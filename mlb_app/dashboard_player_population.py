"""Canonical player identity and active-population service for My Dashboard.

The service consumes verified source rows, keys only by MLBAM player ID, and
persists the durable player object. It does not create analytical snapshots or
change report routing; those remain later sprint slices.
"""

from __future__ import annotations

import datetime as dt
import os
from collections import defaultdict
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Tuple

import requests
from sqlalchemy import func

from .dashboard_object_models import DashboardPlayer
from .database import BatterAggregate, PitcherAggregate, StatcastEvent
from .lineup_data import MLB_STATS_BASE


DEFAULT_ACTIVE_PLAYER_WINDOW_DAYS = 30
ACTIVE_PLAYER_WINDOW_ENV = "DASHBOARD_ACTIVE_PLAYER_WINDOW_DAYS"
CANONICAL_POPULATION_POLICY_VERSION = "verified_active_roster_v2"
ACTIVE_REASONS = (
    "today_confirmed_or_projected_lineup",
    "recent_confirmed_lineup",
    "recent_tracked_game",
    "active_roster_with_analytics",
    "verified_active_roster",
)


def active_player_window_days(value: Optional[Any] = None) -> int:
    raw = value if value is not None else os.getenv(ACTIVE_PLAYER_WINDOW_ENV, DEFAULT_ACTIVE_PLAYER_WINDOW_DAYS)
    try:
        return max(1, int(raw))
    except (TypeError, ValueError):
        return DEFAULT_ACTIVE_PLAYER_WINDOW_DAYS


def _safe_int(value: Any) -> Optional[int]:
    try:
        parsed = int(value)
        return parsed if parsed > 0 else None
    except (TypeError, ValueError):
        return None


def _safe_date(value: Any) -> Optional[dt.date]:
    if isinstance(value, dt.datetime):
        return value.date()
    if isinstance(value, dt.date):
        return value
    if value in (None, ""):
        return None
    try:
        return dt.date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _person(row: Dict[str, Any]) -> Dict[str, Any]:
    return row.get("person") if isinstance(row.get("person"), dict) else {}


def canonical_player_id(row: Dict[str, Any]) -> Optional[int]:
    """Resolve only explicit MLB IDs; never use a name-derived identity."""

    person = _person(row)
    for key in ("mlb_player_id", "player_id", "batter_id", "pitcher_id", "person_id", "id"):
        value = _safe_int(row.get(key))
        if value is not None:
            return value
    return _safe_int(person.get("id"))


def canonical_player_name(row: Dict[str, Any]) -> Optional[str]:
    person = _person(row)
    for value in (
        row.get("full_name"),
        row.get("fullName"),
        row.get("player_name"),
        row.get("batter_name"),
        row.get("pitcher_name"),
        row.get("name"),
        person.get("fullName"),
    ):
        normalized = str(value or "").strip()
        if normalized:
            return normalized
    return None


def normalize_source_player(
    row: Dict[str, Any],
    *,
    source: str,
    player_type: Optional[str] = None,
    observed_date: Optional[dt.date] = None,
    team_id: Optional[int] = None,
    team_name: Optional[str] = None,
) -> Dict[str, Any]:
    position = row.get("primaryPosition") or row.get("position") or {}
    if not isinstance(position, dict):
        position = {"abbreviation": position}
    resolved_type = str(player_type or row.get("player_type") or "").strip().lower()
    if not resolved_type:
        resolved_type = "pitcher" if str(position.get("type") or "").lower() == "pitcher" else "hitter"
    player_id = canonical_player_id(row)
    full_name = canonical_player_name(row)
    return {
        "mlb_player_id": player_id,
        "full_name": full_name,
        "player_type": resolved_type,
        "team_id": _safe_int(row.get("team_id") or team_id),
        "team_name": str(row.get("team_name") or team_name or "").strip() or None,
        "primary_position": str(position.get("abbreviation") or position.get("code") or "").strip() or None,
        "bats": str((row.get("batSide") or {}).get("code") or row.get("bats") or "").strip() or None,
        "throws": str((row.get("pitchHand") or {}).get("code") or row.get("throws") or "").strip() or None,
        "source": source,
        "observed_date": observed_date,
        "identity_resolution_status": "resolved" if player_id and full_name else "missing_mlb_id" if not player_id else "missing_name",
    }


def evaluate_active_player(candidate: Dict[str, Any], *, as_of: dt.date, window_days: int) -> Tuple[bool, str]:
    cutoff = as_of - dt.timedelta(days=window_days - 1)
    lineup_date = _safe_date(candidate.get("most_recent_lineup_date"))
    game_date = _safe_date(candidate.get("most_recent_game_date"))
    if candidate.get("appears_today_lineup"):
        return True, ACTIVE_REASONS[0]
    if lineup_date and cutoff <= lineup_date <= as_of:
        return True, ACTIVE_REASONS[1]
    if game_date and cutoff <= game_date <= as_of:
        return True, ACTIVE_REASONS[2]
    if candidate.get("on_active_roster"):
        reason_index = 3 if candidate.get("has_usable_analytics") else 4
        return True, ACTIVE_REASONS[reason_index]
    return False, "no_recent_verified_activity"


def _safe_nonnegative_int(
    value: Any,
) -> Optional[int]:
    if value in (None, "") or isinstance(
        value,
        bool,
    ):
        return None

    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None

    return parsed if parsed >= 0 else None


def _season_pitching_usage(
    row: Dict[str, Any],
) -> Dict[str, Optional[int]]:
    person = _person(row)

    for stat_group in person.get("stats") or []:
        if not isinstance(stat_group, dict):
            continue

        for split in stat_group.get("splits") or []:
            if not isinstance(split, dict):
                continue

            stat = split.get("stat")

            if not isinstance(stat, dict):
                continue

            raw_games_pitched = stat.get(
                "gamesPitched"
            )

            if raw_games_pitched is None:
                raw_games_pitched = stat.get(
                    "gamesPlayed"
                )

            games_pitched = (
                _safe_nonnegative_int(
                    raw_games_pitched
                )
            )
            games_started = (
                _safe_nonnegative_int(
                    stat.get("gamesStarted")
                )
            )

            if (
                games_pitched is None
                or games_pitched <= 0
                or games_started is None
                or games_started > games_pitched
            ):
                continue

            return {
                "season_games_pitched":
                    games_pitched,
                "season_games_started":
                    games_started,
                "season_relief_appearances": max(
                    games_pitched - games_started,
                    0,
                ),
            }

    return {
        "season_games_pitched": None,
        "season_games_started": None,
        "season_relief_appearances": None,
    }


def fetch_active_roster(
    team_id: int,
    season: int,
    *,
    team_name: Optional[str] = None,
    request_get: Callable[..., Any] = requests.get,
) -> List[Dict[str, Any]]:
    """Read the same verified MLB active-roster source used by the app."""

    response = request_get(
        f"{MLB_STATS_BASE}/teams/{int(team_id)}/roster",
        params={
            "rosterType": "active",
            "season": int(season),
            "hydrate": (
                "person("
                "stats(type=season,group=pitching)"
                ")"
            ),
        },
        timeout=20,
    )
    response.raise_for_status()
    records: List[Dict[str, Any]] = []
    for row in response.json().get("roster", []):
        normalized = normalize_source_player(
            row,
            source="mlb_stats_active_roster",
            team_id=team_id,
            team_name=team_name,
        )
        normalized["on_active_roster"] = True
        normalized.update(
            _season_pitching_usage(row)
        )
        normalized[
            "season_pitching_usage_source"
        ] = (
            "mlb_stats_active_roster_"
            "season_pitching"
            if normalized[
                "season_games_pitched"
            ] is not None
            else None
        )
        records.append(normalized)
    return records


def fetch_confirmed_lineup_players(
    session: Any,
    target_date: dt.date,
    *,
    matchup_builder: Optional[Callable[..., Any]] = None,
    lineup_fetcher: Optional[Callable[[int], Dict[str, List[Dict[str, Any]]]]] = None,
) -> Dict[str, Any]:
    if matchup_builder is None:
        from .matchup_generator import generate_matchups_for_date

        matchup_builder = generate_matchups_for_date
    if lineup_fetcher is None:
        from .lineup_profile import fetch_boxscore_lineup

        lineup_fetcher = fetch_boxscore_lineup
    players: List[Dict[str, Any]] = []
    unresolved: List[Dict[str, Any]] = []
    errors: List[Dict[str, Any]] = []
    matchups = matchup_builder(session, target_date.isoformat()) or []
    for matchup in matchups:
        game_pk = _safe_int(matchup.get("game_pk"))
        if game_pk is None:
            errors.append({"reason": "missing_game_pk"})
            continue
        try:
            lineups = lineup_fetcher(game_pk) or {}
        except Exception as exc:
            errors.append({"game_pk": game_pk, "reason": "lineup_fetch_failed", "error": str(exc)})
            continue
        for side in ("away", "home"):
            for raw in lineups.get(side) or []:
                normalized = normalize_source_player(
                    raw,
                    source="mlb_boxscore_confirmed_lineup",
                    player_type="hitter",
                    observed_date=target_date,
                    team_id=_safe_int(matchup.get(f"{side}_team_id")),
                    team_name=matchup.get(f"{side}_team_name"),
                )
                normalized.update({"confirmed_lineup": True, "appears_today_lineup": target_date == dt.date.today(), "game_pk": game_pk})
                (players if normalized["identity_resolution_status"] == "resolved" else unresolved).append(normalized)
    return {"players": players, "unresolved_identities": unresolved, "errors": errors, "source": "mlb_boxscore_confirmed_lineup"}


def tracked_game_players(session: Any, *, as_of: dt.date, window_days: int) -> List[Dict[str, Any]]:
    cutoff = as_of - dt.timedelta(days=window_days - 1)
    output: List[Dict[str, Any]] = []
    for id_column, player_type in ((StatcastEvent.batter_id, "hitter"), (StatcastEvent.pitcher_id, "pitcher")):
        rows = (
            session.query(
                id_column.label("player_id"),
                func.min(StatcastEvent.game_date).label("first_date"),
                func.max(StatcastEvent.game_date).label("last_date"),
                func.count(func.distinct(StatcastEvent.game_pk)).label("game_count"),
            )
            .filter(StatcastEvent.game_date >= cutoff, StatcastEvent.game_date <= as_of, id_column.isnot(None), id_column != 0)
            .group_by(id_column)
            .all()
        )
        output.extend(
            {
                "mlb_player_id": int(row.player_id),
                "full_name": None,
                "player_type": player_type,
                "source": "statcast_tracked_game",
                "most_recent_game_date": row.last_date,
                "first_tracked_date": row.first_date,
                "tracked_game_count": int(row.game_count or 0),
                "identity_resolution_status": "missing_name",
            }
            for row in rows
        )
    return output


def usable_analytics_ids(session: Any) -> Dict[str, set[int]]:
    hitters = {int(row[0]) for row in session.query(BatterAggregate.batter_id).distinct().all() if row[0]}
    pitchers = {int(row[0]) for row in session.query(PitcherAggregate.pitcher_id).distinct().all() if row[0]}
    return {"hitter": hitters, "pitcher": pitchers}


def _merge_candidate(target: Dict[str, Any], source: Dict[str, Any], as_of: dt.date) -> None:
    source_name = source.get("source")
    if source_name:
        target["sources"].add(str(source_name))
    for key in ("full_name", "team_id", "team_name", "primary_position", "bats", "throws"):
        if source.get(key) not in (None, ""):
            target[key] = source[key]
    if source.get("player_type") in {"hitter", "pitcher"}:
        target["player_type"] = source["player_type"]
    observed = _safe_date(source.get("observed_date"))
    if source.get("confirmed_lineup") and observed:
        target.setdefault("lineup_dates", set()).add(observed)
        target["most_recent_lineup_date"] = max(filter(None, [target.get("most_recent_lineup_date"), observed]))
        target["lineup_appearance_count"] = max(target.get("lineup_appearance_count", 0), len(target["lineup_dates"]))
    game_date = _safe_date(source.get("most_recent_game_date"))
    if game_date:
        target["most_recent_game_date"] = max(filter(None, [target.get("most_recent_game_date"), game_date]))
    first_date = _safe_date(source.get("first_tracked_date")) or observed
    if first_date:
        target["first_tracked_date"] = min(filter(None, [target.get("first_tracked_date"), first_date]))
        target["last_tracked_date"] = max(filter(None, [target.get("last_tracked_date"), game_date or observed or first_date]))
    target["tracked_game_count"] = max(target.get("tracked_game_count", 0), int(source.get("tracked_game_count") or 0))
    target["on_active_roster"] = bool(target.get("on_active_roster") or source.get("on_active_roster"))
    target["appears_today_lineup"] = bool(target.get("appears_today_lineup") or source.get("appears_today_lineup") or (source.get("projected_lineup") and observed == as_of))


def populate_dashboard_players(
    session: Any,
    *,
    as_of: dt.date,
    lineup_rows: Sequence[Dict[str, Any]] = (),
    roster_rows: Sequence[Dict[str, Any]] = (),
    projected_lineup_rows: Sequence[Dict[str, Any]] = (),
    window_days: Optional[int] = None,
    transition_missing_players: bool = False,
) -> Dict[str, Any]:
    window = active_player_window_days(window_days)
    analytics = usable_analytics_ids(session)
    existing = {row.mlb_player_id: row for row in session.query(DashboardPlayer).all()}
    candidates: Dict[int, Dict[str, Any]] = defaultdict(lambda: {"sources": set(), "lineup_appearance_count": 0, "tracked_game_count": 0})
    unresolved: List[Dict[str, Any]] = []
    source_rows = [*lineup_rows, *roster_rows, *projected_lineup_rows, *tracked_game_players(session, as_of=as_of, window_days=window)]

    for raw in source_rows:
        player_id = canonical_player_id(raw)
        if player_id is None:
            unresolved.append({"source": raw.get("source"), "reason": "missing_mlb_id", "name": canonical_player_name(raw)})
            continue
        candidate = candidates[player_id]
        candidate["mlb_player_id"] = player_id
        _merge_candidate(candidate, raw, as_of)

    created = updated = activated = deactivated = 0
    processed_ids: set[int] = set()
    for player_id, candidate in candidates.items():
        current = existing.get(player_id)
        if current and not candidate.get("full_name"):
            candidate["full_name"] = current.full_name
        if current and not candidate.get("player_type"):
            candidate["player_type"] = current.player_type
        if current:
            candidate["most_recent_lineup_date"] = max(
                filter(None, [candidate.get("most_recent_lineup_date"), current.most_recent_lineup_date]),
                default=None,
            )
            candidate["most_recent_game_date"] = max(
                filter(None, [candidate.get("most_recent_game_date"), current.most_recent_game_date]),
                default=None,
            )
            candidate["lineup_appearance_count"] = max(candidate.get("lineup_appearance_count", 0), current.lineup_appearance_count)
            candidate["tracked_game_count"] = max(candidate.get("tracked_game_count", 0), current.tracked_game_count)
            candidate["sources"].update((current.source_provenance_json or {}).get("sources") or [])
        if not candidate.get("full_name"):
            unresolved.append({"mlb_player_id": player_id, "source": sorted(candidate["sources"]), "reason": "missing_name"})
            continue
        player_type = candidate.get("player_type") or "hitter"
        candidate["has_usable_analytics"] = player_id in analytics.get(player_type, set())
        is_active, reason = evaluate_active_player(candidate, as_of=as_of, window_days=window)
        first_tracked = candidate.get("first_tracked_date") or (current.first_tracked_date if current else as_of)
        last_tracked = candidate.get("last_tracked_date") or (current.last_tracked_date if current else as_of)
        values = {
            "full_name": candidate["full_name"],
            "current_team_id": candidate.get("team_id"),
            "current_team_name": candidate.get("team_name"),
            "primary_position": candidate.get("primary_position"),
            "player_type": player_type,
            "bats": candidate.get("bats"),
            "throws": candidate.get("throws"),
            "is_active": is_active,
            "active_status_reason": reason,
            "first_tracked_date": min(filter(None, [first_tracked, current.first_tracked_date if current else None])),
            "last_tracked_date": max(filter(None, [last_tracked, current.last_tracked_date if current else None])),
            "most_recent_lineup_date": candidate.get("most_recent_lineup_date"),
            "most_recent_game_date": candidate.get("most_recent_game_date"),
            "lineup_appearance_count": max(candidate.get("lineup_appearance_count", 0), current.lineup_appearance_count if current else 0),
            "tracked_game_count": max(candidate.get("tracked_game_count", 0), current.tracked_game_count if current else 0),
            "source_provenance_json": {"sources": sorted(candidate["sources"]), "evaluated_as_of": as_of.isoformat(), "active_player_window_days": window, "population_policy_version": CANONICAL_POPULATION_POLICY_VERSION},
            "identity_resolution_status": "resolved",
            "updated_at": dt.datetime.utcnow(),
        }
        if current is None:
            session.add(DashboardPlayer(mlb_player_id=player_id, created_at=dt.datetime.utcnow(), **values))
            created += 1
            activated += int(is_active)
        else:
            was_active = current.is_active
            for key, value in values.items():
                setattr(current, key, value)
            updated += 1
            activated += int(not was_active and is_active)
            deactivated += int(was_active and not is_active)
        processed_ids.add(player_id)

    if transition_missing_players:
        for player_id, current in existing.items():
            if player_id in processed_ids or not current.is_active:
                continue
            current.is_active = False
            current.active_status_reason = "not_observed_in_complete_refresh"
            current.updated_at = dt.datetime.utcnow()
            deactivated += 1
            updated += 1

    session.commit()
    return {
        "as_of": as_of.isoformat(),
        "active_player_window_days": window,
        "source_row_count": len(source_rows),
        "resolved_candidate_count": len(processed_ids),
        "unresolved_identity_count": len(unresolved),
        "unresolved_identities": unresolved,
        "created_count": created,
        "updated_count": updated,
        "activated_count": activated,
        "deactivated_count": deactivated,
        "active_hitter_count": session.query(DashboardPlayer).filter(DashboardPlayer.is_active.is_(True), DashboardPlayer.player_type == "hitter").count(),
        "active_pitcher_count": session.query(DashboardPlayer).filter(DashboardPlayer.is_active.is_(True), DashboardPlayer.player_type == "pitcher").count(),
    }

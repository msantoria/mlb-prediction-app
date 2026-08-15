"""Bounded MLB source for historical pitcher-role evidence."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import datetime as dt
from typing import Any, Callable, Mapping, MutableMapping, Sequence

import requests

from mlb_app.simulation.projections.pitcher_appearance_history import (
    materialize_canonical_pitcher_appearance_history,
)
from mlb_app.simulation.projections.pitcher_typical_role_evidence import (
    materialize_canonical_pitcher_role_evidence,
)


SCHEMA_VERSION = (
    "canonical_pitcher_role_evidence_source_v1"
)
MLB_STATS_BASE = "https://statsapi.mlb.com/api/v1"
MLB_LIVE_FEED_BASE = (
    "https://statsapi.mlb.com/api/v1.1/game"
)
DEFAULT_LOOKBACK_DAYS = 60
DEFAULT_MAXIMUM_FINAL_GAMES = 15
FINAL_STATES = frozenset({
    "final",
    "game over",
    "completed early",
})


def _identifier(value: Any) -> str | None:
    if value in (None, "") or isinstance(value, bool):
        return None

    normalized = str(value).strip()
    return normalized or None


def _date(value: Any) -> dt.date | None:
    if isinstance(value, dt.datetime):
        return value.date()

    if isinstance(value, dt.date):
        return value

    if value in (None, ""):
        return None

    try:
        return dt.datetime.fromisoformat(
            str(value).replace("Z", "+00:00")
        ).date()
    except (TypeError, ValueError):
        try:
            return dt.date.fromisoformat(str(value))
        except (TypeError, ValueError):
            return None


def _positive_int(
    value: Any,
    *,
    name: str,
) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{name} must be positive")

    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"{name} must be positive"
        ) from exc

    if parsed <= 0:
        raise ValueError(f"{name} must be positive")

    return parsed


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _json_response(
    request_get: Callable[..., Any],
    url: str,
    *,
    params: Mapping[str, Any] | None = None,
    timeout: int,
) -> Mapping[str, Any]:
    response = request_get(
        url,
        params=dict(params or {}),
        timeout=timeout,
    )
    response.raise_for_status()
    payload = response.json()

    if not isinstance(payload, Mapping):
        raise TypeError(
            "MLB response payload must be a mapping"
        )

    return payload


def _final_game_records(
    schedule_payload: Mapping[str, Any],
    *,
    as_of_date: dt.date,
) -> list[dict[str, Any]]:
    records = []

    for date_record in schedule_payload.get(
        "dates",
        (),
    ):
        if not isinstance(date_record, Mapping):
            continue

        for game in date_record.get("games", ()):
            if not isinstance(game, Mapping):
                continue

            game_pk = _identifier(
                game.get("gamePk")
                or game.get("game_pk")
            )

            if game_pk is None:
                continue

            game_date = _date(
                game.get("officialDate")
                or game.get("gameDate")
                or date_record.get("date")
            )

            if (
                game_date is None
                or game_date >= as_of_date
            ):
                continue

            status = _mapping(game.get("status"))
            detailed_state = str(
                status.get("detailedState")
                or status.get("abstractGameState")
                or ""
            ).strip().lower()

            if detailed_state not in FINAL_STATES:
                continue

            records.append({
                "game_pk": game_pk,
                "game_date": game_date,
            })

    records.sort(
        key=lambda row: (
            row["game_date"],
            int(row["game_pk"])
            if row["game_pk"].isdigit()
            else row["game_pk"],
        )
    )

    return records


@dataclass(frozen=True)
class CanonicalPitcherRoleEvidenceSourceResult:
    team_id: str
    season: int
    as_of_date: str
    status: str
    appearance_history: Mapping[str, Any]
    role_evidence: Mapping[str, Any]
    diagnostics: Mapping[str, Any]

    def to_diagnostics(self) -> dict[str, Any]:
        return deepcopy(dict(self.diagnostics))


def fetch_canonical_pitcher_role_evidence_source(
    *,
    team_id: Any,
    season: Any,
    as_of: Any,
    active_roster_records: Any,
    request_get: Callable[..., Any] = requests.get,
    lookback_days: int = DEFAULT_LOOKBACK_DAYS,
    maximum_final_games: int = (
        DEFAULT_MAXIMUM_FINAL_GAMES
    ),
    timeout_seconds: int = 20,
    cache: MutableMapping[Any, Any] | None = None,
) -> CanonicalPitcherRoleEvidenceSourceResult:
    """
    Fetch bounded historical evidence once per team/date.

    This source classifies historical typical roles only. It never
    claims today's opener, bulk follower, or other planned assignment.
    """

    normalized_team_id = _identifier(team_id)

    if normalized_team_id is None:
        raise ValueError("team_id is required")

    normalized_season = _positive_int(
        season,
        name="season",
    )
    normalized_as_of = _date(as_of)

    if normalized_as_of is None:
        raise ValueError("as_of must be a valid date")

    normalized_lookback = _positive_int(
        lookback_days,
        name="lookback_days",
    )
    normalized_maximum = _positive_int(
        maximum_final_games,
        name="maximum_final_games",
    )
    normalized_timeout = _positive_int(
        timeout_seconds,
        name="timeout_seconds",
    )

    if (
        not isinstance(active_roster_records, Sequence)
        or isinstance(
            active_roster_records,
            (str, bytes),
        )
    ):
        raise TypeError(
            "active_roster_records must be a sequence"
        )

    if (
        cache is not None
        and not isinstance(cache, MutableMapping)
    ):
        raise TypeError(
            "cache must be a mutable mapping"
        )

    cache_key = (
        SCHEMA_VERSION,
        normalized_team_id,
        normalized_season,
        normalized_as_of.isoformat(),
        normalized_lookback,
        normalized_maximum,
    )

    if cache is not None and cache_key in cache:
        return deepcopy(cache[cache_key])

    start_date = (
        normalized_as_of
        - dt.timedelta(days=normalized_lookback)
    )
    schedule_error = None
    schedule_payload: Mapping[str, Any] = {}

    try:
        schedule_payload = _json_response(
            request_get,
            f"{MLB_STATS_BASE}/schedule",
            params={
                "sportId": 1,
                "teamId": normalized_team_id,
                "season": normalized_season,
                "startDate": start_date.isoformat(),
                "endDate": normalized_as_of.isoformat(),
                "gameType": "R",
            },
            timeout=normalized_timeout,
        )
    except Exception as exc:
        schedule_error = {
            "error_type": exc.__class__.__name__,
            "error_message": str(exc),
        }

    final_games = _final_game_records(
        schedule_payload,
        as_of_date=normalized_as_of,
    )[-normalized_maximum:]

    feeds = []
    feed_errors = []

    for game in final_games:
        try:
            feed = _json_response(
                request_get,
                (
                    f"{MLB_LIVE_FEED_BASE}/"
                    f"{game['game_pk']}/feed/live"
                ),
                timeout=normalized_timeout,
            )
        except Exception as exc:
            feed_errors.append({
                "game_pk": game["game_pk"],
                "error_type":
                    exc.__class__.__name__,
                "error_message": str(exc),
            })
            continue

        feeds.append(feed)

    appearance_history = (
        materialize_canonical_pitcher_appearance_history(
            team_id=normalized_team_id,
            game_feeds=feeds,
        )
    )
    role_evidence = (
        materialize_canonical_pitcher_role_evidence(
            active_roster_records=(
                active_roster_records
            ),
            historical_appearance_evidence_by_pitcher_id=(
                appearance_history.get(
                    "evidence_by_pitcher_id",
                    {},
                )
            ),
        )
    )

    if schedule_error is not None:
        status = "unavailable"
    elif not final_games:
        status = "unavailable"
    elif feed_errors and not feeds:
        status = "unavailable"
    elif feed_errors:
        status = "partial"
    else:
        status = "materialized"

    diagnostics = {
        "schema_version": SCHEMA_VERSION,
        "status": status,
        "team_id": normalized_team_id,
        "season": normalized_season,
        "as_of_date":
            normalized_as_of.isoformat(),
        "lookback_days": normalized_lookback,
        "maximum_final_games":
            normalized_maximum,
        "scheduled_final_game_count":
            len(final_games),
        "fetched_final_game_count": len(feeds),
        "feed_error_count": len(feed_errors),
        "feed_errors": deepcopy(feed_errors),
        "schedule_error":
            deepcopy(schedule_error),
        "historical_pitcher_count":
            appearance_history.get(
                "pitcher_count",
                0,
            ),
        "resolved_typical_role_count":
            role_evidence.get(
                "resolved_typical_role_count",
                0,
            ),
        "detected_opener_bulk_pair_count":
            appearance_history.get(
                "detected_opener_bulk_pair_count",
                0,
            ),
        "cache_key_uses_team_and_date": True,
        "bounded_game_fetch": True,
        "simulation_trial_fetches_performed": 0,
        "planned_role_claimed": False,
        "future_assignment_inferred": False,
        "news_keyword_inference_used": False,
        "database_writes_performed": False,
        "production_authority_changed": False,
    }

    result = CanonicalPitcherRoleEvidenceSourceResult(
        team_id=normalized_team_id,
        season=normalized_season,
        as_of_date=normalized_as_of.isoformat(),
        status=status,
        appearance_history=deepcopy(
            appearance_history
        ),
        role_evidence=deepcopy(role_evidence),
        diagnostics=diagnostics,
    )

    if cache is not None:
        cache[cache_key] = deepcopy(result)

    return result

"""
ETL pipeline for the MLB prediction app.

Pulls schedule, Statcast events, pitch arsenal, team splits, and player splits
from Baseball Savant / MLB Stats API and loads them into the database.

Usage:
    python -m mlb_app.etl --date 2026-04-15
    python -m mlb_app.etl --backfill-days 30
"""

from __future__ import annotations

import argparse
import logging
import os
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd
import requests
from dotenv import load_dotenv
from sqlalchemy import and_, func, or_

from .database import (
    get_engine,
    create_tables,
    get_session,
    StatcastEvent,
    PitchArsenal,
    PitcherAggregate,
    BatterAggregate,
    TeamSplit,
    PlayerSplit,
)
from .statsapi_cache import fetch_json_with_cache, make_cache_key
from .statcast_utils import (
    fetch_statcast_pitcher_data,
    fetch_statcast_batter_data,
    fetch_statcast_all_events,
    fetch_pitch_arsenal_leaderboard,
    calculate_pitcher_aggregates,
    calculate_batter_aggregates,
    build_pitch_arsenal_from_statcast,
)
from .statcast_event_identity import load_canonical_statcast_events

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///mlb.db")
MLB_STATS_BASE = "https://statsapi.mlb.com/api/v1"


# ---------------------------------------------------------------------------
# Schedule helpers
# ---------------------------------------------------------------------------

def fetch_schedule(date_str: str) -> List[dict]:
    """Return list of game dicts for a date, including probable pitcher IDs."""
    url = f"{MLB_STATS_BASE}/schedule"
    params = {"sportId": 1, "date": date_str, "hydrate": "probablePitcher,team,linescore,weather"}
    payload = fetch_json_with_cache(
        url,
        params=params,
        cache_key=make_cache_key("schedule", date_str, params),
        timeout=30,
    )
    games = []
    for day in payload.get("dates", []):
        for game in day.get("games", []):
            teams = game.get("teams", {})
            teams["_game_pk"] = game.get("gamePk")
            teams["_game_date"] = game.get("gameDate")
            teams["_venue"] = game.get("venue", {}).get("name")
            teams["_status"] = game.get("status", {}).get("detailedState")
            teams["_weather"] = game.get("weather")
            games.append(teams)
    return games


def _extract_pitcher_ids(games: List[dict]) -> List[int]:
    ids = []
    for g in games:
        for side in ("home", "away"):
            pid = g.get(side, {}).get("probablePitcher", {}).get("id")
            if pid:
                ids.append(int(pid))
    return list(set(ids))


def _extract_team_ids(games: List[dict]) -> List[int]:
    ids = []
    for g in games:
        for side in ("home", "away"):
            tid = g.get(side, {}).get("team", {}).get("id")
            if tid:
                ids.append(int(tid))
    return list(set(ids))


# ---------------------------------------------------------------------------
# Team / player splits
# ---------------------------------------------------------------------------

def _fetch_team_split(team_id: int, season: int, split_code: str) -> Optional[dict]:
    url = f"{MLB_STATS_BASE}/teams/{team_id}/stats"
    params = {"stats": "statSplits", "group": "hitting", "season": season, "sitCodes": split_code}
    try:
        resp = requests.get(url, params=params, timeout=20)
        resp.raise_for_status()
        stats = resp.json().get("stats", [])
        splits = stats[0].get("splits", []) if stats else []
        return splits[0].get("stat", {}) if splits else None
    except Exception as e:
        log.warning("Team split fetch failed team=%s split=%s: %s", team_id, split_code, e)
        return None


def _load_team_splits(session, team_ids: List[int], season: int) -> None:
    for team_id in team_ids:
        for split_code, split_label in [("vl", "vsL"), ("vr", "vsR")]:
            stat = _fetch_team_split(team_id, season, split_code)
            if not stat:
                continue
            existing = session.query(TeamSplit).filter_by(
                team_id=team_id, season=season, split=split_label
            ).first()
            if existing:
                target = existing
            else:
                target = TeamSplit(season=season, team_id=team_id, split=split_label)
                session.add(target)
            pa = stat.get("plateAppearances") or 0
            k = stat.get("strikeOuts") or 0
            bb = stat.get("baseOnBalls") or 0
            target.pa = pa
            target.hits = stat.get("hits")
            target.doubles = stat.get("doubles")
            target.triples = stat.get("triples")
            target.home_runs = stat.get("homeRuns")
            target.walks = bb
            target.strikeouts = k
            target.batting_avg = _safe_float(stat.get("avg"))
            target.on_base_pct = _safe_float(stat.get("obp"))
            target.slugging_pct = _safe_float(stat.get("slg"))
            target.iso = _safe_float(stat.get("ops"))
            target.k_pct = round(k / pa, 3) if pa > 0 else None
            target.bb_pct = round(bb / pa, 3) if pa > 0 else None
    session.commit()
    log.info("Team splits loaded for %d teams", len(team_ids))


# ---------------------------------------------------------------------------
# Statcast + aggregates
# ---------------------------------------------------------------------------

def _safe_int(val) -> Optional[int]:
    try:
        if pd.isna(val):
            return None
        return int(val)
    except (TypeError, ValueError):
        return None


def _safe_str(val, max_len: int) -> Optional[str]:
    if val is None or pd.isna(val):
        return None
    text = str(val).strip()
    return text[:max_len] if text else None


def _clean_short_text(value: Any, max_len: int) -> Optional[str]:
    if value is None or pd.isna(value):
        return None
    text = str(value).strip()
    if not text or text.lower() in {"nan", "none", "null", "na", "n/a"}:
        return None
    return text[:max_len]


def _row_game_date(row: pd.Series) -> Optional[date]:
    value = row.get("game_date")
    if value is None or pd.isna(value):
        return None
    try:
        return pd.to_datetime(value).date()
    except Exception:
        return None


def _row_pitcher_id(row: pd.Series, fallback_pitcher_id: Optional[int] = None) -> int:
    for key in ("pitcher", "pitcher_id", "player_id"):
        value = _safe_int(row.get(key))
        if value:
            return value
    return int(fallback_pitcher_id or 0)


def _row_batter_id(row: pd.Series) -> int:
    for key in ("batter", "batter_id"):
        value = _safe_int(row.get(key))
        if value:
            return value
    return 0


def _event_values_from_row(row: pd.Series, fallback_pitcher_id: Optional[int] = None) -> Dict[str, Any]:
    return {
        "game_date": _row_game_date(row),
        "game_pk": _safe_int(row.get("game_pk")),
        "at_bat_number": _safe_int(row.get("at_bat_number")),
        "pitch_number": _safe_int(row.get("pitch_number")),
        "inning": _safe_int(row.get("inning")),
        "inning_topbot": _safe_str(row.get("inning_topbot"), 10),
        "outs_when_up": _safe_int(row.get("outs_when_up")),
        "home_team": _safe_str(row.get("home_team"), 10),
        "away_team": _safe_str(row.get("away_team"), 10),
        "pitcher_id": _row_pitcher_id(row, fallback_pitcher_id),
        "batter_id": _row_batter_id(row),
        "pitch_type": _clean_short_text(row.get("pitch_type"), 5),
        "release_speed": _safe_float(row.get("release_speed")),
        "release_spin_rate": _safe_float(row.get("release_spin_rate")),
        "pfx_x": _safe_float(row.get("pfx_x")),
        "pfx_z": _safe_float(row.get("pfx_z")),
        "plate_x": _safe_float(row.get("plate_x")),
        "plate_z": _safe_float(row.get("plate_z")),
        "balls": _safe_int(row.get("balls")),
        "strikes": _safe_int(row.get("strikes")),
        "events": _clean_short_text(row.get("events"), 50),
        "description": _safe_str(row.get("description"), 60),
        "launch_speed": _safe_float(row.get("launch_speed")),
        "launch_angle": _safe_float(row.get("launch_angle")),
        "estimated_woba_using_speedangle": _safe_float(row.get("estimated_woba_using_speedangle")),
        "estimated_ba_using_speedangle": _safe_float(row.get("estimated_ba_using_speedangle")),
        "stand": _clean_short_text(row.get("stand"), 1),
        "p_throws": _clean_short_text(row.get("p_throws"), 1),
    }


def _primary_pitch_identity(values: Dict[str, Any]) -> Optional[Tuple[Any, ...]]:
    required = (
        values.get("game_pk"),
        values.get("at_bat_number"),
        values.get("pitch_number"),
        values.get("pitcher_id"),
        values.get("batter_id"),
    )
    if all(value is not None for value in required):
        return required
    return None


def _find_existing_statcast_event(session, values: Dict[str, Any]) -> Optional[StatcastEvent]:
    primary = _primary_pitch_identity(values)
    if primary is not None:
        game_pk, at_bat_number, pitch_number, pitcher_id, batter_id = primary
        return (
            session.query(StatcastEvent)
            .filter(
                StatcastEvent.game_pk == game_pk,
                StatcastEvent.at_bat_number == at_bat_number,
                StatcastEvent.pitch_number == pitch_number,
                StatcastEvent.pitcher_id == pitcher_id,
                StatcastEvent.batter_id == batter_id,
            )
            .first()
        )

    filters = [
        StatcastEvent.game_date == values.get("game_date"),
        StatcastEvent.pitcher_id == values.get("pitcher_id"),
        StatcastEvent.batter_id == values.get("batter_id"),
        StatcastEvent.pitch_type == values.get("pitch_type"),
        StatcastEvent.events == values.get("events"),
        StatcastEvent.release_speed == values.get("release_speed"),
        StatcastEvent.launch_speed == values.get("launch_speed"),
        StatcastEvent.launch_angle == values.get("launch_angle"),
        StatcastEvent.balls == values.get("balls"),
        StatcastEvent.strikes == values.get("strikes"),
        StatcastEvent.inning == values.get("inning"),
        StatcastEvent.inning_topbot == values.get("inning_topbot"),
        StatcastEvent.outs_when_up == values.get("outs_when_up"),
    ]
    return session.query(StatcastEvent).filter(and_(*filters)).first()


def _upsert_statcast_event(session, values: Dict[str, Any]) -> str:
    if values.get("game_date") is None or not values.get("pitcher_id"):
        return "skipped"

    existing = _find_existing_statcast_event(session, values)
    if existing is None:
        session.add(StatcastEvent(**values))
        return "inserted"

    changed = False
    for key, value in values.items():
        if value is None:
            continue
        if getattr(existing, key, None) != value:
            setattr(existing, key, value)
            changed = True
    return "updated" if changed else "noop"


def _upsert_statcast_dataframe(
    session,
    df: pd.DataFrame,
    fallback_pitcher_id: Optional[int] = None,
    commit_every: int = 1000,
) -> Dict[str, int]:
    stats = {"inserted": 0, "updated": 0, "noop": 0, "skipped": 0, "input_duplicates": 0}
    if df is None or df.empty:
        return stats

    canonical_values: Dict[Tuple[Any, ...], Dict[str, Any]] = {}
    legacy_values: List[Dict[str, Any]] = []
    for _, row in df.iterrows():
        values = _event_values_from_row(row, fallback_pitcher_id)
        primary = _primary_pitch_identity(values)
        if primary is None:
            legacy_values.append(values)
            continue
        existing_values = canonical_values.get(primary)
        if existing_values is None:
            canonical_values[primary] = values
            continue
        stats["input_duplicates"] += 1
        for key, value in values.items():
            if value is not None:
                existing_values[key] = value

    prepared_values = [*canonical_values.values(), *legacy_values]
    for idx, values in enumerate(prepared_values, start=1):
        try:
            status = _upsert_statcast_event(session, values)
            stats[status] = stats.get(status, 0) + 1
        except Exception as exc:
            log.debug("Statcast row upsert skipped: %s", exc)
            stats["skipped"] += 1
        if idx % commit_every == 0:
            session.commit()
    session.commit()
    return stats


def _events_to_statcast_dataframe(events: List[StatcastEvent]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "game_date": e.game_date,
                "game_pk": e.game_pk,
                "at_bat_number": e.at_bat_number,
                "pitch_number": e.pitch_number,
                "inning": e.inning,
                "inning_topbot": e.inning_topbot,
                "outs_when_up": e.outs_when_up,
                "home_team": e.home_team,
                "away_team": e.away_team,
                "pitcher": e.pitcher_id,
                "batter": e.batter_id,
                "pitch_type": e.pitch_type,
                "release_speed": e.release_speed,
                "release_spin_rate": e.release_spin_rate,
                "pfx_x": e.pfx_x,
                "pfx_z": e.pfx_z,
                "plate_x": e.plate_x,
                "plate_z": e.plate_z,
                "balls": e.balls,
                "strikes": e.strikes,
                "events": e.events,
                "description": e.description,
                "launch_speed": e.launch_speed,
                "launch_angle": e.launch_angle,
                "estimated_woba_using_speedangle": e.estimated_woba_using_speedangle,
                "estimated_ba_using_speedangle": e.estimated_ba_using_speedangle,
                "stand": e.stand,
                "p_throws": e.p_throws,
            }
            for e in events
        ]
    )


def _load_statcast_for_pitcher(session, pitcher_id: int, start: str, end: str) -> pd.DataFrame:
    try:
        df = fetch_statcast_pitcher_data(pitcher_id, start, end)
    except Exception as e:
        log.warning("Statcast fetch failed pitcher=%s: %s", pitcher_id, e)
        return pd.DataFrame()
    if df is None or df.empty:
        return pd.DataFrame()

    stats = _upsert_statcast_dataframe(session, df, fallback_pitcher_id=pitcher_id)
    log.info(
        "Statcast events loaded pitcher=%s rows=%d inserted=%d updated=%d noop=%d skipped=%d",
        pitcher_id,
        len(df),
        stats.get("inserted", 0),
        stats.get("updated", 0),
        stats.get("noop", 0),
        stats.get("skipped", 0),
    )
    return df


def refresh_statcast_events_for_date(session, date_str: str) -> Dict[str, Any]:
    """Fetch all pitch-level Statcast rows for one MLB date and upsert them.

    This is the production freshness path. It is intentionally date-wide rather
    than probable-pitcher-only so Batter leaderboards, pitcher game logs,
    relievers, non-probable starters, and H2H fallbacks all see the same base
    event table.
    """
    try:
        df = fetch_statcast_all_events(date_str, date_str)
    except Exception as exc:
        log.warning("Date-wide Statcast fetch failed date=%s: %s", date_str, exc)
        return {
            "date": date_str,
            "source": "datewide_statcast",
            "rows_returned": 0,
            "inserted": 0,
            "updated": 0,
            "noop": 0,
            "skipped": 0,
            "error": str(exc),
        }

    if df is None or df.empty:
        return {
            "date": date_str,
            "source": "datewide_statcast",
            "rows_returned": 0,
            "inserted": 0,
            "updated": 0,
            "noop": 0,
            "skipped": 0,
        }

    stats = _upsert_statcast_dataframe(session, df)
    stats.update({"date": date_str, "source": "datewide_statcast", "rows_returned": int(len(df))})
    return stats


def _query_statcast_events_for_window(
    session,
    *,
    start_date: date,
    end_date: date,
    pitcher_id: Optional[int] = None,
    batter_id: Optional[int] = None,
) -> List[StatcastEvent]:
    filters = [
        StatcastEvent.game_date >= start_date,
        StatcastEvent.game_date <= end_date,
    ]
    if pitcher_id is not None:
        filters.append(StatcastEvent.pitcher_id == pitcher_id)
    if batter_id is not None:
        filters.append(StatcastEvent.batter_id == batter_id)
    events, _ = load_canonical_statcast_events(
        session,
        *filters,
        order_by=(
            StatcastEvent.game_date.asc(),
            StatcastEvent.game_pk.asc(),
            StatcastEvent.at_bat_number.asc(),
            StatcastEvent.pitch_number.asc(),
        ),
    )
    return events


def _load_pitcher_aggregate(session, pitcher_id: int, df: pd.DataFrame, end_date: date) -> None:
    metrics = calculate_pitcher_aggregates(df)
    if not metrics:
        return
    existing = session.query(PitcherAggregate).filter_by(
        pitcher_id=pitcher_id, window="90d", end_date=end_date
    ).first()
    if existing:
        for k, v in metrics.items():
            if hasattr(existing, k):
                setattr(existing, k, v)
    else:
        record = PitcherAggregate(
            pitcher_id=pitcher_id,
            window="90d",
            end_date=end_date,
            **{k: v for k, v in metrics.items() if hasattr(PitcherAggregate, k)},
        )
        session.add(record)
    session.commit()


def _load_batter_aggregate(session, batter_id: int, df: pd.DataFrame, end_date: date) -> None:
    metrics = calculate_batter_aggregates(df)
    if not metrics:
        return
    existing = session.query(BatterAggregate).filter_by(
        batter_id=batter_id, window="90d", end_date=end_date
    ).first()
    if existing:
        for k, v in metrics.items():
            if hasattr(existing, k):
                setattr(existing, k, v)
    else:
        record = BatterAggregate(
            batter_id=batter_id,
            window="90d",
            end_date=end_date,
            **{k: v for k, v in metrics.items() if hasattr(BatterAggregate, k)},
        )
        session.add(record)
    session.commit()


def recompute_recent_aggregates_from_events(
    session,
    *,
    end_date: date,
    window_days: int = 90,
    pitcher_ids: Optional[List[int]] = None,
    batter_ids: Optional[List[int]] = None,
    refresh_pitch_arsenal: bool = True,
) -> Dict[str, int]:
    start_date = end_date - timedelta(days=window_days)

    if pitcher_ids is None:
        pitcher_rows = (
            session.query(StatcastEvent.pitcher_id)
            .filter(
                StatcastEvent.game_date >= start_date,
                StatcastEvent.game_date <= end_date,
                StatcastEvent.pitcher_id.isnot(None),
                StatcastEvent.pitcher_id != 0,
            )
            .distinct()
            .all()
        )
        pitcher_ids = [int(row[0]) for row in pitcher_rows if row[0]]

    if batter_ids is None:
        batter_rows = (
            session.query(StatcastEvent.batter_id)
            .filter(
                StatcastEvent.game_date >= start_date,
                StatcastEvent.game_date <= end_date,
                StatcastEvent.batter_id.isnot(None),
                StatcastEvent.batter_id != 0,
            )
            .distinct()
            .all()
        )
        batter_ids = [int(row[0]) for row in batter_rows if row[0]]

    season = end_date.year
    pitcher_count = 0
    batter_count = 0
    arsenal_count = 0

    for pitcher_id in sorted(set(pitcher_ids)):
        events = _query_statcast_events_for_window(
            session,
            start_date=start_date,
            end_date=end_date,
            pitcher_id=pitcher_id,
        )
        if not events:
            continue
        df = _events_to_statcast_dataframe(events)
        _load_pitcher_aggregate(session, pitcher_id, df, end_date)
        pitcher_count += 1
        if refresh_pitch_arsenal:
            _load_pitch_arsenal_from_df(session, pitcher_id, df, season)
            arsenal_count += 1

    for batter_id in sorted(set(batter_ids)):
        events = _query_statcast_events_for_window(
            session,
            start_date=start_date,
            end_date=end_date,
            batter_id=batter_id,
        )
        if not events:
            continue
        df = _events_to_statcast_dataframe(events)
        _load_batter_aggregate(session, batter_id, df, end_date)
        batter_count += 1

    return {
        "pitcher_aggregates_refreshed": pitcher_count,
        "batter_aggregates_refreshed": batter_count,
        "pitch_arsenal_pitchers_refreshed": arsenal_count,
    }


def _load_pitch_arsenal_from_df(session, pitcher_id: int, df: pd.DataFrame, season: int) -> None:
    records = build_pitch_arsenal_from_statcast(df, pitcher_id, season)
    for rec in records:
        existing = session.query(PitchArsenal).filter_by(
            pitcher_id=pitcher_id, season=season, pitch_type=rec["pitch_type"]
        ).first()
        if existing:
            for k, v in rec.items():
                if hasattr(existing, k):
                    setattr(existing, k, v)
        else:
            session.add(PitchArsenal(**rec))
    session.commit()


def _try_load_arsenal_leaderboard(session, season: int) -> bool:
    """Try loading pitch arsenal from the Savant leaderboard. Returns True on success."""
    try:
        df = fetch_pitch_arsenal_leaderboard(season)
        if df is None or df.empty:
            return False
        col_map = {
            "pitcher": "pitcher_id",
            "player_id": "pitcher_id",
            "mlbam_id": "pitcher_id",
            "pitch_type": "pitch_type",
            "pitch_name": "pitch_name",
            "pitches": "pitch_count",
            "pitch_usage": "usage_pct",
            "whiff_percent": "whiff_pct",
            "k_percent": "strikeout_pct",
            "run_value_per_100": "rv_per_100",
            "est_woba": "xwoba",
            "hard_hit_percent": "hard_hit_pct",
        }
        df = df.rename(columns={k: v for k, v in col_map.items() if k in df.columns})
        if "pitcher_id" not in df.columns:
            return False
        for _, row in df.iterrows():
            pitcher_id = int(row["pitcher_id"])
            pitch_type = str(row.get("pitch_type", "") or "")[:5]
            if not pitch_type:
                continue
            existing = session.query(PitchArsenal).filter_by(
                pitcher_id=pitcher_id, season=season, pitch_type=pitch_type
            ).first()
            if existing:
                for field in ("pitch_name", "pitch_count", "usage_pct", "whiff_pct", "strikeout_pct", "rv_per_100", "xwoba", "hard_hit_pct"):
                    if hasattr(existing, field):
                        setattr(existing, field, _pitch_arsenal_value_from_row(row, field))
                continue
            session.add(PitchArsenal(
                season=season,
                pitcher_id=pitcher_id,
                pitch_type=pitch_type,
                pitch_name=str(row.get("pitch_name", "") or ""),
                pitch_count=int(row["pitch_count"]) if pd.notna(row.get("pitch_count")) else None,
                usage_pct=_safe_float(row.get("usage_pct")),
                whiff_pct=_safe_float(row.get("whiff_pct")),
                strikeout_pct=_safe_float(row.get("strikeout_pct")),
                rv_per_100=_safe_float(row.get("rv_per_100")),
                xwoba=_safe_float(row.get("xwoba")),
                hard_hit_pct=_safe_float(row.get("hard_hit_pct")),
            ))
        session.commit()
        log.info("Arsenal leaderboard loaded for season=%d rows=%d", season, len(df))
        return True
    except Exception as e:
        log.warning("Arsenal leaderboard failed: %s", e)
        return False


def _pitch_arsenal_value_from_row(row: pd.Series, field: str) -> Any:
    if field == "pitch_name":
        return str(row.get("pitch_name", "") or "")
    if field == "pitch_count":
        return int(row["pitch_count"]) if pd.notna(row.get("pitch_count")) else None
    return _safe_float(row.get(field))


# ---------------------------------------------------------------------------
# Main ETL orchestration
# ---------------------------------------------------------------------------

def run_etl_for_date(date_str: str, *, datewide_statcast: bool = True) -> Dict[str, Any]:
    engine = get_engine(os.getenv("DATABASE_URL", DATABASE_URL))
    create_tables(engine)
    Session = get_session(engine)

    with Session() as session:
        log.info("ETL started for %s", date_str)
        games = fetch_schedule(date_str)
        if not games:
            log.info("No games found for %s", date_str)
            return {"date": date_str, "status": "no_games", "statcast_refresh": None}

        pitcher_ids = _extract_pitcher_ids(games)
        team_ids = _extract_team_ids(games)
        season = int(date_str[:4])
        end_dt = datetime.strptime(date_str, "%Y-%m-%d").date()
        start_dt = (end_dt - timedelta(days=90)).isoformat()

        log.info("Found %d probable pitchers, %d teams", len(pitcher_ids), len(team_ids))

        _load_team_splits(session, team_ids, season)

        statcast_refresh = None
        if datewide_statcast:
            statcast_refresh = refresh_statcast_events_for_date(session, date_str)
            log.info("Date-wide Statcast refresh %s", statcast_refresh)

        arsenal_loaded = _try_load_arsenal_leaderboard(session, season)

        aggregate_summary: Dict[str, int] = {
            "pitcher_aggregates_refreshed": 0,
            "batter_aggregates_refreshed": 0,
            "pitch_arsenal_pitchers_refreshed": 0,
        }

        if datewide_statcast:
            date_pitcher_rows = (
                session.query(StatcastEvent.pitcher_id)
                .filter(
                    StatcastEvent.game_date == end_dt,
                    StatcastEvent.pitcher_id.isnot(None),
                    StatcastEvent.pitcher_id != 0,
                )
                .distinct()
                .all()
            )
            date_batter_rows = (
                session.query(StatcastEvent.batter_id)
                .filter(
                    StatcastEvent.game_date == end_dt,
                    StatcastEvent.batter_id.isnot(None),
                    StatcastEvent.batter_id != 0,
                )
                .distinct()
                .all()
            )
            affected_pitcher_ids = [int(row[0]) for row in date_pitcher_rows if row[0]]
            affected_batter_ids = [int(row[0]) for row in date_batter_rows if row[0]]
            aggregate_summary = recompute_recent_aggregates_from_events(
                session,
                end_date=end_dt,
                pitcher_ids=affected_pitcher_ids,
                batter_ids=affected_batter_ids,
                refresh_pitch_arsenal=not arsenal_loaded,
            )
        else:
            for pitcher_id in pitcher_ids:
                df = _load_statcast_for_pitcher(session, pitcher_id, start_dt, date_str)
                _load_pitcher_aggregate(session, pitcher_id, df, end_dt)
                aggregate_summary["pitcher_aggregates_refreshed"] += 1
                if not arsenal_loaded:
                    _load_pitch_arsenal_from_df(session, pitcher_id, df, season)
                    aggregate_summary["pitch_arsenal_pitchers_refreshed"] += 1
                if df.empty:
                    _ensure_historical_aggregate(session, pitcher_id, season)

        log.info("ETL complete for %s", date_str)
        return {
            "date": date_str,
            "status": "ok",
            "probable_pitcher_count": len(pitcher_ids),
            "team_count": len(team_ids),
            "statcast_refresh": statcast_refresh,
            "aggregate_summary": aggregate_summary,
            "arsenal_leaderboard_loaded": arsenal_loaded,
        }


def _ensure_historical_aggregate(session, pitcher_id: int, current_season: int) -> None:
    """Pull prior-season Statcast for pitchers with no data in the current window."""
    existing = session.query(PitcherAggregate).filter(
        PitcherAggregate.pitcher_id == pitcher_id
    ).first()
    if existing:
        return

    for year in [current_season - 1, current_season - 2]:
        start = f"{year}-03-15"
        end = f"{year}-11-01"
        try:
            df = fetch_statcast_pitcher_data(pitcher_id, start, end)
        except Exception as e:
            log.warning("Historical backfill failed pitcher=%s year=%s: %s", pitcher_id, year, e)
            continue
        if df is None or df.empty:
            continue
        metrics = calculate_pitcher_aggregates(df)
        if not metrics:
            continue
        record = PitcherAggregate(
            pitcher_id=pitcher_id,
            window=str(year),
            end_date=date(year, 11, 1),
            **{k: v for k, v in metrics.items() if hasattr(PitcherAggregate, k)},
        )
        session.add(record)
        session.commit()
        _load_pitch_arsenal_from_df(session, pitcher_id, df, year)
        log.info("Backfilled %s season data for pitcher=%s", year, pitcher_id)
        return


def run_backfill(days: int = 30) -> None:
    today = date.today()
    for i in range(days, 0, -1):
        d = (today - timedelta(days=i)).isoformat()
        try:
            run_etl_for_date(d)
        except Exception as e:
            log.error("ETL failed for %s: %s", d, e)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _safe_float(val) -> Optional[float]:
    try:
        f = float(val)
        import math
        return None if math.isnan(f) else f
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="MLB ETL pipeline")
    parser.add_argument("--date", default=date.today().isoformat(), help="YYYY-MM-DD")
    parser.add_argument("--backfill-days", type=int, default=0,
                        help="Backfill this many days before today")
    parser.add_argument("--pitcher-only", action="store_true",
                        help="Use legacy probable-pitcher Statcast pulls instead of date-wide refresh")
    args = parser.parse_args()

    if args.backfill_days > 0:
        run_backfill(args.backfill_days)
    else:
        run_etl_for_date(args.date, datewide_statcast=not args.pitcher_only)

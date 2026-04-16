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
from typing import List, Optional

import pandas as pd
import requests
from dotenv import load_dotenv

from .database import (
    get_engine,
    create_tables,
    get_session,
    AtBatOutcome,
    StatcastEvent,
    PitchArsenal,
    PitcherAggregate,
    BatterAggregate,
    TeamSplit,
    PlayerSplit,
)
from .statcast_utils import (
    fetch_statcast_pitcher_data,
    fetch_statcast_batter_data,
    fetch_pitch_arsenal_leaderboard,
    calculate_pitcher_aggregates,
    calculate_batter_aggregates,
    build_pitch_arsenal_from_statcast,
)

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
    params = {"sportId": 1, "date": date_str, "hydrate": "probablePitcher,team,linescore"}
    resp = requests.get(url, params=params, timeout=30)
    resp.raise_for_status()
    games = []
    for day in resp.json().get("dates", []):
        for game in day.get("games", []):
            teams = game.get("teams", {})
            teams["_game_pk"] = game.get("gamePk")
            teams["_game_date"] = game.get("gameDate")
            teams["_venue"] = game.get("venue", {}).get("name")
            teams["_status"] = game.get("status", {}).get("detailedState")
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
    params = {"stats": "season", "group": "hitting", "season": season, "split": split_code}
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
        for split_code, split_label in [("vsLHP", "vsL"), ("vsRHP", "vsR")]:
            stat = _fetch_team_split(team_id, season, split_code)
            if not stat:
                continue
            existing = session.query(TeamSplit).filter_by(
                team_id=team_id, season=season, split=split_label
            ).first()
            if existing:
                continue
            record = TeamSplit(
                season=season,
                team_id=team_id,
                split=split_label,
                pa=stat.get("plateAppearances"),
                hits=stat.get("hits"),
                doubles=stat.get("doubles"),
                triples=stat.get("triples"),
                home_runs=stat.get("homeRuns"),
                walks=stat.get("baseOnBalls"),
                strikeouts=stat.get("strikeOuts"),
                batting_avg=_safe_float(stat.get("avg")),
                on_base_pct=_safe_float(stat.get("obp")),
                slugging_pct=_safe_float(stat.get("slg")),
                iso=_safe_float(stat.get("ops")),
                k_pct=_safe_float(stat.get("strikeoutRate")),
                bb_pct=_safe_float(stat.get("walkRate")),
            )
            session.add(record)
    session.commit()
    log.info("Team splits loaded for %d teams", len(team_ids))


# ---------------------------------------------------------------------------
# Statcast + aggregates
# ---------------------------------------------------------------------------

def _load_statcast_for_pitcher(session, pitcher_id: int, start: str, end: str) -> pd.DataFrame:
    try:
        df = fetch_statcast_pitcher_data(pitcher_id, start, end)
    except Exception as e:
        log.warning("Statcast fetch failed pitcher=%s: %s", pitcher_id, e)
        return pd.DataFrame()
    if df is None or df.empty:
        return pd.DataFrame()

    # Persist raw events (deduplicate by game_date + pitcher + batter + description)
    for _, row in df.iterrows():
        try:
            ev = StatcastEvent(
                game_date=pd.to_datetime(row.get("game_date")).date() if row.get("game_date") else None,
                pitcher_id=pitcher_id,
                batter_id=int(row["batter"]) if pd.notna(row.get("batter")) else 0,
                pitch_type=str(row.get("pitch_type", "") or "")[:5] or None,
                release_speed=_safe_float(row.get("release_speed")),
                release_spin_rate=_safe_float(row.get("release_spin_rate")),
                pfx_x=_safe_float(row.get("pfx_x")),
                pfx_z=_safe_float(row.get("pfx_z")),
                plate_x=_safe_float(row.get("plate_x")),
                plate_z=_safe_float(row.get("plate_z")),
                balls=int(row["balls"]) if pd.notna(row.get("balls")) else None,
                strikes=int(row["strikes"]) if pd.notna(row.get("strikes")) else None,
                events=str(row.get("events", "") or "")[:50] or None,
                launch_speed=_safe_float(row.get("launch_speed")),
                launch_angle=_safe_float(row.get("launch_angle")),
                stand=str(row.get("stand", "") or "")[:1] or None,
                p_throws=str(row.get("p_throws", "") or "")[:1] or None,
            )
            session.add(ev)
        except Exception:
            continue
    session.commit()
    log.info("Statcast events loaded pitcher=%s rows=%d", pitcher_id, len(df))
    return df


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


# ---------------------------------------------------------------------------
# AtBatOutcome materialisation
# ---------------------------------------------------------------------------

def _load_at_bat_outcomes(session, date_str: str) -> None:
    """Materialise at-bat outcomes for all batters who appeared on *date_str*.

    For each batter active on the given date, this function groups the
    raw ``StatcastEvent`` rows by (batter_id, game_date, pitcher_id) and
    identifies the terminal pitch of each plate appearance — the last
    pitch in the sequence that carries a non-null ``events`` value.  It
    then writes (or skips if already present) an :class:`AtBatOutcome`
    row with a sequential ``ab_number`` that is unique and monotonically
    increasing across all games for that batter.

    The sequential ``ab_number`` is computed as::

        max(existing ab_number for batter) + 1, 2, 3, …

    so that new rows appended on each ETL run extend the all-time
    sequence without gaps.

    :param session: Active database session.
    :param date_str: Date string in ``YYYY-MM-DD`` format.
    """
    target_date = datetime.strptime(date_str, "%Y-%m-%d").date()

    # Fetch all events for the target date
    events = (
        session.query(StatcastEvent)
        .filter(StatcastEvent.game_date == target_date)
        .order_by(StatcastEvent.batter_id, StatcastEvent.pitcher_id, StatcastEvent.id)
        .all()
    )
    if not events:
        log.info("No StatcastEvents found for %s; skipping AtBatOutcome load", date_str)
        return

    # Group into PA sessions: (batter_id, pitcher_id) → list of pitches
    # We use insertion order (id) as the within-PA sequence proxy.
    from collections import defaultdict
    pa_groups: dict = defaultdict(list)
    for ev in events:
        pa_groups[(ev.batter_id, ev.pitcher_id)].append(ev)

    # For each batter, find the current max ab_number so we can extend it
    batter_ids = list({ev.batter_id for ev in events})
    ab_counters: dict = {}
    for batter_id in batter_ids:
        max_row = (
            session.query(AtBatOutcome.ab_number)
            .filter(AtBatOutcome.batter_id == batter_id)
            .order_by(AtBatOutcome.ab_number.desc())
            .first()
        )
        ab_counters[batter_id] = max_row.ab_number if max_row else 0

    # Check which (batter_id, pitcher_id, game_date) combos are already loaded
    existing_keys: set = set()
    existing_rows = (
        session.query(
            AtBatOutcome.batter_id,
            AtBatOutcome.pitcher_id,
            AtBatOutcome.game_date,
        )
        .filter(AtBatOutcome.game_date == target_date)
        .all()
    )
    for row in existing_rows:
        existing_keys.add((row.batter_id, row.pitcher_id, row.game_date))

    new_outcomes = []
    for (batter_id, pitcher_id), pitches in pa_groups.items():
        if (batter_id, pitcher_id, target_date) in existing_keys:
            continue  # already materialised for this date

        # The terminal pitch is the last pitch that has a non-null events value.
        # If none carry an event (e.g. mid-game data), fall back to the last pitch.
        terminal = next(
            (p for p in reversed(pitches) if p.events),
            pitches[-1],
        )

        ab_counters[batter_id] += 1
        new_outcomes.append(
            AtBatOutcome(
                game_date=target_date,
                batter_id=batter_id,
                pitcher_id=pitcher_id,
                ab_number=ab_counters[batter_id],
                result=terminal.events,
                pitch_count=len(pitches),
                exit_velocity=terminal.launch_speed,
                launch_angle=terminal.launch_angle,
                last_pitch_type=terminal.pitch_type,
                pitcher_hand=terminal.p_throws,
            )
        )

    if new_outcomes:
        session.bulk_save_objects(new_outcomes)
        session.commit()
        log.info(
            "AtBatOutcome: inserted %d rows for %s", len(new_outcomes), date_str
        )
    else:
        log.info("AtBatOutcome: no new rows for %s", date_str)


# ---------------------------------------------------------------------------
# Main ETL orchestration
# ---------------------------------------------------------------------------

def run_etl_for_date(date_str: str) -> None:
    engine = get_engine(DATABASE_URL)
    create_tables(engine)
    Session = get_session(engine)

    with Session() as session:
        log.info("ETL started for %s", date_str)
        games = fetch_schedule(date_str)
        if not games:
            log.info("No games found for %s", date_str)
            return

        pitcher_ids = _extract_pitcher_ids(games)
        team_ids = _extract_team_ids(games)
        season = int(date_str[:4])
        end_dt = datetime.strptime(date_str, "%Y-%m-%d").date()
        start_dt = (end_dt - timedelta(days=90)).isoformat()

        log.info("Found %d pitchers, %d teams", len(pitcher_ids), len(team_ids))

        # Team splits
        _load_team_splits(session, team_ids, season)

        # Try leaderboard arsenal first; fall back to per-pitcher Statcast
        arsenal_loaded = _try_load_arsenal_leaderboard(session, season)

        for pitcher_id in pitcher_ids:
            df = _load_statcast_for_pitcher(session, pitcher_id, start_dt, date_str)
            _load_pitcher_aggregate(session, pitcher_id, df, end_dt)
            if not arsenal_loaded:
                _load_pitch_arsenal_from_df(session, pitcher_id, df, season)

        # Materialise at-bat outcomes for fast AB-based rolling queries
        _load_at_bat_outcomes(session, date_str)

        log.info("ETL complete for %s", date_str)



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
    args = parser.parse_args()

    if args.backfill_days > 0:
        run_backfill(args.backfill_days)
    else:
        run_etl_for_date(args.date)

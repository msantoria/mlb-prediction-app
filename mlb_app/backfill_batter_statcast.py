"""
Dedicated batter Statcast backfill.

This script fills the hitter-specific Statcast history needed for reliable
rolling PA, AB, split, pitch-type, and live-count modeling.

Safety rules:
- Inserts missing pitch/event rows for a batter/date window.
- Updates only nullable ordering/context fields when the existing value is NULL.
- Never overwrites populated values.
- Never deletes rows.
- Never touches cron, Railway, or deployment configuration.

Examples:
    python -m mlb_app.backfill_batter_statcast --batter-id 660271 --start 2024-03-01 --end 2026-04-26
    python -m mlb_app.backfill_batter_statcast --batter-id 660271 --seasons 2024,2025,2026
"""

from __future__ import annotations

import argparse
import logging
import math
import os
from datetime import date, datetime
from typing import Any, Dict, Iterable, List, Optional, Tuple

import pandas as pd
from dotenv import load_dotenv

from .database import StatcastEvent, create_tables, get_engine, get_session
from .statcast_utils import fetch_statcast_batter_data

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///mlb.db")

SAFE_UPDATE_FIELDS = (
    "game_pk",
    "at_bat_number",
    "pitch_number",
    "inning",
    "inning_topbot",
    "outs_when_up",
    "home_team",
    "away_team",
    "pitch_type",
    "release_speed",
    "release_spin_rate",
    "pfx_x",
    "pfx_z",
    "plate_x",
    "plate_z",
    "balls",
    "strikes",
    "events",
    "launch_speed",
    "launch_angle",
    "stand",
    "p_throws",
)


def _is_missing(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, float) and math.isnan(value):
        return True
    if isinstance(value, str) and value.strip().lower() in {"", "nan", "none", "null"}:
        return True
    return False


def _safe_int(value: Any) -> Optional[int]:
    if _is_missing(value):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _safe_float(value: Any) -> Optional[float]:
    if _is_missing(value):
        return None
    try:
        val = float(value)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(val) else val


def _safe_str(value: Any, max_len: int) -> Optional[str]:
    if _is_missing(value):
        return None
    text = str(value).strip()
    return text[:max_len] if text else None


def _safe_date(value: Any) -> Optional[date]:
    if _is_missing(value):
        return None
    try:
        return pd.to_datetime(value).date()
    except Exception:
        return None


def _row_to_payload(row: pd.Series, batter_id: int) -> Optional[Dict[str, Any]]:
    game_date = _safe_date(row.get("game_date"))
    pitcher_id = _safe_int(row.get("pitcher"))
    if not game_date or not pitcher_id:
        return None
    return {
        "game_date": game_date,
        "game_pk": _safe_int(row.get("game_pk")),
        "at_bat_number": _safe_int(row.get("at_bat_number")),
        "pitch_number": _safe_int(row.get("pitch_number")),
        "inning": _safe_int(row.get("inning")),
        "inning_topbot": _safe_str(row.get("inning_topbot"), 10),
        "outs_when_up": _safe_int(row.get("outs_when_up")),
        "home_team": _safe_str(row.get("home_team"), 10),
        "away_team": _safe_str(row.get("away_team"), 10),
        "pitcher_id": pitcher_id,
        "batter_id": batter_id,
        "pitch_type": _safe_str(row.get("pitch_type"), 5),
        "release_speed": _safe_float(row.get("release_speed")),
        "release_spin_rate": _safe_float(row.get("release_spin_rate")),
        "pfx_x": _safe_float(row.get("pfx_x")),
        "pfx_z": _safe_float(row.get("pfx_z")),
        "plate_x": _safe_float(row.get("plate_x")),
        "plate_z": _safe_float(row.get("plate_z")),
        "balls": _safe_int(row.get("balls")),
        "strikes": _safe_int(row.get("strikes")),
        "events": _safe_str(row.get("events"), 50),
        "launch_speed": _safe_float(row.get("launch_speed")),
        "launch_angle": _safe_float(row.get("launch_angle")),
        "stand": _safe_str(row.get("stand"), 1),
        "p_throws": _safe_str(row.get("p_throws"), 1),
    }


def _event_identity(payload: Dict[str, Any]) -> Tuple[Any, ...]:
    """Stable enough identity for deduping without requiring a schema change."""
    if payload.get("game_pk") is not None and payload.get("at_bat_number") is not None and payload.get("pitch_number") is not None:
        return (
            payload.get("game_pk"),
            payload.get("at_bat_number"),
            payload.get("pitch_number"),
            payload.get("batter_id"),
            payload.get("pitcher_id"),
        )
    return (
        payload.get("game_date"),
        payload.get("batter_id"),
        payload.get("pitcher_id"),
        payload.get("pitch_type"),
        payload.get("release_speed"),
        payload.get("balls"),
        payload.get("strikes"),
        payload.get("events"),
        payload.get("launch_speed"),
        payload.get("launch_angle"),
    )


def _find_existing(session, payload: Dict[str, Any]) -> Optional[StatcastEvent]:
    if payload.get("game_pk") is not None and payload.get("at_bat_number") is not None and payload.get("pitch_number") is not None:
        existing = session.query(StatcastEvent).filter(
            StatcastEvent.game_pk == payload["game_pk"],
            StatcastEvent.at_bat_number == payload["at_bat_number"],
            StatcastEvent.pitch_number == payload["pitch_number"],
            StatcastEvent.batter_id == payload["batter_id"],
            StatcastEvent.pitcher_id == payload["pitcher_id"],
        ).first()
        if existing:
            return existing

    return session.query(StatcastEvent).filter(
        StatcastEvent.game_date == payload["game_date"],
        StatcastEvent.batter_id == payload["batter_id"],
        StatcastEvent.pitcher_id == payload["pitcher_id"],
        StatcastEvent.pitch_type == payload.get("pitch_type"),
        StatcastEvent.release_speed == payload.get("release_speed"),
        StatcastEvent.balls == payload.get("balls"),
        StatcastEvent.strikes == payload.get("strikes"),
        StatcastEvent.events == payload.get("events"),
        StatcastEvent.launch_speed == payload.get("launch_speed"),
        StatcastEvent.launch_angle == payload.get("launch_angle"),
    ).first()


def _insert_or_fill_missing(session, payload: Dict[str, Any]) -> str:
    existing = _find_existing(session, payload)
    if not existing:
        session.add(StatcastEvent(**payload))
        return "inserted"

    changed = False
    for field in SAFE_UPDATE_FIELDS:
        incoming = payload.get(field)
        if _is_missing(incoming):
            continue
        current = getattr(existing, field, None)
        if _is_missing(current):
            setattr(existing, field, incoming)
            changed = True
    return "updated_missing" if changed else "unchanged"


def backfill_batter_window(batter_id: int, start: str, end: str, commit_every: int = 1000) -> Dict[str, Any]:
    engine = get_engine(DATABASE_URL)
    create_tables(engine)
    Session = get_session(engine)

    log.info("Fetching batter Statcast batter_id=%s start=%s end=%s", batter_id, start, end)
    df = fetch_statcast_batter_data(batter_id, start, end)
    if df is None or df.empty:
        return {"batter_id": batter_id, "start": start, "end": end, "source_rows": 0, "inserted": 0, "updated_missing": 0, "unchanged": 0, "skipped": 0}

    counts = {"inserted": 0, "updated_missing": 0, "unchanged": 0, "skipped": 0}
    seen = set()

    with Session() as session:
        for idx, row in df.iterrows():
            payload = _row_to_payload(row, batter_id)
            if not payload:
                counts["skipped"] += 1
                continue
            identity = _event_identity(payload)
            if identity in seen:
                counts["skipped"] += 1
                continue
            seen.add(identity)
            status = _insert_or_fill_missing(session, payload)
            counts[status] += 1
            if (idx + 1) % commit_every == 0:
                session.commit()
                log.info("Progress batter_id=%s rows=%s inserted=%s updated_missing=%s unchanged=%s skipped=%s", batter_id, idx + 1, counts["inserted"], counts["updated_missing"], counts["unchanged"], counts["skipped"])
        session.commit()

    return {"batter_id": batter_id, "start": start, "end": end, "source_rows": int(len(df)), **counts}


def _season_windows(seasons: Iterable[int]) -> List[Tuple[str, str]]:
    today = date.today()
    windows: List[Tuple[str, str]] = []
    for season in seasons:
        start = f"{season}-03-01"
        if season == today.year:
            end = today.isoformat()
        else:
            end = f"{season}-11-30"
        windows.append((start, end))
    return windows


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill hitter-specific Statcast history without overwriting existing data.")
    parser.add_argument("--batter-id", type=int, required=True, help="MLBAM batter ID")
    parser.add_argument("--start", help="Start date YYYY-MM-DD")
    parser.add_argument("--end", help="End date YYYY-MM-DD")
    parser.add_argument("--seasons", default="2024,2025,2026", help="Comma-separated seasons if start/end are not supplied")
    parser.add_argument("--commit-every", type=int, default=1000)
    args = parser.parse_args()

    if args.start and args.end:
        windows = [(args.start, args.end)]
    else:
        seasons = [int(s.strip()) for s in args.seasons.split(",") if s.strip()]
        windows = _season_windows(seasons)

    all_results = []
    for start, end in windows:
        result = backfill_batter_window(args.batter_id, start, end, args.commit_every)
        all_results.append(result)
        log.info("Completed window result=%s", result)

    total = {"inserted": 0, "updated_missing": 0, "unchanged": 0, "skipped": 0, "source_rows": 0}
    for result in all_results:
        for key in total:
            total[key] += int(result.get(key, 0))
    log.info("Backfill complete batter_id=%s total=%s", args.batter_id, total)


if __name__ == "__main__":
    main()

from __future__ import annotations

import datetime as dt
from collections import defaultdict
from typing import Any, Dict, Iterable, Optional
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from mlb_app.database import PitcherAggregate, StatcastEvent
from mlb_app.statcast_event_identity import load_canonical_statcast_events

SWINGS = {
    "swinging_strike",
    "swinging_strike_blocked",
    "foul",
    "foul_tip",
    "hit_into_play",
    "hit_into_play_no_out",
    "hit_into_play_score",
}
WHIFFS = {"swinging_strike", "swinging_strike_blocked", "foul_tip"}
CALLED_STRIKES = {"called_strike"}
HITS = {"single", "double", "triple", "home_run"}
TERMINAL = HITS | {
    "strikeout",
    "strikeout_double_play",
    "field_out",
    "force_out",
    "walk",
    "intent_walk",
    "hit_by_pitch",
    "double_play",
    "grounded_into_double_play",
    "fielders_choice",
    "fielders_choice_out",
    "sac_fly",
    "sac_bunt",
}
NON_AB = {"walk", "intent_walk", "hit_by_pitch", "sac_fly", "sac_bunt"}

BUCKET_DEFINITIONS = {
    "source": "plate_x/plate_z",
    "release_warning": "release_pos_x/z and release_extension are release-geometry fields, not plate-location fields",
    "horizontal_middle": "abs(plate_x) <= 0.28",
    "vertical_low": "plate_z < 2.00",
    "vertical_high": "plate_z > 3.10",
    "in_zone": "abs(plate_x) <= 0.83 and 1.50 <= plate_z <= 3.50",
    "heart": "abs(plate_x) <= 0.33 and 2.10 <= plate_z <= 3.30",
    "barrel_approximation": "launch_speed >= 98 and 8 <= launch_angle <= 50",
}
MLB_TIMEZONE = ZoneInfo("America/New_York")


def _float(value: Any) -> Optional[float]:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _avg(values: Iterable[Any], digits: int = 3) -> Optional[float]:
    nums = [_float(value) for value in values]
    nums = [value for value in nums if value is not None]
    if not nums:
        return None
    return round(sum(nums) / len(nums), digits)


def _rate(numerator: int, denominator: int, digits: int = 4) -> Optional[float]:
    if not denominator:
        return None
    return round(numerator / denominator, digits)


def location_bucket(plate_x: Any, plate_z: Any, stand: Optional[str] = None) -> Dict[str, Any]:
    x = _float(plate_x)
    z = _float(plate_z)
    if x is None or z is None:
        return {
            "bucket": "missing_plate_location",
            "missing_inputs": ["plate_x", "plate_z"],
            "handedness_adjusted": False,
        }

    if abs(x) <= 0.28:
        horizontal = "middle"
        adjusted = stand in {"L", "R"}
    elif stand == "R":
        horizontal = "inside" if x < 0 else "outside"
        adjusted = True
    elif stand == "L":
        horizontal = "inside" if x > 0 else "outside"
        adjusted = True
    else:
        horizontal = "left" if x < 0 else "right"
        adjusted = False

    vertical = "low" if z < 2.0 else "high" if z > 3.1 else "middle"
    return {
        "bucket": f"{horizontal}_{vertical}",
        "horizontal": horizontal,
        "vertical": vertical,
        "in_zone": abs(x) <= 0.83 and 1.5 <= z <= 3.5,
        "heart_zone": abs(x) <= 0.33 and 2.1 <= z <= 3.3,
        "handedness_adjusted": adjusted,
        "missing_inputs": [],
    }


def _empty_counter() -> Dict[str, Any]:
    return {
        "pitches": 0,
        "swings": 0,
        "whiffs": 0,
        "called_strikes": 0,
        "pa_ended": 0,
        "official_ab": 0,
        "hits": 0,
        "strikeouts": 0,
        "batted_balls": 0,
        "hard_hits": 0,
        "barrels": 0,
        "in_zone": 0,
        "heart_zone": 0,
        "velocity_values": [],
        "spin_values": [],
        "ev_values": [],
        "la_values": [],
        "xwoba_values": [],
        "xba_values": [],
        "plate_x_values": [],
        "plate_z_values": [],
    }


def _barrel_approx(event: StatcastEvent) -> bool:
    ev = _float(event.launch_speed)
    la = _float(event.launch_angle)
    return ev is not None and la is not None and ev >= 98 and 8 <= la <= 50


def _add_event(counter: Dict[str, Any], event: StatcastEvent) -> None:
    counter["pitches"] += 1
    if event.description in SWINGS:
        counter["swings"] += 1
    if event.description in WHIFFS:
        counter["whiffs"] += 1
    if event.description in CALLED_STRIKES:
        counter["called_strikes"] += 1
    if event.events in TERMINAL:
        counter["pa_ended"] += 1
        if event.events not in NON_AB:
            counter["official_ab"] += 1
    if event.events in HITS:
        counter["hits"] += 1
    if event.events in {"strikeout", "strikeout_double_play"}:
        counter["strikeouts"] += 1

    if event.release_speed is not None:
        counter["velocity_values"].append(event.release_speed)
    if event.release_spin_rate is not None:
        counter["spin_values"].append(event.release_spin_rate)

    loc = location_bucket(event.plate_x, event.plate_z, event.stand)
    if loc["bucket"] != "missing_plate_location":
        counter["plate_x_values"].append(event.plate_x)
        counter["plate_z_values"].append(event.plate_z)
        if loc.get("in_zone"):
            counter["in_zone"] += 1
        if loc.get("heart_zone"):
            counter["heart_zone"] += 1

    if event.launch_speed is not None:
        counter["batted_balls"] += 1
        counter["ev_values"].append(event.launch_speed)
        if float(event.launch_speed) >= 95:
            counter["hard_hits"] += 1
    if event.launch_angle is not None:
        counter["la_values"].append(event.launch_angle)
    if _barrel_approx(event):
        counter["barrels"] += 1
    if event.estimated_woba_using_speedangle is not None:
        counter["xwoba_values"].append(event.estimated_woba_using_speedangle)
    if event.estimated_ba_using_speedangle is not None:
        counter["xba_values"].append(event.estimated_ba_using_speedangle)


def _summarize(counter: Dict[str, Any]) -> Dict[str, Any]:
    pitches = counter["pitches"]
    swings = counter["swings"]
    bbe = counter["batted_balls"]
    pa = counter["pa_ended"]
    ab = counter["official_ab"]
    return {
        "pitches": pitches,
        "swings": swings,
        "whiffs": counter["whiffs"],
        "called_strikes": counter["called_strikes"],
        "pa_ended": pa,
        "official_ab": ab,
        "hits": counter["hits"],
        "strikeouts": counter["strikeouts"],
        "batted_balls": bbe,
        "hard_hits": counter["hard_hits"],
        "barrels": counter["barrels"],
        "batting_avg": _rate(counter["hits"], ab, 3),
        "whiff_pct": _rate(counter["whiffs"], swings),
        "csw_pct": _rate(counter["called_strikes"] + counter["whiffs"], pitches),
        "k_pct": _rate(counter["strikeouts"], pa),
        "in_zone_pct": _rate(counter["in_zone"], pitches),
        "heart_zone_pct": _rate(counter["heart_zone"], pitches),
        "hard_hit_pct": _rate(counter["hard_hits"], bbe),
        "barrel_pct": _rate(counter["barrels"], bbe),
        "avg_velocity": _avg(counter["velocity_values"], 1),
        "avg_spin_rate": _avg(counter["spin_values"], 0),
        "avg_exit_velocity": _avg(counter["ev_values"], 1),
        "avg_launch_angle": _avg(counter["la_values"], 1),
        "xwoba": _avg(counter["xwoba_values"], 3),
        "xba": _avg(counter["xba_values"], 3),
        "avg_plate_x": _avg(counter["plate_x_values"], 3),
        "avg_plate_z": _avg(counter["plate_z_values"], 3),
    }


def _score_damage(summary: Dict[str, Any]) -> Optional[float]:
    values = []
    if summary.get("xwoba") is not None:
        values.append((summary["xwoba"] - 0.320) * 2.5)
    if summary.get("hard_hit_pct") is not None:
        values.append((summary["hard_hit_pct"] - 0.350) * 0.8)
    if summary.get("barrel_pct") is not None:
        values.append((summary["barrel_pct"] - 0.080) * 1.2)
    if not values:
        return None
    return round(sum(values) / len(values), 4)


def _score_quality(summary: Dict[str, Any]) -> Optional[float]:
    values = []
    if summary.get("whiff_pct") is not None:
        values.append(summary["whiff_pct"] - 0.24)
    if summary.get("csw_pct") is not None:
        values.append(summary["csw_pct"] - 0.28)
    if summary.get("xwoba") is not None:
        values.append(0.320 - summary["xwoba"])
    if not values:
        return None
    return round(sum(values) / len(values), 4)


def _best(rows: list[Dict[str, Any]], key: str, reverse: bool = True, min_pitches: int = 5) -> Optional[Dict[str, Any]]:
    candidates = [row for row in rows if row.get(key) is not None and row.get("pitches", 0) >= min_pitches]
    if not candidates:
        return None
    return sorted(candidates, key=lambda row: row[key], reverse=reverse)[0]


def _bucket_rows(bucket_counters: Dict[str, Dict[str, Any]]) -> list[Dict[str, Any]]:
    rows = []
    for bucket_name, counter in bucket_counters.items():
        row = {"bucket": bucket_name, **_summarize(counter)}
        row["damage_score"] = _score_damage(row)
        rows.append(row)
    return sorted(rows, key=lambda row: row["pitches"], reverse=True)


def _release_profile(session: Session, pitcher_id: int, season: int) -> Dict[str, Any]:
    row = session.query(PitcherAggregate).filter(
        PitcherAggregate.pitcher_id == int(pitcher_id),
        PitcherAggregate.end_date >= dt.date(int(season), 1, 1),
    ).order_by(PitcherAggregate.end_date.desc()).first()

    missing = []
    if row is None or row.avg_release_pos_x is None:
        missing.append("avg_release_pos_x")
    if row is None or row.avg_release_pos_z is None:
        missing.append("avg_release_pos_z")
    if row is None or row.avg_release_extension is None:
        missing.append("avg_release_extension")

    return {
        "source": "pitcher_aggregates" if row else "missing_pitcher_aggregates",
        "note": BUCKET_DEFINITIONS["release_warning"],
        "window": row.window if row else None,
        "end_date": row.end_date.isoformat() if row and row.end_date else None,
        "avg_release_pos_x": row.avg_release_pos_x if row else None,
        "avg_release_pos_z": row.avg_release_pos_z if row else None,
        "avg_release_extension": row.avg_release_extension if row else None,
        "missing_inputs": missing,
    }


def build_pitcher_intelligence_profile(session: Session, pitcher_id: int, season: int, days_back: int = 365) -> Dict[str, Any]:
    today = dt.datetime.now(MLB_TIMEZONE).date()
    season_start = dt.date(int(season), 1, 1)
    end_date = min(today, dt.date(int(season), 12, 31))
    start_date = max(season_start, end_date - dt.timedelta(days=max(int(days_back), 1)))
    events, identity_diagnostics = load_canonical_statcast_events(
        session,
        StatcastEvent.pitcher_id == int(pitcher_id),
        StatcastEvent.game_date >= start_date,
        StatcastEvent.game_date <= end_date,
        order_by=(
            StatcastEvent.game_date.asc(),
            StatcastEvent.game_pk.asc(),
            StatcastEvent.at_bat_number.asc(),
            StatcastEvent.pitch_number.asc(),
        ),
    )

    overall = _empty_counter()
    by_pitch = defaultdict(_empty_counter)
    by_bucket = defaultdict(_empty_counter)

    for event in events:
        pitch_type = event.pitch_type or "Unknown"
        _add_event(overall, event)
        _add_event(by_pitch[pitch_type], event)
        loc = location_bucket(event.plate_x, event.plate_z, event.stand)
        if loc["bucket"] != "missing_plate_location":
            _add_event(by_bucket[loc["bucket"]], event)

    summary = _summarize(overall)
    total_pitches = max(summary["pitches"], 1)
    arsenal = []
    for pitch_type, counter in by_pitch.items():
        row = _summarize(counter)
        row.update({
            "pitch_type": pitch_type,
            "usage_pct": round(row["pitches"] / total_pitches, 4),
            "quality_score": _score_quality(row),
            "damage_score": _score_damage(row),
            "missing_inputs": [
                key for key, missing in {
                    "plate_x_plate_z": row["avg_plate_x"] is None or row["avg_plate_z"] is None,
                    "launch_speed": row["batted_balls"] == 0,
                    "estimated_woba_using_speedangle": row["xwoba"] is None,
                    "estimated_ba_using_speedangle": row["xba"] is None,
                }.items() if missing
            ],
        })
        arsenal.append(row)
    arsenal.sort(key=lambda row: row["usage_pct"], reverse=True)

    location_rows = _bucket_rows(by_bucket)
    dates = [event.game_date for event in events if event.game_date]
    release = _release_profile(session, pitcher_id, season)
    missing_inputs = [
        key for key, missing in {
            "statcast_events_for_pitcher": not events,
            "plate_x_plate_z": summary["avg_plate_x"] is None or summary["avg_plate_z"] is None,
            "launch_speed_launch_angle": summary["batted_balls"] == 0,
        }.items() if missing
    ]
    missing_inputs.extend(release.get("missing_inputs") or [])

    return {
        "source": "statcast_events",
        "pitcher_id": int(pitcher_id),
        "season": int(season),
        "days_back": int(days_back),
        "data_window": {"date_start": start_date.isoformat(), "date_end": max(dates).isoformat() if dates else None},
        "sample_size": {
            "raw_rows": identity_diagnostics["raw_rows"],
            "deduped_pitch_rows": len(events),
            "canonical_pitch_rows": identity_diagnostics["canonical_pitch_rows"],
            "legacy_pitch_rows": identity_diagnostics["legacy_pitch_rows"],
            "incomplete_identity_rows": identity_diagnostics["incomplete_identity_rows"],
            "duplicate_rows_removed": identity_diagnostics["duplicate_rows_removed"],
            "pitch_types": len(arsenal),
            "batted_balls": summary["batted_balls"],
            "pa_ended": summary["pa_ended"],
        },
        "summary": {**summary, "pitch_types_used": [row["pitch_type"] for row in arsenal], "best_pitch": _best(arsenal, "quality_score", True, 20), "riskiest_pitch": _best(arsenal, "damage_score", True, 20)},
        "arsenal": arsenal,
        "location_profile": {"source": "plate_x_plate_z", "bucket_definitions": BUCKET_DEFINITIONS, "buckets": location_rows, "most_attacked_location_bucket": _best(location_rows, "pitches", True, 1), "most_damaged_location_bucket": _best(location_rows, "damage_score", True, 5)},
        "release_profile": release,
        "missing_inputs": sorted(set(missing_inputs)),
        "quality_flags": [flag for flag in [
            "no_statcast_events" if not events else None,
            "legacy_duplicate_rows_removed" if identity_diagnostics["duplicate_rows_removed"] else None,
            "incomplete_pitch_identity_rows_present" if identity_diagnostics["incomplete_identity_rows"] else None,
            "barrel_rate_is_internal_approximation" if summary["batted_balls"] else None,
        ] if flag],
        "metadata": {"model_version": "pitcher_intelligence_v2", "pitch_identity": "game_pk/at_bat_number/pitch_number", "location_source": "plate_x/plate_z", "release_source": "pitcher_aggregates", "barrel_definition": BUCKET_DEFINITIONS["barrel_approximation"]},
    }

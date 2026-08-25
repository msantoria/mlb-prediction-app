"""Cutoff-safe evidence for canonical pitcher matchup profiles."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import math
from collections import defaultdict
from typing import Any, Iterable


CANONICAL_PITCHER_MATCHUP_PROFILE_EVIDENCE_VERSION = (
    "canonical_pitcher_matchup_profile_evidence_v1"
)

WINDOW_DAYS = 90

TERMINAL_EVENTS = {
    "single",
    "double",
    "triple",
    "home_run",
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

STRIKEOUT_EVENTS = {
    "strikeout",
    "strikeout_double_play",
}

WALK_EVENTS = {"walk"}

CONTACT_CLASSIFICATION = {
    "source": "internal_launch_angle_classification_v1",
    "ground_ball": "launch_angle < 10",
    "line_drive": "10 <= launch_angle < 25",
    "fly_ball": "25 <= launch_angle < 50",
    "popup": "launch_angle >= 50",
    "sweet_spot": "8 <= launch_angle <= 32",
    "barrel_approximation": (
        "launch_speed >= 98 and 8 <= launch_angle <= 50"
    ),
    "barrel_denominator": "batted balls with exit velocity and launch angle",
    "hard_hit": "launch_speed >= 95",
    "official_statcast_classification": False,
}


def _value(row: Any, key: str) -> Any:
    if isinstance(row, dict):
        return row.get(key)
    return getattr(row, key, None)


def _finite(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None

    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None

    return parsed if math.isfinite(parsed) else None


def _date(value: Any) -> dt.date:
    if isinstance(value, dt.datetime):
        return value.date()
    if isinstance(value, dt.date):
        return value
    if isinstance(value, str):
        return dt.date.fromisoformat(value)
    raise TypeError("date value must be ISO text or date")


def _rate(numerator: int, denominator: int) -> float | None:
    if denominator <= 0:
        return None
    return round(numerator / denominator, 6)


def _mean(values: list[float]) -> float | None:
    if not values:
        return None
    return round(sum(values) / len(values), 6)


def _percentile(
    values: list[float],
    percentile: float,
) -> float | None:
    if not values:
        return None

    ordered = sorted(values)
    if len(ordered) == 1:
        return round(ordered[0], 3)

    position = (len(ordered) - 1) * percentile
    lower = math.floor(position)
    upper = math.ceil(position)

    if lower == upper:
        value = ordered[lower]
    else:
        weight = position - lower
        value = (
            ordered[lower] * (1.0 - weight)
            + ordered[upper] * weight
        )

    return round(value, 3)


def _pitch_identity(row: Any) -> tuple[Any, ...]:
    game_pk = _value(row, "game_pk")
    at_bat = _value(row, "at_bat_number")
    pitch_number = _value(row, "pitch_number")

    if (
        game_pk is not None
        and at_bat is not None
        and pitch_number is not None
    ):
        return (
            "canonical",
            game_pk,
            at_bat,
            pitch_number,
        )

    return (
        "legacy",
        _value(row, "id"),
        _value(row, "game_date"),
        _value(row, "batter_id"),
        _value(row, "events"),
        _value(row, "description"),
        _value(row, "launch_speed"),
        _value(row, "launch_angle"),
    )


def _pa_identity(row: Any) -> tuple[Any, ...]:
    game_pk = _value(row, "game_pk")
    at_bat = _value(row, "at_bat_number")

    if game_pk is not None and at_bat is not None:
        return ("canonical", game_pk, at_bat)

    return (
        "legacy",
        _value(row, "game_date"),
        _value(row, "batter_id"),
        _value(row, "id"),
    )


def _sort_key(row: Any) -> tuple[Any, ...]:
    return (
        _date(_value(row, "game_date")),
        _value(row, "game_pk") or -1,
        _value(row, "at_bat_number") or -1,
        _value(row, "pitch_number") or -1,
        _value(row, "id") or -1,
    )


def _empty_counter() -> dict[str, Any]:
    return {
        "plate_appearances": 0,
        "strikeouts": 0,
        "unintentional_walks": 0,
        "batted_balls": 0,
        "hard_hits": 0,
        "barrels_approx": 0,
        "sweet_spot_batted_balls": 0,
        "ground_balls": 0,
        "line_drives": 0,
        "fly_balls": 0,
        "popups": 0,
        "exit_velocities": [],
        "launch_angles": [],
        "xwoba_values": [],
        "xba_values": [],
    }


def _add_plate_appearance(
    counter: dict[str, Any],
    row: Any,
) -> None:
    event = _value(row, "events")
    counter["plate_appearances"] += 1

    if event in STRIKEOUT_EVENTS:
        counter["strikeouts"] += 1
    if event in WALK_EVENTS:
        counter["unintentional_walks"] += 1


def _add_contact(
    counter: dict[str, Any],
    row: Any,
) -> None:
    exit_velocity = _finite(
        _value(row, "launch_speed")
    )
    launch_angle = _finite(
        _value(row, "launch_angle")
    )

    if exit_velocity is None:
        return

    counter["batted_balls"] += 1
    counter["exit_velocities"].append(exit_velocity)

    if exit_velocity >= 95:
        counter["hard_hits"] += 1

    if launch_angle is not None:
        counter["launch_angles"].append(launch_angle)

        if launch_angle < 10:
            counter["ground_balls"] += 1
        elif launch_angle < 25:
            counter["line_drives"] += 1
        elif launch_angle < 50:
            counter["fly_balls"] += 1
        else:
            counter["popups"] += 1

        if 8 <= launch_angle <= 32:
            counter["sweet_spot_batted_balls"] += 1

        if (
            exit_velocity >= 98
            and 8 <= launch_angle <= 50
        ):
            counter["barrels_approx"] += 1

    xwoba = _finite(
        _value(
            row,
            "estimated_woba_using_speedangle",
        )
    )
    if xwoba is not None:
        counter["xwoba_values"].append(xwoba)

    xba = _finite(
        _value(
            row,
            "estimated_ba_using_speedangle",
        )
    )
    if xba is not None:
        counter["xba_values"].append(xba)


def _summarize(counter: dict[str, Any]) -> dict[str, Any]:
    pa = counter["plate_appearances"]
    bbe = counter["batted_balls"]
    launch_angle_count = len(
        counter["launch_angles"]
    )

    return {
        "sample_size": {
            "plate_appearances": pa,
            "batted_balls": bbe,
            "launch_angle_batted_balls": (
                launch_angle_count
            ),
            "barrel_eligible_batted_balls": (
                launch_angle_count
            ),
            "xwoba_batted_balls": len(
                counter["xwoba_values"]
            ),
            "xba_batted_balls": len(
                counter["xba_values"]
            ),
        },
        "discipline": {
            "strikeouts": counter["strikeouts"],
            "unintentional_walks": (
                counter["unintentional_walks"]
            ),
            "k_rate": _rate(
                counter["strikeouts"],
                pa,
            ),
            "bb_rate": _rate(
                counter["unintentional_walks"],
                pa,
            ),
        },
        "contact_quality": {
            "hard_hits": counter["hard_hits"],
            "barrels_approx": (
                counter["barrels_approx"]
            ),
            "hard_hit_rate_allowed": _rate(
                counter["hard_hits"],
                bbe,
            ),
            "barrel_rate_allowed_approx": _rate(
                counter["barrels_approx"],
                launch_angle_count,
            ),
            "avg_exit_velocity_allowed": _mean(
                counter["exit_velocities"]
            ),
            "median_exit_velocity_allowed": (
                _percentile(
                    counter["exit_velocities"],
                    0.50,
                )
            ),
            "p90_exit_velocity_allowed": (
                _percentile(
                    counter["exit_velocities"],
                    0.90,
                )
            ),
            "max_exit_velocity_allowed": (
                round(
                    max(counter["exit_velocities"]),
                    3,
                )
                if counter["exit_velocities"]
                else None
            ),
            "xwoba_allowed": _mean(
                counter["xwoba_values"]
            ),
            "xba_allowed": _mean(
                counter["xba_values"]
            ),
        },
        "launch_angle_distribution": {
            "sweet_spot_batted_balls": (
                counter["sweet_spot_batted_balls"]
            ),
            "ground_balls": counter["ground_balls"],
            "line_drives": counter["line_drives"],
            "fly_balls": counter["fly_balls"],
            "popups": counter["popups"],
            "avg_launch_angle_allowed": _mean(
                counter["launch_angles"]
            ),
            "sweet_spot_rate_allowed": _rate(
                counter["sweet_spot_batted_balls"],
                launch_angle_count,
            ),
            "ground_ball_rate": _rate(
                counter["ground_balls"],
                launch_angle_count,
            ),
            "line_drive_rate": _rate(
                counter["line_drives"],
                launch_angle_count,
            ),
            "fly_ball_rate": _rate(
                counter["fly_balls"],
                launch_angle_count,
            ),
            "popup_rate": _rate(
                counter["popups"],
                launch_angle_count,
            ),
        },
        "metric_denominators": {
            "k_rate": pa,
            "bb_rate": pa,
            "hard_hit_rate_allowed": bbe,
            "barrel_rate_allowed_approx": (
                launch_angle_count
            ),
            "sweet_spot_rate_allowed": (
                launch_angle_count
            ),
            "ground_ball_rate": launch_angle_count,
            "line_drive_rate": launch_angle_count,
            "fly_ball_rate": launch_angle_count,
            "popup_rate": launch_angle_count,
            "avg_exit_velocity_allowed": bbe,
            "median_exit_velocity_allowed": bbe,
            "p90_exit_velocity_allowed": bbe,
            "max_exit_velocity_allowed": bbe,
            "avg_launch_angle_allowed": (
                launch_angle_count
            ),
            "xwoba_allowed": len(
                counter["xwoba_values"]
            ),
            "xba_allowed": len(
                counter["xba_values"]
            ),
        },
    }


def build_canonical_pitcher_matchup_profile_evidence(
    events: Iterable[Any],
    *,
    pitcher_id: int,
    game_date: dt.date | str,
    window_days: int = WINDOW_DAYS,
) -> dict[str, Any]:
    """Build immutable pregame evidence without production authority."""
    cutoff = _date(game_date)
    start_date = cutoff - dt.timedelta(
        days=max(int(window_days), 1)
    )

    filtered = []
    seen_pitch_identities = set()
    eligible_raw_event_count = 0

    for row in events:
        if _value(row, "pitcher_id") != pitcher_id:
            continue

        row_date = _date(_value(row, "game_date"))
        if not start_date <= row_date < cutoff:
            continue

        eligible_raw_event_count += 1
        identity = _pitch_identity(row)

        if identity in seen_pitch_identities:
            continue

        seen_pitch_identities.add(identity)
        filtered.append(row)

    filtered.sort(key=_sort_key)

    terminal_by_pa = {}
    contact_by_pa = {}

    for row in filtered:
        pa_identity = _pa_identity(row)

        if _value(row, "events") in TERMINAL_EVENTS:
            terminal_by_pa[pa_identity] = row

        if _finite(_value(row, "launch_speed")) is not None:
            contact_by_pa[pa_identity] = row

    overall = _empty_counter()
    platoon = defaultdict(_empty_counter)
    tto = defaultdict(_empty_counter)
    encounters = defaultdict(int)

    for pa_identity, row in sorted(
        terminal_by_pa.items(),
        key=lambda item: _sort_key(item[1]),
    ):
        _add_plate_appearance(overall, row)

        stand = _value(row, "stand")
        platoon_key = (
            stand
            if stand in {"L", "R"}
            else "unknown"
        )
        _add_plate_appearance(
            platoon[platoon_key],
            row,
        )

        encounter_key = (
            (
                "canonical",
                _value(row, "game_pk"),
            )
            if _value(row, "game_pk") is not None
            else (
                "legacy_date",
                _date(
                    _value(row, "game_date")
                ).isoformat(),
            ),
            _value(row, "batter_id"),
        )
        encounters[encounter_key] += 1
        encounter = encounters[encounter_key]

        if encounter == 1:
            tto_key = "1"
        elif encounter == 2:
            tto_key = "2"
        else:
            tto_key = "3_plus"

        _add_plate_appearance(tto[tto_key], row)

        contact = contact_by_pa.get(pa_identity)
        if contact is not None:
            _add_contact(overall, contact)
            _add_contact(
                platoon[platoon_key],
                contact,
            )
            _add_contact(tto[tto_key], contact)

    evidence = {
        "schema_version": (
            CANONICAL_PITCHER_MATCHUP_PROFILE_EVIDENCE_VERSION
        ),
        "status": (
            "ready"
            if terminal_by_pa and contact_by_pa
            else "partial"
            if terminal_by_pa
            else "unavailable"
        ),
        "pitcher_id": int(pitcher_id),
        "game_date": cutoff.isoformat(),
        "window": {
            "window_days": int(window_days),
            "start_date_inclusive": (
                start_date.isoformat()
            ),
            "cutoff_date_exclusive": cutoff.isoformat(),
            "cutoff_rule": (
                "statcast_event_game_date_"
                "strictly_before_game_date"
            ),
        },
        "overall": _summarize(overall),
        "platoon_splits": {
            key: _summarize(platoon[key])
            for key in ("L", "R", "unknown")
        },
        "times_through_order_splits": {
            key: _summarize(tto[key])
            for key in ("1", "2", "3_plus")
        },
        "classification": CONTACT_CLASSIFICATION,
        "diagnostics": {
            "raw_event_count": eligible_raw_event_count,
            "deduped_pitch_count": len(filtered),
            "duplicate_pitch_count": (
                eligible_raw_event_count - len(filtered)
            ),
            "terminal_plate_appearance_count": len(
                terminal_by_pa
            ),
            "contact_plate_appearance_count": len(
                contact_by_pa
            ),
            "production_authority": False,
            "shrinkage_applied": False,
            "activation_status": (
                "evidence_only_pending_calibration"
            ),
        },
    }

    digest_payload = {
        key: value
        for key, value in evidence.items()
        if key != "diagnostics"
    }
    evidence["diagnostics"]["evidence_digest"] = (
        hashlib.sha256(
            json.dumps(
                digest_payload,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
    )

    return evidence

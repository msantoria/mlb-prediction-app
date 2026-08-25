"""Cutoff-safe pitcher matchup profile evidence sourcing."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import math
from collections.abc import Mapping
from typing import Any

from sqlalchemy.orm import Session

from mlb_app.database import PitcherAggregate


CANONICAL_PITCHER_MATCHUP_PROFILE_SOURCE_VERSION = (
    "canonical_pitcher_matchup_profile_source_v1"
)

PROFILE_FIELDS = (
    "k_pct",
    "bb_pct",
    "hard_hit_pct",
    "xwoba",
    "xba",
)


def _date(value: Any) -> dt.date:
    if isinstance(value, dt.datetime):
        return value.date()
    if isinstance(value, dt.date):
        return value

    try:
        return dt.date.fromisoformat(
            str(value).strip()[:10]
        )
    except (TypeError, ValueError) as exc:
        raise ValueError(
            "game_date must be a valid date"
        ) from exc


def _finite_number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None

    try:
        number = float(value)
    except (TypeError, ValueError):
        return None

    if not math.isfinite(number):
        return None

    return number


def _digest(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def source_canonical_pitcher_matchup_profile(
    session: Session,
    *,
    pitcher_id: int,
    game_date: Any,
    matchup_features: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Fill missing matchup profile fields from prior 90-day evidence.

    Aggregate evidence must end strictly before the target game date.
    Same-day and future rows are never eligible.
    """

    if isinstance(pitcher_id, bool):
        raise ValueError("pitcher_id must be a positive integer")

    try:
        normalized_pitcher_id = int(pitcher_id)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            "pitcher_id must be a positive integer"
        ) from exc

    if normalized_pitcher_id < 1:
        raise ValueError(
            "pitcher_id must be a positive integer"
        )

    normalized_game_date = _date(game_date)
    supplied = dict(matchup_features or {})

    aggregate = (
        session.query(PitcherAggregate)
        .filter(
            PitcherAggregate.pitcher_id
            == normalized_pitcher_id,
            PitcherAggregate.window == "90d",
            PitcherAggregate.end_date
            < normalized_game_date,
        )
        .order_by(
            PitcherAggregate.end_date.desc(),
            PitcherAggregate.id.desc(),
        )
        .first()
    )

    merged = dict(supplied)
    field_provenance = {}

    for field in PROFILE_FIELDS:
        supplied_value = _finite_number(
            supplied.get(field)
        )

        if supplied_value is not None:
            field_provenance[field] = {
                "source": "matchup_payload",
                "filled_from_aggregate": False,
            }
            continue

        aggregate_value = (
            _finite_number(getattr(aggregate, field))
            if aggregate is not None
            else None
        )

        if aggregate_value is not None:
            merged[field] = aggregate_value
            field_provenance[field] = {
                "source": "pitcher_aggregate_90d",
                "filled_from_aggregate": True,
            }
        else:
            field_provenance[field] = {
                "source": "missing",
                "filled_from_aggregate": False,
            }

    populated_fields = tuple(
        field
        for field in PROFILE_FIELDS
        if _finite_number(merged.get(field))
        is not None
    )
    missing_fields = tuple(
        field
        for field in PROFILE_FIELDS
        if field not in populated_fields
    )

    if not populated_fields:
        status = "unavailable"
    elif missing_fields:
        status = "partial"
    else:
        status = "ready"

    selected_end_date = (
        aggregate.end_date.isoformat()
        if aggregate is not None
        else None
    )
    days_before_game = (
        (normalized_game_date - aggregate.end_date).days
        if aggregate is not None
        else None
    )

    diagnostics = {
        "schema_version": (
            CANONICAL_PITCHER_MATCHUP_PROFILE_SOURCE_VERSION
        ),
        "status": status,
        "pitcher_id": normalized_pitcher_id,
        "game_date": normalized_game_date.isoformat(),
        "cutoff_rule": "aggregate_end_date_strictly_before_game_date",
        "selected_window": (
            aggregate.window
            if aggregate is not None
            else None
        ),
        "selected_end_date": selected_end_date,
        "days_before_game": days_before_game,
        "populated_fields": list(populated_fields),
        "missing_fields": list(missing_fields),
        "field_provenance": field_provenance,
    }
    diagnostics["source_digest"] = _digest(
        diagnostics
    )

    return {
        "pitcher_features": merged,
        "diagnostics": diagnostics,
    }

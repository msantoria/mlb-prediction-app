"""Cutoff-independent realized PA outcomes for pitcher-profile scoring.

This module materializes only observed historical outcomes. It does not build
pregame probabilities, select calibration parameters, or change production
authority.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
from collections import defaultdict
from typing import Any, Iterable, Mapping


SCHEMA_VERSION = (
    "canonical_pitcher_matchup_profile_pa_historical_outcomes_v1"
)

OUTCOME_KEYS = (
    "k",
    "bb",
    "hbp",
    "single",
    "double",
    "triple",
    "hr",
    "reached_on_error",
    "out",
)

_EVENT_OUTCOMES = {
    "strikeout": "k",
    "strikeout_double_play": "k",
    "walk": "bb",
    "intent_walk": "bb",
    "hit_by_pitch": "hbp",
    "single": "single",
    "double": "double",
    "triple": "triple",
    "home_run": "hr",
    "field_error": "reached_on_error",
    "field_out": "out",
    "force_out": "out",
    "grounded_into_double_play": "out",
    "double_play": "out",
    "triple_play": "out",
    "fielders_choice": "out",
    "fielders_choice_out": "out",
    "sac_fly": "out",
    "sac_bunt": "out",
}


def _value(row: Any, name: str) -> Any:
    if isinstance(row, Mapping):
        return row.get(name)
    return getattr(row, name, None)


def _positive_integer(
    value: Any,
    name: str,
) -> int:
    if isinstance(value, bool):
        raise ValueError(
            f"{name}_must_be_positive_integer"
        )

    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"{name}_must_be_positive_integer"
        ) from exc

    if parsed <= 0:
        raise ValueError(
            f"{name}_must_be_positive_integer"
        )

    return parsed


def _date(value: Any) -> dt.date:
    if isinstance(value, dt.datetime):
        return value.date()

    if isinstance(value, dt.date):
        return value

    try:
        return dt.date.fromisoformat(
            str(value)
        )
    except (TypeError, ValueError) as exc:
        raise ValueError(
            "game_date_must_be_iso_date"
        ) from exc


def _event(value: Any) -> str | None:
    if value is None:
        return None

    normalized = str(value).strip().lower()

    if normalized in {
        "",
        "nan",
        "none",
        "null",
    }:
        return None

    return normalized


def _digest(value: Any) -> str:
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")

    return hashlib.sha256(
        encoded
    ).hexdigest()


def _empty_counts() -> dict[str, int]:
    return {
        outcome: 0
        for outcome in OUTCOME_KEYS
    }


def materialize_canonical_pitcher_matchup_profile_pa_historical_outcomes(
    events: Iterable[Any],
) -> dict[str, Any]:
    """Deduplicate terminal Statcast PAs and aggregate realized outcomes."""
    rows = list(events)
    terminal_by_identity: dict[
        tuple[int, int],
        dict[str, Any],
    ] = {}
    conflicting_identities: set[
        tuple[int, int]
    ] = set()
    rejected_rows: list[dict[str, Any]] = []
    nonterminal_pitch_rows = 0
    duplicate_terminal_rows = 0

    for index, row in enumerate(rows):
        event_name = _event(
            _value(row, "events")
        )

        if event_name is None:
            nonterminal_pitch_rows += 1
            continue

        try:
            game_pk = _positive_integer(
                _value(row, "game_pk"),
                "game_pk",
            )
            at_bat_number = _positive_integer(
                _value(row, "at_bat_number"),
                "at_bat_number",
            )
            pitcher_id = _positive_integer(
                _value(row, "pitcher_id"),
                "pitcher_id",
            )
            batter_id = _positive_integer(
                _value(row, "batter_id"),
                "batter_id",
            )
            game_date = _date(
                _value(row, "game_date")
            )
        except ValueError as exc:
            rejected_rows.append({
                "index": index,
                "reason": str(exc),
            })
            continue

        outcome = _EVENT_OUTCOMES.get(
            event_name
        )

        if outcome is None:
            rejected_rows.append({
                "index": index,
                "game_pk": game_pk,
                "at_bat_number": (
                    at_bat_number
                ),
                "event": event_name,
                "reason": (
                    "unsupported_terminal_event"
                ),
            })
            continue

        identity = (
            game_pk,
            at_bat_number,
        )
        terminal = {
            "game_pk": game_pk,
            "game_date": game_date.isoformat(),
            "season": game_date.year,
            "at_bat_number": at_bat_number,
            "pitcher_id": pitcher_id,
            "batter_id": batter_id,
            "event": event_name,
            "outcome": outcome,
        }

        if identity in conflicting_identities:
            duplicate_terminal_rows += 1
            continue

        existing = terminal_by_identity.get(
            identity
        )

        if existing is None:
            terminal_by_identity[
                identity
            ] = terminal
            continue

        comparable_fields = (
            "game_date",
            "pitcher_id",
            "batter_id",
            "outcome",
        )

        if all(
            existing[field] == terminal[field]
            for field in comparable_fields
        ):
            duplicate_terminal_rows += 1
            continue

        terminal_by_identity.pop(
            identity,
            None,
        )
        conflicting_identities.add(
            identity
        )
        rejected_rows.append({
            "index": index,
            "game_pk": game_pk,
            "at_bat_number": (
                at_bat_number
            ),
            "reason": (
                "conflicting_terminal_pa_identity"
            ),
        })

    grouped: dict[
        tuple[int, int, int],
        dict[str, Any],
    ] = {}

    for terminal in terminal_by_identity.values():
        group_key = (
            terminal["game_pk"],
            terminal["pitcher_id"],
            terminal["batter_id"],
        )
        group = grouped.get(group_key)

        if group is None:
            group = {
                "season": terminal["season"],
                "game_pk": terminal["game_pk"],
                "game_date": (
                    terminal["game_date"]
                ),
                "pitcher_id": (
                    terminal["pitcher_id"]
                ),
                "batter_id": (
                    terminal["batter_id"]
                ),
                "comparison_id": (
                    f"{terminal['game_pk']}:"
                    f"{terminal['pitcher_id']}:"
                    f"{terminal['batter_id']}"
                ),
                "observed_counts": (
                    _empty_counts()
                ),
            }
            grouped[group_key] = group

        group["observed_counts"][
            terminal["outcome"]
        ] += 1

    samples = [
        grouped[key]
        for key in sorted(grouped)
    ]

    if samples and rejected_rows:
        status = "partial"
    elif samples:
        status = "ready"
    else:
        status = "unavailable"

    diagnostics = {
        "schema_version": SCHEMA_VERSION,
        "status": status,
        "raw_row_count": len(rows),
        "nonterminal_pitch_row_count": (
            nonterminal_pitch_rows
        ),
        "terminal_pa_count": len(
            terminal_by_identity
        ),
        "duplicate_terminal_row_count": (
            duplicate_terminal_rows
        ),
        "conflicting_terminal_pa_count": (
            len(conflicting_identities)
        ),
        "sample_count": len(samples),
        "rejected_row_count": len(
            rejected_rows
        ),
        "rejected_rows": rejected_rows,
        "grouping_policy": (
            "game_pitcher_batter"
        ),
        "terminal_identity": (
            "game_pk_at_bat_number"
        ),
        "intentional_walk_policy": (
            "mapped_to_canonical_bb"
        ),
        "unsupported_event_policy": (
            "fail_closed"
        ),
        "shadow_only": True,
        "production_authority": False,
        "production_authority_changed": False,
    }
    diagnostics["outcome_digest"] = _digest({
        "samples": samples,
        "diagnostics": diagnostics,
    })

    return {
        "samples": samples,
        "diagnostics": diagnostics,
    }

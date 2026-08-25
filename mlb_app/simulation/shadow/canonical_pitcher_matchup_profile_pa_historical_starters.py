"""Identify historical starters and their realized Statcast plate appearances.

The home starter is the first pitcher recorded in the top half; the away
starter is the first pitcher recorded in the bottom half. Only terminal PAs
against those inferred starters are exposed for historical scoring.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
from collections import defaultdict
from typing import Any, Iterable, Mapping


SCHEMA_VERSION = (
    "canonical_pitcher_matchup_profile_pa_historical_starters_v1"
)


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


def _optional_integer(
    value: Any,
    default: int,
) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default

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


def _half(value: Any) -> str:
    normalized = str(
        value or ""
    ).strip().lower()

    if normalized in {
        "top",
        "t",
    }:
        return "top"

    if normalized in {
        "bot",
        "bottom",
        "b",
    }:
        return "bottom"

    raise ValueError(
        "inning_topbot_must_be_top_or_bottom"
    )


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


def _identity(row: Any) -> tuple[int, int]:
    return (
        _positive_integer(
            _value(row, "game_pk"),
            "game_pk",
        ),
        _positive_integer(
            _value(row, "at_bat_number"),
            "at_bat_number",
        ),
    )


def _order(row: Any) -> tuple[int, int, int]:
    return (
        _optional_integer(
            _value(row, "inning"),
            999,
        ),
        _optional_integer(
            _value(row, "at_bat_number"),
            999999,
        ),
        _optional_integer(
            _value(row, "pitch_number"),
            999,
        ),
    )


def source_canonical_pitcher_matchup_profile_pa_historical_starters(
    events: Iterable[Any],
) -> dict[str, Any]:
    """Infer starters and select their terminal historical PAs."""
    rows = list(events)
    terminal_by_identity: dict[
        tuple[int, int],
        Any,
    ] = {}
    duplicate_terminal_count = 0
    conflicting_identities: set[
        tuple[int, int]
    ] = set()
    rejected_rows = []

    for index, row in enumerate(rows):
        if _event(
            _value(row, "events")
        ) is None:
            continue

        try:
            identity = _identity(row)
            game_date = _date(
                _value(row, "game_date")
            )
            pitcher_id = _positive_integer(
                _value(row, "pitcher_id"),
                "pitcher_id",
            )
            batter_id = _positive_integer(
                _value(row, "batter_id"),
                "batter_id",
            )
            half = _half(
                _value(row, "inning_topbot")
            )
        except ValueError as exc:
            rejected_rows.append({
                "index": index,
                "reason": str(exc),
            })
            continue

        if identity in conflicting_identities:
            duplicate_terminal_count += 1
            continue

        normalized = {
            "row": row,
            "game_pk": identity[0],
            "at_bat_number": identity[1],
            "game_date": game_date,
            "pitcher_id": pitcher_id,
            "batter_id": batter_id,
            "half": half,
            "event": _event(
                _value(row, "events")
            ),
            "order": _order(row),
        }
        existing = terminal_by_identity.get(
            identity
        )

        if existing is None:
            terminal_by_identity[
                identity
            ] = normalized
            continue

        comparable = (
            "game_date",
            "pitcher_id",
            "batter_id",
            "half",
            "event",
        )

        if all(
            existing[name] == normalized[name]
            for name in comparable
        ):
            duplicate_terminal_count += 1
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
            "game_pk": identity[0],
            "at_bat_number": identity[1],
            "reason": (
                "conflicting_terminal_pa_identity"
            ),
        })

    games = defaultdict(list)

    for terminal in (
        terminal_by_identity.values()
    ):
        games[terminal["game_pk"]].append(
            terminal
        )

    starter_records = []
    requests = []
    starter_events = []
    rejected_games = []

    for game_pk in sorted(games):
        terminals = sorted(
            games[game_pk],
            key=lambda value: value["order"],
        )
        game_dates = {
            value["game_date"]
            for value in terminals
        }

        if len(game_dates) != 1:
            rejected_games.append({
                "game_pk": game_pk,
                "reason": (
                    "conflicting_game_dates"
                ),
            })
            continue

        game_date = next(iter(game_dates))
        top = [
            value
            for value in terminals
            if value["half"] == "top"
        ]
        bottom = [
            value
            for value in terminals
            if value["half"] == "bottom"
        ]

        if not top or not bottom:
            rejected_games.append({
                "game_pk": game_pk,
                "game_date": (
                    game_date.isoformat()
                ),
                "reason": (
                    "both_game_halves_required"
                ),
            })
            continue

        home_starter = top[0]["pitcher_id"]
        away_starter = bottom[0][
            "pitcher_id"
        ]

        home_starter_pas = [
            value
            for value in top
            if value["pitcher_id"]
            == home_starter
        ]
        away_starter_pas = [
            value
            for value in bottom
            if value["pitcher_id"]
            == away_starter
        ]

        starter_records.append({
            "game_pk": game_pk,
            "game_date": (
                game_date.isoformat()
            ),
            "away_starter_id": (
                away_starter
            ),
            "home_starter_id": (
                home_starter
            ),
            "away_starter_pa_count": len(
                away_starter_pas
            ),
            "home_starter_pa_count": len(
                home_starter_pas
            ),
        })
        requests.extend([
            {
                "game_pk": game_pk,
                "pitcher_id": (
                    away_starter
                ),
                "game_date": game_date,
                "side": "away",
            },
            {
                "game_pk": game_pk,
                "pitcher_id": (
                    home_starter
                ),
                "game_date": game_date,
                "side": "home",
            },
        ])
        starter_events.extend(
            value["row"]
            for value in (
                home_starter_pas
                + away_starter_pas
            )
        )

    starter_events.sort(
        key=lambda row: (
            _positive_integer(
                _value(row, "game_pk"),
                "game_pk",
            ),
            _positive_integer(
                _value(row, "at_bat_number"),
                "at_bat_number",
            ),
        )
    )
    requests.sort(
        key=lambda value: (
            value["game_date"],
            value["game_pk"],
            value["pitcher_id"],
        )
    )

    if (
        starter_records
        and (
            rejected_rows
            or rejected_games
        )
    ):
        status = "partial"
    elif starter_records:
        status = "ready"
    else:
        status = "unavailable"

    diagnostics = {
        "schema_version": SCHEMA_VERSION,
        "status": status,
        "raw_event_count": len(rows),
        "terminal_pa_count": len(
            terminal_by_identity
        ),
        "duplicate_terminal_count": (
            duplicate_terminal_count
        ),
        "conflicting_terminal_count": (
            len(conflicting_identities)
        ),
        "game_count": len(games),
        "ready_game_count": len(
            starter_records
        ),
        "rejected_game_count": len(
            rejected_games
        ),
        "starter_request_count": len(
            requests
        ),
        "starter_pa_count": len(
            starter_events
        ),
        "rejected_row_count": len(
            rejected_rows
        ),
        "rejected_rows": rejected_rows,
        "rejected_games": rejected_games,
        "starter_records": (
            starter_records
        ),
        "starter_inference": {
            "home": (
                "first_pitcher_in_top_half"
            ),
            "away": (
                "first_pitcher_in_bottom_half"
            ),
        },
        "scoring_scope": (
            "terminal_pas_against_inferred_starters"
        ),
        "shadow_only": True,
        "production_authority": False,
        "production_authority_changed": False,
    }
    diagnostics["starter_window_digest"] = (
        _digest({
            "starter_records": (
                starter_records
            ),
            "requests": requests,
            "diagnostics": diagnostics,
        })
    )

    return {
        "starter_events": starter_events,
        "requests": requests,
        "diagnostics": diagnostics,
    }

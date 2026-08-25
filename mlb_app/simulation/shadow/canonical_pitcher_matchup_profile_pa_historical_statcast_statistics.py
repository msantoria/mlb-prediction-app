"""Build cutoff-safe historical PA statistics from local Statcast events.

The source emits the existing canonical historical statistics contract for one
target game. Only same-season terminal PAs strictly before the target game date
are eligible.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
from collections import defaultdict
from typing import Any, Iterable, Mapping, Sequence

from mlb_app.simulation.shadow.historical_probability_statistics_source import (
    HITTING_STAT_KEYS,
    PITCHING_STAT_KEYS,
    CanonicalHistoricalProbabilityGameStatistics,
    CanonicalHistoricalProbabilityPlayerStatistics,
    CanonicalHistoricalProbabilityStatisticsWindow,
)


SCHEMA_VERSION = (
    "canonical_pitcher_matchup_profile_pa_historical_statcast_statistics_v1"
)

_HIT_EVENTS = {
    "single": "single",
    "double": "double",
    "triple": "triple",
    "home_run": "hr",
}

_STRIKEOUT_EVENTS = {
    "strikeout",
    "strikeout_double_play",
}

_WALK_EVENTS = {
    "walk",
    "intent_walk",
}

_NO_AT_BAT_EVENTS = {
    "walk",
    "intent_walk",
    "hit_by_pitch",
    "catcher_interf",
    "sac_fly",
    "sac_bunt",
}

_SUPPORTED_TERMINAL_EVENTS = {
    *_HIT_EVENTS,
    *_STRIKEOUT_EVENTS,
    *_WALK_EVENTS,
    "hit_by_pitch",
    "catcher_interf",
    "field_error",
    "field_out",
    "force_out",
    "grounded_into_double_play",
    "double_play",
    "triple_play",
    "fielders_choice",
    "fielders_choice_out",
    "sac_fly",
    "sac_bunt",
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


def _digest_value(
    value: Any,
    name: str,
) -> str:
    normalized = str(value)

    if (
        len(normalized) != 64
        or any(
            character
            not in "0123456789abcdef"
            for character in normalized
        )
    ):
        raise ValueError(
            f"{name}_must_be_sha256_digest"
        )

    return normalized


def _identifiers(
    values: Sequence[Any],
    name: str,
) -> tuple[int, ...]:
    if isinstance(values, (str, bytes)):
        raise TypeError(
            f"{name}_must_be_sequence"
        )

    normalized = tuple(
        sorted({
            _positive_integer(
                value,
                name,
            )
            for value in values
        })
    )

    if not normalized:
        raise ValueError(
            f"{name}_must_not_be_empty"
        )

    return normalized


def _empty_hitting() -> dict[str, int]:
    return {
        key: 0
        for key, _ in HITTING_STAT_KEYS
    }


def _empty_pitching() -> dict[str, int]:
    return {
        key: 0
        for key, _ in PITCHING_STAT_KEYS
    }


def _ordered_counts(
    keys: tuple[tuple[str, str], ...],
    values: Mapping[str, int],
) -> tuple[tuple[str, int], ...]:
    return tuple(
        (
            key,
            int(values.get(key, 0)),
        )
        for key, _ in keys
    )


def source_canonical_pitcher_matchup_profile_pa_historical_statcast_statistics(
    events: Iterable[Any],
    *,
    game_pk: int,
    game_date: dt.date | str,
    batter_ids: Sequence[int],
    pitcher_ids: Sequence[int],
    observed_window_digest: str,
    lineup_bullpen_window_digest: str,
) -> dict[str, Any]:
    """Build one strict-pregame canonical statistics window."""
    target_game_pk = _positive_integer(
        game_pk,
        "game_pk",
    )
    cutoff = _date(game_date)
    batters = _identifiers(
        batter_ids,
        "batter_id",
    )
    pitchers = _identifiers(
        pitcher_ids,
        "pitcher_id",
    )
    observed_digest = _digest_value(
        observed_window_digest,
        "observed_window_digest",
    )
    lineup_digest = _digest_value(
        lineup_bullpen_window_digest,
        "lineup_bullpen_window_digest",
    )

    rows = list(events)
    terminal_by_identity = {}
    conflicting_identities = set()
    duplicate_terminal_count = 0
    rejected_rows = []
    excluded_future_or_same_day = 0
    excluded_other_season = 0
    nonterminal_pitch_count = 0

    for index, row in enumerate(rows):
        event_name = _event(
            _value(row, "events")
        )

        if event_name is None:
            nonterminal_pitch_count += 1
            continue

        try:
            row_date = _date(
                _value(row, "game_date")
            )
            row_game_pk = _positive_integer(
                _value(row, "game_pk"),
                "row_game_pk",
            )
            at_bat_number = _positive_integer(
                _value(row, "at_bat_number"),
                "at_bat_number",
            )
            pitcher_id = _positive_integer(
                _value(row, "pitcher_id"),
                "row_pitcher_id",
            )
            batter_id = _positive_integer(
                _value(row, "batter_id"),
                "row_batter_id",
            )
        except ValueError as exc:
            rejected_rows.append({
                "index": index,
                "reason": str(exc),
            })
            continue

        if row_date.year != cutoff.year:
            excluded_other_season += 1
            continue

        if row_date >= cutoff:
            excluded_future_or_same_day += 1
            continue

        if event_name not in (
            _SUPPORTED_TERMINAL_EVENTS
        ):
            rejected_rows.append({
                "index": index,
                "event": event_name,
                "reason": (
                    "unsupported_terminal_event"
                ),
            })
            continue

        identity = (
            row_game_pk,
            at_bat_number,
        )
        normalized = {
            "game_date": row_date,
            "pitcher_id": pitcher_id,
            "batter_id": batter_id,
            "event": event_name,
        }

        if identity in conflicting_identities:
            duplicate_terminal_count += 1
            continue

        existing = terminal_by_identity.get(
            identity
        )

        if existing is None:
            terminal_by_identity[
                identity
            ] = normalized
            continue

        if existing == normalized:
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
            "game_pk": row_game_pk,
            "at_bat_number": (
                at_bat_number
            ),
            "reason": (
                "conflicting_terminal_pa_identity"
            ),
        })

    hitting = defaultdict(
        _empty_hitting
    )
    pitching = defaultdict(
        _empty_pitching
    )

    for terminal in (
        terminal_by_identity.values()
    ):
        batter = hitting[
            terminal["batter_id"]
        ]
        pitcher = pitching[
            terminal["pitcher_id"]
        ]
        event_name = terminal["event"]

        batter["pa"] += 1
        pitcher["batters_faced"] += 1

        if event_name not in _NO_AT_BAT_EVENTS:
            batter["ab"] += 1
            pitcher["ab"] += 1

        hit_key = _HIT_EVENTS.get(
            event_name
        )

        if hit_key is not None:
            batter["hits"] += 1
            pitcher["hits"] += 1

            if hit_key != "single":
                batter[hit_key] += 1
                pitcher[hit_key] += 1

        if event_name in _WALK_EVENTS:
            batter["bb"] += 1
            pitcher["bb"] += 1

        if event_name in _STRIKEOUT_EVENTS:
            batter["k"] += 1
            pitcher["k"] += 1

        if event_name == "hit_by_pitch":
            batter["hbp"] += 1
            pitcher["hbp"] += 1

    players = []

    for batter_id in batters:
        values = hitting.get(
            batter_id,
            _empty_hitting(),
        )
        sample_available = (
            values["pa"] > 0
        )

        players.append(
            CanonicalHistoricalProbabilityPlayerStatistics(
                player_id=str(batter_id),
                role="hitting",
                counts=_ordered_counts(
                    HITTING_STAT_KEYS,
                    values,
                ),
                sample_available=(
                    sample_available
                ),
            )
        )

    for pitcher_id in pitchers:
        values = pitching.get(
            pitcher_id,
            _empty_pitching(),
        )
        sample_available = (
            values["batters_faced"] > 0
        )

        players.append(
            CanonicalHistoricalProbabilityPlayerStatistics(
                player_id=str(pitcher_id),
                role="pitching",
                counts=_ordered_counts(
                    PITCHING_STAT_KEYS,
                    values,
                ),
                sample_available=(
                    sample_available
                ),
            )
        )

    snapshot_payload = {
        "schema_version": SCHEMA_VERSION,
        "game_pk": target_game_pk,
        "game_date": cutoff.isoformat(),
        "statistics_through_date": (
            cutoff - dt.timedelta(days=1)
        ).isoformat(),
        "players": [
            {
                "player_id": player.player_id,
                "role": player.role,
                "counts": player.counts,
                "sample_available": (
                    player.sample_available
                ),
            }
            for player in players
        ],
    }
    snapshot_digest = _digest(
        snapshot_payload
    )

    game = (
        CanonicalHistoricalProbabilityGameStatistics(
            game_pk=target_game_pk,
            game_date=cutoff.isoformat(),
            statistics_through_date=(
                cutoff - dt.timedelta(days=1)
            ).isoformat(),
            players=tuple(players),
            snapshot_digest=snapshot_digest,
        )
    )
    window_digest = _digest({
        "schema_version": SCHEMA_VERSION,
        "observed_window_digest": (
            observed_digest
        ),
        "lineup_bullpen_window_digest": (
            lineup_digest
        ),
        "game": snapshot_payload,
    })
    statistics = (
        CanonicalHistoricalProbabilityStatisticsWindow(
            observed_window_digest=(
                observed_digest
            ),
            lineup_bullpen_window_digest=(
                lineup_digest
            ),
            games=(game,),
            digest=window_digest,
        )
    )

    observed_player_count = sum(
        player.sample_available
        for player in players
    )

    if observed_player_count == len(players):
        status = (
            "partial"
            if rejected_rows
            else "ready"
        )
    elif observed_player_count > 0:
        status = "partial"
    else:
        status = "unavailable"

    diagnostics = {
        "schema_version": SCHEMA_VERSION,
        "status": status,
        "game_pk": target_game_pk,
        "game_date": cutoff.isoformat(),
        "statistics_through_date": (
            cutoff - dt.timedelta(days=1)
        ).isoformat(),
        "raw_event_count": len(rows),
        "eligible_terminal_pa_count": len(
            terminal_by_identity
        ),
        "duplicate_terminal_count": (
            duplicate_terminal_count
        ),
        "conflicting_terminal_count": (
            len(conflicting_identities)
        ),
        "nonterminal_pitch_count": (
            nonterminal_pitch_count
        ),
        "excluded_future_or_same_day_count": (
            excluded_future_or_same_day
        ),
        "excluded_other_season_count": (
            excluded_other_season
        ),
        "requested_batter_count": len(
            batters
        ),
        "requested_pitcher_count": len(
            pitchers
        ),
        "observed_player_role_count": (
            observed_player_count
        ),
        "zero_sample_player_role_count": (
            len(players)
            - observed_player_count
        ),
        "rejected_row_count": len(
            rejected_rows
        ),
        "rejected_rows": rejected_rows,
        "cutoff_rule": (
            "same_season_terminal_pas_strictly_before_game_date"
        ),
        "intentional_walk_policy": (
            "included_in_historical_bb"
        ),
        "source": (
            "local_statcast_terminal_pa_history"
        ),
        "snapshot_digest": (
            snapshot_digest
        ),
        "statistics_window_digest": (
            statistics.digest
        ),
        "shadow_only": True,
        "production_authority": False,
        "production_authority_changed": False,
    }

    return {
        "statistics": statistics,
        "diagnostics": diagnostics,
    }

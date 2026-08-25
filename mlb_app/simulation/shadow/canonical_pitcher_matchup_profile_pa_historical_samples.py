"""Pair historical PA outcomes with production and pitcher-profile models.

This materializer consumes already cutoff-safe historical statistics and
cutoff-specific pitcher candidates. It does not query future data, select
calibration parameters, or change production authority.
"""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from typing import Any, Mapping

from mlb_app.simulation.shadow.canonical_pitcher_matchup_profile_pa_comparator import (
    compare_canonical_pitcher_matchup_profile_pa_outcomes,
)
from mlb_app.simulation.shadow.historical_probability_statistics_source import (
    CanonicalHistoricalProbabilityStatisticsWindow,
)
from mlb_app.simulation.shadow.historical_probability_workspace_reconstruction import (
    build_historical_probability_offense_profile,
    build_historical_probability_pitcher_profile,
)


SCHEMA_VERSION = (
    "canonical_pitcher_matchup_profile_pa_historical_samples_v1"
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


def _mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    return {}


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


def _candidate_key(
    value: Any,
) -> tuple[int, int]:
    if (
        not isinstance(value, tuple)
        or len(value) != 2
    ):
        raise ValueError(
            "candidate_key_must_be_game_pitcher_tuple"
        )

    return (
        _positive_integer(
            value[0],
            "candidate_game_pk",
        ),
        _positive_integer(
            value[1],
            "candidate_pitcher_id",
        ),
    )


def _observed_counts(
    value: Any,
) -> dict[str, int]:
    source = _mapping(value)
    counts = {}

    if tuple(source) != OUTCOME_KEYS:
        raise ValueError(
            "observed_counts_must_use_canonical_order"
        )

    for outcome in OUTCOME_KEYS:
        raw = source.get(outcome)

        if (
            not isinstance(raw, int)
            or isinstance(raw, bool)
            or raw < 0
        ):
            raise ValueError(
                "observed_counts_must_be_nonnegative_integers"
            )

        counts[outcome] = raw

    if sum(counts.values()) <= 0:
        raise ValueError(
            "observed_counts_must_be_positive"
        )

    return counts


def _normalize_candidates(
    candidates: Mapping[Any, Any],
) -> dict[tuple[int, int], dict[str, Any]]:
    if not isinstance(candidates, Mapping):
        raise TypeError(
            "candidates_by_game_pitcher_must_be_mapping"
        )

    normalized = {}

    for raw_key, raw_candidate in (
        candidates.items()
    ):
        key = _candidate_key(raw_key)

        if key in normalized:
            raise ValueError(
                "duplicate_candidate_game_pitcher"
            )

        if not isinstance(
            raw_candidate,
            Mapping,
        ):
            raise TypeError(
                "candidate_payload_must_be_mapping"
            )

        normalized[key] = deepcopy(
            dict(raw_candidate)
        )

    return normalized


def materialize_canonical_pitcher_matchup_profile_pa_historical_samples(
    outcomes: Mapping[str, Any],
    *,
    statistics: CanonicalHistoricalProbabilityStatisticsWindow,
    candidates_by_game_pitcher: Mapping[
        tuple[int, int],
        Mapping[str, Any],
    ],
) -> dict[str, Any]:
    """Build evaluator-ready paired historical PA samples."""
    if not isinstance(outcomes, Mapping):
        raise TypeError(
            "outcomes_must_be_mapping"
        )

    if not isinstance(
        statistics,
        CanonicalHistoricalProbabilityStatisticsWindow,
    ):
        raise TypeError(
            "statistics_must_be_canonical_window"
        )

    raw_samples = outcomes.get("samples")

    if not isinstance(raw_samples, list):
        raise TypeError(
            "outcome_samples_must_be_list"
        )

    candidates = _normalize_candidates(
        candidates_by_game_pitcher
    )
    statistics_games = {
        game.game_pk: game
        for game in statistics.games
    }

    materialized = []
    rejected = []
    identities = set()

    values = sorted(
        (
            deepcopy(dict(sample))
            for sample in raw_samples
            if isinstance(sample, Mapping)
        ),
        key=_digest,
    )

    invalid_shape_count = (
        len(raw_samples) - len(values)
    )

    for index, sample in enumerate(values):
        comparison_id = str(
            sample.get(
                "comparison_id",
                f"invalid:{index}",
            )
        )

        try:
            game_pk = _positive_integer(
                sample.get("game_pk"),
                "game_pk",
            )
            pitcher_id = _positive_integer(
                sample.get("pitcher_id"),
                "pitcher_id",
            )
            batter_id = _positive_integer(
                sample.get("batter_id"),
                "batter_id",
            )
            season = _positive_integer(
                sample.get("season"),
                "season",
            )
            game_date = str(
                sample["game_date"]
            )
            observed_counts = _observed_counts(
                sample.get("observed_counts")
            )

            identity = (
                game_pk,
                pitcher_id,
                batter_id,
                comparison_id,
            )

            if identity in identities:
                raise ValueError(
                    "duplicate_historical_comparison"
                )

            identities.add(identity)

            statistics_game = (
                statistics_games.get(game_pk)
            )

            if statistics_game is None:
                raise ValueError(
                    "historical_statistics_game_unavailable"
                )

            if (
                statistics_game.game_date
                != game_date
            ):
                raise ValueError(
                    "historical_statistics_game_date_mismatch"
                )

            records = {
                record.record_key: record
                for record in (
                    statistics_game.players
                )
            }

            batter_record = records.get(
                ("hitting", str(batter_id))
            )
            pitcher_record = records.get(
                ("pitching", str(pitcher_id))
            )

            if batter_record is None:
                raise ValueError(
                    "historical_batter_statistics_unavailable"
                )

            if pitcher_record is None:
                raise ValueError(
                    "historical_pitcher_statistics_unavailable"
                )

            if not batter_record.sample_available:
                raise ValueError(
                    "historical_batter_sample_unavailable"
                )

            if not pitcher_record.sample_available:
                raise ValueError(
                    "historical_pitcher_sample_unavailable"
                )

            candidate = candidates.get(
                (game_pk, pitcher_id)
            )

            if candidate is None:
                raise ValueError(
                    "historical_pitcher_candidate_unavailable"
                )

            batter_profile = (
                build_historical_probability_offense_profile(
                    dict(batter_record.counts)
                )
            )
            pitcher_profile = (
                build_historical_probability_pitcher_profile(
                    dict(pitcher_record.counts)
                )
            )

            comparison = (
                compare_canonical_pitcher_matchup_profile_pa_outcomes(
                    candidate=candidate,
                    production_pitcher_profile=(
                        pitcher_profile
                    ),
                    batter_profile=batter_profile,
                    environment_profile={},
                )
            )

            if (
                comparison.get("status")
                != "ready"
                or comparison.get("executed")
                is not True
            ):
                blockers = comparison.get(
                    "blockers"
                ) or []
                blocker = (
                    str(blockers[0])
                    if blockers
                    else "unknown"
                )
                raise ValueError(
                    "historical_pa_comparison_blocked:"
                    + blocker
                )

            if (
                comparison.get(
                    "production_inputs_unchanged"
                )
                is not True
                or comparison.get(
                    "production_authority_changed"
                )
                is not False
            ):
                raise ValueError(
                    "historical_pa_authority_contract_invalid"
                )

            materialized.append({
                "season": season,
                "game_pk": str(game_pk),
                "comparison_id": comparison_id,
                "pitcher_id": pitcher_id,
                "batter_id": batter_id,
                "game_date": game_date,
                "production_probabilities": dict(
                    comparison[
                        "production_probabilities"
                    ]
                ),
                "candidate_probabilities": dict(
                    comparison[
                        "shadow_probabilities"
                    ]
                ),
                "observed_counts": (
                    observed_counts
                ),
                "maximum_absolute_probability_delta": (
                    comparison[
                        "maximum_absolute_probability_delta"
                    ]
                ),
                "applied_rates": dict(
                    comparison["applied_rates"]
                ),
                "deferred_rates": dict(
                    comparison["deferred_rates"]
                ),
            })
        except (
            KeyError,
            TypeError,
            ValueError,
        ) as exc:
            rejected.append({
                "index": index,
                "comparison_id": comparison_id,
                "reason": str(exc),
            })

    materialized.sort(
        key=lambda sample: (
            sample["season"],
            int(sample["game_pk"]),
            sample["pitcher_id"],
            sample["batter_id"],
            sample["comparison_id"],
        )
    )

    if materialized and (
        rejected
        or invalid_shape_count
    ):
        status = "partial"
    elif materialized:
        status = "ready"
    else:
        status = "unavailable"

    outcome_diagnostics = _mapping(
        outcomes.get("diagnostics")
    )

    diagnostics = {
        "schema_version": SCHEMA_VERSION,
        "status": status,
        "outcome_sample_count": len(
            raw_samples
        ),
        "materialized_sample_count": len(
            materialized
        ),
        "rejected_sample_count": len(
            rejected
        ),
        "invalid_sample_shape_count": (
            invalid_shape_count
        ),
        "candidate_count": len(candidates),
        "statistics_game_count": len(
            statistics_games
        ),
        "rejected_samples": rejected,
        "pairing_policy": (
            "game_pitcher_batter_cutoff_safe"
        ),
        "candidate_identity": (
            "game_pk_pitcher_id"
        ),
        "historical_environment_policy": (
            "neutral_environment_no_archived_forecast_v1"
        ),
        "outcome_digest": (
            outcome_diagnostics.get(
                "outcome_digest"
            )
        ),
        "statistics_window_digest": (
            statistics.digest
        ),
        "shadow_only": True,
        "production_inputs_unchanged": True,
        "production_authority": False,
        "production_authority_changed": False,
    }
    diagnostics["sample_digest"] = _digest({
        "samples": materialized,
        "diagnostics": diagnostics,
    })

    return {
        "samples": materialized,
        "diagnostics": diagnostics,
    }

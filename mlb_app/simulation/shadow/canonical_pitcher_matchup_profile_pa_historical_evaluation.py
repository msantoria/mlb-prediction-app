"""Historical paired scoring for canonical pitcher PA candidates."""

from __future__ import annotations

import hashlib
import json
import math
from collections import defaultdict
from copy import deepcopy
from typing import Any, Iterable, Mapping


SCHEMA_VERSION = (
    "canonical_pitcher_matchup_profile_pa_"
    "historical_evaluation_v1"
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

PROBABILITY_SUM_TOLERANCE = 0.002
PROBABILITY_FLOOR = 1e-12


def _digest(value: Any) -> str:
    payload = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")

    return hashlib.sha256(payload).hexdigest()


def _mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    return {}


def _probabilities(
    value: Any,
) -> dict[str, float]:
    source = _mapping(value)
    probabilities = {}

    for outcome in OUTCOME_KEYS:
        raw = source.get(outcome)

        if not isinstance(raw, (int, float)):
            raise ValueError(
                f"missing probability: {outcome}"
            )

        probability = float(raw)

        if (
            not math.isfinite(probability)
            or probability < 0.0
            or probability > 1.0
        ):
            raise ValueError(
                f"invalid probability: {outcome}"
            )

        probabilities[outcome] = probability

    total = sum(probabilities.values())

    if abs(total - 1.0) > (
        PROBABILITY_SUM_TOLERANCE
    ):
        raise ValueError(
            "probability distribution must sum to one"
        )

    if total <= 0.0:
        raise ValueError(
            "probability distribution is empty"
        )

    return {
        outcome: (
            probabilities[outcome] / total
        )
        for outcome in OUTCOME_KEYS
    }


def _observed_counts(
    value: Any,
) -> dict[str, int]:
    source = _mapping(value)
    counts = {}

    for outcome in OUTCOME_KEYS:
        raw = source.get(outcome, 0)

        if (
            not isinstance(raw, int)
            or isinstance(raw, bool)
            or raw < 0
        ):
            raise ValueError(
                f"invalid observed count: {outcome}"
            )

        counts[outcome] = raw

    if sum(counts.values()) <= 0:
        raise ValueError(
            "observed PA count must be positive"
        )

    return counts


def _score_distribution(
    probabilities: Mapping[str, float],
    observed_counts: Mapping[str, int],
) -> dict[str, float | int]:
    trials = sum(observed_counts.values())
    log_loss_sum = 0.0
    brier_sum = 0.0
    probability_square_sum = sum(
        float(probabilities[outcome]) ** 2
        for outcome in OUTCOME_KEYS
    )

    for outcome in OUTCOME_KEYS:
        count = int(
            observed_counts[outcome]
        )

        if count <= 0:
            continue

        probability = max(
            float(probabilities[outcome]),
            PROBABILITY_FLOOR,
        )
        log_loss_sum += (
            -count * math.log(probability)
        )
        brier_sum += count * (
            probability_square_sum
            - (2.0 * probability)
            + 1.0
        )

    return {
        "trials": trials,
        "log_loss_sum": log_loss_sum,
        "brier_sum": brier_sum,
    }


def _empty_accumulator() -> dict[str, Any]:
    return {
        "sample_count": 0,
        "observed_pa": 0,
        "production_log_loss_sum": 0.0,
        "candidate_log_loss_sum": 0.0,
        "production_brier_sum": 0.0,
        "candidate_brier_sum": 0.0,
    }


def _add_score(
    accumulator: dict[str, Any],
    *,
    production: Mapping[str, float | int],
    candidate: Mapping[str, float | int],
) -> None:
    trials = int(production["trials"])

    if trials != int(candidate["trials"]):
        raise ValueError(
            "paired scores must use equal trials"
        )

    accumulator["sample_count"] += 1
    accumulator["observed_pa"] += trials
    accumulator[
        "production_log_loss_sum"
    ] += float(production["log_loss_sum"])
    accumulator[
        "candidate_log_loss_sum"
    ] += float(candidate["log_loss_sum"])
    accumulator[
        "production_brier_sum"
    ] += float(production["brier_sum"])
    accumulator[
        "candidate_brier_sum"
    ] += float(candidate["brier_sum"])


def _finalize(
    accumulator: Mapping[str, Any],
) -> dict[str, Any]:
    observed_pa = int(
        accumulator["observed_pa"]
    )
    sample_count = int(
        accumulator["sample_count"]
    )

    if observed_pa <= 0:
        return {
            "sample_count": sample_count,
            "observed_pa": 0,
            "status": "unavailable",
        }

    production_log_loss = (
        float(
            accumulator[
                "production_log_loss_sum"
            ]
        )
        / observed_pa
    )
    candidate_log_loss = (
        float(
            accumulator[
                "candidate_log_loss_sum"
            ]
        )
        / observed_pa
    )
    production_brier = (
        float(
            accumulator[
                "production_brier_sum"
            ]
        )
        / observed_pa
    )
    candidate_brier = (
        float(
            accumulator[
                "candidate_brier_sum"
            ]
        )
        / observed_pa
    )

    return {
        "status": "ready",
        "sample_count": sample_count,
        "observed_pa": observed_pa,
        "production_log_loss": round(
            production_log_loss,
            12,
        ),
        "candidate_log_loss": round(
            candidate_log_loss,
            12,
        ),
        "absolute_log_loss_improvement": (
            round(
                production_log_loss
                - candidate_log_loss,
                12,
            )
        ),
        "relative_log_loss_improvement_pct": (
            round(
                (
                    (
                        production_log_loss
                        - candidate_log_loss
                    )
                    / production_log_loss
                    * 100.0
                )
                if production_log_loss > 0
                else 0.0,
                8,
            )
        ),
        "production_brier_score": round(
            production_brier,
            12,
        ),
        "candidate_brier_score": round(
            candidate_brier,
            12,
        ),
        "absolute_brier_improvement": round(
            production_brier
            - candidate_brier,
            12,
        ),
    }


def evaluate_canonical_pitcher_matchup_profile_pa_history(
    samples: Iterable[Mapping[str, Any]],
    *,
    minimum_samples: int = 30,
    minimum_observed_pa: int = 1000,
    season_log_loss_regression_tolerance: float = 0.0,
) -> dict[str, Any]:
    """Evaluate paired probabilities against realized PA outcome counts."""
    if (
        not isinstance(minimum_samples, int)
        or isinstance(minimum_samples, bool)
        or minimum_samples <= 0
    ):
        raise ValueError(
            "minimum_samples must be positive"
        )

    if (
        not isinstance(minimum_observed_pa, int)
        or isinstance(
            minimum_observed_pa,
            bool,
        )
        or minimum_observed_pa <= 0
    ):
        raise ValueError(
            "minimum_observed_pa must be positive"
        )

    tolerance = float(
        season_log_loss_regression_tolerance
    )

    if (
        not math.isfinite(tolerance)
        or tolerance < 0.0
    ):
        raise ValueError(
            "season regression tolerance must be nonnegative"
        )

    values = sorted(
        (
            deepcopy(dict(sample))
            for sample in samples
        ),
        key=_digest,
    )
    accepted = []
    rejected = []
    overall = _empty_accumulator()
    by_season = defaultdict(
        _empty_accumulator
    )
    identities = set()

    for index, sample in enumerate(values):
        try:
            season = int(sample["season"])
            game_pk = str(sample["game_pk"])
            comparison_id = str(
                sample.get(
                    "comparison_id",
                    f"{season}:{game_pk}:{index}",
                )
            )

            identity = (
                season,
                game_pk,
                comparison_id,
            )

            if identity in identities:
                raise ValueError(
                    "duplicate comparison identity"
                )

            identities.add(identity)

            production_probabilities = (
                _probabilities(
                    sample.get(
                        "production_probabilities"
                    )
                )
            )
            candidate_probabilities = (
                _probabilities(
                    sample.get(
                        "candidate_probabilities"
                    )
                )
            )
            observed_counts = (
                _observed_counts(
                    sample.get(
                        "observed_counts"
                    )
                )
            )

            production_score = (
                _score_distribution(
                    production_probabilities,
                    observed_counts,
                )
            )
            candidate_score = (
                _score_distribution(
                    candidate_probabilities,
                    observed_counts,
                )
            )

            _add_score(
                overall,
                production=production_score,
                candidate=candidate_score,
            )
            _add_score(
                by_season[season],
                production=production_score,
                candidate=candidate_score,
            )

            accepted.append({
                "season": season,
                "game_pk": game_pk,
                "comparison_id": comparison_id,
                "observed_pa": (
                    production_score["trials"]
                ),
            })
        except (
            KeyError,
            TypeError,
            ValueError,
        ) as exc:
            rejected.append({
                "index": index,
                "reason": str(exc),
            })

    overall_result = _finalize(overall)
    season_results = {
        str(season): _finalize(
            by_season[season]
        )
        for season in sorted(by_season)
    }

    blockers = []

    if len(accepted) < minimum_samples:
        blockers.append(
            "insufficient_sample_count"
        )

    if (
        int(overall_result.get(
            "observed_pa",
            0,
        ))
        < minimum_observed_pa
    ):
        blockers.append(
            "insufficient_observed_pa"
        )

    if (
        overall_result.get("status")
        != "ready"
    ):
        blockers.append(
            "paired_scores_unavailable"
        )
    else:
        if (
            overall_result[
                "absolute_log_loss_improvement"
            ]
            <= 0.0
        ):
            blockers.append(
                "candidate_log_loss_not_improved"
            )

        if (
            overall_result[
                "absolute_brier_improvement"
            ]
            < 0.0
        ):
            blockers.append(
                "candidate_brier_score_regressed"
            )

    regressed_seasons = []

    for season, result in (
        season_results.items()
    ):
        if result.get("status") != "ready":
            regressed_seasons.append(season)
            continue

        if (
            result[
                "candidate_log_loss"
            ]
            - result[
                "production_log_loss"
            ]
            > tolerance
        ):
            regressed_seasons.append(season)

    if regressed_seasons:
        blockers.append(
            "season_log_loss_instability"
        )

    selection_gate_passed = not blockers

    diagnostics = {
        "schema_version": SCHEMA_VERSION,
        "status": (
            "ready"
            if accepted
            else "unavailable"
        ),
        "accepted_sample_count": len(
            accepted
        ),
        "rejected_sample_count": len(
            rejected
        ),
        "minimum_samples": minimum_samples,
        "minimum_observed_pa": (
            minimum_observed_pa
        ),
        "season_log_loss_regression_tolerance": (
            tolerance
        ),
        "season_count": len(
            season_results
        ),
        "regressed_seasons": (
            regressed_seasons
        ),
        "blockers": blockers,
        "selection_gate_passed": (
            selection_gate_passed
        ),
        "activation_status": (
            "historical_pa_gate_passed"
            if selection_gate_passed
            else "historical_pa_gate_blocked"
        ),
        "shadow_only": True,
        "production_authority": False,
        "production_authority_changed": False,
    }
    diagnostics["evaluation_digest"] = (
        _digest({
            "accepted": accepted,
            "rejected": rejected,
            "overall": overall_result,
            "by_season": season_results,
            "diagnostics": diagnostics,
        })
    )

    return {
        "overall": overall_result,
        "by_season": season_results,
        "accepted_samples": accepted,
        "rejected_samples": rejected,
        "diagnostics": diagnostics,
    }

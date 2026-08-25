"""Holdout calibration for canonical pitcher-profile shrinkage."""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from typing import Any


CANONICAL_PITCHER_MATCHUP_PROFILE_SHRINKAGE_VERSION = (
    "canonical_pitcher_matchup_profile_shrinkage_v1"
)

DEFAULT_PSEUDO_COUNT_GRID = (
    0,
    25,
    50,
    100,
    200,
    400,
)


def _number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None

    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None

    return parsed if math.isfinite(parsed) else None


def _candidates(
    values: Sequence[int | float],
) -> tuple[float, ...]:
    candidates = tuple(float(value) for value in values)

    if not candidates:
        raise ValueError(
            "candidate pseudo-count grid must not be empty"
        )
    if any(
        not math.isfinite(value) or value < 0
        for value in candidates
    ):
        raise ValueError(
            "candidate pseudo-counts must be finite "
            "and nonnegative"
        )
    if len(set(candidates)) != len(candidates):
        raise ValueError(
            "candidate pseudo-counts must be unique"
        )

    return candidates


def _prepare(
    samples: Iterable[Mapping[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    ready = []
    rejected = []

    for index, raw in enumerate(samples):
        reasons = []
        metric = raw.get("metric")
        family = raw.get("family")
        segment = raw.get("segment") or "overall"
        season = raw.get("season")
        training_successes = _number(
            raw.get("training_successes")
        )
        training_trials = _number(
            raw.get("training_trials")
        )
        holdout_successes = _number(
            raw.get("holdout_successes")
        )
        holdout_trials = _number(
            raw.get("holdout_trials")
        )
        prior_probability = _number(
            raw.get("prior_probability")
        )

        if not isinstance(metric, str) or not metric:
            reasons.append("missing_metric")
        if not isinstance(family, str) or not family:
            reasons.append("missing_family")
        if season is None:
            reasons.append("missing_season")
        if training_trials is None or training_trials <= 0:
            reasons.append("invalid_training_trials")
        if (
            training_successes is None
            or training_successes < 0
            or (
                training_trials is not None
                and training_successes > training_trials
            )
        ):
            reasons.append("invalid_training_successes")
        if holdout_trials is None or holdout_trials <= 0:
            reasons.append("invalid_holdout_trials")
        if (
            holdout_successes is None
            or holdout_successes < 0
            or (
                holdout_trials is not None
                and holdout_successes > holdout_trials
            )
        ):
            reasons.append("invalid_holdout_successes")
        if (
            prior_probability is None
            or not 0 <= prior_probability <= 1
        ):
            reasons.append("invalid_prior_probability")

        if reasons:
            rejected.append({
                "sample_index": index,
                "reasons": sorted(set(reasons)),
            })
            continue

        ready.append({
            "metric": metric,
            "family": family,
            "segment": str(segment),
            "season": int(season),
            "training_successes": int(
                training_successes
            ),
            "training_trials": int(training_trials),
            "holdout_successes": int(
                holdout_successes
            ),
            "holdout_trials": int(holdout_trials),
            "prior_probability": float(
                prior_probability
            ),
        })

    return ready, rejected


def _prediction(
    sample: Mapping[str, Any],
    pseudo_count: float,
) -> tuple[float, float]:
    trials = float(sample["training_trials"])
    reliability = trials / (trials + pseudo_count)
    observed = (
        float(sample["training_successes"])
        / trials
    )
    prior = float(sample["prior_probability"])
    probability = (
        reliability * observed
        + (1.0 - reliability) * prior
    )

    return probability, reliability


def _score(
    samples: Sequence[Mapping[str, Any]],
    pseudo_count: float,
) -> dict[str, Any]:
    log_loss_sum = 0.0
    brier_sum = 0.0
    absolute_error_sum = 0.0
    total_trials = 0
    reliabilities = []

    for sample in samples:
        probability, reliability = _prediction(
            sample,
            pseudo_count,
        )
        probability = min(
            max(probability, 1e-12),
            1.0 - 1e-12,
        )
        successes = int(sample["holdout_successes"])
        trials = int(sample["holdout_trials"])
        failures = trials - successes
        observed = successes / trials

        log_loss_sum += -(
            successes * math.log(probability)
            + failures * math.log(1.0 - probability)
        )
        brier_sum += (
            successes * ((1.0 - probability) ** 2)
            + failures * (probability**2)
        )
        absolute_error_sum += (
            trials * abs(probability - observed)
        )
        total_trials += trials
        reliabilities.append(reliability)

    return {
        "pseudo_count": pseudo_count,
        "sample_count": len(samples),
        "holdout_trials": total_trials,
        "binomial_log_loss": (
            log_loss_sum / total_trials
            if total_trials
            else None
        ),
        "brier_score": (
            brier_sum / total_trials
            if total_trials
            else None
        ),
        "weighted_absolute_error": (
            absolute_error_sum / total_trials
            if total_trials
            else None
        ),
        "mean_training_reliability": (
            sum(reliabilities) / len(reliabilities)
            if reliabilities
            else None
        ),
    }


def _grid(
    samples: Sequence[Mapping[str, Any]],
    candidates: Sequence[float],
) -> list[dict[str, Any]]:
    return [
        _score(samples, candidate)
        for candidate in candidates
    ]


def _rank(
    grid: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    if not grid:
        raise ValueError("candidate grid is empty")

    return dict(min(
        grid,
        key=lambda row: (
            row["binomial_log_loss"],
            row["brier_score"],
            row["weighted_absolute_error"],
            row["pseudo_count"],
        ),
    ))


def _metric_result(
    samples: Sequence[Mapping[str, Any]],
    candidates: Sequence[float],
) -> dict[str, Any]:
    seasons = sorted({
        int(sample["season"])
        for sample in samples
    })
    blockers = []

    if not samples:
        blockers.append("no_eligible_samples")
    if len(seasons) < 2:
        blockers.append(
            "insufficient_cross_season_coverage"
        )

    if blockers:
        return {
            "status": "blocked",
            "blockers": blockers,
            "sample_count": len(samples),
            "seasons": seasons,
        }

    pooled_grid = _grid(samples, candidates)
    pooled_candidate = _rank(pooled_grid)
    folds = []
    selected_candidates = []

    for validation_season in seasons:
        training = [
            sample
            for sample in samples
            if sample["season"] != validation_season
        ]
        validation = [
            sample
            for sample in samples
            if sample["season"] == validation_season
        ]
        selected = _rank(_grid(training, candidates))
        pseudo_count = selected["pseudo_count"]
        selected_candidates.append(pseudo_count)

        folds.append({
            "validation_season": validation_season,
            "training_seasons": sorted({
                int(sample["season"])
                for sample in training
            }),
            "selected_pseudo_count": pseudo_count,
            "training_scores": selected,
            "validation_scores": _score(
                validation,
                pseudo_count,
            ),
            "candidate_reselected_on_validation": False,
        })

    segment_diagnostics = {}

    for segment in sorted({
        str(sample["segment"])
        for sample in samples
    }):
        subset = [
            sample
            for sample in samples
            if sample["segment"] == segment
        ]
        segment_diagnostics[segment] = {
            "sample_count": len(subset),
            "best_candidate": _rank(
                _grid(subset, candidates)
            ),
        }

    return {
        "status": "ready",
        "sample_count": len(samples),
        "holdout_trials": sum(
            int(sample["holdout_trials"])
            for sample in samples
        ),
        "seasons": seasons,
        "pooled_candidate": pooled_candidate,
        "pooled_grid": pooled_grid,
        "cross_season_folds": folds,
        "cross_season_candidate_range": {
            "minimum": min(selected_candidates),
            "maximum": max(selected_candidates),
            "spread": (
                max(selected_candidates)
                - min(selected_candidates)
            ),
        },
        "segment_diagnostics": segment_diagnostics,
    }


def calibrate_canonical_pitcher_matchup_profile_shrinkage(
    samples: Iterable[Mapping[str, Any]],
    *,
    candidate_pseudo_counts: Sequence[int | float] = (
        DEFAULT_PSEUDO_COUNT_GRID
    ),
) -> dict[str, Any]:
    """Calibrate rate shrinkage with season-disjoint holdouts."""
    candidates = _candidates(candidate_pseudo_counts)
    ready, rejected = _prepare(samples)
    grouped = defaultdict(list)

    for sample in ready:
        grouped[sample["metric"]].append(sample)

    metric_results = {
        metric: _metric_result(
            metric_samples,
            candidates,
        )
        for metric, metric_samples in sorted(
            grouped.items()
        )
    }
    blocked_metrics = sorted(
        metric
        for metric, result in metric_results.items()
        if result["status"] != "ready"
    )

    return {
        "schema_version": (
            CANONICAL_PITCHER_MATCHUP_PROFILE_SHRINKAGE_VERSION
        ),
        "status": (
            "ready"
            if metric_results and not blocked_metrics
            else "blocked"
        ),
        "shadow_only": True,
        "production_authority_changed": False,
        "parameter_selected": False,
        "selection_role": "candidate_evidence_only",
        "candidate_pseudo_counts": list(candidates),
        "eligible_sample_count": len(ready),
        "rejected_sample_count": len(rejected),
        "rejected_samples": rejected,
        "metric_results": metric_results,
        "blocked_metrics": blocked_metrics,
        "objective": {
            "primary": (
                "holdout_trial_weighted_"
                "binomial_log_loss"
            ),
            "supporting": [
                "holdout_trial_weighted_brier_score",
                "holdout_trial_weighted_absolute_error",
            ],
            "validation": (
                "leave_one_season_out_cross_validation"
            ),
        },
    }

"""Finalize calibrated canonical pitcher-profile pseudo-counts.

This policy consumes a shadow calibration artifact and selects only pooled
parameters that satisfy improvement, cross-season stability, and boundary
plateau gates. It never changes production authority and does not select
segment-specific parameters.
"""

from __future__ import annotations

from typing import Any, Mapping


CALIBRATION_POLICY_VERSION = (
    "canonical_pitcher_matchup_profile_calibration_policy_v1"
)
MAX_LAST_STEP_ABSOLUTE_GAIN = 0.0001
MAX_LAST_STEP_SHARE_OF_TOTAL_GAIN = 0.01


def _numeric(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _candidate_grid(
    result: Mapping[str, Any],
) -> list[Mapping[str, Any]]:
    return sorted(
        (
            row
            for row in result.get(
                "pooled_grid",
                (),
            )
            if isinstance(row, Mapping)
            and _numeric(
                row.get("pseudo_count")
            )
            is not None
            and _numeric(
                row.get("binomial_log_loss")
            )
            is not None
        ),
        key=lambda row: float(
            row["pseudo_count"]
        ),
    )


def _evaluate_metric(
    metric: str,
    result: Mapping[str, Any],
) -> dict[str, Any]:
    reasons = []
    grid = _candidate_grid(result)
    selected = result.get("pooled_candidate")

    if not grid:
        reasons.append("candidate_grid_unavailable")
    if not isinstance(selected, Mapping):
        reasons.append("pooled_candidate_unavailable")

    if reasons:
        return {
            "metric": metric,
            "status": "blocked",
            "reasons": reasons,
        }

    selected_count = _numeric(
        selected.get("pseudo_count")
    )
    selected_loss = _numeric(
        selected.get("binomial_log_loss")
    )

    if (
        selected_count is None
        or selected_loss is None
    ):
        return {
            "metric": metric,
            "status": "blocked",
            "reasons": [
                "pooled_candidate_invalid"
            ],
        }

    baseline = next(
        (
            row
            for row in grid
            if float(row["pseudo_count"])
            == 0.0
        ),
        None,
    )

    if baseline is None:
        reasons.append("unshrunk_baseline_unavailable")
        baseline_loss = None
    else:
        baseline_loss = float(
            baseline["binomial_log_loss"]
        )

    selected_index = next(
        (
            index
            for index, row in enumerate(grid)
            if float(row["pseudo_count"])
            == selected_count
        ),
        None,
    )

    if selected_index is None:
        reasons.append(
            "selected_candidate_not_in_grid"
        )
        previous = None
    else:
        previous = (
            grid[selected_index - 1]
            if selected_index > 0
            else None
        )

    total_gain = (
        baseline_loss - selected_loss
        if baseline_loss is not None
        else None
    )
    last_step_gain = (
        float(previous["binomial_log_loss"])
        - selected_loss
        if previous is not None
        else None
    )
    last_step_share = (
        last_step_gain / total_gain
        if (
            last_step_gain is not None
            and total_gain is not None
            and total_gain > 0
        )
        else None
    )

    maximum_candidate = max(
        float(row["pseudo_count"])
        for row in grid
    )
    selected_at_boundary = (
        selected_count == maximum_candidate
    )

    season_range = result.get(
        "cross_season_candidate_range",
        {},
    )
    season_spread = (
        _numeric(season_range.get("spread"))
        if isinstance(season_range, Mapping)
        else None
    )
    season_stable = (
        season_spread is not None
        and season_spread == 0.0
    )

    plateaued_boundary = (
        selected_at_boundary
        and season_stable
        and last_step_gain is not None
        and 0.0 <= last_step_gain
        <= MAX_LAST_STEP_ABSOLUTE_GAIN
        and last_step_share is not None
        and last_step_share
        <= MAX_LAST_STEP_SHARE_OF_TOTAL_GAIN
    )

    if total_gain is None or total_gain <= 0:
        reasons.append(
            "no_improvement_over_unshrunk"
        )

    if not season_stable:
        reasons.append(
            "cross_season_candidate_instability"
        )

    if (
        selected_at_boundary
        and not plateaued_boundary
    ):
        reasons.append(
            "unresolved_upper_grid_boundary"
        )

    return {
        "metric": metric,
        "status": (
            "selected"
            if not reasons
            else "blocked"
        ),
        "pseudo_count": selected_count,
        "total_log_loss_gain": total_gain,
        "selected_at_upper_boundary": (
            selected_at_boundary
        ),
        "plateaued_boundary": (
            plateaued_boundary
        ),
        "previous_candidate": (
            float(previous["pseudo_count"])
            if previous is not None
            else None
        ),
        "last_step_log_loss_gain": (
            last_step_gain
        ),
        "last_step_share_of_total_gain": (
            last_step_share
        ),
        "cross_season_candidate_range": (
            dict(season_range)
            if isinstance(
                season_range,
                Mapping,
            )
            else {}
        ),
        "reasons": reasons,
    }


def finalize_canonical_pitcher_matchup_profile_calibration(
    artifact: Mapping[str, Any],
) -> dict[str, Any]:
    """Select stable pooled parameters without production activation."""
    if artifact.get("shadow_only") is not True:
        raise ValueError(
            "calibration artifact must be shadow-only"
        )
    if (
        artifact.get(
            "production_authority_changed"
        )
        is not False
    ):
        raise ValueError(
            "calibration artifact changed production authority"
        )
    if artifact.get("parameter_selected") is not False:
        raise ValueError(
            "input artifact already selected parameters"
        )

    calibration = artifact.get("calibration")
    if not isinstance(calibration, Mapping):
        raise ValueError(
            "calibration payload is required"
        )

    metric_results = calibration.get(
        "metric_results"
    )
    if not isinstance(metric_results, Mapping):
        raise ValueError(
            "metric results are required"
        )

    evaluations = {
        metric: _evaluate_metric(
            metric,
            result,
        )
        for metric, result in sorted(
            metric_results.items()
        )
        if isinstance(result, Mapping)
    }

    selected = {
        metric: evaluation["pseudo_count"]
        for metric, evaluation in evaluations.items()
        if evaluation["status"] == "selected"
    }
    blocked = {
        metric: evaluation["reasons"]
        for metric, evaluation in evaluations.items()
        if evaluation["status"] == "blocked"
    }

    return {
        "schema_version": (
            CALIBRATION_POLICY_VERSION
        ),
        "status": (
            "ready"
            if selected
            else "blocked"
        ),
        "selection_scope": (
            "pooled_metrics_only"
        ),
        "parameter_selected": bool(selected),
        "selected_pseudo_counts": selected,
        "blocked_metrics": blocked,
        "metric_evaluations": evaluations,
        "segment_parameters_selected": False,
        "segment_policy": (
            "deferred_pending_season_disjoint_"
            "segment_stability"
        ),
        "production_authority_changed": False,
        "production_authority": False,
        "activation_status": (
            "candidate_policy_ready"
            if selected
            else "blocked"
        ),
    }

"""Apply calibrated shrinkage to canonical pitcher-profile evidence."""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping
from typing import Any

from .canonical_pitcher_matchup_profile_holdout import (
    METRIC_SPECS,
)


APPLICATION_VERSION = (
    "canonical_pitcher_matchup_profile_application_v1"
)


def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None

    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None

    if not math.isfinite(parsed):
        return None

    return parsed


def _rate(value: Any) -> float | None:
    parsed = _number(value)

    if (
        parsed is None
        or parsed < 0.0
        or parsed > 1.0
    ):
        return None

    return parsed


def _digest(value: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")

    return hashlib.sha256(encoded).hexdigest()


def _metric_counts(
    evidence: Mapping[str, Any],
    metric: str,
) -> tuple[int, int] | None:
    overall = evidence.get("overall")
    if not isinstance(overall, Mapping):
        return None

    specification = METRIC_SPECS.get(metric)
    if specification is None:
        return None

    _, component, numerator_key = specification

    component_values = overall.get(component)
    denominators = overall.get(
        "metric_denominators"
    )

    if (
        not isinstance(
            component_values,
            Mapping,
        )
        or not isinstance(
            denominators,
            Mapping,
        )
    ):
        return None

    numerator = _number(
        component_values.get(numerator_key)
    )
    denominator = _number(
        denominators.get(metric)
    )

    if (
        numerator is None
        or denominator is None
        or numerator < 0
        or denominator < 0
        or numerator > denominator
        or not numerator.is_integer()
        or not denominator.is_integer()
    ):
        return None

    return int(numerator), int(denominator)


def apply_canonical_pitcher_matchup_profile_calibration(
    evidence: Mapping[str, Any],
    *,
    calibration_policy: Mapping[str, Any],
    league_priors: Mapping[str, Any],
) -> dict[str, Any]:
    """Apply pooled calibrated pseudo-counts without production authority."""
    if not isinstance(evidence, Mapping):
        raise TypeError("evidence must be a mapping")

    if (
        calibration_policy.get("status")
        != "ready"
    ):
        raise ValueError(
            "calibration policy must be ready"
        )
    if (
        calibration_policy.get(
            "production_authority"
        )
        is not False
    ):
        raise ValueError(
            "calibration policy must not have "
            "production authority"
        )
    if (
        calibration_policy.get(
            "production_authority_changed"
        )
        is not False
    ):
        raise ValueError(
            "calibration policy changed "
            "production authority"
        )
    if (
        calibration_policy.get(
            "segment_parameters_selected"
        )
        is not False
    ):
        raise ValueError(
            "segment parameters must remain deferred"
        )

    selected = calibration_policy.get(
        "selected_pseudo_counts"
    )
    if not isinstance(selected, Mapping):
        raise ValueError(
            "selected pseudo-counts are required"
        )

    profile_rates = {}
    metric_diagnostics = {}

    for metric, raw_pseudo_count in sorted(
        selected.items()
    ):
        reasons = []
        pseudo_count = _number(
            raw_pseudo_count
        )
        prior = _rate(
            league_priors.get(metric)
        )
        counts = _metric_counts(
            evidence,
            metric,
        )

        if (
            pseudo_count is None
            or pseudo_count < 0
        ):
            reasons.append(
                "invalid_pseudo_count"
            )

        if prior is None:
            reasons.append(
                "league_prior_unavailable"
            )

        if counts is None:
            reasons.append(
                "sufficient_statistics_unavailable"
            )

        if reasons:
            metric_diagnostics[metric] = {
                "status": "unavailable",
                "reasons": reasons,
                "production_authority": False,
            }
            continue

        successes, trials = counts
        denominator = (
            trials + pseudo_count
        )

        if denominator <= 0:
            metric_diagnostics[metric] = {
                "status": "unavailable",
                "reasons": [
                    "nonpositive_shrinkage_denominator"
                ],
                "production_authority": False,
            }
            continue

        observed_rate = (
            successes / trials
            if trials > 0
            else None
        )
        reliability = trials / denominator
        calibrated_rate = (
            successes
            + pseudo_count * prior
        ) / denominator

        profile_rates[metric] = round(
            calibrated_rate,
            12,
        )
        metric_diagnostics[metric] = {
            "status": "ready",
            "successes": successes,
            "trials": trials,
            "observed_rate": (
                round(observed_rate, 12)
                if observed_rate is not None
                else None
            ),
            "league_prior": prior,
            "pseudo_count": pseudo_count,
            "reliability": round(
                reliability,
                12,
            ),
            "calibrated_rate": round(
                calibrated_rate,
                12,
            ),
            "production_authority": False,
        }

    blocked_metrics = dict(
        calibration_policy.get(
            "blocked_metrics",
            {},
        )
    )

    requested_count = len(selected)
    ready_count = len(profile_rates)

    if requested_count == 0 or ready_count == 0:
        status = "unavailable"
    elif ready_count < requested_count:
        status = "partial"
    else:
        status = "ready"

    diagnostics = {
        "schema_version": APPLICATION_VERSION,
        "status": status,
        "application_scope": (
            "overall_pooled_metrics_only"
        ),
        "requested_metric_count": (
            requested_count
        ),
        "ready_metric_count": ready_count,
        "blocked_metrics": blocked_metrics,
        "metric_diagnostics": (
            metric_diagnostics
        ),
        "segment_parameters_applied": False,
        "production_authority": False,
        "production_authority_changed": False,
        "activation_status": (
            "shadow_candidate_applied"
        ),
    }
    diagnostics["application_digest"] = (
        _digest(diagnostics)
    )

    return {
        "profile_rates": profile_rates,
        "diagnostics": diagnostics,
    }

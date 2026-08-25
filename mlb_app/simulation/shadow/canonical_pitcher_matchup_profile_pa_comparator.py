"""Paired PA comparison for canonical pitcher matchup candidates.

This module is deliberately shadow-only. It maps only calibrated, supported
pitcher metrics into a copied pitcher profile and compares the existing PA
model against that candidate without changing production inputs.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Mapping

from mlb_app.simulation.pa_outcome_model import (
    build_pa_outcome_probabilities,
)


SCHEMA_VERSION = (
    "canonical_pitcher_matchup_profile_pa_comparator_v1"
)

SUPPORTED_RATE_MAPPINGS = {
    "k_rate": (
        "bat_missing",
        "k_rate",
    ),
    "barrel_rate_allowed_approx": (
        "contact_management",
        "barrel_rate_allowed",
    ),
    "hard_hit_rate_allowed": (
        "contact_management",
        "hard_hit_rate_allowed",
    ),
}

DEFERRED_RATE_REASONS = {
    "bb_rate": "cross_season_candidate_instability",
    "ground_ball_rate": (
        "pa_outcome_v1_has_no_contact_type_input"
    ),
    "line_drive_rate": (
        "pa_outcome_v1_has_no_contact_type_input"
    ),
    "fly_ball_rate": (
        "pa_outcome_v1_has_no_contact_type_input"
    ),
    "popup_rate": (
        "pa_outcome_v1_has_no_contact_type_input"
    ),
    "sweet_spot_rate_allowed": (
        "pa_outcome_v1_has_no_sweet_spot_input"
    ),
}


def _mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    return {}


def _reconcile_probability_rounding(
    probabilities: Mapping[str, Any],
) -> dict[str, Any]:
    reconciled = dict(probabilities)

    if "out" not in reconciled:
        return reconciled

    values = tuple(reconciled.values())

    if any(
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        for value in values
    ):
        return reconciled

    residual = round(
        1.0
        - sum(
            float(value)
            for value in values
        ),
        12,
    )

    if abs(residual) > 0.0005:
        return reconciled

    adjusted_out = round(
        float(reconciled["out"])
        + residual,
        12,
    )

    if not 0.0 <= adjusted_out <= 1.0:
        return reconciled

    reconciled["out"] = adjusted_out
    return reconciled


def _candidate_status(
    candidate: Mapping[str, Any],
) -> str | None:
    diagnostics = _mapping(
        candidate.get("diagnostics")
    )
    return diagnostics.get("status")


def _set_nested_rate(
    profile: dict[str, Any],
    path: tuple[str, str],
    value: Any,
) -> bool:
    if not isinstance(value, (int, float)):
        return False

    normalized = float(value)

    if not 0.0 <= normalized <= 1.0:
        return False

    family, metric = path
    container = profile.get(family)

    if not isinstance(container, dict):
        container = {}
        profile[family] = container

    container[metric] = normalized
    return True


def compare_canonical_pitcher_matchup_profile_pa_outcomes(
    *,
    candidate: Mapping[str, Any],
    production_pitcher_profile: Mapping[str, Any],
    batter_profile: Mapping[str, Any],
    environment_profile: Mapping[str, Any],
) -> dict[str, Any]:
    """Run immutable production/candidate PA models side by side."""
    candidate_payload = _mapping(candidate)
    production_profile = deepcopy(
        _mapping(production_pitcher_profile)
    )

    diagnostics = _mapping(
        candidate_payload.get("diagnostics")
    )
    candidate_status = _candidate_status(
        candidate_payload
    )

    if candidate_status != "ready":
        return {
            "schema_version": SCHEMA_VERSION,
            "status": "blocked",
            "executed": False,
            "blockers": [
                "pitcher_matchup_profile_candidate_not_ready"
            ],
            "candidate_status": candidate_status,
            "shadow_only": True,
            "production_inputs_unchanged": True,
            "production_authority": False,
            "production_authority_changed": False,
        }

    if (
        diagnostics.get("production_authority")
        is not False
        or diagnostics.get(
            "production_authority_changed"
        )
        is not False
    ):
        return {
            "schema_version": SCHEMA_VERSION,
            "status": "blocked",
            "executed": False,
            "blockers": [
                "candidate_authority_contract_invalid"
            ],
            "candidate_status": candidate_status,
            "shadow_only": True,
            "production_inputs_unchanged": True,
            "production_authority": False,
            "production_authority_changed": False,
        }

    candidate_profile = deepcopy(
        production_profile
    )
    profile_rates = _mapping(
        candidate_payload.get("profile_rates")
    )
    applied_rates: dict[str, float] = {}
    rejected_rates: dict[str, str] = {}

    for source_metric, target_path in (
        SUPPORTED_RATE_MAPPINGS.items()
    ):
        value = profile_rates.get(source_metric)

        if _set_nested_rate(
            candidate_profile,
            target_path,
            value,
        ):
            applied_rates[source_metric] = float(
                value
            )
        else:
            rejected_rates[source_metric] = (
                "missing_or_invalid_candidate_rate"
            )

    deferred_rates = {
        metric: reason
        for metric, reason in (
            DEFERRED_RATE_REASONS.items()
        )
        if metric in profile_rates
        or metric == "bb_rate"
    }

    if not applied_rates:
        return {
            "schema_version": SCHEMA_VERSION,
            "status": "blocked",
            "executed": False,
            "blockers": [
                "no_supported_candidate_rates"
            ],
            "applied_rates": {},
            "rejected_rates": rejected_rates,
            "deferred_rates": deferred_rates,
            "shadow_only": True,
            "production_inputs_unchanged": True,
            "production_authority": False,
            "production_authority_changed": False,
        }

    production_result = (
        build_pa_outcome_probabilities(
            batter_profile=_mapping(
                batter_profile
            ),
            pitcher_profile=production_profile,
            environment_profile=_mapping(
                environment_profile
            ),
        )
    )
    shadow_result = (
        build_pa_outcome_probabilities(
            batter_profile=_mapping(
                batter_profile
            ),
            pitcher_profile=candidate_profile,
            environment_profile=_mapping(
                environment_profile
            ),
        )
    )

    production_probabilities = dict(
        production_result.get(
            "probabilities",
            {},
        )
    )
    shadow_probabilities = (
        _reconcile_probability_rounding(
            shadow_result.get(
                "probabilities",
                {},
            )
        )
    )

    outcome_keys = sorted(
        set(production_probabilities)
        | set(shadow_probabilities)
    )
    probability_deltas = {
        outcome: round(
            float(
                shadow_probabilities.get(
                    outcome,
                    0.0,
                )
            )
            - float(
                production_probabilities.get(
                    outcome,
                    0.0,
                )
            ),
            12,
        )
        for outcome in outcome_keys
    }

    maximum_delta = max(
        (
            abs(value)
            for value in probability_deltas.values()
        ),
        default=0.0,
    )

    return {
        "schema_version": SCHEMA_VERSION,
        "status": "ready",
        "executed": True,
        "comparison_role": (
            "paired_shadow_pa_probability_diagnostic"
        ),
        "production_model_version": (
            production_result.get("model_version")
        ),
        "shadow_model_version": (
            shadow_result.get("model_version")
        ),
        "production_probabilities": (
            production_probabilities
        ),
        "shadow_probabilities": (
            shadow_probabilities
        ),
        "probability_deltas": probability_deltas,
        "maximum_absolute_probability_delta": (
            round(maximum_delta, 12)
        ),
        "production_probability_sum": round(
            sum(production_probabilities.values()),
            12,
        ),
        "shadow_probability_sum": round(
            sum(shadow_probabilities.values()),
            12,
        ),
        "candidate_pitcher_profile": (
            candidate_profile
        ),
        "applied_rates": applied_rates,
        "rejected_rates": rejected_rates,
        "deferred_rates": deferred_rates,
        "mapping_policy": (
            "supported_calibrated_pooled_metrics_only"
        ),
        "segment_parameters_applied": False,
        "shadow_only": True,
        "production_inputs_unchanged": True,
        "production_authority": False,
        "production_authority_changed": False,
    }

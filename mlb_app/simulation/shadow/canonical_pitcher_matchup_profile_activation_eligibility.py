"""Evaluate canonical pitcher-profile production activation eligibility.

Eligibility records that calibration and historical evidence satisfy the
selection contract. It never changes production inputs or authority.
"""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from typing import Any, Mapping


SCHEMA_VERSION = (
    "canonical_pitcher_matchup_profile_activation_eligibility_v1"
)


def _digest(value: Any) -> str:
    payload = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


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


def _nonnegative_float(
    value: Any,
    name: str,
) -> float:
    if isinstance(value, bool):
        raise ValueError(
            f"{name}_must_be_nonnegative"
        )

    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"{name}_must_be_nonnegative"
        ) from exc

    if parsed < 0.0:
        raise ValueError(
            f"{name}_must_be_nonnegative"
        )

    return parsed


def _mapping(
    value: Any,
    name: str,
) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(
            f"{name}_must_be_mapping"
        )
    return deepcopy(dict(value))


def evaluate_canonical_pitcher_matchup_profile_activation_eligibility(
    *,
    calibration_policy: Mapping[str, Any],
    historical_evaluation: Mapping[str, Any],
    minimum_samples: int = 300,
    minimum_observed_pa: int = 900,
    minimum_seasons: int = 3,
    minimum_absolute_log_loss_improvement: float = 0.0,
    minimum_absolute_brier_improvement: float = 0.0,
) -> dict[str, Any]:
    """Return an evidence-only production activation eligibility decision."""

    required_samples = _positive_integer(
        minimum_samples,
        "minimum_samples",
    )
    required_pa = _positive_integer(
        minimum_observed_pa,
        "minimum_observed_pa",
    )
    required_seasons = _positive_integer(
        minimum_seasons,
        "minimum_seasons",
    )
    required_log_loss = _nonnegative_float(
        minimum_absolute_log_loss_improvement,
        "minimum_absolute_log_loss_improvement",
    )
    required_brier = _nonnegative_float(
        minimum_absolute_brier_improvement,
        "minimum_absolute_brier_improvement",
    )
    calibration = _mapping(
        calibration_policy,
        "calibration_policy",
    )
    historical = _mapping(
        historical_evaluation,
        "historical_evaluation",
    )
    calibration_diagnostics = dict(
        calibration.get("diagnostics")
        or calibration
    )
    historical_diagnostics = dict(
        historical.get("diagnostics")
        or {}
    )
    overall = dict(
        historical.get("overall") or {}
    )
    by_season = dict(
        historical.get("by_season") or {}
    )

    blockers = []

    calibration_ready = (
        calibration_diagnostics.get(
            "status"
        )
        == "ready"
        and calibration_diagnostics.get(
            "activation_status"
        )
        == "candidate_policy_ready"
    )
    if not calibration_ready:
        blockers.append(
            "calibration_policy_not_ready"
        )

    if calibration_diagnostics.get(
        "production_authority_changed"
    ) is not False:
        blockers.append(
            "calibration_authority_contract_invalid"
        )

    historical_gate_passed = (
        historical_diagnostics.get(
            "selection_gate_passed"
        )
        is True
        and historical_diagnostics.get(
            "activation_status"
        )
        == "historical_pa_gate_passed"
    )
    if not historical_gate_passed:
        blockers.append(
            "historical_pa_gate_not_passed"
        )

    try:
        sample_count = int(
            overall.get("sample_count", 0)
        )
    except (TypeError, ValueError):
        sample_count = 0
    try:
        observed_pa = int(
            overall.get("observed_pa", 0)
        )
    except (TypeError, ValueError):
        observed_pa = 0

    if sample_count < required_samples:
        blockers.append(
            "historical_sample_count_below_minimum"
        )
    if observed_pa < required_pa:
        blockers.append(
            "historical_observed_pa_below_minimum"
        )
    if len(by_season) < required_seasons:
        blockers.append(
            "historical_season_count_below_minimum"
        )

    try:
        log_loss_improvement = float(
            overall.get(
                "absolute_log_loss_improvement"
            )
        )
    except (TypeError, ValueError):
        log_loss_improvement = float(
            "-inf"
        )
    try:
        brier_improvement = float(
            overall.get(
                "absolute_brier_improvement"
            )
        )
    except (TypeError, ValueError):
        brier_improvement = float(
            "-inf"
        )

    if log_loss_improvement <= (
        required_log_loss
    ):
        blockers.append(
            "absolute_log_loss_improvement_below_minimum"
        )
    if brier_improvement <= required_brier:
        blockers.append(
            "absolute_brier_improvement_below_minimum"
        )

    regressed_seasons = tuple(
        str(value)
        for value in (
            historical_diagnostics.get(
                "regressed_seasons"
            )
            or ()
        )
    )
    if regressed_seasons:
        blockers.append(
            "season_log_loss_instability"
        )

    invalid_historical_authority = any((
        historical_diagnostics.get(
            "production_authority"
        )
        is not False,
        historical_diagnostics.get(
            "production_authority_changed"
        )
        is not False,
    ))
    if invalid_historical_authority:
        blockers.append(
            "historical_authority_contract_invalid"
        )

    blockers = list(dict.fromkeys(blockers))
    eligible = not blockers

    diagnostics = {
        "schema_version": SCHEMA_VERSION,
        "status": (
            "ready"
            if eligible
            else "blocked"
        ),
        "activation_status": (
            "candidate_activation_eligible"
            if eligible
            else "candidate_activation_blocked"
        ),
        "activation_eligible": eligible,
        "blockers": blockers,
        "calibration_policy_ready": (
            calibration_ready
        ),
        "historical_pa_gate_passed": (
            historical_gate_passed
        ),
        "sample_count": sample_count,
        "minimum_samples": required_samples,
        "observed_pa": observed_pa,
        "minimum_observed_pa": required_pa,
        "season_count": len(by_season),
        "minimum_seasons": required_seasons,
        "absolute_log_loss_improvement": (
            log_loss_improvement
        ),
        "minimum_absolute_log_loss_improvement": (
            required_log_loss
        ),
        "absolute_brier_improvement": (
            brier_improvement
        ),
        "minimum_absolute_brier_improvement": (
            required_brier
        ),
        "regressed_seasons": (
            regressed_seasons
        ),
        "eligibility_only": True,
        "activation_executed": False,
        "production_inputs_unchanged": True,
        "production_authority": False,
        "production_authority_changed": False,
        "calibration_policy_digest": (
            calibration_diagnostics.get(
                "calibration_policy_digest"
            )
            or calibration_diagnostics.get(
                "policy_digest"
            )
        ),
        "historical_evaluation_digest": (
            historical_diagnostics.get(
                "evaluation_digest"
            )
        ),
    }
    diagnostics["eligibility_digest"] = (
        _digest(diagnostics)
    )

    return {
        "eligible": eligible,
        "diagnostics": diagnostics,
    }

"""Validate canonical extra-innings and walk-off activation."""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any, Mapping, Tuple


CANONICAL_EXTRAS_WALKOFF_ACTIVATION_VERSION = (
    "canonical_extras_walkoff_activation_v1"
)


def _mapping(value: Any) -> Mapping[str, Any]:
    return (
        value
        if isinstance(value, Mapping)
        else {}
    )


def _probability(value: Any) -> float | None:
    if isinstance(value, bool):
        return None

    try:
        result = float(value)
    except (TypeError, ValueError):
        return None

    if (
        not math.isfinite(result)
        or not 0.0 <= result <= 1.0
    ):
        return None

    return result


def _positive_integer(value: Any) -> int | None:
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or value <= 0
    ):
        return None

    return value


@dataclass(frozen=True)
class CanonicalExtrasWalkoffActivation:
    """Runtime-derived activation state for canonical game endings."""

    status: str
    blockers: Tuple[str, ...]
    simulation_count: int | None
    extra_innings_probability: float | None
    walk_off_probability: float | None
    game_validation_pass_rate: float | None
    box_score_reconciliation_pass_rate: float | None
    maximum_extra_innings: int | None
    automatic_runner_configured: bool
    trial_warnings: Tuple[str, ...] = ()
    schema_version: str = (
        CANONICAL_EXTRAS_WALKOFF_ACTIVATION_VERSION
    )

    def __post_init__(self) -> None:
        if self.status not in {
            "active",
            "blocked",
            "unavailable",
        }:
            raise ValueError(
                "unsupported extras/walk-off activation status"
            )

        if self.schema_version != (
            CANONICAL_EXTRAS_WALKOFF_ACTIVATION_VERSION
        ):
            raise ValueError(
                "unsupported extras/walk-off activation schema"
            )

    @property
    def active(self) -> bool:
        return (
            self.status == "active"
            and not self.blockers
        )

    def to_diagnostics(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "status": self.status,
            "active": self.active,
            "blockers": list(self.blockers),
            "simulation_count": self.simulation_count,
            "extra_innings_probability": (
                self.extra_innings_probability
            ),
            "walk_off_probability": (
                self.walk_off_probability
            ),
            "game_validation_pass_rate": (
                self.game_validation_pass_rate
            ),
            "box_score_reconciliation_pass_rate": (
                self.box_score_reconciliation_pass_rate
            ),
            "maximum_extra_innings": (
                self.maximum_extra_innings
            ),
            "extra_innings_active": self.active,
            "automatic_runner_active": (
                self.active
                and self.automatic_runner_configured
            ),
            "walk_off_shortening_active": self.active,
            "automatic_runner_configured": (
                self.automatic_runner_configured
            ),
            "trial_warnings": list(
                self.trial_warnings
            ),
            "behavioral_validation": (
                "passed"
                if self.active
                else "not_passed"
            ),
            "empirical_calibration_status": (
                "canonical_historical_validation_"
                "not_claimed"
            ),
            "legacy_evidence_status": (
                "reference_only_inconclusive"
            ),
            "legacy_candidate_promoted": False,
            "parameter_reselection_performed": False,
            "database_writes_performed": False,
            "production_authority_changed": False,
        }


def evaluate_canonical_extras_walkoff_activation(
    *,
    canonical_payload: Any,
    execution_inputs: Any,
) -> CanonicalExtrasWalkoffActivation:
    """
    Evaluate already-executed canonical material.

    This function does not run simulations, tune parameters, promote a
    historical prototype, write storage, or change production authority.
    """

    payload = _mapping(canonical_payload)
    outcomes = _mapping(payload.get("outcomes"))
    diagnostics = _mapping(
        payload.get("trial_diagnostics")
    )

    game_config = getattr(
        execution_inputs,
        "game_config",
        None,
    )

    simulation_count = _positive_integer(
        outcomes.get("simulation_count")
    )
    extra_probability = _probability(
        outcomes.get("extra_innings_probability")
    )
    walk_off_probability = _probability(
        outcomes.get("walk_off_probability")
    )
    game_validation_rate = _probability(
        diagnostics.get(
            "game_validation_pass_rate"
        )
    )
    reconciliation_rate = _probability(
        diagnostics.get(
            "box_score_reconciliation_pass_rate"
        )
    )

    maximum_extra_innings = getattr(
        game_config,
        "max_extra_innings",
        None,
    )
    if (
        isinstance(maximum_extra_innings, bool)
        or not isinstance(
            maximum_extra_innings,
            int,
        )
        or maximum_extra_innings < 0
    ):
        maximum_extra_innings = None

    automatic_runner_configured = (
        getattr(
            game_config,
            "automatic_runner_enabled",
            False,
        )
        is True
    )

    raw_warnings = diagnostics.get(
        "warnings",
        (),
    )
    trial_warnings = tuple(
        str(value)
        for value in (
            raw_warnings
            if isinstance(
                raw_warnings,
                (list, tuple),
            )
            else ()
        )
    )

    blockers = []

    if not payload:
        blockers.append(
            "canonical_payload_unavailable"
        )

    if not outcomes:
        blockers.append(
            "canonical_outcomes_unavailable"
        )

    if simulation_count is None:
        blockers.append(
            "canonical_simulation_count_unavailable"
        )

    if extra_probability is None:
        blockers.append(
            "extra_innings_probability_unavailable"
        )

    if walk_off_probability is None:
        blockers.append(
            "walk_off_probability_unavailable"
        )

    if game_validation_rate != 1.0:
        blockers.append(
            "game_validation_incomplete"
        )

    if reconciliation_rate != 1.0:
        blockers.append(
            "box_score_reconciliation_incomplete"
        )

    if maximum_extra_innings is None:
        blockers.append(
            "game_config_unavailable"
        )
    elif maximum_extra_innings <= 0:
        blockers.append(
            "extra_innings_disabled"
        )

    if not automatic_runner_configured:
        blockers.append(
            "automatic_runner_disabled"
        )

    if not payload or not outcomes:
        status = "unavailable"
    elif blockers:
        status = "blocked"
    else:
        status = "active"

    return CanonicalExtrasWalkoffActivation(
        status=status,
        blockers=tuple(blockers),
        simulation_count=simulation_count,
        extra_innings_probability=(
            extra_probability
        ),
        walk_off_probability=(
            walk_off_probability
        ),
        game_validation_pass_rate=(
            game_validation_rate
        ),
        box_score_reconciliation_pass_rate=(
            reconciliation_rate
        ),
        maximum_extra_innings=(
            maximum_extra_innings
        ),
        automatic_runner_configured=(
            automatic_runner_configured
        ),
        trial_warnings=trial_warnings,
    )

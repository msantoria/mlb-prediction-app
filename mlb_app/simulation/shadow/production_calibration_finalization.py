"""Finalize canonical baserunning calibration from settled evidence."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
from typing import Any, Dict, Mapping

from .baserunning_calibration_comparison import (
    CanonicalBaserunningCalibrationComparison,
)
from .baserunning_calibration_gate import (
    CanonicalBaserunningCalibrationGate,
    CanonicalBaserunningCalibrationPolicy,
    evaluate_baserunning_calibration_gate,
)
from .historical_baserunning_holdout_validation import (
    CanonicalHistoricalBaserunningHoldoutPlan,
    build_historical_baserunning_holdout_plan,
)
from .production_monitoring_ledger import (
    CANONICAL_BASERUNNING_PRODUCTION_MONITORING_TARGET,
)
from .production_monitoring_settlement import (
    summarize_canonical_baserunning_production_settlements,
)


CANONICAL_BASERUNNING_PRODUCTION_CALIBRATION_FINALIZATION_VERSION = (
    "canonical_baserunning_production_calibration_finalization_v1"
)
CANONICAL_BASERUNNING_PRODUCTION_CALIBRATION_POLICY_VERSION = (
    "canonical_baserunning_production_calibration_policy_v1"
)


def build_canonical_baserunning_production_calibration_policy(
) -> CanonicalBaserunningCalibrationPolicy:
    return CanonicalBaserunningCalibrationPolicy(
        minimum_game_count=(
            CANONICAL_BASERUNNING_PRODUCTION_MONITORING_TARGET
        ),
        maximum_stolen_base_error_per_game=0.25,
        maximum_caught_stealing_error_per_game=0.10,
        maximum_attempt_error_per_game=0.30,
        maximum_success_rate_absolute_error=0.10,
        policy_version=(
            CANONICAL_BASERUNNING_PRODUCTION_CALIBRATION_POLICY_VERSION
        ),
    )


def _digest(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode("utf-8")
    ).hexdigest()


def _number(
    source: Mapping[str, Any],
    field_name: str,
) -> float:
    value = source.get(field_name)

    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(float(value))
        or float(value) < 0.0
    ):
        raise ValueError(
            f"{field_name} must be nonnegative and finite"
        )

    return float(value)


@dataclass(frozen=True)
class CanonicalBaserunningProductionCalibrationFinalization:
    status: str
    decision: str
    settlement_complete: bool
    settled_game_count: int
    incumbent_transform_digest: str
    comparison: CanonicalBaserunningCalibrationComparison
    calibration_gate: CanonicalBaserunningCalibrationGate
    finalization_digest: str
    schema_version: str = (
        CANONICAL_BASERUNNING_PRODUCTION_CALIBRATION_FINALIZATION_VERSION
    )

    def __post_init__(self) -> None:
        if self.status not in {"ready", "unavailable"}:
            raise ValueError("unsupported finalization status")

        if self.decision not in {
            "retain_incumbent",
            "reopen_candidate_selection",
            "pending_settlement",
        }:
            raise ValueError("unsupported finalization decision")

        if self.settled_game_count < 0:
            raise ValueError(
                "settled_game_count must be nonnegative"
            )

        for field_name in (
            "incumbent_transform_digest",
            "finalization_digest",
        ):
            value = getattr(self, field_name)
            if (
                not isinstance(value, str)
                or len(value) != 64
                or any(
                    character not in "0123456789abcdef"
                    for character in value
                )
            ):
                raise ValueError(
                    f"{field_name} must be a SHA256 digest"
                )

        if not isinstance(
            self.comparison,
            CanonicalBaserunningCalibrationComparison,
        ):
            raise TypeError("comparison must be canonical")

        if not isinstance(
            self.calibration_gate,
            CanonicalBaserunningCalibrationGate,
        ):
            raise TypeError("calibration_gate must be canonical")

        if (
            self.decision == "retain_incumbent"
            and not self.calibration_gate.calibration_gate_passed
        ):
            raise ValueError(
                "retained incumbent must pass calibration gate"
            )

    @property
    def ready(self) -> bool:
        return self.status == "ready"

    def to_diagnostics(self) -> Dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "status": self.status,
            "ready": self.ready,
            "decision": self.decision,
            "settlement_complete": self.settlement_complete,
            "settled_game_count": self.settled_game_count,
            "incumbent_transform_digest": (
                self.incumbent_transform_digest
            ),
            "comparison": self.comparison.to_diagnostics(),
            "calibration_gate": (
                self.calibration_gate.to_diagnostics()
            ),
            "finalization_digest": self.finalization_digest,
            "incumbent_retained": (
                self.decision == "retain_incumbent"
            ),
            "candidate_reselected": False,
            "production_activation": True,
            "production_authority_changed": False,
        }


def finalize_canonical_baserunning_production_calibration(
    settlement: Mapping[str, Any],
    *,
    holdout_plan: (
        CanonicalHistoricalBaserunningHoldoutPlan | None
    ) = None,
) -> CanonicalBaserunningProductionCalibrationFinalization:
    if not isinstance(settlement, Mapping):
        raise TypeError("settlement must be a mapping")

    plan = (
        holdout_plan
        if holdout_plan is not None
        else build_historical_baserunning_holdout_plan()
    )
    if not isinstance(
        plan,
        CanonicalHistoricalBaserunningHoldoutPlan,
    ):
        raise TypeError("holdout_plan must be canonical")

    settled_game_count = int(
        _number(settlement, "settled_game_count")
    )
    settlement_complete = (
        settlement.get("settlement_complete") is True
        and settlement.get(
            "parameter_reselection_permitted"
        ) is True
    )

    if not settlement_complete:
        comparison = CanonicalBaserunningCalibrationComparison(
            status="unavailable",
        )
        gate = CanonicalBaserunningCalibrationGate(
            status="unavailable",
        )
        digest_payload = {
            "schema_version": (
                CANONICAL_BASERUNNING_PRODUCTION_CALIBRATION_FINALIZATION_VERSION
            ),
            "decision": "pending_settlement",
            "settlement_complete": False,
            "settled_game_count": settled_game_count,
            "incumbent_transform_digest": (
                plan.probability_transform.digest
            ),
            "comparison": comparison.to_diagnostics(),
            "calibration_gate": gate.to_diagnostics(),
        }

        return CanonicalBaserunningProductionCalibrationFinalization(
            status="unavailable",
            decision="pending_settlement",
            settlement_complete=False,
            settled_game_count=settled_game_count,
            incumbent_transform_digest=(
                plan.probability_transform.digest
            ),
            comparison=comparison,
            calibration_gate=gate,
            finalization_digest=_digest(digest_payload),
        )

    projected_sb = _number(
        settlement,
        "projected_stolen_bases",
    )
    observed_sb = int(
        _number(settlement, "observed_stolen_bases")
    )
    projected_cs = _number(
        settlement,
        "projected_caught_stealing",
    )
    observed_cs = int(
        _number(settlement, "observed_caught_stealing")
    )

    projected_attempts = round(
        projected_sb + projected_cs,
        6,
    )
    observed_attempts = observed_sb + observed_cs
    projected_success_rate = (
        round(projected_sb / projected_attempts, 6)
        if projected_attempts > 0.0
        else None
    )
    observed_success_rate = (
        round(observed_sb / observed_attempts, 6)
        if observed_attempts > 0
        else None
    )
    success_rate_error = (
        round(
            abs(
                projected_success_rate
                - observed_success_rate
            ),
            6,
        )
        if (
            projected_success_rate is not None
            and observed_success_rate is not None
        )
        else None
    )

    comparison = CanonicalBaserunningCalibrationComparison(
        status="ready",
        game_count=settled_game_count,
        projected_stolen_bases=projected_sb,
        observed_stolen_bases=observed_sb,
        stolen_base_absolute_error=round(
            abs(projected_sb - observed_sb),
            6,
        ),
        projected_caught_stealing=projected_cs,
        observed_caught_stealing=observed_cs,
        caught_stealing_absolute_error=round(
            abs(projected_cs - observed_cs),
            6,
        ),
        projected_attempts=projected_attempts,
        observed_attempts=observed_attempts,
        attempt_absolute_error=round(
            abs(projected_attempts - observed_attempts),
            6,
        ),
        projected_success_rate=projected_success_rate,
        observed_success_rate=observed_success_rate,
        success_rate_absolute_error=success_rate_error,
        observed_source_version=(
            "canonical_baserunning_production_settlement_v1"
        ),
    )

    gate = evaluate_baserunning_calibration_gate(
        comparison,
        build_canonical_baserunning_production_calibration_policy(),
    )

    status = "ready"
    decision = (
        "retain_incumbent"
        if gate.calibration_gate_passed
        else "reopen_candidate_selection"
    )

    digest_payload = {
        "schema_version": (
            CANONICAL_BASERUNNING_PRODUCTION_CALIBRATION_FINALIZATION_VERSION
        ),
        "decision": decision,
        "settlement_complete": settlement_complete,
        "settled_game_count": settled_game_count,
        "incumbent_transform_digest": (
            plan.probability_transform.digest
        ),
        "comparison": comparison.to_diagnostics(),
        "calibration_gate": gate.to_diagnostics(),
    }

    return CanonicalBaserunningProductionCalibrationFinalization(
        status=status,
        decision=decision,
        settlement_complete=settlement_complete,
        settled_game_count=settled_game_count,
        incumbent_transform_digest=(
            plan.probability_transform.digest
        ),
        comparison=comparison,
        calibration_gate=gate,
        finalization_digest=_digest(digest_payload),
    )

def finalize_canonical_baserunning_production_settlements(
    rows: tuple[Any, ...],
) -> CanonicalBaserunningProductionCalibrationFinalization:
    """
    Finalize the earliest fixed production settlement window.

    Ongoing monitoring may contain more than the target number of games.
    Games after the deterministic first target-sized window cannot alter
    the calibration decision or finalization digest.
    """

    if not isinstance(rows, tuple):
        raise TypeError("settlement rows must be a tuple")

    ordered_rows = tuple(
        sorted(
            rows,
            key=lambda row: (
                str(row.game_date),
                int(row.game_pk),
            ),
        )
    )
    frozen_rows = ordered_rows[
        :CANONICAL_BASERUNNING_PRODUCTION_MONITORING_TARGET
    ]
    frozen_summary = (
        summarize_canonical_baserunning_production_settlements(
            frozen_rows
        )
    )

    return finalize_canonical_baserunning_production_calibration(
        frozen_summary
    )

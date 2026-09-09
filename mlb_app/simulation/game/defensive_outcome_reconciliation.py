"""Fail-closed reconciliation of primary and defensive outcomes."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, Optional, Tuple

from .defensive_outcome_sampling import (
    CanonicalDefensiveOutcome,
    CanonicalSampledDefensiveOutcome,
)
from .probability import CanonicalPlateAppearanceOutcome


CANONICAL_DEFENSIVE_OUTCOME_RECONCILIATION_VERSION = (
    "canonical_defensive_outcome_reconciliation_v1"
)


class CanonicalReconciledBattedBallOutcome(str, Enum):
    """Outcome vocabulary required by event materialization."""

    OUT = "out"
    SINGLE = "single"
    DOUBLE = "double"
    TRIPLE = "triple"
    REACHED_ON_ERROR = "reached_on_error"


PRIMARY_HIT_OUTCOMES = frozenset(
    {
        CanonicalPlateAppearanceOutcome.SINGLE,
        CanonicalPlateAppearanceOutcome.DOUBLE,
        CanonicalPlateAppearanceOutcome.TRIPLE,
    }
)
SUPPORTED_PRIMARY_OUTCOMES = frozenset(
    {
        CanonicalPlateAppearanceOutcome.OUT,
        *PRIMARY_HIT_OUTCOMES,
    }
)
RECONCILED_HIT_OUTCOMES = frozenset(
    {
        CanonicalReconciledBattedBallOutcome.SINGLE,
        CanonicalReconciledBattedBallOutcome.DOUBLE,
        CanonicalReconciledBattedBallOutcome.TRIPLE,
    }
)


@dataclass(frozen=True)
class CanonicalDefensiveOutcomeReconciliation:
    """A ready outcome or explicit evidence blockers."""

    primary_outcome: CanonicalPlateAppearanceOutcome
    defensive_sample: CanonicalSampledDefensiveOutcome
    reconciled_outcome: Optional[
        CanonicalReconciledBattedBallOutcome
    ]
    blockers: Tuple[str, ...] = ()
    error_fielder_id: Optional[str] = None
    authoritative: bool = False
    schema_version: str = (
        CANONICAL_DEFENSIVE_OUTCOME_RECONCILIATION_VERSION
    )

    def __post_init__(self) -> None:
        if self.primary_outcome not in (
            SUPPORTED_PRIMARY_OUTCOMES
        ):
            raise ValueError(
                "unsupported primary batted-ball outcome"
            )

        if not isinstance(
            self.defensive_sample,
            CanonicalSampledDefensiveOutcome,
        ):
            raise TypeError(
                "defensive_sample must be a "
                "CanonicalSampledDefensiveOutcome"
            )

        if (
            self.reconciled_outcome is not None
            and not isinstance(
                self.reconciled_outcome,
                CanonicalReconciledBattedBallOutcome,
            )
        ):
            raise TypeError(
                "reconciled_outcome must be canonical"
            )

        if self.reconciled_outcome is None and not self.blockers:
            raise ValueError(
                "missing reconciled outcome requires blockers"
            )

        if self.reconciled_outcome is not None and self.blockers:
            raise ValueError(
                "ready reconciliation cannot contain blockers"
            )

        if self.authoritative is not False:
            raise ValueError(
                "reconciliation is not event authority"
            )

        if self.schema_version != (
            CANONICAL_DEFENSIVE_OUTCOME_RECONCILIATION_VERSION
        ):
            raise ValueError(
                "unsupported defensive reconciliation version"
            )

    @property
    def ready(self) -> bool:
        return (
            self.reconciled_outcome is not None
            and not self.blockers
        )

    @property
    def changes_primary_outcome(self) -> bool:
        if not self.ready:
            return False

        return (
            self.reconciled_outcome.value
            != self.primary_outcome.value
        )

    @property
    def requires_event_rematerialization(self) -> bool:
        return self.ready and self.changes_primary_outcome

    def to_diagnostics(self) -> Dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "status": "ready" if self.ready else "blocked",
            "ready": self.ready,
            "authoritative": self.authoritative,
            "primary_outcome": self.primary_outcome.value,
            "defensive_outcome": (
                self.defensive_sample.outcome.value
            ),
            "reconciled_outcome": (
                self.reconciled_outcome.value
                if self.reconciled_outcome is not None
                else None
            ),
            "changes_primary_outcome": (
                self.changes_primary_outcome
            ),
            "requires_event_rematerialization": (
                self.requires_event_rematerialization
            ),
            "error_fielder_id": self.error_fielder_id,
            "blockers": list(self.blockers),
        }


def reconcile_canonical_defensive_outcome(
    *,
    primary_outcome: CanonicalPlateAppearanceOutcome,
    defensive_sample: CanonicalSampledDefensiveOutcome,
    resolved_hit_type: Optional[
        CanonicalReconciledBattedBallOutcome
    ] = None,
    error_fielder_id: Optional[str] = None,
) -> CanonicalDefensiveOutcomeReconciliation:
    """
    Reconcile evidence without mutating the canonical play event.

    Missing hit-type or error-attribution evidence blocks rather than
    inventing a single or a synthetic fielder identity.
    """

    if primary_outcome not in SUPPORTED_PRIMARY_OUTCOMES:
        raise ValueError(
            "unsupported primary batted-ball outcome"
        )

    if not isinstance(
        defensive_sample,
        CanonicalSampledDefensiveOutcome,
    ):
        raise TypeError(
            "defensive_sample must be a "
            "CanonicalSampledDefensiveOutcome"
        )

    defensive_outcome = defensive_sample.outcome

    if (
        defensive_outcome
        is CanonicalDefensiveOutcome.CONVERTED_OUT
    ):
        return CanonicalDefensiveOutcomeReconciliation(
            primary_outcome=primary_outcome,
            defensive_sample=defensive_sample,
            reconciled_outcome=(
                CanonicalReconciledBattedBallOutcome.OUT
            ),
        )

    if defensive_outcome is CanonicalDefensiveOutcome.BASE_HIT:
        if primary_outcome in PRIMARY_HIT_OUTCOMES:
            return CanonicalDefensiveOutcomeReconciliation(
                primary_outcome=primary_outcome,
                defensive_sample=defensive_sample,
                reconciled_outcome=(
                    CanonicalReconciledBattedBallOutcome(
                        primary_outcome.value
                    )
                ),
            )

        if resolved_hit_type is None:
            return CanonicalDefensiveOutcomeReconciliation(
                primary_outcome=primary_outcome,
                defensive_sample=defensive_sample,
                reconciled_outcome=None,
                blockers=(
                    "defensive_base_hit_requires_hit_type",
                ),
            )

        if resolved_hit_type not in RECONCILED_HIT_OUTCOMES:
            raise ValueError(
                "resolved_hit_type must be single, "
                "double, or triple"
            )

        return CanonicalDefensiveOutcomeReconciliation(
            primary_outcome=primary_outcome,
            defensive_sample=defensive_sample,
            reconciled_outcome=resolved_hit_type,
        )

    normalized_fielder_id = str(
        error_fielder_id or ""
    ).strip()

    if not normalized_fielder_id:
        return CanonicalDefensiveOutcomeReconciliation(
            primary_outcome=primary_outcome,
            defensive_sample=defensive_sample,
            reconciled_outcome=None,
            blockers=(
                "fielding_error_requires_fielder_identity",
            ),
        )

    return CanonicalDefensiveOutcomeReconciliation(
        primary_outcome=primary_outcome,
        defensive_sample=defensive_sample,
        reconciled_outcome=(
            CanonicalReconciledBattedBallOutcome
            .REACHED_ON_ERROR
        ),
        error_fielder_id=normalized_fielder_id,
    )

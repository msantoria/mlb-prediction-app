"""Execute defensive evidence from one canonical trial batch."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from sqlalchemy.orm import Session

from ..game.trials import CanonicalTrialBatch
from .defensive_database_evidence import (
    CanonicalDefensiveDatabaseEvidence,
    execute_canonical_defensive_database_evidence,
)


CANONICAL_DEFENSIVE_TRIAL_EVIDENCE_VERSION = (
    "canonical_defensive_trial_evidence_v1"
)


def _authority_digest(
    batch: CanonicalTrialBatch,
) -> str:
    payload = {
        "simulation_count": len(batch.games),
        "game_validation_pass_rate": (
            batch.diagnostics.game_validation_pass_rate
        ),
        "box_score_reconciliation_pass_rate": (
            batch.diagnostics
            .box_score_reconciliation_pass_rate
        ),
        "warnings": list(batch.diagnostics.warnings),
        "defensive_event_authority": (
            batch.diagnostics
            .defensive_event_authority
            .to_diagnostics()
        ),
    }
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _validate_digest(value: str) -> None:
    if len(value) != 64:
        raise ValueError(
            "authority_digest must be a SHA-256 hex digest"
        )

    try:
        int(value, 16)
    except ValueError as exc:
        raise ValueError(
            "authority_digest must be a SHA-256 hex digest"
        ) from exc


@dataclass(frozen=True)
class CanonicalDefensiveTrialEvidence:
    """Evidence tied to one coherent canonical trial batch."""

    simulation_count: int
    authority_observation_count: int
    authority_digest: str
    database_evidence: CanonicalDefensiveDatabaseEvidence
    schema_version: str = (
        CANONICAL_DEFENSIVE_TRIAL_EVIDENCE_VERSION
    )

    def __post_init__(self) -> None:
        if self.schema_version != (
            CANONICAL_DEFENSIVE_TRIAL_EVIDENCE_VERSION
        ):
            raise ValueError(
                "unsupported defensive trial evidence version"
            )
        if self.simulation_count <= 0:
            raise ValueError(
                "simulation_count must be positive"
            )
        if self.authority_observation_count < 0:
            raise ValueError(
                "authority_observation_count cannot be negative"
            )
        _validate_digest(self.authority_digest)

        if not isinstance(
            self.database_evidence,
            CanonicalDefensiveDatabaseEvidence,
        ):
            raise TypeError(
                "database_evidence must be a "
                "CanonicalDefensiveDatabaseEvidence"
            )

    @property
    def status(self) -> str:
        return self.database_evidence.status

    @property
    def ready(self) -> bool:
        return self.database_evidence.ready

    @property
    def blocker(self) -> str | None:
        return self.database_evidence.blocker

    @property
    def error(self) -> str | None:
        return self.database_evidence.error

    def to_diagnostics(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "status": self.status,
            "ready": self.ready,
            "simulation_count": self.simulation_count,
            "authority_observation_count": (
                self.authority_observation_count
            ),
            "authority_digest": self.authority_digest,
            "authority_source": (
                "trial_batch.diagnostics."
                "defensive_event_authority"
            ),
            "trial_batch_consumed": True,
            "independent_authority_aggregation": False,
            "database_evidence": (
                self.database_evidence.to_diagnostics()
            ),
            "blocker": self.blocker,
            "error": self.error,
            "measurement_only": True,
            "database_accessed": True,
            "database_query_mode": "read_only",
            "network_accessed": False,
            "external_fetch_performed": False,
            "persistence_performed": False,
            "calibration_parameters_selected": False,
            "activation_permitted": False,
            "production_authority_changed": False,
        }


def execute_canonical_defensive_trial_evidence(
    session: Session,
    *,
    trial_batch: CanonicalTrialBatch,
    window_start: object,
    window_end: object,
    through_date: object,
) -> CanonicalDefensiveTrialEvidence:
    """Compare batch-owned authority against stored observations."""

    if not isinstance(trial_batch, CanonicalTrialBatch):
        raise TypeError(
            "trial_batch must be a CanonicalTrialBatch"
        )

    summary = (
        trial_batch.diagnostics.defensive_event_authority
    )
    database_evidence = (
        execute_canonical_defensive_database_evidence(
            session,
            summary=summary,
            window_start=window_start,
            window_end=window_end,
            through_date=through_date,
        )
    )

    return CanonicalDefensiveTrialEvidence(
        simulation_count=len(trial_batch.games),
        authority_observation_count=(
            summary.observation_count
        ),
        authority_digest=_authority_digest(trial_batch),
        database_evidence=database_evidence,
    )

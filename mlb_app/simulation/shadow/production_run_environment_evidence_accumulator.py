"""Accumulate production run-environment evidence artifacts."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
import math
from typing import Mapping, Optional, Tuple

from mlb_app.simulation.projections.aggregator import (
    summarize_values,
)
from mlb_app.simulation.projections.contracts import (
    StatisticalSummary,
)

from .production_run_environment_backtest import (
    LOW_TOTAL_COMPONENTS,
)
from .production_run_environment_evidence import (
    CanonicalProductionRunEnvironmentEvidence,
)


CANONICAL_PRODUCTION_RUN_ENVIRONMENT_EVIDENCE_ACCUMULATOR_VERSION = (
    "canonical_production_run_environment_evidence_accumulator_v1"
)

CountPairs = Tuple[Tuple[str, int], ...]
RatePairs = Tuple[Tuple[str, float], ...]
DigestTuple = Tuple[str, ...]

_ACCUMULATOR_STATUSES = frozenset({"ready", "unavailable"})
_DIAGNOSIS_NAMES = LOW_TOTAL_COMPONENTS + ("unattributed",)


def _validate_digest(name: str, value: str) -> None:
    if len(value) != 64:
        raise ValueError(f"{name} must be a SHA-256 hex digest")
    try:
        int(value, 16)
    except ValueError as exc:
        raise ValueError(
            f"{name} must be a SHA-256 hex digest"
        ) from exc


def _validate_count_pairs(
    name: str,
    values: CountPairs,
) -> None:
    names = tuple(key for key, _ in values)
    if len(names) != len(set(names)):
        raise ValueError(f"{name} names must be unique")
    if any(not key or count < 0 for key, count in values):
        raise ValueError(f"invalid {name} entry")


def _validate_rate_pairs(
    name: str,
    values: RatePairs,
) -> None:
    names = tuple(key for key, _ in values)
    if len(names) != len(set(names)):
        raise ValueError(f"{name} names must be unique")
    for key, value in values:
        if not key or not math.isfinite(value):
            raise ValueError(f"invalid {name} entry")


def _pairs_to_dict(values):
    return {name: value for name, value in values}


@dataclass(frozen=True)
class CanonicalProductionRunEnvironmentEvidenceAccumulator:
    """Deduplicated cohort summary of evidence artifacts."""

    status: str
    input_evidence_count: int
    unique_evidence_count: int
    duplicate_evidence_count: int
    ready_evidence_count: int
    unavailable_evidence_count: int
    error_evidence_count: int
    simulation_count: int
    unique_observed_artifact_count: int
    unique_observed_game_count: int
    low_total_signal_count: int
    low_total_signal_rate: float
    total_run_mean_delta_summary: Optional[StatisticalSummary]
    total_run_mean_relative_delta_summary: Optional[
        StatisticalSummary
    ]
    component_diagnosis_counts: CountPairs
    component_relative_delta_means: RatePairs
    blocker_counts: CountPairs
    evidence_artifact_digests: DigestTuple
    observed_artifact_digests: DigestTuple
    artifact_digest: str
    blocker: Optional[str] = None
    schema_version: str = (
        CANONICAL_PRODUCTION_RUN_ENVIRONMENT_EVIDENCE_ACCUMULATOR_VERSION
    )

    def __post_init__(self) -> None:
        if self.schema_version != (
            CANONICAL_PRODUCTION_RUN_ENVIRONMENT_EVIDENCE_ACCUMULATOR_VERSION
        ):
            raise ValueError(
                "unsupported production run-environment "
                "evidence accumulator version"
            )
        if self.status not in _ACCUMULATOR_STATUSES:
            raise ValueError(
                "unsupported production run-environment "
                "evidence accumulator status"
            )
        for name, value in (
            ("input_evidence_count", self.input_evidence_count),
            ("unique_evidence_count", self.unique_evidence_count),
            ("duplicate_evidence_count", self.duplicate_evidence_count),
            ("ready_evidence_count", self.ready_evidence_count),
            (
                "unavailable_evidence_count",
                self.unavailable_evidence_count,
            ),
            ("error_evidence_count", self.error_evidence_count),
            ("simulation_count", self.simulation_count),
            (
                "unique_observed_artifact_count",
                self.unique_observed_artifact_count,
            ),
            (
                "unique_observed_game_count",
                self.unique_observed_game_count,
            ),
            ("low_total_signal_count", self.low_total_signal_count),
        ):
            if value < 0:
                raise ValueError(f"{name} cannot be negative")
        if self.input_evidence_count <= 0:
            raise ValueError(
                "input_evidence_count must be positive"
            )
        if self.unique_evidence_count + (
            self.duplicate_evidence_count
        ) != self.input_evidence_count:
            raise ValueError(
                "unique and duplicate evidence must reconcile"
            )
        if (
            self.ready_evidence_count
            + self.unavailable_evidence_count
            + self.error_evidence_count
        ) != self.unique_evidence_count:
            raise ValueError(
                "evidence status counts must reconcile"
            )
        if self.low_total_signal_count > self.ready_evidence_count:
            raise ValueError(
                "low-total count cannot exceed ready evidence count"
            )
        expected_low_total_rate = round(
            self.low_total_signal_count / self.ready_evidence_count,
            6,
        ) if self.ready_evidence_count else 0.0
        if self.low_total_signal_rate != expected_low_total_rate:
            raise ValueError(
                "low-total rate must reconcile with evidence counts"
            )
        if not 0.0 <= self.low_total_signal_rate <= 1.0:
            raise ValueError(
                "low_total_signal_rate must be bounded"
            )

        if self.status == "ready":
            if self.ready_evidence_count <= 0:
                raise ValueError(
                    "ready accumulator requires ready evidence"
                )
            if self.blocker is not None:
                raise ValueError(
                    "ready accumulator cannot have a blocker"
                )
            for name, summary in (
                (
                    "total_run_mean_delta_summary",
                    self.total_run_mean_delta_summary,
                ),
                (
                    "total_run_mean_relative_delta_summary",
                    self.total_run_mean_relative_delta_summary,
                ),
            ):
                if not isinstance(summary, StatisticalSummary):
                    raise TypeError(
                        f"{name} must be a StatisticalSummary"
                    )
                if summary.count != self.ready_evidence_count:
                    raise ValueError(
                        f"{name} count must match ready evidence"
                    )
        else:
            if self.ready_evidence_count != 0:
                raise ValueError(
                    "unavailable accumulator cannot have ready evidence"
                )
            if self.blocker != "ready_evidence_empty":
                raise ValueError(
                    "unavailable accumulator requires ready_evidence_empty"
                )
            if (
                self.total_run_mean_delta_summary is not None
                or self.total_run_mean_relative_delta_summary is not None
            ):
                raise ValueError(
                    "unavailable accumulator cannot have summaries"
                )

        _validate_count_pairs(
            "component_diagnosis_counts",
            self.component_diagnosis_counts,
        )
        if tuple(
            name for name, _ in self.component_diagnosis_counts
        ) != _DIAGNOSIS_NAMES:
            raise ValueError(
                "component diagnosis counts must use canonical order"
            )
        if sum(
            count for _, count in self.component_diagnosis_counts
        ) != self.low_total_signal_count:
            raise ValueError(
                "component diagnoses must reconcile with low-total count"
            )
        _validate_rate_pairs(
            "component_relative_delta_means",
            self.component_relative_delta_means,
        )
        if tuple(
            name for name, _ in self.component_relative_delta_means
        ) != LOW_TOTAL_COMPONENTS:
            raise ValueError(
                "component means must use canonical order"
            )
        _validate_count_pairs("blocker_counts", self.blocker_counts)

        if len(self.evidence_artifact_digests) != (
            self.ready_evidence_count
            + self.unavailable_evidence_count
        ):
            raise ValueError(
                "evidence digest count must match non-error evidence"
            )
        if tuple(sorted(set(self.evidence_artifact_digests))) != (
            self.evidence_artifact_digests
        ):
            raise ValueError(
                "evidence artifact digests must be sorted and unique"
            )
        for value in self.evidence_artifact_digests:
            _validate_digest("evidence artifact digest", value)
        if len(self.observed_artifact_digests) != (
            self.unique_observed_artifact_count
        ):
            raise ValueError(
                "observed artifact digest count must reconcile"
            )
        if tuple(sorted(set(self.observed_artifact_digests))) != (
            self.observed_artifact_digests
        ):
            raise ValueError(
                "observed artifact digests must be sorted and unique"
            )
        for value in self.observed_artifact_digests:
            _validate_digest("observed artifact digest", value)
        _validate_digest("artifact_digest", self.artifact_digest)

    @property
    def ready(self) -> bool:
        return self.status == "ready"

    def to_diagnostics(self) -> Mapping[str, object]:
        return {
            "schema_version": self.schema_version,
            "status": self.status,
            "ready": self.ready,
            "input_evidence_count": self.input_evidence_count,
            "unique_evidence_count": self.unique_evidence_count,
            "duplicate_evidence_count": self.duplicate_evidence_count,
            "ready_evidence_count": self.ready_evidence_count,
            "unavailable_evidence_count": (
                self.unavailable_evidence_count
            ),
            "error_evidence_count": self.error_evidence_count,
            "simulation_count": self.simulation_count,
            "unique_observed_artifact_count": (
                self.unique_observed_artifact_count
            ),
            "unique_observed_game_count": (
                self.unique_observed_game_count
            ),
            "low_total_signal_count": self.low_total_signal_count,
            "low_total_signal_rate": self.low_total_signal_rate,
            "total_run_mean_delta_summary": (
                None
                if self.total_run_mean_delta_summary is None
                else asdict(self.total_run_mean_delta_summary)
            ),
            "total_run_mean_relative_delta_summary": (
                None
                if self.total_run_mean_relative_delta_summary is None
                else asdict(
                    self.total_run_mean_relative_delta_summary
                )
            ),
            "component_diagnosis_counts": _pairs_to_dict(
                self.component_diagnosis_counts
            ),
            "component_relative_delta_means": _pairs_to_dict(
                self.component_relative_delta_means
            ),
            "blocker_counts": _pairs_to_dict(self.blocker_counts),
            "evidence_artifact_digests": list(
                self.evidence_artifact_digests
            ),
            "observed_artifact_digests": list(
                self.observed_artifact_digests
            ),
            "artifact_digest": self.artifact_digest,
            "blocker": self.blocker,
            "input_evidence_consumed": True,
            "duplicate_evidence_deduplicated": True,
            "observed_artifacts_deduplicated": True,
            "independent_trial_execution": False,
            "database_accessed": False,
            "network_accessed": False,
            "external_fetch_performed": False,
            "persistence_performed": False,
            "measurement_only": True,
            "causal_claim_permitted": False,
            "calibration_parameters_selected": False,
            "activation_permitted": False,
            "production_authority_changed": False,
        }


def _sha256(payload: object) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _round_mean(values) -> float:
    values = tuple(float(value) for value in values)
    if not values:
        return 0.0
    return round(sum(values) / len(values), 6)


def accumulate_canonical_production_run_environment_evidence(
    evidence_artifacts,
) -> CanonicalProductionRunEnvironmentEvidenceAccumulator:
    """Accumulate already-created evidence without new execution."""

    artifacts = tuple(evidence_artifacts)
    if not artifacts:
        raise ValueError("evidence_artifacts cannot be empty")
    for artifact in artifacts:
        if not isinstance(
            artifact,
            CanonicalProductionRunEnvironmentEvidence,
        ):
            raise TypeError(
                "evidence_artifacts must contain "
                "CanonicalProductionRunEnvironmentEvidence"
            )

    unique_by_identity = {}
    for artifact in artifacts:
        identity = _sha256(artifact.to_diagnostics())
        unique_by_identity.setdefault(identity, artifact)
    unique_artifacts = tuple(
        unique_by_identity[identity]
        for identity in sorted(unique_by_identity)
    )

    ready_artifacts = tuple(
        artifact
        for artifact in unique_artifacts
        if artifact.status == "ready"
    )
    unavailable_artifacts = tuple(
        artifact
        for artifact in unique_artifacts
        if artifact.status == "unavailable"
    )
    error_artifacts = tuple(
        artifact
        for artifact in unique_artifacts
        if artifact.status == "error"
    )

    backtests = tuple(
        artifact.backtest
        for artifact in ready_artifacts
        if artifact.backtest is not None
    )
    if len(backtests) != len(ready_artifacts):
        raise ValueError(
            "ready evidence must expose backtest artifacts"
        )

    observed_game_counts = {}
    for artifact in ready_artifacts:
        observed = artifact.observed
        if observed is None:
            raise ValueError(
                "ready evidence must expose observed artifact"
            )
        previous = observed_game_counts.setdefault(
            observed.artifact_digest,
            observed.game_count,
        )
        if previous != observed.game_count:
            raise ValueError(
                "observed artifact game count conflict"
            )

    low_total_backtests = tuple(
        backtest
        for backtest in backtests
        if backtest.low_total_signal
    )
    diagnosis_counts = {
        name: 0
        for name in _DIAGNOSIS_NAMES
    }
    for backtest in low_total_backtests:
        diagnosis = (
            backtest.largest_negative_component
            or "unattributed"
        )
        diagnosis_counts[diagnosis] += 1

    component_values = {
        name: []
        for name in LOW_TOTAL_COMPONENTS
    }
    for backtest in backtests:
        values = dict(backtest.component_relative_deltas)
        for name in LOW_TOTAL_COMPONENTS:
            component_values[name].append(values[name])

    blocker_counts_map = {}
    for artifact in unavailable_artifacts:
        blocker = artifact.blocker
        if blocker is None:
            raise ValueError(
                "unavailable evidence must expose blocker"
            )
        blocker_counts_map[blocker] = (
            blocker_counts_map.get(blocker, 0) + 1
        )

    ready_count = len(ready_artifacts)
    status = "ready" if ready_count else "unavailable"
    blocker = None if ready_count else "ready_evidence_empty"
    total_delta_summary = (
        summarize_values(
            tuple(
                backtest.total_run_mean_delta
                for backtest in backtests
            )
        )
        if ready_count
        else None
    )
    relative_delta_summary = (
        summarize_values(
            tuple(
                backtest.total_run_mean_relative_delta
                for backtest in backtests
            )
        )
        if ready_count
        else None
    )

    component_diagnosis_counts = tuple(
        (name, diagnosis_counts[name])
        for name in _DIAGNOSIS_NAMES
    )
    component_relative_delta_means = tuple(
        (name, _round_mean(component_values[name]))
        for name in LOW_TOTAL_COMPONENTS
    )
    blocker_counts = tuple(sorted(blocker_counts_map.items()))
    evidence_digests = tuple(
        sorted(
            artifact.artifact_digest
            for artifact in unique_artifacts
            if artifact.status != "error"
        )
    )
    observed_digests = tuple(sorted(observed_game_counts))
    low_total_count = len(low_total_backtests)
    low_total_rate = (
        round(low_total_count / ready_count, 6)
        if ready_count
        else 0.0
    )

    digest_payload = {
        "schema_version": (
            CANONICAL_PRODUCTION_RUN_ENVIRONMENT_EVIDENCE_ACCUMULATOR_VERSION
        ),
        "status": status,
        "input_evidence_count": len(artifacts),
        "unique_evidence_count": len(unique_artifacts),
        "duplicate_evidence_count": (
            len(artifacts) - len(unique_artifacts)
        ),
        "ready_evidence_count": ready_count,
        "unavailable_evidence_count": len(unavailable_artifacts),
        "error_evidence_count": len(error_artifacts),
        "simulation_count": sum(
            backtest.simulation_count
            for backtest in backtests
        ),
        "unique_observed_artifact_count": len(observed_digests),
        "unique_observed_game_count": sum(
            observed_game_counts.values()
        ),
        "low_total_signal_count": low_total_count,
        "low_total_signal_rate": low_total_rate,
        "total_run_mean_delta_summary": (
            None
            if total_delta_summary is None
            else asdict(total_delta_summary)
        ),
        "total_run_mean_relative_delta_summary": (
            None
            if relative_delta_summary is None
            else asdict(relative_delta_summary)
        ),
        "component_diagnosis_counts": dict(
            component_diagnosis_counts
        ),
        "component_relative_delta_means": dict(
            component_relative_delta_means
        ),
        "blocker_counts": dict(blocker_counts),
        "evidence_artifact_digests": list(evidence_digests),
        "observed_artifact_digests": list(observed_digests),
        "blocker": blocker,
    }

    return CanonicalProductionRunEnvironmentEvidenceAccumulator(
        status=status,
        input_evidence_count=len(artifacts),
        unique_evidence_count=len(unique_artifacts),
        duplicate_evidence_count=(
            len(artifacts) - len(unique_artifacts)
        ),
        ready_evidence_count=ready_count,
        unavailable_evidence_count=len(unavailable_artifacts),
        error_evidence_count=len(error_artifacts),
        simulation_count=sum(
            backtest.simulation_count
            for backtest in backtests
        ),
        unique_observed_artifact_count=len(observed_digests),
        unique_observed_game_count=sum(
            observed_game_counts.values()
        ),
        low_total_signal_count=low_total_count,
        low_total_signal_rate=low_total_rate,
        total_run_mean_delta_summary=total_delta_summary,
        total_run_mean_relative_delta_summary=(
            relative_delta_summary
        ),
        component_diagnosis_counts=component_diagnosis_counts,
        component_relative_delta_means=(
            component_relative_delta_means
        ),
        blocker_counts=blocker_counts,
        evidence_artifact_digests=evidence_digests,
        observed_artifact_digests=observed_digests,
        artifact_digest=_sha256(digest_payload),
        blocker=blocker,
    )

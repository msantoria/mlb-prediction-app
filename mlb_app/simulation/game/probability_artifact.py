"""Canonical probability-artifact contracts and provider adapter."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
from functools import cached_property
from typing import Tuple

from .matchup_input import (
    CanonicalProbabilityProviderIdentity,
)
from .probability import (
    CANONICAL_PA_OUTCOME_ORDER,
    CanonicalOutcomeProbability,
    CanonicalPlateAppearanceOutcome,
    CanonicalPlateAppearanceProbabilities,
    CanonicalPlateAppearanceProbabilityProvider,
    CanonicalPlateAppearanceQuery,
)


CANONICAL_PROBABILITY_ARTIFACT_VERSION = (
    "canonical_probability_artifact_v1"
)
CANONICAL_PROBABILITY_ARTIFACT_ADAPTER_VERSION = (
    "canonical_probability_artifact_adapter_v1"
)


@dataclass(frozen=True)
class CanonicalProbabilityArtifactRecord:
    """
    One immutable batter-versus-pitcher probability artifact row.

    This initial production-facing contract performs exact identity
    lookup only. State-dependent features, fallbacks, and live model
    inference remain outside this slice.
    """

    batter_id: str
    pitcher_id: str
    probabilities: Tuple[
        CanonicalOutcomeProbability,
        ...,
    ]

    def __post_init__(self) -> None:
        if not self.batter_id:
            raise ValueError(
                "batter_id is required"
            )

        if not self.pitcher_id:
            raise ValueError(
                "pitcher_id is required"
            )

        outcomes = tuple(
            point.outcome
            for point in self.probabilities
        )

        if outcomes != CANONICAL_PA_OUTCOME_ORDER:
            raise ValueError(
                "artifact probabilities must contain "
                "every canonical outcome exactly once "
                "in canonical order"
            )

        total = sum(
            point.probability
            for point in self.probabilities
        )

        if abs(total - 1.0) > 0.000000001:
            raise ValueError(
                "artifact probabilities must sum to 1"
            )

    @property
    def matchup_key(self) -> Tuple[str, str]:
        return (
            self.batter_id,
            self.pitcher_id,
        )


@dataclass(frozen=True)
class CanonicalProbabilityArtifact:
    """
    Immutable probability artifact with explicit provenance.

    The artifact contains already-produced probabilities. It does not
    train models, load files, fetch external data, or infer missing rows.
    """

    provider: CanonicalProbabilityProviderIdentity
    records: Tuple[
        CanonicalProbabilityArtifactRecord,
        ...,
    ]
    artifact_version: str = (
        CANONICAL_PROBABILITY_ARTIFACT_VERSION
    )

    def __post_init__(self) -> None:
        if not isinstance(
            self.provider,
            CanonicalProbabilityProviderIdentity,
        ):
            raise TypeError(
                "provider must be a "
                "CanonicalProbabilityProviderIdentity"
            )

        if self.artifact_version != (
            CANONICAL_PROBABILITY_ARTIFACT_VERSION
        ):
            raise ValueError(
                "unsupported canonical probability "
                "artifact version"
            )

        keys = tuple(
            record.matchup_key
            for record in self.records
        )

        if len(keys) != len(set(keys)):
            raise ValueError(
                "artifact cannot contain duplicate "
                "batter-pitcher matchup rows"
            )

    @cached_property
    def digest(self) -> str:
        payload_parts = [
            self.artifact_version,
            self.provider.identity,
        ]

        for record in sorted(
            self.records,
            key=lambda value: value.matchup_key,
        ):
            payload_parts.extend(
                (
                    record.batter_id,
                    record.pitcher_id,
                )
            )
            payload_parts.extend(
                (
                    f"{point.outcome.value}:"
                    f"{point.probability:.17g}"
                )
                for point in record.probabilities
            )

        payload = "\x1f".join(
            payload_parts
        ).encode("utf-8")

        return hashlib.sha256(
            payload
        ).hexdigest()

    def record_for(
        self,
        *,
        batter_id: str,
        pitcher_id: str,
    ) -> CanonicalProbabilityArtifactRecord:
        key = (
            batter_id,
            pitcher_id,
        )

        for record in self.records:
            if record.matchup_key == key:
                return record

        raise KeyError(
            "canonical probability artifact has no "
            f"row for batter={batter_id}, "
            f"pitcher={pitcher_id}"
        )


@dataclass(frozen=True)
class CanonicalProbabilityArtifactAdapter:
    """
    Adapt exact artifact rows to canonical PA probability responses.
    """

    artifact: CanonicalProbabilityArtifact
    adapter_version: str = (
        CANONICAL_PROBABILITY_ARTIFACT_ADAPTER_VERSION
    )

    def __post_init__(self) -> None:
        if not isinstance(
            self.artifact,
            CanonicalProbabilityArtifact,
        ):
            raise TypeError(
                "artifact must be a "
                "CanonicalProbabilityArtifact"
            )

        if self.adapter_version != (
            CANONICAL_PROBABILITY_ARTIFACT_ADAPTER_VERSION
        ):
            raise ValueError(
                "unsupported canonical probability "
                "artifact adapter version"
            )

    def __call__(
        self,
        query: CanonicalPlateAppearanceQuery,
    ) -> CanonicalPlateAppearanceProbabilities:
        if not isinstance(
            query,
            CanonicalPlateAppearanceQuery,
        ):
            raise TypeError(
                "query must be a "
                "CanonicalPlateAppearanceQuery"
            )

        if (
            query.matchup_input.probability_provider
            != self.artifact.provider
        ):
            raise ValueError(
                "artifact provider must match "
                "matchup probability-provider identity"
            )

        record = self.artifact.record_for(
            batter_id=query.batter_id,
            pitcher_id=query.pitcher_id,
        )

        return CanonicalPlateAppearanceProbabilities(
            query=query,
            probabilities=record.probabilities,
            provider=self.artifact.provider,
        )


def build_canonical_probability_artifact_provider(
    artifact: CanonicalProbabilityArtifact,
) -> CanonicalPlateAppearanceProbabilityProvider:
    """Build a provider-compatible exact artifact adapter."""

    return CanonicalProbabilityArtifactAdapter(
        artifact=artifact,
    )

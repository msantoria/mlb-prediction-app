"""Explicit canonical probability fallback-policy contracts."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import hashlib
from functools import cached_property
from typing import Optional, Tuple

from .matchup_input import (
    CanonicalProbabilityProviderIdentity,
)
from .probability import (
    CANONICAL_PA_OUTCOME_ORDER,
    CanonicalOutcomeProbability,
    CanonicalPlateAppearanceProbabilities,
    CanonicalPlateAppearanceProbabilityProvider,
    CanonicalPlateAppearanceQuery,
)
from .probability_artifact import (
    CanonicalProbabilityArtifact,
)


CANONICAL_PROBABILITY_FALLBACK_VERSION = (
    "canonical_probability_fallback_v1"
)


class CanonicalProbabilityFallbackTier(str, Enum):
    """Observable probability-resolution tiers."""

    EXACT_MATCHUP = "exact_matchup"
    BATTER = "batter"
    PITCHER = "pitcher"
    GLOBAL = "global"


DEFAULT_CANONICAL_PROBABILITY_FALLBACK_TIERS = (
    CanonicalProbabilityFallbackTier.EXACT_MATCHUP,
)


@dataclass(frozen=True)
class CanonicalProbabilityFallbackRecord:
    """One immutable non-exact fallback distribution."""

    tier: CanonicalProbabilityFallbackTier
    identity: Optional[str]
    probabilities: Tuple[
        CanonicalOutcomeProbability,
        ...,
    ]

    def __post_init__(self) -> None:
        if not isinstance(
            self.tier,
            CanonicalProbabilityFallbackTier,
        ):
            raise TypeError(
                "tier must be a "
                "CanonicalProbabilityFallbackTier"
            )

        if (
            self.tier
            is CanonicalProbabilityFallbackTier.EXACT_MATCHUP
        ):
            raise ValueError(
                "exact matchup rows belong in the exact artifact"
            )

        if self.tier in {
            CanonicalProbabilityFallbackTier.BATTER,
            CanonicalProbabilityFallbackTier.PITCHER,
        }:
            if not self.identity:
                raise ValueError(
                    "batter and pitcher fallback records "
                    "require identity"
                )
        elif self.identity is not None:
            raise ValueError(
                "global fallback identity must be None"
            )

        _validate_probabilities(
            self.probabilities
        )

    @property
    def record_key(
        self,
    ) -> Tuple[
        CanonicalProbabilityFallbackTier,
        Optional[str],
    ]:
        return (
            self.tier,
            self.identity,
        )


@dataclass(frozen=True)
class CanonicalProbabilityFallbackCatalog:
    """Immutable, provider-bound fallback distributions."""

    provider: CanonicalProbabilityProviderIdentity
    records: Tuple[
        CanonicalProbabilityFallbackRecord,
        ...,
    ]
    schema_version: str = (
        CANONICAL_PROBABILITY_FALLBACK_VERSION
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

        if self.schema_version != (
            CANONICAL_PROBABILITY_FALLBACK_VERSION
        ):
            raise ValueError(
                "unsupported probability fallback schema"
            )

        keys = tuple(
            record.record_key
            for record in self.records
        )

        if len(keys) != len(set(keys)):
            raise ValueError(
                "fallback catalog cannot contain "
                "duplicate tier-identity rows"
            )

    @cached_property
    def digest(self) -> str:
        parts = [
            self.schema_version,
            self.provider.identity,
        ]

        for record in sorted(
            self.records,
            key=lambda value: (
                value.tier.value,
                value.identity or "",
            ),
        ):
            parts.extend(
                (
                    record.tier.value,
                    record.identity or "",
                )
            )
            parts.extend(
                f"{point.outcome.value}:"
                f"{point.probability:.17g}"
                for point in record.probabilities
            )

        return hashlib.sha256(
            "\x1f".join(parts).encode("utf-8")
        ).hexdigest()

    def record_for(
        self,
        *,
        tier: CanonicalProbabilityFallbackTier,
        identity: Optional[str],
    ) -> CanonicalProbabilityFallbackRecord:
        key = (
            tier,
            identity,
        )

        for record in self.records:
            if record.record_key == key:
                return record

        raise KeyError(key)


@dataclass(frozen=True)
class CanonicalProbabilityFallbackPolicy:
    """
    Explicit ordered fallback policy.

    The default contains only exact lookup, preserving the existing
    fail-closed behavior unless fallback tiers are deliberately enabled.
    """

    tiers: Tuple[
        CanonicalProbabilityFallbackTier,
        ...,
    ] = DEFAULT_CANONICAL_PROBABILITY_FALLBACK_TIERS
    policy_version: str = (
        CANONICAL_PROBABILITY_FALLBACK_VERSION
    )

    def __post_init__(self) -> None:
        if self.policy_version != (
            CANONICAL_PROBABILITY_FALLBACK_VERSION
        ):
            raise ValueError(
                "unsupported probability fallback policy"
            )

        if not self.tiers:
            raise ValueError(
                "fallback policy requires at least one tier"
            )

        if any(
            not isinstance(
                tier,
                CanonicalProbabilityFallbackTier,
            )
            for tier in self.tiers
        ):
            raise TypeError(
                "all fallback tiers must be canonical tiers"
            )

        if len(self.tiers) != len(set(self.tiers)):
            raise ValueError(
                "fallback policy tiers must be unique"
            )

        if self.tiers[0] is not (
            CanonicalProbabilityFallbackTier.EXACT_MATCHUP
        ):
            raise ValueError(
                "exact matchup must be the first tier"
            )


@dataclass(frozen=True)
class CanonicalProbabilityFallbackResolution:
    """Observable result of one exact-or-fallback lookup."""

    probabilities: CanonicalPlateAppearanceProbabilities
    tier: CanonicalProbabilityFallbackTier
    source_identity: Optional[str]
    exact_artifact_digest: str
    fallback_catalog_digest: str
    policy_version: str = (
        CANONICAL_PROBABILITY_FALLBACK_VERSION
    )

    def __post_init__(self) -> None:
        if not isinstance(
            self.probabilities,
            CanonicalPlateAppearanceProbabilities,
        ):
            raise TypeError(
                "probabilities must be canonical "
                "plate-appearance probabilities"
            )

        if not isinstance(
            self.tier,
            CanonicalProbabilityFallbackTier,
        ):
            raise TypeError(
                "tier must be a canonical fallback tier"
            )

        if self.policy_version != (
            CANONICAL_PROBABILITY_FALLBACK_VERSION
        ):
            raise ValueError(
                "unsupported probability fallback resolution"
            )

        for name, digest in (
            (
                "exact_artifact_digest",
                self.exact_artifact_digest,
            ),
            (
                "fallback_catalog_digest",
                self.fallback_catalog_digest,
            ),
        ):
            if (
                len(digest) != 64
                or any(
                    character not in "0123456789abcdef"
                    for character in digest
                )
            ):
                raise ValueError(
                    f"{name} must be a SHA256 digest"
                )


@dataclass(frozen=True)
class CanonicalProbabilityFallbackAdapter:
    """Resolve exact rows and explicitly enabled fallback tiers."""

    exact_artifact: CanonicalProbabilityArtifact
    fallback_catalog: CanonicalProbabilityFallbackCatalog
    policy: CanonicalProbabilityFallbackPolicy = (
        CanonicalProbabilityFallbackPolicy()
    )

    def __post_init__(self) -> None:
        if not isinstance(
            self.exact_artifact,
            CanonicalProbabilityArtifact,
        ):
            raise TypeError(
                "exact_artifact must be a "
                "CanonicalProbabilityArtifact"
            )

        if not isinstance(
            self.fallback_catalog,
            CanonicalProbabilityFallbackCatalog,
        ):
            raise TypeError(
                "fallback_catalog must be a "
                "CanonicalProbabilityFallbackCatalog"
            )

        if not isinstance(
            self.policy,
            CanonicalProbabilityFallbackPolicy,
        ):
            raise TypeError(
                "policy must be a "
                "CanonicalProbabilityFallbackPolicy"
            )

        if (
            self.exact_artifact.provider
            != self.fallback_catalog.provider
        ):
            raise ValueError(
                "exact artifact and fallback catalog "
                "must use the same provider identity"
            )

    def resolve(
        self,
        query: CanonicalPlateAppearanceQuery,
    ) -> CanonicalProbabilityFallbackResolution:
        if not isinstance(
            query,
            CanonicalPlateAppearanceQuery,
        ):
            raise TypeError(
                "query must be a "
                "CanonicalPlateAppearanceQuery"
            )

        provider = self.exact_artifact.provider

        if (
            query.matchup_input.probability_provider
            != provider
        ):
            raise ValueError(
                "fallback provider must match matchup "
                "probability-provider identity"
            )

        for tier in self.policy.tiers:
            record = self._record_for_tier(
                query=query,
                tier=tier,
            )

            if record is None:
                continue

            probabilities = (
                CanonicalPlateAppearanceProbabilities(
                    query=query,
                    probabilities=record[0],
                    provider=provider,
                )
            )

            return CanonicalProbabilityFallbackResolution(
                probabilities=probabilities,
                tier=tier,
                source_identity=record[1],
                exact_artifact_digest=(
                    self.exact_artifact.digest
                ),
                fallback_catalog_digest=(
                    self.fallback_catalog.digest
                ),
                policy_version=(
                    self.policy.policy_version
                ),
            )

        raise KeyError(
            "canonical probability fallback policy "
            "could not resolve "
            f"batter={query.batter_id}, "
            f"pitcher={query.pitcher_id}; "
            f"enabled_tiers="
            f"{tuple(tier.value for tier in self.policy.tiers)}"
        )

    def __call__(
        self,
        query: CanonicalPlateAppearanceQuery,
    ) -> CanonicalPlateAppearanceProbabilities:
        return self.resolve(
            query
        ).probabilities

    def _record_for_tier(
        self,
        *,
        query: CanonicalPlateAppearanceQuery,
        tier: CanonicalProbabilityFallbackTier,
    ) -> Optional[
        Tuple[
            Tuple[
                CanonicalOutcomeProbability,
                ...,
            ],
            Optional[str],
        ]
    ]:
        if tier is (
            CanonicalProbabilityFallbackTier.EXACT_MATCHUP
        ):
            try:
                record = self.exact_artifact.record_for(
                    batter_id=query.batter_id,
                    pitcher_id=query.pitcher_id,
                )
            except KeyError:
                return None

            return (
                record.probabilities,
                (
                    f"{record.batter_id}:"
                    f"{record.pitcher_id}"
                ),
            )

        identity = (
            query.batter_id
            if tier
            is CanonicalProbabilityFallbackTier.BATTER
            else (
                query.pitcher_id
                if tier
                is CanonicalProbabilityFallbackTier.PITCHER
                else None
            )
        )

        try:
            record = self.fallback_catalog.record_for(
                tier=tier,
                identity=identity,
            )
        except KeyError:
            return None

        return (
            record.probabilities,
            record.identity,
        )


def build_canonical_probability_fallback_provider(
    *,
    exact_artifact: CanonicalProbabilityArtifact,
    fallback_catalog: CanonicalProbabilityFallbackCatalog,
    policy: Optional[
        CanonicalProbabilityFallbackPolicy
    ] = None,
) -> CanonicalPlateAppearanceProbabilityProvider:
    """Build an explicitly configured fallback-capable provider."""

    return CanonicalProbabilityFallbackAdapter(
        exact_artifact=exact_artifact,
        fallback_catalog=fallback_catalog,
        policy=(
            policy
            or CanonicalProbabilityFallbackPolicy()
        ),
    )


def _validate_probabilities(
    probabilities: Tuple[
        CanonicalOutcomeProbability,
        ...,
    ],
) -> None:
    outcomes = tuple(
        point.outcome
        for point in probabilities
    )

    if outcomes != CANONICAL_PA_OUTCOME_ORDER:
        raise ValueError(
            "fallback probabilities must contain "
            "every canonical outcome exactly once "
            "in canonical order"
        )

    total = sum(
        point.probability
        for point in probabilities
    )

    if abs(total - 1.0) > 0.000000001:
        raise ValueError(
            "fallback probabilities must sum to 1"
        )

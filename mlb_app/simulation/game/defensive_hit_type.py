"""Deterministic hit-type resolution for missed defensive plays."""

from __future__ import annotations

from dataclasses import dataclass
import random
from typing import Any, Dict, Mapping, Tuple

from mlb_app.simulation.events import (
    BattedBallDepth,
    BattedBallType,
    ContactQuality,
)

from .defensive_opportunity import (
    CanonicalDefensiveOpportunity,
)
from .defensive_outcome_reconciliation import (
    CanonicalReconciledBattedBallOutcome,
)
from .defensive_outcome_sampling import (
    CanonicalDefensiveOutcome,
    CanonicalSampledDefensiveOutcome,
)


CANONICAL_DEFENSIVE_HIT_TYPE_VERSION = (
    "canonical_defensive_hit_type_v1"
)

CANONICAL_DEFENSIVE_HIT_TYPE_ORDER = (
    CanonicalReconciledBattedBallOutcome.SINGLE,
    CanonicalReconciledBattedBallOutcome.DOUBLE,
    CanonicalReconciledBattedBallOutcome.TRIPLE,
)

BASELINE_HIT_TYPE_WEIGHTS: Mapping[
    Tuple[BattedBallType, BattedBallDepth],
    Tuple[float, float, float],
] = {
    (
        BattedBallType.GROUND_BALL,
        BattedBallDepth.SHALLOW,
    ): (0.94, 0.055, 0.005),
    (
        BattedBallType.GROUND_BALL,
        BattedBallDepth.MEDIUM,
    ): (0.88, 0.11, 0.01),
    (
        BattedBallType.LINE_DRIVE,
        BattedBallDepth.SHALLOW,
    ): (0.85, 0.14, 0.01),
    (
        BattedBallType.LINE_DRIVE,
        BattedBallDepth.MEDIUM,
    ): (0.65, 0.32, 0.03),
    (
        BattedBallType.LINE_DRIVE,
        BattedBallDepth.DEEP,
    ): (0.45, 0.48, 0.07),
    (
        BattedBallType.FLY_BALL,
        BattedBallDepth.SHALLOW,
    ): (0.75, 0.24, 0.01),
    (
        BattedBallType.FLY_BALL,
        BattedBallDepth.MEDIUM,
    ): (0.55, 0.42, 0.03),
    (
        BattedBallType.FLY_BALL,
        BattedBallDepth.DEEP,
    ): (0.30, 0.62, 0.08),
    (
        BattedBallType.POPUP,
        BattedBallDepth.SHALLOW,
    ): (0.96, 0.035, 0.005),
    (
        BattedBallType.POPUP,
        BattedBallDepth.MEDIUM,
    ): (0.94, 0.05, 0.01),
    (
        BattedBallType.POPUP,
        BattedBallDepth.DEEP,
    ): (0.90, 0.085, 0.015),
}


@dataclass(frozen=True)
class CanonicalDefensiveHitTypeProbability:
    hit_type: CanonicalReconciledBattedBallOutcome
    probability: float

    def __post_init__(self) -> None:
        if self.hit_type not in (
            CANONICAL_DEFENSIVE_HIT_TYPE_ORDER
        ):
            raise ValueError(
                "hit_type must be single, double, or triple"
            )

        if not 0.0 <= self.probability <= 1.0:
            raise ValueError(
                "probability must be between 0 and 1"
            )


@dataclass(frozen=True)
class CanonicalDefensiveHitTypeDistribution:
    opportunity: CanonicalDefensiveOpportunity
    probabilities: Tuple[
        CanonicalDefensiveHitTypeProbability,
        ...,
    ]
    schema_version: str = (
        CANONICAL_DEFENSIVE_HIT_TYPE_VERSION
    )

    def __post_init__(self) -> None:
        if not isinstance(
            self.opportunity,
            CanonicalDefensiveOpportunity,
        ):
            raise TypeError(
                "opportunity must be canonical"
            )

        if tuple(
            point.hit_type
            for point in self.probabilities
        ) != CANONICAL_DEFENSIVE_HIT_TYPE_ORDER:
            raise ValueError(
                "hit types must use canonical order"
            )

        if abs(
            sum(
                point.probability
                for point in self.probabilities
            )
            - 1.0
        ) > 0.000000001:
            raise ValueError(
                "hit-type probabilities must sum to 1"
            )

        if self.schema_version != (
            CANONICAL_DEFENSIVE_HIT_TYPE_VERSION
        ):
            raise ValueError(
                "unsupported defensive hit-type version"
            )


@dataclass(frozen=True)
class CanonicalSampledDefensiveHitType:
    distribution: CanonicalDefensiveHitTypeDistribution
    hit_type: CanonicalReconciledBattedBallOutcome
    draw: float
    sampling_seed: int
    authoritative: bool = False
    schema_version: str = (
        CANONICAL_DEFENSIVE_HIT_TYPE_VERSION
    )

    def __post_init__(self) -> None:
        if self.hit_type not in (
            CANONICAL_DEFENSIVE_HIT_TYPE_ORDER
        ):
            raise ValueError(
                "sampled hit type is unsupported"
            )

        if not 0.0 <= self.draw < 1.0:
            raise ValueError("draw must be in [0, 1)")

        if (
            not isinstance(self.sampling_seed, int)
            or isinstance(self.sampling_seed, bool)
            or self.sampling_seed < 0
        ):
            raise ValueError(
                "sampling_seed must be non-negative"
            )

        if self.authoritative is not False:
            raise ValueError(
                "hit-type sampling is reconciliation evidence"
            )

        if self.schema_version != (
            CANONICAL_DEFENSIVE_HIT_TYPE_VERSION
        ):
            raise ValueError(
                "unsupported defensive hit-type version"
            )

    def to_diagnostics(self) -> Dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "hit_type": self.hit_type.value,
            "draw": self.draw,
            "sampling_seed": self.sampling_seed,
            "authoritative": self.authoritative,
            "probabilities": {
                point.hit_type.value: point.probability
                for point in self.distribution.probabilities
            },
        }


def build_canonical_defensive_hit_type_distribution(
    opportunity: CanonicalDefensiveOpportunity,
) -> CanonicalDefensiveHitTypeDistribution:
    if not isinstance(
        opportunity,
        CanonicalDefensiveOpportunity,
    ):
        raise TypeError(
            "opportunity must be canonical"
        )

    context = opportunity.context
    weights = list(
        BASELINE_HIT_TYPE_WEIGHTS[
            (
                context.batted_ball_type,
                context.depth,
            )
        ]
    )

    if context.contact_quality is ContactQuality.HARD:
        weights[0] *= 0.82
        weights[1] *= 1.30
        weights[2] *= 1.55
    elif context.contact_quality is ContactQuality.SOFT:
        weights[0] *= 1.12
        weights[1] *= 0.65
        weights[2] *= 0.45

    total = sum(weights)
    normalized = tuple(
        value / total
        for value in weights
    )

    return CanonicalDefensiveHitTypeDistribution(
        opportunity=opportunity,
        probabilities=tuple(
            CanonicalDefensiveHitTypeProbability(
                hit_type=hit_type,
                probability=probability,
            )
            for hit_type, probability in zip(
                CANONICAL_DEFENSIVE_HIT_TYPE_ORDER,
                normalized,
            )
        ),
    )


def sample_canonical_defensive_hit_type(
    *,
    defensive_sample: CanonicalSampledDefensiveOutcome,
    sampling_seed: int,
) -> CanonicalSampledDefensiveHitType:
    if not isinstance(
        defensive_sample,
        CanonicalSampledDefensiveOutcome,
    ):
        raise TypeError(
            "defensive_sample must be canonical"
        )

    if (
        defensive_sample.outcome
        is not CanonicalDefensiveOutcome.BASE_HIT
    ):
        raise ValueError(
            "defensive hit type requires a base-hit sample"
        )

    if (
        not isinstance(sampling_seed, int)
        or isinstance(sampling_seed, bool)
        or sampling_seed < 0
    ):
        raise ValueError(
            "sampling_seed must be non-negative"
        )

    distribution = (
        build_canonical_defensive_hit_type_distribution(
            defensive_sample.distribution.opportunity
        )
    )
    draw = random.Random(sampling_seed).random()
    cumulative = 0.0

    for point in distribution.probabilities:
        cumulative += point.probability

        if draw < cumulative:
            return CanonicalSampledDefensiveHitType(
                distribution=distribution,
                hit_type=point.hit_type,
                draw=draw,
                sampling_seed=sampling_seed,
            )

    raise RuntimeError(
        "validated hit-type distribution was not exhaustive"
    )

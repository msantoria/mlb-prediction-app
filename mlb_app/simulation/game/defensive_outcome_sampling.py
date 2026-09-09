"""Versioned shadow sampling for canonical defensive outcomes."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import random
from typing import Any, Dict, Mapping, Tuple

from .defensive_opportunity import (
    CanonicalDefensiveDifficulty,
    CanonicalDefensiveOpportunity,
)


CANONICAL_DEFENSIVE_OUTCOME_SAMPLING_VERSION = (
    "canonical_defensive_outcome_sampling_v1"
)
PROBABILITY_TOLERANCE = 0.000000001


class CanonicalDefensiveOutcome(str, Enum):
    """Possible defensive resolution of a ball in play."""

    CONVERTED_OUT = "converted_out"
    BASE_HIT = "base_hit"
    FIELDING_ERROR = "fielding_error"


CANONICAL_DEFENSIVE_OUTCOME_ORDER = tuple(
    CanonicalDefensiveOutcome
)


BASELINE_DEFENSIVE_OUTCOME_PROBABILITIES: Mapping[
    CanonicalDefensiveDifficulty,
    Tuple[float, float, float],
] = {
    CanonicalDefensiveDifficulty.ROUTINE: (
        0.94,
        0.04,
        0.02,
    ),
    CanonicalDefensiveDifficulty.AVERAGE: (
        0.75,
        0.22,
        0.03,
    ),
    CanonicalDefensiveDifficulty.DIFFICULT: (
        0.42,
        0.55,
        0.03,
    ),
}


@dataclass(frozen=True)
class CanonicalDefensiveOutcomeProbability:
    outcome: CanonicalDefensiveOutcome
    probability: float

    def __post_init__(self) -> None:
        if not isinstance(
            self.outcome,
            CanonicalDefensiveOutcome,
        ):
            raise TypeError(
                "outcome must be a CanonicalDefensiveOutcome"
            )

        if not isinstance(self.probability, (int, float)):
            raise TypeError("probability must be numeric")

        if not 0.0 <= float(self.probability) <= 1.0:
            raise ValueError(
                "probability must be between 0 and 1"
            )


@dataclass(frozen=True)
class CanonicalDefensiveOutcomeProbabilities:
    opportunity: CanonicalDefensiveOpportunity
    probabilities: Tuple[
        CanonicalDefensiveOutcomeProbability,
        ...,
    ]
    model_version: str = (
        CANONICAL_DEFENSIVE_OUTCOME_SAMPLING_VERSION
    )

    def __post_init__(self) -> None:
        if not isinstance(
            self.opportunity,
            CanonicalDefensiveOpportunity,
        ):
            raise TypeError(
                "opportunity must be a "
                "CanonicalDefensiveOpportunity"
            )

        outcomes = tuple(
            point.outcome
            for point in self.probabilities
        )

        if outcomes != CANONICAL_DEFENSIVE_OUTCOME_ORDER:
            raise ValueError(
                "probabilities must contain every defensive "
                "outcome exactly once in canonical order"
            )

        total = sum(
            point.probability
            for point in self.probabilities
        )

        if abs(total - 1.0) > PROBABILITY_TOLERANCE:
            raise ValueError(
                "defensive outcome probabilities must sum to 1"
            )

        if self.model_version != (
            CANONICAL_DEFENSIVE_OUTCOME_SAMPLING_VERSION
        ):
            raise ValueError(
                "unsupported defensive outcome sampling version"
            )

    def probability_for(
        self,
        outcome: CanonicalDefensiveOutcome,
    ) -> float:
        for point in self.probabilities:
            if point.outcome is outcome:
                return point.probability

        raise KeyError(outcome)


@dataclass(frozen=True)
class CanonicalSampledDefensiveOutcome:
    """Reproducible shadow result for one defensive opportunity."""

    distribution: CanonicalDefensiveOutcomeProbabilities
    outcome: CanonicalDefensiveOutcome
    draw: float
    sampling_seed: int
    authoritative: bool = False
    sampling_version: str = (
        CANONICAL_DEFENSIVE_OUTCOME_SAMPLING_VERSION
    )

    def __post_init__(self) -> None:
        if not isinstance(
            self.distribution,
            CanonicalDefensiveOutcomeProbabilities,
        ):
            raise TypeError(
                "distribution must be canonical defensive "
                "outcome probabilities"
            )

        if not isinstance(
            self.outcome,
            CanonicalDefensiveOutcome,
        ):
            raise TypeError(
                "outcome must be a CanonicalDefensiveOutcome"
            )

        if not 0.0 <= self.draw < 1.0:
            raise ValueError("draw must be in [0, 1)")

        if (
            not isinstance(self.sampling_seed, int)
            or isinstance(self.sampling_seed, bool)
            or self.sampling_seed < 0
        ):
            raise ValueError(
                "sampling_seed must be a non-negative integer"
            )

        if self.authoritative is not False:
            raise ValueError(
                "defensive outcome sampling is shadow-only"
            )

        if self.sampling_version != (
            CANONICAL_DEFENSIVE_OUTCOME_SAMPLING_VERSION
        ):
            raise ValueError(
                "unsupported defensive outcome sampling version"
            )

    def to_diagnostics(self) -> Dict[str, Any]:
        opportunity = self.distribution.opportunity

        return {
            "schema_version": self.sampling_version,
            "outcome": self.outcome.value,
            "draw": self.draw,
            "sampling_seed": self.sampling_seed,
            "authoritative": self.authoritative,
            "difficulty": opportunity.difficulty.value,
            "field_zone": opportunity.field_zone.value,
            "coverage_unit": opportunity.coverage_unit.value,
            "probabilities": {
                point.outcome.value: point.probability
                for point in self.distribution.probabilities
            },
        }


def build_baseline_defensive_outcome_probabilities(
    opportunity: CanonicalDefensiveOpportunity,
) -> CanonicalDefensiveOutcomeProbabilities:
    if not isinstance(
        opportunity,
        CanonicalDefensiveOpportunity,
    ):
        raise TypeError(
            "opportunity must be a "
            "CanonicalDefensiveOpportunity"
        )

    values = BASELINE_DEFENSIVE_OUTCOME_PROBABILITIES[
        opportunity.difficulty
    ]

    return CanonicalDefensiveOutcomeProbabilities(
        opportunity=opportunity,
        probabilities=tuple(
            CanonicalDefensiveOutcomeProbability(
                outcome=outcome,
                probability=probability,
            )
            for outcome, probability in zip(
                CANONICAL_DEFENSIVE_OUTCOME_ORDER,
                values,
            )
        ),
    )


def sample_canonical_defensive_outcome(
    *,
    opportunity: CanonicalDefensiveOpportunity,
    sampling_seed: int,
) -> CanonicalSampledDefensiveOutcome:
    if (
        not isinstance(sampling_seed, int)
        or isinstance(sampling_seed, bool)
        or sampling_seed < 0
    ):
        raise ValueError(
            "sampling_seed must be a non-negative integer"
        )

    distribution = (
        build_baseline_defensive_outcome_probabilities(
            opportunity
        )
    )
    draw = random.Random(sampling_seed).random()
    cumulative = 0.0

    for point in distribution.probabilities:
        cumulative += point.probability

        if draw < cumulative:
            return CanonicalSampledDefensiveOutcome(
                distribution=distribution,
                outcome=point.outcome,
                draw=draw,
                sampling_seed=sampling_seed,
            )

    raise RuntimeError(
        "validated defensive distribution was not exhaustive"
    )

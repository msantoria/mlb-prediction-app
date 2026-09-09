"""Canonical defensive opportunity derived from batted-ball context."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict

from mlb_app.simulation.events import (
    BattedBallContext,
    BattedBallDepth,
    BattedBallType,
    ContactQuality,
    SprayDirection,
)


CANONICAL_DEFENSIVE_OPPORTUNITY_VERSION = (
    "canonical_defensive_opportunity_v1"
)


class CanonicalFieldZone(str, Enum):
    """Relative field zone before batter-handedness translation."""

    INFIELD_PULL = "infield_pull"
    INFIELD_CENTER = "infield_center"
    INFIELD_OPPOSITE = "infield_opposite"
    OUTFIELD_PULL = "outfield_pull"
    OUTFIELD_CENTER = "outfield_center"
    OUTFIELD_OPPOSITE = "outfield_opposite"


class CanonicalDefensiveCoverageUnit(str, Enum):
    """Defensive unit responsible for the opportunity."""

    CORNER_INFIELD = "corner_infield"
    MIDDLE_INFIELD = "middle_infield"
    CORNER_OUTFIELD = "corner_outfield"
    CENTER_FIELD = "center_field"


class CanonicalDefensiveDifficulty(str, Enum):
    """Coarse opportunity difficulty."""

    ROUTINE = "routine"
    AVERAGE = "average"
    DIFFICULT = "difficult"


@dataclass(frozen=True)
class CanonicalDefensiveOpportunity:
    """Descriptive defense contract that does not change play results."""

    context: BattedBallContext
    field_zone: CanonicalFieldZone
    coverage_unit: CanonicalDefensiveCoverageUnit
    difficulty: CanonicalDefensiveDifficulty
    resolution_seed: int
    schema_version: str = (
        CANONICAL_DEFENSIVE_OPPORTUNITY_VERSION
    )

    def __post_init__(self) -> None:
        if not isinstance(self.context, BattedBallContext):
            raise TypeError(
                "context must be a BattedBallContext"
            )

        if not isinstance(self.field_zone, CanonicalFieldZone):
            raise TypeError(
                "field_zone must be a CanonicalFieldZone"
            )

        if not isinstance(
            self.coverage_unit,
            CanonicalDefensiveCoverageUnit,
        ):
            raise TypeError(
                "coverage_unit must be a "
                "CanonicalDefensiveCoverageUnit"
            )

        if not isinstance(
            self.difficulty,
            CanonicalDefensiveDifficulty,
        ):
            raise TypeError(
                "difficulty must be a "
                "CanonicalDefensiveDifficulty"
            )

        if (
            not isinstance(self.resolution_seed, int)
            or isinstance(self.resolution_seed, bool)
            or self.resolution_seed < 0
        ):
            raise ValueError(
                "resolution_seed must be a non-negative integer"
            )

        if self.schema_version != (
            CANONICAL_DEFENSIVE_OPPORTUNITY_VERSION
        ):
            raise ValueError(
                "unsupported defensive opportunity version"
            )

    def to_diagnostics(self) -> Dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "field_zone": self.field_zone.value,
            "coverage_unit": self.coverage_unit.value,
            "difficulty": self.difficulty.value,
            "resolution_seed": self.resolution_seed,
            "batted_ball_type": (
                self.context.batted_ball_type.value
            ),
            "direction": self.context.direction.value,
            "depth": self.context.depth.value,
            "contact_quality": (
                self.context.contact_quality.value
            ),
            "changes_play_result": False,
        }


def resolve_canonical_defensive_opportunity(
    *,
    context: BattedBallContext,
    resolution_seed: int,
) -> CanonicalDefensiveOpportunity:
    """
    Derive a reproducible defensive opportunity.

    Zones remain pull/center/opposite until an authoritative batter-hand
    adapter can translate them into absolute left/right field positions.
    This resolver records defensive context only and cannot change the
    sampled hit/out, runner movement, scoring, or box score.
    """

    if not isinstance(context, BattedBallContext):
        raise TypeError(
            "context must be a BattedBallContext"
        )

    if (
        not isinstance(resolution_seed, int)
        or isinstance(resolution_seed, bool)
        or resolution_seed < 0
    ):
        raise ValueError(
            "resolution_seed must be a non-negative integer"
        )

    infield = _is_infield_opportunity(context)
    field_zone = _field_zone(
        direction=context.direction,
        infield=infield,
    )
    coverage_unit = _coverage_unit(
        direction=context.direction,
        infield=infield,
    )
    difficulty = _difficulty(context)

    return CanonicalDefensiveOpportunity(
        context=context,
        field_zone=field_zone,
        coverage_unit=coverage_unit,
        difficulty=difficulty,
        resolution_seed=resolution_seed,
    )


def _is_infield_opportunity(
    context: BattedBallContext,
) -> bool:
    if context.batted_ball_type is BattedBallType.GROUND_BALL:
        return True

    if context.batted_ball_type is BattedBallType.POPUP:
        return context.depth is not BattedBallDepth.DEEP

    if context.batted_ball_type is BattedBallType.LINE_DRIVE:
        return context.depth is BattedBallDepth.SHALLOW

    return False


def _field_zone(
    *,
    direction: SprayDirection,
    infield: bool,
) -> CanonicalFieldZone:
    prefix = "infield" if infield else "outfield"

    return CanonicalFieldZone(
        f"{prefix}_{direction.value}"
    )


def _coverage_unit(
    *,
    direction: SprayDirection,
    infield: bool,
) -> CanonicalDefensiveCoverageUnit:
    if infield:
        if direction is SprayDirection.CENTER:
            return (
                CanonicalDefensiveCoverageUnit
                .MIDDLE_INFIELD
            )

        return (
            CanonicalDefensiveCoverageUnit
            .CORNER_INFIELD
        )

    if direction is SprayDirection.CENTER:
        return CanonicalDefensiveCoverageUnit.CENTER_FIELD

    return CanonicalDefensiveCoverageUnit.CORNER_OUTFIELD


def _difficulty(
    context: BattedBallContext,
) -> CanonicalDefensiveDifficulty:
    score = {
        ContactQuality.SOFT: 0,
        ContactQuality.MEDIUM: 1,
        ContactQuality.HARD: 2,
    }[context.contact_quality]

    if context.batted_ball_type is BattedBallType.LINE_DRIVE:
        score += 1

    if context.depth is BattedBallDepth.DEEP:
        score += 1

    if context.batted_ball_type is BattedBallType.POPUP:
        score -= 1

    if score <= 0:
        return CanonicalDefensiveDifficulty.ROUTINE

    if score >= 3:
        return CanonicalDefensiveDifficulty.DIFFICULT

    return CanonicalDefensiveDifficulty.AVERAGE

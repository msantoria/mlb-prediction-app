"""Canonical defensive alignment and fielder identity resolution."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import random
from typing import Any, Dict, Optional, Tuple

from .defensive_opportunity import (
    CanonicalDefensiveCoverageUnit,
    CanonicalDefensiveOpportunity,
)


CANONICAL_DEFENSIVE_ALIGNMENT_VERSION = (
    "canonical_defensive_alignment_v1"
)
CANONICAL_DEFENSIVE_FIELDER_RESOLUTION_VERSION = (
    "canonical_defensive_fielder_resolution_v1"
)


class CanonicalDefensivePosition(str, Enum):
    """The eight non-pitcher defensive positions."""

    CATCHER = "catcher"
    FIRST_BASE = "first_base"
    SECOND_BASE = "second_base"
    THIRD_BASE = "third_base"
    SHORTSTOP = "shortstop"
    LEFT_FIELD = "left_field"
    CENTER_FIELD = "center_field"
    RIGHT_FIELD = "right_field"


CANONICAL_DEFENSIVE_POSITION_ORDER = tuple(
    CanonicalDefensivePosition
)

_COVERAGE_POSITION_CANDIDATES = {
    CanonicalDefensiveCoverageUnit.CORNER_INFIELD: (
        CanonicalDefensivePosition.FIRST_BASE,
        CanonicalDefensivePosition.THIRD_BASE,
    ),
    CanonicalDefensiveCoverageUnit.MIDDLE_INFIELD: (
        CanonicalDefensivePosition.SECOND_BASE,
        CanonicalDefensivePosition.SHORTSTOP,
    ),
    CanonicalDefensiveCoverageUnit.CORNER_OUTFIELD: (
        CanonicalDefensivePosition.LEFT_FIELD,
        CanonicalDefensivePosition.RIGHT_FIELD,
    ),
    CanonicalDefensiveCoverageUnit.CENTER_FIELD: (
        CanonicalDefensivePosition.CENTER_FIELD,
    ),
}


def _normalize_player_id(
    value: Any,
) -> Optional[str]:
    if value in (None, "") or isinstance(value, bool):
        return None

    normalized = str(value).strip()
    return normalized or None


@dataclass(frozen=True)
class CanonicalDefensiveFielder:
    """One defensive position and its optional supported identity."""

    position: CanonicalDefensivePosition
    player_id: Optional[str] = None

    def __post_init__(self) -> None:
        if not isinstance(
            self.position,
            CanonicalDefensivePosition,
        ):
            raise TypeError(
                "position must be a "
                "CanonicalDefensivePosition"
            )

        object.__setattr__(
            self,
            "player_id",
            _normalize_player_id(self.player_id),
        )

    def to_diagnostics(self) -> Dict[str, Any]:
        return {
            "position": self.position.value,
            "player_id": self.player_id,
            "identity_available": self.player_id is not None,
        }


@dataclass(frozen=True)
class CanonicalDefensiveAlignment:
    """
    Eight-position alignment independent of batting-order position.

    Player identities are optional so incomplete source evidence remains
    explicit. An identity, when present, must belong to the team's
    canonical batting lineup.
    """

    team_side: str
    fielders: Tuple[CanonicalDefensiveFielder, ...]
    source_identifier: str
    source_as_of: str
    confidence: str
    schema_version: str = (
        CANONICAL_DEFENSIVE_ALIGNMENT_VERSION
    )

    def __post_init__(self) -> None:
        if self.team_side not in {"away", "home"}:
            raise ValueError(
                "team_side must be away or home"
            )

        if self.schema_version != (
            CANONICAL_DEFENSIVE_ALIGNMENT_VERSION
        ):
            raise ValueError(
                "unsupported defensive alignment version"
            )

        if not str(self.source_identifier).strip():
            raise ValueError(
                "source_identifier is required"
            )

        if not str(self.source_as_of).strip():
            raise ValueError(
                "source_as_of is required"
            )

        if not str(self.confidence).strip():
            raise ValueError(
                "confidence is required"
            )

        normalized = tuple(self.fielders)

        if len(normalized) != len(
            CANONICAL_DEFENSIVE_POSITION_ORDER
        ):
            raise ValueError(
                "defensive alignment requires eight fielders"
            )

        if any(
            not isinstance(
                fielder,
                CanonicalDefensiveFielder,
            )
            for fielder in normalized
        ):
            raise TypeError(
                "fielders must be canonical defensive fielders"
            )

        positions = tuple(
            fielder.position
            for fielder in normalized
        )

        if (
            len(set(positions)) != len(positions)
            or set(positions)
            != set(CANONICAL_DEFENSIVE_POSITION_ORDER)
        ):
            raise ValueError(
                "defensive alignment requires each "
                "non-pitcher position exactly once"
            )

        player_ids = tuple(
            fielder.player_id
            for fielder in normalized
            if fielder.player_id is not None
        )

        if len(set(player_ids)) != len(player_ids):
            raise ValueError(
                "defensive fielder identities must be unique"
            )

        object.__setattr__(
            self,
            "fielders",
            tuple(
                sorted(
                    normalized,
                    key=lambda fielder: (
                        CANONICAL_DEFENSIVE_POSITION_ORDER
                        .index(fielder.position)
                    ),
                )
            ),
        )

    @property
    def identified_player_ids(self) -> Tuple[str, ...]:
        return tuple(
            fielder.player_id
            for fielder in self.fielders
            if fielder.player_id is not None
        )

    @property
    def complete(self) -> bool:
        return (
            len(self.identified_player_ids)
            == len(self.fielders)
        )

    def fielder_for(
        self,
        position: CanonicalDefensivePosition,
    ) -> CanonicalDefensiveFielder:
        for fielder in self.fielders:
            if fielder.position is position:
                return fielder

        raise ValueError(
            "position is not present in defensive alignment"
        )

    def to_diagnostics(self) -> Dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "team_side": self.team_side,
            "source_identifier": self.source_identifier,
            "source_as_of": self.source_as_of,
            "confidence": self.confidence,
            "complete": self.complete,
            "identified_player_count": len(
                self.identified_player_ids
            ),
            "required_player_count": len(self.fielders),
            "fielders": [
                fielder.to_diagnostics()
                for fielder in self.fielders
            ],
            "authoritative": False,
        }


@dataclass(frozen=True)
class CanonicalDefensiveFielderResolution:
    """Selected defensive position plus fail-closed identity evidence."""

    team_side: str
    position: CanonicalDefensivePosition
    player_id: Optional[str]
    selection_seed: int
    blockers: Tuple[str, ...] = ()
    authoritative: bool = False
    schema_version: str = (
        CANONICAL_DEFENSIVE_FIELDER_RESOLUTION_VERSION
    )

    def __post_init__(self) -> None:
        if self.team_side not in {"away", "home"}:
            raise ValueError(
                "team_side must be away or home"
            )

        if not isinstance(
            self.position,
            CanonicalDefensivePosition,
        ):
            raise TypeError(
                "position must be canonical"
            )

        if (
            not isinstance(self.selection_seed, int)
            or isinstance(self.selection_seed, bool)
            or self.selection_seed < 0
        ):
            raise ValueError(
                "selection_seed must be a non-negative integer"
            )

        object.__setattr__(
            self,
            "player_id",
            _normalize_player_id(self.player_id),
        )

        if self.player_id is None and not self.blockers:
            raise ValueError(
                "missing fielder identity requires blockers"
            )

        if self.player_id is not None and self.blockers:
            raise ValueError(
                "resolved fielder cannot contain blockers"
            )

        if self.authoritative is not False:
            raise ValueError(
                "fielder resolution is not event authority"
            )

        if self.schema_version != (
            CANONICAL_DEFENSIVE_FIELDER_RESOLUTION_VERSION
        ):
            raise ValueError(
                "unsupported fielder resolution version"
            )

    @property
    def ready(self) -> bool:
        return self.player_id is not None and not self.blockers

    def to_diagnostics(self) -> Dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "status": "ready" if self.ready else "blocked",
            "team_side": self.team_side,
            "position": self.position.value,
            "player_id": self.player_id,
            "selection_seed": self.selection_seed,
            "blockers": list(self.blockers),
            "authoritative": self.authoritative,
        }


def resolve_canonical_defensive_fielder(
    *,
    opportunity: CanonicalDefensiveOpportunity,
    team_side: str,
    alignment: Optional[CanonicalDefensiveAlignment],
    selection_seed: int,
) -> CanonicalDefensiveFielderResolution:
    """Resolve one supported fielder identity for an opportunity."""

    if not isinstance(
        opportunity,
        CanonicalDefensiveOpportunity,
    ):
        raise TypeError(
            "opportunity must be a "
            "CanonicalDefensiveOpportunity"
        )

    if team_side not in {"away", "home"}:
        raise ValueError(
            "team_side must be away or home"
        )

    if (
        not isinstance(selection_seed, int)
        or isinstance(selection_seed, bool)
        or selection_seed < 0
    ):
        raise ValueError(
            "selection_seed must be a non-negative integer"
        )

    candidates = _COVERAGE_POSITION_CANDIDATES[
        opportunity.coverage_unit
    ]
    position = candidates[
        random.Random(selection_seed).randrange(
            len(candidates)
        )
    ]

    if alignment is None:
        return CanonicalDefensiveFielderResolution(
            team_side=team_side,
            position=position,
            player_id=None,
            selection_seed=selection_seed,
            blockers=(
                "defensive_alignment_unavailable",
            ),
        )

    if not isinstance(
        alignment,
        CanonicalDefensiveAlignment,
    ):
        raise TypeError(
            "alignment must be a "
            "CanonicalDefensiveAlignment"
        )

    if alignment.team_side != team_side:
        raise ValueError(
            "alignment team_side must match fielding side"
        )

    fielder = alignment.fielder_for(position)

    if fielder.player_id is None:
        return CanonicalDefensiveFielderResolution(
            team_side=team_side,
            position=position,
            player_id=None,
            selection_seed=selection_seed,
            blockers=(
                "defensive_fielder_identity_unavailable",
            ),
        )

    return CanonicalDefensiveFielderResolution(
        team_side=team_side,
        position=position,
        player_id=fielder.player_id,
        selection_seed=selection_seed,
    )

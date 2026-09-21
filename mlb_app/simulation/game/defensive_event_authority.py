"""Aggregate canonical defensive event-authority observations."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Iterable, Tuple

from .defensive_event_rematerialization import (
    CanonicalDefensiveEventRematerialization,
)


CANONICAL_DEFENSIVE_EVENT_AUTHORITY_VERSION = (
    "canonical_defensive_event_authority_v1"
)


@dataclass(frozen=True)
class CanonicalDefensiveEventAuthorityRecord:
    """Compact trial-owned record for one batted-ball resolution."""

    applied: bool
    authoritative: bool
    original_event_type: str
    final_event_type: str
    blocker: str | None
    schema_version: str = (
        CANONICAL_DEFENSIVE_EVENT_AUTHORITY_VERSION
    )

    def __post_init__(self) -> None:
        if not self.original_event_type:
            raise ValueError(
                "original_event_type is required"
            )
        if not self.final_event_type:
            raise ValueError(
                "final_event_type is required"
            )
        if self.applied != self.authoritative:
            raise ValueError(
                "applied must match authoritative"
            )
        if self.applied and self.blocker is not None:
            raise ValueError(
                "applied authority cannot have a blocker"
            )
        if not self.applied and not self.blocker:
            raise ValueError(
                "preserved authority requires a blocker"
            )
        if self.schema_version != (
            CANONICAL_DEFENSIVE_EVENT_AUTHORITY_VERSION
        ):
            raise ValueError(
                "unsupported defensive event authority version"
            )

    @classmethod
    def from_rematerialization(
        cls,
        value: CanonicalDefensiveEventRematerialization,
    ) -> "CanonicalDefensiveEventAuthorityRecord":
        if not isinstance(
            value,
            CanonicalDefensiveEventRematerialization,
        ):
            raise TypeError(
                "value must be a "
                "CanonicalDefensiveEventRematerialization"
            )

        return cls(
            applied=value.applied,
            authoritative=value.authoritative,
            original_event_type=(
                value.original_event.event_type
            ),
            final_event_type=value.event.event_type,
            blocker=value.blocker,
        )

    def to_diagnostics(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "applied": self.applied,
            "authoritative": self.authoritative,
            "original_event_type": self.original_event_type,
            "final_event_type": self.final_event_type,
            "blocker": self.blocker,
        }


@dataclass(frozen=True)
class CanonicalDefensiveEventAuthoritySummary:
    """Batch-level observed defensive authority frequencies."""

    observation_count: int
    applied_count: int
    preserved_count: int
    authority_rate: float
    final_event_type_counts: Tuple[
        Tuple[str, int],
        ...,
    ] = ()
    blocker_counts: Tuple[
        Tuple[str, int],
        ...,
    ] = ()
    schema_version: str = (
        CANONICAL_DEFENSIVE_EVENT_AUTHORITY_VERSION
    )

    def __post_init__(self) -> None:
        if self.observation_count < 0:
            raise ValueError(
                "observation_count cannot be negative"
            )
        if self.applied_count < 0:
            raise ValueError(
                "applied_count cannot be negative"
            )
        if self.preserved_count < 0:
            raise ValueError(
                "preserved_count cannot be negative"
            )
        if (
            self.applied_count + self.preserved_count
            != self.observation_count
        ):
            raise ValueError(
                "authority counts must reconcile"
            )
        if not 0.0 <= self.authority_rate <= 1.0:
            raise ValueError(
                "authority_rate must be between zero and one"
            )
        if (
            self.observation_count == 0
            and self.authority_rate != 0.0
        ):
            raise ValueError(
                "empty authority summary requires zero rate"
            )
        if self.schema_version != (
            CANONICAL_DEFENSIVE_EVENT_AUTHORITY_VERSION
        ):
            raise ValueError(
                "unsupported defensive event authority version"
            )

        _validate_counts(
            self.final_event_type_counts,
            "final_event_type_counts",
        )
        _validate_counts(
            self.blocker_counts,
            "blocker_counts",
        )

    @classmethod
    def empty(
        cls,
    ) -> "CanonicalDefensiveEventAuthoritySummary":
        return cls(
            observation_count=0,
            applied_count=0,
            preserved_count=0,
            authority_rate=0.0,
        )

    def to_diagnostics(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "observation_count": self.observation_count,
            "applied_count": self.applied_count,
            "preserved_count": self.preserved_count,
            "authority_rate": self.authority_rate,
            "final_event_type_counts": dict(
                self.final_event_type_counts
            ),
            "blocker_counts": dict(
                self.blocker_counts
            ),
        }


def aggregate_canonical_defensive_event_authority(
    records: Iterable[
        CanonicalDefensiveEventAuthorityRecord
    ],
) -> CanonicalDefensiveEventAuthoritySummary:
    """Aggregate exact observed counts from completed trials."""

    values = tuple(records)

    if any(
        not isinstance(
            value,
            CanonicalDefensiveEventAuthorityRecord,
        )
        for value in values
    ):
        raise TypeError(
            "records must contain "
            "CanonicalDefensiveEventAuthorityRecord values"
        )

    if not values:
        return (
            CanonicalDefensiveEventAuthoritySummary.empty()
        )

    applied_count = sum(
        value.applied for value in values
    )
    final_event_counts = Counter(
        value.final_event_type for value in values
    )
    blocker_counts = Counter(
        value.blocker
        for value in values
        if value.blocker is not None
    )

    return CanonicalDefensiveEventAuthoritySummary(
        observation_count=len(values),
        applied_count=applied_count,
        preserved_count=len(values) - applied_count,
        authority_rate=round(
            applied_count / len(values),
            6,
        ),
        final_event_type_counts=tuple(
            sorted(final_event_counts.items())
        ),
        blocker_counts=tuple(
            sorted(blocker_counts.items())
        ),
    )


def _validate_counts(
    values: Tuple[Tuple[str, int], ...],
    name: str,
) -> None:
    keys = tuple(key for key, _ in values)

    if keys != tuple(sorted(keys)):
        raise ValueError(f"{name} must be sorted")
    if len(keys) != len(set(keys)):
        raise ValueError(f"{name} keys must be unique")
    if any(
        not key or count <= 0
        for key, count in values
    ):
        raise ValueError(
            f"{name} requires non-empty keys "
            "and positive counts"
        )

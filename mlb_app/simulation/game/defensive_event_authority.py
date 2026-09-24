"""Aggregate canonical defensive event-authority observations."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Iterable, Tuple

from .defensive_event_rematerialization import (
    CanonicalDefensiveEventRematerialization,
)


CANONICAL_DEFENSIVE_EVENT_AUTHORITY_VERSION = (
    "canonical_defensive_event_authority_v2"
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
    original_event_type_counts: Tuple[
        Tuple[str, int],
        ...,
    ] = ()
    applied_original_event_type_counts: Tuple[
        Tuple[str, int],
        ...,
    ] = ()
    preserved_original_event_type_counts: Tuple[
        Tuple[str, int],
        ...,
    ] = ()
    authority_rate_by_original_event_type: Tuple[
        Tuple[str, float],
        ...,
    ] = ()
    event_transition_counts: Tuple[
        Tuple[str, str, int],
        ...,
    ] = ()
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
            self.original_event_type_counts,
            "original_event_type_counts",
        )
        _validate_counts(
            self.applied_original_event_type_counts,
            "applied_original_event_type_counts",
        )
        _validate_counts(
            self.preserved_original_event_type_counts,
            "preserved_original_event_type_counts",
        )
        _validate_authority_rates(
            self.authority_rate_by_original_event_type,
        )
        _validate_transition_counts(
            self.event_transition_counts,
        )
        _validate_counts(
            self.final_event_type_counts,
            "final_event_type_counts",
        )
        _validate_counts(
            self.blocker_counts,
            "blocker_counts",
        )

        original_counts = dict(
            self.original_event_type_counts
        )
        applied_original_counts = dict(
            self.applied_original_event_type_counts
        )
        preserved_original_counts = dict(
            self.preserved_original_event_type_counts
        )
        authority_rates = dict(
            self.authority_rate_by_original_event_type
        )

        if sum(original_counts.values()) != (
            self.observation_count
        ):
            raise ValueError(
                "original event counts must reconcile"
            )
        if sum(
            count
            for _, _, count in self.event_transition_counts
        ) != self.observation_count:
            raise ValueError(
                "transition counts must reconcile"
            )
        if sum(
            count
            for _, count in self.final_event_type_counts
        ) != self.observation_count:
            raise ValueError(
                "final event counts must reconcile"
            )
        if sum(applied_original_counts.values()) != (
            self.applied_count
        ):
            raise ValueError(
                "applied original counts must reconcile"
            )
        if sum(preserved_original_counts.values()) != (
            self.preserved_count
        ):
            raise ValueError(
                "preserved original counts must reconcile"
            )
        if sum(
            count
            for _, count in self.blocker_counts
        ) != self.preserved_count:
            raise ValueError(
                "blocker counts must reconcile"
            )

        if set(authority_rates) != set(original_counts):
            raise ValueError(
                "authority-rate keys must match "
                "original event keys"
            )

        for event_type, count in original_counts.items():
            applied = applied_original_counts.get(
                event_type,
                0,
            )
            preserved = preserved_original_counts.get(
                event_type,
                0,
            )
            if applied + preserved != count:
                raise ValueError(
                    "per-event authority counts "
                    "must reconcile"
                )
            expected_rate = round(
                applied / count,
                6,
            )
            if authority_rates[event_type] != expected_rate:
                raise ValueError(
                    "per-event authority rate "
                    "must reconcile"
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
            "original_event_type_counts": dict(
                self.original_event_type_counts
            ),
            "applied_original_event_type_counts": dict(
                self.applied_original_event_type_counts
            ),
            "preserved_original_event_type_counts": dict(
                self.preserved_original_event_type_counts
            ),
            "authority_rate_by_original_event_type": dict(
                self.authority_rate_by_original_event_type
            ),
            "event_transition_counts": (
                _transition_diagnostics(
                    self.event_transition_counts
                )
            ),
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
    original_event_counts = Counter(
        value.original_event_type for value in values
    )
    applied_original_event_counts = Counter(
        value.original_event_type
        for value in values
        if value.applied
    )
    preserved_original_event_counts = Counter(
        value.original_event_type
        for value in values
        if not value.applied
    )
    transition_counts = Counter(
        (
            value.original_event_type,
            value.final_event_type,
        )
        for value in values
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
        original_event_type_counts=tuple(
            sorted(original_event_counts.items())
        ),
        applied_original_event_type_counts=tuple(
            sorted(
                applied_original_event_counts.items()
            )
        ),
        preserved_original_event_type_counts=tuple(
            sorted(
                preserved_original_event_counts.items()
            )
        ),
        authority_rate_by_original_event_type=tuple(
            (
                event_type,
                round(
                    applied_original_event_counts.get(
                        event_type,
                        0,
                    )
                    / count,
                    6,
                ),
            )
            for event_type, count in sorted(
                original_event_counts.items()
            )
        ),
        event_transition_counts=tuple(
            (
                original_event_type,
                final_event_type,
                count,
            )
            for (
                original_event_type,
                final_event_type,
            ), count in sorted(
                transition_counts.items()
            )
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


def _validate_authority_rates(
    values: Tuple[Tuple[str, float], ...],
) -> None:
    keys = tuple(key for key, _ in values)

    if keys != tuple(sorted(keys)):
        raise ValueError(
            "authority rates must be sorted"
        )
    if len(keys) != len(set(keys)):
        raise ValueError(
            "authority-rate keys must be unique"
        )
    if any(
        not key or not 0.0 <= rate <= 1.0
        for key, rate in values
    ):
        raise ValueError(
            "authority rates require non-empty keys "
            "and bounded rates"
        )


def _validate_transition_counts(
    values: Tuple[Tuple[str, str, int], ...],
) -> None:
    keys = tuple(
        (original, final)
        for original, final, _ in values
    )

    if keys != tuple(sorted(keys)):
        raise ValueError(
            "transition counts must be sorted"
        )
    if len(keys) != len(set(keys)):
        raise ValueError(
            "transition keys must be unique"
        )
    if any(
        not original
        or not final
        or count <= 0
        for original, final, count in values
    ):
        raise ValueError(
            "transition counts require non-empty "
            "event types and positive counts"
        )


def _transition_diagnostics(
    values: Tuple[Tuple[str, str, int], ...],
) -> dict[str, dict[str, int]]:
    result: dict[str, dict[str, int]] = {}

    for original, final, count in values:
        result.setdefault(original, {})[final] = count

    return result

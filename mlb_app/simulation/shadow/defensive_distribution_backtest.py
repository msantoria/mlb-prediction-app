"""Backtest canonical defensive event distributions."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Tuple

from ..game.defensive_event_authority import (
    CanonicalDefensiveEventAuthoritySummary,
)


CANONICAL_OBSERVED_DEFENSIVE_DISTRIBUTION_VERSION = (
    "canonical_observed_defensive_distribution_v1"
)
CANONICAL_DEFENSIVE_DISTRIBUTION_BACKTEST_VERSION = (
    "canonical_defensive_distribution_backtest_v1"
)


CountPairs = Tuple[Tuple[str, int], ...]
RatePairs = Tuple[Tuple[str, float], ...]
TransitionRates = Tuple[Tuple[str, str, float], ...]


def _validate_counts(
    values: CountPairs,
    *,
    field_name: str,
    expected_total: int,
) -> None:
    keys = tuple(key for key, _ in values)

    if keys != tuple(sorted(keys)):
        raise ValueError(f"{field_name} must be sorted")
    if len(keys) != len(set(keys)):
        raise ValueError(f"{field_name} keys must be unique")
    if any(
        not key or count <= 0
        for key, count in values
    ):
        raise ValueError(
            f"{field_name} requires non-empty keys "
            "and positive counts"
        )
    if sum(count for _, count in values) != expected_total:
        raise ValueError(
            f"{field_name} must reconcile with "
            "observation_count"
        )


@dataclass(frozen=True)
class CanonicalObservedDefensiveDistribution:
    """Immutable externally supplied observed outcome counts."""

    source_identifier: str
    observation_count: int
    final_event_type_counts: CountPairs
    schema_version: str = (
        CANONICAL_OBSERVED_DEFENSIVE_DISTRIBUTION_VERSION
    )

    def __post_init__(self) -> None:
        if not self.source_identifier.strip():
            raise ValueError(
                "source_identifier is required"
            )
        if self.observation_count <= 0:
            raise ValueError(
                "observation_count must be positive"
            )
        if self.schema_version != (
            CANONICAL_OBSERVED_DEFENSIVE_DISTRIBUTION_VERSION
        ):
            raise ValueError(
                "unsupported observed defensive "
                "distribution version"
            )

        _validate_counts(
            self.final_event_type_counts,
            field_name="final_event_type_counts",
            expected_total=self.observation_count,
        )

    def to_diagnostics(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "source_identifier": self.source_identifier,
            "observation_count": self.observation_count,
            "final_event_type_counts": dict(
                self.final_event_type_counts
            ),
        }


@dataclass(frozen=True)
class CanonicalDefensiveDistributionBacktest:
    """Measurement-only comparison against observed outcomes."""

    status: str
    source_identifier: str
    simulation_observation_count: int
    observed_observation_count: int
    simulated_final_event_type_rates: RatePairs = ()
    observed_final_event_type_rates: RatePairs = ()
    final_event_type_rate_deltas: RatePairs = ()
    total_variation_distance: float = 0.0
    maximum_absolute_rate_delta: float = 0.0
    authority_rate: float = 0.0
    event_transition_rates: TransitionRates = ()
    blocker_counts: CountPairs = ()
    input_digest: str = ""
    blocker: str | None = None
    schema_version: str = (
        CANONICAL_DEFENSIVE_DISTRIBUTION_BACKTEST_VERSION
    )

    def __post_init__(self) -> None:
        if self.status not in {"ready", "unavailable"}:
            raise ValueError(
                "unsupported defensive distribution "
                "backtest status"
            )
        if not self.source_identifier.strip():
            raise ValueError(
                "source_identifier is required"
            )
        if self.schema_version != (
            CANONICAL_DEFENSIVE_DISTRIBUTION_BACKTEST_VERSION
        ):
            raise ValueError(
                "unsupported defensive distribution "
                "backtest version"
            )
        if self.simulation_observation_count < 0:
            raise ValueError(
                "simulation_observation_count cannot "
                "be negative"
            )
        if self.observed_observation_count <= 0:
            raise ValueError(
                "observed_observation_count must be positive"
            )
        if not (
            0.0 <= self.total_variation_distance <= 1.0
        ):
            raise ValueError(
                "total_variation_distance must be bounded"
            )
        if not (
            0.0 <= self.maximum_absolute_rate_delta <= 1.0
        ):
            raise ValueError(
                "maximum_absolute_rate_delta must be bounded"
            )
        if not 0.0 <= self.authority_rate <= 1.0:
            raise ValueError(
                "authority_rate must be bounded"
            )

        if self.status == "ready":
            if self.simulation_observation_count == 0:
                raise ValueError(
                    "ready backtest requires simulations"
                )
            if self.blocker is not None:
                raise ValueError(
                    "ready backtest cannot have a blocker"
                )
            if not self.input_digest:
                raise ValueError(
                    "ready backtest requires input_digest"
                )
        elif not self.blocker:
            raise ValueError(
                "unavailable backtest requires a blocker"
            )

    @property
    def ready(self) -> bool:
        return self.status == "ready"

    def to_diagnostics(self) -> dict[str, object]:
        transition_rates: dict[
            str,
            dict[str, float],
        ] = {}
        for original, final, rate in (
            self.event_transition_rates
        ):
            transition_rates.setdefault(
                original,
                {},
            )[final] = rate

        return {
            "schema_version": self.schema_version,
            "status": self.status,
            "ready": self.ready,
            "source_identifier": self.source_identifier,
            "simulation_observation_count": (
                self.simulation_observation_count
            ),
            "observed_observation_count": (
                self.observed_observation_count
            ),
            "simulated_final_event_type_rates": dict(
                self.simulated_final_event_type_rates
            ),
            "observed_final_event_type_rates": dict(
                self.observed_final_event_type_rates
            ),
            "final_event_type_rate_deltas": dict(
                self.final_event_type_rate_deltas
            ),
            "total_variation_distance": (
                self.total_variation_distance
            ),
            "maximum_absolute_rate_delta": (
                self.maximum_absolute_rate_delta
            ),
            "authority_rate": self.authority_rate,
            "event_transition_rates": transition_rates,
            "blocker_counts": dict(self.blocker_counts),
            "input_digest": self.input_digest,
            "blocker": self.blocker,
            "measurement_only": True,
            "activation_permitted": False,
            "production_authority_changed": False,
        }


def _rate_pairs(
    counts: dict[str, int],
    *,
    denominator: int,
    event_types: tuple[str, ...],
) -> RatePairs:
    return tuple(
        (
            event_type,
            round(
                counts.get(event_type, 0) / denominator,
                6,
            ),
        )
        for event_type in event_types
    )


def _transition_rates(
    summary: CanonicalDefensiveEventAuthoritySummary,
) -> TransitionRates:
    original_counts = dict(
        summary.original_event_type_counts
    )

    return tuple(
        (
            original,
            final,
            round(
                count / original_counts[original],
                6,
            ),
        )
        for original, final, count in (
            summary.event_transition_counts
        )
    )


def _input_digest(
    *,
    summary: CanonicalDefensiveEventAuthoritySummary,
    observed: CanonicalObservedDefensiveDistribution,
) -> str:
    payload = {
        "simulation": summary.to_diagnostics(),
        "observed": observed.to_diagnostics(),
    }
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def backtest_canonical_defensive_distribution(
    *,
    summary: CanonicalDefensiveEventAuthoritySummary,
    observed: CanonicalObservedDefensiveDistribution,
) -> CanonicalDefensiveDistributionBacktest:
    """Compare canonical final outcomes without activation."""

    if not isinstance(
        summary,
        CanonicalDefensiveEventAuthoritySummary,
    ):
        raise TypeError(
            "summary must be a "
            "CanonicalDefensiveEventAuthoritySummary"
        )
    if not isinstance(
        observed,
        CanonicalObservedDefensiveDistribution,
    ):
        raise TypeError(
            "observed must be a "
            "CanonicalObservedDefensiveDistribution"
        )

    if summary.observation_count == 0:
        return CanonicalDefensiveDistributionBacktest(
            status="unavailable",
            source_identifier=observed.source_identifier,
            simulation_observation_count=0,
            observed_observation_count=(
                observed.observation_count
            ),
            authority_rate=summary.authority_rate,
            blocker_counts=summary.blocker_counts,
            blocker="simulation_distribution_empty",
        )

    simulated_counts = dict(
        summary.final_event_type_counts
    )
    observed_counts = dict(
        observed.final_event_type_counts
    )
    event_types = tuple(
        sorted(
            set(simulated_counts)
            | set(observed_counts)
        )
    )

    simulated_rates = _rate_pairs(
        simulated_counts,
        denominator=summary.observation_count,
        event_types=event_types,
    )
    observed_rates = _rate_pairs(
        observed_counts,
        denominator=observed.observation_count,
        event_types=event_types,
    )

    simulated_rate_map = dict(simulated_rates)
    observed_rate_map = dict(observed_rates)
    exact_deltas = tuple(
        (
            simulated_counts.get(event_type, 0)
            / summary.observation_count
        )
        - (
            observed_counts.get(event_type, 0)
            / observed.observation_count
        )
        for event_type in event_types
    )
    deltas = tuple(
        (
            event_type,
            round(delta, 6),
        )
        for event_type, delta in zip(
            event_types,
            exact_deltas,
        )
    )
    absolute_deltas = tuple(
        abs(delta)
        for delta in exact_deltas
    )

    return CanonicalDefensiveDistributionBacktest(
        status="ready",
        source_identifier=observed.source_identifier,
        simulation_observation_count=(
            summary.observation_count
        ),
        observed_observation_count=(
            observed.observation_count
        ),
        simulated_final_event_type_rates=(
            simulated_rates
        ),
        observed_final_event_type_rates=observed_rates,
        final_event_type_rate_deltas=deltas,
        total_variation_distance=round(
            sum(absolute_deltas) / 2.0,
            6,
        ),
        maximum_absolute_rate_delta=round(
            max(absolute_deltas),
            6,
        ),
        authority_rate=summary.authority_rate,
        event_transition_rates=_transition_rates(summary),
        blocker_counts=summary.blocker_counts,
        input_digest=_input_digest(
            summary=summary,
            observed=observed,
        ),
    )

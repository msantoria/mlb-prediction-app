"""Versioned canonical production trial-count policy."""

from __future__ import annotations

from dataclasses import dataclass
import os
from typing import Any, Dict


CANONICAL_PRODUCTION_TRIAL_POLICY_VERSION = (
    "canonical_production_trial_policy_v2"
)
CANONICAL_PRODUCTION_SIMULATION_COUNT_ENV = (
    "MLB_CANONICAL_PRODUCTION_SIMULATION_COUNT"
)
DEFAULT_CANONICAL_PRODUCTION_SIMULATION_COUNT = 1000
MINIMUM_CANONICAL_PRODUCTION_SIMULATION_COUNT = 25
MAXIMUM_CANONICAL_PRODUCTION_SIMULATION_COUNT = 10000


@dataclass(frozen=True)
class CanonicalProductionTrialPolicy:
    simulation_count: int = (
        DEFAULT_CANONICAL_PRODUCTION_SIMULATION_COUNT
    )
    policy_version: str = (
        CANONICAL_PRODUCTION_TRIAL_POLICY_VERSION
    )

    def __post_init__(self) -> None:
        if (
            not isinstance(self.simulation_count, int)
            or isinstance(self.simulation_count, bool)
            or not (
                MINIMUM_CANONICAL_PRODUCTION_SIMULATION_COUNT
                <= self.simulation_count
                <= MAXIMUM_CANONICAL_PRODUCTION_SIMULATION_COUNT
            )
        ):
            raise ValueError(
                "simulation_count must be an integer "
                "between 25 and 10000"
            )

        if self.policy_version != (
            CANONICAL_PRODUCTION_TRIAL_POLICY_VERSION
        ):
            raise ValueError(
                "unsupported canonical production "
                "trial policy version"
            )

    def to_diagnostics(self) -> Dict[str, Any]:
        return {
            "schema_version": self.policy_version,
            "simulation_count": self.simulation_count,
            "environment_variable": (
                CANONICAL_PRODUCTION_SIMULATION_COUNT_ENV
            ),
            "default_simulation_count": (
                DEFAULT_CANONICAL_PRODUCTION_SIMULATION_COUNT
            ),
            "minimum_simulation_count": (
                MINIMUM_CANONICAL_PRODUCTION_SIMULATION_COUNT
            ),
            "maximum_simulation_count": (
                MAXIMUM_CANONICAL_PRODUCTION_SIMULATION_COUNT
            ),
            "configured_from_environment": (
                CANONICAL_PRODUCTION_SIMULATION_COUNT_ENV
                in os.environ
            ),
        }


def build_canonical_production_trial_policy(
    value: Any = None,
) -> CanonicalProductionTrialPolicy:
    raw_value = (
        value
        if value is not None
        else os.getenv(
            CANONICAL_PRODUCTION_SIMULATION_COUNT_ENV,
            str(
                DEFAULT_CANONICAL_PRODUCTION_SIMULATION_COUNT
            ),
        )
    )

    if isinstance(raw_value, bool):
        raise ValueError(
            "production simulation count must be an integer"
        )

    try:
        simulation_count = int(raw_value)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            "production simulation count must be an integer"
        ) from exc

    if str(simulation_count) != str(raw_value).strip():
        raise ValueError(
            "production simulation count must be an integer"
        )

    return CanonicalProductionTrialPolicy(
        simulation_count=simulation_count,
    )

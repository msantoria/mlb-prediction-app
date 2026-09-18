"""Immutable canonical projection payload contracts."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Tuple


CANONICAL_PROJECTION_SCHEMA_VERSION = (
    "canonical_projection_payload_v1"
)


@dataclass(frozen=True)
class StatisticalSummary:
    """Stable distribution summary for one projected metric."""

    count: int
    mean: float
    median: float
    p10: float
    p25: float
    p75: float
    p90: float
    minimum: float
    maximum: float
    sd: float | None = None
    p0: float | None = None
    p1_plus: float | None = None
    p2_plus: float | None = None
    p3_plus: float | None = None
    p4_plus: float | None = None
    p5_plus: float | None = None
    p6_plus: float | None = None

    def __post_init__(self) -> None:
        if self.count <= 0:
            raise ValueError("summary count must be positive")
        if self.minimum > self.maximum:
            raise ValueError(
                "summary minimum cannot exceed maximum"
            )


@dataclass(frozen=True)
class MetricProjection:
    """One named projected metric."""

    name: str
    summary: StatisticalSummary

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("metric name is required")


@dataclass(frozen=True)
class TeamProjection:
    """Canonical projection for one team side."""

    team_side: str
    metrics: Tuple[MetricProjection, ...]

    def __post_init__(self) -> None:
        if self.team_side not in {"away", "home"}:
            raise ValueError(
                "team_side must be 'away' or 'home'"
            )
        _validate_metric_order(self.metrics)


@dataclass(frozen=True)
class PlayerProjection:
    """Canonical batter or pitcher projection."""

    player_id: str
    team_side: str
    metrics: Tuple[MetricProjection, ...]

    def __post_init__(self) -> None:
        if not self.player_id:
            raise ValueError("player_id is required")
        if self.team_side not in {"away", "home"}:
            raise ValueError(
                "team_side must be 'away' or 'home'"
            )
        _validate_metric_order(self.metrics)


@dataclass(frozen=True)
class ProjectionDiagnostics:
    """Aggregate quality diagnostics for canonical runs."""

    pitcher_attribution_complete_rate: float
    replay_validation_pass_rate: float
    earned_run_status: str
    warnings: Tuple[str, ...] = field(
        default_factory=tuple
    )

    def __post_init__(self) -> None:
        for name, value in (
            (
                "pitcher_attribution_complete_rate",
                self.pitcher_attribution_complete_rate,
            ),
            (
                "replay_validation_pass_rate",
                self.replay_validation_pass_rate,
            ),
        ):
            if not 0.0 <= value <= 1.0:
                raise ValueError(
                    f"{name} must be between 0 and 1"
                )

        if self.earned_run_status not in {
            "not_reconstructed",
            "partially_reconstructed",
            "reconstructed",
        }:
            raise ValueError(
                "invalid earned_run_status"
            )


@dataclass(frozen=True)
class CanonicalProjectionPayload:
    """Versioned projection payload from canonical simulations."""

    run_id: str
    model_version: str
    simulation_count: int
    teams: Tuple[TeamProjection, ...]
    batters: Tuple[PlayerProjection, ...]
    pitchers: Tuple[PlayerProjection, ...]
    diagnostics: ProjectionDiagnostics
    schema_version: str = (
        CANONICAL_PROJECTION_SCHEMA_VERSION
    )

    def __post_init__(self) -> None:
        if not self.run_id:
            raise ValueError("run_id is required")
        if not self.model_version:
            raise ValueError("model_version is required")
        if self.simulation_count <= 0:
            raise ValueError(
                "simulation_count must be positive"
            )
        if self.schema_version != (
            CANONICAL_PROJECTION_SCHEMA_VERSION
        ):
            raise ValueError(
                "unsupported canonical projection schema"
            )

        if tuple(
            team.team_side for team in self.teams
        ) != ("away", "home"):
            raise ValueError(
                "teams must be ordered away then home"
            )

        batter_keys = tuple(
            (player.team_side, player.player_id)
            for player in self.batters
        )
        if batter_keys != tuple(sorted(batter_keys)):
            raise ValueError(
                "batters must use deterministic ordering"
            )

        pitcher_keys = tuple(
            (player.team_side, player.player_id)
            for player in self.pitchers
        )
        if pitcher_keys != tuple(sorted(pitcher_keys)):
            raise ValueError(
                "pitchers must use deterministic ordering"
            )


def _validate_metric_order(
    metrics: Tuple[MetricProjection, ...],
) -> None:
    names = tuple(metric.name for metric in metrics)

    if not names:
        raise ValueError(
            "at least one projected metric is required"
        )

    if len(names) != len(set(names)):
        raise ValueError(
            "projected metric names must be unique"
        )

    if names != tuple(sorted(names)):
        raise ValueError(
            "projected metrics must be ordered by name"
        )

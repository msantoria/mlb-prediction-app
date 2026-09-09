"""Canonical full-game orchestration contracts."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from enum import Enum
from typing import Tuple

from .defensive_alignment import (
    CanonicalDefensiveAlignment,
)

from mlb_app.simulation.events import (
    GameState,
    PlayEvent,
    PlayLedger,
)


class GameCompletionReason(str, Enum):
    """Reason canonical game orchestration stopped."""

    REGULATION = "regulation"
    HOME_LEAD_AFTER_TOP = "home_lead_after_top"
    WALK_OFF = "walk_off"
    EXTRA_INNINGS = "extra_innings"
    EXTRA_INNINGS_CAP_TIE = "extra_innings_cap_tie"


@dataclass(frozen=True)
class CanonicalGameConfig:
    """Rules and safety limits for one canonical game."""

    regulation_innings: int = 9
    max_extra_innings: int = 6
    automatic_runner_enabled: bool = True
    max_plate_appearances_per_half: int = 100

    def __post_init__(self) -> None:
        if self.regulation_innings < 1:
            raise ValueError(
                "regulation_innings must be positive"
            )
        if self.max_extra_innings < 0:
            raise ValueError(
                "max_extra_innings cannot be negative"
            )
        if self.max_plate_appearances_per_half < 1:
            raise ValueError(
                "max_plate_appearances_per_half "
                "must be positive"
            )


@dataclass(frozen=True)
class CanonicalLineup:
    """Fixed nine-player batting order for one team."""

    team_side: str
    player_ids: Tuple[str, ...]
    defensive_alignment: CanonicalDefensiveAlignment | None = None

    def __post_init__(self) -> None:
        if self.team_side not in {"away", "home"}:
            raise ValueError(
                "team_side must be 'away' or 'home'"
            )
        if len(self.player_ids) != 9:
            raise ValueError(
                "canonical lineup requires nine players"
            )
        if any(not player_id for player_id in self.player_ids):
            raise ValueError(
                "lineup player identifiers are required"
            )
        if len(set(self.player_ids)) != 9:
            raise ValueError(
                "lineup player identifiers must be unique"
            )

        alignment = self.defensive_alignment

        if alignment is not None:
            if not isinstance(
                alignment,
                CanonicalDefensiveAlignment,
            ):
                raise TypeError(
                    "defensive_alignment must be a "
                    "CanonicalDefensiveAlignment"
                )

            if alignment.team_side != self.team_side:
                raise ValueError(
                    "defensive alignment team_side must "
                    "match canonical lineup"
                )

            if not set(
                alignment.identified_player_ids
            ).issubset(set(self.player_ids)):
                raise ValueError(
                    "defensive fielder identities must "
                    "belong to canonical lineup"
                )

    def batter(self, batting_order_index: int) -> str:
        return self.player_ids[
            batting_order_index % len(self.player_ids)
        ]

    def automatic_runner(
        self,
        batting_order_index: int,
    ) -> str:
        """Return the hitter immediately preceding the leadoff spot."""

        return self.player_ids[
            (batting_order_index - 1)
            % len(self.player_ids)
        ]


@dataclass(frozen=True)
class HalfInningRecord:
    """One canonical half inning with its own valid play ledger."""

    inning: int
    half: str
    initial_state: GameState
    events: Tuple[PlayEvent, ...]
    batting_order_start: int
    batting_order_end: int
    ended_by_walk_off: bool = False
    automatic_runner_id: str | None = None

    def __post_init__(self) -> None:
        if self.inning < 1:
            raise ValueError("inning must be positive")
        if self.half not in {"top", "bottom"}:
            raise ValueError(
                "half must be 'top' or 'bottom'"
            )
        if self.initial_state.inning != self.inning:
            raise ValueError(
                "initial state inning does not match record"
            )
        if self.initial_state.half != self.half:
            raise ValueError(
                "initial state half does not match record"
            )
        if self.initial_state.outs != 0:
            raise ValueError(
                "half inning must begin with zero outs"
            )
        if (
            self.initial_state.batting_order_index
            != self.batting_order_start
        ):
            raise ValueError(
                "batting order start does not match state"
            )

        ledger = self.ledger

        if (
            ledger.current_state.batting_order_index
            != self.batting_order_end
        ):
            raise ValueError(
                "batting order end does not match ledger"
            )

        if self.ended_by_walk_off:
            if self.half != "bottom":
                raise ValueError(
                    "walk-off must occur in bottom half"
                )
            if (
                ledger.current_state.home_score
                <= ledger.current_state.away_score
            ):
                raise ValueError(
                    "walk-off requires home team lead"
                )
        elif ledger.current_state.outs != 3:
            raise ValueError(
                "non-walk-off half inning must end "
                "with three outs"
            )

    @property
    def final_state(self) -> GameState:
        if not self.events:
            return self.initial_state
        return self.events[-1].state_after

    @property
    def ledger(self) -> PlayLedger:
        """
        Return a half-inning-local replay ledger.

        PlayEvent.sequence remains global across the complete game.
        PlayLedger requires local sequences beginning at zero, so temporary
        event copies are normalized only for half-inning replay validation.
        """

        local_events = tuple(
            replace(event, sequence=index)
            for index, event in enumerate(self.events)
        )

        return PlayLedger.from_events(
            self.initial_state,
            local_events,
        )



@dataclass(frozen=True)
class CanonicalGameResult:
    """Complete deterministic result for one canonical game trial."""

    config: CanonicalGameConfig
    away_lineup: CanonicalLineup
    home_lineup: CanonicalLineup
    halves: Tuple[HalfInningRecord, ...]
    final_state: GameState
    completion_reason: GameCompletionReason
    completed: bool = True
    warnings: Tuple[str, ...] = field(
        default_factory=tuple
    )

    def __post_init__(self) -> None:
        if not self.halves:
            raise ValueError(
                "canonical game requires at least one half"
            )
        if self.away_lineup.team_side != "away":
            raise ValueError(
                "away_lineup must use away team side"
            )
        if self.home_lineup.team_side != "home":
            raise ValueError(
                "home_lineup must use home team side"
            )
        if self.final_state != self.halves[-1].final_state:
            raise ValueError(
                "final_state must equal final half state"
            )
        if not self.completed:
            raise ValueError(
                "canonical game result must be completed"
            )

    @property
    def events(self) -> Tuple[PlayEvent, ...]:
        return tuple(
            event
            for half in self.halves
            for event in half.events
        )

    @property
    def away_score(self) -> int:
        return self.final_state.away_score

    @property
    def home_score(self) -> int:
        return self.final_state.home_score

    @property
    def total_runs(self) -> int:
        return self.away_score + self.home_score

    @property
    def went_to_extras(self) -> bool:
        return any(
            half.inning
            > self.config.regulation_innings
            for half in self.halves
        )

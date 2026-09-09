"""Apply ready defensive reconciliation to canonical play events."""

from __future__ import annotations

from dataclasses import dataclass, replace
import random

from mlb_app.simulation.events import (
    Base,
    BaselineRunnerAdvancementSampler,
    BattedBallContext,
    ErrorType,
    MultiOutPlayResolver,
    OutRecord,
    PlayEvent,
    RunnerAdvancementResult,
    RunnerMovement,
    build_play_event,
)

from .defensive_outcome_reconciliation import (
    CanonicalDefensiveOutcomeReconciliation,
    CanonicalReconciledBattedBallOutcome,
)


CANONICAL_DEFENSIVE_EVENT_REMATERIALIZATION_VERSION = (
    "canonical_defensive_event_rematerialization_v1"
)

_HIT_OUTCOMES = {
    CanonicalReconciledBattedBallOutcome.SINGLE,
    CanonicalReconciledBattedBallOutcome.DOUBLE,
    CanonicalReconciledBattedBallOutcome.TRIPLE,
}


@dataclass(frozen=True)
class CanonicalDefensiveEventRematerialization:
    """Original and final events plus activation provenance."""

    original_event: PlayEvent
    event: PlayEvent
    advancement: RunnerAdvancementResult
    applied: bool
    authoritative: bool
    blocker: str | None = None
    schema_version: str = (
        CANONICAL_DEFENSIVE_EVENT_REMATERIALIZATION_VERSION
    )

    def __post_init__(self) -> None:
        if not isinstance(self.original_event, PlayEvent):
            raise TypeError(
                "original_event must be a PlayEvent"
            )

        if not isinstance(self.event, PlayEvent):
            raise TypeError("event must be a PlayEvent")

        if not isinstance(
            self.advancement,
            RunnerAdvancementResult,
        ):
            raise TypeError(
                "advancement must be a "
                "RunnerAdvancementResult"
            )

        if self.applied != self.authoritative:
            raise ValueError(
                "applied rematerialization must define authority"
            )

        if self.applied and self.blocker is not None:
            raise ValueError(
                "applied rematerialization cannot be blocked"
            )

        if not self.applied and not self.blocker:
            raise ValueError(
                "unapplied rematerialization requires a blocker"
            )

        if self.event.state_before != self.original_event.state_before:
            raise ValueError(
                "rematerialized event must preserve state_before"
            )

        if self.event.sequence != self.original_event.sequence:
            raise ValueError(
                "rematerialized event must preserve sequence"
            )

        if self.event.batter_id != self.original_event.batter_id:
            raise ValueError(
                "rematerialized event must preserve batter"
            )

        if self.event.pitcher_id != self.original_event.pitcher_id:
            raise ValueError(
                "rematerialized event must preserve pitcher"
            )

    def to_diagnostics(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "status": "applied" if self.applied else "preserved",
            "applied": self.applied,
            "authoritative": self.authoritative,
            "original_event_type": self.original_event.event_type,
            "final_event_type": self.event.event_type,
            "blocker": self.blocker,
        }


def rematerialize_canonical_defensive_event(
    *,
    original_event: PlayEvent,
    original_advancement: RunnerAdvancementResult,
    reconciliation: CanonicalDefensiveOutcomeReconciliation,
    context: BattedBallContext,
    advancement_seed: int,
) -> CanonicalDefensiveEventRematerialization:
    """Rebuild a coherent event when reconciliation is ready."""

    if not reconciliation.ready:
        return _preserved(
            event=original_event,
            advancement=original_advancement,
            blocker="defensive_reconciliation_blocked",
        )

    if not reconciliation.requires_event_rematerialization:
        return _preserved(
            event=original_event,
            advancement=original_advancement,
            blocker="defensive_outcome_unchanged",
        )

    reconciled = reconciliation.reconciled_outcome

    if reconciled is CanonicalReconciledBattedBallOutcome.OUT:
        event = _build_converted_out(original_event)
        advancement = RunnerAdvancementResult(
            movements=event.runner_movements[:-1],
        )
    elif reconciled in _HIT_OUTCOMES:
        advancement = BaselineRunnerAdvancementSampler(
            rng=random.Random(advancement_seed),
        ).sample(
            state=original_event.state_before,
            batter_id=original_event.batter_id,
            primary_outcome=reconciled.value,
            context=context,
        )
        event = build_play_event(
            sequence=original_event.sequence,
            event_type=reconciled.value,
            batter_id=original_event.batter_id,
            state_before=original_event.state_before,
            runner_movements=advancement.movements,
        )
        event = replace(
            event,
            pitcher_id=original_event.pitcher_id,
        )
    elif (
        reconciled
        is CanonicalReconciledBattedBallOutcome.REACHED_ON_ERROR
    ):
        if not reconciliation.error_fielder_id:
            raise ValueError(
                "ready fielding error requires fielder identity"
            )

        event = MultiOutPlayResolver().resolve(
            state=original_event.state_before,
            event_type="reached_on_error",
            batter_id=original_event.batter_id,
            sequence=original_event.sequence,
            error_fielder_id=reconciliation.error_fielder_id,
            error_type=ErrorType.FIELDING,
        )
        event = replace(
            event,
            pitcher_id=original_event.pitcher_id,
        )
        advancement = RunnerAdvancementResult(
            movements=event.runner_movements,
        )
    else:
        raise ValueError(
            "unsupported reconciled defensive outcome"
        )

    return CanonicalDefensiveEventRematerialization(
        original_event=original_event,
        event=event,
        advancement=advancement,
        applied=True,
        authoritative=True,
    )


def _preserved(
    *,
    event: PlayEvent,
    advancement: RunnerAdvancementResult,
    blocker: str,
) -> CanonicalDefensiveEventRematerialization:
    return CanonicalDefensiveEventRematerialization(
        original_event=event,
        event=event,
        advancement=advancement,
        applied=False,
        authoritative=False,
        blocker=blocker,
    )


def _build_converted_out(
    original_event: PlayEvent,
) -> PlayEvent:
    state = original_event.state_before
    movements = []

    for base, runner_id in zip(
        (Base.FIRST, Base.SECOND, Base.THIRD),
        state.bases,
    ):
        if runner_id is not None:
            movements.append(
                RunnerMovement(
                    runner_id=runner_id,
                    start_base=base,
                    end_base=base,
                )
            )

    movements.append(
        RunnerMovement(
            runner_id=original_event.batter_id,
            start_base=Base.HOME,
            end_base=None,
            is_out=True,
        )
    )

    event = build_play_event(
        sequence=original_event.sequence,
        event_type="out",
        batter_id=original_event.batter_id,
        state_before=state,
        runner_movements=tuple(movements),
        outs_recorded=(
            OutRecord(
                runner_id=original_event.batter_id,
                out_number=state.outs + 1,
                reason="defensive_converted_out",
            ),
        ),
    )

    return replace(
        event,
        pitcher_id=original_event.pitcher_id,
    )

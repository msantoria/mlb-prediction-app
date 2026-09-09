"""Resolve sampled canonical PA outcomes into coherent play events."""

from __future__ import annotations

from dataclasses import replace
from typing import Tuple

from mlb_app.simulation.events import (
    Base,
    DeterministicPlayResolver,
    OutRecord,
    PlayEvent,
    RunnerMovement,
    build_play_event,
)

from .batted_ball_resolution import (
    resolve_canonical_batted_ball_outcome,
)
from .probability import (
    CanonicalPlateAppearanceOutcome,
    CanonicalSampledPlateAppearance,
)


def resolve_canonical_sampled_plate_appearance(
    sampled: CanonicalSampledPlateAppearance,
) -> PlayEvent:
    """
    Convert one sampled PA category into a canonical play event.

    Supported in this initial boundary:

    - deterministic walks and hit-by-pitches;
    - deterministic home runs;
    - batter outs and strikeouts with existing runners holding;
    - state-aware singles, doubles, and triples.
    """

    if not isinstance(
        sampled,
        CanonicalSampledPlateAppearance,
    ):
        raise TypeError(
            "sampled must be a "
            "CanonicalSampledPlateAppearance"
        )

    query = sampled.query
    state = query.state
    outcome = sampled.outcome

    if state.outs >= 3:
        raise ValueError(
            "cannot resolve a plate appearance with three outs"
        )

    if outcome in {
        CanonicalPlateAppearanceOutcome.WALK,
        CanonicalPlateAppearanceOutcome.HIT_BY_PITCH,
        CanonicalPlateAppearanceOutcome.HOME_RUN,
    }:
        event = DeterministicPlayResolver().resolve(
            state=state,
            event_type=outcome.value,
            batter_id=query.batter_id,
            sequence=query.sequence,
        )

        event = replace(
            event,
            pitcher_id=query.pitcher_id,
        )

        if (
            outcome
            is CanonicalPlateAppearanceOutcome.HOME_RUN
        ):
            return _credit_batter_rbi(event)

        return event

    if outcome in {
        CanonicalPlateAppearanceOutcome.OUT,
        CanonicalPlateAppearanceOutcome.SINGLE,
        CanonicalPlateAppearanceOutcome.DOUBLE,
        CanonicalPlateAppearanceOutcome.TRIPLE,
    }:
        event = resolve_canonical_batted_ball_outcome(
            sampled
        ).event

        if event.event_type in {
            CanonicalPlateAppearanceOutcome.SINGLE.value,
            CanonicalPlateAppearanceOutcome.DOUBLE.value,
            CanonicalPlateAppearanceOutcome.TRIPLE.value,
        }:
            return _credit_batter_rbi(event)

        return event

    if (
        outcome
        is CanonicalPlateAppearanceOutcome.STRIKEOUT
    ):
        return _resolve_batter_out(sampled)

    raise ValueError(
        f"unsupported sampled outcome: {outcome}"
    )


def _credit_batter_rbi(
    event: PlayEvent,
) -> PlayEvent:
    """Credit the batter for runs produced by an ordinary hit."""

    run_count = len(event.runs_scored)

    if run_count == 0:
        return event

    return replace(
        event,
        attribution=replace(
            event.attribution,
            rbi_credited_to=event.batter_id,
            rbi_count=run_count,
        ),
    )


def _resolve_batter_out(
    sampled: CanonicalSampledPlateAppearance,
) -> PlayEvent:
    query = sampled.query
    state = query.state
    outcome = sampled.outcome

    movements = list(
        _stationary_runner_movements(state.bases)
    )

    movements.append(
        RunnerMovement(
            runner_id=query.batter_id,
            start_base=Base.HOME,
            end_base=None,
            is_out=True,
        )
    )

    reason = (
        "strikeout"
        if outcome
        is CanonicalPlateAppearanceOutcome.STRIKEOUT
        else "batted_ball_out"
    )

    event = build_play_event(
        sequence=query.sequence,
        event_type=outcome.value,
        batter_id=query.batter_id,
        state_before=state,
        runner_movements=tuple(movements),
        outs_recorded=(
            OutRecord(
                runner_id=query.batter_id,
                out_number=state.outs + 1,
                reason=reason,
            ),
        ),
    )

    return replace(
        event,
        pitcher_id=query.pitcher_id,
    )


def _stationary_runner_movements(
    bases: Tuple[
        str | None,
        str | None,
        str | None,
    ],
) -> Tuple[RunnerMovement, ...]:
    movements = []

    for base, runner_id in zip(
        (
            Base.FIRST,
            Base.SECOND,
            Base.THIRD,
        ),
        bases,
    ):
        if runner_id is None:
            continue

        movements.append(
            RunnerMovement(
                runner_id=runner_id,
                start_base=base,
                end_base=base,
            )
        )

    return tuple(movements)

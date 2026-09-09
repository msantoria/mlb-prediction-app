"""Deterministic canonical batted-ball and runner advancement resolution."""

from __future__ import annotations

from dataclasses import dataclass, replace
import hashlib
import random
from typing import Optional, Tuple

from mlb_app.simulation.events import (
    Base,
    BaselineBattedBallContextProvider,
    BaselineRunnerAdvancementSampler,
    BattedBallContext,
    MultiOutPlayResolver,
    OutRecord,
    PlayAttribution,
    PlayEvent,
    RunnerAdvancementResult,
    RunnerMovement,
    SacrificeType,
    build_play_event,
)

from .defensive_opportunity import (
    CanonicalDefensiveOpportunity,
    resolve_canonical_defensive_opportunity,
)
from .factory_input import MAX_CANONICAL_SEED
from .probability import (
    CanonicalPlateAppearanceOutcome,
    CanonicalSampledPlateAppearance,
)


CANONICAL_BATTED_BALL_RESOLUTION_VERSION = (
    "canonical_batted_ball_resolution_v3"
)

BASELINE_GROUND_BALL_DOUBLE_PLAY_PROBABILITY = 0.55

BASELINE_FLY_TAG_RATES = {
    Base.THIRD: {
        "attempt_probability": 0.65,
        "success_probability": 0.92,
        "destination": Base.HOME,
    },
    Base.SECOND: {
        "attempt_probability": 0.22,
        "success_probability": 0.94,
        "destination": Base.THIRD,
    },
    Base.FIRST: {
        "attempt_probability": 0.06,
        "success_probability": 0.90,
        "destination": Base.SECOND,
    },
}

CANONICAL_OUT_SUBTYPES: Tuple[str, ...] = (
    "groundout",
    "flyout",
    "lineout_popout",
    "other_out",
)

SUPPORTED_BATTED_BALL_ADVANCEMENT_OUTCOMES = frozenset(
    {
        CanonicalPlateAppearanceOutcome.OUT,
        CanonicalPlateAppearanceOutcome.SINGLE,
        CanonicalPlateAppearanceOutcome.DOUBLE,
        CanonicalPlateAppearanceOutcome.TRIPLE,
    }
)


@dataclass(frozen=True)
class CanonicalBattedBallResolution:
    """Resolved event plus deterministic batted-ball provenance."""

    sampled: CanonicalSampledPlateAppearance
    event: PlayEvent
    context: BattedBallContext
    defensive_opportunity: CanonicalDefensiveOpportunity
    advancement: RunnerAdvancementResult
    context_seed: int
    defensive_seed: int
    advancement_seed: int
    force_play_seed: Optional[int] = None
    force_play_draw: Optional[float] = None
    tag_attempt_seed: Optional[int] = None
    tag_attempt_draw: Optional[float] = None
    tag_success_seed: Optional[int] = None
    tag_success_draw: Optional[float] = None
    tag_origin_base: Optional[Base] = None
    outcome_subtype: Optional[str] = None
    resolution_version: str = (
        CANONICAL_BATTED_BALL_RESOLUTION_VERSION
    )

    def __post_init__(self) -> None:
        if self.event.state_before != self.sampled.query.state:
            raise ValueError(
                "resolved event must begin from sampled query state"
            )

        if self.event.batter_id != self.sampled.query.batter_id:
            raise ValueError(
                "resolved event batter must match sampled query"
            )

        if self.event.pitcher_id != self.sampled.query.pitcher_id:
            raise ValueError(
                "resolved event pitcher must match sampled query"
            )

        if self.context_seed < 0:
            raise ValueError(
                "context_seed cannot be negative"
            )

        if self.advancement_seed < 0:
            raise ValueError(
                "advancement_seed cannot be negative"
            )

        if (
            self.force_play_seed is not None
            and self.force_play_seed < 0
        ):
            raise ValueError(
                "force_play_seed cannot be negative"
            )

        if (
            self.force_play_draw is not None
            and not 0.0 <= self.force_play_draw < 1.0
        ):
            raise ValueError(
                "force_play_draw must be in [0, 1)"
            )

        if (
            self.force_play_draw is not None
            and self.force_play_seed is None
        ):
            raise ValueError(
                "force_play_draw requires force_play_seed"
            )

        for name, value in (
            ("tag_attempt_draw", self.tag_attempt_draw),
            ("tag_success_draw", self.tag_success_draw),
        ):
            if (
                value is not None
                and not 0.0 <= value < 1.0
            ):
                raise ValueError(
                    f"{name} must be in [0, 1)"
                )

        if (
            self.tag_attempt_draw is not None
            and self.tag_attempt_seed is None
        ):
            raise ValueError(
                "tag_attempt_draw requires tag_attempt_seed"
            )

        if (
            self.tag_success_draw is not None
            and self.tag_success_seed is None
        ):
            raise ValueError(
                "tag_success_draw requires tag_success_seed"
            )

        if (
            self.tag_success_draw is not None
            and self.tag_attempt_draw is None
        ):
            raise ValueError(
                "tag success requires a tag attempt"
            )

        if (
            self.tag_origin_base is not None
            and self.tag_attempt_draw is None
        ):
            raise ValueError(
                "tag_origin_base requires a tag attempt"
            )

        if self.resolution_version != (
            CANONICAL_BATTED_BALL_RESOLUTION_VERSION
        ):
            raise ValueError(
                "unsupported batted-ball resolution version"
            )


def resolve_canonical_batted_ball_outcome(
    sampled: CanonicalSampledPlateAppearance,
) -> CanonicalBattedBallResolution:
    """
    Resolve a sampled single, double, triple, or batted-ball out.

    Context and advancement RNGs are independently derived from immutable
    sampled plate-appearance identity. No shared mutable RNG is accepted.
    """

    if not isinstance(
        sampled,
        CanonicalSampledPlateAppearance,
    ):
        raise TypeError(
            "sampled must be a "
            "CanonicalSampledPlateAppearance"
        )

    if (
        sampled.outcome
        not in SUPPORTED_BATTED_BALL_ADVANCEMENT_OUTCOMES
    ):
        raise ValueError(
            "sampled outcome is not supported by the "
            "batted-ball advancement resolver"
        )

    query = sampled.query
    outcome = sampled.outcome
    context_seed = derive_canonical_batted_ball_seed(
        sampled=sampled,
        purpose="context",
    )
    defensive_seed = derive_canonical_batted_ball_seed(
        sampled=sampled,
        purpose="defensive_opportunity",
    )
    advancement_seed = derive_canonical_batted_ball_seed(
        sampled=sampled,
        purpose="advancement",
    )
    force_play_seed = (
        derive_canonical_batted_ball_seed(
            sampled=sampled,
            purpose="force_play",
        )
        if outcome
        is CanonicalPlateAppearanceOutcome.OUT
        else None
    )
    tag_attempt_seed = (
        derive_canonical_batted_ball_seed(
            sampled=sampled,
            purpose="tag_attempt",
        )
        if outcome
        is CanonicalPlateAppearanceOutcome.OUT
        else None
    )
    tag_success_seed = (
        derive_canonical_batted_ball_seed(
            sampled=sampled,
            purpose="tag_success",
        )
        if outcome
        is CanonicalPlateAppearanceOutcome.OUT
        else None
    )

    outcome_subtype = (
        _sample_outcome_subtype(context_seed)
        if outcome is CanonicalPlateAppearanceOutcome.OUT
        else None
    )

    context = BaselineBattedBallContextProvider(
        rng=random.Random(context_seed),
    ).sample(
        primary_outcome=outcome.value,
        outcome_subtype=outcome_subtype,
    )

    if context is None:
        raise RuntimeError(
            "batted-ball outcome produced no context"
        )

    defensive_opportunity = (
        resolve_canonical_defensive_opportunity(
            context=context,
            resolution_seed=defensive_seed,
        )
    )

    advancement = BaselineRunnerAdvancementSampler(
        rng=random.Random(advancement_seed),
    ).sample(
        state=query.state,
        batter_id=query.batter_id,
        primary_outcome=outcome.value,
        context=context,
    )

    force_play_draw = (
        random.Random(force_play_seed).random()
        if (
            force_play_seed is not None
            and outcome_subtype == "groundout"
            and query.state.first is not None
            and query.state.outs < 2
        )
        else None
    )

    tag_resolution = (
        _sample_fly_tag_resolution(
            state=query.state,
            outcome_subtype=outcome_subtype,
            attempt_seed=tag_attempt_seed,
            success_seed=tag_success_seed,
        )
        if outcome is CanonicalPlateAppearanceOutcome.OUT
        else None
    )

    special_out_event_type = (
        _select_special_out_event_type(
            state=query.state,
            outcome_subtype=outcome_subtype,
            force_play_draw=force_play_draw,
            tag_resolution=tag_resolution,
        )
        if outcome is CanonicalPlateAppearanceOutcome.OUT
        else None
    )

    if tag_resolution is not None:
        event = _build_caught_fly_tag_event(
            state=query.state,
            batter_id=query.batter_id,
            sequence=query.sequence,
            tag_resolution=tag_resolution,
        )
    elif special_out_event_type is not None:
        event = MultiOutPlayResolver().resolve(
            state=query.state,
            event_type=special_out_event_type,
            batter_id=query.batter_id,
            sequence=query.sequence,
        )
    else:
        if outcome is CanonicalPlateAppearanceOutcome.OUT:
            movements = advancement.movements + (
                RunnerMovement(
                    runner_id=query.batter_id,
                    start_base=Base.HOME,
                    end_base=None,
                    is_out=True,
                ),
            )
            outs_recorded = (
                OutRecord(
                    runner_id=query.batter_id,
                    out_number=query.state.outs + 1,
                    reason=outcome_subtype,
                ),
            )
        else:
            movements = advancement.movements
            outs_recorded = ()

        event = build_play_event(
            sequence=query.sequence,
            event_type=outcome.value,
            batter_id=query.batter_id,
            state_before=query.state,
            runner_movements=movements,
            outs_recorded=outs_recorded,
        )

    event = replace(
        event,
        pitcher_id=query.pitcher_id,
    )

    return CanonicalBattedBallResolution(
        sampled=sampled,
        event=event,
        context=context,
        defensive_opportunity=defensive_opportunity,
        advancement=advancement,
        context_seed=context_seed,
        defensive_seed=defensive_seed,
        advancement_seed=advancement_seed,
        force_play_seed=(
            force_play_seed
            if force_play_draw is not None
            else None
        ),
        force_play_draw=force_play_draw,
        tag_attempt_seed=(
            tag_attempt_seed
            if tag_resolution is not None
            else None
        ),
        tag_attempt_draw=(
            tag_resolution["attempt_draw"]
            if tag_resolution is not None
            else None
        ),
        tag_success_seed=(
            tag_success_seed
            if (
                tag_resolution is not None
                and tag_resolution["attempted"]
            )
            else None
        ),
        tag_success_draw=(
            tag_resolution["success_draw"]
            if (
                tag_resolution is not None
                and tag_resolution["attempted"]
            )
            else None
        ),
        tag_origin_base=(
            tag_resolution["origin_base"]
            if tag_resolution is not None
            else None
        ),
        outcome_subtype=outcome_subtype,
    )


def _select_special_out_event_type(
    *,
    state,
    outcome_subtype: Optional[str],
    force_play_draw: Optional[float] = None,
    tag_resolution=None,
) -> Optional[str]:
    """Select an explicit canonical scoring-rule out transition."""

    if (
        outcome_subtype == "groundout"
        and state.first is not None
        and state.outs < 2
    ):
        if force_play_draw is None:
            raise ValueError(
                "eligible groundout requires force_play_draw"
            )

        if (
            force_play_draw
            < BASELINE_GROUND_BALL_DOUBLE_PLAY_PROBABILITY
        ):
            return "ground_ball_double_play"

        return "ground_ball_fielders_choice"

    if tag_resolution is not None:
        return None

    if outcome_subtype in {
        "flyout",
        "lineout_popout",
    }:
        return "caught_fly"

    return None


def _sample_fly_tag_resolution(
    *,
    state,
    outcome_subtype: Optional[str],
    attempt_seed: Optional[int],
    success_seed: Optional[int],
):
    if (
        outcome_subtype != "flyout"
        or state.outs >= 2
        or attempt_seed is None
        or success_seed is None
    ):
        return None

    for origin_base in (
        Base.THIRD,
        Base.SECOND,
        Base.FIRST,
    ):
        runner_id = state.runner_on(origin_base)

        if runner_id is None:
            continue

        rate = BASELINE_FLY_TAG_RATES[origin_base]
        attempt_draw = random.Random(
            attempt_seed ^ int(origin_base)
        ).random()

        if (
            attempt_draw
            >= rate["attempt_probability"]
        ):
            return {
                "origin_base": origin_base,
                "runner_id": runner_id,
                "destination": rate["destination"],
                "attempt_draw": attempt_draw,
                "success_draw": None,
                "attempted": False,
                "succeeded": False,
            }

        success_draw = random.Random(
            success_seed ^ int(origin_base)
        ).random()

        return {
            "origin_base": origin_base,
            "runner_id": runner_id,
            "destination": rate["destination"],
            "attempt_draw": attempt_draw,
            "success_draw": success_draw,
            "attempted": True,
            "succeeded": (
                success_draw
                < rate["success_probability"]
            ),
        }

    return None


def _build_caught_fly_tag_event(
    *,
    state,
    batter_id: str,
    sequence: int,
    tag_resolution,
) -> PlayEvent:
    movements = []

    for base in (
        Base.FIRST,
        Base.SECOND,
        Base.THIRD,
    ):
        runner_id = state.runner_on(base)

        if runner_id is None:
            continue

        if (
            base == tag_resolution["origin_base"]
            and tag_resolution["attempted"]
        ):
            if tag_resolution["succeeded"]:
                destination = tag_resolution["destination"]
                movements.append(
                    RunnerMovement(
                        runner_id=runner_id,
                        start_base=base,
                        end_base=destination,
                        scored=(
                            destination is Base.HOME
                        ),
                    )
                )
            else:
                movements.append(
                    RunnerMovement(
                        runner_id=runner_id,
                        start_base=base,
                        end_base=None,
                        is_out=True,
                    )
                )
        else:
            movements.append(
                RunnerMovement(
                    runner_id=runner_id,
                    start_base=base,
                    end_base=base,
                )
            )

    movements.append(
        RunnerMovement(
            runner_id=batter_id,
            start_base=Base.HOME,
            end_base=None,
            is_out=True,
        )
    )

    outs = [
        OutRecord(
            runner_id=batter_id,
            out_number=state.outs + 1,
            reason="caught_fly",
        )
    ]

    if (
        tag_resolution["attempted"]
        and not tag_resolution["succeeded"]
        and state.outs + 1 < 3
    ):
        outs.append(
            OutRecord(
                runner_id=tag_resolution["runner_id"],
                out_number=state.outs + 2,
                reason="tag_out",
            )
        )

    scored = (
        tag_resolution["attempted"]
        and tag_resolution["succeeded"]
        and tag_resolution["destination"] is Base.HOME
    )

    return build_play_event(
        sequence=sequence,
        event_type=(
            "sacrifice_fly"
            if scored
            else (
                "caught_fly_tag_advance"
                if (
                    tag_resolution["attempted"]
                    and tag_resolution["succeeded"]
                )
                else (
                    "caught_fly_tag_out"
                    if tag_resolution["attempted"]
                    else "caught_fly"
                )
            )
        ),
        batter_id=batter_id,
        state_before=state,
        runner_movements=tuple(movements),
        outs_recorded=tuple(outs),
        attribution=PlayAttribution(
            rbi_credited_to=(
                batter_id
                if scored
                else None
            ),
            rbi_count=1 if scored else 0,
            sacrifice_type=(
                SacrificeType.FLY
                if scored
                else None
            ),
        ),
    )


def derive_canonical_batted_ball_seed(
    *,
    sampled: CanonicalSampledPlateAppearance,
    purpose: str,
) -> int:
    """Derive deterministic independent RNG identity for one stage."""

    if not isinstance(
        sampled,
        CanonicalSampledPlateAppearance,
    ):
        raise TypeError(
            "sampled must be a "
            "CanonicalSampledPlateAppearance"
        )

    if not purpose:
        raise ValueError(
            "purpose is required"
        )

    query = sampled.query

    payload = "\x1f".join(
        (
            CANONICAL_BATTED_BALL_RESOLUTION_VERSION,
            purpose,
            str(query.matchup_input.game_pk),
            str(query.trial_index),
            str(query.trial_seed),
            str(query.sequence),
            str(sampled.sampling_seed),
            sampled.outcome.value,
            query.batter_id,
            query.pitcher_id,
        )
    ).encode("utf-8")

    digest = hashlib.sha256(payload).digest()

    return int.from_bytes(
        digest[:8],
        byteorder="big",
        signed=False,
    ) & MAX_CANONICAL_SEED


def _sample_outcome_subtype(
    context_seed: int,
) -> str:
    rng = random.Random(
        context_seed ^ 0x5A5A5A5A
    )

    return CANONICAL_OUT_SUBTYPES[
        rng.randrange(
            len(CANONICAL_OUT_SUBTYPES)
        )
    ]

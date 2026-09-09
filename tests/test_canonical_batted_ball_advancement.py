from dataclasses import replace

import pytest

from mlb_app.simulation.events import (
    Base,
    BattedBallContext,
    GameState,
)
from mlb_app.simulation.game import (
    CANONICAL_OUT_SUBTYPES,
    CanonicalLineup,
    CanonicalMatchupInput,
    CanonicalPitchingPlan,
    CanonicalPlateAppearanceOutcome,
    CanonicalPlateAppearanceQuery,
    CanonicalProbabilityProviderIdentity,
    CanonicalSampledPlateAppearance,
    derive_canonical_batted_ball_seed,
    resolve_canonical_batted_ball_outcome,
    resolve_canonical_sampled_plate_appearance,
)


def lineup(side):
    return CanonicalLineup(
        team_side=side,
        player_ids=tuple(
            f"{side}_batter_{index}"
            for index in range(9)
        ),
    )


def pitching_plan(side):
    return CanonicalPitchingPlan(
        team_side=side,
        starter_id=f"{side}_starter",
        bullpen_pitcher_ids=(
            f"{side}_reliever",
        ),
    )


def matchup():
    return CanonicalMatchupInput(
        game_pk=123,
        away_lineup=lineup("away"),
        home_lineup=lineup("home"),
        away_pitching_plan=(
            pitching_plan("away")
        ),
        home_pitching_plan=(
            pitching_plan("home")
        ),
        probability_provider=(
            CanonicalProbabilityProviderIdentity(
                provider_name="advancement-test",
                provider_version="v1",
            )
        ),
    )


def sampled(
    outcome,
    *,
    state=None,
    sequence=0,
):
    state = state or GameState(
        inning=1,
        half="top",
    )

    return CanonicalSampledPlateAppearance(
        query=CanonicalPlateAppearanceQuery(
            matchup_input=matchup(),
            state=state,
            batter_id="away_batter_0",
            pitcher_id="home_starter",
            sequence=sequence,
            trial_index=2,
            trial_seed=12345,
        ),
        outcome=outcome,
        draw=0.25,
        sampling_seed=67890,
    )


@pytest.mark.parametrize(
    "outcome",
    [
        CanonicalPlateAppearanceOutcome.SINGLE,
        CanonicalPlateAppearanceOutcome.DOUBLE,
        CanonicalPlateAppearanceOutcome.TRIPLE,
    ],
)
def test_occupied_base_hits_resolve_with_advancement(
    outcome,
):
    state = GameState(
        inning=4,
        half="top",
        bases=(
            "away_batter_1",
            "away_batter_2",
            "away_batter_3",
        ),
    )

    resolution = resolve_canonical_batted_ball_outcome(
        sampled(
            outcome,
            state=state,
        )
    )

    event = resolution.event

    assert isinstance(
        resolution.context,
        BattedBallContext,
    )
    assert event.event_type == outcome.value
    assert event.pitcher_id == "home_starter"
    assert event.state_after.plate_appearance_number == 1
    assert event.state_after.batting_order_index == 1
    assert (
        event.runner_movements
        == resolution.advancement.movements
    )


def test_occupied_base_triple_scores_all_runners():
    state = GameState(
        inning=4,
        half="top",
        bases=(
            "away_batter_1",
            "away_batter_2",
            "away_batter_3",
        ),
    )

    resolution = resolve_canonical_batted_ball_outcome(
        sampled(
            CanonicalPlateAppearanceOutcome.TRIPLE,
            state=state,
        )
    )

    event = resolution.event

    assert event.event_type == "triple"
    assert event.state_after.first is None
    assert event.state_after.second is None
    assert event.state_after.third == (
        "away_batter_0"
    )
    assert event.state_after.away_score == 3
    assert event.state_after.home_score == 0

    scored = {
        movement.runner_id
        for movement in event.runner_movements
        if movement.scored
    }

    assert scored == {
        "away_batter_1",
        "away_batter_2",
        "away_batter_3",
    }


def test_public_sampled_resolver_routes_occupied_triple():
    state = GameState(
        inning=6,
        half="top",
        bases=(
            "away_batter_1",
            None,
            "away_batter_3",
        ),
    )

    event = resolve_canonical_sampled_plate_appearance(
        sampled(
            CanonicalPlateAppearanceOutcome.TRIPLE,
            state=state,
        )
    )

    assert event.event_type == "triple"
    assert event.state_after.third == (
        "away_batter_0"
    )
    assert event.state_after.away_score == 2


def test_batted_ball_out_uses_explicit_advancement():
    state = GameState(
        inning=5,
        half="top",
        outs=0,
        bases=(
            "away_batter_1",
            "away_batter_2",
            "away_batter_3",
        ),
    )

    resolution = resolve_canonical_batted_ball_outcome(
        sampled(
            CanonicalPlateAppearanceOutcome.OUT,
            state=state,
        )
    )

    event = resolution.event

    assert resolution.outcome_subtype in (
        CANONICAL_OUT_SUBTYPES
    )
    assert event.state_after.outs == 1
    assert event.outs_recorded[0].runner_id == (
        "away_batter_0"
    )
    expected_reason = {
        "flyout": "caught_fly",
        "lineout_popout": "caught_fly",
    }.get(
        resolution.outcome_subtype,
        resolution.outcome_subtype,
    )

    assert event.outs_recorded[0].reason == (
        expected_reason
    )
    assert event.runner_movements[-1].is_out


def test_identical_sample_reproduces_full_resolution():
    value = sampled(
        CanonicalPlateAppearanceOutcome.SINGLE,
        state=GameState(
            inning=3,
            half="top",
            bases=(
                "away_batter_1",
                "away_batter_2",
                None,
            ),
        ),
    )

    first = resolve_canonical_batted_ball_outcome(
        value
    )
    second = resolve_canonical_batted_ball_outcome(
        value
    )

    assert first == second


def test_context_and_advancement_use_separate_seeds():
    value = sampled(
        CanonicalPlateAppearanceOutcome.DOUBLE
    )

    context_seed = derive_canonical_batted_ball_seed(
        sampled=value,
        purpose="context",
    )
    advancement_seed = (
        derive_canonical_batted_ball_seed(
            sampled=value,
            purpose="advancement",
        )
    )

    assert context_seed != advancement_seed


def test_sequence_changes_batted_ball_seed():
    first = sampled(
        CanonicalPlateAppearanceOutcome.SINGLE,
        sequence=1,
    )
    second = replace(
        first,
        query=replace(
            first.query,
            sequence=2,
        ),
    )

    assert derive_canonical_batted_ball_seed(
        sampled=first,
        purpose="context",
    ) != derive_canonical_batted_ball_seed(
        sampled=second,
        purpose="context",
    )


def test_public_sampled_resolver_routes_occupied_single():
    state = GameState(
        inning=2,
        half="top",
        bases=(
            "away_batter_1",
            None,
            None,
        ),
    )

    event = resolve_canonical_sampled_plate_appearance(
        sampled(
            CanonicalPlateAppearanceOutcome.SINGLE,
            state=state,
        )
    )

    assert event.event_type == "single"
    assert event.state_after.first == "away_batter_0"


def test_strikeout_does_not_use_batted_ball_resolution():
    with pytest.raises(
        ValueError,
        match="not supported",
    ):
        resolve_canonical_batted_ball_outcome(
            sampled(
                CanonicalPlateAppearanceOutcome.STRIKEOUT
            )
        )


def test_groundout_with_runner_on_first_becomes_double_play(
    monkeypatch,
):
    monkeypatch.setattr(
        "mlb_app.simulation.game."
        "batted_ball_resolution._sample_outcome_subtype",
        lambda _seed: "groundout",
    )
    monkeypatch.setattr(
        "mlb_app.simulation.game."
        "batted_ball_resolution.random.Random.random",
        lambda _rng: 0.10,
    )

    state = GameState(
        inning=5,
        half="top",
        outs=0,
        bases=(
            "away_batter_1",
            None,
            None,
        ),
    )

    resolution = resolve_canonical_batted_ball_outcome(
        sampled(
            CanonicalPlateAppearanceOutcome.OUT,
            state=state,
        )
    )

    event = resolution.event

    assert event.event_type == (
        "ground_ball_double_play"
    )
    assert event.pitcher_id == "home_starter"
    assert event.state_after.outs == 2
    assert event.state_after.bases == (
        None,
        None,
        None,
    )
    assert len(event.outs_recorded) == 2


def test_groundout_with_two_outs_remains_ordinary_out(
    monkeypatch,
):
    monkeypatch.setattr(
        "mlb_app.simulation.game."
        "batted_ball_resolution._sample_outcome_subtype",
        lambda _seed: "groundout",
    )

    state = GameState(
        inning=5,
        half="top",
        outs=2,
        bases=(
            "away_batter_1",
            None,
            None,
        ),
    )

    resolution = resolve_canonical_batted_ball_outcome(
        sampled(
            CanonicalPlateAppearanceOutcome.OUT,
            state=state,
        )
    )

    event = resolution.event

    assert event.event_type == "out"
    assert event.state_after.outs == 3
    assert len(event.outs_recorded) == 1


def test_flyout_with_runner_on_third_becomes_sacrifice_fly(
    monkeypatch,
):
    monkeypatch.setattr(
        "mlb_app.simulation.game."
        "batted_ball_resolution._sample_outcome_subtype",
        lambda _seed: "flyout",
    )

    state = GameState(
        inning=7,
        half="top",
        outs=1,
        bases=(
            None,
            None,
            "away_batter_3",
        ),
    )

    resolution = resolve_canonical_batted_ball_outcome(
        sampled(
            CanonicalPlateAppearanceOutcome.OUT,
            state=state,
        )
    )

    event = resolution.event

    assert event.event_type == "sacrifice_fly"
    assert event.pitcher_id == "home_starter"
    assert event.state_after.outs == 2
    assert event.state_after.away_score == 1
    assert event.runs_scored == (
        "away_batter_3",
    )
    assert event.attribution.rbi_count == 1


def test_flyout_without_runner_on_third_becomes_caught_fly(
    monkeypatch,
):
    monkeypatch.setattr(
        "mlb_app.simulation.game."
        "batted_ball_resolution._sample_outcome_subtype",
        lambda _seed: "flyout",
    )

    state = GameState(
        inning=7,
        half="top",
        outs=0,
        bases=(
            "away_batter_1",
            None,
            None,
        ),
    )

    resolution = resolve_canonical_batted_ball_outcome(
        sampled(
            CanonicalPlateAppearanceOutcome.OUT,
            state=state,
        )
    )

    event = resolution.event

    assert event.event_type == "caught_fly"
    assert event.pitcher_id == "home_starter"
    assert event.state_after.outs == 1
    assert event.state_after.first == (
        "away_batter_1"
    )


def test_lineout_popout_becomes_caught_fly(
    monkeypatch,
):
    monkeypatch.setattr(
        "mlb_app.simulation.game."
        "batted_ball_resolution._sample_outcome_subtype",
        lambda _seed: "lineout_popout",
    )

    resolution = resolve_canonical_batted_ball_outcome(
        sampled(
            CanonicalPlateAppearanceOutcome.OUT,
        )
    )

    assert resolution.event.event_type == "caught_fly"
    assert resolution.event.state_after.outs == 1


def test_groundout_force_play_can_be_fielders_choice(
    monkeypatch,
):
    monkeypatch.setattr(
        "mlb_app.simulation.game."
        "batted_ball_resolution._sample_outcome_subtype",
        lambda _seed: "groundout",
    )
    monkeypatch.setattr(
        "mlb_app.simulation.game."
        "batted_ball_resolution.random.Random.random",
        lambda _rng: 0.90,
    )

    state = GameState(
        inning=5,
        half="top",
        outs=0,
        bases=(
            "away_batter_1",
            None,
            None,
        ),
    )

    resolution = resolve_canonical_batted_ball_outcome(
        sampled(
            CanonicalPlateAppearanceOutcome.OUT,
            state=state,
        )
    )

    event = resolution.event

    assert event.event_type == (
        "ground_ball_fielders_choice"
    )
    assert event.pitcher_id == "home_starter"
    assert event.state_after.outs == 1
    assert event.state_after.first == (
        "away_batter_0"
    )
    assert event.state_after.second is None
    assert resolution.force_play_seed is not None
    assert resolution.force_play_draw == 0.90


def test_force_play_seed_is_independent():
    value = sampled(
        CanonicalPlateAppearanceOutcome.OUT,
        state=GameState(
            inning=5,
            half="top",
            bases=(
                "away_batter_1",
                None,
                None,
            ),
        ),
    )

    context_seed = derive_canonical_batted_ball_seed(
        sampled=value,
        purpose="context",
    )
    advancement_seed = derive_canonical_batted_ball_seed(
        sampled=value,
        purpose="advancement",
    )
    force_play_seed = derive_canonical_batted_ball_seed(
        sampled=value,
        purpose="force_play",
    )

    assert force_play_seed != context_seed
    assert force_play_seed != advancement_seed


def test_ineligible_groundout_has_no_force_play_provenance(
    monkeypatch,
):
    monkeypatch.setattr(
        "mlb_app.simulation.game."
        "batted_ball_resolution._sample_outcome_subtype",
        lambda _seed: "groundout",
    )

    resolution = resolve_canonical_batted_ball_outcome(
        sampled(
            CanonicalPlateAppearanceOutcome.OUT,
            state=GameState(
                inning=5,
                half="top",
                outs=2,
                bases=(
                    "away_batter_1",
                    None,
                    None,
                ),
            ),
        )
    )

    assert resolution.event.event_type == "out"
    assert resolution.force_play_seed is None
    assert resolution.force_play_draw is None


def test_flyout_runner_on_third_can_hold(
    monkeypatch,
):
    monkeypatch.setattr(
        "mlb_app.simulation.game."
        "batted_ball_resolution._sample_outcome_subtype",
        lambda _seed: "flyout",
    )
    monkeypatch.setattr(
        "mlb_app.simulation.game."
        "batted_ball_resolution._sample_fly_tag_resolution",
        lambda **_kwargs: {
            "origin_base": Base.THIRD,
            "runner_id": "away_batter_3",
            "destination": Base.HOME,
            "attempt_draw": 0.99,
            "success_draw": None,
            "attempted": False,
            "succeeded": False,
        },
    )

    state = GameState(
        inning=6,
        half="top",
        outs=0,
        bases=(
            None,
            None,
            "away_batter_3",
        ),
    )

    resolution = resolve_canonical_batted_ball_outcome(
        sampled(
            CanonicalPlateAppearanceOutcome.OUT,
            state=state,
        )
    )

    event = resolution.event

    assert event.event_type == "caught_fly"
    assert event.state_after.outs == 1
    assert event.state_after.third == "away_batter_3"
    assert event.runs_scored == ()
    assert resolution.tag_origin_base is Base.THIRD
    assert resolution.tag_attempt_draw == 0.99
    assert resolution.tag_success_draw is None


def test_flyout_runner_on_second_tags_safely_to_third(
    monkeypatch,
):
    monkeypatch.setattr(
        "mlb_app.simulation.game."
        "batted_ball_resolution._sample_outcome_subtype",
        lambda _seed: "flyout",
    )

    monkeypatch.setattr(
        "mlb_app.simulation.game."
        "batted_ball_resolution._sample_fly_tag_resolution",
        lambda **_kwargs: {
            "origin_base": Base.SECOND,
            "runner_id": "away_batter_2",
            "destination": Base.THIRD,
            "attempt_draw": 0.10,
            "success_draw": 0.10,
            "attempted": True,
            "succeeded": True,
        },
    )

    state = GameState(
        inning=6,
        half="top",
        outs=0,
        bases=(
            None,
            "away_batter_2",
            None,
        ),
    )

    resolution = resolve_canonical_batted_ball_outcome(
        sampled(
            CanonicalPlateAppearanceOutcome.OUT,
            state=state,
        )
    )

    event = resolution.event

    assert event.event_type == "caught_fly_tag_advance"
    assert event.state_after.outs == 1
    assert event.state_after.second is None
    assert event.state_after.third == "away_batter_2"
    assert resolution.tag_origin_base is Base.SECOND
    assert resolution.tag_attempt_draw == 0.10
    assert resolution.tag_success_draw == 0.10


def test_flyout_runner_on_first_tags_safely_to_second(
    monkeypatch,
):
    monkeypatch.setattr(
        "mlb_app.simulation.game."
        "batted_ball_resolution._sample_outcome_subtype",
        lambda _seed: "flyout",
    )

    monkeypatch.setattr(
        "mlb_app.simulation.game."
        "batted_ball_resolution._sample_fly_tag_resolution",
        lambda **_kwargs: {
            "origin_base": Base.FIRST,
            "runner_id": "away_batter_1",
            "destination": Base.SECOND,
            "attempt_draw": 0.01,
            "success_draw": 0.10,
            "attempted": True,
            "succeeded": True,
        },
    )

    state = GameState(
        inning=6,
        half="top",
        outs=0,
        bases=(
            "away_batter_1",
            None,
            None,
        ),
    )

    resolution = resolve_canonical_batted_ball_outcome(
        sampled(
            CanonicalPlateAppearanceOutcome.OUT,
            state=state,
        )
    )

    event = resolution.event

    assert event.event_type == "caught_fly_tag_advance"
    assert event.state_after.outs == 1
    assert event.state_after.first is None
    assert event.state_after.second == "away_batter_1"


def test_flyout_tag_attempt_can_end_in_tag_out(
    monkeypatch,
):
    monkeypatch.setattr(
        "mlb_app.simulation.game."
        "batted_ball_resolution._sample_outcome_subtype",
        lambda _seed: "flyout",
    )

    monkeypatch.setattr(
        "mlb_app.simulation.game."
        "batted_ball_resolution._sample_fly_tag_resolution",
        lambda **_kwargs: {
            "origin_base": Base.SECOND,
            "runner_id": "away_batter_2",
            "destination": Base.THIRD,
            "attempt_draw": 0.10,
            "success_draw": 0.99,
            "attempted": True,
            "succeeded": False,
        },
    )

    state = GameState(
        inning=6,
        half="top",
        outs=0,
        bases=(
            None,
            "away_batter_2",
            None,
        ),
    )

    resolution = resolve_canonical_batted_ball_outcome(
        sampled(
            CanonicalPlateAppearanceOutcome.OUT,
            state=state,
        )
    )

    event = resolution.event

    assert event.event_type == "caught_fly_tag_out"
    assert event.state_after.outs == 2
    assert event.state_after.bases == (
        None,
        None,
        None,
    )
    assert tuple(
        record.reason
        for record in event.outs_recorded
    ) == (
        "caught_fly",
        "tag_out",
    )


def test_runner_on_third_safe_tag_is_sacrifice_fly(
    monkeypatch,
):
    monkeypatch.setattr(
        "mlb_app.simulation.game."
        "batted_ball_resolution._sample_outcome_subtype",
        lambda _seed: "flyout",
    )

    monkeypatch.setattr(
        "mlb_app.simulation.game."
        "batted_ball_resolution._sample_fly_tag_resolution",
        lambda **_kwargs: {
            "origin_base": Base.THIRD,
            "runner_id": "away_batter_3",
            "destination": Base.HOME,
            "attempt_draw": 0.10,
            "success_draw": 0.10,
            "attempted": True,
            "succeeded": True,
        },
    )

    state = GameState(
        inning=7,
        half="top",
        outs=1,
        bases=(
            None,
            None,
            "away_batter_3",
        ),
    )

    resolution = resolve_canonical_batted_ball_outcome(
        sampled(
            CanonicalPlateAppearanceOutcome.OUT,
            state=state,
        )
    )

    event = resolution.event

    assert event.event_type == "sacrifice_fly"
    assert event.state_after.outs == 2
    assert event.state_after.away_score == 1
    assert event.runs_scored == (
        "away_batter_3",
    )
    assert event.attribution.rbi_count == 1


def test_flyout_with_two_outs_is_not_tag_eligible(
    monkeypatch,
):
    monkeypatch.setattr(
        "mlb_app.simulation.game."
        "batted_ball_resolution._sample_outcome_subtype",
        lambda _seed: "flyout",
    )

    state = GameState(
        inning=7,
        half="top",
        outs=2,
        bases=(
            None,
            "away_batter_2",
            None,
        ),
    )

    resolution = resolve_canonical_batted_ball_outcome(
        sampled(
            CanonicalPlateAppearanceOutcome.OUT,
            state=state,
        )
    )

    assert resolution.event.event_type == "caught_fly"
    assert resolution.event.state_after.outs == 3
    assert resolution.event.state_after.second == (
        "away_batter_2"
    )
    assert resolution.tag_attempt_seed is None
    assert resolution.tag_attempt_draw is None
    assert resolution.tag_success_seed is None
    assert resolution.tag_success_draw is None


def test_failed_tag_after_caught_fly_can_record_third_out(
    monkeypatch,
):
    monkeypatch.setattr(
        "mlb_app.simulation.game."
        "batted_ball_resolution._sample_outcome_subtype",
        lambda _seed: "flyout",
    )

    monkeypatch.setattr(
        "mlb_app.simulation.game."
        "batted_ball_resolution._sample_fly_tag_resolution",
        lambda **_kwargs: {
            "origin_base": Base.SECOND,
            "runner_id": "away_batter_2",
            "destination": Base.THIRD,
            "attempt_draw": 0.10,
            "success_draw": 0.99,
            "attempted": True,
            "succeeded": False,
        },
    )

    state = GameState(
        inning=8,
        half="top",
        outs=1,
        bases=(
            None,
            "away_batter_2",
            None,
        ),
    )

    resolution = resolve_canonical_batted_ball_outcome(
        sampled(
            CanonicalPlateAppearanceOutcome.OUT,
            state=state,
        )
    )

    event = resolution.event

    assert event.state_after.outs == 3
    assert tuple(
        record.out_number
        for record in event.outs_recorded
    ) == (
        2,
        3,
    )
    assert tuple(
        record.reason
        for record in event.outs_recorded
    ) == (
        "caught_fly",
        "tag_out",
    )


@pytest.fixture(autouse=True)
def preserve_primary_batted_ball_event_contract(
    monkeypatch,
):
    """
    Keep this module focused on primary-outcome resolution.

    Defensive event authority is exercised separately by the
    defensive rematerialization contract tests.
    """
    from mlb_app.simulation.game.defensive_event_rematerialization import (
        CanonicalDefensiveEventRematerialization,
    )

    def preserve(**kwargs):
        return CanonicalDefensiveEventRematerialization(
            original_event=kwargs["original_event"],
            event=kwargs["original_event"],
            advancement=kwargs["original_advancement"],
            applied=False,
            authoritative=False,
            blocker="test_primary_outcome_contract",
        )

    monkeypatch.setattr(
        "mlb_app.simulation.game."
        "batted_ball_resolution."
        "rematerialize_canonical_defensive_event",
        preserve,
    )

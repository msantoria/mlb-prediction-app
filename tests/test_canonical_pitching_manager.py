from dataclasses import replace

from mlb_app.simulation.events import (
    Base,
    GameState,
    RunnerMovement,
    build_baserunning_event,
    build_play_event,
)
from mlb_app.simulation.game import (
    CanonicalBullpenPitcher,
    CanonicalBullpenRole,
    CanonicalLineup,
    CanonicalMatchupInput,
    CanonicalPitcherRole,
    CanonicalPitchingManager,
    CanonicalRelieverHookPolicy,
    CanonicalPitchingPlan,
    CanonicalProbabilityProviderIdentity,
    CanonicalStarterHookPolicy,
    build_canonical_bullpen_selector,
)


def matchup():
    return CanonicalMatchupInput(
        game_pk=123,
        away_lineup=CanonicalLineup(
            team_side="away",
            player_ids=tuple(
                f"away_batter_{index}"
                for index in range(9)
            ),
        ),
        home_lineup=CanonicalLineup(
            team_side="home",
            player_ids=tuple(
                f"home_batter_{index}"
                for index in range(9)
            ),
        ),
        away_pitching_plan=CanonicalPitchingPlan(
            team_side="away",
            starter_id="away_starter",
            bullpen_pitcher_ids=(
                "away_long",
                "away_middle",
            ),
        ),
        home_pitching_plan=CanonicalPitchingPlan(
            team_side="home",
            starter_id="home_starter",
            bullpen_pitcher_ids=(
                "home_long",
                "home_middle",
            ),
        ),
        probability_provider=(
            CanonicalProbabilityProviderIdentity(
                provider_name="test",
                provider_version="v1",
            )
        ),
    )


def bullpen(prefix):
    return (
        CanonicalBullpenPitcher(
            pitcher_id=f"{prefix}_long",
            role=CanonicalBullpenRole.LONG_RELIEF,
        ),
        CanonicalBullpenPitcher(
            pitcher_id=f"{prefix}_middle",
            role=CanonicalBullpenRole.MIDDLE_RELIEF,
        ),
    )


def manager():
    return CanonicalPitchingManager(
        matchup_input=matchup(),
        starter_hook_policy=CanonicalStarterHookPolicy(
            minimum_batters_faced=3,
            target_batters_faced=3,
            maximum_batters_faced=3,
        ),
        bullpen_selector=(
            build_canonical_bullpen_selector()
        ),
        away_bullpen=bullpen("away"),
        home_bullpen=bullpen("home"),
    )


def event(
    *,
    state,
    pitcher_id,
    batter_id,
):
    return replace(
        build_play_event(
            sequence=state.plate_appearance_number,
            event_type="out",
            batter_id=batter_id,
            state_before=state,
            runner_movements=(),
            outs_recorded=(),
        ),
        pitcher_id=pitcher_id,
    )


def test_manager_starts_with_both_starters():
    value = manager()

    assert (
        value.active_lifecycle("home").pitcher_id
        == "home_starter"
    )
    assert (
        value.active_lifecycle("away").pitcher_id
        == "away_starter"
    )


def test_top_half_uses_home_pitcher():
    value = manager()

    pitcher = value.pitcher_for_plate_appearance(
        state=GameState(
            inning=1,
            half="top",
        ),
        batter_id="away_batter_0",
    )

    assert pitcher == "home_starter"


def test_bottom_half_uses_away_pitcher():
    value = manager()

    pitcher = value.pitcher_for_plate_appearance(
        state=GameState(
            inning=1,
            half="bottom",
        ),
        batter_id="home_batter_0",
    )

    assert pitcher == "away_starter"


def test_manager_reduces_active_lifecycle():
    value = manager()
    state = GameState(
        inning=1,
        half="top",
    )

    pitcher = value.pitcher_for_plate_appearance(
        state=state,
        batter_id="away_batter_0",
    )

    updated = value.record_plate_appearance(
        event(
            state=state,
            pitcher_id=pitcher,
            batter_id="away_batter_0",
        )
    )

    assert updated.batters_faced == 1


def test_manager_replaces_starter_after_threshold():
    value = manager()
    state = GameState(
        inning=4,
        half="top",
    )

    for index in range(3):
        state = replace(
            state,
            batting_order_index=index,
            plate_appearance_number=index,
        )

        pitcher = value.pitcher_for_plate_appearance(
            state=state,
            batter_id=f"away_batter_{index}",
        )

        value.record_plate_appearance(
            event(
                state=state,
                pitcher_id=pitcher,
                batter_id=f"away_batter_{index}",
            )
        )

    next_state = replace(
        state,
        batting_order_index=3,
        plate_appearance_number=3,
    )

    pitcher = value.pitcher_for_plate_appearance(
        state=next_state,
        batter_id="away_batter_3",
    )

    assert pitcher == "home_long"
    assert (
        value.active_lifecycle("home").role
        is CanonicalPitcherRole.RELIEVER
    )
    assert value.used_pitcher_ids("home") == (
        "home_starter",
        "home_long",
    )

    completed = value.completed_lifecycles(
        "home"
    )

    assert len(completed) == 1
    assert completed[0].pitcher_id == (
        "home_starter"
    )
    assert completed[0].active is False


def test_reliever_is_not_reprocessed_by_starter_policy():
    value = manager()
    state = GameState(
        inning=4,
        half="top",
    )

    starter = value.active_lifecycle("home")

    value._active["home"] = replace(
        starter,
        batters_faced=3,
    )

    first = value.pitcher_for_plate_appearance(
        state=state,
        batter_id="away_batter_3",
    )

    second = value.pitcher_for_plate_appearance(
        state=state,
        batter_id="away_batter_3",
    )

    assert first == "home_long"
    assert second == "home_long"


def test_manager_chains_relievers_after_workload():
    value = CanonicalPitchingManager(
        matchup_input=matchup(),
        starter_hook_policy=CanonicalStarterHookPolicy(
            minimum_batters_faced=3,
            target_batters_faced=3,
            maximum_batters_faced=3,
        ),
        bullpen_selector=(
            build_canonical_bullpen_selector()
        ),
        reliever_hook_policy=CanonicalRelieverHookPolicy(
            minimum_batters_faced=3,
            target_batters_faced=3,
            maximum_batters_faced=3,
        ),
        away_bullpen=bullpen("away"),
        home_bullpen=bullpen("home"),
    )

    state = GameState(
        inning=4,
        half="top",
    )

    value._active["home"] = replace(
        value.active_lifecycle("home"),
        batters_faced=3,
    )

    starter = value.pitcher_for_plate_appearance(
        state=state,
        batter_id="away_batter_0",
    )

    first_reliever = starter

    for index in range(3):
        value.record_plate_appearance(
            event(
                state=state,
                pitcher_id=first_reliever,
                batter_id=f"away_batter_{index}",
            )
        )

    second_reliever = (
        value.pitcher_for_plate_appearance(
            state=state,
            batter_id="away_batter_3",
        )
    )

    assert first_reliever == "home_long"
    assert second_reliever == "home_middle"
    assert value.used_pitcher_ids("home") == (
        "home_starter",
        "home_long",
        "home_middle",
    )

    completed = value.completed_lifecycles(
        "home"
    )

    assert tuple(
        lifecycle.pitcher_id
        for lifecycle in completed
    ) == (
        "home_starter",
        "home_long",
    )


def test_last_available_reliever_is_held():
    value = CanonicalPitchingManager(
        matchup_input=matchup(),
        starter_hook_policy=CanonicalStarterHookPolicy(
            minimum_batters_faced=3,
            target_batters_faced=3,
            maximum_batters_faced=3,
        ),
        bullpen_selector=(
            build_canonical_bullpen_selector()
        ),
        reliever_hook_policy=CanonicalRelieverHookPolicy(
            minimum_batters_faced=3,
            target_batters_faced=3,
            maximum_batters_faced=3,
        ),
        away_bullpen=bullpen("away"),
        home_bullpen=bullpen("home"),
    )

    state = GameState(
        inning=6,
        half="top",
    )

    value._active["home"] = replace(
        value.active_lifecycle("home"),
        batters_faced=3,
    )

    starter = value.pitcher_for_plate_appearance(
        state=state,
        batter_id="away_batter_0",
    )

    reliever = starter

    value._used_pitcher_ids["home"].append(
        "home_long"
    )

    for index in range(3):
        value.record_plate_appearance(
            event(
                state=state,
                pitcher_id=reliever,
                batter_id=f"away_batter_{index}",
            )
        )

    held = value.pitcher_for_plate_appearance(
        state=state,
        batter_id="away_batter_3",
    )

    assert reliever == "home_middle"
    assert held == "home_middle"


def test_manager_preserves_inherited_runner_responsibility():
    value = manager()
    state = GameState(
        inning=4,
        half="top",
    )

    starter_event = replace(
        build_play_event(
            sequence=0,
            event_type="single",
            batter_id="away_batter_0",
            state_before=state,
            runner_movements=(
                RunnerMovement(
                    runner_id="away_batter_0",
                    start_base=0,
                    end_base=1,
                ),
            ),
            outs_recorded=(),
        ),
        pitcher_id="home_starter",
    )

    value.record_plate_appearance(
        starter_event
    )

    value._active["home"] = replace(
        value.active_lifecycle("home"),
        batters_faced=27,
    )

    reliever_id = (
        value.pitcher_for_plate_appearance(
            state=replace(
                state,
                bases=("away_batter_0", None, None),
            ),
            batter_id="away_batter_1",
        )
    )

    scoring_event = replace(
        build_play_event(
            sequence=1,
            event_type="double",
            batter_id="away_batter_1",
            state_before=replace(
                state,
                bases=("away_batter_0", None, None),
            ),
            runner_movements=(
                RunnerMovement(
                    runner_id="away_batter_0",
                    start_base=1,
                    end_base=Base.HOME,
                    scored=True,
                ),
                RunnerMovement(
                    runner_id="away_batter_1",
                    start_base=0,
                    end_base=2,
                ),
            ),
            outs_recorded=(),
        ),
        pitcher_id=reliever_id,
    )

    value.record_plate_appearance(
        scoring_event
    )

    scored = value.scored_run_responsibilities()

    assert len(scored) == 1
    assert scored[0].runner_id == (
        "away_batter_0"
    )
    assert scored[0].responsible_pitcher_id == (
        "home_starter"
    )
    assert scored[0].pitcher_on_mound_id == (
        reliever_id
    )


def test_manager_reconstructs_inherited_earned_run():
    value = manager()
    state = GameState(
        inning=4,
        half="top",
    )

    reach = replace(
        build_play_event(
            sequence=0,
            event_type="single",
            batter_id="away_batter_0",
            state_before=state,
            runner_movements=(
                RunnerMovement(
                    runner_id="away_batter_0",
                    start_base=0,
                    end_base=1,
                ),
            ),
        ),
        pitcher_id="home_starter",
    )

    value.record_plate_appearance(reach)

    value._active["home"] = replace(
        value.active_lifecycle("home"),
        batters_faced=27,
    )

    reliever_id = (
        value.pitcher_for_plate_appearance(
            state=replace(
                state,
                bases=("away_batter_0", None, None),
            ),
            batter_id="away_batter_1",
        )
    )

    score = replace(
        build_play_event(
            sequence=1,
            event_type="double",
            batter_id="away_batter_1",
            state_before=replace(
                state,
                bases=("away_batter_0", None, None),
            ),
            runner_movements=(
                RunnerMovement(
                    runner_id="away_batter_0",
                    start_base=1,
                    end_base=Base.HOME,
                    scored=True,
                ),
                RunnerMovement(
                    runner_id="away_batter_1",
                    start_base=0,
                    end_base=2,
                ),
            ),
        ),
        pitcher_id=reliever_id,
    )

    value.record_plate_appearance(score)

    classifications = value.run_classifications()
    lines = value.reconstructed_pitcher_run_lines()

    assert len(classifications) == 1
    assert classifications[0].earned is True
    assert classifications[0].responsible_pitcher_id == (
        "home_starter"
    )
    assert classifications[0].pitcher_on_mound_id == (
        reliever_id
    )

    assert len(lines) == 1
    assert lines[0].pitcher_id == "home_starter"
    assert lines[0].runs_allowed == 1
    assert lines[0].earned_runs == 1
    assert lines[0].unearned_runs == 0


def test_manager_assigns_automatic_runner_to_active_pitcher():
    value = manager()
    state = GameState(
        inning=10,
        half="top",
        bases=(None, "away_batter_8", None),
    )

    responsibility = value.register_automatic_runner(
        state=state,
        runner_id="away_batter_8",
    )

    assert responsibility.runner_id == "away_batter_8"
    assert responsibility.responsible_pitcher_id == (
        "home_starter"
    )
    assert responsibility.reached_on_event_type == (
        "automatic_runner:10:top"
    )


def test_manager_prefers_bulk_follower_after_opener():
    matchup_input = matchup()

    matchup_input = replace(
        matchup_input,
        home_pitching_plan=CanonicalPitchingPlan(
            team_side="home",
            starter_id="home_starter",
            bullpen_pitcher_ids=(
                "home_long",
                "home_middle",
            ),
            plan_type="opener_bulk",
            preferred_replacement_pitcher_ids=(
                "home_middle",
            ),
        ),
    )

    value = CanonicalPitchingManager(
        matchup_input=matchup_input,
        starter_hook_policy=CanonicalStarterHookPolicy(
            minimum_batters_faced=3,
            target_batters_faced=3,
            maximum_batters_faced=3,
        ),
        bullpen_selector=(
            build_canonical_bullpen_selector()
        ),
        away_bullpen=bullpen("away"),
        home_bullpen=bullpen("home"),
    )

    value._active["home"] = replace(
        value.active_lifecycle("home"),
        batters_faced=3,
    )

    pitcher = value.pitcher_for_plate_appearance(
        state=GameState(
            inning=2,
            half="top",
        ),
        batter_id="away_batter_0",
    )

    assert pitcher == "home_middle"


def test_manager_falls_back_when_preferred_pitcher_unavailable():
    matchup_input = matchup()

    matchup_input = replace(
        matchup_input,
        home_pitching_plan=CanonicalPitchingPlan(
            team_side="home",
            starter_id="home_starter",
            bullpen_pitcher_ids=(
                "home_long",
                "home_middle",
            ),
            plan_type="opener_bulk",
            preferred_replacement_pitcher_ids=(
                "home_middle",
            ),
        ),
    )

    home_options = (
        CanonicalBullpenPitcher(
            pitcher_id="home_long",
            role=CanonicalBullpenRole.LONG_RELIEF,
        ),
        CanonicalBullpenPitcher(
            pitcher_id="home_middle",
            role=CanonicalBullpenRole.MIDDLE_RELIEF,
            available=False,
        ),
    )

    value = CanonicalPitchingManager(
        matchup_input=matchup_input,
        starter_hook_policy=CanonicalStarterHookPolicy(
            minimum_batters_faced=3,
            target_batters_faced=3,
            maximum_batters_faced=3,
        ),
        bullpen_selector=(
            build_canonical_bullpen_selector()
        ),
        away_bullpen=bullpen("away"),
        home_bullpen=home_options,
    )

    value._active["home"] = replace(
        value.active_lifecycle("home"),
        batters_faced=3,
    )

    pitcher = value.pitcher_for_plate_appearance(
        state=GameState(
            inning=2,
            half="top",
        ),
        batter_id="away_batter_0",
    )

    assert pitcher == "home_long"



def test_manager_reconstructs_same_play_home_run_batter():
    value = manager()
    state = GameState(
        inning=1,
        half="top",
    )

    home_run = replace(
        build_play_event(
            sequence=0,
            event_type="hr",
            batter_id="away_batter_0",
            state_before=state,
            runner_movements=(
                RunnerMovement(
                    runner_id="away_batter_0",
                    start_base=Base.HOME,
                    end_base=Base.HOME,
                    scored=True,
                ),
            ),
        ),
        pitcher_id="home_starter",
    )

    value.record_plate_appearance(home_run)

    classifications = value.run_classifications()
    lines = value.reconstructed_pitcher_run_lines()

    assert len(classifications) == 1
    assert classifications[0].runner_id == (
        "away_batter_0"
    )
    assert classifications[0].earned is True
    assert len(lines) == 1
    assert lines[0].pitcher_id == "home_starter"
    assert lines[0].runs_allowed == 1
    assert lines[0].earned_runs == 1


def test_manager_applies_caught_stealing_to_responsibility():
    value = manager()
    state = GameState(
        inning=4,
        half="top",
    )

    reach = replace(
        build_play_event(
            sequence=0,
            event_type="single",
            batter_id="away_batter_0",
            state_before=state,
            runner_movements=(
                RunnerMovement(
                    runner_id="away_batter_0",
                    start_base=Base.HOME,
                    end_base=Base.FIRST,
                ),
            ),
        ),
        pitcher_id="home_starter",
    )
    value.record_plate_appearance(reach)

    assert (
        value.responsibility_for_runner(
            "away_batter_0"
        )
        is not None
    )

    caught = build_baserunning_event(
        sequence=1,
        event_type="caught_stealing",
        batter_id="away_batter_1",
        pitcher_id="home_starter",
        runner_id="away_batter_0",
        state_before=reach.state_after,
        origin_base=Base.FIRST,
        target_base=Base.SECOND,
    )
    value.record_baserunning_event(caught)

    assert (
        value.responsibility_for_runner(
            "away_batter_0"
        )
        is None
    )


def test_manager_preserves_runner_on_successful_steal():
    value = manager()
    state = GameState(
        inning=10,
        half="top",
        bases=(None, "away_batter_8", None),
    )

    value.register_automatic_runner(
        state=state,
        runner_id="away_batter_8",
    )

    steal = build_baserunning_event(
        sequence=1,
        event_type="stolen_base",
        batter_id="away_batter_0",
        pitcher_id="home_starter",
        runner_id="away_batter_8",
        state_before=state,
        origin_base=Base.SECOND,
        target_base=Base.THIRD,
    )
    value.record_baserunning_event(steal)

    responsibility = (
        value.responsibility_for_runner(
            "away_batter_8"
        )
    )

    assert responsibility is not None
    assert (
        responsibility.responsible_pitcher_id
        == "home_starter"
    )


def test_manager_uses_opener_hook_for_opener_bulk():
    from mlb_app.simulation.game.pitcher_hook_policy import (
        build_baseline_opener_hook_policy,
        build_baseline_starter_hook_policy,
    )

    matchup_input = matchup()
    matchup_input = replace(
        matchup_input,
        home_pitching_plan=CanonicalPitchingPlan(
            team_side="home",
            starter_id="home_starter",
            bullpen_pitcher_ids=(
                "home_long",
                "home_middle",
            ),
            plan_type="opener_bulk",
            preferred_replacement_pitcher_ids=(
                "home_middle",
            ),
        ),
    )
    value = CanonicalPitchingManager(
        matchup_input=matchup_input,
        starter_hook_policy=(
            build_baseline_starter_hook_policy()
        ),
        opener_hook_policy=(
            build_baseline_opener_hook_policy()
        ),
        bullpen_selector=(
            build_canonical_bullpen_selector()
        ),
        away_bullpen=bullpen("away"),
        home_bullpen=bullpen("home"),
    )
    value._active["home"] = replace(
        value.active_lifecycle("home"),
        batters_faced=9,
    )

    pitcher = value.pitcher_for_plate_appearance(
        state=GameState(
            inning=3,
            half="top",
        ),
        batter_id="away_batter_0",
    )

    assert pitcher == "home_middle"


def test_manager_preserves_traditional_starter_hook():
    from mlb_app.simulation.game.pitcher_hook_policy import (
        build_baseline_opener_hook_policy,
        build_baseline_starter_hook_policy,
    )

    value = CanonicalPitchingManager(
        matchup_input=matchup(),
        starter_hook_policy=(
            build_baseline_starter_hook_policy()
        ),
        opener_hook_policy=(
            build_baseline_opener_hook_policy()
        ),
        bullpen_selector=(
            build_canonical_bullpen_selector()
        ),
        away_bullpen=bullpen("away"),
        home_bullpen=bullpen("home"),
    )
    value._active["home"] = replace(
        value.active_lifecycle("home"),
        batters_faced=9,
    )

    pitcher = value.pitcher_for_plate_appearance(
        state=GameState(
            inning=3,
            half="top",
        ),
        batter_id="away_batter_0",
    )

    assert pitcher == "home_starter"


def test_manager_falls_back_when_bulk_unavailable_under_opener_hook():
    from mlb_app.simulation.game.pitcher_hook_policy import (
        build_baseline_opener_hook_policy,
        build_baseline_starter_hook_policy,
    )

    matchup_input = replace(
        matchup(),
        home_pitching_plan=CanonicalPitchingPlan(
            team_side="home",
            starter_id="home_starter",
            bullpen_pitcher_ids=(
                "home_long",
                "home_middle",
            ),
            plan_type="opener_bulk",
            preferred_replacement_pitcher_ids=(
                "home_middle",
            ),
        ),
    )
    home_options = (
        CanonicalBullpenPitcher(
            pitcher_id="home_long",
            role=CanonicalBullpenRole.LONG_RELIEF,
        ),
        CanonicalBullpenPitcher(
            pitcher_id="home_middle",
            role=CanonicalBullpenRole.MIDDLE_RELIEF,
            available=False,
        ),
    )
    value = CanonicalPitchingManager(
        matchup_input=matchup_input,
        starter_hook_policy=(
            build_baseline_starter_hook_policy()
        ),
        opener_hook_policy=(
            build_baseline_opener_hook_policy()
        ),
        bullpen_selector=(
            build_canonical_bullpen_selector()
        ),
        away_bullpen=bullpen("away"),
        home_bullpen=home_options,
    )
    value._active["home"] = replace(
        value.active_lifecycle("home"),
        batters_faced=9,
    )

    pitcher = value.pitcher_for_plate_appearance(
        state=GameState(
            inning=3,
            half="top",
        ),
        batter_id="away_batter_0",
    )

    assert pitcher == "home_long"

def test_manager_builds_upcoming_handedness_pocket():
    matchup_input = matchup()

    value = CanonicalPitchingManager(
        matchup_input=matchup_input,
        starter_hook_policy=CanonicalStarterHookPolicy(
            minimum_batters_faced=3,
            target_batters_faced=3,
            maximum_batters_faced=3,
        ),
        bullpen_selector=(
            build_canonical_bullpen_selector()
        ),
        away_bullpen=bullpen("away"),
        home_bullpen=(
            CanonicalBullpenPitcher(
                pitcher_id="home_long",
                role=CanonicalBullpenRole.MIDDLE_RELIEF,
                handedness="L",
            ),
            CanonicalBullpenPitcher(
                pitcher_id="home_middle",
                role=CanonicalBullpenRole.MIDDLE_RELIEF,
                handedness="R",
            ),
        ),
        batter_handedness_by_id={
            "away_batter_0": "L",
            "away_batter_1": "L",
            "away_batter_2": "R",
            "away_batter_3": "L",
            "away_batter_4": "S",
        },
    )

    value._active["home"] = replace(
        value.active_lifecycle("home"),
        batters_faced=3,
    )

    selected = value.pitcher_for_plate_appearance(
        state=GameState(
            inning=6,
            half="top",
            batting_order_index=0,
        ),
        batter_id="away_batter_0",
    )

    assert selected == "home_long"


def test_manager_handedness_pocket_wraps_lineup_order():
    matchup_input = matchup()

    value = CanonicalPitchingManager(
        matchup_input=matchup_input,
        starter_hook_policy=CanonicalStarterHookPolicy(
            minimum_batters_faced=3,
            target_batters_faced=3,
            maximum_batters_faced=3,
        ),
        bullpen_selector=(
            build_canonical_bullpen_selector()
        ),
        away_bullpen=bullpen("away"),
        home_bullpen=(
            CanonicalBullpenPitcher(
                pitcher_id="home_long",
                role=CanonicalBullpenRole.MIDDLE_RELIEF,
                handedness="L",
            ),
            CanonicalBullpenPitcher(
                pitcher_id="home_middle",
                role=CanonicalBullpenRole.MIDDLE_RELIEF,
                handedness="R",
            ),
        ),
        batter_handedness_by_id={
            "away_batter_8": "R",
            "away_batter_0": "R",
            "away_batter_1": "R",
            "away_batter_2": "L",
            "away_batter_3": "S",
        },
    )

    value._active["home"] = replace(
        value.active_lifecycle("home"),
        batters_faced=3,
    )

    selected = value.pitcher_for_plate_appearance(
        state=GameState(
            inning=6,
            half="top",
            batting_order_index=8,
        ),
        batter_id="away_batter_8",
    )

    assert selected == "home_middle"


def test_manager_missing_handedness_preserves_fallback():
    value = manager()

    assert value._upcoming_batter_handedness(
        team_side="home",
        state=GameState(
            inning=6,
            half="top",
            batting_order_index=0,
        ),
    ) == ()

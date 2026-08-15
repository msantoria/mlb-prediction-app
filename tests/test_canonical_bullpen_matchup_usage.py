from dataclasses import replace

import pytest

from mlb_app.simulation.game.bullpen_selector import (
    CanonicalBullpenPitcher,
    CanonicalBullpenRole,
    CanonicalBullpenSelectionContext,
    build_canonical_bullpen_selector,
)
from mlb_app.simulation.game.pitcher_lifecycle import (
    CanonicalPitcherLifecycleState,
    CanonicalPitcherRole,
    CanonicalPitchingDecision,
    CanonicalPitchingDecisionAction,
    CanonicalPitchingDecisionContext,
)


def decision():
    return CanonicalPitchingDecision(
        action=CanonicalPitchingDecisionAction.REPLACE,
        current_pitcher_id="starter",
        replacement_pitcher_id=(
            "pending_bullpen_selection"
        ),
        reason="test_replacement",
    )


def game_context(
    *,
    inning=6,
    fielding_team_score=3,
    batting_team_score=3,
):
    return CanonicalPitchingDecisionContext(
        lifecycle=CanonicalPitcherLifecycleState(
            team_side="home",
            pitcher_id="starter",
            role=CanonicalPitcherRole.STARTER,
            entered_inning=1,
            entered_half="top",
            batters_faced=24,
        ),
        upcoming_batter_id="away_batter_0",
        inning=inning,
        half="top",
        outs=0,
        runners_on_base=0,
        fielding_team_score=fielding_team_score,
        batting_team_score=batting_team_score,
        available_reliever_ids=(
            "left",
            "right",
            "fresh",
            "worked_two",
            "worked_three",
            "priority",
        ),
    )


def pitcher(
    pitcher_id,
    *,
    handedness=None,
    fatigue_index=0.0,
    consecutive_days_worked=0,
    recent_pitch_count=0,
    appearance_priority=0,
    role=CanonicalBullpenRole.MIDDLE_RELIEF,
):
    return CanonicalBullpenPitcher(
        pitcher_id=pitcher_id,
        role=role,
        handedness=handedness,
        fatigue_index=fatigue_index,
        consecutive_days_worked=(
            consecutive_days_worked
        ),
        recent_pitch_count=recent_pitch_count,
        appearance_priority=appearance_priority,
    )


def select(
    bullpen,
    *,
    pocket=(),
    context=None,
):
    return build_canonical_bullpen_selector().select(
        CanonicalBullpenSelectionContext(
            pitching_decision=decision(),
            game_context=context or game_context(),
            bullpen=tuple(bullpen),
            upcoming_batter_handedness=tuple(
                pocket
            ),
        )
    )


def test_left_handed_pocket_prefers_left_hander():
    result = select(
        (
            pitcher("right", handedness="R"),
            pitcher("left", handedness="L"),
        ),
        pocket=("L", "L", "R"),
    )

    assert result.pitcher_id == "left"
    assert result.candidate_pitcher_ids == (
        "left",
        "right",
    )


def test_right_handed_pocket_prefers_right_hander():
    result = select(
        (
            pitcher("left", handedness="L"),
            pitcher("right", handedness="R"),
        ),
        pocket=("R", "R", "L"),
    )

    assert result.pitcher_id == "right"


def test_five_hitter_pocket_is_supported():
    result = select(
        (
            pitcher("right", handedness="R"),
            pitcher("left", handedness="L"),
        ),
        pocket=("L", "L", "L", "R", "S"),
    )

    assert result.pitcher_id == "left"


def test_switch_hitters_are_opposite_side_matchups():
    result = select(
        (
            pitcher(
                "left",
                handedness="L",
                appearance_priority=1,
            ),
            pitcher(
                "right",
                handedness="R",
                appearance_priority=0,
            ),
        ),
        pocket=("S",),
    )

    # Both candidates receive the same switch-hitter penalty,
    # so existing appearance priority remains authoritative.
    assert result.pitcher_id == "right"


def test_two_consecutive_days_remain_fully_usable():
    result = select(
        (
            pitcher(
                "worked_two",
                consecutive_days_worked=2,
                appearance_priority=0,
            ),
            pitcher(
                "fresh",
                consecutive_days_worked=0,
                appearance_priority=1,
            ),
        )
    )

    assert result.pitcher_id == "worked_two"


def test_meaningful_fatigue_begins_on_third_day():
    result = select(
        (
            pitcher(
                "worked_three",
                consecutive_days_worked=3,
                appearance_priority=0,
            ),
            pitcher(
                "fresh",
                consecutive_days_worked=0,
                appearance_priority=1,
            ),
        )
    )

    assert result.pitcher_id == "fresh"


def test_explicit_fatigue_and_pitch_volume_reduce_usage():
    result = select(
        (
            pitcher(
                "priority",
                fatigue_index=0.8,
                recent_pitch_count=35,
                appearance_priority=0,
            ),
            pitcher(
                "fresh",
                fatigue_index=0.1,
                recent_pitch_count=8,
                appearance_priority=1,
            ),
        )
    )

    assert result.pitcher_id == "fresh"


def test_role_order_remains_more_important_than_matchup():
    save_context = game_context(
        inning=9,
        fielding_team_score=4,
        batting_team_score=3,
    )

    result = select(
        (
            pitcher(
                "left",
                role=CanonicalBullpenRole.SETUP,
                handedness="L",
            ),
            pitcher(
                "right",
                role=CanonicalBullpenRole.CLOSER,
                handedness="R",
                fatigue_index=1.0,
                consecutive_days_worked=3,
                recent_pitch_count=40,
            ),
        ),
        pocket=("L", "L", "L"),
        context=save_context,
    )

    assert result.pitcher_id == "right"
    assert result.reason == "save_situation_closer"


def test_missing_new_evidence_preserves_existing_ordering():
    result = select(
        (
            pitcher(
                "left",
                appearance_priority=2,
            ),
            pitcher(
                "right",
                appearance_priority=1,
            ),
        )
    )

    assert result.pitcher_id == "right"


@pytest.mark.parametrize(
    ("changes", "message"),
    (
        (
            {"handedness": "X"},
            "handedness",
        ),
        (
            {"fatigue_index": -0.1},
            "fatigue_index",
        ),
        (
            {"fatigue_index": 1.1},
            "fatigue_index",
        ),
        (
            {"consecutive_days_worked": -1},
            "consecutive_days_worked",
        ),
        (
            {"recent_pitch_count": -1},
            "recent_pitch_count",
        ),
    ),
)
def test_rejects_invalid_pitcher_usage_evidence(
    changes,
    message,
):
    with pytest.raises(ValueError, match=message):
        pitcher("left", **changes)


def test_rejects_invalid_or_oversized_handedness_pocket():
    with pytest.raises(
        ValueError,
        match="cannot exceed five",
    ):
        select(
            (pitcher("left"),),
            pocket=("L",) * 6,
        )

    with pytest.raises(
        ValueError,
        match="must be L, R, or S",
    ):
        select(
            (pitcher("left"),),
            pocket=("X",),
        )


def test_usage_score_is_deterministic():
    bullpen = (
        pitcher(
            "left",
            handedness="L",
            fatigue_index=0.25,
            consecutive_days_worked=2,
            recent_pitch_count=12,
        ),
        pitcher(
            "right",
            handedness="R",
            fatigue_index=0.10,
            consecutive_days_worked=3,
            recent_pitch_count=8,
        ),
    )

    context = CanonicalBullpenSelectionContext(
        pitching_decision=decision(),
        game_context=game_context(),
        bullpen=bullpen,
        upcoming_batter_handedness=(
            "L",
            "L",
            "R",
            "S",
        ),
    )

    selector = build_canonical_bullpen_selector()

    assert selector.select(context) == (
        selector.select(context)
    )

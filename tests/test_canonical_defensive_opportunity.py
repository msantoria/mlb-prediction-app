from dataclasses import replace

import pytest

from mlb_app.simulation.events import (
    BattedBallContext,
    BattedBallDepth,
    BattedBallType,
    ContactQuality,
    GameState,
    SprayDirection,
)
from mlb_app.simulation.game import (
    CANONICAL_DEFENSIVE_OPPORTUNITY_VERSION,
    CanonicalDefensiveCoverageUnit,
    CanonicalDefensiveDifficulty,
    CanonicalDefensiveOpportunity,
    CanonicalDefensiveOutcomeReconciliation,
    CanonicalFieldZone,
    CanonicalLineup,
    CanonicalMatchupInput,
    CanonicalPitchingPlan,
    CanonicalPlateAppearanceOutcome,
    CanonicalPlateAppearanceQuery,
    CanonicalProbabilityProviderIdentity,
    CanonicalSampledDefensiveOutcome,
    CanonicalSampledPlateAppearance,
    derive_canonical_batted_ball_seed,
    resolve_canonical_batted_ball_outcome,
    resolve_canonical_defensive_opportunity,
)


def context(
    *,
    ball_type=BattedBallType.GROUND_BALL,
    direction=SprayDirection.CENTER,
    depth=BattedBallDepth.SHALLOW,
    quality=ContactQuality.MEDIUM,
):
    return BattedBallContext(
        batted_ball_type=ball_type,
        direction=direction,
        depth=depth,
        contact_quality=quality,
    )


@pytest.mark.parametrize(
    (
        "value",
        "expected_zone",
        "expected_unit",
    ),
    (
        (
            context(),
            CanonicalFieldZone.INFIELD_CENTER,
            CanonicalDefensiveCoverageUnit.MIDDLE_INFIELD,
        ),
        (
            context(direction=SprayDirection.PULL),
            CanonicalFieldZone.INFIELD_PULL,
            CanonicalDefensiveCoverageUnit.CORNER_INFIELD,
        ),
        (
            context(
                ball_type=BattedBallType.FLY_BALL,
                direction=SprayDirection.CENTER,
                depth=BattedBallDepth.DEEP,
            ),
            CanonicalFieldZone.OUTFIELD_CENTER,
            CanonicalDefensiveCoverageUnit.CENTER_FIELD,
        ),
        (
            context(
                ball_type=BattedBallType.LINE_DRIVE,
                direction=SprayDirection.OPPOSITE,
                depth=BattedBallDepth.MEDIUM,
            ),
            CanonicalFieldZone.OUTFIELD_OPPOSITE,
            CanonicalDefensiveCoverageUnit.CORNER_OUTFIELD,
        ),
    ),
)
def test_context_maps_to_defensive_zone_and_unit(
    value,
    expected_zone,
    expected_unit,
):
    opportunity = (
        resolve_canonical_defensive_opportunity(
            context=value,
            resolution_seed=17,
        )
    )

    assert opportunity.field_zone is expected_zone
    assert opportunity.coverage_unit is expected_unit
    assert opportunity.resolution_seed == 17


@pytest.mark.parametrize(
    ("value", "expected"),
    (
        (
            context(
                ball_type=BattedBallType.POPUP,
                quality=ContactQuality.SOFT,
            ),
            CanonicalDefensiveDifficulty.ROUTINE,
        ),
        (
            context(
                ball_type=BattedBallType.GROUND_BALL,
                quality=ContactQuality.HARD,
            ),
            CanonicalDefensiveDifficulty.AVERAGE,
        ),
        (
            context(
                ball_type=BattedBallType.LINE_DRIVE,
                depth=BattedBallDepth.DEEP,
                quality=ContactQuality.HARD,
            ),
            CanonicalDefensiveDifficulty.DIFFICULT,
        ),
    ),
)
def test_difficulty_is_derived_from_contact(
    value,
    expected,
):
    opportunity = (
        resolve_canonical_defensive_opportunity(
            context=value,
            resolution_seed=23,
        )
    )

    assert opportunity.difficulty is expected


def test_diagnostics_are_explicitly_non_mutating():
    opportunity = (
        resolve_canonical_defensive_opportunity(
            context=context(),
            resolution_seed=29,
        )
    )

    diagnostics = opportunity.to_diagnostics()

    assert diagnostics["schema_version"] == (
        CANONICAL_DEFENSIVE_OPPORTUNITY_VERSION
    )
    assert diagnostics["changes_play_result"] is False
    assert diagnostics["field_zone"] == "infield_center"


def test_contract_rejects_invalid_seed():
    with pytest.raises(
        ValueError,
        match="resolution_seed",
    ):
        resolve_canonical_defensive_opportunity(
            context=context(),
            resolution_seed=-1,
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


def sampled(sequence=0):
    matchup = CanonicalMatchupInput(
        game_pk=123,
        away_lineup=lineup("away"),
        home_lineup=lineup("home"),
        away_pitching_plan=pitching_plan("away"),
        home_pitching_plan=pitching_plan("home"),
        probability_provider=(
            CanonicalProbabilityProviderIdentity(
                provider_name="defense-test",
                provider_version="v1",
            )
        ),
    )

    return CanonicalSampledPlateAppearance(
        query=CanonicalPlateAppearanceQuery(
            matchup_input=matchup,
            state=GameState(
                inning=1,
                half="top",
            ),
            batter_id="away_batter_0",
            pitcher_id="home_starter",
            sequence=sequence,
            trial_index=2,
            trial_seed=12345,
        ),
        outcome=CanonicalPlateAppearanceOutcome.SINGLE,
        draw=0.25,
        sampling_seed=67890,
    )


def test_batted_ball_resolution_attaches_opportunity():
    value = sampled()
    resolution = resolve_canonical_batted_ball_outcome(
        value
    )

    assert isinstance(
        resolution.defensive_opportunity,
        CanonicalDefensiveOpportunity,
    )
    assert resolution.defensive_seed == (
        derive_canonical_batted_ball_seed(
            sampled=value,
            purpose="defensive_opportunity",
        )
    )
    assert resolution.defensive_seed not in {
        resolution.context_seed,
        resolution.advancement_seed,
    }
    assert isinstance(
        resolution.defensive_outcome,
        CanonicalSampledDefensiveOutcome,
    )
    assert resolution.defensive_outcome.authoritative is False
    assert isinstance(
        resolution.defensive_reconciliation,
        CanonicalDefensiveOutcomeReconciliation,
    )
    assert (
        resolution.defensive_reconciliation.authoritative
        is False
    )
    assert resolution.defensive_outcome.sampling_seed == (
        resolution.defensive_outcome_seed
    )
    assert resolution.defensive_outcome_seed == (
        derive_canonical_batted_ball_seed(
            sampled=value,
            purpose="defensive_outcome",
        )
    )
    assert resolution.defensive_outcome_seed not in {
        resolution.context_seed,
        resolution.defensive_seed,
        resolution.advancement_seed,
    }


def test_identical_sample_reproduces_defensive_opportunity():
    value = sampled()

    first = resolve_canonical_batted_ball_outcome(value)
    second = resolve_canonical_batted_ball_outcome(value)

    assert first.defensive_opportunity == (
        second.defensive_opportunity
    )


def test_sequence_changes_defensive_seed():
    first = sampled(sequence=1)
    second = replace(
        first,
        query=replace(
            first.query,
            sequence=2,
        ),
    )

    first_resolution = (
        resolve_canonical_batted_ball_outcome(first)
    )
    second_resolution = (
        resolve_canonical_batted_ball_outcome(second)
    )

    assert first_resolution.defensive_seed != (
        second_resolution.defensive_seed
    )

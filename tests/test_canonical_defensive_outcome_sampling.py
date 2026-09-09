import pytest

from mlb_app.simulation.events import (
    BattedBallContext,
    BattedBallDepth,
    BattedBallType,
    ContactQuality,
    SprayDirection,
)
from mlb_app.simulation.game import (
    CANONICAL_DEFENSIVE_OUTCOME_ORDER,
    CANONICAL_DEFENSIVE_OUTCOME_SAMPLING_VERSION,
    CanonicalDefensiveDifficulty,
    CanonicalDefensiveOutcome,
    CanonicalDefensiveOutcomeProbabilities,
    CanonicalDefensiveOutcomeProbability,
    resolve_canonical_defensive_opportunity,
    build_baseline_defensive_outcome_probabilities,
    sample_canonical_defensive_outcome,
)


def opportunity(difficulty):
    quality = {
        CanonicalDefensiveDifficulty.ROUTINE: (
            ContactQuality.SOFT
        ),
        CanonicalDefensiveDifficulty.AVERAGE: (
            ContactQuality.MEDIUM
        ),
        CanonicalDefensiveDifficulty.DIFFICULT: (
            ContactQuality.HARD
        ),
    }[difficulty]
    ball_type = (
        BattedBallType.LINE_DRIVE
        if difficulty
        is CanonicalDefensiveDifficulty.DIFFICULT
        else BattedBallType.GROUND_BALL
    )
    depth = (
        BattedBallDepth.DEEP
        if difficulty
        is CanonicalDefensiveDifficulty.DIFFICULT
        else BattedBallDepth.SHALLOW
    )

    return resolve_canonical_defensive_opportunity(
        context=BattedBallContext(
            batted_ball_type=ball_type,
            direction=SprayDirection.CENTER,
            depth=depth,
            contact_quality=quality,
        ),
        resolution_seed=17,
    )


@pytest.mark.parametrize(
    "difficulty",
    tuple(CanonicalDefensiveDifficulty),
)
def test_baseline_distribution_is_complete(difficulty):
    distribution = (
        build_baseline_defensive_outcome_probabilities(
            opportunity(difficulty)
        )
    )

    assert tuple(
        point.outcome
        for point in distribution.probabilities
    ) == CANONICAL_DEFENSIVE_OUTCOME_ORDER
    assert sum(
        point.probability
        for point in distribution.probabilities
    ) == pytest.approx(1.0)
    assert distribution.model_version == (
        CANONICAL_DEFENSIVE_OUTCOME_SAMPLING_VERSION
    )


def test_conversion_probability_declines_with_difficulty():
    probabilities = {
        difficulty: (
            build_baseline_defensive_outcome_probabilities(
                opportunity(difficulty)
            ).probability_for(
                CanonicalDefensiveOutcome.CONVERTED_OUT
            )
        )
        for difficulty in CanonicalDefensiveDifficulty
    }

    assert probabilities[
        CanonicalDefensiveDifficulty.ROUTINE
    ] > probabilities[
        CanonicalDefensiveDifficulty.AVERAGE
    ] > probabilities[
        CanonicalDefensiveDifficulty.DIFFICULT
    ]


@pytest.mark.parametrize(
    ("seed", "expected"),
    (
        (31, CanonicalDefensiveOutcome.CONVERTED_OUT),
        (2, CanonicalDefensiveOutcome.BASE_HIT),
    ),
)
def test_sampling_is_reproducible(seed, expected):
    value = opportunity(
        CanonicalDefensiveDifficulty.AVERAGE
    )

    first = sample_canonical_defensive_outcome(
        opportunity=value,
        sampling_seed=seed,
    )
    second = sample_canonical_defensive_outcome(
        opportunity=value,
        sampling_seed=seed,
    )

    assert first == second
    assert first.outcome is expected
    assert first.authoritative is False


def test_diagnostics_expose_shadow_boundary():
    sampled = sample_canonical_defensive_outcome(
        opportunity=opportunity(
            CanonicalDefensiveDifficulty.DIFFICULT
        ),
        sampling_seed=43,
    )

    diagnostics = sampled.to_diagnostics()

    assert diagnostics["schema_version"] == (
        CANONICAL_DEFENSIVE_OUTCOME_SAMPLING_VERSION
    )
    assert diagnostics["authoritative"] is False
    assert set(diagnostics["probabilities"]) == {
        outcome.value
        for outcome in CanonicalDefensiveOutcome
    }


def test_distribution_rejects_missing_outcome():
    value = opportunity(
        CanonicalDefensiveDifficulty.ROUTINE
    )

    with pytest.raises(
        ValueError,
        match="every defensive outcome",
    ):
        CanonicalDefensiveOutcomeProbabilities(
            opportunity=value,
            probabilities=(
                CanonicalDefensiveOutcomeProbability(
                    outcome=(
                        CanonicalDefensiveOutcome
                        .CONVERTED_OUT
                    ),
                    probability=1.0,
                ),
            ),
        )


@pytest.mark.parametrize(
    "seed",
    (-1, True),
)
def test_sampling_rejects_invalid_seed(seed):
    with pytest.raises(
        ValueError,
        match="sampling_seed",
    ):
        sample_canonical_defensive_outcome(
            opportunity=opportunity(
                CanonicalDefensiveDifficulty.AVERAGE
            ),
            sampling_seed=seed,
        )

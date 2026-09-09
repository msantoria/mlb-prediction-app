import pytest

from mlb_app.simulation.events import (
    BattedBallContext,
    BattedBallDepth,
    BattedBallType,
    ContactQuality,
    SprayDirection,
)
from mlb_app.simulation.game import (
    CANONICAL_DEFENSIVE_HIT_TYPE_ORDER,
    CanonicalDefensiveOutcome,
    CanonicalReconciledBattedBallOutcome,
    build_canonical_defensive_hit_type_distribution,
    resolve_canonical_defensive_opportunity,
    sample_canonical_defensive_hit_type,
    sample_canonical_defensive_outcome,
)


def opportunity(
    *,
    ball_type=BattedBallType.LINE_DRIVE,
    depth=BattedBallDepth.MEDIUM,
    quality=ContactQuality.MEDIUM,
):
    return resolve_canonical_defensive_opportunity(
        context=BattedBallContext(
            batted_ball_type=ball_type,
            direction=SprayDirection.CENTER,
            depth=depth,
            contact_quality=quality,
        ),
        resolution_seed=11,
    )


def base_hit_sample(value=None):
    value = value or opportunity()

    for seed in range(1000):
        sampled = sample_canonical_defensive_outcome(
            opportunity=value,
            sampling_seed=seed,
        )

        if sampled.outcome is CanonicalDefensiveOutcome.BASE_HIT:
            return sampled

    raise AssertionError("no deterministic base-hit seed found")


def test_distribution_is_complete_and_normalized():
    distribution = (
        build_canonical_defensive_hit_type_distribution(
            opportunity()
        )
    )

    assert tuple(
        point.hit_type
        for point in distribution.probabilities
    ) == CANONICAL_DEFENSIVE_HIT_TYPE_ORDER
    assert sum(
        point.probability
        for point in distribution.probabilities
    ) == pytest.approx(1.0)


def test_hard_deep_contact_increases_extra_base_share():
    soft = build_canonical_defensive_hit_type_distribution(
        opportunity(
            depth=BattedBallDepth.DEEP,
            quality=ContactQuality.SOFT,
        )
    )
    hard = build_canonical_defensive_hit_type_distribution(
        opportunity(
            depth=BattedBallDepth.DEEP,
            quality=ContactQuality.HARD,
        )
    )

    soft_extra_bases = sum(
        point.probability
        for point in soft.probabilities
        if point.hit_type is not (
            CanonicalReconciledBattedBallOutcome.SINGLE
        )
    )
    hard_extra_bases = sum(
        point.probability
        for point in hard.probabilities
        if point.hit_type is not (
            CanonicalReconciledBattedBallOutcome.SINGLE
        )
    )

    assert hard_extra_bases > soft_extra_bases


def test_hit_type_sampling_is_reproducible():
    defensive_sample = base_hit_sample()

    first = sample_canonical_defensive_hit_type(
        defensive_sample=defensive_sample,
        sampling_seed=37,
    )
    second = sample_canonical_defensive_hit_type(
        defensive_sample=defensive_sample,
        sampling_seed=37,
    )

    assert first == second
    assert first.hit_type in (
        CANONICAL_DEFENSIVE_HIT_TYPE_ORDER
    )
    assert first.authoritative is False


def test_non_hit_defensive_sample_is_rejected():
    value = opportunity()
    converted = None

    for seed in range(1000):
        candidate = sample_canonical_defensive_outcome(
            opportunity=value,
            sampling_seed=seed,
        )

        if (
            candidate.outcome
            is CanonicalDefensiveOutcome.CONVERTED_OUT
        ):
            converted = candidate
            break

    assert converted is not None

    with pytest.raises(
        ValueError,
        match="base-hit sample",
    ):
        sample_canonical_defensive_hit_type(
            defensive_sample=converted,
            sampling_seed=17,
        )


def test_diagnostics_remain_non_authoritative():
    sampled = sample_canonical_defensive_hit_type(
        defensive_sample=base_hit_sample(),
        sampling_seed=41,
    )

    diagnostics = sampled.to_diagnostics()

    assert diagnostics["authoritative"] is False
    assert diagnostics["hit_type"] in {
        "single",
        "double",
        "triple",
    }

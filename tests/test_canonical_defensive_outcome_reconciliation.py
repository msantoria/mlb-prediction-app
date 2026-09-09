import pytest

from mlb_app.simulation.events import (
    BattedBallContext,
    BattedBallDepth,
    BattedBallType,
    ContactQuality,
    SprayDirection,
)
from mlb_app.simulation.game import (
    CANONICAL_DEFENSIVE_OUTCOME_RECONCILIATION_VERSION,
    CanonicalDefensiveDifficulty,
    CanonicalDefensiveOutcome,
    CanonicalPlateAppearanceOutcome,
    CanonicalReconciledBattedBallOutcome,
    build_baseline_defensive_outcome_probabilities,
    reconcile_canonical_defensive_outcome,
    resolve_canonical_defensive_opportunity,
    sample_canonical_defensive_outcome,
)


def defensive_sample(outcome):
    opportunity = resolve_canonical_defensive_opportunity(
        context=BattedBallContext(
            batted_ball_type=BattedBallType.GROUND_BALL,
            direction=SprayDirection.CENTER,
            depth=BattedBallDepth.SHALLOW,
            contact_quality=ContactQuality.MEDIUM,
        ),
        resolution_seed=11,
    )
    seed = {
        CanonicalDefensiveOutcome.CONVERTED_OUT: 31,
        CanonicalDefensiveOutcome.BASE_HIT: 2,
        CanonicalDefensiveOutcome.FIELDING_ERROR: 52,
    }[outcome]
    sampled = sample_canonical_defensive_outcome(
        opportunity=opportunity,
        sampling_seed=seed,
    )

    assert sampled.outcome is outcome
    return sampled


def test_converted_out_reconciles_primary_hit_to_out():
    result = reconcile_canonical_defensive_outcome(
        primary_outcome=(
            CanonicalPlateAppearanceOutcome.DOUBLE
        ),
        defensive_sample=defensive_sample(
            CanonicalDefensiveOutcome.CONVERTED_OUT
        ),
    )

    assert result.ready is True
    assert result.reconciled_outcome is (
        CanonicalReconciledBattedBallOutcome.OUT
    )
    assert result.changes_primary_outcome is True
    assert result.requires_event_rematerialization is True
    assert result.authoritative is False


@pytest.mark.parametrize(
    (
        "primary",
        "expected",
    ),
    (
        (
            CanonicalPlateAppearanceOutcome.SINGLE,
            CanonicalReconciledBattedBallOutcome.SINGLE,
        ),
        (
            CanonicalPlateAppearanceOutcome.DOUBLE,
            CanonicalReconciledBattedBallOutcome.DOUBLE,
        ),
        (
            CanonicalPlateAppearanceOutcome.TRIPLE,
            CanonicalReconciledBattedBallOutcome.TRIPLE,
        ),
    ),
)
def test_base_hit_preserves_existing_hit_type(
    primary,
    expected,
):
    result = reconcile_canonical_defensive_outcome(
        primary_outcome=primary,
        defensive_sample=defensive_sample(
            CanonicalDefensiveOutcome.BASE_HIT
        ),
    )

    assert result.ready is True
    assert result.reconciled_outcome is expected
    assert result.changes_primary_outcome is False
    assert result.requires_event_rematerialization is False


def test_defense_created_hit_blocks_without_hit_type():
    result = reconcile_canonical_defensive_outcome(
        primary_outcome=CanonicalPlateAppearanceOutcome.OUT,
        defensive_sample=defensive_sample(
            CanonicalDefensiveOutcome.BASE_HIT
        ),
    )

    assert result.ready is False
    assert result.reconciled_outcome is None
    assert result.blockers == (
        "defensive_base_hit_requires_hit_type",
    )


def test_defense_created_hit_accepts_explicit_hit_type():
    result = reconcile_canonical_defensive_outcome(
        primary_outcome=CanonicalPlateAppearanceOutcome.OUT,
        defensive_sample=defensive_sample(
            CanonicalDefensiveOutcome.BASE_HIT
        ),
        resolved_hit_type=(
            CanonicalReconciledBattedBallOutcome.SINGLE
        ),
    )

    assert result.ready is True
    assert result.reconciled_outcome is (
        CanonicalReconciledBattedBallOutcome.SINGLE
    )
    assert result.changes_primary_outcome is True


def test_error_blocks_without_real_fielder_identity():
    result = reconcile_canonical_defensive_outcome(
        primary_outcome=CanonicalPlateAppearanceOutcome.OUT,
        defensive_sample=defensive_sample(
            CanonicalDefensiveOutcome.FIELDING_ERROR
        ),
    )

    assert result.ready is False
    assert result.blockers == (
        "fielding_error_requires_fielder_identity",
    )


def test_error_reconciles_with_fielder_identity():
    result = reconcile_canonical_defensive_outcome(
        primary_outcome=CanonicalPlateAppearanceOutcome.OUT,
        defensive_sample=defensive_sample(
            CanonicalDefensiveOutcome.FIELDING_ERROR
        ),
        error_fielder_id="home_shortstop",
    )

    assert result.ready is True
    assert result.reconciled_outcome is (
        CanonicalReconciledBattedBallOutcome
        .REACHED_ON_ERROR
    )
    assert result.error_fielder_id == "home_shortstop"
    assert result.changes_primary_outcome is True


def test_diagnostics_expose_fail_closed_state():
    result = reconcile_canonical_defensive_outcome(
        primary_outcome=CanonicalPlateAppearanceOutcome.OUT,
        defensive_sample=defensive_sample(
            CanonicalDefensiveOutcome.BASE_HIT
        ),
    )

    diagnostics = result.to_diagnostics()

    assert diagnostics["schema_version"] == (
        CANONICAL_DEFENSIVE_OUTCOME_RECONCILIATION_VERSION
    )
    assert diagnostics["status"] == "blocked"
    assert diagnostics["authoritative"] is False
    assert diagnostics["reconciled_outcome"] is None
    assert diagnostics["blockers"] == [
        "defensive_base_hit_requires_hit_type"
    ]


def test_non_batted_ball_primary_is_rejected():
    with pytest.raises(
        ValueError,
        match="unsupported primary",
    ):
        reconcile_canonical_defensive_outcome(
            primary_outcome=(
                CanonicalPlateAppearanceOutcome.STRIKEOUT
            ),
            defensive_sample=defensive_sample(
                CanonicalDefensiveOutcome.CONVERTED_OUT
            ),
        )

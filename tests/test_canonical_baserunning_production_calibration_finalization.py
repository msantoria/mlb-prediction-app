from datetime import date
from types import SimpleNamespace

from mlb_app.simulation.shadow.production_calibration_finalization import (
    CANONICAL_BASERUNNING_PRODUCTION_CALIBRATION_FINALIZATION_VERSION,
    CANONICAL_BASERUNNING_PRODUCTION_CALIBRATION_POLICY_VERSION,
    build_canonical_baserunning_production_calibration_policy,
    finalize_canonical_baserunning_production_calibration,
    finalize_canonical_baserunning_production_settlements,
)


def settlement(**overrides):
    value = {
        "settled_game_count": 331,
        "settlement_complete": True,
        "parameter_reselection_permitted": True,
        "projected_stolen_bases": 389.6,
        "observed_stolen_bases": 439,
        "projected_caught_stealing": 159.6,
        "observed_caught_stealing": 143,
    }
    value.update(overrides)
    return value


def test_settled_production_evidence_retains_incumbent():
    result = (
        finalize_canonical_baserunning_production_calibration(
            settlement()
        )
    )
    diagnostics = result.to_diagnostics()

    assert result.ready is True
    assert result.decision == "retain_incumbent"
    assert result.calibration_gate.calibration_gate_passed is True
    assert result.comparison.game_count == 331
    assert (
        result.comparison.stolen_base_absolute_error
        == 49.4
    )
    assert (
        result.comparison.caught_stealing_absolute_error
        == 16.6
    )
    assert (
        result.comparison.attempt_absolute_error
        == 32.8
    )
    assert diagnostics["incumbent_retained"] is True
    assert diagnostics["candidate_reselected"] is False
    assert diagnostics["production_authority_changed"] is False


def test_incomplete_settlement_remains_pending():
    result = (
        finalize_canonical_baserunning_production_calibration(
            settlement(
                settled_game_count=99,
                settlement_complete=False,
                parameter_reselection_permitted=False,
            )
        )
    )

    assert result.ready is False
    assert result.decision == "pending_settlement"
    assert result.settlement_complete is False


def test_failed_production_gate_reopens_candidate_selection():
    result = (
        finalize_canonical_baserunning_production_calibration(
            settlement(
                projected_stolen_bases=200.0,
                projected_caught_stealing=250.0,
            )
        )
    )

    assert result.ready is True
    assert result.decision == "reopen_candidate_selection"
    assert result.calibration_gate.calibration_gate_passed is False
    assert result.to_diagnostics()[
        "candidate_reselected"
    ] is False


def test_finalization_is_deterministic():
    first = (
        finalize_canonical_baserunning_production_calibration(
            settlement()
        )
    )
    second = (
        finalize_canonical_baserunning_production_calibration(
            settlement()
        )
    )

    assert first == second
    assert first.finalization_digest == (
        second.finalization_digest
    )
    assert len(first.finalization_digest) == 64


def test_version_is_explicit():
    assert (
        CANONICAL_BASERUNNING_PRODUCTION_CALIBRATION_FINALIZATION_VERSION
        == (
            "canonical_baserunning_production_"
            "calibration_finalization_v1"
        )
    )

def test_empty_summary_fails_safe_as_pending():
    result = (
        finalize_canonical_baserunning_production_calibration(
            {
                "settled_game_count": 0,
                "settlement_complete": False,
                "parameter_reselection_permitted": False,
            }
        )
    )

    assert result.ready is False
    assert result.decision == "pending_settlement"
    assert result.comparison.ready is False
    assert result.calibration_gate.ready is False

def settlement_row(
    game_pk,
    *,
    projected_stolen_bases=1.0,
    projected_caught_stealing=0.5,
    observed_stolen_bases=1,
    observed_caught_stealing=1,
):
    return SimpleNamespace(
        game_pk=game_pk,
        game_date=date(
            2026,
            7,
            1 + ((game_pk - 1) // 15),
        ),
        comparison_json={
            "projected_stolen_bases":
                projected_stolen_bases,
            "projected_caught_stealing":
                projected_caught_stealing,
            "stolen_base_absolute_error": abs(
                projected_stolen_bases
                - observed_stolen_bases
            ),
            "caught_stealing_absolute_error": abs(
                projected_caught_stealing
                - observed_caught_stealing
            ),
            "attempt_absolute_error": abs(
                projected_stolen_bases
                + projected_caught_stealing
                - observed_stolen_bases
                - observed_caught_stealing
            ),
        },
        observed_stolen_bases=observed_stolen_bases,
        observed_caught_stealing=observed_caught_stealing,
    )


def test_production_policy_uses_frozen_window_target():
    policy = (
        build_canonical_baserunning_production_calibration_policy()
    )

    assert policy.minimum_game_count == 100
    assert policy.policy_version == (
        CANONICAL_BASERUNNING_PRODUCTION_CALIBRATION_POLICY_VERSION
    )


def test_games_after_frozen_window_do_not_change_decision():
    first_hundred = tuple(
        settlement_row(game_pk)
        for game_pk in range(1, 101)
    )
    later_games = tuple(
        settlement_row(
            game_pk,
            projected_stolen_bases=20.0,
            projected_caught_stealing=20.0,
        )
        for game_pk in range(101, 111)
    )

    frozen = (
        finalize_canonical_baserunning_production_settlements(
            first_hundred
        )
    )
    extended = (
        finalize_canonical_baserunning_production_settlements(
            later_games + first_hundred
        )
    )

    assert frozen.settled_game_count == 100
    assert extended.settled_game_count == 100
    assert frozen.decision == extended.decision
    assert frozen.finalization_digest == (
        extended.finalization_digest
    )


def test_under_target_window_remains_pending():
    result = (
        finalize_canonical_baserunning_production_settlements(
            tuple(
                settlement_row(game_pk)
                for game_pk in range(1, 100)
            )
        )
    )

    assert result.ready is False
    assert result.decision == "pending_settlement"

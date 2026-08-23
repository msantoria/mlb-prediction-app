from types import SimpleNamespace

import pytest

from mlb_app.simulation.shadow.extras_walkoff_activation import (
    CANONICAL_EXTRAS_WALKOFF_ACTIVATION_VERSION,
    evaluate_canonical_extras_walkoff_activation,
)


def payload(**outcome_overrides):
    outcomes = {
        "simulation_count": 1000,
        "extra_innings_probability": 0.09,
        "walk_off_probability": 0.08,
    }
    outcomes.update(outcome_overrides)

    return {
        "outcomes": outcomes,
        "trial_diagnostics": {
            "game_validation_pass_rate": 1.0,
            "box_score_reconciliation_pass_rate": 1.0,
            "warnings": [],
        },
    }


def inputs(
    *,
    max_extra_innings=6,
    automatic_runner_enabled=True,
):
    return SimpleNamespace(
        game_config=SimpleNamespace(
            max_extra_innings=max_extra_innings,
            automatic_runner_enabled=(
                automatic_runner_enabled
            ),
        )
    )


def test_valid_canonical_execution_activates_mechanics():
    result = (
        evaluate_canonical_extras_walkoff_activation(
            canonical_payload=payload(),
            execution_inputs=inputs(),
        )
    )
    diagnostics = result.to_diagnostics()

    assert result.active is True
    assert result.status == "active"
    assert result.blockers == ()
    assert diagnostics[
        "schema_version"
    ] == (
        CANONICAL_EXTRAS_WALKOFF_ACTIVATION_VERSION
    )
    assert diagnostics[
        "extra_innings_active"
    ] is True
    assert diagnostics[
        "automatic_runner_active"
    ] is True
    assert diagnostics[
        "walk_off_shortening_active"
    ] is True
    assert diagnostics[
        "behavioral_validation"
    ] == "passed"
    assert diagnostics[
        "production_authority_changed"
    ] is False


def test_missing_payload_fails_safe_as_unavailable():
    result = (
        evaluate_canonical_extras_walkoff_activation(
            canonical_payload=None,
            execution_inputs=None,
        )
    )

    assert result.active is False
    assert result.status == "unavailable"
    assert (
        "canonical_payload_unavailable"
        in result.blockers
    )
    assert (
        "canonical_outcomes_unavailable"
        in result.blockers
    )


@pytest.mark.parametrize(
    ("field", "value", "blocker"),
    (
        (
            "simulation_count",
            0,
            "canonical_simulation_count_unavailable",
        ),
        (
            "extra_innings_probability",
            float("nan"),
            "extra_innings_probability_unavailable",
        ),
        (
            "walk_off_probability",
            1.1,
            "walk_off_probability_unavailable",
        ),
    ),
)
def test_invalid_outcomes_block_activation(
    field,
    value,
    blocker,
):
    result = (
        evaluate_canonical_extras_walkoff_activation(
            canonical_payload=payload(
                **{field: value}
            ),
            execution_inputs=inputs(),
        )
    )

    assert result.status == "blocked"
    assert blocker in result.blockers


def test_incomplete_validation_blocks_activation():
    value = payload()
    value["trial_diagnostics"][
        "game_validation_pass_rate"
    ] = 0.999

    result = (
        evaluate_canonical_extras_walkoff_activation(
            canonical_payload=value,
            execution_inputs=inputs(),
        )
    )

    assert result.status == "blocked"
    assert (
        "game_validation_incomplete"
        in result.blockers
    )


def test_incomplete_reconciliation_blocks_activation():
    value = payload()
    value["trial_diagnostics"][
        "box_score_reconciliation_pass_rate"
    ] = 0.99

    result = (
        evaluate_canonical_extras_walkoff_activation(
            canonical_payload=value,
            execution_inputs=inputs(),
        )
    )

    assert result.status == "blocked"
    assert (
        "box_score_reconciliation_incomplete"
        in result.blockers
    )


def test_disabled_extra_innings_blocks_activation():
    result = (
        evaluate_canonical_extras_walkoff_activation(
            canonical_payload=payload(),
            execution_inputs=inputs(
                max_extra_innings=0,
            ),
        )
    )

    assert result.status == "blocked"
    assert (
        "extra_innings_disabled"
        in result.blockers
    )


def test_disabled_automatic_runner_blocks_activation():
    result = (
        evaluate_canonical_extras_walkoff_activation(
            canonical_payload=payload(),
            execution_inputs=inputs(
                automatic_runner_enabled=False,
            ),
        )
    )

    assert result.status == "blocked"
    assert (
        "automatic_runner_disabled"
        in result.blockers
    )


def test_trial_warnings_are_exposed_without_reclassification():
    value = payload()
    value["trial_diagnostics"]["warnings"] = [
        "game_tied_at_extra_innings_cap",
    ]

    result = (
        evaluate_canonical_extras_walkoff_activation(
            canonical_payload=value,
            execution_inputs=inputs(),
        )
    )
    diagnostics = result.to_diagnostics()

    assert result.active is True
    assert diagnostics["trial_warnings"] == [
        "game_tied_at_extra_innings_cap",
    ]
    assert diagnostics[
        "legacy_evidence_status"
    ] == "reference_only_inconclusive"
    assert diagnostics[
        "legacy_candidate_promoted"
    ] is False
    assert diagnostics[
        "parameter_reselection_performed"
    ] is False

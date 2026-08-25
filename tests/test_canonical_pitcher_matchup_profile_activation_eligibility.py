import copy

import pytest

from mlb_app.simulation.shadow.canonical_pitcher_matchup_profile_activation_eligibility import (
    evaluate_canonical_pitcher_matchup_profile_activation_eligibility,
)


DIGEST_A = "a" * 64
DIGEST_B = "b" * 64


def calibration(
    *,
    status="ready",
    activation_status=(
        "candidate_policy_ready"
    ),
    authority_changed=False,
):
    return {
        "diagnostics": {
            "status": status,
            "activation_status": (
                activation_status
            ),
            "calibration_policy_digest": (
                DIGEST_A
            ),
            "production_authority": False,
            "production_authority_changed": (
                authority_changed
            ),
        },
    }


def historical(
    *,
    samples=446,
    observed_pa=1093,
    seasons=3,
    log_loss_improvement=(
        0.001702281887
    ),
    brier_improvement=(
        0.000854666332
    ),
    gate_passed=True,
    activation_status=(
        "historical_pa_gate_passed"
    ),
    regressed_seasons=(),
    production_authority=False,
    production_authority_changed=False,
):
    by_season = {
        str(2024 + index): {
            "status": "ready",
            "sample_count": 100,
            "absolute_log_loss_improvement": (
                0.001
            ),
        }
        for index in range(seasons)
    }

    return {
        "overall": {
            "status": "ready",
            "sample_count": samples,
            "observed_pa": observed_pa,
            "absolute_log_loss_improvement": (
                log_loss_improvement
            ),
            "absolute_brier_improvement": (
                brier_improvement
            ),
        },
        "by_season": by_season,
        "diagnostics": {
            "status": "ready",
            "selection_gate_passed": (
                gate_passed
            ),
            "activation_status": (
                activation_status
            ),
            "regressed_seasons": list(
                regressed_seasons
            ),
            "evaluation_digest": DIGEST_B,
            "production_authority": (
                production_authority
            ),
            "production_authority_changed": (
                production_authority_changed
            ),
        },
    }


def evaluate(
    *,
    calibration_value=None,
    historical_value=None,
    **kwargs,
):
    return (
        evaluate_canonical_pitcher_matchup_profile_activation_eligibility(
            calibration_policy=(
                calibration_value
                if calibration_value
                is not None
                else calibration()
            ),
            historical_evaluation=(
                historical_value
                if historical_value
                is not None
                else historical()
            ),
            **kwargs,
        )
    )


def test_marks_audited_candidate_eligible():
    result = evaluate()
    diagnostics = result["diagnostics"]

    assert result["eligible"] is True
    assert diagnostics["status"] == "ready"
    assert diagnostics[
        "activation_status"
    ] == "candidate_activation_eligible"
    assert diagnostics[
        "activation_eligible"
    ] is True
    assert diagnostics["blockers"] == []
    assert diagnostics[
        "calibration_policy_ready"
    ] is True
    assert diagnostics[
        "historical_pa_gate_passed"
    ] is True


@pytest.mark.parametrize(
    "calibration_value,blocker",
    [
        (
            calibration(status="partial"),
            "calibration_policy_not_ready",
        ),
        (
            calibration(
                activation_status=(
                    "candidate_policy_blocked"
                )
            ),
            "calibration_policy_not_ready",
        ),
        (
            calibration(
                authority_changed=True
            ),
            "calibration_authority_contract_invalid",
        ),
    ],
)
def test_calibration_failures_block(
    calibration_value,
    blocker,
):
    result = evaluate(
        calibration_value=calibration_value
    )

    assert result["eligible"] is False
    assert blocker in result[
        "diagnostics"
    ]["blockers"]


def test_historical_gate_failure_blocks():
    result = evaluate(
        historical_value=historical(
            gate_passed=False,
            activation_status=(
                "historical_pa_gate_blocked"
            ),
        )
    )

    assert result["eligible"] is False
    assert (
        "historical_pa_gate_not_passed"
        in result["diagnostics"]["blockers"]
    )


@pytest.mark.parametrize(
    "historical_value,blocker",
    [
        (
            historical(samples=299),
            "historical_sample_count_below_minimum",
        ),
        (
            historical(observed_pa=899),
            "historical_observed_pa_below_minimum",
        ),
        (
            historical(seasons=2),
            "historical_season_count_below_minimum",
        ),
        (
            historical(
                log_loss_improvement=0.0
            ),
            "absolute_log_loss_improvement_below_minimum",
        ),
        (
            historical(
                brier_improvement=0.0
            ),
            "absolute_brier_improvement_below_minimum",
        ),
        (
            historical(
                regressed_seasons=("2025",)
            ),
            "season_log_loss_instability",
        ),
    ],
)
def test_evidence_thresholds_block(
    historical_value,
    blocker,
):
    result = evaluate(
        historical_value=historical_value
    )

    assert result["eligible"] is False
    assert blocker in result[
        "diagnostics"
    ]["blockers"]


@pytest.mark.parametrize(
    "historical_value",
    [
        historical(
            production_authority=True
        ),
        historical(
            production_authority_changed=True
        ),
    ],
)
def test_historical_authority_violation_blocks(
    historical_value,
):
    result = evaluate(
        historical_value=historical_value
    )

    assert result["eligible"] is False
    assert (
        "historical_authority_contract_invalid"
        in result["diagnostics"]["blockers"]
    )


def test_custom_improvement_thresholds_block():
    result = evaluate(
        minimum_absolute_log_loss_improvement=(
            0.002
        ),
        minimum_absolute_brier_improvement=(
            0.001
        ),
    )

    assert result["eligible"] is False
    assert result["diagnostics"][
        "blockers"
    ] == [
        "absolute_log_loss_improvement_below_minimum",
        "absolute_brier_improvement_below_minimum",
    ]


def test_eligibility_does_not_activate():
    diagnostics = evaluate()["diagnostics"]

    assert diagnostics[
        "eligibility_only"
    ] is True
    assert diagnostics[
        "activation_executed"
    ] is False
    assert diagnostics[
        "production_inputs_unchanged"
    ] is True
    assert diagnostics[
        "production_authority"
    ] is False
    assert diagnostics[
        "production_authority_changed"
    ] is False


def test_evidence_digests_are_preserved():
    diagnostics = evaluate()["diagnostics"]

    assert diagnostics[
        "calibration_policy_digest"
    ] == DIGEST_A
    assert diagnostics[
        "historical_evaluation_digest"
    ] == DIGEST_B
    assert len(
        diagnostics["eligibility_digest"]
    ) == 64


def test_decision_is_deterministic():
    first = evaluate()
    second = evaluate(
        calibration_value={
            "diagnostics": dict(
                reversed(
                    tuple(
                        calibration()[
                            "diagnostics"
                        ].items()
                    )
                )
            ),
        },
        historical_value=historical(),
    )

    assert first["diagnostics"][
        "eligibility_digest"
    ] == second["diagnostics"][
        "eligibility_digest"
    ]


def test_inputs_are_not_mutated():
    calibration_value = calibration()
    historical_value = historical()
    original_calibration = copy.deepcopy(
        calibration_value
    )
    original_historical = copy.deepcopy(
        historical_value
    )

    evaluate(
        calibration_value=calibration_value,
        historical_value=historical_value,
    )

    assert calibration_value == (
        original_calibration
    )
    assert historical_value == (
        original_historical
    )


@pytest.mark.parametrize(
    "kwargs,reason",
    [
        (
            {
                "calibration_policy": None,
                "historical_evaluation": (
                    historical()
                ),
            },
            "calibration_policy_must_be_mapping",
        ),
        (
            {
                "calibration_policy": (
                    calibration()
                ),
                "historical_evaluation": None,
            },
            "historical_evaluation_must_be_mapping",
        ),
        (
            {
                "calibration_policy": (
                    calibration()
                ),
                "historical_evaluation": (
                    historical()
                ),
                "minimum_samples": 0,
            },
            "minimum_samples_must_be_positive_integer",
        ),
        (
            {
                "calibration_policy": (
                    calibration()
                ),
                "historical_evaluation": (
                    historical()
                ),
                "minimum_absolute_log_loss_improvement": -0.1,
            },
            "minimum_absolute_log_loss_improvement_must_be_nonnegative",
        ),
    ],
)
def test_invalid_contracts_raise(
    kwargs,
    reason,
):
    with pytest.raises(
        ValueError,
        match=reason,
    ):
        evaluate_canonical_pitcher_matchup_profile_activation_eligibility(
            **kwargs,
        )

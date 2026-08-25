import copy

import pytest

from mlb_app.simulation.shadow.canonical_pitcher_matchup_profile_pa_activation import (
    APPROVED_CROSS_SEASON_AUDIT_DIGEST,
    APPROVED_ELIGIBILITY_DIGEST,
    APPROVED_HISTORICAL_EVALUATION_DIGEST,
    select_canonical_pitcher_matchup_profile_pa_model,
)


def production():
    return {
        "model_version": "pa_outcome_v1",
        "probabilities": {
            "out": 0.65,
            "single": 0.15,
            "double": 0.05,
            "triple": 0.01,
            "home_run": 0.04,
            "walk": 0.07,
            "strikeout": 0.03,
        },
        "metadata": {
            "source": "existing_production",
        },
    }


def shadow_probabilities():
    return {
        "out": 0.64,
        "single": 0.15,
        "double": 0.05,
        "triple": 0.01,
        "home_run": 0.04,
        "walk": 0.07,
        "strikeout": 0.04,
    }


def comparison(
    *,
    status="ready",
    executed=True,
    probabilities=None,
    inputs_unchanged=True,
    authority_changed=False,
):
    return {
        "status": status,
        "executed": executed,
        "shadow_model_version": (
            "pa_outcome_v1"
        ),
        "production_probabilities": (
            production()["probabilities"]
        ),
        "shadow_probabilities": (
            shadow_probabilities()
            if probabilities is None
            else probabilities
        ),
        "production_inputs_unchanged": (
            inputs_unchanged
        ),
        "production_authority": False,
        "production_authority_changed": (
            authority_changed
        ),
    }


def select(
    *,
    production_value=None,
    comparison_value=None,
    requested=True,
    eligibility_digest=(
        APPROVED_ELIGIBILITY_DIGEST
    ),
    evaluation_digest=(
        APPROVED_HISTORICAL_EVALUATION_DIGEST
    ),
    audit_digest=(
        APPROVED_CROSS_SEASON_AUDIT_DIGEST
    ),
):
    return (
        select_canonical_pitcher_matchup_profile_pa_model(
            production_model=(
                production()
                if production_value is None
                else production_value
            ),
            comparison=(
                comparison()
                if comparison_value is None
                else comparison_value
            ),
            activation_requested=requested,
            eligibility_digest=(
                eligibility_digest
            ),
            historical_evaluation_digest=(
                evaluation_digest
            ),
            cross_season_audit_digest=(
                audit_digest
            ),
        )
    )


def test_activation_selects_audited_candidate():
    result = select()
    diagnostics = result["diagnostics"]

    assert result["activated"] is True
    assert result["model"][
        "probabilities"
    ] == shadow_probabilities()
    assert diagnostics["status"] == "activated"
    assert diagnostics[
        "activation_status"
    ] == "production_candidate_activated"
    assert diagnostics[
        "selected_probability_source"
    ] == (
        "audited_canonical_pitcher_matchup_profile"
    )
    assert diagnostics["blockers"] == []


def test_active_model_carries_evidence():
    result = select()
    evidence = result["model"][
        "pitcher_matchup_profile_activation"
    ]

    assert evidence[
        "eligibility_digest"
    ] == APPROVED_ELIGIBILITY_DIGEST
    assert evidence[
        "historical_evaluation_digest"
    ] == (
        APPROVED_HISTORICAL_EVALUATION_DIGEST
    )
    assert evidence[
        "cross_season_audit_digest"
    ] == APPROVED_CROSS_SEASON_AUDIT_DIGEST


def test_inactive_request_preserves_production():
    original = production()
    result = select(
        production_value=original,
        requested=False,
    )
    diagnostics = result["diagnostics"]

    assert result["activated"] is False
    assert result["model"] == original
    assert diagnostics["status"] == "inactive"
    assert diagnostics[
        "activation_status"
    ] == "production_activation_not_requested"
    assert diagnostics[
        "selected_probability_source"
    ] == "existing_production_pa_model"
    assert diagnostics[
        "production_inputs_unchanged"
    ] is True
    assert diagnostics[
        "production_authority_changed"
    ] is False


@pytest.mark.parametrize(
    "kwargs,blocker",
    [
        (
            {
                "eligibility_digest": (
                    "0" * 64
                ),
            },
            "eligibility_digest_not_approved",
        ),
        (
            {
                "evaluation_digest": (
                    "0" * 64
                ),
            },
            "historical_evaluation_digest_not_approved",
        ),
        (
            {
                "audit_digest": "0" * 64,
            },
            "cross_season_audit_digest_not_approved",
        ),
    ],
)
def test_stale_evidence_fails_closed(
    kwargs,
    blocker,
):
    result = select(**kwargs)

    assert result["activated"] is False
    assert result["model"] == production()
    assert blocker in result[
        "diagnostics"
    ]["blockers"]


@pytest.mark.parametrize(
    "comparison_value,blocker",
    [
        (
            comparison(status="partial"),
            "candidate_comparison_not_ready",
        ),
        (
            comparison(executed=False),
            "candidate_comparison_not_executed",
        ),
        (
            comparison(
                inputs_unchanged=False
            ),
            "comparison_authority_contract_invalid",
        ),
        (
            comparison(
                authority_changed=True
            ),
            "comparison_authority_contract_invalid",
        ),
        (
            comparison(probabilities={}),
            "candidate_probabilities_invalid",
        ),
        (
            comparison(
                probabilities={
                    "out": 0.9,
                    "single": 0.2,
                }
            ),
            "candidate_probabilities_invalid",
        ),
    ],
)
def test_invalid_comparison_fails_closed(
    comparison_value,
    blocker,
):
    result = select(
        comparison_value=comparison_value
    )

    assert result["activated"] is False
    assert result["model"] == production()
    assert blocker in result[
        "diagnostics"
    ]["blockers"]


def test_candidate_keys_must_match_production():
    values = shadow_probabilities()
    values.pop("strikeout")
    values["field_error"] = 0.04

    result = select(
        comparison_value=comparison(
            probabilities=values
        )
    )

    assert result["activated"] is False
    assert (
        "candidate_outcome_keys_mismatch"
        in result["diagnostics"]["blockers"]
    )


@pytest.mark.parametrize(
    "probabilities",
    [
        {},
        {"out": 1.1},
        {"out": float("nan")},
        {"out": True},
    ],
)
def test_invalid_production_fails_closed(
    probabilities,
):
    value = production()
    value["probabilities"] = probabilities

    result = select(
        production_value=value
    )

    assert result["activated"] is False
    assert (
        "production_probabilities_invalid"
        in result["diagnostics"]["blockers"]
    )


def test_activation_authority_is_explicit():
    diagnostics = select()["diagnostics"]

    assert diagnostics["fail_closed"] is True
    assert diagnostics[
        "activation_requested"
    ] is True
    assert diagnostics[
        "activation_executed"
    ] is True
    assert diagnostics[
        "production_inputs_unchanged"
    ] is False
    assert diagnostics[
        "production_authority"
    ] is True
    assert diagnostics[
        "production_authority_changed"
    ] is True


def test_selector_is_nonmutating():
    production_value = production()
    comparison_value = comparison()
    original_production = copy.deepcopy(
        production_value
    )
    original_comparison = copy.deepcopy(
        comparison_value
    )

    select(
        production_value=production_value,
        comparison_value=comparison_value,
    )

    assert production_value == (
        original_production
    )
    assert comparison_value == (
        original_comparison
    )


def test_selector_is_deterministic():
    first = select()
    second = select(
        production_value=dict(
            reversed(
                tuple(
                    production().items()
                )
            )
        ),
    )

    assert first["diagnostics"][
        "activation_digest"
    ] == second["diagnostics"][
        "activation_digest"
    ]


def test_activation_request_must_be_boolean():
    with pytest.raises(
        ValueError,
        match=(
            "activation_requested_must_be_boolean"
        ),
    ):
        select_canonical_pitcher_matchup_profile_pa_model(
            production_model=production(),
            comparison=comparison(),
            activation_requested=1,
            eligibility_digest=(
                APPROVED_ELIGIBILITY_DIGEST
            ),
            historical_evaluation_digest=(
                APPROVED_HISTORICAL_EVALUATION_DIGEST
            ),
            cross_season_audit_digest=(
                APPROVED_CROSS_SEASON_AUDIT_DIGEST
            ),
        )

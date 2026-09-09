from __future__ import annotations

from mlb_app.simulation.shadow import (
    DEFAULT_PRODUCTION_SHADOW_SIMULATION_COUNT,
)


def test_initial_production_shadow_batch_is_small():
    assert (
        DEFAULT_PRODUCTION_SHADOW_SIMULATION_COUNT
        == 25
    )


def test_initial_execution_does_not_replace_legacy():
    expected_contract = {
        "activation_permitted": False,
        "production_authority_changed": False,
        "authoritative_source": "legacy",
    }

    assert expected_contract[
        "activation_permitted"
    ] is False
    assert expected_contract[
        "production_authority_changed"
    ] is False
    assert expected_contract[
        "authoritative_source"
    ] == "legacy"


def test_baserunning_fail_open_constructor_matches_contract():
    import inspect

    from mlb_app.simulation.shadow import (
        CanonicalShadowBaserunningEvidenceDiscovery,
    )

    parameters = inspect.signature(
        CanonicalShadowBaserunningEvidenceDiscovery
    ).parameters

    assert "error_message" in parameters
    assert "error_type" not in parameters

    failure = (
        CanonicalShadowBaserunningEvidenceDiscovery(
            status="error",
            error_message="production prior unavailable",
        )
    )

    assert failure.status == "error"
    assert (
        failure.error_message
        == "production prior unavailable"
    )
    assert failure.ready is False



def test_production_policy_controls_both_execution_paths():
    import inspect

    from mlb_app.model_projections import (
        build_model_projection_payload,
    )

    source = inspect.getsource(
        build_model_projection_payload
    )
    policy_position = source.index(
        "canonical_production_trial_policy ="
    )
    fallback_position = source.index(
        "canonical_legacy_fallback_execution ="
    )
    paired_position = source.index(
        "canonical_live_baserunning_pair ="
    )

    assert policy_position < fallback_position
    assert fallback_position < paired_position

    shared_count_argument = (
        "simulation_count=(\n"
        "                        "
        "canonical_production_trial_policy\n"
        "                        .simulation_count\n"
        "                    )"
    )
    assert source.count(shared_count_argument) == 2

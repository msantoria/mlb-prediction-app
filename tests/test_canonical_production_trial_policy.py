import pytest

from mlb_app.simulation.shadow import (
    CANONICAL_PRODUCTION_SIMULATION_COUNT_ENV,
    CANONICAL_PRODUCTION_TRIAL_POLICY_VERSION,
    DEFAULT_CANONICAL_PRODUCTION_SIMULATION_COUNT,
    CanonicalProductionTrialPolicy,
    build_canonical_production_trial_policy,
)


def test_default_production_count_is_stable(
    monkeypatch,
):
    monkeypatch.delenv(
        CANONICAL_PRODUCTION_SIMULATION_COUNT_ENV,
        raising=False,
    )

    policy = build_canonical_production_trial_policy()

    assert policy.simulation_count == 1000
    assert (
        policy.simulation_count
        == DEFAULT_CANONICAL_PRODUCTION_SIMULATION_COUNT
    )
    assert (
        policy.policy_version
        == CANONICAL_PRODUCTION_TRIAL_POLICY_VERSION
    )
    assert (
        policy.to_diagnostics()[
            "configured_from_environment"
        ]
        is False
    )


def test_environment_can_override_production_count(
    monkeypatch,
):
    monkeypatch.setenv(
        CANONICAL_PRODUCTION_SIMULATION_COUNT_ENV,
        "250",
    )

    policy = build_canonical_production_trial_policy()

    assert policy.simulation_count == 250
    assert (
        policy.to_diagnostics()[
            "configured_from_environment"
        ]
        is True
    )


@pytest.mark.parametrize(
    "value",
    (
        "24",
        "10001",
        "not-an-integer",
        "100.5",
        True,
    ),
)
def test_invalid_production_count_is_rejected(
    value,
):
    with pytest.raises(
        ValueError,
        match="simulation count|simulation_count",
    ):
        build_canonical_production_trial_policy(
            value
        )


def test_policy_is_deterministic():
    first = CanonicalProductionTrialPolicy(
        simulation_count=250
    )
    second = CanonicalProductionTrialPolicy(
        simulation_count=250
    )

    assert first == second
    assert (
        first.to_diagnostics()
        == second.to_diagnostics()
    )


def test_version_is_explicit():
    assert (
        CANONICAL_PRODUCTION_TRIAL_POLICY_VERSION
        == "canonical_production_trial_policy_v2"
    )



def test_default_provides_one_thousand_trial_resolution(
    monkeypatch,
):
    monkeypatch.delenv(
        CANONICAL_PRODUCTION_SIMULATION_COUNT_ENV,
        raising=False,
    )

    policy = build_canonical_production_trial_policy()
    diagnostics = policy.to_diagnostics()

    assert policy.simulation_count == 1000
    assert 1 / policy.simulation_count == 0.001
    assert diagnostics[
        "default_simulation_count"
    ] == 1000

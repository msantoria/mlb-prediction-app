import pytest

from mlb_app.simulation.game import (
    CanonicalDefensiveEventAuthorityRecord,
    aggregate_canonical_defensive_event_authority,
)
from mlb_app.simulation.shadow.defensive_distribution_backtest import (
    CANONICAL_DEFENSIVE_DISTRIBUTION_BACKTEST_VERSION,
    CanonicalObservedDefensiveDistribution,
    backtest_canonical_defensive_distribution,
)


def record(
    *,
    applied,
    original,
    final,
    blocker=None,
):
    return CanonicalDefensiveEventAuthorityRecord(
        applied=applied,
        authoritative=applied,
        original_event_type=original,
        final_event_type=final,
        blocker=blocker,
    )


def simulation_summary():
    return aggregate_canonical_defensive_event_authority(
        (
            record(
                applied=True,
                original="single",
                final="out",
            ),
            record(
                applied=True,
                original="out",
                final="double",
            ),
            record(
                applied=False,
                original="single",
                final="single",
                blocker="defensive_outcome_unchanged",
            ),
            record(
                applied=False,
                original="double",
                final="double",
                blocker="defensive_reconciliation_blocked",
            ),
        )
    )


def observed_distribution():
    return CanonicalObservedDefensiveDistribution(
        source_identifier="statcast:2026-08-01:2026-08-31",
        observation_count=4,
        final_event_type_counts=(
            ("double", 1),
            ("out", 2),
            ("single", 1),
        ),
    )


def test_backtest_compares_union_of_final_event_types():
    result = backtest_canonical_defensive_distribution(
        summary=simulation_summary(),
        observed=observed_distribution(),
    )

    assert result.ready is True
    assert result.status == "ready"
    assert result.simulation_observation_count == 4
    assert result.observed_observation_count == 4
    assert dict(
        result.simulated_final_event_type_rates
    ) == {
        "double": 0.5,
        "out": 0.25,
        "single": 0.25,
    }
    assert dict(
        result.observed_final_event_type_rates
    ) == {
        "double": 0.25,
        "out": 0.5,
        "single": 0.25,
    }
    assert dict(
        result.final_event_type_rate_deltas
    ) == {
        "double": 0.25,
        "out": -0.25,
        "single": 0.0,
    }
    assert result.total_variation_distance == 0.25
    assert result.maximum_absolute_rate_delta == 0.25


def test_backtest_zero_fills_categories_on_only_one_side():
    observed = CanonicalObservedDefensiveDistribution(
        source_identifier="fixture:union-categories",
        observation_count=5,
        final_event_type_counts=(
            ("out", 4),
            ("triple", 1),
        ),
    )

    result = backtest_canonical_defensive_distribution(
        summary=simulation_summary(),
        observed=observed,
    )

    assert dict(
        result.simulated_final_event_type_rates
    ) == {
        "double": 0.5,
        "out": 0.25,
        "single": 0.25,
        "triple": 0.0,
    }
    assert dict(
        result.observed_final_event_type_rates
    ) == {
        "double": 0.0,
        "out": 0.8,
        "single": 0.0,
        "triple": 0.2,
    }
    assert dict(
        result.final_event_type_rate_deltas
    ) == {
        "double": 0.5,
        "out": -0.55,
        "single": 0.25,
        "triple": -0.2,
    }
    assert result.total_variation_distance == 0.75
    assert result.maximum_absolute_rate_delta == 0.55


def test_backtest_preserves_internal_transition_measurement():
    result = backtest_canonical_defensive_distribution(
        summary=simulation_summary(),
        observed=observed_distribution(),
    )

    assert result.authority_rate == 0.5
    assert result.event_transition_rates == (
        ("double", "double", 1.0),
        ("out", "double", 1.0),
        ("single", "out", 0.5),
        ("single", "single", 0.5),
    )
    assert dict(result.blocker_counts) == {
        "defensive_outcome_unchanged": 1,
        "defensive_reconciliation_blocked": 1,
    }


def test_backtest_diagnostics_are_measurement_only():
    result = backtest_canonical_defensive_distribution(
        summary=simulation_summary(),
        observed=observed_distribution(),
    )

    diagnostics = result.to_diagnostics()

    assert diagnostics["schema_version"] == (
        CANONICAL_DEFENSIVE_DISTRIBUTION_BACKTEST_VERSION
    )
    assert diagnostics["measurement_only"] is True
    assert diagnostics["activation_permitted"] is False
    assert (
        diagnostics["production_authority_changed"]
        is False
    )
    assert diagnostics["event_transition_rates"] == {
        "double": {"double": 1.0},
        "out": {"double": 1.0},
        "single": {
            "out": 0.5,
            "single": 0.5,
        },
    }
    assert len(diagnostics["input_digest"]) == 64


def test_backtest_digest_is_deterministic():
    first = backtest_canonical_defensive_distribution(
        summary=simulation_summary(),
        observed=observed_distribution(),
    )
    second = backtest_canonical_defensive_distribution(
        summary=simulation_summary(),
        observed=observed_distribution(),
    )

    assert first.input_digest == second.input_digest


def test_empty_simulation_is_explicitly_unavailable():
    empty = aggregate_canonical_defensive_event_authority(
        ()
    )

    result = backtest_canonical_defensive_distribution(
        summary=empty,
        observed=observed_distribution(),
    )

    assert result.ready is False
    assert result.status == "unavailable"
    assert result.blocker == "simulation_distribution_empty"
    assert result.input_digest == ""


@pytest.mark.parametrize(
    "counts,total,error",
    [
        (
            (("single", 1), ("out", 1)),
            2,
            "must be sorted",
        ),
        (
            (("out", 1),),
            2,
            "must reconcile",
        ),
        (
            (("out", 0),),
            0,
            "must be positive",
        ),
    ],
)
def test_observed_distribution_rejects_invalid_counts(
    counts,
    total,
    error,
):
    with pytest.raises(ValueError, match=error):
        CanonicalObservedDefensiveDistribution(
            source_identifier="fixture",
            observation_count=total,
            final_event_type_counts=counts,
        )


def test_observed_distribution_requires_source_identity():
    with pytest.raises(
        ValueError,
        match="source_identifier",
    ):
        CanonicalObservedDefensiveDistribution(
            source_identifier=" ",
            observation_count=1,
            final_event_type_counts=(
                ("out", 1),
            ),
        )


def test_backtest_rejects_noncanonical_inputs():
    with pytest.raises(TypeError, match="summary"):
        backtest_canonical_defensive_distribution(
            summary={},
            observed=observed_distribution(),
        )

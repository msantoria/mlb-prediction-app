from dataclasses import replace

import pytest

from mlb_app.simulation.projections.aggregator import (
    summarize_values,
)
from mlb_app.simulation.shadow.production_run_environment import (
    CanonicalProductionRunEnvironment,
)
from mlb_app.simulation.shadow.observed_run_environment_source import (
    CanonicalObservedRunEnvironment,
)
from mlb_app.simulation.shadow.production_run_environment_backtest import (
    CanonicalProductionRunEnvironmentBacktest,
    backtest_canonical_production_run_environment,
)


DIGEST_A = "a" * 64
DIGEST_B = "b" * 64


def metric_means(
    *,
    at_bats,
    hits,
    singles,
    doubles,
    triples,
    home_runs,
    walks,
    hit_by_pitch,
    strikeouts,
    stolen_bases,
    caught_stealing,
    left_on_base,
    errors,
    runs,
):
    values = {
        "at_bats_per_game": at_bats,
        "hits_per_game": hits,
        "singles_per_game": singles,
        "doubles_per_game": doubles,
        "triples_per_game": triples,
        "home_runs_per_game": home_runs,
        "walks_per_game": walks,
        "hit_by_pitch_per_game": hit_by_pitch,
        "strikeouts_per_game": strikeouts,
        "stolen_bases_per_game": stolen_bases,
        "caught_stealing_per_game": caught_stealing,
        "left_on_base_per_game": left_on_base,
        "errors_per_game": errors,
        "runs_per_game": runs,
    }
    return tuple(sorted(values.items()))


def production(*, high=False):
    if high:
        totals = (10, 12)
        metrics = metric_means(
            at_bats=66,
            hits=18,
            singles=11,
            doubles=4,
            triples=1,
            home_runs=2,
            walks=8,
            hit_by_pitch=1,
            strikeouts=14,
            stolen_bases=1.2,
            caught_stealing=0.2,
            left_on_base=15,
            errors=1,
            runs=11,
        )
        thresholds = (
            ("away_shutout_rate", 0.0),
            ("home_shutout_rate", 0.0),
            ("total_runs_5_or_fewer_rate", 0.0),
            ("total_runs_6_or_fewer_rate", 0.0),
            ("total_runs_7_or_fewer_rate", 0.0),
            ("total_runs_8_or_fewer_rate", 0.0),
            ("total_runs_9_or_more_rate", 1.0),
        )
    else:
        totals = (4, 6)
        metrics = metric_means(
            at_bats=60,
            hits=12,
            singles=8,
            doubles=2.5,
            triples=0.7,
            home_runs=0.8,
            walks=5,
            hit_by_pitch=1,
            strikeouts=17,
            stolen_bases=0.8,
            caught_stealing=0.4,
            left_on_base=12,
            errors=1,
            runs=5,
        )
        thresholds = (
            ("away_shutout_rate", 0.0),
            ("home_shutout_rate", 0.0),
            ("total_runs_5_or_fewer_rate", 0.5),
            ("total_runs_6_or_fewer_rate", 1.0),
            ("total_runs_7_or_fewer_rate", 1.0),
            ("total_runs_8_or_fewer_rate", 1.0),
            ("total_runs_9_or_more_rate", 0.0),
        )
    return CanonicalProductionRunEnvironment(
        simulation_count=2,
        away_runs=summarize_values(
            tuple(value / 2 for value in totals)
        ),
        home_runs=summarize_values(
            tuple(value / 2 for value in totals)
        ),
        total_runs=summarize_values(totals),
        box_score_metric_means=metrics,
        scoring_rates=(),
        total_threshold_rates=thresholds,
        probability_tier_counts=(),
        probability_resolution_count=0,
        probability_fallback_rate=0.0,
        defensive_authority_observation_count=0,
        defensive_authority_rate=0.0,
        box_score_run_mismatch_count=0,
        artifact_digest=DIGEST_A,
    )


def observed():
    totals = (8, 10)
    return CanonicalObservedRunEnvironment(
        source_identifier=(
            "final_game_snapshots:2026-08-01:2026-08-31:test"
        ),
        window_start="2026-08-01",
        window_end="2026-08-31",
        through_date="2026-09-01",
        game_count=2,
        away_runs=summarize_values((4, 5)),
        home_runs=summarize_values((4, 5)),
        total_runs=summarize_values(totals),
        box_score_metric_means=metric_means(
            at_bats=64,
            hits=16,
            singles=10,
            doubles=3.5,
            triples=0.5,
            home_runs=2,
            walks=7,
            hit_by_pitch=1,
            strikeouts=16,
            stolen_bases=1,
            caught_stealing=0.3,
            left_on_base=14,
            errors=1,
            runs=9,
        ),
        scoring_rates=(),
        total_threshold_rates=(
            ("away_shutout_rate", 0.0),
            ("home_shutout_rate", 0.0),
            ("total_runs_5_or_fewer_rate", 0.0),
            ("total_runs_6_or_fewer_rate", 0.0),
            ("total_runs_7_or_fewer_rate", 0.0),
            ("total_runs_8_or_fewer_rate", 0.5),
            ("total_runs_9_or_more_rate", 0.5),
        ),
        snapshot_version_counts=(("1", 2),),
        query_row_count=2,
        excluded_snapshot_count=0,
        query_digest="c" * 64,
        artifact_digest=DIGEST_B,
    )


def backtest(*, high=False):
    return backtest_canonical_production_run_environment(
        production(high=high),
        observed(),
    )


def test_backtest_detects_low_total_environment():
    result = backtest()

    assert isinstance(
        result,
        CanonicalProductionRunEnvironmentBacktest,
    )
    assert result.simulation_count == 2
    assert result.observed_game_count == 2
    assert result.total_run_mean_delta == -4.0
    assert result.total_run_mean_relative_delta == -0.444444
    assert result.low_total_signal is True
    assert result.largest_negative_component == "power"
    assert len(result.artifact_digest) == 64


def test_backtest_normalizes_to_observed_opportunity_boundary():
    result = backtest()
    deltas = dict(result.comparable_metric_deltas)
    relative = dict(result.comparable_metric_relative_deltas)

    assert deltas["observed_opportunities_per_game"] == -6.0
    assert deltas["known_reaches_per_game"] == -6.0
    assert "plate_appearances_per_game" not in deltas
    assert "reached_on_error_per_game" not in deltas
    assert relative[
        "home_run_rate_per_observed_opportunity"
    ] < 0.0


def test_backtest_reports_distribution_and_threshold_deltas():
    result = backtest()
    distribution = dict(result.run_distribution_deltas)
    thresholds = dict(result.threshold_rate_deltas)

    assert distribution["mean"] == -4.0
    assert distribution["median"] == -4.0
    assert distribution["p90"] < 0.0
    assert thresholds["total_runs_6_or_fewer_rate"] == 1.0
    assert thresholds["total_runs_9_or_more_rate"] == -0.5


def test_backtest_without_low_total_signal_has_no_negative_component():
    result = backtest(high=True)

    assert result.total_run_mean_delta == 2.0
    assert result.low_total_signal is False
    assert result.largest_negative_component is None


def test_backtest_is_deterministic_and_measurement_only():
    first = backtest()
    second = backtest()

    assert first == second
    assert first.artifact_digest == second.artifact_digest

    diagnostics = first.to_diagnostics()
    assert diagnostics["comparison_convention"] == (
        "simulation_minus_observed"
    )
    assert diagnostics["opportunity_boundary"] == (
        "at_bats_plus_walks_plus_hbp"
    )
    assert diagnostics["causal_claim_permitted"] is False
    assert diagnostics["measurement_only"] is True
    assert diagnostics["calibration_parameters_selected"] is False
    assert diagnostics["activation_permitted"] is False
    assert diagnostics["production_authority_changed"] is False


def test_backtest_rejects_invalid_inputs_and_artifact():
    with pytest.raises(TypeError, match="production"):
        backtest_canonical_production_run_environment(
            object(),
            observed(),
        )
    with pytest.raises(TypeError, match="observed"):
        backtest_canonical_production_run_environment(
            production(),
            object(),
        )

    valid = backtest()
    with pytest.raises(ValueError, match="artifact_digest"):
        replace(valid, artifact_digest="invalid")

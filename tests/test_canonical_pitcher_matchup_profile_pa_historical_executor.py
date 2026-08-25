from __future__ import annotations

from copy import deepcopy

import pytest

from mlb_app.simulation.shadow.canonical_pitcher_matchup_profile_pa_historical_executor import (
    execute_canonical_pitcher_matchup_profile_pa_historical_evaluation,
)
from mlb_app.simulation.shadow.historical_probability_statistics_source import (
    HITTING_STAT_KEYS,
    PITCHING_STAT_KEYS,
    CanonicalHistoricalProbabilityGameStatistics,
    CanonicalHistoricalProbabilityPlayerStatistics,
    CanonicalHistoricalProbabilityStatisticsWindow,
)


DIGEST_A = "a" * 64
DIGEST_B = "b" * 64
DIGEST_C = "c" * 64
DIGEST_D = "d" * 64


def counts(keys, values):
    return tuple(
        (
            key,
            int(values.get(key, 0)),
        )
        for key, _ in keys
    )


def statistics():
    hitter = (
        CanonicalHistoricalProbabilityPlayerStatistics(
            player_id="201",
            role="hitting",
            counts=counts(
                HITTING_STAT_KEYS,
                {
                    "pa": 100,
                    "ab": 80,
                    "hits": 24,
                    "double": 6,
                    "triple": 2,
                    "hr": 4,
                    "bb": 10,
                    "k": 20,
                    "hbp": 2,
                },
            ),
            sample_available=True,
        )
    )
    pitcher = (
        CanonicalHistoricalProbabilityPlayerStatistics(
            player_id="101",
            role="pitching",
            counts=counts(
                PITCHING_STAT_KEYS,
                {
                    "batters_faced": 120,
                    "ab": 100,
                    "hits": 25,
                    "double": 5,
                    "triple": 1,
                    "hr": 3,
                    "bb": 12,
                    "k": 30,
                    "hbp": 2,
                },
            ),
            sample_available=True,
        )
    )
    game = (
        CanonicalHistoricalProbabilityGameStatistics(
            game_pk=700001,
            game_date="2025-07-01",
            statistics_through_date=(
                "2025-06-30"
            ),
            players=(
                hitter,
                pitcher,
            ),
            snapshot_digest=DIGEST_D,
        )
    )

    return (
        CanonicalHistoricalProbabilityStatisticsWindow(
            observed_window_digest=DIGEST_A,
            lineup_bullpen_window_digest=(
                DIGEST_B
            ),
            games=(game,),
            digest=DIGEST_C,
        )
    )


def candidate():
    return {
        "profile_rates": {
            "k_rate": 0.35,
            "barrel_rate_allowed_approx": 0.08,
            "hard_hit_rate_allowed": 0.4,
        },
        "diagnostics": {
            "status": "ready",
            "production_authority": False,
            "production_authority_changed": False,
        },
    }


def events():
    return [
        {
            "game_pk": 700001,
            "game_date": "2025-07-01",
            "at_bat_number": 1,
            "pitcher_id": 101,
            "batter_id": 201,
            "events": "single",
        },
        {
            "game_pk": 700001,
            "game_date": "2025-07-01",
            "at_bat_number": 2,
            "pitcher_id": 101,
            "batter_id": 201,
            "events": "strikeout",
        },
    ]


def execute(
    source=None,
    candidates=None,
    **overrides,
):
    values = {
        "statistics": statistics(),
        "candidates_by_game_pitcher": (
            {
                (700001, 101): candidate(),
            }
            if candidates is None
            else candidates
        ),
        "minimum_samples": 1,
        "minimum_observed_pa": 1,
    }
    values.update(overrides)

    return (
        execute_canonical_pitcher_matchup_profile_pa_historical_evaluation(
            events() if source is None else source,
            **values,
        )
    )


def test_executes_complete_historical_pipeline():
    result = execute()
    diagnostics = result["diagnostics"]

    assert diagnostics["status"] == "ready"
    assert diagnostics["raw_event_count"] == 2
    assert diagnostics["terminal_pa_count"] == 2
    assert diagnostics["outcome_sample_count"] == 1
    assert diagnostics["paired_sample_count"] == 1
    assert diagnostics["accepted_sample_count"] == 1
    assert diagnostics["observed_pa"] == 2

    assert result["outcomes"][
        "diagnostics"
    ]["status"] == "ready"
    assert result["paired_samples"][
        "diagnostics"
    ]["status"] == "ready"


def test_executes_historical_evaluator():
    result = execute()
    evaluation = result["evaluation"]

    assert evaluation["diagnostics"][
        "accepted_sample_count"
    ] == 1
    assert evaluation["diagnostics"][
        "rejected_sample_count"
    ] == 0
    assert evaluation["overall"][
        "observed_pa"
    ] == 2
    assert evaluation["overall"][
        "production_log_loss"
    ] >= 0.0
    assert evaluation["overall"][
        "candidate_log_loss"
    ] >= 0.0
    assert evaluation["overall"][
        "absolute_log_loss_improvement"
    ] > 0.0
    assert evaluation["diagnostics"][
        "activation_status"
    ] == "historical_pa_gate_passed"


def test_partial_outcome_evidence_remains_partial():
    source = events()
    source.append({
        "game_pk": 700001,
        "game_date": "2025-07-01",
        "at_bat_number": 3,
        "pitcher_id": 101,
        "batter_id": 201,
        "events": "catcher_interf",
    })

    result = execute(source=source)

    assert result["outcomes"][
        "diagnostics"
    ]["status"] == "partial"
    assert result["diagnostics"][
        "accepted_sample_count"
    ] == 1
    assert result["diagnostics"][
        "status"
    ] == "partial"


def test_empty_evidence_is_unavailable():
    result = execute(source=[])

    assert result["diagnostics"][
        "status"
    ] == "unavailable"
    assert result["diagnostics"][
        "accepted_sample_count"
    ] == 0
    assert result["diagnostics"][
        "blockers"
    ] == [
        "no_evaluator_ready_historical_samples"
    ]


def test_missing_candidate_is_unavailable():
    result = execute(
        candidates={}
    )

    assert result["paired_samples"][
        "diagnostics"
    ]["status"] == "unavailable"
    assert result["diagnostics"][
        "status"
    ] == "unavailable"
    assert result["diagnostics"][
        "accepted_sample_count"
    ] == 0


def test_authority_contracts_all_pass():
    result = execute()
    diagnostics = result["diagnostics"]

    assert diagnostics[
        "authority_contracts"
    ] == {
        "outcomes": True,
        "paired_samples": True,
        "evaluation": True,
    }
    assert diagnostics["shadow_only"] is True
    assert diagnostics[
        "production_inputs_unchanged"
    ] is True
    assert diagnostics[
        "production_authority"
    ] is False
    assert diagnostics[
        "production_authority_changed"
    ] is False
    assert diagnostics[
        "database_accessed"
    ] is False
    assert diagnostics[
        "calibration_parameters_selected"
    ] is False


def test_execution_is_deterministic():
    first = execute()
    second = execute(
        source=list(
            reversed(events())
        )
    )

    assert first["outcomes"]["samples"] == (
        second["outcomes"]["samples"]
    )
    assert first["paired_samples"][
        "samples"
    ] == second["paired_samples"]["samples"]
    assert first["evaluation"]["overall"] == (
        second["evaluation"]["overall"]
    )
    assert first["diagnostics"][
        "execution_digest"
    ] == second["diagnostics"][
        "execution_digest"
    ]


def test_inputs_are_not_mutated():
    source = events()
    stats = statistics()
    candidates = {
        (700001, 101): candidate(),
    }
    original_source = deepcopy(source)
    original_candidates = deepcopy(
        candidates
    )

    execute_canonical_pitcher_matchup_profile_pa_historical_evaluation(
        source,
        statistics=stats,
        candidates_by_game_pitcher=(
            candidates
        ),
        minimum_samples=1,
        minimum_observed_pa=1,
    )

    assert source == original_source
    assert candidates == original_candidates


@pytest.mark.parametrize(
    "name,value",
    [
        ("minimum_samples", 0),
        ("minimum_observed_pa", 0),
        (
            "season_log_loss_regression_tolerance",
            -0.1,
        ),
    ],
)
def test_evaluation_threshold_validation_is_preserved(
    name,
    value,
):
    with pytest.raises(ValueError):
        execute(**{name: value})


def test_pipeline_and_cutoff_contracts_are_explicit():
    diagnostics = execute()["diagnostics"]

    assert diagnostics["pipeline"] == (
        "terminal_outcomes_to_paired_samples_to_evaluation"
    )
    assert diagnostics["cutoff_policy"] == (
        "statistics_and_candidates_supplied_as_pregame_inputs"
    )
    assert diagnostics["outcome_digest"]
    assert diagnostics["sample_digest"]
    assert diagnostics["evaluation_digest"]

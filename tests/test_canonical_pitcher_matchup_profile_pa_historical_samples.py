from __future__ import annotations

from copy import deepcopy

import pytest

from mlb_app.simulation.shadow.canonical_pitcher_matchup_profile_pa_historical_evaluation import (
    evaluate_canonical_pitcher_matchup_profile_pa_history,
)
from mlb_app.simulation.shadow.canonical_pitcher_matchup_profile_pa_historical_outcomes import (
    materialize_canonical_pitcher_matchup_profile_pa_historical_outcomes,
)
from mlb_app.simulation.shadow.canonical_pitcher_matchup_profile_pa_historical_samples import (
    materialize_canonical_pitcher_matchup_profile_pa_historical_samples,
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


def hitter(
    player_id="201",
    *,
    sample_available=True,
):
    values = {
        "pa": 100,
        "ab": 80,
        "hits": 24,
        "double": 6,
        "triple": 2,
        "hr": 4,
        "bb": 10,
        "k": 20,
        "hbp": 2,
    }

    if not sample_available:
        values = {}

    return (
        CanonicalHistoricalProbabilityPlayerStatistics(
            player_id=player_id,
            role="hitting",
            counts=counts(
                HITTING_STAT_KEYS,
                values,
            ),
            sample_available=sample_available,
        )
    )


def pitcher(
    player_id="101",
    *,
    sample_available=True,
):
    values = {
        "batters_faced": 120,
        "ab": 100,
        "hits": 25,
        "double": 5,
        "triple": 1,
        "hr": 3,
        "bb": 12,
        "k": 30,
        "hbp": 2,
    }

    if not sample_available:
        values = {}

    return (
        CanonicalHistoricalProbabilityPlayerStatistics(
            player_id=player_id,
            role="pitching",
            counts=counts(
                PITCHING_STAT_KEYS,
                values,
            ),
            sample_available=sample_available,
        )
    )


def statistics(
    *,
    players=None,
    game_date="2025-07-01",
):
    if players is None:
        players = (
            hitter(),
            pitcher(),
        )

    game = (
        CanonicalHistoricalProbabilityGameStatistics(
            game_pk=700001,
            game_date=game_date,
            statistics_through_date=(
                "2025-06-30"
            ),
            players=tuple(players),
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


def candidate(
    *,
    status="ready",
    production_authority=False,
    production_authority_changed=False,
):
    return {
        "profile_rates": {
            "k_rate": 0.35,
            "barrel_rate_allowed_approx": 0.08,
            "hard_hit_rate_allowed": 0.40,
        },
        "diagnostics": {
            "status": status,
            "production_authority": (
                production_authority
            ),
            "production_authority_changed": (
                production_authority_changed
            ),
        },
    }


def outcomes(
    *,
    batter_id=201,
    game_date="2025-07-01",
):
    return (
        materialize_canonical_pitcher_matchup_profile_pa_historical_outcomes(
            [
                {
                    "game_pk": 700001,
                    "game_date": game_date,
                    "at_bat_number": 1,
                    "pitcher_id": 101,
                    "batter_id": batter_id,
                    "events": "single",
                },
                {
                    "game_pk": 700001,
                    "game_date": game_date,
                    "at_bat_number": 2,
                    "pitcher_id": 101,
                    "batter_id": batter_id,
                    "events": "strikeout",
                },
            ]
        )
    )


def materialize(**overrides):
    values = {
        "outcomes": outcomes(),
        "statistics": statistics(),
        "candidates_by_game_pitcher": {
            (700001, 101): candidate(),
        },
    }
    values.update(overrides)

    return (
        materialize_canonical_pitcher_matchup_profile_pa_historical_samples(
            values.pop("outcomes"),
            **values,
        )
    )


def test_materializes_evaluator_ready_sample():
    result = materialize()

    assert result["diagnostics"]["status"] == "ready"
    assert result["diagnostics"][
        "materialized_sample_count"
    ] == 1
    assert result["diagnostics"][
        "rejected_sample_count"
    ] == 0

    sample = result["samples"][0]

    assert sample["season"] == 2025
    assert sample["game_pk"] == "700001"
    assert sample["comparison_id"] == (
        "700001:101:201"
    )
    assert sample["pitcher_id"] == 101
    assert sample["batter_id"] == 201
    assert sample["observed_counts"]["single"] == 1
    assert sample["observed_counts"]["k"] == 1
    assert round(
        sum(
            sample[
                "production_probabilities"
            ].values()
        ),
        12,
    ) == 1.0
    assert round(
        sum(
            sample[
                "candidate_probabilities"
            ].values()
        ),
        12,
    ) == 1.0


def test_candidate_changes_supported_probabilities():
    sample = materialize()["samples"][0]

    assert sample[
        "maximum_absolute_probability_delta"
    ] > 0.0
    assert sample["applied_rates"] == {
        "k_rate": 0.35,
        "barrel_rate_allowed_approx": 0.08,
        "hard_hit_rate_allowed": 0.4,
    }
    assert sample[
        "production_probabilities"
    ] != sample["candidate_probabilities"]


def test_output_is_accepted_by_historical_evaluator():
    paired = materialize()

    evaluation = (
        evaluate_canonical_pitcher_matchup_profile_pa_history(
            paired["samples"],
            minimum_samples=1,
            minimum_observed_pa=1,
        )
    )

    assert evaluation["diagnostics"][
        "accepted_sample_count"
    ] == 1
    assert evaluation["diagnostics"][
        "rejected_sample_count"
    ] == 0
    assert evaluation["overall"][
        "observed_pa"
    ] == 2


def test_missing_candidate_fails_closed():
    result = materialize(
        candidates_by_game_pitcher={}
    )

    assert result["samples"] == []
    assert result["diagnostics"][
        "status"
    ] == "unavailable"
    assert result["diagnostics"][
        "rejected_samples"
    ][0]["reason"] == (
        "historical_pitcher_candidate_unavailable"
    )


def test_blocked_candidate_fails_closed():
    result = materialize(
        candidates_by_game_pitcher={
            (700001, 101): candidate(
                status="unavailable"
            ),
        }
    )

    assert result["samples"] == []
    assert result["diagnostics"][
        "rejected_samples"
    ][0]["reason"].startswith(
        "historical_pa_comparison_blocked:"
    )


def test_invalid_candidate_authority_fails_closed():
    result = materialize(
        candidates_by_game_pitcher={
            (700001, 101): candidate(
                production_authority=True
            ),
        }
    )

    assert result["samples"] == []
    assert result["diagnostics"][
        "rejected_samples"
    ][0]["reason"] == (
        "historical_pa_comparison_blocked:"
        "candidate_authority_contract_invalid"
    )


def test_missing_batter_statistics_fails_closed():
    result = materialize(
        outcomes=outcomes(
            batter_id=202
        )
    )

    assert result["samples"] == []
    assert result["diagnostics"][
        "rejected_samples"
    ][0]["reason"] == (
        "historical_batter_statistics_unavailable"
    )


@pytest.mark.parametrize(
    "players,reason",
    [
        (
            (
                hitter(
                    sample_available=False
                ),
                pitcher(),
            ),
            "historical_batter_sample_unavailable",
        ),
        (
            (
                hitter(),
                pitcher(
                    sample_available=False
                ),
            ),
            "historical_pitcher_sample_unavailable",
        ),
    ],
)
def test_zero_sample_statistics_fail_closed(
    players,
    reason,
):
    result = materialize(
        statistics=statistics(
            players=players
        )
    )

    assert result["samples"] == []
    assert result["diagnostics"][
        "rejected_samples"
    ][0]["reason"] == reason


def test_game_date_mismatch_fails_closed():
    result = materialize(
        outcomes=outcomes(
            game_date="2025-07-02"
        )
    )

    assert result["samples"] == []
    assert result["diagnostics"][
        "rejected_samples"
    ][0]["reason"] == (
        "historical_statistics_game_date_mismatch"
    )


@pytest.mark.parametrize(
    "key",
    [
        "700001:101",
        (700001,),
        (0, 101),
        (700001, False),
    ],
)
def test_candidate_keys_must_be_exact_tuples(
    key,
):
    with pytest.raises(ValueError):
        materialize(
            candidates_by_game_pitcher={
                key: candidate(),
            }
        )


def test_valid_samples_survive_rejected_samples():
    source = outcomes()
    source["samples"].append({
        **deepcopy(source["samples"][0]),
        "comparison_id": "700001:101:202",
        "batter_id": 202,
    })

    result = materialize(
        outcomes=source
    )

    assert result["diagnostics"][
        "status"
    ] == "partial"
    assert result["diagnostics"][
        "materialized_sample_count"
    ] == 1
    assert result["diagnostics"][
        "rejected_sample_count"
    ] == 1


def test_materialization_is_deterministic():
    source = outcomes()
    first = materialize(
        outcomes=source
    )
    second = materialize(
        outcomes={
            **source,
            "samples": list(
                reversed(source["samples"])
            ),
        }
    )

    assert first["samples"] == second["samples"]
    assert first["diagnostics"][
        "sample_digest"
    ] == second["diagnostics"][
        "sample_digest"
    ]


def test_inputs_are_not_mutated():
    source = outcomes()
    stats = statistics()
    candidates = {
        (700001, 101): candidate(),
    }
    original_source = deepcopy(source)
    original_candidates = deepcopy(
        candidates
    )

    materialize(
        outcomes=source,
        statistics=stats,
        candidates_by_game_pitcher=(
            candidates
        ),
    )

    assert source == original_source
    assert candidates == original_candidates


def test_authority_contract_remains_shadow_only():
    diagnostics = materialize()[
        "diagnostics"
    ]

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
    assert diagnostics["pairing_policy"] == (
        "game_pitcher_batter_cutoff_safe"
    )

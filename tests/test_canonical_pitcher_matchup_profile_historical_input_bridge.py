from __future__ import annotations

from copy import deepcopy

from mlb_app.simulation.pa_outcome_model import (
    build_pa_outcome_probabilities,
)
from mlb_app.simulation.shadow.historical_probability_workspace_reconstruction import (
    build_historical_probability_offense_profile,
    build_historical_probability_pitcher_profile,
)


def offense_counts():
    return {
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


def pitcher_counts():
    return {
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


def test_builds_exact_historical_profiles():
    offense = (
        build_historical_probability_offense_profile(
            offense_counts()
        )
    )
    pitcher = (
        build_historical_probability_pitcher_profile(
            pitcher_counts()
        )
    )

    assert offense["contact_skill"] == {
        "k_rate": 0.2,
        "contact_rate": 0.8,
        "batting_avg": 0.3,
    }
    assert offense["plate_discipline"] == {
        "bb_rate": 0.1,
    }
    assert offense["power"] == {
        "iso": 0.275,
        "barrel_rate": None,
        "hard_hit_rate": None,
    }
    assert pitcher["bat_missing"] == {
        "k_rate": 0.25,
    }
    assert pitcher["command_control"] == {
        "bb_rate": 0.1,
    }
    assert pitcher["contact_management"] == {
        "xba_allowed": 0.25,
        "barrel_rate_allowed": None,
        "hard_hit_rate_allowed": None,
    }


def test_profiles_reproduce_canonical_historical_model():
    result = build_pa_outcome_probabilities(
        batter_profile=(
            build_historical_probability_offense_profile(
                offense_counts()
            )
        ),
        pitcher_profile=(
            build_historical_probability_pitcher_profile(
                pitcher_counts()
            )
        ),
        environment_profile=None,
    )

    assert result["model_version"] == "pa_outcome_v1"
    assert round(
        sum(result["probabilities"].values()),
        12,
    ) == 1.0
    assert result["inputs_used"][
        "batter_k_rate"
    ] == 0.2
    assert result["inputs_used"][
        "pitcher_k_rate"
    ] == 0.25


def test_profile_builders_are_nonmutating():
    offense = offense_counts()
    pitcher = pitcher_counts()
    original_offense = deepcopy(offense)
    original_pitcher = deepcopy(pitcher)

    build_historical_probability_offense_profile(
        offense
    )
    build_historical_probability_pitcher_profile(
        pitcher
    )

    assert offense == original_offense
    assert pitcher == original_pitcher


def test_zero_samples_use_model_fallbacks():
    result = build_pa_outcome_probabilities(
        batter_profile=(
            build_historical_probability_offense_profile(
                {}
            )
        ),
        pitcher_profile=(
            build_historical_probability_pitcher_profile(
                {}
            )
        ),
        environment_profile=None,
    )

    assert result["probabilities"]
    assert round(
        sum(result["probabilities"].values()),
        12,
    ) == 1.0

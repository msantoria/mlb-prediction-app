import copy

from mlb_app import model_projections


OUTCOMES = {
    "out": 0.65,
    "reached_on_error": 0.01,
    "single": 0.13,
    "double": 0.04,
    "triple": 0.005,
    "hr": 0.035,
    "bb": 0.08,
    "hbp": 0.01,
    "k": 0.20,
}


def candidate(k_rate, barrel_rate, hard_hit_rate):
    return {
        "profile_rates": {
            "k_rate": k_rate,
            "barrel_rate_allowed_approx": (
                barrel_rate
            ),
            "hard_hit_rate_allowed": (
                hard_hit_rate
            ),
            "bb_rate": 0.04,
        },
        "diagnostics": {
            "status": "ready",
            "production_authority": False,
            "production_authority_changed": False,
        },
    }


def side(
    team_id,
    team_name,
    pitcher_candidate,
):
    return {
        "team_id": team_id,
        "team_name": team_name,
        "pitcher_id": team_id + 1000,
        "pitcher_name": f"{team_name} Starter",
        "pitcher_features": {},
        "pitch_arsenal": {},
        "offense_inputs": {},
        "bullpen_inputs": {},
        "pitcher_matchup_profile_candidate": (
            pitcher_candidate
        ),
    }


def test_workspace_exposes_paired_pitcher_pa_shadow(
    monkeypatch,
):
    simulation_calls = []

    monkeypatch.setattr(
        model_projections,
        "compute_environment_profile",
        lambda value: {
            "run_environment": {
                "hr_boost_index": 1.0,
                "hit_boost_index": 1.0,
                "run_scoring_index": 1.0,
            },
        },
    )
    monkeypatch.setattr(
        model_projections,
        "build_team_offense_prior",
        lambda **kwargs: {
            "contact_skill": {
                "k_rate": 0.22,
                "contact_rate": 0.76,
                "hit_skill": 0.29,
            },
            "plate_discipline": {
                "bb_rate": 0.08,
            },
            "power": {
                "iso": 0.17,
                "barrel_rate": 0.08,
                "hard_hit_rate": 0.39,
            },
        },
    )
    monkeypatch.setattr(
        model_projections,
        "build_bullpen_profile",
        lambda **kwargs: {},
    )

    def fake_simulation(**kwargs):
        simulation_calls.append(
            copy.deepcopy(kwargs)
        )
        return {
            "away_expected_runs": 4.1,
            "home_expected_runs": 4.2,
            "away_win_probability": 0.49,
            "home_win_probability": 0.51,
            "total_probabilities": {},
            "team_total_probabilities": {},
            "model_version": "fixture",
            "simulations": 1,
            "metadata": {
                "simulation_count": 1,
                "seed": 42,
                "dynamic_starter_exit": True,
            },
        }

    monkeypatch.setattr(
        model_projections,
        "simulate_game_with_bullpen",
        fake_simulation,
    )

    away = side(
        1,
        "Away",
        candidate(0.27, 0.07, 0.34),
    )
    home = side(
        2,
        "Home",
        candidate(0.25, 0.08, 0.36),
    )

    result = (
        model_projections
        ._build_projection_simulation_cards(
            {
                "game_pk": 123,
                "game_date": "2026-08-23",
                "venue": "Fixture Park",
                "weather": {},
                "park_factor": 1.0,
            },
            away,
            home,
        )
    )

    workspace = result["workspace"]
    comparisons = workspace[
        "pitcherMatchupProfilePAShadowComparisons"
    ]
    away_comparison = comparisons[
        "awayOffenseVsHomeStarter"
    ]
    home_comparison = comparisons[
        "homeOffenseVsAwayStarter"
    ]

    assert away_comparison["status"] == "ready"
    assert home_comparison["status"] == "ready"
    assert (
        away_comparison[
            "maximum_absolute_probability_delta"
        ]
        > 0
    )
    assert (
        home_comparison[
            "maximum_absolute_probability_delta"
        ]
        > 0
    )
    assert comparisons[
        "simulation_inputs_changed"
    ] is False
    assert comparisons[
        "final_probabilities_changed"
    ] is False
    assert comparisons[
        "production_authority_changed"
    ] is False

    assert len(simulation_calls) == 1
    simulation_input = simulation_calls[0]

    assert simulation_input[
        "away_starter_probabilities"
    ] == workspace[
        "awayPAOutcomeModel"
    ]["probabilities"]
    assert simulation_input[
        "home_starter_probabilities"
    ] == workspace[
        "homePAOutcomeModel"
    ]["probabilities"]

    assert simulation_input[
        "away_starter_probabilities"
    ] != home_comparison[
        "shadow_probabilities"
    ]
    assert simulation_input[
        "home_starter_probabilities"
    ] != away_comparison[
        "shadow_probabilities"
    ]


def test_workspace_fails_closed_when_candidates_missing(
    monkeypatch,
):
    monkeypatch.setattr(
        model_projections,
        "compute_environment_profile",
        lambda value: {},
    )
    monkeypatch.setattr(
        model_projections,
        "build_team_offense_prior",
        lambda **kwargs: {},
    )
    monkeypatch.setattr(
        model_projections,
        "build_bullpen_profile",
        lambda **kwargs: {},
    )
    monkeypatch.setattr(
        model_projections,
        "simulate_game_with_bullpen",
        lambda **kwargs: {
            "away_expected_runs": 4.0,
            "home_expected_runs": 4.0,
            "away_win_probability": 0.5,
            "home_win_probability": 0.5,
            "total_probabilities": {},
            "team_total_probabilities": {},
            "model_version": "fixture",
            "simulations": 1,
            "metadata": {},
        },
    )

    result = (
        model_projections
        ._build_projection_simulation_cards(
            {
                "game_pk": 456,
                "game_date": "2026-08-23",
            },
            side(1, "Away", {}),
            side(2, "Home", {}),
        )
    )

    comparisons = result["workspace"][
        "pitcherMatchupProfilePAShadowComparisons"
    ]

    assert comparisons[
        "awayOffenseVsHomeStarter"
    ]["status"] == "blocked"
    assert comparisons[
        "homeOffenseVsAwayStarter"
    ]["status"] == "blocked"
    assert comparisons[
        "simulation_inputs_changed"
    ] is False
    assert comparisons[
        "production_authority_changed"
    ] is False



def _execute_activation_workspace(
    monkeypatch,
    *,
    away_candidate,
    home_candidate,
):
    simulation_calls = []

    monkeypatch.setattr(
        model_projections,
        "compute_environment_profile",
        lambda value: {
            "run_environment": {
                "hr_boost_index": 1.0,
                "hit_boost_index": 1.0,
                "run_scoring_index": 1.0,
            },
        },
    )
    monkeypatch.setattr(
        model_projections,
        "build_team_offense_prior",
        lambda **kwargs: {
            "contact_skill": {
                "k_rate": 0.22,
                "contact_rate": 0.76,
                "hit_skill": 0.29,
            },
            "plate_discipline": {
                "bb_rate": 0.08,
            },
            "power": {
                "iso": 0.17,
                "barrel_rate": 0.08,
                "hard_hit_rate": 0.39,
            },
        },
    )
    monkeypatch.setattr(
        model_projections,
        "build_bullpen_profile",
        lambda **kwargs: {},
    )

    def fake_simulation(**kwargs):
        simulation_calls.append(
            copy.deepcopy(kwargs)
        )
        return {
            "away_expected_runs": 4.1,
            "home_expected_runs": 4.2,
            "away_win_probability": 0.49,
            "home_win_probability": 0.51,
            "total_probabilities": {},
            "team_total_probabilities": {},
            "model_version": "fixture",
            "simulations": 1,
            "metadata": {
                "simulation_count": 1,
                "seed": 42,
                "dynamic_starter_exit": True,
            },
        }

    monkeypatch.setattr(
        model_projections,
        "simulate_game_with_bullpen",
        fake_simulation,
    )

    result = (
        model_projections
        ._build_projection_simulation_cards(
            {
                "game_pk": 789,
                "game_date": "2026-08-23",
                "venue": "Fixture Park",
                "weather": {},
                "park_factor": 1.0,
            },
            side(
                1,
                "Away",
                away_candidate,
            ),
            side(
                2,
                "Home",
                home_candidate,
            ),
        )
    )

    return result, simulation_calls


def test_activation_flag_defaults_off(
    monkeypatch,
):
    monkeypatch.delenv(
        "MLB_ENABLE_CANONICAL_PITCHER_MATCHUP_PROFILE_PA",
        raising=False,
    )
    result, simulation_calls = (
        _execute_activation_workspace(
            monkeypatch,
            away_candidate=candidate(
                0.27,
                0.07,
                0.34,
            ),
            home_candidate=candidate(
                0.25,
                0.08,
                0.36,
            ),
        )
    )

    workspace = result["workspace"]
    activation = workspace[
        "pitcherMatchupProfilePAActivation"
    ]
    comparisons = workspace[
        "pitcherMatchupProfilePAShadowComparisons"
    ]

    assert activation["requested"] is False
    assert activation[
        "simulation_inputs_changed"
    ] is False
    assert activation[
        "final_side_probabilities_changed"
    ] is False
    assert activation[
        "awayOffenseVsHomeStarter"
    ]["activation_status"] == (
        "production_activation_not_requested"
    )
    assert activation[
        "homeOffenseVsAwayStarter"
    ]["activation_status"] == (
        "production_activation_not_requested"
    )
    assert comparisons[
        "production_authority_changed"
    ] is False

    simulation_input = simulation_calls[0]
    assert simulation_input[
        "away_starter_probabilities"
    ] == workspace[
        "awayPAOutcomeModel"
    ]["probabilities"]
    assert simulation_input[
        "home_starter_probabilities"
    ] == workspace[
        "homePAOutcomeModel"
    ]["probabilities"]


def test_activation_flag_uses_ready_candidates(
    monkeypatch,
):
    monkeypatch.setenv(
        "MLB_ENABLE_CANONICAL_PITCHER_MATCHUP_PROFILE_PA",
        "true",
    )
    result, simulation_calls = (
        _execute_activation_workspace(
            monkeypatch,
            away_candidate=candidate(
                0.27,
                0.07,
                0.34,
            ),
            home_candidate=candidate(
                0.25,
                0.08,
                0.36,
            ),
        )
    )

    workspace = result["workspace"]
    activation = workspace[
        "pitcherMatchupProfilePAActivation"
    ]
    comparisons = workspace[
        "pitcherMatchupProfilePAShadowComparisons"
    ]
    away_comparison = comparisons[
        "awayOffenseVsHomeStarter"
    ]
    home_comparison = comparisons[
        "homeOffenseVsAwayStarter"
    ]

    assert activation["requested"] is True
    assert activation[
        "simulation_inputs_changed"
    ] is True
    assert activation[
        "final_side_probabilities_changed"
    ] is False
    assert activation[
        "awayOffenseVsHomeStarter"
    ]["activation_status"] == (
        "production_candidate_activated"
    )
    assert activation[
        "homeOffenseVsAwayStarter"
    ]["activation_status"] == (
        "production_candidate_activated"
    )
    assert comparisons[
        "production_authority_changed"
    ] is True

    simulation_input = simulation_calls[0]
    assert simulation_input[
        "away_starter_probabilities"
    ] == away_comparison[
        "shadow_probabilities"
    ]
    assert simulation_input[
        "home_starter_probabilities"
    ] == home_comparison[
        "shadow_probabilities"
    ]


def test_activation_fails_closed_per_invalid_candidate(
    monkeypatch,
):
    monkeypatch.setenv(
        "MLB_ENABLE_CANONICAL_PITCHER_MATCHUP_PROFILE_PA",
        "1",
    )
    result, simulation_calls = (
        _execute_activation_workspace(
            monkeypatch,
            away_candidate=candidate(
                0.27,
                0.07,
                0.34,
            ),
            home_candidate={},
        )
    )

    workspace = result["workspace"]
    activation = workspace[
        "pitcherMatchupProfilePAActivation"
    ]
    comparisons = workspace[
        "pitcherMatchupProfilePAShadowComparisons"
    ]
    away_comparison = comparisons[
        "awayOffenseVsHomeStarter"
    ]
    home_comparison = comparisons[
        "homeOffenseVsAwayStarter"
    ]

    assert away_comparison["status"] == "blocked"
    assert home_comparison["status"] == "ready"
    assert activation["requested"] is True
    assert activation[
        "awayOffenseVsHomeStarter"
    ]["production_authority_changed"] is False
    assert activation[
        "homeOffenseVsAwayStarter"
    ]["production_authority_changed"] is True
    assert activation[
        "simulation_inputs_changed"
    ] is True
    assert activation[
        "final_side_probabilities_changed"
    ] is False

    simulation_input = simulation_calls[0]
    assert simulation_input[
        "away_starter_probabilities"
    ] == workspace[
        "awayPAOutcomeModel"
    ]["probabilities"]
    assert simulation_input[
        "home_starter_probabilities"
    ] == home_comparison[
        "shadow_probabilities"
    ]

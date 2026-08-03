from __future__ import annotations

from mlb_app.model_projection_probability import build_model_projection_probability, select_model_projection_simulation
from mlb_app.model_projection_routes import _apply_projection_probability_contract


def test_select_model_projection_simulation_prefers_bullpen_adjusted_output() -> None:
    shared = {
        "derived_outputs": {
            "game_simulation": {
                "home_win_probability": 0.51,
                "away_win_probability": 0.49,
                "model_version": "base",
            },
            "bullpen_adjusted_game_simulation": {
                "home_win_probability": 0.57,
                "away_win_probability": 0.43,
                "model_version": "bullpen",
            },
        }
    }

    selected, source_path = select_model_projection_simulation(shared)

    assert selected["home_win_probability"] == 0.57
    assert selected["away_win_probability"] == 0.43
    assert source_path == "sharedSimulation.derived_outputs.bullpen_adjusted_game_simulation"


def test_build_probability_contract_uses_model_projection_output() -> None:
    probability = build_model_projection_probability(
        game_pk=123,
        date="2026-07-09",
        shared_simulation={
            "derived_outputs": {
                "bullpen_adjusted_game_simulation": {
                    "home_win_probability": 0.62,
                    "away_win_probability": 0.38,
                    "model_version": "shared_game_simulation_v1",
                }
            }
        },
        matchup={"home_win_prob": 0.51, "away_win_prob": 0.49, "model_version": "canonical_matchup_win_probability_v2"},
        generated_at="2026-07-09T18:00:00Z",
    )

    assert probability["source"] == "model_projections"
    assert probability["is_fallback"] is False
    assert probability["home_win_prob"] == 0.62
    assert probability["away_win_prob"] == 0.38
    assert probability["home_win_probability"] == 0.62
    assert probability["away_win_probability"] == 0.38
    assert probability["source_path"] == "sharedSimulation.derived_outputs.bullpen_adjusted_game_simulation"
    assert probability["model_version"] == "shared_game_simulation_v1"


def test_build_probability_contract_marks_canonical_fallback_explicitly() -> None:
    probability = build_model_projection_probability(
        game_pk=123,
        date="2026-07-09",
        shared_simulation={"derived_outputs": {}},
        matchup={"home_win_prob": 0.51, "away_win_prob": 0.49, "model_version": "canonical_matchup_win_probability_v2"},
        generated_at="2026-07-09T18:00:00Z",
    )

    assert probability["source"] == "fallback:canonical_matchup_win_probability_v2"
    assert probability["fallback_source"] == "canonical_matchup_win_probability_v2"
    assert probability["is_fallback"] is True
    assert probability["missing_model_projection_reason"] == "sharedSimulation derived outputs missing"
    assert probability["home_win_prob"] == 0.51
    assert probability["away_win_prob"] == 0.49


def test_build_probability_contract_preserves_zero_fallback_value() -> None:
    probability = build_model_projection_probability(
        game_pk=123,
        date="2026-07-09",
        shared_simulation={"derived_outputs": {}},
        matchup={
            "home_win_prob": 0.0,
            "home_win_probability": 0.55,
            "away_win_prob": 1.0,
            "away_win_probability": 0.45,
        },
    )

    assert probability["home_win_prob"] == 0.0
    assert probability["away_win_prob"] == 1.0


def test_projection_route_contract_repoints_legacy_aliases_from_model_projection() -> None:
    payload = {
        "date": "2026-07-09",
        "source_notes": [
            "home_win_prob and away_win_prob are canonical v2 from /matchups.",
            "Simulation outputs remain available as diagnostics and do not define final side probability.",
        ],
        "games": [
            {
                "game_pk": 123,
                "game_date": "2026-07-09",
                "home_win_prob": 0.51,
                "away_win_prob": 0.49,
                "main_matchup_probabilities": {"source": "matchups.canonical_matchup_win_probability_v2"},
                "workspace": {"sharedSimulationDiagnostics": {"status": "diagnostic_only_not_final_probability"}},
                "sharedSimulation": {
                    "derived_outputs": {
                        "bullpen_adjusted_game_simulation": {
                            "home_win_probability": 0.64,
                            "away_win_probability": 0.36,
                            "model_version": "bullpen_adjusted_v1",
                        }
                    }
                },
            }
        ],
    }

    updated = _apply_projection_probability_contract(payload, "2026-07-09")
    game = updated["games"][0]

    assert updated["probability_contract"] == "model_projection_probability_v1"
    assert game["home_win_prob"] == 0.64
    assert game["away_win_prob"] == 0.36
    assert game["home_win_probability"] == 0.64
    assert game["away_win_probability"] == 0.36
    assert game["probability_source"] == "model_projections"
    assert game["probability_is_fallback"] is False
    assert game["model_projection_probability"]["source"] == "model_projections"
    assert game["workspace"]["modelProjectionProbability"]["home_win_prob"] == 0.64
    assert game["main_matchup_probabilities"]["displayed_probability_source"] == "model_projections"
    assert not any("canonical v2 from /matchups" in note for note in updated["source_notes"])


def test_projection_route_contract_marks_fallback_when_shared_output_missing() -> None:
    payload = {
        "date": "2026-07-09",
        "games": [
            {
                "game_pk": 123,
                "game_date": "2026-07-09",
                "home_win_prob": 0.52,
                "away_win_prob": 0.48,
                "sharedSimulation": {"derived_outputs": {}},
            }
        ],
    }

    updated = _apply_projection_probability_contract(payload, "2026-07-09")
    probability = updated["games"][0]["model_projection_probability"]

    assert probability["source"] == "fallback:canonical_matchup_win_probability_v2"
    assert probability["is_fallback"] is True
    assert updated["games"][0]["probability_is_fallback"] is True
    assert updated["games"][0]["home_win_prob"] == 0.52
    assert updated["games"][0]["away_win_prob"] == 0.48

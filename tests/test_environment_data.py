from mlb_app.environment_data import build_environment_context, get_park_factors


def test_get_park_factors_returns_contract_for_unknown_venue():
    result = get_park_factors("Unknown Park")
    assert "run_factor" in result
    assert "home_run_factor" in result
    assert "hit_factor" in result
    assert "source_fields_used" in result
    assert "park_readiness" in result
    assert result["park_readiness"] == "stub"


def test_build_environment_context_returns_stable_contract_for_unknown_venue():
    game = {
        "gameDate": "2026-04-22T18:05:00Z",
        "venue": {"name": "Unknown Park"},
        "teams": {
            "home": {"team": {"name": "Home Team"}},
            "away": {"team": {"name": "Away Team"}},
        },
    }

    result = build_environment_context(game)

    assert "venue_name" in result
    assert "temperature_f" in result
    assert "wind_speed_mph" in result
    assert "run_factor" in result
    assert "home_run_factor" in result
    assert "hit_factor" in result
    assert "source_type" in result
    assert "source_fields_used" in result
    assert "data_confidence" in result
    assert "generated_from" in result
    assert "is_stub" in result
    assert "readiness" in result
    assert "missing_inputs" in result

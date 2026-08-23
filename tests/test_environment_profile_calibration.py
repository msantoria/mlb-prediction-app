from mlb_app.environment_profile import (
    compute_environment_profile,
)


def run_environment(**values):
    result = compute_environment_profile(values)
    return result["run_environment"]


def metadata(**values):
    result = compute_environment_profile(values)
    return result["metadata"]


def test_authoritative_park_factors_are_not_capped():
    result = run_environment(
        run_factor=1.18,
        home_run_factor=1.20,
        hit_factor=1.12,
    )

    assert result["run_scoring_index"] == 1.18
    assert result["hr_boost_index"] == 1.20
    assert result["hit_boost_index"] == 1.12


def test_pitcher_friendly_park_factors_are_not_floored():
    result = run_environment(
        run_factor=0.82,
        home_run_factor=0.80,
        hit_factor=0.88,
    )

    assert result["run_scoring_index"] == 0.82
    assert result["hr_boost_index"] == 0.80
    assert result["hit_boost_index"] == 0.88


def test_weather_is_incremental_to_full_park_factor():
    result = run_environment(
        venue_name="Wrigley Field",
        run_factor=1.18,
        home_run_factor=1.20,
        hit_factor=1.12,
        temperature_f=95,
        wind_speed_mph=15,
        wind_direction="Out To CF",
    )

    assert result["run_scoring_index"] > 1.18
    assert result["hr_boost_index"] > 1.20
    assert result["hit_boost_index"] > 1.12


def test_weather_adjustment_remains_bounded():
    values = {
        "venue_name": "Wrigley Field",
        "run_factor": 1.18,
        "home_run_factor": 1.20,
        "hit_factor": 1.12,
        "temperature_f": 95,
        "wind_speed_mph": 30,
        "wind_direction": "Out To CF",
    }
    result = run_environment(**values)
    policy = metadata(**values)

    maximum = policy["max_weather_adjustment"]

    assert result["run_scoring_index"] > 1.18
    assert result["hr_boost_index"] > 1.20
    assert result["hit_boost_index"] > 1.12
    assert (
        result["run_scoring_index"] - 1.18
        <= maximum
    )
    assert (
        result["hr_boost_index"] - 1.20
        <= maximum
    )
    assert (
        result["hit_boost_index"] - 1.12
        <= maximum
    )


def test_run_factor_proxies_preserve_full_signal():
    result = compute_environment_profile({
        "run_factor": 1.30,
    })
    environment = result["run_environment"]
    park = result["environment_components"][
        "park_component"
    ]

    assert environment["run_scoring_index"] == 1.30
    assert environment["hr_boost_index"] == 1.33
    assert environment["hit_boost_index"] == 1.18
    assert park["proxy_from_run_factor_used"] is True


def test_v2_metadata_documents_uncapped_park_policy():
    result = metadata(
        run_factor=1.18,
        home_run_factor=1.20,
        hit_factor=1.12,
    )

    assert (
        result["environment_calibration_version"]
        == "env_calibration_v2"
    )
    assert result[
        "park_factor_preservation_policy"
    ] == (
        "preserve_sourced_park_factor_"
        "bound_weather_only_v1"
    )
    assert "max_total_adjustment" not in result

def test_open_air_venue_applies_weather():
    result = compute_environment_profile({
        "venue_name": "Wrigley Field",
        "temperature_f": 95,
        "wind_speed_mph": 20,
        "wind_direction": "Out To CF",
    })

    weather = result["environment_components"][
        "weather_component"
    ]

    assert weather["weather_application_allowed"] is True
    assert weather["weather_application_status"] == "applied"
    assert weather["applied_temperature_f"] == 95.0


def test_explicit_open_retractable_roof_applies_weather():
    result = compute_environment_profile({
        "venue_name": "Chase Field",
        "roof_status": "open",
        "temperature_f": 95,
        "wind_speed_mph": 20,
        "wind_direction": "Out To CF",
    })

    weather = result["environment_components"][
        "weather_component"
    ]

    assert weather["weather_application_allowed"] is True
    assert weather["roof_resolution"]["roof_state"] == "open"


def test_closed_retractable_roof_neutralizes_weather():
    result = compute_environment_profile({
        "venue_name": "Chase Field",
        "roof_status": "closed",
        "temperature_f": 95,
        "wind_speed_mph": 20,
        "wind_direction": "Out To CF",
    })

    environment = result["run_environment"]
    weather = result["environment_components"][
        "weather_component"
    ]

    assert environment["run_scoring_index"] == 1.01
    assert environment["hr_boost_index"] == 1.02
    assert environment["hit_boost_index"] == 1.01
    assert weather["weather_application_allowed"] is False
    assert (
        weather["weather_application_status"]
        == "neutralized_indoor"
    )


def test_unknown_retractable_roof_fails_closed_for_weather():
    result = compute_environment_profile({
        "venue_name": "Chase Field",
        "temperature_f": 95,
        "wind_speed_mph": 20,
        "wind_direction": "Out To CF",
    })

    environment = result["run_environment"]
    weather = result["environment_components"][
        "weather_component"
    ]

    assert environment["run_scoring_index"] == 1.01
    assert environment["hr_boost_index"] == 1.02
    assert environment["hit_boost_index"] == 1.01
    assert weather["weather_application_allowed"] is False
    assert (
        weather["weather_application_status"]
        == "neutralized_unknown_roof"
    )
    assert weather["temperature_f"] == 95.0
    assert weather["applied_temperature_f"] is None


def test_fixed_dome_neutralizes_weather():
    result = compute_environment_profile({
        "venue_name": "Tropicana Field",
        "temperature_f": 95,
        "wind_speed_mph": 20,
        "wind_direction": "Out To CF",
    })

    environment = result["run_environment"]
    weather = result["environment_components"][
        "weather_component"
    ]

    assert environment["run_scoring_index"] == 0.98
    assert environment["hr_boost_index"] == 0.96
    assert environment["hit_boost_index"] == 0.99
    assert weather["weather_application_allowed"] is False
    assert (
        weather["roof_resolution"]["indoor_effective"]
        is True
    )


def test_unknown_venue_does_not_apply_unverified_weather():
    result = compute_environment_profile({
        "venue_name": "Unknown Test Venue",
        "temperature_f": 95,
        "wind_speed_mph": 20,
        "wind_direction": "Out To CF",
    })

    environment = result["run_environment"]
    weather = result["environment_components"][
        "weather_component"
    ]

    assert environment["run_scoring_index"] == 1.0
    assert environment["hr_boost_index"] == 1.0
    assert environment["hit_boost_index"] == 1.0
    assert weather["weather_application_allowed"] is False

def test_adjustment_breakdown_reconciles_park_weather_and_final():
    result = compute_environment_profile({
        "venue_name": "Wrigley Field",
        "run_factor": 1.18,
        "home_run_factor": 1.20,
        "hit_factor": 1.12,
        "temperature_f": 95,
        "wind_speed_mph": 15,
        "wind_direction": "Out To CF",
    })

    breakdown = result["environment_components"][
        "adjustment_breakdown"
    ]

    expected = {
        "run_scoring": 1.18,
        "hits": 1.12,
        "home_runs": 1.20,
    }

    for key, park_factor in expected.items():
        row = breakdown[key]

        assert row["park_factor"] == park_factor
        assert row["park_adjustment"] == round(
            park_factor - 1.0,
            3,
        )
        assert row["weather_adjustment"] > 0.0
        assert row["full_adjustment"] == round(
            row["final_index"] - 1.0,
            3,
        )
        assert row["reconciles_to_components"] is True


def test_neutralized_weather_has_zero_applied_adjustments():
    result = compute_environment_profile({
        "venue_name": "Chase Field",
        "roof_status": "closed",
        "temperature_f": 95,
        "wind_speed_mph": 20,
        "wind_direction": "Out To CF",
    })

    breakdown = result["environment_components"][
        "adjustment_breakdown"
    ]

    for row in breakdown.values():
        assert row["weather_adjustment"] == 0.0
        assert row["final_index"] == row["park_factor"]
        assert row["reconciles_to_components"] is True

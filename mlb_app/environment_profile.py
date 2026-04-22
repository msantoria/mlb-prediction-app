"""
Utilities for building environment profile summaries for matchup previews.

This module defines a game-level environment profile structure that can later
be populated with real weather, park factor, and contextual inputs.
"""


def compute_environment_profile(raw_context: dict) -> dict:
    """
    Build a structured environment profile from raw game context inputs.

    Parameters
    ----------
    raw_context : dict
        Dictionary of environmental and contextual stats from upstream
        ingestion or transformed sources.

    Returns
    -------
    dict
        A structured game-level environment profile using raw metrics grouped
        by category. Missing fields are returned as None.
    """
    raw_context = raw_context or {}

    return {
        "metadata": {
            "source_type": raw_context.get("source_type", "unknown"),
            "source_fields_used": raw_context.get("source_fields_used", []),
            "data_confidence": raw_context.get("data_confidence", "unknown"),
            "generated_from": raw_context.get("generated_from", "compute_environment_profile"),
        },
        "weather": {
            "temperature_f": raw_context.get("temperature_f"),
            "wind_speed_mph": raw_context.get("wind_speed_mph"),
            "wind_direction": raw_context.get("wind_direction"),
            "humidity_pct": raw_context.get("humidity_pct"),
            "precipitation_probability": raw_context.get("precipitation_probability"),
        },
        "park_factors": {
            "run_factor": raw_context.get("run_factor"),
            "home_run_factor": raw_context.get("home_run_factor"),
            "hit_factor": raw_context.get("hit_factor"),
        },
        "game_context": {
            "venue_name": raw_context.get("venue_name"),
            "roof_status": raw_context.get("roof_status"),
            "home_team": raw_context.get("home_team"),
            "away_team": raw_context.get("away_team"),
            "game_time_local": raw_context.get("game_time_local"),
        },
        "run_environment": {
            "scoring_environment_label": raw_context.get("scoring_environment_label"),
            "weather_run_impact": raw_context.get("weather_run_impact"),
            "park_run_impact": raw_context.get("park_run_impact"),
        },
        "risk_flags": {
            "rain_delay_risk": raw_context.get("rain_delay_risk"),
            "postponement_risk": raw_context.get("postponement_risk"),
            "extreme_wind_flag": raw_context.get("extreme_wind_flag"),
            "extreme_temperature_flag": raw_context.get("extreme_temperature_flag"),
        },
        "status": {
            "is_stub": raw_context.get("is_stub", True),
            "readiness": raw_context.get("readiness", "stub"),
            "missing_inputs": raw_context.get("missing_inputs", []),
        },
    }

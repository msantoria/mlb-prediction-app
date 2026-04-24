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
    weather = raw_context.get("weather") or {}

    def _safe_float(value):
        if value is None:
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    def _park_label(run_factor):
        if run_factor is None:
            return None
        if run_factor >= 1.10:
            return "hitter_friendly"
        if run_factor >= 1.03:
            return "slight_hitter_friendly"
        if run_factor <= 0.92:
            return "pitcher_friendly"
        if run_factor <= 0.97:
            return "slight_pitcher_friendly"
        return "neutral"

    def _weather_impact(temp_f, wind_speed):
        if temp_f is not None and temp_f >= 85:
            return "warm_weather_offense_boost"
        if temp_f is not None and temp_f <= 50:
            return "cold_weather_offense_suppression"
        if wind_speed is not None and wind_speed >= 12:
            return "wind_may_affect_carry"
        return "neutral_or_unknown"

    temperature_f = raw_context.get("temperature_f", weather.get("temp_f"))
    wind_speed_mph = raw_context.get("wind_speed_mph", weather.get("wind_speed_mph"))
    wind_direction = raw_context.get("wind_direction", weather.get("wind_direction") or weather.get("wind"))
    condition = raw_context.get("condition", weather.get("condition"))

    temperature_f = _safe_float(temperature_f)
    wind_speed_mph = _safe_float(wind_speed_mph)

    run_factor = raw_context.get("run_factor", raw_context.get("park_factor"))
    run_factor = _safe_float(run_factor)

    missing_inputs = []
    if temperature_f is None:
        missing_inputs.append("temperature_f")
    if wind_speed_mph is None and not wind_direction:
        missing_inputs.append("wind")
    if run_factor is None:
        missing_inputs.append("run_factor")

    source_fields_used = [
        key for key in [
            "game_pk",
            "game_date",
            "venue_name",
            "weather",
            "park_factor",
            "home_team",
            "away_team",
        ]
        if raw_context.get(key) is not None
    ]

    return {
        "metadata": {
            "source_type": raw_context.get("source_type", "matchup_detail_context"),
            "source_fields_used": raw_context.get("source_fields_used", source_fields_used),
            "data_confidence": raw_context.get(
                "data_confidence",
                "medium" if run_factor is not None or weather else "low",
            ),
            "generated_from": raw_context.get("generated_from", "compute_environment_profile"),
        },
        "weather": {
            "temperature_f": temperature_f,
            "condition": condition,
            "wind_speed_mph": wind_speed_mph,
            "wind_direction": wind_direction,
            "humidity_pct": raw_context.get("humidity_pct", weather.get("humidity_pct")),
            "precipitation_probability": raw_context.get(
                "precipitation_probability",
                weather.get("precipitation_probability"),
            ),
        },
        "park_factors": {
            "run_factor": run_factor,
            "home_run_factor": raw_context.get("home_run_factor"),
            "hit_factor": raw_context.get("hit_factor"),
        },
        "game_context": {
            "venue_name": raw_context.get("venue_name"),
            "roof_status": raw_context.get("roof_status"),
            "home_team": raw_context.get("home_team"),
            "away_team": raw_context.get("away_team"),
            "game_time_local": raw_context.get("game_time_local", raw_context.get("game_date")),
            "game_status": raw_context.get("game_status", raw_context.get("status")),
        },
        "run_environment": {
            "scoring_environment_label": raw_context.get(
                "scoring_environment_label",
                _park_label(run_factor),
            ),
            "weather_run_impact": raw_context.get(
                "weather_run_impact",
                _weather_impact(temperature_f, wind_speed_mph),
            ),
            "park_run_impact": raw_context.get(
                "park_run_impact",
                _park_label(run_factor),
            ),
        },
        "risk_flags": {
            "rain_delay_risk": raw_context.get(
                "rain_delay_risk",
                "rain" in str(condition or "").lower(),
            ),
            "postponement_risk": raw_context.get("postponement_risk", False),
            "extreme_wind_flag": raw_context.get(
                "extreme_wind_flag",
                wind_speed_mph is not None and wind_speed_mph >= 15,
            ),
            "extreme_temperature_flag": raw_context.get(
                "extreme_temperature_flag",
                temperature_f is not None and (temperature_f <= 40 or temperature_f >= 95),
            ),
        },
        "status": {
            "is_stub": raw_context.get("is_stub", False),
            "readiness": raw_context.get(
                "readiness",
                "partial" if missing_inputs else "ready",
            ),
            "missing_inputs": raw_context.get("missing_inputs", missing_inputs),
        },
    }

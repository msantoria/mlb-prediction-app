"""
Environment data retrieval utilities for matchup previews.

This module provides a lightweight backend adapter layer for game-level
environment context. It currently supports:

- stadium coordinate lookup
- weather retrieval from Open-Meteo
- park factor lookup from a static in-repo table
- composition of environment context for environment profiles

The goal is to populate environment profiles with real data when possible
while preserving an honest, contract-stable fallback when data is missing.
"""

from __future__ import annotations

from typing import Dict, Optional

import requests


STADIUM_COORDINATES: Dict[str, Dict[str, object]] = {
    "Chase Field": {"lat": 33.445, "lon": -112.067, "timezone": "America/Phoenix"},
    "Truist Park": {"lat": 33.891, "lon": -84.389, "timezone": "America/New_York"},
    "Oriole Park at Camden Yards": {"lat": 39.284, "lon": -76.622, "timezone": "America/New_York"},
    "Fenway Park": {"lat": 42.346, "lon": -71.098, "timezone": "America/New_York"},
    "Wrigley Field": {"lat": 41.948, "lon": -87.656, "timezone": "America/Chicago"},
    "Rate Field": {"lat": 41.830, "lon": -87.634, "timezone": "America/Chicago"},
    "Great American Ball Park": {"lat": 39.097, "lon": -84.507, "timezone": "America/New_York"},
    "Progressive Field": {"lat": 41.496, "lon": -81.685, "timezone": "America/New_York"},
    "Coors Field": {"lat": 39.756, "lon": -104.994, "timezone": "America/Denver"},
    "Comerica Park": {"lat": 42.339, "lon": -83.049, "timezone": "America/New_York"},
    "Daikin Park": {"lat": 29.757, "lon": -95.356, "timezone": "America/Chicago"},
    "Kauffman Stadium": {"lat": 39.051, "lon": -94.481, "timezone": "America/Chicago"},
    "Angel Stadium": {"lat": 33.800, "lon": -117.883, "timezone": "America/Los_Angeles"},
    "Dodger Stadium": {"lat": 34.074, "lon": -118.240, "timezone": "America/Los_Angeles"},
    "LoanDepot Park": {"lat": 25.778, "lon": -80.220, "timezone": "America/New_York"},
    "American Family Field": {"lat": 43.028, "lon": -87.971, "timezone": "America/Chicago"},
    "Target Field": {"lat": 44.981, "lon": -93.278, "timezone": "America/Chicago"},
    "Citi Field": {"lat": 40.757, "lon": -73.846, "timezone": "America/New_York"},
    "Yankee Stadium": {"lat": 40.830, "lon": -73.926, "timezone": "America/New_York"},
    "Sutter Health Park": {"lat": 38.580, "lon": -121.507, "timezone": "America/Los_Angeles"},
    "Citizens Bank Park": {"lat": 39.906, "lon": -75.166, "timezone": "America/New_York"},
    "PNC Park": {"lat": 40.447, "lon": -80.006, "timezone": "America/New_York"},
    "Petco Park": {"lat": 32.707, "lon": -117.157, "timezone": "America/Los_Angeles"},
    "Oracle Park": {"lat": 37.778, "lon": -122.389, "timezone": "America/Los_Angeles"},
    "T-Mobile Park": {"lat": 47.591, "lon": -122.333, "timezone": "America/Los_Angeles"},
    "Busch Stadium": {"lat": 38.622, "lon": -90.193, "timezone": "America/Chicago"},
    "Tropicana Field": {"lat": 27.768, "lon": -82.653, "timezone": "America/New_York"},
    "Globe Life Field": {"lat": 32.747, "lon": -97.084, "timezone": "America/Chicago"},
    "Rogers Centre": {"lat": 43.641, "lon": -79.389, "timezone": "America/Toronto"},
    "Nationals Park": {"lat": 38.873, "lon": -77.008, "timezone": "America/New_York"},
}


PARK_FACTORS: Dict[str, Dict[str, Optional[float]]] = {
    "Wrigley Field": {"run_factor": 101.0, "home_run_factor": 104.0, "hit_factor": 100.0},
    "Fenway Park": {"run_factor": 105.0, "home_run_factor": 102.0, "hit_factor": 108.0},
    "Yankee Stadium": {"run_factor": 103.0, "home_run_factor": 109.0, "hit_factor": 100.0},
    "Dodger Stadium": {"run_factor": 99.0, "home_run_factor": 100.0, "hit_factor": 98.0},
    "Oracle Park": {"run_factor": 95.0, "home_run_factor": 90.0, "hit_factor": 94.0},
    "Coors Field": {"run_factor": 118.0, "home_run_factor": 115.0, "hit_factor": 112.0},
    "Petco Park": {"run_factor": 96.0, "home_run_factor": 94.0, "hit_factor": 97.0},
}


def _degrees_to_compass(degrees: Optional[float]) -> Optional[str]:
    """Convert meteorological wind direction degrees into a coarse compass label."""
    if degrees is None:
        return None
    directions = [
        "N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
        "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW",
    ]
    idx = round(degrees / 22.5) % 16
    return directions[idx]


def get_stadium_lookup(venue_name: str) -> Dict[str, object]:
    """Return coordinate/timezone metadata for a venue name."""
    return STADIUM_COORDINATES.get(venue_name, {})


def get_game_weather(venue_name: str, game_time_iso: str) -> Dict[str, object]:
    """
    Retrieve approximate game-time weather for a venue using Open-Meteo.

    This implementation uses hourly forecast data keyed off stadium coordinates.
    If weather cannot be fetched, returns a contract-safe partial payload.
    """
    venue = get_stadium_lookup(venue_name)
    lat = venue.get("lat")
    lon = venue.get("lon")
    timezone = venue.get("timezone", "auto")

    if lat is None or lon is None:
        return {
            "temperature_f": None,
            "wind_speed_mph": None,
            "wind_direction": None,
            "humidity_pct": None,
            "precipitation_probability": None,
            "source_fields_used": [],
            "weather_readiness": "stub",
        }

    url = "https://api.open-meteo.com/v1/forecast"
    params = {
        "latitude": lat,
        "longitude": lon,
        "hourly": ",".join(
            [
                "temperature_2m",
                "relative_humidity_2m",
                "precipitation_probability",
                "wind_speed_10m",
                "wind_direction_10m",
            ]
        ),
        "forecast_days": 1,
        "timezone": timezone,
    }

    try:
        response = requests.get(url, params=params, timeout=15)
        response.raise_for_status()
        data = response.json()
    except requests.RequestException:
        return {
            "temperature_f": None,
            "wind_speed_mph": None,
            "wind_direction": None,
            "humidity_pct": None,
            "precipitation_probability": None,
            "source_fields_used": [],
            "weather_readiness": "stub",
        }

    hourly = data.get("hourly", {})
    temperature_c = (hourly.get("temperature_2m") or [None])[0]
    humidity_pct = (hourly.get("relative_humidity_2m") or [None])[0]
    precipitation_probability = (hourly.get("precipitation_probability") or [None])[0]
    wind_speed_kmh = (hourly.get("wind_speed_10m") or [None])[0]
    wind_direction_deg = (hourly.get("wind_direction_10m") or [None])[0]

    temperature_f = None if temperature_c is None else (temperature_c * 9 / 5) + 32
    wind_speed_mph = None if wind_speed_kmh is None else wind_speed_kmh * 0.621371
    wind_direction = _degrees_to_compass(wind_direction_deg)

    return {
        "temperature_f": temperature_f,
        "wind_speed_mph": wind_speed_mph,
        "wind_direction": wind_direction,
        "humidity_pct": humidity_pct,
        "precipitation_probability": precipitation_probability,
        "source_fields_used": [
            "temperature_2m",
            "relative_humidity_2m",
            "precipitation_probability",
            "wind_speed_10m",
            "wind_direction_10m",
        ],
        "weather_readiness": "ready" if temperature_f is not None else "partial",
    }


def get_park_factors(venue_name: str) -> Dict[str, object]:
    """
    Return park factor values for a venue.

    This v1 implementation uses a static adapter table. Missing venues remain
    contract-safe with null values.
    """
    factors = PARK_FACTORS.get(venue_name, {})
    return {
        "run_factor": factors.get("run_factor"),
        "home_run_factor": factors.get("home_run_factor"),
        "hit_factor": factors.get("hit_factor"),
        "source_fields_used": [
            key for key in ("run_factor", "home_run_factor", "hit_factor") if key in factors
        ],
        "park_readiness": "ready" if factors else "stub",
    }


def build_environment_context(game: dict) -> Dict[str, object]:
    """
    Build a combined raw environment context from schedule, weather, and park inputs.
    """
    venue = game.get("venue", {}) or {}
    venue_name = venue.get("name")
    game_time = game.get("gameDate")

    home_team = game.get("teams", {}).get("home", {}).get("team", {}).get("name")
    away_team = game.get("teams", {}).get("away", {}).get("team", {}).get("name")

    weather = get_game_weather(venue_name, game_time) if venue_name and game_time else {}
    park = get_park_factors(venue_name) if venue_name else {}

    missing_inputs = []
    for key in (
        "temperature_f",
        "wind_speed_mph",
        "wind_direction",
        "humidity_pct",
        "precipitation_probability",
        "run_factor",
        "home_run_factor",
        "hit_factor",
    ):
        if key not in {**weather, **park} or ({**weather, **park}).get(key) is None:
            missing_inputs.append(key)

    weather_ready = weather.get("weather_readiness") == "ready"
    park_ready = park.get("park_readiness") == "ready"

    if weather_ready and park_ready:
        readiness = "ready"
    elif weather_ready or park_ready:
        readiness = "partial"
    else:
        readiness = "stub"

    return {
        "venue_name": venue_name,
        "roof_status": None,
        "home_team": home_team,
        "away_team": away_team,
        "game_time_local": game_time,
        "temperature_f": weather.get("temperature_f"),
        "wind_speed_mph": weather.get("wind_speed_mph"),
        "wind_direction": weather.get("wind_direction"),
        "humidity_pct": weather.get("humidity_pct"),
        "precipitation_probability": weather.get("precipitation_probability"),
        "run_factor": park.get("run_factor"),
        "home_run_factor": park.get("home_run_factor"),
        "hit_factor": park.get("hit_factor"),
        "scoring_environment_label": None,
        "weather_run_impact": None,
        "park_run_impact": None,
        "rain_delay_risk": None,
        "postponement_risk": None,
        "extreme_wind_flag": (
            weather.get("wind_speed_mph") is not None and weather.get("wind_speed_mph") >= 15
        ),
        "extreme_temperature_flag": (
            weather.get("temperature_f") is not None
            and (weather.get("temperature_f") <= 45 or weather.get("temperature_f") >= 90)
        ),
        "source_type": "weather_api + park_factor_lookup",
        "source_fields_used": sorted(
            list(set(weather.get("source_fields_used", []) + park.get("source_fields_used", [])))
        ),
        "data_confidence": "medium" if readiness in ("ready", "partial") else "low",
        "generated_from": "build_environment_context",
        "is_stub": readiness == "stub",
        "readiness": readiness,
        "missing_inputs": missing_inputs,
    }

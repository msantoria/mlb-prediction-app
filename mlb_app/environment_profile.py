"""
Utilities for building environment profile summaries for matchup previews.

This module defines a game-level environment profile structure that can later
be populated with real weather, park factor, and contextual inputs.
"""

import re

from .environment.weather_atmospheric_contract import (
    resolve_roof_state,
)
from .park_factors import get_park_factor_profile


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

    def _parse_wind_text(value):
        text = str(value or "").strip()
        if not text:
            return None, None

        speed = None
        speed_match = re.search(r"(\d+(?:\.\d+)?)\s*mph", text, re.IGNORECASE)
        if speed_match:
            speed = _safe_float(speed_match.group(1))

        direction = text
        direction = re.sub(r"^\s*\d+(?:\.\d+)?\s*mph\s*,?\s*", "", direction, flags=re.IGNORECASE)
        direction = direction.strip(" ,") or None

        return speed, direction

    calibration = {
        "environment_calibration_version": "env_calibration_v2",
        "park_weight": 1.00,
        "temperature_weight": 1.00,
        "wind_weight": 1.00,
        "max_weather_adjustment": 0.075,
        "neutral_index": 1.000,
    }

    def _clamp(value, lower, upper):
        if value is None:
            return None
        return max(lower, min(upper, value))

    def _combined_environment_index(
        base_index,
        weather_adjustment,
    ):
        """
        Preserve the complete sourced park factor and bound only
        the incremental forecast-based weather contribution.
        """
        base = (
            base_index
            if base_index is not None
            else calibration["neutral_index"]
        )
        bounded_weather = _clamp(
            weather_adjustment,
            -calibration["max_weather_adjustment"],
            calibration["max_weather_adjustment"],
        )
        return round(base + bounded_weather, 3)

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

    def _park_factor_proxy(run_factor, multiplier):
        """
        Derive a positive factor without flattening the underlying
        park signal through a generic upper or lower ceiling.
        """
        if run_factor is None:
            return None
        value = 1.0 + (
            (run_factor - 1.0) * multiplier
        )
        if value <= 0.0:
            return None
        return round(value, 3)

    def _wind_direction_type(wind_direction):
        text = str(wind_direction or "").lower()
        if not text:
            return None
        if "in from" in text or "blowing in" in text or text.startswith("in "):
            return "in"
        if "out to" in text or "blowing out" in text or text.startswith("out "):
            return "out"
        if "cross" in text or "r to l" in text or "l to r" in text or "right to left" in text or "left to right" in text:
            return "cross"
        return "unknown"

    def _wind_speed_tier(wind_speed):
        if wind_speed is None:
            return None
        if wind_speed >= 15:
            return "strong"
        if wind_speed >= 10:
            return "moderate"
        if wind_speed >= 6:
            return "mild"
        return "calm"

    def _wind_adjustments(wind_speed, wind_direction):
        direction_type = _wind_direction_type(wind_direction)
        tier = _wind_speed_tier(wind_speed)

        base = {
            "calm": 0.0,
            "mild": 0.01,
            "moderate": 0.025,
            "strong": 0.04,
        }.get(tier, 0.0)

        direction_multiplier = {
            "out": 1.0,
            "in": -1.0,
            "cross": -0.25,
            "unknown": 0.0,
            None: 0.0,
        }.get(direction_type, 0.0)

        wind_weight = calibration["wind_weight"]
        hr_adjustment = round(base * 1.50 * direction_multiplier * wind_weight, 3)
        run_adjustment = round(base * 0.85 * direction_multiplier * wind_weight, 3)
        hit_adjustment = round(base * 0.25 * direction_multiplier * wind_weight, 3)

        return {
            "wind_direction_type": direction_type,
            "wind_speed_tier": tier,
            "wind_hr_adjustment": hr_adjustment,
            "wind_run_adjustment": run_adjustment,
            "wind_hit_adjustment": hit_adjustment,
        }

    def _wind_impact(wind_speed, wind_direction):
        direction_type = _wind_direction_type(wind_direction)
        tier = _wind_speed_tier(wind_speed)
        if wind_speed is None:
            return None
        if direction_type == "in" and tier in {"moderate", "strong"}:
            return "wind_in_suppresses_carry"
        if direction_type == "out" and tier in {"moderate", "strong"}:
            return "wind_out_boosts_carry"
        if direction_type == "cross" and tier in {"moderate", "strong"}:
            return "crosswind_may_affect_carry"
        if tier in {"moderate", "strong"}:
            return "wind_may_affect_carry"
        if tier == "mild" and direction_type == "in":
            return "mild_wind_in_slight_suppression"
        if tier == "mild" and direction_type == "out":
            return "mild_wind_out_slight_boost"
        return "limited_wind_impact"

    def _temperature_impact(temp_f):
        if temp_f is None:
            return None
        if temp_f >= 85:
            return "hot_air_boosts_carry"
        if temp_f >= 75:
            return "warm_air_slight_boost"
        if temp_f <= 45:
            return "cold_air_strongly_suppresses_carry"
        if temp_f <= 55:
            return "cold_air_suppresses_carry"
        return "neutral_temperature"

    def _weather_impact(temp_f, wind_speed, wind_direction):
        wind = _wind_impact(wind_speed, wind_direction)
        temp = _temperature_impact(temp_f)

        if wind in {"wind_in_suppresses_carry", "wind_out_boosts_carry"}:
            return wind
        if temp in {"hot_air_boosts_carry", "cold_air_strongly_suppresses_carry", "cold_air_suppresses_carry"}:
            return temp
        if wind:
            return wind
        return temp or "neutral_or_unknown"

    def _temperature_adjustment(temp_f):
        temp = _temperature_impact(temp_f)
        temperature_weight = calibration["temperature_weight"]
        if temp == "hot_air_boosts_carry":
            return 0.03 * temperature_weight
        if temp == "warm_air_slight_boost":
            return 0.01 * temperature_weight
        if temp == "cold_air_strongly_suppresses_carry":
            return -0.04 * temperature_weight
        if temp == "cold_air_suppresses_carry":
            return -0.02 * temperature_weight
        return 0.0

    def _run_scoring_index(run_factor, temp_f, wind_speed, wind_direction):
        base = run_factor if run_factor is not None else calibration["neutral_index"]
        weather_adjustment = _temperature_adjustment(temp_f) + _wind_adjustments(wind_speed, wind_direction)["wind_run_adjustment"]
        weather_adjustment = _clamp(
            weather_adjustment,
            -calibration["max_weather_adjustment"],
            calibration["max_weather_adjustment"],
        )
        return _combined_environment_index(base, weather_adjustment)

    def _scoring_label(index):
        if index is None:
            return None
        if index >= 1.08:
            return "offense_boost"
        if index >= 1.03:
            return "slight_offense_boost"
        if index <= 0.92:
            return "run_suppression"
        if index <= 0.97:
            return "slight_run_suppression"
        return "neutral"

    temperature_f = raw_context.get("temperature_f", weather.get("temp_f"))
    wind_raw = raw_context.get("wind_direction", weather.get("wind_direction") or weather.get("wind"))
    wind_speed_mph = raw_context.get("wind_speed_mph", weather.get("wind_speed_mph"))
    wind_direction = wind_raw
    parsed_wind_speed, parsed_wind_direction = _parse_wind_text(wind_raw)
    condition = raw_context.get("condition", weather.get("condition"))

    temperature_f = _safe_float(temperature_f)
    wind_speed_mph = _safe_float(wind_speed_mph)
    if wind_speed_mph is None and parsed_wind_speed is not None:
        wind_speed_mph = parsed_wind_speed
    if parsed_wind_direction:
        wind_direction = parsed_wind_direction

    park_factor_profile = raw_context.get("park_factor_profile") or {}
    venue_name = raw_context.get("venue_name")
    if not park_factor_profile and venue_name:
        park_factor_profile = get_park_factor_profile(venue_name)

    venue_type = str(
        park_factor_profile.get("venue_type")
        or "unknown"
    ).strip().lower()
    raw_roof_status = raw_context.get("roof_status")
    default_roof_status = (
        park_factor_profile.get("default_roof_status")
    )

    roof_type = {
        "outdoor": "open_air",
        "open_air": "open_air",
        "dome": "fixed_dome",
        "fixed_dome": "fixed_dome",
        "retractable": "retractable",
    }.get(venue_type, "unknown")

    if roof_type == "open_air":
        roof_state = "not_applicable"
    elif roof_type == "fixed_dome":
        roof_state = "fixed_closed"
    else:
        roof_state = str(
            raw_roof_status
            if raw_roof_status is not None
            else default_roof_status
            or "unknown"
        ).strip().lower()

        roof_state = {
            "roof open": "open",
            "open roof": "open",
            "roof closed": "closed",
            "closed roof": "closed",
            "dome": "fixed_closed",
        }.get(roof_state, roof_state)

        if roof_state not in {
            "open",
            "closed",
            "fixed_closed",
            "not_applicable",
            "unknown",
        }:
            roof_state = "unknown"

    roof_resolution = resolve_roof_state(
        roof_type,
        roof_state,
    )

    weather_application_allowed = (
        roof_resolution.valid
        and roof_resolution.weather_behavior
        == "outdoor_weather_retained"
    )

    if weather_application_allowed:
        applied_temperature_f = temperature_f
        applied_wind_speed_mph = wind_speed_mph
        applied_wind_direction = wind_direction
        weather_application_status = "applied"
    else:
        applied_temperature_f = None
        applied_wind_speed_mph = None
        applied_wind_direction = None
        weather_application_status = (
            "neutralized_unknown_roof"
            if roof_state == "unknown"
            else "neutralized_indoor"
            if roof_resolution.indoor_effective
            else "neutralized_invalid_roof"
        )

    raw_run_factor = raw_context.get("run_factor", raw_context.get("park_factor"))
    run_factor = _safe_float(raw_run_factor)

    raw_home_run_factor = _safe_float(raw_context.get("home_run_factor"))
    raw_home_run_factor_lhb = _safe_float(raw_context.get("home_run_factor_lhb"))
    raw_home_run_factor_rhb = _safe_float(raw_context.get("home_run_factor_rhb"))
    raw_hit_factor = _safe_float(raw_context.get("hit_factor"))

    park_factor_profile_found = bool(park_factor_profile.get("park_factor_profile_found"))
    static_park_factor_used = False

    if run_factor is None:
        run_factor = _safe_float(park_factor_profile.get("run_factor"))
        static_park_factor_used = run_factor is not None and park_factor_profile.get("source") != "neutral_fallback_unmapped_venue"

    home_run_factor = raw_home_run_factor
    home_run_factor_lhb = raw_home_run_factor_lhb
    home_run_factor_rhb = raw_home_run_factor_rhb
    hit_factor = raw_hit_factor

    if home_run_factor is None:
        home_run_factor = _safe_float(park_factor_profile.get("home_run_factor"))
    if home_run_factor_lhb is None:
        home_run_factor_lhb = _safe_float(park_factor_profile.get("home_run_factor_lhb"))
    if home_run_factor_rhb is None:
        home_run_factor_rhb = _safe_float(park_factor_profile.get("home_run_factor_rhb"))
    if hit_factor is None:
        hit_factor = _safe_float(park_factor_profile.get("hit_factor"))

    park_factor_fallback_used = False
    park_factor_fallback_source = None

    if home_run_factor is None and run_factor is not None:
        home_run_factor = _park_factor_proxy(
            run_factor,
            multiplier=1.10,
        )
        park_factor_fallback_used = True
        park_factor_fallback_source = "run_factor_proxy"
    if hit_factor is None and run_factor is not None:
        hit_factor = _park_factor_proxy(
            run_factor,
            multiplier=0.60,
        )
        park_factor_fallback_used = True
        park_factor_fallback_source = "run_factor_proxy"

    if run_factor is None:
        run_factor = calibration["neutral_index"]
        park_factor_fallback_used = True
        park_factor_fallback_source = "neutral_fallback_missing_venue_or_park_factor"
    if home_run_factor is None:
        home_run_factor = calibration["neutral_index"]
    if hit_factor is None:
        hit_factor = calibration["neutral_index"]

    wind_adjustments = _wind_adjustments(
        applied_wind_speed_mph,
        applied_wind_direction,
    )

    run_scoring_index = raw_context.get(
        "run_scoring_index",
        _run_scoring_index(
            run_factor,
            applied_temperature_f,
            applied_wind_speed_mph,
            applied_wind_direction,
        ),
    )
    base_index = run_factor if run_factor is not None else calibration["neutral_index"]
    hr_base_index = home_run_factor if home_run_factor is not None else base_index
    hit_base_index = hit_factor if hit_factor is not None else base_index

    hr_boost_index = raw_context.get(
        "hr_boost_index",
        _combined_environment_index(
            hr_base_index,
            _temperature_adjustment(
                applied_temperature_f
            )
            + wind_adjustments[
                "wind_hr_adjustment"
            ],
        ),
    )
    hit_boost_index = raw_context.get(
        "hit_boost_index",
        _combined_environment_index(
            hit_base_index,
            (
                _temperature_adjustment(
                    applied_temperature_f
                )
                * 0.35
            )
            + wind_adjustments[
                "wind_hit_adjustment"
            ],
        ),
    )

    missing_inputs = []
    if temperature_f is None:
        missing_inputs.append("temperature_f")
    if wind_speed_mph is None and not wind_direction:
        missing_inputs.append("wind")
    if not park_factor_profile_found and not static_park_factor_used:
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

    temperature_adjustment = _temperature_adjustment(
        applied_temperature_f
    )

    weather_run_adjustment = _clamp(
        temperature_adjustment
        + wind_adjustments["wind_run_adjustment"],
        -calibration["max_weather_adjustment"],
        calibration["max_weather_adjustment"],
    )
    weather_hr_adjustment = _clamp(
        temperature_adjustment
        + wind_adjustments["wind_hr_adjustment"],
        -calibration["max_weather_adjustment"],
        calibration["max_weather_adjustment"],
    )
    weather_hit_adjustment = _clamp(
        (temperature_adjustment * 0.35)
        + wind_adjustments["wind_hit_adjustment"],
        -calibration["max_weather_adjustment"],
        calibration["max_weather_adjustment"],
    )

    def _adjustment_breakdown(
        *,
        park_factor,
        weather_adjustment,
        final_index,
    ):
        park_adjustment = round(
            park_factor - calibration["neutral_index"],
            3,
        )
        applied_weather_adjustment = round(
            weather_adjustment,
            4,
        )
        full_adjustment = round(
            final_index - calibration["neutral_index"],
            3,
        )
        expected_final = round(
            park_factor + applied_weather_adjustment,
            3,
        )

        return {
            "park_factor": round(park_factor, 3),
            "park_adjustment": park_adjustment,
            "weather_adjustment": (
                applied_weather_adjustment
            ),
            "full_adjustment": full_adjustment,
            "final_index": round(final_index, 3),
            "reconciles_to_components": (
                abs(expected_final - final_index)
                <= 0.001
            ),
        }

    environment_adjustment_breakdown = {
        "run_scoring": _adjustment_breakdown(
            park_factor=run_factor,
            weather_adjustment=weather_run_adjustment,
            final_index=run_scoring_index,
        ),
        "hits": _adjustment_breakdown(
            park_factor=hit_factor,
            weather_adjustment=weather_hit_adjustment,
            final_index=hit_boost_index,
        ),
        "home_runs": _adjustment_breakdown(
            park_factor=home_run_factor,
            weather_adjustment=weather_hr_adjustment,
            final_index=hr_boost_index,
        ),
    }

    if raw_run_factor is not None:
        park_component_source = "real_or_schedule_provided"
    elif static_park_factor_used:
        park_component_source = park_factor_profile.get("source") or "static_park_factor_v1"
    elif park_factor_profile.get("source"):
        park_component_source = park_factor_profile.get("source")
    else:
        park_component_source = "neutral_fallback"

    if park_factor_fallback_used and park_factor_fallback_source and not static_park_factor_used:
        park_component_source = park_factor_fallback_source

    weather_component_source = "schedule_weather" if temperature_f is not None or wind_speed_mph is not None or wind_direction else "missing_weather"
    combined_index_method = "additive_base_plus_weather_adjustment"

    return {
        "metadata": {
            "source_type": raw_context.get("source_type", "matchup_detail_context"),
            "source_fields_used": raw_context.get("source_fields_used", source_fields_used),
            "data_confidence": raw_context.get(
                "data_confidence",
                "medium" if run_factor is not None or weather else "low",
            ),
            "generated_from": raw_context.get("generated_from", "compute_environment_profile"),
            "environment_calibration_version": calibration["environment_calibration_version"],
            "park_weight": calibration["park_weight"],
            "temperature_weight": calibration["temperature_weight"],
            "wind_weight": calibration["wind_weight"],
            "max_weather_adjustment": calibration["max_weather_adjustment"],
            "park_factor_preservation_policy": (
                "preserve_sourced_park_factor_"
                "bound_weather_only_v1"
            ),
            "wind_raw": wind_raw,
            "wind_parsed_from_text": parsed_wind_speed is not None or bool(parsed_wind_direction),
            "park_factor_fallback_used": park_factor_fallback_used,
            "park_factor_fallback_source": park_factor_fallback_source,
            "combined_index_method": combined_index_method,
            "roof_weather_policy": (
                "explicit_open_or_open_air_weather_"
                "otherwise_neutral_v1"
            ),
            "weather_application_status": (
                weather_application_status
            ),
        },
        "environment_components": {
            "combined_index_method": combined_index_method,
            "adjustment_breakdown": (
                environment_adjustment_breakdown
            ),
            "park_component": {
                "run_factor": run_factor,
                "home_run_factor": home_run_factor,
                "home_run_factor_lhb": home_run_factor_lhb,
                "home_run_factor_rhb": home_run_factor_rhb,
                "hit_factor": hit_factor,
                "source": park_component_source,
                "park_factor_profile_found": park_factor_profile_found,
                "static_park_factor_used": static_park_factor_used,
                "normalized_venue_name": park_factor_profile.get("normalized_venue_name"),
                "venue_type": park_factor_profile.get("venue_type"),
                "default_roof_status": park_factor_profile.get("default_roof_status"),
                "weather_applies_default": park_factor_profile.get("weather_applies_default"),
                "neutral_fallback_used": bool(park_factor_profile.get("neutral_park_fallback_used")),
                "proxy_from_run_factor_used": park_factor_fallback_used,
                "proxy_source": park_factor_fallback_source,
            },
            "weather_component": {
                "temperature_f": temperature_f,
                "wind_speed_mph": wind_speed_mph,
                "wind_direction": wind_direction,
                "applied_temperature_f": (
                    applied_temperature_f
                ),
                "applied_wind_speed_mph": (
                    applied_wind_speed_mph
                ),
                "applied_wind_direction": (
                    applied_wind_direction
                ),
                "weather_application_allowed": (
                    weather_application_allowed
                ),
                "weather_application_status": (
                    weather_application_status
                ),
                "roof_resolution": (
                    roof_resolution.to_dict()
                ),
                "wind_direction_type": wind_adjustments["wind_direction_type"],
                "wind_speed_tier": wind_adjustments["wind_speed_tier"],
                "temperature_adjustment": temperature_adjustment,
                "wind_run_adjustment": wind_adjustments["wind_run_adjustment"],
                "wind_hr_adjustment": wind_adjustments["wind_hr_adjustment"],
                "wind_hit_adjustment": wind_adjustments["wind_hit_adjustment"],
                "source": weather_component_source,
            },
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
            "home_run_factor": home_run_factor,
            "home_run_factor_lhb": home_run_factor_lhb,
            "home_run_factor_rhb": home_run_factor_rhb,
            "hit_factor": hit_factor,
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
            "run_scoring_index": run_scoring_index,
            "hr_boost_index": hr_boost_index,
            "hit_boost_index": hit_boost_index,
            "scoring_environment_label": raw_context.get(
                "scoring_environment_label",
                _scoring_label(run_scoring_index),
            ),
            "weather_run_impact": raw_context.get(
                "weather_run_impact",
                _weather_impact(temperature_f, wind_speed_mph, wind_direction),
            ),
            "park_run_impact": raw_context.get(
                "park_run_impact",
                _park_label(run_factor),
            ),
            "wind_run_impact": raw_context.get(
                "wind_run_impact",
                _wind_impact(wind_speed_mph, wind_direction),
            ),
            "wind_direction_type": raw_context.get(
                "wind_direction_type",
                wind_adjustments["wind_direction_type"],
            ),
            "wind_speed_tier": raw_context.get(
                "wind_speed_tier",
                wind_adjustments["wind_speed_tier"],
            ),
            "wind_run_adjustment": raw_context.get(
                "wind_run_adjustment",
                wind_adjustments["wind_run_adjustment"],
            ),
            "wind_hr_adjustment": raw_context.get(
                "wind_hr_adjustment",
                wind_adjustments["wind_hr_adjustment"],
            ),
            "wind_hit_adjustment": raw_context.get(
                "wind_hit_adjustment",
                wind_adjustments["wind_hit_adjustment"],
            ),
            "temperature_run_impact": raw_context.get(
                "temperature_run_impact",
                _temperature_impact(temperature_f),
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

"""
Utilities for building hitter profile summaries for matchup previews.

This module defines a player-level hitter profile structure that can later
be populated with real calculations from split and Statcast inputs.
"""


def _safe_rate(numerator, denominator):
    """Return numerator / denominator when both are available and denominator > 0."""
    if numerator is None or denominator in (None, 0):
        return None
    return numerator / denominator


def _safe_difference(a, b):
    """Return a - b when both values are available."""
    if a is None or b is None:
        return None
    return a - b


def compute_hitter_profile(raw_stats: dict) -> dict:
    """
    Build a structured hitter profile from raw hitter inputs.

    Parameters
    ----------
    raw_stats : dict
        Dictionary of hitter stats from upstream ingestion or transformed sources.

    Returns
    -------
    dict
        A structured player-level hitter profile using raw metrics grouped
        by trait. Missing fields are returned as None.
    """
    raw_stats = raw_stats or {}

    plate_appearances = raw_stats.get("plateAppearances")
    strikeouts = raw_stats.get("strikeOuts")
    walks = raw_stats.get("baseOnBalls")
    avg = raw_stats.get("avg")
    slg = raw_stats.get("slg")

    k_rate = raw_stats.get("k_rate", raw_stats.get("k_pct"))
    if k_rate is None:
        k_rate = _safe_rate(strikeouts, plate_appearances)

    bb_rate = raw_stats.get("bb_rate", raw_stats.get("bb_pct"))
    if bb_rate is None:
        bb_rate = _safe_rate(walks, plate_appearances)

    iso = raw_stats.get("iso")
    if iso is None:
        iso = _safe_difference(slg, avg)

    return {
        "metadata": {
            "source_type": raw_stats.get("source_type", "unknown"),
            "source_fields_used": raw_stats.get("source_fields_used", []),
            "data_confidence": raw_stats.get("data_confidence", "unknown"),
            "generated_from": raw_stats.get("generated_from", "compute_hitter_profile"),
            "profile_granularity": raw_stats.get("profile_granularity", "player"),
            "is_projected_lineup_derived": raw_stats.get("is_projected_lineup_derived", False),
        },
        "contact_skill": {
            "k_rate": k_rate,
            "whiff_rate": raw_stats.get("whiff_rate"),
            "contact_rate": raw_stats.get("contact_rate"),
        },
        "plate_discipline": {
            "bb_rate": bb_rate,
            "chase_rate": raw_stats.get("chase_rate"),
            "swing_rate": raw_stats.get("swing_rate"),
        },
        "power": {
            "iso": iso,
            "barrel_rate": raw_stats.get("barrel_rate", raw_stats.get("barrel_pct")),
            "hard_hit_rate": raw_stats.get("hard_hit_rate", raw_stats.get("hard_hit_pct")),
        },
        "batted_ball_quality": {
            "avg_exit_velocity": raw_stats.get("avg_exit_velocity", raw_stats.get("avg_exit_vel")),
            "avg_launch_angle": raw_stats.get("avg_launch_angle"),
        },
        "platoon_profile": {
            "vs_lhp_woba": raw_stats.get("vs_lhp_woba"),
            "vs_rhp_woba": raw_stats.get("vs_rhp_woba"),
            "vs_lhp_iso": raw_stats.get("vs_lhp_iso"),
            "vs_rhp_iso": raw_stats.get("vs_rhp_iso"),
        },
    }

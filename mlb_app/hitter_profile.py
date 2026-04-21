"""
Utilities for building hitter profile summaries for matchup previews.

This module defines a player-level hitter profile structure that can later
be populated with real calculations from split and Statcast inputs.
"""


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
    return {
        "contact_skill": {
            "k_rate": raw_stats.get("k_rate"),
            "whiff_rate": raw_stats.get("whiff_rate"),
            "contact_rate": raw_stats.get("contact_rate"),
        },
        "plate_discipline": {
            "bb_rate": raw_stats.get("bb_rate"),
            "chase_rate": raw_stats.get("chase_rate"),
            "swing_rate": raw_stats.get("swing_rate"),
        },
        "power": {
            "iso": raw_stats.get("iso"),
            "barrel_rate": raw_stats.get("barrel_rate"),
            "hard_hit_rate": raw_stats.get("hard_hit_rate"),
        },
        "batted_ball_quality": {
            "avg_exit_velocity": raw_stats.get("avg_exit_velocity"),
            "avg_launch_angle": raw_stats.get("avg_launch_angle"),
        },
        "platoon_profile": {
            "vs_lhp_woba": raw_stats.get("vs_lhp_woba"),
            "vs_rhp_woba": raw_stats.get("vs_rhp_woba"),
            "vs_lhp_iso": raw_stats.get("vs_lhp_iso"),
            "vs_rhp_iso": raw_stats.get("vs_rhp_iso"),
        },
    }

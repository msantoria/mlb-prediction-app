"""
Utilities for building pitcher profile summaries for matchup previews.

This module defines a player-level pitcher profile structure that can later
be populated with real calculations from split and Statcast inputs.
"""


def compute_pitcher_profile(raw_stats: dict) -> dict:
    """
    Build a structured pitcher profile from raw pitcher inputs.

    Parameters
    ----------
    raw_stats : dict
        Dictionary of pitcher stats from upstream ingestion or transformed sources.

    Returns
    -------
    dict
        A structured player-level pitcher profile using raw metrics grouped
        by trait. Missing fields are returned as None.
    """
    raw_stats = raw_stats or {}

    return {
        "metadata": {
            "source_type": raw_stats.get("source_type", "unknown"),
            "source_fields_used": raw_stats.get("source_fields_used", []),
            "data_confidence": raw_stats.get("data_confidence", "unknown"),
            "generated_from": raw_stats.get("generated_from", "compute_pitcher_profile"),
            **build_sample_metadata(
                window_name=raw_stats.get("sample_window", "last_365_days"),
                sample_size=raw_stats.get("sample_size"),
                sample_blend_policy=raw_stats.get("sample_blend_policy", "single_window_v1"),
                stabilizer_window=raw_stats.get("stabilizer_window"),
            ),
        },
        "arsenal": {
            "pitch_mix": raw_stats.get("pitch_mix"),
            "avg_velocity": raw_stats.get("avg_velocity"),
            "avg_spin_rate": raw_stats.get("avg_spin_rate", raw_stats.get("avg_spin")),
        },
        "bat_missing": {
            "k_rate": raw_stats.get("k_rate", raw_stats.get("k_pct")),
            "whiff_rate": raw_stats.get("whiff_rate"),
            "csw_rate": raw_stats.get("csw_rate"),
        },
        "command_control": {
            "bb_rate": raw_stats.get("bb_rate", raw_stats.get("bb_pct")),
            "zone_rate": raw_stats.get("zone_rate"),
            "first_pitch_strike_rate": raw_stats.get("first_pitch_strike_rate"),
        },
        "contact_management": {
            "hard_hit_rate_allowed": raw_stats.get(
                "hard_hit_rate_allowed", raw_stats.get("hard_hit_pct")
            ),
            "barrel_rate_allowed": raw_stats.get(
                "barrel_rate_allowed", raw_stats.get("barrel_pct_allowed")
            ),
            "avg_exit_velocity_allowed": raw_stats.get("avg_exit_velocity_allowed"),
            "avg_launch_angle_allowed": raw_stats.get("avg_launch_angle_allowed"),
        },
        "platoon_profile": {
            "vs_lhb_woba_allowed": raw_stats.get("vs_lhb_woba_allowed"),
            "vs_rhb_woba_allowed": raw_stats.get("vs_rhb_woba_allowed"),
            "vs_lhb_k_rate": raw_stats.get("vs_lhb_k_rate"),
            "vs_rhb_k_rate": raw_stats.get("vs_rhb_k_rate"),
            "vs_lhb_bb_rate": raw_stats.get("vs_lhb_bb_rate"),
            "vs_rhb_bb_rate": raw_stats.get("vs_rhb_bb_rate"),
        },
    }

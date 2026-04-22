"""
Offense profile aggregation utilities for matchup previews.

This module builds projected-lineup-aware offense profiles by:
- fetching player-level splits vs pitcher handedness
- converting those player split rows into hitter profiles
- aggregating those hitter profiles into one lineup offense profile
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from .hitter_profile import compute_hitter_profile
from .player_splits import fetch_player_splits


def _average(values: List[Optional[float]]) -> Optional[float]:
    nums = [v for v in values if v is not None]
    if not nums:
        return None
    return sum(nums) / len(nums)


def _extract_metric(profile: Dict[str, Any], section: str, field: str) -> Optional[float]:
    return (profile.get(section) or {}).get(field)


def aggregate_hitter_profiles(
    hitter_profiles: List[Dict[str, Any]],
    lineup_source: str,
    pitcher_hand: Optional[str],
    player_count_used: int,
) -> Dict[str, Any]:
    """
    Aggregate player-level hitter profiles into one projected-lineup offense profile.
    """
    return {
        "metadata": {
            "source_type": "projected_lineup_profile",
            "source_fields_used": ["player_splits", "compute_hitter_profile"],
            "data_confidence": "medium" if hitter_profiles else "low",
            "generated_from": "aggregate_hitter_profiles",
            "profile_granularity": "lineup_candidate_group",
            "is_projected_lineup_derived": lineup_source == "official",
            "lineup_source": lineup_source,
            "opposing_pitcher_hand": pitcher_hand if pitcher_hand in {"L", "R"} else "unknown",
            "player_count_used": player_count_used,
        },
        "contact_skill": {
            "k_rate": _average([_extract_metric(p, "contact_skill", "k_rate") for p in hitter_profiles]),
            "whiff_rate": _average([_extract_metric(p, "contact_skill", "whiff_rate") for p in hitter_profiles]),
            "contact_rate": _average([_extract_metric(p, "contact_skill", "contact_rate") for p in hitter_profiles]),
        },
        "plate_discipline": {
            "bb_rate": _average([_extract_metric(p, "plate_discipline", "bb_rate") for p in hitter_profiles]),
            "chase_rate": _average([_extract_metric(p, "plate_discipline", "chase_rate") for p in hitter_profiles]),
            "swing_rate": _average([_extract_metric(p, "plate_discipline", "swing_rate") for p in hitter_profiles]),
        },
        "power": {
            "iso": _average([_extract_metric(p, "power", "iso") for p in hitter_profiles]),
            "barrel_rate": _average([_extract_metric(p, "power", "barrel_rate") for p in hitter_profiles]),
            "hard_hit_rate": _average([_extract_metric(p, "power", "hard_hit_rate") for p in hitter_profiles]),
        },
        "batted_ball_quality": {
            "avg_exit_velocity": _average(
                [_extract_metric(p, "batted_ball_quality", "avg_exit_velocity") for p in hitter_profiles]
            ),
            "avg_launch_angle": _average(
                [_extract_metric(p, "batted_ball_quality", "avg_launch_angle") for p in hitter_profiles]
            ),
        },
        "platoon_profile": {
            "vs_lhp_woba": _average([_extract_metric(p, "platoon_profile", "vs_lhp_woba") for p in hitter_profiles]),
            "vs_rhp_woba": _average([_extract_metric(p, "platoon_profile", "vs_rhp_woba") for p in hitter_profiles]),
            "vs_lhp_iso": _average([_extract_metric(p, "platoon_profile", "vs_lhp_iso") for p in hitter_profiles]),
            "vs_rhp_iso": _average([_extract_metric(p, "platoon_profile", "vs_rhp_iso") for p in hitter_profiles]),
        },
    }


def build_projected_lineup_offense_profile(
    lineup: List[Dict[str, Any]],
    season: int,
    pitcher_hand: Optional[str],
    lineup_source: str,
) -> Dict[str, Any]:
    """
    Build a projected-lineup offense profile from player split data.

    Parameters
    ----------
    lineup : list of dict
        List of lineup player records containing at least `id`.
    season : int
        Season year.
    pitcher_hand : str or None
        Opposing pitcher throwing hand. Expected 'L', 'R', or None.
    lineup_source : str
        Source label such as 'official', 'roster', or 'missing'.

    Returns
    -------
    dict
        Aggregated offense profile with stable contract and explicit metadata.
    """
    player_ids = [p.get("id") for p in lineup if p.get("id")]
    if not player_ids:
        return aggregate_hitter_profiles(
            hitter_profiles=[],
            lineup_source="missing",
            pitcher_hand=pitcher_hand,
            player_count_used=0,
        )

    split_code = "vr" if pitcher_hand == "R" else "vl" if pitcher_hand == "L" else None
    all_splits = fetch_player_splits(player_ids, season)

    selected_rows = []
    if split_code:
        selected_rows = [row for row in all_splits if row.get("split") == split_code]
    else:
        selected_rows = []

    hitter_profiles = []
    for row in selected_rows:
        enriched_row = {
            **row,
            "source_type": "player_split",
            "source_fields_used": sorted(list(row.keys())),
            "data_confidence": "medium",
            "generated_from": "fetch_player_splits",
            "profile_granularity": "player",
            "is_projected_lineup_derived": lineup_source == "official",
        }
        hitter_profiles.append(compute_hitter_profile(enriched_row))

    return aggregate_hitter_profiles(
        hitter_profiles=hitter_profiles,
        lineup_source=lineup_source,
        pitcher_hand=pitcher_hand,
        player_count_used=len(player_ids),
    )

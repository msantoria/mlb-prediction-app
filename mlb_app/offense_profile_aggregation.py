"""
Offense profile aggregation utilities for matchup previews.

This module builds projected-lineup-aware offense profiles by:
- retrieving player-level split rows across multiple sample windows
- converting those rows into hitter profiles
- blending windowed hitter metrics
- aggregating blended hitter profiles into one lineup offense profile
"""

from __future__ import annotations

import datetime
from typing import Any, Dict, List, Optional

from .hitter_profile import compute_hitter_profile
from .hitter_windows import fetch_player_splits_for_window
from .sample_blending import HITTER_BLEND_WEIGHTS, blend_metric_dict


def _average(values: List[Optional[float]]) -> Optional[float]:
    nums = [v for v in values if v is not None]
    if not nums:
        return None
    return sum(nums) / len(nums)


def _extract_metric(profile: Dict[str, Any], section: str, field: str) -> Optional[float]:
    return (profile.get(section) or {}).get(field)


def _blend_hitter_profile_windows(window_profiles: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    """
    Blend multiple hitter profile windows into one player-level hitter profile.
    """
    return {
        "metadata": {
            "source_type": "player_split_blended",
            "source_fields_used": ["last_30_days", "last_90_days", "current_season"],
            "data_confidence": "medium" if window_profiles else "low",
            "generated_from": "_blend_hitter_profile_windows",
            "profile_granularity": "player",
            "is_projected_lineup_derived": True,
            "sample_window": "blended",
            "sample_family": "blended",
            "sample_description": "Weighted blend across hitter windows",
            "sample_days": None,
            "sample_size": None,
            "sample_blend_policy": "hitter_v1_weighted_blend",
            "stabilizer_window": "current_season",
        },
        "contact_skill": blend_metric_dict(
            {
                window_name: {
                    "k_rate": _extract_metric(profile, "contact_skill", "k_rate"),
                    "whiff_rate": _extract_metric(profile, "contact_skill", "whiff_rate"),
                    "contact_rate": _extract_metric(profile, "contact_skill", "contact_rate"),
                }
                for window_name, profile in window_profiles.items()
            },
            HITTER_BLEND_WEIGHTS,
        ),
        "plate_discipline": blend_metric_dict(
            {
                window_name: {
                    "bb_rate": _extract_metric(profile, "plate_discipline", "bb_rate"),
                    "chase_rate": _extract_metric(profile, "plate_discipline", "chase_rate"),
                    "swing_rate": _extract_metric(profile, "plate_discipline", "swing_rate"),
                }
                for window_name, profile in window_profiles.items()
            },
            HITTER_BLEND_WEIGHTS,
        ),
        "power": blend_metric_dict(
            {
                window_name: {
                    "iso": _extract_metric(profile, "power", "iso"),
                    "barrel_rate": _extract_metric(profile, "power", "barrel_rate"),
                    "hard_hit_rate": _extract_metric(profile, "power", "hard_hit_rate"),
                }
                for window_name, profile in window_profiles.items()
            },
            HITTER_BLEND_WEIGHTS,
        ),
        "batted_ball_quality": blend_metric_dict(
            {
                window_name: {
                    "avg_exit_velocity": _extract_metric(profile, "batted_ball_quality", "avg_exit_velocity"),
                    "avg_launch_angle": _extract_metric(profile, "batted_ball_quality", "avg_launch_angle"),
                }
                for window_name, profile in window_profiles.items()
            },
            HITTER_BLEND_WEIGHTS,
        ),
        "platoon_profile": blend_metric_dict(
            {
                window_name: {
                    "vs_lhp_woba": _extract_metric(profile, "platoon_profile", "vs_lhp_woba"),
                    "vs_rhp_woba": _extract_metric(profile, "platoon_profile", "vs_rhp_woba"),
                    "vs_lhp_iso": _extract_metric(profile, "platoon_profile", "vs_lhp_iso"),
                    "vs_rhp_iso": _extract_metric(profile, "platoon_profile", "vs_rhp_iso"),
                }
                for window_name, profile in window_profiles.items()
            },
            HITTER_BLEND_WEIGHTS,
        ),
    }


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
            "source_fields_used": ["player_splits", "compute_hitter_profile", "sample_blending"],
            "data_confidence": "medium" if hitter_profiles else "low",
            "generated_from": "aggregate_hitter_profiles",
            "profile_granularity": "lineup_candidate_group",
            "is_projected_lineup_derived": lineup_source == "official",
            "lineup_source": lineup_source,
            "opposing_pitcher_hand": pitcher_hand if pitcher_hand in {"L", "R"} else "unknown",
            "player_count_used": player_count_used,
            "sample_window": "blended",
            "sample_family": "blended",
            "sample_description": "Weighted blend across hitter windows",
            "sample_days": None,
            "sample_size": player_count_used,
            "sample_blend_policy": "hitter_v1_weighted_blend",
            "stabilizer_window": "current_season",
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
    target_date: Optional[datetime.date] = None,
) -> Dict[str, Any]:
    """
    Build a projected-lineup offense profile from blended player split data.
    """
    if target_date is None:
        target_date = datetime.date.today()

    player_ids = [p.get("id") for p in lineup if p.get("id")]
    if not player_ids:
        return aggregate_hitter_profiles(
            hitter_profiles=[],
            lineup_source="missing",
            pitcher_hand=pitcher_hand,
            player_count_used=0,
        )

    split_code = "vr" if pitcher_hand == "R" else "vl" if pitcher_hand == "L" else None
    if not split_code:
        return aggregate_hitter_profiles(
            hitter_profiles=[],
            lineup_source=lineup_source,
            pitcher_hand=pitcher_hand,
            player_count_used=len(player_ids),
        )

    windows = ["last_30_days", "last_90_days", "current_season"]
    window_rows = {
        window_name: fetch_player_splits_for_window(
            player_ids=player_ids,
            season=season,
            window_name=window_name,
            target_date=target_date,
        )
        for window_name in windows
    }

    hitter_profiles = []
    for player_id in player_ids:
        per_window_profiles: Dict[str, Dict[str, Any]] = {}
        for window_name, rows in window_rows.items():
            selected_row = next(
                (
                    row for row in rows
                    if row.get("player_id") == player_id and row.get("split") == split_code
                ),
                None,
            )
            if not selected_row:
                continue

            enriched_row = {
                **selected_row,
                "source_type": "player_split",
                "source_fields_used": sorted(list(selected_row.keys())),
                "data_confidence": "medium",
                "generated_from": "fetch_player_splits_for_window",
                "profile_granularity": "player",
                "is_projected_lineup_derived": lineup_source == "official",
                "sample_window": window_name,
                "sample_blend_policy": "hitter_v1_weighted_blend",
                "stabilizer_window": "current_season",
            }
            per_window_profiles[window_name] = compute_hitter_profile(enriched_row)

        if per_window_profiles:
            hitter_profiles.append(_blend_hitter_profile_windows(per_window_profiles))

    return aggregate_hitter_profiles(
        hitter_profiles=hitter_profiles,
        lineup_source=lineup_source,
        pitcher_hand=pitcher_hand,
        player_count_used=len(player_ids),
    )

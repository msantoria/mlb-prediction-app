"""
Matchup analysis utilities for matchup-preview payloads.

This module builds pitch-arsenal-vs-lineup analysis for a matchup using:
- pitcher arsenal data
- projected lineup candidates
- lightweight edge/confidence scoring

The output is designed to support a future "Matchup Analysis" UI tab without
overwriting existing overview, pitcher, batter, or environment views.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from .sample_windows import build_sample_metadata


def _edge_score_from_components(
    batter_ba: Optional[float],
    pitcher_xwoba: Optional[float],
    pitcher_hard_hit_pct: Optional[float],
    usage_pct: Optional[float],
) -> float:
    score = 0.0
    if batter_ba is not None:
        score += (batter_ba - 0.245) * 4.0
    if pitcher_xwoba is not None:
        score -= (pitcher_xwoba - 0.320) * 5.0
    if pitcher_hard_hit_pct is not None:
        score -= (pitcher_hard_hit_pct - 0.35) * 2.0
    if usage_pct is not None:
        score *= max(0.35, min(1.0, usage_pct))
    return round(score, 3)


def _confidence_from_sample(player_count: int, usage_pct: Optional[float]) -> float:
    lineup_component = min(1.0, player_count / 9.0)
    usage_component = min(1.0, max(0.25, usage_pct or 0.0))
    return round(min(1.0, lineup_component * usage_component + (0.2 if player_count >= 5 else 0.0)), 3)


def _placeholder_pitch_arsenal(
    pitcher_id: Optional[int],
    pitcher_name: Optional[str],
    pitcher_hand: Optional[str],
) -> List[Dict[str, Any]]:
    """
    Return a small stable placeholder arsenal for v1 payload enrichment.

    This intentionally avoids overclaiming full arsenal fidelity until a later PR
    wires real arsenal rows into the matchup payload.
    """
    if not pitcher_id:
        return []

    hand = pitcher_hand if pitcher_hand in {"L", "R"} else "unknown"

    if hand == "L":
        return [
            {
                "pitch_type": "Four-Seam Fastball",
                "raw_pitch_type": "FF",
                "pitcher_usage_pct": 0.42,
                "pitcher_whiff_pct": 0.23,
                "pitcher_strikeout_pct": 0.25,
                "pitcher_xwoba": 0.315,
                "pitcher_hard_hit_pct": 0.36,
            },
            {
                "pitch_type": "Slider",
                "raw_pitch_type": "SL",
                "pitcher_usage_pct": 0.31,
                "pitcher_whiff_pct": 0.34,
                "pitcher_strikeout_pct": 0.29,
                "pitcher_xwoba": 0.285,
                "pitcher_hard_hit_pct": 0.31,
            },
            {
                "pitch_type": "Changeup",
                "raw_pitch_type": "CH",
                "pitcher_usage_pct": 0.17,
                "pitcher_whiff_pct": 0.28,
                "pitcher_strikeout_pct": 0.22,
                "pitcher_xwoba": 0.301,
                "pitcher_hard_hit_pct": 0.33,
            },
        ]

    return [
        {
            "pitch_type": "Four-Seam Fastball",
            "raw_pitch_type": "FF",
            "pitcher_usage_pct": 0.45,
            "pitcher_whiff_pct": 0.22,
            "pitcher_strikeout_pct": 0.24,
            "pitcher_xwoba": 0.318,
            "pitcher_hard_hit_pct": 0.37,
        },
        {
            "pitch_type": "Slider",
            "raw_pitch_type": "SL",
            "pitcher_usage_pct": 0.28,
            "pitcher_whiff_pct": 0.33,
            "pitcher_strikeout_pct": 0.30,
            "pitcher_xwoba": 0.287,
            "pitcher_hard_hit_pct": 0.32,
        },
        {
            "pitch_type": "Curveball",
            "raw_pitch_type": "CU",
            "pitcher_usage_pct": 0.14,
            "pitcher_whiff_pct": 0.29,
            "pitcher_strikeout_pct": 0.21,
            "pitcher_xwoba": 0.295,
            "pitcher_hard_hit_pct": 0.34,
        },
    ]


def build_matchup_analysis(
    pitcher_id: Optional[int],
    pitcher_name: Optional[str],
    pitcher_hand: Optional[str],
    lineup: List[Dict[str, Any]],
    lineup_source: str,
) -> Dict[str, Any]:
    """
    Build a stable matchup-analysis payload.

    This v1 implementation adds simple pitch-type matchup rows using a
    placeholder arsenal adapter and lightweight scoring so the future
    Matchup Analysis tab can begin rendering structured content.
    """
    lineup_player_count = len([p for p in lineup if p.get("id")])
    arsenal = _placeholder_pitch_arsenal(pitcher_id, pitcher_name, pitcher_hand)

    pitch_type_matchups = []
    for pitch in arsenal:
        player_count_factor = min(1.0, lineup_player_count / 9.0)
        batter_ba = round(0.240 + (player_count_factor * 0.020), 3) if lineup_player_count else None

        edge_score = _edge_score_from_components(
            batter_ba=batter_ba,
            pitcher_xwoba=pitch.get("pitcher_xwoba"),
            pitcher_hard_hit_pct=pitch.get("pitcher_hard_hit_pct"),
            usage_pct=pitch.get("pitcher_usage_pct"),
        )
        confidence = _confidence_from_sample(
            player_count=lineup_player_count,
            usage_pct=pitch.get("pitcher_usage_pct"),
        )

        pitch_type_matchups.append(
            {
                "pitch_type": pitch.get("pitch_type"),
                "raw_pitch_type": pitch.get("raw_pitch_type"),
                "pitcher_usage_pct": pitch.get("pitcher_usage_pct"),
                "pitcher_whiff_pct": pitch.get("pitcher_whiff_pct"),
                "pitcher_strikeout_pct": pitch.get("pitcher_strikeout_pct"),
                "pitcher_xwoba": pitch.get("pitcher_xwoba"),
                "pitcher_hard_hit_pct": pitch.get("pitcher_hard_hit_pct"),
                "lineup_estimated_batting_avg": batter_ba,
                "edge_score": edge_score,
                "confidence": confidence,
            }
        )

    pitch_type_matchups.sort(key=lambda x: x.get("pitcher_usage_pct") or 0.0, reverse=True)

    biggest_edge = max(pitch_type_matchups, key=lambda x: x.get("edge_score", 0), default=None)
    biggest_weakness = min(pitch_type_matchups, key=lambda x: x.get("edge_score", 0), default=None)

    overall_confidence = (
        round(sum(row["confidence"] for row in pitch_type_matchups) / len(pitch_type_matchups), 3)
        if pitch_type_matchups
        else 0.0
    )

    status = "partial" if pitch_type_matchups else "scaffold"
    note = (
        "Initial pitch arsenal vs lineup scoring is available."
        if pitch_type_matchups
        else "Pitch arsenal vs hitter weakness analysis is not yet fully wired."
    )

    return {
        "metadata": {
            "source_type": "matchup_analysis_v1",
            "generated_from": "build_matchup_analysis",
            "data_confidence": "medium" if pitch_type_matchups else "low",
            "pitcher_id": pitcher_id,
            "pitcher_name": pitcher_name,
            "pitcher_hand": pitcher_hand if pitcher_hand in {"L", "R"} else "unknown",
            "lineup_source": lineup_source,
            "lineup_player_count": lineup_player_count,
            **build_sample_metadata(
                window_name="current_season",
                sample_size=lineup_player_count,
                sample_blend_policy="single_window_v1",
                stabilizer_window=None,
            ),
        },
        "pitchTypeMatchups": pitch_type_matchups,
        "biggestEdge": biggest_edge,
        "biggestWeakness": biggest_weakness,
        "confidence": overall_confidence,
        "summary": {
            "status": status,
            "note": note,
        },
    }

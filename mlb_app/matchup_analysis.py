"""
Matchup analysis utilities for matchup-preview payloads.

This module builds pitch-arsenal-vs-lineup analysis for a matchup using:
- pitcher arsenal data
- projected lineup candidates
- simple batter vs pitch-type capability summaries
- lightweight edge/confidence scoring

The output is designed to support a future "Matchup Analysis" UI tab without
overwriting existing overview, pitcher, batter, or environment views.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional


def build_matchup_analysis(
    pitcher_id: Optional[int],
    pitcher_name: Optional[str],
    pitcher_hand: Optional[str],
    lineup: List[Dict[str, Any]],
    lineup_source: str,
) -> Dict[str, Any]:
    """
    Return a stable matchup-analysis payload scaffold.

    This is the first contract layer for the future Matchup Analysis tab.
    It will be expanded later with real pitch-arsenal-vs-hitter calculations.
    """
    return {
        "metadata": {
            "source_type": "matchup_analysis_scaffold",
            "generated_from": "build_matchup_analysis",
            "data_confidence": "low",
            "pitcher_id": pitcher_id,
            "pitcher_name": pitcher_name,
            "pitcher_hand": pitcher_hand if pitcher_hand in {"L", "R"} else "unknown",
            "lineup_source": lineup_source,
            "lineup_player_count": len([p for p in lineup if p.get("id")]),
        },
        "pitchTypeMatchups": [],
        "biggestEdge": None,
        "biggestWeakness": None,
        "confidence": 0.0,
        "summary": {
            "status": "scaffold",
            "note": (
                "Pitch arsenal vs hitter weakness analysis is not yet fully wired. "
                "This payload is additive and intended for a future Matchup Analysis tab."
            ),
        },
    }

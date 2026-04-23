"""
Hitter multi-window retrieval utilities.

This module provides a first-pass framework for retrieving hitter split
data across named sample windows such as current season, last 30 days,
and last 90 days.
"""

from __future__ import annotations

import datetime
from typing import Dict, List

from .player_splits import fetch_player_splits
from .sample_windows import get_window_definition


def fetch_player_splits_for_window(
    player_ids: List[int],
    season: int,
    window_name: str,
    target_date: datetime.date,
) -> List[Dict[str, float]]:
    """
    Retrieve hitter split rows for a named sample window.

    This v1 implementation supports:
    - current_season: real season split retrieval
    - rolling windows: contract-safe scaffold using the same output shape

    Future work can replace rolling-window scaffolds with true date-bounded
    Statcast or API-backed calculations.
    """
    if not player_ids:
        return []

    window_def = get_window_definition(window_name)
    window_type = window_def.get("window_type")

    # Current season: use the existing real split retrieval path.
    if window_name == "current_season":
        rows = fetch_player_splits(player_ids, season)
        for row in rows:
            row["sample_window"] = "current_season"
            row["sample_window_type"] = window_type
            row["sample_target_date"] = target_date.isoformat()
        return rows

    # Rolling windows: v1 scaffold preserves contract but does not yet claim
    # true date-bounded split calculations.
    if window_name in {"last_30_days", "last_90_days"}:
        rows = fetch_player_splits(player_ids, season)
        for row in rows:
            row["sample_window"] = window_name
            row["sample_window_type"] = window_type
            row["sample_target_date"] = target_date.isoformat()
            row["sample_is_scaffold"] = True
        return rows

    return []

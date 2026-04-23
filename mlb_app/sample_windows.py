"""
Sample window definitions for matchup analysis.

This module provides a stable framework for naming, describing, and
eventually blending time windows used across hitter, pitcher, and
matchup-analysis calculations.
"""

from __future__ import annotations

import datetime
from typing import Dict, Optional


SAMPLE_WINDOWS: Dict[str, Dict[str, object]] = {
    "last_30_days": {
        "window_type": "rolling",
        "days": 30,
        "description": "Rolling last 30 days",
    },
    "last_90_days": {
        "window_type": "rolling",
        "days": 90,
        "description": "Rolling last 90 days",
    },
    "last_365_days": {
        "window_type": "rolling",
        "days": 365,
        "description": "Rolling last 365 days",
    },
    "current_season": {
        "window_type": "season",
        "days": None,
        "description": "Current season to date",
    },
    "career": {
        "window_type": "career",
        "days": None,
        "description": "Career baseline",
    },
}


def get_window_definition(window_name: str) -> Dict[str, object]:
    """Return metadata for a named sample window."""
    return SAMPLE_WINDOWS.get(
        window_name,
        {
            "window_type": "unknown",
            "days": None,
            "description": "Unknown sample window",
        },
    )


def get_window_start_date(
    target_date: datetime.date,
    window_name: str,
) -> Optional[str]:
    """
    Return an ISO start date for rolling windows.

    Non-rolling windows return None because they are not anchored only by
    a backwards-looking day count.
    """
    definition = get_window_definition(window_name)
    days = definition.get("days")
    if not days:
        return None
    return (target_date - datetime.timedelta(days=int(days))).isoformat()


def build_sample_metadata(
    window_name: str,
    sample_size: Optional[int] = None,
    sample_blend_policy: str = "single_window_v1",
    stabilizer_window: Optional[str] = None,
) -> Dict[str, object]:
    """Build a reusable sample metadata block."""
    definition = get_window_definition(window_name)
    return {
        "sample_window": window_name,
        "sample_family": definition.get("window_type"),
        "sample_description": definition.get("description"),
        "sample_days": definition.get("days"),
        "sample_size": sample_size,
        "sample_blend_policy": sample_blend_policy,
        "stabilizer_window": stabilizer_window,
    }

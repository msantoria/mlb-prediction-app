"""
Pitcher multi-window retrieval utilities.

This module provides a first-pass framework for retrieving pitcher metric
data across named sample windows such as last 30 days, last 90 days,
and last 365 days.
"""

from __future__ import annotations

import datetime
from typing import Dict, Optional

from .pitcher_analysis import get_pitcher_metrics
from .sample_windows import get_window_start_date


def fetch_pitcher_metrics_for_window(
    pitcher_id: int,
    target_date: datetime.date,
    window_name: str,
) -> Dict[str, Optional[float]]:
    """
    Retrieve pitcher metrics for a named sample window.

    This v1 implementation supports:
    - last_365_days: real rolling retrieval using the existing pitcher metrics path
    - rolling shorter windows: contract-safe scaffold that still uses the current
      retrieval path shape while explicitly labeling the sample window

    Future work can improve the shorter windows with more exact bounded retrieval.
    """
    if not pitcher_id:
        return {}

    end_date = target_date.isoformat()

    if window_name == "last_365_days":
        start_date = get_window_start_date(target_date, "last_365_days")
        metrics = get_pitcher_metrics(pitcher_id, start_date, end_date)
        metrics["sample_window"] = "last_365_days"
        metrics["sample_target_date"] = end_date
        metrics["sample_is_scaffold"] = False
        return metrics

    if window_name in {"last_30_days", "last_90_days"}:
        start_date = get_window_start_date(target_date, window_name)
        metrics = get_pitcher_metrics(pitcher_id, start_date, end_date)
        metrics["sample_window"] = window_name
        metrics["sample_target_date"] = end_date
        metrics["sample_is_scaffold"] = True
        return metrics

    return {}

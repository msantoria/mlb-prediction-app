"""
Weighted sample blending helpers for matchup analysis.

This module provides reusable helpers for blending metric dictionaries
across multiple sample windows such as last 30 days, last 90 days,
current season, and last 365 days.
"""

from __future__ import annotations

from typing import Dict, Optional


HITTER_BLEND_WEIGHTS: Dict[str, float] = {
    "last_30_days": 0.50,
    "last_90_days": 0.30,
    "current_season": 0.20,
}

PITCHER_BLEND_WEIGHTS: Dict[str, float] = {
    "last_30_days": 0.35,
    "last_90_days": 0.35,
    "last_365_days": 0.30,
}


def weighted_average(values: Dict[str, Optional[float]], weights: Dict[str, float]) -> Optional[float]:
    """
    Compute a weighted average using only non-null values.
    """
    numerator = 0.0
    denominator = 0.0

    for key, weight in weights.items():
        value = values.get(key)
        if value is None:
            continue
        numerator += value * weight
        denominator += weight

    if denominator == 0:
        return None
    return numerator / denominator


def blend_metric_dict(
    metric_windows: Dict[str, Dict[str, Optional[float]]],
    weights: Dict[str, float],
) -> Dict[str, Optional[float]]:
    """
    Blend metric dictionaries across multiple windows.

    Parameters
    ----------
    metric_windows : dict
        Mapping of window_name -> metric dict
    weights : dict
        Mapping of window_name -> weight

    Returns
    -------
    dict
        Blended metric dictionary using weighted averages for shared keys.
    """
    all_keys = set()
    for window_metrics in metric_windows.values():
        all_keys.update(window_metrics.keys())

    blended: Dict[str, Optional[float]] = {}
    for metric_key in all_keys:
        values = {
            window_name: metrics.get(metric_key)
            for window_name, metrics in metric_windows.items()
        }
        blended[metric_key] = weighted_average(values, weights)

    return blended

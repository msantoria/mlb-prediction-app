"""
Batter Analysis Functions
=========================

This module provides convenience functions for retrieving and summarizing
pitch‑level Statcast data for hitters.  It builds upon the retrieval and
aggregation functions defined in ``statcast_utils.py``.

Functions
---------
get_batter_metrics(player_id, start_date, end_date)
    Fetch raw pitch data for a batter over a date range and return
    aggregated statistics such as average exit velocity, launch angle,
    hard‑hit %, barrel %, strikeout % and walk %.
"""

from __future__ import annotations

from typing import Dict, Optional

from .statcast_utils import (
    fetch_statcast_batter_data,
    calculate_batter_aggregates,
)



def get_batter_metrics(
    player_id: int,
    start_date: str,
    end_date: str,
    raw_data: Optional[list[dict]] = None,
) -> Dict[str, float]:
    """Retrieve and aggregate Statcast pitch data for a batter.

    This function fetches raw pitch‑by‑pitch data for the given batter
    over the specified date range and returns a dictionary of summary
    statistics.  If ``raw_data`` is provided, it will be used instead
    of invoking the data retrieval function.  This allows for testing
    without network access.

    Parameters
    ----------
    player_id : int
        MLBAM identifier for the batter.
    start_date : str
        Inclusive start date in ``YYYY-MM-DD`` format.
    end_date : str
        Inclusive end date in ``YYYY-MM-DD`` format.
    raw_data : list of dict, optional
        Pre‑downloaded Statcast pitch records.  If provided, the
        retrieval function will not be called.

    Returns
    -------
    dict
        Aggregated hitting statistics.  Keys include ``avg_exit_vel``,
        ``avg_launch_angle``, ``hard_hit_pct``, ``barrel_pct``,
        ``k_pct`` and ``bb_pct``.  Returns an empty dict if no data is
        available.

    Raises
    ------
    NotImplementedError
        If data retrieval is attempted in an environment without
        network access.
    """
    if raw_data is None:
        raw_data = fetch_statcast_batter_data(player_id, start_date, end_date)
    return calculate_batter_aggregates(raw_data)

"""
Pitcher Analysis Functions
==========================

This module provides convenience functions for retrieving and summarizing
pitch‑level Statcast data for pitchers.  The core functionality relies on
the data retrieval and aggregation functions defined in ``statcast_utils.py``.
In a production deployment, the retrieval functions will download pitch
events from Baseball Savant's Statcast Search API or another data source.

Functions
---------
get_pitcher_metrics(player_id, start_date, end_date)
    Fetch raw pitch data for a pitcher over a date range and return
    aggregated statistics such as average velocity, spin rate, hard‑hit %,
    strikeout % and walk %.
"""

from __future__ import annotations

from typing import Dict, Optional

from .statcast_utils import (
    fetch_statcast_pitcher_data,
    calculate_pitcher_aggregates,
)



def get_pitcher_metrics(
    player_id: int,
    start_date: str,
    end_date: str,
    raw_data: Optional[list[dict]] = None,
) -> Dict[str, float]:
    """Retrieve and aggregate Statcast pitch data for a pitcher.

    This function fetches raw pitch‑by‑pitch data for the given pitcher
    over the specified date range and returns a dictionary of summary
    statistics.  If ``raw_data`` is provided, it will be used instead
    of invoking the data retrieval function.  This allows for testing
    without network access.

    Parameters
    ----------
    player_id : int
        MLBAM identifier for the pitcher.
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
        Aggregated pitching statistics.  Keys include ``avg_velocity``,
        ``avg_spin``, ``hard_hit_pct``, ``k_pct``, ``bb_pct`` and
        ``pitch_mix``.  Returns an empty dict if no data is available.

    Raises
    ------
    NotImplementedError
        If data retrieval is attempted in an environment without
        network access.
    """
    if raw_data is None:
        # Download data via Statcast API.  This may raise NotImplementedError
        # in this execution environment.
        raw_data = fetch_statcast_pitcher_data(player_id, start_date, end_date)
    return calculate_pitcher_aggregates(raw_data)

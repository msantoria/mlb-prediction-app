"""
Data Ingestion Utilities for MLB Prediction App
================================================

This module provides helper functions for retrieving basic game and team
information from the MLB Stats API.  It encapsulates calls for
fetching the daily schedule of games and the current season standings.

Functions
---------
fetch_schedule(date_str)
    Retrieve the list of MLB games scheduled on a given date.

fetch_team_records(season)
    Obtain win/loss records and run differentials for all teams in
    the specified season.

fetch_team_splits(team_id, season, split)
    Fetch hitting statistics for a team against left‑ or
    right‑handed pitching.  Split should be ``"vsLHP"`` or ``"vsRHP"``.

Note
----
These functions interact with the public MLB Stats API and do not
require authentication.  Network errors are propagated as
RuntimeError exceptions to allow callers to handle them uniformly.
"""

from __future__ import annotations

from typing import Dict, List, Optional

import requests



def fetch_schedule(date_str: str) -> List[Dict]:
    """Return the list of scheduled MLB games for a given date.

    Parameters
    ----------
    date_str : str
        Date in ``YYYY-MM-DD`` format.

    Returns
    -------
    list of dict
        Each dict represents a game with keys such as ``teams`` and
        ``status``.  If no games are scheduled, an empty list is
        returned.

    Raises
    ------
    RuntimeError
        If the HTTP request fails or the API response cannot be
        parsed.
    """
    url = f"https://statsapi.mlb.com/api/v1/schedule?sportId=1&date={date_str}"
    try:
        resp = requests.get(url, timeout=20)
        resp.raise_for_status()
    except requests.RequestException as exc:
        raise RuntimeError(f"Failed to fetch schedule data: {exc}") from exc

    data = resp.json()
    dates = data.get("dates", [])
    if not dates:
        return []
    return dates[0].get("games", [])



def fetch_team_records(season: str) -> Dict[int, Dict[str, float]]:
    """Fetch win/loss records and run differentials for all teams in a season.

    Parameters
    ----------
    season : str
        The season year (e.g., ``"2026"``).  The MLB Stats API uses
        the season year to return standings information.

    Returns
    -------
    dict
        Mapping from team ID to a dict containing wins, losses,
        ``win_pct`` and ``run_diff``.

    Raises
    ------
    RuntimeError
        If the HTTP request fails or the API response cannot be
        parsed.
    """
    url = f"https://statsapi.mlb.com/api/v1/standings?leagueId=103,104&season={season}"
    try:
        resp = requests.get(url, timeout=20)
        resp.raise_for_status()
    except requests.RequestException as exc:
        raise RuntimeError(f"Failed to fetch standings data: {exc}") from exc

    data = resp.json()
    records: Dict[int, Dict[str, float]] = {}
    for div in data.get("records", []):
        for team_record in div.get("teamRecords", []):
            team = team_record.get("team", {})
            tid = team.get("id")
            wins = team_record.get("wins", 0)
            losses = team_record.get("losses", 0)
            win_pct = (wins / (wins + losses)) if (wins + losses) > 0 else 0.0
            run_diff = team_record.get("runsScored", 0) - team_record.get(
                "runsAllowed", 0
            )
            records[tid] = {
                "wins": float(wins),
                "losses": float(losses),
                "win_pct": float(win_pct),
                "run_diff": float(run_diff),
            }
    return records



def fetch_team_splits(team_id: int, season: int, split: str) -> Optional[Dict[str, float]]:
    """Fetch basic hitting stats for a team against left‑ or right‑handed pitching.

    This function wraps the Stats API call used in Layer 10 of the
    original project.  It retrieves season‑level hitting stats for a
    team filtered by the specified split.

    Parameters
    ----------
    team_id : int
        MLBAM identifier for the team.
    season : int
        Season year (e.g., 2025).
    split : str
        Split code, either ``"vsLHP"`` or ``"vsRHP"``.

    Returns
    -------
    dict or None
        Dictionary of numeric hitting stats (e.g., plate appearances,
        hits, home runs, OBP, SLG) or ``None`` if no data is
        available.
    """
    params = {
        "stats": "season",
        "group": "hitting",
        "teamId": team_id,
        "season": season,
        "sportId": 1,
        "split": split,
        "gameType": "R",
    }
    url = "https://statsapi.mlb.com/api/v1/stats"
    try:
        resp = requests.get(url, params=params, timeout=20)
        resp.raise_for_status()
    except requests.RequestException:
        return None

    stats = resp.json().get("stats", [])
    if not stats or not stats[0].get("splits"):
        return None
    stat = stats[0]["splits"][0].get("stat", {})
    # Convert string numbers to floats for consistency
    numeric_keys = [
        "plateAppearances",
        "atBats",
        "hits",
        "doubles",
        "triples",
        "homeRuns",
        "runs",
        "rbi",
        "baseOnBalls",
        "strikeOuts",
        "hitByPitch",
        "stolenBases",
        "caughtStealing",
        "avg",
        "obp",
        "slg",
        "ops",
    ]
    result: Dict[str, float] = {}
    for k in numeric_keys:
        try:
            result[k] = float(stat.get(k, 0))
        except (TypeError, ValueError):
            result[k] = 0.0
    return result

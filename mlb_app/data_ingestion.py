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

fetch_live_lineup(game_pk)
    Retrieve the confirmed batting order for both teams in a game
    from the liveData endpoint.  Returns a dict with ``"away"`` and
    ``"home"`` keys, each containing an ordered list of batter dicts
    (``batter_id``, ``name``, ``position``, ``batting_order``).

Note
----
These functions interact with the public MLB Stats API and do not
require authentication.  Network errors are propagated as
RuntimeError exceptions to allow callers to handle them uniformly.
"""

from __future__ import annotations

from typing import Dict, List, Optional

import requests


MLB_STATS_BASE = "https://statsapi.mlb.com/api/v1"



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



def fetch_live_lineup(game_pk: int) -> Dict[str, List[Dict]]:
    """Fetch the confirmed live lineup for a game from the MLB Stats API.

    Calls the liveData endpoint and extracts the boxscore batting order for
    both the away and home teams.  This data is typically available
    approximately one hour before first pitch.

    Parameters
    ----------
    game_pk : int
        The MLB game primary key (e.g., ``745456``).

    Returns
    -------
    dict
        A dict with keys ``"away"`` and ``"home"``, each containing a list
        of batter dicts with the following fields:

        * ``batter_id`` – MLBAM player identifier.
        * ``name`` – Player's full name.
        * ``position`` – Fielding position abbreviation (e.g., ``"1B"``).
        * ``batting_order`` – Batting order slot (1–9).

        Players without a batting order entry (e.g., pitchers in the
        bullpen) are excluded.  If the request fails, ``{"away": [],
        "home": []}`` is returned.

    Raises
    ------
    RuntimeError
        If the HTTP request fails or the API response cannot be parsed.
    """
    url = f"{MLB_STATS_BASE}/game/{game_pk}/liveData"
    try:
        resp = requests.get(url, timeout=20)
        resp.raise_for_status()
    except requests.RequestException as exc:
        raise RuntimeError(
            f"Failed to fetch live lineup for game {game_pk}: {exc}"
        ) from exc

    data = resp.json()
    boxscore = data.get("liveData", {}).get("boxscore", {})
    teams = boxscore.get("teams", {})

    result: Dict[str, List[Dict]] = {"away": [], "home": []}

    for side in ("away", "home"):
        players = teams.get(side, {}).get("players", {})
        batters: List[Dict] = []
        for player_key, player_data in players.items():
            batting_order_raw = player_data.get("battingOrder")
            if not batting_order_raw:
                # Player is not in the batting order (e.g., bullpen arm)
                continue
            try:
                # battingOrder is a string like "100", "200", … "900"
                batting_order = int(str(batting_order_raw).strip()) // 100
            except (TypeError, ValueError):
                continue

            person = player_data.get("person", {})
            position = player_data.get("position", {})
            batters.append(
                {
                    "batter_id": person.get("id"),
                    "name": person.get("fullName", ""),
                    "position": position.get("abbreviation", ""),
                    "batting_order": batting_order,
                }
            )

        # Sort by batting order slot so callers receive an ordered list
        batters.sort(key=lambda b: b["batting_order"])
        result[side] = batters

    return result

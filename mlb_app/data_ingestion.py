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

fetch_standings(season)
    Retrieve AL/NL division standings with per-team W-L, PCT, GB,
    last-10 record, and current streak.

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



def fetch_standings(season: int) -> Dict[str, Dict[str, List[Dict]]]:
    """Retrieve AL/NL division standings for a given season.

    Calls the MLB Stats API standings endpoint and organises the results
    into a nested structure keyed by league (``"AL"`` / ``"NL"``) and
    division (``"East"``, ``"Central"``, ``"West"``).  Teams within each
    division are listed in the order returned by the API (i.e. by
    division rank).

    Parameters
    ----------
    season : int
        Season year (e.g., 2025).

    Returns
    -------
    dict
        Structure::

            {
                "AL": {
                    "East":    [<team_record>, ...],
                    "Central": [<team_record>, ...],
                    "West":    [<team_record>, ...],
                },
                "NL": { ... },
            }

        Each ``team_record`` dict contains:

        * ``team_id``  – MLBAM team identifier (int)
        * ``name``     – team name (str)
        * ``w``        – wins (int)
        * ``l``        – losses (int)
        * ``pct``      – win percentage rounded to three decimal places (float)
        * ``gb``       – games behind division leader; ``0`` for the leader (float)
        * ``l10``      – last-10-games record, e.g. ``"6-4"`` (str)
        * ``streak``   – current streak, e.g. ``"W2"`` or ``"L1"`` (str)

    Raises
    ------
    RuntimeError
        If the HTTP request fails or the API response cannot be parsed.
    """
    url = (
        f"https://statsapi.mlb.com/api/v1/standings"
        f"?leagueId=103,104&season={season}"
    )
    try:
        resp = requests.get(url, timeout=20)
        resp.raise_for_status()
    except requests.RequestException as exc:
        raise RuntimeError(f"Failed to fetch standings data: {exc}") from exc

    data = resp.json()

    # League IDs: 103 = AL, 104 = NL
    league_map = {103: "AL", 104: "NL"}

    # Division names contain "East", "Central", or "West"
    def _division_label(name: str) -> str:
        for label in ("East", "Central", "West"):
            if label in name:
                return label
        return name  # fallback: return raw name

    standings: Dict[str, Dict[str, List[Dict]]] = {
        "AL": {"East": [], "Central": [], "West": []},
        "NL": {"East": [], "Central": [], "West": []},
    }

    for div_record in data.get("records", []):
        league_id = div_record.get("league", {}).get("id")
        league_name = league_map.get(league_id)
        if league_name is None:
            continue

        division_name = _division_label(
            div_record.get("division", {}).get("nameShort", "")
            or div_record.get("division", {}).get("name", "")
        )

        teams: List[Dict] = []
        for tr in div_record.get("teamRecords", []):
            team = tr.get("team", {})
            wins = tr.get("wins", 0)
            losses = tr.get("losses", 0)
            total = wins + losses
            pct = round(wins / total, 3) if total > 0 else 0.0

            # Games behind: the leader has "gamesBack" of "-"; treat as 0
            gb_raw = tr.get("gamesBack", "-")
            try:
                gb = float(gb_raw)
            except (TypeError, ValueError):
                gb = 0.0

            # Last-10 record lives inside the "records" list
            l10 = ""
            for rec in tr.get("records", {}).get("splitRecords", []):
                if rec.get("type") == "lastTen":
                    l10 = f"{rec.get('wins', 0)}-{rec.get('losses', 0)}"
                    break

            # Streak: e.g. {"streakType": "wins", "streakNumber": 2, "streakCode": "W2"}
            streak = tr.get("streak", {}).get("streakCode", "")

            teams.append(
                {
                    "team_id": team.get("id"),
                    "name": team.get("name", ""),
                    "w": wins,
                    "l": losses,
                    "pct": pct,
                    "gb": gb,
                    "l10": l10,
                    "streak": streak,
                }
            )

        standings[league_name][division_name] = teams

    return standings


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

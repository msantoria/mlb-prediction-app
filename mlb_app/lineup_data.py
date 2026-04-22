"""
Lineup data utilities for matchup previews.

This module provides reusable helpers for retrieving official lineups from
the MLB Stats API and falling back to active non-pitcher roster candidates
when an official lineup has not yet been posted.
"""

from __future__ import annotations

import datetime
from typing import Any, Dict, List, Tuple

import requests


MLB_STATS_BASE = "https://statsapi.mlb.com/api/v1"


def fetch_roster_as_lineup(team_id: int, season: int) -> List[Dict[str, Any]]:
    """
    Return active non-pitcher roster entries when an official lineup is unavailable.
    """
    try:
        resp = requests.get(
            f"{MLB_STATS_BASE}/teams/{team_id}/roster",
            params={"rosterType": "active", "season": season},
            timeout=15,
        )
        resp.raise_for_status()
        return [
            {
                "id": r["person"]["id"],
                "fullName": r["person"]["fullName"],
            }
            for r in resp.json().get("roster", [])
            if (r.get("position") or {}).get("type", "").lower() != "pitcher"
            and r.get("person", {}).get("id")
        ]
    except requests.RequestException:
        return []


def resolve_team_lineup(
    game: Dict[str, Any],
    team_id: int,
    side: str,
    season: int,
) -> Tuple[List[Dict[str, Any]], str]:
    """
    Resolve a team lineup from hydrated schedule data, falling back to active roster.

    Returns
    -------
    tuple
        (lineup_list, lineup_source) where lineup_source is one of:
        - "official"
        - "roster"
        - "missing"
    """
    lineups = game.get("lineups", {}) or {}
    lineup_raw = lineups.get(f"{side}Players", []) or []

    if lineup_raw:
        lineup = [
            {
                "id": p.get("id"),
                "fullName": p.get("fullName"),
                "batting_order": i + 1,
            }
            for i, p in enumerate(lineup_raw)
            if p.get("id")
        ]
        return lineup, "official"

    roster_fallback = fetch_roster_as_lineup(team_id, season)
    if roster_fallback:
        lineup = [
            {
                "id": p.get("id"),
                "fullName": p.get("fullName"),
                "batting_order": i + 1,
            }
            for i, p in enumerate(roster_fallback)
            if p.get("id")
        ]
        return lineup, "roster"

    return [], "missing"

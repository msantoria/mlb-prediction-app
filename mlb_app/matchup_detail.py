"""
Matchup detail helpers for the /matchup/{game_pk} endpoint.

This module fetches live lineup and game-info data from the MLB Stats API
and assembles the rich response consumed by the matchup detail page.

Functions
---------
fetch_live_lineup(game_pk)
    Pull the current away/home batting orders from the live-data feed.

fetch_game_info(game_pk)
    Pull game date, time, venue, status, and team identifiers from the
    game endpoint.

build_matchup_detail(session, game_pk)
    Orchestrate all data sources (MLB API + DB) into a single response
    dict matching the /matchup/{game_pk} contract.
"""

from __future__ import annotations

import datetime
from typing import Any, Dict, List, Optional

import requests
from sqlalchemy.orm import Session

from .db_utils import (
    get_pitcher_aggregate,
    get_batter_aggregate,
    get_pitch_arsenal,
    get_player_split,
    get_team_split,
    get_pitcher_game_log,
)
from .scoring import compute_win_probability

MLB_STATS_BASE = "https://statsapi.mlb.com/api/v1"


# ---------------------------------------------------------------------------
# MLB Stats API helpers
# ---------------------------------------------------------------------------

def fetch_live_lineup(game_pk: int) -> Dict[str, List[Dict[str, Any]]]:
    """Return the live batting orders for both teams in a game.

    Calls ``GET /api/v1/game/{game_pk}/liveData`` and extracts each
    team's batting order, including batter ID, full name, primary
    position, and batting-order slot.

    Parameters
    ----------
    game_pk : int
        The MLB game primary key.

    Returns
    -------
    dict
        ``{"away": [...], "home": [...]}`` where each list element is::

            {
                "batter_id": 123,
                "name": "J. Abreu",
                "position": "1B",
                "batting_order": 1,
            }

        Returns empty lists for either side if the data is unavailable.

    Raises
    ------
    RuntimeError
        If the HTTP request fails.
    """
    url = f"{MLB_STATS_BASE}/game/{game_pk}/liveData"
    try:
        resp = requests.get(url, timeout=20)
        resp.raise_for_status()
    except requests.RequestException as exc:
        raise RuntimeError(f"Failed to fetch live lineup for game {game_pk}: {exc}") from exc

    data = resp.json()
    boxscore = data.get("liveData", {}).get("boxscore", {})
    teams_data = boxscore.get("teams", {})

    result: Dict[str, List[Dict[str, Any]]] = {"away": [], "home": []}

    for side in ("away", "home"):
        team_box = teams_data.get(side, {})
        players = team_box.get("players", {})
        batting_order_ids: List[int] = team_box.get("battingOrder", [])

        # Build a lookup from player ID to player dict
        player_lookup: Dict[int, Dict] = {}
        for player_key, player_data in players.items():
            pid = player_data.get("person", {}).get("id")
            if pid:
                player_lookup[int(pid)] = player_data

        lineup: List[Dict[str, Any]] = []
        for slot, batter_id in enumerate(batting_order_ids, start=1):
            batter_id = int(batter_id)
            player_data = player_lookup.get(batter_id, {})
            person = player_data.get("person", {})
            position = player_data.get("position", {}).get("abbreviation", "")
            lineup.append(
                {
                    "batter_id": batter_id,
                    "name": person.get("fullName", ""),
                    "position": position,
                    "batting_order": slot,
                }
            )

        result[side] = lineup

    return result


def fetch_game_info(game_pk: int) -> Dict[str, Any]:
    """Return basic game metadata for a given game PK.

    Calls ``GET /api/v1/game/{game_pk}`` and extracts the game date,
    local start time, venue name, game status, and team identifiers /
    names / records.

    Parameters
    ----------
    game_pk : int
        The MLB game primary key.

    Returns
    -------
    dict
        Example::

            {
                "game_pk": 745528,
                "game_date": "2026-04-15",
                "time": "19:05",
                "venue": "PNC Park",
                "status": "Scheduled",
                "away_team": {"id": 134, "name": "Pirates", "record": "8-6"},
                "home_team": {"id": 119, "name": "Dodgers", "record": "10-4"},
                "away_pitcher": {"id": 677952, "name": "Braxton Ashcraft", "hand": None},
                "home_pitcher": {"id": 543037, "name": "Clayton Kershaw", "hand": None},
            }

    Raises
    ------
    RuntimeError
        If the HTTP request fails.
    """
    url = f"{MLB_STATS_BASE}/game/{game_pk}"
    params = {"hydrate": "probablePitcher,team,linescore"}
    try:
        resp = requests.get(url, params=params, timeout=20)
        resp.raise_for_status()
    except requests.RequestException as exc:
        raise RuntimeError(f"Failed to fetch game info for game {game_pk}: {exc}") from exc

    data = resp.json()
    game_data = data.get("gameData", {})

    # Date / time / venue / status
    datetime_info = game_data.get("datetime", {})
    raw_date = datetime_info.get("officialDate", "")
    raw_time = datetime_info.get("time", "")
    am_pm = datetime_info.get("ampm", "")
    game_time = f"{raw_time} {am_pm}".strip() if raw_time else ""

    venue = game_data.get("venue", {}).get("name", "")
    status = game_data.get("status", {}).get("detailedState", "")

    # Teams
    teams = game_data.get("teams", {})

    def _team_info(side: str) -> Dict[str, Any]:
        team = teams.get(side, {})
        record = team.get("record", {})
        wins = record.get("wins", 0)
        losses = record.get("losses", 0)
        return {
            "id": team.get("id"),
            "name": team.get("teamName") or team.get("name", ""),
            "record": f"{wins}-{losses}",
        }

    def _pitcher_info(side: str) -> Optional[Dict[str, Any]]:
        pitcher = game_data.get("probablePitchers", {}).get(side, {})
        if not pitcher:
            return None
        return {
            "id": pitcher.get("id"),
            "name": pitcher.get("fullName", ""),
            # Handedness is not in this endpoint; enriched later from DB
            "hand": None,
        }

    return {
        "game_pk": game_pk,
        "game_date": raw_date,
        "time": game_time,
        "venue": venue,
        "status": status,
        "away_team": _team_info("away"),
        "home_team": _team_info("home"),
        "away_pitcher": _pitcher_info("away"),
        "home_pitcher": _pitcher_info("home"),
    }


# ---------------------------------------------------------------------------
# DB serialisation helpers
# ---------------------------------------------------------------------------

def _pitcher_aggregate_dict(agg) -> Optional[Dict[str, Any]]:
    """Serialise a PitcherAggregate ORM row to a plain dict."""
    if agg is None:
        return None
    return {
        "avg_velocity": agg.avg_velocity,
        "avg_spin_rate": agg.avg_spin_rate,
        "hard_hit_pct": agg.hard_hit_pct,
        "k_pct": agg.k_pct,
        "bb_pct": agg.bb_pct,
        "xwoba": agg.xwoba,
        "xba": agg.xba,
        "avg_horiz_break": agg.avg_horiz_break,
        "avg_vert_break": agg.avg_vert_break,
    }


def _batter_aggregate_dict(agg) -> Optional[Dict[str, Any]]:
    """Serialise a BatterAggregate ORM row to a plain dict."""
    if agg is None:
        return None
    return {
        "avg_exit_velocity": agg.avg_exit_velocity,
        "avg_launch_angle": agg.avg_launch_angle,
        "hard_hit_pct": agg.hard_hit_pct,
        "barrel_pct": agg.barrel_pct,
        "k_pct": agg.k_pct,
        "bb_pct": agg.bb_pct,
        "batting_avg": agg.batting_avg,
    }


def _split_dict(split) -> Optional[Dict[str, Any]]:
    """Serialise a PlayerSplit or TeamSplit ORM row to a plain dict."""
    if split is None:
        return None
    return {
        "pa": split.pa,
        "batting_avg": split.batting_avg,
        "on_base_pct": split.on_base_pct,
        "slugging_pct": split.slugging_pct,
        "iso": split.iso,
        "k_pct": split.k_pct,
        "bb_pct": split.bb_pct,
        "home_runs": split.home_runs,
    }


def _arsenal_list(arsenal_rows) -> List[Dict[str, Any]]:
    """Serialise a list of PitchArsenal ORM rows to plain dicts."""
    return [
        {
            "pitch_type": r.pitch_type,
            "pitch_name": r.pitch_name,
            "usage_pct": r.usage_pct,
            "whiff_pct": r.whiff_pct,
            "strikeout_pct": r.strikeout_pct,
            "rv_per_100": r.rv_per_100,
            "xwoba": r.xwoba,
            "hard_hit_pct": r.hard_hit_pct,
        }
        for r in arsenal_rows
    ]


def _team_split_dict(session: Session, team_id: Optional[int], season: int) -> Dict[str, Any]:
    """Return vsLHP and vsRHP splits for a team from the DB."""
    if not team_id:
        return {"vsLHP": None, "vsRHP": None}
    return {
        "vsLHP": _split_dict(get_team_split(session, team_id, season, "vsL")),
        "vsRHP": _split_dict(get_team_split(session, team_id, season, "vsR")),
    }


# ---------------------------------------------------------------------------
# Main assembler
# ---------------------------------------------------------------------------

def build_matchup_detail(session: Session, game_pk: int) -> Dict[str, Any]:
    """Assemble the full matchup detail response for a given game PK.

    Fetches live lineup and game metadata from the MLB Stats API, then
    enriches each pitcher and batter with DB-backed aggregates, platoon
    splits, pitch arsenal, and recent outings.  Win probability is
    computed using the existing scoring engine.

    Parameters
    ----------
    session : Session
        Active SQLAlchemy database session.
    game_pk : int
        The MLB game primary key.

    Returns
    -------
    dict
        A fully assembled matchup detail dict.  See the ``/matchup/{game_pk}``
        endpoint docstring for the complete schema.

    Raises
    ------
    RuntimeError
        If the MLB Stats API calls fail.
    """
    # ---- 1. Fetch game metadata and live lineup from the MLB API ----------
    game_info = fetch_game_info(game_pk)
    live_lineup = fetch_live_lineup(game_pk)

    season = datetime.date.today().year
    raw_date = game_info.get("game_date", "")
    if raw_date:
        try:
            season = int(raw_date[:4])
        except ValueError:
            pass

    away_team_id: Optional[int] = (game_info.get("away_team") or {}).get("id")
    home_team_id: Optional[int] = (game_info.get("home_team") or {}).get("id")

    away_pitcher_stub = game_info.get("away_pitcher") or {}
    home_pitcher_stub = game_info.get("home_pitcher") or {}
    away_pitcher_id: Optional[int] = away_pitcher_stub.get("id")
    home_pitcher_id: Optional[int] = home_pitcher_stub.get("id")

    # ---- 2. Enrich pitchers from DB --------------------------------------
    def _build_pitcher_block(
        pitcher_id: Optional[int],
        name: str,
    ) -> Optional[Dict[str, Any]]:
        if not pitcher_id:
            return None
        agg = get_pitcher_aggregate(session, pitcher_id, "90d")
        arsenal = get_pitch_arsenal(session, pitcher_id, season)
        recent = get_pitcher_game_log(session, pitcher_id, limit=5)
        hand = agg.p_throws if agg and hasattr(agg, "p_throws") else None
        return {
            "id": pitcher_id,
            "name": name,
            "hand": hand,
            "aggregate": _pitcher_aggregate_dict(agg),
            "data_source": "90d",
            "arsenal": _arsenal_list(arsenal),
            "recent_outings": recent,
        }

    away_pitcher_block = _build_pitcher_block(
        away_pitcher_id, away_pitcher_stub.get("name", "")
    )
    home_pitcher_block = _build_pitcher_block(
        home_pitcher_id, home_pitcher_stub.get("name", "")
    )

    # ---- 3. Enrich lineup batters from DB --------------------------------
    def _enrich_lineup(
        lineup: List[Dict[str, Any]],
        opposing_pitcher_hand: Optional[str],
    ) -> List[Dict[str, Any]]:
        enriched = []
        split_key = "vsR" if opposing_pitcher_hand == "R" else "vsL"
        for entry in lineup:
            batter_id = entry["batter_id"]
            agg = get_batter_aggregate(session, batter_id, "90d")
            split_vs = get_player_split(session, batter_id, season, split_key)
            enriched.append(
                {
                    **entry,
                    "aggregate": _batter_aggregate_dict(agg),
                    f"vs_{'rhp' if split_key == 'vsR' else 'lhp'}": _split_dict(split_vs),
                }
            )
        return enriched

    away_pitcher_hand = (away_pitcher_block or {}).get("hand")
    home_pitcher_hand = (home_pitcher_block or {}).get("hand")

    away_lineup = _enrich_lineup(live_lineup.get("away", []), home_pitcher_hand)
    home_lineup = _enrich_lineup(live_lineup.get("home", []), away_pitcher_hand)

    # ---- 4. Team splits from DB ------------------------------------------
    away_team_splits = _team_split_dict(session, away_team_id, season)
    home_team_splits = _team_split_dict(session, home_team_id, season)

    # ---- 5. Win probability ----------------------------------------------
    win_prob: Dict[str, Any] = {"away": None, "home": None, "confidence": "No Data"}
    if away_pitcher_id and home_pitcher_id and away_team_id and home_team_id:
        try:
            home_wp, away_wp = compute_win_probability(
                session,
                home_pitcher_id=home_pitcher_id,
                away_pitcher_id=away_pitcher_id,
                home_team_id=home_team_id,
                away_team_id=away_team_id,
                season=season,
                home_pitcher_throws=home_pitcher_hand or "R",
                away_pitcher_throws=away_pitcher_hand or "R",
            )
            win_prob = {
                "away": away_wp,
                "home": home_wp,
                "confidence": "Full Data",
            }
        except Exception:
            win_prob = {"away": None, "home": None, "confidence": "Error"}

    # ---- 6. Assemble final response --------------------------------------
    return {
        "game_pk": game_pk,
        "game_date": game_info.get("game_date"),
        "time": game_info.get("time"),
        "venue": game_info.get("venue"),
        "status": game_info.get("status"),
        "away_team": game_info.get("away_team"),
        "home_team": game_info.get("home_team"),
        "away_pitcher": away_pitcher_block,
        "home_pitcher": home_pitcher_block,
        "away_lineup": away_lineup,
        "home_lineup": home_lineup,
        "away_team_splits": away_team_splits,
        "home_team_splits": home_team_splits,
        "away_pitcher_recent_outings": (away_pitcher_block or {}).get("recent_outings", []),
        "home_pitcher_recent_outings": (home_pitcher_block or {}).get("recent_outings", []),
        "win_probability": win_prob,
    }


__all__ = [
    "fetch_live_lineup",
    "fetch_game_info",
    "build_matchup_detail",
]

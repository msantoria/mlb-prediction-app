"""Normalized MLB Stats API season lines for site-wide player contracts."""

from __future__ import annotations

import datetime
from typing import Any, Dict, List

import requests


MLB_STATS_URL = "https://statsapi.mlb.com/api/v1/stats"
OFFICIAL_HITTING_SOURCE = "mlb_stats_api_season_hitting"


class OfficialPlayerStatsUnavailable(RuntimeError):
    """Raised when an official season-stat population cannot be retrieved."""


def _integer(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _decimal(value: Any) -> float | None:
    try:
        return float(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


def normalize_official_hitting_splits(payload: Dict[str, Any], season: int) -> List[Dict[str, Any]]:
    """Return one authoritative regular-season hitting line per MLB player ID."""

    stats_groups = payload.get("stats") or []
    splits = (stats_groups[0].get("splits") or []) if stats_groups else []
    normalized: Dict[int, Dict[str, Any]] = {}

    for split in splits:
        player = split.get("player") or split.get("person") or {}
        player_id = _integer(player.get("id"))
        if not player_id:
            continue

        stat = split.get("stat") or {}
        team = split.get("team") or player.get("currentTeam") or {}
        avg = _decimal(stat.get("avg"))
        slg = _decimal(stat.get("slg"))
        pa = _integer(stat.get("plateAppearances"))
        walks = _integer(stat.get("baseOnBalls"))
        strikeouts = _integer(stat.get("strikeOuts"))

        normalized[player_id] = {
            "player_id": player_id,
            "player_name": player.get("fullName") or player.get("name") or f"MLB ID {player_id}",
            "team": team.get("abbreviation") or team.get("name") or "",
            "season": int(season),
            "pa": pa,
            "ab": _integer(stat.get("atBats")),
            "hits": _integer(stat.get("hits")),
            "home_runs": _integer(stat.get("homeRuns")),
            "doubles": _integer(stat.get("doubles")),
            "rbi": _integer(stat.get("rbi")),
            "walks": walks,
            "strikeouts": strikeouts,
            "batting_avg": avg,
            "slugging_pct": slg,
            "iso": round(slg - avg, 3) if slg is not None and avg is not None else None,
            "bb_pct": round(walks / pa, 3) if pa else None,
            "k_pct": round(strikeouts / pa, 3) if pa else None,
            "source": OFFICIAL_HITTING_SOURCE,
        }

    return list(normalized.values())


def fetch_official_hitting_season(season: int, *, timeout: int = 20) -> Dict[str, Any]:
    """Fetch the complete official MLB regular-season hitter population."""

    try:
        response = requests.get(
            MLB_STATS_URL,
            params={
                "stats": "season",
                "group": "hitting",
                "gameType": "R",
                "sportIds": 1,
                "playerPool": "ALL",
                "season": int(season),
                "limit": 5000,
                "hydrate": "person(currentTeam),team",
            },
            timeout=timeout,
        )
        response.raise_for_status()
        rows = normalize_official_hitting_splits(response.json(), int(season))
    except (requests.RequestException, ValueError, TypeError) as exc:
        raise OfficialPlayerStatsUnavailable(str(exc)) from exc

    if not rows:
        raise OfficialPlayerStatsUnavailable(
            f"MLB Stats API returned no regular-season hitting rows for {season}."
        )

    return {
        "season": int(season),
        "source": OFFICIAL_HITTING_SOURCE,
        "retrieved_at": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
        "rows": rows,
    }

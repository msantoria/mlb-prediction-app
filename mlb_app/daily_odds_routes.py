from __future__ import annotations

import datetime
import re
from typing import Any, Dict, List, Optional

from fastapi import APIRouter

from .daily_odds_models import build_game_models
from .matchup_generator import generate_matchups_for_date
from .odds_provider import fetch_draftkings_events, fetch_draftkings_event_odds

router = APIRouter()


def _normalize_team_key(name: Any) -> str:
    return re.sub(r"[^a-z0-9]", "", str(name or "").lower().replace("the", "", 1))


def _matchup_key(away: Any, home: Any) -> str:
    return f"{_normalize_team_key(away)}@{_normalize_team_key(home)}"


def _key_from_matchup(matchup: Dict[str, Any]) -> str:
    return _matchup_key(
        matchup.get("away_team_name") or matchup.get("away_team") or matchup.get("away_name"),
        matchup.get("home_team_name") or matchup.get("home_team") or matchup.get("home_name"),
    )


def _key_from_event(event: Dict[str, Any]) -> str:
    away = event.get("away_team") or {}
    home = event.get("home_team") or {}
    away_name = away.get("name") if isinstance(away, dict) else away
    home_name = home.get("name") if isinstance(home, dict) else home
    return _matchup_key(away_name, home_name)


def _build_matchup_index(matchups: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    index: Dict[str, Dict[str, Any]] = {}
    for matchup in matchups or []:
        key = _key_from_matchup(matchup)
        if key != "@":
            index[key] = matchup
    return index


@router.get("/daily-odds/models")
def daily_odds_models(date: Optional[str] = None) -> Dict[str, Any]:
    target_date = date or datetime.date.today().isoformat()
    matchups = generate_matchups_for_date(target_date)
    odds_payload = fetch_draftkings_events(date=target_date, raw=False)
    events = odds_payload.get("events", []) if isinstance(odds_payload, dict) else []
    matchup_index = _build_matchup_index(matchups)

    outputs: List[Dict[str, Any]] = []
    for event in events:
        key = _key_from_event(event)
        matchup = matchup_index.get(key)
        if not matchup:
            outputs.append({
                "event_id": event.get("event_id"),
                "matched": False,
                "match_key": key,
                "models": None,
                "missing_inputs": ["matched_mlb_game"],
            })
            continue
        outputs.append({
            "game_pk": matchup.get("game_pk"),
            "event_id": event.get("event_id"),
            "matched": True,
            "match_key": key,
            "models": build_game_models(matchup, event),
        })

    return {
        "date": target_date,
        "count": len(outputs),
        "matched_count": sum(1 for row in outputs if row.get("matched")),
        "unmatched_count": sum(1 for row in outputs if not row.get("matched")),
        "odds_status": odds_payload.get("status") if isinstance(odds_payload, dict) else None,
        "last_updated": odds_payload.get("last_updated") if isinstance(odds_payload, dict) else None,
        "models": outputs,
    }


@router.get("/daily-odds/event/{event_id}/prop-models")
def daily_odds_prop_models(event_id: str, market: Optional[str] = None) -> Dict[str, Any]:
    from .daily_odds_models import build_prop_models

    payload = fetch_draftkings_event_odds(event_id, props_only=True, raw=False)
    prop_markets = payload.get("markets", []) if isinstance(payload, dict) else []
    return {
        "event_id": event_id,
        "market_filter": market or "all",
        "models": build_prop_models({}, prop_markets, market_filter=market or "all"),
        "odds_status": payload.get("status") if isinstance(payload, dict) else None,
        "last_updated": payload.get("last_updated") if isinstance(payload, dict) else None,
    }

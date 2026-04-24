import os
import time
from typing import Any, Dict, List, Optional

from apify_client import ApifyClient

_CACHE: Dict[str, Dict[str, Any]] = {}


def _cache_get(key: str):
    entry = _CACHE.get(key)
    if entry and time.time() < entry["expires_at"]:
        return entry["data"]
    return None


def _cache_set(key: str, data: Any, ttl: int = 60):
    _CACHE[key] = {
        "data": data,
        "expires_at": time.time() + ttl,
    }


def _provider_not_configured(scope: str, game_pk: Optional[int] = None) -> Dict[str, Any]:
    return {
        "provider": "draftkings",
        "status": "provider_not_configured",
        "scope": scope,
        "game_pk": game_pk,
        "markets": [],
        "books": ["DraftKings"],
        "last_updated": None,
        "raw_count": 0,
        "market_count": 0,
        "errors": [],
        "message": "APIFY_TOKEN is not configured.",
    }


def _first_present(row: Dict[str, Any], keys: List[str]) -> Any:
    for key in keys:
        if key in row and row[key] not in (None, ""):
            return row[key]
    return None


def _to_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _decimal_price(price: Any) -> Optional[float]:
    n = _to_float(price)
    if n is None:
        return None
    if n > 0:
        return round((n / 100) + 1, 4)
    if n < 0:
        return round((100 / abs(n)) + 1, 4)
    return None


def _implied_probability(price: Any) -> Optional[float]:
    n = _to_float(price)
    if n is None:
        return None
    if n > 0:
        return round(100 / (n + 100), 4)
    if n < 0:
        return round(abs(n) / (abs(n) + 100), 4)
    return None


def _normalize_selection(row: Dict[str, Any]) -> Dict[str, Any]:
    price = _first_present(row, ["price", "odds", "americanOdds", "american_odds", "oddsAmerican"])
    return {
        "name": _first_present(row, ["name", "selection", "outcome", "label", "participant", "playerName", "teamName"]),
        "team": _first_present(row, ["team", "teamAbbreviation", "team_abbreviation", "teamName"]),
        "side": _first_present(row, ["side", "homeAway", "designation"]),
        "line": _first_present(row, ["line", "points", "handicap", "total", "spread"]),
        "price": price,
        "decimal_price": _decimal_price(price),
        "implied_probability": _implied_probability(price),
        "raw": row,
    }


def _normalize_items(items: List[Dict[str, Any]], scope: str, game_pk: Optional[int] = None) -> List[Dict[str, Any]]:
    markets: List[Dict[str, Any]] = []
    for idx, item in enumerate(items):
        if game_pk is not None:
            raw_game_pk = _first_present(item, ["game_pk", "gamePk", "mlbGamePk", "eventId", "event_id"])
            if raw_game_pk is not None and str(raw_game_pk) != str(game_pk):
                continue

        market_name = _first_present(item, ["marketName", "market_name", "market", "name", "categoryName"])
        market_key = _first_present(item, ["marketKey", "market_key", "marketType", "market_type", "category"])
        selections = _first_present(item, ["selections", "outcomes", "runners", "offers", "participants"])
        normalized_selections: List[Dict[str, Any]] = []
        if isinstance(selections, list):
            normalized_selections = [_normalize_selection(sel) for sel in selections if isinstance(sel, dict)]
        else:
            normalized_selections = [_normalize_selection(item)]

        markets.append({
            "market_key": str(market_key or market_name or f"market_{idx}"),
            "market_name": str(market_name or market_key or "DraftKings Market"),
            "market_type": _first_present(item, ["marketType", "market_type", "type"]),
            "period": _first_present(item, ["period", "periodName", "period_name"]),
            "game_pk": _first_present(item, ["game_pk", "gamePk", "mlbGamePk"]),
            "event_id": _first_present(item, ["eventId", "event_id", "id"]),
            "start_time": _first_present(item, ["startTime", "start_time", "commence_time"]),
            "is_live": bool(_first_present(item, ["isLive", "is_live", "live"])),
            "selections": normalized_selections,
            "raw": item,
        })
    return markets


def fetch_draftkings_odds(scope: str = "pregame", game_pk: Optional[int] = None, props_only: bool = False) -> Dict[str, Any]:
    token = os.getenv("APIFY_TOKEN")
    if not token:
        return _provider_not_configured(scope, game_pk=game_pk)

    cache_key = f"dk:{scope}:{game_pk or 'all'}:{props_only}"
    cached = _cache_get(cache_key)
    if cached:
        return cached

    client = ApifyClient(token)

    run_input = {
        "leagues": [os.getenv("DRAFTKINGS_ODDS_LEAGUE", "MLB")],
        "marketTypes": ["player_props" if props_only else "all"],
        "liveOnly": scope == "live",
        "usState": os.getenv("DRAFTKINGS_ODDS_STATE", "IL"),
    }

    run = client.actor(os.getenv("DRAFTKINGS_ODDS_ACTOR_ID", "mherzog/draftkings-sportsbook-odds")).call(run_input=run_input)
    items: List[Dict[str, Any]] = list(client.dataset(run["defaultDatasetId"]).iterate_items())
    markets = _normalize_items(items, scope=scope, game_pk=game_pk)

    normalized = {
        "provider": "draftkings",
        "status": "ok",
        "scope": scope,
        "sport": "baseball_mlb",
        "game_pk": game_pk,
        "books": ["DraftKings"],
        "markets": markets,
        "last_updated": int(time.time()),
        "raw_count": len(items),
        "market_count": len(markets),
        "errors": [],
        "run_input": run_input,
    }

    ttl = int(os.getenv("DRAFTKINGS_ODDS_CACHE_TTL_SECONDS", "60"))
    _cache_set(cache_key, normalized, ttl)
    return normalized

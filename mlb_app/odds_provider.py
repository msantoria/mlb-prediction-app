import os
import time
from typing import Any, Dict, List, Optional

import requests

_CACHE: Dict[str, Dict[str, Any]] = {}
_ODDS_API_BASE = "https://api.the-odds-api.com/v4"
_ODDS_API_SPORT = "baseball_mlb"
_DEFAULT_BOOKMAKER = "draftkings"
_DEFAULT_REGIONS = "us"
_DEFAULT_MARKETS = ["h2h", "spreads", "totals"]
_MARKET_TYPE_MAP = {
    "moneyline": "h2h",
    "h2h": "h2h",
    "spread": "spreads",
    "spreads": "spreads",
    "total": "totals",
    "totals": "totals",
    "player_props": "player_props",
    "props": "player_props",
    "all": "all",
}


def _cache_get(key: str):
    entry = _CACHE.get(key)
    if entry and time.time() < entry["expires_at"]:
        return entry["data"]
    return None


def _cache_set(key: str, data: Any, ttl: int = 300):
    _CACHE[key] = {"data": data, "expires_at": time.time() + ttl}


def _provider_not_configured(scope: str, game_pk: Optional[int] = None, message: str = "ODDS_API_KEY is not configured.") -> Dict[str, Any]:
    return {
        "provider": "the_odds_api",
        "book": "DraftKings",
        "status": "provider_not_configured",
        "scope": scope,
        "game_pk": game_pk,
        "markets": [],
        "events": [],
        "books": ["DraftKings"],
        "last_updated": None,
        "raw_count": 0,
        "event_count": 0,
        "market_count": 0,
        "errors": [],
        "message": message,
    }


def _provider_error(scope: str, game_pk: Optional[int], exc: Exception, request_params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    return {
        "provider": "the_odds_api",
        "book": "DraftKings",
        "status": "provider_error",
        "scope": scope,
        "game_pk": game_pk,
        "markets": [],
        "events": [],
        "books": ["DraftKings"],
        "last_updated": int(time.time()),
        "raw_count": 0,
        "event_count": 0,
        "market_count": 0,
        "errors": [str(exc)],
        "message": "The Odds API provider failed while fetching DraftKings odds.",
        "request_params": request_params or {},
    }


def _parse_markets(market_types: Optional[List[str]], props_only: bool = False) -> List[str]:
    if props_only:
        return ["player_props"]
    if not market_types:
        env_value = os.getenv("ODDS_API_MARKETS")
        raw = [m.strip() for m in env_value.split(",") if m.strip()] if env_value else _DEFAULT_MARKETS
    else:
        raw = market_types
    mapped: List[str] = []
    for market in raw:
        value = _MARKET_TYPE_MAP.get(str(market).strip().lower(), str(market).strip())
        if value == "all":
            value = "h2h,spreads,totals"
            for piece in value.split(","):
                if piece not in mapped:
                    mapped.append(piece)
            continue
        if value not in mapped:
            mapped.append(value)
    return mapped or _DEFAULT_MARKETS


def _odds_decimal_from_american(price: Optional[float]) -> Optional[float]:
    if price is None:
        return None
    try:
        price = float(price)
    except (TypeError, ValueError):
        return None
    if price > 0:
        return round(1 + price / 100, 4)
    if price < 0:
        return round(1 + 100 / abs(price), 4)
    return None


def _implied_from_american(price: Optional[float]) -> Optional[float]:
    if price is None:
        return None
    try:
        price = float(price)
    except (TypeError, ValueError):
        return None
    if price > 0:
        return round(100 / (price + 100), 4)
    if price < 0:
        return round(abs(price) / (abs(price) + 100), 4)
    return None


def _normalize_selection(outcome: Dict[str, Any], market: Dict[str, Any]) -> Dict[str, Any]:
    price = outcome.get("price")
    return {
        "selection_id": None,
        "name": outcome.get("name"),
        "team": outcome.get("name"),
        "side": None,
        "line": outcome.get("point") if outcome.get("point") is not None else market.get("point"),
        "odds": {
            "american": price,
            "decimal": _odds_decimal_from_american(price),
            "fractional": None,
            "implied_probability": _implied_from_american(price),
        },
        "price": price,
        "is_open": True,
        "raw": outcome,
    }


def _normalize_event(item: Dict[str, Any], bookmaker_key: str = _DEFAULT_BOOKMAKER) -> Dict[str, Any]:
    target_book = None
    for bookmaker in item.get("bookmakers", []) or []:
        if bookmaker.get("key") == bookmaker_key:
            target_book = bookmaker
            break
    if target_book is None and item.get("bookmakers"):
        target_book = item.get("bookmakers", [None])[0]
    book_markets = target_book.get("markets", []) if isinstance(target_book, dict) else []
    markets: List[Dict[str, Any]] = []
    for market in book_markets:
        outcomes = market.get("outcomes") if isinstance(market.get("outcomes"), list) else []
        markets.append({
            "market_id": market.get("key"),
            "market_key": market.get("key"),
            "market_name": market.get("key"),
            "market_type": market.get("key"),
            "line": None,
            "period": None,
            "is_open": True,
            "last_update": market.get("last_update"),
            "bookmaker_key": target_book.get("key") if isinstance(target_book, dict) else None,
            "bookmaker_title": target_book.get("title") if isinstance(target_book, dict) else None,
            "selections": [_normalize_selection(outcome, market) for outcome in outcomes if isinstance(outcome, dict)],
            "raw": market,
        })
    return {
        "event_id": item.get("id"),
        "name": f"{item.get('away_team')} @ {item.get('home_team')}",
        "sport": item.get("sport_title"),
        "league": item.get("sport_key"),
        "league_id": item.get("sport_key"),
        "home_team": {"name": item.get("home_team")},
        "away_team": {"name": item.get("away_team")},
        "start_time": item.get("commence_time"),
        "status": "scheduled",
        "is_live": False,
        "source_url": None,
        "scraped_at": int(time.time()),
        "markets": markets,
        "market_count": len(markets),
        "raw": item,
    }


def _flatten_markets(events: List[Dict[str, Any]], game_pk: Optional[int] = None) -> List[Dict[str, Any]]:
    flat: List[Dict[str, Any]] = []
    for event in events:
        event_id = event.get("event_id")
        if game_pk is not None and event_id is not None and str(event_id) != str(game_pk):
            continue
        for market in event.get("markets", []):
            row = dict(market)
            row.pop("raw", None)
            row["event_id"] = event_id
            row["event_name"] = event.get("name")
            row["league"] = event.get("league")
            row["league_id"] = event.get("league_id")
            row["start_time"] = event.get("start_time")
            row["is_live"] = event.get("is_live")
            row["source_url"] = event.get("source_url")
            flat.append(row)
    return flat


def _filter_events(events: List[Dict[str, Any]], game_pk: Optional[int], target_date: Optional[str]) -> List[Dict[str, Any]]:
    filtered: List[Dict[str, Any]] = []
    for event in events:
        if game_pk is not None and event.get("event_id") is not None and str(event.get("event_id")) != str(game_pk):
            continue
        if target_date:
            start_time = event.get("start_time") or ""
            if start_time and not str(start_time).startswith(target_date):
                continue
        filtered.append(event)
    return filtered


def _fetch_odds_api(params: Dict[str, Any]) -> List[Dict[str, Any]]:
    url = f"{_ODDS_API_BASE}/sports/{_ODDS_API_SPORT}/odds"
    response = requests.get(url, params=params, timeout=20)
    response.raise_for_status()
    return response.json()


def build_draftkings_run_input(
    scope: str = "pregame",
    props_only: bool = False,
    date: Optional[str] = None,
    league: Optional[str] = None,
    market_types: Optional[List[str]] = None,
    live_only: Optional[bool] = None,
    state: Optional[str] = None,
) -> Dict[str, Any]:
    markets = _parse_markets(market_types, props_only=props_only)
    return {
        "apiKey": "***",
        "sport": _ODDS_API_SPORT,
        "regions": os.getenv("ODDS_API_REGIONS", _DEFAULT_REGIONS),
        "markets": ",".join(markets),
        "oddsFormat": os.getenv("ODDS_API_ODDS_FORMAT", "american"),
        "dateFormat": os.getenv("ODDS_API_DATE_FORMAT", "iso"),
        "bookmakers": os.getenv("ODDS_API_BOOKMAKERS", _DEFAULT_BOOKMAKER),
        "scope": scope,
        "target_date": date,
    }


def fetch_draftkings_odds(
    scope: str = "pregame",
    game_pk: Optional[int] = None,
    props_only: bool = False,
    date: Optional[str] = None,
    raw: bool = False,
    league: Optional[str] = None,
    market_types: Optional[List[str]] = None,
    live_only: Optional[bool] = None,
    state: Optional[str] = None,
) -> Dict[str, Any]:
    token = os.getenv("ODDS_API_KEY") or os.getenv("THE_ODDS_API_KEY")
    if not token:
        return _provider_not_configured(scope, game_pk=game_pk)

    request_params = build_draftkings_run_input(scope, props_only, date, league, market_types, live_only, state)
    actual_params = dict(request_params)
    actual_params["apiKey"] = token
    cache_key = f"oddsapi:{scope}:{game_pk or 'all'}:{props_only}:{date or 'any'}:{request_params}:{raw}"
    cached = _cache_get(cache_key)
    if cached:
        cached_copy = dict(cached)
        cached_copy["cache_hit"] = True
        return cached_copy

    try:
        items = _fetch_odds_api(actual_params)
        events = [_normalize_event(item, bookmaker_key=os.getenv("ODDS_API_BOOKMAKERS", _DEFAULT_BOOKMAKER)) for item in items if isinstance(item, dict)]
        events = _filter_events(events, game_pk=game_pk, target_date=date)
        markets = _flatten_markets(events, game_pk=game_pk)
    except Exception as exc:
        return _provider_error(scope, game_pk, exc, request_params=request_params)

    normalized = {
        "provider": "the_odds_api",
        "book": "DraftKings",
        "status": "ok" if items else "empty",
        "scope": scope,
        "sport": _ODDS_API_SPORT,
        "game_pk": game_pk,
        "target_date": date,
        "books": ["DraftKings"],
        "events": events,
        "markets": markets,
        "last_updated": int(time.time()),
        "raw_count": len(items),
        "event_count": len(events),
        "market_count": len(markets),
        "errors": [],
        "request_params": request_params,
        "cache_hit": False,
    }
    if raw or scope == "debug":
        normalized["raw_items_sample"] = items[:10]
    ttl = int(os.getenv("ODDS_API_CACHE_TTL_SECONDS", "300"))
    _cache_set(cache_key, normalized, ttl)
    return normalized

import os
import time
from typing import Any, Dict, List

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


def _provider_not_configured(scope: str) -> Dict[str, Any]:
    return {
        "provider": "draftkings",
        "status": "provider_not_configured",
        "scope": scope,
        "markets": [],
        "books": ["DraftKings"],
        "last_updated": None,
        "message": "APIFY_TOKEN is not configured.",
    }


def fetch_draftkings_odds(scope: str = "pregame") -> Dict[str, Any]:
    token = os.getenv("APIFY_TOKEN")
    if not token:
        return _provider_not_configured(scope)

    cache_key = f"dk:{scope}"
    cached = _cache_get(cache_key)
    if cached:
        return cached

    client = ApifyClient(token)

    run_input = {
        "leagues": ["MLB"],
        "marketTypes": ["all"],
        "liveOnly": scope == "live",
        "usState": os.getenv("DRAFTKINGS_ODDS_STATE", "IL"),
    }

    run = client.actor(
        os.getenv(
            "DRAFTKINGS_ODDS_ACTOR_ID",
            "mherzog/draftkings-sportsbook-odds",
        )
    ).call(run_input=run_input)

    items: List[Dict[str, Any]] = list(
        client.dataset(
            run["defaultDatasetId"]
        ).iterate_items()
    )

    normalized = {
        "provider": "draftkings",
        "status": "ok",
        "scope": scope,
        "books": ["DraftKings"],
        "markets": items,
        "last_updated": int(time.time()),
        "raw_count": len(items),
        "errors": [],
    }

    ttl = int(
        os.getenv(
            "DRAFTKINGS_ODDS_CACHE_TTL_SECONDS",
            "60",
        )
    )

    _cache_set(cache_key, normalized, ttl)

    return normalized

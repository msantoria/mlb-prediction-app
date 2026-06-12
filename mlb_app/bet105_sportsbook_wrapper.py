from __future__ import annotations

import datetime as dt
import os
import re
import time
from collections import defaultdict
from typing import Any, Dict, Iterable, List, Optional, Tuple
from zoneinfo import ZoneInfo

import requests

from .kibl_bet105_provider import _configured, _get_access_token, _not_configured, _redact

_PROVIDER = "kibl_bet105"
_BOOK = "Bet105"
_BASE_URL = "https://api.kibl.io/sports/get"
_ET = ZoneInfo(os.getenv("KIBL_TIMEZONE", "America/New_York"))
_UTC = dt.timezone.utc

_EVENT_ID_KEYS = (
    "event_id", "eventId", "eventID", "fixture_id", "fixtureId", "fixtureID",
    "game_id", "gameId", "match_id", "matchId", "id", "event",
)
_HOME_KEYS = (
    "home_team", "homeTeam", "home_team_name", "homeTeamName", "home",
    "home_name", "homeName", "home_participant", "homeParticipant", "home_competitor",
)
_AWAY_KEYS = (
    "away_team", "awayTeam", "away_team_name", "awayTeamName", "away",
    "away_name", "awayName", "away_participant", "awayParticipant", "away_competitor",
)
_START_KEYS = (
    "start_time", "startTime", "event_time", "eventTime", "event_date", "eventDate",
    "fixture_date", "start_date", "startDate", "scheduled", "date", "match_date",
)
_MARKET_KEYS = (
    "market_key", "marketKey", "market_type", "marketType", "market_name", "marketName",
    "market", "bet_type", "betType", "wager_type", "wagerType", "type", "name",
    "description", "label",
)
_SELECTION_KEYS = (
    "selection", "selection_name", "selectionName", "outcome", "outcome_name", "outcomeName",
    "runner", "runner_name", "runnerName", "label", "team", "team_name", "participant",
    "participant_name", "player_name", "playerName", "side", "designation", "name",
)
_PRICE_KEYS = (
    "american", "american_odds", "americanOdds", "odds_american", "price", "line_price",
    "linePrice", "current_price", "currentPrice", "moneyline", "odds_value",
)
_DECIMAL_KEYS = ("decimal", "decimal_odds", "decimalOdds", "odds_decimal")
_LINE_KEYS = ("line", "point", "points", "handicap", "spread", "total", "threshold", "value")
_LIST_KEYS = ("data", "items", "results", "fixtures", "events", "games", "matches", "markets", "odds", "lines", "prices", "outcomes", "selections", "runners", "rows", "records")

_MARKET_ALIASES = {
    "moneyline": "h2h",
    "money_line": "h2h",
    "money_line_3_way": "h2h",
    "ml": "h2h",
    "h2h": "h2h",
    "head_to_head": "h2h",
    "spread": "spreads",
    "spreads": "spreads",
    "run_line": "spreads",
    "runline": "spreads",
    "point_spread": "spreads",
    "total": "totals",
    "totals": "totals",
    "total_runs": "totals",
    "over_under": "totals",
    "ou": "totals",
}

_CACHE: Dict[str, Dict[str, Any]] = {}


def _now() -> int:
    return int(time.time())


def _cache_get(key: str) -> Optional[Dict[str, Any]]:
    entry = _CACHE.get(key)
    if entry and time.time() < entry.get("expires_at", 0):
        data = dict(entry.get("data") or {})
        data["cache_hit"] = True
        return data
    return None


def _cache_set(key: str, data: Dict[str, Any]) -> None:
    ttl = int(os.getenv("KIBL_CACHE_TTL_SECONDS", "120"))
    _CACHE[key] = {"data": data, "expires_at": time.time() + ttl}


def _safe_float(value: Any) -> Optional[float]:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _safe_int(value: Any) -> Optional[int]:
    number = _safe_float(value)
    return int(round(number)) if number is not None else None


def _extract_first(row: Dict[str, Any], keys: Iterable[str]) -> Any:
    for key in keys:
        if key in row and row.get(key) not in (None, ""):
            return row.get(key)
    return None


def _name(value: Any) -> Optional[str]:
    if value in (None, ""):
        return None
    if isinstance(value, str):
        return value
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, dict):
        for key in ("name", "display_name", "displayName", "full_name", "fullName", "title", "team_name", "teamName"):
            resolved = _name(value.get(key))
            if resolved:
                return resolved
        for key in ("team", "participant", "competitor", "runner", "outcome"):
            resolved = _name(value.get(key))
            if resolved:
                return resolved
    return None


def _slug(value: Any) -> str:
    return re.sub(r"[^a-z0-9_]+", "_", str(value or "").lower()).strip("_")


def _market_key(value: Any) -> str:
    slug = _slug(_name(value) or value)
    return _MARKET_ALIASES.get(slug, slug or "market")


def _decimal_from_american(price: Optional[int]) -> Optional[float]:
    if price is None:
        return None
    if price > 0:
        return round(1 + price / 100, 4)
    if price < 0:
        return round(1 + 100 / abs(price), 4)
    return None


def _american_from_decimal(decimal_price: Optional[float]) -> Optional[int]:
    if decimal_price is None or decimal_price <= 1:
        return None
    if decimal_price >= 2:
        return int(round((decimal_price - 1) * 100))
    return int(round(-100 / (decimal_price - 1)))


def _implied_from_american(price: Optional[int]) -> Optional[float]:
    if price is None:
        return None
    if price > 0:
        return round(100 / (price + 100), 4)
    if price < 0:
        return round(abs(price) / (abs(price) + 100), 4)
    return None


def _price(row: Dict[str, Any]) -> Optional[int]:
    value = _extract_first(row, _PRICE_KEYS)
    if isinstance(value, dict):
        nested_american = _extract_first(value, _PRICE_KEYS)
        parsed = _safe_int(nested_american)
        if parsed is not None and abs(parsed) >= 100:
            return parsed
        return _american_from_decimal(_safe_float(_extract_first(value, _DECIMAL_KEYS)))

    parsed = _safe_int(value)
    if parsed is not None and abs(parsed) >= 100:
        return parsed

    decimal = _safe_float(_extract_first(row, _DECIMAL_KEYS))
    if decimal is None and isinstance(row.get("odds"), dict):
        decimal = _safe_float(_extract_first(row["odds"], _DECIMAL_KEYS))
    return _american_from_decimal(decimal)


def _line(row: Dict[str, Any]) -> Optional[float]:
    return _safe_float(_extract_first(row, _LINE_KEYS))


def _parse_datetime(value: Any) -> Optional[str]:
    if not value:
        return None
    raw = str(value).strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%SZ"):
        try:
            parsed = dt.datetime.strptime(raw[:19] + ("Z" if fmt.endswith("Z") and raw.endswith("Z") else ""), fmt)
            tz = _UTC if raw.endswith("Z") else _ET
            return parsed.replace(tzinfo=tz).astimezone(_UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
        except ValueError:
            pass
    try:
        parsed = dt.datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=_ET)
        return parsed.astimezone(_UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    except ValueError:
        return None


def _date_body(date: Optional[str]) -> Dict[str, str]:
    if not date:
        return {}
    slate = dt.date.fromisoformat(str(date)[:10])
    start = dt.datetime.combine(slate, dt.time.min, tzinfo=_ET)
    end = start + dt.timedelta(days=1)
    fmt = "%Y-%m-%d %H:%M:%S"
    return {
        "start_date": start.astimezone(_ET).replace(tzinfo=None).strftime(fmt),
        "end_date": end.astimezone(_ET).replace(tzinfo=None).strftime(fmt),
        "from": start.astimezone(_ET).replace(tzinfo=None).strftime(fmt),
        "to": end.astimezone(_ET).replace(tzinfo=None).strftime(fmt),
    }


def _base_body(date: Optional[str], live_only: Optional[bool]) -> Dict[str, Any]:
    is_live = bool(live_only)
    body: Dict[str, Any] = {
        "feed_source_id": int(os.getenv("KIBL_FEED_SOURCE_ID", "171")),
        "betting_type_id": int(os.getenv("KIBL_LIVE_BETTING_TYPE_ID" if is_live else "KIBL_PREMATCH_BETTING_TYPE_ID", "3" if is_live else "1")),
        "league_id": os.getenv("KIBL_LEAGUE_ID", "20,643"),
        "from_cache": False,
    }
    body.update(_date_body(date))
    return body


def _post(path: str, body: Dict[str, Any]) -> Tuple[Any, str]:
    token = _get_access_token()
    base_url = os.getenv("KIBL_BASE_URL", _BASE_URL).rstrip("/")
    url = f"{base_url}/{path.strip('/')}/"
    response = requests.post(
        url,
        json=body,
        headers={"Authorization": f"Bearer {token}", "Accept": "application/json", "Content-Type": "application/json"},
        timeout=int(os.getenv("KIBL_TIMEOUT_SECONDS", "20")),
    )
    if response.status_code == 401:
        # Force a fresh Cognito token and retry once.
        try:
            from . import kibl_bet105_provider
            kibl_bet105_provider._TOKEN_CACHE.clear()
        except Exception:
            pass
        token = _get_access_token()
        response = requests.post(
            url,
            json=body,
            headers={"Authorization": f"Bearer {token}", "Accept": "application/json", "Content-Type": "application/json"},
            timeout=int(os.getenv("KIBL_TIMEOUT_SECONDS", "20")),
        )
    response.raise_for_status()
    return response.json(), path.strip("/")


def _walk_lists(value: Any) -> Iterable[List[Dict[str, Any]]]:
    if isinstance(value, list):
        rows = [item for item in value if isinstance(item, dict)]
        if rows:
            yield rows
        for item in value:
            yield from _walk_lists(item)
    elif isinstance(value, dict):
        for key in _LIST_KEYS:
            child = value.get(key)
            if isinstance(child, list):
                rows = [item for item in child if isinstance(item, dict)]
                if rows:
                    yield rows
        for child in value.values():
            yield from _walk_lists(child)


def _walk_dicts(value: Any) -> Iterable[Dict[str, Any]]:
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _walk_dicts(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_dicts(child)


def _row_signal(row: Dict[str, Any]) -> int:
    keys = set(row.keys())
    score = 0
    if keys.intersection(_EVENT_ID_KEYS):
        score += 3
    if keys.intersection(_HOME_KEYS) or keys.intersection(_AWAY_KEYS):
        score += 4
    if keys.intersection(_MARKET_KEYS):
        score += 2
    if keys.intersection(_SELECTION_KEYS):
        score += 1
    if keys.intersection(_PRICE_KEYS) or keys.intersection(_DECIMAL_KEYS):
        score += 4
    if keys.intersection(_START_KEYS):
        score += 1
    return score


def _find_rows(payload: Any) -> List[Dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    candidates = list(_walk_lists(payload))
    if candidates:
        return max(candidates, key=lambda rows: (sum(_row_signal(row) for row in rows[:50]), len(rows)))
    return []


def _event_id(row: Dict[str, Any], fallback: str) -> str:
    value = _extract_first(row, _EVENT_ID_KEYS)
    if isinstance(value, dict):
        value = _extract_first(value, _EVENT_ID_KEYS) or _name(value)
    return str(value or fallback)


def _teams(row: Dict[str, Any]) -> Tuple[Optional[str], Optional[str]]:
    home = _name(_extract_first(row, _HOME_KEYS))
    away = _name(_extract_first(row, _AWAY_KEYS))
    participants = row.get("competitors") or row.get("participants") or row.get("teams")
    if (not home or not away) and isinstance(participants, list):
        for participant in participants:
            if not isinstance(participant, dict):
                continue
            role = str(_extract_first(participant, ("home_away", "homeAway", "side", "type", "qualifier")) or "").lower()
            participant_name = _name(participant)
            if "home" in role and not home:
                home = participant_name
            elif "away" in role and not away:
                away = participant_name
        if len(participants) >= 2:
            away = away or _name(participants[0])
            home = home or _name(participants[1])
    return away, home


def _fixture_rows(payload: Any) -> List[Dict[str, Any]]:
    rows = _find_rows(payload)
    if not rows:
        rows = list(_walk_dicts(payload))
    fixtures: List[Dict[str, Any]] = []
    seen: set[str] = set()
    for idx, row in enumerate(rows):
        if not isinstance(row, dict):
            continue
        away, home = _teams(row)
        event_id = _event_id(row, f"fixture_{idx}")
        if event_id in seen:
            continue
        if away or home or _extract_first(row, _START_KEYS):
            seen.add(event_id)
            fixtures.append(row)
    return fixtures


def _context_from(row: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
    next_context = dict(context)
    event_id = _extract_first(row, _EVENT_ID_KEYS)
    if event_id is not None:
        next_context["event_id"] = _event_id(row, str(event_id))
    away, home = _teams(row)
    if away:
        next_context["away_team"] = away
    if home:
        next_context["home_team"] = home
    start = _extract_first(row, _START_KEYS)
    if start:
        next_context["start_time"] = start
    market = _extract_first(row, _MARKET_KEYS)
    if market:
        next_context["market_name"] = _name(market) or str(market)
    line = _line(row)
    if line is not None:
        next_context["line"] = line
    return next_context


def _collect_price_rows(node: Any, context: Optional[Dict[str, Any]] = None, rows: Optional[List[Dict[str, Any]]] = None) -> List[Dict[str, Any]]:
    context = context or {}
    rows = rows if rows is not None else []
    if isinstance(node, dict):
        next_context = _context_from(node, context)
        price = _price(node)
        selection = _name(_extract_first(node, _SELECTION_KEYS))
        market = next_context.get("market_name")
        if price is not None and (selection or market):
            rows.append({**next_context, **node})
        for child in node.values():
            _collect_price_rows(child, next_context, rows)
    elif isinstance(node, list):
        for child in node:
            _collect_price_rows(child, context, rows)
    return rows


def _fixture_event(row: Dict[str, Any], idx: int) -> Dict[str, Any]:
    event_id = _event_id(row, f"fixture_{idx}")
    away, home = _teams(row)
    return {
        "event_id": event_id,
        "name": str(_extract_first(row, ("event_name", "eventName", "matchup", "name", "description")) or (f"{away} @ {home}" if away or home else event_id)),
        "sport": _name(_extract_first(row, ("sport", "sport_title", "sport_name"))) or "Baseball",
        "league": _name(_extract_first(row, ("league", "league_name", "competition"))) or "MLB",
        "league_id": str(_extract_first(row, ("league_id", "leagueId", "competition_id")) or "mlb"),
        "away_team": {"name": away},
        "home_team": {"name": home},
        "start_time": _parse_datetime(_extract_first(row, _START_KEYS)),
        "status": str(_extract_first(row, ("status", "event_status", "eventStatus")) or "scheduled"),
        "is_live": bool(_extract_first(row, ("is_live", "isLive", "live", "in_play", "inPlay")) is True),
        "source_url": None,
        "scraped_at": _now(),
        "markets": [],
        "market_count": 0,
        "raw": row,
    }


def _selection(row: Dict[str, Any], idx: int) -> Dict[str, Any]:
    price = _price(row)
    name = _name(_extract_first(row, _SELECTION_KEYS)) or "Selection"
    line = _line(row)
    return {
        "selection_id": str(_extract_first(row, ("selection_id", "selectionId", "outcome_id", "outcomeId", "id")) or f"selection_{idx}"),
        "name": name,
        "description": str(_extract_first(row, ("description", "label", "selection_name", "selectionName")) or name),
        "team": _name(_extract_first(row, ("team", "team_name", "participant"))) or name,
        "side": str(_extract_first(row, ("side", "designation")) or name),
        "line": line,
        "odds": {
            "american": price,
            "decimal": _decimal_from_american(price),
            "fractional": None,
            "implied_probability": _implied_from_american(price),
        },
        "price": price,
        "is_open": True,
        "raw": row,
    }


def _market(rows: List[Dict[str, Any]], idx: int, event_id: str) -> Dict[str, Any]:
    seed = rows[0]
    raw_name = seed.get("market_name") or _extract_first(seed, _MARKET_KEYS) or "market"
    line = seed.get("line") if seed.get("line") is not None else _line(seed)
    market_key = _market_key(raw_name)
    return {
        "market_id": str(_extract_first(seed, ("market_id", "marketId", "id", "key")) or f"{event_id}_market_{idx}"),
        "market_key": market_key,
        "market_name": str(_name(raw_name) or raw_name or market_key),
        "market_type": market_key,
        "line": line,
        "period": _extract_first(seed, ("period", "period_name", "periodName")),
        "is_open": True,
        "last_update": _extract_first(seed, ("last_update", "lastUpdate", "updated_at", "updatedAt", "timestamp", "last_updated", "lastUpdated", "inserted_on", "insertedOn")),
        "bookmaker_key": "bet105",
        "bookmaker_title": _BOOK,
        "selections": [_selection(row, selection_idx) for selection_idx, row in enumerate(rows) if _price(row) is not None],
        "raw": {"rows": rows},
    }


def _latest_update(rows: List[Dict[str, Any]]) -> Optional[str]:
    values = []
    for row in rows:
        value = _extract_first(row, ("last_updated", "lastUpdated", "last_update", "lastUpdate", "updated_at", "updatedAt", "inserted_on", "insertedOn"))
        if value:
            values.append(str(value))
    return max(values) if values else None


def _events_from_market_rows(rows: List[Dict[str, Any]], fixtures: List[Dict[str, Any]], is_live: bool) -> List[Dict[str, Any]]:
    fixture_by_id = {_event_id(row, f"fixture_{idx}"): _fixture_event(row, idx) for idx, row in enumerate(fixtures)}
    only_fixture_id = next(iter(fixture_by_id)) if len(fixture_by_id) == 1 else None

    event_groups: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for idx, row in enumerate(rows):
        fallback = only_fixture_id or f"market_event_{idx}"
        event_groups[_event_id(row, fallback)].append(row)

    events: List[Dict[str, Any]] = []
    for event_idx, (event_id, event_rows) in enumerate(event_groups.items()):
        fixture = fixture_by_id.get(event_id) or (fixture_by_id.get(only_fixture_id) if only_fixture_id else None)
        seed = event_rows[0]
        seed_away, seed_home = _teams(seed)
        away = seed_away or (fixture or {}).get("away_team", {}).get("name")
        home = seed_home or (fixture or {}).get("home_team", {}).get("name")
        start = _extract_first(seed, _START_KEYS) or (fixture or {}).get("start_time")

        market_groups: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        for row in event_rows:
            raw_market = row.get("market_name") or _extract_first(row, _MARKET_KEYS) or "market"
            line = row.get("line") if row.get("line") is not None else _line(row)
            market_groups[f"{_market_key(raw_market)}:{line if line is not None else 'none'}"].append(row)

        markets = [_market(group_rows, market_idx, event_id) for market_idx, group_rows in enumerate(market_groups.values())]
        markets = [market for market in markets if market.get("selections")]
        events.append({
            "event_id": event_id,
            "name": (fixture or {}).get("name") or str(_extract_first(seed, ("event_name", "eventName", "matchup", "name", "description")) or (f"{away} @ {home}" if away or home else event_id)),
            "sport": (fixture or {}).get("sport") or "Baseball",
            "league": (fixture or {}).get("league") or "MLB",
            "league_id": (fixture or {}).get("league_id") or "mlb",
            "away_team": {"name": _name(away) or away},
            "home_team": {"name": _name(home) or home},
            "start_time": _parse_datetime(start) or start,
            "status": (fixture or {}).get("status") or ("live" if is_live else "scheduled"),
            "is_live": bool(is_live or (fixture or {}).get("is_live")),
            "source_url": None,
            "scraped_at": _now(),
            "markets": markets,
            "market_count": len(markets),
            "raw": {"rows": event_rows},
        })
    return events


def _without_raw(events: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    cleaned: List[Dict[str, Any]] = []
    for event in events:
        event_copy = dict(event)
        event_copy.pop("raw", None)
        event_copy["markets"] = []
        for market in event.get("markets") or []:
            market_copy = dict(market)
            market_copy.pop("raw", None)
            market_copy["selections"] = []
            for selection in market.get("selections") or []:
                selection_copy = dict(selection)
                selection_copy.pop("raw", None)
                market_copy["selections"].append(selection_copy)
            event_copy["markets"].append(market_copy)
        cleaned.append(event_copy)
    return cleaned


def _flatten_markets(events: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    markets: List[Dict[str, Any]] = []
    for event in events:
        for market in event.get("markets") or []:
            row = dict(market)
            row.pop("raw", None)
            row["event_id"] = event.get("event_id")
            row["event_name"] = event.get("name")
            row["league"] = event.get("league")
            row["league_id"] = event.get("league_id")
            row["start_time"] = event.get("start_time")
            row["is_live"] = event.get("is_live")
            markets.append(row)
    return markets


def _market_request_bodies(base: Dict[str, Any], since_last_updated: Optional[str] = None) -> List[Dict[str, Any]]:
    bodies = [dict(base)]
    if since_last_updated:
        bodies.insert(0, {**base, "since_last_updated": since_last_updated})
    return bodies


def fetch_bet105_sportsbook_events(date: Optional[str] = None, raw: bool = False, live_only: Optional[bool] = None) -> Dict[str, Any]:
    if not _configured():
        return _not_configured("live" if live_only else "events")

    cache_key = f"bet105-wrapper:{date}:{raw}:{live_only}:v2"
    cached = _cache_get(cache_key)
    if cached:
        return cached

    base_body = _base_body(date, live_only)
    notes: List[str] = []
    errors: List[str] = []
    request_params: Dict[str, Any] = {}
    fixture_rows: List[Dict[str, Any]] = []
    market_rows: List[Dict[str, Any]] = []
    last_path = None
    is_live = bool(live_only)

    try:
        fixture_payload, fixture_path = _post("info/fixtures", base_body)
        fixture_rows = _fixture_rows(fixture_payload)
        notes.append(f"fixtures:{fixture_path}:{len(fixture_rows)}")
    except Exception as exc:
        errors.append(f"fixtures_error:{exc}")

    since_last_updated: Optional[str] = None
    for body in _market_request_bodies(base_body, since_last_updated):
        try:
            payload, path = _post("info/markets", body)
            rows = _collect_price_rows(payload)
            last_path = path
            request_params = body
            notes.append(f"markets:{path}:{len(rows)}")
            if rows:
                market_rows = rows
                since_last_updated = _latest_update(rows)
                break
        except Exception as exc:
            errors.append(f"markets_error:{exc}")

    fixture_events = [_fixture_event(row, idx) for idx, row in enumerate(fixture_rows)]
    events = _events_from_market_rows(market_rows, fixture_rows, is_live) if market_rows else fixture_events
    markets = _flatten_markets(events)
    status = "fixtures_only" if events and not markets else ("ok" if events else "empty")

    response: Dict[str, Any] = {
        "provider": _PROVIDER,
        "book": _BOOK,
        "status": status,
        "scope": "live" if live_only else "events",
        "sport": "baseball_mlb",
        "game_pk": None,
        "event_id": None,
        "target_date": date,
        "books": [_BOOK],
        "events": events if raw else _without_raw(events),
        "markets": markets,
        "last_updated": _now(),
        "since_last_updated": since_last_updated,
        "raw_count": len(market_rows) or len(fixture_rows),
        "event_count": len(events),
        "market_count": len(markets),
        "errors": errors,
        "request_params": _redact({**request_params, "path": last_path or "info/fixtures"}),
        "cache_hit": False,
        "normalization_notes": notes,
    }
    if raw:
        response["raw_items_sample"] = _redact((market_rows or fixture_rows)[:10])
    _cache_set(cache_key, response)
    return response


def fetch_bet105_sportsbook_event(event_id: str, raw: bool = False, props_only: bool = False) -> Dict[str, Any]:
    payload = fetch_bet105_sportsbook_events(raw=raw)
    events = [event for event in payload.get("events") or [] if str(event.get("event_id")) == str(event_id)]
    payload["events"] = events
    payload["event"] = events[0] if events else None
    payload["markets"] = _flatten_markets(events)
    payload["event_count"] = len(events)
    payload["market_count"] = len(payload["markets"])
    payload["status"] = "fixtures_only" if events and not payload["markets"] else ("ok" if events else "empty")
    return payload

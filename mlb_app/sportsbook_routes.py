from __future__ import annotations

import datetime as dt
import os
import re
from contextlib import contextmanager
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException

from .sportsbook_bet105_runtime_v10 import fetch_event_board as fetch_kibl_bet105_event_odds
from .sportsbook_bet105_runtime_v10 import fetch_board as fetch_kibl_bet105_events
from .odds_provider import fetch_draftkings_events
from .database import SharedReportArtifact, create_tables, get_engine, get_session
from .model_tracker_price_snapshots import capture_bet105_price_snapshots, list_price_snapshots

router = APIRouter()

_PROVIDER_ENV_KEYS = ("ODDS_PROVIDER", "DRAFTKINGS_ODDS_PROVIDER", "SPORTSBOOK_ODDS_PROVIDER")


@contextmanager
def _force_default_draftkings_provider():
    """
    The comparison endpoint must fetch the real DraftKings provider even when the
    app-wide ODDS_PROVIDER is set to kibl_bet105 for the main Daily Odds flow.
    This local override is intentionally scoped to the single provider call.
    """
    previous = {key: os.environ.get(key) for key in _PROVIDER_ENV_KEYS}
    try:
        for key in _PROVIDER_ENV_KEYS:
            os.environ.pop(key, None)
        yield
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def _session_factory():
    database_url = os.getenv("DATABASE_URL") or os.getenv("SQLALCHEMY_DATABASE_URL") or os.getenv("POSTGRES_URL") or "sqlite:///mlb.db"
    engine = get_engine(database_url)
    create_tables(engine)
    return get_session(engine)


def _target_date(value: Optional[str]) -> str:
    target = (value or dt.date.today().isoformat())[:10]
    try:
        dt.date.fromisoformat(target)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid date: {value}") from exc
    return target


def _bet105_artifact_key(target_date: str) -> str:
    return f"bet105_board:{target_date}"


def _read_bet105_artifact(target_date: str) -> Optional[Dict[str, Any]]:
    factory = _session_factory()
    with factory() as session:
        artifact = (
            session.query(SharedReportArtifact)
            .filter(SharedReportArtifact.artifact_key == _bet105_artifact_key(target_date))
            .first()
        )
        if artifact is None or not isinstance(artifact.payload_json, dict):
            return None
        payload = dict(artifact.payload_json)
        payload.update({
            "durable_artifact_hit": True,
            "data_status": "ready",
            "last_successful_at": artifact.updated_at.isoformat() if artifact.updated_at else None,
        })
        return payload


def _persist_bet105_artifact(target_date: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    factory = _session_factory()
    with factory() as session:
        key = _bet105_artifact_key(target_date)
        artifact = (
            session.query(SharedReportArtifact)
            .filter(SharedReportArtifact.artifact_key == key)
            .first()
        )
        if artifact is None:
            artifact = SharedReportArtifact(
                artifact_key=key,
                artifact_type="bet105_board",
                target_date=dt.date.fromisoformat(target_date),
                payload_json=payload,
            )
            session.add(artifact)
        else:
            artifact.payload_json = payload
        artifact.row_count = len(payload.get("events") or [])
        artifact.generated_at = dt.datetime.utcnow()
        artifact.updated_at = dt.datetime.utcnow()
        session.commit()
    return payload


def _refresh_bet105_artifact(target_date: str) -> Dict[str, Any]:
    payload = _normalize_bet105_route_status(
        fetch_kibl_bet105_events(date=target_date, raw=False, live_only=False)
    )
    if payload.get("events"):
        return _persist_bet105_artifact(target_date, payload)
    previous = _read_bet105_artifact(target_date)
    if previous is not None:
        previous.update({
            "data_status": "stale",
            "stale": True,
            "refresh_error": payload.get("message") or "Bet105 refresh returned no events.",
        })
        return previous
    return {
        **payload,
        "data_status": "not_ready",
        "stale": False,
        "message": payload.get("message") or "Bet105 board is not ready for this date.",
    }


def _safe_float(value: Any) -> Optional[float]:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def american_to_decimal(price: Any) -> Optional[float]:
    price = _safe_float(price)
    if price is None or price == 0:
        return None
    if price > 0:
        return 1 + price / 100
    return 1 + 100 / abs(price)


def decimal_to_american(decimal: Any) -> Optional[int]:
    decimal = _safe_float(decimal)
    if decimal is None or decimal <= 1:
        return None
    if decimal >= 2:
        return round((decimal - 1) * 100)
    return round(-100 / (decimal - 1))


def implied_probability(decimal: Any) -> Optional[float]:
    decimal = _safe_float(decimal)
    if decimal is None or decimal <= 1:
        return None
    return 1 / decimal


def _team_name(event: Dict[str, Any], side: str) -> str:
    value = event.get(f"{side}_team")
    if isinstance(value, dict):
        nested = value.get("name")
        if isinstance(nested, dict):
            return str(nested.get("name") or nested.get("display_name") or nested.get("fullName") or nested.get("title") or "")
        return str(nested or "")
    return str(value or "")


def _slug(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(value or "").lower()).strip("_")


def _match_key(away: Any, home: Any) -> str:
    def clean(name: Any) -> str:
        return re.sub(r"[^a-z0-9]", "", str(name or "").lower().replace("the", "", 1))

    return f"{clean(away)}@{clean(home)}"


def _market_key(market: Dict[str, Any]) -> str:
    return str(market.get("market_key") or market.get("market_type") or market.get("market_name") or "unknown_market")


def _selection_label(selection: Dict[str, Any]) -> str:
    return str(selection.get("description") or selection.get("name") or selection.get("team") or selection.get("side") or "Selection")


def _selection_price(selection: Dict[str, Any]) -> Optional[float]:
    price = selection.get("price")
    if price is None and isinstance(selection.get("odds"), dict):
        price = selection["odds"].get("american")
    return _safe_float(price)


def _book_selection(selection: Dict[str, Any]) -> Dict[str, Any]:
    price = _selection_price(selection)
    decimal = american_to_decimal(price)
    return {
        "price": price,
        "american": price,
        "decimal": round(decimal, 4) if decimal else None,
        "implied_probability": round(implied_probability(decimal), 4) if decimal else None,
    }


def _events(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    return payload.get("events") if isinstance(payload.get("events"), list) else []


def _payload_market_count(payload: Dict[str, Any]) -> int:
    value = payload.get("market_count")
    try:
        return int(value)
    except (TypeError, ValueError):
        return sum(len(event.get("markets") or []) for event in _events(payload))


def _normalize_bet105_route_status(payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    The sportsbook page needs a hard distinction between real odds boards and
    fixture-only responses. The provider returns normalized fixtures/markets;
    enforce the route contract here so the frontend never has to infer provider
    state from missing odds.
    """
    if not isinstance(payload, dict):
        return payload
    events = _events(payload)
    market_count = _payload_market_count(payload)
    if events and market_count == 0 and payload.get("status") not in {"provider_not_configured", "provider_error"}:
        payload = dict(payload)
        payload["status"] = "fixtures_only"
        payload["market_count"] = 0
    return payload


def _index_events(payload: Dict[str, Any], book: str) -> Dict[str, Dict[str, Any]]:
    indexed: Dict[str, Dict[str, Any]] = {}
    for event in _events(payload):
        away = _team_name(event, "away")
        home = _team_name(event, "home")
        key = _match_key(away, home)
        if key == "@":
            key = str(event.get("event_id") or event.get("name") or book)
        indexed.setdefault(key, {
            "match_key": key,
            "away_team": away,
            "home_team": home,
            "start_time": event.get("start_time"),
            "sources": {},
            "markets": {},
        })
        indexed[key]["sources"][book] = {
            "event_id": event.get("event_id"),
            "status": event.get("status"),
            "market_count": event.get("market_count") or len(event.get("markets") or []),
        }
        for market in event.get("markets") or []:
            market_key = _market_key(market)
            market_bucket = indexed[key]["markets"].setdefault(market_key, {
                "market_key": market_key,
                "market_name": market.get("market_name") or market.get("market_type") or market_key,
                "selections": {},
            })
            for selection in market.get("selections") or []:
                label = _selection_label(selection)
                line = selection.get("line")
                selection_key = f"{_slug(label)}:{line if line is not None else 'none'}"
                bucket = market_bucket["selections"].setdefault(selection_key, {
                    "selection_key": selection_key,
                    "label": label,
                    "line": line,
                    "books": {},
                    "best_book": None,
                    "best_price": None,
                    "price_gap": None
                })
                bucket["books"][book] = _book_selection(selection)
    return indexed


def _comparison_payload(date: Optional[str], books: List[str], payloads: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    merged: Dict[str, Dict[str, Any]] = {}
    for book, payload in payloads.items():
        for key, event in _index_events(payload, book).items():
            target = merged.setdefault(key, {**event, "markets": {}})
            target["sources"].update(event.get("sources") or {})
            for market_key, market in (event.get("markets") or {}).items():
                market_target = target["markets"].setdefault(market_key, {
                    "market_key": market_key,
                    "market_name": market.get("market_name") or market_key,
                    "selections": {},
                })
                for selection_key, selection in (market.get("selections") or {}).items():
                    selection_target = market_target["selections"].setdefault(selection_key, {
                        "selection_key": selection_key,
                        "label": selection.get("label"),
                        "line": selection.get("line"),
                        "books": {},
                        "best_book": None,
                        "best_price": None,
                        "price_gap": None,
                    })
                    selection_target["books"].update(selection.get("books") or {})
                    prices = [book_data.get("price") for book_data in selection_target["books"].values() if book_data.get("price") is not None]
                    if prices:
                        best_book = max(selection_target["books"], key=lambda name: selection_target["books"][name].get("price") if selection_target["books"][name].get("price") is not None else -99999)
                        selection_target["best_book"] = best_book
                        selection_target["best_price"] = selection_target["books"][best_book].get("price")
                        selection_target["price_gap"] = round(max(prices) - min(prices), 2) if len(prices) > 1 else 0
    events: List[Dict[str, Any]] = []
    for event in merged.values():
        markets = []
        for market in event["markets"].values():
            selections = sorted(market["selections"].values(), key=lambda row: row.get("label") or "")
            markets.append({**market, "selections": selections})
        markets.sort(key=lambda row: row.get("market_key") or "")
        events.append({**event, "markets": markets})
    events.sort(key=lambda row: (row.get("start_time") or "", row.get("match_key") or ""))
    return {
        "date": date,
        "books": books,
        "events": events,
        "event_count": len(events),
        "provider_status": {book: payload.get("status") for book, payload in payloads.items()},
        "generated_at": dt.datetime.utcnow().isoformat(timespec="seconds") + "Z",
    }


@router.get("/odds/bet105/events")
def bet105_events(date: Optional[str] = None, live: bool = False, raw: bool = False) -> Dict[str, Any]:
    target_date = _target_date(date)
    if not live and not raw:
        artifact = _read_bet105_artifact(target_date)
        if artifact is not None:
            return artifact
        return _refresh_bet105_artifact(target_date)
    payload = fetch_kibl_bet105_events(date=date, raw=raw, live_only=live)
    return _normalize_bet105_route_status(payload)


@router.post("/odds/bet105/events/refresh")
def refresh_bet105_events(date: Optional[str] = None) -> Dict[str, Any]:
    return _refresh_bet105_artifact(_target_date(date))


@router.get("/odds/bet105/event/{event_id}/markets")
def bet105_event_markets(event_id: str, raw: bool = False) -> Dict[str, Any]:
    payload = fetch_kibl_bet105_event_odds(event_id=event_id, raw=raw, props_only=False)
    return _normalize_bet105_route_status(payload)


@router.get("/odds/bet105/event/{event_id}/props")
def bet105_event_props(event_id: str, raw: bool = False) -> Dict[str, Any]:
    payload = fetch_kibl_bet105_event_odds(event_id=event_id, raw=raw, props_only=True)
    return _normalize_bet105_route_status(payload)


@router.get("/odds/bet105/debug")
def bet105_debug(date: Optional[str] = None, live: bool = False) -> Dict[str, Any]:
    payload = fetch_kibl_bet105_events(date=date, raw=True, live_only=live)
    return _normalize_bet105_route_status(payload)


@router.get("/odds/compare/events")
def compare_odds_events(date: Optional[str] = None, books: str = "bet105,draftkings") -> Dict[str, Any]:
    requested = [book.strip().lower() for book in books.split(",") if book.strip()]
    payloads: Dict[str, Dict[str, Any]] = {}
    if "bet105" in requested:
        payloads["bet105"] = _normalize_bet105_route_status(fetch_kibl_bet105_events(date=date, raw=False))
    if "draftkings" in requested:
        with _force_default_draftkings_provider():
            payloads["draftkings"] = fetch_draftkings_events(date=date, raw=False)
    return _comparison_payload(date=date, books=list(payloads.keys()), payloads=payloads)


@router.post("/odds/price-snapshots")
def model_tracker_price_snapshot_capture(date: Optional[str] = None, provider: str = "bet105") -> Dict[str, Any]:
    target = _target_date(date)
    selected_provider = (provider or "bet105").strip().lower()
    if selected_provider != "bet105":
        raise HTTPException(status_code=400, detail="Only provider=bet105 is implemented for price snapshots in this phase")
    Session = _session_factory()
    with Session() as session:
        return capture_bet105_price_snapshots(session, target)


@router.get("/odds/price-snapshots")
def model_tracker_price_snapshot_list(date: Optional[str] = None, provider: Optional[str] = "bet105") -> Dict[str, Any]:
    target = _target_date(date)
    selected_provider = (provider or "").strip().lower() or None
    Session = _session_factory()
    with Session() as session:
        return list_price_snapshots(session, target, provider=selected_provider)


@router.post("/odds/parlay/calculate")
def calculate_parlay(payload: Dict[str, Any]) -> Dict[str, Any]:
    legs = payload.get("legs") if isinstance(payload.get("legs"), list) else []
    stake = _safe_float(payload.get("stake")) or 0.0
    decimal_odds = 1.0
    valid_legs: List[Dict[str, Any]] = []
    invalid_legs: List[Dict[str, Any]] = []
    seen_event_markets = set()
    warnings: List[str] = []
    for index, leg in enumerate(legs):
        if not isinstance(leg, dict):
            invalid_legs.append({"index": index, "reason": "leg is not an object"})
            continue
        decimal = american_to_decimal(leg.get("price"))
        if not decimal:
            invalid_legs.append({"index": index, "reason": "invalid American price", "leg": leg})
            continue
        event_market = (leg.get("event_id"), leg.get("market_key"))
        if event_market in seen_event_markets:
            warnings.append("Multiple selections from the same event and market may be correlated or invalid.")
        seen_event_markets.add(event_market)
        decimal_odds *= decimal
        valid_legs.append({**leg, "decimal": round(decimal, 4)})
    implied = implied_probability(decimal_odds) if valid_legs else None
    payout = stake * decimal_odds if valid_legs else 0.0
    return {
        "leg_count": len(valid_legs),
        "invalid_leg_count": len(invalid_legs),
        "decimal_odds": round(decimal_odds, 4) if valid_legs else None,
        "american_odds": decimal_to_american(decimal_odds) if valid_legs else None,
        "implied_probability": round(implied, 4) if implied else None,
        "stake": round(stake, 2),
        "payout": round(payout, 2),
        "profit": round(max(payout - stake, 0.0), 2),
        "valid_legs": valid_legs,
        "invalid_legs": invalid_legs,
        "warnings": warnings,
    }

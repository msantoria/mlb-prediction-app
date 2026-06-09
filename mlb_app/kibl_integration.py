"""KIBL Bet105 sportsbook feed integration.

This module handles the safe backend-only flow for Bet105 feed ingestion:
Cognito token -> KIBL baseline fixture/market pulls -> idempotent persistence ->
watermark-driven diff polling.

No live API calls run on import. Credentials are read only from environment at
runtime and are never logged by helper functions in this module.
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import json
import os
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

import requests
from sqlalchemy import Column, DateTime, Float, Index, Integer, JSON, String, Text
from sqlalchemy.orm import Session

from .database import Base

KIBL_COGNITO_REGION_DEFAULT = "us-west-2"
KIBL_COGNITO_CLIENT_ID_DEFAULT = "3udv7qsqgju8c4riqvk72bqcl"
KIBL_BASE_URL_DEFAULT = "https://api.kibl.io/sports/get"
KIBL_FEED_SOURCE_ID_DEFAULT = 171
KIBL_PREMATCH_BETTING_TYPE_ID = 1
KIBL_LIVE_BETTING_TYPE_ID = 3
KIBL_DEFAULT_LEAGUE_IDS = "20,643"
KIBL_FIXTURES_PATH = "info/fixtures"
KIBL_MARKETS_PATH = "info/markets"
KIBL_TIME_FORMAT = "%Y-%m-%d %H:%M:%S"

_SECRET_KEYS = {"password", "token", "access_token", "authorization", "secret"}


class KiblIntegrationError(RuntimeError):
    """Raised when KIBL auth, fetch, or persistence fails."""


@dataclass(frozen=True)
class KiblConfig:
    cognito_region: str
    cognito_client_id: str
    username: str
    password: str
    base_url: str
    feed_source_id: int
    default_league_ids: str
    from_cache: bool

    @classmethod
    def from_env(cls) -> "KiblConfig":
        username = os.getenv("KIBL_USERNAME", "")
        password = os.getenv("KIBL_PASSWORD", "")
        if not username or not password:
            raise KiblIntegrationError("KIBL_USERNAME and KIBL_PASSWORD must be set")
        return cls(
            cognito_region=os.getenv("KIBL_COGNITO_REGION", KIBL_COGNITO_REGION_DEFAULT),
            cognito_client_id=os.getenv("KIBL_COGNITO_CLIENT_ID", KIBL_COGNITO_CLIENT_ID_DEFAULT),
            username=username,
            password=password,
            base_url=os.getenv("KIBL_BASE_URL", KIBL_BASE_URL_DEFAULT).rstrip("/"),
            feed_source_id=int(os.getenv("KIBL_FEED_SOURCE_ID", str(KIBL_FEED_SOURCE_ID_DEFAULT))),
            default_league_ids=os.getenv("KIBL_DEFAULT_LEAGUE_IDS", KIBL_DEFAULT_LEAGUE_IDS),
            from_cache=_env_bool("KIBL_FROM_CACHE", default=False),
        )


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "y", "on"}


def redact_secrets(value: Any) -> Any:
    """Return a copy with secret-like fields redacted for safe logging."""
    if isinstance(value, Mapping):
        redacted: Dict[str, Any] = {}
        for key, item in value.items():
            key_text = str(key).lower()
            if any(secret in key_text for secret in _SECRET_KEYS):
                redacted[str(key)] = "***REDACTED***"
            else:
                redacted[str(key)] = redact_secrets(item)
        return redacted
    if isinstance(value, list):
        return [redact_secrets(item) for item in value]
    return value


def eastern_now_string() -> str:
    """Return the current timestamp in KIBL's expected US Eastern text format."""
    try:
        from zoneinfo import ZoneInfo

        now = _dt.datetime.now(ZoneInfo("America/New_York"))
    except Exception:
        now = _dt.datetime.utcnow() - _dt.timedelta(hours=5)
    return now.strftime(KIBL_TIME_FORMAT)


def newest_kibl_timestamp(rows: Iterable[Mapping[str, Any]]) -> Optional[str]:
    """Return the newest last_updated/inserted_on watermark string from rows."""
    newest: Optional[_dt.datetime] = None
    newest_raw: Optional[str] = None
    for row in rows:
        for field in ("last_updated", "inserted_on"):
            raw = row.get(field)
            if not raw:
                continue
            parsed = _parse_kibl_time(str(raw))
            if parsed is None:
                continue
            if newest is None or parsed > newest:
                newest = parsed
                newest_raw = parsed.strftime(KIBL_TIME_FORMAT)
    return newest_raw


def _parse_kibl_time(raw: str) -> Optional[_dt.datetime]:
    for fmt in (KIBL_TIME_FORMAT, "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S.%f"):
        try:
            return _dt.datetime.strptime(raw[:26], fmt)
        except ValueError:
            continue
    return None


def _stable_json_hash(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _first_present(row: Mapping[str, Any], names: Sequence[str]) -> Optional[Any]:
    for name in names:
        value = row.get(name)
        if value not in (None, ""):
            return value
    return None


def _as_int(value: Any) -> Optional[int]:
    try:
        return int(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _as_float(value: Any) -> Optional[float]:
    try:
        return float(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


def extract_rows(payload: Any) -> List[Dict[str, Any]]:
    """Extract result rows defensively across likely KIBL response wrappers."""
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)]
    if not isinstance(payload, Mapping):
        return []
    for key in ("data", "rows", "results", "items", "fixtures", "markets"):
        value = payload.get(key)
        if isinstance(value, list):
            return [row for row in value if isinstance(row, dict)]
        if isinstance(value, Mapping):
            nested = extract_rows(value)
            if nested:
                return nested
    return [dict(payload)] if payload else []


class KiblFixture(Base):
    __tablename__ = "kibl_fixtures"

    id = Column(Integer, primary_key=True, autoincrement=True)
    fixture_key = Column(String(128), nullable=False, unique=True, index=True)
    external_fixture_id = Column(String(128), nullable=True, index=True)
    feed_source_id = Column(Integer, nullable=False, index=True)
    betting_type_id = Column(Integer, nullable=False, index=True)
    league_id = Column(String(255), nullable=True, index=True)
    sport_name = Column(String(120), nullable=True)
    league_name = Column(String(255), nullable=True)
    home_team = Column(String(255), nullable=True)
    away_team = Column(String(255), nullable=True)
    start_time = Column(String(64), nullable=True)
    last_updated = Column(String(64), nullable=True, index=True)
    inserted_on = Column(String(64), nullable=True)
    raw_payload = Column(JSON, nullable=False)
    created_at = Column(DateTime, default=_dt.datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=_dt.datetime.utcnow, nullable=False)

    __table_args__ = (
        Index("ix_kibl_fixtures_feed_type_league", "feed_source_id", "betting_type_id", "league_id"),
    )


class KiblMarket(Base):
    __tablename__ = "kibl_markets"

    id = Column(Integer, primary_key=True, autoincrement=True)
    market_key = Column(String(128), nullable=False, unique=True, index=True)
    external_market_id = Column(String(128), nullable=True, index=True)
    external_fixture_id = Column(String(128), nullable=True, index=True)
    feed_source_id = Column(Integer, nullable=False, index=True)
    betting_type_id = Column(Integer, nullable=False, index=True)
    league_id = Column(String(255), nullable=True, index=True)
    market_name = Column(String(255), nullable=True)
    selection_name = Column(String(255), nullable=True)
    price = Column(Float, nullable=True)
    line = Column(Float, nullable=True)
    status = Column(String(80), nullable=True)
    last_updated = Column(String(64), nullable=True, index=True)
    inserted_on = Column(String(64), nullable=True)
    raw_payload = Column(JSON, nullable=False)
    created_at = Column(DateTime, default=_dt.datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=_dt.datetime.utcnow, nullable=False)

    __table_args__ = (
        Index("ix_kibl_markets_fixture_market", "external_fixture_id", "external_market_id"),
        Index("ix_kibl_markets_feed_type_league", "feed_source_id", "betting_type_id", "league_id"),
    )


class KiblSyncWatermark(Base):
    __tablename__ = "kibl_sync_watermarks"

    id = Column(Integer, primary_key=True, autoincrement=True)
    sync_key = Column(String(128), nullable=False, unique=True, index=True)
    endpoint_path = Column(String(120), nullable=False, index=True)
    feed_source_id = Column(Integer, nullable=False, index=True)
    betting_type_id = Column(Integer, nullable=False, index=True)
    league_id = Column(String(255), nullable=True, index=True)
    filter_hash = Column(String(64), nullable=False)
    last_watermark = Column(String(64), nullable=True)
    updated_at = Column(DateTime, default=_dt.datetime.utcnow, nullable=False)


class KiblAuthClient:
    def __init__(self, config: KiblConfig, http_session: Optional[requests.Session] = None) -> None:
        self.config = config
        self.http = http_session or requests.Session()
        self._access_token: Optional[str] = None
        self._expires_at: Optional[_dt.datetime] = None

    def get_access_token(self, force_refresh: bool = False) -> str:
        if not force_refresh and self._access_token and not self._token_expired():
            return self._access_token
        endpoint = f"https://cognito-idp.{self.config.cognito_region}.amazonaws.com/"
        body = {
            "AuthFlow": "USER_PASSWORD_AUTH",
            "ClientId": self.config.cognito_client_id,
            "AuthParameters": {
                "USERNAME": self.config.username,
                "PASSWORD": self.config.password,
            },
        }
        headers = {
            "Content-Type": "application/x-amz-json-1.1",
            "X-Amz-Target": "AWSCognitoIdentityProviderService.InitiateAuth",
        }
        resp = self.http.post(endpoint, headers=headers, json=body, timeout=30)
        if resp.status_code >= 400:
            raise KiblIntegrationError(f"Cognito auth failed: {resp.status_code} {resp.text[:240]}")
        payload = resp.json()
        auth = payload.get("AuthenticationResult") or {}
        token = auth.get("AccessToken")
        if not token:
            raise KiblIntegrationError("Cognito auth response did not include AuthenticationResult.AccessToken")
        expires_in = _as_int(auth.get("ExpiresIn")) or 3600
        self._access_token = token
        self._expires_at = _dt.datetime.utcnow() + _dt.timedelta(seconds=max(expires_in - 60, 60))
        return token

    def _token_expired(self) -> bool:
        return bool(self._expires_at and _dt.datetime.utcnow() >= self._expires_at)


class KiblApiClient:
    def __init__(self, config: KiblConfig, auth_client: KiblAuthClient, http_session: Optional[requests.Session] = None) -> None:
        self.config = config
        self.auth_client = auth_client
        self.http = http_session or requests.Session()

    def post(self, path: str, ticket: Mapping[str, Any]) -> Any:
        clean_path = path.strip("/")
        url = f"{self.config.base_url}/{clean_path}/"
        body = {key: value for key, value in ticket.items() if key not in {"request_uuid", "requested"}}
        token = self.auth_client.get_access_token()
        resp = self.http.post(
            url,
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json=body,
            timeout=30,
        )
        if resp.status_code == 401:
            token = self.auth_client.get_access_token(force_refresh=True)
            resp = self.http.post(
                url,
                headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                json=body,
                timeout=30,
            )
        if resp.status_code >= 400:
            raise KiblIntegrationError(f"KIBL {clean_path} failed: {resp.status_code} {resp.text[:240]}")
        return resp.json()

    def build_ticket(
        self,
        betting_type_id: int,
        league_id: Optional[str] = None,
        since_last_updated: Optional[str] = None,
        extra_filters: Optional[Mapping[str, Any]] = None,
    ) -> Dict[str, Any]:
        ticket: Dict[str, Any] = {
            "feed_source_id": self.config.feed_source_id,
            "betting_type_id": betting_type_id,
            "league_id": league_id or self.config.default_league_ids,
            "from_cache": self.config.from_cache,
        }
        if since_last_updated:
            ticket["since_last_updated"] = since_last_updated
        if extra_filters:
            ticket.update(extra_filters)
        ticket.pop("request_uuid", None)
        ticket.pop("requested", None)
        return ticket

    def fixtures(self, betting_type_id: int, league_id: Optional[str] = None, since_last_updated: Optional[str] = None) -> List[Dict[str, Any]]:
        return extract_rows(self.post(KIBL_FIXTURES_PATH, self.build_ticket(betting_type_id, league_id, since_last_updated)))

    def markets(self, betting_type_id: int, league_id: Optional[str] = None, since_last_updated: Optional[str] = None) -> List[Dict[str, Any]]:
        return extract_rows(self.post(KIBL_MARKETS_PATH, self.build_ticket(betting_type_id, league_id, since_last_updated)))


def filter_hash(path: str, feed_source_id: int, betting_type_id: int, league_id: Optional[str]) -> str:
    return _stable_json_hash({
        "path": path.strip("/"),
        "feed_source_id": feed_source_id,
        "betting_type_id": betting_type_id,
        "league_id": league_id or "",
    })


def sync_key(path: str, feed_source_id: int, betting_type_id: int, league_id: Optional[str]) -> str:
    return f"{path.strip('/')}:{feed_source_id}:{betting_type_id}:{filter_hash(path, feed_source_id, betting_type_id, league_id)[:16]}"


def get_watermark(session: Session, path: str, feed_source_id: int, betting_type_id: int, league_id: Optional[str]) -> Optional[str]:
    key = sync_key(path, feed_source_id, betting_type_id, league_id)
    row = session.query(KiblSyncWatermark).filter_by(sync_key=key).one_or_none()
    return row.last_watermark if row else None


def set_watermark(session: Session, path: str, feed_source_id: int, betting_type_id: int, league_id: Optional[str], watermark: str) -> None:
    key = sync_key(path, feed_source_id, betting_type_id, league_id)
    row = session.query(KiblSyncWatermark).filter_by(sync_key=key).one_or_none()
    now = _dt.datetime.utcnow()
    if row is None:
        row = KiblSyncWatermark(
            sync_key=key,
            endpoint_path=path.strip("/"),
            feed_source_id=feed_source_id,
            betting_type_id=betting_type_id,
            league_id=league_id,
            filter_hash=filter_hash(path, feed_source_id, betting_type_id, league_id),
            last_watermark=watermark,
            updated_at=now,
        )
        session.add(row)
    else:
        row.last_watermark = watermark
        row.updated_at = now


def upsert_fixtures(session: Session, rows: Sequence[Mapping[str, Any]], feed_source_id: int, betting_type_id: int, league_id: Optional[str]) -> Tuple[int, int]:
    inserted = updated = 0
    now = _dt.datetime.utcnow()
    for source in rows:
        row = dict(source)
        external_id = _first_present(row, ["fixture_id", "event_id", "game_id", "id", "fixtureId", "eventId"])
        key = str(external_id) if external_id is not None else _stable_json_hash(row)
        fixture_key = f"{feed_source_id}:{betting_type_id}:{key}"
        target = session.query(KiblFixture).filter_by(fixture_key=fixture_key).one_or_none()
        values = {
            "external_fixture_id": str(external_id) if external_id is not None else None,
            "feed_source_id": feed_source_id,
            "betting_type_id": betting_type_id,
            "league_id": str(_first_present(row, ["league_id", "leagueId"]) or league_id or ""),
            "sport_name": _first_present(row, ["sport_name", "sport", "sportName"]),
            "league_name": _first_present(row, ["league_name", "league", "leagueName"]),
            "home_team": _first_present(row, ["home_team", "homeTeam", "home_name"]),
            "away_team": _first_present(row, ["away_team", "awayTeam", "away_name"]),
            "start_time": _first_present(row, ["start_time", "startTime", "event_time", "game_time"]),
            "last_updated": _first_present(row, ["last_updated", "lastUpdated"]),
            "inserted_on": _first_present(row, ["inserted_on", "insertedOn"]),
            "raw_payload": row,
            "updated_at": now,
        }
        if target is None:
            session.add(KiblFixture(fixture_key=fixture_key, created_at=now, **values))
            inserted += 1
        else:
            for attr, value in values.items():
                setattr(target, attr, value)
            updated += 1
    return inserted, updated


def upsert_markets(session: Session, rows: Sequence[Mapping[str, Any]], feed_source_id: int, betting_type_id: int, league_id: Optional[str]) -> Tuple[int, int]:
    inserted = updated = 0
    now = _dt.datetime.utcnow()
    for source in rows:
        row = dict(source)
        market_id = _first_present(row, ["market_id", "marketId", "id"])
        fixture_id = _first_present(row, ["fixture_id", "event_id", "game_id", "fixtureId", "eventId"])
        selection_id = _first_present(row, ["selection_id", "outcome_id", "selectionId", "outcomeId"])
        key_source = {"market_id": market_id, "fixture_id": fixture_id, "selection_id": selection_id, "row": row if market_id is None else None}
        market_key = f"{feed_source_id}:{betting_type_id}:{_stable_json_hash(key_source)}"
        target = session.query(KiblMarket).filter_by(market_key=market_key).one_or_none()
        values = {
            "external_market_id": str(market_id) if market_id is not None else None,
            "external_fixture_id": str(fixture_id) if fixture_id is not None else None,
            "feed_source_id": feed_source_id,
            "betting_type_id": betting_type_id,
            "league_id": str(_first_present(row, ["league_id", "leagueId"]) or league_id or ""),
            "market_name": _first_present(row, ["market_name", "marketName", "name"]),
            "selection_name": _first_present(row, ["selection_name", "outcome_name", "selectionName", "outcomeName"]),
            "price": _as_float(_first_present(row, ["price", "odds", "american_odds", "americanOdds"])),
            "line": _as_float(_first_present(row, ["line", "handicap", "total", "points"])),
            "status": _first_present(row, ["status", "market_status", "marketStatus"]),
            "last_updated": _first_present(row, ["last_updated", "lastUpdated"]),
            "inserted_on": _first_present(row, ["inserted_on", "insertedOn"]),
            "raw_payload": row,
            "updated_at": now,
        }
        if target is None:
            session.add(KiblMarket(market_key=market_key, created_at=now, **values))
            inserted += 1
        else:
            for attr, value in values.items():
                setattr(target, attr, value)
            updated += 1
    return inserted, updated


def sync_kibl_endpoint(
    session: Session,
    client: KiblApiClient,
    path: str,
    betting_type_id: int,
    league_id: Optional[str] = None,
    baseline: bool = False,
) -> Dict[str, Any]:
    active_league_id = league_id or client.config.default_league_ids
    watermark = None if baseline else get_watermark(session, path, client.config.feed_source_id, betting_type_id, active_league_id)
    rows = client.fixtures(betting_type_id, active_league_id, watermark) if path == KIBL_FIXTURES_PATH else client.markets(betting_type_id, active_league_id, watermark)
    if path == KIBL_FIXTURES_PATH:
        inserted, updated = upsert_fixtures(session, rows, client.config.feed_source_id, betting_type_id, active_league_id)
    elif path == KIBL_MARKETS_PATH:
        inserted, updated = upsert_markets(session, rows, client.config.feed_source_id, betting_type_id, active_league_id)
    else:
        raise KiblIntegrationError(f"Unsupported KIBL path: {path}")
    new_watermark = newest_kibl_timestamp(rows)
    if new_watermark:
        set_watermark(session, path, client.config.feed_source_id, betting_type_id, active_league_id, new_watermark)
    session.commit()
    return {
        "path": path,
        "betting_type_id": betting_type_id,
        "league_id": active_league_id,
        "baseline": baseline,
        "previous_watermark": watermark,
        "new_watermark": new_watermark,
        "rows_received": len(rows),
        "rows_inserted": inserted,
        "rows_updated": updated,
    }


def build_default_client(config: Optional[KiblConfig] = None) -> KiblApiClient:
    active_config = config or KiblConfig.from_env()
    auth = KiblAuthClient(active_config)
    return KiblApiClient(active_config, auth)

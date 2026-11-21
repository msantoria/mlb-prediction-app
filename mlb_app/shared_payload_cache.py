from __future__ import annotations

import copy
from collections import OrderedDict
from threading import RLock
import sys
import hashlib
import inspect
import json
import os
import time
from typing import Any, Callable, Dict, Optional, Tuple

from .performance import estimate_payload_bytes, record_cache_status, record_span, timing_span

CacheRecord = Tuple[float, Any]
_CACHE: OrderedDict[str, CacheRecord] = OrderedDict()
_CACHE_SIZES: Dict[str, Tuple[int, Optional[int]]] = {}
_CACHE_LOCK = RLock()
# Resident Python-object estimates, not JSON size or a total process RSS limit.
_CACHE_MAX_BYTES = max(0, int(os.getenv("SHARED_PAYLOAD_CACHE_MAX_BYTES", str(128 * 1024 * 1024))))
_CACHE_MAX_ENTRIES = max(0, int(os.getenv("SHARED_PAYLOAD_CACHE_MAX_ENTRIES", "256")))
_CACHE_MAX_AGE_SECONDS = max(0, int(os.getenv("SHARED_PAYLOAD_CACHE_MAX_AGE_SECONDS", "21600")))


def _resident_bytes(value: Any, seen=None) -> int:
    seen = set() if seen is None else seen
    if id(value) in seen:
        return 0
    seen.add(id(value))
    size = sys.getsizeof(value)
    if isinstance(value, dict):
        size += sum(_resident_bytes(k, seen) + _resident_bytes(v, seen) for k, v in value.items())
    elif isinstance(value, (list, tuple, set, frozenset)):
        size += sum(_resident_bytes(v, seen) for v in value)
    return size


def _remove(key: str):
    _CACHE_SIZES.pop(key, None)
    return _CACHE.pop(key, None)


def cache_diagnostics() -> Dict[str, Any]:
    with _CACHE_LOCK:
        return {"entries": len(_CACHE), "estimated_resident_bytes": sum(v[0] for v in _CACHE_SIZES.values()),
                "max_bytes": _CACHE_MAX_BYTES, "max_entries": _CACHE_MAX_ENTRIES}


DEFAULT_TTLS = {
    "MODEL_PROJECTION_CACHE_TTL_SECONDS": 600,
    "DAILY_CONTEXT_CACHE_TTL_SECONDS": 300,
    "NEWS_CACHE_TTL_SECONDS": 300,
    "TWITTER_X_CACHE_TTL_SECONDS": 120,
    "DASHBOARD_SOLVER_CACHE_TTL_SECONDS": 300,
    "DASHBOARD_CONTEXT_CACHE_TTL_SECONDS": 300,
    "AI_DATA_ASSISTANT_RESPONSE_CACHE_TTL_SECONDS": 180,
    "MATCHUPS_CACHE_TTL_SECONDS": 300,
    "MATCHUP_DETAIL_CACHE_TTL_SECONDS": 300,
    "PITCHER_PROFILE_CACHE_TTL_SECONDS": 21600,
    "PITCHER_ARSENAL_CACHE_TTL_SECONDS": 21600,
}

LIVE_LINEUP_CACHE_MAX_SECONDS = 30


def _now() -> float:
    return time.monotonic()


def env_ttl(name: str) -> int:
    default = DEFAULT_TTLS.get(name, 300)
    try:
        return max(0, int(os.getenv(name, str(default))))
    except Exception:
        return default


def stable_hash(value: Any) -> str:
    try:
        raw = json.dumps(value or {}, sort_keys=True, default=str, separators=(",", ":"))
    except Exception:
        raw = str(value or {})
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def make_cache_key(*parts: Any) -> str:
    return ":".join(str(part) for part in parts if part is not None)


def _effective_ttl(key: str, ttl_seconds: int) -> int:
    """Use baseball-time cache semantics while confirmed lineups are forming.

    Active-lineup solver payloads must promote automatically from projected to
    partial to confirmed as MLB boxscore lineups arrive. A five-minute generic
    dashboard TTL is too stale during that window, so those payloads are polled
    at most every 30 seconds. Once rebuilt, the lineup revision travels with the
    response and the downstream report shell receives the new model state.
    """
    if "active_lineups_full_result" in str(key):
        return min(max(0, ttl_seconds), LIVE_LINEUP_CACHE_MAX_SECONDS)
    return ttl_seconds


def _explicit_matchup_snapshot_refresh(key: str) -> bool:
    """Bypass the daily matchup cache only for the explicit snapshot endpoint.

    The Railway refresh worker calls POST /matchups/snapshot/{date} after it has
    refreshed probable-pitcher and lineup inputs. That endpoint historically
    called the same cached generator used by the homepage, so a warm request
    could simply re-store the old slate. Keep normal /matchups requests fast,
    but treat the dedicated snapshot function as a force-refresh boundary.

    This is intentionally narrow: only matchup date keys are eligible and only
    while the call stack contains app.snapshot_matchups.
    """
    if not str(key).startswith("matchups:date:"):
        return False

    frame = inspect.currentframe()
    try:
        frame = frame.f_back if frame else None
        while frame is not None:
            if frame.f_code.co_name == "snapshot_matchups":
                return True
            frame = frame.f_back
    finally:
        del frame
    return False


def get_cache(key: str, ttl_seconds: int) -> Optional[Any]:
    with _CACHE_LOCK:
        return _get_cache_locked(key, ttl_seconds)


def _get_cache_locked(key: str, ttl_seconds: int) -> Optional[Any]:
    ttl_seconds = min(_effective_ttl(key, ttl_seconds), _CACHE_MAX_AGE_SECONDS)
    with timing_span(
        "shared_payload_cache.get_cache",
        category="cache",
        cache_status=None,
        extra={"cache_key_prefix": str(key).split(":", 1)[0], "ttl_seconds": ttl_seconds},
    ):
        if _explicit_matchup_snapshot_refresh(key):
            previous = _remove(key)
            record_cache_status("MISS")
            record_span(
                "shared_payload_cache.lookup",
                category="cache",
                cache_status="BYPASS",
                payload_bytes=estimate_payload_bytes(previous[1]) if previous else None,
                extra={
                    "cache_key_prefix": str(key).split(":", 1)[0],
                    "ttl_seconds": ttl_seconds,
                    "refresh_boundary": "snapshot_matchups",
                },
            )
            return None

        record = _CACHE.get(key)
        if not record:
            record_cache_status("MISS")
            record_span("shared_payload_cache.lookup", category="cache", cache_status="MISS", extra={"cache_key_prefix": str(key).split(":", 1)[0], "ttl_seconds": ttl_seconds})
            return None
        created_at, value = record
        if ttl_seconds <= 0 or _now() - created_at > ttl_seconds:
            _remove(key)
            record_cache_status("MISS")
            record_span("shared_payload_cache.lookup", category="cache", cache_status="EXPIRED", payload_bytes=estimate_payload_bytes(value), extra={"cache_key_prefix": str(key).split(":", 1)[0], "ttl_seconds": ttl_seconds})
            return None
        record_cache_status("HIT")
        payload_bytes = _CACHE_SIZES.get(key, (0, None))[1]
        _CACHE.move_to_end(key)
        with timing_span("shared_payload_cache.deepcopy.get", category="cache", cache_status="HIT", extra={"cache_key_prefix": str(key).split(":", 1)[0], "payload_bytes": payload_bytes}):
            copied = copy.deepcopy(value)
        record_span("shared_payload_cache.lookup", category="cache", cache_status="HIT", payload_bytes=payload_bytes, extra={"cache_key_prefix": str(key).split(":", 1)[0], "ttl_seconds": ttl_seconds})
        return copied


def set_cache(key: str, value: Any) -> Any:
    # Measure once on insertion, never JSON-serialize the cached object on a hit.
    resident_bytes = _resident_bytes(value)
    payload_bytes = estimate_payload_bytes(value)
    with _CACHE_LOCK:
        now = _now()
        for old_key, (created_at, _) in list(_CACHE.items()):
            if now - created_at > _CACHE_MAX_AGE_SECONDS:
                _remove(old_key)
        _remove(key)
        if (_CACHE_MAX_ENTRIES > 0 and _CACHE_MAX_AGE_SECONDS > 0
                and resident_bytes <= _CACHE_MAX_BYTES):
            while _CACHE and (len(_CACHE) >= _CACHE_MAX_ENTRIES or
                    sum(size[0] for size in _CACHE_SIZES.values()) + resident_bytes > _CACHE_MAX_BYTES):
                _remove(next(iter(_CACHE)))
            with timing_span("shared_payload_cache.deepcopy.set_store", category="cache"):
                _CACHE[key] = (now, copy.deepcopy(value))
            _CACHE_SIZES[key] = (resident_bytes, payload_bytes)
            status = "STORE"
        else:
            status = "BYPASS"
    # Preserve caller isolation even when an oversized value is not retained.
    with timing_span("shared_payload_cache.deepcopy.set_return", category="cache"):
        returned = copy.deepcopy(value)
    record_span("shared_payload_cache.set_cache", category="cache", cache_status=status,
                payload_bytes=payload_bytes, extra={"cache_key_prefix": str(key).split(":", 1)[0]})
    return returned


def get_or_set(key: str, ttl_seconds: int, builder: Callable[[], Any]) -> Any:
    effective_ttl = _effective_ttl(key, ttl_seconds)
    cached = get_cache(key, effective_ttl)
    if cached is not None:
        if isinstance(cached, dict):
            cached["cache_hit"] = True
            cached.setdefault("cache_key", key)
            cached.setdefault("ttl_seconds", effective_ttl)
        return cached
    started_at = _now()
    with timing_span("shared_payload_cache.builder", category="cache", cache_status="MISS", extra={"cache_key_prefix": str(key).split(":", 1)[0], "ttl_seconds": effective_ttl}):
        value = builder()
    built_ms = int(round((_now() - started_at) * 1000))
    stored = set_cache(key, value)
    if isinstance(stored, dict):
        stored.setdefault("cache_hit", False)
        stored.setdefault("cache_key", key)
        stored.setdefault("ttl_seconds", effective_ttl)
        stored.setdefault("built_ms", built_ms)
    return stored


def clear_shared_payload_cache(prefix: Optional[str] = None) -> Dict[str, Any]:
    with _CACHE_LOCK:
        keys = [key for key in _CACHE if not prefix or key.startswith(prefix)]
        for key in keys:
            _remove(key)
        result = {"cleared": True, "entries": len(keys)}
        if prefix:
            result["prefix"] = prefix
        return result

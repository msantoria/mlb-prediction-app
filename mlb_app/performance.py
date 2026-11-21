from __future__ import annotations

import contextlib
import contextvars
import json
import math
import time
from collections import defaultdict, deque
from typing import Any, Deque, Dict, Iterable, Iterator, List, Optional

try:
    import fastapi as _fastapi
except Exception:  # pragma: no cover - FastAPI may be absent in narrow unit tests.
    _fastapi = None


_MAX_SAMPLES = 1000
_MAX_SPANS = 5000
_SAMPLES: Deque[Dict[str, Any]] = deque(maxlen=_MAX_SAMPLES)
_SPANS: Deque[Dict[str, Any]] = deque(maxlen=_MAX_SPANS)
_CACHE_STATUS: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar(
    "mlb_cache_status",
    default=None,
)
_PROBABILITY_SOURCE: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar(
    "mlb_probability_source",
    default=None,
)
_REQUEST_ROUTE: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar(
    "mlb_request_route",
    default=None,
)
_PATCHED = False
_ORIGINAL_FASTAPI = None


def record_cache_status(status: Optional[str]) -> None:
    """Record cache status for the current request context."""
    if status:
        _CACHE_STATUS.set(str(status).upper())


def record_probability_source(source: Optional[str]) -> None:
    """Record probability source metadata for the current request context."""
    if source:
        _PROBABILITY_SOURCE.set(str(source))


def _percentile(values: List[float], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = int(math.ceil((percentile / 100.0) * len(ordered))) - 1
    index = min(max(index, 0), len(ordered) - 1)
    return round(ordered[index], 3)


def _route_label(request: Any) -> str:
    route = request.scope.get("route") if getattr(request, "scope", None) else None
    route_path = getattr(route, "path", None)
    return route_path or getattr(getattr(request, "url", None), "path", None) or "unknown"


def estimate_payload_bytes(value: Any) -> Optional[int]:
    """Best-effort JSON payload byte estimate without logging payload contents."""
    if value is None:
        return None
    try:
        return len(json.dumps(value, default=str, separators=(",", ":")).encode("utf-8"))
    except Exception:
        try:
            return len(str(value).encode("utf-8"))
        except Exception:
            return None


def _response_size_bytes(response: Any) -> Optional[int]:
    try:
        content_length = response.headers.get("content-length")
        return int(content_length) if content_length is not None else None
    except Exception:
        return None


def record_request_sample(sample: Dict[str, Any]) -> None:
    _SAMPLES.append(sample)


def record_span(
    name: str,
    *,
    category: str = "custom",
    route: Optional[str] = None,
    game_pk: Optional[Any] = None,
    date: Optional[Any] = None,
    duration_ms: Optional[float] = None,
    cache_status: Optional[str] = None,
    probability_source: Optional[str] = None,
    payload_bytes: Optional[int] = None,
    extra: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Record a bounded, non-sensitive performance span."""
    span: Dict[str, Any] = {
        "name": str(name),
        "category": str(category or "custom"),
        "route": route or _REQUEST_ROUTE.get() or "unknown",
        "game_pk": game_pk,
        "date": str(date) if date is not None else None,
        "duration_ms": round(float(duration_ms or 0.0), 3),
        "cache_status": cache_status or _CACHE_STATUS.get(),
        "probability_source": probability_source or _PROBABILITY_SOURCE.get(),
        "payload_bytes": payload_bytes,
    }
    if extra:
        safe_extra: Dict[str, Any] = {}
        for key, value in extra.items():
            if key.lower() in {"token", "authorization", "cookie", "password", "secret"}:
                continue
            if isinstance(value, (str, int, float, bool)) or value is None:
                safe_extra[key] = value
            else:
                safe_extra[key] = str(value)[:300]
        if safe_extra:
            span["extra"] = safe_extra
    _SPANS.append(span)
    return span


@contextlib.contextmanager
def timing_span(
    name: str,
    *,
    category: str = "custom",
    route: Optional[str] = None,
    game_pk: Optional[Any] = None,
    date: Optional[Any] = None,
    cache_status: Optional[str] = None,
    probability_source: Optional[str] = None,
    payload_bytes: Optional[int] = None,
    extra: Optional[Dict[str, Any]] = None,
) -> Iterator[None]:
    """Context manager for recording formula/build/cache/simulation timings."""
    started = time.perf_counter()
    try:
        yield
    finally:
        record_span(
            name,
            category=category,
            route=route,
            game_pk=game_pk,
            date=date,
            duration_ms=(time.perf_counter() - started) * 1000,
            cache_status=cache_status,
            probability_source=probability_source,
            payload_bytes=payload_bytes,
            extra=extra,
        )


def _group_counts(rows: Iterable[Dict[str, Any]], field: str, default: str = "NONE") -> Dict[str, int]:
    counts: Dict[str, int] = defaultdict(int)
    for row in rows:
        counts[str(row.get(field) or default)] += 1
    return dict(counts)


def _span_summary(spans: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    grouped: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for span in spans:
        grouped[str(span.get("name") or "unknown")].append(span)

    summary: Dict[str, Dict[str, Any]] = {}
    for name, rows in grouped.items():
        durations = [float(row.get("duration_ms") or 0) for row in rows]
        payloads = [float(row.get("payload_bytes") or 0) for row in rows if row.get("payload_bytes") is not None]
        categories = _group_counts(rows, "category", "custom")
        probability_sources = _group_counts(rows, "probability_source", "NONE")
        summary[name] = {
            "count": len(rows),
            "category_counts": categories,
            "total_ms": round(sum(durations), 3),
            "p50_ms": _percentile(durations, 50),
            "p95_ms": _percentile(durations, 95),
            "max_ms": round(max(durations), 3) if durations else 0.0,
            "payload_bytes_p95": _percentile(payloads, 95) if payloads else 0.0,
            "probability_sources": probability_sources,
        }
    return summary


def performance_snapshot() -> Dict[str, Any]:
    """Return bounded, non-sensitive route timing diagnostics."""
    samples = list(_SAMPLES)
    spans = list(_SPANS)
    grouped: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for sample in samples:
        grouped[str(sample.get("route") or sample.get("path") or "unknown")].append(sample)

    routes: Dict[str, Dict[str, Any]] = {}
    for route, rows in grouped.items():
        durations = [float(row.get("duration_ms") or 0) for row in rows]
        payloads = [float(row.get("response_size_bytes") or 0) for row in rows if row.get("response_size_bytes") is not None]
        routes[route] = {
            "count": len(rows),
            "p50_ms": _percentile(durations, 50),
            "p95_ms": _percentile(durations, 95),
            "max_ms": round(max(durations), 3) if durations else 0.0,
            "payload_bytes_p50": _percentile(payloads, 50) if payloads else 0.0,
            "payload_bytes_p95": _percentile(payloads, 95) if payloads else 0.0,
            "payload_bytes_max": round(max(payloads), 3) if payloads else 0.0,
            "cache": _group_counts(rows, "cache_status"),
            "probability_sources": _group_counts(rows, "probability_source"),
        }

    slow_requests = sorted(
        samples,
        key=lambda row: float(row.get("duration_ms") or 0),
        reverse=True,
    )[:20]
    largest_responses = sorted(
        [sample for sample in samples if sample.get("response_size_bytes") is not None],
        key=lambda row: int(row.get("response_size_bytes") or 0),
        reverse=True,
    )[:20]
    span_summary = _span_summary(spans)
    top_spans_by_total = sorted(
        span_summary.items(),
        key=lambda item: float(item[1].get("total_ms") or 0),
        reverse=True,
    )[:25]
    top_spans_by_max = sorted(
        span_summary.items(),
        key=lambda item: float(item[1].get("max_ms") or 0),
        reverse=True,
    )[:25]
    slow_spans = sorted(
        spans,
        key=lambda row: float(row.get("duration_ms") or 0),
        reverse=True,
    )[:50]
    slow_simulations = [span for span in slow_spans if span.get("category") == "simulation"][:20]
    from .shared_payload_cache import cache_diagnostics

    return {
        "status": "ok",
        "shared_payload_cache": cache_diagnostics(),
        "sample_count": len(samples),
        "sample_limit": _MAX_SAMPLES,
        "span_count": len(spans),
        "span_limit": _MAX_SPANS,
        "routes": routes,
        "slow_requests": slow_requests,
        "largest_responses": largest_responses,
        "spans": {
            "top_by_total_ms": [{"name": name, **data} for name, data in top_spans_by_total],
            "top_by_max_ms": [{"name": name, **data} for name, data in top_spans_by_max],
            "slowest": slow_spans,
            "slowest_simulations": slow_simulations,
        },
    }


def install_fastapi_performance_patch() -> bool:
    """Patch fastapi.FastAPI so app.py gets timing middleware without a large app.py rewrite.

    This is intentionally small and reversible. It only adds response timing
    headers, bounded in-process samples, and /debug/performance. It does not
    inspect request bodies or headers.
    """
    global _PATCHED, _ORIGINAL_FASTAPI
    if _PATCHED or _fastapi is None:
        return _PATCHED

    original_fastapi = _fastapi.FastAPI
    _ORIGINAL_FASTAPI = original_fastapi

    class InstrumentedFastAPI(original_fastapi):  # type: ignore[misc, valid-type]
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            super().__init__(*args, **kwargs)

            @self.middleware("http")
            async def _performance_middleware(request: Any, call_next: Any) -> Any:
                cache_token = _CACHE_STATUS.set(None)
                probability_token = _PROBABILITY_SOURCE.set(None)
                route_token = _REQUEST_ROUTE.set(_route_label(request))
                started = time.perf_counter()
                status_code = 500
                response = None
                try:
                    response = await call_next(request)
                    status_code = getattr(response, "status_code", 500)
                    return response
                finally:
                    duration_ms = round((time.perf_counter() - started) * 1000, 3)
                    cache_status = _CACHE_STATUS.get()
                    probability_source = _PROBABILITY_SOURCE.get()
                    route = _route_label(request)
                    response_size = _response_size_bytes(response)
                    sample = {
                        "method": getattr(request, "method", None),
                        "path": getattr(getattr(request, "url", None), "path", None),
                        "route": route,
                        "status_code": status_code,
                        "duration_ms": duration_ms,
                        "response_size_bytes": response_size,
                        "cache_status": cache_status,
                        "probability_source": probability_source,
                    }
                    record_request_sample(sample)
                    if response is not None:
                        response.headers["X-Response-Time-ms"] = str(duration_ms)
                        if response_size is not None:
                            response.headers["X-Payload-Bytes"] = str(response_size)
                        if cache_status:
                            response.headers["X-Cache"] = cache_status
                        if probability_source:
                            response.headers["X-Probability-Source"] = probability_source
                    _REQUEST_ROUTE.reset(route_token)
                    _PROBABILITY_SOURCE.reset(probability_token)
                    _CACHE_STATUS.reset(cache_token)

            async def _debug_performance() -> Dict[str, Any]:
                return performance_snapshot()

            self.add_api_route(
                "/debug/performance",
                _debug_performance,
                methods=["GET"],
                include_in_schema=False,
            )
            self.add_api_route(
                "/debug/performance/hotspots",
                _debug_performance,
                methods=["GET"],
                include_in_schema=False,
            )

    _fastapi.FastAPI = InstrumentedFastAPI
    _PATCHED = True
    return True


__all__ = [
    "estimate_payload_bytes",
    "install_fastapi_performance_patch",
    "performance_snapshot",
    "record_cache_status",
    "record_probability_source",
    "record_request_sample",
    "record_span",
    "timing_span",
]

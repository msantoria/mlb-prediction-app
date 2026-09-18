#!/usr/bin/env python3
"""Smoke-test production-critical backend paths."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Callable

DEFAULT_BACKEND_BASE_URL = "https://mlb-prediction-app-production-732c.up.railway.app"


class SmokeFailure(Exception):
    pass


def _today_eastern_iso() -> str:
    return dt.datetime.utcnow().date().isoformat()


def _request_json(base_url: str, path: str, timeout: int = 45, method: str = "GET") -> tuple[int, Any]:
    request = urllib.request.Request(url=f"{base_url.rstrip('/')}{path}", method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            status = int(response.status)
            body = response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace") if exc.fp else ""
        raise SmokeFailure(f"HTTP {exc.code} for {method} {path}: {detail[:500]}") from exc
    except urllib.error.URLError as exc:
        raise SmokeFailure(f"Network error for {method} {path}: {exc}") from exc
    try:
        return status, json.loads(body) if body else None
    except json.JSONDecodeError as exc:
        raise SmokeFailure(f"Invalid JSON for {method} {path}: {body[:500]}") from exc


def _expect_dict(data: Any, path: str) -> dict[str, Any]:
    if not isinstance(data, dict):
        raise SmokeFailure(f"Expected object for {path}, got {type(data).__name__}")
    return data


def _check_health(data: Any, path: str) -> None:
    if not _expect_dict(data, path):
        raise SmokeFailure(f"Empty health payload for {path}")


def _check_matchups(data: Any, path: str) -> None:
    if not isinstance(data, list):
        raise SmokeFailure(f"Expected matchup list for {path}, got {type(data).__name__}")


def _check_daily_odds_fast(data: Any, path: str) -> None:
    payload = _expect_dict(data, path)
    for key in ["date", "errors"]:
        if key not in payload:
            raise SmokeFailure(f"Daily Odds fast payload missing {key}")
    if not any(key in payload for key in ["models", "games", "model_games"]):
        raise SmokeFailure("Daily Odds fast payload missing models/games/model_games container")
    if payload.get("unified_loaded") is not False:
        raise SmokeFailure("Daily Odds fast payload should not load unified sections by default")


def _check_daily_odds_unified(data: Any, path: str) -> None:
    payload = _expect_dict(data, path)
    for key in ["daily_recap", "model_projection_summary", "dashboard_solver_summary", "data_quality", "sources_used", "missing_inputs", "fallbacks_used"]:
        if key not in payload:
            raise SmokeFailure(f"Daily Odds unified payload missing {key}")
    if payload.get("unified_loaded") is not True:
        raise SmokeFailure("Daily Odds unified payload should set unified_loaded=true")


def _check_model_projections(data: Any, path: str) -> None:
    payload = _expect_dict(data, path)
    if not any(key in payload for key in ["games", "models", "count"]):
        raise SmokeFailure("Model Projections payload missing games/models/count")


def _check_dashboard_solver(data: Any, path: str) -> None:
    payload = _expect_dict(data, path)
    for key in ["items", "component", "date"]:
        if key not in payload:
            raise SmokeFailure(f"My Dashboard solver payload missing {key}")
    if not isinstance(payload.get("items"), list):
        raise SmokeFailure("My Dashboard solver items must be a list")


def _check_predicts(data: Any, path: str) -> None:
    payload = _expect_dict(data, path)
    if not isinstance(payload.get("records"), list):
        raise SmokeFailure("Predicts records must be a list")
    if payload.get("status") not in {"ready", "unavailable"}:
        raise SmokeFailure("Unexpected Predicts status")
    if not payload["records"]:
        print("WARN predicts: no saved pregame predictions for this date")


def _run_check(base_url: str, label: str, path: str, validator: Callable[[Any, str], None], method: str = "GET") -> bool:
    try:
        status, data = _request_json(base_url, path, method=method)
        validator(data, path)
        print(f"PASS {label}: HTTP {status} {method} {path}")
        return True
    except SmokeFailure as exc:
        print(f"FAIL {label}: {exc}")
        return False


def main() -> int:
    parser = argparse.ArgumentParser(description="Smoke-test production-critical MLB backend paths.")
    parser.add_argument("--base-url", default=os.getenv("BACKEND_BASE_URL", DEFAULT_BACKEND_BASE_URL))
    parser.add_argument("--date", default=os.getenv("SMOKE_TEST_DATE", _today_eastern_iso()))
    args = parser.parse_args()
    date = args.date[:10]
    query_date = urllib.parse.urlencode({"date": date})
    unified_query = urllib.parse.urlencode({"date": date, "include_unified": "true"})
    dashboard_hitter_query = urllib.parse.urlencode({"date": date, "component": "hitters"})
    dashboard_pitcher_query = urllib.parse.urlencode({"date": date, "component": "pitchers"})
    checks: list[tuple[str, str, Callable[[Any, str], None], str]] = [
        ("health", "/health", _check_health, "GET"),
        ("matchups", f"/matchups?{query_date}", _check_matchups, "GET"),
        ("daily_odds_models_fast", f"/daily-odds/models?{query_date}", _check_daily_odds_fast, "GET"),
        ("daily_odds_models_unified", f"/daily-odds/models?{unified_query}", _check_daily_odds_unified, "GET"),
        ("model_projections", f"/models/projections?{query_date}", _check_model_projections, "GET"),
        ("ai_data_assistant_health", "/ai-data-assistant/health", _check_health, "GET"),
        ("my_dashboard_health", "/my-dashboard/health", _check_health, "GET"),
        ("my_dashboard_solver_hitters", f"/my-dashboard/solver?{dashboard_hitter_query}", _check_dashboard_solver, "GET"),
        ("my_dashboard_solver_pitchers", f"/my-dashboard/solver?{dashboard_pitcher_query}", _check_dashboard_solver, "GET"),
        ("predicts", f"/predicts?{query_date}", _check_predicts, "GET"),
    ]
    print(f"Backend base URL: {args.base_url.rstrip('/')}")
    print(f"Smoke-test date: {date}")
    passed = 0
    for label, path, validator, method in checks:
        if _run_check(args.base_url, label, path, validator, method=method):
            passed += 1
    failed = len(checks) - passed
    print(f"Summary: {passed} passed, {failed} failed")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())

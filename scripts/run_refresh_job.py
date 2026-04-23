#!/usr/bin/env python3
"""Railway cron entrypoint for incremental refreshes across production and sandbox.

This script is designed for a separate Railway cron/worker service and should
never start the web server.

Behavior:
- verifies the app imports cleanly
- refreshes live matchup payloads for today and tomorrow
- warms matchup snapshots for today and tomorrow
- does this for both production and sandbox targets
- exits non-zero if any configured target fails
"""

from __future__ import annotations

import datetime as dt
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

REQUEST_TIMEOUT_SECONDS = int(os.environ.get("REFRESH_TIMEOUT_SECONDS", "60"))
WARM_SNAPSHOTS = os.environ.get("WARM_MATCHUP_SNAPSHOTS", "1") == "1"
REFRESH_MATCHUPS_FIRST = os.environ.get("REFRESH_MATCHUPS_FIRST", "1") == "1"


def _log(message: str) -> None:
    timestamp = dt.datetime.utcnow().isoformat(timespec="seconds") + "Z"
    print(f"[{timestamp}] {message}", flush=True)


def _request_json(url: str, method: str = "GET") -> dict | list | str | None:
    request = urllib.request.Request(url=url, method=method)
    with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
        body = response.read().decode("utf-8", errors="replace")
        if not body:
            return None
        try:
            return json.loads(body)
        except json.JSONDecodeError:
            return body


def _refresh_matchups_for_date(label: str, base_url: str, target_date: dt.date) -> None:
    query = urllib.parse.urlencode({"date": target_date.isoformat()})
    url = f"{base_url}/matchups?{query}"
    _log(f"[{label}] Refreshing live matchup payload for {target_date.isoformat()} via {url}")
    result = _request_json(url, method="GET")
    if isinstance(result, list):
        projected_counts = {
            "home": sum(
                1
                for game in result
                if isinstance(game, dict) and game.get("home_lineup_source") == "projected"
            ),
            "away": sum(
                1
                for game in result
                if isinstance(game, dict) and game.get("away_lineup_source") == "projected"
            ),
        }
        _log(
            f"[{label}] Live matchup refresh result for {target_date.isoformat()}: "
            f"{len(result)} games, projected counts={projected_counts}"
        )
    else:
        _log(f"[{label}] Live matchup refresh response for {target_date.isoformat()}: {result}")


def _warm_snapshot_for_date(label: str, base_url: str, target_date: dt.date) -> None:
    url = f"{base_url}/matchups/snapshot/{target_date.isoformat()}"
    _log(f"[{label}] Warming matchup snapshot for {target_date.isoformat()} via {url}")
    result = _request_json(url, method="POST")
    _log(f"[{label}] Snapshot response for {target_date.isoformat()}: {result}")


def _load_targets() -> list[tuple[str, str]]:
    targets: list[tuple[str, str]] = []

    production_url = os.environ.get("PRODUCTION_REFRESH_BASE_URL", "").strip().rstrip("/")
    sandbox_url = os.environ.get("SANDBOX_REFRESH_BASE_URL", "").strip().rstrip("/")

    if production_url:
        targets.append(("production", production_url))
    if sandbox_url:
        targets.append(("sandbox", sandbox_url))

    if not targets:
        legacy_url = os.environ.get("REFRESH_BASE_URL", "").strip().rstrip("/")
        if legacy_url:
            targets.append(("legacy", legacy_url))

    if not targets:
        raise RuntimeError(
            "No refresh targets configured. Set PRODUCTION_REFRESH_BASE_URL and "
            "SANDBOX_REFRESH_BASE_URL in the Railway cron service."
        )

    return targets


def _run_target(label: str, base_url: str) -> None:
    today = dt.date.today()
    tomorrow = today + dt.timedelta(days=1)

    for target_date in (today, tomorrow):
        if REFRESH_MATCHUPS_FIRST:
            _refresh_matchups_for_date(label, base_url, target_date)

        if WARM_SNAPSHOTS:
            _warm_snapshot_for_date(label, base_url, target_date)


def main() -> int:
    _log("Starting Railway refresh job")

    try:
        import mlb_app.app  # noqa: F401
    except Exception as exc:
        _log(f"Failed to import app module: {exc}")
        return 1

    try:
        targets = _load_targets()
    except Exception as exc:
        _log(str(exc))
        return 1

    failures: list[str] = []

    for label, base_url in targets:
        _log(f"[{label}] Starting target refresh against {base_url}")
        try:
            _run_target(label, base_url)
            _log(f"[{label}] Target refresh completed successfully")
        except urllib.error.HTTPError as exc:
            message = f"[{label}] HTTP error: {exc.code} {exc.reason}"
            _log(message)
            failures.append(message)
        except urllib.error.URLError as exc:
            message = f"[{label}] Network error: {exc}"
            _log(message)
            failures.append(message)
        except Exception as exc:
            message = f"[{label}] Unexpected error: {exc}"
            _log(message)
            failures.append(message)

    if failures:
        _log("Refresh job completed with failures:")
        for failure in failures:
            _log(f" - {failure}")
        return 1

    _log("Refresh job completed successfully")
    return 0


if __name__ == "__main__":
    sys.exit(main())

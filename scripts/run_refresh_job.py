#!/usr/bin/env python3
"""Safe Railway cron entrypoint for incremental refreshes.

This script is intentionally conservative. It is designed for a separate
Railway cron/worker service and should never start the web server.

Current behavior:
- verifies the app imports cleanly
- fetches current matchup payloads for today and tomorrow so live lineup paths run
- warms matchup snapshots for today and tomorrow after lineup-aware refreshes
- exits cleanly

The implementation avoids destructive writes and should be extended only with
incremental, non-clobbering refresh steps.
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

DEFAULT_BASE_URL = os.environ.get("REFRESH_BASE_URL", "http://127.0.0.1:8000")
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


def _refresh_matchups_for_date(base_url: str, target_date: dt.date) -> None:
    query = urllib.parse.urlencode({"date": target_date.isoformat()})
    url = f"{base_url}/matchups?{query}"
    _log(f"Refreshing live matchup payload for {target_date.isoformat()} via {url}")
    result = _request_json(url, method="GET")
    if isinstance(result, list):
        projected_counts = {
            "home": sum(1 for game in result if game.get("home_lineup_source") == "projected"),
            "away": sum(1 for game in result if game.get("away_lineup_source") == "projected"),
        }
        _log(
            "Live matchup refresh result for "
            f"{target_date.isoformat()}: {len(result)} games, projected counts={projected_counts}"
        )
    else:
        _log(f"Live matchup refresh response for {target_date.isoformat()}: {result}")


def _warm_snapshot_for_date(base_url: str, target_date: dt.date) -> None:
    url = f"{base_url}/matchups/snapshot/{target_date.isoformat()}"
    _log(f"Warming matchup snapshot for {target_date.isoformat()} via {url}")
    result = _request_json(url, method="POST")
    _log(f"Snapshot response for {target_date.isoformat()}: {result}")


def main() -> int:
    _log("Starting Railway refresh job")

    try:
        import mlb_app.app  # noqa: F401
    except Exception as exc:  # pragma: no cover
        _log(f"Failed to import app module: {exc}")
        return 1

    base_url = DEFAULT_BASE_URL.rstrip("/")
    today = dt.date.today()
    tomorrow = today + dt.timedelta(days=1)

    for target_date in (today, tomorrow):
        if REFRESH_MATCHUPS_FIRST:
            try:
                _refresh_matchups_for_date(base_url, target_date)
            except urllib.error.HTTPError as exc:
                _log(f"HTTP error while refreshing {target_date.isoformat()}: {exc.code} {exc.reason}")
                return 1
            except urllib.error.URLError as exc:
                _log(f"Network error while refreshing {target_date.isoformat()}: {exc}")
                return 1
            except Exception as exc:  # pragma: no cover
                _log(f"Unexpected error while refreshing {target_date.isoformat()}: {exc}")
                return 1

        if not WARM_SNAPSHOTS:
            continue

        try:
            _warm_snapshot_for_date(base_url, target_date)
        except urllib.error.HTTPError as exc:
            _log(f"HTTP error while warming {target_date.isoformat()}: {exc.code} {exc.reason}")
            return 1
        except urllib.error.URLError as exc:
            _log(f"Network error while warming {target_date.isoformat()}: {exc}")
            return 1
        except Exception as exc:  # pragma: no cover
            _log(f"Unexpected error while warming {target_date.isoformat()}: {exc}")
            return 1

    _log("Refresh job completed successfully")
    return 0


if __name__ == "__main__":
    sys.exit(main())

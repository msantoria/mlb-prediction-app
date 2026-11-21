from __future__ import annotations

import argparse
import datetime
import json
import os
import sys
from zoneinfo import ZoneInfo
import urllib.error
import urllib.request
from typing import Any, Dict, List


def _request(method: str, url: str, timeout: int) -> Dict[str, Any]:
    request = urllib.request.Request(url=url, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8")
            return json.loads(raw) if raw else {"status": response.status}
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        return {"error": f"HTTP {exc.code}", "url": url, "body": body[:500]}
    except Exception as exc:
        return {"error": exc.__class__.__name__, "url": url, "message": str(exc)}


def _dates(today: datetime.date) -> Dict[str, str]:
    return {
        "yesterday": (today - datetime.timedelta(days=1)).isoformat(),
        "today": today.isoformat(),
        "tomorrow": (today + datetime.timedelta(days=1)).isoformat(),
    }


def warm(base_url: str, timeout: int = 60) -> Dict[str, Any]:
    today = datetime.datetime.now(ZoneInfo("America/New_York")).date()
    dates = _dates(today)
    base = base_url.rstrip("/")
    actions: List[Dict[str, Any]] = []

    # 1. Warm the lightweight schedule/calendar layer first.
    # This should be the fastest user-visible path and must not force full matchup generation.
    actions.append({
        "name": "calendar_schedule_snapshot",
        "method": "POST",
        "url": f"{base}/matchups/calendar/snapshot",
    })
    actions.append({
        "name": "calendar_schedule_read",
        "method": "GET",
        "url": f"{base}/matchups/calendar/schedule",
    })

    # 2. Explicitly warm heavyweight matchups and projections outside the user path.
    # User-facing pages should reuse these artifacts instead of cold-building on click.
    for label in ("today", "tomorrow"):
        date_value = dates[label]
        actions.append({
            "name": f"bet105_board_snapshot_{label}",
            "method": "POST",
            "url": f"{base}/odds/bet105/events/refresh?date={date_value}",
        })
        actions.append({
            "name": f"model_projection_snapshot_{label}",
            "method": "POST",
            "url": f"{base}/models/projections/snapshot/{date_value}",
        })
        actions.append({
            "name": f"matchups_snapshot_{label}",
            "method": "POST",
            "url": f"{base}/matchups/snapshot/{date_value}",
        })

    results = []
    projection_busy = False
    for action in actions:
        is_projection = action["name"].startswith("model_projection_snapshot")
        if is_projection and projection_busy:
            result = {"error": "deferred", "message": "Earlier projection build may still be running"}
        else:
            result = _request(action["method"], action["url"], timeout)
        if is_projection and result.get("error"):
            # HTTP timeout does not cancel synchronous work on the API. Do not
            # launch another slate build into the same overloaded process.
            projection_busy = True
        results.append({"action": action["name"], "url": action["url"], "result": result})

    return {
        "status": "failed" if any(row["result"].get("error") for row in results) else "ok",
        "base_url": base,
        "dates": dates,
        "results": results,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Warm MLBGPT game-day schedule, matchup, and projection caches.")
    parser.add_argument("--base-url", default=os.getenv("MLBGPT_BASE_URL", "http://127.0.0.1:8000"))
    parser.add_argument("--timeout", type=int, default=int(os.getenv("MLBGPT_WARM_TIMEOUT_SECONDS", "60")))
    args = parser.parse_args()
    result = warm(args.base_url, timeout=args.timeout)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["status"] == "ok" else 1


if __name__ == "__main__":
    sys.exit(main())

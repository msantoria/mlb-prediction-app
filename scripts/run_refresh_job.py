#!/usr/bin/env python3
"""Railway cron entrypoint for matchup refreshes.

This worker intentionally separates the fast, user-facing matchup refresh path
from heavy Statcast repair/backfill work.

Default fast mode:
- verifies the app imports cleanly
- runs the hittingMatchups refresh so batter_pitch_type_matchups / Stored 365 rows are populated
- refreshes live matchup payloads for today and tomorrow
- warms matchup snapshots for today and tomorrow
- clears process-local AI Data Assistant caches on each refreshed API target

Optional heavy recovery mode:
- set RUN_STATCAST_ETL=1 to run Statcast ETL/backfill
- set RUN_HITTER_STATCAST_BACKFILL=1 to run the wider hitter Statcast backfill

Stored 365 cards should not wait behind a multi-day ETL unless heavy recovery is
explicitly enabled in Railway.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import socket
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

REQUEST_TIMEOUT_SECONDS = int(os.environ.get("REFRESH_TIMEOUT_SECONDS", "60"))
REQUEST_MAX_ATTEMPTS = max(
    1,
    int(os.environ.get("REFRESH_MAX_ATTEMPTS", "3")),
)
REQUEST_RETRY_BACKOFF_SECONDS = max(
    0.0,
    float(os.environ.get("REFRESH_RETRY_BACKOFF_SECONDS", "1")),
)
RETRYABLE_HTTP_STATUS_CODES = frozenset({502, 503, 504})
RUN_FAST_MATCHUP_REFRESH = os.environ.get("RUN_FAST_MATCHUP_REFRESH", "1") == "1"
DEFAULT_WARM_MATCHUP_SNAPSHOTS = "0"
WARM_SNAPSHOTS = (
    os.environ.get(
        "WARM_MATCHUP_SNAPSHOTS",
        DEFAULT_WARM_MATCHUP_SNAPSHOTS,
    )
    == "1"
)
REFRESH_MATCHUPS_FIRST = os.environ.get("REFRESH_MATCHUPS_FIRST", "1") == "1"
CLEAR_AI_CACHE_AFTER_REFRESH = os.environ.get("CLEAR_AI_CACHE_AFTER_REFRESH", "1") == "1"
RUN_STATCAST_ETL = os.environ.get("RUN_STATCAST_ETL", "0") == "1"
RUN_HITTER_STATCAST_BACKFILL = os.environ.get("RUN_HITTER_STATCAST_BACKFILL", "0") == "1"
RUN_HITTING_MATCHUPS_REFRESH = os.environ.get("RUN_HITTING_MATCHUPS_REFRESH", "1") == "1"
RUN_CANONICAL_DASHBOARD_REFRESH = os.environ.get("RUN_CANONICAL_DASHBOARD_REFRESH", "1") == "1"
REFRESH_ETL_BACKFILL_DAYS = int(os.environ.get("REFRESH_ETL_BACKFILL_DAYS", "1"))
os.environ.setdefault("STATCAST_LOOKBACK_DAYS", "365")
os.environ.setdefault("HITTING_MATCHUPS_DAYS_BACK", "365")
os.environ.setdefault("HITTING_MATCHUPS_MAX_BATTERS", "240")
os.environ.setdefault("HITTER_STATCAST_START_DATE", "2023-03-01")
os.environ.setdefault("HITTER_STATCAST_MAX_PLAYERS", "1000")


def _log(message: str) -> None:
    timestamp = dt.datetime.utcnow().isoformat(timespec="seconds") + "Z"
    print(f"[{timestamp}] {message}", flush=True)


def _is_retryable_request_error(exc: BaseException) -> bool:
    if isinstance(exc, urllib.error.HTTPError):
        return exc.code in RETRYABLE_HTTP_STATUS_CODES
    return isinstance(
        exc,
        (
            urllib.error.URLError,
            TimeoutError,
            socket.timeout,
            ConnectionError,
        ),
    )


def _request_json(
    url: str,
    method: str = "GET",
    *,
    label: str = "unknown",
) -> dict | list | str | None:
    request = urllib.request.Request(url=url, method=method)

    for attempt in range(1, REQUEST_MAX_ATTEMPTS + 1):
        started = time.monotonic()
        try:
            with urllib.request.urlopen(
                request,
                timeout=REQUEST_TIMEOUT_SECONDS,
            ) as response:
                body = response.read().decode(
                    "utf-8",
                    errors="replace",
                )
                if attempt > 1:
                    _log(
                        json.dumps(
                            {
                                "event": "refresh_request_recovered",
                                "target": label,
                                "url": url,
                                "method": method,
                                "attempt": attempt,
                                "elapsed_seconds": round(
                                    time.monotonic() - started,
                                    3,
                                ),
                            },
                            sort_keys=True,
                        )
                    )
                if not body:
                    return None
                try:
                    return json.loads(body)
                except json.JSONDecodeError:
                    return body
        except Exception as exc:
            elapsed = round(time.monotonic() - started, 3)
            retryable = _is_retryable_request_error(exc)
            exhausted = attempt >= REQUEST_MAX_ATTEMPTS
            diagnostic = {
                "event": "refresh_request_failed",
                "target": label,
                "url": url,
                "method": method,
                "attempt": attempt,
                "max_attempts": REQUEST_MAX_ATTEMPTS,
                "elapsed_seconds": elapsed,
                "exception_type": type(exc).__name__,
                "message": str(exc),
                "retryable": retryable,
                "retries_exhausted": exhausted,
            }
            if isinstance(exc, urllib.error.HTTPError):
                diagnostic["http_status"] = exc.code
            _log(json.dumps(diagnostic, sort_keys=True))

            if not retryable or exhausted:
                raise

            backoff_seconds = (
                REQUEST_RETRY_BACKOFF_SECONDS
                * (2 ** (attempt - 1))
            )
            _log(
                json.dumps(
                    {
                        "event": "refresh_request_retry_scheduled",
                        "target": label,
                        "url": url,
                        "method": method,
                        "next_attempt": attempt + 1,
                        "backoff_seconds": backoff_seconds,
                    },
                    sort_keys=True,
                )
            )
            time.sleep(backoff_seconds)

    raise RuntimeError("request retry loop exited unexpectedly")


def _has_pitcher(game: dict, side: str) -> bool:
    """Return true when a matchup payload includes a usable pitcher for the side."""
    return bool(
        game.get(f"{side}_pitcher_id")
        or game.get(f"{side}_pitcher_name")
        or game.get(f"{side}_probable_pitcher_id")
        or game.get(f"{side}_probable_pitcher_name")
    )


def _missing_pitcher_summary(game: dict) -> dict:
    return {
        "game_pk": game.get("game_pk"),
        "away_team": game.get("away_team_name"),
        "home_team": game.get("home_team_name"),
        "away_pitcher_id": game.get("away_pitcher_id"),
        "away_pitcher_name": game.get("away_pitcher_name"),
        "away_pitcher_status": game.get("away_pitcher_status"),
        "home_pitcher_id": game.get("home_pitcher_id"),
        "home_pitcher_name": game.get("home_pitcher_name"),
        "home_pitcher_status": game.get("home_pitcher_status"),
    }


def _refresh_matchups_for_date(label: str, base_url: str, target_date: dt.date) -> None:
    query = urllib.parse.urlencode({"date": target_date.isoformat()})
    url = f"{base_url}/matchups?{query}"
    _log(f"[{label}] Refreshing live matchup payload for {target_date.isoformat()} via {url}")
    result = _request_json(
        url,
        method="GET",
        label=label,
    )
    if isinstance(result, list):
        pitcher_counts = {
            "home": sum(
                1
                for game in result
                if isinstance(game, dict) and _has_pitcher(game, "home")
            ),
            "away": sum(
                1
                for game in result
                if isinstance(game, dict) and _has_pitcher(game, "away")
            ),
        }
        missing_pitchers = [
            _missing_pitcher_summary(game)
            for game in result
            if isinstance(game, dict)
            and (not _has_pitcher(game, "home") or not _has_pitcher(game, "away"))
        ]
        _log(
            f"[{label}] Live matchup refresh result for {target_date.isoformat()}: "
            f"{len(result)} games, pitcher counts={pitcher_counts}, "
            f"missing_pitcher_games={len(missing_pitchers)}"
        )
        if missing_pitchers:
            _log(
                f"[{label}] Missing pitcher detail for {target_date.isoformat()}: "
                f"{missing_pitchers}"
            )
    else:
        _log(f"[{label}] Live matchup refresh response for {target_date.isoformat()}: {result}")


def _warm_snapshot_for_date(label: str, base_url: str, target_date: dt.date) -> None:
    url = f"{base_url}/matchups/snapshot/{target_date.isoformat()}"
    _log(f"[{label}] Warming matchup snapshot for {target_date.isoformat()} via {url}")
    result = _request_json(
        url,
        method="POST",
        label=label,
    )
    _log(f"[{label}] Snapshot response for {target_date.isoformat()}: {result}")


def _clear_ai_data_assistant_cache(label: str, base_url: str) -> None:
    """Best-effort cache clear for process-local AI/model projection caches.

    This intentionally never raises. A cache clear failure should not turn an
    otherwise successful refresh into a failed Railway cron run.
    """
    if not CLEAR_AI_CACHE_AFTER_REFRESH:
        _log(f"[{label}] Skipping AI Data Assistant cache clear because CLEAR_AI_CACHE_AFTER_REFRESH=0")
        return

    url = f"{base_url}/ai-data-assistant/cache/clear"
    try:
        _log(f"[{label}] Clearing AI Data Assistant cache via {url}")
        result = _request_json(
            url,
            method="POST",
            label=label,
        )
        _log(f"[{label}] AI Data Assistant cache clear response: {result}")
    except Exception as exc:
        _log(f"[{label}] AI Data Assistant cache clear failed but refresh will continue: {exc}")


def _run_statcast_etl_refresh() -> None:
    if not RUN_STATCAST_ETL:
        _log("Skipping Statcast ETL refresh because RUN_STATCAST_ETL=0")
        return
    if REFRESH_ETL_BACKFILL_DAYS < 1:
        _log("Skipping Statcast ETL refresh because REFRESH_ETL_BACKFILL_DAYS < 1")
        return

    _log(
        "Starting Statcast ETL refresh: "
        f"backfill_days={REFRESH_ETL_BACKFILL_DAYS}, "
        f"statcast_lookback_days={os.environ.get('STATCAST_LOOKBACK_DAYS', '365')}"
    )
    from mlb_app.etl import run_backfill

    run_backfill(REFRESH_ETL_BACKFILL_DAYS)
    _log("Statcast ETL refresh completed")


def _run_hitter_statcast_backfill() -> None:
    if not RUN_HITTER_STATCAST_BACKFILL:
        _log("Skipping hitter Statcast backfill because RUN_HITTER_STATCAST_BACKFILL=0")
        return

    _log(
        "Starting hitter Statcast backfill: "
        f"start_date={os.environ.get('HITTER_STATCAST_START_DATE', '2023-03-01')}, "
        f"max_players={os.environ.get('HITTER_STATCAST_MAX_PLAYERS', '1000')}"
    )
    from scripts.backfill_hitter_statcast import run

    result = run(
        start_date=os.environ.get("HITTER_STATCAST_START_DATE", "2023-03-01"),
        end_date=dt.date.today().isoformat(),
        max_players=int(os.environ.get("HITTER_STATCAST_MAX_PLAYERS", "1000")),
    )
    _log(
        "Hitter Statcast backfill completed: "
        f"targets={result.get('target_count')}, "
        f"fetched_rows={result.get('fetched_rows')}, "
        f"inserted_rows={result.get('inserted_rows')}, "
        f"updated_rows={result.get('updated_rows')}"
    )


def _run_hitting_matchups_refresh() -> None:
    if not RUN_HITTING_MATCHUPS_REFRESH:
        _log("Skipping hittingMatchups refresh because RUN_HITTING_MATCHUPS_REFRESH=0")
        return

    _log(
        "Starting hittingMatchups refresh: "
        f"days_back={os.environ.get('HITTING_MATCHUPS_DAYS_BACK', '365')}, "
        f"max_batters={os.environ.get('HITTING_MATCHUPS_MAX_BATTERS', '240')}"
    )
    from scripts.run_hitting_matchups_refresh import run

    result = run()
    _log(
        "hittingMatchups refresh completed: "
        f"targets={result.get('target_count')}, "
        f"upserted_rows={result.get('upserted_rows')}, "
        f"rows_with_raw_statcast={result.get('rows_with_raw_statcast')}, "
        f"rows_without_raw_statcast={result.get('rows_without_raw_statcast')}, "
        f"gap_fill_checked_rows={result.get('gap_fill_checked_rows')}, "
        f"gap_fill_upserted_rows={result.get('gap_fill_upserted_rows')}, "
        f"gap_fill_still_missing_rows={result.get('gap_fill_still_missing_rows')}"
    )


def _run_canonical_dashboard_refresh() -> None:
    if not RUN_CANONICAL_DASHBOARD_REFRESH:
        _log(
            "Skipping canonical MyDashboard refresh because "
            "RUN_CANONICAL_DASHBOARD_REFRESH=0"
        )
        return

    from mlb_app.dashboard_projection_operator import run_canonical_projection_refresh
    from mlb_app.database import create_tables, get_engine, get_session
    from mlb_app.my_dashboard_dataset_runtime import mlb_business_date

    target_date = mlb_business_date()
    database_url = os.environ.get("DATABASE_URL", "sqlite:///mlb.db")
    engine = get_engine(database_url)
    create_tables(engine)
    factory = get_session(engine)
    _log(
        "Starting canonical MyDashboard refresh after upstream matchup, "
        f"Statcast, lineup, and model work for {target_date.isoformat()}"
    )
    with factory() as session:
        result = run_canonical_projection_refresh(
            session,
            target_date=target_date,
        )
    hitter_coverage = (
        result.get("projection", {})
        .get("field_coverage", {})
        .get("hitter", {})
    )
    _log(
        "Canonical MyDashboard refresh completed: "
        f"run_id={result.get('run_id')}, "
        f"active_count={result.get('population', {}).get('active_count')}, "
        f"current_row_count={result.get('current_row_count')}, "
        f"hitter_rows={hitter_coverage.get('row_count')}, "
        f"model_score_coverage="
        f"{hitter_coverage.get('fields', {}).get('model_score', {}).get('coverage')}"
    )
    try:
        from mlb_app.report_subscriptions import dispatch_report_subscriptions

        subscription_summary = dispatch_report_subscriptions(factory)
        _log(
            "Saved-report subscription check completed: "
            + ", ".join(
                f"{key}={value}" for key, value in subscription_summary.items()
            )
        )
    except Exception as exc:
        # Email delivery must never turn a successful canonical refresh into a failed refresh.
        _log(f"Saved-report subscription check failed: {exc}")


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


def _check_readiness(label: str, base_url: str) -> None:
    url = f"{base_url}/health"
    _log(f"[{label}] Checking target readiness via {url}")
    result = _request_json(
        url,
        method="GET",
        label=label,
    )
    _log(f"[{label}] Readiness response: {result}")


def _run_target(label: str, base_url: str) -> None:
    _check_readiness(label, base_url)
    today = dt.date.today()
    tomorrow = today + dt.timedelta(days=1)

    for target_date in (today, tomorrow):
        if REFRESH_MATCHUPS_FIRST:
            _refresh_matchups_for_date(label, base_url, target_date)

        if WARM_SNAPSHOTS:
            _warm_snapshot_for_date(label, base_url, target_date)

    _clear_ai_data_assistant_cache(label, base_url)


def _run_fast_matchup_refresh() -> None:
    if not RUN_FAST_MATCHUP_REFRESH:
        _log("Skipping fast matchup refresh because RUN_FAST_MATCHUP_REFRESH=0")
        return

    try:
        _run_hitting_matchups_refresh()
    except Exception as exc:
        _log(f"hittingMatchups refresh failed: {exc}")
        raise

    targets = _load_targets()
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
        _log("Fast matchup refresh completed with target failures:")
        for failure in failures:
            _log(f" - {failure}")
        raise RuntimeError("One or more refresh targets failed")


def main() -> int:
    _log("Starting Railway refresh job")
    _log(
        "Refresh mode: "
        f"fast_matchup_refresh={int(RUN_FAST_MATCHUP_REFRESH)}, "
        f"run_statcast_etl={int(RUN_STATCAST_ETL)}, "
        f"etl_backfill_days={REFRESH_ETL_BACKFILL_DAYS}, "
        f"run_hitter_statcast_backfill={int(RUN_HITTER_STATCAST_BACKFILL)}, "
        f"run_hitting_matchups_refresh={int(RUN_HITTING_MATCHUPS_REFRESH)}, "
        f"run_canonical_dashboard_refresh={int(RUN_CANONICAL_DASHBOARD_REFRESH)}, "
        f"clear_ai_cache_after_refresh={int(CLEAR_AI_CACHE_AFTER_REFRESH)}, "
        f"request_timeout_seconds={REQUEST_TIMEOUT_SECONDS}, "
        f"request_max_attempts={REQUEST_MAX_ATTEMPTS}, "
        f"request_retry_backoff_seconds={REQUEST_RETRY_BACKOFF_SECONDS}"
    )

    try:
        import mlb_app.app  # noqa: F401
    except Exception as exc:
        _log(f"Failed to import app module: {exc}")
        return 1

    try:
        _run_fast_matchup_refresh()
    except Exception as exc:
        _log(f"Fast matchup refresh failed: {exc}")
        return 1

    try:
        _run_statcast_etl_refresh()
    except Exception as exc:
        _log(f"Statcast ETL refresh failed: {exc}")
        return 1

    try:
        _run_hitter_statcast_backfill()
    except Exception as exc:
        _log(f"Hitter Statcast backfill failed: {exc}")
        return 1

    try:
        _run_canonical_dashboard_refresh()
    except Exception as exc:
        _log(f"Canonical MyDashboard refresh failed: {exc}")
        return 1

    _log("Refresh job completed successfully")
    return 0


if __name__ == "__main__":
    sys.exit(main())

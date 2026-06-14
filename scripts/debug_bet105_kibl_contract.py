#!/usr/bin/env python3
"""Capture the KIBL Bet105 request/response contract without touching the app route.

Run this only in an environment that already has KIBL credentials configured.
It intentionally prints compact, redacted summaries rather than full payloads.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple

# Make the script runnable from Railway/container shells without requiring PYTHONPATH.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from mlb_app.kibl_bet105_repository import KiblBet105Repository
from mlb_app.kibl_client import KiblClient, find_rows


MARKET_PATH = "info/markets"
FIXTURE_PATH = "info/fixtures"


ROUTING_FIELD_SETS: Tuple[Tuple[str, ...], ...] = (
    ("sport_id", "sport_type_id", "league_id", "region_id", "competition_id", "fixture_id", "feed_source_id", "betting_type_id", "market_type_id", "segment_id", "alt_id"),
    ("sport_id", "league_id", "region_id", "competition_id", "fixture_id", "feed_source_id", "betting_type_id", "market_type_id", "segment_id", "alt_id"),
    ("sport_type_id", "league_id", "region_id", "competition_id", "fixture_id", "feed_source_id", "betting_type_id", "market_type_id", "segment_id", "alt_id"),
    ("provider_id", "sport_id", "league_id", "region_id", "competition_id", "fixture_id", "feed_source_id", "betting_type_id", "market_type_id", "segment_id", "alt_id"),
)


def _clean_body(body: Dict[str, Any]) -> Dict[str, Any]:
    return {key: value for key, value in body.items() if value not in (None, "", [], {})}


def _row_value(row: Dict[str, Any], key: str) -> Any:
    if key in row:
        return row.get(key)
    info = row.get("info") if isinstance(row.get("info"), dict) else {}
    return info.get(key)


def _unique(rows: Iterable[Dict[str, Any]], key: str, limit: int = 12) -> List[str]:
    values: List[str] = []
    for row in rows:
        value = _row_value(row, key)
        if value in (None, ""):
            continue
        text = str(value)
        if text not in values:
            values.append(text)
        if len(values) >= limit:
            break
    return values


def _keys(rows: List[Dict[str, Any]]) -> List[str]:
    seen: List[str] = []
    for row in rows[:10]:
        for key in row.keys():
            if key not in seen:
                seen.append(key)
    return seen


def _routing_parts(seed: Dict[str, Any]) -> List[str]:
    raw = str(_row_value(seed, "routing_key") or "")
    prefix = "get.info.markets."
    if raw.startswith(prefix):
        raw = raw[len(prefix):]
    return [piece for piece in raw.split(".") if piece != ""]


def _request(client: KiblClient, path: str, label: str, body: Dict[str, Any]) -> Dict[str, Any]:
    clean = _clean_body(body)
    try:
        payload = client.post(path, clean)
        rows = find_rows(payload)
        return {
            "label": label,
            "path": path,
            "body_keys": sorted(clean.keys()),
            "body": clean,
            "row_count": len(rows),
            "fixture_ids": _unique(rows, "fixture_id"),
            "market_ids": _unique(rows, "market_id"),
            "market_type_ids": _unique(rows, "market_type_id"),
            "participant_ids": _unique(rows, "participant_id"),
            "fixture_participant_ids": _unique(rows, "fixture_participant_id"),
            "line_ids": _unique(rows, "line_id"),
            "contestant_ids": _unique(rows, "contestant_id"),
            "side_ids": _unique(rows, "side_id"),
            "sides": _unique(rows, "side"),
            "routing_keys": _unique(rows, "routing_key"),
            "first_row_keys": _keys(rows),
            "first_row_sample": rows[:1],
        }
    except Exception as exc:  # noqa: BLE001 - debug capture should report every failed shape.
        return {
            "label": label,
            "path": path,
            "body_keys": sorted(clean.keys()),
            "body": clean,
            "row_count": 0,
            "error": str(exc),
        }


def _body_without_dates(filters: Dict[str, Any]) -> Dict[str, Any]:
    return {key: value for key, value in filters.items() if key not in {"start_date", "end_date", "from", "to"}}


def _body_without_book(filters: Dict[str, Any]) -> Dict[str, Any]:
    return {key: value for key, value in filters.items() if key not in {"feed_source_id", "betting_type_id"}}


def _routing_bodies(filters: Dict[str, Any], seed: Dict[str, Any]) -> List[Tuple[str, Dict[str, Any]]]:
    parts = _routing_parts(seed)
    if not parts:
        return []

    out: List[Tuple[str, Dict[str, Any]]] = [("routing_parts_only", {"routing_key_parts": parts})]
    for idx, value in enumerate(parts):
        out.append((f"routing_part_{idx}", {**filters, f"routing_part_{idx}": value}))

    for field_set_idx, fields in enumerate(ROUTING_FIELD_SETS):
        if len(parts) < len(fields):
            continue
        body = dict(zip(fields, parts[: len(fields)]))
        out.append((f"routing_map_{field_set_idx}", body))
        out.append((f"routing_map_{field_set_idx}+dates", {**body, **{key: filters[key] for key in ("start_date", "end_date", "from", "to") if key in filters}}))
        out.append((f"routing_map_{field_set_idx}+league_feed", {**body, "league_id": filters.get("league_id"), "feed_source_id": filters.get("feed_source_id"), "betting_type_id": filters.get("betting_type_id")}))

    # Target likely dimensions from the observed routing key without relying on exact names.
    for key_name in ("sport_id", "sport_type_id", "provider_id", "region_id", "competition_id"):
        for value in parts[:6]:
            out.append((f"{key_name}_{value}", {**filters, key_name: value}))
            out.append((f"core_{key_name}_{value}", {**_body_without_dates(filters), key_name: value}))

    return out


def _diagnostic_filter_bodies(filters: Dict[str, Any]) -> List[Tuple[str, Dict[str, Any]]]:
    core = _body_without_dates(filters)
    no_book = _body_without_book(filters)
    out: List[Tuple[str, Dict[str, Any]]] = [
        ("diag_core_no_dates", core),
        ("diag_feed_betting_only", {"feed_source_id": filters.get("feed_source_id"), "betting_type_id": filters.get("betting_type_id")}),
        ("diag_feed_betting_league20", {"feed_source_id": filters.get("feed_source_id"), "betting_type_id": filters.get("betting_type_id"), "league_id": "20"}),
        ("diag_feed_betting_league643", {"feed_source_id": filters.get("feed_source_id"), "betting_type_id": filters.get("betting_type_id"), "league_id": "643"}),
        ("diag_no_book_filters", no_book),
        ("diag_no_dates_no_book", _body_without_dates(no_book)),
        ("diag_league20_full_dates", {**filters, "league_id": "20"}),
        ("diag_league643_full_dates", {**filters, "league_id": "643"}),
        ("diag_league20_no_dates", {**core, "league_id": "20"}),
        ("diag_league643_no_dates", {**core, "league_id": "643"}),
    ]
    return out


def _seeded_market_bodies(filters: Dict[str, Any], seed: Dict[str, Any]) -> List[Tuple[str, Dict[str, Any]]]:
    base = dict(filters)
    body_specs: List[Tuple[str, Dict[str, Any]]] = [("base", base)]

    # Direct row-derived fields from the one known-good Bet105 market row.
    for key in (
        "fixture_id",
        "event_id",
        "market_id",
        "market_type_id",
        "segment_id",
        "participant_id",
        "fixture_participant_id",
        "side_id",
        "line_id",
        "contestant_id",
    ):
        value = _row_value(seed, key)
        if value not in (None, ""):
            body_specs.append((key, {**base, key: value}))
            body_specs.append((f"core_{key}", {**_body_without_dates(base), key: value}))

    fixture_id = _row_value(seed, "fixture_id")
    market_id = _row_value(seed, "market_id")
    market_type_id = _row_value(seed, "market_type_id")
    line_id = _row_value(seed, "line_id")
    contestant_id = _row_value(seed, "contestant_id")

    combos = [
        ("fixture_id+market_id", {"fixture_id": fixture_id, "market_id": market_id}),
        ("fixture_id+market_type_id", {"fixture_id": fixture_id, "market_type_id": market_type_id}),
        ("fixture_id+line_id", {"fixture_id": fixture_id, "line_id": line_id}),
        ("fixture_id+contestant_id", {"fixture_id": fixture_id, "contestant_id": contestant_id}),
        ("market_id+line_id", {"market_id": market_id, "line_id": line_id}),
    ]
    for label, extra in combos:
        clean_extra = _clean_body(extra)
        if clean_extra:
            body_specs.append((label, {**base, **clean_extra}))
            body_specs.append((f"core_{label}", {**_body_without_dates(base), **clean_extra}))

    body_specs.extend(_diagnostic_filter_bodies(filters))
    body_specs.extend(_routing_bodies(filters, seed))

    # Check whether offset acts as a cursor without multiplying production requests.
    for offset in range(0, int(os.getenv("BET105_CONTRACT_PROBE_OFFSETS", "6"))):
        body_specs.append((f"base_offset_{offset}", {**base, "offset": offset, "limit": 250}))

    seen: set[str] = set()
    out: List[Tuple[str, Dict[str, Any]]] = []
    for label, body in body_specs:
        fp = repr(sorted((key, str(value)) for key, value in _clean_body(body).items()))
        if fp not in seen:
            seen.add(fp)
            out.append((label, body))
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description="Capture KIBL Bet105 request contract summaries.")
    parser.add_argument("--date", default=os.getenv("BET105_DEBUG_DATE"), help="Slate date, YYYY-MM-DD")
    parser.add_argument("--live", action="store_true", help="Use live betting_type_id")
    parser.add_argument("--raw-samples", action="store_true", help="Include first-row samples in output")
    args = parser.parse_args()

    repo = KiblBet105Repository()
    client = repo.client
    filters = repo.build_filters(date=args.date, live_only=args.live)

    base_result = _request(client, MARKET_PATH, "base", {**filters, "offset": 0, "limit": 250})
    results = [base_result]
    seed_rows = base_result.get("first_row_sample") or []
    seed = seed_rows[0] if seed_rows and isinstance(seed_rows[0], dict) else {}

    if seed:
        for label, body in _seeded_market_bodies(filters, seed):
            if label == "base":
                continue
            results.append(_request(client, MARKET_PATH, label, body))

        fixture_id = _row_value(seed, "fixture_id")
        fixture_bodies = [
            ("fixture_by_fixture_id", {**filters, "fixture_id": fixture_id, "offset": 0, "limit": 250}),
            ("fixture_by_id", {**filters, "id": fixture_id, "offset": 0, "limit": 250}),
            ("fixture_core_by_fixture_id", {**_body_without_dates(filters), "fixture_id": fixture_id, "offset": 0, "limit": 250}),
            ("fixture_no_book_by_fixture_id", {**_body_without_book(filters), "fixture_id": fixture_id, "offset": 0, "limit": 250}),
        ]
        if fixture_id not in (None, ""):
            for label, body in fixture_bodies:
                results.append(_request(client, FIXTURE_PATH, label, body))

    if not args.raw_samples:
        for result in results:
            result.pop("first_row_sample", None)

    winners = [result for result in results if int(result.get("row_count") or 0) > 1]
    payload = {
        "status": "ok" if results else "empty",
        "date": args.date,
        "live": bool(args.live),
        "base_filters": filters,
        "result_count": len(results),
        "winner_count": len(winners),
        "winners": winners,
        "results": results,
    }
    print(json.dumps(payload, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

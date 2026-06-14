from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

from . import kibl_bet105_provider as legacy
from .kibl_bet105_types import Bet105RawBoard
from .kibl_client import KiblClient, find_rows


class KiblBet105Repository:
    market_summary_path = "info/markets"
    fixture_summary_path = "info/fixtures"
    fixture_paths = ("info/fixtures", "fixtures", "events", "info/events", "info/games", "info/matches")
    metadata_paths = ("info/fixture_participants", "info/participants", "info/contestants", "info/competitors", "info/teams")

    def __init__(self, client: Optional[KiblClient] = None) -> None:
        self.client = client or KiblClient()

    def build_filters(self, date: Optional[str] = None, live_only: Optional[bool] = None, event_id: Optional[str] = None) -> Dict[str, Any]:
        filters = legacy.build_kibl_bet105_request_params(
            "live" if live_only else "events",
            date=date,
            live_only=live_only,
            event_id=event_id,
            include_markets=False,
        )
        filters.pop("from_cache", None)
        return filters

    @staticmethod
    def _csv_values(value: Any) -> set[str]:
        if value in (None, ""):
            return set()
        if isinstance(value, (list, tuple, set)):
            return {str(item).strip() for item in value if item not in (None, "")}
        return {piece.strip() for piece in str(value).split(",") if piece.strip()}

    @staticmethod
    def _safe_text(value: Any) -> Optional[str]:
        if value in (None, ""):
            return None
        return str(value).strip()

    def _row_matches_requested_feed(self, row: Dict[str, Any], filters: Dict[str, Any]) -> bool:
        expected_feed = self._safe_text(filters.get("feed_source_id"))
        expected_betting = self._safe_text(filters.get("betting_type_id"))
        row_feed = self._safe_text(row.get("feed_source_id"))
        row_betting = self._safe_text(row.get("betting_type_id"))
        if expected_feed and row_feed and row_feed != expected_feed:
            return False
        if expected_betting and row_betting and row_betting != expected_betting:
            return False
        return True

    def _row_matches_requested_league(self, row: Dict[str, Any], filters: Dict[str, Any]) -> bool:
        requested = self._csv_values(filters.get("league_id"))
        if not requested:
            return True
        row_values: set[str] = set()
        for key in ("league_id", "leagueId", "competition_id", "competitionId", "sport_id", "sportId"):
            row_values.update(self._csv_values(row.get(key)))
        if not row_values:
            return True
        return bool(row_values.intersection(requested))

    def _filter_rows(self, rows: List[Dict[str, Any]], filters: Dict[str, Any], notes: List[str], label: str) -> List[Dict[str, Any]]:
        kept: List[Dict[str, Any]] = []
        for row in rows:
            if not self._row_matches_requested_feed(row, filters):
                continue
            if not self._row_matches_requested_league(row, filters):
                continue
            kept.append(row)
        notes.append(
            f"{label}_filter:raw={len(rows)}:kept={len(kept)}:feed={filters.get('feed_source_id')}:betting={filters.get('betting_type_id')}:league={filters.get('league_id')}"
        )
        return kept

    def fetch_summary(self, path: str, filters: Dict[str, Any], notes: List[str], label: str) -> List[Dict[str, Any]]:
        rows: List[Dict[str, Any]] = []
        limit = int(os.getenv("KIBL_SUMMARY_LIMIT", "250"))
        max_pages = int(os.getenv("KIBL_SUMMARY_MAX_PAGES", "1"))
        for page in range(max_pages):
            offset = page * limit
            payload = self.client.post_summary(path, filters, offset=offset, limit=limit)
            page_rows = find_rows(payload)
            filtered = self._filter_rows(page_rows, filters, notes, label)
            notes.append(f"{label}_summary:{path}:offset={offset}:limit={limit}:raw={len(page_rows)}:kept={len(filtered)}")
            rows.extend(filtered)
            if len(page_rows) < limit:
                break
        return rows

    def fetch_market_summary(self, filters: Dict[str, Any], notes: List[str]) -> List[Dict[str, Any]]:
        return self.fetch_summary(self.market_summary_path, filters, notes, "market")

    def fetch_fixture_summary(self, filters: Dict[str, Any], ids: Dict[str, List[str]], notes: List[str]) -> List[Dict[str, Any]]:
        rows = self.fetch_summary(self.fixture_summary_path, filters, notes, "fixture")
        fixture_ids = set(ids.get("fixture_id") or [])
        if fixture_ids and rows:
            matched = []
            for row in rows:
                row_ids = self._csv_values(row.get("fixture_id") or row.get("event_id") or row.get("id"))
                if not row_ids or row_ids.intersection(fixture_ids):
                    matched.append(row)
            notes.append(f"fixture_summary_join:raw={len(rows)}:matched={len(matched)}:market_fixture_ids={len(fixture_ids)}")
            return matched
        notes.append(f"fixture_summary_join:raw={len(rows)}:matched={len(rows)}:market_fixture_ids={len(fixture_ids)}")
        return rows

    @staticmethod
    def _add(ids: Dict[str, List[str]], key: str, value: Any) -> None:
        if value in (None, ""):
            return
        text = str(value)
        if text not in ids.setdefault(key, []):
            ids[key].append(text)

    def extract_ids(self, market_rows: List[Dict[str, Any]]) -> Dict[str, List[str]]:
        ids: Dict[str, List[str]] = {key: [] for key in ("fixture_id", "market_id", "participant_id", "fixture_participant_id", "contestant_id", "line_id")}
        for row in market_rows:
            info = row.get("info") if isinstance(row.get("info"), dict) else {}
            for key in ("fixture_id", "market_id", "participant_id", "fixture_participant_id"):
                self._add(ids, key, row.get(key))
            self._add(ids, "contestant_id", info.get("contestant_id"))
            self._add(ids, "line_id", info.get("line_id"))
        return ids

    def _clean(self, filters: Dict[str, Any], compact: bool = False) -> Dict[str, Any]:
        drop = {"from_cache", "path", "combined_market_candidates"}
        if compact:
            drop.update({"start_date", "end_date", "from", "to"})
        return {key: value for key, value in filters.items() if key not in drop and value not in (None, "")}

    def _detail_bodies(self, filters: Dict[str, Any], ids: Dict[str, List[str]], source_keys: List[str]) -> List[tuple[str, Dict[str, Any]]]:
        bodies: List[tuple[str, Dict[str, Any]]] = []
        for root in (self._clean(filters), self._clean(filters, compact=True)):
            for source_key in source_keys:
                values = ids.get(source_key) or []
                if not values:
                    continue
                for body_key in (source_key, f"{source_key}s", "ids"):
                    bodies.append((f"{source_key}->{body_key}", {**root, body_key: values[:100]}))
        seen: set[str] = set()
        out: List[tuple[str, Dict[str, Any]]] = []
        for label, body in bodies:
            fingerprint = repr(sorted((key, str(value)) for key, value in body.items()))
            if fingerprint not in seen:
                seen.add(fingerprint)
                out.append((label, body))
        return out

    def fetch_details(self, paths: tuple[str, ...], filters: Dict[str, Any], ids: Dict[str, List[str]], keys: List[str], notes: List[str], label: str) -> List[Dict[str, Any]]:
        if not any(ids.get(key) for key in keys):
            notes.append(f"{label}_detail_skipped:no_ids")
            return []
        rows: List[Dict[str, Any]] = []
        max_attempts = int(os.getenv("KIBL_DETAIL_MAX_ATTEMPTS", "12"))
        attempts = 0
        for path in paths:
            for body_label, body in self._detail_bodies(filters, ids, keys):
                attempts += 1
                if attempts > max_attempts:
                    notes.append(f"{label}_detail_stopped:max_attempts={max_attempts}")
                    return rows
                try:
                    payload = self.client.post(path, body)
                    found = find_rows(payload)
                    notes.append(f"{label}_detail:{path}:{body_label}:rows={len(found)}")
                    if found:
                        rows.extend(found)
                        return rows
                except Exception as exc:
                    notes.append(f"{label}_detail_error:{path}:{body_label}:{str(exc)[:120]}")
        return rows

    def fetch_board(self, date: Optional[str] = None, live_only: Optional[bool] = None, event_id: Optional[str] = None) -> Bet105RawBoard:
        filters = self.build_filters(date=date, live_only=live_only, event_id=event_id)
        board = Bet105RawBoard(filters=filters)
        board.market_rows = self.fetch_market_summary(filters, board.notes)
        board.ids = self.extract_ids(board.market_rows)
        board.notes.append(
            f"market_ids:fixtures={len(board.ids.get('fixture_id') or [])}:participants={len(board.ids.get('participant_id') or [])}:fixture_participants={len(board.ids.get('fixture_participant_id') or [])}:markets={len(board.ids.get('market_id') or [])}"
        )
        board.fixture_rows = self.fetch_fixture_summary(filters, board.ids, board.notes)
        if not board.fixture_rows:
            board.fixture_rows = self.fetch_details(self.fixture_paths, filters, board.ids, ["fixture_id"], board.notes, "fixture")
        board.participant_rows = self.fetch_details(
            self.metadata_paths,
            filters,
            board.ids,
            ["fixture_participant_id", "participant_id", "contestant_id", "line_id"],
            board.notes,
            "metadata",
        )
        return board

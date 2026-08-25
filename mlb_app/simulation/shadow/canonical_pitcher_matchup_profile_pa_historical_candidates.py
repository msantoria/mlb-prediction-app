"""Materialize cutoff-safe pitcher-profile candidates for historical games.

Every requested candidate is built from one shared event collection. The
runtime candidate enforces its own strict pregame cutoff and calibrated
shadow-only authority contract.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
from copy import deepcopy
from typing import Any, Iterable, Mapping

from mlb_app.simulation.shadow.canonical_pitcher_matchup_profile_runtime_candidate import (
    build_canonical_pitcher_matchup_profile_runtime_candidate,
)


SCHEMA_VERSION = (
    "canonical_pitcher_matchup_profile_pa_historical_candidates_v1"
)


def _value(row: Any, name: str) -> Any:
    if isinstance(row, Mapping):
        return row.get(name)
    return getattr(row, name, None)


def _positive_integer(
    value: Any,
    name: str,
) -> int:
    if isinstance(value, bool):
        raise ValueError(
            f"{name}_must_be_positive_integer"
        )

    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"{name}_must_be_positive_integer"
        ) from exc

    if parsed <= 0:
        raise ValueError(
            f"{name}_must_be_positive_integer"
        )

    return parsed


def _date(value: Any) -> dt.date:
    if isinstance(value, dt.datetime):
        return value.date()

    if isinstance(value, dt.date):
        return value

    try:
        return dt.date.fromisoformat(
            str(value)
        )
    except (TypeError, ValueError) as exc:
        raise ValueError(
            "game_date_must_be_iso_date"
        ) from exc


def _digest(value: Any) -> str:
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")

    return hashlib.sha256(
        encoded
    ).hexdigest()


def _candidate_status(
    candidate: Mapping[str, Any],
) -> str:
    diagnostics = candidate.get(
        "diagnostics"
    )

    if not isinstance(diagnostics, Mapping):
        return "unavailable"

    status = diagnostics.get("status")

    if status in {
        "ready",
        "partial",
        "unavailable",
    }:
        return str(status)

    return "unavailable"


def materialize_canonical_pitcher_matchup_profile_pa_historical_candidates(
    events: Iterable[Any],
    *,
    requests: Iterable[Any],
    window_days: int = 90,
) -> dict[str, Any]:
    """Build one cutoff-safe candidate per historical game-pitcher."""
    if (
        not isinstance(window_days, int)
        or isinstance(window_days, bool)
        or window_days <= 0
    ):
        raise ValueError(
            "window_days_must_be_positive_integer"
        )

    event_rows = list(events)
    request_rows = list(requests)
    normalized_requests: dict[
        tuple[int, int],
        dict[str, Any],
    ] = {}
    conflicting_keys: set[
        tuple[int, int]
    ] = set()
    rejected_requests = []
    duplicate_request_count = 0

    for index, request in enumerate(
        request_rows
    ):
        try:
            game_pk = _positive_integer(
                _value(request, "game_pk"),
                "game_pk",
            )
            pitcher_id = _positive_integer(
                _value(request, "pitcher_id"),
                "pitcher_id",
            )
            game_date = _date(
                _value(request, "game_date")
            )
        except ValueError as exc:
            rejected_requests.append({
                "index": index,
                "reason": str(exc),
            })
            continue

        key = (
            game_pk,
            pitcher_id,
        )
        normalized = {
            "game_pk": game_pk,
            "pitcher_id": pitcher_id,
            "game_date": game_date,
        }

        if key in conflicting_keys:
            duplicate_request_count += 1
            continue

        existing = normalized_requests.get(
            key
        )

        if existing is None:
            normalized_requests[key] = (
                normalized
            )
            continue

        if (
            existing["game_date"]
            == game_date
        ):
            duplicate_request_count += 1
            continue

        normalized_requests.pop(
            key,
            None,
        )
        conflicting_keys.add(key)
        rejected_requests.append({
            "index": index,
            "game_pk": game_pk,
            "pitcher_id": pitcher_id,
            "reason": (
                "conflicting_game_pitcher_request"
            ),
        })

    candidates: dict[
        tuple[int, int],
        dict[str, Any],
    ] = {}
    candidate_records = []
    status_counts = {
        "ready": 0,
        "partial": 0,
        "unavailable": 0,
    }

    for key, request in sorted(
        normalized_requests.items(),
        key=lambda item: (
            item[1]["game_date"],
            item[0][0],
            item[0][1],
        ),
    ):
        game_pk, pitcher_id = key
        game_date = request["game_date"]

        try:
            candidate = (
                build_canonical_pitcher_matchup_profile_runtime_candidate(
                    event_rows,
                    pitcher_id=pitcher_id,
                    game_date=game_date,
                    window_days=window_days,
                )
            )
        except (
            TypeError,
            ValueError,
        ) as exc:
            rejected_requests.append({
                "game_pk": game_pk,
                "pitcher_id": pitcher_id,
                "game_date": (
                    game_date.isoformat()
                ),
                "reason": (
                    "candidate_materialization_failed:"
                    + str(exc)
                ),
            })
            continue

        candidate = deepcopy(candidate)
        status = _candidate_status(
            candidate
        )
        diagnostics = candidate.get(
            "diagnostics"
        )

        if not isinstance(
            diagnostics,
            Mapping,
        ):
            diagnostics = {}

        authority_valid = (
            diagnostics.get(
                "production_authority"
            )
            is False
            and diagnostics.get(
                "production_authority_changed"
            )
            is False
        )

        if not authority_valid:
            rejected_requests.append({
                "game_pk": game_pk,
                "pitcher_id": pitcher_id,
                "game_date": (
                    game_date.isoformat()
                ),
                "reason": (
                    "candidate_authority_contract_invalid"
                ),
            })
            continue

        candidates[key] = candidate
        status_counts[status] += 1
        candidate_records.append({
            "game_pk": game_pk,
            "pitcher_id": pitcher_id,
            "game_date": (
                game_date.isoformat()
            ),
            "status": status,
            "cutoff_rule": diagnostics.get(
                "cutoff_rule"
            ),
            "evidence_status": (
                diagnostics.get(
                    "evidence_status"
                )
            ),
            "league_prior_status": (
                diagnostics.get(
                    "league_prior_status"
                )
            ),
            "application_status": (
                diagnostics.get(
                    "application_status"
                )
            ),
            "candidate_digest": (
                diagnostics.get(
                    "runtime_candidate_digest"
                )
            ),
        })

    ready_count = status_counts["ready"]

    if (
        candidates
        and ready_count == len(candidates)
        and not rejected_requests
    ):
        status = "ready"
    elif candidates:
        status = "partial"
    else:
        status = "unavailable"

    diagnostics = {
        "schema_version": SCHEMA_VERSION,
        "status": status,
        "event_row_count": len(
            event_rows
        ),
        "raw_request_count": len(
            request_rows
        ),
        "unique_request_count": len(
            normalized_requests
        ),
        "duplicate_request_count": (
            duplicate_request_count
        ),
        "candidate_count": len(
            candidates
        ),
        "ready_candidate_count": (
            ready_count
        ),
        "partial_candidate_count": (
            status_counts["partial"]
        ),
        "unavailable_candidate_count": (
            status_counts["unavailable"]
        ),
        "candidate_status_counts": (
            status_counts
        ),
        "rejected_request_count": len(
            rejected_requests
        ),
        "rejected_requests": (
            rejected_requests
        ),
        "candidate_records": (
            candidate_records
        ),
        "candidate_identity": (
            "game_pk_pitcher_id"
        ),
        "cutoff_rule": (
            "events_strictly_before_each_game_date"
        ),
        "window_days": window_days,
        "single_shared_event_collection": True,
        "event_collection_reused": True,
        "calibrated_pooled_metrics_only": True,
        "segment_parameters_applied": False,
        "shadow_only": True,
        "production_authority": False,
        "production_authority_changed": False,
    }
    diagnostics["candidate_window_digest"] = (
        _digest({
            "candidate_records": (
                candidate_records
            ),
            "diagnostics": diagnostics,
        })
    )

    return {
        "candidates": candidates,
        "diagnostics": diagnostics,
    }

"""Attach canonical pitching-role evidence to projection rows."""

from __future__ import annotations

from collections import defaultdict
from copy import deepcopy
from typing import Any, Mapping


CANONICAL_PITCHER_PROJECTION_ROLE_ENRICHMENT_VERSION = (
    "canonical_pitcher_projection_role_enrichment_v1"
)


def enrich_canonical_pitcher_projection_roles(
    *,
    payload: Mapping[str, Any],
    appearance_audit: Mapping[str, Any],
) -> dict[str, Any]:
    """
    Attach observed canonical planned-role evidence to pitcher rows.

    Roles come only from the same-run canonical appearance audit.
    Missing or conflicting evidence remains explicit and is never
    inferred from workload, row order, or player identity.
    """

    if not isinstance(payload, Mapping):
        raise TypeError("payload must be a mapping")

    if not isinstance(appearance_audit, Mapping):
        raise TypeError(
            "appearance_audit must be a mapping"
        )

    result = deepcopy(dict(payload))
    players = result.get("players")

    if not isinstance(players, list):
        raise TypeError(
            "projection players must be a list"
        )

    records = appearance_audit.get("records")

    if not isinstance(records, (list, tuple)):
        raise TypeError(
            "appearance audit records must be a list or tuple"
        )

    evidence = defaultdict(set)
    invalid_record_count = 0

    for record in records:
        if not isinstance(record, Mapping):
            invalid_record_count += 1
            continue

        team_side = str(
            record.get("team_side") or ""
        ).strip()
        pitcher_id = str(
            record.get("pitcher_id") or ""
        ).strip()
        planned_role = str(
            record.get("planned_role") or ""
        ).strip()

        if (
            team_side not in {"away", "home"}
            or not pitcher_id
            or not planned_role
        ):
            invalid_record_count += 1
            continue

        evidence[
            (team_side, pitcher_id)
        ].add(planned_role)

    resolved_count = 0
    missing_count = 0
    conflicting_count = 0
    conflicting_pitcher_ids = []

    for row in players:
        if not isinstance(row, dict):
            raise TypeError(
                "projection player rows must be dictionaries"
            )

        if row.get("player_type") != "pitcher":
            continue

        team_side = str(
            row.get("team_side") or ""
        ).strip()
        pitcher_id = str(
            row.get("player_id") or ""
        ).strip()

        roles = evidence.get(
            (team_side, pitcher_id),
            set(),
        )

        if len(roles) == 1:
            row["pitcher_role"] = next(iter(roles))
            row[
                "pitcher_role_resolution_status"
            ] = "resolved"
            resolved_count += 1
        elif len(roles) > 1:
            row["pitcher_role"] = None
            row[
                "pitcher_role_resolution_status"
            ] = "conflicting"
            conflicting_count += 1
            conflicting_pitcher_ids.append(
                pitcher_id
            )
        else:
            row["pitcher_role"] = None
            row[
                "pitcher_role_resolution_status"
            ] = "missing"
            missing_count += 1

    result[
        "pitcher_role_enrichment_applied"
    ] = True
    result["pitcher_role_enrichment"] = {
        "schema_version": (
            CANONICAL_PITCHER_PROJECTION_ROLE_ENRICHMENT_VERSION
        ),
        "status": "observed",
        "source": (
            "canonical_pitcher_appearance_sequence_audit"
        ),
        "resolved_pitcher_count": resolved_count,
        "missing_pitcher_count": missing_count,
        "conflicting_pitcher_count": (
            conflicting_count
        ),
        "invalid_record_count": (
            invalid_record_count
        ),
        "conflicting_pitcher_ids": sorted(
            set(conflicting_pitcher_ids)
        ),
        "inference_used": False,
        "database_writes_performed": False,
        "production_authority_changed": False,
    }

    return result

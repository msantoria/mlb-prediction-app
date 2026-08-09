"""Activate canonical pitcher projection authority with rollback."""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
import os
from typing import Any


CANONICAL_PITCHER_PROJECTION_AUTHORITY_VERSION = (
    "canonical_pitcher_projection_authority_v1"
)

CANONICAL_PITCHER_PROJECTIONS_ENABLED_ENV = (
    "MLB_CANONICAL_PITCHER_PROJECTIONS_ENABLED"
)

CANONICAL_PITCHER_PROJECTION_SOURCE = (
    "canonical_event_driven_pitcher_projection"
)

_FALSE_VALUES = frozenset({
    "",
    "0",
    "false",
    "no",
    "off",
})


def canonical_pitcher_projections_enabled(
    value: Any = None,
) -> bool:
    """
    Resolve an explicit override, then the rollback environment flag.

    Canonical pitcher projection authority is active by default after
    this release. Setting the rollback flag to a false value preserves
    the existing legacy authority.
    """

    raw = (
        value
        if value is not None
        else os.getenv(
            CANONICAL_PITCHER_PROJECTIONS_ENABLED_ENV,
            "true",
        )
    )

    if isinstance(raw, bool):
        return raw

    return (
        str(raw).strip().lower()
        not in _FALSE_VALUES
    )


def _readiness_allows_activation(
    readiness: Mapping[str, Any],
) -> bool:
    decision = readiness.get("decision")

    if not isinstance(decision, Mapping):
        return False

    blockers = readiness.get("blockers")

    if not isinstance(blockers, (list, tuple)):
        return False

    return (
        readiness.get("status") == "ready"
        and readiness.get("audited") is True
        and not blockers
        and decision.get(
            "pitcher_projection_activation_allowed"
        )
        is True
        and decision.get(
            "production_activation_allowed"
        )
        is True
        and readiness.get(
            "database_writes_performed"
        )
        is False
        and readiness.get(
            "production_authority_changed"
        )
        is False
    )


def apply_canonical_pitcher_projection_authority(
    *,
    projection_rows: Mapping[str, Any],
    readiness: Mapping[str, Any],
    enabled: Any = None,
) -> dict[str, Any]:
    """
    Promote only ready canonical pitcher projection rows.

    Batter projection authority, game probabilities, simulation
    outcomes, database state, and the caller's inputs are unchanged.
    Missing or blocked readiness fails closed to legacy authority.
    """

    if not isinstance(projection_rows, Mapping):
        raise TypeError(
            "projection_rows must be a mapping"
        )

    if not isinstance(readiness, Mapping):
        raise TypeError(
            "readiness must be a mapping"
        )

    result = deepcopy(dict(projection_rows))
    players = result.get("players")

    if not isinstance(players, list):
        raise TypeError(
            "projection players must be a list"
        )

    activation_requested = (
        canonical_pitcher_projections_enabled(
            enabled
        )
    )
    readiness_allows_activation = (
        _readiness_allows_activation(
            readiness
        )
    )

    pitcher_rows = [
        row
        for row in players
        if (
            isinstance(row, Mapping)
            and row.get("player_type")
            == "pitcher"
        )
    ]
    batter_rows = [
        row
        for row in players
        if (
            isinstance(row, Mapping)
            and row.get("player_type")
            == "batter"
        )
    ]

    pitcher_rows_available = bool(
        pitcher_rows
    )

    activated = (
        activation_requested
        and readiness_allows_activation
        and pitcher_rows_available
    )

    if activated:
        fallback_reason = None
    elif not activation_requested:
        fallback_reason = (
            "rollback_flag_disabled"
        )
    elif not readiness_allows_activation:
        fallback_reason = (
            "pitcher_projection_readiness_blocked"
        )
    else:
        fallback_reason = (
            "pitcher_projection_rows_unavailable"
        )

    activated_pitcher_ids = []

    for row in players:
        if not isinstance(row, dict):
            raise TypeError(
                "projection player rows must be dictionaries"
            )

        if row.get("player_type") == "pitcher":
            row["authoritative"] = activated
            row["authoritative_source"] = (
                CANONICAL_PITCHER_PROJECTION_SOURCE
                if activated
                else "legacy"
            )
            row[
                "production_authority_changed"
            ] = activated

            if activated:
                activated_pitcher_ids.append(
                    str(
                        row.get("player_id")
                        or ""
                    )
                )

        elif row.get("player_type") == "batter":
            # Batter authority is deliberately outside 6SZ.
            row["authoritative"] = False
            row["authoritative_source"] = (
                "legacy"
            )
            row[
                "production_authority_changed"
            ] = False

    authority = {
        "schema_version": (
            CANONICAL_PITCHER_PROJECTION_AUTHORITY_VERSION
        ),
        "status": (
            "activated"
            if activated
            else "fallback"
        ),
        "activation_requested":
            activation_requested,
        "readiness_allows_activation":
            readiness_allows_activation,
        "production_activation": activated,
        "fallback_used": not activated,
        "fallback_reason": fallback_reason,
        "authority_scope": (
            "pitcher_rows_only"
        ),
        "pitcher_projection_count":
            len(pitcher_rows),
        "batter_projection_count":
            len(batter_rows),
        "activated_pitcher_ids": sorted(
            pitcher_id
            for pitcher_id
            in activated_pitcher_ids
            if pitcher_id
        ),
        "rollback_environment_variable": (
            CANONICAL_PITCHER_PROJECTIONS_ENABLED_ENV
        ),
        "database_writes_performed": False,
        "production_authority_changed":
            activated,
        "authoritative_source": (
            CANONICAL_PITCHER_PROJECTION_SOURCE
            if activated
            else "legacy"
        ),
    }

    result[
        "pitcher_projection_authority"
    ] = authority
    result[
        "pitcher_projections_authoritative"
    ] = activated
    result[
        "batter_projections_authoritative"
    ] = False
    result["authority_scope"] = (
        "mixed"
        if activated
        else "legacy"
    )

    # The complete player payload is mixed when only pitchers activate.
    result["authoritative"] = False
    result["authoritative_source"] = (
        "mixed"
        if activated
        else "legacy"
    )

    return result

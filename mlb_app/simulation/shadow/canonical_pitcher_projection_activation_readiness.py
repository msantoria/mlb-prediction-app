"""Audit canonical pitcher projection activation readiness."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


SCHEMA_VERSION = (
    "canonical_pitcher_projection_activation_"
    "readiness_v1"
)

PRIMARY_WORKLOAD_ROLES = frozenset({
    "starter",
    "opener",
    "bulk_follower",
    "tandem_primary",
    "tandem_secondary",
})

ORDERED_DISTRIBUTION_FIELDS = (
    "minimum",
    "p10",
    "median",
    "p90",
    "maximum",
)


def _mapping(value: Any) -> Mapping[str, Any]:
    return (
        value
        if isinstance(value, Mapping)
        else {}
    )


def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None

    if isinstance(value, (int, float)):
        return float(value)

    return None


def _metric_summary(
    row: Mapping[str, Any],
    metric_name: str,
) -> Mapping[str, Any]:
    metrics = _mapping(row.get("metrics"))
    metric = _mapping(metrics.get(metric_name))

    if not metric:
        return {}

    return _mapping(
        metric.get("summary", metric)
    )


def _distribution_valid(
    summary: Mapping[str, Any],
) -> bool:
    ordered = tuple(
        _number(summary.get(field_name))
        for field_name
        in ORDERED_DISTRIBUTION_FIELDS
    )

    if any(value is None for value in ordered):
        return False

    values = tuple(
        value
        for value in ordered
        if value is not None
    )

    if any(value < 0 for value in values):
        return False

    if any(
        left > right
        for left, right
        in zip(values, values[1:])
    ):
        return False

    mean = _number(summary.get("mean"))

    if mean is None:
        return False

    if not (
        values[0]
        <= mean
        <= values[-1]
    ):
        return False

    return True


def _has_workload_spread(
    summary: Mapping[str, Any],
) -> bool:
    minimum = _number(
        summary.get("minimum")
    )
    maximum = _number(
        summary.get("maximum")
    )

    return (
        minimum is not None
        and maximum is not None
        and maximum > minimum
    )


def audit_canonical_pitcher_projection_activation_readiness(
    *,
    projection_rows: Mapping[str, Any],
    appearance_audit: Mapping[str, Any],
    role_and_innings_audit: Mapping[str, Any],
) -> dict[str, Any]:
    """
    Decide whether canonical pitcher projections have enough
    observed evidence for a later production-authority slice.

    This function does not mutate projections, simulation inputs,
    database state, or production authority.
    """

    if not isinstance(projection_rows, Mapping):
        raise TypeError(
            "projection_rows must be a mapping"
        )

    if not isinstance(appearance_audit, Mapping):
        raise TypeError(
            "appearance_audit must be a mapping"
        )

    if not isinstance(
        role_and_innings_audit,
        Mapping,
    ):
        raise TypeError(
            "role_and_innings_audit must be a mapping"
        )

    blockers = set()

    if (
        projection_rows.get("schema_version")
        != "canonical_player_projection_rows_v1"
    ):
        blockers.add(
            "projection_rows_unavailable"
        )

    simulation_count = _number(
        projection_rows.get("simulation_count")
    )

    if (
        simulation_count is None
        or simulation_count <= 0
    ):
        blockers.add(
            "projection_simulation_count_unavailable"
        )

    players = projection_rows.get("players")

    if not isinstance(players, list):
        players = []
        blockers.add(
            "projection_rows_unavailable"
        )

    pitchers = [
        row
        for row in players
        if (
            isinstance(row, Mapping)
            and row.get("player_type")
            == "pitcher"
        )
    ]

    if not pitchers:
        blockers.add(
            "pitcher_projection_rows_empty"
        )

    role_enrichment = _mapping(
        projection_rows.get(
            "pitcher_role_enrichment"
        )
    )

    if (
        projection_rows.get(
            "pitcher_role_enrichment_applied"
        )
        is not True
        or role_enrichment.get("status")
        != "observed"
    ):
        blockers.add(
            "pitcher_role_enrichment_not_ready"
        )

    if (
        role_enrichment.get("inference_used")
        is not False
        or role_enrichment.get(
            "missing_pitcher_count"
        )
        not in {0, 0.0}
        or role_enrichment.get(
            "conflicting_pitcher_count"
        )
        not in {0, 0.0}
        or role_enrichment.get(
            "invalid_record_count"
        )
        not in {0, 0.0}
    ):
        blockers.add(
            "pitcher_role_evidence_incomplete"
        )

    unresolved_pitcher_count = sum(
        row.get(
            "pitcher_role_resolution_status"
        )
        != "resolved"
        for row in pitchers
    )

    if unresolved_pitcher_count:
        blockers.add(
            "pitcher_role_evidence_incomplete"
        )

    appearance_anomalies = _mapping(
        appearance_audit.get(
            "anomaly_counts"
        )
    )

    if (
        appearance_audit.get("status")
        != "observed"
        or appearance_audit.get("audited")
        is not True
    ):
        blockers.add(
            "appearance_sequence_unavailable"
        )

    if appearance_anomalies:
        blockers.add(
            "appearance_sequence_anomalies"
        )

    if (
        appearance_audit.get(
            "starter_relief_detected"
        )
        is not False
    ):
        blockers.add(
            "starter_relief_detected"
        )

    role_anomalies = _mapping(
        role_and_innings_audit.get(
            "anomaly_counts"
        )
    )

    if (
        role_and_innings_audit.get("status")
        != "observed"
        or role_and_innings_audit.get(
            "audited"
        )
        is not True
    ):
        blockers.add(
            "role_and_innings_audit_unavailable"
        )

    if role_anomalies:
        blockers.add(
            "role_and_innings_anomalies"
        )

    if (
        _number(
            role_and_innings_audit.get(
                "role_attribution_complete_rate"
            )
        )
        != 1.0
    ):
        blockers.add(
            "role_attribution_incomplete"
        )

    invalid_distribution_pitcher_ids = []
    missing_distribution_pitcher_ids = []
    dynamic_workload_pitcher_ids = []

    for row in pitchers:
        pitcher_id = str(
            row.get("player_id") or ""
        )
        role = str(
            row.get("pitcher_role") or ""
        )
        outs_summary = _metric_summary(
            row,
            "outs_recorded",
        )

        if not outs_summary:
            missing_distribution_pitcher_ids.append(
                pitcher_id
            )
            continue

        if not _distribution_valid(
            outs_summary
        ):
            invalid_distribution_pitcher_ids.append(
                pitcher_id
            )
            continue

        if (
            role in PRIMARY_WORKLOAD_ROLES
            and _has_workload_spread(
                outs_summary
            )
        ):
            dynamic_workload_pitcher_ids.append(
                pitcher_id
            )

    if missing_distribution_pitcher_ids:
        blockers.add(
            "outs_distribution_unavailable"
        )

    if invalid_distribution_pitcher_ids:
        blockers.add(
            "outs_distribution_invalid"
        )

    primary_role_pitcher_count = sum(
        str(row.get("pitcher_role") or "")
        in PRIMARY_WORKLOAD_ROLES
        for row in pitchers
    )

    if (
        primary_role_pitcher_count > 0
        and not dynamic_workload_pitcher_ids
    ):
        blockers.add(
            "dynamic_workload_evidence_unavailable"
        )

    source_audits = (
        appearance_audit,
        role_and_innings_audit,
        role_enrichment,
    )

    if any(
        audit.get(
            "database_writes_performed"
        )
        is True
        for audit in source_audits
    ):
        blockers.add(
            "source_database_write_detected"
        )

    if any(
        audit.get(
            "production_authority_changed"
        )
        is True
        for audit in source_audits
    ):
        blockers.add(
            "source_production_authority_changed"
        )

    blockers = tuple(sorted(blockers))
    ready = not blockers

    return {
        "schema_version": SCHEMA_VERSION,
        "status": (
            "ready"
            if ready
            else "blocked"
        ),
        "audited": True,
        "simulation_count":
            simulation_count,
        "pitcher_projection_count":
            len(pitchers),
        "primary_role_pitcher_count":
            primary_role_pitcher_count,
        "resolved_role_count": (
            len(pitchers)
            - unresolved_pitcher_count
        ),
        "dynamic_workload_pitcher_count":
            len(dynamic_workload_pitcher_ids),
        "dynamic_workload_pitcher_ids":
            sorted(
                dynamic_workload_pitcher_ids
            ),
        "missing_distribution_pitcher_ids":
            sorted(
                missing_distribution_pitcher_ids
            ),
        "invalid_distribution_pitcher_ids":
            sorted(
                invalid_distribution_pitcher_ids
            ),
        "appearance_anomaly_counts":
            dict(appearance_anomalies),
        "role_and_innings_anomaly_counts":
            dict(role_anomalies),
        "blockers": list(blockers),
        "safety_checks": {
            "projection_values_unchanged": True,
            "event_streams_unchanged": True,
            "pitching_plans_unchanged": True,
            "database_writes_performed": False,
            "production_authority_changed": False,
        },
        "decision": {
            "pitcher_projection_activation_allowed":
                ready,
            "production_activation_allowed":
                ready,
            "recommended_next_slice": (
                "activate_canonical_pitcher_"
                "projection_authority"
                if ready
                else (
                    "resolve_canonical_pitcher_"
                    "projection_readiness_blockers"
                )
            ),
        },
        "database_writes_performed": False,
        "production_authority_changed": False,
    }

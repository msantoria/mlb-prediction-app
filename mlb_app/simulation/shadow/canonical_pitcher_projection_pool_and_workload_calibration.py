"""Audit canonical pitcher pools and workload distributions."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import asdict
from typing import Any

from mlb_app.simulation.projections.aggregator import (
    summarize_values,
)


SCHEMA_VERSION = (
    "canonical_pitcher_projection_pool_"
    "and_workload_calibration_v1"
)

STARTER_LIKE_ROLES = frozenset({
    "starter",
    "probable_starter",
    "opener",
    "bulk_follower",
    "tandem_primary",
    "tandem_secondary",
})

PRIMARY_WORKLOAD_ROLES = frozenset({
    "starter",
    "opener",
    "bulk_follower",
    "tandem_primary",
    "tandem_secondary",
})


def _mapping(value: Any) -> Mapping[str, Any]:
    return (
        value
        if isinstance(value, Mapping)
        else {}
    )


def _sequence(value: Any) -> tuple[Any, ...]:
    if (
        isinstance(value, Sequence)
        and not isinstance(
            value,
            (str, bytes, bytearray),
        )
    ):
        return tuple(value)

    return ()


def _identifier(value: Any) -> str:
    return str(value or "").strip()


def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None

    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None

    return parsed


def _metric_summary(
    row: Mapping[str, Any],
    metric_name: str,
) -> Mapping[str, Any]:
    metrics = _mapping(row.get("metrics"))
    return _mapping(metrics.get(metric_name))


def _innings_summary(
    outs_summary: Mapping[str, Any],
) -> dict[str, float | int | None]:
    result: dict[str, float | int | None] = {}

    for key in (
        "count",
        "mean",
        "median",
        "p10",
        "p25",
        "p75",
        "p90",
        "minimum",
        "maximum",
    ):
        value = _number(outs_summary.get(key))

        if value is None:
            result[key] = None
        elif key == "count":
            result[key] = int(value)
        else:
            result[key] = value / 3.0

    return result


def _conditional_summary(
    records: Sequence[Mapping[str, Any]],
) -> tuple[
    dict[str, Any] | None,
    dict[str, Any] | None,
]:
    outs = [
        float(record["outs_recorded"])
        for record in records
        if _number(record.get("outs_recorded"))
        is not None
    ]

    if not outs:
        return None, None

    outs_summary = asdict(
        summarize_values(outs)
    )

    return (
        outs_summary,
        _innings_summary(outs_summary),
    )


def _eligibility_records(
    bullpen_discovery: Mapping[str, Any],
) -> dict[
    tuple[str, str],
    Mapping[str, Any],
]:
    index: dict[
        tuple[str, str],
        Mapping[str, Any],
    ] = {}

    for team_side in ("away", "home"):
        side = _mapping(
            bullpen_discovery.get(team_side)
        )
        eligibility = _mapping(
            side.get("eligibility")
        )

        for record in _sequence(
            eligibility.get("records")
        ):
            record = _mapping(record)
            pitcher_id = _identifier(
                record.get("pitcher_id")
            )

            if pitcher_id:
                index[
                    (team_side, pitcher_id)
                ] = record

    return index


def audit_canonical_pitcher_projection_pool_and_workload_calibration(
    *,
    projections: Mapping[str, Any],
    appearance_audit: Mapping[str, Any],
    bullpen_discovery: Mapping[str, Any],
) -> dict[str, Any]:
    """
    Audit same-run pitcher pool and workload evidence.

    This audit is observational. It does not alter pitcher pools,
    pitching plans, projection rows, event streams, or authority.
    It also does not infer closer, setup, or other typical bullpen
    roles when explicit evidence is unavailable.
    """

    if not isinstance(projections, Mapping):
        raise TypeError(
            "projections must be a mapping"
        )

    if not isinstance(appearance_audit, Mapping):
        raise TypeError(
            "appearance_audit must be a mapping"
        )

    if not isinstance(bullpen_discovery, Mapping):
        raise TypeError(
            "bullpen_discovery must be a mapping"
        )

    players = [
        row
        for row in _sequence(
            projections.get("players")
        )
        if (
            isinstance(row, Mapping)
            and row.get("player_type")
            == "pitcher"
        )
    ]

    trial_count_value = _number(
        appearance_audit.get("trial_count")
    )
    trial_count = (
        int(trial_count_value)
        if (
            trial_count_value is not None
            and trial_count_value > 0
        )
        else 0
    )

    appearance_index: dict[
        tuple[str, str],
        list[Mapping[str, Any]],
    ] = defaultdict(list)

    invalid_appearance_record_count = 0

    for raw_record in _sequence(
        appearance_audit.get("records")
    ):
        record = _mapping(raw_record)
        team_side = _identifier(
            record.get("team_side")
        )
        pitcher_id = _identifier(
            record.get("pitcher_id")
        )

        if (
            team_side not in {"away", "home"}
            or not pitcher_id
        ):
            invalid_appearance_record_count += 1
            continue

        appearance_index[
            (team_side, pitcher_id)
        ].append(record)

    eligibility_index = _eligibility_records(
        bullpen_discovery
    )

    pitcher_records = []
    pool_conflicts = []
    missing_eligibility_evidence = []
    missing_appearance_evidence = []
    historical_calibration_pitcher_ids = []
    primary_pitcher_ids = []

    for row in players:
        team_side = _identifier(
            row.get("team_side")
        )
        pitcher_id = _identifier(
            row.get("player_id")
        )
        key = (team_side, pitcher_id)

        planned_role = _identifier(
            row.get("pitcher_role")
        ) or None
        role_status = _identifier(
            row.get(
                "pitcher_role_resolution_status"
            )
        ) or None

        appearance_records = sorted(
            appearance_index.get(key, []),
            key=lambda record: (
                int(
                    _number(
                        record.get("trial_index")
                    )
                    or 0
                ),
                int(
                    _number(
                        record.get(
                            "appearance_index"
                        )
                    )
                    or 0
                ),
            ),
        )

        appeared_trial_ids = {
            int(record["trial_index"])
            for record in appearance_records
            if _number(
                record.get("trial_index")
            )
            is not None
        }
        appearance_count = len(
            appeared_trial_ids
        )
        appearance_rate = (
            appearance_count / trial_count
            if trial_count
            else None
        )

        eligibility = _mapping(
            eligibility_index.get(key)
        )
        evidence_present = bool(eligibility)
        evidence_valid = (
            eligibility.get("evidence_valid")
            is True
        )
        typical_role = (
            _identifier(
                eligibility.get("pitcher_role")
            )
            if evidence_valid
            else ""
        ) or None

        retained = (
            eligibility.get("retained")
            if evidence_present
            else None
        )
        planned_override = (
            eligibility.get("planned_pitcher")
            is True
        )

        if retained is True:
            availability_status = "eligible"
        elif retained is False:
            availability_status = "excluded"
        elif planned_role in PRIMARY_WORKLOAD_ROLES:
            availability_status = (
                "planned_primary_pitcher"
            )
        else:
            availability_status = "unknown"

        pool_anomalies = []

        if (
            retained is True
            and typical_role
            in STARTER_LIKE_ROLES
            and not planned_override
        ):
            pool_anomalies.append(
                "starter_like_pitcher_retained_"
                "in_bullpen"
            )
            pool_conflicts.append({
                "team_side": team_side,
                "pitcher_id": pitcher_id,
                "planned_role": planned_role,
                "typical_role": typical_role,
                "decision_reason":
                    eligibility.get(
                        "decision_reason"
                    ),
            })

        if (
            planned_role == "reliever"
            and not evidence_present
        ):
            missing_eligibility_evidence.append(
                pitcher_id
            )

        if not appearance_records:
            missing_appearance_evidence.append(
                pitcher_id
            )

        unconditional_outs = dict(
            _metric_summary(
                row,
                "outs_recorded",
            )
        )
        unconditional_innings = (
            _innings_summary(
                unconditional_outs
            )
        )

        (
            conditional_outs,
            conditional_innings,
        ) = _conditional_summary(
            appearance_records
        )

        calibration_status = (
            "requires_historical_calibration"
            if planned_role
            in PRIMARY_WORKLOAD_ROLES
            else (
                "conditional_distribution_observed"
                if conditional_outs is not None
                else "appearance_evidence_unavailable"
            )
        )

        if planned_role in PRIMARY_WORKLOAD_ROLES:
            primary_pitcher_ids.append(
                pitcher_id
            )
            historical_calibration_pitcher_ids.append(
                pitcher_id
            )

        pitcher_records.append({
            "team_side": team_side,
            "pitcher_id": pitcher_id,
            "planned_role": planned_role,
            "planned_role_resolution_status":
                role_status,
            "typical_bullpen_role": typical_role,
            "typical_role_inference_used": False,
            "eligibility_evidence_present":
                evidence_present,
            "eligibility_evidence_valid":
                evidence_valid,
            "eligibility_evidence_source":
                eligibility.get(
                    "evidence_source"
                ),
            "eligibility_decision_reason":
                eligibility.get(
                    "decision_reason"
                ),
            "planned_pitcher_override":
                planned_override,
            "availability_status":
                availability_status,
            "appearance_count":
                appearance_count,
            "appearance_rate":
                appearance_rate,
            "unconditional_outs":
                unconditional_outs,
            "unconditional_innings":
                unconditional_innings,
            "conditional_on_appearance_outs":
                conditional_outs,
            "conditional_on_appearance_innings":
                conditional_innings,
            "workload_calibration_status":
                calibration_status,
            "historical_calibration_available":
                False,
            "pool_anomalies":
                sorted(pool_anomalies),
        })

    blockers = []

    if not players:
        blockers.append(
            "pitcher_projection_rows_unavailable"
        )

    if trial_count <= 0:
        blockers.append(
            "simulation_trial_count_unavailable"
        )

    if appearance_audit.get("status") not in {
        "observed",
        "ready",
    }:
        blockers.append(
            "appearance_audit_unavailable"
        )

    status = (
        "blocked"
        if blockers
        else "observed"
    )

    return {
        "schema_version": SCHEMA_VERSION,
        "status": status,
        "audited": True,
        "blockers": sorted(blockers),
        "trial_count": trial_count,
        "pitcher_projection_count":
            len(players),
        "primary_pitcher_count":
            len(primary_pitcher_ids),
        "primary_pitcher_ids":
            sorted(set(primary_pitcher_ids)),
        "pool_conflict_count":
            len(pool_conflicts),
        "pool_conflicts": sorted(
            pool_conflicts,
            key=lambda record: (
                record["team_side"],
                record["pitcher_id"],
            ),
        ),
        "missing_eligibility_evidence_count":
            len(
                set(
                    missing_eligibility_evidence
                )
            ),
        "missing_eligibility_evidence_pitcher_ids":
            sorted(
                set(
                    missing_eligibility_evidence
                )
            ),
        "missing_appearance_evidence_count":
            len(
                set(
                    missing_appearance_evidence
                )
            ),
        "missing_appearance_evidence_pitcher_ids":
            sorted(
                set(
                    missing_appearance_evidence
                )
            ),
        "invalid_appearance_record_count":
            invalid_appearance_record_count,
        "historical_calibration_available":
            False,
        "historical_calibration_required":
            bool(
                historical_calibration_pitcher_ids
            ),
        "historical_calibration_pitcher_ids":
            sorted(
                set(
                    historical_calibration_pitcher_ids
                )
            ),
        "pitchers": sorted(
            pitcher_records,
            key=lambda record: (
                record["team_side"],
                record["planned_role"] or "",
                record["pitcher_id"],
            ),
        ),
        "interpretation": {
            "unconditional_distribution_includes_nonappearances":
                True,
            "conditional_distribution_excludes_nonappearances":
                True,
            "typical_bullpen_roles_inferred":
                False,
            "starter_p90_calibration_claimed":
                False,
        },
        "safety_checks": {
            "projection_values_unchanged": True,
            "pitcher_pools_unchanged": True,
            "pitching_plans_unchanged": True,
            "event_streams_unchanged": True,
            "database_writes_performed": False,
            "production_authority_changed": False,
        },
        "decision": {
            "pitcher_pool_change_allowed": False,
            "workload_calibration_change_allowed": False,
            "production_activation_allowed": False,
            "recommended_next_slice": (
                "correct_canonical_pitcher_pool_"
                "role_and_availability_evidence"
                if pool_conflicts
                else (
                    "calibrate_canonical_starter_"
                    "workload_distributions"
                )
            ),
        },
        "database_writes_performed": False,
        "production_authority_changed": False,
    }

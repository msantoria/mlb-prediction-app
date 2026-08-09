"""Reconcile canonical pitcher projection pools and role evidence."""

from __future__ import annotations

from collections import defaultdict
from copy import deepcopy
from typing import Any, Mapping


CANONICAL_PITCHER_POOL_ROLE_RECONCILIATION_VERSION = (
    "canonical_pitcher_projection_pool_role_reconciliation_v1"
)

PLANNED_PRIMARY_ROLES = frozenset({
    "starter",
    "opener",
    "bulk_follower",
    "tandem_primary",
    "tandem_secondary",
})

STARTER_LIKE_TYPICAL_ROLES = frozenset({
    "starter",
    "probable_starter",
})


def _text(value: Any) -> str:
    if value in (None, ""):
        return ""
    return str(value).strip()


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _side_evidence(
    bullpen_discovery: Mapping[str, Any],
) -> dict[str, dict[str, Any]]:
    evidence: dict[str, dict[str, Any]] = {}

    for team_side in ("away", "home"):
        side = _mapping(
            bullpen_discovery.get(team_side)
        )
        starter_id = _text(
            side.get("starter_id")
        )
        bullpen_ids = {
            _text(identifier)
            for identifier in (
                side.get("bullpen_pitcher_ids")
                or ()
            )
            if _text(identifier)
        }
        eligibility = _mapping(
            side.get("eligibility")
        )
        records = eligibility.get("records")

        record_index = {}

        if isinstance(records, (list, tuple)):
            for record in records:
                record = _mapping(record)
                pitcher_id = _text(
                    record.get("pitcher_id")
                )

                if pitcher_id:
                    record_index[pitcher_id] = (
                        dict(record)
                    )

        evidence[team_side] = {
            "starter_id": starter_id,
            "bullpen_pitcher_ids": bullpen_ids,
            "records": record_index,
        }

    return evidence


def _appearance_evidence(
    appearance_audit: Mapping[str, Any],
) -> tuple[int, dict[tuple[str, str], int]]:
    try:
        trial_count = int(
            appearance_audit.get("trial_count")
            or 0
        )
    except (TypeError, ValueError):
        trial_count = 0

    trials_by_pitcher = defaultdict(set)
    records = appearance_audit.get("records")

    if isinstance(records, (list, tuple)):
        for record in records:
            record = _mapping(record)
            team_side = _text(
                record.get("team_side")
            )
            pitcher_id = _text(
                record.get("pitcher_id")
            )
            trial_index = record.get("trial_index")

            if (
                team_side in {"away", "home"}
                and pitcher_id
                and trial_index is not None
            ):
                trials_by_pitcher[
                    (team_side, pitcher_id)
                ].add(trial_index)

    counts = {
        key: len(trials)
        for key, trials in trials_by_pitcher.items()
    }

    return trial_count, counts


def reconcile_canonical_pitcher_projection_pool_roles(
    *,
    payload: Mapping[str, Any],
    appearance_audit: Mapping[str, Any],
    bullpen_discovery: Mapping[str, Any],
) -> dict[str, Any]:
    """
    Attach explicit pitcher-pool, role, and availability evidence.

    Unknown active-roster evidence fails open. Rows are removed only
    when valid explicit evidence marks an unplanned pitcher ineligible.
    Typical bullpen roles are never inferred from row order, workload,
    appearance rate, or player identity.
    """

    if not isinstance(payload, Mapping):
        raise TypeError("payload must be a mapping")

    if not isinstance(appearance_audit, Mapping):
        raise TypeError(
            "appearance_audit must be a mapping"
        )

    if not isinstance(bullpen_discovery, Mapping):
        raise TypeError(
            "bullpen_discovery must be a mapping"
        )

    result = deepcopy(dict(payload))
    players = result.get("players")

    if not isinstance(players, list):
        raise TypeError(
            "projection players must be a list"
        )

    side_evidence = _side_evidence(
        bullpen_discovery
    )
    trial_count, appearance_counts = (
        _appearance_evidence(appearance_audit)
    )

    reconciled_players = []
    pitcher_count = 0
    explicitly_eligible_count = 0
    explicitly_ineligible_count = 0
    unknown_availability_count = 0
    planned_primary_count = 0
    role_conflict_count = 0
    excluded_pitcher_ids = []
    role_conflict_pitcher_ids = []

    for source_row in players:
        if not isinstance(source_row, Mapping):
            raise TypeError(
                "projection player rows must be mappings"
            )

        row = deepcopy(dict(source_row))

        if row.get("player_type") != "pitcher":
            reconciled_players.append(row)
            continue

        pitcher_count += 1
        team_side = _text(
            row.get("team_side")
        )
        pitcher_id = _text(
            row.get("player_id")
        )
        planned_role = _text(
            row.get("pitcher_role")
        )
        side = side_evidence.get(
            team_side,
            {
                "starter_id": "",
                "bullpen_pitcher_ids": set(),
                "records": {},
            },
        )
        eligibility = _mapping(
            side["records"].get(pitcher_id)
        )

        evidence_valid = (
            eligibility.get("evidence_valid")
            is True
        )
        evidence_status = (
            _text(
                eligibility.get(
                    "evidence_status"
                )
            ).lower()
            if evidence_valid
            else "unknown"
        )
        typical_role = (
            _text(
                eligibility.get("pitcher_role")
            ).lower()
            if evidence_valid
            else ""
        )

        if typical_role == "unknown":
            typical_role = ""

        planned_primary = (
            planned_role in PLANNED_PRIMARY_ROLES
            or (
                pitcher_id
                and pitcher_id
                == side["starter_id"]
            )
            or (
                eligibility.get(
                    "planned_pitcher"
                )
                is True
            )
        )

        if planned_primary:
            availability_status = (
                "planned_primary_pitcher"
            )
            membership_status = (
                "included_explicit_pitching_plan"
            )
            planned_primary_count += 1
            include = True
        elif (
            evidence_valid
            and evidence_status == "ineligible"
        ):
            availability_status = (
                "explicitly_ineligible"
            )
            membership_status = (
                "excluded_explicitly_ineligible"
            )
            explicitly_ineligible_count += 1
            include = False
        elif (
            evidence_valid
            and evidence_status == "eligible"
        ):
            availability_status = (
                "explicitly_eligible"
            )
            membership_status = (
                "included_explicitly_eligible"
            )
            explicitly_eligible_count += 1
            include = True
        else:
            availability_status = (
                "active_roster_candidate_unknown"
                if pitcher_id
                in side["bullpen_pitcher_ids"]
                else "availability_evidence_unknown"
            )
            membership_status = (
                "included_unknown_evidence_fail_open"
            )
            unknown_availability_count += 1
            include = True

        if planned_role == "starter":
            projection_group = "starter"
        elif planned_role in {
            "opener",
            "bulk_follower",
            "tandem_primary",
            "tandem_secondary",
        }:
            projection_group = "opener_bulk"
        elif planned_role == "reliever":
            projection_group = "bullpen"
        else:
            projection_group = "unresolved"

        role_conflict = (
            include
            and planned_role == "reliever"
            and typical_role
            in STARTER_LIKE_TYPICAL_ROLES
        )

        if role_conflict:
            taxonomy_status = "conflicting"
            role_conflict_count += 1
            role_conflict_pitcher_ids.append(
                pitcher_id
            )
        elif typical_role or planned_primary:
            taxonomy_status = "resolved"
        else:
            taxonomy_status = "unresolved"

        appearance_count = appearance_counts.get(
            (team_side, pitcher_id),
            0,
        )
        appearance_probability = (
            appearance_count / trial_count
            if trial_count > 0
            else None
        )

        row[
            "pitcher_projection_group"
        ] = projection_group
        row[
            "planned_pitcher_role"
        ] = planned_role or None
        row[
            "typical_bullpen_role"
        ] = typical_role or None
        row[
            "typical_role_inference_used"
        ] = False
        row[
            "game_availability_status"
        ] = availability_status
        row[
            "pitcher_pool_membership_status"
        ] = membership_status
        row[
            "pitcher_role_taxonomy_status"
        ] = taxonomy_status
        row[
            "appearance_count"
        ] = appearance_count
        row[
            "appearance_probability"
        ] = appearance_probability

        if include:
            reconciled_players.append(row)
        else:
            excluded_pitcher_ids.append(
                pitcher_id
            )

    result["players"] = reconciled_players
    result[
        "pitcher_pool_role_reconciliation_applied"
    ] = True
    result[
        "pitcher_pool_role_reconciliation"
    ] = {
        "schema_version": (
            CANONICAL_PITCHER_POOL_ROLE_RECONCILIATION_VERSION
        ),
        "status": "reconciled",
        "source": (
            "canonical_pitching_plan_appearance_and_"
            "explicit_bullpen_eligibility"
        ),
        "pitcher_projection_count": pitcher_count,
        "included_pitcher_count": (
            pitcher_count
            - explicitly_ineligible_count
        ),
        "excluded_pitcher_count": (
            explicitly_ineligible_count
        ),
        "excluded_pitcher_ids": sorted(
            set(excluded_pitcher_ids)
        ),
        "planned_primary_pitcher_count": (
            planned_primary_count
        ),
        "explicitly_eligible_pitcher_count": (
            explicitly_eligible_count
        ),
        "explicitly_ineligible_pitcher_count": (
            explicitly_ineligible_count
        ),
        "unknown_availability_pitcher_count": (
            unknown_availability_count
        ),
        "role_conflict_count": role_conflict_count,
        "role_conflict_pitcher_ids": sorted(
            set(role_conflict_pitcher_ids)
        ),
        "trial_count": trial_count,
        "typical_role_inference_used": False,
        "unknown_evidence_fails_open": True,
        "explicit_plans_take_precedence": True,
        "workload_calibration_changed": False,
        "game_probability_authority_changed": False,
        "database_writes_performed": False,
        "production_authority_changed": (
            explicitly_ineligible_count > 0
        ),
    }

    return result

"""Audit canonical pregame pitcher evidence source coverage."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from typing import Any

from .bullpen_discovery import (
    CanonicalShadowBullpenDiscovery,
)


SCHEMA_VERSION = (
    "canonical_pregame_pitcher_evidence_"
    "source_coverage_v1"
)

SCHEDULED_STARTER_SOURCE = (
    "mlb_stats_probablePitcher"
)

PITCHING_PLAN_SOURCE = (
    "canonical_pregame_pitching_plan"
)

TYPICAL_BULLPEN_ROLES = frozenset({
    "closer",
    "setup",
    "middle_reliever",
    "long_reliever",
})


def _rate(
    numerator: int,
    denominator: int,
) -> float:
    if denominator <= 0:
        return 0.0

    return round(
        numerator / denominator,
        6,
    )


def _matchup_source(
    matchup: Mapping[str, Any],
    *,
    side: str,
) -> tuple[str, str | None]:
    status = str(
        matchup.get(f"{side}_pitcher_status")
        or "missing"
    ).strip().lower()
    source_value = matchup.get(
        f"{side}_pitcher_source"
    )
    source = (
        str(source_value).strip()
        if source_value not in {None, ""}
        else None
    )

    return status, source


def _side_evidence(
    discovery: CanonicalShadowBullpenDiscovery,
    *,
    side: str,
) -> tuple[Any, Mapping[str, Any]]:
    side_discovery = getattr(
        discovery,
        side,
    )
    materialization = (
        side_discovery.pregame_evidence
    )

    if materialization is None:
        return side_discovery, {}

    evidence = (
        materialization.evidence_by_pitcher_id
    )

    if not isinstance(evidence, Mapping):
        return side_discovery, {}

    return side_discovery, evidence


def _audit_side(
    *,
    side: str,
    matchup: Mapping[str, Any],
    discovery: CanonicalShadowBullpenDiscovery,
) -> dict[str, Any]:
    side_discovery, evidence = _side_evidence(
        discovery,
        side=side,
    )
    starter_status, starter_source = (
        _matchup_source(
            matchup,
            side=side,
        )
    )
    starter_id = (
        side_discovery.starter_id
    )

    starter_source_valid = (
        starter_id is not None
        and starter_status == "probable"
        and starter_source
        == SCHEDULED_STARTER_SOURCE
    )

    active_roster_pitcher_count = len(
        evidence
    )

    if (
        starter_id is not None
        and starter_id not in evidence
    ):
        active_roster_pitcher_count += 1

    bullpen_candidate_count = len(
        side_discovery.bullpen_pitcher_ids
    )

    provider_evidence_count = 0
    valid_provider_evidence_count = 0
    explicit_availability_count = 0
    typical_role_count = 0
    unknown_evidence_count = 0
    invalid_evidence_count = 0
    source_counts = Counter()
    role_counts = Counter()
    status_counts = Counter()

    for pitcher_id, raw_record in (
        evidence.items()
    ):
        if not isinstance(raw_record, Mapping):
            invalid_evidence_count += 1
            continue

        source_value = raw_record.get("source")
        source = (
            str(source_value).strip()
            if source_value not in {None, ""}
            else None
        )
        status = str(
            raw_record.get("status")
            or "unknown"
        ).strip().lower()
        role = str(
            raw_record.get("role")
            or "unknown"
        ).strip().lower()
        valid = (
            raw_record.get("evidence_valid")
            is True
        )

        status_counts[status] += 1
        role_counts[role] += 1

        if source is not None:
            source_counts[source] += 1

        if (
            source is not None
            and source != PITCHING_PLAN_SOURCE
        ):
            provider_evidence_count += 1

            if valid:
                valid_provider_evidence_count += 1

                if status in {
                    "eligible",
                    "ineligible",
                }:
                    explicit_availability_count += 1

                if role in TYPICAL_BULLPEN_ROLES:
                    typical_role_count += 1

        if status == "unknown":
            unknown_evidence_count += 1

        if not valid:
            invalid_evidence_count += 1

    materialization = (
        side_discovery.pregame_evidence
    )
    materialization_diagnostics = (
        materialization.diagnostics
        if materialization is not None
        and isinstance(
            materialization.diagnostics,
            Mapping,
        )
        else {}
    )

    return {
        "team_side": side,
        "scheduled_starter_present": (
            starter_id is not None
        ),
        "scheduled_starter_status": (
            starter_status
        ),
        "scheduled_starter_source": (
            starter_source
        ),
        "scheduled_starter_source_valid": (
            starter_source_valid
        ),
        "active_roster_pitcher_count": (
            active_roster_pitcher_count
        ),
        "bullpen_candidate_count": (
            bullpen_candidate_count
        ),
        "materialization_available": (
            materialization is not None
        ),
        "provider_evidence_count": (
            provider_evidence_count
        ),
        "valid_provider_evidence_count": (
            valid_provider_evidence_count
        ),
        "explicit_availability_count": (
            explicit_availability_count
        ),
        "typical_role_count": (
            typical_role_count
        ),
        "unknown_evidence_count": (
            unknown_evidence_count
        ),
        "invalid_evidence_count": (
            invalid_evidence_count
        ),
        "stale_observation_count": int(
            materialization_diagnostics.get(
                "stale_observation_count"
            )
            or 0
        ),
        "conflicting_pitcher_count": int(
            materialization_diagnostics.get(
                "conflicting_pitcher_count"
            )
            or 0
        ),
        "provider_evidence_coverage_rate": (
            _rate(
                valid_provider_evidence_count,
                bullpen_candidate_count,
            )
        ),
        "explicit_availability_coverage_rate": (
            _rate(
                explicit_availability_count,
                bullpen_candidate_count,
            )
        ),
        "typical_role_coverage_rate": (
            _rate(
                typical_role_count,
                bullpen_candidate_count,
            )
        ),
        "source_counts": dict(
            sorted(source_counts.items())
        ),
        "role_counts": dict(
            sorted(role_counts.items())
        ),
        "status_counts": dict(
            sorted(status_counts.items())
        ),
        "pitcher_identifiers_exposed": False,
    }


def audit_canonical_pregame_pitcher_evidence_source_coverage(
    *,
    matchup: Mapping[str, Any],
    bullpen_discovery: CanonicalShadowBullpenDiscovery,
) -> dict[str, Any]:
    """
    Audit source coverage without changing pitcher evidence.

    Active-roster membership is not interpreted as game availability.
    Simulation usage, workload, roster order, and news keywords are not
    treated as explicit role or availability evidence.
    """

    if not isinstance(matchup, Mapping):
        raise TypeError(
            "matchup must be a mapping"
        )

    if not isinstance(
        bullpen_discovery,
        CanonicalShadowBullpenDiscovery,
    ):
        raise TypeError(
            "bullpen_discovery must be a canonical "
            "shadow bullpen discovery"
        )

    away = _audit_side(
        side="away",
        matchup=matchup,
        discovery=bullpen_discovery,
    )
    home = _audit_side(
        side="home",
        matchup=matchup,
        discovery=bullpen_discovery,
    )

    sides = (away, home)

    scheduled_starter_count = sum(
        int(side["scheduled_starter_present"])
        for side in sides
    )
    scheduled_starter_source_valid_count = sum(
        int(
            side[
                "scheduled_starter_source_valid"
            ]
        )
        for side in sides
    )
    bullpen_candidate_count = sum(
        side["bullpen_candidate_count"]
        for side in sides
    )
    valid_provider_evidence_count = sum(
        side["valid_provider_evidence_count"]
        for side in sides
    )
    explicit_availability_count = sum(
        side["explicit_availability_count"]
        for side in sides
    )
    typical_role_count = sum(
        side["typical_role_count"]
        for side in sides
    )
    unknown_evidence_count = sum(
        side["unknown_evidence_count"]
        for side in sides
    )
    invalid_evidence_count = sum(
        side["invalid_evidence_count"]
        for side in sides
    )
    stale_observation_count = sum(
        side["stale_observation_count"]
        for side in sides
    )
    conflicting_pitcher_count = sum(
        side["conflicting_pitcher_count"]
        for side in sides
    )

    blockers = []

    if (
        scheduled_starter_source_valid_count
        < scheduled_starter_count
    ):
        blockers.append(
            "scheduled_starter_source_incomplete"
        )

    if (
        bullpen_candidate_count > 0
        and explicit_availability_count
        < bullpen_candidate_count
    ):
        blockers.append(
            "bullpen_availability_source_incomplete"
        )

    if (
        bullpen_candidate_count > 0
        and typical_role_count
        < bullpen_candidate_count
    ):
        blockers.append(
            "typical_bullpen_role_source_incomplete"
        )

    if stale_observation_count > 0:
        blockers.append(
            "stale_pregame_evidence_observed"
        )

    if conflicting_pitcher_count > 0:
        blockers.append(
            "conflicting_pregame_evidence_observed"
        )

    provider_integration_ready = (
        len(blockers) == 0
        and bullpen_candidate_count > 0
    )

    status = (
        "ready"
        if provider_integration_ready
        else "coverage_gaps_observed"
    )

    return {
        "schema_version": SCHEMA_VERSION,
        "status": status,
        "audited": True,
        "game_pk": (
            matchup.get("game_pk")
            or matchup.get("gamePk")
        ),
        "game_time_present": bool(
            matchup.get("game_time")
        ),
        "away": away,
        "home": home,
        "scheduled_starter_count": (
            scheduled_starter_count
        ),
        "scheduled_starter_source_valid_count": (
            scheduled_starter_source_valid_count
        ),
        "scheduled_starter_source_coverage_rate": (
            _rate(
                scheduled_starter_source_valid_count,
                scheduled_starter_count,
            )
        ),
        "bullpen_candidate_count": (
            bullpen_candidate_count
        ),
        "valid_provider_evidence_count": (
            valid_provider_evidence_count
        ),
        "provider_evidence_coverage_rate": (
            _rate(
                valid_provider_evidence_count,
                bullpen_candidate_count,
            )
        ),
        "explicit_availability_count": (
            explicit_availability_count
        ),
        "explicit_availability_coverage_rate": (
            _rate(
                explicit_availability_count,
                bullpen_candidate_count,
            )
        ),
        "typical_role_count": (
            typical_role_count
        ),
        "typical_role_coverage_rate": (
            _rate(
                typical_role_count,
                bullpen_candidate_count,
            )
        ),
        "unknown_evidence_count": (
            unknown_evidence_count
        ),
        "invalid_evidence_count": (
            invalid_evidence_count
        ),
        "stale_observation_count": (
            stale_observation_count
        ),
        "conflicting_pitcher_count": (
            conflicting_pitcher_count
        ),
        "blockers": sorted(set(blockers)),
        "decision": {
            "provider_integration_ready": (
                provider_integration_ready
            ),
            "production_activation_allowed": False,
            "recommended_next_slice": (
                "source_canonical_pregame_"
                "bullpen_evidence"
            ),
        },
        "source_capabilities": {
            "mlb_stats_probable_pitcher": {
                "scheduled_starter_supported": True,
                "game_availability_supported": False,
                "typical_bullpen_role_supported": False,
            },
            "mlb_stats_active_roster": {
                "active_roster_membership_supported": True,
                "game_availability_supported": False,
                "typical_bullpen_role_supported": False,
            },
        },
        "interpretation": {
            "active_roster_membership_is_not_game_availability":
                True,
            "news_keywords_are_not_structured_evidence":
                True,
            "simulation_usage_is_not_pregame_evidence":
                True,
            "workload_is_not_role_evidence": True,
            "roster_order_is_not_role_evidence": True,
            "unknown_evidence_fails_open": True,
        },
        "safety_checks": {
            "pitcher_evidence_unchanged": True,
            "pitcher_pools_unchanged": True,
            "pitching_plans_unchanged": True,
            "projection_values_unchanged": True,
            "game_probabilities_unchanged": True,
            "database_writes_performed": False,
            "production_authority_changed": False,
        },
        "database_writes_performed": False,
        "production_authority_changed": False,
    }

"""Evidence-backed canonical pitcher typical-role materialization."""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Mapping, Sequence


SCHEMA_VERSION = (
    "canonical_pitcher_typical_role_evidence_v1"
)

TYPICAL_ROLES = frozenset({
    "starter",
    "opener",
    "bulk_follower",
    "swingman",
    "closer",
    "setup",
    "middle_reliever",
    "long_reliever",
    "unknown",
})

PLANNED_GAME_ROLES = frozenset({
    "starter",
    "probable_starter",
    "opener",
    "bulk_follower",
    "tandem_primary",
    "tandem_secondary",
})


def _identifier(value: Any) -> str | None:
    if value in (None, "") or isinstance(value, bool):
        return None

    normalized = str(value).strip()
    return normalized or None


def _nonnegative_int(value: Any) -> int | None:
    if value in (None, "") or isinstance(value, bool):
        return None

    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None

    return parsed if parsed >= 0 else None


def _number(
    mapping: Mapping[str, Any],
    *keys: str,
) -> int | None:
    for key in keys:
        parsed = _nonnegative_int(mapping.get(key))

        if parsed is not None:
            return parsed

    return None


def _pitcher_id(record: Mapping[str, Any]) -> str | None:
    return _identifier(
        record.get("mlb_player_id")
        or record.get("player_id")
        or record.get("pitcher_id")
        or record.get("id")
    )


def _history_record(
    history_by_pitcher_id: Mapping[Any, Any],
    pitcher_id: str,
) -> Mapping[str, Any]:
    direct = history_by_pitcher_id.get(pitcher_id)

    if isinstance(direct, Mapping):
        return direct

    try:
        numeric = int(pitcher_id)
    except (TypeError, ValueError):
        return {}

    numeric_record = history_by_pitcher_id.get(numeric)
    return (
        numeric_record
        if isinstance(numeric_record, Mapping)
        else {}
    )


def _planned_record(
    planned_by_pitcher_id: Mapping[Any, Any],
    pitcher_id: str,
) -> dict[str, Any]:
    raw = planned_by_pitcher_id.get(pitcher_id)

    if raw is None:
        try:
            raw = planned_by_pitcher_id.get(
                int(pitcher_id)
            )
        except (TypeError, ValueError):
            raw = None

    if not isinstance(raw, Mapping):
        return {
            "role": None,
            "source": None,
            "status": "unavailable",
            "confirmed": False,
        }

    role = str(
        raw.get("role")
        or raw.get("pitcher_role")
        or ""
    ).strip().lower()
    source = (
        str(raw.get("source")).strip()
        if raw.get("source") not in {None, ""}
        else None
    )
    evidence_status = str(
        raw.get("evidence_status")
        or raw.get("status")
        or ""
    ).strip().lower()

    confirmed = (
        role in PLANNED_GAME_ROLES
        and source is not None
        and evidence_status
        in {"confirmed", "explicit", "planned"}
    )

    return {
        "role": role if confirmed else None,
        "source": source if confirmed else None,
        "status": (
            "confirmed"
            if confirmed
            else "invalid_or_unconfirmed"
        ),
        "confirmed": confirmed,
    }


def _classify_typical_role(
    record: Mapping[str, Any],
    history: Mapping[str, Any],
) -> dict[str, Any]:
    games_pitched = _number(
        record,
        "season_games_pitched",
        "games_pitched",
    )
    games_started = _number(
        record,
        "season_games_started",
        "games_started",
    )
    relief_appearances = _number(
        record,
        "season_relief_appearances",
        "relief_appearances",
    )
    saves = _number(
        record,
        "season_saves",
        "saves",
    )
    holds = _number(
        record,
        "season_holds",
        "holds",
    )
    games_finished = _number(
        record,
        "season_games_finished",
        "games_finished",
    )
    pitching_outs = _number(
        record,
        "season_pitching_outs",
        "pitching_outs",
        "outs",
    )

    short_start_count = _number(
        history,
        "short_start_count",
    ) or 0
    early_multi_inning_relief_count = _number(
        history,
        "early_multi_inning_relief_count",
        "bulk_follower_count",
    ) or 0
    observed_start_count = _number(
        history,
        "start_count",
        "games_started",
    )
    observed_relief_count = _number(
        history,
        "relief_appearance_count",
        "relief_appearances",
    )
    observed_relief_outs = _number(
        history,
        "relief_outs",
    )

    if observed_start_count is None:
        observed_start_count = games_started

    if observed_relief_count is None:
        observed_relief_count = relief_appearances

    if (
        games_pitched is None
        or games_started is None
        or relief_appearances is None
        or games_pitched <= 0
        or games_started + relief_appearances
        != games_pitched
    ):
        return {
            "typical_role": "unknown",
            "confidence": "unresolved",
            "source": None,
            "reason": "season_usage_evidence_incomplete",
            "inference_used": False,
        }

    start_count = observed_start_count or 0
    relief_count = observed_relief_count or 0

    short_start_rate = (
        short_start_count / start_count
        if start_count > 0
        else 0.0
    )
    bulk_rate = (
        early_multi_inning_relief_count
        / relief_count
        if relief_count > 0
        else 0.0
    )

    if (
        start_count >= 3
        and short_start_count >= 2
        and short_start_rate >= 0.60
    ):
        return {
            "typical_role": "opener",
            "confidence": (
                "high"
                if short_start_count >= 4
                else "medium"
            ),
            "source": (
                "mlb_stats_historical_"
                "appearance_sequence"
            ),
            "reason": "repeated_short_starts",
            "inference_used": True,
        }

    if (
        relief_count >= 3
        and early_multi_inning_relief_count >= 2
        and bulk_rate >= 0.30
    ):
        return {
            "typical_role": "bulk_follower",
            "confidence": (
                "high"
                if early_multi_inning_relief_count >= 4
                else "medium"
            ),
            "source": (
                "mlb_stats_historical_"
                "appearance_sequence"
            ),
            "reason": (
                "repeated_early_multi_inning_relief"
            ),
            "inference_used": True,
        }

    if (
        games_started >= 3
        and relief_appearances >= 3
        and 0.20
        <= games_started / games_pitched
        <= 0.80
    ):
        return {
            "typical_role": "swingman",
            "confidence": (
                "high"
                if games_pitched >= 15
                else "medium"
            ),
            "source": (
                "mlb_stats_season_pitching_usage"
            ),
            "reason": (
                "material_start_and_relief_usage"
            ),
            "inference_used": True,
        }

    if games_started >= relief_appearances:
        return {
            "typical_role": "starter",
            "confidence": (
                "high"
                if games_started >= 5
                else "medium"
            ),
            "source": (
                "mlb_stats_season_pitching_usage"
            ),
            "reason": "start_usage_dominant",
            "inference_used": True,
        }

    normalized_saves = saves or 0
    normalized_holds = holds or 0
    normalized_finished = games_finished or 0

    if (
        normalized_saves >= 5
        and (
            normalized_saves >= normalized_holds
            or normalized_finished
            / games_pitched >= 0.35
        )
    ):
        return {
            "typical_role": "closer",
            "confidence": (
                "high"
                if normalized_saves >= 10
                else "medium"
            ),
            "source": (
                "mlb_stats_season_leverage_usage"
            ),
            "reason": (
                "save_and_games_finished_usage"
            ),
            "inference_used": True,
        }

    if normalized_holds >= 5:
        return {
            "typical_role": "setup",
            "confidence": (
                "high"
                if normalized_holds >= 10
                else "medium"
            ),
            "source": (
                "mlb_stats_season_leverage_usage"
            ),
            "reason": "hold_usage",
            "inference_used": True,
        }

    relief_outs = (
        observed_relief_outs
        if observed_relief_outs is not None
        else pitching_outs
    )
    outs_per_relief_appearance = (
        relief_outs / relief_count
        if (
            relief_outs is not None
            and relief_count > 0
        )
        else None
    )

    if (
        relief_count >= 3
        and outs_per_relief_appearance is not None
        and outs_per_relief_appearance >= 4.5
    ):
        return {
            "typical_role": "long_reliever",
            "confidence": (
                "high"
                if relief_count >= 10
                else "medium"
            ),
            "source": (
                "mlb_stats_season_workload_usage"
            ),
            "reason": (
                "multi_inning_relief_workload"
            ),
            "inference_used": True,
        }

    return {
        "typical_role": "middle_reliever",
        "confidence": (
            "high"
            if relief_appearances >= 15
            else "medium"
            if relief_appearances >= 5
            else "low"
        ),
        "source": (
            "mlb_stats_season_pitching_usage"
        ),
        "reason": "relief_usage_without_specialized_role",
        "inference_used": True,
    }


def materialize_canonical_pitcher_role_evidence(
    *,
    active_roster_records: Any,
    historical_appearance_evidence_by_pitcher_id: (
        Mapping[Any, Any] | None
    ) = None,
    planned_role_evidence_by_pitcher_id: (
        Mapping[Any, Any] | None
    ) = None,
) -> dict[str, Any]:
    """
    Materialize typical and planned pitcher roles separately.

    Typical roles are evidence-backed historical classifications.
    Planned roles require explicit, confirmed pregame evidence.
    Historical inference never claims a pitcher is planned for
    today's opener or bulk-follower assignment.
    """

    if (
        not isinstance(active_roster_records, Sequence)
        or isinstance(
            active_roster_records,
            (str, bytes),
        )
    ):
        raise TypeError(
            "active_roster_records must be a sequence"
        )

    history = (
        historical_appearance_evidence_by_pitcher_id
        if isinstance(
            historical_appearance_evidence_by_pitcher_id,
            Mapping,
        )
        else {}
    )
    planned = (
        planned_role_evidence_by_pitcher_id
        if isinstance(
            planned_role_evidence_by_pitcher_id,
            Mapping,
        )
        else {}
    )

    evidence_by_pitcher_id = {}
    records = []
    role_counts = {}
    confidence_counts = {}
    planned_role_count = 0
    unresolved_pitcher_ids = []

    for raw_record in active_roster_records:
        if not isinstance(raw_record, Mapping):
            continue

        pitcher_id = _pitcher_id(raw_record)

        if pitcher_id is None:
            continue

        historical_record = _history_record(
            history,
            pitcher_id,
        )
        typical = _classify_typical_role(
            raw_record,
            historical_record,
        )
        planned_record = _planned_record(
            planned,
            pitcher_id,
        )

        if planned_record["confirmed"]:
            planned_role_count += 1

        if typical["typical_role"] == "unknown":
            unresolved_pitcher_ids.append(pitcher_id)

        role = typical["typical_role"]
        confidence = typical["confidence"]
        role_counts[role] = role_counts.get(role, 0) + 1
        confidence_counts[confidence] = (
            confidence_counts.get(confidence, 0)
            + 1
        )

        evidence = {
            "pitcher_id": pitcher_id,
            "typical_role": role,
            "typical_role_confidence": confidence,
            "typical_role_source": typical["source"],
            "typical_role_reason": typical["reason"],
            "typical_role_inference_used": (
                typical["inference_used"]
            ),
            "planned_game_role":
                planned_record["role"],
            "planned_game_role_status":
                planned_record["status"],
            "planned_game_role_source":
                planned_record["source"],
            "planned_role_inferred_from_history":
                False,
            "historical_short_start_count": (
                _number(
                    historical_record,
                    "short_start_count",
                )
                or 0
            ),
            "historical_bulk_follower_count": (
                _number(
                    historical_record,
                    "early_multi_inning_relief_count",
                    "bulk_follower_count",
                )
                or 0
            ),
        }
        evidence_by_pitcher_id[pitcher_id] = evidence
        records.append(deepcopy(evidence))

    records.sort(key=lambda row: row["pitcher_id"])

    return {
        "schema_version": SCHEMA_VERSION,
        "status": "materialized",
        "pitcher_count": len(records),
        "resolved_typical_role_count": (
            len(records) - len(unresolved_pitcher_ids)
        ),
        "unresolved_typical_role_count": len(
            unresolved_pitcher_ids
        ),
        "unresolved_pitcher_ids": sorted(
            unresolved_pitcher_ids
        ),
        "confirmed_planned_role_count":
            planned_role_count,
        "typical_role_counts": dict(
            sorted(role_counts.items())
        ),
        "confidence_counts": dict(
            sorted(confidence_counts.items())
        ),
        "evidence_by_pitcher_id":
            evidence_by_pitcher_id,
        "records": records,
        "interpretation": {
            "typical_role_is_historical": True,
            "planned_role_requires_explicit_evidence":
                True,
            "historical_role_never_claims_today_plan":
                True,
            "opener_bulk_history_uses_appearance_sequence":
                True,
        },
        "safety_checks": {
            "active_roster_records_unchanged": True,
            "planned_roles_not_inferred_from_history":
                True,
            "database_writes_performed": False,
            "production_authority_changed": False,
        },
        "database_writes_performed": False,
        "production_authority_changed": False,
    }

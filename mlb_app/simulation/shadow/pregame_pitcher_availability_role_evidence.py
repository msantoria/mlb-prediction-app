"""Materialize explicit canonical pregame pitcher evidence."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Mapping, Sequence


SCHEMA_VERSION = (
    "canonical_pregame_pitcher_availability_"
    "and_role_evidence_v1"
)

VALID_AVAILABILITY_STATUSES = frozenset({
    "eligible",
    "ineligible",
    "unknown",
})

VALID_PITCHER_ROLES = frozenset({
    "starter",
    "probable_starter",
    "opener",
    "bulk_follower",
    "tandem_primary",
    "tandem_secondary",
    "reliever",
    "long_reliever",
    "middle_reliever",
    "setup",
    "closer",
    "unknown",
})

PLAN_ROLE_BY_SEQUENCE_ROLE = {
    "starter": "starter",
    "probable_starter": "probable_starter",
    "opener": "opener",
    "bulk_follower": "bulk_follower",
    "tandem_primary": "tandem_primary",
    "tandem_secondary": "tandem_secondary",
}


@dataclass(frozen=True)
class CanonicalPregamePitcherEvidenceMaterialization:
    """Read-only materialized evidence for one team."""

    team_side: str
    evidence_by_pitcher_id: Mapping[
        str,
        Mapping[str, Any],
    ]
    planned_pitcher_ids: tuple[str, ...]
    diagnostics: Mapping[str, Any] = field(
        default_factory=dict
    )
    schema_version: str = SCHEMA_VERSION
    database_writes_performed: bool = False
    production_authority_changed: bool = False

    def __post_init__(self) -> None:
        if self.team_side not in {"away", "home"}:
            raise ValueError(
                "team_side must be away or home"
            )

        if self.schema_version != SCHEMA_VERSION:
            raise ValueError(
                "unsupported pregame pitcher evidence schema"
            )


def _identifier(value: Any) -> str | None:
    if value in (None, "") or isinstance(value, bool):
        return None

    text = str(value).strip()
    return text or None


def _identifiers(values: Any) -> tuple[str, ...]:
    if values is None:
        return ()

    if isinstance(values, (str, bytes)):
        candidates = (values,)
    elif isinstance(values, Sequence):
        candidates = tuple(values)
    else:
        candidates = (values,)

    result = []
    seen = set()

    for candidate in candidates:
        identifier = _identifier(candidate)

        if (
            identifier is not None
            and identifier not in seen
        ):
            result.append(identifier)
            seen.add(identifier)

    return tuple(result)


def _parse_time(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str) and value.strip():
        text = value.strip()

        if text.endswith("Z"):
            text = f"{text[:-1]}+00:00"

        try:
            parsed = datetime.fromisoformat(text)
        except ValueError:
            return None
    else:
        return None

    if parsed.tzinfo is None:
        return None

    return parsed.astimezone(timezone.utc)


def _normalized_as_of(value: Any) -> datetime:
    parsed = _parse_time(value)

    if parsed is None:
        raise ValueError(
            "as_of must be a timezone-aware datetime"
        )

    return parsed


def _provider_record(
    value: Any,
    *,
    as_of: datetime,
    maximum_age_seconds: int,
) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        return {
            "valid": False,
            "status": "unknown",
            "role": "unknown",
            "source": None,
            "observed_at": None,
            "reason": "invalid_evidence_record",
        }

    status = str(
        value.get("status") or "unknown"
    ).strip().lower()
    role = str(
        value.get("role") or "unknown"
    ).strip().lower()
    source = (
        str(value.get("source")).strip()
        if value.get("source") not in {None, ""}
        else None
    )
    observed_at = _parse_time(
        value.get("observed_at")
    )
    reason = (
        str(value.get("reason")).strip()
        if value.get("reason") not in {None, ""}
        else None
    )

    structurally_valid = (
        status in VALID_AVAILABILITY_STATUSES
        and role in VALID_PITCHER_ROLES
        and source is not None
        and observed_at is not None
    )

    if not structurally_valid:
        return {
            "valid": False,
            "status": "unknown",
            "role": "unknown",
            "source": source,
            "observed_at": (
                observed_at.isoformat()
                if observed_at is not None
                else None
            ),
            "reason": "invalid_evidence_record",
        }

    age_seconds = (
        as_of - observed_at
    ).total_seconds()

    if (
        age_seconds < 0
        or age_seconds > maximum_age_seconds
    ):
        return {
            "valid": False,
            "status": "unknown",
            "role": "unknown",
            "source": source,
            "observed_at": observed_at.isoformat(),
            "reason": "stale_or_future_evidence",
        }

    return {
        "valid": True,
        "status": status,
        "role": role,
        "source": source,
        "observed_at": observed_at.isoformat(),
        "reason": reason,
    }


def _plan_roles(
    *,
    scheduled_starter_id: str,
    pitching_plan: Mapping[str, Any] | None,
) -> dict[str, str]:
    roles = {
        scheduled_starter_id: "starter",
    }

    if not isinstance(pitching_plan, Mapping):
        return roles

    sequence = pitching_plan.get(
        "planned_sequence"
    )

    if not isinstance(sequence, Sequence) or isinstance(
        sequence,
        (str, bytes),
    ):
        return roles

    for record in sequence:
        if not isinstance(record, Mapping):
            continue

        pitcher_id = _identifier(
            record.get("pitcher_id")
        )
        role = str(
            record.get("role")
            or record.get("pitcher_role")
            or ""
        ).strip().lower()

        normalized_role = (
            PLAN_ROLE_BY_SEQUENCE_ROLE.get(role)
        )

        if (
            pitcher_id is not None
            and normalized_role is not None
        ):
            roles[pitcher_id] = normalized_role

    return roles


def materialize_canonical_pregame_pitcher_evidence(
    *,
    team_side: str,
    scheduled_starter_id: Any,
    active_roster_pitcher_ids: Any,
    as_of: Any,
    pitching_plan: Mapping[str, Any] | None = None,
    provider_observations: Any = (),
    maximum_age_seconds: int = 21600,
) -> CanonicalPregamePitcherEvidenceMaterialization:
    """
    Materialize explicit availability and role evidence.

    Pitching-plan evidence takes precedence. Provider observations
    require provenance and a fresh timestamp. Missing, malformed,
    stale, future, or conflicting evidence becomes unknown and
    therefore remains compatible with fail-open bullpen discovery.
    """

    if team_side not in {"away", "home"}:
        raise ValueError(
            "team_side must be away or home"
        )

    starter_id = _identifier(
        scheduled_starter_id
    )

    if starter_id is None:
        raise ValueError(
            "scheduled_starter_id is required"
        )

    if (
        isinstance(maximum_age_seconds, bool)
        or not isinstance(maximum_age_seconds, int)
        or maximum_age_seconds < 0
    ):
        raise ValueError(
            "maximum_age_seconds must be non-negative"
        )

    normalized_as_of = _normalized_as_of(as_of)
    roster_ids = _identifiers(
        active_roster_pitcher_ids
    )
    plan_roles = _plan_roles(
        scheduled_starter_id=starter_id,
        pitching_plan=pitching_plan,
    )

    if provider_observations is None:
        observations = ()
    elif (
        isinstance(provider_observations, Sequence)
        and not isinstance(
            provider_observations,
            (str, bytes),
        )
    ):
        observations = tuple(provider_observations)
    else:
        raise TypeError(
            "provider_observations must be a sequence"
        )

    observations_by_pitcher_id: dict[
        str,
        list[dict[str, Any]],
    ] = {}

    invalid_observation_count = 0
    stale_observation_count = 0

    for raw_record in observations:
        pitcher_id = (
            _identifier(raw_record.get("pitcher_id"))
            if isinstance(raw_record, Mapping)
            else None
        )
        record = _provider_record(
            raw_record,
            as_of=normalized_as_of,
            maximum_age_seconds=(
                maximum_age_seconds
            ),
        )

        if pitcher_id is None:
            invalid_observation_count += 1
            continue

        if not record["valid"]:
            if (
                record["reason"]
                == "stale_or_future_evidence"
            ):
                stale_observation_count += 1
            else:
                invalid_observation_count += 1

        observations_by_pitcher_id.setdefault(
            pitcher_id,
            [],
        ).append(record)

    ordered_pitcher_ids = list(roster_ids)

    for pitcher_id in plan_roles:
        if pitcher_id not in ordered_pitcher_ids:
            ordered_pitcher_ids.append(pitcher_id)

    evidence_by_pitcher_id = {}
    conflicting_pitcher_ids = []
    unknown_pitcher_ids = []
    plan_override_count = 0
    valid_provider_pitcher_count = 0

    for pitcher_id in ordered_pitcher_ids:
        planned_role = plan_roles.get(pitcher_id)

        if planned_role is not None:
            evidence_by_pitcher_id[pitcher_id] = {
                "status": "eligible",
                "role": planned_role,
                "source": (
                    "canonical_pregame_pitching_plan"
                ),
                "reason": (
                    "explicit_pitching_plan_assignment"
                ),
                "observed_at": (
                    normalized_as_of.isoformat()
                ),
                "evidence_valid": True,
                "plan_override": True,
            }
            plan_override_count += 1
            continue

        records = observations_by_pitcher_id.get(
            pitcher_id,
            [],
        )
        valid_records = [
            record
            for record in records
            if record["valid"]
        ]
        distinct_contracts = {
            (
                record["status"],
                record["role"],
            )
            for record in valid_records
        }

        if len(distinct_contracts) > 1:
            conflicting_pitcher_ids.append(
                pitcher_id
            )
            evidence_by_pitcher_id[pitcher_id] = {
                "status": "unknown",
                "role": "unknown",
                "source": None,
                "reason": (
                    "conflicting_provider_evidence"
                ),
                "observed_at": None,
                "evidence_valid": False,
                "plan_override": False,
            }
        elif len(valid_records) == 1 or (
            valid_records
            and len(distinct_contracts) == 1
        ):
            record = valid_records[-1]
            evidence_by_pitcher_id[pitcher_id] = {
                "status": record["status"],
                "role": record["role"],
                "source": record["source"],
                "reason": record["reason"],
                "observed_at": (
                    record["observed_at"]
                ),
                "evidence_valid": True,
                "plan_override": False,
            }
            valid_provider_pitcher_count += 1
        else:
            unknown_pitcher_ids.append(pitcher_id)
            evidence_by_pitcher_id[pitcher_id] = {
                "status": "unknown",
                "role": "unknown",
                "source": None,
                "reason": (
                    "pregame_evidence_unavailable"
                ),
                "observed_at": None,
                "evidence_valid": False,
                "plan_override": False,
            }

    planned_pitcher_ids = tuple(
        pitcher_id
        for pitcher_id in ordered_pitcher_ids
        if pitcher_id in plan_roles
    )

    diagnostics = {
        "schema_version": SCHEMA_VERSION,
        "status": "materialized",
        "team_side": team_side,
        "as_of": normalized_as_of.isoformat(),
        "maximum_age_seconds": maximum_age_seconds,
        "pitcher_count": len(ordered_pitcher_ids),
        "planned_pitcher_count": len(
            planned_pitcher_ids
        ),
        "plan_override_count": plan_override_count,
        "valid_provider_pitcher_count": (
            valid_provider_pitcher_count
        ),
        "unknown_pitcher_count": len(
            unknown_pitcher_ids
        ),
        "unknown_pitcher_ids": sorted(
            unknown_pitcher_ids
        ),
        "conflicting_pitcher_count": len(
            conflicting_pitcher_ids
        ),
        "conflicting_pitcher_ids": sorted(
            conflicting_pitcher_ids
        ),
        "invalid_observation_count": (
            invalid_observation_count
        ),
        "stale_observation_count": (
            stale_observation_count
        ),
        "unknown_evidence_fails_open": True,
        "typical_role_inference_used": False,
        "workload_inference_used": False,
        "roster_order_inference_used": False,
        "database_writes_performed": False,
        "production_authority_changed": False,
    }

    return (
        CanonicalPregamePitcherEvidenceMaterialization(
            team_side=team_side,
            evidence_by_pitcher_id=(
                evidence_by_pitcher_id
            ),
            planned_pitcher_ids=(
                planned_pitcher_ids
            ),
            diagnostics=diagnostics,
        )
    )

"""Deterministically enforce canonical bullpen eligibility evidence."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from typing import Any


SCHEMA_VERSION = (
    "canonical_bullpen_eligibility_v1"
)

VALID_EVIDENCE_STATUSES = frozenset({
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

EXPLICIT_BULLPEN_ROLES = frozenset({
    "reliever",
    "long_reliever",
    "middle_reliever",
    "setup",
    "closer",
})

STARTER_LIKE_ROLES = frozenset({
    "starter",
    "probable_starter",
})


def _identifier(value: Any) -> str | None:
    if value in (None, "") or isinstance(
        value,
        bool,
    ):
        return None

    try:
        parsed = int(value)
    except (TypeError, ValueError):
        text = str(value).strip()
        return text or None

    return str(parsed) if parsed > 0 else None


def _identifiers(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()

    if isinstance(value, (str, bytes)):
        values = (value,)
    elif isinstance(value, Sequence):
        values = tuple(value)
    else:
        try:
            values = tuple(value)
        except TypeError:
            values = (value,)

    result = []
    seen = set()

    for candidate in values:
        identifier = _identifier(candidate)
        if (
            identifier is not None
            and identifier not in seen
        ):
            result.append(identifier)
            seen.add(identifier)

    return tuple(result)


def _evidence_index(
    evidence_by_pitcher_id: (
        Mapping[Any, Any] | None
    ),
) -> dict[str, Any]:
    if evidence_by_pitcher_id is None:
        return {}

    if not isinstance(
        evidence_by_pitcher_id,
        Mapping,
    ):
        raise TypeError(
            "evidence_by_pitcher_id must be "
            "a mapping or None"
        )

    result = {}

    for raw_identifier, evidence in (
        evidence_by_pitcher_id.items()
    ):
        identifier = _identifier(
            raw_identifier
        )
        if identifier is not None:
            result[identifier] = evidence

    return result


def _evidence_record(
    value: Any,
) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        return {
            "valid": False,
            "status": "unknown",
            "role": "unknown",
            "source": None,
            "reason":
                "invalid_eligibility_evidence",
        }

    status = str(
        value.get("status") or "unknown"
    ).strip().lower()
    role = str(
        value.get("role") or "unknown"
    ).strip().lower()
    source = (
        str(value.get("source")).strip()
        if value.get("source") not in {
            None,
            "",
        }
        else None
    )
    reason = (
        str(value.get("reason")).strip()
        if value.get("reason") not in {
            None,
            "",
        }
        else None
    )

    valid = (
        status in VALID_EVIDENCE_STATUSES
        and role in VALID_PITCHER_ROLES
        and source is not None
    )

    if not valid:
        return {
            "valid": False,
            "status": "unknown",
            "role": (
                role
                if role in VALID_PITCHER_ROLES
                else "unknown"
            ),
            "source": source,
            "reason":
                "invalid_eligibility_evidence",
        }

    return {
        "valid": True,
        "status": status,
        "role": role,
        "source": source,
        "reason": reason,
    }


def enforce_canonical_bullpen_eligibility(
    *,
    candidate_pitcher_ids: Any,
    starter_id: Any,
    evidence_by_pitcher_id: (
        Mapping[Any, Any] | None
    ) = None,
    planned_pitcher_ids: Any = (),
    require_explicit_bullpen_membership: (
        bool
    ) = False,
) -> dict[str, Any]:
    """
    Filter a bullpen pool using explicit evidence only.

    Explicitly planned opener, bulk, or tandem pitchers are retained even
    when general role evidence classifies them as starters.

    When require_explicit_bullpen_membership is false, unknown evidence
    preserves the legacy fail-open behavior. When true, only valid,
    explicitly eligible bullpen roles are retained; unknown, invalid, and
    starter-like evidence fails closed.
    """

    if not isinstance(
        require_explicit_bullpen_membership,
        bool,
    ):
        raise TypeError(
            "require_explicit_bullpen_membership "
            "must be a bool"
        )

    candidates = _identifiers(
        candidate_pitcher_ids
    )
    normalized_starter = _identifier(
        starter_id
    )
    planned = set(
        _identifiers(planned_pitcher_ids)
    )
    evidence_index = _evidence_index(
        evidence_by_pitcher_id
    )

    eligible = []
    excluded = []
    records = []
    reason_counts = Counter()
    evidence_pitcher_count = 0
    valid_evidence_count = 0
    unknown_role_count = 0
    planned_override_count = 0
    strict_membership_excluded_count = 0
    starter_like_excluded_count = 0

    for pitcher_id in candidates:
        evidence_present = (
            pitcher_id in evidence_index
        )
        evidence = _evidence_record(
            evidence_index.get(pitcher_id)
        )

        if evidence_present:
            evidence_pitcher_count += 1
        if evidence["valid"]:
            valid_evidence_count += 1
        if evidence["role"] == "unknown":
            unknown_role_count += 1

        retained = True
        decision_reason = (
            "eligibility_evidence_unavailable"
        )

        if (
            normalized_starter is not None
            and pitcher_id == normalized_starter
        ):
            retained = False
            decision_reason = (
                "scheduled_starter_excluded"
            )
        elif pitcher_id in planned:
            retained = True
            decision_reason = (
                "explicit_pitching_plan_override"
            )
            planned_override_count += 1
        elif (
            evidence["valid"]
            and evidence["status"]
            == "ineligible"
        ):
            retained = False
            decision_reason = (
                evidence["reason"]
                or (
                    f"{evidence['role']}_"
                    "ineligible"
                )
            )
        elif (
            require_explicit_bullpen_membership
            and evidence["valid"]
            and evidence["status"]
            == "eligible"
            and evidence["role"]
            not in EXPLICIT_BULLPEN_ROLES
        ):
            retained = False
            strict_membership_excluded_count += 1

            if (
                evidence["role"]
                in STARTER_LIKE_ROLES
            ):
                starter_like_excluded_count += 1
                decision_reason = (
                    "starter_like_role_excluded"
                )
            else:
                decision_reason = (
                    "non_bullpen_role_excluded"
                )
        elif (
            evidence["valid"]
            and evidence["status"]
            == "eligible"
        ):
            retained = True
            decision_reason = (
                "explicitly_eligible"
            )
        elif require_explicit_bullpen_membership:
            retained = False
            strict_membership_excluded_count += 1
            decision_reason = (
                "explicit_bullpen_membership_unavailable"
            )
        elif evidence_present:
            retained = True
            decision_reason = (
                evidence["reason"]
                or "unknown_eligibility_retained"
            )

        reason_counts[decision_reason] += 1

        if retained:
            eligible.append(pitcher_id)
        else:
            excluded.append(pitcher_id)

        records.append({
            "pitcher_id": pitcher_id,
            "retained": retained,
            "decision_reason":
                decision_reason,
            "planned_pitcher": (
                pitcher_id in planned
            ),
            "evidence_present":
                evidence_present,
            "evidence_valid":
                evidence["valid"],
            "evidence_status":
                evidence["status"],
            "pitcher_role":
                evidence["role"],
            "evidence_source":
                evidence["source"],
        })

    candidate_count = len(candidates)
    evidence_complete = (
        candidate_count > 0
        and all(
            record["evidence_valid"]
            or record["planned_pitcher"]
            or (
                normalized_starter is not None
                and record["pitcher_id"]
                == normalized_starter
            )
            for record in records
        )
    )
    evidence_coverage_rate = (
        valid_evidence_count
        / candidate_count
        if candidate_count
        else 0.0
    )

    return {
        "schema_version": SCHEMA_VERSION,
        "status": (
            "enforced"
            if valid_evidence_count > 0
            else "fallback"
        ),
        "candidate_pitcher_ids": list(
            candidates
        ),
        "eligible_bullpen_pitcher_ids":
            eligible,
        "excluded_pitcher_ids": excluded,
        "candidate_pitcher_count":
            candidate_count,
        "eligible_pitcher_count":
            len(eligible),
        "excluded_pitcher_count":
            len(excluded),
        "evidence_pitcher_count":
            evidence_pitcher_count,
        "valid_evidence_count":
            valid_evidence_count,
        "unknown_role_count":
            unknown_role_count,
        "planned_override_count":
            planned_override_count,
        "strict_membership_excluded_count": (
            strict_membership_excluded_count
        ),
        "starter_like_excluded_count": (
            starter_like_excluded_count
        ),
        "require_explicit_bullpen_membership": (
            require_explicit_bullpen_membership
        ),
        "eligibility_evidence_complete":
            evidence_complete,
        "eligibility_evidence_coverage_rate":
            evidence_coverage_rate,
        "exclusion_reason_counts": dict(
            sorted(
                (
                    reason,
                    count,
                )
                for reason, count
                in reason_counts.items()
                if any(
                    (
                        not record["retained"]
                        and record[
                            "decision_reason"
                        ] == reason
                    )
                    for record in records
                )
            )
        ),
        "decision_reason_counts": dict(
            sorted(reason_counts.items())
        ),
        "records": records,
        "safety_checks": {
            "unknown_evidence_fails_open": (
                not require_explicit_bullpen_membership
            ),
            "unknown_evidence_fails_closed": (
                require_explicit_bullpen_membership
            ),
            "active_roster_membership_is_not_"
            "bullpen_membership": True,
            "workload_inference_used": False,
            "roster_order_inference_used": False,
            "appearance_rate_inference_used": False,
            "explicit_plans_take_precedence":
                True,
            "database_writes_performed": False,
            "production_authority_changed": False,
        },
        "decision": {
            "bullpen_filter_applied": (
                bool(excluded)
            ),
            "production_activation_allowed":
                False,
            "recommended_next_slice": (
                "materialize_pregame_pitching_plans"
            ),
        },
        "database_writes_performed": False,
        "production_authority_changed": False,
    }

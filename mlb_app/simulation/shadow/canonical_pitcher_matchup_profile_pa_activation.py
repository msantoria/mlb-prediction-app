"""Select audited pitcher-profile PA probabilities for production use.

The selector is fail closed. Production probabilities remain authoritative
unless activation is explicitly requested and the comparator payload satisfies
the pinned historical-evidence contract.
"""

from __future__ import annotations

import hashlib
import json
import math
from copy import deepcopy
from typing import Any, Mapping


SCHEMA_VERSION = (
    "canonical_pitcher_matchup_profile_pa_activation_v1"
)

APPROVED_ELIGIBILITY_DIGEST = (
    "c8f491ab1668da64de6bae4066b1e7a4"
    "62af68f1b4e74bba296a9546561cf9c4"
)
APPROVED_HISTORICAL_EVALUATION_DIGEST = (
    "b0197ea2a54ab4834ac6d1aed0e2b818"
    "5f0fe5006b2be841847d1481328a4160"
)
APPROVED_CROSS_SEASON_AUDIT_DIGEST = (
    "7f85e5340c1e20e3b634fc52b9720ce0"
    "0e97f720031fcba1354ed2b464da1260"
)


def _digest(value: Any) -> str:
    payload = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _mapping(
    value: Any,
) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return deepcopy(dict(value))
    return {}


def _probabilities(
    value: Any,
) -> dict[str, float] | None:
    if not isinstance(value, Mapping):
        return None

    normalized = {}

    for key, raw_value in value.items():
        if (
            isinstance(raw_value, bool)
            or not isinstance(
                raw_value,
                (int, float),
            )
        ):
            return None

        number = float(raw_value)

        if (
            not math.isfinite(number)
            or not 0.0 <= number <= 1.0
        ):
            return None

        normalized[str(key)] = number

    if not normalized:
        return None
    if not math.isclose(
        sum(normalized.values()),
        1.0,
        rel_tol=0.0,
        abs_tol=1e-9,
    ):
        return None

    return normalized


def select_canonical_pitcher_matchup_profile_pa_model(
    *,
    production_model: Mapping[str, Any],
    comparison: Mapping[str, Any],
    activation_requested: bool,
    eligibility_digest: str,
    historical_evaluation_digest: str,
    cross_season_audit_digest: str,
) -> dict[str, Any]:
    """Select production or audited candidate PA probabilities."""

    if not isinstance(
        activation_requested,
        bool,
    ):
        raise ValueError(
            "activation_requested_must_be_boolean"
        )

    production = _mapping(production_model)
    comparison_value = _mapping(comparison)
    production_probabilities = (
        _probabilities(
            production.get("probabilities")
        )
    )
    blockers = []

    if production_probabilities is None:
        blockers.append(
            "production_probabilities_invalid"
        )

    evidence_matches = {
        "eligibility_digest": (
            str(eligibility_digest)
            == APPROVED_ELIGIBILITY_DIGEST
        ),
        "historical_evaluation_digest": (
            str(historical_evaluation_digest)
            == APPROVED_HISTORICAL_EVALUATION_DIGEST
        ),
        "cross_season_audit_digest": (
            str(cross_season_audit_digest)
            == APPROVED_CROSS_SEASON_AUDIT_DIGEST
        ),
    }

    if activation_requested:
        for name, matched in (
            evidence_matches.items()
        ):
            if not matched:
                blockers.append(
                    f"{name}_not_approved"
                )

        if comparison_value.get(
            "status"
        ) != "ready":
            blockers.append(
                "candidate_comparison_not_ready"
            )
        if comparison_value.get(
            "executed"
        ) is not True:
            blockers.append(
                "candidate_comparison_not_executed"
            )
        if comparison_value.get(
            "production_inputs_unchanged"
        ) is not True:
            blockers.append(
                "comparison_authority_contract_invalid"
            )
        if comparison_value.get(
            "production_authority_changed"
        ) is not False:
            blockers.append(
                "comparison_authority_contract_invalid"
            )

    candidate_probabilities = (
        _probabilities(
            comparison_value.get(
                "shadow_probabilities"
            )
        )
        if activation_requested
        else None
    )

    if (
        activation_requested
        and candidate_probabilities is None
    ):
        blockers.append(
            "candidate_probabilities_invalid"
        )

    if (
        activation_requested
        and production_probabilities
        is not None
        and candidate_probabilities
        is not None
        and set(candidate_probabilities)
        != set(production_probabilities)
    ):
        blockers.append(
            "candidate_outcome_keys_mismatch"
        )

    blockers = list(dict.fromkeys(blockers))
    activated = (
        activation_requested
        and not blockers
    )

    selected_model = deepcopy(production)

    if activated:
        selected_model["probabilities"] = (
            candidate_probabilities
        )
        selected_model["model_version"] = (
            comparison_value.get(
                "shadow_model_version"
            )
            or selected_model.get(
                "model_version"
            )
        )
        selected_model[
            "pitcher_matchup_profile_activation"
        ] = {
            "schema_version": SCHEMA_VERSION,
            "source": (
                "audited_canonical_pitcher_matchup_profile"
            ),
            "eligibility_digest": (
                APPROVED_ELIGIBILITY_DIGEST
            ),
            "historical_evaluation_digest": (
                APPROVED_HISTORICAL_EVALUATION_DIGEST
            ),
            "cross_season_audit_digest": (
                APPROVED_CROSS_SEASON_AUDIT_DIGEST
            ),
        }

    diagnostics = {
        "schema_version": SCHEMA_VERSION,
        "status": (
            "activated"
            if activated
            else (
                "blocked"
                if activation_requested
                else "inactive"
            )
        ),
        "activation_status": (
            "production_candidate_activated"
            if activated
            else (
                "production_activation_blocked"
                if activation_requested
                else "production_activation_not_requested"
            )
        ),
        "activation_requested": (
            activation_requested
        ),
        "activation_executed": activated,
        "blockers": blockers,
        "selected_probability_source": (
            "audited_canonical_pitcher_matchup_profile"
            if activated
            else "existing_production_pa_model"
        ),
        "evidence_matches": evidence_matches,
        "outcome_keys": (
            tuple(
                sorted(
                    selected_model.get(
                        "probabilities",
                        {},
                    )
                )
            )
        ),
        "fail_closed": True,
        "production_inputs_unchanged": (
            not activated
        ),
        "production_authority": activated,
        "production_authority_changed": (
            activated
        ),
    }
    diagnostics["activation_digest"] = (
        _digest({
            "diagnostics": diagnostics,
            "selected_probabilities": (
                selected_model.get(
                    "probabilities"
                )
            ),
        })
    )

    return {
        "model": selected_model,
        "activated": activated,
        "diagnostics": diagnostics,
    }

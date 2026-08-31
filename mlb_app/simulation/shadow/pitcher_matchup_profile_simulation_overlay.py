"""Immutable pitcher-profile overlay for canonical simulation inputs."""

from __future__ import annotations

from dataclasses import replace
import hashlib
import json
import math
from typing import Any, Mapping

from mlb_app.simulation.game import (
    CANONICAL_PA_OUTCOME_ORDER,
    CanonicalMatchupInput,
    CanonicalOutcomeProbability,
    CanonicalPlateAppearanceOutcome,
    CanonicalProbabilityArtifact,
    CanonicalProbabilityArtifactRecord,
    CanonicalProbabilityFallbackCatalog,
    CanonicalProbabilityFallbackRecord,
    CanonicalProbabilityProviderIdentity,
)


SCHEMA_VERSION = (
    "pitcher_matchup_profile_simulation_overlay_v1"
)
PROVIDER_NAME = (
    "pitcher_matchup_profile_simulation_overlay"
)
PROVIDER_VERSION = "v1"

LEGACY_OUTCOME_MAP = {
    "out": CanonicalPlateAppearanceOutcome.OUT,
    "single": CanonicalPlateAppearanceOutcome.SINGLE,
    "double": CanonicalPlateAppearanceOutcome.DOUBLE,
    "triple": CanonicalPlateAppearanceOutcome.TRIPLE,
    "home_run": CanonicalPlateAppearanceOutcome.HOME_RUN,
    "walk": CanonicalPlateAppearanceOutcome.WALK,
    "strikeout": CanonicalPlateAppearanceOutcome.STRIKEOUT,
}


def _mapping(value: Any) -> dict[str, Any]:
    return (
        dict(value)
        if isinstance(value, Mapping)
        else {}
    )


def _legacy_probabilities(
    value: Any,
) -> dict[str, float] | None:
    payload = _mapping(value)

    if set(payload) != set(LEGACY_OUTCOME_MAP):
        return None

    normalized = {}

    for key in LEGACY_OUTCOME_MAP:
        raw_value = payload.get(key)

        if (
            isinstance(raw_value, bool)
            or not isinstance(raw_value, (int, float))
        ):
            return None

        number = float(raw_value)

        if (
            not math.isfinite(number)
            or not 0.0 <= number <= 1.0
        ):
            return None

        normalized[key] = number

    if not math.isclose(
        sum(normalized.values()),
        1.0,
        rel_tol=0.0,
        abs_tol=1e-9,
    ):
        return None

    return normalized


def _activation_deltas(
    value: Mapping[str, Any] | None,
) -> dict[
    CanonicalPlateAppearanceOutcome,
    float,
] | None:
    payload = _mapping(value)
    activation = _mapping(
        payload.get("activation")
    )
    diagnostics = _mapping(
        activation.get("diagnostics")
    )
    comparison = _mapping(
        payload.get("comparison")
    )

    if (
        activation.get("activated") is not True
        or diagnostics.get("status") != "activated"
        or diagnostics.get("activation_executed")
        is not True
        or diagnostics.get("activation_status")
        != "production_candidate_activated"
        or diagnostics.get("production_authority_changed")
        is not True
        or comparison.get("status") != "ready"
        or comparison.get("executed") is not True
        or comparison.get("production_inputs_unchanged")
        is not True
        or comparison.get("production_authority_changed")
        is not False
    ):
        return None

    production = _legacy_probabilities(
        comparison.get("production_probabilities")
    )
    shadow = _legacy_probabilities(
        comparison.get("shadow_probabilities")
    )
    selected = _legacy_probabilities(
        _mapping(
            activation.get("model")
        ).get("probabilities")
    )

    if (
        production is None
        or shadow is None
        or selected is None
        or any(
            not math.isclose(
                selected[key],
                shadow[key],
                rel_tol=0.0,
                abs_tol=1e-12,
            )
            for key in LEGACY_OUTCOME_MAP
        )
    ):
        return None

    deltas = {
        outcome: 0.0
        for outcome in CANONICAL_PA_OUTCOME_ORDER
    }

    for key, outcome in LEGACY_OUTCOME_MAP.items():
        deltas[outcome] = (
            shadow[key] - production[key]
        )

    return deltas


def _overlay_probabilities(
    record: CanonicalProbabilityArtifactRecord,
    deltas: Mapping[
        CanonicalPlateAppearanceOutcome,
        float,
    ],
) -> tuple[CanonicalOutcomeProbability, ...]:
    adjusted = {
        point.outcome: max(
            0.0,
            point.probability
            + float(deltas[point.outcome]),
        )
        for point in record.probabilities
    }
    total = sum(adjusted.values())

    if total <= 0.0:
        raise ValueError(
            "pitcher overlay has no probability mass"
        )

    return tuple(
        CanonicalOutcomeProbability(
            outcome=outcome,
            probability=adjusted[outcome] / total,
        )
        for outcome in CANONICAL_PA_OUTCOME_ORDER
    )


def _artifact_id(
    *,
    matchup_input: CanonicalMatchupInput,
    exact_artifact: CanonicalProbabilityArtifact,
    fallback_catalog: CanonicalProbabilityFallbackCatalog,
    eligible: Mapping[
        str,
        Mapping[
            CanonicalPlateAppearanceOutcome,
            float,
        ],
    ],
) -> str:
    payload = {
        "schema_version": SCHEMA_VERSION,
        "game_pk": matchup_input.game_pk,
        "base_provider": (
            matchup_input.probability_provider.identity
        ),
        "exact_artifact_digest": exact_artifact.digest,
        "fallback_catalog_digest": (
            fallback_catalog.digest
        ),
        "eligible_pitcher_deltas": {
            pitcher_id: {
                outcome.value: deltas[outcome]
                for outcome in CANONICAL_PA_OUTCOME_ORDER
            }
            for pitcher_id, deltas in sorted(
                eligible.items()
            )
        },
    }
    return hashlib.sha256(
        json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _unchanged_result(
    *,
    status: str,
    blocker: str,
    matchup_input: CanonicalMatchupInput,
    exact_artifact: CanonicalProbabilityArtifact,
    fallback_catalog: CanonicalProbabilityFallbackCatalog,
) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "status": status,
        "overlay_applied": False,
        "eligible_pitcher_count": 0,
        "overlaid_matchup_count": 0,
        "preserved_matchup_count": len(
            exact_artifact.records
        ),
        "blockers": [blocker],
        "matchup_input": matchup_input,
        "exact_artifact": exact_artifact,
        "fallback_catalog": fallback_catalog,
        "base_provider_identity": (
            matchup_input.probability_provider.identity
        ),
        "overlay_provider_identity": None,
        "simulation_inputs_changed": False,
        "production_authority_changed": False,
    }


def build_pitcher_matchup_profile_simulation_overlay(
    *,
    matchup_input: CanonicalMatchupInput,
    exact_artifact: CanonicalProbabilityArtifact,
    fallback_catalog: CanonicalProbabilityFallbackCatalog,
    activation_payloads_by_pitcher_id: Mapping[
        str,
        Mapping[str, Any],
    ] | None = None,
) -> dict[str, Any]:
    """Overlay activated starter deltas onto canonical exact rows."""

    base_provider = matchup_input.probability_provider

    if (
        exact_artifact.provider != base_provider
        or fallback_catalog.provider != base_provider
    ):
        return _unchanged_result(
            status="fallback",
            blocker="canonical_provider_identity_mismatch",
            matchup_input=matchup_input,
            exact_artifact=exact_artifact,
            fallback_catalog=fallback_catalog,
        )

    starter_ids = {
        str(matchup_input.away_pitching_plan.starter_id),
        str(matchup_input.home_pitching_plan.starter_id),
    }
    eligible = {}

    for raw_pitcher_id, payload in (
        activation_payloads_by_pitcher_id or {}
    ).items():
        pitcher_id = str(raw_pitcher_id)

        if pitcher_id not in starter_ids:
            continue

        deltas = _activation_deltas(payload)

        if deltas is not None:
            eligible[pitcher_id] = deltas


    if not eligible:
        return _unchanged_result(
            status="fallback",
            blocker="no_eligible_activated_starters",
            matchup_input=matchup_input,
            exact_artifact=exact_artifact,
            fallback_catalog=fallback_catalog,
        )

    try:
        overlay_provider = (
            CanonicalProbabilityProviderIdentity(
                provider_name=PROVIDER_NAME,
                provider_version=PROVIDER_VERSION,
                artifact_id=_artifact_id(
                    matchup_input=matchup_input,
                    exact_artifact=exact_artifact,
                    fallback_catalog=fallback_catalog,
                    eligible=eligible,
                ),
            )
        )
        records = []
        overlaid_count = 0

        for record in exact_artifact.records:
            deltas = eligible.get(record.pitcher_id)

            if deltas is None:
                probabilities = record.probabilities
            else:
                probabilities = _overlay_probabilities(
                    record,
                    deltas,
                )
                overlaid_count += 1

            records.append(
                CanonicalProbabilityArtifactRecord(
                    batter_id=record.batter_id,
                    pitcher_id=record.pitcher_id,
                    probabilities=probabilities,
                )
            )

        if overlaid_count == 0:
            return _unchanged_result(
                status="fallback",
                blocker=(
                    "eligible_starters_absent_from_exact_artifact"
                ),
                matchup_input=matchup_input,
                exact_artifact=exact_artifact,
                fallback_catalog=fallback_catalog,
            )

        overlay_matchup = replace(
            matchup_input,
            probability_provider=overlay_provider,
        )
        overlay_artifact = CanonicalProbabilityArtifact(
            provider=overlay_provider,
            records=tuple(records),
        )
        overlay_fallback = (
            CanonicalProbabilityFallbackCatalog(
                provider=overlay_provider,
                records=tuple(
                    CanonicalProbabilityFallbackRecord(
                        tier=record.tier,
                        identity=record.identity,
                        probabilities=record.probabilities,
                    )
                    for record in fallback_catalog.records
                ),
            )
        )

        return {
            "schema_version": SCHEMA_VERSION,
            "status": "ready",
            "overlay_applied": True,
            "eligible_pitcher_count": len(eligible),
            "overlaid_matchup_count": overlaid_count,
            "preserved_matchup_count": (
                len(exact_artifact.records)
                - overlaid_count
            ),
            "blockers": [],
            "matchup_input": overlay_matchup,
            "exact_artifact": overlay_artifact,
            "fallback_catalog": overlay_fallback,
            "base_provider_identity": (
                base_provider.identity
            ),
            "overlay_provider_identity": (
                overlay_provider.identity
            ),
            "simulation_inputs_changed": True,
            "production_authority_changed": False,
        }
    except Exception:
        return _unchanged_result(
            status="fallback",
            blocker="pitcher_profile_overlay_error",
            matchup_input=matchup_input,
            exact_artifact=exact_artifact,
            fallback_catalog=fallback_catalog,
        )

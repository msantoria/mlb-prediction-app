"""Fail-open canonical-shadow integration."""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Dict, Optional

from mlb_app.simulation.game.probability_diagnostics import (
    CanonicalProbabilityResolutionDiagnostics,
)
from mlb_app.simulation.projections import (
    canonical_player_projection_rows,
)
from mlb_app.simulation.projections.pitcher_role_enrichment import (
    enrich_canonical_pitcher_projection_roles,
)
from .input_assembly import (
    CanonicalShadowExecutionInputs,
)

from .comparator import compare_shadow_payloads
from .contracts import CanonicalShadowDiagnostics
from .serialization import shadow_diagnostics_to_dict
from .probability_serialization import (
    probability_resolution_diagnostics_to_dict,
)
from .input_serialization import (
    CANONICAL_SHADOW_INPUT_PROVENANCE_VERSION,
    canonical_shadow_input_provenance_to_dict,
)


def attach_canonical_shadow(
    *,
    legacy_result: Dict[str, Any],
    enabled: bool = False,
    canonical_payload=None,
    probability_resolution_diagnostics: Optional[
        CanonicalProbabilityResolutionDiagnostics
    ] = None,
    canonical_shadow_execution_inputs: Optional[
        CanonicalShadowExecutionInputs
    ] = None,
    pitcher_appearance_sequence_audit: Optional[
        Dict[str, Any]
    ] = None,
) -> Dict[str, Any]:
    """Attach shadow diagnostics without mutating legacy data."""

    if not isinstance(legacy_result, dict):
        raise TypeError(
            "legacy_result must be a dictionary"
        )

    output = deepcopy(legacy_result)
    diagnostics = output.setdefault(
        "diagnostics",
        {},
    )

    if not isinstance(diagnostics, dict):
        diagnostics = {
            "legacy_diagnostics": deepcopy(
                diagnostics
            )
        }
        output["diagnostics"] = diagnostics

    if not enabled:
        shadow = CanonicalShadowDiagnostics(
            status="disabled",
            enabled=False,
            canonical_available=False,
            authoritative_source="legacy",
            warnings=(
                "canonical_shadow_disabled",
            ),
        )
    elif canonical_payload is None:
        shadow = CanonicalShadowDiagnostics(
            status="unavailable",
            enabled=True,
            canonical_available=False,
            authoritative_source="legacy",
            warnings=(
                "canonical_payload_unavailable",
            ),
        )
    else:
        try:
            shadow = compare_shadow_payloads(
                legacy_result=legacy_result,
                canonical_payload=canonical_payload,
            )
        except Exception as exc:
            shadow = CanonicalShadowDiagnostics(
                status="error",
                enabled=True,
                canonical_available=True,
                authoritative_source="legacy",
                warnings=(
                    "canonical_shadow_comparison_failed",
                ),
                error_type=exc.__class__.__name__,
                error_message=str(exc),
            )

    shadow_payload = shadow_diagnostics_to_dict(
        shadow
    )

    if enabled and canonical_payload is not None:
        try:
            projection_rows = (
                canonical_player_projection_rows(
                    canonical_payload
                )
            )
        except Exception as exc:
            projection_rows = {
                "schema_version": (
                    "canonical_player_projection_rows_v1"
                ),
                "status": "error",
                "error_type": (
                    exc.__class__.__name__
                ),
                "error_message": str(exc),
                "players": [],
                "identity_enrichment_applied": False,
                "authoritative": False,
                "authoritative_source": "legacy",
            }
        else:
            if (
                pitcher_appearance_sequence_audit
                is not None
            ):
                try:
                    projection_rows = (
                        enrich_canonical_pitcher_projection_roles(
                            payload=projection_rows,
                            appearance_audit=(
                                pitcher_appearance_sequence_audit
                            ),
                        )
                    )
                except Exception as exc:
                    projection_rows[
                        "pitcher_role_enrichment_applied"
                    ] = False
                    projection_rows[
                        "pitcher_role_enrichment"
                    ] = {
                        "schema_version": (
                            "canonical_pitcher_projection_"
                            "role_enrichment_v1"
                        ),
                        "status": "error",
                        "error_type": (
                            exc.__class__.__name__
                        ),
                        "error_message": str(exc),
                        "inference_used": False,
                        "database_writes_performed":
                            False,
                        "production_authority_changed":
                            False,
                    }

        shadow_payload[
            "player_projections"
        ] = projection_rows

    if probability_resolution_diagnostics is not None:
        try:
            shadow_payload[
                "probability_resolution"
            ] = probability_resolution_diagnostics_to_dict(
                probability_resolution_diagnostics
            )
        except Exception as exc:
            shadow_payload[
                "probability_resolution"
            ] = {
                "schema_version": (
                    "canonical_probability_"
                    "diagnostics_shadow_v1"
                ),
                "status": "error",
                "error_type": (
                    exc.__class__.__name__
                ),
                "error_message": str(exc),
            }

    if canonical_shadow_execution_inputs is not None:
        try:
            shadow_payload[
                "input_provenance"
            ] = canonical_shadow_input_provenance_to_dict(
                canonical_shadow_execution_inputs
            )
        except Exception as exc:
            shadow_payload[
                "input_provenance"
            ] = {
                "schema_version": (
                    CANONICAL_SHADOW_INPUT_PROVENANCE_VERSION
                ),
                "status": "error",
                "error_type": (
                    exc.__class__.__name__
                ),
                "error_message": str(exc),
                "authoritative_source": "legacy",
            }

    diagnostics["canonical_shadow"] = shadow_payload

    return output

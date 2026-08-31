"""Fail-open production execution for canonical shadow trials."""

from __future__ import annotations

from mlb_app.simulation.box_score import (
    DRAFTKINGS_CLASSIC_BATTER_RULES,
    DRAFTKINGS_CLASSIC_PITCHER_RULES,
)

from dataclasses import dataclass
from typing import Any, Dict, Mapping, Optional, Tuple

from mlb_app.simulation.game import (
    CanonicalBaserunningEvidenceCatalog,
    CanonicalBaserunningProbabilityTransform,
    CanonicalLineup,
    CanonicalMatchupInput,
    CanonicalProbabilityFallbackPolicy,
    CanonicalProbabilityFallbackTier,
    build_canonical_trial_factory_input,
)

from .bullpen_discovery import (
    CanonicalShadowBullpenDiscovery,
)
from .pregame_pitching_plan_materialization import (
    materialize_canonical_pregame_pitching_plan,
)
from .execution_bundle import (
    CanonicalShadowExecutionMaterial,
    canonical_shadow_execution_bundle_to_material,
)
from .exact_artifact_discovery import (
    CanonicalShadowExactArtifactDiscovery,
)
from .fallback_catalog_discovery import (
    CanonicalShadowFallbackCatalogDiscovery,
)
from .input_assembly import (
    CanonicalShadowExecutionInputs,
    assemble_canonical_shadow_execution_inputs,
)
from .lineup_discovery import (
    CanonicalShadowLineupDiscovery,
)
from .probability_provider_discovery import (
    CanonicalShadowProbabilityProviderDiscovery,
)


from .hitter_profile_simulation_shadow_overlay import (
    build_hitter_profile_simulation_shadow_overlay,
)
from .pitcher_matchup_profile_simulation_overlay import (
    build_pitcher_matchup_profile_simulation_overlay,
)


CANONICAL_PRODUCTION_SHADOW_EXECUTION_VERSION = (
    "canonical_production_shadow_execution_v1"
)

DEFAULT_PRODUCTION_SHADOW_SIMULATION_COUNT = 25


@dataclass(frozen=True)
class CanonicalProductionShadowExecution:
    material: Optional[
        CanonicalShadowExecutionMaterial
    ] = None
    execution_inputs: Optional[
        CanonicalShadowExecutionInputs
    ] = None
    status: str = "not_run"
    simulation_count: int = 0
    error_type: Optional[str] = None
    error_message: Optional[str] = None
    hitter_profile_overlay: Optional[
        Mapping[str, Any]
    ] = None
    pitcher_matchup_profile_overlay: Optional[
        Mapping[str, Any]
    ] = None
    execution_version: str = (
        CANONICAL_PRODUCTION_SHADOW_EXECUTION_VERSION
    )

    def __post_init__(self) -> None:
        if self.execution_version != (
            CANONICAL_PRODUCTION_SHADOW_EXECUTION_VERSION
        ):
            raise ValueError(
                "unsupported canonical production shadow "
                "execution version"
            )

        if (
            self.material is not None
            and not isinstance(
                self.material,
                CanonicalShadowExecutionMaterial,
            )
        ):
            raise TypeError(
                "material must be "
                "CanonicalShadowExecutionMaterial or None"
            )

        if (
            self.execution_inputs is not None
            and not isinstance(
                self.execution_inputs,
                CanonicalShadowExecutionInputs,
            )
        ):
            raise TypeError(
                "execution_inputs must be "
                "CanonicalShadowExecutionInputs or None"
            )

        if (
            self.hitter_profile_overlay
            is not None
            and not isinstance(
                self.hitter_profile_overlay,
                Mapping,
            )
        ):
            raise TypeError(
                "hitter_profile_overlay must be "
                "a mapping or None"
            )

        if (
            self.pitcher_matchup_profile_overlay
            is not None
            and not isinstance(
                self.pitcher_matchup_profile_overlay,
                Mapping,
            )
        ):
            raise TypeError(
                "pitcher_matchup_profile_overlay must be "
                "a mapping or None"
            )

    @property
    def executed(self) -> bool:
        return self.material is not None

    def to_diagnostics(self) -> Dict[str, Any]:
        payload = (
            self.material.canonical_payload
            if self.material is not None
            else {}
        )
        metadata = (
            payload.get("metadata")
            or payload.get("meta")
            or {}
        )

        diagnostics = {
            "schema_version": self.execution_version,
            "status": self.status,
            "executed": self.executed,
            "simulation_count": self.simulation_count,
            "canonical_available": self.executed,
            "provider_identity": (
                self.execution_inputs.provider_identity
                if self.execution_inputs is not None
                else None
            ),
            "exact_artifact_digest": (
                self.execution_inputs
                .exact_artifact_digest
                if self.execution_inputs is not None
                else None
            ),
            "fallback_catalog_digest": (
                self.execution_inputs
                .fallback_catalog_digest
                if self.execution_inputs is not None
                else None
            ),
            "baserunning_evidence_catalog_digest": (
                self.execution_inputs
                .baserunning_evidence_catalog_digest
                if self.execution_inputs is not None
                else None
            ),
            "input_assembly_digest": (
                self.execution_inputs.assembly_digest
                if self.execution_inputs is not None
                else None
            ),
            "canonical_model_version": (
                metadata.get("model_version")
            ),
            "error_type": self.error_type,
            "error_message": self.error_message,
            "activation_permitted": False,
            "production_authority_changed": False,
            "authoritative_source": "legacy",
            "pitcher_appearance_sequence_audit": (
                dict(
                    self.material
                    .pitcher_appearance_sequence_audit
                )
                if (
                    self.material is not None
                    and self.material
                    .pitcher_appearance_sequence_audit
                    is not None
                )
                else None
            ),
        }

        if self.hitter_profile_overlay is not None:
            diagnostics[
                "hitter_profile_simulation_shadow"
            ] = dict(
                self.hitter_profile_overlay
            )

        if (
            self.pitcher_matchup_profile_overlay
            is not None
        ):
            diagnostics[
                "pitcher_matchup_profile_simulation_overlay"
            ] = dict(
                self.pitcher_matchup_profile_overlay
            )

        return diagnostics


def _build_matchup_input(
    *,
    game_pk: int,
    lineups: CanonicalShadowLineupDiscovery,
    bullpens: CanonicalShadowBullpenDiscovery,
    provider_discovery: (
        CanonicalShadowProbabilityProviderDiscovery
    ),
    away_pitching_plan_classification: Optional[
        Mapping[str, Any]
    ] = None,
    home_pitching_plan_classification: Optional[
        Mapping[str, Any]
    ] = None,
) -> CanonicalMatchupInput:
    provider = provider_discovery.provider

    if provider is None:
        raise ValueError(
            "probability provider is unavailable"
        )

    away_starter = bullpens.away.starter_id
    home_starter = bullpens.home.starter_id

    if away_starter is None or home_starter is None:
        raise ValueError(
            "both scheduled starters are required"
        )

    away_bullpen_ids = (
        bullpens.away.bullpen_pitcher_ids
    )
    home_bullpen_ids = (
        bullpens.home.bullpen_pitcher_ids
    )

    away_plan_materialization = (
        materialize_canonical_pregame_pitching_plan(
            team_side="away",
            starter_id=away_starter,
            bullpen_pitcher_ids=away_bullpen_ids,
            classification=(
                away_pitching_plan_classification
            ),
        )
    )
    home_plan_materialization = (
        materialize_canonical_pregame_pitching_plan(
            team_side="home",
            starter_id=home_starter,
            bullpen_pitcher_ids=home_bullpen_ids,
            classification=(
                home_pitching_plan_classification
            ),
        )
    )

    return CanonicalMatchupInput(
        game_pk=int(game_pk),
        away_lineup=CanonicalLineup(
            team_side="away",
            player_ids=lineups.away_player_ids,
        ),
        home_lineup=CanonicalLineup(
            team_side="home",
            player_ids=lineups.home_player_ids,
        ),
        away_pitching_plan=(
            away_plan_materialization.pitching_plan
        ),
        home_pitching_plan=(
            home_plan_materialization.pitching_plan
        ),
        probability_provider=provider,
    )


def run_canonical_production_shadow(
    *,
    game_pk: Any,
    lineups: CanonicalShadowLineupDiscovery,
    bullpens: CanonicalShadowBullpenDiscovery,
    provider_discovery: (
        CanonicalShadowProbabilityProviderDiscovery
    ),
    exact_artifact_discovery: (
        CanonicalShadowExactArtifactDiscovery
    ),
    fallback_catalog_discovery: (
        CanonicalShadowFallbackCatalogDiscovery
    ),
    bootstrap_ready: bool,
    baserunning_evidence_catalog: Optional[
        CanonicalBaserunningEvidenceCatalog
    ] = None,
    baserunning_probability_transform: Optional[
        CanonicalBaserunningProbabilityTransform
    ] = None,
    simulation_count: int = (
        DEFAULT_PRODUCTION_SHADOW_SIMULATION_COUNT
    ),
    away_pitching_plan_classification: Optional[
        Mapping[str, Any]
    ] = None,
    home_pitching_plan_classification: Optional[
        Mapping[str, Any]
    ] = None,
    hitter_profile_shadow_enabled: bool = False,
    hitter_profile_acceptance_gate: Optional[
        Mapping[str, Any]
    ] = None,
    hitter_profile_candidate_results: Optional[
        Mapping[
            str,
            Mapping[str, Any],
        ]
    ] = None,
    pitcher_matchup_profile_activation_payloads_by_pitcher_id: Optional[
        Mapping[
            str,
            Mapping[str, Any],
        ]
    ] = None,
    pitcher_usage_evidence_by_id: Optional[
        Mapping[Any, Any]
    ] = None,
    batter_handedness_by_id: Optional[
        Mapping[str, str]
    ] = None,
) -> CanonicalProductionShadowExecution:
    """
    Execute a small canonical batch when every production input is ready.

    Any assembly or execution failure remains fail-open and leaves legacy
    projections authoritative.
    """

    if not bootstrap_ready:
        return CanonicalProductionShadowExecution(
            status="blocked",
        )

    if not lineups.ready:
        return CanonicalProductionShadowExecution(
            status="blocked",
        )

    if not bullpens.ready:
        return CanonicalProductionShadowExecution(
            status="blocked",
        )

    exact_artifact = (
        exact_artifact_discovery.artifact
    )
    fallback_catalog = (
        fallback_catalog_discovery.catalog
    )

    if (
        exact_artifact is None
        or fallback_catalog is None
        or provider_discovery.provider is None
    ):
        return CanonicalProductionShadowExecution(
            status="blocked",
        )

    hitter_profile_overlay_diagnostics = None
    pitcher_matchup_profile_overlay_diagnostics = None

    try:
        normalized_simulation_count = int(
            simulation_count
        )

        if normalized_simulation_count <= 0:
            raise ValueError(
                "simulation_count must be positive"
            )

        matchup_input = _build_matchup_input(
            game_pk=int(game_pk),
            lineups=lineups,
            bullpens=bullpens,
            provider_discovery=provider_discovery,
            away_pitching_plan_classification=(
                away_pitching_plan_classification
            ),
            home_pitching_plan_classification=(
                home_pitching_plan_classification
            ),
        )

        if hitter_profile_shadow_enabled is True:
            overlay = (
                build_hitter_profile_simulation_shadow_overlay(
                    enabled=True,
                    acceptance_gate=(
                        hitter_profile_acceptance_gate
                    ),
                    matchup_input=matchup_input,
                    exact_artifact=exact_artifact,
                    fallback_catalog=fallback_catalog,
                    candidate_results=(
                        hitter_profile_candidate_results
                    ),
                )
            )
            hitter_profile_overlay_diagnostics = {
                key: value
                for key, value in overlay.items()
                if key
                not in {
                    "matchup_input",
                    "exact_artifact",
                    "fallback_catalog",
                }
            }

            if overlay.get("overlay_applied") is True:
                matchup_input = overlay[
                    "matchup_input"
                ]
                exact_artifact = overlay[
                    "exact_artifact"
                ]
                fallback_catalog = overlay[
                    "fallback_catalog"
                ]

        if (
            pitcher_matchup_profile_activation_payloads_by_pitcher_id
        ):
            overlay = (
                build_pitcher_matchup_profile_simulation_overlay(
                    matchup_input=matchup_input,
                    exact_artifact=exact_artifact,
                    fallback_catalog=fallback_catalog,
                    activation_payloads_by_pitcher_id=(
                        pitcher_matchup_profile_activation_payloads_by_pitcher_id
                    ),
                )
            )
            pitcher_matchup_profile_overlay_diagnostics = {
                key: value
                for key, value in overlay.items()
                if key
                not in {
                    "matchup_input",
                    "exact_artifact",
                    "fallback_catalog",
                }
            }

            if overlay.get("overlay_applied") is True:
                matchup_input = overlay[
                    "matchup_input"
                ]
                exact_artifact = overlay[
                    "exact_artifact"
                ]
                fallback_catalog = overlay[
                    "fallback_catalog"
                ]

        fallback_policy = (
            CanonicalProbabilityFallbackPolicy(
                tiers=(
                    CanonicalProbabilityFallbackTier
                    .EXACT_MATCHUP,
                    CanonicalProbabilityFallbackTier
                    .GLOBAL,
                )
            )
        )

        execution_inputs = (
            assemble_canonical_shadow_execution_inputs(
                matchup_input=matchup_input,
                exact_artifact=exact_artifact,
                fallback_catalog=fallback_catalog,
                baserunning_evidence_catalog=(
                    baserunning_evidence_catalog
                ),
                baserunning_probability_transform=(
                    baserunning_probability_transform
                ),
                fallback_policy=fallback_policy,
                batter_dfs_rules=(
                    DRAFTKINGS_CLASSIC_BATTER_RULES
                ),
                pitcher_dfs_rules=(
                    DRAFTKINGS_CLASSIC_PITCHER_RULES
                ),
                pitcher_usage_evidence_by_id=(
                    pitcher_usage_evidence_by_id
                ),
                batter_handedness_by_id=(
                    batter_handedness_by_id
                ),
            )
        )

        factory_input = (
            build_canonical_trial_factory_input(
                game_pk=int(game_pk),
                config={
                    "simulation_count": (
                        normalized_simulation_count
                    ),
                    "canonical_model_version": (
                        "canonical-event-model-v1"
                    ),
                },
            )
        )

        bundle = execution_inputs.build_factory()(
            factory_input=factory_input,
        )

        material = (
            canonical_shadow_execution_bundle_to_material(
                bundle
            )
        )

        atomic_execution_inputs = (
            material.canonical_shadow_execution_inputs
        )

        if atomic_execution_inputs is None:
            raise RuntimeError(
                "canonical execution material is missing "
                "atomic execution inputs"
            )

        return CanonicalProductionShadowExecution(
            material=material,
            execution_inputs=atomic_execution_inputs,
            status="executed",
            simulation_count=(
                normalized_simulation_count
            ),
            hitter_profile_overlay=(
                hitter_profile_overlay_diagnostics
            ),
            pitcher_matchup_profile_overlay=(
                pitcher_matchup_profile_overlay_diagnostics
            ),
        )
    except Exception as exc:
        return CanonicalProductionShadowExecution(
            status="error",
            simulation_count=0,
            error_type=exc.__class__.__name__,
            error_message=str(exc),
            hitter_profile_overlay=(
                hitter_profile_overlay_diagnostics
            ),
            pitcher_matchup_profile_overlay=(
                pitcher_matchup_profile_overlay_diagnostics
            ),
        )

"""Injected canonical shadow execution-bundle factory."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Optional

from mlb_app.simulation.box_score import (
    BatterDfsScoringRules,
    PitcherDfsScoringRules,
)
from mlb_app.simulation.game.baserunning_composition import (
    build_canonical_catalog_baserunning_resolver_factory,
)
from mlb_app.simulation.game.baserunning_evidence_catalog import (
    CanonicalBaserunningEvidenceCatalog,
)
from mlb_app.simulation.game.baserunning_probability_transform import (
    CanonicalBaserunningProbabilityTransform,
)
from mlb_app.simulation.game.contracts import (
    CanonicalGameConfig,
)
from mlb_app.simulation.game.factory_input import (
    CanonicalTrialFactoryInput,
)
from mlb_app.simulation.game.matchup_input import (
    CanonicalMatchupInput,
)
from mlb_app.simulation.game.bullpen_selector import (
    CanonicalBullpenPitcher,
    CanonicalBullpenRole,
)
from mlb_app.simulation.game.pa_resolver_factory import (
    CanonicalPlateAppearanceResolverFactory,
)
from mlb_app.simulation.game.probability_artifact import (
    CanonicalProbabilityArtifact,
)
from mlb_app.simulation.game.probability_diagnostics import (
    CanonicalProbabilityResolutionDiagnosticsCollector,
    build_canonical_probability_diagnostics_provider,
)
from mlb_app.simulation.game.probability_fallback import (
    CanonicalProbabilityFallbackAdapter,
    CanonicalProbabilityFallbackCatalog,
    CanonicalProbabilityFallbackPolicy,
)
from mlb_app.simulation.game.trial_factory import (
    CanonicalTrialExecutionPlan,
    run_canonical_trial_execution_plan,
)

from .execution_bundle import (
    CanonicalShadowExecutionBundle,
)


CANONICAL_SHADOW_EXECUTION_BUNDLE_FACTORY_VERSION = (
    "canonical_shadow_execution_bundle_factory_v1"
)


_ROLE_BY_EVIDENCE = {
    "closer": CanonicalBullpenRole.CLOSER,
    "setup": CanonicalBullpenRole.SETUP,
    "setup_reliever": CanonicalBullpenRole.SETUP,
    "long_relief": CanonicalBullpenRole.LONG_RELIEF,
    "long_reliever": CanonicalBullpenRole.LONG_RELIEF,
    "bulk_follower": CanonicalBullpenRole.LONG_RELIEF,
    "swingman": CanonicalBullpenRole.LONG_RELIEF,
    "middle_relief": CanonicalBullpenRole.MIDDLE_RELIEF,
    "middle_reliever": CanonicalBullpenRole.MIDDLE_RELIEF,
    "opener": CanonicalBullpenRole.MIDDLE_RELIEF,
    "unknown": CanonicalBullpenRole.MIDDLE_RELIEF,
}


def _evidence_record(
    evidence_by_pitcher_id: Optional[
        Mapping[Any, Any]
    ],
    pitcher_id: str,
) -> Mapping[str, Any]:
    if not isinstance(
        evidence_by_pitcher_id,
        Mapping,
    ):
        return {}

    record = (
        evidence_by_pitcher_id.get(pitcher_id)
    )

    if record is None:
        try:
            numeric_id = int(pitcher_id)
        except (TypeError, ValueError):
            numeric_id = None

        if numeric_id is not None:
            record = evidence_by_pitcher_id.get(
                numeric_id
            )

    return record if isinstance(record, Mapping) else {}


def _canonical_bullpen_role(
    record: Mapping[str, Any],
) -> CanonicalBullpenRole:
    planned_role = record.get(
        "planned_game_role"
    )

    if (
        record.get("planned_game_role_status")
        == "confirmed"
        and planned_role
    ):
        role_value = planned_role
    else:
        role_value = (
            record.get("typical_role")
            or record.get("role")
        )

    normalized = str(
        role_value or "unknown"
    ).strip().lower()

    return _ROLE_BY_EVIDENCE.get(
        normalized,
        CanonicalBullpenRole.MIDDLE_RELIEF,
    )


def _nonnegative_int(
    value: Any,
    default: int = 0,
) -> int:
    if isinstance(value, bool):
        return default

    try:
        normalized = int(value)
    except (TypeError, ValueError):
        return default

    return normalized if normalized >= 0 else default


def _fatigue_index(value: Any) -> float:
    if isinstance(value, bool):
        return 0.0

    try:
        normalized = float(value)
    except (TypeError, ValueError):
        return 0.0

    if not 0.0 <= normalized <= 1.0:
        return 0.0

    return normalized


def _baseline_bullpen(
    pitcher_ids: tuple[str, ...],
    evidence_by_pitcher_id: Optional[
        Mapping[Any, Any]
    ] = None,
) -> tuple[CanonicalBullpenPitcher, ...]:
    """
    Adapt a canonical pitching plan and optional pretrial evidence.

    Missing or invalid role, handedness, and workload evidence remains
    neutral. This adapter performs no discovery or storage reads.
    """

    bullpen = []

    for index, pitcher_id in enumerate(
        pitcher_ids
    ):
        record = _evidence_record(
            evidence_by_pitcher_id,
            pitcher_id,
        )

        handedness = str(
            record.get("handedness")
            or record.get("throws")
            or ""
        ).strip().upper()

        if handedness not in {"L", "R"}:
            handedness = None

        available_value = record.get("available")
        available = (
            available_value
            if isinstance(available_value, bool)
            else True
        )

        bullpen.append(
            CanonicalBullpenPitcher(
                pitcher_id=pitcher_id,
                role=_canonical_bullpen_role(
                    record
                ),
                available=available,
                appearance_priority=_nonnegative_int(
                    record.get(
                        "appearance_priority"
                    ),
                    index,
                ),
                handedness=handedness,
                fatigue_index=_fatigue_index(
                    record.get("fatigue_index")
                ),
                consecutive_days_worked=(
                    _nonnegative_int(
                        record.get(
                            "consecutive_days_worked"
                        )
                    )
                ),
                recent_pitch_count=(
                    _nonnegative_int(
                        record.get(
                            "recent_pitch_count"
                        )
                    )
                ),
            )
        )

    return tuple(bullpen)


@dataclass(frozen=True)
class CanonicalShadowExecutionBundleFactory:
    """
    Compose one complete canonical shadow execution.

    This factory is dependency-injected only. It does not load artifacts,
    choose production defaults, mutate legacy output, or activate canonical
    authority.
    """

    matchup_input: CanonicalMatchupInput
    exact_artifact: CanonicalProbabilityArtifact
    fallback_catalog: CanonicalProbabilityFallbackCatalog
    baserunning_evidence_catalog: Optional[
        CanonicalBaserunningEvidenceCatalog
    ] = None
    baserunning_probability_transform: Optional[
        CanonicalBaserunningProbabilityTransform
    ] = None
    fallback_policy: CanonicalProbabilityFallbackPolicy = field(
        default_factory=CanonicalProbabilityFallbackPolicy
    )
    game_config: CanonicalGameConfig = field(
        default_factory=CanonicalGameConfig
    )
    batter_dfs_rules: Optional[
        BatterDfsScoringRules
    ] = None
    pitcher_dfs_rules: Optional[
        PitcherDfsScoringRules
    ] = None
    pitcher_usage_evidence_by_id: Optional[
        Mapping[Any, Any]
    ] = None
    batter_handedness_by_id: Optional[
        Mapping[str, str]
    ] = None
    factory_version: str = (
        CANONICAL_SHADOW_EXECUTION_BUNDLE_FACTORY_VERSION
    )

    def __post_init__(self) -> None:
        if not isinstance(
            self.matchup_input,
            CanonicalMatchupInput,
        ):
            raise TypeError(
                "matchup_input must be a CanonicalMatchupInput"
            )

        if not isinstance(
            self.exact_artifact,
            CanonicalProbabilityArtifact,
        ):
            raise TypeError(
                "exact_artifact must be a "
                "CanonicalProbabilityArtifact"
            )

        if not isinstance(
            self.fallback_catalog,
            CanonicalProbabilityFallbackCatalog,
        ):
            raise TypeError(
                "fallback_catalog must be a "
                "CanonicalProbabilityFallbackCatalog"
            )

        if (
            self.baserunning_evidence_catalog is not None
            and not isinstance(
                self.baserunning_evidence_catalog,
                CanonicalBaserunningEvidenceCatalog,
            )
        ):
            raise TypeError(
                "baserunning_evidence_catalog must be "
                "CanonicalBaserunningEvidenceCatalog or None"
            )

        if (
            self.baserunning_probability_transform is not None
            and not isinstance(
                self.baserunning_probability_transform,
                CanonicalBaserunningProbabilityTransform,
            )
        ):
            raise TypeError(
                "baserunning_probability_transform must be "
                "CanonicalBaserunningProbabilityTransform "
                "or None"
            )

        if not isinstance(
            self.fallback_policy,
            CanonicalProbabilityFallbackPolicy,
        ):
            raise TypeError(
                "fallback_policy must be a "
                "CanonicalProbabilityFallbackPolicy"
            )

        if not isinstance(
            self.game_config,
            CanonicalGameConfig,
        ):
            raise TypeError(
                "game_config must be a CanonicalGameConfig"
            )

        provider = (
            self.matchup_input.probability_provider
        )

        if self.exact_artifact.provider != provider:
            raise ValueError(
                "exact artifact provider must match "
                "matchup probability-provider identity"
            )

        if self.fallback_catalog.provider != provider:
            raise ValueError(
                "fallback catalog provider must match "
                "matchup probability-provider identity"
            )

        if self.factory_version != (
            CANONICAL_SHADOW_EXECUTION_BUNDLE_FACTORY_VERSION
        ):
            raise ValueError(
                "unsupported canonical shadow execution "
                "bundle factory version"
            )

    def __call__(
        self,
        *,
        factory_input: CanonicalTrialFactoryInput,
    ) -> CanonicalShadowExecutionBundle:
        if not isinstance(
            factory_input,
            CanonicalTrialFactoryInput,
        ):
            raise TypeError(
                "factory_input must be a "
                "CanonicalTrialFactoryInput"
            )

        if (
            factory_input.game_pk
            != self.matchup_input.game_pk
        ):
            raise ValueError(
                "factory-input game_pk must match "
                "canonical matchup input"
            )

        collector = (
            CanonicalProbabilityResolutionDiagnosticsCollector()
        )

        fallback_adapter = (
            CanonicalProbabilityFallbackAdapter(
                exact_artifact=self.exact_artifact,
                fallback_catalog=self.fallback_catalog,
                policy=self.fallback_policy,
            )
        )

        probability_provider = (
            build_canonical_probability_diagnostics_provider(
                fallback_adapter=fallback_adapter,
                collector=collector,
            )
        )

        resolver_factory = (
            CanonicalPlateAppearanceResolverFactory(
                probability_provider=probability_provider,
                away_bullpen=_baseline_bullpen(
                    self.matchup_input
                    .away_pitching_plan
                    .bullpen_pitcher_ids,
                    self.pitcher_usage_evidence_by_id,
                ),
                home_bullpen=_baseline_bullpen(
                    self.matchup_input
                    .home_pitching_plan
                    .bullpen_pitcher_ids,
                    self.pitcher_usage_evidence_by_id,
                ),
                batter_handedness_by_id=(
                    self.batter_handedness_by_id
                ),
            )
        )

        coupled_baserunning_resolver_factory = None
        if self.baserunning_evidence_catalog is not None:
            coupled_baserunning_resolver_factory = (
                build_canonical_catalog_baserunning_resolver_factory(
                    catalog=(
                        self.baserunning_evidence_catalog
                    ),
                    probability_transform=(
                        self.baserunning_probability_transform
                    ),
                )
            )

        plan = CanonicalTrialExecutionPlan(
            factory_input=factory_input,
            away_lineup=(
                self.matchup_input.away_lineup
            ),
            home_lineup=(
                self.matchup_input.home_lineup
            ),
            resolver_factory=resolver_factory,
            coupled_baserunning_resolver_factory=(
                coupled_baserunning_resolver_factory
            ),
            game_config=self.game_config,
            batter_dfs_rules=self.batter_dfs_rules,
            pitcher_dfs_rules=self.pitcher_dfs_rules,
            matchup_input=self.matchup_input,
        )

        trial_batch = (
            run_canonical_trial_execution_plan(
                plan
            )
        )

        from .input_assembly import (
            CanonicalShadowExecutionInputs,
        )

        execution_inputs = CanonicalShadowExecutionInputs(
            matchup_input=self.matchup_input,
            exact_artifact=self.exact_artifact,
            fallback_catalog=self.fallback_catalog,
            baserunning_evidence_catalog=(
                self.baserunning_evidence_catalog
            ),
            baserunning_probability_transform=(
                self.baserunning_probability_transform
            ),
            fallback_policy=self.fallback_policy,
            game_config=self.game_config,
            batter_dfs_rules=self.batter_dfs_rules,
            pitcher_dfs_rules=self.pitcher_dfs_rules,
        )

        return CanonicalShadowExecutionBundle(
            trial_batch=trial_batch,
            probability_resolution_diagnostics=(
                collector.snapshot()
            ),
            canonical_shadow_execution_inputs=(
                execution_inputs
            ),
        )


def build_canonical_shadow_execution_bundle_factory(
    *,
    matchup_input: CanonicalMatchupInput,
    exact_artifact: CanonicalProbabilityArtifact,
    fallback_catalog: CanonicalProbabilityFallbackCatalog,
    baserunning_evidence_catalog: Optional[
        CanonicalBaserunningEvidenceCatalog
    ] = None,
    baserunning_probability_transform: Optional[
        CanonicalBaserunningProbabilityTransform
    ] = None,
    fallback_policy: Optional[
        CanonicalProbabilityFallbackPolicy
    ] = None,
    game_config: Optional[
        CanonicalGameConfig
    ] = None,
    batter_dfs_rules: Optional[
        BatterDfsScoringRules
    ] = None,
    pitcher_dfs_rules: Optional[
        PitcherDfsScoringRules
    ] = None,
    pitcher_usage_evidence_by_id: Optional[
        Mapping[Any, Any]
    ] = None,
    batter_handedness_by_id: Optional[
        Mapping[str, str]
    ] = None,
) -> CanonicalShadowExecutionBundleFactory:
    """Build an explicit, non-default canonical shadow factory."""

    return CanonicalShadowExecutionBundleFactory(
        matchup_input=matchup_input,
        exact_artifact=exact_artifact,
        fallback_catalog=fallback_catalog,
        baserunning_evidence_catalog=(
            baserunning_evidence_catalog
        ),
        baserunning_probability_transform=(
            baserunning_probability_transform
        ),
        fallback_policy=(
            fallback_policy
            or CanonicalProbabilityFallbackPolicy()
        ),
        game_config=(
            game_config
            or CanonicalGameConfig()
        ),
        batter_dfs_rules=batter_dfs_rules,
        pitcher_dfs_rules=pitcher_dfs_rules,
        pitcher_usage_evidence_by_id=(
            pitcher_usage_evidence_by_id
        ),
        batter_handedness_by_id=(
            batter_handedness_by_id
        ),
    )

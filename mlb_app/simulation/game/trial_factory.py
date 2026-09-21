"""Indexed canonical trial and resolver-factory protocols."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Optional

from mlb_app.simulation.box_score import (
    BatterDfsScoringRules,
    PitcherDfsScoringRules,
)

from .contracts import (
    CanonicalGameConfig,
    CanonicalGameResult,
    CanonicalLineup,
)
from .executed_trial import (
    CanonicalExecutedTrial,
)
from .factory_input import (
    CanonicalTrialFactoryInput,
)
from .matchup_input import (
    CanonicalMatchupInput,
)
from .orchestrator import (
    BaserunningResolver,
    PlateAppearanceResolver,
    simulate_canonical_game,
)
from .trials import (
    CanonicalTrialBatch,
    run_canonical_trials,
)


@dataclass(frozen=True)
class CanonicalTrialResolverContext:
    """
    Immutable identity supplied when constructing one trial resolver.

    Matchup probability generation may later consume this context, but
    this contract does not select or implement any probability model.
    """

    factory_input: CanonicalTrialFactoryInput
    trial_index: int
    trial_seed: int
    regulation_innings: int = 9
    matchup_input: Optional[
        CanonicalMatchupInput
    ] = None

    def __post_init__(self) -> None:
        if not isinstance(
            self.factory_input,
            CanonicalTrialFactoryInput,
        ):
            raise TypeError(
                "factory_input must be a "
                "CanonicalTrialFactoryInput"
            )

        if isinstance(self.trial_index, bool):
            raise TypeError(
                "trial_index must be an integer"
            )

        if (
            self.trial_index < 0
            or self.trial_index
            >= self.factory_input.simulation_count
        ):
            raise ValueError(
                "trial_index is outside the factory input"
            )

        if isinstance(
            self.regulation_innings,
            bool,
        ):
            raise TypeError(
                "regulation_innings must be an integer"
            )

        if self.regulation_innings < 1:
            raise ValueError(
                "regulation_innings must be positive"
            )

        expected_seed = (
            self.factory_input.seed_for_trial(
                self.trial_index
            )
        )

        if self.trial_seed != expected_seed:
            raise ValueError(
                "trial_seed does not match the indexed "
                "factory-input seed"
            )

        if self.matchup_input is not None:
            if not isinstance(
                self.matchup_input,
                CanonicalMatchupInput,
            ):
                raise TypeError(
                    "matchup_input must be a "
                    "CanonicalMatchupInput"
                )

            if (
                self.matchup_input.game_pk
                != self.factory_input.game_pk
            ):
                raise ValueError(
                    "matchup game_pk must match "
                    "factory input"
                )


CanonicalTrialResolverFactory = Callable[
    [CanonicalTrialResolverContext],
    PlateAppearanceResolver,
]
CanonicalBaserunningResolverFactory = Callable[
    [CanonicalTrialResolverContext],
    BaserunningResolver,
]
CanonicalCoupledBaserunningResolverFactory = Callable[
    [
        CanonicalTrialResolverContext,
        PlateAppearanceResolver,
    ],
    BaserunningResolver,
]


@dataclass(frozen=True)
class CanonicalTrialExecutionPlan:
    """
    Complete non-probabilistic plan for running canonical trials.

    Lineups and game rules are fixed across the batch. The injected
    resolver factory receives one deterministic indexed context for
    every trial and must return a fresh plate-appearance resolver.
    """

    factory_input: CanonicalTrialFactoryInput
    away_lineup: CanonicalLineup
    home_lineup: CanonicalLineup
    resolver_factory: CanonicalTrialResolverFactory
    baserunning_resolver_factory: Optional[
        CanonicalBaserunningResolverFactory
    ] = None
    coupled_baserunning_resolver_factory: Optional[
        CanonicalCoupledBaserunningResolverFactory
    ] = None
    game_config: CanonicalGameConfig = field(
        default_factory=CanonicalGameConfig
    )
    batter_dfs_rules: Optional[
        BatterDfsScoringRules
    ] = None
    pitcher_dfs_rules: Optional[
        PitcherDfsScoringRules
    ] = None
    matchup_input: Optional[
        CanonicalMatchupInput
    ] = None

    def __post_init__(self) -> None:
        if not isinstance(
            self.factory_input,
            CanonicalTrialFactoryInput,
        ):
            raise TypeError(
                "factory_input must be a "
                "CanonicalTrialFactoryInput"
            )

        if not isinstance(
            self.away_lineup,
            CanonicalLineup,
        ):
            raise TypeError(
                "away_lineup must be a CanonicalLineup"
            )

        if not isinstance(
            self.home_lineup,
            CanonicalLineup,
        ):
            raise TypeError(
                "home_lineup must be a CanonicalLineup"
            )

        if self.away_lineup.team_side != "away":
            raise ValueError(
                "away_lineup must use away team side"
            )

        if self.home_lineup.team_side != "home":
            raise ValueError(
                "home_lineup must use home team side"
            )

        if not isinstance(
            self.game_config,
            CanonicalGameConfig,
        ):
            raise TypeError(
                "game_config must be a "
                "CanonicalGameConfig"
            )

        if not callable(self.resolver_factory):
            raise TypeError(
                "resolver_factory must be callable"
            )

        if (
            self.baserunning_resolver_factory is not None
            and not callable(
                self.baserunning_resolver_factory
            )
        ):
            raise TypeError(
                "baserunning_resolver_factory "
                "must be callable"
            )

        if (
            self.coupled_baserunning_resolver_factory
            is not None
            and not callable(
                self.coupled_baserunning_resolver_factory
            )
        ):
            raise TypeError(
                "coupled_baserunning_resolver_factory "
                "must be callable"
            )

        if (
            self.baserunning_resolver_factory is not None
            and self.coupled_baserunning_resolver_factory
            is not None
        ):
            raise ValueError(
                "only one baserunning resolver factory "
                "may be configured"
            )

        if self.matchup_input is not None:
            if not isinstance(
                self.matchup_input,
                CanonicalMatchupInput,
            ):
                raise TypeError(
                    "matchup_input must be a "
                    "CanonicalMatchupInput"
                )

            if (
                self.matchup_input.game_pk
                != self.factory_input.game_pk
            ):
                raise ValueError(
                    "matchup game_pk must match "
                    "factory input"
                )

            if (
                self.matchup_input.away_lineup
                != self.away_lineup
            ):
                raise ValueError(
                    "matchup away lineup must match plan"
                )

            if (
                self.matchup_input.home_lineup
                != self.home_lineup
            ):
                raise ValueError(
                    "matchup home lineup must match plan"
                )


def build_canonical_trial_resolver_context(
    *,
    factory_input: CanonicalTrialFactoryInput,
    trial_index: int,
    regulation_innings: int = 9,
    matchup_input: Optional[
        CanonicalMatchupInput
    ] = None,
) -> CanonicalTrialResolverContext:
    """Build the deterministic resolver context for one trial."""

    return CanonicalTrialResolverContext(
        factory_input=factory_input,
        trial_index=trial_index,
        trial_seed=factory_input.seed_for_trial(
            trial_index
        ),
        regulation_innings=regulation_innings,
        matchup_input=matchup_input,
    )


def run_canonical_trial_execution_plan(
    plan: CanonicalTrialExecutionPlan,
) -> CanonicalTrialBatch:
    """
    Run one complete indexed canonical trial plan.

    This delegates validation, box-score reduction, reconciliation,
    outcome aggregation, and projection aggregation to the existing
    canonical multi-trial runner.
    """

    if not isinstance(
        plan,
        CanonicalTrialExecutionPlan,
    ):
        raise TypeError(
            "plan must be a CanonicalTrialExecutionPlan"
        )

    def trial_factory(
        trial_index: int,
    ) -> CanonicalExecutedTrial:
        context = (
            build_canonical_trial_resolver_context(
                factory_input=plan.factory_input,
                trial_index=trial_index,
                regulation_innings=(
                    plan.game_config.regulation_innings
                ),
                matchup_input=plan.matchup_input,
            )
        )

        resolver = plan.resolver_factory(context)

        if not callable(resolver):
            raise TypeError(
                "resolver_factory must return a "
                "plate-appearance resolver"
            )

        baserunning_resolver = None
        if (
            plan.coupled_baserunning_resolver_factory
            is not None
        ):
            baserunning_resolver = (
                plan.coupled_baserunning_resolver_factory(
                    context,
                    resolver,
                )
            )

            if not callable(baserunning_resolver):
                raise TypeError(
                    "coupled_baserunning_resolver_factory "
                    "must return a baserunning resolver"
                )
        elif (
            plan.baserunning_resolver_factory
            is not None
        ):
            baserunning_resolver = (
                plan.baserunning_resolver_factory(
                    context
                )
            )

            if not callable(baserunning_resolver):
                raise TypeError(
                    "baserunning_resolver_factory "
                    "must return a baserunning resolver"
                )

        game = simulate_canonical_game(
            away_lineup=plan.away_lineup,
            home_lineup=plan.home_lineup,
            resolve_plate_appearance=resolver,
            config=plan.game_config,
            resolve_baserunning=baserunning_resolver,
        )

        reconstructed_lines = (
            resolver.reconstructed_pitcher_run_lines()
            if hasattr(
                resolver,
                "reconstructed_pitcher_run_lines",
            )
            else ()
        )

        reconstruction_complete = (
            resolver.earned_run_reconstruction_complete()
            if hasattr(
                resolver,
                "earned_run_reconstruction_complete",
            )
            else False
        )

        defensive_event_authority_records = (
            resolver.defensive_event_authority_snapshot()
            if hasattr(
                resolver,
                "defensive_event_authority_snapshot",
            )
            else ()
        )

        return CanonicalExecutedTrial(
            game=game,
            reconstructed_pitcher_run_lines=(
                tuple(reconstructed_lines)
            ),
            earned_run_reconstruction_complete=(
                reconstruction_complete
            ),
            defensive_event_authority_records=(
                tuple(
                    defensive_event_authority_records
                )
            ),
        )

    return run_canonical_trials(
        trial_factory=trial_factory,
        simulations=(
            plan.factory_input.simulation_count
        ),
        model_version=(
            plan.factory_input.model_version
        ),
        batter_dfs_rules=plan.batter_dfs_rules,
        pitcher_dfs_rules=plan.pitcher_dfs_rules,
    )

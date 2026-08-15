"""Deterministic canonical plate-appearance resolver construction."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Optional, Tuple

from mlb_app.simulation.events import (
    GameState,
    PlayEvent,
)

from .bulk_follower_hook_policy import (
    CanonicalBulkFollowerHookPolicy,
    build_baseline_bulk_follower_hook_policy,
)
from .bullpen_selector import (
    CanonicalBullpenPitcher,
    CanonicalBullpenSelector,
    build_canonical_bullpen_selector,
)
from .pitcher_hook_policy import (
    CanonicalStarterHookPolicy,
    build_baseline_opener_hook_policy,
    build_baseline_starter_hook_policy,
)
from .pitching_manager import CanonicalPitchingManager
from .reliever_hook_policy import (
    CanonicalRelieverHookPolicy,
    build_baseline_reliever_hook_policy,
)
from .matchup_input import CanonicalMatchupInput
from .orchestrator import PlateAppearanceResolver
from .outcome_resolution import (
    resolve_canonical_sampled_plate_appearance,
)
from .probability import (
    CanonicalPlateAppearanceProbabilities,
    CanonicalPlateAppearanceProbabilityProvider,
    CanonicalPlateAppearanceQuery,
    sample_canonical_plate_appearance,
)
from .trial_factory import (
    CanonicalTrialResolverContext,
    CanonicalTrialResolverFactory,
)


CANONICAL_PA_RESOLVER_FACTORY_VERSION = (
    "canonical_pa_resolver_factory_v1"
)


@dataclass(frozen=True)
class CanonicalPlateAppearanceResolverFactory:
    """
    Build one deterministic canonical PA resolver per trial.

    Pitcher substitutions are intentionally outside this contract.
    Each half-inning therefore uses the fixed starter from the matchup
    pitching plan.
    """

    probability_provider: (
        CanonicalPlateAppearanceProbabilityProvider
    )
    pitching_manager: Optional[
        CanonicalPitchingManager
    ] = None
    starter_hook_policy: Optional[
        CanonicalStarterHookPolicy
    ] = None
    opener_hook_policy: Optional[
        CanonicalStarterHookPolicy
    ] = None
    bulk_follower_hook_policy: Optional[
        CanonicalBulkFollowerHookPolicy
    ] = None
    bullpen_selector: Optional[
        CanonicalBullpenSelector
    ] = None
    reliever_hook_policy: Optional[
        CanonicalRelieverHookPolicy
    ] = None
    away_bullpen: Optional[
        Tuple[CanonicalBullpenPitcher, ...]
    ] = None
    home_bullpen: Optional[
        Tuple[CanonicalBullpenPitcher, ...]
    ] = None
    batter_handedness_by_id: Optional[
        Mapping[str, str]
    ] = None
    version: str = (
        CANONICAL_PA_RESOLVER_FACTORY_VERSION
    )

    def __post_init__(self) -> None:
        if not callable(self.probability_provider):
            raise TypeError(
                "probability_provider must be callable"
            )

        if self.version != (
            CANONICAL_PA_RESOLVER_FACTORY_VERSION
        ):
            raise ValueError(
                "unsupported canonical PA resolver "
                "factory version"
            )

    def __call__(
        self,
        context: CanonicalTrialResolverContext,
    ) -> PlateAppearanceResolver:
        if not isinstance(
            context,
            CanonicalTrialResolverContext,
        ):
            raise TypeError(
                "context must be a "
                "CanonicalTrialResolverContext"
            )

        matchup_input = context.matchup_input

        if matchup_input is None:
            raise ValueError(
                "canonical PA resolver requires "
                "matchup_input"
            )

        if not isinstance(
            matchup_input,
            CanonicalMatchupInput,
        ):
            raise TypeError(
                "matchup_input must be a "
                "CanonicalMatchupInput"
            )

        pitching_manager = None

        if (
            self.away_bullpen is not None
            and self.home_bullpen is not None
        ):
            pitching_manager = CanonicalPitchingManager(
                matchup_input=matchup_input,
                starter_hook_policy=(
                    self.starter_hook_policy
                    or build_baseline_starter_hook_policy()
                ),
                opener_hook_policy=(
                    self.opener_hook_policy
                    or build_baseline_opener_hook_policy()
                ),
                bulk_follower_hook_policy=(
                    self.bulk_follower_hook_policy
                    or build_baseline_bulk_follower_hook_policy()
                ),
                bullpen_selector=(
                    self.bullpen_selector
                    or build_canonical_bullpen_selector()
                ),
                reliever_hook_policy=(
                    self.reliever_hook_policy
                    or build_baseline_reliever_hook_policy()
                ),
                away_bullpen=self.away_bullpen,
                home_bullpen=self.home_bullpen,
                batter_handedness_by_id=(
                    self.batter_handedness_by_id
                ),
            )

        return _CanonicalPlateAppearanceResolver(
            context=context,
            matchup_input=matchup_input,
            probability_provider=(
                self.probability_provider
            ),
            pitching_manager=pitching_manager,
        )


@dataclass(frozen=True)
class _CanonicalPlateAppearanceResolver:
    """Fresh immutable resolver owned by exactly one trial."""

    context: CanonicalTrialResolverContext
    matchup_input: CanonicalMatchupInput
    probability_provider: (
        CanonicalPlateAppearanceProbabilityProvider
    )

    pitching_manager: Optional[
        CanonicalPitchingManager
    ] = None
    scored_run_count: int = 0
    registered_automatic_runner_keys: Tuple[
        Tuple[int, str, str],
        ...,
    ] = ()

    def active_pitcher_id(
        self,
        state: GameState,
    ) -> str:
        """
        Return the current fielding pitcher without making a hook decision.

        This read-only identity bridge allows non-plate-appearance
        resolvers to consume the same trial-owned pitching lifecycle.
        """

        if not isinstance(state, GameState):
            raise TypeError(
                "state must be a GameState"
            )

        if self.pitching_manager is None:
            return _fixed_pitcher_for_state(
                matchup_input=self.matchup_input,
                state=state,
            )

        if state.half == "top":
            team_side = "home"
        elif state.half == "bottom":
            team_side = "away"
        else:
            raise ValueError(
                "state half must be 'top' or 'bottom'"
            )

        return (
            self.pitching_manager
            .active_lifecycle(team_side)
            .pitcher_id
        )

    def _register_automatic_runner(
        self,
        state: GameState,
    ) -> None:
        if self.pitching_manager is None:
            return

        automatic_runner_id = state.bases[1]
        automatic_runner_key = (
            state.inning,
            state.half,
            automatic_runner_id or "",
        )

        should_register = (
            state.outs == 0
            and state.plate_appearance_number >= 0
            and automatic_runner_id is not None
            and automatic_runner_key
            not in self.registered_automatic_runner_keys
            and state.inning
            > self.context.regulation_innings
        )

        if not should_register:
            return

        self.pitching_manager.register_automatic_runner(
            state=state,
            runner_id=automatic_runner_id,
        )

        object.__setattr__(
            self,
            "registered_automatic_runner_keys",
            (
                self.registered_automatic_runner_keys
                + (automatic_runner_key,)
            ),
        )

    def record_baserunning_event(
        self,
        event: PlayEvent,
    ) -> None:
        """Synchronize a non-PA event with pitching state."""

        if not isinstance(event, PlayEvent):
            raise TypeError(
                "event must be a PlayEvent"
            )

        if event.is_plate_appearance:
            raise ValueError(
                "baserunning event must not be a "
                "plate appearance"
            )

        self._register_automatic_runner(
            event.state_before
        )

        if self.pitching_manager is None:
            return

        self.pitching_manager.record_baserunning_event(
            event
        )

        object.__setattr__(
            self,
            "scored_run_count",
            self.scored_run_count
            + len(event.runs_scored),
        )

    def earned_run_reconstruction_complete(
        self,
    ) -> bool:
        if self.pitching_manager is None:
            return False

        reconstructed_count = len(
            self.pitching_manager
            .run_classifications()
        )

        return reconstructed_count == self.scored_run_count

    def reconstructed_pitcher_run_lines(
        self,
    ):
        if self.pitching_manager is None:
            return ()

        return (
            self.pitching_manager
            .reconstructed_pitcher_run_lines()
        )

    def __call__(
        self,
        state: GameState,
        batter_id: str,
        sequence: int,
    ) -> PlayEvent:
        if not isinstance(state, GameState):
            raise TypeError(
                "state must be a GameState"
            )

        self._register_automatic_runner(state)

        pitcher_id = (
            self.pitching_manager
            .pitcher_for_plate_appearance(
                state=state,
                batter_id=batter_id,
            )
            if self.pitching_manager is not None
            else _fixed_pitcher_for_state(
                matchup_input=self.matchup_input,
                state=state,
            )
        )

        query = CanonicalPlateAppearanceQuery(
            matchup_input=self.matchup_input,
            state=state,
            batter_id=batter_id,
            pitcher_id=pitcher_id,
            sequence=sequence,
            trial_index=self.context.trial_index,
            trial_seed=self.context.trial_seed,
        )

        probabilities = self.probability_provider(
            query
        )

        if not isinstance(
            probabilities,
            CanonicalPlateAppearanceProbabilities,
        ):
            raise TypeError(
                "probability provider must return "
                "CanonicalPlateAppearanceProbabilities"
            )

        if probabilities.query != query:
            raise ValueError(
                "probability provider returned a "
                "distribution for a different query"
            )

        sampled = sample_canonical_plate_appearance(
            probabilities
        )

        event = (
            resolve_canonical_sampled_plate_appearance(
                sampled
            )
        )

        if self.pitching_manager is not None:
            self.pitching_manager.record_plate_appearance(
                event
            )

            object.__setattr__(
                self,
                "scored_run_count",
                self.scored_run_count
                + len(event.runs_scored),
            )

        return event


def _fixed_pitcher_for_state(
    *,
    matchup_input: CanonicalMatchupInput,
    state: GameState,
) -> str:
    """
    Select the fixed starting pitcher for the fielding side.

    Top half: home starter.
    Bottom half: away starter.
    """

    if state.half == "top":
        return (
            matchup_input
            .home_pitching_plan
            .starter_id
        )

    if state.half == "bottom":
        return (
            matchup_input
            .away_pitching_plan
            .starter_id
        )

    raise ValueError(
        "state half must be 'top' or 'bottom'"
    )


def build_canonical_pa_resolver_factory(
    probability_provider: (
        CanonicalPlateAppearanceProbabilityProvider
    ),
) -> CanonicalTrialResolverFactory:
    """Build the execution-plan-compatible resolver factory."""

    return CanonicalPlateAppearanceResolverFactory(
        probability_provider=probability_provider,
    )

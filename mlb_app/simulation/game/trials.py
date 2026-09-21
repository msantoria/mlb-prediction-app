"""Run and aggregate coherent canonical game trials."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import (
    Callable,
    Optional,
    Tuple,
)

from mlb_app.simulation.box_score import (
    BatterDfsScoringRules,
    PitcherDfsScoringRules,
    ReducedBoxScore,
)
from mlb_app.simulation.projections import (
    CanonicalProjectionPayload,
    aggregate_projection_payload,
)

from .box_score import (
    GameBoxScoreReconciliation,
    reduce_canonical_game_box_score,
    validate_game_box_score_reconciliation,
)
from .defensive_event_authority import (
    CanonicalDefensiveEventAuthoritySummary,
    aggregate_canonical_defensive_event_authority,
)
from .executed_trial import (
    CanonicalExecutedTrial,
    overlay_reconstructed_pitcher_run_lines,
)
from .contracts import (
    CanonicalGameResult,
    GameCompletionReason,
)
from .validation import validate_canonical_game


CanonicalTrialFactory = Callable[
    [int],
    object,
]


@dataclass(frozen=True)
class DistributionPoint:
    """One discrete outcome and its observed probability."""

    value: int
    probability: float

    def __post_init__(self) -> None:
        if not 0.0 <= self.probability <= 1.0:
            raise ValueError(
                "probability must be between 0 and 1"
            )


@dataclass(frozen=True)
class ProbabilityMetric:
    """One named observed trial frequency."""

    name: str
    probability: float

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError(
                "probability metric name is required"
            )
        if not 0.0 <= self.probability <= 1.0:
            raise ValueError(
                "probability must be between 0 and 1"
            )


@dataclass(frozen=True)
class CanonicalGameOutcomeProjection:
    """Observed game-level outcomes from canonical trials."""

    simulation_count: int
    away_win_probability: float
    home_win_probability: float
    tie_probability: float
    extra_innings_probability: float
    walk_off_probability: float
    away_run_distribution: Tuple[
        DistributionPoint,
        ...,
    ]
    home_run_distribution: Tuple[
        DistributionPoint,
        ...,
    ]
    total_run_distribution: Tuple[
        DistributionPoint,
        ...,
    ]
    team_total_probabilities: Tuple[
        ProbabilityMetric,
        ...,
    ]
    total_probabilities: Tuple[
        ProbabilityMetric,
        ...,
    ]

    def __post_init__(self) -> None:
        if self.simulation_count <= 0:
            raise ValueError(
                "simulation_count must be positive"
            )

        for name, value in (
            (
                "away_win_probability",
                self.away_win_probability,
            ),
            (
                "home_win_probability",
                self.home_win_probability,
            ),
            (
                "tie_probability",
                self.tie_probability,
            ),
            (
                "extra_innings_probability",
                self.extra_innings_probability,
            ),
            (
                "walk_off_probability",
                self.walk_off_probability,
            ),
        ):
            if not 0.0 <= value <= 1.0:
                raise ValueError(
                    f"{name} must be between 0 and 1"
                )

        outcome_total = (
            self.away_win_probability
            + self.home_win_probability
            + self.tie_probability
        )

        if abs(outcome_total - 1.0) > 0.00001:
            raise ValueError(
                "win and tie probabilities must sum to 1"
            )

        _validate_distribution(
            self.away_run_distribution
        )
        _validate_distribution(
            self.home_run_distribution
        )
        _validate_distribution(
            self.total_run_distribution
        )
        _validate_probability_order(
            self.team_total_probabilities
        )
        _validate_probability_order(
            self.total_probabilities
        )


@dataclass(frozen=True)
class CanonicalTrialDiagnostics:
    """Trial-level coherence and reduction diagnostics."""

    game_validation_pass_rate: float
    box_score_reconciliation_pass_rate: float
    warnings: Tuple[str, ...] = field(
        default_factory=tuple
    )
    defensive_event_authority: (
        CanonicalDefensiveEventAuthoritySummary
    ) = field(
        default_factory=(
            CanonicalDefensiveEventAuthoritySummary.empty
        )
    )

    def __post_init__(self) -> None:
        for name, value in (
            (
                "game_validation_pass_rate",
                self.game_validation_pass_rate,
            ),
            (
                "box_score_reconciliation_pass_rate",
                self.box_score_reconciliation_pass_rate,
            ),
        ):
            if not 0.0 <= value <= 1.0:
                raise ValueError(
                    f"{name} must be between 0 and 1"
                )

        if not isinstance(
            self.defensive_event_authority,
            CanonicalDefensiveEventAuthoritySummary,
        ):
            raise TypeError(
                "defensive_event_authority must be a "
                "CanonicalDefensiveEventAuthoritySummary"
            )


@dataclass(frozen=True)
class CanonicalTrialBatch:
    """
    One coherent collection of canonical game simulations.

    The outcome projection and player projection payload are both
    derived from the exact same game trials and reduced box scores.
    """

    games: Tuple[CanonicalGameResult, ...]
    box_scores: Tuple[ReducedBoxScore, ...]
    reconciliations: Tuple[
        GameBoxScoreReconciliation,
        ...,
    ]
    outcomes: CanonicalGameOutcomeProjection
    projections: CanonicalProjectionPayload
    diagnostics: CanonicalTrialDiagnostics

    def __post_init__(self) -> None:
        count = len(self.games)

        if count == 0:
            raise ValueError(
                "canonical trial batch cannot be empty"
            )
        if len(self.box_scores) != count:
            raise ValueError(
                "box score count must match game count"
            )
        if len(self.reconciliations) != count:
            raise ValueError(
                "reconciliation count must match game count"
            )
        if self.outcomes.simulation_count != count:
            raise ValueError(
                "outcome count must match game count"
            )
        if self.projections.simulation_count != count:
            raise ValueError(
                "projection count must match game count"
            )


def run_canonical_trials(
    *,
    trial_factory: CanonicalTrialFactory,
    simulations: int,
    model_version: str,
    batter_dfs_rules: Optional[
        BatterDfsScoringRules
    ] = None,
    pitcher_dfs_rules: Optional[
        PitcherDfsScoringRules
    ] = None,
) -> CanonicalTrialBatch:
    """
    Run, reduce, validate, and aggregate canonical game trials.

    ``trial_factory`` receives the zero-based trial index. This keeps
    seed derivation and resolver construction outside this generic
    orchestration layer.
    """

    if not callable(trial_factory):
        raise TypeError(
            "trial_factory must be callable"
        )
    if simulations <= 0:
        raise ValueError(
            "simulations must be positive"
        )
    if not model_version:
        raise ValueError(
            "model_version is required"
        )

    games = []
    box_scores = []
    reconciliations = []
    game_validation_values = []
    defensive_event_authority_records = []

    for trial_index in range(simulations):
        produced = trial_factory(trial_index)

        if isinstance(
            produced,
            CanonicalExecutedTrial,
        ):
            game = produced.game
            reconstructed_lines = (
                produced
                .reconstructed_pitcher_run_lines
            )
            reconstruction_complete = (
                produced
                .earned_run_reconstruction_complete
            )
            defensive_event_authority_records.extend(
                produced.defensive_event_authority_records
            )
        elif isinstance(
            produced,
            CanonicalGameResult,
        ):
            game = produced
            reconstructed_lines = None
            reconstruction_complete = False
        else:
            raise TypeError(
                "trial_factory must return "
                "CanonicalGameResult or "
                "CanonicalExecutedTrial"
            )

        validation = validate_canonical_game(game)
        game_validation_values.append(
            validation.passed
        )

        if not validation.passed:
            raise ValueError(
                "canonical trial failed game validation "
                f"at index {trial_index}"
            )

        reduced = reduce_canonical_game_box_score(
            game
        )

        box_score = reduced.box_score

        if reconstruction_complete:
            box_score = (
                overlay_reconstructed_pitcher_run_lines(
                    box_score=box_score,
                    run_lines=reconstructed_lines,
                )
            )

            reconciliation = (
                validate_game_box_score_reconciliation(
                    result=game,
                    box_score=box_score,
                    game_validation_passed=(
                        validation.passed
                    ),
                )
            )
        else:
            reconciliation = (
                reduced.reconciliation
            )

        if not reconciliation.passed:
            raise ValueError(
                "canonical trial failed box-score "
                f"reconciliation at index {trial_index}"
            )

        games.append(game)
        box_scores.append(box_score)
        reconciliations.append(
            reconciliation
        )

    game_tuple = tuple(games)
    box_score_tuple = tuple(box_scores)
    reconciliation_tuple = tuple(
        reconciliations
    )

    outcomes = aggregate_game_outcomes(
        game_tuple
    )

    projection_payload = (
        aggregate_projection_payload(
            box_scores=box_score_tuple,
            model_version=model_version,
            replay_validation_passes=(
                game_validation_values
            ),
            batter_dfs_rules=batter_dfs_rules,
            pitcher_dfs_rules=pitcher_dfs_rules,
        )
    )

    game_pass_rate = _rate(
        game_validation_values
    )
    reconciliation_pass_rate = _rate(
        tuple(
            reconciliation.passed
            for reconciliation
            in reconciliation_tuple
        )
    )

    defensive_event_authority = (
        aggregate_canonical_defensive_event_authority(
            defensive_event_authority_records
        )
    )

    warnings = []

    if game_pass_rate < 1.0:
        warnings.append(
            "game_validation_failures_present"
        )
    if reconciliation_pass_rate < 1.0:
        warnings.append(
            "box_score_reconciliation_failures_present"
        )
    if outcomes.tie_probability > 0.0:
        warnings.append(
            "tied_games_present"
        )

    return CanonicalTrialBatch(
        games=game_tuple,
        box_scores=box_score_tuple,
        reconciliations=(
            reconciliation_tuple
        ),
        outcomes=outcomes,
        projections=projection_payload,
        diagnostics=CanonicalTrialDiagnostics(
            game_validation_pass_rate=(
                game_pass_rate
            ),
            box_score_reconciliation_pass_rate=(
                reconciliation_pass_rate
            ),
            warnings=tuple(sorted(warnings)),
            defensive_event_authority=(
                defensive_event_authority
            ),
        ),
    )


def aggregate_game_outcomes(
    games: Tuple[CanonicalGameResult, ...],
) -> CanonicalGameOutcomeProjection:
    """Aggregate observed frequencies from canonical game results."""

    if not games:
        raise ValueError(
            "at least one canonical game is required"
        )

    simulations = len(games)

    away_runs = Counter(
        game.away_score for game in games
    )
    home_runs = Counter(
        game.home_score for game in games
    )
    total_runs = Counter(
        game.total_runs for game in games
    )

    away_wins = sum(
        game.away_score > game.home_score
        for game in games
    )
    home_wins = sum(
        game.home_score > game.away_score
        for game in games
    )
    ties = simulations - away_wins - home_wins

    extra_innings_games = sum(
        game.went_to_extras
        for game in games
    )
    walk_off_games = sum(
        game.completion_reason
        is GameCompletionReason.WALK_OFF
        for game in games
    )

    team_total_probability_metrics = []

    for threshold in (3, 4, 5):
        team_total_probability_metrics.extend(
            (
                ProbabilityMetric(
                    name=f"away_{threshold}_plus",
                    probability=_round(
                        sum(
                            game.away_score >= threshold
                            for game in games
                        )
                        / simulations
                    ),
                ),
                ProbabilityMetric(
                    name=f"home_{threshold}_plus",
                    probability=_round(
                        sum(
                            game.home_score >= threshold
                            for game in games
                        )
                        / simulations
                    ),
                ),
            )
        )

    total_probability_metrics = []

    for line in (6.5, 7.5, 8.5, 9.5, 10.5):
        total_probability_metrics.extend(
            (
                ProbabilityMetric(
                    name=f"over_{line}",
                    probability=_round(
                        sum(
                            game.total_runs > line
                            for game in games
                        )
                        / simulations
                    ),
                ),
                ProbabilityMetric(
                    name=f"under_{line}",
                    probability=_round(
                        sum(
                            game.total_runs < line
                            for game in games
                        )
                        / simulations
                    ),
                ),
            )
        )

    return CanonicalGameOutcomeProjection(
        simulation_count=simulations,
        away_win_probability=_round(
            away_wins / simulations
        ),
        home_win_probability=_round(
            home_wins / simulations
        ),
        tie_probability=_round(
            ties / simulations
        ),
        extra_innings_probability=_round(
            extra_innings_games / simulations
        ),
        walk_off_probability=_round(
            walk_off_games / simulations
        ),
        away_run_distribution=_distribution(
            away_runs,
            simulations,
        ),
        home_run_distribution=_distribution(
            home_runs,
            simulations,
        ),
        total_run_distribution=_distribution(
            total_runs,
            simulations,
        ),
        team_total_probabilities=tuple(
            sorted(
                team_total_probability_metrics,
                key=lambda metric: metric.name,
            )
        ),
        total_probabilities=tuple(
            sorted(
                total_probability_metrics,
                key=lambda metric: metric.name,
            )
        ),
    )


def _distribution(
    counter: Counter,
    simulations: int,
) -> Tuple[DistributionPoint, ...]:
    return tuple(
        DistributionPoint(
            value=value,
            probability=_round(
                count / simulations
            ),
        )
        for value, count in sorted(
            counter.items()
        )
    )


def _validate_distribution(
    values: Tuple[DistributionPoint, ...],
) -> None:
    if not values:
        raise ValueError(
            "distribution cannot be empty"
        )

    points = tuple(
        point.value for point in values
    )

    if points != tuple(sorted(set(points))):
        raise ValueError(
            "distribution values must be unique "
            "and ordered"
        )

    probability_total = sum(
        point.probability for point in values
    )

    if abs(probability_total - 1.0) > 0.00001:
        raise ValueError(
            "distribution probabilities must sum to 1"
        )


def _validate_probability_order(
    values: Tuple[ProbabilityMetric, ...],
) -> None:
    names = tuple(
        value.name for value in values
    )

    if not names:
        raise ValueError(
            "probability metrics cannot be empty"
        )
    if names != tuple(sorted(names)):
        raise ValueError(
            "probability metrics must be ordered"
        )
    if len(names) != len(set(names)):
        raise ValueError(
            "probability metric names must be unique"
        )


def _rate(values) -> float:
    values = tuple(bool(value) for value in values)

    if not values:
        raise ValueError(
            "cannot calculate an empty rate"
        )

    return _round(
        sum(values) / len(values)
    )


def _round(value: float) -> float:
    return round(float(value), 6)

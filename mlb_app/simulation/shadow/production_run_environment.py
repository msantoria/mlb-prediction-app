"""Measure scoring behavior from one production-owned trial batch."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
import math
from typing import Mapping, Tuple

from mlb_app.simulation.projections.aggregator import (
    summarize_values,
)
from mlb_app.simulation.projections.contracts import (
    StatisticalSummary,
)


CANONICAL_PRODUCTION_RUN_ENVIRONMENT_VERSION = (
    "canonical_production_run_environment_v1"
)

CountPairs = Tuple[Tuple[str, int], ...]
RatePairs = Tuple[Tuple[str, float], ...]


def _validate_rate(name: str, value: float) -> None:
    if not math.isfinite(value) or not 0.0 <= value <= 1.0:
        raise ValueError(f"{name} must be between zero and one")


def _validate_digest(value: str) -> None:
    if len(value) != 64:
        raise ValueError("artifact_digest must be a SHA-256 hex digest")
    try:
        int(value, 16)
    except ValueError as exc:
        raise ValueError(
            "artifact_digest must be a SHA-256 hex digest"
        ) from exc


def _pairs_to_dict(values):
    return {name: value for name, value in values}


@dataclass(frozen=True)
class CanonicalProductionRunEnvironment:
    """Observational scoring summary for one production execution."""

    simulation_count: int
    away_runs: StatisticalSummary
    home_runs: StatisticalSummary
    total_runs: StatisticalSummary
    box_score_metric_means: RatePairs
    scoring_rates: RatePairs
    total_threshold_rates: RatePairs
    probability_tier_counts: CountPairs
    probability_resolution_count: int
    probability_fallback_rate: float
    defensive_authority_observation_count: int
    defensive_authority_rate: float
    box_score_run_mismatch_count: int
    artifact_digest: str
    schema_version: str = (
        CANONICAL_PRODUCTION_RUN_ENVIRONMENT_VERSION
    )

    def __post_init__(self) -> None:
        if self.schema_version != (
            CANONICAL_PRODUCTION_RUN_ENVIRONMENT_VERSION
        ):
            raise ValueError(
                "unsupported production run-environment version"
            )
        if self.simulation_count <= 0:
            raise ValueError("simulation_count must be positive")
        for name, summary in (
            ("away_runs", self.away_runs),
            ("home_runs", self.home_runs),
            ("total_runs", self.total_runs),
        ):
            if not isinstance(summary, StatisticalSummary):
                raise TypeError(
                    f"{name} must be a StatisticalSummary"
                )
            if summary.count != self.simulation_count:
                raise ValueError(
                    f"{name} count must match simulation_count"
                )
        for collection_name, values in (
            ("box_score_metric_means", self.box_score_metric_means),
            ("scoring_rates", self.scoring_rates),
            ("total_threshold_rates", self.total_threshold_rates),
        ):
            names = tuple(name for name, _ in values)
            if len(names) != len(set(names)):
                raise ValueError(
                    f"{collection_name} names must be unique"
                )
            for name, value in values:
                if not name or not math.isfinite(value) or value < 0.0:
                    raise ValueError(
                        f"invalid {collection_name} entry"
                    )
        for name, value in self.scoring_rates:
            _validate_rate(name, value)
        for name, value in self.total_threshold_rates:
            _validate_rate(name, value)
        tier_names = tuple(name for name, _ in self.probability_tier_counts)
        if len(tier_names) != len(set(tier_names)):
            raise ValueError("probability tier names must be unique")
        if any(
            not name or count < 0
            for name, count in self.probability_tier_counts
        ):
            raise ValueError("invalid probability tier count")
        if self.probability_resolution_count < 0:
            raise ValueError(
                "probability_resolution_count cannot be negative"
            )
        if sum(count for _, count in self.probability_tier_counts) != (
            self.probability_resolution_count
        ):
            raise ValueError(
                "probability tier counts must reconcile"
            )
        _validate_rate(
            "probability_fallback_rate",
            self.probability_fallback_rate,
        )
        if self.defensive_authority_observation_count < 0:
            raise ValueError(
                "defensive authority count cannot be negative"
            )
        _validate_rate(
            "defensive_authority_rate",
            self.defensive_authority_rate,
        )
        if not 0 <= self.box_score_run_mismatch_count <= (
            self.simulation_count
        ):
            raise ValueError(
                "box-score mismatch count must be bounded"
            )
        _validate_digest(self.artifact_digest)

    def to_diagnostics(self) -> Mapping[str, object]:
        return {
            "schema_version": self.schema_version,
            "status": "ready",
            "ready": True,
            "simulation_count": self.simulation_count,
            "away_runs": asdict(self.away_runs),
            "home_runs": asdict(self.home_runs),
            "total_runs": asdict(self.total_runs),
            "box_score_metric_means": _pairs_to_dict(
                self.box_score_metric_means
            ),
            "scoring_rates": _pairs_to_dict(self.scoring_rates),
            "total_threshold_rates": _pairs_to_dict(
                self.total_threshold_rates
            ),
            "probability_tier_counts": _pairs_to_dict(
                self.probability_tier_counts
            ),
            "probability_resolution_count": (
                self.probability_resolution_count
            ),
            "probability_fallback_rate": (
                self.probability_fallback_rate
            ),
            "defensive_authority_observation_count": (
                self.defensive_authority_observation_count
            ),
            "defensive_authority_rate": (
                self.defensive_authority_rate
            ),
            "box_score_run_mismatch_count": (
                self.box_score_run_mismatch_count
            ),
            "artifact_digest": self.artifact_digest,
            "source": "production_owned_canonical_trial_batch",
            "trial_batch_consumed": True,
            "independent_trial_execution": False,
            "measurement_only": True,
            "calibration_parameters_selected": False,
            "activation_permitted": False,
            "production_authority_changed": False,
        }


def _ratio(numerator: int, denominator: int) -> float:
    if denominator == 0:
        return 0.0
    return round(numerator / denominator, 6)


def _mean(total: int, count: int) -> float:
    return round(total / count, 6)


def _artifact_digest(payload: Mapping[str, object]) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def measure_canonical_production_run_environment(
    execution,
) -> CanonicalProductionRunEnvironment:
    """Measure one already-completed production execution."""

    from .production_execution import (
        CanonicalProductionShadowExecution,
    )

    if not isinstance(
        execution,
        CanonicalProductionShadowExecution,
    ):
        raise TypeError(
            "execution must be a "
            "CanonicalProductionShadowExecution"
        )
    if not execution.executed:
        raise ValueError(
            "executed production shadow is required"
        )
    if execution.trial_batch is None:
        raise ValueError(
            "production execution has no trial batch"
        )
    if execution.material is None:
        raise ValueError(
            "production execution has no execution material"
        )

    batch = execution.trial_batch
    simulation_count = len(batch.games)
    away_values = tuple(game.away_score for game in batch.games)
    home_values = tuple(game.home_score for game in batch.games)
    total_values = tuple(game.total_runs for game in batch.games)

    totals = {
        "plate_appearances": 0,
        "at_bats": 0,
        "hits": 0,
        "singles": 0,
        "doubles": 0,
        "triples": 0,
        "home_runs": 0,
        "walks": 0,
        "hit_by_pitch": 0,
        "strikeouts": 0,
        "reached_on_error": 0,
        "sacrifice_flies": 0,
        "stolen_bases": 0,
        "caught_stealing": 0,
        "runs": 0,
        "left_on_base": 0,
        "errors": 0,
    }
    mismatch_count = 0

    for game, box_score in zip(batch.games, batch.box_scores):
        if (
            box_score.away.runs != game.away_score
            or box_score.home.runs != game.home_score
        ):
            mismatch_count += 1
        totals["runs"] += box_score.away.runs + box_score.home.runs
        totals["left_on_base"] += (
            box_score.away.left_on_base
            + box_score.home.left_on_base
        )
        totals["errors"] += (
            box_score.away.errors + box_score.home.errors
        )
        for batter in box_score.batters:
            for name in (
                "plate_appearances",
                "at_bats",
                "singles",
                "doubles",
                "triples",
                "home_runs",
                "walks",
                "hit_by_pitch",
                "strikeouts",
                "reached_on_error",
                "sacrifice_flies",
                "stolen_bases",
                "caught_stealing",
            ):
                totals[name] += getattr(batter, name)
            totals["hits"] += batter.hits

    plate_appearances = totals["plate_appearances"]
    hits = totals["hits"]
    reaches = (
        hits
        + totals["walks"]
        + totals["hit_by_pitch"]
        + totals["reached_on_error"]
    )
    extra_base_hits = (
        totals["doubles"]
        + totals["triples"]
        + totals["home_runs"]
    )

    box_score_metric_means = tuple(
        (name + "_per_game", _mean(value, simulation_count))
        for name, value in sorted(totals.items())
    ) + (
        ("runs_per_reach", _ratio(totals["runs"], reaches)),
    )

    scoring_rates = (
        ("hit_rate_per_pa", _ratio(hits, plate_appearances)),
        (
            "walk_rate_per_pa",
            _ratio(totals["walks"], plate_appearances),
        ),
        (
            "hit_by_pitch_rate_per_pa",
            _ratio(totals["hit_by_pitch"], plate_appearances),
        ),
        (
            "strikeout_rate_per_pa",
            _ratio(totals["strikeouts"], plate_appearances),
        ),
        (
            "home_run_rate_per_pa",
            _ratio(totals["home_runs"], plate_appearances),
        ),
        ("reach_rate_per_pa", _ratio(reaches, plate_appearances)),
        (
            "extra_base_hit_share",
            _ratio(extra_base_hits, hits),
        ),
        (
            "stolen_base_success_rate",
            _ratio(
                totals["stolen_bases"],
                totals["stolen_bases"] + totals["caught_stealing"],
            ),
        ),
    )

    total_threshold_rates = (
        (
            "away_shutout_rate",
            _ratio(sum(value == 0 for value in away_values), simulation_count),
        ),
        (
            "home_shutout_rate",
            _ratio(sum(value == 0 for value in home_values), simulation_count),
        ),
        (
            "total_runs_5_or_fewer_rate",
            _ratio(sum(value <= 5 for value in total_values), simulation_count),
        ),
        (
            "total_runs_6_or_fewer_rate",
            _ratio(sum(value <= 6 for value in total_values), simulation_count),
        ),
        (
            "total_runs_7_or_fewer_rate",
            _ratio(sum(value <= 7 for value in total_values), simulation_count),
        ),
        (
            "total_runs_8_or_fewer_rate",
            _ratio(sum(value <= 8 for value in total_values), simulation_count),
        ),
        (
            "total_runs_9_or_more_rate",
            _ratio(sum(value >= 9 for value in total_values), simulation_count),
        ),
    )

    probability = (
        execution.material.probability_resolution_diagnostics
    )
    probability_tier_counts = tuple(
        (usage.tier.value, usage.count)
        for usage in probability.tier_usage
    )
    authority = batch.diagnostics.defensive_event_authority

    digest_payload = {
        "schema_version": (
            CANONICAL_PRODUCTION_RUN_ENVIRONMENT_VERSION
        ),
        "simulation_count": simulation_count,
        "away_runs": asdict(summarize_values(away_values)),
        "home_runs": asdict(summarize_values(home_values)),
        "total_runs": asdict(summarize_values(total_values)),
        "box_score_metric_means": dict(box_score_metric_means),
        "scoring_rates": dict(scoring_rates),
        "total_threshold_rates": dict(total_threshold_rates),
        "probability_tier_counts": dict(probability_tier_counts),
        "probability_resolution_count": probability.total_resolutions,
        "defensive_authority_observation_count": (
            authority.observation_count
        ),
        "defensive_authority_rate": authority.authority_rate,
        "box_score_run_mismatch_count": mismatch_count,
    }

    return CanonicalProductionRunEnvironment(
        simulation_count=simulation_count,
        away_runs=summarize_values(away_values),
        home_runs=summarize_values(home_values),
        total_runs=summarize_values(total_values),
        box_score_metric_means=box_score_metric_means,
        scoring_rates=scoring_rates,
        total_threshold_rates=total_threshold_rates,
        probability_tier_counts=probability_tier_counts,
        probability_resolution_count=probability.total_resolutions,
        probability_fallback_rate=round(probability.fallback_rate, 6),
        defensive_authority_observation_count=(
            authority.observation_count
        ),
        defensive_authority_rate=authority.authority_rate,
        box_score_run_mismatch_count=mismatch_count,
        artifact_digest=_artifact_digest(digest_payload),
    )

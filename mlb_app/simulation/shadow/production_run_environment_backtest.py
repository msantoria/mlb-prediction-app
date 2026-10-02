"""Compare production simulation scoring with observed MLB games."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
from typing import Mapping, Optional, Tuple

from .observed_run_environment_source import (
    CanonicalObservedRunEnvironment,
)
from .production_run_environment import (
    CanonicalProductionRunEnvironment,
)


CANONICAL_PRODUCTION_RUN_ENVIRONMENT_BACKTEST_VERSION = (
    "canonical_production_run_environment_backtest_v1"
)

DeltaPairs = Tuple[Tuple[str, float], ...]
LOW_TOTAL_COMPONENTS = (
    "opportunity_volume",
    "reach_creation",
    "power",
    "run_conversion",
)


def _validate_digest(name: str, value: str) -> None:
    if len(value) != 64:
        raise ValueError(f"{name} must be a SHA-256 hex digest")
    try:
        int(value, 16)
    except ValueError as exc:
        raise ValueError(
            f"{name} must be a SHA-256 hex digest"
        ) from exc


def _validate_pairs(name: str, values: DeltaPairs) -> None:
    names = tuple(key for key, _ in values)
    if len(names) != len(set(names)):
        raise ValueError(f"{name} names must be unique")
    for key, value in values:
        if not key or not math.isfinite(value):
            raise ValueError(f"invalid {name} entry")


def _pairs_to_dict(values: DeltaPairs) -> Mapping[str, float]:
    return {name: value for name, value in values}


@dataclass(frozen=True)
class CanonicalProductionRunEnvironmentBacktest:
    """Measurement-only simulation versus observed comparison."""

    production_schema_version: str
    observed_schema_version: str
    simulation_count: int
    observed_game_count: int
    observed_source_identifier: str
    production_artifact_digest: str
    observed_artifact_digest: str
    total_run_mean_delta: float
    total_run_mean_relative_delta: float
    run_distribution_deltas: DeltaPairs
    comparable_metric_deltas: DeltaPairs
    comparable_metric_relative_deltas: DeltaPairs
    threshold_rate_deltas: DeltaPairs
    component_relative_deltas: DeltaPairs
    low_total_signal: bool
    largest_negative_component: Optional[str]
    artifact_digest: str
    schema_version: str = (
        CANONICAL_PRODUCTION_RUN_ENVIRONMENT_BACKTEST_VERSION
    )

    def __post_init__(self) -> None:
        if self.schema_version != (
            CANONICAL_PRODUCTION_RUN_ENVIRONMENT_BACKTEST_VERSION
        ):
            raise ValueError(
                "unsupported production run-environment backtest version"
            )
        if not self.production_schema_version:
            raise ValueError(
                "production_schema_version is required"
            )
        if not self.observed_schema_version:
            raise ValueError(
                "observed_schema_version is required"
            )
        if self.simulation_count <= 0:
            raise ValueError("simulation_count must be positive")
        if self.observed_game_count <= 0:
            raise ValueError("observed_game_count must be positive")
        if not self.observed_source_identifier.strip():
            raise ValueError(
                "observed_source_identifier is required"
            )
        _validate_digest(
            "production_artifact_digest",
            self.production_artifact_digest,
        )
        _validate_digest(
            "observed_artifact_digest",
            self.observed_artifact_digest,
        )
        _validate_digest("artifact_digest", self.artifact_digest)
        for name, value in (
            ("total_run_mean_delta", self.total_run_mean_delta),
            (
                "total_run_mean_relative_delta",
                self.total_run_mean_relative_delta,
            ),
        ):
            if not math.isfinite(value):
                raise ValueError(f"{name} must be finite")
        for name, values in (
            (
                "run_distribution_deltas",
                self.run_distribution_deltas,
            ),
            (
                "comparable_metric_deltas",
                self.comparable_metric_deltas,
            ),
            (
                "comparable_metric_relative_deltas",
                self.comparable_metric_relative_deltas,
            ),
            (
                "threshold_rate_deltas",
                self.threshold_rate_deltas,
            ),
            (
                "component_relative_deltas",
                self.component_relative_deltas,
            ),
        ):
            _validate_pairs(name, values)
        component_names = tuple(
            name for name, _ in self.component_relative_deltas
        )
        if component_names != LOW_TOTAL_COMPONENTS:
            raise ValueError(
                "component relative deltas must use canonical order"
            )
        if self.low_total_signal != (
            self.total_run_mean_delta < 0.0
        ):
            raise ValueError(
                "low_total_signal must reconcile with total-run delta"
            )
        if self.largest_negative_component is not None:
            if self.largest_negative_component not in (
                LOW_TOTAL_COMPONENTS
            ):
                raise ValueError(
                    "invalid largest_negative_component"
                )
            values = dict(self.component_relative_deltas)
            if values[self.largest_negative_component] >= 0.0:
                raise ValueError(
                    "largest negative component must be negative"
                )

    @property
    def ready(self) -> bool:
        return True

    def to_diagnostics(self) -> Mapping[str, object]:
        return {
            "schema_version": self.schema_version,
            "status": "ready",
            "ready": self.ready,
            "production_schema_version": (
                self.production_schema_version
            ),
            "observed_schema_version": (
                self.observed_schema_version
            ),
            "simulation_count": self.simulation_count,
            "observed_game_count": self.observed_game_count,
            "observed_source_identifier": (
                self.observed_source_identifier
            ),
            "production_artifact_digest": (
                self.production_artifact_digest
            ),
            "observed_artifact_digest": (
                self.observed_artifact_digest
            ),
            "total_run_mean_delta": self.total_run_mean_delta,
            "total_run_mean_relative_delta": (
                self.total_run_mean_relative_delta
            ),
            "run_distribution_deltas": _pairs_to_dict(
                self.run_distribution_deltas
            ),
            "comparable_metric_deltas": _pairs_to_dict(
                self.comparable_metric_deltas
            ),
            "comparable_metric_relative_deltas": (
                _pairs_to_dict(
                    self.comparable_metric_relative_deltas
                )
            ),
            "threshold_rate_deltas": _pairs_to_dict(
                self.threshold_rate_deltas
            ),
            "component_relative_deltas": _pairs_to_dict(
                self.component_relative_deltas
            ),
            "low_total_signal": self.low_total_signal,
            "largest_negative_component": (
                self.largest_negative_component
            ),
            "artifact_digest": self.artifact_digest,
            "comparison_convention": "simulation_minus_observed",
            "opportunity_boundary": "at_bats_plus_walks_plus_hbp",
            "causal_claim_permitted": False,
            "measurement_only": True,
            "calibration_parameters_selected": False,
            "activation_permitted": False,
            "production_authority_changed": False,
        }


def _round(value: float) -> float:
    return round(float(value), 6)


def _delta(simulated: float, observed: float) -> float:
    return _round(simulated - observed)


def _relative_delta(
    simulated: float,
    observed: float,
) -> float:
    if observed == 0.0:
        if simulated == 0.0:
            return 0.0
        return 1.0 if simulated > 0.0 else -1.0
    return _round((simulated - observed) / observed)


def _require_metrics(
    values,
    *,
    source_name: str,
    required_names: Tuple[str, ...],
) -> Mapping[str, float]:
    metrics = dict(values)
    missing = tuple(
        name for name in required_names if name not in metrics
    )
    if missing:
        raise ValueError(
            f"{source_name} is missing comparable metrics: "
            + ", ".join(missing)
        )
    return metrics


def _safe_ratio(
    numerator: float,
    denominator: float,
) -> float:
    if denominator <= 0.0:
        return 0.0
    return _round(numerator / denominator)


def _canonical_comparable_metrics(
    environment,
    *,
    source_name: str,
) -> Mapping[str, float]:
    required = (
        "at_bats_per_game",
        "hits_per_game",
        "singles_per_game",
        "doubles_per_game",
        "triples_per_game",
        "home_runs_per_game",
        "walks_per_game",
        "hit_by_pitch_per_game",
        "strikeouts_per_game",
        "stolen_bases_per_game",
        "caught_stealing_per_game",
        "left_on_base_per_game",
        "errors_per_game",
        "runs_per_game",
    )
    raw = _require_metrics(
        environment.box_score_metric_means,
        source_name=source_name,
        required_names=required,
    )

    at_bats = raw["at_bats_per_game"]
    hits = raw["hits_per_game"]
    walks = raw["walks_per_game"]
    hit_by_pitch = raw["hit_by_pitch_per_game"]
    opportunities = at_bats + walks + hit_by_pitch
    known_reaches = hits + walks + hit_by_pitch
    extra_base_hits = (
        raw["doubles_per_game"]
        + raw["triples_per_game"]
        + raw["home_runs_per_game"]
    )
    steal_attempts = (
        raw["stolen_bases_per_game"]
        + raw["caught_stealing_per_game"]
    )

    comparable = {name: raw[name] for name in required}
    comparable.update(
        {
            "observed_opportunities_per_game": _round(
                opportunities
            ),
            "known_reaches_per_game": _round(known_reaches),
            "runs_per_known_reach": _safe_ratio(
                raw["runs_per_game"],
                known_reaches,
            ),
            "hit_rate_per_observed_opportunity": _safe_ratio(
                hits,
                opportunities,
            ),
            "walk_rate_per_observed_opportunity": _safe_ratio(
                walks,
                opportunities,
            ),
            "hit_by_pitch_rate_per_observed_opportunity": (
                _safe_ratio(hit_by_pitch, opportunities)
            ),
            "strikeout_rate_per_observed_opportunity": (
                _safe_ratio(
                    raw["strikeouts_per_game"],
                    opportunities,
                )
            ),
            "home_run_rate_per_observed_opportunity": (
                _safe_ratio(
                    raw["home_runs_per_game"],
                    opportunities,
                )
            ),
            "known_reach_rate_per_observed_opportunity": (
                _safe_ratio(known_reaches, opportunities)
            ),
            "extra_base_hit_share": _safe_ratio(
                extra_base_hits,
                hits,
            ),
            "stolen_base_success_rate": _safe_ratio(
                raw["stolen_bases_per_game"],
                steal_attempts,
            ),
        }
    )
    return comparable


def _summary_values(summary) -> Mapping[str, float]:
    return {
        "mean": float(summary.mean),
        "median": float(summary.median),
        "p10": float(summary.p10),
        "p25": float(summary.p25),
        "p75": float(summary.p75),
        "p90": float(summary.p90),
        "minimum": float(summary.minimum),
        "maximum": float(summary.maximum),
        "sd": float(summary.sd or 0.0),
    }


def _artifact_digest(payload: Mapping[str, object]) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def backtest_canonical_production_run_environment(
    production: CanonicalProductionRunEnvironment,
    observed: CanonicalObservedRunEnvironment,
) -> CanonicalProductionRunEnvironmentBacktest:
    """Compare existing production and observed artifacts."""

    if not isinstance(
        production,
        CanonicalProductionRunEnvironment,
    ):
        raise TypeError(
            "production must be a "
            "CanonicalProductionRunEnvironment"
        )
    if not isinstance(
        observed,
        CanonicalObservedRunEnvironment,
    ):
        raise TypeError(
            "observed must be a "
            "CanonicalObservedRunEnvironment"
        )

    production_metrics = _canonical_comparable_metrics(
        production,
        source_name="production",
    )
    observed_metrics = _canonical_comparable_metrics(
        observed,
        source_name="observed",
    )
    if set(production_metrics) != set(observed_metrics):
        raise ValueError(
            "comparable metric contracts must match"
        )

    comparable_metric_deltas = tuple(
        (
            name,
            _delta(
                production_metrics[name],
                observed_metrics[name],
            ),
        )
        for name in sorted(production_metrics)
    )
    comparable_metric_relative_deltas = tuple(
        (
            name,
            _relative_delta(
                production_metrics[name],
                observed_metrics[name],
            ),
        )
        for name in sorted(production_metrics)
    )

    production_distribution = _summary_values(
        production.total_runs
    )
    observed_distribution = _summary_values(
        observed.total_runs
    )
    run_distribution_deltas = tuple(
        (
            name,
            _delta(
                production_distribution[name],
                observed_distribution[name],
            ),
        )
        for name in (
            "mean",
            "median",
            "p10",
            "p25",
            "p75",
            "p90",
            "minimum",
            "maximum",
            "sd",
        )
    )

    production_thresholds = dict(
        production.total_threshold_rates
    )
    observed_thresholds = dict(
        observed.total_threshold_rates
    )
    if set(production_thresholds) != set(observed_thresholds):
        raise ValueError(
            "total threshold contracts must match"
        )
    threshold_rate_deltas = tuple(
        (
            name,
            _delta(
                production_thresholds[name],
                observed_thresholds[name],
            ),
        )
        for name, _ in production.total_threshold_rates
    )

    component_inputs = (
        (
            "opportunity_volume",
            "observed_opportunities_per_game",
        ),
        (
            "reach_creation",
            "known_reach_rate_per_observed_opportunity",
        ),
        (
            "power",
            "home_run_rate_per_observed_opportunity",
        ),
        (
            "run_conversion",
            "runs_per_known_reach",
        ),
    )
    component_relative_deltas = tuple(
        (
            component,
            _relative_delta(
                production_metrics[metric],
                observed_metrics[metric],
            ),
        )
        for component, metric in component_inputs
    )
    negative_components = tuple(
        (name, value)
        for name, value in component_relative_deltas
        if value < 0.0
    )
    largest_negative_component = (
        min(negative_components, key=lambda item: item[1])[0]
        if negative_components
        else None
    )

    total_run_mean_delta = _delta(
        production.total_runs.mean,
        observed.total_runs.mean,
    )
    total_run_mean_relative_delta = _relative_delta(
        production.total_runs.mean,
        observed.total_runs.mean,
    )
    if total_run_mean_delta >= 0.0:
        largest_negative_component = None

    digest_payload = {
        "schema_version": (
            CANONICAL_PRODUCTION_RUN_ENVIRONMENT_BACKTEST_VERSION
        ),
        "production_schema_version": production.schema_version,
        "observed_schema_version": observed.schema_version,
        "simulation_count": production.simulation_count,
        "observed_game_count": observed.game_count,
        "observed_source_identifier": (
            observed.source_identifier
        ),
        "production_artifact_digest": (
            production.artifact_digest
        ),
        "observed_artifact_digest": observed.artifact_digest,
        "total_run_mean_delta": total_run_mean_delta,
        "total_run_mean_relative_delta": (
            total_run_mean_relative_delta
        ),
        "run_distribution_deltas": dict(
            run_distribution_deltas
        ),
        "comparable_metric_deltas": dict(
            comparable_metric_deltas
        ),
        "comparable_metric_relative_deltas": dict(
            comparable_metric_relative_deltas
        ),
        "threshold_rate_deltas": dict(
            threshold_rate_deltas
        ),
        "component_relative_deltas": dict(
            component_relative_deltas
        ),
        "low_total_signal": total_run_mean_delta < 0.0,
        "largest_negative_component": (
            largest_negative_component
        ),
    }

    return CanonicalProductionRunEnvironmentBacktest(
        production_schema_version=production.schema_version,
        observed_schema_version=observed.schema_version,
        simulation_count=production.simulation_count,
        observed_game_count=observed.game_count,
        observed_source_identifier=observed.source_identifier,
        production_artifact_digest=production.artifact_digest,
        observed_artifact_digest=observed.artifact_digest,
        total_run_mean_delta=total_run_mean_delta,
        total_run_mean_relative_delta=(
            total_run_mean_relative_delta
        ),
        run_distribution_deltas=run_distribution_deltas,
        comparable_metric_deltas=comparable_metric_deltas,
        comparable_metric_relative_deltas=(
            comparable_metric_relative_deltas
        ),
        threshold_rate_deltas=threshold_rate_deltas,
        component_relative_deltas=component_relative_deltas,
        low_total_signal=total_run_mean_delta < 0.0,
        largest_negative_component=(
            largest_negative_component
        ),
        artifact_digest=_artifact_digest(digest_payload),
    )

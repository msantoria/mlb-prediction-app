"""Aggregate canonical box scores into projection distributions."""

from __future__ import annotations

from dataclasses import asdict
import hashlib
import json
import math
from statistics import fmean, median
from bisect import bisect_left, bisect_right
from typing import (
    Dict,
    Iterable,
    List,
    Mapping,
    Optional,
    Sequence,
    Tuple,
)

from mlb_app.simulation.box_score import (
    BatterDfsScoringRules,
    PitcherDfsScoringRules,
    ReducedBoxScore,
    score_batter,
    score_pitcher,
)

from .contracts import (
    CanonicalProjectionPayload,
    MetricProjection,
    PlayerProjection,
    ProjectionDiagnostics,
    StatisticalSummary,
    TeamProjection,
)


TEAM_METRICS = (
    "errors",
    "hits",
    "left_on_base",
    "runs",
)

BATTER_METRICS = (
    "at_bats",
    "caught_stealing",
    "doubles",
    "hit_by_pitch",
    "hits",
    "home_runs",
    "plate_appearances",
    "rbi",
    "reached_on_error",
    "runs",
    "sacrifice_bunts",
    "sacrifice_flies",
    "singles",
    "stolen_bases",
    "strikeouts",
    "total_bases",
    "triples",
    "walks",
)

PITCHER_METRICS = (
    "batters_faced",
    "hit_batters",
    "hits_allowed",
    "home_runs_allowed",
    "outs_recorded",
    "runs_allowed",
    "strikeouts",
    "walks",
)


def summarize_values(
    values: Sequence[float],
) -> StatisticalSummary:
    """Return a deterministic interpolated summary."""

    if not values:
        raise ValueError(
            "cannot summarize an empty value sequence"
        )

    normalized = tuple(float(value) for value in values)

    if any(not math.isfinite(value) for value in normalized):
        raise ValueError(
            "summary values must be finite"
        )

    ordered = tuple(sorted(normalized))

    centre = fmean(ordered)
    return StatisticalSummary(
        count=len(ordered),
        mean=_round(centre),
        median=_round(median(ordered)),
        p10=_round(_percentile(ordered, 0.10)),
        p25=_round(_percentile(ordered, 0.25)),
        p75=_round(_percentile(ordered, 0.75)),
        p90=_round(_percentile(ordered, 0.90)),
        minimum=_round(ordered[0]),
        maximum=_round(ordered[-1]),
        sd=_round(math.sqrt(fmean((value-centre)**2 for value in ordered))),
        p0=(bisect_right(ordered, 0)-bisect_left(ordered, 0))/len(ordered),
        **{f"p{k}_plus": (len(ordered)-bisect_left(ordered, k))/len(ordered) for k in range(1, 7)},
    )


def aggregate_projection_payload(
    *,
    box_scores: Iterable[ReducedBoxScore],
    model_version: str,
    replay_validation_passes: Optional[
        Iterable[bool]
    ] = None,
    batter_dfs_rules: Optional[
        BatterDfsScoringRules
    ] = None,
    pitcher_dfs_rules: Optional[
        PitcherDfsScoringRules
    ] = None,
) -> CanonicalProjectionPayload:
    """Aggregate canonical reduced box-score simulations."""

    runs = tuple(box_scores)

    if not runs:
        raise ValueError(
            "at least one reduced box score is required"
        )

    if not model_version:
        raise ValueError("model_version is required")

    validation_values = (
        tuple(replay_validation_passes)
        if replay_validation_passes is not None
        else tuple(True for _ in runs)
    )

    if len(validation_values) != len(runs):
        raise ValueError(
            "replay validation count must match simulations"
        )

    team_projections = tuple(
        _aggregate_team(
            runs=runs,
            team_side=team_side,
        )
        for team_side in ("away", "home")
    )

    batter_projections = _aggregate_batters(
        runs=runs,
        dfs_rules=batter_dfs_rules,
    )

    pitcher_projections = _aggregate_pitchers(
        runs=runs,
        dfs_rules=pitcher_dfs_rules,
    )

    complete_pitcher_runs = sum(
        run.pitcher_attribution_complete
        for run in runs
    )

    pitcher_complete_rate = (
        complete_pitcher_runs / len(runs)
    )

    replay_pass_rate = (
        sum(bool(value) for value in validation_values)
        / len(validation_values)
    )

    earned_run_status = _earned_run_status(runs)

    warnings = []

    if pitcher_complete_rate < 1.0:
        warnings.append(
            "pitcher_attribution_incomplete"
        )

    if earned_run_status != "reconstructed":
        warnings.append(
            "earned_runs_not_fully_reconstructed"
        )

    if replay_pass_rate < 1.0:
        warnings.append(
            "replay_validation_failures_present"
        )

    if (
        pitcher_dfs_rules is not None
        and pitcher_dfs_rules.earned_run != 0.0
        and earned_run_status != "reconstructed"
    ):
        warnings.append(
            "pitcher_dfs_earned_runs_unavailable"
        )

    run_id = _deterministic_run_id(
        runs=runs,
        model_version=model_version,
        validation_values=validation_values,
        batter_dfs_rules=batter_dfs_rules,
        pitcher_dfs_rules=pitcher_dfs_rules,
    )

    return CanonicalProjectionPayload(
        run_id=run_id,
        model_version=model_version,
        simulation_count=len(runs),
        teams=team_projections,
        batters=batter_projections,
        pitchers=pitcher_projections,
        diagnostics=ProjectionDiagnostics(
            pitcher_attribution_complete_rate=(
                _round(pitcher_complete_rate)
            ),
            replay_validation_pass_rate=(
                _round(replay_pass_rate)
            ),
            earned_run_status=earned_run_status,
            warnings=tuple(sorted(warnings)),
        ),
    )


def _aggregate_team(
    *,
    runs: Tuple[ReducedBoxScore, ...],
    team_side: str,
) -> TeamProjection:
    values = {
        metric: []
        for metric in TEAM_METRICS
    }

    for run in runs:
        line = getattr(run, team_side)

        for metric in TEAM_METRICS:
            values[metric].append(
                float(getattr(line, metric))
            )

    return TeamProjection(
        team_side=team_side,
        metrics=_metric_projections(values),
    )


def _aggregate_batters(
    *,
    runs: Tuple[ReducedBoxScore, ...],
    dfs_rules: Optional[BatterDfsScoringRules],
) -> Tuple[PlayerProjection, ...]:
    player_keys = sorted(
        {
            (line.team_side, line.player_id)
            for run in runs
            for line in run.batters
        }
    )

    projections = []

    for team_side, player_id in player_keys:
        metric_values = {
            metric: []
            for metric in BATTER_METRICS
        }

        if dfs_rules is not None:
            metric_values["dfs_points"] = []

        for run in runs:
            line = _find_batter(
                run=run,
                team_side=team_side,
                player_id=player_id,
            )

            for metric in BATTER_METRICS:
                metric_values[metric].append(
                    float(
                        (line.singles+2*line.doubles+3*line.triples+4*line.home_runs if metric=="total_bases" else getattr(line, metric))
                        if line is not None
                        else 0
                    )
                )

            if dfs_rules is not None:
                metric_values["dfs_points"].append(
                    (
                        score_batter(line, dfs_rules)
                        if line is not None
                        else 0.0
                    )
                )

        projections.append(
            PlayerProjection(
                player_id=player_id,
                team_side=team_side,
                metrics=_metric_projections(
                    metric_values
                ),
            )
        )

    return tuple(projections)


def _aggregate_pitchers(
    *,
    runs: Tuple[ReducedBoxScore, ...],
    dfs_rules: Optional[PitcherDfsScoringRules],
) -> Tuple[PlayerProjection, ...]:
    player_keys = sorted(
        {
            (line.team_side, line.player_id)
            for run in runs
            for line in run.pitchers
        }
    )

    projections = []

    for team_side, player_id in player_keys:
        metric_values = {
            metric: []
            for metric in PITCHER_METRICS
        }

        earned_runs_available = (
            _player_earned_runs_available(
                runs=runs,
                team_side=team_side,
                player_id=player_id,
            )
        )

        include_dfs = (
            dfs_rules is not None
            and (
                dfs_rules.earned_run == 0.0
                or earned_runs_available
            )
        )

        if earned_runs_available:
            metric_values["earned_runs"] = []

        if include_dfs:
            metric_values["dfs_points"] = []

        for run in runs:
            line = _find_pitcher(
                run=run,
                team_side=team_side,
                player_id=player_id,
            )

            for metric in PITCHER_METRICS:
                metric_values[metric].append(
                    float(
                        getattr(line, metric)
                        if line is not None
                        else 0
                    )
                )

            if earned_runs_available:
                metric_values["earned_runs"].append(
                    float(
                        line.earned_runs
                        if line is not None
                        else 0
                    )
                )

            if include_dfs:
                metric_values["dfs_points"].append(
                    (
                        score_pitcher(line, dfs_rules)
                        if line is not None
                        else 0.0
                    )
                )

        projections.append(
            PlayerProjection(
                player_id=player_id,
                team_side=team_side,
                metrics=_metric_projections(
                    metric_values
                ),
            )
        )

    return tuple(projections)


def _metric_projections(
    values: Mapping[str, Sequence[float]],
) -> Tuple[MetricProjection, ...]:
    return tuple(
        MetricProjection(
            name=name,
            summary=summarize_values(values[name]),
        )
        for name in sorted(values)
    )


def _find_batter(
    *,
    run: ReducedBoxScore,
    team_side: str,
    player_id: str,
):
    return next(
        (
            line
            for line in run.batters
            if (
                line.team_side == team_side
                and line.player_id == player_id
            )
        ),
        None,
    )


def _find_pitcher(
    *,
    run: ReducedBoxScore,
    team_side: str,
    player_id: str,
):
    return next(
        (
            line
            for line in run.pitchers
            if (
                line.team_side == team_side
                and line.player_id == player_id
            )
        ),
        None,
    )


def _player_earned_runs_available(
    *,
    runs: Tuple[ReducedBoxScore, ...],
    team_side: str,
    player_id: str,
) -> bool:
    for run in runs:
        line = _find_pitcher(
            run=run,
            team_side=team_side,
            player_id=player_id,
        )

        if line is None:
            continue

        if (
            line.earned_run_status
            != "reconstructed"
            or line.earned_runs is None
        ):
            return False

    return True


def _earned_run_status(
    runs: Tuple[ReducedBoxScore, ...],
) -> str:
    statuses = [
        line.earned_run_status
        for run in runs
        for line in run.pitchers
    ]

    if not statuses:
        return "not_reconstructed"

    reconstructed = sum(
        status == "reconstructed"
        for status in statuses
    )

    if reconstructed == len(statuses):
        return "reconstructed"

    if reconstructed:
        return "partially_reconstructed"

    return "not_reconstructed"


def _deterministic_run_id(
    *,
    runs: Tuple[ReducedBoxScore, ...],
    model_version: str,
    validation_values: Tuple[bool, ...],
    batter_dfs_rules,
    pitcher_dfs_rules,
) -> str:
    source = {
        "model_version": model_version,
        "runs": [asdict(run) for run in runs],
        "validation_values": validation_values,
        "batter_dfs_rules": (
            asdict(batter_dfs_rules)
            if batter_dfs_rules is not None
            else None
        ),
        "pitcher_dfs_rules": (
            asdict(pitcher_dfs_rules)
            if pitcher_dfs_rules is not None
            else None
        ),
    }

    encoded = json.dumps(
        source,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")

    digest = hashlib.sha256(encoded).hexdigest()

    return f"canonical-{digest[:24]}"


def _percentile(
    ordered: Sequence[float],
    probability: float,
) -> float:
    if not 0.0 <= probability <= 1.0:
        raise ValueError(
            "percentile probability must be between 0 and 1"
        )

    if len(ordered) == 1:
        return ordered[0]

    position = probability * (len(ordered) - 1)
    lower_index = math.floor(position)
    upper_index = math.ceil(position)

    if lower_index == upper_index:
        return ordered[lower_index]

    fraction = position - lower_index

    return (
        ordered[lower_index]
        + (
            ordered[upper_index]
            - ordered[lower_index]
        )
        * fraction
    )


def _round(value: float) -> float:
    return round(float(value), 6)

"""Historical holdouts for canonical pitcher-profile shrinkage."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from .canonical_pitcher_matchup_profile_evidence import (
    build_canonical_pitcher_matchup_profile_evidence,
)


CANONICAL_PITCHER_MATCHUP_PROFILE_HOLDOUT_VERSION = (
    "canonical_pitcher_matchup_profile_holdout_v1"
)

DEFAULT_TRAINING_WINDOW_DAYS = 90
DEFAULT_HOLDOUT_WINDOW_DAYS = 30

METRIC_SPECS = {
    "k_rate": (
        "discipline",
        "discipline",
        "strikeouts",
    ),
    "bb_rate": (
        "discipline",
        "discipline",
        "unintentional_walks",
    ),
    "hard_hit_rate_allowed": (
        "contact",
        "contact_quality",
        "hard_hits",
    ),
    "barrel_rate_allowed_approx": (
        "contact",
        "contact_quality",
        "barrels_approx",
    ),
    "sweet_spot_rate_allowed": (
        "launch_angle",
        "launch_angle_distribution",
        "sweet_spot_batted_balls",
    ),
    "ground_ball_rate": (
        "launch_angle",
        "launch_angle_distribution",
        "ground_balls",
    ),
    "line_drive_rate": (
        "launch_angle",
        "launch_angle_distribution",
        "line_drives",
    ),
    "fly_ball_rate": (
        "launch_angle",
        "launch_angle_distribution",
        "fly_balls",
    ),
    "popup_rate": (
        "launch_angle",
        "launch_angle_distribution",
        "popups",
    ),
}


def _value(row: Any, key: str) -> Any:
    if isinstance(row, Mapping):
        return row.get(key)
    return getattr(row, key, None)


def _date(value: Any) -> dt.date:
    if isinstance(value, dt.datetime):
        return value.date()
    if isinstance(value, dt.date):
        return value
    if isinstance(value, str):
        return dt.date.fromisoformat(value)
    raise TypeError("cutoff must be ISO text or date")


def _segments(
    evidence: Mapping[str, Any],
) -> dict[str, Mapping[str, Any]]:
    platoon = evidence.get("platoon_splits") or {}
    tto = (
        evidence.get("times_through_order_splits")
        or {}
    )

    return {
        "overall": evidence.get("overall") or {},
        "vsL": platoon.get("L") or {},
        "vsR": platoon.get("R") or {},
        "tto1": tto.get("1") or {},
        "tto2": tto.get("2") or {},
        "tto3_plus": tto.get("3_plus") or {},
    }


def _metric_counts(
    summary: Mapping[str, Any],
) -> dict[str, dict[str, Any]]:
    denominators = (
        summary.get("metric_denominators") or {}
    )
    rows = {}

    for metric, (
        family,
        component,
        numerator_key,
    ) in METRIC_SPECS.items():
        component_values = summary.get(component) or {}
        numerator = component_values.get(numerator_key)
        denominator = denominators.get(metric)

        if numerator is None or denominator is None:
            continue

        rows[metric] = {
            "family": family,
            "successes": int(numerator),
            "trials": int(denominator),
        }

    return rows


def _minimum(
    value: int | Mapping[str, int],
    family: str,
) -> int:
    if isinstance(value, Mapping):
        selected = value.get(
            family,
            value.get("default", 1),
        )
    else:
        selected = value

    parsed = int(selected)
    if parsed < 1:
        raise ValueError(
            "minimum trials must be positive"
        )

    return parsed


def materialize_canonical_pitcher_matchup_profile_holdouts(
    events: Iterable[Any],
    *,
    cutoffs: Sequence[dt.date | str],
    training_window_days: int = (
        DEFAULT_TRAINING_WINDOW_DAYS
    ),
    holdout_window_days: int = (
        DEFAULT_HOLDOUT_WINDOW_DAYS
    ),
    minimum_training_trials: int | Mapping[str, int] = 1,
    minimum_holdout_trials: int | Mapping[str, int] = 1,
) -> dict[str, Any]:
    """Materialize leakage-safe samples for shrinkage calibration."""
    training_days = int(training_window_days)
    holdout_days = int(holdout_window_days)

    if training_days < 1 or holdout_days < 1:
        raise ValueError(
            "training and holdout windows must be positive"
        )

    cutoff_dates = tuple(sorted({
        _date(cutoff)
        for cutoff in cutoffs
    }))
    if not cutoff_dates:
        raise ValueError("at least one cutoff is required")

    earliest = cutoff_dates[0] - dt.timedelta(
        days=training_days
    )
    latest = cutoff_dates[-1] + dt.timedelta(
        days=holdout_days
    )

    events_by_pitcher = defaultdict(list)
    raw_event_count = 0

    for row in events:
        pitcher_id = _value(row, "pitcher_id")
        game_date = _date(_value(row, "game_date"))

        if pitcher_id in (None, 0):
            continue
        if not earliest <= game_date < latest:
            continue

        raw_event_count += 1
        events_by_pitcher[int(pitcher_id)].append(row)

    samples = []
    cutoff_diagnostics = []

    for cutoff in cutoff_dates:
        holdout_end = cutoff + dt.timedelta(
            days=holdout_days
        )
        pitcher_material = {}
        league_totals = defaultdict(
            lambda: {
                "successes": 0,
                "trials": 0,
            }
        )

        for pitcher_id in sorted(events_by_pitcher):
            pitcher_events = events_by_pitcher[pitcher_id]
            training = (
                build_canonical_pitcher_matchup_profile_evidence(
                    pitcher_events,
                    pitcher_id=pitcher_id,
                    game_date=cutoff,
                    window_days=training_days,
                )
            )
            holdout = (
                build_canonical_pitcher_matchup_profile_evidence(
                    pitcher_events,
                    pitcher_id=pitcher_id,
                    game_date=holdout_end,
                    window_days=holdout_days,
                )
            )

            training_segments = _segments(training)
            holdout_segments = _segments(holdout)
            pitcher_rows = []

            for segment in sorted(training_segments):
                training_counts = _metric_counts(
                    training_segments[segment]
                )
                holdout_counts = _metric_counts(
                    holdout_segments[segment]
                )

                for metric in sorted(METRIC_SPECS):
                    training_row = training_counts.get(metric)
                    holdout_row = holdout_counts.get(metric)

                    if training_row is None:
                        continue

                    family = training_row["family"]
                    total_key = (segment, metric)
                    league_totals[total_key][
                        "successes"
                    ] += training_row["successes"]
                    league_totals[total_key][
                        "trials"
                    ] += training_row["trials"]

                    if holdout_row is None:
                        continue

                    pitcher_rows.append({
                        "pitcher_id": pitcher_id,
                        "season": cutoff.year,
                        "cutoff": cutoff.isoformat(),
                        "holdout_end_exclusive": (
                            holdout_end.isoformat()
                        ),
                        "segment": segment,
                        "metric": metric,
                        "family": family,
                        "training_successes": (
                            training_row["successes"]
                        ),
                        "training_trials": (
                            training_row["trials"]
                        ),
                        "holdout_successes": (
                            holdout_row["successes"]
                        ),
                        "holdout_trials": (
                            holdout_row["trials"]
                        ),
                    })

            pitcher_material[pitcher_id] = pitcher_rows

        rejected_threshold = 0
        rejected_prior = 0
        cutoff_sample_count = 0

        for pitcher_id in sorted(pitcher_material):
            for row in pitcher_material[pitcher_id]:
                family = row["family"]

                if row["training_trials"] < _minimum(
                    minimum_training_trials,
                    family,
                ):
                    rejected_threshold += 1
                    continue
                if row["holdout_trials"] < _minimum(
                    minimum_holdout_trials,
                    family,
                ):
                    rejected_threshold += 1
                    continue

                total = league_totals[
                    (row["segment"], row["metric"])
                ]
                prior_successes = (
                    total["successes"]
                    - row["training_successes"]
                )
                prior_trials = (
                    total["trials"]
                    - row["training_trials"]
                )

                if prior_trials <= 0:
                    rejected_prior += 1
                    continue

                prior_probability = (
                    prior_successes / prior_trials
                )

                samples.append({
                    **row,
                    "prior_successes_excluding_pitcher": (
                        prior_successes
                    ),
                    "prior_trials_excluding_pitcher": (
                        prior_trials
                    ),
                    "prior_probability": (
                        prior_probability
                    ),
                    "prior_scope": (
                        "same_cutoff_segment_metric_"
                        "excluding_pitcher"
                    ),
                })
                cutoff_sample_count += 1

        cutoff_diagnostics.append({
            "cutoff": cutoff.isoformat(),
            "holdout_end_exclusive": (
                holdout_end.isoformat()
            ),
            "pitcher_count": len(pitcher_material),
            "sample_count": cutoff_sample_count,
            "rejected_threshold_count": (
                rejected_threshold
            ),
            "rejected_prior_count": rejected_prior,
        })

    samples.sort(key=lambda row: (
        row["cutoff"],
        row["pitcher_id"],
        row["segment"],
        row["metric"],
    ))

    digest = hashlib.sha256(
        json.dumps(
            samples,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()

    return {
        "schema_version": (
            CANONICAL_PITCHER_MATCHUP_PROFILE_HOLDOUT_VERSION
        ),
        "status": "ready" if samples else "blocked",
        "shadow_only": True,
        "production_authority_changed": False,
        "parameter_selected": False,
        "training_window_days": training_days,
        "holdout_window_days": holdout_days,
        "cutoffs": [
            cutoff.isoformat()
            for cutoff in cutoff_dates
        ],
        "raw_event_count": raw_event_count,
        "pitcher_count": len(events_by_pitcher),
        "sample_count": len(samples),
        "samples": samples,
        "cutoff_diagnostics": cutoff_diagnostics,
        "sample_digest": digest,
        "cutoff_contract": {
            "training": (
                "[cutoff-training_window, cutoff)"
            ),
            "holdout": (
                "[cutoff, cutoff+holdout_window)"
            ),
            "prior": (
                "same cutoff, segment, and metric "
                "excluding evaluated pitcher"
            ),
        },
    }

#!/usr/bin/env python3
"""Audit canonical pitcher-profile shrinkage on historical holdouts.

This executor is read-only. It materializes cutoff-safe historical evidence,
evaluates candidate pseudo-counts, and writes a shadow-only audit artifact.
It never writes to the database or changes production authority.
"""

from __future__ import annotations

import argparse
import collections
import datetime as dt
import json
import os
from pathlib import Path
from typing import Any, Iterable

from sqlalchemy import func

from mlb_app.database import (
    StatcastEvent,
    get_engine,
    get_session,
)
from mlb_app.simulation.shadow.canonical_pitcher_matchup_profile_holdout import (
    materialize_canonical_pitcher_matchup_profile_holdouts,
)
from mlb_app.simulation.shadow.canonical_pitcher_matchup_profile_shrinkage import (
    calibrate_canonical_pitcher_matchup_profile_shrinkage,
)
from mlb_app.statcast_event_identity import (
    load_canonical_statcast_events,
)


SCHEMA_VERSION = (
    "canonical_pitcher_matchup_profile_shrinkage_audit_v1"
)
DEFAULT_OUTPUT = Path(
    "tmp/"
    "canonical_pitcher_matchup_profile_"
    "shrinkage_expanded_audit.json"
)
DEFAULT_CANDIDATES = (
    0,
    25,
    50,
    100,
    200,
    400,
    800,
    1200,
    1600,
)
TRAINING_WINDOW_DAYS = 90
HOLDOUT_WINDOW_DAYS = 30
CUTOFF_STEP_DAYS = 60
MINIMUM_TRAINING_TRIALS = {
    "discipline": 50,
    "contact": 20,
    "launch_angle": 20,
}
MINIMUM_HOLDOUT_TRIALS = {
    "discipline": 10,
    "contact": 5,
    "launch_angle": 5,
}


def _candidate_values(text: str) -> tuple[float, ...]:
    values = tuple(
        float(part.strip())
        for part in text.split(",")
        if part.strip()
    )
    if not values:
        raise ValueError(
            "at least one candidate pseudo-count is required"
        )
    return values


def _cutoffs(
    minimum: dt.date,
    maximum: dt.date,
) -> tuple[dt.date, ...]:
    first = minimum + dt.timedelta(
        days=TRAINING_WINDOW_DAYS
    )
    latest = (
        maximum
        - dt.timedelta(days=HOLDOUT_WINDOW_DAYS)
        + dt.timedelta(days=1)
    )

    values = []
    current = first

    while current <= latest:
        values.append(current)
        current += dt.timedelta(
            days=CUTOFF_STEP_DAYS
        )

    return tuple(values)


def _sample_summary(
    samples: Iterable[dict[str, Any]],
) -> dict[str, Any]:
    rows = list(samples)

    return {
        "sample_count": len(rows),
        "by_season": dict(sorted(
            collections.Counter(
                str(row["season"])
                for row in rows
            ).items()
        )),
        "by_family": dict(sorted(
            collections.Counter(
                row["family"]
                for row in rows
            ).items()
        )),
        "by_metric": dict(sorted(
            collections.Counter(
                row["metric"]
                for row in rows
            ).items()
        )),
        "by_segment": dict(sorted(
            collections.Counter(
                row["segment"]
                for row in rows
            ).items()
        )),
    }


def _selected_candidate(
    result: dict[str, Any],
) -> dict[str, Any]:
    selected = result.get("pooled_candidate")
    return selected if isinstance(selected, dict) else {}


def _metric_summary(
    calibration: dict[str, Any],
) -> dict[str, Any]:
    summary = {}

    for metric, result in sorted(
        calibration["metric_results"].items()
    ):
        selected = _selected_candidate(result)

        segment_candidates = {
            segment: (
                diagnostic.get("best_candidate")
                or {}
            ).get("pseudo_count")
            for segment, diagnostic in sorted(
                result.get(
                    "segment_diagnostics",
                    {},
                ).items()
            )
        }

        summary[metric] = {
            "status": result.get("status"),
            "sample_count": result.get(
                "sample_count"
            ),
            "holdout_trials": result.get(
                "holdout_trials"
            ),
            "selected_candidate_for_review": (
                selected.get("pseudo_count")
            ),
            "pooled_log_loss": selected.get(
                "binomial_log_loss"
            ),
            "pooled_brier_score": selected.get(
                "brier_score"
            ),
            "pooled_weighted_absolute_error": (
                selected.get(
                    "weighted_absolute_error"
                )
            ),
            "mean_training_reliability": (
                selected.get(
                    "mean_training_reliability"
                )
            ),
            "cross_season_candidate_range": (
                result.get(
                    "cross_season_candidate_range"
                )
            ),
            "segment_candidates": (
                segment_candidates
            ),
        }

    return summary


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Run the shadow-only historical pitcher "
            "profile shrinkage audit."
        )
    )
    parser.add_argument(
        "--database-url",
        default=os.environ.get(
            "DATABASE_URL",
            "sqlite:///mlb.db",
        ),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
    )
    parser.add_argument(
        "--candidates",
        default=",".join(
            str(value)
            for value in DEFAULT_CANDIDATES
        ),
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    candidates = _candidate_values(
        args.candidates
    )

    engine = get_engine(args.database_url)
    Session = get_session(engine)

    with Session() as session:
        minimum, maximum = (
            session.query(
                func.min(StatcastEvent.game_date),
                func.max(StatcastEvent.game_date),
            ).one()
        )

        if minimum is None or maximum is None:
            raise RuntimeError(
                "Statcast history is unavailable"
            )

        cutoffs = _cutoffs(minimum, maximum)
        if not cutoffs:
            raise RuntimeError(
                "historical range cannot support holdouts"
            )

        print(
            "audit_date_range="
            f"{minimum.isoformat()}.."
            f"{maximum.isoformat()}",
            flush=True,
        )
        print(
            "candidate_cutoffs="
            + ",".join(
                cutoff.isoformat()
                for cutoff in cutoffs
            ),
            flush=True,
        )
        print(
            "candidate_pseudo_counts="
            + ",".join(
                str(value)
                for value in candidates
            ),
            flush=True,
        )

        samples = []
        cutoff_diagnostics = []
        identity_diagnostics = []

        for index, cutoff in enumerate(
            cutoffs,
            start=1,
        ):
            window_start = (
                cutoff
                - dt.timedelta(
                    days=TRAINING_WINDOW_DAYS
                )
            )
            window_end = (
                cutoff
                + dt.timedelta(
                    days=HOLDOUT_WINDOW_DAYS
                )
            )

            events, identity = (
                load_canonical_statcast_events(
                    session,
                    StatcastEvent.game_date
                    >= window_start,
                    StatcastEvent.game_date
                    < window_end,
                    order_by=(
                        StatcastEvent.game_date,
                        StatcastEvent.game_pk,
                        StatcastEvent.at_bat_number,
                        StatcastEvent.pitch_number,
                        StatcastEvent.id,
                    ),
                )
            )

            materialized = (
                materialize_canonical_pitcher_matchup_profile_holdouts(
                    events,
                    cutoffs=(cutoff,),
                    training_window_days=(
                        TRAINING_WINDOW_DAYS
                    ),
                    holdout_window_days=(
                        HOLDOUT_WINDOW_DAYS
                    ),
                    minimum_training_trials=(
                        MINIMUM_TRAINING_TRIALS
                    ),
                    minimum_holdout_trials=(
                        MINIMUM_HOLDOUT_TRIALS
                    ),
                )
            )

            window_samples = materialized[
                "samples"
            ]
            samples.extend(window_samples)
            cutoff_diagnostics.extend(
                materialized.get(
                    "cutoff_diagnostics",
                    (),
                )
            )
            identity_diagnostics.append({
                "cutoff": cutoff.isoformat(),
                **identity,
            })

            pitcher_count = len({
                int(event.pitcher_id)
                for event in events
                if event.pitcher_id is not None
            })

            print(
                "cutoff_progress="
                f"{index}/{len(cutoffs)} "
                f"cutoff={cutoff.isoformat()} "
                f"events={len(events)} "
                f"pitchers={pitcher_count} "
                f"samples={len(window_samples)}",
                flush=True,
            )

    calibration = (
        calibrate_canonical_pitcher_matchup_profile_shrinkage(
            samples,
            candidate_pseudo_counts=candidates,
        )
    )

    artifact = {
        "schema_version": SCHEMA_VERSION,
        "status": calibration["status"],
        "shadow_only": True,
        "production_authority_changed": False,
        "parameter_selected": False,
        "selection_role": (
            "expanded_grid_candidate_evidence_only"
        ),
        "historical_range": {
            "minimum": minimum.isoformat(),
            "maximum": maximum.isoformat(),
        },
        "policy": {
            "training_window_days": (
                TRAINING_WINDOW_DAYS
            ),
            "holdout_window_days": (
                HOLDOUT_WINDOW_DAYS
            ),
            "cutoff_step_days": (
                CUTOFF_STEP_DAYS
            ),
            "overlapping_holdouts": False,
            "minimum_training_trials": (
                MINIMUM_TRAINING_TRIALS
            ),
            "minimum_holdout_trials": (
                MINIMUM_HOLDOUT_TRIALS
            ),
            "candidate_pseudo_counts": (
                list(candidates)
            ),
            "prior_scope": (
                "same cutoff segment metric "
                "excluding evaluated pitcher"
            ),
        },
        "sample_summary": _sample_summary(
            samples
        ),
        "cutoff_diagnostics": (
            cutoff_diagnostics
        ),
        "identity_diagnostics": (
            identity_diagnostics
        ),
        "metric_summary": _metric_summary(
            calibration
        ),
        "calibration": calibration,
        "recommendation": (
            "Shadow evidence only. Apply explicit "
            "stability gates before selecting or "
            "activating any pseudo-count."
        ),
    }

    if calibration["shadow_only"] is not True:
        raise RuntimeError(
            "calibration is not shadow-only"
        )
    if calibration["parameter_selected"] is not False:
        raise RuntimeError(
            "calibration selected a parameter"
        )
    if (
        calibration[
            "production_authority_changed"
        ]
        is not False
    ):
        raise RuntimeError(
            "calibration changed production authority"
        )

    args.output.parent.mkdir(
        parents=True,
        exist_ok=True,
    )
    args.output.write_text(
        json.dumps(
            artifact,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    print(
        json.dumps(
            {
                "status": artifact["status"],
                "sample_summary": (
                    artifact["sample_summary"]
                ),
                "metric_summary": (
                    artifact["metric_summary"]
                ),
            },
            indent=2,
            sort_keys=True,
        )
    )
    print(f"wrote={args.output}")

    return (
        0
        if calibration["status"] == "ready"
        else 1
    )


if __name__ == "__main__":
    raise SystemExit(main())

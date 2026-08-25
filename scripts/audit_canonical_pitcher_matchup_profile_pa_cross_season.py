"""Run a bounded cross-season historical pitcher-profile PA audit."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
from typing import Any

from mlb_app.database import StatcastEvent
from mlb_app.model_projection_routes import (
    _session_factory,
)
from mlb_app.simulation.shadow.canonical_pitcher_matchup_profile_pa_historical_evaluation import (
    evaluate_canonical_pitcher_matchup_profile_pa_history,
)
from mlb_app.simulation.shadow.canonical_pitcher_matchup_profile_pa_historical_statcast_window import (
    execute_canonical_pitcher_matchup_profile_pa_historical_statcast_window,
)


SCHEMA_VERSION = (
    "canonical_pitcher_matchup_profile_pa_cross_season_audit_v1"
)


def _date(value: str) -> dt.date:
    try:
        return dt.date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            "date must use YYYY-MM-DD"
        ) from exc


def _positive_integer(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            "value must be a positive integer"
        ) from exc

    if parsed <= 0:
        raise argparse.ArgumentTypeError(
            "value must be a positive integer"
        )

    return parsed


def _nonnegative_float(value: str) -> float:
    try:
        parsed = float(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            "value must be nonnegative"
        ) from exc

    if parsed < 0.0:
        raise argparse.ArgumentTypeError(
            "value must be nonnegative"
        )

    return parsed


def _digest(value: Any) -> str:
    payload = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Evaluate pooled pitcher-profile PA "
            "candidates across independent seasons."
        )
    )
    parser.add_argument(
        "--evaluation-date",
        action="append",
        required=True,
        type=_date,
        help=(
            "Evaluation date in YYYY-MM-DD form. "
            "Repeat once per season."
        ),
    )
    parser.add_argument(
        "--max-games-per-date",
        type=_positive_integer,
        default=2,
        help=(
            "Maximum games evaluated on each date."
        ),
    )
    parser.add_argument(
        "--window-days",
        type=_positive_integer,
        default=90,
        help=(
            "Independent lookback for each date."
        ),
    )
    parser.add_argument(
        "--minimum-samples",
        type=_positive_integer,
        default=30,
        help=(
            "Minimum combined paired samples."
        ),
    )
    parser.add_argument(
        "--minimum-observed-pa",
        type=_positive_integer,
        default=100,
        help=(
            "Minimum combined observed PAs."
        ),
    )
    parser.add_argument(
        "--season-regression-tolerance",
        type=_nonnegative_float,
        default=0.0,
        help=(
            "Allowed per-season log-loss regression."
        ),
    )
    return parser


def _selected_games(
    rows: list[Any],
    *,
    evaluation_date: dt.date,
    maximum: int,
) -> tuple[int, ...]:
    identities = sorted({
        int(row.game_pk)
        for row in rows
        if row.game_pk is not None
        and row.game_date
        == evaluation_date
    })
    return tuple(identities[:maximum])


def _load_events(
    session: Any,
    *,
    evaluation_date: dt.date,
    window_days: int,
) -> tuple[
    list[Any],
    dt.date,
]:
    load_start = (
        evaluation_date
        - dt.timedelta(days=window_days)
    )
    load_end = (
        evaluation_date
        + dt.timedelta(days=1)
    )
    rows = (
        session.query(StatcastEvent)
        .filter(
            StatcastEvent.game_date
            >= load_start,
            StatcastEvent.game_date
            < load_end,
            StatcastEvent.events.isnot(None),
        )
        .order_by(
            StatcastEvent.game_date,
            StatcastEvent.game_pk,
            StatcastEvent.at_bat_number,
            StatcastEvent.pitch_number,
            StatcastEvent.id,
        )
        .all()
    )
    return rows, load_start


def _window_digests(
    *,
    evaluation_date: dt.date,
    load_start: dt.date,
    window_days: int,
) -> tuple[str, str]:
    identity = {
        "schema_version": SCHEMA_VERSION,
        "evaluation_date": (
            evaluation_date.isoformat()
        ),
        "load_start": (
            load_start.isoformat()
        ),
        "load_end_exclusive": (
            evaluation_date
            + dt.timedelta(days=1)
        ).isoformat(),
        "window_days": window_days,
        "terminal_rows_only": True,
    }
    return (
        _digest({
            **identity,
            "source": (
                "local_statcast_terminal_pa_history"
            ),
        }),
        _digest({
            **identity,
            "source": (
                "inferred_historical_starters"
            ),
        }),
    )


def main() -> int:
    args = _parser().parse_args()
    evaluation_dates = tuple(sorted(set(
        args.evaluation_date
    )))

    if len(evaluation_dates) < 2:
        raise SystemExit(
            "STOP: at least two distinct "
            "evaluation dates are required."
        )
    if len({
        value.year
        for value in evaluation_dates
    }) < 2:
        raise SystemExit(
            "STOP: evaluation dates must span "
            "at least two seasons."
        )

    started = dt.datetime.now(
        dt.timezone.utc
    )
    session_factory = _session_factory()
    session = session_factory()
    combined_samples = []
    window_records = []

    try:
        for evaluation_date in (
            evaluation_dates
        ):
            rows, load_start = _load_events(
                session,
                evaluation_date=(
                    evaluation_date
                ),
                window_days=(
                    args.window_days
                ),
            )
            selected_game_pks = (
                _selected_games(
                    rows,
                    evaluation_date=(
                        evaluation_date
                    ),
                    maximum=(
                        args.max_games_per_date
                    ),
                )
            )

            if not rows:
                raise SystemExit(
                    "STOP: no terminal events for "
                    f"{evaluation_date}."
                )
            if not selected_game_pks:
                raise SystemExit(
                    "STOP: no evaluation games for "
                    f"{evaluation_date}."
                )

            (
                observed_digest,
                lineup_digest,
            ) = _window_digests(
                evaluation_date=evaluation_date,
                load_start=load_start,
                window_days=args.window_days,
            )
            result = (
                execute_canonical_pitcher_matchup_profile_pa_historical_statcast_window(
                    rows,
                    observed_window_digest=(
                        observed_digest
                    ),
                    lineup_bullpen_window_digest=(
                        lineup_digest
                    ),
                    candidate_window_days=(
                        args.window_days
                    ),
                    evaluation_game_pks=(
                        selected_game_pks
                    ),
                    minimum_samples=1,
                    minimum_observed_pa=1,
                    season_log_loss_regression_tolerance=(
                        args.season_regression_tolerance
                    ),
                )
            )
            diagnostics = dict(
                result.get("diagnostics")
                or {}
            )
            execution = dict(
                result.get("execution")
                or {}
            )
            paired = dict(
                execution.get(
                    "paired_samples"
                )
                or {}
            )
            samples = list(
                paired.get("samples")
                or ()
            )

            if not samples:
                raise SystemExit(
                    "STOP: no paired samples for "
                    f"{evaluation_date}."
                )
            if diagnostics.get(
                "production_authority_changed"
            ) is not False:
                raise SystemExit(
                    "STOP: window authority changed."
                )

            combined_samples.extend(samples)
            window_records.append({
                "season": evaluation_date.year,
                "evaluation_date": (
                    evaluation_date.isoformat()
                ),
                "load_start_date": (
                    load_start.isoformat()
                ),
                "selected_game_pks": list(
                    selected_game_pks
                ),
                "selected_game_count": len(
                    selected_game_pks
                ),
                "terminal_event_count": len(
                    rows
                ),
                "paired_sample_count": len(
                    samples
                ),
                "status": diagnostics.get(
                    "status"
                ),
                "activation_status": (
                    diagnostics.get(
                        "activation_status"
                    )
                ),
                "window_execution_digest": (
                    diagnostics.get(
                        "window_execution_digest"
                    )
                ),
            })
    finally:
        session.close()

    evaluation = (
        evaluate_canonical_pitcher_matchup_profile_pa_history(
            combined_samples,
            minimum_samples=(
                args.minimum_samples
            ),
            minimum_observed_pa=(
                args.minimum_observed_pa
            ),
            season_log_loss_regression_tolerance=(
                args.season_regression_tolerance
            ),
        )
    )
    evaluation_diagnostics = dict(
        evaluation.get("diagnostics") or {}
    )
    elapsed = (
        dt.datetime.now(dt.timezone.utc)
        - started
    ).total_seconds()

    summary = {
        "schema_version": SCHEMA_VERSION,
        "status": (
            evaluation_diagnostics.get(
                "status"
            )
        ),
        "activation_status": (
            evaluation_diagnostics.get(
                "activation_status"
            )
        ),
        "evaluation_dates": [
            value.isoformat()
            for value in evaluation_dates
        ],
        "season_count": len({
            value.year
            for value in evaluation_dates
        }),
        "max_games_per_date": (
            args.max_games_per_date
        ),
        "window_days": args.window_days,
        "combined_sample_count": len(
            combined_samples
        ),
        "overall": evaluation.get(
            "overall"
        ),
        "by_season": evaluation.get(
            "by_season"
        ),
        "selection_gate_passed": (
            evaluation_diagnostics.get(
                "selection_gate_passed"
            )
        ),
        "regressed_seasons": (
            evaluation_diagnostics.get(
                "regressed_seasons"
            )
            or []
        ),
        "blockers": (
            evaluation_diagnostics.get(
                "blockers"
            )
            or []
        ),
        "windows": window_records,
        "database_accessed": True,
        "database_mutated": False,
        "independent_lookback_per_date": True,
        "combined_raw_paired_samples": True,
        "calibration_parameters_selected": False,
        "shadow_only": True,
        "production_inputs_unchanged": True,
        "production_authority": False,
        "production_authority_changed": False,
        "evaluation_digest": (
            evaluation_diagnostics.get(
                "evaluation_digest"
            )
        ),
        "elapsed_seconds": round(
            elapsed,
            3,
        ),
    }
    summary["cross_season_audit_digest"] = (
        _digest({
            key: value
            for key, value in summary.items()
            if key != "elapsed_seconds"
        })
    )

    print(
        json.dumps(
            summary,
            indent=2,
            sort_keys=True,
        )
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

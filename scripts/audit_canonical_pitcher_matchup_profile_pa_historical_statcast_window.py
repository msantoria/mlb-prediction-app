"""Run a bounded real-data historical pitcher-profile PA audit."""

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
from mlb_app.simulation.shadow.canonical_pitcher_matchup_profile_pa_historical_statcast_window import (
    execute_canonical_pitcher_matchup_profile_pa_historical_statcast_window,
)


SCHEMA_VERSION = (
    "canonical_pitcher_matchup_profile_pa_historical_statcast_audit_v1"
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
            "Run a bounded cutoff-safe historical "
            "pitcher-profile PA evaluation."
        )
    )
    parser.add_argument(
        "--start-date",
        required=True,
        type=_date,
        help="First evaluation date, YYYY-MM-DD.",
    )
    parser.add_argument(
        "--end-date",
        required=True,
        type=_date,
        help="Last evaluation date, YYYY-MM-DD.",
    )
    parser.add_argument(
        "--max-games",
        type=_positive_integer,
        default=5,
        help=(
            "Maximum evaluation games selected in "
            "canonical date/game order."
        ),
    )
    parser.add_argument(
        "--window-days",
        type=_positive_integer,
        default=90,
        help="Pregame pitcher evidence lookback.",
    )
    parser.add_argument(
        "--minimum-samples",
        type=_positive_integer,
        default=1,
        help="Minimum paired evaluator samples.",
    )
    parser.add_argument(
        "--minimum-observed-pa",
        type=_positive_integer,
        default=1,
        help="Minimum observed evaluator PAs.",
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
    start_date: dt.date,
    end_date: dt.date,
    max_games: int,
) -> tuple[int, ...]:
    identities = sorted({
        (
            row.game_date,
            int(row.game_pk),
        )
        for row in rows
        if row.game_pk is not None
        and start_date
        <= row.game_date
        <= end_date
    })

    return tuple(
        game_pk
        for _, game_pk in identities[
            :max_games
        ]
    )


def _summary(
    *,
    args: argparse.Namespace,
    load_start: dt.date,
    rows: list[Any],
    selected_game_pks: tuple[int, ...],
    result: dict[str, Any],
    elapsed_seconds: float,
) -> dict[str, Any]:
    diagnostics = dict(
        result.get("diagnostics") or {}
    )
    execution = dict(
        result.get("execution") or {}
    )
    evaluation = dict(
        execution.get("evaluation") or {}
    )
    evaluation_diagnostics = dict(
        evaluation.get("diagnostics") or {}
    )

    return {
        "schema_version": SCHEMA_VERSION,
        "status": diagnostics.get("status"),
        "activation_status": (
            diagnostics.get(
                "activation_status"
            )
        ),
        "evaluation_start_date": (
            args.start_date.isoformat()
        ),
        "evaluation_end_date": (
            args.end_date.isoformat()
        ),
        "load_start_date": (
            load_start.isoformat()
        ),
        "window_days": args.window_days,
        "max_games": args.max_games,
        "selected_game_pks": list(
            selected_game_pks
        ),
        "selected_game_count": len(
            selected_game_pks
        ),
        "terminal_event_count": len(rows),
        "statistics_game_count": (
            diagnostics.get(
                "statistics_game_count"
            )
        ),
        "starter_request_count": (
            diagnostics.get(
                "starter_request_count"
            )
        ),
        "candidate_count": (
            diagnostics.get(
                "candidate_count"
            )
        ),
        "evaluation_overall": (
            evaluation.get("overall")
        ),
        "evaluation_status": (
            evaluation_diagnostics.get(
                "status"
            )
        ),
        "selection_gate_passed": (
            evaluation_diagnostics.get(
                "selection_gate_passed"
            )
        ),
        "evaluation_blockers": (
            evaluation_diagnostics.get(
                "blockers"
            )
            or []
        ),
        "single_shared_event_collection": (
            diagnostics.get(
                "single_shared_event_collection"
            )
        ),
        "lookback_events_reused_for_evaluation": (
            diagnostics.get(
                "lookback_events_reused_for_evaluation"
            )
        ),
        "database_accessed": True,
        "database_mutated": False,
        "shadow_only": True,
        "production_inputs_unchanged": True,
        "production_authority": False,
        "production_authority_changed": False,
        "window_execution_digest": (
            diagnostics.get(
                "window_execution_digest"
            )
        ),
        "elapsed_seconds": round(
            elapsed_seconds,
            3,
        ),
    }


def main() -> int:
    args = _parser().parse_args()

    if args.end_date < args.start_date:
        raise SystemExit(
            "STOP: end date precedes start date."
        )

    load_start = (
        args.start_date
        - dt.timedelta(
            days=args.window_days
        )
    )
    load_end = (
        args.end_date
        + dt.timedelta(days=1)
    )
    query_identity = {
        "schema_version": SCHEMA_VERSION,
        "load_start": load_start.isoformat(),
        "load_end_exclusive": (
            load_end.isoformat()
        ),
        "evaluation_start": (
            args.start_date.isoformat()
        ),
        "evaluation_end": (
            args.end_date.isoformat()
        ),
        "window_days": args.window_days,
        "terminal_rows_only": True,
    }
    observed_window_digest = _digest({
        **query_identity,
        "source": (
            "local_statcast_terminal_pa_history"
        ),
    })
    lineup_bullpen_window_digest = _digest({
        **query_identity,
        "source": (
            "inferred_historical_starters"
        ),
    })

    started = dt.datetime.now(
        dt.timezone.utc
    )
    session_factory = _session_factory()
    session = session_factory()

    try:
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

        selected_game_pks = _selected_games(
            rows,
            start_date=args.start_date,
            end_date=args.end_date,
            max_games=args.max_games,
        )

        if not rows:
            raise SystemExit(
                "STOP: no terminal Statcast events "
                "found in the requested load window."
            )
        if not selected_game_pks:
            raise SystemExit(
                "STOP: no evaluation games found "
                "in the requested date range."
            )

        result = (
            execute_canonical_pitcher_matchup_profile_pa_historical_statcast_window(
                rows,
                observed_window_digest=(
                    observed_window_digest
                ),
                lineup_bullpen_window_digest=(
                    lineup_bullpen_window_digest
                ),
                candidate_window_days=(
                    args.window_days
                ),
                evaluation_game_pks=(
                    selected_game_pks
                ),
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
    finally:
        session.close()

    elapsed = (
        dt.datetime.now(dt.timezone.utc)
        - started
    ).total_seconds()
    summary = _summary(
        args=args,
        load_start=load_start,
        rows=rows,
        selected_game_pks=(
            selected_game_pks
        ),
        result=result,
        elapsed_seconds=elapsed,
    )

    print(
        json.dumps(
            summary,
            indent=2,
            sort_keys=True,
        )
    )

    if summary[
        "production_authority_changed"
    ] is not False:
        raise SystemExit(
            "STOP: production authority changed."
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

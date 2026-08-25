"""Assemble multi-game historical PA evaluation from Statcast events.

This orchestration layer reuses one immutable event collection to infer
starters, construct cutoff-safe statistics and pitcher candidates, and execute
the paired historical PA evaluation.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
from collections import defaultdict
from typing import Any, Iterable, Mapping

from mlb_app.simulation.shadow.canonical_pitcher_matchup_profile_pa_historical_candidates import (
    materialize_canonical_pitcher_matchup_profile_pa_historical_candidates,
)
from mlb_app.simulation.shadow.canonical_pitcher_matchup_profile_pa_historical_executor import (
    execute_canonical_pitcher_matchup_profile_pa_historical_evaluation,
)
from mlb_app.simulation.shadow.canonical_pitcher_matchup_profile_pa_historical_starters import (
    source_canonical_pitcher_matchup_profile_pa_historical_starters,
)
from mlb_app.simulation.shadow.canonical_pitcher_matchup_profile_pa_historical_statcast_statistics import (
    source_canonical_pitcher_matchup_profile_pa_historical_statcast_statistics,
)
from mlb_app.simulation.shadow.historical_probability_statistics_source import (
    CanonicalHistoricalProbabilityStatisticsWindow,
)


SCHEMA_VERSION = (
    "canonical_pitcher_matchup_profile_pa_historical_statcast_window_v1"
)


def _value(row: Any, name: str) -> Any:
    if isinstance(row, Mapping):
        return row.get(name)
    return getattr(row, name, None)


def _digest(value: Any) -> str:
    payload = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _positive_integer(
    value: Any,
    name: str,
) -> int:
    if isinstance(value, bool):
        raise ValueError(
            f"{name}_must_be_positive_integer"
        )

    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"{name}_must_be_positive_integer"
        ) from exc

    if parsed <= 0:
        raise ValueError(
            f"{name}_must_be_positive_integer"
        )

    return parsed


def _date(value: Any) -> dt.date:
    if isinstance(value, dt.datetime):
        return value.date()
    if isinstance(value, dt.date):
        return value
    if isinstance(value, str):
        try:
            return dt.date.fromisoformat(value)
        except ValueError as exc:
            raise ValueError(
                "game_date_must_be_iso_date"
            ) from exc
    raise ValueError(
        "game_date_must_be_iso_date"
    )


def _unavailable(
    *,
    events: list[Any],
    starters: Mapping[str, Any],
    blocker: str,
    observed_window_digest: str,
    lineup_bullpen_window_digest: str,
) -> dict[str, Any]:
    diagnostics = {
        "schema_version": SCHEMA_VERSION,
        "status": "unavailable",
        "activation_status": (
            "historical_pa_evaluation_unavailable"
        ),
        "blockers": [blocker],
        "raw_event_count": len(events),
        "game_count": 0,
        "starter_request_count": 0,
        "statistics_game_count": 0,
        "candidate_count": 0,
        "single_shared_event_collection": True,
        "lookback_events_reused_for_evaluation": True,
        "starter_inference_pass_count": 1,
        "candidate_materialization_pass_count": 0,
        "statistics_materialization_count": 0,
        "database_accessed": False,
        "calibration_parameters_selected": False,
        "shadow_only": True,
        "production_inputs_unchanged": True,
        "production_authority": False,
        "production_authority_changed": False,
        "observed_window_digest": (
            observed_window_digest
        ),
        "lineup_bullpen_window_digest": (
            lineup_bullpen_window_digest
        ),
    }
    diagnostics["window_execution_digest"] = (
        _digest(diagnostics)
    )

    return {
        "starters": dict(starters),
        "statistics": None,
        "candidates": None,
        "execution": None,
        "diagnostics": diagnostics,
    }


def execute_canonical_pitcher_matchup_profile_pa_historical_statcast_window(
    events: Iterable[Any],
    *,
    observed_window_digest: str,
    lineup_bullpen_window_digest: str,
    candidate_window_days: int = 90,
    evaluation_game_pks: Iterable[int] | None = None,
    minimum_samples: int = 30,
    minimum_observed_pa: int = 1000,
    season_log_loss_regression_tolerance: float = 0.0,
) -> dict[str, Any]:
    """Execute cutoff-safe historical PA comparison across Statcast games."""

    observed_digest = str(
        observed_window_digest
    ).strip()
    lineup_digest = str(
        lineup_bullpen_window_digest
    ).strip()

    if not observed_digest:
        raise ValueError(
            "observed_window_digest_required"
        )
    if not lineup_digest:
        raise ValueError(
            "lineup_bullpen_window_digest_required"
        )

    window_days = _positive_integer(
        candidate_window_days,
        "candidate_window_days",
    )
    rows = list(events)

    starters = (
        source_canonical_pitcher_matchup_profile_pa_historical_starters(
            rows
        )
    )
    starter_events = list(
        starters.get("starter_events") or ()
    )
    requests = list(
        starters.get("requests") or ()
    )

    selected_game_pks = None

    if evaluation_game_pks is not None:
        selected_game_pks = {
            _positive_integer(
                value,
                "evaluation_game_pk",
            )
            for value in evaluation_game_pks
        }

        if not selected_game_pks:
            raise ValueError(
                "evaluation_game_pks_must_not_be_empty"
            )

        requests = [
            request
            for request in requests
            if _positive_integer(
                _value(request, "game_pk"),
                "game_pk",
            )
            in selected_game_pks
        ]
        starter_events = [
            event
            for event in starter_events
            if _positive_integer(
                _value(event, "game_pk"),
                "game_pk",
            )
            in selected_game_pks
        ]

    if not requests:
        return _unavailable(
            events=rows,
            starters=starters,
            blocker="no_historical_starter_requests",
            observed_window_digest=(
                observed_digest
            ),
            lineup_bullpen_window_digest=(
                lineup_digest
            ),
        )

    requests_by_game: dict[
        int,
        list[dict[str, Any]],
    ] = defaultdict(list)

    for request in requests:
        game_pk = _positive_integer(
            _value(request, "game_pk"),
            "game_pk",
        )
        pitcher_id = _positive_integer(
            _value(request, "pitcher_id"),
            "pitcher_id",
        )
        game_date = _date(
            _value(request, "game_date")
        )

        requests_by_game[game_pk].append({
            "game_pk": game_pk,
            "pitcher_id": pitcher_id,
            "game_date": game_date,
            "side": _value(request, "side"),
        })

    statistics_games = []
    statistics_diagnostics = []
    rejected_games = []

    for game_pk in sorted(requests_by_game):
        game_requests = sorted(
            requests_by_game[game_pk],
            key=lambda value: (
                value["pitcher_id"],
                str(value.get("side")),
            ),
        )
        game_dates = {
            request["game_date"]
            for request in game_requests
        }

        if len(game_dates) != 1:
            rejected_games.append({
                "game_pk": game_pk,
                "reason": (
                    "conflicting_game_dates"
                ),
            })
            continue

        game_date = next(iter(game_dates))
        pitcher_ids = tuple(sorted({
            request["pitcher_id"]
            for request in game_requests
        }))
        batter_ids = tuple(sorted({
            _positive_integer(
                _value(event, "batter_id"),
                "batter_id",
            )
            for event in starter_events
            if _value(event, "game_pk") == game_pk
            and _value(event, "batter_id") is not None
        }))

        if not batter_ids:
            rejected_games.append({
                "game_pk": game_pk,
                "reason": (
                    "no_historical_batters"
                ),
            })
            continue

        statistics_result = (
            source_canonical_pitcher_matchup_profile_pa_historical_statcast_statistics(
                rows,
                game_pk=game_pk,
                game_date=game_date,
                batter_ids=batter_ids,
                pitcher_ids=pitcher_ids,
                observed_window_digest=(
                    observed_digest
                ),
                lineup_bullpen_window_digest=(
                    lineup_digest
                ),
            )
        )
        statistics = statistics_result[
            "statistics"
        ]
        statistics_games.extend(
            statistics.games
        )
        statistics_diagnostics.append(
            dict(
                statistics_result.get(
                    "diagnostics"
                )
                or {}
            )
        )

    if not statistics_games:
        result = _unavailable(
            events=rows,
            starters=starters,
            blocker=(
                "no_historical_statistics_games"
            ),
            observed_window_digest=(
                observed_digest
            ),
            lineup_bullpen_window_digest=(
                lineup_digest
            ),
        )
        result["diagnostics"][
            "rejected_games"
        ] = rejected_games
        return result

    statistics_games = sorted(
        statistics_games,
        key=lambda game: (
            game.game_date,
            game.game_pk,
        ),
    )
    statistics_window_digest = _digest({
        "schema_version": SCHEMA_VERSION,
        "observed_window_digest": (
            observed_digest
        ),
        "lineup_bullpen_window_digest": (
            lineup_digest
        ),
        "games": [
            {
                "game_pk": game.game_pk,
                "game_date": game.game_date,
                "statistics_through_date": (
                    game.statistics_through_date
                ),
                "snapshot_digest": (
                    game.snapshot_digest
                ),
            }
            for game in statistics_games
        ],
    })
    statistics_window = (
        CanonicalHistoricalProbabilityStatisticsWindow(
            observed_window_digest=(
                observed_digest
            ),
            lineup_bullpen_window_digest=(
                lineup_digest
            ),
            games=tuple(statistics_games),
            digest=statistics_window_digest,
        )
    )

    candidates = (
        materialize_canonical_pitcher_matchup_profile_pa_historical_candidates(
            rows,
            requests=requests,
            window_days=window_days,
        )
    )
    execution = (
        execute_canonical_pitcher_matchup_profile_pa_historical_evaluation(
            starter_events,
            statistics=statistics_window,
            candidates_by_game_pitcher=(
                candidates.get("candidates")
                or {}
            ),
            minimum_samples=minimum_samples,
            minimum_observed_pa=(
                minimum_observed_pa
            ),
            season_log_loss_regression_tolerance=(
                season_log_loss_regression_tolerance
            ),
        )
    )

    starter_diagnostics = dict(
        starters.get("diagnostics") or {}
    )
    candidate_diagnostics = dict(
        candidates.get("diagnostics") or {}
    )
    execution_diagnostics = dict(
        execution.get("diagnostics") or {}
    )
    evaluation_diagnostics = dict(
        (
            execution.get("evaluation")
            or {}
        ).get("diagnostics")
        or {}
    )

    component_statuses = (
        starter_diagnostics.get("status"),
        *(
            value.get("status")
            for value in statistics_diagnostics
        ),
        candidate_diagnostics.get("status"),
        execution_diagnostics.get("status"),
    )

    if evaluation_diagnostics.get(
        "selection_gate_passed"
    ):
        status = "ready"
        activation_status = (
            "historical_pa_gate_passed"
        )
    elif any(
        value == "unavailable"
        for value in component_statuses
    ):
        status = "unavailable"
        activation_status = (
            "historical_pa_evaluation_unavailable"
        )
    else:
        status = "partial"
        activation_status = (
            evaluation_diagnostics.get(
                "activation_status"
            )
            or "historical_pa_gate_blocked"
        )

    diagnostics = {
        "schema_version": SCHEMA_VERSION,
        "status": status,
        "activation_status": (
            activation_status
        ),
        "raw_event_count": len(rows),
        "evaluation_game_filter_applied": (
            selected_game_pks is not None
        ),
        "requested_evaluation_game_count": (
            len(selected_game_pks)
            if selected_game_pks is not None
            else None
        ),
        "game_count": len(
            requests_by_game
        ),
        "starter_request_count": len(
            requests
        ),
        "starter_event_count": len(
            starter_events
        ),
        "statistics_game_count": len(
            statistics_games
        ),
        "candidate_count": len(
            candidates.get("candidates")
            or {}
        ),
        "rejected_game_count": len(
            rejected_games
        ),
        "rejected_games": rejected_games,
        "component_statuses": (
            component_statuses
        ),
        "statistics_diagnostics": (
            statistics_diagnostics
        ),
        "single_shared_event_collection": True,
        "lookback_events_reused_for_evaluation": True,
        "starter_inference_pass_count": 1,
        "candidate_materialization_pass_count": 1,
        "statistics_materialization_count": (
            len(statistics_games)
        ),
        "cutoff_policy": (
            "per_game_same_season_strictly_before_game_date"
        ),
        "pipeline": (
            "starters_to_statistics_and_candidates_to_historical_evaluation"
        ),
        "database_accessed": False,
        "calibration_parameters_selected": False,
        "shadow_only": True,
        "production_inputs_unchanged": True,
        "production_authority": False,
        "production_authority_changed": False,
        "starter_window_digest": (
            starter_diagnostics.get(
                "starter_window_digest"
            )
        ),
        "statistics_window_digest": (
            statistics_window_digest
        ),
        "candidate_window_digest": (
            candidate_diagnostics.get(
                "candidate_window_digest"
            )
        ),
        "execution_digest": (
            execution_diagnostics.get(
                "execution_digest"
            )
        ),
    }
    diagnostics["window_execution_digest"] = (
        _digest(diagnostics)
    )

    return {
        "starters": starters,
        "statistics": statistics_window,
        "candidates": candidates,
        "execution": execution,
        "diagnostics": diagnostics,
    }

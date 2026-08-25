import copy
import datetime as dt
import hashlib

import pytest

import mlb_app.simulation.shadow.canonical_pitcher_matchup_profile_pa_historical_statcast_window as window_module
from mlb_app.simulation.shadow.historical_probability_statistics_source import (
    HITTING_STAT_KEYS,
    PITCHING_STAT_KEYS,
    CanonicalHistoricalProbabilityGameStatistics,
    CanonicalHistoricalProbabilityPlayerStatistics,
    CanonicalHistoricalProbabilityStatisticsWindow,
)


def digest(value):
    return hashlib.sha256(
        str(value).encode("utf-8")
    ).hexdigest()


def event(
    *,
    game_pk=700001,
    game_date=dt.date(2025, 7, 1),
    pitcher_id=800,
    batter_id=900,
):
    return {
        "game_pk": game_pk,
        "game_date": game_date,
        "pitcher_id": pitcher_id,
        "batter_id": batter_id,
        "events": "single",
        "at_bat_number": 1,
        "pitch_number": 1,
        "inning": 1,
        "inning_topbot": "Top",
    }


def player(
    player_id,
    role,
):
    keys = (
        HITTING_STAT_KEYS
        if role == "hitting"
        else PITCHING_STAT_KEYS
    )
    return (
        CanonicalHistoricalProbabilityPlayerStatistics(
            player_id=str(player_id),
            role=role,
            counts=tuple(
                (key, 1)
                for key, _ in keys
            ),
            sample_available=True,
        )
    )


def install_components(
    monkeypatch,
    *,
    no_requests=False,
    conflicting_dates=False,
    no_batters=False,
    gate_passed=True,
    statistics_status="ready",
):
    calls = {
        "starter": 0,
        "statistics": 0,
        "candidate": 0,
        "executor": 0,
    }

    def starters(rows):
        calls["starter"] += 1

        if no_requests:
            requests = []
            starter_events = []
        else:
            second_date = (
                dt.date(2025, 7, 2)
                if conflicting_dates
                else dt.date(2025, 7, 1)
            )
            requests = [
                {
                    "game_pk": 700001,
                    "pitcher_id": 800,
                    "game_date": dt.date(
                        2025,
                        7,
                        1,
                    ),
                    "side": "away",
                },
                {
                    "game_pk": 700001,
                    "pitcher_id": 801,
                    "game_date": second_date,
                    "side": "home",
                },
                {
                    "game_pk": 700002,
                    "pitcher_id": 802,
                    "game_date": dt.date(
                        2025,
                        7,
                        2,
                    ),
                    "side": "away",
                },
            ]
            starter_events = (
                []
                if no_batters
                else [
                    event(),
                    event(
                        game_pk=700001,
                        pitcher_id=801,
                        batter_id=901,
                    ),
                    event(
                        game_pk=700002,
                        game_date=dt.date(
                            2025,
                            7,
                            2,
                        ),
                        pitcher_id=802,
                        batter_id=902,
                    ),
                ]
            )

        return {
            "starter_events": starter_events,
            "requests": requests,
            "diagnostics": {
                "status": (
                    "unavailable"
                    if no_requests
                    else "ready"
                ),
                "starter_window_digest": (
                    "starter-digest"
                ),
                "production_authority_changed": False,
            },
        }

    def statistics(
        rows,
        *,
        game_pk,
        game_date,
        batter_ids,
        pitcher_ids,
        observed_window_digest,
        lineup_bullpen_window_digest,
    ):
        calls["statistics"] += 1
        game_date = dt.date.fromisoformat(
            game_date
        ) if isinstance(
            game_date,
            str,
        ) else game_date

        players = tuple(
            player(value, "hitting")
            for value in batter_ids
        ) + tuple(
            player(value, "pitching")
            for value in pitcher_ids
        )
        game = (
            CanonicalHistoricalProbabilityGameStatistics(
                game_pk=game_pk,
                game_date=game_date.isoformat(),
                statistics_through_date=(
                    game_date
                    - dt.timedelta(days=1)
                ).isoformat(),
                players=players,
                snapshot_digest=digest(
                    f"snapshot-{game_pk}"
                ),
            )
        )
        window = (
            CanonicalHistoricalProbabilityStatisticsWindow(
                observed_window_digest=(
                    observed_window_digest
                ),
                lineup_bullpen_window_digest=(
                    lineup_bullpen_window_digest
                ),
                games=(game,),
                digest=digest(
                    f"window-{game_pk}"
                ),
            )
        )

        return {
            "statistics": window,
            "diagnostics": {
                "status": statistics_status,
                "game_pk": game_pk,
                "production_authority_changed": False,
            },
        }

    def candidates(
        rows,
        *,
        requests,
        window_days,
    ):
        calls["candidate"] += 1
        values = {
            (
                request["game_pk"],
                request["pitcher_id"],
            ): {
                "diagnostics": {
                    "status": "ready",
                    "production_authority_changed": False,
                },
            }
            for request in requests
        }
        return {
            "candidates": values,
            "diagnostics": {
                "status": "ready",
                "candidate_window_digest": (
                    f"candidate-{window_days}"
                ),
                "production_authority_changed": False,
            },
        }

    def executor(
        rows,
        *,
        statistics,
        candidates_by_game_pitcher,
        minimum_samples,
        minimum_observed_pa,
        season_log_loss_regression_tolerance,
    ):
        calls["executor"] += 1
        return {
            "evaluation": {
                "overall": {
                    "status": "ready",
                    "observed_pa": 3,
                },
                "diagnostics": {
                    "status": "ready",
                    "selection_gate_passed": (
                        gate_passed
                    ),
                    "activation_status": (
                        "historical_pa_gate_passed"
                        if gate_passed
                        else "historical_pa_gate_blocked"
                    ),
                    "production_authority_changed": False,
                },
            },
            "diagnostics": {
                "status": "ready",
                "execution_digest": (
                    "execution-digest"
                ),
                "production_authority_changed": False,
            },
        }

    monkeypatch.setattr(
        window_module,
        "source_canonical_pitcher_matchup_profile_pa_historical_starters",
        starters,
    )
    monkeypatch.setattr(
        window_module,
        "source_canonical_pitcher_matchup_profile_pa_historical_statcast_statistics",
        statistics,
    )
    monkeypatch.setattr(
        window_module,
        "materialize_canonical_pitcher_matchup_profile_pa_historical_candidates",
        candidates,
    )
    monkeypatch.setattr(
        window_module,
        "execute_canonical_pitcher_matchup_profile_pa_historical_evaluation",
        executor,
    )

    return calls


def execute():
    return (
        window_module.execute_canonical_pitcher_matchup_profile_pa_historical_statcast_window(
            [
                event(),
                event(
                    game_pk=700002,
                    game_date=dt.date(
                        2025,
                        7,
                        2,
                    ),
                    pitcher_id=802,
                    batter_id=902,
                ),
            ],
            observed_window_digest=digest(
                "observed-window"
            ),
            lineup_bullpen_window_digest=digest(
                "lineup-window"
            ),
            candidate_window_days=90,
            minimum_samples=1,
            minimum_observed_pa=1,
        )
    )


def test_executes_multi_game_window(monkeypatch):
    calls = install_components(monkeypatch)

    result = execute()
    diagnostics = result["diagnostics"]

    assert diagnostics["status"] == "ready"
    assert diagnostics[
        "activation_status"
    ] == "historical_pa_gate_passed"
    assert diagnostics["game_count"] == 2
    assert diagnostics[
        "statistics_game_count"
    ] == 2
    assert len(
        result["statistics"].games
    ) == 2
    assert calls == {
        "starter": 1,
        "statistics": 2,
        "candidate": 1,
        "executor": 1,
    }


def test_reuses_single_event_collection(monkeypatch):
    install_components(monkeypatch)

    diagnostics = execute()["diagnostics"]

    assert diagnostics[
        "single_shared_event_collection"
    ] is True
    assert diagnostics[
        "starter_inference_pass_count"
    ] == 1
    assert diagnostics[
        "candidate_materialization_pass_count"
    ] == 1
    assert diagnostics[
        "statistics_materialization_count"
    ] == 2


def test_statistics_games_are_canonical_order(
    monkeypatch,
):
    install_components(monkeypatch)

    games = execute()["statistics"].games

    assert tuple(
        game.game_pk
        for game in games
    ) == (700001, 700002)


def test_gate_block_remains_partial(monkeypatch):
    install_components(
        monkeypatch,
        gate_passed=False,
    )

    diagnostics = execute()["diagnostics"]

    assert diagnostics["status"] == "partial"
    assert diagnostics[
        "activation_status"
    ] == "historical_pa_gate_blocked"


def test_partial_statistics_remain_executable(
    monkeypatch,
):
    calls = install_components(
        monkeypatch,
        statistics_status="partial",
    )

    result = execute()

    assert result["execution"] is not None
    assert calls["executor"] == 1


def test_no_starter_requests_fail_closed(
    monkeypatch,
):
    calls = install_components(
        monkeypatch,
        no_requests=True,
    )

    result = execute()
    diagnostics = result["diagnostics"]

    assert diagnostics["status"] == "unavailable"
    assert diagnostics["blockers"] == [
        "no_historical_starter_requests"
    ]
    assert result["statistics"] is None
    assert result["candidates"] is None
    assert result["execution"] is None
    assert calls["candidate"] == 0
    assert calls["executor"] == 0


def test_conflicting_game_dates_are_rejected(
    monkeypatch,
):
    install_components(
        monkeypatch,
        conflicting_dates=True,
    )

    result = execute()
    diagnostics = result["diagnostics"]

    assert diagnostics[
        "rejected_game_count"
    ] == 1
    assert diagnostics[
        "rejected_games"
    ][0]["reason"] == (
        "conflicting_game_dates"
    )
    assert tuple(
        game.game_pk
        for game in result[
            "statistics"
        ].games
    ) == (700002,)


def test_no_historical_batters_fail_closed(
    monkeypatch,
):
    calls = install_components(
        monkeypatch,
        no_batters=True,
    )

    result = execute()

    assert result["diagnostics"][
        "status"
    ] == "unavailable"
    assert result["diagnostics"][
        "blockers"
    ] == [
        "no_historical_statistics_games"
    ]
    assert calls["statistics"] == 0
    assert calls["candidate"] == 0
    assert calls["executor"] == 0


def test_evaluation_game_filter_preserves_lookback_events(
    monkeypatch,
):
    calls = install_components(monkeypatch)

    result = (
        window_module.execute_canonical_pitcher_matchup_profile_pa_historical_statcast_window(
            [
                event(),
                event(
                    game_pk=700002,
                    game_date=dt.date(2025, 7, 2),
                    pitcher_id=802,
                    batter_id=902,
                ),
            ],
            observed_window_digest=digest(
                "observed-filter"
            ),
            lineup_bullpen_window_digest=digest(
                "lineup-filter"
            ),
            evaluation_game_pks=(700002,),
            minimum_samples=1,
            minimum_observed_pa=1,
        )
    )
    diagnostics = result["diagnostics"]

    assert diagnostics[
        "evaluation_game_filter_applied"
    ] is True
    assert diagnostics[
        "requested_evaluation_game_count"
    ] == 1
    assert diagnostics["raw_event_count"] == 2
    assert diagnostics["game_count"] == 1
    assert diagnostics[
        "statistics_game_count"
    ] == 1
    assert tuple(
        game.game_pk
        for game in result["statistics"].games
    ) == (700002,)
    assert calls == {
        "starter": 1,
        "statistics": 1,
        "candidate": 1,
        "executor": 1,
    }


def test_unknown_evaluation_game_fails_closed(
    monkeypatch,
):
    calls = install_components(monkeypatch)

    result = (
        window_module.execute_canonical_pitcher_matchup_profile_pa_historical_statcast_window(
            [event()],
            observed_window_digest=digest(
                "observed-unknown"
            ),
            lineup_bullpen_window_digest=digest(
                "lineup-unknown"
            ),
            evaluation_game_pks=(799999,),
            minimum_samples=1,
            minimum_observed_pa=1,
        )
    )

    assert result["diagnostics"]["status"] == (
        "unavailable"
    )
    assert result["diagnostics"]["blockers"] == [
        "no_historical_starter_requests"
    ]
    assert calls["candidate"] == 0
    assert calls["executor"] == 0


@pytest.mark.parametrize(
    "values",
    [
        (),
        (0,),
        (True,),
    ],
)
def test_evaluation_game_filter_must_be_valid(
    monkeypatch,
    values,
):
    install_components(monkeypatch)

    with pytest.raises(ValueError):
        window_module.execute_canonical_pitcher_matchup_profile_pa_historical_statcast_window(
            [event()],
            observed_window_digest=digest(
                "observed-invalid-filter"
            ),
            lineup_bullpen_window_digest=digest(
                "lineup-invalid-filter"
            ),
            evaluation_game_pks=values,
            minimum_samples=1,
            minimum_observed_pa=1,
        )


def test_execution_is_deterministic(monkeypatch):
    install_components(monkeypatch)

    first = execute()
    second = execute()

    assert first["diagnostics"][
        "window_execution_digest"
    ] == second["diagnostics"][
        "window_execution_digest"
    ]
    assert first["statistics"].digest == (
        second["statistics"].digest
    )


def test_input_events_are_not_mutated(monkeypatch):
    install_components(monkeypatch)
    values = [event()]
    original = copy.deepcopy(values)

    window_module.execute_canonical_pitcher_matchup_profile_pa_historical_statcast_window(
        values,
        observed_window_digest=digest(
            "observed"
        ),
        lineup_bullpen_window_digest=digest(
            "lineup"
        ),
        minimum_samples=1,
        minimum_observed_pa=1,
    )

    assert values == original


@pytest.mark.parametrize(
    "kwargs,reason",
    [
        (
            {
                "observed_window_digest": "",
                "lineup_bullpen_window_digest": "lineup",
            },
            "observed_window_digest_required",
        ),
        (
            {
                "observed_window_digest": "observed",
                "lineup_bullpen_window_digest": "",
            },
            "lineup_bullpen_window_digest_required",
        ),
        (
            {
                "observed_window_digest": "observed",
                "lineup_bullpen_window_digest": "lineup",
                "candidate_window_days": 0,
            },
            "candidate_window_days_must_be_positive_integer",
        ),
    ],
)
def test_invalid_contracts_raise(
    monkeypatch,
    kwargs,
    reason,
):
    install_components(monkeypatch)

    with pytest.raises(
        ValueError,
        match=reason,
    ):
        window_module.execute_canonical_pitcher_matchup_profile_pa_historical_statcast_window(
            [event()],
            **kwargs,
        )


def test_shadow_authority_contract(monkeypatch):
    install_components(monkeypatch)

    diagnostics = execute()["diagnostics"]

    assert diagnostics["database_accessed"] is False
    assert diagnostics[
        "calibration_parameters_selected"
    ] is False
    assert diagnostics["shadow_only"] is True
    assert diagnostics[
        "production_inputs_unchanged"
    ] is True
    assert diagnostics[
        "production_authority"
    ] is False
    assert diagnostics[
        "production_authority_changed"
    ] is False
    assert diagnostics["cutoff_policy"] == (
        "per_game_same_season_strictly_before_game_date"
    )

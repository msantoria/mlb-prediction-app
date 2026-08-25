import datetime as dt

from mlb_app.model_projections import (
    _materialize_pitcher_matchup_profile_runtime_batch,
)


MATCHUPS = [
    {
        "away_pitcher_id": 101,
        "home_pitcher_id": 102,
    },
    {
        "away_pitcher_id": 101,
        "home_pitcher_id": 103,
    },
]


def test_loads_one_terminal_window_for_all_pitchers():
    calls = {
        "loader": 0,
        "builder": 0,
    }

    def loader(
        session,
        *filters,
        order_by=None,
    ):
        calls["loader"] += 1
        assert session == "session"
        assert len(filters) == 3
        assert order_by
        return (
            [{"pitcher_id": 101}],
            {
                "raw_rows": 1,
                "canonical_pitch_rows": 1,
            },
        )

    def builder(
        events,
        *,
        pitcher_ids,
        game_date,
        window_days,
    ):
        calls["builder"] += 1
        assert len(events) == 1
        assert pitcher_ids == (
            101,
            102,
            103,
        )
        assert game_date == dt.date(
            2026,
            8,
            23,
        )
        assert window_days == 90

        return {
            "candidates": {
                "101": {
                    "profile_rates": {
                        "k_rate": 0.22,
                    },
                },
            },
            "diagnostics": {
                "status": "ready",
                "single_shared_evidence_pass": True,
            },
        }

    result = (
        _materialize_pitcher_matchup_profile_runtime_batch(
            session="session",
            matchups=MATCHUPS,
            game_date=dt.date(
                2026,
                8,
                23,
            ),
            event_loader=loader,
            batch_builder=builder,
        )
    )

    assert calls == {
        "loader": 1,
        "builder": 1,
    }
    assert result["diagnostics"][
        "single_terminal_event_load"
    ] is True
    assert result["diagnostics"][
        "terminal_event_count"
    ] == 1
    assert result["diagnostics"][
        "production_authority"
    ] is False


def test_deduplicates_probable_pitcher_ids():
    captured = {}

    def loader(*args, **kwargs):
        return [], {}

    def builder(
        events,
        *,
        pitcher_ids,
        **kwargs,
    ):
        captured["pitcher_ids"] = (
            pitcher_ids
        )
        return {
            "candidates": {},
            "diagnostics": {
                "status": "ready",
            },
        }

    _materialize_pitcher_matchup_profile_runtime_batch(
        session=None,
        matchups=MATCHUPS,
        game_date=dt.date(
            2026,
            8,
            23,
        ),
        event_loader=loader,
        batch_builder=builder,
    )

    assert captured["pitcher_ids"] == (
        101,
        102,
        103,
    )


def test_database_failure_fails_open():
    def loader(*args, **kwargs):
        raise RuntimeError(
            "database unavailable"
        )

    result = (
        _materialize_pitcher_matchup_profile_runtime_batch(
            session=None,
            matchups=MATCHUPS,
            game_date=dt.date(
                2026,
                8,
                23,
            ),
            event_loader=loader,
        )
    )

    assert result["candidates"] == {}
    assert result["diagnostics"]["status"] == (
        "error"
    )
    assert result["diagnostics"][
        "blockers"
    ] == [
        "runtime_candidate_batch_failed"
    ]
    assert (
        result["diagnostics"][
            "production_authority_changed"
        ]
        is False
    )


def test_missing_pitchers_skips_database_load():
    calls = []

    def loader(*args, **kwargs):
        calls.append(True)
        return [], {}

    result = (
        _materialize_pitcher_matchup_profile_runtime_batch(
            session=None,
            matchups=[{}],
            game_date=dt.date(
                2026,
                8,
                23,
            ),
            event_loader=loader,
        )
    )

    assert calls == []
    assert result["diagnostics"]["status"] == (
        "unavailable"
    )
    assert result["diagnostics"][
        "single_terminal_event_load"
    ] is False

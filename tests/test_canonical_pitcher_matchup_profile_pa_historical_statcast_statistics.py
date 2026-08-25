from __future__ import annotations

from copy import deepcopy
from types import SimpleNamespace

import pytest

from mlb_app.simulation.shadow.canonical_pitcher_matchup_profile_pa_historical_statcast_statistics import (
    source_canonical_pitcher_matchup_profile_pa_historical_statcast_statistics,
)
from mlb_app.simulation.shadow.historical_probability_statistics_source import (
    CanonicalHistoricalProbabilityStatisticsWindow,
)


DIGEST_A = "a" * 64
DIGEST_B = "b" * 64


def event(**overrides):
    values = {
        "game_pk": 600001,
        "game_date": "2025-06-01",
        "at_bat_number": 1,
        "pitcher_id": 101,
        "batter_id": 201,
        "events": "single",
    }
    values.update(overrides)
    return values


def history():
    event_names = [
        "single",
        "double",
        "triple",
        "home_run",
        "walk",
        "intent_walk",
        "strikeout",
        "hit_by_pitch",
        "sac_fly",
        "field_out",
    ]

    return [
        event(
            at_bat_number=index,
            events=event_name,
        )
        for index, event_name in enumerate(
            event_names,
            start=1,
        )
    ]


def source(
    rows=None,
    **overrides,
):
    values = {
        "game_pk": 700001,
        "game_date": "2025-07-01",
        "batter_ids": [201],
        "pitcher_ids": [101],
        "observed_window_digest": DIGEST_A,
        "lineup_bullpen_window_digest": (
            DIGEST_B
        ),
    }
    values.update(overrides)

    return (
        source_canonical_pitcher_matchup_profile_pa_historical_statcast_statistics(
            history() if rows is None else rows,
            **values,
        )
    )


def record_map(result):
    game = result["statistics"].games[0]

    return {
        record.record_key: dict(
            record.counts
        )
        for record in game.players
    }


def test_builds_exact_historical_counts():
    result = source()
    records = record_map(result)

    assert result["diagnostics"]["status"] == "ready"

    assert records[
        ("hitting", "201")
    ] == {
        "pa": 10,
        "ab": 6,
        "hits": 4,
        "double": 1,
        "triple": 1,
        "hr": 1,
        "bb": 2,
        "k": 1,
        "hbp": 1,
    }
    assert records[
        ("pitching", "101")
    ] == {
        "batters_faced": 10,
        "ab": 6,
        "hits": 4,
        "double": 1,
        "triple": 1,
        "hr": 1,
        "bb": 2,
        "k": 1,
        "hbp": 1,
    }


def test_emits_canonical_statistics_window():
    result = source()
    statistics = result["statistics"]

    assert isinstance(
        statistics,
        CanonicalHistoricalProbabilityStatisticsWindow,
    )
    assert statistics.game_count == 1

    game = statistics.games[0]

    assert game.game_pk == 700001
    assert game.game_date == "2025-07-01"
    assert game.statistics_through_date == (
        "2025-06-30"
    )
    assert game.observed_sample_count == 2
    assert game.zero_sample_count == 0


def test_excludes_same_day_and_future_rows():
    rows = history()
    rows.extend([
        event(
            game_pk=700001,
            game_date="2025-07-01",
            at_bat_number=1,
            events="home_run",
        ),
        event(
            game_pk=700002,
            game_date="2025-07-02",
            at_bat_number=1,
            events="home_run",
        ),
    ])

    result = source(rows)
    records = record_map(result)

    assert records[
        ("hitting", "201")
    ]["hr"] == 1
    assert result["diagnostics"][
        "excluded_future_or_same_day_count"
    ] == 2


def test_excludes_other_seasons():
    rows = history()
    rows.append(
        event(
            game_pk=500001,
            game_date="2024-06-01",
            at_bat_number=1,
            events="home_run",
        )
    )

    result = source(rows)

    assert record_map(result)[
        ("hitting", "201")
    ]["hr"] == 1
    assert result["diagnostics"][
        "excluded_other_season_count"
    ] == 1


def test_ignores_nonterminal_pitch_rows():
    rows = history()
    rows.append(
        event(
            at_bat_number=20,
            events=None,
        )
    )

    result = source(rows)

    assert result["diagnostics"][
        "nonterminal_pitch_count"
    ] == 1
    assert result["diagnostics"][
        "eligible_terminal_pa_count"
    ] == 10


def test_deduplicates_terminal_identity():
    rows = history()
    rows.append(
        deepcopy(rows[0])
    )

    result = source(rows)

    assert result["diagnostics"][
        "duplicate_terminal_count"
    ] == 1
    assert record_map(result)[
        ("hitting", "201")
    ]["pa"] == 10


def test_conflicting_terminal_identity_fails_closed():
    rows = history()
    rows.append({
        **rows[0],
        "events": "double",
    })

    result = source(rows)
    records = record_map(result)

    assert result["diagnostics"][
        "conflicting_terminal_count"
    ] == 1
    assert result["diagnostics"][
        "rejected_rows"
    ][0]["reason"] == (
        "conflicting_terminal_pa_identity"
    )
    assert records[
        ("hitting", "201")
    ]["pa"] == 9
    assert records[
        ("hitting", "201")
    ]["hits"] == 3


def test_unsupported_event_is_reported():
    rows = history()
    rows.append(
        event(
            at_bat_number=20,
            events="synthetic_event",
        )
    )

    result = source(rows)

    assert result["diagnostics"][
        "status"
    ] == "partial"
    assert result["diagnostics"][
        "rejected_rows"
    ][0]["reason"] == (
        "unsupported_terminal_event"
    )


def test_zero_sample_players_are_explicit():
    result = source(
        batter_ids=[
            201,
            202,
        ],
        pitcher_ids=[
            101,
            102,
        ],
    )
    game = result["statistics"].games[0]
    records = {
        record.record_key: record
        for record in game.players
    }

    assert result["diagnostics"][
        "status"
    ] == "partial"
    assert result["diagnostics"][
        "zero_sample_player_role_count"
    ] == 2
    assert records[
        ("hitting", "202")
    ].sample_available is False
    assert records[
        ("pitching", "102")
    ].sample_available is False
    assert all(
        value == 0
        for _, value in records[
            ("hitting", "202")
        ].counts
    )


def test_only_requested_players_are_exposed():
    rows = history()
    rows.append(
        event(
            at_bat_number=20,
            pitcher_id=102,
            batter_id=202,
            events="home_run",
        )
    )

    result = source(rows)
    keys = {
        record.record_key
        for record in (
            result["statistics"].games[0].players
        )
    }

    assert keys == {
        ("hitting", "201"),
        ("pitching", "101"),
    }


def test_supports_object_rows():
    rows = [
        SimpleNamespace(**row)
        for row in history()
    ]

    result = source(rows)

    assert result["diagnostics"][
        "status"
    ] == "ready"
    assert record_map(result)[
        ("hitting", "201")
    ]["pa"] == 10


def test_materialization_is_deterministic():
    rows = history()

    first = source(rows)
    second = source(
        list(reversed(rows))
    )

    assert first["statistics"] == (
        second["statistics"]
    )
    assert first["diagnostics"][
        "snapshot_digest"
    ] == second["diagnostics"][
        "snapshot_digest"
    ]
    assert first["diagnostics"][
        "statistics_window_digest"
    ] == second["diagnostics"][
        "statistics_window_digest"
    ]


def test_inputs_are_not_mutated():
    rows = history()
    original = deepcopy(rows)

    source(rows)

    assert rows == original


@pytest.mark.parametrize(
    "field,value",
    [
        ("game_pk", 0),
        ("game_date", "bad-date"),
        ("batter_ids", []),
        ("pitcher_ids", []),
        (
            "observed_window_digest",
            "bad",
        ),
        (
            "lineup_bullpen_window_digest",
            "bad",
        ),
    ],
)
def test_rejects_invalid_source_contract(
    field,
    value,
):
    with pytest.raises(
        (
            TypeError,
            ValueError,
        )
    ):
        source(**{field: value})


def test_cutoff_and_authority_contracts():
    diagnostics = source()["diagnostics"]

    assert diagnostics["cutoff_rule"] == (
        "same_season_terminal_pas_strictly_before_game_date"
    )
    assert diagnostics[
        "intentional_walk_policy"
    ] == "included_in_historical_bb"
    assert diagnostics["source"] == (
        "local_statcast_terminal_pa_history"
    )
    assert diagnostics["shadow_only"] is True
    assert diagnostics[
        "production_authority"
    ] is False
    assert diagnostics[
        "production_authority_changed"
    ] is False

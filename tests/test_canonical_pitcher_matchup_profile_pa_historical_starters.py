from __future__ import annotations

from copy import deepcopy
from types import SimpleNamespace

from mlb_app.simulation.shadow.canonical_pitcher_matchup_profile_pa_historical_starters import (
    source_canonical_pitcher_matchup_profile_pa_historical_starters,
)


def event(**overrides):
    values = {
        "game_pk": 700001,
        "game_date": "2025-07-01",
        "at_bat_number": 1,
        "pitch_number": 4,
        "inning": 1,
        "inning_topbot": "Top",
        "pitcher_id": 900,
        "batter_id": 201,
        "events": "field_out",
    }
    values.update(overrides)
    return values


def game_rows(
    *,
    game_pk=700001,
    game_date="2025-07-01",
):
    return [
        event(
            game_pk=game_pk,
            game_date=game_date,
            at_bat_number=1,
            inning=1,
            inning_topbot="Top",
            pitcher_id=900,
            batter_id=201,
            events="field_out",
        ),
        event(
            game_pk=game_pk,
            game_date=game_date,
            at_bat_number=2,
            inning=1,
            inning_topbot="Top",
            pitcher_id=900,
            batter_id=202,
            events="single",
        ),
        event(
            game_pk=game_pk,
            game_date=game_date,
            at_bat_number=3,
            inning=7,
            inning_topbot="Top",
            pitcher_id=901,
            batter_id=203,
            events="strikeout",
        ),
        event(
            game_pk=game_pk,
            game_date=game_date,
            at_bat_number=4,
            inning=1,
            inning_topbot="Bot",
            pitcher_id=800,
            batter_id=301,
            events="walk",
        ),
        event(
            game_pk=game_pk,
            game_date=game_date,
            at_bat_number=5,
            inning=1,
            inning_topbot="Bottom",
            pitcher_id=800,
            batter_id=302,
            events="double",
        ),
        event(
            game_pk=game_pk,
            game_date=game_date,
            at_bat_number=6,
            inning=6,
            inning_topbot="Bot",
            pitcher_id=801,
            batter_id=303,
            events="home_run",
        ),
    ]


def source(rows=None):
    return (
        source_canonical_pitcher_matchup_profile_pa_historical_starters(
            game_rows()
            if rows is None
            else rows
        )
    )


def test_identifies_away_and_home_starters():
    result = source()

    assert result["diagnostics"]["status"] == "ready"
    assert result["diagnostics"][
        "ready_game_count"
    ] == 1

    record = result["diagnostics"][
        "starter_records"
    ][0]

    assert record == {
        "game_pk": 700001,
        "game_date": "2025-07-01",
        "away_starter_id": 800,
        "home_starter_id": 900,
        "away_starter_pa_count": 2,
        "home_starter_pa_count": 2,
    }


def test_builds_candidate_requests_for_both_starters():
    result = source()

    assert result["requests"] == [
        {
            "game_pk": 700001,
            "pitcher_id": 800,
            "game_date": result[
                "requests"
            ][0]["game_date"],
            "side": "away",
        },
        {
            "game_pk": 700001,
            "pitcher_id": 900,
            "game_date": result[
                "requests"
            ][1]["game_date"],
            "side": "home",
        },
    ]

    assert all(
        request["game_date"].isoformat()
        == "2025-07-01"
        for request in result["requests"]
    )


def test_exposes_only_starter_plate_appearances():
    result = source()

    assert result["diagnostics"][
        "terminal_pa_count"
    ] == 6
    assert result["diagnostics"][
        "starter_pa_count"
    ] == 4

    assert {
        row["pitcher_id"]
        for row in result["starter_events"]
    } == {800, 900}
    assert {
        row["at_bat_number"]
        for row in result["starter_events"]
    } == {1, 2, 4, 5}


def test_starter_identity_uses_game_order():
    result = source(
        list(reversed(game_rows()))
    )

    record = result["diagnostics"][
        "starter_records"
    ][0]

    assert record["home_starter_id"] == 900
    assert record["away_starter_id"] == 800


def test_ignores_nonterminal_pitch_rows():
    rows = game_rows()
    rows.append(
        event(
            at_bat_number=7,
            events=None,
        )
    )

    result = source(rows)

    assert result["diagnostics"][
        "raw_event_count"
    ] == 7
    assert result["diagnostics"][
        "terminal_pa_count"
    ] == 6
    assert result["diagnostics"][
        "starter_pa_count"
    ] == 4


def test_deduplicates_identical_terminal_rows():
    rows = game_rows()
    rows.append(
        deepcopy(rows[0])
    )

    result = source(rows)

    assert result["diagnostics"][
        "duplicate_terminal_count"
    ] == 1
    assert result["diagnostics"][
        "terminal_pa_count"
    ] == 6
    assert result["diagnostics"][
        "starter_pa_count"
    ] == 4


def test_conflicting_terminal_identity_fails_closed():
    rows = game_rows()
    rows.append(
        event(
            at_bat_number=1,
            pitcher_id=999,
        )
    )

    result = source(rows)

    assert result["diagnostics"][
        "conflicting_terminal_count"
    ] == 1
    assert result["diagnostics"][
        "rejected_rows"
    ][0]["reason"] == (
        "conflicting_terminal_pa_identity"
    )
    assert all(
        row["at_bat_number"] != 1
        for row in result["starter_events"]
    )


def test_requires_both_game_halves():
    rows = [
        row
        for row in game_rows()
        if str(
            row["inning_topbot"]
        ).lower() == "top"
    ]

    result = source(rows)

    assert result["starter_events"] == []
    assert result["requests"] == []
    assert result["diagnostics"][
        "status"
    ] == "unavailable"
    assert result["diagnostics"][
        "rejected_games"
    ][0]["reason"] == (
        "both_game_halves_required"
    )


def test_conflicting_game_dates_fail_closed():
    rows = game_rows()
    rows[3] = {
        **rows[3],
        "game_date": "2025-07-02",
    }

    result = source(rows)

    assert result["starter_events"] == []
    assert result["diagnostics"][
        "rejected_games"
    ][0]["reason"] == (
        "conflicting_game_dates"
    )


def test_invalid_rows_do_not_block_valid_games():
    rows = game_rows()
    rows.append(
        event(
            game_pk=None,
            at_bat_number=20,
        )
    )

    result = source(rows)

    assert result["diagnostics"][
        "status"
    ] == "partial"
    assert result["diagnostics"][
        "ready_game_count"
    ] == 1
    assert result["diagnostics"][
        "rejected_row_count"
    ] == 1
    assert result["diagnostics"][
        "rejected_rows"
    ][0]["reason"] == (
        "game_pk_must_be_positive_integer"
    )


def test_supports_object_rows():
    rows = [
        SimpleNamespace(**row)
        for row in game_rows()
    ]

    result = source(rows)

    assert result["diagnostics"][
        "status"
    ] == "ready"
    assert result["diagnostics"][
        "starter_pa_count"
    ] == 4
    assert {
        row.pitcher_id
        for row in result["starter_events"]
    } == {800, 900}


def test_multiple_games_are_deterministic():
    rows = (
        game_rows()
        + game_rows(
            game_pk=700002,
            game_date="2025-07-02",
        )
    )

    first = source(rows)
    second = source(
        list(reversed(rows))
    )

    assert first["diagnostics"][
        "ready_game_count"
    ] == 2
    assert first["diagnostics"][
        "starter_request_count"
    ] == 4
    assert first["diagnostics"][
        "starter_pa_count"
    ] == 8
    assert first["requests"] == second[
        "requests"
    ]
    assert [
        (
            row["game_pk"],
            row["at_bat_number"],
        )
        for row in first["starter_events"]
    ] == [
        (
            row["game_pk"],
            row["at_bat_number"],
        )
        for row in second[
            "starter_events"
        ]
    ]
    assert first["diagnostics"][
        "starter_window_digest"
    ] == second["diagnostics"][
        "starter_window_digest"
    ]


def test_inputs_are_not_mutated():
    rows = game_rows()
    original = deepcopy(rows)

    source(rows)

    assert rows == original


def test_inference_and_authority_contracts():
    diagnostics = source()["diagnostics"]

    assert diagnostics[
        "starter_inference"
    ] == {
        "home": "first_pitcher_in_top_half",
        "away": "first_pitcher_in_bottom_half",
    }
    assert diagnostics[
        "scoring_scope"
    ] == (
        "terminal_pas_against_inferred_starters"
    )
    assert diagnostics["shadow_only"] is True
    assert diagnostics[
        "production_authority"
    ] is False
    assert diagnostics[
        "production_authority_changed"
    ] is False


def test_empty_input_is_unavailable():
    result = source([])

    assert result["starter_events"] == []
    assert result["requests"] == []
    assert result["diagnostics"][
        "status"
    ] == "unavailable"

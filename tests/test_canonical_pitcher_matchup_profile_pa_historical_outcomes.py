from __future__ import annotations

import datetime as dt

import pytest

from mlb_app.simulation.shadow.canonical_pitcher_matchup_profile_pa_historical_outcomes import (
    OUTCOME_KEYS,
    materialize_canonical_pitcher_matchup_profile_pa_historical_outcomes,
)


def event(**overrides):
    values = {
        "game_pk": 700001,
        "game_date": "2025-07-01",
        "at_bat_number": 1,
        "pitcher_id": 101,
        "batter_id": 201,
        "events": "single",
    }
    values.update(overrides)
    return values


@pytest.mark.parametrize(
    "event_name,outcome",
    [
        ("strikeout", "k"),
        ("strikeout_double_play", "k"),
        ("walk", "bb"),
        ("intent_walk", "bb"),
        ("hit_by_pitch", "hbp"),
        ("single", "single"),
        ("double", "double"),
        ("triple", "triple"),
        ("home_run", "hr"),
        ("field_error", "reached_on_error"),
        ("field_out", "out"),
        ("force_out", "out"),
        ("grounded_into_double_play", "out"),
        ("double_play", "out"),
        ("triple_play", "out"),
        ("fielders_choice", "out"),
        ("fielders_choice_out", "out"),
        ("sac_fly", "out"),
        ("sac_bunt", "out"),
    ],
)
def test_maps_supported_terminal_events(
    event_name,
    outcome,
):
    result = (
        materialize_canonical_pitcher_matchup_profile_pa_historical_outcomes(
            [
                event(events=event_name),
            ]
        )
    )

    assert result["diagnostics"]["status"] == "ready"
    assert result["diagnostics"][
        "terminal_pa_count"
    ] == 1

    sample = result["samples"][0]

    assert tuple(
        sample["observed_counts"]
    ) == OUTCOME_KEYS
    assert sample["observed_counts"][
        outcome
    ] == 1
    assert sum(
        sample["observed_counts"].values()
    ) == 1


def test_groups_by_game_pitcher_and_batter():
    result = (
        materialize_canonical_pitcher_matchup_profile_pa_historical_outcomes(
            [
                event(
                    at_bat_number=1,
                    events="single",
                ),
                event(
                    at_bat_number=2,
                    events="strikeout",
                ),
                event(
                    at_bat_number=3,
                    batter_id=202,
                    events="walk",
                ),
                event(
                    game_pk=700002,
                    at_bat_number=1,
                    events="home_run",
                ),
            ]
        )
    )

    assert result["diagnostics"][
        "terminal_pa_count"
    ] == 4
    assert result["diagnostics"][
        "sample_count"
    ] == 3

    samples = {
        sample["comparison_id"]: sample
        for sample in result["samples"]
    }

    first = samples["700001:101:201"]
    assert first["observed_counts"][
        "single"
    ] == 1
    assert first["observed_counts"]["k"] == 1

    second = samples["700001:101:202"]
    assert second["observed_counts"]["bb"] == 1

    third = samples["700002:101:201"]
    assert third["observed_counts"]["hr"] == 1


def test_deduplicates_identical_terminal_identity():
    row = event(events="double")

    result = (
        materialize_canonical_pitcher_matchup_profile_pa_historical_outcomes(
            [row, dict(row)]
        )
    )

    assert result["diagnostics"][
        "terminal_pa_count"
    ] == 1
    assert result["diagnostics"][
        "duplicate_terminal_row_count"
    ] == 1
    assert result["samples"][0][
        "observed_counts"
    ]["double"] == 1


def test_conflicting_terminal_identity_fails_closed():
    result = (
        materialize_canonical_pitcher_matchup_profile_pa_historical_outcomes(
            [
                event(events="single"),
                event(events="double"),
            ]
        )
    )

    assert result["samples"] == []
    assert result["diagnostics"][
        "status"
    ] == "unavailable"
    assert result["diagnostics"][
        "terminal_pa_count"
    ] == 0
    assert result["diagnostics"][
        "conflicting_terminal_pa_count"
    ] == 1
    assert result["diagnostics"][
        "rejected_rows"
    ][0]["reason"] == (
        "conflicting_terminal_pa_identity"
    )


def test_ignores_nonterminal_pitch_rows():
    result = (
        materialize_canonical_pitcher_matchup_profile_pa_historical_outcomes(
            [
                event(events=None),
                event(
                    at_bat_number=2,
                    events="single",
                ),
            ]
        )
    )

    assert result["diagnostics"][
        "nonterminal_pitch_row_count"
    ] == 1
    assert result["diagnostics"][
        "terminal_pa_count"
    ] == 1


def test_rejects_unsupported_terminal_event():
    result = (
        materialize_canonical_pitcher_matchup_profile_pa_historical_outcomes(
            [
                event(events="catcher_interf"),
            ]
        )
    )

    assert result["samples"] == []
    assert result["diagnostics"][
        "status"
    ] == "unavailable"
    assert result["diagnostics"][
        "rejected_rows"
    ][0]["reason"] == (
        "unsupported_terminal_event"
    )


def test_valid_rows_survive_unsupported_rows():
    result = (
        materialize_canonical_pitcher_matchup_profile_pa_historical_outcomes(
            [
                event(events="catcher_interf"),
                event(
                    at_bat_number=2,
                    events="single",
                ),
            ]
        )
    )

    assert result["diagnostics"][
        "status"
    ] == "partial"
    assert result["diagnostics"][
        "sample_count"
    ] == 1
    assert result["diagnostics"][
        "rejected_row_count"
    ] == 1


@pytest.mark.parametrize(
    "field,value,reason",
    [
        (
            "game_pk",
            None,
            "game_pk_must_be_positive_integer",
        ),
        (
            "at_bat_number",
            0,
            "at_bat_number_must_be_positive_integer",
        ),
        (
            "pitcher_id",
            None,
            "pitcher_id_must_be_positive_integer",
        ),
        (
            "batter_id",
            False,
            "batter_id_must_be_positive_integer",
        ),
        (
            "game_date",
            "not-a-date",
            "game_date_must_be_iso_date",
        ),
    ],
)
def test_rejects_invalid_terminal_identity(
    field,
    value,
    reason,
):
    result = (
        materialize_canonical_pitcher_matchup_profile_pa_historical_outcomes(
            [
                event(**{field: value}),
            ]
        )
    )

    assert result["samples"] == []
    assert result["diagnostics"][
        "rejected_rows"
    ][0]["reason"] == reason


def test_accepts_date_objects_and_sets_season():
    result = (
        materialize_canonical_pitcher_matchup_profile_pa_historical_outcomes(
            [
                event(
                    game_date=dt.date(
                        2024,
                        8,
                        15,
                    )
                ),
            ]
        )
    )

    sample = result["samples"][0]

    assert sample["season"] == 2024
    assert sample["game_date"] == "2024-08-15"


def test_materialization_is_deterministic():
    rows = [
        event(
            at_bat_number=1,
            events="single",
        ),
        event(
            at_bat_number=2,
            events="strikeout",
        ),
        event(
            at_bat_number=3,
            batter_id=202,
            events="walk",
        ),
    ]

    first = (
        materialize_canonical_pitcher_matchup_profile_pa_historical_outcomes(
            rows
        )
    )
    second = (
        materialize_canonical_pitcher_matchup_profile_pa_historical_outcomes(
            list(reversed(rows))
        )
    )

    assert first["samples"] == second["samples"]
    assert first["diagnostics"][
        "outcome_digest"
    ] == second["diagnostics"][
        "outcome_digest"
    ]


def test_empty_input_fails_closed():
    result = (
        materialize_canonical_pitcher_matchup_profile_pa_historical_outcomes(
            []
        )
    )

    assert result["samples"] == []
    assert result["diagnostics"][
        "status"
    ] == "unavailable"
    assert result["diagnostics"][
        "raw_row_count"
    ] == 0


def test_authority_contract_remains_shadow_only():
    result = (
        materialize_canonical_pitcher_matchup_profile_pa_historical_outcomes(
            [
                event(),
            ]
        )
    )
    diagnostics = result["diagnostics"]

    assert diagnostics["shadow_only"] is True
    assert diagnostics[
        "production_authority"
    ] is False
    assert diagnostics[
        "production_authority_changed"
    ] is False
    assert diagnostics[
        "intentional_walk_policy"
    ] == "mapped_to_canonical_bb"
    assert diagnostics[
        "unsupported_event_policy"
    ] == "fail_closed"

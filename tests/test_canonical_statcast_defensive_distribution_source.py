from types import SimpleNamespace

import pytest

from mlb_app.simulation.game import (
    CanonicalDefensiveEventAuthorityRecord,
    aggregate_canonical_defensive_event_authority,
)
from mlb_app.simulation.shadow import (
    CANONICAL_STATCAST_DEFENSIVE_DISTRIBUTION_SOURCE_VERSION,
    backtest_canonical_defensive_distribution,
    source_statcast_defensive_distribution,
)


def row(
    *,
    at_bat_number,
    events,
    game_pk=1001,
    game_date="2026-08-15",
):
    return {
        "game_date": game_date,
        "game_pk": game_pk,
        "at_bat_number": at_bat_number,
        "events": events,
    }


def source(rows):
    return source_statcast_defensive_distribution(
        rows,
        window_start="2026-08-01",
        window_end="2026-08-31",
        through_date="2026-09-01",
    )


def test_sources_canonical_defensive_distribution():
    rows = [
        row(at_bat_number=1, events=None),
        row(at_bat_number=2, events="single"),
        row(at_bat_number=3, events="double"),
        row(at_bat_number=4, events="triple"),
        row(at_bat_number=5, events="field_error"),
        row(at_bat_number=6, events="field_out"),
        row(at_bat_number=7, events="force_out"),
        row(
            at_bat_number=8,
            events="fielders_choice_out",
        ),
        row(
            at_bat_number=9,
            events="grounded_into_double_play",
        ),
        row(
            at_bat_number=10,
            events="double_play",
        ),
        row(
            at_bat_number=11,
            events="fielders_choice",
        ),
        row(at_bat_number=12, events="sac_fly"),
        row(at_bat_number=13, events="home_run"),
        row(at_bat_number=14, events="strikeout"),
        row(at_bat_number=15, events="mystery_event"),
    ]

    result = source(rows)

    assert result.observed.observation_count == 11
    assert dict(
        result.observed.final_event_type_counts
    ) == {
        "double": 1,
        "ground_ball_double_play": 2,
        "ground_ball_fielders_choice": 1,
        "out": 3,
        "reached_on_error": 1,
        "sacrifice_fly": 1,
        "single": 1,
        "triple": 1,
    }
    assert result.source_row_count == 15
    assert result.terminal_row_count == 14
    assert result.nonterminal_row_count == 1
    assert dict(result.excluded_event_counts) == {
        "home_run": 1,
        "strikeout": 1,
    }
    assert dict(result.unmapped_event_counts) == {
        "mystery_event": 1,
    }
    assert len(result.digest) == 64
    assert result.digest in (
        result.observed.source_identifier
    )


def test_source_diagnostics_are_measurement_only():
    result = source(
        [
            row(
                at_bat_number=1,
                events="field_out",
            ),
        ]
    )

    diagnostics = result.to_diagnostics()

    assert diagnostics["schema_version"] == (
        CANONICAL_STATCAST_DEFENSIVE_DISTRIBUTION_SOURCE_VERSION
    )
    assert diagnostics["status"] == "ready"
    assert diagnostics["database_accessed"] is False
    assert diagnostics["network_accessed"] is False
    assert diagnostics["measurement_only"] is True
    assert diagnostics["activation_permitted"] is False
    assert (
        diagnostics["production_authority_changed"]
        is False
    )


def test_sourced_distribution_flows_directly_to_backtest():
    observed_source = source(
        [
            row(
                at_bat_number=1,
                events="single",
            ),
            row(
                at_bat_number=2,
                events="field_out",
            ),
        ]
    )
    summary = aggregate_canonical_defensive_event_authority(
        (
            CanonicalDefensiveEventAuthorityRecord(
                applied=False,
                authoritative=False,
                original_event_type="single",
                final_event_type="single",
                blocker="defensive_outcome_unchanged",
            ),
            CanonicalDefensiveEventAuthorityRecord(
                applied=False,
                authoritative=False,
                original_event_type="out",
                final_event_type="out",
                blocker="defensive_outcome_unchanged",
            ),
        )
    )

    result = backtest_canonical_defensive_distribution(
        summary=summary,
        observed=observed_source.observed,
    )

    assert result.ready is True
    assert result.source_identifier == (
        observed_source.observed.source_identifier
    )
    assert result.total_variation_distance == 0.0
    assert result.maximum_absolute_rate_delta == 0.0
    assert len(result.input_digest) == 64


def test_duplicate_terminal_rows_are_deduplicated():
    duplicate = row(
        at_bat_number=1,
        events="single",
    )

    result = source([duplicate, dict(duplicate)])

    assert result.terminal_row_count == 2
    assert result.duplicate_terminal_row_count == 1
    assert result.observed.observation_count == 1
    assert dict(
        result.observed.final_event_type_counts
    ) == {
        "single": 1,
    }


def test_conflicting_terminal_identity_fails_closed():
    with pytest.raises(
        ValueError,
        match="conflicting terminal",
    ):
        source(
            [
                row(
                    at_bat_number=1,
                    events="single",
                ),
                row(
                    at_bat_number=1,
                    events="double",
                ),
            ]
        )


def test_source_digest_is_input_order_independent():
    first_row = row(
        at_bat_number=1,
        events="single",
    )
    second_row = row(
        at_bat_number=2,
        events="field_out",
    )

    first = source([first_row, second_row])
    second = source([second_row, first_row])

    assert first.digest == second.digest
    assert (
        first.observed.source_identifier
        == second.observed.source_identifier
    )


def test_source_accepts_orm_shaped_records():
    result = source(
        [
            SimpleNamespace(
                game_date="2026-08-15",
                game_pk=1001,
                at_bat_number=1,
                events="field_error",
            ),
        ]
    )

    assert dict(
        result.observed.final_event_type_counts
    ) == {
        "reached_on_error": 1,
    }


@pytest.mark.parametrize(
    "window_end,through_date,error",
    [
        (
            "2026-07-31",
            "2026-09-01",
            "must not precede",
        ),
        (
            "2026-09-02",
            "2026-09-01",
            "must not exceed",
        ),
    ],
)
def test_source_rejects_invalid_cutoff_window(
    window_end,
    through_date,
    error,
):
    with pytest.raises(ValueError, match=error):
        source_statcast_defensive_distribution(
            [
                row(
                    at_bat_number=1,
                    events="single",
                ),
            ],
            window_start="2026-08-01",
            window_end=window_end,
            through_date=through_date,
        )


def test_source_rejects_row_outside_window():
    with pytest.raises(
        ValueError,
        match="within source window",
    ):
        source(
            [
                row(
                    at_bat_number=1,
                    events="single",
                    game_date="2026-07-31",
                ),
            ]
        )


def test_terminal_rows_require_canonical_identity():
    with pytest.raises(
        ValueError,
        match="game_pk",
    ):
        source(
            [
                {
                    "game_date": "2026-08-15",
                    "game_pk": None,
                    "at_bat_number": 1,
                    "events": "single",
                },
            ]
        )


def test_source_requires_comparable_observations():
    with pytest.raises(
        ValueError,
        match="no comparable",
    ):
        source(
            [
                row(
                    at_bat_number=1,
                    events="home_run",
                ),
                row(
                    at_bat_number=2,
                    events="strikeout",
                ),
            ]
        )

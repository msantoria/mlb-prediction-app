from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from mlb_app.simulation.shadow import (
    build_canonical_lineup_side_candidate,
    select_canonical_lineup,
)


def candidate(
    side,
    source,
    ids=None,
    suffix="v1",
):
    return build_canonical_lineup_side_candidate(
        team_side=side,
        player_ids=(
            ids
            if ids is not None
            else [
                1000
                + index
                + (100 if side == "home" else 0)
                for index in range(9)
            ]
        ),
        lineup_source=source,
        source_identifier=(
            f"{source}_{side}_{suffix}"
        ),
        source_as_of="2026-09-06T12:00:00Z",
        confidence=source,
    )


def select(**overrides):
    values = {
        "game_pk": 123,
        "confirmed_away": candidate(
            "away",
            "confirmed",
            [],
        ),
        "confirmed_home": candidate(
            "home",
            "confirmed",
            [],
        ),
        "projected_away": candidate(
            "away",
            "projected",
        ),
        "projected_home": candidate(
            "home",
            "projected",
        ),
    }
    values.update(overrides)

    return select_canonical_lineup(**values)


def test_confirmed_lineups_take_precedence():
    result = select(
        confirmed_away=candidate(
            "away",
            "confirmed",
        ),
        confirmed_home=candidate(
            "home",
            "confirmed",
        ),
    )

    assert result.ready is True
    assert (
        result.selected.lineup_source
        == "confirmed"
    )
    assert (
        result.selected.confidence
        == "confirmed"
    )


def test_projected_selected_when_confirmed_absent():
    result = select()

    assert result.ready is True
    assert (
        result.selected.lineup_source
        == "projected"
    )
    assert (
        result.selected.confidence
        == "provisional"
    )


def test_duplicate_projected_players_block():
    result = select(
        projected_away=candidate(
            "away",
            "projected",
            [999] * 9,
        )
    )

    assert result.ready is False
    assert (
        "projected_away_lineup_"
        "has_duplicate_players"
        in result.blockers
    )


def test_missing_projected_side_blocks():
    result = select(
        projected_home=candidate(
            "home",
            "projected",
            [],
        )
    )

    assert result.ready is False
    assert (
        "projected_home_lineup_"
        "requires_9_players"
        in result.blockers
    )


def test_partial_confirmed_state_fails_closed():
    result = select(
        confirmed_away=candidate(
            "away",
            "confirmed",
        )
    )

    assert result.ready is False
    assert result.blockers[0] == (
        "mixed_or_partial_confirmed_lineups"
    )


def test_selection_is_deterministic():
    first = select()
    second = select()

    assert first.selected.lineup_digest == (
        second.selected.lineup_digest
    )


def test_lineup_order_changes_digest():
    original = select()
    changed = select(
        projected_away=candidate(
            "away",
            "projected",
            list(reversed(range(1000, 1009))),
        )
    )

    assert original.selected.lineup_digest != (
        changed.selected.lineup_digest
    )


def test_confirmed_arrival_supersedes_projected():
    projected = select()
    confirmed = select(
        confirmed_away=candidate(
            "away",
            "confirmed",
        ),
        confirmed_home=candidate(
            "home",
            "confirmed",
        ),
    )

    assert projected.selected.lineup_digest != (
        confirmed.selected.lineup_digest
    )
    assert (
        confirmed.selected.lineup_source
        == "confirmed"
    )


def test_selection_does_not_mutate_input_lists():
    away_ids = list(range(1000, 1009))
    home_ids = list(range(1100, 1109))
    original_away = list(away_ids)
    original_home = list(home_ids)

    result = select(
        projected_away=candidate(
            "away",
            "projected",
            away_ids,
        ),
        projected_home=candidate(
            "home",
            "projected",
            home_ids,
        ),
    )

    assert result.ready is True
    assert away_ids == original_away
    assert home_ids == original_home


def test_contract_is_frozen():
    result = select()

    with pytest.raises(FrozenInstanceError):
        result.selected.lineup_source = (
            "confirmed"
        )


def test_diagnostics_hide_player_identifiers():
    diagnostics = select().to_diagnostics()

    assert (
        diagnostics[
            "player_identifiers_exposed"
        ]
        is False
    )
    assert (
        diagnostics["activation_permitted"]
        is False
    )
    assert "away_player_ids" not in diagnostics
    assert "home_player_ids" not in diagnostics

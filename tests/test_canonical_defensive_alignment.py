from dataclasses import replace

import pytest

from mlb_app.simulation.events import (
    BattedBallContext,
    BattedBallDepth,
    BattedBallType,
    ContactQuality,
    SprayDirection,
)
from mlb_app.simulation.game import (
    CANONICAL_DEFENSIVE_ALIGNMENT_VERSION,
    CANONICAL_DEFENSIVE_POSITION_ORDER,
    CanonicalDefensiveAlignment,
    CanonicalDefensiveFielder,
    CanonicalDefensivePosition,
    CanonicalLineup,
    resolve_canonical_defensive_fielder,
    resolve_canonical_defensive_opportunity,
)


def fielders(
    *,
    prefix="home",
    missing_position=None,
):
    return tuple(
        CanonicalDefensiveFielder(
            position=position,
            player_id=(
                None
                if position is missing_position
                else f"{prefix}_{position.value}"
            ),
        )
        for position in (
            CANONICAL_DEFENSIVE_POSITION_ORDER
        )
    )


def alignment(
    *,
    side="home",
    missing_position=None,
):
    return CanonicalDefensiveAlignment(
        team_side=side,
        fielders=fielders(
            prefix=side,
            missing_position=missing_position,
        ),
        source_identifier="test-alignment",
        source_as_of="2026-09-09T12:00:00Z",
        confidence="test",
    )


def opportunity(
    *,
    ball_type=BattedBallType.FLY_BALL,
    direction=SprayDirection.CENTER,
    depth=BattedBallDepth.DEEP,
):
    return resolve_canonical_defensive_opportunity(
        context=BattedBallContext(
            batted_ball_type=ball_type,
            direction=direction,
            depth=depth,
            contact_quality=ContactQuality.MEDIUM,
        ),
        resolution_seed=17,
    )


def test_alignment_requires_each_position_once():
    value = alignment()

    assert value.schema_version == (
        CANONICAL_DEFENSIVE_ALIGNMENT_VERSION
    )
    assert value.complete is True
    assert tuple(
        fielder.position
        for fielder in value.fielders
    ) == CANONICAL_DEFENSIVE_POSITION_ORDER


def test_alignment_rejects_duplicate_positions():
    values = list(fielders())
    values[-1] = replace(
        values[-1],
        position=values[0].position,
    )

    with pytest.raises(
        ValueError,
        match="each non-pitcher position",
    ):
        CanonicalDefensiveAlignment(
            team_side="home",
            fielders=tuple(values),
            source_identifier="test",
            source_as_of="2026-09-09",
            confidence="test",
        )


def test_alignment_rejects_duplicate_player_identity():
    values = list(fielders())
    values[-1] = replace(
        values[-1],
        player_id=values[0].player_id,
    )

    with pytest.raises(
        ValueError,
        match="identities must be unique",
    ):
        CanonicalDefensiveAlignment(
            team_side="home",
            fielders=tuple(values),
            source_identifier="test",
            source_as_of="2026-09-09",
            confidence="test",
        )


def test_center_field_opportunity_resolves_center_fielder():
    result = resolve_canonical_defensive_fielder(
        opportunity=opportunity(),
        team_side="home",
        alignment=alignment(),
        selection_seed=91,
    )

    assert result.ready is True
    assert (
        result.position
        is CanonicalDefensivePosition.CENTER_FIELD
    )
    assert result.player_id == "home_center_field"
    assert result.authoritative is False


def test_unit_with_two_fielders_is_deterministic():
    value = opportunity(
        ball_type=BattedBallType.GROUND_BALL,
        direction=SprayDirection.CENTER,
        depth=BattedBallDepth.SHALLOW,
    )

    first = resolve_canonical_defensive_fielder(
        opportunity=value,
        team_side="home",
        alignment=alignment(),
        selection_seed=222,
    )
    second = resolve_canonical_defensive_fielder(
        opportunity=value,
        team_side="home",
        alignment=alignment(),
        selection_seed=222,
    )

    assert first == second
    assert first.position in {
        CanonicalDefensivePosition.SECOND_BASE,
        CanonicalDefensivePosition.SHORTSTOP,
    }


def test_missing_alignment_preserves_position_and_blocks_identity():
    result = resolve_canonical_defensive_fielder(
        opportunity=opportunity(),
        team_side="home",
        alignment=None,
        selection_seed=91,
    )

    assert (
        result.position
        is CanonicalDefensivePosition.CENTER_FIELD
    )
    assert result.player_id is None
    assert result.blockers == (
        "defensive_alignment_unavailable",
    )
    assert result.ready is False


def test_incomplete_alignment_blocks_missing_position_identity():
    result = resolve_canonical_defensive_fielder(
        opportunity=opportunity(),
        team_side="home",
        alignment=alignment(
            missing_position=(
                CanonicalDefensivePosition.CENTER_FIELD
            ),
        ),
        selection_seed=91,
    )

    assert result.player_id is None
    assert result.blockers == (
        "defensive_fielder_identity_unavailable",
    )


def test_lineup_accepts_supported_alignment():
    value = alignment()
    player_ids = value.identified_player_ids + (
        "home_designated_hitter",
    )

    lineup = CanonicalLineup(
        team_side="home",
        player_ids=player_ids,
        defensive_alignment=value,
    )

    assert lineup.defensive_alignment == value


def test_lineup_rejects_identity_outside_batting_lineup():
    value = alignment()

    with pytest.raises(
        ValueError,
        match="must belong to canonical lineup",
    ):
        CanonicalLineup(
            team_side="home",
            player_ids=tuple(
                f"other_{index}"
                for index in range(9)
            ),
            defensive_alignment=value,
        )

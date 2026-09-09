from dataclasses import dataclass

import pytest

from mlb_app.simulation.game import (
    CANONICAL_DEFENSIVE_POSITION_ORDER,
)
from mlb_app.simulation.shadow.defensive_alignment_materialization import (
    CANONICAL_DEFENSIVE_ALIGNMENT_MATERIALIZATION_VERSION,
    CanonicalDefensiveAlignmentMaterialization,
    materialize_canonical_defensive_alignments,
)


POSITION_ROWS = (
    ("C", "2"),
    ("1B", "3"),
    ("2B", "4"),
    ("3B", "5"),
    ("SS", "6"),
    ("LF", "7"),
    ("CF", "8"),
    ("RF", "9"),
)


@dataclass(frozen=True)
class Lineups:
    away_player_ids: tuple
    home_player_ids: tuple


def player_ids(prefix):
    return tuple(
        f"{prefix}{index}"
        for index in range(1, 10)
    )


def lineups():
    return Lineups(
        away_player_ids=player_ids("a"),
        home_player_ids=player_ids("h"),
    )


def records(prefix):
    return [
        {
            "batter_id": f"{prefix}{index}",
            "position": position,
            "position_code": code,
        }
        for index, (position, code) in enumerate(
            POSITION_ROWS,
            start=1,
        )
    ] + [
        {
            "batter_id": f"{prefix}9",
            "position": "DH",
            "position_code": "10",
        },
    ]


def materialize(**overrides):
    kwargs = {
        "lineups": lineups(),
        "away_records": records("a"),
        "home_records": records("h"),
        "source_identifier": "mlb-boxscore:123",
        "source_as_of": "2026-09-09T12:00:00Z",
        "confidence": "confirmed",
    }
    kwargs.update(overrides)

    return materialize_canonical_defensive_alignments(
        **kwargs
    )


def test_complete_records_materialize_both_sides():
    result = materialize()

    assert result.schema_version == (
        CANONICAL_DEFENSIVE_ALIGNMENT_MATERIALIZATION_VERSION
    )
    assert result.status == "ready"
    assert result.ready is True
    assert result.blockers == ()
    assert result.away_alignment is not None
    assert result.home_alignment is not None
    assert result.away_alignment.complete is True
    assert result.home_alignment.complete is True
    assert tuple(
        fielder.position
        for fielder in result.away_alignment.fielders
    ) == CANONICAL_DEFENSIVE_POSITION_ORDER


def test_designated_hitter_is_not_a_defensive_position():
    result = materialize()

    assert "a9" not in (
        result.away_alignment.identified_player_ids
    )
    assert "h9" not in (
        result.home_alignment.identified_player_ids
    )


def test_position_mapping_accepts_codes():
    coded_records = [
        {
            "batter_id": row["batter_id"],
            "position_code": row["position_code"],
        }
        for row in records("a")
    ]

    result = materialize(
        away_records=coded_records,
    )

    assert result.ready is True


def test_missing_position_blocks_both_sides_atomically():
    result = materialize(
        away_records=records("a")[:-2],
    )

    assert result.ready is False
    assert result.away_alignment is None
    assert result.home_alignment is None
    assert result.blockers == (
        "away_defensive_alignment_"
        "requires_eight_positions",
    )


def test_player_outside_selected_lineup_blocks_materialization():
    invalid = records("a")
    invalid[0] = {
        **invalid[0],
        "batter_id": "not-selected",
    }

    result = materialize(
        away_records=invalid,
    )

    assert result.ready is False
    assert (
        "away_defensive_player_"
        "outside_selected_lineup"
        in result.blockers
    )


def test_duplicate_position_blocks_materialization():
    invalid = records("a")
    invalid[1] = {
        **invalid[1],
        "position": "C",
        "position_code": "2",
    }

    result = materialize(
        away_records=invalid,
    )

    assert result.ready is False
    assert (
        "away_duplicate_defensive_position"
        in result.blockers
    )


def test_missing_source_metadata_blocks_materialization():
    result = materialize(
        source_identifier="",
        source_as_of="",
        confidence="",
    )

    assert result.ready is False
    assert result.blockers == (
        "defensive_alignment_source_identifier_required",
        "defensive_alignment_source_as_of_required",
        "defensive_alignment_confidence_required",
    )


def test_diagnostics_preserve_shadow_authority():
    diagnostics = materialize().to_diagnostics()

    assert diagnostics["status"] == "ready"
    assert diagnostics["atomic"] is True
    assert diagnostics["authoritative"] is False
    assert (
        diagnostics["production_authority_changed"]
        is False
    )


def test_partial_alignment_contract_is_rejected():
    complete = materialize()

    with pytest.raises(
        ValueError,
        match="must be atomic",
    ):
        CanonicalDefensiveAlignmentMaterialization(
            away_alignment=complete.away_alignment,
        )

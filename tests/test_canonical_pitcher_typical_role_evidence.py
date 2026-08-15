from copy import deepcopy

import pytest

from mlb_app.simulation.projections.pitcher_typical_role_evidence import (
    materialize_canonical_pitcher_role_evidence,
)


def pitcher(
    pitcher_id,
    *,
    games_pitched,
    games_started,
    saves=0,
    holds=0,
    games_finished=0,
    outs=0,
):
    return {
        "mlb_player_id": pitcher_id,
        "player_type": "pitcher",
        "season_games_pitched": games_pitched,
        "season_games_started": games_started,
        "season_relief_appearances": (
            games_pitched - games_started
        ),
        "season_saves": saves,
        "season_holds": holds,
        "season_games_finished": games_finished,
        "season_pitching_outs": outs,
    }


def evidence(rows, **kwargs):
    return materialize_canonical_pitcher_role_evidence(
        active_roster_records=rows,
        **kwargs,
    )


@pytest.mark.parametrize(
    ("row", "expected_role"),
    [
        (
            pitcher(
                "starter",
                games_pitched=24,
                games_started=24,
                outs=420,
            ),
            "starter",
        ),
        (
            pitcher(
                "closer",
                games_pitched=50,
                games_started=0,
                saves=28,
                holds=2,
                games_finished=39,
                outs=150,
            ),
            "closer",
        ),
        (
            pitcher(
                "setup",
                games_pitched=55,
                games_started=0,
                saves=1,
                holds=19,
                games_finished=5,
                outs=150,
            ),
            "setup",
        ),
        (
            pitcher(
                "long",
                games_pitched=20,
                games_started=0,
                outs=120,
            ),
            "long_reliever",
        ),
        (
            pitcher(
                "middle",
                games_pitched=45,
                games_started=0,
                outs=120,
            ),
            "middle_reliever",
        ),
        (
            pitcher(
                "swing",
                games_pitched=20,
                games_started=8,
                outs=210,
            ),
            "swingman",
        ),
    ],
)
def test_materializes_season_usage_roles(
    row,
    expected_role,
):
    result = evidence([row])

    assert result["records"][0][
        "typical_role"
    ] == expected_role
    assert result["records"][0][
        "typical_role_inference_used"
    ] is True


def test_repeated_short_starts_materialize_opener():
    rows = [
        pitcher(
            "100",
            games_pitched=12,
            games_started=8,
            outs=90,
        ),
    ]

    result = evidence(
        rows,
        historical_appearance_evidence_by_pitcher_id={
            "100": {
                "start_count": 8,
                "short_start_count": 6,
                "relief_appearance_count": 4,
                "relief_outs": 24,
            },
        },
    )

    row = result["records"][0]

    assert row["typical_role"] == "opener"
    assert row[
        "typical_role_source"
    ] == (
        "mlb_stats_historical_"
        "appearance_sequence"
    )


def test_repeated_early_length_materializes_bulk_follower():
    rows = [
        pitcher(
            "101",
            games_pitched=18,
            games_started=0,
            outs=180,
        ),
    ]

    result = evidence(
        rows,
        historical_appearance_evidence_by_pitcher_id={
            "101": {
                "relief_appearance_count": 18,
                "early_multi_inning_relief_count": 7,
                "relief_outs": 180,
            },
        },
    )

    row = result["records"][0]

    assert row[
        "typical_role"
    ] == "bulk_follower"
    assert row[
        "historical_bulk_follower_count"
    ] == 7


def test_confirmed_plan_is_separate_from_typical_role():
    rows = [
        pitcher(
            "101",
            games_pitched=30,
            games_started=0,
            holds=12,
            outs=90,
        ),
    ]

    result = evidence(
        rows,
        planned_role_evidence_by_pitcher_id={
            "101": {
                "role": "opener",
                "source": "official_team_game_notes",
                "evidence_status": "confirmed",
            },
        },
    )
    row = result["records"][0]

    assert row["typical_role"] == "setup"
    assert row["planned_game_role"] == "opener"
    assert (
        row["planned_game_role_status"]
        == "confirmed"
    )
    assert row[
        "planned_role_inferred_from_history"
    ] is False


def test_unconfirmed_plan_is_not_promoted():
    result = evidence(
        [
            pitcher(
                "101",
                games_pitched=30,
                games_started=0,
                outs=90,
            ),
        ],
        planned_role_evidence_by_pitcher_id={
            "101": {
                "role": "bulk_follower",
                "source": "historical_guess",
                "evidence_status": "inferred",
            },
        },
    )
    row = result["records"][0]

    assert row["planned_game_role"] is None
    assert (
        row["planned_game_role_status"]
        == "invalid_or_unconfirmed"
    )


def test_incomplete_usage_remains_unknown():
    result = evidence([
        {
            "mlb_player_id": "101",
            "player_type": "pitcher",
        },
    ])

    assert result["records"][0][
        "typical_role"
    ] == "unknown"
    assert result[
        "unresolved_pitcher_ids"
    ] == ["101"]


def test_materialization_is_read_only():
    rows = [
        pitcher(
            "101",
            games_pitched=40,
            games_started=0,
            holds=10,
            outs=120,
        ),
    ]
    original = deepcopy(rows)

    result = evidence(rows)

    assert rows == original
    assert result[
        "database_writes_performed"
    ] is False
    assert result[
        "production_authority_changed"
    ] is False


@pytest.mark.parametrize(
    "invalid",
    [None, "records", {}, object()],
)
def test_rejects_invalid_roster_sequence(invalid):
    with pytest.raises(TypeError):
        evidence(invalid)

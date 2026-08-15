from copy import deepcopy

import pytest

from mlb_app.simulation.projections.pitcher_appearance_history import (
    materialize_canonical_pitcher_appearance_history,
)


def feed(
    game_pk,
    *,
    team_id=113,
    opponent_id=146,
    pitchers,
    state="Final",
):
    player_rows = {}

    for pitcher in pitchers:
        pitcher_id = str(pitcher["pitcher_id"])
        pitching = {
            "gamesStarted": (
                1 if pitcher["started"] else 0
            ),
            "outs": pitcher["outs"],
        }
        player_rows[f"ID{pitcher_id}"] = {
            "person": {
                "id": int(pitcher_id),
                "fullName": pitcher.get(
                    "name",
                    pitcher_id,
                ),
            },
            "stats": {
                "pitching": pitching,
            },
        }

    return {
        "gameData": {
            "gamePk": game_pk,
            "status": {
                "abstractGameState": state,
            },
            "teams": {
                "away": {
                    "id": team_id,
                },
                "home": {
                    "id": opponent_id,
                },
            },
        },
        "liveData": {
            "boxscore": {
                "teams": {
                    "away": {
                        "pitchers": [
                            int(row["pitcher_id"])
                            for row in pitchers
                        ],
                        "players": player_rows,
                    },
                    "home": {
                        "pitchers": [],
                        "players": {},
                    },
                },
            },
        },
    }


def run(feeds, **kwargs):
    return (
        materialize_canonical_pitcher_appearance_history(
            team_id=113,
            game_feeds=feeds,
            **kwargs,
        )
    )


def test_materializes_ordered_appearances():
    result = run([
        feed(
            1,
            pitchers=[
                {
                    "pitcher_id": "100",
                    "started": True,
                    "outs": 18,
                },
                {
                    "pitcher_id": "101",
                    "started": False,
                    "outs": 3,
                },
            ],
        ),
    ])

    assert result["processed_game_count"] == 1
    assert result[
        "evidence_by_pitcher_id"
    ]["100"]["start_count"] == 1
    assert result[
        "evidence_by_pitcher_id"
    ]["101"]["relief_appearance_count"] == 1


def test_detects_opener_and_bulk_follower_pair():
    result = run([
        feed(
            1,
            pitchers=[
                {
                    "pitcher_id": "100",
                    "started": True,
                    "outs": 3,
                },
                {
                    "pitcher_id": "101",
                    "started": False,
                    "outs": 15,
                },
                {
                    "pitcher_id": "102",
                    "started": False,
                    "outs": 9,
                },
            ],
        ),
    ])

    assert result[
        "detected_opener_bulk_pair_count"
    ] == 1
    pair = result[
        "detected_opener_bulk_pairs"
    ][0]

    assert pair["opener_id"] == "100"
    assert pair["bulk_follower_id"] == "101"
    assert result[
        "evidence_by_pitcher_id"
    ]["100"]["short_start_count"] == 1
    assert result[
        "evidence_by_pitcher_id"
    ]["101"]["bulk_follower_count"] == 1


def test_does_not_call_ordinary_short_relief_bulk():
    result = run([
        feed(
            1,
            pitchers=[
                {
                    "pitcher_id": "100",
                    "started": True,
                    "outs": 3,
                },
                {
                    "pitcher_id": "101",
                    "started": False,
                    "outs": 6,
                },
            ],
        ),
    ])

    assert result[
        "detected_opener_bulk_pair_count"
    ] == 0


def test_does_not_call_long_follower_bulk_after_normal_start():
    result = run([
        feed(
            1,
            pitchers=[
                {
                    "pitcher_id": "100",
                    "started": True,
                    "outs": 15,
                },
                {
                    "pitcher_id": "101",
                    "started": False,
                    "outs": 12,
                },
            ],
        ),
    ])

    assert result[
        "detected_opener_bulk_pair_count"
    ] == 0


def test_repeated_games_accumulate_history():
    result = run([
        feed(
            game_pk,
            pitchers=[
                {
                    "pitcher_id": "100",
                    "started": True,
                    "outs": 3,
                },
                {
                    "pitcher_id": "101",
                    "started": False,
                    "outs": 12,
                },
            ],
        )
        for game_pk in (1, 2, 3)
    ])

    opener = result[
        "evidence_by_pitcher_id"
    ]["100"]
    bulk = result[
        "evidence_by_pitcher_id"
    ]["101"]

    assert opener["start_count"] == 3
    assert opener["short_start_count"] == 3
    assert bulk[
        "early_multi_inning_relief_count"
    ] == 3
    assert bulk["relief_outs"] == 36


def test_nonfinal_game_is_skipped():
    result = run([
        feed(
            1,
            state="Live",
            pitchers=[
                {
                    "pitcher_id": "100",
                    "started": True,
                    "outs": 3,
                },
            ],
        ),
    ])

    assert result["status"] == "unavailable"
    assert result["processed_game_count"] == 0
    assert result["skipped_game_count"] == 1


def test_missing_team_is_skipped():
    result = (
        materialize_canonical_pitcher_appearance_history(
            team_id=999,
            game_feeds=[
                feed(
                    1,
                    pitchers=[
                        {
                            "pitcher_id": "100",
                            "started": True,
                            "outs": 3,
                        },
                    ],
                ),
            ],
        )
    )

    assert result["status"] == "unavailable"


def test_falls_back_to_innings_pitched():
    source = feed(
        1,
        pitchers=[
            {
                "pitcher_id": "100",
                "started": True,
                "outs": 3,
            },
        ],
    )
    pitching = source["liveData"]["boxscore"][
        "teams"
    ]["away"]["players"]["ID100"]["stats"][
        "pitching"
    ]
    pitching.pop("outs")
    pitching["inningsPitched"] = "1.2"

    result = run([source])

    assert result[
        "evidence_by_pitcher_id"
    ]["100"]["short_start_count"] == 1


def test_materialization_is_read_only():
    feeds = [
        feed(
            1,
            pitchers=[
                {
                    "pitcher_id": "100",
                    "started": True,
                    "outs": 3,
                },
                {
                    "pitcher_id": "101",
                    "started": False,
                    "outs": 12,
                },
            ],
        ),
    ]
    original = deepcopy(feeds)

    result = run(feeds)

    assert feeds == original
    assert result[
        "database_writes_performed"
    ] is False
    assert result[
        "production_authority_changed"
    ] is False
    assert result["interpretation"][
        "planned_role_claimed"
    ] is False


@pytest.mark.parametrize(
    "invalid",
    [None, "feeds", {}, object()],
)
def test_rejects_invalid_feed_sequence(invalid):
    with pytest.raises(TypeError):
        run(invalid)


@pytest.mark.parametrize(
    ("kwargs", "error"),
    [
        (
            {"team_id": None, "game_feeds": []},
            ValueError,
        ),
        (
            {
                "team_id": 113,
                "game_feeds": [],
                "short_start_maximum_outs": True,
            },
            ValueError,
        ),
        (
            {
                "team_id": 113,
                "game_feeds": [],
                "bulk_follower_minimum_outs": -1,
            },
            ValueError,
        ),
    ],
)
def test_rejects_invalid_contract(kwargs, error):
    with pytest.raises(error):
        materialize_canonical_pitcher_appearance_history(
            **kwargs,
        )

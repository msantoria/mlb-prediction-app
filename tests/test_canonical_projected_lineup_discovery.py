from __future__ import annotations

from copy import deepcopy

from mlb_app.simulation.shadow import (
    PROJECTED_LINEUP_SOURCE,
    discover_canonical_projected_lineup,
)


def players(start):
    return [
        {
            "id": start + index,
            "fullName": f"Player {start + index}",
        }
        for index in range(9)
    ]


def game(
    *,
    game_pk,
    game_date,
    team_id=10,
    side="away",
    state="F",
    lineup=None,
):
    other_side = (
        "home" if side == "away" else "away"
    )
    lineup_key = (
        "awayPlayers"
        if side == "away"
        else "homePlayers"
    )

    return {
        "gamePk": game_pk,
        "gameDate": game_date,
        "status": {
            "codedGameState": state,
        },
        "teams": {
            side: {
                "team": {"id": team_id},
            },
            other_side: {
                "team": {"id": 99},
            },
        },
        "lineups": {
            lineup_key: (
                players(1000)
                if lineup is None
                else lineup
            ),
        },
    }


def payload(*games):
    return {
        "dates": [
            {
                "date": "2026-09-01",
                "games": list(games),
            }
        ]
    }


def discover(
    schedule_payload,
    *,
    side="away",
    team_id=10,
    target_date="2026-09-06",
    calls=None,
):
    def fetcher(**kwargs):
        if calls is not None:
            calls.append(kwargs)

        return schedule_payload

    return discover_canonical_projected_lineup(
        team_side=side,
        team_id=team_id,
        target_game_date=target_date,
        schedule_fetcher=fetcher,
    )


def test_latest_completed_game_is_selected():
    older = game(
        game_pk=100,
        game_date="2026-09-01T18:00:00Z",
        lineup=players(1000),
    )
    newer = game(
        game_pk=200,
        game_date="2026-09-03T18:00:00Z",
        lineup=players(2000),
    )

    result = discover(payload(older, newer))

    assert result.status == "ready"
    assert result.ready is True
    assert result.source_game_pk == "200"
    assert result.player_ids == tuple(
        str(value)
        for value in range(2000, 2009)
    )


def test_team_side_in_game_is_resolved():
    result = discover(
        payload(
            game(
                game_pk=300,
                game_date="2026-09-03",
                side="home",
            )
        ),
        side="away",
    )

    assert result.ready is True
    assert result.source_game_pk == "300"


def test_nonfinal_game_is_not_selected():
    result = discover(
        payload(
            game(
                game_pk=400,
                game_date="2026-09-05",
                state="S",
            )
        )
    )

    assert result.status == "unavailable"
    assert result.player_ids == ()


def test_missing_lineup_is_unavailable():
    source_game = game(
        game_pk=500,
        game_date="2026-09-04",
    )
    source_game["lineups"] = {}

    result = discover(payload(source_game))

    assert result.status == "unavailable"
    assert result.ready is False


def test_duplicate_ids_remain_visible_to_contract():
    duplicate_players = [
        {"id": 999}
        for _ in range(9)
    ]

    result = discover(
        payload(
            game(
                game_pk=600,
                game_date="2026-09-04",
                lineup=duplicate_players,
            )
        )
    )

    assert result.status == "blocked"
    assert result.ready is False
    assert (
        "projected_away_lineup_"
        "has_duplicate_players"
        in result.to_candidate().blockers
    )


def test_invalid_payload_blocks():
    result = discover(None)

    assert result.status == "blocked"
    assert result.error_type == "invalid_payload"


def test_fetch_failure_returns_error():
    def failing_fetcher(**kwargs):
        raise RuntimeError("schedule unavailable")

    result = discover_canonical_projected_lineup(
        team_side="home",
        team_id=10,
        target_game_date="2026-09-06",
        schedule_fetcher=failing_fetcher,
    )

    assert result.status == "error"
    assert result.error_type == "RuntimeError"
    assert result.error_message == (
        "schedule unavailable"
    )


def test_missing_team_and_date_fail_closed():
    missing_team = (
        discover_canonical_projected_lineup(
            team_side="away",
            team_id=None,
            target_game_date="2026-09-06",
            schedule_fetcher=lambda **kwargs: {},
        )
    )
    invalid_date = (
        discover_canonical_projected_lineup(
            team_side="away",
            team_id=10,
            target_game_date="not-a-date",
            schedule_fetcher=lambda **kwargs: {},
        )
    )

    assert (
        missing_team.error_type
        == "missing_team_id"
    )
    assert (
        invalid_date.error_type
        == "invalid_target_game_date"
    )


def test_fetch_window_is_deterministic():
    calls = []

    discover(
        payload(),
        target_date="2026-09-06T18:35:00Z",
        calls=calls,
    )

    assert calls == [
        {
            "team_id": 10,
            "start_date": "2026-08-30",
            "end_date": "2026-09-06",
        }
    ]


def test_input_payload_is_not_mutated():
    source = payload(
        game(
            game_pk=700,
            game_date="2026-09-04",
        )
    )
    original = deepcopy(source)

    discover(source)

    assert source == original


def test_candidate_preserves_provenance():
    result = discover(
        payload(
            game(
                game_pk=800,
                game_date="2026-09-04T19:00:00Z",
            )
        )
    )
    candidate = result.to_candidate()

    assert candidate.lineup_source == "projected"
    assert candidate.source_identifier == (
        f"{PROJECTED_LINEUP_SOURCE}:800"
    )
    assert candidate.source_as_of == (
        "2026-09-04T19:00:00Z"
    )
    assert candidate.confidence == (
        "provisional_previous_lineup"
    )


def test_diagnostics_hide_player_ids():
    result = discover(
        payload(
            game(
                game_pk=900,
                game_date="2026-09-04",
            )
        )
    )
    diagnostics = result.to_diagnostics()

    assert diagnostics["ready"] is True
    assert diagnostics[
        "roster_fallback_used"
    ] is False
    assert diagnostics[
        "player_identifiers_exposed"
    ] is False
    assert diagnostics[
        "activation_permitted"
    ] is False
    assert "player_ids" not in diagnostics

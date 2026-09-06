from mlb_app.simulation.shadow import (
    CanonicalShadowLineupDiscovery,
    discover_canonical_production_lineup,
)


def _players(start):
    return tuple(
        str(start + offset)
        for offset in range(9)
    )


def _schedule(team_id, start):
    side = "away" if team_id == 10 else "home"
    key = (
        "awayPlayers"
        if side == "away"
        else "homePlayers"
    )

    return {
        "dates": [
            {
                "date": "2026-09-05",
                "games": [
                    {
                        "gamePk": 700000 + team_id,
                        "gameDate": (
                            "2026-09-05T23:00:00Z"
                        ),
                        "status": {
                            "codedGameState": "F"
                        },
                        "teams": {
                            side: {
                                "team": {"id": team_id}
                            }
                        },
                        "lineups": {
                            key: [
                                {
                                    "person": {
                                        "id": start + offset
                                    }
                                }
                                for offset in range(9)
                            ]
                        },
                    }
                ],
            }
        ]
    }


def test_complete_confirmed_lineups_skip_projection():
    calls = []

    def schedule_fetcher(**kwargs):
        calls.append(kwargs)
        raise AssertionError(
            "projected source must not be queried"
        )

    result = discover_canonical_production_lineup(
        game_pk=822848,
        away_team_id=10,
        home_team_id=20,
        target_game_date="2026-09-06",
        confirmed_discovery=(
            CanonicalShadowLineupDiscovery(
                away_player_ids=_players(100),
                home_player_ids=_players(200),
                away_source_count=9,
                home_source_count=9,
                status="ready",
            )
        ),
        schedule_fetcher=schedule_fetcher,
    )

    assert calls == []
    assert result.selection.ready is True
    assert result.selection.selected is not None
    assert (
        result.selection.selected.lineup_source
        == "confirmed"
    )
    assert result.lineups.away_player_ids == (
        _players(100)
    )


def test_absent_confirmed_lineups_select_projection():
    calls = []

    def schedule_fetcher(**kwargs):
        calls.append(kwargs)
        team_id = kwargs["team_id"]
        return _schedule(
            team_id,
            300 if team_id == 10 else 400,
        )

    result = discover_canonical_production_lineup(
        game_pk=822848,
        away_team_id=10,
        home_team_id=20,
        target_game_date="2026-09-06",
        confirmed_discovery=(
            CanonicalShadowLineupDiscovery(
                status="unavailable"
            )
        ),
        schedule_fetcher=schedule_fetcher,
    )

    assert [call["team_id"] for call in calls] == [
        10,
        20,
    ]
    assert result.selection.ready is True
    assert result.selection.selected is not None
    assert (
        result.selection.selected.lineup_source
        == "projected"
    )
    assert result.lineups.away_player_ids == (
        _players(300)
    )
    assert result.lineups.home_player_ids == (
        _players(400)
    )


def test_partial_confirmed_lineup_fails_closed():
    calls = []

    def schedule_fetcher(**kwargs):
        calls.append(kwargs)
        raise AssertionError(
            "projection must not fill partial confirmed data"
        )

    confirmed = CanonicalShadowLineupDiscovery(
        away_player_ids=_players(100),
        away_source_count=9,
        status="partial",
    )

    result = discover_canonical_production_lineup(
        game_pk=822848,
        away_team_id=10,
        home_team_id=20,
        target_game_date="2026-09-06",
        confirmed_discovery=confirmed,
        schedule_fetcher=schedule_fetcher,
    )

    assert calls == []
    assert result.selection.ready is False
    assert result.lineups is confirmed
    assert (
        "mixed_or_partial_confirmed_lineups"
        in result.selection.blockers
    )


def test_diagnostics_do_not_expose_player_ids():
    result = discover_canonical_production_lineup(
        game_pk=822848,
        away_team_id=10,
        home_team_id=20,
        target_game_date="2026-09-06",
        confirmed_discovery=(
            CanonicalShadowLineupDiscovery(
                status="unavailable"
            )
        ),
        schedule_fetcher=lambda **kwargs: _schedule(
            kwargs["team_id"],
            300
            if kwargs["team_id"] == 10
            else 400,
        ),
    )

    diagnostics = result.to_diagnostics()
    rendered = str(diagnostics)

    assert diagnostics["selected_source"] == (
        "projected"
    )
    assert diagnostics[
        "production_authority_changed"
    ] is False
    assert "300" not in rendered
    assert "400" not in rendered


def test_projected_selection_matches_execution_interface():
    result = discover_canonical_production_lineup(
        game_pk=822848,
        away_team_id=10,
        home_team_id=20,
        target_game_date="2026-09-06",
        confirmed_discovery=(
            CanonicalShadowLineupDiscovery(
                status="unavailable"
            )
        ),
        schedule_fetcher=lambda **kwargs: _schedule(
            kwargs["team_id"],
            300
            if kwargs["team_id"] == 10
            else 400,
        ),
    )

    lineups = result.lineups
    readiness = lineups.readiness_matchup_fields()

    assert lineups.ready is True
    assert readiness["away_lineup"] == [
        {"player_id": player_id}
        for player_id in _players(300)
    ]
    assert readiness["home_lineup"] == [
        {"player_id": player_id}
        for player_id in _players(400)
    ]
    assert readiness["lineup_source"] == "projected"

    diagnostics = lineups.to_diagnostics()

    assert diagnostics["ready"] is True
    assert diagnostics["lineup_source"] == "projected"
    assert diagnostics[
        "player_identifiers_exposed"
    ] is False
    assert diagnostics[
        "production_authority_changed"
    ] is False
    assert "300" not in str(diagnostics)
    assert "400" not in str(diagnostics)

from mlb_app.simulation.shadow import (
    CanonicalProjectedLineupDiscovery,
    CanonicalShadowLineupDiscovery,
    discover_canonical_production_defensive_alignments,
    discover_canonical_production_lineup,
)


POSITIONS = (
    ("C", "2"),
    ("1B", "3"),
    ("2B", "4"),
    ("3B", "5"),
    ("SS", "6"),
    ("LF", "7"),
    ("CF", "8"),
    ("RF", "9"),
)


def players(start):
    return tuple(
        str(start + index)
        for index in range(9)
    )


def records(player_ids):
    return [
        {
            "batter_id": player_id,
            "position": position,
            "position_code": code,
        }
        for player_id, (position, code) in zip(
            player_ids[:8],
            POSITIONS,
        )
    ] + [
        {
            "batter_id": player_ids[8],
            "position": "DH",
            "position_code": "10",
        },
    ]


def confirmed_selection():
    return discover_canonical_production_lineup(
        game_pk=123,
        away_team_id=10,
        home_team_id=20,
        target_game_date="2026-09-09",
        confirmed_discovery=(
            CanonicalShadowLineupDiscovery(
                away_player_ids=players(100),
                home_player_ids=players(200),
                away_source_count=9,
                home_source_count=9,
                status="ready",
            )
        ),
        schedule_fetcher=lambda **kwargs: (
            (_ for _ in ()).throw(
                AssertionError(
                    "schedule source must not be called"
                )
            )
        ),
    )


def projected_selection():
    confirmed = CanonicalShadowLineupDiscovery(
        status="unavailable",
    )

    def schedule_fetcher(**kwargs):
        team_id = kwargs["team_id"]
        source_game_pk = (
            901 if team_id == 10 else 902
        )
        selected_players = (
            players(300)
            if team_id == 10
            else players(400)
        )

        return {
            "dates": [
                {
                    "date": "2026-09-08",
                    "games": [
                        {
                            "gamePk": source_game_pk,
                            "gameDate": (
                                "2026-09-08T19:00:00Z"
                            ),
                            "status": {
                                "codedGameState": "F",
                            },
                            "teams": {
                                "away": {
                                    "team": {
                                        "id": team_id,
                                    },
                                },
                                "home": {
                                    "team": {
                                        "id": 999,
                                    },
                                },
                            },
                            "lineups": {
                                "awayPlayers": [
                                    {
                                        "id": player_id,
                                    }
                                    for player_id in (
                                        selected_players
                                    )
                                ],
                                "homePlayers": [],
                            },
                        },
                    ],
                },
            ],
        }

    return discover_canonical_production_lineup(
        game_pk=123,
        away_team_id=10,
        home_team_id=20,
        target_game_date="2026-09-09",
        confirmed_discovery=confirmed,
        schedule_fetcher=schedule_fetcher,
    )


def test_confirmed_alignment_uses_current_game_sides():
    calls = []
    selection = confirmed_selection()

    def fetcher(game_pk):
        calls.append(game_pk)
        return {
            "away": records(
                selection.selection.selected
                .away_player_ids
            ),
            "home": records(
                selection.selection.selected
                .home_player_ids
            ),
        }

    result = (
        discover_canonical_production_defensive_alignments(
            game_pk=123,
            lineup_selection=selection,
            lineup_fetcher=fetcher,
        )
    )

    assert calls == [123]
    assert result.ready is True
    assert result.lineup_source == "confirmed"
    assert result.away_source_game_pk == "123"
    assert result.home_source_game_pk == "123"
    assert result.away_source_side == "away"
    assert result.home_source_side == "home"


def test_projected_alignment_uses_prior_source_games():
    calls = []
    selection = projected_selection()

    def fetcher(game_pk):
        calls.append(game_pk)

        if game_pk == 901:
            return {
                "away": [],
                "home": records(players(300)),
            }

        return {
            "away": records(players(400)),
            "home": [],
        }

    result = (
        discover_canonical_production_defensive_alignments(
            game_pk=123,
            lineup_selection=selection,
            lineup_fetcher=fetcher,
        )
    )

    assert calls == [901, 902]
    assert result.ready is True
    assert result.lineup_source == "projected"
    assert result.away_source_game_pk == "901"
    assert result.home_source_game_pk == "902"
    assert result.away_source_side == "home"
    assert result.home_source_side == "away"


def test_same_projected_source_game_is_fetched_once():
    selection = projected_selection()
    selection = type(selection)(
        confirmed=selection.confirmed,
        projected_away=(
            CanonicalProjectedLineupDiscovery(
                team_side="away",
                team_id="10",
                target_game_date="2026-09-09",
                player_ids=players(300),
                source_game_pk="901",
                source_game_date="2026-09-08",
                source_record_count=9,
                status="ready",
            )
        ),
        projected_home=(
            CanonicalProjectedLineupDiscovery(
                team_side="home",
                team_id="20",
                target_game_date="2026-09-09",
                player_ids=players(400),
                source_game_pk="901",
                source_game_date="2026-09-08",
                source_record_count=9,
                status="ready",
            )
        ),
        selection=selection.selection,
    )
    calls = []

    def fetcher(game_pk):
        calls.append(game_pk)
        return {
            "away": records(players(300)),
            "home": records(players(400)),
        }

    result = (
        discover_canonical_production_defensive_alignments(
            game_pk=123,
            lineup_selection=selection,
            lineup_fetcher=fetcher,
        )
    )

    assert calls == [901]
    assert result.ready is True


def test_projected_side_match_fails_closed():
    selection = projected_selection()

    result = (
        discover_canonical_production_defensive_alignments(
            game_pk=123,
            lineup_selection=selection,
            lineup_fetcher=lambda game_pk: {
                "away": records(players(700)),
                "home": records(players(800)),
            },
        )
    )

    assert result.ready is False
    assert result.status == "blocked"
    assert result.materialization.blockers == (
        "projected_defensive_alignment_"
        "lineup_side_not_matched",
    )


def test_fetch_error_is_diagnostic_and_blocked():
    result = (
        discover_canonical_production_defensive_alignments(
            game_pk=123,
            lineup_selection=confirmed_selection(),
            lineup_fetcher=lambda game_pk: (
                (_ for _ in ()).throw(
                    RuntimeError("source offline")
                )
            ),
        )
    )

    assert result.ready is False
    assert result.status == "error"
    assert result.error_type == "RuntimeError"
    assert result.materialization.blockers == (
        "defensive_alignment_source_fetch_error",
    )


def test_unavailable_selection_does_not_fetch():
    calls = []
    selection = discover_canonical_production_lineup(
        game_pk=123,
        away_team_id=10,
        home_team_id=20,
        target_game_date="2026-09-09",
        confirmed_discovery=(
            CanonicalShadowLineupDiscovery(
                away_player_ids=("100",),
                status="partial",
            )
        ),
        schedule_fetcher=lambda **kwargs: {},
    )

    result = (
        discover_canonical_production_defensive_alignments(
            game_pk=123,
            lineup_selection=selection,
            lineup_fetcher=lambda game_pk: (
                calls.append(game_pk)
            ),
        )
    )

    assert calls == []
    assert result.ready is False
    assert result.materialization.blockers == (
        "selected_lineup_unavailable_for_"
        "defensive_alignment",
    )


def test_diagnostics_hide_player_identifiers():
    result = (
        discover_canonical_production_defensive_alignments(
            game_pk=123,
            lineup_selection=confirmed_selection(),
            lineup_fetcher=lambda game_pk: {
                "away": records(players(100)),
                "home": records(players(200)),
            },
        )
    )

    diagnostics = result.to_diagnostics()

    assert diagnostics[
        "player_identifiers_exposed"
    ] is False
    assert diagnostics["authoritative"] is False
    assert (
        diagnostics["production_authority_changed"]
        is False
    )

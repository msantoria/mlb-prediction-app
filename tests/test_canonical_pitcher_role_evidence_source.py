from copy import deepcopy

import pytest

from mlb_app.simulation.shadow.pitcher_role_evidence_source import (
    CanonicalPitcherRoleEvidenceSourceResult,
    fetch_canonical_pitcher_role_evidence_source,
)


AS_OF = "2026-08-15T18:00:00+00:00"


class Response:
    def __init__(
        self,
        payload,
        *,
        error=None,
    ):
        self.payload = payload
        self.error = error

    def raise_for_status(self):
        if self.error is not None:
            raise self.error

    def json(self):
        return deepcopy(self.payload)


def schedule():
    return {
        "dates": [
            {
                "date": "2026-08-10",
                "games": [
                    {
                        "gamePk": 9,
                        "officialDate":
                            "2026-08-10",
                        "status": {
                            "detailedState": "Final",
                        },
                    },
                    {
                        "gamePk": 10,
                        "officialDate":
                            "2026-08-10",
                        "status": {
                            "detailedState": "Final",
                        },
                    },
                ],
            },
            {
                "date": "2026-08-11",
                "games": [
                    {
                        "gamePk": 11,
                        "officialDate":
                            "2026-08-11",
                        "status": {
                            "abstractGameState":
                                "Final",
                        },
                    },
                ],
            },
            {
                "date": "2026-08-15",
                "games": [
                    {
                        "gamePk": 12,
                        "officialDate":
                            "2026-08-15",
                        "status": {
                            "detailedState":
                                "Scheduled",
                        },
                    },
                ],
            },
        ],
    }


def feed(
    game_pk,
    *,
    opener_outs=6,
    bulk_outs=12,
):
    return {
        "gamePk": game_pk,
        "gameData": {
            "status": {
                "detailedState": "Final",
            },
            "teams": {
                "away": {"id": 10},
                "home": {"id": 20},
            },
        },
        "liveData": {
            "boxscore": {
                "teams": {
                    "away": {
                        "pitchers": [
                            100,
                            101,
                            102,
                        ],
                        "players": {
                            "ID100": {
                                "person": {"id": 100},
                                "stats": {
                                    "pitching": {
                                        "gamesStarted": 1,
                                        "outs": opener_outs,
                                    },
                                },
                            },
                            "ID101": {
                                "person": {"id": 101},
                                "stats": {
                                    "pitching": {
                                        "gamesStarted": 0,
                                        "outs": bulk_outs,
                                    },
                                },
                            },
                            "ID102": {
                                "person": {"id": 102},
                                "stats": {
                                    "pitching": {
                                        "gamesStarted": 0,
                                        "outs": 3,
                                    },
                                },
                            },
                        },
                    },
                    "home": {
                        "pitchers": [],
                        "players": {},
                    },
                },
            },
        },
    }


def roster():
    return [
        {
            "mlb_player_id": 100,
            "season_games_pitched": 2,
            "season_games_started": 2,
            "season_relief_appearances": 0,
            "season_pitching_outs": 12,
            "season_games_finished": 0,
            "season_saves": 0,
            "season_holds": 0,
        },
        {
            "mlb_player_id": 101,
            "season_games_pitched": 20,
            "season_games_started": 0,
            "season_relief_appearances": 20,
            "season_pitching_outs": 120,
            "season_games_finished": 2,
            "season_saves": 0,
            "season_holds": 0,
        },
        {
            "mlb_player_id": 102,
            "season_games_pitched": 30,
            "season_games_started": 0,
            "season_relief_appearances": 30,
            "season_pitching_outs": 90,
            "season_games_finished": 20,
            "season_saves": 12,
            "season_holds": 2,
        },
    ]


def request_get_factory(
    *,
    failed_game_pk=None,
):
    calls = []

    def request_get(
        url,
        *,
        params=None,
        timeout=None,
    ):
        calls.append({
            "url": url,
            "params": deepcopy(params),
            "timeout": timeout,
        })

        if url.endswith("/schedule"):
            return Response(schedule())

        game_pk = int(
            url.split("/game/", 1)[1].split("/", 1)[0]
        )

        if game_pk == failed_game_pk:
            return Response(
                {},
                error=RuntimeError(
                    "feed unavailable"
                ),
            )

        return Response(feed(game_pk))

    return request_get, calls


def run(
    *,
    request_get=None,
    cache=None,
    maximum_final_games=15,
):
    if request_get is None:
        request_get, _ = request_get_factory()

    return fetch_canonical_pitcher_role_evidence_source(
        team_id=10,
        season=2026,
        as_of=AS_OF,
        active_roster_records=roster(),
        request_get=request_get,
        maximum_final_games=maximum_final_games,
        cache=cache,
    )


def test_fetches_schedule_and_bounded_final_feeds():
    request_get, calls = request_get_factory()

    result = run(
        request_get=request_get,
        maximum_final_games=1,
    )

    assert result.status == "materialized"
    assert len(calls) == 2
    assert calls[0]["url"].endswith(
        "/api/v1/schedule"
    )
    assert calls[1]["url"].endswith(
        "/api/v1.1/game/11/feed/live"
    )
    assert result.to_diagnostics()[
        "scheduled_final_game_count"
    ] == 1
    assert result.to_diagnostics()[
        "fetched_final_game_count"
    ] == 1


def test_materializes_history_and_typical_roles():
    result = run()
    history = result.appearance_history
    evidence = result.role_evidence[
        "evidence_by_pitcher_id"
    ]

    assert history[
        "detected_opener_bulk_pair_count"
    ] == 3
    assert history[
        "evidence_by_pitcher_id"
    ]["100"]["short_start_count"] == 3
    assert history[
        "evidence_by_pitcher_id"
    ]["101"][
        "early_multi_inning_relief_count"
    ] == 3

    assert evidence["100"][
        "typical_role"
    ] == "opener"
    assert evidence["101"][
        "typical_role"
    ] == "bulk_follower"
    assert evidence["102"][
        "typical_role"
    ] == "closer"


def test_history_never_claims_today_assignment():
    result = run()
    diagnostics = result.to_diagnostics()

    assert diagnostics[
        "planned_role_claimed"
    ] is False
    assert diagnostics[
        "future_assignment_inferred"
    ] is False

    for record in result.role_evidence["records"]:
        assert record.get("planned_role") is None


def test_partial_feed_failure_fails_soft():
    request_get, _ = request_get_factory(
        failed_game_pk=11,
    )

    result = run(request_get=request_get)

    assert result.status == "partial"
    assert result.to_diagnostics()[
        "fetched_final_game_count"
    ] == 2
    assert result.to_diagnostics()[
        "feed_error_count"
    ] == 1
    assert result.role_evidence[
        "pitcher_count"
    ] == 3


def test_cache_prevents_duplicate_requests():
    request_get, calls = request_get_factory()
    cache = {}

    first = run(
        request_get=request_get,
        cache=cache,
    )
    first_call_count = len(calls)

    second = run(
        request_get=request_get,
        cache=cache,
    )

    assert first == second
    assert first_call_count == 4
    assert len(calls) == first_call_count


def test_cache_result_is_defensive():
    request_get, _ = request_get_factory()
    cache = {}

    first = run(
        request_get=request_get,
        cache=cache,
    )
    diagnostics = first.to_diagnostics()
    diagnostics["status"] = "mutated"

    second = run(
        request_get=request_get,
        cache=cache,
    )

    assert second.to_diagnostics()[
        "status"
    ] == "materialized"


def test_roster_and_provider_inputs_are_unchanged():
    active_roster = roster()
    original_roster = deepcopy(active_roster)
    request_get, _ = request_get_factory()

    fetch_canonical_pitcher_role_evidence_source(
        team_id=10,
        season=2026,
        as_of=AS_OF,
        active_roster_records=active_roster,
        request_get=request_get,
    )

    assert active_roster == original_roster


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"team_id": None}, "team_id is required"),
        ({"as_of": "invalid"}, "as_of must be a valid date"),
        (
            {"maximum_final_games": 0},
            "maximum_final_games must be positive",
        ),
        (
            {"lookback_days": 0},
            "lookback_days must be positive",
        ),
    ],
)
def test_rejects_invalid_context(kwargs, message):
    request_get, _ = request_get_factory()
    arguments = {
        "team_id": 10,
        "season": 2026,
        "as_of": AS_OF,
        "active_roster_records": roster(),
        "request_get": request_get,
    }
    arguments.update(kwargs)

    with pytest.raises(
        ValueError,
        match=message,
    ):
        fetch_canonical_pitcher_role_evidence_source(
            **arguments
        )


def test_rejects_invalid_roster_contract():
    request_get, _ = request_get_factory()

    with pytest.raises(
        TypeError,
        match=(
            "active_roster_records must be a sequence"
        ),
    ):
        fetch_canonical_pitcher_role_evidence_source(
            team_id=10,
            season=2026,
            as_of=AS_OF,
            active_roster_records={},
            request_get=request_get,
        )


def test_result_contract_is_public():
    from mlb_app.simulation.shadow import (
        CANONICAL_PITCHER_ROLE_EVIDENCE_SOURCE_VERSION,
        CanonicalPitcherRoleEvidenceSourceResult,
        fetch_canonical_pitcher_role_evidence_source,
    )

    assert (
        CANONICAL_PITCHER_ROLE_EVIDENCE_SOURCE_VERSION
    )
    assert (
        CanonicalPitcherRoleEvidenceSourceResult
        is not None
    )
    assert callable(
        fetch_canonical_pitcher_role_evidence_source
    )

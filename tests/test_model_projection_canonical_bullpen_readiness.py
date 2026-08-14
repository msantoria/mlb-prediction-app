from __future__ import annotations

from mlb_app.simulation.shadow import (
    build_canonical_shadow_bootstrap_readiness,
    discover_canonical_shadow_bullpens,
)


def roster(team_id, season, team_name=None):
    starter = 100 if team_id == 10 else 200

    return [
        {
            "mlb_player_id": starter,
            "player_type": "pitcher",
        },
        {
            "mlb_player_id": starter + 1,
            "player_type": "pitcher",
        },
    ]


def base_matchup():
    return {
        "game_pk": 123,
        "away_pitcher_id": 100,
        "home_pitcher_id": 200,
        "away_lineup": [
            {"player_id": f"a{index}"}
            for index in range(9)
        ],
        "home_lineup": [
            {"player_id": f"h{index}"}
            for index in range(9)
        ],
    }


def test_discovered_bullpens_advance_readiness():
    discovery = discover_canonical_shadow_bullpens(
        away_team_id=10,
        away_team_name="Away",
        away_starter_id=100,
        home_team_id=20,
        home_team_name="Home",
        home_starter_id=200,
        season=2026,
        roster_fetcher=roster,
    )

    matchup = base_matchup()
    matchup.update(
        discovery.readiness_matchup_fields()
    )

    report = build_canonical_shadow_bootstrap_readiness(
        game_pk=123,
        matchup=matchup,
        away_context={},
        home_context={},
        workspace={},
    )

    assert report["requirements"][
        "away_bullpen"
    ]["ready"] is True
    assert report["requirements"][
        "home_bullpen"
    ]["ready"] is True

    assert report["missing_requirements"] == [
        "probability_provider",
        "exact_probability_artifact",
        "fallback_probability_catalog",
    ]


def test_failed_roster_discovery_keeps_bullpens_blocked():
    def failing_roster(
        team_id,
        season,
        team_name=None,
    ):
        raise RuntimeError("unavailable")

    discovery = discover_canonical_shadow_bullpens(
        away_team_id=10,
        away_team_name="Away",
        away_starter_id=100,
        home_team_id=20,
        home_team_name="Home",
        home_starter_id=200,
        season=2026,
        roster_fetcher=failing_roster,
    )

    matchup = base_matchup()
    matchup.update(
        discovery.readiness_matchup_fields()
    )

    report = build_canonical_shadow_bootstrap_readiness(
        game_pk=123,
        matchup=matchup,
        away_context={},
        home_context={},
        workspace={},
    )

    assert report["requirements"][
        "away_bullpen"
    ]["ready"] is False
    assert report["requirements"][
        "home_bullpen"
    ]["ready"] is False

def test_pregame_evidence_uses_scheduled_game_time():
    discovery = discover_canonical_shadow_bullpens(
        away_team_id=10,
        away_team_name="Real Away Team",
        away_starter_id=100,
        home_team_id=20,
        home_team_name="Real Home Team",
        home_starter_id=200,
        season=2026,
        roster_fetcher=roster,
        pregame_evidence_as_of=(
            "2026-08-09T23:05:00+00:00"
        ),
        away_pregame_provider_observations=(
            {
                "pitcher_id": "101",
                "status": "eligible",
                "role": "closer",
                "source": "provider_depth_chart_v1",
                "observed_at": (
                    "2026-08-09T22:30:00+00:00"
                ),
            },
        ),
        home_pregame_provider_observations=(
            {
                "pitcher_id": "201",
                "status": "ineligible",
                "role": "probable_starter",
                "source": "provider_rotation_v1",
                "observed_at": (
                    "2026-08-09T22:30:00+00:00"
                ),
                "reason": (
                    "probable_starter_not_in_plan"
                ),
            },
        ),
    )

    assert discovery.away.pregame_evidence is not None
    assert discovery.home.pregame_evidence is not None

    assert discovery.away.bullpen_pitcher_ids == (
        "101",
    )
    assert discovery.home.bullpen_pitcher_ids == ()

    away_diagnostics = (
        discovery.away.to_diagnostics()
    )
    home_diagnostics = (
        discovery.home.to_diagnostics()
    )

    assert away_diagnostics[
        "pregame_evidence_materialized"
    ] is True
    assert home_diagnostics[
        "pregame_evidence_materialized"
    ] is True
    assert away_diagnostics[
        "pregame_evidence_stale_count"
    ] == 0
    assert home_diagnostics[
        "excluded_pitcher_count"
    ] == 1

    assert discovery.to_diagnostics()[
        "activation_permitted"
    ] is False
    assert discovery.to_diagnostics()[
        "authoritative_source"
    ] == "legacy"

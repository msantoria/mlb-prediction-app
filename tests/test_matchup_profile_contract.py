from mlb_app.analysis_pipeline import generate_daily_matchups


def test_generate_daily_matchups_profile_contract(monkeypatch):
    monkeypatch.setattr(
        "mlb_app.analysis_pipeline.fetch_schedule",
        lambda date_str: [
            {
                "gamePk": 123,
                "gameDate": "2026-04-22T18:05:00Z",
                "teams": {
                    "home": {
                        "team": {"id": 1, "name": "Home Team"},
                        "probablePitcher": {"id": 1001},
                    },
                    "away": {
                        "team": {"id": 2, "name": "Away Team"},
                        "probablePitcher": {"id": 1002},
                    },
                },
                "venue": {"name": "Sample Park"},
            }
        ],
    )

    monkeypatch.setattr(
        "mlb_app.analysis_pipeline.fetch_team_records",
        lambda season: [
            {"team": {"id": 1}, "wins": 10, "losses": 5, "runDifferential": 12},
            {"team": {"id": 2}, "wins": 8, "losses": 7, "runDifferential": -3},
        ],
    )

    monkeypatch.setattr(
        "mlb_app.analysis_pipeline.fetch_team_splits",
        lambda team_id, season, split: {},
    )

    monkeypatch.setattr(
        "mlb_app.analysis_pipeline.get_pitcher_metrics",
        lambda player_id, start_date, end_date: {},
    )

    matchups = generate_daily_matchups("2026-04-22")
    assert len(matchups) == 1

    matchup = matchups[0]

    # Top-level contract
    assert "homePitcherProfile" in matchup
    assert "awayPitcherProfile" in matchup
    assert "homeTeamOffenseProfile" in matchup
    assert "awayTeamOffenseProfile" in matchup
    assert "environmentProfile" in matchup

    # Pitcher profile nested sections
    for key in ("homePitcherProfile", "awayPitcherProfile"):
        profile = matchup[key]
        assert "metadata" in profile
        assert "arsenal" in profile
        assert "bat_missing" in profile
        assert "command_control" in profile
        assert "contact_management" in profile
        assert "platoon_profile" in profile

    # Offense profile nested sections
    for key in ("homeTeamOffenseProfile", "awayTeamOffenseProfile"):
        profile = matchup[key]
        assert "metadata" in profile
        assert "contact_skill" in profile
        assert "plate_discipline" in profile
        assert "power" in profile
        assert "batted_ball_quality" in profile
        assert "platoon_profile" in profile

    # Environment profile nested sections
    environment = matchup["environmentProfile"]
    assert "metadata" in environment
    assert "weather" in environment
    assert "park_factors" in environment
    assert "game_context" in environment
    assert "run_environment" in environment
    assert "risk_flags" in environment
    assert "status" in environment

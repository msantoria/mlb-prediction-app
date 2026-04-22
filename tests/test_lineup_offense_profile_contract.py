from mlb_app.offense_profile_aggregation import build_projected_lineup_offense_profile


def test_projected_lineup_offense_profile_contract_when_lineup_missing():
    result = build_projected_lineup_offense_profile(
        lineup=[],
        season=2026,
        pitcher_hand=None,
        lineup_source="missing",
    )

    assert "metadata" in result
    assert "contact_skill" in result
    assert "plate_discipline" in result
    assert "power" in result
    assert "batted_ball_quality" in result
    assert "platoon_profile" in result

    metadata = result["metadata"]
    assert metadata["source_type"] == "projected_lineup_profile"
    assert metadata["lineup_source"] == "missing"
    assert metadata["opposing_pitcher_hand"] == "unknown"
    assert metadata["player_count_used"] == 0


def test_projected_lineup_offense_profile_contract_with_roster_source():
    result = build_projected_lineup_offense_profile(
        lineup=[{"id": 1, "fullName": "Test Batter", "batting_order": 1}],
        season=2026,
        pitcher_hand="R",
        lineup_source="roster",
    )

    assert "metadata" in result
    assert "contact_skill" in result
    assert "plate_discipline" in result
    assert "power" in result
    assert "batted_ball_quality" in result
    assert "platoon_profile" in result

    metadata = result["metadata"]
    assert metadata["lineup_source"] == "roster"
    assert metadata["opposing_pitcher_hand"] == "R"
    assert metadata["player_count_used"] == 1

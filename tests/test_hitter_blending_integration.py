import datetime

from mlb_app.offense_profile_aggregation import build_projected_lineup_offense_profile


def test_build_projected_lineup_offense_profile_returns_stable_contract_when_no_lineup():
    result = build_projected_lineup_offense_profile(
        lineup=[],
        season=2026,
        pitcher_hand="R",
        lineup_source="missing",
        target_date=datetime.date(2026, 4, 22),
    )

    assert "metadata" in result
    assert "contact_skill" in result
    assert "plate_discipline" in result
    assert "power" in result
    assert "batted_ball_quality" in result
    assert "platoon_profile" in result

    metadata = result["metadata"]
    assert metadata["sample_window"] == "blended"
    assert metadata["sample_blend_policy"] == "hitter_v1_weighted_blend"
    assert metadata["player_count_used"] == 0


def test_build_projected_lineup_offense_profile_marks_blended_metadata():
    result = build_projected_lineup_offense_profile(
        lineup=[{"id": 1, "fullName": "Test Batter", "batting_order": 1}],
        season=2026,
        pitcher_hand=None,
        lineup_source="roster",
        target_date=datetime.date(2026, 4, 22),
    )

    metadata = result["metadata"]
    assert metadata["sample_window"] == "blended"
    assert metadata["sample_family"] == "blended"
    assert metadata["sample_blend_policy"] == "hitter_v1_weighted_blend"
    assert metadata["stabilizer_window"] == "current_season"

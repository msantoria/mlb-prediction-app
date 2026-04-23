from mlb_app.matchup_analysis import build_matchup_analysis


def test_matchup_analysis_contract_with_missing_lineup():
    result = build_matchup_analysis(
        pitcher_id=None,
        pitcher_name=None,
        pitcher_hand=None,
        lineup=[],
        lineup_source="missing",
    )

    assert "metadata" in result
    assert "pitchTypeMatchups" in result
    assert "biggestEdge" in result
    assert "biggestWeakness" in result
    assert "confidence" in result
    assert "summary" in result

    metadata = result["metadata"]
    assert metadata["source_type"] == "matchup_analysis_v1"
    assert metadata["pitcher_hand"] == "unknown"
    assert metadata["lineup_source"] == "missing"
    assert metadata["lineup_player_count"] == 0

    assert result["pitchTypeMatchups"] == []
    assert result["biggestEdge"] is None
    assert result["biggestWeakness"] is None
    assert result["confidence"] == 0.0
    assert result["summary"]["status"] == "scaffold"


def test_matchup_analysis_contract_with_lineup_players():
    result = build_matchup_analysis(
        pitcher_id=123,
        pitcher_name="Pitcher Example",
        pitcher_hand="R",
        lineup=[
            {"id": 1, "fullName": "Batter One", "batting_order": 1},
            {"id": 2, "fullName": "Batter Two", "batting_order": 2},
        ],
        lineup_source="official",
    )

    metadata = result["metadata"]
    assert metadata["source_type"] == "matchup_analysis_v1"
    assert metadata["pitcher_id"] == 123
    assert metadata["pitcher_name"] == "Pitcher Example"
    assert metadata["pitcher_hand"] == "R"
    assert metadata["lineup_source"] == "official"
    assert metadata["lineup_player_count"] == 2

    assert isinstance(result["pitchTypeMatchups"], list)
    assert len(result["pitchTypeMatchups"]) > 0
    assert result["biggestEdge"] is not None
    assert result["biggestWeakness"] is not None
    assert result["confidence"] > 0.0
    assert result["summary"]["status"] == "partial"

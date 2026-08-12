import datetime as dt

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from mlb_app.dashboard_object_models import DashboardPlayer
from mlb_app.dashboard_related_report_query import query_related_report
from mlb_app.dashboard_report_types import describe_report_type
from mlb_app.database import Base, BatterPitchTypeMatchup, PitchArsenal
from mlb_app.model_tracker import ModelTrackerSnapshot


DATE = dt.date(2026, 7, 16)


def make_session():
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, future=True)()


def player(
    player_id,
    name,
    appearances,
    player_type="hitter",
    active=True,
    team_name=None,
):
    return DashboardPlayer(
        mlb_player_id=player_id, full_name=name, player_type=player_type,
        current_team_id=player_id * 10,
        current_team_name=team_name,
        is_active=active, active_status_reason="recent_confirmed_lineup",
        first_tracked_date=DATE - dt.timedelta(days=30), last_tracked_date=DATE,
        most_recent_lineup_date=DATE, most_recent_game_date=DATE,
        lineup_appearance_count=appearances, tracked_game_count=10,
        identity_resolution_status="resolved",
    )


def test_lineup_history_is_a_complete_validated_related_report():
    session = make_session()
    session.add_all([player(1, "Alpha", 3), player(2, "Beta", 1), player(3, "None", 0)])
    session.commit()
    result = query_related_report(session, "players_lineup_history", page_size=1)
    assert result["totalSize"] == 2
    assert result["records"][0]["full_name"] == "Alpha"
    assert result["query_source"] == "dashboard_players"
    assert result["page_info"]["has_next"] is True
    fields = {field["name"] for field in describe_report_type("players_lineup_history")["fields"]}
    assert {"most_recent_lineup_date", "lineup_appearance_count", "tracked_game_count"}.issubset(fields)


def test_arsenal_splits_only_include_active_canonical_hitters_and_filter_in_sql():
    session = make_session()
    session.add_all([player(1, "Alpha", 3), player(2, "Inactive", 3, active=False)])
    session.add_all([
        BatterPitchTypeMatchup(batter_id=1, batter_name="Alpha", opposing_pitcher_id=9, pitch_type="FF", target_date=DATE, pitches_seen=80, xwoba=0.41),
        BatterPitchTypeMatchup(batter_id=1, batter_name="Alpha", opposing_pitcher_id=9, pitch_type="SL", target_date=DATE, pitches_seen=20, xwoba=0.31),
        BatterPitchTypeMatchup(batter_id=2, batter_name="Inactive", opposing_pitcher_id=9, pitch_type="FF", target_date=DATE, pitches_seen=100, xwoba=0.5),
    ])
    session.commit()
    result = query_related_report(
        session, "hitters_arsenal_splits",
        filters={"pitch_type": "FF", "min_pitches_seen": 50},
    )
    assert result["totalSize"] == 1
    assert result["records"][0]["batter_id"] == 1
    assert result["records"][0]["pitches_seen"] == 80
    assert result["query_source"] == "batter_pitch_type_matchups"


def test_arsenal_reports_select_latest_row_at_the_natural_junction_grain():
    session = make_session()
    session.add(player(1, "Alpha", 3))
    session.add_all([
        BatterPitchTypeMatchup(
            batter_id=1, batter_name="Alpha", opposing_pitcher_id=9,
            pitch_type="FF", target_date=DATE, game_pk=77, pitches_seen=40, xwoba=0.31,
        ),
        BatterPitchTypeMatchup(
            batter_id=1, batter_name="Alpha", opposing_pitcher_id=9,
            pitch_type="FF", target_date=DATE, game_pk=77, pitches_seen=80, xwoba=0.41,
        ),
    ])
    session.commit()

    result = query_related_report(session, "hitters_arsenal_splits", as_of_date=DATE)

    assert result["totalSize"] == 1
    assert result["records"][0]["pitches_seen"] == 80


def test_related_reports_reject_unsupported_fields_weights_and_filters():
    session = make_session()
    with pytest.raises(ValueError, match="Weights are not supported"):
        query_related_report(session, "players_lineup_history", weights={"Score": 2})
    with pytest.raises(ValueError, match="Unsupported selected field"):
        query_related_report(session, "players_lineup_history", selected_fields=["secret"])
    with pytest.raises(ValueError, match="Unsupported filter field"):
        query_related_report(session, "hitters_arsenal_splits", filters=[{"field": "secret", "value": 1}])


def test_competitive_batter_arsenal_is_the_registered_matchup_object_and_supports_or():
    session = make_session()
    session.add_all([
        player(1, "Alpha", 3, team_name="Chicago Cubs"),
        player(
            9,
            "Opponent Arm",
            0,
            player_type="pitcher",
            team_name="St. Louis Cardinals",
        ),
    ])
    session.add_all([
        BatterPitchTypeMatchup(batter_id=1, batter_name="Alpha", opposing_pitcher_id=9, pitch_type="FF", target_date=DATE, pitches_seen=80, xwoba=0.41),
        BatterPitchTypeMatchup(batter_id=1, batter_name="Alpha", opposing_pitcher_id=9, pitch_type="SL", target_date=DATE, pitches_seen=20, xwoba=0.31),
    ])
    session.add_all([
        PitchArsenal(season=DATE.year, pitcher_id=9, pitch_type="FF", pitch_name="Four-Seam Fastball", pitch_count=400, usage_pct=0.5, whiff_pct=0.24, strikeout_pct=0.27, xwoba=0.32, hard_hit_pct=0.35),
        PitchArsenal(season=DATE.year, pitcher_id=9, pitch_type="SL", pitch_name="Slider", pitch_count=220, usage_pct=0.28, whiff_pct=0.36, strikeout_pct=0.32, xwoba=0.28, hard_hit_pct=0.30),
    ])
    session.commit()
    result = query_related_report(
        session,
        "competitive_batter_arsenal",
        as_of_date=DATE,
        filters={
            "logic": "or",
            "conditions": [
                {"field": "pitch_type", "operator": "eq", "value": "SL"},
                {"field": "pitches_seen", "operator": "gte", "value": 50},
            ],
        },
    )
    assert result["filter_logic"] == "or"
    assert result["totalSize"] == 2
    assert result["object_info"]["api_name"] == "competitive_batter_arsenal"
    assert result["query_source"] == "batter_pitch_type_matchups"
    fastball = next(row for row in result["records"] if row["pitch_type"] == "FF")
    assert fastball["pitcher_pitch_name"] == "Four-Seam Fastball"
    assert fastball["pitcher_usage_pct"] == pytest.approx(0.5)
    assert fastball["team_name"] == "Chicago Cubs"
    assert fastball["opposing_team_name"] == "St. Louis Cardinals"
    assert fastball["edge_score"] is not None
    assert fastball["matchup_confidence"] is not None
    team_filtered = query_related_report(
        session,
        "competitive_batter_arsenal",
        as_of_date=DATE,
        filters=[{
            "field": "opposing_team_name",
            "operator": "contains",
            "value": "Cardinals",
        }],
    )
    assert team_filtered["totalSize"] == 2
    fields = {
        field["name"]: field
        for field in describe_report_type("competitive_batter_arsenal")["fields"]
    }
    assert fields["team_name"]["relationship_path"] == "batter.current_team"
    assert (
        fields["opposing_team_name"]["relationship_path"]
        == "opposing_pitcher.current_team"
    )


def test_model_tracker_report_exposes_safe_scalar_columns_only():
    session = make_session()
    session.add(ModelTrackerSnapshot(
        tracker_key="fixture",
        snapshot_date=DATE,
        source="model_projections",
        source_component="canonical_moneyline_side",
        game_pk=123,
        pick_label="CHC",
        model_name="fixture_model",
        score=0.73,
        grade="won",
        raw_payload_json='{"secret": "must-not-leak"}',
        reasoning_json='{"private": "detail"}',
    ))
    session.commit()
    result = query_related_report(
        session,
        "model_tracker_snapshots",
        as_of_date=DATE,
        filters={"logic": "and", "conditions": [{"field": "grade", "operator": "eq", "value": "won"}]},
    )
    assert result["totalSize"] == 1
    row = result["records"][0]
    assert row["pick_label"] == "CHC"
    assert "raw_payload_json" not in row
    assert "reasoning_json" not in row
    fields = {field["name"] for field in result["object_info"]["fields"]}
    assert "raw_payload_json" not in fields
    assert "reasoning_json" not in fields

import datetime as dt

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from mlb_app.dashboard_object_models import DashboardPlayer, PlayerTrendSnapshot
from mlb_app.dashboard_report_types import describe_report_type
from mlb_app.database import AppDashboardFolder, AppDashboardItem, Base, StatcastEvent
from mlb_app.player_trends import query_player_trends, supported_trend_configuration
from mlb_app.saved_report_analysis import (
    build_saved_report_packet,
    execution_request_from_item,
    resolve_owned_saved_reports,
)


@pytest.fixture()
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    with Session() as value:
        yield value


def _player(player_id, player_type):
    return DashboardPlayer(
        mlb_player_id=player_id,
        full_name=f"Player {player_id}",
        current_team_name="CHC",
        player_type=player_type,
        is_active=True,
        first_tracked_date=dt.date(2026, 1, 1),
        last_tracked_date=dt.date(2026, 7, 29),
        identity_resolution_status="resolved",
    )


def _event(date, player_id, *, player_type, event, launch_speed=None, description=None):
    return StatcastEvent(
        game_date=date,
        game_pk=int(date.strftime("%m%d")),
        at_bat_number=1,
        pitch_number=1,
        pitcher_id=player_id if player_type == "pitcher" else 999,
        batter_id=player_id if player_type == "hitter" else 998,
        events=event,
        description=description or ("hit_into_play" if launch_speed else "called_strike"),
        launch_speed=launch_speed,
        release_speed=95.0 if player_type == "pitcher" else None,
    )


def test_hitter_previous_window_uses_rolling_page_calculator_and_direction(session):
    session.add(_player(101, "hitter"))
    for day in (dt.date(2026, 7, 10), dt.date(2026, 7, 11)):
        session.add(_event(day, 101, player_type="hitter", event="strikeout", launch_speed=82.0))
    for day in (dt.date(2026, 7, 20), dt.date(2026, 7, 21)):
        session.add(_event(day, 101, player_type="hitter", event="home_run", launch_speed=101.0))
    session.commit()

    result = query_player_trends(
        session,
        as_of_date=dt.date(2026, 7, 21),
        trend_config={
            "player_type": "hitter",
            "window_days": 7,
            "comparison_baseline": "previous_n_days",
            "minimum_sample_size": 2,
            "trend_direction": "all",
            "selected_metrics": ["batting_avg", "avg_exit_velocity", "k_pct"],
        },
    )

    assert result["totalSize"] == 3
    assert {row["trend_direction"] for row in result["records"]} == {"improving"}
    assert all(row["window_sample_size"] == 2 for row in result["records"])
    assert result["provenance"]["source"] == "player_trend_snapshots"
    assert result["provenance"]["upstream_source"] == "statcast_events"
    assert result["data_quality"]["dataset_cache_hit"] is False
    assert session.query(PlayerTrendSnapshot).count() == 3

    cached = query_player_trends(
        session,
        as_of_date=dt.date(2026, 7, 21),
        trend_config={
            "player_type": "hitter",
            "window_days": 7,
            "comparison_baseline": "previous_n_days",
            "minimum_sample_size": 2,
            "trend_direction": "all",
            "selected_metrics": ["batting_avg", "avg_exit_velocity", "k_pct"],
        },
    )
    assert cached["data_quality"]["dataset_cache_hit"] is True
    assert cached["records"] == result["records"]


def test_pitcher_higher_strikeout_rate_is_improving(session):
    session.add(_player(202, "pitcher"))
    for day in (dt.date(2026, 7, 10), dt.date(2026, 7, 11)):
        session.add(_event(day, 202, player_type="pitcher", event="field_out"))
    for day in (dt.date(2026, 7, 20), dt.date(2026, 7, 21)):
        session.add(_event(day, 202, player_type="pitcher", event="strikeout"))
    session.commit()

    result = query_player_trends(
        session,
        as_of_date=dt.date(2026, 7, 21),
        trend_config={
            "player_type": "pitcher",
            "window_days": 7,
            "comparison_baseline": "previous_n_days",
            "minimum_sample_size": 2,
            "trend_direction": "improving",
            "selected_metrics": ["k_pct"],
        },
    )

    assert result["totalSize"] == 1
    assert result["records"][0]["trend_direction"] == "improving"
    assert result["records"][0]["absolute_change"] == 1.0


def test_pitcher_whiff_rate_uses_canonical_pitch_descriptions(session):
    session.add(_player(203, "pitcher"))
    for day in (dt.date(2026, 7, 10), dt.date(2026, 7, 11)):
        session.add(_event(
            day,
            203,
            player_type="pitcher",
            event="field_out",
            description="foul",
        ))
    for day in (dt.date(2026, 7, 20), dt.date(2026, 7, 21)):
        session.add(_event(
            day,
            203,
            player_type="pitcher",
            event="strikeout",
            description="swinging_strike",
        ))
    session.commit()

    result = query_player_trends(
        session,
        as_of_date=dt.date(2026, 7, 21),
        trend_config={
            "player_type": "pitcher",
            "window_days": 7,
            "comparison_baseline": "previous_n_days",
            "minimum_sample_size": 2,
            "trend_direction": "improving",
            "selected_metrics": ["whiff_pct"],
        },
    )

    row = result["records"][0]
    assert row["window_swings"] == 2
    assert row["window_whiffs"] == 2
    assert row["window_whiff_pct"] == 1.0
    assert row["baseline_whiff_pct"] == 0.0
    assert row["trend_direction"] == "improving"


def test_unsupported_prior_equivalent_period_is_not_advertised(session):
    configuration = supported_trend_configuration()
    assert {item["value"] for item in configuration["baselines"]} == {
        "season_to_date",
        "previous_n_days",
    }
    assert "prior_equivalent_period" in configuration["unsupported_baselines"]
    with pytest.raises(ValueError, match="Unsupported Player Trends"):
        query_player_trends(
            session,
            as_of_date=dt.date(2026, 7, 21),
            trend_config={
                "player_type": "hitter",
                "window_days": 15,
                "comparison_baseline": "prior_equivalent_period",
                "minimum_sample_size": 10,
                "selected_metrics": ["batting_avg"],
            },
        )


def test_player_trend_object_registers_cached_rolling_fields():
    object_info = describe_report_type("player_trends")
    field_names = {field["name"] for field in object_info["fields"]}

    assert object_info["base_object"] == "player_trend_snapshots"
    assert {
        "window_batting_avg",
        "baseline_batting_avg",
        "batting_avg_change",
        "window_avg_velocity",
        "baseline_avg_velocity",
        "avg_velocity_change",
        "dataset_generated_at",
    }.issubset(field_names)
    assert all(
        field["filterable"]
        for field in object_info["fields"]
        if field["name"] in {"window_batting_avg", "baseline_avg_velocity"}
    )


def test_saved_report_resolution_is_user_scoped_and_packet_preserves_rank(session):
    folder = AppDashboardFolder(user_id=1, folder_name="Daily", is_default=False)
    session.add(folder)
    session.flush()
    owned = AppDashboardItem(
        user_id=1,
        folder_id=folder.id,
        source_tab="my-dashboard",
        source_type="report_view",
        title="Hot hitters",
        payload_json={
            "definition": {
                "report_type": "all_active_hitters",
                "selected_fields": ["full_name", "model_score"],
                "filters": {"logic": "and", "conditions": [], "weights": {"xwoba": 1.5}},
                "sort": {"by": "model_score", "direction": "desc"},
                "page_size": 50,
            },
            "saved_on_date": "2026-07-29",
        },
        filter_json={},
        sort_json={},
    )
    other = AppDashboardItem(
        user_id=2,
        folder_id=folder.id,
        source_tab="my-dashboard",
        source_type="report_view",
        title="Private",
        payload_json={"definition": {"report_type": "all_active_hitters"}},
        filter_json={},
        sort_json={},
    )
    session.add_all([owned, other])
    session.commit()

    assert resolve_owned_saved_reports(session, 1, [owned.id]) == [owned]
    with pytest.raises(LookupError):
        resolve_owned_saved_reports(session, 1, [other.id])

    request = execution_request_from_item(owned)
    assert request["weights"] == {"xwoba": 1.5}
    assert "weights" not in request["filters"]
    packet = build_saved_report_packet(
        [owned],
        lambda _request: {
            "records": [
                {"mlb_player_id": 1, "full_name": "First", "model_score": 99},
                {"mlb_player_id": 2, "full_name": "Second", "model_score": 90},
            ],
            "totalSize": 2,
        },
    )
    names = [row["full_name"] for row in packet["reports"][0]["highest_ranked_results"]]
    assert names == ["First", "Second"]
    assert packet["reports"][0]["ranking_preserved"] is True

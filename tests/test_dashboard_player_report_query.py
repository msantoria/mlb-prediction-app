import datetime as dt

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from mlb_app.dashboard_object_models import DashboardPlayerCurrent
from mlb_app.dashboard_player_report_query import query_player_report
from mlb_app.dashboard_report_types import (
    PLAYER_PROFILE_STATCAST_FIELD_DIRECTORY,
    describe_report_type,
    list_report_types,
)
from mlb_app.database import Base


NOW = dt.datetime(2026, 7, 15, 12, 0, 0)


def make_session():
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, future=True)()
    session.add_all([
        current(1, "Zeta Tie", "hitter", "AAA", 0.70, 0.40, confidence="high", exit_velocity=96.0),
        current(2, "Alpha Tie", "hitter", "BBB", 0.70, 0.20, confidence="medium", exit_velocity=84.0),
        current(3, "Beta Bat", "hitter", "AAA", 0.60, None, confidence="low", exit_velocity=None),
        current(4, "Inactive Bat", "hitter", "AAA", 0.99, 0.50, active=False),
        current(
            5,
            "Gamma Arm",
            "pitcher",
            "CCC",
            0.80,
            0.29,
            confidence="high",
            metrics={
                "Velocity": 97.2,
                "Spin Rate": 2520.0,
                "horizontal_break": 11.4,
                "vertical_break": 16.8,
                "release_position_x": -1.8,
                "release_position_z": 5.9,
                "release_extension": 6.7,
            },
        ),
        current(
            6,
            "Delta Arm",
            "pitcher",
            "DDD",
            0.50,
            0.34,
            confidence="low",
            metrics={"average_velocity": 91.4, "average_spin_rate": 2180.0},
        ),
    ])
    session.commit()
    return session


def current(
    player_id,
    name,
    player_type,
    team,
    score,
    xwoba,
    *,
    active=True,
    confidence=None,
    exit_velocity=None,
    metrics=None,
):
    return DashboardPlayerCurrent(
        mlb_player_id=player_id, snapshot_id=player_id, player_type=player_type,
        full_name=name, team_id=player_id * 10, team_name=team,
        primary_position="OF" if player_type == "hitter" else "P", is_active=active,
        model_score=score, confidence=confidence, xwoba=xwoba,
        exit_velocity=exit_velocity,
        metrics_json={"source_metric": player_id, **(metrics or {})},
        projection_version="projection-v2" if player_id % 2 else "projection-v1",
        source_freshness_json={"snapshot_date": "2026-07-15"},
        provenance_json={"sources": ["test"]}, promoted_at=NOW,
        updated_at=NOW + dt.timedelta(minutes=player_id),
    )


def test_default_reports_use_complete_active_canonical_populations():
    session = make_session()
    hitters = query_player_report(session, "all_active_hitters")
    pitchers = query_player_report(session, "all_active_pitchers")
    assert hitters["totalSize"] == 3
    assert [row["mlb_player_id"] for row in hitters["records"]] == [2, 1, 3]
    assert pitchers["totalSize"] == 2
    assert hitters["query_source"] == "dashboard_player_current"


def test_validated_filters_are_applied_in_sql_before_count_and_page():
    session = make_session()
    result = query_player_report(
        session, "all_active_hitters",
        filters={"team": "AAA", "metrics": {"xwOBA": {"min": 0.3}}},
    )
    assert result["totalSize"] == 1
    assert result["records"][0]["full_name"] == "Zeta Tie"
    confidence = query_player_report(session, "all_active_hitters", filters={"min_confidence": "medium"})
    assert confidence["totalSize"] == 2


def test_match_all_and_match_any_logic_apply_before_count_sort_and_page():
    session = make_session()
    match_all = query_player_report(
        session,
        "all_active_hitters",
        filters={
            "logic": "and",
            "conditions": [
                {"field": "team_name", "operator": "eq", "value": "AAA"},
                {"field": "model_score", "operator": "gt", "value": "0.65"},
            ],
        },
        page_size=1,
    )
    assert match_all["filter_logic"] == "and"
    assert match_all["totalSize"] == 1
    assert [row["full_name"] for row in match_all["records"]] == ["Zeta Tie"]

    match_any = query_player_report(
        session,
        "all_active_hitters",
        filters={
            "logic": "or",
            "conditions": [
                {"field": "team_name", "operator": "eq", "value": "BBB"},
                {"field": "model_score", "operator": "lt", "value": 0.65},
            ],
        },
        page_size=1,
        page_number=1,
    )
    assert match_any["filter_logic"] == "or"
    assert match_any["totalSize"] == 2
    assert match_any["page_info"]["has_next_page"] is True
    assert match_any["records"][0]["full_name"] == "Alpha Tie"


def test_filter_values_are_typed_and_in_requires_a_bounded_value_list():
    session = make_session()
    result = query_player_report(
        session,
        "all_active_pitchers",
        filters={
            "logic": "and",
            "conditions": [
                {"field": "mlb_player_id", "operator": "in", "value": ["5", 6]},
                {"field": "updated_at", "operator": "gte", "value": "2026-07-15T12:05:00"},
            ],
        },
    )
    assert [row["mlb_player_id"] for row in result["records"]] == [5, 6]
    with pytest.raises(ValueError, match="requires a list"):
        query_player_report(
            session,
            "all_active_pitchers",
            filters=[{"field": "mlb_player_id", "operator": "in", "value": "5,6"}],
        )


def test_invalid_filter_logic_is_rejected():
    with pytest.raises(ValueError, match="filters.logic"):
        query_player_report(
            make_session(),
            "all_active_hitters",
            filters={"logic": "xor", "conditions": []},
        )


def test_confirmed_population_is_constrained_before_filters_count_and_pagination():
    session = make_session()
    result = query_player_report(
        session,
        "all_active_hitters",
        population_player_ids=[1, 2, 999],
        population_mode="confirmed_lineup",
        filters={"team": "AAA"},
        page_size=1,
        page_number=1,
    )
    assert result["population"] == {
        "mode": "confirmed_lineup",
        "candidate_id_count": 3,
        "matched_current_count": 2,
        "filtered_count": 1,
    }
    assert result["totalSize"] == 1
    assert [row["mlb_player_id"] for row in result["records"]] == [1]


def test_empty_confirmed_population_never_falls_back_to_all_active_hitters():
    result = query_player_report(
        make_session(),
        "all_active_hitters",
        population_player_ids=[],
        population_mode="confirmed_lineup",
    )
    assert result["totalSize"] == 0
    assert result["population"]["matched_current_count"] == 0


@pytest.mark.parametrize(
    "filters, message",
    [
        ([{"field": "secret", "operator": "eq", "value": 1}], "Unsupported filter field"),
        ([{"field": "xwoba", "operator": "contains", "value": "4"}], "Unsupported operator"),
        ({"metrics": {"Mystery": {"min": 1}}}, "Unsupported metric filter"),
    ],
)
def test_unsupported_filters_fail_explicitly(filters, message):
    with pytest.raises(ValueError, match=message):
        query_player_report(make_session(), "all_active_hitters", filters=filters)


def test_pagination_and_ties_are_stable_and_disjoint():
    session = make_session()
    first = query_player_report(session, "all_active_hitters", page_size=1, page_number=1)
    second = query_player_report(session, "all_active_hitters", page_size=1, page_number=2)
    assert first["records"][0]["full_name"] == "Alpha Tie"
    assert second["records"][0]["full_name"] == "Zeta Tie"
    assert first["records"][0]["mlb_player_id"] != second["records"][0]["mlb_player_id"]
    assert first["page_info"]["has_next_page"] is True


def test_request_scoped_weights_rerank_without_mutating_base_scores():
    session = make_session()
    baseline = query_player_report(session, "all_active_hitters")
    weighted = query_player_report(session, "all_active_hitters", weights={"xwOBA": 2.0}, sort_by="adjusted_score")
    assert baseline["records"][0]["full_name"] == "Alpha Tie"
    assert weighted["records"][0]["full_name"] == "Zeta Tie"
    assert weighted["totalSize"] == baseline["totalSize"]
    assert weighted["records"][0]["base_score"] == pytest.approx(0.70)
    assert session.get(DashboardPlayerCurrent, 1).model_score == pytest.approx(0.70)
    assert weighted["weight_explanation"] == ["xwOBA emphasized at 2.0"]


def test_null_metrics_do_not_change_weighted_score_and_can_be_filtered():
    session = make_session()
    weighted = query_player_report(session, "all_active_hitters", weights={"xwOBA": 2.0})
    beta = next(row for row in weighted["records"] if row["full_name"] == "Beta Bat")
    assert beta["adjusted_score"] == pytest.approx(beta["base_score"])
    nulls = query_player_report(session, "all_active_hitters", filters=[{"field": "xwoba", "operator": "is_null"}])
    assert [row["full_name"] for row in nulls["records"]] == ["Beta Bat"]


def test_field_metadata_selection_and_provenance_are_authoritative():
    session = make_session()
    info = describe_report_type("all_active_hitters")
    names = {field["name"] for field in info["fields"]}
    assert {"mlb_player_id", "model_score", "xwoba", "projection_version", "metrics"}.issubset(names)
    assert [item["api_name"] for item in list_report_types()[:2]] == ["all_active_hitters", "all_active_pitchers"]
    result = query_player_report(session, "all_active_hitters", selected_fields=["full_name", "xwoba"])
    assert result["query"]["selected_fields"] == ["full_name", "xwoba"]
    assert result["provenance"]["projection_versions"] == ["projection-v1", "projection-v2"]
    assert result["provenance"]["updated_at"] == (NOW + dt.timedelta(minutes=3)).isoformat()
    with pytest.raises(ValueError, match="Unsupported selected field"):
        query_player_report(session, "all_active_hitters", selected_fields=["not_a_field"])
    with pytest.raises(ValueError, match="Unsupported selected field"):
        query_player_report(session, "all_active_hitters", selected_fields=["metrics"])


def test_pitcher_catalog_and_query_use_pitcher_aggregate_fields_only():
    session = make_session()
    info = describe_report_type("all_active_pitchers")
    names = {field["name"] for field in info["fields"]}
    assert {
        "average_velocity",
        "average_spin_rate",
        "horizontal_break",
        "vertical_break",
        "release_position_x",
        "release_position_z",
        "release_extension",
        "xwoba",
        "xba",
    }.issubset(names)
    assert {
        "exit_velocity",
        "launch_angle",
        "barrel_rate",
        "iso",
        "obp",
        "slg",
        "batting_average",
    }.isdisjoint(names)
    result = query_player_report(
        session,
        "all_active_pitchers",
        selected_fields=["full_name", "average_velocity", "average_spin_rate"],
        filters={
            "logic": "and",
            "conditions": [
                {"field": "average_velocity", "operator": "gte", "value": 95},
                {"field": "average_spin_rate", "operator": "gte", "value": 2400},
            ],
        },
        sort_by="average_velocity",
    )
    assert result["totalSize"] == 1
    assert result["records"][0]["full_name"] == "Gamma Arm"
    assert result["records"][0]["average_velocity"] == pytest.approx(97.2)
    assert result["records"][0]["average_spin_rate"] == pytest.approx(2520.0)


def test_hitter_catalog_does_not_advertise_pitcher_only_aggregate_fields():
    names = {
        field["name"]
        for field in describe_report_type("all_active_hitters")["fields"]
    }
    assert "batting_average" in names
    assert {
        "average_velocity",
        "average_spin_rate",
        "horizontal_break",
        "vertical_break",
        "release_position_x",
        "release_position_z",
        "release_extension",
    }.isdisjoint(names)


def test_player_profile_statcast_directory_drives_object_manager_fields():
    hitter_fields = {
        field["name"]: field
        for field in describe_report_type("all_active_hitters")["fields"]
    }
    pitcher_fields = {
        field["name"]: field
        for field in describe_report_type("all_active_pitchers")["fields"]
    }
    for name, definition in PLAYER_PROFILE_STATCAST_FIELD_DIRECTORY.items():
        for player_type, catalog in (
            ("hitter", hitter_fields),
            ("pitcher", pitcher_fields),
        ):
            if player_type in definition["player_types"]:
                assert catalog[name]["field_directory"] == "player_profile_statcast"
            else:
                assert name not in catalog


@pytest.mark.parametrize("report_type", ["all_active_hitters", "all_active_pitchers"])
def test_every_selectable_player_field_has_a_server_filter_contract(report_type):
    info = describe_report_type(report_type)
    selectable = [field for field in info["fields"] if field.get("selectable", True)]
    assert selectable
    assert all(field["filterable"] for field in selectable)
    assert all(field["supported_operators"] for field in selectable)
    metrics = next(field for field in info["fields"] if field["name"] == "metrics")
    assert metrics["selectable"] is False
    assert metrics["filterable"] is False


def test_sort_validation_and_ascending_sort_cover_the_full_result_set():
    session = make_session()
    result = query_player_report(session, "all_active_hitters", sort_by="xwoba", sort_direction="asc")
    assert [row["xwoba"] for row in result["records"]] == [0.2, 0.4, None]
    with pytest.raises(ValueError, match="Unsupported sort field"):
        query_player_report(session, "all_active_hitters", sort_by="metrics")
    with pytest.raises(ValueError, match="Unsupported queryable report type"):
        query_player_report(session, "teams_daily_analysis")

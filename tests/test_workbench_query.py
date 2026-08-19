import datetime as dt

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from mlb_app import admin_access, my_dashboard_routes, workbench_query
from mlb_app.database import AppFeatureFlag, AppSession, AppUser, AppUserRole, Base


EXAMPLE = """SELECT full_name, team_name, model_score
FROM all_active_hitters
WHERE model_score >= 0.5 AND confidence = 'high'
ORDER BY model_score DESC
LIMIT 50"""


def _principal(*, role="admin", capabilities=None):
    now = admin_access._utcnow()
    return admin_access.DashboardPrincipal(
        user_id=1,
        email="owner@example.com",
        username="owner",
        role=role,
        capabilities=tuple(capabilities or admin_access.capabilities_for_role(role)),
        session_id=10,
        session_created_at=now,
        session_expires_at=now + dt.timedelta(hours=6),
    )


def test_example_compiles_to_a_structured_allowlisted_plan():
    plan = workbench_query.parse_workbench_statement(EXAMPLE)
    assert plan.logical_object == "all_active_hitters"
    assert plan.selected_fields == ["full_name", "team_name", "model_score"]
    assert plan.filters == [
        {"field": "model_score", "operator": "gte", "value": 0.5},
        {"field": "confidence", "operator": "eq", "value": "high"},
    ]
    assert plan.sort_by == "model_score"
    assert plan.sort_direction == "desc"
    assert plan.page_size == 50
    assert plan.as_dict()["authored_sql_executed"] is False


@pytest.mark.parametrize(
    "statement, message",
    [
        ("SELECT * FROM all_active_hitters LIMIT 10", "wildcards"),
        ("SELECT full_name FROM dashboard_player_current LIMIT 10", "logical object"),
        ("SELECT full_name FROM all_active_hitters", "Use SELECT fields"),
        ("SELECT full_name FROM all_active_hitters LIMIT 251", "LIMIT must be"),
        ("SELECT full_name FROM all_active_hitters; DROP TABLE users", "semicolons"),
        ("SELECT full_name FROM all_active_hitters -- comment LIMIT 10", "Comments"),
        ("DELETE FROM all_active_hitters LIMIT 10", "DELETE"),
        ("SELECT full_name FROM all_active_hitters JOIN secrets LIMIT 10", "JOIN"),
        ("SELECT full_name FROM all_active_hitters WHERE confidence = 'high' OR confidence = 'low' LIMIT 10", "OR"),
        ("SELECT full_name FROM all_active_hitters WHERE secret = 1 LIMIT 10", "filter field"),
        ("SELECT full_name FROM all_active_hitters WHERE model_score CONTAINS '5' LIMIT 10", "operator"),
    ],
)
def test_unsafe_or_unsupported_statements_are_rejected(statement, message):
    with pytest.raises(ValueError, match=message):
        workbench_query.parse_workbench_statement(statement)


def test_typed_literals_and_null_operators_use_field_contracts():
    plan = workbench_query.parse_workbench_statement(
        "SELECT batter_name, batter_team_id, xwoba FROM hitters_arsenal_splits "
        "WHERE batter_team_id = 112 AND xwoba IS NOT NULL ORDER BY xwoba ASC LIMIT 25"
    )
    assert plan.filters == [
        {"field": "batter_team_id", "operator": "eq", "value": 112},
        {"field": "xwoba", "operator": "is_not_null"},
    ]
    assert plan.sort_direction == "asc"


def test_execution_passes_only_the_normalized_contract_to_existing_service(monkeypatch):
    captured = {}

    def query(session, report_type, **options):
        captured.update({"session": session, "report_type": report_type, **options})
        return {"records": [], "items": [], "totalSize": 0}

    monkeypatch.setattr(workbench_query, "query_player_report", query)
    plan = workbench_query.parse_workbench_statement(EXAMPLE)
    result = workbench_query.execute_workbench_plan(object(), plan, page_number=2)
    assert captured["report_type"] == "all_active_hitters"
    assert captured["filters"] == plan.filters
    assert captured["page_number"] == 2
    assert captured["page_size"] == 50
    assert "statement" not in captured
    assert result["workbench_plan"]["execution_boundary"] == "structured_report_service"


def test_metadata_is_derived_and_excludes_physical_schema_details():
    objects = workbench_query.queryable_objects()
    assert {item["api_name"] for item in objects} == {
        "all_active_hitters",
        "all_active_pitchers",
        "competitive_batter_arsenal",
        "hitters_arsenal_splits",
        "model_projection_games",
        "model_projection_players",
        "player_trends",
        "players_lineup_history",
    }
    assert all("base_object" not in item for item in objects)
    assert all("source_object" not in field for item in objects for field in item["fields"])
    pitcher = next(item for item in objects if item["api_name"] == "all_active_pitchers")
    pitcher_fields = {field["name"] for field in pitcher["fields"]}
    assert {"average_velocity", "average_spin_rate", "xwoba"}.issubset(pitcher_fields)
    assert {"exit_velocity", "launch_angle", "barrel_rate", "iso", "obp", "slg"}.isdisjoint(pitcher_fields)
    assert all(field["selectable"] for item in objects for field in item["fields"])
    assert all(field["filterable"] for item in objects for field in item["fields"])
    pitcher_plan = workbench_query.parse_workbench_statement(
        "SELECT full_name, average_velocity, average_spin_rate "
        "FROM all_active_pitchers WHERE average_velocity >= 95 "
        "ORDER BY average_spin_rate DESC LIMIT 25"
    )
    assert pitcher_plan.logical_object == "all_active_pitchers"
    assert pitcher_plan.filters == [
        {"field": "average_velocity", "operator": "gte", "value": 95.0}
    ]
    projection_plan = workbench_query.parse_workbench_statement(
        "SELECT game_pk, projected_total FROM model_projection_games "
        "WHERE game_date = '2026-08-19' ORDER BY projected_total DESC LIMIT 10"
    )
    assert projection_plan.logical_object == "model_projection_games"


def test_player_trends_requires_explicit_runtime_configuration(monkeypatch):
    statement = (
        "SELECT player_name, window_iso, iso_change FROM player_trends "
        "WHERE freshness_date = '2026-08-19' AND player_type = 'hitter' "
        "AND selected_window_days = 60 AND comparison_baseline = 'previous_n_days' "
        "AND metric = 'iso' AND window_actual_pa >= 40 "
        "ORDER BY window_iso DESC LIMIT 25"
    )
    plan = workbench_query.parse_workbench_statement(statement)
    captured = {}

    def query(_session, **options):
        captured.update(options)
        return {"records": [], "items": [], "totalSize": 0}

    monkeypatch.setattr(workbench_query, "query_player_trends", query)
    result = workbench_query.execute_workbench_plan(object(), plan)

    assert captured["as_of_date"] == dt.date(2026, 8, 19)
    assert captured["trend_config"] == {
        "player_type": "hitter",
        "window_days": 60,
        "comparison_baseline": "previous_n_days",
        "minimum_sample_size": 1,
        "trend_direction": "all",
        "selected_metrics": ["iso"],
    }
    assert result["workbench_plan"]["logical_object"] == "player_trends"

    incomplete = workbench_query.parse_workbench_statement(
        "SELECT player_name FROM player_trends WHERE player_type = 'hitter' LIMIT 10"
    )
    with pytest.raises(ValueError, match="requires equality filters"):
        workbench_query.execute_workbench_plan(object(), incomplete)


def test_projection_workbench_uses_statement_game_date(monkeypatch):
    plan = workbench_query.parse_workbench_statement(
        "SELECT full_name, strikeouts FROM model_projection_players "
        "WHERE game_date = '2026-08-19' AND player_type = 'pitcher' "
        "ORDER BY strikeouts DESC LIMIT 20"
    )
    captured = {}

    def query(report_type, **options):
        captured.update({"report_type": report_type, **options})
        return {"records": [], "items": [], "totalSize": 0}

    monkeypatch.setattr(workbench_query, "query_projection_report", query)
    workbench_query.execute_workbench_plan(object(), plan)

    assert captured["report_type"] == "model_projection_players"
    assert captured["date"] == "2026-08-19"


def test_competitive_batter_arsenal_query_supports_pitcher_usage_and_hitter_sample():
    plan = workbench_query.parse_workbench_statement(
        "SELECT batter_name, pitcher_pitch_name, pitcher_usage_pct, pitches_seen, hard_hit_pct "
        "FROM competitive_batter_arsenal "
        "WHERE pitcher_usage_pct > 0.25 AND pitches_seen > 100 "
        "ORDER BY hard_hit_pct DESC LIMIT 250"
    )
    assert plan.logical_object == "competitive_batter_arsenal"
    assert plan.filters == [
        {"field": "pitcher_usage_pct", "operator": "gt", "value": 0.25},
        {"field": "pitches_seen", "operator": "gt", "value": 100},
    ]


def test_competitive_batter_arsenal_exposes_canonical_team_directory_fields():
    plan = workbench_query.parse_workbench_statement(
        "SELECT batter_name, team_name, opposing_team_name "
        "FROM competitive_batter_arsenal "
        "WHERE team_name = 'Chicago Cubs' "
        "ORDER BY opposing_team_name ASC LIMIT 50"
    )
    assert plan.selected_fields == [
        "batter_name",
        "team_name",
        "opposing_team_name",
    ]
    assert plan.filters == [{
        "field": "team_name",
        "operator": "eq",
        "value": "Chicago Cubs",
    }]


def test_request_contract_rejects_submitted_authorization_fields():
    with pytest.raises(ValidationError):
        my_dashboard_routes.QueryStudioRequest(
            statement=EXAMPLE,
            role="admin",
            capabilities=["workbench.execute"],
        )


def test_feature_flag_defaults_locked_and_honors_profile_target(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'workbench-flags.db'}")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    owner = _principal()
    with Session() as session:
        with pytest.raises(HTTPException) as locked:
            my_dashboard_routes._require_query_studio_enabled(session, owner)
        assert locked.value.status_code == 403
        session.add(AppFeatureFlag(
            flag_key="workbench_query_enabled",
            enabled=True,
            target_profiles_json=["standard_user"],
        ))
        session.commit()
        with pytest.raises(HTTPException):
            my_dashboard_routes._require_query_studio_enabled(session, owner)
        flag = session.query(AppFeatureFlag).one()
        flag.target_profiles_json = ["owner_administrator"]
        session.commit()
        my_dashboard_routes._require_query_studio_enabled(session, owner)


def test_direct_execute_tampering_still_requires_both_capabilities():
    principal = _principal(capabilities=("workbench.execute",))
    with pytest.raises(HTTPException) as denied:
        my_dashboard_routes.my_dashboard_query_studio_execute(
            my_dashboard_routes.QueryStudioRequest(statement=EXAMPLE),
            principal,
        )
    assert denied.value.status_code == 403


def test_query_studio_auth_boundary_returns_401_403_and_owner_metadata(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'workbench-http.db'}")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    now = admin_access._utcnow()
    with Session() as session:
        owner = AppUser(email="owner@example.com", username="owner", password_hash="hash", created_at=now, updated_at=now)
        user = AppUser(email="user@example.com", username="user", password_hash="hash", created_at=now, updated_at=now)
        session.add_all([owner, user])
        session.flush()
        session.add(AppUserRole(
            user_id=owner.id,
            role="admin",
            assignment_source="test",
            assigned_at=now - dt.timedelta(minutes=1),
            verified_at=now - dt.timedelta(minutes=1),
            updated_at=now,
        ))
        session.add_all([
            AppSession(user_id=owner.id, session_token="owner-token", created_at=now, last_seen_at=now, expires_at=now + dt.timedelta(hours=6)),
            AppSession(user_id=user.id, session_token="user-token", created_at=now, last_seen_at=now, expires_at=now + dt.timedelta(hours=6)),
            AppFeatureFlag(
                flag_key="workbench_query_enabled",
                enabled=True,
                target_profiles_json=["owner_administrator", "standard_user"],
            ),
        ])
        session.commit()

    monkeypatch.setattr(admin_access, "dashboard_session_factory", lambda: Session)
    monkeypatch.setattr(my_dashboard_routes, "session_factory", lambda: Session)
    with pytest.raises(HTTPException) as anonymous:
        admin_access.current_dashboard_principal(None, None)
    assert anonymous.value.status_code == 401

    standard = admin_access.current_dashboard_principal(None, "user-token")
    assert admin_access.require_capability("workbench.advanced")(standard) == standard
    standard_metadata = my_dashboard_routes.my_dashboard_query_studio_metadata(standard)
    assert standard_metadata["enabled"] is True

    owner_principal = admin_access.current_dashboard_principal(None, "owner-token")
    metadata = my_dashboard_routes.my_dashboard_query_studio_metadata(owner_principal)
    assert metadata["authored_sql_executed"] is False
    assert metadata["totalSize"] == 8

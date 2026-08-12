import datetime as dt

import pytest
from fastapi import HTTPException, Response
from pydantic import ValidationError
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from mlb_app import admin_access, admin_routes
from mlb_app import model_tracker_routes as routes
from mlb_app.application_registry import list_application_surfaces
from mlb_app.dashboard_report_types import list_report_types
from mlb_app.database import (
    AppDashboardFolder,
    AppDashboardItem,
    AppLoginHistory,
    AppSession,
    AppUser,
    AppUserDirectoryProfile,
    AppUserPreference,
    AppUserRole,
    Base,
)


def _now():
    return dt.datetime.now(dt.timezone.utc).replace(tzinfo=None, microsecond=0)


def _add_session(session, user_id, token, *, created_at=None):
    created_at = created_at or _now()
    db_session = AppSession(
        user_id=user_id,
        session_token=token,
        expires_at=created_at + dt.timedelta(hours=6),
        created_at=created_at,
        last_seen_at=created_at,
    )
    session.add(db_session)
    session.flush()
    return db_session


def _principal(
    *,
    user_id=1,
    role=admin_access.ROLE_ADMIN,
    capabilities=admin_access.ADMIN_CAPABILITIES,
):
    now = _now()
    return admin_access.DashboardPrincipal(
        user_id=user_id,
        email="owner@example.com",
        username="owner",
        role=role,
        capabilities=tuple(capabilities),
        session_id=1,
        session_created_at=now,
        session_expires_at=now + dt.timedelta(hours=6),
    )


@pytest.fixture()
def auth_store(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'dashboard-auth.db'}")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    now = _now()
    with Session() as session:
        owner = AppUser(
            email="owner@example.com",
            username="original-owner",
            password_hash=routes._hash_password("correct-password"),
            created_at=now,
            updated_at=now,
        )
        standard = AppUser(
            email="user@example.com",
            username="standard-user",
            password_hash=routes._hash_password("user-password"),
            created_at=now,
            updated_at=now,
        )
        passwordless = AppUser(
            email="legacy@example.com",
            username="legacy-user",
            password_hash=None,
            created_at=now,
            updated_at=now,
        )
        session.add_all([owner, standard, passwordless])
        session.flush()
        for user in (owner, standard, passwordless):
            session.add(
                AppUserPreference(
                    user_id=user.id,
                    wants_newsletter=False,
                    feature_interests_json=["Matchups"],
                    plan_type="free",
                    created_at=now,
                    updated_at=now,
                )
            )
        session.commit()
        ids = {
            "owner": owner.id,
            "standard": standard.id,
            "passwordless": passwordless.id,
        }

    monkeypatch.delenv("MLBGPT_ADMIN_EMAILS", raising=False)
    monkeypatch.setattr(routes, "_session_factory", lambda: Session)
    monkeypatch.setattr(admin_access, "dashboard_session_factory", lambda: Session)
    monkeypatch.setattr(admin_routes, "_session_factory", lambda: Session)
    return Session, ids


def test_existing_password_account_rejects_omitted_password_without_mutation(auth_store):
    Session, ids = auth_store

    with pytest.raises(HTTPException) as exc:
        routes.my_dashboard_profile_create(
            routes.DashboardProfileRequest(
                email="owner@example.com",
                username="attacker-name",
                password=None,
                feature_interests=["News"],
                wants_newsletter=True,
                plan_type="admin",
            ),
            Response(),
        )

    assert exc.value.status_code == 401
    with Session() as session:
        user = session.get(AppUser, ids["owner"])
        prefs = session.query(AppUserPreference).filter_by(user_id=user.id).one()
        assert user.username == "original-owner"
        assert prefs.feature_interests_json == ["Matchups"]
        assert prefs.plan_type == "free"
        assert session.query(AppSession).filter_by(user_id=user.id).count() == 0


def test_incorrect_password_rejected_without_profile_mutation(auth_store):
    Session, ids = auth_store

    with pytest.raises(HTTPException) as exc:
        routes.my_dashboard_profile_create(
            routes.DashboardProfileRequest(
                email="owner@example.com",
                username="changed-name",
                password="incorrect-password",
                feature_interests=["News"],
                wants_newsletter=True,
                plan_type="paid",
            ),
            Response(),
        )

    assert exc.value.status_code == 401
    with Session() as session:
        user = session.get(AppUser, ids["owner"])
        prefs = session.query(AppUserPreference).filter_by(user_id=user.id).one()
        assert user.username == "original-owner"
        assert prefs.feature_interests_json == ["Matchups"]
        assert prefs.wants_newsletter is False
        assert prefs.plan_type == "free"
        assert session.query(AppSession).filter_by(user_id=user.id).count() == 0


def test_legacy_passwordless_account_requires_recovery_and_cannot_be_claimed(auth_store):
    Session, ids = auth_store

    with pytest.raises(HTTPException) as exc:
        routes.my_dashboard_profile_create(
            routes.DashboardProfileRequest(
                email="legacy@example.com",
                username="attacker",
                password="new-attacker-password",
                feature_interests=["News"],
                wants_newsletter=True,
                plan_type="admin",
            ),
            Response(),
        )

    assert exc.value.status_code == 409
    assert "recovery" in str(exc.value.detail).lower()
    with Session() as session:
        user = session.get(AppUser, ids["passwordless"])
        assert user.username == "legacy-user"
        assert user.password_hash is None
        assert session.query(AppSession).filter_by(user_id=user.id).count() == 0


def test_new_registration_requires_a_password_and_preserves_six_hour_session(auth_store):
    Session, _ = auth_store

    with pytest.raises(HTTPException) as missing:
        routes.my_dashboard_profile_create(
            routes.DashboardProfileRequest(
                email="new@example.com",
                username="new-user",
                password=None,
            ),
            Response(),
        )
    assert missing.value.status_code == 400

    with pytest.raises(ValidationError):
        routes.DashboardRegisterRequest(
            email="new@example.com",
            username="new-user",
            password="short",
        )

    payload = routes.my_dashboard_register(
        routes.DashboardRegisterRequest(
            email="new@example.com",
            username="new-user",
            password="long-enough-password",
        ),
        Response(),
    )
    assert payload["user"]["role"] == "user"
    assert payload["user"]["capabilities"] == list(admin_access.USER_CAPABILITIES)
    with Session() as session:
        user = session.query(AppUser).filter_by(email="new@example.com").one()
        assert user.password_hash
        db_session = session.query(AppSession).filter_by(user_id=user.id).one()
        assert db_session.expires_at - db_session.created_at == dt.timedelta(hours=6)


def test_owner_email_allowlist_normalization():
    configured = admin_access.configured_admin_emails(
        " OWNER@Example.com,second@example.com ; owner@example.com\n"
    )
    assert configured == ("owner@example.com", "second@example.com")
    assert admin_access.is_configured_admin_email(
        "  OWNER@example.COM ",
        "owner@example.com",
    )


def test_owner_role_bootstraps_only_after_verified_login(auth_store, monkeypatch):
    Session, ids = auth_store
    monkeypatch.setenv("MLBGPT_ADMIN_EMAILS", " OWNER@EXAMPLE.COM ")
    old_created_at = _now() - dt.timedelta(hours=1)
    with Session() as session:
        owner = session.get(AppUser, ids["owner"])
        before = admin_access.access_payload_for_user(session, owner)
        assert before == {
            "role": "user",
            "capabilities": list(admin_access.USER_CAPABILITIES),
        }
        _add_session(session, owner.id, "older-owner-token", created_at=old_created_at)
        session.commit()

    with pytest.raises(HTTPException) as incorrect:
        routes.my_dashboard_login(
            routes.DashboardLoginRequest(
                email="owner@example.com",
                password="wrong-password",
            ),
            Response(),
        )
    assert incorrect.value.status_code == 401
    with Session() as session:
        assert session.query(AppUserRole).filter_by(user_id=ids["owner"]).count() == 0
        assert session.query(AppSession).filter_by(session_token="older-owner-token").count() == 1

    payload = routes.my_dashboard_login(
        routes.DashboardLoginRequest(
            email=" OWNER@EXAMPLE.COM ",
            password="correct-password",
        ),
        Response(),
    )
    assert payload["user"]["role"] == "admin"
    assert payload["user"]["capabilities"] == list(admin_access.ADMIN_CAPABILITIES)
    with Session() as session:
        assignment = session.query(AppUserRole).filter_by(user_id=ids["owner"]).one()
        assert assignment.role == "admin"
        assert assignment.assignment_source == "owner_email_allowlist_verified_login"
        assert assignment.verified_at is not None
        assert session.query(AppSession).filter_by(session_token="older-owner-token").count() == 0
        active = session.query(AppSession).filter_by(user_id=ids["owner"]).all()
        assert len(active) == 1
        assert active[0].session_token == payload["session_token"]
        directory = session.query(AppUserDirectoryProfile).filter_by(user_id=ids["owner"]).one()
        assert directory.last_login_at is not None
        login = session.query(AppLoginHistory).filter_by(user_id=ids["owner"]).one()
        assert login.session_id == active[0].id
        assert login.authentication_method == "password"
        assert login.successful is True


def test_allowlisted_email_cannot_be_registered_into_owner_access(auth_store, monkeypatch):
    monkeypatch.setenv("MLBGPT_ADMIN_EMAILS", "unprovisioned-owner@example.com")

    with pytest.raises(HTTPException) as exc:
        routes.my_dashboard_register(
            routes.DashboardRegisterRequest(
                email="unprovisioned-owner@example.com",
                username="attacker",
                password="attacker-password",
            ),
            Response(),
        )

    assert exc.value.status_code == 403


def test_stale_owner_session_cannot_inherit_new_admin_role(auth_store):
    Session, ids = auth_store
    assigned_at = _now()
    with Session() as session:
        session.add(
            AppUserRole(
                user_id=ids["owner"],
                role="admin",
                assignment_source="owner_email_allowlist_verified_login",
                assigned_at=assigned_at,
                verified_at=assigned_at,
                updated_at=assigned_at,
            )
        )
        _add_session(
            session,
            ids["owner"],
            "stale-owner-session",
            created_at=assigned_at - dt.timedelta(minutes=1),
        )
        session.commit()

    with Session() as session:
        principal = admin_access.resolve_principal(session, "stale-owner-session")
        assert principal.role == "user"
        assert principal.capabilities == admin_access.USER_CAPABILITIES
        assert "admin.portal.access" not in principal.capabilities


def test_standard_and_administrator_capabilities_are_sorted_and_server_owned():
    assert admin_access.capabilities_for_role("user") == tuple(
        sorted(admin_access.USER_CAPABILITIES)
    )
    assert admin_access.capabilities_for_role("admin") == tuple(
        sorted(admin_access.ADMIN_CAPABILITIES)
    )
    assert set(admin_access.USER_CAPABILITIES) < set(admin_access.ADMIN_CAPABILITIES)
    assert {
        "dashboard.reports.run",
        "dashboard.folders.manage",
        "dashboard.reports.manage",
        "dashboard.reports.sort",
        "dashboard.reports.filter",
        "dashboard.reports.paginate",
        "dashboard.export",
    } == set(admin_access.USER_CAPABILITIES)
    assert {
        "admin.portal.access",
        "admin.objects.read",
        "admin.apps.read",
        "admin.users.read",
        "admin.settings.read",
        "admin.operations.read",
        "admin.audit.read",
        "workbench.advanced",
    }.issubset(admin_access.ADMIN_CAPABILITIES)


def test_admin_guard_returns_401_without_session_and_403_without_capability(auth_store):
    with pytest.raises(HTTPException) as unauthenticated:
        admin_access.current_dashboard_principal(
            mlb_dashboard_session=None,
            x_dashboard_session=None,
        )
    assert unauthenticated.value.status_code == 401

    standard = _principal(
        role="user",
        capabilities=admin_access.USER_CAPABILITIES,
    )
    guard = admin_access.require_capability("admin.portal.access")
    with pytest.raises(HTTPException) as forbidden:
        guard(standard)
    assert forbidden.value.status_code == 403


def test_direct_admin_endpoint_tampering_cannot_elevate_standard_user(auth_store):
    Session, ids = auth_store
    with Session() as session:
        user = session.get(AppUser, ids["standard"])
        prefs = session.query(AppUserPreference).filter_by(user_id=user.id).one()
        prefs.plan_type = "administrator"
        _add_session(session, user.id, "standard-token")
        session.commit()

    with Session() as session:
        principal = admin_access.resolve_principal(session, "standard-token")
        assert principal.role == "user"
        assert "admin.portal.access" not in principal.capabilities

    for capability in (
        "admin.portal.access",
        "admin.objects.read",
        "admin.apps.read",
        "admin.users.read",
    ):
        guard = admin_access.require_capability(capability)
        with pytest.raises(HTTPException) as forbidden:
            guard(principal)
        assert forbidden.value.status_code == 403


def test_submitted_role_capabilities_and_plan_cannot_elevate_access(auth_store):
    with pytest.raises(ValidationError):
        routes.DashboardRegisterRequest(
            email="new@example.com",
            username="new-user",
            password="secure-password",
            role="admin",
        )
    with pytest.raises(ValidationError):
        routes.DashboardLoginRequest(
            email="user@example.com",
            password="user-password",
            capabilities=["admin.portal.access"],
        )
    with pytest.raises(ValidationError):
        routes.DashboardProfileRequest(
            email="user@example.com",
            username="standard-user",
            password="user-password",
            administrator=True,
        )

    payload = routes.my_dashboard_profile_create(
        routes.DashboardProfileRequest(
            email="user@example.com",
            username="standard-user",
            password="user-password",
            plan_type="admin",
        ),
        Response(),
    )
    assert payload["user"]["preferences"]["plan_type"] == "admin"
    assert payload["user"]["role"] == "user"
    assert payload["user"]["capabilities"] == list(admin_access.USER_CAPABILITIES)


def test_profile_and_workspace_keep_existing_contract_and_add_access(auth_store):
    Session, ids = auth_store
    with Session() as session:
        _add_session(session, ids["standard"], "profile-token")
        session.commit()

    profile = routes.my_dashboard_profile_get(
        mlb_dashboard_session=None,
        x_dashboard_session="profile-token",
    )
    workspace = routes.my_dashboard_workspace(
        mlb_dashboard_session=None,
        x_dashboard_session="profile-token",
    )

    assert profile["authenticated"] is True
    assert {
        "id",
        "email",
        "username",
        "created_at",
        "updated_at",
        "preferences",
        "role",
        "capabilities",
    }.issubset(profile["user"])
    assert profile["user"]["role"] == "user"
    assert profile["user"]["capabilities"] == list(admin_access.USER_CAPABILITIES)
    assert {
        "user",
        "folders",
        "default_folder_id",
        "today_folder_id",
        "feature_choices",
        "seeded_components",
    }.issubset(workspace)
    assert workspace["user"]["role"] == "user"
    assert workspace["user"]["capabilities"] == list(admin_access.USER_CAPABILITIES)


def test_save_as_requires_a_name_and_persists_to_the_selected_folder(auth_store):
    Session, ids = auth_store
    now = _now()
    with Session() as session:
        folder = AppDashboardFolder(
            user_id=ids["standard"],
            folder_name="Scouting Reports",
            is_default=False,
            created_at=now,
            updated_at=now,
        )
        session.add(folder)
        session.flush()
        folder_id = folder.id
        _add_session(session, ids["standard"], "save-as-token")
        session.commit()

    request_data = {
        "folder_id": folder_id,
        "source_tab": "my-dashboard",
        "source_type": "report_view",
        "subtitle": "Batter vs Arsenal",
        "payload_json": {"schema_version": 4},
    }
    with pytest.raises(HTTPException) as blank:
        routes.my_dashboard_create_item(
            routes.DashboardItemCreateRequest(title="   ", **request_data),
            mlb_dashboard_session=None,
            x_dashboard_session="save-as-token",
        )
    assert blank.value.status_code == 400

    created = routes.my_dashboard_create_item(
        routes.DashboardItemCreateRequest(
            title="  Cubs vs Cardinals Arsenal  ",
            **request_data,
        ),
        mlb_dashboard_session=None,
        x_dashboard_session="save-as-token",
    )
    assert created["item"]["title"] == "Cubs vs Cardinals Arsenal"
    assert created["item"]["folder_id"] == folder_id


def test_admin_user_list_is_explicitly_minimized(auth_store):
    Session, ids = auth_store
    now = _now()
    with Session() as session:
        folder = AppDashboardFolder(
            user_id=ids["standard"],
            folder_name="Private folder",
            is_default=False,
            created_at=now,
            updated_at=now,
        )
        session.add(folder)
        session.flush()
        session.add(
            AppDashboardItem(
                user_id=ids["standard"],
                folder_id=folder.id,
                source_tab="my-dashboard",
                source_type="report_view",
                title="Private report",
                payload_json={"secret_report_value": "must-not-leak"},
                notes="private note",
                created_at=now,
                updated_at=now,
            )
        )
        _add_session(session, ids["standard"], "must-not-leak-session-token")
        session.commit()

    payload = admin_routes.admin_users(_principal(user_id=ids["owner"]))
    assert payload["totalSize"] == 3
    assert payload["users"]
    allowed_keys = {
        "id",
        "username",
        "email",
        "role",
        "plan",
        "capabilities",
        "created_at",
        "updated_at",
    }
    assert all(set(user) == allowed_keys for user in payload["users"])
    serialized = repr(payload)
    assert "password_hash" not in serialized
    assert "must-not-leak" not in serialized
    assert "Private report" not in serialized
    assert "private note" not in serialized


def test_object_manager_response_is_derived_from_server_registry(monkeypatch):
    objects = list_report_types()
    monkeypatch.setattr(admin_routes, "list_report_types", lambda: objects)
    payload = admin_routes.admin_objects(_principal())
    assert payload["totalSize"] == len(objects) == 12
    assert payload["queryableSize"] == sum(
        bool(item.get("queryable")) for item in objects
    ) == 11
    assert all(
        {
            "api_name",
            "label",
            "base_object",
            "ui_object",
            "population",
            "relationships",
            "queryable",
            "fields",
            "freshness",
            "filtering",
            "sorting",
        }.issubset(item)
        for item in payload["objects"]
    )
    for item in payload["objects"]:
        expected_filter_count = sum(
            bool(field.get("filterable")) for field in item["fields"]
        ) if item["queryable"] else 0
        expected_sort_count = sum(
            bool(field.get("sortable")) for field in item["fields"]
        ) if item["queryable"] else 0
        expected_selectable_count = sum(
            bool(field.get("selectable", True)) for field in item["fields"]
        ) if item["queryable"] else 0
        assert item["filtering"] == {
            "supported": bool(expected_filter_count),
            "field_count": expected_filter_count,
            "selectable_field_count": expected_selectable_count,
            "logic": ["and", "or"] if item["queryable"] else [],
        }
        assert item["sorting"] == {
            "supported": bool(expected_sort_count),
            "field_count": expected_sort_count,
        }


def test_object_manager_exposes_batter_arsenal_team_directory_fields(monkeypatch):
    objects = list_report_types()
    monkeypatch.setattr(admin_routes, "list_report_types", lambda: objects)
    payload = admin_routes.admin_objects(_principal())
    arsenal = next(
        item
        for item in payload["objects"]
        if item["api_name"] == "competitive_batter_arsenal"
    )
    fields = {field["name"]: field for field in arsenal["fields"]}
    assert fields["team_name"]["label"] == "Team Name"
    assert fields["opposing_team_name"]["label"] == "Opposing Team Name"
    assert fields["team_name"]["field_directory"] == "canonical_player_directory"
    assert (
        fields["opposing_team_name"]["relationship_path"]
        == "opposing_pitcher.current_team"
    )


def test_application_registry_response_is_code_owned(monkeypatch):
    apps = list_application_surfaces()
    monkeypatch.setattr(admin_routes, "list_application_surfaces", lambda: apps)
    payload = admin_routes.admin_apps(_principal())
    assert payload == {
        "apps": apps,
        "totalSize": len(apps),
        "source": "application_registry",
    }
    assert all(
        {
            "label",
            "route",
            "visibility",
            "feature_status",
            "health_classification",
        }.issubset(app)
        for app in payload["apps"]
    )


def test_admin_overview_uses_dynamic_counts_and_safe_identity(auth_store, monkeypatch):
    objects = list_report_types()[:2]
    apps = list_application_surfaces()[:3]
    monkeypatch.setattr(admin_routes, "list_report_types", lambda: objects)
    monkeypatch.setattr(admin_routes, "list_application_surfaces", lambda: apps)
    monkeypatch.setattr(
        admin_routes,
        "latest_hydration_status",
        lambda: {
            "status": "ok",
            "target_date": "2026-07-22",
            "components": {"players": {"secret": "not-forwarded"}},
            "warnings": ["one"],
            "error": None,
            "internal_token": "not-forwarded",
        },
    )

    payload = admin_routes.admin_overview(_principal())
    assert payload["counts"]["objects"] == 2
    assert payload["counts"]["queryable_objects"] == sum(
        bool(item.get("queryable")) for item in objects
    )
    assert payload["counts"]["application_surfaces"] == 3
    assert payload["counts"]["users"] == 3
    assert payload["administrator"]["role"] == "admin"
    assert payload["operations"]["hydration"]["component_count"] == 1
    assert "components" not in payload["operations"]["hydration"]
    assert "internal_token" not in repr(payload)
    assert {item["key"] for item in payload["locked_sections"]} == {
        "operations",
        "workbench",
    }


def test_admin_router_is_direct_and_limits_mutation_to_phase_two_contract():
    methods_by_path = {}
    for route in admin_routes.router.routes:
        if hasattr(route, "methods"):
            methods_by_path.setdefault(route.path, set()).update(route.methods)
    assert methods_by_path == {
        "/admin/overview": {"GET"},
        "/admin/me": {"GET"},
        "/admin/objects": {"GET"},
        "/admin/apps": {"GET"},
        "/admin/users": {"GET"},
        "/admin/users/{user_id}": {"GET", "PATCH"},
        "/admin/profiles": {"GET"},
        "/admin/settings": {"GET", "PATCH"},
        "/admin/feature-flags": {"GET", "PATCH"},
        "/admin/audit-events": {"GET"},
    }

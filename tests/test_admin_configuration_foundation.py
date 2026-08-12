import datetime as dt

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from mlb_app import admin_access, admin_configuration, admin_routes
from mlb_app.database import (
    AppAdminAuditEvent,
    AppFeatureFlag,
    AppGlobalSetting,
    AppSession,
    AppUser,
    AppUserDirectoryProfile,
    AppUserRole,
    Base,
)


def _now():
    return dt.datetime.now(dt.timezone.utc).replace(tzinfo=None, microsecond=0)


def _principal(user_id=1, *, role="admin", capabilities=None):
    now = _now()
    return admin_access.DashboardPrincipal(
        user_id=user_id,
        email="owner@example.com" if user_id == 1 else "user@example.com",
        username="owner" if user_id == 1 else "user",
        role=role,
        capabilities=tuple(capabilities or admin_access.capabilities_for_role(role)),
        session_id=100 + user_id,
        session_created_at=now,
        session_expires_at=now + dt.timedelta(hours=6),
    )


@pytest.fixture()
def admin_store(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'admin-configuration.db'}")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    now = _now()
    with Session() as session:
        owner = AppUser(
            email="owner@example.com",
            username="owner",
            password_hash="password-backed",
            created_at=now,
            updated_at=now,
        )
        user = AppUser(
            email="user@example.com",
            username="user",
            password_hash="password-backed",
            created_at=now,
            updated_at=now,
        )
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
            AppSession(
                user_id=owner.id,
                session_token="owner-token",
                expires_at=now + dt.timedelta(hours=6),
                created_at=now,
                last_seen_at=now,
            ),
            AppSession(
                user_id=user.id,
                session_token="user-token",
                expires_at=now + dt.timedelta(hours=6),
                created_at=now,
                last_seen_at=now,
            ),
        ])
        session.commit()
        ids = {"owner": owner.id, "user": user.id}
    monkeypatch.setattr(admin_access, "dashboard_session_factory", lambda: Session)
    monkeypatch.setattr(admin_routes, "_session_factory", lambda: Session)
    return Session, ids


def test_required_feature_flags_default_false_without_rows(admin_store):
    Session, _ = admin_store
    with Session() as session:
        flags = admin_configuration.serialize_feature_flags(session)
    assert {item["key"] for item in flags} == {
        "federation_enabled",
        "federation_admin_enabled",
        "workbench_query_enabled",
        "federation_refresh_enabled",
    }
    assert all(item["enabled"] is False for item in flags)
    assert all(item["authorization_effect"] == "none" for item in flags)


def test_directory_profiles_default_and_legacy_utc_rows_converge_to_eastern(admin_store):
    Session, ids = admin_store
    with Session() as session:
        created = admin_configuration.get_or_create_directory_profile(
            session,
            ids["owner"],
        )
        assert created.timezone == "America/New_York"
        created.timezone = "UTC"
        session.commit()
    with Session() as session:
        existing = admin_configuration.get_or_create_directory_profile(
            session,
            ids["owner"],
        )
        assert existing.timezone == "America/New_York"


def test_profile_catalog_is_code_owned_and_owner_only_capabilities_extend_user(admin_store):
    payload = admin_routes.admin_profiles(_principal())
    assert [item["key"] for item in payload["profiles"]] == [
        "owner_administrator",
        "standard_user",
    ]
    owner, standard = payload["profiles"]
    assert owner["mutable"] is False
    assert "admin.settings.manage" in owner["capabilities"]
    assert "admin.settings.manage" not in standard["capabilities"]
    assert set(standard["capabilities"]).issubset(owner["capabilities"])


def test_settings_reject_unknown_and_invalid_values_without_audit(admin_store):
    Session, _ = admin_store
    with pytest.raises(HTTPException) as unknown:
        admin_routes.admin_settings_update(
            admin_routes.AdminSettingsPatchRequest(updates=[{
                "namespace": "secrets",
                "key": "api_token",
                "value": "plaintext",
            }]),
            _principal(),
        )
    assert unknown.value.status_code == 400

    with pytest.raises(HTTPException) as invalid:
        admin_routes.admin_settings_update(
            admin_routes.AdminSettingsPatchRequest(updates=[{
                "namespace": "identity",
                "key": "default_timezone",
                "value": "Mars/Olympus",
            }]),
            _principal(),
        )
    assert invalid.value.status_code == 400
    with Session() as session:
        assert session.query(AppGlobalSetting).count() == 0
        assert session.query(AppAdminAuditEvent).count() == 0


def test_setting_update_is_allowlisted_and_audited_without_secrets(admin_store):
    Session, _ = admin_store
    payload = admin_routes.admin_settings_update(
        admin_routes.AdminSettingsPatchRequest(updates=[{
            "namespace": "identity",
            "key": "default_timezone",
            "value": "America/Chicago",
        }]),
        _principal(),
    )
    assert payload["ok"] is True
    assert next(item for item in payload["settings"] if item["key"] == "default_timezone")["value"] == "America/Chicago"
    assert "secret" not in repr(payload).lower()
    with Session() as session:
        event = session.query(AppAdminAuditEvent).one()
        assert event.action == "admin.setting.updated"
        assert event.target_identifier == "identity.default_timezone"
        assert event.after_json["value"] == "America/Chicago"


def test_feature_flag_targeting_is_server_validated_and_audited(admin_store):
    Session, _ = admin_store
    with pytest.raises(HTTPException) as invalid:
        admin_routes.admin_feature_flags_update(
            admin_routes.AdminFeatureFlagsPatchRequest(updates=[{
                "key": "federation_enabled",
                "enabled": True,
                "target_profiles": ["forged_admin"],
            }]),
            _principal(),
        )
    assert invalid.value.status_code == 400

    payload = admin_routes.admin_feature_flags_update(
        admin_routes.AdminFeatureFlagsPatchRequest(updates=[{
            "key": "federation_enabled",
            "enabled": True,
            "target_profiles": ["owner_administrator"],
        }]),
        _principal(),
    )
    flag = next(item for item in payload["feature_flags"] if item["key"] == "federation_enabled")
    assert flag["enabled"] is True
    assert flag["target_profiles"] == ["owner_administrator"]
    assert flag["authorization_effect"] == "none"
    with Session() as session:
        assert session.query(AppFeatureFlag).count() == 1
        assert session.query(AppAdminAuditEvent).count() == 1


def test_user_patch_rejects_authorization_and_credential_fields():
    for forbidden in (
        {"role": "admin"},
        {"capabilities": ["admin.portal.access"]},
        {"plan": "owner"},
        {"email": "attacker@example.com"},
        {"password_hash": "nope"},
        {"session_token": "nope"},
    ):
        with pytest.raises(ValidationError):
            admin_routes.AdminUserUpdateRequest(**forbidden)


def test_owner_cannot_lock_or_deactivate_itself(admin_store):
    _, ids = admin_store
    for request in (
        admin_routes.AdminUserUpdateRequest(is_active=False),
        admin_routes.AdminUserUpdateRequest(is_locked=True),
    ):
        with pytest.raises(HTTPException) as exc:
            admin_routes.admin_user_update(ids["owner"], request, _principal(ids["owner"]))
        assert exc.value.status_code == 400


def test_security_state_change_revokes_target_sessions_and_creates_audit(admin_store):
    Session, ids = admin_store
    payload = admin_routes.admin_user_update(
        ids["user"],
        admin_routes.AdminUserUpdateRequest(
            display_name="  Standard Analyst  ",
            is_active=False,
        ),
        _principal(ids["owner"]),
    )
    assert payload["sessions_revoked"] is True
    assert payload["user"]["directory"]["display_name"] == "Standard Analyst"
    assert payload["user"]["directory"]["is_active"] is False
    with Session() as session:
        assert session.query(AppSession).filter_by(user_id=ids["user"]).count() == 0
        event = session.query(AppAdminAuditEvent).one()
        assert event.action == "admin.user.updated"
        assert "password" not in repr(event.before_json).lower()
        assert "token" not in repr(event.after_json).lower()


def test_inactive_and_locked_accounts_cannot_resolve_existing_sessions(admin_store):
    Session, ids = admin_store
    with Session() as session:
        profile = admin_configuration.get_or_create_directory_profile(session, ids["owner"])
        profile.is_locked = True
        session.commit()
    with Session() as session:
        with pytest.raises(HTTPException) as exc:
            admin_access.resolve_principal(session, "owner-token")
    assert exc.value.status_code == 403


def test_standard_user_cannot_tamper_with_private_mutation_capabilities(admin_store):
    principal = _principal(
        user_id=2,
        role="user",
        capabilities=admin_access.USER_CAPABILITIES,
    )
    for capability in ("admin.users.manage", "admin.settings.manage", "admin.audit.read"):
        guard = admin_access.require_capability(capability)
        with pytest.raises(HTTPException) as exc:
            guard(principal)
        assert exc.value.status_code == 403


def test_admin_router_exposes_only_expected_mutations():
    methods_by_path = {
        route.path: route.methods
        for route in admin_routes.router.routes
        if hasattr(route, "methods")
    }
    assert methods_by_path["/admin/users/{user_id}"] == {"PATCH"}
    assert methods_by_path["/admin/settings"] == {"PATCH"}
    assert methods_by_path["/admin/feature-flags"] == {"PATCH"}
    assert "/admin/profiles/{profile_id}" not in methods_by_path
    assert "/admin/audit-events/{event_id}" not in methods_by_path

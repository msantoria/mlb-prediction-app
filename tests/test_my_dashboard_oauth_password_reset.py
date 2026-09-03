import datetime as dt
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi import HTTPException, Response
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from mlb_app import model_tracker_routes as routes
from mlb_app.database import (
    AppOAuthIdentity,
    AppPasswordResetToken,
    AppSession,
    AppUser,
    AppUserPreference,
    Base,
)


def _now():
    return dt.datetime.now(dt.timezone.utc).replace(tzinfo=None, microsecond=0)


@pytest.fixture()
def auth_store(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'oauth-password-reset.db'}")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    now = _now()
    with Session() as session:
        user = AppUser(
            email="analyst@example.com",
            username="analyst",
            password_hash=routes._hash_password("old-password"),
            created_at=now,
            updated_at=now,
        )
        session.add(user)
        session.flush()
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
        session.add(
            AppSession(
                user_id=user.id,
                session_token="existing-session",
                expires_at=now + dt.timedelta(hours=6),
                created_at=now,
                last_seen_at=now,
            )
        )
        session.commit()
        user_id = user.id

    monkeypatch.setattr(routes, "_session_factory", lambda: Session)
    monkeypatch.setenv("DASHBOARD_FRONTEND_URL", "https://mlbgpt.com")
    return Session, user_id


def test_oauth_provider_is_enabled_only_with_both_credentials(monkeypatch):
    monkeypatch.delenv("GOOGLE_OAUTH_CLIENT_ID", raising=False)
    monkeypatch.delenv("GOOGLE_OAUTH_CLIENT_SECRET", raising=False)
    assert routes._oauth_provider_config("google") is None

    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_ID", "client")
    assert routes._oauth_provider_config("google") is None

    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_SECRET", "secret")
    assert routes._oauth_provider_config("google")["scope"] == "openid email profile"


def test_oauth_verified_email_links_existing_account(auth_store):
    Session, user_id = auth_store
    profile = {
        "provider": "google",
        "provider_user_id": "google-subject",
        "email": "analyst@example.com",
        "username": "Google Analyst",
    }

    with Session() as session:
        user, prefs = routes._resolve_oauth_user(session, profile)
        session.commit()
        assert user.id == user_id
        assert prefs.user_id == user_id
        identity = session.query(AppOAuthIdentity).one()
        assert identity.user_id == user_id
        assert identity.provider_user_id == "google-subject"

    with Session() as session:
        changed_profile = {**profile, "email": "changed@example.com"}
        user, _ = routes._resolve_oauth_user(session, changed_profile)
        session.commit()
        assert user.id == user_id
        assert session.query(AppUser).count() == 1
        assert session.query(AppOAuthIdentity).one().provider_email == "changed@example.com"


def test_password_reset_is_hashed_one_time_and_revokes_sessions(auth_store, monkeypatch):
    Session, user_id = auth_store
    deliveries = []
    monkeypatch.setattr(routes, "_send_password_reset_email", lambda email, url: deliveries.append((email, url)))

    requested = routes.my_dashboard_forgot_password(
        routes.DashboardForgotPasswordRequest(email="Analyst@Example.com")
    )
    assert requested == {"ok": True, "message": routes.DASHBOARD_PASSWORD_RESET_MESSAGE}
    assert deliveries[0][0] == "analyst@example.com"
    raw_token = parse_qs(urlparse(deliveries[0][1]).query)["reset_token"][0]

    with Session() as session:
        stored = session.query(AppPasswordResetToken).one()
        assert stored.user_id == user_id
        assert stored.token_hash == routes._token_hash(raw_token)
        assert raw_token not in stored.token_hash

    reset = routes.my_dashboard_reset_password(
        routes.DashboardResetPasswordRequest(token=raw_token, password="new-password")
    )
    assert reset["ok"] is True
    with Session() as session:
        user = session.get(AppUser, user_id)
        assert routes._verify_password("new-password", user.password_hash)
        assert session.query(AppSession).filter_by(user_id=user_id).count() == 0
        assert session.query(AppPasswordResetToken).one().used_at is not None

    with pytest.raises(HTTPException) as exc:
        routes.my_dashboard_reset_password(
            routes.DashboardResetPasswordRequest(token=raw_token, password="another-password")
        )
    assert exc.value.status_code == 400


def test_unknown_password_reset_request_has_identical_response(auth_store, monkeypatch):
    deliveries = []
    monkeypatch.setattr(routes, "_send_password_reset_email", lambda email, url: deliveries.append((email, url)))

    result = routes.my_dashboard_forgot_password(
        routes.DashboardForgotPasswordRequest(email="missing@example.com")
    )

    assert result == {"ok": True, "message": routes.DASHBOARD_PASSWORD_RESET_MESSAGE}
    assert deliveries == []

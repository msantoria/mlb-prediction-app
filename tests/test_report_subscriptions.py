import base64
import datetime as dt

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from mlb_app import my_dashboard_routes as routes
from mlb_app.admin_access import DashboardPrincipal, USER_CAPABILITIES
from mlb_app.database import (
    AppDashboardFolder,
    AppDashboardItem,
    AppReportSubscription,
    AppUser,
    Base,
)
from mlb_app.report_subscriptions import (
    SavedReportCsvSnapshot,
    build_saved_report_csv,
    dispatch_report_subscriptions,
    send_report_update_email,
)


@pytest.fixture()
def session_factory():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


def _seed_saved_report(session_factory):
    with session_factory() as session:
        user = AppUser(email="owner@example.com", username="owner")
        session.add(user)
        session.flush()
        folder = AppDashboardFolder(user_id=user.id, folder_name="Daily")
        session.add(folder)
        session.flush()
        item = AppDashboardItem(
            user_id=user.id,
            folder_id=folder.id,
            source_tab="my-dashboard",
            source_type="report_view",
            title="Daily Hitters",
            payload_json={
                "definition": {
                    "report_type": "all_active_hitters",
                    "selected_fields": ["full_name"],
                    "filters": {},
                    "sort": {"by": "model_score", "direction": "desc"},
                },
                "snapshot": {"generated_for_date": "2026-08-29"},
            },
        )
        session.add(item)
        session.commit()
        return user.id, item.id


def _executor(state, calls=None):
    def execute(request):
        if calls is not None:
            calls.append(dict(request))
        return {
            "records": [{"full_name": state["name"]}],
            "totalSize": 1,
            "page_info": {"has_next_page": False},
            "object_info": {
                "fields": [{"name": "full_name", "label": "Full Name"}],
            },
        }
    return execute


def _principal(user_id, email="owner@example.com"):
    now = dt.datetime(2026, 8, 29, 12, 0, 0)
    return DashboardPrincipal(
        user_id=user_id,
        email=email,
        username="owner",
        role="user",
        capabilities=USER_CAPABILITIES,
        session_id=1,
        session_created_at=now,
        session_expires_at=now + dt.timedelta(days=1),
    )


def test_saved_report_csv_reuses_saved_definition_and_all_row_page_size(session_factory):
    _, item_id = _seed_saved_report(session_factory)
    calls = []
    with session_factory() as session:
        item = session.get(AppDashboardItem, item_id)
        snapshot = build_saved_report_csv(item, _executor({"name": "One"}, calls))

    assert calls[0]["page_size"] == routes.MAX_PAGE_SIZE
    assert calls[0]["page_number"] == 1
    assert snapshot.csv_bytes == b"Full Name\r\nOne\r\n"
    assert snapshot.filename == "daily-hitters-2026-08-29-all-rows.csv"
    assert snapshot.row_count == 1
    assert len(snapshot.fingerprint) == 64


def test_subscription_sends_once_per_changed_fingerprint(session_factory):
    user_id, item_id = _seed_saved_report(session_factory)
    state = {"name": "One"}
    with session_factory() as session:
        item = session.get(AppDashboardItem, item_id)
        baseline = build_saved_report_csv(item, _executor(state))
        session.add(AppReportSubscription(
            user_id=user_id,
            dashboard_item_id=item_id,
            enabled=True,
            last_fingerprint=baseline.fingerprint,
        ))
        session.commit()

    sent = []
    unchanged = dispatch_report_subscriptions(
        session_factory,
        execute_report=_executor(state),
        send_email=lambda *args: sent.append(args),
    )
    assert unchanged["unchanged"] == 1
    assert sent == []

    state["name"] = "Two"
    changed = dispatch_report_subscriptions(
        session_factory,
        execute_report=_executor(state),
        send_email=lambda *args: sent.append(args),
    )
    repeated = dispatch_report_subscriptions(
        session_factory,
        execute_report=_executor(state),
        send_email=lambda *args: sent.append(args),
    )

    assert changed["sent"] == 1
    assert repeated["unchanged"] == 1
    assert len(sent) == 1
    assert sent[0][0] == "owner@example.com"
    assert sent[0][1] == "Daily Hitters"
    assert sent[0][2].csv_bytes == b"Full Name\r\nTwo\r\n"


def test_failed_email_keeps_old_fingerprint_and_retries(session_factory):
    user_id, item_id = _seed_saved_report(session_factory)
    with session_factory() as session:
        session.add(AppReportSubscription(
            user_id=user_id,
            dashboard_item_id=item_id,
            enabled=True,
            last_fingerprint="old-fingerprint",
        ))
        session.commit()

    failed = dispatch_report_subscriptions(
        session_factory,
        execute_report=_executor({"name": "Changed"}),
        send_email=lambda *_args: (_ for _ in ()).throw(RuntimeError("mail unavailable")),
    )
    with session_factory() as session:
        subscription = session.query(AppReportSubscription).one()
        assert subscription.last_fingerprint == "old-fingerprint"
        assert subscription.last_error == "mail unavailable"
        assert subscription.last_sent_at is None

    sent = []
    retried = dispatch_report_subscriptions(
        session_factory,
        execute_report=_executor({"name": "Changed"}),
        send_email=lambda *args: sent.append(args),
    )
    assert failed["failed"] == 1
    assert retried["sent"] == 1
    assert len(sent) == 1


def test_unsubscribed_report_is_skipped(session_factory):
    user_id, item_id = _seed_saved_report(session_factory)
    with session_factory() as session:
        session.add(AppReportSubscription(
            user_id=user_id,
            dashboard_item_id=item_id,
            enabled=False,
            last_fingerprint="old",
        ))
        session.commit()

    summary = dispatch_report_subscriptions(
        session_factory,
        execute_report=lambda _request: pytest.fail("disabled report was executed"),
        send_email=lambda *_args: pytest.fail("disabled report sent email"),
    )
    assert summary == {"checked": 0, "unchanged": 0, "sent": 0, "failed": 0, "baselined": 0}


def test_subscription_routes_are_owner_scoped_and_create_a_silent_baseline(
    session_factory, monkeypatch
):
    user_id, item_id = _seed_saved_report(session_factory)
    monkeypatch.setattr(routes, "session_factory", lambda: session_factory)
    monkeypatch.setenv("RESEND_API_KEY", "test-key")
    monkeypatch.setenv("REPORT_EMAIL_FROM", "reports@mlbgpt.com")
    baseline = SavedReportCsvSnapshot(
        csv_bytes=b"Full Name\r\nOne\r\n",
        fingerprint="a" * 64,
        filename="daily-hitters.csv",
        report_date="2026-08-29",
        row_count=1,
    )
    monkeypatch.setattr(routes, "build_saved_report_csv", lambda _item, _execute: baseline)

    created = routes.my_dashboard_report_subscription_update(
        item_id,
        routes.ReportSubscriptionUpdate(enabled=True),
        _principal(user_id),
    )
    loaded = routes.my_dashboard_report_subscription_get(item_id, _principal(user_id))

    assert created["enabled"] is True
    assert created["recipient_email"] == "owner@example.com"
    assert loaded["enabled"] is True
    with session_factory() as session:
        assert session.query(AppReportSubscription).one().last_fingerprint == "a" * 64

    with pytest.raises(HTTPException) as exc:
        routes.my_dashboard_report_subscription_get(item_id, _principal(999, "other@example.com"))
    assert exc.value.status_code == 404

    disabled = routes.my_dashboard_report_subscription_update(
        item_id,
        routes.ReportSubscriptionUpdate(enabled=False),
        _principal(user_id),
    )
    assert disabled["enabled"] is False


def test_subscribe_fails_closed_without_email_configuration(
    session_factory, monkeypatch
):
    user_id, item_id = _seed_saved_report(session_factory)
    monkeypatch.setattr(routes, "session_factory", lambda: session_factory)
    monkeypatch.delenv("RESEND_API_KEY", raising=False)
    monkeypatch.delenv("REPORT_EMAIL_FROM", raising=False)

    with pytest.raises(HTTPException) as exc:
        routes.my_dashboard_report_subscription_update(
            item_id,
            routes.ReportSubscriptionUpdate(enabled=True),
            _principal(user_id),
        )
    assert exc.value.status_code == 503


def test_resend_delivery_attaches_csv_and_uses_fingerprint_idempotency(monkeypatch):
    monkeypatch.setenv("RESEND_API_KEY", "secret")
    monkeypatch.setenv("REPORT_EMAIL_FROM", "MLBGPT <reports@mlbgpt.com>")
    request = {}

    class Response:
        def raise_for_status(self):
            return None

    def post(url, **kwargs):
        request.update({"url": url, **kwargs})
        return Response()

    snapshot = SavedReportCsvSnapshot(
        csv_bytes=b"Name\r\nOne\r\n",
        fingerprint="b" * 64,
        filename="daily.csv",
        report_date="2026-08-29",
        row_count=1,
    )
    send_report_update_email(
        "owner@example.com",
        "Daily Report",
        snapshot,
        42,
        post=post,
    )

    assert request["url"] == "https://api.resend.com/emails"
    assert request["headers"]["Idempotency-Key"] == f"report-subscription/42/{'b' * 64}"
    assert request["json"]["to"] == ["owner@example.com"]
    assert base64.b64decode(request["json"]["attachments"][0]["content"]) == snapshot.csv_bytes

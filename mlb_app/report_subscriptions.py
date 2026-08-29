"""Saved-report change detection and email delivery."""

from __future__ import annotations

import base64
import datetime as dt
import hashlib
import html
import os
from dataclasses import dataclass
from typing import Any, Callable, Dict, Optional

import requests

from .database import AppDashboardItem, AppReportSubscription, AppUser
from .my_dashboard_report_query import MAX_PAGE_SIZE
from .report_csv import safe_csv_filename, stream_paginated_csv
from .saved_report_analysis import (
    execution_request_from_item,
    resolve_owned_saved_reports,
)


@dataclass(frozen=True)
class SavedReportCsvSnapshot:
    csv_bytes: bytes
    fingerprint: str
    filename: str
    report_date: str
    row_count: int


def utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)


def email_delivery_configured() -> bool:
    return bool(
        os.getenv("RESEND_API_KEY", "").strip()
        and os.getenv("REPORT_EMAIL_FROM", "").strip()
    )


def owned_executable_report(session, user_id: int, item_id: int) -> AppDashboardItem:
    try:
        item = resolve_owned_saved_reports(session, user_id, [item_id])[0]
    except LookupError as exc:
        raise LookupError("Saved report not found") from exc
    execution_request_from_item(item)
    return item


def build_saved_report_csv(
    item: AppDashboardItem,
    execute_report: Callable[[Dict[str, Any]], Dict[str, Any]],
) -> SavedReportCsvSnapshot:
    """Re-execute an existing saved definition through the canonical report engine."""

    request = execution_request_from_item(item)
    request.update({
        "page_number": 1,
        "page_size": MAX_PAGE_SIZE,
        "include_metadata": True,
    })
    first_result = execute_report(dict(request))

    def fetch_page(page_number: int) -> Dict[str, Any]:
        return execute_report({**request, "page_number": page_number})

    csv_text = "".join(stream_paginated_csv(
        first_result,
        fetch_page,
        selected_fields=request.get("selected_fields"),
    ))
    csv_bytes = csv_text.encode("utf-8")
    report_date = str(request.get("as_of_date") or "current")[:10]
    filename = f"{safe_csv_filename(item.title)}-{safe_csv_filename(report_date)}-all-rows.csv"
    total = first_result.get("totalSize", first_result.get("total_count", 0))
    try:
        row_count = int(total)
    except (TypeError, ValueError):
        row_count = len(first_result.get("records") or first_result.get("items") or [])
    return SavedReportCsvSnapshot(
        csv_bytes=csv_bytes,
        fingerprint=hashlib.sha256(csv_bytes).hexdigest(),
        filename=filename,
        report_date=report_date,
        row_count=row_count,
    )


def send_report_update_email(
    recipient: str,
    report_title: str,
    snapshot: SavedReportCsvSnapshot,
    subscription_id: int,
    *,
    post: Callable[..., Any] = requests.post,
) -> None:
    api_key = os.getenv("RESEND_API_KEY", "").strip()
    sender = os.getenv("REPORT_EMAIL_FROM", "").strip()
    if not api_key or not sender:
        raise RuntimeError("Report email delivery is not configured")
    app_url = os.getenv("REPORT_APP_URL", "").strip().rstrip("/") or "https://mlbgpt.com"
    dashboard_url = app_url + "/my-dashboard"
    detected_at = utcnow().isoformat(timespec="seconds") + "Z"
    subject_title = " ".join(str(report_title).splitlines()).strip() or "Saved report"
    escaped_title = html.escape(subject_title)
    escaped_url = html.escape(dashboard_url, quote=True)
    attachment_content = base64.b64encode(snapshot.csv_bytes).decode("ascii")
    if len(attachment_content) > 40 * 1024 * 1024:
        raise RuntimeError("Report CSV exceeds the email attachment size limit")
    response = post(
        "https://api.resend.com/emails",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Idempotency-Key": f"report-subscription/{subscription_id}/{snapshot.fingerprint}",
        },
        json={
            "from": sender,
            "to": [recipient],
            "subject": f"[MLBGPT] {subject_title} updated",
            "html": (
                f"<h1>{escaped_title} updated</h1>"
                f"<p>MLB date: {html.escape(snapshot.report_date)}</p>"
                f"<p>Rows: {snapshot.row_count}</p>"
                f"<p>Detected: {detected_at}</p>"
                f'<p><a href="{escaped_url}">Open MyDashboard</a></p>'
                "<p>The complete updated report is attached as a CSV.</p>"
            ),
            "attachments": [{
                "filename": snapshot.filename,
                "content": attachment_content,
            }],
        },
        timeout=30,
    )
    response.raise_for_status()


def default_report_executor(request: Dict[str, Any]) -> Dict[str, Any]:
    # Imported lazily to keep route registration free of a circular dependency.
    from .my_dashboard_routes import DashboardPlayerReportRequest, my_dashboard_player_report_query

    return my_dashboard_player_report_query(
        DashboardPlayerReportRequest.model_validate(request)
    )


def dispatch_report_subscriptions(
    session_factory,
    *,
    execute_report: Callable[[Dict[str, Any]], Dict[str, Any]] = default_report_executor,
    send_email: Callable[[str, str, SavedReportCsvSnapshot, int], None] = send_report_update_email,
) -> Dict[str, int]:
    """Check enabled subscriptions independently after a canonical refresh."""

    with session_factory() as session:
        subscription_ids = [
            row[0]
            for row in session.query(AppReportSubscription.id)
            .filter(AppReportSubscription.enabled.is_(True))
            .order_by(AppReportSubscription.id.asc())
            .all()
        ]

    summary = {"checked": 0, "unchanged": 0, "sent": 0, "failed": 0, "baselined": 0}
    for subscription_id in subscription_ids:
        try:
            with session_factory() as session:
                subscription = (
                    session.query(AppReportSubscription)
                    .filter(
                        AppReportSubscription.id == subscription_id,
                        AppReportSubscription.enabled.is_(True),
                    )
                    .with_for_update(skip_locked=True)
                    .first()
                )
                if subscription is None:
                    continue
                item = session.query(AppDashboardItem).filter(
                    AppDashboardItem.id == subscription.dashboard_item_id,
                    AppDashboardItem.user_id == subscription.user_id,
                ).first()
                user = session.query(AppUser).filter(AppUser.id == subscription.user_id).first()
                if item is None or user is None:
                    subscription.enabled = False
                    subscription.last_error = "Saved report or account is unavailable"
                    subscription.updated_at = utcnow()
                    session.commit()
                    summary["failed"] += 1
                    continue

                snapshot = build_saved_report_csv(item, execute_report)
                checked_at = utcnow()
                summary["checked"] += 1
                subscription.last_checked_at = checked_at
                if subscription.last_fingerprint is None:
                    subscription.last_fingerprint = snapshot.fingerprint
                    subscription.last_error = None
                    subscription.updated_at = checked_at
                    session.commit()
                    summary["baselined"] += 1
                    continue
                if subscription.last_fingerprint == snapshot.fingerprint:
                    subscription.last_error = None
                    subscription.updated_at = checked_at
                    session.commit()
                    summary["unchanged"] += 1
                    continue

                send_email(user.email, item.title, snapshot, subscription.id)
                subscription.last_fingerprint = snapshot.fingerprint
                subscription.last_sent_at = checked_at
                subscription.last_error = None
                subscription.updated_at = checked_at
                session.commit()
                summary["sent"] += 1
        except Exception as exc:
            summary["failed"] += 1
            try:
                with session_factory() as error_session:
                    subscription = error_session.query(AppReportSubscription).filter(
                        AppReportSubscription.id == subscription_id
                    ).first()
                    if subscription is not None:
                        subscription.last_checked_at = utcnow()
                        subscription.last_error = str(exc)[:2000]
                        subscription.updated_at = utcnow()
                        error_session.commit()
            except Exception:
                # Keep processing other subscriptions even if error persistence fails.
                continue
    return summary

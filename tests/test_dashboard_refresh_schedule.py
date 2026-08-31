import datetime as dt

from mlb_app import dashboard_projection_operator
from mlb_app import database
from mlb_app import my_dashboard_dataset_runtime
from mlb_app import report_subscriptions
from scripts import run_refresh_job


class SessionContext:
    def __enter__(self):
        return object()

    def __exit__(self, *_args):
        return False


def test_worker_runs_canonical_refresh_after_upstream_job(monkeypatch):
    calls = {}
    monkeypatch.setattr(run_refresh_job, "RUN_CANONICAL_DASHBOARD_REFRESH", True)
    monkeypatch.setattr(my_dashboard_dataset_runtime, "mlb_business_date", lambda: dt.date(2026, 7, 23))
    monkeypatch.setattr(database, "get_engine", lambda _url: object())
    monkeypatch.setattr(database, "create_tables", lambda _engine: None)
    monkeypatch.setattr(database, "get_session", lambda _engine: lambda: SessionContext())

    def refresh(_session, *, target_date):
        calls["target_date"] = target_date
        return {
            "run_id": 23,
            "population": {"active_count": 787},
            "current_row_count": 787,
            "projection": {
                "field_coverage": {
                    "hitter": {
                        "row_count": 379,
                        "fields": {"model_score": {"coverage": 0.75}},
                    },
                },
            },
        }

    monkeypatch.setattr(dashboard_projection_operator, "run_canonical_projection_refresh", refresh)
    monkeypatch.setattr(
        report_subscriptions,
        "dispatch_report_subscriptions",
        lambda _factory: calls.setdefault(
            "subscription_summary",
            {"checked": 1, "unchanged": 1, "sent": 0, "failed": 0, "baselined": 0},
        ),
    )
    run_refresh_job._run_canonical_dashboard_refresh()

    assert calls["target_date"] == dt.date(2026, 7, 23)
    assert calls["subscription_summary"]["checked"] == 1

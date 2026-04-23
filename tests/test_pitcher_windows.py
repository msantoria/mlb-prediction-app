import datetime

from mlb_app.pitcher_windows import fetch_pitcher_metrics_for_window


def test_returns_empty_for_missing_pitcher_id():
    result = fetch_pitcher_metrics_for_window(
        pitcher_id=0,
        target_date=datetime.date(2026, 4, 22),
        window_name="last_365_days",
    )
    assert result == {}


def test_unknown_window_returns_empty():
    result = fetch_pitcher_metrics_for_window(
        pitcher_id=123,
        target_date=datetime.date(2026, 4, 22),
        window_name="unknown_window",
    )
    assert result == {}

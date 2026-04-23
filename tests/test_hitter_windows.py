import datetime

from mlb_app.hitter_windows import fetch_player_splits_for_window


def test_returns_empty_for_no_players():
    result = fetch_player_splits_for_window(
        player_ids=[],
        season=2026,
        window_name="current_season",
        target_date=datetime.date(2026, 4, 22),
    )
    assert result == []


def test_unknown_window_returns_empty():
    result = fetch_player_splits_for_window(
        player_ids=[1],
        season=2026,
        window_name="unknown_window",
        target_date=datetime.date(2026, 4, 22),
    )
    assert result == []

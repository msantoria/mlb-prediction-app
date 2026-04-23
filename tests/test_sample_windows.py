import datetime

from mlb_app.sample_windows import (
    build_sample_metadata,
    get_window_definition,
    get_window_start_date,
)


def test_get_window_definition_known_window():
    result = get_window_definition("last_30_days")
    assert result["window_type"] == "rolling"
    assert result["days"] == 30
    assert result["description"] == "Rolling last 30 days"


def test_get_window_start_date_for_rolling_window():
    target_date = datetime.date(2026, 4, 22)
    result = get_window_start_date(target_date, "last_90_days")
    assert result == "2026-01-22"


def test_build_sample_metadata_contract():
    result = build_sample_metadata(
        window_name="current_season",
        sample_size=120,
        sample_blend_policy="single_window_v1",
        stabilizer_window=None,
    )

    assert result["sample_window"] == "current_season"
    assert result["sample_family"] == "season"
    assert result["sample_description"] == "Current season to date"
    assert result["sample_days"] is None
    assert result["sample_size"] == 120
    assert result["sample_blend_policy"] == "single_window_v1"
    assert result["stabilizer_window"] is None

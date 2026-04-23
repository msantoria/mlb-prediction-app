from mlb_app.sample_blending import (
    HITTER_BLEND_WEIGHTS,
    PITCHER_BLEND_WEIGHTS,
    blend_metric_dict,
    weighted_average,
)


def test_weighted_average_ignores_none_values():
    values = {
        "last_30_days": 0.300,
        "last_90_days": None,
        "current_season": 0.250,
    }
    weights = {
        "last_30_days": 0.50,
        "last_90_days": 0.30,
        "current_season": 0.20,
    }

    result = weighted_average(values, weights)
    expected = (0.300 * 0.50 + 0.250 * 0.20) / (0.50 + 0.20)
    assert round(result, 6) == round(expected, 6)


def test_blend_metric_dict_blends_shared_keys():
    metric_windows = {
        "last_30_days": {"k_rate": 0.22, "bb_rate": 0.08},
        "last_90_days": {"k_rate": 0.24, "bb_rate": 0.09},
        "current_season": {"k_rate": 0.23, "bb_rate": 0.10},
    }

    result = blend_metric_dict(metric_windows, HITTER_BLEND_WEIGHTS)

    assert "k_rate" in result
    assert "bb_rate" in result
    assert result["k_rate"] is not None
    assert result["bb_rate"] is not None


def test_pitcher_blend_weights_exist_for_expected_windows():
    assert PITCHER_BLEND_WEIGHTS["last_30_days"] == 0.35
    assert PITCHER_BLEND_WEIGHTS["last_90_days"] == 0.35
    assert PITCHER_BLEND_WEIGHTS["last_365_days"] == 0.30

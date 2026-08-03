from types import SimpleNamespace

import pytest

from mlb_app.scoring import _arsenal_vs_batter, _batter_advantage, _pitcher_advantage


def _row(**values):
    return SimpleNamespace(**values)


def test_pitcher_advantage_accepts_fractional_or_whole_percent_rates() -> None:
    fractional = _row(
        k_pct=0.247,
        bb_pct=0.081,
        hard_hit_pct=0.386,
        xwoba=0.318,
        avg_velocity=94.2,
    )
    whole_percent = _row(
        k_pct=24.7,
        bb_pct=8.1,
        hard_hit_pct=38.6,
        xwoba=0.318,
        avg_velocity=94.2,
    )

    assert _pitcher_advantage(whole_percent) == pytest.approx(
        _pitcher_advantage(fractional)
    )


def test_batter_advantage_accepts_fractional_or_whole_percent_rates() -> None:
    fractional = _row(
        avg_exit_velocity=90.1,
        hard_hit_pct=0.421,
        barrel_pct=0.093,
        k_pct=0.201,
        bb_pct=0.088,
        batting_avg=0.265,
    )
    whole_percent = _row(
        avg_exit_velocity=90.1,
        hard_hit_pct=42.1,
        barrel_pct=9.3,
        k_pct=20.1,
        bb_pct=8.8,
        batting_avg=0.265,
    )

    assert _batter_advantage(whole_percent) == pytest.approx(
        _batter_advantage(fractional)
    )


def test_arsenal_score_accepts_fractional_or_whole_percent_rates() -> None:
    fractional = [
        _row(
            usage_pct=0.42,
            whiff_pct=0.285,
            strikeout_pct=0.248,
            rv_per_100=-0.4,
            xwoba=0.301,
        )
    ]
    whole_percent = [
        _row(
            usage_pct=42.0,
            whiff_pct=28.5,
            strikeout_pct=24.8,
            rv_per_100=-0.4,
            xwoba=0.301,
        )
    ]

    assert _arsenal_vs_batter(
        whole_percent, _row(on_base_pct=32.6)
    ) == pytest.approx(
        _arsenal_vs_batter(fractional, _row(on_base_pct=0.326))
    )

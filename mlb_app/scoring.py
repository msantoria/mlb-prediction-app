"""
Matchup scoring engine.

Core concept: for each pitch type in the pitcher's arsenal, weight their
effectiveness (whiff%, K%, RV/100, xwOBA) against the batter's performance
vs that handedness split. Combine into a composite advantage score and
convert to win probability using a logistic transform.
"""

from __future__ import annotations

import math
from typing import Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from .db_utils import (
    get_pitcher_aggregate,
    get_batter_aggregate,
    get_pitch_arsenal,
    get_player_split,
    get_team_split,
)


# ---------------------------------------------------------------------------
# Weight configuration
# ---------------------------------------------------------------------------

PITCHER_WEIGHTS = {
    "k_pct": 2.0,
    "bb_pct": -1.5,
    "hard_hit_pct": -1.5,
    "xwoba": -2.0,
    "avg_velocity": 0.05,
}

BATTER_WEIGHTS = {
    "avg_exit_velocity": 0.03,
    "hard_hit_pct": 1.5,
    "barrel_pct": 2.0,
    "k_pct": -1.5,
    "bb_pct": 0.5,
    "batting_avg": 2.0,
}

ARSENAL_WEIGHTS = {
    "whiff_pct": 1.5,
    "strikeout_pct": 1.5,
    "rv_per_100": -1.0,
    "xwoba": -2.0,
}

HOME_FIELD_LOGIT = 0.12


# ---------------------------------------------------------------------------
# League-average baselines (2025 approximations)
# ---------------------------------------------------------------------------

PITCHER_BASELINE = {
    "k_pct": 0.225,
    "bb_pct": 0.085,
    "hard_hit_pct": 0.37,
    "xwoba": 0.315,
    "avg_velocity": 93.5,
}

BATTER_BASELINE = {
    "avg_exit_velocity": 88.5,
    "hard_hit_pct": 0.37,
    "barrel_pct": 0.075,
    "k_pct": 0.225,
    "bb_pct": 0.085,
    "batting_avg": 0.248,
}

ARSENAL_BASELINE = {
    "whiff_pct": 0.25,
    "strikeout_pct": 0.225,
    "rv_per_100": 0.0,
    "xwoba": 0.315,
}


# ---------------------------------------------------------------------------
# Ballpark run-factor lookup (neutral = 1.0)
# ---------------------------------------------------------------------------

PARK_FACTORS: Dict[str, float] = {
    "Coors Field": 1.30,
    "Great American Ball Park": 1.15,
    "Yankee Stadium": 1.10,
    "Citizens Bank Park": 1.04,
    "Fenway Park": 1.05,
    "Rogers Centre": 1.03,
    "Globe Life Field": 1.03,
    "American Family Field": 1.01,
    "Guaranteed Rate Field": 1.01,
    "Minute Maid Park": 1.01,
    "Busch Stadium": 0.99,
    "Wrigley Field": 0.99,
    "Truist Park": 0.99,
    "Camden Yards": 0.99,
    "Chase Field": 0.98,
    "Citi Field": 0.98,
    "Nationals Park": 0.98,
    "Progressive Field": 0.97,
    "PNC Park": 0.97,
    "Target Field": 0.97,
    "Angel Stadium": 0.97,
    "Dodger Stadium": 0.96,
    "Comerica Park": 0.95,
    "Oracle Park": 0.95,
    "loanDepot park": 0.94,
    "Oakland Coliseum": 0.93,
    "Kauffman Stadium": 0.92,
    "Petco Park": 0.90,
    "Tropicana Field": 0.88,
    "T-Mobile Park": 0.88,
}


def get_park_factor(venue_name: Optional[str]) -> float:
    if not venue_name:
        return 1.0
    return PARK_FACTORS.get(venue_name, 1.0)


# ---------------------------------------------------------------------------
# Core math
# ---------------------------------------------------------------------------

def _normalize(value: Optional[float], baseline: float) -> float:
    if value is None:
        return 0.0
    return value - baseline


def _logistic(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-x))


def _pitcher_advantage(agg) -> float:
    if agg is None:
        return 0.0
    score = 0.0
    for field, weight in PITCHER_WEIGHTS.items():
        val = getattr(agg, field, None)
        baseline = PITCHER_BASELINE.get(field, 0.0)
        score += weight * _normalize(val, baseline)
    return score


def _batter_advantage(agg) -> float:
    if agg is None:
        return 0.0
    score = 0.0
    for field, weight in BATTER_WEIGHTS.items():
        val = getattr(agg, field, None)
        baseline = BATTER_BASELINE.get(field, 0.0)
        score += weight * _normalize(val, baseline)
    return score


def _arsenal_vs_batter(arsenal: List, batter_split) -> float:
    if not arsenal:
        return 0.0

    batter_obp = None
    if batter_split:
        batter_obp = getattr(batter_split, "on_base_pct", None)

    score = 0.0
    for pitch in arsenal:
        usage = pitch.usage_pct or 0.0
        pitch_score = 0.0
        for field, weight in ARSENAL_WEIGHTS.items():
            val = getattr(pitch, field, None)
            baseline = ARSENAL_BASELINE.get(field, 0.0)
            pitch_score += weight * _normalize(val, baseline)
        score += usage * pitch_score

    if batter_obp is not None:
        score -= (batter_obp - 0.320) * 2.0

    return score


def _best_pitcher_agg(session: Session, pitcher_id: int, season: int):
    """Return best available aggregate, trying 90d then prior seasons."""
    agg = get_pitcher_aggregate(session, pitcher_id, "90d")
    if agg:
        return agg
    for window in [str(season)] + [str(y) for y in range(season - 1, season - 4, -1)]:
        agg = get_pitcher_aggregate(session, pitcher_id, window)
        if agg:
            return agg
    return None


def _best_arsenal(session: Session, pitcher_id: int, season: int):
    """Return best available arsenal, trying current then prior seasons."""
    arsenal = get_pitch_arsenal(session, pitcher_id, season)
    if arsenal:
        return arsenal
    for yr in range(season - 1, season - 3, -1):
        arsenal = get_pitch_arsenal(session, pitcher_id, yr)
        if arsenal:
            return arsenal
    return []


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def score_pitcher_vs_lineup(
    session: Session,
    pitcher_id: int,
    opposing_team_id: int,
    season: int,
    pitcher_throws: str = "R",
) -> float:
    agg = _best_pitcher_agg(session, pitcher_id, season)
    arsenal = _best_arsenal(session, pitcher_id, season)

    split_key = "vsR" if pitcher_throws == "R" else "vsL"
    team_split = get_team_split(session, opposing_team_id, season, split_key)

    return _pitcher_advantage(agg) + _arsenal_vs_batter(arsenal, team_split)


def compute_win_probability(
    session: Session,
    home_pitcher_id: int,
    away_pitcher_id: int,
    home_team_id: int,
    away_team_id: int,
    season: int,
    home_pitcher_throws: str = "R",
    away_pitcher_throws: str = "R",
) -> Tuple[float, float]:
    home_score = score_pitcher_vs_lineup(
        session, home_pitcher_id, away_team_id, season, home_pitcher_throws
    )
    away_score = score_pitcher_vs_lineup(
        session, away_pitcher_id, home_team_id, season, away_pitcher_throws
    )

    net_logit = (home_score - away_score) + HOME_FIELD_LOGIT
    home_win_prob = _logistic(net_logit)
    return round(home_win_prob, 4), round(1.0 - home_win_prob, 4)


def score_individual_matchup(
    session: Session,
    pitcher_id: int,
    batter_id: int,
    season: int,
    pitcher_throws: str = "R",
) -> Dict[str, float]:
    pitcher_agg = _best_pitcher_agg(session, pitcher_id, season)
    batter_agg = get_batter_aggregate(session, batter_id, "90d")
    arsenal = _best_arsenal(session, pitcher_id, season)

    split_key = "vsR" if pitcher_throws == "R" else "vsL"
    batter_split = get_player_split(session, batter_id, season, split_key)

    p_score = _pitcher_advantage(pitcher_agg)
    b_score = _batter_advantage(batter_agg)
    a_score = _arsenal_vs_batter(arsenal, batter_split)
    net = (p_score + a_score) - b_score

    return {
        "pitcher_advantage": round(p_score + a_score, 4),
        "batter_advantage": round(b_score, 4),
        "net_score": round(net, 4),
        "pitcher_win_prob": round(_logistic(net), 4),
    }

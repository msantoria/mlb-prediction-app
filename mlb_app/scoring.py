"""
Matchup scoring engine.

Core concept: for each pitch type in the pitcher's arsenal, weight their
effectiveness (whiff%, K%, RV/100, xwOBA) against the batter's performance
vs that handedness split. Combine into a composite advantage score and
convert to win probability using a logistic transform.

The formula is intentionally transparent so you can tune weights as more
data accumulates.
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
# Ballpark factors (static, 2024/2025 calibrated)
#
# run_factor > 1.0  → run-friendly park (boosts home win prob slightly)
# run_factor < 1.0  → pitcher-friendly park (suppresses home win prob slightly)
# Logit adjustment = (run_factor - 1.0) * 0.30, capped at ±0.05
# ---------------------------------------------------------------------------

PARK_FACTORS: Dict[str, Dict[str, float]] = {
    # AL East
    "Yankee Stadium":           {"hr_factor": 1.12, "run_factor": 1.05},
    "Fenway Park":              {"hr_factor": 0.95, "run_factor": 1.03},
    "Camden Yards":             {"hr_factor": 1.08, "run_factor": 1.04},
    "Rogers Centre":            {"hr_factor": 1.10, "run_factor": 1.06},
    "Tropicana Field":          {"hr_factor": 0.94, "run_factor": 0.97},
    # AL Central
    "Guaranteed Rate Field":    {"hr_factor": 1.09, "run_factor": 1.04},
    "Progressive Field":        {"hr_factor": 0.96, "run_factor": 0.98},
    "Comerica Park":            {"hr_factor": 0.88, "run_factor": 0.95},
    "Kauffman Stadium":         {"hr_factor": 0.93, "run_factor": 0.97},
    "Target Field":             {"hr_factor": 0.97, "run_factor": 0.99},
    # AL West
    "Minute Maid Park":         {"hr_factor": 1.06, "run_factor": 1.03},
    "Angel Stadium":            {"hr_factor": 0.97, "run_factor": 0.99},
    "Oakland Coliseum":         {"hr_factor": 0.85, "run_factor": 0.93},
    "T-Mobile Park":            {"hr_factor": 0.91, "run_factor": 0.96},
    "Globe Life Field":         {"hr_factor": 1.04, "run_factor": 1.02},
    # NL East
    "Truist Park":              {"hr_factor": 1.05, "run_factor": 1.02},
    "Citi Field":               {"hr_factor": 0.90, "run_factor": 0.96},
    "Citizens Bank Park":       {"hr_factor": 1.11, "run_factor": 1.06},
    "Nationals Park":           {"hr_factor": 1.02, "run_factor": 1.01},
    "loanDepot park":           {"hr_factor": 0.87, "run_factor": 0.94},
    # NL Central
    "Wrigley Field":            {"hr_factor": 1.07, "run_factor": 1.03},
    "Great American Ball Park": {"hr_factor": 1.18, "run_factor": 1.09},
    "American Family Field":    {"hr_factor": 1.06, "run_factor": 1.03},
    "PNC Park":                 {"hr_factor": 0.92, "run_factor": 0.96},
    "Busch Stadium":            {"hr_factor": 0.96, "run_factor": 0.98},
    # NL West
    "Coors Field":              {"hr_factor": 1.25, "run_factor": 1.15},
    "Dodger Stadium":           {"hr_factor": 0.98, "run_factor": 0.99},
    "Petco Park":               {"hr_factor": 0.88, "run_factor": 0.94},
    "Oracle Park":              {"hr_factor": 0.86, "run_factor": 0.93},
    "Chase Field":              {"hr_factor": 1.08, "run_factor": 1.04},
}

# Neutral factor used when venue is unknown
_NEUTRAL_PARK_FACTOR: Dict[str, float] = {"hr_factor": 1.0, "run_factor": 1.0}

# Scale factor: how much a 1-unit deviation in run_factor shifts the logit.
# At run_factor=1.15 (Coors) this yields +0.045 ≈ +0.03 win-prob points.
_PARK_LOGIT_SCALE = 0.30
# Hard cap so no single park swings the model more than ±0.05 logit units.
_PARK_LOGIT_CAP = 0.05


def get_park_factor(venue_name: Optional[str]) -> Dict[str, float]:
    """Return the park-factor dict for *venue_name*, or a neutral dict if unknown."""
    if venue_name is None:
        return _NEUTRAL_PARK_FACTOR
    return PARK_FACTORS.get(venue_name, _NEUTRAL_PARK_FACTOR)


def park_logit_adjustment(venue_name: Optional[str]) -> float:
    """
    Compute the logit adjustment for a given venue.

    Positive values favour the home team (run-friendly park), negative values
    favour the away team (pitcher-friendly park).  The adjustment is capped at
    ±_PARK_LOGIT_CAP so extreme parks cannot dominate the model.
    """
    pf = get_park_factor(venue_name)
    raw = (pf["run_factor"] - 1.0) * _PARK_LOGIT_SCALE
    return max(-_PARK_LOGIT_CAP, min(_PARK_LOGIT_CAP, raw))


# ---------------------------------------------------------------------------
# Weight configuration (tune these)
# ---------------------------------------------------------------------------

# Pitcher aggregate weights (higher = better pitcher performance)
PITCHER_WEIGHTS = {
    "k_pct": 2.0,
    "bb_pct": -1.5,       # walks hurt
    "hard_hit_pct": -1.5,
    "xwoba": -2.0,         # lower xwOBA against = better
    "avg_velocity": 0.05,  # small bonus for velo
}

# Batter aggregate weights (higher = better batter performance vs pitcher)
BATTER_WEIGHTS = {
    "avg_exit_velocity": 0.03,
    "hard_hit_pct": 1.5,
    "barrel_pct": 2.0,
    "k_pct": -1.5,
    "bb_pct": 0.5,
    "batting_avg": 2.0,
}

# Arsenal matchup weights
ARSENAL_WEIGHTS = {
    "whiff_pct": 1.5,
    "strikeout_pct": 1.5,
    "rv_per_100": -1.0,   # negative RV/100 = good for pitcher
    "xwoba": -2.0,
}

# Home-field advantage logit bump
HOME_FIELD_LOGIT = 0.12


# ---------------------------------------------------------------------------
# Stat normalization baselines (league average 2025 approximations)
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
# Core math
# ---------------------------------------------------------------------------

def _normalize(value: Optional[float], baseline: float, scale: float = 1.0) -> float:
    """Return (value - baseline) / scale, or 0 if value is None."""
    if value is None:
        return 0.0
    return (value - baseline) / scale


def _logistic(x: float) -> float:
    """Sigmoid function mapping any real to (0, 1)."""
    return 1.0 / (1.0 + math.exp(-x))


def _pitcher_advantage(agg) -> float:
    """Compute pitcher quality score vs league average."""
    if agg is None:
        return 0.0
    score = 0.0
    for field, weight in PITCHER_WEIGHTS.items():
        val = getattr(agg, field, None)
        baseline = PITCHER_BASELINE.get(field, 0.0)
        score += weight * _normalize(val, baseline)
    return score


def _batter_advantage(agg) -> float:
    """Compute batter quality score vs league average."""
    if agg is None:
        return 0.0
    score = 0.0
    for field, weight in BATTER_WEIGHTS.items():
        val = getattr(agg, field, None)
        baseline = BATTER_BASELINE.get(field, 0.0)
        score += weight * _normalize(val, baseline)
    return score


def _arsenal_vs_batter(arsenal: List, batter_split) -> float:
    """
    For each pitch in arsenal, score pitcher effectiveness weighted by usage%.
    batter_split is a PlayerSplit or TeamSplit ORM object (or None).
    """
    if not arsenal:
        return 0.0

    # If we have batter split, use their OBP as a proxy for vulnerability
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

    # Adjust by batter OBP vs baseline (.320 league avg OBP)
    if batter_obp is not None:
        score -= (batter_obp - 0.320) * 2.0

    return score


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
    """
    Compute a raw advantage score for a pitcher facing an opposing lineup.
    Positive = pitcher advantage, negative = batter advantage.
    """
    agg = get_pitcher_aggregate(session, pitcher_id, "90d")
    arsenal = get_pitch_arsenal(session, pitcher_id, season)

    # Determine relevant split for opposing batters
    split_key = "vsR" if pitcher_throws == "R" else "vsL"
    team_split = get_team_split(session, opposing_team_id, season, split_key)

    pitcher_score = _pitcher_advantage(agg)
    arsenal_score = _arsenal_vs_batter(arsenal, team_split)

    return pitcher_score + arsenal_score


def compute_win_probability(
    session: Session,
    home_pitcher_id: int,
    away_pitcher_id: int,
    home_team_id: int,
    away_team_id: int,
    season: int,
    home_pitcher_throws: str = "R",
    away_pitcher_throws: str = "R",
    venue_name: Optional[str] = None,
) -> Tuple[float, float]:
    """
    Return (home_win_prob, away_win_prob) for a game matchup.

    Uses pitcher quality, arsenal effectiveness vs opposing lineup, home field
    advantage, and a small ballpark-factor logit adjustment derived from the
    venue's run_factor.
    """
    home_pitcher_score = score_pitcher_vs_lineup(
        session, home_pitcher_id, away_team_id, season, home_pitcher_throws
    )
    away_pitcher_score = score_pitcher_vs_lineup(
        session, away_pitcher_id, home_team_id, season, away_pitcher_throws
    )

    # Net advantage: home pitcher better = positive logit
    net_logit = (
        (home_pitcher_score - away_pitcher_score)
        + HOME_FIELD_LOGIT
        + park_logit_adjustment(venue_name)
    )

    home_win_prob = _logistic(net_logit)
    away_win_prob = 1.0 - home_win_prob

    return round(home_win_prob, 4), round(away_win_prob, 4)


def score_individual_matchup(
    session: Session,
    pitcher_id: int,
    batter_id: int,
    season: int,
    pitcher_throws: str = "R",
    venue_name: Optional[str] = None,
) -> Dict:
    """
    Score a specific pitcher vs batter matchup.

    Returns a dict with pitcher_advantage, batter_advantage, net_score,
    pitcher_win_prob, and ballpark_factor metadata for the given venue.
    """
    pitcher_agg = get_pitcher_aggregate(session, pitcher_id, "90d")
    batter_agg = get_batter_aggregate(session, batter_id, "90d")
    arsenal = get_pitch_arsenal(session, pitcher_id, season)

    split_key = "vsR" if pitcher_throws == "R" else "vsL"
    batter_split = get_player_split(session, batter_id, season, split_key)

    p_score = _pitcher_advantage(pitcher_agg)
    b_score = _batter_advantage(batter_agg)
    a_score = _arsenal_vs_batter(arsenal, batter_split)

    park_adj = park_logit_adjustment(venue_name)
    net = (p_score + a_score) - b_score + park_adj

    pf = get_park_factor(venue_name)
    adj_sign = "+" if park_adj >= 0 else ""

    return {
        "pitcher_advantage": round(p_score + a_score, 4),
        "batter_advantage": round(b_score, 4),
        "net_score": round(net, 4),
        "pitcher_win_prob": round(_logistic(net), 4),
        "ballpark_factor": {
            "hr_factor": pf["hr_factor"],
            "run_factor": pf["run_factor"],
            "adjustment": f"{adj_sign}{park_adj:.2f}",
        },
    }

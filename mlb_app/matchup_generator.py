"""
Matchup generation — assembles game-level feature vectors from the DB
and computes win probabilities via the scoring engine.
"""

from __future__ import annotations

from datetime import datetime
from typing import Dict, List, Optional

from sqlalchemy.orm import Session

from .etl import fetch_schedule
from .db_utils import (
    get_pitcher_aggregate,
    get_batter_aggregate,
    get_pitch_arsenal,
    get_player_split,
    get_team_split,
)
from .scoring import compute_win_probability


def _format_pitcher_features(session: Session, pitcher_id: int) -> Dict[str, Optional[float]]:
    agg = get_pitcher_aggregate(session, pitcher_id, "90d")
    if not agg:
        return {k: None for k in [
            "avg_velocity", "avg_spin_rate", "hard_hit_pct", "k_pct", "bb_pct",
            "xwoba", "xba", "avg_horiz_break", "avg_vert_break",
            "avg_release_pos_x", "avg_release_pos_z", "avg_release_extension",
        ]}
    return {
        "avg_velocity": agg.avg_velocity,
        "avg_spin_rate": agg.avg_spin_rate,
        "hard_hit_pct": agg.hard_hit_pct,
        "k_pct": agg.k_pct,
        "bb_pct": agg.bb_pct,
        "xwoba": agg.xwoba,
        "xba": agg.xba,
        "avg_horiz_break": agg.avg_horiz_break,
        "avg_vert_break": agg.avg_vert_break,
        "avg_release_pos_x": agg.avg_release_pos_x,
        "avg_release_pos_z": agg.avg_release_pos_z,
        "avg_release_extension": agg.avg_release_extension,
    }


def _format_pitch_arsenal(session: Session, pitcher_id: int, season: int) -> Dict:
    records = get_pitch_arsenal(session, pitcher_id, season)
    return {
        rec.pitch_type or "": {
            "usage_pct": rec.usage_pct,
            "whiff_pct": rec.whiff_pct,
            "strikeout_pct": rec.strikeout_pct,
            "rv_per_100": rec.rv_per_100,
            "xwoba": rec.xwoba,
            "hard_hit_pct": rec.hard_hit_pct,
        }
        for rec in records
    }


def _format_batter_features(session: Session, batter_id: int) -> Dict[str, Optional[float]]:
    agg = get_batter_aggregate(session, batter_id, "90d")
    if not agg:
        return {k: None for k in [
            "avg_exit_velocity", "avg_launch_angle", "hard_hit_pct",
            "barrel_pct", "k_pct", "bb_pct", "batting_avg",
        ]}
    return {
        "avg_exit_velocity": agg.avg_exit_velocity,
        "avg_launch_angle": agg.avg_launch_angle,
        "hard_hit_pct": agg.hard_hit_pct,
        "barrel_pct": agg.barrel_pct,
        "k_pct": agg.k_pct,
        "bb_pct": agg.bb_pct,
        "batting_avg": agg.batting_avg,
    }


def generate_matchups_for_date(session: Session, date_str: str) -> List[Dict]:
    try:
        date_obj = datetime.strptime(date_str, "%Y-%m-%d")
    except ValueError:
        raise ValueError("date_str must be in YYYY-MM-DD format")

    schedule = fetch_schedule(date_str)
    season = date_obj.year
    matchups = []

    for game in schedule:
        home_team = game.get("home", {}).get("team", {}).get("id")
        away_team = game.get("away", {}).get("team", {}).get("id")
        home_pitcher_id = game.get("home", {}).get("probablePitcher", {}).get("id")
        away_pitcher_id = game.get("away", {}).get("probablePitcher", {}).get("id")

        home_record = game.get("home", {}).get("leagueRecord", {})
        away_record = game.get("away", {}).get("leagueRecord", {})

        if not all([home_team, away_team, home_pitcher_id, away_pitcher_id]):
            # Still include games without probable pitchers — just no win probs
            matchup = {
                "game_date": date_str,
                "game_pk": game.get("_game_pk"),
                "game_time": game.get("_game_date"),
                "venue": game.get("_venue"),
                "status": game.get("_status"),
                "home_team_id": home_team,
                "away_team_id": away_team,
                "home_team_name": game.get("home", {}).get("team", {}).get("name"),
                "away_team_name": game.get("away", {}).get("team", {}).get("name"),
                "home_team_record": f"{home_record.get('wins', 0)}-{home_record.get('losses', 0)}" if home_record else None,
                "away_team_record": f"{away_record.get('wins', 0)}-{away_record.get('losses', 0)}" if away_record else None,
                "home_pitcher_id": home_pitcher_id,
                "away_pitcher_id": away_pitcher_id,
                "home_pitcher_name": game.get("home", {}).get("probablePitcher", {}).get("fullName"),
                "away_pitcher_name": game.get("away", {}).get("probablePitcher", {}).get("fullName"),
                "home_win_prob": None,
                "away_win_prob": None,
                "home_pitcher_features": {},
                "away_pitcher_features": {},
                "home_pitch_arsenal": {},
                "away_pitch_arsenal": {},
            }
            matchups.append(matchup)
            continue

        home_win_prob, away_win_prob = compute_win_probability(
            session,
            home_pitcher_id=home_pitcher_id,
            away_pitcher_id=away_pitcher_id,
            home_team_id=home_team,
            away_team_id=away_team,
            season=season,
        )

        matchup = {
            "game_date": date_str,
            "game_pk": game.get("_game_pk"),
            "game_time": game.get("_game_date"),
            "venue": game.get("_venue"),
            "status": game.get("_status"),
            "home_team_id": home_team,
            "away_team_id": away_team,
            "home_team_name": game.get("home", {}).get("team", {}).get("name"),
            "away_team_name": game.get("away", {}).get("team", {}).get("name"),
            "home_team_record": f"{home_record.get('wins', 0)}-{home_record.get('losses', 0)}" if home_record else None,
            "away_team_record": f"{away_record.get('wins', 0)}-{away_record.get('losses', 0)}" if away_record else None,
            "home_pitcher_id": home_pitcher_id,
            "away_pitcher_id": away_pitcher_id,
            "home_pitcher_name": game.get("home", {}).get("probablePitcher", {}).get("fullName"),
            "away_pitcher_name": game.get("away", {}).get("probablePitcher", {}).get("fullName"),
            "home_win_prob": home_win_prob,
            "away_win_prob": away_win_prob,
            "home_pitcher_features": _format_pitcher_features(session, home_pitcher_id),
            "away_pitcher_features": _format_pitcher_features(session, away_pitcher_id),
            "home_pitch_arsenal": _format_pitch_arsenal(session, home_pitcher_id, season),
            "away_pitch_arsenal": _format_pitch_arsenal(session, away_pitcher_id, season),
        }
        matchups.append(matchup)

    return matchups


__all__ = ["generate_matchups_for_date"]

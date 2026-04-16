"""
Matchup generation utilities.

This module provides functions to assemble game‑level feature vectors
from pre‑computed aggregates stored in the database.  It bridges
schedule information with aggregated pitcher, batter and pitch‑type
statistics so that the prediction model and API can produce a
comprehensive view of each matchup.

The primary entry point is ``generate_matchups_for_date``, which
takes a SQLAlchemy session and a date string (YYYY‑MM‑DD).  It uses
the schedule functions from ``data_ingestion`` to retrieve games for
the given day, then looks up the corresponding aggregates via
``db_utils``.  It returns a list of dictionaries ready for
serialization.

NOTE: The functions here currently assume that aggregates have been
pre‑computed and loaded into the database via the ETL pipeline and
aggregation scripts.  It does not compute on the fly.

Example usage::

    from datetime import date
    from mlb_app.database import get_engine, create_tables, get_session
    from mlb_app.db_utils import get_pitcher_aggregate, get_batter_aggregate
    from mlb_app.matchup_generator import generate_matchups_for_date

    engine = get_engine("postgresql+psycopg2://user:pass@host/db")
    SessionLocal = get_session(engine)
    with SessionLocal() as session:
        matchups = generate_matchups_for_date(session, "2026-04-15")
        for m in matchups:
            print(m)

"""

from __future__ import annotations

from datetime import datetime
from typing import Dict, List, Optional

from sqlalchemy.orm import Session

from . import data_ingestion
from .db_utils import (
    get_pitcher_aggregate,
    get_batter_aggregate,
    get_pitch_arsenal,
    get_player_split,
    get_team_split,
)


def _format_pitcher_features(
    session: Session, pitcher_id: int, date_obj: datetime
) -> Dict[str, Optional[float]]:
    """Retrieve and format pitcher features for a given pitcher.

    This helper function fetches rolling and seasonal aggregates for
    the specified pitcher and date.  It currently uses the 90‑day
    window ("90d") ending on the provided date.  Additional windows
    can be added as needed.

    :param session: Active database session.
    :param pitcher_id: MLBAM identifier for the pitcher.
    :param date_obj: Date of the matchup as a datetime object.
    :returns: A dictionary of feature names to values.  Missing
        aggregates result in ``None`` values.
    """
    window_label = "90d"
    agg = get_pitcher_aggregate(session, pitcher_id, window_label)
    if not agg:
        return {
            "avg_velocity": None,
            "avg_spin_rate": None,
            "hard_hit_pct": None,
            "k_pct": None,
            "bb_pct": None,
            "xwoba": None,
            "xba": None,
            "avg_horiz_break": None,
            "avg_vert_break": None,
            "avg_release_pos_x": None,
            "avg_release_pos_z": None,
            "avg_release_extension": None,
        }
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


def _format_pitch_arsenal(
    session: Session, pitcher_id: int, season: int
) -> Dict[str, Dict[str, Optional[float]]]:
    """Return a mapping of pitch type to arsenal metrics.

    Retrieves all pitch‑arsenal records for the pitcher and season and
    returns a nested dictionary keyed by ``pitch_type``.  The inner
    dictionary contains usage %, whiff % and run value per 100 (RV/100).

    :param session: Active database session.
    :param pitcher_id: MLBAM identifier for the pitcher.
    :param season: Numeric season year.
    :returns: Mapping of pitch type to metrics.
    """
    arsenal_records = get_pitch_arsenal(session, pitcher_id, season)
    arsenal = {}
    for rec in arsenal_records:
        arsenal[rec.pitch_type or ""] = {
            "usage_pct": rec.usage_pct,
            "whiff_pct": rec.whiff_pct,
            "strikeout_pct": rec.strikeout_pct,
            "rv_per_100": rec.rv_per_100,
            "xwoba": rec.xwoba,
            "hard_hit_pct": rec.hard_hit_pct,
        }
    return arsenal


def _format_batter_features(
    session: Session, batter_id: int, date_obj: datetime
) -> Dict[str, Optional[float]]:
    """Retrieve and format batter features for a given batter.

    Similar to ``_format_pitcher_features`` but for hitters.  Uses
    the 90‑day rolling window and returns average exit velocity,
    launch angle, hard‑hit rate, barrel rate, strikeout rate, walk
    rate and batting average.

    :param session: Active database session.
    :param batter_id: MLBAM identifier for the hitter.
    :param date_obj: Date of the matchup.
    :returns: Mapping of feature names to values with ``None`` for
        missing aggregates.
    """
    window_label = "90d"
    agg = get_batter_aggregate(session, batter_id, window_label)
    if not agg:
        return {
            "avg_exit_velocity": None,
            "avg_launch_angle": None,
            "hard_hit_pct": None,
            "barrel_pct": None,
            "k_pct": None,
            "bb_pct": None,
            "batting_avg": None,
        }
    return {
        "avg_exit_velocity": agg.avg_exit_velocity,
        "avg_launch_angle": agg.avg_launch_angle,
        "hard_hit_pct": agg.hard_hit_pct,
        "barrel_pct": agg.barrel_pct,
        "k_pct": agg.k_pct,
        "bb_pct": agg.bb_pct,
        "batting_avg": agg.batting_avg,
    }


def generate_matchups_for_date(
    session: Session, date_str: str
) -> List[Dict[str, object]]:
    """Generate a list of matchup dictionaries for a given date.

    :param session: Active database session.
    :param date_str: Date string in ``YYYY-MM-DD`` format.
    :returns: List of dictionaries containing matchup features.  Each
        dictionary includes team IDs, pitcher IDs and aggregated
        metrics for home and away pitchers.
    """
    # Parse date
    try:
        date_obj = datetime.strptime(date_str, "%Y-%m-%d")
    except ValueError:
        raise ValueError("date_str must be in YYYY-MM-DD format")

    # Fetch schedule for the date
    schedule = data_ingestion.fetch_schedule(date_str)
    matchups = []
    for game in schedule:
        home_team = game.get("home" , {}).get("team", {}).get("id")
        away_team = game.get("away" , {}).get("team", {}).get("id")
        home_pitcher_id = game.get("home", {}).get("probablePitcher", {}).get("id")
        away_pitcher_id = game.get("away", {}).get("probablePitcher", {}).get("id")

        # Skip games without probable pitchers or team IDs
        if not home_team or not away_team or not home_pitcher_id or not away_pitcher_id:
            continue

        # Retrieve features for pitchers
        home_pitcher_features = _format_pitcher_features(
            session, home_pitcher_id, date_obj
        )
        away_pitcher_features = _format_pitcher_features(
            session, away_pitcher_id, date_obj
        )

        # Retrieve pitch arsenal for both pitchers (use current year)
        season = date_obj.year
        home_pitch_arsenal = _format_pitch_arsenal(session, home_pitcher_id, season)
        away_pitch_arsenal = _format_pitch_arsenal(session, away_pitcher_id, season)

        # Build matchup dictionary
        matchup = {
            "game_date": date_str,
            "home_team_id": home_team,
            "away_team_id": away_team,
            "home_pitcher_id": home_pitcher_id,
            "away_pitcher_id": away_pitcher_id,
            "home_pitcher_features": home_pitcher_features,
            "away_pitcher_features": away_pitcher_features,
            "home_pitch_arsenal": home_pitch_arsenal,
            "away_pitch_arsenal": away_pitch_arsenal,
        }
        matchups.append(matchup)

    return matchups


__all__ = ["generate_matchups_for_date"]

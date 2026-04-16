"""
Database helper functions for retrieving aggregated metrics.

This module provides convenience functions to query pitcher and batter
aggregates, pitch‑arsenal statistics and hitting splits from the
database using SQLAlchemy sessions.  It encapsulates common query
patterns so that the rest of the application can remain agnostic of the
underlying ORM models.

Functions defined here accept a ``Session`` object bound to the
application's database engine and return instances of the ORM models
defined in ``database.py`` or ``None`` if no matching record exists.

Example usage::

    from mlb_app.database import get_engine, create_tables, get_session
    from mlb_app.db_utils import (
        get_pitcher_aggregate,
        get_batter_aggregate,
        get_pitch_arsenal,
        get_player_split,
        get_team_split,
    )

    engine = get_engine("postgresql+psycopg2://user:pass@host/db")
    create_tables(engine)
    SessionLocal = get_session(engine)

    with SessionLocal() as session:
        agg = get_pitcher_aggregate(session, pitcher_id=123, window="90d")
        arsenal = get_pitch_arsenal(session, pitcher_id=123, season=2026)
        hitter_vs_rhp = get_player_split(session, player_id=456, season=2026, split="vsR")

"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import pandas as pd
from sqlalchemy.orm import Session

from .database import (
    AtBatOutcome,
    PitcherAggregate,
    BatterAggregate,
    PitchArsenal,
    PlayerSplit,
    StatcastEvent,
    TeamSplit,
)


def get_pitcher_aggregate(
    session: Session, pitcher_id: int, window: str
) -> Optional[PitcherAggregate]:
    """Return a pitcher aggregate for a given pitcher and window.

    :param session: Active database session.
    :param pitcher_id: MLBAM identifier for the pitcher.
    :param window: Rolling window or season label (e.g., ``"90d"``,
        ``"2025"``) used when aggregating metrics.
    :returns: A :class:`PitcherAggregate` instance if found, otherwise
        ``None``.
    """
    return (
        session.query(PitcherAggregate)
        .filter(
            PitcherAggregate.pitcher_id == pitcher_id,
            PitcherAggregate.window == window,
        )
        .order_by(PitcherAggregate.end_date.desc())
        .first()
    )



def get_batter_aggregate(
    session: Session, batter_id: int, window: str
) -> Optional[BatterAggregate]:
    """Return a batter aggregate for a given batter and window.

    :param session: Active database session.
    :param batter_id: MLBAM identifier for the batter.
    :param window: Rolling window or season label.
    :returns: A :class:`BatterAggregate` instance if found, otherwise
        ``None``.
    """
    return (
        session.query(BatterAggregate)
        .filter(
            BatterAggregate.batter_id == batter_id,
            BatterAggregate.window == window,
        )
        .order_by(BatterAggregate.end_date.desc())
        .first()
    )



def get_pitch_arsenal(
    session: Session, pitcher_id: int, season: int
) -> List[PitchArsenal]:
    """Return all pitch‑arsenal records for a pitcher in a given season.

    :param session: Active database session.
    :param pitcher_id: MLBAM identifier for the pitcher.
    :param season: Numeric year (e.g., 2026) for which to retrieve
        pitch‑arsenal stats.
    :returns: A list of :class:`PitchArsenal` records (possibly empty).
    """
    return (
        session.query(PitchArsenal)
        .filter(
            PitchArsenal.pitcher_id == pitcher_id,
            PitchArsenal.season == season,
        )
        .order_by(PitchArsenal.pitch_type)
        .all()
    )



def get_player_split(
    session: Session, player_id: int, season: int, split: str
) -> Optional[PlayerSplit]:
    """Return a player's hitting split for a given season and split code.

    :param session: Active database session.
    :param player_id: MLBAM identifier for the batter.
    :param season: Year to query.
    :param split: ``"vsL"`` or ``"vsR"`` indicating the pitcher
        handedness.
    :returns: A :class:`PlayerSplit` instance if found, otherwise
        ``None``.
    """
    return (
        session.query(PlayerSplit)
        .filter(
            PlayerSplit.player_id == player_id,
            PlayerSplit.season == season,
            PlayerSplit.split == split,
        )
        .first()
    )



def get_team_split(
    session: Session, team_id: int, season: int, split: str
) -> Optional[TeamSplit]:
    """Return a team's hitting split for a given season and split code.

    :param session: Active database session.
    :param team_id: MLBAM identifier for the team.
    :param season: Year to query.
    :param split: ``"vsL"`` or ``"vsR"`` indicating pitcher
        handedness.
    :returns: A :class:`TeamSplit` instance if found, otherwise
        ``None``.
    """
    return (
        session.query(TeamSplit)
        .filter(
            TeamSplit.team_id == team_id,
            TeamSplit.season == season,
            TeamSplit.split == split,
        )
        .first()
    )


# ---------------------------------------------------------------------------
# Rolling computation helpers
# ---------------------------------------------------------------------------

# Plate-appearance terminal events (rows where events IS NOT NULL)
_PA_EVENTS = {
    "single",
    "double",
    "triple",
    "home_run",
    "strikeout",
    "strikeout_double_play",
    "walk",
    "intent_walk",
    "hit_by_pitch",
    "field_out",
    "force_out",
    "grounded_into_double_play",
    "double_play",
    "triple_play",
    "fielders_choice",
    "fielders_choice_out",
    "sac_fly",
    "sac_fly_double_play",
    "sac_bunt",
    "sac_bunt_double_play",
    "catcher_interf",
    "other_out",
}

_HIT_EVENTS = {"single", "double", "triple", "home_run"}
_AB_EVENTS = {
    "single",
    "double",
    "triple",
    "home_run",
    "field_out",
    "force_out",
    "grounded_into_double_play",
    "double_play",
    "triple_play",
    "fielders_choice",
    "fielders_choice_out",
    "other_out",
    "strikeout",
    "strikeout_double_play",
}


def _compute_pitcher_metrics(rows: List[StatcastEvent]) -> Dict[str, Any]:
    """Compute pitcher aggregate metrics from a list of StatcastEvent ORM rows.

    Returns a dict with keys: ``pitch_count``, ``AvgVelo``, ``AvgSpin``,
    ``HardHit%``, ``K%``, ``BB%``.  All rate stats are expressed as
    percentages (0–100).  Returns an empty dict when *rows* is empty.
    """
    if not rows:
        return {}

    total = len(rows)
    velos = [r.release_speed for r in rows if r.release_speed is not None]
    spins = [r.release_spin_rate for r in rows if r.release_spin_rate is not None]
    hard_hits = sum(
        1 for r in rows
        if r.launch_speed is not None and r.launch_speed >= 95
    )
    strikeouts = sum(1 for r in rows if r.events in ("strikeout", "strikeout_double_play"))
    walks = sum(1 for r in rows if r.events in ("walk", "intent_walk"))

    return {
        "pitch_count": total,
        "AvgVelo": sum(velos) / len(velos) if velos else None,
        "AvgSpin": sum(spins) / len(spins) if spins else None,
        "HardHit%": (hard_hits / total) * 100,
        "K%": (strikeouts / total) * 100,
        "BB%": (walks / total) * 100,
    }


def _compute_batter_metrics(rows: List[StatcastEvent]) -> Dict[str, Any]:
    """Compute batter aggregate metrics from a list of StatcastEvent ORM rows.

    Filters to plate-appearance terminal rows (``events IS NOT NULL``) for
    rate stats.  Returns a dict with keys: ``pa``, ``AvgEV``, ``AvgLA``,
    ``HardHit%``, ``AVG``, ``K%``, ``BB%``.  Returns an empty dict when
    *rows* is empty.
    """
    if not rows:
        return {}

    pa_rows = [r for r in rows if r.events]
    total_pa = len(pa_rows)
    if total_pa == 0:
        return {}

    evs = [r.launch_speed for r in pa_rows if r.launch_speed is not None]
    las = [r.launch_angle for r in pa_rows if r.launch_angle is not None]
    hard_hits = sum(1 for r in pa_rows if r.launch_speed is not None and r.launch_speed >= 95)
    hits = sum(1 for r in pa_rows if r.events in _HIT_EVENTS)
    strikeouts = sum(1 for r in pa_rows if r.events in ("strikeout", "strikeout_double_play"))
    walks = sum(1 for r in pa_rows if r.events in ("walk", "intent_walk"))
    at_bats = sum(1 for r in pa_rows if r.events in _AB_EVENTS)

    return {
        "pa": total_pa,
        "AvgEV": sum(evs) / len(evs) if evs else None,
        "AvgLA": sum(las) / len(las) if las else None,
        "HardHit%": (hard_hits / total_pa) * 100,
        "AVG": (hits / at_bats) if at_bats else None,
        "K%": (strikeouts / total_pa) * 100,
        "BB%": (walks / total_pa) * 100,
    }


def get_pitcher_rolling_by_games(
    session: Session, pitcher_id: int, n_games: int
) -> Dict[str, Any]:
    """Return pitcher metrics computed over the last *n_games* distinct game dates.

    Queries all pitches thrown by *pitcher_id* in the most recent
    *n_games* distinct ``game_date`` values, then computes aggregate
    metrics using :func:`_compute_pitcher_metrics`.

    :param session: Active database session.
    :param pitcher_id: MLBAM identifier for the pitcher.
    :param n_games: Number of most-recent distinct game dates to include.
    :returns: Dict of aggregated metrics, or an empty dict if no data.
    """
    # Find the N most-recent distinct game dates for this pitcher
    date_rows = (
        session.query(StatcastEvent.game_date)
        .filter(StatcastEvent.pitcher_id == pitcher_id)
        .distinct()
        .order_by(StatcastEvent.game_date.desc())
        .limit(n_games)
        .all()
    )
    if not date_rows:
        return {}
    cutoff_dates = [r.game_date for r in date_rows]
    rows = (
        session.query(StatcastEvent)
        .filter(
            StatcastEvent.pitcher_id == pitcher_id,
            StatcastEvent.game_date.in_(cutoff_dates),
        )
        .all()
    )
    return _compute_pitcher_metrics(rows)


def get_pitcher_rolling_by_pitches(
    session: Session, pitcher_id: int, n_pitches: int
) -> Dict[str, Any]:
    """Return pitcher metrics computed over the last *n_pitches* pitches.

    Fetches the *n_pitches* most-recent pitch rows for *pitcher_id*
    ordered by ``game_date`` descending and computes aggregate metrics.

    :param session: Active database session.
    :param pitcher_id: MLBAM identifier for the pitcher.
    :param n_pitches: Number of most-recent pitches to include.
    :returns: Dict of aggregated metrics, or an empty dict if no data.
    """
    rows = (
        session.query(StatcastEvent)
        .filter(StatcastEvent.pitcher_id == pitcher_id)
        .order_by(StatcastEvent.game_date.desc(), StatcastEvent.id.desc())
        .limit(n_pitches)
        .all()
    )
    return _compute_pitcher_metrics(rows)


def get_batter_rolling_by_abs(
    session: Session, batter_id: int, n_abs: int
) -> Dict[str, Any]:
    """Return batter metrics computed over the last *n_abs* at-bats.

    An "at-bat" here is any ``StatcastEvent`` row where ``events IS NOT
    NULL`` (i.e. a plate-appearance terminal pitch).  The *n_abs* most
    recent such rows are fetched and metrics are computed via
    :func:`_compute_batter_metrics`.

    :param session: Active database session.
    :param batter_id: MLBAM identifier for the batter.
    :param n_abs: Number of most-recent plate appearances to include.
    :returns: Dict of aggregated metrics, or an empty dict if no data.
    """
    rows = (
        session.query(StatcastEvent)
        .filter(
            StatcastEvent.batter_id == batter_id,
            StatcastEvent.events.isnot(None),
        )
        .order_by(StatcastEvent.game_date.desc(), StatcastEvent.id.desc())
        .limit(n_abs)
        .all()
    )
    return _compute_batter_metrics(rows)


def get_batter_rolling_by_games(
    session: Session, batter_id: int, n_games: int
) -> Dict[str, Any]:
    """Return batter metrics computed over the last *n_games* distinct game dates.

    Queries all plate-appearance terminal rows for *batter_id* in the
    most recent *n_games* distinct ``game_date`` values and computes
    aggregate metrics.

    :param session: Active database session.
    :param batter_id: MLBAM identifier for the batter.
    :param n_games: Number of most-recent distinct game dates to include.
    :returns: Dict of aggregated metrics, or an empty dict if no data.
    """
    date_rows = (
        session.query(StatcastEvent.game_date)
        .filter(StatcastEvent.batter_id == batter_id)
        .distinct()
        .order_by(StatcastEvent.game_date.desc())
        .limit(n_games)
        .all()
    )
    if not date_rows:
        return {}
    cutoff_dates = [r.game_date for r in date_rows]
    rows = (
        session.query(StatcastEvent)
        .filter(
            StatcastEvent.batter_id == batter_id,
            StatcastEvent.game_date.in_(cutoff_dates),
        )
        .all()
    )
    return _compute_batter_metrics(rows)


__all__ = [
    "get_pitcher_aggregate",
    "get_batter_aggregate",
    "get_pitch_arsenal",
    "get_player_split",
    "get_team_split",
    "get_pitcher_rolling_by_games",
    "get_pitcher_rolling_by_pitches",
    "get_batter_rolling_by_abs",
    "get_batter_rolling_by_games",
]

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

import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from .database import (
    PitcherAggregate,
    BatterAggregate,
    PitchArsenal,
    PlayerSplit,
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


def get_pitcher_aggregate_with_fallback(
    session: Session,
    pitcher_id: int,
    as_of_date: Optional[datetime.date] = None,
) -> Optional[Dict[str, Any]]:
    """Return pitcher aggregate data using a fallback chain across windows.

    Tries windows in order: ``"90d"``, ``"2026"``, ``"2025"``, ``"2024"``.
    The first window that has a row in the database is returned as a plain
    dictionary with an extra ``"data_source"`` key indicating which window
    was used.  Returns ``None`` if no data is found in any window.

    A 90‑day result is considered *sparse* (and therefore skipped in favour
    of a prior‑season fallback) when ``total_pitches`` is below 20 **or**
    when all of the key metric columns are ``None``.

    :param session: Active database session.
    :param pitcher_id: MLBAM identifier for the pitcher.
    :param as_of_date: Upper bound for ``end_date`` filtering.  Defaults to
        today.  Season‑window rows are matched regardless of this value
        because their ``end_date`` is set to the season end.
    :returns: A dict of aggregate fields plus ``"data_source"``, or ``None``.
    """
    if as_of_date is None:
        as_of_date = datetime.date.today()

    current_year = as_of_date.year
    # Build the fallback chain: rolling 90d first, then current and prior seasons
    fallback_windows = ["90d", str(current_year), str(current_year - 1), str(current_year - 2)]

    _SPARSE_THRESHOLD = 20  # minimum pitches for a 90d window to be considered sufficient

    for window in fallback_windows:
        query = (
            session.query(PitcherAggregate)
            .filter(
                PitcherAggregate.pitcher_id == pitcher_id,
                PitcherAggregate.window == window,
            )
        )
        # For the rolling window, only consider rows up to as_of_date
        if window == "90d":
            query = query.filter(PitcherAggregate.end_date <= as_of_date)

        row = query.order_by(PitcherAggregate.end_date.desc()).first()
        if row is None:
            continue

        # For the 90d window, skip if the data is too sparse to be useful.
        # We proxy "sparse" by checking whether all key metrics are None,
        # which happens when fewer than ~20 pitches were recorded.
        if window == "90d":
            key_metrics = [row.avg_velocity, row.k_pct, row.bb_pct, row.xwoba]
            all_none = all(v is None for v in key_metrics)
            if all_none:
                continue

        result: Dict[str, Any] = {
            c.name: getattr(row, c.name)
            for c in row.__table__.columns
        }
        result["data_source"] = window
        return result

    return None


def get_batter_aggregate_with_fallback(
    session: Session,
    batter_id: int,
    as_of_date: Optional[datetime.date] = None,
) -> Optional[Dict[str, Any]]:
    """Return batter aggregate data using a fallback chain across windows.

    Tries windows in order: ``"90d"``, ``"2026"``, ``"2025"``, ``"2024"``.
    The first window that has a row in the database is returned as a plain
    dictionary with an extra ``"data_source"`` key indicating which window
    was used.  Returns ``None`` if no data is found in any window.

    A 90‑day result is considered *sparse* (and therefore skipped in favour
    of a prior‑season fallback) when all of the key metric columns are
    ``None``, which occurs when fewer than ~20 at‑bats were recorded.

    :param session: Active database session.
    :param batter_id: MLBAM identifier for the batter.
    :param as_of_date: Upper bound for ``end_date`` filtering.  Defaults to
        today.  Season‑window rows are matched regardless of this value
        because their ``end_date`` is set to the season end.
    :returns: A dict of aggregate fields plus ``"data_source"``, or ``None``.
    """
    if as_of_date is None:
        as_of_date = datetime.date.today()

    current_year = as_of_date.year
    fallback_windows = ["90d", str(current_year), str(current_year - 1), str(current_year - 2)]

    for window in fallback_windows:
        query = (
            session.query(BatterAggregate)
            .filter(
                BatterAggregate.batter_id == batter_id,
                BatterAggregate.window == window,
            )
        )
        if window == "90d":
            query = query.filter(BatterAggregate.end_date <= as_of_date)

        row = query.order_by(BatterAggregate.end_date.desc()).first()
        if row is None:
            continue

        if window == "90d":
            key_metrics = [row.avg_exit_velocity, row.k_pct, row.bb_pct, row.batting_avg]
            all_none = all(v is None for v in key_metrics)
            if all_none:
                continue

        result: Dict[str, Any] = {
            c.name: getattr(row, c.name)
            for c in row.__table__.columns
        }
        result["data_source"] = window
        return result

    return None


__all__ = [
    "get_pitcher_aggregate",
    "get_batter_aggregate",
    "get_pitcher_aggregate_with_fallback",
    "get_batter_aggregate_with_fallback",
    "get_pitch_arsenal",
    "get_player_split",
    "get_team_split",
]

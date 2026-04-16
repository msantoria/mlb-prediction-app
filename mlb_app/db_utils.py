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
        get_pitcher_multi_season_stats,
        get_pitcher_game_log,
        get_team_rotation,
        get_team_bullpen,
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

from typing import List, Optional

from sqlalchemy.orm import Session

from .database import (
    PitcherAggregate,
    BatterAggregate,
    PitchArsenal,
    PlayerSplit,
    TeamSplit,
    PitcherGameLog,
    TeamRoster,
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


def get_pitcher_multi_season_stats(
    session: Session, pitcher_id: int
) -> List[PitcherAggregate]:
    """Return all season-window aggregates for a pitcher, newest first.

    Queries ``pitcher_aggregates`` for rows whose ``window`` value looks like
    a four-digit year (e.g., ``"2024"``, ``"2025"``) **or** the special
    ``"90d"`` rolling window, ordered by ``end_date`` descending so the most
    recent season appears first.  The caller can use the ``window`` field to
    distinguish the current rolling window (``"90d"``) from completed seasons.

    :param session: Active database session.
    :param pitcher_id: MLBAM identifier for the pitcher.
    :returns: A list of :class:`PitcherAggregate` records (possibly empty).
    """
    return (
        session.query(PitcherAggregate)
        .filter(PitcherAggregate.pitcher_id == pitcher_id)
        .order_by(PitcherAggregate.end_date.desc())
        .all()
    )


def get_pitcher_game_log(
    session: Session, pitcher_id: int, limit: int = 10
) -> List[PitcherGameLog]:
    """Return the most recent pitching appearances for a pitcher.

    Results are ordered by ``game_date`` descending so the latest game is
    first.  Use the ``limit`` parameter to control how many rows are returned
    (default 10).

    :param session: Active database session.
    :param pitcher_id: MLBAM identifier for the pitcher.
    :param limit: Maximum number of game-log rows to return.
    :returns: A list of :class:`PitcherGameLog` records (possibly empty).
    """
    return (
        session.query(PitcherGameLog)
        .filter(PitcherGameLog.pitcher_id == pitcher_id)
        .order_by(PitcherGameLog.game_date.desc())
        .limit(limit)
        .all()
    )


def get_team_rotation(
    session: Session, team_id: int, season: int
) -> List[TeamRoster]:
    """Return the starting-pitcher roster entries for a team and season.

    Filters ``team_roster`` to rows where ``is_starter`` is ``True``,
    ordered by ERA ascending so the ace appears first.  Rows with a
    ``NULL`` ERA are sorted to the end.

    :param session: Active database session.
    :param team_id: MLBAM identifier for the team.
    :param season: Year to query (e.g., 2026).
    :returns: A list of :class:`TeamRoster` records (possibly empty).
    """
    return (
        session.query(TeamRoster)
        .filter(
            TeamRoster.team_id == team_id,
            TeamRoster.season == season,
            TeamRoster.is_starter == True,  # noqa: E712
        )
        .order_by(TeamRoster.era.asc().nullslast())
        .all()
    )


def get_team_bullpen(
    session: Session, team_id: int, season: int
) -> List[TeamRoster]:
    """Return the relief-pitcher roster entries for a team and season.

    Filters ``team_roster`` to rows where ``is_starter`` is ``False``,
    ordered by ERA ascending so the best relievers appear first.  Rows
    with a ``NULL`` ERA are sorted to the end.

    :param session: Active database session.
    :param team_id: MLBAM identifier for the team.
    :param season: Year to query (e.g., 2026).
    :returns: A list of :class:`TeamRoster` records (possibly empty).
    """
    return (
        session.query(TeamRoster)
        .filter(
            TeamRoster.team_id == team_id,
            TeamRoster.season == season,
            TeamRoster.is_starter == False,  # noqa: E712
        )
        .order_by(TeamRoster.era.asc().nullslast())
        .all()
    )


__all__ = [
    "get_pitcher_aggregate",
    "get_batter_aggregate",
    "get_pitch_arsenal",
    "get_player_split",
    "get_team_split",
    "get_pitcher_multi_season_stats",
    "get_pitcher_game_log",
    "get_team_rotation",
    "get_team_bullpen",
]

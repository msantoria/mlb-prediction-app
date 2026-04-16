"""
Database models and utilities for the MLB prediction app.

This module defines the SQLAlchemy ORM models used to store raw Statcast
events, aggregated pitch‑arsenal statistics, platoon splits, rolling/seasonal
metrics and game‑level matchups.  It also provides helper functions to
instantiate a database engine and session maker based on a connection URL.

All tables are defined with sensible data types and include primary keys and
simple indexes on fields that will commonly be used in queries (e.g.,
``game_date``, ``pitcher_id``, ``batter_id``).  The schema mirrors the core
entities used throughout the ETL and analysis pipeline:

* ``StatcastEvent`` – one row per pitch with pitch/launch characteristics and
  count context.
* ``PitchArsenal`` – season‑level pitch arsenal metrics for each pitcher and
  pitch type, capturing usage %, whiff %, strikeout %, run value per 100,
  expected wOBA and hard‑hit %.
* ``TeamSplit`` and ``PlayerSplit`` – basic hitting statistics for teams and
  players vs. left‑ and right‑handed pitching.
* ``PitcherAggregate`` and ``BatterAggregate`` – rolling or seasonal
  aggregates derived from ``StatcastEvent`` using functions defined in
  ``aggregation.py``.
* ``PitcherGameLog`` – one row per pitching appearance with box-score line
  (IP, H, R, ER, K, BB, HR, pitches) used to build game-log tables.
* ``TeamRoster`` – season roster entries for pitchers, flagged as starter or
  reliever, with ERA/WHIP/K%/BB% used to build rotation and bullpen sections.
* ``Matchup`` – one row per game capturing the teams, pitchers and the
  computed feature vector for that game.

To use this module, call ``get_engine`` with a database URL (e.g.,
``postgresql+psycopg2://user:password@host/dbname``), then call
``create_tables`` to create the schema.  Use ``get_session`` to obtain a
sessionmaker bound to the engine.  See the README for deployment details.
"""

from __future__ import annotations

from datetime import date
from typing import Optional

from sqlalchemy import (
    Boolean,
    Column,
    Date,
    Float,
    Integer,
    String,
    create_engine,
    Index,
)
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session


# Base class for ORM models
Base = declarative_base()


class StatcastEvent(Base):
    """Pitch‑level Statcast event data.

    Each row corresponds to a single pitch thrown in a game.  The
    ``statcast_events`` table stores both pitch characteristics (velocity,
    spin rate, movement, release position) and outcome information (balls,
    strikes, event type) along with identifiers for the pitcher, batter and
    date.  Primary key ``id`` is an auto‑incrementing
    surrogate.
    """

    __tablename__ = "statcast_events"

    id: int = Column(Integer, primary_key=True, autoincrement=True)
    game_date: date = Column(Date, nullable=False, index=True)
    pitcher_id: int = Column(Integer, nullable=False, index=True)
    batter_id: int = Column(Integer, nullable=False, index=True)
    pitch_type: Optional[str] = Column(String(5), nullable=True)
    release_speed: Optional[float] = Column(Float, nullable=True)
    release_spin_rate: Optional[float] = Column(Float, nullable=True)
    pfx_x: Optional[float] = Column(Float, nullable=True)
    pfx_z: Optional[float] = Column(Float, nullable=True)
    plate_x: Optional[float] = Column(Float, nullable=True)
    plate_z: Optional[float] = Column(Float, nullable=True)
    balls: Optional[int] = Column(Integer, nullable=True)
    strikes: Optional[int] = Column(Integer, nullable=True)
    events: Optional[str] = Column(String(50), nullable=True)
    launch_speed: Optional[float] = Column(Float, nullable=True)
    launch_angle: Optional[float] = Column(Float, nullable=True)
    stand: Optional[str] = Column(String(1), nullable=True)  # batter stance (L/R)
    p_throws: Optional[str] = Column(String(1), nullable=True)  # pitcher throws (L/R)

    # Composite index for fast filtering by date and player
    __table_args__ = (
        Index("ix_statcast_events_date_pitcher", "game_date", "pitcher_id"),
        Index("ix_statcast_events_date_batter", "game_date", "batter_id"),
    )


class PitchArsenal(Base):
    """Aggregated pitch arsenal statistics for each pitcher.

    This table stores season‑level metrics for each pitch type thrown by a
    pitcher, including usage share, whiff and strikeout rates, run value per
    100 pitches, expected wOBA and hard‑hit percentage.  These fields mirror
    the columns available in Baseball Savant's pitch‑arsenal leaderboard.
    """

    __tablename__ = "pitch_arsenal"

    id: int = Column(Integer, primary_key=True, autoincrement=True)
    season: int = Column(Integer, nullable=False, index=True)
    pitcher_id: int = Column(Integer, nullable=False, index=True)
    pitch_type: Optional[str] = Column(String(5), nullable=True)
    pitch_name: Optional[str] = Column(String(50), nullable=True)
    pitch_count: Optional[int] = Column(Integer, nullable=True)
    usage_pct: Optional[float] = Column(Float, nullable=True)
    whiff_pct: Optional[float] = Column(Float, nullable=True)
    strikeout_pct: Optional[float] = Column(Float, nullable=True)
    rv_per_100: Optional[float] = Column(Float, nullable=True)
    xwoba: Optional[float] = Column(Float, nullable=True)
    hard_hit_pct: Optional[float] = Column(Float, nullable=True)

    __table_args__ = (
        Index("ix_pitch_arsenal_season_pitcher", "season", "pitcher_id"),
    )


class TeamSplit(Base):
    """Team hitting splits versus pitcher handedness.

    Each row contains a team's aggregated offensive statistics for a given
    season and split (vs LHP or RHP).  Metrics include plate appearances,
    hits, doubles, triples, home runs, walks, strikeouts, batting average,
    on‑base percentage, slugging and ISO.
    """

    __tablename__ = "team_splits"

    id: int = Column(Integer, primary_key=True, autoincrement=True)
    season: int = Column(Integer, nullable=False, index=True)
    team_id: int = Column(Integer, nullable=False, index=True)
    split: str = Column(String(3), nullable=False)  # 'vsL' or 'vsR'
    pa: Optional[int] = Column(Integer, nullable=True)
    hits: Optional[int] = Column(Integer, nullable=True)
    doubles: Optional[int] = Column(Integer, nullable=True)
    triples: Optional[int] = Column(Integer, nullable=True)
    home_runs: Optional[int] = Column(Integer, nullable=True)
    walks: Optional[int] = Column(Integer, nullable=True)
    strikeouts: Optional[int] = Column(Integer, nullable=True)
    batting_avg: Optional[float] = Column(Float, nullable=True)
    on_base_pct: Optional[float] = Column(Float, nullable=True)
    slugging_pct: Optional[float] = Column(Float, nullable=True)
    iso: Optional[float] = Column(Float, nullable=True)
    k_pct: Optional[float] = Column(Float, nullable=True)
    bb_pct: Optional[float] = Column(Float, nullable=True)

    __table_args__ = (
        Index("ix_team_splits_season_team", "season", "team_id"),
    )


class PlayerSplit(Base):
    """Player hitting splits versus pitcher handedness.

    Stores individual player offensive stats split by opposing pitcher handedness
    (vs LHP or vs RHP).  The schema is similar to ``TeamSplit`` but keyed
    by player ID instead of team ID.
    """

    __tablename__ = "player_splits"

    id: int = Column(Integer, primary_key=True, autoincrement=True)
    season: int = Column(Integer, nullable=False, index=True)
    player_id: int = Column(Integer, nullable=False, index=True)
    split: str = Column(String(3), nullable=False)  # 'vsL' or 'vsR'
    pa: Optional[int] = Column(Integer, nullable=True)
    hits: Optional[int] = Column(Integer, nullable=True)
    doubles: Optional[int] = Column(Integer, nullable=True)
    triples: Optional[int] = Column(Integer, nullable=True)
    home_runs: Optional[int] = Column(Integer, nullable=True)
    walks: Optional[int] = Column(Integer, nullable=True)
    strikeouts: Optional[int] = Column(Integer, nullable=True)
    batting_avg: Optional[float] = Column(Float, nullable=True)
    on_base_pct: Optional[float] = Column(Float, nullable=True)
    slugging_pct: Optional[float] = Column(Float, nullable=True)
    iso: Optional[float] = Column(Float, nullable=True)
    k_pct: Optional[float] = Column(Float, nullable=True)
    bb_pct: Optional[float] = Column(Float, nullable=True)

    __table_args__ = (
        Index("ix_player_splits_season_player", "season", "player_id"),
    )


class PitcherAggregate(Base):
    """Rolling and seasonal aggregates for pitchers.

    Derived statistics computed from Statcast events over specified windows
    (e.g., 90/180/270/365 days) or entire seasons.  Fields include
    average velocity, spin rate, hard‑hit rate, strikeout and walk rates,
    expected wOBA and expected batting average.
    """

    __tablename__ = "pitcher_aggregates"

    id: int = Column(Integer, primary_key=True, autoincrement=True)
    pitcher_id: int = Column(Integer, nullable=False, index=True)
    window: str = Column(String(10), nullable=False)  # e.g., '90d', '180d', '2025'
    end_date: date = Column(Date, nullable=False, index=True)  # window end date
    avg_velocity: Optional[float] = Column(Float, nullable=True)
    avg_spin_rate: Optional[float] = Column(Float, nullable=True)
    hard_hit_pct: Optional[float] = Column(Float, nullable=True)
    k_pct: Optional[float] = Column(Float, nullable=True)
    bb_pct: Optional[float] = Column(Float, nullable=True)
    xwoba: Optional[float] = Column(Float, nullable=True)
    xba: Optional[float] = Column(Float, nullable=True)
    avg_horiz_break: Optional[float] = Column(Float, nullable=True)  # pfx_x
    avg_vert_break: Optional[float] = Column(Float, nullable=True)  # pfx_z
    avg_release_pos_x: Optional[float] = Column(Float, nullable=True)
    avg_release_pos_z: Optional[float] = Column(Float, nullable=True)
    avg_release_extension: Optional[float] = Column(Float, nullable=True)

    __table_args__ = (
        Index("ix_pitcher_aggregates_date_pitcher", "end_date", "pitcher_id"),
    )


class BatterAggregate(Base):
    """Rolling and seasonal aggregates for batters.

    Statistics computed from Statcast events to capture a batter's performance
    over various windows.  Metrics include average exit velocity, launch
    angle, hard‑hit rate, barrel rate, strikeout and walk rates, and
    batting average.
    """

    __tablename__ = "batter_aggregates"

    id: int = Column(Integer, primary_key=True, autoincrement=True)
    batter_id: int = Column(Integer, nullable=False, index=True)
    window: str = Column(String(10), nullable=False)  # e.g., '90d', '180d', '2025'
    end_date: date = Column(Date, nullable=False, index=True)
    avg_exit_velocity: Optional[float] = Column(Float, nullable=True)
    avg_launch_angle: Optional[float] = Column(Float, nullable=True)
    hard_hit_pct: Optional[float] = Column(Float, nullable=True)
    barrel_pct: Optional[float] = Column(Float, nullable=True)
    k_pct: Optional[float] = Column(Float, nullable=True)
    bb_pct: Optional[float] = Column(Float, nullable=True)
    batting_avg: Optional[float] = Column(Float, nullable=True)

    __table_args__ = (
        Index("ix_batter_aggregates_date_batter", "end_date", "batter_id"),
    )


class PitcherGameLog(Base):
    """Per-game pitching log for a single pitcher appearance.

    Each row represents one game start or relief appearance, capturing
    traditional box-score pitching lines (IP, hits, runs, earned runs,
    strikeouts, walks, home runs, pitch count) alongside the game date,
    season, opponent team abbreviation, and win/loss/no-decision result.
    """

    __tablename__ = "pitcher_game_log"

    id: int = Column(Integer, primary_key=True, autoincrement=True)
    pitcher_id: int = Column(Integer, nullable=False, index=True)
    season: int = Column(Integer, nullable=False, index=True)
    game_date: date = Column(Date, nullable=False, index=True)
    opponent: Optional[str] = Column(String(5), nullable=True)
    result: Optional[str] = Column(String(2), nullable=True)   # 'W', 'L', 'ND'
    ip: Optional[float] = Column(Float, nullable=True)
    hits: Optional[int] = Column(Integer, nullable=True)
    runs: Optional[int] = Column(Integer, nullable=True)
    earned_runs: Optional[int] = Column(Integer, nullable=True)
    strikeouts: Optional[int] = Column(Integer, nullable=True)
    walks: Optional[int] = Column(Integer, nullable=True)
    home_runs: Optional[int] = Column(Integer, nullable=True)
    pitches: Optional[int] = Column(Integer, nullable=True)

    __table_args__ = (
        Index("ix_pitcher_game_log_pitcher_date", "pitcher_id", "game_date"),
    )


class TeamRoster(Base):
    """Roster membership linking a player to a team for a given season.

    Tracks whether a player is a starter (``is_starter=True``) or reliever
    (``is_starter=False``) along with basic season-level pitching stats used
    to populate the rotation and bullpen sections of the team profile page.
    Non-pitchers are excluded; only pitching-role players are stored here.
    """

    __tablename__ = "team_roster"

    id: int = Column(Integer, primary_key=True, autoincrement=True)
    team_id: int = Column(Integer, nullable=False, index=True)
    season: int = Column(Integer, nullable=False, index=True)
    pitcher_id: int = Column(Integer, nullable=False, index=True)
    player_name: Optional[str] = Column(String(100), nullable=True)
    is_starter: bool = Column(Boolean, nullable=False, default=True)
    wins: Optional[int] = Column(Integer, nullable=True)
    losses: Optional[int] = Column(Integer, nullable=True)
    era: Optional[float] = Column(Float, nullable=True)
    whip: Optional[float] = Column(Float, nullable=True)
    k_pct: Optional[float] = Column(Float, nullable=True)
    bb_pct: Optional[float] = Column(Float, nullable=True)
    xfip: Optional[float] = Column(Float, nullable=True)
    ip: Optional[float] = Column(Float, nullable=True)
    saves: Optional[int] = Column(Integer, nullable=True)
    holds: Optional[int] = Column(Integer, nullable=True)
    next_start: Optional[date] = Column(Date, nullable=True)  # starters only

    __table_args__ = (
        Index("ix_team_roster_season_team", "season", "team_id"),
    )


class Matchup(Base):
    """Game‑level matchups combining team, pitcher and batter metrics.

    This table stores the feature vector used by the prediction model for each
    scheduled game.  It includes identifiers for home and away teams and
    pitchers, the game date, and optionally a computed win probability or
    prediction outcome.
    """

    __tablename__ = "matchups"

    id: int = Column(Integer, primary_key=True, autoincrement=True)
    game_date: date = Column(Date, nullable=False, index=True)
    home_team_id: int = Column(Integer, nullable=False)
    away_team_id: int = Column(Integer, nullable=False)
    home_pitcher_id: int = Column(Integer, nullable=False)
    away_pitcher_id: int = Column(Integer, nullable=False)
    # Fields below can store precomputed probabilities or scores
    home_win_prob: Optional[float] = Column(Float, nullable=True)
    away_win_prob: Optional[float] = Column(Float, nullable=True)
    prediction: Optional[float] = Column(Float, nullable=True)

    __table_args__ = (
        Index("ix_matchups_date_home_away", "game_date", "home_team_id", "away_team_id"),
    )


def get_engine(database_url: str):
    """Create a SQLAlchemy engine from the provided database URL.

    :param database_url: SQLAlchemy‑compatible connection string.  For example,
        ``postgresql+psycopg2://user:password@host:port/dbname``.
    :returns: An SQLAlchemy Engine instance.
    """
    return create_engine(database_url, echo=False, future=True)


def create_tables(engine) -> None:
    """Create all defined tables in the connected database.

    Call this function once during initialization to ensure the schema
    exists.  It will emit CREATE TABLE statements for any missing tables.

    :param engine: A SQLAlchemy Engine connected to the target database.
    """
    Base.metadata.create_all(engine)


def get_session(engine) -> sessionmaker:
    """Return a sessionmaker bound to the given engine.

    Use the returned sessionmaker to create database sessions in your
    application code.  Sessions should be created and closed within
    ``with`` blocks or explicitly closed when done.

    :param engine: SQLAlchemy Engine used for database connections.
    :returns: A sessionmaker class configured with autocommit=False and
        autoflush=False.
    """
    return sessionmaker(bind=engine, autocommit=False, autoflush=False, future=True)

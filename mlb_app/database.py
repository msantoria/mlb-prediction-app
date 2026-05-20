"""
Database models and utilities for the MLB prediction app.

This module defines the SQLAlchemy ORM models used to store raw Statcast
events, aggregated pitch-arsenal statistics, platoon splits, rolling/seasonal
metrics and game-level matchups. It also provides helper functions to
instantiate a database engine and session maker based on a connection URL.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from sqlalchemy import (
    JSON,
    Column,
    Date,
    DateTime,
    Float,
    Integer,
    String,
    create_engine,
    Index,
    inspect,
    text,
)
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker


Base = declarative_base()


class StatcastEvent(Base):
    """Pitch-level Statcast event data."""

    __tablename__ = "statcast_events"

    id: int = Column(Integer, primary_key=True, autoincrement=True)
    game_date: date = Column(Date, nullable=False, index=True)
    game_pk: Optional[int] = Column(Integer, nullable=True, index=True)
    at_bat_number: Optional[int] = Column(Integer, nullable=True)
    pitch_number: Optional[int] = Column(Integer, nullable=True)
    inning: Optional[int] = Column(Integer, nullable=True)
    inning_topbot: Optional[str] = Column(String(10), nullable=True)
    outs_when_up: Optional[int] = Column(Integer, nullable=True)
    home_team: Optional[str] = Column(String(10), nullable=True)
    away_team: Optional[str] = Column(String(10), nullable=True)
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
    description: Optional[str] = Column(String(60), nullable=True)
    launch_speed: Optional[float] = Column(Float, nullable=True)
    launch_angle: Optional[float] = Column(Float, nullable=True)
    estimated_woba_using_speedangle: Optional[float] = Column(Float, nullable=True)
    estimated_ba_using_speedangle: Optional[float] = Column(Float, nullable=True)
    stand: Optional[str] = Column(String(1), nullable=True)
    p_throws: Optional[str] = Column(String(1), nullable=True)

    __table_args__ = (
        Index("ix_statcast_events_date_pitcher", "game_date", "pitcher_id"),
        Index("ix_statcast_events_date_batter", "game_date", "batter_id"),
        Index("ix_statcast_events_batter_order", "batter_id", "game_date", "game_pk", "at_bat_number", "pitch_number"),
    )


class BatterPitchTypeMatchup(Base):
    """Restored hitter-centered hittingMatchups aggregate for Batter vs Arsenal."""

    __tablename__ = "batter_pitch_type_matchups"

    id: int = Column(Integer, primary_key=True, autoincrement=True)
    batter_id: int = Column(Integer, nullable=False, index=True)
    batter_name: Optional[str] = Column(String(120), nullable=True)
    batter_team_id: Optional[int] = Column(Integer, nullable=True, index=True)
    opposing_pitcher_id: int = Column(Integer, nullable=False, index=True)
    pitch_type: str = Column(String(5), nullable=False, index=True)
    game_pk: Optional[int] = Column(Integer, nullable=True, index=True)
    target_date: Optional[date] = Column(Date, nullable=True, index=True)
    date_start: Optional[date] = Column(Date, nullable=True)
    date_end: Optional[date] = Column(Date, nullable=True)
    days_back: Optional[int] = Column(Integer, nullable=True)
    source: Optional[str] = Column(String(40), nullable=True)

    raw_rows: Optional[int] = Column(Integer, nullable=True)
    deduped_rows: Optional[int] = Column(Integer, nullable=True)
    duplicate_rows_removed: Optional[int] = Column(Integer, nullable=True)
    pitches_seen: Optional[int] = Column(Integer, nullable=True)
    swings: Optional[int] = Column(Integer, nullable=True)
    whiffs: Optional[int] = Column(Integer, nullable=True)
    strikeouts: Optional[int] = Column(Integer, nullable=True)
    putaway_swings: Optional[int] = Column(Integer, nullable=True)
    two_strike_pitches: Optional[int] = Column(Integer, nullable=True)
    pa: Optional[int] = Column(Integer, nullable=True)
    pa_ended: Optional[int] = Column(Integer, nullable=True)
    ab: Optional[int] = Column(Integer, nullable=True)
    hits: Optional[int] = Column(Integer, nullable=True)

    batting_avg: Optional[float] = Column(Float, nullable=True)
    xwoba: Optional[float] = Column(Float, nullable=True)
    xba: Optional[float] = Column(Float, nullable=True)
    avg_ev: Optional[float] = Column(Float, nullable=True)
    avg_exit_velocity: Optional[float] = Column(Float, nullable=True)
    avg_la: Optional[float] = Column(Float, nullable=True)
    avg_launch_angle: Optional[float] = Column(Float, nullable=True)
    batted_ball_count: Optional[int] = Column(Integer, nullable=True)
    hard_hit_count: Optional[int] = Column(Integer, nullable=True)
    whiff_pct: Optional[float] = Column(Float, nullable=True)
    k_pct: Optional[float] = Column(Float, nullable=True)
    putaway_pct: Optional[float] = Column(Float, nullable=True)
    hardhit_pct: Optional[float] = Column(Float, nullable=True)
    hard_hit_pct: Optional[float] = Column(Float, nullable=True)

    refreshed_at: datetime = Column(DateTime, default=datetime.utcnow, nullable=False)

    __table_args__ = (
        Index(
            "ix_batter_pitch_type_matchups_lookup",
            "batter_id",
            "opposing_pitcher_id",
            "pitch_type",
            "target_date",
        ),
    )


class PitchArsenal(Base):
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

    __table_args__ = (Index("ix_pitch_arsenal_season_pitcher", "season", "pitcher_id"),)


class TeamSplit(Base):
    __tablename__ = "team_splits"

    id: int = Column(Integer, primary_key=True, autoincrement=True)
    season: int = Column(Integer, nullable=False, index=True)
    team_id: int = Column(Integer, nullable=False, index=True)
    split: str = Column(String(3), nullable=False)
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

    __table_args__ = (Index("ix_team_splits_season_team", "season", "team_id"),)


class PlayerSplit(Base):
    __tablename__ = "player_splits"

    id: int = Column(Integer, primary_key=True, autoincrement=True)
    season: int = Column(Integer, nullable=False, index=True)
    player_id: int = Column(Integer, nullable=False, index=True)
    split: str = Column(String(3), nullable=False)
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

    __table_args__ = (Index("ix_player_splits_season_player", "season", "player_id"),)


class PitcherAggregate(Base):
    __tablename__ = "pitcher_aggregates"

    id: int = Column(Integer, primary_key=True, autoincrement=True)
    pitcher_id: int = Column(Integer, nullable=False, index=True)
    window: str = Column(String(10), nullable=False)
    end_date: date = Column(Date, nullable=False, index=True)
    avg_velocity: Optional[float] = Column(Float, nullable=True)
    avg_spin_rate: Optional[float] = Column(Float, nullable=True)
    hard_hit_pct: Optional[float] = Column(Float, nullable=True)
    k_pct: Optional[float] = Column(Float, nullable=True)
    bb_pct: Optional[float] = Column(Float, nullable=True)
    xwoba: Optional[float] = Column(Float, nullable=True)
    xba: Optional[float] = Column(Float, nullable=True)
    avg_horiz_break: Optional[float] = Column(Float, nullable=True)
    avg_vert_break: Optional[float] = Column(Float, nullable=True)
    avg_release_pos_x: Optional[float] = Column(Float, nullable=True)
    avg_release_pos_z: Optional[float] = Column(Float, nullable=True)
    avg_release_extension: Optional[float] = Column(Float, nullable=True)

    __table_args__ = (Index("ix_pitcher_aggregates_date_pitcher", "end_date", "pitcher_id"),)


class BatterAggregate(Base):
    __tablename__ = "batter_aggregates"

    id: int = Column(Integer, primary_key=True, autoincrement=True)
    batter_id: int = Column(Integer, nullable=False, index=True)
    window: str = Column(String(10), nullable=False)
    end_date: date = Column(Date, nullable=False, index=True)
    avg_exit_velocity: Optional[float] = Column(Float, nullable=True)
    avg_launch_angle: Optional[float] = Column(Float, nullable=True)
    hard_hit_pct: Optional[float] = Column(Float, nullable=True)
    barrel_pct: Optional[float] = Column(Float, nullable=True)
    k_pct: Optional[float] = Column(Float, nullable=True)
    bb_pct: Optional[float] = Column(Float, nullable=True)
    batting_avg: Optional[float] = Column(Float, nullable=True)

    __table_args__ = (Index("ix_batter_aggregates_date_batter", "end_date", "batter_id"),)


class Matchup(Base):
    __tablename__ = "matchups"

    id: int = Column(Integer, primary_key=True, autoincrement=True)
    game_date: date = Column(Date, nullable=False, index=True)
    home_team_id: int = Column(Integer, nullable=False)
    away_team_id: int = Column(Integer, nullable=False)
    home_pitcher_id: int = Column(Integer, nullable=False)
    away_pitcher_id: int = Column(Integer, nullable=False)
    home_win_prob: Optional[float] = Column(Float, nullable=True)
    away_win_prob: Optional[float] = Column(Float, nullable=True)
    prediction: Optional[float] = Column(Float, nullable=True)

    __table_args__ = (Index("ix_matchups_date_home_away", "game_date", "home_team_id", "away_team_id"),)


class PitcherProfileOverview(Base):
    __tablename__ = "pitcher_profile_overview"

    id: int = Column(Integer, primary_key=True, autoincrement=True)
    player_id: int = Column(Integer, nullable=False, index=True)
    season: int = Column(Integer, nullable=False, index=True)
    player_name: Optional[str] = Column(String(120), nullable=True)
    team_id: Optional[int] = Column(Integer, nullable=True, index=True)
    team_name: Optional[str] = Column(String(120), nullable=True)
    era: Optional[float] = Column(Float, nullable=True)
    whip: Optional[float] = Column(Float, nullable=True)
    wins: Optional[int] = Column(Integer, nullable=True)
    losses: Optional[int] = Column(Integer, nullable=True)
    games_pitched: Optional[int] = Column(Integer, nullable=True)
    games_started: Optional[int] = Column(Integer, nullable=True)
    innings_pitched: Optional[float] = Column(Float, nullable=True)
    batters_faced: Optional[int] = Column(Integer, nullable=True)
    pitches_thrown: Optional[int] = Column(Integer, nullable=True)
    strikeouts: Optional[int] = Column(Integer, nullable=True)
    walks: Optional[int] = Column(Integer, nullable=True)
    home_runs_allowed: Optional[int] = Column(Integer, nullable=True)
    earned_runs: Optional[int] = Column(Integer, nullable=True)
    runs_allowed: Optional[int] = Column(Integer, nullable=True)
    hits_allowed: Optional[int] = Column(Integer, nullable=True)
    fip: Optional[float] = Column(Float, nullable=True)
    xfip: Optional[float] = Column(Float, nullable=True)
    siera: Optional[float] = Column(Float, nullable=True)
    xsiera: Optional[float] = Column(Float, nullable=True)
    k_pct: Optional[float] = Column(Float, nullable=True)
    bb_pct: Optional[float] = Column(Float, nullable=True)
    k_minus_bb_pct: Optional[float] = Column(Float, nullable=True)
    hr_per_9: Optional[float] = Column(Float, nullable=True)
    gb_pct: Optional[float] = Column(Float, nullable=True)
    fb_pct: Optional[float] = Column(Float, nullable=True)
    hr_fb_pct: Optional[float] = Column(Float, nullable=True)
    babip: Optional[float] = Column(Float, nullable=True)
    lob_pct: Optional[float] = Column(Float, nullable=True)
    xwoba_allowed: Optional[float] = Column(Float, nullable=True)
    xba_allowed: Optional[float] = Column(Float, nullable=True)
    hard_hit_pct: Optional[float] = Column(Float, nullable=True)
    barrel_pct: Optional[float] = Column(Float, nullable=True)
    avg_exit_velocity_allowed: Optional[float] = Column(Float, nullable=True)
    avg_launch_angle_allowed: Optional[float] = Column(Float, nullable=True)
    whiff_rate: Optional[float] = Column(Float, nullable=True)
    csw_rate: Optional[float] = Column(Float, nullable=True)
    avg_velocity: Optional[float] = Column(Float, nullable=True)
    avg_spin_rate: Optional[float] = Column(Float, nullable=True)
    avg_horiz_break: Optional[float] = Column(Float, nullable=True)
    avg_vert_break: Optional[float] = Column(Float, nullable=True)
    avg_release_pos_x: Optional[float] = Column(Float, nullable=True)
    avg_release_pos_z: Optional[float] = Column(Float, nullable=True)
    avg_release_extension: Optional[float] = Column(Float, nullable=True)
    arm_slot_label: Optional[str] = Column(String(40), nullable=True)
    source_priority_json = Column(JSON, nullable=True)
    metric_sources_json = Column(JSON, nullable=True)
    missing_inputs_json = Column(JSON, nullable=True)
    data_window_used: Optional[str] = Column(String(255), nullable=True)
    profile_source: str = Column(String(60), nullable=False, default="derived_serving_table")
    source_updated_at: Optional[datetime] = Column(DateTime, nullable=True)
    created_at: datetime = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: datetime = Column(DateTime, default=datetime.utcnow, nullable=False)

    __table_args__ = (
        Index("ix_pitcher_profile_overview_player_season", "player_id", "season", unique=True),
    )


class PitcherProfileArsenal(Base):
    __tablename__ = "pitcher_profile_arsenal"

    id: int = Column(Integer, primary_key=True, autoincrement=True)
    player_id: int = Column(Integer, nullable=False, index=True)
    season: int = Column(Integer, nullable=False, index=True)
    pitch_type: str = Column(String(5), nullable=False)
    pitch_name: Optional[str] = Column(String(50), nullable=True)
    pitch_count: Optional[int] = Column(Integer, nullable=True)
    usage_pct: Optional[float] = Column(Float, nullable=True)
    whiff_pct: Optional[float] = Column(Float, nullable=True)
    strikeout_pct: Optional[float] = Column(Float, nullable=True)
    batted_ball_count: Optional[int] = Column(Integer, nullable=True)
    xwoba: Optional[float] = Column(Float, nullable=True)
    hard_hit_pct: Optional[float] = Column(Float, nullable=True)
    avg_velocity: Optional[float] = Column(Float, nullable=True)
    avg_spin_rate: Optional[float] = Column(Float, nullable=True)
    avg_horiz_break: Optional[float] = Column(Float, nullable=True)
    avg_vert_break: Optional[float] = Column(Float, nullable=True)
    avg_release_pos_x: Optional[float] = Column(Float, nullable=True)
    avg_release_pos_z: Optional[float] = Column(Float, nullable=True)
    avg_release_extension: Optional[float] = Column(Float, nullable=True)
    source: Optional[str] = Column(String(60), nullable=True)
    source_window: Optional[str] = Column(String(120), nullable=True)
    quality_flags_json = Column(JSON, nullable=True)
    source_updated_at: Optional[datetime] = Column(DateTime, nullable=True)
    created_at: datetime = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: datetime = Column(DateTime, default=datetime.utcnow, nullable=False)

    __table_args__ = (
        Index("ix_pitcher_profile_arsenal_player_season_pitch", "player_id", "season", "pitch_type", unique=True),
    )


class PitcherProfileRecentGame(Base):
    __tablename__ = "pitcher_profile_recent_games"

    id: int = Column(Integer, primary_key=True, autoincrement=True)
    player_id: int = Column(Integer, nullable=False, index=True)
    game_pk: Optional[int] = Column(Integer, nullable=True, index=True)
    game_date: date = Column(Date, nullable=False, index=True)
    pitch_count: Optional[int] = Column(Integer, nullable=True)
    plate_appearances: Optional[int] = Column(Integer, nullable=True)
    strikeouts: Optional[int] = Column(Integer, nullable=True)
    walks: Optional[int] = Column(Integer, nullable=True)
    home_runs: Optional[int] = Column(Integer, nullable=True)
    hard_hit_pct: Optional[float] = Column(Float, nullable=True)
    avg_velocity: Optional[float] = Column(Float, nullable=True)
    source_updated_at: Optional[datetime] = Column(DateTime, nullable=True)
    created_at: datetime = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: datetime = Column(DateTime, default=datetime.utcnow, nullable=False)

    __table_args__ = (
        Index("ix_pitcher_profile_recent_games_player_game", "player_id", "game_date", "game_pk", unique=True),
    )


STATCAST_EVENT_SAFE_COLUMNS = {
    "game_pk": "INTEGER",
    "at_bat_number": "INTEGER",
    "pitch_number": "INTEGER",
    "inning": "INTEGER",
    "inning_topbot": "VARCHAR(10)",
    "outs_when_up": "INTEGER",
    "home_team": "VARCHAR(10)",
    "away_team": "VARCHAR(10)",
    "description": "VARCHAR(60)",
    "estimated_woba_using_speedangle": "FLOAT",
    "estimated_ba_using_speedangle": "FLOAT",
}


def _ensure_statcast_event_columns(engine) -> None:
    """Add missing nullable Statcast ordering and hitter-quality columns without touching existing data.

    This is intentionally additive only. It never drops tables, deletes rows,
    rewrites existing values, or changes cron/refresh behavior.
    """
    try:
        inspector = inspect(engine)
        if "statcast_events" not in inspector.get_table_names():
            return
        existing_columns = {col["name"] for col in inspector.get_columns("statcast_events")}
        missing_columns = {
            name: sql_type
            for name, sql_type in STATCAST_EVENT_SAFE_COLUMNS.items()
            if name not in existing_columns
        }
        if not missing_columns:
            return
        dialect = engine.dialect.name
        with engine.begin() as conn:
            for name, sql_type in missing_columns.items():
                if dialect == "postgresql":
                    stmt = text(f"ALTER TABLE statcast_events ADD COLUMN IF NOT EXISTS {name} {sql_type}")
                else:
                    stmt = text(f"ALTER TABLE statcast_events ADD COLUMN {name} {sql_type}")
                try:
                    conn.execute(stmt)
                except Exception as exc:
                    if "duplicate column" in str(exc).lower() or "already exists" in str(exc).lower():
                        continue
                    raise
    except Exception as exc:
        print(f"[database] Non-fatal statcast_events schema guard skipped: {exc}")


def get_engine(database_url: str):
    return create_engine(database_url, echo=False, future=True)


def create_tables(engine) -> None:
    Base.metadata.create_all(engine)
    _ensure_statcast_event_columns(engine)


def get_session(engine) -> sessionmaker:
    return sessionmaker(bind=engine, autocommit=False, autoflush=False, future=True)

"""
Database models and utilities for the MLB prediction app.

This module defines the SQLAlchemy ORM models used to store raw Statcast
events, aggregated pitch-arsenal statistics, platoon splits, rolling/seasonal
metrics and game-level matchups. It also provides helper functions to
instantiate a database engine and session maker based on a connection URL.
"""

from __future__ import annotations

from datetime import date, datetime
import uuid
from typing import Optional

from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    Date,
    DateTime,
    Float,
    Integer,
    String,
    Text,
    UniqueConstraint,
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
        Index(
            "ux_statcast_events_pitch_identity",
            "game_pk",
            "at_bat_number",
            "pitch_number",
            unique=True,
            postgresql_where=text(
                "game_pk IS NOT NULL AND at_bat_number IS NOT NULL AND pitch_number IS NOT NULL"
            ),
            sqlite_where=text(
                "game_pk IS NOT NULL AND at_bat_number IS NOT NULL AND pitch_number IS NOT NULL"
            ),
        ),
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


class AppUser(Base):
    __tablename__ = "app_users"

    id: int = Column(Integer, primary_key=True, autoincrement=True)
    email: str = Column(String(255), nullable=False, unique=True, index=True)
    username: str = Column(String(80), nullable=False, index=True)
    password_hash: Optional[str] = Column(String(255), nullable=True)
    created_at: datetime = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: datetime = Column(DateTime, default=datetime.utcnow, nullable=False)


class AppUserRole(Base):
    """Additive server-owned role assignment for application users."""

    __tablename__ = "app_user_roles"

    id: int = Column(Integer, primary_key=True, autoincrement=True)
    user_id: int = Column(Integer, nullable=False, unique=True, index=True)
    role: str = Column(String(32), nullable=False, default="user", index=True)
    assignment_source: str = Column(String(64), nullable=False)
    assigned_at: datetime = Column(DateTime, default=datetime.utcnow, nullable=False)
    verified_at: Optional[datetime] = Column(DateTime, nullable=True)
    updated_at: datetime = Column(DateTime, default=datetime.utcnow, nullable=False)

    __table_args__ = (
        Index("ix_app_user_roles_role_user", "role", "user_id"),
    )


class AppUserPreference(Base):
    __tablename__ = "app_user_preferences"

    id: int = Column(Integer, primary_key=True, autoincrement=True)
    user_id: int = Column(Integer, nullable=False, unique=True, index=True)
    wants_newsletter: bool = Column(Boolean, nullable=False, default=False)
    feature_interests_json = Column(JSON, nullable=True)
    plan_type: Optional[str] = Column(String(64), nullable=True)
    created_at: datetime = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: datetime = Column(DateTime, default=datetime.utcnow, nullable=False)


class AppUserDirectoryProfile(Base):
    """Additive administrative metadata for an existing ``app_users`` row."""

    __tablename__ = "app_user_directory_profiles"

    id: int = Column(Integer, primary_key=True, autoincrement=True)
    user_id: int = Column(Integer, nullable=False, unique=True, index=True)
    public_id: str = Column(
        String(36),
        nullable=False,
        unique=True,
        index=True,
        default=lambda: str(uuid.uuid4()),
    )
    first_name: Optional[str] = Column(String(80), nullable=True)
    last_name: Optional[str] = Column(String(80), nullable=True)
    display_name: Optional[str] = Column(String(160), nullable=True)
    alias: Optional[str] = Column(String(80), nullable=True)
    title: Optional[str] = Column(String(120), nullable=True)
    company: Optional[str] = Column(String(160), nullable=True)
    is_active: bool = Column(Boolean, nullable=False, default=True, index=True)
    is_locked: bool = Column(Boolean, nullable=False, default=False, index=True)
    locale: str = Column(String(32), nullable=False, default="en_US")
    language: str = Column(String(16), nullable=False, default="en")
    timezone: str = Column(String(64), nullable=False, default="America/New_York")
    session_version: int = Column(Integer, nullable=False, default=1)
    last_login_at: Optional[datetime] = Column(DateTime, nullable=True)
    created_by_user_id: Optional[int] = Column(Integer, nullable=True)
    updated_by_user_id: Optional[int] = Column(Integer, nullable=True)
    created_at: datetime = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: datetime = Column(DateTime, default=datetime.utcnow, nullable=False)


class FederatedIdentity(Base):
    """Provider subject mapping only; credentials and provider tokens never belong here."""

    __tablename__ = "federated_identities"

    id: int = Column(Integer, primary_key=True, autoincrement=True)
    public_id: str = Column(
        String(36),
        nullable=False,
        unique=True,
        index=True,
        default=lambda: str(uuid.uuid4()),
    )
    user_id: int = Column(Integer, nullable=False, index=True)
    provider: str = Column(String(64), nullable=False)
    issuer: str = Column(String(255), nullable=False)
    subject: str = Column(String(255), nullable=False)
    federation_identifier: Optional[str] = Column(String(255), nullable=True, index=True)
    verified_at: Optional[datetime] = Column(DateTime, nullable=True)
    last_authenticated_at: Optional[datetime] = Column(DateTime, nullable=True)
    created_at: datetime = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: datetime = Column(DateTime, default=datetime.utcnow, nullable=False)

    __table_args__ = (
        UniqueConstraint("issuer", "subject", name="uq_federated_identity_issuer_subject"),
    )


class AppAccessProfile(Base):
    """Persisted catalog identity for code-owned role/capability profiles."""

    __tablename__ = "app_access_profiles"

    id: int = Column(Integer, primary_key=True, autoincrement=True)
    profile_key: str = Column(String(64), nullable=False, unique=True, index=True)
    label: str = Column(String(120), nullable=False)
    role: str = Column(String(32), nullable=False, unique=True, index=True)
    description: Optional[str] = Column(String(500), nullable=True)
    created_at: datetime = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: datetime = Column(DateTime, default=datetime.utcnow, nullable=False)



class CanonicalBaserunningProductionObservation(Base):
    """Immutable canonical production-monitoring observation."""

    __tablename__ = (
        "canonical_baserunning_production_observations"
    )

    id: int = Column(
        Integer,
        primary_key=True,
        autoincrement=True,
    )
    game_pk: int = Column(
        Integer,
        nullable=False,
        index=True,
    )
    game_date: date = Column(
        Date,
        nullable=False,
        index=True,
    )
    canonical_run_id: str = Column(
        String(128),
        nullable=False,
    )
    observation_digest: str = Column(
        String(64),
        nullable=False,
        unique=True,
        index=True,
    )
    paired_context_digest: str = Column(
        String(64),
        nullable=False,
    )
    calibrated_transform_digest: str = Column(
        String(64),
        nullable=False,
        index=True,
    )
    simulation_count: int = Column(
        Integer,
        nullable=False,
    )
    status: str = Column(
        String(24),
        nullable=False,
    )
    ready: bool = Column(
        Boolean,
        nullable=False,
    )
    production_activation: bool = Column(
        Boolean,
        nullable=False,
    )
    authoritative_source: str = Column(
        String(96),
        nullable=False,
    )
    payload_json = Column(
        JSON,
        nullable=False,
    )
    created_at: datetime = Column(
        DateTime,
        default=datetime.utcnow,
        nullable=False,
    )

    __table_args__ = (
        Index(
            "ix_canonical_baserunning_monitor_game",
            "game_date",
            "game_pk",
        ),
    )


class CanonicalBaserunningProductionSettlement(Base):
    """Immutable postgame settlement for one production observation."""

    __tablename__ = (
        "canonical_baserunning_production_settlements"
    )

    id: int = Column(
        Integer,
        primary_key=True,
        autoincrement=True,
    )
    monitoring_observation_digest: str = Column(
        String(64),
        nullable=False,
        unique=True,
        index=True,
    )
    settlement_digest: str = Column(
        String(64),
        nullable=False,
        unique=True,
        index=True,
    )
    game_pk: int = Column(
        Integer,
        nullable=False,
        unique=True,
        index=True,
    )
    game_date: date = Column(
        Date,
        nullable=False,
        index=True,
    )
    canonical_run_id: str = Column(
        String(128),
        nullable=False,
    )
    observed_source_version: str = Column(
        String(96),
        nullable=False,
    )
    observed_source_digest: str = Column(
        String(64),
        nullable=False,
    )
    observed_stolen_bases: int = Column(
        Integer,
        nullable=False,
    )
    observed_caught_stealing: int = Column(
        Integer,
        nullable=False,
    )
    comparison_json = Column(
        JSON,
        nullable=False,
    )
    payload_json = Column(
        JSON,
        nullable=False,
    )
    created_at: datetime = Column(
        DateTime,
        default=datetime.utcnow,
        nullable=False,
    )

    __table_args__ = (
        Index(
            "ix_canonical_baserunning_settlement_game",
            "game_date",
            "game_pk",
        ),
    )



class AppGlobalSetting(Base):
    __tablename__ = "app_global_settings"

    id: int = Column(Integer, primary_key=True, autoincrement=True)
    namespace: str = Column(String(64), nullable=False)
    setting_key: str = Column(String(128), nullable=False)
    value_type: str = Column(String(24), nullable=False)
    value_json = Column(JSON, nullable=True)
    default_value_json = Column(JSON, nullable=True)
    validation_json = Column(JSON, nullable=True)
    description: Optional[str] = Column(String(500), nullable=True)
    environment_override: bool = Column(Boolean, nullable=False, default=False)
    sensitive_reference: Optional[str] = Column(String(255), nullable=True)
    updated_by_user_id: Optional[int] = Column(Integer, nullable=True)
    created_at: datetime = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: datetime = Column(DateTime, default=datetime.utcnow, nullable=False)

    __table_args__ = (
        UniqueConstraint("namespace", "setting_key", name="uq_app_global_setting_key"),
    )


class SharedReportArtifact(Base):
    """Durable cross-worker payload for warmed report and projection reads."""

    __tablename__ = "shared_report_artifacts"

    id: int = Column(Integer, primary_key=True, autoincrement=True)
    artifact_key: str = Column(String(255), nullable=False, unique=True, index=True)
    artifact_type: str = Column(String(80), nullable=False, index=True)
    target_date: date = Column(Date, nullable=False, index=True)
    payload_json = Column(JSON, nullable=False)
    row_count: int = Column(Integer, nullable=False, default=0)
    generated_at: datetime = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at: datetime = Column(DateTime, nullable=False, default=datetime.utcnow)

    __table_args__ = (
        Index("ix_shared_report_artifact_type_date", "artifact_type", "target_date"),
    )


class AppUserSetting(Base):
    __tablename__ = "app_user_settings"

    id: int = Column(Integer, primary_key=True, autoincrement=True)
    user_id: int = Column(Integer, nullable=False, index=True)
    namespace: str = Column(String(64), nullable=False)
    setting_key: str = Column(String(128), nullable=False)
    value_type: str = Column(String(24), nullable=False)
    value_json = Column(JSON, nullable=True)
    updated_at: datetime = Column(DateTime, default=datetime.utcnow, nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "namespace",
            "setting_key",
            name="uq_app_user_setting_key",
        ),
    )


class AppFeatureFlag(Base):
    __tablename__ = "app_feature_flags"

    id: int = Column(Integer, primary_key=True, autoincrement=True)
    flag_key: str = Column(String(128), nullable=False, unique=True, index=True)
    enabled: bool = Column(Boolean, nullable=False, default=False)
    target_profiles_json = Column(JSON, nullable=True)
    updated_by_user_id: Optional[int] = Column(Integer, nullable=True)
    created_at: datetime = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: datetime = Column(DateTime, default=datetime.utcnow, nullable=False)


class AppAdminAuditEvent(Base):
    __tablename__ = "app_admin_audit_events"

    id: int = Column(Integer, primary_key=True, autoincrement=True)
    public_id: str = Column(
        String(36),
        nullable=False,
        unique=True,
        index=True,
        default=lambda: str(uuid.uuid4()),
    )
    actor_user_id: int = Column(Integer, nullable=False, index=True)
    actor_session_id: Optional[int] = Column(Integer, nullable=True, index=True)
    action: str = Column(String(128), nullable=False, index=True)
    target_type: str = Column(String(64), nullable=False, index=True)
    target_identifier: str = Column(String(255), nullable=False)
    before_json = Column(JSON, nullable=True)
    after_json = Column(JSON, nullable=True)
    source: str = Column(String(64), nullable=False, default="control_center_api")
    created_at: datetime = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)


class AppLoginHistory(Base):
    __tablename__ = "app_login_history"

    id: int = Column(Integer, primary_key=True, autoincrement=True)
    user_id: int = Column(Integer, nullable=False, index=True)
    session_id: Optional[int] = Column(Integer, nullable=True, index=True)
    authentication_method: str = Column(String(64), nullable=False, default="password")
    successful: bool = Column(Boolean, nullable=False, default=True)
    created_at: datetime = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)


class AppDashboardFolder(Base):
    __tablename__ = "app_dashboard_folders"

    id: int = Column(Integer, primary_key=True, autoincrement=True)
    user_id: int = Column(Integer, nullable=False, index=True)
    folder_name: str = Column(String(255), nullable=False)
    folder_date: Optional[date] = Column(Date, nullable=True, index=True)
    is_default: bool = Column(Boolean, nullable=False, default=False)
    created_at: datetime = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: datetime = Column(DateTime, default=datetime.utcnow, nullable=False)

    __table_args__ = (
        Index("ix_app_dashboard_folders_user_default", "user_id", "is_default"),
        Index("ix_app_dashboard_folders_user_date", "user_id", "folder_date"),
    )


class AppDashboardItem(Base):
    __tablename__ = "app_dashboard_items"

    id: int = Column(Integer, primary_key=True, autoincrement=True)
    user_id: int = Column(Integer, nullable=False, index=True)
    folder_id: int = Column(Integer, nullable=False, index=True)
    source_tab: str = Column(String(100), nullable=False, index=True)
    source_type: str = Column(String(100), nullable=False, index=True)
    title: str = Column(String(255), nullable=False)
    subtitle: Optional[str] = Column(String(255), nullable=True)
    payload_json = Column(JSON, nullable=False)
    filter_json = Column(JSON, nullable=True)
    sort_json = Column(JSON, nullable=True)
    pin_order: Optional[int] = Column(Integer, nullable=True)
    notes: Optional[str] = Column(Text, nullable=True)
    created_at: datetime = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: datetime = Column(DateTime, default=datetime.utcnow, nullable=False)

    __table_args__ = (
        Index("ix_app_dashboard_items_user_folder", "user_id", "folder_id"),
        Index("ix_app_dashboard_items_source", "source_tab", "source_type"),
    )


class AppSession(Base):
    __tablename__ = "app_sessions"

    id: int = Column(Integer, primary_key=True, autoincrement=True)
    user_id: int = Column(Integer, nullable=False, index=True)
    session_token: str = Column(String(128), nullable=False, unique=True, index=True)
    expires_at: datetime = Column(DateTime, nullable=False, index=True)
    created_at: datetime = Column(DateTime, default=datetime.utcnow, nullable=False)
    last_seen_at: datetime = Column(DateTime, default=datetime.utcnow, nullable=False)


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


def _ensure_dashboard_snapshot_lineup_status_width(engine) -> None:
    """Widen the deployed PostgreSQL column for canonical activity reasons."""

    inspector = inspect(engine)
    table_name = "dashboard_player_snapshots"
    if table_name not in inspector.get_table_names():
        return
    lineup_status = next(
        (column for column in inspector.get_columns(table_name) if column["name"] == "lineup_status"),
        None,
    )
    if lineup_status is None:
        return
    current_length = getattr(lineup_status["type"], "length", None)
    if current_length is None or current_length >= 80 or engine.dialect.name != "postgresql":
        return
    with engine.begin() as conn:
        conn.execute(text(
            "ALTER TABLE dashboard_player_snapshots "
            "ALTER COLUMN lineup_status TYPE VARCHAR(80)"
        ))


def get_engine(database_url: str):
    return create_engine(database_url, echo=False, future=True)


def create_tables(engine) -> None:
    # Register dashboard object tables before metadata creation. Kept local to
    # avoid a database -> model -> database import cycle at module import time.
    from . import dashboard_object_models  # noqa: F401
    from . import final_game_snapshots  # noqa: F401

    Base.metadata.create_all(engine)
    _ensure_dashboard_snapshot_lineup_status_width(engine)
    _ensure_statcast_event_columns(engine)


def get_session(engine) -> sessionmaker:
    return sessionmaker(bind=engine, autocommit=False, autoflush=False, future=True)

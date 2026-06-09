"""SQLAlchemy models for the KIBL sportsbook integration.

These models are defined in a separate module to avoid cluttering
``mlb_app/database.py``.  They are imported by the main database
module when migrations run, ensuring that SQLAlchemy is aware of
them.  The models use the global ``Base`` defined in
``mlb_app.database``.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import Column, Integer, String, JSON, DateTime, Index

from mlb_app.database import Base


class KiblFixture(Base):
    """Normalized fixture record from KIBL.

    Each row corresponds to a single sporting event (game) returned by
    the ``/info/fixtures/`` endpoint.  The combination of
    ``external_id`` and ``feed_source_id`` should be unique.  Raw
    payloads are preserved for troubleshooting and future schema
    evolution.
    """

    __tablename__ = "kibl_fixtures"

    id: int = Column(Integer, primary_key=True, autoincrement=True)
    external_id: str = Column(String(64), nullable=False, index=True)
    feed_source_id: int = Column(Integer, nullable=False, index=True)
    betting_type_id: int = Column(Integer, nullable=False, index=True)
    league_id: str = Column(String(64), nullable=True)
    sport: str = Column(String(64), nullable=True)
    league: str = Column(String(128), nullable=True)
    home_team: str = Column(String(128), nullable=True)
    away_team: str = Column(String(128), nullable=True)
    start_time: str = Column(String(32), nullable=True)
    last_updated: str = Column(String(32), nullable=True)
    inserted_on: str = Column(String(32), nullable=True)
    raw: Any = Column(JSON, nullable=False)
    created_at: datetime = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: datetime = Column(DateTime, default=datetime.utcnow, nullable=False)

    __table_args__ = (
        Index(
            "ix_kibl_fixtures_unique",
            "external_id",
            "feed_source_id",
            unique=True,
        ),
    )


class KiblMarket(Base):
    """Normalized market/odds record from KIBL.

    Each row corresponds to a market selection (e.g. moneyline, spread,
    total) for a fixture.  The combination of ``market_id``,
    ``selection_id``, and ``feed_source_id`` should be unique.
    """

    __tablename__ = "kibl_markets"

    id: int = Column(Integer, primary_key=True, autoincrement=True)
    market_id: str = Column(String(64), nullable=False, index=True)
    selection_id: str = Column(String(64), nullable=False, index=True)
    fixture_external_id: str = Column(String(64), nullable=False, index=True)
    feed_source_id: int = Column(Integer, nullable=False, index=True)
    betting_type_id: int = Column(Integer, nullable=False, index=True)
    market_name: str = Column(String(128), nullable=True)
    selection_name: str = Column(String(128), nullable=True)
    price: str = Column(String(32), nullable=True)
    line: str = Column(String(32), nullable=True)
    status: str = Column(String(32), nullable=True)
    last_updated: str = Column(String(32), nullable=True)
    inserted_on: str = Column(String(32), nullable=True)
    raw: Any = Column(JSON, nullable=False)
    created_at: datetime = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: datetime = Column(DateTime, default=datetime.utcnow, nullable=False)

    __table_args__ = (
        Index(
            "ix_kibl_markets_unique",
            "market_id",
            "selection_id",
            "feed_source_id",
            unique=True,
        ),
    )


class KiblSyncWatermark(Base):
    """Tracks the latest sync watermark per KIBL endpoint and filter set.

    A watermark identifies the most recent ``last_updated`` or
    ``inserted_on`` timestamp processed for a given combination of
    endpoint, feed_source_id, betting_type_id, and league_id.  This
    value is used as the ``since_last_updated`` parameter when polling
    for diffs.  Watermarks are updated only after successful
    persistence of diff results.
    """

    __tablename__ = "kibl_sync_watermarks"

    id: int = Column(Integer, primary_key=True, autoincrement=True)
    source_name: str = Column(String(32), nullable=False, index=True)
    endpoint: str = Column(String(64), nullable=False, index=True)
    feed_source_id: int = Column(Integer, nullable=False, index=True)
    betting_type_id: int = Column(Integer, nullable=False, index=True)
    league_id: str = Column(String(64), nullable=False, index=True)
    last_watermark: str = Column(String(32), nullable=True)
    updated_at: datetime = Column(DateTime, default=datetime.utcnow, nullable=False)

    __table_args__ = (
        Index(
            "ix_kibl_sync_watermark_unique",
            "source_name",
            "endpoint",
            "feed_source_id",
            "betting_type_id",
            "league_id",
            unique=True,
        ),
    )

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

from typing import List, Optional

from sqlalchemy.orm import Session

from .database import (
    StatcastEvent,
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


def get_pitcher_game_log(
    session: Session, pitcher_id: int, limit: int = 5
) -> List[dict]:
    """Return per-game pitching stats for a pitcher's most recent outings.

    Groups ``StatcastEvent`` rows by ``game_date`` and computes inning-level
    counting stats for each appearance.  Only games where the pitcher recorded
    at least one pitch are included.

    Stat definitions
    ~~~~~~~~~~~~~~~~
    * **ip** – innings pitched, approximated as ``(outs_recorded / 3)``.
      An out is counted for any ``events`` value that ends a plate appearance
      without a hit or walk (strikeouts, ground-outs, fly-outs, etc.).
    * **h** – hits (single, double, triple, home_run).
    * **r / er** – runs and earned runs are not tracked in Statcast pitch-level
      data, so both are set to ``None``.
    * **k** – strikeouts (``strikeout`` or ``strikeout_double_play``).
    * **bb** – walks (``walk``).
    * **hr** – home runs (``home_run``).

    Parameters
    ----------
    session : Session
        Active SQLAlchemy database session.
    pitcher_id : int
        MLBAM identifier for the pitcher.
    limit : int, optional
        Maximum number of recent games to return (default: 5).

    Returns
    -------
    list of dict
        Each element represents one game appearance::

            {
                "date": "2026-04-11",
                "ip": 6.0,
                "h": 5,
                "r": None,
                "er": None,
                "k": 7,
                "bb": 2,
                "hr": 0,
            }

        Returned in reverse chronological order (most recent first).
    """
    # Fetch all pitch-level events for this pitcher, ordered by date desc.
    # We pull only the columns we need to keep the query light.
    rows = (
        session.query(StatcastEvent.game_date, StatcastEvent.events)
        .filter(StatcastEvent.pitcher_id == pitcher_id)
        .order_by(StatcastEvent.game_date.desc())
        .all()
    )

    if not rows:
        return []

    # Group by game_date (rows are already sorted desc, so we process in order)
    from collections import defaultdict

    games_events: dict = defaultdict(list)
    for game_date, events in rows:
        games_events[game_date].append(events or "")

    # Terminal plate-appearance events that record an out
    OUT_EVENTS = {
        "strikeout",
        "strikeout_double_play",
        "field_out",
        "force_out",
        "grounded_into_double_play",
        "double_play",
        "triple_play",
        "fielders_choice_out",
        "sac_fly",
        "sac_bunt",
        "sac_fly_double_play",
        "caught_stealing_2b",
        "caught_stealing_3b",
        "caught_stealing_home",
        "pickoff_1b",
        "pickoff_2b",
        "pickoff_3b",
        "other_out",
    }
    HIT_EVENTS = {"single", "double", "triple", "home_run"}
    K_EVENTS = {"strikeout", "strikeout_double_play"}
    BB_EVENTS = {"walk", "intent_walk"}
    HR_EVENTS = {"home_run"}

    game_log: List[dict] = []
    # Iterate in reverse-chronological order (defaultdict preserves insertion order
    # in Python 3.7+, and rows were fetched desc)
    for game_date in list(games_events.keys())[:limit]:
        event_list = games_events[game_date]
        outs = sum(1 for e in event_list if e in OUT_EVENTS)
        hits = sum(1 for e in event_list if e in HIT_EVENTS)
        ks = sum(1 for e in event_list if e in K_EVENTS)
        bbs = sum(1 for e in event_list if e in BB_EVENTS)
        hrs = sum(1 for e in event_list if e in HR_EVENTS)
        ip = round(outs / 3, 1)

        game_log.append(
            {
                "date": game_date.isoformat() if hasattr(game_date, "isoformat") else str(game_date),
                "ip": ip,
                "h": hits,
                "r": None,   # not available at pitch level
                "er": None,  # not available at pitch level
                "k": ks,
                "bb": bbs,
                "hr": hrs,
            }
        )

    return game_log


__all__ = [
    "get_pitcher_aggregate",
    "get_batter_aggregate",
    "get_pitch_arsenal",
    "get_player_split",
    "get_team_split",
    "get_pitcher_game_log",
]

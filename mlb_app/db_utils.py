from __future__ import annotations

import datetime
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd
from sqlalchemy.orm import Session

from .database import BatterAggregate, PitchArsenal, PitcherAggregate, PlayerSplit, StatcastEvent, TeamSplit


def get_pitcher_aggregate(session: Session, pitcher_id: int, window: str) -> Optional[PitcherAggregate]:
    return (
        session.query(PitcherAggregate)
        .filter(PitcherAggregate.pitcher_id == pitcher_id, PitcherAggregate.window == window)
        .order_by(PitcherAggregate.end_date.desc())
        .first()
    )


def get_pitcher_aggregate_with_fallback(session: Session, pitcher_id: int, current_season: Optional[int] = None) -> Tuple[Optional[PitcherAggregate], Optional[str]]:
    if current_season is None:
        current_season = datetime.date.today().year
    agg = get_pitcher_aggregate(session, pitcher_id, "90d")
    if agg:
        return agg, "Last 90 Days"
    for window, label in [(str(current_season), f"{current_season} Season"), (str(current_season - 1), f"{current_season - 1} Season"), (str(current_season - 2), f"{current_season - 2} Season"), (str(current_season - 3), f"{current_season - 3} Season")]:
        agg = get_pitcher_aggregate(session, pitcher_id, window)
        if agg:
            return agg, label
    return None, None


def get_batter_aggregate(session: Session, batter_id: int, window: str) -> Optional[BatterAggregate]:
    return (
        session.query(BatterAggregate)
        .filter(BatterAggregate.batter_id == batter_id, BatterAggregate.window == window)
        .order_by(BatterAggregate.end_date.desc())
        .first()
    )


def get_batter_aggregate_with_fallback(session: Session, batter_id: int, current_season: Optional[int] = None) -> Tuple[Optional[BatterAggregate], Optional[str]]:
    if current_season is None:
        current_season = datetime.date.today().year
    agg = get_batter_aggregate(session, batter_id, "90d")
    if agg:
        return agg, "Last 90 Days"
    for window, label in [(str(current_season), f"{current_season} Season"), (str(current_season - 1), f"{current_season - 1} Season"), (str(current_season - 2), f"{current_season - 2} Season"), (str(current_season - 3), f"{current_season - 3} Season")]:
        agg = get_batter_aggregate(session, batter_id, window)
        if agg:
            return agg, label
    return None, None


def get_pitch_arsenal(session: Session, pitcher_id: int, season: int) -> List[PitchArsenal]:
    return (
        session.query(PitchArsenal)
        .filter(PitchArsenal.pitcher_id == pitcher_id, PitchArsenal.season == season)
        .order_by(PitchArsenal.usage_pct.desc())
        .all()
    )


def get_pitch_arsenal_with_fallback(session: Session, pitcher_id: int, current_season: Optional[int] = None) -> Tuple[List[PitchArsenal], Optional[int]]:
    if current_season is None:
        current_season = datetime.date.today().year
    for season in [current_season, current_season - 1, current_season - 2]:
        arsenal = get_pitch_arsenal(session, pitcher_id, season)
        if arsenal:
            return arsenal, season
    return [], None


def get_player_split(session: Session, player_id: int, season: int, split: str) -> Optional[PlayerSplit]:
    return (
        session.query(PlayerSplit)
        .filter(PlayerSplit.player_id == player_id, PlayerSplit.season == season, PlayerSplit.split == split)
        .first()
    )


def get_team_split(session: Session, team_id: int, season: int, split: str) -> Optional[TeamSplit]:
    return (
        session.query(TeamSplit)
        .filter(TeamSplit.team_id == team_id, TeamSplit.season == season, TeamSplit.split == split)
        .first()
    )


def _events_to_pitcher_df(events: List[StatcastEvent]) -> pd.DataFrame:
    return pd.DataFrame([
        {
            "release_speed": e.release_speed,
            "release_spin_rate": e.release_spin_rate,
            "launch_speed": e.launch_speed,
            "events": e.events or "",
            "description": "",
            "pfx_x": e.pfx_x,
            "pfx_z": e.pfx_z,
            "release_pos_x": None,
            "release_pos_z": None,
            "release_extension": None,
            "estimated_woba_using_speedangle": None,
            "estimated_ba_using_speedangle": None,
        }
        for e in events
    ])


def _events_to_batter_df(events: List[StatcastEvent]) -> pd.DataFrame:
    return pd.DataFrame([
        {"launch_speed": e.launch_speed, "launch_angle": e.launch_angle, "events": e.events or ""}
        for e in events
    ])


def get_pitcher_rolling_by_games(session: Session, pitcher_id: int, n_games: int) -> Optional[Dict[str, Any]]:
    date_rows = (
        session.query(StatcastEvent.game_date)
        .filter(StatcastEvent.pitcher_id == pitcher_id)
        .distinct()
        .order_by(StatcastEvent.game_date.desc())
        .limit(n_games)
        .all()
    )
    if not date_rows:
        return None
    date_list = [r[0] for r in date_rows]
    events = (
        session.query(StatcastEvent)
        .filter(StatcastEvent.pitcher_id == pitcher_id, StatcastEvent.game_date.in_(date_list))
        .all()
    )
    if not events:
        return None
    from .statcast_utils import calculate_pitcher_aggregates
    stats = calculate_pitcher_aggregates(_events_to_pitcher_df(events))
    stats["actual_games"] = len(date_list)
    stats["start_date"] = min(date_list).isoformat()
    stats["end_date"] = max(date_list).isoformat()
    return stats


def get_batter_rolling_by_games(session: Session, batter_id: int, n_games: int) -> Optional[Dict[str, Any]]:
    date_rows = (
        session.query(StatcastEvent.game_date)
        .filter(StatcastEvent.batter_id == batter_id)
        .distinct()
        .order_by(StatcastEvent.game_date.desc())
        .limit(n_games)
        .all()
    )
    if not date_rows:
        return None
    date_list = [r[0] for r in date_rows]
    events = (
        session.query(StatcastEvent)
        .filter(StatcastEvent.batter_id == batter_id, StatcastEvent.game_date.in_(date_list), StatcastEvent.events.isnot(None), StatcastEvent.events != "")
        .all()
    )
    if not events:
        return None
    from .statcast_utils import calculate_batter_aggregates
    stats = calculate_batter_aggregates(_events_to_batter_df(events))
    stats["actual_games"] = len(date_list)
    stats["start_date"] = min(date_list).isoformat()
    stats["end_date"] = max(date_list).isoformat()
    return stats


def get_batter_rolling_by_abs(session: Session, batter_id: int, n_abs: int) -> Optional[Dict[str, Any]]:
    events = (
        session.query(StatcastEvent)
        .filter(StatcastEvent.batter_id == batter_id, StatcastEvent.events.isnot(None), StatcastEvent.events != "")
        .order_by(StatcastEvent.game_date.desc())
        .limit(n_abs)
        .all()
    )
    if not events:
        return None
    from .statcast_utils import calculate_batter_aggregates
    stats = calculate_batter_aggregates(_events_to_batter_df(events))
    stats["actual_abs"] = len(events)
    dates = [e.game_date for e in events if e.game_date]
    stats["start_date"] = min(dates).isoformat() if dates else None
    stats["end_date"] = max(dates).isoformat() if dates else None
    return stats


def get_batter_at_bats(session: Session, batter_id: int, n: int = 50, offset: int = 0) -> Tuple[int, List[Dict[str, Any]]]:
    base = session.query(StatcastEvent).filter(StatcastEvent.batter_id == batter_id, StatcastEvent.events.isnot(None), StatcastEvent.events != "")
    total = base.count()
    events = base.order_by(StatcastEvent.game_date.desc()).offset(offset).limit(n).all()
    rows = [
        {
            "game_date": e.game_date.isoformat() if e.game_date else None,
            "pitcher_id": e.pitcher_id,
            "pitcher_hand": e.p_throws,
            "batter_stand": e.stand,
            "result": e.events,
            "exit_velocity": e.launch_speed,
            "launch_angle": e.launch_angle,
            "pitch_type": e.pitch_type,
        }
        for e in events
    ]
    return total, rows


def _dedupe_events(events: List[StatcastEvent]) -> List[StatcastEvent]:
    seen = set()
    out: List[StatcastEvent] = []
    for e in events:
        key = (e.game_date, e.pitcher_id, e.batter_id, e.pitch_type, e.release_speed, e.release_spin_rate, e.launch_speed, e.launch_angle, e.balls, e.strikes, e.events, e.stand, e.p_throws, e.pfx_x, e.pfx_z, e.plate_x, e.plate_z)
        if key in seen:
            continue
        seen.add(key)
        out.append(e)
    return out


def get_pitcher_game_log(session: Session, pitcher_id: int, n: int = 10) -> List[Dict[str, Any]]:
    date_rows = (
        session.query(StatcastEvent.game_date)
        .filter(StatcastEvent.pitcher_id == pitcher_id)
        .distinct()
        .order_by(StatcastEvent.game_date.desc())
        .limit(n)
        .all()
    )
    if not date_rows:
        return []
    date_list = [r[0] for r in date_rows]
    events = (
        session.query(StatcastEvent)
        .filter(StatcastEvent.pitcher_id == pitcher_id, StatcastEvent.game_date.in_(date_list))
        .all()
    )
    by_date: Dict[str, List[StatcastEvent]] = {}
    for e in _dedupe_events(events):
        key = e.game_date.isoformat() if e.game_date else "unknown"
        by_date.setdefault(key, []).append(e)
    log = []
    for d in sorted(by_date, reverse=True):
        evs = by_date[d]
        terminal = [e for e in evs if e.events and e.events != ""]
        outcomes = [e.events for e in terminal]
        ev_vals = [e.launch_speed for e in terminal if e.launch_speed is not None]
        speeds = [e.release_speed for e in evs if e.release_speed is not None]
        hard_hits = sum(1 for v in ev_vals if v >= 95)
        log.append({
            "game_date": d,
            "pitch_count": len(evs),
            "plate_appearances": len(terminal),
            "strikeouts": outcomes.count("strikeout") + outcomes.count("strikeout_double_play"),
            "walks": outcomes.count("walk") + outcomes.count("intent_walk"),
            "home_runs": outcomes.count("home_run"),
            "hard_hit_pct": round(hard_hits / len(ev_vals), 3) if ev_vals else None,
            "avg_velocity": round(sum(speeds) / len(speeds), 1) if speeds else None,
        })
    return log


def get_pitcher_multi_season(session: Session, pitcher_id: int, seasons: List[int]) -> List[Dict[str, Any]]:
    today_year = datetime.date.today().year
    result = []
    for season in seasons:
        window = "90d" if season == today_year else str(season)
        agg = get_pitcher_aggregate(session, pitcher_id, window)
        label = "YTD (90d)" if season == today_year else str(season)
        result.append({
            "season": season,
            "label": label,
            "avg_velocity": agg.avg_velocity if agg else None,
            "avg_spin_rate": agg.avg_spin_rate if agg else None,
            "k_pct": agg.k_pct if agg else None,
            "bb_pct": agg.bb_pct if agg else None,
            "hard_hit_pct": agg.hard_hit_pct if agg else None,
            "xwoba": agg.xwoba if agg else None,
            "xba": agg.xba if agg else None,
        })
    return result


def get_batter_multi_season(session: Session, batter_id: int, seasons: List[int]) -> List[Dict[str, Any]]:
    today_year = datetime.date.today().year
    result = []
    for season in seasons:
        window = "90d" if season == today_year else str(season)
        agg = get_batter_aggregate(session, batter_id, window)
        label = "YTD (90d)" if season == today_year else str(season)
        result.append({
            "season": season,
            "label": label,
            "avg_exit_velocity": agg.avg_exit_velocity if agg else None,
            "avg_launch_angle": agg.avg_launch_angle if agg else None,
            "hard_hit_pct": agg.hard_hit_pct if agg else None,
            "barrel_pct": agg.barrel_pct if agg else None,
            "k_pct": agg.k_pct if agg else None,
            "bb_pct": agg.bb_pct if agg else None,
            "batting_avg": agg.batting_avg if agg else None,
        })
    return result


__all__ = [
    "get_pitcher_aggregate",
    "get_pitcher_aggregate_with_fallback",
    "get_batter_aggregate",
    "get_batter_aggregate_with_fallback",
    "get_pitch_arsenal",
    "get_pitch_arsenal_with_fallback",
    "get_player_split",
    "get_team_split",
    "get_pitcher_rolling_by_games",
    "get_batter_rolling_by_games",
    "get_batter_rolling_by_abs",
    "get_batter_at_bats",
    "get_pitcher_game_log",
    "get_pitcher_multi_season",
    "get_batter_multi_season",
]

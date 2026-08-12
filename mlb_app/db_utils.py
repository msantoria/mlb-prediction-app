from __future__ import annotations

import datetime
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd
from sqlalchemy import and_, case, func, or_
from sqlalchemy.orm import Session

from .database import (
    BatterAggregate,
    PitchArsenal,
    PitcherAggregate,
    PlayerSplit,
    StatcastEvent,
    TeamSplit,
)
from .statcast_event_identity import dedupe_statcast_events

HIT_EVENTS = {"single", "double", "triple", "home_run"}
WALK_EVENTS = {"walk", "intent_walk"}
HBP_EVENTS = {"hit_by_pitch"}
STRIKEOUT_EVENTS = {"strikeout", "strikeout_double_play"}
NON_AB_EVENTS = {
    "walk",
    "intent_walk",
    "hit_by_pitch",
    "sac_bunt",
    "sac_fly",
    "catcher_interf",
    "catcher_interference",
}
TERMINAL_EVENTS = {
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
    "double_play",
    "grounded_into_double_play",
    "fielders_choice",
    "fielders_choice_out",
    "sac_fly",
    "sac_bunt",
    "catcher_interf",
    "catcher_interference",
}
TOTAL_BASES = {"single": 1, "double": 2, "triple": 3, "home_run": 4}

SWING_DESCRIPTIONS = {
    "swinging_strike",
    "swinging_strike_blocked",
    "foul",
    "foul_tip",
    "foul_bunt",
    "missed_bunt",
    "hit_into_play",
    "hit_into_play_no_out",
    "hit_into_play_score",
}
WHIFF_DESCRIPTIONS = {"swinging_strike", "swinging_strike_blocked", "missed_bunt"}


def _clean_event_name(event_name: Optional[Any]) -> Optional[str]:
    if event_name is None:
        return None
    text = str(event_name).strip().lower()
    if text in {"", "nan", "none", "null", "na", "n/a"}:
        return None
    return text


def _clean_description(description: Optional[Any]) -> Optional[str]:
    if description is None:
        return None
    text = str(description).strip().lower()
    if text in {"", "nan", "none", "null", "na", "n/a"}:
        return None
    return text


def _is_terminal_event(event_name: Optional[Any]) -> bool:
    cleaned = _clean_event_name(event_name)
    return cleaned in TERMINAL_EVENTS


def _is_true_ab_event(event_name: Optional[Any]) -> bool:
    cleaned = _clean_event_name(event_name)
    return bool(cleaned and cleaned in TERMINAL_EVENTS and cleaned not in NON_AB_EVENTS)


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        if value is None:
            return default
        return int(value)
    except (TypeError, ValueError):
        return default


def _safe_float(value: Any) -> Optional[float]:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _round(value: Optional[float], digits: int = 3) -> Optional[float]:
    return round(value, digits) if value is not None else None


def _model_has_column(model: Any, column_name: str) -> bool:
    return hasattr(model, column_name)


def _is_real_player_name(name: Optional[str]) -> bool:
    if not name:
        return False
    cleaned = str(name).strip()
    if not cleaned:
        return False
    if cleaned.startswith("#"):
        return False
    if cleaned.lower() in {"none", "null", "nan", "unknown", "n/a", "na"}:
        return False
    return True


def get_pitcher_aggregate(session: Session, pitcher_id: int, window: str) -> Optional[PitcherAggregate]:
    return (
        session.query(PitcherAggregate)
        .filter(PitcherAggregate.pitcher_id == pitcher_id, PitcherAggregate.window == window)
        .order_by(PitcherAggregate.end_date.desc())
        .first()
    )


def get_pitcher_aggregate_with_fallback(
    session: Session,
    pitcher_id: int,
    current_season: Optional[int] = None,
) -> Tuple[Optional[PitcherAggregate], Optional[str]]:
    if current_season is None:
        current_season = datetime.date.today().year

    agg = get_pitcher_aggregate(session, pitcher_id, "90d")
    if agg:
        return agg, "Last 90 Days"

    for window, label in [
        (str(current_season), f"{current_season} Season"),
        (str(current_season - 1), f"{current_season - 1} Season"),
        (str(current_season - 2), f"{current_season - 2} Season"),
        (str(current_season - 3), f"{current_season - 3} Season"),
    ]:
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


def get_batter_aggregate_with_fallback(
    session: Session,
    batter_id: int,
    current_season: Optional[int] = None,
) -> Tuple[Optional[BatterAggregate], Optional[str]]:
    if current_season is None:
        current_season = datetime.date.today().year

    agg = get_batter_aggregate(session, batter_id, "90d")
    if agg:
        return agg, "Last 90 Days"

    for window, label in [
        (str(current_season), f"{current_season} Season"),
        (str(current_season - 1), f"{current_season - 1} Season"),
        (str(current_season - 2), f"{current_season - 2} Season"),
        (str(current_season - 3), f"{current_season - 3} Season"),
    ]:
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


def get_pitch_arsenal_with_fallback(
    session: Session,
    pitcher_id: int,
    current_season: Optional[int] = None,
) -> Tuple[List[PitchArsenal], Optional[int]]:
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
    return pd.DataFrame(
        [
            {
                "release_speed": e.release_speed,
                "release_spin_rate": e.release_spin_rate,
                "launch_speed": e.launch_speed,
                "events": _clean_event_name(e.events) or "",
                "description": _clean_description(getattr(e, "description", None)) or "",
                "pfx_x": e.pfx_x,
                "pfx_z": e.pfx_z,
                "release_pos_x": None,
                "release_pos_z": None,
                "release_extension": None,
                "estimated_woba_using_speedangle": None,
                "estimated_ba_using_speedangle": None,
            }
            for e in events
        ]
    )


def _events_to_batter_df(events: List[StatcastEvent]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "launch_speed": e.launch_speed,
                "launch_angle": e.launch_angle,
                "events": _clean_event_name(e.events) or "",
                "description": _clean_description(getattr(e, "description", None)) or "",
            }
            for e in events
        ]
    )


def _calculate_batter_stats(
    events: List[StatcastEvent],
    raw_event_count: Optional[int] = None,
) -> Dict[str, Any]:
    terminal = [e for e in events if _is_terminal_event(e.events)]
    raw_count = len(events) if raw_event_count is None else raw_event_count
    dates = [e.game_date for e in terminal if e.game_date]

    pa = len(terminal)
    ab_events = [e for e in terminal if _is_true_ab_event(e.events)]
    ab = len(ab_events)

    outcomes = [_clean_event_name(e.events) for e in terminal]
    descriptions = [_clean_description(getattr(e, "description", None)) for e in events]

    hits = sum(1 for event in outcomes if event in HIT_EVENTS)
    doubles = sum(1 for event in outcomes if event == "double")
    triples = sum(1 for event in outcomes if event == "triple")
    walks = sum(1 for event in outcomes if event in WALK_EVENTS)
    hbp = sum(1 for event in outcomes if event in HBP_EVENTS)
    strikeouts = sum(1 for event in outcomes if event in STRIKEOUT_EVENTS)
    home_runs = sum(1 for event in outcomes if event == "home_run")
    sacrifice_flies = sum(1 for event in outcomes if event == "sac_fly")
    total_bases = sum(TOTAL_BASES.get(event or "", 0) for event in outcomes)

    batted_balls = [e for e in events if e.launch_speed is not None]
    launch_angles = [e.launch_angle for e in events if e.launch_angle is not None]
    hard_hit_count = sum(1 for e in batted_balls if e.launch_speed is not None and e.launch_speed >= 95)
    barrel_count = sum(
        1
        for e in batted_balls
        if e.launch_speed is not None
        and e.launch_angle is not None
        and e.launch_speed >= 98
        and 8 <= e.launch_angle <= 50
    )

    swings = sum(1 for description in descriptions if description in SWING_DESCRIPTIONS)
    whiffs = sum(1 for description in descriptions if description in WHIFF_DESCRIPTIONS)

    obp_denominator = ab + walks + hbp + sacrifice_flies
    batting_avg = round(hits / ab, 3) if ab else None
    obp = round((hits + walks + hbp) / obp_denominator, 3) if obp_denominator else None
    slg = round(total_bases / ab, 3) if ab else None
    iso = round(slg - batting_avg, 3) if slg is not None and batting_avg is not None else None

    avg_exit_velocity = (
        round(sum(e.launch_speed for e in batted_balls if e.launch_speed is not None) / len(batted_balls), 1)
        if batted_balls
        else None
    )
    max_exit_velocity = (
        round(max(e.launch_speed for e in batted_balls if e.launch_speed is not None), 1)
        if batted_balls
        else None
    )

    stats = {
        "actual_pa": pa,
        "actual_ab": ab,
        "event_count": raw_count,
        "terminal_event_count": pa,
        "invalid_event_count": max(raw_count - pa, 0),
        "batted_ball_count": len(batted_balls),
        "hard_hit_count": hard_hit_count,
        "barrel_count": barrel_count,
        "hits": hits,
        "doubles": doubles,
        "triples": triples,
        "walks": walks,
        "strikeouts": strikeouts,
        "home_runs": home_runs,
        "total_bases": total_bases,
        "batting_avg": batting_avg,
        "on_base_pct": obp,
        "slugging_pct": slg,
        "ops": round(obp + slg, 3) if obp is not None and slg is not None else None,
        "iso": iso,
        "k_pct": round(strikeouts / pa, 3) if pa else None,
        "bb_pct": round(walks / pa, 3) if pa else None,
        "avg_exit_velocity": avg_exit_velocity,
        "max_exit_velocity": max_exit_velocity,
        "avg_launch_angle": round(sum(launch_angles) / len(launch_angles), 1) if launch_angles else None,
        "hard_hit_pct": round(hard_hit_count / len(batted_balls), 3) if batted_balls else None,
        "barrel_pct": round(barrel_count / len(batted_balls), 3) if batted_balls else None,
        "swings": swings,
        "whiffs": whiffs,
        "whiff_pct": round(whiffs / swings, 3) if swings else None,
        "contact_pct": round(1 - (whiffs / swings), 3) if swings else None,
        "start_date": min(dates).isoformat() if dates else None,
        "end_date": max(dates).isoformat() if dates else None,
        "source": "postgres_statcast_events",
    }
    return stats


def _has_full_event_order(session: Session, batter_id: int) -> bool:
    return (
        session.query(StatcastEvent.id)
        .filter(
            StatcastEvent.batter_id == batter_id,
            StatcastEvent.game_pk.isnot(None),
            StatcastEvent.at_bat_number.isnot(None),
            StatcastEvent.pitch_number.isnot(None),
        )
        .first()
        is not None
    )


def _freshness_from_latest(latest: Optional[datetime.date]) -> Dict[str, Any]:
    today = datetime.date.today()
    days_stale = (today - latest).days if latest else None
    return {
        "as_of_date": today.isoformat(),
        "latest_event_date": latest.isoformat() if latest else None,
        "days_stale": days_stale,
        "is_stale": days_stale is None or days_stale > 1,
    }


def get_batter_data_quality(session: Session, batter_id: int) -> Dict[str, Any]:
    total = session.query(func.count(StatcastEvent.id)).filter(StatcastEvent.batter_id == batter_id).scalar() or 0
    latest = (
        session.query(func.max(StatcastEvent.game_date))
        .filter(StatcastEvent.batter_id == batter_id)
        .scalar()
    )
    terminal_count = (
        session.query(func.count(StatcastEvent.id))
        .filter(
            StatcastEvent.batter_id == batter_id,
            StatcastEvent.events.in_(TERMINAL_EVENTS),
        )
        .scalar()
        or 0
    )
    full_order = _has_full_event_order(session, batter_id)
    freshness = _freshness_from_latest(latest)

    warnings: List[str] = []
    if freshness["is_stale"]:
        warnings.append(
            f"Statcast data is stale: latest event is {freshness['latest_event_date'] or 'unavailable'}, "
            f"as-of date is {freshness['as_of_date']}."
        )

    if total == 0:
        ordering_quality = "unavailable"
        warnings.append("No Statcast events found for this batter.")
    elif full_order:
        ordering_quality = "full_event_order"
    else:
        ordering_quality = "date_only"
        warnings.append("Rolling PA order is date-level only; intra-game PA order unavailable.")

    return {
        "has_statcast": total > 0,
        "total_event_rows": total,
        "terminal_event_rows": terminal_count,
        "latest_event_date": freshness["latest_event_date"],
        "as_of_date": freshness["as_of_date"],
        "days_stale": freshness["days_stale"],
        "is_stale": freshness["is_stale"],
        "rolling_pa_available": terminal_count > 0,
        "rolling_game_available": total > 0,
        "ordering_quality": ordering_quality,
        "warnings": warnings,
        "source": "postgres_statcast_events",
    }


def _ordered_batter_terminal_query(session: Session, batter_id: int):
    query = session.query(StatcastEvent).filter(
        StatcastEvent.batter_id == batter_id,
        StatcastEvent.events.in_(TERMINAL_EVENTS),
    )
    if _has_full_event_order(session, batter_id):
        return query.order_by(
            StatcastEvent.game_date.desc(),
            StatcastEvent.game_pk.desc(),
            StatcastEvent.at_bat_number.desc(),
            StatcastEvent.pitch_number.desc(),
        )
    return query.order_by(StatcastEvent.game_date.desc(), StatcastEvent.id.desc())


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
    events = dedupe_statcast_events(events)
    if not events:
        return None

    from .statcast_utils import calculate_pitcher_aggregates

    stats = calculate_pitcher_aggregates(_events_to_pitcher_df(events))
    stats["actual_games"] = len(date_list)
    stats["start_date"] = min(date_list).isoformat()
    stats["end_date"] = max(date_list).isoformat()
    return stats


def get_batter_rolling_by_games(session: Session, batter_id: int, n_games: int) -> Optional[Dict[str, Any]]:
    quality = get_batter_data_quality(session, batter_id)

    if quality["ordering_quality"] == "full_event_order":
        game_rows = (
            session.query(StatcastEvent.game_pk, func.max(StatcastEvent.game_date).label("game_date"))
            .filter(
                StatcastEvent.batter_id == batter_id,
                StatcastEvent.game_pk.isnot(None),
                StatcastEvent.events.in_(TERMINAL_EVENTS),
            )
            .group_by(StatcastEvent.game_pk)
            .order_by(func.max(StatcastEvent.game_date).desc(), StatcastEvent.game_pk.desc())
            .limit(n_games)
            .all()
        )
        if not game_rows:
            return None

        game_pks = [r[0] for r in game_rows]
        events = (
            session.query(StatcastEvent)
            .filter(
                StatcastEvent.batter_id == batter_id,
                StatcastEvent.game_pk.in_(game_pks),
                StatcastEvent.events.in_(TERMINAL_EVENTS),
            )
            .all()
        )
        actual_games = len(game_pks)
    else:
        date_rows = (
            session.query(StatcastEvent.game_date)
            .filter(StatcastEvent.batter_id == batter_id, StatcastEvent.events.in_(TERMINAL_EVENTS))
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
            .filter(
                StatcastEvent.batter_id == batter_id,
                StatcastEvent.game_date.in_(date_list),
                StatcastEvent.events.in_(TERMINAL_EVENTS),
            )
            .all()
        )
        actual_games = len(date_list)
        quality["warnings"] = list(quality.get("warnings", [])) + [
            "Rolling game windows are date-based because game_pk is unavailable."
        ]

    if not events:
        return None

    stats = _calculate_batter_stats(events, raw_event_count=len(events))
    stats["actual_games"] = actual_games
    stats["window_type"] = "games"
    stats["data_quality"] = quality
    return stats


def get_batter_rolling_by_pa(session: Session, batter_id: int, n_pa: int) -> Optional[Dict[str, Any]]:
    events = _ordered_batter_terminal_query(session, batter_id).limit(n_pa).all()
    if not events:
        return None

    stats = _calculate_batter_stats(events, raw_event_count=len(events))
    stats["actual_pa"] = len(events)
    stats["window_type"] = "PA"
    stats["label"] = f"Last {n_pa} PA"
    stats["data_quality"] = get_batter_data_quality(session, batter_id)
    return stats


def get_batter_rolling_by_ab(session: Session, batter_id: int, n_ab: int) -> Optional[Dict[str, Any]]:
    candidates = _ordered_batter_terminal_query(session, batter_id).limit(max(n_ab * 5, n_ab)).all()
    events = [e for e in candidates if _is_true_ab_event(e.events)][:n_ab]
    if not events:
        return None

    stats = _calculate_batter_stats(events, raw_event_count=len(candidates))
    stats["actual_ab"] = len(events)
    stats["window_type"] = "AB"
    stats["label"] = f"Last {n_ab} AB"
    stats["data_quality"] = get_batter_data_quality(session, batter_id)
    return stats


def get_batter_rolling_by_abs(session: Session, batter_id: int, n_abs: int) -> Optional[Dict[str, Any]]:
    result = get_batter_rolling_by_pa(session, batter_id, n_abs)
    if result:
        result["actual_abs"] = result.get("actual_pa")
        result["legacy_alias"] = "get_batter_rolling_by_abs"
        result["label_warning"] = "Legacy abs rolling returns PA-style terminal outcomes, not strict official AB."
    return result


def get_batter_rolling_splits(session: Session, batter_id: int, n_pa: int = 100) -> Dict[str, Any]:
    events = _ordered_batter_terminal_query(session, batter_id).limit(n_pa).all()
    grouped = {"vsL": [], "vsR": [], "unknown": []}

    for event in events:
        key = "vsL" if event.p_throws == "L" else "vsR" if event.p_throws == "R" else "unknown"
        grouped[key].append(event)

    return {
        "window_type": "PA",
        "requested_pa": n_pa,
        "actual_pa": len(events),
        "splits": {k: ({**_calculate_batter_stats(v), "actual_pa": len(v)} if v else None) for k, v in grouped.items()},
        "data_quality": get_batter_data_quality(session, batter_id),
    }


def get_batter_rolling_pitch_types(session: Session, batter_id: int, n_pa: int = 100) -> Dict[str, Any]:
    events = _ordered_batter_terminal_query(session, batter_id).limit(n_pa).all()
    grouped: Dict[str, List[StatcastEvent]] = {}

    for event in events:
        key = event.pitch_type or "unknown"
        grouped.setdefault(key, []).append(event)

    return {
        "window_type": "PA",
        "requested_pa": n_pa,
        "actual_pa": len(events),
        "pitch_types": {
            k: {**_calculate_batter_stats(v), "actual_pa": len(v)}
            for k, v in sorted(grouped.items(), key=lambda item: len(item[1]), reverse=True)
        },
        "data_quality": get_batter_data_quality(session, batter_id),
    }


def get_batter_at_bats(
    session: Session,
    batter_id: int,
    n: int = 50,
    offset: int = 0,
) -> Tuple[int, List[Dict[str, Any]]]:
    base = session.query(StatcastEvent).filter(
        StatcastEvent.batter_id == batter_id,
        StatcastEvent.events.in_(TERMINAL_EVENTS),
    )
    total = base.count()
    events = _ordered_batter_terminal_query(session, batter_id).offset(offset).limit(n).all()

    rows = [
        {
            "game_date": e.game_date.isoformat() if e.game_date else None,
            "game_pk": e.game_pk,
            "at_bat_number": e.at_bat_number,
            "pitch_number": e.pitch_number,
            "inning": e.inning,
            "inning_topbot": e.inning_topbot,
            "outs_when_up": e.outs_when_up,
            "pitcher_id": e.pitcher_id,
            "pitcher_hand": e.p_throws,
            "batter_stand": e.stand,
            "result": _clean_event_name(e.events),
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
        key = (
            e.game_date,
            e.game_pk,
            e.at_bat_number,
            e.pitch_number,
            e.pitcher_id,
            e.batter_id,
            e.pitch_type,
            e.release_speed,
            e.release_spin_rate,
            e.launch_speed,
            e.launch_angle,
            e.balls,
            e.strikes,
            e.events,
            e.stand,
            e.p_throws,
            e.pfx_x,
            e.pfx_z,
            e.plate_x,
            e.plate_z,
        )
        if key in seen:
            continue
        seen.add(key)
        out.append(e)

    return out


def _pitch_event_identity(e: StatcastEvent) -> Tuple[Any, ...]:
    if e.game_pk is not None and e.at_bat_number is not None and e.pitch_number is not None:
        return (
            e.game_pk,
            e.at_bat_number,
            e.pitch_number,
            e.pitcher_id,
            e.batter_id,
            e.pitch_type,
        )

    return (
        e.game_date,
        e.pitcher_id,
        e.batter_id,
        e.pitch_type,
        _clean_event_name(e.events),
        e.release_speed,
        e.release_spin_rate,
        e.launch_speed,
        e.launch_angle,
        e.balls,
        e.strikes,
        e.inning,
        e.inning_topbot,
        e.outs_when_up,
    )


def _dedupe_pitch_events(events: List[StatcastEvent]) -> List[StatcastEvent]:
    return dedupe_statcast_events(events)


def _terminal_pa_identity(e: StatcastEvent) -> Tuple[Any, ...]:
    if e.game_pk is not None and e.at_bat_number is not None:
        return (
            e.game_pk,
            e.at_bat_number,
            e.pitcher_id,
            e.batter_id,
        )

    return (
        e.game_date,
        e.pitcher_id,
        e.batter_id,
        _clean_event_name(e.events),
        e.inning,
        e.inning_topbot,
        e.outs_when_up,
    )


def _dedupe_terminal_pas(events: List[StatcastEvent]) -> List[StatcastEvent]:
    seen = set()
    out: List[StatcastEvent] = []

    for e in events:
        if not _is_terminal_event(e.events):
            continue

        key = _terminal_pa_identity(e)
        if key in seen:
            continue

        seen.add(key)
        out.append(e)

    return out


def get_pitcher_game_log(session: Session, pitcher_id: int, n: int = 10) -> List[Dict[str, Any]]:
    game_rows = (
        session.query(
            StatcastEvent.game_pk,
            func.max(StatcastEvent.game_date).label("game_date"),
        )
        .filter(
            StatcastEvent.pitcher_id == pitcher_id,
            StatcastEvent.game_date.isnot(None),
        )
        .group_by(StatcastEvent.game_pk)
        .order_by(func.max(StatcastEvent.game_date).desc(), StatcastEvent.game_pk.desc().nullslast())
        .limit(n)
        .all()
    )

    if not game_rows:
        return []

    game_pks = [row.game_pk for row in game_rows if row.game_pk is not None]
    date_only_rows = [row.game_date for row in game_rows if row.game_pk is None and row.game_date is not None]

    query = session.query(StatcastEvent).filter(StatcastEvent.pitcher_id == pitcher_id)

    filters = []
    if game_pks:
        filters.append(StatcastEvent.game_pk.in_(game_pks))
    if date_only_rows:
        filters.append(StatcastEvent.game_date.in_(date_only_rows))

    if not filters:
        return []

    events = query.filter(or_(*filters)).all()

    by_game: Dict[Tuple[Any, str], List[StatcastEvent]] = {}
    for e in _dedupe_pitch_events(events):
        game_date = e.game_date.isoformat() if e.game_date else "unknown"
        game_key = e.game_pk if e.game_pk is not None else f"date:{game_date}"
        by_game.setdefault((game_key, game_date), []).append(e)

    log = []
    for (game_key, game_date), evs in sorted(by_game.items(), key=lambda item: item[0][1], reverse=True):
        terminal = _dedupe_terminal_pas(evs)
        outcomes = [_clean_event_name(e.events) for e in terminal]

        batted_balls = [e for e in terminal if e.launch_speed is not None]
        speeds = [e.release_speed for e in evs if e.release_speed is not None]
        hard_hits = sum(1 for e in batted_balls if e.launch_speed is not None and e.launch_speed >= 95)

        log.append(
            {
                "game_pk": game_key if not str(game_key).startswith("date:") else None,
                "game_date": game_date,
                "pitch_count": len(evs),
                "plate_appearances": len(terminal),
                "strikeouts": sum(1 for event in outcomes if event in STRIKEOUT_EVENTS),
                "walks": sum(1 for event in outcomes if event in WALK_EVENTS or event in HBP_EVENTS),
                "home_runs": sum(1 for event in outcomes if event == "home_run"),
                "hard_hit_pct": round(hard_hits / len(batted_balls), 3) if batted_balls else None,
                "avg_velocity": round(sum(speeds) / len(speeds), 1) if speeds else None,
            }
        )

    log.sort(key=lambda row: (row.get("game_date") or "", row.get("game_pk") or 0), reverse=True)
    return log[:n]


def get_pitcher_multi_season(session: Session, pitcher_id: int, seasons: List[int]) -> List[Dict[str, Any]]:
    today_year = datetime.date.today().year
    result = []

    for season in seasons:
        window = "90d" if season == today_year else str(season)
        agg = get_pitcher_aggregate(session, pitcher_id, window)
        label = "YTD (90d)" if season == today_year else str(season)
        result.append(
            {
                "season": season,
                "label": label,
                "avg_velocity": agg.avg_velocity if agg else None,
                "avg_spin_rate": agg.avg_spin_rate if agg else None,
                "k_pct": agg.k_pct if agg else None,
                "bb_pct": agg.bb_pct if agg else None,
                "hard_hit_pct": agg.hard_hit_pct if agg else None,
                "xwoba": agg.xwoba if agg else None,
                "xba": agg.xba if agg else None,
            }
        )

    return result


def get_batter_multi_season(session: Session, batter_id: int, seasons: List[int]) -> List[Dict[str, Any]]:
    today_year = datetime.date.today().year
    result = []

    for season in seasons:
        window = "90d" if season == today_year else str(season)
        agg = get_batter_aggregate(session, batter_id, window)
        label = "YTD (90d)" if season == today_year else str(season)
        result.append(
            {
                "season": season,
                "label": label,
                "avg_exit_velocity": agg.avg_exit_velocity if agg else None,
                "avg_launch_angle": agg.avg_launch_angle if agg else None,
                "hard_hit_pct": agg.hard_hit_pct if agg else None,
                "barrel_pct": agg.barrel_pct if agg else None,
                "k_pct": agg.k_pct if agg else None,
                "bb_pct": agg.bb_pct if agg else None,
                "batting_avg": agg.batting_avg if agg else None,
            }
        )

    return result


def _leaderboard_row(
    rank: int,
    player: Dict[str, Any],
    metric: str,
    value: Any,
) -> Dict[str, Any]:
    return {
        "rank": rank,
        "player_id": player["player_id"],
        "player_name": player["player_name"],
        "team": player.get("team") or "",
        "value": value,
        "pa": player.get("pa"),
        "ab": player.get("ab"),
        "bbe": player.get("bbe"),
        "swings": player.get("swings"),
    }


def _make_board(
    players: List[Dict[str, Any]],
    metric: str,
    *,
    min_key: str,
    min_count: int,
    limit: int,
    reverse: bool = True,
) -> List[Dict[str, Any]]:
    filtered = [
        p
        for p in players
        if _is_real_player_name(p.get("player_name"))
        and p.get(metric) is not None
        and p.get(min_key, 0) is not None
        and p.get(min_key, 0) >= min_count
    ]
    filtered.sort(key=lambda p: p[metric], reverse=reverse)

    return [
        _leaderboard_row(i + 1, player, metric, player[metric])
        for i, player in enumerate(filtered[:limit])
    ]


def _latest_batter_names(session: Session) -> Dict[int, str]:
    name_map: Dict[int, str] = {}

    try:
        from .database import BatterPitchTypeMatchup

        if hasattr(BatterPitchTypeMatchup, "batter_id") and hasattr(BatterPitchTypeMatchup, "batter_name"):
            rows = (
                session.query(BatterPitchTypeMatchup.batter_id, BatterPitchTypeMatchup.batter_name)
                .filter(BatterPitchTypeMatchup.batter_id.isnot(None))
                .filter(BatterPitchTypeMatchup.batter_name.isnot(None))
                .all()
            )
            for batter_id, batter_name in rows:
                if batter_id and _is_real_player_name(batter_name):
                    name_map[int(batter_id)] = str(batter_name).strip()
    except Exception:
        pass

    try:
        if hasattr(StatcastEvent, "batter_name"):
            rows = (
                session.query(StatcastEvent.batter_id, StatcastEvent.batter_name)
                .filter(StatcastEvent.batter_id.isnot(None))
                .filter(StatcastEvent.batter_name.isnot(None))
                .distinct()
                .all()
            )
            for batter_id, batter_name in rows:
                if batter_id and _is_real_player_name(batter_name):
                    name_map.setdefault(int(batter_id), str(batter_name).strip())
    except Exception:
        pass

    return name_map


def _latest_batter_teams(session: Session, season: int) -> Dict[int, str]:
    if not (
        _model_has_column(StatcastEvent, "home_team")
        and _model_has_column(StatcastEvent, "away_team")
        and _model_has_column(StatcastEvent, "inning_topbot")
    ):
        return {}

    s_start = datetime.date(season, 1, 1)
    s_end = datetime.date(season, 12, 31)

    # Subquery: most recent game_date per batter (indexed GROUP BY, not a full table load)
    max_date_sq = (
        session.query(
            StatcastEvent.batter_id.label("batter_id"),
            func.max(StatcastEvent.game_date).label("max_date"),
        )
        .filter(
            StatcastEvent.game_date >= s_start,
            StatcastEvent.game_date <= s_end,
            StatcastEvent.batter_id.isnot(None),
        )
        .group_by(StatcastEvent.batter_id)
        .subquery()
    )

    # Fetch only the 4 team-relevant columns for one row per batter
    rows = (
        session.query(
            StatcastEvent.batter_id,
            StatcastEvent.home_team,
            StatcastEvent.away_team,
            StatcastEvent.inning_topbot,
        )
        .join(
            max_date_sq,
            and_(
                StatcastEvent.batter_id == max_date_sq.c.batter_id,
                StatcastEvent.game_date == max_date_sq.c.max_date,
            ),
        )
        .filter(StatcastEvent.batter_id.isnot(None))
        .all()
    )

    team_map: Dict[int, str] = {}
    for row in rows:
        batter_id = row.batter_id
        if not batter_id or int(batter_id) in team_map:
            continue
        team = row.away_team if row.inning_topbot == "Top" else row.home_team
        if team:
            team_map[int(batter_id)] = team

    return team_map


def _compute_batter_counting_sql(
    session: Session,
    s_start: datetime.date,
    s_end: datetime.date,
) -> List[Any]:
    """Aggregate terminal PA counting stats at the DB level.

    Double GROUP BY deduplicates PAs: first by (batter_id, game_pk, at_bat_number)
    to collapse any duplicate rows per plate appearance, then sums across all PAs per
    batter. Rows missing game_pk or at_bat_number are excluded (edge-case data only).
    """
    terminal_list = list(TERMINAL_EVENTS)
    non_ab_list = list(NON_AB_EVENTS)

    inner = (
        session.query(
            StatcastEvent.batter_id.label("batter_id"),
            StatcastEvent.game_pk.label("game_pk"),
            StatcastEvent.at_bat_number.label("at_bat_number"),
            func.max(case((StatcastEvent.events == "home_run", 1), else_=0)).label("home_runs"),
            func.max(
                case((StatcastEvent.events.in_(["single", "double", "triple", "home_run"]), 1), else_=0)
            ).label("is_hit"),
            func.max(case((StatcastEvent.events == "double", 1), else_=0)).label("is_double"),
            func.max(
                case((StatcastEvent.events.in_(["walk", "intent_walk"]), 1), else_=0)
            ).label("is_walk"),
            func.max(
                case((StatcastEvent.events.in_(["strikeout", "strikeout_double_play"]), 1), else_=0)
            ).label("is_strikeout"),
            func.max(case((StatcastEvent.events.notin_(non_ab_list), 1), else_=0)).label("is_ab"),
            func.max(
                case(
                    (StatcastEvent.events == "home_run", 4),
                    (StatcastEvent.events == "triple", 3),
                    (StatcastEvent.events == "double", 2),
                    (StatcastEvent.events == "single", 1),
                    else_=0,
                )
            ).label("total_bases"),
        )
        .filter(
            StatcastEvent.game_date >= s_start,
            StatcastEvent.game_date <= s_end,
            StatcastEvent.batter_id.isnot(None),
            StatcastEvent.events.in_(terminal_list),
            StatcastEvent.game_pk.isnot(None),
            StatcastEvent.at_bat_number.isnot(None),
        )
        .group_by(
            StatcastEvent.batter_id,
            StatcastEvent.game_pk,
            StatcastEvent.at_bat_number,
        )
        .subquery()
    )

    return (
        session.query(
            inner.c.batter_id,
            func.count().label("pa"),
            func.sum(inner.c.is_ab).label("ab"),
            func.sum(inner.c.is_hit).label("hits"),
            func.sum(inner.c.home_runs).label("home_runs"),
            func.sum(inner.c.is_double).label("doubles"),
            func.sum(inner.c.is_walk).label("walks"),
            func.sum(inner.c.is_strikeout).label("strikeouts"),
            func.sum(inner.c.total_bases).label("total_bases"),
        )
        .group_by(inner.c.batter_id)
        .all()
    )


def _compute_batter_batted_ball_sql(
    session: Session,
    s_start: datetime.date,
    s_end: datetime.date,
) -> List[Any]:
    """Aggregate batted-ball EV/quality stats at the DB level.

    Double GROUP BY deduplicates pitch events: first by
    (batter_id, game_pk, at_bat_number, pitch_number), then aggregates per batter.
    """
    inner = (
        session.query(
            StatcastEvent.batter_id.label("batter_id"),
            StatcastEvent.game_pk.label("game_pk"),
            StatcastEvent.at_bat_number.label("at_bat_number"),
            StatcastEvent.pitch_number.label("pitch_number"),
            func.max(StatcastEvent.launch_speed).label("launch_speed"),
            func.max(StatcastEvent.launch_angle).label("launch_angle"),
        )
        .filter(
            StatcastEvent.game_date >= s_start,
            StatcastEvent.game_date <= s_end,
            StatcastEvent.batter_id.isnot(None),
            StatcastEvent.launch_speed.isnot(None),
            StatcastEvent.game_pk.isnot(None),
            StatcastEvent.at_bat_number.isnot(None),
            StatcastEvent.pitch_number.isnot(None),
        )
        .group_by(
            StatcastEvent.batter_id,
            StatcastEvent.game_pk,
            StatcastEvent.at_bat_number,
            StatcastEvent.pitch_number,
        )
        .subquery()
    )

    return (
        session.query(
            inner.c.batter_id,
            func.count().label("bbe"),
            func.avg(inner.c.launch_speed).label("avg_exit_velocity"),
            func.max(inner.c.launch_speed).label("max_exit_velocity"),
            func.sum(case((inner.c.launch_speed >= 95.0, 1), else_=0)).label("hard_hits"),
            func.sum(
                case(
                    (
                        and_(
                            inner.c.launch_speed >= 98.0,
                            inner.c.launch_angle >= 8.0,
                            inner.c.launch_angle <= 50.0,
                        ),
                        1,
                    ),
                    else_=0,
                )
            ).label("barrels"),
        )
        .group_by(inner.c.batter_id)
        .all()
    )


def get_batter_leaderboards(
    session: Session,
    season: Optional[int] = None,
    min_pa: int = 50,
    min_bbe: int = 100,
    limit: int = 10,
) -> Dict[str, Any]:
    if season is None:
        season = datetime.date.today().year

    # Find which season has data with a lightweight existence check
    actual_season = season
    s_start: Optional[datetime.date] = None
    s_end: Optional[datetime.date] = None
    for candidate_season in [season, season - 1]:
        cs_start = datetime.date(candidate_season, 1, 1)
        cs_end = datetime.date(candidate_season, 12, 31)
        has_data = (
            session.query(StatcastEvent.batter_id)
            .filter(
                StatcastEvent.game_date >= cs_start,
                StatcastEvent.game_date <= cs_end,
                StatcastEvent.batter_id.isnot(None),
                StatcastEvent.events.in_(list(TERMINAL_EVENTS)),
            )
            .limit(1)
            .first()
        )
        if has_data:
            actual_season = candidate_season
            s_start = cs_start
            s_end = cs_end
            break

    _all_metrics = [
        "home_runs", "hits", "doubles", "iso",
        "hard_hit_pct", "barrel_pct", "avg_exit_velocity", "max_exit_velocity",
        "bb_pct", "k_pct_avoidance",
    ]

    if s_start is None:
        return {
            "updated_at": datetime.datetime.utcnow().isoformat(timespec="seconds") + "Z",
            "source": "batter_aggregate_sql",
            "season": season,
            "leaderboards": {},
            "available_metrics": [],
            "unavailable_metrics": sorted(_all_metrics),
            "notes": ["No StatcastEvent rows found for requested season or previous season."],
        }

    name_map = _latest_batter_names(session)
    team_map = _latest_batter_teams(session, actual_season)

    # Compute stats via SQL GROUP BY — no full-table-to-Python load
    counting_rows = _compute_batter_counting_sql(session, s_start, s_end)
    batted_ball_rows = _compute_batter_batted_ball_sql(session, s_start, s_end)

    bb_by_batter: Dict[int, Any] = {int(row.batter_id): row for row in batted_ball_rows}

    players: List[Dict[str, Any]] = []
    for row in counting_rows:
        batter_id = int(row.batter_id)
        player_name = name_map.get(batter_id)
        if not _is_real_player_name(player_name):
            continue

        pa = int(row.pa or 0)
        ab = int(row.ab or 0)
        hits = int(row.hits or 0)
        home_runs = int(row.home_runs or 0)
        doubles = int(row.doubles or 0)
        walks = int(row.walks or 0)
        strikeouts = int(row.strikeouts or 0)
        total_bases = int(row.total_bases or 0)

        batting_avg = round(hits / ab, 3) if ab else None
        slugging_pct = round(total_bases / ab, 3) if ab else None
        iso = (
            round(slugging_pct - batting_avg, 3)
            if slugging_pct is not None and batting_avg is not None
            else None
        )
        k_pct = round(strikeouts / pa, 3) if pa else None
        bb_pct = round(walks / pa, 3) if pa else None

        bb = bb_by_batter.get(batter_id)
        if bb is not None:
            bbe = int(bb.bbe or 0)
            avg_ev = round(float(bb.avg_exit_velocity), 1) if bb.avg_exit_velocity is not None else None
            max_ev = round(float(bb.max_exit_velocity), 1) if bb.max_exit_velocity is not None else None
            hard_hits = int(bb.hard_hits or 0)
            barrels = int(bb.barrels or 0)
            hard_hit_pct = round(hard_hits / bbe, 3) if bbe else None
            barrel_pct = round(barrels / bbe, 3) if bbe else None
        else:
            bbe = 0
            avg_ev = max_ev = hard_hit_pct = barrel_pct = None

        players.append({
            "player_id": batter_id,
            "player_name": player_name,
            "team": team_map.get(batter_id, ""),
            "pa": pa,
            "ab": ab,
            "bbe": bbe,
            "hits": hits,
            "home_runs": home_runs,
            "doubles": doubles,
            "iso": iso,
            "hard_hit_pct": hard_hit_pct,
            "barrel_pct": barrel_pct,
            "avg_exit_velocity": avg_ev,
            "max_exit_velocity": max_ev,
            "k_pct": k_pct,
            "bb_pct": bb_pct,
        })

    latest_event_date = (
        session.query(func.max(StatcastEvent.game_date))
        .filter(StatcastEvent.game_date >= s_start, StatcastEvent.game_date <= s_end)
        .scalar()
    )

    leaderboards: Dict[str, List[Dict[str, Any]]] = {}
    board_specs = [
        ("home_runs", "home_runs", "pa", min_pa, True),
        ("hits", "hits", "pa", min_pa, True),
        ("doubles", "doubles", "pa", min_pa, True),
        ("iso", "iso", "pa", max(min_pa, 100), True),
        ("hard_hit_pct", "hard_hit_pct", "bbe", min_bbe, True),
        ("barrel_pct", "barrel_pct", "bbe", min_bbe, True),
        ("avg_exit_velocity", "avg_exit_velocity", "bbe", min_bbe, True),
        ("max_exit_velocity", "max_exit_velocity", "bbe", min_bbe, True),
        ("bb_pct", "bb_pct", "pa", max(min_pa, 100), True),
        ("k_pct_avoidance", "k_pct", "pa", max(min_pa, 100), False),
    ]

    for response_key, metric, min_key, min_count, reverse in board_specs:
        board = _make_board(players, metric, min_key=min_key, min_count=min_count, limit=limit, reverse=reverse)
        if board:
            leaderboards[response_key] = board

    available_metrics = sorted(leaderboards.keys())
    unavailable_metrics = sorted(set(_all_metrics) - set(available_metrics))

    notes: List[str] = [
        "Counting stats computed via SQL GROUP BY on deduplicated terminal plate appearances.",
        "Batted-ball stats computed via SQL GROUP BY on deduplicated pitch events.",
        "Whiff/contact/RBI leaderboards require full pitch-level data and are not precomputed here.",
    ]
    if actual_season != season:
        notes.append(f"No rows found for {season}; leaderboards fell back to {actual_season}.")
    if not players:
        notes.append("No leaderboard rows had resolvable real player names.")

    return {
        "updated_at": datetime.datetime.utcnow().isoformat(timespec="seconds") + "Z",
        "source": "batter_aggregate_sql",
        "season": actual_season,
        "latest_event_date": latest_event_date.isoformat() if latest_event_date else None,
        "minimums": {"min_pa": min_pa, "min_bbe": min_bbe, "limit": limit},
        "leaderboards": leaderboards,
        "available_metrics": available_metrics,
        "unavailable_metrics": unavailable_metrics,
        "notes": notes,
    }


def get_player_splits_multi_season(
    session: Session,
    player_id: int,
    seasons: List[int],
) -> Dict[int, Dict[str, Any]]:
    result: Dict[int, Dict[str, Any]] = {}

    for season in seasons:
        vs_l = get_player_split(session, player_id, season, "vsL")
        vs_r = get_player_split(session, player_id, season, "vsR")

        if vs_l or vs_r:
            def _split_dict(split: Optional[PlayerSplit]) -> Optional[Dict[str, Any]]:
                if not split:
                    return None
                return {
                    "pa": split.pa,
                    "batting_avg": split.batting_avg,
                    "on_base_pct": split.on_base_pct,
                    "slugging_pct": split.slugging_pct,
                    "k_pct": split.k_pct,
                    "bb_pct": split.bb_pct,
                    "home_runs": split.home_runs,
                }

            result[season] = {"vsL": _split_dict(vs_l), "vsR": _split_dict(vs_r)}

    return result


__all__ = [
    "get_pitcher_aggregate",
    "get_pitcher_aggregate_with_fallback",
    "get_batter_aggregate",
    "get_batter_aggregate_with_fallback",
    "get_pitch_arsenal",
    "get_pitch_arsenal_with_fallback",
    "get_player_split",
    "get_player_splits_multi_season",
    "get_team_split",
    "get_pitcher_rolling_by_games",
    "get_batter_data_quality",
    "get_batter_rolling_by_games",
    "get_batter_rolling_by_pa",
    "get_batter_rolling_by_ab",
    "get_batter_rolling_by_abs",
    "get_batter_rolling_splits",
    "get_batter_rolling_pitch_types",
    "get_batter_at_bats",
    "get_batter_leaderboards",
    "get_pitcher_game_log",
    "get_pitcher_multi_season",
    "get_batter_multi_season",
]

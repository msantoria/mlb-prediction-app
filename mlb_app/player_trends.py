from __future__ import annotations

import datetime as dt
import math
from typing import Any, Dict, Iterable, List, Optional

from sqlalchemy import and_, case, func

from .dashboard_object_models import DashboardPlayer, PlayerTrendSnapshot
from .database import StatcastEvent
from .statcast_event_identity import canonical_event_ids_subquery
from .dashboard_report_types import describe_report_type
from .db_utils import (
    HBP_EVENTS,
    HIT_EVENTS,
    NON_AB_EVENTS,
    STRIKEOUT_EVENTS,
    SWING_DESCRIPTIONS,
    TERMINAL_EVENTS,
    TOTAL_BASES,
    WALK_EVENTS,
    WHIFF_DESCRIPTIONS,
)
from .my_dashboard_report_query import MAX_PAGE_SIZE, normalize_query


METRICS: Dict[str, Dict[str, Dict[str, Any]]] = {
    "hitter": {
        "batting_avg": {"label": "Batting Average", "favorable": "higher", "tolerance": .005},
        "on_base_pct": {"label": "On-Base Percentage", "favorable": "higher", "tolerance": .005},
        "slugging_pct": {"label": "Slugging Percentage", "favorable": "higher", "tolerance": .01},
        "ops": {"label": "OPS", "favorable": "higher", "tolerance": .01},
        "iso": {"label": "ISO", "favorable": "higher", "tolerance": .01},
        "avg_exit_velocity": {"label": "Average Exit Velocity", "favorable": "higher", "tolerance": .5},
        "max_exit_velocity": {"label": "Maximum Exit Velocity", "favorable": "higher", "tolerance": .5},
        "avg_launch_angle": {"label": "Average Launch Angle", "favorable": "higher", "tolerance": .5},
        "hard_hit_pct": {"label": "Hard-Hit Rate", "favorable": "higher", "tolerance": .01},
        "barrel_pct": {"label": "Barrel Rate", "favorable": "higher", "tolerance": .01},
        "k_pct": {"label": "Strikeout Rate", "favorable": "lower", "tolerance": .01},
        "bb_pct": {"label": "Walk Rate", "favorable": "higher", "tolerance": .01},
        "whiff_pct": {"label": "Whiff Rate", "favorable": "lower", "tolerance": .01},
        "contact_pct": {"label": "Contact Rate", "favorable": "higher", "tolerance": .01},
    },
    "pitcher": {
        "k_pct": {"label": "Strikeout Rate", "favorable": "higher", "tolerance": .01},
        "bb_pct": {"label": "Walk Rate", "favorable": "lower", "tolerance": .01},
        "hard_hit_pct": {"label": "Hard-Hit Rate Allowed", "favorable": "lower", "tolerance": .01},
        "avg_velocity": {"label": "Average Pitch Velocity", "favorable": "higher", "tolerance": .3},
        "avg_spin_rate": {"label": "Average Spin Rate", "favorable": "higher", "tolerance": 25.0},
        "xwoba": {"label": "xwOBA Allowed", "favorable": "lower", "tolerance": .01},
        "xba": {"label": "xBA Allowed", "favorable": "lower", "tolerance": .01},
        "avg_horiz_break": {"label": "Average Horizontal Break", "favorable": "higher", "tolerance": .25},
        "avg_vert_break": {"label": "Average Vertical Break", "favorable": "higher", "tolerance": .25},
    },
}

ROLLING_NUMERIC_FIELDS: Dict[str, Dict[str, str]] = {
    "hitter": {
        "actual_pa": "Plate Appearances",
        "actual_ab": "At Bats",
        "event_count": "Pitch Events",
        "batted_ball_count": "Batted Balls",
        "hard_hit_count": "Hard-Hit Balls",
        "barrel_count": "Barrels",
        "hits": "Hits",
        "doubles": "Doubles",
        "triples": "Triples",
        "walks": "Walks",
        "strikeouts": "Strikeouts",
        "home_runs": "Home Runs",
        "total_bases": "Total Bases",
        **{key: value["label"] for key, value in METRICS["hitter"].items()},
        "swings": "Swings",
        "whiffs": "Whiffs",
    },
    "pitcher": {
        "batters_faced": "Batters Faced",
        "pitch_count": "Pitch Count",
        "batted_ball_count": "Batted Balls Allowed",
        "hard_hit_count": "Hard-Hit Balls Allowed",
        "strikeouts": "Strikeouts",
        "walks": "Walks",
        **{key: value["label"] for key, value in METRICS["pitcher"].items()},
    },
}

BASELINES = {
    "season_to_date": "Season to date",
    "previous_n_days": "Previous N days",
}


def supported_trend_configuration() -> Dict[str, Any]:
    return {
        "player_types": ["hitter", "pitcher"],
        "window_presets": [7, 15, 30, 60],
        "window_min": 3,
        "window_max": 90,
        "baselines": [{"value": key, "label": label} for key, label in BASELINES.items()],
        "minimum_sample_units": {"hitter": "plate_appearances", "pitcher": "batters_faced"},
        "metrics": {
            player_type: [
                {"value": key, **metadata} for key, metadata in metrics.items()
            ]
            for player_type, metrics in METRICS.items()
        },
        "unsupported_baselines": {
            "prior_equivalent_period": (
                "Raw Statcast is date-bounded but the repository does not guarantee a complete "
                "authoritative prior-season equivalent period."
            )
        },
    }


def _validated_config(config: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    value = dict(config or {})
    player_type = str(value.get("player_type") or "").strip().lower()
    if player_type not in METRICS:
        raise ValueError("Player Trends requires player_type hitter or pitcher")
    try:
        days = int(value.get("window_days"))
    except (TypeError, ValueError) as exc:
        raise ValueError("Player Trends requires a numeric N-day window") from exc
    if days < 3 or days > 90:
        raise ValueError("Player Trends window_days must be between 3 and 90")
    baseline = str(value.get("comparison_baseline") or "").strip().lower()
    if baseline not in BASELINES:
        raise ValueError(
            "Unsupported Player Trends comparison_baseline; use season_to_date or previous_n_days"
        )
    try:
        minimum = int(value.get("minimum_sample_size"))
    except (TypeError, ValueError) as exc:
        raise ValueError("Player Trends requires a minimum sample size") from exc
    if minimum < 1 or minimum > 1000:
        raise ValueError("Player Trends minimum_sample_size must be between 1 and 1000")
    direction = str(value.get("trend_direction") or "all").strip().lower()
    if direction not in {"improving", "declining", "stable", "all"}:
        raise ValueError("Invalid Player Trends trend_direction")
    requested_metrics = value.get("selected_metrics")
    if not isinstance(requested_metrics, list) or not requested_metrics:
        raise ValueError("Player Trends requires at least one selected metric")
    metrics = list(dict.fromkeys(str(metric).strip() for metric in requested_metrics))
    unsupported = [metric for metric in metrics if metric not in METRICS[player_type]]
    if unsupported:
        raise ValueError(f"Unsupported {player_type} trend metric(s): {', '.join(unsupported)}")
    return {
        "player_type": player_type,
        "window_days": days,
        "comparison_baseline": baseline,
        "minimum_sample_size": minimum,
        "trend_direction": direction,
        "selected_metrics": metrics,
    }


def _date_ranges(as_of_date: dt.date, config: Dict[str, Any]) -> Dict[str, dt.date]:
    window_end = as_of_date
    window_start = window_end - dt.timedelta(days=config["window_days"] - 1)
    if config["comparison_baseline"] == "previous_n_days":
        baseline_end = window_start - dt.timedelta(days=1)
        baseline_start = baseline_end - dt.timedelta(days=config["window_days"] - 1)
    else:
        baseline_start = dt.date(as_of_date.year, 1, 1)
        baseline_end = as_of_date
    return {
        "window_start": window_start,
        "window_end": window_end,
        "baseline_start": baseline_start,
        "baseline_end": baseline_end,
    }


def _ratio(numerator: int, denominator: int, digits: int = 3) -> Optional[float]:
    return round(numerator / denominator, digits) if denominator else None


def _aggregate_hitter_period(
    session,
    start: dt.date,
    end: dt.date,
    player_ids: List[int],
    metrics: List[str],
) -> Dict[int, Dict[str, Any]]:
    """Compute the batter rolling-page metrics in SQL instead of loading every pitch."""
    terminal = (
        session.query(
            StatcastEvent.batter_id.label("player_id"),
            StatcastEvent.game_pk.label("game_pk"),
            StatcastEvent.at_bat_number.label("at_bat_number"),
            func.max(case((StatcastEvent.events.in_(list(HIT_EVENTS)), 1), else_=0)).label("is_hit"),
            func.max(case((StatcastEvent.events == "double", 1), else_=0)).label("is_double"),
            func.max(case((StatcastEvent.events == "triple", 1), else_=0)).label("is_triple"),
            func.max(case((StatcastEvent.events == "home_run", 1), else_=0)).label("is_home_run"),
            func.max(case((StatcastEvent.events.in_(list(WALK_EVENTS)), 1), else_=0)).label("is_walk"),
            func.max(case((StatcastEvent.events.in_(list(HBP_EVENTS)), 1), else_=0)).label("is_hbp"),
            func.max(case((StatcastEvent.events.in_(list(STRIKEOUT_EVENTS)), 1), else_=0)).label("is_strikeout"),
            func.max(case((StatcastEvent.events == "sac_fly", 1), else_=0)).label("is_sac_fly"),
            func.max(case((StatcastEvent.events.notin_(list(NON_AB_EVENTS)), 1), else_=0)).label("is_ab"),
            func.max(
                case(
                    *[(StatcastEvent.events == event, bases) for event, bases in TOTAL_BASES.items()],
                    else_=0,
                )
            ).label("total_bases"),
        )
        .filter(
            StatcastEvent.game_date >= start,
            StatcastEvent.game_date <= end,
            StatcastEvent.batter_id.isnot(None),
            StatcastEvent.batter_id.in_(player_ids),
            StatcastEvent.events.in_(list(TERMINAL_EVENTS)),
            StatcastEvent.game_pk.isnot(None),
            StatcastEvent.at_bat_number.isnot(None),
        )
        .group_by(StatcastEvent.batter_id, StatcastEvent.game_pk, StatcastEvent.at_bat_number)
        .subquery()
    )
    counting_rows = (
        session.query(
            terminal.c.player_id,
            func.count().label("pa"),
            func.sum(terminal.c.is_ab).label("ab"),
            func.sum(terminal.c.is_hit).label("hits"),
            func.sum(terminal.c.is_double).label("doubles"),
            func.sum(terminal.c.is_triple).label("triples"),
            func.sum(terminal.c.is_home_run).label("home_runs"),
            func.sum(terminal.c.is_walk).label("walks"),
            func.sum(terminal.c.is_hbp).label("hbp"),
            func.sum(terminal.c.is_strikeout).label("strikeouts"),
            func.sum(terminal.c.is_sac_fly).label("sacrifice_flies"),
            func.sum(terminal.c.total_bases).label("total_bases"),
        )
        .group_by(terminal.c.player_id)
        .all()
    )

    pitch_rows = []
    if set(metrics).intersection({"avg_exit_velocity", "hard_hit_pct", "barrel_pct", "whiff_pct"}):
        pitch = (
            session.query(
                StatcastEvent.batter_id.label("player_id"),
                StatcastEvent.game_pk.label("game_pk"),
                StatcastEvent.at_bat_number.label("at_bat_number"),
                StatcastEvent.pitch_number.label("pitch_number"),
                func.max(StatcastEvent.launch_speed).label("launch_speed"),
                func.max(StatcastEvent.launch_angle).label("launch_angle"),
                func.max(case((StatcastEvent.description.in_(list(SWING_DESCRIPTIONS)), 1), else_=0)).label("is_swing"),
                func.max(case((StatcastEvent.description.in_(list(WHIFF_DESCRIPTIONS)), 1), else_=0)).label("is_whiff"),
            )
            .filter(
                StatcastEvent.game_date >= start,
                StatcastEvent.game_date <= end,
                StatcastEvent.batter_id.isnot(None),
                StatcastEvent.batter_id.in_(player_ids),
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
        pitch_rows = (
            session.query(
                pitch.c.player_id,
                func.count().label("event_count"),
                func.count(pitch.c.launch_speed).label("batted_balls"),
                func.avg(pitch.c.launch_speed).label("avg_exit_velocity"),
                func.max(pitch.c.launch_speed).label("max_exit_velocity"),
                func.avg(pitch.c.launch_angle).label("avg_launch_angle"),
                func.sum(case((pitch.c.launch_speed >= 95.0, 1), else_=0)).label("hard_hits"),
                func.sum(
                    case(
                        (
                            and_(
                                pitch.c.launch_speed >= 98.0,
                                pitch.c.launch_angle >= 8.0,
                                pitch.c.launch_angle <= 50.0,
                            ),
                            1,
                        ),
                        else_=0,
                    )
                ).label("barrels"),
                func.sum(pitch.c.is_swing).label("swings"),
                func.sum(pitch.c.is_whiff).label("whiffs"),
            )
            .group_by(pitch.c.player_id)
            .all()
        )
    pitch_by_player = {int(row.player_id): row for row in pitch_rows}

    result: Dict[int, Dict[str, Any]] = {}
    for row in counting_rows:
        player_id = int(row.player_id)
        pa = int(row.pa or 0)
        ab = int(row.ab or 0)
        hits = int(row.hits or 0)
        doubles = int(row.doubles or 0)
        triples = int(row.triples or 0)
        home_runs = int(row.home_runs or 0)
        walks = int(row.walks or 0)
        hbp = int(row.hbp or 0)
        strikeouts = int(row.strikeouts or 0)
        sacrifice_flies = int(row.sacrifice_flies or 0)
        total_bases = int(row.total_bases or 0)
        batting_avg = _ratio(hits, ab)
        on_base_pct = _ratio(hits + walks + hbp, ab + walks + hbp + sacrifice_flies)
        slugging_pct = _ratio(total_bases, ab)
        pitch_row = pitch_by_player.get(player_id)
        batted_balls = int(getattr(pitch_row, "batted_balls", 0) or 0)
        hard_hits = int(getattr(pitch_row, "hard_hits", 0) or 0)
        barrels = int(getattr(pitch_row, "barrels", 0) or 0)
        swings = int(getattr(pitch_row, "swings", 0) or 0)
        whiffs = int(getattr(pitch_row, "whiffs", 0) or 0)
        avg_exit_velocity = getattr(pitch_row, "avg_exit_velocity", None)
        max_exit_velocity = getattr(pitch_row, "max_exit_velocity", None)
        avg_launch_angle = getattr(pitch_row, "avg_launch_angle", None)
        result[player_id] = {
            "sample_size": pa,
            "actual_pa": pa,
            "actual_ab": ab,
            "event_count": int(getattr(pitch_row, "event_count", 0) or 0),
            "batted_ball_count": batted_balls,
            "hard_hit_count": hard_hits,
            "barrel_count": barrels,
            "hits": hits,
            "doubles": doubles,
            "triples": triples,
            "walks": walks,
            "strikeouts": strikeouts,
            "home_runs": home_runs,
            "total_bases": total_bases,
            "batting_avg": batting_avg,
            "on_base_pct": on_base_pct,
            "slugging_pct": slugging_pct,
            "ops": (
                round(on_base_pct + slugging_pct, 3)
                if on_base_pct is not None and slugging_pct is not None
                else None
            ),
            "iso": (
                round(slugging_pct - batting_avg, 3)
                if slugging_pct is not None and batting_avg is not None
                else None
            ),
            "avg_exit_velocity": round(float(avg_exit_velocity), 1) if avg_exit_velocity is not None else None,
            "max_exit_velocity": round(float(max_exit_velocity), 1) if max_exit_velocity is not None else None,
            "avg_launch_angle": round(float(avg_launch_angle), 1) if avg_launch_angle is not None else None,
            "hard_hit_pct": _ratio(hard_hits, batted_balls),
            "barrel_pct": _ratio(barrels, batted_balls),
            "k_pct": _ratio(strikeouts, pa),
            "bb_pct": _ratio(walks, pa),
            "swings": swings,
            "whiffs": whiffs,
            "whiff_pct": _ratio(whiffs, swings),
            "contact_pct": round(1 - (whiffs / swings), 3) if swings else None,
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
        }
    return result


def _aggregate_pitcher_period(
    session,
    start: dt.date,
    end: dt.date,
    player_ids: List[int],
) -> Dict[int, Dict[str, Any]]:
    """Compute the pitcher rolling-page metrics in one grouped SQL query."""
    filters = (
        StatcastEvent.game_date >= start,
        StatcastEvent.game_date <= end,
        StatcastEvent.pitcher_id.isnot(None),
        StatcastEvent.pitcher_id.in_(player_ids),
    )
    canonical_ids = canonical_event_ids_subquery(session, *filters)
    rows = (
        session.query(
            StatcastEvent.pitcher_id.label("player_id"),
            func.count(StatcastEvent.id).label("pitch_count"),
            func.sum(
                case(
                    (
                        and_(StatcastEvent.events.isnot(None), StatcastEvent.events != ""),
                        1,
                    ),
                    else_=0,
                )
            ).label("batters_faced"),
            func.sum(case((StatcastEvent.events == "strikeout", 1), else_=0)).label("strikeouts"),
            func.sum(case((StatcastEvent.events == "walk", 1), else_=0)).label("walks"),
            func.count(StatcastEvent.launch_speed).label("batted_balls"),
            func.sum(case((StatcastEvent.launch_speed >= 95.0, 1), else_=0)).label("hard_hits"),
            func.avg(StatcastEvent.release_speed).label("avg_velocity"),
            func.avg(StatcastEvent.release_spin_rate).label("avg_spin_rate"),
            func.avg(StatcastEvent.estimated_woba_using_speedangle).label("xwoba"),
            func.avg(StatcastEvent.estimated_ba_using_speedangle).label("xba"),
            func.avg(StatcastEvent.pfx_x).label("avg_horiz_break"),
            func.avg(StatcastEvent.pfx_z).label("avg_vert_break"),
        )
        .join(canonical_ids, StatcastEvent.id == canonical_ids.c.event_id)
        .group_by(StatcastEvent.pitcher_id)
        .all()
    )
    result: Dict[int, Dict[str, Any]] = {}
    for row in rows:
        player_id = int(row.player_id)
        batters_faced = int(row.batters_faced or 0)
        batted_balls = int(row.batted_balls or 0)
        result[player_id] = {
            "sample_size": batters_faced,
            "batters_faced": batters_faced,
            "pitch_count": int(row.pitch_count or 0),
            "batted_ball_count": batted_balls,
            "hard_hit_count": int(row.hard_hits or 0),
            "strikeouts": int(row.strikeouts or 0),
            "walks": int(row.walks or 0),
            "k_pct": _ratio(int(row.strikeouts or 0), batters_faced),
            "bb_pct": _ratio(int(row.walks or 0), batters_faced),
            "hard_hit_pct": _ratio(int(row.hard_hits or 0), batted_balls),
            "avg_velocity": float(row.avg_velocity) if row.avg_velocity is not None else None,
            "avg_spin_rate": float(row.avg_spin_rate) if row.avg_spin_rate is not None else None,
            "xwoba": float(row.xwoba) if row.xwoba is not None else None,
            "xba": float(row.xba) if row.xba is not None else None,
            "avg_horiz_break": float(row.avg_horiz_break) if row.avg_horiz_break is not None else None,
            "avg_vert_break": float(row.avg_vert_break) if row.avg_vert_break is not None else None,
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
        }
    return result


def _aggregate_period(
    session,
    player_type: str,
    start: dt.date,
    end: dt.date,
    player_ids: List[int],
    metrics: List[str],
) -> Dict[int, Dict[str, Any]]:
    """Batch the ID-page metric definitions without materializing the event warehouse."""
    if player_type == "hitter":
        return _aggregate_hitter_period(session, start, end, player_ids, metrics)
    return _aggregate_pitcher_period(session, start, end, player_ids)


def _classify(metric: str, player_type: str, change: float) -> str:
    metadata = METRICS[player_type][metric]
    if abs(change) <= metadata["tolerance"]:
        return "stable"
    favorable_change = change if metadata["favorable"] == "higher" else -change
    return "improving" if favorable_change > 0 else "declining"


def _matches_condition(row: Dict[str, Any], condition: Dict[str, Any]) -> bool:
    field = str(condition.get("field") or "")
    operator = str(condition.get("operator") or "eq")
    actual = row.get(field)
    expected = condition.get("value")
    if operator == "is_null":
        return actual is None
    if operator == "is_not_null":
        return actual is not None
    if operator == "in":
        values = expected if isinstance(expected, list) else [item.strip() for item in str(expected).split(",")]
        return str(actual) in {str(item) for item in values}
    if operator == "contains":
        return str(expected).lower() in str(actual or "").lower()
    if operator in {"gt", "gte", "lt", "lte"}:
        try:
            left, right = float(actual), float(expected)
        except (TypeError, ValueError):
            return False
        return {"gt": left > right, "gte": left >= right, "lt": left < right, "lte": left <= right}[operator]
    return (actual != expected) if operator == "neq" else (str(actual) == str(expected))


def _apply_filters(rows: Iterable[Dict[str, Any]], filters: Any) -> List[Dict[str, Any]]:
    if isinstance(filters, list):
        conditions, logic = filters, "and"
    else:
        conditions = list((filters or {}).get("conditions") or [])
        logic = str((filters or {}).get("logic") or "and").lower()
    if not conditions:
        return list(rows)
    return [
        row for row in rows
        if (any(_matches_condition(row, condition) for condition in conditions)
            if logic == "or"
            else all(_matches_condition(row, condition) for condition in conditions))
    ]


def _snapshot_query(session, as_of_date: dt.date, config: Dict[str, Any]):
    return session.query(PlayerTrendSnapshot).filter(
        PlayerTrendSnapshot.as_of_date == as_of_date,
        PlayerTrendSnapshot.player_type == config["player_type"],
        PlayerTrendSnapshot.window_days == config["window_days"],
        PlayerTrendSnapshot.comparison_baseline == config["comparison_baseline"],
        PlayerTrendSnapshot.metric.in_(config["selected_metrics"]),
    )


def _cached_snapshots_are_fresh(
    snapshots: List[PlayerTrendSnapshot],
    *,
    as_of_date: dt.date,
    selected_metrics: List[str],
) -> bool:
    if {row.metric for row in snapshots} != set(selected_metrics):
        return False
    if as_of_date < dt.date.today():
        return True
    cutoff = dt.datetime.utcnow() - dt.timedelta(minutes=30)
    return all(row.generated_at and row.generated_at >= cutoff for row in snapshots)


def _materialize_trend_dataset(
    session,
    *,
    as_of_date: dt.date,
    config: Dict[str, Any],
    ranges: Dict[str, dt.date],
) -> List[PlayerTrendSnapshot]:
    players_list = (
        session.query(DashboardPlayer)
        .filter(
            DashboardPlayer.is_active.is_(True),
            DashboardPlayer.player_type == config["player_type"],
        )
        .all()
    )
    players = {int(player.mlb_player_id): player for player in players_list}
    player_ids = sorted(players)
    if not player_ids:
        return []

    all_metrics = list(METRICS[config["player_type"]])
    window = _aggregate_period(
        session,
        config["player_type"],
        ranges["window_start"],
        ranges["window_end"],
        player_ids,
        all_metrics,
    )
    baseline = _aggregate_period(
        session,
        config["player_type"],
        ranges["baseline_start"],
        ranges["baseline_end"],
        player_ids,
        all_metrics,
    )
    comparable_ids = sorted(set(window).intersection(baseline))
    generated_at = dt.datetime.utcnow()
    records: List[Dict[str, Any]] = []
    for player_id in comparable_ids:
        current = window[player_id]
        comparison = baseline[player_id]
        player = players[player_id]
        window_metrics = {
            key: current.get(key)
            for key in ROLLING_NUMERIC_FIELDS[config["player_type"]]
        }
        baseline_metrics = {
            key: comparison.get(key)
            for key in ROLLING_NUMERIC_FIELDS[config["player_type"]]
        }
        for metric in config["selected_metrics"]:
            current_value = current.get(metric)
            baseline_value = comparison.get(metric)
            change = (
                float(current_value) - float(baseline_value)
                if current_value is not None and baseline_value is not None
                else None
            )
            records.append({
                "as_of_date": as_of_date,
                "player_id": player_id,
                "player_name": player.full_name or str(player_id),
                "player_type": config["player_type"],
                "team": player.current_team_name,
                "window_days": config["window_days"],
                "comparison_baseline": config["comparison_baseline"],
                "metric": metric,
                "window_start": ranges["window_start"],
                "window_end": ranges["window_end"],
                "baseline_start": ranges["baseline_start"],
                "baseline_end": ranges["baseline_end"],
                "window_sample_size": int(current.get("sample_size") or 0),
                "baseline_sample_size": int(comparison.get("sample_size") or 0),
                "current_value": float(current_value) if current_value is not None else None,
                "baseline_value": float(baseline_value) if baseline_value is not None else None,
                "absolute_change": change,
                "percentage_change": (
                    change / abs(float(baseline_value))
                    if change is not None and float(baseline_value) != 0
                    else None
                ),
                "trend_direction": (
                    _classify(metric, config["player_type"], change)
                    if change is not None
                    else None
                ),
                "favorable_direction": METRICS[config["player_type"]][metric]["favorable"],
                "window_metrics_json": window_metrics,
                "baseline_metrics_json": baseline_metrics,
                "source": "statcast_events_sql_aggregate",
                "generated_at": generated_at,
            })

    _snapshot_query(session, as_of_date, config).delete(synchronize_session=False)
    if records:
        session.bulk_insert_mappings(PlayerTrendSnapshot, records)
    session.commit()
    return _snapshot_query(session, as_of_date, config).all()


def _snapshot_to_row(snapshot: PlayerTrendSnapshot) -> Dict[str, Any]:
    window_metrics = dict(snapshot.window_metrics_json or {})
    baseline_metrics = dict(snapshot.baseline_metrics_json or {})
    row: Dict[str, Any] = {
        "player_id": snapshot.player_id,
        "player_name": snapshot.player_name,
        "player_type": snapshot.player_type,
        "team": snapshot.team,
        "metric": snapshot.metric,
        "metric_label": METRICS[snapshot.player_type][snapshot.metric]["label"],
        "selected_window_days": snapshot.window_days,
        "comparison_baseline": snapshot.comparison_baseline,
        "window_start": snapshot.window_start.isoformat(),
        "window_end": snapshot.window_end.isoformat(),
        "baseline_start": snapshot.baseline_start.isoformat(),
        "baseline_end": snapshot.baseline_end.isoformat(),
        "window_sample_size": snapshot.window_sample_size,
        "baseline_sample_size": snapshot.baseline_sample_size,
        "current_value": snapshot.current_value,
        "baseline_value": snapshot.baseline_value,
        "absolute_change": snapshot.absolute_change,
        "percentage_change": snapshot.percentage_change,
        "trend_direction": snapshot.trend_direction,
        "favorable_direction": snapshot.favorable_direction,
        "freshness_date": snapshot.as_of_date.isoformat(),
        "dataset_generated_at": snapshot.generated_at.isoformat(),
        "source": snapshot.source,
    }
    for key in ROLLING_NUMERIC_FIELDS[snapshot.player_type]:
        row[f"window_{key}"] = window_metrics.get(key)
        row[f"baseline_{key}"] = baseline_metrics.get(key)
    for metric in METRICS[snapshot.player_type]:
        current = window_metrics.get(metric)
        baseline = baseline_metrics.get(metric)
        change = (
            float(current) - float(baseline)
            if current is not None and baseline is not None
            else None
        )
        row[f"{metric}_change"] = change
        row[f"{metric}_change_pct"] = (
            change / abs(float(baseline))
            if change is not None and float(baseline) != 0
            else None
        )
        row[f"{metric}_direction"] = (
            _classify(metric, snapshot.player_type, change)
            if change is not None
            else None
        )
    return row


def query_player_trends(
    session,
    *,
    as_of_date: dt.date,
    trend_config: Dict[str, Any],
    filters: Any = None,
    page_size: int = 50,
    page_number: int = 1,
    sort_by: str = "absolute_change",
    sort_direction: str = "desc",
    selected_fields: Optional[List[str]] = None,
    include_metadata: bool = True,
) -> Dict[str, Any]:
    config = _validated_config(trend_config)
    ranges = _date_ranges(as_of_date, config)
    snapshots = _snapshot_query(session, as_of_date, config).all()
    dataset_cache_hit = _cached_snapshots_are_fresh(
        snapshots,
        as_of_date=as_of_date,
        selected_metrics=config["selected_metrics"],
    )
    if not dataset_cache_hit:
        snapshots = _materialize_trend_dataset(
            session,
            as_of_date=as_of_date,
            config=config,
            ranges=ranges,
        )

    rows: List[Dict[str, Any]] = []
    missing_metric_pairs = 0
    comparable_player_ids = set()
    for snapshot in snapshots:
        comparable_player_ids.add(snapshot.player_id)
        if (
            snapshot.window_sample_size < config["minimum_sample_size"]
            or snapshot.baseline_sample_size < config["minimum_sample_size"]
        ):
            continue
        if snapshot.current_value is None or snapshot.baseline_value is None:
            missing_metric_pairs += 1
            continue
        if (
            config["trend_direction"] != "all"
            and snapshot.trend_direction != config["trend_direction"]
        ):
            continue
        rows.append(_snapshot_to_row(snapshot))
    rows = _apply_filters(rows, filters)
    query = normalize_query(page_size, page_number, sort_by, sort_direction)
    rows.sort(
        key=lambda row: (row.get(query["sort_by"]) is None, row.get(query["sort_by"])),
        reverse=query["sort_direction"] == "desc",
    )
    for index, row in enumerate(rows, 1):
        row["rank"] = index
    total = len(rows)
    page_rows = rows[query["offset"]:query["offset"] + query["page_size"]]
    result = {
        "records": page_rows,
        "items": page_rows,
        "totalSize": total,
        "total_count": total,
        "done": query["offset"] + query["page_size"] >= total,
        "query": query,
        "trend_config": config,
        "supported_trend_configuration": supported_trend_configuration(),
        "provenance": {
            "source": "player_trend_snapshots",
            "upstream_source": "statcast_events",
            "calculation": "sql_aggregate_equivalent_to_player_id_rolling_pages",
            "requested_date": as_of_date.isoformat(),
            **{key: value.isoformat() for key, value in ranges.items()},
        },
        "data_quality": {
            "players_with_both_periods": len(comparable_player_ids),
            "missing_metric_pairs": missing_metric_pairs,
            "minimum_sample_size": config["minimum_sample_size"],
            "dataset_cache_hit": dataset_cache_hit,
            "dataset_row_count": len(snapshots),
        },
        "page_info": {
            "page_number": query["page_number"],
            "page_size": query["page_size"],
            "page_count": math.ceil(total / query["page_size"]) if total else 0,
            "record_count": len(page_rows),
            "total_count": total,
            "has_next": query["offset"] + query["page_size"] < total,
            "has_previous": query["page_number"] > 1 and total > 0,
        },
    }
    if include_metadata:
        result["object_info"] = describe_report_type("player_trends")
    if selected_fields:
        result["selected_fields"] = list(selected_fields)
    return result

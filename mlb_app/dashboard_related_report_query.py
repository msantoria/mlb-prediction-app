"""Validated SQL queries for selected one-to-many dashboard relationships."""

from __future__ import annotations

import datetime as dt
import math
from typing import Any, Dict, Iterable, List, Optional, Tuple

from sqlalchemy import and_, case, func, or_
from sqlalchemy.orm import aliased

from .dashboard_object_models import DashboardPlayer
from .dashboard_report_types import FIELD_CATALOG, REPORT_TYPES, describe_report_type
from .database import BatterPitchTypeMatchup, PitchArsenal
from .model_tracker import ModelTrackerSnapshot


BATTER_DIRECTORY = aliased(DashboardPlayer, name="batter_directory")
OPPOSING_PITCHER_DIRECTORY = aliased(DashboardPlayer, name="opposing_pitcher_directory")


MODELS = {
    "players_lineup_history": DashboardPlayer,
    "hitters_arsenal_splits": BatterPitchTypeMatchup,
    "competitive_batter_arsenal": BatterPitchTypeMatchup,
    "model_tracker_snapshots": ModelTrackerSnapshot,
}

COLUMN_NAMES = {
    "players_lineup_history": (
        "mlb_player_id", "full_name", "player_type", "current_team_id", "current_team_name",
        "most_recent_lineup_date", "lineup_appearance_count", "most_recent_game_date",
        "tracked_game_count", "active_status_reason", "is_active",
    ),
    "hitters_arsenal_splits": (
        "id", "batter_id", "batter_name", "batter_team_id", "opposing_pitcher_id",
        "pitch_type", "game_pk", "target_date", "date_end", "pitches_seen", "pa_ended",
        "xwoba", "xba", "avg_exit_velocity", "avg_launch_angle", "hard_hit_pct",
        "whiff_pct", "k_pct", "source", "refreshed_at",
    ),
    "competitive_batter_arsenal": (
        "id", "batter_id", "batter_name", "batter_team_id", "opposing_pitcher_id",
        "team_name", "opposing_team_name",
        "pitch_type", "game_pk", "target_date", "date_end", "pitches_seen", "pa_ended",
        "xwoba", "xba", "avg_exit_velocity", "avg_launch_angle", "hard_hit_pct",
        "whiff_pct", "k_pct", "source", "refreshed_at", "pitcher_pitch_name",
        "pitcher_pitch_count", "pitcher_usage_pct", "pitcher_whiff_pct",
        "pitcher_strikeout_pct", "pitcher_xwoba", "pitcher_hard_hit_pct",
        "edge_score", "matchup_confidence",
    ),
    "model_tracker_snapshots": (
        "id", "snapshot_date", "source", "source_component", "game_pk", "player_id",
        "player_name", "team_name", "opponent_name", "away_team", "home_team",
        "market_type", "pick_type", "pick_label", "model_name", "model_version",
        "model_probability", "market_implied_probability", "edge", "score", "confidence",
        "line", "price", "expected_value", "projected_total", "projected_home_runs",
        "projected_away_runs", "home_win_probability", "away_win_probability",
        "primary_reason", "game_status_at_snapshot", "result_status", "grade",
        "grade_reason", "created_at", "updated_at", "last_compared_at",
    ),
}


def _columns(report_type: str) -> Dict[str, Any]:
    if report_type == "competitive_batter_arsenal":
        pa = func.coalesce(BatterPitchTypeMatchup.pa_ended, BatterPitchTypeMatchup.pa, 0)
        usage = func.coalesce(PitchArsenal.usage_pct, 0.0)
        pa_component = case((pa >= 12, 1.0), else_=pa / 12.0)
        usage_component = case(
            (usage < 0.25, 0.25),
            (usage > 1.0, 1.0),
            else_=usage,
        )
        confidence = case(
            (pa_component * usage_component + case((pa >= 3, 0.25), else_=0.0) > 1.0, 1.0),
            else_=pa_component * usage_component + case((pa >= 3, 0.25), else_=0.0),
        )
        raw_edge = (
            func.coalesce((BatterPitchTypeMatchup.batting_avg - 0.245) * 4.0, 0.0)
            + func.coalesce((BatterPitchTypeMatchup.xwoba - 0.320) * 5.0, 0.0)
            - func.coalesce((PitchArsenal.xwoba - 0.320) * 5.0, 0.0)
            - func.coalesce((PitchArsenal.hard_hit_pct - 0.35) * 2.0, 0.0)
        )
        usage_weight = case(
            (PitchArsenal.usage_pct.is_(None), 1.0),
            (PitchArsenal.usage_pct < 0.35, 0.35),
            (PitchArsenal.usage_pct > 1.0, 1.0),
            else_=PitchArsenal.usage_pct,
        )
        columns = {
            name: getattr(BatterPitchTypeMatchup, name)
            for name in COLUMN_NAMES[report_type]
            if hasattr(BatterPitchTypeMatchup, name)
        }
        columns.update({
            "team_name": BATTER_DIRECTORY.current_team_name,
            "opposing_team_name": OPPOSING_PITCHER_DIRECTORY.current_team_name,
            "pitcher_pitch_name": PitchArsenal.pitch_name,
            "pitcher_pitch_count": PitchArsenal.pitch_count,
            "pitcher_usage_pct": PitchArsenal.usage_pct,
            "pitcher_whiff_pct": PitchArsenal.whiff_pct,
            "pitcher_strikeout_pct": PitchArsenal.strikeout_pct,
            "pitcher_xwoba": PitchArsenal.xwoba,
            "pitcher_hard_hit_pct": PitchArsenal.hard_hit_pct,
            "edge_score": raw_edge * usage_weight,
            "matchup_confidence": confidence,
        })
        return columns
    model = MODELS[report_type]
    return {name: getattr(model, name) for name in COLUMN_NAMES[report_type]}


def _conditions(filters: Any, report_type: str) -> Tuple[str, List[Dict[str, Any]]]:
    if filters is None:
        return "and", []
    if isinstance(filters, list):
        return "and", filters
    if not isinstance(filters, dict):
        raise ValueError("filters must be an object or list of conditions")
    logic = str(filters.get("logic") or "and").strip().lower()
    if logic not in {"and", "or"}:
        raise ValueError("filters.logic must be 'and' or 'or'")
    conditions = list(filters.get("conditions") or [])
    aliases = {
        "players_lineup_history": (
            ("search_text", "full_name", "contains"),
            ("team", "current_team_name", "eq"),
            ("min_lineup_appearances", "lineup_appearance_count", "gte"),
        ),
        "hitters_arsenal_splits": (
            ("search_text", "batter_name", "contains"),
            ("team_id", "batter_team_id", "eq"),
            ("pitch_type", "pitch_type", "eq"),
            ("min_pitches_seen", "pitches_seen", "gte"),
        ),
        "competitive_batter_arsenal": (
            ("search_text", "batter_name", "contains"),
            ("team_id", "batter_team_id", "eq"),
            ("pitch_type", "pitch_type", "eq"),
            ("min_pitches_seen", "pitches_seen", "gte"),
        ),
        "model_tracker_snapshots": (),
    }[report_type]
    for key, field, operator in aliases:
        if filters.get(key) not in (None, "", "All"):
            conditions.append({"field": field, "operator": operator, "value": filters[key]})
    return logic, conditions


def _apply_filters(query: Any, report_type: str, filters: Any) -> Tuple[Any, str, List[Dict[str, Any]]]:
    columns = _columns(report_type)
    catalog = {field["name"]: field for field in FIELD_CATALOG[report_type]}
    logic, applied = _conditions(filters, report_type)
    expressions = []
    for condition in applied:
        if not isinstance(condition, dict):
            raise ValueError("Each filter condition must be an object")
        field_name = str(condition.get("field") or "")
        operator = str(condition.get("operator") or "eq").lower()
        field = catalog.get(field_name)
        if not field or not field.get("filterable") or field_name not in columns:
            raise ValueError(f"Unsupported filter field: {field_name}")
        if operator not in field["supported_operators"]:
            raise ValueError(f"Unsupported operator '{operator}' for field '{field_name}'")
        column, value = columns[field_name], condition.get("value")
        if operator == "eq": expression = column == value
        elif operator == "neq": expression = column != value
        elif operator == "in":
            if not isinstance(value, (list, tuple, set)):
                raise ValueError(f"Operator 'in' for field '{field_name}' requires a list")
            expression = column.in_(list(value))
        elif operator == "contains": expression = func.lower(column).contains(str(value).lower())
        elif operator == "gt": expression = column > value
        elif operator == "gte": expression = column >= value
        elif operator == "lt": expression = column < value
        elif operator == "lte": expression = column <= value
        elif operator == "is_null": expression = column.is_(None)
        elif operator == "is_not_null": expression = column.is_not(None)
        else: raise ValueError(f"Unsupported operator: {operator}")
        expressions.append(expression)
    if expressions:
        query = query.filter(or_(*expressions) if logic == "or" else and_(*expressions))
    return query, logic, applied


def _iso(value: Any) -> Any:
    return value.isoformat() if isinstance(value, (dt.date, dt.datetime)) else value


def query_related_report(
    session: Any,
    report_type: str,
    *,
    filters: Any = None,
    weights: Any = None,
    page_size: int = 50,
    page_number: int = 1,
    sort_by: Optional[str] = None,
    sort_direction: str = "desc",
    selected_fields: Optional[Iterable[str]] = None,
    include_metadata: bool = True,
    as_of_date: Optional[dt.date] = None,
) -> Dict[str, Any]:
    if report_type not in MODELS or not REPORT_TYPES[report_type].get("queryable"):
        raise ValueError(f"Unsupported related report type: {report_type}")
    if weights:
        raise ValueError(f"Weights are not supported for related report type: {report_type}")
    if not isinstance(page_size, int) or page_size < 1 or page_size > 250:
        raise ValueError("page_size must be between 1 and 250")
    if not isinstance(page_number, int) or page_number < 1:
        raise ValueError("page_number must be at least 1")
    direction = str(sort_direction).lower()
    if direction not in {"asc", "desc"}:
        raise ValueError("sort_direction must be 'asc' or 'desc'")

    model, columns = MODELS[report_type], _columns(report_type)
    catalog = {field["name"]: field for field in FIELD_CATALOG[report_type]}
    requested_fields = list(selected_fields or columns)
    invalid = [name for name in requested_fields if name not in catalog]
    if invalid:
        raise ValueError(f"Unsupported selected field(s): {', '.join(invalid)}")

    if report_type == "players_lineup_history":
        query = session.query(model).filter(
            DashboardPlayer.identity_resolution_status == "resolved",
            DashboardPlayer.lineup_appearance_count > 0,
        )
        default_sort = "most_recent_lineup_date"
        tie_column = DashboardPlayer.mlb_player_id
    elif report_type in {"hitters_arsenal_splits", "competitive_batter_arsenal"}:
        latest_matchup = (
            session.query(
                BatterPitchTypeMatchup.batter_id.label("batter_id"),
                BatterPitchTypeMatchup.opposing_pitcher_id.label("opposing_pitcher_id"),
                BatterPitchTypeMatchup.pitch_type.label("pitch_type"),
                BatterPitchTypeMatchup.target_date.label("target_date"),
                BatterPitchTypeMatchup.game_pk.label("game_pk"),
                func.max(BatterPitchTypeMatchup.id).label("matchup_id"),
            )
            .group_by(
                BatterPitchTypeMatchup.batter_id,
                BatterPitchTypeMatchup.opposing_pitcher_id,
                BatterPitchTypeMatchup.pitch_type,
                BatterPitchTypeMatchup.target_date,
                BatterPitchTypeMatchup.game_pk,
            )
            .subquery()
        )
        player_directory = (
            BATTER_DIRECTORY
            if report_type == "competitive_batter_arsenal"
            else DashboardPlayer
        )
        query = session.query(model).join(
            latest_matchup,
            BatterPitchTypeMatchup.id == latest_matchup.c.matchup_id,
        ).join(
            player_directory,
            player_directory.mlb_player_id == BatterPitchTypeMatchup.batter_id,
        ).filter(
            player_directory.is_active.is_(True),
            player_directory.identity_resolution_status == "resolved",
            player_directory.player_type == "hitter",
        )
        default_sort = "pitches_seen"
        tie_column = BatterPitchTypeMatchup.id
        if report_type == "competitive_batter_arsenal":
            query = query.outerjoin(
                OPPOSING_PITCHER_DIRECTORY,
                OPPOSING_PITCHER_DIRECTORY.mlb_player_id
                == BatterPitchTypeMatchup.opposing_pitcher_id,
            )
            arsenal_season = (as_of_date or dt.date.today()).year
            latest_arsenal = (
                session.query(
                    PitchArsenal.pitcher_id.label("pitcher_id"),
                    PitchArsenal.pitch_type.label("pitch_type"),
                    func.max(PitchArsenal.id).label("arsenal_id"),
                )
                .filter(PitchArsenal.season == arsenal_season)
                .group_by(PitchArsenal.pitcher_id, PitchArsenal.pitch_type)
                .subquery()
            )
            query = query.outerjoin(
                latest_arsenal,
                and_(
                    latest_arsenal.c.pitcher_id == BatterPitchTypeMatchup.opposing_pitcher_id,
                    latest_arsenal.c.pitch_type == BatterPitchTypeMatchup.pitch_type,
                ),
            ).outerjoin(PitchArsenal, PitchArsenal.id == latest_arsenal.c.arsenal_id)
        if as_of_date is not None:
            query = query.filter(
                or_(
                    BatterPitchTypeMatchup.target_date == as_of_date,
                    BatterPitchTypeMatchup.target_date.is_(None),
                )
            )
    else:
        query = session.query(model)
        default_sort = "snapshot_date"
        tie_column = ModelTrackerSnapshot.id
        if as_of_date is not None:
            query = query.filter(ModelTrackerSnapshot.snapshot_date == as_of_date)

    query, filter_logic, applied_filters = _apply_filters(query, report_type, filters)
    total_count = query.count()
    sort_name = str(sort_by or default_sort)
    field = catalog.get(sort_name)
    if not field or not field.get("sortable") or sort_name not in columns:
        raise ValueError(f"Unsupported sort field: {sort_name}")
    sort_column = columns[sort_name]
    query = query.order_by(
        case((sort_column.is_(None), 1), else_=0),
        sort_column.asc() if direction == "asc" else sort_column.desc(),
        tie_column.asc(),
    )
    offset = (page_number - 1) * page_size
    if report_type == "competitive_batter_arsenal":
        extra_names = [
            name for name in COLUMN_NAMES[report_type]
            if not hasattr(BatterPitchTypeMatchup, name)
        ]
        rows = (
            query.add_columns(*[columns[name].label(name) for name in extra_names])
            .offset(offset)
            .limit(page_size)
            .all()
        )
    else:
        extra_names = []
        rows = query.offset(offset).limit(page_size).all()
    records = []
    for index, result_row in enumerate(rows, start=offset + 1):
        if report_type == "competitive_batter_arsenal":
            row = result_row[0]
            extra_values = dict(zip(extra_names, result_row[1:]))
            record = {
                name: _iso(getattr(row, name)) if hasattr(row, name) else _iso(extra_values.get(name))
                for name in columns
            }
        else:
            row = result_row
            record = {name: _iso(getattr(row, name)) for name in columns}
        record["rank"] = index
        records.append(record)
    page_count = math.ceil(total_count / page_size) if total_count else 0
    has_next = offset + len(records) < total_count
    response = {
        "report_type": report_type,
        "component": REPORT_TYPES[report_type]["ui_object"],
        "records": records,
        "items": records,
        "totalSize": total_count,
        "total_count": total_count,
        "done": not has_next,
        "query_source": REPORT_TYPES[report_type]["base_object"],
        "filters_applied": applied_filters,
        "filter_logic": filter_logic,
        "query": {
            "source": REPORT_TYPES[report_type]["base_object"],
            "sort_by": sort_name,
            "sort_direction": direction,
            "selected_fields": requested_fields,
        },
        "page_info": {
            "page_number": page_number,
            "page_size": page_size,
            "page_count": page_count,
            "record_count": len(records),
            "total_count": total_count,
            "has_next": has_next,
            "has_previous": page_number > 1 and total_count > 0,
            "next_page": page_number + 1 if has_next else None,
            "previous_page": page_number - 1 if page_number > 1 and total_count > 0 else None,
        },
        "provenance": {
            "source_object": REPORT_TYPES[report_type]["base_object"],
            "relationship_path": REPORT_TYPES[report_type]["relationships"],
            "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        },
    }
    if include_metadata:
        response["object_info"] = describe_report_type(report_type)
    return response

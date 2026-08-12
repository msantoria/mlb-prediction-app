"""Validated SQL report queries over the canonical current-player projection."""

from __future__ import annotations

import datetime as dt
from typing import Any, Dict, Iterable, List, Optional, Tuple

from sqlalchemy import Float, and_, case, cast, func, or_
from sqlalchemy.orm import Session

from .dashboard_object_models import DashboardPlayerCurrent
from .dashboard_report_types import (
    FIELD_CATALOG,
    PLAYER_PROFILE_STATCAST_FIELD_DIRECTORY,
    REPORT_TYPES,
    describe_report_type,
)


DEFAULT_PAGE_SIZE = 50
MAX_PAGE_SIZE = 250

FIELD_COLUMNS = {
    name: getattr(DashboardPlayerCurrent, name)
    for name in (
        "mlb_player_id", "full_name", "player_type", "team_id", "team_name",
        "primary_position", "model_score", "confidence", "xwoba", "xba",
        "exit_velocity", "launch_angle", "hard_hit_rate", "barrel_rate",
        "strikeout_rate", "walk_rate", "iso", "obp", "slg",
        "plate_appearances", "projection_version", "promoted_at", "updated_at",
    )
}

JSON_METRIC_SOURCES = {
    name: tuple(definition["json_keys"])
    for name, definition in PLAYER_PROFILE_STATCAST_FIELD_DIRECTORY.items()
}


def _json_metric_expression(*keys: str):
    expressions = [
        cast(DashboardPlayerCurrent.metrics_json[key].as_string(), Float)
        for key in keys
    ]
    return func.coalesce(*expressions) if len(expressions) > 1 else expressions[0]


FIELD_EXPRESSIONS = {
    **FIELD_COLUMNS,
    **{
        name: _json_metric_expression(*keys)
        for name, keys in JSON_METRIC_SOURCES.items()
    },
}

METRIC_ALIASES = {
    "xwoba": "xwoba", "xwoba allowed": "xwoba", "xba": "xba",
    "xba allowed": "xba", "ev": "exit_velocity", "exit velocity": "exit_velocity",
    "la": "launch_angle", "launch angle": "launch_angle", "hardhit": "hard_hit_rate",
    "hardhit allowed": "hard_hit_rate", "barrel": "barrel_rate", "k%": "strikeout_rate",
    "bb%": "walk_rate", "iso": "iso", "obp": "obp", "slg": "slg",
    "pa": "plate_appearances", "pitches seen": "plate_appearances", "score": "model_score",
}


def _field_map(report_type: str) -> Dict[str, Dict[str, Any]]:
    return {field["name"]: field for field in FIELD_CATALOG[report_type]}


def _validate_report_type(report_type: str) -> Dict[str, Any]:
    if (
        report_type not in REPORT_TYPES
        or not REPORT_TYPES[report_type].get("queryable")
        or REPORT_TYPES[report_type].get("base_object") != "dashboard_player_current"
    ):
        raise ValueError(f"Unsupported queryable report type: {report_type}")
    return REPORT_TYPES[report_type]


def _filter_contract(filters: Any) -> Tuple[str, List[Dict[str, Any]]]:
    if filters is None:
        return "and", []
    if isinstance(filters, list):
        return "and", filters
    if not isinstance(filters, dict):
        raise ValueError("filters must be an object or a list of conditions")
    logic = str(filters.get("logic") or "and").strip().lower()
    if logic not in {"and", "or"}:
        raise ValueError("filters.logic must be 'and' or 'or'")
    result = list(filters.get("conditions") or [])
    if filters.get("search_text") not in (None, ""):
        result.append({"field": "full_name", "operator": "contains", "value": filters["search_text"]})
    if filters.get("team") not in (None, "", "All"):
        result.append({"field": "team_name", "operator": "eq", "value": filters["team"]})
    for key, field, operator in (
        ("team_id", "team_id", "eq"), ("min_score", "model_score", "gte"),
        ("max_score", "model_score", "lte"), ("min_confidence", "confidence", "gte"),
    ):
        if filters.get(key) is not None:
            result.append({"field": field, "operator": operator, "value": filters[key]})
    metrics = filters.get("metrics") or {}
    if not isinstance(metrics, dict):
        raise ValueError("filters.metrics must be an object")
    for raw_name, bounds in metrics.items():
        field = METRIC_ALIASES.get(str(raw_name).strip().lower())
        if not field:
            raise ValueError(f"Unsupported metric filter: {raw_name}")
        if not isinstance(bounds, dict):
            raise ValueError(f"Metric filter for {raw_name} must be an object")
        for key, operator in (("min", "gte"), ("max", "lte")):
            if bounds.get(key) is not None:
                result.append({"field": field, "operator": operator, "value": bounds[key]})
    return logic, result


def _confidence_expression():
    return case(
        (func.lower(DashboardPlayerCurrent.confidence) == "high", 3),
        (func.lower(DashboardPlayerCurrent.confidence) == "medium", 2),
        (func.lower(DashboardPlayerCurrent.confidence) == "low", 1),
        else_=0,
    )


def _coerce_scalar(field: Dict[str, Any], value: Any) -> Any:
    data_type = field.get("data_type")
    if data_type in {"id", "integer"}:
        try:
            return int(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Invalid integer value for field '{field['name']}'") from exc
    if data_type in {"double", "number", "float"}:
        try:
            return float(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Invalid numeric value for field '{field['name']}'") from exc
    if data_type == "datetime":
        if isinstance(value, dt.datetime):
            return value
        try:
            return dt.datetime.fromisoformat(str(value).replace("Z", "+00:00")).replace(tzinfo=None)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Invalid datetime value for field '{field['name']}'") from exc
    return str(value)


def _apply_filters(query, report_type: str, filters: Any) -> Tuple[Any, str, List[Dict[str, Any]]]:
    fields = _field_map(report_type)
    logic, applied = _filter_contract(filters)
    expressions = []
    for condition in applied:
        if not isinstance(condition, dict):
            raise ValueError("Each filter condition must be an object")
        field_name = str(condition.get("field") or "")
        operator = str(condition.get("operator") or "eq").lower()
        field = fields.get(field_name)
        if not field or not field.get("filterable") or field_name not in FIELD_EXPRESSIONS:
            raise ValueError(f"Unsupported filter field: {field_name}")
        if operator not in field["supported_operators"]:
            raise ValueError(f"Unsupported operator '{operator}' for field '{field_name}'")
        column = FIELD_EXPRESSIONS[field_name]
        value = condition.get("value")
        comparison = _confidence_expression() if field_name == "confidence" and operator in {"gt", "gte", "lt", "lte"} else column
        if comparison is not column:
            ordinal = {"low": 1, "medium": 2, "high": 3}
            try:
                value = ordinal[str(value).lower()]
            except KeyError as exc:
                raise ValueError("min_confidence must be low, medium, or high") from exc
        elif operator not in {"is_null", "is_not_null", "in"}:
            value = _coerce_scalar(field, value)
        if operator == "eq": expression = column == value
        elif operator == "neq": expression = column != value
        elif operator == "in":
            if not isinstance(value, (list, tuple, set)):
                raise ValueError(f"Operator 'in' for field '{field_name}' requires a list")
            expression = column.in_([_coerce_scalar(field, item) for item in value])
        elif operator == "contains": expression = func.lower(column).contains(str(value).lower())
        elif operator == "gt": expression = comparison > value
        elif operator == "gte": expression = comparison >= value
        elif operator == "lt": expression = comparison < value
        elif operator == "lte": expression = comparison <= value
        elif operator == "is_null": expression = column.is_(None)
        elif operator == "is_not_null": expression = column.is_not(None)
        else:  # guarded by field metadata
            raise ValueError(f"Unsupported operator: {operator}")
        expressions.append(expression)
    if expressions:
        query = query.filter(or_(*expressions) if logic == "or" else and_(*expressions))
    return query, logic, applied


def _normalize_weights(report_type: str, weights: Any) -> Tuple[Dict[str, float], Dict[str, str]]:
    if weights is None:
        return {}, {}
    if not isinstance(weights, dict):
        raise ValueError("weights must be an object")
    aliases: Dict[str, str] = {}
    for field in FIELD_CATALOG[report_type]:
        if field["name"] in FIELD_EXPRESSIONS and field.get("weight_aliases"):
            aliases[field["name"].lower()] = field["name"]
            for alias in field["weight_aliases"]:
                aliases[alias.lower()] = field["name"]
    normalized, labels = {}, {}
    for raw_name, raw_weight in weights.items():
        key = str(raw_name).strip().lower()
        if key not in aliases:
            raise ValueError(f"Unsupported weight metric: {raw_name}")
        try:
            weight = float(raw_weight)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Invalid weight for {raw_name}") from exc
        if weight < 0.0 or weight > 2.0:
            raise ValueError(f"Weight for {raw_name} must be between 0 and 2")
        if abs(weight - 1.0) >= 0.000001:
            normalized[aliases[key]] = weight
            labels[aliases[key]] = str(raw_name)
    return normalized, labels


def _clamp(expression):
    return case((expression < -1.0, -1.0), (expression > 1.0, 1.0), else_=expression)


def _normalized_metric(field_name: str, label: str):
    value = FIELD_EXPRESSIONS[field_name]
    name = label.lower()
    if "ev" in name or "velocity" in name: normalized = (value - 88.0) / 12.0
    elif "la" in name or "launch angle" in name: normalized = 1.0 - func.abs(value - 16.0) / 25.0
    elif "pitches seen" in name or name == "pa": normalized = value / 60.0
    elif "total" in name: normalized = (value - 8.5) / 4.0
    elif "score" in name or "edge" in name or "diff" in name: normalized = value
    elif "bb" in name: normalized = (0.085 - value) * 8.0
    elif "allowed" in name and ("xwoba" in name or "hardhit" in name): normalized = (0.34 - value) * 5.0
    else: normalized = value
    return case((value.is_(None), 0.0), else_=_clamp(normalized))


def _weighted_score(weights: Dict[str, float], labels: Dict[str, str]):
    score = func.coalesce(DashboardPlayerCurrent.model_score, 0.0)
    for field_name, weight in weights.items():
        score = score + _normalized_metric(field_name, labels[field_name]) * (weight - 1.0) * 0.25
    return score


def _iso(value: Any) -> Any:
    return value.isoformat() if isinstance(value, (dt.date, dt.datetime)) else value


def _record(row: DashboardPlayerCurrent, effective_score: float, rank: int, explanations: List[str]) -> Dict[str, Any]:
    values = {name: _iso(getattr(row, name)) for name in FIELD_COLUMNS}
    metrics = row.metrics_json or {}
    for name, keys in JSON_METRIC_SOURCES.items():
        values[name] = next(
            (metrics.get(key) for key in keys if metrics.get(key) is not None),
            None,
        )
    values.update({
        "metrics": metrics, "entity_id": str(row.mlb_player_id),
        "entity_name": row.full_name, "entity_type": row.player_type,
        "team": row.team_name, "base_score": row.model_score or 0.0,
        "adjusted_score": float(effective_score), "score": float(effective_score),
        "rank": rank, "weight_explanation": explanations,
    })
    return values


def query_player_report(
    session: Session,
    report_type: str,
    *,
    population_player_ids: Optional[Iterable[int]] = None,
    population_mode: str = "all_active",
    filters: Any = None,
    weights: Any = None,
    page_size: int = DEFAULT_PAGE_SIZE,
    page_number: int = 1,
    sort_by: str = "model_score",
    sort_direction: str = "desc",
    selected_fields: Optional[Iterable[str]] = None,
    include_metadata: bool = True,
) -> Dict[str, Any]:
    config = _validate_report_type(report_type)
    if not isinstance(page_size, int) or page_size < 1 or page_size > MAX_PAGE_SIZE:
        raise ValueError(f"page_size must be between 1 and {MAX_PAGE_SIZE}")
    if not isinstance(page_number, int) or page_number < 1:
        raise ValueError("page_number must be at least 1")
    direction = str(sort_direction).lower()
    if direction not in {"asc", "desc"}:
        raise ValueError("sort_direction must be 'asc' or 'desc'")

    field_map = _field_map(report_type)
    requested_fields = list(selected_fields or [
        field["name"] for field in FIELD_CATALOG[report_type] if field.get("selectable", True)
    ])
    invalid_fields = [
        name for name in requested_fields
        if name not in field_map or not field_map[name].get("selectable", True)
    ]
    if invalid_fields:
        raise ValueError(f"Unsupported selected field(s): {', '.join(invalid_fields)}")

    query = session.query(DashboardPlayerCurrent).filter(
        DashboardPlayerCurrent.is_active.is_(True),
        DashboardPlayerCurrent.player_type == config["population"]["player_type"],
    )
    normalized_population_ids: Optional[List[int]] = None
    if population_player_ids is not None:
        normalized_population_ids = sorted({
            int(value)
            for value in population_player_ids
            if value not in (None, "")
        })
        query = query.filter(
            DashboardPlayerCurrent.mlb_player_id.in_(normalized_population_ids)
            if normalized_population_ids
            else False
        )
    population_count = query.count()
    query, filter_logic, applied_filters = _apply_filters(query, report_type, filters)
    total_count = query.count()
    normalized_weights, weight_labels = _normalize_weights(report_type, weights)
    score_expression = _weighted_score(normalized_weights, weight_labels)

    sort_alias = "adjusted_score" if sort_by in {"score", "adjusted_score"} else sort_by
    if sort_alias == "adjusted_score": sort_expression = score_expression
    else:
        field = field_map.get(sort_alias)
        if not field or not field.get("sortable") or sort_alias not in FIELD_EXPRESSIONS:
            raise ValueError(f"Unsupported sort field: {sort_by}")
        sort_expression = FIELD_EXPRESSIONS[sort_alias]
    ordered = query.add_columns(score_expression.label("effective_score"))
    ordered = ordered.order_by(
        case((sort_expression.is_(None), 1), else_=0),
        sort_expression.asc() if direction == "asc" else sort_expression.desc(),
        DashboardPlayerCurrent.full_name.asc(), DashboardPlayerCurrent.mlb_player_id.asc(),
    )
    offset = (page_number - 1) * page_size
    rows = ordered.offset(offset).limit(page_size).all()
    explanations = [f"{weight_labels[name]} {'emphasized' if weight > 1 else 'deemphasized'} at {round(weight, 2)}" for name, weight in normalized_weights.items()]
    records = [_record(row, score, offset + index + 1, explanations) for index, (row, score) in enumerate(rows)]

    versions = [value for (value,) in query.with_entities(DashboardPlayerCurrent.projection_version).distinct().all()]
    promoted_at, updated_at = query.with_entities(func.max(DashboardPlayerCurrent.promoted_at), func.max(DashboardPlayerCurrent.updated_at)).one()
    freshness_row = query.order_by(
        DashboardPlayerCurrent.updated_at.desc(),
        DashboardPlayerCurrent.mlb_player_id.asc(),
    ).first()
    source_freshness = dict(freshness_row.source_freshness_json or {}) if freshness_row else {}
    response = {
        "report_type": report_type, "component": config["ui_object"], "records": records,
        "items": records, "totalSize": total_count, "total_count": total_count,
        "done": offset + len(records) >= total_count,
        "page_info": {"page_number": page_number, "page_size": page_size, "returned": len(records), "has_next_page": offset + len(records) < total_count},
        "query": {"source": "dashboard_player_current", "sort_by": sort_by, "sort_direction": direction, "selected_fields": requested_fields},
        "population": {
            "mode": population_mode,
            "candidate_id_count": len(normalized_population_ids) if normalized_population_ids is not None else None,
            "matched_current_count": population_count,
            "filtered_count": total_count,
        },
        "filters_applied": applied_filters, "filter_logic": filter_logic,
        "weights": normalized_weights,
        "weight_explanation": explanations, "query_source": "dashboard_player_current",
        "provenance": {
            "source_object": "dashboard_player_current",
            "projection_versions": sorted(versions),
            "snapshot_date": source_freshness.get("snapshot_date"),
            "source_freshness": source_freshness,
            "promoted_at": _iso(promoted_at),
            "updated_at": _iso(updated_at),
            "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        },
    }
    if include_metadata:
        response["object_info"] = describe_report_type(report_type)
    return response

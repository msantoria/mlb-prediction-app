"""Constrained MLBGPT Query Studio language and execution contract.

The authored statement is parsed into the existing structured report request. It is
never passed to SQLAlchemy or the database as SQL text.
"""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from .dashboard_player_report_query import query_player_report
from .dashboard_projection_report_query import query_projection_report
from .dashboard_related_report_query import query_related_report
from .dashboard_report_types import FIELD_CATALOG, REPORT_TYPES
from .my_dashboard_dataset_runtime import mlb_business_date
from .player_trends import query_player_trends


MAX_WORKBENCH_ROWS = 250
RELATED_REPORT_TYPES = frozenset({
    "players_lineup_history",
    "hitters_arsenal_splits",
    "competitive_batter_arsenal",
})
PROJECTION_REPORT_TYPES = frozenset({
    "model_projection_games",
    "model_projection_players",
})

_STATEMENT = re.compile(
    r"^\s*SELECT\s+(?P<fields>.+?)\s+FROM\s+(?P<object>[A-Za-z_][A-Za-z0-9_]*)"
    r"(?:\s+WHERE\s+(?P<where>.+?))?"
    r"(?:\s+ORDER\s+BY\s+(?P<sort>[A-Za-z_][A-Za-z0-9_]*)(?:\s+(?P<direction>ASC|DESC))?)?"
    r"\s+LIMIT\s+(?P<limit>[0-9]+)\s*$",
    re.IGNORECASE | re.DOTALL,
)
_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_CONDITION = re.compile(
    r"^(?P<field>[A-Za-z_][A-Za-z0-9_]*)\s*"
    r"(?P<operator>IS\s+NOT\s+NULL|IS\s+NULL|CONTAINS|>=|<=|!=|<>|=|>|<)"
    r"(?:\s*(?P<value>.+))?$",
    re.IGNORECASE | re.DOTALL,
)
_FORBIDDEN = re.compile(
    r"\b(INSERT|UPDATE|DELETE|UPSERT|MERGE|CREATE|ALTER|DROP|TRUNCATE|GRANT|REVOKE|"
    r"JOIN|UNION|WITH|GROUP\s+BY|HAVING|OFFSET|OR)\b",
    re.IGNORECASE,
)

_OPERATOR_MAP = {
    "=": "eq",
    "!=": "neq",
    "<>": "neq",
    ">": "gt",
    ">=": "gte",
    "<": "lt",
    "<=": "lte",
    "contains": "contains",
    "is null": "is_null",
    "is not null": "is_not_null",
}


@dataclass(frozen=True)
class WorkbenchPlan:
    logical_object: str
    selected_fields: List[str]
    filters: List[Dict[str, Any]]
    sort_by: Optional[str]
    sort_direction: str
    page_size: int

    def as_dict(self, *, page_number: int = 1) -> Dict[str, Any]:
        return {
            "language": "mlbgpt_query_v1",
            "operation": "select",
            "logical_object": self.logical_object,
            "selected_fields": list(self.selected_fields),
            "filters": [dict(item) for item in self.filters],
            "filter_logic": "and",
            "sort": {
                "field": self.sort_by,
                "direction": self.sort_direction,
            },
            "pagination": {
                "page_number": page_number,
                "page_size": self.page_size,
                "maximum_page_size": MAX_WORKBENCH_ROWS,
            },
            "execution_boundary": "structured_report_service",
            "authored_sql_executed": False,
        }


def _field_map(report_type: str) -> Dict[str, Dict[str, Any]]:
    return {field["name"]: field for field in FIELD_CATALOG[report_type]}


def queryable_objects() -> List[Dict[str, Any]]:
    """Return logical metadata without physical schema or source expressions."""

    objects: List[Dict[str, Any]] = []
    for api_name, definition in REPORT_TYPES.items():
        if not definition.get("queryable") or definition.get("workbench_queryable") is False:
            continue
        fields = []
        for field in FIELD_CATALOG[api_name]:
            if field["name"] == "metrics" or not field.get("selectable", True):
                continue
            fields.append({
                "name": field["name"],
                "label": field["label"],
                "data_type": field["data_type"],
                "group": field["group"],
                "filterable": bool(field.get("filterable")),
                "sortable": bool(field.get("sortable")),
                "selectable": True,
                "operators": list(field.get("supported_operators") or []),
                "freshness": field.get("freshness"),
            })
        objects.append({
            "api_name": api_name,
            "label": definition["label"],
            "ui_object": definition["ui_object"],
            "fields": fields,
        })
    return objects


def _split_and(value: str) -> List[str]:
    parts, start, quote = [], 0, None
    index = 0
    while index < len(value):
        character = value[index]
        if quote:
            if character == quote:
                if index + 1 < len(value) and value[index + 1] == quote:
                    index += 2
                    continue
                quote = None
            index += 1
            continue
        if character in {"'", '"'}:
            quote = character
            index += 1
            continue
        match = re.match(r"\s+AND\s+", value[index:], re.IGNORECASE)
        if match:
            parts.append(value[start:index].strip())
            index += match.end()
            start = index
            continue
        index += 1
    if quote:
        raise ValueError("Unterminated string literal")
    parts.append(value[start:].strip())
    return [part for part in parts if part]


def _literal(raw: str, field: Dict[str, Any]) -> Any:
    value = str(raw or "").strip()
    if not value:
        raise ValueError(f"A value is required for field '{field['name']}'")
    if value[0:1] in {"'", '"'}:
        quote = value[0]
        if len(value) < 2 or value[-1] != quote:
            raise ValueError("Unterminated string literal")
        value = value[1:-1].replace(quote * 2, quote)
    elif re.search(r"\s", value):
        raise ValueError("Text values containing spaces must be quoted")

    data_type = field["data_type"]
    try:
        if data_type in {"integer", "id"}:
            return int(value)
        if data_type in {"double", "number", "float"}:
            return float(value)
        if data_type == "boolean":
            if value.lower() not in {"true", "false"}:
                raise ValueError
            return value.lower() == "true"
        if data_type == "date":
            return dt.date.fromisoformat(value).isoformat()
        if data_type == "datetime":
            return dt.datetime.fromisoformat(value.replace("Z", "+00:00")).isoformat()
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Invalid {data_type} value for field '{field['name']}'") from exc
    return value


def parse_workbench_statement(statement: str) -> WorkbenchPlan:
    source = str(statement or "").strip()
    if not source:
        raise ValueError("Enter a Query Studio statement")
    if ";" in source:
        raise ValueError("Multiple statements and semicolons are not supported")
    if "--" in source or "/*" in source or "*/" in source or "#" in source:
        raise ValueError("Comments are not supported")
    forbidden = _FORBIDDEN.search(source)
    if forbidden:
        raise ValueError(f"Unsupported Query Studio keyword: {forbidden.group(0).upper()}")

    match = _STATEMENT.fullmatch(source)
    if not match:
        raise ValueError("Use SELECT fields FROM logical_object [WHERE ...] [ORDER BY ...] LIMIT 1-250")

    logical_object = match.group("object").lower()
    definition = REPORT_TYPES.get(logical_object)
    if (
        not definition
        or not definition.get("queryable")
        or definition.get("workbench_queryable") is False
    ):
        raise ValueError(f"Unsupported queryable logical object: {logical_object}")
    fields = _field_map(logical_object)

    selected_fields = [item.strip() for item in match.group("fields").split(",")]
    if not selected_fields or any(not _IDENTIFIER.fullmatch(item) for item in selected_fields):
        raise ValueError("SELECT accepts registered field names only; wildcards and expressions are not supported")
    duplicates = {name for name in selected_fields if selected_fields.count(name) > 1}
    if duplicates:
        raise ValueError(f"Duplicate selected field: {sorted(duplicates)[0]}")
    unknown = [name for name in selected_fields if name not in fields or name == "metrics"]
    if unknown:
        raise ValueError(f"Unsupported selected field: {unknown[0]}")

    filters: List[Dict[str, Any]] = []
    for raw_condition in _split_and(match.group("where") or ""):
        condition = _CONDITION.fullmatch(raw_condition)
        if not condition:
            raise ValueError(f"Unsupported WHERE condition: {raw_condition}")
        field_name = condition.group("field")
        field = fields.get(field_name)
        if not field or not field.get("filterable") or field_name == "metrics":
            raise ValueError(f"Unsupported filter field: {field_name}")
        raw_operator = re.sub(r"\s+", " ", condition.group("operator").lower())
        operator = _OPERATOR_MAP[raw_operator]
        if operator not in field.get("supported_operators", []):
            raise ValueError(f"Unsupported operator '{raw_operator}' for field '{field_name}'")
        entry: Dict[str, Any] = {"field": field_name, "operator": operator}
        if operator not in {"is_null", "is_not_null"}:
            entry["value"] = _literal(condition.group("value"), field)
        elif condition.group("value") not in (None, ""):
            raise ValueError(f"Operator '{raw_operator}' does not accept a value")
        filters.append(entry)

    sort_by = match.group("sort")
    if sort_by:
        sort_field = fields.get(sort_by)
        if not sort_field or not sort_field.get("sortable") or sort_by == "metrics":
            raise ValueError(f"Unsupported sort field: {sort_by}")
    elif "model_score" in fields:
        sort_by = "model_score"
    else:
        sort_by = next((name for name, field in fields.items() if field.get("sortable") and name != "metrics"), None)

    page_size = int(match.group("limit"))
    if page_size < 1 or page_size > MAX_WORKBENCH_ROWS:
        raise ValueError(f"LIMIT must be between 1 and {MAX_WORKBENCH_ROWS}")

    return WorkbenchPlan(
        logical_object=logical_object,
        selected_fields=selected_fields,
        filters=filters,
        sort_by=sort_by,
        sort_direction=(match.group("direction") or "DESC").lower(),
        page_size=page_size,
    )


def execute_workbench_plan(session: Any, plan: WorkbenchPlan, *, page_number: int = 1) -> Dict[str, Any]:
    if not isinstance(page_number, int) or page_number < 1:
        raise ValueError("page_number must be at least 1")
    options = {
        "filters": plan.filters,
        "page_size": plan.page_size,
        "page_number": page_number,
        "sort_by": plan.sort_by,
        "sort_direction": plan.sort_direction,
        "selected_fields": plan.selected_fields,
        "include_metadata": True,
    }
    if plan.logical_object == "player_trends":
        config_values: Dict[str, Any] = {}
        for field_name in (
            "player_type",
            "selected_window_days",
            "comparison_baseline",
            "metric",
            "freshness_date",
        ):
            matches = [
                condition for condition in plan.filters
                if condition["field"] == field_name and condition["operator"] == "eq"
            ]
            if len(matches) > 1 and len({str(item.get("value")) for item in matches}) > 1:
                raise ValueError(f"Conflicting Player Trends configuration for '{field_name}'")
            if matches:
                config_values[field_name] = matches[0].get("value")
        missing = [
            field_name for field_name in ("player_type", "selected_window_days", "metric")
            if field_name not in config_values
        ]
        if missing:
            raise ValueError(
                "Player Trends Query Studio requires equality filters for "
                "player_type, selected_window_days, and metric"
            )
        as_of_date = dt.date.fromisoformat(
            str(config_values.get("freshness_date") or mlb_business_date())[:10]
        )
        result = query_player_trends(
            session,
            as_of_date=as_of_date,
            trend_config={
                "player_type": config_values["player_type"],
                "window_days": config_values["selected_window_days"],
                "comparison_baseline": config_values.get("comparison_baseline") or "previous_n_days",
                "minimum_sample_size": 1,
                "trend_direction": "all",
                "selected_metrics": [config_values["metric"]],
            },
            **options,
        )
    elif plan.logical_object in PROJECTION_REPORT_TYPES:
        dates = [
            condition.get("value") for condition in plan.filters
            if condition["field"] == "game_date" and condition["operator"] == "eq"
        ]
        if len({str(value) for value in dates}) > 1:
            raise ValueError("Conflicting game_date filters for Model Projections")
        result = query_projection_report(
            plan.logical_object,
            date=str(dates[0] if dates else mlb_business_date()),
            **options,
        )
    elif plan.logical_object in RELATED_REPORT_TYPES:
        result = query_related_report(session, plan.logical_object, **options)
    else:
        result = query_player_report(session, plan.logical_object, **options)
    result["workbench_plan"] = plan.as_dict(page_number=page_number)
    return result

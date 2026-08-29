"""Streaming CSV helpers for paginated MyDashboard report results."""

from __future__ import annotations

import csv
import io
import json
from typing import Any, Callable, Dict, Iterable, List, Optional


def result_rows(result: Dict[str, Any]) -> List[Dict[str, Any]]:
    records = result.get("records")
    if isinstance(records, list) and (records or not isinstance(result.get("items"), list)):
        return [row for row in records if isinstance(row, dict)]
    items = result.get("items")
    return [row for row in items if isinstance(row, dict)] if isinstance(items, list) else []


def value_at_path(row: Dict[str, Any], accessor: str) -> Any:
    value: Any = row
    for key in str(accessor).split("."):
        if not isinstance(value, dict):
            return None
        value = value.get(key)
    return value


def csv_value(value: Any) -> Any:
    if value is None:
        return ""
    if isinstance(value, (dict, list, tuple)):
        return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    return value


def report_columns(
    result: Dict[str, Any],
    selected_fields: Optional[Iterable[str]] = None,
) -> List[Dict[str, str]]:
    described = result.get("object_info", {}).get("fields", [])
    field_map = {
        str(field.get("name")): field
        for field in described
        if isinstance(field, dict) and field.get("name")
    }
    selected = [str(value) for value in selected_fields or [] if str(value)]
    if selected:
        names = list(dict.fromkeys(selected))
    elif field_map:
        names = [
            name for name, field in field_map.items()
            if field.get("selectable", True) is not False
        ]
    else:
        names = list(dict.fromkeys(
            key
            for row in result_rows(result)
            for key in row.keys()
        ))
    return [
        {
            "name": name,
            "label": str(field_map.get(name, {}).get("label") or name),
        }
        for name in names
    ]


def _csv_line(values: Iterable[Any]) -> str:
    output = io.StringIO(newline="")
    csv.writer(output, lineterminator="\r\n").writerow(list(values))
    return output.getvalue()


def _has_next_page(result: Dict[str, Any], emitted_count: int) -> bool:
    page_info = result.get("page_info") or {}
    explicit = page_info.get("has_next")
    if explicit is None:
        explicit = page_info.get("has_next_page")
    if explicit is not None:
        return bool(explicit)
    total_value = result.get("totalSize", result.get("total_size"))
    try:
        return emitted_count < int(total_value)
    except (TypeError, ValueError):
        return False


def stream_paginated_csv(
    first_result: Dict[str, Any],
    fetch_page: Callable[[int], Dict[str, Any]],
    *,
    selected_fields: Optional[Iterable[str]] = None,
    max_pages: int = 10000,
) -> Iterable[str]:
    """Yield one CSV response while fetching subsequent report pages server-side."""

    columns = report_columns(first_result, selected_fields)
    if not columns:
        raise ValueError("CSV export has no selectable report columns")

    yield _csv_line(column["label"] for column in columns)

    result = first_result
    page_number = 1
    emitted_count = 0
    visited_pages = set()
    while page_number <= max_pages:
        if page_number in visited_pages:
            raise RuntimeError("CSV export received a repeated page number")
        visited_pages.add(page_number)

        rows = result_rows(result)
        for row in rows:
            yield _csv_line(
                csv_value(value_at_path(row, column["name"]))
                for column in columns
            )
        emitted_count += len(rows)

        if not _has_next_page(result, emitted_count):
            return
        if not rows:
            raise RuntimeError("CSV export stopped before every matching row was returned")

        page_info = result.get("page_info") or {}
        try:
            next_page = int(page_info.get("next_page"))
        except (TypeError, ValueError):
            next_page = page_number + 1
        if next_page <= page_number:
            next_page = page_number + 1
        page_number = next_page
        result = fetch_page(page_number)

    raise RuntimeError(f"CSV export exceeded the {max_pages}-page safety limit")


def safe_csv_filename(value: Any) -> str:
    cleaned = "".join(
        character if character.isalnum() or character in {"-", "_"} else "-"
        for character in str(value or "report").strip().lower()
    )
    cleaned = "-".join(part for part in cleaned.split("-") if part)
    return cleaned or "report"

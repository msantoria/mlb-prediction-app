from __future__ import annotations

import datetime as dt
import os
from dataclasses import replace
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field

from . import my_dashboard_solver as dashboard_solver
from .active_lineup_solver import build_active_lineup_solver_payload, build_confirmed_lineup_index
from .admin_access import DashboardPrincipal, require_capability
from .admin_configuration import profile_key_for_role
from .dashboard_canonical_status import canonical_dashboard_status
from .dashboard_player_report_query import query_player_report
from .dashboard_projection_report_query import query_projection_report
from .dashboard_related_report_query import query_related_report
from .dashboard_report_types import list_report_types
from .database import AppFeatureFlag, create_tables, get_engine, get_session
from .my_dashboard_context_cache import install_dashboard_context_cache
from .my_dashboard_dataset_runtime import mlb_business_date, run_dataset_query, should_use_dataset_query
from .my_dashboard_observability import (
    begin_hydration,
    complete_hydration,
    cron_configuration,
    fail_hydration,
    latest_hydration_status,
)
from .my_dashboard_report_query import (
    DEFAULT_PAGE_SIZE,
    MAX_PAGE_SIZE,
    apply_report_query,
    install_full_result_finalizer,
)
from .player_trends import query_player_trends, supported_trend_configuration
from .report_csv import safe_csv_filename, stream_paginated_csv
from .shared_payload_cache import env_ttl, get_or_set, make_cache_key, stable_hash
from .workbench_query import execute_workbench_plan, parse_workbench_statement, queryable_objects

install_full_result_finalizer(dashboard_solver)

router = APIRouter()
SUPPORTED_COMPONENTS = dashboard_solver.SUPPORTED_COMPONENTS


class MyDashboardSolverRequest(BaseModel):
    date: Optional[str] = None
    component: str
    filters: Optional[Dict[str, Any]] = None
    page_size: int = DEFAULT_PAGE_SIZE
    page_number: int = 1
    sort_by: str = "score"
    sort_direction: str = "desc"
    include_metadata: bool = True


class MyDashboardBatchSolverRequest(BaseModel):
    date: Optional[str] = None
    components: Optional[List[str]] = None
    filters_by_component: Optional[Dict[str, Dict[str, Any]]] = None
    active_lineups: bool = False


class MyDashboardHydrateRequest(BaseModel):
    date: Optional[str] = None
    components: Optional[List[str]] = None
    active_lineups: bool = True
    force: bool = False


class DashboardPlayerReportRequest(BaseModel):
    report_type: str
    as_of_date: Optional[dt.date] = None
    filters: Optional[Any] = None
    weights: Optional[Dict[str, float]] = None
    page_size: int = DEFAULT_PAGE_SIZE
    page_number: int = 1
    sort_by: str = "model_score"
    sort_direction: str = "desc"
    selected_fields: Optional[List[str]] = None
    include_metadata: bool = True
    confirmed_lineups_only: bool = False
    trend_config: Optional[Dict[str, Any]] = None


class QueryStudioRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    statement: str = Field(min_length=1, max_length=8000)
    page_number: int = Field(default=1, ge=1)


def session_factory():
    database_url = os.getenv("DATABASE_URL", "sqlite:///mlb.db")
    engine = get_engine(database_url)
    create_tables(engine)
    return get_session(engine)


def _yesterday_iso() -> str:
    return (mlb_business_date() - dt.timedelta(days=1)).isoformat()


@router.get("/my-dashboard/health")
def my_dashboard_health() -> Dict[str, Any]:
    return {
        "name": "My Dashboard",
        "status": "ok",
        "auth_required": False,
        "persistence": "frontend_localStorage_v1",
        "supported_components": sorted(SUPPORTED_COMPONENTS),
        "query_contract": {
            "style": "mlbgpt_report_query_and_describe",
            "default_page_size": DEFAULT_PAGE_SIZE,
            "maximum_page_size": MAX_PAGE_SIZE,
            "full_candidate_universe": True,
            "final_top_ten_cap": False,
            "fields": ["totalSize", "done", "records", "page_info", "object_info"],
            "filtered_current_date_source": "my_dashboard_records",
        },
        "lineup_policy": {
            "today_confirmed_preferred": True,
            "partial_lineups_are_explicit": True,
            "unavailable_lineups_return_zero_verified_hitters": True,
            "yesterday_hydration_is_cache_warming_not_today_fallback": True,
        },
        "hydration": {
            **cron_configuration(),
            "latest": latest_hydration_status(),
        },
    }


@router.get("/my-dashboard/hydration/status")
def my_dashboard_hydration_status() -> Dict[str, Any]:
    return {
        "configuration": cron_configuration(),
        "latest": latest_hydration_status(),
    }


@router.get("/my-dashboard/report-types")
def my_dashboard_report_types() -> Dict[str, Any]:
    report_types = list_report_types()
    for report_type in report_types:
        if report_type.get("api_name") == "player_trends":
            report_type["trend_configuration"] = supported_trend_configuration()
    return {"report_types": report_types, "totalSize": len(report_types)}


def _require_query_studio_enabled(session, principal: DashboardPrincipal) -> None:
    flag = (
        session.query(AppFeatureFlag)
        .filter(AppFeatureFlag.flag_key == "workbench_query_enabled")
        .first()
    )
    profile_key = profile_key_for_role(principal.role)
    targets = set(flag.target_profiles_json or []) if flag else set()
    if not flag or not flag.enabled or (targets and profile_key not in targets):
        raise HTTPException(
            status_code=403,
            detail="Query Studio is locked until the owner enables it for this profile.",
        )


@router.get("/my-dashboard/query-studio/metadata")
def my_dashboard_query_studio_metadata(
    principal: DashboardPrincipal = Depends(require_capability("workbench.advanced")),
) -> Dict[str, Any]:
    factory = session_factory()
    with factory() as session:
        _require_query_studio_enabled(session, principal)
    objects = queryable_objects()
    return {
        "language": "mlbgpt_query_v1",
        "enabled": True,
        "objects": objects,
        "totalSize": len(objects),
        "maximum_page_size": MAX_PAGE_SIZE,
        "authored_sql_executed": False,
    }


@router.post("/my-dashboard/query-studio/preview")
def my_dashboard_query_studio_preview(
    request: QueryStudioRequest,
    principal: DashboardPrincipal = Depends(require_capability("workbench.advanced")),
) -> Dict[str, Any]:
    factory = session_factory()
    with factory() as session:
        _require_query_studio_enabled(session, principal)
    try:
        plan = parse_workbench_statement(request.statement)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        "ok": True,
        "plan": plan.as_dict(page_number=request.page_number),
        "authored_sql_executed": False,
    }


@router.post("/my-dashboard/query-studio/execute")
def my_dashboard_query_studio_execute(
    request: QueryStudioRequest,
    principal: DashboardPrincipal = Depends(require_capability("workbench.execute")),
) -> Dict[str, Any]:
    if not principal.has_capability("workbench.advanced"):
        raise HTTPException(status_code=403, detail="Advanced Query Studio access required")
    try:
        plan = parse_workbench_statement(request.statement)
        factory = session_factory()
        with factory() as session:
            _require_query_studio_enabled(session, principal)
            return execute_workbench_plan(session, plan, page_number=request.page_number)
    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/my-dashboard/query-studio/export.csv")
def my_dashboard_query_studio_export(
    request: QueryStudioRequest,
    principal: DashboardPrincipal = Depends(require_capability("dashboard.export")),
) -> StreamingResponse:
    if not principal.has_capability("workbench.advanced"):
        raise HTTPException(status_code=403, detail="Advanced Query Studio access required")
    try:
        plan = replace(parse_workbench_statement(request.statement), page_size=MAX_PAGE_SIZE)
        factory = session_factory()

        def fetch_page(page_number: int) -> Dict[str, Any]:
            with factory() as session:
                _require_query_studio_enabled(session, principal)
                return execute_workbench_plan(session, plan, page_number=page_number)

        first_result = fetch_page(1)
        filename = f"{safe_csv_filename(plan.logical_object)}-all-rows.csv"
        return StreamingResponse(
            stream_paginated_csv(
                first_result,
                fetch_page,
                selected_fields=plan.selected_fields,
            ),
            media_type="text/csv; charset=utf-8",
            headers={
                "Cache-Control": "no-store",
                "Content-Disposition": f'attachment; filename="{filename}"',
                "X-Report-Row-Count": str(first_result.get("totalSize") or 0),
            },
        )
    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/my-dashboard/canonical/status")
def my_dashboard_canonical_status() -> Dict[str, Any]:
    factory = session_factory()
    with factory() as session:
        return canonical_dashboard_status(session)


@router.post("/my-dashboard/reports/query")
def my_dashboard_player_report_query(payload: DashboardPlayerReportRequest) -> Dict[str, Any]:
    try:
        factory = session_factory()
        with factory() as session:
            if payload.report_type == "player_trends":
                return query_player_trends(
                    session,
                    as_of_date=payload.as_of_date or mlb_business_date(),
                    trend_config=payload.trend_config or {},
                    filters=payload.filters,
                    page_size=payload.page_size,
                    page_number=payload.page_number,
                    sort_by="absolute_change" if payload.sort_by == "model_score" else payload.sort_by,
                    sort_direction=payload.sort_direction,
                    selected_fields=payload.selected_fields,
                    include_metadata=payload.include_metadata,
                )
            if payload.report_type in {
                "players_lineup_history",
                "hitters_arsenal_splits",
                "competitive_batter_arsenal",
                "model_tracker_snapshots",
            }:
                return query_related_report(
                    session, payload.report_type, filters=payload.filters, weights=payload.weights,
                    page_size=payload.page_size, page_number=payload.page_number,
                    sort_by=None if payload.sort_by == "model_score" else payload.sort_by,
                    sort_direction=payload.sort_direction,
                    selected_fields=payload.selected_fields, include_metadata=payload.include_metadata,
                    as_of_date=payload.as_of_date,
                )
            if payload.report_type in {"model_projection_games", "model_projection_players"}:
                return query_projection_report(
                    payload.report_type,
                    date=(payload.as_of_date or mlb_business_date()).isoformat(),
                    filters=payload.filters,
                    weights=payload.weights,
                    page_size=payload.page_size,
                    page_number=payload.page_number,
                    sort_by=None if payload.sort_by == "model_score" else payload.sort_by,
                    sort_direction=payload.sort_direction,
                    selected_fields=payload.selected_fields,
                    include_metadata=payload.include_metadata,
                )
            dataset_reports = {
                "teams_daily_analysis": "teams",
                "games_totals_analysis": "totals",
                "overall_players_daily_analysis": "overall_players",
            }
            if payload.report_type in dataset_reports:
                target_date = (payload.as_of_date or mlb_business_date()).isoformat()
                filters = payload.filters
                if isinstance(filters, list):
                    filters = {"logic": "and", "conditions": filters}
                filters = dict(filters or {})
                if payload.weights:
                    filters["weights"] = dict(payload.weights)
                component = dataset_reports[payload.report_type]
                active_lineups = bool(
                    payload.confirmed_lineups_only
                    and payload.report_type == "overall_players_daily_analysis"
                )
                if active_lineups:
                    payload_builder = lambda: build_active_lineup_solver_payload(
                        session=session,
                        date=target_date,
                        component=component,
                        filters={},
                    )
                else:
                    payload_builder = lambda: dashboard_solver.build_dashboard_solver_payload(
                        session=session,
                        date=target_date,
                        component=component,
                        filters={},
                    )
                return run_dataset_query(
                    session=session,
                    date=target_date,
                    component=component,
                    filters=filters,
                    page_size=payload.page_size,
                    page_number=payload.page_number,
                    sort_by="score" if payload.sort_by == "model_score" else payload.sort_by,
                    sort_direction=payload.sort_direction,
                    include_metadata=payload.include_metadata,
                    payload_builder=payload_builder,
                    active_lineups=active_lineups,
                    report_type=payload.report_type,
                    selected_fields=payload.selected_fields,
                )
            lineup_index = None
            population_player_ids = None
            population_mode = "all_active"
            if payload.confirmed_lineups_only:
                if payload.report_type != "all_active_hitters":
                    raise ValueError("Confirmed 1–9 is supported only for the active hitters report")
                target_date = payload.as_of_date or mlb_business_date()
                lineup_index = build_confirmed_lineup_index(session, target_date.isoformat())
                population_player_ids = {
                    int(value)
                    for value in lineup_index.get("confirmed_ids") or set()
                    if str(value).isdigit()
                }
                population_mode = "confirmed_lineup"
            result = query_player_report(
                session, payload.report_type, filters=payload.filters, weights=payload.weights,
                page_size=payload.page_size, page_number=payload.page_number,
                sort_by=payload.sort_by, sort_direction=payload.sort_direction,
                selected_fields=payload.selected_fields, include_metadata=payload.include_metadata,
                population_player_ids=population_player_ids, population_mode=population_mode,
            )
            result["population_bootstrap"] = {
                "status": "not_run",
                "reason": "report_requests_are_read_only",
            }
            current_population = int(
                (result.get("population") or {}).get("matched_current_count") or 0
            )
            result["data_status"] = "ready" if current_population else "not_ready"
            result["refreshing"] = False
            result["stale"] = False
            if result["data_status"] == "not_ready":
                result["message"] = (
                    "No current canonical player snapshot is available. "
                    "The scheduled canonical refresh must populate this report."
                )
            if lineup_index is not None:
                lineup_metadata = dict(lineup_index.get("metadata") or {})
                lineup_metadata["matched_current_count"] = result["population"]["matched_current_count"]
                lineup_metadata["unmatched_confirmed_count"] = max(
                    0,
                    int(result["population"]["candidate_id_count"] or 0)
                    - int(result["population"]["matched_current_count"]),
                )
                lineup_metadata["filtered_out_count"] = max(
                    0,
                    int(result["population"]["matched_current_count"])
                    - int(result["population"]["filtered_count"]),
                )
                lineup_metadata["removed_unconfirmed_count"] = 0
                result["lineup_filter"] = lineup_metadata
                result["model_state"] = lineup_metadata.get("model_state")
                result["lineup_revision"] = lineup_metadata.get("lineup_revision")
                for record in result.get("records") or []:
                    record.update({
                        "lineup_verified": True,
                        "lineup_source": lineup_metadata.get("source"),
                        "confirmed_lineup_date": lineup_metadata.get("confirmed_lineup_date"),
                        "lineup_revision": lineup_metadata.get("lineup_revision"),
                    })
            return result
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/my-dashboard/reports/export.csv")
def my_dashboard_report_export(
    payload: DashboardPlayerReportRequest,
    _principal: DashboardPrincipal = Depends(require_capability("dashboard.export")),
) -> StreamingResponse:
    """Stream every matching report row without browser-side page collection."""

    export_payload = payload.model_copy(update={
        "page_number": 1,
        "page_size": MAX_PAGE_SIZE,
        "include_metadata": True,
    })
    first_result = my_dashboard_player_report_query(export_payload)

    def fetch_page(page_number: int) -> Dict[str, Any]:
        return my_dashboard_player_report_query(
            export_payload.model_copy(update={"page_number": page_number})
        )

    date_part = (payload.as_of_date or mlb_business_date()).isoformat()
    filename = f"{safe_csv_filename(payload.report_type)}-{date_part}-all-rows.csv"
    return StreamingResponse(
        stream_paginated_csv(
            first_result,
            fetch_page,
            selected_fields=payload.selected_fields,
        ),
        media_type="text/csv; charset=utf-8",
        headers={
            "Cache-Control": "no-store",
            "Content-Disposition": f'attachment; filename="{filename}"',
            "X-Report-Row-Count": str(first_result.get("totalSize") or 0),
        },
    )


@router.get("/my-dashboard/solver")
def my_dashboard_solver_get(
    date: Optional[str] = Query(default=None),
    component: str = Query(default="hitters"),
    page_size: int = Query(default=DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    page_number: int = Query(default=1, ge=1),
    sort_by: str = Query(default="score"),
    sort_direction: str = Query(default="desc"),
    include_metadata: bool = Query(default=True),
) -> Dict[str, Any]:
    return _run_solver(
        date=date,
        component=component,
        filters=None,
        page_size=page_size,
        page_number=page_number,
        sort_by=sort_by,
        sort_direction=sort_direction,
        include_metadata=include_metadata,
    )


@router.post("/my-dashboard/solver")
def my_dashboard_solver_post(payload: MyDashboardSolverRequest) -> Dict[str, Any]:
    return _run_solver(
        date=payload.date,
        component=payload.component,
        filters=payload.filters,
        page_size=payload.page_size,
        page_number=payload.page_number,
        sort_by=payload.sort_by,
        sort_direction=payload.sort_direction,
        include_metadata=payload.include_metadata,
    )


@router.post("/my-dashboard/solver/batch")
def my_dashboard_solver_batch_post(payload: MyDashboardBatchSolverRequest) -> Dict[str, Any]:
    return _run_batch_solver(
        date=payload.date,
        components=payload.components,
        filters_by_component=payload.filters_by_component,
        active_lineups=payload.active_lineups,
    )


@router.post("/my-dashboard/solver/active-lineups")
def my_dashboard_active_lineup_solver_post(payload: MyDashboardSolverRequest) -> Dict[str, Any]:
    return _run_active_lineup_solver(
        date=payload.date,
        component=payload.component,
        filters=payload.filters,
        page_size=payload.page_size,
        page_number=payload.page_number,
        sort_by=payload.sort_by,
        sort_direction=payload.sort_direction,
        include_metadata=payload.include_metadata,
    )


@router.post("/my-dashboard/solver/hydrate-yesterday")
def my_dashboard_hydrate_yesterday_post(payload: Optional[MyDashboardHydrateRequest] = None) -> Dict[str, Any]:
    request = payload or MyDashboardHydrateRequest()
    target_date = request.date or _yesterday_iso()
    return _run_hydration(
        date=target_date,
        components=request.components,
        active_lineups=request.active_lineups,
        force=request.force,
    )


@router.get("/my-dashboard/solver/hydrate-yesterday")
def my_dashboard_hydrate_yesterday_get(
    date: Optional[str] = Query(default=None),
    active_lineups: bool = Query(default=True),
    force: bool = Query(default=False),
) -> Dict[str, Any]:
    return _run_hydration(
        date=date or _yesterday_iso(),
        components=None,
        active_lineups=active_lineups,
        force=force,
    )


def _normalize_request(date: Optional[str], component: str, filters: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    target_date = (date or mlb_business_date().isoformat())[:10]
    try:
        dt.date.fromisoformat(target_date)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid date: {date}") from exc
    normalized_component = (component or "").strip().lower()
    if normalized_component not in SUPPORTED_COMPONENTS:
        raise HTTPException(
            status_code=400,
            detail={
                "message": "Unsupported dashboard component",
                "component": normalized_component,
                "supported_components": sorted(SUPPORTED_COMPONENTS),
            },
        )
    return {
        "target_date": target_date,
        "component": normalized_component,
        "filters": dashboard_solver.normalize_filter_payload(filters),
    }


def _normalize_component_list(components: Optional[List[str]]) -> List[str]:
    requested_components = [str(c or "").strip().lower() for c in (components or sorted(SUPPORTED_COMPONENTS))]
    requested_components = [c for c in requested_components if c]
    invalid = [c for c in requested_components if c not in SUPPORTED_COMPONENTS]
    if invalid:
        raise HTTPException(status_code=400, detail={"message": "Unsupported dashboard component(s)", "components": invalid, "supported_components": sorted(SUPPORTED_COMPONENTS)})
    return requested_components


def _query_response(
    payload: Dict[str, Any],
    component: str,
    page_size: int,
    page_number: int,
    sort_by: str,
    sort_direction: str,
    include_metadata: bool,
) -> Dict[str, Any]:
    return apply_report_query(
        payload=payload,
        component=component,
        page_size=page_size,
        page_number=page_number,
        sort_by=sort_by,
        sort_direction=sort_direction,
        include_metadata=include_metadata,
    )


def _legacy_solver_response(
    *,
    target_date: str,
    component: str,
    filters: Dict[str, Any],
    page_size: int,
    page_number: int,
    sort_by: str,
    sort_direction: str,
    include_metadata: bool,
    active_lineups: bool,
) -> Dict[str, Any]:
    filters_hash = stable_hash(filters)
    cache_key = make_cache_key(
        "dashboard_solver",
        "active_lineups_full_result" if active_lineups else "component_full_result",
        target_date,
        component,
        filters_hash,
    )

    def build() -> Dict[str, Any]:
        factory = session_factory()
        with factory() as session:
            if active_lineups:
                return build_active_lineup_solver_payload(
                    session=session,
                    date=target_date,
                    component=component,
                    filters=filters,
                )
            return dashboard_solver.build_dashboard_solver_payload(
                session=session,
                date=target_date,
                component=component,
                filters=filters,
            )

    full_payload = get_or_set(cache_key, env_ttl("DASHBOARD_SOLVER_CACHE_TTL_SECONDS"), build)
    response = _query_response(full_payload, component, page_size, page_number, sort_by, sort_direction, include_metadata)
    response.setdefault("execution_path", "legacy_in_memory_solver")
    return response


def _run_solver(
    date: Optional[str],
    component: str,
    filters: Optional[Dict[str, Any]],
    page_size: int = DEFAULT_PAGE_SIZE,
    page_number: int = 1,
    sort_by: str = "score",
    sort_direction: str = "desc",
    include_metadata: bool = True,
) -> Dict[str, Any]:
    install_dashboard_context_cache()
    normalized = _normalize_request(date, component, filters)
    target_date = normalized["target_date"]
    normalized_component = normalized["component"]
    normalized_filters = normalized["filters"]

    try:
        if should_use_dataset_query(date=target_date, filters=normalized_filters):
            factory = session_factory()
            with factory() as session:
                return run_dataset_query(
                    session=session,
                    date=target_date,
                    component=normalized_component,
                    filters=normalized_filters,
                    page_size=page_size,
                    page_number=page_number,
                    sort_by=sort_by,
                    sort_direction=sort_direction,
                    include_metadata=include_metadata,
                    payload_builder=lambda: dashboard_solver.build_dashboard_solver_payload(
                        session=session,
                        date=target_date,
                        component=normalized_component,
                        filters={},
                    ),
                    active_lineups=False,
                )
        return _legacy_solver_response(
            target_date=target_date,
            component=normalized_component,
            filters=normalized_filters,
            page_size=page_size,
            page_number=page_number,
            sort_by=sort_by,
            sort_direction=sort_direction,
            include_metadata=include_metadata,
            active_lineups=False,
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail={"message": "My Dashboard solver failed", "error": str(exc)}) from exc


def _run_active_lineup_solver(
    date: Optional[str],
    component: str,
    filters: Optional[Dict[str, Any]],
    page_size: int = DEFAULT_PAGE_SIZE,
    page_number: int = 1,
    sort_by: str = "score",
    sort_direction: str = "desc",
    include_metadata: bool = True,
) -> Dict[str, Any]:
    install_dashboard_context_cache()
    normalized = _normalize_request(date, component, filters)
    target_date = normalized["target_date"]
    normalized_component = normalized["component"]
    normalized_filters = normalized["filters"]

    try:
        if should_use_dataset_query(date=target_date, filters=normalized_filters):
            factory = session_factory()
            with factory() as session:
                return run_dataset_query(
                    session=session,
                    date=target_date,
                    component=normalized_component,
                    filters=normalized_filters,
                    page_size=page_size,
                    page_number=page_number,
                    sort_by=sort_by,
                    sort_direction=sort_direction,
                    include_metadata=include_metadata,
                    payload_builder=lambda: build_active_lineup_solver_payload(
                        session=session,
                        date=target_date,
                        component=normalized_component,
                        filters={},
                    ),
                    active_lineups=True,
                )
        return _legacy_solver_response(
            target_date=target_date,
            component=normalized_component,
            filters=normalized_filters,
            page_size=page_size,
            page_number=page_number,
            sort_by=sort_by,
            sort_direction=sort_direction,
            include_metadata=include_metadata,
            active_lineups=True,
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail={"message": "Active-lineup solver failed", "error": str(exc)}) from exc


def _run_batch_solver(
    date: Optional[str],
    components: Optional[List[str]],
    filters_by_component: Optional[Dict[str, Dict[str, Any]]],
    active_lineups: bool = False,
) -> Dict[str, Any]:
    install_dashboard_context_cache()
    target_date = (date or mlb_business_date().isoformat())[:10]
    try:
        dt.date.fromisoformat(target_date)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid date: {date}") from exc

    requested_components = _normalize_component_list(components)
    normalized_filters_by_component = {
        component: dashboard_solver.normalize_filter_payload((filters_by_component or {}).get(component))
        for component in requested_components
    }
    filters_hash = stable_hash(normalized_filters_by_component)
    cache_key = make_cache_key(
        "dashboard_solver",
        "batch_active_lineups_full_result" if active_lineups else "batch_full_result",
        target_date,
        ",".join(requested_components),
        filters_hash,
    )

    try:
        def build() -> Dict[str, Any]:
            return _build_batch_payload(
                target_date=target_date,
                requested_components=requested_components,
                normalized_filters_by_component=normalized_filters_by_component,
                active_lineups=active_lineups,
                hydration_mode=False,
            )

        return get_or_set(cache_key, env_ttl("DASHBOARD_SOLVER_CACHE_TTL_SECONDS"), build)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail={"message": "My Dashboard batch solver failed", "error": str(exc)}) from exc


def _run_hydration(
    date: str,
    components: Optional[List[str]],
    active_lineups: bool = True,
    force: bool = False,
) -> Dict[str, Any]:
    install_dashboard_context_cache()
    target_date = (date or _yesterday_iso())[:10]
    try:
        dt.date.fromisoformat(target_date)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid date: {date}") from exc

    requested_components = _normalize_component_list(components)
    normalized_filters_by_component = {component: {} for component in requested_components}
    cache_key = make_cache_key(
        "dashboard_solver",
        "morning_hydration_active_lineups_full_result" if active_lineups else "morning_hydration_full_result",
        target_date,
        ",".join(requested_components),
    )
    run = begin_hydration(target_date, requested_components, active_lineups, force)

    def build() -> Dict[str, Any]:
        hydrated = _build_batch_payload(
            target_date=target_date,
            requested_components=requested_components,
            normalized_filters_by_component=normalized_filters_by_component,
            active_lineups=active_lineups,
            hydration_mode=True,
        )
        hydrated.update({
            "hydration_status": "hydrated",
            "hydration_target": "yesterday_confirmed_1_9" if active_lineups else "standard_dashboard_solver",
            "hydrated_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
            "force_requested": force,
        })
        return hydrated

    try:
        cache_mode = "forced_refresh" if force else "cache_allowed"
        hydrated = build() if force else get_or_set(cache_key, env_ttl("DASHBOARD_SOLVER_CACHE_TTL_SECONDS"), build)
        execution = complete_hydration(run, hydrated, cache_mode=cache_mode)
        return {**hydrated, "execution": execution}
    except HTTPException:
        raise
    except Exception as exc:
        fail_hydration(run, exc)
        raise HTTPException(status_code=500, detail={"message": "My Dashboard hydration failed", "error": str(exc)}) from exc


def _build_batch_payload(
    target_date: str,
    requested_components: List[str],
    normalized_filters_by_component: Dict[str, Dict[str, Any]],
    active_lineups: bool,
    hydration_mode: bool,
) -> Dict[str, Any]:
    results: Dict[str, Any] = {}
    factory = session_factory()
    with factory() as session:
        for component in requested_components:
            filters = normalized_filters_by_component.get(component) or {}
            if active_lineups:
                results[component] = build_active_lineup_solver_payload(
                    session=session,
                    date=target_date,
                    component=component,
                    filters=filters,
                )
            else:
                results[component] = dashboard_solver.build_dashboard_solver_payload(
                    session=session,
                    date=target_date,
                    component=component,
                    filters=filters,
                )
    return {
        "date": target_date,
        "components": requested_components,
        "active_lineups": active_lineups,
        "hydration_mode": hydration_mode,
        "lineup_source_policy": "confirmed_1_9_lineups" if active_lineups else "not_lineup_filtered",
        "results": results,
    }

from __future__ import annotations

import datetime
import os
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException

from .database import SharedReportArtifact, create_tables, get_engine, get_session
from .model_projection_performance_cache import build_model_projection_payload
from .model_projection_probability import build_model_projection_probability
from .model_tracker_routes import router as model_tracker_router
from .performance import estimate_payload_bytes, record_probability_source, record_span, timing_span
from .schedule_calendar import build_calendar_window_payload, warm_schedule_calendar_window
from .shared_artifacts import (
    attach_artifact_metadata,
    artifact_metadata,
    cache_artifact,
    MODEL_PROJECTION_WORKSPACE_VERSION,
    model_projection_date_key,
    model_projection_probability_key,
    payload_input_hash,
)
from .shared_payload_cache import env_ttl, get_cache
from mlb_app.simulation.game_simulation_builder import build_game_simulation as build_shared_game_simulation

router = APIRouter()
router.include_router(model_tracker_router)


def _session_factory():
    database_url = os.getenv("DATABASE_URL", "sqlite:///mlb.db")
    engine = get_engine(database_url)
    create_tables(engine)
    return get_session(engine)


def _projection_cache_key(target_date: str) -> str:
    return model_projection_date_key(target_date)


def _canonical_outcome_transport_complete(
    payload: Any,
) -> bool:
    """
    Reject warmed payloads that claim completed canonical execution
    without transporting the same run's game outcomes.

    Games with no completed canonical execution remain valid.
    """

    if not isinstance(payload, dict):
        return False

    games = payload.get("games")

    if not isinstance(games, list):
        return False

    for game in games:
        if not isinstance(game, dict):
            continue

        shared_simulation = game.get("sharedSimulation")

        if not isinstance(shared_simulation, dict):
            shared_simulation = {}

        shared_diagnostics = shared_simulation.get(
            "diagnostics"
        )

        if not isinstance(shared_diagnostics, dict):
            shared_diagnostics = {}

        execution = (
            game.get(
                "canonical_shadow_production_execution"
            )
            or shared_diagnostics.get(
                "canonical_shadow_production_execution"
            )
            or {}
        )

        if not isinstance(execution, dict):
            execution = {}

        executed = (
            execution.get("executed") is True
            or execution.get("status") == "executed"
        )

        if not executed:
            continue

        canonical_shadow = shared_diagnostics.get(
            "canonical_shadow"
        )

        if not isinstance(canonical_shadow, dict):
            return False

        outcomes = canonical_shadow.get(
            "canonical_outcomes"
        )

        if not isinstance(outcomes, dict):
            return False

        if outcomes.get("schema_version") != (
            "canonical_game_outcomes_transport_v1"
        ):
            return False

        if outcomes.get("simulation_count") in (
            None,
            0,
        ):
            return False

    return True


def _attach_projection_artifact_metadata(payload: Dict[str, Any], target_date: str) -> Dict[str, Any]:
    metadata = artifact_metadata(
        artifact_type="model_projection_date",
        cache_key=_projection_cache_key(target_date),
        source_route="/models/projections",
        source_builder="model_projection_routes._build_uncached_projection_payload",
        model_version=MODEL_PROJECTION_WORKSPACE_VERSION,
        probability_source="model_projections",
    )
    attach_artifact_metadata(payload, metadata)
    return payload


def _apply_projection_probability_contract(payload: Dict[str, Any], target_date: str) -> Dict[str, Any]:
    """Expose Model Projections as the displayed/default probability source.

    Existing canonical/debug objects stay available for compatibility, but
    top-level probability aliases now resolve from Model Projections shared
    derived simulation output when available.
    """
    games = payload.get("games") if isinstance(payload.get("games"), list) else []
    for game in games:
        if not isinstance(game, dict):
            continue
        probability = build_model_projection_probability(
            game_pk=game.get("game_pk"),
            date=game.get("game_date") or target_date,
            shared_simulation=game.get("sharedSimulation"),
            matchup=game,
            generated_at=payload.get("generated_at"),
        )
        probability_hash = payload_input_hash({
            "game_pk": game.get("game_pk"),
            "date": game.get("game_date") or target_date,
            "source_path": probability.get("source_path"),
            "home_win_probability": probability.get("home_win_probability"),
            "away_win_probability": probability.get("away_win_probability"),
        })
        probability_cache_key = model_projection_probability_key(
            date=game.get("game_date") or target_date,
            game_pk=game.get("game_pk"),
            model_version=probability.get("model_version"),
            input_hash=probability_hash,
        )
        attach_artifact_metadata(
            probability,
            artifact_metadata(
                artifact_type="model_projection_probability",
                cache_key=probability_cache_key,
                source_route="/models/projections",
                source_builder="model_projection_probability.build_model_projection_probability",
                model_version=probability.get("model_version"),
                input_hash=probability_hash,
                probability_source=probability.get("source"),
            ),
        )
        game["model_projection_probability"] = probability
        game["probability"] = probability
        game["home_win_probability"] = probability.get("home_win_probability")
        game["away_win_probability"] = probability.get("away_win_probability")
        game["home_win_prob"] = probability.get("home_win_prob")
        game["away_win_prob"] = probability.get("away_win_prob")
        game["probability_source"] = probability.get("source")
        game["probability_source_path"] = probability.get("source_path")
        game["probability_is_fallback"] = probability.get("is_fallback")
        game["probability_cache_key"] = probability_cache_key

        workspace = game.get("workspace")
        if isinstance(workspace, dict):
            workspace["modelProjectionProbability"] = probability
            diagnostics = workspace.get("sharedSimulationDiagnostics")
            if isinstance(diagnostics, dict):
                diagnostics["displayed_probability_source"] = probability.get("source")
                diagnostics["displayed_probability_source_path"] = probability.get("source_path")
                diagnostics["displayed_probability_is_fallback"] = probability.get("is_fallback")
                diagnostics["displayed_probability_cache_key"] = probability_cache_key

        main = game.get("main_matchup_probabilities")
        if isinstance(main, dict):
            main["displayed_probability_source"] = probability.get("source")
            main["displayed_probability_source_path"] = probability.get("source_path")
            main["displayed_probability_is_fallback"] = probability.get("is_fallback")
            main["model_projection_probability"] = probability

    notes = list(payload.get("source_notes") or [])
    notes = [note for note in notes if "home_win_prob and away_win_prob are canonical v2" not in str(note)]
    notes = [note for note in notes if "Simulation outputs remain available as diagnostics and do not define final side probability" not in str(note)]
    notes.append("Displayed/default home_win_prob and away_win_prob are resolved from Model Projections sharedSimulation derived outputs when available.")
    notes.append("Canonical matchup probability remains available as a compatibility/fallback diagnostic, not the displayed Model Projections source of truth.")
    payload["source_notes"] = notes
    payload["probability_contract"] = "model_projection_probability_v1"
    payload["workspace_contract"] = MODEL_PROJECTION_WORKSPACE_VERSION
    payload["probability_source"] = "model_projections"
    return payload


def _build_uncached_projection_payload(target_date: str) -> Dict[str, Any]:
    with timing_span("model_projection.session_factory", category="db", route="/models/projections", date=target_date):
        session_factory = _session_factory()
    with session_factory() as session:
        with timing_span(
            "build_model_projection_payload",
            category="projection",
            route="/models/projections",
            date=target_date,
            probability_source="model_projections",
        ):
            payload = build_model_projection_payload(session, target_date)
            session.commit()
    payload = _apply_projection_probability_contract(payload, target_date)
    payload = _attach_projection_artifact_metadata(payload, target_date)
    record_probability_source("model_projections")
    record_span(
        "model_projection.payload_bytes",
        category="serialization",
        route="/models/projections",
        date=target_date,
        probability_source="model_projections",
        payload_bytes=estimate_payload_bytes(payload),
    )
    return payload


def warm_model_projection_payload(target_date: str) -> Dict[str, Any]:
    """Build and store the projection payload explicitly for cron/warm jobs."""
    payload = _build_uncached_projection_payload(target_date)
    stored = cache_artifact(
        cache_key=_projection_cache_key(target_date),
        payload=payload,
        artifact_type="model_projection_date",
        source_route="/models/projections",
        source_builder="model_projection_routes.warm_model_projection_payload",
        model_version=MODEL_PROJECTION_WORKSPACE_VERSION,
        probability_source="model_projections",
    )
    factory = _session_factory()
    with factory() as session:
        artifact = (
            session.query(SharedReportArtifact)
            .filter(SharedReportArtifact.artifact_key == _projection_cache_key(target_date))
            .first()
        )
        if artifact is None:
            artifact = SharedReportArtifact(
                artifact_key=_projection_cache_key(target_date),
                artifact_type="model_projection_date",
                target_date=datetime.date.fromisoformat(target_date),
                payload_json=stored,
            )
            session.add(artifact)
        else:
            artifact.payload_json = stored
            artifact.updated_at = datetime.datetime.utcnow()
        artifact.row_count = len(stored.get("games") or []) if isinstance(stored, dict) else 0
        artifact.generated_at = datetime.datetime.utcnow()
        session.commit()
    return {
        "warmed": True,
        "date": target_date,
        "games_cached": len(stored.get("games") or []) if isinstance(stored, dict) else None,
        "cache_key": _projection_cache_key(target_date),
        "probability_contract": "model_projection_probability_v1",
        "workspace_contract": MODEL_PROJECTION_WORKSPACE_VERSION,
        "artifact": stored.get("artifact") if isinstance(stored, dict) else None,
    }


def get_model_projection_payload(target_date: str) -> Dict[str, Any]:
    """Read the warmed projection artifact without building inside a user request."""
    cache_key = _projection_cache_key(target_date)
    cached = get_cache(cache_key, env_ttl("MODEL_PROJECTION_CACHE_TTL_SECONDS"))
    if (
        cached is not None
        and _canonical_outcome_transport_complete(
            cached
        )
    ):
        if isinstance(cached, dict):
            cached.setdefault("cache_hit", True)
            cached.setdefault("cache_key", cache_key)
            cached.setdefault("data_status", "ready")
        return cached
    factory = _session_factory()
    with factory() as session:
        artifact = (
            session.query(SharedReportArtifact)
            .filter(SharedReportArtifact.artifact_key == cache_key)
            .first()
        )
        if (
            artifact is not None
            and isinstance(
                artifact.payload_json,
                dict,
            )
            and _canonical_outcome_transport_complete(
                artifact.payload_json
            )
        ):
            payload = dict(artifact.payload_json)
            payload.update({
                "cache_hit": False,
                "durable_artifact_hit": True,
                "cache_key": cache_key,
                "data_status": "ready",
                "last_successful_at": artifact.updated_at.isoformat() if artifact.updated_at else None,
            })
            return payload
    return {
        "date": target_date,
        "games": [],
        "data_status": "not_ready",
        "refreshing": False,
        "stale": False,
        "cache_hit": False,
        "cache_key": cache_key,
        "message": "Model projections have not been warmed for this date.",
        "refresh_contract": "scheduled_warm_required",
    }


@router.get("/models/projections")
def model_projections(date: Optional[str] = None) -> Dict[str, Any]:
    target_date = date or datetime.date.today().isoformat()
    cache_key = _projection_cache_key(target_date)
    try:
        with timing_span(
            "route.models.projections.resolve",
            category="route",
            route="/models/projections",
            date=target_date,
            probability_source="model_projections",
        ):
            payload = get_model_projection_payload(target_date)
        record_probability_source("model_projections")
        record_span(
            "route.models.projections.payload_bytes",
            category="serialization",
            route="/models/projections",
            date=target_date,
            probability_source="model_projections",
            payload_bytes=estimate_payload_bytes(payload),
        )
        return payload
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail={"message": "Failed to build model projections", "error": str(exc)}) from exc


@router.get("/matchups/calendar/schedule")
def lightweight_matchup_calendar() -> Dict[str, Any]:
    """Lightweight schedule-only calendar payload for fast initial calendar load."""
    try:
        return build_calendar_window_payload()
    except Exception as exc:
        raise HTTPException(status_code=500, detail={"message": "Failed to build lightweight calendar", "error": str(exc)}) from exc


@router.post("/matchups/calendar/snapshot")
def snapshot_lightweight_matchup_calendar() -> Dict[str, Any]:
    """Warm schedule-only calendar snapshots without full matchup/model generation."""
    try:
        return warm_schedule_calendar_window()
    except Exception as exc:
        raise HTTPException(status_code=500, detail={"message": "Failed to warm lightweight calendar", "error": str(exc)}) from exc


@router.post("/models/projections/snapshot/{date_str}")
def snapshot_model_projections(date_str: str) -> Dict[str, Any]:
    try:
        datetime.datetime.strptime(date_str, "%Y-%m-%d")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="date_str must be YYYY-MM-DD") from exc
    try:
        return warm_model_projection_payload(date_str)
    except Exception as exc:
        raise HTTPException(status_code=500, detail={"message": "Failed to warm model projections", "error": str(exc)}) from exc

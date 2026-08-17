from __future__ import annotations

import datetime
from typing import Any, Callable, Dict, Optional

from .shared_payload_cache import env_ttl, get_cache, make_cache_key, set_cache, stable_hash

ARTIFACT_SCHEMA_VERSION = "shared_artifact_v1"


ARTIFACT_TYPES = {
    "schedule_calendar": "schedule_calendar",
    "matchups_date": "matchups_date",
    "model_projection_date": "model_projection_date",
    "model_projection_probability": "model_projection_probability",
    "matchup_overview": "matchup_overview",
    "simulation": "simulation",
}


def utc_timestamp() -> str:
    return datetime.datetime.utcnow().isoformat(timespec="seconds") + "Z"


def artifact_key(artifact_type: str, *parts: Any) -> str:
    if artifact_type not in ARTIFACT_TYPES.values():
        raise ValueError(f"Unknown artifact type: {artifact_type}")
    return make_cache_key("artifact", ARTIFACT_SCHEMA_VERSION, artifact_type, *parts)


def schedule_calendar_key(date: str) -> str:
    return artifact_key("schedule_calendar", date)


def matchups_date_key(date: str) -> str:
    return artifact_key("matchups_date", date)


MODEL_PROJECTION_WORKSPACE_VERSION = (
    "model_projection_workspace_v4"
)


def model_projection_date_key(date: str) -> str:
    return artifact_key(
        "model_projection_date",
        MODEL_PROJECTION_WORKSPACE_VERSION,
        date,
    )


def model_projection_probability_key(
    *,
    date: str,
    game_pk: Any,
    model_version: Optional[str] = None,
    input_hash: Optional[str] = None,
) -> str:
    return artifact_key(
        "model_projection_probability",
        date,
        game_pk,
        model_version or "unknown_model",
        input_hash or "no_input_hash",
    )


def matchup_overview_key(date: str, game_pk: Any) -> str:
    return artifact_key("matchup_overview", date, game_pk)


def simulation_key(
    *,
    date: str,
    game_pk: Any,
    simulation_count: Any,
    input_hash: Optional[str] = None,
) -> str:
    return artifact_key("simulation", date, game_pk, simulation_count, input_hash or "no_input_hash")


def artifact_metadata(
    *,
    artifact_type: str,
    cache_key: str,
    source_route: Optional[str] = None,
    source_builder: Optional[str] = None,
    model_version: Optional[str] = None,
    input_hash: Optional[str] = None,
    probability_source: Optional[str] = None,
    generated_at: Optional[str] = None,
) -> Dict[str, Any]:
    if artifact_type not in ARTIFACT_TYPES.values():
        raise ValueError(f"Unknown artifact type: {artifact_type}")
    return {
        "artifact_schema_version": ARTIFACT_SCHEMA_VERSION,
        "artifact_type": artifact_type,
        "cache_key": cache_key,
        "generated_at": generated_at or utc_timestamp(),
        "source_route": source_route,
        "source_builder": source_builder,
        "model_version": model_version,
        "input_hash": input_hash,
        "probability_source": probability_source,
    }


def attach_artifact_metadata(payload: Any, metadata: Dict[str, Any]) -> Any:
    if isinstance(payload, dict):
        existing = payload.get("artifact") if isinstance(payload.get("artifact"), dict) else {}
        payload["artifact"] = {**existing, **metadata}
        payload.setdefault("generated_at", metadata.get("generated_at"))
        payload.setdefault("cache_key", metadata.get("cache_key"))
    return payload


def cache_artifact(
    *,
    cache_key: str,
    payload: Any,
    artifact_type: str,
    source_route: Optional[str] = None,
    source_builder: Optional[str] = None,
    model_version: Optional[str] = None,
    input_hash: Optional[str] = None,
    probability_source: Optional[str] = None,
) -> Any:
    metadata = artifact_metadata(
        artifact_type=artifact_type,
        cache_key=cache_key,
        source_route=source_route,
        source_builder=source_builder,
        model_version=model_version,
        input_hash=input_hash,
        probability_source=probability_source,
    )
    return set_cache(cache_key, attach_artifact_metadata(payload, metadata))


def get_or_build_artifact(
    *,
    cache_key: str,
    ttl_seconds: int,
    builder: Callable[[], Any],
    artifact_type: str,
    source_route: Optional[str] = None,
    source_builder: Optional[str] = None,
    model_version: Optional[str] = None,
    input_hash: Optional[str] = None,
    probability_source: Optional[str] = None,
) -> Any:
    cached = get_cache(cache_key, ttl_seconds)
    if cached is not None:
        if isinstance(cached, dict):
            cached.setdefault("cache_hit", True)
            cached.setdefault("cache_key", cache_key)
            artifact = cached.get("artifact") if isinstance(cached.get("artifact"), dict) else {}
            cached["artifact"] = {
                **artifact,
                "cache_key": cache_key,
                "artifact_schema_version": artifact.get("artifact_schema_version") or ARTIFACT_SCHEMA_VERSION,
                "artifact_type": artifact.get("artifact_type") or artifact_type,
            }
        return cached

    payload = builder()
    return cache_artifact(
        cache_key=cache_key,
        payload=payload,
        artifact_type=artifact_type,
        source_route=source_route,
        source_builder=source_builder,
        model_version=model_version,
        input_hash=input_hash,
        probability_source=probability_source,
    )


def payload_input_hash(value: Any) -> str:
    return stable_hash(value)


__all__ = [
    "ARTIFACT_SCHEMA_VERSION",
    "ARTIFACT_TYPES",
    "artifact_key",
    "artifact_metadata",
    "attach_artifact_metadata",
    "cache_artifact",
    "get_or_build_artifact",
    "matchup_overview_key",
    "matchups_date_key",
    "MODEL_PROJECTION_WORKSPACE_VERSION",
    "model_projection_date_key",
    "model_projection_probability_key",
    "payload_input_hash",
    "schedule_calendar_key",
    "simulation_key",
    "utc_timestamp",
]

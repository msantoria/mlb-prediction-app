"""Code-owned Control Center profiles, settings, and feature-flag contracts."""

from __future__ import annotations

import datetime as dt
from typing import Any, Dict, Iterable, List, Mapping, Tuple

from fastapi import HTTPException

from .database import (
    AppAccessProfile,
    AppAdminAuditEvent,
    AppFeatureFlag,
    AppGlobalSetting,
    AppUserDirectoryProfile,
)

PROFILE_OWNER = "owner_administrator"
PROFILE_STANDARD = "standard_user"
EASTERN_TIME_ZONE = "America/New_York"

PROFILE_DEFINITIONS: Dict[str, Dict[str, str]] = {
    PROFILE_OWNER: {
        "label": "Owner Administrator",
        "role": "admin",
        "description": "Private owner profile with server-verified administrative capabilities.",
    },
    PROFILE_STANDARD: {
        "label": "Standard User",
        "role": "user",
        "description": "Personal MyDashboard reporting, folders, saved reports, and export.",
    },
}

SETTING_DEFINITIONS: Dict[Tuple[str, str], Dict[str, Any]] = {
    ("identity", "default_locale"): {
        "value_type": "string",
        "default": "en_US",
        "description": "Default locale for newly materialized directory profiles.",
        "validation": {"allowed": ["en_US"]},
        "environment_variable": None,
        "sensitive": False,
    },
    ("identity", "default_language"): {
        "value_type": "string",
        "default": "en",
        "description": "Default language for newly materialized directory profiles.",
        "validation": {"allowed": ["en"]},
        "environment_variable": None,
        "sensitive": False,
    },
    ("identity", "default_timezone"): {
        "value_type": "string",
        "default": EASTERN_TIME_ZONE,
        "description": "Default Eastern Time zone for newly materialized directory profiles.",
        "validation": {
            "allowed": [
                "UTC",
                "America/Chicago",
                "America/Denver",
                "America/Los_Angeles",
                "America/New_York",
            ]
        },
        "environment_variable": None,
        "sensitive": False,
    },
}

FEATURE_FLAG_DEFINITIONS: Dict[str, Dict[str, str]] = {
    "federation_enabled": {
        "label": "Federation",
        "description": "Foundation gate for federated data services. No public behavior is wired in this phase.",
    },
    "federation_admin_enabled": {
        "label": "Federation administration",
        "description": "Foundation gate for future owner-only federation controls.",
    },
    "workbench_query_enabled": {
        "label": "Query Studio",
        "description": "Gates the owner-only constrained Query Studio in MyDashboard.",
    },
    "federation_refresh_enabled": {
        "label": "Federation refresh",
        "description": "Foundation gate only; no refresh or backfill action is exposed.",
    },
}


def _utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)


def profile_key_for_role(role: str) -> str:
    return PROFILE_OWNER if role == "admin" else PROFILE_STANDARD


def ensure_profile_catalog(session) -> None:
    now = _utcnow()
    existing = {
        item.profile_key: item
        for item in session.query(AppAccessProfile).all()
    }
    for key, definition in PROFILE_DEFINITIONS.items():
        item = existing.get(key)
        if item is None:
            session.add(AppAccessProfile(
                profile_key=key,
                label=definition["label"],
                role=definition["role"],
                description=definition["description"],
                created_at=now,
                updated_at=now,
            ))
            continue
        # Labels and role mappings are code-owned and converge only when needed.
        expected = (
            definition["label"],
            definition["role"],
            definition["description"],
        )
        if (item.label, item.role, item.description) != expected:
            item.label, item.role, item.description = expected
            item.updated_at = now


def serialize_profile_catalog(capabilities_for_role) -> List[Dict[str, Any]]:
    return [
        {
            "key": key,
            "label": definition["label"],
            "role": definition["role"],
            "description": definition["description"],
            "capabilities": list(capabilities_for_role(definition["role"])),
            "mutable": False,
        }
        for key, definition in PROFILE_DEFINITIONS.items()
    ]


def get_or_create_directory_profile(
    session,
    user_id: int,
    *,
    actor_user_id: int | None = None,
) -> AppUserDirectoryProfile:
    profile = (
        session.query(AppUserDirectoryProfile)
        .filter(AppUserDirectoryProfile.user_id == user_id)
        .first()
    )
    if profile is not None:
        # UTC was the original application default. Converge those legacy
        # directory rows to the product-wide Eastern Time contract while still
        # preserving any explicitly selected non-UTC timezone.
        if profile.timezone in (None, "", "UTC"):
            profile.timezone = EASTERN_TIME_ZONE
            profile.updated_by_user_id = actor_user_id
            profile.updated_at = _utcnow()
        return profile
    defaults = resolved_setting_values(session)
    now = _utcnow()
    default_timezone = defaults[("identity", "default_timezone")]
    if default_timezone in (None, "", "UTC"):
        default_timezone = EASTERN_TIME_ZONE
    profile = AppUserDirectoryProfile(
        user_id=user_id,
        locale=defaults[("identity", "default_locale")],
        language=defaults[("identity", "default_language")],
        timezone=default_timezone,
        created_by_user_id=actor_user_id,
        updated_by_user_id=actor_user_id,
        created_at=now,
        updated_at=now,
    )
    session.add(profile)
    session.flush()
    return profile


def validate_setting_value(namespace: str, key: str, value: Any) -> Any:
    definition = SETTING_DEFINITIONS.get((namespace, key))
    if definition is None:
        raise HTTPException(status_code=400, detail=f"Unknown setting: {namespace}.{key}")
    if definition.get("sensitive"):
        raise HTTPException(status_code=400, detail="Plaintext sensitive settings are not accepted")
    expected = definition["value_type"]
    if expected == "boolean" and type(value) is not bool:
        raise HTTPException(status_code=400, detail=f"{namespace}.{key} must be a boolean")
    if expected == "integer" and (type(value) is not int):
        raise HTTPException(status_code=400, detail=f"{namespace}.{key} must be an integer")
    if expected == "string" and not isinstance(value, str):
        raise HTTPException(status_code=400, detail=f"{namespace}.{key} must be a string")
    allowed = definition.get("validation", {}).get("allowed")
    if allowed is not None and value not in allowed:
        raise HTTPException(
            status_code=400,
            detail=f"{namespace}.{key} must be one of: {', '.join(map(str, allowed))}",
        )
    return value.strip() if isinstance(value, str) else value


def resolved_setting_values(session) -> Dict[Tuple[str, str], Any]:
    values = {
        identity: definition["default"]
        for identity, definition in SETTING_DEFINITIONS.items()
    }
    for item in session.query(AppGlobalSetting).all():
        identity = (item.namespace, item.setting_key)
        if identity in SETTING_DEFINITIONS and item.sensitive_reference is None:
            values[identity] = item.value_json
    return values


def serialize_settings(session) -> List[Dict[str, Any]]:
    rows = {
        (item.namespace, item.setting_key): item
        for item in session.query(AppGlobalSetting).all()
    }
    values = resolved_setting_values(session)
    payload = []
    for identity, definition in SETTING_DEFINITIONS.items():
        namespace, key = identity
        row = rows.get(identity)
        payload.append({
            "namespace": namespace,
            "key": key,
            "value_type": definition["value_type"],
            "value": values[identity],
            "default_value": definition["default"],
            "validation": definition.get("validation", {}),
            "description": definition["description"],
            "environment_override": bool(definition.get("environment_variable")),
            "environment_variable": definition.get("environment_variable"),
            "sensitive": bool(definition.get("sensitive")),
            "configured": row is not None,
            "updated_at": row.updated_at.isoformat() if row and row.updated_at else None,
        })
    return payload


def validate_target_profiles(values: Iterable[str]) -> List[str]:
    normalized = sorted({str(value or "").strip() for value in values if str(value or "").strip()})
    unknown = [value for value in normalized if value not in PROFILE_DEFINITIONS]
    if unknown:
        raise HTTPException(status_code=400, detail=f"Unknown target profile: {unknown[0]}")
    return normalized


def serialize_feature_flags(session) -> List[Dict[str, Any]]:
    rows = {item.flag_key: item for item in session.query(AppFeatureFlag).all()}
    payload = []
    for key, definition in FEATURE_FLAG_DEFINITIONS.items():
        row = rows.get(key)
        payload.append({
            "key": key,
            "label": definition["label"],
            "description": definition["description"],
            "enabled": bool(row.enabled) if row else False,
            "target_profiles": validate_target_profiles(row.target_profiles_json or []) if row else [],
            "default_enabled": False,
            "configured": row is not None,
            "authorization_effect": "none",
            "updated_at": row.updated_at.isoformat() if row and row.updated_at else None,
        })
    return payload


def safe_audit_value(value: Any) -> Any:
    """Recursively remove security-bearing fields before persistence or response."""

    forbidden = {
        "password",
        "password_hash",
        "session_token",
        "token",
        "secret",
        "sensitive_reference",
    }
    if isinstance(value, Mapping):
        return {
            str(key): safe_audit_value(item)
            for key, item in value.items()
            if str(key).lower() not in forbidden
        }
    if isinstance(value, (list, tuple)):
        return [safe_audit_value(item) for item in value]
    return value


def record_audit_event(
    session,
    *,
    actor_user_id: int,
    actor_session_id: int | None,
    action: str,
    target_type: str,
    target_identifier: str,
    before: Any,
    after: Any,
) -> AppAdminAuditEvent:
    event = AppAdminAuditEvent(
        actor_user_id=actor_user_id,
        actor_session_id=actor_session_id,
        action=action,
        target_type=target_type,
        target_identifier=str(target_identifier),
        before_json=safe_audit_value(before),
        after_json=safe_audit_value(after),
        source="control_center_api",
        created_at=_utcnow(),
    )
    session.add(event)
    session.flush()
    return event

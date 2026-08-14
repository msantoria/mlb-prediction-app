from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import datetime as dt
from typing import Any, Callable, Mapping, Sequence

import requests


SCHEMA_VERSION = (
    "canonical_pregame_bullpen_evidence_provider_v1"
)
PAYLOAD_SCHEMA_VERSION = (
    "canonical_pregame_bullpen_observations_v1"
)

ALLOWED_TEAM_SIDES = frozenset({
    "away",
    "home",
})
ALLOWED_AVAILABILITY_STATUSES = frozenset({
    "eligible",
    "ineligible",
    "unknown",
})
ALLOWED_TYPICAL_ROLES = frozenset({
    "closer",
    "setup",
    "middle_reliever",
    "long_reliever",
})


def _identifier(value: Any) -> str | None:
    if value is None or isinstance(value, bool):
        return None

    normalized = str(value).strip()

    return normalized or None


def _text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None

    normalized = value.strip()

    return normalized or None


def _timestamp(value: Any) -> str | None:
    normalized = _text(value)

    if normalized is None:
        return None

    candidate = (
        normalized[:-1] + "+00:00"
        if normalized.endswith("Z")
        else normalized
    )

    try:
        parsed = dt.datetime.fromisoformat(
            candidate
        )
    except ValueError:
        return None

    if parsed.tzinfo is None:
        return None

    return parsed.isoformat()


def _team_identifier(
    *,
    team_side: str,
    away_team_id: Any,
    home_team_id: Any,
) -> str | None:
    return _identifier(
        away_team_id
        if team_side == "away"
        else home_team_id
    )


def _normalize_observation(
    *,
    row: Any,
    away_team_id: Any,
    home_team_id: Any,
    provider_name: str,
) -> tuple[dict[str, Any] | None, str | None]:
    if not isinstance(row, Mapping):
        return None, "observation_not_mapping"

    team_side = _text(row.get("team_side"))

    if team_side not in ALLOWED_TEAM_SIDES:
        return None, "team_side_invalid"

    expected_team_id = _team_identifier(
        team_side=team_side,
        away_team_id=away_team_id,
        home_team_id=home_team_id,
    )
    observed_team_id = _identifier(
        row.get("team_id")
    )

    if (
        expected_team_id is None
        or observed_team_id != expected_team_id
    ):
        return None, "team_identity_mismatch"

    pitcher_id = _identifier(
        row.get("pitcher_id")
    )

    if pitcher_id is None:
        return None, "pitcher_identity_missing"

    status = _text(row.get("status"))

    if status not in ALLOWED_AVAILABILITY_STATUSES:
        return None, "availability_status_invalid"

    role = _text(row.get("role"))

    if role is not None and role not in (
        ALLOWED_TYPICAL_ROLES
    ):
        return None, "typical_role_invalid"

    observed_at = _timestamp(
        row.get("observed_at")
    )

    if observed_at is None:
        return None, "observation_timestamp_invalid"

    reason = _text(row.get("reason"))
    provider_record_id = _identifier(
        row.get("provider_record_id")
    )

    return {
        "pitcher_id": pitcher_id,
        "status": status,
        "role": role,
        "source": (
            f"{provider_name}_pregame_bullpen_v1"
        ),
        "observed_at": observed_at,
        "reason": reason,
        "provider_record_id": provider_record_id,
        "team_side": team_side,
        "team_id": expected_team_id,
    }, None


@dataclass(frozen=True)
class CanonicalPregameBullpenEvidenceProviderResult:
    status: str
    provider_name: str | None = None
    endpoint_configured: bool = False
    observations: tuple[
        Mapping[str, Any],
        ...,
    ] = ()
    source_record_count: int = 0
    invalid_record_count: int = 0
    invalid_reason_counts: Mapping[
        str,
        int,
    ] | None = None
    error_type: str | None = None
    error_message: str | None = None

    def to_observations(
        self,
        *,
        team_side: str,
    ) -> tuple[dict[str, Any], ...]:
        if team_side not in ALLOWED_TEAM_SIDES:
            raise ValueError(
                "team_side must be away or home"
            )

        return tuple(
            deepcopy(dict(observation))
            for observation in self.observations
            if observation.get("team_side")
            == team_side
        )

    def to_diagnostics(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "status": self.status,
            "provider_name": self.provider_name,
            "endpoint_configured": (
                self.endpoint_configured
            ),
            "source_record_count": (
                self.source_record_count
            ),
            "valid_observation_count": len(
                self.observations
            ),
            "invalid_record_count": (
                self.invalid_record_count
            ),
            "invalid_reason_counts": dict(
                sorted(
                    (
                        self.invalid_reason_counts
                        or {}
                    ).items()
                )
            ),
            "away_observation_count": sum(
                observation.get("team_side")
                == "away"
                for observation in self.observations
            ),
            "home_observation_count": sum(
                observation.get("team_side")
                == "home"
                for observation in self.observations
            ),
            "error_type": self.error_type,
            "error_message": self.error_message,
            "pitcher_identifiers_exposed": False,
            "raw_provider_payload_exposed": False,
            "availability_inference_used": False,
            "typical_role_inference_used": False,
            "workload_inference_used": False,
            "roster_order_inference_used": False,
            "news_keyword_inference_used": False,
            "database_writes_performed": False,
            "production_authority_changed": False,
        }


def fetch_canonical_pregame_bullpen_evidence(
    *,
    game_pk: Any,
    game_time: Any,
    away_team_id: Any,
    home_team_id: Any,
    endpoint: str | None,
    provider_name: str | None,
    api_token: str | None = None,
    request_get: Callable[..., Any] = requests.get,
    timeout_seconds: float = 10.0,
) -> CanonicalPregameBullpenEvidenceProviderResult:
    """
    Fetch explicit pregame bullpen evidence.

    The endpoint is an externally configured structured
    provider. MLB active-roster membership, news text,
    workload, roster order, and simulation usage are not
    converted into availability or typical-role evidence.
    """

    normalized_endpoint = _text(endpoint)
    normalized_provider = _text(provider_name)

    if (
        normalized_endpoint is None
        or normalized_provider is None
    ):
        return (
            CanonicalPregameBullpenEvidenceProviderResult(
                status="provider_not_configured",
                provider_name=normalized_provider,
                endpoint_configured=(
                    normalized_endpoint is not None
                ),
            )
        )

    normalized_game_pk = _identifier(game_pk)
    normalized_game_time = _timestamp(game_time)
    normalized_away_team_id = _identifier(
        away_team_id
    )
    normalized_home_team_id = _identifier(
        home_team_id
    )

    if (
        normalized_game_pk is None
        or normalized_game_time is None
        or normalized_away_team_id is None
        or normalized_home_team_id is None
    ):
        return (
            CanonicalPregameBullpenEvidenceProviderResult(
                status="request_context_invalid",
                provider_name=normalized_provider,
                endpoint_configured=True,
            )
        )

    headers = {
        "Accept": "application/json",
    }

    normalized_token = _text(api_token)

    if normalized_token is not None:
        headers["Authorization"] = (
            f"Bearer {normalized_token}"
        )

    try:
        response = request_get(
            normalized_endpoint,
            params={
                "game_pk": normalized_game_pk,
                "game_time": normalized_game_time,
                "away_team_id":
                    normalized_away_team_id,
                "home_team_id":
                    normalized_home_team_id,
            },
            headers=headers,
            timeout=float(timeout_seconds),
        )
        response.raise_for_status()
        payload = response.json()
    except Exception as exc:
        return (
            CanonicalPregameBullpenEvidenceProviderResult(
                status="provider_error",
                provider_name=normalized_provider,
                endpoint_configured=True,
                error_type=exc.__class__.__name__,
                error_message=str(exc),
            )
        )

    if not isinstance(payload, Mapping):
        return (
            CanonicalPregameBullpenEvidenceProviderResult(
                status="payload_invalid",
                provider_name=normalized_provider,
                endpoint_configured=True,
                invalid_record_count=1,
                invalid_reason_counts={
                    "payload_not_mapping": 1,
                },
            )
        )

    if (
        payload.get("schema_version")
        != PAYLOAD_SCHEMA_VERSION
    ):
        return (
            CanonicalPregameBullpenEvidenceProviderResult(
                status="schema_mismatch",
                provider_name=normalized_provider,
                endpoint_configured=True,
                invalid_record_count=1,
                invalid_reason_counts={
                    "schema_version_invalid": 1,
                },
            )
        )

    rows = payload.get("observations")

    if not isinstance(rows, Sequence) or isinstance(
        rows,
        (str, bytes, bytearray),
    ):
        return (
            CanonicalPregameBullpenEvidenceProviderResult(
                status="payload_invalid",
                provider_name=normalized_provider,
                endpoint_configured=True,
                invalid_record_count=1,
                invalid_reason_counts={
                    "observations_not_sequence": 1,
                },
            )
        )

    observations = []
    invalid_reason_counts: dict[str, int] = {}

    for row in rows:
        observation, invalid_reason = (
            _normalize_observation(
                row=row,
                away_team_id=(
                    normalized_away_team_id
                ),
                home_team_id=(
                    normalized_home_team_id
                ),
                provider_name=(
                    normalized_provider
                ),
            )
        )

        if observation is None:
            reason = (
                invalid_reason
                or "observation_invalid"
            )
            invalid_reason_counts[reason] = (
                invalid_reason_counts.get(
                    reason,
                    0,
                )
                + 1
            )
            continue

        observations.append(observation)

    observations.sort(
        key=lambda observation: (
            observation["team_side"],
            observation["pitcher_id"],
            observation["observed_at"],
            observation["status"],
            observation["role"] or "",
        )
    )

    invalid_record_count = sum(
        invalid_reason_counts.values()
    )

    if observations and invalid_record_count:
        status = "partial"
    elif observations:
        status = "observed"
    elif invalid_record_count:
        status = "payload_invalid"
    else:
        status = "empty"

    return CanonicalPregameBullpenEvidenceProviderResult(
        status=status,
        provider_name=normalized_provider,
        endpoint_configured=True,
        observations=tuple(observations),
        source_record_count=len(rows),
        invalid_record_count=invalid_record_count,
        invalid_reason_counts=(
            invalid_reason_counts
        ),
    )

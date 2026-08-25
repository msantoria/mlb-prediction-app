"""Assemble shadow runtime candidates for canonical pitcher profiles."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
from collections.abc import Iterable, Mapping
from typing import Any

from .canonical_pitcher_matchup_profile_application import (
    apply_canonical_pitcher_matchup_profile_calibration,
)
from .canonical_pitcher_matchup_profile_evidence import (
    build_canonical_pitcher_matchup_profile_evidence,
)
from .canonical_pitcher_matchup_profile_league_prior import (
    build_canonical_pitcher_matchup_profile_league_priors,
)


RUNTIME_CANDIDATE_VERSION = (
    "canonical_pitcher_matchup_profile_runtime_candidate_v1"
)
CALIBRATION_ARTIFACT_VERSION = (
    "canonical_pitcher_matchup_profile_shrinkage_audit_v1"
)
CALIBRATION_POLICY_VERSION = (
    "canonical_pitcher_matchup_profile_calibration_policy_v1"
)

CALIBRATED_POOLED_PSEUDO_COUNTS = {
    "barrel_rate_allowed_approx": 400.0,
    "fly_ball_rate": 200.0,
    "ground_ball_rate": 50.0,
    "hard_hit_rate_allowed": 200.0,
    "k_rate": 100.0,
    "line_drive_rate": 1600.0,
    "popup_rate": 100.0,
    "sweet_spot_rate_allowed": 800.0,
}
BLOCKED_METRICS = {
    "bb_rate": [
        "cross_season_candidate_instability"
    ],
}


def _date(value: Any) -> dt.date:
    if isinstance(value, dt.datetime):
        return value.date()
    if isinstance(value, dt.date):
        return value

    try:
        return dt.date.fromisoformat(
            str(value).strip()[:10]
        )
    except (TypeError, ValueError) as exc:
        raise ValueError(
            "game_date must be a valid date"
        ) from exc


def _pitcher_id(value: Any) -> int:
    if isinstance(value, bool):
        raise ValueError(
            "pitcher_id must be positive"
        )

    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            "pitcher_id must be positive"
        ) from exc

    if parsed < 1:
        raise ValueError(
            "pitcher_id must be positive"
        )

    return parsed


def _digest(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def calibrated_candidate_policy() -> dict[str, Any]:
    """Return the immutable pooled candidate policy."""
    return {
        "schema_version": (
            CALIBRATION_POLICY_VERSION
        ),
        "status": "ready",
        "selection_scope": (
            "pooled_metrics_only"
        ),
        "parameter_selected": True,
        "selected_pseudo_counts": dict(
            CALIBRATED_POOLED_PSEUDO_COUNTS
        ),
        "blocked_metrics": {
            metric: list(reasons)
            for metric, reasons in (
                BLOCKED_METRICS.items()
            )
        },
        "segment_parameters_selected": False,
        "segment_policy": (
            "deferred_pending_season_disjoint_"
            "segment_stability"
        ),
        "production_authority": False,
        "production_authority_changed": False,
        "activation_status": (
            "candidate_policy_ready"
        ),
        "calibration_artifact_version": (
            CALIBRATION_ARTIFACT_VERSION
        ),
    }


def build_canonical_pitcher_matchup_profile_runtime_candidate(
    events: Iterable[Any],
    *,
    pitcher_id: int,
    game_date: dt.date | str,
    window_days: int = 90,
) -> dict[str, Any]:
    """Build a calibrated shadow candidate from one shared event window."""
    normalized_pitcher_id = _pitcher_id(
        pitcher_id
    )
    cutoff = _date(game_date)
    rows = list(events)

    evidence = (
        build_canonical_pitcher_matchup_profile_evidence(
            rows,
            pitcher_id=normalized_pitcher_id,
            game_date=cutoff,
            window_days=window_days,
        )
    )
    prior_result = (
        build_canonical_pitcher_matchup_profile_league_priors(
            rows,
            game_date=cutoff,
            excluded_pitcher_id=(
                normalized_pitcher_id
            ),
            window_days=window_days,
            metrics=(
                CALIBRATED_POOLED_PSEUDO_COUNTS
            ),
        )
    )
    policy = calibrated_candidate_policy()

    application = (
        apply_canonical_pitcher_matchup_profile_calibration(
            evidence,
            calibration_policy=policy,
            league_priors=prior_result[
                "league_priors"
            ],
        )
    )

    evidence_status = (
        evidence.get("diagnostics", {})
        .get("status")
    )
    prior_status = (
        prior_result["diagnostics"].get(
            "status"
        )
    )
    application_status = (
        application["diagnostics"].get(
            "status"
        )
    )

    if application_status == "ready":
        status = "ready"
    elif application_status == "partial":
        status = "partial"
    else:
        status = "unavailable"

    diagnostics = {
        "schema_version": (
            RUNTIME_CANDIDATE_VERSION
        ),
        "status": status,
        "pitcher_id": normalized_pitcher_id,
        "game_date": cutoff.isoformat(),
        "window_days": int(window_days),
        "cutoff_rule": (
            "events_strictly_before_game_date"
        ),
        "event_window_reused": True,
        "evidence_status": evidence_status,
        "league_prior_status": prior_status,
        "application_status": (
            application_status
        ),
        "selected_pseudo_counts": dict(
            CALIBRATED_POOLED_PSEUDO_COUNTS
        ),
        "blocked_metrics": {
            metric: list(reasons)
            for metric, reasons in (
                BLOCKED_METRICS.items()
            )
        },
        "segment_parameters_applied": False,
        "production_authority": False,
        "production_authority_changed": False,
        "activation_status": (
            "shadow_candidate_materialized"
        ),
        "evidence_digest": (
            evidence.get("diagnostics", {})
            .get("evidence_digest")
        ),
        "prior_digest": (
            prior_result["diagnostics"].get(
                "prior_digest"
            )
        ),
        "application_digest": (
            application["diagnostics"].get(
                "application_digest"
            )
        ),
    }
    diagnostics["runtime_candidate_digest"] = (
        _digest(diagnostics)
    )

    return {
        "profile_rates": dict(
            application["profile_rates"]
        ),
        "diagnostics": diagnostics,
        "evidence_diagnostics": (
            evidence.get("diagnostics", {})
        ),
        "league_prior_diagnostics": (
            prior_result["diagnostics"]
        ),
        "application_diagnostics": (
            application["diagnostics"]
        ),
    }

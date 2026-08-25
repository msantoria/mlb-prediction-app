"""Batch runtime assembly for canonical pitcher matchup profiles."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
from collections import defaultdict
from collections.abc import Iterable, Mapping
from typing import Any

from .canonical_pitcher_matchup_profile_application import (
    apply_canonical_pitcher_matchup_profile_calibration,
)
from .canonical_pitcher_matchup_profile_evidence import (
    build_canonical_pitcher_matchup_profile_evidence,
)
from .canonical_pitcher_matchup_profile_holdout import (
    METRIC_SPECS,
)
from .canonical_pitcher_matchup_profile_runtime_candidate import (
    BLOCKED_METRICS,
    CALIBRATED_POOLED_PSEUDO_COUNTS,
    calibrated_candidate_policy,
)


RUNTIME_BATCH_VERSION = (
    "canonical_pitcher_matchup_profile_runtime_batch_v1"
)


def _value(row: Any, key: str) -> Any:
    if isinstance(row, Mapping):
        return row.get(key)
    return getattr(row, key, None)


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


def _pitcher_id(value: Any) -> int | None:
    if isinstance(value, bool):
        return None

    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None

    return parsed if parsed > 0 else None


def _counts(
    summary: Mapping[str, Any],
    metric: str,
) -> tuple[int, int] | None:
    specification = METRIC_SPECS.get(metric)
    if specification is None:
        return None

    _, component, numerator_key = specification
    component_values = summary.get(component)
    denominators = summary.get(
        "metric_denominators"
    )

    if (
        not isinstance(
            component_values,
            Mapping,
        )
        or not isinstance(
            denominators,
            Mapping,
        )
    ):
        return None

    numerator = component_values.get(
        numerator_key
    )
    denominator = denominators.get(metric)

    if (
        not isinstance(numerator, int)
        or isinstance(numerator, bool)
        or not isinstance(denominator, int)
        or isinstance(denominator, bool)
        or numerator < 0
        or denominator < 0
        or numerator > denominator
    ):
        return None

    return numerator, denominator


def _digest(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def build_canonical_pitcher_matchup_profile_runtime_batch(
    events: Iterable[Any],
    *,
    pitcher_ids: Iterable[int],
    game_date: dt.date | str,
    window_days: int = 90,
) -> dict[str, Any]:
    """Build many exclusion-safe candidates from one evidence pass."""
    cutoff = _date(game_date)
    days = int(window_days)

    if days < 1:
        raise ValueError(
            "window_days must be positive"
        )

    requested = tuple(sorted({
        pitcher
        for value in pitcher_ids
        for pitcher in [_pitcher_id(value)]
        if pitcher is not None
    }))

    if not requested:
        raise ValueError(
            "at least one positive pitcher_id is required"
        )

    grouped = defaultdict(list)
    raw_event_count = 0
    invalid_pitcher_event_count = 0

    for row in events:
        raw_event_count += 1
        pitcher = _pitcher_id(
            _value(row, "pitcher_id")
        )

        if pitcher is None:
            invalid_pitcher_event_count += 1
            continue

        grouped[pitcher].append(row)

    metrics = tuple(sorted(
        CALIBRATED_POOLED_PSEUDO_COUNTS
    ))
    league_totals = {
        metric: {
            "successes": 0,
            "trials": 0,
        }
        for metric in metrics
    }
    pitcher_counts = {}
    requested_evidence = {}
    evidence_build_count = 0

    for pitcher in sorted(grouped):
        evidence = (
            build_canonical_pitcher_matchup_profile_evidence(
                grouped[pitcher],
                pitcher_id=pitcher,
                game_date=cutoff,
                window_days=days,
            )
        )
        evidence_build_count += 1
        overall = evidence.get("overall")
        rows = {}

        if isinstance(overall, Mapping):
            for metric in metrics:
                metric_counts = _counts(
                    overall,
                    metric,
                )
                if metric_counts is None:
                    continue

                successes, trials = metric_counts
                rows[metric] = {
                    "successes": successes,
                    "trials": trials,
                }
                league_totals[metric][
                    "successes"
                ] += successes
                league_totals[metric][
                    "trials"
                ] += trials

        pitcher_counts[pitcher] = rows

        if pitcher in requested:
            requested_evidence[pitcher] = (
                evidence
            )

    policy = calibrated_candidate_policy()
    candidates = {}

    for pitcher in requested:
        own_counts = pitcher_counts.get(
            pitcher,
            {},
        )
        priors = {}
        prior_diagnostics = {}

        for metric in metrics:
            total = league_totals[metric]
            own = own_counts.get(
                metric,
                {
                    "successes": 0,
                    "trials": 0,
                },
            )
            successes = (
                total["successes"]
                - own["successes"]
            )
            trials = (
                total["trials"]
                - own["trials"]
            )

            if trials > 0:
                prior = successes / trials
                priors[metric] = round(
                    prior,
                    12,
                )
                status = "ready"
                reasons = []
            else:
                status = "unavailable"
                reasons = [
                    "league_trials_unavailable"
                ]

            prior_diagnostics[metric] = {
                "status": status,
                "successes": successes,
                "trials": trials,
                "prior": priors.get(metric),
                "excluded_pitcher_id": pitcher,
                "reasons": reasons,
            }

        requested_evidence_present = (
            pitcher in requested_evidence
        )
        evidence = requested_evidence.get(
            pitcher,
            {
                "overall": {},
                "diagnostics": {
                    "status": "unavailable",
                    "reasons": [
                        "pitcher_evidence_unavailable",
                    ],
                    "evidence_digest": None,
                },
            },
        )
        application = (
            apply_canonical_pitcher_matchup_profile_calibration(
                evidence,
                calibration_policy=policy,
                league_priors=priors,
            )
        )

        evidence_diagnostics = dict(
            evidence.get("diagnostics") or {}
        )
        application_diagnostics = dict(
            application.get("diagnostics")
            or {}
        )

        explicit_evidence_status = (
            evidence_diagnostics.get("status")
        )

        if explicit_evidence_status:
            evidence_status = (
                explicit_evidence_status
            )
            evidence_status_source = (
                "explicit_evidence_diagnostics"
            )
        elif requested_evidence_present:
            evidence_status = "ready"
            evidence_status_source = (
                "single_pass_sufficient_statistics"
            )
            evidence_diagnostics.update({
                "status": "ready",
                "status_source": (
                    evidence_status_source
                ),
                "reasons": [],
                "evidence_digest": (
                    evidence_diagnostics.get(
                        "evidence_digest"
                    )
                ),
            })
        else:
            evidence_status = "unavailable"
            evidence_status_source = (
                "requested_pitcher_evidence_missing"
            )
            evidence_diagnostics.update({
                "status": "unavailable",
                "status_source": (
                    evidence_status_source
                ),
                "reasons": [
                    "pitcher_evidence_unavailable",
                ],
                "evidence_digest": None,
            })

        application_status = (
            application_diagnostics.get(
                "status"
            )
            or "unavailable"
        )
        prior_status = (
            "ready"
            if prior_diagnostics
            and all(
                row.get("status") == "ready"
                for row in (
                    prior_diagnostics.values()
                )
            )
            else "unavailable"
        )

        if application_status == "ready":
            candidate_status = "ready"
            activation_status = (
                "shadow_candidate_materialized"
            )
        elif application_status == "partial":
            candidate_status = "partial"
            activation_status = (
                "shadow_candidate_partial"
            )
        else:
            candidate_status = "unavailable"
            activation_status = (
                "shadow_candidate_unavailable"
            )

        candidate_blockers = []

        if evidence_status != "ready":
            candidate_blockers.append(
                "pitcher_evidence_unavailable"
            )

        if prior_status != "ready":
            candidate_blockers.append(
                "league_priors_unavailable"
            )

        metric_diagnostics = (
            application_diagnostics.get(
                "metric_diagnostics"
            )
            or {}
        )

        for metric_row in (
            metric_diagnostics.values()
        ):
            for reason in (
                metric_row.get("reasons")
                or ()
            ):
                if (
                    reason
                    not in candidate_blockers
                ):
                    candidate_blockers.append(
                        reason
                    )

        if (
            application_status == "partial"
            and "partial_calibrated_profile_rates"
            not in candidate_blockers
        ):
            candidate_blockers.append(
                "partial_calibrated_profile_rates"
            )

        if (
            application_status
            == "unavailable"
            and not candidate_blockers
        ):
            candidate_blockers.append(
                "calibrated_profile_unavailable"
            )

        diagnostics = {
            "schema_version": (
                RUNTIME_BATCH_VERSION
            ),
            "status": candidate_status,
            "pitcher_id": pitcher,
            "blockers": list(
                candidate_blockers
            ),
            "evidence_status": evidence_status,
            "evidence_status_source": (
                evidence_status_source
            ),
            "league_prior_status": prior_status,
            "application_status": (
                application_status
            ),
            "game_date": cutoff.isoformat(),
            "window_days": days,
            "cutoff_rule": (
                "events_strictly_before_game_date"
            ),
            "prior_scope": (
                "all_other_pitchers_in_window"
            ),
            "event_window_reused": True,
            "batch_evidence_pass": True,
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
                activation_status
            ),
            "evidence_digest": (
                evidence.get(
                    "diagnostics",
                    {},
                ).get("evidence_digest")
            ),
            "application_digest": (
                application["diagnostics"].get(
                    "application_digest"
                )
            ),
        }
        diagnostics[
            "runtime_candidate_digest"
        ] = _digest(diagnostics)

        candidates[str(pitcher)] = {
            "profile_rates": dict(
                application["profile_rates"]
            ),
            "diagnostics": diagnostics,
            "prior_diagnostics": (
                prior_diagnostics
            ),
            "league_prior_diagnostics": (
                prior_diagnostics
            ),
            "evidence_diagnostics": (
                evidence_diagnostics
            ),
            "application_diagnostics": (
                application_diagnostics
            ),
        }

    candidate_status_counts = {
        status: sum(
            1
            for candidate in candidates.values()
            if (
                candidate.get(
                    "diagnostics",
                    {},
                ).get("status")
                == status
            )
        )
        for status in (
            "ready",
            "partial",
            "unavailable",
        )
    }
    ready_candidate_count = (
        candidate_status_counts["ready"]
    )
    partial_candidate_count = (
        candidate_status_counts["partial"]
    )
    unavailable_candidate_count = (
        candidate_status_counts[
            "unavailable"
        ]
    )
    ready_candidate_coverage = (
        round(
            ready_candidate_count
            / len(candidates),
            12,
        )
        if candidates
        else 0.0
    )

    batch_diagnostics = {
        "schema_version": RUNTIME_BATCH_VERSION,
        "status": (
            "ready"
            if candidates
            else "unavailable"
        ),
        "game_date": cutoff.isoformat(),
        "window_days": days,
        "requested_pitcher_ids": list(
            requested
        ),
        "candidate_count": len(candidates),
        "ready_candidate_count": (
            ready_candidate_count
        ),
        "partial_candidate_count": (
            partial_candidate_count
        ),
        "unavailable_candidate_count": (
            unavailable_candidate_count
        ),
        "candidate_status_counts": dict(
            candidate_status_counts
        ),
        "ready_candidate_coverage": (
            ready_candidate_coverage
        ),
        "raw_event_count": raw_event_count,
        "candidate_pitcher_count": len(
            grouped
        ),
        "evidence_build_count": (
            evidence_build_count
        ),
        "invalid_pitcher_event_count": (
            invalid_pitcher_event_count
        ),
        "single_shared_evidence_pass": True,
        "production_authority": False,
        "production_authority_changed": False,
    }
    batch_diagnostics["batch_digest"] = (
        _digest(batch_diagnostics)
    )

    return {
        "candidates": candidates,
        "diagnostics": batch_diagnostics,
    }

"""Build cutoff-safe league priors for pitcher-profile shrinkage."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import math
from collections import defaultdict
from collections.abc import Iterable, Mapping
from typing import Any

from .canonical_pitcher_matchup_profile_evidence import (
    build_canonical_pitcher_matchup_profile_evidence,
)
from .canonical_pitcher_matchup_profile_holdout import (
    METRIC_SPECS,
)


LEAGUE_PRIOR_VERSION = (
    "canonical_pitcher_matchup_profile_league_prior_v1"
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


def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None

    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None

    if not math.isfinite(parsed):
        return None

    return parsed


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

    numerator = _number(
        component_values.get(numerator_key)
    )
    denominator = _number(
        denominators.get(metric)
    )

    if (
        numerator is None
        or denominator is None
        or numerator < 0
        or denominator <= 0
        or numerator > denominator
        or not numerator.is_integer()
        or not denominator.is_integer()
    ):
        return None

    return int(numerator), int(denominator)


def _digest(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def build_canonical_pitcher_matchup_profile_league_priors(
    events: Iterable[Any],
    *,
    game_date: dt.date | str,
    excluded_pitcher_id: int,
    window_days: int = 90,
    metrics: Iterable[str] | None = None,
) -> dict[str, Any]:
    """Build pregame league priors excluding the evaluated pitcher."""
    cutoff = _date(game_date)
    excluded = _pitcher_id(
        excluded_pitcher_id
    )
    days = int(window_days)

    if excluded is None:
        raise ValueError(
            "excluded_pitcher_id must be positive"
        )
    if days < 1:
        raise ValueError(
            "window_days must be positive"
        )

    selected_metrics = tuple(sorted(
        set(metrics or METRIC_SPECS)
    ))
    unknown_metrics = tuple(
        metric
        for metric in selected_metrics
        if metric not in METRIC_SPECS
    )

    if unknown_metrics:
        raise ValueError(
            "unknown metrics: "
            + ", ".join(unknown_metrics)
        )

    grouped = defaultdict(list)
    raw_event_count = 0
    excluded_event_count = 0
    invalid_pitcher_event_count = 0

    for row in events:
        raw_event_count += 1
        pitcher = _pitcher_id(
            _value(row, "pitcher_id")
        )

        if pitcher is None:
            invalid_pitcher_event_count += 1
            continue

        if pitcher == excluded:
            excluded_event_count += 1
            continue

        grouped[pitcher].append(row)

    totals = {
        metric: {
            "successes": 0,
            "trials": 0,
            "contributing_pitchers": 0,
        }
        for metric in selected_metrics
    }

    for pitcher in sorted(grouped):
        evidence = (
            build_canonical_pitcher_matchup_profile_evidence(
                grouped[pitcher],
                pitcher_id=pitcher,
                game_date=cutoff,
                window_days=days,
            )
        )
        overall = evidence.get("overall")

        if not isinstance(overall, Mapping):
            continue

        for metric in selected_metrics:
            row_counts = _counts(
                overall,
                metric,
            )
            if row_counts is None:
                continue

            successes, trials = row_counts
            totals[metric]["successes"] += (
                successes
            )
            totals[metric]["trials"] += trials
            totals[metric][
                "contributing_pitchers"
            ] += 1

    priors = {}
    metric_diagnostics = {}

    for metric in selected_metrics:
        total = totals[metric]
        trials = total["trials"]

        if trials > 0:
            prior = (
                total["successes"] / trials
            )
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

        metric_diagnostics[metric] = {
            "status": status,
            "successes": total["successes"],
            "trials": trials,
            "contributing_pitchers": (
                total["contributing_pitchers"]
            ),
            "prior": priors.get(metric),
            "reasons": reasons,
        }

    if not priors:
        status = "unavailable"
    elif len(priors) < len(selected_metrics):
        status = "partial"
    else:
        status = "ready"

    diagnostics = {
        "schema_version": LEAGUE_PRIOR_VERSION,
        "status": status,
        "game_date": cutoff.isoformat(),
        "window_days": days,
        "cutoff_rule": (
            "events_strictly_before_game_date"
        ),
        "prior_scope": (
            "all_other_pitchers_in_window"
        ),
        "excluded_pitcher_id": excluded,
        "raw_event_count": raw_event_count,
        "excluded_event_count": (
            excluded_event_count
        ),
        "invalid_pitcher_event_count": (
            invalid_pitcher_event_count
        ),
        "candidate_pitcher_count": len(grouped),
        "metric_diagnostics": (
            metric_diagnostics
        ),
        "production_authority": False,
        "production_authority_changed": False,
    }
    diagnostics["prior_digest"] = _digest(
        diagnostics
    )

    return {
        "league_priors": priors,
        "diagnostics": diagnostics,
    }

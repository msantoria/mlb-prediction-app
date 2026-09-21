"""Adapt canonical trial batches to the shadow payload boundary."""

from __future__ import annotations

from typing import Any, Dict

from mlb_app.simulation.game import (
    CanonicalTrialBatch,
)
from mlb_app.simulation.projections import (
    projection_payload_to_dict,
)


def canonical_trial_batch_to_shadow_payload(
    batch: CanonicalTrialBatch,
) -> Dict[str, Any]:
    """
    Serialize one canonical trial batch for shadow comparison.

    The existing canonical projection payload remains intact.
    Game-level outcomes and trial diagnostics are attached as
    additive, non-authoritative shadow fields.
    """

    if not isinstance(batch, CanonicalTrialBatch):
        raise TypeError(
            "batch must be a CanonicalTrialBatch"
        )

    payload = projection_payload_to_dict(
        batch.projections
    )

    outcomes = batch.outcomes

    payload["outcomes"] = {
        "simulation_count": (
            outcomes.simulation_count
        ),
        "away_win_probability": (
            outcomes.away_win_probability
        ),
        "home_win_probability": (
            outcomes.home_win_probability
        ),
        "tie_probability": (
            outcomes.tie_probability
        ),
        "extra_innings_probability": (
            outcomes.extra_innings_probability
        ),
        "walk_off_probability": (
            outcomes.walk_off_probability
        ),
        "away_run_distribution": {
            str(point.value): point.probability
            for point
            in outcomes.away_run_distribution
        },
        "home_run_distribution": {
            str(point.value): point.probability
            for point
            in outcomes.home_run_distribution
        },
        "total_run_distribution": {
            str(point.value): point.probability
            for point
            in outcomes.total_run_distribution
        },
        "team_total_probabilities": {
            metric.name: metric.probability
            for metric
            in outcomes.team_total_probabilities
        },
        "total_probabilities": {
            metric.name: metric.probability
            for metric
            in outcomes.total_probabilities
        },
    }

    payload["trial_diagnostics"] = {
        "game_validation_pass_rate": (
            batch.diagnostics
            .game_validation_pass_rate
        ),
        (
            "box_score_reconciliation_"
            "pass_rate"
        ): (
            batch.diagnostics
            .box_score_reconciliation_pass_rate
        ),
        "warnings": list(
            batch.diagnostics.warnings
        ),
        "defensive_event_authority": (
            batch.diagnostics
            .defensive_event_authority
            .to_diagnostics()
        ),
    }

    payload["shadow_metadata"] = {
        "source": "canonical_trial_batch",
        "authoritative": False,
        "authoritative_source": "legacy",
    }

    return payload

"""Execute the canonical pitcher-profile historical PA evaluation pipeline.

The executor composes realized outcome materialization, cutoff-safe probability
pairing, and historical scoring. It remains shadow-only and has no database or
production activation authority.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Iterable, Mapping

from mlb_app.simulation.shadow.canonical_pitcher_matchup_profile_pa_historical_evaluation import (
    evaluate_canonical_pitcher_matchup_profile_pa_history,
)
from mlb_app.simulation.shadow.canonical_pitcher_matchup_profile_pa_historical_outcomes import (
    materialize_canonical_pitcher_matchup_profile_pa_historical_outcomes,
)
from mlb_app.simulation.shadow.canonical_pitcher_matchup_profile_pa_historical_samples import (
    materialize_canonical_pitcher_matchup_profile_pa_historical_samples,
)
from mlb_app.simulation.shadow.historical_probability_statistics_source import (
    CanonicalHistoricalProbabilityStatisticsWindow,
)


SCHEMA_VERSION = (
    "canonical_pitcher_matchup_profile_pa_historical_executor_v1"
)


def _digest(value: Any) -> str:
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")

    return hashlib.sha256(
        encoded
    ).hexdigest()


def _mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    return {}


def _authority_contract(
    value: Any,
) -> bool:
    diagnostics = _mapping(value)

    return (
        diagnostics.get(
            "production_authority"
        )
        is False
        and diagnostics.get(
            "production_authority_changed"
        )
        is False
    )


def execute_canonical_pitcher_matchup_profile_pa_historical_evaluation(
    events: Iterable[Any],
    *,
    statistics: CanonicalHistoricalProbabilityStatisticsWindow,
    candidates_by_game_pitcher: Mapping[
        tuple[int, int],
        Mapping[str, Any],
    ],
    minimum_samples: int = 30,
    minimum_observed_pa: int = 1000,
    season_log_loss_regression_tolerance: float = 0.0,
) -> dict[str, Any]:
    """Execute the immutable paired historical PA evaluation."""
    outcomes = (
        materialize_canonical_pitcher_matchup_profile_pa_historical_outcomes(
            events
        )
    )

    paired = (
        materialize_canonical_pitcher_matchup_profile_pa_historical_samples(
            outcomes,
            statistics=statistics,
            candidates_by_game_pitcher=(
                candidates_by_game_pitcher
            ),
        )
    )

    evaluation = (
        evaluate_canonical_pitcher_matchup_profile_pa_history(
            paired["samples"],
            minimum_samples=minimum_samples,
            minimum_observed_pa=(
                minimum_observed_pa
            ),
            season_log_loss_regression_tolerance=(
                season_log_loss_regression_tolerance
            ),
        )
    )

    outcome_diagnostics = _mapping(
        outcomes.get("diagnostics")
    )
    paired_diagnostics = _mapping(
        paired.get("diagnostics")
    )
    evaluation_diagnostics = _mapping(
        evaluation.get("diagnostics")
    )

    authority_contracts = {
        "outcomes": _authority_contract(
            outcome_diagnostics
        ),
        "paired_samples": (
            _authority_contract(
                paired_diagnostics
            )
            and paired_diagnostics.get(
                "production_inputs_unchanged"
            )
            is True
        ),
        "evaluation": (
            _authority_contract(
                evaluation_diagnostics
            )
        ),
    }

    accepted_sample_count = int(
        evaluation_diagnostics.get(
            "accepted_sample_count",
            0,
        )
        or 0
    )

    if not all(authority_contracts.values()):
        status = "blocked"
        blockers = [
            "shadow_authority_contract_invalid"
        ]
    elif (
        accepted_sample_count > 0
        and outcome_diagnostics.get("status")
        == "ready"
        and paired_diagnostics.get("status")
        == "ready"
    ):
        status = "ready"
        blockers = []
    elif accepted_sample_count > 0:
        status = "partial"
        blockers = []
    else:
        status = "unavailable"
        blockers = [
            "no_evaluator_ready_historical_samples"
        ]

    diagnostics = {
        "schema_version": SCHEMA_VERSION,
        "status": status,
        "blockers": blockers,
        "raw_event_count": (
            outcome_diagnostics.get(
                "raw_row_count",
                0,
            )
        ),
        "terminal_pa_count": (
            outcome_diagnostics.get(
                "terminal_pa_count",
                0,
            )
        ),
        "outcome_sample_count": (
            outcome_diagnostics.get(
                "sample_count",
                0,
            )
        ),
        "paired_sample_count": (
            paired_diagnostics.get(
                "materialized_sample_count",
                0,
            )
        ),
        "accepted_sample_count": (
            accepted_sample_count
        ),
        "observed_pa": (
            _mapping(
                evaluation.get("overall")
            ).get("observed_pa", 0)
        ),
        "outcome_status": (
            outcome_diagnostics.get("status")
        ),
        "paired_sample_status": (
            paired_diagnostics.get("status")
        ),
        "evaluation_status": (
            evaluation_diagnostics.get(
                "status"
            )
        ),
        "evaluation_activation_status": (
            evaluation_diagnostics.get(
                "activation_status"
            )
        ),
        "authority_contracts": (
            authority_contracts
        ),
        "pipeline": (
            "terminal_outcomes_to_paired_samples_to_evaluation"
        ),
        "cutoff_policy": (
            "statistics_and_candidates_supplied_as_pregame_inputs"
        ),
        "database_accessed": False,
        "calibration_parameters_selected": False,
        "shadow_only": True,
        "production_inputs_unchanged": True,
        "production_authority": False,
        "production_authority_changed": False,
        "outcome_digest": (
            outcome_diagnostics.get(
                "outcome_digest"
            )
        ),
        "sample_digest": (
            paired_diagnostics.get(
                "sample_digest"
            )
        ),
        "evaluation_digest": (
            evaluation_diagnostics.get(
                "evaluation_digest"
            )
        ),
    }
    diagnostics["execution_digest"] = _digest({
        "diagnostics": diagnostics,
        "evaluation_overall": (
            evaluation.get("overall")
        ),
        "evaluation_by_season": (
            evaluation.get("by_season")
        ),
    })

    return {
        "outcomes": outcomes,
        "paired_samples": paired,
        "evaluation": evaluation,
        "diagnostics": diagnostics,
    }

import copy

import pytest

from mlb_app.simulation.shadow.canonical_pitcher_matchup_profile_pa_historical_evaluation import (
    OUTCOME_KEYS,
    evaluate_canonical_pitcher_matchup_profile_pa_history,
)


def probabilities(
    *,
    k,
    bb,
    single,
    double,
    triple,
    hr,
    hbp,
    reached_on_error,
):
    out = 1.0 - sum((
        k,
        bb,
        single,
        double,
        triple,
        hr,
        hbp,
        reached_on_error,
    ))

    return {
        "k": k,
        "bb": bb,
        "hbp": hbp,
        "single": single,
        "double": double,
        "triple": triple,
        "hr": hr,
        "reached_on_error": (
            reached_on_error
        ),
        "out": out,
    }


OBSERVED = {
    "k": 22,
    "bb": 8,
    "hbp": 1,
    "single": 14,
    "double": 4,
    "triple": 1,
    "hr": 4,
    "reached_on_error": 1,
    "out": 45,
}

PRODUCTION = probabilities(
    k=0.18,
    bb=0.08,
    hbp=0.01,
    single=0.12,
    double=0.035,
    triple=0.005,
    hr=0.025,
    reached_on_error=0.01,
)

CANDIDATE = probabilities(
    k=0.22,
    bb=0.08,
    hbp=0.01,
    single=0.14,
    double=0.04,
    triple=0.01,
    hr=0.04,
    reached_on_error=0.01,
)


def sample(
    index,
    *,
    season=2025,
    candidate=None,
):
    return {
        "season": season,
        "game_pk": 1000 + index,
        "comparison_id": f"sample-{index}",
        "production_probabilities": (
            dict(PRODUCTION)
        ),
        "candidate_probabilities": dict(
            candidate
            if candidate is not None
            else CANDIDATE
        ),
        "observed_counts": dict(OBSERVED),
    }


def evaluate(values):
    return (
        evaluate_canonical_pitcher_matchup_profile_pa_history(
            values,
            minimum_samples=2,
            minimum_observed_pa=100,
        )
    )


def test_candidate_improvement_passes_paired_gate():
    result = evaluate([
        sample(1, season=2024),
        sample(2, season=2025),
    ])
    diagnostics = result["diagnostics"]

    assert result["overall"][
        "absolute_log_loss_improvement"
    ] > 0
    assert result["overall"][
        "absolute_brier_improvement"
    ] > 0
    assert diagnostics[
        "selection_gate_passed"
    ] is True
    assert diagnostics[
        "activation_status"
    ] == "historical_pa_gate_passed"
    assert diagnostics["blockers"] == []
    assert diagnostics[
        "production_authority_changed"
    ] is False


def test_reports_exact_outcome_contract():
    assert OUTCOME_KEYS == (
        "k",
        "bb",
        "hbp",
        "single",
        "double",
        "triple",
        "hr",
        "reached_on_error",
        "out",
    )


def test_season_regression_blocks_selection():
    bad_candidate = probabilities(
        k=0.40,
        bb=0.03,
        hbp=0.01,
        single=0.06,
        double=0.02,
        triple=0.005,
        hr=0.01,
        reached_on_error=0.005,
    )

    result = evaluate([
        sample(1, season=2024),
        sample(
            2,
            season=2025,
            candidate=bad_candidate,
        ),
    ])

    assert result["diagnostics"][
        "selection_gate_passed"
    ] is False
    assert (
        "season_log_loss_instability"
        in result["diagnostics"][
            "blockers"
        ]
    )
    assert "2025" in result[
        "diagnostics"
    ]["regressed_seasons"]


def test_insufficient_sample_blocks_selection():
    result = (
        evaluate_canonical_pitcher_matchup_profile_pa_history(
            [sample(1)],
            minimum_samples=2,
            minimum_observed_pa=50,
        )
    )

    assert result["diagnostics"][
        "selection_gate_passed"
    ] is False
    assert (
        "insufficient_sample_count"
        in result["diagnostics"][
            "blockers"
        ]
    )


def test_invalid_distribution_is_rejected():
    invalid = sample(1)
    invalid[
        "candidate_probabilities"
    ]["k"] = 0.90

    result = (
        evaluate_canonical_pitcher_matchup_profile_pa_history(
            [invalid],
            minimum_samples=1,
            minimum_observed_pa=1,
        )
    )

    assert result["diagnostics"][
        "accepted_sample_count"
    ] == 0
    assert result["diagnostics"][
        "rejected_sample_count"
    ] == 1
    assert result["diagnostics"][
        "selection_gate_passed"
    ] is False


def test_duplicate_identity_is_rejected():
    first = sample(1)
    second = copy.deepcopy(first)

    result = (
        evaluate_canonical_pitcher_matchup_profile_pa_history(
            [first, second],
            minimum_samples=1,
            minimum_observed_pa=1,
        )
    )

    assert result["diagnostics"][
        "accepted_sample_count"
    ] == 1
    assert result["diagnostics"][
        "rejected_sample_count"
    ] == 1
    assert (
        "duplicate comparison identity"
        in result["rejected_samples"][0][
            "reason"
        ]
    )


def test_evaluation_is_deterministic_and_nonmutating():
    values = [
        sample(1, season=2024),
        sample(2, season=2025),
    ]
    original = copy.deepcopy(values)

    first = evaluate(values)
    second = evaluate(
        list(reversed(values))
    )

    assert values == original
    assert first["overall"] == second[
        "overall"
    ]
    assert first["by_season"] == second[
        "by_season"
    ]
    assert first["diagnostics"][
        "evaluation_digest"
    ] == second["diagnostics"][
        "evaluation_digest"
    ]


@pytest.mark.parametrize(
    "minimum_samples,minimum_pa",
    [
        (0, 1),
        (1, 0),
    ],
)
def test_thresholds_must_be_positive(
    minimum_samples,
    minimum_pa,
):
    with pytest.raises(ValueError):
        evaluate_canonical_pitcher_matchup_profile_pa_history(
            [sample(1)],
            minimum_samples=minimum_samples,
            minimum_observed_pa=minimum_pa,
        )

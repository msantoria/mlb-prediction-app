import copy

import pytest

from mlb_app.simulation.shadow.canonical_pitcher_matchup_profile_shrinkage import (
    CANONICAL_PITCHER_MATCHUP_PROFILE_SHRINKAGE_VERSION,
    calibrate_canonical_pitcher_matchup_profile_shrinkage,
)


def sample(
    *,
    season,
    training_successes,
    training_trials=20,
    holdout_successes=2,
    holdout_trials=20,
    prior_probability=0.10,
    metric="barrel_rate_allowed_approx",
    family="contact",
    segment="overall",
):
    return {
        "season": season,
        "training_successes": training_successes,
        "training_trials": training_trials,
        "holdout_successes": holdout_successes,
        "holdout_trials": holdout_trials,
        "prior_probability": prior_probability,
        "metric": metric,
        "family": family,
        "segment": segment,
    }


def test_strong_shrinkage_wins_for_noisy_small_samples():
    samples = [
        sample(
            season=2023,
            training_successes=18,
        ),
        sample(
            season=2024,
            training_successes=17,
        ),
        sample(
            season=2025,
            training_successes=19,
        ),
    ]

    result = (
        calibrate_canonical_pitcher_matchup_profile_shrinkage(
            samples,
            candidate_pseudo_counts=(0, 20, 100, 400),
        )
    )
    metric = result["metric_results"][
        "barrel_rate_allowed_approx"
    ]

    assert result["status"] == "ready"
    assert metric["pooled_candidate"][
        "pseudo_count"
    ] == 400.0


def test_no_shrinkage_wins_when_training_matches_holdout():
    samples = [
        sample(
            season=2023,
            training_successes=10,
            holdout_successes=10,
            prior_probability=0.05,
        ),
        sample(
            season=2024,
            training_successes=10,
            holdout_successes=10,
            prior_probability=0.05,
        ),
    ]

    result = (
        calibrate_canonical_pitcher_matchup_profile_shrinkage(
            samples,
            candidate_pseudo_counts=(0, 25, 100),
        )
    )

    assert result["metric_results"][
        "barrel_rate_allowed_approx"
    ]["pooled_candidate"]["pseudo_count"] == 0.0


def test_cross_season_folds_never_reselect_on_validation():
    samples = [
        sample(season=2023, training_successes=8),
        sample(season=2024, training_successes=7),
        sample(season=2025, training_successes=9),
    ]

    result = (
        calibrate_canonical_pitcher_matchup_profile_shrinkage(
            samples,
            candidate_pseudo_counts=(0, 25, 100),
        )
    )
    folds = result["metric_results"][
        "barrel_rate_allowed_approx"
    ]["cross_season_folds"]

    assert {
        fold["validation_season"]
        for fold in folds
    } == {2023, 2024, 2025}
    assert all(
        fold["candidate_reselected_on_validation"]
        is False
        for fold in folds
    )


def test_single_season_metric_is_blocked():
    result = (
        calibrate_canonical_pitcher_matchup_profile_shrinkage([
            sample(
                season=2025,
                training_successes=2,
            ),
        ])
    )

    assert result["status"] == "blocked"
    assert result["metric_results"][
        "barrel_rate_allowed_approx"
    ]["blockers"] == [
        "insufficient_cross_season_coverage",
    ]


def test_rejects_invalid_samples_without_mutating_input():
    samples = [
        sample(
            season=2023,
            training_successes=2,
        ),
        sample(
            season=2024,
            training_successes=30,
            training_trials=20,
        ),
    ]
    original = copy.deepcopy(samples)

    result = (
        calibrate_canonical_pitcher_matchup_profile_shrinkage(
            samples
        )
    )

    assert samples == original
    assert result["eligible_sample_count"] == 1
    assert result["rejected_sample_count"] == 1
    assert result["status"] == "blocked"


def test_segment_diagnostics_remain_separate():
    samples = [
        sample(
            season=2023,
            training_successes=2,
            segment="overall",
        ),
        sample(
            season=2024,
            training_successes=2,
            segment="overall",
        ),
        sample(
            season=2023,
            training_successes=3,
            segment="vsL",
        ),
        sample(
            season=2024,
            training_successes=3,
            segment="vsL",
        ),
    ]

    result = (
        calibrate_canonical_pitcher_matchup_profile_shrinkage(
            samples,
            candidate_pseudo_counts=(0, 25),
        )
    )
    segments = result["metric_results"][
        "barrel_rate_allowed_approx"
    ]["segment_diagnostics"]

    assert set(segments) == {"overall", "vsL"}
    assert segments["overall"]["sample_count"] == 2
    assert segments["vsL"]["sample_count"] == 2


def test_candidate_grid_validation():
    with pytest.raises(
        ValueError,
        match="must be unique",
    ):
        calibrate_canonical_pitcher_matchup_profile_shrinkage(
            [],
            candidate_pseudo_counts=(25, 25),
        )

    with pytest.raises(
        ValueError,
        match="nonnegative",
    ):
        calibrate_canonical_pitcher_matchup_profile_shrinkage(
            [],
            candidate_pseudo_counts=(-1, 25),
        )


def test_explicit_shadow_only_contract():
    result = (
        calibrate_canonical_pitcher_matchup_profile_shrinkage([
            sample(season=2023, training_successes=2),
            sample(season=2024, training_successes=2),
        ])
    )

    assert (
        CANONICAL_PITCHER_MATCHUP_PROFILE_SHRINKAGE_VERSION
        == "canonical_pitcher_matchup_profile_shrinkage_v1"
    )
    assert result["shadow_only"] is True
    assert result["production_authority_changed"] is False
    assert result["parameter_selected"] is False

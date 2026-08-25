import copy

import pytest

from mlb_app.simulation.shadow.canonical_pitcher_matchup_profile_application import (
    apply_canonical_pitcher_matchup_profile_calibration,
)


def evidence():
    return {
        "overall": {
            "discipline": {
                "strikeouts": 20,
                "unintentional_walks": 8,
            },
            "contact_quality": {
                "hard_hits": 30,
                "barrels_approx": 10,
            },
            "launch_angle_distribution": {
                "sweet_spot_batted_balls": 25,
                "ground_balls": 40,
                "line_drives": 20,
                "fly_balls": 30,
                "popups": 10,
            },
            "metric_denominators": {
                "k_rate": 100,
                "bb_rate": 100,
                "hard_hit_rate_allowed": 100,
                "barrel_rate_allowed_approx": 100,
                "sweet_spot_rate_allowed": 100,
                "ground_ball_rate": 100,
                "line_drive_rate": 100,
                "fly_ball_rate": 100,
                "popup_rate": 100,
            },
        },
    }


def policy():
    return {
        "status": "ready",
        "selected_pseudo_counts": {
            "k_rate": 100,
            "hard_hit_rate_allowed": 200,
            "ground_ball_rate": 50,
        },
        "blocked_metrics": {
            "bb_rate": [
                "cross_season_candidate_instability"
            ],
        },
        "segment_parameters_selected": False,
        "production_authority": False,
        "production_authority_changed": False,
    }


def priors():
    return {
        "k_rate": 0.22,
        "hard_hit_rate_allowed": 0.36,
        "ground_ball_rate": 0.43,
    }


def test_applies_exact_binomial_shrinkage():
    result = (
        apply_canonical_pitcher_matchup_profile_calibration(
            evidence(),
            calibration_policy=policy(),
            league_priors=priors(),
        )
    )

    assert result["profile_rates"]["k_rate"] == (
        (20 + 100 * 0.22) / 200
    )
    assert result["profile_rates"][
        "hard_hit_rate_allowed"
    ] == (
        (30 + 200 * 0.36) / 300
    )
    assert result["profile_rates"][
        "ground_ball_rate"
    ] == (
        (40 + 50 * 0.43) / 150
    )


def test_exposes_reliability_and_provenance():
    result = (
        apply_canonical_pitcher_matchup_profile_calibration(
            evidence(),
            calibration_policy=policy(),
            league_priors=priors(),
        )
    )

    row = result["diagnostics"][
        "metric_diagnostics"
    ]["k_rate"]

    assert row["successes"] == 20
    assert row["trials"] == 100
    assert row["observed_rate"] == 0.2
    assert row["league_prior"] == 0.22
    assert row["pseudo_count"] == 100
    assert row["reliability"] == 0.5
    assert row["production_authority"] is False


def test_blocked_walk_rate_is_not_applied():
    result = (
        apply_canonical_pitcher_matchup_profile_calibration(
            evidence(),
            calibration_policy=policy(),
            league_priors=priors(),
        )
    )

    assert "bb_rate" not in result["profile_rates"]
    assert result["diagnostics"][
        "blocked_metrics"
    ] == {
        "bb_rate": [
            "cross_season_candidate_instability"
        ],
    }


def test_missing_prior_fails_closed_per_metric():
    values = priors()
    del values["k_rate"]

    result = (
        apply_canonical_pitcher_matchup_profile_calibration(
            evidence(),
            calibration_policy=policy(),
            league_priors=values,
        )
    )

    assert "k_rate" not in result["profile_rates"]
    assert result["diagnostics"]["status"] == (
        "partial"
    )
    assert result["diagnostics"][
        "metric_diagnostics"
    ]["k_rate"]["reasons"] == [
        "league_prior_unavailable"
    ]


def test_zero_trials_returns_league_prior():
    values = evidence()
    values["overall"]["discipline"][
        "strikeouts"
    ] = 0
    values["overall"]["metric_denominators"][
        "k_rate"
    ] = 0

    result = (
        apply_canonical_pitcher_matchup_profile_calibration(
            values,
            calibration_policy=policy(),
            league_priors=priors(),
        )
    )

    row = result["diagnostics"][
        "metric_diagnostics"
    ]["k_rate"]

    assert result["profile_rates"]["k_rate"] == 0.22
    assert row["observed_rate"] is None
    assert row["reliability"] == 0.0


def test_segment_parameters_remain_inactive():
    result = (
        apply_canonical_pitcher_matchup_profile_calibration(
            evidence(),
            calibration_policy=policy(),
            league_priors=priors(),
        )
    )

    diagnostics = result["diagnostics"]

    assert (
        diagnostics["application_scope"]
        == "overall_pooled_metrics_only"
    )
    assert (
        diagnostics["segment_parameters_applied"]
        is False
    )
    assert (
        diagnostics["production_authority"]
        is False
    )
    assert (
        diagnostics["production_authority_changed"]
        is False
    )


def test_rejects_policy_with_production_authority():
    values = policy()
    values["production_authority"] = True

    with pytest.raises(
        ValueError,
        match="must not have production authority",
    ):
        apply_canonical_pitcher_matchup_profile_calibration(
            evidence(),
            calibration_policy=values,
            league_priors=priors(),
        )


def test_rejects_selected_segment_parameters():
    values = policy()
    values["segment_parameters_selected"] = True

    with pytest.raises(
        ValueError,
        match="must remain deferred",
    ):
        apply_canonical_pitcher_matchup_profile_calibration(
            evidence(),
            calibration_policy=values,
            league_priors=priors(),
        )


def test_application_is_deterministic_and_nonmutating():
    source = evidence()
    selected_policy = policy()
    league_values = priors()

    original_source = copy.deepcopy(source)
    original_policy = copy.deepcopy(
        selected_policy
    )
    original_priors = copy.deepcopy(
        league_values
    )

    first = (
        apply_canonical_pitcher_matchup_profile_calibration(
            source,
            calibration_policy=selected_policy,
            league_priors=league_values,
        )
    )
    second = (
        apply_canonical_pitcher_matchup_profile_calibration(
            source,
            calibration_policy=selected_policy,
            league_priors=league_values,
        )
    )

    assert first == second
    assert source == original_source
    assert selected_policy == original_policy
    assert league_values == original_priors

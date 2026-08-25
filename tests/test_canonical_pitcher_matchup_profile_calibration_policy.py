import copy

import pytest

from mlb_app.simulation.shadow.canonical_pitcher_matchup_profile_calibration_policy import (
    finalize_canonical_pitcher_matchup_profile_calibration,
)


def metric(
    selected,
    losses,
    *,
    season_spread=0,
):
    grid = [
        {
            "pseudo_count": candidate,
            "binomial_log_loss": loss,
        }
        for candidate, loss in losses
    ]
    selected_row = next(
        row
        for row in grid
        if row["pseudo_count"] == selected
    )

    return {
        "pooled_grid": grid,
        "pooled_candidate": selected_row,
        "cross_season_candidate_range": {
            "minimum": selected - season_spread,
            "maximum": selected,
            "spread": season_spread,
        },
    }


def artifact(results):
    return {
        "shadow_only": True,
        "parameter_selected": False,
        "production_authority_changed": False,
        "calibration": {
            "metric_results": results,
        },
    }


def test_selects_stable_interior_candidate():
    result = finalize_canonical_pitcher_matchup_profile_calibration(
        artifact({
            "k_rate": metric(
                100,
                [
                    (0, 0.54),
                    (50, 0.532),
                    (100, 0.530),
                    (200, 0.531),
                ],
            ),
        })
    )

    assert result["selected_pseudo_counts"] == {
        "k_rate": 100.0,
    }
    assert result["blocked_metrics"] == {}
    assert result["parameter_selected"] is True
    assert (
        result["production_authority_changed"]
        is False
    )


def test_accepts_stable_plateaued_boundary():
    result = finalize_canonical_pitcher_matchup_profile_calibration(
        artifact({
            "line_drive_rate": metric(
                1600,
                [
                    (0, 0.522),
                    (800, 0.5100),
                    (1200, 0.50991),
                    (1600, 0.509908),
                ],
            ),
        })
    )

    evaluation = result["metric_evaluations"][
        "line_drive_rate"
    ]

    assert evaluation["status"] == "selected"
    assert (
        evaluation["plateaued_boundary"]
        is True
    )


def test_blocks_unresolved_boundary():
    result = finalize_canonical_pitcher_matchup_profile_calibration(
        artifact({
            "metric": metric(
                400,
                [
                    (0, 0.60),
                    (200, 0.58),
                    (400, 0.575),
                ],
            ),
        })
    )

    assert result["selected_pseudo_counts"] == {}
    assert result["blocked_metrics"] == {
        "metric": [
            "unresolved_upper_grid_boundary"
        ],
    }


def test_blocks_cross_season_instability():
    result = finalize_canonical_pitcher_matchup_profile_calibration(
        artifact({
            "bb_rate": metric(
                200,
                [
                    (0, 0.29),
                    (100, 0.28),
                    (200, 0.275),
                    (400, 0.276),
                ],
                season_spread=100,
            ),
        })
    )

    assert result["blocked_metrics"] == {
        "bb_rate": [
            "cross_season_candidate_instability"
        ],
    }


def test_segment_parameters_remain_deferred():
    result = finalize_canonical_pitcher_matchup_profile_calibration(
        artifact({
            "k_rate": metric(
                100,
                [
                    (0, 0.54),
                    (100, 0.53),
                    (200, 0.531),
                ],
            ),
        })
    )

    assert (
        result["segment_parameters_selected"]
        is False
    )
    assert result["selection_scope"] == (
        "pooled_metrics_only"
    )
    assert result["production_authority"] is False


def test_rejects_non_shadow_artifact():
    payload = artifact({})
    payload["shadow_only"] = False

    with pytest.raises(
        ValueError,
        match="shadow-only",
    ):
        finalize_canonical_pitcher_matchup_profile_calibration(
            payload
        )


def test_rejects_artifact_with_prior_selection():
    payload = artifact({})
    payload["parameter_selected"] = True

    with pytest.raises(
        ValueError,
        match="already selected",
    ):
        finalize_canonical_pitcher_matchup_profile_calibration(
            payload
        )


def test_does_not_mutate_artifact():
    payload = artifact({
        "k_rate": metric(
            100,
            [
                (0, 0.54),
                (100, 0.53),
                (200, 0.531),
            ],
        ),
    })
    original = copy.deepcopy(payload)

    finalize_canonical_pitcher_matchup_profile_calibration(
        payload
    )

    assert payload == original

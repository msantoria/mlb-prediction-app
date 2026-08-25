import datetime as dt
from types import SimpleNamespace

import pytest

from mlb_app.simulation.shadow.canonical_pitcher_matchup_profile_holdout import (
    CANONICAL_PITCHER_MATCHUP_PROFILE_HOLDOUT_VERSION,
    materialize_canonical_pitcher_matchup_profile_holdouts,
)
from mlb_app.simulation.shadow.canonical_pitcher_matchup_profile_shrinkage import (
    calibrate_canonical_pitcher_matchup_profile_shrinkage,
)


def event(
    *,
    event_id,
    game_date,
    pitcher_id,
    batter_id,
    at_bat_number,
    events,
    stand="R",
    launch_speed=None,
    launch_angle=None,
):
    return SimpleNamespace(
        id=event_id,
        game_date=dt.date.fromisoformat(game_date),
        game_pk=(
            pitcher_id * 1000
            + int(game_date[-2:])
        ),
        at_bat_number=at_bat_number,
        pitch_number=1,
        pitcher_id=pitcher_id,
        batter_id=batter_id,
        events=events,
        description=(
            "hit_into_play"
            if launch_speed is not None
            else None
        ),
        launch_speed=launch_speed,
        launch_angle=launch_angle,
        estimated_woba_using_speedangle=None,
        estimated_ba_using_speedangle=None,
        stand=stand,
        p_throws="R",
    )


def rows():
    return [
        event(
            event_id=1,
            game_date="2023-06-01",
            pitcher_id=101,
            batter_id=201,
            at_bat_number=1,
            events="strikeout",
            stand="R",
        ),
        event(
            event_id=2,
            game_date="2023-06-02",
            pitcher_id=101,
            batter_id=202,
            at_bat_number=2,
            events="single",
            stand="L",
            launch_speed=100,
            launch_angle=20,
        ),
        event(
            event_id=3,
            game_date="2023-06-01",
            pitcher_id=102,
            batter_id=203,
            at_bat_number=1,
            events="field_out",
            stand="R",
            launch_speed=85,
            launch_angle=5,
        ),
        event(
            event_id=4,
            game_date="2023-06-02",
            pitcher_id=102,
            batter_id=204,
            at_bat_number=2,
            events="walk",
            stand="L",
        ),
        event(
            event_id=5,
            game_date="2023-07-01",
            pitcher_id=101,
            batter_id=205,
            at_bat_number=1,
            events="strikeout",
            stand="R",
        ),
        event(
            event_id=6,
            game_date="2023-07-02",
            pitcher_id=101,
            batter_id=206,
            at_bat_number=2,
            events="field_out",
            stand="L",
            launch_speed=90,
            launch_angle=5,
        ),
        event(
            event_id=7,
            game_date="2023-07-01",
            pitcher_id=102,
            batter_id=207,
            at_bat_number=1,
            events="field_out",
            stand="R",
            launch_speed=99,
            launch_angle=20,
        ),
        event(
            event_id=8,
            game_date="2023-07-02",
            pitcher_id=102,
            batter_id=208,
            at_bat_number=2,
            events="walk",
            stand="L",
        ),
    ]


def materialize(input_rows=None):
    return materialize_canonical_pitcher_matchup_profile_holdouts(
        rows() if input_rows is None else input_rows,
        cutoffs=("2023-07-01",),
        training_window_days=30,
        holdout_window_days=30,
    )


def sample_for(result, *, pitcher_id, metric, segment):
    return next(
        row
        for row in result["samples"]
        if (
            row["pitcher_id"] == pitcher_id
            and row["metric"] == metric
            and row["segment"] == segment
        )
    )


def test_materializes_strict_training_and_forward_holdout():
    result = materialize()
    sample = sample_for(
        result,
        pitcher_id=101,
        metric="k_rate",
        segment="overall",
    )

    assert result["status"] == "ready"
    assert sample["training_successes"] == 1
    assert sample["training_trials"] == 2
    assert sample["holdout_successes"] == 1
    assert sample["holdout_trials"] == 2
    assert sample["cutoff"] == "2023-07-01"
    assert (
        sample["holdout_end_exclusive"]
        == "2023-07-31"
    )


def test_prior_excludes_evaluated_pitcher():
    result = materialize()
    pitcher_101 = sample_for(
        result,
        pitcher_id=101,
        metric="k_rate",
        segment="overall",
    )
    pitcher_102 = sample_for(
        result,
        pitcher_id=102,
        metric="k_rate",
        segment="overall",
    )

    assert pitcher_101[
        "prior_successes_excluding_pitcher"
    ] == 0
    assert pitcher_101[
        "prior_trials_excluding_pitcher"
    ] == 2
    assert pitcher_101["prior_probability"] == 0.0

    assert pitcher_102[
        "prior_successes_excluding_pitcher"
    ] == 1
    assert pitcher_102[
        "prior_trials_excluding_pitcher"
    ] == 2
    assert pitcher_102["prior_probability"] == 0.5


def test_materializes_platoon_and_tto_segments():
    result = materialize()
    segments = {
        row["segment"]
        for row in result["samples"]
    }

    assert {"overall", "vsL", "vsR", "tto1"} <= segments


def test_thresholds_are_family_specific():
    result = (
        materialize_canonical_pitcher_matchup_profile_holdouts(
            rows(),
            cutoffs=("2023-07-01",),
            training_window_days=30,
            holdout_window_days=30,
            minimum_training_trials={
                "discipline": 2,
                "contact": 2,
                "launch_angle": 2,
            },
            minimum_holdout_trials={
                "discipline": 2,
                "contact": 2,
                "launch_angle": 2,
            },
        )
    )

    assert result["sample_count"] == 8
    assert {
        row["metric"]
        for row in result["samples"]
    } == {"k_rate", "bb_rate"}
    assert {
        row["segment"]
        for row in result["samples"]
    } == {"overall", "tto1"}
    assert {
        row["pitcher_id"]
        for row in result["samples"]
    } == {101, 102}


def test_output_is_accepted_by_shrinkage_calibrator():
    first_season = materialize()["samples"]
    second_season = [
        {
            **sample,
            "season": 2024,
            "cutoff": "2024-07-01",
        }
        for sample in first_season
    ]

    calibration = (
        calibrate_canonical_pitcher_matchup_profile_shrinkage(
            first_season + second_season,
            candidate_pseudo_counts=(0, 25),
        )
    )

    assert calibration["eligible_sample_count"] == (
        len(first_season) * 2
    )
    assert calibration["status"] == "ready"


def test_materialization_is_deterministic():
    first = materialize()
    second = materialize(list(reversed(rows())))

    assert first == second
    assert first["sample_digest"] == (
        second["sample_digest"]
    )


def test_empty_materialization_is_blocked():
    result = materialize([])

    assert result["status"] == "blocked"
    assert result["sample_count"] == 0
    assert result["production_authority_changed"] is False


def test_invalid_windows_and_cutoffs_are_rejected():
    with pytest.raises(
        ValueError,
        match="at least one cutoff",
    ):
        materialize_canonical_pitcher_matchup_profile_holdouts(
            rows(),
            cutoffs=(),
        )

    with pytest.raises(
        ValueError,
        match="must be positive",
    ):
        materialize_canonical_pitcher_matchup_profile_holdouts(
            rows(),
            cutoffs=("2023-07-01",),
            training_window_days=0,
        )


def test_explicit_shadow_only_contract():
    result = materialize()

    assert (
        CANONICAL_PITCHER_MATCHUP_PROFILE_HOLDOUT_VERSION
        == "canonical_pitcher_matchup_profile_holdout_v1"
    )
    assert result["shadow_only"] is True
    assert result["production_authority_changed"] is False
    assert result["parameter_selected"] is False

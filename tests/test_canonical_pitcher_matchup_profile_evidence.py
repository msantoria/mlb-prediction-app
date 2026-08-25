import datetime as dt
from types import SimpleNamespace

from mlb_app.simulation.shadow.canonical_pitcher_matchup_profile_evidence import (
    CANONICAL_PITCHER_MATCHUP_PROFILE_EVIDENCE_VERSION,
    build_canonical_pitcher_matchup_profile_evidence,
)


def event(
    *,
    event_id,
    game_date="2026-08-22",
    game_pk=1,
    at_bat_number=1,
    pitch_number=1,
    pitcher_id=101,
    batter_id=201,
    events=None,
    description=None,
    launch_speed=None,
    launch_angle=None,
    xwoba=None,
    xba=None,
    stand="R",
):
    return SimpleNamespace(
        id=event_id,
        game_date=dt.date.fromisoformat(game_date),
        game_pk=game_pk,
        at_bat_number=at_bat_number,
        pitch_number=pitch_number,
        pitcher_id=pitcher_id,
        batter_id=batter_id,
        events=events,
        description=description,
        launch_speed=launch_speed,
        launch_angle=launch_angle,
        estimated_woba_using_speedangle=xwoba,
        estimated_ba_using_speedangle=xba,
        stand=stand,
        p_throws="R",
    )


def build(events):
    return build_canonical_pitcher_matchup_profile_evidence(
        events,
        pitcher_id=101,
        game_date="2026-08-23",
    )


def contact_sample():
    return [
        event(
            event_id=1,
            at_bat_number=1,
            batter_id=201,
            events="single",
            description="hit_into_play",
            launch_speed=100,
            launch_angle=20,
            xwoba=0.70,
            xba=0.80,
            stand="R",
        ),
        event(
            event_id=2,
            at_bat_number=2,
            batter_id=202,
            events="field_out",
            description="hit_into_play",
            launch_speed=90,
            launch_angle=5,
            xwoba=0.10,
            xba=0.12,
            stand="L",
        ),
        event(
            event_id=3,
            at_bat_number=3,
            batter_id=203,
            events="field_out",
            description="hit_into_play",
            launch_speed=96,
            launch_angle=30,
            xwoba=0.35,
            xba=0.28,
            stand="R",
        ),
        event(
            event_id=4,
            at_bat_number=4,
            batter_id=204,
            events="field_out",
            description="hit_into_play",
            launch_speed=85,
            launch_angle=55,
            xwoba=0.02,
            xba=0.01,
            stand="L",
        ),
    ]


def test_builds_contact_quality_and_launch_distribution():
    result = build(contact_sample())
    overall = result["overall"]

    assert result["status"] == "ready"
    assert overall["sample_size"][
        "plate_appearances"
    ] == 4
    assert overall["sample_size"]["batted_balls"] == 4
    assert overall["contact_quality"][
        "hard_hit_rate_allowed"
    ] == 0.5
    assert overall["contact_quality"][
        "barrel_rate_allowed_approx"
    ] == 0.25
    assert overall["contact_quality"][
        "median_exit_velocity_allowed"
    ] == 93.0

    distribution = overall[
        "launch_angle_distribution"
    ]
    assert distribution["ground_ball_rate"] == 0.25
    assert distribution["line_drive_rate"] == 0.25
    assert distribution["fly_ball_rate"] == 0.25
    assert distribution["popup_rate"] == 0.25
    assert distribution["sweet_spot_rate_allowed"] == 0.5


def test_builds_platoon_splits_with_exact_denominators():
    result = build(contact_sample())

    versus_left = result["platoon_splits"]["L"]
    versus_right = result["platoon_splits"]["R"]

    assert versus_left["sample_size"][
        "plate_appearances"
    ] == 2
    assert versus_right["sample_size"][
        "plate_appearances"
    ] == 2
    assert versus_left["contact_quality"][
        "avg_exit_velocity_allowed"
    ] == 87.5
    assert versus_right["contact_quality"][
        "avg_exit_velocity_allowed"
    ] == 98.0


def test_builds_times_through_order_splits():
    rows = [
        event(
            event_id=1,
            at_bat_number=1,
            batter_id=201,
            events="strikeout",
        ),
        event(
            event_id=2,
            at_bat_number=10,
            batter_id=201,
            events="walk",
        ),
        event(
            event_id=3,
            at_bat_number=19,
            batter_id=201,
            events="single",
            launch_speed=100,
            launch_angle=20,
        ),
        event(
            event_id=4,
            at_bat_number=28,
            batter_id=201,
            events="field_out",
            launch_speed=90,
            launch_angle=5,
        ),
    ]

    result = build(rows)
    splits = result["times_through_order_splits"]

    assert splits["1"]["discipline"]["k_rate"] == 1.0
    assert splits["2"]["discipline"]["bb_rate"] == 1.0
    assert splits["3_plus"]["sample_size"][
        "plate_appearances"
    ] == 2
    assert splits["3_plus"]["sample_size"][
        "batted_balls"
    ] == 2


def test_excludes_same_day_future_and_old_evidence():
    rows = [
        event(
            event_id=1,
            game_date="2026-08-22",
            events="strikeout",
        ),
        event(
            event_id=2,
            game_date="2026-08-23",
            events="walk",
        ),
        event(
            event_id=3,
            game_date="2026-08-24",
            events="walk",
        ),
        event(
            event_id=4,
            game_date="2026-05-01",
            events="walk",
        ),
    ]

    result = build(rows)

    assert result["overall"]["sample_size"][
        "plate_appearances"
    ] == 1
    assert result["overall"]["discipline"][
        "k_rate"
    ] == 1.0


def test_deduplicates_pitch_identity():
    row = event(
        event_id=1,
        events="strikeout",
    )
    duplicate = event(
        event_id=2,
        events="strikeout",
    )

    result = build([row, duplicate])

    assert result["diagnostics"]["raw_event_count"] == 2
    assert result["diagnostics"][
        "deduped_pitch_count"
    ] == 1
    assert result["diagnostics"][
        "duplicate_pitch_count"
    ] == 1
    assert result["overall"]["sample_size"][
        "plate_appearances"
    ] == 1


def test_empty_evidence_fails_closed():
    result = build([])

    assert result["status"] == "unavailable"
    assert result["overall"]["sample_size"][
        "plate_appearances"
    ] == 0
    assert result["diagnostics"][
        "production_authority"
    ] is False
    assert result["diagnostics"][
        "activation_status"
    ] == "evidence_only_pending_calibration"


def test_result_is_deterministic():
    rows = contact_sample()

    first = build(rows)
    second = build(list(reversed(rows)))

    assert first == second
    assert first["diagnostics"]["evidence_digest"] == (
        second["diagnostics"]["evidence_digest"]
    )


def test_explicit_schema_and_classification_contract():
    result = build(contact_sample())

    assert (
        CANONICAL_PITCHER_MATCHUP_PROFILE_EVIDENCE_VERSION
        == "canonical_pitcher_matchup_profile_evidence_v1"
    )
    assert result["classification"][
        "official_statcast_classification"
    ] is False
    assert result["classification"][
        "source"
    ] == "internal_launch_angle_classification_v1"
    assert result["diagnostics"][
        "shrinkage_applied"
    ] is False


def test_other_pitchers_are_excluded():
    rows = [
        event(
            event_id=1,
            pitcher_id=101,
            events="strikeout",
        ),
        event(
            event_id=2,
            pitcher_id=999,
            events="walk",
        ),
    ]

    result = build(rows)

    assert result["overall"]["sample_size"][
        "plate_appearances"
    ] == 1
    assert result["overall"]["discipline"][
        "k_rate"
    ] == 1.0


def test_missing_launch_angle_is_not_counted_as_non_barrel():
    rows = [
        event(
            event_id=1,
            at_bat_number=1,
            batter_id=201,
            events="single",
            launch_speed=100,
            launch_angle=20,
        ),
        event(
            event_id=2,
            at_bat_number=2,
            batter_id=202,
            events="field_out",
            launch_speed=100,
            launch_angle=None,
        ),
    ]

    result = build(rows)
    overall = result["overall"]

    assert overall["sample_size"]["batted_balls"] == 2
    assert overall["sample_size"][
        "barrel_eligible_batted_balls"
    ] == 1
    assert overall["contact_quality"][
        "barrel_rate_allowed_approx"
    ] == 1.0


def test_discipline_only_evidence_is_partial():
    result = build([
        event(
            event_id=1,
            events="strikeout",
            launch_speed=None,
            launch_angle=None,
        ),
    ])

    assert result["status"] == "partial"
    assert result["overall"]["sample_size"][
        "plate_appearances"
    ] == 1
    assert result["overall"]["sample_size"][
        "batted_balls"
    ] == 0


def test_legacy_tto_encounters_reset_by_date():
    rows = [
        event(
            event_id=1,
            game_date="2026-08-21",
            game_pk=None,
            at_bat_number=None,
            batter_id=201,
            events="strikeout",
        ),
        event(
            event_id=2,
            game_date="2026-08-22",
            game_pk=None,
            at_bat_number=None,
            batter_id=201,
            events="strikeout",
        ),
    ]

    result = build(rows)
    splits = result["times_through_order_splits"]

    assert splits["1"]["sample_size"][
        "plate_appearances"
    ] == 2
    assert splits["2"]["sample_size"][
        "plate_appearances"
    ] == 0
    assert splits["3_plus"]["sample_size"][
        "plate_appearances"
    ] == 0


def test_barrel_denominator_is_explicit():
    result = build(contact_sample())

    assert result["classification"][
        "barrel_denominator"
    ] == (
        "batted balls with exit velocity and launch angle"
    )


def test_launch_distribution_exposes_exact_numerators():
    result = build(contact_sample())
    distribution = result["overall"][
        "launch_angle_distribution"
    ]

    assert distribution[
        "sweet_spot_batted_balls"
    ] == 2
    assert distribution["ground_balls"] == 1
    assert distribution["line_drives"] == 1
    assert distribution["fly_balls"] == 1
    assert distribution["popups"] == 1

    classified = result["overall"]["sample_size"][
        "launch_angle_batted_balls"
    ]
    classified_sum = sum(
        distribution[key]
        for key in (
            "ground_balls",
            "line_drives",
            "fly_balls",
            "popups",
        )
    )

    assert classified_sum == classified


def test_metric_denominators_are_explicit():
    result = build(contact_sample())
    denominators = result["overall"][
        "metric_denominators"
    ]

    assert denominators == {
        "k_rate": 4,
        "bb_rate": 4,
        "hard_hit_rate_allowed": 4,
        "barrel_rate_allowed_approx": 4,
        "sweet_spot_rate_allowed": 4,
        "ground_ball_rate": 4,
        "line_drive_rate": 4,
        "fly_ball_rate": 4,
        "popup_rate": 4,
        "avg_exit_velocity_allowed": 4,
        "median_exit_velocity_allowed": 4,
        "p90_exit_velocity_allowed": 4,
        "max_exit_velocity_allowed": 4,
        "avg_launch_angle_allowed": 4,
        "xwoba_allowed": 4,
        "xba_allowed": 4,
    }


def test_empty_segment_has_zero_denominators():
    result = build(contact_sample())
    empty = result["times_through_order_splits"][
        "3_plus"
    ]

    assert all(
        denominator == 0
        for denominator in empty[
            "metric_denominators"
        ].values()
    )

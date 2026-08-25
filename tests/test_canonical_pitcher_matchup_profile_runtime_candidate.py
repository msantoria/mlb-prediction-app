import copy

from mlb_app.simulation.shadow.canonical_pitcher_matchup_profile_runtime_candidate import (
    CALIBRATED_POOLED_PSEUDO_COUNTS,
    build_canonical_pitcher_matchup_profile_runtime_candidate,
    calibrated_candidate_policy,
)


def event(
    *,
    event_id,
    pitcher_id,
    events="field_out",
    description="hit_into_play",
    launch_speed=90,
    launch_angle=5,
    game_date="2026-08-22",
):
    return {
        "id": event_id,
        "game_pk": 500,
        "at_bat_number": event_id,
        "pitch_number": 1,
        "pitcher_id": pitcher_id,
        "batter_id": 1000 + event_id,
        "game_date": game_date,
        "events": events,
        "description": description,
        "launch_speed": launch_speed,
        "launch_angle": launch_angle,
        "stand": "R",
    }


def rows():
    return [
        event(
            event_id=1,
            pitcher_id=101,
            events="strikeout",
            description="swinging_strike",
            launch_speed=None,
            launch_angle=None,
        ),
        event(
            event_id=2,
            pitcher_id=101,
            launch_speed=100,
            launch_angle=20,
        ),
        event(
            event_id=3,
            pitcher_id=102,
            events="strikeout",
            description="swinging_strike",
            launch_speed=None,
            launch_angle=None,
        ),
        event(
            event_id=4,
            pitcher_id=102,
            launch_speed=90,
            launch_angle=5,
        ),
        event(
            event_id=5,
            pitcher_id=103,
            launch_speed=99,
            launch_angle=28,
        ),
    ]


def build(values=None):
    return (
        build_canonical_pitcher_matchup_profile_runtime_candidate(
            rows() if values is None else values,
            pitcher_id=101,
            game_date="2026-08-23",
        )
    )


def test_materializes_all_selected_pooled_metrics():
    result = build()

    assert set(result["profile_rates"]) == set(
        CALIBRATED_POOLED_PSEUDO_COUNTS
    )
    assert result["diagnostics"]["status"] == (
        "ready"
    )


def test_walk_rate_remains_blocked():
    result = build()

    assert "bb_rate" not in result[
        "profile_rates"
    ]
    assert result["diagnostics"][
        "blocked_metrics"
    ] == {
        "bb_rate": [
            "cross_season_candidate_instability"
        ],
    }


def test_candidate_has_no_production_authority():
    result = build()
    diagnostics = result["diagnostics"]

    assert (
        diagnostics["production_authority"]
        is False
    )
    assert (
        diagnostics["production_authority_changed"]
        is False
    )
    assert (
        diagnostics["activation_status"]
        == "shadow_candidate_materialized"
    )
    assert (
        diagnostics["segment_parameters_applied"]
        is False
    )


def test_league_prior_excludes_target_pitcher():
    result = build()

    prior = result[
        "league_prior_diagnostics"
    ]

    assert prior["excluded_pitcher_id"] == 101
    assert prior["excluded_event_count"] == 2


def test_same_event_window_drives_all_components():
    result = build()
    diagnostics = result["diagnostics"]

    assert diagnostics["event_window_reused"] is True
    assert diagnostics["evidence_digest"]
    assert diagnostics["prior_digest"]
    assert diagnostics["application_digest"]


def test_candidate_policy_is_immutable_by_copy():
    first = calibrated_candidate_policy()
    first["selected_pseudo_counts"][
        "k_rate"
    ] = 999

    second = calibrated_candidate_policy()

    assert second["selected_pseudo_counts"][
        "k_rate"
    ] == 100.0


def test_result_is_deterministic_and_nonmutating():
    values = rows()
    original = copy.deepcopy(values)

    first = build(values)
    second = build(
        list(reversed(values))
    )

    assert first == second
    assert values == original

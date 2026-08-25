import copy

from mlb_app.simulation.shadow.canonical_pitcher_matchup_profile_runtime_batch import (
    build_canonical_pitcher_matchup_profile_runtime_batch,
)


def event(
    event_id,
    pitcher_id,
    *,
    events="field_out",
    description="hit_into_play",
    launch_speed=90,
    launch_angle=5,
):
    return {
        "id": event_id,
        "game_pk": 500,
        "at_bat_number": event_id,
        "pitch_number": 1,
        "pitcher_id": pitcher_id,
        "batter_id": 1000 + event_id,
        "game_date": "2026-08-22",
        "events": events,
        "description": description,
        "launch_speed": launch_speed,
        "launch_angle": launch_angle,
        "stand": "R",
    }


def rows():
    return [
        event(
            1,
            101,
            events="strikeout",
            description="swinging_strike",
            launch_speed=None,
            launch_angle=None,
        ),
        event(2, 101, launch_speed=100, launch_angle=20),
        event(
            3,
            102,
            events="strikeout",
            description="swinging_strike",
            launch_speed=None,
            launch_angle=None,
        ),
        event(4, 102, launch_speed=90, launch_angle=5),
        event(5, 103, launch_speed=99, launch_angle=28),
    ]


def build(values=None):
    return (
        build_canonical_pitcher_matchup_profile_runtime_batch(
            rows() if values is None else values,
            pitcher_ids=(101, 102),
            game_date="2026-08-23",
        )
    )


def test_builds_all_requested_candidates():
    result = build()

    assert set(result["candidates"]) == {
        "101",
        "102",
    }
    assert result["diagnostics"][
        "candidate_count"
    ] == 2


def test_builds_each_pitcher_evidence_once():
    result = build()
    diagnostics = result["diagnostics"]

    assert diagnostics[
        "candidate_pitcher_count"
    ] == 3
    assert diagnostics[
        "evidence_build_count"
    ] == 3
    assert diagnostics[
        "single_shared_evidence_pass"
    ] is True


def test_priors_exclude_each_target_pitcher():
    result = build()

    first = result["candidates"]["101"][
        "prior_diagnostics"
    ]["k_rate"]
    second = result["candidates"]["102"][
        "prior_diagnostics"
    ]["k_rate"]

    assert first["excluded_pitcher_id"] == 101
    assert second["excluded_pitcher_id"] == 102
    assert first["trials"] == 3
    assert second["trials"] == 3


def test_candidates_remain_shadow_only():
    result = build()

    for candidate in result[
        "candidates"
    ].values():
        diagnostics = candidate["diagnostics"]

        assert (
            diagnostics["production_authority"]
            is False
        )
        assert (
            diagnostics[
                "production_authority_changed"
            ]
            is False
        )
        assert (
            diagnostics[
                "segment_parameters_applied"
            ]
            is False
        )


def test_missing_requested_pitcher_fails_closed():
    result = (
        build_canonical_pitcher_matchup_profile_runtime_batch(
            rows(),
            pitcher_ids=(999,),
            game_date="2026-08-23",
        )
    )

    candidate = result["candidates"]["999"]

    assert candidate["profile_rates"] == {}
    assert candidate["diagnostics"]["status"] == (
        "unavailable"
    )


def test_batch_is_deterministic_and_nonmutating():
    values = rows()
    original = copy.deepcopy(values)

    first = build(values)
    second = build(
        list(reversed(values))
    )

    assert first == second
    assert values == original

def test_missing_requested_pitcher_reports_explicit_unavailable_telemetry():
    result = (
        build_canonical_pitcher_matchup_profile_runtime_batch(
            rows(),
            pitcher_ids=(999,),
            game_date="2026-08-23",
        )
    )
    candidate = result["candidates"]["999"]
    diagnostics = candidate["diagnostics"]
    batch = result["diagnostics"]

    assert diagnostics["status"] == (
        "unavailable"
    )
    assert diagnostics["activation_status"] == (
        "shadow_candidate_unavailable"
    )
    assert diagnostics["evidence_status"] == (
        "unavailable"
    )
    assert diagnostics["league_prior_status"] == (
        "ready"
    )
    assert diagnostics["application_status"] == (
        "unavailable"
    )
    assert (
        "pitcher_evidence_unavailable"
        in diagnostics["blockers"]
    )
    assert (
        "sufficient_statistics_unavailable"
        in diagnostics["blockers"]
    )
    assert candidate["evidence_diagnostics"][
        "status"
    ] == "unavailable"
    assert (
        candidate["league_prior_diagnostics"]
        == candidate["prior_diagnostics"]
    )
    assert candidate[
        "application_diagnostics"
    ]["status"] == "unavailable"

    assert batch["candidate_count"] == 1
    assert batch["ready_candidate_count"] == 0
    assert batch["partial_candidate_count"] == 0
    assert (
        batch["unavailable_candidate_count"]
        == 1
    )
    assert batch["candidate_status_counts"] == {
        "ready": 0,
        "partial": 0,
        "unavailable": 1,
    }
    assert batch[
        "ready_candidate_coverage"
    ] == 0.0
    assert batch[
        "production_authority_changed"
    ] is False


def test_ready_candidates_report_materialized_telemetry():
    result = build()
    batch = result["diagnostics"]

    assert batch["candidate_count"] == 2
    assert batch["ready_candidate_count"] == 2
    assert batch["partial_candidate_count"] == 0
    assert (
        batch["unavailable_candidate_count"]
        == 0
    )
    assert batch[
        "ready_candidate_coverage"
    ] == 1.0

    for candidate in result[
        "candidates"
    ].values():
        diagnostics = candidate["diagnostics"]

        assert diagnostics["status"] == "ready"
        assert diagnostics[
            "activation_status"
        ] == "shadow_candidate_materialized"
        assert diagnostics[
            "evidence_status"
        ] in {"ready", "partial"}
        assert diagnostics[
            "league_prior_status"
        ] == "ready"
        assert diagnostics[
            "application_status"
        ] == "ready"
        assert diagnostics["blockers"] == []
        assert candidate[
            "evidence_diagnostics"
        ]["status"] in {"ready", "partial"}
        assert (
            candidate[
                "league_prior_diagnostics"
            ]
            == candidate[
                "prior_diagnostics"
            ]
        )

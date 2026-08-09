from copy import deepcopy

import pytest

from mlb_app.simulation.shadow.canonical_pitcher_projection_pool_and_workload_calibration import (
    SCHEMA_VERSION,
    audit_canonical_pitcher_projection_pool_and_workload_calibration,
)


def metric(
    *,
    count=100,
    mean=0,
    median=0,
    p10=0,
    p25=0,
    p75=0,
    p90=0,
    minimum=0,
    maximum=0,
):
    return {
        "count": count,
        "mean": mean,
        "median": median,
        "p10": p10,
        "p25": p25,
        "p75": p75,
        "p90": p90,
        "minimum": minimum,
        "maximum": maximum,
    }


def projections():
    return {
        "schema_version":
            "canonical_player_projection_rows_v1",
        "simulation_count": 100,
        "players": [
            {
                "player_id": "100",
                "team_side": "away",
                "player_type": "pitcher",
                "pitcher_role": "starter",
                "pitcher_role_resolution_status":
                    "resolved",
                "metrics": {
                    "outs_recorded": metric(
                        mean=15,
                        median=17,
                        p10=8,
                        p25=12,
                        p75=19,
                        p90=20,
                        minimum=0,
                        maximum=23,
                    ),
                },
            },
            {
                "player_id": "101",
                "team_side": "away",
                "player_type": "pitcher",
                "pitcher_role": "reliever",
                "pitcher_role_resolution_status":
                    "resolved",
                "metrics": {
                    "outs_recorded": metric(
                        mean=0.9,
                        median=0,
                        p10=0,
                        p25=0,
                        p75=0,
                        p90=3,
                        minimum=0,
                        maximum=4,
                    ),
                },
            },
            {
                "player_id": "102",
                "team_side": "away",
                "player_type": "pitcher",
                "pitcher_role": "reliever",
                "pitcher_role_resolution_status":
                    "resolved",
                "metrics": {
                    "outs_recorded": metric(
                        mean=0.6,
                        median=0,
                        p10=0,
                        p25=0,
                        p75=0,
                        p90=3,
                        minimum=0,
                        maximum=3,
                    ),
                },
            },
        ],
    }


def appearance_audit():
    records = []

    for trial_index in range(100):
        records.append({
            "trial_index": trial_index,
            "team_side": "away",
            "pitcher_id": "100",
            "appearance_index": 0,
            "planned_role": "starter",
            "actual_role": "first_pitcher",
            "outs_recorded": (
                15
                if trial_index < 50
                else 20
            ),
        })

    for trial_index, outs in (
        (1, 3),
        (5, 3),
        (9, 4),
        (20, 2),
        (40, 3),
        (60, 3),
        (80, 3),
        (95, 3),
    ):
        records.append({
            "trial_index": trial_index,
            "team_side": "away",
            "pitcher_id": "101",
            "appearance_index": 1,
            "planned_role": "reliever",
            "actual_role": "reliever",
            "outs_recorded": outs,
        })

    return {
        "schema_version":
            "canonical_pitcher_appearance_"
            "sequence_audit_v1",
        "status": "observed",
        "trial_count": 100,
        "records": records,
    }


def bullpen_discovery():
    return {
        "away": {
            "starter_id": "100",
            "bullpen_pitcher_ids": [
                "101",
                "102",
            ],
            "eligibility": {
                "schema_version":
                    "canonical_bullpen_eligibility_v1",
                "records": [
                    {
                        "pitcher_id": "101",
                        "retained": True,
                        "decision_reason":
                            "explicitly_eligible",
                        "planned_pitcher": False,
                        "evidence_present": True,
                        "evidence_valid": True,
                        "evidence_status":
                            "eligible",
                        "pitcher_role":
                            "starter",
                        "evidence_source":
                            "depth_chart",
                    },
                    {
                        "pitcher_id": "102",
                        "retained": True,
                        "decision_reason":
                            "explicitly_eligible",
                        "planned_pitcher": False,
                        "evidence_present": True,
                        "evidence_valid": True,
                        "evidence_status":
                            "eligible",
                        "pitcher_role":
                            "closer",
                        "evidence_source":
                            "depth_chart",
                    },
                ],
            },
        },
        "home": {
            "starter_id": "200",
            "bullpen_pitcher_ids": [],
            "eligibility": {
                "records": [],
            },
        },
    }


def run():
    return (
        audit_canonical_pitcher_projection_pool_and_workload_calibration(
            projections=projections(),
            appearance_audit=appearance_audit(),
            bullpen_discovery=bullpen_discovery(),
        )
    )


def pitcher(result, pitcher_id):
    return next(
        row
        for row in result["pitchers"]
        if row["pitcher_id"] == pitcher_id
    )


def test_reports_observed_read_only_audit():
    result = run()

    assert result["schema_version"] == SCHEMA_VERSION
    assert result["status"] == "observed"
    assert result["audited"] is True
    assert result["trial_count"] == 100
    assert result["pitcher_projection_count"] == 3
    assert result["database_writes_performed"] is False
    assert result["production_authority_changed"] is False
    assert result["safety_checks"] == {
        "projection_values_unchanged": True,
        "pitcher_pools_unchanged": True,
        "pitching_plans_unchanged": True,
        "event_streams_unchanged": True,
        "database_writes_performed": False,
        "production_authority_changed": False,
    }


def test_separates_unconditional_and_conditional_workload():
    result = run()
    reliever = pitcher(result, "101")

    assert reliever["appearance_count"] == 8
    assert reliever["appearance_rate"] == 0.08

    assert reliever["unconditional_outs"][
        "mean"
    ] == 0.9
    assert reliever["unconditional_outs"][
        "median"
    ] == 0

    conditional = reliever[
        "conditional_on_appearance_outs"
    ]

    assert conditional["count"] == 8
    assert conditional["minimum"] == 2
    assert conditional["maximum"] == 4
    assert conditional["median"] == 3

    assert reliever[
        "conditional_on_appearance_innings"
    ]["median"] == 1.0


def test_flags_starter_like_pitcher_retained_in_bullpen():
    result = run()
    reliever = pitcher(result, "101")

    assert result["pool_conflict_count"] == 1
    assert result["pool_conflicts"] == [{
        "team_side": "away",
        "pitcher_id": "101",
        "planned_role": "reliever",
        "typical_role": "starter",
        "decision_reason":
            "explicitly_eligible",
    }]
    assert reliever["pool_anomalies"] == [
        "starter_like_pitcher_retained_in_bullpen"
    ]
    assert result["decision"][
        "recommended_next_slice"
    ] == (
        "correct_canonical_pitcher_pool_"
        "role_and_availability_evidence"
    )


def test_surfaces_explicit_typical_bullpen_role():
    result = run()
    closer = pitcher(result, "102")

    assert closer["typical_bullpen_role"] == (
        "closer"
    )
    assert closer[
        "typical_role_inference_used"
    ] is False
    assert closer["availability_status"] == (
        "eligible"
    )


def test_does_not_infer_missing_typical_role():
    source = bullpen_discovery()
    source["away"]["eligibility"]["records"] = []

    result = (
        audit_canonical_pitcher_projection_pool_and_workload_calibration(
            projections=projections(),
            appearance_audit=appearance_audit(),
            bullpen_discovery=source,
        )
    )
    reliever = pitcher(result, "101")

    assert reliever["typical_bullpen_role"] is None
    assert reliever[
        "typical_role_inference_used"
    ] is False
    assert reliever["availability_status"] == (
        "unknown"
    )
    assert result[
        "missing_eligibility_evidence_count"
    ] == 2


def test_primary_p90_requires_historical_calibration():
    result = run()
    starter = pitcher(result, "100")

    assert starter[
        "workload_calibration_status"
    ] == "requires_historical_calibration"
    assert starter[
        "historical_calibration_available"
    ] is False
    assert result[
        "historical_calibration_required"
    ] is True
    assert result[
        "historical_calibration_pitcher_ids"
    ] == ["100"]
    assert result["interpretation"][
        "starter_p90_calibration_claimed"
    ] is False


def test_primary_pitcher_is_not_marked_missing_from_bullpen():
    result = run()
    starter = pitcher(result, "100")

    assert starter["availability_status"] == (
        "planned_primary_pitcher"
    )
    assert result[
        "missing_eligibility_evidence_pitcher_ids"
    ] == []


def test_missing_appearance_is_explicit():
    result = run()
    closer = pitcher(result, "102")

    assert closer["appearance_count"] == 0
    assert closer["appearance_rate"] == 0
    assert closer[
        "conditional_on_appearance_outs"
    ] is None
    assert closer[
        "workload_calibration_status"
    ] == "appearance_evidence_unavailable"
    assert result[
        "missing_appearance_evidence_pitcher_ids"
    ] == ["102"]


def test_planned_override_does_not_create_pool_conflict():
    source = bullpen_discovery()
    source["away"]["eligibility"][
        "records"
    ][0]["planned_pitcher"] = True

    result = (
        audit_canonical_pitcher_projection_pool_and_workload_calibration(
            projections=projections(),
            appearance_audit=appearance_audit(),
            bullpen_discovery=source,
        )
    )

    assert result["pool_conflict_count"] == 0


def test_blocks_without_trial_count():
    audit = appearance_audit()
    audit["trial_count"] = 0

    result = (
        audit_canonical_pitcher_projection_pool_and_workload_calibration(
            projections=projections(),
            appearance_audit=audit,
            bullpen_discovery=bullpen_discovery(),
        )
    )

    assert result["status"] == "blocked"
    assert (
        "simulation_trial_count_unavailable"
        in result["blockers"]
    )


def test_rejects_invalid_inputs():
    with pytest.raises(
        TypeError,
        match="projections must be a mapping",
    ):
        audit_canonical_pitcher_projection_pool_and_workload_calibration(
            projections=[],
            appearance_audit=appearance_audit(),
            bullpen_discovery=bullpen_discovery(),
        )


def test_does_not_mutate_inputs():
    projection_source = projections()
    appearance_source = appearance_audit()
    bullpen_source = bullpen_discovery()

    originals = deepcopy((
        projection_source,
        appearance_source,
        bullpen_source,
    ))

    audit_canonical_pitcher_projection_pool_and_workload_calibration(
        projections=projection_source,
        appearance_audit=appearance_source,
        bullpen_discovery=bullpen_source,
    )

    assert (
        projection_source,
        appearance_source,
        bullpen_source,
    ) == originals

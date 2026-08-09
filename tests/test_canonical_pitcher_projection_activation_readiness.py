from copy import deepcopy

import pytest

from mlb_app.simulation.shadow.canonical_pitcher_projection_activation_readiness import (
    SCHEMA_VERSION,
    audit_canonical_pitcher_projection_activation_readiness,
)


def metric(
    *,
    minimum,
    p10,
    median,
    mean,
    p90,
    maximum,
    count=100,
):
    return {
        "count": count,
        "minimum": minimum,
        "p10": p10,
        "median": median,
        "mean": mean,
        "p90": p90,
        "p95": p90,
        "maximum": maximum,
    }


def projection_rows():
    return {
        "schema_version":
            "canonical_player_projection_rows_v1",
        "simulation_count": 100,
        "pitcher_role_enrichment_applied": True,
        "pitcher_role_enrichment": {
            "status": "observed",
            "resolved_pitcher_count": 2,
            "missing_pitcher_count": 0,
            "conflicting_pitcher_count": 0,
            "invalid_record_count": 0,
            "inference_used": False,
            "database_writes_performed": False,
            "production_authority_changed": False,
        },
        "players": [
            {
                "player_id": "100",
                "player_type": "pitcher",
                "team_side": "away",
                "pitcher_role": "starter",
                "pitcher_role_resolution_status":
                    "resolved",
                "metrics": {
                    "batters_faced": metric(
                        minimum=12,
                        p10=18,
                        median=25,
                        mean=25,
                        p90=32,
                        maximum=36,
                    ),
                    "outs_recorded": metric(
                        minimum=3,
                        p10=9,
                        median=17,
                        mean=16,
                        p90=20,
                        maximum=24,
                    ),
                },
            },
            {
                "player_id": "101",
                "player_type": "pitcher",
                "team_side": "away",
                "pitcher_role": "reliever",
                "pitcher_role_resolution_status":
                    "resolved",
                "metrics": {
                    "outs_recorded": metric(
                        minimum=0,
                        p10=1,
                        median=3,
                        mean=3,
                        p90=5,
                        maximum=6,
                    ),
                },
            },
        ],
    }


def appearance_audit():
    return {
        "status": "observed",
        "audited": True,
        "trial_count": 100,
        "anomaly_counts": {},
        "starter_relief_detected": False,
        "database_writes_performed": False,
        "production_authority_changed": False,
    }


def role_audit():
    return {
        "status": "observed",
        "audited": True,
        "role_attribution_complete_rate": 1.0,
        "anomaly_counts": {},
        "database_writes_performed": False,
        "production_authority_changed": False,
    }


def run(
    *,
    projections=None,
    appearances=None,
    roles=None,
):
    return (
        audit_canonical_pitcher_projection_activation_readiness(
            projection_rows=(
                projections
                if projections is not None
                else projection_rows()
            ),
            appearance_audit=(
                appearances
                if appearances is not None
                else appearance_audit()
            ),
            role_and_innings_audit=(
                roles
                if roles is not None
                else role_audit()
            ),
        )
    )


def test_ready_evidence_allows_later_activation_slice():
    result = run()

    assert result["schema_version"] == (
        SCHEMA_VERSION
    )
    assert result["status"] == "ready"
    assert result["blockers"] == []
    assert result[
        "dynamic_workload_pitcher_ids"
    ] == ["100"]
    assert result["decision"][
        "pitcher_projection_activation_allowed"
    ] is True
    assert result["decision"][
        "production_activation_allowed"
    ] is True
    assert result["decision"][
        "recommended_next_slice"
    ] == (
        "activate_canonical_pitcher_"
        "projection_authority"
    )


def test_sequence_anomaly_blocks_activation():
    appearances = appearance_audit()
    appearances["anomaly_counts"] = {
        "pitcher_reentry": 1,
    }

    result = run(
        appearances=appearances,
    )

    assert result["status"] == "blocked"
    assert (
        "appearance_sequence_anomalies"
        in result["blockers"]
    )
    assert result["decision"][
        "production_activation_allowed"
    ] is False


def test_starter_relief_detection_blocks_activation():
    appearances = appearance_audit()
    appearances[
        "starter_relief_detected"
    ] = True

    result = run(
        appearances=appearances,
    )

    assert (
        "starter_relief_detected"
        in result["blockers"]
    )


def test_missing_role_evidence_blocks_activation():
    projections = projection_rows()
    projections["pitcher_role_enrichment"][
        "missing_pitcher_count"
    ] = 1
    projections["players"][0][
        "pitcher_role_resolution_status"
    ] = "missing"
    projections["players"][0][
        "pitcher_role"
    ] = None

    result = run(
        projections=projections,
    )

    assert (
        "pitcher_role_evidence_incomplete"
        in result["blockers"]
    )


def test_role_attribution_anomaly_blocks_activation():
    roles = role_audit()
    roles["anomaly_counts"] = {
        "planned_starter_not_projected": 1,
    }

    result = run(
        roles=roles,
    )

    assert (
        "role_and_innings_anomalies"
        in result["blockers"]
    )


def test_invalid_outs_distribution_blocks_activation():
    projections = projection_rows()
    projections["players"][0]["metrics"][
        "outs_recorded"
    ]["p90"] = 8

    result = run(
        projections=projections,
    )

    assert (
        "outs_distribution_invalid"
        in result["blockers"]
    )
    assert result[
        "invalid_distribution_pitcher_ids"
    ] == ["100"]


def test_missing_outs_distribution_blocks_activation():
    projections = projection_rows()
    del projections["players"][0][
        "metrics"
    ]["outs_recorded"]

    result = run(
        projections=projections,
    )

    assert (
        "outs_distribution_unavailable"
        in result["blockers"]
    )


def test_metric_count_is_not_required_by_row_contract():
    projections = projection_rows()

    for row in projections["players"]:
        row["metrics"]["outs_recorded"].pop(
            "count",
            None,
        )

    result = run(
        projections=projections,
    )

    assert result["status"] == "ready"
    assert result["simulation_count"] == 100
    assert result["decision"][
        "production_activation_allowed"
    ] is True


def test_missing_simulation_count_blocks_activation():
    projections = projection_rows()
    del projections["simulation_count"]

    result = run(
        projections=projections,
    )

    assert (
        "projection_simulation_count_unavailable"
        in result["blockers"]
    )
    assert result["decision"][
        "production_activation_allowed"
    ] is False


def test_primary_workload_requires_distribution_spread():
    projections = projection_rows()
    summary = projections["players"][0][
        "metrics"
    ]["outs_recorded"]

    for field_name in (
        "minimum",
        "p10",
        "median",
        "mean",
        "p90",
        "p95",
        "maximum",
    ):
        summary[field_name] = 15

    result = run(
        projections=projections,
    )

    assert (
        "dynamic_workload_evidence_unavailable"
        in result["blockers"]
    )


def test_more_than_twenty_seven_batters_does_not_block():
    projections = projection_rows()

    projections["players"][0]["metrics"][
        "batters_faced"
    ] = metric(
        minimum=18,
        p10=24,
        median=29,
        mean=30,
        p90=36,
        maximum=41,
    )

    result = run(
        projections=projections,
    )

    assert result["status"] == "ready"
    assert result["decision"][
        "production_activation_allowed"
    ] is True


def test_audit_is_read_only_and_non_authoritative():
    projections = projection_rows()
    appearances = appearance_audit()
    roles = role_audit()

    originals = (
        deepcopy(projections),
        deepcopy(appearances),
        deepcopy(roles),
    )

    result = run(
        projections=projections,
        appearances=appearances,
        roles=roles,
    )

    assert projections == originals[0]
    assert appearances == originals[1]
    assert roles == originals[2]
    assert (
        result["database_writes_performed"]
        is False
    )
    assert (
        result["production_authority_changed"]
        is False
    )


def test_source_authority_change_blocks_readiness():
    appearances = appearance_audit()
    appearances[
        "production_authority_changed"
    ] = True

    result = run(
        appearances=appearances,
    )

    assert (
        "source_production_authority_changed"
        in result["blockers"]
    )


def test_rejects_invalid_inputs():
    with pytest.raises(
        TypeError,
        match="projection_rows",
    ):
        (
            audit_canonical_pitcher_projection_activation_readiness(
                projection_rows=object(),
                appearance_audit=appearance_audit(),
                role_and_innings_audit=role_audit(),
            )
        )

    with pytest.raises(
        TypeError,
        match="appearance_audit",
    ):
        (
            audit_canonical_pitcher_projection_activation_readiness(
                projection_rows=projection_rows(),
                appearance_audit=object(),
                role_and_innings_audit=role_audit(),
            )
        )

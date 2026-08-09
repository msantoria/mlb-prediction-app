from copy import deepcopy

import pytest

from mlb_app.simulation.projections.pitcher_pool_role_reconciliation import (
    CANONICAL_PITCHER_POOL_ROLE_RECONCILIATION_VERSION,
    reconcile_canonical_pitcher_projection_pool_roles,
)


def metric(mean):
    return {
        "mean": mean,
        "minimum": 0,
        "maximum": mean,
    }


def payload():
    return {
        "schema_version":
            "canonical_player_projection_rows_v1",
        "players": [
            {
                "player_id": "100",
                "team_side": "away",
                "player_type": "pitcher",
                "pitcher_role": "starter",
                "metrics": {
                    "outs_recorded": metric(15),
                },
            },
            {
                "player_id": "101",
                "team_side": "away",
                "player_type": "pitcher",
                "pitcher_role": "reliever",
                "metrics": {
                    "outs_recorded": metric(3),
                },
            },
            {
                "player_id": "102",
                "team_side": "away",
                "player_type": "pitcher",
                "pitcher_role": "reliever",
                "metrics": {
                    "outs_recorded": metric(0.5),
                },
            },
            {
                "player_id": "103",
                "team_side": "away",
                "player_type": "pitcher",
                "pitcher_role": "reliever",
                "metrics": {
                    "outs_recorded": metric(0),
                },
            },
            {
                "player_id": "batter_1",
                "team_side": "away",
                "player_type": "batter",
                "metrics": {
                    "hits": metric(1),
                },
            },
        ],
    }


def appearance_audit():
    records = []

    for trial_index in range(10):
        records.append({
            "trial_index": trial_index,
            "team_side": "away",
            "pitcher_id": "100",
        })

    for trial_index in range(4):
        records.append({
            "trial_index": trial_index,
            "team_side": "away",
            "pitcher_id": "101",
        })

    return {
        "trial_count": 10,
        "records": records,
    }


def evidence_record(
    pitcher_id,
    *,
    status,
    role,
    planned=False,
):
    return {
        "pitcher_id": pitcher_id,
        "retained": status != "ineligible",
        "decision_reason": (
            "explicitly_eligible"
            if status == "eligible"
            else "probable_starter_not_in_plan"
        ),
        "planned_pitcher": planned,
        "evidence_present": True,
        "evidence_valid": True,
        "evidence_status": status,
        "pitcher_role": role,
        "evidence_source":
            "pregame_role_evidence_v1",
    }


def bullpen_discovery():
    return {
        "away": {
            "starter_id": "100",
            "bullpen_pitcher_ids": [
                "101",
                "103",
            ],
            "eligibility": {
                "records": [
                    evidence_record(
                        "101",
                        status="eligible",
                        role="closer",
                    ),
                    evidence_record(
                        "102",
                        status="ineligible",
                        role="probable_starter",
                    ),
                    {
                        "pitcher_id": "103",
                        "retained": True,
                        "decision_reason":
                            "eligibility_evidence_unavailable",
                        "planned_pitcher": False,
                        "evidence_present": False,
                        "evidence_valid": False,
                        "evidence_status": "unknown",
                        "pitcher_role": "unknown",
                        "evidence_source": None,
                    },
                ],
            },
        },
        "home": {},
    }


def run(**overrides):
    kwargs = {
        "payload": payload(),
        "appearance_audit": appearance_audit(),
        "bullpen_discovery": bullpen_discovery(),
    }
    kwargs.update(overrides)

    return (
        reconcile_canonical_pitcher_projection_pool_roles(
            **kwargs
        )
    )


def pitchers(result):
    return {
        row["player_id"]: row
        for row in result["players"]
        if row["player_type"] == "pitcher"
    }


def test_reconciles_explicit_pool_and_role_evidence():
    result = run()
    rows = pitchers(result)

    assert set(rows) == {
        "100",
        "101",
        "103",
    }

    assert rows["100"][
        "pitcher_projection_group"
    ] == "starter"
    assert rows["100"][
        "game_availability_status"
    ] == "planned_primary_pitcher"

    assert rows["101"][
        "pitcher_projection_group"
    ] == "bullpen"
    assert rows["101"][
        "typical_bullpen_role"
    ] == "closer"
    assert rows["101"][
        "game_availability_status"
    ] == "explicitly_eligible"

    assert "102" not in rows
    assert rows["103"][
        "game_availability_status"
    ] == "active_roster_candidate_unknown"


def test_surfaces_appearance_probability():
    rows = pitchers(run())

    assert rows["100"]["appearance_count"] == 10
    assert rows["100"][
        "appearance_probability"
    ] == 1.0
    assert rows["101"]["appearance_count"] == 4
    assert rows["101"][
        "appearance_probability"
    ] == 0.4
    assert rows["103"]["appearance_count"] == 0
    assert rows["103"][
        "appearance_probability"
    ] == 0.0


def test_unknown_evidence_fails_open():
    result = run()
    reconciliation = result[
        "pitcher_pool_role_reconciliation"
    ]

    assert "103" in pitchers(result)
    assert reconciliation[
        "unknown_evidence_fails_open"
    ] is True
    assert reconciliation[
        "unknown_availability_pitcher_count"
    ] == 1


def test_explicit_ineligibility_excludes_only_pitcher_row():
    result = run()
    reconciliation = result[
        "pitcher_pool_role_reconciliation"
    ]

    assert reconciliation[
        "excluded_pitcher_ids"
    ] == ["102"]
    assert reconciliation[
        "excluded_pitcher_count"
    ] == 1
    assert any(
        row["player_id"] == "batter_1"
        for row in result["players"]
    )


def test_planned_pitcher_overrides_ineligibility():
    source = bullpen_discovery()
    source["away"]["eligibility"][
        "records"
    ][1]["planned_pitcher"] = True

    result = run(
        bullpen_discovery=source,
    )

    assert "102" in pitchers(result)
    assert pitchers(result)["102"][
        "pitcher_pool_membership_status"
    ] == "included_explicit_pitching_plan"


def test_starter_like_eligible_reliever_is_conflicting():
    source = bullpen_discovery()
    source["away"]["eligibility"][
        "records"
    ][0]["pitcher_role"] = "starter"

    result = run(
        bullpen_discovery=source,
    )
    row = pitchers(result)["101"]

    assert row[
        "pitcher_role_taxonomy_status"
    ] == "conflicting"
    assert result[
        "pitcher_pool_role_reconciliation"
    ]["role_conflict_pitcher_ids"] == [
        "101",
    ]


def test_does_not_infer_missing_typical_role():
    row = pitchers(run())["103"]

    assert row["typical_bullpen_role"] is None
    assert row[
        "typical_role_inference_used"
    ] is False


def test_preserves_projection_metrics_and_inputs():
    source_payload = payload()
    original_payload = deepcopy(source_payload)
    original_discovery = bullpen_discovery()

    result = run(
        payload=source_payload,
        bullpen_discovery=original_discovery,
    )

    assert source_payload == original_payload
    assert pitchers(result)["101"]["metrics"] == (
        pitchers(original_payload)["101"][
            "metrics"
        ]
    )
    assert result[
        "pitcher_pool_role_reconciliation"
    ]["workload_calibration_changed"] is False
    assert result[
        "pitcher_pool_role_reconciliation"
    ]["game_probability_authority_changed"] is False


def test_reports_schema_and_safety_contract():
    reconciliation = run()[
        "pitcher_pool_role_reconciliation"
    ]

    assert reconciliation["schema_version"] == (
        CANONICAL_PITCHER_POOL_ROLE_RECONCILIATION_VERSION
    )
    assert reconciliation[
        "typical_role_inference_used"
    ] is False
    assert reconciliation[
        "database_writes_performed"
    ] is False


@pytest.mark.parametrize(
    "field,value",
    [
        ("payload", None),
        ("appearance_audit", None),
        ("bullpen_discovery", None),
    ],
)
def test_rejects_invalid_inputs(field, value):
    kwargs = {
        "payload": payload(),
        "appearance_audit": appearance_audit(),
        "bullpen_discovery": bullpen_discovery(),
    }
    kwargs[field] = value

    with pytest.raises(TypeError):
        reconcile_canonical_pitcher_projection_pool_roles(
            **kwargs
        )

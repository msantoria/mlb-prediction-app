from copy import deepcopy

from mlb_app.simulation.shadow import (
    attach_canonical_shadow,
)


def legacy_result():
    return {
        "simulation_count": 3000,
        "away_team": {
            "win_probability": 0.48,
        },
        "home_team": {
            "win_probability": 0.52,
        },
    }


def canonical_payload():
    return {
        "schema_version": (
            "canonical_projection_payload_v1"
        ),
        "run_id": "canonical-run-123",
        "model_version": "canonical-model-v1",
        "simulation_count": 25,
        "teams": [
            {
                "team_side": "away",
                "metrics": [],
            },
            {
                "team_side": "home",
                "metrics": [],
            },
        ],
        "batters": [
            {
                "player_id": "100",
                "team_side": "away",
                "metrics": [
                    {
                        "name": "plate_appearances",
                        "summary": {
                            "count": 25,
                            "mean": 4.4,
                            "median": 4.0,
                            "p10": 3.0,
                            "p25": 4.0,
                            "p75": 5.0,
                            "p90": 5.0,
                            "minimum": 3.0,
                            "maximum": 6.0,
                        },
                    },
                    {
                        "name": "singles",
                        "summary": {
                            "count": 25,
                            "mean": 0.8,
                            "median": 1.0,
                            "p10": 0.0,
                            "p25": 0.0,
                            "p75": 1.0,
                            "p90": 2.0,
                            "minimum": 0.0,
                            "maximum": 3.0,
                        },
                    },
                    {
                        "name": "dfs_points",
                        "summary": {
                            "count": 25,
                            "mean": 9.5,
                            "median": 8.0,
                            "p10": 2.0,
                            "p25": 4.0,
                            "p75": 13.0,
                            "p90": 18.0,
                            "minimum": 0.0,
                            "maximum": 24.0,
                        },
                    },
                ],
            },
        ],
        "pitchers": [
            {
                "player_id": "200",
                "team_side": "home",
                "metrics": [
                    {
                        "name": "strikeouts",
                        "summary": {
                            "count": 25,
                            "mean": 6.2,
                            "median": 6.0,
                            "p10": 3.0,
                            "p25": 5.0,
                            "p75": 8.0,
                            "p90": 9.0,
                            "minimum": 2.0,
                            "maximum": 11.0,
                        },
                    },
                    {
                        "name": "dfs_points",
                        "summary": {
                            "count": 25,
                            "mean": 17.4,
                            "median": 17.0,
                            "p10": 8.0,
                            "p25": 12.0,
                            "p75": 22.0,
                            "p90": 28.0,
                            "minimum": 4.0,
                            "maximum": 33.0,
                        },
                    },
                ],
            },
        ],
        "diagnostics": {
            "warnings": [],
            "pitcher_attribution_complete_rate": 1.0,
            "replay_validation_pass_rate": 1.0,
        },
    }


def test_shadow_attaches_same_run_player_projections():
    result = attach_canonical_shadow(
        legacy_result=legacy_result(),
        enabled=True,
        canonical_payload=canonical_payload(),
    )

    shadow = result["diagnostics"][
        "canonical_shadow"
    ]
    projections = shadow[
        "player_projections"
    ]

    assert projections["schema_version"] == (
        "canonical_player_projection_rows_v1"
    )
    assert projections["run_id"] == (
        "canonical-run-123"
    )
    assert projections["model_version"] == (
        "canonical-model-v1"
    )
    assert projections["simulation_count"] == 25
    assert len(projections["players"]) == 2

    batter = next(
        row
        for row in projections["players"]
        if row["player_id"] == "100"
    )

    assert batter["player_type"] == "batter"
    assert batter["projected_dfs_points"] == 9.5
    assert batter["metrics"][
        "plate_appearances"
    ]["mean"] == 4.4
    assert batter["metrics"][
        "singles"
    ]["mean"] == 0.8


def test_shadow_projection_metadata_matches_source_run():
    source = canonical_payload()

    result = attach_canonical_shadow(
        legacy_result=legacy_result(),
        enabled=True,
        canonical_payload=source,
    )

    projections = result["diagnostics"][
        "canonical_shadow"
    ]["player_projections"]

    assert projections["run_id"] == source["run_id"]
    assert (
        projections["model_version"]
        == source["model_version"]
    )
    assert (
        projections["simulation_count"]
        == source["simulation_count"]
    )
    assert projections["authoritative"] is False
    assert (
        projections["authoritative_source"]
        == "legacy"
    )


def test_shadow_projection_attachment_does_not_mutate_inputs():
    legacy = legacy_result()
    canonical = canonical_payload()
    original_legacy = deepcopy(legacy)
    original_canonical = deepcopy(canonical)

    attach_canonical_shadow(
        legacy_result=legacy,
        enabled=True,
        canonical_payload=canonical,
    )

    assert legacy == original_legacy
    assert canonical == original_canonical


def test_invalid_projection_payload_fails_open():
    malformed = canonical_payload()
    malformed["batters"] = "invalid"

    result = attach_canonical_shadow(
        legacy_result=legacy_result(),
        enabled=True,
        canonical_payload=malformed,
    )

    projections = result["diagnostics"][
        "canonical_shadow"
    ]["player_projections"]

    assert projections["status"] == "error"
    assert projections["players"] == []
    assert projections["authoritative"] is False


def test_disabled_shadow_has_no_player_projections():
    result = attach_canonical_shadow(
        legacy_result=legacy_result(),
        enabled=False,
        canonical_payload=canonical_payload(),
    )

    shadow = result["diagnostics"][
        "canonical_shadow"
    ]

    assert "player_projections" not in shadow

def test_shadow_attaches_same_run_pitcher_role_evidence():
    result = attach_canonical_shadow(
        legacy_result=legacy_result(),
        enabled=True,
        canonical_payload=canonical_payload(),
        pitcher_appearance_sequence_audit={
            "records": [
                {
                    "trial_index": 0,
                    "team_side": "home",
                    "pitcher_id": "200",
                    "planned_role": "starter",
                },
            ],
        },
    )

    projections = result["diagnostics"][
        "canonical_shadow"
    ]["player_projections"]

    pitcher = next(
        row
        for row in projections["players"]
        if row["player_id"] == "200"
    )

    assert pitcher["pitcher_role"] == "starter"
    assert pitcher[
        "pitcher_role_resolution_status"
    ] == "resolved"
    assert projections[
        "pitcher_role_enrichment_applied"
    ] is True
    assert projections["pitcher_role_enrichment"][
        "inference_used"
    ] is False


def test_pitcher_role_failure_preserves_projection_rows():
    result = attach_canonical_shadow(
        legacy_result=legacy_result(),
        enabled=True,
        canonical_payload=canonical_payload(),
        pitcher_appearance_sequence_audit={
            "records": "invalid",
        },
    )

    projections = result["diagnostics"][
        "canonical_shadow"
    ]["player_projections"]

    assert len(projections["players"]) == 2
    assert projections[
        "pitcher_role_enrichment_applied"
    ] is False
    assert projections["pitcher_role_enrichment"][
        "status"
    ] == "error"
    assert projections["authoritative"] is False

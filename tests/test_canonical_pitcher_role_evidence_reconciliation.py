from copy import deepcopy

import pytest

from mlb_app.simulation.projections.pitcher_pool_role_reconciliation import (
    reconcile_canonical_pitcher_projection_pool_roles,
)


def payload():
    return {
        "players": [
            {
                "player_id": "100",
                "player_name": "Starter",
                "player_type": "pitcher",
                "team_side": "away",
                "pitcher_role": "starter",
            },
            {
                "player_id": "101",
                "player_name": "Historical Closer",
                "player_type": "pitcher",
                "team_side": "away",
                "pitcher_role": "reliever",
            },
            {
                "player_id": "102",
                "player_name": "Historical Bulk",
                "player_type": "pitcher",
                "team_side": "away",
                "pitcher_role": "reliever",
            },
            {
                "player_id": "200",
                "player_name": "Home Starter",
                "player_type": "pitcher",
                "team_side": "home",
                "pitcher_role": "starter",
            },
        ],
    }


def appearance_audit():
    return {
        "trial_count": 2,
        "records": [
            {
                "trial_index": 0,
                "team_side": "away",
                "pitcher_id": "100",
            },
            {
                "trial_index": 1,
                "team_side": "away",
                "pitcher_id": "100",
            },
            {
                "trial_index": 0,
                "team_side": "away",
                "pitcher_id": "101",
            },
            {
                "trial_index": 0,
                "team_side": "away",
                "pitcher_id": "102",
            },
            {
                "trial_index": 1,
                "team_side": "away",
                "pitcher_id": "102",
            },
            {
                "trial_index": 0,
                "team_side": "home",
                "pitcher_id": "200",
            },
            {
                "trial_index": 1,
                "team_side": "home",
                "pitcher_id": "200",
            },
        ],
    }


def bullpen_discovery(
    *,
    explicit_role=None,
):
    away_records = []

    if explicit_role is not None:
        away_records.append({
            "pitcher_id": "101",
            "evidence_valid": True,
            "evidence_status": "eligible",
            "pitcher_role": explicit_role,
            "source": "explicit_provider",
        })

    return {
        "away": {
            "starter_id": "100",
            "bullpen_pitcher_ids": [
                "101",
                "102",
            ],
            "eligibility": {
                "records": away_records,
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


def role_evidence():
    return {
        "evidence_by_pitcher_id": {
            "101": {
                "pitcher_id": "101",
                "typical_role": "closer",
                "typical_role_confidence": "high",
                "typical_role_source":
                    "mlb_stats_season_pitching_usage",
                "typical_role_inference_used": True,
                "planned_role": None,
            },
            "102": {
                "pitcher_id": "102",
                "typical_role": "bulk_follower",
                "confidence": "medium",
                "source":
                    "mlb_final_game_appearance_history",
                "inference_used": True,
                "planned_role": None,
            },
        },
    }


def rows(result):
    return {
        row["player_id"]: row
        for row in result["players"]
        if row["player_type"] == "pitcher"
    }


def run(
    *,
    discovery=None,
    evidence=None,
):
    return reconcile_canonical_pitcher_projection_pool_roles(
        payload=payload(),
        appearance_audit=appearance_audit(),
        bullpen_discovery=(
            discovery
            if discovery is not None
            else bullpen_discovery()
        ),
        pitcher_role_evidence=(
            evidence
            if evidence is not None
            else role_evidence()
        ),
    )


def test_attaches_historical_typical_roles():
    result = run()
    pitcher_rows = rows(result)

    assert pitcher_rows["101"][
        "typical_bullpen_role"
    ] == "closer"
    assert pitcher_rows["101"][
        "typical_role_source"
    ] == "mlb_stats_season_pitching_usage"
    assert pitcher_rows["101"][
        "typical_role_confidence"
    ] == "high"
    assert pitcher_rows["101"][
        "typical_role_inference_used"
    ] is True

    assert pitcher_rows["102"][
        "typical_bullpen_role"
    ] == "bulk_follower"
    assert pitcher_rows["102"][
        "planned_pitcher_role"
    ] == "reliever"
    assert pitcher_rows["102"][
        "pitcher_projection_group"
    ] == "bullpen"


def test_historical_bulk_role_never_becomes_planned_role():
    result = run()
    row = rows(result)["102"]

    assert row["typical_bullpen_role"] == (
        "bulk_follower"
    )
    assert row["planned_pitcher_role"] == "reliever"
    assert result[
        "pitcher_pool_role_reconciliation"
    ][
        "historical_role_never_claims_today_plan"
    ] is True


def test_explicit_pregame_role_takes_precedence():
    result = run(
        discovery=bullpen_discovery(
            explicit_role="setup",
        ),
    )
    row = rows(result)["101"]

    assert row["typical_bullpen_role"] == "setup"
    assert row["typical_role_source"] == (
        "explicit_provider"
    )
    assert row["typical_role_confidence"] == (
        "explicit"
    )
    assert row[
        "typical_role_inference_used"
    ] is False


def test_reports_role_evidence_counts():
    result = run()
    reconciliation = result[
        "pitcher_pool_role_reconciliation"
    ]

    assert reconciliation[
        "explicit_typical_role_count"
    ] == 0
    assert reconciliation[
        "historical_typical_role_count"
    ] == 2
    assert reconciliation[
        "inferred_typical_role_count"
    ] == 2
    assert reconciliation[
        "typical_role_inference_used"
    ] is True


def test_missing_history_preserves_unknown_contract():
    result = run(evidence={})
    row = rows(result)["101"]

    assert row["typical_bullpen_role"] is None
    assert row["typical_role_source"] is None
    assert row["typical_role_confidence"] is None
    assert row[
        "typical_role_inference_used"
    ] is False


def test_role_evidence_input_is_not_mutated():
    evidence = role_evidence()
    original = deepcopy(evidence)

    run(evidence=evidence)

    assert evidence == original


def test_rejects_non_mapping_role_evidence():
    with pytest.raises(
        TypeError,
        match="pitcher_role_evidence must be a mapping",
    ):
        reconcile_canonical_pitcher_projection_pool_roles(
            payload=payload(),
            appearance_audit=appearance_audit(),
            bullpen_discovery=bullpen_discovery(),
            pitcher_role_evidence=[],
        )


def test_public_projection_import_contract():
    from mlb_app.simulation.projections import (
        CANONICAL_PITCHER_APPEARANCE_HISTORY_VERSION,
        CANONICAL_PITCHER_TYPICAL_ROLE_EVIDENCE_VERSION,
        materialize_canonical_pitcher_appearance_history,
        materialize_canonical_pitcher_role_evidence,
    )

    assert (
        CANONICAL_PITCHER_APPEARANCE_HISTORY_VERSION
    )
    assert (
        CANONICAL_PITCHER_TYPICAL_ROLE_EVIDENCE_VERSION
    )
    assert callable(
        materialize_canonical_pitcher_appearance_history
    )
    assert callable(
        materialize_canonical_pitcher_role_evidence
    )

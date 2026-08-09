from __future__ import annotations

from dataclasses import dataclass

from mlb_app import model_projections
from mlb_app.simulation.game import (
    CANONICAL_PA_OUTCOME_ORDER,
    CanonicalOutcomeProbability,
    CanonicalProbabilityArtifact,
    CanonicalProbabilityArtifactRecord,
    CanonicalProbabilityFallbackCatalog,
    CanonicalProbabilityFallbackRecord,
    CanonicalProbabilityFallbackTier,
    CanonicalProbabilityProviderIdentity,
)
from mlb_app.simulation.shadow import (
    CanonicalShadowBullpenDiscovery,
    CanonicalShadowBullpenSideDiscovery,
    CanonicalShadowExactArtifactDiscovery,
    CanonicalShadowFallbackCatalogDiscovery,
    CanonicalShadowLineupDiscovery,
    CanonicalShadowProbabilityProviderDiscovery,
    run_canonical_production_shadow,
)


PROVIDER = CanonicalProbabilityProviderIdentity(
    provider_name="model_projections_pa_outcome",
    provider_version="pa_outcome_v1",
)


def probability_points():
    values = {
        "out": 0.43,
        "single": 0.15,
        "double": 0.05,
        "triple": 0.005,
        "hr": 0.03,
        "bb": 0.085,
        "hbp": 0.01,
        "k": 0.24,
    }

    return tuple(
        CanonicalOutcomeProbability(
            outcome=outcome,
            probability=values[outcome.value],
        )
        for outcome in CANONICAL_PA_OUTCOME_ORDER
    )


def lineups():
    return CanonicalShadowLineupDiscovery(
        away_player_ids=tuple(
            f"a{index}"
            for index in range(1, 10)
        ),
        home_player_ids=tuple(
            f"h{index}"
            for index in range(1, 10)
        ),
        away_source_count=9,
        home_source_count=9,
        status="ready",
    )


def bullpens():
    return CanonicalShadowBullpenDiscovery(
        away=CanonicalShadowBullpenSideDiscovery(
            team_id="1",
            starter_id="100",
            bullpen_pitcher_ids=("101",),
            source_record_count=2,
            status="ready",
        ),
        home=CanonicalShadowBullpenSideDiscovery(
            team_id="2",
            starter_id="200",
            bullpen_pitcher_ids=("201",),
            source_record_count=2,
            status="ready",
        ),
    )


def provider_discovery():
    return CanonicalShadowProbabilityProviderDiscovery(
        provider=PROVIDER,
        model_versions=("pa_outcome_v1",),
        valid_model_count=4,
        status="ready",
    )


def exact_discovery():
    records = tuple(
        CanonicalProbabilityArtifactRecord(
            batter_id=batter_id,
            pitcher_id=pitcher_id,
            probabilities=probability_points(),
        )
        for batter_id, pitcher_id in (
            *(
                (f"a{index}", "200")
                for index in range(1, 10)
            ),
            *(
                (f"h{index}", "100")
                for index in range(1, 10)
            ),
        )
    )

    return CanonicalShadowExactArtifactDiscovery(
        artifact=CanonicalProbabilityArtifact(
            provider=PROVIDER,
            records=records,
        ),
        away_record_count=9,
        home_record_count=9,
        away_real_profile_count=9,
        home_real_profile_count=9,
        status="ready",
    )


def fallback_discovery():
    return CanonicalShadowFallbackCatalogDiscovery(
        catalog=CanonicalProbabilityFallbackCatalog(
            provider=PROVIDER,
            records=(
                CanonicalProbabilityFallbackRecord(
                    tier=(
                        CanonicalProbabilityFallbackTier
                        .GLOBAL
                    ),
                    identity=None,
                    probabilities=probability_points(),
                ),
            ),
        ),
        source_model_count=4,
        status="ready",
    )


def executed_shadow(*, simulation_count=2):
    return run_canonical_production_shadow(
        game_pk=123,
        lineups=lineups(),
        bullpens=bullpens(),
        provider_discovery=provider_discovery(),
        exact_artifact_discovery=exact_discovery(),
        fallback_catalog_discovery=(
            fallback_discovery()
        ),
        bootstrap_ready=True,
        simulation_count=simulation_count,
    )


def legacy_payload():
    return {
        "model_version": "shared-simulation-v1",
        "simulation_count": 3000,
        "away_win_probability": 0.48,
        "home_win_probability": 0.52,
        "away_expected_runs": 4.1,
        "home_expected_runs": 4.4,
        "expected_total_runs": 8.5,
        "diagnostics": {
            "existing": True,
        },
    }


def test_executed_material_reaches_comparator():
    result = (
        model_projections
        ._attach_production_shadow_comparison(
            legacy_result=legacy_payload(),
            production_execution=executed_shadow(),
        )
    )

    shadow = result["diagnostics"][
        "canonical_shadow"
    ]

    assert shadow["enabled"] is True
    assert shadow["canonical_available"] is True
    assert shadow["authoritative_source"] == (
        "legacy"
    )
    assert shadow["status"] in {
        "compared",
        "partial",
    }


def test_comparator_attaches_probability_diagnostics():
    result = (
        model_projections
        ._attach_production_shadow_comparison(
            legacy_result=legacy_payload(),
            production_execution=executed_shadow(),
        )
    )

    probability = result["diagnostics"][
        "canonical_shadow"
    ]["probability_resolution"]

    assert probability[
        "schema_version"
    ] == (
        "canonical_probability_diagnostics_shadow_v1"
    )
    assert probability["summary"][
        "total_resolutions"
    ] > 0
    assert probability[
        "tier_usage"
    ]


def test_comparator_attaches_atomic_input_provenance():
    execution = executed_shadow()

    result = (
        model_projections
        ._attach_production_shadow_comparison(
            legacy_result=legacy_payload(),
            production_execution=execution,
        )
    )

    provenance = result["diagnostics"][
        "canonical_shadow"
    ]["input_provenance"]

    assert provenance[
        "schema_version"
    ] == "canonical_shadow_input_provenance_v1"
    assert provenance[
        "probability_provider"
    ]["identity"] == PROVIDER.identity
    assert provenance["assembly_digest"] == (
        execution.execution_inputs
        .assembly_digest
    )
    assert provenance[
        "authoritative_source"
    ] == "legacy"


def test_legacy_values_remain_authoritative():
    legacy = legacy_payload()

    result = (
        model_projections
        ._attach_production_shadow_comparison(
            legacy_result=legacy,
            production_execution=executed_shadow(),
        )
    )

    assert result[
        "away_win_probability"
    ] == legacy["away_win_probability"]

    assert result[
        "home_win_probability"
    ] == legacy["home_win_probability"]

    assert result[
        "expected_total_runs"
    ] == legacy["expected_total_runs"]

    assert result is not legacy


@dataclass(frozen=True)
class BlockedExecution:
    material: object = None
    status: str = "blocked"


def test_blocked_execution_leaves_payload_unchanged():
    legacy = legacy_payload()

    result = (
        model_projections
        ._attach_production_shadow_comparison(
            legacy_result=legacy,
            production_execution=BlockedExecution(),
        )
    )

    assert result is legacy
    assert "canonical_shadow" not in (
        result["diagnostics"]
    )


def test_invalid_legacy_payload_is_rejected():
    try:
        (
            model_projections
            ._attach_production_shadow_comparison(
                legacy_result=[],
                production_execution=executed_shadow(),
            )
        )
    except TypeError as exc:
        assert str(exc) == (
            "legacy_result must be a dictionary"
        )
    else:
        raise AssertionError(
            "invalid legacy payload must fail"
        )


def test_executed_shadow_attaches_same_run_player_projections():
    execution = executed_shadow()

    result = (
        model_projections
        ._attach_production_shadow_comparison(
            legacy_result={
                "status": "ok",
                "diagnostics": {},
            },
            production_execution=execution,
        )
    )

    shadow = result["diagnostics"]["canonical_shadow"]
    projections = shadow["player_projections"]

    assert projections["schema_version"] == (
        "canonical_player_projection_rows_v1"
    )
    assert projections["run_id"] == (
        execution.material.canonical_payload["run_id"]
    )
    assert projections["simulation_count"] == (
        execution
        .material
        .canonical_payload["simulation_count"]
    )
    assert projections["players"]


def test_realism_payload_exposes_frontend_capability_aliases():
    realism = (
        model_projections
        ._build_game_state_realism_diagnostics()
    )

    assert realism["multi_out_scoring"] is True
    assert (
        realism["sacrifice_fly_scoring"]
        is True
    )
    assert realism["stolen_bases"] is True
    assert realism["stolen_base_model"] is True
    assert realism["steals_model_status"] == (
        "canonical_calibrated_active"
    )
    assert realism[
        "steals_projection_wiring_status"
    ] == (
        "canonical_event_driven_production_authority"
    )

def test_comparator_attaches_pitcher_projection_readiness():
    legacy = legacy_payload()

    result = (
        model_projections
        ._attach_production_shadow_comparison(
            legacy_result=legacy,
            production_execution=executed_shadow(
                simulation_count=100,
            ),
            bullpen_discovery=(
                model_projections
                ._canonical_pitcher_pool_audit_input(
                    bullpens()
                )
            ),
        )
    )

    shadow = result["diagnostics"][
        "canonical_shadow"
    ]
    readiness = shadow[
        "pitcher_projection_activation_readiness"
    ]
    projections = shadow["player_projections"]

    assert readiness["status"] == "ready"
    assert readiness["blockers"] == []
    assert readiness["decision"][
        "pitcher_projection_activation_allowed"
    ] is True
    assert readiness["decision"][
        "production_activation_allowed"
    ] is True
    assert (
        readiness["dynamic_workload_pitcher_count"]
        > 0
    )

    # 6SY only surfaces the readiness verdict.
    # Legacy production authority remains untouched.
    assert shadow["authoritative_source"] == "legacy"
    assert projections["authoritative"] is False
    assert projections[
        "authoritative_source"
    ] == "mixed"
    assert projections[
        "pitcher_projections_authoritative"
    ] is True
    assert projections[
        "batter_projections_authoritative"
    ] is False

    authority = shadow[
        "pitcher_projection_authority"
    ]
    pool_audit = shadow[
        "pitcher_projection_pool_and_"
        "workload_calibration"
    ]

    assert pool_audit["status"] == "observed"
    assert pool_audit["audited"] is True
    assert pool_audit["trial_count"] == 100
    assert (
        pool_audit["pitcher_projection_count"]
        == 4
    )
    assert pool_audit[
        "historical_calibration_required"
    ] is True
    assert pool_audit["interpretation"][
        "unconditional_distribution_"
        "includes_nonappearances"
    ] is True
    assert pool_audit["interpretation"][
        "conditional_distribution_"
        "excludes_nonappearances"
    ] is True
    assert pool_audit["interpretation"][
        "typical_bullpen_roles_inferred"
    ] is False
    assert pool_audit["interpretation"][
        "starter_p90_calibration_claimed"
    ] is False
    assert pool_audit[
        "database_writes_performed"
    ] is False
    assert pool_audit[
        "production_authority_changed"
    ] is False

    starter_rows = [
        row
        for row in pool_audit["pitchers"]
        if row["planned_role"] == "starter"
    ]
    reliever_rows = [
        row
        for row in pool_audit["pitchers"]
        if row["planned_role"] == "reliever"
    ]

    assert starter_rows
    assert reliever_rows

    assert all(
        row["appearance_rate"] == 1.0
        for row in starter_rows
    )
    assert all(
        row[
            "conditional_on_appearance_outs"
        ] is not None
        for row in starter_rows
    )
    assert all(
        row["typical_role_inference_used"]
        is False
        for row in reliever_rows
    )

    assert authority["status"] == "activated"
    assert authority[
        "production_activation"
    ] is True
    assert authority[
        "authority_scope"
    ] == "pitcher_rows_only"
    assert authority[
        "production_authority_changed"
    ] is True

    pitcher_rows = [
        row
        for row in projections["players"]
        if row["player_type"] == "pitcher"
    ]
    batter_rows = [
        row
        for row in projections["players"]
        if row["player_type"] == "batter"
    ]

    assert pitcher_rows
    assert all(
        row["authoritative"] is True
        for row in pitcher_rows
    )
    assert all(
        row["authoritative_source"]
        == (
            "canonical_event_driven_"
            "pitcher_projection"
        )
        for row in pitcher_rows
    )

    assert batter_rows
    assert all(
        row["authoritative"] is False
        for row in batter_rows
    )
    assert all(
        row["authoritative_source"]
        == "legacy"
        for row in batter_rows
    )
    assert result[
        "away_win_probability"
    ] == legacy["away_win_probability"]
    assert result[
        "home_win_probability"
    ] == legacy["home_win_probability"]

    assert (
        readiness["database_writes_performed"]
        is False
    )
    assert (
        readiness["production_authority_changed"]
        is False
    )

def test_pitcher_projection_authority_rolls_back_with_flag(
    monkeypatch,
):
    monkeypatch.setenv(
        "MLB_CANONICAL_PITCHER_PROJECTIONS_ENABLED",
        "false",
    )

    legacy = legacy_payload()

    result = (
        model_projections
        ._attach_production_shadow_comparison(
            legacy_result=legacy,
            production_execution=executed_shadow(
                simulation_count=100,
            ),
        )
    )

    shadow = result["diagnostics"][
        "canonical_shadow"
    ]
    readiness = shadow[
        "pitcher_projection_activation_readiness"
    ]
    authority = shadow[
        "pitcher_projection_authority"
    ]
    projections = shadow["player_projections"]

    # The evidence remains ready, but the immediate
    # environment rollback retains legacy authority.
    assert readiness["status"] == "ready"
    assert readiness["decision"][
        "production_activation_allowed"
    ] is True

    assert authority["status"] == "fallback"
    assert authority[
        "activation_requested"
    ] is False
    assert authority[
        "production_activation"
    ] is False
    assert authority["fallback_reason"] == (
        "rollback_flag_disabled"
    )
    assert authority[
        "production_authority_changed"
    ] is False

    assert projections[
        "pitcher_projections_authoritative"
    ] is False
    assert projections[
        "authoritative_source"
    ] == "legacy"

    pitcher_rows = [
        row
        for row in projections["players"]
        if row["player_type"] == "pitcher"
    ]

    assert pitcher_rows
    assert all(
        row["authoritative"] is False
        for row in pitcher_rows
    )
    assert all(
        row["authoritative_source"]
        == "legacy"
        for row in pitcher_rows
    )

    # Game-level outputs are not part of 6SZ.
    assert shadow["authoritative_source"] == "legacy"
    assert result[
        "away_win_probability"
    ] == legacy["away_win_probability"]
    assert result[
        "home_win_probability"
    ] == legacy["home_win_probability"]


def test_low_evidence_run_fails_closed_to_legacy():
    result = (
        model_projections
        ._attach_production_shadow_comparison(
            legacy_result=legacy_payload(),
            production_execution=executed_shadow(
                simulation_count=2,
            ),
        )
    )

    shadow = result["diagnostics"][
        "canonical_shadow"
    ]
    readiness = shadow[
        "pitcher_projection_activation_readiness"
    ]
    authority = shadow[
        "pitcher_projection_authority"
    ]

    if readiness["status"] != "ready":
        assert authority["status"] == "fallback"
        assert authority[
            "production_activation"
        ] is False
        assert authority["fallback_reason"] == (
            "pitcher_projection_readiness_blocked"
        )
        assert authority[
            "authoritative_source"
        ] == "legacy"

def test_comparator_reconciles_pitcher_projection_pool_roles():
    legacy = legacy_payload()

    result = (
        model_projections
        ._attach_production_shadow_comparison(
            legacy_result=legacy,
            production_execution=executed_shadow(
                simulation_count=100,
            ),
            bullpen_discovery=(
                model_projections
                ._canonical_pitcher_pool_audit_input(
                    bullpens()
                )
            ),
        )
    )

    shadow = result["diagnostics"][
        "canonical_shadow"
    ]
    projections = shadow["player_projections"]
    reconciliation = shadow[
        "pitcher_projection_pool_role_reconciliation"
    ]

    assert reconciliation["status"] == "reconciled"
    assert reconciliation[
        "schema_version"
    ] == (
        "canonical_pitcher_projection_"
        "pool_role_reconciliation_v1"
    )
    assert reconciliation[
        "excluded_pitcher_count"
    ] == 0
    assert reconciliation[
        "unknown_evidence_fails_open"
    ] is True
    assert reconciliation[
        "typical_role_inference_used"
    ] is False
    assert reconciliation[
        "game_probability_authority_changed"
    ] is False
    assert reconciliation[
        "database_writes_performed"
    ] is False
    assert reconciliation[
        "production_authority_changed"
    ] is False

    pitcher_rows = {
        row["player_id"]: row
        for row in projections["players"]
        if row["player_type"] == "pitcher"
    }

    starter_rows = [
        row
        for row in pitcher_rows.values()
        if row["planned_pitcher_role"]
        == "starter"
    ]
    reliever_rows = [
        row
        for row in pitcher_rows.values()
        if row["planned_pitcher_role"]
        == "reliever"
    ]

    assert starter_rows
    assert reliever_rows

    assert all(
        row["pitcher_projection_group"]
        == "starter"
        for row in starter_rows
    )
    assert all(
        row["game_availability_status"]
        == "planned_primary_pitcher"
        for row in starter_rows
    )

    # Production currently has active-roster
    # candidate evidence, not verified same-game
    # role or availability evidence.
    assert all(
        row["pitcher_projection_group"]
        == "bullpen"
        for row in reliever_rows
    )
    assert all(
        row["typical_bullpen_role"] is None
        for row in reliever_rows
    )
    assert all(
        row["typical_role_inference_used"]
        is False
        for row in reliever_rows
    )
    assert all(
        row["game_availability_status"]
        == "active_roster_candidate_unknown"
        for row in reliever_rows
    )

    assert all(
        row["appearance_probability"]
        is not None
        and 0.0
        <= row["appearance_probability"]
        <= 1.0
        for row in pitcher_rows.values()
    )

    assert projections[
        "pitcher_pool_role_reconciliation_applied"
    ] is True
    assert projections[
        "pitcher_projections_authoritative"
    ] is True
    assert projections[
        "batter_projections_authoritative"
    ] is False

    authority = shadow[
        "pitcher_projection_authority"
    ]

    assert authority["status"] == "activated"
    assert authority[
        "authority_scope"
    ] == "pitcher_rows_only"

    assert result[
        "away_win_probability"
    ] == legacy["away_win_probability"]
    assert result[
        "home_win_probability"
    ] == legacy["home_win_probability"]

def test_comparator_applies_explicit_pitcher_pool_role_evidence():
    from copy import deepcopy

    legacy = legacy_payload()
    discovery = deepcopy(
        model_projections
        ._canonical_pitcher_pool_audit_input(
            bullpens()
        )
    )

    discovery["away"]["eligibility"] = {
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
                "pitcher_role": "closer",
                "evidence_source":
                    "pregame_role_evidence_v1",
            },
        ],
    }
    discovery["home"]["eligibility"] = {
        "records": [
            {
                "pitcher_id": "201",
                "retained": False,
                "decision_reason":
                    "probable_starter_not_in_plan",
                "planned_pitcher": False,
                "evidence_present": True,
                "evidence_valid": True,
                "evidence_status":
                    "ineligible",
                "pitcher_role":
                    "probable_starter",
                "evidence_source":
                    "pregame_role_evidence_v1",
            },
        ],
    }

    result = (
        model_projections
        ._attach_production_shadow_comparison(
            legacy_result=legacy,
            production_execution=executed_shadow(
                simulation_count=100,
            ),
            bullpen_discovery=discovery,
        )
    )

    shadow = result["diagnostics"][
        "canonical_shadow"
    ]
    projections = shadow[
        "player_projections"
    ]
    reconciliation = shadow[
        "pitcher_projection_pool_role_reconciliation"
    ]

    pitcher_rows = {
        row["player_id"]: row
        for row in projections["players"]
        if row["player_type"] == "pitcher"
    }
    batter_rows = [
        row
        for row in projections["players"]
        if row["player_type"] == "batter"
    ]

    assert set(pitcher_rows) == {
        "100",
        "101",
        "200",
    }
    assert pitcher_rows["101"][
        "typical_bullpen_role"
    ] == "closer"
    assert pitcher_rows["101"][
        "game_availability_status"
    ] == "explicitly_eligible"
    assert pitcher_rows["101"][
        "pitcher_pool_membership_status"
    ] == "included_explicitly_eligible"

    assert "201" not in pitcher_rows
    assert reconciliation[
        "excluded_pitcher_ids"
    ] == ["201"]
    assert reconciliation[
        "explicitly_ineligible_pitcher_count"
    ] == 1
    assert reconciliation[
        "production_authority_changed"
    ] is True
    assert reconciliation[
        "game_probability_authority_changed"
    ] is False
    assert reconciliation[
        "typical_role_inference_used"
    ] is False
    assert reconciliation[
        "database_writes_performed"
    ] is False

    assert len(batter_rows) == 18

    authority = shadow[
        "pitcher_projection_authority"
    ]

    assert authority["status"] == "activated"
    assert authority[
        "production_activation"
    ] is True
    assert authority[
        "authority_scope"
    ] == "pitcher_rows_only"

    assert projections[
        "pitcher_projections_authoritative"
    ] is True
    assert projections[
        "batter_projections_authoritative"
    ] is False

    assert result[
        "away_win_probability"
    ] == legacy["away_win_probability"]
    assert result[
        "home_win_probability"
    ] == legacy["home_win_probability"]

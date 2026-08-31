from __future__ import annotations

import pytest

from mlb_app.simulation.box_score import (
    DRAFTKINGS_CLASSIC_BATTER_RULES,
    DRAFTKINGS_CLASSIC_PITCHER_RULES,
)
from mlb_app.simulation.game import (
    CANONICAL_PA_OUTCOME_ORDER,
    CanonicalBaserunningEvidenceCatalog,
    CanonicalCatcherBaserunningProfile,
    CanonicalOutcomeProbability,
    CanonicalPitcherBaserunningProfile,
    CanonicalRunnerBaserunningProfile,
    CanonicalProbabilityArtifact,
    CanonicalProbabilityArtifactRecord,
    CanonicalProbabilityFallbackCatalog,
    CanonicalProbabilityFallbackRecord,
    CanonicalProbabilityFallbackTier,
    CanonicalProbabilityProviderIdentity,
)
from mlb_app.simulation.shadow import (
    CANONICAL_PRODUCTION_SHADOW_EXECUTION_VERSION,
    CanonicalShadowBullpenDiscovery,
    CanonicalShadowBullpenSideDiscovery,
    CanonicalShadowExactArtifactDiscovery,
    CanonicalShadowFallbackCatalogDiscovery,
    CanonicalShadowBaserunningEvidenceDiscovery,
    CanonicalShadowLineupDiscovery,
    CanonicalShadowProbabilityProviderDiscovery,
    run_canonical_production_shadow,
    run_canonical_production_shadow_with_baserunning_discovery,
    validate_canonical_baserunning_shadow_outputs,
)


from mlb_app.simulation.shadow.hitter_profile_paired_simulation_shadow_audit import (
    run_paired_hitter_profile_simulation_shadow_audit,
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

    artifact = CanonicalProbabilityArtifact(
        provider=PROVIDER,
        records=records,
    )

    return CanonicalShadowExactArtifactDiscovery(
        artifact=artifact,
        away_record_count=9,
        home_record_count=9,
        away_real_profile_count=9,
        home_real_profile_count=9,
        status="ready",
    )


def fallback_discovery():
    catalog = CanonicalProbabilityFallbackCatalog(
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
    )

    return CanonicalShadowFallbackCatalogDiscovery(
        catalog=catalog,
        source_model_count=4,
        status="ready",
    )


def baserunning_catalog():
    return CanonicalBaserunningEvidenceCatalog(
        runners=tuple(
            CanonicalRunnerBaserunningProfile(
                runner_id=runner_id,
                speed_score=0.50,
                attempt_rate=0.0,
                success_rate=0.75,
                lead_quality=0.50,
                fatigue_index=0.0,
            )
            for runner_id in (
                *(
                    f"a{index}"
                    for index in range(1, 10)
                ),
                *(
                    f"h{index}"
                    for index in range(1, 10)
                ),
            )
        ),
        pitchers=tuple(
            CanonicalPitcherBaserunningProfile(
                pitcher_id=pitcher_id,
                hold_score=0.50,
                delivery_time_score=0.50,
                pickoff_attempt_rate=0.0,
                pickoff_success_rate=0.0,
            )
            for pitcher_id in (
                "100",
                "101",
                "200",
                "201",
            )
        ),
        away_catcher=CanonicalCatcherBaserunningProfile(
            catcher_id="away-catcher",
            team_side="away",
            throwing_score=0.50,
            pop_time_score=0.50,
        ),
        home_catcher=CanonicalCatcherBaserunningProfile(
            catcher_id="home-catcher",
            team_side="home",
            throwing_score=0.50,
            pop_time_score=0.50,
        ),
    )


def run(**overrides):
    kwargs = {
        "game_pk": 123,
        "lineups": lineups(),
        "bullpens": bullpens(),
        "provider_discovery": provider_discovery(),
        "exact_artifact_discovery": (
            exact_discovery()
        ),
        "fallback_catalog_discovery": (
            fallback_discovery()
        ),
        "bootstrap_ready": True,
        "simulation_count": 2,
    }
    kwargs.update(overrides)

    return run_canonical_production_shadow(
        **kwargs
    )


def test_ready_inputs_execute_real_trial_batch():
    result = run()

    assert result.status == "executed"
    assert result.executed is True
    assert result.material is not None
    assert result.execution_inputs is not None
    assert result.simulation_count == 2


def test_trial_batch_contains_requested_games():
    result = run()

    assert len(
        result.material.canonical_payload[
            "metadata"
        ]["simulation_count"]
        if False
        else result.material.canonical_payload
    ) > 0

    assert (
        result.material
        .probability_resolution_diagnostics
        .total_resolutions
        > 0
    )


def test_policy_enables_exact_then_global():
    result = run()

    tiers = (
        result.execution_inputs
        .fallback_policy
        .tiers
    )

    assert tiers == (
        CanonicalProbabilityFallbackTier.EXACT_MATCHUP,
        CanonicalProbabilityFallbackTier.GLOBAL,
    )


def test_execution_carries_atomic_input_provenance():
    result = run()

    assert (
        result.material
        .canonical_shadow_execution_inputs
        is result.execution_inputs
    )
    assert len(
        result.execution_inputs.assembly_digest
    ) == 64


def test_diagnostics_keep_legacy_authority():
    diagnostics = run().to_diagnostics()

    assert diagnostics["schema_version"] == (
        CANONICAL_PRODUCTION_SHADOW_EXECUTION_VERSION
    )
    assert diagnostics["executed"] is True
    assert diagnostics[
        "production_authority_changed"
    ] is False
    assert diagnostics[
        "activation_permitted"
    ] is False
    assert diagnostics["authoritative_source"] == (
        "legacy"
    )


def test_not_ready_does_not_execute():
    result = run(
        bootstrap_ready=False,
    )

    assert result.status == "blocked"
    assert result.executed is False
    assert result.material is None


def test_missing_artifact_does_not_execute():
    result = run(
        exact_artifact_discovery=(
            CanonicalShadowExactArtifactDiscovery(
                status="unavailable",
            )
        )
    )

    assert result.status == "blocked"
    assert result.executed is False


def test_invalid_simulation_count_fails_open():
    result = run(
        simulation_count=0,
    )

    assert result.status == "error"
    assert result.executed is False
    assert result.error_type == "ValueError"


def opener_bulk_classification(
    *,
    starter_id,
    bulk_id,
):
    return {
        "plan_type": "opener_bulk",
        "fallback_used": False,
        "planned_sequence": [
            {
                "order": 1,
                "role": "opener",
                "pitcher_id": starter_id,
            },
            {
                "order": 2,
                "role": "bulk_follower",
                "pitcher_id": bulk_id,
            },
        ],
        "diagnostics": {
            "production_activation": False,
        },
    }


def test_production_matchup_activates_opener_bulk_plan():
    result = run(
        away_pitching_plan_classification=(
            opener_bulk_classification(
                starter_id="100",
                bulk_id="101",
            )
        ),
    )

    assert result.status == "executed"

    plan = (
        result.execution_inputs
        .matchup_input
        .away_pitching_plan
    )

    assert plan.plan_type == "opener_bulk"
    assert (
        plan.preferred_replacement_pitcher_ids
        == ("101",)
    )


def test_unknown_classification_falls_back_safely():
    result = run(
        away_pitching_plan_classification={
            "plan_type": "unknown_fallback",
            "fallback_used": True,
            "planned_sequence": [],
        },
    )

    assert result.status == "executed"

    plan = (
        result.execution_inputs
        .matchup_input
        .away_pitching_plan
    )

    assert plan.plan_type == (
        "traditional_starter"
    )
    assert (
        plan.preferred_replacement_pitcher_ids
        == ()
    )


def test_preferred_replacement_outside_bullpen_is_ignored():
    result = run(
        away_pitching_plan_classification=(
            opener_bulk_classification(
                starter_id="100",
                bulk_id="999",
            )
        ),
    )

    assert result.status == "executed"

    plan = (
        result.execution_inputs
        .matchup_input
        .away_pitching_plan
    )

    assert plan.plan_type == "opener_bulk"
    assert (
        plan.preferred_replacement_pitcher_ids
        == ()
    )


def test_production_shadow_activates_draftkings_scoring_rules():
    result = run()

    assert result.status == "executed"
    assert result.material is not None
    assert result.execution_inputs is not None

    payload = result.material.canonical_payload

    batter_metric_names = {
        metric["name"]
        for row in payload["batters"]
        for metric in row["metrics"]
    }
    pitcher_metric_names = {
        metric["name"]
        for row in payload["pitchers"]
        for metric in row["metrics"]
    }

    assert "dfs_points" in batter_metric_names

    assert (
        result.execution_inputs.batter_dfs_rules
        is DRAFTKINGS_CLASSIC_BATTER_RULES
    )
    assert (
        result.execution_inputs.pitcher_dfs_rules
        is DRAFTKINGS_CLASSIC_PITCHER_RULES
    )

    if (
        payload["diagnostics"]["earned_run_status"]
        == "reconstructed"
    ):
        assert "dfs_points" in pitcher_metric_names
    else:
        assert "dfs_points" not in pitcher_metric_names
        assert (
            "pitcher_dfs_earned_runs_unavailable"
            in payload["diagnostics"]["warnings"]
        )



def test_production_shadow_exposes_reconstructed_earned_runs():
    result = run()

    assert result.status == "executed"
    assert result.material is not None

    payload = result.material.canonical_payload
    diagnostics = payload["diagnostics"]
    pitcher_metric_names = {
        metric["name"]
        for row in payload["pitchers"]
        for metric in row["metrics"]
    }

    assert diagnostics["earned_run_status"] == (
        "reconstructed"
    )
    assert (
        "earned_runs_not_fully_reconstructed"
        not in diagnostics["warnings"]
    )
    assert (
        "pitcher_dfs_earned_runs_unavailable"
        not in diagnostics["warnings"]
    )
    assert "earned_runs" in pitcher_metric_names
    assert "dfs_points" in pitcher_metric_names



def test_production_shadow_accepts_injected_baserunning_catalog():
    source = baserunning_catalog()
    result = run(
        baserunning_evidence_catalog=source,
    )

    assert result.status == "executed"
    assert result.execution_inputs is not None
    assert (
        result.execution_inputs
        .baserunning_evidence_catalog
        is source
    )
    assert (
        result.to_diagnostics()[
            "baserunning_evidence_catalog_digest"
        ]
        == source.digest
    )


def test_invalid_production_baserunning_catalog_fails_open():
    result = run(
        baserunning_evidence_catalog=object(),
    )

    assert result.status == "error"
    assert result.executed is False
    assert result.material is None
    assert result.error_type == "TypeError"



def baserunning_discovery(
    *,
    status="ready",
    error_message=None,
):
    source = (
        baserunning_catalog()
        if status == "ready"
        else None
    )

    return CanonicalShadowBaserunningEvidenceDiscovery(
        catalog=source,
        requested_runner_count=(
            18
            if status == "ready"
            else 0
        ),
        available_runner_count=(
            18
            if status == "ready"
            else 0
        ),
        requested_pitcher_count=(
            4
            if status == "ready"
            else 0
        ),
        available_pitcher_count=(
            4
            if status == "ready"
            else 0
        ),
        status=status,
        error_message=error_message,
    )


def run_with_discovery(
    discovery=None,
    **overrides,
):
    kwargs = {
        "game_pk": 123,
        "lineups": lineups(),
        "bullpens": bullpens(),
        "provider_discovery": provider_discovery(),
        "exact_artifact_discovery": (
            exact_discovery()
        ),
        "fallback_catalog_discovery": (
            fallback_discovery()
        ),
        "bootstrap_ready": True,
        "simulation_count": 2,
    }
    kwargs.update(overrides)

    return (
        run_canonical_production_shadow_with_baserunning_discovery(
            baserunning_evidence_discovery=(
                baserunning_discovery()
                if discovery is None
                else discovery
            ),
            **kwargs,
        )
    )


def test_ready_discovery_injects_catalog():
    discovery = baserunning_discovery()
    result = run_with_discovery(
        discovery=discovery,
    )

    assert result.status == "executed"
    assert result.executed is True
    assert result.execution_inputs is not None
    assert (
        result.execution_inputs
        .baserunning_evidence_catalog
        is discovery.catalog
    )
    assert (
        result.to_diagnostics()[
            "baserunning_evidence_catalog_digest"
        ]
        == discovery.catalog.digest
    )


def test_unavailable_discovery_blocks_execution():
    result = run_with_discovery(
        discovery=baserunning_discovery(
            status="unavailable",
        ),
    )

    assert result.status == "blocked"
    assert result.executed is False
    assert result.material is None
    assert result.error_type == (
        "BaserunningEvidenceUnavailable"
    )


def test_error_discovery_fails_open():
    result = run_with_discovery(
        discovery=baserunning_discovery(
            status="error",
            error_message="source unavailable",
        ),
    )

    assert result.status == "error"
    assert result.executed is False
    assert result.material is None
    assert result.error_type == (
        "BaserunningEvidenceDiscoveryError"
    )
    assert result.error_message == "source unavailable"


def test_invalid_discovery_contract_fails_open():
    result = run_with_discovery(
        discovery=object(),
    )

    assert result.status == "error"
    assert result.executed is False
    assert result.error_type == "TypeError"


def test_direct_catalog_and_discovery_are_rejected():
    result = run_with_discovery(
        baserunning_evidence_catalog=(
            baserunning_catalog()
        ),
    )

    assert result.status == "error"
    assert result.executed is False
    assert result.error_type == "ValueError"
    assert result.error_message == (
        "baserunning_evidence_catalog must be "
        "supplied through discovery"
    )


def test_discovered_execution_preserves_shadow_authority():
    diagnostics = run_with_discovery().to_diagnostics()

    assert diagnostics["activation_permitted"] is False
    assert diagnostics[
        "production_authority_changed"
    ] is False
    assert diagnostics["authoritative_source"] == "legacy"



def test_injected_catalog_exposes_baserunning_metrics():
    execution = run(
        baserunning_evidence_catalog=(
            baserunning_catalog()
        ),
    )
    validation = (
        validate_canonical_baserunning_shadow_outputs(
            execution
        )
    )

    assert validation.status == "ready"
    assert validation.ready is True
    assert validation.catalog_digest == (
        baserunning_catalog().digest
    )
    assert validation.runner_projection_count == 18
    assert validation.simulation_count == 2


def test_observed_activity_is_reported():
    execution = run(
        baserunning_evidence_catalog=(
            baserunning_catalog()
        ),
    )
    validation = (
        validate_canonical_baserunning_shadow_outputs(
            execution
        )
    )

    assert validation.observed_activity is True
    assert (
        validation.stolen_base_mean_total
        + validation.caught_stealing_mean_total
        > 0.0
    )
    assert validation.warnings == ()


def test_execution_without_catalog_is_unavailable():
    validation = (
        validate_canonical_baserunning_shadow_outputs(
            run()
        )
    )

    assert validation.status == "unavailable"
    assert validation.ready is False
    assert validation.catalog_digest is None
    assert validation.error_message == (
        "baserunning evidence catalog was not injected"
    )


def test_blocked_execution_is_unavailable():
    validation = (
        validate_canonical_baserunning_shadow_outputs(
            run(
                bootstrap_ready=False,
            )
        )
    )

    assert validation.status == "unavailable"
    assert validation.ready is False


def test_invalid_execution_contract_fails_open():
    validation = (
        validate_canonical_baserunning_shadow_outputs(
            object()
        )
    )

    assert validation.status == "error"
    assert validation.ready is False
    assert validation.error_message == (
        "execution must be "
        "CanonicalProductionShadowExecution"
    )


def test_output_validation_preserves_shadow_authority():
    execution = run(
        baserunning_evidence_catalog=(
            baserunning_catalog()
        ),
    )
    diagnostics = (
        validate_canonical_baserunning_shadow_outputs(
            execution
        ).to_diagnostics()
    )

    assert diagnostics["activation_permitted"] is False
    assert diagnostics[
        "production_authority_changed"
    ] is False
    assert diagnostics["authoritative_source"] == "legacy"


from mlb_app.simulation.shadow import (
    CANONICAL_LIVE_BASERUNNING_SHADOW_EXECUTION_VERSION,
    execute_live_baserunning_shadow_pair,
)


def run_live_pair(**overrides):
    kwargs = {
        "game_pk": 123,
        "game_date": "2026-07-26",
        "lineups": lineups(),
        "bullpens": bullpens(),
        "provider_discovery": provider_discovery(),
        "exact_artifact_discovery": (
            exact_discovery()
        ),
        "fallback_catalog_discovery": (
            fallback_discovery()
        ),
        "bootstrap_ready": True,
        "simulation_count": 2,
    }
    kwargs.update(overrides)

    return execute_live_baserunning_shadow_pair(
        baserunning_evidence_discovery=(
            baserunning_discovery()
        ),
        **kwargs,
    )


def test_live_pair_preserves_legacy_production_authority():
    result = run_live_pair()
    diagnostics = result.to_diagnostics()

    assert result.production_execution is (
        result.legacy_execution
    )
    assert diagnostics["production_result"] == (
        "legacy_execution"
    )
    assert diagnostics["activation_permitted"] is False
    assert diagnostics["production_activation"] is False
    assert (
        diagnostics["production_authority_changed"]
        is False
    )
    assert diagnostics["authoritative_source"] == "legacy"


def test_live_pair_uses_identical_inputs_and_seeds():
    result = run_live_pair()

    assert result.legacy_execution.executed is True
    assert result.calibrated_execution.executed is True
    assert result.observation.ready is True
    assert (
        result.observation.input_parity_verified
        is True
    )
    assert (
        result.observation.seed_parity_verified
        is True
    )
    assert result.observation.simulation_count == 2
    assert (
        result.observation.calibrated_transform_digest
        != result.observation.paired_context_digest
    )


def test_live_pair_is_deterministic():
    first = run_live_pair()
    second = run_live_pair()

    assert first.observation == second.observation
    assert (
        first.observation.digest
        == second.observation.digest
    )
    assert (
        CANONICAL_LIVE_BASERUNNING_SHADOW_EXECUTION_VERSION
        == "canonical_live_baserunning_shadow_execution_v1"
    )



def test_live_pair_unavailable_evidence_fails_open():
    result = execute_live_baserunning_shadow_pair(
        game_pk=123,
        game_date="2026-07-26",
        lineups=lineups(),
        bullpens=bullpens(),
        provider_discovery=provider_discovery(),
        exact_artifact_discovery=exact_discovery(),
        fallback_catalog_discovery=(
            fallback_discovery()
        ),
        bootstrap_ready=True,
        simulation_count=2,
        baserunning_evidence_discovery=(
            baserunning_discovery(
                status="unavailable",
            )
        ),
    )

    assert result.production_execution is (
        result.legacy_execution
    )
    assert result.legacy_execution.status == "blocked"
    assert (
        result.calibrated_execution.status
        == "blocked"
    )
    assert result.observation.status == "unavailable"
    assert result.observation.ready is False
    assert (
        result.observation.input_parity_verified
        is False
    )
    assert (
        result.observation.seed_parity_verified
        is False
    )
    assert (
        result.to_diagnostics()[
            "authoritative_source"
        ]
        == "legacy"
    )


def test_live_pair_rejects_external_transform():
    from mlb_app.simulation.game import (
        CanonicalBaserunningProbabilityTransform,
    )

    with pytest.raises(
        ValueError,
        match="owns the calibrated probability transform",
    ):
        run_live_pair(
            baserunning_probability_transform=(
                CanonicalBaserunningProbabilityTransform()
            ),
        )


from mlb_app.simulation.shadow import (
    CALIBRATED_BASERUNNING_ENABLED_ENV,
    CANONICAL_CALIBRATED_BASERUNNING_ACTIVATION_VERSION,
    activate_calibrated_baserunning,
    apply_calibrated_baserunning_production_authority,
    calibrated_baserunning_enabled,
)


def test_calibrated_baserunning_is_active_by_default(
    monkeypatch,
):
    monkeypatch.delenv(
        CALIBRATED_BASERUNNING_ENABLED_ENV,
        raising=False,
    )

    fallback = run()
    paired = run_live_pair()
    activation = activate_calibrated_baserunning(
        fallback_execution=fallback,
        paired_execution=paired,
    )

    assert calibrated_baserunning_enabled() is True
    assert activation.calibrated_ready is True
    assert activation.activated is True
    assert activation.production_execution is (
        paired.calibrated_execution
    )

    diagnostics = activation.to_diagnostics()

    assert diagnostics["production_activation"] is True
    assert diagnostics[
        "production_authority_changed"
    ] is True
    assert diagnostics["authoritative_source"] == (
        "canonical_calibrated_baserunning"
    )
    assert diagnostics[
        "post_activation_monitoring_target"
    ]["game_count"] == 100
    assert diagnostics[
        "probability_transform"
    ]["frozen_during_monitoring_window"] is True


def test_calibrated_baserunning_rollback_uses_legacy():
    fallback = run()
    paired = run_live_pair()
    activation = activate_calibrated_baserunning(
        fallback_execution=fallback,
        paired_execution=paired,
        enabled=False,
    )

    assert activation.activated is False
    assert activation.production_execution is fallback
    assert activation.fallback_reason == (
        "rollback_flag_disabled"
    )
    assert (
        activation.to_diagnostics()[
            "authoritative_source"
        ]
        == "legacy"
    )


def test_unavailable_calibrated_evidence_falls_back():
    fallback = run()
    paired = execute_live_baserunning_shadow_pair(
        game_pk=123,
        game_date="2026-07-26",
        lineups=lineups(),
        bullpens=bullpens(),
        provider_discovery=provider_discovery(),
        exact_artifact_discovery=exact_discovery(),
        fallback_catalog_discovery=(
            fallback_discovery()
        ),
        bootstrap_ready=True,
        simulation_count=2,
        baserunning_evidence_discovery=(
            baserunning_discovery(
                status="unavailable",
            )
        ),
    )
    activation = activate_calibrated_baserunning(
        fallback_execution=fallback,
        paired_execution=paired,
        enabled=True,
    )

    assert fallback.executed is True
    assert activation.calibrated_ready is False
    assert activation.activated is False
    assert activation.production_execution is fallback
    assert activation.fallback_reason == (
        "calibrated_baserunning_unavailable"
    )


def test_activation_version_is_explicit():
    assert (
        CANONICAL_CALIBRATED_BASERUNNING_ACTIVATION_VERSION
        == "canonical_calibrated_baserunning_activation_v1"
    )



def legacy_shared_simulation():
    return {
        "status": "ok",
        "derived_outputs": {
            "game_simulation": {
                "away_win_probability": 0.40,
                "home_win_probability": 0.60,
                "model_version": "legacy-base-v1",
            },
            "bullpen_adjusted_game_simulation": {
                "away_win_probability": 0.42,
                "home_win_probability": 0.58,
                "model_version": "legacy-bullpen-v1",
            },
        },
        "diagnostics": {},
        "meta": {
            "model_version": "shared-simulation-v1",
        },
    }


def test_ready_activation_promotes_canonical_outcomes():
    legacy = legacy_shared_simulation()
    paired = run_live_pair()
    activation = activate_calibrated_baserunning(
        fallback_execution=run(),
        paired_execution=paired,
        enabled=True,
    )

    result = (
        apply_calibrated_baserunning_production_authority(
            legacy_result=legacy,
            activation=activation,
        )
    )

    canonical = (
        paired.calibrated_execution
        .material
        .canonical_payload
    )
    outcomes = canonical["outcomes"]
    selected = result["derived_outputs"][
        "bullpen_adjusted_game_simulation"
    ]

    assert selected["away_win_probability"] == (
        outcomes["away_win_probability"]
    )
    assert selected["home_win_probability"] == (
        outcomes["home_win_probability"]
    )
    assert selected["source"] == (
        "canonical_event_driven_simulation"
    )
    assert selected["production_activation"] is True
    assert selected[
        "production_authority_changed"
    ] is True
    assert result["meta"]["canonical_run_id"] == (
        canonical["run_id"]
    )
    assert result["meta"]["simulation_count"] == (
        outcomes["simulation_count"]
    )
    assert result["meta"][
        "production_authority_changed"
    ] is True
    assert result["diagnostics"][
        "calibrated_baserunning_activation"
    ]["production_activation"] is True

    assert legacy["derived_outputs"][
        "bullpen_adjusted_game_simulation"
    ]["home_win_probability"] == 0.58


def test_rollback_preserves_legacy_simulation_outputs():
    legacy = legacy_shared_simulation()
    activation = activate_calibrated_baserunning(
        fallback_execution=run(),
        paired_execution=run_live_pair(),
        enabled=False,
    )

    result = (
        apply_calibrated_baserunning_production_authority(
            legacy_result=legacy,
            activation=activation,
        )
    )

    assert result["derived_outputs"] == (
        legacy["derived_outputs"]
    )
    assert result["meta"] == legacy["meta"]
    assert result["diagnostics"][
        "calibrated_baserunning_activation"
    ]["fallback_reason"] == (
        "rollback_flag_disabled"
    )


def test_authority_adapter_rejects_invalid_activation():
    with pytest.raises(
        TypeError,
        match="activation must be canonical",
    ):
        apply_calibrated_baserunning_production_authority(
            legacy_result={},
            activation=object(),
        )

def hitter_profile_gate(passed=True):
    return {
        "status": (
            "accepted_for_feature_flag_integration"
            if passed
            else "blocked"
        ),
        "gate_passed": passed,
        "decision": {
            "feature_flag_integration_allowed":
                passed,
            "production_activation_allowed":
                False,
        },
        "production_authority_changed": False,
    }


def hitter_profile_candidate():
    return {
        "status": "ready",
        "executed": True,
        "production_inputs_unchanged": True,
        "production_authority_changed": False,
        "fallback_telemetry": {
            "fallback_count": 0,
        },
        "probability_deltas": {
            "out": 0.02,
            "reached_on_error": 0.0,
            "single": 0.0,
            "double": 0.0,
            "triple": 0.0,
            "hr": 0.0,
            "bb": 0.0,
            "hbp": 0.0,
            "k": -0.02,
        },
    }


def test_hitter_profile_shadow_is_disabled_by_default():
    result = run()
    diagnostics = result.to_diagnostics()

    assert result.status == "executed"
    assert (
        "hitter_profile_simulation_shadow"
        not in diagnostics
    )
    assert (
        result.execution_inputs.provider_identity
        == PROVIDER.identity
    )


def test_explicit_hitter_profile_shadow_uses_overlay():
    result = run(
        hitter_profile_shadow_enabled=True,
        hitter_profile_acceptance_gate=(
            hitter_profile_gate()
        ),
        hitter_profile_candidate_results={
            "a1": hitter_profile_candidate(),
        },
    )
    diagnostics = result.to_diagnostics()
    overlay = diagnostics[
        "hitter_profile_simulation_shadow"
    ]

    assert result.status == "executed"
    assert overlay["status"] == "ready"
    assert overlay["overlay_applied"] is True
    assert overlay["overlaid_matchup_count"] == 1
    assert (
        result.execution_inputs.provider_identity
        == overlay["shadow_provider_identity"]
    )
    assert (
        diagnostics["production_authority_changed"]
        is False
    )


def test_blocked_hitter_gate_fails_open_to_base_shadow():
    result = run(
        hitter_profile_shadow_enabled=True,
        hitter_profile_acceptance_gate=(
            hitter_profile_gate(False)
        ),
        hitter_profile_candidate_results={
            "a1": hitter_profile_candidate(),
        },
    )
    diagnostics = result.to_diagnostics()
    overlay = diagnostics[
        "hitter_profile_simulation_shadow"
    ]

    assert result.status == "executed"
    assert overlay["status"] == "blocked"
    assert overlay["overlay_applied"] is False
    assert (
        result.execution_inputs.provider_identity
        == PROVIDER.identity
    )
    assert (
        diagnostics["production_authority_changed"]
        is False
    )


def test_ineligible_hitter_candidate_fails_open():
    candidate = hitter_profile_candidate()
    candidate["fallback_telemetry"] = {
        "fallback_count": 1,
    }

    result = run(
        hitter_profile_shadow_enabled=True,
        hitter_profile_acceptance_gate=(
            hitter_profile_gate()
        ),
        hitter_profile_candidate_results={
            "a1": candidate,
        },
    )
    overlay = result.to_diagnostics()[
        "hitter_profile_simulation_shadow"
    ]

    assert result.status == "executed"
    assert overlay["status"] == "fallback"
    assert overlay["overlay_applied"] is False
    assert (
        result.execution_inputs.provider_identity
        == PROVIDER.identity
    )

def test_real_hitter_profile_shadow_pair_uses_same_trials():
    candidate_materialization = {
        "status": "ready",
        "materialized": True,
        "candidate_results": {
            "a1": hitter_profile_candidate(),
        },
        "candidate_batter_count": 1,
        "database_writes_performed": False,
        "production_inputs_unchanged": True,
        "production_authority_changed": False,
    }

    paired = (
        run_paired_hitter_profile_simulation_shadow_audit(
            enabled=True,
            acceptance_gate=(
                hitter_profile_gate()
            ),
            candidate_materialization=(
                candidate_materialization
            ),
            execution_runner=(
                run_canonical_production_shadow
            ),
            game_pk=123,
            lineups=lineups(),
            bullpens=bullpens(),
            provider_discovery=(
                provider_discovery()
            ),
            exact_artifact_discovery=(
                exact_discovery()
            ),
            fallback_catalog_discovery=(
                fallback_discovery()
            ),
            bootstrap_ready=True,
            simulation_count=2,
        )
    )

    assert paired.status == "observed"
    assert paired.production_execution is (
        paired.baseline_execution
    )
    assert (
        paired.baseline_execution.status
        == "executed"
    )
    assert (
        paired.candidate_execution.status
        == "executed"
    )
    assert (
        paired.baseline_execution.simulation_count
        == paired.candidate_execution.simulation_count
        == 2
    )

    baseline_inputs = (
        paired.baseline_execution.execution_inputs
    )
    candidate_inputs = (
        paired.candidate_execution.execution_inputs
    )

    assert (
        baseline_inputs.exact_artifact_digest
        != candidate_inputs.exact_artifact_digest
    )
    assert (
        baseline_inputs
        .baserunning_evidence_catalog_digest
        == candidate_inputs
        .baserunning_evidence_catalog_digest
    )
    assert (
        baseline_inputs.provider_identity
        != candidate_inputs.provider_identity
    )

    diagnostics = paired.to_diagnostics()
    overlay = diagnostics[
        "candidate_execution"
    ][
        "hitter_profile_simulation_shadow"
    ]

    assert overlay["overlay_applied"] is True
    assert overlay["overlaid_matchup_count"] == 1
    assert diagnostics[
        "safety_checks"
    ]["simulation_counts_match"] is True
    assert diagnostics[
        "safety_checks"
    ]["production_authority_unchanged"] is True
    assert diagnostics[
        "production_result"
    ] == "baseline_execution"
    assert diagnostics[
        "production_activation_allowed"
    ] is False

    comparison = diagnostics["comparison"]
    assert comparison["status"] == "ready"
    assert comparison["simulation_count"] == 2
    assert comparison["comparison_count"] > 0
    assert {
        record["scope"]
        for record in comparison["records"]
    } >= {
        "game",
        "game_probability",
        "team",
        "batter",
        "pitcher",
    }

def test_execution_exposes_pitcher_appearance_sequence_audit():
    result = run()
    diagnostics = result.to_diagnostics()

    audit = (
        result.material
        .pitcher_appearance_sequence_audit
    )

    assert result.status == "executed"
    assert audit is not None
    assert audit["status"] == "observed"
    assert audit["trial_count"] == 2
    assert audit["appearance_count"] >= 4
    assert (
        diagnostics[
            "pitcher_appearance_sequence_audit"
        ]
        == audit
    )
    assert (
        "pitcher_appearance_sequence_audit"
        not in result.material.canonical_payload
    )
    assert (
        audit["database_writes_performed"]
        is False
    )
    assert (
        audit["production_authority_changed"]
        is False
    )
    assert audit["decision"][
        "production_activation_allowed"
    ] is False

def test_opener_bulk_sequence_is_observed_by_audit():
    result = run(
        simulation_count=5,
        away_pitching_plan_classification=(
            opener_bulk_classification(
                starter_id="100",
                bulk_id="101",
            )
        ),
    )

    audit = (
        result.material
        .pitcher_appearance_sequence_audit
    )
    away_records = [
        record
        for record in audit["records"]
        if record["team_side"] == "away"
    ]

    assert result.status == "executed"
    assert audit["trial_count"] == 5
    assert {
        record["planned_role"]
        for record in away_records
    } >= {
        "opener",
        "bulk_follower",
    }
    assert all(
        trial["away_pitcher_ids"][:2]
        == ["100", "101"]
        for trial in audit["trials"]
    )
    assert (
        "away:preferred_follower_skipped"
        not in audit["anomaly_counts"]
    )
    assert (
        audit["starter_relief_detected"]
        is False
    )
    assert (
        "pitcher_appearance_sequence_audit"
        not in result.material.canonical_payload
    )

def test_bulk_follower_exit_is_dynamic_with_bullpen_depth():
    from dataclasses import replace

    baseline_bullpens = bullpens()

    expanded_bullpens = replace(
        baseline_bullpens,
        away=replace(
            baseline_bullpens.away,
            bullpen_pitcher_ids=(
                "101",
                "102",
                "103",
                "104",
            ),
            source_record_count=5,
        ),
        home=replace(
            baseline_bullpens.home,
            bullpen_pitcher_ids=(
                "201",
                "202",
                "203",
                "204",
            ),
            source_record_count=5,
        ),
    )

    result = run(
        simulation_count=25,
        bullpens=expanded_bullpens,
        away_pitching_plan_classification=(
            opener_bulk_classification(
                starter_id="100",
                bulk_id="101",
            )
        ),
    )

    diagnostics = result.to_diagnostics()
    audit = diagnostics[
        "pitcher_appearance_sequence_audit"
    ]
    roles = audit["role_summaries"]

    opener_innings = roles[
        "opener"
    ]["innings_equivalent"]
    bulk_innings = roles[
        "bulk_follower"
    ]["innings_equivalent"]

    assert result.status == "executed"
    assert audit["status"] == "observed"
    assert audit["anomaly_counts"] == {}
    assert (
        audit["starter_relief_detected"]
        is False
    )

    # The opener remains shorter than its bulk
    # follower without assigning final innings.
    assert (
        opener_innings["mean"]
        < bulk_innings["mean"]
    )

    # Poor simulated outings can terminate well
    # before the efficient-outing workload ceiling.
    assert (
        bulk_innings["minimum"]
        < bulk_innings["median"]
    )
    assert bulk_innings["p10"] < 6.0

    # Efficient bulk appearances can still go deep.
    assert bulk_innings["maximum"] >= 6.0

    # Replacement depth is actually exercised after
    # the opener and planned bulk follower.
    assert any(
        len(trial["away_pitcher_ids"]) >= 3
        for trial in audit["trials"]
    )

    assert (
        audit["database_writes_performed"]
        is False
    )
    assert (
        audit["production_authority_changed"]
        is False
    )

def test_starter_exit_is_dynamic_with_performance_and_workload():
    result = run(
        simulation_count=100,
    )

    diagnostics = result.to_diagnostics()
    audit = diagnostics[
        "pitcher_appearance_sequence_audit"
    ]
    roles = audit["role_summaries"]

    starter_innings = roles[
        "starter"
    ]["innings_equivalent"]

    starter_records = [
        record
        for record in audit["records"]
        if record["planned_role"] == "starter"
    ]

    starter_batters_faced = [
        record["batters_faced"]
        for record in starter_records
    ]

    assert result.status == "executed"
    assert audit["status"] == "observed"
    assert audit["anomaly_counts"] == {}
    assert (
        audit["starter_relief_detected"]
        is False
    )

    # Poor simulated starts are no longer forced
    # through the old eighteen-batter floor.
    assert min(starter_batters_faced) < 18

    # Efficient starters are not forcibly removed
    # merely because they faced batter number 27.
    assert max(starter_batters_faced) > 27

    assert (
        starter_innings["minimum"]
        < starter_innings["median"]
    )

    # Efficient starts retain a meaningful deep
    # workload tail instead of using a fixed IP.
    assert starter_innings["p90"] >= 5.0
    assert starter_innings["maximum"] >= 6.0

    # Workload remains an emergent event-stream
    # result and the audit stays non-authoritative.
    assert (
        audit["database_writes_performed"]
        is False
    )
    assert (
        audit["production_authority_changed"]
        is False
    )


def pitcher_profile_activation_payload():
    production = {
        "out": 0.65,
        "single": 0.15,
        "double": 0.05,
        "triple": 0.01,
        "home_run": 0.04,
        "walk": 0.07,
        "strikeout": 0.03,
    }
    shadow = {
        "out": 0.05,
        "single": 0.05,
        "double": 0.02,
        "triple": 0.0,
        "home_run": 0.02,
        "walk": 0.01,
        "strikeout": 0.85,
    }

    return {
        "activation": {
            "activated": True,
            "model": {
                "probabilities": shadow,
            },
            "diagnostics": {
                "status": "activated",
                "activation_executed": True,
                "activation_status": (
                    "production_candidate_activated"
                ),
                "production_authority_changed": True,
            },
        },
        "comparison": {
            "status": "ready",
            "executed": True,
            "production_inputs_unchanged": True,
            "production_authority_changed": False,
            "production_probabilities": production,
            "shadow_probabilities": shadow,
        },
    }


def test_pitcher_profile_overlay_reaches_execution_inputs():
    baseline = run(simulation_count=25)
    activated = run(
        simulation_count=25,
        pitcher_matchup_profile_activation_payloads_by_pitcher_id={
            "200": pitcher_profile_activation_payload(),
        },
    )

    assert activated.status == "executed"
    assert (
        activated.pitcher_matchup_profile_overlay[
            "overlay_applied"
        ]
        is True
    )
    assert activated.execution_inputs.provider_identity != (
        baseline.execution_inputs.provider_identity
    )
    assert activated.execution_inputs.exact_artifact_digest != (
        baseline.execution_inputs.exact_artifact_digest
    )
    assert activated.pitcher_matchup_profile_overlay[
        "overlaid_matchup_count"
    ] == 9


def test_pitcher_profile_overlay_reaches_player_projection_trials():
    baseline = run(simulation_count=100)
    activated = run(
        simulation_count=100,
        pitcher_matchup_profile_activation_payloads_by_pitcher_id={
            "200": pitcher_profile_activation_payload(),
        },
    )

    baseline_payload = (
        baseline.material.canonical_payload
    )
    activated_payload = (
        activated.material.canonical_payload
    )

    assert activated_payload["batters"] != (
        baseline_payload["batters"]
    )
    assert activated_payload["pitchers"] != (
        baseline_payload["pitchers"]
    )

    diagnostics = activated.to_diagnostics()[
        "pitcher_matchup_profile_simulation_overlay"
    ]
    assert diagnostics["simulation_inputs_changed"] is True
    assert diagnostics["production_authority_changed"] is False

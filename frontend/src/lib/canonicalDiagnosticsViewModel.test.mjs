import assert from 'node:assert/strict'
import test from 'node:test'

import {
  CANONICAL_DIAGNOSTICS_VIEW_MODEL_VERSION,
  buildCanonicalDiagnosticsViewModel,
} from './canonicalDiagnosticsViewModel.mjs'

function sharedSimulation() {
  return {
    meta: {
      model_version: 'shared-simulation-v1',
    },
    game_state_realism_diagnostics: {
      base_out_state: true,
      runner_advancement_enabled: true,
      extras_enabled: true,
      ghost_runner_enabled: true,
      walkoff_shortening_enabled: true,
      double_play_scoring: true,
      sacrifice_fly_scoring_enabled: true,
      steals_model: 'deferred_not_active',
    },
    diagnostics: {
      canonical_shadow_bootstrap_readiness: {
        schema_version:
          'canonical_shadow_bootstrap_readiness_v1',
        status: 'blocked',
        ready: false,
        game_pk: 123,
        requirements: {
          game_identity: {
            ready: true,
            source: 'game_pk',
          },
          away_lineup: {
            ready: false,
            player_count: 0,
            required_player_count: 9,
          },
          home_lineup: {
            ready: false,
            player_count: 0,
            required_player_count: 9,
          },
          away_starter: {
            ready: true,
            source: 'away_pitcher_id',
          },
          home_starter: {
            ready: true,
            source: 'home_pitcher_id',
          },
          away_bullpen: {
            ready: false,
            pitcher_count: 0,
          },
          home_bullpen: {
            ready: false,
            pitcher_count: 0,
          },
          probability_provider: {
            ready: false,
          },
          exact_probability_artifact: {
            ready: false,
          },
          fallback_probability_catalog: {
            ready: false,
          },
        },
        missing_requirements: [
          'away_lineup',
          'home_lineup',
          'away_bullpen',
          'home_bullpen',
          'probability_provider',
          'exact_probability_artifact',
          'fallback_probability_catalog',
        ],
        activation_permitted: false,
        activation_status: 'diagnostic_only',
        probability_records_exposed: false,
        authoritative_source: 'legacy',
      },
      canonical_shadow: {
        status: 'complete',
        enabled: true,
        canonical_available: true,
        authoritative_source: 'legacy',
        schema_version: 'canonical_shadow_v1',
        legacy_simulation_count: 3000,
        canonical_simulation_count: 3000,
        pitcher_attribution_complete_rate: 0.98,
        replay_validation_pass_rate: 1,
        coverage: {
          game_validation_pass_rate: 1,
          box_score_reconciliation_pass_rate: 1,
        },
        warnings: [
          'legacy_authority_retained',
        ],
        probability_resolution: {
          schema_version:
            'canonical_probability_diagnostics_shadow_v1',
          diagnostics_version:
            'canonical_probability_diagnostics_v1',
          summary: {
            total_resolutions: 100,
            exact_resolutions: 81,
            fallback_resolutions: 19,
            fallback_rate: 0.19,
          },
          tier_usage: [
            {
              tier: 'exact_matchup',
              count: 81,
            },
            {
              tier: 'batter',
              count: 10,
            },
            {
              tier: 'pitcher',
              count: 5,
            },
            {
              tier: 'global',
              count: 4,
            },
          ],
        },
        input_provenance: {
          schema_version:
            'canonical_shadow_input_provenance_v1',
          assembly_version:
            'canonical_shadow_input_assembly_v1',
          assembly_digest: 'a'.repeat(64),
          matchup: {
            game_pk: 123,
          },
          probability_provider: {
            identity: 'provider:v1:artifact-123',
            provider_name: 'provider',
            provider_version: 'v1',
            artifact_id: 'artifact-123',
          },
          artifacts: {
            exact: {
              artifact_version:
                'canonical_probability_artifact_v1',
              digest: 'b'.repeat(64),
              record_count: 50,
            },
            fallback_catalog: {
              schema_version:
                'canonical_probability_fallback_v1',
              digest: 'c'.repeat(64),
              record_count: 12,
            },
          },
          fallback_policy: {
            policy_version:
              'canonical_probability_fallback_v1',
            tiers: [
              'exact_matchup',
              'batter',
              'pitcher',
              'global',
            ],
          },
          game_config: {
            regulation_innings: 9,
            max_extra_innings: 6,
            automatic_runner_enabled: true,
          },
          dfs_rules: {
            batter_rules_supplied: false,
            pitcher_rules_supplied: false,
          },
          probability_records_exposed: false,
          authoritative_source: 'legacy',
        },
      },
    },
  }
}

test('returns a stable empty view model', () => {
  const view = buildCanonicalDiagnosticsViewModel()

  assert.equal(
    view.viewModelVersion,
    CANONICAL_DIAGNOSTICS_VIEW_MODEL_VERSION,
  )
  assert.equal(view.hasCanonicalShadow, false)
  assert.equal(view.status.state, 'not_run')
  assert.equal(
    view.status.authoritativeSource,
    'legacy',
  )
  assert.match(
    view.status.availabilityReason,
    /not attached/,
  )
  assert.deepEqual(view.warnings, [])
})

test('normalizes bootstrap readiness blockers', () => {
  const payload = sharedSimulation()
  delete payload.diagnostics.canonical_shadow

  const view = buildCanonicalDiagnosticsViewModel(
    payload,
  )

  assert.equal(
    view.bootstrapReadiness.available,
    true,
  )
  assert.equal(
    view.bootstrapReadiness.status,
    'blocked',
  )
  assert.equal(
    view.bootstrapReadiness.readyCount,
    3,
  )
  assert.equal(
    view.bootstrapReadiness.blockedCount,
    7,
  )
  assert.equal(
    view.bootstrapReadiness.totalCount,
    10,
  )
  assert.equal(
    view.bootstrapReadiness
      .activationPermitted,
    false,
  )
  assert.match(
    view.status.availabilityReason,
    /7 missing production requirements/,
  )
})

test('preserves ordered bootstrap requirements', () => {
  const payload = sharedSimulation()
  delete payload.diagnostics.canonical_shadow

  const view = buildCanonicalDiagnosticsViewModel(
    payload,
  )

  assert.deepEqual(
    view.bootstrapReadiness.items.map(
      item => item.key
    ),
    [
      'game_identity',
      'away_lineup',
      'home_lineup',
      'away_starter',
      'home_starter',
      'away_bullpen',
      'home_bullpen',
      'probability_provider',
      'exact_probability_artifact',
      'fallback_probability_catalog',
    ],
  )

  assert.equal(
    view.bootstrapReadiness.items[1].detail,
    '0 of 9 players',
  )
})

test('normalizes canonical status', () => {
  const view = buildCanonicalDiagnosticsViewModel(
    sharedSimulation(),
  )

  assert.equal(view.hasCanonicalShadow, true)
  assert.equal(view.status.state, 'complete')
  assert.equal(view.status.enabled, true)
  assert.equal(
    view.status.canonicalAvailable,
    true,
  )
  assert.equal(
    view.status.canonicalSimulationCount,
    3000,
  )
  assert.equal(
    view.status.authoritativeSource,
    'legacy',
  )
})

test('normalizes probability coverage', () => {
  const view = buildCanonicalDiagnosticsViewModel(
    sharedSimulation(),
  )

  assert.equal(view.coverage.available, true)
  assert.equal(
    view.coverage.totalResolutions,
    100,
  )
  assert.equal(view.coverage.exactRate, 0.81)
  assert.equal(
    view.coverage.fallbackRate,
    0.19,
  )
})

test('preserves ordered fallback tiers', () => {
  const view = buildCanonicalDiagnosticsViewModel(
    sharedSimulation(),
  )

  assert.deepEqual(
    view.coverage.tiers.map(item => item.tier),
    [
      'exact_matchup',
      'batter',
      'pitcher',
      'global',
    ],
  )
})

test('normalizes simulation integrity', () => {
  const view = buildCanonicalDiagnosticsViewModel(
    sharedSimulation(),
  )

  const values = Object.fromEntries(
    view.integrity.metrics.map(metric => [
      metric.key,
      metric.value,
    ]),
  )

  assert.equal(
    values.game_validation,
    1,
  )
  assert.equal(
    values.box_score_reconciliation,
    1,
  )
  assert.equal(
    values.replay_validation,
    1,
  )
  assert.equal(
    values.pitcher_attribution,
    0.98,
  )
})

test('normalizes atomic input provenance', () => {
  const view = buildCanonicalDiagnosticsViewModel(
    sharedSimulation(),
  )

  assert.equal(view.provenance.available, true)
  assert.equal(view.provenance.gamePk, 123)
  assert.equal(
    view.provenance.provider.name,
    'provider',
  )
  assert.equal(
    view.provenance.exactArtifact.recordCount,
    50,
  )
  assert.equal(
    view.provenance.fallbackCatalog.recordCount,
    12,
  )
  assert.equal(
    view.provenance.probabilityRecordsExposed,
    false,
  )
})

test('normalizes realism feature aliases and states', () => {
  const view = buildCanonicalDiagnosticsViewModel(
    sharedSimulation(),
  )

  const features = Object.fromEntries(
    view.realism.features.map(feature => [
      feature.key,
      feature.status,
    ]),
  )

  assert.equal(
    features.base_out_state,
    'enabled',
  )
  assert.equal(
    features.runner_advancement,
    'enabled',
  )
  assert.equal(
    features.extra_innings,
    'enabled',
  )
  assert.equal(
    features.automatic_runner,
    'enabled',
  )
  assert.equal(
    features.walk_offs,
    'enabled',
  )
  assert.equal(
    features.multi_out_scoring,
    'enabled',
  )
  assert.equal(
    features.stolen_bases,
    'deferred',
  )
})

test('explicit unavailable runtime realism does not fall through to implementation flags', () => {
  const payload = sharedSimulation()

  payload.game_state_realism_diagnostics = {
    extra_innings_enabled: null,
    extras_enabled: true,
    automatic_runner_enabled: null,
    ghost_runner_enabled: true,
    walk_off_enabled: null,
    walkoff_shortening_enabled: true,
  }

  const view = buildCanonicalDiagnosticsViewModel(
    payload,
  )

  const features = Object.fromEntries(
    view.realism.features.map(feature => [
      feature.key,
      feature.status,
    ]),
  )

  assert.equal(
    features.extra_innings,
    'unknown',
  )
  assert.equal(
    features.automatic_runner,
    'unknown',
  )
  assert.equal(
    features.walk_offs,
    'unknown',
  )
})

test('collects and deduplicates warnings', () => {
  const payload = sharedSimulation()

  payload.diagnostics.canonical_shadow.warnings = [
    'legacy_authority_retained',
    'legacy_authority_retained',
  ]

  payload.diagnostics.canonical_shadow
    .probability_resolution = {
      status: 'error',
      error_message: 'probability diagnostics failed',
    }

  const view = buildCanonicalDiagnosticsViewModel(
    payload,
  )

  assert.deepEqual(view.warnings, [
    'legacy_authority_retained',
    'probability diagnostics failed',
  ])
})

test('does not mutate the source payload', () => {
  const payload = sharedSimulation()
  const snapshot = structuredClone(payload)

  buildCanonicalDiagnosticsViewModel(payload)

  assert.deepEqual(payload, snapshot)
})

test('surfaces fail-open production execution errors', () => {
  const payload = sharedSimulation()

  delete payload.diagnostics.canonical_shadow

  payload.diagnostics
    .canonical_shadow_bootstrap_readiness.status =
      'ready'

  payload.diagnostics
    .canonical_shadow_bootstrap_readiness.ready =
      true

  payload.diagnostics
    .canonical_shadow_bootstrap_readiness
    .missing_requirements = []

  for (
    const requirement of Object.values(
      payload.diagnostics
        .canonical_shadow_bootstrap_readiness
        .requirements
    )
  ) {
    requirement.ready = true
  }

  payload.diagnostics
    .canonical_shadow_production_execution = {
      schema_version:
        'canonical_production_shadow_execution_v1',
      status: 'error',
      executed: false,
      simulation_count: 0,
      canonical_available: false,
      provider_identity:
        'model_projections_pa_outcome:pa_outcome_v1',
      error_type: 'ValueError',
      error_message:
        'example production execution failure',
      activation_permitted: false,
      production_authority_changed: false,
      authoritative_source: 'legacy',
    }

  const view = buildCanonicalDiagnosticsViewModel(
    payload,
  )

  assert.equal(view.status.state, 'error')
  assert.equal(
    view.productionExecution.available,
    true,
  )
  assert.equal(
    view.productionExecution.status,
    'error',
  )
  assert.equal(
    view.productionExecution.errorType,
    'ValueError',
  )
  assert.equal(
    view.productionExecution.errorMessage,
    'example production execution failure',
  )
  assert.match(
    view.status.availabilityReason,
    /ValueError: example production execution failure/,
  )
  assert.deepEqual(
    view.warnings,
    ['example production execution failure'],
  )
  assert.equal(
    view.status.authoritativeSource,
    'legacy',
  )
})

test('distinguishes executed-but-unattached material', () => {
  const payload = sharedSimulation()

  delete payload.diagnostics.canonical_shadow

  payload.diagnostics
    .canonical_shadow_production_execution = {
      schema_version:
        'canonical_production_shadow_execution_v1',
      status: 'executed',
      executed: true,
      simulation_count: 25,
      canonical_available: true,
      canonical_model_version:
        'canonical-event-model-v1',
      activation_permitted: false,
      production_authority_changed: false,
      authoritative_source: 'legacy',
    }

  const view = buildCanonicalDiagnosticsViewModel(
    payload,
  )

  assert.equal(view.status.state, 'executed')
  assert.equal(
    view.productionExecution.executed,
    true,
  )
  assert.equal(
    view.productionExecution.simulationCount,
    25,
  )
  assert.equal(
    view.status.modelVersion,
    'canonical-event-model-v1',
  )
  assert.match(
    view.status.availabilityReason,
    /executed, but comparison diagnostics were not attached/,
  )
})

test('preserves blocked readiness presentation', () => {
  const payload = sharedSimulation()

  delete payload.diagnostics.canonical_shadow

  payload.diagnostics
    .canonical_shadow_production_execution = {
      schema_version:
        'canonical_production_shadow_execution_v1',
      status: 'blocked',
      executed: false,
      simulation_count: 0,
      canonical_available: false,
      authoritative_source: 'legacy',
    }

  const view = buildCanonicalDiagnosticsViewModel(
    payload,
  )

  assert.equal(view.status.state, 'blocked')
  assert.match(
    view.status.availabilityReason,
    /7 missing production requirements/,
  )
})


test('exposes canonical production monitoring progress', () => {
  const source = sharedSimulation()

  source.meta = {
    ...(source.meta || {}),
    production_activation: true,
  }
  source.diagnostics.canonical_shadow = {
    ...source.diagnostics.canonical_shadow,
    production_activation: true,
    authoritative_source:
      'canonical_event_driven_calibrated_baserunning',
  }
  source.diagnostics[
    'canonical_baserunning_production_monitoring'
  ] = {
    schema_version:
      'canonical_baserunning_production_monitoring_v1',
    recorded: true,
    record_created: true,
    observation_digest: 'digest-1',
    eligibility: {
      eligible: true,
      failures: [],
    },
    summary: {
      target_game_count: 100,
      ready_game_count: 1,
      remaining_game_count: 99,
      stored_observation_count: 1,
      unique_game_count: 1,
      progress_rate: 0.01,
      monitoring_complete: false,
      transform_frozen: true,
      transform_digests: ['transform-1'],
      parameter_reselection_permitted: false,
    },
    settlement: {
      settled_game_count: 1,
      target_game_count: 100,
      remaining_game_count: 99,
      progress_rate: 0.01,
      settlement_complete: false,
      projected_stolen_bases: 1.4,
      observed_stolen_bases: 2,
      stolen_base_bias: -0.6,
      stolen_base_mae: 0.6,
      projected_caught_stealing: 0.3,
      observed_caught_stealing: 1,
      caught_stealing_bias: -0.7,
      caught_stealing_mae: 0.7,
      attempt_mae: 1.3,
      parameter_reselection_permitted: false,
    },
    calibration_finalization: {
      schema_version:
        'canonical_baserunning_production_calibration_finalization_v1',
      status: 'ready',
      ready: true,
      decision: 'retain_incumbent',
      incumbent_transform_digest:
        'a'.repeat(64),
      incumbent_retained: true,
      candidate_reselected: false,
      finalization_digest: 'b'.repeat(64),
      calibration_gate: {
        calibration_gate_passed: true,
      },
    },
  }

  const view = (
    buildCanonicalDiagnosticsViewModel(source)
  )

  assert.equal(view.status.productionActive, true)
  assert.equal(
    view.productionMonitoring.available,
    true,
  )
  assert.equal(
    view.productionMonitoring.readyGameCount,
    1,
  )
  assert.equal(
    view.productionMonitoring.remainingGameCount,
    99,
  )
  assert.equal(
    view.productionMonitoring.progressRate,
    0.01,
  )
  assert.equal(
    view.productionMonitoring.transformFrozen,
    true,
  )
  assert.equal(
    view.productionMonitoring.settledGameCount,
    1,
  )
  assert.equal(
    view.productionMonitoring
      .settlementRemainingGameCount,
    99,
  )
  assert.equal(
    view.productionMonitoring
      .settlementProgressRate,
    0.01,
  )
  assert.equal(
    view.productionMonitoring.stolenBaseBias,
    -0.6,
  )
  assert.equal(
    view.productionMonitoring.attemptMae,
    1.3,
  )
  assert.equal(
    view.productionMonitoring
      .calibrationFinalizationAvailable,
    true,
  )
  assert.equal(
    view.productionMonitoring.calibrationDecision,
    'retain_incumbent',
  )
  assert.equal(
    view.productionMonitoring.calibrationGatePassed,
    true,
  )
  assert.equal(
    view.productionMonitoring.incumbentRetained,
    true,
  )
  assert.equal(
    view.productionMonitoring
      .incumbentTransformDigest,
    'a'.repeat(64),
  )
  assert.equal(
    view.productionMonitoring.candidateReselected,
    false,
  )
  assert.equal(
    view.productionMonitoring
      .calibrationFinalizationDigest,
    'b'.repeat(64),
  )
  assert.equal(
    view.productionMonitoring
      .parameterReselectionPermitted,
    false,
  )
})

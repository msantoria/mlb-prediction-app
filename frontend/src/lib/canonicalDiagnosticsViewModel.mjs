export const CANONICAL_DIAGNOSTICS_VIEW_MODEL_VERSION =
  'canonical_diagnostics_view_model_v1'

const BOOTSTRAP_REQUIREMENTS = [
  ['game_identity', 'Game identity'],
  ['away_lineup', 'Away lineup'],
  ['home_lineup', 'Home lineup'],
  ['away_starter', 'Away starter'],
  ['home_starter', 'Home starter'],
  ['away_bullpen', 'Away bullpen plan'],
  ['home_bullpen', 'Home bullpen plan'],
  ['probability_provider', 'Probability provider'],
  [
    'exact_probability_artifact',
    'Exact probability artifact',
  ],
  [
    'fallback_probability_catalog',
    'Fallback probability catalog',
  ],
]

const REALISM_FEATURES = [
  {
    key: 'base_out_state',
    label: 'Base/out state',
    aliases: [
      'base_out_state',
      'base_out_state_enabled',
      'base_state',
    ],
  },
  {
    key: 'runner_advancement',
    label: 'Runner advancement',
    aliases: [
      'runner_advancement',
      'runner_advancement_enabled',
    ],
  },
  {
    key: 'extra_innings',
    label: 'Extra innings',
    aliases: [
      'extra_innings',
      'extra_innings_enabled',
      'extras_enabled',
    ],
  },
  {
    key: 'automatic_runner',
    label: 'Automatic runner',
    aliases: [
      'automatic_runner',
      'automatic_runner_enabled',
      'ghost_runner',
      'ghost_runner_enabled',
    ],
  },
  {
    key: 'walk_offs',
    label: 'Walk-off endings',
    aliases: [
      'walk_offs',
      'walk_off_enabled',
      'walk_off_shortening',
      'walkoff_shortening_enabled',
    ],
  },
  {
    key: 'multi_out_scoring',
    label: 'Multi-out scoring',
    aliases: [
      'multi_out_scoring',
      'multi_out_scoring_enabled',
      'double_play_scoring',
    ],
  },
  {
    key: 'sacrifice_fly_scoring',
    label: 'Sacrifice-fly scoring',
    aliases: [
      'sacrifice_fly_scoring',
      'sacrifice_fly_scoring_enabled',
    ],
  },
  {
    key: 'stolen_bases',
    label: 'Stolen bases',
    aliases: [
      'stolen_bases',
      'stolen_base_model',
      'steals_model',
    ],
  },
]

function objectValue(value) {
  return (
    value &&
    typeof value === 'object' &&
    !Array.isArray(value)
  )
    ? value
    : {}
}

function arrayValue(value) {
  return Array.isArray(value) ? value : []
}

function finiteNumber(value) {
  if (
    value === null ||
    value === undefined ||
    value === ''
  ) {
    return null
  }

  const number = Number(value)

  return Number.isFinite(number)
    ? number
    : null
}

function firstPresent(...values) {
  return values.find(
    value =>
      value !== null &&
      value !== undefined &&
      value !== ''
  )
}

function humanize(value) {
  if (
    value === null ||
    value === undefined ||
    value === ''
  ) {
    return null
  }

  return String(value)
    .replace(/_/g, ' ')
    .replace(/\b\w/g, letter => letter.toUpperCase())
}

function normalizeFeatureStatus(value) {
  if (value === true) {
    return {
      status: 'enabled',
      detail: null,
    }
  }

  if (value === false) {
    return {
      status: 'disabled',
      detail: null,
    }
  }

  if (
    value === null ||
    value === undefined ||
    value === ''
  ) {
    return {
      status: 'unknown',
      detail: null,
    }
  }

  const normalized = String(value)
    .trim()
    .toLowerCase()

  if (
    [
      'enabled',
      'active',
      'implemented',
      'complete',
      'supported',
      'true',
    ].includes(normalized)
  ) {
    return {
      status: 'enabled',
      detail: humanize(value),
    }
  }

  if (
    normalized.includes('deferred') ||
    normalized.includes('not_active') ||
    normalized.includes('planned')
  ) {
    return {
      status: 'deferred',
      detail: humanize(value),
    }
  }

  if (
    [
      'disabled',
      'inactive',
      'unsupported',
      'false',
    ].includes(normalized)
  ) {
    return {
      status: 'disabled',
      detail: humanize(value),
    }
  }

  return {
    status: 'unknown',
    detail: humanize(value),
  }
}

function readAlias(source, aliases) {
  for (const alias of aliases) {
    if (
      Object.prototype.hasOwnProperty.call(
        source,
        alias,
      )
    ) {
      return source[alias]
    }
  }

  return undefined
}

function uniqueStrings(values) {
  return [
    ...new Set(
      values
        .flatMap(value =>
          Array.isArray(value)
            ? value
            : [value]
        )
        .filter(
          value =>
            value !== null &&
            value !== undefined &&
            value !== ''
        )
        .map(value => String(value))
    ),
  ]
}

function buildBootstrapReadiness(
  sharedSimulation,
) {
  const diagnostics = objectValue(
    sharedSimulation.diagnostics
  )

  const report = {
    ...objectValue(
      diagnostics
        .canonical_shadow_bootstrap_readiness
    ),
    ...objectValue(
      sharedSimulation
        .canonical_shadow_bootstrap_readiness
    ),
  }

  const requirements = objectValue(
    report.requirements
  )

  const items = BOOTSTRAP_REQUIREMENTS.map(
    ([key, labelText]) => {
      const requirement = objectValue(
        requirements[key]
      )

      const ready = requirement.ready === true

      let detail = null

      if (
        key.endsWith('_lineup') &&
        finiteNumber(
          requirement.player_count
        ) !== null
      ) {
        detail = (
          `${requirement.player_count} of ` +
          `${requirement.required_player_count || 9} players`
        )
      } else if (
        key.endsWith('_bullpen') &&
        finiteNumber(
          requirement.pitcher_count
        ) !== null
      ) {
        detail = (
          `${requirement.pitcher_count} pitchers`
        )
      } else if (requirement.source) {
        detail = humanize(requirement.source)
      }

      return {
        key,
        label: labelText,
        ready,
        status: ready ? 'ready' : 'blocked',
        detail,
        source: requirement.source || null,
      }
    }
  )

  const readyCount = items.filter(
    item => item.ready
  ).length

  const missingRequirements = arrayValue(
    report.missing_requirements
  ).map(String)

  return {
    available: Object.keys(report).length > 0,
    schemaVersion:
      report.schema_version || null,
    status: report.status || null,
    ready: report.ready === true,
    gamePk: firstPresent(
      report.game_pk,
      null,
    ),
    readyCount,
    totalCount: items.length,
    blockedCount: items.length - readyCount,
    items,
    missingRequirements,
    activationPermitted:
      report.activation_permitted === true,
    activationStatus:
      report.activation_status || null,
    probabilityRecordsExposed:
      report.probability_records_exposed ??
      null,
    authoritativeSource:
      report.authoritative_source || 'legacy',
  }
}


function buildProductionExecution(
  sharedSimulation,
) {
  const diagnostics = objectValue(
    sharedSimulation.diagnostics
  )

  const execution = {
    ...objectValue(
      diagnostics
        .canonical_shadow_production_execution
    ),
    ...objectValue(
      sharedSimulation
        .canonical_shadow_production_execution
    ),
  }

  const status = execution.status || null
  const errorType = execution.error_type || null
  const errorMessage = execution.error_message || null

  return {
    available: Object.keys(execution).length > 0,
    schemaVersion:
      execution.schema_version || null,
    status,
    executed: execution.executed === true,
    canonicalAvailable:
      execution.canonical_available === true,
    simulationCount: finiteNumber(
      execution.simulation_count
    ),
    providerIdentity:
      execution.provider_identity || null,
    exactArtifactDigest:
      execution.exact_artifact_digest || null,
    fallbackCatalogDigest:
      execution.fallback_catalog_digest || null,
    inputAssemblyDigest:
      execution.input_assembly_digest || null,
    canonicalModelVersion:
      execution.canonical_model_version || null,
    errorType,
    errorMessage,
    activationPermitted:
      execution.activation_permitted === true,
    productionAuthorityChanged:
      execution.production_authority_changed === true,
    authoritativeSource:
      execution.authoritative_source || 'legacy',
  }
}


function buildRealism(sharedSimulation, shadow) {
  const diagnostics = objectValue(
    sharedSimulation.diagnostics
  )

  const source = {
    ...objectValue(
      sharedSimulation.game_state_realism
    ),
    ...objectValue(
      sharedSimulation.game_state_realism_diagnostics
    ),
    ...objectValue(
      diagnostics.game_state_realism
    ),
    ...objectValue(
      diagnostics.game_state_realism_diagnostics
    ),
    ...objectValue(
      shadow.game_state_realism
    ),
  }

  return {
    available: Object.keys(source).length > 0,
    features: REALISM_FEATURES.map(feature => {
      const rawValue = readAlias(
        source,
        feature.aliases,
      )

      const normalized =
        normalizeFeatureStatus(rawValue)

      return {
        key: feature.key,
        label: feature.label,
        status: normalized.status,
        detail: normalized.detail,
        rawValue: (
          rawValue === undefined
            ? null
            : rawValue
        ),
      }
    }),
  }
}

function buildCoverage(shadow) {
  const probabilityResolution = objectValue(
    shadow.probability_resolution
  )
  const summary = objectValue(
    probabilityResolution.summary
  )

  const totalResolutions = finiteNumber(
    summary.total_resolutions
  )
  const exactResolutions = finiteNumber(
    summary.exact_resolutions
  )
  const fallbackResolutions = finiteNumber(
    summary.fallback_resolutions
  )

  const fallbackRate = finiteNumber(
    summary.fallback_rate
  )

  const exactRate = (
    totalResolutions !== null &&
    totalResolutions > 0 &&
    exactResolutions !== null
  )
    ? exactResolutions / totalResolutions
    : (
      fallbackRate !== null
        ? 1 - fallbackRate
        : null
    )

  const tiers = arrayValue(
    probabilityResolution.tier_usage
  ).map(item => {
    const value = objectValue(item)

    return {
      tier: value.tier || 'unknown',
      label: humanize(value.tier) || 'Unknown',
      count: finiteNumber(value.count) || 0,
    }
  })

  return {
    available: (
      probabilityResolution &&
      Object.keys(probabilityResolution).length > 0 &&
      probabilityResolution.status !== 'error'
    ),
    status: probabilityResolution.status || null,
    schemaVersion:
      probabilityResolution.schema_version || null,
    diagnosticsVersion:
      probabilityResolution.diagnostics_version || null,
    totalResolutions,
    exactResolutions,
    fallbackResolutions,
    exactRate,
    fallbackRate,
    tiers,
  }
}

function buildIntegrity(shadow) {
  const coverage = objectValue(shadow.coverage)

  const gameValidationPassRate = finiteNumber(
    firstPresent(
      shadow.game_validation_pass_rate,
      coverage.game_validation_pass_rate,
    )
  )

  const reconciliationPassRate = finiteNumber(
    firstPresent(
      shadow.box_score_reconciliation_pass_rate,
      coverage.box_score_reconciliation_pass_rate,
      coverage.reconciliation_pass_rate,
    )
  )

  const replayValidationPassRate = finiteNumber(
    shadow.replay_validation_pass_rate
  )

  const pitcherAttributionCompleteRate =
    finiteNumber(
      shadow.pitcher_attribution_complete_rate
    )

  return {
    available: [
      gameValidationPassRate,
      reconciliationPassRate,
      replayValidationPassRate,
      pitcherAttributionCompleteRate,
    ].some(value => value !== null),
    metrics: [
      {
        key: 'game_validation',
        label: 'Game validation',
        value: gameValidationPassRate,
      },
      {
        key: 'box_score_reconciliation',
        label: 'Box-score reconciliation',
        value: reconciliationPassRate,
      },
      {
        key: 'replay_validation',
        label: 'Replay validation',
        value: replayValidationPassRate,
      },
      {
        key: 'pitcher_attribution',
        label: 'Pitcher attribution',
        value: pitcherAttributionCompleteRate,
      },
    ],
    earnedRunStatus:
      shadow.earned_run_status || null,
  }
}

function buildProvenance(shadow) {
  const provenance = objectValue(
    shadow.input_provenance
  )
  const provider = objectValue(
    provenance.probability_provider
  )
  const artifacts = objectValue(
    provenance.artifacts
  )
  const exact = objectValue(artifacts.exact)
  const fallbackCatalog = objectValue(
    artifacts.fallback_catalog
  )
  const matchup = objectValue(
    provenance.matchup
  )
  const fallbackPolicy = objectValue(
    provenance.fallback_policy
  )

  return {
    available: (
      Object.keys(provenance).length > 0 &&
      provenance.status !== 'error'
    ),
    status: provenance.status || null,
    schemaVersion:
      provenance.schema_version || null,
    assemblyVersion:
      provenance.assembly_version || null,
    assemblyDigest:
      provenance.assembly_digest || null,
    gamePk: firstPresent(
      matchup.game_pk,
      null,
    ),
    provider: {
      identity: provider.identity || null,
      name: provider.provider_name || null,
      version: provider.provider_version || null,
      artifactId: provider.artifact_id || null,
    },
    exactArtifact: {
      version: firstPresent(
        exact.artifact_version,
        exact.schema_version,
        null,
      ),
      digest: exact.digest || null,
      recordCount: finiteNumber(
        exact.record_count
      ),
    },
    fallbackCatalog: {
      version: firstPresent(
        fallbackCatalog.schema_version,
        fallbackCatalog.catalog_version,
        null,
      ),
      digest: fallbackCatalog.digest || null,
      recordCount: finiteNumber(
        fallbackCatalog.record_count
      ),
    },
    fallbackPolicy: {
      version:
        fallbackPolicy.policy_version || null,
      tiers: arrayValue(
        fallbackPolicy.tiers
      ).map(tier => ({
        key: String(tier),
        label: humanize(tier),
      })),
    },
    gameConfig: objectValue(
      provenance.game_config
    ),
    dfsRules: objectValue(
      provenance.dfs_rules
    ),
    authoritativeSource:
      provenance.authoritative_source || null,
    probabilityRecordsExposed:
      provenance.probability_records_exposed ??
      null,
  }
}


function buildProductionMonitoring(sharedSimulation) {
  const diagnostics = objectValue(
    sharedSimulation.diagnostics
  )
  const report = objectValue(
    diagnostics
      .canonical_baserunning_production_monitoring
  )
  const summary = objectValue(report.summary)
  const settlement = objectValue(
    report.settlement
  )
  const eligibility = objectValue(
    report.eligibility
  )
  const finalization = objectValue(
    report.calibration_finalization
  )
  const finalizationGate = objectValue(
    finalization.calibration_gate
  )

  return {
    available: Object.keys(report).length > 0,
    schemaVersion:
      report.schema_version || null,
    recorded: report.recorded === true,
    recordCreated:
      report.record_created === true,
    observationDigest:
      report.observation_digest || null,
    eligible: eligibility.eligible === true,
    eligibilityFailures: arrayValue(
      eligibility.failures
    ).map(String),
    targetGameCount: finiteNumber(
      summary.target_game_count
    ),
    readyGameCount: finiteNumber(
      summary.ready_game_count
    ),
    remainingGameCount: finiteNumber(
      summary.remaining_game_count
    ),
    storedObservationCount: finiteNumber(
      summary.stored_observation_count
    ),
    uniqueGameCount: finiteNumber(
      summary.unique_game_count
    ),
    progressRate: finiteNumber(
      summary.progress_rate
    ),
    monitoringComplete:
      summary.monitoring_complete === true,
    transformFrozen:
      summary.transform_frozen === true,
    transformDigests: arrayValue(
      summary.transform_digests
    ).map(String),
    settledGameCount: finiteNumber(
      settlement.settled_game_count
    ),
    settlementTargetGameCount: finiteNumber(
      settlement.target_game_count
    ),
    settlementRemainingGameCount: finiteNumber(
      settlement.remaining_game_count
    ),
    settlementProgressRate: finiteNumber(
      settlement.progress_rate
    ),
    settlementComplete:
      settlement.settlement_complete === true,
    projectedStolenBases: finiteNumber(
      settlement.projected_stolen_bases
    ),
    observedStolenBases: finiteNumber(
      settlement.observed_stolen_bases
    ),
    stolenBaseBias: finiteNumber(
      settlement.stolen_base_bias
    ),
    stolenBaseMae: finiteNumber(
      settlement.stolen_base_mae
    ),
    projectedCaughtStealing: finiteNumber(
      settlement.projected_caught_stealing
    ),
    observedCaughtStealing: finiteNumber(
      settlement.observed_caught_stealing
    ),
    caughtStealingBias: finiteNumber(
      settlement.caught_stealing_bias
    ),
    caughtStealingMae: finiteNumber(
      settlement.caught_stealing_mae
    ),
    attemptMae: finiteNumber(
      settlement.attempt_mae
    ),
    parameterReselectionPermitted:
      settlement.parameter_reselection_permitted === true,
    calibrationFinalizationAvailable:
      finalization.ready === true,
    calibrationDecision:
      finalization.decision || null,
    calibrationGatePassed:
      finalizationGate.calibration_gate_passed === true,
    incumbentRetained:
      finalization.incumbent_retained === true,
    incumbentTransformDigest:
      finalization.incumbent_transform_digest || null,
    candidateReselected:
      finalization.candidate_reselected === true,
    calibrationFinalizationDigest:
      finalization.finalization_digest || null,
  }
}

function buildWarnings(shadow) {
  const probabilityResolution = objectValue(
    shadow.probability_resolution
  )
  const provenance = objectValue(
    shadow.input_provenance
  )

  return uniqueStrings([
    arrayValue(shadow.warnings),
    shadow.error_message,
    (
      probabilityResolution.status === 'error'
        ? probabilityResolution.error_message
        : null
    ),
    (
      provenance.status === 'error'
        ? provenance.error_message
        : null
    ),
  ])
}

export function buildCanonicalDiagnosticsViewModel(
  sharedSimulation,
) {
  const shared = objectValue(sharedSimulation)
  const diagnostics = objectValue(
    shared.diagnostics
  )
  const shadow = objectValue(
    diagnostics.canonical_shadow
  )
  const metadata = {
    ...objectValue(shared.metadata),
    ...objectValue(shared.meta),
  }

  const hasCanonicalShadow =
    Object.keys(shadow).length > 0

  const bootstrapReadiness = (
    buildBootstrapReadiness(shared)
  )

  const productionExecution = (
    buildProductionExecution(shared)
  )
  const productionMonitoring = (
    buildProductionMonitoring(shared)
  )

  const canonicalAvailable = Boolean(
    shadow.canonical_available
  )

  const state = firstPresent(
    shadow.status,
    (
      productionExecution.available &&
      productionExecution.status !== 'not_run'
        ? productionExecution.status
        : null
    ),
    hasCanonicalShadow
      ? 'unknown'
      : 'not_run',
  )

  let availabilityReason = null

  if (!hasCanonicalShadow) {
    if (
      productionExecution.status === 'error'
    ) {
      const errorPrefix = (
        productionExecution.errorType
          ? `${productionExecution.errorType}: `
          : ''
      )

      availabilityReason = (
        'Canonical shadow execution failed open. ' +
        errorPrefix +
        (
          productionExecution.errorMessage ||
          'No error message was supplied.'
        )
      )
    } else if (
      productionExecution.status === 'executed'
    ) {
      availabilityReason = (
        'Canonical trials executed, but comparison ' +
        'diagnostics were not attached to this payload.'
      )
    } else if (
      bootstrapReadiness.available &&
      bootstrapReadiness.blockedCount > 0
    ) {
      availabilityReason = (
        'Canonical shadow execution is blocked by ' +
        `${bootstrapReadiness.blockedCount} missing ` +
        'production requirements.'
      )
    } else if (
      productionExecution.status === 'blocked'
    ) {
      availabilityReason = (
        'Canonical shadow execution remained blocked ' +
        'despite complete bootstrap readiness.'
      )
    } else {
      availabilityReason = (
        'Canonical shadow execution was not attached ' +
        'to this simulation payload.'
      )
    }
  }

  return {
    viewModelVersion:
      CANONICAL_DIAGNOSTICS_VIEW_MODEL_VERSION,

    hasCanonicalShadow,

    status: {
      state,
      label: humanize(state),
      enabled: Boolean(shadow.enabled),
      canonicalAvailable,
      authoritativeSource:
        shadow.authoritative_source || 'legacy',
      productionActive: (
        metadata.production_activation === true ||
        shadow.production_activation === true ||
        shadow.authoritative_source ===
          'canonical_event_driven_calibrated_baserunning'
      ),
      legacySimulationCount: finiteNumber(
        shadow.legacy_simulation_count
      ),
      canonicalSimulationCount: finiteNumber(
        shadow.canonical_simulation_count
      ),
      modelVersion: firstPresent(
        productionExecution
          .canonicalModelVersion,
        metadata.canonical_model_version,
        metadata.model_version,
        shared.model_version,
        null,
      ),
      schemaVersion:
        shadow.schema_version || null,
      errorType: shadow.error_type || null,
      errorMessage: shadow.error_message || null,
      availabilityReason,
    },

    bootstrapReadiness,
    productionExecution,
    productionMonitoring,
    realism: buildRealism(shared, shadow),
    coverage: buildCoverage(shadow),
    integrity: buildIntegrity(shadow),
    provenance: buildProvenance(shadow),
    warnings: uniqueStrings([
      buildWarnings(shadow),
      (
        productionExecution.status === 'error'
          ? productionExecution.errorMessage
          : null
      ),
    ]),

    raw: {
      canonicalShadow: shadow,
      bootstrapReadiness: objectValue(
        diagnostics
          .canonical_shadow_bootstrap_readiness
      ),
      productionExecution: objectValue(
        diagnostics
          .canonical_shadow_production_execution
      ),
    },
  }
}

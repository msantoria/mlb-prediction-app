import {
  buildCanonicalDiagnosticsViewModel,
} from './canonicalDiagnosticsViewModel.mjs'

function asObject(value) {
  return value && typeof value === 'object'
    ? value
    : {}
}

function asArray(value) {
  return Array.isArray(value)
    ? value
    : []
}

function number(value) {
  const parsed = Number(value)

  return Number.isFinite(parsed)
    ? parsed
    : null
}

function metricSummary(row, name) {
  const metrics = asObject(row?.metrics)
  const metric = asObject(metrics[name])

  return metric
}

function metricValue(row, name, key = 'mean') {
  return number(
    metricSummary(row, name)?.[key],
  )
}

function pitcherInningsValue(
  row,
  key = 'mean',
) {
  const outs = (
    metricValue(
      row,
      'outs_recorded',
      key,
    ) ??
    metricValue(
      row,
      'outs',
      key,
    )
  )

  return (
    outs === null
      ? null
      : outs / 3
  )
}

function sumValues(values) {
  const available = values.filter(
    value => value !== null,
  )

  if (!available.length) return null

  return available.reduce(
    (total, value) => total + value,
    0,
  )
}

function playerName(row) {
  return (
    row?.full_name ||
    row?.player_name ||
    row?.player_id ||
    'Unknown player'
  )
}

function teamSide(row) {
  const value = String(
    row?.team_side ||
    row?.side ||
    '',
  ).trim()

  return value || '—'
}

function pitcherRoleLabel(value) {
  const role = String(value || '').trim()

  const labels = {
    starter: 'Starter',
    opener: 'Opener',
    bulk_follower: 'Bulk Follower',
    reliever: 'Reliever',
    tandem_primary: 'Tandem Primary',
    tandem_secondary: 'Tandem Secondary',
    unexpected_pitcher: 'Unexpected',
  }

  return labels[role] || '—'
}

function dfsValue(row, key) {
  const direct = number(row?.[key])

  if (direct !== null) return direct

  const mapping = {
    projected_dfs_points: 'mean',
    dfs_floor: 'p10',
    dfs_median: 'median',
    dfs_ceiling: 'p90',
  }

  return metricValue(
    row,
    'dfs_points',
    mapping[key],
  )
}

function batterRow(row) {
  const singles = metricValue(row, 'singles')
  const doubles = metricValue(row, 'doubles')
  const triples = metricValue(row, 'triples')
  const homeRuns = metricValue(
    row,
    'home_runs',
  )

  return {
    playerId: row?.player_id ?? null,
    mlbPlayerId: row?.mlb_player_id ?? null,
    name: playerName(row),
    side: teamSide(row),
    plateAppearances: metricValue(
      row,
      'plate_appearances',
    ),
    hits: sumValues([
      singles,
      doubles,
      triples,
      homeRuns,
    ]),
    runs: metricValue(row, 'runs'),
    rbis: (
      metricValue(row, 'rbi') ??
      metricValue(row, 'rbis')
    ),
    singles,
    doubles,
    triples,
    homeRuns,
    walks: metricValue(row, 'walks'),
    stolenBases: metricValue(
      row,
      'stolen_bases',
    ),
    strikeouts: metricValue(
      row,
      'strikeouts',
    ),
    dfsMean: dfsValue(
      row,
      'projected_dfs_points',
    ),
    dfsFloor: dfsValue(row, 'dfs_floor'),
    dfsMedian: dfsValue(row, 'dfs_median'),
    dfsCeiling: dfsValue(
      row,
      'dfs_ceiling',
    ),
  }
}

function pitcherRow(row) {
  return {
    playerId: row?.player_id ?? null,
    mlbPlayerId: row?.mlb_player_id ?? null,
    name: playerName(row),
    side: teamSide(row),
    pitcherRole: row?.pitcher_role ?? null,
    pitcherRoleLabel: pitcherRoleLabel(
      row?.pitcher_role,
    ),
    battersFaced: metricValue(
      row,
      'batters_faced',
    ),
    inningsPitched: pitcherInningsValue(
      row,
    ),
    inningsPitchedP10: pitcherInningsValue(
      row,
      'p10',
    ),
    inningsPitchedMedian: pitcherInningsValue(
      row,
      'median',
    ),
    inningsPitchedP90: pitcherInningsValue(
      row,
      'p90',
    ),
    hitsAllowed: (
      metricValue(row, 'hits_allowed') ??
      metricValue(row, 'hits')
    ),
    walks: metricValue(row, 'walks'),
    hitByPitch: (
      metricValue(row, 'hit_by_pitch') ??
      metricValue(row, 'hit_batters')
    ),
    strikeouts: metricValue(
      row,
      'strikeouts',
    ),
    runs: (
      metricValue(row, 'runs_allowed') ??
      metricValue(row, 'runs')
    ),
    earnedRuns: (
      metricValue(row, 'earned_runs') ??
      metricValue(row, 'earned_runs_allowed')
    ),
    dfsMean: dfsValue(
      row,
      'projected_dfs_points',
    ),
    dfsFloor: dfsValue(row, 'dfs_floor'),
    dfsMedian: dfsValue(row, 'dfs_median'),
    dfsCeiling: dfsValue(
      row,
      'dfs_ceiling',
    ),
  }
}

function sortRows(rows) {
  return [...rows].sort((left, right) => {
    const sideComparison = String(
      left.side,
    ).localeCompare(String(right.side))

    if (sideComparison) return sideComparison

    return String(left.name).localeCompare(
      String(right.name),
    )
  })
}

function unavailableProjectionState(
  game,
  projections,
) {
  const diagnostics = (
    buildCanonicalDiagnosticsViewModel(game)
  )

  const projectionStatus = String(
    projections?.status || ''
  ).toLowerCase()
  const projectionSchema = (
    projections?.schema_version || null
  )
  const projectionPlayers = asArray(
    projections?.players,
  )

  if (projectionStatus === 'error') {
    return {
      state: 'attachment_error',
      title: 'Canonical projection attachment failed',
      message: (
        projections?.error_message ||
        'Canonical player projection rows could not be adapted from the completed simulation payload.'
      ),
      blockers: [],
      errorType: projections?.error_type || null,
      errorMessage: (
        projections?.error_message || null
      ),
      receivedSchema: projectionSchema,
    }
  }

  if (
    projectionSchema ===
      'canonical_player_projection_rows_v1' &&
    projectionPlayers.length === 0
  ) {
    return {
      state: 'empty_rows',
      title: 'Canonical projection rows were empty',
      message: (
        'The canonical projection attachment was present, but it contained no batter or pitcher rows.'
      ),
      blockers: [],
      errorType: null,
      errorMessage: null,
      receivedSchema: projectionSchema,
    }
  }

  if (
    projectionSchema &&
    projectionSchema !==
      'canonical_player_projection_rows_v1'
  ) {
    return {
      state: 'schema_mismatch',
      title: 'Canonical projection schema was not recognized',
      message: (
        `Expected canonical_player_projection_rows_v1 but received ${projectionSchema}.`
      ),
      blockers: [],
      errorType: null,
      errorMessage: null,
      receivedSchema: projectionSchema,
    }
  }

  const execution = (
    diagnostics.productionExecution || {}
  )
  const readiness = (
    diagnostics.bootstrapReadiness || {}
  )

  const status = String(
    execution.status ||
    diagnostics.status?.state ||
    'not_run'
  ).toLowerCase()

  if (status === 'error') {
    return {
      state: 'error',
      title: 'Canonical projection run failed',
      message: (
        diagnostics.status?.availabilityReason ||
        execution.errorMessage ||
        'The canonical simulation failed open before player projections could be attached.'
      ),
      blockers: [],
      errorType: execution.errorType || null,
      errorMessage: execution.errorMessage || null,
    }
  }

  if (
    readiness.available &&
    readiness.blockedCount > 0
  ) {
    return {
      state: 'blocked',
      title: 'Canonical projections blocked',
      message: (
        diagnostics.status?.availabilityReason ||
        'Required canonical simulation inputs are missing.'
      ),
      blockers: (
        readiness.items || []
      )
        .filter(item => !item.ready)
        .map(item => ({
          key: item.key,
          label: item.label,
          detail: item.detail || null,
        })),
      errorType: null,
      errorMessage: null,
    }
  }

  if (status === 'executed') {
    return {
      state: 'attachment_missing',
      title: 'Canonical projections were not attached',
      message: (
        diagnostics.status?.availabilityReason ||
        'Canonical trials executed, but same-run player projection rows were not attached to this response.'
      ),
      blockers: [],
      errorType: null,
      errorMessage: null,
    }
  }

  return {
    state: 'not_run',
    title: 'Canonical simulation was not available',
    message: (
      diagnostics.status?.availabilityReason ||
      'Canonical player projections require a completed canonical simulation run for this game.'
    ),
    blockers: [],
    errorType: null,
    errorMessage: null,
  }
}


export function buildCanonicalProjectionsViewModel(
  game,
) {
  const sharedSimulation = asObject(
    game?.sharedSimulation,
  )
  const sharedDiagnostics = asObject(
    sharedSimulation.diagnostics,
  )
  const topLevelDiagnostics = asObject(
    game?.diagnostics,
  )
  const shadow = asObject(
    topLevelDiagnostics.canonical_shadow ||
    sharedDiagnostics.canonical_shadow,
  )
  const projections = asObject(
    shadow.player_projections,
  )
  const players = asArray(projections.players)

  const available = (
    projections.schema_version ===
      'canonical_player_projection_rows_v1' &&
    players.length > 0
  )

  const unavailable = (
    available
      ? null
      : unavailableProjectionState(
          game,
          projections,
        )
  )

  return {
    available,
    unavailable,
    status: projections.status || (
      available ? 'available' : 'unavailable'
    ),
    schemaVersion: (
      projections.schema_version || null
    ),
    sourceProjectionSchemaVersion: (
      projections
        .source_projection_schema_version ||
      null
    ),
    runId: projections.run_id || null,
    modelVersion: (
      projections.model_version || null
    ),
    simulationCount: number(
      projections.simulation_count,
    ),
    authoritative: (
      projections.authoritative === true
    ),
    authoritativeSource: (
      projections.authoritative_source ||
      shadow.authoritative_source ||
      'legacy'
    ),
    identityEnrichmentApplied: (
      projections
        .identity_enrichment_applied === true
    ),
    batters: sortRows(
      players
        .filter(
          row => row?.player_type === 'batter',
        )
        .map(batterRow),
    ),
    pitchers: sortRows(
      players
        .filter(
          row => row?.player_type === 'pitcher',
        )
        .map(pitcherRow),
    ),
    errorMessage: (
      projections.error_message || null
    ),
    raw: projections,
  }
}

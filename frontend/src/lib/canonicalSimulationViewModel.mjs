function asObject(value) {
  return (
    value &&
    typeof value === 'object' &&
    !Array.isArray(value)
  ) ? value : {}
}

function finiteNumber(value) {
  const parsed = Number(value)
  return Number.isFinite(parsed) ? parsed : null
}

function expectedRuns(distribution) {
  const entries = Object.entries(asObject(distribution))

  if (!entries.length) return null

  let expectation = 0

  for (const [runs, probability] of entries) {
    const runValue = finiteNumber(runs)
    const probabilityValue = finiteNumber(probability)

    if (
      runValue === null ||
      probabilityValue === null
    ) {
      return null
    }

    expectation += runValue * probabilityValue
  }

  return expectation
}

function diagnostic(
  topLevelDiagnostics,
  sharedDiagnostics,
  key,
) {
  const topLevel = asObject(
    topLevelDiagnostics[key],
  )

  if (Object.keys(topLevel).length) {
    return topLevel
  }

  return asObject(sharedDiagnostics[key])
}

export function buildCanonicalSimulationViewModel(game) {
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
  const outcomes = asObject(
    shadow.canonical_outcomes,
  )
  const selection = diagnostic(
    topLevelDiagnostics,
    sharedDiagnostics,
    'canonical_production_lineup_selection',
  )
  const selected = asObject(selection.selection)
  const profiles = diagnostic(
    topLevelDiagnostics,
    sharedDiagnostics,
    'canonical_selected_lineup_profile_materialization',
  )
  const artifact = diagnostic(
    topLevelDiagnostics,
    sharedDiagnostics,
    'canonical_shadow_exact_artifact_discovery',
  )
  const execution = diagnostic(
    topLevelDiagnostics,
    sharedDiagnostics,
    'canonical_shadow_production_execution',
  )

  const lineupSource = (
    selection.selected_source ||
    selected.lineup_source ||
    null
  )
  const selectionReady = (
    selection.status === 'ready' ||
    selected.ready === true
  )
  const profilesReady = profiles.ready === true
  const artifactReady = (
    artifact.ready === true ||
    artifact.status === 'ready'
  )
  const executionCompleted = (
    execution.executed === true ||
    execution.status === 'executed'
  )
  const projectedEvidenceReady = (
    lineupSource !== 'projected' ||
    (profilesReady && artifactReady)
  )
  const outcomeSchemaReady = (
    outcomes.schema_version ===
    'canonical_game_outcomes_transport_v1'
  )
  const simulationCount = finiteNumber(
    outcomes.simulation_count,
  )
  const available = (
    selectionReady &&
    executionCompleted &&
    projectedEvidenceReady &&
    outcomeSchemaReady &&
    simulationCount !== null &&
    simulationCount > 0
  )
  const claimed = (
    selectionReady ||
    executionCompleted ||
    Object.keys(outcomes).length > 0
  )

  const awayExpectedRuns = expectedRuns(
    outcomes.away_run_distribution,
  )
  const homeExpectedRuns = expectedRuns(
    outcomes.home_run_distribution,
  )
  const totalExpectedRuns = expectedRuns(
    outcomes.total_run_distribution,
  )

  let status = 'unavailable'
  let title = 'Canonical simulation unavailable'
  let message = (
    'No canonical same-run outcome payload is attached.'
  )

  if (available && lineupSource === 'projected') {
    status = 'projected'
    title = (
      'Canonical simulation ran with projected lineups'
    )
    message = (
      'These values come from the canonical event-driven '
      + 'run using the selected projected batting orders.'
    )
  } else if (
    available &&
    lineupSource === 'confirmed'
  ) {
    status = 'confirmed'
    title = (
      'Canonical simulation ran with confirmed lineups'
    )
    message = (
      'These values come from the canonical event-driven '
      + 'run using the confirmed batting orders.'
    )
  } else if (claimed) {
    status = 'blocked'
    title = 'Canonical simulation results unavailable'

    if (!executionCompleted) {
      message = (
        'Canonical execution did not complete for this game.'
      )
    } else if (!projectedEvidenceReady) {
      message = (
        'Projected-lineup profile or exact-artifact '
        + 'evidence is incomplete.'
      )
    } else if (!outcomeSchemaReady) {
      message = (
        'Canonical execution completed, but its game '
        + 'outcomes were not attached to this payload.'
      )
    }
  }

  return {
    available,
    claimed,
    status,
    title,
    message,
    lineupSource,
    lineupSourceLabel: (
      lineupSource === 'projected'
        ? 'Projected lineups'
        : lineupSource === 'confirmed'
          ? 'Confirmed lineups'
          : 'Lineup source unavailable'
    ),
    runId: outcomes.run_id || null,
    modelVersion: (
      outcomes.model_version ||
      execution.canonical_model_version ||
      null
    ),
    simulationCount,
    awayExpectedRuns,
    homeExpectedRuns,
    totalExpectedRuns,
    awayWinProbability: finiteNumber(
      outcomes.away_win_probability,
    ),
    homeWinProbability: finiteNumber(
      outcomes.home_win_probability,
    ),
    tieProbability: finiteNumber(
      outcomes.tie_probability,
    ),
    extraInningsProbability: finiteNumber(
      outcomes.extra_innings_probability,
    ),
    walkOffProbability: finiteNumber(
      outcomes.walk_off_probability,
    ),
    totalProbabilities: asObject(
      outcomes.total_probabilities,
    ),
    teamTotalProbabilities: asObject(
      outcomes.team_total_probabilities,
    ),
    authoritative: outcomes.authoritative === true,
    authoritativeSource: (
      outcomes.authoritative_source ||
      'canonical_shadow'
    ),
  }
}

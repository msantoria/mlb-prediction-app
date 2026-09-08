import assert from 'node:assert/strict'
import test from 'node:test'

import {
  buildCanonicalSimulationViewModel,
} from './canonicalSimulationViewModel.mjs'

function canonicalGame(lineupSource = 'projected') {
  return {
    diagnostics: {
      canonical_shadow: {
        canonical_outcomes: {
          schema_version: (
            'canonical_game_outcomes_transport_v1'
          ),
          run_id: 'canonical-run-123',
          model_version: 'canonical-game-v1',
          simulation_count: 25,
          away_win_probability: 0.56,
          home_win_probability: 0.44,
          tie_probability: 0,
          extra_innings_probability: 0.12,
          walk_off_probability: 0.08,
          away_run_distribution: {
            3: 0.5,
            5: 0.5,
          },
          home_run_distribution: {
            2: 0.5,
            4: 0.5,
          },
          total_run_distribution: {
            5: 0.5,
            9: 0.5,
          },
          total_probabilities: {
            'over_6.5': 0.5,
            'under_6.5': 0.5,
          },
          team_total_probabilities: {
            away_3_plus: 1,
            home_3_plus: 0.5,
          },
          authoritative: false,
          authoritative_source: 'canonical_shadow',
        },
      },
      canonical_production_lineup_selection: {
        status: 'ready',
        selected_source: lineupSource,
        selection: {
          ready: true,
          lineup_source: lineupSource,
        },
      },
      canonical_selected_lineup_profile_materialization: {
        status: 'ready',
        ready: true,
      },
      canonical_shadow_exact_artifact_discovery: {
        status: 'ready',
        ready: true,
      },
      canonical_shadow_production_execution: {
        status: 'executed',
        executed: true,
        canonical_model_version: 'canonical-game-v1',
      },
    },
  }
}

test('builds projected-lineup canonical outcomes', () => {
  const view = buildCanonicalSimulationViewModel(
    canonicalGame(),
  )

  assert.equal(view.available, true)
  assert.equal(view.status, 'projected')
  assert.equal(view.simulationCount, 25)
  assert.equal(view.runId, 'canonical-run-123')
  assert.equal(view.totalExpectedRuns, 7)
  assert.equal(view.awayExpectedRuns, 4)
  assert.equal(view.homeExpectedRuns, 3)
  assert.equal(view.awayWinProbability, 0.56)
  assert.equal(
    view.lineupSourceLabel,
    'Projected lineups',
  )
  assert.match(view.title, /projected lineups/i)
})

test('builds confirmed-lineup canonical outcomes', () => {
  const view = buildCanonicalSimulationViewModel(
    canonicalGame('confirmed'),
  )

  assert.equal(view.available, true)
  assert.equal(view.status, 'confirmed')
  assert.match(view.title, /confirmed lineups/i)
})

test('does not relabel the legacy 3000-run payload', () => {
  const game = canonicalGame()
  game.sharedSimulation = {
    metadata: {
      simulation_count: 3000,
    },
    derived_outputs: {
      game_simulation: {
        simulation_count: 3000,
        away_win_probability: 0.99,
      },
    },
  }

  const view = buildCanonicalSimulationViewModel(game)

  assert.equal(view.simulationCount, 25)
  assert.equal(view.awayWinProbability, 0.56)
})

test('blocks projected display without profile evidence', () => {
  const game = canonicalGame()
  game.diagnostics
    .canonical_selected_lineup_profile_materialization
    .ready = false

  const view = buildCanonicalSimulationViewModel(game)

  assert.equal(view.available, false)
  assert.equal(view.claimed, true)
  assert.equal(view.status, 'blocked')
})

test('blocks completed execution without transported outcomes', () => {
  const game = canonicalGame()
  delete game.diagnostics.canonical_shadow
    .canonical_outcomes

  const view = buildCanonicalSimulationViewModel(game)

  assert.equal(view.available, false)
  assert.equal(view.claimed, true)
  assert.match(view.message, /not attached/i)
})

test('reads canonical data from shared diagnostics', () => {
  const source = canonicalGame()

  const view = buildCanonicalSimulationViewModel({
    sharedSimulation: {
      diagnostics: source.diagnostics,
    },
  })

  assert.equal(view.available, true)
  assert.equal(view.runId, 'canonical-run-123')
})

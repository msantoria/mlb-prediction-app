import assert from 'node:assert/strict'
import test from 'node:test'

import {
  buildCanonicalProjectionsViewModel,
} from './canonicalProjectionsViewModel.mjs'

function metric(mean, overrides = {}) {
  return {
    mean,
    median: mean,
    p10: mean - 1,
    p90: mean + 1,
    ...overrides,
  }
}

function payload() {
  return {
    diagnostics: {
      canonical_shadow: {
        authoritative_source: 'legacy',
        player_projections: {
          schema_version: (
            'canonical_player_projection_rows_v1'
          ),
          source_projection_schema_version: (
            'canonical_projection_payload_v1'
          ),
          run_id: 'run-123',
          model_version: 'canonical-v1',
          simulation_count: 25,
          identity_enrichment_applied: false,
          authoritative: false,
          authoritative_source: 'mixed',
          authority_scope: 'mixed',
          pitcher_projections_authoritative: true,
          batter_projections_authoritative: false,
          pitcher_projection_authority: {
            status: 'activated',
            authoritative_source: (
              'canonical_event_driven_'
              + 'pitcher_projection'
            ),
          },
          players: [
            {
              player_id: 'b-1',
              full_name: 'Test Batter',
              team_side: 'away',
              player_type: 'batter',
              projected_dfs_points: 10.5,
              dfs_floor: 3,
              dfs_median: 9,
              dfs_ceiling: 20,
              metrics: {
                plate_appearances: metric(4.4),
                singles: metric(0.7),
                doubles: metric(0.3),
                triples: metric(0.1),
                home_runs: metric(0.4),
                runs: metric(0.8),
                rbi: metric(1.1),
                walks: metric(0.5),
                stolen_bases: metric(0.2),
                strikeouts: metric(1.2),
              },
            },
            {
              player_id: 'p-1',
              player_type: 'pitcher',
              team_side: 'home',
              pitcher_role: 'starter',
              authoritative: true,
              authoritative_source: (
                'canonical_event_driven_'
                + 'pitcher_projection'
              ),
              metrics: {
                batters_faced: metric(24),
                outs_recorded: metric(
                  18,
                  {
                    p10: 12,
                    median: 18,
                    p90: 21,
                  },
                ),
                hits_allowed: metric(5),
                walks: metric(2),
                hit_by_pitch: metric(0.3),
                strikeouts: metric(7),
                runs_allowed: metric(2.5),
                earned_runs: metric(2),
                dfs_points: metric(
                  18,
                  {
                    p10: 8,
                    median: 17,
                    p90: 27,
                  },
                ),
              },
            },
          ],
        },
      },
    },
  }
}

test('builds same-run projection metadata', () => {
  const view = (
    buildCanonicalProjectionsViewModel(
      payload(),
    )
  )

  assert.equal(view.available, true)
  assert.equal(view.runId, 'run-123')
  assert.equal(view.modelVersion, 'canonical-v1')
  assert.equal(view.simulationCount, 25)
  assert.equal(view.authoritative, false)
  assert.equal(
    view.authoritativeSource,
    'mixed',
  )
  assert.equal(view.authorityScope, 'mixed')
  assert.equal(
    view.pitcherProjectionsAuthoritative,
    true,
  )
  assert.equal(
    view.batterProjectionsAuthoritative,
    false,
  )
  assert.equal(
    view.pitcherAuthoritativeSource,
    'canonical_event_driven_pitcher_projection',
  )
})

test('derives batter hits from component means', () => {
  const view = (
    buildCanonicalProjectionsViewModel(
      payload(),
    )
  )
  const batter = view.batters[0]

  assert.equal(batter.name, 'Test Batter')
  assert.equal(batter.plateAppearances, 4.4)
  assert.equal(batter.hits, 1.5)
  assert.equal(batter.rbis, 1.1)
  assert.equal(batter.stolenBases, 0.2)
  assert.equal(batter.dfsMean, 10.5)
  assert.equal(batter.dfsFloor, 3)
  assert.equal(batter.dfsMedian, 9)
  assert.equal(batter.dfsCeiling, 20)
})

test('derives pitcher innings from canonical outs recorded', () => {
  const view = (
    buildCanonicalProjectionsViewModel(
      payload(),
    )
  )
  const pitcher = view.pitchers[0]

  assert.equal(pitcher.name, 'p-1')
  assert.equal(pitcher.pitcherRole, 'starter')
  assert.equal(
    pitcher.pitcherRoleLabel,
    'Starter',
  )
  assert.equal(pitcher.inningsPitched, 6)
  assert.equal(pitcher.inningsPitchedP10, 4)
  assert.equal(
    pitcher.inningsPitchedMedian,
    6,
  )
  assert.equal(pitcher.inningsPitchedP90, 7)
  assert.equal(pitcher.battersFaced, 24)
  assert.equal(pitcher.authoritative, true)
  assert.equal(
    pitcher.authoritativeSource,
    'canonical_event_driven_pitcher_projection',
  )
  assert.equal(pitcher.dfsMean, 18)
  assert.equal(pitcher.dfsFloor, 8)
  assert.equal(pitcher.dfsMedian, 17)
  assert.equal(pitcher.dfsCeiling, 27)
})


test('does not infer missing pitcher role from workload', () => {
  const source = payload()
  const pitcher = (
    source
      .diagnostics
      .canonical_shadow
      .player_projections
      .players[1]
  )

  delete pitcher.pitcher_role

  pitcher.metrics.outs_recorded.mean = 24
  pitcher.metrics.batters_faced.mean = 35

  const view = (
    buildCanonicalProjectionsViewModel(source)
  )

  assert.equal(
    view.pitchers[0].pitcherRole,
    null,
  )
  assert.equal(
    view.pitchers[0].pitcherRoleLabel,
    '—',
  )
})


test('formats canonical bulk follower role', () => {
  const source = payload()
  source
    .diagnostics
    .canonical_shadow
    .player_projections
    .players[1]
    .pitcher_role = 'bulk_follower'

  const view = (
    buildCanonicalProjectionsViewModel(source)
  )

  assert.equal(
    view.pitchers[0].pitcherRole,
    'bulk_follower',
  )
  assert.equal(
    view.pitchers[0].pitcherRoleLabel,
    'Bulk Follower',
  )
})


test('preserves legacy RBI and outs metric aliases', () => {
  const source = payload()
  const players = (
    source
      .diagnostics
      .canonical_shadow
      .player_projections
      .players
  )
  const batterMetrics = players[0].metrics
  const pitcherMetrics = players[1].metrics

  batterMetrics.rbis = batterMetrics.rbi
  delete batterMetrics.rbi
  pitcherMetrics.outs = pitcherMetrics.outs_recorded
  delete pitcherMetrics.outs_recorded

  const view = buildCanonicalProjectionsViewModel(source)

  assert.equal(view.batters[0].rbis, 1.1)
  assert.equal(view.pitchers[0].inningsPitched, 6)
  assert.equal(
    view.pitchers[0].inningsPitchedP10,
    4,
  )
  assert.equal(
    view.pitchers[0].inningsPitchedMedian,
    6,
  )
  assert.equal(
    view.pitchers[0].inningsPitchedP90,
    7,
  )
})


test('returns unavailable view without rows', () => {
  const view = (
    buildCanonicalProjectionsViewModel({})
  )

  assert.equal(view.available, false)
  assert.deepEqual(view.batters, [])
  assert.deepEqual(view.pitchers, [])
})

test('leaves stolen bases unavailable when simulation omits metric', () => {
  const source = payload()
  delete (
    source
      .diagnostics
      .canonical_shadow
      .player_projections
      .players[0]
      .metrics
      .stolen_bases
  )

  const view = (
    buildCanonicalProjectionsViewModel(source)
  )

  assert.equal(
    view.batters[0].stolenBases,
    null,
  )
})

test('explains blocked canonical projections', () => {
  const view = (
    buildCanonicalProjectionsViewModel({
      diagnostics: {
        canonical_shadow_bootstrap_readiness: {
          status: 'blocked',
          ready: false,
          requirements: {
            game_identity: {
              ready: true,
            },
            away_lineup: {
              ready: false,
              player_count: 7,
              required_player_count: 9,
            },
            home_lineup: {
              ready: true,
              player_count: 9,
              required_player_count: 9,
            },
            away_starter: {
              ready: true,
            },
            home_starter: {
              ready: true,
            },
            away_bullpen: {
              ready: true,
              pitcher_count: 7,
            },
            home_bullpen: {
              ready: true,
              pitcher_count: 7,
            },
            probability_provider: {
              ready: true,
              source: 'canonical provider',
            },
            exact_probability_artifact: {
              ready: true,
              source: 'exact artifact',
            },
            fallback_probability_catalog: {
              ready: true,
              source: 'fallback catalog',
            },
          },
          missing_requirements: [
            'away_lineup',
          ],
        },
        canonical_shadow_production_execution: {
          status: 'blocked',
          executed: false,
        },
      },
    })
  )

  assert.equal(view.available, false)
  assert.equal(
    view.unavailable.state,
    'blocked',
  )
  assert.equal(
    view.unavailable.title,
    'Canonical projections blocked',
  )
  assert.equal(
    view.unavailable.blockers.length,
    1,
  )
  assert.equal(
    view.unavailable.blockers[0].label,
    'Away lineup',
  )
  assert.equal(
    view.unavailable.blockers[0].detail,
    '7 of 9 players',
  )
})

test('explains canonical execution errors', () => {
  const view = (
    buildCanonicalProjectionsViewModel({
      diagnostics: {
        canonical_shadow_production_execution: {
          status: 'error',
          executed: false,
          error_type: 'RuntimeError',
          error_message: 'provider failed',
        },
      },
    })
  )

  assert.equal(view.available, false)
  assert.equal(
    view.unavailable.state,
    'error',
  )
  assert.equal(
    view.unavailable.title,
    'Canonical projection run failed',
  )
  assert.equal(
    view.unavailable.errorType,
    'RuntimeError',
  )
  assert.match(
    view.unavailable.message,
    /provider failed/,
  )
})

test('explains missing projection attachment after execution', () => {
  const view = (
    buildCanonicalProjectionsViewModel({
      diagnostics: {
        canonical_shadow_production_execution: {
          status: 'executed',
          executed: true,
          canonical_available: true,
        },
      },
    })
  )

  assert.equal(view.available, false)
  assert.equal(
    view.unavailable.state,
    'attachment_missing',
  )
  assert.equal(
    view.unavailable.title,
    'Canonical projections were not attached',
  )
})


test('explains projection attachment adapter errors', () => {
  const view = (
    buildCanonicalProjectionsViewModel({
      diagnostics: {
        canonical_shadow: {
          player_projections: {
            schema_version: (
              'canonical_player_projection_rows_v1'
            ),
            status: 'error',
            error_type: 'ValueError',
            error_message: (
              'metric count must match simulation_count'
            ),
            players: [],
          },
        },
        canonical_shadow_production_execution: {
          status: 'executed',
          executed: true,
          canonical_available: true,
        },
      },
    })
  )

  assert.equal(view.available, false)
  assert.equal(
    view.unavailable.state,
    'attachment_error',
  )
  assert.equal(
    view.unavailable.errorType,
    'ValueError',
  )
  assert.match(
    view.unavailable.message,
    /metric count must match simulation_count/,
  )
})


test('explains empty canonical projection rows', () => {
  const view = (
    buildCanonicalProjectionsViewModel({
      diagnostics: {
        canonical_shadow: {
          player_projections: {
            schema_version: (
              'canonical_player_projection_rows_v1'
            ),
            status: 'available',
            players: [],
          },
        },
        canonical_shadow_production_execution: {
          status: 'executed',
          executed: true,
        },
      },
    })
  )

  assert.equal(view.available, false)
  assert.equal(
    view.unavailable.state,
    'empty_rows',
  )
  assert.equal(
    view.unavailable.title,
    'Canonical projection rows were empty',
  )
})


test('explains projection schema mismatches', () => {
  const view = (
    buildCanonicalProjectionsViewModel({
      diagnostics: {
        canonical_shadow: {
          player_projections: {
            schema_version: (
              'canonical_player_projection_rows_v2'
            ),
            players: [
              {
                player_id: 'b-1',
              },
            ],
          },
        },
      },
    })
  )

  assert.equal(view.available, false)
  assert.equal(
    view.unavailable.state,
    'schema_mismatch',
  )
  assert.equal(
    view.unavailable.receivedSchema,
    'canonical_player_projection_rows_v2',
  )
  assert.match(
    view.unavailable.message,
    /received canonical_player_projection_rows_v2/,
  )
})


test('reads canonical projections from sharedSimulation diagnostics', () => {
  const source = payload()
  const shadow = source.diagnostics.canonical_shadow

  const view = buildCanonicalProjectionsViewModel({
    sharedSimulation: {
      diagnostics: {
        canonical_shadow: shadow,
      },
    },
  })

  assert.equal(view.available, true)
  assert.equal(view.runId, 'run-123')
  assert.equal(view.batters.length, 1)
  assert.equal(view.pitchers.length, 1)
})


test('prefers top-level projection diagnostics when both paths exist', () => {
  const source = payload()
  const topLevelShadow = source.diagnostics.canonical_shadow

  const view = buildCanonicalProjectionsViewModel({
    diagnostics: {
      canonical_shadow: topLevelShadow,
    },
    sharedSimulation: {
      diagnostics: {
        canonical_shadow: {
          player_projections: {
            schema_version: (
              'canonical_player_projection_rows_v1'
            ),
            run_id: 'shared-run',
            simulation_count: 25,
            players: [],
          },
        },
      },
    },
  })

  assert.equal(view.available, true)
  assert.equal(view.runId, 'run-123')
})



test('recognizes activated production projections', () => {
  const source = payload()
  const shadow = (
    source.diagnostics.canonical_shadow
  )
  const projections = shadow.player_projections

  shadow.authoritative_source = (
    'canonical_event_driven_calibrated_baserunning'
  )
  projections.simulation_count = 250
  projections.authoritative = true
  projections.authoritative_source = (
    'canonical_event_driven_calibrated_baserunning'
  )

  const view = (
    buildCanonicalProjectionsViewModel(source)
  )

  assert.equal(view.authoritative, true)
  assert.equal(view.simulationCount, 250)
  assert.equal(
    view.authoritativeSource,
    'canonical_event_driven_calibrated_baserunning',
  )
})

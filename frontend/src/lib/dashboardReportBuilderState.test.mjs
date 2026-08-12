import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

import {
  buildReportRequest,
  canonicalBootstrapMessage,
  defaultReportSaveAsDraft,
  defaultFieldsForObject,
  initialFieldsByObject,
  normalizeCanonicalPage,
  reportExecutionFacts,
  reportFieldsForMode,
  savedReportExecutionMode,
  selectableRequestFields,
} from './dashboardReportBuilderState.mjs'

const query = { page_number: 1, page_size: 50, sort_by: 'score', sort_direction: 'desc' }

test('unfiltered hitters query the complete canonical active-player report', () => {
  const request = buildReportRequest({ objectKey: 'hitters', activeLineupsOnly: false, date: '2026-07-16', cleanedFilters: {}, query })
  assert.equal(request.path, '/my-dashboard/reports/query')
  assert.equal(request.payload.report_type, 'all_active_hitters')
  assert.deepEqual(request.payload.filters, {})
  assert.deepEqual(request.payload.weights, {})
  assert.equal(request.payload.sort_by, 'adjusted_score')
  assert.equal(request.payload.as_of_date, '2026-07-16')
  assert.equal('date' in request.payload, false)
})

test('weights rerank canonical players without becoming filter criteria', () => {
  const request = buildReportRequest({
    objectKey: 'pitchers',
    activeLineupsOnly: false,
    date: '2026-07-16',
    cleanedFilters: { team: 'CHC', weights: { 'K%': 1.6 } },
    query,
  })
  assert.deepEqual(request.payload.filters, { team: 'CHC' })
  assert.deepEqual(request.payload.weights, { 'K%': 1.6 })
})

test('report payload carries only fields registered for the selected object', () => {
  const availableFields = [
    { accessor: 'full_name', selectable: true },
    { accessor: 'average_velocity', selectable: true },
    { accessor: 'metrics', selectable: false },
  ]
  const selectedFields = selectableRequestFields(
    ['rank', 'full_name', 'average_velocity', 'exit_velocity', 'metrics'],
    availableFields,
  )
  assert.deepEqual(selectedFields, ['full_name', 'average_velocity'])
  const request = buildReportRequest({
    objectKey: 'pitchers',
    activeLineupsOnly: false,
    date: '2026-07-16',
    cleanedFilters: {},
    query,
    selectedFields,
  })
  assert.deepEqual(request.payload.selected_fields, ['full_name', 'average_velocity'])
})

test('confirmed and expanded objects use registered report populations', () => {
  const teams = buildReportRequest({ objectKey: 'teams', activeLineupsOnly: false, date: '2026-07-16', cleanedFilters: {}, query })
  assert.equal(teams.path, '/my-dashboard/reports/query')
  assert.equal(teams.payload.report_type, 'teams_daily_analysis')
  const hitters = buildReportRequest({ objectKey: 'hitters', activeLineupsOnly: true, date: '2026-07-16', cleanedFilters: {}, query })
  assert.equal(hitters.path, '/my-dashboard/reports/query')
  assert.equal(hitters.payload.report_type, 'all_active_hitters')
  assert.equal(hitters.payload.confirmed_lineups_only, true)
  const overall = buildReportRequest({ objectKey: 'overall_players', activeLineupsOnly: true, date: '2026-07-16', cleanedFilters: {}, query })
  assert.equal(overall.path, '/my-dashboard/reports/query')
  assert.equal(overall.payload.report_type, 'overall_players_daily_analysis')
  assert.equal(overall.payload.confirmed_lineups_only, true)
})

test('confirmed hitter reports preserve canonical fields', () => {
  assert.deepEqual(reportFieldsForMode({
    objectKey: 'hitters',
    activeLineupsOnly: true,
    selectedFields: ['rank', 'full_name', 'team_name', 'model_score', 'confidence'],
  }), ['rank', 'full_name', 'team_name', 'model_score', 'confidence'])
  assert.deepEqual(reportFieldsForMode({
    objectKey: 'hitters',
    activeLineupsOnly: false,
    selectedFields: ['rank', 'full_name'],
  }), ['rank', 'full_name'])
})

test('report execution facts expose population, lineup, projection, and freshness', () => {
  assert.deepEqual(reportExecutionFacts({
    population: { mode: 'confirmed_lineup' },
    lineup_filter: { lineup_status: 'partial', confirmed_batter_count: 72 },
    provenance: { snapshot_date: '2026-07-23', projection_versions: ['v23'] },
    population_bootstrap: { age_hours: 0.25 },
  }), {
    mode: 'Confirmed 1–9',
    lineupStatus: 'partial',
    confirmedCount: 72,
    snapshotDate: '2026-07-23',
    projectionVersion: 'v23',
    ageHours: 0.25,
  })
})

test('saved reports restore their original lineup execution mode', () => {
  assert.equal(savedReportExecutionMode({
    payload_json: { definition: { active_lineups_only: true } },
  }), true)
  assert.equal(savedReportExecutionMode({
    payload_json: { workbench_state: { activeLineupsOnly: false } },
  }, true), false)
})

test('primary objects own independent default column selections', () => {
  assert.deepEqual(defaultFieldsForObject('hitters'), ['rank', 'full_name', 'team_name', 'model_score', 'confidence'])
  assert.deepEqual(defaultFieldsForObject('teams'), ['rank', 'entity_name', 'team', 'opponent', 'score', 'confidence'])
  const fields = initialFieldsByObject([{ key: 'hitters' }, { key: 'pitchers' }], {
    activeObject: 'hitters',
    selectedFields: ['rank', 'full_name'],
  })
  assert.deepEqual(fields.hitters, ['rank', 'full_name', 'team_name', 'model_score', 'confidence'])
  assert.deepEqual(fields.pitchers, ['rank', 'full_name', 'team_name', 'model_score', 'confidence'])
  fields.hitters.push('xwoba')
  assert.equal(fields.pitchers.includes('xwoba'), false)
})

test('batter arsenal defaults show both canonical teams and save-as has an explicit destination', () => {
  assert.deepEqual(
    defaultFieldsForObject('batter_arsenal').slice(0, 3),
    ['batter_name', 'team_name', 'opposing_team_name'],
  )
  assert.deepEqual(defaultReportSaveAsDraft({
    label: 'Batter vs Arsenal',
    date: '2026-08-12',
    folderId: 42,
  }), {
    title: 'Batter vs Arsenal Report | 2026-08-12',
    folder_id: '42',
  })
  const workspaceSource = readFileSync(new URL('../pages/MyDashboardReportBuilderPage.jsx', import.meta.url), 'utf8')
  assert.match(workspaceSource, />Save As<\/button>/)
  assert.match(workspaceSource, />Folder selection<\/div>/)
  assert.match(workspaceSource, /folder_id: destination\.id/)
})

test('projection, tracker, and competitive objects use safe registered sort defaults', () => {
  const projection = buildReportRequest({ objectKey: 'model_projections', activeLineupsOnly: false, date: '2026-07-16', cleanedFilters: {}, query })
  const players = buildReportRequest({ objectKey: 'model_projection_players', activeLineupsOnly: false, date: '2026-07-16', cleanedFilters: {}, query })
  const tracker = buildReportRequest({ objectKey: 'model_tracker', activeLineupsOnly: false, date: '2026-07-16', cleanedFilters: {}, query })
  const arsenal = buildReportRequest({ objectKey: 'batter_arsenal', activeLineupsOnly: false, date: '2026-07-16', cleanedFilters: {}, query })
  assert.equal(projection.payload.report_type, 'model_projection_games')
  assert.equal(projection.payload.sort_by, 'home_win_probability')
  assert.equal(players.payload.sort_by, 'projected_dfs_points')
  assert.equal(tracker.payload.sort_by, 'score')
  assert.equal(arsenal.payload.sort_by, 'pitches_seen')
})

test('player trends sends the required user-selected configuration', () => {
  const trendConfig = {
    player_type: 'hitter',
    window_days: 15,
    comparison_baseline: 'previous_n_days',
    minimum_sample_size: 25,
    trend_direction: 'improving',
    selected_metrics: ['batting_avg', 'hard_hit_pct'],
  }
  const request = buildReportRequest({
    objectKey: 'player_trends',
    activeLineupsOnly: false,
    date: '2026-07-29',
    cleanedFilters: {},
    query,
    trendConfig,
  })
  assert.equal(request.payload.report_type, 'player_trends')
  assert.equal(request.payload.sort_by, 'absolute_change')
  assert.deepEqual(request.payload.trend_config, trendConfig)
})

test('canonical pagination is adapted to the Report Workspace contract', () => {
  const result = normalizeCanonicalPage({ totalSize: 125, records: Array(50).fill({}), page_info: { has_next_page: true } }, query)
  assert.equal(result.page_info.page_count, 3)
  assert.equal(result.page_info.record_count, 50)
  assert.equal(result.page_info.has_next, true)
  assert.equal(result.page_info.has_previous, false)
})


test('canonical bootstrap diagnostics expose only safe status details', () => {
  assert.deepEqual(
    canonicalBootstrapMessage({
      population_bootstrap: {
        status: 'failed',
        error_type: 'RuntimeError',
        run_id: 42,
      },
    }),
    {
      tone: 'error',
      title: 'Canonical population failed',
      detail: 'The guarded refresh failed with RuntimeError. Run #42.',
    },
  )
  assert.equal(
    canonicalBootstrapMessage({
      population_bootstrap: { status: 'in_progress', run_id: 43 },
    }).title,
    'Canonical population is refreshing',
  )
  assert.equal(
    canonicalBootstrapMessage({
      population_bootstrap: { status: 'empty', run_id: 44 },
    }).title,
    'Canonical population remained empty',
  )
})

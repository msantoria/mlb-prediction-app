import assert from 'node:assert/strict'
import test from 'node:test'

import {
  canOpenQueryStudio,
  QUERY_STUDIO_EXAMPLE,
  queryStudioColumns,
  queryStudioObjects,
  queryStudioRows,
  queryStudioSavePayload,
} from './dashboardQueryStudioState.mjs'

test('Query Studio visibility requires the server-returned advanced capability', () => {
  assert.equal(canOpenQueryStudio({ capabilities: ['workbench.advanced'] }), true)
  assert.equal(canOpenQueryStudio({ capabilities: ['workbench.execute'] }), false)
  assert.equal(canOpenQueryStudio({ role: 'admin' }), false)
})

test('Query Studio metadata tolerates missing and malformed object fields', () => {
  assert.deepEqual(queryStudioObjects(), [])
  assert.deepEqual(queryStudioObjects({ objects: null }), [])
  assert.deepEqual(queryStudioObjects({
    objects: [
      null,
      { label: 'Missing API name', fields: [] },
      { api_name: 'hitters', label: 'Hitters' },
      { api_name: 'pitchers', fields: [null, {}, { name: 'full_name', label: 'Name' }] },
    ],
  }), [
    { api_name: 'hitters', label: 'Hitters', fields: [] },
    { api_name: 'pitchers', fields: [{ name: 'full_name', label: 'Name' }] },
  ])
})

test('Query Studio result helpers preserve the server plan and row contract', () => {
  const result = {
    component: 'hitters',
    report_type: 'all_active_hitters',
    records: [{ full_name: 'Example Hitter', model_score: 0.72 }],
    workbench_plan: {
      language: 'mlbgpt_query_v1',
      logical_object: 'all_active_hitters',
      selected_fields: ['full_name', 'model_score'],
      filters: [{ field: 'model_score', operator: 'gte', value: 0.5 }],
      sort: { field: 'model_score', direction: 'desc' },
      pagination: { page_size: 50 },
    },
  }
  assert.deepEqual(queryStudioRows(result), result.records)
  assert.deepEqual(queryStudioColumns(result), ['full_name', 'model_score'])
  const payload = queryStudioSavePayload({ folderId: '12', statement: QUERY_STUDIO_EXAMPLE, result, title: 'High confidence hitters' })
  assert.equal(payload.folder_id, 12)
  assert.equal(payload.source_type, 'workbench_view')
  assert.equal(payload.payload_json.definition.query_studio_statement, QUERY_STUDIO_EXAMPLE)
  assert.deepEqual(payload.payload_json.snapshot.board_state, result)
  assert.equal(payload.sort_json.query_studio, true)
})

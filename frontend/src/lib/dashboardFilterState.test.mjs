import assert from 'node:assert/strict'
import test from 'node:test'

import {
  canonicalFilterCount,
  cleanCanonicalFilters,
  defaultOperator,
  filterInputType,
  filterableReportFields,
  newFilterCondition,
  normalizeSavedFilters,
  operatorNeedsValue,
} from './dashboardFilterState.mjs'

const fields = [
  { accessor: 'full_name', dataType: 'string', filterable: true, selectable: true, supportedOperators: ['eq', 'contains'] },
  { accessor: 'model_score', dataType: 'double', filterable: true, selectable: true, supportedOperators: ['eq', 'gte'] },
  { accessor: 'updated_at', dataType: 'datetime', filterable: true, selectable: true, supportedOperators: ['gte'] },
  { accessor: 'eligibility_status', dataType: 'string', filterable: true, selectable: false, supportedOperators: ['eq'] },
  { accessor: 'metrics', dataType: 'json', filterable: false, selectable: false, supportedOperators: [] },
]

test('uses every explicitly filterable server field even when it is not a report column', () => {
  assert.deepEqual(filterableReportFields(fields).map(field => field.accessor), [
    'full_name',
    'model_score',
    'updated_at',
    'eligibility_status',
  ])
  assert.deepEqual(newFilterCondition(fields), {
    field: 'full_name',
    operator: 'eq',
    value: '',
  })
  assert.equal(defaultOperator(fields[1]), 'eq')
})

test('cleans match-all and match-any condition trees without empty rows', () => {
  assert.deepEqual(cleanCanonicalFilters({
    logic: 'or',
    conditions: [
      { field: 'full_name', operator: 'contains', value: 'Smith' },
      { field: 'model_score', operator: 'gte', value: '' },
      { field: 'updated_at', operator: 'is_not_null', value: '' },
      { field: 'mlb_player_id', operator: 'in', value: '10, 20, ,30' },
      { field: 'team_id', operator: 'in', value: ', ,' },
    ],
  }), {
    logic: 'or',
    conditions: [
      { field: 'full_name', operator: 'contains', value: 'Smith' },
      { field: 'updated_at', operator: 'is_not_null' },
      { field: 'mlb_player_id', operator: 'in', value: ['10', '20', '30'] },
    ],
  })
  assert.equal(canonicalFilterCount({ conditions: [{ field: 'x', operator: 'eq', value: '' }] }), 0)
})

test('selects typed value controls and value-less operators', () => {
  assert.equal(filterInputType(fields[1], 'gte'), 'number')
  assert.equal(filterInputType(fields[2], 'gte'), 'datetime-local')
  assert.equal(filterInputType(fields[1], 'in'), 'text')
  assert.equal(operatorNeedsValue('eq'), true)
  assert.equal(operatorNeedsValue('is_null'), false)
})

test('restores the legacy hitter and pitcher filter shape into match-all rows', () => {
  assert.deepEqual(normalizeSavedFilters({
    team: 'CHC',
    min_score: 0.5,
    metrics: { xwOBA: { min: 0.3 }, 'K%': { max: 0.25 } },
    weights: { xwOBA: 1.4 },
  }), {
    logic: 'and',
    conditions: [
      { field: 'team_name', operator: 'eq', value: 'CHC' },
      { field: 'model_score', operator: 'gte', value: 0.5 },
      { field: 'xwoba', operator: 'gte', value: 0.3 },
      { field: 'strikeout_rate', operator: 'lte', value: 0.25 },
    ],
    weights: { xwoba: 1.4 },
  })
})

import test from 'node:test'
import assert from 'node:assert/strict'

import { buildReportCsv, csvEscape, formatEasternDateTime, mlbDateIso, safeFilenamePart } from './dashboardReportUtils.mjs'

test('mlbDateIso uses the MLB Eastern business date instead of UTC', () => {
  assert.equal(mlbDateIso(new Date('2026-07-14T02:30:00.000Z')), '2026-07-13')
  assert.equal(mlbDateIso(new Date('2026-07-14T05:00:00.000Z')), '2026-07-14')
})

test('formatEasternDateTime renders an explicit Eastern Time value', () => {
  const formatted = formatEasternDateTime('2026-07-14T02:30:00.000Z')
  assert.match(formatted, /Jul 13, 2026/)
  assert.match(formatted, /10:30 PM ET$/)
})

test('csvEscape protects commas, quotes, and line breaks', () => {
  assert.equal(csvEscape('Chicago Cubs'), 'Chicago Cubs')
  assert.equal(csvEscape('Cubs, Chicago'), '"Cubs, Chicago"')
  assert.equal(csvEscape('He said "go"'), '"He said ""go"""')
})

test('buildReportCsv exports visible columns in their current order', () => {
  const csv = buildReportCsv({
    columns: ['name', 'metrics.xwOBA'],
    rows: [{ name: 'Player, One', metrics: { xwOBA: 0.412 } }],
    fieldMap: { name: { label: 'Name' }, 'metrics.xwOBA': { label: 'xwOBA' } },
    getValue: (row, accessor) => accessor === 'metrics.xwOBA' ? row.metrics.xwOBA : row[accessor],
  })
  assert.equal(csv, 'Name,xwOBA\r\n"Player, One",0.412')
})

test('safeFilenamePart produces portable filenames', () => {
  assert.equal(safeFilenamePart('Overall Players Report'), 'overall-players-report')
})

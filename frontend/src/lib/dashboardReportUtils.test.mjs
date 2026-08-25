import test from 'node:test'
import assert from 'node:assert/strict'

import { buildReportCsv, collectPaginatedRows, csvEscape, formatEasternDateTime, mlbDateIso, safeFilenamePart } from './dashboardReportUtils.mjs'

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

test('collectPaginatedRows exports every records page in server order', async () => {
  const pagesRequested = []
  const rows = await collectPaginatedRows(async pageNumber => {
    pagesRequested.push(pageNumber)
    const records = pageNumber === 1
      ? [{ id: 1 }, { id: 2 }]
      : pageNumber === 2
        ? [{ id: 3 }, { id: 4 }]
        : [{ id: 5 }]
    return {
      records,
      totalSize: 5,
      page_info: { has_next_page: pageNumber < 3 },
    }
  })

  assert.deepEqual(pagesRequested, [1, 2, 3])
  assert.deepEqual(rows.map(row => row.id), [1, 2, 3, 4, 5])
})

test('collectPaginatedRows supports legacy item pages and fails on an incomplete empty page', async () => {
  const legacyRows = await collectPaginatedRows(async pageNumber => ({
    items: pageNumber === 1 ? [{ id: 'a' }] : [{ id: 'b' }],
    totalSize: 2,
    page_info: { has_next: pageNumber === 1 },
  }))
  assert.deepEqual(legacyRows.map(row => row.id), ['a', 'b'])

  await assert.rejects(
    collectPaginatedRows(async pageNumber => ({
      records: pageNumber === 1 ? [{ id: 1 }] : [],
      totalSize: 2,
      page_info: { has_next_page: true },
    })),
    /before every matching row/,
  )
})

test('safeFilenamePart produces portable filenames', () => {
  assert.equal(safeFilenamePart('Overall Players Report'), 'overall-players-report')
})

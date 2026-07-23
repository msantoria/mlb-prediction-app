import test from 'node:test'
import assert from 'node:assert/strict'

import { organizeReportFolders, reportFolderSummary } from './dashboardReportFolders.mjs'

const folders = [
  { id: 1, folder_name: '2026-07-20', folder_date: '2026-07-20', item_count: 2, items: [{ id: 11 }, { id: 12 }] },
  { id: 2, folder_name: '2026-07-19', folder_date: '2026-07-19', item_count: 1, items: [{ id: 13 }] },
  { id: 3, folder_name: 'Scouting', folder_date: null, item_count: 1, items: [{ id: 14 }] },
  { id: 4, folder_name: 'Default Dashboard', folder_date: null, is_default: true, item_count: 0, items: [] },
]

test('organizes physical folders into daily, weekly, monthly, and custom shelves', () => {
  const organized = organizeReportFolders(folders)

  assert.deepEqual(organized.daily.map(entry => entry.folder_date), ['2026-07-20', '2026-07-19'])
  assert.equal(organized.weekly[0].label, 'Week of 2026-07-20')
  assert.equal(organized.weekly[1].label, 'Week of 2026-07-13')
  assert.equal(organized.monthly[0].key, '2026-07')
  assert.equal(organized.monthly[0].item_count, 3)
  assert.deepEqual(organized.custom.map(entry => entry.label), ['Scouting', 'Default Dashboard'])
})

test('summarizes physical folders without double-counting virtual rollups', () => {
  assert.deepEqual(reportFolderSummary(folders), { folderCount: 4, itemCount: 4 })
})

test('uses a renamed physical folder label without changing computed rollup labels', () => {
  const renamed = folders.map(folder => folder.id === 1 ? { ...folder, folder_name: 'Opening Day Reports' } : folder)
  const organized = organizeReportFolders(renamed)

  assert.equal(organized.daily[0].label, 'Opening Day Reports')
  assert.equal(organized.weekly[0].label, 'Week of 2026-07-20')
  assert.equal(organized.monthly[0].label, '2026-07')
  assert.deepEqual(organized.weekly[0].folderIds, [1])
})

test('malformed legacy folder dates cannot crash authenticated workspace rollups', () => {
  const organized = organizeReportFolders([
    ...folders,
    { id: 5, folder_name: 'Legacy Import', folder_date: '2026-99-45', item_count: 0, items: [] },
  ])

  assert.equal(organized.daily.some(entry => entry.id === 5), false)
  assert.equal(organized.weekly.every(entry => entry.key), true)
  assert.equal(organized.monthly.every(entry => entry.key), true)
  assert.equal(organized.custom.some(entry => entry.id === 5), true)
})

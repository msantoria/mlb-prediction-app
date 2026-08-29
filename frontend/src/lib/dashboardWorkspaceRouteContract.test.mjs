import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

const appSource = readFileSync(new URL('../App.jsx', import.meta.url), 'utf8')
const routeSource = readFileSync(new URL('../pages/MyDashboardReportBuilderRoute.jsx', import.meta.url), 'utf8')
const workspaceSource = readFileSync(new URL('../pages/MyDashboardReportBuilderPage.jsx', import.meta.url), 'utf8')
const studioSource = readFileSync(new URL('../components/QueryStudioPanel.jsx', import.meta.url), 'utf8')
const adminSource = readFileSync(new URL('../pages/AdminControlCenterPage.jsx', import.meta.url), 'utf8')

test('/my-dashboard resolves to the current Report Builder workspace', () => {
  assert.match(appSource, /path="\/my-dashboard" element={<MyDashboardReportBuilderRoute\s*\/>}/)
  assert.match(routeSource, /<MyDashboardReportBuilderPage\s*\/>/)
  assert.doesNotMatch(appSource, /MyDashboardWorkbenchPage/)
})

test('the routed page owns both the signed-out landing and authenticated workspace', () => {
  assert.match(workspaceSource, /if \(!profile\) return/)
  assert.match(workspaceSource, /Sign in to MyDashboard/)
  assert.match(workspaceSource, /Private report workspace/)
  assert.match(workspaceSource, /Build your report\./)
})

test('the authenticated saved-report shelf receives the declared selection setter', () => {
  assert.match(workspaceSource, /setSelectedEntryKey={setSelectedShelfEntryKey}/)
  assert.doesNotMatch(workspaceSource, /setSelectedEntryKey={setSelectedEntryKey}/)
})

test('registered report objects use the server catalog and persist match-all or match-any logic', () => {
  assert.match(workspaceSource, /FILTER_LOGIC_OPTIONS/)
  assert.match(workspaceSource, /filterableReportFields\(fields\)/)
  assert.match(workspaceSource, /normalizeSavedFilters\(definition\.filters/)
  assert.match(workspaceSource, /schema_version: 4/)
  assert.match(adminSource, />Report</)
  assert.match(adminSource, /object\.filtering\?\.logic/)
  assert.match(workspaceSource, /key: 'model_projections'/)
  assert.match(workspaceSource, /key: 'model_projection_players'/)
  assert.match(workspaceSource, /key: 'model_tracker'/)
  assert.match(workspaceSource, /key: 'batter_arsenal'/)
  assert.match(workspaceSource, /WEIGHTED_OBJECTS\.has\(objectKey\)/)
})

test('Query Studio visibility is capability-derived and the server remains the execution boundary', () => {
  assert.match(workspaceSource, /hasDashboardCapability\(profile, 'workbench\.advanced'\) \? <QueryStudioPanel/)
  assert.doesNotMatch(workspaceSource, /profile\.(email|plan_type)\s*===/)
  assert.match(studioSource, /dashboardApi\('\/my-dashboard\/query-studio\/metadata'/)
  assert.match(studioSource, /dashboardApi\(path/)
  assert.match(studioSource, /Normalized request and bindings/)
  assert.match(studioSource, /event\.(metaKey|ctrlKey)/)
})

test('all-row CSV downloads use one authenticated streaming request', () => {
  assert.match(workspaceSource, /dashboardDownload\('\/my-dashboard\/reports\/export\.csv'/)
  assert.match(studioSource, /dashboardDownload\('\/my-dashboard\/query-studio\/export\.csv'/)
  assert.doesNotMatch(workspaceSource, /collectPaginatedRows/)
  assert.doesNotMatch(studioSource, /collectPaginatedRows/)
})

test('saved reports expose an authenticated report subscription toggle', () => {
  assert.match(workspaceSource, /Save report to subscribe/)
  assert.match(workspaceSource, /Subscribe to report/)
  assert.match(workspaceSource, /Subscribed ✓/)
  assert.match(workspaceSource, /\/my-dashboard\/items\/\$\{savedReportId\}\/subscription/)
  assert.match(workspaceSource, /JSON\.stringify\(\{ enabled: !subscription\?\.enabled \}\)/)
  assert.match(workspaceSource, /setReportSavedItemId\(item\.id\)/)
})

test('the workspace preserves the approved type system and responsive breakpoints', () => {
  assert.match(workspaceSource, /Franklin Gothic/)
  assert.match(workspaceSource, /Century Gothic/)
  assert.match(workspaceSource, /const isMobile = width < 760/)
  assert.match(workspaceSource, /const isNarrow = width < 1050/)
  assert.match(studioSource, /overflowX: 'auto'/)
  assert.match(studioSource, /overflow: 'auto'/)
})

test('the landing and workspace expose a persisted light, dark, and system theme control', () => {
  assert.match(workspaceSource, /DASHBOARD_THEME_KEY/)
  assert.match(workspaceSource, /prefers-color-scheme: dark/)
  assert.match(workspaceSource, /Dashboard color theme/)
  assert.match(workspaceSource, /data-dashboard-theme/)
})

test('new MyDashboard surfaces contain no prohibited legacy product name', () => {
  const prohibited = ['sales', 'force'].join('')
  assert.equal(workspaceSource.toLowerCase().includes(prohibited), false)
  assert.equal(studioSource.toLowerCase().includes(prohibited), false)
})

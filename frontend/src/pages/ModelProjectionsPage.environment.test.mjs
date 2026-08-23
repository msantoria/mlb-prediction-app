import assert from 'node:assert/strict'
import fs from 'node:fs'
import test from 'node:test'

const source = fs.readFileSync(
  new URL(
    './ModelProjectionsPage.jsx',
    import.meta.url,
  ),
  'utf8',
)

test('environment tab renders component adjustments', () => {
  assert.match(source, /Park Adjustment/)
  assert.match(source, /Weather Adjustment/)
  assert.match(
    source,
    /Full Environmental Adjustment/,
  )
  assert.match(source, /Final Multiplier/)
  assert.match(source, /adjustments\.run_scoring/)
  assert.match(source, /adjustments\.hits/)
  assert.match(source, /adjustments\.home_runs/)
})

test('environment tab exposes roof-aware application', () => {
  assert.match(source, /Weather Application/)
  assert.match(source, /Roof Type/)
  assert.match(source, /Roof State/)
  assert.match(source, /Observed Weather/)
  assert.match(source, /Applied Temperature/)
  assert.match(source, /Applied Wind Speed/)
  assert.match(source, /Park Factor Policy/)
})

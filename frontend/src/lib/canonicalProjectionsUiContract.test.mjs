import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'

const pageUrl = new URL(
  '../pages/ModelProjectionsPage.jsx',
  import.meta.url,
)

async function pageSource() {
  return readFile(pageUrl, 'utf8')
}

test('projections tab follows simulation and precedes diagnostics', async () => {
  const source = await pageSource()

  assert.match(
    source,
    /\['simulation', 'Simulation'\],\s*\['projections', 'Projections'\],\s*\['diagnostics', 'Diagnostics'\]/,
  )
})

test('projections tab consumes canonical projections view model', async () => {
  const source = await pageSource()

  assert.match(
    source,
    /buildCanonicalProjectionsViewModel/,
  )
  assert.match(
    source,
    /Canonical Player Projections/,
  )
  assert.match(
    source,
    /<ProjectionsTab game=\{game\}/,
  )
})

test('projections tab describes same-run coherence', async () => {
  const source = await pageSource()

  assert.match(
    source,
    /exact same trial\s*batch/i,
  )
  assert.match(
    source,
    /view\.authoritative/,
  )
  assert.match(
    source,
    /Authoritative production/,
  )
  assert.match(
    source,
    /Pitchers authoritative/,
  )
  assert.match(
    source,
    /Non-authoritative shadow/,
  )
  assert.match(
    source,
    /view\.pitcherProjectionsAuthoritative/,
  )
})

test('projections tab describes mixed row authority', async () => {
  const source = await pageSource()

  assert.match(source, /Authority Scope/)
  assert.match(source, /Pitcher Authority/)
  assert.match(source, /Batter Authority/)
  assert.match(
    source,
    /view\.pitcherAuthoritativeSource/,
  )
})

test('projections tab renders requested batter metrics', async () => {
  const source = await pageSource()

  for (const label of [
    'PA',
    'RBI',
    '1B',
    '2B',
    '3B',
    'HR',
    'BB',
    'SB',
    'DK Mean',
    'DK Floor',
    'DK Median',
    'DK Ceiling',
  ]) {
    assert.match(source, new RegExp(label))
  }
})

test('projections tab separates pitcher role taxonomy', async () => {
  const source = await pageSource()

  assert.match(
    source,
    /key: 'plannedPitcherRoleLabel', label: 'Planned Role'/,
  )
  assert.match(
    source,
    /key: 'typicalBullpenRoleLabel', label: 'Typical Role'/,
  )
  assert.match(
    source,
    /key: 'gameAvailabilityStatusLabel', label: 'Availability'/,
  )
  assert.match(
    source,
    /key: 'appearanceProbabilityPercent', label: 'App %'/,
  )
  assert.match(source, /view\.pitcherSections\.map/)
})

test('projections tab renders pitcher workload distribution', async () => {
  const source = await pageSource()

  for (const label of [
    'BF',
    'IP',
    'IP P10',
    'IP Median',
    'IP P90',
  ]) {
    assert.match(source, new RegExp(label))
  }
})

test('projections tab explains unavailable canonical states', async () => {
  const source = await pageSource()

  assert.match(
    source,
    /view\.unavailable\.title/,
  )
  assert.match(
    source,
    /view\.unavailable\.message/,
  )
  assert.match(
    source,
    /view\.unavailable\.blockers/,
  )
  assert.match(
    source,
    /same\s+canonical simulation run/i,
  )
})

test('projections tab explains pitcher workload scope', async () => {
  const source = await pageSource()

  assert.match(
    source,
    /unconditional\s+game-level outcomes/i,
  )
  assert.match(
    source,
    /include nonappearances/i,
  )
  assert.match(
    source,
    /Appearance probability is shown separately/i,
  )
  assert.match(
    source,
    /no role is inferred from workload/i,
  )
})


test('projections tab displays canonical lineup execution context', async () => {
  const source = await pageSource()

  assert.match(
    source,
    /view\.simulationContext\.title/,
  )
  assert.match(
    source,
    /view\.simulationContext\.lineupSourceLabel/,
  )
  assert.match(source, /Lineup Selection/)
  assert.match(source, /Player Profiles/)
  assert.match(source, /Exact Artifact/)
  assert.match(source, /Canonical Execution/)
  assert.match(
    source,
    /view\.simulationContext\.fullyVerified/,
  )
})

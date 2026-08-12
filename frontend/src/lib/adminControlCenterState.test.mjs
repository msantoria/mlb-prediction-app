import assert from 'node:assert/strict'
import test from 'node:test'

import {
  editableUserPayload,
  featureFlagUpdatePayload,
  settingUpdatePayload,
  userEditorValues,
} from './adminControlCenterState.mjs'

test('user editor payload excludes authorization and credential fields', () => {
  assert.deepEqual(editableUserPayload({
    username: 'analyst',
    display_name: 'Analyst',
    role: 'admin',
    capabilities: ['admin.portal.access'],
    password_hash: 'nope',
    plan: 'owner',
  }), {
    username: 'analyst',
    display_name: 'Analyst',
  })
})

test('user editor values flatten only safe directory fields', () => {
  const values = userEditorValues({
    username: 'owner',
    role: 'admin',
    directory: { display_name: 'Owner', is_active: true, is_locked: false },
  })
  assert.equal(values.username, 'owner')
  assert.equal(values.display_name, 'Owner')
  assert.equal(values.timezone, 'America/New_York')
  assert.equal(values.is_active, true)
  assert.equal('role' in values, false)
})

test('setting and feature flag payloads use the validated API contracts', () => {
  assert.deepEqual(
    settingUpdatePayload({ namespace: 'identity', key: 'default_timezone' }, 'America/Chicago'),
    { updates: [{ namespace: 'identity', key: 'default_timezone', value: 'America/Chicago' }] },
  )
  assert.deepEqual(
    featureFlagUpdatePayload({ key: 'federation_enabled', target_profiles: [] }, true),
    { updates: [{ key: 'federation_enabled', enabled: true, target_profiles: [] }] },
  )
})

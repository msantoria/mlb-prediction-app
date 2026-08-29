import assert from 'node:assert/strict'
import test from 'node:test'

import {
  DASHBOARD_SESSION_STORAGE_KEY,
  DashboardApiError,
  adminAccessState,
  dashboardApi,
  dashboardDownload,
  dashboardApiUrl,
  hasDashboardCapability,
  readDashboardSessionToken,
  writeDashboardSessionToken,
} from './dashboardSession.mjs'

function memoryStorage(initial = {}) {
  const values = new Map(Object.entries(initial))
  return {
    getItem(key) { return values.get(key) || null },
    setItem(key, value) { values.set(key, String(value)) },
    removeItem(key) { values.delete(key) },
  }
}

test('dashboard session token helpers store and remove the compatibility token', () => {
  const storage = memoryStorage()
  writeDashboardSessionToken('session-one', storage)
  assert.equal(readDashboardSessionToken(storage), 'session-one')
  writeDashboardSessionToken('', storage)
  assert.equal(readDashboardSessionToken(storage), '')
})

test('dashboard API URL accepts relative and absolute paths', () => {
  assert.equal(
    dashboardApiUrl('/admin/overview', 'https://api.example.test/'),
    'https://api.example.test/admin/overview',
  )
  assert.equal(
    dashboardApiUrl('https://other.example.test/path', 'https://api.example.test'),
    'https://other.example.test/path',
  )
})

test('dashboard API sends the active server session and stores rotated tokens', async () => {
  const storage = memoryStorage({ [DASHBOARD_SESSION_STORAGE_KEY]: 'session-one' })
  let request = null
  const fetchImpl = async (url, options) => {
    request = { url, options }
    return {
      ok: true,
      status: 200,
      async json() { return { ok: true, session_token: 'session-two' } },
    }
  }

  await dashboardApi('/my-dashboard/workspace', {}, {
    fetchImpl,
    storage,
    apiBase: 'https://api.example.test',
  })

  assert.equal(request.url, 'https://api.example.test/my-dashboard/workspace')
  assert.equal(request.options.credentials, 'include')
  assert.equal(request.options.cache, 'no-store')
  assert.equal(request.options.headers['X-Dashboard-Session'], 'session-one')
  assert.equal(readDashboardSessionToken(storage), 'session-two')
})

test('dashboard API clears rejected tokens and preserves server error state', async () => {
  const storage = memoryStorage({ [DASHBOARD_SESSION_STORAGE_KEY]: 'rejected-token' })
  const fetchImpl = async () => ({
    ok: false,
    status: 401,
    async json() { return { detail: 'Dashboard sign-in required' } },
  })

  await assert.rejects(
    dashboardApi('/admin/overview', {}, {
      fetchImpl,
      storage,
      apiBase: 'https://api.example.test',
    }),
    error => error instanceof DashboardApiError
      && error.status === 401
      && error.message === 'Dashboard sign-in required',
  )
  assert.equal(readDashboardSessionToken(storage), '')
})

test('dashboard profile clears a stale compatibility token when no session resolves', async () => {
  const storage = memoryStorage({ [DASHBOARD_SESSION_STORAGE_KEY]: 'stale-token' })
  const fetchImpl = async () => ({
    ok: true,
    status: 200,
    async json() { return { authenticated: false } },
  })

  await dashboardApi('/my-dashboard/profile', {}, {
    fetchImpl,
    storage,
    apiBase: 'https://api.example.test',
  })
  assert.equal(readDashboardSessionToken(storage), '')
})

test('dashboard download returns the streaming response with the active session', async () => {
  const storage = memoryStorage({ [DASHBOARD_SESSION_STORAGE_KEY]: 'download-token' })
  let request = null
  const response = {
    ok: true,
    status: 200,
    headers: new Map([['content-type', 'text/csv; charset=utf-8']]),
    async blob() { return new Blob(['Name\r\nPlayer One\r\n'], { type: 'text/csv' }) },
  }
  const fetchImpl = async (url, options) => {
    request = { url, options }
    return response
  }

  const result = await dashboardDownload('/my-dashboard/reports/export.csv', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: '{"report_type":"all_active_hitters"}',
  }, {
    fetchImpl,
    storage,
    apiBase: 'https://api.example.test',
  })

  assert.equal(result, response)
  assert.equal(request.url, 'https://api.example.test/my-dashboard/reports/export.csv')
  assert.equal(request.options.credentials, 'include')
  assert.equal(request.options.cache, 'no-store')
  assert.equal(request.options.headers['X-Dashboard-Session'], 'download-token')
})

test('dashboard download clears rejected sessions and reports JSON errors', async () => {
  const storage = memoryStorage({ [DASHBOARD_SESSION_STORAGE_KEY]: 'rejected-download-token' })
  const fetchImpl = async () => ({
    ok: false,
    status: 401,
    async json() { return { detail: 'Dashboard sign-in required' } },
  })

  await assert.rejects(
    dashboardDownload('/my-dashboard/reports/export.csv', { method: 'POST' }, {
      fetchImpl,
      storage,
      apiBase: 'https://api.example.test',
    }),
    error => error instanceof DashboardApiError
      && error.status === 401
      && error.message === 'Dashboard sign-in required',
  )
  assert.equal(readDashboardSessionToken(storage), '')
})

test('capability and direct-route state helpers are deterministic', () => {
  const profile = { capabilities: ['dashboard.reports.run', 'admin.portal.access'] }
  assert.equal(hasDashboardCapability(profile, 'admin.portal.access'), true)
  assert.equal(hasDashboardCapability(profile, 'admin.users.read'), false)
  assert.equal(hasDashboardCapability({ capabilities: 'admin.portal.access' }, 'admin.portal.access'), false)

  assert.equal(adminAccessState({ loading: true }), 'loading')
  assert.equal(adminAccessState({ authenticated: false }), 'sign_in_required')
  assert.equal(adminAccessState({ authenticated: true, status: 401 }), 'sign_in_required')
  assert.equal(adminAccessState({ authenticated: true, status: 403 }), 'access_denied')
  assert.equal(adminAccessState({ authenticated: true, status: 500 }), 'error')
  assert.equal(adminAccessState({ authenticated: true, status: 200 }), 'ready')
})

import { API_BASE } from './api.js'

export const DASHBOARD_SESSION_STORAGE_KEY = 'mlbgpt_dashboard_session_token'

function browserStorage() {
  if (typeof window === 'undefined') return null
  try { return window.localStorage || null } catch { return null }
}

export function readDashboardSessionToken(storage = browserStorage()) {
  if (!storage) return ''
  try { return storage.getItem(DASHBOARD_SESSION_STORAGE_KEY) || '' } catch { return '' }
}

export function writeDashboardSessionToken(value, storage = browserStorage()) {
  if (!storage) return
  try {
    if (value) storage.setItem(DASHBOARD_SESSION_STORAGE_KEY, value)
    else storage.removeItem(DASHBOARD_SESSION_STORAGE_KEY)
  } catch {}
}

export function dashboardApiUrl(path, apiBase = API_BASE) {
  const value = String(path || '')
  if (/^https?:\/\//i.test(value)) return value
  return `${String(apiBase || '').replace(/\/$/, '')}/${value.replace(/^\//, '')}`
}

function errorDetail(json, fallback) {
  if (typeof json?.detail === 'string') return json.detail
  if (json?.detail != null) {
    try { return JSON.stringify(json.detail) } catch {}
  }
  return fallback
}

export class DashboardApiError extends Error {
  constructor(message, status, payload = null) {
    super(message)
    this.name = 'DashboardApiError'
    this.status = status
    this.payload = payload
  }
}

export async function dashboardApi(
  path,
  options = {},
  {
    fetchImpl = globalThis.fetch,
    storage = browserStorage(),
    apiBase = API_BASE,
  } = {},
) {
  const headers = { ...(options.headers || {}) }
  const token = readDashboardSessionToken(storage)
  if (token) headers['X-Dashboard-Session'] = token
  const response = await fetchImpl(dashboardApiUrl(path, apiBase), {
    credentials: 'include',
    cache: 'no-store',
    ...options,
    headers,
  })
  const json = await response.json().catch(() => ({}))
  if (json?.session_token) writeDashboardSessionToken(json.session_token, storage)
  if (json?.authenticated === false) writeDashboardSessionToken('', storage)
  if (response.status === 401) writeDashboardSessionToken('', storage)
  if (!response.ok) {
    throw new DashboardApiError(
      errorDetail(json, `${response.status} request failed`),
      response.status,
      json,
    )
  }
  return json
}

export async function dashboardDownload(
  path,
  options = {},
  {
    fetchImpl = globalThis.fetch,
    storage = browserStorage(),
    apiBase = API_BASE,
  } = {},
) {
  const headers = { ...(options.headers || {}) }
  const token = readDashboardSessionToken(storage)
  if (token) headers['X-Dashboard-Session'] = token
  const response = await fetchImpl(dashboardApiUrl(path, apiBase), {
    credentials: 'include',
    cache: 'no-store',
    ...options,
    headers,
  })
  if (response.status === 401) writeDashboardSessionToken('', storage)
  if (!response.ok) {
    const json = await response.json().catch(() => ({}))
    throw new DashboardApiError(
      errorDetail(json, `${response.status} request failed`),
      response.status,
      json,
    )
  }
  return response
}

export async function logoutDashboardSession(dependencies) {
  try {
    return await dashboardApi('/my-dashboard/auth/logout', { method: 'POST' }, dependencies)
  } finally {
    writeDashboardSessionToken('', dependencies?.storage)
  }
}

export function hasDashboardCapability(profile, capability) {
  return Array.isArray(profile?.capabilities) && profile.capabilities.includes(capability)
}

export function adminAccessState({ loading = false, authenticated = false, status = null } = {}) {
  if (loading) return 'loading'
  if (!authenticated || status === 401) return 'sign_in_required'
  if (status === 403) return 'access_denied'
  if (status && status >= 400) return 'error'
  return 'ready'
}

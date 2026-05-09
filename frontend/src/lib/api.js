const PROD_API_BASE = 'https://mlb-prediction-app-production-732c.up.railway.app'

export const API_BASE = import.meta.env.VITE_API_BASE_URL || PROD_API_BASE

export function getMlbToday() {
  const parts = new Intl.DateTimeFormat('en-CA', {
    timeZone: 'America/New_York',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
  }).formatToParts(new Date())

  const values = Object.fromEntries(parts.map(part => [part.type, part.value]))
  return `${values.year}-${values.month}-${values.day}`
}

/**
 * Return the current MLB "live" date, accounting for late-night rollover.
 * Games that start before 5 AM ET are still part of the previous day's slate.
 */
export function getMlbLiveDate() {
  const now = new Date()
  const etHour = Number(
    new Intl.DateTimeFormat('en-US', {
      timeZone: 'America/New_York',
      hour: 'numeric',
      hour12: false,
    }).format(now),
  )

  const adjusted = etHour < 5 ? new Date(now.getTime() - 24 * 60 * 60 * 1000) : now

  const parts = new Intl.DateTimeFormat('en-CA', {
    timeZone: 'America/New_York',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
  }).formatToParts(adjusted)

  const values = Object.fromEntries(parts.map(part => [part.type, part.value]))
  return `${values.year}-${values.month}-${values.day}`
}

/**
 * Add (or subtract) days from an ISO date string (YYYY-MM-DD).
 */
export function addIsoDays(dateStr, days) {
  const d = new Date(dateStr + 'T12:00:00')
  d.setDate(d.getDate() + days)
  return d.toISOString().slice(0, 10)
}

const MLB_TIME_ZONE = 'America/New_York'

export function mlbDateIso(date = new Date()) {
  const parts = new Intl.DateTimeFormat('en-CA', {
    timeZone: MLB_TIME_ZONE,
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
  }).formatToParts(date)
  const values = Object.fromEntries(parts.map(part => [part.type, part.value]))
  return `${values.year}-${values.month}-${values.day}`
}

export function formatEasternDateTime(value) {
  if (!value) return '—'
  const date = value instanceof Date ? value : new Date(value)
  if (!Number.isFinite(date.getTime())) return String(value)
  const formatted = new Intl.DateTimeFormat('en-US', {
    timeZone: MLB_TIME_ZONE,
    month: 'short',
    day: 'numeric',
    year: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
  }).format(date)
  return `${formatted} ET`
}

export function csvEscape(value) {
  if (value === null || value === undefined) return ''
  const text = typeof value === 'object' ? JSON.stringify(value) : String(value)
  return /[",\n\r]/.test(text) ? `"${text.replaceAll('"', '""')}"` : text
}

export function buildReportCsv({ columns, rows, fieldMap, getValue }) {
  const header = columns.map(accessor => csvEscape(fieldMap[accessor]?.label || accessor)).join(',')
  const body = rows.map(row => columns.map(accessor => csvEscape(getValue(row, accessor))).join(','))
  return [header, ...body].join('\r\n')
}

export function safeFilenamePart(value) {
  return String(value || 'report')
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '') || 'report'
}

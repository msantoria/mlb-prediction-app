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

export function paginatedResultRows(result = {}) {
  if (Array.isArray(result?.records) && (result.records.length || !Array.isArray(result?.items))) {
    return result.records
  }
  return Array.isArray(result?.items) ? result.items : []
}

export async function collectPaginatedRows(fetchPage, { maxPages = 10000 } = {}) {
  if (typeof fetchPage !== 'function') throw new TypeError('fetchPage must be a function')

  const rows = []
  const visitedPages = new Set()
  let pageNumber = 1

  while (pageNumber <= maxPages) {
    if (visitedPages.has(pageNumber)) throw new Error('CSV export received a repeated page number')
    visitedPages.add(pageNumber)

    const result = await fetchPage(pageNumber)
    const pageRows = paginatedResultRows(result)
    rows.push(...pageRows)

    const pageInfo = result?.page_info || {}
    const totalValue = result?.totalSize ?? result?.total_size
    const total = Number(totalValue)
    const hasTotal = Number.isFinite(total) && total >= 0
    const explicitHasNext = pageInfo.has_next ?? pageInfo.has_next_page
    const hasNext = explicitHasNext === true || (hasTotal && rows.length < total)

    if (!hasNext) return rows
    if (!pageRows.length) throw new Error('CSV export stopped before every matching row was returned')

    const nextPage = Number(pageInfo.next_page)
    pageNumber = Number.isInteger(nextPage) && nextPage > pageNumber ? nextPage : pageNumber + 1
  }

  throw new Error(`CSV export exceeded the ${maxPages}-page safety limit`)
}

export function safeFilenamePart(value) {
  return String(value || 'report')
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '') || 'report'
}

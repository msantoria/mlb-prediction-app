export function normalizeRate(value) {
  if (value == null || Number.isNaN(Number(value))) return null
  const n = Number(value)
  return n > 1 ? n / 100 : n
}

export function fmtPct(value, digits = 1) {
  const n = normalizeRate(value)
  if (n == null) return '—'
  return `${(n * 100).toFixed(digits)}%`
}

export function fmtDec(value, digits = 3) {
  if (value == null || Number.isNaN(Number(value))) return '—'
  return Number(value).toFixed(digits)
}

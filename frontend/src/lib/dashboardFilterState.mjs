const VALUELESS_OPERATORS = new Set(['is_null', 'is_not_null'])
const LEGACY_FIELD_ALIASES = {
  xwOBA: 'xwoba', xBA: 'xba', EV: 'exit_velocity', LA: 'launch_angle',
  HardHit: 'hard_hit_rate', 'K%': 'strikeout_rate', 'BB%': 'walk_rate',
  ISO: 'iso', OBP: 'obp', SLG: 'slg', PA: 'plate_appearances', Score: 'model_score',
  'xwOBA Allowed': 'xwoba', 'xBA Allowed': 'xba', 'HardHit Allowed': 'hard_hit_rate',
}

export const FILTER_LOGIC_OPTIONS = [
  { value: 'and', label: 'Match all' },
  { value: 'or', label: 'Match any' },
]

export function filterableReportFields(fields = []) {
  return fields.filter(field => field?.filterable === true)
}

export function defaultOperator(field) {
  const operators = Array.isArray(field?.supportedOperators) ? field.supportedOperators : []
  return operators[0] || 'eq'
}

export function newFilterCondition(fields = []) {
  const field = filterableReportFields(fields)[0]
  return field
    ? { field: field.accessor, operator: defaultOperator(field), value: '' }
    : { field: '', operator: 'eq', value: '' }
}

export function operatorNeedsValue(operator) {
  return !VALUELESS_OPERATORS.has(String(operator || '').toLowerCase())
}

export function filterInputType(field, operator) {
  if (String(operator).toLowerCase() === 'in') return 'text'
  if (field?.dataType === 'datetime') return 'datetime-local'
  if (['double', 'number', 'float', 'integer', 'id'].includes(field?.dataType)) return 'number'
  return 'text'
}

export function cleanCanonicalFilters(filters = {}) {
  const logic = filters.logic === 'or' ? 'or' : 'and'
  const conditions = (Array.isArray(filters.conditions) ? filters.conditions : [])
    .filter(condition => {
      if (!condition?.field || !condition?.operator) return false
      return !operatorNeedsValue(condition.operator)
        || (condition.value !== '' && condition.value != null)
    })
    .map(condition => {
      const operator = String(condition.operator).toLowerCase()
      const cleaned = { field: String(condition.field), operator }
      if (operatorNeedsValue(operator)) {
        cleaned.value = operator === 'in'
          ? String(condition.value).split(',').map(value => value.trim()).filter(Boolean)
          : condition.value
      }
      return cleaned
    })
    .filter(condition => condition.operator !== 'in' || condition.value.length > 0)
  return { logic, conditions }
}

export function canonicalFilterCount(filters = {}) {
  return cleanCanonicalFilters(filters).conditions.length
}

export function normalizeSavedFilters(filters = {}) {
  if (Array.isArray(filters?.conditions)) {
    return {
      ...filters,
      logic: filters.logic === 'or' ? 'or' : 'and',
      conditions: filters.conditions.map(condition => ({ ...condition })),
    }
  }
  const conditions = []
  if (filters.search_text) conditions.push({ field: 'full_name', operator: 'contains', value: filters.search_text })
  if (filters.team && filters.team !== 'All') conditions.push({ field: 'team_name', operator: 'eq', value: filters.team })
  if (filters.team_id != null && filters.team_id !== '') conditions.push({ field: 'team_id', operator: 'eq', value: filters.team_id })
  if (filters.min_score != null && filters.min_score !== '') conditions.push({ field: 'model_score', operator: 'gte', value: filters.min_score })
  if (filters.max_score != null && filters.max_score !== '') conditions.push({ field: 'model_score', operator: 'lte', value: filters.max_score })
  if (filters.min_confidence) conditions.push({ field: 'confidence', operator: 'gte', value: filters.min_confidence })
  Object.entries(filters.metrics || {}).forEach(([rawField, bounds]) => {
    const field = LEGACY_FIELD_ALIASES[rawField] || rawField
    if (bounds?.min != null && bounds.min !== '') conditions.push({ field, operator: 'gte', value: bounds.min })
    if (bounds?.max != null && bounds.max !== '') conditions.push({ field, operator: 'lte', value: bounds.max })
  })
  const weights = Object.fromEntries(
    Object.entries(filters.weights || {}).map(([field, value]) => [
      LEGACY_FIELD_ALIASES[field] || field,
      value,
    ]),
  )
  return { logic: 'and', conditions, weights }
}

import { queryPayload } from './dashboardQueryState.mjs'

export const CANONICAL_REPORT_TYPES = {
  hitters: 'all_active_hitters',
  pitchers: 'all_active_pitchers',
  teams: 'teams_daily_analysis',
  totals: 'games_totals_analysis',
  overall_players: 'overall_players_daily_analysis',
  model_projections: 'model_projection_games',
  model_projection_players: 'model_projection_players',
  model_tracker: 'model_tracker_snapshots',
  batter_arsenal: 'competitive_batter_arsenal',
  player_trends: 'player_trends',
}

const LEGACY_DEFAULT_FIELDS = ['rank', 'entity_name', 'team', 'opponent', 'score', 'confidence']

export const DEFAULT_FIELDS_BY_OBJECT = {
  hitters: ['rank', 'full_name', 'team_name', 'model_score', 'confidence'],
  pitchers: ['rank', 'full_name', 'team_name', 'model_score', 'confidence'],
  teams: LEGACY_DEFAULT_FIELDS,
  totals: ['rank', 'entity_name', 'score', 'confidence'],
  overall_players: LEGACY_DEFAULT_FIELDS,
  model_projections: ['game_pk', 'away_team_name', 'home_team_name', 'away_win_probability', 'home_win_probability', 'projected_total'],
  model_projection_players: ['full_name', 'player_type', 'team_name', 'projected_dfs_points', 'dfs_floor', 'dfs_ceiling'],
  model_tracker: ['snapshot_date', 'pick_label', 'model_name', 'score', 'grade', 'result_status'],
  batter_arsenal: ['batter_name', 'team_name', 'opposing_team_name', 'pitcher_pitch_name', 'pitcher_usage_pct', 'pitches_seen', 'xwoba', 'edge_score', 'matchup_confidence'],
  player_trends: ['rank', 'player_name', 'team', 'metric_label', 'current_value', 'baseline_value', 'absolute_change', 'trend_direction'],
}

export function defaultFieldsForObject(objectKey) {
  return [...(DEFAULT_FIELDS_BY_OBJECT[objectKey] || LEGACY_DEFAULT_FIELDS)]
}

export function defaultReportSaveAsDraft({ label, date, folderId }) {
  return {
    title: `${String(label || 'Report').trim()} Report | ${date}`,
    folder_id: folderId == null ? '' : String(folderId),
  }
}

export function initialFieldsByObject(objects, persisted = {}) {
  const defaults = Object.fromEntries(objects.map(object => [object.key, defaultFieldsForObject(object.key)]))
  if (persisted.selectedFieldsByObject && typeof persisted.selectedFieldsByObject === 'object') {
    Object.entries(persisted.selectedFieldsByObject).forEach(([key, fields]) => {
      if (Array.isArray(fields) && fields.length) defaults[key] = fields
    })
  }
  return defaults
}

export function reportFieldsForMode({ objectKey, activeLineupsOnly, selectedFields }) {
  return Array.isArray(selectedFields) && selectedFields.length
    ? [...selectedFields]
    : defaultFieldsForObject(objectKey)
}

export function selectableRequestFields(selectedFields = [], availableFields = []) {
  const allowed = new Set(
    availableFields
      .filter(field => field?.accessor && field.selectable !== false)
      .map(field => field.accessor),
  )
  return selectedFields.filter(field => allowed.has(field))
}

export function canonicalSortField(field, objectKey) {
  if (field === 'score') {
    if (objectKey === 'model_projections') return 'home_win_probability'
    if (objectKey === 'model_projection_players') return 'projected_dfs_points'
    if (objectKey === 'batter_arsenal') return 'pitches_seen'
    if (objectKey === 'model_tracker') return 'score'
    if (objectKey === 'player_trends') return 'absolute_change'
  }
  if (!['hitters', 'pitchers'].includes(objectKey)) return field
  return ({
    entity_name: 'full_name',
    team: 'team_name',
    score: 'adjusted_score',
    base_score: 'model_score',
  })[field] || field
}

export function buildReportRequest({
  objectKey,
  activeLineupsOnly,
  date,
  cleanedFilters,
  query,
  selectedFields,
  trendConfig,
}) {
  const reportType = CANONICAL_REPORT_TYPES[objectKey]
  const confirmedCanonicalHitters = Boolean(
    activeLineupsOnly && objectKey === 'hitters' && reportType,
  )
  const { weights = {}, ...criteria } = cleanedFilters || {}
  if (reportType) {
    return {
      path: '/my-dashboard/reports/query',
      reportType,
      payload: {
        report_type: reportType,
        as_of_date: date,
        filters: criteria,
        weights,
        page_size: query.page_size,
        page_number: query.page_number,
        sort_by: canonicalSortField(query.sort_by, objectKey),
        sort_direction: query.sort_direction,
        selected_fields: Array.isArray(selectedFields) ? selectedFields : undefined,
        include_metadata: true,
        confirmed_lineups_only: Boolean(
          activeLineupsOnly && (
            confirmedCanonicalHitters ||
            objectKey === 'overall_players'
          )
        ),
        trend_config: objectKey === 'player_trends' ? trendConfig : undefined,
      },
    }
  }
  return {
    path: '/my-dashboard/solver',
    reportType: null,
    payload: queryPayload({ date, component: objectKey, filters: cleanedFilters, query }),
  }
}


export function canonicalBootstrapMessage(result) {
  const bootstrap = result?.population_bootstrap
  if (!bootstrap || !bootstrap.status) {
    return { tone: 'empty', title: 'No qualifying rows', detail: 'No records matched this server query.' }
  }
  const run = bootstrap.run_id ? ` Run #${bootstrap.run_id}.` : ''
  if (bootstrap.status === 'in_progress') {
    return { tone: 'loading', title: 'Canonical population is refreshing', detail: `The verified roster refresh is still running.${run} Retry shortly.` }
  }
  if (bootstrap.status === 'failed') {
    const errorType = bootstrap.error_type || 'UnknownError'
    return { tone: 'error', title: 'Canonical population failed', detail: `The guarded refresh failed with ${errorType}.${run}` }
  }
  if (bootstrap.status === 'disabled') {
    return { tone: 'error', title: 'Canonical population is disabled', detail: 'Automatic canonical population is disabled by server configuration.' }
  }
  if (bootstrap.status === 'empty') {
    return { tone: 'error', title: 'Canonical population remained empty', detail: `The guarded refresh completed without reportable current rows.${run}` }
  }
  return { tone: 'empty', title: 'No qualifying rows', detail: 'No records matched this server query.' }
}

export function normalizeCanonicalPage(json, query) {
  const total = Number(json?.totalSize || 0)
  const records = Array.isArray(json?.records) ? json.records : []
  const pageCount = total ? Math.ceil(total / query.page_size) : 0
  const hasNext = Boolean(json?.page_info?.has_next_page ?? json?.page_info?.has_next)
  return {
    ...json,
    execution_path: json?.execution_path || 'catalog_report_query',
    page_info: {
      ...json?.page_info,
      page_number: query.page_number,
      page_size: query.page_size,
      page_count: pageCount,
      record_count: records.length,
      has_next: hasNext,
      has_previous: query.page_number > 1 && total > 0,
      next_page: hasNext ? query.page_number + 1 : null,
      previous_page: query.page_number > 1 ? query.page_number - 1 : null,
    },
  }
}

export function reportExecutionFacts(result) {
  const population = result?.population || {}
  const lineup = result?.lineup_filter || {}
  const provenance = result?.provenance || {}
  const bootstrap = result?.population_bootstrap || {}
  const mode = population.mode === 'confirmed_lineup'
    ? 'Confirmed 1–9'
    : population.mode === 'all_active'
      ? 'All active players'
      : population.mode === 'daily_dataset'
        ? 'Daily report population'
        : 'Legacy report population'
  return {
    mode,
    lineupStatus: lineup.lineup_status || null,
    confirmedCount: lineup.confirmed_batter_count ?? null,
    snapshotDate: provenance.snapshot_date || bootstrap.latest_snapshot_date || null,
    projectionVersion: Array.isArray(provenance.projection_versions)
      ? provenance.projection_versions[0] || null
      : null,
    ageHours: bootstrap.age_hours ?? null,
  }
}

export function savedReportExecutionMode(item, fallback = false) {
  const payload = item?.payload_json || {}
  const definition = payload.definition || {}
  if (typeof definition.active_lineups_only === 'boolean') {
    return definition.active_lineups_only
  }
  if (typeof payload.workbench_state?.activeLineupsOnly === 'boolean') {
    return payload.workbench_state.activeLineupsOnly
  }
  return Boolean(fallback)
}

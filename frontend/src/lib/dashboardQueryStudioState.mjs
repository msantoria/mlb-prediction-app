export const QUERY_STUDIO_EXAMPLE = `SELECT full_name, team_name, model_score
FROM all_active_hitters
WHERE model_score >= 0.5 AND confidence = 'high'
ORDER BY model_score DESC
LIMIT 50`

export function canOpenQueryStudio(profile = {}) {
  return Array.isArray(profile.capabilities) && profile.capabilities.includes('workbench.advanced')
}

export function queryStudioObjects(metadata = {}) {
  if (!Array.isArray(metadata?.objects)) return []
  return metadata.objects
    .filter(object => object && typeof object === 'object' && object.api_name)
    .map(object => ({
      ...object,
      fields: Array.isArray(object.fields)
        ? object.fields.filter(field => field && typeof field === 'object' && field.name)
        : [],
    }))
}

export function queryStudioRows(result = {}) {
  if (Array.isArray(result?.records)) return result.records
  return Array.isArray(result?.items) ? result.items : []
}

export function queryStudioColumns(result = {}) {
  const selected = result?.workbench_plan?.selected_fields
  if (Array.isArray(selected) && selected.length) return [...selected]
  return []
}

export function queryStudioSavePayload({ folderId, statement, result, title }) {
  const plan = result?.workbench_plan || {}
  const columns = queryStudioColumns(result)
  return {
    folder_id: Number(folderId),
    source_tab: 'my-dashboard',
    source_type: 'workbench_view',
    title,
    subtitle: 'Saved Query Studio result',
    notes: 'Saved from MLBGPT Query Studio.',
    payload_json: {
      schema_version: 4,
      definition: {
        component: result?.component || null,
        report_type: result?.report_type || plan.logical_object || null,
        selected_fields: columns,
        filters: plan.filters || [],
        sort: plan.sort || {},
        page_size: plan?.pagination?.page_size || null,
        query_studio_statement: statement,
        query_studio_language: plan.language || 'mlbgpt_query_v1',
      },
      snapshot: { board_state: result, generated_at: new Date().toISOString() },
      board_state: result,
      report_columns: columns,
      workbench_state: { selectedFields: columns, queryStudioStatement: statement },
    },
    filter_json: { conditions: plan.filters || [] },
    sort_json: {
      by: plan?.sort?.field || null,
      direction: plan?.sort?.direction || 'desc',
      component: result?.component || null,
      query_studio: true,
    },
  }
}

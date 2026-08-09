export const LEGACY_MY_DASHBOARD_UI_OBJECTS = new Set(['teams', 'totals', 'overall_players'])

export function visibleMyDashboardObjects(objects = []) {
  return objects.filter(object => !LEGACY_MY_DASHBOARD_UI_OBJECTS.has(object?.key))
}

export function normalizeVisibleMyDashboardObject(objectKey, fallback = 'hitters') {
  return LEGACY_MY_DASHBOARD_UI_OBJECTS.has(objectKey) ? fallback : (objectKey || fallback)
}

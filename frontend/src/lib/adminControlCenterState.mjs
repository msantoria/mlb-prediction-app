export const EDITABLE_DIRECTORY_FIELDS = Object.freeze([
  'username',
  'first_name',
  'last_name',
  'display_name',
  'alias',
  'title',
  'company',
  'locale',
  'language',
  'timezone',
  'is_active',
  'is_locked',
  'is_admin',
])

export function editableUserPayload(values = {}) {
  return Object.fromEntries(
    EDITABLE_DIRECTORY_FIELDS
      .filter(key => Object.prototype.hasOwnProperty.call(values, key))
      .map(key => [key, values[key]]),
  )
}

export function userEditorValues(user = {}) {
  const directory = user.directory || {}
  return editableUserPayload({
    username: user.username || '',
    first_name: directory.first_name || '',
    last_name: directory.last_name || '',
    display_name: directory.display_name || '',
    alias: directory.alias || '',
    title: directory.title || '',
    company: directory.company || '',
    locale: directory.locale || 'en_US',
    language: directory.language || 'en',
    timezone: directory.timezone || 'America/New_York',
    is_active: directory.is_active !== false,
    is_locked: Boolean(directory.is_locked),
    is_admin: user.role === 'admin',
  })
}

export function settingUpdatePayload(setting, value) {
  return {
    updates: [{ namespace: setting.namespace, key: setting.key, value }],
  }
}

export function featureFlagUpdatePayload(flag, enabled, targetProfiles = flag.target_profiles || []) {
  return {
    updates: [{ key: flag.key, enabled: Boolean(enabled), target_profiles: [...targetProfiles] }],
  }
}

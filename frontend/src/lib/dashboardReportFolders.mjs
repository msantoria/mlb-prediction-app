function dateValue(value) {
  const text = String(value || '').slice(0, 10)
  if (!/^\d{4}-\d{2}-\d{2}$/.test(text)) return null
  const parsed = new Date(`${text}T00:00:00Z`)
  return Number.isFinite(parsed.getTime()) && parsed.toISOString().slice(0, 10) === text ? text : null
}

function uniqueItems(folders) {
  const seen = new Set()
  return folders.flatMap(folder => Array.isArray(folder?.items) ? folder.items : []).filter(item => {
    const key = String(item?.id ?? `${item?.title}:${item?.created_at}`)
    if (seen.has(key)) return false
    seen.add(key)
    return true
  })
}

function mondayFor(value) {
  const date = new Date(`${value}T00:00:00Z`)
  const offset = (date.getUTCDay() + 6) % 7
  date.setUTCDate(date.getUTCDate() - offset)
  return date.toISOString().slice(0, 10)
}

function rollup(folders, keyForDate, labelForKey) {
  const buckets = new Map()
  folders.forEach(folder => {
    const date = dateValue(folder?.folder_date)
    if (!date) return
    const key = keyForDate(date)
    if (!buckets.has(key)) buckets.set(key, [])
    buckets.get(key).push(folder)
  })
  return Array.from(buckets.entries())
    .sort(([left], [right]) => right.localeCompare(left))
    .map(([key, groupedFolders]) => ({
      key,
      label: labelForKey(key),
      folderIds: groupedFolders.map(folder => folder.id),
      item_count: groupedFolders.reduce((sum, folder) => sum + Number(folder.item_count || 0), 0),
      items: uniqueItems(groupedFolders),
      virtual: true,
    }))
}

export function organizeReportFolders(folders = []) {
  const safeFolders = Array.isArray(folders) ? folders : []
  const dated = safeFolders
    .filter(folder => dateValue(folder?.folder_date))
    .sort((left, right) => String(right.folder_date).localeCompare(String(left.folder_date)))
  const daily = dated.map(folder => ({
    ...folder,
    key: `daily:${folder.id}`,
    label: folder.folder_name || folder.folder_date,
    virtual: false,
  }))
  const weekly = rollup(
    dated,
    mondayFor,
    key => `Week of ${key}`,
  )
  const monthly = rollup(
    dated,
    date => date.slice(0, 7),
    key => key,
  )
  const custom = safeFolders
    .filter(folder => folder.is_default || !dateValue(folder.folder_date) || folder.folder_name !== folder.folder_date)
    .map(folder => ({
      ...folder,
      key: `custom:${folder.id}`,
      label: folder.folder_name || 'Untitled folder',
      virtual: false,
    }))

  return { daily, weekly, monthly, custom }
}

export function reportFolderSummary(folders = []) {
  const safeFolders = Array.isArray(folders) ? folders : []
  return {
    folderCount: safeFolders.length,
    itemCount: safeFolders.reduce((sum, folder) => sum + Number(folder.item_count || 0), 0),
  }
}

import React, { useEffect, useMemo, useState } from 'react'
import QueryStudioPanel from '../components/QueryStudioPanel.jsx'
import { buildReportCsv, mlbDateIso, safeFilenamePart } from '../lib/dashboardReportUtils.mjs'
import { DEFAULT_PAGE_SIZE, PAGE_SIZE_OPTIONS, defaultQueryState, normalizeQueryState, resultRange, serverFields } from '../lib/dashboardQueryState.mjs'
import { CANONICAL_REPORT_TYPES, buildReportRequest, canonicalBootstrapMessage, defaultFieldsForObject, initialFieldsByObject, normalizeCanonicalPage, reportFieldsForMode } from '../lib/dashboardReportBuilderState.mjs'
import { organizeReportFolders, reportFolderSummary } from '../lib/dashboardReportFolders.mjs'
import { dashboardRenameRequest, renameKeyboardAction } from '../lib/dashboardRenameState.mjs'
import { dashboardApi, hasDashboardCapability, logoutDashboardSession } from '../lib/dashboardSession.mjs'
import { DASHBOARD_THEME_KEY, DASHBOARD_THEME_OPTIONS, dashboardThemeVariables, normalizeDashboardTheme, resolveDashboardTheme } from '../lib/dashboardThemeState.mjs'

const BUILDER_KEY = 'mlbgpt-report-builder:v3'

const OBJECTS = [
  { key: 'hitters', label: 'Hitters', description: 'Batter vs arsenal, quality-of-contact, matchup, and model fields.' },
  { key: 'pitchers', label: 'Pitchers', description: 'Pitcher skills, contact suppression, opponent profile, and model fields.' },
  { key: 'teams', label: 'Teams', description: 'Team offense, projected runs, side edge, and matchup fields.' },
  { key: 'totals', label: 'Totals', description: 'Projected game totals, run environment, and simulation fields.' },
  { key: 'overall_players', label: 'Overall Players', description: 'Combined hitter and pitcher report.' },
]
const ACTIVE_LINEUP_OBJECTS = new Set(['hitters', 'overall_players'])
const DEFAULT_FIELDS = ['rank', 'entity_name', 'team', 'opponent', 'score', 'confidence']
const BASE_FIELDS = [
  ['rank', 'Rank', 'Identity'], ['entity_name', 'Name', 'Identity'], ['entity_id', 'Entity ID', 'Identity'],
  ['entity_type', 'Entity Type', 'Identity'], ['player_type', 'Player Type', 'Identity'], ['team', 'Team', 'Matchup'],
  ['opponent', 'Opponent', 'Matchup'], ['game_pk', 'Game PK', 'Matchup'], ['pitch_type', 'Pitch Type', 'Matchup'],
  ['pitch_name', 'Pitch Name', 'Matchup'], ['category', 'Category', 'Classification'], ['score', 'Score', 'Scoring'],
  ['base_score', 'Base Score', 'Scoring'], ['adjusted_score', 'Adjusted Score', 'Scoring'], ['confidence', 'Confidence', 'Scoring'],
  ['source', 'Source', 'Audit'], ['primary_reason', 'Primary Reason', 'Audit'], ['lineup_verified', 'Lineup Verified', 'Audit'],
  ['lineup_source', 'Lineup Source', 'Audit'],
].map(([accessor, label, group]) => ({ accessor, label, group, sortable: accessor !== 'primary_reason' }))
const DEFAULT_METRICS = {
  hitters: ['xwOBA', 'xBA', 'EV', 'LA', 'HardHit', 'Usage', 'Pitcher xwOBA', 'Pitches Seen', 'PA'],
  pitchers: ['K%', 'BB%', 'xwOBA Allowed', 'HardHit Allowed', 'Opp K%', 'Opp ISO', 'Score'],
  teams: ['Edge Score', 'Win Edge', 'Run Diff', 'ISO', 'OBP', 'SLG'],
  totals: ['Projected Total', 'Raw Total', 'Run Index', 'Score'],
  overall_players: ['Score', 'xwOBA', 'EV', 'K%', 'xwOBA Allowed'],
}
const C = { bg: 'var(--md-bg)', panel: 'var(--md-panel)', panel2: 'var(--md-panel-2)', border: 'var(--md-border)', text: 'var(--md-text)', muted: 'var(--md-muted)', blue: '#8176ff', green: '#28b78b', amber: '#d99a36', red: '#e06a75' }
const FRANKLIN = '"Franklin Gothic Medium", "Franklin Gothic", "Arial Narrow", Arial, sans-serif'
const CENTURY = '"Century Gothic", CenturyGothic, AppleGothic, Arial, sans-serif'

class DashboardWorkspaceErrorBoundary extends React.Component {
  constructor(props) {
    super(props)
    this.state = { error: null }
  }

  static getDerivedStateFromError(error) {
    return { error }
  }

  componentDidCatch(error, info) {
    console.error('MyDashboard workspace render failed', error, info)
  }

  async signOut() {
    await logoutDashboardSession().catch(() => null)
    window.location.assign('/my-dashboard')
  }

  render() {
    if (!this.state.error) return this.props.children
    return <main style={s.crashPage}>
      <section style={s.crashCard}>
        <div style={s.eyebrow}>MyDashboard recovery</div>
        <h1 style={s.crashTitle}>The workspace could not finish loading.</h1>
        <p style={s.crashCopy}>Your session is still protected. Reload the latest workspace, or sign out to return to the landing page.</p>
        <div style={s.actions}>
          <button type="button" style={s.primary} onClick={() => window.location.reload()}>Reload Workspace</button>
          <button type="button" style={s.secondary} onClick={() => this.signOut()}>Sign Out</button>
        </div>
      </section>
    </main>
  }
}

function safeArray(value) { return Array.isArray(value) ? value : [] }
function titleCase(value) { return String(value || '').replace(/[_.-]+/g, ' ').replace(/\s+/g, ' ').trim().replace(/\b\w/g, c => c.toUpperCase()) }
function readJson(key, fallback) { try { return JSON.parse(localStorage.getItem(key)) || fallback } catch { return fallback } }
function writeJson(key, value) { try { localStorage.setItem(key, JSON.stringify(value)) } catch {} }
function readThemePreference() { try { return normalizeDashboardTheme(localStorage.getItem(DASHBOARD_THEME_KEY)) } catch { return 'system' } }
function emptyFilters() { return { search_text: '', team: '', opponent: '', min_score: '', max_score: '', min_confidence: '', category: '', pitch_type: '', metrics: {}, weights: {} } }
function cleanFilters(filters) {
  const out = {}
  Object.entries(filters || {}).forEach(([key, value]) => { if (!['metrics', 'weights'].includes(key) && value !== '' && value != null) out[key] = value })
  const metrics = {}
  Object.entries(filters?.metrics || {}).forEach(([metric, rule]) => {
    const next = {}
    if (rule?.min !== '' && rule?.min != null) next.min = Number(rule.min)
    if (rule?.max !== '' && rule?.max != null) next.max = Number(rule.max)
    if (Object.keys(next).length) metrics[metric] = next
  })
  if (Object.keys(metrics).length) out.metrics = metrics
  const weights = {}
  Object.entries(filters?.weights || {}).forEach(([metric, value]) => { const number = Number(value); if (Number.isFinite(number) && number !== 1) weights[metric] = number })
  if (Object.keys(weights).length) out.weights = weights
  return out
}
function getValue(row, accessor) { return accessor.startsWith('metrics.') ? row?.metrics?.[accessor.slice(8)] : accessor.split('.').reduce((value, key) => value == null ? null : value[key], row) }
function formatCell(value) {
  if (value === '' || value == null) return '—'
  if (typeof value === 'number') return Math.abs(value) >= 10 ? value.toFixed(1) : value.toFixed(3)
  if (typeof value === 'boolean') return value ? 'Yes' : 'No'
  if (Array.isArray(value)) return value.slice(0, 4).join(', ')
  if (typeof value === 'object') return JSON.stringify(value)
  return String(value)
}
function fieldsForResult(result, objectKey) {
  const fallback = [...BASE_FIELDS]
  const defaults = DEFAULT_METRICS[objectKey] || []
  defaults.forEach(metric => fallback.push({ accessor: `metrics.${metric}`, label: metric, group: 'Metrics', sortable: true }))
  const described = serverFields(result, fallback)
  const seen = new Map(described.map(field => [field.accessor, field]))
  safeArray(result?.items).forEach(row => {
    Object.keys(row || {}).forEach(key => { if (!['chart_data', 'reasoning', 'missing_data', 'best_pitch_angles', 'metrics'].includes(key) && !seen.has(key)) seen.set(key, { accessor: key, label: titleCase(key), group: 'Runtime', sortable: true }) })
    Object.keys(row?.metrics || {}).forEach(metric => { const accessor = `metrics.${metric}`; if (!seen.has(accessor)) seen.set(accessor, { accessor, label: metric, group: 'Metrics', sortable: true }) })
  })
  return Array.from(seen.values())
}
function downloadTextFile(filename, contents, mimeType) {
  const blob = new Blob([contents], { type: mimeType }); const url = URL.createObjectURL(blob); const link = document.createElement('a')
  link.href = url; link.download = filename; document.body.appendChild(link); link.click(); link.remove(); URL.revokeObjectURL(url)
}
function Pill({ children, tone = 'blue' }) {
  const color = tone === 'green' ? C.green : tone === 'amber' ? C.amber : tone === 'red' ? C.red : C.blue
  return <span style={{ ...s.pill, color, borderColor: `${color}55`, background: `${color}16` }}>{children}</span>
}
function StatePanel({ tone = 'empty', title, children, action }) {
  const style = tone === 'error' ? s.errorState : tone === 'loading' ? s.loadingState : s.empty
  return <div style={style}><strong>{title}</strong><div>{children}</div>{action || null}</div>
}
function ThemePicker() {
  const preference = typeof window === 'undefined' ? 'system' : readThemePreference()
  const resolvedTheme = resolveDashboardTheme(preference, typeof window !== 'undefined' && window.matchMedia?.('(prefers-color-scheme: dark)').matches)
  function changeTheme(nextTheme) {
    const normalized = normalizeDashboardTheme(nextTheme)
    try { localStorage.setItem(DASHBOARD_THEME_KEY, normalized) } catch {}
    window.dispatchEvent(new CustomEvent('mlbgpt-dashboard-theme-change', { detail: normalized }))
  }
  return <div style={s.themePicker} role="group" aria-label="Dashboard color theme">
    {DASHBOARD_THEME_OPTIONS.map(option => <button key={option} type="button" aria-pressed={preference === option} title={option === 'system' ? `System (${resolvedTheme})` : `${titleCase(option)} mode`} style={preference === option ? s.themeOptionActive : s.themeOption} onClick={() => changeTheme(option)}>{option === 'light' ? '☀ Light' : option === 'dark' ? '● Dark' : '◐ System'}</button>)}
  </div>
}
function FilterPanel({ objectKey, filters, fields, setBasic, setMetric, setWeight }) {
  const metrics = (DEFAULT_METRICS[objectKey] || []).slice(0, 10).map(metric => ({ accessor: `metrics.${metric}`, label: metric }))
  return <section style={s.card}><div style={s.panelTitle}>Filters</div><div style={s.copySmall}>Define the report criteria before generating rows.</div><div style={s.filterGrid}>
    <input style={s.input} placeholder="Search text" value={filters.search_text || ''} onChange={e => setBasic(objectKey, 'search_text', e.target.value)} />
    <input style={s.input} placeholder="Team contains" value={filters.team || ''} onChange={e => setBasic(objectKey, 'team', e.target.value)} />
    <input style={s.input} placeholder="Opponent contains" value={filters.opponent || ''} onChange={e => setBasic(objectKey, 'opponent', e.target.value)} />
    <select style={s.input} value={filters.min_confidence || ''} onChange={e => setBasic(objectKey, 'min_confidence', e.target.value)}><option value="">Any confidence</option><option value="low">Low+</option><option value="medium">Medium+</option><option value="high">High only</option></select>
    <input style={s.input} inputMode="decimal" placeholder="Minimum score" value={filters.min_score || ''} onChange={e => setBasic(objectKey, 'min_score', e.target.value)} />
    <input style={s.input} inputMode="decimal" placeholder="Maximum score" value={filters.max_score || ''} onChange={e => setBasic(objectKey, 'max_score', e.target.value)} />
    <input style={s.input} placeholder="Category" value={filters.category || ''} onChange={e => setBasic(objectKey, 'category', e.target.value)} />
    <input style={s.input} placeholder="Pitch type" value={filters.pitch_type || ''} onChange={e => setBasic(objectKey, 'pitch_type', e.target.value)} />
  </div><div style={s.sectionLabel}>Metric thresholds</div><div style={s.metricGrid}>{metrics.map(field => { const metric = field.accessor.slice(8); return <div style={s.metricCard} key={field.accessor}><strong>{field.label}</strong><div style={s.twoCol}><input style={s.miniInput} placeholder="Min" value={filters.metrics?.[metric]?.min || ''} onChange={e => setMetric(objectKey, metric, 'min', e.target.value)} /><input style={s.miniInput} placeholder="Max" value={filters.metrics?.[metric]?.max || ''} onChange={e => setMetric(objectKey, metric, 'max', e.target.value)} /></div></div> })}</div>
  <div style={s.sectionLabel}>Scoring weights</div><div style={s.metricGrid}>{metrics.slice(0, 6).map(field => { const metric = field.accessor.slice(8), value = Number(filters.weights?.[metric] ?? 1); return <label style={s.metricCard} key={`weight-${field.accessor}`}><span>{field.label}</span><input type="range" min="0" max="2" step="0.1" value={value} onChange={e => setWeight(objectKey, metric, e.target.value)} /><b>{value.toFixed(1)}</b></label> })}</div></section>
}
function FieldLibrary({ fields, selected, setSelected }) {
  const selectedSet = new Set(selected); const grouped = fields.reduce((map, field) => ({ ...map, [field.group]: [...(map[field.group] || []), field] }), {})
  function toggle(accessor) { const next = selectedSet.has(accessor) ? selected.filter(value => value !== accessor) : [...selected, accessor]; setSelected(next.length ? next : DEFAULT_FIELDS) }
  return <section style={s.card}><div style={s.cardHeader}><div><div style={s.panelTitle}>Field Library</div><div style={s.copySmall}>Choose the columns you want displayed in the finished report.</div></div><Pill>{selected.length} selected</Pill></div><div style={s.fieldGroups}>{Object.entries(grouped).map(([group, groupFields]) => <div key={group}><div style={s.sectionLabel}>{group}</div><div style={s.fieldGrid}>{groupFields.map(field => <button key={field.accessor} style={selectedSet.has(field.accessor) ? s.fieldActive : s.fieldButton} onClick={() => toggle(field.accessor)}><span>{field.label}</span><small>{field.accessor}</small></button>)}</div></div>)}</div></section>
}
function RenameEditor({ value, saving, onChange, onSave, onCancel, label }) {
  function onKeyDown(event) {
    const action = renameKeyboardAction(event.key)
    if (!action) return
    event.preventDefault()
    if (action === 'save') onSave()
    if (action === 'cancel') onCancel()
  }
  return <div style={s.renameEditor}><input autoFocus aria-label={label} maxLength={255} style={s.renameInput} value={value} onChange={event => onChange(event.target.value)} onKeyDown={onKeyDown} /><div style={s.renameActions}><button style={s.smallPrimary} disabled={saving || !value.trim()} onClick={onSave}>{saving ? 'Saving…' : 'Save'}</button><button style={s.smallSecondary} disabled={saving} onClick={onCancel}>Cancel</button></div></div>
}

function SavedReportsShelfV2({ workspace, loading, error, openSaved, refresh, renameSaved, open, setOpen, view, setView, selectedEntryKey, setSelectedEntryKey, selectedFolderId, setSelectedFolderId, newFolderName, setNewFolderName, createFolder, creatingFolder }) {
  const [editing, setEditing] = useState(null)
  const [draftName, setDraftName] = useState('')
  const [savingRename, setSavingRename] = useState(false)
  const folders = safeArray(workspace?.folders)
  const groups = useMemo(() => organizeReportFolders(folders), [folders])
  const summary = useMemo(() => reportFolderSummary(folders), [folders])
  const entries = groups[view] || []
  const selectedEntry = entries.find(entry => entry.key === selectedEntryKey) || entries[0] || null
  const items = safeArray(selectedEntry?.items).filter(item => ['workbench_view', 'report_view', 'dashboard_report'].includes(item?.source_type))
  const views = [['daily', 'Daily Reports'], ['weekly', 'Weekly Reports'], ['monthly', 'Monthly Folders'], ['custom', 'Custom Folders']]
  function selectView(nextView) { setView(nextView); setSelectedEntryKey(''); setSelectedFolderId(''); setEditing(null) }
  function selectEntry(entry) { setSelectedEntryKey(entry.key); setSelectedFolderId(entry.virtual ? '' : String(entry.id)) }
  function beginRename(kind, id, name) { setEditing({ kind, id: String(id) }); setDraftName(name || ''); }
  function cancelRename() { setEditing(null); setDraftName('') }
  async function saveRename() {
    if (!editing || savingRename) return
    setSavingRename(true)
    try { await renameSaved(editing.kind, editing.id, draftName); cancelRename() } catch {} finally { setSavingRename(false) }
  }
  return <><ThemePicker /><section style={s.card}>
    <div style={s.cardHeader}><div><div style={s.panelTitle}>Saved Reports</div><div style={s.copySmall}>Organize reports in daily, weekly, monthly, and custom folders.</div></div><div style={s.actions}><button style={s.secondary} onClick={refresh} disabled={loading}>{loading ? 'Refreshing…' : 'Refresh'}</button><button style={s.secondary} onClick={() => setOpen(current => !current)}>{open ? 'Collapse Shelf' : 'Expand Shelf'}</button></div></div>
    <div style={s.shelfSummary}><Pill>{summary.folderCount} folders</Pill><Pill tone="green">{summary.itemCount} saved reports</Pill>{selectedFolderId ? <Pill tone="amber">Save destination selected</Pill> : null}</div>
    {!open ? null : error ? <StatePanel tone="error" title="Saved reports unavailable">{error}</StatePanel> : <>
      <div style={s.shelfTabs}>{views.map(([key, label]) => <button key={key} style={view === key ? s.shelfTabActive : s.shelfTab} onClick={() => selectView(key)}>{label}<span>{groups[key]?.length || 0}</span></button>)}</div>
      {view === 'custom' ? <div style={s.newFolderRow}><input style={s.input} maxLength={255} placeholder="New folder name" value={newFolderName} onChange={event => setNewFolderName(event.target.value)} /><button style={s.primary} onClick={createFolder} disabled={creatingFolder || !newFolderName.trim()}>{creatingFolder ? 'Creating…' : 'Create Folder'}</button></div> : null}
      <div style={s.shelfGrid}>
        <div style={s.folderList}>{entries.length ? entries.map(entry => {
          const isEditing = editing?.kind === 'folder' && editing.id === String(entry.id)
          if (isEditing) return <RenameEditor key={entry.key} value={draftName} saving={savingRename} onChange={setDraftName} onSave={saveRename} onCancel={cancelRename} label="Folder name" />
          return <div key={entry.key} style={selectedEntry?.key === entry.key ? s.folderRowActive : s.folderRow}><button style={s.folderSelect} onClick={() => selectEntry(entry)}><span><strong>📁 {entry.label}</strong><small>{entry.virtual ? `${entry.folderIds.length} daily folders` : entry.folder_date || (entry.is_default ? 'Default folder' : 'Custom folder')}</small></span><b>{entry.item_count || 0}</b></button>{entry.virtual ? null : <button style={s.editButton} onClick={() => beginRename('folder', entry.id, entry.label)}>Edit</button>}</div>
        }) : <StatePanel title={`No ${views.find(([key]) => key === view)?.[1] || 'folders'} yet`}>Saved reports will appear here.</StatePanel>}</div>
        <div style={s.folderDetail}>{selectedEntry ? <><div style={s.folderDetailHeader}><div><strong>{selectedEntry.label}</strong><div style={s.copySmall}>{selectedEntry.item_count || 0} saved reports</div></div>{!selectedEntry.virtual ? <Pill tone="amber">{String(selectedEntry.id) === String(selectedFolderId) ? 'Save destination' : 'Select to save here'}</Pill> : <Pill>Browse rollup</Pill>}</div>{items.length ? <div style={s.savedList}>{items.map((item, index) => {
          const isEditing = editing?.kind === 'item' && editing.id === String(item.id)
          if (isEditing) return <RenameEditor key={item.id || index} value={draftName} saving={savingRename} onChange={setDraftName} onSave={saveRename} onCancel={cancelRename} label="Report name" />
          return <div key={item.id || index} style={s.savedItemRow}><button style={s.savedItemOpen} onClick={() => openSaved(item)}><span><strong>{item.title || 'Saved report'}</strong><small>{item.subtitle || item.source_type || 'Dashboard report'}</small></span><span>Open →</span></button><button style={s.editButton} onClick={() => beginRename('item', item.id, item.title || 'Saved report')}>Edit</button></div>
        })}</div> : <StatePanel title="No reports in this folder">Save a populated report or choose another folder.</StatePanel>}</> : <StatePanel title="Choose a folder">Select a folder to browse its reports.</StatePanel>}</div>
      </div>
    </>}
  </section></>
}
function ReportWorkspace({ open, close, objectMeta, result, fields, builderFields, generatedAt, reportDate, initialColumns, query, setQuery, reload, loading, onSave, isMobile }) {
  const [columns, setColumns] = useState(initialColumns); const [hidden, setHidden] = useState([])
  useEffect(() => { setColumns(initialColumns); setHidden([]) }, [initialColumns, result])
  const fieldMap = useMemo(() => Object.fromEntries(fields.map(field => [field.accessor, field])), [fields])
  const visible = columns.filter(accessor => !hidden.includes(accessor)); const rows = safeArray(result?.records?.length ? result.records : result?.items)
  const pageInfo = result?.page_info || { page_number: query.page_number, page_size: query.page_size, record_count: rows.length }
  const range = resultRange(pageInfo, result?.totalSize ?? rows.length)
  const bootstrapMessage = canonicalBootstrapMessage(result)
  if (!open) return null
  function requestSort(accessor) { if (fieldMap[accessor]?.sortable === false || loading) return; const next = normalizeQueryState({ ...query, page_number: 1, sort_by: accessor, sort_direction: query.sort_by === accessor && query.sort_direction === 'desc' ? 'asc' : 'desc' }); setQuery(next); reload(next) }
  function requestPage(pageNumber) { const next = normalizeQueryState({ ...query, page_number: pageNumber }); setQuery(next); reload(next) }
  function requestPageSize(value) { const next = normalizeQueryState({ ...query, page_number: 1, page_size: Number(value) }); setQuery(next); reload(next) }
  function exportCsv() { if (!rows.length || !visible.length) return; downloadTextFile(`${safeFilenamePart(objectMeta.label)}-${reportDate}-page-${pageInfo.page_number || 1}.csv`, buildReportCsv({ columns: visible, rows, fieldMap, getValue }), 'text/csv;charset=utf-8') }
  return <div style={s.overlay} role="dialog" aria-modal="true"><section style={s.reportSurface}><header style={s.reportHeader}><div><div style={s.eyebrow}>Report Workspace</div><h2 style={s.reportTitle}>{objectMeta.label} Report</h2><div style={s.copySmall}>MLB date {reportDate} · Generated {generatedAt ? new Date(generatedAt).toLocaleString() : 'now'} · Showing {range.start}–{range.end} of {range.total}</div></div><div style={s.actions}><button style={s.secondary} onClick={exportCsv} disabled={!rows.length}>Export current page CSV</button><button style={s.secondary} onClick={onSave} disabled={!rows.length}>Save Report</button><button style={s.primary} onClick={close}>Back to Builder</button></div></header><div style={{ ...s.reportBody, ...(isMobile ? s.reportBodyMobile : {}) }}><aside style={s.columnPanel}><div style={s.panelTitle}>Report Columns</div><div style={s.copySmall}>Hide or reorder columns without changing saved results.</div><div style={s.columnList}>{columns.map((accessor, index) => { const isHidden = hidden.includes(accessor); return <div style={s.columnRow} key={accessor}><label><input type="checkbox" checked={!isHidden} onChange={() => setHidden(current => isHidden ? current.filter(v => v !== accessor) : [...current, accessor])} /> {fieldMap[accessor]?.label || titleCase(accessor)}</label><div><button style={s.iconButton} disabled={index === 0} onClick={() => setColumns(current => { const next = [...current]; [next[index - 1], next[index]] = [next[index], next[index - 1]]; return next })}>↑</button><button style={s.iconButton} disabled={index === columns.length - 1} onClick={() => setColumns(current => { const next = [...current]; [next[index + 1], next[index]] = [next[index], next[index + 1]]; return next })}>↓</button></div></div> })}</div><button style={s.secondaryWide} onClick={() => { setColumns(builderFields); setHidden([]) }}>Reset to Builder Fields</button></aside><main style={s.gridPanel}><div style={s.gridToolbar}><div style={s.pillRow}><Pill>{range.total} matching rows</Pill><Pill tone="green">Sorted by: {fieldMap[query.sort_by]?.label || titleCase(query.sort_by)} {query.sort_direction}</Pill></div><label style={s.pageSize}>Rows per page <select style={s.input} value={query.page_size} onChange={e => requestPageSize(e.target.value)}>{PAGE_SIZE_OPTIONS.map(size => <option key={size} value={size}>{size}</option>)}</select></label></div>{result?.filter_warnings?.length ? <div style={s.warning}>{result.filter_warnings.join(' • ')}</div> : null}{loading ? <StatePanel tone="loading" title="Loading report page">Loading the complete report.</StatePanel> : rows.length && visible.length ? <div style={s.dataGridWrap}><table style={s.table}><thead><tr>{visible.map(accessor => <th key={accessor} style={s.th}><button style={s.sortButton} disabled={fieldMap[accessor]?.sortable === false} onClick={() => requestSort(accessor)}>{fieldMap[accessor]?.label || titleCase(accessor)} {query.sort_by === accessor ? (query.sort_direction === 'desc' ? '↓' : '↑') : '↕'}</button></th>)}</tr></thead><tbody>{rows.map((row, rowIndex) => <tr key={row.entity_id || `${objectMeta.key}-${rowIndex}`}>{visible.map(accessor => <td style={s.td} key={`${rowIndex}-${accessor}`}>{formatCell(getValue(row, accessor))}</td>)}</tr>)}</tbody></table></div> : <StatePanel tone={bootstrapMessage.tone} title={bootstrapMessage.title}>{bootstrapMessage.detail}</StatePanel>}<div style={s.pagination}><button style={s.secondary} disabled={!pageInfo.has_previous || loading} onClick={() => requestPage(pageInfo.previous_page || Math.max(1, query.page_number - 1))}>← Previous</button><span>Page {pageInfo.page_number || 1} of {pageInfo.page_count || 1}</span><button style={s.secondary} disabled={!pageInfo.has_next || loading} onClick={() => requestPage(pageInfo.next_page || query.page_number + 1)}>Next →</button></div></main></div></section></div>
}

function MyDashboardReportBuilderContent() {
  const persisted = typeof window === 'undefined' ? {} : readJson(BUILDER_KEY, {}); const [width, setWidth] = useState(() => typeof window === 'undefined' ? 1200 : window.innerWidth)
  const [themePreference, setThemePreference] = useState(() => typeof window === 'undefined' ? 'system' : readThemePreference())
  const [systemDark, setSystemDark] = useState(() => typeof window !== 'undefined' && window.matchMedia?.('(prefers-color-scheme: dark)').matches)
  useEffect(() => { const update = () => setWidth(window.innerWidth); window.addEventListener('resize', update); return () => window.removeEventListener('resize', update) }, [])
  useEffect(() => { const media = window.matchMedia?.('(prefers-color-scheme: dark)'); if (!media) return undefined; const update = event => setSystemDark(event.matches); media.addEventListener?.('change', update); return () => media.removeEventListener?.('change', update) }, [])
  useEffect(() => { const update = event => setThemePreference(normalizeDashboardTheme(event.detail)); window.addEventListener('mlbgpt-dashboard-theme-change', update); return () => window.removeEventListener('mlbgpt-dashboard-theme-change', update) }, [])
  const isMobile = width < 760; const isNarrow = width < 1050
  const resolvedTheme = resolveDashboardTheme(themePreference, systemDark); const themeVariables = dashboardThemeVariables(resolvedTheme)
  useEffect(() => { Object.entries(themeVariables).forEach(([key, value]) => document.documentElement.style.setProperty(key, value)); return () => Object.keys(themeVariables).forEach(key => document.documentElement.style.removeProperty(key)) }, [resolvedTheme])
  const [authChecked, setAuthChecked] = useState(false); const [profile, setProfile] = useState(null); const [workspace, setWorkspace] = useState(null); const [workspaceLoading, setWorkspaceLoading] = useState(false); const [workspaceError, setWorkspaceError] = useState('')
  const [form, setForm] = useState({ email: '', username: '', password: '', feature_interests: ['Matchups', 'Model Projections'], wants_newsletter: false }); const [authMode, setAuthMode] = useState('signin'); const [savingProfile, setSavingProfile] = useState(false); const [authError, setAuthError] = useState('')
  const [activeObject, setActiveObject] = useState(persisted.activeObject || 'hitters'); const [reportDate, setReportDate] = useState(persisted.reportDate || mlbDateIso()); const [filters, setFilters] = useState(persisted.filters || Object.fromEntries(OBJECTS.map(object => [object.key, emptyFilters()]))); const [selectedFieldsByObject, setSelectedFieldsByObject] = useState(() => initialFieldsByObject(OBJECTS, persisted)); const [activeLineupsOnly, setActiveLineupsOnly] = useState(Boolean(persisted.activeLineupsOnly)); const [reportTypes, setReportTypes] = useState([])
  const [results, setResults] = useState({}); const [loading, setLoading] = useState({}); const [error, setError] = useState(''); const [saveMessage, setSaveMessage] = useState(''); const [reportOpen, setReportOpen] = useState(false); const [reportObject, setReportObject] = useState('hitters'); const [reportResult, setReportResult] = useState(null); const [reportColumns, setReportColumns] = useState(DEFAULT_FIELDS); const [generatedAt, setGeneratedAt] = useState(null); const [generatedForDate, setGeneratedForDate] = useState(reportDate); const [reportQuery, setReportQuery] = useState(defaultQueryState()); const [savedShelfOpen, setSavedShelfOpen] = useState(true); const [savedShelfView, setSavedShelfView] = useState('daily'); const [selectedShelfEntryKey, setSelectedShelfEntryKey] = useState(''); const [selectedFolderId, setSelectedFolderId] = useState(''); const [newFolderName, setNewFolderName] = useState(''); const [creatingFolder, setCreatingFolder] = useState(false); const [queryStudioRestore, setQueryStudioRestore] = useState(null)
  const selectedFields = selectedFieldsByObject[activeObject] || defaultFieldsForObject(activeObject)
  const setSelectedFields = next => setSelectedFieldsByObject(current => ({ ...current, [activeObject]: typeof next === 'function' ? next(current[activeObject] || defaultFieldsForObject(activeObject)) : next }))
  const activeMeta = OBJECTS.find(object => object.key === activeObject) || OBJECTS[0]; const activeResult = results[activeObject]; const activeReportType = CANONICAL_REPORT_TYPES[activeObject]; const activeCatalog = reportTypes.find(reportType => reportType.api_name === activeReportType); const activeMetadataResult = activeResult || (activeCatalog ? { object_info: activeCatalog } : null); const activeFields = useMemo(() => fieldsForResult(activeMetadataResult, activeObject), [activeMetadataResult, activeObject]); const activeFilters = filters[activeObject] || emptyFilters(); const folderId = Number(selectedFolderId || workspace?.today_folder_id || safeArray(workspace?.folders)[0]?.id)
  useEffect(() => { writeJson(BUILDER_KEY, { activeObject, reportDate, filters, selectedFieldsByObject, activeLineupsOnly }) }, [activeObject, reportDate, filters, selectedFieldsByObject, activeLineupsOnly])
  useEffect(() => { if (!selectedFolderId && workspace?.today_folder_id) setSelectedFolderId(String(workspace.today_folder_id)) }, [workspace?.today_folder_id, selectedFolderId])
  async function apiJson(path, options = {}) { try { return await dashboardApi(path, options) } catch (err) { if (err?.status === 401) setProfile(null); throw err } }
  async function loadWorkspace() { setWorkspaceLoading(true); setWorkspaceError(''); try { const json = await apiJson('/my-dashboard/workspace'); setWorkspace(json); return json } catch (err) { setWorkspaceError(err.message || 'Unable to load saved reports.'); return null } finally { setWorkspaceLoading(false) } }
  async function loadReportTypes() { try { const json = await apiJson('/my-dashboard/report-types'); setReportTypes(safeArray(json.report_types)); return json } catch { setReportTypes([]); return null } }
  async function createReportFolder() { const folderName = newFolderName.trim(); if (!folderName) return; setCreatingFolder(true); setSaveMessage(''); try { const json = await apiJson('/my-dashboard/folders', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ folder_name: folderName, folder_date: null, is_default: false }) }); const createdId = String(json?.folder?.id || ''); setNewFolderName(''); setSavedShelfView('custom'); setSelectedShelfEntryKey(createdId ? `custom:${createdId}` : ''); setSelectedFolderId(createdId); await loadWorkspace(); setSaveMessage(`Created report folder: ${json?.folder?.folder_name || folderName}.`) } catch (err) { setSaveMessage(err.message || 'Failed to create report folder.') } finally { setCreatingFolder(false) } }
  async function renameSaved(kind, id, value) { setSaveMessage(''); try { const request = dashboardRenameRequest(kind, id, value); await apiJson(request.path, request.options); await loadWorkspace(); setSaveMessage(`${kind === 'folder' ? 'Folder' : 'Report'} renamed to ${request.name}.`) } catch (err) { setSaveMessage(err.message || `Failed to rename ${kind}.`); throw err } }
  useEffect(() => { let cancelled = false; (async () => { try { const json = await dashboardApi('/my-dashboard/profile'); if (cancelled) return; if (json.authenticated) { setProfile(json.user); await Promise.all([loadWorkspace(), loadReportTypes()]) } } catch (err) { if (!cancelled && err?.status !== 401) setAuthError('Unable to load dashboard profile.') } finally { if (!cancelled) setAuthChecked(true) } })(); return () => { cancelled = true } }, [])
  async function submitProfile(event) { event.preventDefault(); setSavingProfile(true); setAuthError(''); try { const isRegistration = authMode === 'register'; const endpoint = isRegistration ? '/my-dashboard/auth/register' : '/my-dashboard/auth/login'; const payload = isRegistration ? form : { email: form.email, password: form.password }; const created = await apiJson(endpoint, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) }); setProfile(created.user); await Promise.all([loadWorkspace(), loadReportTypes()]) } catch (err) { setAuthError(err.message || (authMode === 'register' ? 'Failed to create profile' : 'Failed to sign in')) } finally { setSavingProfile(false); setAuthChecked(true) } }
  async function signOut() { await logoutDashboardSession().catch(() => null); setProfile(null); setWorkspace(null); setResults({}); setAuthMode('signin'); setAuthError('') }
  function setBasic(objectKey, key, value) { setFilters(current => ({ ...current, [objectKey]: { ...(current[objectKey] || emptyFilters()), [key]: value } })) }
  function setMetric(objectKey, metric, side, value) { setFilters(current => ({ ...current, [objectKey]: { ...(current[objectKey] || emptyFilters()), metrics: { ...(current[objectKey]?.metrics || {}), [metric]: { ...(current[objectKey]?.metrics?.[metric] || {}), [side]: value } } } })) }
  function setWeight(objectKey, metric, value) { setFilters(current => ({ ...current, [objectKey]: { ...(current[objectKey] || emptyFilters()), weights: { ...(current[objectKey]?.weights || {}), [metric]: value } } })) }
  function selectPrimaryObject(objectKey) { setActiveObject(objectKey); setReportOpen(false); setReportObject(objectKey); setReportResult(results[objectKey] || null); setReportColumns(defaultFieldsForObject(objectKey)); setReportQuery(defaultQueryState()); setError('') }
  async function populateReport(objectKey = activeObject, queryOverride = null, openWorkspace = true) { const query = normalizeQueryState(queryOverride || (objectKey === reportObject ? reportQuery : defaultQueryState())); const cleaned = cleanFilters(filters[objectKey] || {}); const request = buildReportRequest({ objectKey, activeLineupsOnly, date: reportDate, cleanedFilters: cleaned, query }); const reportType = request.reportType; const payload = request.payload; const objectFields = reportFieldsForMode({ objectKey, activeLineupsOnly, selectedFields: selectedFieldsByObject[objectKey] }); setLoading(current => ({ ...current, [objectKey]: true })); setError(''); setSaveMessage(''); try { const raw = await apiJson(request.path, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) }); const json = reportType ? normalizeCanonicalPage(raw, query) : raw; setResults(current => ({ ...current, [objectKey]: json })); setReportObject(objectKey); setReportResult(json); setReportColumns(current => openWorkspace ? [...objectFields] : current); setReportQuery(query); setGeneratedAt(new Date().toISOString()); setGeneratedForDate(reportDate); if (openWorkspace) setReportOpen(true); return json } catch (err) { setError(err.message || 'Report generation failed'); return null } finally { setLoading(current => ({ ...current, [objectKey]: false })) } }
  function openSaved(item) { const payload = item?.payload_json || {}, snapshot = payload.snapshot || {}, definition = payload.definition || {}, board = snapshot.board_state || payload.board_state || payload.report_state || payload, component = definition.component || payload.saved_from_component || item?.sort_json?.component || activeObject, columns = definition.selected_fields || payload.workbench_state?.selectedFields || payload.report_columns || selectedFieldsByObject[component] || defaultFieldsForObject(component), sort = definition.sort || item?.sort_json || defaultQueryState(); if (definition.query_studio_statement) setQueryStudioRestore({ statement: definition.query_studio_statement, restoredAt: Date.now() }); if (!board?.items && !board?.records) { setSaveMessage('This saved item does not contain report rows.'); return } setReportObject(component); setReportResult(board); setReportColumns(columns); setReportQuery(normalizeQueryState({ page_number: board?.page_info?.page_number || 1, page_size: board?.page_info?.page_size || DEFAULT_PAGE_SIZE, sort_by: sort.by || sort.sort_by || 'score', sort_direction: sort.direction || sort.sort_direction || 'desc' })); setGeneratedForDate(snapshot.generated_for_date || payload.saved_on_date || reportDate); setGeneratedAt(snapshot.generated_at || item.created_at || new Date().toISOString()); setReportOpen(true) }
  async function saveReport() { const rows = safeArray(reportResult?.records?.length ? reportResult.records : reportResult?.items); if (!folderId || !rows.length) { setSaveMessage(!folderId ? 'No dashboard folder is available.' : 'Populate a report before saving.'); return } const meta = OBJECTS.find(object => object.key === reportObject) || activeMeta; const definition = { component: reportObject, report_type: CANONICAL_REPORT_TYPES[reportObject] || null, selected_fields: reportColumns, filters: cleanFilters(filters[reportObject] || {}), active_lineups_only: activeLineupsOnly, sort: { by: reportQuery.sort_by, direction: reportQuery.sort_direction }, page_size: reportQuery.page_size }; const snapshot = { generated_for_date: generatedForDate, generated_at: generatedAt, board_state: reportResult }; try { await apiJson('/my-dashboard/items', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ folder_id: folderId, source_tab: 'my-dashboard', source_type: 'report_view', title: `${meta.label} Report | ${generatedForDate}`, subtitle: meta.description, notes: 'Saved from the MLBGPT Report Workspace.', payload_json: { schema_version: 3, definition, snapshot, saved_from_component: reportObject, saved_on_date: generatedForDate, board_state: reportResult, report_columns: reportColumns, workbench_state: { selectedFields: reportColumns, activeLineupsOnly } }, filter_json: definition.filters, sort_json: { ...definition.sort, component: reportObject, report_workspace: true } }) }); await loadWorkspace(); setSaveMessage(`Saved ${meta.label} report.`) } catch (err) { setSaveMessage(err.message || 'Failed to save report.') } }
  if (!authChecked) return <div data-dashboard-theme={resolvedTheme} style={{ ...themeVariables, ...s.loadingPage }}>Loading Report Builder…</div>
  if (!profile) return <main data-dashboard-theme={resolvedTheme} style={{ ...themeVariables, ...s.authPage, gridTemplateColumns: isNarrow ? '1fr' : 'minmax(0,1.08fr) minmax(400px,.92fr)' }}>
    <div aria-hidden="true" style={s.chromeRibbon} />
    <section style={s.authStory}>
      <div style={s.brand}>MLB<span style={{ color: C.blue }}>GPT</span></div>
      <div style={s.eyebrow}>Private reporting workspace</div>
      <h1 style={s.authHeadline}>AI-powered MLB intelligence.<br /><span style={{ color: C.blue }}>Smarter analysis.</span></h1>
      <p style={s.authLead}>Build detailed reports from MLBGPT’s registered baseball objects, save your work, and return to the same analytical state later.</p>
      <div style={s.authFeatureGrid}>{[
        ['Custom Reports', 'Choose registered objects, fields, filters, weights, and dates.'],
        ['Saved Workspace', 'Organize report snapshots in daily, weekly, monthly, and personal folders.'],
        ['Protected Query Studio', 'Authorized owners can prompt the same report registry with a constrained language.'],
      ].map(([title, detail]) => <div style={s.authFeature} key={title}><span>◇</span><div><strong>{title}</strong><small>{detail}</small></div></div>)}</div>
    </section>
    <section style={s.authCard}>
      <ThemePicker />
      <div style={s.eyebrow}>{authMode === 'register' ? 'New analyst profile' : 'Welcome back'}</div>
      <h2 style={s.authTitle}>{authMode === 'register' ? 'Create your MLBGPT account' : 'Sign in to MyDashboard'}</h2>
      <p style={s.copy}>{authMode === 'register' ? 'Create a password-backed profile to save and reopen your reports.' : 'Use the password associated with your analyst profile.'}</p>
      <div style={s.authTabs}>
        <button type="button" style={authMode === 'signin' ? s.authTabActive : s.authTab} onClick={() => { setAuthMode('signin'); setAuthError('') }}>Sign In</button>
        <button type="button" style={authMode === 'register' ? s.authTabActive : s.authTab} onClick={() => { setAuthMode('register'); setAuthError('') }}>Create Account</button>
      </div>
      <form onSubmit={submitProfile} style={s.stack}>
        <label style={s.authLabel}>Email<input required style={s.input} type="email" autoComplete="email" placeholder="you@example.com" value={form.email} onChange={e => setForm(v => ({ ...v, email: e.target.value }))} /></label>
        {authMode === 'register' ? <label style={s.authLabel}>Username<input required style={s.input} autoComplete="username" placeholder="Analyst name" value={form.username} onChange={e => setForm(v => ({ ...v, username: e.target.value }))} /></label> : null}
        <label style={s.authLabel}>Password<input required minLength={authMode === 'register' ? 8 : 1} maxLength={256} style={s.input} type="password" autoComplete={authMode === 'register' ? 'new-password' : 'current-password'} placeholder={authMode === 'register' ? '8 or more characters' : 'Enter your password'} value={form.password} onChange={e => setForm(v => ({ ...v, password: e.target.value }))} /></label>
        {authError ? <div style={s.error}>{authError}</div> : null}
        <button style={s.authPrimary} disabled={savingProfile}>{savingProfile ? (authMode === 'register' ? 'Creating…' : 'Signing in…') : (authMode === 'register' ? 'Create Account' : 'Enter Report Builder →')}</button>
      </form>
      <p style={s.authTruth}>Password-backed sessions use the current verified MyDashboard security contract.</p>
    </section>
  </main>
  const reportMeta = OBJECTS.find(object => object.key === reportObject) || activeMeta; const reportFields = fieldsForResult(reportResult, reportObject)
  return <main style={s.page}><section style={s.hero}><div><div style={s.brandSmall}>MLB<span>GPT</span></div><div style={s.eyebrow}>Private report workspace</div><h1 style={s.title}>Build your report.</h1><p style={s.copy}>Choose an MLB date, report type, fields, and filters. Sorting and pagination apply to every matching result.</p><div style={s.pillRow}><Pill>Signed in: {profile.username}</Pill><Pill tone="green">MLB date: {reportDate}</Pill></div></div><div style={s.actions}>{hasDashboardCapability(profile, 'admin.portal.access') ? <a style={s.adminLink} href="/admin">Control Center</a> : null}<button style={s.secondary} onClick={signOut}>Sign Out</button><label>MLB date<input type="date" style={s.input} value={reportDate} onChange={e => setReportDate(e.target.value || mlbDateIso())} /></label><button style={s.primary} disabled={loading[activeObject]} onClick={() => populateReport(activeObject, defaultQueryState())}>{loading[activeObject] ? 'Populating…' : 'Populate Report'}</button></div></section>{saveMessage ? <div style={saveMessage.startsWith('Failed') || saveMessage.startsWith('No ') || saveMessage.startsWith('This ') || saveMessage.startsWith('Name ') || saveMessage.startsWith('Choose ') || saveMessage.startsWith('Run ') ? s.error : s.success}>{saveMessage}</div> : null}{error ? <StatePanel tone="error" title="Report could not be generated">{error}</StatePanel> : null}<div style={{ ...s.builderShell, ...(isNarrow ? s.builderShellNarrow : {}) }}><aside style={{ ...s.objectManager, ...(isMobile ? { position: 'static' } : {}) }}><div style={s.panelTitle}>Report Types</div>{OBJECTS.map(object => <button key={object.key} style={activeObject === object.key ? s.objectActive : s.objectButton} onClick={() => selectPrimaryObject(object.key)}><span><strong>{object.label}</strong><small>{object.description}</small></span><b>{results[object.key]?.totalSize ?? safeArray(results[object.key]?.items).length}</b></button>)}</aside><div style={s.mainStack}><section style={s.card}><div style={s.cardHeader}><div><div style={s.panelTitle}>{activeMeta.label}</div><div style={s.copySmall}>{activeMeta.description}</div></div><label><input type="checkbox" checked={activeLineupsOnly} disabled={!ACTIVE_LINEUP_OBJECTS.has(activeObject)} onChange={e => setActiveLineupsOnly(e.target.checked)} /> Confirmed 1–9 only</label></div></section><div style={{ ...s.builderColumns, ...(isNarrow ? s.builderColumnsNarrow : {}) }}><div style={s.stack}><FilterPanel objectKey={activeObject} filters={activeFilters} fields={activeFields} setBasic={setBasic} setMetric={setMetric} setWeight={setWeight} /><FieldLibrary fields={activeFields} selected={selectedFields} setSelected={setSelectedFields} /></div><div style={s.stack}>{hasDashboardCapability(profile, 'workbench.advanced') ? <QueryStudioPanel folderId={folderId} refreshWorkspace={loadWorkspace} restore={queryStudioRestore} onMessage={setSaveMessage} /> : null}<section style={s.card}><div style={s.panelTitle}>Report Preview</div><div style={s.previewStats}><Pill>{selectedFields.length} columns</Pill><Pill tone="green">{Object.keys(cleanFilters(activeFilters)).length} active filter groups</Pill></div><button style={s.populateWide} disabled={loading[activeObject]} onClick={() => populateReport(activeObject, defaultQueryState())}>{loading[activeObject] ? 'Populating Report…' : 'Populate Report'}</button>{activeResult ? <button style={s.secondaryWide} onClick={() => { setReportObject(activeObject); setReportResult(activeResult); setReportColumns([...selectedFields]); setReportQuery(normalizeQueryState(activeResult.query || defaultQueryState())); setGeneratedForDate(reportDate); setGeneratedAt(new Date().toISOString()); setReportOpen(true) }}>Open Last Report</button> : <StatePanel title="No report generated yet">Choose fields and filters, then populate the report.</StatePanel>}</section></div></div><SavedReportsShelfV2 workspace={workspace} loading={workspaceLoading} error={workspaceError} openSaved={openSaved} refresh={loadWorkspace} renameSaved={renameSaved} open={savedShelfOpen} setOpen={setSavedShelfOpen} view={savedShelfView} setView={setSavedShelfView} selectedEntryKey={selectedShelfEntryKey} setSelectedEntryKey={setSelectedShelfEntryKey} selectedFolderId={selectedFolderId} setSelectedFolderId={setSelectedFolderId} newFolderName={newFolderName} setNewFolderName={setNewFolderName} createFolder={createReportFolder} creatingFolder={creatingFolder} /></div></div><ReportWorkspace open={reportOpen} close={() => setReportOpen(false)} objectMeta={reportMeta} result={reportResult} fields={reportFields} builderFields={selectedFields} initialColumns={reportColumns} generatedAt={generatedAt} reportDate={generatedForDate} query={reportQuery} setQuery={setReportQuery} reload={next => populateReport(reportObject, next, false)} loading={loading[reportObject]} onSave={saveReport} isMobile={isMobile} /></main>
}

export default function MyDashboardReportBuilderPage() {
  return <DashboardWorkspaceErrorBoundary><MyDashboardReportBuilderContent /></DashboardWorkspaceErrorBoundary>
}

const s = {
  crashPage: { minHeight: '100vh', display: 'grid', placeItems: 'center', padding: 24, color: '#edf2fb', background: '#07111f', boxSizing: 'border-box', fontFamily: CENTURY },
  crashCard: { width: 'min(100%,620px)', padding: 'clamp(24px,5vw,48px)', background: '#111d2d', border: '1px solid #33445a', borderRadius: 24, boxShadow: '0 24px 70px rgba(0,0,0,.38)' },
  crashTitle: { margin: '8px 0 12px', fontFamily: FRANKLIN, fontSize: 'clamp(28px,5vw,44px)', fontWeight: 500, lineHeight: 1.05 },
  crashCopy: { margin: '0 0 22px', color: '#b9c5d6', fontSize: 14, lineHeight: 1.6 },
  page: { minHeight: '100vh', padding: 'clamp(12px,2.5vw,28px)', color: C.text, colorScheme: 'var(--md-color-scheme)', background: 'var(--md-page-bg)', boxSizing: 'border-box', fontFamily: CENTURY, fontSize: 13, lineHeight: 1.42, transition: 'color .2s ease,background .2s ease' },
  loadingPage: { minHeight: '100vh', display: 'grid', placeItems: 'center', color: C.text, colorScheme: 'var(--md-color-scheme)', background: 'var(--md-page-bg)', fontFamily: CENTURY },
  authPage: { position: 'relative', minHeight: '100vh', display: 'grid', alignItems: 'center', gap: 'clamp(24px,5vw,84px)', padding: 'clamp(22px,5vw,74px)', overflow: 'hidden', color: C.text, colorScheme: 'var(--md-color-scheme)', background: 'var(--md-auth-bg)', boxSizing: 'border-box', fontFamily: CENTURY, transition: 'color .2s ease,background .2s ease' },
  chromeRibbon: { position: 'absolute', width: 'min(78vw,1100px)', height: 'min(78vw,1100px)', left: '20%', top: '-32%', transform: 'rotate(34deg)', opacity: .72, borderRadius: '42% 58% 48% 52%', background: 'var(--md-chrome)', filter: 'blur(2px)', pointerEvents: 'none' },
  authStory: { position: 'relative', zIndex: 1, display: 'grid', alignContent: 'center', gap: 18, maxWidth: 690, padding: 'clamp(8px,2vw,28px)' },
  brand: { fontFamily: FRANKLIN, fontSize: 30, fontWeight: 700, letterSpacing: '-.04em' },
  brandSmall: { marginBottom: 12, fontFamily: FRANKLIN, fontSize: 19, fontWeight: 700, letterSpacing: '-.04em' },
  authHeadline: { margin: '10px 0 0', fontFamily: FRANKLIN, fontSize: 'clamp(40px,6vw,76px)', fontWeight: 400, lineHeight: .98, letterSpacing: '-.045em' },
  authLead: { maxWidth: 590, margin: 0, color: C.muted, fontSize: 'clamp(14px,1.5vw,18px)', lineHeight: 1.65 },
  authFeatureGrid: { display: 'grid', gap: 9, maxWidth: 620 },
  authFeature: { display: 'grid', gridTemplateColumns: '38px minmax(0,1fr)', gap: 10, alignItems: 'center', padding: 10, background: C.panel, border: '1px solid var(--md-glass-border)', borderRadius: 14, backdropFilter: 'blur(14px)' },
  authCard: { position: 'relative', zIndex: 2, width: '100%', maxWidth: 560, justifySelf: 'center', boxSizing: 'border-box', padding: 'clamp(22px,4vw,46px)', borderRadius: 34, border: '1px solid var(--md-glass-border)', background: 'var(--md-glass)', boxShadow: 'var(--md-inset),var(--md-shadow)', backdropFilter: 'blur(28px)' },
  authTitle: { margin: '6px 0', fontFamily: FRANKLIN, fontSize: 'clamp(28px,4vw,42px)', fontWeight: 400, letterSpacing: '-.035em' },
  authLabel: { display: 'grid', gap: 6, color: 'var(--md-label)', fontFamily: FRANKLIN, fontSize: 12 },
  authTruth: { margin: '16px 0 0', color: C.muted, textAlign: 'center', fontSize: 11, lineHeight: 1.5 },
  authPrimary: { width: '100%', padding: '13px 18px', color: '#fff', fontFamily: FRANKLIN, fontSize: 14, background: 'linear-gradient(105deg,#1d2027,#6f63f5 76%,#d5d3ff)', border: '1px solid rgba(255,255,255,.75)', borderRadius: 999, boxShadow: '0 10px 30px rgba(91,75,220,.24)' },
  authTabs: { display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 7, margin: '18px 0 14px', padding: 4, background: C.panel2, borderRadius: 999 },
  authTab: { padding: '9px 12px', color: C.muted, fontFamily: FRANKLIN, fontSize: 12, background: 'transparent', border: 0, borderRadius: 999 },
  authTabActive: { padding: '9px 12px', color: '#fff', fontFamily: FRANKLIN, fontSize: 12, background: 'linear-gradient(105deg,#22252c,#776df5)', border: '1px solid rgba(255,255,255,.52)', borderRadius: 999 },
  hero: { display: 'flex', justifyContent: 'space-between', gap: 16, flexWrap: 'wrap', padding: 20, marginBottom: 14, borderRadius: 24, border: '1px solid var(--md-glass-border)', background: 'var(--md-glass-strong)', boxShadow: 'var(--md-inset),var(--md-shadow)', backdropFilter: 'blur(18px)' },
  title: { margin: '7px 0', fontFamily: FRANKLIN, fontSize: 'clamp(28px,4vw,42px)', fontWeight: 500, lineHeight: 1.04, letterSpacing: '-.03em' }, eyebrow: { color: C.blue, fontFamily: FRANKLIN, fontSize: 10, fontWeight: 500, letterSpacing: '.12em', textTransform: 'uppercase' }, copy: { color: C.muted, maxWidth: 720, fontSize: 13, lineHeight: 1.55 }, copySmall: { color: C.muted, fontSize: 11, lineHeight: 1.42 }, actions: { display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'end' }, adminLink: { display: 'inline-flex', alignItems: 'center', padding: '9px 12px', color: C.blue, fontFamily: FRANKLIN, fontSize: 12, textDecoration: 'none', background: 'rgba(112,100,245,.09)', border: '1px solid rgba(112,100,245,.3)', borderRadius: 999 }, stack: { display: 'grid', gap: 12 }, builderShell: { display: 'grid', gridTemplateColumns: '235px minmax(0,1fr)', gap: 14 }, builderShellNarrow: { gridTemplateColumns: '1fr' }, builderColumns: { display: 'grid', gridTemplateColumns: 'minmax(0,1.12fr) minmax(340px,.88fr)', gap: 12 }, builderColumnsNarrow: { gridTemplateColumns: '1fr' }, mainStack: { display: 'grid', gap: 12, minWidth: 0 }, objectManager: { position: 'sticky', top: 14, display: 'grid', alignContent: 'start', gap: 7, padding: 14, borderRadius: 20, border: '1px solid var(--md-glass-border)', background: 'var(--md-glass-strong)', boxShadow: 'var(--md-inset),var(--md-shadow)' }, objectButton: { display: 'flex', justifyContent: 'space-between', gap: 9, padding: 10, textAlign: 'left', color: C.text, fontFamily: FRANKLIN, fontSize: 12, background: C.panel2, border: `1px solid ${C.border}`, borderRadius: 11 }, objectActive: { display: 'flex', justifyContent: 'space-between', gap: 9, padding: 10, textAlign: 'left', color: '#fff', fontFamily: FRANKLIN, fontSize: 12, background: 'linear-gradient(105deg,#272a32,#776df5)', border: '1px solid rgba(255,255,255,.55)', borderRadius: 11, boxShadow: '0 8px 20px rgba(86,72,206,.18)' }, card: { padding: 14, borderRadius: 20, border: '1px solid var(--md-glass-border)', background: C.panel, boxShadow: 'var(--md-inset),var(--md-shadow)', backdropFilter: 'blur(16px)' }, cardHeader: { display: 'flex', justifyContent: 'space-between', gap: 10, flexWrap: 'wrap' }, panelTitle: { fontFamily: FRANKLIN, fontSize: 16, fontWeight: 500, letterSpacing: '.01em' }, input: { width: '100%', boxSizing: 'border-box', padding: '9px 11px', color: C.text, colorScheme: 'var(--md-color-scheme)', fontFamily: CENTURY, fontSize: 12, background: 'var(--md-control)', border: `1px solid ${C.border}`, borderRadius: 10 }, miniInput: { width: '100%', boxSizing: 'border-box', padding: 7, color: C.text, colorScheme: 'var(--md-color-scheme)', fontFamily: CENTURY, fontSize: 11, background: 'var(--md-control)', border: `1px solid ${C.border}`, borderRadius: 8 }, filterGrid: { display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(150px,1fr))', gap: 7, marginTop: 10 }, metricGrid: { display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(145px,1fr))', gap: 7 }, metricCard: { display: 'grid', gap: 6, padding: 9, color: C.muted, fontSize: 11, background: C.panel2, border: `1px solid ${C.border}`, borderRadius: 10 }, twoCol: { display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 6 }, sectionLabel: { margin: '12px 0 7px', color: C.muted, fontFamily: FRANKLIN, fontSize: 9, fontWeight: 500, letterSpacing: '.1em', textTransform: 'uppercase' }, fieldGroups: { maxHeight: 520, overflowY: 'auto' }, fieldGrid: { display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(135px,1fr))', gap: 6 }, fieldButton: { display: 'grid', padding: 8, textAlign: 'left', color: C.text, fontFamily: CENTURY, fontSize: 11, background: C.panel2, border: `1px solid ${C.border}`, borderRadius: 9 }, fieldActive: { display: 'grid', padding: 8, textAlign: 'left', color: C.text, fontFamily: CENTURY, fontSize: 11, background: 'rgba(112,100,245,.16)', border: '1px solid rgba(112,100,245,.44)', borderRadius: 9 }, primary: { padding: '10px 14px', color: '#fff', fontFamily: FRANKLIN, fontSize: 12, fontWeight: 500, background: 'linear-gradient(105deg,#24262d,#776df5)', border: '1px solid rgba(255,255,255,.52)', borderRadius: 999, boxShadow: '0 8px 20px rgba(86,72,206,.15)' }, secondary: { padding: '9px 12px', color: C.text, fontFamily: FRANKLIN, fontSize: 11, fontWeight: 500, background: 'var(--md-control-soft)', border: `1px solid ${C.border}`, borderRadius: 999 }, secondaryWide: { width: '100%', padding: 10, color: C.text, fontFamily: FRANKLIN, fontSize: 11, background: 'var(--md-control-soft)', border: `1px solid ${C.border}`, borderRadius: 999 }, populateWide: { width: '100%', padding: 12, color: '#fff', fontFamily: FRANKLIN, fontSize: 12, fontWeight: 500, background: 'linear-gradient(105deg,#24262d,#776df5 78%,#d4d1ff)', border: '1px solid rgba(255,255,255,.6)', borderRadius: 999, boxShadow: '0 9px 24px rgba(86,72,206,.18)' }, pillRow: { display: 'flex', gap: 7, flexWrap: 'wrap' }, pill: { display: 'inline-flex', padding: '5px 9px', border: '1px solid', borderRadius: 999, fontFamily: FRANKLIN, fontSize: 10, fontWeight: 500 }, previewStats: { display: 'flex', gap: 7, flexWrap: 'wrap', margin: '10px 0' }, empty: { display: 'grid', gap: 7, padding: 12, color: C.muted, fontSize: 11, border: `1px dashed ${C.border}`, borderRadius: 10, background: C.panel2 }, loadingState: { padding: 12, color: C.blue, fontSize: 11, border: '1px solid rgba(112,100,245,.3)', borderRadius: 10, background: 'rgba(112,100,245,.08)' }, errorState: { padding: 12, color: C.red, fontSize: 11, border: '1px solid rgba(196,74,86,.3)', borderRadius: 10, background: 'rgba(196,74,86,.08)' }, success: { marginBottom: 12, padding: 10, color: C.green, fontSize: 11, background: 'rgba(22,143,106,.1)', borderRadius: 10 }, error: { marginBottom: 12, padding: 10, color: C.red, fontSize: 11, background: 'rgba(196,74,86,.1)', borderRadius: 10 }, warning: { padding: 10, color: C.amber, fontSize: 11, background: 'rgba(185,120,22,.1)', borderRadius: 10 }, shelfSummary: { display: 'flex', gap: 7, flexWrap: 'wrap', margin: '10px 0' }, shelfTabs: { display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(130px,1fr))', gap: 7, marginBottom: 10 }, shelfTab: { display: 'flex', justifyContent: 'space-between', gap: 7, padding: 9, color: C.text, fontFamily: FRANKLIN, fontSize: 11, background: C.panel2, border: `1px solid ${C.border}`, borderRadius: 9 }, shelfTabActive: { display: 'flex', justifyContent: 'space-between', gap: 7, padding: 9, color: '#fff', fontFamily: FRANKLIN, fontSize: 11, background: 'linear-gradient(105deg,#2b2e36,#776df5)', border: '1px solid rgba(255,255,255,.5)', borderRadius: 9 }, newFolderRow: { display: 'grid', gridTemplateColumns: 'minmax(180px,1fr) auto', gap: 7, marginBottom: 10 }, shelfGrid: { display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(260px,1fr))', gap: 10 }, folderList: { display: 'grid', alignContent: 'start', gap: 7, maxHeight: 410, overflowY: 'auto' }, folderButton: { display: 'flex', justifyContent: 'space-between', gap: 9, padding: 10, textAlign: 'left', color: C.text, background: C.panel2, border: `1px solid ${C.border}`, borderRadius: 9 }, folderButtonActive: { display: 'flex', justifyContent: 'space-between', gap: 9, padding: 10, textAlign: 'left', color: C.text, background: 'rgba(22,143,106,.08)', border: '1px solid rgba(22,143,106,.3)', borderRadius: 9 }, folderDetail: { minHeight: 170, padding: 11, background: C.panel2, border: `1px solid ${C.border}`, borderRadius: 10 }, folderDetailHeader: { display: 'flex', justifyContent: 'space-between', gap: 9, alignItems: 'center', marginBottom: 9 }, savedList: { display: 'grid', gap: 7, maxHeight: 350, overflowY: 'auto' }, savedItem: { display: 'flex', justifyContent: 'space-between', gap: 9, padding: 10, textAlign: 'left', color: C.text, background: C.panel, border: `1px solid ${C.border}`, borderRadius: 10 }, overlay: { position: 'fixed', inset: 0, zIndex: 1000, padding: 10, background: 'rgba(5,7,12,.92)' }, reportSurface: { height: '100%', display: 'grid', gridTemplateRows: 'auto minmax(0,1fr)', overflow: 'hidden', color: C.text, colorScheme: 'var(--md-color-scheme)', fontFamily: CENTURY, fontSize: 11, background: 'var(--md-report-bg)', borderRadius: 18 }, reportHeader: { display: 'flex', justifyContent: 'space-between', gap: 14, flexWrap: 'wrap', padding: 15, borderBottom: `1px solid ${C.border}` }, reportTitle: { margin: '4px 0', fontFamily: FRANKLIN, fontSize: 23, fontWeight: 500 }, reportBody: { minHeight: 0, display: 'grid', gridTemplateColumns: '255px minmax(0,1fr)' }, reportBodyMobile: { gridTemplateColumns: '1fr', overflowY: 'auto' }, columnPanel: { minHeight: 0, padding: 12, overflowY: 'auto', borderRight: `1px solid ${C.border}` }, columnList: { display: 'grid', gap: 5, margin: '10px 0' }, columnRow: { display: 'flex', justifyContent: 'space-between', gap: 7, padding: 7, background: C.panel2, borderRadius: 7 }, iconButton: { padding: '3px 7px', color: C.text, fontFamily: FRANKLIN, background: 'transparent', border: `1px solid ${C.border}`, borderRadius: 6 }, gridPanel: { minWidth: 0, minHeight: 0, display: 'grid', gridTemplateRows: 'auto minmax(0,1fr) auto', gap: 8, padding: 12 }, gridToolbar: { display: 'flex', justifyContent: 'space-between', gap: 8, flexWrap: 'wrap' }, pageSize: { display: 'flex', gap: 7, alignItems: 'center', color: C.muted }, dataGridWrap: { minHeight: 0, overflow: 'auto', border: `1px solid ${C.border}`, borderRadius: 9 }, table: { width: '100%', borderCollapse: 'collapse', minWidth: 760, fontFamily: CENTURY, fontSize: 11 }, th: { position: 'sticky', top: 0, padding: '7px 8px', textAlign: 'left', background: 'var(--md-table-head)', borderBottom: `1px solid ${C.border}` }, td: { padding: '6px 8px', borderBottom: `1px solid ${C.border}`, whiteSpace: 'nowrap' }, sortButton: { color: C.text, fontFamily: FRANKLIN, fontSize: 10, background: 'transparent', border: 0, fontWeight: 500 }, pagination: { display: 'flex', justifyContent: 'center', gap: 10, alignItems: 'center', fontFamily: FRANKLIN },
  themePicker: { position: 'relative', zIndex: 3, display: 'grid', gridTemplateColumns: 'repeat(3,minmax(0,1fr))', gap: 4, width: 'min(100%,300px)', marginBottom: 10, padding: 4, color: C.text, background: C.panel2, border: `1px solid ${C.border}`, borderRadius: 999, boxSizing: 'border-box' },
  themeOption: { minWidth: 0, padding: '7px 8px', color: C.muted, fontFamily: FRANKLIN, fontSize: 10, background: 'transparent', border: 0, borderRadius: 999 },
  themeOptionActive: { minWidth: 0, padding: '7px 8px', color: '#fff', fontFamily: FRANKLIN, fontSize: 10, background: 'linear-gradient(105deg,#252831,#776df5)', border: '1px solid rgba(255,255,255,.34)', borderRadius: 999 },
  renameEditor: { display: 'grid', gap: 7, padding: 9, background: C.panel2, border: '1px solid rgba(96,165,250,.5)', borderRadius: 9 },
  renameInput: { width: '100%', boxSizing: 'border-box', padding: '8px 10px', color: C.text, fontFamily: CENTURY, fontSize: 12, background: C.panel, border: `1px solid ${C.border}`, borderRadius: 8 },
  renameActions: { display: 'flex', justifyContent: 'flex-end', gap: 6 },
  smallPrimary: { padding: '6px 9px', color: C.text, fontFamily: FRANKLIN, fontSize: 11, background: 'rgba(96,165,250,.22)', border: '1px solid rgba(96,165,250,.5)', borderRadius: 7 },
  smallSecondary: { padding: '6px 9px', color: C.text, fontFamily: FRANKLIN, fontSize: 11, background: C.panel, border: `1px solid ${C.border}`, borderRadius: 7 },
  folderRow: { display: 'grid', gridTemplateColumns: 'minmax(0,1fr) auto', gap: 6, alignItems: 'stretch', background: C.panel2, border: `1px solid ${C.border}`, borderRadius: 9 },
  folderRowActive: { display: 'grid', gridTemplateColumns: 'minmax(0,1fr) auto', gap: 6, alignItems: 'stretch', background: 'rgba(52,211,153,.12)', border: '1px solid rgba(52,211,153,.42)', borderRadius: 9 },
  folderSelect: { minWidth: 0, display: 'flex', justifyContent: 'space-between', gap: 9, padding: 10, textAlign: 'left', color: C.text, fontFamily: CENTURY, fontSize: 12, background: 'transparent', border: 0 },
  savedItemRow: { display: 'grid', gridTemplateColumns: 'minmax(0,1fr) auto', gap: 6, alignItems: 'stretch', background: C.panel, border: `1px solid ${C.border}`, borderRadius: 10 },
  savedItemOpen: { minWidth: 0, display: 'flex', justifyContent: 'space-between', gap: 9, padding: 10, textAlign: 'left', color: C.text, fontFamily: CENTURY, fontSize: 12, background: 'transparent', border: 0 },
  editButton: { alignSelf: 'center', marginRight: 7, padding: '6px 8px', color: C.blue, fontFamily: FRANKLIN, fontSize: 11, background: 'transparent', border: '1px solid rgba(96,165,250,.32)', borderRadius: 7 },
}

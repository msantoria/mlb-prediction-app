import React, { useEffect, useMemo, useRef, useState } from 'react'

import { buildReportCsv, collectPaginatedRows, safeFilenamePart } from '../lib/dashboardReportUtils.mjs'
import {
  QUERY_STUDIO_EXAMPLE,
  queryStudioColumns,
  queryStudioExampleForObject,
  queryStudioObjects,
  queryStudioRows,
  queryStudioSavePayload,
} from '../lib/dashboardQueryStudioState.mjs'
import { dashboardApi } from '../lib/dashboardSession.mjs'

const FRANKLIN = '"Franklin Gothic Medium", "Franklin Gothic", "Arial Narrow", Arial, sans-serif'
const CENTURY = '"Century Gothic", CenturyGothic, AppleGothic, Arial, sans-serif'

function display(value) {
  if (value == null || value === '') return '—'
  if (typeof value === 'number') return Math.abs(value) >= 10 ? value.toFixed(1) : value.toFixed(3)
  if (typeof value === 'boolean') return value ? 'Yes' : 'No'
  return typeof value === 'object' ? JSON.stringify(value) : String(value)
}

function download(filename, contents) {
  const blob = new Blob([contents], { type: 'text/csv;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = filename
  document.body.appendChild(link)
  link.click()
  link.remove()
  URL.revokeObjectURL(url)
}

export default function QueryStudioPanel({
  folderId,
  refreshWorkspace,
  restore,
  onMessage,
  preferredObject,
}) {
  const [metadata, setMetadata] = useState(null)
  const [metadataState, setMetadataState] = useState('loading')
  const [metadataMessage, setMetadataMessage] = useState('')
  const [statement, setStatement] = useState(QUERY_STUDIO_EXAMPLE)
  const automaticStatement = useRef(QUERY_STUDIO_EXAMPLE)
  const [preview, setPreview] = useState(null)
  const [result, setResult] = useState(null)
  const [executedStatement, setExecutedStatement] = useState('')
  const [running, setRunning] = useState(false)
  const [exporting, setExporting] = useState(false)
  const [error, setError] = useState('')
  const [pageNumber, setPageNumber] = useState(1)

  useEffect(() => {
    let cancelled = false
    dashboardApi('/my-dashboard/query-studio/metadata')
      .then(json => {
        if (cancelled) return
        setMetadata(json)
        setMetadataState('ready')
      })
      .catch(err => {
        if (cancelled) return
        setMetadataState(err?.status === 403 ? 'locked' : 'error')
        setMetadataMessage(err.message || 'Query Studio metadata is unavailable.')
      })
    return () => { cancelled = true }
  }, [])

  useEffect(() => {
    const next = restore?.statement
    if (!next) return
    automaticStatement.current = null
    setStatement(next)
    setPreview(null)
    setResult(null)
    setExecutedStatement('')
    setPageNumber(1)
  }, [restore])

  const rows = queryStudioRows(result)
  const columns = queryStudioColumns(result)
  const objects = useMemo(() => queryStudioObjects(metadata), [metadata])
  const fieldLabels = useMemo(() => {
    const map = {}
    objects.forEach(object => object.fields.forEach(field => { map[field.name] = field.label || field.name }))
    return map
  }, [objects])
  const pageInfo = result?.page_info || {}

  useEffect(() => {
    const object = objects.find(item => item.api_name === preferredObject)
    if (!object) return
    const next = queryStudioExampleForObject(object)
    setStatement(current => {
      if (current !== automaticStatement.current) return current
      automaticStatement.current = next
      return next
    })
    setPreview(null)
    setResult(null)
    setExecutedStatement('')
    setPageNumber(1)
  }, [objects, preferredObject])

  async function request(path, nextPage = 1) {
    setRunning(true)
    setError('')
    const submittedStatement = statement
    try {
      const json = await dashboardApi(path, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ statement: submittedStatement, page_number: nextPage }),
      })
      if (path.endsWith('/preview')) setPreview(json.plan)
      else {
        setResult(json)
        setPreview(json.workbench_plan)
        setExecutedStatement(submittedStatement)
        setPageNumber(nextPage)
      }
    } catch (err) {
      setError(err.message || 'Query Studio request failed.')
    } finally {
      setRunning(false)
    }
  }

  async function save() {
    if (!folderId) {
      onMessage('Choose a physical saved-report folder before saving this query.')
      return
    }
    if (!rows.length) {
      onMessage('Run Query Studio before saving.')
      return
    }
    const label = metadata?.objects?.find(item => item.api_name === result?.report_type)?.label || 'Query Studio'
    const payload = queryStudioSavePayload({
      folderId,
      statement: executedStatement || statement,
      result,
      title: `${label} Query`,
    })
    try {
      await dashboardApi('/my-dashboard/items', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      })
      await refreshWorkspace()
      onMessage(`Saved ${label} query.`)
    } catch (err) {
      onMessage(err.message || 'Failed to save Query Studio result.')
    }
  }

  async function exportCsv() {
    if (!rows.length || !columns.length || exporting) return
    setExporting(true)
    setError('')
    try {
      const exportStatement = executedStatement || statement
      const exportRows = await collectPaginatedRows(page => dashboardApi('/my-dashboard/query-studio/execute', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ statement: exportStatement, page_number: page }),
      }))
      const fieldMap = Object.fromEntries(columns.map(accessor => [accessor, { accessor, label: fieldLabels[accessor] || accessor }]))
      const csv = buildReportCsv({ columns, rows: exportRows, fieldMap, getValue: (row, accessor) => row?.[accessor] })
      download(`${safeFilenamePart(result?.report_type || 'query-studio')}-all-rows.csv`, csv)
    } catch (err) {
      setError(err.message || 'Unable to export every Query Studio row.')
    } finally {
      setExporting(false)
    }
  }

  if (metadataState === 'loading') return <section style={s.panel}><div style={s.eyebrow}>Owner Query Studio</div><p style={s.muted}>Loading the registered query language…</p></section>
  if (metadataState === 'locked') return <section style={s.panel}><div style={s.row}><div><div style={s.eyebrow}>Owner Query Studio</div><h3 style={s.title}>Intentionally locked</h3></div><span style={s.lockBadge}>Feature off</span></div><p style={s.muted}>{metadataMessage}</p><p style={s.note}>Enable <code>workbench_query_enabled</code> for Owner Administrator in the private Control Center. The flag does not grant access by itself.</p></section>
  if (metadataState === 'error') return <section style={s.panel}><div style={s.eyebrow}>Owner Query Studio</div><h3 style={s.title}>Studio unavailable</h3><p style={s.error}>{metadataMessage}</p></section>

  return <section style={s.panel}>
    <div style={s.row}><div><div style={s.eyebrow}>Owner Query Studio</div><h3 style={s.title}>Prompt the report registry</h3><p style={s.muted}>SELECT-only MLBGPT language. Your statement becomes a validated report plan; authored SQL never reaches the database.</p></div><span style={s.readyBadge}>Protected</span></div>
    <div style={s.objectStrip}>{objects.map(object => <button type="button" key={object.api_name} style={s.objectChip} title={`Use ${object.label || object.api_name}`} onClick={() => { const next = queryStudioExampleForObject(object); automaticStatement.current = next; setStatement(next); setPreview(null); setResult(null); setPageNumber(1) }}>{object.label || object.api_name}<small>{object.fields.length} fields</small></button>)}</div>
    <label style={s.label}>MLBGPT statement<textarea aria-label="Query Studio statement" spellCheck="false" style={s.editor} value={statement} onChange={event => { automaticStatement.current = null; setStatement(event.target.value) }} onKeyDown={event => { if ((event.metaKey || event.ctrlKey) && event.key === 'Enter') { event.preventDefault(); request('/my-dashboard/query-studio/execute', 1) } }} /></label>
    {error ? <div style={s.error}>{error}</div> : null}
    <div style={s.actions}><button style={s.secondary} disabled={running} onClick={() => request('/my-dashboard/query-studio/preview', 1)}>Preview Plan</button><button style={s.primary} disabled={running} onClick={() => request('/my-dashboard/query-studio/execute', 1)}>{running ? 'Validating…' : 'Run Query'}</button></div>
    {preview ? <div style={s.plan}><div style={s.planHeader}><strong>Validated plan</strong><span>{preview.logical_object}</span></div><div style={s.planGrid}><span>{preview.selected_fields?.length || 0} fields</span><span>{preview.filters?.length || 0} bound values</span><span>{preview.sort?.field || 'default sort'} {preview.sort?.direction || ''}</span><span>Limit {preview.pagination?.page_size}</span></div><details style={s.planDetails}><summary>Normalized request and bindings</summary><pre style={s.planCode}>{JSON.stringify({ logical_object: preview.logical_object, selected_fields: preview.selected_fields, filters: preview.filters, sort: preview.sort, pagination: preview.pagination }, null, 2)}</pre></details></div> : null}
    {result ? <div style={s.results}>
      <div style={s.row}><div><strong>{result.totalSize || 0} matching rows</strong><div style={s.muted}>Page {pageNumber} · {result?.provenance?.updated_at || result?.provenance?.generated_at || 'Current registered data'}</div></div><div style={s.actions}><button style={s.secondary} disabled={!rows.length || running || exporting} onClick={exportCsv}>{exporting ? 'Exporting All Rows…' : 'Export All Rows'}</button><button style={s.secondary} disabled={!rows.length || exporting} onClick={save}>Save Query</button></div></div>
      <div style={s.tableWrap}><table style={s.table}><thead><tr>{columns.map(column => <th style={s.th} key={column}>{fieldLabels[column] || column}</th>)}</tr></thead><tbody>{rows.map((row, index) => <tr key={row.mlb_player_id || row.id || index}>{columns.map(column => <td style={s.td} key={column}>{display(row?.[column])}</td>)}</tr>)}</tbody></table></div>
      <div style={s.pager}><button style={s.secondary} disabled={running || pageNumber <= 1} onClick={() => request('/my-dashboard/query-studio/execute', pageNumber - 1)}>Previous</button><span>Page {pageNumber}</span><button style={s.secondary} disabled={running || !(pageInfo.has_next || pageInfo.has_next_page)} onClick={() => request('/my-dashboard/query-studio/execute', pageNumber + 1)}>Next</button></div>
    </div> : null}
  </section>
}

const s = {
  panel: { display: 'grid', gap: 12, padding: 16, color: '#f7f8fb', fontFamily: CENTURY, fontSize: 12, background: 'radial-gradient(circle at 95% 0%,rgba(123,97,255,.2),transparent 34%),linear-gradient(145deg,#11141b,#242935 58%,#0b0d12)', border: '1px solid rgba(255,255,255,.28)', borderRadius: 20, boxShadow: 'inset 0 1px rgba(255,255,255,.18),0 18px 45px rgba(20,24,34,.18)' },
  row: { display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 12, flexWrap: 'wrap' },
  eyebrow: { color: '#a9a0ff', fontFamily: FRANKLIN, fontSize: 10, letterSpacing: '.12em', textTransform: 'uppercase' },
  title: { margin: '4px 0', fontFamily: FRANKLIN, fontSize: 19, fontWeight: 500, letterSpacing: '-.01em' },
  muted: { margin: 0, color: '#aeb4c2', lineHeight: 1.5 },
  note: { margin: 0, padding: 10, color: '#cdd2dc', lineHeight: 1.5, background: 'rgba(255,255,255,.06)', borderRadius: 10 },
  readyBadge: { padding: '5px 9px', color: '#d8d4ff', fontFamily: FRANKLIN, border: '1px solid rgba(167,139,250,.5)', borderRadius: 999, background: 'rgba(124,58,237,.18)' },
  lockBadge: { padding: '5px 9px', color: '#ffe2a8', fontFamily: FRANKLIN, border: '1px solid rgba(245,158,11,.45)', borderRadius: 999, background: 'rgba(245,158,11,.12)' },
  objectStrip: { display: 'flex', gap: 7, overflowX: 'auto', paddingBottom: 2 },
  objectChip: { flex: '0 0 auto', display: 'grid', gap: 2, padding: '8px 10px', color: '#f8fafc', textAlign: 'left', fontFamily: FRANKLIN, background: 'linear-gradient(145deg,rgba(255,255,255,.13),rgba(255,255,255,.035))', border: '1px solid rgba(255,255,255,.18)', borderRadius: 10 },
  label: { display: 'grid', gap: 7, color: '#d6dae3', fontFamily: FRANKLIN, fontSize: 11, letterSpacing: '.03em' },
  editor: { width: '100%', minHeight: 150, resize: 'vertical', boxSizing: 'border-box', padding: 13, color: '#f7f8fb', caretColor: '#a78bfa', fontFamily: 'ui-monospace,SFMono-Regular,Menlo,Consolas,monospace', fontSize: 12, lineHeight: 1.55, background: 'rgba(3,5,9,.64)', border: '1px solid rgba(255,255,255,.2)', borderRadius: 12, outline: 'none' },
  actions: { display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center' },
  primary: { padding: '9px 13px', color: '#fff', fontFamily: FRANKLIN, background: 'linear-gradient(105deg,#24252c,#7770ff 78%,#d7d5ff)', border: '1px solid rgba(255,255,255,.55)', borderRadius: 999, boxShadow: '0 0 22px rgba(124,92,255,.28)' },
  secondary: { padding: '8px 11px', color: '#f5f6f9', fontFamily: FRANKLIN, background: 'linear-gradient(145deg,rgba(255,255,255,.14),rgba(255,255,255,.035))', border: '1px solid rgba(255,255,255,.2)', borderRadius: 999 },
  error: { padding: 10, color: '#fecaca', background: 'rgba(185,28,28,.18)', border: '1px solid rgba(248,113,113,.28)', borderRadius: 10 },
  plan: { padding: 11, background: 'rgba(255,255,255,.055)', border: '1px solid rgba(255,255,255,.12)', borderRadius: 12 },
  planHeader: { display: 'flex', justifyContent: 'space-between', gap: 8, fontFamily: FRANKLIN },
  planGrid: { display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(100px,1fr))', gap: 6, marginTop: 8, color: '#bfc5d1' },
  planDetails: { marginTop: 9, color: '#d8dce5' },
  planCode: { maxHeight: 230, overflow: 'auto', margin: '8px 0 0', padding: 10, color: '#d8d4ff', fontFamily: 'ui-monospace,SFMono-Regular,Menlo,Consolas,monospace', fontSize: 10, lineHeight: 1.5, background: 'rgba(2,4,8,.48)', borderRadius: 9 },
  results: { display: 'grid', gap: 10, minWidth: 0 },
  tableWrap: { maxHeight: 360, overflow: 'auto', background: 'rgba(2,4,8,.4)', border: '1px solid rgba(255,255,255,.14)', borderRadius: 11 },
  table: { width: '100%', minWidth: 560, borderCollapse: 'collapse', fontFamily: CENTURY, fontSize: 11 },
  th: { position: 'sticky', top: 0, padding: '8px 9px', color: '#f8fafc', textAlign: 'left', fontFamily: FRANKLIN, background: '#171b24', borderBottom: '1px solid rgba(255,255,255,.16)' },
  td: { padding: '7px 9px', color: '#d4d8e1', whiteSpace: 'nowrap', borderBottom: '1px solid rgba(255,255,255,.08)' },
  pager: { display: 'flex', justifyContent: 'center', alignItems: 'center', gap: 10, color: '#c7cbd5', fontFamily: FRANKLIN },
}

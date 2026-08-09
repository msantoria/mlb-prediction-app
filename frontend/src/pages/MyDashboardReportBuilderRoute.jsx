import React, { useEffect, useState } from 'react'
import { createPortal } from 'react-dom'
import MyDashboardReportBuilderPage from './MyDashboardReportBuilderPage'
import { normalizeVisibleMyDashboardObject } from '../lib/myDashboardVisibleReportTypes.mjs'

const BUILDER_KEY = 'mlbgpt-report-builder:v3'
const LEGACY_LABELS = new Set(['Teams', 'Totals', 'Overall Players'])

function titleCase(value) {
  return String(value || '')
    .replace(/^metrics\./, '')
    .replace(/[_.-]+/g, ' ')
    .replace(/\s+/g, ' ')
    .trim()
    .replace(/\b\w/g, character => character.toUpperCase())
}

function operatorLabel(value) {
  return ({
    eq: '=',
    neq: '≠',
    contains: 'contains',
    in: 'is one of',
    gt: '>',
    gte: '≥',
    lt: '<',
    lte: '≤',
    is_null: 'is blank',
    is_not_null: 'is not blank',
  })[value] || titleCase(value)
}

function readBuilderState() {
  if (typeof window === 'undefined') return {}
  try {
    return JSON.parse(window.localStorage.getItem(BUILDER_KEY) || '{}') || {}
  } catch {
    return {}
  }
}

function normalizePersistedLegacySelection() {
  if (typeof window === 'undefined') return
  try {
    const persisted = readBuilderState()
    const activeObject = normalizeVisibleMyDashboardObject(persisted.activeObject)
    if (activeObject !== persisted.activeObject) {
      window.localStorage.setItem(BUILDER_KEY, JSON.stringify({ ...persisted, activeObject }))
    }
  } catch {}
}

function filterFacts(state) {
  const objectKey = state.activeObject || 'hitters'
  const filters = state.filters?.[objectKey] || {}
  const facts = []

  if (Array.isArray(filters.conditions)) {
    filters.conditions.forEach(condition => {
      if (!condition?.field || !condition?.operator) return
      const needsValue = !['is_null', 'is_not_null'].includes(condition.operator)
      facts.push(`${titleCase(condition.field)} ${operatorLabel(condition.operator)}${needsValue ? ` ${String(condition.value ?? '')}` : ''}`.trim())
    })
    const weightFacts = Object.entries(filters.weights || {})
      .filter(([, value]) => Number(value) !== 1)
      .map(([field, value]) => `${titleCase(field)} weight ${Number(value).toFixed(1)}×`)
    facts.push(...weightFacts)
    if (facts.length > 1) facts.unshift(`Logic: ${(filters.logic || 'and').toUpperCase()}`)
  } else {
    const labels = {
      search_text: 'Search', team: 'Team', opponent: 'Opponent', min_score: 'Min Score', max_score: 'Max Score',
      min_confidence: 'Min Confidence', category: 'Category', pitch_type: 'Pitch Type',
    }
    Object.entries(labels).forEach(([key, label]) => {
      const value = filters[key]
      if (value !== '' && value != null) facts.push(`${label}: ${value}`)
    })
    Object.entries(filters.metrics || {}).forEach(([metric, range]) => {
      if (range?.min !== '' && range?.min != null) facts.push(`${titleCase(metric)} ≥ ${range.min}`)
      if (range?.max !== '' && range?.max != null) facts.push(`${titleCase(metric)} ≤ ${range.max}`)
    })
    Object.entries(filters.weights || {}).forEach(([metric, value]) => {
      if (Number(value) !== 1) facts.push(`${titleCase(metric)} weight ${Number(value).toFixed(1)}×`)
    })
  }

  if (state.activeLineupsOnly) facts.push('Confirmed 1–9 only')
  return facts
}

function ReportFilterSummary({ state }) {
  const facts = filterFacts(state)
  return <div style={{ flexBasis: '100%', display: 'grid', gap: 7, marginTop: 4, padding: '10px 12px', border: '1px solid var(--md-border)', borderRadius: 12, background: 'var(--md-panel-2)' }}>
    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 10, flexWrap: 'wrap' }}>
      <strong style={{ fontFamily: '"Franklin Gothic Medium", "Franklin Gothic", "Arial Narrow", Arial, sans-serif', fontSize: 11, letterSpacing: '.06em', textTransform: 'uppercase' }}>Report Filters</strong>
      <span style={{ color: 'var(--md-muted)', fontSize: 10 }}>{facts.length ? `${facts.length} applied` : 'No filters applied'}</span>
    </div>
    {facts.length ? <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>{facts.map((fact, index) => <span key={`${fact}-${index}`} style={{ padding: '5px 8px', color: 'var(--md-text)', fontSize: 10, border: '1px solid var(--md-border)', borderRadius: 999, background: 'var(--md-control-soft)' }}>{fact}</span>)}</div> : <span style={{ color: 'var(--md-muted)', fontSize: 10 }}>This report was populated without additional filter criteria.</span>}
  </div>
}

export default function MyDashboardReportBuilderRoute() {
  normalizePersistedLegacySelection()
  const [reportHeader, setReportHeader] = useState(null)
  const [reportState, setReportState] = useState(() => readBuilderState())

  useEffect(() => {
    function reconcileUi() {
      document.querySelectorAll('.my-dashboard-route aside button').forEach(button => {
        const label = button.querySelector('strong')?.textContent?.trim()
        if (LEGACY_LABELS.has(label)) button.style.display = 'none'
      })

      const header = document.querySelector('.my-dashboard-route [role="dialog"][aria-modal="true"] header')
      setReportHeader(current => current === header ? current : header)
      if (header) setReportState(readBuilderState())
    }

    reconcileUi()
    const observer = new MutationObserver(reconcileUi)
    observer.observe(document.body, { childList: true, subtree: true })
    return () => observer.disconnect()
  }, [])

  return <div className="my-dashboard-route">
    <MyDashboardReportBuilderPage />
    {reportHeader ? createPortal(<ReportFilterSummary state={reportState} />, reportHeader) : null}
  </div>
}

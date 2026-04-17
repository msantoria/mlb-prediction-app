import React, { useState, useEffect } from 'react'
import { useParams, Link } from 'react-router-dom'

const API = import.meta.env.VITE_API_BASE_URL || ''

const s = {
  back: { color: '#58a6ff', textDecoration: 'none', fontSize: '13px', display: 'inline-block', marginBottom: '20px' },
  header: { display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '24px', flexWrap: 'wrap', gap: '12px' },
  title: { fontSize: '22px', fontWeight: '700', color: '#e6edf3' },
  subtitle: { fontSize: '13px', color: '#8b949e', marginTop: '4px' },
  tableWrap: { background: '#161b22', border: '1px solid #30363d', borderRadius: '10px', overflow: 'auto', marginBottom: '20px' },
  table: { width: '100%', borderCollapse: 'collapse', fontSize: '13px', minWidth: '700px' },
  th: { padding: '12px 14px', textAlign: 'left', color: '#8b949e', fontSize: '11px', textTransform: 'uppercase', letterSpacing: '0.5px', borderBottom: '1px solid #21262d', whiteSpace: 'nowrap' },
  thRight: { textAlign: 'right' },
  td: { padding: '11px 14px', borderBottom: '1px solid #0d1117', color: '#e6edf3', whiteSpace: 'nowrap' },
  tdRight: { textAlign: 'right' },
  tdMuted: { color: '#8b949e' },
  noData: { color: '#8b949e', padding: '12px 14px', fontSize: '13px' },
  loader: { color: '#8b949e', padding: '48px', textAlign: 'center' },
  error: { color: '#f85149', padding: '24px', background: '#1f1116', borderRadius: '8px' },
  note: { background: '#161b22', border: '1px solid #30363d', borderRadius: '8px', padding: '14px 18px', fontSize: '13px', color: '#8b949e', marginBottom: '16px' },
}

const pct = (v, d = 1) => v != null ? `${(v * 100).toFixed(d)}%` : '—'
const mph = v => v != null ? `${Number(v).toFixed(1)}` : '—'
const rpm = v => v != null ? `${Math.round(v)}` : '—'
const dec = (v, d = 3) => v != null ? Number(v).toFixed(d) : '—'

function kColor(v) {
  if (v == null) return '#e6edf3'
  if (v >= 0.28) return '#3fb950'
  if (v >= 0.22) return '#d29922'
  return '#f85149'
}
function bbColor(v) {
  if (v == null) return '#e6edf3'
  if (v <= 0.07) return '#3fb950'
  if (v <= 0.09) return '#d29922'
  return '#f85149'
}
function hhColor(v) {
  if (v == null) return '#e6edf3'
  if (v <= 0.30) return '#3fb950'
  if (v <= 0.37) return '#d29922'
  return '#f85149'
}
function xwobaColor(v) {
  if (v == null) return '#e6edf3'
  if (v <= 0.28) return '#3fb950'
  if (v <= 0.32) return '#d29922'
  return '#f85149'
}

export default function RollingPitcherPage() {
  const { id } = useParams()
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  useEffect(() => {
    if (!id) return
    setLoading(true)
    fetch(`${API}/pitcher/${id}/rolling?windows=15,30,60,90,120,150`)
      .then(r => r.ok ? r.json() : r.json().then(e => Promise.reject(e.detail || r.statusText)))
      .then(d => { setData(d); setLoading(false) })
      .catch(e => { setError(String(e)); setLoading(false) })
  }, [id])

  if (loading) return <div style={s.loader}>Loading rolling stats…</div>
  if (error) return <div style={s.error}>{error}</div>

  const windows = data?.windows || []
  const hasAny = windows.some(w => w.stats)

  return (
    <div>
      <Link to={`/pitcher/${id}`} style={s.back}>← Back to Pitcher Profile</Link>

      <div style={s.header}>
        <div>
          <div style={s.title}>Rolling Performance — Pitcher #{id}</div>
          <div style={s.subtitle}>Last N game appearances. Green = elite · Yellow = average · Red = below average</div>
        </div>
      </div>

      <div style={s.note}>
        Stats computed from stored Statcast events. xwOBA and release metrics require full Statcast data (available on 90-day aggregate). Rolling windows show K%, BB%, Hard Hit%, and velocity from event-level data.
      </div>

      {!hasAny && (
        <div style={{ color: '#8b949e', textAlign: 'center', padding: '48px' }}>
          No event-level data available for pitcher #{id}. Run the ETL to populate Statcast events.
        </div>
      )}

      {hasAny && (
        <div style={s.tableWrap}>
          <table style={s.table}>
            <thead>
              <tr>
                <th style={s.th}>Window</th>
                <th style={s.th}>Games</th>
                <th style={s.th}>Date Range</th>
                <th style={{ ...s.th, ...s.thRight }}>K%</th>
                <th style={{ ...s.th, ...s.thRight }}>BB%</th>
                <th style={{ ...s.th, ...s.thRight }}>Hard Hit%</th>
                <th style={{ ...s.th, ...s.thRight }}>xwOBA</th>
                <th style={{ ...s.th, ...s.thRight }}>Velo</th>
                <th style={{ ...s.th, ...s.thRight }}>Spin</th>
                <th style={{ ...s.th, ...s.thRight }}>HBreak</th>
                <th style={{ ...s.th, ...s.thRight }}>VBreak</th>
              </tr>
            </thead>
            <tbody>
              {windows.map((w, i) => {
                const st = w.stats
                if (!st) {
                  return (
                    <tr key={i}>
                      <td style={{ ...s.td, fontWeight: '600' }}>{w.window}</td>
                      <td colSpan={10} style={{ ...s.td, ...s.tdMuted }}>Insufficient data</td>
                    </tr>
                  )
                }
                const dateRange = st.start_date && st.end_date
                  ? `${st.start_date.slice(5)} – ${st.end_date.slice(5)}`
                  : '—'
                return (
                  <tr key={i}>
                    <td style={{ ...s.td, fontWeight: '700', color: '#58a6ff' }}>{w.window}</td>
                    <td style={s.td}>{st.actual_games ?? '—'}</td>
                    <td style={{ ...s.td, ...s.tdMuted, fontSize: '12px' }}>{dateRange}</td>
                    <td style={{ ...s.td, ...s.tdRight, color: kColor(st.k_pct), fontWeight: '600' }}>{pct(st.k_pct)}</td>
                    <td style={{ ...s.td, ...s.tdRight, color: bbColor(st.bb_pct), fontWeight: '600' }}>{pct(st.bb_pct)}</td>
                    <td style={{ ...s.td, ...s.tdRight, color: hhColor(st.hard_hit_pct), fontWeight: '600' }}>{pct(st.hard_hit_pct)}</td>
                    <td style={{ ...s.td, ...s.tdRight, color: xwobaColor(st.xwoba) }}>{dec(st.xwoba)}</td>
                    <td style={{ ...s.td, ...s.tdRight }}>{mph(st.avg_velocity)}</td>
                    <td style={{ ...s.td, ...s.tdRight }}>{rpm(st.avg_spin_rate)}</td>
                    <td style={{ ...s.td, ...s.tdRight }}>{st.avg_horiz_break != null ? Number(st.avg_horiz_break).toFixed(2) : '—'}</td>
                    <td style={{ ...s.td, ...s.tdRight }}>{st.avg_vert_break != null ? Number(st.avg_vert_break).toFixed(2) : '—'}</td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}

      <div style={{ fontSize: '12px', color: '#8b949e', marginTop: '8px' }}>
        Window = last N distinct game dates. A pitcher appearing 3 times in a doubleheader counts as 1 game.
        Seasons cross if N exceeds current-season appearances.
      </div>
    </div>
  )
}

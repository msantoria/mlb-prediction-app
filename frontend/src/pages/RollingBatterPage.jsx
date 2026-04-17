import React, { useState, useEffect, useCallback } from 'react'
import { useParams, Link } from 'react-router-dom'

const API = '/api'

const RESULT_COLORS = {
  single: '#3fb950', double: '#3fb950', triple: '#3fb950', home_run: '#58a6ff',
  walk: '#d29922', intent_walk: '#d29922', hit_by_pitch: '#d29922',
  strikeout: '#f85149', strikeout_double_play: '#f85149',
  field_out: '#8b949e', grounded_into_double_play: '#8b949e', double_play: '#8b949e',
  force_out: '#8b949e', fielders_choice: '#8b949e', fielders_choice_out: '#8b949e',
  sac_fly: '#8b949e', sac_bunt: '#8b949e',
}

const RESULT_LABELS = {
  single: '1B', double: '2B', triple: '3B', home_run: 'HR',
  walk: 'BB', intent_walk: 'IBB', hit_by_pitch: 'HBP',
  strikeout: 'K', strikeout_double_play: 'KDP',
  field_out: 'FO', grounded_into_double_play: 'GDP', double_play: 'DP',
  force_out: 'FO', fielders_choice: 'FC', fielders_choice_out: 'FCO',
  sac_fly: 'SF', sac_bunt: 'SB',
}

const s = {
  back: { color: '#58a6ff', textDecoration: 'none', fontSize: '13px', display: 'inline-block', marginBottom: '20px' },
  header: { display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '20px', flexWrap: 'wrap', gap: '12px' },
  title: { fontSize: '22px', fontWeight: '700', color: '#e6edf3' },
  subtitle: { fontSize: '13px', color: '#8b949e', marginTop: '4px' },
  tabs: { display: 'flex', gap: '0', marginBottom: '20px', background: '#161b22', border: '1px solid #30363d', borderRadius: '8px', overflow: 'hidden', width: 'fit-content' },
  tab: (active) => ({
    padding: '8px 18px', fontSize: '13px', fontWeight: '500', cursor: 'pointer',
    background: active ? '#58a6ff' : 'transparent',
    color: active ? '#0d1117' : '#8b949e',
    border: 'none', outline: 'none',
  }),
  tableWrap: { background: '#161b22', border: '1px solid #30363d', borderRadius: '10px', overflow: 'auto', marginBottom: '20px' },
  table: { width: '100%', borderCollapse: 'collapse', fontSize: '13px', minWidth: '600px' },
  th: { padding: '12px 14px', textAlign: 'left', color: '#8b949e', fontSize: '11px', textTransform: 'uppercase', letterSpacing: '0.5px', borderBottom: '1px solid #21262d', whiteSpace: 'nowrap' },
  thRight: { textAlign: 'right' },
  td: { padding: '10px 14px', borderBottom: '1px solid #0d1117', color: '#e6edf3', whiteSpace: 'nowrap' },
  tdRight: { textAlign: 'right' },
  tdMuted: { color: '#8b949e' },
  sectionTitle: { fontSize: '15px', fontWeight: '600', color: '#e6edf3', marginBottom: '12px', borderBottom: '1px solid #21262d', paddingBottom: '8px' },
  abRow: { display: 'grid', gridTemplateColumns: '90px 28px 70px auto 60px 60px 40px', gap: '4px', padding: '7px 14px', borderBottom: '1px solid #0d1117', fontSize: '13px', alignItems: 'center' },
  abHeader: { display: 'grid', gridTemplateColumns: '90px 28px 70px auto 60px 60px 40px', gap: '4px', padding: '9px 14px', borderBottom: '1px solid #21262d', fontSize: '11px', color: '#8b949e', textTransform: 'uppercase', letterSpacing: '0.5px' },
  pagination: { display: 'flex', gap: '8px', alignItems: 'center', justifyContent: 'center', padding: '16px', fontSize: '13px', color: '#8b949e' },
  pageBtn: (disabled) => ({
    background: disabled ? '#21262d' : '#30363d', border: 'none', color: disabled ? '#555' : '#e6edf3',
    borderRadius: '6px', padding: '6px 14px', cursor: disabled ? 'default' : 'pointer', fontSize: '13px',
  }),
  loader: { color: '#8b949e', padding: '48px', textAlign: 'center' },
  error: { color: '#f85149', padding: '24px', background: '#1f1116', borderRadius: '8px' },
}

const pct = (v) => v != null ? `${(v * 100).toFixed(1)}%` : '—'
const dec = (v, d = 3) => v != null ? Number(v).toFixed(d) : '—'
const mph = v => v != null ? `${Number(v).toFixed(1)}` : '—'
const deg = v => v != null ? `${Number(v).toFixed(1)}°` : '—'

function avgColor(v) {
  if (v == null) return '#e6edf3'
  if (v >= 0.280) return '#3fb950'
  if (v >= 0.240) return '#d29922'
  return '#f85149'
}
function kColor(v) {
  if (v == null) return '#e6edf3'
  if (v <= 0.18) return '#3fb950'
  if (v <= 0.25) return '#d29922'
  return '#f85149'
}
function evColor(v) {
  if (v == null) return '#e6edf3'
  if (v >= 92) return '#3fb950'
  if (v >= 88) return '#d29922'
  return '#f85149'
}

export default function RollingBatterPage() {
  const { id } = useParams()
  const [view, setView] = useState('abs')     // 'abs' | 'games'
  const [rolling, setRolling] = useState(null)
  const [abData, setAbData] = useState(null)
  const [abPage, setAbPage] = useState(0)
  const [abWindow, setAbWindow] = useState(50)
  const [loading, setLoading] = useState(true)
  const [abLoading, setAbLoading] = useState(false)
  const [error, setError] = useState(null)

  const AB_PAGE_SIZE = 50

  useEffect(() => {
    if (!id) return
    setLoading(true)
    const windows = view === 'abs' ? '10,25,50,100,200,400,1000' : '15,30,60,90,120,150'
    fetch(`${API}/batter/${id}/rolling?windows=${windows}&type=${view}`)
      .then(r => r.ok ? r.json() : r.json().then(e => Promise.reject(e.detail || r.statusText)))
      .then(d => { setRolling(d); setLoading(false) })
      .catch(e => { setError(String(e)); setLoading(false) })
  }, [id, view])

  const loadAbs = useCallback((page) => {
    if (!id) return
    setAbLoading(true)
    fetch(`${API}/batter/${id}/at-bats?n=${AB_PAGE_SIZE}&offset=${page * AB_PAGE_SIZE}`)
      .then(r => r.ok ? r.json() : r.json().then(e => Promise.reject(e.detail || r.statusText)))
      .then(d => { setAbData(d); setAbLoading(false) })
      .catch(() => setAbLoading(false))
  }, [id])

  useEffect(() => { loadAbs(0) }, [loadAbs])

  const totalPages = abData ? Math.ceil(abData.total_abs / AB_PAGE_SIZE) : 0

  function goPage(p) {
    setAbPage(p)
    loadAbs(p)
  }

  if (error) return <div style={s.error}>{error}</div>

  const windows = rolling?.windows || []

  return (
    <div>
      <Link to={`/batter/${id}`} style={s.back}>← Back to Batter Profile</Link>

      <div style={s.header}>
        <div>
          <div style={s.title}>Rolling Stats — Batter #{id}</div>
          <div style={s.subtitle}>Green = elite · Yellow = average · Red = below average</div>
        </div>
      </div>

      {/* Toggle */}
      <div style={s.tabs}>
        <button style={s.tab(view === 'abs')} onClick={() => setView('abs')}>Last N At-Bats</button>
        <button style={s.tab(view === 'games')} onClick={() => setView('games')}>Last N Games</button>
      </div>

      {/* Rolling stats table */}
      {loading ? <div style={s.loader}>Loading…</div> : (
        <div style={s.tableWrap}>
          <table style={s.table}>
            <thead>
              <tr>
                <th style={s.th}>Window</th>
                <th style={s.th}>{view === 'abs' ? 'ABs' : 'Games'}</th>
                <th style={s.th}>Range</th>
                <th style={{ ...s.th, ...s.thRight }}>AVG</th>
                <th style={{ ...s.th, ...s.thRight }}>OBP</th>
                <th style={{ ...s.th, ...s.thRight }}>SLG</th>
                <th style={{ ...s.th, ...s.thRight }}>HR</th>
                <th style={{ ...s.th, ...s.thRight }}>K%</th>
                <th style={{ ...s.th, ...s.thRight }}>BB%</th>
                <th style={{ ...s.th, ...s.thRight }}>EV</th>
                <th style={{ ...s.th, ...s.thRight }}>LA</th>
                <th style={{ ...s.th, ...s.thRight }}>HH%</th>
                <th style={{ ...s.th, ...s.thRight }}>Barrel%</th>
              </tr>
            </thead>
            <tbody>
              {windows.map((w, i) => {
                const st = w.stats
                if (!st) {
                  return (
                    <tr key={i}>
                      <td style={{ ...s.td, fontWeight: '600' }}>{w.window}</td>
                      <td colSpan={12} style={{ ...s.td, ...s.tdMuted }}>Insufficient data</td>
                    </tr>
                  )
                }
                const count = st.actual_abs ?? st.actual_games ?? '—'
                const dateRange = st.start_date && st.end_date
                  ? `${st.start_date.slice(5)} – ${st.end_date.slice(5)}`
                  : '—'
                return (
                  <tr key={i}>
                    <td style={{ ...s.td, fontWeight: '700', color: '#58a6ff' }}>{w.window}</td>
                    <td style={s.td}>{count}</td>
                    <td style={{ ...s.td, ...s.tdMuted, fontSize: '12px' }}>{dateRange}</td>
                    <td style={{ ...s.td, ...s.tdRight, color: avgColor(st.batting_avg), fontWeight: '600' }}>{dec(st.batting_avg)}</td>
                    <td style={{ ...s.td, ...s.tdRight }}>{dec(st.on_base_pct ?? null)}</td>
                    <td style={{ ...s.td, ...s.tdRight }}>{dec(st.slugging_pct ?? null)}</td>
                    <td style={{ ...s.td, ...s.tdRight }}>{st.home_runs ?? '—'}</td>
                    <td style={{ ...s.td, ...s.tdRight, color: kColor(st.k_pct), fontWeight: '600' }}>{pct(st.k_pct)}</td>
                    <td style={{ ...s.td, ...s.tdRight }}>{pct(st.bb_pct)}</td>
                    <td style={{ ...s.td, ...s.tdRight, color: evColor(st.avg_exit_velocity) }}>{mph(st.avg_exit_velocity)}</td>
                    <td style={{ ...s.td, ...s.tdRight }}>{deg(st.avg_launch_angle)}</td>
                    <td style={{ ...s.td, ...s.tdRight }}>{pct(st.hard_hit_pct)}</td>
                    <td style={{ ...s.td, ...s.tdRight }}>{pct(st.barrel_pct)}</td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}

      {/* Chronological At-Bat Session */}
      <div style={{ marginTop: '28px' }}>
        <div style={s.sectionTitle}>Chronological At-Bat Session</div>
        <div style={{ fontSize: '13px', color: '#8b949e', marginBottom: '14px' }}>
          {abData ? `${abData.total_abs.toLocaleString()} total plate appearances on record · showing ${AB_PAGE_SIZE} per page` : ''}
        </div>

        {abLoading ? <div style={s.loader}>Loading at-bats…</div> : abData && (
          <div style={s.tableWrap}>
            <div style={s.abHeader}>
              <span>Date</span>
              <span>Hand</span>
              <span>Pitch</span>
              <span>Result</span>
              <span style={{ textAlign: 'right' }}>EV</span>
              <span style={{ textAlign: 'right' }}>LA</span>
              <span>Stand</span>
            </div>
            {abData.at_bats.map((ab, i) => {
              const resultLabel = RESULT_LABELS[ab.result] || ab.result?.replace(/_/g, ' ') || '?'
              const resultColor = RESULT_COLORS[ab.result] || '#8b949e'
              return (
                <div key={i} style={s.abRow}>
                  <span style={{ color: '#8b949e', fontSize: '12px' }}>{ab.game_date}</span>
                  <span style={{ color: '#8b949e', fontSize: '12px' }}>{ab.pitcher_hand || '?'}</span>
                  <span style={{ color: '#8b949e', fontSize: '12px' }}>{ab.pitch_type || '—'}</span>
                  <span style={{ color: resultColor, fontWeight: '600' }}>{resultLabel}</span>
                  <span style={{ color: ab.exit_velocity ? '#e6edf3' : '#8b949e', textAlign: 'right' }}>
                    {ab.exit_velocity ? `${ab.exit_velocity.toFixed(1)}` : '—'}
                  </span>
                  <span style={{ color: '#8b949e', textAlign: 'right', fontSize: '12px' }}>
                    {ab.launch_angle != null ? `${ab.launch_angle.toFixed(0)}°` : '—'}
                  </span>
                  <span style={{ color: '#8b949e', fontSize: '12px' }}>{ab.batter_stand || '?'}</span>
                </div>
              )
            })}

            {/* Pagination */}
            <div style={s.pagination}>
              <button style={s.pageBtn(abPage === 0)} disabled={abPage === 0} onClick={() => goPage(abPage - 1)}>← Prev</button>
              <span>Page {abPage + 1} of {totalPages || 1}</span>
              <button style={s.pageBtn(abPage >= totalPages - 1)} disabled={abPage >= totalPages - 1} onClick={() => goPage(abPage + 1)}>Next →</button>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}

import React, { useState, useEffect } from 'react'
import { useParams, useNavigate, Link } from 'react-router-dom'

const API = '/api'

const s = {
  searchRow: { display: 'flex', gap: '12px', marginBottom: '28px' },
  input: {
    flex: 1, background: '#161b22', border: '1px solid #30363d', color: '#e6edf3',
    borderRadius: '6px', padding: '10px 14px', fontSize: '14px', outline: 'none',
  },
  btn: {
    background: '#238636', color: '#fff', border: 'none', borderRadius: '6px',
    padding: '10px 20px', fontSize: '14px', fontWeight: '600', cursor: 'pointer',
  },
  rollingLink: {
    display: 'inline-block', background: '#21262d', border: '1px solid #30363d',
    color: '#58a6ff', textDecoration: 'none', borderRadius: '6px',
    padding: '7px 16px', fontSize: '13px', fontWeight: '500', marginBottom: '24px',
  },
  section: { marginBottom: '28px' },
  sectionTitle: { fontSize: '16px', fontWeight: '600', color: '#e6edf3', marginBottom: '14px', borderBottom: '1px solid #21262d', paddingBottom: '8px' },
  statsGrid: { display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(160px, 1fr))', gap: '12px' },
  statCard: { background: '#161b22', border: '1px solid #30363d', borderRadius: '8px', padding: '14px 16px' },
  statLabel: { fontSize: '12px', color: '#8b949e', marginBottom: '6px', textTransform: 'uppercase', letterSpacing: '0.5px' },
  statVal: { fontSize: '22px', fontWeight: '700', color: '#e6edf3' },
  tableWrap: { background: '#161b22', border: '1px solid #30363d', borderRadius: '10px', overflow: 'auto' },
  table: { width: '100%', borderCollapse: 'collapse', fontSize: '13px' },
  th: { padding: '10px 14px', textAlign: 'left', color: '#8b949e', fontWeight: '500', fontSize: '11px', textTransform: 'uppercase', letterSpacing: '0.4px', borderBottom: '1px solid #21262d', whiteSpace: 'nowrap' },
  thRight: { textAlign: 'right' },
  td: { padding: '10px 14px', borderBottom: '1px solid #0d1117', color: '#e6edf3', whiteSpace: 'nowrap' },
  tdRight: { textAlign: 'right' },
  tdMuted: { color: '#8b949e' },
  sourceBadge: { display: 'inline-block', fontSize: '11px', padding: '2px 7px', borderRadius: '3px', background: '#21262d', color: '#8b949e', marginLeft: '10px', verticalAlign: 'middle', fontWeight: '400' },
  splitGrid: { display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '16px' },
  splitCard: { background: '#161b22', border: '1px solid #30363d', borderRadius: '8px', padding: '16px' },
  splitTitle: { fontSize: '14px', fontWeight: '600', color: '#58a6ff', marginBottom: '12px' },
  splitRow: { display: 'flex', justifyContent: 'space-between', padding: '6px 0', borderBottom: '1px solid #21262d', fontSize: '13px' },
  splitKey: { color: '#8b949e' },
  splitVal: { color: '#e6edf3', fontWeight: '500' },
  loader: { color: '#8b949e', padding: '48px', textAlign: 'center' },
  error: { color: '#f85149', padding: '24px', background: '#1f1116', borderRadius: '8px' },
  hint: { color: '#8b949e', textAlign: 'center', padding: '48px' },
}

function fmt(val, decimals = 1) {
  if (val == null) return '—'
  return typeof val === 'number' ? val.toFixed(decimals) : val
}
function pct(val) {
  if (val == null) return '—'
  return `${(val * 100).toFixed(1)}%`
}

function StatCard({ label, value }) {
  return (
    <div style={s.statCard}>
      <div style={s.statLabel}>{label}</div>
      <div style={s.statVal}>{value}</div>
    </div>
  )
}

function SplitCard({ title, split }) {
  if (!split) return (
    <div style={s.splitCard}>
      <div style={s.splitTitle}>{title}</div>
      <div style={{ color: '#8b949e', fontSize: '13px' }}>No data</div>
    </div>
  )
  const rows = [
    ['PA', split.pa],
    ['AVG', fmt(split.batting_avg, 3)],
    ['OBP', fmt(split.on_base_pct, 3)],
    ['SLG', fmt(split.slugging_pct, 3)],
    ['HR', split.home_runs],
    ['K%', pct(split.k_pct)],
    ['BB%', pct(split.bb_pct)],
  ]
  return (
    <div style={s.splitCard}>
      <div style={s.splitTitle}>{title}</div>
      {rows.map(([k, v]) => (
        <div key={k} style={s.splitRow}>
          <span style={s.splitKey}>{k}</span>
          <span style={s.splitVal}>{v ?? '—'}</span>
        </div>
      ))}
    </div>
  )
}

export default function BatterPage() {
  const { id } = useParams()
  const navigate = useNavigate()
  const [inputId, setInputId] = useState(id || '')
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)

  function load(pid) {
    if (!pid) return
    setLoading(true)
    setError(null)
    fetch(`${API}/batter/${pid}`)
      .then(r => r.ok ? r.json() : r.json().then(e => Promise.reject(e.detail || r.statusText)))
      .then(d => { setData(d); setLoading(false) })
      .catch(e => { setError(String(e)); setLoading(false); setData(null) })
  }

  useEffect(() => { if (id) load(id) }, [id])

  function handleSearch(e) {
    e.preventDefault()
    navigate(`/batter/${inputId}`)
  }

  const agg = data?.aggregate
  const multiSeason = data?.multi_season || []

  return (
    <div>
      <h1 style={{ fontSize: '24px', fontWeight: '700', marginBottom: '20px' }}>Batter Profile</h1>

      <form style={s.searchRow} onSubmit={handleSearch}>
        <input
          style={s.input}
          placeholder="MLBAM Batter ID (e.g. 660271)"
          value={inputId}
          onChange={e => setInputId(e.target.value)}
        />
        <button type="submit" style={s.btn}>Look Up</button>
      </form>

      {loading && <div style={s.loader}>Loading…</div>}
      {error && <div style={s.error}>{error}</div>}
      {!loading && !error && !data && <div style={s.hint}>Enter a batter's MLBAM ID to view their stats.</div>}

      {data && (
        <>
          {id && (
            <Link to={`/batter/${id}/rolling`} style={s.rollingLink}>
              View Rolling Stats (L10–L1000 ABs) →
            </Link>
          )}

          {agg && (
            <div style={s.section}>
              <div style={s.sectionTitle}>
                Current Metrics
                {data.data_source && <span style={s.sourceBadge}>{data.data_source}</span>}
              </div>
              <div style={s.statsGrid}>
                <StatCard label="Exit Velocity" value={`${fmt(agg.avg_exit_velocity)} mph`} />
                <StatCard label="Launch Angle" value={`${fmt(agg.avg_launch_angle)}°`} />
                <StatCard label="Hard Hit%" value={pct(agg.hard_hit_pct)} />
                <StatCard label="Barrel%" value={pct(agg.barrel_pct)} />
                <StatCard label="K%" value={pct(agg.k_pct)} />
                <StatCard label="BB%" value={pct(agg.bb_pct)} />
                <StatCard label="AVG" value={fmt(agg.batting_avg, 3)} />
              </div>
            </div>
          )}

          {multiSeason.some(r => r.avg_exit_velocity != null || r.k_pct != null) && (
            <div style={s.section}>
              <div style={s.sectionTitle}>Season-by-Season</div>
              <div style={s.tableWrap}>
                <table style={s.table}>
                  <thead>
                    <tr>
                      <th style={s.th}>Season</th>
                      <th style={{ ...s.th, ...s.thRight }}>EV</th>
                      <th style={{ ...s.th, ...s.thRight }}>LA</th>
                      <th style={{ ...s.th, ...s.thRight }}>Hard Hit%</th>
                      <th style={{ ...s.th, ...s.thRight }}>Barrel%</th>
                      <th style={{ ...s.th, ...s.thRight }}>K%</th>
                      <th style={{ ...s.th, ...s.thRight }}>BB%</th>
                      <th style={{ ...s.th, ...s.thRight }}>AVG</th>
                    </tr>
                  </thead>
                  <tbody>
                    {multiSeason.map((row, i) => (
                      <tr key={i}>
                        <td style={{ ...s.td, fontWeight: '700', color: '#58a6ff' }}>{row.label}</td>
                        <td style={{ ...s.td, ...s.tdRight }}>{fmt(row.avg_exit_velocity)}</td>
                        <td style={{ ...s.td, ...s.tdRight }}>{fmt(row.avg_launch_angle)}°</td>
                        <td style={{ ...s.td, ...s.tdRight }}>{pct(row.hard_hit_pct)}</td>
                        <td style={{ ...s.td, ...s.tdRight }}>{pct(row.barrel_pct)}</td>
                        <td style={{ ...s.td, ...s.tdRight }}>{pct(row.k_pct)}</td>
                        <td style={{ ...s.td, ...s.tdRight }}>{pct(row.bb_pct)}</td>
                        <td style={{ ...s.td, ...s.tdRight }}>{fmt(row.batting_avg, 3)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          <div style={s.section}>
            <div style={s.sectionTitle}>Platoon Splits</div>
            <div style={s.splitGrid}>
              <SplitCard title="vs Left-Handed Pitchers" split={data.splits?.vsL} />
              <SplitCard title="vs Right-Handed Pitchers" split={data.splits?.vsR} />
            </div>
          </div>
        </>
      )}
    </div>
  )
}

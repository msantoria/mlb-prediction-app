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

export default function PitcherPage() {
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
    fetch(`${API}/pitcher/${pid}`)
      .then(r => r.ok ? r.json() : r.json().then(e => Promise.reject(e.detail || r.statusText)))
      .then(d => { setData(d); setLoading(false) })
      .catch(e => { setError(String(e)); setLoading(false); setData(null) })
  }

  useEffect(() => { if (id) load(id) }, [id])

  function handleSearch(e) {
    e.preventDefault()
    navigate(`/pitcher/${inputId}`)
  }

  const agg = data?.aggregate
  const arsenal = data?.arsenal || []
  const multiSeason = data?.multi_season || []
  const gameLog = data?.game_log || []

  return (
    <div>
      <h1 style={{ fontSize: '24px', fontWeight: '700', marginBottom: '20px' }}>Pitcher Profile</h1>

      <form style={s.searchRow} onSubmit={handleSearch}>
        <input
          style={s.input}
          placeholder="MLBAM Pitcher ID (e.g. 605483)"
          value={inputId}
          onChange={e => setInputId(e.target.value)}
        />
        <button type="submit" style={s.btn}>Look Up</button>
      </form>

      {loading && <div style={s.loader}>Loading…</div>}
      {error && <div style={s.error}>{error}</div>}
      {!loading && !error && !data && <div style={s.hint}>Enter a pitcher's MLBAM ID to view their stats.</div>}

      {data && (
        <>
          {id && (
            <Link to={`/pitcher/${id}/rolling`} style={s.rollingLink}>
              View Rolling Stats (L15–L150 Games) →
            </Link>
          )}

          {agg && (
            <div style={s.section}>
              <div style={s.sectionTitle}>
                Current Metrics
                {data.data_source && <span style={s.sourceBadge}>{data.data_source}</span>}
              </div>
              <div style={s.statsGrid}>
                <StatCard label="Avg Velocity" value={`${fmt(agg.avg_velocity)} mph`} />
                <StatCard label="Spin Rate" value={`${fmt(agg.avg_spin_rate, 0)} rpm`} />
                <StatCard label="K%" value={pct(agg.k_pct)} />
                <StatCard label="BB%" value={pct(agg.bb_pct)} />
                <StatCard label="Hard Hit%" value={pct(agg.hard_hit_pct)} />
                <StatCard label="xwOBA" value={fmt(agg.xwoba, 3)} />
                <StatCard label="xBA" value={fmt(agg.xba, 3)} />
                <StatCard label="Horiz Break" value={`${fmt(agg.avg_horiz_break, 2)}"`} />
                <StatCard label="Vert Break" value={`${fmt(agg.avg_vert_break, 2)}"`} />
              </div>
            </div>
          )}

          {multiSeason.some(r => r.avg_velocity != null || r.k_pct != null) && (
            <div style={s.section}>
              <div style={s.sectionTitle}>Season-by-Season</div>
              <div style={s.tableWrap}>
                <table style={s.table}>
                  <thead>
                    <tr>
                      <th style={s.th}>Season</th>
                      <th style={{ ...s.th, ...s.thRight }}>Velo</th>
                      <th style={{ ...s.th, ...s.thRight }}>Spin</th>
                      <th style={{ ...s.th, ...s.thRight }}>K%</th>
                      <th style={{ ...s.th, ...s.thRight }}>BB%</th>
                      <th style={{ ...s.th, ...s.thRight }}>Hard Hit%</th>
                      <th style={{ ...s.th, ...s.thRight }}>xwOBA</th>
                      <th style={{ ...s.th, ...s.thRight }}>xBA</th>
                    </tr>
                  </thead>
                  <tbody>
                    {multiSeason.map((row, i) => (
                      <tr key={i}>
                        <td style={{ ...s.td, fontWeight: '700', color: '#58a6ff' }}>{row.label}</td>
                        <td style={{ ...s.td, ...s.tdRight }}>{fmt(row.avg_velocity)}</td>
                        <td style={{ ...s.td, ...s.tdRight }}>{fmt(row.avg_spin_rate, 0)}</td>
                        <td style={{ ...s.td, ...s.tdRight }}>{pct(row.k_pct)}</td>
                        <td style={{ ...s.td, ...s.tdRight }}>{pct(row.bb_pct)}</td>
                        <td style={{ ...s.td, ...s.tdRight }}>{pct(row.hard_hit_pct)}</td>
                        <td style={{ ...s.td, ...s.tdRight }}>{fmt(row.xwoba, 3)}</td>
                        <td style={{ ...s.td, ...s.tdRight }}>{fmt(row.xba, 3)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {gameLog.length > 0 && (
            <div style={s.section}>
              <div style={s.sectionTitle}>Recent Outings</div>
              <div style={s.tableWrap}>
                <table style={s.table}>
                  <thead>
                    <tr>
                      <th style={s.th}>Date</th>
                      <th style={{ ...s.th, ...s.thRight }}>Pitches</th>
                      <th style={{ ...s.th, ...s.thRight }}>PA</th>
                      <th style={{ ...s.th, ...s.thRight }}>K</th>
                      <th style={{ ...s.th, ...s.thRight }}>BB</th>
                      <th style={{ ...s.th, ...s.thRight }}>HR</th>
                      <th style={{ ...s.th, ...s.thRight }}>HH%</th>
                      <th style={{ ...s.th, ...s.thRight }}>Velo</th>
                    </tr>
                  </thead>
                  <tbody>
                    {gameLog.map((g, i) => (
                      <tr key={i}>
                        <td style={{ ...s.td, ...s.tdMuted, fontSize: '12px' }}>{g.game_date}</td>
                        <td style={{ ...s.td, ...s.tdRight }}>{g.pitch_count ?? '—'}</td>
                        <td style={{ ...s.td, ...s.tdRight }}>{g.plate_appearances ?? '—'}</td>
                        <td style={{ ...s.td, ...s.tdRight, color: '#3fb950' }}>{g.strikeouts ?? '—'}</td>
                        <td style={{ ...s.td, ...s.tdRight, color: '#d29922' }}>{g.walks ?? '—'}</td>
                        <td style={{ ...s.td, ...s.tdRight, color: g.home_runs > 0 ? '#f85149' : '#e6edf3' }}>{g.home_runs ?? '—'}</td>
                        <td style={{ ...s.td, ...s.tdRight }}>{g.hard_hit_pct != null ? pct(g.hard_hit_pct) : '—'}</td>
                        <td style={{ ...s.td, ...s.tdRight }}>{g.avg_velocity != null ? `${g.avg_velocity.toFixed(1)}` : '—'}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {arsenal.length > 0 && (
            <div style={s.section}>
              <div style={s.sectionTitle}>
                Pitch Arsenal
                {data.arsenal_season && <span style={s.sourceBadge}>{data.arsenal_season}</span>}
              </div>
              <div style={s.tableWrap}>
                <table style={s.table}>
                  <thead>
                    <tr>
                      {['Pitch', 'Usage%', 'Whiff%', 'K%', 'RV/100', 'xwOBA', 'Hard Hit%'].map(h => (
                        <th key={h} style={h === 'Pitch' ? s.th : { ...s.th, ...s.thRight }}>{h}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {arsenal.map((p, i) => (
                      <tr key={i}>
                        <td style={s.td}>{p.pitch_name || p.pitch_type}</td>
                        <td style={{ ...s.td, ...s.tdRight }}>{pct(p.usage_pct)}</td>
                        <td style={{ ...s.td, ...s.tdRight }}>{pct(p.whiff_pct)}</td>
                        <td style={{ ...s.td, ...s.tdRight }}>{pct(p.strikeout_pct)}</td>
                        <td style={{ ...s.td, ...s.tdRight, color: (p.rv_per_100 || 0) < 0 ? '#3fb950' : '#f85149' }}>
                          {fmt(p.rv_per_100, 1)}
                        </td>
                        <td style={{ ...s.td, ...s.tdRight }}>{fmt(p.xwoba, 3)}</td>
                        <td style={{ ...s.td, ...s.tdRight }}>{pct(p.hard_hit_pct)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </>
      )}
    </div>
  )
}

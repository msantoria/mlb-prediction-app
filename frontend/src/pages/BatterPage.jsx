import React, { useState, useEffect } from 'react'
import { useParams, useNavigate, Link } from 'react-router-dom'

const API = import.meta.env.VITE_API_BASE_URL || ''

const s = {
  searchRow: { display: 'flex', gap: '12px', marginBottom: '28px' },
  input: {
    flex: 1, background: '#161b22', border: '1px solid #30363d', color: '#e6edf3',
    borderRadius: '6px', padding: '10px 14px', fontSize: '14px', outline: 'none',
  },
  playerHeader: {
    background: '#161b22', border: '1px solid #30363d', borderRadius: '10px',
    padding: '20px 24px', marginBottom: '20px',
  },
  playerName: { fontSize: '26px', fontWeight: '700', color: '#e6edf3', marginBottom: '6px' },
  playerMeta: { display: 'flex', gap: '16px', flexWrap: 'wrap', fontSize: '13px', color: '#8b949e' },
  metaChip: { background: '#21262d', borderRadius: '4px', padding: '2px 8px', color: '#e6edf3' },
  rollingLink: {
    display: 'inline-block', background: '#21262d', border: '1px solid #30363d',
    color: '#58a6ff', textDecoration: 'none', borderRadius: '6px',
    padding: '7px 16px', fontSize: '13px', fontWeight: '500', marginBottom: '24px',
  },
  section: { marginBottom: '28px' },
  sectionTitle: { fontSize: '16px', fontWeight: '600', color: '#e6edf3', marginBottom: '14px', borderBottom: '1px solid #21262d', paddingBottom: '8px' },
  statsGrid: { display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(140px, 1fr))', gap: '12px' },
  statCard: { background: '#161b22', border: '1px solid #30363d', borderRadius: '8px', padding: '14px 16px' },
  statLabel: { fontSize: '11px', color: '#8b949e', marginBottom: '6px', textTransform: 'uppercase', letterSpacing: '0.5px' },
  statVal: { fontSize: '22px', fontWeight: '700', color: '#e6edf3' },
  tableWrap: { background: '#161b22', border: '1px solid #30363d', borderRadius: '10px', overflow: 'auto' },
  table: { width: '100%', borderCollapse: 'collapse', fontSize: '13px' },
  th: { padding: '10px 14px', textAlign: 'left', color: '#8b949e', fontWeight: '500', fontSize: '11px', textTransform: 'uppercase', letterSpacing: '0.4px', borderBottom: '1px solid #21262d', whiteSpace: 'nowrap' },
  thR: { textAlign: 'right' },
  td: { padding: '10px 14px', borderBottom: '1px solid #0d1117', color: '#e6edf3', whiteSpace: 'nowrap' },
  tdR: { textAlign: 'right' },
  tdMuted: { color: '#8b949e' },
  splitGrid: { display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '16px' },
  splitCard: { background: '#161b22', border: '1px solid #30363d', borderRadius: '8px', padding: '16px' },
  splitTitle: { fontSize: '14px', fontWeight: '600', color: '#58a6ff', marginBottom: '12px' },
  splitRow: { display: 'flex', justifyContent: 'space-between', padding: '6px 0', borderBottom: '1px solid #21262d', fontSize: '13px' },
  splitKey: { color: '#8b949e' },
  splitVal: { color: '#e6edf3', fontWeight: '500' },
  sourceBadge: { display: 'inline-block', fontSize: '11px', padding: '2px 7px', borderRadius: '3px', background: '#21262d', color: '#8b949e', marginLeft: '10px', verticalAlign: 'middle', fontWeight: '400' },
  loader: { color: '#8b949e', padding: '48px', textAlign: 'center' },
  error: { color: '#f85149', padding: '24px', background: '#1f1116', borderRadius: '8px' },
  hint: { color: '#8b949e', textAlign: 'center', padding: '48px' },
}

const searchDropStyle = {
  position: 'absolute', top: '100%', left: 0, right: 0, zIndex: 100,
  background: '#161b22', border: '1px solid #30363d', borderRadius: '6px',
  marginTop: '4px', maxHeight: '280px', overflowY: 'auto',
}
const searchItemStyle = (hover) => ({
  padding: '9px 14px', cursor: 'pointer', borderBottom: '1px solid #21262d',
  background: hover ? '#21262d' : 'transparent',
  display: 'flex', justifyContent: 'space-between', alignItems: 'center',
})

const fmt = (v, d = 1) => v != null ? (typeof v === 'number' ? v.toFixed(d) : v) : '—'
const pct = (v, d = 1) => v != null ? `${(v * 100).toFixed(d)}%` : '—'
const num = (v) => v != null ? v : '—'

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
    ['PA', num(split.pa)],
    ['AVG', fmt(split.batting_avg, 3)],
    ['OBP', fmt(split.on_base_pct, 3)],
    ['SLG', fmt(split.slugging_pct, 3)],
    ['OPS', fmt(split.ops, 3)],
    ['HR', num(split.hr ?? split.home_runs)],
    ['K%', pct(split.k_pct)],
    ['BB%', pct(split.bb_pct)],
  ]
  return (
    <div style={s.splitCard}>
      <div style={s.splitTitle}>{title}</div>
      {rows.map(([k, v]) => (
        <div key={k} style={s.splitRow}>
          <span style={s.splitKey}>{k}</span>
          <span style={s.splitVal}>{v}</span>
        </div>
      ))}
    </div>
  )
}

export default function BatterPage() {
  const { id } = useParams()
  const navigate = useNavigate()
  const [query, setQuery] = useState('')
  const [results, setResults] = useState([])
  const [searching, setSearching] = useState(false)
  const [hoverIdx, setHoverIdx] = useState(-1)
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const debounceRef = React.useRef(null)

  function load(pid) {
    if (!pid) return
    setLoading(true); setError(null); setResults([])
    fetch(`${API}/batter/${pid}/profile`)
      .then(r => r.ok ? r.json() : r.json().then(e => Promise.reject(e.detail || r.statusText)))
      .then(d => { setData(d); setLoading(false) })
      .catch(e => { setError(String(e)); setLoading(false); setData(null) })
  }

  useEffect(() => { if (id) load(id) }, [id])

  function onQueryChange(e) {
    const val = e.target.value
    setQuery(val); setHoverIdx(-1)
    clearTimeout(debounceRef.current)
    if (val.length < 2) { setResults([]); return }
    debounceRef.current = setTimeout(() => {
      setSearching(true)
      fetch(`${API}/players/search?name=${encodeURIComponent(val)}`)
        .then(r => r.ok ? r.json() : [])
        .then(d => { setResults((d || []).filter(p => p.position_type === 'Batter')); setSearching(false) })
        .catch(() => setSearching(false))
    }, 300)
  }

  function selectPlayer(p) {
    setQuery(p.name); setResults([])
    navigate(`/batter/${p.id}`)
  }

  const info = data?.player_info
  const ss = data?.season_stats
  const sc = data?.statcast
  const splits = data?.splits || {}
  const yby = data?.year_by_year || []
  const agg = data?.aggregate

  return (
    <div>
      <h1 style={{ fontSize: '24px', fontWeight: '700', marginBottom: '20px' }}>Batter Profile</h1>

      <div style={{ position: 'relative', marginBottom: '28px' }}>
        <div style={s.searchRow}>
          <input
            style={s.input}
            placeholder="Search batter by name (e.g. Aaron Judge)"
            value={query}
            onChange={onQueryChange}
            autoComplete="off"
          />
          {searching && <span style={{ color: '#8b949e', fontSize: '13px', alignSelf: 'center' }}>Searching…</span>}
        </div>
        {results.length > 0 && (
          <div style={searchDropStyle}>
            {results.slice(0, 10).map((p, i) => (
              <div key={p.id} style={searchItemStyle(i === hoverIdx)}
                onMouseEnter={() => setHoverIdx(i)} onMouseLeave={() => setHoverIdx(-1)}
                onClick={() => selectPlayer(p)}>
                <span style={{ color: '#e6edf3' }}>{p.name}</span>
                <span style={{ color: '#8b949e', fontSize: '12px' }}>{p.team || ''}</span>
              </div>
            ))}
          </div>
        )}
      </div>

      {loading && <div style={s.loader}>Loading…</div>}
      {error && <div style={s.error}>{error}</div>}
      {!loading && !error && !data && <div style={s.hint}>Search for a batter by name to view their stats.</div>}

      {data && (
        <>
          {info && (
            <div style={s.playerHeader}>
              <div style={s.playerName}>{info.name}</div>
              <div style={s.playerMeta}>
                {info.position && <span style={s.metaChip}>{info.position}</span>}
                {info.team && <span style={s.metaChip}>{info.team}</span>}
                {info.bats && <span>Bats: <strong style={{ color: '#e6edf3' }}>{info.bats}</strong></span>}
                {info.throws && <span>Throws: <strong style={{ color: '#e6edf3' }}>{info.throws}</strong></span>}
                {info.mlb_debut && <span>Debut: <strong style={{ color: '#e6edf3' }}>{info.mlb_debut?.slice(0, 4)}</strong></span>}
              </div>
            </div>
          )}

          {id && (
            <Link to={`/batter/${id}/rolling`} style={s.rollingLink}>
              View Rolling Stats (PA / AB / Games) →
            </Link>
          )}

          {ss && (
            <div style={s.section}>
              <div style={s.sectionTitle}>
                {new Date().getFullYear()} Season Stats
                <span style={s.sourceBadge}>MLB Stats API</span>
              </div>
              <div style={s.statsGrid}>
                <StatCard label="G" value={num(ss.g)} />
                <StatCard label="PA" value={num(ss.pa)} />
                <StatCard label="AB" value={num(ss.ab)} />
                <StatCard label="H" value={num(ss.h)} />
                <StatCard label="HR" value={num(ss.hr)} />
                <StatCard label="RBI" value={num(ss.rbi)} />
                <StatCard label="R" value={num(ss.r)} />
                <StatCard label="SB" value={num(ss.sb)} />
                <StatCard label="BB" value={num(ss.bb)} />
                <StatCard label="K" value={num(ss.k)} />
                <StatCard label="AVG" value={fmt(ss.batting_avg, 3)} />
                <StatCard label="OBP" value={fmt(ss.on_base_pct, 3)} />
                <StatCard label="SLG" value={fmt(ss.slugging_pct, 3)} />
                <StatCard label="OPS" value={fmt(ss.ops, 3)} />
                <StatCard label="K%" value={pct(ss.k_pct)} />
                <StatCard label="BB%" value={pct(ss.bb_pct)} />
              </div>
            </div>
          )}

          {sc && (
            <div style={s.section}>
              <div style={s.sectionTitle}>
                Statcast Metrics
                <span style={s.sourceBadge}>{sc.data_window} · {sc.sample_size} PA</span>
              </div>
              <div style={s.statsGrid}>
                <StatCard label="Avg Exit Velo" value={`${fmt(sc.avg_exit_velocity)} mph`} />
                <StatCard label="Max Exit Velo" value={`${fmt(sc.max_exit_velocity)} mph`} />
                <StatCard label="Avg Launch Angle" value={`${fmt(sc.avg_launch_angle)}°`} />
                <StatCard label="Hard Hit%" value={pct(sc.hard_hit_pct)} />
                <StatCard label="Barrel%" value={pct(sc.barrel_pct)} />
                <StatCard label="AVG (Statcast)" value={fmt(sc.batting_avg, 3)} />
                <StatCard label="K% (Statcast)" value={pct(sc.k_pct)} />
                <StatCard label="BB% (Statcast)" value={pct(sc.bb_pct)} />
              </div>
            </div>
          )}

          {agg && (
            <div style={s.section}>
              <div style={s.sectionTitle}>
                Aggregate (DB)
                {data.aggregate_label && <span style={s.sourceBadge}>{data.aggregate_label}</span>}
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

          {(splits.vsL || splits.vsR) && (
            <div style={s.section}>
              <div style={s.sectionTitle}>Platoon Splits — Current Season</div>
              <div style={s.splitGrid}>
                <SplitCard title="vs Left-Handed Pitchers" split={splits.vsL} />
                <SplitCard title="vs Right-Handed Pitchers" split={splits.vsR} />
              </div>
            </div>
          )}

          {yby.length > 0 && (
            <div style={s.section}>
              <div style={s.sectionTitle}>
                Year-by-Year
                <span style={s.sourceBadge}>MLB Stats API</span>
              </div>
              <div style={s.tableWrap}>
                <table style={s.table}>
                  <thead>
                    <tr>
                      {['Season','G','PA','H','2B','3B','HR','RBI','SB','BB','K','AVG','OBP','SLG','OPS','K%','BB%'].map(h => (
                        <th key={h} style={h === 'Season' ? s.th : { ...s.th, ...s.thR }}>{h}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {yby.map((row, i) => (
                      <tr key={i}>
                        <td style={{ ...s.td, fontWeight: '700', color: '#58a6ff' }}>{row.season}</td>
                        <td style={{ ...s.td, ...s.tdR }}>{num(row.g)}</td>
                        <td style={{ ...s.td, ...s.tdR }}>{num(row.pa)}</td>
                        <td style={{ ...s.td, ...s.tdR }}>{num(row.h)}</td>
                        <td style={{ ...s.td, ...s.tdR }}>{num(row.doubles)}</td>
                        <td style={{ ...s.td, ...s.tdR }}>{num(row.triples)}</td>
                        <td style={{ ...s.td, ...s.tdR }}>{num(row.hr)}</td>
                        <td style={{ ...s.td, ...s.tdR }}>{num(row.rbi)}</td>
                        <td style={{ ...s.td, ...s.tdR }}>{num(row.sb)}</td>
                        <td style={{ ...s.td, ...s.tdR }}>{num(row.bb)}</td>
                        <td style={{ ...s.td, ...s.tdR }}>{num(row.k)}</td>
                        <td style={{ ...s.td, ...s.tdR }}>{fmt(row.batting_avg, 3)}</td>
                        <td style={{ ...s.td, ...s.tdR }}>{fmt(row.on_base_pct, 3)}</td>
                        <td style={{ ...s.td, ...s.tdR }}>{fmt(row.slugging_pct, 3)}</td>
                        <td style={{ ...s.td, ...s.tdR }}>{fmt(row.ops, 3)}</td>
                        <td style={{ ...s.td, ...s.tdR }}>{pct(row.k_pct)}</td>
                        <td style={{ ...s.td, ...s.tdR }}>{pct(row.bb_pct)}</td>
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

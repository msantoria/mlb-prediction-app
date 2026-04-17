import React, { useState, useEffect } from 'react'
import { useParams, Link } from 'react-router-dom'

const API = '/api'

const TEAMS = [
  { id: 108, name: 'Los Angeles Angels' },
  { id: 109, name: 'Arizona Diamondbacks' },
  { id: 110, name: 'Baltimore Orioles' },
  { id: 111, name: 'Boston Red Sox' },
  { id: 112, name: 'Chicago Cubs' },
  { id: 113, name: 'Cincinnati Reds' },
  { id: 114, name: 'Cleveland Guardians' },
  { id: 115, name: 'Colorado Rockies' },
  { id: 116, name: 'Detroit Tigers' },
  { id: 117, name: 'Houston Astros' },
  { id: 118, name: 'Kansas City Royals' },
  { id: 119, name: 'Los Angeles Dodgers' },
  { id: 120, name: 'Washington Nationals' },
  { id: 121, name: 'New York Mets' },
  { id: 133, name: 'Oakland Athletics' },
  { id: 134, name: 'Pittsburgh Pirates' },
  { id: 135, name: 'San Diego Padres' },
  { id: 136, name: 'Seattle Mariners' },
  { id: 137, name: 'San Francisco Giants' },
  { id: 138, name: 'St. Louis Cardinals' },
  { id: 139, name: 'Tampa Bay Rays' },
  { id: 140, name: 'Texas Rangers' },
  { id: 141, name: 'Toronto Blue Jays' },
  { id: 142, name: 'Minnesota Twins' },
  { id: 143, name: 'Philadelphia Phillies' },
  { id: 144, name: 'Atlanta Braves' },
  { id: 145, name: 'Chicago White Sox' },
  { id: 146, name: 'Miami Marlins' },
  { id: 147, name: 'New York Yankees' },
  { id: 158, name: 'Milwaukee Brewers' },
]

const s = {
  back: { color: '#58a6ff', textDecoration: 'none', fontSize: '13px', display: 'inline-block', marginBottom: '20px' },
  row: { display: 'flex', gap: '12px', marginBottom: '28px', alignItems: 'center' },
  select: {
    flex: 1, background: '#161b22', border: '1px solid #30363d', color: '#e6edf3',
    borderRadius: '6px', padding: '10px 14px', fontSize: '14px', outline: 'none',
  },
  btn: {
    background: '#238636', color: '#fff', border: 'none', borderRadius: '6px',
    padding: '10px 20px', fontSize: '14px', fontWeight: '600', cursor: 'pointer',
  },
  teamHeader: { marginBottom: '24px' },
  teamName: { fontSize: '26px', fontWeight: '700', color: '#e6edf3', marginBottom: '6px' },
  recordRow: { display: 'flex', gap: '20px', alignItems: 'center', flexWrap: 'wrap' },
  recordBig: { fontSize: '28px', fontWeight: '700', color: '#3fb950' },
  metaItem: { fontSize: '13px', color: '#8b949e' },
  metaVal: { color: '#e6edf3', fontWeight: '600' },
  streakBadge: (code) => ({
    display: 'inline-block', fontSize: '12px', fontWeight: '700', padding: '3px 8px', borderRadius: '4px',
    background: code?.startsWith('W') ? '#1f3a1f' : '#3a1f1f',
    color: code?.startsWith('W') ? '#3fb950' : '#f85149',
  }),
  section: { marginBottom: '28px' },
  sectionTitle: { fontSize: '16px', fontWeight: '600', color: '#e6edf3', marginBottom: '14px', borderBottom: '1px solid #21262d', paddingBottom: '8px' },
  splitGrid: { display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '16px' },
  splitCard: { background: '#161b22', border: '1px solid #30363d', borderRadius: '8px', padding: '16px' },
  splitTitle: { fontSize: '14px', fontWeight: '600', color: '#58a6ff', marginBottom: '12px' },
  splitRow: { display: 'flex', justifyContent: 'space-between', padding: '6px 0', borderBottom: '1px solid #21262d', fontSize: '13px' },
  splitKey: { color: '#8b949e' },
  splitVal: { color: '#e6edf3', fontWeight: '500' },
  standingsLink: { color: '#58a6ff', textDecoration: 'none', fontSize: '13px' },
  loader: { color: '#8b949e', padding: '48px', textAlign: 'center' },
  error: { color: '#f85149', padding: '24px', background: '#1f1116', borderRadius: '8px' },
  hint: { color: '#8b949e', textAlign: 'center', padding: '48px' },
}

function fmt(val, d = 3) {
  if (val == null) return '—'
  return typeof val === 'number' ? val.toFixed(d) : val
}
function pct(val) {
  if (val == null) return '—'
  return `${(val * 100).toFixed(1)}%`
}

function SplitCard({ title, split }) {
  if (!split) return (
    <div style={s.splitCard}>
      <div style={s.splitTitle}>{title}</div>
      <div style={{ color: '#8b949e', fontSize: '13px' }}>No data — run ETL to populate team splits.</div>
    </div>
  )
  const rows = [
    ['PA', split.pa],
    ['AVG', fmt(split.batting_avg)],
    ['OBP', fmt(split.on_base_pct)],
    ['SLG', fmt(split.slugging_pct)],
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

export default function TeamPage() {
  const { id: urlId } = useParams()
  const [teamId, setTeamId] = useState(urlId ? Number(urlId) : 147)
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)

  function load(tid) {
    setLoading(true)
    setError(null)
    fetch(`${API}/team/${tid}`)
      .then(r => r.ok ? r.json() : r.json().then(e => Promise.reject(e.detail || r.statusText)))
      .then(d => { setData(d); setLoading(false) })
      .catch(e => { setError(String(e)); setLoading(false) })
  }

  useEffect(() => {
    if (urlId) load(Number(urlId))
  }, [urlId])

  const teamName = data?.standing?.team_name || TEAMS.find(t => t.id === teamId)?.name || `Team ${teamId}`
  const standing = data?.standing

  return (
    <div>
      <Link to="/standings" style={s.back}>← Standings</Link>

      <div style={{ fontSize: '24px', fontWeight: '700', marginBottom: '20px' }}>Team Profile</div>

      {!urlId && (
        <div style={s.row}>
          <select style={s.select} value={teamId} onChange={e => setTeamId(Number(e.target.value))}>
            {TEAMS.map(t => <option key={t.id} value={t.id}>{t.name}</option>)}
          </select>
          <button style={s.btn} onClick={() => load(teamId)}>Load</button>
        </div>
      )}

      {loading && <div style={s.loader}>Loading…</div>}
      {error && <div style={s.error}>{error}</div>}

      {!loading && !error && !data && !urlId && (
        <div style={s.hint}>Select a team and click Load to view their stats.</div>
      )}

      {data && (
        <>
          <div style={s.teamHeader}>
            <div style={s.teamName}>{teamName}</div>
            {standing ? (
              <div style={s.recordRow}>
                <div style={s.recordBig}>
                  {standing.wins ?? '—'} – {standing.losses ?? '—'}
                </div>
                {standing.pct && (
                  <div style={s.metaItem}>
                    <span style={s.metaVal}>{standing.pct}</span> PCT
                  </div>
                )}
                {standing.division && (
                  <div style={s.metaItem}>
                    <span style={s.metaVal}>{standing.division}</span>
                    {standing.games_back && standing.games_back !== '0' && (
                      <span> · {standing.games_back} GB</span>
                    )}
                    {standing.games_back === '0' && <span> · Division Leader</span>}
                  </div>
                )}
                {standing.streak && (
                  <span style={s.streakBadge(standing.streak)}>{standing.streak}</span>
                )}
              </div>
            ) : (
              <div style={{ color: '#8b949e', fontSize: '13px', marginTop: '6px' }}>
                Standings data unavailable.
              </div>
            )}
          </div>

          <div style={s.section}>
            <div style={s.sectionTitle}>Team Splits — {data.season}</div>
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

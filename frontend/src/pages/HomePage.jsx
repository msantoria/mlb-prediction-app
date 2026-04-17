import React, { useState, useEffect } from 'react'
import { Link, useNavigate } from 'react-router-dom'

const API = '/api'

const s = {
  header: { display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '24px', flexWrap: 'wrap', gap: '12px' },
  title: { fontSize: '24px', fontWeight: '700', color: '#e6edf3' },
  datePicker: {
    background: '#161b22', border: '1px solid #30363d', color: '#e6edf3',
    borderRadius: '6px', padding: '8px 12px', fontSize: '14px', cursor: 'pointer',
  },
  grid: { display: 'grid', gap: '12px' },
  card: {
    background: '#161b22', border: '1px solid #30363d', borderRadius: '10px',
    padding: '16px 20px', cursor: 'pointer', transition: 'border-color 0.15s',
  },
  cardHover: { borderColor: '#58a6ff' },
  meta: { display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '12px', fontSize: '12px', color: '#8b949e' },
  venue: { display: 'flex', gap: '8px', alignItems: 'center' },
  statusBadge: (status) => ({
    display: 'inline-block', borderRadius: '4px', padding: '2px 7px',
    fontSize: '11px', fontWeight: '600',
    background: status === 'Final' ? '#21262d' : status?.includes('Progress') ? '#1f3a1f' : '#21262d',
    color: status === 'Final' ? '#8b949e' : status?.includes('Progress') ? '#3fb950' : '#58a6ff',
  }),
  matchupRow: {
    display: 'grid', gridTemplateColumns: '1fr auto 1fr', alignItems: 'center', gap: '12px',
  },
  team: { display: 'flex', flexDirection: 'column', gap: '3px' },
  teamName: { fontSize: '16px', fontWeight: '600', color: '#e6edf3' },
  record: { fontSize: '12px', color: '#8b949e' },
  pitcher: { fontSize: '12px', color: '#58a6ff' },
  prob: { fontSize: '26px', fontWeight: '700' },
  vs: { textAlign: 'center', fontSize: '13px', color: '#8b949e', fontWeight: '600', letterSpacing: '1px' },
  noData: { color: '#8b949e', fontSize: '14px', textAlign: 'center', padding: '48px' },
  loader: { color: '#8b949e', textAlign: 'center', padding: '48px' },
  error: { color: '#f85149', textAlign: 'center', padding: '24px', background: '#1f1116', borderRadius: '8px' },
}

function probColor(p) {
  if (p == null) return '#8b949e'
  if (p >= 0.62) return '#3fb950'
  if (p >= 0.50) return '#d29922'
  return '#f85149'
}

function formatTime(iso) {
  if (!iso) return null
  try {
    const d = new Date(iso)
    return d.toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit', timeZone: 'America/New_York' }) + ' ET'
  } catch { return null }
}

function ProbBar({ homeProb, awayProb }) {
  const hp = homeProb != null ? Math.round(homeProb * 100) : 50
  const ap = 100 - hp
  return (
    <div style={{ marginTop: '12px' }}>
      <div style={{ display: 'flex', height: '5px', borderRadius: '3px', overflow: 'hidden', background: '#21262d' }}>
        <div style={{ width: `${ap}%`, background: '#58a6ff', transition: 'width 0.4s' }} />
        <div style={{ width: `${hp}%`, background: '#3fb950', transition: 'width 0.4s' }} />
      </div>
      <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '11px', color: '#8b949e', marginTop: '3px' }}>
        <span>{ap}% away</span>
        <span>{hp}% home</span>
      </div>
    </div>
  )
}

export default function HomePage() {
  const today = new Date().toISOString().slice(0, 10)
  const [date, setDate] = useState(today)
  const [matchups, setMatchups] = useState([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const [hovered, setHovered] = useState(null)
  const navigate = useNavigate()

  useEffect(() => {
    setLoading(true)
    setError(null)
    fetch(`${API}/matchups?date=${date}`)
      .then(r => r.ok ? r.json() : Promise.reject(r.statusText))
      .then(data => { setMatchups(data); setLoading(false) })
      .catch(e => { setError(String(e)); setLoading(false) })
  }, [date])

  return (
    <div>
      <div style={s.header}>
        <h1 style={s.title}>Daily Matchups</h1>
        <input type="date" value={date} onChange={e => setDate(e.target.value)} style={s.datePicker} />
      </div>

      {loading && <div style={s.loader}>Loading matchups…</div>}
      {error && <div style={s.error}>Error: {error}</div>}
      {!loading && !error && matchups.length === 0 && (
        <div style={s.noData}>No games scheduled for {date}.</div>
      )}

      <div style={s.grid}>
        {matchups.map((m, i) => (
          <div
            key={i}
            style={{ ...s.card, ...(hovered === i ? s.cardHover : {}) }}
            onMouseEnter={() => setHovered(i)}
            onMouseLeave={() => setHovered(null)}
            onClick={() => m.game_pk && navigate(`/matchup/${m.game_pk}`)}
          >
            {/* Meta row: venue + time + status */}
            <div style={s.meta}>
              <div style={s.venue}>
                <span>{m.venue || '—'}</span>
                {m.game_time && <span>· {formatTime(m.game_time)}</span>}
              </div>
              {m.status && <span style={s.statusBadge(m.status)}>{m.status}</span>}
            </div>

            {/* Main matchup row */}
            <div style={s.matchupRow}>
              {/* Away team */}
              <div style={s.team}>
                <div style={s.teamName}>{m.away_team_name || `Team ${m.away_team_id}`}</div>
                <div style={s.record}>{m.away_team_record || ''}</div>
                <div style={s.pitcher}>
                  {m.away_pitcher_name
                    ? <Link to={`/pitcher/${m.away_pitcher_id}`} onClick={e => e.stopPropagation()} style={{ color: '#58a6ff', textDecoration: 'none' }}>
                        {m.away_pitcher_name}
                      </Link>
                    : <span style={{ color: '#8b949e' }}>TBD</span>}
                </div>
                <div style={{ ...s.prob, color: probColor(m.away_win_prob) }}>
                  {m.away_win_prob != null ? `${Math.round(m.away_win_prob * 100)}%` : '—'}
                </div>
              </div>

              <div style={s.vs}>@</div>

              {/* Home team */}
              <div style={{ ...s.team, textAlign: 'right' }}>
                <div style={s.teamName}>{m.home_team_name || `Team ${m.home_team_id}`}</div>
                <div style={s.record}>{m.home_team_record || ''}</div>
                <div style={{ ...s.pitcher, textAlign: 'right' }}>
                  {m.home_pitcher_name
                    ? <Link to={`/pitcher/${m.home_pitcher_id}`} onClick={e => e.stopPropagation()} style={{ color: '#58a6ff', textDecoration: 'none' }}>
                        {m.home_pitcher_name}
                      </Link>
                    : <span style={{ color: '#8b949e' }}>TBD</span>}
                </div>
                <div style={{ ...s.prob, color: probColor(m.home_win_prob), textAlign: 'right' }}>
                  {m.home_win_prob != null ? `${Math.round(m.home_win_prob * 100)}%` : '—'}
                </div>
              </div>
            </div>

            <ProbBar homeProb={m.home_win_prob} awayProb={m.away_win_prob} />
          </div>
        ))}
      </div>
    </div>
  )
}

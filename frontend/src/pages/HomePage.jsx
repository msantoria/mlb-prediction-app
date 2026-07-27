import React, { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { API_BASE, fetchJson, getMlbLiveDate, readCachedJson } from '../lib/api'

const API = API_BASE
const MATCHUPS_TTL_SECONDS = 120
const CALENDAR_SCHEDULE_URL = `${API}/matchups/calendar/schedule`

function useIsMobile(breakpoint = 768) {
  const getMatches = () => (typeof window !== 'undefined' ? window.innerWidth <= breakpoint : false)
  const [isMobile, setIsMobile] = useState(getMatches)

  useEffect(() => {
    if (typeof window === 'undefined') return undefined
    const onResize = () => setIsMobile(getMatches())
    window.addEventListener('resize', onResize)
    return () => window.removeEventListener('resize', onResize)
  }, [breakpoint])

  return isMobile
}

const s = {
  matchupGrid: { display: 'grid', gap: '16px', minWidth: 0 },
  card: { cursor: 'pointer', minWidth: 0 },
  slateMeta: { display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16, gap: 12, flexWrap: 'wrap', minWidth: 0 },
  slateMetaMobile: { flexDirection: 'column', alignItems: 'stretch' },
  venue: { display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap', color: 'var(--text-muted)', fontSize: 12, minWidth: 0, overflowWrap: 'anywhere' },
  matchupRow: { display: 'grid', gridTemplateColumns: 'minmax(0, 1fr) auto minmax(0, 1fr)', alignItems: 'stretch', gap: 16, minWidth: 0 },
  matchupRowMobile: { gridTemplateColumns: '1fr', gap: 10 },
  teamPanel: { border: '1px solid var(--border-subtle)', borderRadius: 'var(--radius-md)', padding: 14, background: 'rgba(7, 11, 18, 0.34)', minWidth: 0 },
  teamPanelMobile: { textAlign: 'left' },
  teamPanelRight: { textAlign: 'right' },
  teamName: { fontSize: 18, fontWeight: 850, color: 'var(--text-primary)', letterSpacing: '-0.03em', minWidth: 0, overflowWrap: 'anywhere', lineHeight: 1.16 },
  record: { fontSize: 12, color: 'var(--text-muted)', marginTop: 2, overflowWrap: 'anywhere' },
  pitcher: { fontSize: 13, color: 'var(--accent)', marginTop: 10, minHeight: 20, minWidth: 0, overflowWrap: 'anywhere' },
  prob: { fontSize: 30, fontWeight: 900, letterSpacing: '-0.06em', marginTop: 12, overflowWrap: 'anywhere' },
  vs: { display: 'grid', placeItems: 'center', color: 'var(--text-muted)', fontWeight: 900, letterSpacing: '0.18em', fontSize: 12, minWidth: 0 },
  vsMobile: { placeItems: 'start', padding: '0 2px', letterSpacing: '0.08em' },
}

function probColor(p) {
  if (p == null) return 'var(--text-muted)'
  if (p >= 0.62) return 'var(--success)'
  if (p >= 0.50) return 'var(--warning)'
  return 'var(--danger)'
}

function formatTime(iso) {
  if (!iso) return null
  try {
    const d = new Date(iso)
    return d.toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit', timeZone: 'America/New_York' }) + ' ET'
  } catch {
    return null
  }
}

function weatherLabel(weather) {
  if (!weather) return null
  const pieces = []
  if (weather.temp_f != null) pieces.push(`${weather.temp_f}°F`)
  if (weather.condition) pieces.push(weather.condition)
  if (weather.wind) pieces.push(weather.wind)
  return pieces.length ? pieces.join(' · ') : null
}

function dateBucket(date) {
  const today = getMlbLiveDate()
  const todayDate = new Date(`${today}T12:00:00Z`)
  const targetDate = new Date(`${date}T12:00:00Z`)
  const diffDays = Math.round((targetDate - todayDate) / 86400000)
  if (diffDays === -1) return 'yesterday'
  if (diffDays === 0) return 'today'
  if (diffDays === 1) return 'tomorrow'
  return null
}

function scheduleRowToMatchup(g, date) {
  return {
    game_pk: g.game_pk,
    game_date: date,
    game_time: g.game_time || g.game_date,
    venue: g.venue,
    status: g.status,
    home_team_id: g.home_team_id,
    away_team_id: g.away_team_id,
    home_team_name: g.home_team_name,
    away_team_name: g.away_team_name,
    home_pitcher_id: g.home_pitcher?.id,
    away_pitcher_id: g.away_pitcher?.id,
    home_pitcher_name: g.home_pitcher?.name,
    away_pitcher_name: g.away_pitcher?.name,
    home_team_record: 'Record pending',
    away_team_record: 'Record pending',
    home_win_prob: null,
    away_win_prob: null,
    probability_source: 'schedule_calendar_fallback_not_model_probability',
    frontend_fallback_source: '/matchups/calendar/schedule',
  }
}

async function loadScheduleFallback(date) {
  const calendar = await fetchJson(CALENDAR_SCHEDULE_URL, { ttlSeconds: MATCHUPS_TTL_SECONDS })
  const bucket = dateBucket(date)
  const source = bucket ? calendar?.[bucket] : null
  if (!source || !Array.isArray(source.games)) return []
  return source.games.map(game => scheduleRowToMatchup(game, source.date || date))
}

function ProbBar({ homeProb, awayProb }) {
  const hp = homeProb != null ? Math.round(homeProb * 100) : 50
  const ap = awayProb != null ? Math.round(awayProb * 100) : 100 - hp
  return (
    <div style={{ marginTop: 14, minWidth: 0 }}>
      <div style={{ display: 'flex', height: 6, borderRadius: 999, overflow: 'hidden', background: 'rgba(148, 163, 184, 0.14)' }}>
        <div style={{ width: `${ap}%`, background: 'linear-gradient(90deg, #5aa7ff, #7bbcff)', transition: 'width 0.4s' }} />
        <div style={{ width: `${hp}%`, background: 'linear-gradient(90deg, #41d695, #8ee8bd)', transition: 'width 0.4s' }} />
      </div>
      <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8, fontSize: 11, color: 'var(--text-muted)', marginTop: 5, flexWrap: 'wrap' }}>
        <span>{awayProb != null ? `${Math.round(awayProb * 100)}% Away` : 'Away pending'}</span>
        <span>{homeProb != null ? `${Math.round(homeProb * 100)}% Home` : 'Home pending'}</span>
      </div>
    </div>
  )
}

function statusClass(status) {
  const value = String(status || '').toLowerCase()
  if (value.includes('final')) return 'success'
  if (value.includes('progress') || value.includes('live')) return 'warning'
  return ''
}

function openMatchupDetail(gamePk) {
  if (!gamePk) return
  window.location.href = `/matchup/${gamePk}`
}

export default function HomePage() {
  const isMobile = useIsMobile()
  const today = getMlbLiveDate()
  const [date, setDate] = useState(today)
  const initialMatchupsUrl = `${API}/matchups?date=${today}`
  const [matchups, setMatchups] = useState(() => {
    const cached = readCachedJson(initialMatchupsUrl, MATCHUPS_TTL_SECONDS)
    return Array.isArray(cached) ? cached : []
  })
  const [loading, setLoading] = useState(matchups.length === 0)
  const [error, setError] = useState(null)

  useEffect(() => {
    let cancelled = false
    const url = `${API}/matchups?date=${date}`
    const cached = readCachedJson(url, MATCHUPS_TTL_SECONDS)
    if (Array.isArray(cached)) {
      setMatchups(cached)
      setLoading(false)
    } else {
      setLoading(true)
    }
    setError(null)
    fetchJson(url, { ttlSeconds: MATCHUPS_TTL_SECONDS })
      .then(data => {
        if (cancelled) return
        setMatchups(Array.isArray(data) ? data : [])
        setLoading(false)
      })
      .catch(async e => {
        if (cancelled) return
        try {
          const fallback = await loadScheduleFallback(date)
          if (cancelled) return
          setMatchups(fallback)
          setError(fallback.length ? null : String(e))
        } catch {
          if (cancelled) return
          setError(String(e))
          setMatchups([])
        } finally {
          if (!cancelled) setLoading(false)
        }
      })
    return () => { cancelled = true }
  }, [date])

  return (
    <div>
      <header className="page-header">
        <div>
          <p className="page-kicker">Live Slate</p>
          <h1 className="page-title">Daily Matchups</h1>
          <p className="page-subtitle">Validated MLB schedule, probable starters, model win probabilities, and weather context in one production slate.</p>
        </div>
        <div className="control-row">
          <span className="status-badge success">Live Data</span>
          <input className="input-control" type="date" value={date} onChange={e => setDate(e.target.value)} />
        </div>
      </header>

      {loading && (
        <div className="state-panel">
          <div className="skeleton-line" style={{ maxWidth: 420, margin: '0 auto 12px' }} />
          <div className="skeleton-line" style={{ maxWidth: 300, margin: '0 auto' }} />
        </div>
      )}
      {error && <div className="state-panel error">Matchup data unavailable: {error}</div>}
      {!loading && !error && matchups.length === 0 && (
        <div className="state-panel">No games are scheduled for {date}.</div>
      )}

      <div style={s.matchupGrid}>
        {matchups.map((m, i) => {
          const awayPanelStyle = {
            ...s.teamPanel,
            ...(isMobile ? s.teamPanelMobile : {}),
          }
          const homePanelStyle = {
            ...s.teamPanel,
            ...(!isMobile ? s.teamPanelRight : s.teamPanelMobile),
          }
          return (
            <article
              key={m.game_pk || i}
              className="pro-card pro-card-hover card-pad responsive-matchup-card"
              style={s.card}
              onClick={() => openMatchupDetail(m.game_pk)}
            >
              <div style={{ ...s.slateMeta, ...(isMobile ? s.slateMetaMobile : {}) }}>
                <div style={s.venue}>
                  <span>{m.venue || 'Venue pending'}</span>
                  {m.game_time && <span>· {formatTime(m.game_time)}</span>}
                  {weatherLabel(m.weather) && <span>· {weatherLabel(m.weather)}</span>}
                </div>
                {m.status && <span className={`status-badge ${statusClass(m.status)}`}>{m.status}</span>}
              </div>

              <div style={{ ...s.matchupRow, ...(isMobile ? s.matchupRowMobile : {}) }}>
                <div style={awayPanelStyle}>
                  <div style={s.teamName}>{m.away_team_name || `Team ${m.away_team_id}`}</div>
                  <div style={s.record}>{m.away_team_record || 'Record pending'}</div>
                  <div style={s.pitcher}>
                    {m.away_pitcher_name
                      ? <Link to={`/pitcher/${m.away_pitcher_id}`} onClick={e => e.stopPropagation()} style={{ color: 'var(--accent)', textDecoration: 'none', fontWeight: 750, overflowWrap: 'anywhere' }}>
                          {m.away_pitcher_name}
                        </Link>
                      : <span className="status-badge warning">Pitcher Pending</span>}
                  </div>
                  <div style={{ ...s.prob, color: probColor(m.away_win_prob) }}>
                    {m.away_win_prob != null ? `${Math.round(m.away_win_prob * 100)}%` : 'Pending'}
                  </div>
                </div>

                <div style={{ ...s.vs, ...(isMobile ? s.vsMobile : {}) }}>AT</div>

                <div style={homePanelStyle}>
                  <div style={s.teamName}>{m.home_team_name || `Team ${m.home_team_id}`}</div>
                  <div style={s.record}>{m.home_team_record || 'Record pending'}</div>
                  <div style={{ ...s.pitcher, textAlign: isMobile ? 'left' : 'right' }}>
                    {m.home_pitcher_name
                      ? <Link to={`/pitcher/${m.home_pitcher_id}`} onClick={e => e.stopPropagation()} style={{ color: 'var(--accent)', textDecoration: 'none', fontWeight: 750, overflowWrap: 'anywhere' }}>
                          {m.home_pitcher_name}
                        </Link>
                      : <span className="status-badge warning">Pitcher Pending</span>}
                  </div>
                  <div style={{ ...s.prob, color: probColor(m.home_win_prob), textAlign: isMobile ? 'left' : 'right' }}>
                    {m.home_win_prob != null ? `${Math.round(m.home_win_prob * 100)}%` : 'Pending'}
                  </div>
                </div>
              </div>

              <ProbBar homeProb={m.home_win_prob} awayProb={m.away_win_prob} />
            </article>
          )
        })}
      </div>
    </div>
  )
}

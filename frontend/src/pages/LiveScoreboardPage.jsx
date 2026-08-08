import React, { useState, useEffect, useRef } from 'react'
import { Link } from 'react-router-dom'
import { API_BASE, getMlbLiveDate, addIsoDays } from '../lib/api'

const REFRESH_INTERVAL_MS = 30_000

const STATUS_COLORS = {
  Live: '#3fb950',
  Final: '#8b949e',
  Scheduled: '#58a6ff',
  Preview: '#58a6ff',
  'Pre-Game': '#58a6ff',
  Warmup: '#d29922',
  Delayed: '#d29922',
  Postponed: '#f85149',
  Suspended: '#f85149',
  'Status Pending': '#8b949e',
}

function normalizeGameStatus(game) {
  const abstract = game?.status_abstract || game?.abstractGameState || game?.status?.abstractGameState
  const detail = game?.status_detail || game?.detailedState || game?.status?.detailedState
  const coded = game?.codedGameState || game?.status?.codedGameState
  const raw = `${abstract || ''} ${detail || ''} ${coded || ''}`.toLowerCase()

  if (raw.includes('final') || raw.includes('game over') || raw.includes('completed early') || coded === 'F') {
    return { abstract: 'Final', label: 'Final' }
  }

  if (raw.includes('postponed')) {
    return { abstract: 'Postponed', label: 'Postponed' }
  }

  if (raw.includes('suspended')) {
    return { abstract: 'Suspended', label: 'Suspended' }
  }

  if (raw.includes('delay')) {
    return { abstract: 'Delayed', label: detail || 'Delayed' }
  }

  if (abstract === 'Live' || ['I', 'M', 'N'].includes(coded) || raw.includes('progress')) {
    if (game?.inning) {
      return {
        abstract: 'Live',
        label: `${game?.inning_state || ''} ${game.inning}`.trim(),
      }
    }

    return {
      abstract: 'Live',
      label: detail && detail !== 'In Progress' ? detail : 'Live',
    }
  }

  if (detail === 'Warmup' || detail === 'Warm Up') {
    return { abstract: 'Warmup', label: 'Warmup' }
  }

  if (detail === 'Pre-Game') {
    return { abstract: 'Scheduled', label: 'Pre-Game' }
  }

  if (abstract === 'Preview' || ['S', 'P'].includes(coded)) {
    return { abstract: 'Scheduled', label: detail || 'Scheduled' }
  }

  const start = game?.game_datetime || game?.gameDate || game?.start_time
  if (start) {
    const minutesUntilStart = (new Date(start).getTime() - Date.now()) / 60000

    if (minutesUntilStart <= 30 && minutesUntilStart >= 0) {
      return { abstract: 'Warmup', label: 'Warmup' }
    }

    if (minutesUntilStart < 0 && minutesUntilStart >= -240) {
      return { abstract: 'Live', label: 'Live' }
    }

    if (minutesUntilStart < -240) {
      return { abstract: 'Final', label: 'Status Pending' }
    }
  }

  return { abstract: 'Scheduled', label: detail || abstract || 'Scheduled' }
}

function statusColor(abstract) {
  return STATUS_COLORS[abstract] || '#8b949e'
}

function isUpcomingStatus(game) {
  const normalized = normalizeGameStatus(game)
  return normalized.abstract === 'Scheduled' || normalized.abstract === 'Warmup'
}

function WeatherBadge({ weather }) {
  if (!weather) return null
  const parts = [weather.condition, weather.temp_f ? `${weather.temp_f}°F` : null, weather.wind].filter(Boolean)
  if (!parts.length) return null
  return (
    <span style={{ fontSize: '11px', color: '#8b949e' }}>{parts.join(' · ')}</span>
  )
}

function ProbablePitcher({ label, pitcher }) {
  if (!pitcher) return <span style={{ color: '#8b949e', fontSize: '12px' }}>{label}: TBD</span>
  return (
    <span style={{ fontSize: '12px', color: '#c9d1d9' }}>
      <span style={{ color: '#8b949e' }}>{label}: </span>
      <Link to={`/pitcher/${pitcher.id}`} style={{ color: '#58a6ff', textDecoration: 'none' }}>
        {pitcher.name}
      </Link>
    </span>
  )
}

function DecisionLine({ decisions }) {
  if (!decisions) return null
  const parts = []
  if (decisions.winner) parts.push(`W: ${decisions.winner.name}`)
  if (decisions.loser) parts.push(`L: ${decisions.loser.name}`)
  if (decisions.save) parts.push(`S: ${decisions.save.name}`)
  if (!parts.length) return null
  return (
    <div style={{ fontSize: '11px', color: '#8b949e', marginTop: '4px' }}>
      {parts.join('  ·  ')}
    </div>
  )
}

function GameCard({ game }) {
  const normalizedStatus = normalizeGameStatus(game)
  const color = statusColor(normalizedStatus.abstract)
  const label = normalizedStatus.label
  const isLive = normalizedStatus.abstract === 'Live'
  const isFinal = normalizedStatus.abstract === 'Final'
  const showProbables = !isFinal && !isLive
  const destination = isFinal ? `/final/${game.game_pk}` : `/live/${game.game_pk}`

  return (
    <Link to={destination} style={{ textDecoration: 'none' }}>
      <div style={{
        background: '#0d1117',
        border: `1px solid ${isLive ? '#3fb950' : '#30363d'}`,
        borderRadius: '8px',
        padding: '16px',
        cursor: 'pointer',
        transition: 'border-color 0.15s',
      }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '10px' }}>
          <span style={{
            fontSize: '11px',
            fontWeight: '600',
            color: color,
            background: `${color}22`,
            border: `1px solid ${color}44`,
            borderRadius: '4px',
            padding: '2px 7px',
          }}>
            {isLive && <span style={{ marginRight: '4px' }}>●</span>}
            {label}
          </span>
          <span style={{ fontSize: '11px', color: '#8b949e' }}>{game.venue || ''}</span>
        </div>

        <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
          {[
            { side: game.away },
            { side: game.home },
          ].map(({ side }) => (
            <div key={side.team_id} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <span style={{ fontSize: '15px', fontWeight: '600', color: '#e6edf3' }}>
                {side.abbreviation || side.name}
              </span>
              <span style={{
                fontSize: '22px',
                fontWeight: '700',
                color: (isFinal || isLive) ? '#e6edf3' : '#484f58',
                minWidth: '28px',
                textAlign: 'right',
              }}>
                {side.score != null ? side.score : '—'}
              </span>
            </div>
          ))}
        </div>

        {isLive && game.outs != null && (
          <div style={{ marginTop: '8px', display: 'flex', gap: '4px', alignItems: 'center' }}>
            <span style={{ fontSize: '11px', color: '#8b949e', marginRight: '4px' }}>Outs:</span>
            {[0, 1, 2].map(i => (
              <span key={i} style={{
                width: '8px', height: '8px', borderRadius: '50%',
                background: i < game.outs ? '#d29922' : '#21262d',
                border: '1px solid #30363d',
                display: 'inline-block',
              }} />
            ))}
          </div>
        )}

        {showProbables && (
          <div style={{ marginTop: '10px', display: 'flex', flexDirection: 'column', gap: '3px' }}>
            <ProbablePitcher label={game.away.abbreviation} pitcher={game.away.probable_pitcher} />
            <ProbablePitcher label={game.home.abbreviation} pitcher={game.home.probable_pitcher} />
          </div>
        )}

        {isFinal && <DecisionLine decisions={game.decisions} />}

        {game.weather && (
          <div style={{ marginTop: '8px' }}>
            <WeatherBadge weather={game.weather} />
          </div>
        )}
      </div>
    </Link>
  )
}

export default function LiveScoreboardPage() {
  const [date, setDate] = useState(getMlbLiveDate())
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [lastRefresh, setLastRefresh] = useState(null)
  const timerRef = useRef(null)

  function fetchScoreboard(selectedDate = date) {
    fetch(`${API_BASE}/live/scoreboard?date=${selectedDate}`)
      .then(r => r.ok ? r.json() : r.json().then(e => Promise.reject(e.detail || r.statusText)))
      .then(d => {
        setData(d)
        setLastRefresh(new Date())
        setLoading(false)
        setError(null)
      })
      .catch(e => {
        setError(String(e))
        setLoading(false)
      })
  }

  useEffect(() => {
    fetchScoreboard(date)
    timerRef.current = setInterval(() => fetchScoreboard(date), REFRESH_INTERVAL_MS)
    return () => {
      if (timerRef.current) {
        clearInterval(timerRef.current)
      }
    }
  }, [date])

  if (loading) return <div style={{ color: '#8b949e', padding: '40px' }}>Loading scoreboard…</div>
  if (error) return <div style={{ color: '#f85149', padding: '40px' }}>Error: {error}</div>

  const games = data?.games || []
  const liveGames = games.filter(g => normalizeGameStatus(g).abstract === 'Live')
  const upcomingGames = games.filter(isUpcomingStatus)
  const finalGames = games.filter(g => normalizeGameStatus(g).abstract === 'Final')

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '24px', flexWrap: 'wrap', gap: '12px' }}>
        <div>
          <h1 style={{ margin: 0, fontSize: '22px', fontWeight: '700', color: '#e6edf3' }}>
            Live Scoreboard
          </h1>
          <div style={{ fontSize: '13px', color: '#8b949e', marginTop: '4px' }}>
            {date} · {games.length} games
            {liveGames.length > 0 && (
              <span style={{ color: '#3fb950', marginLeft: '8px' }}>● {liveGames.length} live</span>
            )}
          </div>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px', flexWrap: 'wrap' }}>
          {lastRefresh && (
            <span style={{ fontSize: '11px', color: '#8b949e' }}>
              Updated {lastRefresh.toLocaleTimeString()}
            </span>
          )}
          <button
            onClick={() => setDate(addIsoDays(date, -1))}
            style={{
              background: '#21262d', border: '1px solid #30363d', color: '#e6edf3',
              borderRadius: '6px', padding: '6px 10px', cursor: 'pointer', fontSize: '13px',
            }}
          >
            ←
          </button>
          <input
            type="date"
            value={date}
            onChange={e => setDate(e.target.value)}
            style={{
              background: '#0d1117', border: '1px solid #30363d', color: '#e6edf3',
              borderRadius: '6px', padding: '6px 10px', fontSize: '13px',
            }}
          />
          <button
            onClick={() => setDate(getMlbLiveDate())}
            style={{
              background: '#238636', border: '1px solid #2ea043', color: '#fff',
              borderRadius: '6px', padding: '6px 10px', cursor: 'pointer', fontSize: '13px',
            }}
          >
            Today
          </button>
          <button
            onClick={() => setDate(addIsoDays(date, 1))}
            style={{
              background: '#21262d', border: '1px solid #30363d', color: '#e6edf3',
              borderRadius: '6px', padding: '6px 10px', cursor: 'pointer', fontSize: '13px',
            }}
          >
            →
          </button>
          <button
            onClick={() => fetchScoreboard(date)}
            style={{
              background: '#21262d', border: '1px solid #30363d', color: '#e6edf3',
              borderRadius: '6px', padding: '6px 14px', cursor: 'pointer', fontSize: '13px',
            }}
          >
            Refresh
          </button>
        </div>
      </div>

      {games.length === 0 && (
        <div style={{ color: '#8b949e', textAlign: 'center', padding: '60px 0' }}>
          No games scheduled for {date}.
        </div>
      )}

      {liveGames.length > 0 && (
        <section style={{ marginBottom: '32px' }}>
          <h2 style={{ fontSize: '13px', fontWeight: '600', color: '#3fb950', textTransform: 'uppercase', letterSpacing: '0.08em', marginBottom: '12px' }}>
            ● In Progress
          </h2>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(220px, 1fr))', gap: '12px' }}>
            {liveGames.map(g => <GameCard key={g.game_pk} game={g} />)}
          </div>
        </section>
      )}

      {upcomingGames.length > 0 && (
        <section style={{ marginBottom: '32px' }}>
          <h2 style={{ fontSize: '13px', fontWeight: '600', color: '#8b949e', textTransform: 'uppercase', letterSpacing: '0.08em', marginBottom: '12px' }}>
            Upcoming
          </h2>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(220px, 1fr))', gap: '12px' }}>
            {upcomingGames.map(g => <GameCard key={g.game_pk} game={g} />)}
          </div>
        </section>
      )}

      {finalGames.length > 0 && (
        <section>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12, marginBottom: 12 }}>
            <h2 style={{ fontSize: '13px', fontWeight: '600', color: '#8b949e', textTransform: 'uppercase', letterSpacing: '0.08em', margin: 0 }}>Final</h2>
            <Link to={`/final?date=${date}`} style={{ color: '#58a6ff', fontSize: 12, textDecoration: 'none', fontWeight: 700 }}>Completed-game review →</Link>
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(220px, 1fr))', gap: '12px' }}>
            {finalGames.map(g => <GameCard key={g.game_pk} game={g} />)}
          </div>
        </section>
      )}
    </div>
  )
}

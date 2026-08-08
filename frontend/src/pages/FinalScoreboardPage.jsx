import React, { useEffect, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { API_BASE, addIsoDays, getMlbToday } from '../lib/api'

function yesterday() {
  return addIsoDays(getMlbToday(), -1)
}

function GameCard({ game }) {
  return (
    <Link to={`/final/${game.game_pk}`} className="final-game-card">
      <div className="final-game-card-header">
        <span className="status-badge neutral">Final</span>
        <span>{game.venue || 'MLB'}</span>
      </div>
      {[game.away, game.home].map(team => (
        <div className="final-game-team" key={team?.team_id || team?.name}>
          <span>{team?.abbreviation || team?.name || 'Team'}</span>
          <strong>{team?.score ?? '—'}</strong>
        </div>
      ))}
      {game.summary && <p className="final-game-summary">{game.summary}</p>}
      <span className="final-game-open">Full box score →</span>
    </Link>
  )
}

export default function FinalScoreboardPage() {
  const [searchParams] = useSearchParams()
  const requestedDate = searchParams.get('date')
  const [date, setDate] = useState(/^\d{4}-\d{2}-\d{2}$/.test(requestedDate || '') ? requestedDate : yesterday())
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  useEffect(() => {
    const controller = new AbortController()
    setLoading(true)
    setError(null)
    fetch(`${API_BASE}/final?date=${date}`, { signal: controller.signal })
      .then(async response => {
        if (response.ok) return response.json()
        const body = await response.json().catch(() => ({}))
        throw new Error(body.detail || response.statusText)
      })
      .then(payload => {
        setData(payload)
        setLoading(false)
      })
      .catch(reason => {
        if (reason.name === 'AbortError') return
        setError(String(reason.message || reason))
        setLoading(false)
      })
    return () => controller.abort()
  }, [date])

  const games = data?.games || []
  return (
    <div>
      <header className="page-header final-page-header">
        <div>
          <p className="page-kicker" style={{ textAlign: 'left' }}>Completed games</p>
          <h1 className="page-title" style={{ textAlign: 'left' }}>Final</h1>
          <p className="page-subtitle" style={{ textAlign: 'left', marginLeft: 0 }}>
            Permanent box scores, every participant, scoring context, and a concise game review.
          </p>
        </div>
        <div className="final-date-controls">
          <button className="btn secondary" onClick={() => setDate(addIsoDays(date, -1))} aria-label="Previous day">←</button>
          <input type="date" value={date} onChange={event => setDate(event.target.value)} />
          <button className="btn secondary" onClick={() => setDate(yesterday())}>Yesterday</button>
          <button className="btn secondary" onClick={() => setDate(addIsoDays(date, 1))} aria-label="Next day">→</button>
        </div>
      </header>

      <div className="final-page-meta">
        <span>{date}</span>
        <span>{games.length} completed game{games.length === 1 ? '' : 's'}</span>
        {data?.snapshot_status?.snapshotted > 0 && (
          <span>{data.snapshot_status.snapshotted} new snapshot{data.snapshot_status.snapshotted === 1 ? '' : 's'}</span>
        )}
      </div>

      {loading && <section className="state-panel">Building the completed-game review…</section>}
      {error && <section className="state-panel error">Final games could not be loaded: {error}</section>}
      {!loading && !error && games.length === 0 && (
        <section className="state-panel">No completed games are available for {date}.</section>
      )}
      {!loading && !error && games.length > 0 && (
        <section className="final-game-grid">
          {games.map(game => <GameCard key={game.game_pk} game={game} />)}
        </section>
      )}
    </div>
  )
}

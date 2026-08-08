import React, { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { API_BASE } from '../lib/api'

function value(input) {
  return input === undefined || input === null || input === '' ? '—' : String(input)
}

function DataTable({ headers, rows, renderRow, label, variant = 'standard' }) {
  return (
    <div className="final-table-scroll" role="region" aria-label={label} tabIndex="0">
      <table className={`final-table final-table-${variant}`}>
        <thead><tr>{headers.map(header => <th key={header}>{header}</th>)}</tr></thead>
        <tbody>
          {rows.map((row, index) => (
            <tr key={row.id || index} className={row.is_substitute ? 'is-substitute' : ''}>
              {renderRow(row).map((cell, cellIndex) => <td key={cellIndex}>{cell}</td>)}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function Linescore({ data }) {
  if (!data) return null
  const innings = data.innings || []
  const rows = [
    { side: 'away', label: data.away_team || 'Away' },
    { side: 'home', label: data.home_team || 'Home' },
  ]
  return (
    <section className="final-panel">
      <div className="final-section-title">Linescore</div>
      <DataTable
        label="Game linescore"
        variant="linescore"
        headers={['Team', ...innings.map(inning => inning.num), 'R', 'H', 'E', 'LOB']}
        rows={rows}
        renderRow={row => [
          row.label,
          ...innings.map(inning => value(inning[`${row.side}_runs`])),
          value(data.totals?.[row.side]?.runs),
          value(data.totals?.[row.side]?.hits),
          value(data.totals?.[row.side]?.errors),
          value(data.totals?.[row.side]?.left_on_base),
        ]}
      />
      <div className="final-decisions">
        {data.decisions?.winner && <span><strong>W</strong> {data.decisions.winner.name}</span>}
        {data.decisions?.loser && <span><strong>L</strong> {data.decisions.loser.name}</span>}
        {data.decisions?.save && <span><strong>S</strong> {data.decisions.save.name}</span>}
      </div>
    </section>
  )
}

function TeamBoxScore({ team, label }) {
  const batters = team?.batters || []
  const pitchers = team?.pitchers || []
  return (
    <section className="final-team-box">
      <header className="final-team-heading">
        <div><span>{label}</span><h2>{team?.name || label}</h2></div>
        <div>{batters.length} batters · {pitchers.length} pitchers</div>
      </header>
      <div className="final-section-title">Batting</div>
      <DataTable
        label={`${team?.name || label} batting box score`}
        variant="batting"
        headers={['#', 'Batter', 'POS', 'AB', 'R', 'H', 'RBI', 'HR', 'BB', 'K', 'AVG', 'OPS']}
        rows={batters}
        renderRow={batter => [
          batter.batting_order_slot || '',
          <span className="final-player-name"><Link to={`/batter/${batter.id}`}>{batter.name}</Link>{batter.entry_label && <small>{batter.entry_label}</small>}</span>,
          value(batter.position), value(batter.ab), value(batter.r), value(batter.h), value(batter.rbi),
          value(batter.hr), value(batter.bb), value(batter.k), value(batter.avg), value(batter.ops),
        ]}
      />
      <div className="final-section-title final-pitching-title">Pitching</div>
      <DataTable
        label={`${team?.name || label} pitching box score`}
        variant="pitching"
        headers={['Pitcher', 'IP', 'H', 'R', 'ER', 'BB', 'K', 'HR', 'PC-ST', 'ERA']}
        rows={pitchers}
        renderRow={pitcher => [
          <Link to={`/pitcher/${pitcher.id}`}>{pitcher.name}</Link>, value(pitcher.ip), value(pitcher.h),
          value(pitcher.r), value(pitcher.er), value(pitcher.bb), value(pitcher.k), value(pitcher.hr),
          pitcher.pitches != null ? `${pitcher.pitches}-${pitcher.strikes ?? '?'}` : '—', value(pitcher.era),
        ]}
      />
    </section>
  )
}

function ScoringPlays({ plays }) {
  if (!plays?.length) return null
  return (
    <section className="final-panel">
      <div className="final-section-title">Scoring plays</div>
      <div className="final-scoring-list">
        {plays.map((play, index) => (
          <div key={`${play.inning}-${index}`}>
            <span>{play.half_inning === 'top' ? 'Top' : 'Bottom'} {play.inning}</span>
            <p>{play.description || play.event}</p>
            <strong>{value(play.away_score)}–{value(play.home_score)}</strong>
          </div>
        ))}
      </div>
    </section>
  )
}

export default function FinalGamePage() {
  const { game_pk } = useParams()
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  useEffect(() => {
    const controller = new AbortController()
    fetch(`${API_BASE}/final/game/${game_pk}`, { signal: controller.signal })
      .then(async response => {
        if (response.ok) return response.json()
        const body = await response.json().catch(() => ({}))
        throw new Error(body.detail || response.statusText)
      })
      .then(payload => { setData(payload); setLoading(false) })
      .catch(reason => {
        if (reason.name === 'AbortError') return
        setError(String(reason.message || reason)); setLoading(false)
      })
    return () => controller.abort()
  }, [game_pk])

  if (loading) return <section className="state-panel">Loading the final box score…</section>
  if (error) return <section className="state-panel error">Final box score could not be loaded: {error}</section>

  return (
    <div className="final-detail-page">
      <Link to={`/final?date=${data.official_date || ''}`} className="final-back-link">← Final games</Link>
      <header className="final-score-hero">
        <div className="final-score-team"><span>{data.away?.abbreviation || 'Away'}</span><h1>{data.away?.name}</h1><strong>{value(data.away?.score)}</strong></div>
        <div className="final-score-state"><span>Final</span><small>{data.official_date}{data.venue ? ` · ${data.venue}` : ''}</small></div>
        <div className="final-score-team is-home"><span>{data.home?.abbreviation || 'Home'}</span><h1>{data.home?.name}</h1><strong>{value(data.home?.score)}</strong></div>
      </header>

      {data.summary && <section className="final-summary-panel"><span>Game review</span><p>{data.summary}</p></section>}
      <Linescore data={data.linescore} />
      <TeamBoxScore team={data.boxscore?.away} label="Away" />
      <TeamBoxScore team={data.boxscore?.home} label="Home" />
      <ScoringPlays plays={data.scoring_plays} />
      <section className="final-panel final-abs-panel">
        <div className="final-section-title">ABS tracker</div>
        <p>{data.abs_tracker?.available ? data.abs_tracker.summary : data.abs_tracker?.reason_unavailable || 'ABS data is not available for this game.'}</p>
      </section>
    </div>
  )
}

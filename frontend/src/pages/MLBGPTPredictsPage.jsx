import React, { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { API_BASE, getMlbToday } from '../lib/api'
import './MLBGPTPredictsPage.css'

const fmt = (value, digits = 2) => value == null ? '—' : Number(value).toFixed(digits)
const percent = value => value == null ? '—' : `${(value * 100).toFixed(1)}%`
const labels = { hits: 'Hits', total_bases: 'Total bases', home_runs: 'Home runs', strikeouts: 'Strikeouts' }
const tabs = ['Confirmed lineup', 'Shortlist', 'Baseline board', 'Games', 'Results & drivers', 'Model health']
const driverLabel = value => String(value || '').replaceAll('_', ' ')
const stageLabel = row => row.prediction_stage_label || (row.prediction_stage === 'confirmed_lineup' ? 'Confirmed Lineup Prediction' : 'Model Projection Baseline')

function BookContext({ markets }) {
  if (!markets?.length) return <small>No captured player market</small>
  return <div>{markets.slice(0, 2).map((market, index) => <small key={`${market.market}-${market.selection}-${index}`}>
    {market.book}: {market.selection} {fmt(market.line, 1)} ({market.price > 0 ? '+' : ''}{fmt(market.price, 0)}) · line gap {market.line_gap > 0 ? '+' : ''}{fmt(market.line_gap)}
  </small>)}</div>
}

function Detail({ row, metric, onClose }) {
  const prediction = row.predictions?.[metric] || {}
  const board = row.decision_board?.[metric] || {}
  const distribution = prediction.distribution || row.baseline_distributions?.[metric]
  return <section className="predicts-detail" aria-label={`${row.player_name} prediction details`}>
    <div className="predicts-heading"><div><span className={`predicts-stage ${row.prediction_stage}`}>{stageLabel(row)}</span><h2>{row.player_name} · {labels[metric]}</h2></div><button onClick={onClose}>Close details</button></div>
    <p>{row.team} vs {row.opponent} · {row.batting_order ? `Batting ${row.batting_order}` : row.lineup_status || 'Lineup status unavailable'} · {row.locked ? 'Pregame record locked' : 'Updating before first pitch'}</p>
    <div className="predicts-summary-grid">
      <article><span>Model Projection</span><strong>{fmt(row.baseline?.[metric])}</strong><small>Original numerical baseline</small></article>
      <article><span>MLBGPT line</span><strong>{fmt(board.mlbgpt_line)}</strong><small>{board.line_authority === 'validated_residual_model' ? 'Validated residual adjustment' : 'Baseline retained—no proven adjustment yet'}</small></article>
      <article><span>Convergence</span><strong>{fmt(board.convergence_score, 0)}</strong><small>{board.supporting_signals || 0} supporting · {board.opposing_signals || 0} opposing</small></article>
      <article><span>Residual model</span><strong>{prediction.status === 'ready' ? `${prediction.expected_residual > 0 ? '+' : ''}${fmt(prediction.expected_residual)}` : 'Not active'}</strong><small>{prediction.status === 'ready' ? `P(over baseline) ${percent(prediction.probability_over_baseline)}` : 'Requires demonstrated holdout improvement'}</small></article>
    </div>
    <h3>What drives this ranking</h3>
    {board.drivers?.length ? <div className="predicts-driver-list">{board.drivers.map(item => <div key={item.driver}><span>{driverLabel(item.driver)}</span><strong className={item.contribution >= 0 ? 'positive' : 'negative'}>{item.contribution >= 0 ? '+' : ''}{fmt(item.contribution)}</strong><small>raw {fmt(item.raw)} · slate z {item.z_score >= 0 ? '+' : ''}{fmt(item.z_score)}</small></div>)}</div> : <p>No independent evidence was available for this snapshot.</p>}
    <h3>Book comparison</h3><BookContext markets={board.book_markets} />
    <h3>Projection range</h3><p>Median {fmt(distribution?.median)} · 10th–90th percentile {fmt(distribution?.p10)}–{fmt(distribution?.p90)} · P(1+) {percent(distribution?.p1_plus)} · P(2+) {percent(distribution?.p2_plus)}</p>
    {row.outcome && <p className="predicts-result">Final: {fmt(row.outcome.metrics?.[metric]?.actual)} · Result vs baseline: {row.outcome.metrics?.[metric]?.result || 'unavailable'} · <Link to={`/final/${row.game_pk}`}>Open Final</Link></p>}
    <p className="predicts-muted">Frozen {new Date(row.as_of).toLocaleString()} · <Link to={`/models/projections?date=${row.date}`}>Open Model Projections</Link></p>
  </section>
}

export default function MLBGPTPredictsPage() {
  const [date, setDate] = useState(getMlbToday())
  const [tab, setTab] = useState('Confirmed lineup')
  const [metric, setMetric] = useState('total_bases')
  const [data, setData] = useState(null)
  const [analysis, setAnalysis] = useState(null)
  const [error, setError] = useState(null)
  const [loading, setLoading] = useState(true)
  const [selected, setSelected] = useState(null)
  useEffect(() => {
    const controller = new AbortController()
    setLoading(true); setError(null); setSelected(null)
    const path = tab === 'Model health' ? '/predicts/model-health' : tab === 'Results & drivers' ? `/predicts/backtest?start=${date}&end=${date}` : `/predicts?date=${date}`
    fetch(`${API_BASE}${path}`, { signal: controller.signal, cache: 'no-store' }).then(async response => {
      const body = await response.json(); if (!response.ok) throw new Error(body.detail || 'Could not load predictions'); return body
    }).then(body => { if (tab === 'Model health' || tab === 'Results & drivers') setAnalysis(body); else setData(body) })
      .catch(err => { if (err.name !== 'AbortError') setError(err.message) })
      .finally(() => { if (!controller.signal.aborted) setLoading(false) })
    return () => controller.abort()
  }, [date, tab])
  const rows = useMemo(() => (data?.records || []).filter(row => {
    const board = row.decision_board?.[metric]
    if (!board || row.baseline?.[metric] == null) return false
    if (tab === 'Confirmed lineup') return row.prediction_stage === 'confirmed_lineup'
    if (tab === 'Shortlist') return board.category === 'confirmed_lineup_shortlist'
    if (tab === 'Baseline board') return row.prediction_stage === 'model_projection_baseline'
    return true
  }).sort((a, b) => (b.decision_board?.[metric]?.convergence_score || 0) - (a.decision_board?.[metric]?.convergence_score || 0)), [data, tab, metric])
  const games = [...new Map((data?.records || []).map(row => [row.game_pk, row])).values()]
  const counts = data?.stage_counts || {}
  return <main className="predicts-page">
    <header className="predicts-hero"><div><p className="predicts-kicker">MLBGPT PREDICTION DESK</p><h1>From baseline to confirmed call</h1><p>Model Projections drives the early board. Confirmed lineups unlock the full matchup funnel and a separately graded prediction.</p></div><label>Game date<input type="date" value={date} onChange={event => event.target.value && setDate(event.target.value)} /></label></header>
    <section className="predicts-pipeline" aria-label="Prediction timing"><div><span>1</span><strong>Model Projection</strong><small>Always the baseline</small></div><b>→</b><div><span>2</span><strong>Lineup confirmed</strong><small>Opportunity is locked</small></div><b>→</b><div><span>3</span><strong>MLBGPT funnel</strong><small>Trends + matchup + context</small></div><b>→</b><div><span>4</span><strong>Final & learn</strong><small>Grade every frozen call</small></div></section>
    <nav className="predicts-tabs" aria-label="Prediction views">{tabs.map(value => <button key={value} aria-pressed={tab === value} onClick={() => { setTab(value); setSelected(null) }}>{value}</button>)}</nav>
    {!['Games', 'Results & drivers', 'Model health'].includes(tab) && <div className="predicts-toolbar"><label>Outcome<select value={metric} onChange={event => { setMetric(event.target.value); setSelected(null) }}>{Object.entries(labels).map(([key, value]) => <option key={key} value={key}>{value}</option>)}</select></label><p><strong>{counts.confirmed_lineup || 0}</strong> confirmed · <strong>{counts.model_projection_baseline || 0}</strong> awaiting lineup</p></div>}
    {loading && <p role="status">Loading prediction desk…</p>}{error && <p role="alert">{error}</p>}
    {!loading && !error && tab === 'Model health' && analysis && <section><h2>Residual model health</h2><p>{analysis.cold_start ? 'The learned adjustment is collecting enough real frozen predictions and Finals to prove it can beat Model Projections.' : 'The learned adjustment has passed its temporal evidence gate.'}</p><p className="predicts-muted">Until that proof exists, the MLBGPT numerical line remains the Model Projections baseline. The convergence board still ranks the strongest multi-source cases.</p></section>}
    {!loading && !error && tab === 'Results & drivers' && analysis && <section><h2>What is actually winning</h2>{analysis.decision_performance?.length ? <div className="predicts-table-wrap"><table><thead><tr><th>Prediction</th><th>Outcome</th><th>Record</th><th>Win rate</th><th>Avg vs baseline</th></tr></thead><tbody>{analysis.decision_performance.map(row => <tr key={`${row.player_type}-${row.metric}-${row.category}`}><td>{driverLabel(row.category)}</td><td>{row.player_type} · {labels[row.metric]}</td><td>{row.wins}–{row.n - row.wins}</td><td>{percent(row.win_rate)}</td><td>{row.average_actual_minus_baseline > 0 ? '+' : ''}{fmt(row.average_actual_minus_baseline)}</td></tr>)}</tbody></table></div> : <p>No graded predictions for this date yet.</p>}{analysis.winning_drivers?.length > 0 && <><h3>Drivers inside confirmed shortlists</h3><div className="predicts-driver-cards">{analysis.winning_drivers.map(row => <article key={`${row.player_type}-${row.metric}-${row.driver}`}><span>{driverLabel(row.driver)}</span><strong>{percent(row.win_rate)}</strong><small>{row.wins}/{row.n} finished above baseline</small></article>)}</div></>}</section>}
    {!loading && !error && tab === 'Games' && <div className="predicts-game-grid">{games.map(row => <article key={row.game_pk}><span className={`predicts-stage ${row.prediction_stage}`}>{stageLabel(row)}</span><h3>{row.team} vs {row.opponent}</h3><p>{new Date(row.game_time).toLocaleString()}</p><Link to={`/matchup/${row.game_pk}`}>Open matchup</Link>{row.outcome && <p><Link to={`/final/${row.game_pk}`}>View Final</Link></p>}</article>)}</div>}
    {!loading && !error && !['Games', 'Results & drivers', 'Model health'].includes(tab) && <>{rows.length ? <div className="predicts-table-wrap"><table><thead><tr><th>Rank</th><th>Player</th><th>Matchup</th><th>Stage</th><th>Model Projection</th><th>MLBGPT line</th><th>Convergence</th><th>Signals</th><th>Book context</th></tr></thead><tbody>{rows.map((row, index) => { const board = row.decision_board[metric]; return <tr key={`${row.game_pk}-${row.player_id}-${row.player_type}`}><td className="predicts-rank">{index + 1}</td><td><button className="predicts-player" onClick={() => setSelected(row)}>{row.player_name || `Player ${row.player_id}`}</button><small>{row.player_type === 'batter' && row.batting_order ? `Batting ${row.batting_order}` : row.player_type}</small></td><td>{row.team} vs {row.opponent}<small>{new Date(row.game_time).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })}</small></td><td><span className={`predicts-stage ${row.prediction_stage}`}>{row.prediction_stage === 'confirmed_lineup' ? 'Confirmed' : 'Baseline'}</span></td><td>{fmt(row.baseline[metric])}</td><td><strong>{fmt(board.mlbgpt_line)}</strong><small>{board.line_authority === 'validated_residual_model' ? 'Adjusted' : 'Baseline retained'}</small></td><td><span className="predicts-score">{fmt(board.convergence_score, 0)}</span></td><td>{board.supporting_signals} supporting<small>{board.opposing_signals} opposing</small></td><td><BookContext markets={board.book_markets} /></td></tr> })}</tbody></table></div> : <p>{tab === 'Confirmed lineup' || tab === 'Shortlist' ? 'No confirmed-lineup predictions yet. Model Projections remains available on the Baseline board until lineups lock.' : data?.reason || 'No eligible predictions.'}</p>}</>}
    {selected && <Detail row={selected} metric={metric} onClose={() => setSelected(null)} />}
  </main>
}

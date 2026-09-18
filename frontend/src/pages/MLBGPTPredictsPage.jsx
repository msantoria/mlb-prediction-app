import React, { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { API_BASE, getMlbToday } from '../lib/api'
import './MLBGPTPredictsPage.css'

const fmt = value => value == null ? '—' : Number(value).toFixed(2)
const percent = value => value == null ? '—' : `${(value * 100).toFixed(1)}%`
const labels = { hits: 'Hits', total_bases: 'Total bases', home_runs: 'Home runs', strikeouts: 'Strikeouts' }
const tabs = ['All', 'Overperform', 'Underperform', 'Hitters', 'Pitchers', 'Games', 'Model health']
const statusLabel = status => ({ insufficient_history: 'Collecting history', baseline_unavailable: 'Baseline unavailable', no_validated_improvement: 'No validated improvement', ready: 'Research estimate' }[status] || 'Unavailable')

function Feature({ name, value, children }) {
  return <section className="predicts-feature"><h3>{name}</h3><strong>{fmt(value)}</strong>{children}</section>
}

function Detail({ row, metric, onClose }) {
  const prediction = row.predictions[metric]
  const f = row.features
  const distribution = prediction?.distribution || row.baseline_distributions[metric]
  return <section className="predicts-detail" aria-label={`${row.player_name} prediction details`}>
    <div className="predicts-heading"><h2>{row.player_name} · {labels[metric]}</h2><button onClick={onClose}>Close details</button></div>
    <p>{row.team} vs {row.opponent} · {row.lineup_status || 'Lineup status unavailable'} · {row.locked ? 'Pregame record locked' : 'Pregame candidate'}</p>
    <div className="predicts-features">
      <Feature name="Baseline" value={row.baseline[metric]}><p>Model Projections</p></Feature>
      <Feature name="Predicts" value={prediction?.adjusted}><p>{statusLabel(prediction?.status)}</p></Feature>
      <Feature name="Expected difference" value={prediction?.expected_residual}><p>Over: {percent(prediction?.probability_over_baseline)} · Under: {percent(prediction?.probability_under_baseline)}</p></Feature>
      <Feature name={row.player_type === 'batter' ? 'Expected plate appearances' : 'Expected batters faced'} value={f.opportunity.value} />
      <Feature name="Arsenal compatibility" value={f.arsenal.value}><p>{f.arsenal.sample_size} batted balls · Reliability {percent(f.arsenal.reliability)}</p></Feature>
      <Feature name="Location compatibility" value={f.location.value}><p>{f.location.sample_size} batted balls</p></Feature>
      <Feature name="Recent process change" value={f.trend.value}><p>{f.trend.sample_size} recent observations · Standardized difference</p></Feature>
      <Feature name="Expected starter pitches" value={f.workload.value}><p>{f.workload.sample_size} prior starts</p></Feature>
    </div>
    <h3>Why the projection changes</h3>
    {prediction?.attributions?.length ? <ul>{prediction.attributions.map(item => <li key={item.feature}>{item.feature.replaceAll('_', ' ')}: {item.value > 0 ? '+' : ''}{fmt(item.value)}{item.missing ? ' (missing input)' : ''}</li>)}</ul> : <p>There is not enough validated history to justify changing this baseline.</p>}
    <h3>Starter, bullpen and environment</h3>
    <p>PA vs starter: {fmt(f.bullpen.exposure?.expected_pa_vs_starter)} · PA vs bullpen: {fmt(f.bullpen.exposure?.expected_pa_vs_bullpen)} · Run environment index: {fmt(f.environment.value)}</p>
    <h3>{prediction?.distribution ? 'Adjusted distribution' : 'Baseline simulation distribution'}</h3>
    <p>Median {fmt(distribution?.median)} · 10th–90th percentile {fmt(distribution?.p10)}–{fmt(distribution?.p90)} · SD {fmt(distribution?.sd)}</p>
    <p>P(0) {percent(distribution?.p0)} · P(1+) {percent(distribution?.p1_plus)} · P(2+) {percent(distribution?.p2_plus)} · P(3+) {percent(distribution?.p3_plus)}</p>
    {prediction?.comparables && <p>Historical comparables: {prediction.comparables.sample_size} · Over baseline {percent(prediction.comparables.over_rate)} · Population {percent(prediction.comparables.population_over_rate)}</p>}
    {row.outcome && <p>Final result: {fmt(row.outcome.metrics[metric]?.actual)} · Baseline error: {fmt(row.outcome.metrics[metric]?.residual)} · <Link to={`/final/${row.game_pk}`}>Open Final</Link></p>}
    <p className="predicts-muted">Captured {new Date(row.as_of).toLocaleString()} · <Link to={`/models/projections?date=${row.date}`}>Open Model Projections</Link></p>
  </section>
}

export default function MLBGPTPredictsPage() {
  const [date, setDate] = useState(getMlbToday())
  const [tab, setTab] = useState('All')
  const [metric, setMetric] = useState('total_bases')
  const [data, setData] = useState(null)
  const [health, setHealth] = useState(null)
  const [error, setError] = useState(null)
  const [loading, setLoading] = useState(true)
  const [selected, setSelected] = useState(null)
  useEffect(() => {
    const controller = new AbortController()
    setLoading(true); setError(null); setData(null); setSelected(null); setHealth(null)
    const path = tab === 'Model health' ? '/predicts/model-health' : `/predicts?date=${date}`
    fetch(`${API_BASE}${path}`, { signal: controller.signal, cache: 'no-store' }).then(async response => {
      const body = await response.json()
      if (!response.ok) throw new Error(typeof body.detail === 'string' ? body.detail : 'Could not load predictions')
      return body
    }).then(body => {
      if (tab === 'Model health') setHealth(body)
      else setData(body)
    }).catch(err => { if (err.name !== 'AbortError') setError(err.message) })
      .finally(() => { if (!controller.signal.aborted) setLoading(false) })
    return () => controller.abort()
  }, [date, tab === 'Model health'])
  const rows = useMemo(() => (data?.records || []).filter(row => {
    const prediction = row.predictions[metric]
    if (tab === 'Hitters' && row.player_type !== 'batter') return false
    if (tab === 'Pitchers' && row.player_type !== 'pitcher') return false
    if (tab === 'Overperform') return prediction?.expected_residual > 0
    if (tab === 'Underperform') return prediction?.expected_residual < 0
    return row.baseline[metric] != null
  }).sort((a, b) => {
    const av = a.predictions[metric]?.expected_residual
    const bv = b.predictions[metric]?.expected_residual
    if (av == null) return bv == null ? 0 : 1
    if (bv == null) return -1
    return tab === 'Underperform' ? av - bv : bv - av
  }), [data, tab, metric])
  const games = [...new Map((data?.records || []).map(row => [row.game_pk, row])).values()]
  const selectTab = value => { setTab(value); setSelected(null); if (value === 'Pitchers') setMetric('strikeouts'); if (value === 'Hitters') setMetric('total_bases') }
  return <main className="predicts-page">
    <div className="predicts-heading"><div><p className="predicts-kicker">MLBGPT RESEARCH</p><h1>MLBGPT Predicts</h1><p>Where does the evidence disagree with the baseline?</p></div><label>Game date<input type="date" value={date} onChange={event => { if (event.target.value) setDate(event.target.value) }} /></label></div>
    <nav className="predicts-tabs" aria-label="Prediction views">{tabs.map(value => <button key={value} aria-pressed={tab === value} onClick={() => selectTab(value)}>{value}</button>)}</nav>
    {tab !== 'Model health' && tab !== 'Games' && <label className="predicts-metric">Outcome<select value={metric} onChange={event => { setMetric(event.target.value); setSelected(null) }}>{Object.entries(labels).map(([key, value]) => <option key={key} value={key}>{value}</option>)}</select></label>}
    {loading && <p role="status">Loading predictions…</p>}
    {error && <p role="alert">{error}</p>}
    {!loading && !error && tab === 'Model health' && health && <section>
      <h2>Measured against the original baseline</h2><p>{health.cold_start ? 'Collecting pregame history. Adjustments require at least 100 training rows, 30 later validation rows and 14 game dates.' : 'Validation uses saved pregame predictions and official Final results.'}</p>
      <div className="predicts-table-wrap"><table><thead><tr><th>Outcome</th><th>Players</th><th>Baseline MAE</th><th>Adjusted MAE</th><th>Adjusted sample</th><th>Brier score</th></tr></thead><tbody>{health.recent_evaluation.groups.map(group => <tr key={`${group.player_type}-${group.metric}-${group.model_version}`}><td>{group.player_type} · {labels[group.metric]}</td><td>{group.n}</td><td>{fmt(group.paired_baseline_mae ?? group.mae)}</td><td>{fmt(group.adjusted_mae)}</td><td>{group.adjusted_n}</td><td>{fmt(group.brier)}</td></tr>)}</tbody></table></div>
      {!health.recent_evaluation.groups.length && <p>No graded predictions in the last 30 days.</p>}
    </section>}
    {!loading && !error && tab === 'Games' && <div className="predicts-features">{games.map(row => <section className="predicts-feature" key={row.game_pk}><h3>{row.team} vs {row.opponent}</h3><p>{new Date(row.game_time).toLocaleString()}</p><Link to={`/matchup/${row.game_pk}`}>Open matchup</Link>{row.outcome && <p><Link to={`/final/${row.game_pk}`}>View Final</Link></p>}</section>)}</div>}
    {!loading && !error && !['Games', 'Model health'].includes(tab) && <>
      <p className="predicts-muted">Pregame candidates update until game time. A dash means the evidence is unavailable. Times are shown in your local time zone.</p>
      {rows.length ? <div className="predicts-table-wrap"><table><thead><tr><th>Player</th><th>Matchup</th><th>Lineup</th><th>Baseline</th><th>Predicts</th><th>Difference</th><th>P(over)</th><th>Evidence</th></tr></thead><tbody>{rows.map(row => {
        const prediction = row.predictions[metric]
        return <tr key={`${row.game_pk}-${row.player_id}-${row.player_type}`}><td><button className="predicts-player" onClick={() => setSelected(row)}>{row.player_name || `Player ${row.player_id}`}</button></td><td>{row.team} vs {row.opponent}<small>{new Date(row.game_time).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })}</small></td><td>{row.lineup_status || 'Unavailable'}</td><td>{fmt(row.baseline[metric])}</td><td>{fmt(prediction?.adjusted)}</td><td>{fmt(prediction?.expected_residual)}</td><td>{percent(prediction?.probability_over_baseline)}</td><td>{statusLabel(prediction?.status)}</td></tr>
      })}</tbody></table></div> : <p>{data?.reason || 'No players meet this view’s evidence requirements.'}</p>}
    </>}
    {selected && <Detail row={selected} metric={metric} onClose={() => setSelected(null)} />}
  </main>
}

import React, { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'

const API = import.meta.env.VITE_API_BASE_URL || ''

const s = {
  page: { display: 'grid', gap: '18px' },
  hero: { background: 'linear-gradient(135deg, #161b22 0%, #0d1117 58%, #101826 100%)', border: '1px solid #30363d', borderRadius: '16px', padding: '22px', boxShadow: '0 18px 48px rgba(0,0,0,0.24)' },
  header: { display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: '16px', flexWrap: 'wrap' },
  eyebrow: { color: '#58a6ff', fontSize: '12px', fontWeight: '800', textTransform: 'uppercase', letterSpacing: '1.2px', marginBottom: '8px' },
  title: { fontSize: '30px', lineHeight: 1.05, fontWeight: '900', color: '#e6edf3', margin: 0 },
  subtitle: { color: '#8b949e', fontSize: '14px', marginTop: '8px', maxWidth: '720px' },
  controls: { display: 'flex', gap: '10px', alignItems: 'center', flexWrap: 'wrap' },
  input: { background: '#0d1117', border: '1px solid #30363d', color: '#e6edf3', borderRadius: '10px', padding: '10px 12px', fontSize: '14px', outline: 'none' },
  select: { background: '#0d1117', border: '1px solid #30363d', color: '#e6edf3', borderRadius: '10px', padding: '9px 11px', fontSize: '13px', outline: 'none', minWidth: '220px' },
  button: { background: '#238636', border: '1px solid #2ea043', color: '#fff', borderRadius: '10px', padding: '10px 14px', fontSize: '13px', fontWeight: '800', cursor: 'pointer' },
  mutedButton: { background: '#21262d', border: '1px solid #30363d', color: '#58a6ff', borderRadius: '9px', padding: '8px 11px', fontSize: '12px', fontWeight: '800', cursor: 'pointer' },
  stats: { display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(145px, 1fr))', gap: '10px', marginTop: '18px' },
  statCard: { background: 'rgba(13,17,23,0.72)', border: '1px solid #30363d', borderRadius: '12px', padding: '13px 14px' },
  statLabel: { color: '#8b949e', fontSize: '10px', textTransform: 'uppercase', letterSpacing: '0.9px', fontWeight: '800' },
  statValue: { color: '#e6edf3', fontSize: '24px', fontWeight: '900', marginTop: '5px' },
  toolbar: { display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: '12px', flexWrap: 'wrap', background: '#161b22', border: '1px solid #30363d', borderRadius: '12px', padding: '12px 14px' },
  toolbarText: { color: '#8b949e', fontSize: '13px' },
  grid: { display: 'grid', gap: '12px' },
  card: { background: '#161b22', border: '1px solid #30363d', borderRadius: '14px', padding: '0', overflow: 'hidden' },
  cardTop: { display: 'grid', gridTemplateColumns: 'minmax(0, 1fr) auto', gap: '14px', alignItems: 'center', padding: '15px 16px', borderBottom: '1px solid #30363d', background: '#111820' },
  matchup: { color: '#e6edf3', fontSize: '18px', fontWeight: '900' },
  metaRow: { display: 'flex', gap: '8px', flexWrap: 'wrap', marginTop: '8px' },
  chip: { color: '#8b949e', border: '1px solid #30363d', background: '#0d1117', borderRadius: '999px', padding: '4px 8px', fontSize: '11px', fontWeight: '700' },
  badge: matched => ({ display: 'inline-block', borderRadius: '999px', padding: '5px 10px', fontSize: '11px', fontWeight: '900', background: matched ? 'rgba(35,134,54,0.18)' : 'rgba(248,81,73,0.14)', border: matched ? '1px solid rgba(63,185,80,0.45)' : '1px solid rgba(248,81,73,0.45)', color: matched ? '#3fb950' : '#f85149' }),
  markets: { display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: '10px', padding: '14px 16px' },
  market: { border: '1px solid #30363d', borderRadius: '12px', padding: '12px', background: '#0d1117' },
  marketTitle: { color: '#8b949e', fontSize: '10px', textTransform: 'uppercase', letterSpacing: '0.9px', fontWeight: '900', marginBottom: '9px' },
  oddsLine: { display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: '10px', color: '#e6edf3', fontSize: '13px', marginTop: '6px', padding: '5px 0', borderTop: '1px solid rgba(48,54,61,0.55)' },
  price: { fontWeight: '900', color: '#e6edf3', whiteSpace: 'nowrap' },
  props: { borderTop: '1px solid #30363d', padding: '13px 16px 16px', background: '#111820' },
  propControls: { display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: '10px', marginBottom: '10px' },
  propsGrid: { display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(235px, 1fr))', gap: '9px' },
  propCard: { border: '1px solid #30363d', borderRadius: '10px', padding: '10px', background: '#0d1117' },
  propMarket: { color: '#d29922', fontSize: '10px', fontWeight: '900', textTransform: 'uppercase', letterSpacing: '0.6px', marginBottom: '6px' },
  propName: { color: '#e6edf3', fontSize: '13px', fontWeight: '900' },
  propDetail: { color: '#8b949e', fontSize: '12px', marginTop: '4px' },
  modelPanel: { borderTop: '1px solid #30363d', padding: '14px 16px 16px', background: '#0f1720' },
  modelHeader: { display: 'flex', justifyContent: 'space-between', gap: '12px', alignItems: 'flex-start', flexWrap: 'wrap', marginBottom: '12px' },
  modelTitle: { color: '#e6edf3', fontSize: '14px', fontWeight: '900' },
  modelSubtitle: { color: '#8b949e', fontSize: '12px', marginTop: '4px' },
  modelGrid: { display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: '10px' },
  modelCard: { border: '1px solid #30363d', borderRadius: '12px', padding: '12px', background: '#0d1117' },
  modelCardTitle: { color: '#8b949e', fontSize: '10px', textTransform: 'uppercase', letterSpacing: '0.9px', fontWeight: '900', marginBottom: '8px' },
  modelPick: { color: '#e6edf3', fontSize: '15px', fontWeight: '900', lineHeight: 1.25 },
  modelDetail: { color: '#8b949e', fontSize: '12px', marginTop: '6px', lineHeight: 1.35 },
  confidence: score => ({ color: Number(score) >= 0.65 || Number(score) >= 65 ? '#3fb950' : '#d29922', fontSize: '20px', fontWeight: '900', marginTop: '7px' }),
  reasonList: { margin: '8px 0 0', paddingLeft: '18px', color: '#8b949e', fontSize: '12px', lineHeight: 1.45 },
  section: { background: '#161b22', border: '1px solid #30363d', borderRadius: '14px', padding: '16px' },
  sectionHeader: { display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: '12px', flexWrap: 'wrap', marginBottom: '12px' },
  sectionTitle: { color: '#e6edf3', fontSize: '18px', fontWeight: '900' },
  error: { color: '#f85149', background: '#1f1116', border: '1px solid #3b2222', borderRadius: '12px', padding: '14px' },
  loader: { color: '#8b949e', textAlign: 'center', padding: '40px' },
  empty: { color: '#8b949e', textAlign: 'center', padding: '40px', border: '1px solid #30363d', borderRadius: '14px', background: '#161b22' },
}

function normalizeTeamName(name) {
  return String(name || '').toLowerCase().replace(/[^a-z0-9]/g, '').replace(/^the/, '')
}

function matchupKey(away, home) {
  return `${normalizeTeamName(away)}@${normalizeTeamName(home)}`
}

function keyFromMatchup(m) {
  return matchupKey(m.away_team_name || m.away_team || m.away_name, m.home_team_name || m.home_team || m.home_name)
}

function keyFromEvent(e) {
  return matchupKey(e?.away_team?.name || e?.away_team || '', e?.home_team?.name || e?.home_team || '')
}

function keyFromModelGame(game) {
  return matchupKey(game?.away_team || game?.away_team_name || game?.away || '', game?.home_team || game?.home_team_name || game?.home || '')
}

function american(v) {
  if (v == null || v === '') return '—'
  const n = Number(v)
  if (Number.isNaN(n)) return String(v)
  return n > 0 ? `+${n}` : `${n}`
}

function pct(v) {
  if (v == null || v === '') return '—'
  const n = Number(v)
  if (Number.isNaN(n)) return String(v)
  const pctValue = n <= 1 ? n * 100 : n
  return `${Math.round(pctValue)}%`
}

function formatTime(iso) {
  if (!iso) return '—'
  try {
    return new Date(iso).toLocaleString('en-US', { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit', timeZone: 'America/New_York' }) + ' ET'
  } catch {
    return '—'
  }
}

function cleanMarketName(name) {
  return String(name || 'Market').replaceAll('_', ' ')
}

function getMarkets(event) {
  return Array.isArray(event?.markets) ? event.markets : []
}

function findMarket(event, keys) {
  const wanted = Array.isArray(keys) ? keys : [keys]
  return getMarkets(event).find(m => wanted.includes(m.market_key) || wanted.includes(m.market_type) || wanted.includes(m.market_name))
}

function selectionLabel(sel) {
  return `${sel?.name || sel?.description || '—'}${sel?.line != null ? ` ${sel.line}` : ''}`
}

function asArray(value) {
  return Array.isArray(value) ? value : []
}

function firstDefined(...values) {
  return values.find(v => v !== undefined && v !== null && v !== '')
}

function modelGamesFromPayload(payload) {
  if (Array.isArray(payload)) return payload
  if (Array.isArray(payload?.games)) return payload.games
  if (Array.isArray(payload?.models)) return payload.models
  if (Array.isArray(payload?.game_models)) return payload.game_models
  return []
}

function propCandidatesFromPayload(payload) {
  if (Array.isArray(payload?.top_prop_model_candidates)) return payload.top_prop_model_candidates
  if (Array.isArray(payload?.top_props)) return payload.top_props
  if (Array.isArray(payload?.prop_candidates)) return payload.prop_candidates
  if (Array.isArray(payload?.props)) return payload.props
  return []
}

function modelDetail(model) {
  if (!model) return ''
  const probability = firstDefined(model.model_probability, model.probability)
  const marketProbability = firstDefined(model.market_implied_probability, model.market_probability)
  const score = firstDefined(model.score)
  const parts = []
  if (probability != null) parts.push(`Model probability: ${pct(probability)}`)
  if (marketProbability != null) parts.push(`Market implied: ${pct(marketProbability)}`)
  if (score != null) parts.push(`Score: ${score}`)
  return parts.join(' · ')
}

function modelReasons(model) {
  return [
    ...asArray(model?.drivers),
    ...asArray(model?.reasons),
    ...asArray(model?.missing_inputs).slice(0, 2).map(item => `Missing: ${item}`),
  ]
}

function normalizeCandidate(candidate) {
  const pick = firstDefined(candidate.pick, candidate.side, candidate.recommendation, candidate.selection, 'No pick')
  const market = cleanMarketName(firstDefined(candidate.market, candidate.market_name, candidate.prop_market, 'Prop Market'))
  const line = firstDefined(candidate.line, candidate.prop_line)
  const price = firstDefined(candidate.price, candidate.odds, candidate.american_odds)
  return { pick, market, line, price }
}

function ModelCard({ title, pick, confidence, detail, reasons }) {
  const reasonItems = asArray(reasons).filter(Boolean).slice(0, 4)
  return (
    <div style={s.modelCard}>
      <div style={s.modelCardTitle}>{title}</div>
      <div style={s.modelPick}>{pick || 'No model pick'}</div>
      {confidence != null && <div style={s.confidence(confidence)}>{pct(confidence)}</div>}
      {detail && <div style={s.modelDetail}>{detail}</div>}
      {reasonItems.length > 0 && (
        <ul style={s.reasonList}>
          {reasonItems.map((reason, idx) => <li key={`${title}-reason-${idx}`}>{reason}</li>)}
        </ul>
      )}
    </div>
  )
}

function GameModelPanel({ model }) {
  if (!model) {
    return (
      <div style={s.modelPanel}>
        <div style={s.modelTitle}>Game Model Panel</div>
        <div style={s.modelSubtitle}>No model output matched this sportsbook event yet.</div>
      </div>
    )
  }

  const modelRoot = model?.models || model
  const moneylineModel = modelRoot?.moneyline || {}
  const spreadModel = modelRoot?.spread || modelRoot?.run_line || {}
  const totalModel = modelRoot?.total || {}

  const sidePick = firstDefined(model.side_pick, model.moneyline_pick, model.winner_pick, model.pick, moneylineModel.pick)
  const totalPick = firstDefined(model.total_pick, model.total_model_pick, model.over_under_pick, totalModel.pick)
  const runLinePick = firstDefined(model.run_line_pick, model.spread_pick, model.runline_pick, spreadModel.pick)
  const edge = firstDefined(model.edge, model.edge_score, model.model_edge, moneylineModel.edge, spreadModel.edge, totalModel.edge)
  const confidence = firstDefined(model.confidence, model.model_confidence, model.score, moneylineModel.confidence)
  const reasons = firstDefined(model.reasons, model.model_reasons, model.summary_reasons, moneylineModel.drivers, [])

  return (
    <div style={s.modelPanel}>
      <div style={s.modelHeader}>
        <div>
          <div style={s.modelTitle}>GameModelPanel</div>
          <div style={s.modelSubtitle}>Visible model output from /daily-odds/models for this matched game.</div>
        </div>
        <span style={s.chip}>Edge: {edge ?? '—'}</span>
      </div>
      <div style={s.modelGrid}>
        <ModelCard
          title="Moneyline Model"
          pick={sidePick}
          confidence={confidence}
          detail={firstDefined(model.moneyline_detail, model.side_detail, model.summary, modelDetail(moneylineModel))}
          reasons={firstDefined(reasons, modelReasons(moneylineModel))}
        />
        <ModelCard
          title="Run Line Model"
          pick={runLinePick}
          confidence={firstDefined(model.run_line_confidence, model.spread_confidence, spreadModel.confidence)}
          detail={firstDefined(model.run_line_detail, model.spread_detail, modelDetail(spreadModel))}
          reasons={firstDefined(model.run_line_reasons, model.spread_reasons, modelReasons(spreadModel))}
        />
        <ModelCard
          title="Total Model"
          pick={totalPick}
          confidence={firstDefined(model.total_confidence, model.over_under_confidence, totalModel.confidence)}
          detail={firstDefined(model.total_detail, model.over_under_detail, modelDetail(totalModel))}
          reasons={firstDefined(model.total_reasons, model.over_under_reasons, modelReasons(totalModel))}
        />
      </div>
    </div>
  )
}

function CandidateGrid({ candidates, limit = 10 }) {
  const rows = asArray(candidates).slice(0, limit)
  if (rows.length === 0) return <div style={s.empty}>No top prop model candidates returned.</div>
  return (
    <div style={s.modelGrid}>
      {rows.map((candidate, idx) => {
        const { pick, market, line, price } = normalizeCandidate(candidate)
        const player = firstDefined(candidate.player_name, candidate.player, candidate.name, 'Player')
        return (
          <ModelCard
            key={`${player}-${market}-${pick}-${idx}`}
            title={market}
            pick={`${player}: ${pick}${line != null ? ` ${line}` : ''}${price != null ? ` (${american(price)})` : ''}`}
            confidence={firstDefined(candidate.confidence, candidate.score, candidate.model_score)}
            detail={firstDefined(candidate.detail, candidate.summary, candidate.edge != null ? `Edge: ${candidate.edge}` : '')}
            reasons={firstDefined(candidate.reasons, candidate.reasoning, candidate.drivers, [])}
          />
        )
      })}
    </div>
  )
}

function TopPropModelCandidates({ candidates }) {
  const rows = asArray(candidates).slice(0, 20)
  return (
    <section style={s.section}>
      <div style={s.sectionHeader}>
        <div>
          <div style={s.sectionTitle}>Top Prop Model Candidates</div>
          <div style={s.modelSubtitle}>Highest-ranked prop model outputs returned by /daily-odds/models.</div>
        </div>
        <span style={s.chip}>{rows.length} shown</span>
      </div>
      <CandidateGrid candidates={rows} limit={20} />
    </section>
  )
}

function PerGamePropCandidates({ eventId }) {
  const [open, setOpen] = useState(false)
  const [limit, setLimit] = useState(10)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const [payload, setPayload] = useState(null)

  function load() {
    if (!eventId || loading) return
    setLoading(true)
    setError(null)
    fetch(`${API}/daily-odds/event/${eventId}/prop-models`)
      .then(async r => {
        if (!r.ok) throw new Error(`${r.status} ${r.statusText}: ${await r.text()}`)
        return r.json()
      })
      .then(json => { setPayload(json); setLoading(false) })
      .catch(err => { setError(String(err?.message || err)); setLoading(false) })
  }

  function toggle() {
    const next = !open
    setOpen(next)
    if (next && !payload) load()
  }

  const models = payload?.models || {}
  const candidates = asArray(payload?.top_prop_model_candidates).length
    ? payload.top_prop_model_candidates
    : asArray(models?.top_candidates)
  const count = firstDefined(models?.candidate_count, candidates.length, 0)

  return (
    <div style={s.modelPanel}>
      <div style={s.modelHeader}>
        <div>
          <div style={s.modelTitle}>Per-Game Top Prop Model Candidates</div>
          <div style={s.modelSubtitle}>Pitcher and hitter prop candidates ranked from this game’s DraftKings prop board.</div>
        </div>
        <div style={s.controls}>
          <select value={limit} onChange={e => setLimit(Number(e.target.value))} style={s.select}>
            <option value={5}>Top 5</option>
            <option value={10}>Top 10</option>
            <option value={20}>Top 20</option>
          </select>
          <button type="button" style={s.mutedButton} onClick={toggle}>{open ? 'Hide Prop Candidates' : 'Show Prop Candidates'}</button>
        </div>
      </div>
      {open && loading && <div style={s.loader}>Loading prop model candidates...</div>}
      {open && error && <div style={s.error}>Prop model error: {error}</div>}
      {open && !loading && !error && payload && (
        <>
          <div style={{ ...s.modelSubtitle, marginBottom: '10px' }}>{count} prop candidates evaluated. Showing {Math.min(limit, candidates.length)}.</div>
          <CandidateGrid candidates={candidates} limit={limit} />
        </>
      )}
    </div>
  )
}

function MarketBox({ label, market }) {
  const selections = market?.selections || []
  return (
    <div style={s.market}>
      <div style={s.marketTitle}>{label}</div>
      {selections.length === 0 && <div style={s.oddsLine}><span>Unavailable</span><strong style={s.price}>—</strong></div>}
      {selections.slice(0, 3).map((sel, idx) => (
        <div key={`${label}-${idx}`} style={s.oddsLine}>
          <span>{selectionLabel(sel)}</span>
          <strong style={s.price}>{american(sel.price)}</strong>
        </div>
      ))}
    </div>
  )
}

function PropsPanel({ eventId }) {
  const [open, setOpen] = useState(false)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const [data, setData] = useState(null)
  const [selectedMarket, setSelectedMarket] = useState('all')

  function toggle() {
    if (open) {
      setOpen(false)
      return
    }
    setOpen(true)
    if (data || loading) return
    setLoading(true)
    setError(null)
    fetch(`${API}/odds/draftkings/event/${eventId}/props`)
      .then(async r => {
        if (!r.ok) throw new Error(`${r.status} ${r.statusText}: ${await r.text()}`)
        return r.json()
      })
      .then(json => { setData(json); setLoading(false) })
      .catch(err => { setError(String(err?.message || err)); setLoading(false) })
  }

  const markets = data?.markets || data?.event?.markets || []
  const filteredMarkets = selectedMarket === 'all'
    ? markets
    : markets.filter((_, idx) => String(idx) === selectedMarket)
  const props = filteredMarkets.flatMap(market =>
    (market.selections || []).map(sel => ({ market, sel }))
  )

  return (
    <div style={s.props}>
      <div style={s.propControls}>
        <button type="button" style={s.mutedButton} onClick={toggle}>{open ? 'Hide Player Props' : 'Show Player Props'}</button>
        {open && markets.length > 0 && (
          <select value={selectedMarket} onChange={e => setSelectedMarket(e.target.value)} style={s.select}>
            <option value="all">All prop markets</option>
            {markets.map((market, idx) => (
              <option key={`${market.market_key || market.market_name}-${idx}`} value={String(idx)}>{cleanMarketName(market.market_name || market.market_key)}</option>
            ))}
          </select>
        )}
      </div>
      {open && loading && <div style={{ color: '#8b949e', fontSize: '12px', marginTop: '10px' }}>Loading props...</div>}
      {open && error && <div style={{ color: '#f85149', fontSize: '12px', marginTop: '10px' }}>Props error: {error}</div>}
      {open && !loading && !error && data && props.length === 0 && <div style={{ color: '#8b949e', fontSize: '12px', marginTop: '10px' }}>No props returned for this selection.</div>}
      {open && props.length > 0 && (
        <div style={{ ...s.propsGrid, marginTop: '10px' }}>
          {props.slice(0, 80).map(({ market, sel }, idx) => (
            <div key={`${market.market_key || market.market_name}-${sel.description}-${sel.name}-${idx}`} style={s.propCard}>
              <div style={s.propMarket}>{cleanMarketName(market.market_name || market.market_key)}</div>
              <div style={s.propName}>{sel.description || sel.name || '—'}</div>
              <div style={s.propDetail}>{selectionLabel(sel)} · <strong style={{ color: '#e6edf3' }}>{american(sel.price)}</strong></div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

export default function DailyOddsPage() {
  const today = new Date().toISOString().slice(0, 10)
  const [date, setDate] = useState(today)
  const [matchups, setMatchups] = useState([])
  const [events, setEvents] = useState([])
  const [modelPayload, setModelPayload] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const [modelError, setModelError] = useState(null)
  const [lastRefreshed, setLastRefreshed] = useState(null)

  function load() {
    setLoading(true)
    setError(null)
    setModelError(null)
    Promise.all([
      fetch(`${API}/matchups?date=${date}`).then(async r => {
        if (!r.ok) throw new Error(`/matchups failed: ${r.status} ${r.statusText}: ${await r.text()}`)
        return r.json()
      }),
      fetch(`${API}/odds/draftkings/events?date=${date}`).then(async r => {
        if (!r.ok) throw new Error(`/odds/draftkings/events failed: ${r.status} ${r.statusText}: ${await r.text()}`)
        return r.json()
      }),
      fetch(`${API}/daily-odds/models?date=${date}`).then(async r => {
        if (!r.ok) throw new Error(`/daily-odds/models failed: ${r.status} ${r.statusText}: ${await r.text()}`)
        return r.json()
      }).catch(err => ({ __modelError: String(err?.message || err) })),
    ])
      .then(([matchupData, oddsData, modelsData]) => {
        setMatchups(Array.isArray(matchupData) ? matchupData : [])
        setEvents(Array.isArray(oddsData?.events) ? oddsData.events : [])
        if (modelsData?.__modelError) {
          setModelPayload(null)
          setModelError(modelsData.__modelError)
        } else {
          setModelPayload(modelsData)
        }
        setLastRefreshed(new Date())
        setLoading(false)
      })
      .catch(err => {
        setError(String(err?.message || err))
        setLoading(false)
      })
  }

  useEffect(() => { load() }, [date])

  const matchupByKey = useMemo(() => {
    const map = new Map()
    matchups.forEach(m => {
      const key = keyFromMatchup(m)
      if (key !== '@') map.set(key, m)
    })
    return map
  }, [matchups])

  const modelByKey = useMemo(() => {
    const map = new Map()
    modelGamesFromPayload(modelPayload).forEach(game => {
      const key = keyFromModelGame(game)
      if (key !== '@') map.set(key, game)
    })
    return map
  }, [modelPayload])

  const topPropCandidates = useMemo(() => propCandidatesFromPayload(modelPayload), [modelPayload])

  const rows = useMemo(() => events.map(event => {
    const key = keyFromEvent(event)
    const matchup = matchupByKey.get(key)
    const model = modelByKey.get(key)
    return { event, matchup, model, matched: Boolean(matchup), key }
  }), [events, matchupByKey, modelByKey])

  const matchedCount = rows.filter(r => r.matched).length
  const unmatchedCount = rows.length - matchedCount
  const modelCount = modelGamesFromPayload(modelPayload).length

  return (
    <div style={s.page}>
      <section style={s.hero}>
        <div style={s.header}>
          <div>
            <div style={s.eyebrow}>DraftKings board</div>
            <h1 style={s.title}>Daily Odds</h1>
            <div style={s.subtitle}>Moneyline, run line, totals, prop market selectors, event IDs, MLB game matching, GameModelPanel, ModelCard, and Top Prop Model Candidates in one clean board.</div>
          </div>
          <div style={s.controls}>
            <input type="date" value={date} onChange={e => setDate(e.target.value)} style={s.input} />
            <button type="button" style={s.button} onClick={load} disabled={loading}>{loading ? 'Refreshing...' : 'Refresh Odds'}</button>
          </div>
        </div>

        <div style={s.stats}>
          <div style={s.statCard}><div style={s.statLabel}>MLB Games</div><div style={s.statValue}>{matchups.length}</div></div>
          <div style={s.statCard}><div style={s.statLabel}>DK Events</div><div style={s.statValue}>{events.length}</div></div>
          <div style={s.statCard}><div style={s.statLabel}>Matched</div><div style={s.statValue}>{matchedCount}</div></div>
          <div style={s.statCard}><div style={s.statLabel}>Model Games</div><div style={s.statValue}>{modelCount}</div></div>
          <div style={s.statCard}><div style={s.statLabel}>Top Props</div><div style={s.statValue}>{topPropCandidates.length}</div></div>
          <div style={s.statCard}><div style={s.statLabel}>Last Refreshed</div><div style={{ ...s.statValue, fontSize: '15px' }}>{lastRefreshed ? lastRefreshed.toLocaleTimeString() : '—'}</div></div>
        </div>
      </section>

      <div style={s.toolbar}>
        <div style={s.toolbarText}>{rows.length} sportsbook events loaded for {date}</div>
        <div style={s.toolbarText}>Use each game’s prop selector to choose exactly which player prop market to price.</div>
      </div>

      {error && <div style={s.error}>{error}</div>}
      {modelError && <div style={s.error}>Model panel error: {modelError}</div>}
      {loading && <div style={s.loader}>Loading daily odds...</div>}
      {!loading && !error && rows.length === 0 && <div style={s.empty}>No DraftKings events returned for {date}.</div>}

      {!loading && !error && <TopPropModelCandidates candidates={topPropCandidates} />}

      <div style={s.grid}>
        {rows.map(({ event, matchup, model, matched, key }, idx) => {
          const away = event?.away_team?.name || event?.away_team || matchup?.away_team_name || 'Away'
          const home = event?.home_team?.name || event?.home_team || matchup?.home_team_name || 'Home'
          const moneyline = findMarket(event, 'h2h')
          const spread = findMarket(event, 'spreads')
          const total = findMarket(event, 'totals')
          return (
            <article key={`${event.event_id || key || idx}`} style={s.card}>
              <div style={s.cardTop}>
                <div>
                  <div style={s.matchup}>{away} @ {home}</div>
                  <div style={s.metaRow}>
                    <span style={s.chip}>Time: {formatTime(matchup?.game_time || event?.start_time || event?.commence_time)}</span>
                    <span style={s.chip}>MLB: {matchup?.game_pk ? <Link to={`/matchup/${matchup.game_pk}`} style={{ color: '#58a6ff', textDecoration: 'none' }}>{matchup.game_pk}</Link> : '—'}</span>
                    <span style={s.chip}>DK: {event.event_id || '—'}</span>
                    <span style={s.chip}>Model: {model ? 'loaded' : 'none'}</span>
                  </div>
                </div>
                <span style={s.badge(matched)}>{matched ? 'MATCHED' : 'UNMATCHED'}</span>
              </div>

              <GameModelPanel model={model} />
              {event.event_id && <PerGamePropCandidates eventId={event.event_id} />}

              <div style={s.markets}>
                <MarketBox label="Moneyline" market={moneyline} />
                <MarketBox label="Run Line" market={spread} />
                <MarketBox label="Total" market={total} />
              </div>

              {event.event_id && <PropsPanel eventId={event.event_id} />}
            </article>
          )
        })}
      </div>
    </div>
  )
}

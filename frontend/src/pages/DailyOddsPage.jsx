import React, { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'

const API = import.meta.env.VITE_API_BASE_URL || ''

const s = {
  header: { display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: '16px', flexWrap: 'wrap', marginBottom: '24px' },
  title: { fontSize: '24px', fontWeight: '700', color: '#e6edf3', margin: 0 },
  subtitle: { color: '#8b949e', fontSize: '13px', marginTop: '6px' },
  controls: { display: 'flex', gap: '10px', alignItems: 'center', flexWrap: 'wrap' },
  input: { background: '#161b22', border: '1px solid #30363d', color: '#e6edf3', borderRadius: '6px', padding: '8px 12px', fontSize: '14px' },
  select: { background: '#0d1117', border: '1px solid #30363d', color: '#e6edf3', borderRadius: '8px', padding: '8px 10px', fontSize: '13px', minWidth: '220px' },
  button: { background: '#238636', border: '1px solid #2ea043', color: '#fff', borderRadius: '6px', padding: '8px 12px', fontSize: '13px', fontWeight: '700', cursor: 'pointer' },
  mutedButton: { background: '#21262d', border: '1px solid #30363d', color: '#58a6ff', borderRadius: '6px', padding: '7px 10px', fontSize: '12px', fontWeight: '700', cursor: 'pointer' },
  stats: { display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))', gap: '10px', marginBottom: '20px' },
  statCard: { background: '#161b22', border: '1px solid #30363d', borderRadius: '8px', padding: '12px' },
  statLabel: { color: '#8b949e', fontSize: '11px', textTransform: 'uppercase', letterSpacing: '0.7px', fontWeight: '700' },
  statValue: { color: '#e6edf3', fontSize: '22px', fontWeight: '800', marginTop: '4px' },
  grid: { display: 'grid', gap: '12px' },
  card: { background: '#161b22', border: '1px solid #30363d', borderRadius: '10px', padding: '16px' },
  cardHeader: { display: 'flex', justifyContent: 'space-between', gap: '14px', alignItems: 'flex-start', flexWrap: 'wrap', marginBottom: '12px' },
  matchup: { color: '#e6edf3', fontSize: '17px', fontWeight: '800' },
  meta: { color: '#8b949e', fontSize: '12px', marginTop: '4px' },
  badge: matched => ({ display: 'inline-block', borderRadius: '999px', padding: '3px 8px', fontSize: '11px', fontWeight: '800', background: matched ? '#1f3a1f' : '#3b2222', color: matched ? '#3fb950' : '#f85149' }),
  markets: { display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(210px, 1fr))', gap: '10px', marginTop: '12px' },
  market: { border: '1px solid #21262d', borderRadius: '8px', padding: '10px', background: '#0d1117' },
  marketTitle: { color: '#8b949e', fontSize: '11px', textTransform: 'uppercase', letterSpacing: '0.7px', fontWeight: '800', marginBottom: '8px' },
  oddsLine: { display: 'flex', justifyContent: 'space-between', gap: '8px', color: '#e6edf3', fontSize: '13px', marginTop: '5px' },
  props: { marginTop: '12px', borderTop: '1px solid #30363d', paddingTop: '12px' },
  propControls: { display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: '10px', marginBottom: '10px' },
  propsGrid: { display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(230px, 1fr))', gap: '8px' },
  propCard: { border: '1px solid #21262d', borderRadius: '8px', padding: '9px', background: '#0d1117' },
  propMarket: { color: '#d29922', fontSize: '11px', fontWeight: '800', marginBottom: '5px' },
  propName: { color: '#e6edf3', fontSize: '13px', fontWeight: '800' },
  propDetail: { color: '#8b949e', fontSize: '12px', marginTop: '4px' },
  error: { color: '#f85149', background: '#1f1116', border: '1px solid #3b2222', borderRadius: '8px', padding: '14px', marginBottom: '14px' },
  loader: { color: '#8b949e', textAlign: 'center', padding: '40px' },
  empty: { color: '#8b949e', textAlign: 'center', padding: '40px', border: '1px solid #30363d', borderRadius: '10px', background: '#161b22' },
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

function american(v) {
  if (v == null || v === '') return '—'
  const n = Number(v)
  if (Number.isNaN(n)) return String(v)
  return n > 0 ? `+${n}` : `${n}`
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

function MarketBox({ label, market }) {
  const selections = market?.selections || []
  return (
    <div style={s.market}>
      <div style={s.marketTitle}>{label}</div>
      {selections.length === 0 && <div style={s.oddsLine}><span>Unavailable</span><strong>—</strong></div>}
      {selections.slice(0, 3).map((sel, idx) => (
        <div key={`${label}-${idx}`} style={s.oddsLine}>
          <span>{selectionLabel(sel)}</span>
          <strong>{american(sel.price)}</strong>
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
      {open && loading && <div style={{ ...s.meta, marginTop: '10px' }}>Loading props…</div>}
      {open && error && <div style={{ color: '#f85149', fontSize: '12px', marginTop: '10px' }}>Props error: {error}</div>}
      {open && !loading && !error && data && props.length === 0 && <div style={{ ...s.meta, marginTop: '10px' }}>No props returned for this selection.</div>}
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
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const [lastRefreshed, setLastRefreshed] = useState(null)

  function load() {
    setLoading(true)
    setError(null)
    Promise.all([
      fetch(`${API}/matchups?date=${date}`).then(async r => {
        if (!r.ok) throw new Error(`/matchups failed: ${r.status} ${r.statusText}: ${await r.text()}`)
        return r.json()
      }),
      fetch(`${API}/odds/draftkings/events?date=${date}`).then(async r => {
        if (!r.ok) throw new Error(`/odds/draftkings/events failed: ${r.status} ${r.statusText}: ${await r.text()}`)
        return r.json()
      }),
    ])
      .then(([matchupData, oddsData]) => {
        setMatchups(Array.isArray(matchupData) ? matchupData : [])
        setEvents(Array.isArray(oddsData?.events) ? oddsData.events : [])
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

  const rows = useMemo(() => events.map(event => {
    const key = keyFromEvent(event)
    const matchup = matchupByKey.get(key)
    return { event, matchup, matched: Boolean(matchup), key }
  }), [events, matchupByKey])

  const matchedCount = rows.filter(r => r.matched).length
  const unmatchedCount = rows.length - matchedCount

  return (
    <div>
      <div style={s.header}>
        <div>
          <h1 style={s.title}>Daily Odds</h1>
          <div style={s.subtitle}>Full DraftKings board with MLB matchup matching, market odds, and selectable player props.</div>
        </div>
        <div style={s.controls}>
          <input type="date" value={date} onChange={e => setDate(e.target.value)} style={s.input} />
          <button type="button" style={s.button} onClick={load} disabled={loading}>{loading ? 'Refreshing…' : 'Refresh Odds'}</button>
        </div>
      </div>

      <div style={s.stats}>
        <div style={s.statCard}><div style={s.statLabel}>MLB Games</div><div style={s.statValue}>{matchups.length}</div></div>
        <div style={s.statCard}><div style={s.statLabel}>DK Events</div><div style={s.statValue}>{events.length}</div></div>
        <div style={s.statCard}><div style={s.statLabel}>Matched</div><div style={s.statValue}>{matchedCount}</div></div>
        <div style={s.statCard}><div style={s.statLabel}>Unmatched</div><div style={s.statValue}>{unmatchedCount}</div></div>
        <div style={s.statCard}><div style={s.statLabel}>Last Refreshed</div><div style={{ ...s.statValue, fontSize: '14px' }}>{lastRefreshed ? lastRefreshed.toLocaleTimeString() : '—'}</div></div>
      </div>

      {error && <div style={s.error}>{error}</div>}
      {loading && <div style={s.loader}>Loading daily odds…</div>}
      {!loading && !error && rows.length === 0 && <div style={s.empty}>No DraftKings events returned for {date}.</div>}

      <div style={s.grid}>
        {rows.map(({ event, matchup, matched, key }, idx) => {
          const away = event?.away_team?.name || event?.away_team || matchup?.away_team_name || 'Away'
          const home = event?.home_team?.name || event?.home_team || matchup?.home_team_name || 'Home'
          const moneyline = findMarket(event, 'h2h')
          const spread = findMarket(event, 'spreads')
          const total = findMarket(event, 'totals')
          return (
            <div key={`${event.event_id || key || idx}`} style={s.card}>
              <div style={s.cardHeader}>
                <div>
                  <div style={s.matchup}>{away} @ {home}</div>
                  <div style={s.meta}>Game time: {formatTime(matchup?.game_time || event?.start_time || event?.commence_time)}</div>
                  <div style={s.meta}>MLB game_pk: {matchup?.game_pk ? <Link to={`/matchup/${matchup.game_pk}`} style={{ color: '#58a6ff' }}>{matchup.game_pk}</Link> : '—'} · DK event ID: {event.event_id || '—'}</div>
                  <div style={s.meta}>MLB teams: {matchup ? `${matchup.away_team_name} @ ${matchup.home_team_name}` : 'No matched MLB game'} · DK teams: {away} @ {home}</div>
                </div>
                <span style={s.badge(matched)}>{matched ? 'MATCHED' : 'UNMATCHED'}</span>
              </div>

              <div style={s.markets}>
                <MarketBox label="Moneyline" market={moneyline} />
                <MarketBox label="Run Line" market={spread} />
                <MarketBox label="Total" market={total} />
              </div>

              {event.event_id && <PropsPanel eventId={event.event_id} />}
            </div>
          )
        })}
      </div>
    </div>
  )
}

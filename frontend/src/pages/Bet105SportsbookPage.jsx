import React, { useEffect, useMemo, useState } from 'react'
import { API_BASE, fetchJson, getMlbToday } from '../lib/api'

const TTL = 75

const s = {
  page: { display: 'grid', gap: 18, color: '#e6edf3' },
  hero: { position: 'relative', overflow: 'hidden', border: '1px solid rgba(88,166,255,.22)', borderRadius: 24, padding: 22, background: 'radial-gradient(circle at 15% 0%, rgba(35,134,54,.22), transparent 34%), radial-gradient(circle at 90% 10%, rgba(88,166,255,.18), transparent 28%), linear-gradient(135deg, #07111f 0%, #0d1117 52%, #111827 100%)', boxShadow: '0 22px 70px rgba(0,0,0,.38)' },
  header: { display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 18, flexWrap: 'wrap' },
  eyebrow: { color: '#7ee787', fontSize: 12, textTransform: 'uppercase', letterSpacing: 1.3, fontWeight: 950 },
  title: { margin: '6px 0 0', fontSize: 34, lineHeight: 1, fontWeight: 950, color: '#f0f6fc' },
  subtitle: { marginTop: 9, color: '#9ba7b4', maxWidth: 820, fontSize: 14, lineHeight: 1.55 },
  controls: { display: 'flex', gap: 10, flexWrap: 'wrap', alignItems: 'center' },
  input: { background: 'rgba(1,4,9,.72)', border: '1px solid #30363d', color: '#e6edf3', borderRadius: 12, padding: '10px 12px', outline: 'none', fontWeight: 800 },
  button: { border: '1px solid rgba(63,185,80,.65)', color: '#fff', background: 'linear-gradient(135deg,#238636,#2ea043)', borderRadius: 12, padding: '10px 14px', fontWeight: 950, cursor: 'pointer' },
  mutedButton: { border: '1px solid #30363d', color: '#58a6ff', background: '#161b22', borderRadius: 12, padding: '10px 14px', fontWeight: 900, cursor: 'pointer' },
  tabs: { display: 'flex', gap: 8, flexWrap: 'wrap', marginTop: 18 },
  tab: active => ({ border: active ? '1px solid rgba(88,166,255,.75)' : '1px solid #30363d', background: active ? 'rgba(88,166,255,.16)' : 'rgba(13,17,23,.72)', color: active ? '#dbeafe' : '#8b949e', borderRadius: 999, padding: '8px 12px', fontWeight: 950, cursor: 'pointer' }),
  stats: { display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(150px,1fr))', gap: 10, marginTop: 18 },
  stat: { background: 'rgba(13,17,23,.72)', border: '1px solid rgba(48,54,61,.88)', borderRadius: 16, padding: 14 },
  statLabel: { color: '#8b949e', fontSize: 10, textTransform: 'uppercase', letterSpacing: .9, fontWeight: 950 },
  statValue: { marginTop: 6, color: '#f0f6fc', fontSize: 23, fontWeight: 950 },
  shell: { display: 'grid', gridTemplateColumns: '280px minmax(0,1fr) 340px', gap: 16, alignItems: 'start' },
  panel: { background: 'linear-gradient(180deg,rgba(22,27,34,.97),rgba(13,17,23,.97))', border: '1px solid #30363d', borderRadius: 20, boxShadow: '0 14px 42px rgba(0,0,0,.22)' },
  panelInner: { padding: 15 },
  panelTitle: { color: '#f0f6fc', fontSize: 15, fontWeight: 950 },
  panelSub: { color: '#8b949e', fontSize: 12, marginTop: 4, lineHeight: 1.4 },
  gameButton: active => ({ width: '100%', textAlign: 'left', border: active ? '1px solid rgba(88,166,255,.76)' : '1px solid rgba(48,54,61,.75)', background: active ? 'linear-gradient(135deg,rgba(88,166,255,.18),rgba(63,185,80,.08))' : '#0d1117', borderRadius: 14, padding: 12, color: '#e6edf3', cursor: 'pointer', marginTop: 10 }),
  gameName: { fontWeight: 950, fontSize: 13.5, lineHeight: 1.3 },
  chipRow: { display: 'flex', gap: 7, flexWrap: 'wrap', marginTop: 8 },
  chip: { color: '#8b949e', border: '1px solid #30363d', borderRadius: 999, padding: '4px 8px', fontSize: 10.5, fontWeight: 850, background: 'rgba(1,4,9,.44)' },
  boardHero: { borderBottom: '1px solid #30363d', padding: 18, background: 'linear-gradient(135deg,rgba(88,166,255,.13),rgba(126,231,135,.07))' },
  matchup: { fontSize: 24, fontWeight: 950, color: '#f0f6fc' },
  marketWrap: { padding: 16, display: 'grid', gap: 12 },
  accordion: { border: '1px solid #30363d', borderRadius: 16, overflow: 'hidden', background: '#0d1117' },
  accordionHead: { padding: '13px 14px', display: 'flex', justifyContent: 'space-between', alignItems: 'center', background: '#111820', borderBottom: '1px solid #30363d' },
  marketTitle: { fontWeight: 950, color: '#f0f6fc' },
  oddsGrid: { display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(160px,1fr))', gap: 10, padding: 12 },
  oddsButton: active => ({ textAlign: 'left', border: active ? '1px solid rgba(63,185,80,.85)' : '1px solid #30363d', background: active ? 'linear-gradient(135deg,rgba(35,134,54,.3),rgba(13,17,23,.96))' : 'linear-gradient(180deg,#161b22,#0d1117)', borderRadius: 14, padding: 12, cursor: 'pointer', color: '#e6edf3', minHeight: 92, boxShadow: active ? '0 0 0 3px rgba(63,185,80,.12)' : 'none' }),
  oddsLabel: { color: '#c9d1d9', fontWeight: 900, fontSize: 13, lineHeight: 1.25 },
  oddsPrice: { marginTop: 8, color: '#7ee787', fontSize: 20, fontWeight: 950 },
  oddsMeta: { marginTop: 6, color: '#8b949e', fontSize: 11, display: 'flex', justifyContent: 'space-between', gap: 8 },
  slip: { position: 'sticky', top: 14 },
  leg: { border: '1px solid #30363d', borderRadius: 14, padding: 12, background: '#0d1117', marginTop: 10 },
  remove: { border: 'none', background: 'transparent', color: '#f85149', cursor: 'pointer', fontWeight: 950 },
  calcGrid: { display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8, marginTop: 12 },
  calcBox: { border: '1px solid #30363d', borderRadius: 12, padding: 10, background: '#010409' },
  calcLabel: { color: '#8b949e', fontSize: 10, textTransform: 'uppercase', fontWeight: 950 },
  calcValue: { color: '#f0f6fc', fontWeight: 950, marginTop: 4 },
  tableWrap: { overflowX: 'auto', border: '1px solid #30363d', borderRadius: 18, background: '#0d1117' },
  table: { width: '100%', borderCollapse: 'collapse', minWidth: 980 },
  th: { textAlign: 'left', color: '#8b949e', fontSize: 11, textTransform: 'uppercase', letterSpacing: .7, padding: 11, background: '#111820', borderBottom: '1px solid #30363d' },
  td: { color: '#c9d1d9', padding: 11, borderBottom: '1px solid #21262d', fontSize: 12.5 },
  error: { color: '#ffb4b4', background: '#2b1218', border: '1px solid #6e2633', borderRadius: 16, padding: 14 },
  empty: { color: '#8b949e', textAlign: 'center', padding: 24, border: '1px solid #30363d', borderRadius: 16, background: '#0d1117' },
}

function asArray(value) { return Array.isArray(value) ? value : [] }
function hasPrice(selection) { return selection?.price !== null && selection?.price !== undefined && Number.isFinite(Number(selection.price)) }
function teamName(team) {
  if (!team) return null
  if (typeof team === 'string') return team
  return team.name || team.display_name || team.displayName || team.fullName || team.full_name || team.team?.name || team.participant?.name || null
}
function eventName(event) {
  const away = teamName(event?.away_team) || 'Away'
  const home = teamName(event?.home_team) || 'Home'
  return `${away} @ ${home}`
}
function formatTime(iso) { if (!iso) return 'Time pending'; try { return new Date(iso).toLocaleString('en-US', { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit', timeZone: 'America/New_York' }) + ' ET' } catch { return 'Time pending' } }
function american(price) { const n = Number(price); if (!Number.isFinite(n)) return '—'; return n > 0 ? `+${n}` : `${n}` }
function pct(v) { const n = Number(v); if (!Number.isFinite(n)) return '—'; return `${Math.round(n * 1000) / 10}%` }
function cleanMarketName(name) { return String(name || 'Market').replaceAll('_', ' ') }
function marketKey(m) { return String(m?.market_key || m?.market_type || m?.market_name || 'other') }
function selectionLabel(sel) { return `${sel?.description || sel?.name || sel?.team || 'Selection'}${sel?.line != null ? ` ${sel.line}` : ''}` }
function legKey(leg) { return [leg.event_id, leg.market_key, leg.label, leg.line, leg.price].join('|') }
function americanToDecimal(price) { const n = Number(price); if (!Number.isFinite(n) || n === 0) return null; return n > 0 ? 1 + n / 100 : 1 + 100 / Math.abs(n) }
function decimalToAmerican(decimal) { const n = Number(decimal); if (!Number.isFinite(n) || n <= 1) return null; return n >= 2 ? Math.round((n - 1) * 100) : Math.round(-100 / (n - 1)) }
function categoryFor(market) { const key = marketKey(market).toLowerCase(); if (['h2h', 'spreads', 'totals'].includes(key)) return 'Game Lines'; if (key.includes('batter')) return 'Batter Props'; if (key.includes('pitcher')) return 'Pitcher Props'; if (key.includes('inning') || key.includes('period')) return 'Innings / Periods'; if (key.includes('team')) return 'Team Props'; return 'Other Markets' }
function groupMarkets(event) {
  const groups = { Featured: [], 'Game Lines': [], 'Team Props': [], 'Batter Props': [], 'Pitcher Props': [], 'Innings / Periods': [], 'Other Markets': [] }
  asArray(event?.markets)
    .map(market => ({ ...market, selections: asArray(market?.selections).filter(hasPrice) }))
    .filter(market => market.selections.length)
    .forEach(market => {
      const cat = categoryFor(market)
      groups[cat].push(market)
      if (['h2h', 'spreads', 'totals'].includes(marketKey(market))) groups.Featured.push(market)
    })
  return groups
}

function OddsButton({ event, market, selection, selected, onToggle }) {
  const leg = { book: 'Bet105', event_id: event.event_id, game: eventName(event), market_key: marketKey(market), market_name: market.market_name || marketKey(market), label: selectionLabel(selection), selection: selection.name || selection.description, line: selection.line, price: selection.price, implied_probability: selection?.odds?.implied_probability }
  return <button type="button" style={s.oddsButton(selected)} onClick={() => onToggle(leg)}>
    <div style={s.oddsLabel}>{leg.label}</div>
    <div style={s.oddsPrice}>{american(leg.price)}</div>
    <div style={s.oddsMeta}><span>Bet105</span><span>Imp {pct(leg.implied_probability)}</span></div>
  </button>
}

function BetSlip({ legs, stake, setStake, onRemove, onClear }) {
  const decimal = legs.reduce((product, leg) => product * (americanToDecimal(leg.price) || 1), 1)
  const activeDecimal = legs.length ? decimal : null
  const stakeValue = Number(stake || 0)
  const payout = activeDecimal ? stakeValue * activeDecimal : 0
  const profit = Math.max(payout - stakeValue, 0)
  const warnings = new Set()
  const seen = new Set()
  legs.forEach(leg => { const key = `${leg.event_id}:${leg.market_key}`; if (seen.has(key)) warnings.add('Multiple selections from the same game market may be correlated.'); seen.add(key) })
  return <aside style={{ ...s.panel, ...s.slip }}>
    <div style={s.panelInner}>
      <div style={{ display: 'flex', justifyContent: 'space-between', gap: 10, alignItems: 'center' }}><div><div style={s.panelTitle}>Bet Slip</div><div style={s.panelSub}>Informational parlay calculator. No wagers are placed.</div></div>{legs.length > 0 && <button type="button" style={s.remove} onClick={onClear}>Clear</button>}</div>
      {legs.length === 0 && <div style={{ ...s.empty, marginTop: 12 }}>Tap any Bet105 price to build a slip.</div>}
      {legs.map(leg => <div key={legKey(leg)} style={s.leg}>
        <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8 }}><strong>{leg.label}</strong><button type="button" style={s.remove} onClick={() => onRemove(leg)}>×</button></div>
        <div style={s.panelSub}>{leg.game}</div>
        <div style={s.chipRow}><span style={s.chip}>{cleanMarketName(leg.market_name)}</span><span style={s.chip}>{american(leg.price)}</span></div>
      </div>)}
      {Array.from(warnings).map(w => <div key={w} style={{ ...s.panelSub, color: '#f2cc60', marginTop: 10 }}>{w}</div>)}
      <label style={{ display: 'block', marginTop: 13 }}><div style={s.panelSub}>Simulated stake</div><input type="number" min="0" step="1" value={stake} onChange={e => setStake(e.target.value)} style={{ ...s.input, width: '100%', marginTop: 6 }} /></label>
      <div style={s.calcGrid}>
        <div style={s.calcBox}><div style={s.calcLabel}>Decimal</div><div style={s.calcValue}>{activeDecimal ? activeDecimal.toFixed(4) : '—'}</div></div>
        <div style={s.calcBox}><div style={s.calcLabel}>American</div><div style={s.calcValue}>{activeDecimal ? american(decimalToAmerican(activeDecimal)) : '—'}</div></div>
        <div style={s.calcBox}><div style={s.calcLabel}>Implied</div><div style={s.calcValue}>{activeDecimal ? pct(1 / activeDecimal) : '—'}</div></div>
        <div style={s.calcBox}><div style={s.calcLabel}>Payout</div><div style={s.calcValue}>${payout.toFixed(2)}</div></div>
      </div>
      <div style={{ ...s.calcBox, marginTop: 8 }}><div style={s.calcLabel}>Potential profit</div><div style={{ ...s.calcValue, color: '#7ee787', fontSize: 22 }}>${profit.toFixed(2)}</div></div>
    </div>
  </aside>
}

function MarketBoard({ event, selectedKeys, onToggle }) {
  const groups = groupMarkets(event)
  const ordered = ['Featured', 'Game Lines', 'Batter Props', 'Pitcher Props', 'Team Props', 'Innings / Periods', 'Other Markets']
  return <section style={s.panel}>
    <div style={s.boardHero}><div style={s.matchup}>{eventName(event)}</div><div style={s.chipRow}><span style={s.chip}>{formatTime(event?.start_time)}</span><span style={s.chip}>Bet105</span><span style={s.chip}>{asArray(event?.markets).length} markets</span></div></div>
    <div style={s.marketWrap}>{ordered.map(category => {
      const markets = groups[category] || []
      if (!markets.length) return null
      return <div key={category} style={s.accordion}><div style={s.accordionHead}><div style={s.marketTitle}>{category}</div><span style={s.chip}>{markets.length} markets</span></div>{markets.map((market, idx) => <div key={`${category}-${marketKey(market)}-${idx}`}><div style={{ ...s.panelSub, padding: '12px 12px 0', color: '#58a6ff', fontWeight: 950 }}>{cleanMarketName(market.market_name || marketKey(market))}</div><div style={s.oddsGrid}>{asArray(market.selections).filter(hasPrice).map((selection, sidx) => { const tempLeg = { event_id: event.event_id, market_key: marketKey(market), label: selectionLabel(selection), line: selection.line, price: selection.price }; return <OddsButton key={`${selectionLabel(selection)}-${selection.price}-${sidx}`} event={event} market={market} selection={selection} selected={selectedKeys.has(legKey(tempLeg))} onToggle={onToggle} /> })}</div></div>)}</div>
    })}</div>
  </section>
}

function ComparisonPanel({ comparison, loading, error }) {
  const rows = []
  asArray(comparison?.events).forEach(event => asArray(event.markets).forEach(market => asArray(market.selections).forEach(selection => rows.push({ event, market, selection }))))
  return <section style={s.panel}><div style={s.panelInner}><div style={s.panelTitle}>Bet105 vs DraftKings</div><div style={s.panelSub}>Best-price comparison across normalized markets. Model edge columns can be joined here as the Daily Odds model payload expands.</div></div>{loading && <div style={s.empty}>Loading comparison board...</div>}{error && <div style={{ ...s.error, margin: 16 }}>{error}</div>}{!loading && !error && rows.length === 0 && <div style={{ ...s.empty, margin: 16 }}>No comparable rows returned.</div>}{rows.length > 0 && <div style={s.tableWrap}><table style={s.table}><thead><tr><th style={s.th}>Game</th><th style={s.th}>Market</th><th style={s.th}>Selection</th><th style={s.th}>Line</th><th style={s.th}>Bet105</th><th style={s.th}>DraftKings</th><th style={s.th}>Best</th><th style={s.th}>Gap</th><th style={s.th}>Model Prob</th><th style={s.th}>Edge</th></tr></thead><tbody>{rows.slice(0, 250).map(({ event, market, selection }, idx) => { const bet105 = selection.books?.bet105; const dk = selection.books?.draftkings; return <tr key={`${event.match_key}-${market.market_key}-${selection.selection_key}-${idx}`}><td style={s.td}>{event.away_team} @ {event.home_team}</td><td style={s.td}>{cleanMarketName(market.market_name || market.market_key)}</td><td style={s.td}>{selection.label}</td><td style={s.td}>{selection.line ?? '—'}</td><td style={{ ...s.td, color: selection.best_book === 'bet105' ? '#7ee787' : '#c9d1d9', fontWeight: 950 }}>{bet105 ? american(bet105.price) : '—'}</td><td style={{ ...s.td, color: selection.best_book === 'draftkings' ? '#7ee787' : '#c9d1d9', fontWeight: 950 }}>{dk ? american(dk.price) : '—'}</td><td style={s.td}>{selection.best_book || '—'}</td><td style={s.td}>{selection.price_gap ?? '—'}</td><td style={s.td}>Pending</td><td style={s.td}>Pending</td></tr> })}</tbody></table></div>}</section>
}

export default function Bet105SportsbookPage() {
  const [date, setDate] = useState(getMlbToday())
  const [live, setLive] = useState(false)
  const [activeTab, setActiveTab] = useState('board')
  const [payload, setPayload] = useState(null)
  const [comparison, setComparison] = useState(null)
  const [selectedEventId, setSelectedEventId] = useState('')
  const [legs, setLegs] = useState([])
  const [stake, setStake] = useState('25')
  const [loading, setLoading] = useState(false)
  const [compareLoading, setCompareLoading] = useState(false)
  const [error, setError] = useState(null)
  const [compareError, setCompareError] = useState(null)
  const [lastRefreshed, setLastRefreshed] = useState(null)

  const events = asArray(payload?.events)
  const marketCount = Number(payload?.market_count ?? events.reduce((sum, event) => sum + asArray(event.markets).length, 0))
  const boardEvents = marketCount > 0 ? events.filter(event => asArray(event.markets).some(market => asArray(market.selections).some(hasPrice))) : []
  const selectedEvent = boardEvents.find(event => String(event.event_id) === String(selectedEventId)) || boardEvents[0]
  const selectedKeys = useMemo(() => new Set(legs.map(legKey)), [legs])

  function load(forceRefresh = false) {
    setLoading(true); setError(null)
    const url = `${API_BASE}/odds/bet105/events?date=${date}&live=${live ? 'true' : 'false'}`
    fetchJson(url, { ttlSeconds: TTL, forceRefresh }).then(json => {
      const nextEvents = asArray(json?.events)
      const nextMarketCount = Number(json?.market_count ?? nextEvents.reduce((sum, event) => sum + asArray(event.markets).length, 0))
      setPayload(json)
      setSelectedEventId(nextMarketCount > 0 ? nextEvents[0]?.event_id || '' : '')
      setLastRefreshed(new Date())
      setLoading(false)
    }).catch(err => { setError(String(err?.message || err)); setLoading(false) })
  }

  function loadComparison(forceRefresh = false) {
    setCompareLoading(true); setCompareError(null)
    const url = `${API_BASE}/odds/compare/events?date=${date}&books=bet105,draftkings`
    fetchJson(url, { ttlSeconds: TTL, forceRefresh }).then(json => { setComparison(json); setCompareLoading(false) }).catch(err => { setCompareError(String(err?.message || err)); setCompareLoading(false) })
  }

  function toggleLeg(leg) { const key = legKey(leg); setLegs(prev => prev.some(item => legKey(item) === key) ? prev.filter(item => legKey(item) !== key) : [...prev, leg]) }
  function removeLeg(leg) { const key = legKey(leg); setLegs(prev => prev.filter(item => legKey(item) !== key)) }

  useEffect(() => { load(false) }, [date, live])
  useEffect(() => { setComparison(null) }, [date])
  useEffect(() => { if (activeTab === 'compare') loadComparison(false) }, [activeTab, date])

  return <div style={s.page}>
    <style>{`@media (max-width: 1100px){.bet105-shell{grid-template-columns:1fr!important}.bet105-slip{position:static!important}.bet105-game-rail{order:1}.bet105-board{order:2}.bet105-slip{order:3}}`}</style>
    <section style={s.hero}><div style={s.header}><div><div style={s.eyebrow}>Bet105 Sportsbook</div><h1 style={s.title}>Premium MLB Odds Board</h1><div style={s.subtitle}>Browse normalized Bet105 markets, build an informational slip, and compare prices against DraftKings without leaving MLBGPT.</div></div><div style={s.controls}><input type="date" value={date} onChange={e => setDate(e.target.value)} style={s.input} /><button type="button" style={live ? s.button : s.mutedButton} onClick={() => setLive(v => !v)}>{live ? 'Live On' : 'Prematch'}</button><button type="button" style={s.button} onClick={() => { load(true); if (activeTab === 'compare') loadComparison(true) }} disabled={loading}>{loading ? 'Refreshing...' : 'Refresh'}</button></div></div><div style={s.tabs}><button type="button" style={s.tab(activeTab === 'board')} onClick={() => setActiveTab('board')}>Sportsbook Board</button><button type="button" style={s.tab(activeTab === 'compare')} onClick={() => setActiveTab('compare')}>Compare Books</button></div><div style={s.stats}><div style={s.stat}><div style={s.statLabel}>Bet105 Events</div><div style={s.statValue}>{events.length}</div></div><div style={s.stat}><div style={s.statLabel}>Markets</div><div style={s.statValue}>{marketCount}</div></div><div style={s.stat}><div style={s.statLabel}>Slip Legs</div><div style={s.statValue}>{legs.length}</div></div><div style={s.stat}><div style={s.statLabel}>Provider</div><div style={{ ...s.statValue, fontSize: 16 }}>{payload?.status || 'pending'}</div></div><div style={s.stat}><div style={s.statLabel}>Last Refreshed</div><div style={{ ...s.statValue, fontSize: 16 }}>{lastRefreshed ? lastRefreshed.toLocaleTimeString() : 'Not loaded'}</div></div></div></section>
    {error && <div style={s.error}>{error}</div>}
    {activeTab === 'board' && <div className="bet105-shell" style={s.shell}><aside className="bet105-game-rail" style={s.panel}><div style={s.panelInner}><div style={s.panelTitle}>Games</div><div style={s.panelSub}>Select a game to expand all available Bet105 markets.</div>{loading && <div style={{ ...s.empty, marginTop: 12 }}>Loading board...</div>}{!loading && events.length === 0 && <div style={{ ...s.empty, marginTop: 12 }}>No Bet105 events returned for {date}.</div>}{!loading && events.length > 0 && marketCount === 0 && <div style={{ ...s.empty, marginTop: 12 }}>Bet105 returned fixtures but no markets for {date}.</div>}{boardEvents.map(event => <button type="button" key={event.event_id} style={s.gameButton(String(event.event_id) === String(selectedEvent?.event_id))} onClick={() => setSelectedEventId(event.event_id)}><div style={s.gameName}>{eventName(event)}</div><div style={s.chipRow}><span style={s.chip}>{formatTime(event.start_time)}</span><span style={s.chip}>{asArray(event.markets).length} markets</span></div></button>)}</div></aside><main className="bet105-board">{marketCount > 0 && selectedEvent ? <MarketBoard event={selectedEvent} selectedKeys={selectedKeys} onToggle={toggleLeg} /> : <div style={s.empty}>{events.length > 0 ? 'No Bet105 market board is available for this slate yet.' : 'Choose a game to view markets.'}</div>}</main><div className="bet105-slip"><BetSlip legs={legs} stake={stake} setStake={setStake} onRemove={removeLeg} onClear={() => setLegs([])} /></div></div>}
    {activeTab === 'compare' && <ComparisonPanel comparison={comparison} loading={compareLoading} error={compareError} />}
  </div>
}

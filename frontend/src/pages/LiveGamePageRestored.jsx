import React, { useEffect, useMemo, useRef, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { API_BASE } from '../lib/api'

const REFRESH_LIVE_MS = 15000
const MLB_LIVE_BASE = 'https://statsapi.mlb.com/api/v1.1/game'

const s = {
  muted: { color: '#8b949e' },
  link: { color: '#58a6ff', textDecoration: 'none' },
  card: { background: '#0d1117', border: '1px solid #30363d', borderRadius: '10px', padding: '16px' },
  tab: active => ({ background: 'transparent', border: 0, borderBottom: active ? '2px solid #58a6ff' : '2px solid transparent', color: active ? '#e6edf3' : '#8b949e', padding: '10px 14px', cursor: 'pointer', fontWeight: active ? 800 : 500 }),
  th: { textAlign: 'right', padding: '7px 8px', fontWeight: 600, color: '#8b949e', borderBottom: '1px solid #30363d', whiteSpace: 'nowrap' },
  td: { textAlign: 'right', padding: '7px 8px', color: '#c9d1d9', borderBottom: '1px solid #21262d', whiteSpace: 'nowrap' },
}

function pick(...values) {
  return values.find(v => v !== undefined && v !== null && v !== '')
}

function val(v) {
  return v !== undefined && v !== null && v !== '' ? String(v) : '—'
}

function toInt(v) {
  const n = Number(v)
  return Number.isFinite(n) ? n : null
}

function personObj(person) {
  if (!person) return null
  return { id: person.id, name: person.fullName || person.name || '—' }
}

function teamAbbr(team) {
  return team?.abbreviation || team?.teamCode || team?.fileCode || team?.name || '—'
}

function isLiveStatus(status, detail) {
  const raw = `${status || ''} ${detail || ''}`.toLowerCase()
  return raw.includes('live') || raw.includes('progress') || raw.includes('delayed')
}

function normalizeStatus(feed, backendState) {
  const status = feed?.gameData?.status || {}
  const abstract = status.abstractGameState || backendState?.status
  const detailed = status.detailedState || backendState?.status_detail || backendState?.status
  return {
    status: isLiveStatus(abstract, detailed) ? 'Live' : abstract || detailed || 'Unknown',
    status_detail: detailed || abstract || 'Unknown',
  }
}

function normalizeLiveState(feed, backendState = {}) {
  if (!feed) return backendState
  const gameData = feed.gameData || {}
  const liveData = feed.liveData || {}
  const linescore = liveData.linescore || {}
  const teams = gameData.teams || {}
  const currentPlay = liveData.plays?.currentPlay || {}
  const matchup = currentPlay.matchup || {}
  const count = currentPlay.count || linescore.balls !== undefined ? currentPlay.count || {} : {}
  const status = normalizeStatus(feed, backendState)
  const offense = linescore.offense || {}
  const defense = linescore.defense || {}
  const playEvents = Array.isArray(currentPlay.playEvents) ? currentPlay.playEvents : []

  return {
    game_pk: gameData.game?.pk || backendState.game_pk,
    away: {
      id: teams.away?.id || backendState.away?.id,
      name: teams.away?.name || backendState.away?.name,
      abbreviation: teamAbbr(teams.away) || backendState.away?.abbreviation,
      score: pick(linescore.teams?.away?.runs, backendState.away?.score, backendState.away?.runs),
    },
    home: {
      id: teams.home?.id || backendState.home?.id,
      name: teams.home?.name || backendState.home?.name,
      abbreviation: teamAbbr(teams.home) || backendState.home?.abbreviation,
      score: pick(linescore.teams?.home?.runs, backendState.home?.score, backendState.home?.runs),
    },
    status: status.status,
    status_detail: status.status_detail,
    inning: pick(linescore.currentInningOrdinal, linescore.currentInning, backendState.inning),
    inning_state: pick(linescore.inningState, linescore.inningHalf, backendState.inning_state),
    outs: pick(linescore.outs, currentPlay.count?.outs, backendState.outs),
    count: {
      balls: pick(currentPlay.count?.balls, linescore.balls, backendState.count?.balls),
      strikes: pick(currentPlay.count?.strikes, linescore.strikes, backendState.count?.strikes),
      outs: pick(currentPlay.count?.outs, linescore.outs, backendState.count?.outs),
    },
    runners: {
      first: offense.first?.fullName || backendState.runners?.first,
      second: offense.second?.fullName || backendState.runners?.second,
      third: offense.third?.fullName || backendState.runners?.third,
    },
    current_batter: {
      ...personObj(matchup.batter),
      bat_side: matchup.batSide?.code || matchup.batSide?.description || backendState.current_batter?.bat_side,
    },
    current_pitcher: {
      ...personObj(matchup.pitcher || defense.pitcher),
      pitch_hand: matchup.pitchHand?.code || matchup.pitchHand?.description || backendState.current_pitcher?.pitch_hand,
    },
    pitch_sequence: playEvents
      .filter(e => e.isPitch || e.details?.type?.code || e.pitchData)
      .map(e => ({
        pitch_type: e.details?.type?.description || e.details?.type?.code || e.pitchData?.type || null,
        speed_mph: e.pitchData?.startSpeed ?? e.pitchData?.endSpeed ?? null,
        call: e.details?.description || e.details?.call?.description || null,
      })),
    source: 'mlb_live_feed_restored',
  }
}

function battingLine(player) {
  const stat = player?.stats?.batting || {}
  return {
    id: player?.person?.id,
    name: player?.person?.fullName || player?.person?.name || '—',
    position: player?.position?.abbreviation || player?.position?.code || '—',
    batting_order: toInt(player?.battingOrder),
    at_bats: pick(stat.atBats, stat.ab),
    runs: stat.runs,
    hits: stat.hits,
    rbi: stat.rbi,
    home_runs: pick(stat.homeRuns, stat.hr),
    walks: pick(stat.baseOnBalls, stat.walks, stat.bb),
    strikeouts: pick(stat.strikeOuts, stat.strikeouts, stat.k),
    season_avg: pick(stat.avg, stat.battingAverage),
    season_ops: stat.ops,
  }
}

function pitchingLine(player, currentPitcherId) {
  const stat = player?.stats?.pitching || {}
  return {
    id: player?.person?.id,
    name: player?.person?.fullName || player?.person?.name || '—',
    innings_pitched: pick(stat.inningsPitched, stat.ip),
    hits: stat.hits,
    runs: stat.runs,
    earned_runs: pick(stat.earnedRuns, stat.er),
    walks: pick(stat.baseOnBalls, stat.walks, stat.bb),
    strikeouts: pick(stat.strikeOuts, stat.strikeouts, stat.k),
    home_runs: pick(stat.homeRuns, stat.hr),
    pitch_count: pick(stat.numberOfPitches, stat.pitchCount, stat.pitchesThrown),
    strikes_thrown: stat.strikes,
    era: stat.era,
    is_current_pitcher: currentPitcherId && String(currentPitcherId) === String(player?.person?.id),
  }
}

function normalizeBoxscore(feed, backendBoxscore = null) {
  if (!feed?.liveData?.boxscore?.teams) return backendBoxscore
  const teams = feed.liveData.boxscore.teams
  const live = feed.liveData || {}
  const currentPitcherId = live.linescore?.defense?.pitcher?.id

  function side(which) {
    const team = teams[which] || {}
    const players = team.players || {}
    const battingOrder = Array.isArray(team.battingOrder) ? team.battingOrder.map(String) : []
    const pitcherIds = new Set((team.pitchers || []).map(String))
    const batterIds = new Set([...(team.batters || []).map(String), ...battingOrder])
    const allPlayers = Object.values(players)

    const batters = allPlayers
      .filter(p => batterIds.has(String(p?.person?.id)) || p?.stats?.batting)
      .map(battingLine)
      .filter(p => p.id)
      .sort((a, b) => (a.batting_order || 999999) - (b.batting_order || 999999))

    const pitchers = allPlayers
      .filter(p => pitcherIds.has(String(p?.person?.id)) || p?.stats?.pitching)
      .map(p => pitchingLine(p, currentPitcherId))
      .filter(p => p.id)

    return { batters, pitchers }
  }

  return { away: side('away'), home: side('home'), source: 'mlb_live_feed_restored' }
}

function normalizePlays(feed, backendPlays = null) {
  const allPlays = feed?.liveData?.plays?.allPlays
  if (!Array.isArray(allPlays)) return backendPlays
  const plays = allPlays.slice().reverse().slice(0, 60).map(play => {
    const result = play.result || {}
    const about = play.about || {}
    const matchup = play.matchup || {}
    const hit = play.playEvents?.slice().reverse().find(e => e.hitData)?.hitData
    return {
      inning: about.inning,
      half_inning: about.halfInning,
      event: result.event,
      event_type: result.eventType,
      description: result.description,
      rbi: result.rbi,
      is_scoring_play: Boolean(about.isScoringPlay),
      away_score: result.awayScore,
      home_score: result.homeScore,
      batter: personObj(matchup.batter),
      pitcher: personObj(matchup.pitcher),
      hit_data: hit ? { exit_velocity: hit.launchSpeed, distance: hit.totalDistance, launch_angle: hit.launchAngle } : null,
    }
  })
  return { plays, total_plays: allPlays.length, source: 'mlb_live_feed_restored' }
}

function normalizeLinescore(feed, backendLinescore = null) {
  const ls = feed?.liveData?.linescore
  if (!ls) return backendLinescore
  const gd = feed.gameData || {}
  return {
    away_team: gd.teams?.away?.name,
    home_team: gd.teams?.home?.name,
    innings: (ls.innings || []).map(inn => ({
      num: inn.num,
      away_runs: inn.away?.runs,
      away_hits: inn.away?.hits,
      away_errors: inn.away?.errors,
      home_runs: inn.home?.runs,
      home_hits: inn.home?.hits,
      home_errors: inn.home?.errors,
    })),
    totals: {
      away: {
        runs: ls.teams?.away?.runs,
        hits: ls.teams?.away?.hits,
        errors: ls.teams?.away?.errors,
        left_on_base: ls.teams?.away?.leftOnBase,
      },
      home: {
        runs: ls.teams?.home?.runs,
        hits: ls.teams?.home?.hits,
        errors: ls.teams?.home?.errors,
        left_on_base: ls.teams?.home?.leftOnBase,
      },
    },
    decisions: {
      winner: personObj(feed.liveData?.decisions?.winner),
      loser: personObj(feed.liveData?.decisions?.loser),
      save: personObj(feed.liveData?.decisions?.save),
    },
    source: 'mlb_live_feed_restored',
  }
}

function CountDot({ filled, color }) {
  return <span style={{ display: 'inline-block', width: 10, height: 10, borderRadius: '50%', marginRight: 3, background: filled ? color : '#21262d', border: '1px solid #30363d' }} />
}

function RunnerDiamond({ runners }) {
  const base = (filled, label) => <div title={label || ''} style={{ width: 16, height: 16, background: filled ? '#d29922' : '#21262d', border: `1px solid ${filled ? '#d29922' : '#30363d'}`, transform: 'rotate(45deg)' }} />
  return <div style={{ display: 'grid', gridTemplateColumns: '20px 20px 20px', gridTemplateRows: '20px 20px', gap: 2, alignItems: 'center' }}><div />{base(Boolean(runners?.second), runners?.second)}<div />{base(Boolean(runners?.third), runners?.third)}<div />{base(Boolean(runners?.first), runners?.first)}</div>
}

function SectionHeader({ children }) {
  return <div style={{ fontSize: 11, fontWeight: 800, color: '#8b949e', textTransform: 'uppercase', letterSpacing: '0.08em', marginBottom: 10 }}>{children}</div>
}

function LiveTab({ state }) {
  if (!state) return <div style={s.muted}>No live state data.</div>
  const isLive = isLiveStatus(state.status, state.status_detail)
  return <div>
    <div style={{ ...s.card, marginBottom: 16 }}>
      <div style={{ display: 'flex', justifyContent: 'space-around', alignItems: 'center' }}>
        <div style={{ textAlign: 'center' }}><div style={s.muted}>{state.away?.abbreviation}</div><div style={{ fontSize: 40, fontWeight: 900, color: '#e6edf3' }}>{val(state.away?.score)}</div></div>
        <div style={{ textAlign: 'center' }}><div style={{ color: isLive ? '#3fb950' : '#8b949e', fontWeight: 800 }}>{state.inning_state || state.status_detail} {state.inning || ''}</div><div style={{ marginTop: 6 }}>{[0,1,2].map(i => <CountDot key={i} filled={i < (state.outs || 0)} color="#d29922" />)}</div></div>
        <div style={{ textAlign: 'center' }}><div style={s.muted}>{state.home?.abbreviation}</div><div style={{ fontSize: 40, fontWeight: 900, color: '#e6edf3' }}>{val(state.home?.score)}</div></div>
      </div>
    </div>
    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))', gap: 12 }}>
      <div style={s.card}><SectionHeader>At Bat</SectionHeader>{state.current_batter?.id ? <Link to={`/batter/${state.current_batter.id}`} style={s.link}>{state.current_batter.name}</Link> : <div style={s.muted}>—</div>}<div style={{ marginTop: 12 }}><SectionHeader>Count</SectionHeader><div>{[0,1,2,3].map(i => <CountDot key={i} filled={i < (state.count?.balls || 0)} color="#3fb950" />)} <span style={s.muted}>B</span> {[0,1].map(i => <CountDot key={i} filled={i < (state.count?.strikes || 0)} color="#f85149" />)} <span style={s.muted}>S</span></div></div><div style={{ marginTop: 12 }}><SectionHeader>Runners</SectionHeader><RunnerDiamond runners={state.runners} /></div></div>
      <div style={s.card}><SectionHeader>Pitching</SectionHeader>{state.current_pitcher?.id ? <Link to={`/pitcher/${state.current_pitcher.id}`} style={s.link}>{state.current_pitcher.name}</Link> : <div style={s.muted}>—</div>}<div style={{ marginTop: 12 }}><SectionHeader>Pitch Sequence</SectionHeader>{(state.pitch_sequence || []).length ? state.pitch_sequence.map((p, i) => <div key={i} style={{ display: 'grid', gridTemplateColumns: '32px 1fr 80px 1.5fr', gap: 8, padding: '5px 0', borderBottom: '1px solid #21262d', fontSize: 12 }}><span style={s.muted}>#{i + 1}</span><span>{val(p.pitch_type)}</span><span style={{ color: '#58a6ff' }}>{p.speed_mph ? `${Number(p.speed_mph).toFixed(1)} mph` : '—'}</span><span>{val(p.call)}</span></div>) : <div style={s.muted}>No pitch sequence yet.</div>}</div></div>
    </div>
  </div>
}

function BoxScoreTab({ boxscore }) {
  if (!boxscore) return <div style={s.muted}>No box score data.</div>
  const PitcherTable = ({ rows }) => <div><SectionHeader>Pitching</SectionHeader><Table headers={['Pitcher','IP','H','R','ER','BB','K','HR','PC-ST','ERA']} rows={rows} render={p => [<Link to={`/pitcher/${p.id}`} style={s.link}>{p.name}</Link>, val(p.innings_pitched ?? p.ip), val(p.hits ?? p.h), val(p.runs ?? p.r), val(p.earned_runs ?? p.er), val(p.walks ?? p.bb), val(p.strikeouts ?? p.k), val(p.home_runs ?? p.hr), (p.pitch_count ?? p.pitches) != null ? `${p.pitch_count ?? p.pitches}-${p.strikes_thrown ?? p.strikes ?? '?'}` : '—', val(p.season_era ?? p.era)]} /></div>
  const BatterTable = ({ rows }) => <div style={{ marginBottom: 22 }}><SectionHeader>Batting</SectionHeader><Table headers={['#','Batter','POS','AB','R','H','RBI','HR','BB','K','AVG','OPS']} rows={rows} render={b => [b.batting_order_slot ?? (b.batting_order ? Math.floor(b.batting_order / 100) : ''), <span style={{ display: 'inline-flex', alignItems: 'center', gap: 7, paddingLeft: b.is_substitute ? 14 : 0 }}><Link to={`/batter/${b.id}`} style={s.link}>{b.name}</Link>{b.entry_label && <span style={{ color: '#d29922', fontSize: 10, fontWeight: 800 }}>{b.entry_label}</span>}</span>, val(b.position), val(b.at_bats ?? b.ab), val(b.runs ?? b.r), val(b.hits ?? b.h), val(b.rbi), val(b.home_runs ?? b.hr), val(b.walks ?? b.bb), val(b.strikeouts ?? b.k), val(b.season_avg ?? b.avg), val(b.season_ops ?? b.ops)]} /></div>
  const Team = ({ side, label }) => {
    const team = boxscore[side] || {}
    return <section style={{ ...s.card, marginBottom: 18 }}><div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: 18 }}><div><div style={{ color: '#8b949e', fontSize: 11, fontWeight: 800, textTransform: 'uppercase', letterSpacing: '0.08em' }}>{label}</div><h2 style={{ margin: '4px 0 0', color: '#e6edf3', fontSize: 18 }}>{team.name || label}</h2></div><span style={{ color: '#8b949e', fontSize: 12 }}>{(team.batters || []).length} batters · {(team.pitchers || []).length} pitchers</span></div><BatterTable rows={team.batters || []} /><PitcherTable rows={team.pitchers || []} /></section>
  }
  return <div><Team side="away" label="Away" /><Team side="home" label="Home" /></div>
}

function Table({ headers, rows, render }) {
  return <div style={{ overflowX: 'auto' }}><table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}><thead><tr>{headers.map((h, i) => <th key={h} style={{ ...s.th, textAlign: i === 0 || h === 'Batter' || h === 'Pitcher' ? 'left' : 'right' }}>{h}</th>)}</tr></thead><tbody>{rows.map((row, r) => <tr key={row.id || r}>{render(row).map((cell, c) => <td key={c} style={{ ...s.td, textAlign: c === 0 || headers[c] === 'Batter' || headers[c] === 'Pitcher' ? 'left' : 'right' }}>{cell}</td>)}</tr>)}</tbody></table></div>
}

function PlaysTab({ plays }) {
  const list = plays?.plays || []
  if (!list.length) return <div style={s.muted}>No plays recorded yet.</div>
  return <div><div style={{ ...s.muted, marginBottom: 8 }}>Showing {list.length} of {plays.total_plays} plays.</div>{list.map((p, i) => <div key={i} style={{ ...s.card, marginBottom: 8, borderColor: p.is_scoring_play ? '#3fb950' : '#30363d' }}><div style={{ display: 'flex', justifyContent: 'space-between', gap: 16 }}><div><div style={{ color: p.is_scoring_play ? '#3fb950' : '#e6edf3', fontWeight: 800 }}>{p.half_inning === 'top' ? '▲' : '▼'}{p.inning} · {p.event}</div><div style={{ ...s.muted, marginTop: 4 }}>{p.description}</div><div style={{ color: '#484f58', marginTop: 6 }}>{p.batter?.name} {p.pitcher?.name ? `vs ${p.pitcher.name}` : ''}</div></div><div style={{ color: '#e6edf3', fontWeight: 900 }}>{val(p.away_score)}-{val(p.home_score)}</div></div></div>)}</div>
}

function LinescoreTab({ linescore }) {
  if (!linescore) return <div style={s.muted}>No linescore data.</div>
  const headers = ['Team', ...(linescore.innings || []).map(i => i.num), 'R', 'H', 'E', 'LOB']
  const rows = [
    { label: linescore.away_team || 'Away', key: 'away' },
    { label: linescore.home_team || 'Home', key: 'home' },
  ]
  return <div style={s.card}><Table headers={headers} rows={rows} render={r => [r.label, ...(linescore.innings || []).map(i => val(i[`${r.key}_runs`])), val(linescore.totals?.[r.key]?.runs), val(linescore.totals?.[r.key]?.hits), val(linescore.totals?.[r.key]?.errors), val(linescore.totals?.[r.key]?.left_on_base)]} /></div>
}

const TABS = [
  { id: 'live', label: 'Live' },
  { id: 'boxscore', label: 'Box Score' },
  { id: 'plays', label: 'Play-by-Play' },
  { id: 'linescore', label: 'Linescore' },
]

export default function LiveGamePageRestored() {
  const { game_pk } = useParams()
  const [activeTab, setActiveTab] = useState('live')
  const [state, setState] = useState(null)
  const [boxscore, setBoxscore] = useState(null)
  const [plays, setPlays] = useState(null)
  const [linescore, setLinescore] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [lastRefresh, setLastRefresh] = useState(null)
  const timerRef = useRef(null)

  async function optionalJson(url) {
    try {
      const r = await fetch(url)
      return r.ok ? await r.json() : null
    } catch {
      return null
    }
  }

  async function fetchAll() {
    setError(null)
    try {
      const [backendState, backendBox, backendPlays, backendLine, mlbFeed] = await Promise.all([
        optionalJson(`${API_BASE}/live/game/${game_pk}`),
        optionalJson(`${API_BASE}/live/game/${game_pk}/boxscore`),
        optionalJson(`${API_BASE}/live/game/${game_pk}/plays`),
        optionalJson(`${API_BASE}/live/game/${game_pk}/linescore`),
        optionalJson(`${MLB_LIVE_BASE}/${game_pk}/feed/live`),
      ])
      const liveState = normalizeLiveState(mlbFeed, backendState || {})
      setState(liveState)
      setBoxscore(normalizeBoxscore(mlbFeed, backendBox))
      setPlays(normalizePlays(mlbFeed, backendPlays))
      setLinescore(normalizeLinescore(mlbFeed, backendLine))
      setLastRefresh(new Date())
      setLoading(false)
    } catch (e) {
      setError(String(e?.message || e))
      setLoading(false)
    }
  }

  useEffect(() => { fetchAll() }, [game_pk])
  useEffect(() => {
    if (isLiveStatus(state?.status, state?.status_detail)) timerRef.current = setInterval(fetchAll, REFRESH_LIVE_MS)
    return () => clearInterval(timerRef.current)
  }, [state?.status, state?.status_detail, game_pk])

  const away = state?.away
  const home = state?.home
  const content = useMemo(() => {
    if (activeTab === 'boxscore') return <BoxScoreTab boxscore={boxscore} />
    if (activeTab === 'plays') return <PlaysTab plays={plays} />
    if (activeTab === 'linescore') return <LinescoreTab linescore={linescore} />
    return <LiveTab state={state} />
  }, [activeTab, state, boxscore, plays, linescore])

  if (loading) return <div style={{ color: '#8b949e', padding: 40 }}>Loading game data...</div>
  if (error) return <div style={{ padding: 40 }}><Link to="/live" style={s.link}>← Scoreboard</Link><div style={{ color: '#f85149', marginTop: 12 }}>Error: {error}</div></div>

  return <div>
    <div style={{ marginBottom: 20 }}>
      <Link to="/live" style={{ ...s.link, fontSize: 13 }}>← Scoreboard</Link>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginTop: 10 }}>
        <div><h1 style={{ margin: 0, fontSize: 20, color: '#e6edf3' }}>{away?.name || away?.abbreviation} @ {home?.name || home?.abbreviation}</h1><div style={{ ...s.muted, marginTop: 6 }}>{state?.status_detail || state?.status}</div></div>
        <div style={{ display: 'flex', gap: 10, alignItems: 'center' }}><span style={{ ...s.muted, fontSize: 12 }}>{lastRefresh ? lastRefresh.toLocaleTimeString() : '—'}</span><button onClick={fetchAll} style={{ background: '#21262d', border: '1px solid #30363d', color: '#e6edf3', borderRadius: 8, padding: '7px 10px', cursor: 'pointer' }}>↻</button></div>
      </div>
    </div>
    <div style={{ display: 'flex', gap: 14, borderBottom: '1px solid #30363d', marginBottom: 16 }}>{TABS.map(tab => <button key={tab.id} onClick={() => setActiveTab(tab.id)} style={s.tab(activeTab === tab.id)}>{tab.label}</button>)}</div>
    {content}
  </div>
}

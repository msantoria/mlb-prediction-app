import React, { useState, useEffect, useRef } from 'react'
import { useParams, Link } from 'react-router-dom'
import { API_BASE } from '../lib/api'

const REFRESH_LIVE_MS = 15_000

// ─── helpers ────────────────────────────────────────────────────────────────

function val(v, suffix = '') {
  return v != null ? `${v}${suffix}` : '—'
}

function fmtAvg(v) {
  if (v == null) return '—'
  const n = parseFloat(v)
  return isNaN(n) ? v : n.toFixed(3)
}

function CountBall({ filled }) {
  return (
    <span style={{
      display: 'inline-block', width: '10px', height: '10px', borderRadius: '50%',
      background: filled ? '#3fb950' : '#21262d',
      border: '1px solid #30363d', marginRight: '3px',
    }} />
  )
}

function CountStrike({ filled }) {
  return (
    <span style={{
      display: 'inline-block', width: '10px', height: '10px', borderRadius: '50%',
      background: filled ? '#f85149' : '#21262d',
      border: '1px solid #30363d', marginRight: '3px',
    }} />
  )
}

function RunnerDiamond({ runners }) {
  const on1 = Boolean(runners?.first)
  const on2 = Boolean(runners?.second)
  const on3 = Boolean(runners?.third)
  const base = (filled, label) => (
    <div title={label || ''} style={{
      width: '16px', height: '16px',
      background: filled ? '#d29922' : '#21262d',
      border: `1px solid ${filled ? '#d29922' : '#30363d'}`,
      transform: 'rotate(45deg)',
    }} />
  )
  return (
    <div style={{ display: 'grid', gridTemplateColumns: '20px 20px 20px', gridTemplateRows: '20px 20px', gap: '2px', alignItems: 'center' }}>
      <div />
      {base(on2, runners?.second)}
      <div />
      {base(on3, runners?.third)}
      <div />
      {base(on1, runners?.first)}
    </div>
  )
}

function SectionHeader({ children }) {
  return (
    <div style={{ fontSize: '11px', fontWeight: '600', color: '#8b949e', textTransform: 'uppercase', letterSpacing: '0.08em', marginBottom: '10px' }}>
      {children}
    </div>
  )
}

function Card({ children, style }) {
  return (
    <div style={{ background: '#0d1117', border: '1px solid #30363d', borderRadius: '8px', padding: '16px', ...style }}>
      {children}
    </div>
  )
}

// ─── Tab: Live (current play state) ─────────────────────────────────────────

function LiveTab({ state }) {
  if (!state) return <div style={{ color: '#8b949e' }}>No live state data.</div>

  const { current_batter, current_pitcher, count, runners, pitch_sequence, status, status_detail } = state
  const isLive = status === 'Live'

  return (
    <div>
      {/* Score banner */}
      <Card style={{ marginBottom: '16px' }}>
        <div style={{ display: 'flex', justifyContent: 'space-around', alignItems: 'center' }}>
          <div style={{ textAlign: 'center' }}>
            <div style={{ fontSize: '13px', color: '#8b949e' }}>{state.away?.abbreviation}</div>
            <div style={{ fontSize: '36px', fontWeight: '700', color: '#e6edf3' }}>{val(state.away?.score)}</div>
          </div>
          <div style={{ textAlign: 'center' }}>
            {isLive ? (
              <>
                <div style={{ fontSize: '13px', fontWeight: '600', color: '#3fb950' }}>
                  {state.inning_state} {state.inning}
                </div>
                <div style={{ display: 'flex', justifyContent: 'center', gap: '3px', marginTop: '4px' }}>
                  {[0, 1, 2].map(i => (
                    <span key={i} style={{
                      width: '8px', height: '8px', borderRadius: '50%',
                      background: i < (state.outs ?? 0) ? '#d29922' : '#21262d',
                      border: '1px solid #30363d',
                      display: 'inline-block',
                    }} />
                  ))}
                </div>
              </>
            ) : (
              <div style={{ fontSize: '13px', color: '#8b949e' }}>{status_detail || status}</div>
            )}
          </div>
          <div style={{ textAlign: 'center' }}>
            <div style={{ fontSize: '13px', color: '#8b949e' }}>{state.home?.abbreviation}</div>
            <div style={{ fontSize: '36px', fontWeight: '700', color: '#e6edf3' }}>{val(state.home?.score)}</div>
          </div>
        </div>
      </Card>

      {isLive && (
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '12px', marginBottom: '16px' }}>
          {/* Current batter */}
          <Card>
            <SectionHeader>At Bat</SectionHeader>
            {current_batter?.id ? (
              <Link to={`/batter/${current_batter.id}`} style={{ textDecoration: 'none' }}>
                <div style={{ fontSize: '16px', fontWeight: '600', color: '#58a6ff' }}>{current_batter.name}</div>
              </Link>
            ) : (
              <div style={{ color: '#8b949e' }}>—</div>
            )}
            {current_batter?.bat_side && (
              <div style={{ fontSize: '12px', color: '#8b949e', marginTop: '3px' }}>Bats {current_batter.bat_side}</div>
            )}

            {/* Count */}
            <div style={{ marginTop: '12px' }}>
              <div style={{ fontSize: '11px', color: '#8b949e', marginBottom: '4px' }}>COUNT</div>
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                <div>
                  {[0,1,2,3].map(i => <CountBall key={i} filled={i < (count?.balls ?? 0)} />)}
                  <span style={{ fontSize: '11px', color: '#8b949e', marginLeft: '2px' }}>B</span>
                </div>
                <div>
                  {[0,1].map(i => <CountStrike key={i} filled={i < (count?.strikes ?? 0)} />)}
                  <span style={{ fontSize: '11px', color: '#8b949e', marginLeft: '2px' }}>S</span>
                </div>
              </div>
            </div>

            {/* Runners */}
            <div style={{ marginTop: '12px' }}>
              <div style={{ fontSize: '11px', color: '#8b949e', marginBottom: '6px' }}>RUNNERS</div>
              <RunnerDiamond runners={runners} />
              <div style={{ fontSize: '11px', color: '#8b949e', marginTop: '4px' }}>
                {runners?.first ? `1B: ${runners.first}` : ''}
                {runners?.second ? ` · 2B: ${runners.second}` : ''}
                {runners?.third ? ` · 3B: ${runners.third}` : ''}
              </div>
            </div>
          </Card>

          {/* Current pitcher */}
          <Card>
            <SectionHeader>Pitching</SectionHeader>
            {current_pitcher?.id ? (
              <Link to={`/pitcher/${current_pitcher.id}`} style={{ textDecoration: 'none' }}>
                <div style={{ fontSize: '16px', fontWeight: '600', color: '#58a6ff' }}>{current_pitcher.name}</div>
              </Link>
            ) : (
              <div style={{ color: '#8b949e' }}>—</div>
            )}
            {current_pitcher?.pitch_hand && (
              <div style={{ fontSize: '12px', color: '#8b949e', marginTop: '3px' }}>Throws {current_pitcher.pitch_hand}</div>
            )}

            {/* Pitch sequence */}
            {pitch_sequence?.length > 0 && (
              <div style={{ marginTop: '12px' }}>
                <div style={{ fontSize: '11px', color: '#8b949e', marginBottom: '6px' }}>PITCH SEQUENCE ({pitch_sequence.length} pitches)</div>
                <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
                  {pitch_sequence.map((p, i) => (
                    <div key={i} style={{ display: 'flex', justifyContent: 'space-between', fontSize: '12px', color: '#c9d1d9', background: '#161b22', borderRadius: '4px', padding: '4px 8px' }}>
                      <span style={{ color: '#8b949e' }}>#{i + 1}</span>
                      <span>{p.pitch_type || '—'}</span>
                      <span style={{ color: '#58a6ff' }}>{p.speed_mph != null ? `${Number(p.speed_mph).toFixed(1)} mph` : '—'}</span>
                      <span style={{ color: p.call?.includes('Strike') || p.call?.includes('Foul') ? '#f85149' : p.call?.includes('Ball') ? '#3fb950' : '#8b949e' }}>
                        {p.call || '—'}
                      </span>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </Card>
        </div>
      )}
    </div>
  )
}

// ─── Tab: Box Score ──────────────────────────────────────────────────────────

function BoxScoreTab({ boxscore }) {
  if (!boxscore) return <div style={{ color: '#8b949e' }}>No box score data.</div>

  function PitcherTable({ pitchers, title }) {
    return (
      <div style={{ marginBottom: '20px' }}>
        <SectionHeader>{title} Pitchers</SectionHeader>
        <div style={{ overflowX: 'auto' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '13px' }}>
            <thead>
              <tr style={{ color: '#8b949e', borderBottom: '1px solid #30363d' }}>
                <th style={{ textAlign: 'left', padding: '6px 8px', fontWeight: '500' }}>Pitcher</th>
                <th style={{ textAlign: 'right', padding: '6px 8px', fontWeight: '500' }}>IP</th>
                <th style={{ textAlign: 'right', padding: '6px 8px', fontWeight: '500' }}>H</th>
                <th style={{ textAlign: 'right', padding: '6px 8px', fontWeight: '500' }}>R</th>
                <th style={{ textAlign: 'right', padding: '6px 8px', fontWeight: '500' }}>ER</th>
                <th style={{ textAlign: 'right', padding: '6px 8px', fontWeight: '500' }}>BB</th>
                <th style={{ textAlign: 'right', padding: '6px 8px', fontWeight: '500' }}>K</th>
                <th style={{ textAlign: 'right', padding: '6px 8px', fontWeight: '500' }}>HR</th>
                <th style={{ textAlign: 'right', padding: '6px 8px', fontWeight: '500' }}>PC-ST</th>
                <th style={{ textAlign: 'right', padding: '6px 8px', fontWeight: '500' }}>ERA</th>
              </tr>
            </thead>
            <tbody>
              {pitchers.map(p => (
                <tr key={p.id} style={{ borderBottom: '1px solid #21262d', background: p.is_current_pitcher ? '#161b22' : 'transparent' }}>
                  <td style={{ padding: '6px 8px', color: '#e6edf3' }}>
                    <Link to={`/pitcher/${p.id}`} style={{ color: '#58a6ff', textDecoration: 'none' }}>
                      {p.name}
                    </Link>
                    {p.is_current_pitcher && <span style={{ color: '#3fb950', fontSize: '10px', marginLeft: '6px' }}>●</span>}
                  </td>
                  <td style={{ textAlign: 'right', padding: '6px 8px', color: '#c9d1d9' }}>{val(p.innings_pitched)}</td>
                  <td style={{ textAlign: 'right', padding: '6px 8px', color: '#c9d1d9' }}>{val(p.hits)}</td>
                  <td style={{ textAlign: 'right', padding: '6px 8px', color: '#c9d1d9' }}>{val(p.runs)}</td>
                  <td style={{ textAlign: 'right', padding: '6px 8px', color: p.earned_runs > 2 ? '#f85149' : '#c9d1d9' }}>{val(p.earned_runs)}</td>
                  <td style={{ textAlign: 'right', padding: '6px 8px', color: '#c9d1d9' }}>{val(p.walks)}</td>
                  <td style={{ textAlign: 'right', padding: '6px 8px', color: '#3fb950' }}>{val(p.strikeouts)}</td>
                  <td style={{ textAlign: 'right', padding: '6px 8px', color: p.home_runs > 0 ? '#f85149' : '#c9d1d9' }}>{val(p.home_runs)}</td>
                  <td style={{ textAlign: 'right', padding: '6px 8px', color: '#8b949e', fontSize: '12px' }}>
                    {p.pitch_count != null ? `${p.pitch_count}-${p.strikes_thrown ?? '?'}` : '—'}
                  </td>
                  <td style={{ textAlign: 'right', padding: '6px 8px', color: '#c9d1d9' }}>{val(p.era)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    )
  }

  function BatterTable({ batters, title }) {
    return (
      <div style={{ marginBottom: '20px' }}>
        <SectionHeader>{title} Batters</SectionHeader>
        <div style={{ overflowX: 'auto' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '13px' }}>
            <thead>
              <tr style={{ color: '#8b949e', borderBottom: '1px solid #30363d' }}>
                <th style={{ textAlign: 'left', padding: '6px 8px', fontWeight: '500' }}>#</th>
                <th style={{ textAlign: 'left', padding: '6px 8px', fontWeight: '500' }}>Batter</th>
                <th style={{ textAlign: 'center', padding: '6px 8px', fontWeight: '500' }}>POS</th>
                <th style={{ textAlign: 'right', padding: '6px 8px', fontWeight: '500' }}>AB</th>
                <th style={{ textAlign: 'right', padding: '6px 8px', fontWeight: '500' }}>R</th>
                <th style={{ textAlign: 'right', padding: '6px 8px', fontWeight: '500' }}>H</th>
                <th style={{ textAlign: 'right', padding: '6px 8px', fontWeight: '500' }}>RBI</th>
                <th style={{ textAlign: 'right', padding: '6px 8px', fontWeight: '500' }}>HR</th>
                <th style={{ textAlign: 'right', padding: '6px 8px', fontWeight: '500' }}>BB</th>
                <th style={{ textAlign: 'right', padding: '6px 8px', fontWeight: '500' }}>K</th>
                <th style={{ textAlign: 'right', padding: '6px 8px', fontWeight: '500' }}>AVG</th>
                <th style={{ textAlign: 'right', padding: '6px 8px', fontWeight: '500' }}>OPS</th>
              </tr>
            </thead>
            <tbody>
              {batters.map(b => (
                <tr key={b.id} style={{ borderBottom: '1px solid #21262d' }}>
                  <td style={{ padding: '6px 8px', color: '#484f58', fontSize: '11px' }}>
                    {b.batting_order ? Math.floor(b.batting_order / 100) : ''}
                  </td>
                  <td style={{ padding: '6px 8px', color: '#e6edf3' }}>
                    <Link to={`/batter/${b.id}`} style={{ color: '#58a6ff', textDecoration: 'none' }}>
                      {b.name}
                    </Link>
                  </td>
                  <td style={{ textAlign: 'center', padding: '6px 8px', color: '#8b949e', fontSize: '11px' }}>{val(b.position)}</td>
                  <td style={{ textAlign: 'right', padding: '6px 8px', color: '#c9d1d9' }}>{val(b.at_bats)}</td>
                  <td style={{ textAlign: 'right', padding: '6px 8px', color: '#c9d1d9' }}>{val(b.runs)}</td>
                  <td style={{ textAlign: 'right', padding: '6px 8px', color: b.hits > 0 ? '#e6edf3' : '#c9d1d9', fontWeight: b.hits > 0 ? '600' : '400' }}>{val(b.hits)}</td>
                  <td style={{ textAlign: 'right', padding: '6px 8px', color: b.rbi > 0 ? '#3fb950' : '#c9d1d9' }}>{val(b.rbi)}</td>
                  <td style={{ textAlign: 'right', padding: '6px 8px', color: b.home_runs > 0 ? '#f85149' : '#c9d1d9' }}>{val(b.home_runs)}</td>
                  <td style={{ textAlign: 'right', padding: '6px 8px', color: '#c9d1d9' }}>{val(b.walks)}</td>
                  <td style={{ textAlign: 'right', padding: '6px 8px', color: '#c9d1d9' }}>{val(b.strikeouts)}</td>
                  <td style={{ textAlign: 'right', padding: '6px 8px', color: '#8b949e' }}>{fmtAvg(b.season_avg)}</td>
                  <td style={{ textAlign: 'right', padding: '6px 8px', color: '#8b949e' }}>{val(b.season_ops)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    )
  }

  return (
    <div>
      <PitcherTable pitchers={boxscore.away?.pitchers || []} title="Away" />
      <BatterTable batters={boxscore.away?.batters || []} title="Away" />
      <PitcherTable pitchers={boxscore.home?.pitchers || []} title="Home" />
      <BatterTable batters={boxscore.home?.batters || []} title="Home" />
    </div>
  )
}

// ─── Tab: Play-by-Play ───────────────────────────────────────────────────────

function PlaysTab({ plays }) {
  if (!plays) return <div style={{ color: '#8b949e' }}>No play data.</div>
  const list = plays.plays || []
  if (!list.length) return <div style={{ color: '#8b949e' }}>No plays recorded yet.</div>

  return (
    <div>
      <div style={{ marginBottom: '8px', fontSize: '12px', color: '#8b949e' }}>
        Showing {list.length} of {plays.total_plays} plays (most recent first)
      </div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
        {list.map((play, i) => (
          <div key={i} style={{
            background: play.is_scoring_play ? '#161b22' : '#0d1117',
            border: `1px solid ${play.is_scoring_play ? '#3fb950' : '#21262d'}`,
            borderRadius: '6px',
            padding: '10px 14px',
          }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: '12px' }}>
              <div style={{ flex: 1 }}>
                <div style={{ display: 'flex', gap: '8px', alignItems: 'center', marginBottom: '3px' }}>
                  <span style={{ fontSize: '11px', color: '#8b949e' }}>
                    {play.half_inning === 'top' ? '▲' : '▼'}{play.inning}
                  </span>
                  <span style={{
                    fontSize: '12px', fontWeight: '600',
                    color: play.event_type === 'home_run' ? '#f85149' : play.is_scoring_play ? '#3fb950' : '#e6edf3',
                  }}>
                    {play.event || '—'}
                  </span>
                  {play.rbi > 0 && (
                    <span style={{ fontSize: '11px', background: '#3fb95022', border: '1px solid #3fb95044', borderRadius: '3px', padding: '1px 5px', color: '#3fb950' }}>
                      {play.rbi} RBI
                    </span>
                  )}
                </div>
                <div style={{ fontSize: '12px', color: '#8b949e' }}>{play.description}</div>
              </div>
              <div style={{ textAlign: 'right', flexShrink: 0 }}>
                <div style={{ fontSize: '13px', fontWeight: '600', color: '#e6edf3' }}>
                  {play.away_score}–{play.home_score}
                </div>
                {play.hit_data && (
                  <div style={{ fontSize: '11px', color: '#58a6ff', marginTop: '3px' }}>
                    {play.hit_data.exit_velocity != null && `${Number(play.hit_data.exit_velocity).toFixed(1)} mph`}
                    {play.hit_data.distance != null && ` · ${Math.round(play.hit_data.distance)} ft`}
                  </div>
                )}
              </div>
            </div>
            <div style={{ marginTop: '6px', fontSize: '12px', color: '#484f58', display: 'flex', gap: '12px' }}>
              {play.batter?.name && (
                <Link to={`/batter/${play.batter.id}`} style={{ color: '#484f58', textDecoration: 'none' }}>
                  {play.batter.name}
                </Link>
              )}
              {play.pitcher?.name && (
                <span>vs <Link to={`/pitcher/${play.pitcher.id}`} style={{ color: '#484f58', textDecoration: 'none' }}>{play.pitcher.name}</Link></span>
              )}
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}

// ─── Tab: Linescore ──────────────────────────────────────────────────────────

function LinescoreTab({ linescore }) {
  if (!linescore) return <div style={{ color: '#8b949e' }}>No linescore data.</div>
  const innings = linescore.innings || []

  return (
    <div>
      <Card>
        <div style={{ overflowX: 'auto' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '13px' }}>
            <thead>
              <tr style={{ color: '#8b949e', borderBottom: '1px solid #30363d' }}>
                <th style={{ textAlign: 'left', padding: '6px 10px', fontWeight: '500' }}>Team</th>
                {innings.map(inn => (
                  <th key={inn.num} style={{ textAlign: 'center', padding: '6px 8px', fontWeight: '500', minWidth: '28px' }}>{inn.num}</th>
                ))}
                <th style={{ textAlign: 'right', padding: '6px 10px', fontWeight: '600', color: '#e6edf3', borderLeft: '1px solid #30363d' }}>R</th>
                <th style={{ textAlign: 'right', padding: '6px 10px', fontWeight: '500' }}>H</th>
                <th style={{ textAlign: 'right', padding: '6px 10px', fontWeight: '500' }}>E</th>
                <th style={{ textAlign: 'right', padding: '6px 10px', fontWeight: '500' }}>LOB</th>
              </tr>
            </thead>
            <tbody>
              {[
                { key: 'away', label: linescore.away_team || 'Away', runsKey: 'away_runs', hitsKey: 'away_hits', errKey: 'away_errors' },
                { key: 'home', label: linescore.home_team || 'Home', runsKey: 'home_runs', hitsKey: 'home_hits', errKey: 'home_errors' },
              ].map(row => (
                <tr key={row.key} style={{ borderBottom: '1px solid #21262d' }}>
                  <td style={{ padding: '8px 10px', fontWeight: '600', color: '#e6edf3' }}>{row.label}</td>
                  {innings.map(inn => (
                    <td key={inn.num} style={{ textAlign: 'center', padding: '8px 8px', color: inn[row.runsKey] > 0 ? '#e6edf3' : '#484f58' }}>
                      {inn[row.runsKey] != null ? inn[row.runsKey] : '—'}
                    </td>
                  ))}
                  <td style={{ textAlign: 'right', padding: '8px 10px', fontWeight: '700', fontSize: '15px', color: '#e6edf3', borderLeft: '1px solid #30363d' }}>
                    {val(linescore.totals?.[row.key]?.runs)}
                  </td>
                  <td style={{ textAlign: 'right', padding: '8px 10px', color: '#c9d1d9' }}>{val(linescore.totals?.[row.key]?.hits)}</td>
                  <td style={{ textAlign: 'right', padding: '8px 10px', color: linescore.totals?.[row.key]?.errors > 0 ? '#f85149' : '#c9d1d9' }}>
                    {val(linescore.totals?.[row.key]?.errors)}
                  </td>
                  <td style={{ textAlign: 'right', padding: '8px 10px', color: '#8b949e' }}>{val(linescore.totals?.[row.key]?.left_on_base)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        {/* Decisions */}
        {linescore.decisions && (linescore.decisions.winner || linescore.decisions.loser) && (
          <div style={{ marginTop: '16px', paddingTop: '12px', borderTop: '1px solid #21262d', display: 'flex', gap: '20px', fontSize: '13px' }}>
            {linescore.decisions.winner && (
              <span>
                <span style={{ color: '#8b949e' }}>W: </span>
                <Link to={`/pitcher/${linescore.decisions.winner.id}`} style={{ color: '#3fb950', textDecoration: 'none' }}>
                  {linescore.decisions.winner.name}
                </Link>
              </span>
            )}
            {linescore.decisions.loser && (
              <span>
                <span style={{ color: '#8b949e' }}>L: </span>
                <Link to={`/pitcher/${linescore.decisions.loser.id}`} style={{ color: '#f85149', textDecoration: 'none' }}>
                  {linescore.decisions.loser.name}
                </Link>
              </span>
            )}
            {linescore.decisions.save && (
              <span>
                <span style={{ color: '#8b949e' }}>S: </span>
                <Link to={`/pitcher/${linescore.decisions.save.id}`} style={{ color: '#58a6ff', textDecoration: 'none' }}>
                  {linescore.decisions.save.name}
                </Link>
              </span>
            )}
          </div>
        )}
      </Card>
    </div>
  )
}

// ─── Main page ───────────────────────────────────────────────────────────────

const TABS = [
  { id: 'live', label: 'Live' },
  { id: 'boxscore', label: 'Box Score' },
  { id: 'plays', label: 'Play-by-Play' },
  { id: 'linescore', label: 'Linescore' },
]

export default function LiveGamePage() {
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

  function fetchAll() {
    Promise.all([
      fetch(`${API_BASE}/live/game/${game_pk}`).then(r => r.ok ? r.json() : r.json().then(e => Promise.reject(e.detail || r.statusText))),
      fetch(`${API_BASE}/live/game/${game_pk}/boxscore`).then(r => r.ok ? r.json() : null).catch(() => null),
      fetch(`${API_BASE}/live/game/${game_pk}/plays`).then(r => r.ok ? r.json() : null).catch(() => null),
      fetch(`${API_BASE}/live/game/${game_pk}/linescore`).then(r => r.ok ? r.json() : null).catch(() => null),
    ])
      .then(([s, b, p, l]) => {
        setState(s)
        setBoxscore(b)
        setPlays(p)
        setLinescore(l)
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
    fetchAll()
  }, [game_pk])

  useEffect(() => {
    if (state?.status === 'Live') {
      timerRef.current = setInterval(fetchAll, REFRESH_LIVE_MS)
    }
    return () => clearInterval(timerRef.current)
  }, [state?.status, game_pk])

  if (loading) return <div style={{ color: '#8b949e', padding: '40px' }}>Loading game data…</div>
  if (error) return (
    <div style={{ padding: '40px' }}>
      <Link to="/live" style={{ color: '#58a6ff', textDecoration: 'none', fontSize: '13px' }}>← Scoreboard</Link>
      <div style={{ color: '#f85149', marginTop: '12px' }}>Error: {error}</div>
    </div>
  )

  const away = state?.away
  const home = state?.home
  const isLive = state?.status === 'Live'

  return (
    <div>
      {/* Header */}
      <div style={{ marginBottom: '20px' }}>
        <Link to="/live" style={{ color: '#58a6ff', textDecoration: 'none', fontSize: '13px' }}>← Scoreboard</Link>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginTop: '10px' }}>
          <h1 style={{ margin: 0, fontSize: '20px', fontWeight: '700', color: '#e6edf3' }}>
            {away?.abbreviation || away?.name} @ {home?.abbreviation || home?.name}
          </h1>
          <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
            {isLive && (
              <span style={{ fontSize: '12px', color: '#3fb950', background: '#3fb95022', border: '1px solid #3fb95044', borderRadius: '4px', padding: '2px 8px' }}>
                ● LIVE · {state?.inning_state} {state?.inning}
              </span>
            )}
            {lastRefresh && (
              <span style={{ fontSize: '11px', color: '#8b949e' }}>{lastRefresh.toLocaleTimeString()}</span>
            )}
            <button
              onClick={fetchAll}
              style={{ background: '#21262d', border: '1px solid #30363d', color: '#e6edf3', borderRadius: '6px', padding: '5px 12px', cursor: 'pointer', fontSize: '12px' }}
            >
              ↻
            </button>
          </div>
        </div>
        {state?.status && !isLive && (
          <div style={{ fontSize: '13px', color: '#8b949e', marginTop: '4px' }}>{state.status_detail || state.status}</div>
        )}
      </div>

      {/* Tabs */}
      <div style={{ display: 'flex', gap: '4px', marginBottom: '20px', borderBottom: '1px solid #30363d', paddingBottom: '0' }}>
        {TABS.map(tab => (
          <button
            key={tab.id}
            onClick={() => setActiveTab(tab.id)}
            style={{
              background: 'transparent',
              border: 'none',
              borderBottom: activeTab === tab.id ? '2px solid #58a6ff' : '2px solid transparent',
              color: activeTab === tab.id ? '#e6edf3' : '#8b949e',
              fontSize: '14px',
              fontWeight: activeTab === tab.id ? '600' : '400',
              padding: '8px 16px',
              cursor: 'pointer',
              marginBottom: '-1px',
            }}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {/* Tab content */}
      {activeTab === 'live' && <LiveTab state={state} />}
      {activeTab === 'boxscore' && <BoxScoreTab boxscore={boxscore} />}
      {activeTab === 'plays' && <PlaysTab plays={plays} />}
      {activeTab === 'linescore' && <LinescoreTab linescore={linescore} />}
    </div>
  )
}

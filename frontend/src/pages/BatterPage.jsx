import React, { useState, useEffect } from 'react'
import { useParams, useNavigate, Link } from 'react-router-dom'
import {
  LineChart, Line, BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip,
  Legend, ResponsiveContainer, ReferenceLine,
} from 'recharts'

function FourBlockLoader({ title, kicker, stages, note, compact = false }) {
  if (compact) {
    return (
      <div className="mlbgpt-loader mlbgpt-loader-compact" role="status" aria-live="polite">
        <div className="mlbgpt-loader-blocks" aria-hidden="true">
          <span className="mlbgpt-loader-block mlbgpt-loader-block-red" />
          <span className="mlbgpt-loader-block mlbgpt-loader-block-blue" />
          <span className="mlbgpt-loader-block mlbgpt-loader-block-yellow" />
          <span className="mlbgpt-loader-block mlbgpt-loader-block-green" />
        </div>
        <span className="mlbgpt-loader-compact-label">{title}</span>
      </div>
    )
  }

  return (
    <section className="mlbgpt-loader" role="status" aria-live="polite" aria-label={title}>
      <div className="mlbgpt-loader-blocks" aria-hidden="true">
        <span className="mlbgpt-loader-block mlbgpt-loader-block-red" />
        <span className="mlbgpt-loader-block mlbgpt-loader-block-blue" />
        <span className="mlbgpt-loader-block mlbgpt-loader-block-yellow" />
        <span className="mlbgpt-loader-block mlbgpt-loader-block-green" />
      </div>
      <p className="mlbgpt-loader-kicker">{kicker}</p>
      <h2 className="mlbgpt-loader-title">{title}</h2>
      <ul className="mlbgpt-loader-stages">
        {stages.map(stage => <li key={stage}>{stage}</li>)}
      </ul>
      {note && <p className="mlbgpt-loader-note">{note}</p>}
    </section>
  )
}

const API = import.meta.env.VITE_API_BASE_URL || ''

const C = {
  green: '#3fb950', blue: '#58a6ff', orange: '#d29922', red: '#f85149',
  purple: '#bc8cff', teal: '#39d0d8',
  text: '#e6edf3', muted: '#8b949e', bg: '#0d1117', card: '#161b22',
  border: '#30363d', elevated: '#21262d',
}

const s = {
  searchRow: { display: 'flex', gap: '12px', marginBottom: '20px' },
  input: {
    flex: 1, background: C.card, border: `1px solid ${C.border}`, color: C.text,
    borderRadius: '6px', padding: '10px 14px', fontSize: '14px', outline: 'none',
  },
  playerHeader: {
    background: C.card, border: `1px solid ${C.border}`, borderRadius: '10px',
    padding: '20px 24px', marginBottom: '20px',
  },
  playerName: { fontSize: '26px', fontWeight: '700', color: C.text, marginBottom: '6px' },
  playerMeta: { display: 'flex', gap: '16px', flexWrap: 'wrap', fontSize: '13px', color: C.muted },
  metaChip: { background: C.elevated, borderRadius: '4px', padding: '2px 8px', color: C.text },
  rollingLink: {
    display: 'inline-block', background: C.elevated, border: `1px solid ${C.border}`,
    color: C.blue, textDecoration: 'none', borderRadius: '6px',
    padding: '7px 16px', fontSize: '13px', fontWeight: '500', marginBottom: '24px',
  },
  qaBox: { background: C.card, border: `1px solid ${C.border}`, borderRadius: '8px', padding: '12px 14px', marginBottom: '20px', fontSize: '13px', color: C.muted },
  qaWarn: { color: C.orange, marginTop: '6px' },
  section: { marginBottom: '32px' },
  sectionTitle: { fontSize: '16px', fontWeight: '600', color: C.text, marginBottom: '14px', borderBottom: `1px solid ${C.elevated}`, paddingBottom: '8px' },
  statsGrid: { display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(140px, 1fr))', gap: '12px' },
  statCard: { background: C.card, border: `1px solid ${C.border}`, borderRadius: '8px', padding: '14px 16px' },
  statLabel: { fontSize: '11px', color: C.muted, marginBottom: '6px', textTransform: 'uppercase', letterSpacing: '0.5px' },
  statVal: { fontSize: '22px', fontWeight: '700', color: C.text },
  tableWrap: { background: C.card, border: `1px solid ${C.border}`, borderRadius: '10px', overflow: 'auto' },
  table: { width: '100%', borderCollapse: 'collapse', fontSize: '13px' },
  th: { padding: '10px 14px', textAlign: 'left', color: C.muted, fontWeight: '500', fontSize: '11px', textTransform: 'uppercase', letterSpacing: '0.4px', borderBottom: `1px solid ${C.elevated}`, whiteSpace: 'nowrap' },
  thR: { textAlign: 'right' },
  td: { padding: '10px 14px', borderBottom: `1px solid ${C.bg}`, color: C.text, whiteSpace: 'nowrap' },
  tdR: { textAlign: 'right' },
  sourceBadge: { display: 'inline-block', fontSize: '11px', padding: '2px 7px', borderRadius: '3px', background: C.elevated, color: C.muted, marginLeft: '10px', verticalAlign: 'middle', fontWeight: '400' },
  loader: { color: C.muted, padding: '48px', textAlign: 'center' },
  error: { color: C.red, padding: '24px', background: '#1f1116', borderRadius: '8px' },
  chartBox: { background: C.card, border: `1px solid ${C.border}`, borderRadius: '10px', padding: '20px' },
}

const searchDropStyle = {
  position: 'absolute', top: '100%', left: 0, right: 0, zIndex: 100,
  background: C.card, border: `1px solid ${C.border}`, borderRadius: '6px',
  marginTop: '4px', maxHeight: '280px', overflowY: 'auto',
}

const searchItemStyle = (hover) => ({
  padding: '9px 14px', cursor: 'pointer', borderBottom: `1px solid ${C.elevated}`,
  background: hover ? C.elevated : 'transparent',
  display: 'flex', justifyContent: 'space-between', alignItems: 'center',
})

const fmt = (v, d = 1) => v != null ? (typeof v === 'number' ? v.toFixed(d) : v) : '—'
const pct = (v, d = 1) => v != null ? `${(v * 100).toFixed(d)}%` : '—'
const num = (v) => v != null ? v : '—'

const LEAGUE_AVGS = {
  avg_exit_velocity: 88.5, hard_hit_pct: 0.38, barrel_pct: 0.08,
  k_pct: 0.225, bb_pct: 0.085,
}

const tooltipStyle = { background: '#1c2128', border: `1px solid ${C.border}`, borderRadius: '6px', fontSize: '12px', color: C.text }

function safeNumber(value) {
  const parsed = Number(value)
  return Number.isFinite(parsed) ? parsed : null
}

function hasRealPlayerName(name) {
  if (!name) return false
  const cleaned = String(name).trim()
  if (!cleaned) return false
  if (cleaned.startsWith('#')) return false
  return !['none', 'null', 'nan', 'unknown', 'n/a', 'na'].includes(cleaned.toLowerCase())
}

function cleanLeaderboardRows(board) {
  if (!Array.isArray(board)) return []

  return board
    .map((row, idx) => {
      const value = safeNumber(row?.value)
      return {
        ...row,
        value,
        rank: row?.rank || idx + 1,
      }
    })
    .filter(row => (
      row.player_id &&
      hasRealPlayerName(row.player_name) &&
      row.value !== null
    ))
    .slice(0, 10)
}

// ─── Leaderboard config ────────────────────────────────────────────────────
const LB_CONFIG = [
  { key: 'home_runs', title: 'Home Runs', fmt: v => `${Math.round(v)}`, color: C.blue, group: 'Counting' },
  { key: 'hits', title: 'Hits', fmt: v => `${Math.round(v)}`, color: C.green, group: 'Counting' },
  { key: 'doubles', title: 'Doubles (2B)', fmt: v => `${Math.round(v)}`, color: C.teal, group: 'Counting' },
  { key: 'rbi', title: 'RBI', fmt: v => `${Math.round(v)}`, color: C.purple, group: 'Counting' },
  { key: 'avg_exit_velocity', title: 'Avg Exit Velocity', fmt: v => `${v.toFixed(1)} mph`, color: C.orange, group: 'Statcast' },
  { key: 'hard_hit_pct', title: 'Hard Hit %', fmt: v => `${(v * 100).toFixed(1)}%`, color: C.orange, group: 'Statcast' },
  { key: 'barrel_pct', title: 'Barrel %', fmt: v => `${(v * 100).toFixed(1)}%`, color: C.red, group: 'Statcast' },
  { key: 'max_exit_velocity', title: 'Max Exit Velocity', fmt: v => `${v.toFixed(1)} mph`, color: C.purple, group: 'Statcast' },
  { key: 'iso', title: 'ISO', fmt: v => v.toFixed(3), color: C.blue, group: 'Rate' },
  { key: 'bb_pct', title: 'Walk Rate (BB%)', fmt: v => `${(v * 100).toFixed(1)}%`, color: C.green, group: 'Rate' },
  { key: 'k_pct_avoidance', title: 'K% Avoidance', fmt: v => `${(v * 100).toFixed(1)}%`, color: C.teal, group: 'Rate', inverse: true },
  { key: 'contact_pct', title: 'Contact %', fmt: v => `${(v * 100).toFixed(1)}%`, color: C.green, group: 'Contact' },
  { key: 'whiff_pct', title: 'Whiff % (Lowest)', fmt: v => `${(v * 100).toFixed(1)}%`, color: C.muted, group: 'Contact', inverse: true },
]

function MiniBar({ value, maxVal, minVal, color, inverse }) {
  const range = maxVal - minVal || 1
  const rawPct = inverse
    ? ((maxVal - value) / range) * 100
    : ((value - minVal) / range) * 100
  const width = Math.max(4, Math.min(100, rawPct))

  return (
    <div style={{ background: C.elevated, borderRadius: '3px', height: '6px', width: '52px', display: 'inline-block', verticalAlign: 'middle' }}>
      <div style={{ width: `${width}%`, height: '100%', background: color, borderRadius: '3px', opacity: 0.85 }} />
    </div>
  )
}

function LeaderboardCard({ title, board, fmtVal, color, inverse = false }) {
  const rows = cleanLeaderboardRows(board)
  if (!rows.length) return null

  const vals = rows.map(r => r.value)
  const maxVal = Math.max(...vals)
  const minVal = Math.min(...vals)

  return (
    <div style={{ background: C.card, border: `1px solid ${C.border}`, borderRadius: '10px', overflow: 'hidden' }}>
      <div style={{ padding: '12px 16px', borderBottom: `1px solid ${C.elevated}`, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <span style={{ fontSize: '13px', fontWeight: '600', color: C.text }}>{title}</span>
        <span style={{ fontSize: '11px', color: color, fontWeight: '600' }}>TOP {rows.length}</span>
      </div>
      {rows.map(row => (
        <div key={`${title}-${row.player_id}`} style={{ display: 'grid', gridTemplateColumns: '22px 1fr auto', gap: '8px', padding: '8px 14px', borderBottom: `1px solid ${C.bg}`, alignItems: 'center' }}>
          <span style={{ fontSize: '11px', color: C.muted, fontWeight: '700', textAlign: 'right' }}>{row.rank}</span>
          <div style={{ overflow: 'hidden' }}>
            <Link
              to={`/batter/${row.player_id}`}
              style={{ color: C.blue, textDecoration: 'none', fontSize: '13px', fontWeight: '500', display: 'block', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}
            >
              {row.player_name}
            </Link>
            <div style={{ fontSize: '11px', color: C.muted }}>
              {row.team ? `${row.team} · ` : ''}
              {row.pa != null ? `${row.pa} PA` : ''}
              {row.bbe != null ? `${row.pa != null ? ' · ' : ''}${row.bbe} BBE` : ''}
            </div>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px', justifyContent: 'flex-end' }}>
            <MiniBar value={row.value} maxVal={maxVal} minVal={minVal} color={color} inverse={inverse} />
            <span style={{ fontSize: '12px', fontWeight: '700', color: C.text, minWidth: '58px', textAlign: 'right' }}>{fmtVal(row.value)}</span>
          </div>
        </div>
      ))}
    </div>
  )
}

function LeaderboardNotes({ data }) {
  const notes = Array.isArray(data?.notes) ? data.notes : []
  const unavailable = Array.isArray(data?.unavailable_metrics) ? data.unavailable_metrics : []

  if (!notes.length && !unavailable.length) return null

  return (
    <div style={{ background: C.card, border: `1px solid ${C.border}`, borderRadius: '8px', padding: '12px 14px', marginBottom: '20px', color: C.muted, fontSize: '12px', lineHeight: 1.5 }}>
      {notes.length > 0 && (
        <div>
          {notes.slice(0, 3).map((note, idx) => (
            <div key={idx}>• {note}</div>
          ))}
        </div>
      )}
      {unavailable.length > 0 && (
        <div style={{ marginTop: notes.length ? '8px' : 0 }}>
          Unavailable or hidden metrics: {unavailable.join(', ')}
        </div>
      )}
    </div>
  )
}

function LeaderboardDashboard({ data, loading }) {
  if (loading) return <FourBlockLoader
    kicker="Scanning qualified hitters"
    title="Loading Batter Leaderboards"
    stages={[
      'Loading qualified batter populations',
      'Reading contact quality and expected results',
      'Comparing plate discipline',
      'Ranking damage and pitch-type performance',
    ]}
    note="The boards apply minimum samples before ranking hitters."
  />
  if (!data) return null

  const leaderboards = data.leaderboards || {}
  const groups = ['Counting', 'Statcast', 'Rate', 'Contact']
  const groupColors = { Counting: C.blue, Statcast: C.orange, Rate: C.green, Contact: C.teal }
  const groupLabels = { Counting: 'Counting Stats', Statcast: 'Statcast & Contact Quality', Rate: 'Plate Discipline', Contact: 'Swing Metrics' }

  const visibleCards = LB_CONFIG.filter(cfg => cleanLeaderboardRows(leaderboards[cfg.key]).length > 0)

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: '16px', flexWrap: 'wrap', gap: '8px' }}>
        <div>
          <h1 style={{ fontSize: '24px', fontWeight: '700', color: C.text, margin: 0 }}>Batter Leaderboards</h1>
          <div style={{ fontSize: '13px', color: C.muted, marginTop: '6px' }}>
            Official MLB season totals joined to canonical Statcast pitch metrics by MLB player ID.
          </div>
        </div>
        <div style={{ fontSize: '13px', color: C.muted, textAlign: 'right' }}>
          {data.season && <div>{data.season} Season · Live Statcast Data</div>}
          {data.latest_event_date && <div>Latest event: {data.latest_event_date}</div>}
        </div>
      </div>

      <LeaderboardNotes data={data} />

      {groups.map(group => {
        const cards = visibleCards.filter(c => c.group === group)
        if (!cards.length) return null

        return (
          <div key={group} style={{ marginBottom: '32px' }}>
            <div style={{ fontSize: '13px', fontWeight: '600', color: groupColors[group], textTransform: 'uppercase', letterSpacing: '0.6px', marginBottom: '12px' }}>
              {groupLabels[group]}
            </div>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(300px, 1fr))', gap: '14px' }}>
              {cards.map(cfg => (
                <LeaderboardCard
                  key={cfg.key}
                  title={cfg.title}
                  board={leaderboards[cfg.key]}
                  fmtVal={cfg.fmt}
                  color={cfg.color}
                  inverse={cfg.inverse}
                />
              ))}
            </div>
          </div>
        )
      })}

      {!visibleCards.length && (
        <div style={{ color: C.muted, textAlign: 'center', padding: '48px', background: C.card, borderRadius: '10px', border: `1px solid ${C.border}` }}>
          No clean leaderboard rows are available yet. Rows without real player names or valid values are hidden.
        </div>
      )}
    </div>
  )
}

// ─── Profile chart helpers ─────────────────────────────────────────────────
function StatCard({ label, value }) {
  return (
    <div style={s.statCard}>
      <div style={s.statLabel}>{label}</div>
      <div style={s.statVal}>{value}</div>
    </div>
  )
}

function DataQualityBox({ quality }) {
  if (!quality) return null
  const warnings = quality.warnings || []
  return (
    <div style={s.qaBox}>
      <div>Data Quality: <strong style={{ color: C.text }}>{quality.ordering_quality || 'unknown'}</strong></div>
      <div>Latest Statcast Event: <strong style={{ color: C.text }}>{quality.latest_event_date || '—'}</strong></div>
      {warnings.map((w, i) => <div key={i} style={s.qaWarn}>⚠ {w}</div>)}
    </div>
  )
}

function GaugeBar({ label, value, leagueAvg, max, unit = '', inverse = false }) {
  if (value == null) return null
  const pctFill = Math.min(100, Math.max(0, (value / max) * 100))
  const leaguePct = Math.min(100, Math.max(0, (leagueAvg / max) * 100))
  const isGood = inverse ? value <= leagueAvg : value >= leagueAvg
  const color = isGood ? C.green : C.orange
  return (
    <div style={{ marginBottom: '18px' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '7px', fontSize: '13px' }}>
        <span style={{ color: C.muted }}>{label}</span>
        <div style={{ display: 'flex', gap: '12px', alignItems: 'center' }}>
          <span style={{ color: C.muted, fontSize: '11px' }}>Lg avg: {leagueAvg}{unit}</span>
          <span style={{ color, fontWeight: '700' }}>{value.toFixed(1)}{unit}</span>
        </div>
      </div>
      <div style={{ background: C.elevated, borderRadius: '4px', height: '10px', position: 'relative' }}>
        <div style={{ width: `${pctFill}%`, height: '100%', background: color, borderRadius: '4px', opacity: 0.85 }} />
        <div style={{ position: 'absolute', top: '-3px', left: `${leaguePct}%`, width: '2px', height: '16px', background: C.muted, opacity: 0.6, transform: 'translateX(-50%)' }} />
      </div>
    </div>
  )
}

function StatcastGauges({ sc, agg }) {
  const data = sc || agg
  if (!data) return null
  return (
    <div style={{ ...s.chartBox, padding: '24px 28px' }}>
      <div style={{ fontSize: '13px', color: C.muted, marginBottom: '20px' }}>
        Bars show player value vs MLB average. Green = above average, orange = below average.
      </div>
      <GaugeBar label="Avg Exit Velocity" value={data.avg_exit_velocity} leagueAvg={LEAGUE_AVGS.avg_exit_velocity} max={115} unit=" mph" />
      <GaugeBar label="Hard Hit%" value={data.hard_hit_pct != null ? data.hard_hit_pct * 100 : null} leagueAvg={LEAGUE_AVGS.hard_hit_pct * 100} max={80} unit="%" />
      <GaugeBar label="Barrel%" value={data.barrel_pct != null ? data.barrel_pct * 100 : null} leagueAvg={LEAGUE_AVGS.barrel_pct * 100} max={25} unit="%" />
      <GaugeBar label="K%" value={data.k_pct != null ? data.k_pct * 100 : null} leagueAvg={LEAGUE_AVGS.k_pct * 100} max={50} unit="%" inverse />
      <GaugeBar label="BB%" value={data.bb_pct != null ? data.bb_pct * 100 : null} leagueAvg={LEAGUE_AVGS.bb_pct * 100} max={20} unit="%" />
    </div>
  )
}

function SeasonTrendChart({ yby }) {
  if (!yby || yby.length < 2) return null
  const data = [...yby].sort((a, b) => a.season - b.season).map(row => ({
    season: String(row.season),
    AVG: row.batting_avg != null ? +row.batting_avg.toFixed(3) : null,
    OBP: row.on_base_pct != null ? +row.on_base_pct.toFixed(3) : null,
    SLG: row.slugging_pct != null ? +row.slugging_pct.toFixed(3) : null,
    OPS: row.ops != null ? +row.ops.toFixed(3) : null,
  }))
  return (
    <div style={s.chartBox}>
      <ResponsiveContainer width="100%" height={260}>
        <LineChart data={data} margin={{ top: 8, right: 24, left: 0, bottom: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke={C.elevated} />
          <XAxis dataKey="season" tick={{ fill: C.muted, fontSize: 12 }} axisLine={{ stroke: C.border }} tickLine={false} />
          <YAxis domain={['auto', 'auto']} tick={{ fill: C.muted, fontSize: 11 }} axisLine={false} tickLine={false} width={48} />
          <Tooltip contentStyle={tooltipStyle} labelStyle={{ color: C.blue, fontWeight: 600 }} />
          <Legend wrapperStyle={{ fontSize: '12px', paddingTop: '12px' }} />
          <ReferenceLine y={0.250} stroke={C.muted} strokeDasharray="4 4" opacity={0.4} />
          <Line type="monotone" dataKey="AVG" stroke={C.green} strokeWidth={2} dot={{ r: 3, fill: C.green }} activeDot={{ r: 5 }} connectNulls />
          <Line type="monotone" dataKey="OBP" stroke={C.blue} strokeWidth={2} dot={{ r: 3, fill: C.blue }} activeDot={{ r: 5 }} connectNulls />
          <Line type="monotone" dataKey="SLG" stroke={C.orange} strokeWidth={2} dot={{ r: 3, fill: C.orange }} activeDot={{ r: 5 }} connectNulls />
          <Line type="monotone" dataKey="OPS" stroke={C.purple} strokeWidth={2} dot={{ r: 3, fill: C.purple }} activeDot={{ r: 5 }} connectNulls />
        </LineChart>
      </ResponsiveContainer>
    </div>
  )
}

function HRTrendChart({ yby }) {
  if (!yby || yby.length < 2) return null
  const data = [...yby].sort((a, b) => a.season - b.season).map(row => ({
    season: String(row.season),
    HR: row.hr ?? 0,
    SB: row.sb ?? 0,
  }))
  return (
    <div style={s.chartBox}>
      <ResponsiveContainer width="100%" height={220}>
        <BarChart data={data} margin={{ top: 8, right: 24, left: 0, bottom: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke={C.elevated} vertical={false} />
          <XAxis dataKey="season" tick={{ fill: C.muted, fontSize: 12 }} axisLine={{ stroke: C.border }} tickLine={false} />
          <YAxis tick={{ fill: C.muted, fontSize: 11 }} axisLine={false} tickLine={false} width={32} />
          <Tooltip contentStyle={tooltipStyle} labelStyle={{ color: C.blue, fontWeight: 600 }} />
          <Legend wrapperStyle={{ fontSize: '12px', paddingTop: '12px' }} />
          <Bar dataKey="HR" fill={C.blue} radius={[3, 3, 0, 0]} maxBarSize={36} />
          <Bar dataKey="SB" fill={C.green} radius={[3, 3, 0, 0]} maxBarSize={36} />
        </BarChart>
      </ResponsiveContainer>
    </div>
  )
}

function PlatoonChart({ splits }) {
  if (!splits?.vsL && !splits?.vsR) return null
  const vsL = splits.vsL
  const vsR = splits.vsR
  const metrics = [
    { key: 'batting_avg', label: 'AVG', scale: 1000 },
    { key: 'on_base_pct', label: 'OBP', scale: 1000 },
    { key: 'slugging_pct', label: 'SLG', scale: 1000 },
    { key: 'k_pct', label: 'K%', scale: 100 },
    { key: 'bb_pct', label: 'BB%', scale: 100 },
  ]
  const data = metrics.map(m => ({
    label: m.label,
    'vs LHP': vsL?.[m.key] != null ? +(vsL[m.key] * m.scale).toFixed(1) : null,
    'vs RHP': vsR?.[m.key] != null ? +(vsR[m.key] * m.scale).toFixed(1) : null,
  }))
  return (
    <div style={s.chartBox}>
      <div style={{ fontSize: '13px', color: C.muted, marginBottom: '12px' }}>
        AVG/OBP/SLG ×1000 · K%/BB% as percentage
      </div>
      <ResponsiveContainer width="100%" height={200}>
        <BarChart data={data} margin={{ top: 4, right: 16, left: 0, bottom: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke={C.elevated} vertical={false} />
          <XAxis dataKey="label" tick={{ fill: C.muted, fontSize: 12 }} axisLine={false} tickLine={false} />
          <YAxis tick={{ fill: C.muted, fontSize: 11 }} axisLine={false} tickLine={false} width={36} />
          <Tooltip contentStyle={tooltipStyle} labelStyle={{ color: C.orange, fontWeight: 600 }} />
          <Legend wrapperStyle={{ fontSize: '12px', paddingTop: '8px' }} />
          <Bar dataKey="vs LHP" fill={C.purple} radius={[3, 3, 0, 0]} maxBarSize={40} />
          <Bar dataKey="vs RHP" fill={C.blue} radius={[3, 3, 0, 0]} maxBarSize={40} />
        </BarChart>
      </ResponsiveContainer>
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '12px', marginTop: '20px' }}>
        {[['vs LHP', vsL, C.purple], ['vs RHP', vsR, C.blue]].map(([title, split, color]) => (
          <div key={title} style={{ background: C.elevated, borderRadius: '8px', padding: '14px' }}>
            <div style={{ fontSize: '13px', fontWeight: '600', color, marginBottom: '10px' }}>{title} · {split?.pa ?? '—'} PA</div>
            {split ? [
              ['AVG', fmt(split.batting_avg, 3)], ['OBP', fmt(split.on_base_pct, 3)],
              ['SLG', fmt(split.slugging_pct, 3)], ['OPS', fmt(split.ops, 3)],
              ['K%', pct(split.k_pct)], ['BB%', pct(split.bb_pct)],
            ].map(([k, v]) => (
              <div key={k} style={{ display: 'flex', justifyContent: 'space-between', padding: '4px 0', fontSize: '13px', borderBottom: `1px solid ${C.border}` }}>
                <span style={{ color: C.muted }}>{k}</span>
                <span style={{ color: C.text, fontWeight: '500' }}>{v}</span>
              </div>
            )) : <div style={{ color: C.muted, fontSize: '13px' }}>No data</div>}
          </div>
        ))}
      </div>
    </div>
  )
}

// ─── Main page ─────────────────────────────────────────────────────────────
export default function BatterPage() {
  const { id } = useParams()
  const navigate = useNavigate()
  const [query, setQuery] = useState('')
  const [results, setResults] = useState([])
  const [searching, setSearching] = useState(false)
  const [hoverIdx, setHoverIdx] = useState(-1)
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const [lbData, setLbData] = useState(null)
  const [lbLoading, setLbLoading] = useState(false)
  const [lbError, setLbError] = useState(null)
  const debounceRef = React.useRef(null)

  // Load player profile when id is present
  useEffect(() => {
    if (!id) { setData(null); return }
    setLoading(true); setError(null); setResults([])
    fetch(`${API}/batter/${id}/profile`)
      .then(r => r.ok ? r.json() : r.json().then(e => Promise.reject(e.detail || r.statusText)))
      .then(d => { setData(d); setLoading(false) })
      .catch(e => { setError(String(e)); setLoading(false); setData(null) })
  }, [id])

  // Load leaderboards on landing page (no player selected)
  useEffect(() => {
    if (id) return

    let cancelled = false
    setLbLoading(true)
    setLbError(null)

    fetch(`${API}/batters/leaderboards?contract=batter_leaderboards_v3`)
      .then(r => r.ok ? r.json() : r.json().then(e => Promise.reject(e.detail || r.statusText)))
      .then(d => {
        if (cancelled) return
        setLbData(d)
        setLbLoading(false)
      })
      .catch(e => {
        if (cancelled) return
        setLbError(String(e))
        setLbLoading(false)
      })

    return () => {
      cancelled = true
    }
  }, [id])

  function onQueryChange(e) {
    const val = e.target.value
    setQuery(val); setHoverIdx(-1)
    clearTimeout(debounceRef.current)
    if (val.length < 2) { setResults([]); return }
    debounceRef.current = setTimeout(() => {
      setSearching(true)
      fetch(`${API}/players/search?name=${encodeURIComponent(val)}`)
        .then(r => r.ok ? r.json() : [])
        .then(d => { setResults((d || []).filter(p => p.position_type === 'Batter')); setSearching(false) })
        .catch(() => setSearching(false))
    }, 300)
  }

  function selectPlayer(p) {
    setQuery(p.name); setResults([])
    navigate(`/batter/${p.id}`)
  }

  const info = data?.player_info
  const ss = data?.season_stats
  const sc = data?.statcast
  const splits = data?.splits || {}
  const yby = data?.year_by_year || []
  const agg = data?.aggregate
  const dq = data?.data_quality

  return (
    <div>
      {/* Search — always visible at top */}
      <div style={{ position: 'relative', marginBottom: id ? '28px' : '20px' }}>
        <div style={s.searchRow}>
          <input
            style={s.input}
            placeholder="Search batter by name (e.g. Aaron Judge) — or browse leaderboards below"
            value={query}
            onChange={onQueryChange}
            autoComplete="off"
          />
          {searching && <span style={{ color: C.muted, fontSize: '13px', alignSelf: 'center' }}>Searching…</span>}
          {id && (
            <button
              onClick={() => { setQuery(''); navigate('/batter') }}
              style={{ background: C.elevated, border: `1px solid ${C.border}`, color: C.muted, borderRadius: '6px', padding: '0 14px', fontSize: '13px', cursor: 'pointer' }}
            >
              ← Leaderboards
            </button>
          )}
        </div>
        {results.length > 0 && (
          <div style={searchDropStyle}>
            {results.slice(0, 10).map((p, i) => (
              <div key={p.id} style={searchItemStyle(i === hoverIdx)}
                onMouseEnter={() => setHoverIdx(i)} onMouseLeave={() => setHoverIdx(-1)}
                onClick={() => selectPlayer(p)}>
                <span style={{ color: C.text }}>{p.name}</span>
                <span style={{ color: C.muted, fontSize: '12px' }}>{p.team || ''}</span>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* ── Landing dashboard (no player selected) ── */}
      {!id && (
        <>
          {lbError && <div style={s.error}>Leaderboard error: {lbError}</div>}
          <LeaderboardDashboard
            data={lbData}
            loading={lbLoading}
          />
        </>
      )}

      {/* ── Player profile ── */}
      {id && (
        <>
          {loading && <FourBlockLoader
        kicker="Building hitter intelligence"
        title="Loading Batter Profile"
        stages={[
          'Resolving player identity and team',
          'Loading Statcast contact metrics',
          'Reading plate discipline and expected results',
          'Building pitch-type and zone views',
          'Loading recent performance',
        ]}
        note="This profile combines multiple hitter research datasets."
      />}
          {error && <div style={{ color: C.red, padding: '24px', background: '#1f1116', borderRadius: '8px' }}>{error}</div>}

          {data && (
            <>
              {info && (
                <div style={s.playerHeader}>
                  <div style={s.playerName}>{info.name}</div>
                  <div style={s.playerMeta}>
                    {info.position && <span style={s.metaChip}>{info.position}</span>}
                    {info.team && <span style={s.metaChip}>{info.team}</span>}
                    {info.bats && <span>Bats: <strong style={{ color: C.text }}>{info.bats}</strong></span>}
                    {info.throws && <span>Throws: <strong style={{ color: C.text }}>{info.throws}</strong></span>}
                    {info.mlb_debut && <span>Debut: <strong style={{ color: C.text }}>{info.mlb_debut?.slice(0, 4)}</strong></span>}
                  </div>
                </div>
              )}

              <DataQualityBox quality={dq} />

              <Link to={`/batter/${id}/rolling`} style={s.rollingLink}>
                View Rolling Stats (PA / AB / Games)
              </Link>

              {ss && (
                <div style={s.section}>
                  <div style={s.sectionTitle}>
                    Season Stats <span style={s.sourceBadge}>MLB Stats API</span>
                  </div>
                  <div style={s.statsGrid}>
                    <StatCard label="AVG" value={fmt(ss.batting_avg ?? ss.avg, 3)} />
                    <StatCard label="OBP" value={fmt(ss.on_base_pct ?? ss.obp, 3)} />
                    <StatCard label="SLG" value={fmt(ss.slugging_pct ?? ss.slg, 3)} />
                    <StatCard label="OPS" value={fmt(ss.ops, 3)} />
                    <StatCard label="HR" value={num(ss.hr)} />
                    <StatCard label="RBI" value={num(ss.rbi)} />
                    <StatCard label="SB" value={num(ss.sb)} />
                    <StatCard label="PA" value={num(ss.pa ?? ss.plate_appearances)} />
                  </div>
                </div>
              )}

              {sc && (
                <div style={s.section}>
                  <div style={s.sectionTitle}>
                    Statcast Profile <span style={s.sourceBadge}>Local Statcast</span>
                  </div>
                  <div style={s.statsGrid}>
                    <StatCard label="Avg EV" value={sc.avg_exit_velocity ? `${fmt(sc.avg_exit_velocity)} mph` : '—'} />
                    <StatCard label="Max EV" value={sc.max_exit_velocity ? `${fmt(sc.max_exit_velocity)} mph` : '—'} />
                    <StatCard label="Avg LA" value={sc.avg_launch_angle ? `${fmt(sc.avg_launch_angle)}°` : '—'} />
                    <StatCard label="Hard Hit%" value={pct(sc.hard_hit_pct)} />
                    <StatCard label="Barrel%" value={pct(sc.barrel_pct)} />
                    <StatCard label="K%" value={pct(sc.k_pct)} />
                    <StatCard label="BB%" value={pct(sc.bb_pct)} />
                    <StatCard label="PA" value={num(sc.actual_pa)} />
                  </div>
                </div>
              )}

              {(sc || agg) && (
                <div style={s.section}>
                  <div style={s.sectionTitle}>Baseball Savant-Style Profile Bars</div>
                  <StatcastGauges sc={sc} agg={agg} />
                </div>
              )}

              {yby.length > 1 && (
                <div style={s.section}>
                  <div style={s.sectionTitle}>Year-by-Year Slash Line Trend</div>
                  <SeasonTrendChart yby={yby} />
                </div>
              )}

              {yby.length > 1 && (
                <div style={s.section}>
                  <div style={s.sectionTitle}>Power / Speed Trend</div>
                  <HRTrendChart yby={yby} />
                </div>
              )}

              {(splits.vsL || splits.vsR) && (
                <div style={s.section}>
                  <div style={s.sectionTitle}>
                    Platoon Splits <span style={s.sourceBadge}>vs LHP / vs RHP</span>
                  </div>
                  <PlatoonChart splits={splits} />
                </div>
              )}

              {data.pitch_type_matchups && data.pitch_type_matchups.length > 0 && (
                <div style={s.section}>
                  <div style={s.sectionTitle}>
                    Pitch-Type Performance <span style={s.sourceBadge}>Batter vs Pitch Type</span>
                  </div>
                  <div style={s.tableWrap}>
                    <table style={s.table}>
                      <thead>
                        <tr>
                          <th style={s.th}>Pitch</th>
                          <th style={{ ...s.th, ...s.thR }}>PA</th>
                          <th style={{ ...s.th, ...s.thR }}>AVG</th>
                          <th style={{ ...s.th, ...s.thR }}>SLG</th>
                          <th style={{ ...s.th, ...s.thR }}>wOBA</th>
                          <th style={{ ...s.th, ...s.thR }}>Whiff%</th>
                        </tr>
                      </thead>
                      <tbody>
                        {data.pitch_type_matchups.map(row => (
                          <tr key={row.pitch_type}>
                            <td style={{ ...s.td, color: C.blue, fontWeight: '600' }}>{row.pitch_type}</td>
                            <td style={{ ...s.td, ...s.tdR }}>{num(row.pa)}</td>
                            <td style={{ ...s.td, ...s.tdR }}>{fmt(row.batting_avg, 3)}</td>
                            <td style={{ ...s.td, ...s.tdR }}>{fmt(row.slugging_pct, 3)}</td>
                            <td style={{ ...s.td, ...s.tdR }}>{fmt(row.woba, 3)}</td>
                            <td style={{ ...s.td, ...s.tdR }}>{pct(row.whiff_pct)}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              )}

              {!ss && !sc && !agg && (
                <div style={{ color: C.muted, textAlign: 'center', padding: '48px' }}>
                  No batter profile data available for this player yet.
                </div>
              )}
            </>
          )}
        </>
      )}
    </div>
  )
}

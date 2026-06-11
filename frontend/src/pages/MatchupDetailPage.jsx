import React, { useState, useEffect } from 'react'
import { fmtPct, fmtDec } from '../utils/formatters'
import { useParams, Link } from 'react-router-dom'
import { API_BASE } from '../lib/api'

const API = API_BASE

const PITCH_NAMES = {
  FF: '4-Seam', SI: 'Sinker', FC: 'Cutter', FS: 'Splitter',
  CH: 'Changeup', CU: 'Curveball', SL: 'Slider', ST: 'Sweeper',
  KC: 'Knuckle-Curve', SV: 'Slurve', KN: 'Knuckleball', PO: 'Pitchout', UN: 'Unknown',
}

const t = {
  page: { width: '100%', maxWidth: '100%', overflowX: 'hidden' },
  back: { color: '#58a6ff', textDecoration: 'none', fontSize: '13px', display: 'inline-block', marginBottom: '20px' },
  header: { background: '#161b22', border: '1px solid #30363d', borderRadius: '10px', padding: '20px 24px', marginBottom: '20px' },
  headerTop: { display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', flexWrap: 'wrap', gap: '12px' },
  teamsRow: { display: 'flex', alignItems: 'center', gap: '16px', flexWrap: 'wrap' },
  teamBlock: { textAlign: 'center' },
  teamName: { fontSize: '20px', fontWeight: '700', color: '#e6edf3' },
  teamRecord: { fontSize: '13px', color: '#8b949e', marginTop: '2px' },
  at: { fontSize: '20px', color: '#8b949e', fontWeight: '600', padding: '0 4px' },
  metaText: { fontSize: '13px', color: '#8b949e' },
  statusBadge: { display: 'inline-block', background: '#1f3a1f', color: '#3fb950', borderRadius: '4px', padding: '3px 8px', fontSize: '12px', fontWeight: '600' },
  parkBadge: { display: 'inline-block', background: '#21262d', color: '#8b949e', borderRadius: '4px', padding: '3px 8px', fontSize: '12px' },
  probSection: { background: '#161b22', border: '1px solid #30363d', borderRadius: '10px', padding: '20px 24px', marginBottom: '20px' },
  probRow: { display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '12px' },
  probTeam: { fontSize: '15px', fontWeight: '600', color: '#e6edf3' },
  probPct: { fontSize: '32px', fontWeight: '800' },
  probBar: { height: '10px', borderRadius: '5px', overflow: 'hidden', background: '#21262d', display: 'flex' },
  section: { background: '#161b22', border: '1px solid #30363d', borderRadius: '10px', padding: '20px 24px', marginBottom: '20px', maxWidth: '100%', overflowX: 'hidden' },
  sectionTitle: { fontSize: '15px', fontWeight: '600', color: '#e6edf3', marginBottom: '16px', borderBottom: '1px solid #21262d', paddingBottom: '8px' },
  pitcherGrid: { display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(min(100%, 520px), 1fr))', gap: '20px', maxWidth: '100%', overflowX: 'hidden' },
  pitcherCard: { background: '#0d1117', border: '1px solid #21262d', borderRadius: '8px', padding: '16px', minWidth: 0, maxWidth: '100%', overflowX: 'hidden' },
  pitcherName: { fontSize: '16px', fontWeight: '700', color: '#e6edf3', marginBottom: '4px' },
  dataSource: { fontSize: '11px', color: '#8b949e', marginBottom: '12px' },
  statRow: { display: 'flex', justifyContent: 'space-between', padding: '5px 0', borderBottom: '1px solid #161b22', fontSize: '13px' },
  statKey: { color: '#8b949e' },
  statVal: { color: '#e6edf3', fontWeight: '500' },
  arsenalTableWrap: { width: '100%', maxWidth: '100%', overflowX: 'auto', marginTop: '12px' },
  arsenalTable: { width: '100%', minWidth: '620px', borderCollapse: 'collapse', fontSize: '12px' },
  th: { padding: '6px 8px', textAlign: 'left', color: '#8b949e', fontSize: '11px', textTransform: 'uppercase', borderBottom: '1px solid #21262d', whiteSpace: 'nowrap' },
  td: { padding: '6px 8px', borderBottom: '1px solid #0d1117', color: '#e6edf3', verticalAlign: 'top' },
  splitsGrid: { display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '20px' },
  splitCard: { background: '#0d1117', border: '1px solid #21262d', borderRadius: '8px', padding: '16px' },
  splitTitle: { fontSize: '14px', fontWeight: '600', color: '#58a6ff', marginBottom: '10px' },
  logTable: { width: '100%', borderCollapse: 'collapse', fontSize: '13px' },
  lineupGrid: { display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '20px' },
  lineupItem: { display: 'flex', gap: '10px', padding: '5px 0', borderBottom: '1px solid #0d1117', fontSize: '13px', color: '#e6edf3' },
  orderNum: { color: '#8b949e', width: '20px', flexShrink: 0 },
  loader: { color: '#8b949e', padding: '48px', textAlign: 'center' },
  error: { color: '#f85149', padding: '24px', background: '#1f1116', borderRadius: '8px' },
  compTabs: { display: 'flex', gap: '0', marginBottom: '16px', background: '#0d1117', border: '1px solid #21262d', borderRadius: '6px', overflow: 'hidden', width: 'fit-content' },
  compTab: (active) => ({ padding: '7px 16px', fontSize: '13px', fontWeight: '500', cursor: 'pointer', background: active ? '#58a6ff' : 'transparent', color: active ? '#0d1117' : '#8b949e', border: 'none', outline: 'none' }),
  batterRow: { background: '#0d1117', border: '1px solid #21262d', borderRadius: '8px', marginBottom: '10px', overflow: 'hidden' },
  batterHeader: { display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '10px 14px', cursor: 'pointer', userSelect: 'none' },
  batterName: { fontSize: '14px', fontWeight: '600', color: '#e6edf3' },
  edgeBadge: (edge) => ({
    fontSize: '11px', fontWeight: '700', padding: '2px 7px', borderRadius: '3px',
    background: edge > 0.15 ? '#1f3a1f' : edge < -0.15 ? '#3a1f1f' : '#21262d',
    color: edge > 0.15 ? '#3fb950' : edge < -0.15 ? '#f85149' : '#8b949e',
  }),
  matchupTable: { width: '100%', borderCollapse: 'collapse', fontSize: '12px' },
  mth: { padding: '7px 10px', textAlign: 'left', color: '#8b949e', fontSize: '10px', textTransform: 'uppercase', letterSpacing: '0.5px', borderBottom: '1px solid #21262d', borderTop: '1px solid #21262d', background: '#0a0f14' },
  mtd: { padding: '7px 10px', borderBottom: '1px solid #161b22', color: '#e6edf3' },
  mtdR: { textAlign: 'right' },
  noData: { color: '#8b949e', fontSize: '13px', textAlign: 'center', padding: '24px' },
  pitchWidgetGrid: { display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(260px, 1fr))', gap: '12px', marginTop: '12px' },
  pitchWidget: (edge) => ({
    background: 'linear-gradient(180deg, #101820 0%, #0d1117 100%)',
    border: `1px solid ${edge > 0.15 ? '#2ea043' : edge < -0.15 ? '#da3633' : '#30363d'}`,
    borderRadius: '12px',
    padding: '14px',
    boxShadow: edge > 0.15 ? '0 0 0 1px rgba(46,160,67,0.08), 0 8px 24px rgba(0,0,0,0.22)' : edge < -0.15 ? '0 0 0 1px rgba(218,54,51,0.08), 0 8px 24px rgba(0,0,0,0.22)' : '0 8px 24px rgba(0,0,0,0.18)',
  }),
  pitchWidgetTop: { display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: '10px', marginBottom: '12px' },
  pitchTypeBig: { fontSize: '18px', fontWeight: '800', color: '#e6edf3', letterSpacing: '0.2px' },
  pitchNameSmall: { fontSize: '11px', color: '#8b949e', marginTop: '2px', textTransform: 'uppercase', letterSpacing: '0.6px' },
  sourceBadge: (source) => ({
    fontSize: '10px', fontWeight: '700', padding: '3px 7px', borderRadius: '999px', whiteSpace: 'nowrap',
    background: source === 'batter_pitch_type_matchups' ? '#102b1b' : '#21262d',
    color: source === 'batter_pitch_type_matchups' ? '#3fb950' : '#8b949e',
    border: `1px solid ${source === 'batter_pitch_type_matchups' ? '#238636' : '#30363d'}`,
  }),
  metricPillGrid: { display: 'grid', gridTemplateColumns: 'repeat(4, minmax(0, 1fr))', gap: '8px', marginBottom: '12px' },
  metricPill: { background: '#0a0f14', border: '1px solid #21262d', borderRadius: '8px', padding: '8px', minHeight: '48px' },
  metricLabel: { color: '#8b949e', fontSize: '10px', textTransform: 'uppercase', letterSpacing: '0.5px', marginBottom: '4px' },
  metricValue: { color: '#e6edf3', fontSize: '15px', fontWeight: '800' },
  sampleStrip: { display: 'grid', gridTemplateColumns: 'repeat(4, minmax(0, 1fr))', gap: '6px', marginBottom: '12px' },
  sampleCell: { background: '#161b22', border: '1px solid #21262d', borderRadius: '7px', padding: '7px', textAlign: 'center' },
  sampleNum: { color: '#e6edf3', fontSize: '14px', fontWeight: '800' },
  sampleLabel: { color: '#8b949e', fontSize: '9px', textTransform: 'uppercase', letterSpacing: '0.4px', marginTop: '2px' },
  rateStack: { display: 'flex', flexDirection: 'column', gap: '8px' },
  rateRow: { display: 'grid', gridTemplateColumns: '105px 1fr 44px', alignItems: 'center', gap: '8px', fontSize: '11px' },
  rateLabel: { color: '#8b949e', textTransform: 'uppercase', letterSpacing: '0.4px' },
  rateTrack: { height: '7px', background: '#21262d', borderRadius: '999px', overflow: 'hidden' },
  rateFill: (value, variant = 'neutral') => ({
    height: '100%',
    width: `${Math.max(0, Math.min(100, Number(value || 0) * 100))}%`,
    background: variant === 'good' ? '#3fb950' : variant === 'bad' ? '#f85149' : '#58a6ff',
    borderRadius: '999px',
  }),
  rateValue: { color: '#e6edf3', textAlign: 'right', fontWeight: '700' },
  widgetFooter: { display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: '10px', borderTop: '1px solid #21262d', paddingTop: '10px', marginTop: '12px' },
  confidenceWrap: { display: 'flex', alignItems: 'center', gap: '8px', minWidth: '130px' },
}

const pct = (v, d = 1) => fmtPct(v, d)
const dec = (v, d = 3) => fmtDec(v, d)
const mph = v => v != null ? `${Number(v).toFixed(1)}` : '—'
const intVal = v => v != null && !Number.isNaN(Number(v)) ? Number(v).toLocaleString() : '—'

function pickMetric(obj, keys, fallback = null) {
  for (const key of keys) {
    if (obj && obj[key] != null) return obj[key]
  }
  return fallback
}

function confidenceVariant(value) {
  if (value == null) return 'neutral'
  if (value >= 0.70) return 'good'
  if (value <= 0.45) return 'bad'
  return 'neutral'
}

function hitterRiskVariant(value, strong = 0.30, medium = 0.22) {
  if (value == null) return 'neutral'
  if (value >= strong) return 'bad'
  if (value >= medium) return 'neutral'
  return 'good'
}

function hitterDamageVariant(value, strong = 0.40, medium = 0.32) {
  if (value == null) return 'neutral'
  if (value >= strong) return 'good'
  if (value >= medium) return 'neutral'
  return 'bad'
}

function sourceLabel(source) {
  if (source === 'batter_pitch_type_matchups') return 'Stored 365'
  if (source === 'live_statcast_events_fallback') return 'Fallback'
  return 'Live'
}

function arsenalSourceLabel(source) {
  if (source === 'savant_arsenal_leaderboard') return 'Savant'
  if (source === 'raw_statcast_aggregated') return 'Raw Statcast'
  if (source === 'live_statcast_events_fallback') return 'Live Savant'
  if (source) return source
  return 'Legacy'
}

function arsenalFlagLabel(flag) {
  if (flag === 'small_pitch_sample') return 'Small sample'
  if (flag === 'unstable_pa_end_k_rate') return 'Unstable K%'
  if (flag === 'no_xwoba_sample') return 'No xwOBA'
  if (flag === 'low_batted_ball_sample') return 'Low BBE'
  if (flag === 'raw_statcast_fallback') return 'Fallback'
  return flag
}

function probColor(p) {
  if (p == null) return '#8b949e'
  if (p >= 0.62) return '#3fb950'
  if (p >= 0.50) return '#d29922'
  return '#f85149'
}

function parkLabel(factor) {
  if (factor >= 1.10) return `Park +${Math.round((factor - 1) * 100)}% (Hitter-friendly)`
  if (factor >= 1.03) return `Park +${Math.round((factor - 1) * 100)}% (Slight hitter-friendly)`
  if (factor <= 0.92) return `Park ${Math.round((factor - 1) * 100)}% (Pitcher-friendly)`
  if (factor <= 0.97) return `Park ${Math.round((factor - 1) * 100)}% (Slight pitcher-friendly)`
  return 'Neutral park'
}

function formatTime(iso) {
  if (!iso) return null
  try { return new Date(iso).toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit', timeZone: 'America/New_York' }) + ' ET' }
  catch { return null }
}

function weatherLabel(weather) {
  if (!weather) return null
  const bits = []
  if (weather.temp_f != null) bits.push(`${weather.temp_f}°F`)
  if (weather.condition) bits.push(weather.condition)
  if (weather.wind) bits.push(weather.wind)
  return bits.length ? bits.join(' · ') : null
}

function edgeLabel(score) {
  if (score == null) return '—'
  if (score > 0.15) return `Hitter Edge ${(score > 0 ? '+' : '') + score.toFixed(2)}`
  if (score < -0.15) return `Pitcher Edge ${score.toFixed(2)}`
  return `Neutral ${(score > 0 ? '+' : '') + score.toFixed(2)}`
}

function edgeMeta(score) {
  if (score == null) return { label: 'Neutral', color: '#8b949e' }
  if (score > 0.15) return { label: 'Hitter Edge', color: '#3fb950' }
  if (score < -0.15) return { label: 'Pitcher Edge', color: '#f85149' }
  return { label: 'Neutral', color: '#8b949e' }
}

function tooltipFor(label) {
  const tips = {
    'Usage': 'How often the pitcher throws this pitch. More relevant, not automatically better.',
    'Hitter Whiff%': 'How often this hitter swings and misses vs this pitch type. Higher favors the pitcher.',
    'Hitter K%': 'How often this hitter’s PA ends in a strikeout vs this pitch type. Higher favors the pitcher.',
    'PutAway Risk': 'Two-strike finish risk for the hitter on this pitch type. Higher favors the pitcher.',
    'Hitter HardHit%': 'Share of batted balls hit 95+ mph by the hitter vs this pitch type. Higher favors the hitter.',
    'Pitcher xwOBA Allowed': 'Expected offensive value allowed by the pitcher on this pitch. Higher favors the hitter.',
    'Confidence': 'Sample/relevance confidence, not betting certainty.',
    'Edge Score': 'Composite pitch-type interaction score. Positive favors the hitter; negative favors the pitcher.',
  }
  return tips[label] || label
}

function PitcherCard({ side, pitcherName, pitcherId, detail }) {
  const profileOverview = detail?.profile_overview || null
  const agg = detail?.aggregate || {}
  const arsenal = (detail?.profile_arsenal && detail.profile_arsenal.length > 0)
    ? detail.profile_arsenal
    : (detail?.arsenal || [])
  const gameLog = (detail?.profile_recent_games && detail.profile_recent_games.length > 0)
    ? detail.profile_recent_games
    : (detail?.game_log || [])

  const sourceLabelText = profileOverview?.profile_source || agg.data_source || 'No data'

  const overviewRows = profileOverview
    ? [
        ['ERA', dec(profileOverview.era)],
        ['WHIP', dec(profileOverview.whip)],
        ['FIP', dec(profileOverview.fip)],
        ['SIERA', dec(profileOverview.siera)],
        ['K%', pct(pickMetric(profileOverview, ['k_pct'], agg.k_pct))],
        ['BB%', pct(pickMetric(profileOverview, ['bb_pct'], agg.bb_pct))],
        ['K-BB%', pct(pickMetric(profileOverview, ['k_minus_bb_pct']))],
        ['HR/9', dec(profileOverview.hr_per_9)],
        ['xwOBA', dec(pickMetric(profileOverview, ['xwoba_allowed'], agg.xwoba))],
        ['xBA', dec(profileOverview.xba_allowed)],
        ['Hard Hit%', pct(pickMetric(profileOverview, ['hard_hit_pct', 'hard_hit_rate_allowed'], agg.hard_hit_pct))],
        ['Barrel%', pct(pickMetric(profileOverview, ['barrel_pct', 'barrel_rate_allowed']))],
        ['Velocity', pickMetric(profileOverview, ['avg_velocity'], agg.avg_velocity) != null ? `${Number(pickMetric(profileOverview, ['avg_velocity'], agg.avg_velocity)).toFixed(1)} mph` : '—'],
        ['Spin Rate', pickMetric(profileOverview, ['avg_spin_rate'], agg.avg_spin_rate) != null ? `${Math.round(Number(pickMetric(profileOverview, ['avg_spin_rate'], agg.avg_spin_rate)))} rpm` : '—'],
        ['IP', profileOverview.innings_pitched != null ? Number(profileOverview.innings_pitched).toFixed(1) : '—'],
        ['Batters Faced', intVal(profileOverview.batters_faced)],
      ]
    : [
        ['K%', pct(agg.k_pct)],
        ['BB%', pct(agg.bb_pct)],
        ['xwOBA', dec(agg.xwoba)],
        ['Hard Hit%', pct(agg.hard_hit_pct)],
        ['Velocity', agg.avg_velocity != null ? `${Number(agg.avg_velocity).toFixed(1)} mph` : '—'],
        ['Spin Rate', agg.avg_spin_rate != null ? `${Math.round(Number(agg.avg_spin_rate))} rpm` : '—'],
        ['Horiz Break', agg.avg_horiz_break != null ? `${Number(agg.avg_horiz_break).toFixed(2)}"` : '—'],
        ['Vert Break', agg.avg_vert_break != null ? `${Number(agg.avg_vert_break).toFixed(2)}"` : '—'],
      ]

  return (
    <div style={t.pitcherCard}>
      <div style={{ fontSize: '12px', color: '#8b949e', marginBottom: '4px', textTransform: 'uppercase', letterSpacing: '0.5px' }}>{side}</div>
      <div style={t.pitcherName}>
        {pitcherId
          ? <Link to={`/pitcher/${pitcherId}`} style={{ color: '#e6edf3', textDecoration: 'none' }}>{pitcherName || `ID ${pitcherId}`}</Link>
          : <span style={{ color: '#8b949e' }}>TBD</span>}
      </div>
      <div style={t.dataSource}>{sourceLabelText}</div>

      {overviewRows.map(([k, v]) => (
        <div key={k} style={t.statRow}>
          <span style={t.statKey}>{k}</span>
          <span style={t.statVal}>{v ?? '—'}</span>
        </div>
      ))}

      {arsenal.length > 0 && (
        <>
          <div style={{ fontSize: '12px', color: '#8b949e', marginTop: '14px', marginBottom: '4px', textTransform: 'uppercase', letterSpacing: '0.5px' }}>
            Arsenal
          </div>
          <div style={t.arsenalTableWrap}>
            <table style={t.arsenalTable}>
              <thead>
                <tr>
                  {['Pitch', 'Count', 'Use%', 'Whiff%', 'PA-End K%', 'BBE', 'xwOBA', 'Source'].map(h => (
                    <th key={h} style={t.th}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {arsenal.map((p, i) => {
                  const flags = Array.isArray(p.quality_flags)
                    ? p.quality_flags
                    : (Array.isArray(p.quality_flags_json) ? p.quality_flags_json : [])
                  const pitchLabel = PITCH_NAMES[p.pitch_type] || p.pitch_name || p.pitch_type || '—'

                  return (
                    <tr key={i}>
                      <td style={t.td}>
                        <div>{pitchLabel}</div>
                        {flags.length > 0 && (
                          <div style={{ display: 'flex', gap: '4px', flexWrap: 'wrap', marginTop: '4px' }}>
                            {flags.slice(0, 3).map(flag => (
                              <span
                                key={flag}
                                style={{
                                  fontSize: '9px',
                                  color: '#d29922',
                                  background: '#2d2308',
                                  border: '1px solid #5f4700',
                                  borderRadius: '999px',
                                  padding: '1px 5px',
                                  whiteSpace: 'nowrap',
                                }}
                              >
                                {arsenalFlagLabel(flag)}
                              </span>
                            ))}
                          </div>
                        )}
                      </td>
                      <td style={t.td}>{intVal(p.pitch_count)}</td>
                      <td style={t.td}>{pct(p.usage_pct)}</td>
                      <td style={t.td}>{pct(p.whiff_pct)}</td>
                      <td style={t.td}>{pct(p.strikeout_pct)}</td>
                      <td style={t.td}>{intVal(p.batted_ball_count)}</td>
                      <td style={t.td}>{dec(p.xwoba)}</td>
                      <td style={t.td}>
                        <div>{arsenalSourceLabel(p.source)}</div>
                        {p.source_window && (
                          <div style={{ color: '#8b949e', fontSize: '10px', marginTop: '2px', maxWidth: '120px' }}>
                            {p.source_window}
                          </div>
                        )}
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        </>
      )}

      {gameLog.length > 0 && (
        <>
          <div style={{ fontSize: '12px', color: '#8b949e', marginTop: '14px', marginBottom: '4px', textTransform: 'uppercase', letterSpacing: '0.5px' }}>
            Recent Outings
          </div>
          <table style={t.logTable}>
            <thead>
              <tr>
                {['Date', 'P', 'PA', 'K', 'BB', 'HR', 'HH%'].map(h => <th key={h} style={t.th}>{h}</th>)}
              </tr>
            </thead>
            <tbody>
              {gameLog.map((g, i) => (
                <tr key={i}>
                  <td style={t.td}>{g.game_date?.slice ? g.game_date.slice(5) : String(g.game_date || '').slice(5)}</td>
                  <td style={t.td}>{g.pitch_count ?? '—'}</td>
                  <td style={t.td}>{g.plate_appearances ?? g.batters_faced ?? '—'}</td>
                  <td style={t.td}>{g.strikeouts ?? '—'}</td>
                  <td style={t.td}>{g.walks ?? '—'}</td>
                  <td style={t.td}>{g.home_runs ?? '—'}</td>
                  <td style={t.td}>{pct(g.hard_hit_pct)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}

      {pitcherId && (
        <div style={{ marginTop: '14px' }}>
          <Link to={`/pitcher/${pitcherId}/rolling`} style={{ color: '#58a6ff', fontSize: '12px', textDecoration: 'none' }}>
            View Rolling Stats →
          </Link>
        </div>
      )}
    </div>
  )
}

function SplitTable({ title, split }) {
  return (
    <div style={t.splitCard}>
      <div style={t.splitTitle}>{title}</div>
      {!split
        ? <div style={{ color: '#8b949e', fontSize: '13px' }}>No data</div>
        : [
            ['PA', split.pa],
            ['AVG', dec(split.batting_avg)],
            ['OBP', dec(split.on_base_pct)],
            ['SLG', dec(split.slugging_pct)],
            ['HR', split.home_runs],
            ['K%', pct(split.k_pct)],
            ['BB%', pct(split.bb_pct)],
          ].map(([k, v]) => (
            <div key={k} style={t.statRow}>
              <span style={t.statKey}>{k}</span>
              <span style={t.statVal}>{v ?? '—'}</span>
            </div>
          ))}
    </div>
  )
}

function RateBar({ label, value, variant = 'neutral', title }) {
  return (
    <div style={t.rateRow} title={title || tooltipFor(label)}>
      <span style={t.rateLabel}>{label}</span>
      <div style={t.rateTrack}>
        <div style={t.rateFill(value, variant)} />
      </div>
      <span style={t.rateValue}>{pct(value)}</span>
    </div>
  )
}

function MetricPill({ label, value, title }) {
  return (
    <div style={t.metricPill} title={title || tooltipFor(label)}>
      <div style={t.metricLabel}>{label}</div>
      <div style={t.metricValue}>{value ?? '—'}</div>
    </div>
  )
}

function PitchTypeWidget({ pitch }) {
  const bvt = pitch.batter_vs_type || {}
  const edge = pitch.edge_score ?? 0
  const conf = pitch.confidence ?? 0
  const source = bvt.source || null
  const edgeInfo = edgeMeta(edge)

  const pitchesSeenVal = pickMetric(bvt, ['pitches_seen', 'pa']) ?? 0
  const paEndedVal = pickMetric(bvt, ['pa_ended', 'pa']) ?? 0
  const swingsVal = pickMetric(bvt, ['swings']) ?? 0
  const whiffsVal = pickMetric(bvt, ['whiffs']) ?? 0

  const avgVal = pickMetric(bvt, ['batting_avg'])
  const xwobaVal = pickMetric(bvt, ['xwoba'])
  const xbaVal = pickMetric(bvt, ['xba'])
  const evVal = pickMetric(bvt, ['avg_exit_velocity', 'avg_ev'])
  const laVal = pickMetric(bvt, ['avg_launch_angle', 'avg_la'])

  const whiffPct = pickMetric(bvt, ['whiff_pct'])
  const kPct = pickMetric(bvt, ['k_pct'])
  const putawayPct = pickMetric(bvt, ['putaway_pct'])
  const hardHitPct = pickMetric(bvt, ['hard_hit_pct', 'hardhit_pct'])

  return (
    <div style={t.pitchWidget(edge)}>
      <div style={t.pitchWidgetTop}>
        <div>
          <div style={t.pitchTypeBig}>{pitch.pitch_type || '—'}</div>
          <div style={t.pitchNameSmall} title={tooltipFor('Usage')}>
            Usage {pct(pitch.pitcher_usage_pct)}
          </div>
        </div>
        <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-end', gap: '6px' }}>
          {source && (
            <span style={t.sourceBadge(source)}>{sourceLabel(source)}</span>
          )}
          <span style={{ fontSize: '10px', color: '#8b949e', textTransform: 'uppercase', letterSpacing: '0.5px' }} title={tooltipFor('Edge Score')}>
            {edgeInfo.label}
          </span>
          <span style={{ fontSize: '13px', fontWeight: '800', color: edgeInfo.color }} title={tooltipFor('Edge Score')}>
            {edge > 0 ? '+' : ''}{Number(edge).toFixed(2)}
          </span>
        </div>
      </div>

      <div style={t.sampleStrip}>
        {[
          { label: 'Pitches', value: intVal(pitchesSeenVal) },
          { label: 'PA Ended', value: intVal(paEndedVal) },
          { label: 'Swings', value: intVal(swingsVal) },
          { label: 'Whiffs', value: intVal(whiffsVal) },
        ].map(({ label, value }) => (
          <div key={label} style={t.sampleCell}>
            <div style={t.sampleNum}>{value}</div>
            <div style={t.sampleLabel}>{label}</div>
          </div>
        ))}
      </div>

      <div style={t.metricPillGrid}>
        <MetricPill label="AVG" value={dec(avgVal)} title="Batting average by this hitter against this pitch type. Higher favors the hitter." />
        <MetricPill label="xwOBA" value={dec(xwobaVal)} title="Expected offensive value by this hitter against this pitch type. Higher favors the hitter." />
        <MetricPill label="EV" value={evVal != null ? `${Number(evVal).toFixed(1)}` : '—'} title="Average exit velocity by this hitter against this pitch type. Higher generally favors the hitter." />
        <MetricPill label="LA" value={laVal != null ? `${Number(laVal).toFixed(1)}°` : '—'} title="Average launch angle by this hitter against this pitch type. Best interpreted by range, not simply higher." />
      </div>

      <div style={t.rateStack}>
        <RateBar label="Hitter Whiff%" value={whiffPct} variant={hitterRiskVariant(whiffPct, 0.34, 0.24)} />
        <RateBar label="Hitter K%" value={kPct} variant={hitterRiskVariant(kPct, 0.28, 0.20)} />
        <RateBar label="PutAway Risk" value={putawayPct} variant={hitterRiskVariant(putawayPct, 0.24, 0.16)} />
        <RateBar label="Hitter HardHit%" value={hardHitPct} variant={hitterDamageVariant(hardHitPct, 0.40, 0.32)} />
      </div>

      <div style={t.widgetFooter}>
        <span style={{ fontSize: '11px', color: '#8b949e', textTransform: 'uppercase', letterSpacing: '0.5px' }} title={tooltipFor('Pitcher xwOBA Allowed')}>
          Pitcher xwOBA Allowed {dec(pitch.pitcher_xwoba)}
        </span>
        <div style={t.confidenceWrap} title={tooltipFor('Confidence')}>
          <div style={{ ...t.rateTrack, flex: 1 }}>
            <div style={t.rateFill(conf, confidenceVariant(conf))} />
          </div>
          <span style={{ fontSize: '11px', fontWeight: '700', color: '#8b949e', whiteSpace: 'nowrap' }}>
            {pct(conf)} conf
          </span>
        </div>
      </div>
    </div>
  )
}

function CompetitiveBatterRow({ batter, expanded, onToggle }) {
  const matchup = batter.matchup || {}
  const matrix = matchup.pitch_type_matrix || []
  const headToHead = matchup.head_to_head || {}
  const bestEdge = matrix.reduce((best, p) => !best || (p.edge_score ?? -999) > (best.edge_score ?? -999) ? p : best, null)

  return (
    <div style={t.batterRow}>
      <div style={t.batterHeader} onClick={onToggle}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
          <span style={{ color: '#8b949e', fontSize: '12px', width: '20px' }}>{batter.batting_order}</span>
          <Link to={`/batter/${batter.batter_id}`} style={t.batterName} onClick={(e) => e.stopPropagation()}>
            {batter.batter_name}
          </Link>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
          {bestEdge && (
            <span style={t.edgeBadge(bestEdge.edge_score)}>
              {bestEdge.pitch_type}: {edgeLabel(bestEdge.edge_score)}
            </span>
          )}
          <span style={{ color: '#8b949e', fontSize: '12px' }}>{expanded ? '▼' : '▶'}</span>
        </div>
      </div>

      {expanded && (
        <div style={{ padding: '0 14px 14px' }}>
          <div style={{
            display: 'flex',
            gap: '20px',
            marginBottom: '16px',
            padding: '10px 12px',
            background: '#0a0f14',
            borderRadius: '8px',
            border: '1px solid #21262d',
            fontSize: '12px',
            color: '#8b949e',
            flexWrap: 'wrap',
          }}>
            <span>H2H PA: <strong style={{ color: '#e6edf3' }}>{headToHead.pa ?? 0}</strong></span>
            <span>H2H AVG: <strong style={{ color: '#e6edf3' }}>{headToHead.batting_avg != null ? dec(headToHead.batting_avg) : '—'}</strong></span>
            <span>H2H xwOBA: <strong style={{ color: '#e6edf3' }}>{headToHead.xwoba != null ? dec(headToHead.xwoba) : '—'}</strong></span>
            <span>Arsenal Season: <strong style={{ color: '#e6edf3' }}>{matchup.arsenal_season ?? '—'}</strong></span>
          </div>

          {matrix.length === 0 ? (
            <div style={t.noData}>No arsenal matchup data available</div>
          ) : (
            <div style={t.pitchWidgetGrid}>
              {matrix.map((p, idx) => (
                <PitchTypeWidget key={idx} pitch={p} />
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  )
}

export default function MatchupDetailPage() {
  const { game_pk } = useParams()
  const [matchup, setMatchup] = useState(null)
  const [competitive, setCompetitive] = useState(null)
  const [activeTab, setActiveTab] = useState('overview')
  const [expandedBatters, setExpandedBatters] = useState({})
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  useEffect(() => {
    setLoading(true)
    setError(null)
    Promise.all([
      fetch(`${API}/matchup/${game_pk}`).then(r => r.ok ? r.json() : r.json().then(e => Promise.reject(e.detail || r.statusText))),
      fetch(`${API}/matchup/${game_pk}/competitive`).then(r => r.ok ? r.json() : null).catch(() => null),
    ])
      .then(([detail, comp]) => {
        setMatchup(detail)
        setCompetitive(comp)
        setLoading(false)
      })
      .catch(e => {
        setError(String(e))
        setLoading(false)
      })
  }, [game_pk])

  if (loading) return <div style={t.loader}>Loading matchup…</div>
  if (error) return <div style={t.error}>{error}</div>
  if (!matchup) return null

  const home = matchup.home_team || {}
  const away = matchup.away_team || {}
  const hp = matchup.home_win_prob
  const ap = matchup.away_win_prob
  const hPct = hp != null ? Math.round(hp * 100) : 50
  const aPct = 100 - hPct

  const awayPitcherHand = away.pitcher_name?.includes('(L)') ? 'L' : 'R'
  const homePitcherHand = home.pitcher_name?.includes('(L)') ? 'L' : 'R'

  const awayLineupMatchups = competitive?.away_lineup_matchups || []
  const homeLineupMatchups = competitive?.home_lineup_matchups || []
  const awayLineupSource = competitive?.away_lineup_source
  const homeLineupSource = competitive?.home_lineup_source

  function lineupSourceBadge(source) {
    if (source === 'projected') return "Projected (yesterday's lineup)"
    if (source === 'roster') return 'Lineup TBD — showing full roster'
    return null
  }

  function toggleBatter(key) {
    setExpandedBatters(prev => ({ ...prev, [key]: !prev[key] }))
  }

  return (
    <div style={t.page}>
      <Link to="/" style={t.back}>← Back to Matchups</Link>

      <div style={t.header}>
        <div style={t.headerTop}>
          <div style={t.teamsRow}>
            <div style={t.teamBlock}>
              <div style={t.teamName}>{away.name || 'Away'}</div>
              <div style={t.teamRecord}>{away.record || ''}</div>
            </div>
            <div style={t.at}>@</div>
            <div style={t.teamBlock}>
              <div style={t.teamName}>{home.name || 'Home'}</div>
              <div style={t.teamRecord}>{home.record || ''}</div>
            </div>
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: '6px', alignItems: 'flex-end' }}>
            {matchup.status && <span style={t.statusBadge}>{matchup.status}</span>}
            {matchup.park_factor && <span style={t.parkBadge}>{parkLabel(matchup.park_factor)}</span>}
          </div>
        </div>
        <div style={{ marginTop: '8px', display: 'flex', gap: '16px', flexWrap: 'wrap' }}>
          {matchup.venue && <span style={t.metaText}>📍 {matchup.venue}</span>}
          {matchup.game_date && <span style={t.metaText}>🕐 {formatTime(matchup.game_date)}</span>}
          {weatherLabel(matchup.weather) && <span style={t.metaText}>☁️ {weatherLabel(matchup.weather)}</span>}
        </div>
      </div>

      {(hp != null || ap != null) && (
        <div style={t.probSection}>
          <div style={t.sectionTitle}>Win Probability</div>
          <div style={t.probRow}>
            <div>
              <div style={{ fontSize: '13px', color: '#8b949e' }}>{away.name}</div>
              <div style={{ ...t.probPct, color: probColor(ap) }}>{ap != null ? `${aPct}%` : '—'}</div>
            </div>
            <div style={{ textAlign: 'right' }}>
              <div style={{ fontSize: '13px', color: '#8b949e' }}>{home.name}</div>
              <div style={{ ...t.probPct, color: probColor(hp) }}>{hp != null ? `${hPct}%` : '—'}</div>
            </div>
          </div>
          <div style={t.probBar}>
            <div style={{ width: `${aPct}%`, background: '#58a6ff', transition: 'width 0.5s' }} />
            <div style={{ width: `${hPct}%`, background: '#3fb950', transition: 'width 0.5s' }} />
          </div>
        </div>
      )}

      <div style={t.compTabs}>
        <button style={t.compTab(activeTab === 'overview')} onClick={() => setActiveTab('overview')}>Overview</button>
        <button style={t.compTab(activeTab === 'competitive')} onClick={() => setActiveTab('competitive')}>Batter vs Arsenal</button>
      </div>

      {activeTab === 'overview' && (
        <>
          <div style={t.section}>
            <div style={t.sectionTitle}>Starting Pitchers</div>
            <div style={t.pitcherGrid}>
              <PitcherCard side="Away" pitcherName={away.pitcher_name} pitcherId={away.pitcher_id} detail={away} />
              <PitcherCard side="Home" pitcherName={home.pitcher_name} pitcherId={home.pitcher_id} detail={home} />
            </div>
          </div>

          <div style={t.section}>
            <div style={t.sectionTitle}>Starting Lineups</div>
            <div style={t.lineupGrid}>
              <div>
                <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '10px' }}>
                  <div style={{ fontSize: '13px', color: '#58a6ff', fontWeight: '600' }}>{away.name}</div>
                  {away.lineup_source && away.lineup_source !== 'official' && (
                    <span style={{ fontSize: '11px', color: '#8b949e', background: '#21262d', padding: '2px 7px', borderRadius: '3px' }}>
                      {lineupSourceBadge(away.lineup_source)}
                    </span>
                  )}
                </div>
                {away.lineup?.length > 0 ? away.lineup.map((p, i) => (
                  <div key={i} style={t.lineupItem}>
                    <span style={t.orderNum}>{i + 1}</span>
                    <Link to={`/batter/${p.id}`} style={{ color: '#e6edf3', textDecoration: 'none', flex: 1 }}>{p.name}</Link>
                    {p.position && <span style={{ color: '#8b949e', fontSize: '12px' }}>{p.position}</span>}
                  </div>
                )) : (
                  <div style={{ color: '#8b949e', fontSize: '13px', fontStyle: 'italic', paddingTop: '6px' }}>Lineup not yet posted</div>
                )}
              </div>
              <div>
                <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '10px' }}>
                  <div style={{ fontSize: '13px', color: '#3fb950', fontWeight: '600' }}>{home.name}</div>
                  {home.lineup_source && home.lineup_source !== 'official' && (
                    <span style={{ fontSize: '11px', color: '#8b949e', background: '#21262d', padding: '2px 7px', borderRadius: '3px' }}>
                      {lineupSourceBadge(home.lineup_source)}
                    </span>
                  )}
                </div>
                {home.lineup?.length > 0 ? home.lineup.map((p, i) => (
                  <div key={i} style={t.lineupItem}>
                    <span style={t.orderNum}>{i + 1}</span>
                    <Link to={`/batter/${p.id}`} style={{ color: '#e6edf3', textDecoration: 'none', flex: 1 }}>{p.name}</Link>
                    {p.position && <span style={{ color: '#8b949e', fontSize: '12px' }}>{p.position}</span>}
                  </div>
                )) : (
                  <div style={{ color: '#8b949e', fontSize: '13px', fontStyle: 'italic', paddingTop: '6px' }}>Lineup not yet posted</div>
                )}
              </div>
            </div>
          </div>

          <div style={t.section}>
            <div style={t.sectionTitle}>Team Hitting Splits</div>
            <div style={{ marginBottom: '16px' }}>
              <div style={{ fontSize: '13px', color: '#58a6ff', fontWeight: '600', marginBottom: '10px' }}>{away.name} — vs {homePitcherHand}HP</div>
              <div style={t.splitsGrid}>
                <SplitTable title="vs LHP" split={away.splits?.vsL} />
                <SplitTable title="vs RHP" split={away.splits?.vsR} />
              </div>
            </div>
            <div>
              <div style={{ fontSize: '13px', color: '#3fb950', fontWeight: '600', marginBottom: '10px' }}>{home.name} — vs {awayPitcherHand}HP</div>
              <div style={t.splitsGrid}>
                <SplitTable title="vs LHP" split={home.splits?.vsL} />
                <SplitTable title="vs RHP" split={home.splits?.vsR} />
              </div>
            </div>
          </div>
        </>
      )}

      {activeTab === 'competitive' && (
        <div style={t.section}>
          <div style={t.sectionTitle}>Batter vs Pitcher Arsenal Matchups</div>

          <div style={{ marginBottom: '24px' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '10px', marginBottom: '12px' }}>
              <div style={{ fontSize: '14px', color: '#58a6ff', fontWeight: '600' }}>{away.name} hitters vs {home.pitcher_name || 'Home Starter'}</div>
              {awayLineupSource && awayLineupSource !== 'official' && (
                <span style={{ fontSize: '11px', color: '#8b949e', background: '#21262d', padding: '2px 7px', borderRadius: '3px' }}>
                  {lineupSourceBadge(awayLineupSource)}
                </span>
              )}
            </div>
            {awayLineupMatchups.length === 0 ? (
              <div style={t.noData}>No data available</div>
            ) : awayLineupMatchups.map((b) => (
              <CompetitiveBatterRow
                key={`away-${b.batter_id}`}
                batter={b}
                expanded={!!expandedBatters[`away-${b.batter_id}`]}
                onToggle={() => toggleBatter(`away-${b.batter_id}`)}
              />
            ))}
          </div>

          <div>
            <div style={{ display: 'flex', alignItems: 'center', gap: '10px', marginBottom: '12px' }}>
              <div style={{ fontSize: '14px', color: '#3fb950', fontWeight: '600' }}>{home.name} hitters vs {away.pitcher_name || 'Away Starter'}</div>
              {homeLineupSource && homeLineupSource !== 'official' && (
                <span style={{ fontSize: '11px', color: '#8b949e', background: '#21262d', padding: '2px 7px', borderRadius: '3px' }}>
                  {lineupSourceBadge(homeLineupSource)}
                </span>
              )}
            </div>
            {homeLineupMatchups.length === 0 ? (
              <div style={t.noData}>No data available</div>
            ) : homeLineupMatchups.map((b) => (
              <CompetitiveBatterRow
                key={`home-${b.batter_id}`}
                batter={b}
                expanded={!!expandedBatters[`home-${b.batter_id}`]}
                onToggle={() => toggleBatter(`home-${b.batter_id}`)}
              />
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

import React, { useState, useEffect } from 'react'
import { fmtPct, fmtDec } from '../utils/formatters'
import { useParams, Link } from 'react-router-dom'

const API = import.meta.env.VITE_API_BASE_URL || ''

const PITCH_NAMES = {
  FF: '4-Seam', SI: 'Sinker', FC: 'Cutter', FS: 'Splitter',
  CH: 'Changeup', CU: 'Curveball', SL: 'Slider', ST: 'Sweeper',
  KC: 'Knuckle-Curve', SV: 'Slurve', KN: 'Knuckleball', PO: 'Pitchout', UN: 'Unknown',
}

const t = {
  page: {},
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
  section: { background: '#161b22', border: '1px solid #30363d', borderRadius: '10px', padding: '20px 24px', marginBottom: '20px' },
  sectionTitle: { fontSize: '15px', fontWeight: '600', color: '#e6edf3', marginBottom: '16px', borderBottom: '1px solid #21262d', paddingBottom: '8px' },
  pitcherGrid: { display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '20px' },
  pitcherCard: { background: '#0d1117', border: '1px solid #21262d', borderRadius: '8px', padding: '16px' },
  pitcherName: { fontSize: '16px', fontWeight: '700', color: '#e6edf3', marginBottom: '4px' },
  dataSource: { fontSize: '11px', color: '#8b949e', marginBottom: '12px' },
  statRow: { display: 'flex', justifyContent: 'space-between', padding: '5px 0', borderBottom: '1px solid #161b22', fontSize: '13px' },
  statKey: { color: '#8b949e' },
  statVal: { color: '#e6edf3', fontWeight: '500' },
  arsenalTable: { width: '100%', borderCollapse: 'collapse', fontSize: '12px', marginTop: '12px' },
  th: { padding: '6px 8px', textAlign: 'left', color: '#8b949e', fontSize: '11px', textTransform: 'uppercase', borderBottom: '1px solid #21262d' },
  td: { padding: '6px 8px', borderBottom: '1px solid #0d1117', color: '#e6edf3' },
  splitsGrid: { display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '20px' },
  splitCard: { background: '#0d1117', border: '1px solid #21262d', borderRadius: '8px', padding: '16px' },
  splitTitle: { fontSize: '14px', fontWeight: '600', color: '#58a6ff', marginBottom: '10px' },
  logTable: { width: '100%', borderCollapse: 'collapse', fontSize: '13px' },
  lineupGrid: { display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '20px' },
  lineupItem: { display: 'flex', gap: '10px', padding: '5px 0', borderBottom: '1px solid #0d1117', fontSize: '13px', color: '#e6edf3' },
  orderNum: { color: '#8b949e', width: '20px', flexShrink: 0 },
  loader: { color: '#8b949e', padding: '48px', textAlign: 'center' },
  error: { color: '#f85149', padding: '24px', background: '#1f1116', borderRadius: '8px' },
  compTabs: { display: 'flex', gap: '0', marginBottom: '16px', background: '#0d1117', border: '1px solid #21262d', borderRadius: '6px', overflow: 'hidden', width: 'fit-content', flexWrap: 'wrap' },
  compTab: (active) => ({ padding: '8px 16px', fontSize: '13px', fontWeight: '600', cursor: 'pointer', background: active ? '#58a6ff' : 'transparent', color: active ? '#0d1117' : '#8b949e', border: 'none', outline: 'none' }),
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
  insightGrid: { display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '12px', marginBottom: '16px' },
  insightCard: { background: '#0d1117', border: '1px solid #21262d', borderRadius: '8px', padding: '12px 14px' },
  insightLabel: { fontSize: '11px', color: '#8b949e', textTransform: 'uppercase', letterSpacing: '0.5px', marginBottom: '6px' },
  insightValue: { fontSize: '14px', color: '#e6edf3', fontWeight: '600' },
}

const pct = (v, d = 1) => fmtPct(v, d)
const dec = (v, d = 3) => fmtDec(v, d)
const mph = v => v != null ? `${Number(v).toFixed(1)}` : '—'

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
  return (score > 0 ? '+' : '') + score.toFixed(2)
}

function PitcherCard({ side, pitcherName, pitcherId, detail }) {
  const agg = detail?.aggregate || {}
  const arsenal = detail?.arsenal || []
  const gameLog = detail?.game_log || []

  return (
    <div style={t.pitcherCard}>
      <div style={{ fontSize: '12px', color: '#8b949e', marginBottom: '4px', textTransform: 'uppercase', letterSpacing: '0.5px' }}>{side}</div>
      <div style={t.pitcherName}>
        {pitcherId
          ? <Link to={`/pitcher/${pitcherId}`} style={{ color: '#e6edf3', textDecoration: 'none' }}>{pitcherName || `ID ${pitcherId}`}</Link>
          : <span style={{ color: '#8b949e' }}>TBD</span>}
      </div>
      <div style={t.dataSource}>{agg.data_source || 'No data'}</div>

      {[
        ['K%', pct(agg.k_pct)],
        ['BB%', pct(agg.bb_pct)],
        ['xwOBA', dec(agg.xwoba)],
        ['Hard Hit%', pct(agg.hard_hit_pct)],
        ['Velocity', mph(agg.avg_velocity) + (agg.avg_velocity ? ' mph' : '')],
        ['Spin Rate', agg.avg_spin_rate ? `${Math.round(agg.avg_spin_rate)} rpm` : '—'],
        ['Horiz Break', agg.avg_horiz_break != null ? `${Number(agg.avg_horiz_break).toFixed(2)}"` : '—'],
        ['Vert Break', agg.avg_vert_break != null ? `${Number(agg.avg_vert_break).toFixed(2)}"` : '—'],
      ].map(([k, v]) => (
        <div key={k} style={t.statRow}>
          <span style={t.statKey}>{displayKey(k)}</span>
          <span style={t.statVal}>{v}</span>
        </div>
      ))}

      {arsenal.length > 0 && (
        <>
          <div style={{ fontSize: '12px', color: '#8b949e', marginTop: '14px', marginBottom: '4px', textTransform: 'uppercase', letterSpacing: '0.5px' }}>Arsenal</div>
          <table style={t.arsenalTable}>
            <thead>
              <tr>
                {['Pitch', 'Use%', 'Whiff%', 'K%', 'xwOBA'].map(h => <th key={h} style={t.th}>{h}</th>)}
              </tr>
            </thead>
            <tbody>
              {arsenal.map((p, i) => (
                <tr key={i}>
                  <td style={t.td}>{PITCH_NAMES[p.pitch_type] || p.pitch_type}</td>
                  <td style={t.td}>{pct(p.usage_pct)}</td>
                  <td style={t.td}>{pct(p.whiff_pct)}</td>
                  <td style={t.td}>{pct(p.strikeout_pct)}</td>
                  <td style={t.td}>{dec(p.xwoba)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}

      {gameLog.length > 0 && (
        <>
          <div style={{ fontSize: '12px', color: '#8b949e', marginTop: '14px', marginBottom: '4px', textTransform: 'uppercase', letterSpacing: '0.5px' }}>Recent Outings</div>
          <table style={t.logTable}>
            <thead>
              <tr>
                {['Date', 'P', 'PA', 'K', 'BB', 'HR', 'HH%'].map(h => <th key={h} style={t.th}>{h}</th>)}
              </tr>
            </thead>
            <tbody>
              {gameLog.map((g, i) => (
                <tr key={i}>
                  <td style={t.td}>{g.game_date?.slice(5)}</td>
                  <td style={t.td}>{g.pitch_count}</td>
                  <td style={t.td}>{g.plate_appearances}</td>
                  <td style={t.td}>{g.strikeouts}</td>
                  <td style={t.td}>{g.walks}</td>
                  <td style={t.td}>{g.home_runs}</td>
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
              <span style={t.statKey}>{displayKey(k)}</span>
              <span style={t.statVal}>{v ?? '—'}</span>
            </div>
          ))}
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
          {bestEdge && <span style={t.edgeBadge(bestEdge.edge_score)}>{bestEdge.pitch_type}: {edgeLabel(bestEdge.edge_score)}</span>}
          <span style={{ color: '#8b949e', fontSize: '12px' }}>{expanded ? '▼' : '▶'}</span>
        </div>
      </div>

      {expanded && (
        <div style={{ padding: '0 14px 14px' }}>
          <div style={{ display: 'flex', gap: '24px', marginBottom: '12px', fontSize: '12px', color: '#8b949e' }}>
            <span>H2H PA: <span style={{ color: '#e6edf3' }}>{headToHead.pa ?? 0}</span></span>
            <span>H2H AVG: <span style={{ color: '#e6edf3' }}>{headToHead.batting_avg != null ? dec(headToHead.batting_avg) : '—'}</span></span>
            <span>Arsenal Season: <span style={{ color: '#e6edf3' }}>{matchup.arsenal_season ?? '—'}</span></span>
          </div>

          {matrix.length === 0 ? (
            <div style={t.noData}>No arsenal matchup data available</div>
          ) : (
            <table style={t.matchupTable}>
              <thead>
                <tr>
                  <th style={t.mth}>Pitch</th>
                  <th style={{ ...t.mth, ...t.mtdR }}>Use%</th>
                  <th style={{ ...t.mth, ...t.mtdR }}>Pitch xwOBA</th>
                  <th style={{ ...t.mth, ...t.mtdR }}>Batter PA</th>
                  <th style={{ ...t.mth, ...t.mtdR }}>Batter AVG</th>
                  <th style={{ ...t.mth, ...t.mtdR }}>EV</th>
                  <th style={{ ...t.mth, ...t.mtdR }}>HH%</th>
                  <th style={{ ...t.mth, ...t.mtdR }}>Edge</th>
                  <th style={{ ...t.mth, ...t.mtdR }}>Conf</th>
                </tr>
              </thead>
              <tbody>
                {matrix.map((p, idx) => (
                  <tr key={idx}>
                    <td style={t.mtd}>{p.pitch_type}</td>
                    <td style={{ ...t.mtd, ...t.mtdR }}>{pct(p.pitcher_usage_pct)}</td>
                    <td style={{ ...t.mtd, ...t.mtdR }}>{dec(p.pitcher_xwoba)}</td>
                    <td style={{ ...t.mtd, ...t.mtdR }}>{p.batter_vs_type?.pa ?? 0}</td>
                    <td style={{ ...t.mtd, ...t.mtdR }}>{p.batter_vs_type?.batting_avg != null ? dec(p.batter_vs_type.batting_avg) : '—'}</td>
                    <td style={{ ...t.mtd, ...t.mtdR }}>{p.batter_vs_type?.avg_exit_velocity != null ? mph(p.batter_vs_type.avg_exit_velocity) : '—'}</td>
                    <td style={{ ...t.mtd, ...t.mtdR }}>{p.batter_vs_type?.hard_hit_pct != null ? pct(p.batter_vs_type.hard_hit_pct) : '—'}</td>
                    <td style={{ ...t.mtd, ...t.mtdR, color: (p.edge_score ?? 0) > 0 ? '#3fb950' : (p.edge_score ?? 0) < 0 ? '#f85149' : '#8b949e', fontWeight: '600' }}>{edgeLabel(p.edge_score)}</td>
                    <td style={{ ...t.mtd, ...t.mtdR }}>{pct(p.confidence)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}
    </div>
  )
}



function buildPitcherInsights(profile) {
  const kRate = profile?.bat_missing?.k_rate
  const bbRate = profile?.command_control?.bb_rate
  const hhAllowed = profile?.contact_management?.hard_hit_rate_allowed
  return [
    {
      label: 'Swing & Miss',
      value: kRate != null
        ? (kRate >= 0.27 ? 'Strong strikeout profile' : kRate >= 0.22 ? 'Average strikeout profile' : 'Limited strikeout profile')
        : 'No strikeout insight yet',
    },
    {
      label: 'Command',
      value: bbRate != null
        ? (bbRate <= 0.07 ? 'Strong command baseline' : bbRate <= 0.10 ? 'Manageable walk risk' : 'Elevated walk risk')
        : 'No command insight yet',
    },
    {
      label: 'Contact Quality',
      value: hhAllowed != null
        ? (hhAllowed <= 0.35 ? 'Suppressing hard contact' : hhAllowed <= 0.40 ? 'Neutral contact quality' : 'Hard contact risk elevated')
        : 'No contact-quality insight yet',
    },
  ]
}

function buildBatterInsights(profile) {
  const iso = profile?.power?.iso
  const kRate = profile?.contact_skill?.k_rate
  const bbRate = profile?.plate_discipline?.bb_rate
  return [
    {
      label: 'Power',
      value: iso != null
        ? (iso >= 0.20 ? 'Above-average game power' : iso >= 0.15 ? 'Playable power baseline' : 'Limited over-the-fence power')
        : 'No power insight yet',
    },
    {
      label: 'Contact Risk',
      value: kRate != null
        ? (kRate <= 0.20 ? 'Low strikeout risk' : kRate <= 0.27 ? 'Moderate strikeout risk' : 'Elevated strikeout risk')
        : 'No contact-risk insight yet',
    },
    {
      label: 'Discipline',
      value: bbRate != null
        ? (bbRate >= 0.10 ? 'Plate discipline advantage' : bbRate >= 0.07 ? 'Average plate discipline' : 'Aggressive approach profile')
        : 'No discipline insight yet',
    },
  ]
}

function buildEnvironmentInsights(profile) {
  const runBoost = profile?.run_environment?.run_scoring_index
  const wind = profile?.weather?.wind_speed_mph
  const readiness = profile?.status?.readiness || profile?.metadata?.readiness
  return [
    {
      label: 'Run Environment',
      value: runBoost != null
        ? (runBoost >= 1.05 ? 'Run environment favors offense' : runBoost <= 0.95 ? 'Run environment suppresses scoring' : 'Run environment looks neutral')
        : 'No run-environment signal yet',
    },
    {
      label: 'Weather',
      value: wind != null
        ? (wind >= 12 ? 'Weather could meaningfully affect carry' : wind >= 7 ? 'Weather has mild impact potential' : 'Weather impact looks limited')
        : 'No weather insight yet',
    },
    {
      label: 'Readiness',
      value: readiness ? String(readiness).replace(/_/g, ' ') : 'Environment profile still maturing',
    },
  ]
}

function buildMatchupInsights(analysis) {
  const confidence = analysis?.confidence
  const best = analysis?.biggestEdge?.pitch_type
  const weakness = analysis?.biggestWeakness?.pitch_type
  return [
    {
      label: 'Best Edge',
      value: best ? `Best current edge vs ${best}` : 'No best-edge signal yet',
    },
    {
      label: 'Biggest Risk',
      value: weakness ? `Most vulnerable vs ${weakness}` : 'No weakness signal yet',
    },
    {
      label: 'Confidence',
      value: confidence != null
        ? (confidence >= 0.7 ? 'High-confidence read' : confidence >= 0.4 ? 'Moderate-confidence read' : 'Low-confidence read')
        : 'No confidence signal yet',
    },
  ]
}

function InsightCards({ items }) {
  if (!items || items.length === 0) return null
  return (
    <div style={t.insightGrid}>
      {items.map((item, idx) => (
        <div key={idx} style={t.insightCard}>
          <div style={t.insightLabel}>{item.label}</div>
          <div style={t.insightValue}>{item.value}</div>
        </div>
      ))}
    </div>
  )
<<<<<<< HEAD
}

=======
  }
>>>>>>> upstream/sandbox/contributor-analysis
function displayKey(key) {
  if (!key) return '—'
  const map = {
    k_rate: 'K Rate',
    bb_rate: 'BB Rate',
    whiff_rate: 'Whiff Rate',
    contact_rate: 'Contact Rate',
    chase_rate: 'Chase Rate',
    swing_rate: 'Swing Rate',
    iso: 'ISO',
    barrel_rate: 'Barrel Rate',
    hard_hit_rate: 'Hard Hit Rate',
    avg_exit_velocity: 'Avg Exit Velo',
    avg_launch_angle: 'Avg Launch Angle',
    vs_lhp_woba: 'vs LHP wOBA',
    vs_rhp_woba: 'vs RHP wOBA',
    vs_lhp_iso: 'vs LHP ISO',
    vs_rhp_iso: 'vs RHP ISO',
    source_type: 'Source Type',
    source_fields_used: 'Source Fields',
    data_confidence: 'Data Confidence',
    generated_from: 'Generated From',
    profile_granularity: 'Granularity',
    is_projected_lineup_derived: 'Lineup Derived',
    lineup_source: 'Lineup Source',
    opposing_pitcher_hand: 'Opposing Pitcher Hand',
    player_count_used: 'Players Used',
    sample_window: 'Sample Window',
    sample_family: 'Sample Family',
    sample_description: 'Sample Description',
    sample_days: 'Sample Days',
    sample_size: 'Sample Size',
    sample_blend_policy: 'Blend Policy',
    stabilizer_window: 'Stabilizer Window',
    pitch_mix: 'Pitch Mix',
    avg_velocity: 'Avg Velocity',
    avg_spin_rate: 'Avg Spin Rate',
    csw_rate: 'CSW Rate',
    zone_rate: 'Zone Rate',
    first_pitch_strike_rate: 'First Pitch Strike Rate',
    hard_hit_rate_allowed: 'Hard Hit Allowed',
    barrel_rate_allowed: 'Barrel Allowed',
    avg_exit_velocity_allowed: 'Avg EV Allowed',
    avg_launch_angle_allowed: 'Avg LA Allowed',
    vs_lhb_woba_allowed: 'vs LHB wOBA Allowed',
    vs_rhb_woba_allowed: 'vs RHB wOBA Allowed',
    vs_lhb_k_rate: 'vs LHB K Rate',
    vs_rhb_k_rate: 'vs RHB K Rate',
    vs_lhb_bb_rate: 'vs LHB BB Rate',
    vs_rhb_bb_rate: 'vs RHB BB Rate',
    readiness: 'Readiness',
    is_stub: 'Stub',
    missing_inputs: 'Missing Inputs',
    status: 'Status',
    note: 'Note',
  }
  return map[key] || key.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase())
}

function confidenceColor(v) {
  if (v == null) return '#8b949e'
  if (v >= 0.7) return '#3fb950'
  if (v >= 0.4) return '#d29922'
  return '#f85149'
}

function metricValue(v) {
  if (v == null) return '—'
  if (typeof v === 'number') {
    if (Math.abs(v) <= 1) return dec(v)
    return Number(v).toFixed(1)
  }
  return String(v)
}

function ProfileSectionCard({ title, data }) {
  const entries = Object.entries(data || {})
  return (
    <div style={t.splitCard}>
      <div style={t.splitTitle}>{title}</div>
      {entries.length === 0 ? (
        <div style={{ color: '#8b949e', fontSize: '13px' }}>No data</div>
      ) : (
        entries.map(([k, v]) => (
          <div key={k} style={t.statRow}>
            <span style={t.statKey}>{displayKey(k)}</span>
            <span style={t.statVal}>{metricValue(v)}</span>
          </div>
        ))
      )}
    </div>
  )
}

function ProfileMetadataCard({ title, metadata }) {
  return (
    <div style={t.splitCard}>
      <div style={t.splitTitle}>{title}</div>
      {!metadata ? (
        <div style={{ color: '#8b949e', fontSize: '13px' }}>No metadata</div>
      ) : (
        Object.entries(metadata).map(([k, v]) => (
          <div key={k} style={t.statRow}>
            <span style={t.statKey}>{displayKey(k)}</span>
            <span style={t.statVal}>{Array.isArray(v) ? v.join(', ') : metricValue(v)}</span>
          </div>
        ))
      )}
    </div>
  )
}

function PitcherProfilePanel({ sideLabel, teamName, profile }) {
  if (!profile) return <div style={t.noData}>No pitcher profile available for this matchup yet.</div>
  return (
    <div style={t.pitcherCard}>
      <div style={{ fontSize: '12px', color: '#8b949e', marginBottom: '4px', textTransform: 'uppercase', letterSpacing: '0.5px' }}>{sideLabel}</div>
      <div style={t.pitcherName}>{teamName}</div>
      <div style={t.dataSource}>{profile.metadata?.generated_from || 'No source info'}</div>
      <InsightCards items={buildPitcherInsights(profile)} />
      <div style={t.splitsGrid}>
        <ProfileMetadataCard title="Metadata" metadata={profile.metadata} />
        <ProfileSectionCard title="Arsenal" data={profile.arsenal} />
        <ProfileSectionCard title="Bat Missing" data={profile.bat_missing} />
        <ProfileSectionCard title="Command / Control" data={profile.command_control} />
        <ProfileSectionCard title="Contact Management" data={profile.contact_management} />
        <ProfileSectionCard title="Platoon Profile" data={profile.platoon_profile} />
      </div>
    </div>
  )
}

function BatterProfilePanel({ sideLabel, teamName, profile }) {
  if (!profile) return <div style={t.noData}>No projected lineup offense profile available yet.</div>
  return (
    <div style={t.pitcherCard}>
      <div style={{ fontSize: '12px', color: '#8b949e', marginBottom: '4px', textTransform: 'uppercase', letterSpacing: '0.5px' }}>{sideLabel}</div>
      <div style={t.pitcherName}>{teamName}</div>
      <div style={t.dataSource}>{profile.metadata?.generated_from || 'No source info'}</div>
      <InsightCards items={buildBatterInsights(profile)} />
      <div style={t.splitsGrid}>
        <ProfileMetadataCard title="Metadata" metadata={profile.metadata} />
        <ProfileSectionCard title="Contact Skill" data={profile.contact_skill} />
        <ProfileSectionCard title="Plate Discipline" data={profile.plate_discipline} />
        <ProfileSectionCard title="Power" data={profile.power} />
        <ProfileSectionCard title="Batted Ball Quality" data={profile.batted_ball_quality} />
        <ProfileSectionCard title="Platoon Profile" data={profile.platoon_profile} />
      </div>
    </div>
  )
}

function EnvironmentPanel({ profile }) {
  if (!profile) return <div style={t.noData}>No environment profile available for this game yet.</div>
  return (
    <div style={t.section}>
      <div style={t.sectionTitle}>Environment Profile</div>
      <InsightCards items={buildEnvironmentInsights(profile)} />
      <div style={t.splitsGrid}>
        <ProfileMetadataCard title="Metadata" metadata={profile.metadata} />
        <ProfileSectionCard title="Weather" data={profile.weather} />
        <ProfileSectionCard title="Park Factors" data={profile.park_factors} />
        <ProfileSectionCard title="Game Context" data={profile.game_context} />
        <ProfileSectionCard title="Run Environment" data={profile.run_environment} />
        <ProfileSectionCard title="Risk Flags" data={profile.risk_flags} />
        <ProfileSectionCard title="Status" data={profile.status} />
      </div>
    </div>
  )
}

function MatchupAnalysisPanel({ sideLabel, teamName, analysis }) {
  if (!analysis) return <div style={t.noData}>No matchup analysis is available for this side yet.</div>
  const pitchRows = analysis.pitchTypeMatchups || []
  return (
    <div style={t.pitcherCard}>
      <div style={{ fontSize: '12px', color: '#8b949e', marginBottom: '4px', textTransform: 'uppercase', letterSpacing: '0.5px' }}>{sideLabel}</div>
      <div style={t.pitcherName}>{teamName}</div>
      <div style={t.dataSource}>{analysis.metadata?.generated_from || 'No source info'}</div>
      <InsightCards items={buildMatchupInsights(analysis)} />

      <div style={{ display: 'flex', gap: '16px', flexWrap: 'wrap', marginBottom: '14px', fontSize: '12px' }}>
        <span style={{ color: '#8b949e' }}>Confidence: <span style={{ color: confidenceColor(analysis.confidence), fontWeight: '700' }}>{metricValue(analysis.confidence)}</span></span>
        <span style={{ color: '#8b949e' }}>Biggest Edge: <span style={{ color: '#e6edf3' }}>{analysis.biggestEdge?.pitch_type || '—'}</span></span>
        <span style={{ color: '#8b949e' }}>Biggest Weakness: <span style={{ color: '#e6edf3' }}>{analysis.biggestWeakness?.pitch_type || '—'}</span></span>
      </div>

      <div style={t.splitsGrid}>
        <ProfileMetadataCard title="Metadata" metadata={analysis.metadata} />
        <ProfileSectionCard title="Summary" data={analysis.summary} />
      </div>

      <div style={{ marginTop: '16px' }}>
        <div style={{ fontSize: '12px', color: '#8b949e', marginBottom: '6px', textTransform: 'uppercase', letterSpacing: '0.5px' }}>Pitch Type Matchups</div>
        {pitchRows.length === 0 ? (
          <div style={t.noData}>No pitch-type matchup rows are available yet.</div>
        ) : (
          <table style={t.matchupTable}>
            <thead>
              <tr>
                <th style={t.mth}>Pitch</th>
                <th style={{ ...t.mth, ...t.mtdR }}>Use%</th>
                <th style={{ ...t.mth, ...t.mtdR }}>xwOBA</th>
                <th style={{ ...t.mth, ...t.mtdR }}>HH%</th>
                <th style={{ ...t.mth, ...t.mtdR }}>Edge</th>
                <th style={{ ...t.mth, ...t.mtdR }}>Conf</th>
              </tr>
            </thead>
            <tbody>
              {pitchRows.map((p, idx) => (
                <tr key={idx}>
                  <td style={t.mtd}>{p.pitch_type || p.raw_pitch_type || '—'}</td>
                  <td style={{ ...t.mtd, ...t.mtdR }}>{pct(p.pitcher_usage_pct)}</td>
                  <td style={{ ...t.mtd, ...t.mtdR }}>{dec(p.pitcher_xwoba)}</td>
                  <td style={{ ...t.mtd, ...t.mtdR }}>{pct(p.pitcher_hard_hit_pct)}</td>
                  <td style={{ ...t.mtd, ...t.mtdR }}>{edgeLabel(p.edge_score)}</td>
                  <td style={{ ...t.mtd, ...t.mtdR }}>{pct(p.confidence)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
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
    if (source === 'projected') return 'Projected (yesterday\'s lineup)'
    if (source === 'roster') return 'Lineup TBD — showing full roster'
    return null
  }

  function toggleBatter(key) {
    setExpandedBatters(prev => ({ ...prev, [key]: !prev[key] }))
  }

  return (
    <div>
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
        <button style={t.compTab(activeTab === 'pitcher')} onClick={() => setActiveTab('pitcher')}>Pitcher</button>
        <button style={t.compTab(activeTab === 'batter')} onClick={() => setActiveTab('batter')}>Batter</button>
        <button style={t.compTab(activeTab === 'environment')} onClick={() => setActiveTab('environment')}>Environment</button>
        <button style={t.compTab(activeTab === 'analysis')} onClick={() => setActiveTab('analysis')}>Matchup Analysis</button>
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


      {activeTab === 'pitcher' && (
        <div style={t.section}>
          <div style={t.sectionTitle}>Pitcher Profiles</div>
          <div style={t.pitcherGrid}>
            <PitcherProfilePanel sideLabel="Away" teamName={away.name} profile={matchup.awayPitcherProfile} />
            <PitcherProfilePanel sideLabel="Home" teamName={home.name} profile={matchup.homePitcherProfile} />
          </div>
        </div>
      )}

      {activeTab === 'batter' && (
        <div style={t.section}>
          <div style={t.sectionTitle}>Projected Lineup Offense Profiles</div>
          <div style={t.pitcherGrid}>
            <BatterProfilePanel sideLabel="Away" teamName={away.name} profile={matchup.awayProjectedLineupOffenseProfile} />
            <BatterProfilePanel sideLabel="Home" teamName={home.name} profile={matchup.homeProjectedLineupOffenseProfile} />
          </div>
        </div>
      )}

      {activeTab === 'environment' && (
        <EnvironmentPanel profile={matchup.environmentProfile} />
      )}

      {activeTab === 'analysis' && (
        <div style={t.section}>
          <div style={t.sectionTitle}>Matchup Analysis</div>
          <div style={t.pitcherGrid}>
            <MatchupAnalysisPanel sideLabel="Away Offense" teamName={away.name} analysis={matchup.awayMatchupAnalysis} />
            <MatchupAnalysisPanel sideLabel="Home Offense" teamName={home.name} analysis={matchup.homeMatchupAnalysis} />
          </div>
        </div>
      )}

      {activeTab === 'competitive' && (
        <div style={t.section}>
          <div style={t.sectionTitle}>Batter vs Pitcher Arsenal Matchups</div>

          <div style={{ marginBottom: '24px' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '10px', marginBottom: '12px' }}>
              <div style={{ fontSize: '14px', color: '#58a6ff', fontWeight: '600' }}>{away.name} hitters vs {home.pitcher_name || 'Home Starter'}</div>
              {awayLineupSource && awayLineupSource !== 'official' && <span style={{ fontSize: '11px', color: '#8b949e', background: '#21262d', padding: '2px 7px', borderRadius: '3px' }}>{lineupSourceBadge(awayLineupSource)}</span>}
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
              {homeLineupSource && homeLineupSource !== 'official' && <span style={{ fontSize: '11px', color: '#8b949e', background: '#21262d', padding: '2px 7px', borderRadius: '3px' }}>{lineupSourceBadge(homeLineupSource)}</span>}
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

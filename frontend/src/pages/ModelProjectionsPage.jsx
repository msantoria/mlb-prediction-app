import React, { useEffect, useMemo, useState } from 'react'
import { API_BASE } from '../lib/api'
import {
  buildCanonicalDiagnosticsViewModel,
} from '../lib/canonicalDiagnosticsViewModel.mjs'
import {
  buildCanonicalProjectionsViewModel,
} from '../lib/canonicalProjectionsViewModel.mjs'

const API = API_BASE

const s = {
  page: { color: '#e6edf3' },
  header: { marginBottom: '24px' },
  title: { margin: 0, color: '#e6edf3', fontSize: '34px', fontWeight: 800 },
  subtitle: { color: '#8b949e', marginTop: '6px', fontSize: '15px' },
  dateInput: {
    background: '#0d1117',
    color: '#e6edf3',
    border: '1px solid #30363d',
    borderRadius: '8px',
    padding: '8px',
    marginLeft: '8px',
  },
  card: {
    background: '#0d1117',
    border: '1px solid #30363d',
    borderRadius: '14px',
    padding: '18px',
    marginBottom: '16px',
  },
  gameCard: {
    background: '#0d1117',
    border: '1px solid #30363d',
    borderRadius: '14px',
    padding: '20px',
    marginBottom: '20px',
  },
  gameHeader: {
    display: 'flex',
    justifyContent: 'space-between',
    gap: '16px',
    alignItems: 'flex-start',
    flexWrap: 'wrap',
    marginBottom: '16px',
  },
  matchupTitle: { margin: 0, color: '#e6edf3', fontSize: '24px', fontWeight: 800 },
  meta: { color: '#8b949e', fontSize: '14px', marginTop: '5px' },
  pill: {
    display: 'inline-block',
    padding: '3px 8px',
    borderRadius: '999px',
    background: '#21262d',
    color: '#c9d1d9',
    fontSize: '12px',
    marginLeft: '8px',
    whiteSpace: 'nowrap',
  },
  grid: {
    display: 'grid',
    gridTemplateColumns: 'repeat(auto-fit, minmax(260px, 1fr))',
    gap: '14px',
  },
  splitGrid: {
    display: 'grid',
    gridTemplateColumns: 'repeat(auto-fit, minmax(340px, 1fr))',
    gap: '14px',
    marginTop: '14px',
  },
  metricCard: {
    background: '#161b22',
    border: '1px solid #30363d',
    borderRadius: '12px',
    padding: '16px',
  },
  metricLabel: {
    color: '#8b949e',
    textTransform: 'uppercase',
    letterSpacing: '0.6px',
    fontSize: '11px',
    fontWeight: 700,
    marginBottom: '7px',
  },
  metricValue: { color: '#58a6ff', fontSize: '30px', fontWeight: 850, lineHeight: 1 },
  metricSub: { color: '#c9d1d9', fontSize: '13px', marginTop: '8px' },
  sectionTitle: {
    color: '#58a6ff',
    fontSize: '18px',
    fontWeight: 800,
    margin: '18px 0 10px',
  },
  row: {
    display: 'flex',
    justifyContent: 'space-between',
    gap: '12px',
    borderBottom: '1px solid #21262d',
    padding: '8px 0',
    fontSize: '14px',
  },
  key: { color: '#8b949e' },
  val: { color: '#e6edf3', fontWeight: 750, textAlign: 'right' },
  tabBar: {
    display: 'flex',
    flexWrap: 'wrap',
    border: '1px solid #30363d',
    borderRadius: '10px',
    overflow: 'hidden',
    margin: '16px 0',
    width: 'fit-content',
    maxWidth: '100%',
  },
  tab: {
    border: 0,
    borderRight: '1px solid #30363d',
    background: '#0d1117',
    color: '#8b949e',
    padding: '10px 14px',
    fontWeight: 800,
    cursor: 'pointer',
  },
  tabActive: {
    background: '#58a6ff',
    color: '#0d1117',
  },
  details: {
    marginTop: '14px',
    background: '#0a0f14',
    border: '1px solid #21262d',
    borderRadius: '10px',
    padding: '12px',
  },
  summary: { cursor: 'pointer', color: '#c9d1d9', fontWeight: 800 },
  diagnosticHeader: {
    display: 'flex',
    justifyContent: 'space-between',
    alignItems: 'flex-start',
    flexWrap: 'wrap',
    gap: '12px',
    marginBottom: '14px',
  },
  diagnosticStatus: {
    display: 'inline-flex',
    alignItems: 'center',
    gap: '7px',
    borderRadius: '999px',
    padding: '5px 10px',
    fontSize: '12px',
    fontWeight: 800,
  },
  featureGrid: {
    display: 'grid',
    gridTemplateColumns: 'repeat(auto-fit, minmax(210px, 1fr))',
    gap: '8px',
  },
  featureRow: {
    display: 'flex',
    alignItems: 'center',
    gap: '9px',
    border: '1px solid #30363d',
    borderRadius: '9px',
    padding: '9px 10px',
    background: '#0d1117',
  },
  featureIcon: {
    width: '20px',
    height: '20px',
    borderRadius: '999px',
    display: 'inline-flex',
    alignItems: 'center',
    justifyContent: 'center',
    flexShrink: 0,
    fontSize: '12px',
    fontWeight: 900,
  },
  warning: {
    border: '1px solid #9e6a03',
    borderRadius: '9px',
    background: 'rgba(158, 106, 3, 0.12)',
    color: '#d29922',
    padding: '10px 12px',
    marginTop: '8px',
    fontSize: '13px',
  },
  rawPayload: {
    maxHeight: '440px',
    overflow: 'auto',
    whiteSpace: 'pre-wrap',
    overflowWrap: 'anywhere',
    color: '#c9d1d9',
    fontFamily: 'ui-monospace, SFMono-Regular, Menlo, monospace',
    fontSize: '12px',
    lineHeight: 1.5,
  },
  noData: { color: '#8b949e', padding: '18px', textAlign: 'center' },
}

function today() {
  return new Date().toISOString().slice(0, 10)
}

function num(v, digits = 1) {
  if (v === null || v === undefined || v === '') return '—'
  const n = Number(v)
  if (!Number.isFinite(n)) return String(v)
  return n.toFixed(digits)
}

function pct(v, digits = 1) {
  if (v === null || v === undefined || v === '') return '—'
  const n = Number(v)
  if (!Number.isFinite(n)) return String(v)
  return `${(n * 100).toFixed(digits)}%`
}

function label(v) {
  if (v === null || v === undefined || v === '') return '—'
  return String(v).replace(/_/g, ' ')
}

function findModel(team, name) {
  return (team?.models || []).find(m => m?.model_name === name)
}

function getSharedSimulation(game) {
  return game?.sharedSimulation || {}
}

function getSharedDerivedSimulation(game) {
  const shared = getSharedSimulation(game)
  const derived = shared?.derived_outputs || {}
  return (
    derived.bullpen_adjusted_game_simulation ||
    derived.game_simulation ||
    {}
  )
}

function getSharedMeta(game) {
  const shared = getSharedSimulation(game)
  return shared?.meta || shared?.metadata || {}
}

function getSharedFormulaMap(game) {
  return getSharedSimulation(game)?.formulaMap || {}
}

function getSharedDirectInputs(game) {
  return getSharedSimulation(game)?.direct_inputs || {}
}

function getSharedPAModels(game) {
  return getSharedSimulation(game)?.pa_models || {}
}

function isPresent(v) {
  return v !== null && v !== undefined && v !== '' && !(typeof v === 'number' && Number.isNaN(v))
}

function formatStatValue(key, value, format = 'auto') {
  if (!isPresent(value)) return null

  if (format === 'pct') return pct(value)
  if (format === 'num') return num(value)
  if (format === 'decimal') {
    const n = Number(value)
    if (!Number.isFinite(n)) return label(value)
    return n.toFixed(3)
  }
  if (format === 'text') return label(value)

  const keyText = String(key || '').toLowerCase().replace(/_/g, ' ')

  const forceNumberKeys = [
    'spin', 'velocity', 'release', 'movement', 'extension',
    'pa', 'plate appearances', 'hits', 'walks', 'strikeouts',
    'home runs', 'doubles', 'triples', 'pitch count', 'count used',
    'avg spin rate', 'avg velocity'
  ]

  const decimalKeys = [
    'xwoba', 'xba', 'iso', 'slugging', 'on base', 'obp',
    'batting avg', 'batting average', 'avg allowed',
    'index', 'score', 'confidence'
  ]

  const pctKeys = [
    'k rate', 'bb rate', 'k pct', 'bb pct', 'rate allowed',
    'hard hit', 'barrel', 'probability', 'usage pct',
    'usage', 'whiff', 'csw', 'zone', 'strike',
    'over ', 'under ', '3+ runs', '4+ runs', '5+ runs'
  ]

  if (forceNumberKeys.some(token => keyText.includes(token))) return num(value)

  if (decimalKeys.some(token => keyText.includes(token))) {
    const n = Number(value)
    if (!Number.isFinite(n)) return label(value)
    return n.toFixed(3)
  }

  if (pctKeys.some(token => keyText.includes(token))) return pct(value)

  if (typeof value === 'number') return num(value)
  return label(value)
}

function StatRow({ k, v, format = 'auto' }) {
  const rendered = formatStatValue(k, v, format)
  if (!isPresent(rendered)) return null

  return (
    <div style={s.row}>
      <span style={s.key}>{k}</span>
      <span style={s.val}>{rendered}</span>
    </div>
  )
}

function Tag({ children, tone = 'context' }) {
  const colors = {
    sim: '#1f6feb',
    context: '#9e6a03',
    diagnostic: '#30363d',
  }
  return (
    <span style={{
      display: 'inline-block',
      marginLeft: '8px',
      padding: '2px 8px',
      borderRadius: '999px',
      background: colors[tone] || colors.context,
      color: '#e6edf3',
      fontSize: '11px',
      fontWeight: 800,
      verticalAlign: 'middle',
    }}>
      {children}
    </span>
  )
}

function MetricCard({ labelText, value, sub, format = 'num' }) {
  const rendered = format === 'pct' ? pct(value) : format === 'text' ? label(value) : num(value)
  return (
    <div style={s.metricCard}>
      <div style={s.metricLabel}>{labelText}</div>
      <div style={s.metricValue}>{rendered}</div>
      {sub ? <div style={s.metricSub}>{sub}</div> : null}
    </div>
  )
}

function GenericPanel({ title, subtitle, tag, tagTone = 'context', children }) {
  return (
    <div style={s.metricCard}>
      <div style={s.metricLabel}>
        {title}
        {tag ? <Tag tone={tagTone}>{tag}</Tag> : null}
      </div>
      {subtitle ? <h3 style={{ margin: '0 0 12px', color: '#e6edf3' }}>{subtitle}</h3> : null}
      {children}
    </div>
  )
}

function DataSection({ title, data, formatHint = {}, tag, tagTone = 'context' }) {
  if (!data || typeof data !== 'object') {
    return null
  }

  const rows = Object.entries(data)
    .filter(([, value]) => !(value && typeof value === 'object'))
    .map(([key, value]) => {
      const format = formatHint[key] || 'auto'
      return [key, value, format]
    })
    .filter(([key, value, format]) => isPresent(formatStatValue(label(key), value, format)))

  if (!rows.length) return null

  return (
    <GenericPanel title={title} tag={tag} tagTone={tagTone}>
      {rows.map(([key, value, format]) => (
        <StatRow key={key} k={label(key)} v={value} format={format} />
      ))}
    </GenericPanel>
  )
}

function TeamProjectionPanel({ side, teamName, pitcherName, model, sim = {}, teamTotals = {}, directInputs = {} }) {
  const inputs = model?.inputs || {}
  const isAway = String(side || '').toLowerCase() === 'away'
  const expectedRuns = isAway
    ? sim.away_expected_runs ?? inputs.expected_runs ?? model?.score
    : sim.home_expected_runs ?? inputs.expected_runs ?? model?.score
  const winProbability = isAway
    ? sim.away_win_probability ?? inputs.win_probability
    : sim.home_win_probability ?? inputs.win_probability

  return (
    <div style={s.metricCard}>
      <div style={s.metricLabel}>{side} Projection</div>
      <h3 style={{ margin: '0 0 4px', color: '#e6edf3' }}>{teamName || side}</h3>
      <div style={{ color: '#8b949e', fontSize: '13px', marginBottom: '12px' }}>
        {pitcherName || 'No pitcher listed'}
        <span style={s.pill}>{model?.data_confidence || directInputs?.metadata?.data_confidence || 'shared simulation'} confidence</span>
      </div>

      <MetricCard
        labelText="Expected Runs"
        value={expectedRuns}
        sub={`Simulation-derived: ${num(expectedRuns)}`}
      />

      <div style={{ marginTop: '12px' }}>
        <StatRow k="Win Probability" v={winProbability} format="pct" />
        <StatRow k="3+ Runs" v={isAway ? teamTotals.away_3_plus : teamTotals.home_3_plus} format="pct" />
        <StatRow k="4+ Runs" v={isAway ? teamTotals.away_4_plus : teamTotals.home_4_plus} format="pct" />
        <StatRow k="5+ Runs" v={isAway ? teamTotals.away_5_plus : teamTotals.home_5_plus} format="pct" />
        <StatRow k="Offense Source" v={directInputs?.metadata?.source_type || inputs.offense_source} />
        <StatRow k="Run Environment Index" v={directInputs?.run_environment?.run_scoring_index ?? inputs.run_environment_index} format="num" />
      </div>
    </div>
  )
}

function TotalProjectionPanel({ model, sim = {}, environmentProfile = {} }) {
  const inputs = model?.inputs || {}
  const totals = sim.calibrated_total_probabilities || sim.total_probabilities || {}
  const run = environmentProfile?.run_environment || {}

  return (
    <div style={s.metricCard}>
      <div style={s.metricLabel}>Game Total Projection</div>
      <MetricCard
        labelText="Projected Total Runs"
        value={sim.total_expected_runs ?? inputs.total_expected_runs ?? model?.score}
        sub={`Simulation-derived: ${num(sim.total_expected_runs ?? inputs.total_expected_runs ?? model?.score)}`}
      />

      <div style={{ marginTop: '12px' }}>
        <StatRow k="Over 6.5" v={totals['over_6.5'] ?? inputs.over_6_5} format="pct" />
        <StatRow k="Over 7.5" v={totals['over_7.5'] ?? inputs.over_7_5} format="pct" />
        <StatRow k="Over 8.5" v={totals['over_8.5'] ?? inputs.over_8_5} format="pct" />
        <StatRow k="Over 9.5" v={totals['over_9.5'] ?? inputs.over_9_5} format="pct" />
        <StatRow k="Under 7.5" v={totals['under_7.5'] ?? inputs.under_7_5} format="pct" />
        <StatRow k="Under 8.5" v={totals['under_8.5'] ?? inputs.under_8_5} format="pct" />
        <StatRow k="Under 9.5" v={totals['under_9.5'] ?? inputs.under_9_5} format="pct" />
        <StatRow k="Tie After Regulation" v={sim.tie_after_regulation_probability ?? inputs.tie_after_regulation} format="pct" />
        <StatRow k="Environment" v={run.scoring_environment_label ?? inputs.environment_label} />
      </div>
    </div>
  )
}

function OverviewTab({ game, awayRunModel, homeRunModel, totalModel }) {
  const away = game?.teams?.away || {}
  const home = game?.teams?.home || {}
  const awayInputs = awayRunModel?.inputs || {}
  const homeInputs = homeRunModel?.inputs || {}
  const totalInputs = totalModel?.inputs || {}

  const sharedSim = getSharedDerivedSimulation(game)
  const directInputs = getSharedDirectInputs(game)
  const totals = sharedSim.calibrated_total_probabilities || sharedSim.total_probabilities || {}
  const teamTotals = sharedSim.calibrated_team_total_probabilities || sharedSim.team_total_probabilities || {}

  const totalExpectedRuns = sharedSim.total_expected_runs ?? totalInputs.total_expected_runs ?? totalModel?.score
  const awayExpectedRuns = sharedSim.away_expected_runs ?? awayInputs.expected_runs ?? awayRunModel?.score
  const homeExpectedRuns = sharedSim.home_expected_runs ?? homeInputs.expected_runs ?? homeRunModel?.score
  const awayWinProbability = sharedSim.away_win_probability ?? awayInputs.win_probability
  const homeWinProbability = sharedSim.home_win_probability ?? homeInputs.win_probability

  return (
    <>
      <div style={s.grid}>
        <MetricCard labelText="Projected Total" value={totalExpectedRuns} />
        <MetricCard labelText={`${game?.away_team?.name || away?.team_name || 'Away'} Runs`} value={awayExpectedRuns} />
        <MetricCard labelText={`${game?.home_team?.name || home?.team_name || 'Home'} Runs`} value={homeExpectedRuns} />
        <MetricCard labelText={`${game?.away_team?.name || away?.team_name || 'Away'} Win`} value={awayWinProbability} format="pct" />
        <MetricCard labelText={`${game?.home_team?.name || home?.team_name || 'Home'} Win`} value={homeWinProbability} format="pct" />
        <MetricCard labelText="Over 8.5" value={totals['over_8.5'] ?? totalInputs.over_8_5} format="pct" />
      </div>

      <div style={s.splitGrid}>
        <TeamProjectionPanel
          side="Away"
          teamName={game?.away_team?.name || away?.team_name}
          pitcherName={game?.away_pitcher?.name || away?.pitcher_name}
          model={awayRunModel}
          sim={sharedSim}
          teamTotals={teamTotals}
          directInputs={directInputs.away_offense_profile}
        />
        <TeamProjectionPanel
          side="Home"
          teamName={game?.home_team?.name || home?.team_name}
          pitcherName={game?.home_pitcher?.name || home?.pitcher_name}
          model={homeRunModel}
          sim={sharedSim}
          teamTotals={teamTotals}
          directInputs={directInputs.home_offense_profile}
        />
      </div>

      <div style={{ marginTop: '14px' }}>
        <TotalProjectionPanel model={totalModel} sim={sharedSim} environmentProfile={directInputs.environment_profile} />
      </div>
    </>
  )
}

function PitcherTab({ workspace, game }) {
  const directInputs = getSharedDirectInputs(game)
  return (
    <div style={s.splitGrid}>
      <PitcherProfilePanel labelText="Away Starting Pitcher" profile={directInputs.away_pitcher_profile || workspace?.awayPitcherProfile} />
      <PitcherProfilePanel labelText="Home Starting Pitcher" profile={directInputs.home_pitcher_profile || workspace?.homePitcherProfile} />
    </div>
  )
}

function PitcherProfilePanel({ labelText, profile }) {
  const metadata = profile?.metadata || {}
  const arsenal = profile?.arsenal || {}

  return (
    <div style={s.metricCard}>
      <div style={s.metricLabel}>{labelText}</div>
      <h3 style={{ margin: '0 0 4px', color: '#e6edf3' }}>{metadata.pitcher_name || 'Unknown pitcher'}</h3>
      <div style={{ color: '#8b949e', fontSize: '13px', marginBottom: '12px' }}>
        {metadata.source_type || 'pitcher profile'}
        <span style={s.pill}>{metadata.data_confidence || 'unknown'} confidence</span>
      </div>

      <div style={s.grid}>
        <DataSection title="Bat Missing" data={profile?.bat_missing} />
        <DataSection title="Command / Control" data={profile?.command_control} />
        <DataSection
          title="Contact Management"
          data={Object.fromEntries(
            Object.entries(profile?.contact_management || {}).filter(([key]) => key !== 'xba_allowed')
          )}
        />
        <GenericPanel title="Arsenal">
          <StatRow k="Avg Velocity" v={arsenal.avg_velocity} format="num" />
          <StatRow k="Avg Spin Rate" v={arsenal.avg_spin_rate} format="num" />
          <details style={{ marginTop: '10px' }}>
            <summary style={s.summary}>Pitch mix</summary>
            <pre style={{ whiteSpace: 'pre-wrap', color: '#c9d1d9', fontFamily: 'inherit' }}>
              {JSON.stringify(arsenal.pitch_mix || {}, null, 2)}
            </pre>
          </details>
        </GenericPanel>
      </div>
    </div>
  )
}

function BatterTab({ workspace, game }) {
  const directInputs = getSharedDirectInputs(game)
  return (
    <div style={s.splitGrid}>
      <OffenseProfilePanel labelText="Away Offense" profile={directInputs.away_offense_profile || workspace?.awayOffenseProfile} />
      <OffenseProfilePanel labelText="Home Offense" profile={directInputs.home_offense_profile || workspace?.homeOffenseProfile} />
    </div>
  )
}

function OffenseProfilePanel({ labelText, profile }) {
  const metadata = profile?.metadata || {}

  return (
    <div style={s.metricCard}>
      <div style={s.metricLabel}>{labelText}</div>
      <h3 style={{ margin: '0 0 4px', color: '#e6edf3' }}>{metadata.team_name || 'Unknown team'}</h3>
      <div style={{ color: '#8b949e', fontSize: '13px', marginBottom: '12px' }}>
        {metadata.source_type || 'offense profile'}
        <span style={s.pill}>{metadata.data_confidence || 'unknown'} confidence</span>
      </div>

      <div style={s.grid}>
        <DataSection title="Contact Skill" data={profile?.contact_skill} />
        <DataSection title="Plate Discipline" data={profile?.plate_discipline} />
        <DataSection title="Power" data={profile?.power} />
        {/* Run Creation is intentionally hidden in the core Batter tab until count formatting and model usage are finalized. */}
      </div>
    </div>
  )
}

function EnvironmentTab({ workspace, game }) {
  const directInputs = getSharedDirectInputs(game)
  const profile = directInputs.environment_profile || workspace?.environmentProfile || {}
  const run = profile.run_environment || {}
  const weather = profile.weather || {}
  const metadata = profile.metadata || {}

  return (
    <div style={s.splitGrid}>
      <GenericPanel title="Run Environment" subtitle={label(run.scoring_environment_label)}>
        <StatRow k="Run Scoring Index" v={run.run_scoring_index} format="num" />
        <StatRow k="HR Boost Index" v={run.hr_boost_index} format="num" />
        <StatRow k="Hit Boost Index" v={run.hit_boost_index} format="num" />
        <StatRow k="Weather Impact" v={run.weather_run_impact} />
        <StatRow k="Wind Impact" v={run.wind_run_impact} />
      </GenericPanel>

      <GenericPanel title="Weather">
        <StatRow k="Temperature" v={weather.temperature_f} format="num" />
        <StatRow k="Condition" v={weather.condition} />
        <StatRow k="Wind Speed" v={weather.wind_speed_mph} format="num" />
        <StatRow k="Wind Direction" v={weather.wind_direction} />
      </GenericPanel>

      <DataSection title="Metadata" data={metadata} />
    </div>
  )
}

function MatchupTab({ workspace }) {
  return (
    <div style={s.splitGrid}>
      <MatchupPanel labelText="Away Offense vs Home Pitching" analysis={workspace?.awayMatchupAnalysis} />
      <MatchupPanel labelText="Home Offense vs Away Pitching" analysis={workspace?.homeMatchupAnalysis} />
    </div>
  )
}

function MatchupPanel({ labelText, analysis }) {
  const metadata = analysis?.metadata || {}
  const summary = analysis?.summary || {}
  const plate = analysis?.plate_discipline_matchup || {}
  const arsenal = analysis?.arsenal_matchup || {}

  return (
    <div style={s.metricCard}>
      <div style={s.metricLabel}>{labelText}</div>
      <h3 style={{ margin: '0 0 8px', color: '#e6edf3' }}>
        {metadata.offense_team_name || 'Offense'} vs {metadata.opposing_pitcher_name || 'Pitcher'}
      </h3>
      <StatRow k="Status" v={summary.status} />
      <StatRow k="Biggest Edge" v={summary.biggest_edge} />
      <StatRow k="Confidence" v={summary.confidence} format="pct" />
      <StatRow k="Note" v={summary.note} />

      <div style={s.grid}>
        <DataSection title="Plate Discipline Matchup" data={plate} />
        <GenericPanel title="Arsenal Matchup">
          <StatRow k="Biggest Edge" v={arsenal.biggest_edge} />
          <StatRow k="Pitch Count Used" v={arsenal.pitch_count_used} format="num" />
          <details style={{ marginTop: '10px' }}>
            <summary style={s.summary}>Pitch edges</summary>
            <pre style={{ whiteSpace: 'pre-wrap', color: '#c9d1d9', fontFamily: 'inherit' }}>
              {JSON.stringify(arsenal.pitch_edges || [], null, 2)}
            </pre>
          </details>
        </GenericPanel>
      </div>
    </div>
  )
}

function BullpenTab({ workspace, game }) {
  const directInputs = getSharedDirectInputs(game)
  return (
    <div style={s.splitGrid}>
      <BullpenProfilePanel labelText="Away Bullpen" profile={directInputs.away_bullpen_profile || workspace?.awayBullpenProfile} />
      <BullpenProfilePanel labelText="Home Bullpen" profile={directInputs.home_bullpen_profile || workspace?.homeBullpenProfile} />
    </div>
  )
}

function BullpenProfilePanel({ labelText, profile }) {
  const metadata = profile?.metadata || {}

  return (
    <div style={s.metricCard}>
      <div style={s.metricLabel}>{labelText}</div>
      <h3 style={{ margin: '0 0 4px', color: '#e6edf3' }}>{metadata.team_name || 'Unknown team'}</h3>
      <div style={{ color: '#8b949e', fontSize: '13px', marginBottom: '12px' }}>
        {metadata.bullpen_profile_version || 'bullpen profile'}
        <span style={s.pill}>{label(metadata.bullpen_quality_label)}</span>
      </div>
      <div style={s.grid}>
        <DataSection title="Bat Missing" data={profile?.bat_missing} />
        <DataSection title="Command / Control" data={profile?.command_control} />
        <DataSection title="Contact Management" data={profile?.contact_management} />
        <DataSection title="Platoon Profile" data={profile?.platoon_profile} />
        {/* Bullpen arsenal is hidden in the core tab until active reliever pitch-mix data is available. */}
      </div>
    </div>
  )
}

function ModelContractPanel({ game }) {
  const meta = getSharedMeta(game)
  const shared = getSharedSimulation(game)

  return (
    <GenericPanel
      title="Model Contract"
      subtitle={meta.model_version || shared.model_version || 'shared simulation'}
      tag="Diagnostic"
      tagTone="diagnostic"
    >
      <StatRow k="Status" v={shared.status} />
      <StatRow k="Source Builder" v={meta.source_builder} />
      <StatRow k="Simulation Count" v={meta.simulation_count} format="num" />
      <StatRow k="Seed" v={meta.seed} format="num" />
      <StatRow k="Starter Exit Enabled" v={meta.starter_exit_enabled ? 'true' : 'false'} />
      <StatRow k="Starter Quality Score" v={meta.starter_quality_score} format="decimal" />
      <StatRow k="Starter Quality Label" v={meta.starter_quality_label} />
      <StatRow k="Calibration Version" v={meta.calibration_version} />
      <StatRow k="Offense Source" v={meta.offense_source} />
      <StatRow k="Pitcher Source" v={meta.pitcher_source} />
      <StatRow k="Bullpen Source" v={meta.bullpen_source} />
      <StatRow k="Environment Source" v={meta.environment_source} />
      {shared.error ? <StatRow k="Shared Simulation Error" v={shared.error} /> : null}
    </GenericPanel>
  )
}

function SimulationTab({ workspace, game }) {
  const sharedSim = getSharedDerivedSimulation(game)
  const sim = Object.keys(sharedSim || {}).length ? sharedSim : (workspace?.bullpenAdjustedGameSimulation || {})
  const totals = sim.calibrated_total_probabilities || sim.total_probabilities || {}
  const teamTotals = sim.calibrated_team_total_probabilities || sim.team_total_probabilities || {}

  return (
    <div style={s.splitGrid}>
      <ModelContractPanel game={game} />

      <GenericPanel title="Game Simulation" subtitle={sim.model_version || 'bullpen adjusted simulation'}>
        <StatRow k="Total Expected Runs" v={sim.total_expected_runs} format="num" />
        <StatRow k="Away Expected Runs" v={sim.away_expected_runs} format="num" />
        <StatRow k="Home Expected Runs" v={sim.home_expected_runs} format="num" />
        <StatRow k="Away Win Probability" v={sim.away_win_probability} format="pct" />
        <StatRow k="Home Win Probability" v={sim.home_win_probability} format="pct" />
        <StatRow k="Tie After Regulation" v={sim.tie_after_regulation_probability} format="pct" />
        <StatRow k="Dynamic Starter Exit" v={sim.dynamic_starter_exit ? 'true' : 'false'} />
      </GenericPanel>

      <GenericPanel title="Game Totals">
        <StatRow k="Over 6.5" v={totals['over_6.5']} format="pct" />
        <StatRow k="Over 7.5" v={totals['over_7.5']} format="pct" />
        <StatRow k="Over 8.5" v={totals['over_8.5']} format="pct" />
        <StatRow k="Over 9.5" v={totals['over_9.5']} format="pct" />
        <StatRow k="Under 8.5" v={totals['under_8.5']} format="pct" />
        <StatRow k="Under 9.5" v={totals['under_9.5']} format="pct" />
      </GenericPanel>

      <GenericPanel title="Team Totals">
        <StatRow k="Away 3+ Runs" v={teamTotals.away_3_plus} format="pct" />
        <StatRow k="Away 4+ Runs" v={teamTotals.away_4_plus} format="pct" />
        <StatRow k="Away 5+ Runs" v={teamTotals.away_5_plus} format="pct" />
        <StatRow k="Home 3+ Runs" v={teamTotals.home_3_plus} format="pct" />
        <StatRow k="Home 4+ Runs" v={teamTotals.home_4_plus} format="pct" />
        <StatRow k="Home 5+ Runs" v={teamTotals.home_5_plus} format="pct" />
      </GenericPanel>
    </div>
  )
}

function projectionNumber(value, digits = 2) {
  const parsed = Number(value)

  if (!Number.isFinite(parsed)) return '—'

  return parsed.toFixed(digits)
}

function ProjectionTable({
  title,
  columns,
  rows,
}) {
  return (
    <div style={{ ...s.metricCard, marginTop: '14px' }}>
      <div style={s.metricLabel}>{title}</div>

      {!rows.length ? (
        <div style={s.noData}>
          No {title.toLowerCase()} are available for this run.
        </div>
      ) : (
        <div style={{ overflowX: 'auto' }}>
          <table
            style={{
              width: '100%',
              borderCollapse: 'collapse',
              minWidth: '1120px',
              marginTop: '10px',
            }}
          >
            <thead>
              <tr>
                {columns.map(column => (
                  <th
                    key={column.key}
                    style={{
                      color: '#8b949e',
                      fontSize: '11px',
                      fontWeight: 700,
                      letterSpacing: '0.04em',
                      padding: '9px 8px',
                      textAlign: column.align || 'right',
                      borderBottom: '1px solid #30363d',
                      whiteSpace: 'nowrap',
                    }}
                  >
                    {column.label}
                  </th>
                ))}
              </tr>
            </thead>

            <tbody>
              {rows.map(row => (
                <tr
                  key={
                    row.mlbPlayerId ||
                    row.playerId ||
                    `${row.side}-${row.name}`
                  }
                >
                  {columns.map(column => (
                    <td
                      key={column.key}
                      style={{
                        color: (
                          column.key === 'name'
                            ? '#e6edf3'
                            : '#c9d1d9'
                        ),
                        fontSize: '12px',
                        padding: '9px 8px',
                        textAlign: column.align || 'right',
                        borderBottom: '1px solid #21262d',
                        whiteSpace: 'nowrap',
                        fontWeight: (
                          column.key === 'name' ||
                          column.key === 'dfsMean'
                            ? 600
                            : 400
                        ),
                      }}
                    >
                      {column.format === 'text'
                        ? row[column.key]
                        : projectionNumber(
                            row[column.key],
                            column.digits ?? 2,
                          )}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

const BATTER_PROJECTION_COLUMNS = [
  { key: 'name', label: 'Player', format: 'text', align: 'left' },
  { key: 'side', label: 'Side', format: 'text', align: 'left' },
  { key: 'plateAppearances', label: 'PA' },
  { key: 'hits', label: 'H' },
  { key: 'runs', label: 'R' },
  { key: 'rbis', label: 'RBI' },
  { key: 'singles', label: '1B' },
  { key: 'doubles', label: '2B' },
  { key: 'triples', label: '3B' },
  { key: 'homeRuns', label: 'HR' },
  { key: 'walks', label: 'BB' },
  { key: 'stolenBases', label: 'SB' },
  { key: 'strikeouts', label: 'K' },
  { key: 'dfsMean', label: 'DK Mean' },
  { key: 'dfsFloor', label: 'DK Floor' },
  { key: 'dfsMedian', label: 'DK Median' },
  { key: 'dfsCeiling', label: 'DK Ceiling' },
]

const PITCHER_PROJECTION_COLUMNS = [
  { key: 'name', label: 'Pitcher', format: 'text', align: 'left' },
  { key: 'side', label: 'Side', format: 'text', align: 'left' },
  { key: 'pitcherRoleLabel', label: 'Role', format: 'text', align: 'left' },
  { key: 'battersFaced', label: 'BF' },
  { key: 'inningsPitched', label: 'IP' },
  { key: 'inningsPitchedP10', label: 'IP P10' },
  { key: 'inningsPitchedMedian', label: 'IP Median' },
  { key: 'inningsPitchedP90', label: 'IP P90' },
  { key: 'hitsAllowed', label: 'H' },
  { key: 'walks', label: 'BB' },
  { key: 'hitByPitch', label: 'HBP' },
  { key: 'strikeouts', label: 'K' },
  { key: 'runs', label: 'R' },
  { key: 'earnedRuns', label: 'ER' },
  { key: 'dfsMean', label: 'DK Mean' },
  { key: 'dfsFloor', label: 'DK Floor' },
  { key: 'dfsMedian', label: 'DK Median' },
  { key: 'dfsCeiling', label: 'DK Ceiling' },
]

function ProjectionsTab({ game }) {
  const view = (
    buildCanonicalProjectionsViewModel(game)
  )

  if (!view.available) {
    return (
      <div style={s.noData}>
        <div
          style={{
            color: '#e6edf3',
            fontSize: '16px',
            fontWeight: 800,
            marginBottom: '8px',
          }}
        >
          {view.unavailable.title}
        </div>

        <div>
          {view.unavailable.message}
        </div>

        {view.unavailable.blockers.length ? (
          <div
            style={{
              marginTop: '14px',
              display: 'grid',
              gap: '8px',
            }}
          >
            {view.unavailable.blockers.map(
              blocker => (
                <div
                  key={blocker.key}
                  style={{
                    border: '1px solid #30363d',
                    borderRadius: '8px',
                    padding: '9px 11px',
                    background: '#161b22',
                  }}
                >
                  <div
                    style={{
                      color: '#e6edf3',
                      fontWeight: 750,
                    }}
                  >
                    {blocker.label}
                  </div>

                  {blocker.detail ? (
                    <div
                      style={{
                        color: '#8b949e',
                        fontSize: '12px',
                        marginTop: '3px',
                      }}
                    >
                      {blocker.detail}
                    </div>
                  ) : null}
                </div>
              )
            )}
          </div>
        ) : null}

        <div
          style={{
            color: '#8b949e',
            fontSize: '12px',
            marginTop: '12px',
          }}
        >
          This tab only renders rows produced by the same
          canonical simulation run shown in Simulation and
          Diagnostics.
        </div>
      </div>
    )
  }

  return (
    <div>
      <div style={s.diagnosticHeader}>
        <div>
          <h3
            style={{
              margin: 0,
              color: '#e6edf3',
              fontSize: '21px',
            }}
          >
            Canonical Player Projections
          </h3>

          <div
            style={{
              color: '#8b949e',
              fontSize: '13px',
              marginTop: '5px',
            }}
          >
            Player outcomes derived from the exact same trial
            batch as this game simulation.
          </div>
        </div>

        <Tag
          tone={
            view.authoritative
              ? 'success'
              : 'diagnostic'
          }
        >
          {
            view.authoritative
              ? 'Authoritative production'
              : 'Non-authoritative shadow'
          }
        </Tag>
      </div>

      <div style={s.grid}>
        <GenericPanel title="Run Identity">
          <StatRow
            k="Run ID"
            v={view.runId}
            format="text"
          />
          <StatRow
            k="Model Version"
            v={view.modelVersion}
            format="text"
          />
          <StatRow
            k="Simulation Count"
            v={view.simulationCount}
            format="num"
          />
        </GenericPanel>

        <GenericPanel title="Projection Contract">
          <StatRow
            k="Schema"
            v={view.schemaVersion}
            format="text"
          />
          <StatRow
            k="Source Schema"
            v={view.sourceProjectionSchemaVersion}
            format="text"
          />
          <StatRow
            k="Authoritative Source"
            v={view.authoritativeSource}
            format="text"
          />
          <StatRow
            k="Identity Enrichment"
            v={
              view.identityEnrichmentApplied
                ? 'applied'
                : 'not applied'
            }
            format="text"
          />
        </GenericPanel>
      </div>

      <ProjectionTable
        title="Batter Projections"
        columns={BATTER_PROJECTION_COLUMNS}
        rows={view.batters}
      />

      <ProjectionTable
        title="Pitcher Projections"
        columns={PITCHER_PROJECTION_COLUMNS}
        rows={view.pitchers}
      />
    </div>
  )
}

function shortDigest(value) {
  if (!value) return '—'
  const text = String(value)
  return text.length > 18
    ? `${text.slice(0, 10)}…${text.slice(-6)}`
    : text
}

function statusPresentation(state) {
  const normalized = String(state || '').toLowerCase()

  if (
    normalized === 'complete' ||
    normalized === 'available'
  ) {
    return {
      label: 'Complete',
      foreground: '#3fb950',
      background: 'rgba(46, 160, 67, 0.15)',
      symbol: '✓',
    }
  }

  if (normalized === 'error') {
    return {
      label: 'Error',
      foreground: '#f85149',
      background: 'rgba(248, 81, 73, 0.15)',
      symbol: '!',
    }
  }

  if (
    normalized === 'disabled' ||
    normalized === 'unavailable' ||
    normalized === 'not_run'
  ) {
    return {
      label: (
        normalized === 'not_run'
          ? 'Not run'
          : label(state || 'Unavailable')
      ),
      foreground: '#8b949e',
      background: '#21262d',
      symbol: '○',
    }
  }

  return {
    label: label(state || 'Unknown'),
    foreground: '#d29922',
    background: 'rgba(210, 153, 34, 0.15)',
    symbol: '•',
  }
}

function DiagnosticStatusBadge({ state }) {
  const presentation = statusPresentation(state)

  return (
    <span
      style={{
        ...s.diagnosticStatus,
        color: presentation.foreground,
        background: presentation.background,
      }}
    >
      <span>{presentation.symbol}</span>
      {presentation.label}
    </span>
  )
}

function RealismFeature({ feature }) {
  const presentations = {
    enabled: {
      symbol: '✓',
      foreground: '#3fb950',
      background: 'rgba(46, 160, 67, 0.15)',
    },
    deferred: {
      symbol: '○',
      foreground: '#d29922',
      background: 'rgba(210, 153, 34, 0.15)',
    },
    disabled: {
      symbol: '–',
      foreground: '#f85149',
      background: 'rgba(248, 81, 73, 0.15)',
    },
    unknown: {
      symbol: '?',
      foreground: '#8b949e',
      background: '#21262d',
    },
  }

  const presentation =
    presentations[feature.status] ||
    presentations.unknown

  return (
    <div style={s.featureRow}>
      <span
        style={{
          ...s.featureIcon,
          color: presentation.foreground,
          background: presentation.background,
        }}
      >
        {presentation.symbol}
      </span>

      <div>
        <div
          style={{
            color: '#e6edf3',
            fontSize: '13px',
            fontWeight: 750,
          }}
        >
          {feature.label}
        </div>

        {feature.detail ? (
          <div
            style={{
              color: '#8b949e',
              fontSize: '11px',
              marginTop: '2px',
            }}
          >
            {feature.detail}
          </div>
        ) : null}
      </div>
    </div>
  )
}

function DiagnosticsTab({ game }) {
  const sharedSimulation = getSharedSimulation(game)

  const view = buildCanonicalDiagnosticsViewModel({
    ...sharedSimulation,
    game_state_realism: (
      game?.game_state_realism ||
      sharedSimulation?.game_state_realism
    ),
  })

  const status = view.status
  const bootstrap = view.bootstrapReadiness
  const coverage = view.coverage
  const monitoring = view.productionMonitoring
  const integrity = view.integrity
  const provenance = view.provenance

  return (
    <div>
      <div style={s.diagnosticHeader}>
        <div>
          <h3
            style={{
              margin: 0,
              color: '#e6edf3',
              fontSize: '21px',
            }}
          >
            Canonical Simulation Diagnostics
          </h3>

          <div
            style={{
              color: '#8b949e',
              fontSize: '13px',
              marginTop: '5px',
            }}
          >
            Coverage, integrity, realism, provenance, and
            production monitoring for the event-driven simulation.
          </div>
        </div>

        <DiagnosticStatusBadge state={status.state} />
      </div>

      {!view.hasCanonicalShadow ? (
        <div
          style={{
            ...s.metricCard,
            marginBottom: '16px',
            borderColor: '#30363d',
          }}
        >
          <div style={s.metricLabel}>
            Canonical Simulation
            <Tag tone="diagnostic">Shadow</Tag>
          </div>

          <h3
            style={{
              margin: '0 0 8px',
              color: '#e6edf3',
            }}
          >
            Not run for this payload
          </h3>

          <div
            style={{
              color: '#8b949e',
              fontSize: '13px',
              lineHeight: 1.6,
            }}
          >
            {status.availabilityReason}
            {' '}
            The displayed projections remain sourced from the
            legacy shared simulation.
          </div>

          <div style={{ marginTop: '12px' }}>
            <StatRow
              k="Authoritative Source"
              v={status.authoritativeSource}
              format="text"
            />
            <StatRow
              k="Legacy Model"
              v={status.modelVersion}
              format="text"
            />
          </div>

          {bootstrap.available ? (
            <div style={{ marginTop: '18px' }}>
              <div
                style={{
                  display: 'flex',
                  justifyContent: 'space-between',
                  alignItems: 'center',
                  flexWrap: 'wrap',
                  gap: '8px',
                  marginBottom: '10px',
                }}
              >
                <div style={s.metricLabel}>
                  Activation readiness
                </div>

                <span style={s.pill}>
                  {bootstrap.readyCount} of{' '}
                  {bootstrap.totalCount} ready
                </span>
              </div>

              <div style={s.featureGrid}>
                {bootstrap.items.map(item => (
                  <div
                    key={item.key}
                    style={s.featureRow}
                  >
                    <span
                      style={{
                        ...s.featureIcon,
                        color: (
                          item.ready
                            ? '#3fb950'
                            : '#f85149'
                        ),
                        background: (
                          item.ready
                            ? 'rgba(46, 160, 67, 0.15)'
                            : 'rgba(248, 81, 73, 0.15)'
                        ),
                      }}
                    >
                      {item.ready ? '✓' : '×'}
                    </span>

                    <div>
                      <div
                        style={{
                          color: '#e6edf3',
                          fontSize: '13px',
                          fontWeight: 750,
                        }}
                      >
                        {item.label}
                      </div>

                      {item.detail ? (
                        <div
                          style={{
                            color: '#8b949e',
                            fontSize: '11px',
                            marginTop: '2px',
                          }}
                        >
                          {item.detail}
                        </div>
                      ) : null}
                    </div>
                  </div>
                ))}
              </div>

              <div
                style={{
                  color: '#8b949e',
                  fontSize: '12px',
                  lineHeight: 1.5,
                  marginTop: '10px',
                }}
              >
                Diagnostic only. Readiness does not permit
                activation or change the authoritative projection
                source.
              </div>
            </div>
          ) : null}
        </div>
      ) : (
        <div style={s.splitGrid}>
          <GenericPanel
            title="Canonical Simulation"
            subtitle={
              status.modelVersion ||
              'Canonical shadow simulation'
            }
            tag={
              status.productionActive
                ? 'Production'
                : 'Shadow'
            }
            tagTone={
              status.productionActive
                ? 'success'
                : 'diagnostic'
            }
          >
            <StatRow
              k="Status"
              v={status.label || status.state}
              format="text"
            />
            <StatRow
              k="Canonical Output"
              v={
                status.canonicalAvailable
                  ? 'Available'
                  : 'Unavailable'
              }
              format="text"
            />
            <StatRow
              k="Authoritative Source"
              v={status.authoritativeSource}
              format="text"
            />
            <StatRow
              k="Legacy Simulations"
              v={status.legacySimulationCount}
              format="num"
            />
            <StatRow
              k="Canonical Simulations"
              v={status.canonicalSimulationCount}
              format="num"
            />
            <StatRow
              k="Schema"
              v={status.schemaVersion}
              format="text"
            />
          </GenericPanel>

          <GenericPanel title="Probability Coverage">
          <StatRow
            k="Total Resolutions"
            v={coverage.totalResolutions}
            format="num"
          />
          <StatRow
            k="Exact Resolution Rate"
            v={coverage.exactRate}
            format="pct"
          />
          <StatRow
            k="Global Profile Fallback Rate"
            v={coverage.fallbackRate}
            format="pct"
          />
          <StatRow
            k="Exact Resolutions"
            v={coverage.exactResolutions}
            format="num"
          />
          <StatRow
            k="Global Profile Resolutions"
            v={coverage.fallbackResolutions}
            format="num"
          />

          {coverage.tiers.length ? (
            <div style={{ marginTop: '10px' }}>
              <div style={s.metricLabel}>
                Resolution tiers
              </div>

              {coverage.tiers.map(item => (
                <StatRow
                  key={item.tier}
                  k={item.label}
                  v={item.count}
                  format="num"
                />
              ))}
            </div>
          ) : null}
          </GenericPanel>
        </div>
      )}


      {monitoring.available ? (
        <div style={{ marginTop: '18px' }}>
          <GenericPanel
            title="Production Baserunning Monitoring"
            subtitle="Frozen 100-game evidence window"
            tag={
              monitoring.settlementComplete
                ? 'Review ready'
                : 'Collecting'
            }
            tagTone={
              monitoring.settlementComplete
                ? 'success'
                : 'diagnostic'
            }
          >
            <StatRow
              k="Pregame Observation Progress"
              v={monitoring.progressRate}
              format="pct"
            />
            <StatRow
              k="Pregame Observations"
              v={monitoring.readyGameCount}
              format="num"
            />
            <StatRow
              k="Settlement Progress"
              v={monitoring.settlementProgressRate}
              format="pct"
            />
            <StatRow
              k="Settled Games"
              v={monitoring.settledGameCount}
              format="num"
            />
            <StatRow
              k="Target Settled Games"
              v={monitoring.settlementTargetGameCount}
              format="num"
            />
            <StatRow
              k="Settlements Remaining"
              v={monitoring.settlementRemainingGameCount}
              format="num"
            />
            <StatRow
              k="Current Snapshot Recorded"
              v={monitoring.recorded ? 'Yes' : 'No'}
              format="text"
            />
            {monitoring.settledGameCount > 0 ? (
              <>
                <StatRow
                  k="Projected Stolen Bases"
                  v={monitoring.projectedStolenBases}
                  format="num"
                />
                <StatRow
                  k="Observed Stolen Bases"
                  v={monitoring.observedStolenBases}
                  format="num"
                />
                <StatRow
                  k="Stolen Base Bias"
                  v={monitoring.stolenBaseBias}
                  format="num"
                />
                <StatRow
                  k="Stolen Base MAE"
                  v={monitoring.stolenBaseMae}
                  format="num"
                />
                <StatRow
                  k="Projected Caught Stealing"
                  v={monitoring.projectedCaughtStealing}
                  format="num"
                />
                <StatRow
                  k="Observed Caught Stealing"
                  v={monitoring.observedCaughtStealing}
                  format="num"
                />
                <StatRow
                  k="Caught Stealing Bias"
                  v={monitoring.caughtStealingBias}
                  format="num"
                />
                <StatRow
                  k="Caught Stealing MAE"
                  v={monitoring.caughtStealingMae}
                  format="num"
                />
                <StatRow
                  k="Attempt MAE"
                  v={monitoring.attemptMae}
                  format="num"
                />
              </>
            ) : null}
            <StatRow
              k="Transform Frozen"
              v={
                monitoring.transformFrozen
                  ? 'Yes'
                  : 'No'
              }
              format="text"
            />
            <StatRow
              k="Parameter Reselection"
              v={
                monitoring.parameterReselectionPermitted
                  ? 'Permitted'
                  : 'Locked'
              }
              format="text"
            />
          </GenericPanel>
        </div>
      ) : null}

      <h3 style={s.sectionTitle}>
        Game-State Realism
      </h3>

      <div style={s.featureGrid}>
        {view.realism.features.map(feature => (
          <RealismFeature
            key={feature.key}
            feature={feature}
          />
        ))}
      </div>

      {view.hasCanonicalShadow ? (
        <div style={s.splitGrid}>
          <GenericPanel title="Simulation Integrity">
          {integrity.metrics.map(metric => (
            <StatRow
              key={metric.key}
              k={metric.label}
              v={metric.value}
              format="pct"
            />
          ))}

          <StatRow
            k="Earned Run Status"
            v={integrity.earnedRunStatus}
            format="text"
          />
        </GenericPanel>

        <GenericPanel title="Input Provenance">
          <StatRow
            k="Game PK"
            v={provenance.gamePk}
            format="num"
          />
          <StatRow
            k="Provider"
            v={
              provenance.provider.name ||
              provenance.provider.identity
            }
            format="text"
          />
          <StatRow
            k="Provider Version"
            v={provenance.provider.version}
            format="text"
          />
          <StatRow
            k="Artifact ID"
            v={provenance.provider.artifactId}
            format="text"
          />
          <StatRow
            k="Exact Artifact Rows"
            v={provenance.exactArtifact.recordCount}
            format="num"
          />
          <StatRow
            k="Fallback Catalog Rows"
            v={provenance.fallbackCatalog.recordCount}
            format="num"
          />
          <StatRow
            k="Assembly Digest"
            v={shortDigest(provenance.assemblyDigest)}
            format="text"
          />
          <StatRow
            k="Exact Artifact Digest"
            v={shortDigest(provenance.exactArtifact.digest)}
            format="text"
          />
          <StatRow
            k="Fallback Catalog Digest"
            v={shortDigest(provenance.fallbackCatalog.digest)}
            format="text"
          />

          {provenance.fallbackPolicy.tiers.length ? (
            <StatRow
              k="Fallback Policy"
              v={provenance.fallbackPolicy.tiers
                .map(item => item.label)
                .join(' → ')}
              format="text"
            />
          ) : null}
          </GenericPanel>
        </div>
      ) : null}

      {view.warnings.length ? (
        <>
          <h3 style={s.sectionTitle}>Warnings</h3>

          {view.warnings.map(warning => (
            <div key={warning} style={s.warning}>
              {label(warning)}
            </div>
          ))}
        </>
      ) : null}

      {view.hasCanonicalShadow ? (
        <details style={s.details}>
          <summary style={s.summary}>
            Advanced: raw canonical payload
          </summary>

          <pre style={s.rawPayload}>
            {JSON.stringify(
              view.raw.canonicalShadow,
              null,
              2,
            )}
          </pre>
        </details>
      ) : null}
    </div>
  )
}

const TABS = [
  ['overview', 'Overview'],
  ['pitcher', 'Pitcher'],
  ['batter', 'Batter'],
  ['environment', 'Environment'],
  ['matchup', 'Matchup Analysis'],
  ['bullpen', 'Bullpen'],
  ['simulation', 'Simulation'],
  ['projections', 'Projections'],
  ['diagnostics', 'Diagnostics'],
]

function GameProjectionCard({ game }) {
  const [activeTab, setActiveTab] = useState('overview')
  const away = game?.teams?.away || {}
  const home = game?.teams?.home || {}
  const workspace = game?.workspace || {}

  const awayRunModel = findModel(away, 'Simulation: Away Team Run/Win Projection')
  const homeRunModel = findModel(home, 'Simulation: Home Team Run/Win Projection')
  const totalModel = findModel(away, 'Simulation: Game Total Projection') || findModel(home, 'Simulation: Game Total Projection')

  function renderTab() {
    if (activeTab === 'overview') return <OverviewTab game={game} awayRunModel={awayRunModel} homeRunModel={homeRunModel} totalModel={totalModel} />
    if (activeTab === 'pitcher') return <PitcherTab workspace={workspace} game={game} />
    if (activeTab === 'batter') return <BatterTab workspace={workspace} game={game} />
    if (activeTab === 'environment') return <EnvironmentTab workspace={workspace} game={game} />
    if (activeTab === 'matchup') return <MatchupTab workspace={workspace} />
    if (activeTab === 'bullpen') return <BullpenTab workspace={workspace} game={game} />
    if (activeTab === 'simulation') return <SimulationTab workspace={workspace} game={game} />
    if (activeTab === 'projections') return <ProjectionsTab game={game} />
    if (activeTab === 'diagnostics') return <DiagnosticsTab game={game} />
    return null
  }

  return (
    <article style={s.gameCard}>
      <div style={s.gameHeader}>
        <div>
          <h2 style={s.matchupTitle}>
            {game?.away_team?.name || away?.team_name || 'Away'} @ {game?.home_team?.name || home?.team_name || 'Home'}
          </h2>
          <div style={s.meta}>
            Game PK: {game?.game_pk || '—'} | Time: {game?.game_time || '—'} | Venue: {game?.venue || '—'} | Status: {game?.status || '—'}
          </div>
        </div>
        <div style={{ textAlign: 'right' }}>
          <span style={s.pill}>Simulation Workspace</span>
          <span style={s.pill}>{workspace?.metadata?.data_confidence || totalModel?.data_confidence || 'low'} confidence</span>
        </div>
      </div>

      <div style={s.tabBar}>
        {TABS.map(([id, name]) => (
          <button
            key={id}
            type="button"
            onClick={() => setActiveTab(id)}
            style={{
              ...s.tab,
              ...(activeTab === id ? s.tabActive : {}),
            }}
          >
            {name}
          </button>
        ))}
      </div>

      {(
        !awayRunModel ||
        !homeRunModel ||
        !totalModel
      ) && !Object.keys(getSharedDerivedSimulation(game) || {}).length ? (
        <div style={s.noData}>Simulation projections are not available for this game yet.</div>
      ) : renderTab()}
    </article>
  )
}




export default function ModelProjectionsPage() {
  const [date, setDate] = useState(today())
  const [payload, setPayload] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)

  useEffect(() => {
    let cancelled = false

    async function load() {
      setLoading(true)
      setError(null)

      try {
        const url = `${API}/models/projections?date=${date}`
        const res = await fetch(url, { cache: 'no-store' })
        const contentType = res.headers.get('content-type') || ''

        if (!res.ok) {
          const body = await res.text()
          throw new Error(`Request failed: ${res.status} ${res.statusText}. URL: ${url}. Response: ${body.slice(0, 300)}`)
        }

        if (!contentType.includes('application/json')) {
          const body = await res.text()
          throw new Error(`Expected JSON but received ${contentType || 'unknown content type'}. URL: ${url}. Response starts with: ${body.slice(0, 120)}`)
        }

        const json = await res.json()
        if (!cancelled) setPayload(json)
      } catch (err) {
        if (!cancelled) setError(err.message)
      } finally {
        if (!cancelled) setLoading(false)
      }
    }

    load()
    return () => { cancelled = true }
  }, [date])

  const games = useMemo(() => payload?.games || [], [payload])

  return (
    <div style={s.page}>
      <header style={s.header}>
        <h1 style={s.title}>Model Projections</h1>
        <p style={s.subtitle}>
          Full prediction workspace powered by pitcher profiles, offense profiles, environment, matchup analysis, bullpen modeling, and calibrated simulations.
        </p>
        <label style={{ color: '#c9d1d9' }}>
          Date:
          <input type="date" value={date} onChange={e => setDate(e.target.value)} style={s.dateInput} />
        </label>
      </header>

      {loading && <div style={s.card}>Loading projections...</div>}
      {error && <div style={{ ...s.card, borderColor: '#f85149', color: '#f85149' }}>{error}</div>}

      {payload?.source_notes?.length ? (
        <div style={s.card}>
          <strong>Source notes:</strong> {payload.source_notes.join(' ')}
        </div>
      ) : null}

      {!loading && payload && !games.length ? (
        <div style={s.card}>
          {payload?.data_status === 'not_ready'
            ? (payload?.message || 'Model projections are being prepared for this date.')
            : 'No games returned for this date.'}
        </div>
      ) : null}

      {games.map(game => (
        <GameProjectionCard key={game.game_pk || `${game.away_team?.name}-${game.home_team?.name}`} game={game} />
      ))}
    
</div>
  )
}

import React, { useState, useEffect } from 'react'
import { fmtPct, fmtDec, normalizeRate } from '../utils/formatters'
import { useParams, Link } from 'react-router-dom'

const API = import.meta.env.VITE_API_BASE_URL || ''

const s = {
  back: { color: '#58a6ff', textDecoration: 'none', fontSize: '13px', display: 'inline-block', marginBottom: '20px' },
  header: { background: '#161b22', border: '1px solid #30363d', borderRadius: '10px', padding: '20px 24px', marginBottom: '20px' },
  headerTop: { display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', flexWrap: 'wrap', gap: '12px', marginBottom: '16px' },
  teamsRow: { display: 'flex', alignItems: 'center', gap: '16px', flexWrap: 'wrap' },
  teamBlock: { textAlign: 'center' },
  teamName: { fontSize: '20px', fontWeight: '700', color: '#e6edf3' },
  pitcherName: { fontSize: '13px', color: '#8b949e', marginTop: '4px' },
  at: { fontSize: '20px', color: '#8b949e', fontWeight: '600', padding: '0 4px' },

  section: { marginBottom: '28px' },
  sectionTitle: { fontSize: '18px', fontWeight: '700', color: '#e6edf3', marginBottom: '16px', borderBottom: '1px solid #21262d', paddingBottom: '8px' },

  lineupGrid: { display: 'grid', gap: '16px' },
  batterCard: { background: '#161b22', border: '1px solid #30363d', borderRadius: '10px', overflow: 'hidden' },
  batterHeader: { padding: '12px 16px', background: '#0d1117', borderBottom: '1px solid #21262d', display: 'flex', justifyContent: 'space-between', alignItems: 'center' },
  batterName: { fontSize: '14px', fontWeight: '600', color: '#e6edf3' },
  batterOrder: { fontSize: '12px', color: '#8b949e', background: '#21262d', padding: '2px 8px', borderRadius: '4px' },

  h2hRow: { padding: '12px 16px', borderBottom: '1px solid #0d1117', display: 'flex', justifyContent: 'space-between', alignItems: 'center', fontSize: '13px' },
  h2hLabel: { color: '#8b949e' },
  h2hValue: { color: '#e6edf3', fontWeight: '600' },

  pitchTypeTable: { width: '100%', borderCollapse: 'collapse', fontSize: '12px' },
  th: { padding: '8px 12px', textAlign: 'left', color: '#8b949e', fontSize: '11px', textTransform: 'uppercase', letterSpacing: '0.4px', borderBottom: '1px solid #21262d', whiteSpace: 'nowrap' },
  thRight: { textAlign: 'right' },
  td: { padding: '8px 12px', borderBottom: '1px solid #0d1117', color: '#e6edf3', whiteSpace: 'nowrap' },
  tdRight: { textAlign: 'right' },
  tdMuted: { color: '#8b949e' },

  edgeScore: (score) => {
    let color = '#8b949e'
    if (score > 0.5) color = '#3fb950'
    else if (score > 0.2) color = '#d29922'
    else if (score < -0.5) color = '#f85149'
    return { color, fontWeight: '600' }
  },

  confidenceBadge: (conf) => ({
    display: 'inline-block',
    fontSize: '10px',
    padding: '1px 5px',
    borderRadius: '3px',
    background: conf >= 0.8 ? '#1f3a1f' : conf >= 0.5 ? '#2d3a1f' : '#3a2d1f',
    color: conf >= 0.8 ? '#3fb950' : conf >= 0.5 ? '#d29922' : '#f85149',
  }),

  callout: { background: '#1f3a1f', border: '1px solid #238636', borderRadius: '8px', padding: '12px 16px', marginBottom: '12px', fontSize: '13px', color: '#3fb950' },
  calloutTitle: { fontWeight: '600', marginBottom: '4px' },

  loader: { color: '#8b949e', padding: '48px', textAlign: 'center' },
  error: { color: '#f85149', padding: '24px', background: '#1f1116', borderRadius: '8px' },
}

export default function CompetitiveAnalysisPage() {
  const { game_pk } = useParams()
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  useEffect(() => {
    const fetchData = async () => {
      try {
        const res = await fetch(`${API}/matchup/${game_pk}/competitive`)
        if (!res.ok) throw new Error('Failed to load competitive analysis')
        const json = await res.json()
        setData(json)
      } catch (err) {
        setError(err.message)
      } finally {
        setLoading(false)
      }
    }
    fetchData()
  }, [game_pk])

  if (loading) return <div style={s.loader}>Loading competitive analysis...</div>
  if (error) return <div style={s.error}>{error}</div>
  if (!data) return <div style={s.error}>No data available</div>

  const renderLineupMatchups = (matchups) => {
    return (
      <div style={s.lineupGrid}>
        {matchups.map((m) => {
          const matchup = m.matchup
          const summary = matchup.summary

          return (
            <div key={m.batter_id} style={s.batterCard}>
              <div style={s.batterHeader}>
                <div>
                  <div style={s.batterName}>
                    <Link to={`/batter/${m.batter_id}`} style={{ color: '#58a6ff', textDecoration: 'none' }}>
                      Batter #{m.batter_id}
                    </Link>
                  </div>
                </div>
                <div style={s.batterOrder}>#{m.batting_order}</div>
              </div>

              {summary.biggest_edge && (
                <div style={{ ...s.callout, margin: '12px 16px 0' }}>
                  <div style={s.calloutTitle}>✓ Edge: {summary.biggest_edge}</div>
                  <div style={{ fontSize: '12px' }}>
                    Batter has advantage vs {summary.biggest_edge} pitches
                  </div>
                </div>
              )}

              {summary.biggest_weakness && (
                <div style={{ ...s.callout, background: '#3a1f1f', borderColor: '#f85149', color: '#f85149', margin: '12px 16px 0' }}>
                  <div style={s.calloutTitle}>⚠ Weakness: {summary.biggest_weakness}</div>
                  <div style={{ fontSize: '12px' }}>
                    Pitcher has advantage with {summary.biggest_weakness} pitches
                  </div>
                </div>
              )}

              <div style={{ padding: '12px 16px' }}>
                <div style={{ fontSize: '12px', fontWeight: '600', color: '#8b949e', marginBottom: '8px', textTransform: 'uppercase' }}>
                  Head-to-Head
                </div>
                <div style={s.h2hRow}>
                  <span style={s.h2hLabel}>PA</span>
                  <span style={s.h2hValue}>{matchup.head_to_head.pa}</span>
                </div>
                <div style={s.h2hRow}>
                  <span style={s.h2hLabel}>BA</span>
                  <span style={s.h2hValue}>{fmtDec(matchup.head_to_head.batting_avg, 3)}</span>
                </div>
                <div style={s.h2hRow}>
                  <span style={s.h2hLabel}>xwOBA</span>
                  <span style={s.h2hValue}>{fmtDec(matchup.head_to_head.xwoba, 3)}</span>
                </div>
              </div>

              <div style={{ padding: '12px 16px', borderTop: '1px solid #0d1117' }}>
                <div style={{ fontSize: '12px', fontWeight: '600', color: '#8b949e', marginBottom: '8px', textTransform: 'uppercase' }}>
                  Pitch Type Breakdown
                </div>
                <div style={{ overflowX: 'auto' }}>
                  <table style={s.pitchTypeTable}>
                    <thead>
                      <tr>
                        <th style={s.th}>Type</th>
                        <th style={{ ...s.th, ...s.thRight }}>Usage</th>
                        <th style={{ ...s.th, ...s.thRight }}>BA</th>
                        <th style={{ ...s.th, ...s.thRight }}>xwOBA</th>
                        <th style={{ ...s.th, ...s.thRight }}>Edge</th>
                        <th style={{ ...s.th, ...s.thRight }}>Conf</th>
                      </tr>
                    </thead>
                    <tbody>
                      {matchup.pitch_type_matrix.map((pt) => (
                        <tr key={pt.pitch_type}>
                          <td style={s.td}>{pt.pitch_type}</td>
                          <td style={{ ...s.td, ...s.tdRight, ...s.tdMuted }}>
                            {fmtPct(normalizeRate(pt.pitcher_usage_pct), 1)}
                          </td>
                          <td style={{ ...s.td, ...s.tdRight }}>
                            {fmtDec(pt.batter_vs_type.batting_avg, 3)}
                          </td>
                          <td style={{ ...s.td, ...s.tdRight }}>
                            {fmtDec(pt.batter_vs_type.xwoba, 3)}
                          </td>
                          <td style={{ ...s.td, ...s.tdRight, ...s.edgeScore(pt.edge_score) }}>
                            {pt.edge_score > 0 ? '+' : ''}{Number(pt.edge_score || 0).toFixed(2)}
                          </td>
                          <td style={{ ...s.td, ...s.tdRight }}>
                            <span style={s.confidenceBadge(pt.confidence)}>
                              {(pt.confidence * 100).toFixed(0)}%
                            </span>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            </div>
          )
        })}
      </div>
    )
  }

  return (
    <div style={{ maxWidth: '1200px', margin: '0 auto', padding: '32px 24px' }}>
      <Link to={`/matchup/${game_pk}`} style={s.back}>← Back to Matchup</Link>

      <div style={s.header}>
        <div style={s.headerTop}>
          <div style={s.teamsRow}>
            <div style={s.teamBlock}>
              <div style={s.teamName}>{data.away_team}</div>
              <div style={s.pitcherName}>vs Pitcher #{data.home_pitcher_id}</div>
            </div>
            <div style={s.at}>@</div>
            <div style={s.teamBlock}>
              <div style={s.teamName}>{data.home_team}</div>
              <div style={s.pitcherName}>vs Pitcher #{data.away_pitcher_id}</div>
            </div>
          </div>
        </div>
      </div>

      <div style={s.section}>
        <div style={s.sectionTitle}>{data.away_team} Lineup vs {data.home_team} Pitcher</div>
        {renderLineupMatchups(data.away_lineup_matchups)}
      </div>

      <div style={s.section}>
        <div style={s.sectionTitle}>{data.home_team} Lineup vs {data.away_team} Pitcher</div>
        {renderLineupMatchups(data.home_lineup_matchups)}
      </div>
    </div>
  )
}

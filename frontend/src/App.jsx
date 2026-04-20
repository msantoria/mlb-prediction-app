import React from 'react'
import { BrowserRouter, Routes, Route, NavLink } from 'react-router-dom'
import HomePage from './pages/HomePage'
import MatchupDetailPage from './pages/MatchupDetailPage'
import PitcherPage from './pages/PitcherPage'
import RollingPitcherPage from './pages/RollingPitcherPage'
import BatterPage from './pages/BatterPage'
import RollingBatterPage from './pages/RollingBatterPage'
import TeamPage from './pages/TeamPage'
import StandingsPage from './pages/StandingsPage'
import CompetitiveAnalysisPage from './pages/CompetitiveAnalysisPage'
import YesterdayTodayPage from './pages/YesterdayTodayPage'
import AIPage from './pages/AIPage'

const styles = {
  nav: {
    background: '#161b22',
    borderBottom: '1px solid #30363d',
    padding: '0 24px',
    display: 'flex',
    alignItems: 'center',
    gap: '28px',
    height: '56px',
    flexWrap: 'wrap',
  },
  brand: {
    fontSize: '18px',
    fontWeight: '700',
    color: '#58a6ff',
    textDecoration: 'none',
    letterSpacing: '-0.5px',
    marginRight: '4px',
  },
  link: {
    color: '#8b949e',
    textDecoration: 'none',
    fontSize: '14px',
    fontWeight: '500',
    padding: '4px 0',
    borderBottom: '2px solid transparent',
    transition: 'color 0.15s, border-color 0.15s',
  },
  activeLink: {
    color: '#e6edf3',
    borderBottomColor: '#58a6ff',
  },
  main: {
    maxWidth: '1200px',
    margin: '0 auto',
    padding: '32px 24px',
  },
}

const link = ({ isActive }) => ({ ...styles.link, ...(isActive ? styles.activeLink : {}) })

export default function App() {
  return (
    <BrowserRouter>
      <nav style={styles.nav}>
        <NavLink to="/" style={styles.brand}>⚾ MLB Predict</NavLink>
        <NavLink to="/" end style={link}>Matchups</NavLink>
        <NavLink to="/standings" style={link}>Standings</NavLink>
        <NavLink to="/pitcher" style={link}>Pitcher</NavLink>
        <NavLink to="/batter" style={link}>Batter</NavLink>
        <NavLink to="/team" style={link}>Team</NavLink>
        <NavLink to="/calendar" style={link}>Calendar</NavLink>
        <NavLink to="/ai" style={link}>AI</NavLink>
      </nav>
      <main style={styles.main}>
        <Routes>
          <Route path="/" element={<HomePage />} />
          <Route path="/matchup/:game_pk" element={<MatchupDetailPage />} />
          <Route path="/matchup/:game_pk/competitive" element={<CompetitiveAnalysisPage />} />
          <Route path="/standings" element={<StandingsPage />} />
          <Route path="/pitcher" element={<PitcherPage />} />
          <Route path="/pitcher/:id" element={<PitcherPage />} />
          <Route path="/pitcher/:id/rolling" element={<RollingPitcherPage />} />
          <Route path="/batter" element={<BatterPage />} />
          <Route path="/batter/:id" element={<BatterPage />} />
          <Route path="/batter/:id/rolling" element={<RollingBatterPage />} />
          <Route path="/team" element={<TeamPage />} />
          <Route path="/team/:id" element={<TeamPage />} />
          <Route path="/calendar" element={<YesterdayTodayPage />} />
          <Route path="/ai" element={<AIPage />} />
        </Routes>
      </main>
    </BrowserRouter>
  )
}

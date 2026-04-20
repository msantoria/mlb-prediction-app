# Data Architecture Audit (Current State)

## 1) Pull Layer (external APIs)
- MLB schedule, lineups, probable pitchers, weather: `mlb_app/app.py` (`/matchups`, `/matchup/{game_pk}`, `/matchup/{game_pk}/competitive`).
- MLB team/player endpoints for roster/search/standings: `mlb_app/app.py`.
- Savant arsenal leaderboard fallback for pitchers missing DB arsenal: `_fetch_live_pitch_arsenal` in `mlb_app/app.py`.

## 2) Storage Layer
- SQLAlchemy models + tables: `mlb_app/database.py`.
- Event-level source of truth for rolling pages and game logs: `StatcastEvent`.
- Aggregate tables for pitcher/batter/team/splits: accessed through `mlb_app/db_utils.py`.

## 3) Transform Layer
- Aggregate + fallback resolution helpers in `mlb_app/db_utils.py`.
- Matchup assembly + probabilities in `mlb_app/matchup_generator.py` and `mlb_app/scoring.py`.
- Competitive matchup matrix generation in `_build_competitive_matchup` (`mlb_app/app.py`).

## 4) Serve Layer
- API surface in `mlb_app/app.py`.
- Calendar/snapshot consistency endpoints:
  - `GET /matchups/calendar`
  - `POST /matchups/snapshot/{date_str}`
- AI data assistant endpoint:
  - `POST /ai/ask`

## 5) UI Consumption Map
- Daily matchups/date picker: `frontend/src/pages/HomePage.jsx`.
- Yesterday/Today/Tomorrow snapshot view: `frontend/src/pages/YesterdayTodayPage.jsx`.
- Matchup detail and batter-vs-arsenal matrix: `frontend/src/pages/MatchupDetailPage.jsx`.
- Pitcher profile and arsenal tables: `frontend/src/pages/PitcherPage.jsx`.
- Rolling pitcher diagnostics (event-level availability warnings): `frontend/src/pages/RollingPitcherPage.jsx`.
- AI question page: `frontend/src/pages/AIPage.jsx`.

## 6) Data Quality Risks Identified
- Percentage scale mismatch (fraction vs whole-number %) can inflate output values (e.g. 2500%).
- Missing pitcher arsenal rows reduce matchup matrix completeness.
- Missing event-level rows show blank rolling pages even if aggregate rows exist.

## 7) Fixes Implemented in this iteration
- Percentage normalization introduced at API and UI layers.
- Live arsenal fallback normalized and reused when DB is empty.
- Calendar snapshot endpoints provide stable yesterday/today snapshots.
- Rolling page error copy now explicitly explains data absence vs UI failure.

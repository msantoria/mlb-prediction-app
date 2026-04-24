# MLB Prediction App

A production full-stack MLB matchup and prediction engine. Data is ingested from the **MLB Stats API** and **Baseball Savant / Statcast**, stored in PostgreSQL, and served through a **FastAPI** backend to a **React 18** frontend hosted at [mlbgpt.com](https://mlbgpt.com).

---

## Current Known-Good Sandbox Checkpoint

The sandbox environment is confirmed working on branch `sandbox/contributor-analysis`.

Use this branch for enhancement work unless a change is explicitly approved for `main`.

### Sandbox services

| Service | Purpose | Expected behavior |
|---------|---------|-------------------|
| `backend-sandbox-production` | FastAPI backend/API | API endpoints return raw JSON |
| `frontend-sandbox-production` | React/Vite frontend | Browser routes render the UI |

Backend sandbox example:

```text
https://backend-sandbox-production.up.railway.app/matchup/824770
```

This endpoint should return raw JSON. That is correct.

Frontend sandbox example:

```text
https://frontend-sandbox-production.up.railway.app/matchup/824770
```

This route should render the React matchup detail page.

### Sandbox deployment configuration

The backend sandbox uses the root Railway config:

```text
railway.json
```

The frontend sandbox uses the frontend-specific Railway config:

```text
railway.frontend.json
```

The frontend sandbox service must use:

```text
Branch: sandbox/contributor-analysis
Root Directory: /frontend
Railway Config File: /railway.frontend.json
Build Command: npm install && npm run build
Start Command: npm run preview -- --host 0.0.0.0 --port $PORT
```

The frontend sandbox must also have this environment variable:

```text
VITE_API_BASE_URL=https://backend-sandbox-production.up.railway.app
```

The Vite preview host allowlist must include:

```text
frontend-sandbox-production.up.railway.app
```

That setting lives in:

```text
frontend/vite.config.js
```

### Sandbox rules

- Do not use the backend URL for visual UI testing. Backend routes are API routes and return JSON.
- Use the frontend sandbox URL for browser/UI testing.
- Do not touch `main` unless explicitly approved.
- Make small commits to `sandbox/contributor-analysis` and visually verify the frontend sandbox after deploy.
- If changing frontend routes or components, verify `npm run build` still passes.
- If changing backend routes, preserve existing endpoint names and JSON contracts unless a breaking change is explicitly approved.

### New-session starting prompt

Use this prompt when starting a fresh AI/code session:

```text
We are working on my repo: msantoria/mlb-prediction-app.

Current setup:
- Main branch is production. Do not touch main unless I explicitly say so.
- Sandbox branch is sandbox/contributor-analysis.
- Backend sandbox service is backend-sandbox-production on Railway. It returns raw JSON from API endpoints.
- Frontend sandbox service is frontend-sandbox-production on Railway. It renders the React UI.
- Frontend sandbox uses root directory /frontend.
- Frontend sandbox uses railway.frontend.json.
- Frontend sandbox VITE_API_BASE_URL points to https://backend-sandbox-production.up.railway.app.
- Vite preview allowedHosts includes frontend-sandbox-production.up.railway.app.
- MatchupDetailPage.jsx had a merge conflict and missing brace issue, but it is fixed now.
- The sandbox frontend and backend are both working.

Rules:
- Work only on sandbox/contributor-analysis unless I explicitly approve main.
- Do not rewrite working backend or frontend logic unless needed.
- Make small safe commits.
- After any frontend change, make sure npm build would pass.
- After any backend/API change, preserve existing endpoints and JSON contracts.
- Prefer incremental enhancements over big rewrites.
- Before editing, inspect the current files in the repo and summarize the planned change.
```

---

## Architecture — Two Separate Railway Services

This project deploys as **two independent Railway services**. Understanding this is mandatory before contributing.

| Service | Builder | Role | Domain |
|---------|---------|------|--------|
| `mlb-prediction-app` | Dockerfile | FastAPI backend + API | `*.up.railway.app` |
| Frontend | Railpack/Node/Vite | React SPA | `mlbgpt.com` / frontend Railway domain |

The frontend calls the backend via `VITE_API_BASE_URL` (set in Railway env vars at build time). If `VITE_API_BASE_URL` is unset, API calls fall back to relative URLs, which **breaks** when the frontend service has no API routes.

### CORS Policy

The backend (`mlb_app/app.py`) allows:
- `https://mlbgpt.com` and `https://www.mlbgpt.com`
- `https://*.up.railway.app` via `allow_origin_regex`

**Never restrict CORS to only the custom domain.** The Railway service URL must always be allowed.

---

## Stack

| Layer | Technology |
|-------|-----------|
| Backend | Python 3.11, FastAPI, Uvicorn |
| ORM / DB | SQLAlchemy 2.x, PostgreSQL (SQLite fallback for local) |
| Data | pybaseball (Statcast), MLB Stats API (`statsapi.mlb.com`) |
| Frontend | React 18, Vite, React Router 6 |
| Deployment | Docker (backend), Railpack/Node/Vite (frontend), Railway, GitHub Actions |

---

## Repository Structure

```
mlb-prediction-app/
├── mlb_app/                    # Core Python package
│   ├── app.py                  # FastAPI application — all API routes
│   ├── database.py             # SQLAlchemy ORM models
│   ├── db_utils.py             # Database query helpers
│   ├── etl.py                  # ETL pipeline (Statcast, arsenal, splits → DB)
│   ├── matchup_generator.py    # Assembles game-level feature vectors from DB
│   ├── scoring.py              # Matchup scoring engine / win probability
│   ├── aggregation.py          # Rolling-window and seasonal stat aggregation
│   ├── data_ingestion.py       # MLB Stats API wrappers (schedule, standings, splits)
│   ├── statcast_utils.py       # Statcast retrieval and aggregation (pybaseball)
│   ├── pitcher_analysis.py     # Pitcher metric retrieval helpers
│   ├── batter_analysis.py      # Batter metric retrieval helpers
│   ├── player_splits.py        # Player splits vs L/R pitching
│   ├── analysis_pipeline.py    # Matchup analysis orchestration
│   └── hitter_profile.py       # Hitter profile scaffold (in progress)
├── frontend/
│   ├── src/
│   │   ├── App.jsx             # Root component + routing
│   │   ├── pages/
│   │   │   ├── HomePage.jsx                # Daily matchups
│   │   │   ├── MatchupDetailPage.jsx       # Single-game drill-down
│   │   │   ├── CompetitiveAnalysisPage.jsx # Lineup-vs-pitcher matrix
│   │   │   ├── PitcherPage.jsx             # Pitcher profile + arsenal
│   │   │   ├── RollingPitcherPage.jsx      # Pitcher rolling stats (L15G–L150G)
│   │   │   ├── BatterPage.jsx              # Batter profile + platoon splits
│   │   │   ├── RollingBatterPage.jsx       # Batter rolling stats (L10–L1000 ABs)
│   │   │   ├── TeamPage.jsx                # Team vsL/vsR splits + standings
│   │   │   ├── StandingsPage.jsx           # AL/NL standings
│   │   │   ├── YesterdayTodayPage.jsx      # Calendar view (yesterday/today/tomorrow)
│   │   │   └── AIPage.jsx                  # Lightweight MLB Q&A assistant
│   │   └── utils/
│   │       └── formatters.js   # Shared number/percent/date formatters
│   ├── index.html
│   ├── vite.config.js          # Vite dev/preview config, including Railway preview allowed hosts
│   └── package.json
├── main.py                     # Uvicorn entry point for Railway
├── seed_db.py                  # Bootstrap: loads last N days of Statcast into DB
├── generate_matchups.py        # CLI: prints matchups JSON for a given date
├── Dockerfile                  # Multi-stage build (Python 3.11 + Node 20)
├── railway.json                # Railway backend deploy config
├── railway.frontend.json       # Railway frontend deploy config for sandbox/frontend service
├── CLAUDE.md                   # Architecture notes for AI-assisted development
└── requirements.txt            # Python dependencies
```

---

## API Endpoints

All endpoints are served by `mlb_app/app.py`.

### Health
| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/health` | Health check |

### Matchups / Schedule
| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/matchups` | List games for a date (`?date=YYYY-MM-DD`) |
| `GET` | `/matchups/calendar` | Yesterday / today / tomorrow snapshot |
| `POST` | `/matchups/snapshot/{date_str}` | Cache matchups for a specific date |
| `GET` | `/matchup/{game_pk}` | Full game detail (pitchers, lineups, splits, game log) |
| `GET` | `/matchup/{game_pk}/competitive` | Lineup-level competitive matchup matrix |

### Pitchers
| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/pitcher/{id}` | Aggregate stats + pitch arsenal |
| `GET` | `/pitcher/{id}/rolling` | Rolling stats (L15G–L150G) |
| `GET` | `/pitcher/{id}/game-log` | Recent game-by-game appearances |

### Batters
| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/batter/{id}` | Aggregate stats + platoon splits |
| `GET` | `/batter/{id}/rolling` | Rolling stats (L10, L25, L50, L100, L200, L400, L1000 ABs) |
| `GET` | `/batter/{id}/splits` | Multi-season vsL/vsR splits |
| `GET` | `/batter/{id}/at-bats` | Chronological Statcast-level at-bat log |

### Teams / Standings / Rosters
| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/standings` | AL/NL standings |
| `GET` | `/team/{team_id}` | Team splits (vsL/vsR) + standings |
| `GET` | `/team/{team_id}/roster` | Full active roster |
| `GET` | `/lineup/{team_id}` | Day-of lineup (`?date=YYYY-MM-DD`) |

### Players
| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/players/search` | Search by name (`?name=...`) |
| `GET` | `/players/all` | All active MLB players (`?season=YYYY`) |

### AI / Prediction
| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/ai/ask` | Lightweight MLB data Q&A assistant |
| `POST` | `/predict` | Score a specific pitcher vs batter matchup |

---

## Local Development

### Backend

```bash
# 1. Create and activate a virtual environment
python -m venv .venv
source .venv/bin/activate

# 2. Install dependencies
pip install -r requirements.txt

# 3. Set environment variables
#    DATABASE_URL  — PostgreSQL connection string (omit to use SQLite fallback)
#    VITE_API_BASE_URL — only needed when building the frontend
export DATABASE_URL=postgresql://user:pass@localhost:5432/mlb

# 4. Seed the database with recent Statcast data
python seed_db.py

# 5. Start the API server
uvicorn mlb_app.app:app --reload --port 8000
```

The API will be available at `http://localhost:8000`. Interactive docs at `http://localhost:8000/docs`.

### Frontend

```bash
cd frontend

# Install Node dependencies
npm install

# Set the API base URL to point at your local backend
echo "VITE_API_BASE_URL=http://localhost:8000" > .env.local

# Start the dev server
npm run dev
```

The frontend dev server runs at `http://localhost:5173`.

To test the production-style Vite preview server locally:

```bash
cd frontend
npm run build
npm run preview -- --host 0.0.0.0 --port 4173
```

---

## Deployment

Pushing to `main` triggers production deploys. Sandbox work should happen on `sandbox/contributor-analysis` first.

### Production

1. **Backend** — GitHub Actions runs `railway up --detach --service mlb-prediction-app`, which builds and deploys the Dockerfile.
2. **Frontend** — Railway's frontend service detects Node/Vite and deploys the React SPA automatically.

The `VITE_API_BASE_URL` environment variable **must** be set in the Railway frontend service's env vars before deploying, or the frontend will break.

### Sandbox

The sandbox has separate backend and frontend Railway services.

Backend sandbox:

```text
backend-sandbox-production
```

Frontend sandbox:

```text
frontend-sandbox-production
```

For visual testing, use the frontend sandbox URL. For API verification, use the backend sandbox URL.

---

## Contributing

Before opening a PR, read this entire README and `CLAUDE.md`.

### Branch naming

Use descriptive prefixes:

```
feature/<short-description>
fix/<short-description>
refactor/<short-description>
```

### Code conventions

- **Python**: Follow the existing module structure. New backend modules go in `mlb_app/`. Keep logic out of `app.py` — routes should call helpers, not contain business logic inline.
- **Comments**: Only add a comment when the *why* is non-obvious. Do not write docstrings that restate what the function name already says. Do not write multi-paragraph docstrings for placeholder or scaffold code.
- **Parameters**: Do not define function parameters that are not used. If a function is a scaffold, either omit the parameter until it is needed or use it.
- **No dead code**: Do not merge modules or functions that are entirely placeholder (returning `None` for every field). At minimum, implement enough logic to be testable.
- **Tests**: Every new module must include a corresponding test file in `tests/`. There is currently no test suite — new contributions are expected to establish one.
- **Trailing newline**: All Python files must end with a newline character.

### PR checklist

- [ ] New Python files end with a trailing newline
- [ ] No unused function parameters
- [ ] No overly verbose docstrings on scaffold/placeholder code
- [ ] A test file exists for every new module (`tests/test_<module>.py`)
- [ ] If touching `mlb_app/app.py` CORS config, review `CLAUDE.md` first
- [ ] If touching the frontend build, `railway.frontend.json`, `vite.config.js`, or `VITE_API_BASE_URL`, verify the two-service deploy still works

---

## Data Sources

| Source | Used For |
|--------|---------|
| [MLB Stats API](https://statsapi.mlb.com) | Schedule, standings, rosters, lineups, player splits |
| [Baseball Savant / Statcast](https://baseballsavant.mlb.com) | Pitch velocity, spin rate, exit velocity, barrel rate, pitch arsenal CSVs |
| [pybaseball](https://github.com/jldbc/pybaseball) | Python wrapper for Statcast bulk downloads |

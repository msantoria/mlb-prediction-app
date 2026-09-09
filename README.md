# MLBGPT

MLBGPT is a production full-stack MLB intelligence, matchup, projection, simulation, reporting, and sportsbook-analysis platform hosted at [mlbgpt.com](https://mlbgpt.com).

It combines official MLB data, Statcast-derived data, persisted analytical datasets, internal model/simulation outputs, and selected sportsbook feeds behind a FastAPI backend and React frontend.

> **Start here for architecture work:** [`docs/MLBGPT_SYSTEM_REFERENCE.md`](docs/MLBGPT_SYSTEM_REFERENCE.md)
>
> That file is the current system-level contract for source authority, Model Projections, My Dashboard, Railway refresh behavior, failure semantics, and invariants future coding agents should preserve.

---

## Production topology

MLBGPT deploys as **two independent Railway services**.

| Service | Runtime | Responsibility |
| --- | --- | --- |
| Backend | Docker, Python 3.11, Uvicorn/FastAPI | APIs, PostgreSQL access, data/model services, simulations, reports, refresh jobs |
| Frontend | Node/Railpack, React 18, Vite | `mlbgpt.com` single-page application |

Two variables are especially important:

- `DATABASE_URL` — backend/refresh-job PostgreSQL connection.
- `VITE_API_BASE_URL` — frontend **build-time** FastAPI base URL.

The frontend service does not own FastAPI routes. A frontend build with an incorrect API base can fail even when both Railway deployments are individually healthy.

Production PostgreSQL is authoritative persistence. SQLite fallback exists for local development and focused tests only.

---

## Current product surfaces

| Surface | Frontend route | Primary backend ownership |
| --- | --- | --- |
| Daily Matchups | `/` | `mlb_app/app.py`, `mlb_app/matchup_generator.py` |
| Matchup Detail | `/matchup/:game_pk` | matchup routes/analysis |
| Competitive Analysis | `/matchup/:game_pk/competitive` | competitive matchup contract |
| Daily Odds | `/daily-odds` | `mlb_app/daily_odds_routes.py` |
| Bet105 Sportsbook | `/sportsbook/bet105` | `mlb_app/sportsbook_routes.py` and provider modules |
| Model Projections | `/models/projections` | `mlb_app/model_projection_routes.py`, `mlb_app/model_projections.py` |
| My Dashboard | `/my-dashboard` | `mlb_app/my_dashboard_routes.py` and dashboard modules |
| Control Center | `/admin` | `mlb_app/admin_routes.py` and access-control modules |
| AI Data Assistant | `/ai-data-assistant` | `mlb_app/ai_data_assistant_routes.py` |
| Model Tracker | `/model-tracker` | `mlb_app/model_tracker_routes.py` |
| News | `/news` | `mlb_app/news_routes.py` |
| Live Games | `/live`, `/live/:game_pk` | live routes/services |
| Pitchers | `/pitcher`, `/pitcher/:id` | pitcher routes/profile stores |
| Batters | `/batter`, `/batter/:id` | `mlb_app/batter_routes.py` |
| Teams | `/team`, `/team/:id` | team routes |
| Standings | `/standings` | standings route |
| Calendar | `/calendar` | matchup/calendar routes |

The Batter frontend is intentionally feature-gated by `VITE_ENABLE_BATTER_PAGE`. Current `frontend/src/App.jsx` says to keep it disabled until the leaderboard endpoint is verified stable in production.

---

## Golden matchup path

The daily matchup analyzer is a core production path. Preserve it unless direct regression evidence shows that a change is required.

Expected flow:

1. Load the official MLB schedule for an explicit `YYYY-MM-DD` date.
2. Resolve `game_pk`, teams, IDs, status, and probable/assigned starters.
3. Join persisted historical, rolling, split, arsenal, and Statcast-derived data.
4. Build backend-owned matchup records.
5. Preserve missingness when an upstream input is unavailable.
6. Return a valid empty slate when no games are scheduled.

Primary implementation:

- `mlb_app/matchup_generator.py`
- `generate_matchups_for_date(...)`
- `GET /matchups?date=YYYY-MM-DD`
- `GET /matchup/{game_pk}`
- `GET /matchup/{game_pk}/competitive`
- `frontend/src/pages/HomePage.jsx`
- `frontend/src/pages/MatchupDetailPage.jsx`

Do not invent teams, pitchers, IDs, odds, model probabilities, or statistics in frontend fallback code.

---

## Model Projections: September 2026 architecture

The current Model Projections workspace includes a canonical confirmed/projected-lineup simulation chain with explicit readiness and provenance.

The important sequence is:

```text
confirmed/projected lineup discovery
        ↓
canonical selected-lineup contract
        ↓
projected hitter-profile materialization when needed
        ↓
exact-artifact/readiness checks
        ↓
canonical shadow execution
        ↓
versioned canonical outcomes
        ↓
shared canonical Simulation/Overview view model
```

Key rules:

- Complete confirmed batting orders are preferred.
- Complete projected orders are used only under the selected-lineup contract when confirmed data is absent.
- Partial/mixed/duplicate lineup input fails closed rather than creating a synthetic hybrid order.
- Projected player-level offense contexts replace the original contexts only when **both teams** materialize nine usable profiles.
- UI claims about canonical execution require explicit same-run evidence; they are not inferred from player counts.
- Canonical outcomes are not filled with legacy values when canonical evidence is incomplete.
- Model Projection workspace artifacts currently use `model_projection_workspace_v7`; the version prevents pre-outcome cached artifacts from masquerading as current completed canonical payloads.
- Model authority/fallback is explicit in diagnostics. Do not infer authority merely because canonical results are visible.

Primary modules include:

- `mlb_app/simulation/shadow/selected_lineup.py`
- `mlb_app/simulation/shadow/projected_lineup_discovery.py`
- `mlb_app/simulation/shadow/production_lineup_selection.py`
- `mlb_app/simulation/shadow/selected_lineup_profile_materialization.py`
- `mlb_app/simulation/shadow/integration.py`
- `mlb_app/model_projections.py`
- `mlb_app/model_projection_routes.py`
- `frontend/src/lib/canonicalSimulationViewModel.mjs`
- `frontend/src/pages/ModelProjectionsPage.jsx`

See [`docs/MLBGPT_SYSTEM_REFERENCE.md`](docs/MLBGPT_SYSTEM_REFERENCE.md) for the full chain and merged PR history (#1380–#1386).

---

## My Dashboard

My Dashboard is a signed-in report workspace with server-owned report contracts, filters, sorting, pagination, saved reports, Query Studio capability controls, canonical player populations, and complete CSV export.

### Canonical population

Core canonical tables include:

- `dashboard_players`
- `dashboard_player_snapshots`
- `dashboard_player_current`
- `dashboard_projection_runs`

Canonical identity is MLBAM-ID based. Name-only identity matching must not be introduced as a replacement.

The canonical refresh requires a verified MLB team/roster source set. A failed replacement refresh does **not** erase the previous good `dashboard_player_current` projection. That is why report/export data can remain available during a transient scheduled-refresh failure.

Operational details: [`docs/my_dashboard_canonical_production_runbook.md`](docs/my_dashboard_canonical_production_runbook.md)

### All-row CSV export

Report Builder and Query Studio all-row exports are server-streamed. The browser makes one authenticated download request while the backend pages through the result set and streams CSV rows.

Report Builder route:

```text
POST /my-dashboard/reports/export.csv
```

Do not reintroduce browser-side sequential page collection without a demonstrated requirement.

### Authentication

My Dashboard supports:

- email/password;
- Google OAuth;
- GitHub OAuth;
- one-time password recovery through configured SMTP.

Operational configuration: [`docs/my_dashboard_authentication.md`](docs/my_dashboard_authentication.md)

---

## Data sources

| Source | Use |
| --- | --- |
| MLB Stats API | schedule, game/team IDs, probable pitchers, rosters, lineups, standings, official player data |
| Baseball Savant / Statcast | pitch and batted-ball events, arsenals, velocity/movement, xwOBA/xBA, hard-hit/barrel data |
| `pybaseball` | supported bulk Statcast/Savant retrieval |
| PostgreSQL | durable events, aggregates, canonical dashboard rows, model/tracking data, artifacts |
| KIBL Bet105 feed | Bet105 events, markets, selections, prices |
| Other configured sportsbook providers | provider-specific event/market/price data |
| Internal model/simulation modules | matchup probabilities, expected runs, projections, diagnostics, simulations |

### Missing-data rule

Never fabricate provider or model values. Missing, `null`, unavailable, and zero are distinct states.

A model-only signal is not a priced sportsbook edge unless a real market/price is matched.

---

## Scheduled refresh worker

Primary entry point:

```text
scripts/run_refresh_job.py
```

The worker separates fast user-facing refresh work from optional heavy recovery/backfill work.

Important current toggles:

| Variable | Default |
| --- | ---: |
| `RUN_FAST_MATCHUP_REFRESH` | `1` |
| `WARM_MATCHUP_SNAPSHOTS` | `0` |
| `REFRESH_MATCHUPS_FIRST` | `1` |
| `CLEAR_AI_CACHE_AFTER_REFRESH` | `1` |
| `RUN_STATCAST_ETL` | `0` |
| `RUN_HITTER_STATCAST_BACKFILL` | `0` |
| `RUN_HITTING_MATCHUPS_REFRESH` | `1` |
| `RUN_CANONICAL_DASHBOARD_REFRESH` | `1` |
| `REFRESH_ETL_BACKFILL_DAYS` | `1` |

Worker HTTP retry controls include:

- `REFRESH_TIMEOUT_SECONDS`
- `REFRESH_MAX_ATTEMPTS`
- `REFRESH_RETRY_BACKOFF_SECONDS`

Important: worker-level retries do not automatically wrap every lower-level HTTP request inside imported Python modules.

AI Data Assistant cache clearing is best-effort. Diagnose cron failures by identifying the first fatal application-stage exception rather than treating every warning as the root cause.

---

## Date handling

Public dates use `YYYY-MM-DD`.

Explicit user dates must be preserved. Implicit “today”/default-slate/cron dates must use the intended MLB business-date logic rather than raw Railway/UTC container date.

Do not introduce unqualified `datetime.date.today()` into production slate-selection code without verifying the business-timezone contract.

---

## Local development

### Backend

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Optional for production-like local persistence:
export DATABASE_URL=postgresql://user:pass@localhost:5432/mlb

uvicorn mlb_app.app:app --reload --port 8000
```

### Frontend

```bash
cd frontend
npm install
echo "VITE_API_BASE_URL=http://localhost:8000" > .env.local
npm run dev
```

Default Vite development URL: `http://localhost:5173`.

---

## Validation before merge

Run the checks relevant to the changed contract.

```bash
python -m compileall mlb_app
python -c "from mlb_app.app import app"
pytest

cd frontend
npm install
npm run build
```

For production-path work, validate a real response contract for an explicit MLB date. HTTP 200 by itself is not sufficient evidence.

Suggested smoke matrix:

1. `GET /health`.
2. Matchups for an explicit date.
3. One chart-rich Matchup Detail render.
4. Model Projections for the same date.
5. Canonical projection diagnostics/outcomes when applicable.
6. Daily Odds with and without provider prices.
7. My Dashboard query and all-row export.
8. My Dashboard authentication if auth changed.
9. AI Data Assistant if assistant/cache code changed.
10. Refresh-worker logs/freshness evidence if refresh code changed.

---

## Engineering invariants

Before changing production behavior, read [`docs/MLBGPT_SYSTEM_REFERENCE.md`](docs/MLBGPT_SYSTEM_REFERENCE.md). In particular:

- keep missing values distinct from zero;
- preserve MLBAM-ID canonical identity;
- do not partially promote incomplete canonical dashboard data;
- do not mix blocked confirmed/projected lineup inputs;
- do not relabel legacy simulation values as canonical values;
- do not mix canonical and legacy fields inside one claimed canonical result;
- preserve artifact/cache version boundaries;
- keep session-specific dashboard data correctly scoped;
- preserve MLB business-date handling;
- prefer narrow fixes over broad rewrites of working production paths.

---

## Specialized documentation

- [`docs/MLBGPT_SYSTEM_REFERENCE.md`](docs/MLBGPT_SYSTEM_REFERENCE.md) — current architecture, authority, safety, operations, and important PR chronology.
- [`docs/my_dashboard_canonical_production_runbook.md`](docs/my_dashboard_canonical_production_runbook.md) — canonical dashboard refresh/status/rollback.
- [`docs/my_dashboard_authentication.md`](docs/my_dashboard_authentication.md) — Google/GitHub OAuth and password recovery.
- [`docs/canonical_model_engine_v2_summary.md`](docs/canonical_model_engine_v2_summary.md) — deeper canonical model-engine design history; verify against current code before treating historical statements as active authority.
- [`docs/canonical_baserunning_production_monitoring.md`](docs/canonical_baserunning_production_monitoring.md) — baserunning monitoring detail.

The `docs/` directory also contains task-specific audits, probes, plans, and historical implementation notes. Those are useful evidence but are not automatically current production architecture.

---

## Documentation rule

Architecture-changing PRs should update documentation when they change route ownership, source/model authority, artifact versions, database promotion semantics, refresh order, authentication, environment-variable ownership, or production validation requirements.

For the definitive maintenance procedure, see the final section of [`docs/MLBGPT_SYSTEM_REFERENCE.md`](docs/MLBGPT_SYSTEM_REFERENCE.md).

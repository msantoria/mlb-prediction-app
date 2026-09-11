# MLBGPT System Reference

> **Purpose:** authoritative orientation for engineers and coding agents working in this repository.
>
> **Verified against:** `main` at `7e261594d84ba44a517174df85ea7320c6bb7280` on 2026-09-09.
>
> **Rule:** this document explains the intended production contracts, but executable code on the current `main` branch is the final source of truth. If this file and current code disagree, verify the code and update this file in the same PR.

MLBGPT is a production full-stack MLB intelligence, matchup, reporting, simulation, and sportsbook-analysis application hosted at `mlbgpt.com`. It combines official MLB data, Statcast-derived data, persisted analytical datasets, internal model outputs, and selected sportsbook feeds behind a FastAPI backend and React frontend.

This file is intentionally broader than the root `README.md`. The root README is the quick-start and deployment entry point. This file is the current architecture and operating contract.

---

## 1. Source-of-truth hierarchy

When investigating or changing behavior, use this order:

1. Current code on `main`.
2. Tests that assert the current contract.
3. Current production runbooks under `docs/`.
4. This system reference.
5. Merged PR descriptions, for architectural intent and historical safety boundaries.
6. Old plans, audit scripts, probe notes, and archived implementation notes.

Do **not** treat an old PR body, plan file, issue description, or stale Markdown file as proof that a feature is currently active.

Open or unmerged PRs are not production behavior. If this document mentions future work, it must be labeled explicitly as unmerged or planned.

---

## 2. Deployment topology

Production uses two independent Railway services.

| Service | Runtime | Responsibility |
| --- | --- | --- |
| Backend | Docker, Python 3.11, Uvicorn/FastAPI | APIs, database access, data contracts, refreshes, simulations, model/report routes |
| Frontend | Node/Railpack, React 18, Vite | `mlbgpt.com` single-page application |

The frontend calls the backend through `VITE_API_BASE_URL`, which is a **frontend build-time** variable. The frontend service does not own FastAPI routes, so a missing or incorrect API base can break production even when both Railway deployments are individually healthy.

The backend uses `DATABASE_URL`. Production uses PostgreSQL. SQLite fallback is for local development and tests and must not be treated as production persistence.

### CORS invariant

The backend must allow the live custom domains and the required Railway service domains. Do not narrow CORS to only `mlbgpt.com` without verifying internal/deployment traffic.

### Production acceptance invariant

A successful Railway deployment does not prove that MLBGPT is healthy. Production acceptance requires application-level checks: current slate date, API connectivity, database connectivity, required refreshes, current artifacts, provider state, and representative product renders.

---

## 3. Primary product surfaces

The current application includes these major surfaces.

| Surface | Frontend route | Primary backend ownership |
| --- | --- | --- |
| Daily Matchups | `/` | `mlb_app/app.py`, `mlb_app/matchup_generator.py` |
| Matchup Detail | `/matchup/:game_pk` | matchup routes and analysis modules |
| Competitive Analysis | `/matchup/:game_pk/competitive` | competitive matchup contract |
| Daily Odds | `/daily-odds` | `mlb_app/daily_odds_routes.py` |
| Bet105 Sportsbook | `/sportsbook/bet105` | `mlb_app/sportsbook_routes.py` and provider modules |
| Model Projections | `/models/projections` | `mlb_app/model_projection_routes.py`, `mlb_app/model_projections.py`, simulation modules |
| My Dashboard | `/my-dashboard` | `mlb_app/my_dashboard_routes.py` and dashboard modules |
| Control Center | `/admin` | `mlb_app/admin_routes.py`, access-control modules |
| AI Data Assistant | `/ai-data-assistant` | `mlb_app/ai_data_assistant_routes.py` |
| Model Tracker | `/model-tracker` | `mlb_app/model_tracker_routes.py` |
| News | `/news` | `mlb_app/news_routes.py` |
| Live Games | `/live`, `/live/:game_pk` | live routes and live data services |
| Pitchers | `/pitcher`, `/pitcher/:id` | pitcher routes/profile stores |
| Batters | `/batter`, `/batter/:id` | `mlb_app/batter_routes.py` and batter contracts |
| Teams | `/team`, `/team/:id` | team routes |
| Standings | `/standings` | standings route |
| Calendar | `/calendar` | matchup/calendar routes |

Before changing a route, verify both the React route registration and the FastAPI decorator/router registration. Do not infer route existence from filenames.

---

## 4. Golden daily matchup path

The daily matchup analyzer is a core production path and should not be broadly rewritten without regression evidence.

Expected sequence:

1. Load the official MLB schedule for the requested `YYYY-MM-DD` date.
2. Resolve `game_pk`, teams, team IDs, status, and probable/assigned starters.
3. Join persisted historical, rolling, split, arsenal, and Statcast-derived data.
4. Build backend-owned matchup records.
5. Preserve missingness when upstream information is unavailable.
6. Return a valid empty slate when there are no games.

Primary code:

- `mlb_app/matchup_generator.py`
- `generate_matchups_for_date(...)`
- `GET /matchups?date=YYYY-MM-DD`
- `GET /matchup/{game_pk}`
- `GET /matchup/{game_pk}/competitive`
- `frontend/src/pages/HomePage.jsx`
- `frontend/src/pages/MatchupDetailPage.jsx`
- `frontend/src/pages/CompetitiveAnalysisPage.jsx`

### Matchup contract rule

The backend owns matchup identity. Frontend code must not invent missing teams, starters, IDs, lines, probabilities, or statistics.

---

## 5. Data-source authority

MLBGPT uses multiple data families. Their roles must remain distinguishable.

| Source | Primary role |
| --- | --- |
| MLB Stats API | schedule, game IDs, teams, probable pitchers, active rosters, lineups, standings, official player information/statistics |
| Baseball Savant / Statcast | pitch events, batted-ball events, pitch arsenals, velocity/movement, xwOBA/xBA, hard-hit/barrel metrics |
| `pybaseball` | supported bulk Statcast/Savant retrieval paths |
| PostgreSQL | durable event data, aggregates, canonical dashboard rows, model/report state, tracking data, artifacts |
| KIBL Bet105 feed | Bet105 events/markets/selections/prices |
| Other configured odds providers | provider-specific sportsbook event/price data |
| Internal model/simulation modules | model probabilities, expected runs, projections, diagnostics, simulations |

### Missing-data invariant

`null`, missing, unavailable, and zero are different states. Do not coerce missing provider/model data into a plausible zero or fabricated value.

A model-only signal is not a sportsbook-priced edge unless a real market/price has been matched.

---

## 6. Model Projections: current canonical simulation chain

The September 2026 work added a canonical confirmed/projected-lineup simulation chain while preserving explicit safety boundaries.

### 6.1 Canonical selected-lineup contract

Primary module:

- `mlb_app/simulation/shadow/selected_lineup.py`

The selected-lineup contract is ordered and immutable. Selection is order-sensitive and records sanitized provenance/digest information.

Selection rules:

1. Prefer a **complete confirmed batting order**.
2. Use a **complete projected batting order only when confirmed data is absent**.
3. Do not mix a confirmed side with projected replacements because confirmed input is partial.
4. Reject partial, duplicate, malformed, or otherwise invalid lineup candidates.

This fail-closed behavior was introduced in merged PR #1380.

### 6.2 Projected-lineup discovery

Primary module:

- `mlb_app/simulation/shadow/projected_lineup_discovery.py`

The projected-lineup source adapter uses the most recent eligible completed MLB game and retains source-game provenance. It does **not** use an active-roster fallback to manufacture a batting order.

This adapter was introduced in merged PR #1381.

### 6.3 Production selection handoff

Primary modules:

- `mlb_app/simulation/shadow/production_lineup_selection.py`
- `mlb_app/model_projections.py`

Merged PR #1382 wired selected projected lineups into canonical readiness/shadow execution. Complete or partial confirmed discovery prevents inappropriate projected discovery. Public diagnostics remain redacted.

### 6.4 Projected hitter-profile materialization

Primary module:

- `mlb_app/simulation/shadow/selected_lineup_profile_materialization.py`

Merged PR #1383 added player-level hitter-profile materialization from the selected projected batting order.

Critical invariant:

- both teams must produce nine usable projected player profiles before both offense contexts are replaced;
- one-sided success does not create a mixed simulation context;
- if either projected side cannot be materialized safely, the original team-level contexts remain unchanged;
- batting-order position and lineup provenance are preserved;
- probable-pitcher handedness is retained so the correct hitter split can be selected.

### 6.5 UI verification state

The Model Projections UI does not infer a canonical projected-lineup run from player counts.

It requires same-run evidence for:

- lineup selection;
- player-profile materialization;
- exact-artifact readiness;
- canonical execution.

When the full chain is verified, the UI can explicitly state that the canonical simulation ran with projected lineups. Confirmed-lineup executions receive a separate explicit label. Blocked/unverified states remain blocked/unverified.

This display contract was added in merged PR #1384.

### 6.6 Canonical outcomes

Canonical game-level outcomes are transported under `canonical_outcomes` in the canonical shadow diagnostics.

Current UI/view-model code includes:

- `frontend/src/lib/canonicalSimulationViewModel.mjs`
- `frontend/src/pages/ModelProjectionsPage.jsx`
- `mlb_app/simulation/shadow/integration.py`

When same-run evidence is complete, the UI can display the actual canonical trial count and canonical expected runs, win probabilities, total/team-total outputs, extra-innings probability, and walk-off probability.

The UI must not relabel the legacy 3,000-run payload as canonical output. When canonical selection is claimed but canonical outcomes are blocked or unattached, canonical result fields are withheld rather than silently filled from legacy values.

This transport/display contract was added in merged PR #1385.

### 6.7 Artifact namespace and Overview atomicity

`mlb_app/shared_artifacts.py` currently defines:

```text
MODEL_PROJECTION_WORKSPACE_VERSION = model_projection_workspace_v7
```

The v7 namespace prevents durable or memory-cached pre-outcome artifacts from masquerading as post-outcome canonical payloads.

A cached/durable payload that claims completed canonical execution must include the same run's versioned canonical outcomes before it is treated as a valid current artifact.

Overview and Simulation consume the same canonical simulation view-model semantics. Canonical fields are presented atomically; missing canonical fields do not fall through to legacy fields one-by-one.

This was completed in merged PR #1386.

### 6.8 Authority boundary

Do not assume that “canonical is visible” means “canonical replaced every production model authority.”

The shadow execution code explicitly preserves legacy authority when canonical assembly/execution cannot safely run. Activation/authority is represented explicitly in diagnostics. Future changes to authority must be deliberate, tested, and documented; do not infer authority from the existence of `canonical_outcomes` or a UI label.

---

## 7. My Dashboard architecture

My Dashboard is a signed-in report workspace with server-owned report types, filters, sorting, pagination, saved reports, Query Studio capability controls, and all-row export.

Primary code:

- `mlb_app/my_dashboard_routes.py`
- `mlb_app/my_dashboard_solver.py`
- `mlb_app/dashboard_player_population.py`
- `mlb_app/dashboard_projection_operator.py`
- `mlb_app/dashboard_player_projection.py`
- `frontend/src/pages/MyDashboardReportBuilderPage.jsx`

### 7.1 Canonical report population

Default canonical hitter/pitcher reports read from durable/current canonical dashboard data rather than rebuilding the full player population inside every request.

Important tables include:

- `dashboard_players`
- `dashboard_player_snapshots`
- `dashboard_player_current`
- `dashboard_projection_runs`
- legacy/compatible dashboard storage such as `my_dashboard_records`

Canonical identity is based on MLBAM IDs. Do not introduce name-only canonical identity matching.

### 7.2 Active-roster collection

`fetch_verified_active_rosters(...)` fetches all verified MLB active rosters concurrently and retains an all-team completeness requirement.

Current behavior is intentionally strict: if verified roster collection fails for any team, that canonical refresh is rejected rather than promoting a knowingly incomplete replacement.

The previous successful `dashboard_player_current` projection is preserved when the new canonical refresh fails.

This means a transient roster-network failure can mark one scheduled refresh as failed while existing report/export data remains available. A later healthy refresh may succeed without manual data repair because the prior current projection was never destroyed.

Do not weaken this behavior casually. Any resilience change should preserve the integrity contract or explicitly redefine it with tests.

### 7.3 Promotion and coverage safety

Canonical refreshes stage/build the new projection and promote validated current rows atomically. Coverage gates can reject implausibly sparse critical hitter fields. A rejected refresh must not erase the previous current projection.

See:

- `docs/my_dashboard_canonical_production_runbook.md`

### 7.4 Report requests are read-only

Current report-query behavior marks canonical population bootstrap as not run because report requests are read-only. Refresh work belongs in the scheduled/operator path, not as an implicit side effect of every report request.

### 7.5 All-row CSV export

The all-row CSV export is server-streamed. The browser makes one authenticated download request; the backend paginates through the report at the server's supported page size and streams the rows.

Primary route:

```text
POST /my-dashboard/reports/export.csv
```

Query Studio has its own server-streamed export path.

Do not restore browser-side sequential page collection unless there is a demonstrated reason. The streaming implementation was introduced in merged PR #1374 specifically to avoid that overhead and preserve complete exports.

### 7.6 Authentication

My Dashboard supports:

- email/password authentication;
- Google OAuth;
- GitHub OAuth;
- one-time password recovery through configured SMTP.

OAuth/recovery configuration belongs on the backend Railway service. See:

- `docs/my_dashboard_authentication.md`

Do not expose provider secrets or weaken identical-response behavior for password-reset account enumeration.

---

## 8. Scheduled refresh worker

Primary entry point:

- `scripts/run_refresh_job.py`

The worker separates fast user-facing refresh work from optional heavy recovery/backfill work.

Important current toggles include:

| Variable | Default | Purpose |
| --- | ---: | --- |
| `RUN_FAST_MATCHUP_REFRESH` | `1` | refresh live matchup payloads |
| `WARM_MATCHUP_SNAPSHOTS` | `0` | optional matchup snapshot warming |
| `REFRESH_MATCHUPS_FIRST` | `1` | preserve matchup-first sequencing |
| `CLEAR_AI_CACHE_AFTER_REFRESH` | `1` | best-effort AI/model cache clearing |
| `RUN_STATCAST_ETL` | `0` | optional heavier Statcast ETL |
| `RUN_HITTER_STATCAST_BACKFILL` | `0` | optional wider hitter backfill |
| `RUN_HITTING_MATCHUPS_REFRESH` | `1` | refresh hitting matchup data |
| `RUN_CANONICAL_DASHBOARD_REFRESH` | `1` | run canonical My Dashboard refresh |
| `REFRESH_ETL_BACKFILL_DAYS` | `1` | ETL backfill span when enabled |

The worker-level HTTP helper has retry/backoff controls for its own deployed-service requests:

- `REFRESH_TIMEOUT_SECONDS`
- `REFRESH_MAX_ATTEMPTS`
- `REFRESH_RETRY_BACKOFF_SECONDS`

Do not assume these worker-level retries automatically wrap every lower-level `requests.get(...)` call made by downstream Python modules.

### Cache-clear rule

AI Data Assistant cache clearing is best-effort and is not itself the canonical refresh success gate. Keep warning-level cache-clear failures distinct from fatal data-refresh failures.

### Cron failure semantics

When reading a Railway cron log, identify the first fatal application-stage exception rather than treating every warning/HTTP error as the root cause. A scheduled worker can complete several upstream refresh stages and then fail a later canonical stage.

---

## 9. Caching and durable artifacts

### Projection performance and diagnostic transport

Model Projection reads, including AI Data Assistant and My Dashboard solver
consumers, use the warmed artifact. A missing artifact returns `not_ready`;
these readers must not launch a full-slate simulation. Valid durable artifacts
are promoted into the process cache for subsequent reads.

Projection transport retains every game, outcome, player projection, readiness
field, and aggregate diagnostic. Only per-plate-appearance probability debug
observations and per-trial pitcher appearance audit arrays are limited to 100
rows, with explicit total/included counts and truncation metadata. Full audit
objects remain available to internal simulation/role calculations before the
transport boundary. Low-level probability serialization defaults to full
observations for audit callers; production attachment requests a bounded sample.

Existing v7 durable artifacts are compacted on read, so a deployment can serve
the last verified outcomes without waiting for another refresh. The semantic
outcome namespace remains v7 because model results and authority are unchanged.

Immutable probability artifact/catalog digests are calculated once per instance,
not once per simulated plate appearance. Replaced artifacts get fresh digests.

Only one Model Projection warm operation runs per API process at a time.
Overlapping snapshot requests receive HTTP 409 with `Retry-After: 30`; they do
not start a duplicate build or clear the last good artifact. This guard matches
the current single-process Uvicorn deployment; it is not a distributed lock.

The repository has multiple independent cache/storage layers:

- process-local response caches;
- matchup snapshots;
- shared/durable artifact storage;
- canonical current database tables;
- browser request behavior;
- local-storage UI/report state.

A database refresh does not automatically invalidate every process-local or browser cache.

Cache/artifact keys must include every input that changes semantic meaning, especially:

- contract/artifact version;
- MLB business date;
- route/report type;
- filters/sort/mode;
- provider;
- user/session scope when applicable.

Version bumps such as Model Projection workspace v7 are compatibility boundaries, not cosmetic names.

---

## 10. Date and time rules

Public date parameters use `YYYY-MM-DD`.

Explicit dates supplied by a user must be preserved. Implicit concepts such as “today,” default slate date, cron hydration date, and report date must use the intended MLB business-date helper rather than raw UTC container date.

Railway containers can run in UTC. Do not introduce unqualified `datetime.date.today()` into production slate-selection code without verifying the business-date contract.

UTC timestamps are appropriate for audit timestamps when clearly distinguished from the MLB slate date.

---

## 11. Probability and source labeling

Several probability concepts can coexist:

- legacy/final model probability;
- canonical simulation probability;
- diagnostic/base simulation probability;
- bullpen-adjusted diagnostic probability;
- sportsbook-implied probability.

Do not collapse them into a generic “Win Probability” label. Preserve source/authority metadata through backend contracts and frontend display.

Similarly, a canonical simulation display must not relabel legacy values as canonical when canonical evidence is missing.

---

## 12. Environment-variable ownership

Minimum production-critical variables:

| Variable | Service | Responsibility |
| --- | --- | --- |
| `DATABASE_URL` | backend / refresh jobs | PostgreSQL connection |
| `VITE_API_BASE_URL` | frontend build | FastAPI backend base URL |

My Dashboard OAuth/password-recovery variables belong on the backend and are documented in `docs/my_dashboard_authentication.md`.

Provider-specific sportsbook credentials belong only on the service that consumes them.

Never commit secrets, cookies, tokens, OAuth client secrets, SMTP passwords, or production connection strings.

---

## 13. Local development

Backend:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn mlb_app.app:app --reload --port 8000
```

Frontend:

```bash
cd frontend
npm install
echo "VITE_API_BASE_URL=http://localhost:8000" > .env.local
npm run dev
```

Use an explicit local PostgreSQL `DATABASE_URL` when validating production-like persistence behavior. SQLite is useful for focused unit tests but is not evidence of PostgreSQL production compatibility by itself.

---

## 14. Validation before merge

Run tests that prove the changed contract, not merely a broad command with no interpretation.

Baseline checks:

```bash
python -m compileall mlb_app
python -c "from mlb_app.app import app"
pytest

cd frontend
npm install
npm run build
```

For a targeted change, run the focused tests first and then the relevant regression family.

### Production-path smoke matrix

At minimum, consider:

1. `GET /health`.
2. Matchups for an explicit known MLB date.
3. One Matchup Detail render.
4. Model Projections for the same date.
5. Canonical Model Projection diagnostics/outcomes where applicable.
6. Daily Odds with real provider data and with provider data absent.
7. My Dashboard report query and all-row export.
8. My Dashboard authentication path if auth changed.
9. AI Data Assistant request if cache/assistant code changed.
10. Refresh-worker logs and freshness evidence if refresh code changed.

Never use “HTTP 200” as the only acceptance criterion for a data product.

---

## 15. Operational triage order

When production appears wrong:

1. Determine the exact affected surface and MLB date.
2. Determine whether the frontend request reached the expected backend service.
3. Inspect the backend contract, not just the rendered UI.
4. Separate provider/data-source failure from cache staleness and frontend-state problems.
5. Check the latest durable/current artifact or database projection.
6. Read the scheduled refresh log stage-by-stage.
7. Identify the first fatal exception.
8. Confirm whether the system preserved the previous good state.
9. Change only the failing layer unless evidence demonstrates a broader contract problem.

This order is intentionally conservative. MLBGPT contains several production paths where preserving the last verified result is safer than partially overwriting it.

---

## 16. Invariants future agents must preserve

Unless a dedicated migration/architecture PR explicitly changes them:

- Do not fabricate missing MLB, Statcast, model, or sportsbook data.
- Do not confuse `null` with zero.
- Do not name-match canonical player identity when an MLBAM ID is required.
- Do not partially promote an incomplete canonical My Dashboard population.
- Do not mix confirmed and projected batting-order inputs when the selection contract blocks it.
- Do not replace only one projected offense context when the materialization contract requires both sides.
- Do not relabel legacy simulations as canonical simulations.
- Do not mix canonical and legacy fields inside one claimed canonical Overview/result.
- Do not bypass artifact versioning when a payload contract changes.
- Do not make report GET/query behavior mutate canonical production state as an accidental side effect.
- Do not revert all-row export to browser-side page collection without evidence.
- Do not put session-specific dashboard responses into an unsafe global browser cache.
- Do not use UTC container date as a substitute for the MLB business date.
- Do not treat a warning-only cache-clear failure as equivalent to a failed data refresh.
- Do not broadly rewrite the working matchup/detail path to solve a narrow issue.

---

## 17. Important merged PR chronology

These PRs are useful when architectural intent is not obvious from one function.

| PR | Purpose | Current architectural significance |
| --- | --- | --- |
| #1058 | Populate canonical active players | MLBAM identity, verified source population, guarded deactivation |
| #1086 | Harden canonical My Dashboard lifecycle | status, audited refresh, atomic/preserved projection semantics |
| #1125 | Finish canonical roster bootstrap | concurrent all-team roster collection, fail-as-a-set completeness |
| #1186 | Repair My Dashboard freshness/Confirmed 1–9 | scheduled canonical refresh, freshness/coverage safeguards |
| #1374 | Speed all-row CSV exports | authenticated server-streamed Report Builder/Query Studio export |
| #1380 | Define selected-lineup contract | complete confirmed first, complete projected fallback, fail closed |
| #1381 | Projected-lineup source adapter | latest eligible completed-game batting-order source |
| #1382 | Wire projected selection | production canonical selection handoff/readiness integration |
| #1383 | Materialize projected hitter profiles | atomic two-sided player-level offense contexts |
| #1384 | Display projected-lineup simulation state | explicit same-run readiness evidence in UI |
| #1385 | Transport/display canonical outcomes | truthful canonical run count and game-level outcomes |
| #1386 | Align Overview with canonical outcomes | v7 artifact boundary and atomic canonical Overview/Simulation semantics |

PR descriptions are historical intent. Current code/tests remain authoritative.

---

## 18. Specialized documentation

Use specialized docs for operational detail rather than duplicating them here.

- `docs/my_dashboard_canonical_production_runbook.md` — canonical dashboard inspection, refresh, coverage, rollback.
- `docs/my_dashboard_authentication.md` — OAuth and password-recovery production configuration.
- `docs/canonical_model_engine_v2_summary.md` — canonical engine design history/details; verify current code before treating historical statements as active authority.
- `docs/canonical_baserunning_production_monitoring.md` — canonical baserunning monitoring details.
- Other `docs/` audit/probe/plan files — historical or task-specific evidence; do not automatically treat as current architecture.

---

## 19. Documentation maintenance contract

Every architecture-changing PR should update documentation when it changes any of the following:

- production route ownership;
- source authority;
- model authority or fallback semantics;
- artifact/cache version;
- database ownership/promotion semantics;
- Railway service topology;
- scheduled refresh order;
- authentication/session contract;
- environment-variable ownership;
- production validation requirements.

When updating this file:

1. verify the current code path;
2. verify the tests that encode the intended behavior;
3. inspect the merged PR only for design intent/history;
4. update the `Verified against` commit/date;
5. distinguish active behavior from planned behavior;
6. avoid copying transient production incidents into permanent architectural claims unless they reveal a lasting contract.

The goal is not to make this Markdown “never wrong” by freezing it. The goal is to make drift obvious and easy to correct whenever the code evolves.

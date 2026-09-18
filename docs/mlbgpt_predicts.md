# MLBGPT Predicts

Predicts is a pregame research layer over Model Projections. It preserves the baseline,
freezes the evidence available before a game, joins official Final results, and learns
residual corrections only after sufficient historical evidence exists. It never emits
sportsbook prices or treats model-only signals as priced plays.

## Product and API

Research → MLBGPT Predicts opens `/predicts`. The board includes All, Overperform,
Underperform, Hitters, Pitchers, Games and Model health views, with player details.
The frontend uses `VITE_API_BASE_URL` and bypasses the global 30-minute browser cache
for this frequently changing board. Dates use the existing MLB business-date helper;
displayed times use the viewer's local timezone.

All API routes are public read-only research routes, consistent with Model Projections.
No new authentication system, public training endpoint or write endpoint is introduced.

| Route | Contract |
| --- | --- |
| `GET /predicts?date=YYYY-MM-DD` | Latest saved pregame version for each player/game/type |
| `GET /predicts/game/{game_pk}` | Saved game predictions across both teams |
| `GET /predicts/player/{player_id}?date=YYYY-MM-DD` | MLBAM identity; preserves doubleheaders |
| `GET /predicts/history?start=...&end=...&player_id=...&offset=...&limit=...` | Graded snapshots; limit ≤ 200 |
| `GET /predicts/backtest?start=...&end=...` | Frozen-prediction evaluation; maximum range 366 days |
| `GET /predicts/model-health` | Last capture, learning threshold and 30-day evaluation |

Backtest filters: `player_type`, `metric`, `model_version`, `lineup_position`,
`min_expected_pa`, `min_arsenal`. MAE/RMSE comparisons use the same population when
an adjusted forecast exists. Brier/log loss evaluate the binary event **actual >
baseline**; equality is a separate outcome, not incorrectly counted as under.
The new API does no simulation, raw-pitch retrieval, training or feature reconstruction.

## Source authority and data flow

1. The existing projection warm route persists a `model_projection_date` artifact.
2. Its background task calls the Predicts refresh worker after warming succeeds.
3. Predicts batch-reads that exact artifact, canonical dashboard rows and approved
   lineup snapshots, existing Player Trends and Batter vs Arsenal rows, bounded
   Statcast history and previous Final snapshots.
4. Features and baseline distributions are materialized, then eligible earlier
   graded snapshots fit a residual model.
5. A new immutable player revision is appended and the game candidate pointer moves
   atomically. Identical source/feature/model content is a no-op.
6. At scheduled game time the candidate becomes logically locked even if no job
   runs at that exact instant. Refresh also persists the lock. If information arrives
   late, it cannot create or replace a historical pregame prediction.
7. The existing Final capture path grades the last pregame revision in an isolated
   transaction. The refresh sweep retries missing settlements.
8. Subsequent dates can learn from those frozen features and results.

`run_refresh_job.py` also invokes Predicts after its existing prerequisite stages.
It only consumes warmed artifacts and does not invoke another simulator. A missing
artifact is reported as unavailable. Feature/source failures are logged, and do not
roll back existing Matchups, MyDashboard, Model Projections or Final data. Settlement
commits before processing possibly stale pregame sources.

## Persistence and migration

The existing SQLAlchemy `create_tables` registration adds four tables. There is no
rewrite of canonical player, Statcast, Final, market or source-report tables.

| Table | Purpose |
| --- | --- |
| `predicts_game_snapshots` | One game identity, schedule, latest revision pointer and lock |
| `predicts_player_snapshots` | Append-only baseline, feature store and predictions per revision/player/type |
| `predicts_outcomes` | One immutable outcome join per frozen player snapshot |
| `predicts_model_runs` | Immutable coefficients, temporal split, source snapshot IDs and validation evidence |

Unique player revision identity includes game PK, revision, MLBAM ID and player type
(two-way players retain both roles). The point-in-time index includes game PK,
player ID, capture timestamp and feature version. Date/game and player indexes
support board and history reads. Foreign keys link settlement to the exact Final.

Database triggers reject updates/deletes of player history, outcomes and model runs;
locked game pointers are also protected. ORM guards provide earlier errors. Inserts
use PostgreSQL/SQLite conflict handling; promotion uses a row lock plus revision
compare-and-swap. An older worker cannot supersede a newer candidate.

Normal app initialization creates the additive tables. To apply them explicitly with
the deployment's existing `DATABASE_URL` before enabling the page:

```sh
python -c 'from mlb_app.predicts_service import session_factory; session_factory()'
```

Use the same database in the API and Railway refresh service. No new API keys or
external providers are required. Rollback is the prior application version; keep the
new history tables. Do not delete genuine pregame history to reset a model.
PostgreSQL deployment/migration execution is still a deployment acceptance check;
the local integration suite uses SQLite and also checks PostgreSQL DDL generation.

## Historical integrity

All source timestamps used by an adapter must precede capture. Projection artifacts
older than six hours are rejected. Canonical player process values older than 36 hours
are retained for audit but excluded from model inputs. Statcast event dates must be
strictly before the target date, conservatively excluding same-day doubleheader data.
Raw Statcast has no ingestion timestamp: its values are observed and frozen at capture;
these records are never presented as an earlier historical reconstruction.

Capture happens after feature computation and is rechecked against game time. A job
that runs past first pitch cannot promote its result. Unknown/ambiguous start times,
non-pregame status, wrong teams, duplicate identities, corrupt opportunity counts,
and future source timestamps fail closed. Final's recorded game timestamp provides
an additional anti-leakage check before settlement. Scheduled start is a conservative
cutoff during delays; after it passes, a delayed game's record is not reopened.

Each record carries baseline authority, model/run/version, artifact version,
simulation count, source timestamps, feature version, Predicts version, revision,
capture time and Railway Git SHA when provided. Models retain the training cutoff
and exact contributing snapshot IDs. Unknown legacy authority is not promoted to
canonical authority by Predicts.

## Residual model and probability semantics

The four learned targets are hitter hits, total bases, home runs, and pitcher strikeouts.
Baselines are never overwritten. Features are baseline, projected opportunity,
canonical process, standardized recent change, arsenal, location, bullpen,
environment and opponent-adjusted recent process.

Models are grouped by player type, target and baseline model version. At least **100
fit records, 30 temporal holdout records and 14 distinct game dates** are required.
The last quarter of earlier dates is reserved for validation. Features are standardized
with fit-only statistics; missing numerical values are mean-imputed internally, while
the public feature remains null. Ridge penalty is 20 with an unpenalized intercept.
All-absent features have zero coefficients. The fitting population is bounded to the
most recent 50,000 graded snapshots within 365 days.

A model must reduce continuous residual MAE on the later holdout before producing an
adjustment. Its held-out errors form an empirical predictive distribution, floored at
zero and rounded to count support. This is a **research estimate**, not a claim of
calibrated certainty. Prospective stored forecasts supply subsequent calibration tests.
MAE validation is for the continuous residual estimator; final count-support forecasts
are separately measured in the prospective backtest.

Attributions are actual linear contributions plus an explicit holdout-error/count-support
correction. They sum to adjusted minus baseline. They are not SHAP or causal explanations.
Historical comparables are the closest 50 prior observations in available standardized
features; the interval is a descriptive Wilson interval, not an independence guarantee.
There is no win guarantee and no automatic model promotion to the baseline simulator.

The existing canonical simulator now exports empirical SD and zero/threshold probabilities
alongside existing quantiles. Exact hits/total-base distributions are aggregated from
those same simulated box scores, preserving within-game dependence. No second Monte
Carlo engine or duplicate execution was added. Older artifacts remain readable and
missing distribution fields stay null until the next normal projection warm.

## Requested capabilities: exact implementation status

| # | Capability | Current implementation and boundary |
| --- | --- | --- |
| 1 | Immutable pregame snapshots | Append-only revisions, atomic candidate promotion, logical and durable locks |
| 2 | Point-in-time feature store | Frozen features embedded in indexed player snapshots; no redundant table |
| 3 | Final joins | H/TB/HR/K residuals, errors, over/under/equal, idempotent settlement |
| 4 | PA layer | Terminal-event view over existing Statcast; missing score/base state/TTO remain null |
| 5 | Pitch layer | Bounded normalized SQL rows from `statcast_events`; absent release/extension fields not invented |
| 6 | Expected arsenal | Handedness-conditioned recent/longer-window usage, existing matchup xwOBA, sample shrinkage and coverage; longer window is capped at 1,500 pitches, not a full-season model |
| 7 | Location compatibility | Pitch-type × fixed plate-coordinate buckets, shrunk damage and coverage; not personalized zone heights or a whiff-zone model |
| 8 | Expected PA | Reuses canonical PA mean/distribution as a residual-model feature; no separately trained batting-slot opportunity model |
| 9 | Starter workload | Last five official starters' pitches/BF, empirical thresholds and third-pass rate; no trained rest/opener/tandem leash model |
| 10 | Bullpen | Reuses canonical quality/profile and divides projected PA into starter/bullpen shares; fatigue and handedness availability remain unavailable |
| 11 | Environment | Reuses canonical run/HR indexes and weather; air density only with real temperature, humidity and pressure; no unvalidated carry formula |
| 12 | Park | Existing environment/park context only; no newly trained handedness/directional park factors |
| 13 | Opponent adjustment | Recent batted-ball xwOBA adjusted toward the observed canonical opponent-quality reference, sample-shrunk; current-as-of quality, not reconstructed pre-PA quality |
| 14 | Process/results | Preserves process metrics and production separately; no claim of causal luck attribution |
| 15 | Skill change | Disjoint recent/prior sample standardized difference with sample gate; formal change-point detection is unavailable |
| 16 | Opportunity windows | Hitter 25/50/100/250 terminal PA, pitcher 100/250/500 pitches; workload last 3/5 starts; sample and completeness included |
| 17 | Distributions | Same-run canonical quantiles, SD, P(0), P(1+)…P(6+); supported adjusted targets use temporal errors; no invented pitcher pitch-count simulation |
| 18 | Residual model | Versioned ridge/temporal-validation model for H/TB/HR/pitcher K; explicit cold start |
| 19 | Backtest/calibration | MAE/RMSE/bias, over/under/equal, Brier/log loss/calibration, listed filters; other requested multi-dimensional segments are not yet implemented |
| 20 | Attribution | Exact additive contributions and count-support correction, historical comparables |

Unavailable fields in this table are not completed capabilities merely because a
nullable interface exists. In particular, the advanced PA-state, personalized location,
independent opportunity/leash, fatigue, directional park and formal change-point
models require further implementation/source enrichment. The first priority is the
working baseline → pregame snapshot → Final → residual learning chain.

## Backfill and troubleshooting

```sh
python scripts/backfill_predicts_outcomes.py --start-date 2026-09-01 --end-date 2026-09-17 --dry-run
python scripts/backfill_predicts_outcomes.py --start-date 2026-09-01 --end-date 2026-09-17
```

The command commits one date at a time and is safe to resume. It imports only saved
pregame projection artifacts at their original capture time; it does not attach
today's trends or mutable features to old predictions. Model health reports daily
month coverage and explicit source gaps. The normal refresh job runs this current-
month recovery idempotently. Historical periods without a saved pregame artifact
remain unavailable for training.

- Empty board: check warmed artifact, date, explicit start timestamp, pregame status
  and worker rejection log. Started games without a pregame capture cannot be added.
- No adjustment: inspect sample thresholds and held-out improvement status. This is
  expected on a new installation.
- Missing feature: check source timestamp, sample coverage and status; zero is distinct
  from unavailable. Stale process inputs are not silently used.
- Final not graded: check MLBAM/game join and capture/start ordering; run the resumable
  outcome join or next refresh. Missing actual fields are not converted to zero.
- Refresh failure: inspect `Predicts refresh failed` logs. Existing product surfaces
  continue to read their own authoritative sources.

## Validation

The focused backend suite covers real SQLite persistence, lock triggers, atomic
versioning, duplicate jobs, stale-worker ordering, leakage rejection, cold start,
residual arithmetic and attribution, exposure, arsenal shrinkage, location/change,
opponent adjustment, distribution tails, weather missingness and FastAPI read paths.
Existing projection performance, canonical projection payloads, report queries/CSV,
Player Trends, identity, Final and refresh tests are included. Production feeds and
Railway PostgreSQL are not accessed by these fixture-backed checks.

Validation result for this PR: **89 focused backend tests passed**, **72 selected
frontend contract tests passed**, and `npm run build` passed. The full frontend
suite has five pre-existing `modelTrackerPnl.test.mjs` failures, reproduced against
the unchanged base tree. Existing Vite bundle-size/duplicate-style-key warnings
are outside this change. Browser rendering could not be verified: the headless
Chromium executable was absent and its download timed out. Production feeds and
Railway PostgreSQL migration execution remain deployment acceptance checks.

Backend command:

```sh
python -m pytest -q tests/test_predicts.py tests/test_dashboard_projection_report_query.py tests/test_final_game_snapshots.py tests/test_canonical_projection_payload.py tests/test_canonical_player_projection_rows.py tests/test_refresh_job_retries.py tests/test_projection_performance_regression.py tests/test_my_dashboard_report_query.py tests/test_player_trends_and_saved_report_analysis.py tests/test_model_projection_player_identity_attachment.py tests/test_report_csv.py
```

The local runner used the existing dependency cache plus isolated `httpx` and
`feedparser` test dependencies; no application dependency manifest was changed.

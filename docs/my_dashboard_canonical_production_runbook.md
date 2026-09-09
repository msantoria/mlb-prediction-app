# My Dashboard canonical projection production runbook

## Purpose

The default Hitters and Pitchers reports read `dashboard_player_current`. They do not build a slate population at request time. This runbook is the production procedure for populating, inspecting, refreshing, and verifying that canonical projection.

Do not claim My Dashboard is populated from a successful deploy alone. A successful production refresh and plausible status counts are separate requirements.

For system-wide architecture and current invariants, also read [`MLBGPT_SYSTEM_REFERENCE.md`](MLBGPT_SYSTEM_REFERENCE.md).

## Read-only inspection

From a Railway shell or equivalent environment with the production `DATABASE_URL`:

```bash
python scripts/refresh_dashboard_player_projection.py
```

The command is status-only unless `--refresh` or `--backfill-days` is explicitly supplied.

The deployed API also exposes:

```text
GET /my-dashboard/canonical/status
GET /my-dashboard/report-types
```

The status response contains no player names, credentials, connection strings, or source payloads.

## Initial production refresh

Run after the schema-containing deployment is healthy:

```bash
python scripts/refresh_dashboard_player_projection.py --date YYYY-MM-DD --refresh
```

The operator command:

1. reads the verified MLB active-team endpoint and refuses fewer than 30 teams;
2. reads every verified MLB active roster;
3. reads confirmed boxscore lineups available for the target date;
4. combines those sources with tracked Statcast game activity and existing aggregate coverage;
5. populates canonical identities using MLBAM IDs only;
6. builds one snapshot row for every resolved active canonical player;
7. atomically promotes the full current projection;
8. records a durable success or failure row in `dashboard_projection_runs`;
9. emits before/after status and row-count evidence.

Missing-player deactivation is off by default. Use `--transition-missing-players` only after confirming the team and roster source set is complete. A source or projection failure preserves the previous `dashboard_player_current` projection.

## Active-roster completeness and transient failures

`fetch_verified_active_rosters(...)` collects the verified active rosters concurrently but retains an all-team completeness contract. If any team's verified roster request fails, the new canonical projection is rejected rather than promoting a knowingly incomplete roster set.

This is intentionally different from deleting or corrupting the current data:

- the failed refresh is recorded as failed;
- the previous successfully promoted `dashboard_player_current` rows remain available;
- report queries and CSV exports can continue to read that prior good projection;
- a later scheduled run can succeed normally if the upstream/network condition was transient.

Therefore, one failed Railway cron run does not automatically mean current report data was destroyed or that manual database repair is required.

When diagnosing a roster failure, distinguish between:

- a transient `ConnectionError`/timeout from one team request;
- a persistent upstream/source failure;
- an actual canonical population or coverage failure after roster collection.

Do not weaken the all-team integrity contract as an incident reaction without a dedicated design/test change. If retry behavior is added later, preserve the verified-source and atomic-promotion guarantees unless the architecture is deliberately redefined.

## Optional historical snapshot backfill

After a successful current refresh:

```bash
python scripts/refresh_dashboard_player_projection.py --date YYYY-MM-DD --backfill-days 30
```

To perform both operations in one invocation:

```bash
python scripts/refresh_dashboard_player_projection.py --date YYYY-MM-DD --refresh --backfill-days 30
```

Backfill retains immutable snapshots. Only the final successful date is promoted as current.

## Plausibility gates

Treat the projection as production-ready only when all of the following are true:

- `status = ready`;
- `population.canonical_count > 0`;
- `population.active_hitter_count > 0`;
- `population.active_pitcher_count > 0`;
- `current_projection.row_count = population.active_count`;
- hitter and pitcher current counts match their active canonical counts;
- `current_projection.stale = false`;
- a durable `refresh_runs.latest_success` exists;
- snapshot count is non-zero;
- field coverage is inspected rather than assumed;
- default hitter/pitcher reports return the same full-population counts across pagination;
- changing weights does not change `totalSize`.

The service intentionally does not hard-code a claim such as “200+ hitters” because roster availability, season timing, aggregate coverage, and the active-window policy affect the actual population.

## Field coverage

The status endpoint reports non-null counts and ratios separately for hitters and pitchers for:

- model score and confidence;
- xwOBA and xBA;
- exit velocity and launch angle;
- hard-hit and barrel rates;
- strikeout and walk rates;
- ISO, OBP, and SLG;
- plate appearances.

A low-coverage field remains visible and nillable. It must not silently remove players from an unfiltered report.

## Related reports

The query endpoint supports these additional validated related reports:

```json
{"report_type": "players_lineup_history"}
```

```json
{"report_type": "hitters_arsenal_splits"}
```

They use explicit field catalogs from `GET /my-dashboard/report-types`, SQL validation, stable pagination, and canonical-player joins. Arsenal split rows only include active resolved hitters. These one-to-many reports do not redefine the default active-player population.

## Scheduled Railway worker

The checked-in Railway worker is `scripts/run_refresh_job.py`. It runs the canonical My Dashboard refresh after the earlier **enabled** refresh stages complete. Heavy Statcast ETL and hitter backfill are optional feature-toggled stages and must not be assumed to execute on every scheduled run.

Current important toggles/defaults include:

```text
RUN_FAST_MATCHUP_REFRESH=1
WARM_MATCHUP_SNAPSHOTS=0
RUN_STATCAST_ETL=0
RUN_HITTER_STATCAST_BACKFILL=0
RUN_HITTING_MATCHUPS_REFRESH=1
RUN_CANONICAL_DASHBOARD_REFRESH=1
CLEAR_AI_CACHE_AFTER_REFRESH=1
```

Use the same production `DATABASE_URL` as the API.

For an isolated operator run:

```bash
python scripts/refresh_dashboard_player_projection.py --refresh
```

Recommended canonical environment controls:

```text
DASHBOARD_ACTIVE_PLAYER_WINDOW_DAYS=30
DASHBOARD_PROJECTION_STALE_HOURS=36
DASHBOARD_COVERAGE_GATE_MIN_HITTER_POPULATION=50
DASHBOARD_MIN_HITTER_CRITICAL_FIELD_COVERAGE=0.25
```

The coverage gate rejects a promotion when model score, confidence, xwOBA, or xBA falls below the configured ratio for a normal-sized hitter population. The previous current projection remains available after rejection.

Do not run overlapping projection refreshes. The command is idempotent for identical approved content, but simultaneous source collection wastes capacity and makes run evidence harder to interpret.

### Cache-clear warnings

AI Data Assistant cache clearing in `scripts/run_refresh_job.py` is best-effort. A cache-clear warning should not be treated as the fatal root cause unless the worker explicitly reports it as the terminating stage.

Read cron logs in execution order and identify the first fatal application-stage exception. The worker can successfully finish matchup/hitting-matchup work and still fail later in the canonical dashboard stage.

## Production verification

For the original July 23, 2026 repair, the historical pre-repair baseline was:

| Measure | Before deployment |
| --- | ---: |
| Active hitters | 379 |
| Active pitchers | 408 |
| Current projection date | 2026-07-20 |
| Projection age | 68.24 hours |
| Hitter model-score coverage | 14 / 379 (3.69%) |
| Confirmed hitters reported by lineup discovery | 72 |
| Confirmed hitters returned by the legacy route | 6 |

Those numbers are incident history, not current production expectations.

For any current deployment or repair:

1. Deploy the code/schema change and verify backend health.
2. Run status-only inspection and save the prior baseline.
3. Run the explicit current refresh if required.
4. Save the emitted JSON counts.
5. Call `GET /my-dashboard/canonical/status` from production.
6. Query `all_active_hitters` and `all_active_pitchers` without filters.
7. Page through results and confirm stable, gap-free totals.
8. Apply one team filter and one metric filter.
9. Apply a weight-only change and confirm count stability with ordering change.
10. Query the supported related report types.
11. Test an all-row CSV export and verify expected row count.
12. Open the Report Builder on desktop and mobile and switch among primary objects.
13. Smoke-test Matchups, Matchup Detail, Daily Odds, Model Projections, and AI Data Assistant.
14. Preserve counts, versions, timestamps, tests, build result, deployment logs, and smoke-test results in the relevant PR/incident record.

## Failure and rollback

- If verified team/roster collection fails, the current projection is not promoted.
- If the snapshot builder returns empty or incomplete coverage, promotion is rejected.
- If a critical coverage gate fails, promotion is rejected.
- If promotion fails after staging, snapshots/current changes roll back according to the transaction boundary.
- The failure is recorded in `dashboard_projection_runs`.
- Continue serving the previous current projection while repairing the source.
- Do not delete `dashboard_players`, `dashboard_player_snapshots`, `dashboard_player_current`, or `my_dashboard_records` as a routine incident response.
- Roll back application code normally if required; additive tables and immutable snapshots are safe to retain unless a dedicated migration says otherwise.

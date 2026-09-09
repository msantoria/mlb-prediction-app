# MLBGPT — Coding Agent Entry Point

Before making production changes, read:

1. [`README.md`](README.md) for the current repository/product overview.
2. [`docs/MLBGPT_SYSTEM_REFERENCE.md`](docs/MLBGPT_SYSTEM_REFERENCE.md) for architecture, authority, refresh semantics, Model Projections, My Dashboard, and invariants.
3. The specialized runbook for the subsystem being changed.

Executable code and tests on the current `main` branch are the final source of truth. Old plans, issue descriptions, probe notes, and PR bodies are historical evidence unless current code still implements them.

## Critical deployment topology

MLBGPT uses **two independent Railway services**.

| Service | Runtime | Role |
| --- | --- | --- |
| Backend | Docker, Python 3.11, Uvicorn/FastAPI | API, PostgreSQL, models, refreshes, reports |
| Frontend | Node/Railpack, React/Vite | `mlbgpt.com` SPA |

The frontend calls the backend through `VITE_API_BASE_URL`, which is set at **frontend build time**. The frontend service does not own FastAPI routes.

Production backend persistence uses `DATABASE_URL` and PostgreSQL. Do not treat SQLite fallback as production behavior.

## CORS

The backend must allow the live MLBGPT domains and the required Railway service domains. Do not restrict CORS to only the custom frontend domain without verifying deployment/internal traffic.

## High-value invariants

Do not casually change these contracts:

- Missing, `null`, unavailable, and zero are different states.
- Canonical player identity uses MLBAM IDs; do not replace it with name-only matching.
- Failed/incomplete canonical My Dashboard refreshes must not overwrite the previous verified current projection.
- Complete confirmed lineups take precedence over projected lineups under the canonical selected-lineup contract.
- Partial or blocked confirmed/projected input must not be silently mixed into a synthetic batting order.
- Projected player-level offense contexts are replaced atomically for both teams only when the materialization contract passes.
- Canonical simulation claims require explicit same-run readiness/execution/outcome evidence.
- Do not relabel legacy simulation values as canonical values.
- Do not mix canonical and legacy fields inside one claimed canonical Overview/result.
- Model Projection artifact-version bumps are semantic cache boundaries; current workspace contract is v7 as of the system-reference verification point.
- All-row My Dashboard exports are server-streamed; do not restore browser-side sequential pagination without evidence.
- Use MLB business-date handling for implicit slate dates; do not substitute raw UTC container date.
- Diagnose cron jobs stage-by-stage. Warning-only cache-clear failures are not automatically the fatal refresh cause.
- Prefer narrow fixes to broad rewrites of working production paths.

## Validation

Run focused tests for the contract being changed, then relevant regressions. For production paths, verify actual response semantics for an explicit MLB date; HTTP 200 alone is not acceptance evidence.

For full details and current merged architecture history, use [`docs/MLBGPT_SYSTEM_REFERENCE.md`](docs/MLBGPT_SYSTEM_REFERENCE.md).

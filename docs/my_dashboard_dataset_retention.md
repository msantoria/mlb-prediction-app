# My Dashboard dataset retention

`my_dashboard_records` stores versioned analytical datasets.
The query layer reads only rows where `is_current = true`.
Successful rehydration demotes the previous version to
`is_current = false`.

This retention stage bounds those superseded versions without
changing the current UI dataset.

## Production defaults

- Superseded-version grace period: 7 days
- Execution mode: dry run
- Maximum deletion per run: 10,000 rows
- Authority guard: only `is_current = false`
- Current rows are protected regardless of age
- Recent superseded rows remain available during the grace period

## Environment variables

- `MY_DASHBOARD_RETENTION_ENABLED`
  - Defaults to `1`
  - Set to `0` to skip evaluation.
- `MY_DASHBOARD_RETENTION_DAYS`
  - Defaults to `7`.
- `MY_DASHBOARD_RETENTION_DELETE_ENABLED`
  - Defaults to `0`.
  - Set to `1` only after reviewing dry-run diagnostics.
- `MY_DASHBOARD_RETENTION_DELETE_LIMIT`
  - Defaults to `10000`.
  - Bounds each production transaction.

The stage runs after dashboard hydration and Predicts consumption.
Failures are logged without turning a successful refresh into a
failed refresh job.

Deletion makes PostgreSQL space reusable internally. It does not
necessarily shrink the physical Railway volume immediately.

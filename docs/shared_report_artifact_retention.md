# Shared projection artifact retention

Large `model_projection_date` artifacts are retained for a
bounded period after Predicts has consumed the warmed data.

## Production defaults

- Retention: 14 days
- Execution mode: dry run
- Cutoff: `target_date < business_date - retention_days`
- The cutoff date, newer dates, current dates, and future dates
  are always preserved.
- Other shared artifact types are never affected.

## Environment variables

- `SHARED_REPORT_ARTIFACT_RETENTION_ENABLED`
  - Defaults to `1`
  - Set to `0` to skip the stage.
- `SHARED_REPORT_ARTIFACT_RETENTION_DAYS`
  - Defaults to `14`.
- `SHARED_REPORT_ARTIFACT_DELETE_ENABLED`
  - Defaults to `0`.
  - Set to `1` only after reviewing dry-run diagnostics.

The stage runs after the Predicts refresh and current-month
backfill so those consumers receive the warmed artifacts first.

PostgreSQL does not necessarily return deleted space to the
filesystem immediately. Normal vacuum makes it reusable inside
the database; a later controlled compaction can be considered
only if reducing the physical volume is necessary.

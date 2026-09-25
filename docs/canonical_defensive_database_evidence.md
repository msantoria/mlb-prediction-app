# Canonical defensive database evidence

This adapter executes the canonical defensive-distribution evidence
contract against one bounded window of stored Statcast events.

## Query boundary

The database query:

- is bounded by inclusive `window_start` and `window_end`;
- requires `window_end <= through_date`;
- reads only rows with a non-null terminal `events` value;
- selects only `game_date`, `game_pk`, `at_bat_number`, and `events`;
- applies deterministic ordering; and
- performs no insert, update, delete, flush, or commit.

The existing Statcast distribution source remains authoritative for
plate-appearance deduplication, event mapping, exclusion accounting,
and conflicting-terminal-event rejection.

## Statuses

- `ready`: the database window and comparison are available.
- `unavailable`: the database window is empty or the supplied
  simulation summary has no comparable observations.
- `error`: validation, query execution, source construction, or
  evidence execution failed.

The query receives a deterministic SHA-256 digest independent of
database insertion order.

## Safety boundary

This adapter discloses that the database was accessed in read-only
mode. It performs no network request, external fetch, persistence,
calibration selection, activation, or production-authority change.

The nested evidence artifact continues to describe its own
caller-owned-row boundary, where `database_accessed = false`; the
outer database execution artifact records the actual read as
`database_accessed = true`.

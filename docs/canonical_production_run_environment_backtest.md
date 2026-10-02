# Canonical production run-environment backtest

This measurement-only backtest compares one production-owned
canonical simulation run environment with one bounded observed MLB
run environment.

## Comparison convention

Every delta is calculated as:

    simulation - observed

Negative total-run deltas indicate that the simulation produced fewer
runs than the observed completed-game window. Positive low-total-rate
deltas indicate that the simulation produced too many low-scoring
games.

## Common evidence boundary

Production simulations contain richer plate-appearance and
reached-on-error detail than historical final snapshots. The backtest
therefore normalizes both inputs to the evidence available on both
sides.

Observed opportunities are:

    at_bats + walks + hit_by_pitch

Known reaches are:

    hits + walks + hit_by_pitch

The backtest does not include sacrifice events, catcher interference,
or reached-on-error totals in normalized opportunity or reach rates.

## Low-total decomposition

When simulated mean total runs are below observed mean total runs, the
artifact ranks four signed relative discrepancies:

- opportunity_volume: observed opportunities per game;
- reach_creation: known reaches per observed opportunity;
- power: home runs per observed opportunity; and
- run_conversion: runs per known reach.

largest_negative_component identifies the most negative of those four
measurements only when a low-total signal exists. It is a diagnostic
priority, not a causal conclusion.

The artifact also reports total-run distribution deltas, comparable
raw and normalized metric deltas, total-threshold-rate deltas, source
artifact identities, and a deterministic artifact digest.

## Safety boundary

The backtest consumes already-created artifacts:

- it does not execute additional trials;
- it does not query a database or fetch external data;
- it does not persist results;
- it does not select calibration parameters;
- activation is not permitted;
- production authority is unchanged; and
- causal claims are not permitted.

A later calibration slice may use accumulated backtest evidence to
propose a bounded parameter change, but this artifact cannot activate
one.

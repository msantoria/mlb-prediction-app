# Canonical defensive distribution backtest

This contract compares canonical defensive final-event frequencies
with an externally supplied observed distribution.

## Scope

The backtest measures:

- simulated and observed final-event rates;
- signed rate deltas;
- total variation distance;
- maximum absolute event-rate delta;
- canonical defensive-authority rate;
- conditional original-to-final transition rates; and
- reconciliation blockers.

The observed reference must provide a stable `source_identifier`,
an observation count, and exact final-event counts. The application
does not embed assumed MLB target rates.

## Safety boundary

This is an offline, measurement-only contract. Its diagnostics always
report:

- `measurement_only = true`;
- `activation_permitted = false`; and
- `production_authority_changed = false`.

It does not fetch data, persist results, optimize parameters, alter
probabilities, or activate calibration.

An empty simulation distribution returns `unavailable` with the
`simulation_distribution_empty` blocker. Invalid or non-reconciling
observed counts fail closed.

# Canonical defensive distribution evidence

This artifact combines one caller-owned Statcast observation window
with one canonical defensive-event authority summary.

It executes two existing measurement contracts:

1. source a cutoff-safe observed defensive distribution; and
2. compare the simulated and observed final-event distributions.

## Statuses

- `ready`: both the observed source and comparison are available.
- `unavailable`: the observed source is valid, but the simulation
  summary does not contain comparable observations.
- `error`: input validation or source construction failed. Partial
  source and comparison results are not exposed.

Ready and unavailable artifacts receive a deterministic SHA-256
digest over their complete source and comparison diagnostics.

## Safety boundary

The executor:

- accepts caller-owned rows;
- performs no database query;
- performs no network request;
- performs no external fetch;
- performs no persistence;
- selects no calibration parameters;
- permits no activation; and
- changes no production authority.

This slice packages evidence only. Threshold selection, calibration,
holdout validation, and production activation remain separate,
explicit decisions.

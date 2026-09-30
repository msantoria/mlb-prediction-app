# Canonical defensive trial evidence

This bridge compares the defensive-event authority summary owned by
one completed `CanonicalTrialBatch` against a bounded read-only
Statcast database window.

## Authority ownership

`run_canonical_trials` already gathers defensive authority records
from the exact executed trials used for:

- game-outcome distributions;
- reduced and reconciled box scores; and
- player projection payloads.

The bridge consumes:

```text
trial_batch.diagnostics.defensive_event_authority
```

It does not traverse executed trials or independently aggregate
authority records.

The artifact records the batch simulation count, authority observation
count, and a deterministic SHA-256 digest over the relevant trial
diagnostics and authority summary.

## Execution boundary

The batch-owned summary is passed directly to the canonical defensive
database evidence executor. That executor performs the bounded
read-only Statcast query and the existing distribution comparison.

## Safety boundary

This bridge:

- creates no alternative simulation path;
- performs no independent authority aggregation;
- performs no network request or external fetch;
- performs no persistence;
- selects no calibration parameters;
- permits no activation; and
- changes no production authority.

Operational scheduling, evidence persistence, calibration policy,
holdout validation, and activation remain separate future decisions.

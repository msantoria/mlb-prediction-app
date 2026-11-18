# Canonical production run-environment evidence accumulator

This artifact combines multiple already-created canonical production
run-environment evidence results into one deterministic cohort summary.

## Input boundary

The accumulator consumes CanonicalProductionRunEnvironmentEvidence
objects. It does not execute simulations, query the database, fetch
external data, or recreate any underlying evidence.

Inputs may be ready, unavailable, or error evidence. Exact duplicate
evidence is removed before cohort measurements are calculated.

## Deduplication

Evidence identity is derived deterministically from the complete
evidence diagnostics. Repeated evidence therefore contributes once to
status counts, simulation coverage, scoring summaries, and diagnosis
counts.

Observed artifacts are deduplicated separately by artifact digest.
When several production executions use the same observed window, its
game count contributes once to unique observed coverage.

The artifact reports both input and unique evidence counts so removed
duplicates remain visible.

## Cohort measurements

For ready evidence, the accumulator reports:

- total production simulation count;
- unique observed artifact and observed-game coverage;
- low-total signal count and rate;
- total-run mean-delta distribution;
- total-run relative-delta distribution;
- mean relative delta for opportunity volume, reach creation, power,
  and run conversion; and
- the count of each largest-negative-component diagnosis.

A low-total result without a negative canonical component is recorded
as unattributed rather than silently discarded.

Unavailable blockers and error evidence are counted explicitly. If no
ready evidence exists, the cohort is unavailable with the blocker
ready_evidence_empty.

## Interpretation

The cohort establishes whether the low-total signal is persistent and
which diagnostic component most often ranks as the largest deficit.
It does not prove that the ranked component caused the scoring bias.

The cohort is not yet a calibration proposal. Sample coverage and
diagnostic stability must be evaluated before a bounded sensitivity
experiment selects any candidate adjustment.

## Safety boundary

The accumulator is measurement-only:

- it consumes existing evidence and performs no independent trials;
- it does not access the database or network;
- it does not persist results;
- it does not select calibration parameters;
- causal claims are not permitted;
- activation is not permitted; and
- production authority remains unchanged.

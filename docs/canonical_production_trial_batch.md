# Canonical production trial-batch transport

The production shadow executor creates one CanonicalShadowExecutionBundle.
That bundle owns the exact CanonicalTrialBatch used to construct the attached canonical payload.

The production execution result retains that same batch on
CanonicalProductionShadowExecution.trial_batch.

No additional trial execution or defensive-authority aggregation is performed.

## Coherence contract

For an executed production shadow:

- the exposed batch is the exact object carried by the execution bundle;
- the canonical shadow payload is derived from that exposed batch;
- the number of batch games matches the requested simulation count; and
- downstream evidence consumes the batch-owned defensive authority summary.

Blocked or failed-open executions expose no trial batch.

## Safety boundary

This transport is observational only:

- independent_trial_execution is false;
- no database query, network fetch, or persistence is added;
- no calibration parameter is selected;
- activation_permitted is false;
- production_authority_changed is false; and
- legacy output remains authoritative.

The next slice can pass this production-owned batch to the existing defensive trial-evidence executor without rerunning the simulation.

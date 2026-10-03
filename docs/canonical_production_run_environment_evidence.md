# Canonical production run-environment evidence

This executor composes the complete production-versus-observed
run-environment evidence path for one completed production shadow.

## Evidence path

The executor:

1. consumes an existing CanonicalProductionShadowExecution;
2. measures its exact production-owned CanonicalTrialBatch;
3. queries a bounded FinalGameSnapshot window read-only;
4. constructs the canonical observed run environment;
5. backtests simulated output against observed output; and
6. returns one deterministic evidence artifact.

No additional simulation batch is created. The measured production
artifact comes from the exact trials that produced the production
shadow payload.

## Result states

A result has one of three states:

- ready: production, observed, and backtest artifacts are present;
- unavailable: a known prerequisite is absent, with an explicit blocker;
- error: an invalid input or unexpected source failure is contained.

Known unavailable blockers include:

- production_execution_unavailable;
- database_window_empty; and
- observed_window_incomplete.

Unavailable evidence may retain the completed production measurement
when the observed database window cannot support a comparison.

## Low-total evidence

The composed backtest preserves the simulation-minus-observed
total-run delta, low_total_signal, threshold deltas, and the
largest negative diagnostic component among:

- opportunity_volume;
- reach_creation;
- power; and
- run_conversion.

This identifies where the scoring deficit is most visible. It does
not establish causation and does not select a calibration change.

## Determinism and provenance

The evidence digest covers the date boundary, query state, production
measurement, observed source artifact, backtest artifact, and blocker.
Identical source inputs therefore produce identical evidence.

## Safety boundary

The executor is measurement-only:

- the production execution is consumed, not rerun;
- database access is bounded and read-only;
- no network request or external fetch is performed;
- no result is persisted;
- no calibration parameter is selected;
- causal claims are not permitted;
- activation is not permitted; and
- production authority is unchanged.

A later calibration slice may consume accumulated evidence to propose
a bounded scoring correction. This executor cannot activate one.

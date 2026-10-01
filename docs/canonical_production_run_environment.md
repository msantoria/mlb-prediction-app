# Canonical production run-environment measurement

This measurement summarizes scoring behavior from the exact
CanonicalTrialBatch retained by CanonicalProductionShadowExecution.
It does not run additional simulations.

## Purpose

Production simulations have shown consistently low projected totals
across games. This artifact separates the scoring funnel so later
historical comparison can identify whether suppression begins with:

- plate-appearance volume;
- reaching-base frequency;
- hit and extra-base-hit frequency;
- home-run frequency;
- strikeout frequency;
- conversion of baserunners into runs;
- stolen-base execution;
- defensive-event authority; or
- exact-versus-fallback probability resolution.

## Production ownership

The measurement consumes the production-owned trial batch already
transported on CanonicalProductionShadowExecution. Game outcomes,
box scores, player projections, and this measurement therefore share
the same executed trials.

The artifact verifies that every reduced box score agrees with its
canonical game result for away and home runs. Any mismatch is exposed
through box_score_run_mismatch_count.

## Measurements

The artifact reports:

- away, home, and total-run distributions;
- team shutout rates;
- rates for totals of five through eight runs or fewer;
- the rate of totals reaching at least nine runs;
- per-game plate appearances, hits, walks, strikeouts, home runs,
  extra-base hits, baserunning events, left on base, and errors;
- reach, hit, walk, strikeout, home-run, and extra-base-hit rates;
- runs per recorded reach;
- probability fallback tier counts and fallback rate;
- defensive-authority observation count and authority rate; and
- a deterministic SHA-256 artifact digest.

## Interpretation boundary

This slice measures the simulated run environment only. It does not
compare the results with an observed MLB baseline and does not select
a correction. A following slice will compare these measurements with
a bounded historical window and locate the dominant scoring deficit.

A low total-run mean alone is not enough to justify a multiplier.
Calibration must target the responsible transition or probability
layer while preserving event-derived statistics.

## Safety contract

- trial_batch_consumed is true;
- independent_trial_execution is false;
- measurement_only is true;
- calibration_parameters_selected is false;
- activation_permitted is false;
- production_authority_changed is false; and
- legacy production output remains authoritative.

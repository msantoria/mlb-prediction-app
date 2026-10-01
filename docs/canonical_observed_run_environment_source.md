# Canonical observed run-environment source

This source constructs a bounded observed MLB scoring baseline from
durable final-game snapshots. It is intended for comparison with the
production-owned canonical trial-batch run environment.

## Authoritative inputs

Final scores come from the away_score and home_score columns on
FinalGameSnapshot. Available batting totals come from the normalized
batter lines in payload_json.boxscore. Team errors and left on base
come from payload_json.linescore.totals.

Rows are selected by an explicit official-date window and stable
official_date/game_pk ordering. The source performs one read-only
database query and performs no external fetch.

## Completeness boundary

A snapshot is excluded when it lacks nonnegative final scores,
normalized batter lines, linescore totals, or a positive observed
opportunity count. Query row count and excluded snapshot count remain
visible so incomplete source coverage cannot be hidden.

Historical final snapshots do not retain sacrifice flies, sacrifice
hits, catcher interference, or reached-on-error totals. Therefore this
source does not claim to reconstruct exact plate appearances or total
reaches.

Observed opportunities are explicitly defined as:

    at_bats + walks + hit_by_pitch

Rates using that denominator are named per_observed_opportunity.
Known reaches include hits, walks, and hit by pitch. The next
comparison slice must normalize simulated results to the same
available-data boundary before attributing the low-total bias.

## Measurements

The artifact includes away, home, and total-run distributions;
shutout and total-threshold rates; available batting-event totals per
game; known runs per reach; observed-opportunity scoring rates;
snapshot-version coverage; deterministic query and artifact digests;
and explicit excluded-row accounting.

## Safety

The source is measurement-only:

- database access is read-only;
- no network request or external fetch is performed;
- no row is inserted, updated, or deleted;
- no calibration parameter is selected;
- activation is not permitted; and
- production authority is unchanged.

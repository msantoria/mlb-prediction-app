# Statcast defensive distribution source

This source converts caller-owned terminal Statcast plate appearances into
the observed distribution consumed by the canonical defensive backtest.

## Comparable event mapping

| Statcast event | Canonical event |
| --- | --- |
| `single`, `double`, `triple` | same value |
| `field_error` | `reached_on_error` |
| `field_out`, `force_out`, `fielders_choice_out` | `out` |
| `grounded_into_double_play`, `double_play` | `ground_ball_double_play` |
| `fielders_choice` | `ground_ball_fielders_choice` |
| `sac_fly` | `sacrifice_fly` |

Home runs and non-batted-ball outcomes are excluded because canonical
defensive authority does not resolve them. Unknown terminal event values are
counted separately as unmapped evidence.

## Identity and cutoff rules

- The source window is inclusive.
- `window_end` cannot exceed `through_date`.
- Every terminal row requires positive `game_pk` and `at_bat_number`.
- Exact duplicate terminal rows are counted and deduplicated.
- Conflicting terminal rows for one plate appearance fail closed.
- The canonical terminal collection receives a deterministic SHA-256 digest.

## Safety boundary

Fetching and database queries remain caller-owned. The source does not mutate
records, persist artifacts, select calibration parameters, activate changes,
or alter production simulation authority.

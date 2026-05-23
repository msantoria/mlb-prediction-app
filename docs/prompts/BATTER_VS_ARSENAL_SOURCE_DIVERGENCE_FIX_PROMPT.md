# Batter vs Arsenal Source Divergence Fix Prompt

You are working in the `msantoria/mlb-prediction-app` repo.

Your task is to investigate and then surgically fix a production data consistency bug affecting the matchup detail experience.

## Problem summary

On the matchup detail UI, the pitcher arsenal section shows a larger stored sample for a pitch type, for example `Stored 365` for a Sweeper, and the overview arsenal table shows populated pitch-level metrics. But on the `Batter vs Arsenal` tab or slide for the same game and pitcher, that same pitch type is not always fully populating the expected matchup data.

The key product issue is this:

- the pitcher overview arsenal can show a fuller or fresher pitch inventory
- the `Batter vs Arsenal` tab can show fewer pitch rows or incomplete pitch cards for the same pitcher and pitch type

This is creating a misleading user experience because both screens look like they should be describing the same underlying arsenal context.

## What evidence already shows

The current code strongly suggests the main issue is **source divergence between the overview arsenal path and the competitive Batter vs Arsenal path**, not just a frontend rendering problem.

### Confirmed frontend paths

File:
- `frontend/src/pages/MatchupDetailPage.jsx`

Important components:
- `PitcherCard`
- `CompetitiveBatterRow`
- `PitchTypeWidget`

Important behavior:
- `PitcherCard` prefers `detail.profile_arsenal` and only falls back to `detail.arsenal`
- `CompetitiveBatterRow` renders `matchup.pitch_type_matrix`
- `PitchTypeWidget` renders `pitch.batter_vs_type`
- `sourceLabel(source)` returns `Stored 365` when `source === 'batter_pitch_type_matchups'`

This means the overview card and the competitive card are not necessarily consuming the same backend payload shape or the same data source.

### Confirmed backend overview path

File:
- `mlb_app/app.py`

Route:
- `GET /matchup/{game_pk}`

Important function:
- inside `get_matchup_detail(game_pk)`, inspect `pitcher_detail(pid)`

Current overview arsenal priority is effectively:
1. `refresh_starting_pitcher_arsenal(...)`
2. `get_pitch_arsenal_with_fallback(...)`
3. `_fetch_live_pitch_arsenal(...)`
4. plus separate `profile_arsenal` from `get_pitcher_profile_arsenal(...)`

The frontend `PitcherCard` then prefers `profile_arsenal` over `arsenal`.

### Confirmed backend competitive path

File:
- `mlb_app/app.py`

Route:
- `GET /matchup/{game_pk}/competitive`

Important functions:
- `load_pitcher_arsenal(pitcher_id)`
- `_build_competitive_matchup(...)`
- `_stored_batter_pitch_type_summary(...)`

Current competitive arsenal priority is only:
1. `get_pitch_arsenal_with_fallback(...)`
2. `_fetch_live_pitch_arsenal(...)`

The competitive route does **not** currently reuse the same arsenal-building path as the overview route.
It does **not** use `refresh_starting_pitcher_arsenal(...)`.
It does **not** use `get_pitcher_profile_arsenal(...)`.

That is the biggest red flag in the repo right now.

## Confirmed schema differences

File:
- `mlb_app/database.py`

### Pitcher arsenal storage
Table:
- `pitch_arsenal`

Shape:
- keyed by `season + pitcher_id + pitch_type`

### Batter vs Arsenal storage
Table:
- `batter_pitch_type_matchups`

Shape:
- keyed by `batter_id + opposing_pitcher_id + pitch_type + target_date`

This means the competitive page is joining two different concepts:

- pitcher arsenal inventory from a pitcher-centric table
- batter performance card data from a hitter-centric aggregate table

That is valid product logic, but only if both sides are populated consistently and the route uses the correct shared arsenal source.

## Confirmed competitive lookup behavior

File:
- `mlb_app/app.py`

Function:
- `_stored_batter_pitch_type_summary(...)`

This queries `BatterPitchTypeMatchup` by:
- `batter_id`
- `opposing_pitcher_id`
- `pitch_type`
- optional exact `target_date`

If exact `target_date` misses, it falls back to the latest row for the same batter plus opposing pitcher plus pitch type.

If no row exists, `_build_competitive_matchup(...)` inserts a placeholder payload with:
- `source = 'missing_batter_pitch_type_matchups'`
- zero counts
- null metrics

So one source of missing values is legitimate: the batter aggregate row may not exist.
But that is **separate** from the overview arsenal mismatch.

## Confirmed refresh job behavior

File:
- `scripts/run_hitting_matchups_refresh.py`

This job:
- builds targets by game, lineup, batter, and opposing pitcher
- gets pitcher pitch types
- runs `build_batter_pitch_type_summary(session, batter_id, pitch_type, days_back=DAYS_BACK)`
- upserts rows into `batter_pitch_type_matchups`

Important detail:
- the stored row is materially stricter than the pitcher arsenal row because it is tied to batter plus opposing pitcher plus pitch type plus target date

This means there are two separate failure classes to investigate:
1. the arsenal source used by overview and competitive may differ
2. the batter aggregate row may be missing even when the pitcher arsenal row exists

## Existing repo doc that already points at intended product truth

File:
- `docs/BATTER_ARSENAL_STATCAST_PATH_FIX.md`

That doc states the intended pipeline is:

`statcast_events -> run_hitting_matchups_refresh.py -> batter_pitch_type_matchups -> /matchup/{game_pk}/competitive -> frontend cards`

Use that as a reference, but do not blindly trust that the live code matches it.

## Most likely root cause ranking

Rank the causes in this order unless new evidence overturns it:

1. **Different table or query path than the overview arsenal page**
   - strongest current evidence
   - overview and competitive routes clearly do not share the same arsenal builder

2. **Different season or filter window**
   - overview arsenal path and competitive batter rows are not using identical windows or refresh paths

3. **Wrong join keys on batter-side lookup**
   - real risk because batter rows require `batter_id + opposing_pitcher_id + pitch_type + target_date` while pitcher arsenal only needs `pitcher_id + season + pitch_type`

4. **Pitch type normalization mismatch**
   - still investigate
   - but current code suggests the larger immediate problem is path divergence, not label rendering alone

## What you need to do

### Goal
Make the `Batter vs Arsenal` route use the same effective pitcher arsenal source as the overview route, while preserving the existing batter aggregate lookup and without redesigning the app.

### Required investigation tasks

1. Trace the exact arsenal payload used by:
   - `GET /matchup/{game_pk}`
   - `GET /matchup/{game_pk}/competitive`

2. Confirm whether the richer arsenal shown in the overview page is coming from:
   - `profile_arsenal`
   - `arsenal`
   - `refresh_starting_pitcher_arsenal(...)`
   - or another transformed source

3. Compare the same pitcher and pitch type across both routes and document:
   - pitch type label
   - raw pitch type code
   - pitch count
   - usage pct
   - whiff pct
   - xwOBA
   - source
   - season/window

4. Verify whether the competitive route is dropping pitch rows because:
   - its arsenal source is different
   - batter rows are missing in `batter_pitch_type_matchups`
   - pitch type normalization differs across paths

5. Explicitly inspect pitch type normalization for these values across all relevant code paths:
   - `Sweeper`
   - `ST`
   - `SW`
   - `Slider`
   - `sweeper/slurve`

6. Confirm whether the competitive route should be reading from:
   - `profile_arsenal`
   - refreshed starting pitcher arsenal rows
   - `pitch_arsenal`
   - or a merged canonical arsenal payload

### Required implementation direction

Do **not** do a broad refactor.
Do **not** redesign the frontend contract unless absolutely necessary.
Do **not** touch unrelated pages.

Implement the safest possible fix.

#### Step 1
Update the competitive route arsenal loading path so it matches the overview route priority as closely as possible.

Specifically inspect and likely update `load_pitcher_arsenal(pitcher_id)` inside `GET /matchup/{game_pk}/competitive` so it uses the same effective priority as `pitcher_detail(pid)` in the overview route:

1. `refresh_starting_pitcher_arsenal(...)`
2. `get_pitch_arsenal_with_fallback(...)`
3. `_fetch_live_pitch_arsenal(...)`
4. if appropriate, align with `profile_arsenal` if that is the true canonical source

Do not guess. Confirm which source is actually powering the richer overview table first.

#### Step 2
Add explicit diagnostics to the competitive payload for every pitch row so we can prove what source was used.

At minimum include fields like:
- `arsenal_source`
- `arsenal_source_window`
- `arsenal_source_season`
- `batter_vs_type.source`
- `batter_vs_type.target_date`
- `stored_row_found`

Only add fields that are safe for the frontend contract or can be ignored by the frontend.

#### Step 3
Do not change the batter aggregate lookup semantics unless evidence proves that lookup is wrong.

The batter-side lookup currently uses `batter_pitch_type_matchups`, which is correct product intent. The main problem appears to be that the competitive page arsenal source is not aligned with the overview page arsenal source.

#### Step 4
If, after source parity is fixed, some pitch rows still show missing batter metrics, isolate those as a second-class issue and prove whether they are caused by missing rows in `batter_pitch_type_matchups`.

## Concrete break point to verify

The current likely break point is:

1. `/matchup/{game_pk}` overview route builds a richer arsenal using starting pitcher refresh and/or profile arsenal
2. `/matchup/{game_pk}/competitive` rebuilds arsenal separately using a weaker or different source path
3. `_build_competitive_matchup(...)` then tries to attach batter metrics from `batter_pitch_type_matchups`
4. if the batter row is absent, the pitch card remains partially populated or empty

So the product bug is likely a combination of:
- **arsenal source divergence first**
- **batter row coverage second**

## Validation requirements

Use a real example that matches the current production symptom.

Preferred example:
- Chicago Cubs hitters vs Kai-Wei Teng
- Sweeper
- overview arsenal shows a large stored sample
- Batter vs Arsenal card is incomplete or less populated

For the validation, compare before and after on both endpoints:

### Check 1: overview route
`GET /matchup/{game_pk}`

Confirm:
- `profile_arsenal`
- `arsenal`
- actual source of the pitch row shown in the UI

### Check 2: competitive route
`GET /matchup/{game_pk}/competitive`

For the same pitch row confirm:
- `pitch_type`
- `raw_pitch_type`
- `pitcher_pitch_count`
- `pitcher_usage_pct`
- `pitcher_xwoba`
- `arsenal_source`
- `batter_vs_type.source`
- `batter_vs_type.target_date`
- `batter_vs_type.pitches_seen`

### Expected result after fix
- overview arsenal and competitive arsenal should describe the same effective pitcher arsenal inventory for the same starter and pitch type
- remaining missing batter metrics, if any, should be clearly attributable to absent `batter_pitch_type_matchups` rows rather than the wrong pitcher arsenal source

## Output requirements for your work

1. Make the code change on a new branch
2. Keep the diff surgical
3. Add clear inline comments only where they materially help future debugging
4. Provide a concise engineering note in the PR body covering:
   - root cause
   - files changed
   - why this fix is safe
   - how to validate

## Deliverables

You should complete all of the following:
- implement the surgical source-parity fix
- preserve current production response contracts where possible
- add diagnostics for proof
- open a PR with a precise title and summary

## PR title suggestion

`Align competitive batter-vs-arsenal route with overview pitcher arsenal source`

## Final instruction

Do not stop at a theory. Verify the actual payloads and fix the real source divergence path in code.
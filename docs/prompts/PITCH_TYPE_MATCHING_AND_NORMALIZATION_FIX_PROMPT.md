# Pitch Type Matching and Normalization Cleanup Prompt

You are working in the `msantoria/mlb-prediction-app` repo.

Your job is to make a surgical production fix for pitch-type matching between the matchup detail overview arsenal and the `Batter vs Arsenal` tab.

## Primary goal

Make sure the same real-world pitch is represented consistently across the relevant backend and frontend paths.

In plain terms:
- if the overview arsenal shows a pitch, the competitive Batter vs Arsenal route should refer to that same pitch type correctly
- if pitch types are being mismatched, duplicated under different labels, or missed because of inconsistent codes or names, clean that up
- if one path stores `ST` and another path renders `Sweeper`, make sure the matching logic handles that correctly
- if one path uses a pitch name and another uses a raw code, make sure the join and payload stay consistent

Do not do a broad refactor. Fix the pitch-type matching and normalization problem directly.

## Product issue to solve

The overview arsenal path and the Batter vs Arsenal path can currently drift apart. One major reason may be that pitch types are not normalized consistently across:
- refreshed starting pitcher arsenal rows
- fallback `pitch_arsenal` rows
- live Savant fallback rows
- `batter_pitch_type_matchups`
- competitive matchup payload construction
- frontend display labels

The outcome we want is simple:
- the same pitch should map to the same canonical pitch type everywhere it matters
- Batter vs Arsenal should not miss or fragment pitch rows because of code/name mismatches
- the payload should expose enough diagnostics to prove the pitch type mapping used

## Important confirmed repo facts

### Frontend
File:
- `frontend/src/pages/MatchupDetailPage.jsx`

Relevant behavior:
- `PitcherCard` prefers `detail.profile_arsenal`, then falls back to `detail.arsenal`
- `CompetitiveBatterRow` renders `matchup.pitch_type_matrix`
- `PitchTypeWidget` uses `pitch.pitch_type`, `pitch.raw_pitch_type`, and `pitch.batter_vs_type`
- `PITCH_NAMES` currently maps codes like `ST` to `Sweeper`

### Backend
File:
- `mlb_app/app.py`

Relevant behavior:
- overview route: `GET /matchup/{game_pk}`
- competitive route: `GET /matchup/{game_pk}/competitive`
- competitive payload is built in `_build_competitive_matchup(...)`
- batter-side stored lookup happens in `_stored_batter_pitch_type_summary(...)`
- current label helper `_normalize_pitch_label(pitch_type, pitch_name)` just returns `pitch_name or pitch_type or "Unknown"`

That helper is too weak if the real problem is inconsistent pitch codes versus display names.

### Schema
File:
- `mlb_app/database.py`

Relevant tables:
- `pitch_arsenal`
- `batter_pitch_type_matchups`

Important:
- `pitch_arsenal` rows are pitcher-centric
- `batter_pitch_type_matchups` rows are batter plus opposing pitcher plus pitch_type plus target_date
- if pitch_type values are not normalized consistently, stored batter rows can be missed even when the pitcher arsenal row exists

### Existing refresh job
File:
- `scripts/run_hitting_matchups_refresh.py`

Important:
- this job populates `batter_pitch_type_matchups`
- it determines pitch types for the pitcher and then builds batter summaries by pitch type
- if pitch type values are inconsistent across the system, that job may be writing one representation while the runtime lookup expects another

## Main task

Create one canonical pitch type normalization path for the matchup detail arsenal and Batter vs Arsenal flow.

The fix should focus on these questions:
1. what pitch type code is stored in each source
2. what pitch type name is displayed in each route
3. what pitch type key is used for lookup into `batter_pitch_type_matchups`
4. whether the same real-world pitch is being split across multiple labels or missed because one path uses a code and another uses a display name

## Pitch types that must be audited carefully

At minimum inspect the handling of:
- `ST`
- `Sweeper`
- `SW`
- `SL`
- `Slider`
- `SV`
- `Slurve`
- `sweeper/slurve`
- `FF`
- `Four-Seam`
- `4-Seam`
- `SI`
- `Sinker`
- `FC`
- `Cutter`
- `CH`
- `Changeup`
- `CU`
- `Curveball`
- `KC`
- `Knuckle-Curve`
- `FS`
- `Splitter`

You do not need to invent unsupported mappings, but you do need to eliminate obvious mismatches that can cause missed pitch rows or inconsistent joins.

## What to implement

### 1. Add a canonical pitch type normalization helper

In the safest appropriate backend location, create a normalization helper that can do all of the following:
- take raw pitch code and optional pitch name
- return a canonical pitch code used for matching and storage lookups
- return a canonical display label used for payload output

The helper should handle both code-first and name-first cases.

The key distinction should be:
- canonical lookup key for joins and stored lookups
- canonical display label for frontend rendering

Do not rely on display names alone for joins.

### 2. Use canonical pitch matching in competitive matchup building

In `_build_competitive_matchup(...)`, make sure the pitch rows coming from arsenal sources are normalized before batter-side lookup happens.

Specifically:
- normalize the pitcher arsenal pitch type into a canonical lookup key
- use that canonical lookup key when calling `_stored_batter_pitch_type_summary(...)`
- preserve a human-friendly display label separately
- include both the canonical key and raw values in the payload for diagnostics

### 3. Strengthen `_stored_batter_pitch_type_summary(...)` lookup behavior

Keep the existing contract, but make the lookup more resilient to pitch type mismatches.

You should inspect whether the stored table may contain alternative pitch-type values for the same pitch. If so, make the lookup handle that safely.

Possible safe behavior:
- try canonical pitch type first
- if needed, try a small controlled alias set for known equivalent representations
- do not create a loose fuzzy matcher that could merge truly different pitches incorrectly

The objective is to clean up real mismatches, not blur distinct pitch families.

### 4. Align payload fields

For each competitive pitch row, make sure the payload clearly exposes:
- `pitch_type` as the clean display label
- `raw_pitch_type` as the original source pitch code or raw type
- `canonical_pitch_type` as the lookup key used for matching
- `pitch_name` if useful
- `arsenal_source`
- `stored_row_found`
- `stored_pitch_type` if available from the matched batter row

Only add additive fields that will not break current frontend behavior.

### 5. Confirm whether frontend needs a tiny cleanup

Inspect `frontend/src/pages/MatchupDetailPage.jsx` only if necessary.

If the backend fix is enough, leave the frontend alone.
If the frontend is displaying the wrong label or hiding useful raw information, make only the smallest safe adjustment.

## Important constraints

- do not redesign the app
- do not rewrite the matchup page
- do not change unrelated routes
- do not remove `batter_pitch_type_matchups` as the main batter-side source
- do not merge distinct pitch types just because their names look similar
- do not use a broad fuzzy match
- do not break existing response contracts unless changes are additive and safe

## Where the fix most likely belongs

You will probably need to update:
- `mlb_app/app.py`

You may also need to inspect:
- `scripts/run_hitting_matchups_refresh.py`
- any helper used by arsenal refresh or pitcher profile serialization
- `frontend/src/pages/MatchupDetailPage.jsx`

But keep the code change surgical.

## What success looks like

After the fix:
- the same pitch should not appear under mismatched names between overview and competitive paths
- Batter vs Arsenal should not miss a pitch row just because one path used `ST` and another used `Sweeper`
- payload diagnostics should make it obvious which canonical pitch type was used for matching
- the system should still distinguish genuinely different pitch families, for example `ST` versus `SL`, unless the repo’s real source data proves they must be treated as the same canonical type

## Validation requirements

Use a real example if available.

Preferred example:
- Chicago Cubs hitters vs Kai-Wei Teng
- Sweeper / ST case

### Required checks

#### Overview route
Call:
- `GET /matchup/{game_pk}`

Verify for the target pitch:
- raw pitch code
- pitch name
- displayed label
- pitch count
- source

#### Competitive route
Call:
- `GET /matchup/{game_pk}/competitive`

Verify for the same pitch:
- `raw_pitch_type`
- `canonical_pitch_type`
- `pitch_type`
- `stored_row_found`
- matched batter row source
- whether the pitch row now appears correctly and consistently

### Expected result

The same real-world pitch should now line up across both routes with a stable canonical key and a stable display label.

If a batter row is still missing after normalization is fixed, the payload should prove that the pitch type match succeeded and that the remaining problem is simply absence of stored batter aggregate coverage.

## Deliverables

You must do all of the following:
1. create a new branch
2. make the code change
3. keep the diff surgical
4. add payload diagnostics for proof
5. validate with at least one real pitch-type example
6. commit the changes
7. open a PR

## PR title

Use:
`Normalize pitch type matching for competitive batter-vs-arsenal payloads`

## PR body must include

- exact root cause
- files changed
- which pitch type mappings were normalized
- why the fix is safe
- how to validate with one real example

Now do the actual fix.
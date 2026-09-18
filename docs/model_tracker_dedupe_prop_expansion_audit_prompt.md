# Model Tracker duplicate prevention, prop expansion, and price action audit prompt

Issue: #795

## Goal

Run a required audit area for the Model Tracker: duplicate prevention, individual/player/prop expansion, and sportsbook price-action tracking.

The Model Tracker must avoid duplicate model outputs while producing more unique individual/player/prop betting rows. It must also preserve sportsbook prices over time so we can measure closing line value (CLV) and later use those price histories in Model Projections analysis.

Do not fake props. Do not fake sportsbook prices. Do not rewrite existing production model formulas. This is an audit/reporting task first.

## Scope

Primary files:

- `frontend/src/pages/ModelTrackerPage.jsx`
- `mlb_app/model_tracker.py`
- `mlb_app/model_tracker_safe_snapshot.py`
- `mlb_app/model_tracker_routes.py`
- `tests/test_model_tracker_daily_odds.py`

Sportsbook / price-action files to inspect:

- Bet105 normalized odds provider files
- DraftKings normalized odds provider files, if available
- Odds compare routes and normalized market/selection schemas
- Any scheduled job, cron, or cache layer that can safely trigger hourly snapshots
- Any existing model projection payload code that can consume stored prices later

Related sources to inspect only as needed:

- Daily Odds `top_prop_model_candidates`
- Batter vs Arsenal / LayerSix matchup outputs
- Pitcher advanced profile / strikeout lean outputs
- My Dashboard solver top hitters/top pitchers
- Daily odds prop markets if available
- Bet105/DraftKings normalized prop markets if available
- Existing best plays payloads, if any

## Hard rules

1. Do not fake model rows.
2. Do not fake player props.
3. Do not fake sportsbook prices.
4. Do not create placeholder grades.
5. Do not reduce the current Table View data surface.
6. Do not rewrite existing model formulas.
7. Do not push directly to `main`.
8. Use a branch and PR.
9. Audit/report first; code implementation only after the audit identifies safe additive changes.
10. Start with Bet105 prices if that is the only complete price source. Preserve the architecture so DraftKings/second provider prices can be added beside Bet105.

## Required audit areas

### 1. Database-level duplicates

Inspect `ModelTrackerSnapshot.tracker_key` generation.

Confirm:

- `tracker_key` is stable across repeated snapshot refreshes for the same date.
- Running `POST /model-tracker/snapshot` twice for the same date does not create duplicate rows.
- `tracker_key` is not too broad, causing different player props/picks to collapse into one row.
- `tracker_key` is not too narrow, causing the same pick to be inserted multiple times because of tiny raw payload differences.
- The unique constraint on `tracker_key` is actually enforced in production.
- Upsert behavior updates existing rows instead of inserting duplicates.

### 2. Logical duplicate picks

Check for duplicate rows that are technically different `tracker_key`s but represent the same betting idea.

Detect duplicates by these signatures:

- `snapshot_date + source + game_pk + market_type + pick_type + pick_label`
- `snapshot_date + game_pk + player_id + market_type + line`
- `snapshot_date + game_pk + player_name + market_type + line`
- `snapshot_date + game_pk + team_name + market_type + pick_label`
- `snapshot_date + event_id + market_type + selection + line`
- `snapshot_date + source_component + player_id + pick_type`
- `snapshot_date + normalized player name + normalized market + normalized line`

Report:

- Exact duplicate groups.
- Near-duplicate groups.
- Which source created them.
- Whether duplicates come from matchups, daily odds, model projections, my-dashboard solver, AI prompts, or prop candidate extraction.
- Whether frontend Game Grouped Tracker shows the same idea multiple times.
- Whether Table View shows duplicate logical picks.
- Whether duplicate cards differ only by `source_component`/`model_name` but should be grouped.
- Whether duplicate rows should be merged, ranked, or preserved as separate source votes.

### 3. Frontend duplicate handling

Audit `ModelTrackerPage.jsx` and report:

- Whether the UI dedupes cards or simply renders every row.
- Whether game cards can show repeated picks for the same player/market.
- Whether table rows can repeat identical pick ideas.
- Whether filters make duplicates easier or harder to spot.
- Whether the UI should add:
  - duplicate warning badge
  - grouped duplicate count
  - source votes panel
  - best unique props section
  - unique individuals section
  - row hash/debug key column
  - sort by unique player/prop score

### 4. Individual/player prop coverage

We want the tracker to produce more unique individual players and prop bets somewhere.

Audit current row sources and report:

- Which sources currently generate player-level rows.
- Which sources generate team/game-only rows.
- Which sources generate prop/watchlist rows.
- Whether `top_prop_model_candidates` are populated.
- Whether hitter props are captured.
- Whether pitcher props are captured.
- Whether batter-vs-arsenal outputs are converted into trackable player prop candidates.
- Whether pitcher strikeout/outs/earned-runs style candidates are produced.
- Whether total bases, hits, RBI, HR, runs, walks, strikeouts, stolen bases, and pitcher Ks are available from existing model data.
- Whether `player_id` is consistently present.
- Whether player-name-only rows need stable identity resolution.
- Whether sportsbook line/price is present for prop rows.
- Whether prop rows are gradeable today or watchlist-only.
- Whether missing sportsbook line prevents grading.

### 5. Prop generation opportunities

Do not fake props. Only use existing model/source data.

Find safe places to create additive prop candidates from existing data:

- Daily Odds `top_prop_model_candidates`
- Batter vs Arsenal / LayerSix matchup outputs
- Pitcher advanced profile / strikeout lean outputs
- My Dashboard solver top hitters/top pitchers
- Daily odds prop markets if available
- Bet105/DraftKings normalized prop markets if available
- Existing best plays payloads, if any

For each candidate source, report:

- File/function that owns the data.
- Fields available.
- Whether `player_id` exists.
- Whether market type exists.
- Whether line and sportsbook price exists.
- Whether model probability exists.
- Whether confidence/score exists.
- Whether actual result mapping exists.
- Whether it should be gradeable or watchlist-only.
- What tracker row shape should be emitted.

### 6. Bet105 price action and CLV snapshotting

This is required. The Model Tracker needs prices, not just model scores. We need stored price history so later model-projection analysis can evaluate:

- opening/first-seen price
- hourly movement
- best available price during tracking window
- last price before first pitch
- closing line value
- model edge versus market implied probability at each snapshot time

Start with Bet105 numbers if they are the only reliable normalized prices today. Keep the schema and naming provider-aware because we now have two source providers and will need to compare Bet105 vs the second provider later.

Audit and design:

1. Current price availability
   - Which Model Tracker rows already have `price`, `line`, `market_implied_probability`, and sportsbook/provider metadata?
   - Which rows are missing Bet105 price/line even though a matching Bet105 market exists?
   - Which rows can match to Bet105 by `event_id + market_type + selection + line`?
   - Which rows need player/team identity normalization before price matching?
   - Which prop candidates can receive a Bet105 price today?
   - Which game/team picks can receive a Bet105 moneyline, spread, or total today?

2. Price snapshot storage
   Recommend a safe additive backend persistence model. Prefer a separate price snapshot table rather than overloading the existing `model_tracker_snapshots` row if hourly price history would create repeated rows.

   Suggested table shape:
   - `id`
   - `snapshot_date`
   - `captured_at`
   - `game_pk`
   - `event_id`
   - `provider` (`bet105`, `draftkings`, etc.)
   - `market_type`
   - `market_key`
   - `selection_key`
   - `selection_label`
   - `player_id`
   - `player_name`
   - `team_name`
   - `line`
   - `price`
   - `decimal_price`
   - `implied_probability`
   - `raw_market_id`
   - `raw_selection_id`
   - `source_endpoint`
   - `raw_payload_json`
   - `created_at`

   Required uniqueness guidance:
   - Do not make uniqueness so broad that it loses hourly movement.
   - Do not make uniqueness so narrow that repeated refreshes in the same hour create dupes.
   - Suggested logical key: `snapshot_date + provider + event_id + market_key + selection_key + normalized line + captured_hour`.
   - If using exact `captured_at`, bucket to hour or store an explicit `snapshot_bucket` for idempotency.

3. Hourly snapshot cadence
   We need snapshotting every hour from when odds are first available until first pitch.

   Audit how to determine:
   - first odds availability time
   - game start / first pitch time
   - pregame cutoff
   - whether live odds should be excluded from CLV tracking
   - what to do with postponed/rescheduled games
   - how to avoid duplicate hourly jobs

   Recommend implementation options:
   - cron job that calls a backend endpoint hourly
   - internal scheduled task if already available
   - manual admin endpoint first, cron later
   - lazy snapshot on page load only as fallback, not primary CLV tracking

4. CLV metrics
   Recommend fields and calculations:
   - `first_seen_price`
   - `first_seen_implied_probability`
   - `current_price`
   - `current_implied_probability`
   - `closing_price`
   - `closing_implied_probability`
   - `best_price_seen`
   - `worst_price_seen`
   - `price_move_american`
   - `implied_probability_move`
   - `clv_american`
   - `clv_implied_probability`
   - `beat_close` boolean
   - `snapshot_count`
   - `first_seen_at`
   - `last_seen_before_start_at`

5. Model Tracker integration
   Recommend how Model Tracker rows should expose prices without duplicating every hourly price row in the main tracker table:
   - current/best/closing price summary columns
   - price action drawer/detail panel
   - provider comparison mini-table
   - CLV badge once closing line is known
   - source provider column
   - price stale/missing badge

6. Model Projections integration
   Recommend how stored price snapshots can feed later Model Projections analysis:
   - join by game/player/market/line/provider
   - evaluate model edge at snapshot time
   - compare model recommendation timestamp versus closing line
   - compute CLV by model source/component
   - evaluate whether Bet105 moved toward or against model picks
   - produce historical calibration by model version and market type

7. Production checks
   Include endpoint checks for Bet105 pricing:

   ```bash
   curl -sS "https://mlbgpt.com/odds/bet105/events?date=YYYY-MM-DD&live=false" | jq '{status, event_count, market_count}'
   curl -sS "https://mlbgpt.com/odds/compare/events?date=YYYY-MM-DD&books=bet105,draftkings" | jq '{event_count, market_count}'
   ```

   If a price snapshot endpoint exists after implementation, verify:

   ```bash
   curl -sS -X POST "https://mlbgpt.com/odds/price-snapshots?date=YYYY-MM-DD&provider=bet105" | jq .
   curl -sS "https://mlbgpt.com/odds/price-snapshots?date=YYYY-MM-DD&provider=bet105" | jq '{snapshots: (.snapshots | length)}'
   ```

### 7. Required new tracker sections

Recommend whether the frontend should add these sections.

#### A. Unique Individual Watchlist

Purpose: show one row per player per date, deduped across all model sources.

Suggested grouping:

- `snapshot_date + player_id`
- fallback `normalized player_name + team_name`

Fields:

- player
- team
- game
- best source
- top market candidate
- score
- confidence
- reason
- number of source votes
- missing inputs
- gradeability status
- current Bet105 price if matched
- first-seen Bet105 price if matched
- closing Bet105 price when available
- CLV status when available

#### B. Unique Prop Candidates

Purpose: show one row per player-market-line candidate, deduped and ranked.

Suggested grouping:

- `snapshot_date + game_pk + player_id + market_type + line`

Fields:

- player
- market
- line
- sportsbook price if available
- provider
- model probability if available
- market implied probability if available
- edge if available
- expected value if available
- confidence
- source votes
- grade status
- gradeability reason
- first-seen price
- last pregame price
- closing line value
- number of hourly price snapshots

#### C. Duplicate Review

Purpose: debug and prevent repeated cards/picks.

Suggested grouping:

- logical duplicate signatures above

Fields:

- duplicate signature
- row count
- sources
- row IDs/tracker_keys
- pick labels
- recommendation: merge / preserve / fix key / ignore

#### D. Price Action / CLV Review

Purpose: debug and analyze line movement for model-tracked plays.

Suggested grouping:

- `snapshot_date + provider + event_id + market_key + selection_key + line`

Fields:

- provider
- game
- market
- selection
- line
- first seen price
- best seen price
- last pregame price
- closing price
- CLV
- snapshot count
- first seen timestamp
- last pregame timestamp
- linked tracker rows / model sources

### 8. Acceptance criteria

The audit is not complete unless it answers:

- Are duplicate rows currently possible?
- Are duplicate rows currently happening?
- Can repeated snapshot refreshes create duplicates?
- Are duplicate `tracker_key`s prevented at the DB layer?
- Are logical duplicate picks visible in the UI?
- Which source creates the most duplicates?
- Which player/prop rows are currently being produced?
- Why are there not more individual/player props?
- What is the safest additive place to create more individual/player prop rows?
- Which prop rows can be graded now?
- Which prop rows must remain watchlist-only until result mapping exists?
- Are Bet105 prices currently captured in Model Tracker rows?
- Which rows can be matched to Bet105 prices today?
- What price fields need to be added to the backend?
- What hourly snapshot table or endpoint should be added?
- How will repeated hourly snapshots avoid duplicate price rows?
- How will CLV be computed after first pitch / close?
- How will price history flow into Model Projections later?

### 9. Tests to add or recommend

- Snapshot idempotency: same date snapshot twice does not increase row count.
- Tracker key stability: same source payload creates same `tracker_key`.
- Logical dedupe utility: duplicate player-market-line rows are detected.
- Prop candidate normalization: player prop candidate includes `player_id`, `player_name`, `market_type`, `pick_label`, `line`, `score`, `confidence`.
- Watchlist-only prop rows do not get fake won/lost grades.
- Gradeable moneyline side rows still grade correctly.
- Frontend duplicate grouping does not hide unique rows.
- Frontend unique prop section renders one row per player-market-line.
- Bet105 price matcher links a tracker moneyline/total/prop row to the correct provider price.
- Hourly price snapshot idempotency: same provider/date/hour run does not create duplicate price rows.
- Price snapshot uniqueness preserves multiple hours of movement.
- CLV calculator correctly compares first-seen/current/best/closing prices.
- Missing price rows produce explicit `price_unavailable` status, not fake prices.

### 10. Required final recommendations

Include a specific implementation plan for:

- Preventing duplicate inserts.
- Detecting logical duplicate picks.
- Showing duplicate warnings in the UI.
- Producing more unique individual/player rows.
- Producing more prop candidate rows.
- Keeping non-gradeable props as watchlist-only until actual result mapping exists.
- Adding Bet105 price matching to Model Tracker rows.
- Adding hourly Bet105 price snapshot persistence from first odds availability through first pitch.
- Computing CLV and exposing it in Model Tracker.
- Keeping schema provider-aware for the second provider.
- Feeding price history into Model Projections analysis.

Also include:

- Whether duplicates exist today.
- Whether duplicates are DB duplicates, logical duplicates, or UI duplicates.
- The exact duplicate signatures used to test.
- How many unique individuals are produced.
- How many unique prop candidates are produced.
- Why individual/player prop volume is low.
- The safest next implementation to increase prop volume without faking data.
- Whether Bet105 price action can be captured today.
- What endpoint/job should snapshot prices hourly.
- What table/schema should store price snapshots.
- What CLV fields should appear in the Model Tracker.

## Endpoint checks

Use these checks during the audit against local and production as available:

```bash
curl -sS https://mlbgpt.com/model-tracker/health | jq .
curl -sS "https://mlbgpt.com/model-tracker?date=YYYY-MM-DD" | jq '.rows | length'
curl -sS -X POST "https://mlbgpt.com/model-tracker/snapshot?date=YYYY-MM-DD" | jq .
curl -sS "https://mlbgpt.com/model-tracker?date=YYYY-MM-DD" | jq '{rows: (.rows | length), games: (.games | length)}'
curl -sS -X POST "https://mlbgpt.com/model-tracker/results/refresh?date=YYYY-MM-DD" | jq .
curl -sS "https://mlbgpt.com/odds/bet105/events?date=YYYY-MM-DD&live=false" | jq '{status, event_count, market_count}'
curl -sS "https://mlbgpt.com/odds/compare/events?date=YYYY-MM-DD&books=bet105,draftkings" | jq '{event_count, market_count}'
```

## Final output format

Produce a markdown audit report with:

1. Executive summary
2. Duplicate findings
3. Current player/prop coverage
4. Source-by-source prop opportunity table
5. Bet105 price availability and matching findings
6. Hourly price snapshot design
7. CLV calculation design
8. Frontend duplicate/visibility findings
9. Database duplicate/key findings
10. Recommended unique individual section
11. Recommended unique prop candidate section
12. Recommended duplicate review section
13. Recommended price action / CLV section
14. Tests to add
15. Files to change later
16. Safe implementation sequence
17. Final verdict

## Intended implementation sequence after audit

1. Add provider-aware price snapshot persistence for Bet105 pregame odds.
2. Add an idempotent backend endpoint/job that captures Bet105 prices once per hour from first odds availability until first pitch.
3. Add price matching between Model Tracker rows and Bet105 market selections.
4. Add CLV summary calculation once last pregame/closing price is known.
5. Add UI visibility without reducing the existing Table View: price columns, CLV badges, and a Price Action / CLV Review section.
6. Expand to the second provider using the same schema once its normalized market/selection contract is verified.

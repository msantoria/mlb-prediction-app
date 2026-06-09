# KIBL Bet105 Feed 171 Integration

This document describes the integration of the KIBL Bet105 sportsbook feed (`feed_source_id` **171**) into the MLB prediction app.  The goal of the integration is to ingest fixtures and market data from KIBL, persist it in the database, and surface it through existing odds and prediction pipelines.

## Overview

KIBL provides a REST API for sportsbook data under `https://api.kibl.io/sports/get/`.  Authentication is handled via AWS Cognito and the KIBL user account credentials.  The integration uses two core endpoints:

* `POST /info/fixtures/` — Returns fixture (event) data, including metadata about each game.
* `POST /info/markets/` — Returns market and odds data for fixtures, including individual selections and pricing.

Both endpoints accept a JSON body with a set of filters.  Key parameters include:

| Parameter             | Description                                                   |
|----------------------|---------------------------------------------------------------|
| `feed_source_id`     | Sportsbook feed identifier (`171` for Bet105).               |
| `betting_type_id`    | Betting type (`1` for prematch, `3` for live).               |
| `league_id`          | Comma-separated league IDs (default: `20,643`).              |
| `from_cache`         | Whether to return cached data (always `false` for fresh data). |
| `since_last_updated` | Optional timestamp (`YYYY-MM-DD HH:MM:SS` Eastern) for diffs.  |

Unknown or unsupported parameters will be ignored by the API.  The integration intentionally omits `request_uuid` and `requested` fields because the KIBL server populates them automatically.

## Authentication

Authentication uses the AWS Cognito **USER_PASSWORD_AUTH** flow.  The app must provide a Cognito client ID and region along with a KIBL username and password.  Tokens are retrieved from the Cognito user pool and then passed to KIBL via the `Authorization: Bearer <token>` header.  When KIBL returns `401 Unauthorized`, the integration refreshes the token and retries once.

### Required environment variables

Set the following variables in the backend service environment (e.g. via Railway or a `.env` file).  Do not commit secrets to the repository.

```bash
KIBL_COGNITO_REGION=us-west-2
KIBL_COGNITO_CLIENT_ID=3udv7qsqgju8c4riqvk72bqcl
KIBL_USERNAME=your_kibl_username
KIBL_PASSWORD=your_kibl_password
KIBL_BASE_URL=https://api.kibl.io/sports/get
KIBL_FEED_SOURCE_ID=171
KIBL_PREMATCH_BETTING_TYPE_ID=1
KIBL_LIVE_BETTING_TYPE_ID=3
KIBL_FROM_CACHE=false
KIBL_DEFAULT_LEAGUE_IDS=20,643
KIBL_POLL_INTERVAL_SECONDS=60
```

Do **not** log or expose the values of `KIBL_USERNAME`, `KIBL_PASSWORD`, or the access token.  The integration code redacts secrets from all log messages.

## Baseline vs Diff polling

When first syncing a set of fixtures or markets, make a **baseline** request without a `since_last_updated` field.  This returns all records for the specified filters.  Persist the results and record the newest of the `last_updated` or `inserted_on` timestamps as a watermark.

Subsequent syncs should perform **diff** polling by including the stored watermark as `since_last_updated`.  When the diff returns an empty result, there have been no changes since the last poll and the watermark should remain unchanged.  If the diff contains updates, process and persist them, then update the watermark to the newest timestamp from the diff.  Always perform idempotent upserts to avoid duplicating records.

Timestamps in KIBL responses are in **US Eastern** time.  They are plain strings (`YYYY-MM-DD HH:MM:SS`) rather than UTC/Z timestamps.  The integration must treat them as Eastern and store them as such in the database, or convert to UTC with care.

## Running a sync locally

To execute a baseline or diff sync manually, set the required environment variables and run the sync functions (to be implemented) from within the project root:

```bash
export KIBL_USERNAME=... KIBL_PASSWORD=...
python -m mlb_app.sync.kibl_sync --mode baseline --betting_type prematch
python -m mlb_app.sync.kibl_sync --mode diff --betting_type live
```

Replace `prematch` with `live` for live markets.  The CLI module `mlb_app.sync.kibl_sync` does not exist yet; it will be added during implementation.

## Database tables

The integration introduces three new tables via SQLAlchemy models:

| Table                          | Purpose                                                         |
|--------------------------------|-----------------------------------------------------------------|
| `kibl_fixtures`                | Normalized fixture/event records with raw payload JSON.         |
| `kibl_markets`                 | Normalized market and odds records with raw payload JSON.       |
| `kibl_sync_watermarks`         | Tracks the latest `last_updated` or `inserted_on` per endpoint. |

Models will be defined in `mlb_app/integrations/kibl/models.py` and registered with the global `Base` to create tables during migrations.  Each model includes `created_at` and `updated_at` timestamps and uses idempotent upserts keyed on external identifiers and feed_source_id.

## Admin routes and scheduling

For observability and manual control, the backend may expose admin routes (protected by existing authentication) to trigger baseline and diff syncs and to read the latest sync status.  In production, periodic polling should be scheduled using the existing job scheduler or a lightweight task runner.  The poll interval is configurable via `KIBL_POLL_INTERVAL_SECONDS`.

## Security considerations

* **Never send the KIBL user password to the KIBL API.**  It is only used to authenticate with Cognito.
* **Do not log sensitive data.**  Mask or omit tokens, passwords, and personally identifiable information from logs and error messages.
* **Respect rate limits.**  While KIBL does not document explicit limits, excessive polling could lead to throttling.  Use a sensible default interval (60 seconds) and back off when no diffs are returned.

## Troubleshooting

* **401 Unauthorized** — The access token has expired or is invalid.  The client automatically refreshes the token and retries once.  If 401 persists, verify your credentials and Cognito configuration.
* **Empty diff response** — No updates since the last watermark.  Leave the watermark unchanged and continue polling.
* **Unexpected fields or missing data** — The KIBL API may evolve.  Preserve the raw payload JSON in the database to aid debugging and adjust normalization logic as needed.
* **Time skew issues** — Ensure that the server clock is accurate.  Since KIBL timestamps are Eastern time, converting to UTC incorrectly can cause missed updates.

---

For a detailed implementation plan, see issue #688.  The integration modules live under `mlb_app/integrations/kibl/`.  Contributions should be accompanied by unit tests in the `tests/` directory.

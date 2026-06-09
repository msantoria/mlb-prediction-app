# KIBL Bet105 feed 171 integration

This integration pulls Bet105 fixtures and markets from KIBL into the backend database so the app can compare sportsbook lines against model outputs.

## Runtime flow

```text
Scheduled job / worker
    ↓
Get Cognito token
    ↓
Pull KIBL fixtures baseline
    ↓
Store fixtures in DB
    ↓
Pull KIBL markets baseline
    ↓
Store odds/markets in DB
    ↓
Every X seconds/minutes:
        call same endpoints with since_last_updated
        upsert changed rows
        update watermark
```

## Environment variables

Do not commit real values.

```env
KIBL_COGNITO_REGION=us-west-2
KIBL_COGNITO_CLIENT_ID=3udv7qsqgju8c4riqvk72bqcl
KIBL_USERNAME=
KIBL_PASSWORD=
KIBL_BASE_URL=https://api.kibl.io/sports/get
KIBL_FEED_SOURCE_ID=171
KIBL_DEFAULT_LEAGUE_IDS=20,643
KIBL_FROM_CACHE=false
DATABASE_URL=sqlite:///mlb.db
```

## Important constants

- Bet105 feed source: `feed_source_id=171`
- Prematch betting type: `betting_type_id=1`
- Live betting type: `betting_type_id=3`
- Fixture path: `info/fixtures`
- Market path: `info/markets`
- KIBL watermark format: US Eastern `YYYY-MM-DD HH:MM:SS`

## Authentication

`mlb_app.kibl_integration.KiblAuthClient` calls Amazon Cognito `InitiateAuth` with `USER_PASSWORD_AUTH` using environment values. The password is only sent to Cognito. KIBL receives only:

```http
Authorization: Bearer <access token>
```

The client caches the access token in memory and refreshes/re-authenticates when KIBL returns `401`, then retries the KIBL request once.

## Baseline sync

Baseline calls do not include `since_last_updated`.

```bash
python scripts/sync_kibl_bet105.py --baseline --prematch
python scripts/sync_kibl_bet105.py --baseline --live
```

Fixtures only:

```bash
python scripts/sync_kibl_bet105.py --baseline --prematch --fixtures-only
```

Markets only:

```bash
python scripts/sync_kibl_bet105.py --baseline --prematch --markets-only
```

## Diff sync

Diff calls read the stored watermark for the endpoint/filter and include it as `since_last_updated`.

```bash
python scripts/sync_kibl_bet105.py --diff --prematch
python scripts/sync_kibl_bet105.py --diff --live
```

If KIBL returns no rows, the sync no-ops safely and leaves the previous watermark unchanged.

## Persistence

The integration defines three SQLAlchemy models in `mlb_app.kibl_integration`:

- `KiblFixture`
- `KiblMarket`
- `KiblSyncWatermark`

The sync stores normalized fields where they are available and always preserves `raw_payload` JSON for forward compatibility with KIBL schema changes.

## Scheduling

The repo can wire the CLI into the existing deployment scheduler/worker. A safe default cadence is controlled outside this module, for example every 60 seconds for live and less frequently for prematch. Keep the cadence configurable in hosting/runtime configuration.

## Troubleshooting

### 401 from KIBL

The client automatically re-authenticates with Cognito and retries once. If it still fails, verify `KIBL_USERNAME`, `KIBL_PASSWORD`, region, and client id.

### Empty diff response

Usually means no rows changed since the stored `since_last_updated` watermark. This is not an error.

### Duplicate rows

The module uses stable keys and idempotent upserts. If duplicates appear, inspect whether KIBL changed identifiers for fixture/market/selection rows and adjust the key extraction candidates.

### Timestamp issues

KIBL expects US Eastern timestamp strings in `YYYY-MM-DD HH:MM:SS`, not UTC ISO strings with `Z`.

## Security boundaries

- Do not log `KIBL_PASSWORD`.
- Do not log full access tokens.
- Do not commit credentials.
- Do not expose sync endpoints publicly.
- Tests must mock Cognito and KIBL; CI should not call live KIBL.

# Model Projection Game-Day Warming

Model Projections serves precomputed artifacts and does not run heavyweight
simulation work inside a user GET request.

## Railway service

Create a dedicated Railway cron service using
`railway.game-day-warm-cron.json`. Configure its cron schedule as:

`0 * * * *`

The service calls the production web service for today and tomorrow, using the
America/New_York business date. It no longer warms yesterday, today, and tomorrow:
past dates must use saved artifacts, not repeated simulations of completed games.

The configured timeout remains 180 seconds. Production diagnostics on September
22 showed builds lasting up to 1,279 seconds, so this timeout is **not** evidence
that a build completed. A timeout does not cancel work already running on the API.
After a projection error the warmer defers the next projection build, continues
lightweight/non-projection actions, reports `status: failed`, and exits nonzero.
It never automatically retries a timed-out projection POST. A later scheduled
run can try again; the API's existing process lock prevents overlapping builds.
This patch reduces waste but does not move simulation CPU off the web service or
eliminate HTTP gateway timeouts. Railway logs and successful warm completion are
required for production acceptance.

The warmer must run after every deployment and hourly during game days.
A successful model-projection snapshot reports `warmed: true` and a positive
`games_cached` count when MLB games exist for the date.

## Read behavior

`GET /models/projections` remains read-only. When an artifact is unavailable,
it returns `data_status: not_ready` and an explanatory message. The frontend
must not persist that transient response in its 30-minute browser cache.

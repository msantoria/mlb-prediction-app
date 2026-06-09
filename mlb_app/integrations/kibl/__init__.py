"""KIBL integration package.

This package provides authentication and API client helpers for the
KIBL sportsbook feed.  The implementation follows the AWS Cognito
authentication flow and wraps the KIBL `/info/fixtures/` and
`/info/markets/` endpoints with a thin client.

Modules:

- ``auth`` – handles Cognito authentication and token management.
- ``client`` – provides a typed HTTP client for KIBL endpoints.

The classes defined here are intended for use by the KIBL sync jobs in
``mlb_app/sync`` (to be implemented) and should not be imported by
FastAPI routes directly.  See ``docs/kibl-bet105.md`` for a
high‑level overview of the integration.
"""

from .auth import KiblAuthClient  # noqa: F401
from .client import KiblApiClient  # noqa: F401

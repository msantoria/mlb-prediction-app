"""HTTP client for the KIBL sportsbook API.

This module exposes a :class:`KiblApiClient` which wraps the KIBL
``/info/fixtures/`` and ``/info/markets/`` endpoints.  It handles
construction of the request payload, bearer token injection, 401
refresh retries, and basic response validation/normalization.

The client depends on :class:`~mlb_app.integrations.kibl.auth.KiblAuthClient`
for authentication.  Instantiate both and use the API client to
perform requests::

    auth = KiblAuthClient()
    api = KiblApiClient(auth)
    fixtures = api.fetch("info/fixtures", betting_type_id=1, league_id="20,643")

Refer to ``docs/kibl-bet105.md`` for usage examples and integration
details.
"""

from __future__ import annotations

import json
import os
from typing import Any, Dict, Optional

import requests

from .auth import KiblAuthClient, KiblAuthError


class KiblApiError(Exception):
    """Raised for HTTP or application errors from KIBL."""


class KiblApiClient:
    """Simple HTTP client for the KIBL sportsbook endpoints.

    Parameters
    ----------
    auth: KiblAuthClient
        Authentication client used to obtain bearer tokens.  If a
        request returns 401, the client will force a token refresh and
        retry once.
    base_url: str, optional
        Base URL for KIBL API calls.  Defaults to the value of
        ``KIBL_BASE_URL`` environment variable or
        ``https://api.kibl.io/sports/get``.  The trailing slash is
        stripped automatically.
    """

    def __init__(self, auth: KiblAuthClient, base_url: Optional[str] = None) -> None:
        self.auth = auth
        self.base_url = (base_url or os.getenv("KIBL_BASE_URL", "https://api.kibl.io/sports/get")).rstrip("/")

    def _post(self, path: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Internal helper to POST JSON to the given path.

        Automatically injects the bearer token and retries once on
        unauthorized responses.  Raises :class:`KiblApiError` on
        non‑success status codes or JSON parsing failures.
        """
        url = f"{self.base_url}/{path.strip('/')}/"
        # Compose a copy of payload to avoid mutating caller's object.
        body = dict(payload)
        # Do not send request_uuid or requested.
        body.pop("request_uuid", None)
        body.pop("requested", None)
        headers = {"Content-Type": "application/json"}
        token: Optional[str] = None
        for attempt in range(2):  # allow one retry after token refresh
            try:
                token = self.auth.get_token(force_refresh=(attempt == 1))
            except KiblAuthError as exc:
                raise KiblApiError(f"Authentication error: {exc}")
            if token:
                headers["Authorization"] = f"Bearer {token}"
            try:
                resp = requests.post(url, data=json.dumps(body), headers=headers, timeout=15)
            except Exception as exc:
                raise KiblApiError(f"Failed to reach KIBL endpoint: {exc}")
            if resp.status_code == 401 and attempt == 0:
                # force refresh and retry once
                continue
            if resp.status_code != 200:
                raise KiblApiError(f"KIBL API returned status {resp.status_code}")
            try:
                return resp.json()
            except Exception as exc:
                raise KiblApiError(f"Failed to parse KIBL response: {exc}")
        # If we exit the loop without return, raise generic error.
        raise KiblApiError("Exceeded authentication retries for KIBL API call")

    def fetch(
        self,
        path: str,
        *,
        feed_source_id: Optional[int] = None,
        betting_type_id: Optional[int] = None,
        league_id: Optional[str] = None,
        from_cache: Optional[bool] = None,
        since_last_updated: Optional[str] = None,
        **extra_filters: Any,
    ) -> Dict[str, Any]:
        """Fetch fixtures or markets from KIBL.

        Parameters
        ----------
        path: str
            Endpoint path, e.g. ``info/fixtures`` or ``info/markets``.
        feed_source_id: int, optional
            Sportsbook feed ID.  Defaults to ``KIBL_FEED_SOURCE_ID``.
        betting_type_id: int, optional
            Betting type (1 for prematch, 3 for live).  Defaults to
            ``KIBL_PREMATCH_BETTING_TYPE_ID`` when unspecified.
        league_id: str, optional
            Comma‑separated league IDs.  Defaults to
            ``KIBL_DEFAULT_LEAGUE_IDS``.
        from_cache: bool, optional
            Whether to allow cached responses.  Defaults to
            ``KIBL_FROM_CACHE`` (environment variable) or ``False``.
        since_last_updated: str, optional
            Timestamp string in US Eastern ``YYYY-MM-DD HH:MM:SS`` to
            request a diff since the last sync.
        extra_filters: dict
            Additional filters supported by KIBL.  Unknown keys are
            passed through as-is.
        """
        payload: Dict[str, Any] = {}
        # Apply defaults from environment if not provided.
        payload["feed_source_id"] = feed_source_id if feed_source_id is not None else int(os.getenv("KIBL_FEED_SOURCE_ID", "171"))
        if betting_type_id is not None:
            payload["betting_type_id"] = betting_type_id
        else:
            # default to prematch
            payload["betting_type_id"] = int(os.getenv("KIBL_PREMATCH_BETTING_TYPE_ID", "1"))
        if league_id is not None:
            payload["league_id"] = league_id
        else:
            payload["league_id"] = os.getenv("KIBL_DEFAULT_LEAGUE_IDS", "20,643")
        if from_cache is not None:
            payload["from_cache"] = bool(from_cache)
        else:
            payload["from_cache"] = os.getenv("KIBL_FROM_CACHE", "false").strip().lower() in {"1", "true", "yes", "y", "on"}
        if since_last_updated:
            payload["since_last_updated"] = since_last_updated
        # Include any extra filters (do not overwrite default keys).
        for key, value in extra_filters.items():
            if key in payload:
                continue
            payload[key] = value
        return self._post(path, payload)

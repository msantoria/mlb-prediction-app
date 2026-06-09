"""AWS Cognito authentication for the KIBL sportsbook API.

The :class:`KiblAuthClient` encapsulates the logic required to obtain
and refresh a bearer token for the KIBL API.  Tokens are issued by
AWS Cognito via the ``USER_PASSWORD_AUTH`` flow and expire after a
period of time (configured on the Cognito user pool).  This module
does not log the user's password or full token values and only stores
the minimal information necessary to retry KIBL requests on a 401.

Environment variables:

``KIBL_COGNITO_REGION``
    AWS region for the Cognito user pool (e.g. ``us-west-2``).

``KIBL_COGNITO_CLIENT_ID``
    Cognito app client ID used to initiate the auth flow.

``KIBL_USERNAME`` and ``KIBL_PASSWORD``
    Credentials for the KIBL user.  Only sent to Cognito; never to
    KIBL directly.

Usage example::

    from mlb_app.integrations.kibl import KiblAuthClient
    auth_client = KiblAuthClient()
    token = auth_client.get_token()

The returned ``token`` can be passed to :class:`KiblApiClient` which
will automatically refresh it on 401 responses.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from typing import Any, Dict, Optional

import requests


@dataclass
class _AuthTokens:
    """Container for access and refresh tokens with expiry information."""

    access_token: str
    expires_at: float  # epoch seconds when the token expires


class KiblAuthError(Exception):
    """Raised when authentication with Cognito fails."""


class KiblAuthClient:
    """Authenticate a KIBL user via AWS Cognito.

    This client performs the ``InitiateAuth`` call against
    ``https://cognito-idp.<region>.amazonaws.com/`` using the
    ``USER_PASSWORD_AUTH`` flow.  It caches the resulting access
    token in memory until it expires.  Call :meth:`get_token` to
    obtain a valid token for API requests.  If a token has expired
    or is otherwise invalidated, it will automatically reauthenticate.
    """

    def __init__(self) -> None:
        self._region: str = os.getenv("KIBL_COGNITO_REGION", "").strip()
        self._client_id: str = os.getenv("KIBL_COGNITO_CLIENT_ID", "").strip()
        self._username: str = os.getenv("KIBL_USERNAME", "").strip()
        self._password: str = os.getenv("KIBL_PASSWORD", "").strip()
        self._tokens: Optional[_AuthTokens] = None
        if not self._region or not self._client_id:
            raise KiblAuthError(
                "KIBL_COGNITO_REGION and KIBL_COGNITO_CLIENT_ID environment variables must be set"
            )

    def _initiate_auth(self) -> _AuthTokens:
        """Perform the AWS Cognito InitiateAuth request.

        Returns an ``_AuthTokens`` instance on success or raises
        :class:`KiblAuthError` on failure.
        """
        if not self._username or not self._password:
            raise KiblAuthError("KIBL_USERNAME and KIBL_PASSWORD must be set for authentication")

        endpoint = f"https://cognito-idp.{self._region}.amazonaws.com/"
        payload: Dict[str, Any] = {
            "AuthFlow": "USER_PASSWORD_AUTH",
            "ClientId": self._client_id,
            "AuthParameters": {
                "USERNAME": self._username,
                "PASSWORD": self._password,
            },
        }
        headers = {
            "X-Amz-Target": "AWSCognitoIdentityProviderService.InitiateAuth",
            "Content-Type": "application/x-amz-json-1.1",
        }
        try:
            resp = requests.post(endpoint, json=payload, headers=headers, timeout=10)
        except Exception as exc:
            raise KiblAuthError(f"Failed to reach Cognito endpoint: {exc}")
        if resp.status_code != 200:
            # Do not expose sensitive details; include status code only.
            raise KiblAuthError(f"Cognito auth failed with status {resp.status_code}")
        try:
            data: Dict[str, Any] = resp.json()
        except Exception as exc:
            raise KiblAuthError(f"Failed to parse Cognito response: {exc}")
        auth_result = data.get("AuthenticationResult") or {}
        access = auth_result.get("AccessToken")
        expires_in = auth_result.get("ExpiresIn")  # seconds
        if not access or not expires_in:
            raise KiblAuthError("Cognito response missing AccessToken or ExpiresIn")
        # Compute expiry as now + expires_in - 60 seconds (buffer).
        expires_at = time.time() + float(expires_in) - 60
        return _AuthTokens(access_token=access, expires_at=expires_at)

    def get_token(self, force_refresh: bool = False) -> str:
        """Return a valid access token, refreshing if necessary.

        Parameters
        ----------
        force_refresh: bool, optional
            If True, always reauthenticate even if the current token
            appears valid.
        """
        now = time.time()
        if (
            not force_refresh
            and self._tokens is not None
            and self._tokens.access_token
            and self._tokens.expires_at > now
        ):
            return self._tokens.access_token
        # Either no token or expired; reauthenticate.
        self._tokens = self._initiate_auth()
        return self._tokens.access_token

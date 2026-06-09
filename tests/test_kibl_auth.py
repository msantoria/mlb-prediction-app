"""Tests for the KiblAuthClient.

These tests use Python's built-in ``unittest`` framework and
``unittest.mock`` to patch network calls.  They do not hit the real
AWS Cognito API.
"""

import os
import unittest
from unittest import mock

from mlb_app.integrations.kibl.auth import KiblAuthClient, KiblAuthError


class TestKiblAuthClient(unittest.TestCase):
    def setUp(self) -> None:
        # Set required env vars for each test.  Use test values.
        os.environ["KIBL_COGNITO_REGION"] = "us-west-2"
        os.environ["KIBL_COGNITO_CLIENT_ID"] = "client123"
        os.environ["KIBL_USERNAME"] = "user@example.com"
        os.environ["KIBL_PASSWORD"] = "secretpass"

    def tearDown(self) -> None:
        # Clean up environment variables that may affect other tests.
        for key in [
            "KIBL_COGNITO_REGION",
            "KIBL_COGNITO_CLIENT_ID",
            "KIBL_USERNAME",
            "KIBL_PASSWORD",
        ]:
            os.environ.pop(key, None)

    def test_get_token_success(self) -> None:
        """get_token should return the access token from Cognito."""

        # Fake response from Cognito
        fake_response = mock.Mock()
        fake_response.status_code = 200
        fake_response.json.return_value = {
            "AuthenticationResult": {
                "AccessToken": "test-access",
                "ExpiresIn": 3600,
            }
        }
        with mock.patch("requests.post", return_value=fake_response) as mock_post:
            auth = KiblAuthClient()
            token = auth.get_token()
            # Ensure the token matches the fake value
            self.assertEqual(token, "test-access")
            # Ensure the correct endpoint and payload were used
            mock_post.assert_called_once()
            args, kwargs = mock_post.call_args
            self.assertIn("cognito-idp.us-west-2.amazonaws.com", args[0])
            self.assertEqual(kwargs["headers"]["X-Amz-Target"], "AWSCognitoIdentityProviderService.InitiateAuth")
            # Password should be present in payload but we check its placement
            self.assertEqual(kwargs["json"]["AuthParameters"]["PASSWORD"], "secretpass")

    def test_auth_error_redaction(self) -> None:
        """KiblAuthError should not leak the password."""

        # Simulate a non-200 response
        bad_response = mock.Mock()
        bad_response.status_code = 400
        bad_response.json.return_value = {}
        with mock.patch("requests.post", return_value=bad_response):
            auth = KiblAuthClient()
            with self.assertRaises(KiblAuthError) as ctx:
                auth.get_token(force_refresh=True)
            message = str(ctx.exception)
            # Ensure the password is not present in the error message
            self.assertNotIn("secretpass", message)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()

import os
import string
from datetime import datetime, timedelta, timezone
from typing import Any
from unittest.mock import MagicMock, Mock, patch

import pytest

os.environ["AUTH_URL"] = "auth_url"
os.environ["PUBLIC_KEY_URL"] = "public_key_url"
os.environ["API_KEY"] = "api_key"
os.environ["TOKEN_TABLE_NAME"] = "token_table"  # noqa: S105 - Dummy value
os.environ["DDB_INDEX_TAG"] = "branch_name"

from apim_mock.handler import (
    _generate_random_token,
    handle_request,
)


class TestHandleRequest:
    @patch("jwt.decode")
    @patch("jwt.get_unverified_header")
    @patch("apim_mock.handler._generate_random_token")
    @patch("apim_mock.handler.datetime")
    @patch("boto3.resource")
    def test_handle_request(
        self,
        boto3_resource_mock: MagicMock,
        datetime_mock: MagicMock,
        generate_random_token_mock: MagicMock,
        jwt_get_unverified_header_mock: MagicMock,
        jwt_decode_mock: MagicMock,
    ) -> None:
        jwt_get_unverified_header_mock.return_value = {
            "alg": "RS512",
            "kid": "DEV-1",
        }
        jwt_decode_mock.return_value = {
            "iss": "api_key",
            "sub": "api_key",
            "exp": 1772212239,
            "jti": "7632b48d-0e2f-43e5-93a9-d339c1bcddf8",
        }

        datetime_mock.now.return_value = datetime.fromtimestamp(
            1772212240, tz=timezone.utc
        )
        # As we're mocking the datetime module, ensure that fromtimestamp can still be
        # used to create a new datetime instance.
        datetime_mock.fromtimestamp.side_effect = lambda ts, tz=None: (
            datetime.fromtimestamp(ts, tz=tz)
        )

        generate_random_token_mock.return_value = "test_token"

        payload = {
            "grant_type": "client_credentials",
            "client_assertion_type": [
                "urn:ietf:params:oauth:client-assertion-type:jwt-bearer"
            ],
            "client_assertion": ["testing"],
        }

        mock_dynamodb_client = Mock()
        boto3_resource_mock.return_value = mock_dynamodb_client

        response = handle_request(payload)

        assert response == {
            "access_token": "test_token",
            "expires_in": "599",
            "token_type": "Bearer",
        }

        boto3_resource_mock.assert_called_once_with("dynamodb")

        mock_dynamodb_client.Table.return_value.put_item.assert_called_with(
            Item={
                "access_token": "test_token",
                "expiresAt": 1772212839,
                "ddb_index": "branch_name",
                "sessionId": "test_token",
                "type": "access_token",
            }
        )

    @pytest.mark.parametrize(
        ("payload", "error_message"),
        [
            pytest.param(
                {
                    "client_assertion_type": [
                        "urn:ietf:params:oauth:client-assertion-type:jwt-bearer"
                    ],
                    "client_assertion": ["testing"],
                },
                "grant_type is missing",
            ),
            pytest.param(
                {
                    "grant_type": ["client_credentials"],
                    "client_assertion": ["testing"],
                },
                (
                    "Missing or invalid client_assertion_type - "
                    "must be 'urn:ietf:params:oauth:client-assertion-type:jwt-bearer'"
                ),
            ),
            pytest.param(
                {
                    "grant_type": ["client_credentials"],
                    "client_assertion_type": [
                        "urn:ietf:params:oauth:client-assertion-type:jwt-bearer"
                    ],
                },
                "Missing client_assertion",
            ),
        ],
    )
    def test_invalid_payload(self, payload: dict[str, Any], error_message: str) -> None:
        with pytest.raises(ValueError, match=error_message):
            handle_request(payload)

    @pytest.mark.parametrize(
        ("unverified_headers", "error_message"),
        [
            pytest.param(
                {"alg": "RS512"},
                "Missing 'kid' header in client_assertion JWT",
            ),
            pytest.param(
                {"alg": "RS256", "kid": "DEV-1"},
                (
                    "Invalid 'alg' header in client_assertion JWT - "
                    "unsupported JWT algorithm - must be 'RS512'"
                ),
            ),
        ],
    )
    @patch("jwt.get_unverified_header")
    def test_invalid_jwt_headers(
        self,
        jwt_get_unverified_header_mock: MagicMock,
        unverified_headers: dict[str, Any],
        error_message: str,
    ) -> None:
        jwt_get_unverified_header_mock.return_value = unverified_headers

        payload = {
            "grant_type": "client_credentials",
            "client_assertion_type": [
                "urn:ietf:params:oauth:client-assertion-type:jwt-bearer"
            ],
            "client_assertion": ["testing"],
        }

        with pytest.raises(ValueError, match=error_message):
            handle_request(payload)

    @patch("jwt.decode")
    @patch("jwt.get_unverified_header")
    def test_get_jwk_key(
        self, jwt_get_unverified_header_mock: MagicMock, jwt_decode_mock: MagicMock
    ) -> None:
        error_message = (
            "Invalid 'kid' header in client_assertion JWT - no matching public key"
        )

        jwt_get_unverified_header_mock.return_value = {
            "alg": "RS512",
            "kid": "invalid",
        }
        jwt_decode_mock.return_value = {
            "iss": "api_key",
            "sub": "api_key",
            "exp": 1772212239,
            "jti": "7632b48d-0e2f-43e5-93a9-d339c1bcddf8",
        }

        payload = {
            "grant_type": "client_credentials",
            "client_assertion_type": [
                "urn:ietf:params:oauth:client-assertion-type:jwt-bearer"
            ],
            "client_assertion": ["testing"],
        }

        with pytest.raises(ValueError, match=error_message):
            handle_request(payload)

    @pytest.mark.parametrize(
        ("assertions", "error_message"),
        [
            pytest.param(
                {
                    "iss": "api_key",
                    "exp": 1772212239,
                    "jti": "7632b48d-0e2f-43e5-93a9-d339c1bcddf8",
                },
                "Missing or non-matching 'iss'/'sub' claims in client_assertion JWT",
            ),
            pytest.param(
                {
                    "iss": "wrong_key",
                    "sub": "wrong_key",
                    "exp": 1772212239,
                    "jti": "7632b48d-0e2f-43e5-93a9-d339c1bcddf8",
                },
                "Invalid 'iss'/'sub' claims in client_assertion JWT",
            ),
            pytest.param(
                {
                    "iss": "api_key",
                    "sub": "api_key",
                    "exp": 1772212239,
                },
                "Missing 'jti' claim in client_assertion JWT",
            ),
            pytest.param(
                {
                    "iss": "api_key",
                    "sub": "api_key",
                    "exp": 1772212239,
                    "jti": "invalid uuid",
                },
                "Invalid UUID4 value for jti",
            ),
            pytest.param(
                {
                    "iss": "api_key",
                    "sub": "api_key",
                    "jti": "7632b48d-0e2f-43e5-93a9-d339c1bcddf8",
                },
                "Missing exp claim in assertions",
            ),
            pytest.param(
                {
                    "iss": "api_key",
                    "sub": "api_key",
                    "jti": "7632b48d-0e2f-43e5-93a9-d339c1bcddf8",
                    "exp": (
                        datetime.now(tz=timezone.utc) + timedelta(minutes=5, seconds=1)
                    ).timestamp(),
                },
                "Invalid 'exp' claim in client_assertion JWT"
                " - more than 5 minutes in future",
            ),
        ],
    )
    @patch("jwt.decode")
    @patch("jwt.get_unverified_header")
    def test_validate_assertions(
        self,
        jwt_get_unverified_header_mock: MagicMock,
        jwt_decode_mock: MagicMock,
        assertions: dict[str, Any],
        error_message: str,
    ) -> None:
        payload = {
            "grant_type": "client_credentials",
            "client_assertion_type": [
                "urn:ietf:params:oauth:client-assertion-type:jwt-bearer"
            ],
            "client_assertion": ["testing"],
        }

        jwt_get_unverified_header_mock.return_value = {
            "alg": "RS512",
            "kid": "DEV-1",
        }
        jwt_decode_mock.return_value = assertions

        with pytest.raises(ValueError, match=error_message):
            handle_request(payload)

    def test_generate_random_token(self) -> None:
        token = _generate_random_token()
        assert len(token) == 15
        assert all(
            c
            in "-._~+/"
            + string.ascii_uppercase
            + string.ascii_lowercase
            + string.digits
            for c in token
        )

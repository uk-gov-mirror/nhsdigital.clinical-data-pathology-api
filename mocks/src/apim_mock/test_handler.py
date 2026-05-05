import json
import os
import string
import urllib.parse
from datetime import datetime, timedelta, timezone
from types import ModuleType
from typing import Any
from unittest.mock import MagicMock, Mock, patch

import pytest
from aws_lambda_powertools.event_handler import (
    APIGatewayHttpResolver,
)
from aws_lambda_powertools.utilities.typing import LambdaContext
from requests import HTTPError

os.environ["AUTH_URL"] = "auth_url"
os.environ["PUBLIC_KEY_URL"] = "public_key_url"
os.environ["API_KEY"] = "api_key"
os.environ["MOCK_TABLE_NAME"] = "token_table"
os.environ["DDB_INDEX_TAG"] = "test_branch"
os.environ["API_KEY_SECRET_NAME"] = "test_secret"  # noqa: S105 - Dummy value

CLIENT_ASSERTION_TYPE = "urn:ietf:params:oauth:client-assertion-type:jwt-bearer"


class TestHandleRequest:
    mock_dynamodb_client = Mock()

    @pytest.fixture
    def handler(self) -> ModuleType:
        with (
            patch("boto3.resource") as boto_resource_mock,
        ):
            boto_resource_mock.return_value = self.mock_dynamodb_client
            import apim_mock.handler as handler

            return handler

    @pytest.fixture
    def lambda_app(self, handler: ModuleType) -> APIGatewayHttpResolver:
        app = APIGatewayHttpResolver()
        app.include_router(handler.apim_routes)

        return app

    def _create_test_event(
        self,
        body: str | None = None,
        path_params: str | None = None,
        request_method: str | None = None,
        headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        return {
            "body": body,
            "requestContext": {
                "http": {
                    "path": f"/{path_params}",
                    "method": request_method,
                },
                "requestId": "request-id",
                "stage": "$default",
            },
            "headers": headers,
            "httpMethod": request_method,
            "rawPath": f"/{path_params}",
            "rawQueryString": "",
            "pathParameters": {"proxy": path_params},
        }

    @patch("jwt.decode")
    @patch("jwt.get_unverified_header")
    @patch("jwt.algorithms.RSAAlgorithm.from_jwk")
    @patch("apim_mock.handler._generate_random_token")
    @patch("apim_mock.handler.datetime")
    @patch("requests.get")
    @patch("aws_lambda_powertools.utilities.parameters.get_secret")
    def test_handle_request(
        self,
        get_secret_mock: MagicMock,
        requests_mock: MagicMock,
        datetime_mock: MagicMock,
        generate_random_token_mock: MagicMock,
        rsaa_jwt_from_jwk_mock: MagicMock,
        jwt_get_unverified_header_mock: MagicMock,
        jwt_decode_mock: MagicMock,
        handler: ModuleType,
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

        rsaa_jwt_from_jwk_mock.return_value = "public_key"

        requests_mock.return_value.json.return_value = {
            "keys": [
                {
                    "kty": "RSA",
                    "n": "key_value",
                    "e": "AQAB",
                    "alg": "RS512",
                    "kid": "DEV-1",
                    "use": "sig",
                }
            ]
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

        get_secret_mock.return_value = "api_key"

        payload = {
            "grant_type": "client_credentials",
            "client_assertion_type": [
                "urn:ietf:params:oauth:client-assertion-type:jwt-bearer"
            ],
            "client_assertion": ["testing"],
        }

        response = handler.handle_request(payload)

        assert response == {
            "access_token": "test_token",
            "expires_in": "599",
            "token_type": "Bearer",
        }

        self.mock_dynamodb_client.Table.return_value.put_item.assert_called_with(
            Item={
                "access_token": "test_token",
                "expiresAt": 1772212839,
                "ddb_index": "test_branch",
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
    def test_invalid_payload(
        self, payload: dict[str, Any], error_message: str, handler: ModuleType
    ) -> None:
        with pytest.raises(ValueError, match=error_message):
            handler.handle_request(payload)

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
        handler: ModuleType,
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
            handler.handle_request(payload)

    @patch("jwt.decode")
    @patch("jwt.get_unverified_header")
    @patch("jwt.algorithms.RSAAlgorithm.from_jwk")
    @patch("requests.get")
    def test_get_jwk_key(
        self,
        requests_get_mock: MagicMock,
        rsaa_jwt_from_jwk_mock: MagicMock,
        jwt_get_unverified_header_mock: MagicMock,
        jwt_decode_mock: MagicMock,
        handler: ModuleType,
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

        rsaa_jwt_from_jwk_mock.return_value = "public_key"

        requests_get_mock.return_value.json.return_value = {
            "keys": [
                {
                    "kty": "RSA",
                    "n": "key_value",
                    "e": "AQAB",
                    "alg": "RS512",
                    "kid": "DEV-1",
                    "use": "sig",
                }
            ]
        }

        payload = {
            "grant_type": "client_credentials",
            "client_assertion_type": [
                "urn:ietf:params:oauth:client-assertion-type:jwt-bearer"
            ],
            "client_assertion": ["testing"],
        }

        with pytest.raises(ValueError, match=error_message):
            handler.handle_request(payload)

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
    @patch("requests.get")
    @patch("aws_lambda_powertools.utilities.parameters.get_secret")
    def test_validate_assertions(
        self,
        get_secret_mock: MagicMock,
        requests_mock: MagicMock,
        jwt_get_unverified_header_mock: MagicMock,
        jwt_decode_mock: MagicMock,
        assertions: dict[str, Any],
        error_message: str,
        handler: ModuleType,
    ) -> None:
        payload = {
            "grant_type": "client_credentials",
            "client_assertion_type": [
                "urn:ietf:params:oauth:client-assertion-type:jwt-bearer"
            ],
            "client_assertion": ["testing"],
        }

        requests_mock.return_value.json.return_value = {
            "keys": [
                {
                    "kty": "RSA",
                    "n": "test_value",
                    "e": "AQAB",
                    "alg": "RS512",
                    "kid": "DEV-1",
                    "use": "sig",
                }
            ]
        }

        jwt_get_unverified_header_mock.return_value = {
            "alg": "RS512",
            "kid": "DEV-1",
        }
        jwt_decode_mock.return_value = assertions

        get_secret_mock.return_value = "api_key"

        with pytest.raises(ValueError, match=error_message):
            handler.handle_request(payload)

    @patch("jwt.decode")
    @patch("jwt.get_unverified_header")
    @patch("jwt.algorithms.RSAAlgorithm.from_jwk")
    @patch("apim_mock.handler.datetime")
    @patch("requests.get")
    @patch("aws_lambda_powertools.utilities.parameters.get_secret")
    def test_generate_random_token(
        self,
        get_secret_mock: MagicMock,
        requests_mock: MagicMock,
        datetime_mock: MagicMock,
        rsaa_jwt_from_jwk_mock: MagicMock,
        jwt_get_unverified_header_mock: MagicMock,
        jwt_decode_mock: MagicMock,
        handler: ModuleType,
    ) -> None:
        get_secret_mock.return_value = "api_key"

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

        rsaa_jwt_from_jwk_mock.return_value = "public_key"

        requests_mock.return_value.json.return_value = {
            "keys": [
                {
                    "kty": "RSA",
                    "n": "key_value",
                    "e": "AQAB",
                    "alg": "RS512",
                    "kid": "DEV-1",
                    "use": "sig",
                }
            ]
        }

        datetime_mock.now.return_value = datetime.fromtimestamp(
            1772212240, tz=timezone.utc
        )
        # As we're mocking the datetime module, ensure that fromtimestamp can still be
        # used to create a new datetime instance.
        datetime_mock.fromtimestamp.side_effect = lambda ts, tz=None: (
            datetime.fromtimestamp(ts, tz=tz)
        )

        payload = {
            "grant_type": "client_credentials",
            "client_assertion_type": [
                "urn:ietf:params:oauth:client-assertion-type:jwt-bearer"
            ],
            "client_assertion": ["testing"],
        }

        response = handler.handle_request(payload)

        token = response["access_token"]
        assert len(token) == 15
        assert all(
            c
            in "-._~+/"
            + string.ascii_uppercase
            + string.ascii_lowercase
            + string.digits
            for c in token
        )

    @patch("jwt.decode")
    @patch("jwt.get_unverified_header")
    @patch("apim_mock.handler._generate_random_token")
    @patch("jwt.algorithms.RSAAlgorithm.from_jwk")
    @patch("requests.get")
    @patch("aws_lambda_powertools.utilities.parameters.get_secret")
    def test_get_access_token_success(
        self,
        get_secret_mock: MagicMock,
        requests_get_mock: MagicMock,
        rsaa_jwt_from_jwk_mock: MagicMock,
        generate_random_token_mock: MagicMock,
        jwt_get_unverified_header_mock: MagicMock,
        jwt_decode_mock: MagicMock,
        lambda_app: APIGatewayHttpResolver,
    ) -> None:
        get_secret_mock.return_value = "api_key"

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
        generate_random_token_mock.return_value = "test_token"

        rsaa_jwt_from_jwk_mock.return_value = "public_key"

        requests_get_mock.return_value.json.return_value = {
            "keys": [
                {
                    "kty": "RSA",
                    "n": "key_value",
                    "e": "AQAB",
                    "alg": "RS512",
                    "kid": "DEV-1",
                    "use": "sig",
                }
            ]
        }

        body = {
            "grant_type": "client_credentials",
            "client_assertion_type": CLIENT_ASSERTION_TYPE,
            "client_assertion": "testing",
        }
        event = self._create_test_event(
            urllib.parse.urlencode(body),
            path_params="apim/oauth2/token",
            request_method="POST",
        )
        context = LambdaContext()

        response = lambda_app.resolve(event, context)

        expected_body = {
            "access_token": "test_token",
            "expires_in": "599",
            "token_type": "Bearer",
        }

        assert response["statusCode"] == 200
        assert json.loads(response["body"]) == expected_body
        assert response["headers"] == {"Content-Type": "application/json"}

    def test_get_access_token_no_payload(
        self,
        lambda_app: APIGatewayHttpResolver,
    ) -> None:
        event = self._create_test_event(
            path_params="apim/oauth2/token", request_method="POST"
        )
        context = LambdaContext()

        response = lambda_app.resolve(event, context)

        assert response["statusCode"] == 400
        assert response["body"] == "Bad Request"

    def test_get_access_token_invalid_body(
        self, lambda_app: APIGatewayHttpResolver
    ) -> None:
        event = self._create_test_event(
            body="Invalid Body", path_params="apim/oauth2/token", request_method="POST"
        )
        context = LambdaContext()

        response = lambda_app.resolve(event, context)

        assert response["statusCode"] == 400
        assert json.loads(response["body"]) == {
            "error": "invalid_request",
            "error_description": "grant_type is missing",
        }

    def test_invalid_token_error(self, lambda_app: APIGatewayHttpResolver) -> None:
        body = {
            "grant_type": "client_credentials",
            "client_assertion_type": CLIENT_ASSERTION_TYPE,
            "client_assertion": "testing",
        }

        event = self._create_test_event(
            urllib.parse.urlencode(body),
            path_params="apim/oauth2/token",
            request_method="POST",
        )

        context = LambdaContext()

        response = lambda_app.resolve(event, context)

        assert response["statusCode"] == 400
        assert json.loads(response["body"]) == {
            "error": "invalid_request",
            "error_description": "Not enough segments",
        }

        assert response["headers"] == {"Content-Type": "application/json"}

    @patch("jwt.get_unverified_header")
    @patch("requests.get")
    def test_value_error(
        self,
        requests_get_mock: MagicMock,
        jwt_get_unverified_header_mock: MagicMock,
        lambda_app: APIGatewayHttpResolver,
    ) -> None:
        jwt_get_unverified_header_mock.return_value = {
            "alg": "RS512",
            "kid": "TEST-1",
        }

        requests_get_mock.return_value.json.return_value = {
            "keys": [
                {
                    "kty": "RSA",
                    "n": "test_value",
                    "e": "AQAB",
                    "alg": "RS512",
                    "kid": "DEV-1",
                    "use": "sig",
                }
            ]
        }

        body = {
            "grant_type": "client_credentials",
            "client_assertion_type": CLIENT_ASSERTION_TYPE,
            "client_assertion": "testing",
        }

        event = self._create_test_event(
            urllib.parse.urlencode(body),
            path_params="apim/oauth2/token",
            request_method="POST",
        )

        context = LambdaContext()

        response = lambda_app.resolve(event, context)
        expected_error_description = (
            "Invalid 'kid' header in client_assertion JWT - no matching public key"
        )

        assert response["statusCode"] == 400
        assert json.loads(response["body"]) == {
            "error": "invalid_request",
            "error_description": expected_error_description,
        }

    @patch("apim_mock.handler.handle_request")
    def test_apim_http_error(
        self, apim_handle_request_mock: MagicMock, lambda_app: APIGatewayHttpResolver
    ) -> None:
        apim_handle_request_mock.side_effect = HTTPError(
            "404 Client Error: Not Found for url: http://example.com"
        )

        body = {
            "grant_type": "client_credentials",
            "client_assertion_type": CLIENT_ASSERTION_TYPE,
            "client_assertion": "testing",
        }

        event = self._create_test_event(
            urllib.parse.urlencode(body),
            path_params="apim/oauth2/token",
            request_method="POST",
        )

        context = LambdaContext()

        response = lambda_app.resolve(event, context)

        assert response["statusCode"] == 403
        assert json.loads(response["body"]) == {
            "error": "public_key error",
            "error_description": "The JWKS endpoint, for your"
            " client_assertion can't be reached",
        }

    @patch("apim_mock.handler.handle_request")
    def test_apim_get_token_internal_server_error(
        self,
        apim_handle_request_mock: MagicMock,
        lambda_app: APIGatewayHttpResolver,
    ) -> None:

        apim_handle_request_mock.side_effect = Exception("Test exception")

        body = {
            "grant_type": "client_credentials",
            "client_assertion_type": CLIENT_ASSERTION_TYPE,
            "client_assertion": "testing",
        }

        event = self._create_test_event(
            urllib.parse.urlencode(body),
            path_params="apim/oauth2/token",
            request_method="POST",
        )

        context = LambdaContext()

        response = lambda_app.resolve(event, context)

        assert response["statusCode"] == 500
        assert response["body"] == "Internal Server Error"

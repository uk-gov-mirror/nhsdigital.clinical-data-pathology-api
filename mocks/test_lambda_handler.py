import json
import os
import urllib.parse
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from aws_lambda_powertools.utilities.typing import LambdaContext

os.environ["AUTH_URL"] = "auth_url"
os.environ["PUBLIC_KEY_URL"] = "public_key_url"
os.environ["API_KEY"] = "api_key"
os.environ["TOKEN_TABLE_NAME"] = "token_table"  # noqa: S105 - Dummy value
os.environ["DDB_INDEX_TAG"] = "branch_name"

from lambda_handler import handler

CLIENT_ASSERTION_TYPE = "urn:ietf:params:oauth:client-assertion-type:jwt-bearer"


class TestHandler:
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
    @patch("apim_mock.handler._generate_random_token")
    def test_get_access_token_success(
        self,
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
        generate_random_token_mock.return_value = "test_token"

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

        with patch("apim_mock.handler.boto3"):
            response = handler(event, context)

        expected_body = {
            "access_token": "test_token",
            "expires_in": "599",
            "token_type": "Bearer",
        }

        assert response["statusCode"] == 200
        assert json.loads(response["body"]) == expected_body
        assert response["headers"] == {"Content-Type": "application/json"}

    def test_get_access_token_no_payload(self) -> None:
        event = self._create_test_event(
            path_params="apim/oauth2/token", request_method="POST"
        )
        context = LambdaContext()

        response = handler(event, context)

        assert response["statusCode"] == 400
        assert response["body"] == "Bad Request"

    def test_get_access_token_invalid_body(self) -> None:
        event = self._create_test_event(
            body="Invalid Body", path_params="apim/oauth2/token", request_method="POST"
        )
        context = LambdaContext()

        response = handler(event, context)

        assert response["statusCode"] == 400
        assert json.loads(response["body"]) == {
            "error": "invalid_request",
            "error_description": "grant_type is missing",
        }

    def test_invalid_token_error(self) -> None:
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

        response = handler(event, context)

        assert response["statusCode"] == 400
        assert json.loads(response["body"]) == {
            "error": "invalid_request",
            "error_description": "Not enough segments",
        }

        assert response["headers"] == {"Content-Type": "application/json"}

    @patch("jwt.get_unverified_header")
    def test_value_error(self, jwt_get_unverified_header_mock: MagicMock) -> None:
        jwt_get_unverified_header_mock.return_value = {
            "alg": "RS512",
            "kid": "TEST-1",
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

        response = handler(event, context)
        expected_error_description = (
            "Invalid 'kid' header in client_assertion JWT - no matching public key"
        )

        assert response["statusCode"] == 400
        assert json.loads(response["body"]) == {
            "error": "invalid_request",
            "error_description": expected_error_description,
        }

    @patch("apim_mock.auth_check.boto3.resource")
    def test_check_auth(self, boto3_mock: MagicMock) -> None:
        event = self._create_test_event(
            path_params="apim/check_auth",
            request_method="POST",
            headers={"Authorization": "Bearer token"},
        )

        context = LambdaContext()

        response = handler(event, context)
        assert response["statusCode"] == 401

        mock_table = MagicMock()
        mock_table.query.return_value = {"Items": [{"sessionId": "token"}]}
        boto3_mock.return_value.Table.return_value = mock_table

        response = handler(event, context)
        assert response["statusCode"] == 200

    def test_root_check(self) -> None:
        event = self._create_test_event(
            path_params="",
            request_method="GET",
            headers={"test_header": "test_value"},
        )

        context = LambdaContext()

        response = handler(event, context)
        assert response["statusCode"] == 200
        assert json.loads(response["body"]) == {
            "message": "ok",
            "headers": {"test_header": "test_value"},
            "requestContext": {
                "http": {
                    "method": "GET",
                    "path": "/",
                },
                "requestId": "request-id",
                "stage": "$default",
            },
        }

    @pytest.mark.parametrize(
        ("request_method", "request_parameter"),
        [
            pytest.param("GET", "unknown_path", id="Unknown path"),
            pytest.param("GET", "apim/oauth2/token", id="Unknown GET method"),
            pytest.param("POST", "_status", id="Unknown POST method"),
        ],
    )
    def test_invalid_request(self, request_method: str, request_parameter: str) -> None:
        event = self._create_test_event(
            path_params=request_parameter, request_method=request_method
        )
        context = LambdaContext()

        response = handler(event, context)

        assert response["statusCode"] == 404
        assert json.loads(response["body"]) == {
            "statusCode": 404,
            "message": "Not found",
        }
        assert response["headers"] == {"Content-Type": "application/json"}

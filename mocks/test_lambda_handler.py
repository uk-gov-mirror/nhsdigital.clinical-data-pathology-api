import json
import os
from collections.abc import Callable
from typing import Any
from unittest.mock import MagicMock, Mock, patch

import pytest
from aws_lambda_powertools.utilities.typing import LambdaContext

os.environ["AUTH_URL"] = "auth_url"
os.environ["PUBLIC_KEY_URL"] = "public_key_url"
os.environ["API_KEY"] = "api_key"
os.environ["TOKEN_TABLE_NAME"] = "token_table"  # noqa: S105 - Dummy value
os.environ["DDB_INDEX_TAG"] = "branch_name"

with patch("boto3.resource"):
    from apim_mock.auth_check import AuthenticationError

CLIENT_ASSERTION_TYPE = "urn:ietf:params:oauth:client-assertion-type:jwt-bearer"

mock_dynamodb_client = Mock()


class TestHandler:
    @pytest.fixture
    def handler(self) -> Callable[..., Any]:
        with (
            patch("boto3.resource") as boto_resource_mock,
        ):
            boto_resource_mock.return_value = mock_dynamodb_client
            from lambda_handler import handler as handler

            return handler

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

    def test_root_check(self, handler: Callable[..., Any]) -> None:
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
    def test_invalid_request(
        self, request_method: str, request_parameter: str, handler: Callable[..., Any]
    ) -> None:
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

    @patch("pdm_mock.handler.check_authenticated")
    def test_authentication_exception_handler(
        self, check_authenticated_mock: MagicMock, handler: Callable[..., Any]
    ) -> None:
        check_authenticated_mock.side_effect = AuthenticationError()

        event = self._create_test_event(
            path_params="pdm/FHIR/R4/Bundle",
            request_method="POST",
            body=json.dumps({"test": "data"}),
        )
        context = LambdaContext()

        response = handler(event, context)

        assert response["statusCode"] == 401
        assert response["body"] == ""

import json
import os
from types import ModuleType
from typing import Any
from unittest.mock import MagicMock, Mock, patch

import pytest
from aws_lambda_powertools.event_handler import APIGatewayHttpResolver
from aws_lambda_powertools.utilities.typing import LambdaContext

os.environ["TOKEN_TABLE_NAME"] = "token_table"  # noqa: S105
os.environ["MNS_TABLE_NAME"] = "test_table"
os.environ["DDB_INDEX_TAG"] = "test_branch"
os.environ["AUTH_URL"] = "auth_url"
os.environ["PUBLIC_KEY_URL"] = "public_key_url"
os.environ["API_KEY"] = "api_key"

with patch("boto3.resource"):
    from apim_mock.auth_check import AuthenticationError

NHS_NUMBER = "9912003888"

mock_dynamodb_client = Mock()


@pytest.fixture
def basic_event_payload() -> dict[str, Any]:
    bundle_id = "473283"
    return {
        "specversion": "1.0",
        "id": "8829c575-b828-44d5-b4d9-9ed88b8b95c4",
        "source": "uk.nhs.pathology-laboratory-reporting",
        "type": "pathology-laboratory-reporting-test-result-stored-1",
        "time": "2024-06-01T00:00:00Z",
        "dataref": f"https://api.service.nhs.uk/patient-data-manager/FHIR/R4/Bundle/{bundle_id}",
        "subject": NHS_NUMBER,
        "filtering": {"requestingOrganisationODS": "ABC123"},
    }


class TestMNSMockHandler:
    @pytest.fixture
    def handler(self) -> ModuleType:
        with patch("boto3.resource") as boto_resource_mock:
            boto_resource_mock.return_value = mock_dynamodb_client
            import mns_mock.handler as handler

            return handler

    @pytest.fixture
    def lambda_app(self, handler: ModuleType) -> APIGatewayHttpResolver:
        app = APIGatewayHttpResolver()
        app.include_router(handler.mns_routes)
        return app

    def _create_test_event(
        self,
        body: str | None = None,
        path_params: str | None = None,
        query_params: dict[str, str] | None = None,
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
            "queryStringParameters": query_params,
        }

    @patch("mns_mock.handler.storage_helper")
    def test_handle_post_request_success(
        self,
        mock_storage: MagicMock,
        basic_event_payload: dict[str, Any],
        handler: ModuleType,
    ) -> None:
        response = handler.handle_post_request(basic_event_payload)

        assert response == {
            "status_code": 200,
            "response": {"id": basic_event_payload["id"]},
        }
        mock_storage.put_item.assert_called_once()

    @pytest.mark.parametrize(
        ("subject", "expected_response"),
        [
            (
                "MNS_VALIDATION_ERROR",
                {
                    "status_code": 400,
                    "response": {
                        "validationErrors": {
                            "type": "Please provide a valid event type"
                        }
                    },
                },
            ),
            (
                "MNS_AUTHENTICATION_ERROR",
                {
                    "status_code": 401,
                    "response": {
                        "fault": {
                            "faultstring": "Invalid access token",
                            "detail": {"errorcode": "oauth.v2.InvalidAccessToken"},
                        }
                    },
                },
            ),
            (
                "MNS_SERVER_ERROR",
                {"status_code": 500, "response": {"errors": "Internal server error"}},
            ),
            (
                "MNS_BAD_GATEWAY_ERROR",
                {"status_code": 502, "response": None},
            ),
            (
                "MNS_GATEWAY_TIMEOUT_ERROR",
                {"status_code": 504, "response": None},
            ),
        ],
    )
    def test_handle_post_request_error_responses(
        self,
        basic_event_payload: dict[str, Any],
        subject: str,
        expected_response: dict[str, Any],
        handler: ModuleType,
    ) -> None:
        payload = {**basic_event_payload, "subject": subject}
        response = handler.handle_post_request(payload)

        assert response == expected_response

    @patch("mns_mock.handler.storage_helper")
    def test_handle_search_returns_event(
        self,
        mock_storage: MagicMock,
        basic_event_payload: dict[str, Any],
        handler: ModuleType,
    ) -> None:
        mock_storage.find_items.return_value = [
            {
                "sessionId": "some-id",
                "type": "mns_event",
                "expiresAt": 9999999999,
                "event": basic_event_payload,
                "subject": NHS_NUMBER,
            }
        ]

        response = handler.handle_search(NHS_NUMBER)

        assert response == {
            "status_code": 200,
            "response": {"events": [basic_event_payload]},
        }

    @patch("mns_mock.handler.storage_helper")
    def test_handle_search_raises_error_when_no_event_found(
        self,
        mock_storage: MagicMock,
        handler: ModuleType,
    ) -> None:
        mock_storage.find_items.return_value = []

        assert handler.handle_search(NHS_NUMBER) == {
            "status_code": 200,
            "response": {"events": []},
        }

    @patch("mns_mock.handler.check_authenticated", new=MagicMock(return_value=None))
    def test_create_event_success(
        self,
        basic_event_payload: dict[str, Any],
        lambda_app: APIGatewayHttpResolver,
    ) -> None:
        event = self._create_test_event(
            body=json.dumps(basic_event_payload),
            path_params="mns/events",
            request_method="POST",
            headers={"Authorization": "Bearer token"},
        )
        context = LambdaContext()

        with patch("mns_mock.handler.storage_helper"):
            response = lambda_app.resolve(event, context)

        assert response["statusCode"] == 200
        assert response["headers"] == {"Content-Type": "application/fhir+json"}
        assert json.loads(response["body"]) == {"id": basic_event_payload["id"]}

    @patch("mns_mock.handler.check_authenticated", new=MagicMock(return_value=None))
    def test_create_event_without_response_payload(
        self,
        basic_event_payload: dict[str, Any],
        lambda_app: APIGatewayHttpResolver,
    ) -> None:
        payload = basic_event_payload | {"subject": "MNS_BAD_GATEWAY_ERROR"}

        event = self._create_test_event(
            body=json.dumps(payload),
            path_params="mns/events",
            request_method="POST",
            headers={"Authorization": "Bearer token"},
        )
        context = LambdaContext()

        with patch("mns_mock.handler.storage_helper"):
            response = lambda_app.resolve(event, context)

        assert response["statusCode"] == 502
        assert not response["headers"]
        assert response["body"] is None

    @patch("mns_mock.handler.check_authenticated")
    def test_create_event_fails_authentication(
        self,
        check_authenticated_mock: MagicMock,
        lambda_app: APIGatewayHttpResolver,
    ) -> None:
        check_authenticated_mock.side_effect = AuthenticationError()

        event = self._create_test_event(
            path_params="mns/events",
            request_method="POST",
        )
        context = LambdaContext()

        with pytest.raises(AuthenticationError):
            lambda_app.resolve(event, context)

    @patch("mns_mock.handler.check_authenticated", new=MagicMock(return_value=None))
    def test_create_event_invalid_json_body(
        self,
        lambda_app: APIGatewayHttpResolver,
    ) -> None:
        event = self._create_test_event(
            body="not valid json",
            path_params="mns/events",
            request_method="POST",
            headers={"Authorization": "Bearer token"},
        )
        context = LambdaContext()

        response = lambda_app.resolve(event, context)

        assert response["statusCode"] == 400
        assert response["headers"] == {"Content-Type": "application/fhir+json"}
        assert json.loads(response["body"]) == {
            "validationErrors": {"type": "Invalid payload provided"}
        }

    @patch("mns_mock.handler.check_authenticated", new=MagicMock(return_value=None))
    def test_create_event_no_payload(
        self,
        lambda_app: APIGatewayHttpResolver,
    ) -> None:
        event = self._create_test_event(
            path_params="mns/events",
            request_method="POST",
            headers={"Authorization": "Bearer token"},
        )
        context = LambdaContext()

        response = lambda_app.resolve(event, context)

        assert response["statusCode"] == 400
        assert response["headers"] == {"Content-Type": "application/fhir+json"}
        assert json.loads(response["body"]) == {
            "validationErrors": {"type": "No payload provided"}
        }

    @patch("mns_mock.handler.check_authenticated", new=MagicMock(return_value=None))
    @patch(
        "mns_mock.handler.handle_post_request",
        new=MagicMock(side_effect=Exception("Unexpected error")),
    )
    def test_create_event_unexpected_exception(
        self,
        basic_event_payload: dict[str, Any],
        lambda_app: APIGatewayHttpResolver,
    ) -> None:
        event = self._create_test_event(
            body=json.dumps(basic_event_payload),
            path_params="mns/events",
            request_method="POST",
            headers={"Authorization": "Bearer token"},
        )
        context = LambdaContext()

        response = lambda_app.resolve(event, context)

        assert response["statusCode"] == 500
        assert json.loads(response["body"]) == {"error": "Unexpected error"}

    @patch("mns_mock.handler.storage_helper")
    def test_find_events_success(
        self,
        mock_storage: MagicMock,
        basic_event_payload: dict[str, Any],
        lambda_app: APIGatewayHttpResolver,
    ) -> None:
        mock_storage.find_items.return_value = [
            {
                "sessionId": "some-id",
                "type": "mns_event",
                "expiresAt": 9999999999,
                "event": basic_event_payload,
                "subject": NHS_NUMBER,
            }
        ]

        event = self._create_test_event(
            path_params="mns/mock/event",
            query_params={"subject": NHS_NUMBER},
            request_method="GET",
        )
        context = LambdaContext()

        response = lambda_app.resolve(event, context)

        assert response["statusCode"] == 200
        assert response["headers"] == {"Content-Type": "application/json"}
        assert json.loads(response["body"]) == {"events": [basic_event_payload]}

    @patch("mns_mock.handler.storage_helper")
    def test_find_events_not_found(
        self,
        mock_storage: MagicMock,
        lambda_app: APIGatewayHttpResolver,
    ) -> None:
        mock_storage.find_items.return_value = []

        event = self._create_test_event(
            path_params="mns/mock/event",
            query_params={"subject": NHS_NUMBER},
            request_method="GET",
        )
        context = LambdaContext()

        response = lambda_app.resolve(event, context)

        assert response["statusCode"] == 200
        assert json.loads(response["body"]) == {"events": []}

    def test_find_events_without_subject(
        self, lambda_app: APIGatewayHttpResolver
    ) -> None:
        event = self._create_test_event(
            path_params="mns/mock/event",
            request_method="GET",
        )
        context = LambdaContext()

        response = lambda_app.resolve(event, context)

        assert response["statusCode"] == 400
        assert response["body"] == "No subject provided with request"

    @patch("mns_mock.handler.storage_helper")
    def test_find_events_raises_exception(
        self,
        storage_helper_mock: MagicMock,
        lambda_app: APIGatewayHttpResolver,
    ) -> None:
        event = self._create_test_event(
            path_params="mns/mock/event",
            query_params={"subject": NHS_NUMBER},
            request_method="GET",
        )
        context = LambdaContext()

        storage_helper_mock.find_items.side_effect = Exception("Unexpected error")
        response = lambda_app.resolve(event, context)

        assert response["statusCode"] == 500
        assert json.loads(response["body"]) == {"error": "Unexpected error"}

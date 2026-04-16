import datetime
import json
import os
from types import ModuleType
from typing import Any
from unittest.mock import MagicMock, Mock, patch

import pytest
from aws_lambda_powertools.event_handler import (
    APIGatewayHttpResolver,
)
from aws_lambda_powertools.utilities.typing import LambdaContext

with patch("boto3.resource"):
    from apim_mock.auth_check import AuthenticationError
    from common.storage_helper import ItemNotFoundException

os.environ["PDM_TABLE_NAME"] = "test_table"
os.environ["DDB_INDEX_TAG"] = "test_branch"
os.environ["AUTH_URL"] = "auth_url"
os.environ["PUBLIC_KEY_URL"] = "public_key_url"
os.environ["API_KEY"] = "api_key"
os.environ["TOKEN_TABLE_NAME"] = "token_table"  # noqa: S105 - Dummy value


@pytest.fixture
def basic_document_payload() -> dict[str, Any]:
    return {"resourceType": "Bundle", "type": "document", "entry": [{}]}


@pytest.fixture
def multiple_patient_document_payload(
    basic_document_payload: dict[str, Any],
) -> dict[str, Any]:
    return {
        **basic_document_payload,
        "entry": [
            {
                "resource": {
                    "resourceType": "Patient",
                    "identifier": {"value": "patient1"},
                }
            },
            {
                "resource": {
                    "resourceType": "Patient",
                    "identifier": {"value": "patient2"},
                }
            },
        ],
    }


@pytest.fixture
def validation_error_patient_payload(
    basic_document_payload: dict[str, Any],
) -> dict[str, Any]:
    return {
        **basic_document_payload,
        "entry": [
            {
                "resource": {
                    "resourceType": "Patient",
                    "identifier": {"value": "PDM_VALIDATION_ERROR"},
                }
            },
        ],
    }


@pytest.fixture
def server_error_patient_payload(
    basic_document_payload: dict[str, Any],
) -> dict[str, Any]:
    return {
        **basic_document_payload,
        "entry": [
            {
                "resource": {
                    "resourceType": "Patient",
                    "identifier": {"value": "PDM_SERVER_ERROR"},
                }
            },
        ],
    }


@pytest.fixture
def basic_saved_document(basic_document_payload: dict[str, Any]) -> dict[str, Any]:
    return {
        **basic_document_payload,
        "id": "document_id",
        "meta": {"versionId": "1", "last_updated": "2024-06-01T00:00:00Z"},
    }


mock_dynamodb_client = Mock()


class TestPDMMockHandler:
    @pytest.fixture
    def handler(self) -> ModuleType:
        with (
            patch("boto3.resource") as boto_resource_mock,
        ):
            boto_resource_mock.return_value = mock_dynamodb_client
            import pdm_mock.handler as handler

            return handler

    @pytest.fixture
    def lambda_app(self, handler: ModuleType) -> APIGatewayHttpResolver:
        app = APIGatewayHttpResolver()
        app.include_router(handler.pdm_routes)

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

    @patch("common.storage_helper.StorageHelper.put_item")
    @patch("pdm_mock.handler.uuid4")
    @patch("pdm_mock.handler.datetime")
    def test_handle_post_request(
        self,
        mock_datetime: MagicMock,
        mock_uuid: MagicMock,
        mock_storage_helper_put_item: MagicMock,
        basic_document_payload: dict[str, Any],
        handler: ModuleType,
    ) -> None:

        mock_datetime.now.return_value = datetime.datetime(
            2024, 6, 1, 0, 0, 0, tzinfo=datetime.timezone.utc
        )
        mock_uuid.return_value = "uuid4"
        response = handler.handle_post_request(basic_document_payload)

        assert response == {
            "status_code": 201,
            "response": {
                "resourceType": "Bundle",
                "id": "uuid4",
                "meta": {"versionId": "1", "last_updated": "2024-06-01T00:00:00Z"},
                "type": "document",
                "entry": [{}],
            },
        }
        assert mock_storage_helper_put_item.called

    @patch("boto3.resource")
    @patch("pdm_mock.handler.uuid4")
    @patch("pdm_mock.handler.datetime")
    def test_handle_post_request_multiple_patients(
        self,
        mock_datetime: MagicMock,
        mock_uuid: MagicMock,
        boto3_resource_mock: MagicMock,
        multiple_patient_document_payload: dict[str, Any],
        handler: ModuleType,
    ) -> None:

        mock_datetime.now.return_value = datetime.datetime(
            2024, 6, 1, 0, 0, 0, tzinfo=datetime.timezone.utc
        )
        mock_uuid.return_value = "uuid4"

        with pytest.raises(
            ValueError, match="Multiple patients referenced within the same bundle"
        ):
            handler.handle_post_request(multiple_patient_document_payload)

        assert not boto3_resource_mock.called

    @patch("boto3.resource")
    @patch("pdm_mock.handler.uuid4")
    @patch("pdm_mock.handler.datetime")
    def test_pdm_validation_error(
        self,
        mock_datetime: MagicMock,
        mock_uuid: MagicMock,
        boto3_resource_mock: MagicMock,
        validation_error_patient_payload: dict[str, Any],
        handler: ModuleType,
    ) -> None:
        mock_datetime.now.return_value = datetime.datetime(
            2024, 6, 1, 0, 0, 0, tzinfo=datetime.timezone.utc
        )
        mock_uuid.return_value = "uuid4"
        response = handler.handle_post_request(validation_error_patient_payload)

        assert response == {
            "status_code": 422,
            "response": {
                "resourceType": "OperationOutcome",
                "issue": [
                    {
                        "severity": "error",
                        "code": "invariant",
                        "details": {
                            "text": (
                                "Bundle size exceeds maximum "
                                "allowed size or number of entries."
                            ),
                        },
                    }
                ],
            },
        }
        assert not boto3_resource_mock.called

    @patch("boto3.resource")
    @patch("pdm_mock.handler.uuid4")
    @patch("pdm_mock.handler.datetime")
    def test_pdm_server_error(
        self,
        mock_datetime: MagicMock,
        mock_uuid: MagicMock,
        boto3_resource_mock: MagicMock,
        server_error_patient_payload: dict[str, Any],
        handler: ModuleType,
    ) -> None:
        mock_datetime.now.return_value = datetime.datetime(
            2024, 6, 1, 0, 0, 0, tzinfo=datetime.timezone.utc
        )
        mock_uuid.return_value = "uuid4"
        response = handler.handle_post_request(server_error_patient_payload)

        assert response == {
            "status_code": 500,
            "response": {
                "resourceType": "OperationOutcome",
                "issue": [
                    {
                        "severity": "error",
                        "code": "exception",
                        "details": {
                            "text": "Internal server error",
                        },
                    }
                ],
            },
        }
        assert not boto3_resource_mock.called

    def test_handle_get_request(
        self, basic_saved_document: dict[str, Any], handler: ModuleType
    ) -> None:

        mock_dynamodb_client.Table.return_value.get_item.return_value = {
            "Item": {
                "sessionId": "document_id",
                "document": basic_saved_document,
                "type": "document",
                "expiresAt": 1,
                "ddb_index": "test_branch",
            }
        }

        response = handler.handle_get_request("document_id")

        assert response == {
            "status_code": 200,
            "response": {
                "resourceType": "Bundle",
                "id": "document_id",
                "meta": {"versionId": "1", "last_updated": "2024-06-01T00:00:00Z"},
                "type": "document",
                "entry": [{}],
            },
        }

    def test_get_request_no_document_found(self, handler: ModuleType) -> None:
        mock_dynamodb_client.Table.return_value.get_item.return_value = {}

        with pytest.raises(ItemNotFoundException, match="Item not found"):
            handler.handle_get_request("document_id")

    @patch("pdm_mock.handler.check_authenticated")
    def test_create_document(
        self,
        check_authenticated_mock: MagicMock,
        lambda_app: APIGatewayHttpResolver,
    ) -> None:
        check_authenticated_mock.return_value = True

        event = self._create_test_event(
            path_params="pdm/FHIR/R4/Bundle",
            request_method="POST",
            headers={"X-Request-ID": "8c64be5f-3d7a-4b7b-8260-b716d122bdaf"},
            body=json.dumps({"test": "data"}),
        )
        context = LambdaContext()

        with patch("boto3.resource"):
            response = lambda_app.resolve(event, context)

        assert response["statusCode"] == 201

    @pytest.mark.parametrize(
        ("headers", "expected_issue_code", "expected_error_message"),
        [
            pytest.param({}, "required", "Missing X-Request-ID header"),
            pytest.param(
                {"X-Request-ID": "invalid"}, "invalid", "Invalid X-Request-ID header"
            ),
        ],
    )
    @patch("pdm_mock.handler.check_authenticated")
    def test_pdm_invalid_or_missing_x_request_id(
        self,
        check_authenticated_mock: MagicMock,
        headers: dict[str, str],
        expected_issue_code: str,
        expected_error_message: str,
        lambda_app: APIGatewayHttpResolver,
    ) -> None:
        check_authenticated_mock.return_value = True

        event = self._create_test_event(
            path_params="pdm/FHIR/R4/Bundle",
            request_method="POST",
            headers=headers,
            body=json.dumps({"test": "data"}),
        )
        context = LambdaContext()
        response = lambda_app.resolve(event, context)

        assert response["statusCode"] == 400
        assert json.loads(response["body"]) == {
            "resourceType": "OperationOutcome",
            "issue": [
                {
                    "severity": "error",
                    "code": expected_issue_code,
                    "details": {
                        "text": expected_error_message,
                    },
                }
            ],
        }

    @patch("pdm_mock.handler.check_authenticated")
    def test_pdm_mock_failed_authentication(
        self,
        check_authenticated_mock: MagicMock,
        lambda_app: APIGatewayHttpResolver,
    ) -> None:
        check_authenticated_mock.side_effect = AuthenticationError()

        event = self._create_test_event(
            path_params="pdm/FHIR/R4/Bundle",
            request_method="POST",
            headers={"X-Request-ID": "8c64be5f-3d7a-4b7b-8260-b716d122bdaf"},
            body=json.dumps({"test": "data"}),
        )
        context = LambdaContext()
        with pytest.raises(AuthenticationError, match=r"^$"):
            lambda_app.resolve(event, context)

    @patch("pdm_mock.handler.check_authenticated")
    def test_create_document_invalid_body(
        self,
        check_authenticated_mock: MagicMock,
        lambda_app: APIGatewayHttpResolver,
    ) -> None:
        check_authenticated_mock.return_value = None

        event = self._create_test_event(
            path_params="pdm/FHIR/R4/Bundle",
            request_method="POST",
            headers={"X-Request-ID": "8c64be5f-3d7a-4b7b-8260-b716d122bdaf"},
            body="Invalid Body",
        )
        context = LambdaContext()

        response = lambda_app.resolve(event, context)

        assert response["statusCode"] == 400
        assert json.loads(response["body"]) == {
            "resourceType": "OperationOutcome",
            "issue": [
                {
                    "severity": "error",
                    "code": "invalid_request",
                    "details": {
                        "text": "Invalid Payload provided.",
                    },
                }
            ],
        }

    @patch("pdm_mock.handler.check_authenticated")
    def test_create_document_invalid_payload(
        self,
        check_authenticated_mock: MagicMock,
        lambda_app: APIGatewayHttpResolver,
    ) -> None:
        check_authenticated_mock.return_value = True

        event = self._create_test_event(
            path_params="pdm/FHIR/R4/Bundle",
            request_method="POST",
            headers={"X-Request-ID": "8c64be5f-3d7a-4b7b-8260-b716d122bdaf"},
            body="",
        )
        context = LambdaContext()

        response = lambda_app.resolve(event, context)

        assert response["statusCode"] == 400
        assert json.loads(response["body"]) == {
            "resourceType": "OperationOutcome",
            "issue": [
                {
                    "severity": "error",
                    "code": "invalid_request",
                    "details": {
                        "text": "No payload provided.",
                    },
                }
            ],
        }

    @patch("pdm_mock.handler.check_authenticated")
    @patch("pdm_mock.handler.handle_post_request")
    def test_pdm_mock_create_document_internal_server_error(
        self,
        pdm_handle_request_mock: MagicMock,
        check_authenticated_mock: MagicMock,
        lambda_app: APIGatewayHttpResolver,
    ) -> None:

        pdm_handle_request_mock.side_effect = Exception("Test exception")

        check_authenticated_mock.return_value = True

        event = self._create_test_event(
            path_params="pdm/FHIR/R4/Bundle",
            request_method="POST",
            headers={"X-Request-ID": "8c64be5f-3d7a-4b7b-8260-b716d122bdaf"},
            body=json.dumps({"test": "data"}),
        )

        context = LambdaContext()

        response = lambda_app.resolve(event, context)

        assert response["statusCode"] == 500
        assert json.loads(response["body"]) == {"error": "Test exception"}

    @patch("pdm_mock.handler.check_authenticated")
    @patch("pdm_mock.handler.StorageHelper.get_item_by_session_id")
    def test_get_document(
        self,
        mock_storage_helper: MagicMock,
        check_authenticated_mock: MagicMock,
        lambda_app: APIGatewayHttpResolver,
    ) -> None:
        check_authenticated_mock.return_value = None
        mock_storage_helper.return_value = {
            "sessionId": "document_id",
            "document": {"test_key": "test_data"},
        }

        event = self._create_test_event(
            path_params="pdm/mock/Bundle/document_id",
            request_method="GET",
        )

        context = LambdaContext()

        response = lambda_app.resolve(event, context)

        assert response["statusCode"] == 200
        assert json.loads(response["body"]) == {"test_key": "test_data"}

    @patch("pdm_mock.handler.check_authenticated")
    @patch("pdm_mock.handler.StorageHelper.get_item_by_session_id")
    def test_fail_to_get_document(
        self,
        mock_storage_helper: MagicMock,
        check_authenticated_mock: MagicMock,
        lambda_app: APIGatewayHttpResolver,
    ) -> None:
        check_authenticated_mock.return_value = None
        mock_storage_helper.side_effect = ItemNotFoundException("Item not found")

        event = self._create_test_event(
            path_params="pdm/mock/Bundle/document_id",
            request_method="GET",
        )
        context = LambdaContext()

        response = lambda_app.resolve(event, context)

        assert response["statusCode"] == 500
        assert json.loads(response["body"]) == {"error": "Item not found"}

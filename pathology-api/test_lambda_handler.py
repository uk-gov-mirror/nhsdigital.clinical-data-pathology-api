import logging
from collections.abc import Callable
from typing import Any
from unittest.mock import MagicMock, patch

import pydantic
import pytest
from aws_lambda_powertools.utilities.typing import LambdaContext

with (
    patch("pathology_api.environment.apim_authenticator"),
):
    from lambda_handler import handler
    from pathology_api.mns import MnsException

from pathology_api.exception import ValidationError
from pathology_api.fhir.r4.elements import Meta
from pathology_api.fhir.r4.resources import Bundle, OperationOutcome

TEST_CORRELATION_ID = "b876145d-1ebf-4e22-8ff8-275b570c1ec4"


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
            "headers": headers or {},
            "requestContext": {
                "http": {
                    "path": f"/{path_params}",
                    "method": request_method,
                },
                "requestId": "request-id",
                "stage": "$default",
            },
            "httpMethod": request_method,
            "rawPath": f"/{path_params}",
            "rawQueryString": "",
            "pathParameters": {"proxy": path_params},
        }

    def _parse_returned_issue(self, response: str) -> OperationOutcome.Issue:
        response_outcome = OperationOutcome.model_validate_json(response)

        assert len(response_outcome.issue) == 1
        returned_issue = response_outcome.issue[0]
        return returned_issue

    @pytest.fixture
    def bundle(self, build_valid_test_result: Callable[[str, str], Bundle]) -> Bundle:
        return build_valid_test_result("nhs_number", "ods_code")

    @pytest.fixture
    def context(self) -> LambdaContext:
        return LambdaContext()

    @pytest.fixture
    def post_event(self, bundle: Bundle) -> dict[str, Any]:
        return self._create_test_event(
            body=bundle.model_dump_json(by_alias=True),
            path_params="FHIR/R4/Bundle",
            request_method="POST",
            headers={"nhsd-correlation-id": TEST_CORRELATION_ID},
        )

    @patch("lambda_handler.handle_request")
    def test_create_test_result_success(
        self,
        handle_request_mock: MagicMock,
        bundle: Bundle,
        post_event: dict[str, Any],
        context: LambdaContext,
    ) -> None:
        expected_response = Bundle.create(
            id="test-id",
            type="document",
            meta=Meta.with_last_updated(),
            entry=bundle.entries,
        )
        handle_request_mock.return_value = expected_response

        response = handler(post_event, context)

        assert response["statusCode"] == 200
        assert response["headers"]["Content-Type"] == "application/fhir+json"

        response_body = response["body"]
        assert isinstance(response_body, str)

        response_bundle = Bundle.model_validate_json(response_body, by_alias=True)
        assert response_bundle == expected_response

    def test_correlation_id_is_set_on_all_log_records_during_request(
        self, caplog: pytest.LogCaptureFixture, bundle: Bundle, context: LambdaContext
    ) -> None:
        event = self._create_test_event(
            body=bundle.model_dump_json(by_alias=True),
            path_params="FHIR/R4/Bundle",
            request_method="POST",
            headers={"nhsd-correlation-id": "b876145d-1ebf-4e22-8ff8-275b570c1123"},
        )

        with (
            patch("pathology_api.mns.create_event"),
            caplog.at_level(logging.DEBUG),
        ):
            handler(event, context)

        assert len(caplog.records) > 0
        for record in caplog.records:
            assert (
                getattr(record, "correlation_id", None)
                == "b876145d-1ebf-4e22-8ff8-275b570c1123"
            )

    def test_correlation_id_is_cleared_after_request(
        self, caplog: pytest.LogCaptureFixture, bundle: Bundle, context: LambdaContext
    ) -> None:
        # First request sets a correlation ID
        event = self._create_test_event(
            body=bundle.model_dump_json(by_alias=True),
            path_params="FHIR/R4/Bundle",
            request_method="POST",
            headers={"nhsd-correlation-id": "c876145d-1ebf-4e22-8ff8-275b570c1ec4"},
        )
        with (
            patch("pathology_api.mns.create_event"),
            caplog.at_level(logging.DEBUG),
        ):
            handler(event, context)
        caplog.clear()

        # Second request with a different correlation ID — no bleed-through
        event2 = self._create_test_event(
            body=bundle.model_dump_json(by_alias=True),
            path_params="FHIR/R4/Bundle",
            request_method="POST",
            headers={"nhsd-correlation-id": "d876145d-1ebf-4e22-8ff8-275b570c1ec4"},
        )
        with (
            patch("pathology_api.mns.create_event"),
            caplog.at_level(logging.DEBUG),
        ):
            handler(event2, context)

        for record in caplog.records:
            assert (
                getattr(record, "correlation_id", None)
                == "d876145d-1ebf-4e22-8ff8-275b570c1ec4"
            )

    def test_missing_correlation_id_header_returns_500(
        self, bundle: Bundle, context: LambdaContext
    ) -> None:
        event = self._create_test_event(
            body=bundle.model_dump_json(by_alias=True),
            path_params="FHIR/R4/Bundle",
            request_method="POST",
        )

        response = handler(event, context)

        assert response["statusCode"] == 500
        assert response["headers"] == {"Content-Type": "application/fhir+json"}

        returned_issue = self._parse_returned_issue(response["body"])
        assert returned_issue["severity"] == "fatal"
        assert returned_issue["code"] == "exception"
        assert (
            returned_issue["diagnostics"]
            == "Missing required header: nhsd-correlation-id"
        )

    def test_empty_correlation_id_header_returns_500(
        self, bundle: Bundle, context: LambdaContext
    ) -> None:
        event = self._create_test_event(
            body=bundle.model_dump_json(by_alias=True),
            path_params="FHIR/R4/Bundle",
            request_method="POST",
            headers={"nhsd-correlation-id": ""},
        )

        response = handler(event, context)

        assert response["statusCode"] == 500
        returned_issue = self._parse_returned_issue(response["body"])
        assert (
            returned_issue["diagnostics"]
            == "Missing required header: nhsd-correlation-id"
        )

    def test_correlation_id_is_cleared_after_exception_mid_handler(
        self, context: LambdaContext
    ) -> None:
        from pathology_api.request_context import get_correlation_id

        event = self._create_test_event(
            body="invalid json",
            path_params="FHIR/R4/Bundle",
            request_method="POST",
            headers={"nhsd-correlation-id": TEST_CORRELATION_ID},
        )

        handler(event, context)

        assert get_correlation_id() == ""

    def test_create_test_result_no_payload(self, context: LambdaContext) -> None:
        event = self._create_test_event(
            path_params="FHIR/R4/Bundle",
            request_method="POST",
            headers={"nhsd-correlation-id": TEST_CORRELATION_ID},
        )

        response = handler(event, context)

        assert response["statusCode"] == 400
        assert response["headers"]["Content-Type"] == "application/fhir+json"

        returned_issue = self._parse_returned_issue(response["body"])

        assert returned_issue["severity"] == "error"
        assert returned_issue["code"] == "invalid"
        assert (
            returned_issue["diagnostics"]
            == "Resources must be provided as a bundle of type 'document'"
        )

    def test_create_test_result_empty_payload(self, context: LambdaContext) -> None:
        event = self._create_test_event(
            body="{}",
            path_params="FHIR/R4/Bundle",
            request_method="POST",
            headers={"nhsd-correlation-id": TEST_CORRELATION_ID},
        )

        response = handler(event, context)

        assert response["statusCode"] == 400
        assert response["headers"]["Content-Type"] == "application/fhir+json"

        returned_issue = self._parse_returned_issue(response["body"])

        assert returned_issue["severity"] == "error"
        assert returned_issue["code"] == "invalid"
        assert (
            returned_issue["diagnostics"]
            == "('resourceType',) - Field required \n('type',) - Field required \n"
        )

    def test_create_test_result_invalid_json(self, context: LambdaContext) -> None:
        event = self._create_test_event(
            body="invalid json",
            path_params="FHIR/R4/Bundle",
            request_method="POST",
            headers={"nhsd-correlation-id": TEST_CORRELATION_ID},
        )

        response = handler(event, context)

        assert response["statusCode"] == 400
        assert response["headers"]["Content-Type"] == "application/fhir+json"

        returned_issue = self._parse_returned_issue(response["body"])
        assert returned_issue["severity"] == "error"
        assert returned_issue["code"] == "invalid"
        assert returned_issue["diagnostics"] == "Invalid payload provided."

    @pytest.mark.parametrize(
        ("error", "expected_issue", "expected_status_code"),
        [
            pytest.param(
                ValidationError("Test processing error"),
                OperationOutcome.Issue(
                    severity="error",
                    code="invalid",
                    diagnostics="Test processing error",
                ),
                400,
                id="ValidationError",
            ),
            pytest.param(
                Exception("Test general error"),
                {
                    "severity": "fatal",
                    "code": "exception",
                    "diagnostics": "An unexpected error has occurred. "
                    "Please try again later.",
                },
                500,
                id="Unexpected exception",
            ),
            pytest.param(
                MnsException("Test MNS error"),
                {
                    "severity": "fatal",
                    "code": "exception",
                    "diagnostics": "Failed to publish an event",
                },
                500,
                id="MnsException",
            ),
        ],
    )
    @patch("lambda_handler.handle_request")
    def test_create_test_result_processing_error(
        self,
        handle_request_mock: MagicMock,
        error: type[Exception],
        expected_issue: OperationOutcome.Issue,
        expected_status_code: int,
        post_event: dict[str, Any],
        context: LambdaContext,
    ) -> None:
        handle_request_mock.side_effect = error
        response = handler(post_event, context)

        assert response["statusCode"] == expected_status_code
        assert response["headers"]["Content-Type"] == "application/fhir+json"

        returned_issue = self._parse_returned_issue(response["body"])
        assert returned_issue == expected_issue

    @pytest.mark.parametrize(
        ("expected_error", "expected_diagnostic"),
        [
            pytest.param(
                ValidationError("Test validation error"),
                "Test validation error",
                id="ValidationError",
            ),
            pytest.param(
                pydantic.ValidationError.from_exception_data(
                    "Test validation error",
                    [{"type": "missing", "loc": ("field",), "input": "is invalid"}],
                ),
                "('field',) - Field required \n",
                id="Pydantic ValidationError",
            ),
        ],
    )
    def test_create_test_result_model_validate_error(
        self,
        expected_error: Exception,
        expected_diagnostic: str,
        post_event: dict[str, Any],
        context: LambdaContext,
    ) -> None:
        with patch(
            "pathology_api.fhir.r4.resources.Bundle.model_validate",
            side_effect=expected_error,
        ):
            response = handler(post_event, context)

            assert response["statusCode"] == 400
            assert response["headers"]["Content-Type"] == "application/fhir+json"

            returned_issue = self._parse_returned_issue(response["body"])
            assert returned_issue["severity"] == "error"
            assert returned_issue["code"] == "invalid"
            assert returned_issue["diagnostics"] == expected_diagnostic

    def test_status_success(self, context: LambdaContext) -> None:
        event = self._create_test_event(
            path_params="_status",
            request_method="GET",
            headers={"nhsd-correlation-id": TEST_CORRELATION_ID},
        )

        response = handler(event, context)

        assert response["statusCode"] == 200
        assert response["body"] == '{"status": "pass"}'
        assert response["headers"]["Content-Type"] == "application/json"

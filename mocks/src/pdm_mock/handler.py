import json
import os
from collections.abc import Callable
from datetime import datetime, timezone
from time import time
from typing import Any, TypedDict, cast
from uuid import uuid4

from apim_mock.auth_check import check_authenticated
from aws_lambda_powertools.event_handler import Response
from aws_lambda_powertools.event_handler.router import APIGatewayHttpRouter
from common.logging import get_logger
from common.storage_helper import BaseMockItem, StorageHelper
from common.utils import check_valid_uuid4

PDM_TABLE_NAME = os.environ["PDM_TABLE_NAME"]
BRANCH_NAME = os.environ["DDB_INDEX_TAG"]


# Constructor for APIGatewayHttpRouter leads to untyped code.
pdm_routes = APIGatewayHttpRouter()  # type: ignore
storage_helper = StorageHelper(PDM_TABLE_NAME, BRANCH_NAME)
_logger = get_logger(__name__)


class PDMResponse(TypedDict):
    status_code: int
    response: dict[str, Any]


class DocumentItem(BaseMockItem):
    document: dict[str, Any]


type RequestHandler = Callable[[], PDMResponse]


def _create_operation_outcome(
    status_code: int, error_text: str, error_code: str
) -> PDMResponse:
    return {
        "status_code": status_code,
        "response": {
            "resourceType": "OperationOutcome",
            "issue": [
                {
                    "severity": "error",
                    "code": error_code,
                    "details": {
                        "text": error_text,
                    },
                }
            ],
        },
    }


def _raise_error(status_code: int, error_text: str, error_code: str) -> RequestHandler:
    return lambda: _create_operation_outcome(status_code, error_text, error_code)


REQUEST_HANDLERS: dict[str, RequestHandler] = {
    "PDM_VALIDATION_ERROR": _raise_error(
        422,
        "Bundle size exceeds maximum allowed size or number of entries.",
        "invariant",
    ),
    "PDM_SERVER_ERROR": _raise_error(
        500,
        "Internal server error",
        "exception",
    ),
}


def _fetch_patient_from_payload(payload: dict[str, Any]) -> str | None:
    patient_values = [
        str(patient)
        for entry in payload.get("entry", [])
        if (resource := entry.get("resource"))
        and resource.get("resourceType") == "Patient"
        and "identifier" in resource
        and (patient := resource.get("identifier", {}).get("value"))
    ]

    if not patient_values:
        return None

    if len(patient_values) > 1:
        raise ValueError("Multiple patients referenced within the same bundle")

    return str(patient_values[0])


def handle_post_request(payload: dict[str, Any]) -> PDMResponse:
    if (patient := _fetch_patient_from_payload(payload)) in REQUEST_HANDLERS:
        _logger.debug("Using magic patient id bypass, %s", patient)
        return REQUEST_HANDLERS[patient]()

    _logger.debug("Not using magic patient id bypass")

    document_id = str(uuid4())
    created_document = {
        **payload,
        "id": document_id,
        "meta": {
            "versionId": "1",
            "last_updated": datetime.now(tz=timezone.utc)
            .isoformat()
            .replace("+00:00", "Z"),
        },
    }
    item: DocumentItem = {
        "sessionId": document_id,
        "expiresAt": int(time()) + 600,
        "document": created_document,
        "type": "pdm_document",
    }

    _write_document_to_table(item)

    return {"status_code": 201, "response": created_document}


def handle_get_request(document_id: str) -> PDMResponse:

    table_item = _get_document_from_table(document_id)
    document = table_item["document"]

    return {"status_code": 200, "response": document}


def _write_document_to_table(item: DocumentItem) -> None:
    _logger.debug("Writing document to dynamodb table")
    storage_helper.put_item(item)


def _get_document_from_table(document_id: str) -> DocumentItem:
    _logger.debug("Retrieving document from dynamodb table")
    item = storage_helper.get_item_by_session_id(document_id)
    return cast("DocumentItem", item)


def _with_default_headers(response: PDMResponse) -> Response[str]:
    return Response(
        body=json.dumps(response["response"]),
        status_code=response["status_code"],
        headers={"Content-Type": "application/fhir+json"},
    )


@pdm_routes.post("/pdm/FHIR/R4/Bundle")
def create_document() -> Response[str]:
    _logger.debug("Post a document endpoint called")

    request_headers = pdm_routes.current_event.headers

    check_authenticated(request_headers)

    _logger.debug("Passed Auth Check")

    x_request_id = request_headers.get("X-Request-ID")
    if not x_request_id:
        _logger.error("Missing X-Request-ID header.")
        return _with_default_headers(
            _create_operation_outcome(400, "Missing X-Request-ID header", "required")
        )
    if not check_valid_uuid4(x_request_id):
        _logger.error("Invalid X-Request-ID header. Value provided: %s", x_request_id)
        return _with_default_headers(
            _create_operation_outcome(400, "Invalid X-Request-ID header", "invalid")
        )

    try:
        payload = pdm_routes.current_event.json_body
    except json.JSONDecodeError as err:
        _logger.error("Error decoding JSON payload. error: %s", err)
        return _with_default_headers(
            _create_operation_outcome(
                400, "Invalid Payload provided.", "invalid_request"
            )
        )
    _logger.debug("Payload received: %s", payload)

    if not payload:
        _logger.error("No payload provided.")
        return _with_default_headers(
            _create_operation_outcome(400, "No payload provided.", "invalid_request")
        )

    try:
        response = handle_post_request(payload)
    except Exception as err:
        _logger.exception("Error handling PDM request")
        return Response(status_code=500, body=json.dumps({"error": str(err)}))

    return Response(
        body=json.dumps(response["response"]),
        status_code=response["status_code"],
        headers={
            "Content-Type": "application/fhir+json",
            "x-request-id": x_request_id,
            "etag": 'W/"1"',
        },
    )


@pdm_routes.get("/pdm/mock/Bundle/<document_id>")
def get_document(document_id: str) -> Response[str]:
    _logger.debug("Get a document endpoint called with document_id: %s", document_id)

    try:
        response = handle_get_request(document_id)
    except Exception as err:
        _logger.exception("Error handling PDM request")
        return Response(status_code=500, body=json.dumps({"error": str(err)}))

    return _with_default_headers(response)

import json
import os
from collections.abc import Callable
from time import time
from typing import Any, TypedDict, cast
from uuid import uuid4

from apim_mock.auth_check import check_authenticated
from aws_lambda_powertools.event_handler import Response
from aws_lambda_powertools.event_handler.router import APIGatewayHttpRouter
from boto3.dynamodb.conditions import Attr
from common.logging import get_logger
from common.storage_helper import BaseMockItem, StorageHelper

MNS_TABLE_NAME = os.environ["MNS_TABLE_NAME"]
BRANCH_NAME = os.environ["DDB_INDEX_TAG"]

# Constructor for APIGatewayHttpRouter leads to untyped code.
mns_routes = APIGatewayHttpRouter()  # type: ignore
storage_helper = StorageHelper(MNS_TABLE_NAME, BRANCH_NAME)

_logger = get_logger(__name__)


class MNSResponse(TypedDict):
    status_code: int
    response: dict[str, Any]


class EventItem(BaseMockItem):
    event: dict[str, Any]
    subject: str


type RequestHandler = Callable[[], MNSResponse]


def _create_operation_outcome(
    status_code: int, response: dict[str, Any]
) -> MNSResponse:
    return {"status_code": status_code, "response": response}


def _raise_validation_error(event_type: str) -> RequestHandler:
    return lambda: _create_operation_outcome(
        400, {"validationErrors": {"type": event_type}}
    )


def _raise_authentication_error(fault_string: str, error_code: str) -> RequestHandler:
    return lambda: _create_operation_outcome(
        401,
        {"fault": {"faultstring": fault_string, "detail": {"errorcode": error_code}}},
    )


def _raise_server_error(status_code: int, errors: str) -> RequestHandler:
    return lambda: _create_operation_outcome(status_code, {"errors": errors})


REQUEST_HANDLERS: dict[str, RequestHandler] = {
    "MNS_VALIDATION_ERROR": _raise_validation_error(
        "Please provide a valid event type"
    ),
    "MNS_AUTHENTICATION_ERROR": _raise_authentication_error(
        "Invalid access token", "oauth.v2.InvalidAccessToken"
    ),
    "MNS_SERVER_ERROR": _raise_server_error(500, "Internal server error"),
}


def handle_post_request(payload: dict[str, Any]) -> MNSResponse:
    if (subject := payload["subject"]) in REQUEST_HANDLERS:
        return REQUEST_HANDLERS[subject]()

    event_id = str(uuid4())
    event_item: EventItem = {
        "sessionId": event_id,
        "expiresAt": int(time()) + 600,
        "type": "mns_event",
        "event": payload,
        "subject": payload["subject"],
    }

    _write_event_to_table(event_item)

    return {"status_code": 200, "response": {"id": payload["id"]}}


def handle_get_request(subject: str) -> MNSResponse:

    table_item = _get_event_from_table(subject)
    event = table_item["event"]

    return {"status_code": 200, "response": event}


def _write_event_to_table(event: EventItem) -> None:
    storage_helper.put_item(event)


def _get_event_from_table(subject: str) -> EventItem:
    expression = Attr("subject").eq(subject)
    item = storage_helper.find_items(expression)[0]
    return cast("EventItem", item)


def _with_default_headers(response: MNSResponse) -> Response[str]:
    return Response(
        body=json.dumps(response["response"]),
        status_code=response["status_code"],
        headers={"Content-Type": "application/fhir+json"},
    )


@mns_routes.post("/mns/events")
def create_event() -> Response[str]:
    _logger.debug("Post an event endpoint called")

    request_headers = mns_routes.current_event.headers

    check_authenticated(request_headers)

    try:
        payload = mns_routes.current_event.json_body
    except json.JSONDecodeError as err:
        _logger.error("Error decoding JSON payload. Error: %s", err)
        return _with_default_headers(
            _create_operation_outcome(
                400, {"validationErrors": {"type": "Invalid payload provided"}}
            )
        )

    if not payload:
        _logger.error("No payload provided.")
        return _with_default_headers(
            _create_operation_outcome(
                400, {"validationErrors": {"type": "No payload provided"}}
            )
        )

    _logger.debug(
        "Payload received: %s",
        {k: v for k, v in payload.items() if k.lower() != "subject"},
    )

    try:
        response = handle_post_request(payload)
    except Exception as err:
        _logger.exception("Error handling MNS request")
        return Response(status_code=500, body=json.dumps({"error": str(err)}))

    return _with_default_headers(response)


@mns_routes.get("/mns/mock/event/<subject>")
def get_event(subject: str) -> Response[str]:
    _logger.debug("Get an event endpoint called with the subject: %s", subject)

    try:
        response = handle_get_request(subject)
    except Exception as err:
        _logger.exception("Error handling MNS Mock request")
        return Response(status_code=500, body=json.dumps({"error": str(err)}))

    return _with_default_headers(response)

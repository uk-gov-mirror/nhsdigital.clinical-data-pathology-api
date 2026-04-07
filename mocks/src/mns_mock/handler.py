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
    response: dict[str, Any] | None


class EventItem(BaseMockItem):
    event: dict[str, Any]
    subject: str


type RequestHandler = Callable[[], MNSResponse]


def _create_response(
    status_code: int, response: dict[str, Any] | None = None
) -> MNSResponse:
    return {"status_code": status_code, "response": response}


def _raise_validation_error(event_type: str) -> RequestHandler:
    return lambda: _create_response(400, {"validationErrors": {"type": event_type}})


def _raise_authentication_error(fault_string: str, error_code: str) -> RequestHandler:
    return lambda: _create_response(
        401,
        {"fault": {"faultstring": fault_string, "detail": {"errorcode": error_code}}},
    )


def _raise_error(status_code: int, errors: str) -> RequestHandler:
    return lambda: _create_response(status_code, {"errors": errors})


REQUEST_HANDLERS: dict[str, RequestHandler] = {
    "MNS_VALIDATION_ERROR": _raise_validation_error(
        "Please provide a valid event type"
    ),
    "MNS_AUTHENTICATION_ERROR": _raise_authentication_error(
        "Invalid access token", "oauth.v2.InvalidAccessToken"
    ),
    "MNS_AUTHORIZATION_ERROR": _raise_error(
        403, "User is not authorized to handle the requested event type"
    ),
    "MNS_SERVER_ERROR": _raise_error(500, "Internal server error"),
    "MNS_BAD_GATEWAY_ERROR": lambda: _create_response(502),
    "MNS_GATEWAY_TIMEOUT_ERROR": lambda: _create_response(504),
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


def handle_search(subject: str) -> MNSResponse:
    events = [item["event"] for item in _find_events_in_table(subject)]
    return {"status_code": 200, "response": {"events": events}}


def _write_event_to_table(event: EventItem) -> None:
    storage_helper.put_item(event)


def _find_events_in_table(subject: str) -> list[EventItem]:
    expression = Attr("subject").eq(subject)
    return [cast("EventItem", item) for item in storage_helper.find_items(expression)]


def _with_default_headers(response: MNSResponse) -> Response[str]:
    if response["response"] is not None:
        body = json.dumps(response["response"])
        headers = {"Content-Type": "application/fhir+json"}
    else:
        body = None
        headers = None

    return Response(body=body, status_code=response["status_code"], headers=headers)


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
            _create_response(
                400, {"validationErrors": {"type": "Invalid payload provided"}}
            )
        )

    if not payload:
        _logger.error("No payload provided.")
        return _with_default_headers(
            _create_response(400, {"validationErrors": {"type": "No payload provided"}})
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


@mns_routes.get("/mns/mock/event")
def search_events() -> Response[str]:
    query_parameters = mns_routes.current_event.query_string_parameters
    if "subject" not in query_parameters:
        return Response(status_code=400, body="No subject provided with request")

    subject = query_parameters["subject"]
    _logger.debug("Get an event endpoint called with the subject: %s", subject)

    try:
        response = handle_search(subject)
    except Exception as err:
        _logger.exception("Error handling MNS Mock request")
        return Response(status_code=500, body=json.dumps({"error": str(err)}))

    return Response(
        status_code=response["status_code"],
        body=json.dumps(response["response"]),
        content_type="application/json",
    )

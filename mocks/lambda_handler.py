import json
import logging
from typing import Any
from urllib.parse import parse_qs

from apim_mock.auth_check import check_authenticated
from apim_mock.handler import handle_request as handle_apim_request
from aws_lambda_powertools.event_handler import (
    APIGatewayHttpResolver,
    Response,
)
from aws_lambda_powertools.utilities.typing import LambdaContext
from jwt.exceptions import InvalidTokenError

_logger = logging.getLogger(__name__)

app = APIGatewayHttpResolver()


def _with_default_headers(status_code: int, body: str) -> Response[str]:
    return Response(
        status_code=status_code,
        headers={"Content-Type": "application/json"},
        body=body,
    )


@app.get("/_status")
def status() -> Response[str]:
    _logger.debug("Status check endpoint called")
    return Response(status_code=200, body="OK", headers={"Content-Type": "text/plain"})


@app.get("/")
def root() -> Response[str]:
    """Handler for the preview environment. This simply returns a 200 response with
        the request headers, which can be used to verify and debug how the environment
        is working and to inspect the incoming request.

    Returns:
        dict: Diagnostic 200 response with request headers.
    """

    event = app.current_event
    context = app.append_context

    _logger.info("Lambda context: %s", context)
    headers = event.get("headers", {}) or {}

    # Log headers to CloudWatch
    _logger.info("Incoming request headers:")
    for k, v in headers.items():
        _logger.info("%s: %s", k, v)

    response_body = {
        "message": "ok",
        "headers": headers,
        "requestContext": event.get("requestContext", {}),
    }

    return _with_default_headers(200, body=json.dumps(response_body, indent=2))


@app.post("/apim/oauth2/token")
def post_auth() -> Response[str]:
    _logger.debug("Authentication Mock called")

    payload = app.current_event.decoded_body

    if not payload:
        _logger.error("No payload provided.")
        return Response(status_code=400, body="Bad Request")

    parsed_payload: dict[str, Any] = parse_qs(payload)

    _logger.debug("Payload received %s", parsed_payload)

    try:
        response = handle_apim_request(parsed_payload)
    except InvalidTokenError as err:
        _logger.error("expected exception %s", err)
        _logger.error("Type %s", type(err))
        error_body = {"error": "invalid_request", "error_description": str(err)}
        return _with_default_headers(status_code=400, body=json.dumps(error_body))
    except ValueError as err:
        _logger.error("expected exception %s", err)
        error_body = {"error": "invalid_request", "error_description": str(err)}
        return _with_default_headers(status_code=400, body=json.dumps(error_body))
    except Exception as err:
        _logger.error("unexpected exception %s", err)
        _logger.error("Type %s", type(err))
        return _with_default_headers(status_code=500, body="Internal Server Error")

    return _with_default_headers(
        status_code=200,
        body=json.dumps(response),
    )


@app.route("/apim/check_auth", method=["POST", "GET"])
def check_auth() -> Response[str]:
    headers = app.current_event.headers

    token = headers.get("Authorization", "").replace("Bearer ", "")

    if check_authenticated(token):
        return _with_default_headers(
            status_code=200, body=json.dumps({"message": "ok"})
        )
    else:
        return _with_default_headers(
            status_code=401, body=json.dumps({"message": "Unauthorized"})
        )


def handler(data: dict[str, Any], context: LambdaContext) -> dict[str, Any]:
    return app.resolve(data, context)

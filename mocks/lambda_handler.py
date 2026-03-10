import json
from collections.abc import Callable
from typing import Any

from apim_mock.auth_check import AuthenticationError
from apim_mock.handler import apim_routes
from aws_lambda_powertools.event_handler import (
    APIGatewayHttpResolver,
    Response,
)
from aws_lambda_powertools.utilities.typing import LambdaContext
from common.logging import get_logger
from pdm_mock.handler import pdm_routes

_logger = get_logger(__name__)

app = APIGatewayHttpResolver()
app.include_router(apim_routes)
app.include_router(pdm_routes)

type _ExceptionHandler[T: Exception] = Callable[[T], Response[str]]


def _with_default_headers(status_code: int, body: str) -> Response[str]:
    return Response(
        status_code=status_code,
        headers={"Content-Type": "application/json"},
        body=body,
    )


###### Exception Handlers ######


def _exception_handler[T: Exception](
    exception_type: type[T],
) -> Callable[[_ExceptionHandler[T]], _ExceptionHandler[T]]:
    """
    Exception handler decorator that registers a function as an exception handler
    with the created app whilst maintaining type information.
    """

    def decorator(func: _ExceptionHandler[T]) -> _ExceptionHandler[T]:
        def wrapper(exception: T) -> Response[str]:
            return func(exception)

        app.exception_handler(exception_type)(wrapper)
        return wrapper

    return decorator


@_exception_handler(AuthenticationError)
def handle_authentication_error(_exception: AuthenticationError) -> Response[str]:
    # LOG014: False positive, we are within an exception handler here.
    _logger.info(
        "Authentication failed: %s",
        _exception,
        exc_info=True,  # noqa: LOG014
    )
    return _with_default_headers(401, "")


###### Health Checks ######


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


##########


def handler(data: dict[str, Any], context: LambdaContext) -> dict[str, Any]:
    return app.resolve(data, context)

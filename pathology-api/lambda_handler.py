from collections.abc import Callable
from functools import reduce
from json import JSONDecodeError
from typing import Any

import pydantic
from aws_lambda_powertools.event_handler import (
    APIGatewayHttpResolver,
    Response,
)
from aws_lambda_powertools.utilities.typing import LambdaContext
from pathology_api.exception import ValidationError
from pathology_api.fhir.r4.resources import Bundle, OperationOutcome
from pathology_api.handler import handle_request
from pathology_api.logging import get_logger

_logger = get_logger(__name__)
app = APIGatewayHttpResolver()

type _ExceptionHandler[T: Exception] = Callable[[T], Response[str]]


def _exception_handler[T: Exception](
    exception_type: type[T],
) -> Callable[[_ExceptionHandler[T]], _ExceptionHandler[T]]:
    """
    Exception handler decorator that registers a function as an exception handler with
    the created app whilst maintaining type information.
    """

    def decorator(func: _ExceptionHandler[T]) -> _ExceptionHandler[T]:
        def wrapper(exception: T) -> Response[str]:
            return func(exception)

        app.exception_handler(exception_type)(wrapper)
        return wrapper

    return decorator


def _with_default_headers(status_code: int, body: pydantic.BaseModel) -> Response[str]:
    return Response(
        status_code=status_code,
        headers={"Content-Type": "application/fhir+json"},
        body=body.model_dump_json(by_alias=True, exclude_none=True),
    )


@_exception_handler(ValidationError)
def handle_validation_error(exception: ValidationError) -> Response[str]:
    # LOG014: False positive, we are within an exception handler here.
    _logger.info(
        "ValidationError encountered: %s",
        exception,
        exc_info=True,  # noqa: LOG014
    )
    return _with_default_headers(
        status_code=400,
        body=OperationOutcome.create_validation_error(exception.message),
    )


@_exception_handler(pydantic.ValidationError)
def handle_pydantic_validation_error(
    exception: pydantic.ValidationError,
) -> Response[str]:
    # LOG014: False positive, we are within an exception handler here.
    _logger.info(
        "Pydantic ValidationError encountered: %s",
        exception,
        exc_info=True,  # noqa: LOG014
    )

    operation_outcome = OperationOutcome.create_validation_error(
        reduce(
            lambda acc, e: acc + f"{str(e['loc'])} - {e['msg']} \n",
            exception.errors(),
            "",
        )
    )
    return _with_default_headers(
        status_code=400,
        body=operation_outcome,
    )


@_exception_handler(Exception)
def handle_exception(exception: Exception) -> Response[str]:
    _logger.exception("Unhandled Exception encountered: %s", exception)
    return _with_default_headers(
        status_code=500,
        body=OperationOutcome.create_server_error(
            "An unexpected error has occurred. Please try again later."
        ),
    )


@app.get("/_status")
def status() -> Response[str]:
    _logger.debug("Status check endpoint called")
    return Response(status_code=200, body="OK", headers={"Content-Type": "text/plain"})


@app.post("/FHIR/R4/Bundle")
def post_result() -> Response[str]:
    _logger.debug("Post result endpoint called.")

    try:
        payload = app.current_event.json_body
    except JSONDecodeError as e:
        raise ValidationError("Invalid payload provided.") from e

    _logger.debug("Payload received: %s", payload)

    if payload is None:
        raise ValidationError(
            "Resources must be provided as a bundle of type 'document'"
        )

    bundle = Bundle.model_validate(payload, by_alias=True)

    response = handle_request(bundle)

    return _with_default_headers(
        status_code=200,
        body=response,
    )


def handler(data: dict[str, Any], context: LambdaContext) -> dict[str, Any]:
    return app.resolve(data, context)

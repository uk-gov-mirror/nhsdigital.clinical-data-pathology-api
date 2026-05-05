import json
import secrets
import string
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import parse_qs

import jwt
import requests
from aws_lambda_powertools.event_handler import (
    Response,
)
from aws_lambda_powertools.event_handler.router import APIGatewayHttpRouter
from aws_lambda_powertools.utilities import parameters
from common import environment
from common.logging import get_logger
from common.storage_helper import BaseMockItem, StorageHelper
from common.utils import check_valid_uuid4
from requests import HTTPError

JWT_ALGORITHMS = ["RS512"]
REQUESTS_TIMEOUT = 5
DEFAULT_TOKEN_LIFETIME = 599

TOKEN_TABLE_NAME = environment.values()["mock_table_name"]
BRANCH_NAME = environment.values()["ddb_index_tag"]

# Constructor for APIGatewayHttpRouter leads to untyped code.
apim_routes = APIGatewayHttpRouter()  # type: ignore
storage_helper = StorageHelper(TOKEN_TABLE_NAME, BRANCH_NAME)

_logger = get_logger(__name__)


class TokenItem(BaseMockItem):
    access_token: str


def handle_request(payload: dict[str, Any]) -> dict[str, Any]:

    _validate_payload(payload)

    client_assertion = payload["client_assertion"][0]

    unverified_headers = _get_jwt_headers(client_assertion)
    kid = unverified_headers.get("kid", "")

    public_key = _get_jwk_key_by_kid(kid)

    assertions = jwt.decode(
        client_assertion,
        public_key,
        audience=environment.values()["auth_url"],
        algorithms=JWT_ALGORITHMS,
    )

    _validate_assertions(assertions)

    token = _generate_random_token()
    current_time = int(datetime.now(tz=timezone.utc).timestamp())

    item: TokenItem = {
        "access_token": token,
        "expiresAt": current_time + DEFAULT_TOKEN_LIFETIME,
        "sessionId": token,
        "type": "access_token",
    }

    _write_token_to_table(item)

    response = {
        "access_token": item["access_token"],
        "expires_in": "599",
        "token_type": "Bearer",
    }

    return response


def _validate_payload(payload: dict[str, Any]) -> None:
    if not payload.get("grant_type"):
        raise ValueError("grant_type is missing")
    client_assertion_type = payload.get("client_assertion_type")
    client_assertion = payload.get("client_assertion")
    if (
        not client_assertion_type
        or client_assertion_type[0]
        != "urn:ietf:params:oauth:client-assertion-type:jwt-bearer"
        or len(client_assertion_type) != 1
    ):
        raise ValueError(
            "Missing or invalid client_assertion_type - "
            "must be 'urn:ietf:params:oauth:client-assertion-type:jwt-bearer'"
        )
    if not client_assertion or len(client_assertion) != 1:
        raise ValueError("Missing client_assertion")


def _get_jwt_headers(client_assertion: str) -> dict[str, Any]:
    unverified_headers = jwt.get_unverified_header(client_assertion)  # noqa: S5659
    _logger.debug("unverified headers: %s", unverified_headers)
    algorithm = unverified_headers.get("alg", "")
    if algorithm not in JWT_ALGORITHMS:
        raise ValueError(
            "Invalid 'alg' header in client_assertion JWT - unsupported JWT algorithm"
            " - must be 'RS512'"
        )

    if not unverified_headers.get("kid"):
        raise ValueError("Missing 'kid' header in client_assertion JWT")

    return unverified_headers


def _get_jwk_keys_from_public_url() -> Any:
    _logger.debug("Retrieving keys from url")

    response = requests.get(
        environment.values()["public_key_url"], timeout=REQUESTS_TIMEOUT
    )
    response.raise_for_status()

    response_body = response.json()

    return response_body["keys"]


def _get_jwk_key_by_kid(kid: str) -> Any:

    keys = _get_jwk_keys_from_public_url()

    jwk_key: dict[str, Any] = next((key for key in keys if key.get("kid") == kid), {})

    if not jwk_key:
        raise ValueError(
            "Invalid 'kid' header in client_assertion JWT - no matching public key"
        )

    jwk_key_string = json.dumps(jwk_key)

    key = jwt.algorithms.RSAAlgorithm.from_jwk(jwk_key_string)

    return key


def _validate_assertions(assertions: dict[str, Any]) -> None:
    api_key = parameters.get_secret(environment.values()["api_key_secret_name"])

    if not assertions.get("iss") or not assertions.get("sub"):
        raise ValueError(
            "Missing or non-matching 'iss'/'sub' claims in client_assertion JWT"
        )

    if assertions.get("iss") != api_key or assertions.get("sub") != api_key:
        raise ValueError("Invalid 'iss'/'sub' claims in client_assertion JWT")

    jti = assertions.get("jti", "")
    if not jti:
        raise ValueError("Missing 'jti' claim in client_assertion JWT")

    if not check_valid_uuid4(jti):
        raise ValueError("Invalid UUID4 value for jti")

    if not assertions.get("exp"):
        raise ValueError("Missing exp claim in assertions")

    if datetime.fromtimestamp(assertions["exp"], tz=timezone.utc) > (
        datetime.now(tz=timezone.utc) + timedelta(minutes=5)
    ):
        raise ValueError(
            "Invalid 'exp' claim in client_assertion JWT"
            " - more than 5 minutes in future"
        )


def _generate_random_token() -> str:
    return "".join(
        secrets.choice(
            "-._~+/" + string.ascii_uppercase + string.ascii_lowercase + string.digits
        )
        for _ in range(15)
    )


def _write_token_to_table(item: TokenItem) -> None:
    storage_helper.put_item(item)


##### APIM Mock Routing
def _with_default_headers(status_code: int, body: str) -> Response[str]:
    return Response(
        status_code=status_code,
        headers={"Content-Type": "application/json"},
        body=body,
    )


@apim_routes.post("/apim/oauth2/token")
def post_auth() -> Response[str]:
    _logger.debug("Authentication Mock called")

    payload = apim_routes.current_event.decoded_body

    if not payload:
        _logger.error("No payload provided.")
        return Response(status_code=400, body="Bad Request")

    parsed_payload: dict[str, Any] = parse_qs(payload)

    _logger.debug("Payload received %s", parsed_payload)

    try:
        response = handle_request(parsed_payload)
    except jwt.InvalidTokenError as err:
        _logger.error("expected exception %s", err)
        _logger.error("Type %s", type(err))
        error_body = {"error": "invalid_request", "error_description": str(err)}
        return _with_default_headers(status_code=400, body=json.dumps(error_body))
    except ValueError as err:
        _logger.error("expected exception %s", err)
        error_body = {"error": "invalid_request", "error_description": str(err)}
        return _with_default_headers(status_code=400, body=json.dumps(error_body))
    except HTTPError as err:
        _logger.error("HTTP error occurred: %s", err)
        error_body = {
            "error": "public_key error",
            "error_description": "The JWKS endpoint, for your"
            " client_assertion can't be reached",
        }
        return _with_default_headers(status_code=403, body=json.dumps(error_body))
    except Exception as err:
        _logger.error("unexpected exception %s", err)
        _logger.error("Type %s", type(err))
        return _with_default_headers(status_code=500, body="Internal Server Error")

    return _with_default_headers(
        status_code=200,
        body=json.dumps(response),
    )

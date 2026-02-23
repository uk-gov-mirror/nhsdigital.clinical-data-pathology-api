import json
import os
import re
import secrets
import string
from datetime import datetime, timedelta, timezone
from typing import Any, TypedDict

import boto3
import jwt

from apim_mock.logging import get_logger

_logger = get_logger(__name__)

JWT_ALGORITHMS = ["RS512"]
AUTH_URL = os.environ["AUTH_URL"]
PUBLIC_KEY_URL = os.environ["PUBLIC_KEY_URL"]
API_KEY = os.environ["API_KEY"]
TOKEN_TABLE_NAME = os.environ["TOKEN_TABLE_NAME"]
BRANCH_NAME = os.environ["DDB_INDEX_TAG"]


class TokenItem(TypedDict):
    access_token: str
    expiresAt: int
    ddb_index: str
    sessionId: str
    type: str


def handle_request(payload: dict[str, Any]) -> dict[str, Any]:

    _validate_payload(payload)

    client_assertion = payload["client_assertion"][0]

    unverified_headers = _get_jwt_headers(client_assertion)
    kid = unverified_headers.get("kid", "")

    public_key = _get_jwk_key_from_url_by_kid(kid)

    assertions = jwt.decode(
        client_assertion,
        public_key,
        audience=AUTH_URL,
        algorithms=JWT_ALGORITHMS,
    )

    _validate_assertions(assertions)

    token = _generate_random_token()

    item: TokenItem = {
        "access_token": token,
        "expiresAt": int(datetime.now(tz=timezone.utc).timestamp()) + 599,
        "ddb_index": BRANCH_NAME,
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


def _get_jwk_key_from_url_by_kid(kid: str) -> Any:

    # TODO - once we have our endpoint setup we can query it here
    # _logger.debug("Retrieving keys from url", unverified_headers)
    # with urllib.requests.urlopen(PUBLIC_KEY_URL) as resp:
    #     resp_body = resp.read()
    resp_body = """
    {
        "keys": [
            {
                "kty": "RSA",
                "n": "uCqVUiCd8EAkTaii5tUl0rRu0_u5DKPTseoz9qIsNwNl2iuLOLW_bFy29Oi1JC4V-C8q3KFshygnay7UDXAddlZ6h6V6VoBFLcgjx9kolCP0gNcY8WW9B071tfsjOK_rWS4aOS_jRZA9_SFLX9JM7OtE0dvWfBaKwMIFuj3g4GNfBmla5JfM_6zBw7KuKijTwf0Jjqc11PtbbEEJZLpoXSlJx6tXRHMFHY_XUr3AOMnnpxVhJAat-3Q-ORkTysjj0FS1QdW1Zh93jmoflAFnTosHYvoKU_UQz9t4IKpHg9CIgHjbi21Q-qJZztwLnFH-t4EjNtPEZdma0oR1jWSgKuFkOPgQPyRG5FPQ4bMYmO9RiVl1zZSsuC6eppXsrsW6ZXVDP7TY2KCT2N4SoAK9dMw7Qi3repvjtua6Cny-eZs01YxSygaobIZ6DB0Xu3bAzD0NMNfihBCTAoXBkqCRjKTlnJxOMiS5Sk8HAmZ_unUC_4HAQu7NY_dU8GG5gtGbcuqTZSZyX_ETkfyo9IwFBaiBw8sKEzZ0e_vvhnmlMmn63WtRGVtc2qb7TI6wpVoTlhbY05iF2xAFaeGFTf4_esj63-5DlaCPB8Mf53wIdiifC0l3t4siOT-CZE82Fl7SQ0K-fCBBQOmTXd8QwBzwMlFbtubfvm20J-jFkXOTQ50",
                "e": "AQAB",
                "alg": "RS512",
                "kid": "DEV-1",
                "use": "sig"
            }
        ]
    }
    """  # noqa: E501

    keys = json.loads(resp_body).get("keys", [])

    jwk_key: dict[str, Any] = next((key for key in keys if key.get("kid") == kid), {})

    if not jwk_key:
        raise ValueError(
            "Invalid 'kid' header in client_assertion JWT - no matching public key"
        )

    jwk_key_string = json.dumps(jwk_key)

    key = jwt.algorithms.RSAAlgorithm.from_jwk(jwk_key_string)

    return key


def _validate_assertions(assertions: dict[str, Any]) -> None:
    expected_api_key = API_KEY

    if not assertions.get("iss") or not assertions.get("sub"):
        raise ValueError(
            "Missing or non-matching 'iss'/'sub' claims in client_assertion JWT"
        )

    if (
        assertions.get("iss") != expected_api_key
        or assertions.get("sub") != expected_api_key
    ):
        raise ValueError("Invalid 'iss'/'sub' claims in client_assertion JWT")

    jti = assertions.get("jti", "")
    if not jti:
        raise ValueError("Missing 'jti' claim in client_assertion JWT")

    if not _check_valid_uuid4(jti):
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


def _check_valid_uuid4(string: str) -> bool:
    uuid_regex = (
        r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
    )
    return re.match(uuid_regex, string) is not None


def _generate_random_token() -> str:
    return "".join(
        secrets.choice(
            "-._~+/" + string.ascii_uppercase + string.ascii_lowercase + string.digits
        )
        for _ in range(15)
    )


def _write_token_to_table(item: TokenItem) -> None:
    dynamodb = boto3.resource("dynamodb")
    table = dynamodb.Table(TOKEN_TABLE_NAME)
    table.put_item(Item=item)

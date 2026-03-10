import os
from typing import Any

from boto3.dynamodb.conditions import Attr
from common.storage_helper import StorageHelper

JWT_ALGORITHMS = ["RS512"]
REQUESTS_TIMEOUT = 5
DEFAULT_TOKEN_LIFETIME = 599

AUTH_URL = os.environ["AUTH_URL"]
PUBLIC_KEY_URL = os.environ["PUBLIC_KEY_URL"]
API_KEY = os.environ["API_KEY"]
TOKEN_TABLE_NAME = os.environ["TOKEN_TABLE_NAME"]
BRANCH_NAME = os.environ["DDB_INDEX_TAG"]

storage_helper = StorageHelper(TOKEN_TABLE_NAME, BRANCH_NAME)


class AuthenticationError(Exception):
    pass


def check_authenticated(request_headers: dict[str, Any]) -> None:
    auth_token = request_headers.get("Authorization", "").replace("Bearer ", "")

    filter_expression = Attr("access_token").eq(auth_token)
    query_result = storage_helper.find_items(filter_expression)

    if len(query_result) == 0:
        raise AuthenticationError("Token is not valid or has expired")

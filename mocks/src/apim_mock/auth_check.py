from typing import Any

from boto3.dynamodb.conditions import Attr
from common import environment
from common.logging import get_logger
from common.storage_helper import StorageHelper

TOKEN_TABLE_NAME = environment.values()["mock_table_name"]
BRANCH_NAME = environment.values()["ddb_index_tag"]

storage_helper = StorageHelper(TOKEN_TABLE_NAME, BRANCH_NAME)
_logger = get_logger(__name__)


class AuthenticationError(Exception):
    pass


def check_authenticated(request_headers: dict[str, Any]) -> None:
    auth_token = request_headers.get("Authorization", "").replace("Bearer ", "")

    _logger.debug("Querying DynamoDB table for access token")
    filter_expression = Attr("access_token").eq(auth_token)
    query_result = storage_helper.find_items(filter_expression)

    if len(query_result) == 0:
        raise AuthenticationError("Token is not valid or has expired")

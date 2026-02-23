import os
from time import time

import boto3
from boto3.dynamodb.conditions import Attr, Key

TOKEN_TABLE_NAME = os.environ["TOKEN_TABLE_NAME"]
BRANCH_NAME = os.environ["DDB_INDEX_TAG"]


def check_authenticated(token: str) -> bool:
    dynamodb = boto3.resource("dynamodb")
    table = dynamodb.Table(TOKEN_TABLE_NAME)

    query_result = table.query(
        IndexName="ddb_index",
        KeyConditionExpression=Key("ddb_index").eq(BRANCH_NAME),
        FilterExpression=Attr("access_token").eq(token)
        & Attr("expiresAt").gt(int(time())),
    )

    return len(query_result["Items"]) > 0

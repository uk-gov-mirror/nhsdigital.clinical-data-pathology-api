from time import time
from typing import NotRequired, TypedDict, cast

import boto3
from boto3.dynamodb.conditions import Attr, ConditionBase, Key


class BaseMockItem(TypedDict):
    sessionId: str
    type: str
    expiresAt: int
    ddb_index: NotRequired[str]


class ItemNotFoundException(Exception):
    pass


class StorageHelper:
    def __init__(self, table_name: str, branch_name: str):
        self.table_name = table_name
        self.branch_name = branch_name

        self.dynamodb = boto3.resource("dynamodb")

        self.table = self.dynamodb.Table(self.table_name)

    def get_item_by_session_id(self, session_id: str) -> BaseMockItem:
        response = self.table.get_item(Key={"sessionId": session_id})
        if not response.get("Item"):
            raise ItemNotFoundException("Item not found")

        return cast("BaseMockItem", response.get("Item"))

    def find_items(self, expression: ConditionBase) -> list[BaseMockItem]:
        filter_expression = expression & Attr("expiresAt").gt(int(time()))

        response = self.table.query(
            IndexName="ddb_index",
            KeyConditionExpression=Key("ddb_index").eq(self.branch_name),
            FilterExpression=filter_expression,
        )

        return cast("list[BaseMockItem]", response.get("Items"))

    def put_item(self, item: BaseMockItem) -> None:
        item_with_index = {**item, "ddb_index": self.branch_name}
        self.table.put_item(Item=item_with_index)

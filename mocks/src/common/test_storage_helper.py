from unittest.mock import MagicMock, Mock, patch

import pytest
from boto3.dynamodb.conditions import Attr, Key

from common.storage_helper import ItemNotFoundException, StorageHelper


class TestStorageHelper:
    @patch("boto3.resource")
    def test_get_item_by_session_id(self, mock_boto_resource: MagicMock) -> None:
        mock_dynamodb = Mock()
        mock_boto_resource.return_value = mock_dynamodb
        mock_dynamodb.Table.return_value.get_item.return_value = {
            "Item": {
                "sessionId": "test_session_id",
                "type": "test_type",
                "expiresAt": 1,
                "ddb_index": "test_branch",
            }
        }

        storage_helper = StorageHelper("test_table_name", "test_branch")
        item = storage_helper.get_item_by_session_id("test_session_id")

        mock_dynamodb.Table.return_value.get_item.assert_called_once_with(
            Key={"sessionId": "test_session_id"}
        )
        assert item == {
            "sessionId": "test_session_id",
            "type": "test_type",
            "expiresAt": 1,
            "ddb_index": "test_branch",
        }
        mock_dynamodb.Table.return_value.get_item.assert_called_once_with(
            Key={"sessionId": "test_session_id"}
        )

    @patch("boto3.resource")
    def test_get_item_by_session_id_not_found(
        self, mock_boto_resource: MagicMock
    ) -> None:
        mock_dynamodb = Mock()
        mock_boto_resource.return_value = mock_dynamodb
        mock_dynamodb.Table.return_value.get_item.return_value = {"Item": {}}

        storage_helper = StorageHelper("test_table_name", "test_branch")
        with pytest.raises(ItemNotFoundException, match="Item not found"):
            storage_helper.get_item_by_session_id("test_session_id")

        mock_dynamodb.Table.return_value.get_item.assert_called_once_with(
            Key={"sessionId": "test_session_id"}
        )

    @patch("boto3.resource")
    @patch("common.storage_helper.time")
    def test_query_item(
        self, mock_time: MagicMock, mock_boto_resource: MagicMock
    ) -> None:
        mock_dynamodb = Mock()
        mock_boto_resource.return_value = mock_dynamodb
        mock_dynamodb.Table.return_value.query.return_value = {
            "Items": [
                {
                    "sessionId": "test_session_id",
                    "type": "test_type",
                    "expiresAt": 1,
                    "ddb_index": "test_branch",
                }
            ]
        }

        mock_time.return_value = 1775742286.0369024

        storage_helper = StorageHelper("test_table_name", "test_branch")
        items = storage_helper.find_items(Attr("test_field").eq("test_value"))

        assert items == [
            {
                "sessionId": "test_session_id",
                "type": "test_type",
                "expiresAt": 1,
                "ddb_index": "test_branch",
            }
        ]
        mock_dynamodb.Table.return_value.query.assert_called_once_with(
            IndexName="ddb_index",
            KeyConditionExpression=Key("ddb_index").eq("test_branch"),
            FilterExpression=Attr("test_field").eq("test_value")
            & Attr("expiresAt").gt(1775742286),
        )

    @patch("boto3.resource")
    def test_put_item(self, mock_boto_resource: MagicMock) -> None:
        mock_dynamodb = Mock()
        mock_boto_resource.return_value = mock_dynamodb

        storage_helper = StorageHelper("test_table_name", "test_branch")
        storage_helper.put_item(
            {
                "sessionId": "test_session_id",
                "type": "test_type",
                "expiresAt": 1,
            }
        )

        mock_dynamodb.Table.return_value.put_item.assert_called_once_with(
            Item={
                "sessionId": "test_session_id",
                "type": "test_type",
                "expiresAt": 1,
                "ddb_index": "test_branch",
            }
        )

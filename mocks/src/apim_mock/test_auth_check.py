import os
from types import ModuleType
from unittest.mock import MagicMock, Mock, patch

import pytest

os.environ["TOKEN_TABLE_NAME"] = "token_table"  # noqa: S105 - Dummy value
os.environ["DDB_INDEX_TAG"] = "branch_name"
os.environ["AUTH_URL"] = "auth_url"
os.environ["PUBLIC_KEY_URL"] = "public_key"
os.environ["BRANCH_NAME"] = "branch_name"
os.environ["API_KEY"] = "api_key"


class TestAuthCheck:
    mock_dynamodb_client = Mock()

    @pytest.fixture
    def apim_mock_handler(self) -> ModuleType:
        with (
            patch("boto3.resource") as boto_resource_mock,
        ):
            boto_resource_mock.return_value = self.mock_dynamodb_client
            import apim_mock.auth_check as auth_check

            return auth_check

    @patch("common.storage_helper.StorageHelper.find_items")
    def test_authentication_check(
        self,
        query_by_ddb_index_mock: MagicMock,
        apim_mock_handler: ModuleType,
    ) -> None:
        query_by_ddb_index_mock.return_value = [
            {
                "sessionId": "test_token",
                "access_token": "test_token",
                "ddb_index": "test_branch",
                "expiresAt": 1,
                "type": "access_token",
            }
        ]

        apim_mock_handler.check_authenticated({"Authorization": "Bearer test_token"})

    @patch("common.storage_helper.StorageHelper.find_items")
    def test_failed_authentication_check(
        self,
        query_by_ddb_index_mock: MagicMock,
        apim_mock_handler: ModuleType,
    ) -> None:

        query_by_ddb_index_mock.return_value = []
        with pytest.raises(
            apim_mock_handler.AuthenticationError,
            match="Token is not valid or has expired",
        ):
            apim_mock_handler.check_authenticated(
                {"Authorization": "Bearer test_token"}
            )

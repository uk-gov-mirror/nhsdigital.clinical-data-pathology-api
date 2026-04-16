import importlib
import uuid
from collections.abc import Callable, Generator
from datetime import datetime, timezone
from json import JSONDecodeError
from typing import Any
from unittest.mock import MagicMock, Mock, patch

import pytest
import requests

from pathology_api.request_context import reset_correlation_id, set_correlation_id

mock_session = Mock()


def _mock_auth() -> Callable[..., Any]:
    def _auth_decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            return func(mock_session, *args, **kwargs)

        return wrapper

    return _auth_decorator


with patch("pathology_api.environment.apim_authenticator") as apim_authenticator_mock:
    import pathology_api.mns

    apim_authenticator_mock.return_value.auth = _mock_auth()

    # Reload the module to ensure the patched authenticator is used in case it has
    # already been imported
    importlib.reload(pathology_api.mns)
    from pathology_api.mns import MnsException, create_event


class TestMns:
    def setup_method(self) -> None:
        mock_session.reset_mock(return_value=True, side_effect=True)

    @pytest.fixture(autouse=True)
    def set_correlation_id_for_logger(self) -> Generator[None, None, None]:
        set_correlation_id(
            full_id="test_id_long",
            short_id="test_id",
        )
        yield
        reset_correlation_id()

    @patch("pathology_api.environment.values")
    @patch("pathology_api.mns.datetime")
    @patch("pathology_api.mns.uuid")
    def test_create_event(
        self, uuid_mock: MagicMock, datetime_mock: MagicMock, env_values_mock: MagicMock
    ) -> None:
        mock_env: dict[str, Any] = {
            "pdm_url": "pdm_url",
            "mns_url": "mns_url",
        }

        env_values_mock.return_value = mock_env

        response_value: dict[str, Any] = {"id": "event_id"}
        mock_session.post.return_value.json.return_value = response_value
        mock_session.post.return_value.ok = True

        datetime_mock.now.return_value = datetime(2026, 4, 10, tzinfo=timezone.utc)

        expected_uuid = uuid.uuid4()
        uuid_mock.uuid4.return_value = expected_uuid

        create_event(
            requesting_org="test_org", nhs_number="nhs_number", bundle_id="bundle_id"
        )

        mock_session.post.assert_called_once()

        assert mock_session.post.call_args.args[0] == mock_env["mns_url"]
        assert mock_session.post.call_args.kwargs["headers"] == {
            "Content-Type": "application/cloudevents+json"
        }

        supplied_event = mock_session.post.call_args.kwargs["json"]
        assert supplied_event["source"] == "uk.nhs.pathology-laboratory-reporting"
        assert (
            supplied_event["type"]
            == "pathology-laboratory-reporting-test-result-stored-1"
        )
        assert supplied_event["dataref"] == mock_env["pdm_url"] + "/bundle_id"
        assert supplied_event["subject"] == "nhs_number"
        assert supplied_event["filtering"] == {"requestingOrganisationODS": "test_org"}
        assert supplied_event["time"] == "2026-04-10T00:00:00+00:00"

        assert supplied_event["id"] == str(expected_uuid)

    @patch("pathology_api.environment.values")
    @patch("pathology_api.mns.datetime")
    @patch("pathology_api.mns.uuid")
    def test_create_event_request_failure(
        self, uuid_mock: MagicMock, datetime_mock: MagicMock, env_values_mock: MagicMock
    ) -> None:
        mock_env: dict[str, Any] = {
            "pdm_url": "pdm_url",
            "mns_url": "mns_url",
        }

        env_values_mock.return_value = mock_env

        mock_session.post.return_value.status_code = 400
        mock_session.post.return_value.text = "Response text"
        mock_session.post.return_value.ok = False

        datetime_mock.now.return_value = datetime(2026, 4, 10, tzinfo=timezone.utc)

        expected_uuid = uuid.uuid4()
        uuid_mock.uuid4.return_value = expected_uuid

        with pytest.raises(
            MnsException,
            match=r"Failed to create MNS event. status_code=400 response=Response text",
        ):
            create_event(
                requesting_org="test_org",
                nhs_number="nhs_number",
                bundle_id="bundle_id",
            )

    @patch("pathology_api.environment.values")
    @patch("pathology_api.mns.datetime")
    @patch("pathology_api.mns.uuid")
    def test_create_event_request_throws_exception(
        self, uuid_mock: MagicMock, datetime_mock: MagicMock, env_values_mock: MagicMock
    ) -> None:
        mock_env: dict[str, Any] = {
            "pdm_url": "pdm_url",
            "mns_url": "mns_url",
        }

        env_values_mock.return_value = mock_env

        mock_session.post.side_effect = requests.RequestException("Request failed")

        datetime_mock.now.return_value = datetime(2026, 4, 10, tzinfo=timezone.utc)

        expected_uuid = uuid.uuid4()
        uuid_mock.uuid4.return_value = expected_uuid

        with pytest.raises(MnsException, match="Failed to send request to MNS"):
            create_event(
                requesting_org="test_org",
                nhs_number="nhs_number",
                bundle_id="bundle_id",
            )

    @patch("pathology_api.environment.values")
    @patch("pathology_api.mns.datetime")
    @patch("pathology_api.mns.uuid")
    def test_create_event_json_exception(
        self, uuid_mock: MagicMock, datetime_mock: MagicMock, env_values_mock: MagicMock
    ) -> None:
        mock_env: dict[str, Any] = {
            "pdm_url": "pdm_url",
            "mns_url": "mns_url",
        }

        env_values_mock.return_value = mock_env

        mock_session.post.return_value.json.side_effect = JSONDecodeError(
            "Expecting value", "doc", 0
        )
        mock_session.post.return_value.text = "Response text"
        mock_session.post.return_value.ok = True

        datetime_mock.now.return_value = datetime(2026, 4, 10, tzinfo=timezone.utc)

        expected_uuid = uuid.uuid4()
        uuid_mock.uuid4.return_value = expected_uuid

        with pytest.raises(
            MnsException,
            match=r"Failed to decode MNS response as JSON. response=Response text",
        ):
            create_event(
                requesting_org="test_org",
                nhs_number="nhs_number",
                bundle_id="bundle_id",
            )

    @patch("pathology_api.environment.values")
    @patch("pathology_api.mns.datetime")
    @patch("pathology_api.mns.uuid")
    def test_create_event_response_missing_id(
        self, uuid_mock: MagicMock, datetime_mock: MagicMock, env_values_mock: MagicMock
    ) -> None:
        mock_env: dict[str, Any] = {
            "pdm_url": "pdm_url",
            "mns_url": "mns_url",
        }

        env_values_mock.return_value = mock_env

        mock_session.post.return_value.json.return_value = {"not_id": "value"}
        mock_session.post.return_value.text = "Response text"
        mock_session.post.return_value.ok = True

        datetime_mock.now.return_value = datetime(2026, 4, 10, tzinfo=timezone.utc)

        expected_uuid = uuid.uuid4()
        uuid_mock.uuid4.return_value = expected_uuid

        with pytest.raises(
            MnsException,
            match=r"MNS response does not contain a valid 'id' field. "
            r"response={'not_id': 'value'}",
        ):
            create_event(
                requesting_org="test_org",
                nhs_number="nhs_number",
                bundle_id="bundle_id",
            )

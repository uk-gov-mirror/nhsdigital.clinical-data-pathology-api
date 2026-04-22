import datetime
import importlib
from collections.abc import Callable, Generator
from typing import Any
from unittest.mock import Mock, patch

import pytest

from pathology_api.fhir.r4.elements import LogicalReference, PatientIdentifier
from pathology_api.fhir.r4.resources import Bundle, Composition
from pathology_api.request_context import reset_correlation_id, set_correlation_id

mock_session = Mock()


def _mock_auth() -> Callable[..., Any]:
    def _auth_decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            return func(mock_session, *args, **kwargs)

        return wrapper

    return _auth_decorator


with patch("pathology_api.environment.apim_authenticator") as apim_authenticator_mock:
    import pathology_api.pdm

    apim_authenticator_mock.return_value.auth = _mock_auth()

    # Reload the module to ensure the patched authenticator is used in case it has
    # already been imported
    importlib.reload(pathology_api.pdm)
    from pathology_api.pdm import PdmException, post_document


@pytest.fixture
def default_returned_bundle() -> dict[str, Any]:
    return {
        "type": "document",
        "resourceType": "Bundle",
        "id": "8aa429d6-6281-481c-ae31-df043636245e",
        "meta": {
            "last_updated": datetime.datetime.now(tz=datetime.timezone.utc),
            "version_id": "1",
        },
        "entry": [
            {
                "fullUrl": "patient",
                "resource": {
                    "id": None,
                    "meta": None,
                    "resourceType": "Composition",
                    "subject": {
                        "identifier": {
                            "system": "https://fhir.nhs.uk/Id/nhs-number",
                            "value": "nhs_number",
                        }
                    },
                },
            }
        ],
    }


class TestPDMClient:
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

    @patch("pathology_api.pdm.uuid4")
    def test_post_document_success(
        self, mock_uuid: Mock, default_returned_bundle: dict[str, Any]
    ) -> None:

        ## Arrange
        mock_session.post.return_value.status_code = 201
        mock_session.post.return_value.json.return_value = default_returned_bundle
        mock_session.post.return_value.headers = {"etag": 'W/"1"'}
        mock_uuid.return_value = "x_request_id"

        bundle = Bundle.create(
            type="document",
            entry=[
                Bundle.Entry(
                    fullUrl="patient",
                    resource=Composition.create(
                        subject=LogicalReference(
                            PatientIdentifier.create_with("nhs_number")
                        )
                    ),
                )
            ],
        )

        response = post_document(bundle)

        result_bundle = response.bundle
        assert result_bundle is not None
        assert type(result_bundle) is Bundle
        assert result_bundle.id is not None

        assert result_bundle.bundle_type == bundle.bundle_type
        assert result_bundle.entries == bundle.entries
        assert result_bundle.meta is not None

        result_meta = result_bundle.meta

        assert result_meta.last_updated is not None
        assert result_meta.version_id == "1"

        assert response.etag == 'W/"1"'

        mock_session.post.assert_called_once_with(
            url="pdm_url",
            data=bundle.model_dump_json(by_alias=True, exclude_none=True),
            headers={
                "Content-Type": "application/fhir+json",
                "X-Request-ID": "x_request_id",
            },
        )

    def test_post_document_401(self) -> None:

        mock_session.post.return_value.status_code = 401
        mock_session.post.return_value.text = "error message"

        bundle = Bundle.create(
            type="document",
            entry=[
                Bundle.Entry(
                    fullUrl="patient",
                    resource=Composition.create(
                        subject=LogicalReference(
                            PatientIdentifier.create_with("nhs_number")
                        )
                    ),
                )
            ],
        )

        with pytest.raises(
            PdmException, match="An unexpected internal server error has occured"
        ):
            post_document(bundle)

    def test_post_document_4xx(self) -> None:

        mock_session.post.return_value.status_code = 400
        mock_session.post.return_value.text = "error message"

        bundle = Bundle.create(
            type="document",
            entry=[
                Bundle.Entry(
                    fullUrl="patient",
                    resource=Composition.create(
                        subject=LogicalReference(
                            PatientIdentifier.create_with("nhs_number")
                        )
                    ),
                )
            ],
        )

        with pytest.raises(
            PdmException, match="Failed to store document: error message"
        ):
            post_document(bundle)

    def test_post_document_5xx(self) -> None:
        mock_session.post.return_value.status_code = 500
        mock_session.post.return_value.text = "error message"

        bundle = Bundle.create(
            type="document",
            entry=[
                Bundle.Entry(
                    fullUrl="patient",
                    resource=Composition.create(
                        subject=LogicalReference(
                            PatientIdentifier.create_with("nhs_number")
                        )
                    ),
                )
            ],
        )

        with pytest.raises(
            PdmException, match="Failed to store document: error message"
        ):
            post_document(bundle)

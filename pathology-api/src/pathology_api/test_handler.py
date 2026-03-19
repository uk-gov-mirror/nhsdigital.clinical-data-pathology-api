import datetime
import os
from collections.abc import Callable
from typing import Any
from unittest.mock import MagicMock, Mock, call, patch

import pytest
from requests.exceptions import RequestException

os.environ["CLIENT_TIMEOUT"] = "1s"
os.environ["APIM_TOKEN_URL"] = "apim_url"  # noqa S105 - dummy value
os.environ["APIM_PRIVATE_KEY_NAME"] = "apim_private_key_name"
os.environ["APIM_API_KEY_NAME"] = "apim_api_key_name"
os.environ["APIM_TOKEN_EXPIRY_THRESHOLD"] = "1s"  # noqa S105 - dummy value
os.environ["APIM_KEY_ID"] = "apim_key"
os.environ["PDM_BUNDLE_URL"] = "pdm_bundle_url"

from pathology_api.exception import ValidationError
from pathology_api.fhir.r4.elements import (
    LogicalReference,
    PatientIdentifier,
)
from pathology_api.fhir.r4.resources import Bundle, Composition

mock_session = Mock()


def mock_auth(func: Callable[..., Any]) -> Callable[..., Any]:

    def wrapper(*args: Any, **kwargs: Any) -> Any:
        return func(mock_session, *args, **kwargs)

    return wrapper


with (
    patch("aws_lambda_powertools.utilities.parameters.get_secret") as get_secret_mock,
    patch("pathology_api.apim.ApimAuthenticator") as apim_authenticator_mock,
    patch("pathology_api.http.SessionManager") as session_manager_mock,
):
    apim_authenticator_mock.return_value.auth = mock_auth
    get_secret_mock.side_effect = lambda secret_name: {
        os.environ["APIM_PRIVATE_KEY_NAME"]: "private_key",
        os.environ["APIM_API_KEY_NAME"]: "api_key",
        "mtls_cert_name": "mtls_cert",
        "mtls_key_name": "mtls_key",
    }[secret_name]
    from pathology_api.handler import _create_client_certificate, handle_request


class TestHandleRequest:
    def setup_method(self) -> None:
        mock_session.reset()

    def test_handle_request(self) -> None:
        # Arrange
        bundle = Bundle.create(
            type="document",
            entry=[
                Bundle.Entry(
                    fullUrl="patient",
                    resource=Composition.create(
                        subject=LogicalReference(
                            PatientIdentifier.from_nhs_number("nhs_number")
                        )
                    ),
                )
            ],
        )

        before_call = datetime.datetime.now(tz=datetime.timezone.utc)
        result_bundle = handle_request(bundle)
        after_call = datetime.datetime.now(tz=datetime.timezone.utc)

        assert result_bundle is not None

        assert result_bundle.id is not None

        assert result_bundle.bundle_type == bundle.bundle_type
        assert result_bundle.entries == bundle.entries

        # Verify last_updated field
        assert result_bundle.meta is not None
        created_meta = result_bundle.meta

        assert created_meta.last_updated is not None
        assert before_call <= created_meta.last_updated
        assert created_meta.last_updated <= after_call

        assert created_meta.version_id is None

        mock_session.post.assert_called_once_with(os.environ["PDM_BUNDLE_URL"])

        session_manager_mock.assert_called_once_with(
            client_timeout=datetime.timedelta(seconds=1), client_certificate=None
        )

        apim_authenticator_mock.assert_called_once_with(
            private_key="private_key",
            key_id=os.environ["APIM_KEY_ID"],
            api_key="api_key",
            token_endpoint=os.environ["APIM_TOKEN_URL"],
            token_validity_threshold=datetime.timedelta(seconds=1),
            session_manager=session_manager_mock.return_value,
        )

    def test_handle_request_raises_error_when_send_request_fails(self) -> None:
        # Arrange
        bundle = Bundle.create(
            type="document",
            entry=[
                Bundle.Entry(
                    fullUrl="patient",
                    resource=Composition.create(
                        subject=LogicalReference(
                            PatientIdentifier.from_nhs_number("nhs_number")
                        )
                    ),
                )
            ],
        )

        expected_error_message = "Failed to send request"
        mock_session.post.side_effect = RequestException(expected_error_message)

        with pytest.raises(RequestException, match=expected_error_message):
            handle_request(bundle)

    def test_handle_request_raises_error_when_no_composition_resource(self) -> None:
        bundle = Bundle.create(
            type="document",
            entry=[],
        )

        with pytest.raises(
            ValidationError,
            match="Document must include a single Composition resource",
        ):
            handle_request(bundle)

    def test_handle_request_raises_error_when_multiple_composition_resources(
        self,
    ) -> None:
        composition = Composition.create(
            subject=LogicalReference(PatientIdentifier.from_nhs_number("nhs_number_1"))
        )

        bundle = Bundle.create(
            type="document",
            entry=[
                Bundle.Entry(
                    fullUrl="composition1",
                    resource=composition,
                ),
                Bundle.Entry(
                    fullUrl="composition2",
                    resource=composition,
                ),
            ],
        )

        with pytest.raises(
            ValidationError,
            match="Document must include a single Composition resource",
        ):
            handle_request(bundle)

    @pytest.mark.parametrize(
        ("composition", "expected_error_message"),
        [
            pytest.param(
                Composition.create(subject=None),
                "Composition does not define a valid subject identifier",
                id="No subject",
            )
        ],
    )
    def test_handle_request_raises_error_when_invalid_composition(
        self, composition: Composition, expected_error_message: str
    ) -> None:
        bundle = Bundle.create(
            type="document",
            entry=[
                Bundle.Entry(
                    fullUrl="composition",
                    resource=composition,
                )
            ],
        )

        with pytest.raises(
            ValidationError,
            match=expected_error_message,
        ):
            handle_request(bundle)

    def test_handle_request_raises_error_when_bundle_includes_id(
        self,
    ) -> None:
        composition = Composition.create(
            subject=LogicalReference(PatientIdentifier.from_nhs_number("nhs_number_1"))
        )

        bundle = Bundle.create(
            id="id",
            type="document",
            entry=[Bundle.Entry(fullUrl="composition1", resource=composition)],
        )

        with pytest.raises(
            ValidationError,
            match="Bundles cannot be defined with an existing ID",
        ):
            handle_request(bundle)

    def test_handle_request_raises_error_when_bundle_not_document_type(
        self,
    ) -> None:
        composition = Composition.create(
            subject=LogicalReference(PatientIdentifier.from_nhs_number("nhs_number_1"))
        )

        bundle = Bundle.create(
            type="collection",
            entry=[Bundle.Entry(fullUrl="composition1", resource=composition)],
        )

        with pytest.raises(
            ValidationError,
            match="Resource must be a bundle of type 'document'",
        ):
            handle_request(bundle)


@patch("pathology_api.handler.parameters.get_secret")
def test_create_client_certificate(get_secret_mock: MagicMock) -> None:
    get_secret_mock.side_effect = lambda secret_name: {
        "mtls_cert_name": "mtls_cert",
        "mtls_key_name": "mtls_key",
    }[secret_name]

    certificate_name = "mtls_cert_name"
    key_name = "mtls_key_name"

    client_certificate = _create_client_certificate(certificate_name, key_name)

    assert client_certificate == {
        "certificate": "mtls_cert",
        "key": "mtls_key",
    }

    get_secret_mock.assert_has_calls([call(certificate_name), call(key_name)])

import datetime
import os
from collections.abc import Callable
from typing import Any
from unittest.mock import MagicMock, Mock, call, patch

import pytest
from pydantic import Field
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
    Extension,
    LiteralReference,
    LogicalReference,
    OrganizationIdentifier,
    PatientIdentifier,
    ReferenceExtension,
)
from pathology_api.fhir.r4.resources import (
    Bundle,
    Composition,
    Organization,
    PractitionerRole,
    ServiceRequest,
)
from pathology_api.test_utils import BundleBuilder

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


def _missing_resource_scenarios() -> list[Any]:
    return [
        pytest.param(
            BundleBuilder.with_defaults(composition_func=lambda _: None).build(),
            "Document must include a single Composition resource",
            id="Missing composition resource",
        ),
        pytest.param(
            BundleBuilder.with_defaults(organisation_func=lambda: None).build(),
            "Document must include an Organization resource",
            id="Missing organization resource",
        ),
        pytest.param(
            BundleBuilder.with_defaults(practitioner_role_func=lambda _: None).build(),
            "Document must include a PractitionerRole resource",
            id="Missing practitioner role resource",
        ),
        pytest.param(
            BundleBuilder.with_defaults(service_request_func=lambda _: None).build(),
            "Document must include a ServiceRequest resource",
            id="Missing service request resource",
        ),
    ]


def _invalid_composition_scenarios() -> list[Any]:
    class _InvalidExtension(Extension, type_name="invalid_extension"):
        value: str = Field(..., frozen=True)

    return [
        pytest.param(
            lambda service_request_url: Composition.create(
                subject=None,
                extension=[
                    ReferenceExtension(
                        url="http://hl7.eu/fhir/StructureDefinition/composition-basedOn-order-or-requisition",
                        valueReference=LiteralReference(reference=service_request_url),
                    )
                ],
            ),
            "Composition does not define a valid subject identifier",
            id="Composition with no subject",
        ),
        pytest.param(
            lambda _: Composition.create(
                subject=LogicalReference(
                    PatientIdentifier.from_nhs_number("nhs_number")
                ),
                extension=None,
            ),
            "Composition does not define a valid basedOn-order-or-requisition "
            "extension",
            id="Composition with no extensions",
        ),
        pytest.param(
            lambda service_request_url: Composition.create(
                subject=LogicalReference(
                    PatientIdentifier.from_nhs_number("nhs_number")
                ),
                extension=[
                    _InvalidExtension(
                        url="http://hl7.eu/fhir/StructureDefinition/composition-basedOn-order-or-requisition",
                        value=service_request_url,
                    )
                ],
            ),
            "Extension with url "
            "http://hl7.eu/fhir/StructureDefinition/composition-basedOn-order-or-requisition"
            " is not expected type Reference",
            id="Composition with invalid extension",
        ),
        pytest.param(
            lambda service_request_url: Composition.create(
                subject=LogicalReference(
                    PatientIdentifier.from_nhs_number("nhs_number")
                ),
                extension=[
                    ReferenceExtension(
                        url="invalid",
                        valueReference=LiteralReference(service_request_url),
                    )
                ],
            ),
            "Composition does not define a valid basedOn-order-or-requisition"
            " extension",
            id="Composition with invalid extension URL",
        ),
        pytest.param(
            lambda _: Composition.create(
                subject=LogicalReference(
                    PatientIdentifier.from_nhs_number("nhs_number")
                ),
                extension=[
                    ReferenceExtension(
                        url="http://hl7.eu/fhir/StructureDefinition/composition-basedOn-order-or-requisition",
                        valueReference=LiteralReference("invalid"),
                    )
                ],
            ),
            "ServiceRequest resource not found with provided reference. "
            "Provided reference: invalid",
            id="Composition with invalid service request reference",
        ),
    ]


def _invalid_service_request_scenarios() -> list[Any]:
    return [
        pytest.param(
            ServiceRequest.create(requester=None),
            "ServiceRequest does not define a valid requester",
            id="ServiceRequest with no requester",
        ),
        pytest.param(
            ServiceRequest.create(requester=LiteralReference("invalid")),
            "PractitionerRole resource not found with provided reference. Provided "
            "reference: invalid",
            id="ServiceRequest with invalid requester",
        ),
    ]


def _invalid_practitioner_role_scenarios() -> list[Any]:
    return [
        pytest.param(
            PractitionerRole.create(organization=None),
            r"PractitionerRole \(practitioner_role\) does not define a valid"
            " Organization reference",
            id="PractitionerRole with no organization",
        ),
        pytest.param(
            PractitionerRole.create(organization=LiteralReference("invalid")),
            "Organization resource not found with provided reference. "
            "Provided reference: invalid",
            id="PractitionerRole with invalid organization reference",
        ),
        pytest.param(
            PractitionerRole.create(organization=LiteralReference("service_request")),
            "Organization resource not found with provided reference. "
            "Provided reference: service_request",
            id="PractitionerRole with non-Organization resource reference",
        ),
    ]


def _invalid_organization_scenarios() -> list[Any]:
    return [
        pytest.param(
            Organization.create(identifier=None),
            r"Organisation \(organisation\) does not define a valid subject identifier",
            id="Organization with no identifier",
        ),
        pytest.param(
            Organization.create(identifier=[]),
            r"Organisation \(organisation\) does not define a valid subject identifier",
            id="Organization with empty identifier list",
        ),
        pytest.param(
            Organization.create(
                identifier=[PatientIdentifier.from_nhs_number("nhs_number")]
            ),
            r"Organization \(organisation\) does not define a supported identifier\. "
            r"Supported system 'https://fhir\.nhs\.uk/Id/ods-organization-code'",
            id="Organization with unsupported identifier system",
        ),
        pytest.param(
            Organization.create(
                identifier=[
                    OrganizationIdentifier.from_ods_code("ods_code_1"),
                    OrganizationIdentifier.from_ods_code("ods_code_2"),
                ]
            ),
            r"Organization \(organisation\) defines multiple identifier values\. "
            r"Identifier values: \['ods_code_1', 'ods_code_2'\]",
            id="Organization with multiple ODS identifiers",
        ),
    ]


class TestHandleRequest:
    def setup_method(self) -> None:
        mock_session.reset()

    def test_handle_request(
        self, build_valid_test_result: Callable[[str, str], Bundle]
    ) -> None:
        # Arrange
        bundle = build_valid_test_result("nhs_number_1", "ods_code")

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

    def test_handle_request_raises_error_when_send_request_fails(
        self, build_valid_test_result: Callable[[str, str], Bundle]
    ) -> None:
        # Arrange
        bundle = build_valid_test_result("nhs_number_1", "ods_code")

        expected_error_message = "Failed to send request"
        mock_session.post.side_effect = RequestException(expected_error_message)

        with pytest.raises(RequestException, match=expected_error_message):
            handle_request(bundle)

    @pytest.mark.parametrize(
        ("bundle", "expected_error_message"), _missing_resource_scenarios()
    )
    def test_handle_request_raises_error_when_missing_resource(
        self, bundle: Bundle, expected_error_message: str
    ) -> None:
        with pytest.raises(
            ValidationError,
            match=expected_error_message,
        ):
            handle_request(bundle)

    def test_handle_request_raises_error_when_multiple_composition_resources(
        self,
    ) -> None:
        composition = Composition.create(
            subject=LogicalReference(PatientIdentifier.from_nhs_number("nhs_number_1"))
        )

        bundle = (
            BundleBuilder.with_defaults(composition_func=lambda _: composition)
            .include_resource("composition2", composition)
            .build()
        )

        with pytest.raises(
            ValidationError,
            match="Document must include a single Composition resource",
        ):
            handle_request(bundle)

    @pytest.mark.parametrize(
        ("composition_func", "expected_error_message"),
        _invalid_composition_scenarios(),
    )
    def test_handle_request_raises_error_when_invalid_composition(
        self,
        composition_func: Callable[[str], Composition],
        expected_error_message: str,
    ) -> None:
        bundle = BundleBuilder.with_defaults(composition_func=composition_func).build()

        with pytest.raises(
            ValidationError,
            match=expected_error_message,
        ):
            handle_request(bundle)

    @pytest.mark.parametrize(
        ("service_request", "expected_error_message"),
        _invalid_service_request_scenarios(),
    )
    def test_handle_request_raises_error_when_invalid_service_request(
        self,
        service_request: ServiceRequest,
        expected_error_message: str,
    ) -> None:
        bundle = BundleBuilder.with_defaults(
            service_request_func=lambda _: service_request
        ).build()

        with pytest.raises(
            ValidationError,
            match=expected_error_message,
        ):
            handle_request(bundle)

    @pytest.mark.parametrize(
        ("practitioner_role", "expected_error_message"),
        _invalid_practitioner_role_scenarios(),
    )
    def test_handle_request_raises_error_when_invalid_practitioner_role(
        self,
        practitioner_role: PractitionerRole,
        expected_error_message: str,
    ) -> None:

        bundle = BundleBuilder.with_defaults(
            practitioner_role_func=lambda _: practitioner_role
        ).build()

        with pytest.raises(
            ValidationError,
            match=expected_error_message,
        ):
            handle_request(bundle)

    @pytest.mark.parametrize(
        ("organization", "expected_error_message"),
        _invalid_organization_scenarios(),
    )
    def test_handle_request_raises_error_when_invalid_organization(
        self,
        organization: Organization,
        expected_error_message: str,
    ) -> None:
        bundle = BundleBuilder.with_defaults(
            organisation_func=lambda: organization
        ).build()

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
        bundle = BundleBuilder.with_defaults().with_type("collection").build()

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

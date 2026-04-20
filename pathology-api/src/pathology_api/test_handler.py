import datetime
from collections.abc import Callable, Generator
from typing import Any
from unittest.mock import patch

import pytest
from pydantic import Field

from pathology_api.exception import ValidationError
from pathology_api.fhir.r4.elements import (
    Extension,
    LiteralReference,
    LogicalReference,
    Meta,
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
from pathology_api.request_context import reset_correlation_id, set_correlation_id
from pathology_api.test_utils import BundleBuilder

with (
    patch("pathology_api.environment.apim_authenticator"),
    patch("pathology_api.mns.create_event") as create_event_mock,
    patch("pathology_api.pdm.post_document") as post_document_mock,
):
    from pathology_api.handler import handle_request
    from pathology_api.mns import MnsException
    from pathology_api.pdm import PdmException, PdmResponse


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
    @pytest.fixture(autouse=True)
    def set_correlation_id_for_logger(self) -> Generator[None, None, None]:
        set_correlation_id(
            full_id="test_id_long",
            short_id="test_id",
        )
        yield
        reset_correlation_id()

    def _build_valid_test_result(self) -> Bundle:
        organisation_entry = Bundle.Entry(
            fullUrl="organisation",
            resource=Organization.create(
                identifier=[OrganizationIdentifier.from_ods_code("ods_code")]
            ),
        )

        practitioner_role_entry = Bundle.Entry(
            fullUrl="practitioner_role",
            resource=PractitionerRole.create(
                organization=LiteralReference(reference=organisation_entry.full_url)
            ),
        )

        service_request_entry = Bundle.Entry(
            fullUrl="service_request",
            resource=ServiceRequest.create(
                requester=LiteralReference(reference=practitioner_role_entry.full_url)
            ),
        )

        composition = Composition.create(
            subject=LogicalReference(PatientIdentifier.from_nhs_number("nhs_number_1")),
            extension=[
                ReferenceExtension(
                    url="http://hl7.eu/fhir/StructureDefinition/composition-basedOn-order-or-requisition",
                    valueReference=LiteralReference(service_request_entry.full_url),
                )
            ],
        )

        return Bundle.create(
            type="document",
            entry=[
                organisation_entry,
                practitioner_role_entry,
                service_request_entry,
                Bundle.Entry(
                    fullUrl="composition",
                    resource=composition,
                ),
            ],
        )

    def test_handle_request(
        self,
        build_valid_test_result: Callable[[str, str], Bundle],
    ) -> None:
        # Arrange
        bundle = build_valid_test_result("nhs_number_1", "ods_code")
        expected_bundle = Bundle.create(
            id="generated_id",
            type="document",
            meta=Meta(
                last_updated=datetime.datetime.now(tz=datetime.timezone.utc),
                version_id="1",
            ),
            entry=bundle.entries,
        )
        expected_etag = "generated_etag"

        post_document_mock.return_value = PdmResponse(expected_bundle, expected_etag)

        pdm_response = handle_request(bundle)
        result_bundle = pdm_response.bundle

        assert result_bundle is not None

        assert result_bundle.id is not None

        assert result_bundle.bundle_type == bundle.bundle_type
        assert result_bundle.entries == bundle.entries

        # Verify last_updated field
        assert result_bundle.meta is not None
        created_meta = result_bundle.meta

        assert created_meta.last_updated is not None
        assert created_meta.version_id == "1"

        assert pdm_response.etag == "generated_etag"

        post_document_mock.assert_called_with(bundle)

        create_event_mock.assert_called_once_with(
            requesting_org="ods_code",
            nhs_number="nhs_number_1",
            bundle_id=result_bundle.id,
        )

    def test_handle_request_raises_error_when_create_event_fails(
        self, build_valid_test_result: Callable[[str, str], Bundle]
    ) -> None:
        # Arrange
        bundle = build_valid_test_result("nhs_number_1", "ods_code")

        expected_error_message = "Failed to create bundle"
        create_event_mock.side_effect = MnsException(expected_error_message)

        with pytest.raises(MnsException, match=expected_error_message):
            handle_request(bundle)

    def test_handle_request_raises_error_when_post_request_fails(
        self,
        build_valid_test_result: Callable[[str, str], Bundle],
    ) -> None:
        # Arrange
        bundle = build_valid_test_result("nhs_number_1", "ods_code")

        expected_error_message = "An unexpected internal server error has occured"
        post_document_mock.side_effect = PdmException(expected_error_message)

        with pytest.raises(PdmException, match=expected_error_message):
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

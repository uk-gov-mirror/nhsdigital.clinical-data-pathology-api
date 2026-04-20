from collections.abc import Callable

import pytest
from pathology_api.fhir.r4.elements import (
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
)
from pathology_api.test_utils import BundleBuilder


@pytest.fixture(scope="session")
def build_valid_test_result() -> Callable[[str, str], Bundle]:
    def builder_function(patient: str, ods_code: str) -> Bundle:
        return BundleBuilder.with_defaults(
            composition_func=lambda service_request_url: Composition.create(
                subject=LogicalReference(PatientIdentifier.create_with(patient)),
                extension=[
                    # Using HTTP to match profile required by implementation guide.
                    ReferenceExtension(
                        url="http://hl7.eu/fhir/StructureDefinition/composition-basedOn-order-or-requisition",  # noqa: S5332
                        valueReference=LiteralReference(service_request_url),
                    )
                ],
            ),
            organisation_func=lambda: Organization.create(
                identifier=[OrganizationIdentifier.from_ods_code(ods_code)]
            ),
        ).build()

    return builder_function

from collections.abc import Callable

from pathology_api.fhir.r4.elements import (
    LiteralReference,
    LogicalReference,
    OrganizationIdentifier,
    PatientIdentifier,
    ReferenceExtension,
)
from pathology_api.fhir.r4.resources import (
    Bundle,
    BundleType,
    Composition,
    Organization,
    PractitionerRole,
    Resource,
    ServiceRequest,
)


def _build_composition(service_request_url: str) -> Composition:
    return Composition.create(
        subject=LogicalReference(PatientIdentifier.from_nhs_number("nhs_number")),
        extension=[
            # Using HTTP to match profile required by implementation guide.
            ReferenceExtension(
                url="http://hl7.eu/fhir/StructureDefinition/composition-basedOn-order-or-requisition",  # noqa: S5332
                valueReference=LiteralReference(service_request_url),
            )
        ],
    )


def _build_service_request(practitioner_role_url: str) -> ServiceRequest:
    return ServiceRequest.create(requester=LiteralReference(practitioner_role_url))


def _build_practitioner_role(organisation_url: str) -> PractitionerRole:
    return PractitionerRole.create(
        organization=LiteralReference(reference=organisation_url)
    )


def _build_organisation() -> Organization:
    return Organization.create(
        identifier=[OrganizationIdentifier.from_ods_code("ods_code")]
    )


class BundleBuilder:
    def __init__(self) -> None:
        self._entries: list[Bundle.Entry] = []
        self._type: BundleType | None = None

    def include_resource(self, full_url: str, resource: Resource) -> "BundleBuilder":
        self._entries.append(Bundle.Entry(fullUrl=full_url, resource=resource))
        return self

    def with_type(self, bundle_type: BundleType) -> "BundleBuilder":
        self._type = bundle_type
        return self

    def build(self) -> Bundle:
        if self._type is None:
            raise ValueError("Bundle type must be set before building the Bundle")
        return Bundle.create(
            type=self._type,
            entry=self._entries,
        )

    @staticmethod
    def with_defaults(
        composition_func: Callable[[str], Composition | None] = _build_composition,
        service_request_func: Callable[
            [str], ServiceRequest | None
        ] = _build_service_request,
        practitioner_role_func: Callable[
            [str], PractitionerRole | None
        ] = _build_practitioner_role,
        organisation_func: Callable[[], Organization | None] = _build_organisation,
    ) -> "BundleBuilder":
        organisation_url = "organisation"
        practitioner_role_url = "practitioner_role"
        service_request_url = "service_request"
        composition_url = "composition"

        bundle = BundleBuilder().with_type("document")

        if (organisation := organisation_func()) is not None:
            bundle.include_resource(organisation_url, organisation)

        if (practitioner_role := practitioner_role_func(organisation_url)) is not None:
            bundle.include_resource(practitioner_role_url, practitioner_role)

        if (service_request := service_request_func(practitioner_role_url)) is not None:
            bundle.include_resource(service_request_url, service_request)

        if (composition := composition_func(service_request_url)) is not None:
            bundle.include_resource(composition_url, composition)

        return bundle

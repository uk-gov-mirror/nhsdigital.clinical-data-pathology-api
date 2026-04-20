import uuid

from pathology_api.exception import ValidationError
from pathology_api.fhir.r4.elements import (
    LiteralReference,
    Meta,
    OrganizationIdentifier,
    ReferenceExtension,
)
from pathology_api.fhir.r4.resources import (
    Bundle,
    Composition,
    Organization,
    PractitionerRole,
    ServiceRequest,
)
from pathology_api.logging import get_logger
from pathology_api.mns import create_event

_logger = get_logger(__name__)


def _validate_bundle(bundle: Bundle) -> None:
    if bundle.id is not None:
        raise ValidationError("Bundles cannot be defined with an existing ID")

    if bundle.bundle_type != "document":
        raise ValidationError("Resource must be a bundle of type 'document'")

    if not bundle.has_resource(ServiceRequest):
        raise ValidationError("Document must include a ServiceRequest resource")

    if not bundle.has_resource(PractitionerRole):
        raise ValidationError("Document must include a PractitionerRole resource")

    if not bundle.has_resource(Organization):
        raise ValidationError("Document must include an Organization resource")


def _fetch_composition(bundle: Bundle) -> Composition:
    compositions = bundle.find_resources(Composition)
    if len(compositions) != 1:
        raise ValidationError("Document must include a single Composition resource")

    return compositions[0]


def _fetch_service_request(composition: Composition, bundle: Bundle) -> ServiceRequest:
    request_reference = composition.find_extension(
        # Using HTTP to match profile required by implementation guide.
        url="http://hl7.eu/fhir/StructureDefinition/composition-basedOn-order-or-requisition",  # noqa: S5332
        required_type=ReferenceExtension,
    )

    if request_reference is None:
        raise ValidationError(
            "Composition does not define a valid basedOn-order-or-requisition extension"
        )

    service_request = bundle.get_resource(
        url=request_reference.value.reference, t=ServiceRequest
    )
    if service_request is None:
        raise ValidationError(
            "ServiceRequest resource not found with provided reference. "
            f"Provided reference: {request_reference.value.reference}"
        )

    return service_request


def _fetch_requesting_organisation(
    requester_reference: LiteralReference, bundle: Bundle
) -> OrganizationIdentifier:
    requester = bundle.get_resource(
        url=requester_reference.reference, t=PractitionerRole
    )
    if requester is None:
        raise ValidationError(
            "PractitionerRole resource not found with provided reference. Provided "
            f"reference: {requester_reference.reference}"
        )

    if requester.organization is None:
        raise ValidationError(
            f"PractitionerRole ({requester_reference.reference}) does not define a "
            "valid Organization reference"
        )

    requesting_organisation = bundle.get_resource(
        url=requester.organization.reference, t=Organization
    )
    if requesting_organisation is None:
        raise ValidationError(
            "Organization resource not found with provided reference. "
            f"Provided reference: {requester.organization.reference}"
        )

    if not requesting_organisation.identifier:
        raise ValidationError(
            f"Organisation ({requester.organization.reference}) does not "
            "define a valid subject identifier"
        )

    organisation_identifiers = [
        identifier
        for identifier in requesting_organisation.identifier
        if isinstance(identifier, OrganizationIdentifier)
    ]

    if not organisation_identifiers:
        raise ValidationError(
            f"Organization ({requester.organization.reference}) does not define a "
            "supported identifier. "
            f"Supported system '{OrganizationIdentifier.expected_system}'"
        )

    if len(organisation_identifiers) > 1:
        raise ValidationError(
            f"Organization ({requester.organization.reference}) defines multiple "
            "identifier values. Identifier values: "
            f"{[identifier.value for identifier in organisation_identifiers]}"
        )

    return organisation_identifiers[0]


def handle_request(bundle: Bundle) -> Bundle:
    _logger.debug("Bundle entries: %s", bundle.entries)
    _validate_bundle(bundle)

    composition = _fetch_composition(bundle)
    _logger.debug("Found composition resource: %s", composition)

    service_request = _fetch_service_request(composition, bundle)

    if service_request.requester is None:
        raise ValidationError("ServiceRequest does not define a valid requester")

    requesting_organisation = _fetch_requesting_organisation(
        service_request.requester, bundle
    )
    _logger.debug("Requesting organization: %s", requesting_organisation)

    subject = composition.subject
    if subject is None:
        raise ValidationError("Composition does not define a valid subject identifier")

    return_bundle = Bundle.create(
        id=str(uuid.uuid4()),
        meta=Meta.with_last_updated(),
        identifier=bundle.identifier,
        type=bundle.bundle_type,
        entry=bundle.entries,
    )
    _logger.debug("Return bundle: %s", return_bundle)

    if return_bundle.id is None:
        raise ValueError("Bundle returned from PDM does not include an ID.")

    create_event(
        requesting_org=requesting_organisation.value,
        nhs_number=subject.identifier.value,
        bundle_id=return_bundle.id,
    )

    return return_bundle

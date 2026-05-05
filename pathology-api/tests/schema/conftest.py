from collections.abc import Iterable
from typing import Any

import schemathesis

_SERVICE_REQUEST_EXTENSION_URL = (
    "http://hl7.eu/fhir/StructureDefinition/composition-basedOn-order-or-requisition"
)
_ODS_CODE_SYSTEM_URL = "https://fhir.nhs.uk/Id/ods-organization-code"


def _find_entries(body: dict[str, Any]) -> list[dict[str, Any]]:
    if "entry" in body and isinstance(body["entry"], list):
        return body["entry"]
    return []


def _find_resources(
    entries: Iterable[dict[str, Any]], resource_type: str
) -> list[dict[str, Any]]:
    return [
        item
        for item in entries
        if (resource := item.get("resource")) is not None
        and isinstance(resource, dict)
        and resource.get("resourceType") == resource_type
    ]


def _find_resource_by_url(entries: Iterable[dict[str, Any]], url: str) -> Any | None:
    return next(
        (
            entry["resource"]
            for entry in entries
            if entry.get("fullUrl") == url and isinstance(entry.get("resource"), dict)
        ),
        None,
    )


def _validate_reference(
    entries: Iterable[dict[str, Any]], reference: str, resource_type: str
) -> bool:
    resource = _find_resource_by_url(entries, reference)
    return resource is not None and resource.get("resourceType") == resource_type


def _find_extension(resource: dict[str, Any], url: str) -> Any | None:
    if "extension" not in resource or not isinstance(resource["extension"], list):
        return None

    return next(
        (
            extension
            for extension in resource["extension"]
            if extension.get("url") == url
        ),
        None,
    )


def _add_missing_resource_if_required(
    case: schemathesis.Case, resource_type: str, resource: dict[str, Any]
) -> schemathesis.Case:
    if isinstance(case.body, dict):
        entries = _find_entries(case.body)
        if len(_find_resources(entries, resource_type)) == 0:
            entries.append(resource)
            case.body["entry"] = entries

    return case


@schemathesis.hook("before_call")
def ensure_composition_in_body(
    _ctx: schemathesis.HookContext, case: schemathesis.Case, *_kwargs: Any
) -> schemathesis.Case:
    """
    Hook to ensure that when schemathesis generates a request body,
    it always contains a Composition resource.
    """
    return _add_missing_resource_if_required(
        case,
        "Composition",
        {
            "fullUrl": "composition",
            "resource": {
                "resourceType": "Composition",
                "subject": {
                    "identifier": {
                        "system": "https://fhir.nhs.uk/Id/nhs-number",
                        "value": "nhs_number",
                    }
                },
                "extension": [
                    {
                        "url": _SERVICE_REQUEST_EXTENSION_URL,
                        "valueReference": {"reference": "service_request"},
                    }
                ],
            },
        },
    )


@schemathesis.hook("before_call")
def ensure_service_request_in_body(
    _ctx: schemathesis.HookContext, case: schemathesis.Case, *_kwargs: Any
) -> schemathesis.Case:
    """
    Hook to ensure that when schemathesis generates a request body,
    it always contains a ServiceRequest resource.
    """
    return _add_missing_resource_if_required(
        case,
        "ServiceRequest",
        {
            "fullUrl": "service_request",
            "resource": {
                "resourceType": "ServiceRequest",
                "subject": {
                    "identifier": {
                        "system": "https://fhir.nhs.uk/Id/nhs-number",
                        "value": "nhs_number",
                    }
                },
                "requester": {"reference": "practitioner_role"},
            },
        },
    )


@schemathesis.hook("before_call")
def ensure_practitioner_role_in_body(
    _ctx: schemathesis.HookContext, case: schemathesis.Case, *_kwargs: Any
) -> schemathesis.Case:
    """
    Hook to ensure that when schemathesis generates a request body,
    it always contains a PractitionerRole resource.
    """
    return _add_missing_resource_if_required(
        case,
        "PractitionerRole",
        {
            "fullUrl": "practitioner_role",
            "resource": {
                "resourceType": "PractitionerRole",
                "organization": {"reference": "organization"},
            },
        },
    )


@schemathesis.hook("before_call")
def ensure_organization_in_body(
    _ctx: schemathesis.HookContext, case: schemathesis.Case, *_kwargs: Any
) -> schemathesis.Case:
    """
    Hook to ensure that when schemathesis generates a request body,
    it always contains an Organization resource.
    """
    return _add_missing_resource_if_required(
        case,
        "Organization",
        {
            "fullUrl": "organization",
            "resource": {
                "resourceType": "Organization",
                "identifier": [
                    {
                        "system": _ODS_CODE_SYSTEM_URL,
                        "value": "ods_code",
                    }
                ],
            },
        },
    )


def _ensure_organization_references(
    entries: Iterable[dict[str, Any]],
) -> None:
    for practitioner_role in _find_resources(entries, "PractitionerRole"):
        if not _validate_reference(
            entries,
            practitioner_role["resource"]["organization"]["reference"],
            "Organization",
        ):
            new_ref = _find_resources(entries, "Organization")[0]["fullUrl"]
            practitioner_role["resource"]["organization"]["reference"] = new_ref


def _ensure_practitioner_role_references(
    entries: Iterable[dict[str, Any]],
) -> None:
    for service_request in _find_resources(entries, "ServiceRequest"):
        if not _validate_reference(
            entries,
            service_request["resource"]["requester"]["reference"],
            "PractitionerRole",
        ):
            service_request["resource"]["requester"]["reference"] = _find_resources(
                entries, "PractitionerRole"
            )[0]["fullUrl"]


def _ensure_service_request_references(
    entries: Iterable[dict[str, Any]],
) -> None:
    for composition in _find_resources(entries, "Composition"):
        ext_ref = _find_extension(
            composition["resource"],
            _SERVICE_REQUEST_EXTENSION_URL,
        )
        if ext_ref is None:
            ext_ref = {
                "url": _SERVICE_REQUEST_EXTENSION_URL,
                "valueReference": {"reference": "unknown"},
            }

            composition["resource"].setdefault("extension", []).append(ext_ref)

        if not _validate_reference(
            entries,
            ext_ref["valueReference"]["reference"],
            "ServiceRequest",
        ):
            ext_ref["valueReference"]["reference"] = _find_resources(
                entries, "ServiceRequest"
            )[0]["fullUrl"]


@schemathesis.hook("before_call")
def ensure_organization_includes_single_identifier(
    _ctx: schemathesis.HookContext, case: schemathesis.Case, *_kwargs: Any
) -> schemathesis.Case:
    """
    Hook to ensure that when schemathesis generates a request body,
    any Organization resource included only contains a single identifier.
    """

    def _duplicate_identifiers(item: dict[str, Any]) -> bool:
        return (
            len(
                [
                    identifier
                    for identifier in item["resource"].get("identifier", [])
                    if identifier.get("system") == _ODS_CODE_SYSTEM_URL
                ]
            )
            > 1
        )

    if isinstance(case.body, dict):
        entries = _find_entries(case.body)
        for organization in filter(
            _duplicate_identifiers,
            _find_resources(entries, "Organization"),
        ):
            organization["resource"]["identifier"] = [
                {
                    "system": _ODS_CODE_SYSTEM_URL,
                    "value": "ods_code",
                }
            ]

        case.body["entry"] = entries

    return case


@schemathesis.hook("before_call")
def ensure_non_duplicate_full_urls(
    _ctx: schemathesis.HookContext, case: schemathesis.Case, *_kwargs: Any
) -> schemathesis.Case:
    """
    Hook to ensure that when schemathesis generates a request body,
    it does not contain duplicate fullUrl values.
    """
    if isinstance(case.body, dict):
        entries = _find_entries(case.body)
        existing_full_urls = set[str]()
        for item in entries:
            full_url = item.get("fullUrl") or "None"
            if full_url in existing_full_urls:
                item["fullUrl"] = f"{full_url}_{id(item)}"
            existing_full_urls.add(full_url)

        case.body["entry"] = entries

    return case


@schemathesis.hook("before_call")
def ensure_valid_references_in_body(
    _ctx: schemathesis.HookContext, case: schemathesis.Case, *_kwargs: Any
) -> schemathesis.Case:
    """
    Hook to ensure that when schemathesis generates a request body,
    it contains valid references between resources.
    """
    if isinstance(case.body, dict):
        entries = _find_entries(case.body)
        _ensure_organization_references(entries)
        _ensure_practitioner_role_references(entries)
        _ensure_service_request_references(entries)

        case.body["entry"] = entries

    return case


@schemathesis.hook("filter_body")
def ignore_multiple_composition_requests(
    _: schemathesis.HookContext, body: dict[str, Any]
) -> bool:
    """
    Hook to filter out any requests generated by schemathesis that contain more
    than one Composition resource.
    """
    composition_resources = _find_resources(_find_entries(body), "Composition")
    return len(composition_resources) < 2

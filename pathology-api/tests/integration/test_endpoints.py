"""Integration tests for the pathology API using pytest."""

import json
import uuid
from collections.abc import Callable
from typing import Any, Literal

import pytest
from pathology_api.fhir.r4.resources import (
    Bundle,
    OperationOutcome,
)
from pydantic import BaseModel, HttpUrl

from tests.conftest import Client
from tests.mock_client import MNSMockClient, PDMMockClient


class TestBundleEndpoint:
    def test_bundle_returns_200(
        self,
        client: Client,
        build_valid_test_result: Callable[[str, str], Bundle],
        pdm_mock_client: PDMMockClient,
        mns_mock_client: MNSMockClient,
        pdm_bundle_url: str,
    ) -> None:
        subject = "subject-" + str(uuid.uuid4())
        requesting_ods_code = "ods_code"
        bundle = build_valid_test_result(subject, requesting_ods_code)

        response = client.send(
            data=bundle.model_dump_json(by_alias=True),
            path="FHIR/R4/Bundle",
            request_method="POST",
            headers={"X-Correlation-ID": "bb038f9a-dc45-49e1-bcfd-3ab3c3de5e16"},
        )

        assert response.status_code == 200
        assert response.headers["Content-Type"] == "application/fhir+json"
        assert (
            response.headers["X-Correlation-ID"]
            == "bb038f9a-dc45-49e1-bcfd-3ab3c3de5e16"
        )

        response_data = response.json()
        response_bundle = Bundle.model_validate(response_data, by_alias=True)

        assert response_bundle.bundle_type == bundle.bundle_type
        assert response_bundle.entries == bundle.entries

        # A UUID value so can only check its presence.
        assert response_bundle.id is not None

        assert response_bundle.meta is not None
        response_meta = response_bundle.meta

        print(f"Response meta: {response_meta}")

        assert response_meta.last_updated is not None
        assert response_meta.version_id == "1"

        assert response.headers["etag"] == 'W/"1"'

        sent_request = pdm_mock_client.retrieve_sent_request(response_bundle.id)
        assert sent_request == bundle.model_dump(by_alias=True, exclude_none=True)

        published_events = mns_mock_client.retrieve_sent_messages(subject)
        assert len(published_events) == 1

        published_event = published_events[0]
        assert published_event["subject"] == subject
        assert published_event["dataref"] == pdm_bundle_url + "/" + response_bundle.id
        assert published_event["filtering"] == {
            "requestingOrganisationODS": requesting_ods_code
        }
        assert (
            published_event["type"]
            == "pathology-laboratory-reporting-test-result-stored-1"
        )
        assert published_event["source"] == "uk.nhs.pathology-laboratory-reporting"
        assert published_event["specversion"] == "1.0"

    def test_no_payload_returns_error(self, client: Client) -> None:
        response = client.send_without_payload(
            request_method="POST", path="FHIR/R4/Bundle"
        )
        assert response.status_code == 400

        response_data = response.json()
        assert response_data == {
            "resourceType": "OperationOutcome",
            "issue": [
                {
                    "severity": "error",
                    "code": "invalid",
                    "diagnostics": "Resources must be provided as a bundle of type"
                    " 'document'",
                }
            ],
        }

        assert response.headers["Content-Type"] == "application/fhir+json"
        assert response.status_code == 400

    def test_empty_payload_returns_error(self, client: Client) -> None:
        response = client.send(data="", request_method="POST", path="FHIR/R4/Bundle")
        assert response.status_code == 400

        response_data = response.json()
        assert response_data == {
            "resourceType": "OperationOutcome",
            "issue": [
                {
                    "severity": "error",
                    "code": "invalid",
                    "diagnostics": "Resources must be provided as a bundle of type"
                    " 'document'",
                }
            ],
        }

        assert response.headers["Content-Type"] == "application/fhir+json"
        assert response.status_code == 400

    @pytest.mark.parametrize(
        ("payload", "expected_diagnostic"),
        [
            pytest.param(
                {
                    "resourceType": "Bundle",
                    "type": "document",
                    "entry": [],
                },
                "Document must include a ServiceRequest resource",
                id="empty entries list",
            ),
            pytest.param(
                {"resourceType": "Bundle", "type": "document"},
                "Document must include a ServiceRequest resource",
                id="missing entries list",
            ),
            pytest.param(
                {
                    "resourceType": "Bundle",
                    "type": "document",
                    "entry": [
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
                            },
                        },
                        {
                            "fullUrl": "invalid-resource",
                            "resource": {"resourceType": "InvalidResourceType"},
                        },
                    ],
                },
                "Unsupported resourceType: InvalidResourceType",
                id="bundle with unexpected resource type",
            ),
            pytest.param(
                {
                    "resourceType": "Bundle",
                    "type": "document",
                    "entry": [
                        {
                            "fullUrl": "organization",
                            "resource": {
                                "resourceType": "Organization",
                                "identifier": [
                                    {
                                        "system": "https://fhir.nhs.uk/Id/ods-organization-code",
                                        "value": "ods_code",
                                    }
                                ],
                            },
                        },
                        {
                            "fullUrl": "practitionerrole",
                            "resource": {
                                "resourceType": "PractitionerRole",
                                "organization": {"reference": "organization"},
                            },
                        },
                        {
                            "fullUrl": "servicerequest",
                            "resource": {
                                "resourceType": "ServiceRequest",
                                "requester": {"reference": "practitionerrole"},
                            },
                        },
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
                            },
                        },
                        {
                            "fullUrl": "composition-2",
                            "resource": {
                                "resourceType": "Composition",
                                "subject": {
                                    "identifier": {
                                        "system": "https://fhir.nhs.uk/Id/nhs-number",
                                        "value": "nhs_number",
                                    }
                                },
                            },
                        },
                    ],
                },
                "Document must include a single Composition resource",
                id="bundle with multiple compositions",
            ),
            pytest.param(
                {
                    "resourceType": "Bundle",
                    "type": "document",
                    "entry": [
                        {
                            "fullUrl": "practitionerrole",
                            "resource": {
                                "resourceType": "PractitionerRole",
                                "organization": {"reference": "organization"},
                            },
                        },
                        {
                            "fullUrl": "servicerequest",
                            "resource": {
                                "resourceType": "ServiceRequest",
                                "requester": {"reference": "practitionerrole"},
                            },
                        },
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
                                        "url": "http://hl7.eu/fhir/StructureDefinition/composition-basedOn-order-or-requisition",
                                        "valueReference": {
                                            "reference": "servicerequest",
                                        },
                                    }
                                ],
                            },
                        },
                    ],
                },
                "Document must include an Organization resource",
                id="Missing Organization resource",
            ),
            pytest.param(
                {
                    "resourceType": "Bundle",
                    "type": "document",
                    "entry": [
                        {
                            "fullUrl": "organization",
                            "resource": {
                                "resourceType": "Organization",
                                "identifier": [
                                    {
                                        "system": "https://fhir.nhs.uk/Id/ods-organization-code",
                                        "value": "ods_code",
                                    }
                                ],
                            },
                        },
                        {
                            "fullUrl": "servicerequest",
                            "resource": {
                                "resourceType": "ServiceRequest",
                                "requester": {"reference": "practitionerrole"},
                            },
                        },
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
                                        "url": "http://hl7.eu/fhir/StructureDefinition/composition-basedOn-order-or-requisition",
                                        "valueReference": {
                                            "reference": "servicerequest",
                                        },
                                    }
                                ],
                            },
                        },
                    ],
                },
                "Document must include a PractitionerRole resource",
                id="Missing PractitionerRole resource",
            ),
            pytest.param(
                {
                    "resourceType": "Bundle",
                    "type": "document",
                    "entry": [
                        {
                            "fullUrl": "organization",
                            "resource": {
                                "resourceType": "Organization",
                                "identifier": [
                                    {
                                        "system": "https://fhir.nhs.uk/Id/ods-organization-code",
                                        "value": "ods_code",
                                    }
                                ],
                            },
                        },
                        {
                            "fullUrl": "practitionerrole",
                            "resource": {
                                "resourceType": "PractitionerRole",
                                "organization": {"reference": "organization"},
                            },
                        },
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
                                        "url": "http://hl7.eu/fhir/StructureDefinition/composition-basedOn-order-or-requisition",
                                        "valueReference": {
                                            "reference": "servicerequest",
                                        },
                                    }
                                ],
                            },
                        },
                    ],
                },
                "Document must include a ServiceRequest resource",
                id="Missing ServiceRequest resource",
            ),
        ],
    )
    def test_invalid_payload_returns_error(
        self, client: Client, payload: dict[str, Any], expected_diagnostic: str
    ) -> None:
        response = client.send(
            data=json.dumps(payload), request_method="POST", path="FHIR/R4/Bundle"
        )
        assert response.status_code == 400

        response_data = response.json()
        assert response_data == {
            "resourceType": "OperationOutcome",
            "issue": [
                {
                    "severity": "error",
                    "code": "invalid",
                    "diagnostics": expected_diagnostic,
                }
            ],
        }

    @pytest.mark.parametrize(
        ("composition_builder", "expected_diagnostic"),
        [
            pytest.param(
                lambda service_request_reference: {
                    "resourceType": "Composition",
                    "extension": [
                        {
                            "url": "http://hl7.eu/fhir/StructureDefinition/composition-basedOn-order-or-requisition",
                            "valueReference": {
                                "reference": service_request_reference,
                            },
                        }
                    ],
                },
                "Composition does not define a valid subject identifier",
                id="composition with no subject",
            ),
            pytest.param(
                lambda service_request_reference: {
                    "resourceType": "Composition",
                    "extension": [
                        {
                            "url": "http://hl7.eu/fhir/StructureDefinition/composition-basedOn-order-or-requisition",
                            "valueReference": {
                                "reference": service_request_reference,
                            },
                        }
                    ],
                    "subject": {
                        "identifier": {
                            "system": "https://fhir.nhs.uk/Id/nhs-number",
                            "value": "",
                        }
                    },
                },
                "Composition does not define a valid subject identifier",
                id="composition with subject with empty identifier value",
            ),
            pytest.param(
                lambda _: {
                    "resourceType": "Composition",
                    "subject": {
                        "identifier": {
                            "system": "https://fhir.nhs.uk/Id/nhs-number",
                            "value": "nhs_number",
                        }
                    },
                },
                "Composition does not define a valid basedOn-order-or-requisition "
                "extension",
                id="composition with no extension",
            ),
            pytest.param(
                lambda _: {
                    "resourceType": "Composition",
                    "subject": {
                        "identifier": {
                            "system": "https://fhir.nhs.uk/Id/nhs-number",
                            "value": "nhs_number",
                        }
                    },
                    "extension": [
                        {
                            "url": "http://hl7.eu/fhir/StructureDefinition/composition-basedOn-order-or-requisition",
                            "valueReference": {
                                "reference": "unknown-resource",
                            },
                        }
                    ],
                },
                "ServiceRequest resource not found with provided reference. "
                "Provided reference: unknown-resource",
                id="composition with based on extension referencing unknown resource",
            ),
            pytest.param(
                lambda _: {
                    "resourceType": "Composition",
                    "subject": {
                        "identifier": {
                            "system": "https://fhir.nhs.uk/Id/nhs-number",
                            "value": "nhs_number",
                        }
                    },
                    "extension": [
                        {
                            "url": "http://hl7.eu/fhir/StructureDefinition/composition-basedOn-order-or-requisition",
                            "valueReference": {
                                "reference": "practitionerrole",
                            },
                        }
                    ],
                },
                "ServiceRequest resource not found with provided reference. "
                "Provided reference: practitionerrole",
                id="composition with based on extension referencing wrong resource",
            ),
            pytest.param(
                lambda service_request_url: {
                    "resourceType": "Composition",
                    "subject": {
                        "identifier": {
                            "system": "https://fhir.nhs.uk/Id/nhs-number",
                            "value": "nhs_number",
                        }
                    },
                    "extension": [
                        {
                            "url": "http://hl7.eu/fhir/StructureDefinition/composition-basedOn-order-or-requisition",
                            "valueString": service_request_url,
                        }
                    ],
                },
                "Extension with url "
                "http://hl7.eu/fhir/StructureDefinition"
                "/composition-basedOn-order-or-requisition "
                "is not expected type Reference",
                id="composition with based on extension using wrong type",
            ),
            pytest.param(
                lambda service_request_url: {
                    "resourceType": "Composition",
                    "subject": {
                        "identifier": {
                            "system": "https://fhir.nhs.uk/Id/nhs-number",
                            "value": "nhs_number",
                        }
                    },
                    "extension": [
                        {
                            "url": "wrong-url",
                            "valueReference": {
                                "reference": service_request_url,
                            },
                        }
                    ],
                },
                "Composition does not define a valid basedOn-order-or-requisition "
                "extension",
                id="composition with based on extension using wrong url",
            ),
            pytest.param(
                lambda _: {
                    "resourceType": "Composition",
                    "subject": {"identifier": {"value": "nhs_number"}},
                },
                "('entry', 3, 'resource', 'subject', 'identifier', 'system') "
                "- Field required \n",
                id="composition with subject but no system",
            ),
            pytest.param(
                lambda _: {
                    "resourceType": "Composition",
                    "subject": {
                        "identifier": {"system": "https://fhir.nhs.uk/Id/nhs-number"}
                    },
                },
                "('entry', 3, 'resource', 'subject', 'identifier', 'value')"
                " - Field required \n",
                id="composition with subject but identifier has no value",
            ),
        ],
    )
    def test_invalid_composition_resource(
        self,
        composition_builder: Callable[[str], dict[str, Any]],
        expected_diagnostic: str,
        client: Client,
    ) -> None:
        bundle = {
            "resourceType": "Bundle",
            "type": "document",
            "entry": [
                {
                    "fullUrl": "organization",
                    "resource": {
                        "resourceType": "Organization",
                        "identifier": [
                            {
                                "system": "https://fhir.nhs.uk/Id/ods-organization-code",
                                "value": "ods_code",
                            }
                        ],
                    },
                },
                {
                    "fullUrl": "practitionerrole",
                    "resource": {
                        "resourceType": "PractitionerRole",
                        "organization": {"reference": "organization"},
                    },
                },
                {
                    "fullUrl": "servicerequest",
                    "resource": {
                        "resourceType": "ServiceRequest",
                        "requester": {"reference": "practitionerrole"},
                    },
                },
                {
                    "fullUrl": "composition",
                    "resource": composition_builder("servicerequest"),
                },
            ],
        }

        response = client.send(
            data=json.dumps(bundle), request_method="POST", path="FHIR/R4/Bundle"
        )
        assert response.status_code == 400

        response_data = response.json()
        assert response_data == {
            "resourceType": "OperationOutcome",
            "issue": [
                {
                    "severity": "error",
                    "code": "invalid",
                    "diagnostics": expected_diagnostic,
                }
            ],
        }

    @pytest.mark.parametrize(
        ("service_request", "expected_diagnostic"),
        [
            pytest.param(
                {
                    "resourceType": "ServiceRequest",
                    # No requester field
                },
                "ServiceRequest does not define a valid requester",
                id="ServiceRequest without requester field",
            ),
            pytest.param(
                {
                    "resourceType": "ServiceRequest",
                    "requester": {"reference": "nonexistent-practitionerrole"},
                },
                "PractitionerRole resource not found with provided reference. "
                "Provided reference: nonexistent-practitionerrole",
                id="ServiceRequest requester does not reference a PractitionerRole "
                "resource",
            ),
            pytest.param(
                {
                    "resourceType": "ServiceRequest",
                    "requester": "invalid",
                },
                "('entry', 2, 'resource', 'requester') - Input should be a "
                "dictionary or an instance of LiteralReference \n",
                id="ServiceRequest requester field invalid type",
            ),
        ],
    )
    def test_invalid_service_request_resource(
        self,
        service_request: dict[str, Any],
        expected_diagnostic: str,
        client: Client,
    ) -> None:
        bundle = {
            "resourceType": "Bundle",
            "type": "document",
            "entry": [
                {
                    "fullUrl": "organization",
                    "resource": {
                        "resourceType": "Organization",
                        "identifier": [
                            {
                                "system": "https://fhir.nhs.uk/Id/ods-organization-code",
                                "value": "ods_code",
                            }
                        ],
                    },
                },
                {
                    "fullUrl": "practitionerrole",
                    "resource": {
                        "resourceType": "PractitionerRole",
                        "organization": {"reference": "organization"},
                    },
                },
                {
                    "fullUrl": "servicerequest",
                    "resource": service_request,
                },
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
                                "url": "http://hl7.eu/fhir/StructureDefinition/composition-basedOn-order-or-requisition",
                                "valueReference": {
                                    "reference": "servicerequest",
                                },
                            }
                        ],
                    },
                },
            ],
        }

        response = client.send(
            data=json.dumps(bundle), request_method="POST", path="FHIR/R4/Bundle"
        )
        assert response.status_code == 400

        response_data = response.json()
        assert response_data == {
            "resourceType": "OperationOutcome",
            "issue": [
                {
                    "severity": "error",
                    "code": "invalid",
                    "diagnostics": expected_diagnostic,
                }
            ],
        }

    @pytest.mark.parametrize(
        ("practitioner_role", "expected_diagnostic"),
        [
            pytest.param(
                {
                    "resourceType": "PractitionerRole",
                    # No organization field
                },
                "PractitionerRole (practitionerrole) does not define a valid "
                "Organization reference",
                id="PractitionerRole without organization field",
            ),
            pytest.param(
                {
                    "resourceType": "PractitionerRole",
                    "organization": {"reference": "nonexistent-organization"},
                },
                "Organization resource not found with provided reference. "
                "Provided reference: nonexistent-organization",
                id="PractitionerRole organization does not reference an "
                "Organization resource",
            ),
            pytest.param(
                {
                    "resourceType": "PractitionerRole",
                    "organization": "invalid",
                },
                "('entry', 1, 'resource', 'organization') - Input should be a "
                "dictionary or an instance of LiteralReference \n",
                id="PractitionerRole organization field is invalid",
            ),
        ],
    )
    def test_invalid_practitioner_role_resource(
        self,
        practitioner_role: dict[str, Any],
        expected_diagnostic: str,
        client: Client,
    ) -> None:
        bundle = {
            "resourceType": "Bundle",
            "type": "document",
            "entry": [
                {
                    "fullUrl": "organization",
                    "resource": {
                        "resourceType": "Organization",
                        "identifier": [
                            {
                                "system": "https://fhir.nhs.uk/Id/ods-organization-code",
                                "value": "ods_code",
                            }
                        ],
                    },
                },
                {
                    "fullUrl": "practitionerrole",
                    "resource": practitioner_role,
                },
                {
                    "fullUrl": "servicerequest",
                    "resource": {
                        "resourceType": "ServiceRequest",
                        "requester": {"reference": "practitionerrole"},
                    },
                },
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
                                "url": "http://hl7.eu/fhir/StructureDefinition/composition-basedOn-order-or-requisition",
                                "valueReference": {
                                    "reference": "servicerequest",
                                },
                            }
                        ],
                    },
                },
            ],
        }

        response = client.send(
            data=json.dumps(bundle), request_method="POST", path="FHIR/R4/Bundle"
        )
        assert response.status_code == 400

        response_data = response.json()
        assert response_data == {
            "resourceType": "OperationOutcome",
            "issue": [
                {
                    "severity": "error",
                    "code": "invalid",
                    "diagnostics": expected_diagnostic,
                }
            ],
        }

    @pytest.mark.parametrize(
        ("organization", "expected_diagnostic"),
        [
            pytest.param(
                {
                    "resourceType": "Organization",
                    # No identifier field
                },
                "Organisation (organization) does not define a valid subject "
                "identifier",
                id="organization with no identifier",
            ),
            pytest.param(
                {
                    "resourceType": "Organization",
                    "identifier": [
                        {
                            "system": "https://fhir.nhs.uk/Id/ods-organization-code",
                            "value": "ods_code_1",
                        },
                        {
                            "system": "https://fhir.nhs.uk/Id/ods-organization-code",
                            "value": "ods_code_2",
                        },
                    ],
                },
                "Organization (organization) defines multiple identifier values. "
                "Identifier values: ['ods_code_1', 'ods_code_2']",
                id="organization with multiple identifiers",
            ),
            pytest.param(
                {
                    "resourceType": "Organization",
                    "identifier": [
                        {
                            "system": "https://example.com/unknown-system",
                            "value": "some_value",
                        }
                    ],
                },
                "Organization (organization) does not define a supported identifier. "
                "Supported system 'https://fhir.nhs.uk/Id/ods-organization-code'",
                id="organization with unknown identifier system",
            ),
            pytest.param(
                {
                    "resourceType": "Organization",
                    "identifier": [
                        {
                            "system": "https://fhir.nhs.uk/Id/ods-organization-code",
                            "value": "",
                        }
                    ],
                },
                "Organization (organization) does not define a "
                "supported identifier. "
                r"Supported system 'https://fhir.nhs.uk/Id/ods-organization-code'",
                id="organization with identifier with empty value",
            ),
        ],
    )
    def test_invalid_organization_resource(
        self, organization: dict[str, Any], expected_diagnostic: str, client: Client
    ) -> None:
        bundle = {
            "resourceType": "Bundle",
            "type": "document",
            "entry": [
                {
                    "fullUrl": "organization",
                    "resource": organization,
                },
                {
                    "fullUrl": "practitionerrole",
                    "resource": {
                        "resourceType": "PractitionerRole",
                        "organization": {"reference": "organization"},
                    },
                },
                {
                    "fullUrl": "servicerequest",
                    "resource": {
                        "resourceType": "ServiceRequest",
                        "requester": {"reference": "practitionerrole"},
                    },
                },
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
                                "url": "http://hl7.eu/fhir/StructureDefinition/composition-basedOn-order-or-requisition",
                                "valueReference": {
                                    "reference": "servicerequest",
                                },
                            }
                        ],
                    },
                },
            ],
        }

        response = client.send(
            data=json.dumps(bundle), request_method="POST", path="FHIR/R4/Bundle"
        )
        assert response.status_code == 400

        response_data = response.json()
        assert response_data == {
            "resourceType": "OperationOutcome",
            "issue": [
                {
                    "severity": "error",
                    "code": "invalid",
                    "diagnostics": expected_diagnostic,
                }
            ],
        }

    @pytest.mark.parametrize(
        ("subject"),
        [
            "MNS_VALIDATION_ERROR",
            "MNS_AUTHENTICATION_ERROR",
            "MNS_SERVER_ERROR",
            "MNS_AUTHORIZATION_ERROR",
            "MNS_BAD_GATEWAY_ERROR",
            "MNS_GATEWAY_TIMEOUT_ERROR",
        ],
    )
    def test_unexpected_mns_response(
        self,
        subject: str,
        client: Client,
        build_valid_test_result: Callable[[str, str], Bundle],
    ) -> None:
        bundle = build_valid_test_result(subject, "ods_code")
        response = client.send(
            data=bundle.model_dump_json(by_alias=True),
            path="FHIR/R4/Bundle",
            request_method="POST",
            headers={"X-Correlation-ID": "bb038f9a-dc45-49e1-bcfd-3ab3c3de5e16"},
        )

        assert response.status_code == 500
        assert response.headers["Content-Type"] == "application/fhir+json"
        assert (
            response.headers["X-Correlation-ID"]
            == "bb038f9a-dc45-49e1-bcfd-3ab3c3de5e16"
        )

        assert response.status_code == 500

        response_data = response.json()
        operation_outcome = OperationOutcome.model_validate(response_data)

        issue: OperationOutcome.Issue = {
            "severity": "fatal",
            "code": "exception",
            "diagnostics": "Failed to publish an event",
        }

        assert operation_outcome.issue == [issue]


@pytest.mark.remote_only
class TestStatusEndpoint:
    """Tests for the Proxygen /_status health-check endpoint.

    These tests only run against the APIM proxy (remote), since the
    local Lambda does not serve the proxygen status endpoint.
    """

    @pytest.mark.status_auth_headers
    def test_status_returns_200(self, client: Client) -> None:
        response = client.send_without_payload(request_method="GET", path="_status")
        assert response.status_code == 200
        assert response.headers["Content-Type"] == "application/json"

        print("Received /_status response:", response.json())

        parsed = StatusResponse.model_validate(response.json())

        assert parsed.status == "pass"
        assert parsed.checks.healthcheck.responseCode == 200


class StatusLinks(BaseModel):
    self: HttpUrl


class HealthCheckOutcome(BaseModel):
    status: Literal["pass", "fail"]


class HealthCheck(BaseModel):
    status: Literal["pass", "fail"]
    timeout: Literal["true", "false"]
    responseCode: int
    outcome: dict[Any, Any]
    links: StatusLinks


class Checks(BaseModel):
    healthcheck: HealthCheck


class StatusResponse(BaseModel):
    """Expected shape of the GET /_status response from the APIM proxy.

    This is the Proxygen-standard health check response, not the application's
    own status. Only returned when hitting the proxy URL (remote tests).
    """

    model_config = {"extra": "forbid"}

    status: Literal["pass", "fail"]
    version: str
    spec_hash: str
    proxygen_version: str
    checks: Checks

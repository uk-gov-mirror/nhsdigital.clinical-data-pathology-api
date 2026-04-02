"""Integration tests for the pathology API using pytest."""

import json
from typing import Any, Literal

import pytest
from pathology_api.fhir.r4.elements import LogicalReference, PatientIdentifier
from pathology_api.fhir.r4.resources import Bundle, Composition
from pydantic import BaseModel, HttpUrl

from tests.conftest import Client


class TestBundleEndpoint:
    def test_bundle_returns_200(self, client: Client) -> None:
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
        assert response_meta.last_updated is not None
        assert response_meta.version_id is None

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
                "Document must include a single Composition resource",
                id="empty entries list",
            ),
            pytest.param(
                {"resourceType": "Bundle", "type": "document"},
                "Document must include a single Composition resource",
                id="missing entries list",
            ),
            pytest.param(
                {
                    "resourceType": "Bundle",
                    "type": "document",
                    "entry": [
                        {
                            "fullUrl": "composition",
                            "resource": {"resourceType": "Composition"},
                        }
                    ],
                },
                "Composition does not define a valid subject identifier",
                id="composition with no subject",
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
                                "subject": {"identifier": {"value": "nhs_number"}},
                            },
                        }
                    ],
                },
                "('entry', 0, 'resource', 'subject', 'identifier', 'system') "
                "- Field required \n",
                id="composition with subject but no system",
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
                                        "system": "https://fhir.nhs.uk/Id/nhs-number"
                                    }
                                },
                            },
                        }
                    ],
                },
                "('entry', 0, 'resource', 'subject', 'identifier', 'value')"
                " - Field required \n",
                id="composition with subject but identifier has no value",
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

        parsed = StatusResponse.model_validate(response.json())

        assert parsed.status == "pass"
        assert parsed.checks.healthcheck.responseCode == 200


class StatusLinks(BaseModel):
    self: HttpUrl


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

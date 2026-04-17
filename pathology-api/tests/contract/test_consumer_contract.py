"""Consumer contract tests using Pact for the pathology API.

This test suite acts as a consumer that defines the expected
interactions with the provider (the Flask API).
"""

import requests
from pact import Pact, match


class TestConsumerContract:
    """Consumer contract tests to define expected API behavior."""

    def test_post_bundle(self) -> None:
        """Test the consumer's expectation of the Bundle endpoint.

        This test defines the contract: when the consumer requests
        POST to the Bundle endpoint, with a valid Bundle,
        a 200 response containing the newly created Bundle is returned.
        """
        pact = Pact(consumer="PathologyAPIConsumer", provider="PathologyAPIProvider")

        request_body = {
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
                            },
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
                {
                    "fullUrl": "servicerequest",
                    "resource": {
                        "resourceType": "ServiceRequest",
                        "requester": {"reference": "practitionerrole"},
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
            ],
        }

        response_body = {
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
                            },
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
                {
                    "fullUrl": "servicerequest",
                    "resource": {
                        "resourceType": "ServiceRequest",
                        "requester": {"reference": "practitionerrole"},
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
            ],
            "id": match.uuid(),
            "meta": {
                "lastUpdated": match.datetime(
                    "2026-01-16T12:00:00.000Z", format="%Y-%m-%dT%H:%M:%S.%fZ"
                ),
            },
        }

        # Define the expected interaction
        (
            pact.upon_receiving("a request for the Bundle endpoint")
            .with_body(request_body, content_type="application/fhir+json")
            .with_request(
                method="POST",
                path="/FHIR/R4/Bundle",
            )
            .with_headers(
                {"X-Correlation-ID": "bb038f9a-dc45-49e1-bcfd-3ab3c3de5e16"},
                part="Request",
            )
            .will_respond_with(status=200)
            .with_body(
                response_body,
                content_type="application/fhir+json",
            )
        )

        # Start the mock server and execute the test
        with pact.serve() as server:
            # Make the actual request to the mock provider
            response = requests.post(
                f"{server.url}/FHIR/R4/Bundle",
                json=request_body,
                headers={
                    "Content-Type": "application/fhir+json",
                    "X-Correlation-ID": "bb038f9a-dc45-49e1-bcfd-3ab3c3de5e16",
                },
                timeout=10,
            )

            # Verify the response matches expectations
            assert response.status_code == 200
            assert response.headers["Content-Type"] == "application/fhir+json"

        # Write the pact file after the test
        pact.write_file("tests/contract/pacts")

    def test_status(self) -> None:
        """Test the consumer's expectation of the status endpoint.

        This test defines the contract: when the consumer requests
        GET to the status endpoint, a 200 response with "OK" body is returned.
        """
        status_matcher = match.regex("pass", regex=r"^(pass|ok)$")
        pact = Pact(consumer="PathologyAPIConsumer", provider="PathologyAPIProvider")

        # Define the expected interaction
        (
            pact.upon_receiving("a request for the status endpoint")
            .with_request(method="GET", path="/_status")
            .will_respond_with(status=200)
            .with_body(
                {"status": status_matcher},
                content_type="application/json",
            )
        )

        # Start the mock server and execute the test
        with pact.serve() as server:
            # Make the actual request to the mock provider
            response = requests.get(f"{server.url}/_status", timeout=10)
            data = response.json()

            # Verify the response matches expectations
            assert response.status_code == 200
            assert data["status"] in {"pass", "ok"}
            assert response.headers["Content-Type"] == "application/json"

        # Write the pact file after the test
        pact.write_file("tests/contract/pacts")

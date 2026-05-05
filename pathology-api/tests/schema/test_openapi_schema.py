"""Schemathesis-based API schema validation tests.

This test suite uses property-based testing to automatically generate test cases
from the OpenAPI specification and validate the API implementation.
"""

from pathlib import Path

import yaml
from hypothesis import HealthCheck, settings
from schemathesis.generation.case import Case
from schemathesis.openapi import from_dict

from tests.conftest import Client

# Load the OpenAPI schema from the local file
schema_path = Path(__file__).parent.parent.parent / "openapi.yaml"
with open(schema_path) as f:
    schema_dict = yaml.safe_load(f)
schema = from_dict(schema_dict)


@schema.parametrize()
# Allowing client even though function scoped. Same auth can be safely
# used for all schema testing.
@settings(suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_api_schema_compliance(case: Case, base_url: str, client: Client) -> None:
    """Test API endpoints against the OpenAPI schema.

    Schemathesis automatically generates test cases with:
    - Valid inputs
    - Edge cases
    - Invalid inputs
    - Boundary values

    This test verifies that the API:
    - Returns responses matching the schema
    - Handles edge cases correctly
    - Validates inputs properly
    - Returns appropriate status codes
    """
    # Call the API and validate the response against the schema
    case.call_and_validate(base_url=base_url, timeout=30, headers=client.auth_headers)

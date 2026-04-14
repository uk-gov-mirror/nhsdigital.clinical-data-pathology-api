"""Step definitions for pathology API bundle endpoint feature."""

import json
from collections.abc import Callable
from typing import Any

import requests
from pathology_api.fhir.r4.resources import (
    Bundle,
    BundleType,
)
from pytest_bdd import given, parsers, then, when

from tests.acceptance.conftest import ResponseContext, TestContext
from tests.conftest import Client

BUNDLE_ENDPOINT = "FHIR/R4/Bundle"


@given("the API is running")
def step_api_is_running(client: Client) -> None:
    """Verify the API test client is available.

    Args:
        client: Test client from conftest.py
    """
    response = client.send_without_payload(path="_status", request_method="GET")

    assert response.status_code == 200
    assert response.json()["checks"]["healthcheck"]["responseCode"] == 200


@when("I send a valid Bundle to the Pathology API")
def step_send_valid_bundle(
    client: Client,
    response_context: ResponseContext,
    test_context: TestContext,
    build_full_test_result: Callable[[str, str], str],
) -> None:
    """
    Send a valid Bundle to the API.

    Args:
        client: Test client
        response_context: Context to store the response
        test_context: Context to store test data
        build_full_test_result: Function to build a full test result
    """

    test_result = build_full_test_result("nhs_number_1", "ods_code")
    response_context.response = client.send(
        path=BUNDLE_ENDPOINT,
        request_method="POST",
        data=test_result,
    )

    test_context.sent_request = test_result


@when("I send an invalid Bundle to the Pathology API")
def step_send_invalid_bundle(client: Client, response_context: ResponseContext) -> None:
    """
    Send an invalid request to the API.

    Args:
        client: Test client
        response_context: Context to store the response
    """
    bundle = Bundle.empty(bundle_type="document").model_dump_json(
        by_alias=True, exclude_none=True
    )

    response_context.response = client.send(
        path=BUNDLE_ENDPOINT, request_method="POST", data=bundle
    )


@when("I send a Bundle with missing Composition to the Pathology API")
def step_send_bundle_without_composition(
    client: Client, response_context: ResponseContext
) -> None:
    bundle = Bundle.create(
        type="document",
        entry=[],  # Missing required Composition
    )

    response_context.response = client.send(
        path=BUNDLE_ENDPOINT,
        request_method="POST",
        data=bundle.model_dump_json(by_alias=True, exclude_none=True),
    )


@when(parsers.cfparse('I send a Bundle with type "{bundle_type}" to the Pathology API'))
def step_send_bundle_wrong_type(
    client: Client,
    response_context: ResponseContext,
    bundle_type: str,
) -> None:
    bundle = Bundle.create(
        type=bundle_type,
        entry=[],
    )

    response_context.response = client.send(
        path=BUNDLE_ENDPOINT,
        request_method="POST",
        data=bundle.model_dump_json(by_alias=True, exclude_none=True),
    )


# fmt: off
@then(parsers.cfparse("the response status code should be {expected_status:d}",extra_types={"expected_status": int})) # noqa: E501 - BDD steps must be declared on a singular line.
# fmt: on
def step_check_status_code(
    response_context: ResponseContext, expected_status: int
) -> None:
    """Verify the response status code matches expected value.

    Args:
        response_context: Context containing the response
        expected_status: Expected HTTP status code
    """
    response = _validate_response_set(response_context)

    assert response.status_code == expected_status, (
        f"Expected status {expected_status}, "
        f"got {response.status_code}"
    )

@then("the response should include the created test result")
def step_check_response_includes_created_result(
    response_context: ResponseContext, test_context: TestContext
) -> None:
    """Verify the response includes the created test result.

    Args:
        response_context: Context containing the response
        test_context: Context containing the sent request data
    """
    response = _validate_response_set(response_context)

    assert test_context.sent_request is not None, "Sent request has not been set."

    expected_data = json.loads(test_context.sent_request)
    response_data = response.json()

    print(f"Expected data: {expected_data}")
    print(f"Response data: {response_data}")

    _assert_content(expected_data, response_data)

    assert response_data.get("id") is not None
    assert response_data.get("meta", {}).get("lastUpdated") is not None

@then(parsers.cfparse('the response should contain "{expected_text}"'))
def step_check_response_contains(
    response_context: ResponseContext, expected_text: str
) -> None:
    """Verify the response contains the expected text.

    Args:
        response_context: Context containing the response
        expected_text: Text that should be in the response
    """
    response = _validate_response_set(response_context)

    assert expected_text in response.text, (
        f"Expected '{expected_text}' in response, got: {response.text}"
    )

@then(parsers.cfparse('the response should contain a valid "{expected_type}" Bundle'))
def step_check_response_contains_valid_bundle(
    response_context: ResponseContext,
    expected_type: BundleType
) -> None:
    """Verify the response contains a valid FHIR Bundle.

    Args:
        response_context: Context containing the response
        expected_type: Expected Bundle type
    """
    response = _validate_response_set(response_context)

    response_data = response.json()
    bundle = Bundle.model_validate(response_data, by_alias=True)

    assert bundle.bundle_type == expected_type, (
        f"Expected bundle type '{expected_type}', got: '{bundle.bundle_type}'"
    )

    assert bundle.id is not None, "Bundle ID is missing."

def _validate_response_set(response_context: ResponseContext) -> requests.Response:
    assert response_context.response is not None, "Response has not been set."
    return response_context.response

def _assert_content(expected: Any, actual: Any) -> None:
    if isinstance(expected, dict):
        for k, v in expected.items():
            _assert_content(v, actual.get(k))
    elif isinstance(expected, list):
        for i, item in enumerate(expected):
            _assert_content(item, actual[i])
    else:
        assert expected == actual, f"Expected {expected}, got {actual}"

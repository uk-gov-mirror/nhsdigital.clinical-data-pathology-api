"""Pytest configuration and shared fixtures for pathology API tests."""

import os
import tempfile
from collections.abc import Generator
from datetime import timedelta
from typing import Any, Literal, Protocol, cast

import pytest
import requests
from dotenv import load_dotenv

from .mock_client import CertificateDetails, MNSMockClient, PDMMockClient

load_dotenv()

type _RequestMethod = Literal["GET", "POST"]


class Client(Protocol):
    """Protocol defining the interface for HTTP clients."""

    def send(
        self,
        data: str,
        path: str,
        request_method: _RequestMethod,
        headers: dict[str, str] | None = None,
    ) -> requests.Response:
        """
        Send a request to the APIs with some given parameters.
        Args:
            data: The data to send in the request payload
            path: The path to send the request to
            request_method: The HTTP method to use for the request
        Returns:
            Response object from the request
        """
        ...

    def send_without_payload(
        self,
        path: str,
        request_method: _RequestMethod,
        headers: dict[str, str] | None = None,
    ) -> requests.Response:
        """
        Send a request to the APIs without a payload.
        Args:
            path: The path to send the request to
            request_method: The HTTP method to use for the request
        Returns:
            Response object from the request
        """
        ...


class LocalClient:
    """HTTP client that sends requests to the Lambda via the RIE (no auth headers)."""

    def __init__(
        self,
        lambda_url: str,
        headers: dict[str, str] | None = None,
        timeout: timedelta = timedelta(seconds=1),
    ):
        self._lambda_url = lambda_url
        self._default_headers = {"Content-Type": "application/fhir+json"} | (
            headers or {}
        )
        self._timeout = timeout.total_seconds()

    def send(
        self,
        data: str,
        path: str,
        request_method: _RequestMethod,
        headers: dict[str, str] | None = None,
    ) -> requests.Response:

        return self._send(
            data=data,
            path=path,
            include_payload=True,
            request_method=request_method,
            headers=headers,
        )

    def send_without_payload(
        self,
        path: str,
        request_method: _RequestMethod,
        headers: dict[str, str] | None = None,
    ) -> requests.Response:

        return self._send(
            data=None,
            path=path,
            include_payload=False,
            request_method=request_method,
            headers=headers,
        )

    def _send(
        self,
        data: str | None,
        path: str,
        include_payload: bool,
        request_method: _RequestMethod,
        headers: dict[str, str] | None = None,
    ) -> requests.Response:
        url = f"{self._lambda_url}/{path}"
        merged_headers = self._default_headers | (headers or {})
        match request_method:
            case "POST":
                return requests.post(
                    url,
                    data=data if include_payload else None,
                    timeout=self._timeout,
                    headers=merged_headers,
                )
            case "GET":
                return requests.get(
                    url,
                    data=data if include_payload else None,
                    timeout=self._timeout,
                    headers=merged_headers,
                )


class RemoteClient:
    """HTTP client for remote testing.

    Sends requests to the deployed APIM proxy URL with authentication headers.
    Unlike LocalClient, all requests include auth headers (from pytest-nhsd-apim)
    and a Content-Type of application/fhir+json by default.

    Args:
        api_url: The APIM proxy URL (e.g. https://internal-dev.api.service.nhs.uk/...-pr-123)
        auth_headers: Auth headers obtained from the pytest-nhsd-apim plugin.
        timeout: Request timeout (default 5s, longer than local due to proxy latency).

    For more details about the pytest-nhsd-apim plugin see:
        https://nhsd-confluence.digital.nhs.uk/x/VC-BGw
    """

    def __init__(
        self,
        api_url: str,
        auth_headers: dict[str, str],
        timeout: timedelta = timedelta(seconds=20),
    ):
        self._api_url = api_url
        self._default_headers = auth_headers | {"Content-Type": "application/fhir+json"}
        self._timeout = timeout.total_seconds()

    def send(
        self,
        data: str,
        path: str,
        request_method: _RequestMethod,
        headers: dict[str, str] | None = None,
    ) -> requests.Response:

        return self._send(
            data=data,
            path=path,
            include_payload=True,
            request_method=request_method,
            headers=headers,
        )

    def send_without_payload(
        self,
        path: str,
        request_method: _RequestMethod,
        headers: dict[str, str] | None = None,
    ) -> requests.Response:

        return self._send(
            data=None,
            path=path,
            include_payload=False,
            request_method=request_method,
            headers=headers,
        )

    def _send(
        self,
        data: str | None,
        path: str,
        include_payload: bool,
        request_method: _RequestMethod,
        headers: dict[str, str] | None = None,
    ) -> requests.Response:
        url = f"{self._api_url}/{path}"
        merged_headers = self._default_headers | (headers or {})
        match request_method:
            case "POST":
                return requests.post(
                    url,
                    data=data if include_payload else None,
                    headers=merged_headers,
                    timeout=self._timeout,
                )
            case "GET":
                return requests.get(
                    url,
                    data=data if include_payload else None,
                    headers=merged_headers,
                    timeout=self._timeout,
                )


@pytest.fixture(scope="module")
def base_url() -> str:
    """Retrieves the base URL of the currently deployed application."""
    return _fetch_env_variable("BASE_URL", str)


@pytest.fixture
def hostname() -> str:
    """Retrieves the hostname of the currently deployed application."""
    return _fetch_env_variable("HOST", str)


@pytest.fixture
def get_headers(request: pytest.FixtureRequest) -> Any:
    """Return merged auth headers for remote tests, or None for local.

    Remote headers combine nhsd_apim_auth_headers (APIM proxy auth) with
    status_endpoint_auth_headers (which includes the api key for the _status endpoint).
    Used by the provider contract verifier to authenticate against the APIM proxy.
    """

    env = request.config.getoption("--env")
    if env == "remote":
        merged_auth_headers = request.getfixturevalue(
            "nhsd_apim_auth_headers"
        ) | request.getfixturevalue("status_endpoint_auth_headers")
        return merged_auth_headers
    return {}


@pytest.fixture
def client(request: pytest.FixtureRequest, base_url: str) -> Client:
    """Create the appropriate HTTP client based on the --env option."""

    env = request.config.getoption("--env")

    if env == "local":
        return LocalClient(lambda_url=base_url)
    elif env == "remote":
        return _create_remote_client(request)
    else:
        raise ValueError(f"Unknown env: {env}")


@pytest.fixture(scope="module")
def client_cert() -> Generator[CertificateDetails | None, None, None]:
    client_cert = _fetch_env_variable("CLIENT_CERT", str)
    client_key = _fetch_env_variable("CLIENT_KEY", str)

    if client_cert and client_key:
        with (
            tempfile.NamedTemporaryFile(delete=True) as cert_file,
            tempfile.NamedTemporaryFile(delete=True) as key_file,
        ):
            cert_file.write(client_cert.encode())
            cert_file.flush()
            key_file.write(client_key.encode())
            key_file.flush()
            yield {
                "cert_path": cert_file.name,
                "key_path": key_file.name,
            }
    else:
        yield None


@pytest.fixture(scope="module")
def pdm_mock_document_url() -> str:
    return _fetch_env_variable("PDM_MOCK_DOCUMENT_URL", str)


@pytest.fixture(scope="module")
def mns_mock_events_url() -> str:
    return _fetch_env_variable("MNS_MOCK_EVENTS_URL", str)


@pytest.fixture(scope="module")
def pdm_mock_client(
    client_cert: CertificateDetails | None, pdm_mock_document_url: str
) -> PDMMockClient:
    return PDMMockClient(
        document_url=pdm_mock_document_url,
        timeout=timedelta(seconds=5),
        client_cert=client_cert,
    )


@pytest.fixture(scope="module")
def mns_mock_client(
    client_cert: CertificateDetails | None, mns_mock_events_url: str
) -> MNSMockClient:
    return MNSMockClient(
        events_url=mns_mock_events_url,
        timeout=timedelta(seconds=5),
        client_cert=client_cert,
    )


def _create_remote_client(request: pytest.FixtureRequest) -> RemoteClient:
    """Create a RemoteClient with auth headers chosen by test markers.

    The APIM proxy requires different auth headers depending on the endpoint:
        - Default: nhsd_apim_auth_headers (OAuth/app-restricted token)
        - @status_auth_headers: status_endpoint_auth_headers only (api-key)
        - @status_merged_auth_headers: both sets merged (needed when a test
        hits both _status and a protected endpoint in the same scenario)
    """
    proxy_url = request.getfixturevalue("nhsd_apim_proxy_url")
    default_auth_headers = request.getfixturevalue("nhsd_apim_auth_headers")

    has_status_marker = request.node.get_closest_marker("status_auth_headers")
    has_merged_marker = request.node.get_closest_marker("status_merged_auth_headers")

    if has_merged_marker:
        status_headers = request.getfixturevalue("status_endpoint_auth_headers")
        auth_headers = default_auth_headers | status_headers
    elif has_status_marker:
        auth_headers = request.getfixturevalue("status_endpoint_auth_headers")
    else:
        auth_headers = default_auth_headers

    return RemoteClient(
        api_url=proxy_url, auth_headers=auth_headers, timeout=timedelta(seconds=30)
    )


def _fetch_env_variable[T](name: str, _: type[T]) -> T:
    value = os.getenv(name)
    if not value:
        raise ValueError(f"{name} environment variable is not set.")
    return cast("T", value)


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--env",
        action="store",
        default="local",
        help="Environment to run tests against",
    )


def pytest_collection_modifyitems(
    config: pytest.Config, items: list[pytest.Item]
) -> None:
    env = config.getoption("--env")

    if env == "local":
        skip_remote = pytest.mark.skip(reason="Test only runs in remote environment")
        for item in items:
            if item.get_closest_marker("remote_only"):
                item.add_marker(skip_remote)

    if env == "remote":
        for item in items:
            item.add_marker(
                pytest.mark.nhsd_apim_authorization(
                    access="application", level="level3"
                )
            )

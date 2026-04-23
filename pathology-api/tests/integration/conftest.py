import tempfile
from collections.abc import Callable, Generator
from datetime import timedelta

import pytest

from tests.mock_client import CertificateDetails, MNSMockClient, PDMMockClient


@pytest.fixture(scope="module")
def client_cert(
    fetch_env_variable: Callable[[str, type[str]], str],
) -> Generator[CertificateDetails | None, None, None]:
    client_cert = fetch_env_variable("CLIENT_CERT", str)
    client_key = fetch_env_variable("CLIENT_KEY", str)

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
def pdm_mock_document_url(fetch_env_variable: Callable[[str, type[str]], str]) -> str:
    return fetch_env_variable("PDM_MOCK_DOCUMENT_URL", str)


@pytest.fixture(scope="module")
def mns_mock_events_url(fetch_env_variable: Callable[[str, type[str]], str]) -> str:
    return fetch_env_variable("MNS_MOCK_EVENTS_URL", str)


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

from datetime import timedelta
from typing import Any, TypedDict

import requests


class CertificateDetails(TypedDict):
    cert_path: str
    key_path: str


class PDMMockClient:
    def __init__(
        self, url: str, timeout: timedelta, client_cert: CertificateDetails | None
    ):
        self._url = url
        self._timeout = timeout
        self._client_cert = client_cert

    def retrieve_sent_request(self, request_id: str) -> Any:
        certs = (
            (self._client_cert["cert_path"], self._client_cert["key_path"])
            if self._client_cert
            else None
        )

        response = requests.get(
            self._url + request_id,
            timeout=self._timeout.total_seconds(),
            cert=certs,
        )
        return response.json()

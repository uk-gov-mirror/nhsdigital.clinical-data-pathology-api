from datetime import timedelta
from typing import Any, TypedDict, cast

import requests


class CertificateDetails(TypedDict):
    cert_path: str
    key_path: str


class PDMMockClient:
    def __init__(
        self,
        document_url: str,
        timeout: timedelta,
        client_cert: CertificateDetails | None,
    ):
        self._document_url = document_url
        self._timeout = timeout
        self._client_cert = client_cert

    def retrieve_sent_request(self, request_id: str) -> Any:
        certs = (
            (self._client_cert["cert_path"], self._client_cert["key_path"])
            if self._client_cert
            else None
        )

        response = requests.get(
            self._document_url + "/" + request_id,
            timeout=self._timeout.total_seconds(),
            cert=certs,
        )
        return response.json()


class MNSMockClient:
    def __init__(
        self,
        events_url: str,
        timeout: timedelta,
        client_cert: CertificateDetails | None,
    ):
        self._events_url = events_url
        self._timeout = timeout
        self._client_cert = client_cert

    def retrieve_sent_messages(self, subject: str) -> list[Any]:
        certs = (
            (self._client_cert["cert_path"], self._client_cert["key_path"])
            if self._client_cert
            else None
        )

        response = requests.get(
            self._events_url + "?subject=" + subject,
            timeout=self._timeout.total_seconds(),
            cert=certs,
        )
        return cast("list[Any]", response.json().get("events", []))

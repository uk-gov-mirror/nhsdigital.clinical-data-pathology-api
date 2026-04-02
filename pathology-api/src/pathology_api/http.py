import functools
import tempfile
from collections.abc import Callable
from contextlib import ExitStack
from datetime import timedelta
from typing import Any, Concatenate, TypedDict

import requests
from requests.adapters import HTTPAdapter

from pathology_api.logging import get_logger

_logger = get_logger(__name__)

# Type alias describing the expected signature for a request making a HTTP request.
# Any function that takes a `requests.Session` as its first argument, followed by any
# number of additional arguments, and returns any type of value.
type RequestMethod[**P, S] = Callable[Concatenate[requests.Session, P], S]


class ClientCertificate(TypedDict):
    certificate: str
    key: str


class SessionManager:
    class _Adapter(HTTPAdapter):
        """
        HTTPAdapter to apply default configuration to apply to all created
        `request.Session` objects.
        """

        def __init__(self, timeout: float):
            self._timeout = timeout
            super().__init__()

        def send(
            self,
            request: requests.PreparedRequest,
            *args: Any,
            **kwargs: Any,
        ) -> requests.Response:
            _logger.debug(
                "Applying default timeout of %s seconds to request", self._timeout
            )
            kwargs["timeout"] = self._timeout
            return super().send(request, *args, **kwargs)

    def __init__(
        self,
        client_timeout: timedelta,
        client_certificate: ClientCertificate | None = None,
    ):
        self._client_adapter = self._Adapter(timeout=client_timeout.total_seconds())
        self._client_certificate = client_certificate

    def with_session[**P, S](self, func: RequestMethod[P, S]) -> Callable[P, S]:
        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            with ExitStack() as stack:
                _logger.debug("Creating new session for request")
                session = requests.Session()
                stack.enter_context(session)

                _logger.debug("Mounted default settings to session")
                session.mount("https://", self._client_adapter)

                if self._client_certificate is not None:
                    _logger.debug("Configuring session with client certificate...")

                    # File added to Exit stack and will be automatically cleaned up with
                    # the stack.
                    cert_file = tempfile.NamedTemporaryFile(  # noqa: SIM115
                        delete=True
                    )
                    stack.enter_context(cert_file)

                    # File added to Exit stack and will be automatically cleaned up with
                    # the stack.
                    key_file = tempfile.NamedTemporaryFile(  # noqa: SIM115
                        delete=True
                    )
                    stack.enter_context(key_file)

                    cert_file.write(self._client_certificate["certificate"].encode())
                    cert_file.flush()
                    key_file.write(self._client_certificate["key"].encode())
                    key_file.flush()

                    session.cert = (cert_file.name, key_file.name)
                    _logger.debug("Client certificate added.")

                return func(session, *args, **kwargs)

        return wrapper

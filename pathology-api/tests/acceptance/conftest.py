from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
import requests


class ResponseContext:
    _response: requests.Response | None = None

    @property
    def response(self) -> requests.Response | None:
        return self._response

    @response.setter
    def response(self, value: requests.Response) -> None:
        if self._response:
            raise RuntimeError("Response has already been set.")
        self._response = value


@pytest.fixture
def response_context() -> ResponseContext:
    return ResponseContext()


class TestContext:
    _sent_request: str | None = None

    @property
    def sent_request(self) -> str | None:
        return self._sent_request

    @sent_request.setter
    def sent_request(self, value: str) -> None:
        if self._sent_request:
            raise RuntimeError("Request has already been sent.")
        self._sent_request = value


@pytest.fixture
def test_context() -> TestContext:
    return TestContext()


@pytest.fixture
def build_full_test_result() -> Callable[[str, str], Any]:
    def _build_full_test_result(subject: str, requesting_ods_code: str) -> str:
        with open(Path(__file__).parent / "full_test_result_template.json") as template:
            return (
                template.read()
                .replace("$subject", subject)
                .replace("$requesting_ods_code", requesting_ods_code)
            )

    return _build_full_test_result

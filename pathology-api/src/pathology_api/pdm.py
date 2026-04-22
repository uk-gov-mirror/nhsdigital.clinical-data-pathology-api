from typing import Any, NamedTuple
from uuid import uuid4

import requests

from pathology_api import environment
from pathology_api.fhir.r4.resources import Bundle
from pathology_api.logging import get_logger

_logger = get_logger(__name__)


class PdmException(Exception):
    """
    Custom exception for validation errors in the PDM Client.
    Note that any message here will be provided in the error response returned to users.
    """

    def __init__(self, message: str):
        self.message = message
        super().__init__(message)


class PdmResponse(NamedTuple):
    bundle: Bundle
    etag: str


@environment.apim_authenticator().auth
def _make_post_request(session: requests.Session, document: Bundle) -> Any:
    response = session.post(
        url=environment.values()["pdm_url"],
        data=document.model_dump_json(by_alias=True, exclude_none=True),
        headers={"Content-Type": "application/fhir+json", "X-Request-ID": str(uuid4())},
    )

    return response


def post_document(document: Bundle) -> PdmResponse:

    response = _make_post_request(document)

    _logger.debug(
        "Result of post request. status_code=%s data=%s",
        response.status_code,
        response.text,
    )

    if response.status_code == 201:
        returned_document = response.json()
        etag = response.headers.get("etag")
        pdm_response = PdmResponse(
            Bundle.model_validate(returned_document, by_alias=True), etag
        )
        return pdm_response
    elif response.status_code == 401:
        raise PdmException("An unexpected internal server error has occured")
    # all other responses including 5xx and 4xx return same format for now
    else:
        pdm_error = response.text
        raise PdmException(f"Failed to store document: {pdm_error}")

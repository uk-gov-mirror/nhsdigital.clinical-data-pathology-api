import uuid
from datetime import datetime, timezone
from json import JSONDecodeError
from typing import Any
from urllib.parse import urljoin

import requests

from pathology_api import environment
from pathology_api.logging import get_logger

_logger = get_logger(__name__)


class MnsException(Exception):
    """
    Standard exception indicating that an issue occurred whilst interacting with MNS.
    """


@environment.apim_authenticator().auth
def create_event(
    session: requests.Session,
    requesting_org: str,
    nhs_number: str,
    bundle_id: str,
) -> None:
    _logger.debug(
        "Publishing MNS event. requesting_org=%s bundle_id=%s",
        requesting_org,
        bundle_id,
    )

    event: dict[str, Any] = {
        "specversion": "1.0",
        "id": str(uuid.uuid4()),
        "source": "uk.nhs.pathology-laboratory-reporting",
        "type": "pathology-laboratory-reporting-test-result-stored-1",
        "time": datetime.now(timezone.utc).isoformat(),
        "dataref": urljoin(environment.values()["pdm_url"] + "/", bundle_id),
        "subject": nhs_number,
        "filtering": {"requestingOrganisationODS": requesting_org},
    }

    _logger.debug(
        "MNS event payload: %s",
        # Mask subject value in logs
        {k: "*" * len(v) if k == "subject" else v for k, v in event.items()},
    )

    try:
        response = session.post(
            environment.values()["mns_url"],
            json=event,
            headers={"Content-Type": "application/cloudevents+json"},
        )
    except requests.RequestException as e:
        raise MnsException("Failed to send request to MNS") from e

    if not response.ok:
        raise MnsException(
            f"Failed to create MNS event. status_code={response.status_code} "
            f"response={response.text}"
        )

    try:
        response_data = response.json()
    except JSONDecodeError as e:
        raise MnsException(
            f"Failed to decode MNS response as JSON. response={response.text}"
        ) from e

    if "id" not in response_data:
        raise MnsException(
            "MNS response does not contain a valid 'id' field. "
            f"response={response_data}"
        )

    _logger.debug("MNS event published. event_id=%s", response_data["id"])

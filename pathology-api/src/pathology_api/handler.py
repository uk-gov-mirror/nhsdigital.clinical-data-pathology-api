import uuid
from collections.abc import Callable

import requests
from aws_lambda_powertools.utilities import parameters

from pathology_api.apim import ApimAuthenticator
from pathology_api.config import (
    Duration,
    get_environment_variable,
    get_optional_environment_variable,
)
from pathology_api.exception import ValidationError
from pathology_api.fhir.r4.elements import Meta
from pathology_api.fhir.r4.resources import Bundle, Composition
from pathology_api.http import ClientCertificate, SessionManager
from pathology_api.logging import get_logger

_logger = get_logger(__name__)

CLIENT_TIMEOUT = get_environment_variable("CLIENT_TIMEOUT", Duration)

CLIENT_CERTIFICATE_NAME = get_optional_environment_variable("APIM_MTLS_CERT_NAME", str)
CLIENT_KEY_NAME = get_optional_environment_variable("APIM_MTLS_KEY_NAME", str)

APIM_TOKEN_URL = get_environment_variable("APIM_TOKEN_URL", str)
APIM_PRIVATE_KEY_NAME = get_environment_variable("APIM_PRIVATE_KEY_NAME", str)
APIM_API_KEY_NAME = get_environment_variable("APIM_API_KEY_NAME", str)
APIM_TOKEN_EXPIRY_THRESHOLD = get_environment_variable(
    "APIM_TOKEN_EXPIRY_THRESHOLD", Duration
)
APIM_KEY_ID = get_environment_variable("APIM_KEY_ID", str)

PDM_URL = get_environment_variable("PDM_BUNDLE_URL", str)


def _create_client_certificate(
    certificate_name: str, key_name: str
) -> ClientCertificate:
    certificate = parameters.get_secret(certificate_name)
    key = parameters.get_secret(key_name)

    return {
        "certificate": certificate,
        "key": key,
    }


if CLIENT_CERTIFICATE_NAME and CLIENT_KEY_NAME:
    CLIENT_CERTIFICATE: ClientCertificate | None = _create_client_certificate(
        CLIENT_CERTIFICATE_NAME, CLIENT_KEY_NAME
    )
else:
    CLIENT_CERTIFICATE = None


session_manager = SessionManager(
    client_timeout=CLIENT_TIMEOUT.timedelta,
    client_certificate=CLIENT_CERTIFICATE,
)

apim_authenticator = ApimAuthenticator(
    private_key=parameters.get_secret(APIM_PRIVATE_KEY_NAME),
    key_id=APIM_KEY_ID,
    api_key=parameters.get_secret(APIM_API_KEY_NAME),
    token_endpoint=APIM_TOKEN_URL,
    token_validity_threshold=APIM_TOKEN_EXPIRY_THRESHOLD.timedelta,
    session_manager=session_manager,
)


def _validate_composition(bundle: Bundle) -> None:
    compositions = bundle.find_resources(t=Composition)
    if len(compositions) != 1:
        raise ValidationError("Document must include a single Composition resource")

    subject = compositions[0].subject
    if subject is None:
        raise ValidationError("Composition does not define a valid subject identifier")


def _validate_bundle(bundle: Bundle) -> None:
    if bundle.id is not None:
        raise ValidationError("Bundles cannot be defined with an existing ID")

    if bundle.bundle_type != "document":
        raise ValidationError("Resource must be a bundle of type 'document'")


type ValidationFunction = Callable[[Bundle], None]
_validation_functions: list[ValidationFunction] = [
    _validate_composition,
    _validate_bundle,
]


def handle_request(bundle: Bundle) -> Bundle:
    for validate_function in _validation_functions:
        validate_function(bundle)

    _logger.debug("Bundle entries: %s", bundle.entries)
    return_bundle = Bundle.create(
        id=str(uuid.uuid4()),
        meta=Meta.with_last_updated(),
        identifier=bundle.identifier,
        type=bundle.bundle_type,
        entry=bundle.entries,
    )
    _logger.debug("Return bundle: %s", return_bundle)

    auth_response = _send_request(PDM_URL)
    _logger.debug(
        "Result of authenticated request. status_code=%s data=%s",
        auth_response.status_code,
        auth_response.text,
    )

    return return_bundle


@apim_authenticator.auth
def _send_request(session: requests.Session, url: str) -> requests.Response:
    return session.post(url)

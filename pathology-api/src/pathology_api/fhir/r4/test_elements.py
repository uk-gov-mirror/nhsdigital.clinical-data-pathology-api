import datetime
import uuid

import pydantic
import pytest
from pydantic import BaseModel

from pathology_api.exception import ValidationError

from .elements import (
    Extension,
    Identifier,
    LogicalReference,
    Meta,
    OrganizationIdentifier,
    PatientIdentifier,
    ReferenceExtension,
    UnknownIdentifier,
    UUIDIdentifier,
)


class TestMeta:
    def test_create(self) -> None:
        meta = Meta(
            version_id="1",
            last_updated=datetime.datetime.fromisoformat("2023-10-01T12:00:00Z"),
        )
        assert meta.version_id == "1"
        assert meta.last_updated == datetime.datetime.fromisoformat(
            "2023-10-01T12:00:00Z"
        )

    def test_create_without_last_updated(self) -> None:
        meta = Meta(version_id="2")

        assert meta.version_id == "2"
        assert meta.last_updated is None

    def test_create_without_version(self) -> None:
        meta = Meta(
            last_updated=datetime.datetime.fromisoformat("2023-10-01T12:00:00Z")
        )

        assert meta.version_id is None
        assert meta.last_updated == datetime.datetime.fromisoformat(
            "2023-10-01T12:00:00Z"
        )

    def test_with_last_updated(self) -> None:
        last_updated = datetime.datetime.fromisoformat("2023-10-01T12:00:00Z")
        meta = Meta.with_last_updated(last_updated)

        assert meta.last_updated == last_updated
        assert meta.version_id is None

    def test_with_last_updated_defaults_to_now(self) -> None:
        before_create = datetime.datetime.now(tz=datetime.timezone.utc)
        meta = Meta.with_last_updated(None)
        after_create = datetime.datetime.now(tz=datetime.timezone.utc)

        assert meta.last_updated is not None
        assert meta.version_id is None

        assert before_create <= meta.last_updated
        assert meta.last_updated <= after_create


class TestUUIDIdentifier:
    def test_create_with_value(self) -> None:
        expected_uuid = uuid.UUID("12345678-1234-5678-1234-567812345678")
        identifier = UUIDIdentifier.create_with_uuid(expected_uuid)

        assert identifier.system == "https://tools.ietf.org/html/rfc4122"
        assert identifier.value == str(expected_uuid)

    def test_create_without_value(self) -> None:
        identifier = UUIDIdentifier.create_with_uuid()

        assert identifier.system == "https://tools.ietf.org/html/rfc4122"
        # Validates that value is a valid UUID v4
        parsed_uuid = uuid.UUID(identifier.value)
        assert parsed_uuid.version == 4


class _TestIdentifierContainer(BaseModel):
    identifier: "IdentifierStub"

    class IdentifierStub(Identifier, expected_system="expected-system"):
        pass


class _TestIdentifierListContainer(BaseModel):
    identifier: list[Identifier]


class TestIdentifier:
    def test_invalid_system(self) -> None:
        with pytest.raises(
            ValidationError,
            match="Identifier system 'invalid-system' does not match expected "
            "system 'expected-system'.",
        ):
            _TestIdentifierContainer.model_validate(
                {"identifier": {"system": "invalid-system", "value": "some-value"}}
            )

    def test_without_value(self) -> None:
        with pytest.raises(
            pydantic.ValidationError,
            match="1 validation error for _TestIdentifierContainer"
            "\nidentifier.value\n  "
            "Field required [type=missing, input_value={'system': 'expected-system'},"
            " input_type=dict]*",
        ):
            _TestIdentifierContainer.model_validate(
                {"identifier": {"system": "expected-system"}}
            )

    def test_unknown_system(self) -> None:

        result = _TestIdentifierListContainer.model_validate(
            {"identifier": [{"system": "unknown-system", "value": "some-value"}]}
        )

        assert isinstance(result.identifier[0], UnknownIdentifier)

    def test_deserialises_by_system(self) -> None:
        result = _TestIdentifierListContainer.model_validate(
            {
                "identifier": [
                    {
                        "system": "unknown-system",
                        "value": "some-value",
                    },
                    {
                        "system": "https://fhir.nhs.uk/Id/nhs-number",
                        "value": "second-value",
                    },
                ]
            }
        )

        assert isinstance(result.identifier[0], UnknownIdentifier)
        assert isinstance(result.identifier[1], PatientIdentifier)


class TestUnknownIdentifier:
    def test_does_not_validate_system(self) -> None:
        result = UnknownIdentifier.model_validate(
            {"system": "any-system", "value": "some-value"}
        )

        assert result.system == "any-system"
        assert result.value == "some-value"


class TestPatientIdentifier:
    def test_create_from_nhs_number(self) -> None:
        """Test creating a PatientIdentifier from an NHS number."""
        nhs_number = "1234567890"
        identifier = PatientIdentifier.from_nhs_number(nhs_number)

        assert identifier.system == "https://fhir.nhs.uk/Id/nhs-number"
        assert identifier.value == nhs_number


class TestOrganizationIdentifier:
    def test_create_from_ods_code(self) -> None:
        expected_ods_code = "ods_code"
        identifier = OrganizationIdentifier.from_ods_code(expected_ods_code)

        assert identifier.system == "https://fhir.nhs.uk/Id/ods-organization-code"
        assert identifier.value == expected_ods_code


class TestLogicalReference:
    class _TestContainer(BaseModel):
        reference: LogicalReference[PatientIdentifier]

    def test_create_with_patient_identifier(self) -> None:
        nhs_number = "nhs_number"
        patient_id = PatientIdentifier.from_nhs_number(nhs_number)

        reference = LogicalReference(identifier=patient_id)

        assert reference.identifier == patient_id
        assert reference.identifier.system == "https://fhir.nhs.uk/Id/nhs-number"
        assert reference.identifier.value == nhs_number

    def test_serialization(self) -> None:
        nhs_number = "nhs_number"
        patient_id = PatientIdentifier.from_nhs_number(nhs_number)
        reference = LogicalReference(identifier=patient_id)

        container = self._TestContainer(reference=reference)
        serialized = container.model_dump(by_alias=True)

        expected = {
            "reference": {
                "identifier": {
                    "system": "https://fhir.nhs.uk/Id/nhs-number",
                    "value": "nhs_number",
                }
            }
        }
        assert serialized == expected

    def test_deserialization(self) -> None:
        data = {
            "reference": {
                "identifier": {
                    "system": "https://fhir.nhs.uk/Id/nhs-number",
                    "value": "nhs_number",
                }
            }
        }

        container = self._TestContainer.model_validate(data)

        created_identifier = container.reference.identifier
        assert isinstance(created_identifier, PatientIdentifier)
        assert created_identifier.system == "https://fhir.nhs.uk/Id/nhs-number"
        assert created_identifier.value == "nhs_number"


class TestExtension:
    def test_deserialises_on_type(self) -> None:
        result = Extension.model_validate(
            {"url": "test-extension", "valueReference": {"reference": "test-reference"}}
        )

        assert isinstance(result, ReferenceExtension)

        unknown_type = Extension.model_validate(
            {"url": "unknown-extension", "valueString": "test-value"}
        )

        assert isinstance(unknown_type, Extension)
        assert not isinstance(unknown_type, ReferenceExtension)

    def test_deserialises_wrong_casing(self) -> None:
        result = Extension.model_validate(
            {"url": "test-extension", "valuereference": {"reference": "test-reference"}}
        )

        assert isinstance(result, Extension)
        assert not isinstance(result, ReferenceExtension)

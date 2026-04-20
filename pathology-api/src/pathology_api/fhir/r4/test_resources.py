import json
import uuid
from datetime import datetime, timezone
from typing import Any

import pydantic
import pytest
from pydantic import BaseModel

from pathology_api.exception import ValidationError

from .elements import (
    Extension,
    LiteralReference,
    LogicalReference,
    PatientIdentifier,
    ReferenceExtension,
)
from .resources import Bundle, Composition, OperationOutcome, Patient, Resource


class TestResource:
    class _TestContainer(BaseModel):
        resource: Resource

    def test_resource_deserialisation(self) -> None:
        expected_system = "https://fhir.nhs.uk/Id/nhs-number"
        expected_nhs_number = "nhs_number"
        example_json = json.dumps(
            {
                "resource": {
                    "resourceType": "Composition",
                    "subject": {
                        "identifier": {
                            "system": expected_system,
                            "value": expected_nhs_number,
                        }
                    },
                }
            }
        )

        created_object = self._TestContainer.model_validate_json(example_json)
        assert isinstance(created_object.resource, Composition)

        created_composition = created_object.resource
        assert created_composition.subject is not None
        assert created_composition.subject.identifier.system == expected_system
        assert created_composition.subject.identifier.value == expected_nhs_number

    def test_resource_deserialisation_unknown_resource(self) -> None:
        expected_resource_type = "UnknownResourceType"
        example_json = json.dumps(
            {
                "resource": {
                    "resourceType": expected_resource_type,
                }
            }
        )

        with pytest.raises(
            ValidationError,
            match=f"Unsupported resourceType: {expected_resource_type}",
        ):
            self._TestContainer.model_validate_json(example_json)

    @pytest.mark.parametrize(
        "value",
        [
            pytest.param({"resource": {}}, id="No resourceType key"),
            pytest.param(
                {"resource": {"resourceType": None}},
                id="resourceType is defined as None",
            ),
        ],
    )
    def test_resource_deserialisation_without_resource_type(
        self, value: dict[str, Any]
    ) -> None:
        example_json = json.dumps(value)

        with pytest.raises(
            ValidationError,
            match="resourceType must be provided for each Resource.",
        ):
            self._TestContainer.model_validate_json(example_json)

    @pytest.mark.parametrize(
        ("json", "expected_error_message", "expected_error_type"),
        [
            pytest.param(
                json.dumps({"resourceType": "invalid", "type": "document"}),
                "Provided resourceType 'invalid' does not match required "
                "resourceType 'Bundle'.",
                ValidationError,
                id="Invalid resource type",
            ),
            pytest.param(
                json.dumps({"resourceType": None, "type": "document"}),
                "1 validation error for Bundle\nresourceType\n  "
                "Input should be a valid string",
                pydantic.ValidationError,
                id="Input should be a valid string",
            ),
            pytest.param(
                json.dumps({"type": "document"}),
                "1 validation error for Bundle\nresourceType\n  Field required",
                pydantic.ValidationError,
                id="Missing resource type",
            ),
        ],
    )
    def test_deserialise_wrong_resource_type(
        self,
        json: str,
        expected_error_message: str,
        expected_error_type: type[Exception],
    ) -> None:
        with pytest.raises(
            expected_error_type,
            match=expected_error_message,
        ):
            Bundle.model_validate_json(json, strict=True)

    expected_extension = ReferenceExtension(
        valueReference=LiteralReference(reference="expected_reference"),
        url="expected_url",
    )

    @pytest.mark.parametrize(
        ("extensions", "expected_result"),
        [
            pytest.param(
                [
                    expected_extension,
                ],
                expected_extension,
                id="Single extension",
            ),
            pytest.param(
                [
                    expected_extension,
                    ReferenceExtension(
                        valueReference=LiteralReference(reference="second_reference"),
                        url="second_url",
                    ),
                ],
                expected_extension,
                id="Multiple extensions",
            ),
        ],
    )
    def test_find_extension(
        self, extensions: list[Extension], expected_result: Extension
    ) -> None:
        bundle = Bundle.create(type="document", extension=extensions, entry=[])

        assert (
            bundle.find_extension(url="expected_url", required_type=ReferenceExtension)
            == expected_result
        )

        assert (
            bundle.find_extension(url="expected_url", required_type=Extension)
            == expected_result
        )

    def test_find_extension_no_extensions(self) -> None:
        bundle = Bundle.create(type="document", entry=[])

        assert (
            bundle.find_extension(url="expected_url", required_type=Extension) is None
        )

    def test_find_extension_duplicate_url(self) -> None:
        bundle = Bundle.create(
            type="document",
            extension=[
                self.expected_extension,
                self.expected_extension,
            ],
            entry=[],
        )

        with pytest.raises(
            ValidationError,
            match="Multiple extensions provided with same url: expected_url",
        ):
            bundle.find_extension(url="expected_url", required_type=Extension)

    def test_find_extension_wrong_type(self) -> None:
        class _ExtensionStub(Extension, type_name="stub"):
            pass

        bundle = Bundle.create(
            type="document",
            extension=[_ExtensionStub(url="expected_url")],
            entry=[],
        )

        with pytest.raises(
            ValidationError,
            match="Extension with url expected_url is not expected type Reference",
        ):
            bundle.find_extension(url="expected_url", required_type=ReferenceExtension)


class TestBundle:
    def test_create(self) -> None:
        expected_entry = Bundle.Entry(
            fullUrl="full",
            resource=Composition.create(
                subject=LogicalReference(PatientIdentifier.create_with("nhs_number"))
            ),
        )

        bundle = Bundle.create(
            type="document",
            entry=[expected_entry],
        )

        assert bundle.bundle_type == "document"
        assert bundle.entries == [expected_entry]

    def test_create_without_entries(self) -> None:
        bundle = Bundle.empty("document")

        assert bundle.bundle_type == "document"
        assert bundle.entries is None

    expected_composition = Composition.create(
        subject=LogicalReference(identifier=PatientIdentifier.create_with("nhs_number"))
    )

    @pytest.mark.parametrize(
        ("entries", "expected_results"),
        [
            pytest.param(
                [
                    Bundle.Entry(
                        fullUrl="fullUrl",
                        resource=expected_composition,
                    ),
                    Bundle.Entry(
                        fullUrl="fullUrl",
                        resource=expected_composition,
                    ),
                ],
                [expected_composition, expected_composition],
                id="Duplicate resources",
            ),
            pytest.param(
                [
                    Bundle.Entry(
                        fullUrl="fullUrl",
                        resource=expected_composition,
                    ),
                ],
                [expected_composition],
                id="Single resource",
            ),
        ],
    )
    def test_find_resources(
        self, entries: list[Bundle.Entry], expected_results: list[Resource]
    ) -> None:
        bundle = Bundle.create(type="document", entry=entries)

        result = bundle.find_resources(Composition)
        assert result == expected_results

    @pytest.mark.parametrize(
        "bundle",
        [
            pytest.param(Bundle.empty("document"), id="Bundle has no entries at all"),
            pytest.param(
                Bundle.create(type="document", entry=[]),
                id="Bundle has an empty entries list",
            ),
            pytest.param(
                Bundle.create(
                    type="document",
                    entry=[
                        Bundle.Entry(
                            fullUrl="fullUrl",
                            resource=Bundle.empty("document"),
                        ),
                    ],
                ),
                id="different_resource_type",
            ),
        ],
    )
    def test_find_resources_returns_empty_list(self, bundle: Bundle) -> None:
        result = bundle.find_resources(Patient)
        assert result == []

    def test_deserialise_without_type(self) -> None:
        with pytest.raises(
            pydantic.ValidationError,
            match="1 validation error for Bundle\ntype\n  Field required [type=missing,"
            "input_value={'resourceType': 'Bundle'}, input_type=dict]*",
        ):
            Bundle.model_validate_json('{"resourceType": "Bundle"}')

    def test_has_resource(self) -> None:
        expected_resource = Patient.create(
            identifier=PatientIdentifier.create_with("nhs_number")
        )

        bundle = Bundle.create(
            type="document",
            entry=[Bundle.Entry(fullUrl="fullUrl", resource=expected_resource)],
        )

        assert bundle.has_resource(Patient) is True
        assert bundle.has_resource(Resource) is True
        assert bundle.has_resource(Composition) is False

    def test_has_resource_no_resources(self) -> None:
        bundle = Bundle.empty("document")

        assert bundle.has_resource(Resource) is False

    expected_patient = Patient.create(
        identifier=PatientIdentifier.create_with("nhs_number")
    )

    @pytest.mark.parametrize(
        ("bundle", "expected_resource"),
        [
            pytest.param(
                Bundle.create(
                    type="document",
                    entry=[
                        Bundle.Entry(
                            fullUrl="fullUrl",
                            resource=expected_patient,
                        )
                    ],
                ),
                expected_patient,
                id="Bundle with single resource",
            ),
            pytest.param(
                Bundle.create(
                    type="document",
                    entry=[
                        Bundle.Entry(
                            fullUrl="fullUrl",
                            resource=expected_patient,
                        ),
                        Bundle.Entry(
                            fullUrl="secondUrl",
                            resource=Patient.create(
                                identifier=PatientIdentifier.create_with(
                                    "second_nhs_number"
                                )
                            ),
                        ),
                    ],
                ),
                expected_patient,
                id="Bundle with multiple resources",
            ),
        ],
    )
    def test_get_resource(self, bundle: Bundle, expected_resource: Patient) -> None:
        assert bundle.get_resource(url="fullUrl", t=Patient) == expected_resource
        assert bundle.get_resource(url="fullUrl", t=Resource) == expected_resource

    def test_get_resource_no_resources(self) -> None:
        bundle = Bundle.empty("document")

        assert bundle.get_resource(url="fullUrl", t=Resource) is None

    def test_get_resource_wrong_type(self) -> None:
        expected_resource = Patient.create(
            identifier=PatientIdentifier.create_with("nhs_number")
        )

        bundle = Bundle.create(
            type="document",
            entry=[Bundle.Entry(fullUrl="fullUrl", resource=expected_resource)],
        )

        assert bundle.get_resource(url="fullUrl", t=Composition) is None

    def test_get_resource_wrong_url(self) -> None:
        expected_resource = Patient.create(
            identifier=PatientIdentifier.create_with("nhs_number")
        )

        bundle = Bundle.create(
            type="document",
            entry=[Bundle.Entry(fullUrl="fullUrl", resource=expected_resource)],
        )

        assert bundle.get_resource(url="wrongUrl", t=Patient) is None

    def test_get_resource_multiple_resources_same_url(self) -> None:
        expected_resource = Patient.create(
            identifier=PatientIdentifier.create_with("nhs_number")
        )

        bundle = Bundle.create(
            type="document",
            entry=[
                Bundle.Entry(fullUrl="fullUrl", resource=expected_resource),
                Bundle.Entry(fullUrl="fullUrl", resource=expected_resource),
            ],
        )

        with pytest.raises(
            ValidationError,
            match="Multiple resources provided with same fullUrl: fullUrl",
        ):
            bundle.get_resource(url="fullUrl", t=Patient)

    def test_create_with_identifier(self) -> None:
        data: dict[str, Any] = {
            "resourceType": "Bundle",
            "type": "document",
            "identifier": {"system": "urn:ietf:rfc:3986", "value": str(uuid.uuid4())},
        }

        bundle = Bundle.model_validate(data)
        assert bundle.resource_type == "Bundle"
        assert bundle.bundle_type == "document"

        serialised = bundle.model_dump(by_alias=True)
        assert serialised["identifier"] == {
            "system": "urn:ietf:rfc:3986",
            "value": data["identifier"]["value"],
        }

    def test_create_with_unexpected_field(self) -> None:
        data: dict[str, Any] = {
            "resourceType": "Bundle",
            "type": "document",
            "timestamp": datetime.now(tz=timezone.utc).isoformat(),
        }

        bundle = Bundle.model_validate(data)
        assert bundle.resource_type == "Bundle"
        assert bundle.bundle_type == "document"

        serialised = bundle.model_dump(by_alias=True)
        assert serialised["timestamp"] == data["timestamp"]


class TestOperationOutcome:
    def test_create_validation_error(self) -> None:
        expected_diagnostics = "Invalid patient identifier format"

        outcome = OperationOutcome.create_validation_error(expected_diagnostics)

        assert outcome.resource_type == "OperationOutcome"
        assert len(outcome.issue) == 1

        issue = outcome.issue[0]
        assert issue["severity"] == "error"
        assert issue["code"] == "invalid"
        assert issue["diagnostics"] == expected_diagnostics

    @pytest.mark.parametrize(
        ("diagnostics", "expected_diagnostics"),
        [
            pytest.param(
                "Unexpected error",
                "Unexpected error",
                id="with_diagnostics",
            ),
            pytest.param(
                None,
                None,
                id="without_diagnostics",
            ),
        ],
    )
    def test_create_server_error(
        self, diagnostics: str | None, expected_diagnostics: str | None
    ) -> None:
        outcome = OperationOutcome.create_server_error(diagnostics)

        assert outcome.resource_type == "OperationOutcome"
        assert len(outcome.issue) == 1

        issue = outcome.issue[0]
        assert issue["severity"] == "fatal"
        assert issue["code"] == "exception"
        assert issue["diagnostics"] == expected_diagnostics

import datetime
from abc import ABC
from dataclasses import dataclass
from typing import Annotated, Any, ClassVar

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidatorFunctionWrapHandler,
    model_validator,
)

from pathology_api.exception import ValidationError


@dataclass(frozen=True)
class Meta:
    """
    A FHIR R4 Meta element. See https://hl7.org/fhir/R4/datatypes.html#Meta.
    Attributes:
        version_id: The version id of the resource.
        last_updated: The last updated timestamp of the resource.
    """

    last_updated: Annotated[datetime.datetime | None, Field(alias="lastUpdated")] = None
    version_id: Annotated[str | None, Field(alias="versionId")] = None
    profile: list[str] | None = None

    @classmethod
    def with_last_updated(cls, last_updated: datetime.datetime | None = None) -> "Meta":
        """
        Create a Meta instance with the provided last_updated timestamp.
        Args:
            last_updated: The last updated timestamp.
        Returns:
            A Meta instance with the specified last_updated.
        """
        return cls(
            last_updated=last_updated or datetime.datetime.now(tz=datetime.timezone.utc)
        )


class Identifier(ABC, BaseModel):
    """
    A FHIR R4 Identifier element. See https://hl7.org/fhir/R4/datatypes.html#Identifier.
    Attributes:
        system: The namespace for the identifier value.
        value: The value that is unique within the system.
    """

    __system_types: ClassVar[dict[str, type["Identifier"]]] = {}

    _validate_system: ClassVar[bool] = True
    expected_system: ClassVar[str] = "__unknown__"

    system: str = Field(..., frozen=True)
    value: str = Field(..., frozen=True)

    @model_validator(mode="after")
    def validate_system(self) -> "Identifier":
        if self._validate_system and self.system != self.expected_system:
            raise ValidationError(
                f"Identifier system '{self.system}' does not match expected "
                f"system '{self.expected_system}'."
            )
        return self

    @classmethod
    def __init_subclass__(
        cls, expected_system: str = "__unknown__", validate_system: bool = True
    ) -> None:
        cls.expected_system = expected_system
        cls._validate_system = validate_system

        cls.__system_types[expected_system] = cls

    @model_validator(mode="wrap")
    @classmethod
    def validate_with_system(
        cls, value: dict[str, Any], handler: ValidatorFunctionWrapHandler
    ) -> Any:
        """
        Provides a model validator that instantiates the correct Identifier type based
        on the supplied system. If either no system is provided, or the system provided
        is not supported, the UnknownIdentifier type will be utilised.
        """

        if cls != Identifier or not isinstance(value, dict):
            return handler(value)

        system = value.get("system")
        if system is None:
            # This condition is unreachable as Pydantic will validate the presence of
            # the required 'system' field before this validator is called.
            raise ValueError("Identifier provided without a system attribute.")

        identifier_cls = cls.__system_types.get(system)
        if identifier_cls is None:
            return UnknownIdentifier.model_validate(value)

        return identifier_cls.model_validate(value)


class UnknownIdentifier(Identifier, validate_system=False):
    """Provides a fallback Identifier type for an unknown system."""


class PatientIdentifier(
    Identifier, expected_system="https://fhir.nhs.uk/Id/nhs-number"
):
    """A FHIR R4 Patient Identifier utilising the NHS Number system."""

    @classmethod
    def create_with(cls, nhs_number: str) -> "PatientIdentifier":
        """Create a PatientIdentifier from an NHS number."""
        return cls(value=nhs_number, system=cls.expected_system)


class OrganizationIdentifier(
    Identifier, expected_system="https://fhir.nhs.uk/Id/ods-organization-code"
):
    """A FHIR R4 Organization Identifier utilising the ODS Organization Code system."""

    @classmethod
    def from_ods_code(cls, ods_code: str) -> "OrganizationIdentifier":
        """Create an OrganizationIdentifier from an ODS code."""
        return cls(value=ods_code, system=cls.expected_system)


@dataclass(frozen=True)
class LogicalReference[T: Identifier]:
    identifier: T
    reference: str | None = None


@dataclass(frozen=True)
class LiteralReference:
    reference: str


class Extension(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True, extra="allow")

    __extension_types: ClassVar[dict[str, type["Extension"]]] = {}
    type_name: ClassVar[str] = "__unknown__"

    url: str = Field(..., frozen=True)

    def __init_subclass__(cls, type_name: str) -> None:
        cls.type_name = type_name
        cls.__extension_types[type_name] = cls
        super().__init_subclass__()

    @model_validator(mode="wrap")
    @classmethod
    def validate_with_type(
        cls, value: dict[str, Any], handler: ValidatorFunctionWrapHandler
    ) -> Any:
        """
        Provides a model validator that instantiates the correct Extension type based on
        the valueX field provided.
        If an Extension subclass cannot be found, the default handler is utilised
        instead.
        """

        # If we're not validating an Extension, or the value is not a dict,
        # delegate to the default handler
        if cls != Extension or not isinstance(value, dict):
            return handler(value)

        for key in value:
            if key.startswith("value"):
                type_name = key.split("value", 1)[1]
                if (extension_cls := cls.__extension_types.get(type_name)) is not None:
                    return extension_cls.model_validate(value)

        return handler(value)


class ReferenceExtension(Extension, type_name="Reference"):
    value: LiteralReference = Field(..., alias="valueReference", frozen=True)

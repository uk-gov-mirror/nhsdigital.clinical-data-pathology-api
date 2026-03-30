from dataclasses import dataclass
from typing import Annotated, Any, ClassVar, Literal, Self, TypedDict

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    SerializeAsAny,
    ValidatorFunctionWrapHandler,
    field_validator,
    model_validator,
)

from pathology_api.exception import ValidationError

from .elements import (
    Extension,
    Identifier,
    LiteralReference,
    LogicalReference,
    Meta,
    PatientIdentifier,
    UUIDIdentifier,
)


class Resource(BaseModel):
    """A FHIR R4 Resource base class."""

    model_config = ConfigDict(extra="allow")

    # class variable to hold class mappings per resource_type
    __resource_types: ClassVar[dict[str, type["Resource"]]] = {}
    __expected_resource_type: ClassVar[dict[type["Resource"], str]] = {}

    id: Annotated[str | None, Field(frozen=True)] = None
    meta: Annotated[Meta | None, Field(alias="meta", frozen=True)] = None
    resource_type: str = Field(alias="resourceType", frozen=True)
    extension: Annotated[list[SerializeAsAny[Extension]] | None, Field(frozen=True)] = (
        None
    )

    def __init_subclass__(cls, resource_type: str, **kwargs: Any) -> None:
        cls.__resource_types[resource_type] = cls
        cls.__expected_resource_type[cls] = resource_type

        super().__init_subclass__(**kwargs)

    def find_extension[T: Extension](
        self, url: str, required_type: type[T]
    ) -> T | None:
        extensions = [ext for ext in self.extension or [] if ext.url == url]
        if not extensions:
            return None

        if len(extensions) > 1:
            raise ValidationError(f"Multiple extensions provided with same url: {url}")

        extension = extensions[0]
        if not isinstance(extension, required_type):
            raise ValidationError(
                f"Extension with url {url} is not expected type "
                f"{required_type.type_name}"
            )

        return extension

    @model_validator(mode="wrap")
    @classmethod
    def validate_with_subtype(
        cls, value: dict[str, Any], handler: ValidatorFunctionWrapHandler
    ) -> Any:
        """
        Provides a model validator that instantiates the correct Resource subclass
        based on its defined resource_type.
        """
        # If we're not currently acting on a top level Resource, and we've not been
        # provided a generic dictonary object, delegate to the normal handler.
        if cls != Resource or not isinstance(value, dict):
            return handler(value)

        if "resourceType" not in value or value["resourceType"] is None:
            raise ValidationError("resourceType must be provided for each Resource.")

        resource_type = value["resourceType"]

        subclass = cls.__resource_types.get(resource_type)
        if subclass is None:
            raise ValidationError(f"Unsupported resourceType: {resource_type}")

        # Instantiate the subclass using the dictionary values.
        return subclass.model_validate(value)

    @classmethod
    def create(cls, **kwargs: Any) -> Self:
        """
        Create a Resource instance with the correct resourceType.
        Note any unknown arguments provided via this method will only error at runtime.
        """
        return cls(resourceType=cls.__expected_resource_type[cls], **kwargs)

    @field_validator("resource_type", mode="after")
    @classmethod
    def _validate_resource_type(cls, value: str) -> str:
        expected_resource_type = cls.__expected_resource_type[cls]
        if value != expected_resource_type:
            raise ValidationError(
                f"Provided resourceType '{value}' does not match required "
                f"resourceType '{expected_resource_type}'."
            )
        return value


type BundleType = Literal[
    "document",
    "message",
    "transaction",
    "transaction-response",
    "batch",
    "batch-response",
    "history",
    "searchset",
    "collection",
]


class Bundle(Resource, resource_type="Bundle"):
    """A FHIR R4 Bundle resource."""

    bundle_type: BundleType = Field(alias="type", frozen=True)
    identifier: Annotated[UUIDIdentifier | None, Field(frozen=True)] = None
    entries: list["Bundle.Entry"] | None = Field(None, frozen=True, alias="entry")

    class Entry(BaseModel):
        full_url: str = Field(..., alias="fullUrl", frozen=True)
        resource: Annotated[SerializeAsAny[Resource], Field(frozen=True)]

    def find_resources[T: Resource](self, t: type[T]) -> list[T]:
        """
        Find all resources of a given type in the bundle entries. If the bundle has no
        entries, an empty list is returned.
        Args:
            t: The resource type to search for.
        Returns:
            A list of resources of the specified type.
        """
        return [
            entry.resource
            for entry in self.entries or []
            if isinstance(entry.resource, t)
        ]

    def has_resource[T: Resource](self, t: type[T]) -> bool:
        """
        Check if the bundle contains at least one resource of a given type in its
        entries.
        If the bundle has no entries, False is returned.
        Args:
            t: The resource type to search for.
        Returns:
            True if at least one resource of the specified type is found, otherwise
            False.
        """
        return self.find_resources(t) != []

    def get_resource[T: Resource](self, url: str, t: type[T]) -> T | None:
        """
        Get the resource of a given type in the bundle entries with the specified
        fullUrl.
        If no matching resource is found, or if the matching resource is not of the
        expected type, a ValidationError is raised.
        Args:
            url: The fullUrl of the resource to find.
            t: The expected type of the resource.
        Returns:
            The resource with the specified fullUrl and type. Or None if not resource is
            found with the provided url and required type.
        """
        resources = [
            entry.resource
            for entry in self.entries or []
            if entry.full_url == url and isinstance(entry.resource, t)
        ]

        if not resources:
            return None

        if len(resources) > 1:
            raise ValidationError(
                f"Multiple resources provided with same fullUrl: {url}"
            )

        return resources[0]

    @classmethod
    def empty(cls, bundle_type: BundleType) -> "Bundle":
        """Create an empty Bundle of the specified type."""
        return cls.create(type=bundle_type, entry=None)


class Patient(Resource, resource_type="Patient"):
    """A FHIR R4 Patient resource."""


class ServiceRequest(Resource, resource_type="ServiceRequest"):
    """A FHIR R4 ServiceRequest resource."""

    requester: LiteralReference | None = Field(None, frozen=True)


class DiagnosticReport(Resource, resource_type="DiagnosticReport"):
    """A FHIR R4 DiagnosticReport resource."""


class Organization(Resource, resource_type="Organization"):
    """A FHIR R4 Organization resource."""

    identifier: SerializeAsAny[list[Identifier]] | None = Field(None, frozen=True)


class Practitioner(Resource, resource_type="Practitioner"):
    """A FHIR R4 Practitioner resource."""


class PractitionerRole(Resource, resource_type="PractitionerRole"):
    """A FHIR R4 PractitionerRole resource."""

    organization: LiteralReference | None = Field(None, frozen=True)


class Observation(Resource, resource_type="Observation"):
    """A FHIR R4 Observation resource."""


class Specimen(Resource, resource_type="Specimen"):
    """A FHIR R4 Specimen resource."""


class Composition(Resource, resource_type="Composition"):
    """A FHIR R4 Composition resource."""

    subject: Annotated[
        LogicalReference[PatientIdentifier] | None, Field(frozen=True)
    ] = None


class OperationOutcome(BaseModel):
    """
    A FHIR R4 OperationOutcome resource.

    Note this class is deliberately not a subclass of Resource so that it is not
    accepted as a valid resource for a client.
    """

    resource_type: Literal["OperationOutcome"] = Field(
        "OperationOutcome", alias="resourceType", frozen=True
    )

    @dataclass(frozen=True)
    class Issue(TypedDict):
        severity: Literal["fatal", "error", "warning", "information"]
        code: str
        diagnostics: str | None

    issue: list[Issue] = Field(frozen=True)

    @classmethod
    def create_validation_error(cls, diagnostics: str) -> Self:
        """
        Create an OperationOutcome with the provided diagnostic as a validation error.
        Args:
            diagnostics: The diagnostic message for the validation error.
        """

        return cls(
            resourceType="OperationOutcome",
            issue=[
                {
                    "severity": "error",
                    "code": "invalid",
                    "diagnostics": diagnostics,
                }
            ],
        )

    @classmethod
    def create_server_error(cls, diagnostics: str | None = None) -> Self:
        """
        Create an OperationOutcome with the provided diagnostics as a server error.
        Args:
            diagnostics: any diagnostics to include with the server error.
        """

        return cls(
            resourceType="OperationOutcome",
            issue=[
                {
                    "severity": "fatal",
                    "code": "exception",
                    "diagnostics": diagnostics,
                }
            ],
        )

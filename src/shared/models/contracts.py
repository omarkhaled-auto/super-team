"""Contract engine Pydantic v2 data models."""
from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, model_validator


class ContractType(str, Enum):
    """Types of API contracts."""
    OPENAPI = "openapi"
    ASYNCAPI = "asyncapi"
    JSON_SCHEMA = "json_schema"


class ContractStatus(str, Enum):
    """Status of a contract."""
    ACTIVE = "active"
    DEPRECATED = "deprecated"
    DRAFT = "draft"


class ImplementationStatus(str, Enum):
    """Status of a contract implementation."""
    VERIFIED = "verified"
    PENDING = "pending"
    FAILED = "failed"


class ContractEntry(BaseModel):
    """A stored contract entry."""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    type: ContractType
    version: str = Field(..., pattern=r"^\d+\.\d+\.\d+$")
    service_name: str
    spec: dict[str, Any]
    spec_hash: str = ""
    status: ContractStatus = ContractStatus.DRAFT
    build_cycle_id: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    model_config = {"from_attributes": True}

    @model_validator(mode="before")
    @classmethod
    def compute_spec_hash(cls, data: Any) -> Any:
        if isinstance(data, dict):
            spec = data.get("spec")
            if spec and not data.get("spec_hash"):
                data["spec_hash"] = hashlib.sha256(
                    json.dumps(spec, sort_keys=True).encode("utf-8")
                ).hexdigest()
        return data


class ContractCreate(BaseModel):
    """Request to create or update a contract."""
    service_name: str = Field(..., max_length=100)
    type: ContractType
    version: str = Field(..., pattern=r"^\d+\.\d+\.\d+$")
    spec: dict[str, Any]
    build_cycle_id: str | None = None

    model_config = {"from_attributes": True}


class ContractListResponse(BaseModel):
    """Paginated list of contracts."""
    items: list[ContractEntry]
    total: int
    page: int
    page_size: int

    model_config = {"from_attributes": True}


class EndpointSpec(BaseModel):
    """Specification for an API endpoint."""
    path: str
    method: str = Field(..., pattern=r"^(GET|POST|PUT|PATCH|DELETE|HEAD|OPTIONS)$")
    operation_id: str | None = None
    summary: str = ""
    parameters: list[dict[str, Any]] = Field(default_factory=list)
    request_body_schema: dict[str, Any] | None = None
    response_schemas: dict[str, dict[str, Any]] = Field(default_factory=dict)

    model_config = {"from_attributes": True}


class OpenAPIContract(BaseModel):
    """Parsed OpenAPI contract."""
    contract_id: str
    openapi_version: str = "3.1.0"
    title: str
    api_version: str
    endpoints: list[EndpointSpec] = Field(default_factory=list)
    schemas: dict[str, Any] = Field(default_factory=dict)

    model_config = {"from_attributes": True}


class MessageSpec(BaseModel):
    """Specification for an async message."""
    name: str
    content_type: str = "application/json"
    payload_schema: dict[str, Any] = Field(default_factory=dict)
    headers_schema: dict[str, Any] | None = None

    model_config = {"from_attributes": True}


class ChannelSpec(BaseModel):
    """Specification for an async channel."""
    name: str
    address: str
    description: str = ""
    messages: list[MessageSpec] = Field(default_factory=list)

    model_config = {"from_attributes": True}


class OperationSpec(BaseModel):
    """Specification for an async operation."""
    name: str
    action: str = Field(..., pattern=r"^(send|receive)$")
    channel_name: str
    summary: str = ""
    message_names: list[str] = Field(default_factory=list)

    model_config = {"from_attributes": True}


class AsyncAPIContract(BaseModel):
    """Parsed AsyncAPI contract."""
    contract_id: str
    asyncapi_version: str = "3.0.0"
    title: str
    api_version: str
    channels: list[ChannelSpec] = Field(default_factory=list)
    operations: list[OperationSpec] = Field(default_factory=list)
    schemas: dict[str, Any] = Field(default_factory=dict)

    model_config = {"from_attributes": True}


class SharedSchema(BaseModel):
    """A schema shared between services."""
    name: str
    schema_def: dict[str, Any]
    owning_service: str
    consuming_services: list[str] = Field(default_factory=list)

    model_config = {"from_attributes": True}


class BreakingChange(BaseModel):
    """A breaking change detected between contract versions."""
    change_type: str
    path: str
    old_value: str | None = None
    new_value: str | None = None
    severity: str = Field(default="error", pattern=r"^(error|warning|info)$")
    is_breaking: bool = True
    affected_consumers: list[str] = Field(default_factory=list)

    model_config = {"from_attributes": True}

    @model_validator(mode="before")
    @classmethod
    def compute_is_breaking(cls, data: Any) -> Any:
        if isinstance(data, dict):
            severity = data.get("severity", "error")
            if "is_breaking" not in data:
                data["is_breaking"] = severity in ("error", "warning")
        return data


class ContractVersion(BaseModel):
    """Version record for a contract."""
    contract_id: str
    version: str
    spec_hash: str
    build_cycle_id: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    is_breaking: bool = False
    breaking_changes: list[BreakingChange] = Field(default_factory=list)

    model_config = {"from_attributes": True}


class ImplementationRecord(BaseModel):
    """Record of a contract implementation."""
    contract_id: str
    service_name: str
    evidence_path: str
    status: ImplementationStatus = ImplementationStatus.PENDING
    verified_at: datetime | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    model_config = {"from_attributes": True}


class ValidationResult(BaseModel):
    """Result of validating a contract spec."""
    valid: bool
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)

    model_config = {"from_attributes": True}


class ValidateRequest(BaseModel):
    """Request to validate a contract spec."""
    spec: dict[str, Any]
    type: ContractType

    model_config = {"from_attributes": True}


class MarkRequest(BaseModel):
    """Request to mark a contract as implemented."""
    contract_id: str
    service_name: str
    evidence_path: str

    model_config = {"from_attributes": True}


class MarkResponse(BaseModel):
    """Response from marking a contract as implemented."""
    marked: bool
    total_implementations: int
    all_implemented: bool

    model_config = {"from_attributes": True}


class UnimplementedContract(BaseModel):
    """A contract that has not been implemented."""
    id: str
    type: str
    version: str
    expected_service: str
    status: str

    model_config = {"from_attributes": True}


class ContractTestSuite(BaseModel):
    """Generated test suite for a contract."""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    contract_id: str
    framework: str = Field(default="pytest", pattern=r"^(pytest|jest)$")
    test_code: str
    test_count: int = Field(..., ge=0)
    include_negative: bool = False
    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    model_config = {"from_attributes": True}


class ComplianceViolation(BaseModel):
    """A compliance violation found during checking."""
    field: str
    expected: str
    actual: str
    severity: str = "error"

    model_config = {"from_attributes": True}


class ComplianceResult(BaseModel):
    """Result of a compliance check."""
    endpoint_path: str
    method: str
    compliant: bool
    violations: list[ComplianceViolation] = Field(default_factory=list)

    model_config = {"from_attributes": True}

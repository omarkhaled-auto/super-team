"""Architect service Pydantic v2 data models."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, model_validator


class ServiceStack(BaseModel):
    """Technology stack for a service."""
    language: str
    framework: str | None = None
    database: str | None = None
    message_broker: str | None = None

    model_config = {"from_attributes": True}


class RelationshipType(str, Enum):
    """Types of relationships between domain entities."""
    OWNS = "OWNS"
    REFERENCES = "REFERENCES"
    TRIGGERS = "TRIGGERS"
    EXTENDS = "EXTENDS"
    DEPENDS_ON = "DEPENDS_ON"


class ServiceDefinition(BaseModel):
    """Definition of a microservice within the system."""
    name: str = Field(..., pattern=r"^[a-z][a-z0-9-]*$")
    domain: str
    description: str
    stack: ServiceStack
    estimated_loc: int = Field(..., ge=100, le=200000)
    owns_entities: list[str] = Field(default_factory=list)
    provides_contracts: list[str] = Field(default_factory=list)
    consumes_contracts: list[str] = Field(default_factory=list)

    model_config = {"from_attributes": True}


class EntityField(BaseModel):
    """Field within a domain entity."""
    name: str
    type: str
    required: bool = True
    description: str = ""

    model_config = {"from_attributes": True}


class StateTransition(BaseModel):
    """Transition between states in a state machine."""
    from_state: str
    to_state: str
    trigger: str
    guard: str | None = None

    model_config = {"from_attributes": True}


class StateMachine(BaseModel):
    """State machine definition for an entity."""
    states: list[str] = Field(..., min_length=2)
    initial_state: str
    transitions: list[StateTransition]

    model_config = {"from_attributes": True}


class DomainEntity(BaseModel):
    """Entity within the domain model."""
    name: str
    description: str
    owning_service: str
    fields: list[EntityField] = Field(default_factory=list)
    state_machine: StateMachine | None = None

    model_config = {"from_attributes": True}


class DomainRelationship(BaseModel):
    """Relationship between two domain entities."""
    source_entity: str
    target_entity: str
    relationship_type: RelationshipType
    cardinality: str = Field(..., pattern=r"^(1|N):(1|N)$")
    description: str = ""

    model_config = {"from_attributes": True}


class DomainModel(BaseModel):
    """Complete domain model with entities and relationships."""
    entities: list[DomainEntity]
    relationships: list[DomainRelationship]
    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    model_config = {"from_attributes": True}


class ServiceMap(BaseModel):
    """Map of all services in the system."""
    project_name: str
    services: list[ServiceDefinition] = Field(..., min_length=1)
    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    prd_hash: str
    build_cycle_id: str | None = None

    model_config = {"from_attributes": True}


class DecompositionResult(BaseModel):
    """Result of decomposing a PRD into services."""
    service_map: ServiceMap
    domain_model: DomainModel
    contract_stubs: list[dict] = Field(default_factory=list)
    validation_issues: list[str] = Field(default_factory=list)
    interview_questions: list[str] = Field(default_factory=list)

    model_config = {"from_attributes": True}


class DecomposeRequest(BaseModel):
    """Request to decompose a PRD document."""
    prd_text: str = Field(..., min_length=10, max_length=1_048_576)

    model_config = {"from_attributes": True}


class DecompositionRun(BaseModel):
    """Record of a decomposition run."""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    prd_content_hash: str
    status: str = Field(
        default="pending",
        pattern=r"^(pending|running|completed|failed|review)$"
    )
    service_map_id: str | None = None
    domain_model_id: str | None = None
    validation_issues: list[str] = Field(default_factory=list)
    interview_questions: list[str] = Field(default_factory=list)
    started_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: datetime | None = None

    model_config = {"from_attributes": True}

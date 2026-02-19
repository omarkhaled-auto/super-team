"""Shared test fixtures for the super-team test suite."""
from __future__ import annotations

import os
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Generator

import pytest

from src.shared.db.connection import ConnectionPool
from src.shared.models.architect import (
    DecomposeRequest,
    DecompositionRun,
    DomainEntity,
    DomainModel,
    DomainRelationship,
    EntityField,
    RelationshipType,
    ServiceDefinition,
    ServiceMap,
    ServiceStack,
    StateMachine,
    StateTransition,
)
from src.shared.models.codebase import (
    CodeChunk,
    DeadCodeEntry,
    DependencyEdge,
    DependencyRelation,
    GraphAnalysis,
    ImportReference,
    IndexStats,
    Language,
    SemanticSearchResult,
    ServiceInterface,
    SymbolDefinition,
    SymbolKind,
)
from src.shared.models.common import ArtifactRegistration, BuildCycle, HealthStatus
from src.shared.models.contracts import (
    BreakingChange,
    ComplianceResult,
    ComplianceViolation,
    ContractCreate,
    ContractEntry,
    ContractListResponse,
    ContractStatus,
    ContractTestSuite,
    ContractType,
    ContractVersion,
    EndpointSpec,
    ImplementationRecord,
    ImplementationStatus,
    MarkRequest,
    MarkResponse,
    OpenAPIContract,
    UnimplementedContract,
    ValidateRequest,
    ValidationResult,
)


@pytest.fixture
def tmp_db_path(tmp_path: Path) -> Path:
    """Provide a temporary database path."""
    return tmp_path / "test.db"


@pytest.fixture
def connection_pool(tmp_db_path: Path) -> Generator[ConnectionPool, None, None]:
    """Provide a ConnectionPool with a temporary database."""
    pool = ConnectionPool(tmp_db_path)
    yield pool
    pool.close()


@pytest.fixture
def sample_service_stack() -> ServiceStack:
    """Provide a sample ServiceStack instance."""
    return ServiceStack(language="python", framework="fastapi", database="sqlite")


@pytest.fixture
def sample_service_definition(sample_service_stack: ServiceStack) -> ServiceDefinition:
    """Provide a sample ServiceDefinition instance."""
    return ServiceDefinition(
        name="user-service",
        domain="identity",
        description="Manages user accounts",
        stack=sample_service_stack,
        estimated_loc=5000,
        owns_entities=["User", "Profile"],
        provides_contracts=["user-api"],
        consumes_contracts=[],
    )


@pytest.fixture
def sample_entity_field() -> EntityField:
    """Provide a sample EntityField instance."""
    return EntityField(name="email", type="string", required=True, description="User email")


@pytest.fixture
def sample_state_machine() -> StateMachine:
    """Provide a sample StateMachine instance."""
    return StateMachine(
        states=["active", "inactive", "suspended"],
        initial_state="active",
        transitions=[
            StateTransition(
                from_state="active", to_state="inactive", trigger="deactivate"
            ),
            StateTransition(
                from_state="inactive", to_state="active", trigger="activate"
            ),
        ],
    )


@pytest.fixture
def sample_domain_entity(
    sample_entity_field: EntityField, sample_state_machine: StateMachine
) -> DomainEntity:
    """Provide a sample DomainEntity instance."""
    return DomainEntity(
        name="User",
        description="Application user",
        owning_service="user-service",
        fields=[sample_entity_field],
        state_machine=sample_state_machine,
    )


@pytest.fixture
def sample_domain_relationship() -> DomainRelationship:
    """Provide a sample DomainRelationship instance."""
    return DomainRelationship(
        source_entity="Order",
        target_entity="User",
        relationship_type=RelationshipType.REFERENCES,
        cardinality="N:1",
        description="Order belongs to user",
    )


@pytest.fixture
def sample_contract_entry() -> ContractEntry:
    """Provide a sample ContractEntry instance."""
    return ContractEntry(
        type=ContractType.OPENAPI,
        version="1.0.0",
        service_name="user-service",
        spec={"openapi": "3.1.0", "info": {"title": "User API", "version": "1.0.0"}},
    )


@pytest.fixture
def sample_symbol_definition() -> SymbolDefinition:
    """Provide a sample SymbolDefinition instance."""
    return SymbolDefinition(
        file_path="src/auth/auth.py",
        symbol_name="AuthService",
        kind=SymbolKind.CLASS,
        language=Language.PYTHON,
        service_name="auth-service",
        line_start=10,
        line_end=50,
        signature="class AuthService:",
        docstring="Authentication service",
        is_exported=True,
    )


@pytest.fixture
def sample_health_status() -> HealthStatus:
    """Provide a sample HealthStatus instance."""
    return HealthStatus(
        status="healthy",
        service_name="test-service",
        version="1.0.0",
        database="connected",
        uptime_seconds=120.5,
    )


@pytest.fixture
def mock_env_vars(monkeypatch: pytest.MonkeyPatch) -> None:
    """Set mock environment variables for config testing."""
    monkeypatch.setenv("LOG_LEVEL", "debug")
    monkeypatch.setenv("DATABASE_PATH", "/tmp/test.db")
    monkeypatch.setenv("CONTRACT_ENGINE_URL", "http://localhost:9000")
    monkeypatch.setenv("CODEBASE_INTEL_URL", "http://localhost:9001")
    monkeypatch.setenv("CHROMA_PATH", "/tmp/chroma")
    monkeypatch.setenv("GRAPH_PATH", "/tmp/graph.json")

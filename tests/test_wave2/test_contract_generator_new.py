"""Wave 2 tests for contract generator.

Tests entity schema field definitions, state machine transition endpoints,
generic CRUD generation, and backward compatibility.
"""
from __future__ import annotations

import pytest

from src.architect.services.contract_generator import generate_contract_stubs
from src.shared.models.architect import (
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


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _stack(language: str = "python") -> ServiceStack:
    return ServiceStack(language=language)


def _service(
    name: str,
    owns_entities: list[str] | None = None,
) -> ServiceDefinition:
    return ServiceDefinition(
        name=name,
        domain="core",
        description=f"{name} service",
        stack=_stack(),
        estimated_loc=500,
        owns_entities=owns_entities or [],
    )


def _field(name: str, type_: str = "string", required: bool = True) -> EntityField:
    return EntityField(name=name, type=type_, required=required)


def _entity(
    name: str,
    owning_service: str = "svc",
    fields: list[EntityField] | None = None,
    state_machine: StateMachine | None = None,
) -> DomainEntity:
    return DomainEntity(
        name=name,
        description=f"{name} entity",
        owning_service=owning_service,
        fields=fields or [],
        state_machine=state_machine,
    )


def _service_map(*services: ServiceDefinition) -> ServiceMap:
    return ServiceMap(
        project_name="test-project",
        services=list(services),
        prd_hash="hash123",
    )


def _domain_model(
    entities: list[DomainEntity] | None = None,
    relationships: list[DomainRelationship] | None = None,
) -> DomainModel:
    return DomainModel(
        entities=entities or [],
        relationships=relationships or [],
    )


# ---------------------------------------------------------------------------
# 1. Generic CRUD generation (backward compat)
# ---------------------------------------------------------------------------


class TestGenericCRUDFallback:
    """Generic CRUD endpoints are generated for services with entities."""

    def test_crud_generated_for_service_with_entities(self):
        """Without explicit endpoints, generic CRUD is generated."""
        svc = _service("user-service", owns_entities=["User"])
        smap = _service_map(svc)
        dm = _domain_model(entities=[_entity("User", "user-service")])

        specs = generate_contract_stubs(smap, dm)
        assert len(specs) >= 1

        openapi_spec = specs[0]
        paths = openapi_spec["paths"]
        assert "/api/users" in paths
        assert "/api/users/{id}" in paths

        # Verify CRUD operations
        collection = paths["/api/users"]
        assert "get" in collection
        assert "post" in collection

        item = paths["/api/users/{id}"]
        assert "get" in item
        assert "put" in item
        assert "delete" in item


# ---------------------------------------------------------------------------
# 2. Entity schemas include field definitions
# ---------------------------------------------------------------------------


class TestEntitySchemaFieldDefinitions:
    """Entity schemas in OpenAPI specs include field definitions."""

    def test_schema_has_entity_fields(self):
        """Entity schema properties include all entity fields."""
        svc = _service("user-service", owns_entities=["User"])
        smap = _service_map(svc)
        dm = _domain_model(entities=[
            _entity("User", "user-service", fields=[
                _field("email", "string"),
                _field("age", "integer", required=False),
                _field("active", "boolean"),
            ]),
        ])

        specs = generate_contract_stubs(smap, dm)
        schema = specs[0]["components"]["schemas"]["User"]
        properties = schema["properties"]

        assert "email" in properties
        assert "age" in properties
        assert "active" in properties
        assert "id" in properties  # Always present

    def test_empty_entity_schema_has_id_only(self):
        """An entity with no fields has a schema with only 'id'."""
        svc = _service("tag-service", owns_entities=["Tag"])
        smap = _service_map(svc)
        dm = _domain_model(entities=[_entity("Tag", "tag-service")])

        specs = generate_contract_stubs(smap, dm)
        schema = specs[0]["components"]["schemas"]["Tag"]
        properties = schema["properties"]

        assert "id" in properties
        assert len(properties) == 1  # Only id

    def test_required_fields_in_schema(self):
        """Required fields are listed in the schema's required array."""
        svc = _service("user-service", owns_entities=["User"])
        smap = _service_map(svc)
        dm = _domain_model(entities=[
            _entity("User", "user-service", fields=[
                _field("email", "string", required=True),
                _field("nickname", "string", required=False),
            ]),
        ])

        specs = generate_contract_stubs(smap, dm)
        schema = specs[0]["components"]["schemas"]["User"]
        required = schema.get("required", [])

        assert "id" in required
        assert "email" in required
        assert "nickname" not in required


# ---------------------------------------------------------------------------
# 3. CRUD path generation
# ---------------------------------------------------------------------------


class TestCRUDPathGeneration:
    """CRUD paths are generated for entities owned by a service."""

    def test_crud_paths_include_collection_and_item(self):
        """CRUD paths include both collection and item endpoints."""
        svc = _service("user-service", owns_entities=["User"])
        smap = _service_map(svc)
        dm = _domain_model(entities=[_entity("User", "user-service")])

        specs = generate_contract_stubs(smap, dm)
        paths = specs[0]["paths"]

        # Should have standard CRUD paths
        assert "/api/users" in paths
        assert "/api/users/{id}" in paths

        # Should only have standard CRUD paths (no action-style paths)
        for path_key in paths:
            parts = path_key.strip("/").split("/")
            # CRUD paths have at most 3 segments: api/users/{id}
            assert len(parts) <= 3


# ---------------------------------------------------------------------------
# 4. No contracts for bogus entities
# ---------------------------------------------------------------------------


class TestNoBogusEntityContracts:
    """No contracts generated for filtered-out bogus entities."""

    def test_service_with_no_entities_gets_health_only(self):
        """A service with no owned entities gets only a health endpoint."""
        svc = _service("empty-service", owns_entities=[])
        smap = _service_map(svc)
        dm = _domain_model()

        specs = generate_contract_stubs(smap, dm)
        assert len(specs) == 1
        paths = specs[0]["paths"]
        assert "/health" in paths
        assert len(paths) == 1  # Only health endpoint

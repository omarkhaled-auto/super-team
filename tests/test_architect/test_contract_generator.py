"""Tests for src.architect.services.contract_generator.generate_contract_stubs.

Covers the OpenAPI 3.1 stub generation logic:
    1.  Generates one spec per service
    2.  Each spec has openapi "3.1.0"
    3.  CRUD paths generated for owned entities (GET list, POST, GET by id, PUT, DELETE)
    4.  Schema definitions in components/schemas
    5.  Entity fields mapped to correct JSON Schema types
    6.  Entity pluralization (User -> users)
    7.  CamelCase to kebab-case conversion (OrderItem -> order-items)
    8.  Service with no owned entities generates minimal spec (health only)
    9.  Entity not found in domain model generates minimal schema (id only)
    10. Required fields correctly identified in schema
"""

from __future__ import annotations

import pytest

from src.shared.models.architect import (
    DomainEntity,
    DomainModel,
    DomainRelationship,
    EntityField,
    RelationshipType,
    ServiceDefinition,
    ServiceMap,
    ServiceStack,
)
from src.architect.services.contract_generator import generate_contract_stubs


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _stack() -> ServiceStack:
    """Return a minimal ServiceStack."""
    return ServiceStack(language="python")


def _service(
    name: str,
    owns_entities: list[str] | None = None,
    description: str | None = None,
) -> ServiceDefinition:
    """Build a ServiceDefinition with sensible defaults."""
    return ServiceDefinition(
        name=name,
        domain="core",
        description=description or f"{name} service",
        stack=_stack(),
        estimated_loc=500,
        owns_entities=owns_entities or [],
    )


def _field(name: str, type_: str = "string", required: bool = True) -> EntityField:
    """Build an EntityField."""
    return EntityField(name=name, type=type_, required=required)


def _entity(
    name: str,
    owning_service: str = "svc",
    fields: list[EntityField] | None = None,
) -> DomainEntity:
    """Build a DomainEntity with optional fields."""
    return DomainEntity(
        name=name,
        description=f"{name} entity",
        owning_service=owning_service,
        fields=fields or [],
    )


def _service_map(*services: ServiceDefinition) -> ServiceMap:
    """Wrap services in a ServiceMap."""
    return ServiceMap(
        project_name="test-project",
        services=list(services),
        prd_hash="hash123",
    )


def _domain_model(
    entities: list[DomainEntity] | None = None,
    relationships: list[DomainRelationship] | None = None,
) -> DomainModel:
    """Build a DomainModel."""
    return DomainModel(
        entities=entities or [],
        relationships=relationships or [],
    )


# ---------------------------------------------------------------------------
# 1. Generates one spec per service
# ---------------------------------------------------------------------------


class TestOneSpecPerService:
    """generate_contract_stubs must return exactly one spec per service."""

    def test_single_service_yields_one_spec(self) -> None:
        """One service in the map should produce exactly one spec."""
        sm = _service_map(_service("order-svc", owns_entities=["Order"]))
        dm = _domain_model(entities=[_entity("Order")])

        specs = generate_contract_stubs(sm, dm)

        assert len(specs) == 1

    def test_three_services_yield_three_specs(self) -> None:
        """Three services should produce exactly three specs."""
        sm = _service_map(
            _service("svc-a", owns_entities=["Alpha"]),
            _service("svc-b", owns_entities=["Beta"]),
            _service("svc-c", owns_entities=["Gamma"]),
        )
        dm = _domain_model(
            entities=[_entity("Alpha"), _entity("Beta"), _entity("Gamma")]
        )

        specs = generate_contract_stubs(sm, dm)

        assert len(specs) == 3


# ---------------------------------------------------------------------------
# 2. Each spec has openapi "3.1.0"
# ---------------------------------------------------------------------------


class TestOpenapiVersion:
    """Every generated spec must declare OpenAPI version 3.1.0."""

    def test_openapi_version_is_3_1_0(self) -> None:
        """The 'openapi' key in each spec must be the string '3.1.0'."""
        sm = _service_map(_service("my-svc", owns_entities=["Thing"]))
        dm = _domain_model(entities=[_entity("Thing")])

        specs = generate_contract_stubs(sm, dm)

        for spec in specs:
            assert spec["openapi"] == "3.1.0"


# ---------------------------------------------------------------------------
# 3. CRUD paths generated for owned entities
# ---------------------------------------------------------------------------


class TestCrudPaths:
    """Owned entities must produce the five standard CRUD endpoints."""

    def test_crud_paths_present_for_entity(self) -> None:
        """For entity 'User' the spec must include:
        GET /api/users, POST /api/users, GET /api/users/{id},
        PUT /api/users/{id}, DELETE /api/users/{id}."""
        sm = _service_map(_service("user-svc", owns_entities=["User"]))
        dm = _domain_model(entities=[_entity("User")])

        specs = generate_contract_stubs(sm, dm)
        paths = specs[0]["paths"]

        # Collection endpoints
        assert "/api/users" in paths
        assert "get" in paths["/api/users"], "GET list endpoint missing"
        assert "post" in paths["/api/users"], "POST endpoint missing"

        # Item endpoints
        assert "/api/users/{id}" in paths
        assert "get" in paths["/api/users/{id}"], "GET by ID endpoint missing"
        assert "put" in paths["/api/users/{id}"], "PUT endpoint missing"
        assert "delete" in paths["/api/users/{id}"], "DELETE endpoint missing"

    def test_multiple_entities_produce_separate_crud_paths(self) -> None:
        """A service owning two entities must have CRUD paths for both."""
        sm = _service_map(
            _service("multi-svc", owns_entities=["User", "Order"])
        )
        dm = _domain_model(
            entities=[_entity("User"), _entity("Order")]
        )

        specs = generate_contract_stubs(sm, dm)
        paths = specs[0]["paths"]

        assert "/api/users" in paths
        assert "/api/users/{id}" in paths
        assert "/api/orders" in paths
        assert "/api/orders/{id}" in paths


# ---------------------------------------------------------------------------
# 4. Schema definitions in components/schemas
# ---------------------------------------------------------------------------


class TestSchemaDefinitions:
    """Each owned entity must appear in components/schemas."""

    def test_entity_schema_present_in_components(self) -> None:
        """The entity name should be a key in components/schemas."""
        sm = _service_map(_service("svc", owns_entities=["Product"]))
        dm = _domain_model(entities=[_entity("Product")])

        specs = generate_contract_stubs(sm, dm)
        schemas = specs[0]["components"]["schemas"]

        assert "Product" in schemas
        assert schemas["Product"]["type"] == "object"
        assert "properties" in schemas["Product"]


# ---------------------------------------------------------------------------
# 5. Entity fields mapped to correct JSON Schema types
# ---------------------------------------------------------------------------


class TestFieldTypeMapping:
    """Domain field types must be converted to correct JSON Schema types."""

    @pytest.mark.parametrize(
        "domain_type, expected_schema",
        [
            ("string", {"type": "string"}),
            ("str", {"type": "string"}),
            ("int", {"type": "integer"}),
            ("integer", {"type": "integer"}),
            ("float", {"type": "number"}),
            ("number", {"type": "number"}),
            ("bool", {"type": "boolean"}),
            ("boolean", {"type": "boolean"}),
            ("date", {"type": "string", "format": "date"}),
            ("datetime", {"type": "string", "format": "date-time"}),
            ("uuid", {"type": "string", "format": "uuid"}),
            ("email", {"type": "string", "format": "email"}),
        ],
    )
    def test_field_type_mapping(
        self, domain_type: str, expected_schema: dict
    ) -> None:
        """Each domain type string must map to the correct JSON Schema fragment."""
        entity = _entity(
            "Widget",
            fields=[_field("some_field", domain_type)],
        )
        sm = _service_map(_service("svc", owns_entities=["Widget"]))
        dm = _domain_model(entities=[entity])

        specs = generate_contract_stubs(sm, dm)
        field_schema = specs[0]["components"]["schemas"]["Widget"]["properties"]["some_field"]

        for key, value in expected_schema.items():
            assert field_schema[key] == value, (
                f"For domain type '{domain_type}': expected {key}={value}, "
                f"got {field_schema.get(key)}"
            )


# ---------------------------------------------------------------------------
# 6. Entity pluralization (User -> users)
# ---------------------------------------------------------------------------


class TestPluralization:
    """Entity names must be pluralized for URL path segments."""

    def test_user_becomes_users(self) -> None:
        """'User' should produce path /api/users."""
        sm = _service_map(_service("svc", owns_entities=["User"]))
        dm = _domain_model(entities=[_entity("User")])

        specs = generate_contract_stubs(sm, dm)
        paths = specs[0]["paths"]

        assert "/api/users" in paths

    def test_entity_ending_in_s_is_not_double_pluralized(self) -> None:
        """An entity already ending in 's' (e.g. 'Address') should not get
        an extra 's' appended -- the naive pluralizer just keeps it as-is."""
        sm = _service_map(_service("svc", owns_entities=["Address"]))
        dm = _domain_model(entities=[_entity("Address")])

        specs = generate_contract_stubs(sm, dm)
        paths = specs[0]["paths"]

        # _camel_to_kebab("Address") -> "address", _pluralize("address") -> "address" (ends in 's')
        assert "/api/address" in paths
        assert "/api/addresss" not in paths


# ---------------------------------------------------------------------------
# 7. CamelCase to kebab-case conversion (OrderItem -> order-items)
# ---------------------------------------------------------------------------


class TestCamelToKebab:
    """CamelCase entity names must be converted to kebab-case path segments."""

    def test_order_item_becomes_order_items(self) -> None:
        """'OrderItem' should produce path /api/order-items."""
        sm = _service_map(_service("svc", owns_entities=["OrderItem"]))
        dm = _domain_model(entities=[_entity("OrderItem")])

        specs = generate_contract_stubs(sm, dm)
        paths = specs[0]["paths"]

        assert "/api/order-items" in paths
        assert "/api/order-items/{id}" in paths

    def test_single_word_entity_lowercased(self) -> None:
        """'Product' should become 'products' (lowercased and pluralized)."""
        sm = _service_map(_service("svc", owns_entities=["Product"]))
        dm = _domain_model(entities=[_entity("Product")])

        specs = generate_contract_stubs(sm, dm)
        paths = specs[0]["paths"]

        assert "/api/products" in paths


# ---------------------------------------------------------------------------
# 8. Service with no owned entities generates minimal spec
# ---------------------------------------------------------------------------


class TestNoOwnedEntities:
    """A service with zero entities should still produce a valid spec."""

    def test_minimal_spec_has_health_endpoint(self) -> None:
        """The minimal spec should contain a /health path and no schemas."""
        sm = _service_map(_service("gateway-svc", owns_entities=[]))
        dm = _domain_model()

        specs = generate_contract_stubs(sm, dm)

        assert len(specs) == 1
        spec = specs[0]
        assert spec["openapi"] == "3.1.0"
        assert "/health" in spec["paths"]
        assert "get" in spec["paths"]["/health"]
        # No entity-derived schemas expected
        assert spec["components"]["schemas"] == {}


# ---------------------------------------------------------------------------
# 9. Entity not found in domain model generates minimal schema
# ---------------------------------------------------------------------------


class TestEntityNotInDomainModel:
    """When an owned entity is not present in the domain model, the generator
    should still produce CRUD paths and a minimal schema with just an 'id' field."""

    def test_missing_entity_produces_id_only_schema(self) -> None:
        """If 'Ghost' is in owns_entities but not in the domain model,
        the schema should contain only an 'id' property."""
        sm = _service_map(_service("svc", owns_entities=["Ghost"]))
        dm = _domain_model(entities=[])  # No entities at all

        specs = generate_contract_stubs(sm, dm)
        schema = specs[0]["components"]["schemas"]["Ghost"]

        assert "id" in schema["properties"]
        assert schema["properties"]["id"]["type"] == "string"
        assert schema["properties"]["id"]["format"] == "uuid"
        # Only 'id' should be present since entity was not found
        assert len(schema["properties"]) == 1
        assert schema["required"] == ["id"]


# ---------------------------------------------------------------------------
# 10. Required fields correctly identified in schema
# ---------------------------------------------------------------------------


class TestRequiredFields:
    """Fields marked as required in the domain model must appear in the
    schema's 'required' array; optional fields must not."""

    def test_required_and_optional_fields(self) -> None:
        """Given a mix of required and optional fields, the schema 'required'
        list should include 'id' plus only the required domain fields."""
        entity = _entity(
            "Invoice",
            fields=[
                _field("amount", "float", required=True),
                _field("currency", "string", required=True),
                _field("notes", "string", required=False),
                _field("due_date", "date", required=False),
            ],
        )
        sm = _service_map(_service("billing-svc", owns_entities=["Invoice"]))
        dm = _domain_model(entities=[entity])

        specs = generate_contract_stubs(sm, dm)
        schema = specs[0]["components"]["schemas"]["Invoice"]

        required = schema["required"]
        assert "id" in required
        assert "amount" in required
        assert "currency" in required
        assert "notes" not in required
        assert "due_date" not in required

    def test_all_fields_required(self) -> None:
        """When every field is required, every field name (plus 'id') must
        appear in the required list."""
        entity = _entity(
            "Token",
            fields=[
                _field("value", "string", required=True),
                _field("expires_at", "datetime", required=True),
            ],
        )
        sm = _service_map(_service("auth-svc", owns_entities=["Token"]))
        dm = _domain_model(entities=[entity])

        specs = generate_contract_stubs(sm, dm)
        schema = specs[0]["components"]["schemas"]["Token"]

        required = schema["required"]
        assert set(required) == {"id", "value", "expires_at"}

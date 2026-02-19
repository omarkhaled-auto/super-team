"""Tests for SchemaRegistry service."""
import os
import tempfile

import pytest

from src.contract_engine.services.schema_registry import SchemaRegistry
from src.shared.db.connection import ConnectionPool
from src.shared.db.schema import init_contracts_db
from src.shared.errors import NotFoundError


@pytest.fixture
def pool():
    tmpdir = tempfile.mkdtemp()
    p = ConnectionPool(os.path.join(tmpdir, "test.db"))
    init_contracts_db(p)
    yield p
    p.close()


class TestSchemaRegistry:
    """Tests for the SchemaRegistry class."""

    def test_register_schema_new(self, pool):
        """Registering a new schema creates it and returns a SharedSchema."""
        registry = SchemaRegistry(pool)

        result = registry.register_schema(
            name="UserProfile",
            schema={"type": "object", "properties": {"name": {"type": "string"}}},
            owning_service="user-svc",
        )

        assert result.name == "UserProfile"
        assert result.schema_def == {"type": "object", "properties": {"name": {"type": "string"}}}
        assert result.owning_service == "user-svc"
        assert result.consuming_services == []

    def test_register_schema_update(self, pool):
        """Re-registering an existing schema name updates it (upsert)."""
        registry = SchemaRegistry(pool)

        registry.register_schema(
            name="UserProfile",
            schema={"type": "object", "properties": {"name": {"type": "string"}}},
            owning_service="user-svc",
        )

        # Update with new schema content and different owning service
        updated = registry.register_schema(
            name="UserProfile",
            schema={"type": "object", "properties": {"name": {"type": "string"}, "email": {"type": "string"}}},
            owning_service="auth-svc",
        )

        assert updated.name == "UserProfile"
        assert "email" in updated.schema_def["properties"]
        assert updated.owning_service == "auth-svc"

    def test_get_schema_found(self, pool):
        """Retrieving a registered schema returns the correct SharedSchema."""
        registry = SchemaRegistry(pool)

        registry.register_schema(
            name="OrderItem",
            schema={"type": "object", "properties": {"quantity": {"type": "integer"}}},
            owning_service="order-svc",
        )

        result = registry.get_schema("OrderItem")

        assert result.name == "OrderItem"
        assert result.schema_def["properties"]["quantity"]["type"] == "integer"
        assert result.owning_service == "order-svc"

    def test_get_schema_not_found(self, pool):
        """Retrieving a non-existent schema raises NotFoundError."""
        registry = SchemaRegistry(pool)

        with pytest.raises(NotFoundError) as exc_info:
            registry.get_schema("NonExistent")

        assert "NonExistent" in str(exc_info.value)

    def test_list_schemas_all(self, pool):
        """Listing all schemas returns every registered schema."""
        registry = SchemaRegistry(pool)

        registry.register_schema(
            name="Alpha",
            schema={"type": "string"},
            owning_service="svc-a",
        )
        registry.register_schema(
            name="Beta",
            schema={"type": "integer"},
            owning_service="svc-b",
        )
        registry.register_schema(
            name="Gamma",
            schema={"type": "boolean"},
            owning_service="svc-a",
        )

        results = registry.list_schemas()

        assert len(results) == 3
        names = [s.name for s in results]
        # list_schemas orders by name
        assert names == ["Alpha", "Beta", "Gamma"]

    def test_list_schemas_filter_owner(self, pool):
        """Listing schemas with owning_service filter returns only matching schemas."""
        registry = SchemaRegistry(pool)

        registry.register_schema(
            name="Alpha",
            schema={"type": "string"},
            owning_service="svc-a",
        )
        registry.register_schema(
            name="Beta",
            schema={"type": "integer"},
            owning_service="svc-b",
        )
        registry.register_schema(
            name="Gamma",
            schema={"type": "boolean"},
            owning_service="svc-a",
        )

        results = registry.list_schemas(owning_service="svc-a")

        assert len(results) == 2
        names = {s.name for s in results}
        assert names == {"Alpha", "Gamma"}

    def test_add_consumer(self, pool):
        """Adding a consumer to a schema records it correctly."""
        registry = SchemaRegistry(pool)

        registry.register_schema(
            name="UserProfile",
            schema={"type": "object"},
            owning_service="user-svc",
        )

        registry.add_consumer("UserProfile", "frontend-svc")

        consumers = registry.get_consumers("UserProfile")
        assert consumers == ["frontend-svc"]

    def test_get_consumers(self, pool):
        """Getting consumers returns all registered consumers sorted by name."""
        registry = SchemaRegistry(pool)

        registry.register_schema(
            name="UserProfile",
            schema={"type": "object"},
            owning_service="user-svc",
        )

        registry.add_consumer("UserProfile", "frontend-svc")
        registry.add_consumer("UserProfile", "analytics-svc")
        registry.add_consumer("UserProfile", "mobile-svc")

        consumers = registry.get_consumers("UserProfile")

        assert len(consumers) == 3
        # Should be sorted alphabetically
        assert consumers == ["analytics-svc", "frontend-svc", "mobile-svc"]

    def test_add_consumer_idempotent(self, pool):
        """Adding the same consumer twice is a no-op (INSERT OR IGNORE)."""
        registry = SchemaRegistry(pool)

        registry.register_schema(
            name="UserProfile",
            schema={"type": "object"},
            owning_service="user-svc",
        )

        registry.add_consumer("UserProfile", "frontend-svc")
        registry.add_consumer("UserProfile", "frontend-svc")  # duplicate

        consumers = registry.get_consumers("UserProfile")
        assert consumers == ["frontend-svc"]


class TestSharedSchemaModel:
    """Tests for the SharedSchema model schema_def field."""

    def test_shared_schema_uses_schema_def(self):
        """SharedSchema should use schema_def field, not schema."""
        from src.shared.models.contracts import SharedSchema

        s = SharedSchema(
            name="test",
            schema_def={"type": "object", "properties": {"id": {"type": "string"}}},
            owning_service="test-svc",
        )
        assert s.schema_def == {"type": "object", "properties": {"id": {"type": "string"}}}
        # Ensure 'schema' is NOT a model field
        assert "schema" not in SharedSchema.model_fields

    def test_shared_schema_schema_def_round_trip(self):
        """SharedSchema.schema_def should survive model_dump round trip."""
        from src.shared.models.contracts import SharedSchema

        schema_data = {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "age": {"type": "integer"},
            },
            "required": ["name"],
        }
        s = SharedSchema(
            name="UserProfile",
            schema_def=schema_data,
            owning_service="user-svc",
        )
        dumped = s.model_dump()
        assert dumped["schema_def"] == schema_data
        assert "schema" not in dumped or dumped.get("schema") is None

    def test_shared_schema_empty_schema_def(self):
        """SharedSchema should accept an empty dict for schema_def."""
        from src.shared.models.contracts import SharedSchema

        s = SharedSchema(
            name="empty",
            schema_def={},
            owning_service="svc",
        )
        assert s.schema_def == {}

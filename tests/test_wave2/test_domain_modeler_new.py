"""Wave 2 tests for domain modeler enhancements.

Tests state machine detection without status fields, entity field population,
and relationship type diversity in the domain model.
"""
from __future__ import annotations

import pytest

from src.architect.services.domain_modeler import build_domain_model
from src.architect.services.prd_parser import ParsedPRD
from src.architect.services.service_boundary import ServiceBoundary
from src.shared.models.architect import RelationshipType


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _entity(
    name: str,
    fields: list[dict] | None = None,
    description: str = "",
) -> dict:
    """Shorthand for creating a raw entity dict."""
    return {
        "name": name,
        "description": description or f"{name} entity",
        "fields": fields or [],
        "owning_context": None,
    }


def _boundary(name: str, entities: list[str]) -> ServiceBoundary:
    """Shorthand for creating a ServiceBoundary."""
    return ServiceBoundary(
        name=name,
        domain=name.lower().replace(" ", "-"),
        description=f"Boundary for {name}",
        entities=list(entities),
    )


# ---------------------------------------------------------------------------
# 1. Entity fields populated
# ---------------------------------------------------------------------------


class TestEntityFieldPopulation:
    """Entities with populated fields produce DomainEntity.fields."""

    def test_entity_fields_not_empty(self):
        """When parsed entity has fields, DomainEntity.fields is populated."""
        parsed = ParsedPRD(
            project_name="Test",
            entities=[
                _entity("Invoice", fields=[
                    {"name": "id", "type": "UUID", "required": True},
                    {"name": "amount", "type": "float", "required": True},
                    {"name": "status", "type": "str", "required": True},
                ]),
            ],
        )
        boundaries = [_boundary("Billing", ["Invoice"])]
        model = build_domain_model(parsed, boundaries)

        assert len(model.entities) == 1
        entity = model.entities[0]
        assert len(entity.fields) == 3
        field_names = {f.name for f in entity.fields}
        assert "id" in field_names
        assert "amount" in field_names
        assert "status" in field_names

    def test_entity_fields_types_preserved(self):
        """Field types are preserved from the parsed entity."""
        parsed = ParsedPRD(
            project_name="Test",
            entities=[
                _entity("User", fields=[
                    {"name": "email", "type": "str", "required": True},
                    {"name": "age", "type": "int", "required": False},
                ]),
            ],
        )
        boundaries = [_boundary("Users", ["User"])]
        model = build_domain_model(parsed, boundaries)

        entity = model.entities[0]
        type_map = {f.name: f.type for f in entity.fields}
        assert type_map["email"] == "str"
        assert type_map["age"] == "int"

    def test_entity_without_fields_has_empty_fields(self):
        """An entity with no fields results in an empty fields list."""
        parsed = ParsedPRD(
            project_name="Test",
            entities=[_entity("Tag")],
        )
        boundaries = [_boundary("Tags", ["Tag"])]
        model = build_domain_model(parsed, boundaries)

        entity = model.entities[0]
        assert entity.fields == []


# ---------------------------------------------------------------------------
# 2. State machine detection without status field
# ---------------------------------------------------------------------------


class TestStateMachineWithoutStatusField:
    """State machines are detected even when the entity has no 'status' field."""

    def test_state_machine_from_parsed_data_no_status_field(self):
        """An entity with no 'status' field but with parsed state_machines gets a state machine."""
        parsed = ParsedPRD(
            project_name="Test",
            entities=[
                # Invoice has NO status field at all
                _entity("Invoice", fields=[
                    {"name": "id", "type": "UUID", "required": True},
                    {"name": "amount", "type": "float", "required": True},
                ]),
            ],
            state_machines=[
                {
                    "entity": "Invoice",
                    "states": ["draft", "submitted", "approved", "paid"],
                    "transitions": [
                        {"from_state": "draft", "to_state": "submitted", "trigger": "submit"},
                        {"from_state": "submitted", "to_state": "approved", "trigger": "approve"},
                        {"from_state": "approved", "to_state": "paid", "trigger": "mark_paid"},
                    ],
                },
            ],
        )
        boundaries = [_boundary("Billing", ["Invoice"])]
        model = build_domain_model(parsed, boundaries)

        entity = model.entities[0]
        assert entity.state_machine is not None
        assert "draft" in entity.state_machine.states
        assert "paid" in entity.state_machine.states
        assert len(entity.state_machine.transitions) == 3

    def test_state_machine_from_status_field(self):
        """An entity WITH a status field still gets a default state machine."""
        parsed = ParsedPRD(
            project_name="Test",
            entities=[
                _entity("Task", fields=[
                    {"name": "id", "type": "UUID", "required": True},
                    {"name": "status", "type": "str", "required": True},
                ]),
            ],
        )
        boundaries = [_boundary("Tasks", ["Task"])]
        model = build_domain_model(parsed, boundaries)

        entity = model.entities[0]
        assert entity.state_machine is not None

    def test_no_state_machine_without_evidence(self):
        """An entity with no status field AND no parsed state_machines gets None."""
        parsed = ParsedPRD(
            project_name="Test",
            entities=[
                _entity("Product", fields=[
                    {"name": "id", "type": "UUID"},
                    {"name": "name", "type": "str"},
                ]),
            ],
        )
        boundaries = [_boundary("Catalog", ["Product"])]
        model = build_domain_model(parsed, boundaries)

        entity = model.entities[0]
        assert entity.state_machine is None

    def test_parsed_state_machine_takes_priority_over_default(self):
        """When both parsed state_machines and a status field exist, parsed data wins."""
        parsed = ParsedPRD(
            project_name="Test",
            entities=[
                _entity("Order", fields=[
                    {"name": "status", "type": "str"},
                ]),
            ],
            state_machines=[
                {
                    "entity": "Order",
                    "states": ["pending", "confirmed", "shipped", "delivered"],
                    "transitions": [
                        {"from_state": "pending", "to_state": "confirmed", "trigger": "confirm"},
                        {"from_state": "confirmed", "to_state": "shipped", "trigger": "ship"},
                    ],
                },
            ],
        )
        boundaries = [_boundary("Orders", ["Order"])]
        model = build_domain_model(parsed, boundaries)

        entity = model.entities[0]
        assert entity.state_machine is not None
        # Should use the explicit states, not the default active/inactive
        assert "pending" in entity.state_machine.states
        assert "delivered" in entity.state_machine.states

    def test_empty_fields_entity_with_state_machine(self):
        """An entity with zero fields but with parsed state machine data still gets a state machine."""
        parsed = ParsedPRD(
            project_name="Test",
            entities=[
                _entity("Workflow", fields=[]),
            ],
            state_machines=[
                {
                    "entity": "Workflow",
                    "states": ["created", "running", "completed"],
                    "transitions": [],
                },
            ],
        )
        boundaries = [_boundary("Workflows", ["Workflow"])]
        model = build_domain_model(parsed, boundaries)

        entity = model.entities[0]
        assert entity.state_machine is not None
        assert "created" in entity.state_machine.states


# ---------------------------------------------------------------------------
# 3. Relationship type diversity
# ---------------------------------------------------------------------------


class TestRelationshipTypeDiversity:
    """Domain model relationships have diverse types (not all OWNS)."""

    def test_owns_relationship_mapped(self):
        """OWNS raw type maps to RelationshipType.OWNS."""
        parsed = ParsedPRD(
            project_name="Test",
            entities=[_entity("Order"), _entity("LineItem")],
            relationships=[
                {"source": "Order", "target": "LineItem", "type": "OWNS", "cardinality": "1:N"},
            ],
        )
        boundaries = [_boundary("Orders", ["Order", "LineItem"])]
        model = build_domain_model(parsed, boundaries)

        assert len(model.relationships) == 1
        assert model.relationships[0].relationship_type == RelationshipType.OWNS

    def test_references_relationship_mapped(self):
        """REFERENCES raw type maps to RelationshipType.REFERENCES."""
        parsed = ParsedPRD(
            project_name="Test",
            entities=[_entity("Order"), _entity("Product")],
            relationships=[
                {"source": "Order", "target": "Product", "type": "REFERENCES", "cardinality": "N:1"},
            ],
        )
        boundaries = [_boundary("Shop", ["Order", "Product"])]
        model = build_domain_model(parsed, boundaries)

        assert len(model.relationships) == 1
        assert model.relationships[0].relationship_type == RelationshipType.REFERENCES

    def test_triggers_relationship_mapped(self):
        """TRIGGERS raw type maps to RelationshipType.TRIGGERS."""
        parsed = ParsedPRD(
            project_name="Test",
            entities=[_entity("Payment"), _entity("Notification")],
            relationships=[
                {"source": "Payment", "target": "Notification", "type": "TRIGGERS", "cardinality": "1:N"},
            ],
        )
        boundaries = [_boundary("Payments", ["Payment", "Notification"])]
        model = build_domain_model(parsed, boundaries)

        assert len(model.relationships) == 1
        assert model.relationships[0].relationship_type == RelationshipType.TRIGGERS

    def test_has_many_relationship_mapped(self):
        """HAS_MANY raw type maps to RelationshipType.HAS_MANY."""
        parsed = ParsedPRD(
            project_name="Test",
            entities=[_entity("Customer"), _entity("Address")],
            relationships=[
                {"source": "Customer", "target": "Address", "type": "HAS_MANY", "cardinality": "1:N"},
            ],
        )
        boundaries = [_boundary("Customers", ["Customer", "Address"])]
        model = build_domain_model(parsed, boundaries)

        assert len(model.relationships) == 1
        assert model.relationships[0].relationship_type == RelationshipType.HAS_MANY

    def test_belongs_to_relationship_mapped(self):
        """BELONGS_TO raw type maps to RelationshipType.BELONGS_TO."""
        parsed = ParsedPRD(
            project_name="Test",
            entities=[_entity("Comment"), _entity("Post")],
            relationships=[
                {"source": "Comment", "target": "Post", "type": "BELONGS_TO", "cardinality": "N:1"},
            ],
        )
        boundaries = [_boundary("Blog", ["Comment", "Post"])]
        model = build_domain_model(parsed, boundaries)

        assert len(model.relationships) == 1
        assert model.relationships[0].relationship_type == RelationshipType.BELONGS_TO

    def test_depends_on_relationship_mapped(self):
        """DEPENDS_ON raw type maps to RelationshipType.DEPENDS_ON."""
        parsed = ParsedPRD(
            project_name="Test",
            entities=[_entity("Deployment"), _entity("Config")],
            relationships=[
                {"source": "Deployment", "target": "Config", "type": "DEPENDS_ON", "cardinality": "N:1"},
            ],
        )
        boundaries = [_boundary("Ops", ["Deployment", "Config"])]
        model = build_domain_model(parsed, boundaries)

        assert len(model.relationships) == 1
        assert model.relationships[0].relationship_type == RelationshipType.DEPENDS_ON

    def test_mixed_relationship_types_in_model(self):
        """Domain model can contain multiple different relationship types."""
        parsed = ParsedPRD(
            project_name="Test",
            entities=[
                _entity("Order"),
                _entity("LineItem"),
                _entity("Product"),
                _entity("Notification"),
            ],
            relationships=[
                {"source": "Order", "target": "LineItem", "type": "OWNS", "cardinality": "1:N"},
                {"source": "Order", "target": "Product", "type": "REFERENCES", "cardinality": "N:1"},
                {"source": "Order", "target": "Notification", "type": "TRIGGERS", "cardinality": "1:N"},
            ],
        )
        boundaries = [_boundary("Shop", ["Order", "LineItem", "Product", "Notification"])]
        model = build_domain_model(parsed, boundaries)

        types = {r.relationship_type for r in model.relationships}
        assert RelationshipType.OWNS in types
        assert RelationshipType.REFERENCES in types
        assert RelationshipType.TRIGGERS in types


# ---------------------------------------------------------------------------
# 4. All entities present in domain model
# ---------------------------------------------------------------------------


class TestAllEntitiesPresent:
    """Every entity from the parsed PRD appears in the domain model."""

    def test_all_entities_in_domain_model(self):
        """All parsed entities show up as DomainEntity instances."""
        parsed = ParsedPRD(
            project_name="Test",
            entities=[
                _entity("User"),
                _entity("Invoice"),
                _entity("Payment"),
                _entity("AuditLog"),
            ],
        )
        boundaries = [_boundary("All", ["User", "Invoice", "Payment", "AuditLog"])]
        model = build_domain_model(parsed, boundaries)

        model_names = {e.name for e in model.entities}
        assert model_names == {"User", "Invoice", "Payment", "AuditLog"}

    def test_invalid_relationships_skipped(self):
        """Relationships referencing non-existent entities are skipped."""
        parsed = ParsedPRD(
            project_name="Test",
            entities=[_entity("User")],
            relationships=[
                {"source": "User", "target": "Nonexistent", "type": "OWNS", "cardinality": "1:N"},
            ],
        )
        boundaries = [_boundary("Users", ["User"])]
        model = build_domain_model(parsed, boundaries)

        # The relationship should be skipped (Nonexistent is not in entities)
        assert len(model.relationships) == 0

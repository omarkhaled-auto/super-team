"""Tests for the domain modeler service.

Covers ``build_domain_model`` which converts parsed PRD data and service
boundaries into a fully-typed ``DomainModel`` containing ``DomainEntity``
and ``DomainRelationship`` instances, with state machine detection.
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
# Tests
# ---------------------------------------------------------------------------


class TestBasicEntityConversion:
    """Parsed entity dicts are converted to DomainEntity instances."""

    def test_entity_name_and_description_are_preserved(self):
        """The name and description from the raw entity dict appear verbatim
        on the resulting DomainEntity."""
        parsed = ParsedPRD(
            project_name="Test",
            entities=[_entity("User", description="A registered user")],
        )
        boundaries = [_boundary("UserService", ["User"])]

        model = build_domain_model(parsed, boundaries)

        assert len(model.entities) == 1
        entity = model.entities[0]
        assert entity.name == "User"
        assert entity.description == "A registered user"

    def test_entity_fields_are_converted(self):
        """Fields from the raw entity dict are converted to EntityField
        objects with correct name, type, and required flag."""
        parsed = ParsedPRD(
            project_name="Test",
            entities=[
                _entity(
                    "Product",
                    fields=[
                        {"name": "id", "type": "UUID", "required": True},
                        {"name": "title", "type": "string", "required": False, "description": "Product title"},
                    ],
                )
            ],
        )
        boundaries = [_boundary("Catalog", ["Product"])]

        model = build_domain_model(parsed, boundaries)

        entity = model.entities[0]
        assert len(entity.fields) == 2
        assert entity.fields[0].name == "id"
        assert entity.fields[0].type == "UUID"
        assert entity.fields[0].required is True
        assert entity.fields[1].name == "title"
        assert entity.fields[1].required is False


class TestStateMachineDetectionWithParsedData:
    """State machine detection when parsed.state_machines has matching data."""

    def test_state_machine_from_parsed_state_machines(self):
        """When an entity has a 'status' field AND parsed.state_machines
        contains a matching entry for that entity, the state machine is
        built from the parsed data (not the default)."""
        parsed = ParsedPRD(
            project_name="Test",
            entities=[
                _entity(
                    "Order",
                    fields=[
                        {"name": "id", "type": "UUID"},
                        {"name": "status", "type": "string"},
                    ],
                )
            ],
            state_machines=[
                {
                    "entity": "Order",
                    "states": ["pending", "confirmed", "shipped", "delivered"],
                    "initial_state": "pending",
                    "transitions": [
                        {"from_state": "pending", "to_state": "confirmed", "trigger": "confirm"},
                        {"from_state": "confirmed", "to_state": "shipped", "trigger": "ship"},
                        {"from_state": "shipped", "to_state": "delivered", "trigger": "deliver"},
                    ],
                }
            ],
        )
        boundaries = [_boundary("OrderService", ["Order"])]

        model = build_domain_model(parsed, boundaries)
        sm = model.entities[0].state_machine

        assert sm is not None
        assert sm.states == ["pending", "confirmed", "shipped", "delivered"]
        assert sm.initial_state == "pending"
        assert len(sm.transitions) == 3
        assert sm.transitions[0].from_state == "pending"
        assert sm.transitions[0].to_state == "confirmed"
        assert sm.transitions[0].trigger == "confirm"


class TestStateMachineDefaultCreation:
    """Default state machine when a status field exists but no parsed data."""

    def test_default_state_machine_created(self):
        """When an entity has a 'status' field but parsed.state_machines has
        no matching entry, a default state machine with ['active', 'inactive']
        is created."""
        parsed = ParsedPRD(
            project_name="Test",
            entities=[
                _entity(
                    "Task",
                    fields=[
                        {"name": "id", "type": "UUID"},
                        {"name": "status", "type": "string"},
                    ],
                )
            ],
            state_machines=[],  # No matching state machine data
        )
        boundaries = [_boundary("TaskService", ["Task"])]

        model = build_domain_model(parsed, boundaries)
        sm = model.entities[0].state_machine

        assert sm is not None
        assert sm.states == ["active", "inactive"]
        assert sm.initial_state == "active"
        assert len(sm.transitions) == 1
        assert sm.transitions[0].from_state == "active"
        assert sm.transitions[0].to_state == "inactive"
        assert sm.transitions[0].trigger == "transition_to_inactive"

    def test_other_state_field_names_trigger_detection(self):
        """Fields named 'state', 'phase', 'lifecycle', or 'workflow_state'
        also trigger state machine detection."""
        for field_name in ["state", "phase", "lifecycle", "workflow_state"]:
            parsed = ParsedPRD(
                project_name="Test",
                entities=[
                    _entity(
                        "Item",
                        fields=[{"name": field_name, "type": "string"}],
                    )
                ],
            )
            boundaries = [_boundary("ItemService", ["Item"])]

            model = build_domain_model(parsed, boundaries)
            sm = model.entities[0].state_machine

            assert sm is not None, (
                f"Expected state machine for field name '{field_name}'"
            )


class TestNoStateMachineWithoutStatusField:
    """No state machine when the entity has no status-like field."""

    def test_no_state_machine_without_status_field(self):
        """An entity whose fields do not include any state-related name
        (status, state, phase, etc.) gets state_machine=None."""
        parsed = ParsedPRD(
            project_name="Test",
            entities=[
                _entity(
                    "Address",
                    fields=[
                        {"name": "street", "type": "string"},
                        {"name": "city", "type": "string"},
                        {"name": "zip_code", "type": "string"},
                    ],
                )
            ],
        )
        boundaries = [_boundary("GeoService", ["Address"])]

        model = build_domain_model(parsed, boundaries)

        assert model.entities[0].state_machine is None


class TestOwningServiceFromBoundaries:
    """Owning service is resolved from the provided service boundaries."""

    def test_owning_service_matches_boundary_name(self):
        """Each DomainEntity's owning_service equals the name of the
        ServiceBoundary that lists that entity."""
        parsed = ParsedPRD(
            project_name="Test",
            entities=[
                _entity("User"),
                _entity("Order"),
            ],
        )
        boundaries = [
            _boundary("Auth", ["User"]),
            _boundary("Commerce", ["Order"]),
        ]

        model = build_domain_model(parsed, boundaries)

        user_entity = next(e for e in model.entities if e.name == "User")
        order_entity = next(e for e in model.entities if e.name == "Order")

        assert user_entity.owning_service == "Auth"
        assert order_entity.owning_service == "Commerce"


class TestUnassignedEntitiesOwningService:
    """Entities not in any boundary get 'unassigned' as owning_service."""

    def test_unassigned_entity_gets_unassigned_service(self):
        """When an entity does not appear in any boundary's entities list,
        its owning_service defaults to 'unassigned'."""
        parsed = ParsedPRD(
            project_name="Test",
            entities=[
                _entity("User"),
                _entity("Orphan"),
            ],
        )
        # Only User is assigned; Orphan is not in any boundary.
        boundaries = [_boundary("Auth", ["User"])]

        model = build_domain_model(parsed, boundaries)

        orphan_entity = next(e for e in model.entities if e.name == "Orphan")
        assert orphan_entity.owning_service == "unassigned"


class TestRelationshipConversion:
    """Valid relationships are converted to DomainRelationship instances."""

    def test_relationship_with_valid_entities(self):
        """A relationship whose source and target both exist in the parsed
        entities is converted into a DomainRelationship with the correct
        type and cardinality."""
        parsed = ParsedPRD(
            project_name="Test",
            entities=[_entity("User"), _entity("Order")],
            relationships=[
                {
                    "source": "User",
                    "target": "Order",
                    "type": "OWNS",
                    "cardinality": "1:N",
                    "description": "User places orders",
                }
            ],
        )
        boundaries = [_boundary("Main", ["User", "Order"])]

        model = build_domain_model(parsed, boundaries)

        assert len(model.relationships) == 1
        rel = model.relationships[0]
        assert rel.source_entity == "User"
        assert rel.target_entity == "Order"
        assert rel.relationship_type == RelationshipType.OWNS
        assert rel.cardinality == "1:N"
        assert rel.description == "User places orders"

    def test_multiple_relationship_types(self):
        """Different relationship type strings are mapped to the correct
        RelationshipType enum values."""
        parsed = ParsedPRD(
            project_name="Test",
            entities=[_entity("A"), _entity("B")],
            relationships=[
                {"source": "A", "target": "B", "type": "references"},
                {"source": "B", "target": "A", "type": "triggers"},
            ],
        )
        boundaries = [_boundary("Main", ["A", "B"])]

        model = build_domain_model(parsed, boundaries)

        assert len(model.relationships) == 2
        types = {r.relationship_type for r in model.relationships}
        assert RelationshipType.REFERENCES in types
        assert RelationshipType.TRIGGERS in types


class TestRelationshipsWithNonExistentEntities:
    """Relationships referencing unknown entities are silently skipped."""

    def test_relationship_with_nonexistent_source_is_skipped(self):
        """A relationship whose source entity does not exist in the parsed
        entities list is not included in the domain model."""
        parsed = ParsedPRD(
            project_name="Test",
            entities=[_entity("Order")],
            relationships=[
                {
                    "source": "Ghost",
                    "target": "Order",
                    "type": "OWNS",
                }
            ],
        )
        boundaries = [_boundary("Main", ["Order"])]

        model = build_domain_model(parsed, boundaries)
        assert len(model.relationships) == 0

    def test_relationship_with_nonexistent_target_is_skipped(self):
        """A relationship whose target entity does not exist in the parsed
        entities list is not included in the domain model."""
        parsed = ParsedPRD(
            project_name="Test",
            entities=[_entity("User")],
            relationships=[
                {
                    "source": "User",
                    "target": "Phantom",
                    "type": "REFERENCES",
                }
            ],
        )
        boundaries = [_boundary("Main", ["User"])]

        model = build_domain_model(parsed, boundaries)
        assert len(model.relationships) == 0

    def test_mix_of_valid_and_invalid_relationships(self):
        """When some relationships are valid and others reference
        non-existent entities, only the valid ones appear in the output."""
        parsed = ParsedPRD(
            project_name="Test",
            entities=[_entity("User"), _entity("Order")],
            relationships=[
                {"source": "User", "target": "Order", "type": "OWNS"},
                {"source": "User", "target": "Missing", "type": "REFERENCES"},
                {"source": "Ghost", "target": "Order", "type": "TRIGGERS"},
            ],
        )
        boundaries = [_boundary("Main", ["User", "Order"])]

        model = build_domain_model(parsed, boundaries)
        assert len(model.relationships) == 1
        assert model.relationships[0].source_entity == "User"
        assert model.relationships[0].target_entity == "Order"


class TestCardinalityNormalization:
    """Cardinality strings from parsed data are normalized to valid patterns."""

    def test_direct_valid_cardinality(self):
        """Standard cardinality strings are preserved as-is."""
        for card in ["1:1", "1:N", "N:1", "N:N"]:
            parsed = ParsedPRD(
                project_name="Test",
                entities=[_entity("A"), _entity("B")],
                relationships=[{
                    "source": "A", "target": "B",
                    "type": "OWNS", "cardinality": card,
                }],
            )
            boundaries = [_boundary("Main", ["A", "B"])]
            model = build_domain_model(parsed, boundaries)
            assert model.relationships[0].cardinality == card

    def test_prose_cardinality_one_to_many(self):
        """'one-to-many' is normalized to '1:N'."""
        parsed = ParsedPRD(
            project_name="Test",
            entities=[_entity("A"), _entity("B")],
            relationships=[{
                "source": "A", "target": "B",
                "type": "OWNS", "cardinality": "one-to-many",
            }],
        )
        boundaries = [_boundary("Main", ["A", "B"])]
        model = build_domain_model(parsed, boundaries)
        assert model.relationships[0].cardinality == "1:N"

    def test_prose_cardinality_many_to_many(self):
        """'many-to-many' is normalized to 'N:N'."""
        parsed = ParsedPRD(
            project_name="Test",
            entities=[_entity("A"), _entity("B")],
            relationships=[{
                "source": "A", "target": "B",
                "type": "references", "cardinality": "many-to-many",
            }],
        )
        boundaries = [_boundary("Main", ["A", "B"])]
        model = build_domain_model(parsed, boundaries)
        assert model.relationships[0].cardinality == "N:N"

    def test_invalid_cardinality_defaults_to_1_n(self):
        """Unrecognizable cardinality defaults to '1:N'."""
        parsed = ParsedPRD(
            project_name="Test",
            entities=[_entity("A"), _entity("B")],
            relationships=[{
                "source": "A", "target": "B",
                "type": "OWNS", "cardinality": "unknown-format",
            }],
        )
        boundaries = [_boundary("Main", ["A", "B"])]
        model = build_domain_model(parsed, boundaries)
        assert model.relationships[0].cardinality == "1:N"


class TestRelationshipTypeMapping:
    """Relationship type strings are mapped to correct enum values."""

    def test_owns_synonyms(self):
        """'owns', 'contains', 'has' all map to RelationshipType.OWNS."""
        for raw in ["owns", "contains", "has"]:
            parsed = ParsedPRD(
                project_name="Test",
                entities=[_entity("A"), _entity("B")],
                relationships=[{
                    "source": "A", "target": "B", "type": raw,
                }],
            )
            boundaries = [_boundary("Main", ["A", "B"])]
            model = build_domain_model(parsed, boundaries)
            assert model.relationships[0].relationship_type == RelationshipType.OWNS

    def test_references_synonyms(self):
        """'references', 'refers to' map to REFERENCES."""
        for raw in ["references", "refers to"]:
            parsed = ParsedPRD(
                project_name="Test",
                entities=[_entity("A"), _entity("B")],
                relationships=[{
                    "source": "A", "target": "B", "type": raw,
                }],
            )
            boundaries = [_boundary("Main", ["A", "B"])]
            model = build_domain_model(parsed, boundaries)
            assert model.relationships[0].relationship_type == RelationshipType.REFERENCES

    def test_belongs_to_synonyms(self):
        """'belongs to', 'belongs_to' map to BELONGS_TO."""
        for raw in ["belongs to", "belongs_to"]:
            parsed = ParsedPRD(
                project_name="Test",
                entities=[_entity("A"), _entity("B")],
                relationships=[{
                    "source": "A", "target": "B", "type": raw,
                }],
            )
            boundaries = [_boundary("Main", ["A", "B"])]
            model = build_domain_model(parsed, boundaries)
            assert model.relationships[0].relationship_type == RelationshipType.BELONGS_TO

    def test_triggers_synonyms(self):
        """'triggers', 'initiates', 'starts' map to TRIGGERS."""
        for raw in ["triggers", "initiates", "starts"]:
            parsed = ParsedPRD(
                project_name="Test",
                entities=[_entity("A"), _entity("B")],
                relationships=[{
                    "source": "A", "target": "B", "type": raw,
                }],
            )
            boundaries = [_boundary("Main", ["A", "B"])]
            model = build_domain_model(parsed, boundaries)
            assert model.relationships[0].relationship_type == RelationshipType.TRIGGERS

    def test_extends_synonyms(self):
        """'extends', 'inherits' map to EXTENDS."""
        for raw in ["extends", "inherits"]:
            parsed = ParsedPRD(
                project_name="Test",
                entities=[_entity("A"), _entity("B")],
                relationships=[{
                    "source": "A", "target": "B", "type": raw,
                }],
            )
            boundaries = [_boundary("Main", ["A", "B"])]
            model = build_domain_model(parsed, boundaries)
            assert model.relationships[0].relationship_type == RelationshipType.EXTENDS

    def test_depends_on_synonyms(self):
        """'depends on', 'requires', 'uses' map to DEPENDS_ON."""
        for raw in ["depends on", "requires", "uses"]:
            parsed = ParsedPRD(
                project_name="Test",
                entities=[_entity("A"), _entity("B")],
                relationships=[{
                    "source": "A", "target": "B", "type": raw,
                }],
            )
            boundaries = [_boundary("Main", ["A", "B"])]
            model = build_domain_model(parsed, boundaries)
            assert model.relationships[0].relationship_type == RelationshipType.DEPENDS_ON

    def test_unknown_type_defaults_to_references(self):
        """An unrecognized type string defaults to REFERENCES."""
        parsed = ParsedPRD(
            project_name="Test",
            entities=[_entity("A"), _entity("B")],
            relationships=[{
                "source": "A", "target": "B", "type": "custom-unknown",
            }],
        )
        boundaries = [_boundary("Main", ["A", "B"])]
        model = build_domain_model(parsed, boundaries)
        assert model.relationships[0].relationship_type == RelationshipType.REFERENCES


class TestStateMachineInference:
    """State machine transitions are inferred when parsed data has states but no transitions."""

    def test_inferred_sequential_transitions(self):
        """When parsed data has states but no transitions, sequential transitions
        are inferred."""
        parsed = ParsedPRD(
            project_name="Test",
            entities=[_entity("Order", fields=[{"name": "status", "type": "string"}])],
            state_machines=[{
                "entity": "Order",
                "states": ["draft", "active", "closed"],
            }],
        )
        boundaries = [_boundary("Main", ["Order"])]
        model = build_domain_model(parsed, boundaries)

        sm = model.entities[0].state_machine
        assert sm is not None
        assert sm.states == ["draft", "active", "closed"]
        assert sm.initial_state == "draft"
        assert len(sm.transitions) == 2
        assert sm.transitions[0].from_state == "draft"
        assert sm.transitions[0].to_state == "active"
        assert sm.transitions[1].from_state == "active"
        assert sm.transitions[1].to_state == "closed"

    def test_empty_entities_produces_empty_model(self):
        """No entities in parsed data produces an empty DomainModel."""
        parsed = ParsedPRD(project_name="Test", entities=[])
        model = build_domain_model(parsed, [])
        assert model.entities == []
        assert model.relationships == []

    def test_state_machine_case_insensitive_entity_match(self):
        """State machine entity matching is case-insensitive."""
        parsed = ParsedPRD(
            project_name="Test",
            entities=[_entity("order", fields=[{"name": "status", "type": "string"}])],
            state_machines=[{
                "entity": "ORDER",
                "states": ["new", "done"],
                "transitions": [
                    {"from_state": "new", "to_state": "done", "trigger": "complete"},
                ],
            }],
        )
        boundaries = [_boundary("Main", ["order"])]
        model = build_domain_model(parsed, boundaries)

        sm = model.entities[0].state_machine
        assert sm is not None
        assert sm.states == ["new", "done"]

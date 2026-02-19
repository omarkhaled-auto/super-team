"""Tests for service boundary identification and service map building.

Covers the aggregate-root algorithm in ``identify_boundaries`` and the
``build_service_map`` helper that converts boundaries into a valid
``ServiceMap`` Pydantic model.
"""
from __future__ import annotations

import hashlib

import pytest

from src.architect.services.prd_parser import ParsedPRD
from src.architect.services.service_boundary import (
    ServiceBoundary,
    build_service_map,
    identify_boundaries,
)


# ---------------------------------------------------------------------------
# Helpers — reusable PRD fixtures built from the ParsedPRD dataclass
# ---------------------------------------------------------------------------


def _entity(name: str, fields: list[dict] | None = None) -> dict:
    """Shorthand for creating a raw entity dict."""
    return {
        "name": name,
        "description": f"{name} entity",
        "fields": fields or [],
        "owning_context": None,
    }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestBoundariesFromExplicitBoundedContexts:
    """Step 1 of the algorithm: explicit bounded contexts seed boundaries."""

    def test_bounded_contexts_create_boundaries(self):
        """When bounded_contexts are provided, each one becomes a ServiceBoundary
        whose entities list contains only the entities named in that context."""
        parsed = ParsedPRD(
            project_name="Shop",
            entities=[_entity("User"), _entity("Order"), _entity("Product")],
            bounded_contexts=[
                {
                    "name": "User Management",
                    "entities": ["User"],
                    "description": "Handles user accounts.",
                },
                {
                    "name": "Order Processing",
                    "entities": ["Order", "Product"],
                    "description": "Handles orders and products.",
                },
            ],
        )
        boundaries = identify_boundaries(parsed)

        names = {b.name for b in boundaries}
        assert "User Management" in names
        assert "Order Processing" in names

        user_boundary = next(b for b in boundaries if b.name == "User Management")
        assert user_boundary.entities == ["User"]

        order_boundary = next(b for b in boundaries if b.name == "Order Processing")
        assert set(order_boundary.entities) == {"Order", "Product"}


class TestAggregateRootDiscovery:
    """Step 2: OWNS relationships drive aggregate root discovery."""

    def test_owns_relationships_create_aggregate_root_boundaries(self):
        """Entities with outgoing OWNS edges and no incoming OWNS edges are
        aggregate roots. Each root and its owned children form a boundary."""
        parsed = ParsedPRD(
            project_name="Billing",
            entities=[_entity("Invoice"), _entity("LineItem"), _entity("Payment")],
            relationships=[
                {"source": "Invoice", "target": "LineItem", "type": "OWNS"},
            ],
        )
        boundaries = identify_boundaries(parsed)

        # Invoice is an aggregate root owning LineItem.
        invoice_boundary = next(
            (b for b in boundaries if "Invoice" in b.entities), None
        )
        assert invoice_boundary is not None
        assert "LineItem" in invoice_boundary.entities

        # Payment is standalone (not owned, not an owner in the graph) so it
        # ends up either in its own boundary or via the relationship / fallback
        # path.
        all_entities = [e for b in boundaries for e in b.entities]
        assert "Payment" in all_entities


class TestRelationshipBasedAssignment:
    """Step 3: unassigned entities join the boundary they relate to most."""

    def test_unassigned_entity_joins_most_related_boundary(self):
        """An entity not covered by a bounded context or ownership graph is
        assigned to the boundary with which it shares the most relationships."""
        parsed = ParsedPRD(
            project_name="CRM",
            entities=[
                _entity("Account"),
                _entity("Contact"),
                _entity("Ticket"),
            ],
            relationships=[
                {"source": "Account", "target": "Contact", "type": "OWNS"},
                # Ticket references Account (2 rels) vs Contact (1 rel)
                {"source": "Ticket", "target": "Account", "type": "REFERENCES"},
                {"source": "Ticket", "target": "Account", "type": "TRIGGERS"},
                {"source": "Ticket", "target": "Contact", "type": "REFERENCES"},
            ],
        )
        boundaries = identify_boundaries(parsed)

        # Account is the aggregate root; Ticket should join Account's boundary
        # because it has more relationships with Account (2) than Contact (1).
        account_boundary = next(
            b for b in boundaries if "Account" in b.entities
        )
        assert "Ticket" in account_boundary.entities


class TestFallbackToMonolith:
    """Step 4: no contexts and no relationships -> single monolith boundary."""

    def test_no_contexts_no_relationships_produces_monolith(self):
        """When there are no bounded contexts and no relationships, all
        entities are grouped into a single 'monolith' boundary."""
        parsed = ParsedPRD(
            project_name="SimpleApp",
            entities=[_entity("Alpha"), _entity("Beta"), _entity("Gamma")],
        )
        boundaries = identify_boundaries(parsed)

        assert len(boundaries) == 1
        boundary = boundaries[0]
        assert set(boundary.entities) == {"Alpha", "Beta", "Gamma"}
        # The name should be the project name when used as monolith fallback.
        assert boundary.name == "SimpleApp"


class TestNonOverlappingBoundaries:
    """Each entity must appear in exactly one boundary (exclusive ownership)."""

    def test_every_entity_in_exactly_one_boundary(self):
        """Across all boundaries returned by identify_boundaries, each entity
        name appears exactly once."""
        parsed = ParsedPRD(
            project_name="MultiService",
            entities=[
                _entity("User"),
                _entity("Profile"),
                _entity("Order"),
                _entity("Item"),
                _entity("Notification"),
            ],
            relationships=[
                {"source": "User", "target": "Profile", "type": "OWNS"},
                {"source": "Order", "target": "Item", "type": "OWNS"},
                {"source": "Notification", "target": "User", "type": "REFERENCES"},
            ],
        )
        boundaries = identify_boundaries(parsed)

        all_entities: list[str] = []
        for b in boundaries:
            all_entities.extend(b.entities)

        # No duplicates
        assert len(all_entities) == len(set(all_entities))
        # All original entities are present
        assert set(all_entities) == {"User", "Profile", "Order", "Item", "Notification"}


class TestServiceNameNormalization:
    """Service names in ServiceMap must be kebab-case (^[a-z][a-z0-9-]*$)."""

    def test_camel_case_converted(self):
        """PascalCase / camelCase boundary names are correctly converted to
        kebab-case in the resulting ServiceMap."""
        parsed = ParsedPRD(
            project_name="Test",
            entities=[_entity("Order")],
            bounded_contexts=[
                {
                    "name": "OrderProcessing",
                    "entities": ["Order"],
                    "description": "Handles orders.",
                },
            ],
        )
        boundaries = identify_boundaries(parsed)
        smap = build_service_map(parsed, boundaries)

        service_names = [s.name for s in smap.services]
        assert "order-processing" in service_names

    def test_spaces_converted(self):
        """Boundary names with spaces are converted to kebab-case."""
        parsed = ParsedPRD(
            project_name="Test",
            entities=[_entity("User")],
            bounded_contexts=[
                {
                    "name": "User Management",
                    "entities": ["User"],
                    "description": "Users.",
                },
            ],
        )
        boundaries = identify_boundaries(parsed)
        smap = build_service_map(parsed, boundaries)

        service_names = [s.name for s in smap.services]
        assert "user-management" in service_names


class TestBuildServiceMap:
    """build_service_map must return a valid ServiceMap with correct prd_hash."""

    def test_service_map_has_correct_prd_hash(self):
        """The prd_hash in the ServiceMap is the SHA-256 hex-digest of the
        project_name string."""
        parsed = ParsedPRD(
            project_name="HashTest",
            entities=[_entity("Foo")],
        )
        boundaries = identify_boundaries(parsed)
        smap = build_service_map(parsed, boundaries)

        expected_hash = hashlib.sha256(b"HashTest").hexdigest()
        assert smap.prd_hash == expected_hash

    def test_service_map_project_name_matches(self):
        """The ServiceMap project_name matches the parsed PRD project_name."""
        parsed = ParsedPRD(
            project_name="MyProject",
            entities=[_entity("Widget")],
        )
        boundaries = identify_boundaries(parsed)
        smap = build_service_map(parsed, boundaries)

        assert smap.project_name == "MyProject"

    def test_service_map_services_non_empty(self):
        """The ServiceMap always contains at least one service."""
        parsed = ParsedPRD(
            project_name="Minimal",
            entities=[_entity("Thing")],
        )
        boundaries = identify_boundaries(parsed)
        smap = build_service_map(parsed, boundaries)

        assert len(smap.services) >= 1

    def test_technology_hints_propagate_to_stack(self):
        """Technology hints from the parsed PRD are reflected in each
        service's stack definition."""
        parsed = ParsedPRD(
            project_name="TechTest",
            entities=[_entity("Gizmo")],
            technology_hints={
                "language": "typescript",
                "framework": "express",
                "database": "postgres",
                "message_broker": "rabbitmq",
            },
        )
        boundaries = identify_boundaries(parsed)
        smap = build_service_map(parsed, boundaries)

        service = smap.services[0]
        assert service.stack.language == "typescript"
        assert service.stack.framework == "express"
        assert service.stack.database == "postgres"
        assert service.stack.message_broker == "rabbitmq"

    def test_estimated_loc_clamped(self):
        """estimated_loc is 500 * entity_count, clamped to [100, 200000]."""
        # Zero entities in boundary -> 0 * 500 = 0, clamped to 100
        parsed = ParsedPRD(project_name="EmptyLoc", entities=[])
        boundaries = identify_boundaries(parsed)
        smap = build_service_map(parsed, boundaries)
        assert smap.services[0].estimated_loc == 100


class TestEmptyEntitiesDefaultBoundary:
    """When no entities exist, a single default boundary is returned."""

    def test_empty_entities_produce_single_default_boundary(self):
        """If parsed.entities is empty, identify_boundaries returns exactly
        one boundary with an empty entities list and the project name."""
        parsed = ParsedPRD(
            project_name="NoEntities",
            entities=[],
        )
        boundaries = identify_boundaries(parsed)

        assert len(boundaries) == 1
        assert boundaries[0].entities == []
        assert boundaries[0].name == "NoEntities"
        assert boundaries[0].domain == "general"


# ---------------------------------------------------------------------------
# Pipeline integration tests
# ---------------------------------------------------------------------------


class TestPipelineEndToEnd:
    """Integration tests exercising parse_prd -> identify_boundaries -> build_service_map."""

    def test_pipeline_without_tech_hints(self):
        """Pipeline must handle PRDs with no technology mentions."""
        from src.architect.services.prd_parser import parse_prd

        prd = (
            "# SimpleApp PRD\n\n"
            "## Project Overview\n"
            "Project Name: SimpleApp\n"
            "A basic CRUD application.\n\n"
            "### UserAccount Entity\n"
            "- id (UUID)\n"
            "- email (string)\n\n"
            "## Notes\n"
            "End.\n"
        )
        parsed = parse_prd(prd)
        boundaries = identify_boundaries(parsed)
        service_map = build_service_map(parsed, boundaries)

        assert service_map is not None
        assert len(service_map.services) >= 1
        # Without tech hints, should default to "python"
        assert service_map.services[0].stack.language == "python"
        assert service_map.project_name == "SimpleApp PRD"

    def test_pipeline_with_tech_hints(self):
        """Pipeline should propagate detected technology hints to service stacks."""
        from src.architect.services.prd_parser import parse_prd

        prd = (
            "# Payments API\n\n"
            "| Entity | Description |\n"
            "|--------|-------------|\n"
            "| Invoice | A billing invoice |\n"
            "\n"
            "The backend is built with Python and FastAPI.\n"
            "Data is stored in PostgreSQL.\n"
        )
        parsed = parse_prd(prd)
        boundaries = identify_boundaries(parsed)
        service_map = build_service_map(parsed, boundaries)

        assert service_map is not None
        assert service_map.services[0].stack.language == "Python"
        assert service_map.services[0].stack.framework == "FastAPI"
        assert service_map.services[0].stack.database == "PostgreSQL"

    def test_pipeline_with_multiple_entities(self):
        """Pipeline should handle multiple entities and produce boundaries."""
        from src.architect.services.prd_parser import parse_prd

        prd = (
            "# Hospital System\n\n"
            "### Patient\n"
            "A person receiving care.\n"
            "- id: UUID (required)\n"
            "- name: string\n\n"
            "### Doctor\n"
            "A medical professional.\n"
            "- id: UUID (required)\n"
            "- specialty: string\n\n"
            "### Appointment\n"
            "A scheduled visit.\n"
            "- id: UUID (required)\n"
            "- scheduled_at: datetime\n\n"
            "## Notes\n"
            "End.\n"
        )
        parsed = parse_prd(prd)
        boundaries = identify_boundaries(parsed)
        service_map = build_service_map(parsed, boundaries)

        assert service_map is not None
        assert len(service_map.services) >= 1
        # All entities should be owned by some service
        all_entities = []
        for svc in service_map.services:
            all_entities.extend(svc.owns_entities)
        entity_names = [e["name"] for e in parsed.entities]
        for ename in entity_names:
            assert ename in all_entities, f"Entity {ename} not owned by any service"

    def test_pipeline_produces_valid_service_names(self):
        """All service names in the service map should be kebab-case."""
        from src.architect.services.prd_parser import parse_prd
        import re

        prd = (
            "# E-Commerce\n\n"
            "| Entity | Description |\n"
            "|--------|-------------|\n"
            "| Product | A catalog product |\n"
            "| Order   | A purchase order |\n"
            "\n"
            "## Service: Product Catalog\n"
            "Manages products.\n\n"
            "## Service: Order Processing\n"
            "Manages orders.\n"
        )
        parsed = parse_prd(prd)
        boundaries = identify_boundaries(parsed)
        service_map = build_service_map(parsed, boundaries)

        for svc in service_map.services:
            assert re.match(r"^[a-z][a-z0-9-]*$", svc.name), (
                f"Service name '{svc.name}' is not kebab-case"
            )

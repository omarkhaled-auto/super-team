"""Wave 2 tests for service boundary identification enhancements.

Tests heuristic boundary creation, cross-service contract computation,
and entity assignment behavior.
"""
from __future__ import annotations

import pytest

from src.architect.services.prd_parser import ParsedPRD
from src.architect.services.service_boundary import (
    ServiceBoundary,
    build_service_map,
    identify_boundaries,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _entity(name: str, fields: list[dict] | None = None, owning_context: str | None = None) -> dict:
    """Shorthand for creating a raw entity dict."""
    return {
        "name": name,
        "description": f"{name} entity",
        "fields": fields or [],
        "owning_context": owning_context,
    }


# ---------------------------------------------------------------------------
# 1. Heuristic boundary creation (aggregate root algorithm)
# ---------------------------------------------------------------------------


class TestHeuristicBoundaryCreation:
    """Without explicit services, boundaries are created via heuristic algorithm."""

    def test_aggregate_root_creates_boundary(self):
        """When no explicit services, the heuristic aggregate root algorithm runs."""
        parsed = ParsedPRD(
            project_name="Shop",
            entities=[_entity("Order"), _entity("LineItem")],
            relationships=[
                {"source": "Order", "target": "LineItem", "type": "OWNS"},
            ],
        )
        boundaries = identify_boundaries(parsed)
        # Should fall through to aggregate root algorithm
        assert len(boundaries) >= 1
        # Order should be an aggregate root
        order_boundary = next(
            (b for b in boundaries if "Order" in b.entities), None
        )
        assert order_boundary is not None

    def test_bounded_contexts_create_boundaries(self):
        """When bounded_contexts is populated, boundaries are created directly from them."""
        parsed = ParsedPRD(
            project_name="LedgerPro",
            entities=[_entity("Invoice"), _entity("User"), _entity("Ledger")],
            bounded_contexts=[
                {"name": "Invoice Service", "description": "Billing", "entities": ["Invoice", "Ledger"]},
                {"name": "User Service", "description": "Users", "entities": ["User"]},
            ],
        )
        boundaries = identify_boundaries(parsed)
        names = {b.name for b in boundaries}
        assert "Invoice Service" in names
        assert "User Service" in names

    def test_monolith_fallback(self):
        """When no bounded contexts or relationships, all entities in one boundary."""
        parsed = ParsedPRD(
            project_name="SimpleApp",
            entities=[_entity("Alpha"), _entity("Beta")],
        )
        boundaries = identify_boundaries(parsed)
        # Should have at least one boundary containing all entities
        all_assigned = set()
        for b in boundaries:
            all_assigned.update(b.entities)
        assert "Alpha" in all_assigned
        assert "Beta" in all_assigned


# ---------------------------------------------------------------------------
# 2. Service map building
# ---------------------------------------------------------------------------


class TestServiceMapBuilding:
    """build_service_map produces valid ServiceMap instances."""

    def test_service_map_has_services(self):
        """Service map contains at least one service per boundary."""
        parsed = ParsedPRD(
            project_name="TestApp",
            entities=[_entity("User"), _entity("Order")],
            technology_hints={"language": "Python", "framework": "FastAPI", "database": "PostgreSQL"},
            bounded_contexts=[
                {"name": "User Service", "entities": ["User"]},
                {"name": "Order Service", "entities": ["Order"]},
            ],
        )
        boundaries = identify_boundaries(parsed)
        smap = build_service_map(parsed, boundaries)
        assert len(smap.services) >= 2

    def test_backend_service_defaults(self):
        """Backend services default to the correct stack from technology hints."""
        parsed = ParsedPRD(
            project_name="App",
            entities=[_entity("User")],
            technology_hints={"language": "Python", "framework": "FastAPI"},
        )
        boundaries = identify_boundaries(parsed)
        smap = build_service_map(parsed, boundaries)

        for svc in smap.services:
            assert svc.stack.language == "Python"


# ---------------------------------------------------------------------------
# 3. All entities assigned
# ---------------------------------------------------------------------------


class TestAllEntitiesAssigned:
    """Every entity must end up in some service boundary."""

    def test_entities_assigned_via_bounded_contexts(self):
        """Entities matching bounded contexts are assigned to those contexts."""
        parsed = ParsedPRD(
            project_name="System",
            entities=[_entity("Invoice"), _entity("User"), _entity("AuditLog")],
            bounded_contexts=[
                {"name": "Invoice Service", "entities": ["Invoice"]},
                {"name": "User Service", "entities": ["User"]},
            ],
        )
        boundaries = identify_boundaries(parsed)
        all_assigned = set()
        for b in boundaries:
            all_assigned.update(b.entities)

        # All entities should be assigned somewhere
        all_entity_names = {"Invoice", "User", "AuditLog"}
        assert all_entity_names.issubset(all_assigned)

    def test_no_entities_returns_default_boundary(self):
        """If no entities at all, a default boundary is returned."""
        parsed = ParsedPRD(
            project_name="Empty",
            entities=[],
        )
        boundaries = identify_boundaries(parsed)
        assert len(boundaries) == 1

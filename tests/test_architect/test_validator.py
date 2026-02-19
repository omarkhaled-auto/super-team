"""Tests for src.architect.services.validator.validate_decomposition.

Covers all seven structural checks performed by validate_decomposition:
    1. Valid decomposition returns empty list
    2. Circular dependency detection
    3. Entity overlap detection
    4. Orphaned entity detection
    5. Empty service detection (no owns_entities)
    6. Relationship consistency (dangling entity references)
    7. Service name uniqueness
    8. Contract consistency (consumed contract with no provider)
"""

from __future__ import annotations

import pytest

from src.shared.models.architect import (
    DomainEntity,
    DomainModel,
    DomainRelationship,
    RelationshipType,
    ServiceDefinition,
    ServiceMap,
    ServiceStack,
)
from src.architect.services.validator import validate_decomposition


# ---------------------------------------------------------------------------
# Helpers -- reusable factory functions to reduce boilerplate
# ---------------------------------------------------------------------------

def _stack() -> ServiceStack:
    """Return a minimal ServiceStack to satisfy model validation."""
    return ServiceStack(language="python")


def _service(
    name: str,
    domain: str = "core",
    owns_entities: list[str] | None = None,
    provides_contracts: list[str] | None = None,
    consumes_contracts: list[str] | None = None,
) -> ServiceDefinition:
    """Build a ServiceDefinition with sensible defaults."""
    return ServiceDefinition(
        name=name,
        domain=domain,
        description=f"{name} service",
        stack=_stack(),
        estimated_loc=500,
        owns_entities=owns_entities or [],
        provides_contracts=provides_contracts or [],
        consumes_contracts=consumes_contracts or [],
    )


def _entity(name: str, owning_service: str = "svc") -> DomainEntity:
    """Build a minimal DomainEntity."""
    return DomainEntity(
        name=name,
        description=f"{name} entity",
        owning_service=owning_service,
    )


def _relationship(
    source: str,
    target: str,
    rel_type: RelationshipType = RelationshipType.REFERENCES,
    cardinality: str = "1:N",
) -> DomainRelationship:
    """Build a DomainRelationship between two entities."""
    return DomainRelationship(
        source_entity=source,
        target_entity=target,
        relationship_type=rel_type,
        cardinality=cardinality,
    )


def _service_map(*services: ServiceDefinition, project: str = "test-project") -> ServiceMap:
    """Wrap one or more ServiceDefinition objects in a ServiceMap."""
    return ServiceMap(
        project_name=project,
        services=list(services),
        prd_hash="abc123",
    )


def _domain_model(
    entities: list[DomainEntity] | None = None,
    relationships: list[DomainRelationship] | None = None,
) -> DomainModel:
    """Build a DomainModel with optional entities and relationships."""
    return DomainModel(
        entities=entities or [],
        relationships=relationships or [],
    )


# ---------------------------------------------------------------------------
# 1. Valid decomposition returns empty list
# ---------------------------------------------------------------------------


class TestValidDecomposition:
    """A well-formed decomposition must yield zero issues."""

    def test_valid_decomposition_returns_empty_list(self) -> None:
        """Given two services with disjoint entities and consistent contracts,
        validate_decomposition should return an empty list."""
        svc_a = _service(
            "order-service",
            owns_entities=["Order"],
            provides_contracts=["order-api"],
        )
        svc_b = _service(
            "user-service",
            owns_entities=["User"],
            provides_contracts=["user-api"],
            consumes_contracts=["order-api"],
        )
        sm = _service_map(svc_a, svc_b)
        dm = _domain_model(
            entities=[_entity("Order", "order-service"), _entity("User", "user-service")],
            relationships=[_relationship("Order", "User")],
        )

        issues = validate_decomposition(sm, dm)

        assert issues == [], f"Expected no issues, got: {issues}"


# ---------------------------------------------------------------------------
# 2. Circular dependency detection
# ---------------------------------------------------------------------------


class TestCircularDependency:
    """Services that mutually consume each other's contracts form a cycle."""

    def test_two_service_cycle_detected(self) -> None:
        """Service A consumes B's contract and B consumes A's contract.
        The validator must report a circular dependency."""
        svc_a = _service(
            "service-a",
            owns_entities=["EntityA"],
            provides_contracts=["contract-a"],
            consumes_contracts=["contract-b"],
        )
        svc_b = _service(
            "service-b",
            owns_entities=["EntityB"],
            provides_contracts=["contract-b"],
            consumes_contracts=["contract-a"],
        )
        sm = _service_map(svc_a, svc_b)
        dm = _domain_model(
            entities=[_entity("EntityA", "service-a"), _entity("EntityB", "service-b")],
        )

        issues = validate_decomposition(sm, dm)

        cycle_issues = [i for i in issues if "Circular dependency" in i]
        assert len(cycle_issues) >= 1, "Expected at least one circular-dependency issue"

    def test_three_service_cycle_detected(self) -> None:
        """A -> B -> C -> A should be flagged as a circular dependency."""
        svc_a = _service(
            "svc-a",
            owns_entities=["Alpha"],
            provides_contracts=["api-a"],
            consumes_contracts=["api-c"],
        )
        svc_b = _service(
            "svc-b",
            owns_entities=["Beta"],
            provides_contracts=["api-b"],
            consumes_contracts=["api-a"],
        )
        svc_c = _service(
            "svc-c",
            owns_entities=["Gamma"],
            provides_contracts=["api-c"],
            consumes_contracts=["api-b"],
        )
        sm = _service_map(svc_a, svc_b, svc_c)
        dm = _domain_model(
            entities=[
                _entity("Alpha", "svc-a"),
                _entity("Beta", "svc-b"),
                _entity("Gamma", "svc-c"),
            ],
        )

        issues = validate_decomposition(sm, dm)

        cycle_issues = [i for i in issues if "Circular dependency" in i]
        assert len(cycle_issues) >= 1, "Expected at least one circular-dependency issue in 3-service cycle"


# ---------------------------------------------------------------------------
# 3. Entity overlap detection
# ---------------------------------------------------------------------------


class TestEntityOverlap:
    """An entity must be owned by at most one service."""

    def test_entity_owned_by_two_services(self) -> None:
        """When both service-a and service-b claim 'SharedEntity', the
        validator should report an entity overlap error."""
        svc_a = _service("svc-a", owns_entities=["SharedEntity"])
        svc_b = _service("svc-b", owns_entities=["SharedEntity"])
        sm = _service_map(svc_a, svc_b)
        dm = _domain_model(entities=[_entity("SharedEntity")])

        issues = validate_decomposition(sm, dm)

        overlap_issues = [i for i in issues if "owned by multiple services" in i]
        assert len(overlap_issues) == 1
        assert "SharedEntity" in overlap_issues[0]


# ---------------------------------------------------------------------------
# 4. Orphaned entity detection
# ---------------------------------------------------------------------------


class TestOrphanedEntity:
    """Entities in the domain model that no service owns are orphaned."""

    def test_entity_in_domain_but_not_in_any_service(self) -> None:
        """'Phantom' is in the domain model but not listed in any service's
        owns_entities. The validator should issue a warning."""
        svc = _service("svc-a", owns_entities=["RealEntity"])
        sm = _service_map(svc)
        dm = _domain_model(
            entities=[_entity("RealEntity"), _entity("Phantom")],
        )

        issues = validate_decomposition(sm, dm)

        orphan_issues = [i for i in issues if "not owned by any service" in i]
        assert len(orphan_issues) == 1
        assert "Phantom" in orphan_issues[0]


# ---------------------------------------------------------------------------
# 5. Empty service detection (service with no owns_entities)
# ---------------------------------------------------------------------------


class TestEmptyService:
    """A service that owns zero entities should trigger a warning."""

    def test_service_with_no_entities(self) -> None:
        """A service with an empty owns_entities list should produce a
        'does not own any entities' warning."""
        svc_empty = _service("empty-svc", owns_entities=[])
        svc_ok = _service("ok-svc", owns_entities=["Thing"])
        sm = _service_map(svc_empty, svc_ok)
        dm = _domain_model(entities=[_entity("Thing")])

        issues = validate_decomposition(sm, dm)

        empty_issues = [i for i in issues if "does not own any entities" in i]
        assert len(empty_issues) == 1
        assert "empty-svc" in empty_issues[0]


# ---------------------------------------------------------------------------
# 6. Relationship consistency (dangling entity reference)
# ---------------------------------------------------------------------------


class TestRelationshipConsistency:
    """Relationships that reference non-existent entities must be caught."""

    def test_dangling_target_entity_in_relationship(self) -> None:
        """A relationship whose target entity is not in the domain model
        should produce an error."""
        svc = _service("svc-a", owns_entities=["Order"])
        sm = _service_map(svc)
        dm = _domain_model(
            entities=[_entity("Order")],
            relationships=[_relationship("Order", "NonExistentEntity")],
        )

        issues = validate_decomposition(sm, dm)

        rel_issues = [i for i in issues if "non-existent" in i and "NonExistentEntity" in i]
        assert len(rel_issues) == 1

    def test_dangling_source_entity_in_relationship(self) -> None:
        """A relationship whose source entity is not in the domain model
        should produce an error."""
        svc = _service("svc-a", owns_entities=["User"])
        sm = _service_map(svc)
        dm = _domain_model(
            entities=[_entity("User")],
            relationships=[_relationship("Ghost", "User")],
        )

        issues = validate_decomposition(sm, dm)

        rel_issues = [i for i in issues if "non-existent" in i and "Ghost" in i]
        assert len(rel_issues) == 1


# ---------------------------------------------------------------------------
# 7. Service name uniqueness
# ---------------------------------------------------------------------------


class TestServiceNameUniqueness:
    """Duplicate service names must be detected."""

    def test_duplicate_service_names(self) -> None:
        """Two services with the same name should produce an error
        mentioning the duplicate."""
        svc1 = _service("dupe-svc", owns_entities=["Alpha"])
        svc2 = _service("dupe-svc", owns_entities=["Beta"])
        sm = _service_map(svc1, svc2)
        dm = _domain_model(entities=[_entity("Alpha"), _entity("Beta")])

        issues = validate_decomposition(sm, dm)

        dup_issues = [i for i in issues if "Duplicate service name" in i]
        assert len(dup_issues) == 1
        assert "dupe-svc" in dup_issues[0]
        assert "2" in dup_issues[0]


# ---------------------------------------------------------------------------
# 8. Contract consistency (consumed contract with no provider)
# ---------------------------------------------------------------------------


class TestContractConsistency:
    """Every consumed contract must be provided by some service."""

    def test_consumed_contract_without_provider(self) -> None:
        """If service-a consumes 'missing-api' but no service provides it,
        the validator should report a contract consistency error."""
        svc = _service(
            "svc-a",
            owns_entities=["Item"],
            consumes_contracts=["missing-api"],
        )
        sm = _service_map(svc)
        dm = _domain_model(entities=[_entity("Item")])

        issues = validate_decomposition(sm, dm)

        contract_issues = [i for i in issues if "no service provides it" in i]
        assert len(contract_issues) == 1
        assert "missing-api" in contract_issues[0]

    def test_consumed_contract_with_provider_is_fine(self) -> None:
        """When the consumed contract IS provided by another service,
        no contract consistency issue should be raised."""
        svc_provider = _service(
            "provider-svc",
            owns_entities=["Product"],
            provides_contracts=["product-api"],
        )
        svc_consumer = _service(
            "consumer-svc",
            owns_entities=["Cart"],
            consumes_contracts=["product-api"],
        )
        sm = _service_map(svc_provider, svc_consumer)
        dm = _domain_model(
            entities=[_entity("Product"), _entity("Cart")],
        )

        issues = validate_decomposition(sm, dm)

        contract_issues = [i for i in issues if "no service provides it" in i]
        assert contract_issues == []

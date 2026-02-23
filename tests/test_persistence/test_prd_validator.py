"""Tests for PRD pre-validation."""
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
    StateMachine,
    StateTransition,
)
from src.super_orchestrator.prd_validator import (
    ValidationResult,
    validate_decomposition,
)


def _make_service(
    name: str,
    provides: list[str] | None = None,
    consumes: list[str] | None = None,
    owns_entities: list[str] | None = None,
) -> ServiceDefinition:
    return ServiceDefinition(
        name=name,
        domain="test",
        description=f"Test service {name}",
        stack=ServiceStack(language="python", framework="fastapi"),
        estimated_loc=1000,
        owns_entities=owns_entities or [],
        provides_contracts=provides or [],
        consumes_contracts=consumes or [],
    )


def _make_entity(
    name: str,
    fields: list[EntityField] | None = None,
    state_machine: StateMachine | None = None,
) -> DomainEntity:
    return DomainEntity(
        name=name,
        description=f"Test entity {name}",
        owning_service="test-service",
        fields=fields or [EntityField(name="id", type="string")],
        state_machine=state_machine,
    )


def _make_service_map(services: list[ServiceDefinition]) -> ServiceMap:
    return ServiceMap(
        project_name="test-project",
        services=services,
        prd_hash="test-hash",
    )


def _make_domain_model(
    entities: list[DomainEntity] | None = None,
    relationships: list[DomainRelationship] | None = None,
) -> DomainModel:
    return DomainModel(
        entities=entities or [_make_entity("DefaultEntity")],
        relationships=relationships or [],
    )


class TestPRDValidation:
    def test_ownership_conflict_detected(self) -> None:
        """PRD-001: Entity in two services' owns_entities → BLOCKING."""
        services = [
            _make_service("svc-a", owns_entities=["User"]),
            _make_service("svc-b", owns_entities=["User"]),
        ]
        result = validate_decomposition(
            _make_service_map(services), _make_domain_model()
        )
        blocking_codes = [i.code for i in result.blocking]
        assert "PRD-001" in blocking_codes
        assert not result.is_valid

    def test_missing_producer_detected(self) -> None:
        """PRD-003: Consumed contract, no provider → BLOCKING."""
        services = [
            _make_service("svc-a", consumes=["missing-api"]),
            _make_service("svc-b", provides=["other-api"]),
        ]
        result = validate_decomposition(
            _make_service_map(services), _make_domain_model()
        )
        blocking_codes = [i.code for i in result.blocking]
        assert "PRD-003" in blocking_codes

    def test_circular_dependency_detected(self) -> None:
        """PRD-004: A→B→A in DiGraph → BLOCKING."""
        services = [
            _make_service("svc-a", provides=["api-a"], consumes=["api-b"]),
            _make_service("svc-b", provides=["api-b"], consumes=["api-a"]),
        ]
        result = validate_decomposition(
            _make_service_map(services), _make_domain_model()
        )
        blocking_codes = [i.code for i in result.blocking]
        assert "PRD-004" in blocking_codes

    def test_isolated_service_detected(self) -> None:
        """PRD-005: Service with no contracts → WARNING."""
        services = [
            _make_service("svc-a", provides=["api-a"]),
            _make_service("svc-b"),  # No contracts
        ]
        result = validate_decomposition(
            _make_service_map(services), _make_domain_model()
        )
        warning_codes = [i.code for i in result.warnings]
        assert "PRD-005" in warning_codes

    def test_interview_questions_surfaced(self) -> None:
        """PRD-008: Non-empty field → WARNING."""
        services = [
            _make_service("svc-a", provides=["api-a"]),
            _make_service("svc-b", consumes=["api-a"]),
        ]
        result = validate_decomposition(
            _make_service_map(services),
            _make_domain_model(),
            interview_questions=["What auth method?"],
        )
        warning_codes = [i.code for i in result.warnings]
        assert "PRD-008" in warning_codes

    def test_valid_service_map_passes_all_checks(self) -> None:
        """Clean ServiceMap → is_valid=True, empty blocking."""
        services = [
            _make_service("svc-a", provides=["api-a"], owns_entities=["User"]),
            _make_service("svc-b", consumes=["api-a"], owns_entities=["Order"]),
        ]
        entities = [
            _make_entity("User"),
            _make_entity("Order"),
        ]
        result = validate_decomposition(
            _make_service_map(services),
            _make_domain_model(entities=entities),
        )
        assert result.is_valid
        assert len(result.blocking) == 0

    def test_orphan_contract_detected(self) -> None:
        """PRD-002: Provided but not consumed → WARNING."""
        services = [
            _make_service("svc-a", provides=["api-a", "api-orphan"]),
            _make_service("svc-b", consumes=["api-a"]),
        ]
        result = validate_decomposition(
            _make_service_map(services), _make_domain_model()
        )
        warning_codes = [i.code for i in result.warnings]
        assert "PRD-002" in warning_codes

    def test_state_machine_gap_detected(self) -> None:
        """PRD-007: Transition to undefined state → BLOCKING."""
        sm = StateMachine(
            states=["active", "inactive"],
            initial_state="active",
            transitions=[
                StateTransition(
                    from_state="active",
                    to_state="deleted",  # Not in states list
                    trigger="delete",
                ),
            ],
        )
        entities = [_make_entity("User", state_machine=sm)]
        result = validate_decomposition(
            _make_service_map([
                _make_service("svc-a", provides=["api-a"]),
                _make_service("svc-b", consumes=["api-a"]),
            ]),
            _make_domain_model(entities=entities),
        )
        blocking_codes = [i.code for i in result.blocking]
        assert "PRD-007" in blocking_codes

    def test_duplicate_contract_providers_detected(self) -> None:
        """PRD-010: Same contract by two services → BLOCKING."""
        services = [
            _make_service("svc-a", provides=["shared-api"]),
            _make_service("svc-b", provides=["shared-api"]),
        ]
        result = validate_decomposition(
            _make_service_map(services), _make_domain_model()
        )
        blocking_codes = [i.code for i in result.blocking]
        assert "PRD-010" in blocking_codes

    def test_empty_entity_detected(self) -> None:
        """PRD-006: Entity with no fields → WARNING."""
        entities = [
            DomainEntity(
                name="EmptyEntity",
                description="No fields",
                owning_service="svc-a",
                fields=[],
            ),
        ]
        result = validate_decomposition(
            _make_service_map([
                _make_service("svc-a", provides=["api-a"]),
                _make_service("svc-b", consumes=["api-a"]),
            ]),
            _make_domain_model(entities=entities),
        )
        warning_codes = [i.code for i in result.warnings]
        assert "PRD-006" in warning_codes

    def test_degenerate_decomposition_detected(self) -> None:
        """PRD-009: Single service → WARNING."""
        result = validate_decomposition(
            _make_service_map([_make_service("svc-only")]),
            _make_domain_model(),
        )
        warning_codes = [i.code for i in result.warnings]
        assert "PRD-009" in warning_codes

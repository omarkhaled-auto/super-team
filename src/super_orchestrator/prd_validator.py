"""PRD pre-validation -- structural checks on decomposition results.

Validates a ``ServiceMap`` and ``DomainModel`` for structural issues
*before* contract registration and builder dispatch.  Uses NetworkX
for graph-based dependency and cycle detection.

Ten checks are implemented (PRD-001 through PRD-010).  BLOCKING issues
halt the pipeline; WARNING issues are logged and optionally fed back
to the architect for retry.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from src.shared.models.architect import DomainModel, ServiceMap

logger = logging.getLogger(__name__)


@dataclass
class ValidationIssue:
    """A single validation issue found in the decomposition."""

    code: str  # e.g. "PRD-001"
    message: str
    severity: str  # "BLOCKING" or "WARNING"
    details: dict = field(default_factory=dict)


@dataclass
class ValidationResult:
    """Result of validating a decomposition."""

    blocking: list[ValidationIssue] = field(default_factory=list)
    warnings: list[ValidationIssue] = field(default_factory=list)
    is_valid: bool = True  # True only when blocking is empty

    def __post_init__(self) -> None:
        self.is_valid = len(self.blocking) == 0


def validate_decomposition(
    service_map: ServiceMap,
    domain_model: DomainModel,
    interview_questions: list[str] | None = None,
) -> ValidationResult:
    """Validate a decomposition result for structural issues.

    Never raises -- always returns a ``ValidationResult``.

    Args:
        service_map: The service map from architect decomposition.
        domain_model: The domain model with entities and relationships.
        interview_questions: Optional list of unresolved questions.

    Returns:
        Validation result with blocking and warning issues.
    """
    blocking: list[ValidationIssue] = []
    warnings: list[ValidationIssue] = []

    try:
        _check_entity_ownership_conflict(service_map, blocking)
        _check_orphan_contracts(service_map, warnings)
        _check_missing_producers(service_map, blocking)
        _check_circular_dependencies(service_map, blocking)
        _check_isolated_services(service_map, warnings)
        _check_empty_entities(domain_model, warnings)
        _check_state_machine_gaps(domain_model, blocking)
        _check_interview_questions(interview_questions, warnings)
        _check_degenerate_decomposition(service_map, warnings)
        _check_duplicate_contract_providers(service_map, blocking)
    except Exception as exc:
        logger.warning("PRD validation encountered an error (non-blocking): %s", exc)

    result = ValidationResult(blocking=blocking, warnings=warnings)
    return result


# ---------------------------------------------------------------------------
# Individual checks
# ---------------------------------------------------------------------------


def _check_entity_ownership_conflict(
    service_map: ServiceMap, issues: list[ValidationIssue]
) -> None:
    """PRD-001: Entity owned by more than one service (BLOCKING)."""
    entity_owners: dict[str, list[str]] = {}
    for svc in service_map.services:
        for entity in svc.owns_entities:
            entity_owners.setdefault(entity, []).append(svc.name)

    for entity, owners in entity_owners.items():
        if len(owners) > 1:
            issues.append(ValidationIssue(
                code="PRD-001",
                message=f"Entity '{entity}' is owned by multiple services: {', '.join(owners)}",
                severity="BLOCKING",
                details={"entity": entity, "owners": owners},
            ))


def _check_orphan_contracts(
    service_map: ServiceMap, issues: list[ValidationIssue]
) -> None:
    """PRD-002: Contract provided but consumed by nobody (WARNING)."""
    all_provided: dict[str, str] = {}
    all_consumed: set[str] = set()

    for svc in service_map.services:
        for contract in svc.provides_contracts:
            all_provided[contract] = svc.name
        for contract in svc.consumes_contracts:
            all_consumed.add(contract)

    orphans = set(all_provided.keys()) - all_consumed
    for contract in orphans:
        issues.append(ValidationIssue(
            code="PRD-002",
            message=(
                f"Contract '{contract}' is provided by '{all_provided[contract]}' "
                f"but consumed by no service"
            ),
            severity="WARNING",
            details={"contract": contract, "provider": all_provided[contract]},
        ))


def _check_missing_producers(
    service_map: ServiceMap, issues: list[ValidationIssue]
) -> None:
    """PRD-003: Contract consumed but provided by nobody (BLOCKING)."""
    all_provided: set[str] = set()
    all_consumed: dict[str, list[str]] = {}

    for svc in service_map.services:
        for contract in svc.provides_contracts:
            all_provided.add(contract)
        for contract in svc.consumes_contracts:
            all_consumed.setdefault(contract, []).append(svc.name)

    for contract, consumers in all_consumed.items():
        if contract not in all_provided:
            issues.append(ValidationIssue(
                code="PRD-003",
                message=(
                    f"Contract '{contract}' is consumed by {', '.join(consumers)} "
                    f"but no service provides it"
                ),
                severity="BLOCKING",
                details={"contract": contract, "consumers": consumers},
            ))


def _check_circular_dependencies(
    service_map: ServiceMap, issues: list[ValidationIssue]
) -> None:
    """PRD-004: Circular service dependency (BLOCKING).

    Builds a directed graph where an edge (A -> B) means A consumes
    a contract that B provides.  Detects simple cycles using NetworkX.
    """
    try:
        import networkx as nx
    except ImportError:
        logger.warning("NetworkX not available -- skipping circular dependency check")
        return

    try:
        # Build contract -> provider mapping
        contract_provider: dict[str, str] = {}
        for svc in service_map.services:
            for contract in svc.provides_contracts:
                contract_provider[contract] = svc.name

        # Build directed graph: consumer -> provider
        g = nx.DiGraph()
        for svc in service_map.services:
            g.add_node(svc.name)
            for contract in svc.consumes_contracts:
                provider = contract_provider.get(contract)
                if provider and provider != svc.name:
                    g.add_edge(svc.name, provider)

        cycles = list(nx.simple_cycles(g))
        for cycle in cycles:
            issues.append(ValidationIssue(
                code="PRD-004",
                message=f"Circular service dependency detected: {' -> '.join(cycle + [cycle[0]])}",
                severity="BLOCKING",
                details={"cycle": cycle},
            ))
    except Exception as exc:
        logger.warning("Circular dependency check failed: %s", exc)


def _check_isolated_services(
    service_map: ServiceMap, issues: list[ValidationIssue]
) -> None:
    """PRD-005: Isolated service with no contracts at all (WARNING)."""
    for svc in service_map.services:
        if not svc.provides_contracts and not svc.consumes_contracts:
            issues.append(ValidationIssue(
                code="PRD-005",
                message=f"Service '{svc.name}' has no contracts (neither provides nor consumes)",
                severity="WARNING",
                details={"service": svc.name},
            ))


def _check_empty_entities(
    domain_model: DomainModel, issues: list[ValidationIssue]
) -> None:
    """PRD-006: DomainModel entity with no fields (WARNING)."""
    for entity in domain_model.entities:
        if not entity.fields:
            issues.append(ValidationIssue(
                code="PRD-006",
                message=f"Entity '{entity.name}' has no fields defined",
                severity="WARNING",
                details={"entity": entity.name},
            ))


def _check_state_machine_gaps(
    domain_model: DomainModel, issues: list[ValidationIssue]
) -> None:
    """PRD-007: StateMachine transition references undefined state (BLOCKING)."""
    for entity in domain_model.entities:
        if entity.state_machine is None:
            continue
        sm = entity.state_machine
        defined_states = set(sm.states)
        for transition in sm.transitions:
            if transition.from_state not in defined_states:
                issues.append(ValidationIssue(
                    code="PRD-007",
                    message=(
                        f"Entity '{entity.name}' state machine: transition from "
                        f"undefined state '{transition.from_state}'"
                    ),
                    severity="BLOCKING",
                    details={
                        "entity": entity.name,
                        "undefined_state": transition.from_state,
                        "defined_states": list(defined_states),
                    },
                ))
            if transition.to_state not in defined_states:
                issues.append(ValidationIssue(
                    code="PRD-007",
                    message=(
                        f"Entity '{entity.name}' state machine: transition to "
                        f"undefined state '{transition.to_state}'"
                    ),
                    severity="BLOCKING",
                    details={
                        "entity": entity.name,
                        "undefined_state": transition.to_state,
                        "defined_states": list(defined_states),
                    },
                ))


def _check_interview_questions(
    interview_questions: list[str] | None, issues: list[ValidationIssue]
) -> None:
    """PRD-008: interview_questions non-empty (WARNING)."""
    if interview_questions:
        issues.append(ValidationIssue(
            code="PRD-008",
            message=(
                f"Architect has {len(interview_questions)} unresolved questions: "
                + "; ".join(interview_questions[:3])
                + ("..." if len(interview_questions) > 3 else "")
            ),
            severity="WARNING",
            details={"questions": interview_questions},
        ))


def _check_degenerate_decomposition(
    service_map: ServiceMap, issues: list[ValidationIssue]
) -> None:
    """PRD-009: Service count < 2 (degenerate decomposition) (WARNING)."""
    if len(service_map.services) < 2:
        issues.append(ValidationIssue(
            code="PRD-009",
            message=f"Only {len(service_map.services)} service(s) in decomposition -- possibly degenerate",
            severity="WARNING",
            details={"service_count": len(service_map.services)},
        ))


def _check_duplicate_contract_providers(
    service_map: ServiceMap, issues: list[ValidationIssue]
) -> None:
    """PRD-010: Same contract name registered by two services (BLOCKING)."""
    contract_providers: dict[str, list[str]] = {}
    for svc in service_map.services:
        for contract in svc.provides_contracts:
            contract_providers.setdefault(contract, []).append(svc.name)

    for contract, providers in contract_providers.items():
        if len(providers) > 1:
            issues.append(ValidationIssue(
                code="PRD-010",
                message=(
                    f"Contract '{contract}' is provided by multiple services: "
                    f"{', '.join(providers)}"
                ),
                severity="BLOCKING",
                details={"contract": contract, "providers": providers},
            ))

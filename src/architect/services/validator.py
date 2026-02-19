"""Decomposition validator for the Architect Service.

Pure-function module that validates a ServiceMap + DomainModel pair for
structural issues such as circular dependencies, entity overlap, orphaned
entities, and contract consistency.  Every check is self-contained and
operates only on the data passed in -- no global state is read or written.
"""

from __future__ import annotations

from collections import defaultdict

import networkx as nx

from src.shared.models.architect import ServiceMap, DomainModel


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def validate_decomposition(
    service_map: ServiceMap,
    domain_model: DomainModel,
) -> list[str]:
    """Validate a decomposition result for issues.

    Checks performed:
        1. Circular dependency detection between services
        2. Entity overlap (entity owned by multiple services)
        3. Orphaned entities (entities in domain model not owned by any service)
        4. Service completeness (every service has at least one entity)
        5. Relationship consistency (relationships reference existing entities)
        6. Service name uniqueness
        7. Contract consistency (consumed contracts have a provider)

    Args:
        service_map: The service map produced by decomposition.
        domain_model: The domain model produced by decomposition.

    Returns:
        List of validation issue strings.  Empty list means the
        decomposition is valid.
    """
    issues: list[str] = []

    issues.extend(_check_service_name_uniqueness(service_map))
    issues.extend(_check_circular_dependencies(service_map))
    issues.extend(_check_entity_overlap(service_map))
    issues.extend(_check_orphaned_entities(service_map, domain_model))
    issues.extend(_check_service_completeness(service_map))
    issues.extend(_check_relationship_consistency(domain_model))
    issues.extend(_check_contract_consistency(service_map))

    return issues


# ---------------------------------------------------------------------------
# Individual validation checks (private helpers)
# ---------------------------------------------------------------------------


def _check_circular_dependencies(service_map: ServiceMap) -> list[str]:
    """Detect circular dependencies between services via their contracts.

    Builds a directed graph where an edge ``A -> B`` means service *A*
    consumes a contract that service *B* provides.  Any cycle in this graph
    represents a circular dependency chain.
    """
    issues: list[str] = []

    # Map each provided contract to the service that provides it.
    provider_index: dict[str, str] = {}
    for service in service_map.services:
        for contract in service.provides_contracts:
            provider_index[contract] = service.name

    # Build the dependency digraph.
    graph = nx.DiGraph()
    for service in service_map.services:
        graph.add_node(service.name)
        for contract in service.consumes_contracts:
            provider = provider_index.get(contract)
            if provider is not None and provider != service.name:
                graph.add_edge(service.name, provider)

    # Detect cycles.
    for cycle in nx.simple_cycles(graph):
        cycle_path = " -> ".join(cycle + [cycle[0]])
        issues.append(
            f"ERROR: Circular dependency detected: {cycle_path}"
        )

    return issues


def _check_entity_overlap(service_map: ServiceMap) -> list[str]:
    """Check whether any entity is owned by more than one service."""
    issues: list[str] = []

    entity_owners: dict[str, list[str]] = defaultdict(list)
    for service in service_map.services:
        for entity in service.owns_entities:
            entity_owners[entity].append(service.name)

    for entity, owners in sorted(entity_owners.items()):
        if len(owners) > 1:
            owners_str = ", ".join(sorted(owners))
            issues.append(
                f"ERROR: Entity '{entity}' is owned by multiple services: "
                f"{owners_str}"
            )

    return issues


def _check_orphaned_entities(
    service_map: ServiceMap,
    domain_model: DomainModel,
) -> list[str]:
    """Find entities present in the domain model but not owned by any service."""
    issues: list[str] = []

    owned_entities: set[str] = set()
    for service in service_map.services:
        owned_entities.update(service.owns_entities)

    domain_entity_names: set[str] = {e.name for e in domain_model.entities}

    orphaned = sorted(domain_entity_names - owned_entities)
    for entity in orphaned:
        issues.append(
            f"WARNING: Entity '{entity}' exists in the domain model but is "
            f"not owned by any service"
        )

    return issues


def _check_service_completeness(service_map: ServiceMap) -> list[str]:
    """Ensure every service owns at least one entity."""
    issues: list[str] = []

    for service in service_map.services:
        if not service.owns_entities:
            issues.append(
                f"WARNING: Service '{service.name}' does not own any entities"
            )

    return issues


def _check_relationship_consistency(domain_model: DomainModel) -> list[str]:
    """Verify that every relationship references entities that exist."""
    issues: list[str] = []

    known_entities: set[str] = {e.name for e in domain_model.entities}

    for rel in domain_model.relationships:
        if rel.source_entity not in known_entities:
            issues.append(
                f"ERROR: Relationship references non-existent source entity "
                f"'{rel.source_entity}'"
            )
        if rel.target_entity not in known_entities:
            issues.append(
                f"ERROR: Relationship references non-existent target entity "
                f"'{rel.target_entity}'"
            )

    return issues


def _check_service_name_uniqueness(service_map: ServiceMap) -> list[str]:
    """Check that all service names in the map are unique."""
    issues: list[str] = []

    seen: dict[str, int] = defaultdict(int)
    for service in service_map.services:
        seen[service.name] += 1

    for name, count in sorted(seen.items()):
        if count > 1:
            issues.append(
                f"ERROR: Duplicate service name '{name}' appears {count} times"
            )

    return issues


def _check_contract_consistency(service_map: ServiceMap) -> list[str]:
    """Ensure every consumed contract has a corresponding provider."""
    issues: list[str] = []

    # Collect all provided contracts across the entire service map.
    all_provided: set[str] = set()
    for service in service_map.services:
        all_provided.update(service.provides_contracts)

    # Check that every consumed contract can be resolved.
    for service in service_map.services:
        for contract in service.consumes_contracts:
            if contract not in all_provided:
                issues.append(
                    f"ERROR: Service '{service.name}' consumes contract "
                    f"'{contract}' but no service provides it"
                )

    return issues

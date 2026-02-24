"""Service boundary identification using aggregate root algorithm.

Identifies non-overlapping service boundaries from parsed PRD data,
ensuring each entity belongs to exactly one service (exclusive ownership).

This module contains only pure functions with no global state.
"""

from __future__ import annotations

import hashlib
import re
from collections import defaultdict
from dataclasses import dataclass, field

from src.architect.services.prd_parser import ParsedPRD
from src.shared.models.architect import (
    ServiceDefinition,
    ServiceMap,
    ServiceStack,
)


@dataclass
class ServiceBoundary:
    """A service boundary grouping related entities.

    Attributes:
        name: Human-readable boundary name (e.g. "User Management").
        domain: Domain area this boundary covers.
        description: Brief description of the boundary's responsibility.
        entities: Entity names exclusively owned by this boundary.
        provides_contracts: Contracts this service exposes to others.
        consumes_contracts: Contracts this service depends on from others.
    """

    name: str
    domain: str
    description: str
    entities: list[str]
    provides_contracts: list[str] = field(default_factory=list)
    consumes_contracts: list[str] = field(default_factory=list)


def _to_kebab_case(name: str) -> str:
    """Convert a human-readable name to kebab-case.

    Examples:
        "User Management" -> "user-management"
        "OrderProcessing"  -> "order-processing"
        "  API  Gateway  " -> "api-gateway"

    The result always matches ``^[a-z][a-z0-9-]*$``.
    """
    # Strip leading/trailing whitespace
    name = name.strip()

    # Insert hyphens before uppercase letters in camelCase / PascalCase
    name = re.sub(r"([a-z0-9])([A-Z])", r"\1-\2", name)

    # Replace any non-alphanumeric characters (spaces, underscores, etc.)
    # with hyphens
    name = re.sub(r"[^a-zA-Z0-9]+", "-", name)

    # Lowercase everything
    name = name.lower()

    # Collapse consecutive hyphens
    name = re.sub(r"-+", "-", name)

    # Strip leading/trailing hyphens
    name = name.strip("-")

    # Safety: if the result is empty, fall back to "service"
    if not name:
        name = "service"

    # Ensure the name starts with a letter (not a digit)
    if name[0].isdigit():
        name = "svc-" + name

    return name


def _build_ownership_graph(
    relationships: list[dict],
) -> dict[str, list[str]]:
    """Build a directed ownership graph from OWNS relationships.

    Returns a mapping of *owner entity* -> [*owned entities*].
    Only relationships whose ``type`` is ``"OWNS"`` (case-insensitive)
    are considered.
    """
    graph: dict[str, list[str]] = defaultdict(list)
    for rel in relationships:
        rel_type = rel.get("type", "")
        if rel_type.upper() == "OWNS":
            source = rel.get("source", "")
            target = rel.get("target", "")
            if source and target:
                graph[source].append(target)
    return dict(graph)


def _find_aggregate_roots(
    all_entities: set[str],
    ownership_graph: dict[str, list[str]],
) -> set[str]:
    """Find aggregate roots — entities with no incoming OWNS edges.

    An aggregate root is an entity that is not *owned* by any other entity,
    yet itself appears in the ownership graph (either as an owner or as a
    known entity).
    """
    owned_entities: set[str] = set()
    for children in ownership_graph.values():
        owned_entities.update(children)

    # Aggregate roots are entities present in the graph as owners that are
    # not themselves owned by another entity.
    owners = set(ownership_graph.keys())

    # Only entities that are owners and not owned are aggregate roots.
    roots = owners - owned_entities

    # Also include entities that appear nowhere in the ownership graph as
    # potential standalone roots (handled later in the algorithm).
    return roots


def _count_relationships(
    entity: str,
    boundary_entities: set[str],
    relationships: list[dict],
) -> int:
    """Count how many relationships link *entity* to members of *boundary_entities*."""
    count = 0
    for rel in relationships:
        source = rel.get("source", "")
        target = rel.get("target", "")
        if source == entity and target in boundary_entities:
            count += 1
        elif target == entity and source in boundary_entities:
            count += 1
    return count


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def _normalise_boundary_key(name: str) -> str:
    """Normalise a boundary name for deduplication purposes.

    Strips trailing "Service" (case-insensitive), collapses whitespace,
    and lowercases.  This ensures "User Service" and "User Service\\n\\nThe
    User Service" collapse to the same key.
    """
    key = re.sub(r"\s+", " ", name).strip().lower()
    # Strip trailing " service" for dedup (but keep as the display name)
    if key.endswith(" service"):
        key = key[: -len(" service")].strip()
    return key


def identify_boundaries(parsed: ParsedPRD) -> list[ServiceBoundary]:
    """Identify service boundaries from parsed PRD data.

    Uses the aggregate root algorithm:

    1. **Explicit bounded contexts** — If ``parsed.bounded_contexts`` is
       non-empty, each context seeds a ``ServiceBoundary`` and its listed
       entities are assigned to it.
    2. **Aggregate root discovery** — For entities not yet assigned, an
       ownership graph is built from ``OWNS`` relationships.  Entities with
       no incoming ``OWNS`` edge are *aggregate roots* and each seeds a new
       boundary.  Their owned children join the same boundary.
    3. **Relationship-based assignment** — Still-unassigned entities are
       placed in the boundary with which they share the most relationships
       (``REFERENCES``, ``TRIGGERS``, ``DEPENDS_ON``).
    4. **Fallback** — If no bounded contexts *and* no relationships exist,
       all entities are grouped into a single "monolith" boundary.

    Returns:
        A list of ``ServiceBoundary`` instances with non-overlapping,
        exclusive entity ownership.
    """
    all_entity_names: set[str] = {e.get("name", "") for e in parsed.entities}
    all_entity_names.discard("")

    # If there are no entities at all, return a single empty boundary.
    if not all_entity_names:
        return [
            ServiceBoundary(
                name=parsed.project_name or "default",
                domain="general",
                description="Default service boundary (no entities detected).",
                entities=[],
            )
        ]

    assigned: dict[str, str] = {}  # entity_name -> boundary_name
    boundaries: dict[str, ServiceBoundary] = {}  # boundary_name -> ServiceBoundary

    # ------------------------------------------------------------------
    # Step 1: Explicit bounded contexts
    # ------------------------------------------------------------------
    # Track normalised keys to detect duplicate contexts (e.g.
    # "User Service" mentioned as heading and again in prose).
    _seen_boundary_keys: dict[str, str] = {}  # norm_key -> canonical ctx_name

    if parsed.bounded_contexts:
        for ctx in parsed.bounded_contexts:
            ctx_name = ctx.get("name", "").strip()
            if not ctx_name:
                continue

            # Deduplicate using normalised key
            norm_key = _normalise_boundary_key(ctx_name)
            if norm_key in _seen_boundary_keys:
                # Merge into the existing boundary instead of creating a duplicate
                canonical_name = _seen_boundary_keys[norm_key]
                existing_boundary = boundaries[canonical_name]
                for ent in ctx.get("entities", []):
                    ent_name = ent if isinstance(ent, str) else ent.get("name", "")
                    if ent_name in all_entity_names and ent_name not in assigned:
                        existing_boundary.entities.append(ent_name)
                        assigned[ent_name] = canonical_name
                continue

            _seen_boundary_keys[norm_key] = ctx_name
            ctx_entities = ctx.get("entities", [])
            ctx_description = ctx.get("description", f"Bounded context: {ctx_name}")

            # Normalise entity names coming from the context definition
            resolved: list[str] = []
            for ent in ctx_entities:
                ent_name = ent if isinstance(ent, str) else ent.get("name", "")
                if ent_name in all_entity_names and ent_name not in assigned:
                    resolved.append(ent_name)
                    assigned[ent_name] = ctx_name

            boundary = ServiceBoundary(
                name=ctx_name,
                domain=ctx_name.lower().replace(" ", "-"),
                description=ctx_description,
                entities=resolved,
            )
            boundaries[ctx_name] = boundary

    # ------------------------------------------------------------------
    # Step 2: Aggregate root discovery (for remaining entities)
    # ------------------------------------------------------------------
    unassigned = all_entity_names - set(assigned.keys())

    if unassigned:
        ownership_graph = _build_ownership_graph(parsed.relationships)
        roots = _find_aggregate_roots(all_entity_names, ownership_graph)

        # Only consider roots that are still unassigned
        roots = roots & unassigned

        for root in sorted(roots):  # sorted for determinism
            boundary_name = root
            owned = set(ownership_graph.get(root, []))
            # Only include owned entities that are themselves unassigned
            owned_unassigned = owned & unassigned

            group = [root] + sorted(owned_unassigned)
            for ent in group:
                assigned[ent] = boundary_name

            boundary = ServiceBoundary(
                name=boundary_name,
                domain=_to_kebab_case(boundary_name),
                description=f"Service boundary rooted at aggregate {root}.",
                entities=group,
            )
            boundaries[boundary_name] = boundary

        # Update unassigned set
        unassigned = all_entity_names - set(assigned.keys())

    # ------------------------------------------------------------------
    # Step 3: Relationship-based assignment
    # ------------------------------------------------------------------
    if unassigned and boundaries:
        for entity in sorted(unassigned):  # sorted for determinism
            best_boundary: str | None = None
            best_count = 0

            for bname, boundary in boundaries.items():
                bset = set(boundary.entities)
                count = _count_relationships(entity, bset, parsed.relationships)
                if count > best_count:
                    best_count = count
                    best_boundary = bname

            if best_boundary is not None:
                boundaries[best_boundary].entities.append(entity)
                assigned[entity] = best_boundary
            else:
                # No relationship found — create or extend a "misc" boundary
                misc_name = "Miscellaneous"
                if misc_name not in boundaries:
                    boundaries[misc_name] = ServiceBoundary(
                        name=misc_name,
                        domain="misc",
                        description="Entities not assigned to any specific boundary.",
                        entities=[],
                    )
                boundaries[misc_name].entities.append(entity)
                assigned[entity] = misc_name

        unassigned = all_entity_names - set(assigned.keys())

    # ------------------------------------------------------------------
    # Step 4: Fallback — single monolith if nothing was created
    # ------------------------------------------------------------------
    if not boundaries:
        monolith_name = parsed.project_name or "monolith"
        boundaries[monolith_name] = ServiceBoundary(
            name=monolith_name,
            domain="general",
            description="All entities grouped into a single service (no contexts or relationships found).",
            entities=sorted(all_entity_names),
        )

    # Assign any truly remaining entities (shouldn't happen, but be safe)
    remaining = all_entity_names - set(assigned.keys())
    if remaining:
        first_boundary = next(iter(boundaries.values()))
        for ent in sorted(remaining):
            first_boundary.entities.append(ent)

    # ------------------------------------------------------------------
    # Step 5: Derive inter-boundary contracts
    # ------------------------------------------------------------------
    _compute_contracts(list(boundaries.values()), parsed.relationships)

    return list(boundaries.values())


def _compute_contracts(
    boundaries: list[ServiceBoundary],
    relationships: list[dict],
) -> None:
    """Populate ``provides_contracts`` and ``consumes_contracts`` in-place.

    A boundary *provides* a contract named ``"{kebab-name}-api"``.
    A boundary *consumes* a contract when one of its entities references an
    entity in another boundary via a non-OWNS relationship.
    """
    # Build entity -> boundary index
    entity_to_boundary: dict[str, ServiceBoundary] = {}
    for boundary in boundaries:
        for ent in boundary.entities:
            entity_to_boundary[ent] = boundary

    # Each boundary provides its own API contract
    for boundary in boundaries:
        contract_name = f"{_to_kebab_case(boundary.name)}-api"
        if contract_name not in boundary.provides_contracts:
            boundary.provides_contracts.append(contract_name)

    # Determine consumed contracts from cross-boundary relationships
    for rel in relationships:
        rel_type = rel.get("type", "").upper()
        if rel_type == "OWNS":
            # OWNS is intra-boundary, skip
            continue

        source = rel.get("source", "")
        target = rel.get("target", "")
        source_boundary = entity_to_boundary.get(source)
        target_boundary = entity_to_boundary.get(target)

        if (
            source_boundary is not None
            and target_boundary is not None
            and source_boundary is not target_boundary
        ):
            # source_boundary consumes target_boundary's contract
            target_contract = f"{_to_kebab_case(target_boundary.name)}-api"
            if target_contract not in source_boundary.consumes_contracts:
                source_boundary.consumes_contracts.append(target_contract)

            # For BELONGS_TO, the target boundary also needs to consume
            # from source (bidirectional dependency).
            if rel_type == "BELONGS_TO":
                source_contract = f"{_to_kebab_case(source_boundary.name)}-api"
                if source_contract not in target_boundary.consumes_contracts:
                    target_boundary.consumes_contracts.append(source_contract)


def build_service_map(
    parsed: ParsedPRD,
    boundaries: list[ServiceBoundary],
) -> ServiceMap:
    """Build a ``ServiceMap`` from parsed PRD and identified boundaries.

    Each ``ServiceBoundary`` is converted into a ``ServiceDefinition``:

    * **name** — kebab-case of the boundary name.
    * **domain** — boundary domain.
    * **stack** — derived from ``parsed.technology_hints``.
    * **estimated_loc** — 500 lines per entity, clamped to [100, 200000].
    * **owns_entities** — the boundary's entity names.
    * **provides_contracts** — carried from the boundary.
    * **consumes_contracts** — carried from the boundary.

    The ``prd_hash`` is computed as the SHA-256 hex-digest of
    ``parsed.project_name`` (used as a stable proxy for the original PRD
    text at this layer).
    """
    hints = parsed.technology_hints or {}
    stack = ServiceStack(
        language=hints.get("language") or "python",
        framework=hints.get("framework"),
        database=hints.get("database"),
        message_broker=hints.get("message_broker"),
    )

    services: list[ServiceDefinition] = []
    for boundary in boundaries:
        entity_count = len(boundary.entities)
        raw_loc = entity_count * 500
        estimated_loc = max(100, min(200_000, raw_loc))

        service = ServiceDefinition(
            name=_to_kebab_case(boundary.name),
            domain=boundary.domain,
            description=boundary.description,
            stack=stack,
            estimated_loc=estimated_loc,
            owns_entities=list(boundary.entities),
            provides_contracts=list(boundary.provides_contracts),
            consumes_contracts=list(boundary.consumes_contracts),
        )
        services.append(service)

    prd_hash = hashlib.sha256(
        (parsed.project_name or "").encode("utf-8")
    ).hexdigest()

    return ServiceMap(
        project_name=parsed.project_name,
        services=services,
        prd_hash=prd_hash,
    )

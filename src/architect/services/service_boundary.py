"""Service boundary identification using aggregate root algorithm.

Identifies non-overlapping service boundaries from parsed PRD data,
ensuring each entity belongs to exactly one service (exclusive ownership).

Supports three decomposition strategies:
  - ``microservices`` (default) — current 4-tier fallback logic.
  - ``bounded_contexts`` — merges small services into larger bounded contexts.
  - ``monolith`` — all entities in one backend + optional frontend.

This module contains only pure functions with no global state.
"""

from __future__ import annotations

import hashlib
import logging
import re
from collections import defaultdict
from dataclasses import dataclass, field

from src.architect.services.prd_parser import ParsedPRD
from src.shared.models.architect import (
    ServiceDefinition,
    ServiceMap,
    ServiceStack,
)

logger = logging.getLogger(__name__)


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
        is_frontend: Whether this boundary is a frontend/UI service.
    """

    name: str
    domain: str
    description: str
    entities: list[str]
    provides_contracts: list[str] = field(default_factory=list)
    consumes_contracts: list[str] = field(default_factory=list)
    is_frontend: bool = False


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


def _boundaries_from_explicit_services(parsed: ParsedPRD) -> list[ServiceBoundary]:
    """Create boundaries from explicitly defined services in the PRD.

    Uses ``parsed.explicit_services`` for service definitions and
    ``entity.owning_context`` for entity-to-service assignment.
    """
    all_entity_names: set[str] = {e.get("name", "") for e in parsed.entities}
    all_entity_names.discard("")

    # Build entity → owning service mapping from entity metadata
    entity_ownership: dict[str, str] = {}
    for entity in parsed.entities:
        owning_ctx = entity.get("owning_context")
        if owning_ctx:
            entity_ownership[entity["name"]] = owning_ctx

    boundaries: list[ServiceBoundary] = []
    assigned: set[str] = set()

    for svc in parsed.explicit_services:
        svc_name = svc["name"]

        # Find entities owned by this service
        svc_entities: list[str] = []
        for ename, owner in entity_ownership.items():
            if owner == svc_name and ename in all_entity_names:
                svc_entities.append(ename)
                assigned.add(ename)

        boundary = ServiceBoundary(
            name=svc_name,
            domain=_to_kebab_case(svc_name),
            description=svc.get("description", f"Service: {svc_name}"),
            entities=svc_entities,
            is_frontend=bool(svc.get("is_frontend", False)),
        )
        boundaries.append(boundary)

    # Handle unassigned entities — assign to closest service via relationships
    unassigned = all_entity_names - assigned
    if unassigned and boundaries:
        for entity in sorted(unassigned):
            best_boundary: ServiceBoundary | None = None
            best_count = 0
            for boundary in boundaries:
                bset = set(boundary.entities)
                count = _count_relationships(entity, bset, parsed.relationships)
                if count > best_count:
                    best_count = count
                    best_boundary = boundary
            if best_boundary is not None:
                best_boundary.entities.append(entity)
            else:
                # Fallback: assign to first non-frontend boundary
                for b in boundaries:
                    svc_meta = next(
                        (s for s in parsed.explicit_services if s["name"] == b.name),
                        None,
                    )
                    if svc_meta and not svc_meta.get("is_frontend", False):
                        b.entities.append(entity)
                        break

    # Compute inter-boundary contracts
    _compute_contracts(boundaries, parsed.relationships)

    return boundaries


def identify_boundaries(
    parsed: ParsedPRD,
    decomposition_strategy: str = "microservices",
    max_services: int = 5,
    min_entities_per_service: int = 6,
) -> list[ServiceBoundary]:
    """Identify service boundaries based on decomposition strategy.

    Strategies:
      - ``microservices`` (default) — current 4-tier fallback.
      - ``bounded_contexts`` — natural decomposition then merge small services.
      - ``monolith`` — one backend with all entities + optional frontend.

    Args:
        parsed: Structured data from PRD parsing.
        decomposition_strategy: One of ``microservices``, ``bounded_contexts``,
            or ``monolith``.
        max_services: Max backend services (bounded_contexts mode only).
        min_entities_per_service: Minimum entities per service before merging
            (bounded_contexts mode only).

    Returns:
        A list of ``ServiceBoundary`` instances with non-overlapping,
        exclusive entity ownership.
    """
    logger.info("Decomposition strategy: %s", decomposition_strategy)

    if decomposition_strategy == "monolith":
        return _boundaries_monolith(parsed)

    if decomposition_strategy == "bounded_contexts":
        # First get the natural decomposition (current behaviour)
        raw_boundaries = _identify_boundaries_natural(parsed)
        # Then merge small services into bounded contexts
        return _merge_to_bounded_contexts(
            boundaries=raw_boundaries,
            parsed=parsed,
            max_services=max_services,
            min_entities_per_service=min_entities_per_service,
        )

    # "microservices" — current default behaviour
    return _identify_boundaries_natural(parsed)


def _identify_boundaries_natural(parsed: ParsedPRD) -> list[ServiceBoundary]:
    """Original 4-tier decomposition logic (microservices mode).

    0. **Explicit services** — If ``parsed.explicit_services`` has 3+
       services, boundaries are created directly from them with entity
       ownership from entity metadata.
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
    # Step 0: Use explicit services if available (from Technology Stack table)
    if (
        hasattr(parsed, "explicit_services")
        and len(getattr(parsed, "explicit_services", [])) >= 3
    ):
        return _boundaries_from_explicit_services(parsed)

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


# ---------------------------------------------------------------------------
# Monolith mode
# ---------------------------------------------------------------------------

_FRONTEND_FRAMEWORKS = frozenset(
    {"angular", "react", "vue", "next.js", "nuxt.js", "svelte"}
)


def _is_frontend_boundary(boundary: ServiceBoundary) -> bool:
    """Check if a boundary is a frontend service."""
    return boundary.is_frontend


def _boundaries_monolith(parsed: ParsedPRD) -> list[ServiceBoundary]:
    """Monolith mode: one backend service with ALL entities + optional frontend."""
    all_entity_names: list[str] = sorted(
        {e.get("name", "") for e in parsed.entities} - {""}
    )

    # Determine backend language from the majority of explicit services
    backend_lang = "python"  # default
    frontend_found = False
    if parsed.explicit_services:
        lang_counts: dict[str, int] = {}
        for svc in parsed.explicit_services:
            fw = (svc.get("framework") or "").lower()
            if fw in _FRONTEND_FRAMEWORKS:
                frontend_found = True
                continue
            lang = (svc.get("language") or "").lower()
            if lang:
                lang_counts[lang] = lang_counts.get(lang, 0) + 1
        if lang_counts:
            backend_lang = max(lang_counts, key=lang_counts.get)  # type: ignore[arg-type]

    # Also check technology hints for frontend
    if not frontend_found:
        hint_fw = (parsed.technology_hints.get("framework") or "").lower()
        if hint_fw in _FRONTEND_FRAMEWORKS:
            frontend_found = True

    project_name = parsed.project_name or "app"
    slug = re.sub(r"[^a-z0-9]+", "-", project_name.lower()).strip("-") or "app"
    backend_name = f"{slug}-backend"

    boundaries: list[ServiceBoundary] = [
        ServiceBoundary(
            name=backend_name,
            domain="general",
            description=f"Monolith backend for {project_name}",
            entities=all_entity_names,
        )
    ]

    # Add frontend as separate service if any frontend stack detected
    if frontend_found:
        boundaries.append(
            ServiceBoundary(
                name="frontend",
                domain="frontend",
                description=f"Frontend for {project_name}",
                entities=[],
                is_frontend=True,
            )
        )

    _compute_contracts(boundaries, parsed.relationships)

    logger.info(
        "Monolith mode: 1 backend with %d entities%s",
        len(all_entity_names),
        " + 1 frontend" if frontend_found else "",
    )
    return boundaries


# ---------------------------------------------------------------------------
# Bounded contexts merge engine
# ---------------------------------------------------------------------------


def _merge_to_bounded_contexts(
    boundaries: list[ServiceBoundary],
    parsed: ParsedPRD,
    max_services: int = 5,
    min_entities_per_service: int = 6,
) -> list[ServiceBoundary]:
    """Merge small service boundaries into larger bounded contexts.

    Algorithm:
      1. Separate frontend from backend (frontend is never merged).
      2. Build a relatedness graph between backend services.
      3. Iteratively merge the two most-related services until constraints met.
    """
    frontend = [b for b in boundaries if _is_frontend_boundary(b)]
    backend = [b for b in boundaries if not _is_frontend_boundary(b)]

    if len(backend) <= max_services and all(
        len(b.entities) >= min_entities_per_service for b in backend
    ):
        logger.info(
            "Bounded contexts: %d services already meet constraints", len(backend)
        )
        return backend + frontend

    # Build relatedness scores
    relatedness = _build_relatedness_graph(backend, parsed)

    merged = list(backend)
    merge_count = 0

    while True:
        over_limit = len(merged) > max_services
        has_small = any(
            len(b.entities) < min_entities_per_service for b in merged
        )

        if not over_limit and not has_small:
            break
        if len(merged) <= 1:
            break

        best_pair = _find_best_merge_pair(merged, relatedness, min_entities_per_service)
        if best_pair is None:
            logger.warning(
                "Bounded contexts: cannot find valid merge pair. "
                "Stopping at %d services.",
                len(merged),
            )
            break

        svc_a, svc_b = best_pair
        merged_boundary = _merge_two_boundaries(svc_a, svc_b)
        merged.remove(svc_a)
        merged.remove(svc_b)
        merged.append(merged_boundary)

        # Update relatedness keys for the new merged boundary
        _update_relatedness_after_merge(relatedness, svc_a, svc_b, merged_boundary)

        merge_count += 1
        logger.info(
            "Merged '%s' + '%s' -> '%s' (%d entities). %d remaining.",
            svc_a.name,
            svc_b.name,
            merged_boundary.name,
            len(merged_boundary.entities),
            len(merged),
        )

    # Recompute contracts for the merged set
    result = merged + frontend
    _compute_contracts(result, parsed.relationships)

    logger.info(
        "Bounded contexts: %d services -> %d after %d merges",
        len(backend),
        len(merged),
        merge_count,
    )
    return result


def _build_relatedness_graph(
    boundaries: list[ServiceBoundary],
    parsed: ParsedPRD,
) -> dict[tuple[str, str], float]:
    """Build relatedness scores between every pair of backend services.

    Score components:
      - Cross-boundary entity relationships: +3 per relationship
      - Event pub/sub connections: +2 per event
      - Same tech stack (from explicit_services): +1
    """
    scores: dict[tuple[str, str], float] = {}

    # Index: entity name -> boundary name
    entity_to_boundary: dict[str, str] = {}
    for b in boundaries:
        for ent_name in b.entities:
            entity_to_boundary[ent_name] = b.name

    # Score from entity relationships (FK, references, triggers, etc.)
    for rel in parsed.relationships:
        source = rel.get("source", "")
        target = rel.get("target", "")
        source_svc = entity_to_boundary.get(source)
        target_svc = entity_to_boundary.get(target)

        if source_svc and target_svc and source_svc != target_svc:
            pair = tuple(sorted([source_svc, target_svc]))
            scores[pair] = scores.get(pair, 0) + 3.0

    # Score from event connections
    for event in parsed.events:
        publisher = event.get("publisher", "")
        subscribers = event.get("subscribers", [])
        if isinstance(subscribers, str):
            subscribers = [subscribers]

        for sub in subscribers:
            pub_norm = _normalise_boundary_key(publisher) if publisher else ""
            sub_norm = _normalise_boundary_key(sub) if sub else ""
            # Try to match normalised names to boundary names
            pub_id = _match_boundary_name(pub_norm, boundaries)
            sub_id = _match_boundary_name(sub_norm, boundaries)
            if pub_id and sub_id and pub_id != sub_id:
                pair = tuple(sorted([pub_id, sub_id]))
                scores[pair] = scores.get(pair, 0) + 2.0

    # Score from same tech stack (via explicit_services lookup)
    svc_lang: dict[str, str] = {}
    for svc in parsed.explicit_services:
        svc_name = svc.get("name", "")
        lang = (svc.get("language") or "").lower()
        if svc_name and lang:
            svc_lang[svc_name] = lang

    for i, a in enumerate(boundaries):
        for b in boundaries[i + 1 :]:
            pair = tuple(sorted([a.name, b.name]))
            lang_a = svc_lang.get(a.name, "")
            lang_b = svc_lang.get(b.name, "")
            if lang_a and lang_b and lang_a == lang_b:
                scores[pair] = scores.get(pair, 0) + 1.0

    return scores


def _match_boundary_name(
    normalised: str, boundaries: list[ServiceBoundary]
) -> str | None:
    """Try to match a normalised name to an actual boundary name."""
    if not normalised:
        return None
    for b in boundaries:
        if _normalise_boundary_key(b.name) == normalised:
            return b.name
    return None


def _find_best_merge_pair(
    boundaries: list[ServiceBoundary],
    relatedness: dict[tuple[str, str], float],
    min_entities: int,
) -> tuple[ServiceBoundary, ServiceBoundary] | None:
    """Find the best pair of services to merge."""
    best_score = -1.0
    best_pair: tuple[ServiceBoundary, ServiceBoundary] | None = None

    # Build stack lookup from boundary names
    for i, a in enumerate(boundaries):
        for b in boundaries[i + 1 :]:
            pair_key = tuple(sorted([a.name, b.name]))
            score = relatedness.get(pair_key, 0.0)

            # Prefer merging small services
            if len(a.entities) < min_entities or len(b.entities) < min_entities:
                score += 5.0

            if score > best_score:
                best_score = score
                best_pair = (a, b)

    return best_pair


def _merge_two_boundaries(
    a: ServiceBoundary,
    b: ServiceBoundary,
) -> ServiceBoundary:
    """Merge two service boundaries into one."""
    if len(a.entities) >= len(b.entities):
        primary, secondary = a, b
    else:
        primary, secondary = b, a

    # Combine name
    primary_base = primary.name.replace(" Service", "").replace(" service", "")
    secondary_base = secondary.name.replace(" Service", "").replace(" service", "")
    merged_name = f"{primary_base} & {secondary_base}"
    if len(merged_name) > 50:
        merged_name = primary.name

    # Combine entities (deduplicate)
    seen: set[str] = set()
    merged_entities: list[str] = []
    for ent in list(a.entities) + list(b.entities):
        if ent not in seen:
            seen.add(ent)
            merged_entities.append(ent)

    # Combine contracts (deduplicate)
    merged_provides = list(dict.fromkeys(
        a.provides_contracts + b.provides_contracts
    ))
    merged_consumes = list(dict.fromkeys(
        a.consumes_contracts + b.consumes_contracts
    ))

    return ServiceBoundary(
        name=merged_name,
        domain=_to_kebab_case(merged_name),
        description=f"Bounded context combining {a.name} and {b.name}",
        entities=merged_entities,
        provides_contracts=merged_provides,
        consumes_contracts=merged_consumes,
    )


def _update_relatedness_after_merge(
    relatedness: dict[tuple[str, str], float],
    old_a: ServiceBoundary,
    old_b: ServiceBoundary,
    new: ServiceBoundary,
) -> None:
    """Update the relatedness graph after merging two boundaries.

    Combines scores from both old boundaries into entries keyed by the new name.
    Removes stale entries for the old boundary names.
    """
    stale_keys: list[tuple[str, str]] = []
    additions: dict[tuple[str, str], float] = {}

    for pair_key, score in relatedness.items():
        involves_a = old_a.name in pair_key
        involves_b = old_b.name in pair_key
        if not (involves_a or involves_b):
            continue
        stale_keys.append(pair_key)

        # Determine the "other" boundary name in this pair
        other = pair_key[0] if pair_key[1] in (old_a.name, old_b.name) else pair_key[1]
        if other in (old_a.name, old_b.name):
            continue  # This was the pair between a and b — discard

        new_pair = tuple(sorted([new.name, other]))
        additions[new_pair] = additions.get(new_pair, 0.0) + score

    for key in stale_keys:
        del relatedness[key]
    relatedness.update(additions)


def _compute_contracts(
    boundaries: list[ServiceBoundary],
    relationships: list[dict],
) -> None:
    """Populate ``provides_contracts`` and ``consumes_contracts`` in-place.

    A non-frontend boundary *provides* a contract named ``"{kebab-name}-api"``.
    Frontend boundaries do NOT provide an API contract.
    A boundary *consumes* a contract when one of its entities references an
    entity in another boundary via a non-OWNS relationship.

    Special rules:
    - Frontend boundaries consume ALL backend boundaries' APIs.
    - Reporting/analytics boundaries consume all data-producing service APIs.
    """
    # Build entity -> boundary index
    entity_to_boundary: dict[str, ServiceBoundary] = {}
    for boundary in boundaries:
        for ent in boundary.entities:
            entity_to_boundary[ent] = boundary

    # Each non-frontend boundary provides its own API contract (Fix 12)
    for boundary in boundaries:
        if boundary.is_frontend:
            continue
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
            if rel_type == "HAS_MANY":
                # HAS_MANY: "A has many B" — B holds FK to A, so
                # target_boundary (B) consumes source_boundary (A) API.
                source_contract = f"{_to_kebab_case(source_boundary.name)}-api"
                if source_contract not in target_boundary.consumes_contracts:
                    target_boundary.consumes_contracts.append(source_contract)
            else:
                # BELONGS_TO, REFERENCES, TRIGGERS, etc.: source depends
                # on target, so source_boundary consumes target_boundary API.
                target_contract = f"{_to_kebab_case(target_boundary.name)}-api"
                if target_contract not in source_boundary.consumes_contracts:
                    source_boundary.consumes_contracts.append(target_contract)

    # Collect all backend API contract names for frontend/reporting heuristics
    all_backend_contracts: list[str] = []
    for boundary in boundaries:
        if not boundary.is_frontend:
            for c in boundary.provides_contracts:
                if c not in all_backend_contracts:
                    all_backend_contracts.append(c)

    # Fix 2: Frontend boundaries consume ALL backend APIs
    for boundary in boundaries:
        if boundary.is_frontend:
            for contract in all_backend_contracts:
                if contract not in boundary.consumes_contracts:
                    boundary.consumes_contracts.append(contract)

    # Fix 9: Reporting/analytics services consume all data-producing APIs
    _reporting_keywords = {"report", "reporting", "analytics", "dashboard"}
    for boundary in boundaries:
        if boundary.is_frontend:
            continue
        boundary_lower = boundary.name.lower()
        if any(kw in boundary_lower for kw in _reporting_keywords):
            for contract in all_backend_contracts:
                own_contract = f"{_to_kebab_case(boundary.name)}-api"
                if contract != own_contract and contract not in boundary.consumes_contracts:
                    boundary.consumes_contracts.append(contract)


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
    default_stack = ServiceStack(
        language=hints.get("language") or "python",
        framework=hints.get("framework"),
        database=hints.get("database"),
        message_broker=hints.get("message_broker"),
    )

    # Build per-service stack lookup from explicit_services
    service_stacks: dict[str, ServiceStack] = {}
    if hasattr(parsed, "explicit_services"):
        for svc in getattr(parsed, "explicit_services", []):
            svc_name = svc["name"]
            svc_lang = svc.get("language") or hints.get("language") or "python"
            svc_fw = svc.get("framework") or hints.get("framework")
            service_stacks[svc_name] = ServiceStack(
                language=svc_lang,
                framework=svc_fw,
                database=hints.get("database"),
                message_broker=hints.get("message_broker"),
            )

    services: list[ServiceDefinition] = []
    for boundary in boundaries:
        entity_count = len(boundary.entities)
        raw_loc = entity_count * 500
        estimated_loc = max(100, min(200_000, raw_loc))

        # Use per-service stack if available, otherwise default
        stack = service_stacks.get(boundary.name, default_stack)

        service = ServiceDefinition(
            name=_to_kebab_case(boundary.name),
            domain=boundary.domain,
            description=boundary.description,
            stack=stack,
            estimated_loc=estimated_loc,
            owns_entities=list(boundary.entities),
            provides_contracts=list(boundary.provides_contracts),
            consumes_contracts=list(boundary.consumes_contracts),
            is_frontend=boundary.is_frontend,
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

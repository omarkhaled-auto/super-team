"""Domain modeler service — builds a DomainModel from parsed PRD data.

Converts parsed entities and relationships into fully-typed domain model
objects, detects state machines from status/state/phase fields, and
resolves owning services from service boundary definitions.

This module is a pure function with no global state.
"""
from __future__ import annotations

from src.architect.services.prd_parser import ParsedPRD
from src.architect.services.service_boundary import ServiceBoundary
from src.shared.models.architect import (
    DomainEntity,
    DomainModel,
    DomainRelationship,
    EntityField,
    RelationshipType,
    StateMachine,
    StateTransition,
)

# ---------------------------------------------------------------------------
# Field names that indicate state-machine behaviour in an entity
# ---------------------------------------------------------------------------
_STATE_FIELD_NAMES: frozenset[str] = frozenset(
    {"status", "state", "phase", "lifecycle", "workflow_state"}
)

# ---------------------------------------------------------------------------
# Mapping of raw relationship type strings to RelationshipType enum values
# ---------------------------------------------------------------------------
_RELATIONSHIP_TYPE_MAP: dict[str, RelationshipType] = {
    # OWNS
    "owns": RelationshipType.OWNS,
    "contains": RelationshipType.OWNS,
    "has": RelationshipType.OWNS,
    # REFERENCES
    "references": RelationshipType.REFERENCES,
    "belongs to": RelationshipType.REFERENCES,
    "refers to": RelationshipType.REFERENCES,
    # TRIGGERS
    "triggers": RelationshipType.TRIGGERS,
    "initiates": RelationshipType.TRIGGERS,
    "starts": RelationshipType.TRIGGERS,
    # EXTENDS
    "extends": RelationshipType.EXTENDS,
    "inherits": RelationshipType.EXTENDS,
    # DEPENDS_ON
    "depends on": RelationshipType.DEPENDS_ON,
    "requires": RelationshipType.DEPENDS_ON,
    "uses": RelationshipType.DEPENDS_ON,
}

# ---------------------------------------------------------------------------
# Valid cardinality patterns accepted by DomainRelationship
# ---------------------------------------------------------------------------
_VALID_CARDINALITIES: frozenset[str] = frozenset({"1:1", "1:N", "N:1", "N:N"})

_DEFAULT_CARDINALITY: str = "1:N"


# ===================================================================
# Public API
# ===================================================================


def build_domain_model(
    parsed: ParsedPRD,
    boundaries: list[ServiceBoundary],
) -> DomainModel:
    """Build a complete DomainModel from parsed PRD data and service boundaries.

    Steps:
        1. Convert parsed entities to ``DomainEntity`` instances.
        2. Detect state machines from entity fields and ``parsed.state_machines``.
        3. Determine ``owning_service`` for each entity from *boundaries*.
        4. Convert parsed relationships to ``DomainRelationship`` instances.
        5. Return the complete ``DomainModel``.

    Args:
        parsed: Structured data extracted from a PRD document.
        boundaries: Service boundary definitions with entity ownership.

    Returns:
        A fully populated ``DomainModel`` with entities, relationships,
        and detected state machines.
    """
    # Pre-compute a lookup: entity name -> owning service name
    ownership_map: dict[str, str] = _build_ownership_map(boundaries)

    # Collect entity names so we can later validate relationships
    entity_names: set[str] = {e.get("name", "") for e in parsed.entities}

    # Step 1-3: Build domain entities
    domain_entities: list[DomainEntity] = [
        _build_entity(raw_entity, ownership_map, parsed)
        for raw_entity in parsed.entities
    ]

    # Step 4: Build domain relationships (skip invalid references)
    domain_relationships: list[DomainRelationship] = _build_relationships(
        parsed.relationships, entity_names
    )

    # Step 5: Assemble and return
    return DomainModel(
        entities=domain_entities,
        relationships=domain_relationships,
    )


# ===================================================================
# Internal helpers
# ===================================================================


def _build_ownership_map(boundaries: list[ServiceBoundary]) -> dict[str, str]:
    """Create a mapping from entity name to the service that owns it.

    Iterates over all boundaries and their ``entities`` lists to produce
    a flat ``{entity_name: service_name}`` dictionary.
    """
    ownership: dict[str, str] = {}
    for boundary in boundaries:
        service_name: str = boundary.name
        for entity_name in boundary.entities:
            ownership[entity_name] = service_name
    return ownership


def _build_entity(
    raw: dict,
    ownership_map: dict[str, str],
    parsed: ParsedPRD,
) -> DomainEntity:
    """Convert a single raw parsed entity dict into a ``DomainEntity``.

    Also detects and attaches a ``StateMachine`` if appropriate.
    """
    entity_name: str = raw.get("name", "")
    description: str = raw.get("description", "")
    raw_fields: list[dict] = raw.get("fields", [])

    # Build typed field list
    fields: list[EntityField] = [
        EntityField(
            name=f.get("name", ""),
            type=f.get("type", "string"),
            required=f.get("required", True),
            description=f.get("description", ""),
        )
        for f in raw_fields
    ]

    # Determine owning service
    owning_service: str = ownership_map.get(entity_name, "unassigned")

    # Detect state machine
    state_machine: StateMachine | None = _detect_state_machine(
        entity_name, fields, parsed
    )

    return DomainEntity(
        name=entity_name,
        description=description,
        owning_service=owning_service,
        fields=fields,
        state_machine=state_machine,
    )


def _detect_state_machine(
    entity_name: str,
    fields: list[EntityField],
    parsed: ParsedPRD,
) -> StateMachine | None:
    """Detect whether an entity should have a state machine attached.

    Detection logic:
        1. Look for a field whose name is in ``_STATE_FIELD_NAMES``.
        2. If such a field exists **and** ``parsed.state_machines`` contains
           matching data for this entity, use that rich definition.
        3. Otherwise, if a state-like field exists but no explicit state
           machine definition was parsed, create a minimal default state
           machine (``["active", "inactive"]`` with one transition).
        4. If no state-like field is present, return ``None``.
    """
    # Check if any field is a state-like field
    state_field: EntityField | None = None
    for field in fields:
        if field.name.lower() in _STATE_FIELD_NAMES:
            state_field = field
            break

    if state_field is None:
        return None

    # Look for explicit state machine data in parsed.state_machines
    parsed_sm: dict | None = _find_parsed_state_machine(entity_name, parsed)

    if parsed_sm is not None:
        return _state_machine_from_parsed(parsed_sm)

    # No explicit definition — create a minimal default state machine
    return _default_state_machine()


def _find_parsed_state_machine(
    entity_name: str,
    parsed: ParsedPRD,
) -> dict | None:
    """Find an explicit state machine definition for *entity_name*.

    ``parsed.state_machines`` is expected to be a list of dicts, each
    having at least an ``"entity"`` key identifying which entity it
    belongs to.
    """
    for sm in parsed.state_machines:
        if sm.get("entity", "").lower() == entity_name.lower():
            return sm
    return None


def _state_machine_from_parsed(sm_data: dict) -> StateMachine:
    """Build a ``StateMachine`` from an explicit parsed definition.

    Expected *sm_data* keys:
        - ``states``:  list[str]
        - ``initial_state``: str  (optional — defaults to first state)
        - ``transitions``: list[dict] each with ``from_state``, ``to_state``,
          ``trigger``, and optional ``guard``.
    """
    states: list[str] = sm_data.get("states", ["active", "inactive"])
    initial_state: str = sm_data.get("initial_state", states[0] if states else "active")

    raw_transitions: list[dict] = sm_data.get("transitions", [])
    transitions: list[StateTransition] = [
        StateTransition(
            from_state=t.get("from_state", ""),
            to_state=t.get("to_state", ""),
            trigger=t.get("trigger", ""),
            guard=t.get("guard"),
        )
        for t in raw_transitions
    ]

    # If parsed data provided states but no transitions, infer sequential
    if not transitions and len(states) >= 2:
        transitions = _infer_sequential_transitions(states)

    return StateMachine(
        states=states,
        initial_state=initial_state,
        transitions=transitions,
    )


def _default_state_machine() -> StateMachine:
    """Return a minimal default state machine: active -> inactive."""
    states: list[str] = ["active", "inactive"]
    return StateMachine(
        states=states,
        initial_state=states[0],
        transitions=_infer_sequential_transitions(states),
    )


def _infer_sequential_transitions(states: list[str]) -> list[StateTransition]:
    """Create transitions where each state transitions to the next one.

    For a list ``[A, B, C]`` this produces:
        A -> B  (trigger: "transition_to_B")
        B -> C  (trigger: "transition_to_C")
    """
    transitions: list[StateTransition] = []
    for i in range(len(states) - 1):
        transitions.append(
            StateTransition(
                from_state=states[i],
                to_state=states[i + 1],
                trigger=f"transition_to_{states[i + 1]}",
            )
        )
    return transitions


# -------------------------------------------------------------------
# Relationship helpers
# -------------------------------------------------------------------


def _build_relationships(
    raw_relationships: list[dict],
    valid_entity_names: set[str],
) -> list[DomainRelationship]:
    """Convert raw parsed relationships to typed ``DomainRelationship`` objects.

    Relationships that reference entities not present in *valid_entity_names*
    are silently skipped.
    """
    results: list[DomainRelationship] = []
    for raw in raw_relationships:
        source: str = raw.get("source", "")
        target: str = raw.get("target", "")

        # Skip relationships with non-existent entities
        if source not in valid_entity_names or target not in valid_entity_names:
            continue

        rel_type: RelationshipType = _map_relationship_type(
            raw.get("type", "")
        )
        cardinality: str = _normalise_cardinality(
            raw.get("cardinality", _DEFAULT_CARDINALITY)
        )
        description: str = raw.get("description", "")

        results.append(
            DomainRelationship(
                source_entity=source,
                target_entity=target,
                relationship_type=rel_type,
                cardinality=cardinality,
                description=description,
            )
        )
    return results


def _map_relationship_type(raw_type: str) -> RelationshipType:
    """Map a free-text relationship type string to a ``RelationshipType`` enum.

    The lookup is case-insensitive. Unrecognised types fall back to
    ``RelationshipType.REFERENCES``.
    """
    return _RELATIONSHIP_TYPE_MAP.get(
        raw_type.strip().lower(),
        RelationshipType.REFERENCES,
    )


def _normalise_cardinality(raw: str) -> str:
    """Normalise a cardinality string to one of the valid patterns.

    Accepted raw formats include ``"1:1"``, ``"1:N"``, ``"N:1"``,
    ``"N:N"``, ``"one-to-many"``, ``"many-to-many"`` etc.  If the raw
    value cannot be mapped, returns the default ``"1:N"``.
    """
    cleaned: str = raw.strip().upper()

    # Direct match
    if cleaned in _VALID_CARDINALITIES:
        return cleaned

    # Attempt to parse common prose forms
    normalised = (
        cleaned.replace("ONE", "1")
        .replace("MANY", "N")
        .replace("-TO-", ":")
        .replace(" TO ", ":")
        .replace("_TO_", ":")
    )

    if normalised in _VALID_CARDINALITIES:
        return normalised

    return _DEFAULT_CARDINALITY

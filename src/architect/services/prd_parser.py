"""PRD Parser module for the Architect Service.

Parses Product Requirements Document (PRD) text and extracts structured data
using deterministic regex/string matching. No LLM usage.

Supports 3+ PRD formats:
  - Markdown table patterns
  - Heading + bullet list patterns
  - Sentence / prose patterns
  - Data-model section patterns
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from src.shared.errors import ParsingError
from src.shared.models.architect import RelationshipType

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_MIN_PRD_LENGTH = 30

_LANGUAGES = [
    "Python", "TypeScript", "JavaScript", "Go", "Golang",
    "C#", "CSharp", "Java", "Rust", "Kotlin", "Ruby", "Elixir", "Scala",
]

_FRAMEWORKS = [
    "FastAPI", "Express", "Express.js", "Django", "Flask", "NestJS",
    "Spring", "Spring Boot", "ASP.NET", "Gin", "Echo", "Fiber",
    "Rails", "Ruby on Rails", "Phoenix", "Next.js", "Nuxt",
    "Actix", "Rocket", "Axum", "Ktor",
]

_DATABASES = [
    "PostgreSQL", "Postgres", "MySQL", "MariaDB", "MongoDB",
    "SQLite", "Redis", "DynamoDB", "CockroachDB", "Cassandra",
    "Firestore", "Supabase", "SQL Server", "MSSQL", "Oracle",
    "Neo4j", "InfluxDB", "TimescaleDB", "CouchDB",
]

_MESSAGE_BROKERS = [
    "RabbitMQ", "Kafka", "Apache Kafka", "Redis Pub/Sub",
    "NATS", "Amazon SQS", "AWS SNS", "Google Pub/Sub",
    "Azure Service Bus", "ActiveMQ", "ZeroMQ", "Pulsar",
]

_AUTH_PATTERNS = [
    "JWT", "jwt", "JSON Web Token", "bearer token", "Bearer Token",
    "OAuth", "OAuth2", "OAuth 2.0", "SAML",
    "auth token", "access token", "refresh token",
    "bcrypt", "argon2", "RBAC", "role-based access",
]

_CONTEXT_CLUES: dict[str, tuple[str, str]] = {
    "REST API": ("api_style", "rest"),
    "RESTful": ("api_style", "rest"),
    "GraphQL": ("api_style", "graphql"),
    "gRPC": ("api_style", "grpc"),
    "WebSocket": ("messaging", "websocket"),
    "real-time": ("messaging", "websocket"),
    "send email": ("notification", "email"),
    "email notification": ("notification", "email"),
    "SMS": ("notification", "sms"),
    "push notification": ("notification", "push"),
    "Docker": ("deployment", "docker"),
    "Kubernetes": ("deployment", "kubernetes"),
    "container": ("deployment", "docker"),
    "microservice": ("architecture", "microservices"),
    "event-driven": ("architecture", "event_driven"),
    "CQRS": ("architecture", "cqrs"),
    "saga": ("architecture", "saga"),
}

# Normalisation map (maps alternative spellings to a canonical name).
_LANGUAGE_NORMALISE: dict[str, str] = {
    "golang": "Go",
    "csharp": "C#",
    "javascript": "JavaScript",
}

_DATABASE_NORMALISE: dict[str, str] = {
    "postgres": "PostgreSQL",
    "mariadb": "MariaDB",
    "mssql": "SQL Server",
}

# Relationship keyword -> (RelationshipType, default cardinality)
_RELATIONSHIP_KEYWORDS: list[tuple[str, RelationshipType, str]] = [
    ("belongs to", RelationshipType.OWNS, "N:1"),
    ("owned by", RelationshipType.OWNS, "N:1"),
    ("has many", RelationshipType.OWNS, "1:N"),
    ("has one", RelationshipType.OWNS, "1:1"),
    ("contains", RelationshipType.OWNS, "1:N"),
    ("composed of", RelationshipType.OWNS, "1:N"),
    ("references", RelationshipType.REFERENCES, "N:1"),
    ("refers to", RelationshipType.REFERENCES, "N:1"),
    ("linked to", RelationshipType.REFERENCES, "N:1"),
    ("associated with", RelationshipType.REFERENCES, "N:N"),
    ("triggers", RelationshipType.TRIGGERS, "1:N"),
    ("invokes", RelationshipType.TRIGGERS, "1:N"),
    ("notifies", RelationshipType.TRIGGERS, "1:N"),
    ("extends", RelationshipType.EXTENDS, "1:1"),
    ("inherits from", RelationshipType.EXTENDS, "1:1"),
    ("depends on", RelationshipType.DEPENDS_ON, "N:1"),
    ("requires", RelationshipType.DEPENDS_ON, "N:1"),
]

# Prose relationship patterns for terse PRDs.  Each tuple contains:
# (compiled_regex, RelationshipType, default_cardinality).
# These use \w+ (not [A-Z]) so they also match lowercase entity names.
_PROSE_RELATIONSHIP_PATTERNS: list[tuple[re.Pattern[str], RelationshipType, str]] = [
    (
        re.compile(r"\b(\w+)\s+(?:has\s+many|has\s+multiple|contains)\s+(\w+)", re.IGNORECASE),
        RelationshipType.OWNS,
        "1:N",
    ),
    (
        re.compile(r"\b(\w+)\s+(?:belongs?\s+to|is\s+(?:owned|part)\s+of)\s+(\w+)", re.IGNORECASE),
        RelationshipType.OWNS,
        "N:1",
    ),
    (
        re.compile(r"\b(\w+)\s+(?:references?|refers?\s+to|links?\s+to)\s+(\w+)", re.IGNORECASE),
        RelationshipType.REFERENCES,
        "N:1",
    ),
    (
        re.compile(r"\b(\w+)\s*(?:\u2192|->|=>|triggers?)\s*(\w+)", re.IGNORECASE),
        RelationshipType.TRIGGERS,
        "1:N",
    ),
    (
        re.compile(r"\b(\w+)\s+(?:depends?\s+on|requires?)\s+(\w+)", re.IGNORECASE),
        RelationshipType.DEPENDS_ON,
        "N:1",
    ),
]

_CARDINALITY_MAP: dict[str, str] = {
    "one-to-one": "1:1",
    "one-to-many": "1:N",
    "many-to-one": "N:1",
    "many-to-many": "N:N",
    "1:1": "1:1",
    "1:n": "1:N",
    "n:1": "N:1",
    "n:n": "N:N",
    "1:m": "1:N",
    "m:1": "N:1",
    "n:m": "N:N",
    "m:n": "N:N",
}

# State-related field names that hint at a state machine.
_STATE_FIELD_NAMES = {"status", "state", "phase", "lifecycle", "stage", "workflow_state"}

# Common type aliases encountered in PRDs.
_TYPE_ALIASES: dict[str, str] = {
    "string": "str",
    "text": "str",
    "integer": "int",
    "number": "int",
    "float": "float",
    "decimal": "float",
    "boolean": "bool",
    "bool": "bool",
    "date": "datetime",
    "datetime": "datetime",
    "timestamp": "datetime",
    "uuid": "UUID",
    "id": "UUID",
    "list": "list",
    "array": "list",
    "dict": "dict",
    "map": "dict",
    "object": "dict",
    "email": "str",
    "url": "str",
    "enum": "str",
}

# ---------------------------------------------------------------------------
# Dataclass
# ---------------------------------------------------------------------------


@dataclass
class ParsedPRD:
    """Structured result produced by ``parse_prd``.

    Attributes:
        project_name: Extracted project / product name.
        entities: Domain entities with name, description, fields, owning context.
        relationships: Directed edges between entities.
        bounded_contexts: Service / bounded-context groupings.
        technology_hints: Detected technology mentions.
        state_machines: Detected state-machine definitions.
        interview_questions: Auto-generated clarification questions.
    """

    project_name: str
    entities: list[dict[str, Any]] = field(default_factory=list)
    relationships: list[dict[str, Any]] = field(default_factory=list)
    bounded_contexts: list[dict[str, Any]] = field(default_factory=list)
    technology_hints: dict[str, str | None] = field(default_factory=dict)
    state_machines: list[dict[str, Any]] = field(default_factory=list)
    interview_questions: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def parse_prd(prd_text: str) -> ParsedPRD:
    """Parse a PRD document and return structured ``ParsedPRD`` data.

    This is a **pure, deterministic** function.  It uses regex and string
    matching exclusively -- no LLM calls.

    Args:
        prd_text: Raw PRD text (Markdown or plain text).

    Returns:
        A ``ParsedPRD`` dataclass populated with all extracted artefacts.
        If no entities can be extracted, returns a ``ParsedPRD`` with empty
        entities (never crashes on valid input).

    Raises:
        ParsingError: When the input is too short (below minimum length).
    """
    if not prd_text or len(prd_text.strip()) < _MIN_PRD_LENGTH:
        raise ParsingError(
            f"PRD text is too short (minimum {_MIN_PRD_LENGTH} characters)."
        )

    text = prd_text.strip()

    project_name = _extract_project_name(text)
    entities = _extract_entities(text)

    # If no entities were found, return a valid ParsedPRD with empty entities
    # rather than crashing.  Downstream pipeline handles empty entities
    # gracefully (e.g. service_boundary returns a single default boundary).
    if not entities:
        return ParsedPRD(
            project_name=project_name,
            entities=[],
            relationships=[],
            bounded_contexts=[],
            technology_hints=_extract_technology_hints(text),
            state_machines=[],
            interview_questions=[
                "No entities could be extracted from the PRD. "
                "Please provide entity definitions in a supported format "
                "(Markdown tables, heading+bullets, prose, or data-model sections)."
            ],
        )

    relationships = _extract_relationships(text, entities)
    bounded_contexts = _extract_bounded_contexts(text, entities)
    technology_hints = _extract_technology_hints(text)
    state_machines = _extract_state_machines(text, entities)
    interview_questions = _generate_interview_questions(
        text, entities, relationships, bounded_contexts, technology_hints,
    )

    return ParsedPRD(
        project_name=project_name,
        entities=entities,
        relationships=relationships,
        bounded_contexts=bounded_contexts,
        technology_hints=technology_hints,
        state_machines=state_machines,
        interview_questions=interview_questions,
    )


# ---------------------------------------------------------------------------
# Project name extraction
# ---------------------------------------------------------------------------


def _extract_project_name(text: str) -> str:
    """Extract the project name from headings or the first line.

    Strategy (first match wins):
      1. ``# Project: <name>`` or ``# PRD: <name>`` heading.
      2. The first ``# <heading>`` in the document.
      3. ``Project Name: <name>`` on any line.
      4. Fall back to the first non-empty line.
    """
    # Pattern 1 -- explicit project / PRD heading
    m = re.search(
        r"^#\s+(?:Project|PRD|Product\s+Requirements?\s+Document)\s*[:\-]\s*(.+)",
        text,
        re.MULTILINE | re.IGNORECASE,
    )
    if m:
        return m.group(1).strip().strip("*_")

    # Pattern 2 -- first top-level Markdown heading
    m = re.search(r"^#\s+(.+)", text, re.MULTILINE)
    if m:
        return m.group(1).strip().strip("*_")

    # Pattern 3 -- "Project Name:" line
    m = re.search(
        r"(?:project|product)\s+name\s*[:\-]\s*(.+)",
        text,
        re.IGNORECASE,
    )
    if m:
        return m.group(1).strip().strip("*_")

    # Fallback -- first non-empty line
    for line in text.splitlines():
        stripped = line.strip()
        if stripped:
            return stripped[:120]

    return "Untitled Project"


# ---------------------------------------------------------------------------
# Entity extraction
# ---------------------------------------------------------------------------


def _extract_entities(text: str) -> list[dict[str, Any]]:
    """Extract entity definitions from the PRD using multiple patterns.

    Five extraction strategies are applied in order and their results are
    merged (de-duplicated by normalised entity name).
    """
    entities: dict[str, dict[str, Any]] = {}

    # Strategy 1 -- Markdown tables
    for entity in _extract_entities_from_tables(text):
        key = entity["name"].lower()
        entities.setdefault(key, entity)

    # Strategy 2 -- Heading + bullet lists
    for entity in _extract_entities_from_headings(text):
        key = entity["name"].lower()
        if key in entities:
            _merge_entity(entities[key], entity)
        else:
            entities[key] = entity

    # Strategy 3 -- Sentence / prose patterns
    for entity in _extract_entities_from_sentences(text):
        key = entity["name"].lower()
        if key in entities:
            _merge_entity(entities[key], entity)
        else:
            entities[key] = entity

    # Strategy 4 -- Data model sections
    for entity in _extract_entities_from_data_model_section(text):
        key = entity["name"].lower()
        if key in entities:
            _merge_entity(entities[key], entity)
        else:
            entities[key] = entity

    # Strategy 5 -- Terse / inline patterns (fallback for minimal PRDs)
    for entity in _extract_entities_from_terse_patterns(text):
        key = entity["name"].lower()
        if key in entities:
            _merge_entity(entities[key], entity)
        else:
            entities[key] = entity

    return list(entities.values())


def _merge_entity(existing: dict[str, Any], incoming: dict[str, Any]) -> None:
    """Merge *incoming* entity data into *existing* in-place."""
    if not existing.get("description") and incoming.get("description"):
        existing["description"] = incoming["description"]

    existing_field_names = {f["name"] for f in existing.get("fields", [])}
    for f in incoming.get("fields", []):
        if f["name"] not in existing_field_names:
            existing.setdefault("fields", []).append(f)
            existing_field_names.add(f["name"])

    if not existing.get("owning_context") and incoming.get("owning_context"):
        existing["owning_context"] = incoming["owning_context"]


# -- Strategy 1: Markdown table ------------------------------------------


def _extract_entities_from_tables(text: str) -> list[dict[str, Any]]:
    """Extract entities defined in Markdown tables.

    Supports tables like:

        | Entity | Description |
        |--------|-------------|
        | User   | A registered user |
        | Order  | A purchase order  |

    And field-level tables under an entity heading:

        ### User
        | Field | Type | Required |
        |-------|------|----------|
        | id    | UUID | Yes      |
    """
    entities: list[dict[str, Any]] = []

    # --- Entity-listing tables (| Entity | Description | ...) ---
    table_pattern = re.compile(
        r"^\|[^\n]*(?:entity|name)[^\n]*\|[^\n]*\n"
        r"\|[-:\s|]+\|\s*\n"
        r"((?:\|[^\n]+\n?)+)",
        re.MULTILINE | re.IGNORECASE,
    )
    for m in table_pattern.finditer(text):
        header_line = m.group(0).split("\n")[0]
        headers = [h.strip().lower() for h in header_line.strip().strip("|").split("|")]
        rows_text = m.group(1).strip()
        for row_line in rows_text.splitlines():
            cols = [c.strip() for c in row_line.strip().strip("|").split("|")]
            if len(cols) < 2:
                continue
            name = _to_pascal(cols[0])
            if not name or name.startswith("-"):
                continue
            desc = cols[1] if len(cols) > 1 else ""
            entities.append({
                "name": name,
                "description": desc,
                "fields": [],
                "owning_context": None,
            })

    # --- Field-level tables under a heading ---
    heading_table_pattern = re.compile(
        r"^(#{2,4})\s+(.+?)\s*\n"
        r"(?:.*?\n)*?"
        r"(\|[^\n]*(?:field|attribute|property|column|name)[^\n]*\|\s*\n"
        r"\|[-:\s|]+\|\s*\n"
        r"(?:\|[^\n]+\n?)+)",
        re.MULTILINE | re.IGNORECASE,
    )
    for m in heading_table_pattern.finditer(text):
        raw_heading = m.group(2).strip()
        # Strip leading numbered prefixes: "2.3 Product" -> "Product"
        raw_heading = re.sub(r'^\d+[\.\d]*\s*', '', raw_heading).strip()
        if _is_section_heading(raw_heading):
            continue
        entity_name = _to_pascal(raw_heading)
        # Normalize "UserEntity" -> "User"
        if entity_name.endswith('Entity') and len(entity_name) > 6:
            entity_name = entity_name[:-6]
        table_block = m.group(3)
        fields = _parse_field_table(table_block)
        if entity_name and fields:
            entities.append({
                "name": entity_name,
                "description": "",
                "fields": fields,
                "owning_context": None,
            })

    return entities


def _parse_field_table(table_block: str) -> list[dict[str, Any]]:
    """Parse a Markdown table of fields and return a list of field dicts."""
    lines = table_block.strip().splitlines()
    if len(lines) < 3:
        return []

    headers = [h.strip().lower() for h in lines[0].strip().strip("|").split("|")]
    # Skip separator line (index 1).
    fields: list[dict[str, Any]] = []
    for row_line in lines[2:]:
        cols = [c.strip() for c in row_line.strip().strip("|").split("|")]
        if len(cols) < 1:
            continue
        name = cols[0].strip("`* ")
        if not name or name.startswith("-"):
            continue

        # Determine type and required flag from available columns.
        ftype = "str"
        required = True
        for i, header in enumerate(headers):
            if i >= len(cols):
                break
            val = cols[i].strip()
            if header in ("type", "data type", "datatype"):
                ftype = _normalise_type(val)
            if header in ("required", "nullable", "optional"):
                required = _parse_required(val, header)

        fields.append({"name": _to_snake(name), "type": ftype, "required": required})
    return fields


# -- Strategy 2: Heading + bullet lists ----------------------------------


def _extract_entities_from_headings(text: str) -> list[dict[str, Any]]:
    """Extract entities defined as headings followed by bullet-list fields.

    Example::

        ### User
        Represents a registered user in the system.
        - id: UUID (required)
        - email: string
        - name: string
    """
    # Suffixes that indicate infrastructure/section names rather than entities.
    SKIP_SUFFIXES = (
        'Service', 'Endpoint', 'Endpoints', 'StateMachine', 'StateMachines',
        'Overview', 'Summary', 'Requirements', 'Architecture', 'Configuration',
        'Deployment', 'Integration', 'API', 'Database', 'Schema', 'Migration',
        'Router', 'Controller', 'Workflow', 'Pipeline', 'System', 'Pattern',
        'Patterns', 'Design', 'Flow', 'Diagram', 'Stack', 'Setup', 'Management',
        'Processing', 'Handling', 'Operations', 'Monitoring', 'Logging',
    )

    entities: list[dict[str, Any]] = []
    # Match a heading followed by optional description lines and bullet items.
    pattern = re.compile(
        r"^(#{2,4})\s+([A-Z][A-Za-z0-9_ ]*?)\s*\n"
        r"((?:(?!^#{1,4}\s).*\n)*)",
        re.MULTILINE,
    )
    for m in pattern.finditer(text):
        raw_name = m.group(2).strip()

        # Strip leading numbered prefixes: "1.2.ProjectOverview" -> "ProjectOverview"
        raw_name = re.sub(r'^\d+[\.\d]*\s*', '', raw_name).strip()

        # Skip headings that are clearly section titles, not entities.
        if _is_section_heading(raw_name):
            continue

        body = m.group(3)
        name = _to_pascal(raw_name)

        # Normalize "UserEntity" -> "User"
        if name.endswith('Entity') and len(name) > 6:
            name = name[:-6]

        # Skip names ending with infrastructure/section suffixes
        if any(name.endswith(suffix) for suffix in SKIP_SUFFIXES):
            continue

        description = ""
        fields: list[dict[str, Any]] = []

        for line in body.splitlines():
            stripped = line.strip()
            # Bullet field line: "- field_name: type" or "* field_name (type, required)"
            field_match = re.match(
                r"^[-*]\s+`?(\w+)`?\s*[:\-]\s*(.+)", stripped
            )
            if field_match:
                fname = _to_snake(field_match.group(1))
                rest = field_match.group(2).strip()
                ftype, required = _parse_field_type_from_text(rest)
                fields.append({"name": fname, "type": ftype, "required": required})
            elif stripped and not fields and not description:
                # Treat the first non-bullet line as the description.
                description = stripped

        if name and (fields or description):
            entities.append({
                "name": name,
                "description": description,
                "fields": fields,
                "owning_context": None,
            })

    return entities


# -- Strategy 3: Sentence / prose ----------------------------------------


def _extract_entities_from_sentences(text: str) -> list[dict[str, Any]]:
    """Extract entities from prose patterns.

    Patterns supported:
      - "The system manages {Entity} which has {field1, field2, ...}"
      - "Entity: description" (when preceded by a blank line or at doc start)
      - "{Entity} entity/model/object with fields ..."
    """
    entities: list[dict[str, Any]] = []

    # Pattern A -- "The system manages <Entity> which has <fields>"
    pat_a = re.compile(
        r"(?:system|platform|application|app)\s+"
        r"(?:manages?|tracks?|stores?|maintains?|handles?)\s+"
        r"(?:an?\s+)?([A-Z][A-Za-z]+(?:\s+[A-Z][a-z]+)*)"
        r"(?:\s+(?:which|that|with)\s+(?:has|contains?|includes?)\s+(.+?))?[.\n]",
        re.IGNORECASE,
    )
    for m in pat_a.finditer(text):
        name = _to_pascal(_simple_singularize(m.group(1).strip()))
        fields_text = m.group(2) or ""
        fields = _fields_from_comma_list(fields_text)
        entities.append({
            "name": name,
            "description": "Managed by the system.",
            "fields": fields,
            "owning_context": None,
        })

    # Pattern B -- "<Entity>: description" (standalone line)
    # Additional labels that commonly appear in "Label: description" format
    # but are not domain entities.
    _PAT_B_SKIP_LABELS = {
        "version", "last updated", "project name", "product name",
        "author", "date", "status", "priority", "language", "framework",
        "database", "license", "contact", "team", "owner", "reviewer",
        "note", "warning", "important", "todo", "fixme", "hack",
        "primary database", "cache layer", "message broker",
        "containerization", "api gateway", "valid states",
    }
    pat_b = re.compile(
        r"^([A-Z][A-Za-z]+(?:\s+[A-Z][a-z]+)*)\s*:\s+(.{10,})",
        re.MULTILINE,
    )
    for m in pat_b.finditer(text):
        candidate = m.group(1).strip()
        # Filter out common non-entity labels.
        if _is_section_heading(candidate):
            continue
        if candidate.lower() in _PAT_B_SKIP_LABELS:
            continue
        name = _to_pascal(candidate)
        # Skip names ending with infrastructure suffixes
        if any(name.endswith(s) for s in _HEADING_SUFFIXES):
            continue
        desc = m.group(2).strip().rstrip(".")
        entities.append({
            "name": name,
            "description": desc,
            "fields": [],
            "owning_context": None,
        })

    # Pattern C -- "<Entity> entity/model/object/resource"
    pat_c = re.compile(
        r"\b([A-Z][A-Za-z]+)\s+(?:entity|model|object|resource|record|aggregate)\b",
        re.IGNORECASE,
    )
    seen: set[str] = set()
    for m in pat_c.finditer(text):
        name = _to_pascal(m.group(1).strip())
        if name.lower() in seen or _is_section_heading(name):
            continue
        seen.add(name.lower())
        entities.append({
            "name": name,
            "description": "",
            "fields": [],
            "owning_context": None,
        })

    return entities


# -- Strategy 4: Data model section --------------------------------------


def _extract_entities_from_data_model_section(text: str) -> list[dict[str, Any]]:
    """Extract entities from an explicit ``## Data Model`` / ``## Entities`` section.

    Looks for a level-2 heading, then parses the content within that section
    for sub-headings, tables, or bullet lists describing entities.
    """
    entities: list[dict[str, Any]] = []

    section_pat = re.compile(
        r"^##\s+(?:Data\s+Model|Entities|Domain\s+Model|Entity\s+Definitions?)\s*\n"
        r"((?:(?!^##\s).*\n)*)",
        re.MULTILINE | re.IGNORECASE,
    )
    for sec_match in section_pat.finditer(text):
        section_body = sec_match.group(1)
        # Delegate to heading and table extractors scoped to this section.
        entities.extend(_extract_entities_from_headings(section_body))
        entities.extend(_extract_entities_from_tables(section_body))

    return entities


# -- Strategy 5: Terse / inline patterns ----------------------------------


def _extract_entities_from_terse_patterns(text: str) -> list[dict[str, Any]]:
    """Extract entities from terse or single-sentence PRDs.

    Handles patterns such as:
      - ``"3 entities: User, Task, Notification"``
      - ``"1 entity: Greeting"``
      - ``"Entities: Patient, Provider, Appointment"``
      - ``"Manages users, tasks and notifications"``
      - ``"(User, Task, Notification)"``
      - ``"models: User, Task"`` / ``"data models: X, Y"``
    """
    entities: list[dict[str, Any]] = []

    def _append(names: list[str]) -> None:
        for name in names:
            entities.append({
                "name": name,
                "description": "",
                "fields": [],
                "owning_context": None,
            })

    # Pattern A — "N entities: X, Y, Z" or "entities: X, Y, Z"
    pat_a = re.compile(
        r"(?:\d+\s+)?entit(?:y|ies)\s*:\s*(.+?)(?:\.\s|\.$|\n|$)",
        re.IGNORECASE,
    )
    for m in pat_a.finditer(text):
        _append(_split_entity_list(m.group(1)))

    # Pattern E — after "models:", "data models:", "stores:", "manages:"
    pat_e = re.compile(
        r"\b(?:data\s+)?models?\s*:\s*(.+?)(?:\.\s|\.$|\n|$)",
        re.IGNORECASE,
    )
    for m in pat_e.finditer(text):
        _append(_split_entity_list(m.group(1)))

    # Pattern C — verb + comma-list: "manages users, tasks and notifications"
    pat_c = re.compile(
        r"\b(?:manages?|tracks?|stores?|handles?|maintains?)\s+"
        r"((?:[A-Za-z]+(?:\s*,\s*|\s+and\s+|\s+&\s+))+[A-Za-z]+)",
        re.IGNORECASE,
    )
    for m in pat_c.finditer(text):
        _append(_split_entity_list(m.group(1)))

    # Pattern D — parenthetical entity lists: "(User, Task, Notification)"
    pat_d = re.compile(
        r"\(([A-Z][a-z]+(?:\s*,\s*[A-Z][a-z]+)+)\)",
    )
    for m in pat_d.finditer(text):
        _append(_split_entity_list(m.group(1)))

    return entities


# ---------------------------------------------------------------------------
# Relationship extraction
# ---------------------------------------------------------------------------


def _extract_relationships(
    text: str, entities: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Extract inter-entity relationships from prose and structured content.

    Scans for keyword patterns such as "User has many Orders" and maps them
    to ``RelationshipType`` values with cardinality.
    """
    relationships: list[dict[str, Any]] = []
    # Build lookup mapping lowercase name (and plural variants) -> canonical name.
    entity_lookup = _build_entity_lookup(entities)
    seen: set[tuple[str, str, str]] = set()

    # Build a combined regex for all known relationship keywords.
    for keyword, rel_type, default_card in _RELATIONSHIP_KEYWORDS:
        # E.g. "User has many Order(s)"
        pattern = re.compile(
            r"\b([A-Z][A-Za-z]+)\s+"
            + re.escape(keyword)
            + r"\s+(?:an?\s+)?([A-Z][A-Za-z]+)",
            re.IGNORECASE,
        )
        for m in pattern.finditer(text):
            source_raw = _to_pascal(m.group(1))
            target_raw = _to_pascal(m.group(2))
            source = entity_lookup.get(source_raw.lower())
            target = entity_lookup.get(target_raw.lower())
            # Only record relationships between known entities.
            if source and target:
                sig = (source, target, rel_type.value)
                if sig not in seen:
                    seen.add(sig)
                    # Check if an explicit cardinality is nearby.
                    cardinality = _find_nearby_cardinality(text, m.start(), m.end()) or default_card
                    relationships.append({
                        "source": source,
                        "target": target,
                        "type": rel_type.value,
                        "cardinality": cardinality,
                    })

    # Additional pattern: "relationship between X and Y" or "X <-> Y"
    arrow_pat = re.compile(
        r"\b([A-Z][A-Za-z]+)\s*(?:<->|<-->|-->|->)\s*([A-Z][A-Za-z]+)\b"
    )
    for m in arrow_pat.finditer(text):
        source_raw = _to_pascal(m.group(1))
        target_raw = _to_pascal(m.group(2))
        source = entity_lookup.get(source_raw.lower())
        target = entity_lookup.get(target_raw.lower())
        if source and target:
            sig = (source, target, RelationshipType.REFERENCES.value)
            if sig not in seen:
                seen.add(sig)
                relationships.append({
                    "source": source,
                    "target": target,
                    "type": RelationshipType.REFERENCES.value,
                    "cardinality": "N:1",
                })

    # Supplemental pass — prose relationship patterns for terse PRDs.
    # These use \w+ groups so they also match lowercase entity names
    # (resolved via entity_lookup which includes plural/singular forms).
    for prose_pat, rel_type, default_card in _PROSE_RELATIONSHIP_PATTERNS:
        for m in prose_pat.finditer(text):
            source_raw = _to_pascal(_simple_singularize(m.group(1)))
            target_raw = _to_pascal(_simple_singularize(m.group(2)))
            source = entity_lookup.get(source_raw.lower())
            target = entity_lookup.get(target_raw.lower())
            if source and target and source != target:
                sig = (source, target, rel_type.value)
                if sig not in seen:
                    seen.add(sig)
                    cardinality = _find_nearby_cardinality(text, m.start(), m.end()) or default_card
                    relationships.append({
                        "source": source,
                        "target": target,
                        "type": rel_type.value,
                        "cardinality": cardinality,
                    })

    return relationships


def _find_nearby_cardinality(text: str, start: int, end: int) -> str | None:
    """Look for an explicit cardinality string near *start..end*."""
    window = text[max(0, start - 60): min(len(text), end + 60)].lower()
    for label, normalised in _CARDINALITY_MAP.items():
        if label in window:
            return normalised
    return None


# ---------------------------------------------------------------------------
# Bounded context / service extraction
# ---------------------------------------------------------------------------


def _extract_bounded_contexts(
    text: str, entities: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Identify bounded contexts (services) and group entities under them.

    Detection strategies:
      1. Explicit headings: ``## Service: UserService``, ``### User Service``
      2. Prose mentions: "the User Service handles ..."
      3. ``## Bounded Context:`` headings
    """
    contexts: dict[str, dict[str, Any]] = {}

    # Pattern 1 -- Section headings
    heading_pat = re.compile(
        r"^#{2,4}\s+(?:Service|Bounded\s+Context|Context|Microservice)\s*"
        r"[:\-]\s*(.+)",
        re.MULTILINE | re.IGNORECASE,
    )
    for m in heading_pat.finditer(text):
        name = m.group(1).strip().strip("*_")
        key = _normalise_context_name(name)
        if key not in contexts:
            # Grab the next paragraph as description.
            desc = _grab_next_paragraph(text, m.end())
            contexts[key] = {"name": name, "description": desc, "entities": []}

    # Pattern 2 -- Heading that ends with "Service"
    service_heading_pat = re.compile(
        r"^#{2,4}\s+((?:[A-Z][A-Za-z]+\s+)*Service)\s*$",
        re.MULTILINE,
    )
    for m in service_heading_pat.finditer(text):
        name = m.group(1).strip()
        key = _normalise_context_name(name)
        if key not in contexts:
            desc = _grab_next_paragraph(text, m.end())
            contexts[key] = {"name": name, "description": desc, "entities": []}

    # Pattern 3 -- Prose: "the Foo Service manages/handles ..."
    prose_pat = re.compile(
        r"\b((?:[A-Z][a-z]+\s+)+Service)\b",
        re.MULTILINE,
    )
    for m in prose_pat.finditer(text):
        name = m.group(1).strip()
        key = _normalise_context_name(name)
        if key not in contexts:
            contexts[key] = {"name": name, "description": "", "entities": []}

    # Assign entities to contexts based on proximity and mentions.
    _assign_entities_to_contexts(text, entities, contexts)

    return list(contexts.values())


def _normalise_context_name(name: str) -> str:
    """Return a lowercase key for context de-duplication."""
    return re.sub(r"\s+", " ", name).strip().lower()


def _grab_next_paragraph(text: str, pos: int) -> str:
    """Return the first non-empty paragraph after *pos*."""
    remaining = text[pos:]
    for line in remaining.splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            return stripped[:300]
    return ""


def _assign_entities_to_contexts(
    text: str,
    entities: list[dict[str, Any]],
    contexts: dict[str, dict[str, Any]],
) -> None:
    """Best-effort assignment of entities to bounded contexts."""
    text_lower = text.lower()
    for entity in entities:
        ename = entity["name"]
        ename_lower = ename.lower()
        assigned = False

        # Check if any context heading section mentions this entity.
        for key, ctx in contexts.items():
            ctx_name_lower = ctx["name"].lower()
            # Simple heuristic: entity name appears within ~500 chars of context name.
            idx = text_lower.find(ctx_name_lower)
            while idx != -1:
                window = text_lower[idx: idx + 500]
                if ename_lower in window:
                    if ename not in ctx["entities"]:
                        ctx["entities"].append(ename)
                    entity["owning_context"] = ctx["name"]
                    assigned = True
                    break
                idx = text_lower.find(ctx_name_lower, idx + 1)
            if assigned:
                break

        # Fallback: match by name similarity (e.g. User -> User Service).
        if not assigned:
            for key, ctx in contexts.items():
                if ename_lower in key:
                    ctx["entities"].append(ename)
                    entity["owning_context"] = ctx["name"]
                    break


# ---------------------------------------------------------------------------
# Technology hints extraction
# ---------------------------------------------------------------------------


def _extract_technology_hints(text: str) -> dict[str, str | None]:
    """Scan the PRD for technology mentions and return the first match per category."""
    hints: dict[str, str | None] = {
        "language": None,
        "framework": None,
        "database": None,
        "message_broker": None,
    }

    hints["language"] = _first_mention(text, _LANGUAGES, _LANGUAGE_NORMALISE)
    hints["framework"] = _first_mention(text, _FRAMEWORKS, {})
    hints["database"] = _first_mention(text, _DATABASES, _DATABASE_NORMALISE)
    hints["message_broker"] = _first_mention(text, _MESSAGE_BROKERS, {})

    # Auth / token detection
    auth_hint = _first_mention(text, _AUTH_PATTERNS, {})
    if auth_hint:
        hints["auth"] = auth_hint.lower()

    # Context-based technology detection
    for pattern, (key, value) in _CONTEXT_CLUES.items():
        if re.search(rf"\b{re.escape(pattern)}\b", text, re.IGNORECASE):
            if key not in hints:  # Don't override explicit mentions
                hints[key] = value

    return hints


def _first_mention(
    text: str,
    candidates: list[str],
    normalise_map: dict[str, str],
) -> str | None:
    """Return the first candidate found in *text* (case-insensitive word match)."""
    for candidate in candidates:
        pattern = re.compile(r"\b" + re.escape(candidate) + r"\b", re.IGNORECASE)
        if pattern.search(text):
            canonical = normalise_map.get(candidate.lower(), candidate)
            return canonical
    return None


# ---------------------------------------------------------------------------
# State machine detection
# ---------------------------------------------------------------------------


def _extract_state_machines(
    text: str, entities: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Detect state machines from entity fields and transition descriptions.

    Detection strategies:
      1. Entity fields named status/state/phase with enum-like values.
      2. Prose patterns: "<Entity> transitions from <A> to <B>".
      3. Status workflow descriptions with arrow notation.
    """
    machines: list[dict[str, Any]] = []
    processed_entities: set[str] = set()

    # Strategy 1 -- status fields with enum values
    for entity in entities:
        for fld in entity.get("fields", []):
            if fld["name"] in _STATE_FIELD_NAMES:
                # Look for enum values near this entity in the text.
                states = _find_enum_values_near_entity(text, entity["name"])
                if len(states) >= 2:
                    transitions = _infer_linear_transitions(states)
                    machines.append({
                        "entity": entity["name"],
                        "states": states,
                        "transitions": transitions,
                    })
                    processed_entities.add(entity["name"].lower())

    # Strategy 2 -- explicit transition sentences
    trans_pat = re.compile(
        r"\b([A-Z][A-Za-z]+)\s+transitions?\s+from\s+[\"']?(\w+)[\"']?\s+to\s+[\"']?(\w+)[\"']?",
        re.IGNORECASE,
    )
    for m in trans_pat.finditer(text):
        entity_name = _to_pascal(m.group(1))
        from_state = m.group(2).lower()
        to_state = m.group(3).lower()
        machine = _find_or_create_machine(machines, entity_name)
        _add_state(machine, from_state)
        _add_state(machine, to_state)
        _add_transition(machine, from_state, to_state, f"{from_state}_to_{to_state}")

    # Strategy 3 -- arrow notation: "pending -> confirmed -> shipped"
    arrow_pat = re.compile(
        r"\b([A-Z][A-Za-z]+)\s*(?:status|state|lifecycle|workflow)\s*"
        r"[:\-]\s*([\w]+(?:\s*(?:->|-->|=>|,)\s*[\w]+)+)",
        re.IGNORECASE,
    )
    for m in arrow_pat.finditer(text):
        entity_name = _to_pascal(m.group(1))
        raw_states = re.split(r"\s*(?:->|-->|=>|,)\s*", m.group(2))
        states = [s.strip().lower() for s in raw_states if s.strip()]
        if len(states) >= 2:
            machine = _find_or_create_machine(machines, entity_name)
            for s in states:
                _add_state(machine, s)
            for i in range(len(states) - 1):
                _add_transition(
                    machine, states[i], states[i + 1],
                    f"{states[i]}_to_{states[i + 1]}",
                )

    # Strategy 4 -- heading-separated format:
    #   #### Task Status State Machine
    #   todo -> in_progress -> done
    # or:
    #   #### Order State Machine
    #   pending --> confirmed  (payment captured)
    #   confirmed --> shipped  (warehouse marks shipped)
    heading_sm_pat = re.compile(
        r"^#{2,5}\s+([A-Z][A-Za-z]+(?:\s+[A-Z][a-z]+)*)\s+"
        r"(?:Status\s+)?State\s+Machine\s*\n"
        r"((?:(?!^#{1,5}\s).*\n)*)",
        re.MULTILINE | re.IGNORECASE,
    )
    for m in heading_sm_pat.finditer(text):
        entity_name = _to_pascal(m.group(1).strip())
        body = m.group(2)

        # Parse arrow-notation transitions from the body
        transition_pat = re.compile(
            r"(\w+)\s*(?:->|-->|=>)\s*(\w+)"
        )
        for t_match in transition_pat.finditer(body):
            from_state = t_match.group(1).strip().lower()
            to_state = t_match.group(2).strip().lower()
            machine = _find_or_create_machine(machines, entity_name)
            _add_state(machine, from_state)
            _add_state(machine, to_state)
            _add_transition(machine, from_state, to_state, f"{from_state}_to_{to_state}")

    return machines


def _find_enum_values_near_entity(text: str, entity_name: str) -> list[str]:
    """Find enum-like state values mentioned near the entity name.

    Looks for patterns like:
      - ``Order status: pending | confirmed | shipped``
      - ``Order states: [draft, published, archived]``
      - ``Order can be pending, active, completed, or cancelled``

    Prefers patterns that explicitly mention the entity name to avoid
    attributing another entity's states to this one.
    """
    text_lower = text.lower()
    ename_lower = entity_name.lower()

    # Priority 1: "<Entity> status/state: val1, val2, ..." (explicit entity mention)
    explicit_pat = re.compile(
        re.escape(ename_lower)
        + r"\s+(?:status|state|phase|lifecycle)\s*[:\-]\s*"
        + r"[\[\"']?([\w]+(?:\s*[,|/]\s*[\w]+)+)[\]\"']?",
        re.IGNORECASE,
    )
    m = explicit_pat.search(text)
    if m:
        raw = re.split(r"\s*[,|/]\s*", m.group(1))
        return [v.strip().lower() for v in raw if v.strip()]

    # Priority 2: "<Entity> can be <state1>, <state2>, or <state3>"
    explicit_can_be = re.compile(
        re.escape(ename_lower)
        + r"\s+(?:can\s+be|may\s+be|is\s+either)\s+"
        + r"([\w]+(?:\s*,\s*[\w]+)*(?:\s*,?\s*(?:or|and)\s+[\w]+))",
        re.IGNORECASE,
    )
    m = explicit_can_be.search(text)
    if m:
        raw = re.split(r"\s*(?:,|or|and)\s*", m.group(1))
        return [v.strip().lower() for v in raw if v.strip()]

    # Priority 3: Look within the entity's own definition block (heading section).
    # Find the entity heading and limit search to its body.
    heading_pat = re.compile(
        r"^#{2,4}\s+" + re.escape(entity_name) + r"\s*\n"
        r"((?:(?!^#{1,4}\s).*\n)*)",
        re.MULTILINE,
    )
    hm = heading_pat.search(text)
    if hm:
        block = hm.group(1)
        enum_pat = re.compile(
            r"(?:status|state|phase|lifecycle)\s*[:\-]\s*"
            r"[\[\"']?([\w]+(?:\s*[,|/]\s*[\w]+)+)[\]\"']?",
            re.IGNORECASE,
        )
        m = enum_pat.search(block)
        if m:
            raw = re.split(r"\s*[,|/]\s*", m.group(1))
            return [v.strip().lower() for v in raw if v.strip()]

    return []


def _find_or_create_machine(
    machines: list[dict[str, Any]], entity_name: str
) -> dict[str, Any]:
    """Find an existing machine for the entity or create a new one."""
    for machine in machines:
        if machine["entity"].lower() == entity_name.lower():
            return machine
    new_machine: dict[str, Any] = {
        "entity": entity_name,
        "states": [],
        "transitions": [],
    }
    machines.append(new_machine)
    return new_machine


def _add_state(machine: dict[str, Any], state: str) -> None:
    """Add a state to the machine if not already present."""
    if state not in machine["states"]:
        machine["states"].append(state)


def _add_transition(
    machine: dict[str, Any], from_state: str, to_state: str, trigger: str
) -> None:
    """Add a transition to the machine if not already present."""
    for t in machine["transitions"]:
        if t["from_state"] == from_state and t["to_state"] == to_state:
            return
    machine["transitions"].append({
        "from_state": from_state,
        "to_state": to_state,
        "trigger": trigger,
    })


def _infer_linear_transitions(states: list[str]) -> list[dict[str, str]]:
    """Infer sequential transitions from an ordered list of states."""
    transitions: list[dict[str, str]] = []
    for i in range(len(states) - 1):
        transitions.append({
            "from_state": states[i],
            "to_state": states[i + 1],
            "trigger": f"{states[i]}_to_{states[i + 1]}",
        })
    return transitions


# ---------------------------------------------------------------------------
# Interview question generation
# ---------------------------------------------------------------------------


def _generate_interview_questions(
    text: str,
    entities: list[dict[str, Any]],
    relationships: list[dict[str, Any]],
    bounded_contexts: list[dict[str, Any]],
    technology_hints: dict[str, str | None],
) -> list[str]:
    """Generate clarification questions for ambiguous or missing requirements.

    This is deterministic: questions are produced based on pattern-detected
    gaps, not by an LLM.
    """
    questions: list[str] = []
    text_lower = text.lower()

    # Authentication mentioned but not specified?
    if re.search(r"\b(?:auth|login|sign[- ]?in|authentication|authorization)\b", text_lower):
        if not re.search(
            r"\b(?:oauth|jwt|session|saml|openid|api[- ]?key|bearer|token[- ]?based|cookie)\b",
            text_lower,
        ):
            questions.append(
                "What authentication mechanism should be used (e.g., JWT, OAuth2, session-based)?"
            )

    # No database specified?
    if technology_hints.get("database") is None:
        questions.append(
            "Which database technology should be used for persistence?"
        )

    # No message broker but multiple services detected?
    if len(bounded_contexts) > 1 and technology_hints.get("message_broker") is None:
        questions.append(
            "How should services communicate asynchronously? "
            "Is a message broker (e.g., RabbitMQ, Kafka) required?"
        )

    # Entities without fields?
    fieldless = [e["name"] for e in entities if not e.get("fields")]
    if fieldless:
        names = ", ".join(fieldless[:5])
        suffix = f" (and {len(fieldless) - 5} more)" if len(fieldless) > 5 else ""
        questions.append(
            f"What fields/attributes should the following entities have: {names}{suffix}?"
        )

    # No relationships found?
    if not relationships and len(entities) > 1:
        questions.append(
            "What are the relationships between the identified entities?"
        )

    # Pagination / listing mentioned?
    if re.search(r"\b(?:list|search|filter|paginate|browse)\b", text_lower):
        if not re.search(r"\b(?:page\s*size|limit|offset|cursor|per\s*page)\b", text_lower):
            questions.append(
                "What pagination strategy and default page size should be used for list endpoints?"
            )

    # Payment / billing mentioned?
    if re.search(r"\b(?:payment|billing|checkout|charge|invoice|subscription)\b", text_lower):
        if not re.search(r"\b(?:stripe|paypal|braintree|adyen|square|paddle)\b", text_lower):
            questions.append(
                "Which payment provider should be integrated (e.g., Stripe, PayPal)?"
            )

    # File upload mentioned?
    if re.search(r"\b(?:upload|file|image|attachment|media|document)\b", text_lower):
        if not re.search(r"\b(?:s3|blob|gcs|cloudinary|minio|local\s*storage)\b", text_lower):
            questions.append(
                "Where should uploaded files be stored (e.g., S3, GCS, local filesystem)?"
            )

    # Email / notification mentioned?
    if re.search(r"\b(?:email|notification|alert|sms|push\s*notification)\b", text_lower):
        if not re.search(r"\b(?:sendgrid|ses|mailgun|twilio|firebase\s*cloud\s*messaging)\b", text_lower):
            questions.append(
                "Which email/notification provider should be used?"
            )

    # No language specified?
    if technology_hints.get("language") is None:
        questions.append(
            "What programming language should be used for the backend services?"
        )

    # Caching mentioned?
    if re.search(r"\b(?:cach(?:e|ing)|performance|latency|speed)\b", text_lower):
        if not re.search(r"\b(?:redis|memcached|varnish|cdn|in[- ]?memory)\b", text_lower):
            questions.append(
                "What caching strategy should be employed for performance?"
            )

    return questions


# ---------------------------------------------------------------------------
# Utility helpers
# ---------------------------------------------------------------------------


def _build_entity_lookup(entities: list[dict[str, Any]]) -> dict[str, str]:
    """Build a lookup dict mapping lowercase names (including plural/singular forms) to canonical names.

    For an entity named ``Order``, the lookup will contain::

        {"order": "Order", "orders": "Order"}
    """
    lookup: dict[str, str] = {}
    for entity in entities:
        canonical = entity["name"]
        lower = canonical.lower()
        lookup[lower] = canonical
        # Add common plural forms so "Orders" resolves to "Order".
        lookup[_simple_pluralize(lower)] = canonical
        # Add singular form so "Product" resolves even if stored as "Products".
        singular = _simple_singularize(lower)
        if singular != lower:
            lookup[singular] = canonical
    return lookup


def _simple_pluralize(word: str) -> str:
    """Return a naive English plural for *word*."""
    if not word:
        return word
    if word.endswith("s") or word.endswith("x") or word.endswith("z"):
        return word + "es"
    if word.endswith("sh") or word.endswith("ch"):
        return word + "es"
    if word.endswith("y") and len(word) > 1 and word[-2] not in "aeiou":
        return word[:-1] + "ies"
    return word + "s"


def _simple_singularize(word: str) -> str:
    """Return a naive English singular for *word*.

    Handles common English plural rules.  This is intentionally simple
    (no dictionary lookup) and optimised for PascalCase domain entity names
    commonly found in PRDs (e.g. Orders, Products, Warehouses, Categories).
    """
    if not word:
        return word
    lower = word.lower()
    # "ies" -> "y" (e.g. "Categories" -> "Category")
    if lower.endswith("ies") and len(lower) > 3:
        return word[:-3] + "y"
    # "sses" -> strip "es" (e.g. "Addresses" -> "Address", "Classes" -> "Class")
    if lower.endswith("sses"):
        return word[:-2]
    # "zzes" -> strip "es" (e.g. "Quizzes" -> "Quiz")
    if lower.endswith("zzes"):
        return word[:-3]
    # "shes" -> strip "es" (e.g. "Bushes" -> "Bush")
    if lower.endswith("shes"):
        return word[:-2]
    # "ches" -> strip "es" (e.g. "Batches" -> "Batch")
    if lower.endswith("ches"):
        return word[:-2]
    # "xes" -> strip "es" (e.g. "Boxes" -> "Box", "Indexes" -> "Index")
    if lower.endswith("xes"):
        return word[:-2]
    # Generic "s" removal -- covers the vast majority of entity names.
    # "Orders" -> "Order", "Warehouses" -> "Warehouse", "Phases" -> "Phase",
    # "Responses" -> "Response", "Databases" -> "Database", "Services" -> "Service"
    if lower.endswith("s") and not lower.endswith("ss"):
        return word[:-1]
    return word


# Headings / labels that should NOT be treated as entity names.
_SECTION_KEYWORDS = {
    "overview", "introduction", "summary", "requirements", "description",
    "features", "architecture", "deployment", "testing", "security",
    "authentication", "authorization", "api", "endpoints", "notes",
    "glossary", "appendix", "references", "changelog", "versioning",
    "scope", "background", "goals", "constraints", "assumptions",
    "dependencies", "risks", "timeline", "milestones", "deliverables",
    "stakeholders", "user stories", "use cases", "functional requirements",
    "non-functional requirements", "acceptance criteria", "data model",
    "entities", "domain model", "entity definitions", "technology stack",
    "tech stack", "stack", "services", "bounded contexts", "context map",
    "table of contents", "revision history", "conclusion",
    "project", "prd",
    # Additional section keywords to reduce false positives
    "relationships", "data", "configuration", "monitoring",
    "logging", "conventions", "performance",
    # Multi-word section patterns
    "data flow", "api endpoints", "service boundaries",
    "non-functional", "state machine", "state machines",
    # Infrastructure / architecture section headings
    "system overview", "project overview", "technical requirements",
    "functional requirements", "implementation", "implementation details",
    "integration", "notifications", "error handling", "api design",
    "database design", "service architecture",
    # Contract / API section headings
    "api contracts", "api contracts summary", "contracts summary",
    "cross-service relationships", "cross service relationships",
    "non-functional requirements",
}

# Single-word generic terms that should never be extracted as entities.
# Only includes words that are clearly section headings or too abstract
# to be domain entities. Legitimate domain nouns (Task, Event, etc.) are
# intentionally excluded from this list.
_GENERIC_SINGLE_WORDS = {
    "data", "status", "type", "state", "result", "response", "request",
    "error", "action", "config", "option", "setting",
    "value", "list", "table", "field", "key", "index", "node",
    "overview", "relationships", "requirements", "summary", "endpoints",
    "architecture", "background", "introduction", "scope", "dependencies",
    "configuration", "deployment", "testing", "security", "performance",
    "monitoring", "logging", "conventions",
    # Additional generic words that should never be standalone entities
    "model", "name", "description", "title", "content", "item", "items",
    "details", "info", "information", "properties", "attributes",
}


# Suffixes on PascalCase / multi-word names that indicate a section heading
# rather than a domain entity.
_HEADING_SUFFIXES = (
    'Service', 'Endpoint', 'Endpoints', 'StateMachine', 'StateMachines',
    'Overview', 'Summary', 'Requirements', 'Architecture', 'Configuration',
    'Deployment', 'Integration', 'API', 'Database', 'Schema', 'Migration',
    'Router', 'Controller', 'Workflow', 'Pipeline', 'System', 'Pattern',
    'Patterns', 'Design', 'Flow', 'Diagram', 'Stack', 'Setup', 'Management',
    'Processing', 'Handling', 'Operations', 'Monitoring', 'Logging',
)


def _is_section_heading(name: str) -> bool:
    """Return True if *name* looks like a section heading rather than an entity."""
    normalised = name.strip().lower()
    if normalised in _SECTION_KEYWORDS:
        return True
    # Reject single-word entities that are too generic
    if " " not in normalised and normalised in _GENERIC_SINGLE_WORDS:
        return True

    # Strip leading numbered prefixes for comparison: "1.2 System Overview" -> "System Overview"
    stripped = re.sub(r'^\d+[\.\d]*\s*', '', name).strip()
    if stripped.lower() in _SECTION_KEYWORDS:
        return True

    # Check if the PascalCase name ends with an infrastructure/section suffix
    pascal = _to_pascal(stripped)
    if any(pascal.endswith(suffix) for suffix in _HEADING_SUFFIXES):
        return True

    return False


def _to_pascal(name: str) -> str:
    """Convert a string to PascalCase.

    Examples::

        "user account"    -> "UserAccount"
        "order_item"      -> "OrderItem"
        "UserProfile"     -> "UserProfile"  (no change)
        "OrderItem Entity" -> "OrderItemEntity"
    """
    if not name:
        return ""
    # Strip Markdown formatting.
    name = name.strip().strip("`*_")
    # If already PascalCase (single word or multi-word), return as-is.
    if re.match(r"^[A-Z][a-zA-Z0-9]*$", name) and not name.islower():
        return name
    # Split on spaces, underscores, hyphens.
    parts = re.split(r"[\s_\-]+", name)

    def _capitalize_part(word: str) -> str:
        """Capitalize the first letter but preserve existing casing.

        "orderItem" -> "OrderItem" (not "Orderitem")
        "user"      -> "User"
        """
        if not word:
            return ""
        # If already starts with uppercase and has mixed case, preserve it
        if len(word) > 1 and word[0].isupper() and not word.isupper():
            return word
        # If all lowercase, capitalize normally
        if word.islower():
            return word.capitalize()
        # If all uppercase (like "API"), keep as-is
        if word.isupper():
            return word
        # Mixed case starting with lowercase: capitalize first letter
        return word[0].upper() + word[1:]

    return "".join(_capitalize_part(word) for word in parts if word)


def _to_snake(name: str) -> str:
    """Convert a string to snake_case.

    Examples::

        "firstName" -> "first_name"
        "OrderItem" -> "order_item"
        "user_id"   -> "user_id" (no change)
    """
    if not name:
        return ""
    name = name.strip().strip("`*_")
    # Insert underscore before uppercase letters.
    s1 = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1_\2", name)
    s2 = re.sub(r"([a-z\d])([A-Z])", r"\1_\2", s1)
    return re.sub(r"[\s\-]+", "_", s2).lower()


def _normalise_type(raw: str) -> str:
    """Normalise a raw type string to a Python-friendly type name."""
    cleaned = raw.strip().strip("`*_").lower()
    # Strip array/list wrappers: "list[string]" -> "list"
    base = re.match(r"^(\w+)", cleaned)
    if base:
        key = base.group(1).lower()
        return _TYPE_ALIASES.get(key, raw.strip())
    return raw.strip()


def _parse_required(value: str, header: str) -> bool:
    """Parse a required/optional/nullable column value into a boolean."""
    val_lower = value.strip().lower()
    if header in ("nullable", "optional"):
        return val_lower not in ("yes", "true", "y", "1", "x")
    # header == "required"
    return val_lower in ("yes", "true", "y", "1", "x", "required")


def _parse_field_type_from_text(text: str) -> tuple[str, bool]:
    """Parse a field type and required flag from free-form text.

    Examples::

        "string (required)" -> ("str", True)
        "int, optional"     -> ("int", False)
        "UUID"              -> ("UUID", True)
    """
    required = True
    if re.search(r"\b(?:optional|nullable)\b", text, re.IGNORECASE):
        required = False
    if re.search(r"\b(?:required|mandatory|not\s*null)\b", text, re.IGNORECASE):
        required = True

    # Extract the type token (first word-like token).
    type_match = re.match(r"^[`*]?(\w+)", text.strip())
    if type_match:
        ftype = _normalise_type(type_match.group(1))
    else:
        ftype = "str"

    return ftype, required


def _fields_from_comma_list(text: str) -> list[dict[str, Any]]:
    """Parse a comma-separated list of field names into field dicts.

    Example::

        "name, email, created_at" -> [{"name": "name", ...}, ...]
    """
    if not text.strip():
        return []
    raw_items = re.split(r"\s*,\s*", text.strip())
    fields: list[dict[str, Any]] = []
    for item in raw_items:
        # Each item might be "field_name" or "field_name (type)"
        m = re.match(r"(\w+)(?:\s*\((\w+)\))?", item.strip())
        if m:
            fname = _to_snake(m.group(1))
            ftype = _normalise_type(m.group(2)) if m.group(2) else "str"
            fields.append({"name": fname, "type": ftype, "required": True})
    return fields


def _split_entity_list(text: str) -> list[str]:
    """Split a comma/and-separated list of entity names into PascalCase names.

    Handles patterns like ``"User, Task, Notification"`` or
    ``"users, tasks and notifications"``.  Each token is singularised and
    converted to PascalCase.  Generic / section-heading words are filtered.
    """
    parts = re.split(r"\s*(?:,\s*(?:and\s+)?|\band\b\s*|\b&\b\s*)\s*", text.strip())
    names: list[str] = []
    for part in parts:
        part = part.strip().strip(".")
        if not part or len(part) < 2:
            continue
        name = _to_pascal(_simple_singularize(part))
        if (
            name
            and name.lower() not in _GENERIC_SINGLE_WORDS
            and not _is_section_heading(name)
        ):
            names.append(name)
    return names

"""Tests for the PRD parser module.

Covers entity extraction (tables, headings, prose, data-model sections),
relationship extraction, bounded context detection, technology hint scanning,
state machine detection, interview question generation, project name
extraction, error cases, and edge cases such as entity merging.
"""
from __future__ import annotations

import pytest

from src.architect.services.prd_parser import parse_prd, ParsedPRD
from src.shared.errors import ParsingError


# ---------------------------------------------------------------------------
# Fixtures -- reusable PRD text fragments
# ---------------------------------------------------------------------------


@pytest.fixture()
def minimal_table_prd() -> str:
    """A minimal PRD with an entity-listing Markdown table."""
    return (
        "# Inventory System\n\n"
        "## Data Model\n\n"
        "| Entity | Description |\n"
        "|--------|-------------|\n"
        "| Product | A product in the catalog |\n"
        "| Warehouse | A physical storage location |\n"
    )


@pytest.fixture()
def heading_bullets_prd() -> str:
    """A PRD that defines entities via heading + bullet-list fields."""
    return (
        "# Task Tracker\n\n"
        "## Entities\n\n"
        "### Task\n"
        "Represents a unit of work.\n"
        "- id: UUID (required)\n"
        "- title: string\n"
        "- status: string (optional)\n"
        "\n"
        "### Assignee\n"
        "A person assigned to tasks.\n"
        "- id: UUID (required)\n"
        "- name: string\n"
        "- email: string\n"
    )


@pytest.fixture()
def prose_prd() -> str:
    """A PRD that mentions entities only in prose/sentences."""
    return (
        "# Fleet Manager\n\n"
        "The system manages Vehicle which has vin, make, model.\n"
        "The application tracks Driver which has license_number, name.\n"
    )


@pytest.fixture()
def relationship_prd() -> str:
    """A PRD with relationship keywords between known entities."""
    return (
        "# School Portal\n\n"
        "| Entity | Description |\n"
        "|--------|-------------|\n"
        "| Teacher | A school teacher |\n"
        "| Student | A school student |\n"
        "| Course  | An academic course |\n"
        "\n"
        "Teacher has many Student.\n"
        "Student belongs to Course.\n"
        "Course references Teacher.\n"
    )


@pytest.fixture()
def technology_prd() -> str:
    """A PRD that mentions specific technologies."""
    return (
        "# Payments API\n\n"
        "| Entity | Description |\n"
        "|--------|-------------|\n"
        "| Invoice | A billing invoice |\n"
        "\n"
        "The backend is built with Python and FastAPI.\n"
        "Data is stored in PostgreSQL.\n"
        "Events are published via Kafka.\n"
    )


# ---------------------------------------------------------------------------
# 1. Entity extraction from Markdown tables
# ---------------------------------------------------------------------------


class TestEntityExtractionFromTables:
    """Tests for Strategy 1: Markdown table entity extraction."""

    def test_entities_from_entity_listing_table(self, minimal_table_prd: str) -> None:
        """parse_prd extracts entities defined in an entity-listing Markdown table."""
        result = parse_prd(minimal_table_prd)

        assert isinstance(result, ParsedPRD)
        names = [e["name"] for e in result.entities]
        assert "Product" in names
        assert "Warehouse" in names

    def test_entity_descriptions_from_table(self, minimal_table_prd: str) -> None:
        """parse_prd captures descriptions from the table's second column."""
        result = parse_prd(minimal_table_prd)

        product = next(e for e in result.entities if e["name"] == "Product")
        assert "product" in product["description"].lower()

    def test_field_level_table_under_heading(self) -> None:
        """parse_prd extracts fields from a Markdown table nested under an entity heading."""
        prd = (
            "# CRM System\n\n"
            "## Contact\n\n"
            "| Field | Type | Required |\n"
            "|-------|------|----------|\n"
            "| id    | UUID | Yes      |\n"
            "| email | string | Yes    |\n"
            "| phone | string | No     |\n"
        )
        result = parse_prd(prd)

        contact = next(e for e in result.entities if e["name"] == "Contact")
        field_names = [f["name"] for f in contact["fields"]]
        assert "id" in field_names
        assert "email" in field_names
        assert "phone" in field_names

        # Check type normalisation
        email_field = next(f for f in contact["fields"] if f["name"] == "email")
        assert email_field["type"] == "str"

        # Check required flag
        phone_field = next(f for f in contact["fields"] if f["name"] == "phone")
        assert phone_field["required"] is False


# ---------------------------------------------------------------------------
# 2. Entity extraction from heading + bullet list patterns
# ---------------------------------------------------------------------------


class TestEntityExtractionFromHeadings:
    """Tests for Strategy 2: heading + bullet-list fields."""

    def test_entities_from_heading_bullets(self, heading_bullets_prd: str) -> None:
        """parse_prd extracts entities defined as headings with bullet-list fields."""
        result = parse_prd(heading_bullets_prd)

        names = [e["name"] for e in result.entities]
        assert "Task" in names
        assert "Assignee" in names

    def test_fields_parsed_from_bullets(self, heading_bullets_prd: str) -> None:
        """parse_prd parses field name, type, and required flag from bullet lines."""
        result = parse_prd(heading_bullets_prd)

        task = next(e for e in result.entities if e["name"] == "Task")
        field_names = [f["name"] for f in task["fields"]]
        assert "id" in field_names
        assert "title" in field_names
        assert "status" in field_names

        # "status: string (optional)" should be marked not required
        status_field = next(f for f in task["fields"] if f["name"] == "status")
        assert status_field["required"] is False

    def test_description_captured_from_heading_body(self, heading_bullets_prd: str) -> None:
        """parse_prd captures the description line following the heading."""
        result = parse_prd(heading_bullets_prd)

        task = next(e for e in result.entities if e["name"] == "Task")
        assert "unit of work" in task["description"].lower()


# ---------------------------------------------------------------------------
# 3. Entity extraction from sentence / prose patterns
# ---------------------------------------------------------------------------


class TestEntityExtractionFromProse:
    """Tests for Strategy 3: prose/sentence entity extraction."""

    def test_entities_from_system_manages_pattern(self, prose_prd: str) -> None:
        """parse_prd extracts entities from 'The system manages Entity' sentences."""
        result = parse_prd(prose_prd)

        names = [e["name"] for e in result.entities]
        assert "Vehicle" in names
        assert "Driver" in names

    def test_fields_from_which_has_clause(self, prose_prd: str) -> None:
        """parse_prd parses comma-separated fields from 'which has field1, field2' clauses."""
        result = parse_prd(prose_prd)

        vehicle = next(e for e in result.entities if e["name"] == "Vehicle")
        field_names = [f["name"] for f in vehicle["fields"]]
        assert "vin" in field_names
        assert "make" in field_names
        assert "model" in field_names

    def test_entity_model_keyword_pattern(self) -> None:
        """parse_prd detects entities from '<Name> entity/model/object' prose patterns."""
        prd = (
            "# Logistics Platform\n\n"
            "The Shipment entity represents a package in transit.\n"
            "The Route model defines the path from origin to destination.\n"
        )
        result = parse_prd(prd)

        names = [e["name"] for e in result.entities]
        assert "Shipment" in names
        assert "Route" in names


# ---------------------------------------------------------------------------
# 4. Entity extraction from data model sections
# ---------------------------------------------------------------------------


class TestEntityExtractionFromDataModelSection:
    """Tests for Strategy 4: explicit Data Model section."""

    def test_entities_from_data_model_section(self) -> None:
        """parse_prd delegates extraction within a ## Data Model section."""
        prd = (
            "# Blog Platform\n\n"
            "## Overview\n"
            "A simple blog platform.\n\n"
            "## Data Model\n"
            "### Post\n"
            "Represents a blog post.\n"
            "- id: UUID\n"
            "- title: string\n"
            "- body: text\n"
            "\n"
            "### Comment\n"
            "A reader comment.\n"
            "- id: UUID\n"
            "- content: string\n"
        )
        result = parse_prd(prd)

        names = [e["name"] for e in result.entities]
        assert "Post" in names
        assert "Comment" in names


# ---------------------------------------------------------------------------
# 5. Relationship extraction
# ---------------------------------------------------------------------------


class TestRelationshipExtraction:
    """Tests for relationship detection from prose keywords."""

    def test_has_many_relationship(self, relationship_prd: str) -> None:
        """parse_prd detects 'has many' as a HAS_MANY relationship with 1:N cardinality."""
        result = parse_prd(relationship_prd)

        rel = next(
            (r for r in result.relationships
             if r["source"] == "Teacher" and r["target"] == "Student"),
            None,
        )
        assert rel is not None
        assert rel["type"] == "HAS_MANY"
        assert rel["cardinality"] == "1:N"

    def test_belongs_to_relationship(self, relationship_prd: str) -> None:
        """parse_prd detects 'belongs to' as a BELONGS_TO relationship with N:1 cardinality."""
        result = parse_prd(relationship_prd)

        rel = next(
            (r for r in result.relationships
             if r["source"] == "Student" and r["target"] == "Course"),
            None,
        )
        assert rel is not None
        assert rel["type"] == "BELONGS_TO"
        assert rel["cardinality"] == "N:1"

    def test_references_relationship(self, relationship_prd: str) -> None:
        """parse_prd detects 'references' as a REFERENCES relationship."""
        result = parse_prd(relationship_prd)

        rel = next(
            (r for r in result.relationships
             if r["source"] == "Course" and r["target"] == "Teacher"),
            None,
        )
        assert rel is not None
        assert rel["type"] == "REFERENCES"

    def test_triggers_relationship(self) -> None:
        """parse_prd detects 'triggers' as a TRIGGERS relationship."""
        prd = (
            "# Notification System\n\n"
            "| Entity | Description |\n"
            "|--------|-------------|\n"
            "| Order   | A purchase order |\n"
            "| Alert   | A user alert     |\n"
            "\n"
            "Order triggers Alert when payment completes.\n"
        )
        result = parse_prd(prd)

        rel = next(
            (r for r in result.relationships
             if r["source"] == "Order" and r["target"] == "Alert"),
            None,
        )
        assert rel is not None
        assert rel["type"] == "TRIGGERS"

    def test_depends_on_relationship(self) -> None:
        """parse_prd detects 'depends on' as a DEPENDS_ON relationship."""
        prd = (
            "# Build System\n\n"
            "| Entity | Description |\n"
            "|--------|-------------|\n"
            "| Module  | A code module      |\n"
            "| Library | An external library |\n"
            "\n"
            "Module depends on Library for compilation.\n"
        )
        result = parse_prd(prd)

        rel = next(
            (r for r in result.relationships
             if r["source"] == "Module" and r["target"] == "Library"),
            None,
        )
        assert rel is not None
        assert rel["type"] == "DEPENDS_ON"


# ---------------------------------------------------------------------------
# 6. Bounded context / service extraction
# ---------------------------------------------------------------------------


class TestBoundedContextExtraction:
    """Tests for bounded context (service) detection."""

    def test_service_heading_detection(self) -> None:
        """parse_prd detects bounded contexts from '## Service: Name' headings."""
        prd = (
            "# E-Commerce Platform\n\n"
            "| Entity | Description |\n"
            "|--------|-------------|\n"
            "| Product | A catalog product |\n"
            "| Cart    | A shopping cart    |\n"
            "\n"
            "## Service: Catalog Service\n"
            "Manages Product listings and search.\n\n"
            "## Service: Cart Service\n"
            "Handles Cart operations and checkout.\n"
        )
        result = parse_prd(prd)

        ctx_names = [c["name"] for c in result.bounded_contexts]
        assert "Catalog Service" in ctx_names
        assert "Cart Service" in ctx_names

    def test_prose_service_mention(self) -> None:
        """parse_prd detects services mentioned in prose ('the Foo Service handles...')."""
        prd = (
            "# Platform\n\n"
            "| Entity | Description |\n"
            "|--------|-------------|\n"
            "| User    | A registered user |\n"
            "\n"
            "The Auth Service verifies user credentials.\n"
        )
        result = parse_prd(prd)

        # The prose regex captures the full match including "The", so check
        # that at least one detected context contains "Auth Service".
        ctx_names = [c["name"] for c in result.bounded_contexts]
        assert any("Auth Service" in name for name in ctx_names)


# ---------------------------------------------------------------------------
# 7. Technology hint extraction
# ---------------------------------------------------------------------------


class TestTechnologyHintExtraction:
    """Tests for technology mention scanning."""

    def test_all_technology_categories_detected(self, technology_prd: str) -> None:
        """parse_prd detects language, framework, database, and message broker."""
        result = parse_prd(technology_prd)

        assert result.technology_hints["language"] == "Python"
        assert result.technology_hints["framework"] == "FastAPI"
        assert result.technology_hints["database"] == "PostgreSQL"
        assert result.technology_hints["message_broker"] == "Kafka"

    def test_technology_normalisation(self) -> None:
        """parse_prd normalises alternative technology names (e.g. Postgres -> PostgreSQL)."""
        prd = (
            "# Backend App\n\n"
            "| Entity | Description |\n"
            "|--------|-------------|\n"
            "| Account | A user account |\n"
            "\n"
            "We use Golang with Postgres for storage.\n"
        )
        result = parse_prd(prd)

        assert result.technology_hints["language"] == "Go"
        assert result.technology_hints["database"] == "PostgreSQL"


# ---------------------------------------------------------------------------
# 8. State machine detection
# ---------------------------------------------------------------------------


class TestStateMachineDetection:
    """Tests for state machine / lifecycle detection."""

    def test_status_field_triggers_state_machine(self) -> None:
        """parse_prd detects a state machine when an entity has a status field with enum values."""
        prd = (
            "# Order System\n\n"
            "### Order\n"
            "Represents a purchase.\n"
            "- id: UUID\n"
            "- status: string\n"
            "- total: float\n"
            "\n"
            "Order status: pending, confirmed, shipped, delivered.\n"
        )
        result = parse_prd(prd)

        assert len(result.state_machines) >= 1
        machine = next(m for m in result.state_machines if m["entity"] == "Order")
        assert "pending" in machine["states"]
        assert "confirmed" in machine["states"]
        assert "shipped" in machine["states"]
        assert "delivered" in machine["states"]
        # Transitions should be inferred linearly
        assert len(machine["transitions"]) >= 3

    def test_transition_sentence_detection(self) -> None:
        """parse_prd detects state transitions from 'Entity transitions from A to B' sentences."""
        prd = (
            "# Ticket System\n\n"
            "| Entity | Description |\n"
            "|--------|-------------|\n"
            "| Ticket | A support ticket |\n"
            "\n"
            "Ticket transitions from open to in_progress.\n"
            "Ticket transitions from in_progress to resolved.\n"
        )
        result = parse_prd(prd)

        assert len(result.state_machines) >= 1
        machine = next(m for m in result.state_machines if m["entity"] == "Ticket")
        assert "open" in machine["states"]
        assert "in_progress" in machine["states"]
        assert "resolved" in machine["states"]

    def test_arrow_notation_detection(self) -> None:
        """parse_prd detects state machines from arrow notation like 'Entity status: a -> b -> c'."""
        prd = (
            "# Pipeline App\n\n"
            "| Entity | Description |\n"
            "|--------|-------------|\n"
            "| Job | A processing job |\n"
            "\n"
            "Job status: queued -> running -> completed\n"
        )
        result = parse_prd(prd)

        assert len(result.state_machines) >= 1
        machine = next(m for m in result.state_machines if m["entity"] == "Job")
        assert "queued" in machine["states"]
        assert "running" in machine["states"]
        assert "completed" in machine["states"]


# ---------------------------------------------------------------------------
# 9. Interview question generation
# ---------------------------------------------------------------------------


class TestInterviewQuestionGeneration:
    """Tests for deterministic interview question generation."""

    def test_question_for_missing_auth_details(self) -> None:
        """parse_prd asks about authentication mechanism when auth is mentioned without specifics."""
        prd = (
            "# Secure App\n\n"
            "| Entity | Description |\n"
            "|--------|-------------|\n"
            "| User | A registered user |\n"
            "\n"
            "Users must login to access the dashboard.\n"
        )
        result = parse_prd(prd)

        auth_questions = [q for q in result.interview_questions if "authentication" in q.lower()]
        assert len(auth_questions) >= 1

    def test_question_for_missing_database(self) -> None:
        """parse_prd asks which database to use when none is mentioned."""
        prd = (
            "# Simple App\n\n"
            "| Entity | Description |\n"
            "|--------|-------------|\n"
            "| Widget | A widget item |\n"
        )
        result = parse_prd(prd)

        db_questions = [q for q in result.interview_questions if "database" in q.lower()]
        assert len(db_questions) >= 1

    def test_no_database_question_when_database_specified(self, technology_prd: str) -> None:
        """parse_prd does NOT ask about database when one is explicitly mentioned."""
        result = parse_prd(technology_prd)

        db_questions = [q for q in result.interview_questions if "database" in q.lower()]
        assert len(db_questions) == 0

    def test_question_for_fieldless_entities(self) -> None:
        """parse_prd generates a question when entities have no fields defined."""
        prd = (
            "# Bare App\n\n"
            "| Entity | Description |\n"
            "|--------|-------------|\n"
            "| Alpha | First entity  |\n"
            "| Beta  | Second entity |\n"
        )
        result = parse_prd(prd)

        field_questions = [q for q in result.interview_questions if "fields" in q.lower() or "attributes" in q.lower()]
        assert len(field_questions) >= 1

    def test_question_for_payment_without_provider(self) -> None:
        """parse_prd asks about payment provider when payment is mentioned without specifics."""
        prd = (
            "# Shop\n\n"
            "| Entity | Description |\n"
            "|--------|-------------|\n"
            "| Order | A purchase order |\n"
            "\n"
            "The checkout flow processes payment for each order.\n"
        )
        result = parse_prd(prd)

        pay_questions = [q for q in result.interview_questions if "payment" in q.lower()]
        assert len(pay_questions) >= 1


# ---------------------------------------------------------------------------
# 10. Project name extraction
# ---------------------------------------------------------------------------


class TestProjectNameExtraction:
    """Tests for project name extraction from various heading styles."""

    def test_project_name_from_top_heading(self) -> None:
        """parse_prd extracts the project name from the first top-level heading."""
        prd = (
            "# My Awesome Project\n\n"
            "| Entity | Description |\n"
            "|--------|-------------|\n"
            "| Foo | A foo |\n"
        )
        result = parse_prd(prd)
        assert result.project_name == "My Awesome Project"

    def test_project_name_from_explicit_project_heading(self) -> None:
        """parse_prd extracts from '# Project: Name' style headings."""
        prd = (
            "# Project: Super Platform\n\n"
            "| Entity | Description |\n"
            "|--------|-------------|\n"
            "| Item | An item |\n"
        )
        result = parse_prd(prd)
        assert result.project_name == "Super Platform"

    def test_project_name_from_prd_heading(self) -> None:
        """parse_prd extracts from '# PRD: Name' style headings."""
        prd = (
            "# PRD: Inventory Manager\n\n"
            "| Entity | Description |\n"
            "|--------|-------------|\n"
            "| Stock | Stock item |\n"
        )
        result = parse_prd(prd)
        assert result.project_name == "Inventory Manager"


# ---------------------------------------------------------------------------
# 11. Error case: too short text
# ---------------------------------------------------------------------------


class TestErrorTooShortText:
    """Tests for the minimum-length validation."""

    def test_empty_string_raises_parsing_error(self) -> None:
        """parse_prd raises ParsingError for an empty string."""
        with pytest.raises(ParsingError):
            parse_prd("")

    def test_very_short_text_raises_parsing_error(self) -> None:
        """parse_prd raises ParsingError when text is shorter than 30 characters."""
        with pytest.raises(ParsingError, match="too short"):
            parse_prd("Short text.")

    def test_whitespace_only_raises_parsing_error(self) -> None:
        """parse_prd raises ParsingError for whitespace-only input."""
        with pytest.raises(ParsingError):
            parse_prd("          \n\n\n      ")


# ---------------------------------------------------------------------------
# 12. Error case: no recognisable entities
# ---------------------------------------------------------------------------


class TestErrorNoEntities:
    """Tests for documents that contain no parseable entity structure."""

    def test_long_text_without_entities_returns_empty(self) -> None:
        """parse_prd returns empty entities when text has no entity patterns (no crash)."""
        prd = (
            "This is a document that discusses general project requirements "
            "without defining any specific data models, entities, or structured "
            "tables. It merely talks about features and timelines at length."
        )
        result = parse_prd(prd)
        assert result.entities == []


# ---------------------------------------------------------------------------
# 13. Multiple entities with fields in a single PRD
# ---------------------------------------------------------------------------


class TestMultipleEntitiesWithFields:
    """Tests for a PRD defining several entities each with their own fields."""

    def test_multiple_entities_each_with_fields(self) -> None:
        """parse_prd correctly distinguishes fields belonging to different entities.

        Note: a trailing section is added after the last entity so the heading
        body regex (which requires each line to end with a newline) can capture
        all bullet fields for the final entity.
        """
        prd = (
            "# Hospital System\n\n"
            "### Patient\n"
            "A person receiving care.\n"
            "- id: UUID (required)\n"
            "- name: string\n"
            "- date_of_birth: date\n"
            "\n"
            "### Doctor\n"
            "A medical professional.\n"
            "- id: UUID (required)\n"
            "- specialty: string\n"
            "- license_number: string\n"
            "\n"
            "### Appointment\n"
            "A scheduled visit.\n"
            "- id: UUID (required)\n"
            "- scheduled_at: datetime\n"
            "- duration: integer\n"
            "\n"
            "## Notes\n"
            "Additional details to follow.\n"
        )
        result = parse_prd(prd)

        names = [e["name"] for e in result.entities]
        assert "Patient" in names
        assert "Doctor" in names
        assert "Appointment" in names

        patient = next(e for e in result.entities if e["name"] == "Patient")
        doctor = next(e for e in result.entities if e["name"] == "Doctor")
        appointment = next(e for e in result.entities if e["name"] == "Appointment")

        patient_fields = [f["name"] for f in patient["fields"]]
        assert "date_of_birth" in patient_fields

        doctor_fields = [f["name"] for f in doctor["fields"]]
        assert "specialty" in doctor_fields

        appt_fields = [f["name"] for f in appointment["fields"]]
        assert "scheduled_at" in appt_fields

        # Verify type normalisation for specific fields
        dob = next(f for f in patient["fields"] if f["name"] == "date_of_birth")
        assert dob["type"] == "datetime"

        dur = next(f for f in appointment["fields"] if f["name"] == "duration")
        assert dur["type"] == "int"


# ---------------------------------------------------------------------------
# 14. Cardinality extraction
# ---------------------------------------------------------------------------


class TestCardinalityExtraction:
    """Tests for explicit cardinality labels near relationship keywords."""

    def test_one_to_many_cardinality(self) -> None:
        """parse_prd extracts 1:N cardinality from 'has many' keyword."""
        prd = (
            "# Library System\n\n"
            "| Entity | Description |\n"
            "|--------|-------------|\n"
            "| Author | A book author |\n"
            "| Book   | A published book |\n"
            "\n"
            "Author has many Book.\n"
        )
        result = parse_prd(prd)

        rel = next(
            (r for r in result.relationships
             if r["source"] == "Author" and r["target"] == "Book"),
            None,
        )
        assert rel is not None
        assert rel["cardinality"] == "1:N"

    def test_many_to_many_cardinality(self) -> None:
        """parse_prd extracts N:N cardinality from 'associated with' keyword."""
        prd = (
            "# Enrollment System\n\n"
            "| Entity  | Description |\n"
            "|---------|-------------|\n"
            "| Student | A student       |\n"
            "| Course  | A course        |\n"
            "\n"
            "Student associated with Course.\n"
        )
        result = parse_prd(prd)

        rel = next(
            (r for r in result.relationships
             if r["source"] == "Student" and r["target"] == "Course"),
            None,
        )
        assert rel is not None
        assert rel["cardinality"] == "N:N"

    def test_explicit_one_to_many_label_overrides_default(self) -> None:
        """parse_prd uses an explicit cardinality label when found near the relationship."""
        prd = (
            "# Project Tracker\n\n"
            "| Entity   | Description |\n"
            "|----------|-------------|\n"
            "| Project  | A project |\n"
            "| Task     | A task    |\n"
            "\n"
            "one-to-many: Project has many Task.\n"
        )
        result = parse_prd(prd)

        rel = next(
            (r for r in result.relationships
             if r["source"] == "Project" and r["target"] == "Task"),
            None,
        )
        assert rel is not None
        assert rel["cardinality"] == "1:N"


# ---------------------------------------------------------------------------
# 15. Edge case: entity merging from multiple strategies
# ---------------------------------------------------------------------------


class TestEntityMergingFromMultipleStrategies:
    """Tests for de-duplication and merging when the same entity is found by multiple strategies."""

    def test_entity_merged_across_table_and_heading(self) -> None:
        """parse_prd merges an entity found in both a table and a heading+bullets section.

        The table provides the description; the heading provides fields.
        The result should be a single entity with both description and fields.

        A trailing section is needed so the regex captures the last bullet field.
        """
        prd = (
            "# Merging Test\n\n"
            "| Entity | Description |\n"
            "|--------|-------------|\n"
            "| Customer | A paying customer |\n"
            "\n"
            "### Customer\n"
            "- id: UUID (required)\n"
            "- name: string\n"
            "- tier: string (optional)\n"
            "\n"
            "## Notes\n"
            "End of document.\n"
        )
        result = parse_prd(prd)

        # Should be exactly one Customer entity (merged, not duplicated)
        customer_entities = [e for e in result.entities if e["name"] == "Customer"]
        assert len(customer_entities) == 1

        customer = customer_entities[0]
        # Description should come from the table
        assert "paying customer" in customer["description"].lower()
        # Fields should come from the heading+bullets
        field_names = [f["name"] for f in customer["fields"]]
        assert "id" in field_names
        assert "name" in field_names
        assert "tier" in field_names

    def test_merged_entity_does_not_duplicate_fields(self) -> None:
        """parse_prd does not duplicate fields when merging entities from two strategies.

        A trailing section is needed so the regex captures the last bullet field.
        """
        prd = (
            "# Dedup App\n\n"
            "The system manages Account which has email, name.\n"
            "\n"
            "### Account\n"
            "Business account record.\n"
            "- email: string\n"
            "- phone: string\n"
            "\n"
            "## Notes\n"
            "End of document.\n"
        )
        result = parse_prd(prd)

        account_entities = [e for e in result.entities if e["name"] == "Account"]
        assert len(account_entities) == 1

        account = account_entities[0]
        field_names = [f["name"] for f in account["fields"]]
        # 'email' should appear only once even though both strategies found it
        assert field_names.count("email") == 1
        # 'phone' from heading strategy should be added
        assert "phone" in field_names
        # 'name' from prose strategy should be present
        assert "name" in field_names


# ---------------------------------------------------------------------------
# Additional edge-case tests (beyond the 15 required)
# ---------------------------------------------------------------------------


class TestReturnTypeAndStructure:
    """Tests verifying the shape of the ParsedPRD return value."""

    def test_parsed_prd_has_all_expected_fields(self, minimal_table_prd: str) -> None:
        """parse_prd returns a ParsedPRD with all documented attributes."""
        result = parse_prd(minimal_table_prd)

        assert isinstance(result.project_name, str)
        assert isinstance(result.entities, list)
        assert isinstance(result.relationships, list)
        assert isinstance(result.bounded_contexts, list)
        assert isinstance(result.technology_hints, dict)
        assert isinstance(result.state_machines, list)
        assert isinstance(result.interview_questions, list)

    def test_technology_hints_keys(self, minimal_table_prd: str) -> None:
        """parse_prd always returns technology_hints with language, framework, database, message_broker keys."""
        result = parse_prd(minimal_table_prd)

        assert "language" in result.technology_hints
        assert "framework" in result.technology_hints
        assert "database" in result.technology_hints
        assert "message_broker" in result.technology_hints


class TestArrowRelationshipNotation:
    """Tests for arrow-notation relationship extraction (Entity -> Entity)."""

    def test_arrow_notation_creates_references_relationship(self) -> None:
        """parse_prd creates a REFERENCES relationship from arrow notation between entities."""
        prd = (
            "# Graph App\n\n"
            "| Entity | Description |\n"
            "|--------|-------------|\n"
            "| Sender   | Message sender   |\n"
            "| Receiver | Message receiver |\n"
            "\n"
            "Sender --> Receiver\n"
        )
        result = parse_prd(prd)

        rel = next(
            (r for r in result.relationships
             if r["source"] == "Sender" and r["target"] == "Receiver"),
            None,
        )
        assert rel is not None
        assert rel["type"] == "REFERENCES"


# ---------------------------------------------------------------------------
# 16. JWT / Auth token detection
# ---------------------------------------------------------------------------


class TestJwtAuthDetection:
    """Tests for JWT and authentication token detection in technology hints."""

    def test_jwt_detection_in_prd(self) -> None:
        """PRD mentioning JWT should populate auth hint."""
        prd = (
            "# Secure API\n\n"
            "| Entity | Description |\n"
            "|--------|-------------|\n"
            "| User | A registered user |\n"
            "\n"
            "## Auth\n"
            "The service uses JWT tokens for authentication.\n"
        )
        result = parse_prd(prd)
        assert result.technology_hints.get("auth") is not None
        assert "jwt" in result.technology_hints["auth"].lower()

    def test_oauth_detection_in_prd(self) -> None:
        """PRD mentioning OAuth should populate auth hint."""
        prd = (
            "# OAuth App\n\n"
            "| Entity | Description |\n"
            "|--------|-------------|\n"
            "| Account | A user account |\n"
            "\n"
            "Authentication is handled via OAuth2 with refresh tokens.\n"
        )
        result = parse_prd(prd)
        assert result.technology_hints.get("auth") is not None

    def test_bearer_token_detection(self) -> None:
        """PRD mentioning bearer token should populate auth hint."""
        prd = (
            "# Token Service\n\n"
            "| Entity | Description |\n"
            "|--------|-------------|\n"
            "| Session | A user session |\n"
            "\n"
            "All API calls require a bearer token in the Authorization header.\n"
        )
        result = parse_prd(prd)
        assert result.technology_hints.get("auth") is not None

    def test_no_auth_hint_when_absent(self) -> None:
        """PRD without auth mentions should NOT have auth hint."""
        prd = (
            "# Simple CRUD App\n\n"
            "| Entity | Description |\n"
            "|--------|-------------|\n"
            "| Widget | A widget item |\n"
        )
        result = parse_prd(prd)
        assert result.technology_hints.get("auth") is None


# ---------------------------------------------------------------------------
# 17. Context clue technology detection
# ---------------------------------------------------------------------------


class TestContextClueDetection:
    """Tests for context-based technology detection."""

    def test_rest_api_detection(self) -> None:
        """PRD mentioning 'REST API' should populate api_style hint."""
        prd = (
            "# DataService\n\n"
            "| Entity | Description |\n"
            "|--------|-------------|\n"
            "| Record | A data record |\n"
            "\n"
            "## Overview\n"
            "A REST API service for managing data records.\n"
        )
        result = parse_prd(prd)
        assert result.technology_hints.get("api_style") == "rest"

    def test_graphql_detection(self) -> None:
        """PRD mentioning GraphQL should populate api_style hint."""
        prd = (
            "# QueryService\n\n"
            "| Entity | Description |\n"
            "|--------|-------------|\n"
            "| Item | A queryable item |\n"
            "\n"
            "The API is exposed via GraphQL for flexible querying.\n"
        )
        result = parse_prd(prd)
        assert result.technology_hints.get("api_style") == "graphql"

    def test_microservice_detection(self) -> None:
        """PRD mentioning microservice should populate architecture hint."""
        prd = (
            "# Platform\n\n"
            "| Entity | Description |\n"
            "|--------|-------------|\n"
            "| Service | A platform service |\n"
            "\n"
            "The system is built as a microservice architecture.\n"
        )
        result = parse_prd(prd)
        assert result.technology_hints.get("architecture") == "microservices"

    def test_websocket_detection(self) -> None:
        """PRD mentioning WebSocket should populate messaging hint."""
        prd = (
            "# ChatApp\n\n"
            "| Entity | Description |\n"
            "|--------|-------------|\n"
            "| Message | A chat message |\n"
            "\n"
            "Real-time communication is handled via WebSocket connections.\n"
        )
        result = parse_prd(prd)
        assert result.technology_hints.get("messaging") == "websocket"

    def test_docker_deployment_detection(self) -> None:
        """PRD mentioning Docker should populate deployment hint."""
        prd = (
            "# ContainerApp\n\n"
            "| Entity | Description |\n"
            "|--------|-------------|\n"
            "| Task | A background task |\n"
            "\n"
            "The application is deployed using Docker containers.\n"
        )
        result = parse_prd(prd)
        assert result.technology_hints.get("deployment") == "docker"

    def test_event_driven_detection(self) -> None:
        """PRD mentioning event-driven should populate architecture hint."""
        prd = (
            "# EventSystem\n\n"
            "| Entity | Description |\n"
            "|--------|-------------|\n"
            "| Event | A domain event |\n"
            "\n"
            "The platform follows an event-driven architecture for loose coupling.\n"
        )
        result = parse_prd(prd)
        assert result.technology_hints.get("architecture") == "event_driven"


# ---------------------------------------------------------------------------
# 18. Entity extraction quality -- no false positives
# ---------------------------------------------------------------------------


class TestEntityExtractionQuality:
    """Tests that section headers and non-entity text are NOT extracted as entities."""

    def test_no_false_positive_section_headers(self) -> None:
        """Markdown section headers should NOT be extracted as entities."""
        prd = (
            "# TaskTracker PRD\n\n"
            "## Overview\n"
            "The system manages tasks.\n\n"
            "## Requirements\n"
            "Must support CRUD.\n\n"
            "## Data Flow\n"
            "Tasks flow between services.\n\n"
            "### User Entity\n"
            "- id (UUID)\n"
            "- name (string)\n\n"
            "### Task Entity\n"
            "- id (UUID)\n"
            "- title (string)\n\n"
            "## Notes\n"
            "End.\n"
        )
        result = parse_prd(prd)
        entity_names = [e["name"] for e in result.entities]
        # Should NOT contain section headers
        for bad_name in ["Overview", "Requirements", "Data Flow"]:
            assert bad_name not in entity_names, f"False positive: {bad_name}"
        # Should contain real entities
        names_lower = [n.lower() for n in entity_names]
        assert "user" in names_lower or "User" in entity_names
        assert "task" in names_lower or "Task" in entity_names

    def test_no_notes_as_entity(self) -> None:
        """A 'Notes' section heading should NOT be extracted as an entity."""
        prd = (
            "# Project PRD\n\n"
            "### Order\n"
            "A purchase order.\n"
            "- id: UUID\n"
            "- total: float\n\n"
            "## Notes\n"
            "This section has additional notes.\n"
        )
        result = parse_prd(prd)
        entity_names = [e["name"] for e in result.entities]
        assert "Notes" not in entity_names
        assert "Order" in entity_names

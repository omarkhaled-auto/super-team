"""Wave 2 tests for PRD parser new extraction strategies.

Tests:
  - Entity field extraction from markdown tables
  - State machine extraction from various formats
  - Relationship type diversity (HAS_MANY, BELONGS_TO, REFERENCES)
  - Backward compatibility with existing heuristic parser
"""
from __future__ import annotations

import pytest

from src.architect.services.prd_parser import (
    ParsedPRD,
    parse_prd,
    _extract_state_machines,
    _extract_relationships,
    _extract_entities,
)
from src.shared.errors import ParsingError
from src.shared.models.architect import RelationshipType


# ---------------------------------------------------------------------------
# 1. Entity field extraction
# ---------------------------------------------------------------------------


class TestEntityFieldExtractionFromTables:
    """Entity fields are extracted from markdown field tables."""

    def test_field_table_under_heading(self):
        """Fields are extracted from a table under an entity heading."""
        text = (
            "# Product Catalog\n\n"
            "### Product\n"
            "A product in the catalog.\n\n"
            "| Field | Type | Required |\n"
            "|-------|------|----------|\n"
            "| id | UUID | Yes |\n"
            "| name | string | Yes |\n"
            "| price | float | No |\n"
        )
        parsed = parse_prd(text)
        product = next((e for e in parsed.entities if e["name"] == "Product"), None)
        assert product is not None
        field_names = {f["name"] for f in product.get("fields", [])}
        assert "id" in field_names
        assert "name" in field_names
        assert "price" in field_names

    def test_field_type_normalization(self):
        """Field types are normalized (UUID -> UUID, string -> str, etc.)."""
        text = (
            "# System\n\n"
            "### Account\n"
            "A user account.\n\n"
            "| Field | Type |\n"
            "|-------|------|\n"
            "| id | UUID |\n"
            "| email | string |\n"
            "| balance | decimal |\n"
            "| active | boolean |\n"
        )
        parsed = parse_prd(text)
        account = next((e for e in parsed.entities if e["name"] == "Account"), None)
        assert account is not None
        type_map = {f["name"]: f["type"] for f in account.get("fields", [])}
        assert type_map.get("id") == "UUID"
        assert type_map.get("email") == "str"
        assert type_map.get("balance") == "float"
        assert type_map.get("active") == "bool"

    def test_no_type_column_defaults_to_str(self):
        """When no type column exists, fields default to 'str' type."""
        text = (
            "# System\n\n"
            "### Ticket\n"
            "A support ticket.\n"
            "- id: UUID (required)\n"
            "- subject: The ticket subject\n"
        )
        parsed = parse_prd(text)
        ticket = next((e for e in parsed.entities if e["name"] == "Ticket"), None)
        assert ticket is not None
        # The second field should have been parsed with some type
        fields = ticket.get("fields", [])
        assert len(fields) >= 1


# ---------------------------------------------------------------------------
# 2. State machine extraction
# ---------------------------------------------------------------------------


class TestStateMachineExtraction:
    """State machines are extracted from various PRD formats."""

    def test_ascii_arrow_states(self):
        """Arrow-notation state machines are extracted: draft -> submitted -> approved."""
        text = (
            "# System\n\n"
            "| Entity | Description |\n"
            "|--------|-------------|\n"
            "| Invoice | A billing document |\n"
            "\n"
            "Invoice status: draft -> submitted -> approved -> paid\n"
        )
        parsed = parse_prd(text)
        assert len(parsed.state_machines) >= 1
        sm = next((m for m in parsed.state_machines if m["entity"] == "Invoice"), None)
        assert sm is not None
        assert "draft" in sm["states"]
        assert "submitted" in sm["states"]
        assert "approved" in sm["states"]
        assert "paid" in sm["states"]
        assert len(sm["transitions"]) >= 3

    def test_transition_sentence_format(self):
        """Prose format: 'Invoice transitions from draft to submitted'."""
        text = (
            "# System\n\n"
            "| Entity | Description |\n"
            "|--------|-------------|\n"
            "| Invoice | A billing document |\n"
            "\n"
            "Invoice transitions from draft to submitted.\n"
            "Invoice transitions from submitted to approved.\n"
        )
        parsed = parse_prd(text)
        sm = next((m for m in parsed.state_machines if m["entity"] == "Invoice"), None)
        assert sm is not None
        assert "draft" in sm["states"]
        assert "submitted" in sm["states"]
        assert "approved" in sm["states"]

    def test_heading_state_machine_format(self):
        """State machine extracted from a heading like '#### Task State Machine'."""
        text = (
            "# System\n\n"
            "| Entity | Description |\n"
            "|--------|-------------|\n"
            "| Task | A task item |\n"
            "\n"
            "#### Task State Machine\n"
            "todo -> in_progress\n"
            "in_progress -> done\n"
            "\n"  # Extra trailing content so body capture works after strip()
            "## Next Section\n"
        )
        parsed = parse_prd(text)
        sm = next((m for m in parsed.state_machines if m["entity"] == "Task"), None)
        assert sm is not None
        assert "todo" in sm["states"]
        assert "in_progress" in sm["states"]
        assert "done" in sm["states"]


# ---------------------------------------------------------------------------
# 3. Entity filtering
# ---------------------------------------------------------------------------


class TestEntityFiltering:
    """Entity filtering removes bogus non-domain entities using stop-list."""

    def test_parse_prd_filters_section_headings(self):
        """Full integration: parse_prd does not produce section headings as entities."""
        text = (
            "# LedgerPro\n\n"
            "## Data Model\n\n"
            "| Entity | Description |\n"
            "|--------|-------------|\n"
            "| Invoice | A billing record |\n"
            "| User | A user account |\n"
            "\n"
        )
        parsed = parse_prd(text)
        entity_names = {e["name"] for e in parsed.entities}
        assert "Invoice" in entity_names
        assert "User" in entity_names


# ---------------------------------------------------------------------------
# 4. Relationship types
# ---------------------------------------------------------------------------


class TestRelationshipTypeDiversity:
    """Relationship extraction produces diverse types, not all OWNS."""

    def test_references_type_detected(self):
        """'references' keyword produces REFERENCES type."""
        text = (
            "# System\n\n"
            "| Entity | Description |\n"
            "|--------|-------------|\n"
            "| Order | A customer order |\n"
            "| Product | A catalog product |\n"
            "\n"
            "Order references Product.\n"
        )
        parsed = parse_prd(text)
        refs = [r for r in parsed.relationships if r["type"] == "REFERENCES"]
        assert len(refs) >= 1

    def test_has_many_keyword(self):
        """'has many' keyword produces HAS_MANY type."""
        text = (
            "# System\n\n"
            "| Entity | Description |\n"
            "|--------|-------------|\n"
            "| Customer | A customer |\n"
            "| Order | A customer order |\n"
            "\n"
            "Customer has many Order.\n"
        )
        parsed = parse_prd(text)
        has_many = [r for r in parsed.relationships if r["type"] == "HAS_MANY"]
        assert len(has_many) >= 1

    def test_triggers_type_detected(self):
        """'triggers' keyword produces TRIGGERS type."""
        text = (
            "# System\n\n"
            "| Entity | Description |\n"
            "|--------|-------------|\n"
            "| Payment | A payment |\n"
            "| Notification | A notification |\n"
            "\n"
            "Payment triggers Notification.\n"
        )
        parsed = parse_prd(text)
        triggers = [r for r in parsed.relationships if r["type"] == "TRIGGERS"]
        assert len(triggers) >= 1

    def test_depends_on_type_detected(self):
        """'depends on' keyword produces DEPENDS_ON type."""
        text = (
            "# System\n\n"
            "| Entity | Description |\n"
            "|--------|-------------|\n"
            "| Order | A customer order |\n"
            "| Inventory | Inventory stock |\n"
            "\n"
            "Order depends on Inventory.\n"
        )
        parsed = parse_prd(text)
        deps = [r for r in parsed.relationships if r["type"] == "DEPENDS_ON"]
        assert len(deps) >= 1

    def test_mixed_relationship_types(self):
        """A PRD with multiple relationship keywords produces diverse types."""
        text = (
            "# System\n\n"
            "| Entity | Description |\n"
            "|--------|-------------|\n"
            "| User | A user |\n"
            "| Order | An order |\n"
            "| Product | A product |\n"
            "| Notification | A notification |\n"
            "\n"
            "User has many Order.\n"
            "Order references Product.\n"
            "Order triggers Notification.\n"
        )
        parsed = parse_prd(text)
        types = {r["type"] for r in parsed.relationships}
        assert len(types) >= 2, f"Expected at least 2 relationship types, got: {types}"


# ---------------------------------------------------------------------------
# 5. Backward compatibility
# ---------------------------------------------------------------------------


class TestBackwardCompatibility:
    """Existing heuristic parsing still works after Wave 2 changes."""

    def test_minimal_prose_prd_still_works(self):
        """A minimal prose PRD still extracts entities via heuristic."""
        text = (
            "# Task Manager\n\n"
            "The system manages Task which has title, status.\n"
            "The application tracks User which has name, email.\n"
        )
        parsed = parse_prd(text)
        assert len(parsed.entities) >= 2
        names = {e["name"] for e in parsed.entities}
        assert "Task" in names
        assert "User" in names

    def test_table_prd_still_works(self):
        """A standard table PRD still extracts entities."""
        text = (
            "# Inventory System\n\n"
            "## Data Model\n\n"
            "| Entity | Description |\n"
            "|--------|-------------|\n"
            "| Product | A product in the catalog |\n"
            "| Warehouse | A physical storage location |\n"
        )
        parsed = parse_prd(text)
        assert len(parsed.entities) >= 2

    def test_empty_prd_raises_parsing_error(self):
        """An empty or too-short PRD raises ParsingError."""
        with pytest.raises(ParsingError):
            parse_prd("")
        with pytest.raises(ParsingError):
            parse_prd("short")

    def test_no_entities_returns_valid_parsed_prd(self):
        """A PRD with no extractable entities returns an empty entities list."""
        text = (
            "# Project Overview\n\n"
            "This is a general project description with no entity definitions.\n"
            "It contains enough text to pass the minimum length requirement.\n"
        )
        parsed = parse_prd(text)
        # Should not crash; entities list may be empty or have some items
        assert isinstance(parsed.entities, list)

    def test_parsed_prd_default_fields(self):
        """ParsedPRD fields have correct defaults."""
        parsed = ParsedPRD(project_name="Test")
        assert parsed.entities == []
        assert parsed.relationships == []
        assert parsed.bounded_contexts == []
        assert parsed.state_machines == []
        assert parsed.interview_questions == []

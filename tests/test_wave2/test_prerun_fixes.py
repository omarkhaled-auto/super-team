"""Pre-run fix tests for Phase 2A and 2B.

Tests all fixes made in Phase 2A (Parser Finisher) and Phase 2B (Pipeline Wirer):

Phase 2A:
  - Relationship type mapping (_RELATIONSHIP_KEYWORDS, _PROSE_RELATIONSHIP_PATTERNS)
  - Strategy 9: _strategy9_extract_transition_sections
  - Domain modeler integration with parsed state machines

Phase 2B:
  - Builder config enrichment (entities, state_machines, is_frontend, contracts, etc.)
  - Compose generator multi-stack Dockerfiles
  - Graph RAG fallback context generation
  - Cross-service contract refs (HAS_MANY/BELONGS_TO detection)
"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from src.architect.services.prd_parser import (
    ParsedPRD,
    parse_prd,
    _extract_state_machines,
    _extract_relationships,
    _extract_entities,
)
from src.architect.services.service_boundary import (
    ServiceBoundary,
    identify_boundaries,
    _compute_contracts,
)
from src.architect.services.domain_modeler import build_domain_model
from src.integrator.compose_generator import ComposeGenerator
from src.build3_shared.models import ServiceInfo
from src.super_orchestrator.pipeline import (
    generate_builder_config,
    _build_fallback_contexts,
)
from src.super_orchestrator.state import PipelineState
from src.shared.models.architect import RelationshipType


# ============================================================================
# LedgerPro PRD fixture -- canonical PRD format with Transitions sections
# ============================================================================

LEDGERPRO_PRD = """\
# LedgerPro - Enterprise Accounting Platform

## Technology Stack
- **Language:** Python
- **Framework:** FastAPI
- **Primary Database:** PostgreSQL
- **Message Broker:** RabbitMQ

## Data Model

| Entity | Description |
|--------|-------------|
| Invoice | A billing document issued to clients |
| JournalEntry | An accounting journal entry |
| FiscalPeriod | A fiscal accounting period |
| Account | A general ledger account |
| Client | A customer or vendor entity |

## Relationships

Invoice belongs to Client.
Invoice references Account.
Client has many Invoice.
Account has many JournalEntry.
JournalEntry references FiscalPeriod.

## Services

### Invoice Service
Handles all invoice lifecycle operations.

### Ledger Service
Manages journal entries and general ledger.

### Period Service
Controls fiscal period lifecycle.

## State Machines

### Invoice Status State Machine

**States:** draft, submitted, approved, posted, paid, voided

**Transitions:**
- draft -> submitted: user submits invoice
- submitted -> approved: manager approves
- approved -> posted: accountant posts to ledger
- posted -> paid: payment received
- approved -> voided: invoice cancelled
- submitted -> voided: invoice rejected
- posted -> voided: reversal initiated

### Journal Entry Status State Machine

**States:** draft, pending_review, approved, posted, reversed

**Transitions:**
- draft -> pending_review: entry submitted for review
- pending_review -> approved: reviewer approves entry
- approved -> posted: entry posted to ledger
- posted -> reversed: reversal entry created
- pending_review -> draft: reviewer returns for correction

### Fiscal Period Status State Machine

**States:** open, closing, closed, locked

**Transitions:**
- open -> closing: period end date reached
- closing -> closed: all entries reconciled
- closed -> locked: audit completed
- closing -> open: reconciliation issues found
"""


# ============================================================================
# 1. State Machine Tests
# ============================================================================


class TestLedgerProStateMachines:
    """LedgerPro PRD format produces correct state machines."""

    @pytest.fixture(autouse=True)
    def parse_ledgerpro(self):
        """Parse the LedgerPro PRD once for all tests."""
        self.parsed = parse_prd(LEDGERPRO_PRD)
        self.sm_map = {sm["entity"]: sm for sm in self.parsed.state_machines}

    def test_invoice_has_six_states(self):
        """Invoice state machine has exactly 6 states."""
        sm = self.sm_map.get("Invoice")
        assert sm is not None, "Invoice state machine not found"
        assert len(sm["states"]) == 6, (
            f"Expected 6 states, got {len(sm['states'])}: {sm['states']}"
        )
        expected = {"draft", "submitted", "approved", "posted", "paid", "voided"}
        assert set(sm["states"]) == expected

    def test_invoice_has_seven_transitions(self):
        """Invoice state machine has exactly 7 transitions."""
        sm = self.sm_map.get("Invoice")
        assert sm is not None
        assert len(sm["transitions"]) == 7, (
            f"Expected 7 transitions, got {len(sm['transitions'])}: "
            f"{[(t['from_state'], t['to_state']) for t in sm['transitions']]}"
        )

    def test_journal_entry_has_five_states(self):
        """JournalEntry state machine has exactly 5 states."""
        sm = self.sm_map.get("JournalEntry")
        assert sm is not None, "JournalEntry state machine not found"
        assert len(sm["states"]) == 5, (
            f"Expected 5 states, got {len(sm['states'])}: {sm['states']}"
        )
        expected = {"draft", "pending_review", "approved", "posted", "reversed"}
        assert set(sm["states"]) == expected

    def test_journal_entry_has_five_transitions(self):
        """JournalEntry state machine has exactly 5 transitions."""
        sm = self.sm_map.get("JournalEntry")
        assert sm is not None
        assert len(sm["transitions"]) == 5, (
            f"Expected 5 transitions, got {len(sm['transitions'])}: "
            f"{[(t['from_state'], t['to_state']) for t in sm['transitions']]}"
        )

    def test_fiscal_period_has_four_states(self):
        """FiscalPeriod state machine has exactly 4 states."""
        sm = self.sm_map.get("FiscalPeriod")
        assert sm is not None, "FiscalPeriod state machine not found"
        assert len(sm["states"]) == 4, (
            f"Expected 4 states, got {len(sm['states'])}: {sm['states']}"
        )
        expected = {"open", "closing", "closed", "locked"}
        assert set(sm["states"]) == expected

    def test_fiscal_period_has_four_transitions(self):
        """FiscalPeriod state machine has exactly 4 transitions."""
        sm = self.sm_map.get("FiscalPeriod")
        assert sm is not None
        assert len(sm["transitions"]) == 4, (
            f"Expected 4 transitions, got {len(sm['transitions'])}: "
            f"{[(t['from_state'], t['to_state']) for t in sm['transitions']]}"
        )

    def test_invoice_initial_state_is_draft(self):
        """Invoice initial state is 'draft' (first state in list)."""
        sm = self.sm_map.get("Invoice")
        assert sm is not None
        # The initial_state is the first state in the ordered list
        assert sm["states"][0] == "draft"

    def test_journal_entry_initial_state_is_draft(self):
        """JournalEntry initial state is 'draft'."""
        sm = self.sm_map.get("JournalEntry")
        assert sm is not None
        assert sm["states"][0] == "draft"

    def test_fiscal_period_initial_state_is_open(self):
        """FiscalPeriod initial state is 'open'."""
        sm = self.sm_map.get("FiscalPeriod")
        assert sm is not None
        assert sm["states"][0] == "open"

    def test_invoice_terminal_states(self):
        """Invoice terminal states include 'paid' and 'voided'."""
        sm = self.sm_map.get("Invoice")
        assert sm is not None
        # Terminal states = states with no outgoing transitions
        states_with_outgoing = {t["from_state"] for t in sm["transitions"]}
        all_states = set(sm["states"])
        terminal = all_states - states_with_outgoing
        assert "paid" in terminal
        assert "voided" in terminal

    def test_journal_entry_terminal_state(self):
        """JournalEntry terminal state is 'reversed'."""
        sm = self.sm_map.get("JournalEntry")
        assert sm is not None
        states_with_outgoing = {t["from_state"] for t in sm["transitions"]}
        all_states = set(sm["states"])
        terminal = all_states - states_with_outgoing
        assert "reversed" in terminal

    def test_fiscal_period_terminal_state(self):
        """FiscalPeriod terminal state is 'locked'."""
        sm = self.sm_map.get("FiscalPeriod")
        assert sm is not None
        states_with_outgoing = {t["from_state"] for t in sm["transitions"]}
        all_states = set(sm["states"])
        terminal = all_states - states_with_outgoing
        assert "locked" in terminal


class TestStateMachineDomainModelerIntegration:
    """Domain modeler correctly consumes state machines from parser."""

    def test_domain_model_entities_get_state_machines(self):
        """Domain model entities receive state machines from parsed data."""
        parsed = parse_prd(LEDGERPRO_PRD)
        boundaries = identify_boundaries(parsed)
        model = build_domain_model(parsed, boundaries)

        invoice = next((e for e in model.entities if e.name == "Invoice"), None)
        assert invoice is not None
        assert invoice.state_machine is not None
        assert "draft" in invoice.state_machine.states
        assert invoice.state_machine.initial_state == "draft"
        assert len(invoice.state_machine.transitions) >= 5


# ============================================================================
# 2. Relationship Type Tests
# ============================================================================


class TestRelationshipTypeMapping:
    """Relationship keywords map to correct RelationshipType values."""

    def test_has_many_produces_has_many(self):
        """'has many' keyword maps to HAS_MANY, not OWNS."""
        text = (
            "# System\n\n"
            "| Entity | Description |\n"
            "|--------|-------------|\n"
            "| Customer | A customer |\n"
            "| Order | An order |\n"
            "\n"
            "Customer has many Order.\n"
        )
        parsed = parse_prd(text)
        has_many = [r for r in parsed.relationships if r["type"] == "HAS_MANY"]
        assert len(has_many) >= 1, (
            f"Expected HAS_MANY, got types: {[r['type'] for r in parsed.relationships]}"
        )
        owns = [r for r in parsed.relationships
                if r["source"] == "Customer" and r["target"] == "Order" and r["type"] == "OWNS"]
        assert len(owns) == 0, "has many should NOT map to OWNS"

    def test_belongs_to_produces_belongs_to(self):
        """'belongs to' keyword maps to BELONGS_TO, not OWNS."""
        text = (
            "# System\n\n"
            "| Entity | Description |\n"
            "|--------|-------------|\n"
            "| Comment | A comment |\n"
            "| Post | A blog post |\n"
            "\n"
            "Comment belongs to Post.\n"
        )
        parsed = parse_prd(text)
        belongs_to = [r for r in parsed.relationships if r["type"] == "BELONGS_TO"]
        assert len(belongs_to) >= 1, (
            f"Expected BELONGS_TO, got types: {[r['type'] for r in parsed.relationships]}"
        )
        owns = [r for r in parsed.relationships
                if r["source"] == "Comment" and r["target"] == "Post" and r["type"] == "OWNS"]
        assert len(owns) == 0, "belongs to should NOT map to OWNS"

    def test_references_produces_references(self):
        """'references' keyword maps to REFERENCES."""
        text = (
            "# System\n\n"
            "| Entity | Description |\n"
            "|--------|-------------|\n"
            "| Order | An order |\n"
            "| Product | A product |\n"
            "\n"
            "Order references Product.\n"
        )
        parsed = parse_prd(text)
        refs = [r for r in parsed.relationships if r["type"] == "REFERENCES"]
        assert len(refs) >= 1

    def test_contains_produces_owns(self):
        """'contains' keyword maps to OWNS (unchanged)."""
        text = (
            "# System\n\n"
            "| Entity | Description |\n"
            "|--------|-------------|\n"
            "| Folder | A folder |\n"
            "| Document | A document |\n"
            "\n"
            "Folder contains Document.\n"
        )
        parsed = parse_prd(text)
        owns = [r for r in parsed.relationships if r["type"] == "OWNS"]
        assert len(owns) >= 1

    def test_has_multiple_produces_has_many(self):
        """'has multiple' maps to HAS_MANY via prose pattern."""
        text = (
            "# System\n\n"
            "| Entity | Description |\n"
            "|--------|-------------|\n"
            "| Department | A department |\n"
            "| Employee | An employee |\n"
            "\n"
            "Department has multiple Employee.\n"
        )
        parsed = parse_prd(text)
        has_many = [r for r in parsed.relationships if r["type"] == "HAS_MANY"]
        assert len(has_many) >= 1, (
            f"Expected HAS_MANY, got types: {[r['type'] for r in parsed.relationships]}"
        )

    def test_is_part_of_produces_belongs_to(self):
        """'is part of' maps to BELONGS_TO via prose pattern."""
        text = (
            "# System\n\n"
            "| Entity | Description |\n"
            "|--------|-------------|\n"
            "| Task | A task |\n"
            "| Project | A project |\n"
            "\n"
            "Task is part of Project.\n"
        )
        parsed = parse_prd(text)
        belongs_to = [r for r in parsed.relationships if r["type"] == "BELONGS_TO"]
        assert len(belongs_to) >= 1, (
            f"Expected BELONGS_TO, got types: {[r['type'] for r in parsed.relationships]}"
        )

    def test_mixed_relationship_types_in_single_prd(self):
        """A single PRD with multiple relationship types produces diverse types."""
        parsed = parse_prd(LEDGERPRO_PRD)
        types = {r["type"] for r in parsed.relationships}
        # LedgerPro PRD has: belongs to, references, has many
        assert "BELONGS_TO" in types or "HAS_MANY" in types or "REFERENCES" in types, (
            f"Expected diverse types in LedgerPro PRD, got: {types}"
        )
        assert len(types) >= 2, (
            f"Expected at least 2 relationship types, got {len(types)}: {types}"
        )


# ============================================================================
# 3. Builder Config Tests
# ============================================================================


class TestBuilderConfigEnrichment:
    """Builder config includes entities, state_machines, contracts, etc."""

    def _make_config_with_artifacts(
        self, tmpdir: str, domain_model: dict | None = None, service_map: dict | None = None
    ) -> tuple:
        """Create service_info, config, state with optional domain model and service map."""
        output_dir = Path(tmpdir)

        service_info = ServiceInfo(
            service_id="invoice-service",
            domain="billing",
            stack={"language": "python", "framework": "fastapi"},
            port=8001,
        )

        config = MagicMock()
        config.output_dir = tmpdir
        config.builder.depth = "thorough"
        config.persistence = MagicMock()
        config.persistence.enabled = False

        state = PipelineState()
        state.prd_path = "/dummy/prd.md"
        state.phase_artifacts = {}

        if domain_model:
            dm_path = output_dir / "domain_model.json"
            dm_path.write_text(json.dumps(domain_model))
            state.domain_model_path = str(dm_path)

        if service_map:
            sm_path = output_dir / "service_map.json"
            sm_path.write_text(json.dumps(service_map))
            state.service_map_path = str(sm_path)

        return service_info, config, state

    def test_config_includes_entities_list(self):
        """Config includes entities list (non-empty when domain model has entities for service)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            domain_model = {
                "entities": [
                    {
                        "name": "Invoice",
                        "description": "A billing document",
                        "owning_service": "invoice-service",
                        "fields": [{"name": "id", "type": "UUID"}],
                    },
                ],
                "relationships": [],
            }
            service_info, config, state = self._make_config_with_artifacts(
                tmpdir, domain_model=domain_model
            )
            config_dict, _ = generate_builder_config(service_info, config, state)

            assert "entities" in config_dict
            assert len(config_dict["entities"]) >= 1
            assert config_dict["entities"][0]["name"] == "Invoice"

    def test_config_includes_state_machines(self):
        """Config includes state_machines when applicable."""
        with tempfile.TemporaryDirectory() as tmpdir:
            domain_model = {
                "entities": [
                    {
                        "name": "Invoice",
                        "description": "A billing document",
                        "owning_service": "invoice-service",
                        "fields": [],
                        "state_machine": {
                            "states": ["draft", "submitted"],
                            "initial_state": "draft",
                            "transitions": [
                                {"from_state": "draft", "to_state": "submitted", "trigger": "submit"},
                            ],
                        },
                    },
                ],
                "relationships": [],
            }
            service_info, config, state = self._make_config_with_artifacts(
                tmpdir, domain_model=domain_model
            )
            config_dict, _ = generate_builder_config(service_info, config, state)

            assert "state_machines" in config_dict
            assert len(config_dict["state_machines"]) >= 1

    def test_config_includes_is_frontend_flag(self):
        """Config includes is_frontend flag."""
        with tempfile.TemporaryDirectory() as tmpdir:
            service_map = {
                "services": [
                    {
                        "service_id": "invoice-service",
                        "name": "invoice-service",
                        "is_frontend": False,
                        "provides_contracts": ["invoice-service-api"],
                        "consumes_contracts": [],
                    },
                ],
            }
            service_info, config, state = self._make_config_with_artifacts(
                tmpdir, service_map=service_map
            )
            config_dict, _ = generate_builder_config(service_info, config, state)

            assert "is_frontend" in config_dict
            assert config_dict["is_frontend"] is False

    def test_config_includes_provides_contracts(self):
        """Config includes provides_contracts list."""
        with tempfile.TemporaryDirectory() as tmpdir:
            service_map = {
                "services": [
                    {
                        "service_id": "invoice-service",
                        "name": "invoice-service",
                        "provides_contracts": ["invoice-service-api"],
                        "consumes_contracts": ["user-service-api"],
                    },
                ],
            }
            service_info, config, state = self._make_config_with_artifacts(
                tmpdir, service_map=service_map
            )
            config_dict, _ = generate_builder_config(service_info, config, state)

            assert "provides_contracts" in config_dict
            assert "invoice-service-api" in config_dict["provides_contracts"]

    def test_config_includes_consumes_contracts(self):
        """Config includes consumes_contracts list."""
        with tempfile.TemporaryDirectory() as tmpdir:
            service_map = {
                "services": [
                    {
                        "service_id": "invoice-service",
                        "name": "invoice-service",
                        "provides_contracts": [],
                        "consumes_contracts": ["user-service-api"],
                    },
                ],
            }
            service_info, config, state = self._make_config_with_artifacts(
                tmpdir, service_map=service_map
            )
            config_dict, _ = generate_builder_config(service_info, config, state)

            assert "consumes_contracts" in config_dict
            assert "user-service-api" in config_dict["consumes_contracts"]

    def test_config_includes_contracts_dict(self):
        """Config includes contracts dict."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create a contract file in the registry
            registry_dir = Path(tmpdir) / "contracts"
            registry_dir.mkdir()
            contract_file = registry_dir / "invoice-service-openapi.json"
            contract_file.write_text(json.dumps({
                "openapi": "3.1.0",
                "info": {"title": "Invoice API"},
            }))

            service_info, config, state = self._make_config_with_artifacts(tmpdir)
            state.contract_registry_path = str(registry_dir)

            # Set up service map so consumes_contracts is populated
            sm_path = Path(tmpdir) / "service_map.json"
            sm_path.write_text(json.dumps({
                "services": [
                    {
                        "service_id": "invoice-service",
                        "name": "invoice-service",
                        "provides_contracts": ["invoice-service-api"],
                        "consumes_contracts": [],
                    },
                ],
            }))
            state.service_map_path = str(sm_path)

            config_dict, _ = generate_builder_config(service_info, config, state)

            assert "contracts" in config_dict
            assert isinstance(config_dict["contracts"], dict)

    def test_frontend_config_has_is_frontend_true(self):
        """Frontend service config has is_frontend=True."""
        with tempfile.TemporaryDirectory() as tmpdir:
            service_info = ServiceInfo(
                service_id="web-ui",
                domain="frontend",
                stack={"language": "typescript", "framework": "react"},
                port=3000,
            )
            service_map = {
                "services": [
                    {
                        "service_id": "web-ui",
                        "name": "web-ui",
                        "is_frontend": True,
                        "provides_contracts": [],
                        "consumes_contracts": ["invoice-service-api"],
                    },
                ],
            }

            config = MagicMock()
            config.output_dir = tmpdir
            config.builder.depth = "thorough"
            config.persistence = MagicMock()
            config.persistence.enabled = False

            state = PipelineState()
            state.prd_path = "/dummy/prd.md"
            state.phase_artifacts = {}

            sm_path = Path(tmpdir) / "service_map.json"
            sm_path.write_text(json.dumps(service_map))
            state.service_map_path = str(sm_path)

            config_dict, _ = generate_builder_config(service_info, config, state)

            assert config_dict["is_frontend"] is True


# ============================================================================
# 4. Compose Generator Tests
# ============================================================================


class TestComposeGeneratorMultiStack:
    """Compose generator handles Python, TypeScript, and Frontend stacks."""

    def test_python_fastapi_service_dockerfile(self):
        """Python/FastAPI service produces Python Dockerfile."""
        svc = ServiceInfo(
            service_id="billing-service",
            domain="billing",
            stack={"language": "python", "framework": "fastapi"},
            port=8001,
        )
        content = ComposeGenerator._dockerfile_content_for_stack(8001, svc)
        assert "python:3.12" in content
        assert "uvicorn" in content
        assert "requirements.txt" in content

    def test_typescript_nestjs_service_dockerfile(self):
        """TypeScript/NestJS service produces TypeScript Dockerfile."""
        svc = ServiceInfo(
            service_id="user-service",
            domain="identity",
            stack={"language": "typescript", "framework": "nestjs"},
            port=8002,
        )
        content = ComposeGenerator._dockerfile_content_for_stack(8002, svc)
        assert "node:20" in content
        assert "npm" in content
        assert "dist/main.js" in content

    def test_angular_frontend_dockerfile(self):
        """Angular frontend produces multi-stage nginx Dockerfile."""
        svc = ServiceInfo(
            service_id="web-frontend",
            domain="frontend",
            stack={"language": "typescript", "framework": "angular"},
            port=80,
        )
        content = ComposeGenerator._dockerfile_content_for_stack(80, svc)
        assert "nginx" in content
        assert "build" in content.lower()
        # Multi-stage: has FROM ... AS build and FROM nginx
        assert content.count("FROM") >= 2

    def test_react_frontend_dockerfile(self):
        """React frontend produces multi-stage nginx Dockerfile."""
        svc = ServiceInfo(
            service_id="web-app",
            domain="frontend",
            stack={"language": "typescript", "framework": "react"},
            port=3000,
        )
        content = ComposeGenerator._dockerfile_content_for_stack(3000, svc)
        assert "nginx" in content
        assert content.count("FROM") >= 2

    def test_frontend_service_no_postgres_redis_depends(self):
        """Frontend service does NOT depend on postgres/redis."""
        generator = ComposeGenerator()
        svc = ServiceInfo(
            service_id="web-frontend",
            domain="frontend",
            stack={"language": "typescript", "framework": "angular"},
            port=80,
        )
        service_def = generator._app_service(svc)
        # Frontend should only be on the frontend network
        assert "frontend" in service_def["networks"]
        assert "backend" not in service_def["networks"]
        # Frontend should NOT depend on postgres/redis
        assert "depends_on" not in service_def

    def test_backend_service_depends_on_postgres_redis(self):
        """Backend service depends on postgres and redis."""
        generator = ComposeGenerator()
        svc = ServiceInfo(
            service_id="api-service",
            domain="core",
            stack={"language": "python", "framework": "fastapi"},
            port=8080,
        )
        service_def = generator._app_service(svc)
        # Backend should be on both networks
        assert "frontend" in service_def["networks"]
        assert "backend" in service_def["networks"]
        # Backend should depend on postgres and redis
        assert "depends_on" in service_def
        assert "postgres" in service_def["depends_on"]
        assert "redis" in service_def["depends_on"]


class TestComposeGeneratorStackDetection:
    """_detect_stack correctly categorizes service stacks."""

    def test_python_detected(self):
        """Python services detected as 'python'."""
        svc = ServiceInfo(
            service_id="svc", domain="d",
            stack={"language": "python", "framework": "fastapi"},
        )
        assert ComposeGenerator._detect_stack(svc) == "python"

    def test_typescript_detected(self):
        """TypeScript services detected as 'typescript'."""
        svc = ServiceInfo(
            service_id="svc", domain="d",
            stack={"language": "typescript", "framework": "nestjs"},
        )
        assert ComposeGenerator._detect_stack(svc) == "typescript"

    def test_angular_detected_as_frontend(self):
        """Angular services detected as 'frontend'."""
        svc = ServiceInfo(
            service_id="svc", domain="d",
            stack={"language": "typescript", "framework": "angular"},
        )
        assert ComposeGenerator._detect_stack(svc) == "frontend"

    def test_react_detected_as_frontend(self):
        """React services detected as 'frontend'."""
        svc = ServiceInfo(
            service_id="svc", domain="d",
            stack={"language": "typescript", "framework": "react"},
        )
        assert ComposeGenerator._detect_stack(svc) == "frontend"

    def test_none_defaults_to_python(self):
        """None service_info defaults to 'python'."""
        assert ComposeGenerator._detect_stack(None) == "python"


# ============================================================================
# 5. Graph RAG Fallback Test
# ============================================================================


class TestGraphRAGFallback:
    """When graph_rag_contexts is empty, fallback context is generated."""

    def test_fallback_context_generated_when_empty(self):
        """Fallback context is non-empty for services with domain model data."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create a domain model file
            dm_path = Path(tmpdir) / "domain_model.json"
            dm_path.write_text(json.dumps({
                "entities": [
                    {
                        "name": "Invoice",
                        "description": "A billing document",
                        "owning_service": "invoice-service",
                        "fields": [
                            {"name": "id", "type": "UUID"},
                            {"name": "amount", "type": "float"},
                        ],
                    },
                ],
                "relationships": [],
            }))

            state = PipelineState()
            state.domain_model_path = str(dm_path)

            service_map = {
                "services": [
                    {
                        "service_id": "invoice-service",
                        "name": "invoice-service",
                        "domain": "billing",
                        "stack": {"language": "python", "framework": "fastapi"},
                        "provides_contracts": ["invoice-service-api"],
                        "consumes_contracts": [],
                    },
                ],
            }

            fallback = _build_fallback_contexts(state, service_map)

            # Fallback context should be non-empty for the service
            assert "invoice-service" in fallback
            assert len(fallback["invoice-service"]) > 0
            # Should mention the entity
            assert "Invoice" in fallback["invoice-service"]

    def test_fallback_context_includes_entities(self):
        """Fallback context includes entity information."""
        with tempfile.TemporaryDirectory() as tmpdir:
            dm_path = Path(tmpdir) / "domain_model.json"
            dm_path.write_text(json.dumps({
                "entities": [
                    {
                        "name": "User",
                        "description": "A user",
                        "owning_service": "user-service",
                        "fields": [{"name": "email", "type": "str"}],
                    },
                    {
                        "name": "Profile",
                        "description": "A profile",
                        "owning_service": "user-service",
                        "fields": [],
                    },
                ],
                "relationships": [],
            }))

            state = PipelineState()
            state.domain_model_path = str(dm_path)

            service_map = {
                "services": [
                    {
                        "service_id": "user-service",
                        "name": "user-service",
                        "domain": "identity",
                    },
                ],
            }

            fallback = _build_fallback_contexts(state, service_map)
            ctx = fallback.get("user-service", "")
            assert "User" in ctx
            assert "Profile" in ctx


# ============================================================================
# 6. Cross-Service Contract Refs
# ============================================================================


class TestCrossServiceContractRefs:
    """Cross-boundary contract detection includes HAS_MANY and BELONGS_TO."""

    def test_has_many_triggers_cross_boundary_consumption(self):
        """HAS_MANY relationship triggers cross-boundary contract consumption."""
        boundary_a = ServiceBoundary(
            name="Order Service",
            domain="orders",
            description="Orders",
            entities=["Order"],
        )
        boundary_b = ServiceBoundary(
            name="Item Service",
            domain="items",
            description="Line items",
            entities=["LineItem"],
        )

        relationships = [
            {
                "source": "Order",
                "target": "LineItem",
                "type": "HAS_MANY",
                "cardinality": "1:N",
            },
        ]

        _compute_contracts([boundary_a, boundary_b], relationships)

        # HAS_MANY: LineItem holds FK to Order, so Item Service consumes
        # Order Service's API (the "many" side depends on the "one" side).
        assert "order-service-api" in boundary_b.consumes_contracts
        # Order Service does NOT consume Item Service's API
        assert "item-service-api" not in boundary_a.consumes_contracts

    def test_belongs_to_triggers_cross_boundary_consumption(self):
        """BELONGS_TO relationship triggers cross-boundary contract consumption."""
        boundary_a = ServiceBoundary(
            name="Comment Service",
            domain="comments",
            description="Comments",
            entities=["Comment"],
        )
        boundary_b = ServiceBoundary(
            name="Post Service",
            domain="posts",
            description="Posts",
            entities=["Post"],
        )

        relationships = [
            {
                "source": "Comment",
                "target": "Post",
                "type": "BELONGS_TO",
                "cardinality": "N:1",
            },
        ]

        _compute_contracts([boundary_a, boundary_b], relationships)

        # Comment Service consumes Post Service's API (forward direction)
        assert "post-service-api" in boundary_a.consumes_contracts
        # BELONGS_TO is one-way: Post Service does NOT consume Comment Service's API
        assert "comment-service-api" not in boundary_b.consumes_contracts

    def test_owns_does_not_trigger_cross_boundary_consumption(self):
        """OWNS relationship does NOT trigger cross-boundary consumption."""
        boundary_a = ServiceBoundary(
            name="Order Service",
            domain="orders",
            description="Orders",
            entities=["Order"],
        )
        boundary_b = ServiceBoundary(
            name="Detail Service",
            domain="details",
            description="Details",
            entities=["OrderDetail"],
        )

        relationships = [
            {
                "source": "Order",
                "target": "OrderDetail",
                "type": "OWNS",
                "cardinality": "1:N",
            },
        ]

        _compute_contracts([boundary_a, boundary_b], relationships)

        # OWNS is intra-boundary, should not create consumption
        # (only provides_contracts should be set, no consumes)
        assert len(boundary_a.consumes_contracts) == 0
        assert len(boundary_b.consumes_contracts) == 0

    def test_references_triggers_cross_boundary_consumption(self):
        """REFERENCES relationship triggers cross-boundary contract consumption."""
        boundary_a = ServiceBoundary(
            name="Invoice Service",
            domain="billing",
            description="Billing",
            entities=["Invoice"],
        )
        boundary_b = ServiceBoundary(
            name="Account Service",
            domain="accounting",
            description="Accounting",
            entities=["Account"],
        )

        relationships = [
            {
                "source": "Invoice",
                "target": "Account",
                "type": "REFERENCES",
                "cardinality": "N:1",
            },
        ]

        _compute_contracts([boundary_a, boundary_b], relationships)

        # Invoice Service should consume Account Service's API
        assert "account-service-api" in boundary_a.consumes_contracts

"""Tests against the REAL LedgerPro PRD (509 lines, 28,762 chars).
NOT a simplified fixture. This is the actual PRD the pipeline must handle.
"""
import pytest
from pathlib import Path

from src.architect.services.prd_parser import parse_prd
from src.architect.services.service_boundary import identify_boundaries, build_service_map
from src.architect.services.domain_modeler import build_domain_model

REAL_PRD = Path(__file__).parent.parent / "fixtures" / "ledgerpro_full.md"


@pytest.fixture
def prd_text():
    text = REAL_PRD.read_text(encoding="utf-8")
    assert len(text) > 25000, f"PRD too short ({len(text)} chars) — wrong file?"
    assert "LedgerPro" in text, "Not the LedgerPro PRD"
    assert "### Docker" in text, "Missing Docker section — simplified fixture?"
    assert "AsyncAPI 3.0" in text, "Missing AsyncAPI section — simplified fixture?"
    return text


@pytest.fixture
def parsed(prd_text):
    return parse_prd(prd_text)


@pytest.fixture
def boundaries(parsed):
    return identify_boundaries(parsed)


@pytest.fixture
def service_map(parsed, boundaries):
    return build_service_map(parsed, boundaries)


@pytest.fixture
def domain_model(parsed, boundaries):
    return build_domain_model(parsed, boundaries)


# ===================================================================
# Entity Tests
# ===================================================================

class TestEntityExtraction:
    EXPECTED_ENTITIES = {
        "User", "Tenant", "Role", "Account", "JournalEntry", "JournalLine",
        "FiscalPeriod", "Invoice", "InvoiceLine", "Payment", "Notification",
        "AuditEntry",
    }
    BOGUS_ENTITIES = {
        "Docker", "Observability", "SeedData", "DataIntegrity", "Pages",
        "Reliability", "Domain", "With", "All", "Concurrent", "Vendor",
        "Client", "EntityRelationships", "EventChains", "EventsPublished",
        "SuccessCriteria", "UserRolesAndPermissions", "Technology",
        "Architecture", "Frontend", "Security", "Performance",
    }

    def test_entity_count(self, parsed):
        names = {e["name"] for e in parsed.entities}
        assert len(names) == 12, f"Expected 12 entities, got {len(names)}: {sorted(names)}"

    def test_entity_names_exact(self, parsed):
        names = {e["name"] for e in parsed.entities}
        assert names == self.EXPECTED_ENTITIES, (
            f"Missing: {self.EXPECTED_ENTITIES - names}, Extra: {names - self.EXPECTED_ENTITIES}"
        )

    def test_zero_bogus_entities(self, parsed):
        names = {e["name"] for e in parsed.entities}
        found_bogus = names & self.BOGUS_ENTITIES
        assert found_bogus == set(), f"Bogus entities found: {found_bogus}"

    def test_user_fields(self, parsed):
        user = next(e for e in parsed.entities if e["name"] == "User")
        field_names = {f["name"] for f in user["fields"]}
        expected = {"id", "email", "password_hash", "first_name", "last_name",
                    "role", "tenant_id", "is_active", "created_at", "updated_at"}
        assert expected <= field_names, f"Missing User fields: {expected - field_names}"

    def test_invoice_fields(self, parsed):
        inv = next(e for e in parsed.entities if e["name"] == "Invoice")
        field_names = {f["name"] for f in inv["fields"]}
        expected = {"id", "invoice_number", "type", "customer_name", "status",
                    "issue_date", "due_date", "total", "tenant_id"}
        assert expected <= field_names, f"Missing Invoice fields: {expected - field_names}"

    def test_every_entity_has_fields(self, parsed):
        for entity in parsed.entities:
            assert len(entity["fields"]) > 0, (
                f"Entity {entity['name']} has no fields"
            )

    def test_entity_ownership(self, parsed):
        ownership = {e["name"]: e.get("owning_context") for e in parsed.entities}
        assert ownership["User"] == "auth-service"
        assert ownership["Tenant"] == "auth-service"
        assert ownership["Role"] == "auth-service"
        assert ownership["Account"] == "accounts-service"
        assert ownership["JournalEntry"] == "accounts-service"
        assert ownership["JournalLine"] == "accounts-service"
        assert ownership["FiscalPeriod"] == "accounts-service"
        assert ownership["Invoice"] == "invoicing-service"
        assert ownership["InvoiceLine"] == "invoicing-service"
        assert ownership["Payment"] == "invoicing-service"
        assert ownership["Notification"] == "notification-service"
        assert ownership["AuditEntry"] == "accounts-service"


# ===================================================================
# Service Tests
# ===================================================================

class TestServiceBoundary:
    EXPECTED_SERVICES = {
        "auth-service", "accounts-service", "invoicing-service",
        "reporting-service", "notification-service", "frontend",
    }

    def test_service_count(self, service_map):
        names = {s.name for s in service_map.services}
        assert len(names) == 6, f"Expected 6 services, got {len(names)}: {sorted(names)}"

    def test_service_names_exact(self, service_map):
        names = {s.name for s in service_map.services}
        assert names == self.EXPECTED_SERVICES, (
            f"Missing: {self.EXPECTED_SERVICES - names}, Extra: {names - self.EXPECTED_SERVICES}"
        )

    def test_auth_service_stack(self, service_map):
        auth = next(s for s in service_map.services if s.name == "auth-service")
        assert auth.stack.language == "Python"
        assert auth.stack.framework == "FastAPI"

    def test_accounts_service_stack(self, service_map):
        acct = next(s for s in service_map.services if s.name == "accounts-service")
        assert acct.stack.language == "TypeScript"
        assert acct.stack.framework == "NestJS"

    def test_invoicing_service_stack(self, service_map):
        inv = next(s for s in service_map.services if s.name == "invoicing-service")
        assert inv.stack.language == "Python"
        assert inv.stack.framework == "FastAPI"

    def test_reporting_service_stack(self, service_map):
        rpt = next(s for s in service_map.services if s.name == "reporting-service")
        assert rpt.stack.language == "Python"
        assert rpt.stack.framework == "FastAPI"

    def test_notification_service_stack(self, service_map):
        notif = next(s for s in service_map.services if s.name == "notification-service")
        assert notif.stack.language == "TypeScript"
        assert notif.stack.framework == "NestJS"

    def test_frontend_stack(self, service_map):
        fe = next(s for s in service_map.services if s.name == "frontend")
        assert fe.stack.framework == "Angular"

    def test_auth_entities(self, service_map):
        auth = next(s for s in service_map.services if s.name == "auth-service")
        assert set(auth.owns_entities) == {"User", "Tenant", "Role"}

    def test_accounts_entities(self, service_map):
        acct = next(s for s in service_map.services if s.name == "accounts-service")
        assert set(acct.owns_entities) == {
            "Account", "JournalEntry", "JournalLine", "FiscalPeriod", "AuditEntry"
        }

    def test_invoicing_entities(self, service_map):
        inv = next(s for s in service_map.services if s.name == "invoicing-service")
        assert set(inv.owns_entities) == {"Invoice", "InvoiceLine", "Payment"}

    def test_notification_entities(self, service_map):
        notif = next(s for s in service_map.services if s.name == "notification-service")
        assert set(notif.owns_entities) == {"Notification"}

    def test_reporting_no_entities(self, service_map):
        rpt = next(s for s in service_map.services if s.name == "reporting-service")
        assert rpt.owns_entities == []

    def test_frontend_no_entities(self, service_map):
        fe = next(s for s in service_map.services if s.name == "frontend")
        assert fe.owns_entities == []


# ===================================================================
# Event Tests
# ===================================================================

class TestEventExtraction:
    EXPECTED_EVENTS = {
        "user.created", "user.role_changed", "invoice.submitted",
        "invoice.approved", "invoice.posted", "invoice.paid",
        "invoice.voided", "journal.posted", "journal.reversed",
        "period.closing", "period.closed", "period.locked",
        "payment.received",
    }

    def test_event_count(self, parsed):
        names = {e["name"] for e in parsed.events}
        assert len(names) == 13, f"Expected 13 events, got {len(names)}: {sorted(names)}"

    def test_event_names_exact(self, parsed):
        names = {e["name"] for e in parsed.events}
        assert names == self.EXPECTED_EVENTS, (
            f"Missing: {self.EXPECTED_EVENTS - names}, Extra: {names - self.EXPECTED_EVENTS}"
        )

    def test_every_event_has_publisher(self, parsed):
        for event in parsed.events:
            assert event.get("publisher_service"), (
                f"Event {event['name']} has no publisher"
            )

    def test_every_event_has_consumers(self, parsed):
        for event in parsed.events:
            assert event.get("subscriber_services"), (
                f"Event {event['name']} has no consumers"
            )

    def test_user_created_publisher(self, parsed):
        ev = next(e for e in parsed.events if e["name"] == "user.created")
        assert ev["publisher_service"] == "auth-service"

    def test_invoice_posted_publisher_and_consumers(self, parsed):
        ev = next(e for e in parsed.events if e["name"] == "invoice.posted")
        assert ev["publisher_service"] == "invoicing-service"
        consumers = set(ev["subscriber_services"])
        assert "accounts-service" in consumers
        assert "reporting-service" in consumers
        assert "notification-service" in consumers

    def test_journal_posted_publisher(self, parsed):
        ev = next(e for e in parsed.events if e["name"] == "journal.posted")
        assert ev["publisher_service"] == "accounts-service"

    def test_period_closing_consumers(self, parsed):
        ev = next(e for e in parsed.events if e["name"] == "period.closing")
        consumers = set(ev["subscriber_services"])
        assert "invoicing-service" in consumers

    def test_payment_received_publisher(self, parsed):
        ev = next(e for e in parsed.events if e["name"] == "payment.received")
        assert ev["publisher_service"] == "invoicing-service"

    def test_invoice_posted_payload_fields(self, parsed):
        ev = next(e for e in parsed.events if e["name"] == "invoice.posted")
        payload = ev.get("payload_fields", [])
        assert len(payload) >= 5, f"invoice.posted should have 5+ payload fields, got {len(payload)}: {payload}"
        assert "invoice_id" in payload
        assert "tenant_id" in payload


# ===================================================================
# State Machine Tests
# ===================================================================

class TestStateMachines:
    def test_state_machine_count(self, parsed):
        entities = {sm["entity"] for sm in parsed.state_machines}
        assert len(entities) >= 3, (
            f"Expected 3+ state machines, got {len(entities)}: {entities}"
        )

    def test_invoice_state_machine_exists(self, parsed):
        sm = next((sm for sm in parsed.state_machines if sm["entity"] == "Invoice"), None)
        assert sm is not None, "No state machine for Invoice"
        assert len(sm["states"]) >= 6, (
            f"Invoice should have 6+ states, got {len(sm['states'])}: {sm['states']}"
        )

    def test_journal_entry_state_machine_exists(self, parsed):
        sm = next((sm for sm in parsed.state_machines if sm["entity"] == "JournalEntry"), None)
        assert sm is not None, "No state machine for JournalEntry"
        assert len(sm["states"]) >= 5, (
            f"JournalEntry should have 5+ states, got {len(sm['states'])}: {sm['states']}"
        )

    def test_fiscal_period_state_machine_exists(self, parsed):
        sm = next((sm for sm in parsed.state_machines if sm["entity"] == "FiscalPeriod"), None)
        assert sm is not None, "No state machine for FiscalPeriod"
        assert len(sm["states"]) >= 4, (
            f"FiscalPeriod should have 4+ states, got {len(sm['states'])}: {sm['states']}"
        )

    def test_invoice_transitions(self, parsed):
        sm = next(sm for sm in parsed.state_machines if sm["entity"] == "Invoice")
        assert len(sm["transitions"]) >= 6, (
            f"Invoice should have 6+ transitions, got {len(sm['transitions'])}"
        )


# ===================================================================
# Relationship Tests
# ===================================================================

class TestRelationships:
    def test_has_many_count(self, parsed):
        hm = [r for r in parsed.relationships if r["type"] == "HAS_MANY"]
        assert len(hm) >= 6, f"Expected 6+ HAS_MANY, got {len(hm)}"

    def test_belongs_to_count(self, parsed):
        bt = [r for r in parsed.relationships if r["type"] == "BELONGS_TO"]
        assert len(bt) >= 5, f"Expected 5+ BELONGS_TO, got {len(bt)}"

    def test_references_count(self, parsed):
        ref = [r for r in parsed.relationships if r["type"] == "REFERENCES"]
        assert len(ref) >= 3, f"Expected 3+ REFERENCES, got {len(ref)}"


# ===================================================================
# Explicit Services Tests
# ===================================================================

class TestExplicitServices:
    def test_explicit_service_count(self, parsed):
        assert len(parsed.explicit_services) == 6, (
            f"Expected 6, got {len(parsed.explicit_services)}"
        )

    def test_explicit_service_names(self, parsed):
        names = {s["name"] for s in parsed.explicit_services}
        expected = {
            "auth-service", "accounts-service", "invoicing-service",
            "reporting-service", "notification-service", "frontend",
        }
        assert names == expected, f"Missing: {expected - names}, Extra: {names - expected}"

    def test_explicit_service_tech_stacks(self, parsed):
        stacks = {s["name"]: (s.get("language"), s.get("framework")) for s in parsed.explicit_services}
        assert stacks["auth-service"] == ("Python", "FastAPI")
        assert stacks["accounts-service"] == ("TypeScript", "NestJS")
        assert stacks["invoicing-service"] == ("Python", "FastAPI")
        assert stacks["notification-service"] == ("TypeScript", "NestJS")

    def test_frontend_is_frontend(self, parsed):
        fe = next(s for s in parsed.explicit_services if s["name"] == "frontend")
        assert fe["is_frontend"] is True
        assert fe["framework"] == "Angular"


# ===================================================================
# Integration Tests
# ===================================================================

class TestIntegration:
    def test_full_pipeline_completes(self, prd_text):
        """Full decompose pipeline completes without error on real PRD."""
        parsed = parse_prd(prd_text)
        boundaries = identify_boundaries(parsed)
        smap = build_service_map(parsed, boundaries)
        dmodel = build_domain_model(parsed, boundaries)
        assert len(smap.services) == 6
        assert len(dmodel.entities) == 12

    def test_domain_model_entities(self, domain_model):
        names = {e.name for e in domain_model.entities}
        assert len(names) == 12
        assert "User" in names
        assert "Invoice" in names

    def test_domain_model_relationships(self, domain_model):
        assert len(domain_model.relationships) >= 10

    def test_domain_model_owning_service_assigned(self, domain_model):
        """B3: Every entity in the domain model has an owning_service (not 'unassigned')."""
        unassigned = [e.name for e in domain_model.entities if e.owning_service == "unassigned"]
        assert unassigned == [], f"Unassigned entities: {unassigned}"

    def test_domain_model_state_machines(self, domain_model):
        """B4: At least 3 entities in the domain model have state machines."""
        sm_entities = [e.name for e in domain_model.entities if e.state_machine is not None]
        assert len(sm_entities) >= 3, (
            f"Expected 3+ entities with state machines, got {len(sm_entities)}: {sm_entities}"
        )

    def test_domain_model_entity_fields(self, domain_model):
        """B5: All 12 entities in the domain model have fields."""
        for entity in domain_model.entities:
            assert len(entity.fields) > 0, f"Entity {entity.name} has no fields in domain model"
        assert len([e for e in domain_model.entities if len(e.fields) > 0]) == 12

    def test_domain_model_owning_services_match(self, domain_model):
        """B3 detailed: Each entity maps to the correct service."""
        expected = {
            "User": "auth-service", "Tenant": "auth-service", "Role": "auth-service",
            "Account": "accounts-service", "JournalEntry": "accounts-service",
            "JournalLine": "accounts-service", "FiscalPeriod": "accounts-service",
            "AuditEntry": "accounts-service",
            "Invoice": "invoicing-service", "InvoiceLine": "invoicing-service",
            "Payment": "invoicing-service",
            "Notification": "notification-service",
        }
        actual = {e.name: e.owning_service for e in domain_model.entities}
        for name, expected_svc in expected.items():
            assert actual.get(name) == expected_svc, (
                f"{name} -> {actual.get(name)}, expected {expected_svc}"
            )


# ===================================================================
# Contract Tests
# ===================================================================

class TestServiceContracts:
    def test_every_backend_service_provides_contract(self, service_map):
        """B6: Every backend service provides at least one contract."""
        for svc in service_map.services:
            if svc.is_frontend:
                # Frontend services do not provide API contracts (Fix 12)
                assert len(svc.provides_contracts) == 0, (
                    f"Frontend {svc.name} should NOT provide contracts"
                )
            else:
                assert len(svc.provides_contracts) > 0, (
                    f"{svc.name} provides no contracts"
                )

    def test_backend_services_have_api_contracts(self, service_map):
        """A10: All 5 backend services have API contracts."""
        backend = [s for s in service_map.services if s.name != "frontend"]
        assert len(backend) == 5
        for svc in backend:
            assert any("api" in c.lower() for c in svc.provides_contracts), (
                f"{svc.name} has no API contract in {svc.provides_contracts}"
            )

    def test_no_dual_owned_entities(self, service_map):
        """A14: No entity is owned by more than one service."""
        entity_to_services = {}
        for svc in service_map.services:
            for entity in svc.owns_entities:
                entity_to_services.setdefault(entity, []).append(svc.name)
        dual = {e: svcs for e, svcs in entity_to_services.items() if len(svcs) > 1}
        assert dual == {}, f"Dual-owned entities: {dual}"


# ===================================================================
# Relationship Diversity Tests
# ===================================================================

class TestRelationshipDiversity:
    def test_at_least_3_relationship_types(self, parsed):
        """A13: At least 3 distinct relationship types."""
        types = {r["type"] for r in parsed.relationships}
        assert len(types) >= 3, f"Only {len(types)} types: {types}"

    def test_relationship_types_include_core(self, parsed):
        """Core relationship types present."""
        types = {r["type"] for r in parsed.relationships}
        assert "HAS_MANY" in types
        assert "BELONGS_TO" in types
        assert "REFERENCES" in types


# ===================================================================
# Events Metadata Completeness Tests
# ===================================================================

class TestEventsMetadata:
    def test_all_events_have_complete_metadata(self, parsed):
        """B8: All 13 events have publisher, consumers, and payload fields."""
        incomplete = []
        for ev in parsed.events:
            has_pub = bool(ev.get("publisher_service"))
            has_cons = bool(ev.get("subscriber_services"))
            has_payload = bool(ev.get("payload_fields"))
            if not (has_pub and has_cons and has_payload):
                incomplete.append(
                    f"{ev['name']} (pub={has_pub}, cons={has_cons}, payload={has_payload})"
                )
        assert incomplete == [], f"Incomplete events: {incomplete}"

    def test_all_events_have_payload_fields(self, parsed):
        for ev in parsed.events:
            payload = ev.get("payload_fields", [])
            assert len(payload) > 0, f"Event {ev['name']} has no payload fields"


# ===================================================================
# Project Metadata Tests
# ===================================================================

class TestProjectMetadata:
    def test_project_name(self, parsed):
        """B9: Project name contains LedgerPro."""
        assert "LedgerPro" in parsed.project_name or "Ledger" in parsed.project_name, (
            f"Project name: {parsed.project_name}"
        )

    def test_technology_hints_database(self, parsed):
        """B10: Technology hints include database."""
        assert parsed.technology_hints.get("database") is not None, (
            f"No database hint. Hints: {parsed.technology_hints}"
        )

    def test_technology_hints_keys(self, parsed):
        """B10: Key technology hints are present."""
        hints = parsed.technology_hints
        assert "database" in hints
        assert hints["database"] == "PostgreSQL"

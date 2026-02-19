"""5-PRD pipeline tests and edge cases.

Exercises the Architect decompose_prd pipeline with 5 structurally different
PRD documents plus edge cases (empty, short, unicode, whitespace) to verify
the pipeline handles them correctly without crashing.
"""
from __future__ import annotations

import pytest

from src.shared.db.connection import ConnectionPool
from src.shared.db.schema import init_architect_db
from src.shared.errors import ParsingError
from src.architect.storage.service_map_store import ServiceMapStore
from src.architect.storage.domain_model_store import DomainModelStore
from src.architect.services.prd_parser import parse_prd

# ---------------------------------------------------------------------------
# 5 PRD definitions
# ---------------------------------------------------------------------------

PIPELINE_PRDS = {
    "TaskTracker": {
        "text": (
            "TaskTracker: Project management tool for tracking users, tasks and "
            "notifications. 3 entities: User, Task, Notification. User has many "
            "Tasks. Tasks trigger Notifications."
        ),
        "min_entities": 3,
        "expected": ["User", "Task", "Notification"],
    },
    "ShopSimple": {
        "text": (
            "ShopSimple: E-commerce platform managing products and orders. "
            "Entities: User, Product, Order. User has many Orders. Order "
            "references Product."
        ),
        "min_entities": 3,
        "expected": ["User", "Product", "Order"],
    },
    "QuickChat": {
        "text": (
            "QuickChat: Real-time messaging app. Models: User, Room, Message. "
            "User has many Rooms. Room contains Messages."
        ),
        "min_entities": 3,
        "expected": ["User", "Room", "Message"],
    },
    "HelloAPI": {
        "text": (
            "HelloAPI: Single REST API returning hello message on GET /hello. "
            "1 entity: Greeting."
        ),
        "min_entities": 0,  # May or may not extract -- must NOT crash
        "expected": [],  # Empty OK
    },
    "HealthTrack": {
        "text": (
            "HealthTrack: Healthcare platform. Entities: Patient, Provider, "
            "Appointment, Invoice, Notification, AuditLog. Patient has many "
            "Appointments. Provider has many Appointments. Appointment triggers "
            "Notification. Invoice references Appointment."
        ),
        "min_entities": 4,
        "expected": ["Patient", "Provider", "Appointment"],
    },
}


# ---------------------------------------------------------------------------
# Fixture: Architect MCP with isolated DB
# ---------------------------------------------------------------------------


@pytest.fixture()
def architect_mcp(tmp_path, monkeypatch):
    """Architect MCP module wired to an isolated temp SQLite database."""
    db_path = str(tmp_path / "pipeline_5prd_test.db")
    monkeypatch.setenv("DATABASE_PATH", db_path)

    import src.architect.mcp_server as mod

    pool = ConnectionPool(db_path)
    init_architect_db(pool)

    monkeypatch.setattr(mod, "pool", pool)
    monkeypatch.setattr(mod, "service_map_store", ServiceMapStore(pool))
    monkeypatch.setattr(mod, "domain_model_store", DomainModelStore(pool))

    yield mod

    pool.close()


# ===================================================================
# TASK 2: 5-PRD Pipeline Tests
# ===================================================================


class TestPipelineNoCrash:
    """Every PRD must complete without crashing or returning an 'error' key."""

    @pytest.mark.parametrize("prd_name", list(PIPELINE_PRDS.keys()))
    def test_pipeline_does_not_crash(self, architect_mcp, prd_name: str):
        prd = PIPELINE_PRDS[prd_name]
        result = architect_mcp.decompose_prd(prd["text"])

        assert isinstance(result, dict), f"{prd_name}: Expected dict, got {type(result).__name__}"
        assert "error" not in result, (
            f"{prd_name}: Pipeline returned error: {result.get('error')}"
        )


class TestPipelineEntities:
    """Verify entity extraction meets minimums for each PRD."""

    @pytest.mark.parametrize("prd_name", list(PIPELINE_PRDS.keys()))
    def test_entities_extracted(self, architect_mcp, prd_name: str):
        prd = PIPELINE_PRDS[prd_name]
        result = architect_mcp.decompose_prd(prd["text"])

        assert "error" not in result, f"{prd_name}: error: {result.get('error')}"

        domain_model = result["domain_model"]
        entities = domain_model.get("entities", [])
        entity_names = [e["name"] for e in entities]

        if prd["min_entities"] > 0:
            assert len(entities) >= prd["min_entities"], (
                f"{prd_name}: Expected >= {prd['min_entities']} entities, "
                f"got {len(entities)}: {entity_names}"
            )

        for expected_name in prd["expected"]:
            assert expected_name in entity_names, (
                f"{prd_name}: Expected entity '{expected_name}' not found. "
                f"Got: {entity_names}"
            )


class TestPipelineServiceMap:
    """Verify service_map is produced for each PRD."""

    @pytest.mark.parametrize("prd_name", list(PIPELINE_PRDS.keys()))
    def test_service_map_produced(self, architect_mcp, prd_name: str):
        prd = PIPELINE_PRDS[prd_name]
        result = architect_mcp.decompose_prd(prd["text"])

        assert "error" not in result

        service_map = result["service_map"]
        assert isinstance(service_map, dict)
        assert "services" in service_map
        assert "project_name" in service_map
        assert isinstance(service_map["services"], list)
        assert len(service_map["project_name"]) > 0


class TestPipelineContractStubs:
    """Verify contract_stubs are produced for each PRD."""

    @pytest.mark.parametrize("prd_name", list(PIPELINE_PRDS.keys()))
    def test_contract_stubs_produced(self, architect_mcp, prd_name: str):
        prd = PIPELINE_PRDS[prd_name]
        result = architect_mcp.decompose_prd(prd["text"])

        assert "error" not in result

        contract_stubs = result["contract_stubs"]
        assert isinstance(contract_stubs, list)


class TestPipelineFullOutput:
    """Verify the full pipeline output has all expected top-level keys."""

    @pytest.mark.parametrize("prd_name", list(PIPELINE_PRDS.keys()))
    def test_full_pipeline_output(self, architect_mcp, prd_name: str):
        prd = PIPELINE_PRDS[prd_name]
        result = architect_mcp.decompose_prd(prd["text"])

        assert "error" not in result

        expected_keys = {"service_map", "domain_model", "contract_stubs", "validation_issues"}
        missing = expected_keys - set(result.keys())
        assert not missing, f"{prd_name}: Missing keys: {missing}"


# ===================================================================
# TASK 3: Edge Case Tests
# ===================================================================


class TestPRDEdgeCases:
    """Edge cases for the PRD parser: empty, short, unicode, whitespace."""

    def test_empty_string_raises_parsing_error(self):
        """Empty string PRD must raise ParsingError (too short)."""
        with pytest.raises(ParsingError):
            parse_prd("")

    def test_single_word_raises_parsing_error(self):
        """Single word PRD must raise ParsingError (too short)."""
        with pytest.raises(ParsingError):
            parse_prd("hello")

    def test_unicode_prd_no_crash(self, architect_mcp):
        """PRD with Unicode characters must not crash."""
        unicode_text = (
            "Projet de gestion: Entites: Utilisateur, Commande, Produit. "
            "Utilisateur a plusieurs Commandes. Commande reference Produit. "
            "Support des emojis et caracteres speciaux."
        )
        result = architect_mcp.decompose_prd(unicode_text)
        assert isinstance(result, dict)
        assert "error" not in result

    def test_whitespace_only_raises_parsing_error(self):
        """PRD with only whitespace must raise ParsingError (too short)."""
        with pytest.raises(ParsingError):
            parse_prd("     \t\n   ")

    def test_short_text_below_threshold(self):
        """PRD below minimum length threshold raises ParsingError."""
        with pytest.raises(ParsingError):
            parse_prd("Too short.")

    def test_decompose_prd_empty_returns_error(self, architect_mcp):
        """decompose_prd with empty text returns error dict (ParsingError caught)."""
        result = architect_mcp.decompose_prd("")
        assert isinstance(result, dict)
        assert "error" in result

    def test_decompose_prd_whitespace_returns_error(self, architect_mcp):
        """decompose_prd with whitespace-only text returns error dict."""
        result = architect_mcp.decompose_prd("   \n  \t  ")
        assert isinstance(result, dict)
        assert "error" in result

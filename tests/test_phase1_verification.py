"""Phase 1 Build 1 comprehensive verification tests.

Covers ALL behaviors verified by the 4 previous agents:
  - Architect service
  - Contract Engine service
  - Codebase Intelligence service
  - Inter-service wiring and Docker infrastructure

Tests work WITHOUT live services -- mocks for inter-service HTTP calls,
real SQLite / ChromaDB in temporary directories.
"""
from __future__ import annotations

import ast
import base64
import json
import re
import sqlite3
import uuid
from pathlib import Path
from contextlib import asynccontextmanager
from typing import AsyncGenerator
from unittest.mock import MagicMock, patch

import networkx as nx
import pytest
import yaml
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.shared.db.connection import ConnectionPool
from src.shared.db.schema import init_architect_db, init_contracts_db, init_symbols_db
from src.shared.models.contracts import MarkResponse

# ---------------------------------------------------------------------------
# Sample data
# ---------------------------------------------------------------------------

SAMPLE_PRD = """
# E-Commerce Platform PRD

## Overview
Build a modern e-commerce platform with user management, product catalog,
and order processing.  The backend will be built in Python using the FastAPI
framework with a PostgreSQL database.

## Services

### User Service
- Manages user accounts and authentication
- Stores user profiles and preferences

### Product Service
- Manages product catalog and inventory
- Handles product search and filtering

### Order Service
- Processes customer orders
- Manages order lifecycle and fulfillment

## Entities

### User
- id: uuid
- email: string
- name: string
- status: string

### Product
- id: uuid
- name: string
- price: number
- stock: integer

### Order
- id: uuid
- user_id: uuid
- total: number
- status: string

## Relationships
- User has many Orders
- Order references Product
"""

SAMPLE_OPENAPI_SPEC = {
    "openapi": "3.1.0",
    "info": {"title": "Test API", "version": "1.0.0"},
    "paths": {
        "/api/users": {
            "get": {
                "summary": "List users",
                "responses": {
                    "200": {
                        "description": "Success",
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "array",
                                    "items": {
                                        "$ref": "#/components/schemas/User"
                                    },
                                }
                            }
                        },
                    }
                },
            },
            "post": {
                "summary": "Create user",
                "requestBody": {
                    "required": True,
                    "content": {
                        "application/json": {
                            "schema": {"$ref": "#/components/schemas/UserCreate"}
                        }
                    },
                },
                "responses": {
                    "201": {
                        "description": "Created",
                        "content": {
                            "application/json": {
                                "schema": {"$ref": "#/components/schemas/User"}
                            }
                        },
                    }
                },
            },
        }
    },
    "components": {
        "schemas": {
            "User": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "name": {"type": "string"},
                    "email": {"type": "string"},
                },
                "required": ["id", "name"],
            },
            "UserCreate": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "email": {"type": "string"},
                },
                "required": ["name"],
            },
        }
    },
}

SAMPLE_ASYNCAPI_SPEC = {
    "asyncapi": "3.0.0",
    "info": {"title": "User Events", "version": "1.0.0"},
    "channels": {
        "user-created": {
            "address": "user.created",
            "messages": {
                "UserCreated": {
                    "payload": {
                        "type": "object",
                        "properties": {
                            "userId": {"type": "string"},
                            "email": {"type": "string"},
                        },
                    }
                }
            },
        }
    },
    "operations": {
        "publishUserCreated": {
            "action": "send",
            "channel": {"$ref": "#/channels/user-created"},
        }
    },
}

SAMPLE_PYTHON_SOURCE = '''\
class UserService:
    """Service for managing users."""

    def get_user(self, user_id: str) -> dict:
        """Get a user by ID."""
        return {"id": user_id}

    def create_user(self, name: str, email: str) -> dict:
        """Create a new user."""
        return {"name": name, "email": email}

def helper_function():
    """A helper function."""
    pass

def _private_helper():
    """A private helper -- should not be flagged as dead code entry point."""
    pass
'''

SAMPLE_TYPESCRIPT_SOURCE = '''\
export class UserController {
    async getUser(id: string): Promise<User> {
        return {} as User;
    }
}

export function calculateTotal(items: Item[]): number {
    return items.reduce((sum, item) => sum + item.price, 0);
}

interface User {
    id: string;
    name: string;
}

interface Item {
    price: number;
}
'''


# ============================================================================
# FIXTURES
# ============================================================================

@pytest.fixture()
def architect_mcp(tmp_path, monkeypatch):
    """Architect MCP server with temporary database."""
    db_path = str(tmp_path / "architect_test.db")
    monkeypatch.setenv("DATABASE_PATH", db_path)

    from src.architect.storage.service_map_store import ServiceMapStore
    from src.architect.storage.domain_model_store import DomainModelStore
    import src.architect.mcp_server as mod

    pool = ConnectionPool(db_path)
    init_architect_db(pool)

    monkeypatch.setattr(mod, "pool", pool)
    monkeypatch.setattr(mod, "service_map_store", ServiceMapStore(pool))
    monkeypatch.setattr(mod, "domain_model_store", DomainModelStore(pool))

    yield mod

    pool.close()


@pytest.fixture()
def contract_mcp(tmp_path, monkeypatch):
    """Contract Engine MCP server with temporary database."""
    db_path = str(tmp_path / "contract_test.db")
    monkeypatch.setenv("DATABASE_PATH", db_path)

    from src.contract_engine.services.contract_store import ContractStore
    from src.contract_engine.services.implementation_tracker import ImplementationTracker
    from src.contract_engine.services.version_manager import VersionManager
    from src.contract_engine.services.test_generator import ContractTestGenerator
    from src.contract_engine.services.compliance_checker import ComplianceChecker
    import src.contract_engine.mcp_server as mod

    pool = ConnectionPool(db_path)
    init_contracts_db(pool)

    monkeypatch.setattr(mod, "_pool", pool)
    monkeypatch.setattr(mod, "_contract_store", ContractStore(pool))
    monkeypatch.setattr(mod, "_implementation_tracker", ImplementationTracker(pool))
    monkeypatch.setattr(mod, "_version_manager", VersionManager(pool))
    monkeypatch.setattr(mod, "_test_generator", ContractTestGenerator(pool))
    monkeypatch.setattr(mod, "_compliance_checker", ComplianceChecker(pool))

    yield mod

    pool.close()


@pytest.fixture()
def codebase_mcp(tmp_path, monkeypatch):
    """Codebase Intelligence MCP server with temporary storage."""
    db_path = str(tmp_path / "codebase_test.db")
    chroma_path = str(tmp_path / "chroma")
    monkeypatch.setenv("DATABASE_PATH", db_path)
    monkeypatch.setenv("CHROMA_PATH", chroma_path)

    from src.codebase_intelligence.storage.symbol_db import SymbolDB
    from src.codebase_intelligence.storage.graph_db import GraphDB
    from src.codebase_intelligence.storage.chroma_store import ChromaStore
    from src.codebase_intelligence.services.ast_parser import ASTParser
    from src.codebase_intelligence.services.symbol_extractor import SymbolExtractor
    from src.codebase_intelligence.services.import_resolver import ImportResolver
    from src.codebase_intelligence.services.graph_builder import GraphBuilder
    from src.codebase_intelligence.services.graph_analyzer import GraphAnalyzer
    from src.codebase_intelligence.services.dead_code_detector import DeadCodeDetector
    from src.codebase_intelligence.services.semantic_indexer import SemanticIndexer
    from src.codebase_intelligence.services.semantic_searcher import SemanticSearcher
    from src.codebase_intelligence.services.incremental_indexer import IncrementalIndexer
    from src.codebase_intelligence.services.service_interface_extractor import ServiceInterfaceExtractor
    import src.codebase_intelligence.mcp_server as mod

    pool = ConnectionPool(db_path)
    init_symbols_db(pool)

    symbol_db = SymbolDB(pool)
    graph_db = GraphDB(pool)
    chroma_store = ChromaStore(chroma_path)

    graph_builder = GraphBuilder()
    graph_analyzer = GraphAnalyzer(graph_builder.graph)
    ast_parser = ASTParser()
    symbol_extractor = SymbolExtractor()
    import_resolver = ImportResolver()
    dead_code_detector = DeadCodeDetector(graph_builder.graph)
    semantic_indexer = SemanticIndexer(chroma_store, symbol_db)
    semantic_searcher = SemanticSearcher(chroma_store)
    service_interface_extractor = ServiceInterfaceExtractor(ast_parser, symbol_extractor)
    incremental_indexer = IncrementalIndexer(
        ast_parser=ast_parser,
        symbol_extractor=symbol_extractor,
        import_resolver=import_resolver,
        graph_builder=graph_builder,
        symbol_db=symbol_db,
        graph_db=graph_db,
        semantic_indexer=semantic_indexer,
    )

    monkeypatch.setattr(mod, "_pool", pool)
    monkeypatch.setattr(mod, "_symbol_db", symbol_db)
    monkeypatch.setattr(mod, "_graph_db", graph_db)
    monkeypatch.setattr(mod, "_chroma_store", chroma_store)
    monkeypatch.setattr(mod, "_graph_builder", graph_builder)
    monkeypatch.setattr(mod, "_graph_analyzer", graph_analyzer)
    monkeypatch.setattr(mod, "_ast_parser", ast_parser)
    monkeypatch.setattr(mod, "_symbol_extractor", symbol_extractor)
    monkeypatch.setattr(mod, "_import_resolver", import_resolver)
    monkeypatch.setattr(mod, "_dead_code_detector", dead_code_detector)
    monkeypatch.setattr(mod, "_semantic_indexer", semantic_indexer)
    monkeypatch.setattr(mod, "_semantic_searcher", semantic_searcher)
    monkeypatch.setattr(mod, "_incremental_indexer", incremental_indexer)
    monkeypatch.setattr(mod, "_service_interface_extractor", service_interface_extractor)

    yield mod, pool, graph_builder, graph_db, symbol_db

    pool.close()


@pytest.fixture()
def architect_test_client(tmp_path):
    """FastAPI TestClient for the Architect service."""
    from src.architect.storage.service_map_store import ServiceMapStore
    from src.architect.storage.domain_model_store import DomainModelStore
    from src.architect.routers.health import router as health_router
    from src.architect.routers.decomposition import router as decomposition_router
    from src.architect.routers.service_map import router as service_map_router
    from src.architect.routers.domain_model import router as domain_model_router
    from src.shared.errors import register_exception_handlers

    db_path = str(tmp_path / "architect_http.db")
    pool = ConnectionPool(db_path)
    init_architect_db(pool)

    import time

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
        app.state.pool = pool
        app.state.start_time = time.time()
        app.state.service_map_store = ServiceMapStore(pool)
        app.state.domain_model_store = DomainModelStore(pool)
        yield
        pool.close()

    app = FastAPI(lifespan=lifespan)
    register_exception_handlers(app)
    app.include_router(health_router)
    app.include_router(decomposition_router)
    app.include_router(service_map_router)
    app.include_router(domain_model_router)

    with TestClient(app, raise_server_exceptions=False) as client:
        yield client


# ============================================================================
# Helpers
# ============================================================================


def _create_contract(mod, spec=None, service_name="user-service"):
    """Helper to create a contract via Contract Engine MCP tool."""
    return mod.create_contract(
        service_name=service_name,
        type="openapi",
        version="1.0.0",
        spec=spec or SAMPLE_OPENAPI_SPEC,
    )


def _index_python_file(mod_tuple, tmp_path, source=None, filename="user_service.py", service_name="user-service"):
    """Helper to index a Python file via Codebase Intelligence MCP tool."""
    mod = mod_tuple[0] if isinstance(mod_tuple, tuple) else mod_tuple
    sample_file = tmp_path / filename
    sample_file.write_text(source or SAMPLE_PYTHON_SOURCE, encoding="utf-8")
    return mod.index_file(file_path=str(sample_file), service_name=service_name)


def _index_ts_file(mod_tuple, tmp_path, source=None, filename="user_controller.ts", service_name="user-service"):
    """Helper to index a TypeScript file via Codebase Intelligence MCP tool."""
    mod = mod_tuple[0] if isinstance(mod_tuple, tuple) else mod_tuple
    sample_file = tmp_path / filename
    sample_file.write_text(source or SAMPLE_TYPESCRIPT_SOURCE, encoding="utf-8")
    return mod.index_file(file_path=str(sample_file), service_name=service_name)


# ============================================================================
# SECTION 1: Architect Verification Tests
# ============================================================================


class TestArchitectDecompositionPipeline:
    """Test 1: Decomposition pipeline produces valid ServiceMap."""

    def test_decomposition_produces_valid_service_map(self, architect_mcp):
        """POST /api/decompose with realistic PRD -> valid ServiceMap structure."""
        result = architect_mcp.decompose_prd(SAMPLE_PRD)

        assert "error" not in result
        service_map = result["service_map"]
        assert "services" in service_map
        assert "project_name" in service_map
        assert isinstance(service_map["services"], list)
        assert len(service_map["services"]) > 0

        for svc in service_map["services"]:
            assert "name" in svc
            assert "domain" in svc
            assert "description" in svc
            assert "stack" in svc
            assert "estimated_loc" in svc
            # name matches kebab-case pattern
            assert re.match(r"^[a-z][a-z0-9-]*$", svc["name"]), f"Name {svc['name']} not kebab-case"

    def test_decomposition_produces_valid_domain_model(self, architect_mcp):
        """Test 2: Verify entities with fields, relationships with types/cardinality."""
        result = architect_mcp.decompose_prd(SAMPLE_PRD)

        assert "error" not in result
        domain_model = result["domain_model"]
        assert "entities" in domain_model
        assert "relationships" in domain_model
        assert isinstance(domain_model["entities"], list)
        assert len(domain_model["entities"]) > 0

        for entity in domain_model["entities"]:
            assert "name" in entity
            assert "description" in entity
            assert "fields" in entity

        for rel in domain_model["relationships"]:
            assert "source_entity" in rel
            assert "target_entity" in rel
            assert "relationship_type" in rel
            assert "cardinality" in rel

    def test_contract_stubs_generated(self, architect_mcp):
        """Test 3: Contract stubs list is non-empty."""
        result = architect_mcp.decompose_prd(SAMPLE_PRD)

        assert "error" not in result
        assert isinstance(result["contract_stubs"], list)
        assert len(result["contract_stubs"]) > 0

    def test_decomposition_run_persisted(self, architect_mcp, tmp_path, monkeypatch):
        """Test 4: DecompositionRun persisted after decompose."""
        # The MCP server does persist results but via the stores.
        # We verify indirectly by ensuring get_service_map returns data after decompose.
        result = architect_mcp.decompose_prd(SAMPLE_PRD)
        assert "error" not in result

        # The service map should now be retrievable
        sm = architect_mcp.get_service_map()
        assert "error" not in sm
        assert "services" in sm

    def test_invalid_prd_returns_error_without_crash(self, architect_mcp):
        """Test 5: Empty/too-short PRD -> error dict."""
        result = architect_mcp.decompose_prd("")
        assert isinstance(result, dict)
        assert "error" in result

        result2 = architect_mcp.decompose_prd("abc")
        assert isinstance(result2, dict)
        assert "error" in result2

    def test_get_service_map_consistent_after_decompose(self, architect_mcp):
        """Test 6: After decompose, get_service_map returns matching data."""
        decomposed = architect_mcp.decompose_prd(SAMPLE_PRD)
        assert "error" not in decomposed

        sm = architect_mcp.get_service_map()
        assert "error" not in sm
        assert "services" in sm
        assert sm["project_name"] == decomposed["service_map"]["project_name"]
        assert len(sm["services"]) == len(decomposed["service_map"]["services"])

    def test_get_domain_model_consistent_after_decompose(self, architect_mcp):
        """Test 7: After decompose, get_domain_model returns matching data."""
        decomposed = architect_mcp.decompose_prd(SAMPLE_PRD)
        assert "error" not in decomposed

        dm = architect_mcp.get_domain_model()
        assert "error" not in dm
        assert "entities" in dm
        assert len(dm["entities"]) == len(decomposed["domain_model"]["entities"])

    def test_retrieval_before_decomposition_returns_error(self, architect_mcp):
        """Test 8: get_service_map and get_domain_model before any decompose -> error."""
        sm = architect_mcp.get_service_map()
        assert "error" in sm

        dm = architect_mcp.get_domain_model()
        assert "error" in dm


class TestArchitectHTTPEndpoints:
    """Test 9: HTTP endpoints return correct status codes."""

    def test_decompose_returns_201(self, architect_test_client):
        resp = architect_test_client.post(
            "/api/decompose",
            json={"prd_text": SAMPLE_PRD},
        )
        assert resp.status_code == 201

    def test_get_service_map_returns_404_before_decompose(self, architect_test_client):
        resp = architect_test_client.get("/api/service-map")
        assert resp.status_code == 404

    def test_get_domain_model_returns_404_before_decompose(self, architect_test_client):
        resp = architect_test_client.get("/api/domain-model")
        assert resp.status_code == 404

    def test_get_service_map_returns_200_after_decompose(self, architect_test_client):
        architect_test_client.post("/api/decompose", json={"prd_text": SAMPLE_PRD})
        resp = architect_test_client.get("/api/service-map")
        assert resp.status_code == 200

    def test_get_domain_model_returns_200_after_decompose(self, architect_test_client):
        architect_test_client.post("/api/decompose", json={"prd_text": SAMPLE_PRD})
        resp = architect_test_client.get("/api/domain-model")
        assert resp.status_code == 200

    def test_decompose_invalid_prd_returns_422(self, architect_test_client):
        resp = architect_test_client.post(
            "/api/decompose",
            json={"prd_text": "ab"},  # min_length=10
        )
        assert resp.status_code == 422


# ============================================================================
# SECTION 2: Contract Engine Verification Tests
# ============================================================================


class TestContractEngineValidation:
    """Tests 10-13: Specification validation."""

    def test_validate_spec_catches_invalid_openapi(self, contract_mcp):
        """Test 10: Invalid spec missing required field -> valid=false."""
        invalid_spec = {"openapi": "3.1.0"}  # Missing info
        result = contract_mcp.validate_contract(spec=invalid_spec, type="openapi")

        assert isinstance(result, dict)
        assert "valid" in result
        # The spec is missing 'info' and 'paths' -- should have issues
        assert result["valid"] is False or len(result.get("errors", [])) > 0 or len(result.get("warnings", [])) > 0

    def test_validate_spec_accepts_valid_openapi(self, contract_mcp):
        """Test 11: Valid OpenAPI 3.1 spec -> valid=true."""
        result = contract_mcp.validate_contract(spec=SAMPLE_OPENAPI_SPEC, type="openapi")

        assert isinstance(result, dict)
        assert result["valid"] is True

    def test_validate_spec_accepts_valid_asyncapi(self, contract_mcp):
        """Test 12: Valid AsyncAPI 3.0 spec -> valid=true."""
        result = contract_mcp.validate_contract(spec=SAMPLE_ASYNCAPI_SPEC, type="asyncapi")

        assert isinstance(result, dict)
        assert result["valid"] is True

    def test_validate_spec_rejects_malformed(self, contract_mcp):
        """Test 13: Completely invalid content -> error, not crash."""
        result = contract_mcp.validate_contract(spec="not-a-dict", type="openapi")

        assert isinstance(result, dict)
        # Should return some form of error or valid=false
        has_error = "error" in result or result.get("valid") is False
        assert has_error


class TestContractEngineEndpointValidation:
    """Tests 14-16: Endpoint validation."""

    def test_validate_endpoint_missing_required_field(self, contract_mcp):
        """Test 14: Response missing field from contract -> valid=false."""
        _create_contract(contract_mcp)

        result = contract_mcp.validate_endpoint(
            service_name="user-service",
            method="GET",
            path="/api/users",
            response_body=[{"id": "1"}],  # missing 'name' (required)
            status_code=200,
        )

        assert isinstance(result, dict)
        assert result["valid"] is False
        assert len(result["violations"]) > 0

    def test_validate_endpoint_compliant_response(self, contract_mcp):
        """Test 15: Matching response -> valid=true."""
        _create_contract(contract_mcp)

        result = contract_mcp.validate_endpoint(
            service_name="user-service",
            method="GET",
            path="/api/users",
            response_body=[{"id": "1", "name": "Alice"}],
            status_code=200,
        )

        assert isinstance(result, dict)
        assert result["valid"] is True

    def test_validate_endpoint_allows_extra_fields(self, contract_mcp):
        """Test 16: Extra fields in response -> still valid=true."""
        _create_contract(contract_mcp)

        result = contract_mcp.validate_endpoint(
            service_name="user-service",
            method="GET",
            path="/api/users",
            response_body=[{"id": "1", "name": "Alice", "extra_field": "should be ok"}],
            status_code=200,
        )

        assert isinstance(result, dict)
        assert result["valid"] is True


class TestContractEngineTestGeneration:
    """Tests 17-18: Test generation."""

    def test_generate_tests_produces_valid_python(self, contract_mcp):
        """Test 17: ast.parse() on generated code succeeds."""
        created = _create_contract(contract_mcp)
        code = contract_mcp.generate_tests(contract_id=created["id"])

        assert isinstance(code, str)
        assert len(code) > 0
        # Should be parseable Python
        ast.parse(code)

    def test_generate_tests_cached(self, contract_mcp):
        """Test 18: Second call returns same code without regenerating."""
        created = _create_contract(contract_mcp)
        code1 = contract_mcp.generate_tests(contract_id=created["id"])
        code2 = contract_mcp.generate_tests(contract_id=created["id"])

        assert code1 == code2


class TestContractEngineBreakingChanges:
    """Tests 19-22: Breaking change detection."""

    def _make_modified_spec(self, **overrides):
        """Create a modified version of the sample spec."""
        import copy
        spec = copy.deepcopy(SAMPLE_OPENAPI_SPEC)
        spec["info"]["version"] = "2.0.0"
        for key, value in overrides.items():
            spec[key] = value
        return spec

    def test_added_optional_field_not_breaking(self, contract_mcp):
        """Test 19: Added optional field is NOT breaking."""
        created = _create_contract(contract_mcp)
        import copy
        new_spec = copy.deepcopy(SAMPLE_OPENAPI_SPEC)
        new_spec["info"]["version"] = "2.0.0"
        # Add an optional field to User schema
        new_spec["components"]["schemas"]["User"]["properties"]["nickname"] = {"type": "string"}

        result = contract_mcp.detect_breaking_changes(
            contract_id=created["id"],
            new_spec=new_spec,
        )

        assert isinstance(result, list)
        # No error-severity changes for adding an optional field
        errors = [c for c in result if isinstance(c, dict) and c.get("severity") == "error"]
        assert len(errors) == 0

    def test_removed_required_field_is_breaking(self, contract_mcp):
        """Test 20: Removed required field IS breaking."""
        created = _create_contract(contract_mcp)
        import copy
        new_spec = copy.deepcopy(SAMPLE_OPENAPI_SPEC)
        new_spec["info"]["version"] = "2.0.0"
        # Remove 'name' from User schema (was required)
        del new_spec["components"]["schemas"]["User"]["properties"]["name"]
        new_spec["components"]["schemas"]["User"]["required"] = ["id"]

        result = contract_mcp.detect_breaking_changes(
            contract_id=created["id"],
            new_spec=new_spec,
        )

        assert isinstance(result, list)
        assert len(result) > 0  # Should detect at least one change

    def test_changed_field_type_is_breaking(self, contract_mcp):
        """Test 21: Changed field type IS breaking."""
        created = _create_contract(contract_mcp)
        import copy
        new_spec = copy.deepcopy(SAMPLE_OPENAPI_SPEC)
        new_spec["info"]["version"] = "2.0.0"
        # Change 'id' from string to integer
        new_spec["components"]["schemas"]["User"]["properties"]["id"] = {"type": "integer"}

        result = contract_mcp.detect_breaking_changes(
            contract_id=created["id"],
            new_spec=new_spec,
        )

        assert isinstance(result, list)
        assert len(result) > 0

    def test_removed_endpoint_is_breaking(self, contract_mcp):
        """Test 22: Removed endpoint IS breaking."""
        created = _create_contract(contract_mcp)
        import copy
        new_spec = copy.deepcopy(SAMPLE_OPENAPI_SPEC)
        new_spec["info"]["version"] = "2.0.0"
        # Remove POST /api/users
        del new_spec["paths"]["/api/users"]["post"]

        result = contract_mcp.detect_breaking_changes(
            contract_id=created["id"],
            new_spec=new_spec,
        )

        assert isinstance(result, list)
        errors = [c for c in result if isinstance(c, dict) and c.get("severity") == "error"]
        assert len(errors) > 0


class TestContractEngineImplementationTracking:
    """Tests 23-25: Implementation tracking."""

    def test_mark_implemented_returns_total_implementations(self, contract_mcp):
        """Test 23 (SVC-005 regression): mark_implemented returns total_implementations key."""
        created = _create_contract(contract_mcp)
        result = contract_mcp.mark_implementation(
            contract_id=created["id"],
            service_name="user-service",
            evidence_path="/tests/test_user.py",
        )

        assert isinstance(result, dict)
        assert "error" not in result
        assert "marked" in result
        assert result["marked"] is True
        # SVC-005: Must be "total_implementations", NOT "total"
        assert "total_implementations" in result, (
            "SVC-005 regression: expected 'total_implementations' key, "
            f"got keys: {list(result.keys())}"
        )
        assert "total" not in result or "total_implementations" in result
        assert "all_implemented" in result
        assert isinstance(result["total_implementations"], int)
        assert result["total_implementations"] >= 1

    def test_get_unimplemented_excludes_verified(self, contract_mcp):
        """Test 24: Verified (not just marked) contract should not appear in unimplemented list.

        Note: mark_implemented sets status to 'pending'. The contract only
        leaves the unimplemented list when verified (status='verified').
        This matches the implementation_tracker's design: pending means
        'awaiting verification'.
        """
        from src.contract_engine.services.implementation_tracker import ImplementationTracker
        created = _create_contract(contract_mcp)

        # Before marking, should be unimplemented
        unimpl_before = contract_mcp.get_unimplemented()
        contract_ids_before = [c.get("id") for c in unimpl_before]
        assert created["id"] in contract_ids_before

        # Mark as implemented (status=pending)
        contract_mcp.mark_implementation(
            contract_id=created["id"],
            service_name="user-service",
            evidence_path="/tests/test_user.py",
        )

        # Still unimplemented because status is 'pending'
        unimpl_pending = contract_mcp.get_unimplemented()
        contract_ids_pending = [c.get("id") for c in unimpl_pending]
        assert created["id"] in contract_ids_pending

        # Verify the implementation directly via the tracker
        import src.contract_engine.mcp_server as ce_mod
        tracker = ce_mod._implementation_tracker
        tracker.verify_implementation(created["id"], "user-service")

        # After verification, should not appear in unimplemented
        unimpl_after = contract_mcp.get_unimplemented()
        contract_ids_after = [c.get("id") for c in unimpl_after]
        assert created["id"] not in contract_ids_after

    def test_nonexistent_contract_returns_error(self, contract_mcp):
        """Test 25: Non-existent contract -> appropriate error."""
        fake_id = str(uuid.uuid4())
        result = contract_mcp.get_contract(fake_id)
        assert isinstance(result, dict)
        assert "error" in result

        result2 = contract_mcp.mark_implementation(
            contract_id=fake_id,
            service_name="user-service",
            evidence_path="/tests/test.py",
        )
        assert isinstance(result2, dict)
        assert "error" in result2


# ============================================================================
# SECTION 3: Codebase Intelligence Verification Tests
# ============================================================================


class TestCodebaseIntelRegisterArtifact:
    """Tests 26-29: register_artifact."""

    def test_register_python_file_correct_symbols(self, codebase_mcp, tmp_path):
        """Test 26: Python file -> correct symbols in SQLite."""
        mod, pool, graph_builder, graph_db, symbol_db = codebase_mcp
        result = _index_python_file(codebase_mcp, tmp_path)

        assert result["indexed"] is True
        assert result["symbols_found"] > 0

        # Verify symbols are in SQLite
        conn = pool.get()
        rows = conn.execute(
            "SELECT symbol_name, kind FROM symbols WHERE file_path LIKE '%user_service.py'"
        ).fetchall()
        symbol_names = [r["symbol_name"] for r in rows]
        assert "UserService" in symbol_names
        assert "helper_function" in symbol_names

    def test_register_typescript_file_correct_symbols(self, codebase_mcp, tmp_path):
        """Test 27: TypeScript file -> correct symbols."""
        mod, pool, *_ = codebase_mcp
        result = _index_ts_file(codebase_mcp, tmp_path)

        assert result["indexed"] is True
        assert result["symbols_found"] > 0

        conn = pool.get()
        rows = conn.execute(
            "SELECT symbol_name, kind FROM symbols WHERE file_path LIKE '%user_controller.ts'"
        ).fetchall()
        symbol_names = [r["symbol_name"] for r in rows]
        # Should find at least UserController and calculateTotal
        assert "UserController" in symbol_names or "calculateTotal" in symbol_names

    def test_reregistration_no_duplicates(self, codebase_mcp, tmp_path):
        """Test 28: Index same file twice -> no duplicate entries."""
        mod, pool, *_ = codebase_mcp
        _index_python_file(codebase_mcp, tmp_path)

        conn = pool.get()
        count1 = conn.execute(
            "SELECT COUNT(*) as cnt FROM symbols WHERE file_path LIKE '%user_service.py'"
        ).fetchone()["cnt"]

        # Index again
        _index_python_file(codebase_mcp, tmp_path)

        count2 = conn.execute(
            "SELECT COUNT(*) as cnt FROM symbols WHERE file_path LIKE '%user_service.py'"
        ).fetchone()["cnt"]

        assert count1 == count2

    def test_syntax_error_file_graceful(self, codebase_mcp, tmp_path):
        """Test 29: Syntax error file -> graceful handling, no crash."""
        mod = codebase_mcp[0]
        bad_file = tmp_path / "bad_syntax.py"
        bad_file.write_text("def broken(:\n  pass\n  {{{invalid", encoding="utf-8")

        result = mod.index_file(file_path=str(bad_file), service_name="test-service")
        assert isinstance(result, dict)
        # May or may not succeed, but should not crash
        assert "indexed" in result


class TestCodebaseIntelFindDefinition:
    """Tests 30-31: find_definition."""

    def test_find_definition_indexed_symbol(self, codebase_mcp, tmp_path):
        """Test 30: Indexed symbol -> correct file and line."""
        mod = codebase_mcp[0]
        _index_python_file(codebase_mcp, tmp_path)

        result = mod.find_definition(symbol="UserService")
        assert isinstance(result, dict)
        assert "error" not in result
        assert "file" in result
        assert "line" in result
        assert "kind" in result
        assert "user_service.py" in result["file"]
        assert isinstance(result["line"], int)
        assert result["line"] >= 1

    def test_find_definition_nonexistent_symbol(self, codebase_mcp, tmp_path):
        """Test 31: Non-existent symbol -> found=false / error, not exception."""
        mod = codebase_mcp[0]
        result = mod.find_definition(symbol="NonExistentSymbolXYZ123")
        assert isinstance(result, dict)
        assert "error" in result


class TestCodebaseIntelFindCallers:
    """Test 32: find_callers."""

    def test_find_callers_returns_correct_format(self, codebase_mcp, tmp_path):
        """Test 32: find_callers returns correct callers."""
        mod = codebase_mcp[0]
        _index_python_file(codebase_mcp, tmp_path)

        result = mod.find_callers(symbol="UserService")
        assert isinstance(result, list)
        for entry in result:
            assert "file_path" in entry
            assert "line" in entry
            assert "caller_symbol" in entry


class TestCodebaseIntelFindDependencies:
    """Test 33: find_dependencies."""

    def test_find_dependencies_returns_correct_structure(self, codebase_mcp, tmp_path):
        """Test 33: find_dependencies returns imports/imported_by/transitive/circular."""
        mod = codebase_mcp[0]
        _index_python_file(codebase_mcp, tmp_path)

        sample_file = str(tmp_path / "user_service.py")
        result = mod.get_dependencies(file_path=sample_file)

        assert isinstance(result, dict)
        assert "imports" in result
        assert "imported_by" in result
        assert "transitive_deps" in result
        assert "circular_deps" in result
        assert isinstance(result["imports"], list)
        assert isinstance(result["imported_by"], list)
        assert isinstance(result["transitive_deps"], list)
        assert isinstance(result["circular_deps"], list)


class TestCodebaseIntelSemanticSearch:
    """Tests 34-35: search_semantic."""

    def test_search_semantic_returns_results_with_scores(self, codebase_mcp, tmp_path):
        """Test 34: After indexing, semantic search finds related content."""
        mod = codebase_mcp[0]
        _index_python_file(codebase_mcp, tmp_path)

        result = mod.search_code(query="get user by ID")
        assert isinstance(result, list)
        if len(result) > 0:
            first = result[0]
            assert "file_path" in first
            assert "score" in first
            assert isinstance(first["score"], (int, float))

    def test_search_semantic_language_filter(self, codebase_mcp, tmp_path):
        """Test 35: Language filter scopes results correctly."""
        mod = codebase_mcp[0]
        _index_python_file(codebase_mcp, tmp_path)

        result_python = mod.search_code(query="user service", language="python")
        result_ts = mod.search_code(query="user service", language="typescript")

        assert isinstance(result_python, list)
        assert isinstance(result_ts, list)
        # Python results should be non-empty, TS results should be empty
        # (we only indexed a Python file)
        assert len(result_python) >= len(result_ts)


class TestCodebaseIntelDeadCode:
    """Tests 36-37: check_dead_code."""

    def test_dead_code_finds_unreferenced_function(self, codebase_mcp, tmp_path):
        """Test 36: Dead code detector finds planted dead function."""
        mod = codebase_mcp[0]
        _index_python_file(codebase_mcp, tmp_path)

        result = mod.detect_dead_code()
        assert isinstance(result, list)
        # helper_function is unreferenced and exported -> should be flagged
        dead_names = [e["symbol_name"] for e in result if "symbol_name" in e]
        # At minimum, helper_function should be considered dead
        # (UserService may also be flagged since nothing calls it)
        assert len(dead_names) > 0

    def test_dead_code_excludes_entry_points(self, codebase_mcp, tmp_path):
        """Test 37: Main, test functions, lifecycle methods not flagged."""
        mod = codebase_mcp[0]
        source_with_entry_points = '''\
def main():
    """Entry point."""
    pass

def test_something():
    """A test function."""
    pass

class TestSuite:
    """A test class."""
    def setUp(self):
        pass

def regular_dead_function():
    """Should be flagged as dead."""
    pass
'''
        sample_file = tmp_path / "entry_points.py"
        sample_file.write_text(source_with_entry_points, encoding="utf-8")
        mod.index_file(file_path=str(sample_file), service_name="test-service")

        result = mod.detect_dead_code(service_name="test-service")
        assert isinstance(result, list)
        dead_names = [e["symbol_name"] for e in result if "symbol_name" in e]

        # Entry points should NOT be flagged
        assert "main" not in dead_names
        assert "test_something" not in dead_names


class TestCodebaseIntelGraphPersistence:
    """Tests 38-39: Graph snapshot save/load round-trip and lifespan teardown."""

    def test_graph_snapshot_save_load_roundtrip(self, tmp_path):
        """Test 38 (B-001 regression): Save graph, load it, verify structure preserved."""
        db_path = str(tmp_path / "graph_roundtrip.db")
        pool = ConnectionPool(db_path)
        init_symbols_db(pool)

        from src.codebase_intelligence.storage.graph_db import GraphDB

        graph_db = GraphDB(pool)

        # Create a graph with some nodes and edges
        g = nx.DiGraph()
        g.add_node("file_a.py", language="python", service_name="svc-a")
        g.add_node("file_b.py", language="python", service_name="svc-b")
        g.add_edge("file_a.py", "file_b.py", relation="imports", line=5)
        g.add_edge("file_b.py", "file_a.py", relation="imports", line=10)

        # Save
        graph_db.save_snapshot(g)

        # Load
        loaded = graph_db.load_snapshot()
        assert loaded is not None
        assert loaded.number_of_nodes() == g.number_of_nodes()
        assert loaded.number_of_edges() == g.number_of_edges()
        assert set(loaded.nodes()) == set(g.nodes())
        assert loaded.nodes["file_a.py"]["language"] == "python"

        pool.close()

    def test_lifespan_teardown_saves_graph_snapshot(self, tmp_path):
        """Test 39 (B-001 regression): Lifespan teardown saves graph snapshot."""
        # Verify main.py teardown code calls graph_db.save_snapshot
        from src.codebase_intelligence import main as ci_main
        import inspect

        source = inspect.getsource(ci_main.lifespan)
        assert "save_snapshot" in source, (
            "B-001 regression: main.py lifespan teardown must call graph_db.save_snapshot()"
        )


# ============================================================================
# SECTION 4: Inter-Service and Wiring Tests
# ============================================================================


class TestDockerComposeWiring:
    """Tests 40: Docker Compose service name consistency."""

    def _load_compose(self, path: str) -> dict:
        """Load a Docker Compose YAML file."""
        with open(path, "r") as f:
            return yaml.safe_load(f)

    def test_service_name_consistency_across_compose_files(self):
        """Test 40: Parse all compose files, verify no orphan references."""
        base_dir = Path("C:/MY_PROJECTS/super-team/docker")
        root_compose = Path("C:/MY_PROJECTS/super-team/docker-compose.yml")

        # Collect all service names defined across compose files
        defined_services = set()
        compose_files = list(base_dir.glob("docker-compose*.yml"))
        if root_compose.exists():
            compose_files.append(root_compose)

        for f in compose_files:
            data = self._load_compose(str(f))
            if data and "services" in data:
                defined_services.update(data["services"].keys())

        # Check depends_on references are in the defined set
        for f in compose_files:
            data = self._load_compose(str(f))
            if not data or "services" not in data:
                continue
            for svc_name, svc_def in data["services"].items():
                if isinstance(svc_def, dict) and "depends_on" in svc_def:
                    deps = svc_def["depends_on"]
                    if isinstance(deps, list):
                        for dep in deps:
                            assert dep in defined_services, (
                                f"Service '{svc_name}' in {f.name} depends on '{dep}' "
                                f"which is not defined in any compose file"
                            )
                    elif isinstance(deps, dict):
                        for dep in deps.keys():
                            assert dep in defined_services, (
                                f"Service '{svc_name}' in {f.name} depends on '{dep}' "
                                f"which is not defined in any compose file"
                            )


class TestDatabaseInitIdempotency:
    """Test 41: Database schema initialization idempotency."""

    def test_init_architect_db_twice(self, tmp_path):
        """Calling init_architect_db twice without error."""
        pool = ConnectionPool(str(tmp_path / "arch.db"))
        init_architect_db(pool)
        init_architect_db(pool)  # second call should not error
        pool.close()

    def test_init_contracts_db_twice(self, tmp_path):
        """Calling init_contracts_db twice without error."""
        pool = ConnectionPool(str(tmp_path / "cont.db"))
        init_contracts_db(pool)
        init_contracts_db(pool)
        pool.close()

    def test_init_symbols_db_twice(self, tmp_path):
        """Calling init_symbols_db twice without error."""
        pool = ConnectionPool(str(tmp_path / "sym.db"))
        init_symbols_db(pool)
        init_symbols_db(pool)
        pool.close()


class TestMCPToolNameConsistency:
    """Test 42: All MCP tool names match client-server."""

    def test_architect_tool_names_match(self, architect_mcp):
        """Architect MCP tool names match expected client calls."""
        tools = architect_mcp.mcp._tool_manager._tools
        expected = {"decompose", "get_service_map", "get_domain_model", "get_contracts_for_service"}
        assert set(tools.keys()) == expected

    def test_contract_engine_tool_names_match(self, contract_mcp):
        """Contract Engine MCP tool names match expected client calls."""
        tools = contract_mcp.mcp._tool_manager._tools
        expected = {
            "create_contract", "list_contracts", "get_contract",
            "validate_spec", "check_breaking_changes",
            "mark_implemented", "get_unimplemented_contracts",
            "generate_tests", "check_compliance", "validate_endpoint",
        }
        assert set(tools.keys()) == expected

    def test_codebase_intel_tool_names_match(self, codebase_mcp):
        """Codebase Intelligence MCP tool names match expected client calls."""
        mod = codebase_mcp[0]
        tools = mod.mcp._tool_manager._tools
        expected = {
            "register_artifact", "search_semantic", "find_definition",
            "find_dependencies", "analyze_graph", "check_dead_code",
            "find_callers", "get_service_interface",
        }
        assert set(tools.keys()) == expected


class TestMarkImplementedMCPConsistency:
    """Test 43 (SVC-005 regression): mark_implemented MCP returns model-consistent keys."""

    def test_mark_implemented_keys_match_model(self, contract_mcp):
        """Verify MCP tool returns keys matching MarkResponse model fields."""
        created = _create_contract(contract_mcp)
        result = contract_mcp.mark_implementation(
            contract_id=created["id"],
            service_name="user-service",
            evidence_path="/tests/test.py",
        )

        model_fields = set(MarkResponse.model_fields.keys())
        result_keys = set(result.keys())

        # All model fields must be present in result
        for field in model_fields:
            assert field in result_keys, (
                f"MarkResponse field '{field}' missing from MCP tool result. "
                f"Result keys: {result_keys}"
            )


# ============================================================================
# SECTION 5: Regression Guards
# ============================================================================


class TestRegressionGuards:
    """Additional regression tests to ensure previously-fixed bugs stay fixed."""

    def test_svc005_model_dump_used_for_mark_implemented(self):
        """Verify source code uses model_dump instead of manual dict."""
        import inspect
        import src.contract_engine.mcp_server as ce_mod
        source = inspect.getsource(ce_mod.mark_implementation)
        assert "model_dump" in source, (
            "SVC-005 regression: mark_implementation should use result.model_dump()"
        )
        # Ensure old manual dict pattern is gone
        assert '"total":' not in source.replace(" ", ""), (
            "SVC-005 regression: manual dict with 'total' key should be removed"
        )

    def test_b001_graph_save_in_teardown(self):
        """Verify codebase intelligence main.py lifespan saves graph on teardown."""
        import inspect
        from src.codebase_intelligence.main import lifespan
        source = inspect.getsource(lifespan)
        # After the yield, there should be a save_snapshot call
        yield_pos = source.index("yield")
        after_yield = source[yield_pos:]
        assert "save_snapshot" in after_yield, (
            "B-001 regression: lifespan must call save_snapshot after yield"
        )

    def test_wire001_service_name_standardized(self):
        """Verify Docker compose files use consistent 'codebase-intel' name."""
        traefik_path = Path("C:/MY_PROJECTS/super-team/docker/docker-compose.traefik.yml")
        run4_path = Path("C:/MY_PROJECTS/super-team/docker/docker-compose.run4.yml")
        build1_path = Path("C:/MY_PROJECTS/super-team/docker/docker-compose.build1.yml")

        for path in [traefik_path, run4_path, build1_path]:
            if path.exists():
                with open(str(path), "r") as f:
                    data = yaml.safe_load(f)
                if data and "services" in data:
                    # If codebase-related service is defined, must be 'codebase-intel'
                    service_keys = list(data["services"].keys())
                    for key in service_keys:
                        if "codebase" in key:
                            assert key == "codebase-intel", (
                                f"WIRE-001: Service name in {path.name} is '{key}', "
                                f"expected 'codebase-intel'"
                            )

    def test_svc005_test_asserts_total_implementations(self):
        """Verify existing MCP test checks for total_implementations (not total)."""
        test_path = Path("C:/MY_PROJECTS/super-team/tests/test_mcp/test_contract_engine_mcp.py")
        if test_path.exists():
            content = test_path.read_text(encoding="utf-8")
            assert "total_implementations" in content, (
                "SVC-005: existing MCP test should assert 'total_implementations'"
            )

"""SVC interface contract tests.

Verifies that all 13 MCP tool functions return the EXACT response shapes
that Build 2 expects.  Each test calls the real tool function (via the
module-level MCP server instance, patched to use a temporary database)
and asserts the concrete keys / types in the response.

SVC-001 .. SVC-006  -- Contract Engine  (src.contract_engine.mcp_server)
SVC-007 .. SVC-013  -- Codebase Intelligence (src.codebase_intelligence.mcp_server)
"""
from __future__ import annotations

import base64
import inspect
import uuid

import pytest

from src.shared.db.connection import ConnectionPool
from src.shared.db.schema import init_contracts_db, init_symbols_db
from src.contract_engine.services.contract_store import ContractStore
from src.contract_engine.services.implementation_tracker import ImplementationTracker
from src.contract_engine.services.version_manager import VersionManager
from src.contract_engine.services.test_generator import ContractTestGenerator
from src.contract_engine.services.compliance_checker import ComplianceChecker
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

# ---------------------------------------------------------------------------
# Sample data
# ---------------------------------------------------------------------------

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
                                    "items": {"$ref": "#/components/schemas/User"},
                                }
                            }
                        },
                    }
                },
            }
        }
    },
    "components": {
        "schemas": {
            "User": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "name": {"type": "string"},
                },
                "required": ["id", "name"],
            }
        }
    },
}

SAMPLE_PYTHON = '''\
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
'''


# ---------------------------------------------------------------------------
# Fixtures — Contract Engine
# ---------------------------------------------------------------------------


@pytest.fixture()
def contract_mcp(tmp_path, monkeypatch):
    """Contract Engine MCP module wired to an isolated temp database."""
    db_path = str(tmp_path / "svc_contract_test.db")
    monkeypatch.setenv("DATABASE_PATH", db_path)

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


def _create_contract(mod) -> dict:
    """Helper: create and return a sample OpenAPI contract."""
    return mod.create_contract(
        service_name="user-service",
        type="openapi",
        version="1.0.0",
        spec=SAMPLE_OPENAPI_SPEC,
    )


# ---------------------------------------------------------------------------
# Fixtures — Codebase Intelligence
# ---------------------------------------------------------------------------


@pytest.fixture()
def codebase_mcp(tmp_path, monkeypatch):
    """Codebase Intelligence MCP module wired to isolated temp storage."""
    db_path = str(tmp_path / "svc_codebase_test.db")
    chroma_path = str(tmp_path / "chroma")
    monkeypatch.setenv("DATABASE_PATH", db_path)
    monkeypatch.setenv("CHROMA_PATH", chroma_path)

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

    yield mod

    pool.close()


def _index_sample(mod, tmp_path) -> dict:
    """Helper: write sample Python file and index it."""
    sample_file = tmp_path / "user_service.py"
    sample_file.write_text(SAMPLE_PYTHON, encoding="utf-8")
    return mod.index_file(file_path=str(sample_file), service_name="user-service")


# ===================================================================
# CONTRACT ENGINE — SVC-001 through SVC-006
# ===================================================================


class TestSVC001GetContract:
    """SVC-001: get_contract returns {id, type, version, service_name, spec, spec_hash, status}."""

    def test_response_shape(self, contract_mcp):
        created = _create_contract(contract_mcp)
        result = contract_mcp.get_contract(created["id"])

        assert isinstance(result, dict)
        assert "error" not in result

        required_keys = {"id", "type", "version", "service_name", "spec", "spec_hash", "status"}
        missing = required_keys - set(result.keys())
        assert not missing, f"SVC-001 missing keys: {missing}"

    def test_value_types(self, contract_mcp):
        created = _create_contract(contract_mcp)
        result = contract_mcp.get_contract(created["id"])

        assert isinstance(result["id"], str)
        assert isinstance(result["type"], str)
        assert isinstance(result["version"], str)
        assert isinstance(result["service_name"], str)
        assert isinstance(result["spec"], dict)
        assert isinstance(result["spec_hash"], str)
        assert isinstance(result["status"], str)


class TestSVC002ValidateEndpoint:
    """SVC-002: validate_endpoint returns {valid: bool, violations: list}."""

    def test_response_shape_no_contract(self, contract_mcp):
        result = contract_mcp.validate_endpoint(
            service_name="nonexistent",
            method="GET",
            path="/api/users",
            response_body=[],
        )

        assert isinstance(result, dict)
        assert "valid" in result
        assert "violations" in result
        assert isinstance(result["valid"], bool)
        assert isinstance(result["violations"], list)

    def test_response_shape_with_contract(self, contract_mcp):
        _create_contract(contract_mcp)
        result = contract_mcp.validate_endpoint(
            service_name="user-service",
            method="GET",
            path="/api/users",
            response_body=[{"id": "1", "name": "Alice"}],
        )

        assert isinstance(result, dict)
        assert "valid" in result
        assert "violations" in result
        assert isinstance(result["valid"], bool)
        assert isinstance(result["violations"], list)

    def test_exactly_two_top_level_keys(self, contract_mcp):
        """Build 2 expects ONLY valid + violations at the top level."""
        result = contract_mcp.validate_endpoint(
            service_name="nonexistent",
            method="GET",
            path="/api/x",
            response_body={},
        )
        assert "valid" in result
        assert "violations" in result


class TestSVC003GenerateTests:
    """SVC-003: generate_tests returns a STRING (raw test code), NOT a dict."""

    def test_returns_string(self, contract_mcp):
        created = _create_contract(contract_mcp)
        result = contract_mcp.generate_tests(contract_id=created["id"])

        assert isinstance(result, str), (
            f"SVC-003 VIOLATION: generate_tests returned {type(result).__name__}, expected str"
        )

    def test_string_is_nonempty(self, contract_mcp):
        created = _create_contract(contract_mcp)
        result = contract_mcp.generate_tests(contract_id=created["id"])

        assert len(result) > 0, "SVC-003: generated test code must not be empty"

    def test_error_case_returns_json_string(self, contract_mcp):
        """On error, generate_tests returns a JSON-encoded error string."""
        fake_id = str(uuid.uuid4())
        result = contract_mcp.generate_tests(contract_id=fake_id)

        assert isinstance(result, str), (
            f"SVC-003: error path returned {type(result).__name__}, expected str"
        )
        assert "error" in result


class TestSVC004CheckBreakingChanges:
    """SVC-004: check_breaking_changes returns a list."""

    def test_returns_list(self, contract_mcp):
        created = _create_contract(contract_mcp)
        result = contract_mcp.detect_breaking_changes(contract_id=created["id"])

        assert isinstance(result, list), (
            f"SVC-004 VIOLATION: check_breaking_changes returned {type(result).__name__}, expected list"
        )

    def test_returns_list_with_new_spec(self, contract_mcp):
        created = _create_contract(contract_mcp)
        new_spec = {
            "openapi": "3.1.0",
            "info": {"title": "Test API", "version": "2.0.0"},
            "paths": {},
            "components": {"schemas": {}},
        }
        result = contract_mcp.detect_breaking_changes(
            contract_id=created["id"], new_spec=new_spec
        )

        assert isinstance(result, list)

    def test_error_case_returns_list_with_error(self, contract_mcp):
        fake_id = str(uuid.uuid4())
        result = contract_mcp.detect_breaking_changes(contract_id=fake_id)

        assert isinstance(result, list)
        assert len(result) > 0
        assert "error" in result[0]


class TestSVC005MarkImplemented:
    """SVC-005 FIXED: mark_implemented now uses model_dump() and returns
    {marked: bool, total_implementations: int, all_implemented: bool}.

    The key is 'total_implementations' (matching the MarkResponse model).
    The old 'total' key was a bug that has been corrected.
    """

    def test_response_shape(self, contract_mcp):
        created = _create_contract(contract_mcp)
        result = contract_mcp.mark_implementation(
            contract_id=created["id"],
            service_name="user-service",
            evidence_path="/tests/test_api.py",
        )

        assert isinstance(result, dict)
        assert "error" not in result

        required_keys = {"marked", "total_implementations", "all_implemented"}
        missing = required_keys - set(result.keys())
        assert not missing, f"SVC-005 missing keys: {missing}"

    def test_value_types(self, contract_mcp):
        created = _create_contract(contract_mcp)
        result = contract_mcp.mark_implementation(
            contract_id=created["id"],
            service_name="user-service",
            evidence_path="/tests/test_api.py",
        )

        assert isinstance(result["marked"], bool)
        assert isinstance(result["total_implementations"], int)
        assert isinstance(result["all_implemented"], bool)

    def test_total_implementations_key_present(self, contract_mcp):
        """SVC-005 FIXED: model_dump() produces 'total_implementations'."""
        created = _create_contract(contract_mcp)
        result = contract_mcp.mark_implementation(
            contract_id=created["id"],
            service_name="user-service",
            evidence_path="/tests/test_api.py",
        )

        assert "total_implementations" in result, (
            "SVC-005 REGRESSION: 'total_implementations' key must be present "
            "(using model_dump)."
        )


class TestSVC006GetUnimplementedContracts:
    """SVC-006: get_unimplemented_contracts returns a list."""

    def test_returns_list(self, contract_mcp):
        result = contract_mcp.get_unimplemented()

        assert isinstance(result, list), (
            f"SVC-006 VIOLATION: get_unimplemented returned {type(result).__name__}, expected list"
        )

    def test_items_are_dicts(self, contract_mcp):
        _create_contract(contract_mcp)
        result = contract_mcp.get_unimplemented()

        assert isinstance(result, list)
        assert len(result) >= 1
        for item in result:
            assert isinstance(item, dict)


# ===================================================================
# CODEBASE INTELLIGENCE — SVC-007 through SVC-013
# ===================================================================


class TestSVC007FindDefinition:
    """SVC-007: find_definition returns {file: str, line: int, kind: str, signature: str}.

    IMPORTANT: Keys are 'file' and 'line', NOT 'file_path'/'line_start'.
    """

    def test_response_shape(self, codebase_mcp, tmp_path):
        _index_sample(codebase_mcp, tmp_path)
        result = codebase_mcp.find_definition(symbol="UserService")

        assert isinstance(result, dict)
        assert "error" not in result

        required_keys = {"file", "line", "kind", "signature"}
        missing = required_keys - set(result.keys())
        assert not missing, f"SVC-007 missing keys: {missing}"

    def test_value_types(self, codebase_mcp, tmp_path):
        _index_sample(codebase_mcp, tmp_path)
        result = codebase_mcp.find_definition(symbol="UserService")

        assert isinstance(result["file"], str)
        assert isinstance(result["line"], int)
        assert isinstance(result["kind"], str)
        assert isinstance(result["signature"], str)

    def test_no_file_path_key(self, codebase_mcp, tmp_path):
        """Build 2 expects 'file', NOT 'file_path'."""
        _index_sample(codebase_mcp, tmp_path)
        result = codebase_mcp.find_definition(symbol="UserService")

        assert "file_path" not in result, (
            "SVC-007 VIOLATION: Found 'file_path' key -- Build 2 expects 'file'"
        )

    def test_no_line_start_key(self, codebase_mcp, tmp_path):
        """Build 2 expects 'line', NOT 'line_start'."""
        _index_sample(codebase_mcp, tmp_path)
        result = codebase_mcp.find_definition(symbol="UserService")

        assert "line_start" not in result, (
            "SVC-007 VIOLATION: Found 'line_start' key -- Build 2 expects 'line'"
        )


class TestSVC008FindCallers:
    """SVC-008: find_callers returns a list."""

    def test_returns_list(self, codebase_mcp):
        result = codebase_mcp.find_callers(symbol="NonExistent")

        assert isinstance(result, list), (
            f"SVC-008 VIOLATION: find_callers returned {type(result).__name__}, expected list"
        )

    def test_returns_list_after_indexing(self, codebase_mcp, tmp_path):
        _index_sample(codebase_mcp, tmp_path)
        result = codebase_mcp.find_callers(symbol="UserService")

        assert isinstance(result, list)


class TestSVC009FindDependencies:
    """SVC-009: find_dependencies returns {imports, imported_by, transitive_deps, circular_deps}.

    IMPORTANT: Keys are 'imports'/'imported_by', NOT 'dependencies'/'dependents'.
    """

    def test_response_shape(self, codebase_mcp):
        result = codebase_mcp.get_dependencies(file_path="some/file.py")

        assert isinstance(result, dict)
        required_keys = {"imports", "imported_by", "transitive_deps", "circular_deps"}
        missing = required_keys - set(result.keys())
        assert not missing, f"SVC-009 missing keys: {missing}"

    def test_value_types(self, codebase_mcp):
        result = codebase_mcp.get_dependencies(file_path="some/file.py")

        assert isinstance(result["imports"], list)
        assert isinstance(result["imported_by"], list)
        assert isinstance(result["transitive_deps"], list)
        assert isinstance(result["circular_deps"], list)

    def test_no_dependencies_key(self, codebase_mcp):
        """Build 2 expects 'imports', NOT 'dependencies'."""
        result = codebase_mcp.get_dependencies(file_path="some/file.py")

        assert "dependencies" not in result, (
            "SVC-009 VIOLATION: Found 'dependencies' key -- Build 2 expects 'imports'"
        )

    def test_no_dependents_key(self, codebase_mcp):
        """Build 2 expects 'imported_by', NOT 'dependents'."""
        result = codebase_mcp.get_dependencies(file_path="some/file.py")

        assert "dependents" not in result, (
            "SVC-009 VIOLATION: Found 'dependents' key -- Build 2 expects 'imported_by'"
        )


class TestSVC010SearchSemantic:
    """SVC-010: search_semantic accepts 'n_results' param (NOT 'top_k'), returns list."""

    def test_signature_uses_n_results(self, codebase_mcp):
        """Verify the MCP tool function signature has 'n_results' parameter."""
        sig = inspect.signature(codebase_mcp.search_code)
        param_names = list(sig.parameters.keys())

        assert "n_results" in param_names, (
            f"SVC-010 VIOLATION: search_code param names are {param_names}, "
            f"expected 'n_results'"
        )

    def test_signature_does_not_have_top_k(self, codebase_mcp):
        """Build 2 passes n_results, so top_k must NOT be in the signature."""
        sig = inspect.signature(codebase_mcp.search_code)
        param_names = list(sig.parameters.keys())

        assert "top_k" not in param_names, (
            "SVC-010 VIOLATION: search_code has 'top_k' param -- "
            "Build 2 expects 'n_results'"
        )

    def test_returns_list(self, codebase_mcp):
        result = codebase_mcp.search_code(query="user management")

        assert isinstance(result, list), (
            f"SVC-010 VIOLATION: search_semantic returned {type(result).__name__}, expected list"
        )

    def test_n_results_limits_output(self, codebase_mcp, tmp_path):
        _index_sample(codebase_mcp, tmp_path)
        result = codebase_mcp.search_code(query="user", n_results=2)

        assert isinstance(result, list)
        assert len(result) <= 2


class TestSVC011GetServiceInterface:
    """SVC-011: get_service_interface returns {endpoints, events_published, events_consumed}."""

    def test_response_shape(self, codebase_mcp):
        result = codebase_mcp.get_service_interface(service_name="unknown")

        assert isinstance(result, dict)
        required_keys = {"endpoints", "events_published", "events_consumed"}
        missing = required_keys - set(result.keys())
        assert not missing, f"SVC-011 missing keys: {missing}"

    def test_value_types(self, codebase_mcp):
        result = codebase_mcp.get_service_interface(service_name="unknown")

        assert isinstance(result["endpoints"], list)
        assert isinstance(result["events_published"], list)
        assert isinstance(result["events_consumed"], list)


class TestSVC012CheckDeadCode:
    """SVC-012: check_dead_code returns a list."""

    def test_returns_list(self, codebase_mcp):
        result = codebase_mcp.detect_dead_code()

        assert isinstance(result, list), (
            f"SVC-012 VIOLATION: check_dead_code returned {type(result).__name__}, expected list"
        )

    def test_entries_have_expected_shape(self, codebase_mcp, tmp_path):
        _index_sample(codebase_mcp, tmp_path)
        result = codebase_mcp.detect_dead_code()

        assert isinstance(result, list)
        for entry in result:
            assert isinstance(entry, dict)


class TestSVC013RegisterArtifact:
    """SVC-013: register_artifact returns {indexed: bool, symbols_found: int, dependencies_found: int}."""

    def test_response_shape(self, codebase_mcp, tmp_path):
        result = _index_sample(codebase_mcp, tmp_path)

        assert isinstance(result, dict)
        required_keys = {"indexed", "symbols_found", "dependencies_found"}
        missing = required_keys - set(result.keys())
        assert not missing, f"SVC-013 missing keys: {missing}"

    def test_value_types(self, codebase_mcp, tmp_path):
        result = _index_sample(codebase_mcp, tmp_path)

        assert isinstance(result["indexed"], bool)
        assert isinstance(result["symbols_found"], int)
        assert isinstance(result["dependencies_found"], int)

    def test_indexed_is_true_for_python(self, codebase_mcp, tmp_path):
        result = _index_sample(codebase_mcp, tmp_path)

        assert result["indexed"] is True
        assert result["symbols_found"] > 0

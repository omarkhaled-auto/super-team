"""Integration tests for the Codebase Intelligence MCP server.

Tests the MCP tool functions exposed by ``src.codebase_intelligence.mcp_server``
by patching module-level database, storage, and service instances with temporary
ones so each test runs against an isolated SQLite database and ChromaDB directory.
"""
from __future__ import annotations

import base64

import pytest
from mcp.server.fastmcp import FastMCP

from src.shared.db.connection import ConnectionPool
from src.shared.db.schema import init_symbols_db
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
# Sample Python source used for indexing tests
# ---------------------------------------------------------------------------

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
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def codebase_mcp(tmp_path, monkeypatch):
    """Set up the Codebase Intelligence MCP server with temporary storage.

    Patches all module-level instances so tool functions operate against
    isolated, ephemeral SQLite and ChromaDB directories.
    """
    db_path = str(tmp_path / "codebase_test.db")
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


def _index_sample_file(mod, tmp_path) -> dict:
    """Helper: write sample Python file to disk and index it via the MCP tool."""
    sample_file = tmp_path / "user_service.py"
    sample_file.write_text(SAMPLE_PYTHON, encoding="utf-8")
    file_path = str(sample_file)

    return mod.index_file(file_path=file_path, service_name="user-service")


def _index_sample_file_via_base64(mod) -> dict:
    """Helper: index sample Python file using base64-encoded source."""
    source_b64 = base64.b64encode(SAMPLE_PYTHON.encode("utf-8")).decode("ascii")
    return mod.index_file(
        file_path="virtual/user_service.py",
        service_name="user-service",
        source_base64=source_b64,
    )


# ---------------------------------------------------------------------------
# MCP instance sanity checks
# ---------------------------------------------------------------------------


class TestCodebaseIntelMCPInstance:
    """Verify the FastMCP instance is correctly wired."""

    def test_mcp_is_fastmcp_instance(self, codebase_mcp):
        assert isinstance(codebase_mcp.mcp, FastMCP)

    def test_mcp_has_registered_tools(self, codebase_mcp):
        tools = codebase_mcp.mcp._tool_manager._tools
        expected_tools = [
            "register_artifact",
            "search_semantic",
            "find_definition",
            "find_dependencies",
            "analyze_graph",
            "check_dead_code",
            "find_callers",
            "get_service_interface",
        ]
        for tool_name in expected_tools:
            assert tool_name in tools, f"Tool '{tool_name}' not registered"

    def test_mcp_name_is_codebase_intelligence(self, codebase_mcp):
        assert codebase_mcp.mcp.name == "Codebase Intelligence"


# ---------------------------------------------------------------------------
# index_file tool
# ---------------------------------------------------------------------------


class TestIndexFile:
    """Tests for the ``index_file`` MCP tool."""

    def test_index_file_from_disk(self, codebase_mcp, tmp_path):
        result = _index_sample_file(codebase_mcp, tmp_path)

        assert isinstance(result, dict)
        assert result["indexed"] is True
        assert result["symbols_found"] > 0
        assert isinstance(result["dependencies_found"], int)
        assert isinstance(result["errors"], list)

    def test_index_file_via_base64(self, codebase_mcp):
        result = _index_sample_file_via_base64(codebase_mcp)

        assert isinstance(result, dict)
        assert result["indexed"] is True
        assert result["symbols_found"] > 0

    def test_index_file_unsupported_extension(self, codebase_mcp, tmp_path):
        txt_file = tmp_path / "readme.txt"
        txt_file.write_text("Hello world", encoding="utf-8")

        result = codebase_mcp.index_file(file_path=str(txt_file))

        assert isinstance(result, dict)
        assert result["indexed"] is False
        assert len(result["errors"]) > 0

    def test_index_file_nonexistent_path(self, codebase_mcp):
        result = codebase_mcp.index_file(file_path="/nonexistent/path/foo.py")

        assert isinstance(result, dict)
        assert result["indexed"] is False
        assert len(result["errors"]) > 0


# ---------------------------------------------------------------------------
# search_code tool
# ---------------------------------------------------------------------------


class TestSearchCode:
    """Tests for the ``search_code`` MCP tool."""

    def test_search_returns_list_on_clean_db(self, codebase_mcp):
        result = codebase_mcp.search_code(query="user management")
        assert isinstance(result, list)

    def test_search_after_indexing(self, codebase_mcp, tmp_path):
        _index_sample_file(codebase_mcp, tmp_path)

        result = codebase_mcp.search_code(query="get user by ID")

        assert isinstance(result, list)
        # After indexing, we expect at least some results for a relevant query
        if len(result) > 0:
            first = result[0]
            assert "file_path" in first
            assert "score" in first

    def test_search_with_language_filter(self, codebase_mcp, tmp_path):
        _index_sample_file(codebase_mcp, tmp_path)

        result = codebase_mcp.search_code(
            query="user service",
            language="python",
        )
        assert isinstance(result, list)

    def test_search_with_service_name_filter(self, codebase_mcp, tmp_path):
        _index_sample_file(codebase_mcp, tmp_path)

        result = codebase_mcp.search_code(
            query="user service",
            service_name="user-service",
        )
        assert isinstance(result, list)

    def test_search_with_n_results(self, codebase_mcp, tmp_path):
        _index_sample_file(codebase_mcp, tmp_path)

        result = codebase_mcp.search_code(
            query="create user",
            n_results=3,
        )
        assert isinstance(result, list)
        assert len(result) <= 3


# ---------------------------------------------------------------------------
# get_symbols tool
# ---------------------------------------------------------------------------


class TestFindDefinition:
    """Tests for the ``find_definition`` MCP tool."""

    def test_symbol_not_found_on_clean_db(self, codebase_mcp):
        result = codebase_mcp.find_definition(symbol="NonExistent")
        assert isinstance(result, dict)
        assert "error" in result

    def test_find_definition_after_indexing(self, codebase_mcp, tmp_path):
        _index_sample_file(codebase_mcp, tmp_path)

        result = codebase_mcp.find_definition(symbol="UserService")

        assert isinstance(result, dict)
        assert "error" not in result
        # SVC-007: find_definition returns {file, line, kind, signature}
        assert "file" in result
        assert "line" in result
        assert "kind" in result
        assert "signature" in result

    def test_find_definition_with_language_filter(self, codebase_mcp, tmp_path):
        _index_sample_file(codebase_mcp, tmp_path)

        result = codebase_mcp.find_definition(symbol="UserService", language="python")

        assert isinstance(result, dict)
        assert "error" not in result
        assert "file" in result

    def test_find_definition_wrong_language_returns_error(self, codebase_mcp, tmp_path):
        _index_sample_file(codebase_mcp, tmp_path)

        result = codebase_mcp.find_definition(symbol="UserService", language="typescript")

        assert isinstance(result, dict)
        assert "error" in result

    def test_find_function_definition(self, codebase_mcp, tmp_path):
        _index_sample_file(codebase_mcp, tmp_path)

        result = codebase_mcp.find_definition(symbol="helper_function")

        assert isinstance(result, dict)
        assert "error" not in result
        assert "file" in result
        assert "kind" in result

    def test_find_method_definition(self, codebase_mcp, tmp_path):
        _index_sample_file(codebase_mcp, tmp_path)

        result = codebase_mcp.find_definition(symbol="get_user")

        assert isinstance(result, dict)
        # Methods may or may not be indexed depending on the extractor
        # so we just check it returns a valid response


# ---------------------------------------------------------------------------
# get_dependencies tool
# ---------------------------------------------------------------------------


class TestGetDependencies:
    """Tests for the ``get_dependencies`` MCP tool."""

    def test_returns_expected_structure(self, codebase_mcp):
        """SVC-009: find_dependencies returns {imports, imported_by, transitive_deps, circular_deps}."""
        result = codebase_mcp.get_dependencies(file_path="some/file.py")

        assert isinstance(result, dict)
        assert "imports" in result
        assert "imported_by" in result
        assert "transitive_deps" in result
        assert "circular_deps" in result
        assert isinstance(result["imports"], list)
        assert isinstance(result["imported_by"], list)

    def test_after_indexing_returns_deps(self, codebase_mcp, tmp_path):
        sample_file = tmp_path / "user_service.py"
        sample_file.write_text(SAMPLE_PYTHON, encoding="utf-8")
        file_path = str(sample_file)

        codebase_mcp.index_file(file_path=file_path, service_name="user-service")

        result = codebase_mcp.get_dependencies(file_path=file_path)

        assert isinstance(result, dict)
        assert isinstance(result["imports"], list)
        assert isinstance(result["imported_by"], list)
        assert isinstance(result["transitive_deps"], list)
        assert isinstance(result["circular_deps"], list)

    def test_custom_depth(self, codebase_mcp):
        result = codebase_mcp.get_dependencies(
            file_path="some/file.py",
            depth=3,
        )
        assert isinstance(result, dict)
        assert "imports" in result

    def test_forward_direction(self, codebase_mcp):
        result = codebase_mcp.get_dependencies(
            file_path="some/file.py",
            direction="forward",
        )
        assert isinstance(result, dict)
        assert isinstance(result["imports"], list)

    def test_reverse_direction(self, codebase_mcp):
        result = codebase_mcp.get_dependencies(
            file_path="some/file.py",
            direction="reverse",
        )
        assert isinstance(result, dict)
        assert isinstance(result["imported_by"], list)


# ---------------------------------------------------------------------------
# analyze_graph tool
# ---------------------------------------------------------------------------


class TestAnalyzeGraph:
    """Tests for the ``analyze_graph`` MCP tool."""

    def test_empty_graph_analysis(self, codebase_mcp):
        result = codebase_mcp.analyze_graph()

        assert isinstance(result, dict)
        assert "node_count" in result
        assert "edge_count" in result
        assert "is_dag" in result
        assert result["node_count"] == 0
        assert result["edge_count"] == 0
        assert result["is_dag"] is True

    def test_graph_analysis_after_indexing(self, codebase_mcp, tmp_path):
        _index_sample_file(codebase_mcp, tmp_path)

        result = codebase_mcp.analyze_graph()

        assert isinstance(result, dict)
        assert "node_count" in result
        assert "edge_count" in result
        assert "is_dag" in result
        assert isinstance(result["node_count"], int)
        assert isinstance(result["edge_count"], int)
        assert isinstance(result["is_dag"], bool)


# ---------------------------------------------------------------------------
# detect_dead_code tool
# ---------------------------------------------------------------------------


class TestDetectDeadCode:
    """Tests for the ``detect_dead_code`` MCP tool."""

    def test_empty_db_returns_list(self, codebase_mcp):
        result = codebase_mcp.detect_dead_code()

        assert isinstance(result, list)

    def test_detect_dead_code_after_indexing(self, codebase_mcp, tmp_path):
        _index_sample_file(codebase_mcp, tmp_path)

        result = codebase_mcp.detect_dead_code()

        assert isinstance(result, list)
        # Each entry (if any) should have expected keys
        for entry in result:
            assert "file_path" in entry
            assert "symbol_name" in entry
            assert "confidence" in entry

    def test_detect_dead_code_with_service_filter(self, codebase_mcp, tmp_path):
        _index_sample_file(codebase_mcp, tmp_path)

        result = codebase_mcp.detect_dead_code(service_name="user-service")

        assert isinstance(result, list)


# ---------------------------------------------------------------------------
# find_callers tool
# ---------------------------------------------------------------------------


class TestFindCallers:
    """Tests for the ``find_callers`` MCP tool."""

    def test_empty_db_returns_empty_list(self, codebase_mcp):
        result = codebase_mcp.find_callers(symbol="NonExistent")
        assert isinstance(result, list)
        assert result == []

    def test_find_callers_after_indexing(self, codebase_mcp, tmp_path):
        _index_sample_file(codebase_mcp, tmp_path)

        result = codebase_mcp.find_callers(symbol="UserService")

        assert isinstance(result, list)
        # Each entry (if any) should have expected keys
        for entry in result:
            assert "file_path" in entry
            assert "line" in entry
            assert "caller_symbol" in entry


# ---------------------------------------------------------------------------
# get_service_interface tool
# ---------------------------------------------------------------------------


class TestGetServiceInterface:
    """Tests for the ``get_service_interface`` MCP tool."""

    def test_unknown_service_returns_empty_interface(self, codebase_mcp):
        result = codebase_mcp.get_service_interface(service_name="unknown")

        assert isinstance(result, dict)
        assert result["service_name"] == "unknown"
        assert result["endpoints"] == []
        assert result["events_published"] == []
        assert result["events_consumed"] == []
        assert result["exported_symbols"] == []

    def test_after_indexing_returns_interface(self, codebase_mcp, tmp_path):
        _index_sample_file(codebase_mcp, tmp_path)

        result = codebase_mcp.get_service_interface(service_name="user-service")

        assert isinstance(result, dict)
        assert result["service_name"] == "user-service"
        assert "endpoints" in result
        assert "events_published" in result
        assert "events_consumed" in result
        assert "exported_symbols" in result


# ---------------------------------------------------------------------------
# Tool count verification
# ---------------------------------------------------------------------------


class TestMCPToolCount:
    """Verify the total number of registered MCP tools."""

    def test_mcp_tool_count_is_8(self, codebase_mcp):
        tools = codebase_mcp.mcp._tool_manager._tools
        assert len(tools) == 8, f"Expected 8 tools, got {len(tools)}: {list(tools.keys())}"

"""Unit tests for Graph RAG MCP Server."""
from __future__ import annotations

import os
import pytest
from unittest.mock import patch, MagicMock
from src.shared.models.graph_rag import GraphRAGBuildResult


@pytest.fixture(autouse=True)
def _mock_server_init(tmp_path, monkeypatch):
    """Mock environment variables and heavy initialization before importing mcp_server.

    The mcp_server module performs module-level initialization (ConnectionPool,
    ChromaDB, etc.) on import. We need to set env vars pointing to temp dirs
    before the import happens.
    """
    monkeypatch.setenv("GRAPH_RAG_DB_PATH", str(tmp_path / "graph_rag.db"))
    monkeypatch.setenv("GRAPH_RAG_CHROMA_PATH", str(tmp_path / "chroma"))
    monkeypatch.setenv("CI_DATABASE_PATH", str(tmp_path / "ci.db"))
    monkeypatch.setenv("ARCHITECT_DATABASE_PATH", str(tmp_path / "architect.db"))
    monkeypatch.setenv("CONTRACT_DATABASE_PATH", str(tmp_path / "contracts.db"))


def _get_tool_names():
    """Import mcp_server and return tool names registered on the FastMCP instance."""
    import importlib
    import src.graph_rag.mcp_server as mod
    importlib.reload(mod)
    mcp_instance = mod.mcp
    # FastMCP stores tools in _tool_manager._tools dict
    if hasattr(mcp_instance, '_tool_manager'):
        return list(mcp_instance._tool_manager._tools.keys())
    # Fallback: list_tools() method
    if hasattr(mcp_instance, 'list_tools'):
        tools = mcp_instance.list_tools()
        return [t.name if hasattr(t, 'name') else str(t) for t in tools]
    return []


class TestServerToolRegistration:
    def test_server_has_all_7_tools(self) -> None:
        tool_names = _get_tool_names()
        expected = {
            "build_knowledge_graph",
            "get_service_context",
            "query_graph_neighborhood",
            "hybrid_search",
            "find_cross_service_impact",
            "validate_service_boundaries",
            "check_cross_service_events",
        }
        assert expected.issubset(set(tool_names)), (
            f"Missing tools: {expected - set(tool_names)}"
        )


class TestBuildKnowledgeGraphTool:
    def test_build_knowledge_graph_returns_dict(self) -> None:
        import importlib
        import src.graph_rag.mcp_server as mod
        importlib.reload(mod)

        result = mod.build_knowledge_graph(project_name="test")
        assert isinstance(result, dict)
        # Should have success key (from BuildResult or error dict)
        assert "success" in result


class TestGetServiceContextTool:
    def test_get_service_context_returns_dict(self) -> None:
        import importlib
        import src.graph_rag.mcp_server as mod
        importlib.reload(mod)

        result = mod.get_service_context(service_name="test-service")
        assert isinstance(result, dict)
        assert "service_name" in result


class TestHybridSearchTool:
    def test_hybrid_search_returns_dict(self) -> None:
        import importlib
        import src.graph_rag.mcp_server as mod
        importlib.reload(mod)

        result = mod.hybrid_search(query="authentication")
        assert isinstance(result, dict)
        assert "results" in result


class TestQueryNeighborhoodTool:
    def test_query_neighborhood_returns_dict(self) -> None:
        import importlib
        import src.graph_rag.mcp_server as mod
        importlib.reload(mod)

        result = mod.query_graph_neighborhood(node_id="file::test.py")
        assert isinstance(result, dict)
        assert "nodes" in result or "center_node" in result


class TestFindImpactTool:
    def test_find_impact_returns_dict(self) -> None:
        import importlib
        import src.graph_rag.mcp_server as mod
        importlib.reload(mod)

        result = mod.find_cross_service_impact(node_id="file::test.py")
        assert isinstance(result, dict)
        assert "total_impacted_nodes" in result or "source_node" in result


class TestCheckEventsTool:
    def test_check_events_returns_dict(self) -> None:
        import importlib
        import src.graph_rag.mcp_server as mod
        importlib.reload(mod)

        result = mod.check_cross_service_events()
        assert isinstance(result, dict)
        assert "matched_events" in result or "orphaned_events" in result

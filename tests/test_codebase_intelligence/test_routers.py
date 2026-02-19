"""Integration tests for all FastAPI routers in the codebase-intelligence service.

Covers every endpoint with a mocked app.state so no real DB or ChromaDB is needed:
    1.  GET  /api/health                     -> 200 with status
    2.  GET  /api/symbols                    -> 200 with list
    3.  GET  /api/symbols?name=MyClass       -> 200 filtered results
    4.  GET  /api/dependencies?file_path=... -> 200 deps
    5.  GET  /api/graph/analysis             -> 200 graph analysis
    6.  POST /api/search  (valid query)      -> 200 results
    7.  POST /api/search  (with filters)     -> 200 filtered results
    8.  POST /api/artifacts                  -> 200 indexing result
    9.  GET  /api/dead-code                  -> 200 dead code entries
   10.  POST /api/search  (empty query)      -> 422 validation error
"""
from __future__ import annotations

import gc
import warnings
from collections.abc import Generator

import pytest
from unittest.mock import MagicMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.codebase_intelligence.routers.symbols import router as symbols_router
from src.codebase_intelligence.routers.dependencies import router as dependencies_router
from src.codebase_intelligence.routers.search import router as search_router
from src.codebase_intelligence.routers.artifacts import router as artifacts_router
from src.codebase_intelligence.routers.dead_code import router as dead_code_router
from src.codebase_intelligence.routers.health import router as health_router
from src.shared.models.codebase import (
    SymbolDefinition,
    SymbolKind,
    Language,
    SemanticSearchResult,
    DeadCodeEntry,
    GraphAnalysis,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def mock_app() -> FastAPI:
    """Create a FastAPI app with all routers and fully mocked app.state."""
    app = FastAPI()

    # ---- app.state mocks ------------------------------------------------
    app.state.symbol_db = MagicMock()
    app.state.graph_analyzer = MagicMock()
    app.state.semantic_searcher = MagicMock()
    app.state.incremental_indexer = MagicMock()
    app.state.dead_code_detector = MagicMock()
    app.state.chroma_store = MagicMock()
    app.state.pool = MagicMock()
    app.state.start_time = 1_000_000.0

    # ---- Default return values ------------------------------------------

    # symbol_db: query helpers
    app.state.symbol_db.query_by_name.return_value = []
    app.state.symbol_db.query_by_file.return_value = []

    # symbol_db: raw SQL fallback used by list_symbols and find_dead_code
    mock_conn = MagicMock()
    mock_conn.execute.return_value.fetchall.return_value = []
    app.state.symbol_db._pool.get.return_value = mock_conn

    # graph_analyzer
    app.state.graph_analyzer.get_dependencies.return_value = ["dep1.py"]
    app.state.graph_analyzer.get_dependents.return_value = ["dependent1.py"]
    app.state.graph_analyzer.analyze.return_value = GraphAnalysis(
        node_count=5,
        edge_count=3,
        is_dag=True,
        circular_dependencies=[],
        top_files_by_pagerank=[],
        connected_components=1,
        build_order=["a.py", "b.py"],
    )

    # semantic_searcher
    app.state.semantic_searcher.search.return_value = [
        SemanticSearchResult(
            chunk_id="test.py::MyClass",
            file_path="test.py",
            symbol_name="MyClass",
            content="class MyClass: pass",
            score=0.95,
            language="python",
            line_start=1,
            line_end=1,
        )
    ]

    # incremental_indexer
    app.state.incremental_indexer.index_file.return_value = {
        "indexed": True,
        "symbols_found": 3,
        "dependencies_found": 1,
        "errors": [],
    }

    # dead_code_detector
    app.state.dead_code_detector.find_dead_code.return_value = [
        DeadCodeEntry(
            symbol_name="unused_func",
            file_path="test.py",
            kind=SymbolKind.FUNCTION,
            line=10,
            confidence="high",
        )
    ]

    # pool (used by health check: pool.get().execute("SELECT 1"))
    app.state.pool.get.return_value.execute.return_value = None

    # chroma_store (used by health check)
    app.state.chroma_store.get_stats.return_value = 42

    # ---- Include routers ------------------------------------------------
    app.include_router(health_router)
    app.include_router(symbols_router)
    app.include_router(dependencies_router)
    app.include_router(search_router)
    app.include_router(artifacts_router)
    app.include_router(dead_code_router)

    return app


@pytest.fixture()
def client(mock_app: FastAPI) -> Generator[TestClient, None, None]:
    """Return a synchronous test client bound to *mock_app*."""
    with TestClient(mock_app) as c:
        yield c
    # Force GC to collect any dangling sockets before the next test starts,
    # suppressing ResourceWarning that Windows raises for transient sockets.
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", ResourceWarning)
        gc.collect()


# ---------------------------------------------------------------------------
# 1. GET /api/health -> 200
# ---------------------------------------------------------------------------

class TestHealthEndpoint:
    """Tests for the health-check endpoint."""

    def test_health_returns_200_with_status(self, client: TestClient) -> None:
        resp = client.get("/api/health")

        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "healthy"
        assert body["service_name"] == "codebase-intelligence"
        assert body["database"] == "connected"
        assert "uptime_seconds" in body
        # ChromaDB details should also be present
        assert body["details"]["chroma"] == "connected"
        assert body["details"]["chroma_chunks"] == 42

    def test_health_degraded_when_db_fails(self, mock_app: FastAPI) -> None:
        """If pool.get().execute raises, status should be 'degraded'."""
        mock_app.state.pool.get.return_value.execute.side_effect = RuntimeError("db down")
        with TestClient(mock_app) as c:
            resp = c.get("/api/health")
        # Collect dangling sockets before they trigger ResourceWarning.
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", ResourceWarning)
            gc.collect()

        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "degraded"
        assert body["database"] == "disconnected"


# ---------------------------------------------------------------------------
# 2. GET /api/symbols -> 200 with list
# ---------------------------------------------------------------------------

class TestSymbolsEndpoint:
    """Tests for the symbols query endpoint."""

    def test_list_symbols_returns_200_with_empty_list(self, client: TestClient) -> None:
        """No filters -- fallback to raw SQL returns nothing."""
        resp = client.get("/api/symbols")

        assert resp.status_code == 200
        assert resp.json() == []

    # -------------------------------------------------------------------
    # 3. GET /api/symbols?name=MyClass -> filtered results
    # -------------------------------------------------------------------

    def test_list_symbols_filtered_by_name(
        self, mock_app: FastAPI, client: TestClient
    ) -> None:
        sample_symbol = SymbolDefinition(
            file_path="src/app.py",
            symbol_name="MyClass",
            kind=SymbolKind.CLASS,
            language=Language.PYTHON,
            line_start=1,
            line_end=10,
        )
        mock_app.state.symbol_db.query_by_name.return_value = [sample_symbol]

        resp = client.get("/api/symbols", params={"name": "MyClass"})

        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["symbol_name"] == "MyClass"
        assert data[0]["kind"] == "class"
        mock_app.state.symbol_db.query_by_name.assert_called_once_with(
            "MyClass", kind=None
        )

    def test_list_symbols_filtered_by_file_path(
        self, mock_app: FastAPI, client: TestClient
    ) -> None:
        sample = SymbolDefinition(
            file_path="src/utils.py",
            symbol_name="helper",
            kind=SymbolKind.FUNCTION,
            language=Language.PYTHON,
            line_start=5,
            line_end=15,
        )
        mock_app.state.symbol_db.query_by_file.return_value = [sample]

        resp = client.get("/api/symbols", params={"file_path": "src/utils.py"})

        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["file_path"] == "src/utils.py"
        mock_app.state.symbol_db.query_by_file.assert_called_once_with("src/utils.py")


# ---------------------------------------------------------------------------
# 4. GET /api/dependencies?file_path=test.py -> 200
# ---------------------------------------------------------------------------

class TestDependenciesEndpoint:
    """Tests for the dependencies endpoint."""

    def test_get_dependencies_returns_deps(
        self, mock_app: FastAPI, client: TestClient
    ) -> None:
        resp = client.get("/api/dependencies", params={"file_path": "test.py"})

        assert resp.status_code == 200
        body = resp.json()
        assert body["file_path"] == "test.py"
        assert body["depth"] == 1
        assert "dep1.py" in body["dependencies"]
        assert "dependent1.py" in body["dependents"]
        mock_app.state.graph_analyzer.get_dependencies.assert_called_once_with(
            "test.py", depth=1
        )
        mock_app.state.graph_analyzer.get_dependents.assert_called_once_with(
            "test.py", depth=1
        )

    def test_get_dependencies_forward_only(
        self, mock_app: FastAPI, client: TestClient
    ) -> None:
        resp = client.get(
            "/api/dependencies",
            params={"file_path": "test.py", "direction": "forward"},
        )

        assert resp.status_code == 200
        body = resp.json()
        assert body["dependencies"] == ["dep1.py"]
        assert body["dependents"] == []

    def test_get_dependencies_requires_file_path(self, client: TestClient) -> None:
        """file_path is required -- omitting it should return 422."""
        resp = client.get("/api/dependencies")
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# 5. GET /api/graph/analysis -> 200
# ---------------------------------------------------------------------------

class TestGraphAnalysisEndpoint:
    """Tests for the graph analysis endpoint."""

    def test_graph_analysis_returns_analysis(
        self, mock_app: FastAPI, client: TestClient
    ) -> None:
        resp = client.get("/api/graph/analysis")

        assert resp.status_code == 200
        body = resp.json()
        assert body["node_count"] == 5
        assert body["edge_count"] == 3
        assert body["is_dag"] is True
        assert body["circular_dependencies"] == []
        assert body["connected_components"] == 1
        assert body["build_order"] == ["a.py", "b.py"]
        mock_app.state.graph_analyzer.analyze.assert_called_once()


# ---------------------------------------------------------------------------
# 6. POST /api/search with query -> 200
# ---------------------------------------------------------------------------

class TestSearchEndpoint:
    """Tests for the semantic search endpoint."""

    def test_search_with_query_returns_results(
        self, mock_app: FastAPI, client: TestClient
    ) -> None:
        resp = client.post("/api/search", json={"query": "find MyClass"})

        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["symbol_name"] == "MyClass"
        assert data[0]["score"] == 0.95
        mock_app.state.semantic_searcher.search.assert_called_once_with(
            query="find MyClass",
            language=None,
            service_name=None,
            top_k=10,
        )

    # -------------------------------------------------------------------
    # 7. POST /api/search with filters -> filtered results
    # -------------------------------------------------------------------

    def test_search_with_filters_returns_filtered_results(
        self, mock_app: FastAPI, client: TestClient
    ) -> None:
        resp = client.post(
            "/api/search",
            json={
                "query": "database handler",
                "language": "python",
                "service_name": "my-service",
                "top_k": 5,
            },
        )

        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        mock_app.state.semantic_searcher.search.assert_called_once_with(
            query="database handler",
            language="python",
            service_name="my-service",
            top_k=5,
        )

    # -------------------------------------------------------------------
    # 10. POST /api/search with empty query -> 422
    # -------------------------------------------------------------------

    def test_search_with_empty_query_returns_422(self, client: TestClient) -> None:
        resp = client.post("/api/search", json={"query": ""})
        assert resp.status_code == 422

    def test_search_without_body_returns_422(self, client: TestClient) -> None:
        resp = client.post("/api/search")
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# 8. POST /api/artifacts with file_path -> 200
# ---------------------------------------------------------------------------

class TestArtifactsEndpoint:
    """Tests for the artifact indexing endpoint."""

    def test_register_artifact_triggers_indexing(
        self, mock_app: FastAPI, client: TestClient
    ) -> None:
        resp = client.post(
            "/api/artifacts",
            json={"file_path": "src/main.py", "service_name": "my-service"},
        )

        assert resp.status_code == 200
        body = resp.json()
        assert body["indexed"] is True
        assert body["symbols_found"] == 3
        assert body["dependencies_found"] == 1
        assert body["errors"] == []
        mock_app.state.incremental_indexer.index_file.assert_called_once_with(
            file_path="src/main.py",
            source=None,
            service_name="my-service",
            project_root=None,
        )

    def test_register_artifact_with_source(
        self, mock_app: FastAPI, client: TestClient
    ) -> None:
        """When base64 source is provided it should be decoded and forwarded."""
        import base64

        source_content = b"print('hello')"
        encoded = base64.b64encode(source_content).decode()

        resp = client.post(
            "/api/artifacts",
            json={"file_path": "script.py", "source": encoded},
        )

        assert resp.status_code == 200
        call_kwargs = mock_app.state.incremental_indexer.index_file.call_args
        assert call_kwargs.kwargs["source"] == source_content

    def test_register_artifact_missing_file_path_returns_422(
        self, client: TestClient
    ) -> None:
        resp = client.post("/api/artifacts", json={})
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# 9. GET /api/dead-code -> 200
# ---------------------------------------------------------------------------

class TestDeadCodeEndpoint:
    """Tests for the dead code detection endpoint."""

    def test_dead_code_returns_entries(
        self, mock_app: FastAPI, client: TestClient
    ) -> None:
        # The dead code router first queries symbols from DB, so we need
        # the mock to return at least one SymbolDefinition.
        sample_symbol = SymbolDefinition(
            file_path="test.py",
            symbol_name="unused_func",
            kind=SymbolKind.FUNCTION,
            language=Language.PYTHON,
            line_start=10,
            line_end=20,
        )
        mock_conn = mock_app.state.symbol_db._pool.get.return_value
        mock_conn.execute.return_value.fetchall.return_value = ["row1"]
        mock_app.state.symbol_db._row_to_symbol.return_value = sample_symbol

        resp = client.get("/api/dead-code")

        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["symbol_name"] == "unused_func"
        assert data[0]["file_path"] == "test.py"
        assert data[0]["kind"] == "function"
        assert data[0]["confidence"] == "high"
        mock_app.state.dead_code_detector.find_dead_code.assert_called_once()

    def test_dead_code_empty_when_no_symbols(
        self, mock_app: FastAPI, client: TestClient
    ) -> None:
        """If the DB has no symbols the endpoint should return an empty list."""
        mock_conn = mock_app.state.symbol_db._pool.get.return_value
        mock_conn.execute.return_value.fetchall.return_value = []

        resp = client.get("/api/dead-code")

        assert resp.status_code == 200
        assert resp.json() == []
        mock_app.state.dead_code_detector.find_dead_code.assert_not_called()

    def test_dead_code_with_service_name_filter(
        self, mock_app: FastAPI, client: TestClient
    ) -> None:
        sample_symbol = SymbolDefinition(
            file_path="test.py",
            symbol_name="unused_func",
            kind=SymbolKind.FUNCTION,
            language=Language.PYTHON,
            line_start=10,
            line_end=20,
            service_name="my-service",
        )
        mock_conn = mock_app.state.symbol_db._pool.get.return_value
        mock_conn.execute.return_value.fetchall.return_value = ["row1"]
        mock_app.state.symbol_db._row_to_symbol.return_value = sample_symbol

        resp = client.get("/api/dead-code", params={"service_name": "my-service"})

        assert resp.status_code == 200
        # The raw SQL path should include the WHERE clause for service_name
        call_args = mock_conn.execute.call_args
        assert "service_name" in call_args[0][0]

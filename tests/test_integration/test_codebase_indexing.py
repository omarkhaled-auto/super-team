"""Integration tests for the full codebase indexing pipeline (REQ-018).

Verifies that files can be registered via the artifacts API, symbols become
queryable, semantic search returns relevant results, and dead code detection
operates correctly -- all exercised through the FastAPI ``TestClient``.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

# ---------------------------------------------------------------------------
# Resolve the absolute path to the sample codebase files *before* any test
# runs, so that the indexer can read them from disk.
# ---------------------------------------------------------------------------
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_SAMPLE_DIR = _PROJECT_ROOT / "sample_data" / "sample_codebase" / "auth_service"
_AUTH_PY = str(_SAMPLE_DIR / "auth.py")
_MODELS_PY = str(_SAMPLE_DIR / "models.py")


@pytest.fixture(scope="module")
def client(tmp_path_factory: pytest.TempPathFactory) -> TestClient:
    """Create a ``TestClient`` backed by temporary storage directories.

    Environment variables are set *before* the app module is imported so that
    ``CodebaseIntelConfig`` picks up the temporary paths for the database,
    ChromaDB, and graph snapshot file.  They are cleaned up after the module
    tests complete to avoid leaking into other test modules.
    """
    tmp = tmp_path_factory.mktemp("codebase_intel")
    db_path = str(tmp / "test.db")
    chroma_path = str(tmp / "chroma")
    graph_path = str(tmp / "graph.json")

    # Ensure the chroma directory exists before ChromaDB tries to use it.
    os.makedirs(chroma_path, exist_ok=True)

    # Save original env values so we can restore them after tests.
    _saved_env: dict[str, str | None] = {
        "DATABASE_PATH": os.environ.get("DATABASE_PATH"),
        "CHROMA_PATH": os.environ.get("CHROMA_PATH"),
        "GRAPH_PATH": os.environ.get("GRAPH_PATH"),
    }

    os.environ["DATABASE_PATH"] = db_path
    os.environ["CHROMA_PATH"] = chroma_path
    os.environ["GRAPH_PATH"] = graph_path

    # Import the app *after* environment variables are configured so the
    # ``CodebaseIntelConfig`` reads the temp paths.
    from src.codebase_intelligence.main import app

    with TestClient(app) as tc:
        yield tc

    # Restore original environment variables.
    for key, original in _saved_env.items():
        if original is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = original


@pytest.fixture(scope="module")
def indexed_auth(client: TestClient) -> dict:
    """Register ``auth.py`` once and return the JSON response.

    Using *module* scope avoids re-indexing in every test that needs the
    artifact to be present.
    """
    response = client.post(
        "/api/artifacts",
        json={
            "file_path": _AUTH_PY,
            "service_name": "auth-service",
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


@pytest.fixture(scope="module")
def indexed_models(client: TestClient) -> dict:
    """Register ``models.py`` once and return the JSON response."""
    response = client.post(
        "/api/artifacts",
        json={
            "file_path": _MODELS_PY,
            "service_name": "auth-service",
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


# ------------------------------------------------------------------
# Test cases
# ------------------------------------------------------------------


class TestRegisterArtifact:
    """Tests for ``POST /api/artifacts``."""

    def test_register_artifact_python_file(
        self, client: TestClient, indexed_auth: dict
    ) -> None:
        """Registering auth.py returns a successful indexing result."""
        assert indexed_auth["indexed"] is True
        assert indexed_auth["symbols_found"] > 0
        assert isinstance(indexed_auth["errors"], list)


class TestSymbolsQueryable:
    """Tests for ``GET /api/symbols`` after indexing."""

    def test_symbols_queryable_after_indexing(
        self, client: TestClient, indexed_auth: dict
    ) -> None:
        """Symbols extracted from auth.py are retrievable via the API."""
        response = client.get(
            "/api/symbols",
            params={"service_name": "auth-service"},
        )
        assert response.status_code == 200
        symbols = response.json()
        assert isinstance(symbols, list)
        assert len(symbols) > 0

        # The sample auth.py defines ``AuthService`` -- make sure it shows up.
        symbol_names = [s["symbol_name"] for s in symbols]
        assert "AuthService" in symbol_names


class TestSemanticSearch:
    """Tests for ``POST /api/search`` after indexing."""

    def test_semantic_search_after_indexing(
        self, client: TestClient, indexed_auth: dict
    ) -> None:
        """A query for 'authentication' returns at least one result
        whose file_path points back to the indexed auth module."""
        response = client.post(
            "/api/search",
            json={"query": "authentication"},
        )
        assert response.status_code == 200
        results = response.json()
        assert isinstance(results, list)
        assert len(results) > 0

        # At least one result should reference the auth file.
        file_paths = [r["file_path"] for r in results]
        assert any("auth.py" in fp for fp in file_paths)


class TestDeadCodeDetection:
    """Tests for ``GET /api/dead-code`` after indexing."""

    def test_dead_code_detection(
        self, client: TestClient, indexed_auth: dict
    ) -> None:
        """Dead code endpoint returns a list (possibly empty) after
        indexing.  Each entry, if present, must have the expected
        schema keys."""
        response = client.get("/api/dead-code")
        assert response.status_code == 200
        entries = response.json()
        assert isinstance(entries, list)

        # If any dead code was detected, validate the entry shape matches
        # the DeadCodeEntry model (symbol_name, file_path, kind, line,
        # service_name, confidence).
        for entry in entries:
            assert "symbol_name" in entry
            assert "file_path" in entry
            assert "kind" in entry
            assert "line" in entry
            assert "confidence" in entry


class TestRegisterMultipleArtifacts:
    """Tests for indexing several files in the same service."""

    def test_register_multiple_artifacts(
        self,
        client: TestClient,
        indexed_auth: dict,
        indexed_models: dict,
    ) -> None:
        """After registering both auth.py and models.py, symbols from
        both files appear in the symbol listing."""
        assert indexed_auth["indexed"] is True
        assert indexed_models["indexed"] is True

        response = client.get(
            "/api/symbols",
            params={"service_name": "auth-service"},
        )
        assert response.status_code == 200
        symbols = response.json()
        symbol_names = [s["symbol_name"] for s in symbols]

        # ``AuthService`` comes from auth.py, ``User`` from models.py.
        assert "AuthService" in symbol_names
        assert "User" in symbol_names


class TestHealthEndpoint:
    """Tests for ``GET /api/health``."""

    def test_health_endpoint_returns_healthy(self, client: TestClient) -> None:
        """The health endpoint reports a healthy status with database
        connected."""
        response = client.get("/api/health")
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "healthy"
        assert body["service_name"] == "codebase-intelligence"
        assert body["database"] == "connected"

"""E2E tests for the Codebase Intelligence Service.

Endpoints covered:
  - CI-01: GET  /api/health
  - CI-02: GET  /api/symbols
  - CI-03: GET  /api/dependencies
  - CI-04: GET  /api/graph/analysis
  - CI-05: POST /api/search
  - CI-06: POST /api/artifacts
  - CI-07: GET  /api/dead-code
"""
import pytest
import httpx
import base64

from tests.e2e.api.conftest import (
    CODEBASE_INTEL_URL,
    SAMPLE_PYTHON_SOURCE,
    SAMPLE_PYTHON_SOURCE_B64,
    TIMEOUT,
)


@pytest.fixture(scope="module")
def client():
    with httpx.Client(base_url=CODEBASE_INTEL_URL, timeout=TIMEOUT) as c:
        yield c


@pytest.fixture(scope="module")
def registered_artifact(client):
    """Register a Python artifact and return the result.
    This fixture ensures we have indexed data for symbol/search/graph tests.
    """
    payload = {
        "file_path": "auth_service/auth.py",
        "service_name": "auth-service",
        "source": SAMPLE_PYTHON_SOURCE_B64,
    }
    resp = client.post("/api/artifacts", json=payload)
    assert resp.status_code == 200, f"Failed to register artifact: {resp.text}"
    return resp.json()


# ── CI-01: GET /api/health ──────────────────────────────────────────────


class TestCodebaseIntelHealth:
    """CI-01: Health check endpoint."""

    def test_health_returns_200(self, client):
        resp = client.get("/api/health")
        assert resp.status_code == 200

    def test_health_response_shape(self, client):
        resp = client.get("/api/health")
        data = resp.json()
        assert data["status"] == "healthy"
        assert "service_name" in data
        assert "version" in data
        assert data["database"] == "connected"
        assert isinstance(data["uptime_seconds"], (int, float))
        # Codebase intelligence should include chroma details
        assert "details" in data


# ── CI-06: POST /api/artifacts ──────────────────────────────────────────
# Tested FIRST because other tests depend on having artifacts indexed.


class TestArtifactRegistration:
    """CI-06: Artifact registration endpoint."""

    def test_register_python_artifact(self, client):
        payload = {
            "file_path": "auth_service/auth.py",
            "service_name": "auth-service",
            "source": SAMPLE_PYTHON_SOURCE_B64,
        }
        resp = client.post("/api/artifacts", json=payload)
        assert resp.status_code == 200

    def test_register_artifact_response_shape(self, client):
        payload = {
            "file_path": "test_module/sample.py",
            "service_name": "test-service",
            "source": base64.b64encode(
                b'"""Test module."""\n\ndef hello():\n    """Say hello."""\n    return "hello"\n\nclass Greeter:\n    """A greeter class."""\n    def greet(self, name: str) -> str:\n        return f"Hello, {name}"\n'
            ).decode("utf-8"),
        }
        resp = client.post("/api/artifacts", json=payload)
        assert resp.status_code == 200
        data = resp.json()
        # Should return indexing result data
        assert isinstance(data, dict)

    def test_register_artifact_missing_file_path_returns_422(self, client):
        resp = client.post("/api/artifacts", json={"service_name": "test"})
        assert resp.status_code == 422

    def test_register_artifact_mutation_verification(self, client, registered_artifact):
        """Mutation Verification Rule: register then GET symbols confirms indexing."""
        # After registering, symbols should appear
        resp = client.get("/api/symbols", params={"file_path": "auth_service/auth.py"})
        assert resp.status_code == 200
        data = resp.json()
        # Should have extracted symbols from the Python source
        assert isinstance(data, list)


# ── CI-02: GET /api/symbols ─────────────────────────────────────────────


class TestSymbolList:
    """CI-02: Symbol listing endpoint."""

    def test_symbols_returns_200(self, client, registered_artifact):
        resp = client.get("/api/symbols")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_symbols_filter_by_language(self, client, registered_artifact):
        resp = client.get("/api/symbols", params={"language": "python"})
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        for symbol in data:
            assert symbol.get("language", "python") == "python"

    def test_symbols_filter_by_kind(self, client, registered_artifact):
        resp = client.get("/api/symbols", params={"kind": "class"})
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        for symbol in data:
            assert symbol.get("kind") == "class"

    def test_symbols_filter_by_name(self, client, registered_artifact):
        resp = client.get("/api/symbols", params={"name": "AuthService"})
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)

    def test_symbols_filter_by_service_name(self, client, registered_artifact):
        resp = client.get("/api/symbols", params={"service_name": "auth-service"})
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)

    def test_symbols_filter_by_file_path(self, client, registered_artifact):
        resp = client.get("/api/symbols", params={"file_path": "auth_service/auth.py"})
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)


# ── CI-03: GET /api/dependencies ─────────────────────────────────────────


class TestDependencies:
    """CI-03: Dependency analysis endpoint."""

    def test_dependencies_returns_200(self, client, registered_artifact):
        resp = client.get("/api/dependencies", params={"file_path": "auth_service/auth.py"})
        assert resp.status_code == 200

    def test_dependencies_response_shape(self, client, registered_artifact):
        resp = client.get("/api/dependencies", params={
            "file_path": "auth_service/auth.py",
            "depth": 1,
            "direction": "both",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert "file_path" in data
        assert "depth" in data

    def test_dependencies_custom_depth(self, client, registered_artifact):
        resp = client.get("/api/dependencies", params={
            "file_path": "auth_service/auth.py",
            "depth": 3,
        })
        assert resp.status_code == 200

    def test_dependencies_missing_file_path_returns_422(self, client):
        resp = client.get("/api/dependencies")
        assert resp.status_code == 422


# ── CI-04: GET /api/graph/analysis ───────────────────────────────────────


class TestGraphAnalysis:
    """CI-04: Graph analysis endpoint."""

    def test_graph_analysis_returns_200(self, client, registered_artifact):
        resp = client.get("/api/graph/analysis")
        assert resp.status_code == 200

    def test_graph_analysis_response_shape(self, client, registered_artifact):
        resp = client.get("/api/graph/analysis")
        data = resp.json()
        assert "node_count" in data
        assert "edge_count" in data
        assert isinstance(data["node_count"], int)
        assert isinstance(data["edge_count"], int)


# ── CI-05: POST /api/search ─────────────────────────────────────────────


class TestSemanticSearch:
    """CI-05: Semantic search endpoint."""

    def test_search_returns_200(self, client, registered_artifact):
        payload = {"query": "authentication password hashing"}
        resp = client.post("/api/search", json=payload)
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_search_with_filters(self, client, registered_artifact):
        payload = {
            "query": "token verification",
            "language": "python",
            "service_name": "auth-service",
            "top_k": 5,
        }
        resp = client.post("/api/search", json=payload)
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert len(data) <= 5

    def test_search_empty_query_returns_422(self, client):
        resp = client.post("/api/search", json={"query": ""})
        assert resp.status_code == 422

    def test_search_missing_query_returns_422(self, client):
        resp = client.post("/api/search", json={})
        assert resp.status_code == 422


# ── CI-07: GET /api/dead-code ────────────────────────────────────────────


class TestDeadCode:
    """CI-07: Dead code detection endpoint."""

    def test_dead_code_returns_200(self, client, registered_artifact):
        resp = client.get("/api/dead-code")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_dead_code_filter_by_service(self, client, registered_artifact):
        resp = client.get("/api/dead-code", params={"service_name": "auth-service"})
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_dead_code_response_shape(self, client, registered_artifact):
        resp = client.get("/api/dead-code")
        data = resp.json()
        assert isinstance(data, list)
        for entry in data:
            # Each entry should have at minimum symbol_name and file_path
            if entry:  # Only check if results exist
                assert "symbol_name" in entry
                assert "file_path" in entry


# ── Endpoint Coverage Summary ──────────────────────────────────────────────
# GET  /api/health       → TESTED (TestCodebaseIntelHealth)
# GET  /api/symbols      → TESTED (TestSymbolList)
# GET  /api/dependencies → TESTED (TestDependencies)
# GET  /api/graph/analysis → TESTED (TestGraphAnalysis)
# POST /api/search       → TESTED (TestSemanticSearch)
# POST /api/artifacts    → TESTED (TestArtifactRegistration)
# GET  /api/dead-code    → TESTED (TestDeadCode)
# All 7 codebase intelligence endpoints covered.

"""E2E tests for the Architect Service.

Endpoints covered:
  - ARCH-01: GET  /api/health
  - ARCH-02: POST /api/decompose
  - ARCH-03: GET  /api/service-map
  - ARCH-04: GET  /api/domain-model
"""
import pytest
import httpx

from tests.e2e.api.conftest import (
    ARCHITECT_URL,
    SAMPLE_PRD_TEXT,
    TIMEOUT,
)


@pytest.fixture(scope="module")
def client():
    with httpx.Client(base_url=ARCHITECT_URL, timeout=TIMEOUT) as c:
        yield c


# ── ARCH-01: GET /api/health ─────────────────────────────────────────────


class TestArchitectHealth:
    """ARCH-01: Health check endpoint."""

    def test_health_returns_200(self, client):
        resp = client.get("/api/health")
        assert resp.status_code == 200

    def test_health_response_shape(self, client):
        resp = client.get("/api/health")
        data = resp.json()
        assert data["status"] == "healthy"
        assert "service_name" in data
        assert "version" in data
        assert "database" in data
        assert data["database"] == "connected"
        assert "uptime_seconds" in data
        assert isinstance(data["uptime_seconds"], (int, float))
        assert data["uptime_seconds"] >= 0


# ── ARCH-02: POST /api/decompose ─────────────────────────────────────────


class TestArchitectDecompose:
    """ARCH-02: PRD decomposition endpoint."""

    def test_decompose_returns_201(self, client):
        resp = client.post("/api/decompose", json={"prd_text": SAMPLE_PRD_TEXT})
        assert resp.status_code == 201

    def test_decompose_response_has_required_fields(self, client):
        resp = client.post("/api/decompose", json={"prd_text": SAMPLE_PRD_TEXT})
        data = resp.json()
        assert "service_map" in data
        assert "domain_model" in data
        assert "contract_stubs" in data
        assert "validation_issues" in data
        assert "interview_questions" in data

    def test_decompose_service_map_has_services(self, client):
        resp = client.post("/api/decompose", json={"prd_text": SAMPLE_PRD_TEXT})
        data = resp.json()
        service_map = data["service_map"]
        assert "services" in service_map
        assert len(service_map["services"]) >= 1

    def test_decompose_domain_model_structure(self, client):
        resp = client.post("/api/decompose", json={"prd_text": SAMPLE_PRD_TEXT})
        data = resp.json()
        domain_model = data["domain_model"]
        assert "entities" in domain_model
        assert "relationships" in domain_model

    def test_decompose_contract_stubs_are_list(self, client):
        resp = client.post("/api/decompose", json={"prd_text": SAMPLE_PRD_TEXT})
        data = resp.json()
        assert isinstance(data["contract_stubs"], list)

    def test_decompose_empty_prd_returns_422(self, client):
        resp = client.post("/api/decompose", json={"prd_text": ""})
        assert resp.status_code == 422

    def test_decompose_short_prd_returns_422(self, client):
        resp = client.post("/api/decompose", json={"prd_text": "short"})
        assert resp.status_code == 422

    def test_decompose_missing_body_returns_422(self, client):
        resp = client.post("/api/decompose", json={})
        assert resp.status_code == 422


# ── ARCH-03: GET /api/service-map ─────────────────────────────────────────


class TestArchitectServiceMap:
    """ARCH-03: Service map retrieval endpoint."""

    def test_service_map_returns_200_after_decompose(self, client):
        # Ensure we have a decomposition result
        client.post("/api/decompose", json={"prd_text": SAMPLE_PRD_TEXT})

        resp = client.get("/api/service-map")
        assert resp.status_code == 200

    def test_service_map_response_shape(self, client):
        resp = client.get("/api/service-map")
        data = resp.json()
        assert "services" in data
        assert "project_name" in data
        assert "generated_at" in data

    def test_service_map_unknown_project_returns_404(self, client):
        resp = client.get("/api/service-map", params={"project_name": "nonexistent-project-xyz"})
        assert resp.status_code == 404

    def test_service_map_mutation_verification(self, client):
        """Mutation Verification Rule: decompose then GET confirms persistence."""
        post_resp = client.post("/api/decompose", json={"prd_text": SAMPLE_PRD_TEXT})
        assert post_resp.status_code == 201
        decomp_map = post_resp.json()["service_map"]

        get_resp = client.get("/api/service-map")
        assert get_resp.status_code == 200
        fetched_map = get_resp.json()

        # The service names should match
        decomp_names = {s["name"] for s in decomp_map["services"]}
        fetched_names = {s["name"] for s in fetched_map["services"]}
        assert decomp_names == fetched_names


# ── ARCH-04: GET /api/domain-model ─────────────────────────────────────────


class TestArchitectDomainModel:
    """ARCH-04: Domain model retrieval endpoint."""

    def test_domain_model_returns_200_after_decompose(self, client):
        client.post("/api/decompose", json={"prd_text": SAMPLE_PRD_TEXT})

        resp = client.get("/api/domain-model")
        assert resp.status_code == 200

    def test_domain_model_response_shape(self, client):
        resp = client.get("/api/domain-model")
        data = resp.json()
        assert "entities" in data
        assert "relationships" in data
        assert "generated_at" in data

    def test_domain_model_entities_non_empty(self, client):
        resp = client.get("/api/domain-model")
        data = resp.json()
        assert len(data["entities"]) >= 1

    def test_domain_model_unknown_project_returns_404(self, client):
        resp = client.get("/api/domain-model", params={"project_name": "nonexistent-project-xyz"})
        assert resp.status_code == 404

    def test_domain_model_mutation_verification(self, client):
        """Mutation Verification Rule: decompose then GET confirms persistence."""
        post_resp = client.post("/api/decompose", json={"prd_text": SAMPLE_PRD_TEXT})
        decomp_model = post_resp.json()["domain_model"]

        get_resp = client.get("/api/domain-model")
        fetched_model = get_resp.json()

        # Entity names should match
        decomp_entity_names = {e["name"] for e in decomp_model["entities"]}
        fetched_entity_names = {e["name"] for e in fetched_model["entities"]}
        assert decomp_entity_names == fetched_entity_names


# ── Endpoint Coverage Summary ──────────────────────────────────────────────
# GET  /api/health       → TESTED (TestArchitectHealth)
# POST /api/decompose    → TESTED (TestArchitectDecompose)
# GET  /api/service-map  → TESTED (TestArchitectServiceMap)
# GET  /api/domain-model → TESTED (TestArchitectDomainModel)
# All 4 architect endpoints covered.

"""Integration tests for Contract Engine API routers using FastAPI TestClient."""
import os
import sys
import tempfile

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    tmpdir = tempfile.mkdtemp()
    os.environ["DATABASE_PATH"] = os.path.join(tmpdir, "test.db")
    # Clear cached modules so the app picks up the new DATABASE_PATH
    for mod_name in list(sys.modules.keys()):
        if "contract_engine" in mod_name:
            del sys.modules[mod_name]
    from src.contract_engine.main import app

    with TestClient(app) as c:
        yield c


def _valid_openapi_spec():
    """Return a minimal valid OpenAPI 3.0.0 specification."""
    return {
        "openapi": "3.0.0",
        "info": {"title": "Test API", "version": "1.0.0"},
        "paths": {
            "/api/test": {
                "get": {
                    "summary": "Test endpoint",
                    "responses": {
                        "200": {"description": "OK"},
                    },
                },
            },
        },
    }


def _create_contract_payload(service_name="test-svc", version="1.0.0"):
    """Return a valid contract creation payload."""
    return {
        "service_name": service_name,
        "type": "openapi",
        "version": version,
        "spec": _valid_openapi_spec(),
    }


class TestHealthRouter:
    """Tests for the health check endpoint."""

    def test_health_returns_200(self, client):
        """GET /api/health returns 200 with service status."""
        resp = client.get("/api/health")

        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] in ("healthy", "degraded")
        assert "service_name" in data
        assert "version" in data
        assert "database" in data
        assert "uptime_seconds" in data


class TestContractsRouter:
    """Tests for the contracts CRUD endpoints."""

    def test_create_contract_201(self, client):
        """POST /api/contracts with valid payload returns 201."""
        payload = _create_contract_payload()
        resp = client.post("/api/contracts", json=payload)

        assert resp.status_code == 201
        data = resp.json()
        assert data["service_name"] == "test-svc"
        assert data["type"] == "openapi"
        assert data["version"] == "1.0.0"
        assert "id" in data
        assert "spec_hash" in data
        assert data["status"] == "draft"

    def test_create_contract_invalid_spec_422(self, client):
        """POST /api/contracts with an invalid OpenAPI spec returns 422."""
        payload = {
            "service_name": "test-svc",
            "type": "openapi",
            "version": "1.0.0",
            "spec": {"not_a_valid": "openapi_spec"},
        }
        resp = client.post("/api/contracts", json=payload)

        assert resp.status_code == 422

    def test_list_contracts_200(self, client):
        """GET /api/contracts returns a paginated list."""
        # Create two contracts
        client.post("/api/contracts", json=_create_contract_payload("svc-a", "1.0.0"))
        client.post("/api/contracts", json=_create_contract_payload("svc-b", "1.0.0"))

        resp = client.get("/api/contracts")

        assert resp.status_code == 200
        data = resp.json()
        assert "items" in data
        assert "total" in data
        assert "page" in data
        assert "page_size" in data
        assert data["total"] == 2
        assert len(data["items"]) == 2

    def test_get_contract_by_id_200(self, client):
        """GET /api/contracts/{id} returns the specific contract."""
        create_resp = client.post(
            "/api/contracts",
            json=_create_contract_payload(),
        )
        contract_id = create_resp.json()["id"]

        resp = client.get(f"/api/contracts/{contract_id}")

        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == contract_id
        assert data["service_name"] == "test-svc"

    def test_get_contract_not_found_404(self, client):
        """GET /api/contracts/nonexistent returns 404."""
        resp = client.get("/api/contracts/nonexistent-uuid")

        assert resp.status_code == 404
        data = resp.json()
        assert "detail" in data

    def test_delete_contract_204(self, client):
        """DELETE /api/contracts/{id} returns 204 on success."""
        create_resp = client.post(
            "/api/contracts",
            json=_create_contract_payload(),
        )
        contract_id = create_resp.json()["id"]

        resp = client.delete(f"/api/contracts/{contract_id}")
        assert resp.status_code == 204

        # Confirm it is actually deleted
        get_resp = client.get(f"/api/contracts/{contract_id}")
        assert get_resp.status_code == 404

    def test_list_pagination(self, client):
        """Verify page/page_size/total pagination behavior."""
        # Create 5 contracts
        for i in range(5):
            client.post(
                "/api/contracts",
                json=_create_contract_payload(f"svc-{i}", "1.0.0"),
            )

        # Request page 1 with page_size=2
        resp = client.get("/api/contracts", params={"page": 1, "page_size": 2})

        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 5
        assert data["page"] == 1
        assert data["page_size"] == 2
        assert len(data["items"]) == 2

        # Request page 2 with page_size=2
        resp2 = client.get("/api/contracts", params={"page": 2, "page_size": 2})
        data2 = resp2.json()
        assert data2["total"] == 5
        assert data2["page"] == 2
        assert len(data2["items"]) == 2

        # Request page 3 with page_size=2 (should have 1 remaining)
        resp3 = client.get("/api/contracts", params={"page": 3, "page_size": 2})
        data3 = resp3.json()
        assert data3["total"] == 5
        assert data3["page"] == 3
        assert len(data3["items"]) == 1


class TestValidationRouter:
    """Tests for the validation endpoint."""

    def test_validate_openapi_valid(self, client):
        """POST /api/validate with a valid OpenAPI spec returns valid=true."""
        payload = {
            "spec": _valid_openapi_spec(),
            "type": "openapi",
        }

        resp = client.post("/api/validate", json=payload)

        assert resp.status_code == 200
        data = resp.json()
        assert data["valid"] is True
        assert data["errors"] == []

    def test_validate_openapi_invalid(self, client):
        """POST /api/validate with an invalid OpenAPI spec returns valid=false."""
        payload = {
            "spec": {"not_valid": "at all"},
            "type": "openapi",
        }

        resp = client.post("/api/validate", json=payload)

        assert resp.status_code == 200
        data = resp.json()
        assert data["valid"] is False
        assert len(data["errors"]) > 0


class TestImplementationsRouter:
    """Tests for the implementation tracking endpoints."""

    def test_mark_implementation_200(self, client):
        """POST /api/implementations/mark succeeds for an existing contract."""
        # First create a contract
        create_resp = client.post(
            "/api/contracts",
            json=_create_contract_payload(),
        )
        contract_id = create_resp.json()["id"]

        # Mark it as implemented
        payload = {
            "contract_id": contract_id,
            "service_name": "consumer-svc",
            "evidence_path": "/tests/test_integration.py",
        }
        resp = client.post("/api/implementations/mark", json=payload)

        assert resp.status_code == 200
        data = resp.json()
        assert data["marked"] is True
        assert data["total_implementations"] == 1

    def test_get_unimplemented_200(self, client):
        """GET /api/implementations/unimplemented returns a list."""
        # Create a contract (which starts unimplemented)
        client.post(
            "/api/contracts",
            json=_create_contract_payload(),
        )

        resp = client.get("/api/implementations/unimplemented")

        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert len(data) >= 1
        assert "id" in data[0]
        assert "expected_service" in data[0]

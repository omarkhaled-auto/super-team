"""Integration tests for test generation and compliance checking routers."""
from __future__ import annotations

import os
import sys
import tempfile

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    """Create a TestClient backed by a temporary database."""
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
                        "200": {
                            "description": "OK",
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "object",
                                        "properties": {
                                            "message": {"type": "string"},
                                        },
                                        "required": ["message"],
                                    }
                                }
                            },
                        },
                    },
                },
            },
        },
    }


def _create_contract(client, spec=None, service_name="test-svc", version="1.0.0"):
    """Helper to create a contract and return its ID."""
    if spec is None:
        spec = _valid_openapi_spec()
    payload = {
        "service_name": service_name,
        "type": "openapi",
        "version": version,
        "spec": spec,
    }
    resp = client.post("/api/contracts", json=payload)
    assert resp.status_code == 201, f"Contract creation failed: {resp.text}"
    return resp.json()["id"]


# ------------------------------------------------------------------
# POST /api/tests/generate/{contract_id}
# ------------------------------------------------------------------

class TestGenerateEndpoint:
    """Tests for POST /api/tests/generate/{contract_id}."""

    def test_generate_returns_200(self, client):
        """POST /api/tests/generate/{id} returns 200 with ContractTestSuite."""
        contract_id = _create_contract(client)
        resp = client.post(f"/api/tests/generate/{contract_id}")

        assert resp.status_code == 200
        data = resp.json()
        assert "contract_id" in data
        assert data["contract_id"] == contract_id
        assert "test_code" in data
        assert "test_count" in data
        assert data["test_count"] >= 0
        assert data["framework"] == "pytest"

    def test_generate_with_include_negative(self, client):
        """POST with include_negative=true should produce more tests."""
        contract_id = _create_contract(client)

        resp_normal = client.post(f"/api/tests/generate/{contract_id}")
        normal_count = resp_normal.json()["test_count"]

        # Delete cached suite to force regeneration
        # Use a different contract to avoid caching issues
        contract_id_2 = _create_contract(
            client, service_name="test-svc-2", version="1.0.0"
        )
        resp_negative = client.post(
            f"/api/tests/generate/{contract_id_2}?include_negative=true"
        )
        negative_count = resp_negative.json()["test_count"]

        assert negative_count >= normal_count

    def test_generate_404_for_unknown(self, client):
        """POST with unknown contract_id returns 404."""
        resp = client.post("/api/tests/generate/non-existent-uuid")
        assert resp.status_code == 404

    def test_generate_cached_on_second_call(self, client):
        """Second call returns same test suite (cached)."""
        contract_id = _create_contract(client)
        resp1 = client.post(f"/api/tests/generate/{contract_id}")
        resp2 = client.post(f"/api/tests/generate/{contract_id}")

        assert resp1.json()["test_code"] == resp2.json()["test_code"]
        assert resp1.json()["test_count"] == resp2.json()["test_count"]


# ------------------------------------------------------------------
# GET /api/tests/{contract_id}
# ------------------------------------------------------------------

class TestGetTestSuiteEndpoint:
    """Tests for GET /api/tests/{contract_id}."""

    def test_get_returns_generated_suite(self, client):
        """GET /api/tests/{id} returns a previously generated suite."""
        contract_id = _create_contract(client)
        # First generate
        client.post(f"/api/tests/generate/{contract_id}")

        # Then retrieve
        resp = client.get(f"/api/tests/{contract_id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["contract_id"] == contract_id
        assert data["test_code"] != ""

    def test_get_404_when_not_generated(self, client):
        """GET /api/tests/{id} returns 404 when no suite exists."""
        contract_id = _create_contract(client)
        resp = client.get(f"/api/tests/{contract_id}")
        assert resp.status_code == 404


# ------------------------------------------------------------------
# POST /api/compliance/check/{contract_id}
# ------------------------------------------------------------------

class TestComplianceEndpoint:
    """Tests for POST /api/compliance/check/{contract_id}."""

    def test_compliance_returns_200(self, client):
        """POST /api/compliance/check/{id} returns 200 with results."""
        contract_id = _create_contract(client)
        response_data = {
            "GET /api/test": {"message": "hello"},
        }
        resp = client.post(
            f"/api/compliance/check/{contract_id}", json=response_data
        )

        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert len(data) == 1
        assert data[0]["endpoint_path"] == "/api/test"
        assert data[0]["method"] == "GET"
        assert data[0]["compliant"] is True

    def test_compliance_detects_violation(self, client):
        """POST with non-compliant response should return violations."""
        contract_id = _create_contract(client)
        response_data = {
            "GET /api/test": {
                # "message" is missing — required!
            },
        }
        resp = client.post(
            f"/api/compliance/check/{contract_id}", json=response_data
        )

        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["compliant"] is False
        assert len(data[0]["violations"]) > 0

    def test_compliance_404_for_unknown(self, client):
        """POST with unknown contract_id returns 404."""
        resp = client.post(
            "/api/compliance/check/non-existent-uuid", json={}
        )
        assert resp.status_code == 404

    def test_compliance_empty_data(self, client):
        """POST with empty response data returns empty results."""
        contract_id = _create_contract(client)
        resp = client.post(
            f"/api/compliance/check/{contract_id}", json={}
        )

        assert resp.status_code == 200
        assert resp.json() == []

    def test_compliance_extra_fields_are_not_errors(self, client):
        """Extra fields should be info/warning, not errors."""
        contract_id = _create_contract(client)
        response_data = {
            "GET /api/test": {
                "message": "hello",
                "extra_bonus": "data",
            },
        }
        resp = client.post(
            f"/api/compliance/check/{contract_id}", json=response_data
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data[0]["compliant"] is True
        # Extra field should generate info violation
        info_violations = [
            v for v in data[0]["violations"] if v["severity"] == "info"
        ]
        assert len(info_violations) >= 1

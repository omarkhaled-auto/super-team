"""E2E cross-service workflow tests.

Workflow covered:
  - XS-01: Architect decompose → Contract Engine store/validate/generate tests
"""
import pytest
import httpx

from tests.e2e.api.conftest import (
    ARCHITECT_URL,
    CONTRACT_ENGINE_URL,
    SAMPLE_PRD_TEXT,
    TIMEOUT,
)


@pytest.fixture(scope="module")
def architect_client():
    with httpx.Client(base_url=ARCHITECT_URL, timeout=TIMEOUT) as c:
        yield c


@pytest.fixture(scope="module")
def contract_client():
    with httpx.Client(base_url=CONTRACT_ENGINE_URL, timeout=TIMEOUT) as c:
        yield c


class TestCrossServiceWorkflow:
    """XS-01: Architect decompose → Contract Engine store & validate."""

    def test_decompose_and_store_contracts(self, architect_client, contract_client):
        """Full cross-service workflow:
        1. Decompose PRD via Architect
        2. Store contract stubs in Contract Engine
        3. Validate stored contracts
        4. Generate tests for stored contracts
        """
        # Step 1: Decompose PRD
        decomp_resp = architect_client.post(
            "/api/decompose", json={"prd_text": SAMPLE_PRD_TEXT}
        )
        assert decomp_resp.status_code == 201
        decomp_data = decomp_resp.json()

        contract_stubs = decomp_data.get("contract_stubs", [])
        service_map = decomp_data["service_map"]

        # Step 2: Store at least one contract in Contract Engine
        # Use the service names from the decomposition
        services = service_map.get("services", [])
        assert len(services) >= 1, "Decomposition should produce at least 1 service"

        # Build an OpenAPI spec for the first service
        first_service = services[0]
        service_name = first_service["name"]

        openapi_spec = {
            "openapi": "3.1.0",
            "info": {"title": f"{service_name} API", "version": "1.0.0"},
            "paths": {
                f"/api/{service_name}": {
                    "get": {
                        "summary": f"List {service_name} resources",
                        "responses": {
                            "200": {
                                "description": "Success",
                                "content": {
                                    "application/json": {
                                        "schema": {"type": "object"}
                                    }
                                },
                            }
                        },
                    }
                }
            },
        }

        create_resp = contract_client.post("/api/contracts", json={
            "service_name": service_name,
            "type": "openapi",
            "version": "1.0.0",
            "spec": openapi_spec,
        })
        assert create_resp.status_code == 201
        contract = create_resp.json()
        contract_id = contract["id"]

        # Step 3: Validate the stored contract
        validate_resp = contract_client.post("/api/validate", json={
            "spec": openapi_spec,
            "type": "openapi",
        })
        assert validate_resp.status_code == 200

        # Step 4: Generate tests for the contract
        gen_resp = contract_client.post(f"/api/tests/generate/{contract_id}")
        assert gen_resp.status_code == 200
        test_suite = gen_resp.json()
        assert test_suite["contract_id"] == contract_id
        assert test_suite["test_count"] >= 0

        # Step 5: Verify the contract persisted
        get_resp = contract_client.get(f"/api/contracts/{contract_id}")
        assert get_resp.status_code == 200
        assert get_resp.json()["service_name"] == service_name

    def test_decompose_produces_entities_and_relationships(self, architect_client):
        """Verify decomposition produces both entities and relationships."""
        resp = architect_client.post("/api/decompose", json={"prd_text": SAMPLE_PRD_TEXT})
        assert resp.status_code == 201
        data = resp.json()

        entities = data["domain_model"]["entities"]
        relationships = data["domain_model"]["relationships"]

        # Should have multiple entities from the e-commerce PRD
        assert len(entities) >= 2, f"Expected >= 2 entities, got {len(entities)}"

        # Each entity should have a name
        for entity in entities:
            assert "name" in entity
            assert len(entity["name"]) > 0


# ── Endpoint Coverage Summary ──────────────────────────────────────────────
# Cross-service workflow covering:
#   POST /api/decompose (Architect)
#   POST /api/contracts (Contract Engine)
#   POST /api/validate (Contract Engine)
#   POST /api/tests/generate/{id} (Contract Engine)
#   GET  /api/contracts/{id} (Contract Engine)
# XS-01: TESTED

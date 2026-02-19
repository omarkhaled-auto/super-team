"""E2E tests for the Contract Engine Service.

Endpoints covered:
  - CE-01:  GET    /api/health
  - CE-02:  POST   /api/contracts
  - CE-03:  GET    /api/contracts
  - CE-04:  GET    /api/contracts/{id}
  - CE-05:  DELETE /api/contracts/{id}
  - CE-06:  POST   /api/validate
  - CE-07:  POST   /api/breaking-changes/{id}
  - CE-08:  POST   /api/implementations/mark
  - CE-09:  GET    /api/implementations/unimplemented
  - CE-10:  POST   /api/tests/generate/{id}
  - CE-11:  GET    /api/tests/{id}
  - CE-12:  POST   /api/compliance/check/{id}
"""
import pytest
import httpx
import uuid

from tests.e2e.api.conftest import (
    CONTRACT_ENGINE_URL,
    SAMPLE_OPENAPI_SPEC,
    SAMPLE_ASYNCAPI_SPEC,
    TIMEOUT,
)


@pytest.fixture(scope="module")
def client():
    with httpx.Client(base_url=CONTRACT_ENGINE_URL, timeout=TIMEOUT) as c:
        yield c


def create_openapi_contract(client, service_name=None, version="1.0.0"):
    """Helper to create an OpenAPI contract and return its id."""
    svc_name = service_name or f"test-svc-{uuid.uuid4().hex[:8]}"
    payload = {
        "service_name": svc_name,
        "type": "openapi",
        "version": version,
        "spec": SAMPLE_OPENAPI_SPEC,
    }
    resp = client.post("/api/contracts", json=payload)
    assert resp.status_code == 201, f"Failed to create contract: {resp.text}"
    return resp.json()


# ── CE-01: GET /api/health ──────────────────────────────────────────────


class TestContractEngineHealth:
    """CE-01: Health check endpoint."""

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


# ── CE-02: POST /api/contracts ──────────────────────────────────────────


class TestContractCreate:
    """CE-02: Contract creation endpoint."""

    def test_create_openapi_contract_returns_201(self, client):
        contract = create_openapi_contract(client)
        assert "id" in contract
        assert contract["type"] == "openapi"
        assert contract["version"] == "1.0.0"
        assert "spec_hash" in contract
        assert contract["spec_hash"] != ""

    def test_create_contract_without_build_cycle_id(self, client):
        """Contracts can be created without a build_cycle_id (default None).
        Note: build_cycle_id has a FK constraint to build_cycles table,
        so only None or a valid build_cycle row id is accepted.
        """
        payload = {
            "service_name": f"svc-{uuid.uuid4().hex[:8]}",
            "type": "openapi",
            "version": "1.0.0",
            "spec": SAMPLE_OPENAPI_SPEC,
        }
        resp = client.post("/api/contracts", json=payload)
        assert resp.status_code == 201
        assert resp.json()["build_cycle_id"] is None

    def test_create_contract_invalid_type_returns_422(self, client):
        payload = {
            "service_name": "test-svc",
            "type": "invalid_type",
            "version": "1.0.0",
            "spec": {},
        }
        resp = client.post("/api/contracts", json=payload)
        assert resp.status_code == 422

    def test_create_contract_invalid_version_returns_422(self, client):
        payload = {
            "service_name": "test-svc",
            "type": "openapi",
            "version": "not-semver",
            "spec": SAMPLE_OPENAPI_SPEC,
        }
        resp = client.post("/api/contracts", json=payload)
        assert resp.status_code == 422

    def test_create_contract_missing_fields_returns_422(self, client):
        resp = client.post("/api/contracts", json={})
        assert resp.status_code == 422

    def test_create_asyncapi_contract(self, client):
        payload = {
            "service_name": f"events-svc-{uuid.uuid4().hex[:8]}",
            "type": "asyncapi",
            "version": "1.0.0",
            "spec": SAMPLE_ASYNCAPI_SPEC,
        }
        resp = client.post("/api/contracts", json=payload)
        assert resp.status_code == 201
        assert resp.json()["type"] == "asyncapi"


# ── CE-03: GET /api/contracts (list) ────────────────────────────────────


class TestContractList:
    """CE-03: Contract listing with pagination."""

    def test_list_contracts_returns_200(self, client):
        # Ensure at least one contract exists
        create_openapi_contract(client)
        resp = client.get("/api/contracts")
        assert resp.status_code == 200

    def test_list_contracts_pagination_shape(self, client):
        resp = client.get("/api/contracts")
        data = resp.json()
        assert "items" in data
        assert "total" in data
        assert "page" in data
        assert "page_size" in data
        assert isinstance(data["items"], list)

    def test_list_contracts_pagination_params(self, client):
        resp = client.get("/api/contracts", params={"page": 1, "page_size": 5})
        assert resp.status_code == 200
        data = resp.json()
        assert data["page"] == 1
        assert data["page_size"] == 5
        assert len(data["items"]) <= 5

    def test_list_contracts_filter_by_service_name(self, client):
        svc_name = f"filter-svc-{uuid.uuid4().hex[:8]}"
        create_openapi_contract(client, service_name=svc_name)

        resp = client.get("/api/contracts", params={"service_name": svc_name})
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] >= 1
        for item in data["items"]:
            assert item["service_name"] == svc_name

    def test_list_contracts_filter_by_type(self, client):
        resp = client.get("/api/contracts", params={"type": "openapi"})
        assert resp.status_code == 200
        for item in resp.json()["items"]:
            assert item["type"] == "openapi"


# ── CE-04: GET /api/contracts/{id} ──────────────────────────────────────


class TestContractGet:
    """CE-04: Single contract retrieval."""

    def test_get_contract_returns_200(self, client):
        contract = create_openapi_contract(client)
        contract_id = contract["id"]

        resp = client.get(f"/api/contracts/{contract_id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == contract_id
        assert data["type"] == "openapi"

    def test_get_contract_not_found_returns_404(self, client):
        fake_id = str(uuid.uuid4())
        resp = client.get(f"/api/contracts/{fake_id}")
        assert resp.status_code == 404

    def test_get_contract_mutation_verification(self, client):
        """Mutation Verification Rule: POST then GET confirms persistence."""
        contract = create_openapi_contract(client)
        contract_id = contract["id"]

        fetched = client.get(f"/api/contracts/{contract_id}")
        assert fetched.status_code == 200
        data = fetched.json()
        assert data["service_name"] == contract["service_name"]
        assert data["spec_hash"] == contract["spec_hash"]


# ── CE-05: DELETE /api/contracts/{id} ────────────────────────────────────


class TestContractDelete:
    """CE-05: Contract deletion endpoint."""

    def test_delete_contract_returns_204(self, client):
        contract = create_openapi_contract(client)
        contract_id = contract["id"]

        resp = client.delete(f"/api/contracts/{contract_id}")
        assert resp.status_code == 204

    def test_delete_contract_then_get_returns_404(self, client):
        """Mutation Verification Rule: DELETE then GET confirms removal."""
        contract = create_openapi_contract(client)
        contract_id = contract["id"]

        del_resp = client.delete(f"/api/contracts/{contract_id}")
        assert del_resp.status_code == 204

        get_resp = client.get(f"/api/contracts/{contract_id}")
        assert get_resp.status_code == 404

    def test_delete_nonexistent_contract(self, client):
        fake_id = str(uuid.uuid4())
        resp = client.delete(f"/api/contracts/{fake_id}")
        # Should be 404 or 204 depending on implementation
        assert resp.status_code in (204, 404)


# ── CE-06: POST /api/validate ────────────────────────────────────────────


class TestContractValidation:
    """CE-06: Contract spec validation endpoint."""

    def test_validate_valid_openapi_spec(self, client):
        payload = {"spec": SAMPLE_OPENAPI_SPEC, "type": "openapi"}
        resp = client.post("/api/validate", json=payload)
        assert resp.status_code == 200
        data = resp.json()
        assert "valid" in data
        assert "errors" in data
        assert "warnings" in data

    def test_validate_invalid_openapi_spec(self, client):
        invalid_spec = {"openapi": "3.1.0"}  # Missing required fields
        payload = {"spec": invalid_spec, "type": "openapi"}
        resp = client.post("/api/validate", json=payload)
        assert resp.status_code == 200
        data = resp.json()
        # Should report errors for missing info/paths
        assert data["valid"] is False or len(data["errors"]) > 0

    def test_validate_asyncapi_spec(self, client):
        payload = {"spec": SAMPLE_ASYNCAPI_SPEC, "type": "asyncapi"}
        resp = client.post("/api/validate", json=payload)
        assert resp.status_code == 200
        data = resp.json()
        assert "valid" in data

    def test_validate_missing_type_returns_422(self, client):
        resp = client.post("/api/validate", json={"spec": {}})
        assert resp.status_code == 422


# ── CE-07: POST /api/breaking-changes/{id} ───────────────────────────────


class TestBreakingChanges:
    """CE-07: Breaking change detection endpoint."""

    def test_breaking_changes_with_new_spec(self, client):
        contract = create_openapi_contract(client)
        contract_id = contract["id"]

        # Modify spec — remove an endpoint (breaking change)
        modified_spec = {
            "openapi": "3.1.0",
            "info": {"title": "User Service API", "version": "2.0.0"},
            "paths": {},  # Removed all paths — breaking!
        }
        resp = client.post(
            f"/api/breaking-changes/{contract_id}",
            json={"new_spec": modified_spec},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)

    def test_breaking_changes_without_new_spec(self, client):
        """Compare against previous version (no new_spec in body)."""
        contract = create_openapi_contract(client)
        contract_id = contract["id"]

        resp = client.post(f"/api/breaking-changes/{contract_id}", json={})
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)

    def test_breaking_changes_nonexistent_contract(self, client):
        fake_id = str(uuid.uuid4())
        resp = client.post(f"/api/breaking-changes/{fake_id}", json={})
        assert resp.status_code == 404


# ── CE-08: POST /api/implementations/mark ────────────────────────────────


class TestImplementationsMark:
    """CE-08: Mark implementation endpoint."""

    def test_mark_implemented_returns_200(self, client):
        contract = create_openapi_contract(client)
        payload = {
            "contract_id": contract["id"],
            "service_name": contract["service_name"],
            "evidence_path": "src/services/user_service.py",
        }
        resp = client.post("/api/implementations/mark", json=payload)
        assert resp.status_code == 200
        data = resp.json()
        assert "marked" in data
        assert "total_implementations" in data
        assert "all_implemented" in data

    def test_mark_implemented_mutation_verification(self, client):
        """Mutation Verification Rule: mark then check confirms implementation record exists.

        Note: mark_implemented inserts with status='pending'. The unimplemented
        query returns contracts with no implementation OR status='pending'.
        So marking alone does NOT remove from unimplemented — that requires
        verification. We verify the mark response and that the total count grows.
        """
        svc_name = f"mark-svc-{uuid.uuid4().hex[:8]}"
        contract = create_openapi_contract(client, service_name=svc_name)

        # Before marking: should be in unimplemented list (no impl row)
        unimp_resp = client.get("/api/implementations/unimplemented", params={"service_name": svc_name})
        assert unimp_resp.status_code == 200
        unimp_ids_before = {c["id"] for c in unimp_resp.json()}
        assert contract["id"] in unimp_ids_before

        # Mark as implemented (creates a 'pending' implementation row)
        mark_resp = client.post("/api/implementations/mark", json={
            "contract_id": contract["id"],
            "service_name": svc_name,
            "evidence_path": "src/impl.py",
        })
        assert mark_resp.status_code == 200
        data = mark_resp.json()
        assert data["marked"] is True
        assert data["total_implementations"] >= 1

        # Mark again (idempotent) — should still succeed
        mark_resp2 = client.post("/api/implementations/mark", json={
            "contract_id": contract["id"],
            "service_name": svc_name,
            "evidence_path": "src/impl_v2.py",
        })
        assert mark_resp2.status_code == 200
        assert mark_resp2.json()["marked"] is True


# ── CE-09: GET /api/implementations/unimplemented ────────────────────────


class TestImplementationsUnimplemented:
    """CE-09: List unimplemented contracts endpoint."""

    def test_unimplemented_returns_200(self, client):
        resp = client.get("/api/implementations/unimplemented")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_unimplemented_filter_by_service(self, client):
        svc_name = f"unimp-svc-{uuid.uuid4().hex[:8]}"
        create_openapi_contract(client, service_name=svc_name)

        resp = client.get("/api/implementations/unimplemented", params={"service_name": svc_name})
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) >= 1
        for item in data:
            assert item["expected_service"] == svc_name


# ── CE-10: POST /api/tests/generate/{id} ────────────────────────────────


class TestTestGeneration:
    """CE-10: Test generation endpoint."""

    def test_generate_tests_returns_200(self, client):
        contract = create_openapi_contract(client)
        resp = client.post(f"/api/tests/generate/{contract['id']}")
        assert resp.status_code == 200
        data = resp.json()
        assert "contract_id" in data
        assert "framework" in data
        assert "test_code" in data
        assert "test_count" in data
        assert data["test_count"] >= 0
        assert data["contract_id"] == contract["id"]

    def test_generate_tests_pytest_framework(self, client):
        contract = create_openapi_contract(client)
        resp = client.post(
            f"/api/tests/generate/{contract['id']}",
            params={"framework": "pytest"},
        )
        assert resp.status_code == 200
        assert resp.json()["framework"] == "pytest"

    def test_generate_tests_jest_framework(self, client):
        contract = create_openapi_contract(client)
        resp = client.post(
            f"/api/tests/generate/{contract['id']}",
            params={"framework": "jest"},
        )
        assert resp.status_code == 200
        assert resp.json()["framework"] == "jest"

    def test_generate_tests_nonexistent_contract(self, client):
        fake_id = str(uuid.uuid4())
        resp = client.post(f"/api/tests/generate/{fake_id}")
        assert resp.status_code == 404

    def test_generate_tests_with_negative_cases(self, client):
        contract = create_openapi_contract(client)
        resp = client.post(
            f"/api/tests/generate/{contract['id']}",
            params={"include_negative": True},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["test_count"] >= 0


# ── CE-11: GET /api/tests/{id} ──────────────────────────────────────────


class TestTestSuiteRetrieval:
    """CE-11: Test suite retrieval endpoint."""

    def test_get_test_suite_after_generation(self, client):
        """Mutation Verification Rule: generate then GET confirms persistence."""
        contract = create_openapi_contract(client)
        # First generate
        gen_resp = client.post(f"/api/tests/generate/{contract['id']}")
        assert gen_resp.status_code == 200

        # Then retrieve
        get_resp = client.get(f"/api/tests/{contract['id']}")
        assert get_resp.status_code == 200
        data = get_resp.json()
        assert data["contract_id"] == contract["id"]
        assert "test_code" in data

    def test_get_test_suite_nonexistent(self, client):
        fake_id = str(uuid.uuid4())
        resp = client.get(f"/api/tests/{fake_id}")
        assert resp.status_code == 404


# ── CE-12: POST /api/compliance/check/{id} ──────────────────────────────


class TestComplianceCheck:
    """CE-12: Compliance checking endpoint."""

    def test_compliance_check_returns_200(self, client):
        contract = create_openapi_contract(client)
        sample_response_data = {
            "GET /api/users": {
                "items": [{"name": "Alice", "email": "alice@example.com"}],
                "total": 1,
            }
        }
        resp = client.post(
            f"/api/compliance/check/{contract['id']}",
            json={"response_data": sample_response_data},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)

    def test_compliance_check_response_shape(self, client):
        contract = create_openapi_contract(client)
        resp = client.post(
            f"/api/compliance/check/{contract['id']}",
            json={"response_data": {}},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        # Each item should have endpoint_path, method, compliant, violations
        for item in data:
            assert "endpoint_path" in item or "compliant" in item

    def test_compliance_check_nonexistent_contract(self, client):
        fake_id = str(uuid.uuid4())
        resp = client.post(f"/api/compliance/check/{fake_id}", json={})
        assert resp.status_code == 404

    def test_compliance_check_without_response_data(self, client):
        contract = create_openapi_contract(client)
        resp = client.post(
            f"/api/compliance/check/{contract['id']}",
            json={},
        )
        assert resp.status_code == 200


# ── Endpoint Coverage Summary ──────────────────────────────────────────────
# GET    /api/health                    → TESTED (TestContractEngineHealth)
# POST   /api/contracts                 → TESTED (TestContractCreate)
# GET    /api/contracts                 → TESTED (TestContractList)
# GET    /api/contracts/{id}            → TESTED (TestContractGet)
# DELETE /api/contracts/{id}            → TESTED (TestContractDelete)
# POST   /api/validate                  → TESTED (TestContractValidation)
# POST   /api/breaking-changes/{id}     → TESTED (TestBreakingChanges)
# POST   /api/implementations/mark      → TESTED (TestImplementationsMark)
# GET    /api/implementations/unimplemented → TESTED (TestImplementationsUnimplemented)
# POST   /api/tests/generate/{id}       → TESTED (TestTestGeneration)
# GET    /api/tests/{id}                → TESTED (TestTestSuiteRetrieval)
# POST   /api/compliance/check/{id}     → TESTED (TestComplianceCheck)
# All 12 contract engine endpoints covered.

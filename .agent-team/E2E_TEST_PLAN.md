# E2E Backend API Test Plan

## Overview

End-to-end API tests for the Super Team platform — 3 FastAPI microservices:
1. **Architect Service** (port 8001) — PRD decomposition, service map, domain model
2. **Contract Engine Service** (port 8002) — Contract CRUD, validation, breaking changes, tests, compliance
3. **Codebase Intelligence Service** (port 8003) — Symbol indexing, dependencies, search, dead code

**Authentication:** NONE — all endpoints are public (no roles/RBAC)

## Test Infrastructure

- **Framework:** pytest + httpx (real HTTP calls, zero mocks)
- **Server startup:** uvicorn per service (ports 8001-8003)
- **Test files:** `tests/e2e/api/`
- **Health check:** `GET /api/health` on each service

## API Workflows

### Workflow 1: Architect Service (tests/e2e/api/test_architect_service.py)

| Step | Method | Endpoint | Expected Status | Verifies |
|------|--------|----------|----------------|----------|
| 1 | GET | /api/health | 200 | Service healthy, DB connected |
| 2 | POST | /api/decompose | 201 | PRD decomposition returns service_map, domain_model, contract_stubs |
| 3 | GET | /api/service-map | 200 | Persisted service map matches decomposition output |
| 4 | GET | /api/domain-model | 200 | Persisted domain model matches decomposition output |

**Negative tests:**
- POST /api/decompose with empty PRD → 422
- POST /api/decompose with short PRD → 422
- POST /api/decompose with missing body → 422
- GET /api/service-map with nonexistent project → 404
- GET /api/domain-model with nonexistent project → 404

### Workflow 2: Contract Engine Service (tests/e2e/api/test_contract_engine_service.py)

| Step | Method | Endpoint | Expected Status | Verifies |
|------|--------|----------|----------------|----------|
| 1 | GET | /api/health | 200 | Service healthy |
| 2 | POST | /api/contracts | 201 | Create OpenAPI contract |
| 3 | GET | /api/contracts | 200 | List contracts (pagination) |
| 4 | GET | /api/contracts/{id} | 200 | Get specific contract |
| 5 | POST | /api/validate | 200 | Validate spec |
| 6 | POST | /api/breaking-changes/{id} | 200 | Detect breaking changes |
| 7 | POST | /api/implementations/mark | 200 | Mark as implemented |
| 8 | GET | /api/implementations/unimplemented | 200 | List unimplemented |
| 9 | POST | /api/tests/generate/{id} | 200 | Generate test suite |
| 10 | GET | /api/tests/{id} | 200 | Retrieve test suite |
| 11 | POST | /api/compliance/check/{id} | 200 | Check compliance |
| 12 | DELETE | /api/contracts/{id} | 204 | Delete contract |

**Negative tests:**
- Create with invalid type → 422
- Create with invalid version → 422
- Get nonexistent contract → 404
- Delete nonexistent contract → 404
- Breaking changes on nonexistent → 404
- Generate tests for nonexistent → 404
- Compliance check on nonexistent → 404

### Workflow 3: Codebase Intelligence Service (tests/e2e/api/test_codebase_intelligence_service.py)

| Step | Method | Endpoint | Expected Status | Verifies |
|------|--------|----------|----------------|----------|
| 1 | GET | /api/health | 200 | Service healthy, ChromaDB connected |
| 2 | POST | /api/artifacts | 200 | Register Python source artifact |
| 3 | GET | /api/symbols | 200 | List symbols from indexed artifact |
| 4 | GET | /api/dependencies | 200 | Get file dependencies |
| 5 | GET | /api/graph/analysis | 200 | Get graph analysis |
| 6 | POST | /api/search | 200 | Semantic search for symbols |
| 7 | GET | /api/dead-code | 200 | Find dead code |

**Negative tests:**
- Register artifact missing file_path → 422
- Get dependencies without file_path → 422
- Search with empty query → 422
- Search with missing query → 422

### Workflow 4: Cross-Service Integration (tests/e2e/api/test_cross_service_workflow.py)

| Step | Method | Endpoint (Service) | Expected | Verifies |
|------|--------|--------------------|----------|----------|
| 1 | POST | /api/decompose (Architect) | 201 | Decompose PRD |
| 2 | POST | /api/contracts (Contract Engine) | 201 | Store contract from decomposition |
| 3 | POST | /api/validate (Contract Engine) | 200 | Validate stored contract |
| 4 | POST | /api/tests/generate/{id} (Contract Engine) | 200 | Generate tests |
| 5 | GET | /api/contracts/{id} (Contract Engine) | 200 | Verify persistence |

## Endpoint Summary

| Service | Endpoints | Test File |
|---------|-----------|-----------|
| Architect | 4 | test_architect_service.py |
| Contract Engine | 12 | test_contract_engine_service.py |
| Codebase Intelligence | 7 | test_codebase_intelligence_service.py |
| Cross-Service | 5 (shared) | test_cross_service_workflow.py |
| **Total Unique** | **23** | **4 files** |

## Test Accounts

No authentication — all endpoints are public. No role-based testing needed.

## Server Lifecycle

1. Start 3 uvicorn instances (ports 8001-8003)
2. Wait for health checks (GET /api/health returning 200)
3. Run pytest tests/e2e/api/
4. Shut down servers

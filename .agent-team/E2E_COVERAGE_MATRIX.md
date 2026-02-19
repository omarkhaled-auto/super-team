# E2E Coverage Matrix

## Architect Service Endpoints

| Req ID | Endpoint | Method | Roles | Test File | Test Written | Test Passed |
|--------|----------|--------|-------|-----------|-------------|-------------|
| ARCH-01 | /api/health | GET | Public | test_architect_service.py | [x] | [x] |
| ARCH-02 | /api/decompose | POST | Public | test_architect_service.py | [x] | [x] |
| ARCH-03 | /api/service-map | GET | Public | test_architect_service.py | [x] | [x] |
| ARCH-04 | /api/domain-model | GET | Public | test_architect_service.py | [x] | [x] |

## Contract Engine Service Endpoints

| Req ID | Endpoint | Method | Roles | Test File | Test Written | Test Passed |
|--------|----------|--------|-------|-----------|-------------|-------------|
| CE-01 | /api/health | GET | Public | test_contract_engine_service.py | [x] | [x] |
| CE-02 | /api/contracts | POST | Public | test_contract_engine_service.py | [x] | [x] |
| CE-03 | /api/contracts | GET | Public | test_contract_engine_service.py | [x] | [x] |
| CE-04 | /api/contracts/{id} | GET | Public | test_contract_engine_service.py | [x] | [x] |
| CE-05 | /api/contracts/{id} | DELETE | Public | test_contract_engine_service.py | [x] | [x] |
| CE-06 | /api/validate | POST | Public | test_contract_engine_service.py | [x] | [x] |
| CE-07 | /api/breaking-changes/{id} | POST | Public | test_contract_engine_service.py | [x] | [x] |
| CE-08 | /api/implementations/mark | POST | Public | test_contract_engine_service.py | [x] | [x] |
| CE-09 | /api/implementations/unimplemented | GET | Public | test_contract_engine_service.py | [x] | [x] |
| CE-10 | /api/tests/generate/{id} | POST | Public | test_contract_engine_service.py | [x] | [x] |
| CE-11 | /api/tests/{id} | GET | Public | test_contract_engine_service.py | [x] | [x] |
| CE-12 | /api/compliance/check/{id} | POST | Public | test_contract_engine_service.py | [x] | [x] |

## Codebase Intelligence Service Endpoints

| Req ID | Endpoint | Method | Roles | Test File | Test Written | Test Passed |
|--------|----------|--------|-------|-----------|-------------|-------------|
| CI-01 | /api/health | GET | Public | test_codebase_intelligence_service.py | [x] | [x] |
| CI-02 | /api/symbols | GET | Public | test_codebase_intelligence_service.py | [x] | [x] |
| CI-03 | /api/dependencies | GET | Public | test_codebase_intelligence_service.py | [x] | [x] |
| CI-04 | /api/graph/analysis | GET | Public | test_codebase_intelligence_service.py | [x] | [x] |
| CI-05 | /api/search | POST | Public | test_codebase_intelligence_service.py | [x] | [x] |
| CI-06 | /api/artifacts | POST | Public | test_codebase_intelligence_service.py | [x] | [x] |
| CI-07 | /api/dead-code | GET | Public | test_codebase_intelligence_service.py | [x] | [x] |

## Cross-Service Workflow

| Req ID | Workflow | Services | Test File | Test Written | Test Passed |
|--------|----------|----------|-----------|-------------|-------------|
| XS-01 | Decompose → Store → Validate → Generate Tests | Architect + Contract Engine | test_cross_service_workflow.py | [x] | [x] |
| XS-02 | Decompose entities and relationships verification | Architect | test_cross_service_workflow.py | [x] | [x] |

## Coverage Summary

## Coverage: 25/25 written (100%) | 25/25 passed (100%)

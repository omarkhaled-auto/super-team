# Backend API E2E Test Results

**Date:** 2026-02-19 (Run 4, Milestone-4 verification)
**Framework:** pytest + httpx (real HTTP calls, zero mocks)
**Services:** 3 FastAPI microservices (Architect, Contract Engine, Codebase Intelligence)
**Duration:** 10.43 seconds
**Python:** 3.12.10 | **pytest:** 9.0.2 | **FastAPI:** 0.129.0 | **httpx:** 0.28.1

## Backend API Tests
Total: 87 | Passed: 87 | Failed: 0

### Fix Applied

One infrastructure issue was resolved before tests could pass:

- **Issue:** `GET /api/graph/analysis` on Codebase Intelligence service returned HTTP 500
- **Root Cause:** `scipy` was not installed. NetworkX's `pagerank()` requires scipy, and the error handler only caught `NetworkXError` and `KeyError`, not `ModuleNotFoundError`
- **Fix:** Installed `scipy` via `pip install scipy`
- **Verification:** Graph analysis endpoint now returns 200 with valid JSON

### Passed

- ✓ TestArchitectHealth::test_health_returns_200: Architect /api/health returns 200
- ✓ TestArchitectHealth::test_health_response_shape: Health response has status, service_name, version, database, uptime_seconds
- ✓ TestArchitectDecompose::test_decompose_returns_201: POST /api/decompose returns 201
- ✓ TestArchitectDecompose::test_decompose_response_has_required_fields: Response has service_map, domain_model, contract_stubs, validation_issues, interview_questions
- ✓ TestArchitectDecompose::test_decompose_service_map_has_services: Service map has >= 1 service
- ✓ TestArchitectDecompose::test_decompose_domain_model_structure: Domain model has entities and relationships
- ✓ TestArchitectDecompose::test_decompose_contract_stubs_are_list: Contract stubs is a list
- ✓ TestArchitectDecompose::test_decompose_empty_prd_returns_422: Empty PRD rejected with 422
- ✓ TestArchitectDecompose::test_decompose_short_prd_returns_422: Short PRD rejected with 422
- ✓ TestArchitectDecompose::test_decompose_missing_body_returns_422: Missing body rejected with 422
- ✓ TestArchitectServiceMap::test_service_map_returns_200_after_decompose: GET /api/service-map returns 200 after decompose
- ✓ TestArchitectServiceMap::test_service_map_response_shape: Response has services, project_name, generated_at
- ✓ TestArchitectServiceMap::test_service_map_unknown_project_returns_404: Unknown project returns 404
- ✓ TestArchitectServiceMap::test_service_map_mutation_verification: Decompose then GET confirms persistence
- ✓ TestArchitectDomainModel::test_domain_model_returns_200_after_decompose: GET /api/domain-model returns 200
- ✓ TestArchitectDomainModel::test_domain_model_response_shape: Response has entities, relationships, generated_at
- ✓ TestArchitectDomainModel::test_domain_model_entities_non_empty: Entities list is non-empty
- ✓ TestArchitectDomainModel::test_domain_model_unknown_project_returns_404: Unknown project returns 404
- ✓ TestArchitectDomainModel::test_domain_model_mutation_verification: Decompose then GET confirms persistence
- ✓ TestCodebaseIntelHealth::test_health_returns_200: CI /api/health returns 200
- ✓ TestCodebaseIntelHealth::test_health_response_shape: Health response includes chroma details
- ✓ TestArtifactRegistration::test_register_python_artifact: POST /api/artifacts returns 200
- ✓ TestArtifactRegistration::test_register_artifact_response_shape: Response is a dict with indexing results
- ✓ TestArtifactRegistration::test_register_artifact_missing_file_path_returns_422: Missing file_path rejected
- ✓ TestArtifactRegistration::test_register_artifact_mutation_verification: Register then GET symbols confirms indexing
- ✓ TestSymbolList::test_symbols_returns_200: GET /api/symbols returns 200
- ✓ TestSymbolList::test_symbols_filter_by_language: Filter by language=python works
- ✓ TestSymbolList::test_symbols_filter_by_kind: Filter by kind=class works
- ✓ TestSymbolList::test_symbols_filter_by_name: Filter by name=AuthService works
- ✓ TestSymbolList::test_symbols_filter_by_service_name: Filter by service_name works
- ✓ TestSymbolList::test_symbols_filter_by_file_path: Filter by file_path works
- ✓ TestDependencies::test_dependencies_returns_200: GET /api/dependencies returns 200
- ✓ TestDependencies::test_dependencies_response_shape: Response has file_path and depth
- ✓ TestDependencies::test_dependencies_custom_depth: Custom depth=3 works
- ✓ TestDependencies::test_dependencies_missing_file_path_returns_422: Missing file_path rejected
- ✓ TestGraphAnalysis::test_graph_analysis_returns_200: GET /api/graph/analysis returns 200
- ✓ TestGraphAnalysis::test_graph_analysis_response_shape: Response has node_count, edge_count as integers
- ✓ TestSemanticSearch::test_search_returns_200: POST /api/search returns 200
- ✓ TestSemanticSearch::test_search_with_filters: Search with language, service_name, top_k filters works
- ✓ TestSemanticSearch::test_search_empty_query_returns_422: Empty query rejected
- ✓ TestSemanticSearch::test_search_missing_query_returns_422: Missing query rejected
- ✓ TestDeadCode::test_dead_code_returns_200: GET /api/dead-code returns 200
- ✓ TestDeadCode::test_dead_code_filter_by_service: Filter by service_name works
- ✓ TestDeadCode::test_dead_code_response_shape: Response entries have symbol_name and file_path
- ✓ TestContractEngineHealth::test_health_returns_200: CE /api/health returns 200
- ✓ TestContractEngineHealth::test_health_response_shape: Health response shape correct
- ✓ TestContractCreate::test_create_openapi_contract_returns_201: POST /api/contracts returns 201
- ✓ TestContractCreate::test_create_contract_without_build_cycle_id: Contract created with null build_cycle_id
- ✓ TestContractCreate::test_create_contract_invalid_type_returns_422: Invalid type rejected
- ✓ TestContractCreate::test_create_contract_invalid_version_returns_422: Invalid version rejected
- ✓ TestContractCreate::test_create_contract_missing_fields_returns_422: Missing fields rejected
- ✓ TestContractCreate::test_create_asyncapi_contract: AsyncAPI contract creation works
- ✓ TestContractList::test_list_contracts_returns_200: GET /api/contracts returns 200
- ✓ TestContractList::test_list_contracts_pagination_shape: Response has items, total, page, page_size
- ✓ TestContractList::test_list_contracts_pagination_params: Pagination parameters respected
- ✓ TestContractList::test_list_contracts_filter_by_service_name: Filter by service_name works
- ✓ TestContractList::test_list_contracts_filter_by_type: Filter by type=openapi works
- ✓ TestContractGet::test_get_contract_returns_200: GET /api/contracts/{id} returns 200
- ✓ TestContractGet::test_get_contract_not_found_returns_404: Nonexistent contract returns 404
- ✓ TestContractGet::test_get_contract_mutation_verification: POST then GET confirms persistence
- ✓ TestContractDelete::test_delete_contract_returns_204: DELETE returns 204
- ✓ TestContractDelete::test_delete_contract_then_get_returns_404: DELETE then GET confirms removal
- ✓ TestContractDelete::test_delete_nonexistent_contract: Delete of nonexistent handled gracefully
- ✓ TestContractValidation::test_validate_valid_openapi_spec: Valid spec returns valid=true
- ✓ TestContractValidation::test_validate_invalid_openapi_spec: Invalid spec returns errors
- ✓ TestContractValidation::test_validate_asyncapi_spec: AsyncAPI validation works
- ✓ TestContractValidation::test_validate_missing_type_returns_422: Missing type rejected
- ✓ TestBreakingChanges::test_breaking_changes_with_new_spec: Breaking change detection works
- ✓ TestBreakingChanges::test_breaking_changes_without_new_spec: Comparison against previous version works
- ✓ TestBreakingChanges::test_breaking_changes_nonexistent_contract: Nonexistent contract returns 404
- ✓ TestImplementationsMark::test_mark_implemented_returns_200: Mark implemented returns 200
- ✓ TestImplementationsMark::test_mark_implemented_mutation_verification: Mark then check confirms record
- ✓ TestImplementationsUnimplemented::test_unimplemented_returns_200: Unimplemented list returns 200
- ✓ TestImplementationsUnimplemented::test_unimplemented_filter_by_service: Filter by service works
- ✓ TestTestGeneration::test_generate_tests_returns_200: Test generation returns 200
- ✓ TestTestGeneration::test_generate_tests_pytest_framework: Pytest framework generation works
- ✓ TestTestGeneration::test_generate_tests_jest_framework: Jest framework generation works
- ✓ TestTestGeneration::test_generate_tests_nonexistent_contract: Nonexistent contract returns 404
- ✓ TestTestGeneration::test_generate_tests_with_negative_cases: Negative case generation works
- ✓ TestTestSuiteRetrieval::test_get_test_suite_after_generation: Generate then GET confirms persistence
- ✓ TestTestSuiteRetrieval::test_get_test_suite_nonexistent: Nonexistent returns 404
- ✓ TestComplianceCheck::test_compliance_check_returns_200: Compliance check returns 200
- ✓ TestComplianceCheck::test_compliance_check_response_shape: Response shape correct
- ✓ TestComplianceCheck::test_compliance_check_nonexistent_contract: Nonexistent returns 404
- ✓ TestComplianceCheck::test_compliance_check_without_response_data: Empty response_data handled
- ✓ TestCrossServiceWorkflow::test_decompose_and_store_contracts: Full cross-service workflow passes
- ✓ TestCrossServiceWorkflow::test_decompose_produces_entities_and_relationships: Entities and relationships produced

### Failed

(none)

## Test Coverage by Service

| Service | Endpoints | Tests | Pass Rate |
|---------|-----------|-------|-----------|
| Architect | 4 | 19 | 100% |
| Contract Engine | 12 | 42 | 100% |
| Codebase Intelligence | 7 | 24 | 100% |
| Cross-Service | N/A | 2 | 100% |
| **Total** | **23** | **87** | **100%** |

## Mutation Verification

All mutation endpoints (POST, PUT, DELETE) have follow-up GET verification:
- POST /api/decompose → GET /api/service-map, GET /api/domain-model
- POST /api/contracts → GET /api/contracts/{id}
- DELETE /api/contracts/{id} → GET /api/contracts/{id} (expect 404)
- POST /api/implementations/mark → GET /api/implementations/unimplemented
- POST /api/tests/generate/{id} → GET /api/tests/{id}
- POST /api/artifacts → GET /api/symbols

## Authentication

No authentication/authorization is implemented. All endpoints are public.
Role-based testing: N/A (skipped — no auth).

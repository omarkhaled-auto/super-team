## Milestone 2: Build 1 to Build 2 MCP Wiring Verification
- ID: milestone-2
- Status: COMPLETE
- Dependencies: milestone-1
- Description: Verify that every MCP tool exposed by Build 1's 3 servers is callable from Build 2's client wrappers. Test session lifecycle, error recovery, retry behavior, and fallback paths.

---

### Overview

Milestone 2 validates the MCP integration layer between Build 1 (Foundation Services) and Build 2 (Builder Fleet). There are 20 MCP tools across 3 servers, 3 client wrappers with 17 methods, and 12 wire-level protocol tests. This milestone is the highest-risk wiring verification due to MCP SDK async patterns and real server process management.

### Estimated Effort
- **LOC**: ~1,000
- **Files**: 2 test files
- **Risk**: HIGH (MCP SDK compatibility, async edge cases, real process spawning)
- **Duration**: 1.5-2.5 hours

---

### MCP Server Inventory

| Server | Module | Tools | Internal Port | External Port |
|--------|--------|-------|---------------|---------------|
| Architect | `src.architect.mcp_server` | 4 | 8000 | 8001 |
| Contract Engine | `src.contract_engine.mcp_server` | 9 | 8000 | 8002 |
| Codebase Intelligence | `src.codebase_intelligence.mcp_server` | 7 | 8000 | 8003 |

### MCP Tool-to-Client Wiring Map (20 SVC entries)

#### Architect (4 tools)

| SVC-ID | Client Method | MCP Tool | Request | Response |
|--------|---------------|----------|---------|----------|
| SVC-001 | `ArchitectClient.decompose(prd_text)` | `decompose` | `{prd_text: str}` | `DecompositionResult {service_map, domain_model, contract_stubs, validation_issues, interview_questions}` |
| SVC-002 | `ArchitectClient.get_service_map()` | `get_service_map` | `None` | `ServiceMap {project_name, services, generated_at, prd_hash, build_cycle_id}` |
| SVC-003 | `ArchitectClient.get_contracts_for_service(service_name)` | `get_contracts_for_service` | `{service_name: str}` | `list[{id, role, type, counterparty, summary}]` |
| SVC-004 | `ArchitectClient.get_domain_model()` | `get_domain_model` | `None` | `DomainModel {entities, relationships, generated_at}` |

#### Contract Engine (9 tools — 6 via client, 3 direct MCP)

| SVC-ID | Client Method | MCP Tool | Request | Response |
|--------|---------------|----------|---------|----------|
| SVC-005 | `ContractEngineClient.get_contract(contract_id)` | `get_contract` | `{contract_id: str}` | `ContractEntry {id, service_name, type, version, spec, spec_hash, status}` |
| SVC-006 | `ContractEngineClient.validate_endpoint(...)` | `validate_endpoint` | `{service_name, method, path, response_body, status_code}` | `ContractValidation {valid, violations}` |
| SVC-007 | `ContractEngineClient.generate_tests(...)` | `generate_tests` | `{contract_id, framework, include_negative}` | `string` |
| SVC-008 | `ContractEngineClient.check_breaking_changes(...)` | `check_breaking_changes` | `{contract_id, new_spec}` | `list[{change_type, path, severity, old_value, new_value, affected_consumers}]` |
| SVC-009 | `ContractEngineClient.mark_implemented(...)` | `mark_implemented` | `{contract_id, service_name, evidence_path}` | `MarkResult {marked, total_implementations, all_implemented}` |
| SVC-010 | `ContractEngineClient.get_unimplemented_contracts(...)` | `get_unimplemented_contracts` | `{service_name: str}` | `list[{id, type, expected_service, version, status}]` |
| SVC-010a | (Build 3 direct) | `create_contract` | contract spec dict | contract entry |
| SVC-010b | (Build 3 direct) | `validate_spec` | spec dict | validation result |
| SVC-010c | (Build 3 direct) | `list_contracts` | optional filters | list of contracts |

#### Codebase Intelligence (7 tools)

| SVC-ID | Client Method | MCP Tool | Request | Response |
|--------|---------------|----------|---------|----------|
| SVC-011 | `CodebaseIntelligenceClient.find_definition(symbol, language)` | `find_definition` | `{symbol, language}` | `DefinitionResult {file_path, line_start, line_end, kind, signature, docstring}` |
| SVC-012 | `CodebaseIntelligenceClient.find_callers(symbol, max_results)` | `find_callers` | `{symbol, max_results}` | `list[{file_path, line, caller_name}]` |
| SVC-013 | `CodebaseIntelligenceClient.find_dependencies(file_path)` | `find_dependencies` | `{file_path}` | `DependencyResult {imports, imported_by, transitive_deps, circular_deps}` |
| SVC-014 | `CodebaseIntelligenceClient.search_semantic(...)` | `search_semantic` | `{query, language, service_name, n_results}` | `list[{chunk_id, file_path, symbol_name, content, score, language, service_name, line_start, line_end}]` |
| SVC-015 | `CodebaseIntelligenceClient.get_service_interface(service_name)` | `get_service_interface` | `{service_name}` | `ServiceInterface {service_name, endpoints, events_published, events_consumed, exported_symbols}` |
| SVC-016 | `CodebaseIntelligenceClient.check_dead_code(service_name)` | `check_dead_code` | `{service_name}` | `list[{symbol_name, file_path, kind, line, service_name, confidence}]` |
| SVC-017 | `CodebaseIntelligenceClient.register_artifact(file_path, service_name)` | `register_artifact` | `{file_path, service_name}` | `ArtifactResult {indexed, symbols_found, dependencies_found, errors}` |

---

### Test Files

#### 1. `tests/run4/test_m2_mcp_wiring.py` (~500 LOC)
**Implements**: REQ-009 through REQ-012, WIRE-001 through WIRE-012, TEST-008

##### MCP Handshake Tests (REQ-009, REQ-010, REQ-011)

| Test | Requirement | Description |
|------|-------------|-------------|
| `test_architect_mcp_handshake` | REQ-009 | Spawn Architect via StdioServerParameters, call `session.initialize()`, verify capabilities include "tools", call `session.list_tools()`, verify exactly 4 tools: {decompose, get_service_map, get_contracts_for_service, get_domain_model} |
| `test_contract_engine_mcp_handshake` | REQ-010 | Spawn Contract Engine, initialize, verify 9 tools: {create_contract, validate_spec, list_contracts, get_contract, validate_endpoint, generate_tests, check_breaking_changes, mark_implemented, get_unimplemented_contracts} |
| `test_codebase_intel_mcp_handshake` | REQ-011 | Spawn Codebase Intelligence, initialize, verify 7 tools: {find_definition, find_callers, find_dependencies, search_semantic, get_service_interface, check_dead_code, register_artifact} |

##### MCP Tool Roundtrip Tests (REQ-012)

| Test | Description |
|------|-------------|
| `test_architect_tool_valid_calls` | Call each of 4 Architect tools with valid params, verify non-error response |
| `test_contract_engine_tool_valid_calls` | Call each of 9 CE tools with valid params, verify non-error response |
| `test_codebase_intel_tool_valid_calls` | Call each of 7 CI tools with valid params, verify non-error response |
| `test_all_tools_invalid_params` | Call each of 20 tools with invalid param types, verify `isError` without crash |
| `test_all_tools_response_parsing` | Parse each response into expected schema, verify field presence and types |

##### Session Lifecycle Tests (WIRE-001 through WIRE-008)

| Test | Wire ID | Description |
|------|---------|-------------|
| `test_session_sequential_calls` | WIRE-001 | Open session, make 10 sequential calls, close; verify all succeed |
| `test_session_crash_recovery` | WIRE-002 | Open session, kill server process, verify client detects broken pipe |
| `test_session_timeout` | WIRE-003 | Simulate slow tool exceeding `mcp_tool_timeout_ms`, verify TimeoutError |
| `test_multi_server_concurrency` | WIRE-004 | Open 3 sessions simultaneously, make parallel calls, verify no conflicts |
| `test_session_restart_data_access` | WIRE-005 | Close session, reopen to same server, verify data access |
| `test_malformed_json_handling` | WIRE-006 | Call tool producing malformed JSON, verify `isError` without crash |
| `test_nonexistent_tool_call` | WIRE-007 | Call `session.call_tool("nonexistent_tool", {})`, verify error response |
| `test_server_exit_detection` | WIRE-008 | Server process exits non-zero, client detects and logs error |

##### Fallback Tests (WIRE-009 through WIRE-011)

| Test | Wire ID | Description |
|------|---------|-------------|
| `test_fallback_contract_engine_unavailable` | WIRE-009 | CE MCP unavailable, Build 2 falls back to `run_api_contract_scan()` |
| `test_fallback_codebase_intel_unavailable` | WIRE-010 | CI MCP unavailable, Build 2 falls back to `generate_codebase_map()` |
| `test_fallback_architect_unavailable` | WIRE-011 | Architect MCP unavailable, standard PRD decomposition proceeds |

##### Cross-Server Test (WIRE-012)

| Test | Wire ID | Description |
|------|---------|-------------|
| `test_architect_cross_server_contract_lookup` | WIRE-012 | Architect's `get_contracts_for_service` internally calls Contract Engine HTTP; verify when both MCP servers and CE FastAPI are running |

##### Latency Benchmark (TEST-008)

| Test | Description |
|------|-------------|
| `test_mcp_tool_latency_benchmark` | Measure round-trip time for each of 20 MCP tools; record median, p95, p99; threshold: <5s per call, <30s server startup (120s for CI first start) |

---

#### 2. `tests/run4/test_m2_client_wrappers.py` (~400 LOC)
**Implements**: REQ-013 through REQ-015

##### ContractEngineClient Tests (REQ-013)

| Test | Description |
|------|-------------|
| `test_ce_client_get_contract_returns_correct_type` | Mock MCP session, verify `get_contract()` returns dict with ContractEntry fields |
| `test_ce_client_validate_endpoint_returns_correct_type` | Verify `validate_endpoint()` returns dict with `valid` and `violations` |
| `test_ce_client_generate_tests_returns_string` | Verify `generate_tests()` returns non-empty string |
| `test_ce_client_check_breaking_returns_list` | Verify `check_breaking_changes()` returns list of change dicts |
| `test_ce_client_mark_implemented_returns_result` | Verify `mark_implemented()` returns MarkResult dict |
| `test_ce_client_get_unimplemented_returns_list` | Verify `get_unimplemented_contracts()` returns list |
| `test_ce_client_safe_defaults_on_error` | All 6 methods return safe defaults on MCP error (never raise) |
| `test_ce_client_retry_3x_backoff` | All methods retry 3 times with exponential backoff (1s, 2s, 4s) |

##### CodebaseIntelligenceClient Tests (REQ-014)

| Test | Description |
|------|-------------|
| `test_ci_client_find_definition_type` | Verify returns DefinitionResult dict |
| `test_ci_client_find_callers_type` | Verify returns list of caller dicts |
| `test_ci_client_find_dependencies_type` | Verify returns DependencyResult dict |
| `test_ci_client_search_semantic_type` | Verify returns list of semantic results |
| `test_ci_client_get_service_interface_type` | Verify returns ServiceInterface dict |
| `test_ci_client_check_dead_code_type` | Verify returns list of dead code dicts |
| `test_ci_client_register_artifact_type` | Verify returns ArtifactResult dict |
| `test_ci_client_safe_defaults` | All 7 methods return safe defaults on error |
| `test_ci_client_retry_pattern` | 3-retry pattern with exponential backoff verified |

##### ArchitectClient Tests (REQ-015)

| Test | Description |
|------|-------------|
| `test_arch_client_decompose_returns_result` | Verify returns DecompositionResult dict |
| `test_arch_client_get_service_map_type` | Verify returns ServiceMap dict |
| `test_arch_client_get_contracts_type` | Verify returns list of contract dicts |
| `test_arch_client_get_domain_model_type` | Verify returns DomainModel dict |
| `test_arch_client_decompose_failure_returns_none` | `decompose()` returns None on failure (fallback path) |

---

### Test Matrix Mapping (B1 + B2 entries for M2)

| Matrix ID | Test Function | Priority |
|-----------|---------------|----------|
| B1-05 | `test_ce_tool_generate_tests` | P1 |
| B1-06 | `test_codebase_indexing_perf` | P2 |
| B1-07 | `test_all_tools_valid_calls` | P0 |
| B1-08 | `test_ci_dead_code_planted` | P1 |
| B1-09 | `test_architect_mcp_handshake` | P0 |
| B1-10 | `test_contract_engine_mcp_handshake` | P0 |
| B1-11 | `test_codebase_intel_mcp_handshake` | P0 |
| B1-12 | `test_architect_tool_count` | P0 |
| B1-13 | `test_contract_engine_tool_count` | P0 |
| B1-14 | `test_codebase_intel_tool_count` | P0 |
| B1-15 | `test_all_tools_invalid_params` | P0 |
| B1-16 | `test_nonexistent_tool_call` | P1 |
| B1-17 | `test_session_crash_recovery` | P0 |
| B1-18 | `test_multi_server_concurrency` | P0 |
| B1-19 | `test_architect_cross_server_contract_lookup` | P1 |
| B2-07 | `test_fallback_contract_engine_unavailable` | P0 |
| B2-08 | `test_fallback_codebase_intel_unavailable` | P0 |
| X-01 | `test_mcp_b1_to_b2_contract_engine` | P0 |
| X-02 | `test_mcp_b1_to_b2_codebase_intel` | P0 |

---

### SVC Wiring Checklist

- [x] SVC-001: ArchitectClient.decompose() -> Architect MCP decompose (review_cycles: 1)
- [x] SVC-002: ArchitectClient.get_service_map() -> Architect MCP get_service_map (review_cycles: 1)
- [x] SVC-003: ArchitectClient.get_contracts_for_service() -> Architect MCP get_contracts_for_service (review_cycles: 1)
- [x] SVC-004: ArchitectClient.get_domain_model() -> Architect MCP get_domain_model (review_cycles: 1)
- [x] SVC-005: ContractEngineClient.get_contract() -> Contract Engine MCP get_contract (review_cycles: 1)
- [x] SVC-006: ContractEngineClient.validate_endpoint() -> Contract Engine MCP validate_endpoint (review_cycles: 1)
- [x] SVC-007: ContractEngineClient.generate_tests() -> Contract Engine MCP generate_tests (review_cycles: 1)
- [x] SVC-008: ContractEngineClient.check_breaking_changes() -> Contract Engine MCP check_breaking_changes (review_cycles: 1)
- [x] SVC-009: ContractEngineClient.mark_implemented() -> Contract Engine MCP mark_implemented (review_cycles: 1)
- [x] SVC-010: ContractEngineClient.get_unimplemented_contracts() -> Contract Engine MCP get_unimplemented_contracts (review_cycles: 1)
- [x] SVC-010a: Build 3 Integrator -> Contract Engine MCP create_contract (review_cycles: 1)
- [x] SVC-010b: Build 3 Integrator -> Contract Engine MCP validate_spec (review_cycles: 1)
- [x] SVC-010c: Build 3 Integrator -> Contract Engine MCP list_contracts (review_cycles: 1)
- [x] SVC-011: CodebaseIntelligenceClient.find_definition() -> CI MCP find_definition (review_cycles: 1)
- [x] SVC-012: CodebaseIntelligenceClient.find_callers() -> CI MCP find_callers (review_cycles: 1)
- [x] SVC-013: CodebaseIntelligenceClient.find_dependencies() -> CI MCP find_dependencies (review_cycles: 1)
- [x] SVC-014: CodebaseIntelligenceClient.search_semantic() -> CI MCP search_semantic (review_cycles: 1)
- [x] SVC-015: CodebaseIntelligenceClient.get_service_interface() -> CI MCP get_service_interface (review_cycles: 1)
- [x] SVC-016: CodebaseIntelligenceClient.check_dead_code() -> CI MCP check_dead_code (review_cycles: 1)
- [x] SVC-017: CodebaseIntelligenceClient.register_artifact() -> CI MCP register_artifact (review_cycles: 1)

---

### Dependencies on Milestone 1

| M1 Output | M2 Usage |
|-----------|----------|
| `Run4Config` | MCP timeout values, build paths |
| `conftest.py` fixtures | `mock_mcp_session`, `make_mcp_result`, server params |
| `sample_prd.md` | Input for Architect decompose roundtrip test |
| `mcp_health.py` | `check_mcp_health()` for handshake tests |

### Risk Analysis

| Risk | Impact | Mitigation |
|------|--------|------------|
| MCP SDK `mcp.ClientSession` API changes | Tests fail to compile | Pin mcp>=1.25,<2.0 |
| ChromaDB model download on first CI start | 120s+ startup | Use `mcp_first_start_timeout_ms: 120000` |
| Architect HTTP call to CE in WIRE-012 | Connection refused | Ensure Docker Compose up before test |
| Windows pipe handling differs from Unix | Broken pipe detection differs | Use platform-agnostic error checks |
| Concurrent MCP sessions exhaust resources | WIRE-004 flaky | Limit to 3 sessions max |

### Gate Condition

**Milestone 2 is COMPLETE when**: All REQ-009 through REQ-015, WIRE-001 through WIRE-012, and TEST-008 tests pass. Combined with M3 completion, this unblocks M4.

---

### Requirement Verification Checklist

- [x] REQ-009: Architect MCP handshake — `TestArchitectMCPHandshake` (2 tests) (review_cycles: 1)
- [x] REQ-010: Contract Engine MCP handshake — `TestContractEngineMCPHandshake` (2 tests) (review_cycles: 1)
- [x] REQ-011: Codebase Intelligence MCP handshake — `TestCodebaseIntelMCPHandshake` (2 tests) (review_cycles: 1)
- [x] REQ-012: Tool roundtrip tests — `TestArchitectToolValidCalls` (4), `TestContractEngineToolValidCalls` (9), `TestCodebaseIntelToolValidCalls` (7), `TestAllToolsInvalidParams` (1), `TestAllToolsResponseParsing` (5) (review_cycles: 1)
- [x] REQ-013: ContractEngineClient tests — 8 test classes (get_contract, validate_endpoint, generate_tests, check_breaking, mark_implemented, get_unimplemented, safe_defaults, retry) (review_cycles: 1)
- [x] REQ-014: CodebaseIntelligenceClient tests — 9 test classes (find_definition, find_callers, find_dependencies, search_semantic, get_service_interface, check_dead_code, register_artifact, safe_defaults, retry) (review_cycles: 1)
- [x] REQ-015: ArchitectClient tests — 5 test classes (decompose, service_map, contracts, domain_model, decompose_failure) (review_cycles: 1)
- [x] WIRE-001: Session sequential calls — `TestSessionSequentialCalls` (review_cycles: 1)
- [x] WIRE-002: Session crash recovery — `TestSessionCrashRecovery` (review_cycles: 1)
- [x] WIRE-003: Session timeout — `TestSessionTimeout` (review_cycles: 1)
- [x] WIRE-004: Multi-server concurrency — `TestMultiServerConcurrency` (review_cycles: 1)
- [x] WIRE-005: Session restart data access — `TestSessionRestartDataAccess` (review_cycles: 1)
- [x] WIRE-006: Malformed JSON handling — `TestMalformedJsonHandling` (review_cycles: 1)
- [x] WIRE-007: Nonexistent tool call — `TestNonexistentToolCall` (review_cycles: 1)
- [x] WIRE-008: Server exit detection — `TestServerExitDetection` (review_cycles: 1)
- [x] WIRE-009: Fallback CE unavailable — `TestFallbackContractEngineUnavailable` (2 tests) (review_cycles: 1)
- [x] WIRE-010: Fallback CI unavailable — `TestFallbackCodebaseIntelUnavailable` (2 tests) (review_cycles: 1)
- [x] WIRE-011: Fallback Architect unavailable — `TestFallbackArchitectUnavailable` (review_cycles: 1)
- [x] WIRE-012: Cross-server contract lookup — `TestArchitectCrossServerContractLookup` (review_cycles: 1)
- [x] TEST-008: MCP tool latency benchmark — `TestMCPToolLatencyBenchmark` (review_cycles: 1)

### Additional Verifications

- [x] check_mcp_health integration — `TestCheckMCPHealthIntegration` (2 tests: healthy + timeout) (review_cycles: 1)
- [x] MCP client module importability — `TestArchitectMCPClientWiring`, `TestContractEngineMCPClientWiring` (review_cycles: 1)
- [x] MCP server module discoverability — `TestMCPServerToolRegistration` (3 tests) (review_cycles: 1)
- [x] Client function signatures verified — `test_architect_mcp_client_signature`, `test_ce_create_contract_signature`, etc. (review_cycles: 1)

### Test Results

- **Total M2 tests**: 81
- **Passing**: 81
- **Failing**: 0
- **M1 regression check**: 31/31 M1 tests still passing
- **Total run4 suite**: 112/112 passing

### Contracts (Module Exports for M2)

M2 creates NO new source modules. All output is test code:

| File | Exports | Purpose |
|------|---------|---------|
| `tests/run4/test_m2_mcp_wiring.py` | 49 test functions across 19 test classes | MCP wiring, lifecycle, fallback, benchmark |
| `tests/run4/test_m2_client_wrappers.py` | 32 test functions across 22 test classes | Client wrapper type, error, retry, import verification |

### M2 Consumes from M1

| M1 Export | M2 Usage | Verified |
|-----------|----------|----------|
| `Run4Config` | `run4_config` fixture used in timeout tests | [x] |
| `conftest.py:make_mcp_result` | Used throughout both test files | [x] |
| `conftest.py:MockToolResult` | Used throughout both test files | [x] |
| `conftest.py:MockTextContent` | Used in malformed JSON test | [x] |
| `conftest.py:mock_mcp_session` | Available but M2 builds custom mocks | [x] |
| `conftest.py:architect_params` | Used in handshake and health check tests | [x] |
| `conftest.py:contract_engine_params` | Used in handshake tests | [x] |
| `conftest.py:codebase_intel_params` | Used in handshake tests | [x] |
| `conftest.py:sample_prd_text` | Used in decompose roundtrip tests | [x] |
| `mcp_health.check_mcp_health` | Used in health integration tests | [x] |

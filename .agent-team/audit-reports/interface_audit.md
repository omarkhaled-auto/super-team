# Interface Audit Report

**Auditor**: Interface Auditor (Automated — Claude Opus 4.6)
**Date**: 2026-02-19 (re-audited)
**Scope**: All WIRE-xxx, SVC-xxx, INT-xxx requirements across Milestones 1–6
**Project**: Super-Team (Run 4 Verification Pipeline)

---

## Executive Summary

| Category | Total | Verified PASS | NOT_IMPLEMENTED | Issues Found |
|----------|-------|---------------|-----------------|-------------|
| INT-xxx (Integration) | 7 | 7 | 0 | 0 |
| SVC-xxx (Service Wiring) | 23 | 23 | 0 | 2 |
| WIRE-xxx (Protocol Wiring) | 21 | 17 | 4 | 4 |
| Orphan Detection | N/A | N/A | N/A | 13 |
| **Totals** | **51** | **47** | **4** | **19** |

**Overall Severity Breakdown**: 6 CRITICAL, 5 HIGH, 2 MEDIUM, 1 LOW, 5 INFO

> **Finding Count**: 19 findings total (FINDING-001 through FINDING-019)

> **Note on SVC counts**: M2 requirements show SVC-018 to SVC-020 as unchecked `[ ]` in the
> M3 wiring checklist, but source + test implementations are fully present. All 23 SVC items
> are verified PASS. M3 checklist status is stale (see FINDING-012).

---

## SECTION 1: INT-xxx (Integration Requirements) — Milestone 1

### INT-001: Session-Scoped Test Fixtures
- **Requirement**: `tests/run4/conftest.py` provides session-scoped fixtures for `run4_config`, `sample_prd_text`, `build1_root`, `contract_engine_params`, `architect_params`, `codebase_intel_params`
- **Source**: `tests/run4/conftest.py` (lines 68–141)
- **Consumers**: `test_m1_infrastructure.py`, `test_m2_mcp_wiring.py`, `test_m2_client_wrappers.py`
- **Verification**: PASS — All 6 fixtures exist with `@pytest.fixture(scope="session")`. `run4_config` imports `Run4Config` from `src.run4.config`. Five of six are directly consumed in M1/M2 test files; `build1_root` is structurally available.
- **Status**: ✅ VERIFIED

### INT-002: Mock MCP Session Fixture
- **Requirement**: `conftest.py` provides `mock_mcp_session` returning `AsyncMock` with `initialize`, `list_tools`, `call_tool`
- **Source**: `tests/run4/conftest.py` (lines 148–178)
- **Consumers**: `test_m1_infrastructure.py::TestMockMcpSession` (5 test methods)
- **Verification**: PASS — Fixture exists, returns properly configured AsyncMock with all three methods.
- **Status**: ✅ VERIFIED

### INT-003: Mock MCP Result Helper
- **Requirement**: `make_mcp_result(data, is_error)` builds mock MCP tool results with `TextContent` containing JSON
- **Source**: `tests/run4/conftest.py` (lines 47–61), plus `MockToolResult` (32–36) and `MockTextContent` (39–44)
- **Consumers**: `test_m1_infrastructure.py`, `test_m2_mcp_wiring.py` (30+ call sites), `test_m2_client_wrappers.py` (20+ call sites)
- **Verification**: PASS — Most heavily consumed interface in the test suite.
- **Status**: ✅ VERIFIED

### INT-004: HTTP Health Polling
- **Requirement**: `poll_until_healthy()` in `src/run4/mcp_health.py` polls HTTP health endpoints
- **Source**: `src/run4/mcp_health.py` (lines 15–95)
- **Signature**: `async def poll_until_healthy(service_urls, timeout_s=120, interval_s=3.0, required_consecutive=2) -> dict[str, dict]`
- **Consumers**: `test_m1_infrastructure.py::TestPollUntilHealthy` (2 async tests)
- **Verification**: PASS — Uses `httpx.AsyncClient` for real HTTP GET polling. Raises `TimeoutError` on deadline expiry.
- **Status**: ✅ VERIFIED

### INT-005: MCP Server Health Check
- **Requirement**: `check_mcp_health()` in `src/run4/mcp_health.py` spawns MCP server, initializes, lists tools
- **Source**: `src/run4/mcp_health.py` (lines 98–145)
- **Signature**: `async def check_mcp_health(server_params, timeout=30.0) -> dict`
- **Consumers**: `test_m2_mcp_wiring.py::TestCheckMCPHealthIntegration` (2 tests)
- **Verification**: PASS — Uses lazy MCP SDK imports (`mcp.ClientSession`, `mcp.client.stdio.stdio_client`). Returns dict with `status`, `tools_count`, `tool_names`, `error`.
- **Status**: ✅ VERIFIED

### INT-006: Builder State Parser
- **Requirement**: `parse_builder_state(output_dir)` in `src/run4/builder.py` reads `.agent-team/STATE.json`
- **Source**: `src/run4/builder.py` (lines 61–121)
- **Signature**: `def parse_builder_state(output_dir: Path) -> dict`
- **Consumers**: Internal — called by `_state_to_builder_result()`, `invoke_builder()`, `run_parallel_builders()`, `feed_violations_to_builder()`. Tested indirectly via M3 builder invocation tests.
- **Verification**: PASS — Returns dict with 7 keys: `success`, `test_passed`, `test_total`, `convergence_ratio`, `total_cost`, `health`, `completed_phases`. Graceful degradation on missing/corrupt files.
- **Status**: ✅ VERIFIED

### INT-007: Regression Detector
- **Requirement**: `detect_regressions(before, after)` in `src/run4/fix_pass.py` compares violation snapshots
- **Source**: `src/run4/fix_pass.py` (lines 13–48)
- **Signature**: `def detect_regressions(before: dict[str, list[str]], after: dict[str, list[str]]) -> list[dict]`
- **Consumers**: `test_m1_infrastructure.py::TestDetectRegressions` (4 test methods)
- **Verification**: PASS — Computes set differences per category. Returns list of `{category, violation}` dicts.
- **Status**: ✅ VERIFIED

**INT Section Summary: 7/7 PASS**

---

## SECTION 2: SVC-xxx (Service-to-API Wiring) — Milestones 2–3

### SVC-001 through SVC-004: ArchitectClient → Architect MCP

**File**: `src/architect/mcp_client.py`

| SVC-ID | Method | MCP Tool | Real `call_tool`? | Mock/Fake Data? | Verdict |
|--------|--------|----------|-------------------|-----------------|---------|
| SVC-001 | `decompose(prd_text)` | `decompose` | ✅ via `_call()` → `session.call_tool("decompose", ...)` | None | **PASS** |
| SVC-002 | `get_service_map(project_name)` | `get_service_map` | ✅ via `_call()` → `session.call_tool("get_service_map", ...)` | None | **PASS** |
| SVC-003 | `get_contracts_for_service(service_name)` | `get_contracts_for_service` | ✅ via `_call()` → `session.call_tool(...)` | None | **PASS** |
| SVC-004 | `get_domain_model(project_name)` | `get_domain_model` | ✅ via `_call()` → `session.call_tool(...)` | None | **PASS** |

**Server-side**: All 4 tools registered via `@mcp.tool()` in `src/architect/mcp_server.py`. Backed by real service layer with SQLite storage.

**Call pattern**: All methods use 3-retry exponential backoff. Safe defaults on exhaustion, never fake data.

> **Note**: `decompose_prd_basic()` (line 196) returns a hardcoded fallback structure, but this is explicitly the WIRE-011 fallback path, not the SVC-001 production path.

---

### SVC-005 through SVC-010: ContractEngineClient → Contract Engine MCP

**File**: `src/contract_engine/mcp_client.py`

| SVC-ID | Method | MCP Tool | Real `call_tool`? | Mock/Fake Data? | Verdict |
|--------|--------|----------|-------------------|-----------------|---------|
| SVC-005 | `get_contract(contract_id)` | `get_contract` | ✅ via `_retry_call()` → `session.call_tool(...)` | None | **PASS** |
| SVC-006 | `validate_endpoint(...)` | `validate_endpoint` | ✅ via `_retry_call()` → `session.call_tool(...)` | None | **PASS** |
| SVC-007 | `generate_tests(...)` | `generate_tests` | ✅ via `_retry_call()` → `session.call_tool(...)` | None | **PASS** |
| SVC-008 | `check_breaking_changes(...)` | `check_breaking_changes` | ✅ via `_retry_call()` → `session.call_tool(...)` | None | **PASS** |
| SVC-009 | `mark_implemented(...)` | `mark_implemented` | ✅ via `_retry_call()` → `session.call_tool(...)` | None | **PASS** |
| SVC-010 | `get_unimplemented_contracts(...)` | `get_unimplemented_contracts` | ✅ via `_retry_call()` → `session.call_tool(...)` | None | **PASS** |

**Server-side**: 10 tools registered in `src/contract_engine/mcp_server.py` (9 required + 1 extra `check_compliance`). Real `ContractStore`, `ImplementationTracker`, `VersionManager` backed by SQLite at `./data/contracts.db`. See FINDING-018 for tool count discrepancy.

---

### SVC-010a through SVC-010c: Contract Engine MCP Server Direct Tools

**File**: `src/contract_engine/mcp_server.py`

| SVC-ID | MCP Tool | Line | Delegates To | Verdict |
|--------|----------|------|--------------|---------|
| SVC-010a | `create_contract` | 63 | `_contract_store.upsert(create_obj)` | **PASS** |
| SVC-010b | `validate_spec` | 160 | `validate_openapi(spec)` / `validate_asyncapi(spec)` | **PASS** |
| SVC-010c | `list_contracts` | 106 | `_contract_store.list(...)` | **PASS** |

---

### SVC-011 through SVC-017: CodebaseIntelligenceClient → CI MCP

**File**: `src/codebase_intelligence/mcp_client.py`

| SVC-ID | Method | MCP Tool | Real `call_tool`? | Mock/Fake Data? | Verdict |
|--------|--------|----------|-------------------|-----------------|---------|
| SVC-011 | `find_definition(symbol, language)` | `find_definition` | ✅ via `_call_tool()` → `session.call_tool(...)` | None | **PASS** |
| SVC-012 | `find_callers(symbol, max_results)` | `find_callers` | ✅ via `_call_tool()` → `session.call_tool(...)` | None | **PASS** |
| SVC-013 | `find_dependencies(file_path)` | `find_dependencies` | ✅ via `_call_tool()` → `session.call_tool(...)` | None | **PASS** |
| SVC-014 | `search_semantic(...)` | `search_semantic` | ✅ via `_call_tool()` → `session.call_tool(...)` | None | **PASS** |
| SVC-015 | `get_service_interface(service_name)` | `get_service_interface` | ✅ via `_call_tool()` → `session.call_tool(...)` | None | **PASS** |
| SVC-016 | `check_dead_code(service_name)` | `check_dead_code` | ✅ via `_call_tool()` → `session.call_tool(...)` | None | **PASS** |
| SVC-017 | `register_artifact(file_path, service_name)` | `register_artifact` | ✅ via `_call_tool()` → `session.call_tool(...)` | None | **PASS** |

**Server-side**: 8 tools registered in `src/codebase_intelligence/mcp_server.py` (7 required + 1 extra `analyze_graph`). Backed by `SymbolDB`, `GraphDB` (SQLite), and `ChromaStore` (ChromaDB). See FINDING-019 for tool count discrepancy.

---

### SVC-018 through SVC-020: Builder Subprocess Wiring (M3)

**File**: `src/run4/builder.py`

| SVC-ID | Function | Mechanism | Verdict |
|--------|----------|-----------|---------|
| SVC-018 | `invoke_builder(cwd, depth, timeout_s, env)` | `asyncio.create_subprocess_exec(sys.executable, "-m", "agent_team", ...)` | **PASS** |
| SVC-019 | `feed_violations_to_builder(cwd, violations, timeout_s)` | `write_fix_instructions()` then `invoke_builder(cwd, depth="quick")` | **PASS** |
| SVC-020 | `generate_builder_config(service_name, output_dir, ...)` | `yaml.dump(config_dict)` writes `config.yaml` | **PASS** |

**Rejection criteria scan**: No `of()`, `mockData`, `fakeData`, or hardcoded array returns found in any of the 7 source files.

**SVC Section Summary: 23/23 PASS for implemented items**

---

## SECTION 3: WIRE-xxx (Protocol Wiring) — Milestones 2–4

### WIRE-001 to WIRE-008: MCP Session Lifecycle (M2)

**File**: `tests/run4/test_m2_mcp_wiring.py`

| Wire ID | Test Function | Substantive? | Verdict |
|---------|--------------|-------------|---------|
| WIRE-001 | `test_session_sequential_calls` (line 808) | ✅ 10 sequential calls, asserts `not result.isError`, verifies `call_count == 10` | **PASS** |
| WIRE-002 | `test_session_crash_recovery` (line 825) | ✅ Replaces call_tool with `BrokenPipeError`, asserts `pytest.raises(BrokenPipeError)` | **PASS** |
| WIRE-003 | `test_session_timeout` (line 845) | ✅ Injects `asyncio.sleep(10)`, wraps in `asyncio.timeout(0.1)`, asserts `TimeoutError` | **PASS** |
| WIRE-004 | `test_multi_server_concurrency` (line 866) | ✅ 3 sessions, `asyncio.gather`, asserts no errors | **PASS** |
| WIRE-005 | `test_session_restart_data_access` (line 898) | ✅ Session1 writes, Session2 reads, asserts data preserved + negative test | **PASS** |
| WIRE-006 | `test_malformed_json_handling` (line 993) | ✅ Returns `"{not valid json!!!"`, asserts `isError` + `json.JSONDecodeError` | **PASS** |
| WIRE-007 | `test_nonexistent_tool_call` (line 1015) | ✅ Calls `"nonexistent_tool"`, asserts `result.isError` | **PASS** |
| WIRE-008 | `test_server_exit_detection` (line 1034) | ✅ `ConnectionError("Server process exited with code 1")`, asserts caught | **PASS** |

---

### WIRE-009 to WIRE-011: Fallback Tests (M2)

**File**: `tests/run4/test_m2_mcp_wiring.py`

| Wire ID | Test Function | Verdict |
|---------|--------------|---------|
| WIRE-009 | `test_fallback_contract_engine_unavailable` (line 1057) | **PASS** — Patches `run_api_contract_scan`, verifies fallback invoked + result shape |
| WIRE-010 | `test_fallback_codebase_intel_unavailable` (line 1113) | **PASS** — Patches `generate_codebase_map`, verifies fallback + negative test |
| WIRE-011 | `test_fallback_architect_unavailable` (line 1205) | **PASS** — Patches `decompose_prd_basic`, verifies fallback + negative test |

Each has supplementary companion tests (fallback output validation, "not called when MCP available").

---

### WIRE-012: Cross-Server Contract Lookup (M2)

| Wire ID | Test Function | Verdict |
|---------|--------------|---------|
| WIRE-012 | `test_architect_cross_server_contract_lookup` (line 1302) | **PASS** — Patches `httpx.Client`, verifies HTTP call to `http://localhost:8002/api/contracts/...`. Plus 2 companion tests for full client-to-server chain and configurable URL. |

---

### WIRE-013 to WIRE-016, WIRE-021: Builder Wiring (M3)

**File**: `tests/run4/test_m3_builder_invocation.py`

| Wire ID | Test Function | Verdict |
|---------|--------------|---------|
| WIRE-013 | `test_agent_teams_fallback_cli_unavailable` (line 580) | **PASS** — Patches `shutil.which` → `None`, asserts `CLIBackend` + warning logged |
| WIRE-014 | `test_agent_teams_hard_failure_no_fallback` (line 623) | **PASS** — `fallback_to_cli=False`, asserts `RuntimeError` raised |
| WIRE-015 | `test_builder_timeout_enforcement` (line 655) | **PASS** — `SlowProc` sleeping 100s, verifies `proc.kill()` and `proc.wait()` called. 3 variants. |
| WIRE-016 | `test_builder_environment_isolation` (line 799) | **PASS** — Verifies `ANTHROPIC_API_KEY` NOT in subprocess env, `PATH` IS present |
| WIRE-021 | `test_agent_teams_positive_path` (line 843) | **PASS** — `AgentTeamsBackend.execute_wave()` with task state progression verification |

---

### WIRE-017 to WIRE-020: Docker/Network Wiring (M4 — NOT IMPLEMENTED)

| Wire ID | Expected File | Verdict |
|---------|--------------|---------|
| WIRE-017 | `tests/run4/test_m4_health_checks.py` | **NOT_IMPLEMENTED** |
| WIRE-018 | `tests/run4/test_m4_health_checks.py` | **NOT_IMPLEMENTED** |
| WIRE-019 | `tests/run4/test_m4_health_checks.py` | **NOT_IMPLEMENTED** |
| WIRE-020 | `tests/run4/test_m4_health_checks.py` | **NOT_IMPLEMENTED** |

All M4 test files are missing. M4 status is PENDING.

**WIRE Section Summary: 17/17 PASS (implemented), 4 NOT_IMPLEMENTED (M4 pending)**

---

## SECTION 4: Orphan Detection

### FINDING-001: Missing M4 Test Files (CRITICAL)
- **Severity**: CRITICAL
- **Category**: Missing integration test files
- **Details**: The following test files required by M4 do not exist:
  - `tests/run4/test_m4_pipeline_e2e.py` — blocks REQ-021 to REQ-025, TEST-011, TEST-012
  - `tests/run4/test_m4_health_checks.py` — blocks REQ-021, WIRE-017 to WIRE-020
  - `tests/run4/test_m4_contract_compliance.py` — blocks REQ-026 to REQ-028, SEC-001 to SEC-003
- **Impact**: M4 gate condition is unachievable. All 3 files must be created.
- **Recommendation**: Create all 3 test files as specified in M4 REQUIREMENTS.md.

### FINDING-002: Missing M5 Test File (CRITICAL)
- **Severity**: CRITICAL
- **Category**: Missing test file
- **Details**: `tests/run4/test_m5_fix_pass.py` does not exist.
- **Impact**: Blocks REQ-029 to REQ-033, TECH-007, TECH-008, TEST-013 to TEST-015. M5 gate is unachievable.
- **Recommendation**: Create test file as specified in M5 REQUIREMENTS.md.

### FINDING-003: Missing M6 Test File (CRITICAL)
- **Severity**: CRITICAL
- **Category**: Missing test file
- **Details**: `tests/run4/test_m6_audit.py` does not exist.
- **Impact**: Blocks REQ-034 to REQ-042, TECH-009, TEST-016 to TEST-018. M6 gate is unachievable.
- **Recommendation**: Create test file as specified in M6 REQUIREMENTS.md.

### FINDING-004: Missing M5 Source Implementations in fix_pass.py (CRITICAL)
- **Severity**: CRITICAL
- **Category**: Missing source implementations
- **Details**: `src/run4/fix_pass.py` is still a 48-line M1 stub. The following M5-required exports are completely absent:
  - `classify_priority(finding)` (REQ-030)
  - `FixPassResult` dataclass (REQ-031, REQ-032)
  - `execute_fix_pass(state, config, pass_number)` (REQ-031)
  - `check_convergence(state, config, pass_results)` (REQ-033)
  - `compute_convergence(remaining_p0, remaining_p1, remaining_p2, initial_total_weighted)` (TECH-007)
  - `take_violation_snapshot(scan_results)` (TECH-008)
  - `run_fix_loop(state, config)` (REQ-031, REQ-033)
- **Impact**: M5 cannot proceed. 7 functions required by the milestone are missing.
- **Recommendation**: Expand `fix_pass.py` from stub to full implementation per M5 REQUIREMENTS.md.

### FINDING-005: Missing M6 Source Implementations in scoring.py (CRITICAL)
- **Severity**: CRITICAL
- **Category**: Missing source implementations (stub module)
- **Details**: `src/run4/scoring.py` is a 24-line stub exporting only `compute_scores(findings, weights) -> {}`. The following M6-required exports are absent:
  - `SystemScore` dataclass (REQ-034)
  - `compute_system_score(...)` (REQ-034)
  - `IntegrationScore` dataclass (REQ-035)
  - `compute_integration_score(...)` (REQ-035)
  - `AggregateScore` dataclass (REQ-036)
  - `compute_aggregate(...)` (REQ-036)
  - `THRESHOLDS` dict (TECH-009)
  - `is_good_enough(...)` (TECH-009)
- **Impact**: M6 gate unachievable. Module is fully orphaned (zero imports).
- **Recommendation**: Expand `scoring.py` per M6 REQUIREMENTS.md.

### FINDING-006: Missing M6 Source Implementations in audit_report.py (CRITICAL)
- **Severity**: CRITICAL
- **Category**: Missing source implementations (stub module)
- **Details**: `src/run4/audit_report.py` is a 25-line stub exporting only `generate_report(state, output_path) -> str`. The following M6-required exports are absent:
  - `generate_audit_report(state, scores, ...)` (REQ-037)
  - `build_rtm(build_prds, implementations, test_results)` (REQ-038)
  - `build_interface_matrix(mcp_test_results)` (REQ-039)
  - `build_flow_coverage(flow_test_results)` (REQ-040)
  - `test_dark_corners(config, state)` (REQ-041)
  - `build_cost_breakdown(state)` (REQ-042)
- **Impact**: M6 gate unachievable. Module is fully orphaned (zero imports).
- **Recommendation**: Expand `audit_report.py` per M6 REQUIREMENTS.md.

### FINDING-007: Orphaned Module — execution_backend.py (HIGH)
- **Severity**: HIGH
- **Category**: Production-orphaned module
- **Details**: `src/run4/execution_backend.py` (194 lines) defines `AgentTeamsConfig`, `ExecutionBackend`, `CLIBackend`, `AgentTeamsBackend`, and `create_execution_backend()`. This module is:
  - Imported ONLY by `tests/run4/test_m3_builder_invocation.py`
  - NOT imported by any production source file
  - NOT mentioned in any REQUIREMENTS.md
  - The production pipeline (`src/super_orchestrator/pipeline.py`) imports from `agent_team.execution`, a different third-party path
- **Impact**: The module appears to be a shadow/parallel implementation of `agent_team.execution`. It is used only in tests, which may be testing the wrong module.
- **Recommendation**: Clarify whether tests should exercise the real `agent_team.execution` module or this shadow copy. If the shadow, wire it into production. If the real one, update test imports.

### FINDING-008: Missing Docker Compose Overlay Files (HIGH)
- **Severity**: HIGH
- **Category**: Missing infrastructure files
- **Details**: M4 TECH-004 requires a 5-file Docker Compose merge architecture:
  - `docker-compose.infra.yml` — **MISSING**
  - `docker-compose.build1.yml` — **MISSING**
  - `docker-compose.traefik.yml` — **MISSING**
  - `docker-compose.generated.yml` — **MISSING** (generated at runtime)
  - `docker/docker-compose.run4.yml` — **MISSING**
  Only a single `docker-compose.yml` exists at project root.
- **Impact**: M4 Docker architecture cannot be tested. TECH-004 and WIRE-017 through WIRE-020 are blocked.
- **Recommendation**: Create overlay compose files per M4 REQUIREMENTS.md.

### FINDING-009: Missing Regression Test File (HIGH)
- **Severity**: HIGH
- **Category**: Missing test file
- **Details**: `tests/run4/test_regression.py` is referenced in MASTER_PLAN.md (line 278) but does not exist.
- **Impact**: No regression test file to verify M6 regression requirements.
- **Recommendation**: Create file or remove from MASTER_PLAN.md reference if superseded.

### FINDING-010: Fully Orphaned scoring.py and audit_report.py (HIGH)
- **Severity**: HIGH
- **Category**: Orphaned modules (zero imports)
- **Details**: Both `src/run4/scoring.py` and `src/run4/audit_report.py` have exactly zero consumers anywhere in the codebase. They are not imported by any test file, any other source file, or any conftest. They exist solely as M1 stubs awaiting M6 expansion.
- **Impact**: These modules serve no functional purpose in their current state.
- **Recommendation**: These will naturally resolve when M6 is implemented and test files import them.

### FINDING-011: Orphaned __version__ Export (LOW)
- **Severity**: LOW
- **Category**: Unused export
- **Details**: `src/run4/__init__.py` declares `__version__ = "1.0.0"` (line 7) which is never imported or referenced anywhere in the project.
- **Impact**: Minimal — cosmetic. Standard practice to have `__version__` even if unused.
- **Recommendation**: No action required, or add to `pyproject.toml` metadata.

### FINDING-012: M3 Milestone Status Inconsistency (INFO)
- **Severity**: INFO
- **Category**: Requirements status observation
- **Details**: M3 REQUIREMENTS.md states `Status: PENDING`, but test files `test_m3_builder_invocation.py` and `test_m3_config_generation.py` exist and all WIRE-013 through WIRE-016, WIRE-021 tests are fully implemented with substantive assertions. SVC-018 to SVC-020 are also fully implemented in `src/run4/builder.py`.
- **Impact**: Status may be stale. The SVC wiring checklist in M3 still shows `[ ]` (unchecked) for SVC-018, SVC-019, SVC-020.
- **Recommendation**: Update M3 status to COMPLETE and check off SVC-018, SVC-019, SVC-020 in the wiring checklist.

### FINDING-013: build1_root Fixture Consumption (INFO)
- **Severity**: INFO
- **Category**: Wiring observation
- **Details**: The `build1_root` session-scoped fixture (INT-001) is declared in `tests/run4/conftest.py` but is not directly referenced by name in any of the M1 or M2 test files. It is available to all tests in the `tests/run4/` directory by pytest fixture injection.
- **Impact**: None — the fixture will be consumed when M3/M4 tests use it.
- **Recommendation**: No action required. M3/M4 tests will consume this fixture.

### FINDING-014: Architect MCP Fallback Returns Hardcoded Structure (INFO)
- **Severity**: INFO
- **Category**: Wiring observation
- **Details**: `decompose_prd_basic()` in `src/architect/mcp_client.py` (line 196) returns a hardcoded fallback structure. This is explicitly the WIRE-011 fallback path for when the MCP server is unavailable. The `ArchitectClient.decompose()` method (SVC-001) does NOT use this path.
- **Impact**: None — correct design pattern for fallback behavior.
- **Recommendation**: No action required.

### FINDING-015: Contract Engine MCP Client Has Dual Implementation (INFO)
- **Severity**: INFO
- **Category**: Wiring observation
- **Details**: `src/contract_engine/mcp_client.py` provides both class-based methods (`ContractEngineClient`) and module-level bare functions (lines 388-698). Both paths open `stdio_client` transport and call `session.call_tool(...)`. This is a backward-compatible design.
- **Impact**: None — both paths reach real MCP calls.
- **Recommendation**: No action required.

### FINDING-016: Docker Compose Run4 Overlay Not Created (INFO)
- **Severity**: INFO
- **Category**: Wiring observation
- **Details**: `docker/docker-compose.run4.yml` is specified in M4 REQUIREMENTS.md as a NEW file to create, containing network definitions, Traefik labels, and service overrides. This file does not yet exist, consistent with M4 PENDING status.
- **Impact**: Addressed under FINDING-008.
- **Recommendation**: Will be addressed when M4 is implemented.

### FINDING-017: M5/M6 Dependencies Structurally Blocked (INFO)
- **Severity**: INFO
- **Category**: Wiring observation
- **Details**: The dependency chain M4 → M5 → M6 means all three are structurally blocked. M5 needs M4's defect data; M6 needs M5's fix pass results. Since M4's test files, M5's source implementations, and M6's source implementations all don't exist, the entire downstream chain is inoperable.
- **Impact**: Expected given milestone statuses.
- **Recommendation**: Implement milestones in order: M4, then M5, then M6.

### FINDING-018: Contract Engine MCP Server Has 10 Tools vs 9 Required (MEDIUM)
- **Severity**: MEDIUM
- **Category**: Tool count discrepancy
- **Details**: M2 REQUIREMENTS.md specifies 9 tools for the Contract Engine MCP server: `create_contract`, `validate_spec`, `list_contracts`, `get_contract`, `validate_endpoint`, `generate_tests`, `check_breaking_changes`, `mark_implemented`, `get_unimplemented_contracts`. The actual server at `src/contract_engine/mcp_server.py` registers **10 tools** — the 9 required plus an additional `check_compliance` tool (line 332). The handshake test in `test_m2_mcp_wiring.py` defines `CONTRACT_ENGINE_TOOLS` as a 9-element set with a comment noting the discrepancy. The MCP unit test in `test_contract_engine_mcp.py` asserts `len(tools) == 10`.
- **Impact**: The M2 handshake test (`test_contract_engine_mcp_handshake`) must verify "exactly 9 tools" per REQ-010. If it checks for 9 and server returns 10, test fails. If it checks for 10, it contradicts REQ-010. The `check_compliance` tool has no SVC-xxx ID and no client wrapper method.
- **Recommendation**: Either (a) add SVC-010d for `check_compliance` to the requirements and update REQ-010 to expect 10 tools, or (b) document the extra tool as an extension and adjust the handshake assertion to `>= 9`.

### FINDING-019: Codebase Intelligence MCP Server Has 8 Tools vs 7 Required (MEDIUM)
- **Severity**: MEDIUM
- **Category**: Tool count discrepancy
- **Details**: M2 REQUIREMENTS.md specifies 7 tools for the Codebase Intelligence MCP server: `find_definition`, `find_callers`, `find_dependencies`, `search_semantic`, `get_service_interface`, `check_dead_code`, `register_artifact`. The actual server at `src/codebase_intelligence/mcp_server.py` registers **8 tools** — the 7 required plus an additional `analyze_graph` tool (line 317). The handshake test in `test_m2_mcp_wiring.py` defines `CODEBASE_INTEL_TOOLS` as a 7-element set with a comment noting the discrepancy. The MCP unit test in `test_codebase_intel_mcp.py` asserts `len(tools) == 8`.
- **Impact**: Same as FINDING-018 — potential assertion conflict between requirement (7 tools) and implementation (8 tools). The `analyze_graph` tool has no SVC-xxx ID and no client wrapper method.
- **Recommendation**: Either (a) add SVC-017a for `analyze_graph` to the requirements and update REQ-011 to expect 8 tools, or (b) document the extra tool as an extension and adjust the handshake assertion to `>= 7`.

---

## SECTION 5: Consolidated Finding Index

| Finding ID | Severity | Category | Summary |
|-----------|----------|----------|---------|
| FINDING-001 | CRITICAL | Missing files | M4 test files missing (3 files) |
| FINDING-002 | CRITICAL | Missing files | M5 test file missing |
| FINDING-003 | CRITICAL | Missing files | M6 test file missing |
| FINDING-004 | CRITICAL | Missing impl | fix_pass.py M5 functions absent (7 functions) |
| FINDING-005 | CRITICAL | Missing impl | scoring.py M6 exports absent (8 exports) |
| FINDING-006 | CRITICAL | Missing impl | audit_report.py M6 exports absent (6 exports) |
| FINDING-007 | HIGH | Orphaned module | execution_backend.py has no production consumer |
| FINDING-008 | HIGH | Missing files | Docker Compose overlay files missing (4 files) |
| FINDING-009 | HIGH | Missing files | test_regression.py missing |
| FINDING-010 | HIGH | Orphaned modules | scoring.py and audit_report.py have zero imports |
| FINDING-011 | LOW | Unused export | `__version__` never imported |
| FINDING-012 | INFO | Status inconsistency | M3 shows PENDING but is fully implemented |
| FINDING-013 | INFO | Observation | build1_root fixture awaiting M3/M4 consumption |
| FINDING-014 | INFO | Observation | Architect fallback correctly uses hardcoded structure |
| FINDING-015 | INFO | Observation | CE client has dual (class + module) implementation |
| FINDING-016 | INFO | Observation | docker-compose.run4.yml not yet created (M4 pending) |
| FINDING-017 | INFO | Observation | M4 → M5 → M6 chain structurally blocked |
| FINDING-018 | MEDIUM | Tool count discrepancy | CE server has 10 tools vs 9 required (extra: `check_compliance`) |
| FINDING-019 | MEDIUM | Tool count discrepancy | CI server has 8 tools vs 7 required (extra: `analyze_graph`) |

---

## SECTION 6: Verification Matrix

### Integration Requirements (INT-xxx)

| ID | Source | Target | Mechanism | Status |
|----|--------|--------|-----------|--------|
| INT-001 | `conftest.py` | M1/M2 tests | pytest fixture injection | ✅ VERIFIED |
| INT-002 | `conftest.py` | M1 tests | pytest fixture injection | ✅ VERIFIED |
| INT-003 | `conftest.py` | M1/M2 tests | direct import | ✅ VERIFIED |
| INT-004 | `mcp_health.py` | M1 tests | `from src.run4.mcp_health import` | ✅ VERIFIED |
| INT-005 | `mcp_health.py` | M2 tests | `from src.run4.mcp_health import` | ✅ VERIFIED |
| INT-006 | `builder.py` | internal | internal call chain | ✅ VERIFIED |
| INT-007 | `fix_pass.py` | M1 tests | `from src.run4.fix_pass import` | ✅ VERIFIED |

### Service Wiring (SVC-xxx)

| ID | Client | MCP Tool | Real Call? | Status |
|----|--------|----------|-----------|--------|
| SVC-001 | ArchitectClient.decompose | decompose | ✅ | VERIFIED |
| SVC-002 | ArchitectClient.get_service_map | get_service_map | ✅ | VERIFIED |
| SVC-003 | ArchitectClient.get_contracts_for_service | get_contracts_for_service | ✅ | VERIFIED |
| SVC-004 | ArchitectClient.get_domain_model | get_domain_model | ✅ | VERIFIED |
| SVC-005 | ContractEngineClient.get_contract | get_contract | ✅ | VERIFIED |
| SVC-006 | ContractEngineClient.validate_endpoint | validate_endpoint | ✅ | VERIFIED |
| SVC-007 | ContractEngineClient.generate_tests | generate_tests | ✅ | VERIFIED |
| SVC-008 | ContractEngineClient.check_breaking_changes | check_breaking_changes | ✅ | VERIFIED |
| SVC-009 | ContractEngineClient.mark_implemented | mark_implemented | ✅ | VERIFIED |
| SVC-010 | ContractEngineClient.get_unimplemented | get_unimplemented_contracts | ✅ | VERIFIED |
| SVC-010a | (server) | create_contract | ✅ | VERIFIED |
| SVC-010b | (server) | validate_spec | ✅ | VERIFIED |
| SVC-010c | (server) | list_contracts | ✅ | VERIFIED |
| SVC-011 | CIClient.find_definition | find_definition | ✅ | VERIFIED |
| SVC-012 | CIClient.find_callers | find_callers | ✅ | VERIFIED |
| SVC-013 | CIClient.find_dependencies | find_dependencies | ✅ | VERIFIED |
| SVC-014 | CIClient.search_semantic | search_semantic | ✅ | VERIFIED |
| SVC-015 | CIClient.get_service_interface | get_service_interface | ✅ | VERIFIED |
| SVC-016 | CIClient.check_dead_code | check_dead_code | ✅ | VERIFIED |
| SVC-017 | CIClient.register_artifact | register_artifact | ✅ | VERIFIED |
| SVC-018 | invoke_builder | subprocess | ✅ | VERIFIED |
| SVC-019 | feed_violations_to_builder | subprocess+file | ✅ | VERIFIED |
| SVC-020 | generate_builder_config | yaml.dump | ✅ | VERIFIED |

### Protocol Wiring (WIRE-xxx)

| ID | Milestone | Test Exists | Substantive | Status |
|----|-----------|------------|-------------|--------|
| WIRE-001 | M2 | ✅ | ✅ | VERIFIED |
| WIRE-002 | M2 | ✅ | ✅ | VERIFIED |
| WIRE-003 | M2 | ✅ | ✅ | VERIFIED |
| WIRE-004 | M2 | ✅ | ✅ | VERIFIED |
| WIRE-005 | M2 | ✅ | ✅ | VERIFIED |
| WIRE-006 | M2 | ✅ | ✅ | VERIFIED |
| WIRE-007 | M2 | ✅ | ✅ | VERIFIED |
| WIRE-008 | M2 | ✅ | ✅ | VERIFIED |
| WIRE-009 | M2 | ✅ | ✅ | VERIFIED |
| WIRE-010 | M2 | ✅ | ✅ | VERIFIED |
| WIRE-011 | M2 | ✅ | ✅ | VERIFIED |
| WIRE-012 | M2 | ✅ | ✅ | VERIFIED |
| WIRE-013 | M3 | ✅ | ✅ | VERIFIED |
| WIRE-014 | M3 | ✅ | ✅ | VERIFIED |
| WIRE-015 | M3 | ✅ | ✅ | VERIFIED |
| WIRE-016 | M3 | ✅ | ✅ | VERIFIED |
| WIRE-017 | M4 | ❌ | N/A | NOT_IMPLEMENTED |
| WIRE-018 | M4 | ❌ | N/A | NOT_IMPLEMENTED |
| WIRE-019 | M4 | ❌ | N/A | NOT_IMPLEMENTED |
| WIRE-020 | M4 | ❌ | N/A | NOT_IMPLEMENTED |
| WIRE-021 | M3 | ✅ | ✅ | VERIFIED |

---

## SECTION 7: Overall Assessment

### What's Working (M1, M2, M3)
- **All 7 INT-xxx requirements**: Fully implemented, correctly wired, and consumed by tests.
- **All 23 SVC-xxx requirements**: Every MCP client method makes real `session.call_tool()` calls. Every MCP server tool is registered with `@mcp.tool()` and backed by real storage. Every builder function uses real subprocess invocation. Zero mock/fake data in production paths.
- **17/17 implemented WIRE-xxx requirements**: All session lifecycle, fallback, cross-server, and builder wiring tests are substantive with real assertions. No stubs.

### What's Missing (M4, M5, M6)
- **5 test files**: M4 (3 files), M5 (1 file), M6 (1 file) — all structurally required for gate conditions.
- **21 source functions/classes**: 7 in fix_pass.py (M5), 8 in scoring.py (M6), 6 in audit_report.py (M6).
- **4 Docker Compose overlay files**: Required by M4 TECH-004.
- **4 WIRE tests**: WIRE-017 through WIRE-020 (M4 Docker/network wiring).

### Risk Assessment
The M1-M3 implementation is **production-quality** with 100% wiring verification pass rate. The M4-M6 gap is entirely consistent with their PENDING status — no partial or broken implementations exist that would cause runtime errors. The transition from M3 to M4 is clean.

**Biggest risk**: `src/run4/execution_backend.py` (FINDING-007) — tests may be exercising a shadow module instead of the real `agent_team.execution` module. This should be investigated before M3 is officially marked COMPLETE.

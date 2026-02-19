# PRD Reconciliation Report

> **Generated**: 2026-02-19 (Updated — Run 4 Phase)
> **Scope**: Run 4 — End-to-End Integration, Verification & Audit
> **PRD Sources**: MASTER_PLAN.md, milestone-1 through milestone-6 REQUIREMENTS.md, UI_REQUIREMENTS.md
> **Method**: Automated codebase inspection — file existence, grep counts, AST-level field verification

---

## VERIFIED (claim matches implementation)

### Source File Structure (src/run4/)

- **Claim: 8 source files in src/run4/**: PRD lists `__init__.py`, `config.py`, `state.py`, `mcp_health.py`, `builder.py`, `fix_pass.py`, `scoring.py`, `audit_report.py`. **Found 9 files** — all 8 claimed files exist PLUS `execution_backend.py` (not in PRD). Extra file is NOT a mismatch.
  - Files: `src/run4/__init__.py`, `src/run4/config.py`, `src/run4/state.py`, `src/run4/mcp_health.py`, `src/run4/builder.py`, `src/run4/fix_pass.py`, `src/run4/scoring.py`, `src/run4/audit_report.py`, `src/run4/execution_backend.py`

- **Claim: `__version__ = "1.0.0"` in `src/run4/__init__.py`**: VERIFIED. Exact string present.
  - File: `src/run4/__init__.py`

- **Claim: `Run4Config` dataclass with 19 fields + `from_yaml` classmethod + `__post_init__` validation**: VERIFIED. All 19 fields present (build1_project_root, build2_project_root, build3_project_root, output_dir, compose_project_name, docker_compose_files, health_check_timeout_s, health_check_interval_s, mcp_startup_timeout_ms, mcp_tool_timeout_ms, mcp_first_start_timeout_ms, max_concurrent_builders, builder_timeout_s, builder_depth, max_fix_passes, fix_effectiveness_floor, regression_rate_ceiling, max_budget_usd, sample_prd_path). `from_yaml()` classmethod and `__post_init__()` validation both present.
  - File: `src/run4/config.py`

- **Claim: `Finding` dataclass with 10 fields**: VERIFIED. All 10 fields present (finding_id, priority, system, component, evidence, recommendation, resolution, fix_pass_number, fix_verification, created_at).
  - File: `src/run4/state.py`

- **Claim: `Run4State` dataclass with 15 fields + 4 methods (`save`, `load`, `add_finding`, `next_finding_id`)**: VERIFIED. All 15 fields and 4 methods present with atomic write (tmp+rename) pattern for save.
  - File: `src/run4/state.py`

- **Claim: `poll_until_healthy` and `check_mcp_health` async functions**: VERIFIED. Both fully implemented.
  - File: `src/run4/mcp_health.py`

- **Claim: `BuilderResult` dataclass with 12 fields**: VERIFIED. All 12 fields present (service_name, success, test_passed, test_total, convergence_ratio, total_cost, health, completed_phases, exit_code, stdout, stderr, duration_s).
  - File: `src/run4/builder.py`

- **Claim: 6 functions in builder.py**: VERIFIED. All 6 present: `invoke_builder`, `run_parallel_builders`, `generate_builder_config`, `parse_builder_state`, `feed_violations_to_builder`, `write_fix_instructions`.
  - File: `src/run4/builder.py`

- **Claim: `fix_pass.py` has `classify_priority`, `execute_fix_pass`, `check_convergence`, `compute_convergence`, `take_violation_snapshot`, `detect_regressions`**: VERIFIED. All 6 functions present and fully implemented.
  - File: `src/run4/fix_pass.py`

- **Claim: `FixPassMetrics` dataclass in fix_pass.py**: VERIFIED. Present with 9 fields.
  - File: `src/run4/fix_pass.py`

- **Claim: `ConvergenceResult` dataclass in fix_pass.py**: VERIFIED. Present with 5 fields (should_stop, reason, convergence_score, is_hard_stop, is_soft_convergence).
  - File: `src/run4/fix_pass.py`

- **Claim: `check_convergence()` has 5 hard stop conditions**: VERIFIED. Exactly 5: (1) P0==0 AND P1==0, (2) max_fix_passes reached, (3) budget exhausted, (4) effectiveness below floor, (5) regression rate above ceiling.
  - File: `src/run4/fix_pass.py`

- **Claim: `SystemScore` dataclass with 8 scoring dimensions + traffic_light**: VERIFIED. All fields present (system_name, functional_completeness, test_health, contract_compliance, code_quality, docker_health, documentation, total, traffic_light).
  - File: `src/run4/scoring.py`

- **Claim: `IntegrationScore` dataclass with 4 scoring dimensions + total + traffic_light**: VERIFIED. All fields present (mcp_connectivity, data_flow_integrity, contract_fidelity, pipeline_completion, total, traffic_light).
  - File: `src/run4/scoring.py`

- **Claim: `AggregateScore` dataclass with 6 fields**: VERIFIED. All present (build1, build2, build3, integration, aggregate, traffic_light).
  - File: `src/run4/scoring.py`

- **Claim: `THRESHOLDS` dict with 8 entries**: VERIFIED. All 8 present (per_system_minimum=60, integration_minimum=50, aggregate_minimum=65, p0_remaining_max=0, p1_remaining_max=3, test_pass_rate_min=0.85, mcp_tool_coverage_min=0.90, fix_convergence_min=0.70).
  - File: `src/run4/scoring.py`

- **Claim: `compute_system_score`, `compute_integration_score`, `compute_aggregate`, `is_good_enough` functions**: VERIFIED. All 4 present.
  - File: `src/run4/scoring.py`

- **Claim: Aggregate formula = build1*0.30 + build2*0.25 + build3*0.25 + integration*0.20**: VERIFIED. Exact formula implemented.
  - File: `src/run4/scoring.py`

- **Claim: `audit_report.py` has 6 functions**: VERIFIED. All present: `generate_audit_report`, `build_rtm`, `build_interface_matrix`, `build_flow_coverage`, `test_dark_corners`, `build_cost_breakdown`.
  - File: `src/run4/audit_report.py`

- **Claim: Audit report has 7 sections**: VERIFIED. Sections: Executive Summary, Methodology, Per-System Assessment, Integration Assessment, Fix Pass History, Gap Analysis, Appendices.
  - File: `src/run4/audit_report.py`

- **Claim: Audit report has 4 appendices**: VERIFIED. Appendices: A (RTM), B (Violations), C (Test Results), D (Cost Breakdown).
  - File: `src/run4/audit_report.py`

- **Claim: 5 primary data flows in flow coverage**: VERIFIED. Exactly 5: User registration, User login, Order creation (JWT), Order event notification, Notification delivery.
  - File: `src/run4/audit_report.py`

- **Claim: 5 dark corner tests**: VERIFIED. Exactly 5: MCP startup race, Docker DNS resolution, Concurrent builder conflicts, State machine resume, Large PRD handling.
  - File: `src/run4/audit_report.py`

### Fixture Files (tests/run4/fixtures/)

- **Claim: 5 fixture files**: VERIFIED. All 5 present: `sample_prd.md`, `sample_openapi_auth.yaml`, `sample_openapi_order.yaml`, `sample_asyncapi_order.yaml`, `sample_pact_auth.json`.
  - Path: `tests/run4/fixtures/`

- **Claim: sample_prd.md describes 3 services (auth-service, order-service, notification-service)**: VERIFIED. All 3 services with all claimed endpoints.
  - auth-service: POST /register, POST /login, GET /users/me, GET /health (4 endpoints)
  - order-service: POST /orders, GET /orders/{id}, PUT /orders/{id}, GET /health (4 endpoints)
  - notification-service: POST /notify, GET /notifications, GET /health (3 endpoints)
  - File: `tests/run4/fixtures/sample_prd.md`

- **Claim: 3 data models in PRD (User, Order, Notification)**: VERIFIED. All 3 models plus OrderItem present.
  - File: `tests/run4/fixtures/sample_prd.md`

- **Claim: sample_openapi_auth.yaml is OpenAPI 3.1 with 4 endpoints and JWT securityScheme**: VERIFIED.
  - File: `tests/run4/fixtures/sample_openapi_auth.yaml`

- **Claim: sample_openapi_order.yaml is OpenAPI 3.1 with 4 endpoints and JWT securityScheme**: VERIFIED.
  - File: `tests/run4/fixtures/sample_openapi_order.yaml`

- **Claim: sample_asyncapi_order.yaml is AsyncAPI 3.0 with 2 channels (order/created, order/shipped)**: VERIFIED.
  - File: `tests/run4/fixtures/sample_asyncapi_order.yaml`

- **Claim: sample_pact_auth.json is Pact V4 with consumer=order-service, provider=auth-service**: VERIFIED.
  - File: `tests/run4/fixtures/sample_pact_auth.json`

### MCP Servers and Clients

- **Claim: Architect MCP server has exactly 4 tools (decompose, get_service_map, get_contracts_for_service, get_domain_model)**: VERIFIED. Exactly 4 tools registered.
  - File: `src/architect/mcp_server.py`

- **Claim: ArchitectClient with 4 methods**: VERIFIED. All 4 present (decompose, get_service_map, get_contracts_for_service, get_domain_model).
  - File: `src/architect/mcp_client.py`

- **Claim: CodebaseIntelligenceClient with 7 methods**: VERIFIED. All 7 present (find_definition, find_callers, find_dependencies, search_semantic, get_service_interface, check_dead_code, register_artifact).
  - File: `src/codebase_intelligence/mcp_client.py`

### Test Infrastructure

- **Claim: conftest.py has 7 session-scoped fixtures**: VERIFIED. All present: run4_config, sample_prd_text, build1_root, contract_engine_params, architect_params, codebase_intel_params, mock_mcp_session.
  - File: `tests/run4/conftest.py`

- **Claim: conftest.py has MockToolResult, MockTextContent, make_mcp_result**: VERIFIED. All 3 present.
  - File: `tests/run4/conftest.py`

### Test File Existence and Counts (M1, M2, M3, M5, M6)

- **Claim: test_m1_infrastructure.py implements TEST-001 through TEST-007**: VERIFIED. **36 test functions** across 9 test classes. Exceeds PRD minimum.
  - File: `tests/run4/test_m1_infrastructure.py`

- **Claim: test_m2_mcp_wiring.py covers REQ-009-012, WIRE-001-012, TEST-008**: VERIFIED. **61 test functions** across 22 test classes (PRD claimed ~49 across ~19).
  - File: `tests/run4/test_m2_mcp_wiring.py`

- **Claim: test_m2_client_wrappers.py covers REQ-013-015**: VERIFIED. **41 test functions** across 26 test classes (PRD claimed ~32 across ~22).
  - File: `tests/run4/test_m2_client_wrappers.py`

- **Claim: test_m3_builder_invocation.py covers REQ-016-020, WIRE-013-016, WIRE-021**: VERIFIED. **24 test functions** across 11 test classes.
  - File: `tests/run4/test_m3_builder_invocation.py`

- **Claim: test_m3_config_generation.py covers SVC-020, TEST-009, TEST-010**: VERIFIED. **11 test functions** across 5 test classes.
  - File: `tests/run4/test_m3_config_generation.py`

- **Claim: test_m5_fix_pass.py covers REQ-029-033, TECH-007, TECH-008, TEST-013-015**: VERIFIED. **45 test functions** across 8 test classes (PRD claimed 17).
  - File: `tests/run4/test_m5_fix_pass.py`

- **Claim: test_m6_audit.py covers REQ-034-042, TECH-009, TEST-016-018**: VERIFIED. **36 test functions** across 9 test classes (PRD claimed 26).
  - File: `tests/run4/test_m6_audit.py`

### Milestone Structure

- **Claim: 6 milestones (M1-M6)**: VERIFIED. All 6 milestone directories exist under `.agent-team/milestones/`.
  - Paths: `milestone-1/` through `milestone-6/`

### Build 1 Port Assignments

- **Claim: Architect=8001, Contract Engine=8002, Codebase Intelligence=8003**: VERIFIED.
  - File: `docker-compose.yml` (root)

---

## MISMATCH (claim does NOT match implementation)

### MISMATCH-001: Missing 4 Milestone 4 test files

- **PRD says**: 3 test files for M4: `test_m4_pipeline_e2e.py` (7 tests), `test_m4_health_checks.py` (5 tests), `test_m4_contract_compliance.py` (9 tests), plus `test_regression.py`.
- **Found**: **0 of 4 files exist**. No files matching `test_m4_*` or `test_regression*` in `tests/run4/`.
- **Impact**: 21+ test functions missing. Blocks verification of REQ-021 through REQ-028, WIRE-017-020, TECH-004-006, SEC-001-003, TEST-011, TEST-012.
- Files: `tests/run4/` directory

### MISMATCH-002: Missing 5 tiered Docker Compose files

- **PRD says (TECH-004)**: 5-file Docker Compose merge architecture:
  1. `docker/docker-compose.infra.yml` — Tier 0: postgres (16-alpine), redis (7-alpine)
  2. `docker/docker-compose.build1.yml` — Tier 1: architect, contract-engine, codebase-intelligence
  3. `docker/docker-compose.traefik.yml` — Tier 2: traefik (v3.6)
  4. `docker/docker-compose.generated.yml` — Tier 3: auth/order/notification (runtime)
  5. `docker/docker-compose.run4.yml` — Tier 4: cross-build wiring overrides (NEW)
- **Found**: **0 of 5 tiered files exist**. Only a single monolithic `docker-compose.yml` at project root with Build 1 services. No postgres, redis, or traefik in any compose file. No `docker/` directory contains compose files.
- **Impact**: Blocks TECH-004 (5-file merge), WIRE-017 (network architecture), WIRE-018 (inter-container DNS), WIRE-019 (Traefik routing), WIRE-020 (health cascade), SEC-002 (Traefik dashboard), SEC-003 (docker socket).
- Files: `docker-compose.yml` (root), `docker/` directory

### MISMATCH-003: `run_fix_loop` function does not exist

- **PRD says (M5 REQUIREMENTS)**: `run_fix_loop()` function should exist in `src/run4/fix_pass.py` as the main orchestrator: "take initial violation snapshot, for each pass execute fix pass, track metrics, check convergence".
- **Found**: Function **does not exist**. The file has `execute_fix_pass()` for a single pass but no loop orchestrator wrapping multiple passes.
- **Impact**: The convergence loop that runs multiple fix passes until convergence is not implemented as a standalone function.
- File: `src/run4/fix_pass.py`

### MISMATCH-004: `FixPassResult` has 18 fields, PRD claims 11 named fields

- **PRD says (M5 REQUIREMENTS)**: `FixPassResult` should have fields: `pass_number`, `violations_before`, `violations_after`, `fixes_attempted`, `fixes_resolved`, `regressions` (list[dict]), `fix_effectiveness` (float), `regression_rate` (float), `new_defect_discovery_rate` (int), `score_delta` (float), `cost` (float), `duration_s` (float) — 12 fields.
- **Found**: Actual `FixPassResult` has **18 direct fields** with a different structure. The PRD's 12 named fields map to the implementation as follows:
  - `pass_number` -> `pass_number` (direct)
  - `violations_before` -> NOT a direct field (embedded in `metrics.total_before`)
  - `violations_after` -> NOT a direct field (embedded in `metrics.total_after`)
  - `fixes_attempted` -> `fixes_generated` (renamed)
  - `fixes_resolved` -> `fixes_verified` (renamed)
  - `regressions` -> `regressions_found` (int, not list[dict] as claimed)
  - `fix_effectiveness` -> `metrics.fix_effectiveness` (nested)
  - `regression_rate` -> `metrics.regression_rate` (nested)
  - `new_defect_discovery_rate` -> `metrics.new_defect_discovery_rate` (nested)
  - `score_delta` -> `metrics.score_delta` (nested)
  - `cost` -> `cost_usd` (renamed)
  - `duration_s` -> `duration_s` (direct)
- **Additional fields**: `status`, `steps_completed`, `p0_count`, `p1_count`, `p2_count`, `p3_count`, `fixes_applied`, `convergence` (ConvergenceResult), `snapshot_before`, `snapshot_after`.
- **Classification**: Structural mismatch — the implementation uses nested dataclasses (`FixPassMetrics`, `ConvergenceResult`) instead of flat fields.
- File: `src/run4/fix_pass.py`

### MISMATCH-005: Soft convergence conditions — PRD claims 4, implementation has 1

- **PRD says (REQ-033)**: Soft convergence has 4 conditions: (1) P0==0, (2) P1<=2, (3) new_defect_rate<3 per pass for 2 consecutive, (4) aggregate_score>=70.
- **Found**: `check_convergence()` has only **1 soft convergence condition**: `convergence_score >= convergence_threshold (0.85)`. The 4 specific conditions from the PRD are NOT individually evaluated.
- **Impact**: The soft convergence evaluation is simpler than specified.
- File: `src/run4/fix_pass.py`, lines 456-465

### MISMATCH-006: Contract Engine MCP server has 10 tools, PRD claims 9

- **PRD says**: Contract Engine MCP server exposes exactly 9 tools.
- **Found**: **10 tools** registered. All 9 claimed present PLUS `check_compliance` (validates runtime response data).
- **Note**: The PRD makes an exact count claim ("9 tools"). Extra tool means total MCP tools = 4+10+8=22, not claimed 20.
- File: `src/contract_engine/mcp_server.py`

### MISMATCH-007: Codebase Intelligence MCP server has 8 tools, PRD claims 7

- **PRD says**: Codebase Intelligence MCP server exposes exactly 7 tools.
- **Found**: **8 tools** registered. All 7 claimed present PLUS `analyze_graph`.
- File: `src/codebase_intelligence/mcp_server.py`

### MISMATCH-008: Total MCP tools = 22, PRD claims 20

- **PRD says**: "20 MCP tools across 3 servers".
- **Found**: 4 + 10 + 8 = **22 MCP tools**. Discrepancy of +2 from extra tools in Contract Engine and Codebase Intelligence.
- Files: `src/architect/mcp_server.py`, `src/contract_engine/mcp_server.py`, `src/codebase_intelligence/mcp_server.py`

### MISMATCH-009: ContractEngineClient has 9 methods, PRD claims "6 via client"

- **PRD says (M2 REQUIREMENTS, REQ-013)**: ContractEngineClient has 6 methods: get_contract, validate_endpoint, generate_tests, check_breaking_changes, mark_implemented, get_unimplemented_contracts.
- **Found**: **9 methods** in the client class. The extra 3 are `create_contract`, `validate_spec`, `list_contracts` (labeled SVC-010a/b/c as "Build 3 direct" in the PRD).
- **Classification**: AMBIGUOUS within the PRD itself — the SVC table lists them separately but they're implemented in the same client.
- File: `src/contract_engine/mcp_client.py`

### MISMATCH-010: Client method total = 20, PRD claims "17 methods"

- **PRD says (M2 Overview)**: "3 client wrappers with 17 methods".
- **Found**: ArchitectClient=4 + ContractEngineClient=9 + CodebaseIntelligenceClient=7 = **20 total methods**. The "17" counted 4+6+7, excluding the 3 "Build 3 direct" methods.
- Files: `src/architect/mcp_client.py`, `src/contract_engine/mcp_client.py`, `src/codebase_intelligence/mcp_client.py`

### MISMATCH-011: Missing SUPER_TEAM_AUDIT_REPORT.md output

- **PRD says (M6)**: Final report written to `.run4/SUPER_TEAM_AUDIT_REPORT.md`.
- **Found**: File does not exist. `.run4/` directory does not exist.
- **Context**: Expected — M4 has not been executed to generate pipeline results that feed M5/M6.
- File: `.run4/` directory

---

## AMBIGUOUS (claim interpretation unclear)

### A-001: "120 total requirements" count

- **PRD says**: Requirements Checklist: REQ=42, TECH=9, INT=7, WIRE=21, SVC=20, TEST=18, SEC=3 = 120 total.
- **Finding**: The codebase references 199+ unique requirement IDs (many added by Builds 1-3 beyond the Run 4 scope). All REQ-001 through REQ-042 are referenced somewhere. The "120" count is specific to Run 4 requirements — this is self-consistent.
- **Test coverage gap**: TEST-011, TEST-012, TEST-013 and WIRE-017-020 lack implementations in test files (these belong to M4, which is missing).

### A-002: Test Matrix "57 tests" vs actual function count

- **PRD says**: Test Matrix Summary: B1=20, B2=10, B3=10, X=10 = 57 total.
- **Found**: 254 actual test functions across all existing test files (36+61+41+24+11+45+36). The "57" refers to test matrix scenario IDs, not pytest function count.
- **Classification**: AMBIGUOUS — different granularity. Not a mismatch.

### A-003: Milestone 3 status inconsistency

- **PRD says (MASTER_PLAN)**: Milestone 3 status = "FAILED".
- **Found**: M3 REQUIREMENTS.md says "PENDING". M3 test files exist with 35 test functions. Status labels are inconsistent.
- Files: `.agent-team/MASTER_PLAN.md`, `.agent-team/milestones/milestone-3/REQUIREMENTS.md`

### A-004: M2 test count "81 passing" vs actual "102"

- **PRD says (M2 REQUIREMENTS)**: "Total M2 tests: 81 passing" and "Total run4 suite: 112/112 passing".
- **Found**: M2 test files now contain 61+41 = 102 test functions. M1+M2 = 36+102 = 138.
- **Classification**: AMBIGUOUS — the 81/112 counts likely represent the state at time of M2 completion. Additional tests were added afterward.

### A-005: "~5,000 estimated LOC"

- **PRD says**: Estimated LOC: ~5,000.
- **Finding**: Cannot precisely verify without line counting. The 9 source files + 9 test files + 5 fixtures represent substantial code. Estimate appears reasonable.

---

## SUMMARY

| Metric | Count |
|--------|-------|
| **Total claims checked** | **54** |
| **Verified** | **35** |
| **Mismatches** | **11** |
| **Ambiguous** | **5** |
| **Not applicable (extra features)** | **3** |

### Mismatch Severity Breakdown

| Severity | Count | IDs |
|----------|-------|-----|
| **CRITICAL (blocks pipeline)** | 2 | MISMATCH-001 (missing M4 test files), MISMATCH-002 (missing Docker compose files) |
| **HIGH (missing function)** | 1 | MISMATCH-003 (`run_fix_loop` does not exist) |
| **MEDIUM (structural difference)** | 2 | MISMATCH-004 (FixPassResult 18 vs 11 fields), MISMATCH-005 (soft convergence 1 vs 4 conditions) |
| **LOW (count discrepancy, extra features)** | 5 | MISMATCH-006 (CE 10 vs 9 tools), MISMATCH-007 (CI 8 vs 7 tools), MISMATCH-008 (22 vs 20 total), MISMATCH-009 (CE client 9 vs 6), MISMATCH-010 (20 vs 17 methods) |
| **INFO (expected pending)** | 1 | MISMATCH-011 (missing audit report output) |

### Test Function Count Summary

| Test File | PRD Claimed | Actual Found | Delta |
|-----------|-------------|--------------|-------|
| test_m1_infrastructure.py | 8 | 36 | +28 |
| test_m2_mcp_wiring.py | 49 | 61 | +12 |
| test_m2_client_wrappers.py | 32 | 41 | +9 |
| test_m3_builder_invocation.py | 10 | 24 | +14 |
| test_m3_config_generation.py | 5 | 11 | +6 |
| test_m4_pipeline_e2e.py | 7 | **MISSING** | -7 |
| test_m4_health_checks.py | 5 | **MISSING** | -5 |
| test_m4_contract_compliance.py | 9 | **MISSING** | -9 |
| test_m5_fix_pass.py | 17 | 45 | +28 |
| test_m6_audit.py | 26 | 36 | +10 |
| test_regression.py | unspecified | **MISSING** | N/A |
| **Totals (existing)** | **147** | **254** | **+107** |
| **Missing tests** | **21** | **0** | **-21** |

### MCP Tool/Method Count Summary

| Component | PRD Claimed | Actual | Delta |
|-----------|-------------|--------|-------|
| Architect Server Tools | 4 | 4 | 0 |
| Contract Engine Server Tools | 9 | 10 | +1 |
| Codebase Intel Server Tools | 7 | 8 | +1 |
| **Total Server Tools** | **20** | **22** | **+2** |
| ArchitectClient Methods | 4 | 4 | 0 |
| ContractEngineClient Methods | 6 | 9 | +3 |
| CodebaseIntelClient Methods | 7 | 7 | 0 |
| **Total Client Methods** | **17** | **20** | **+3** |

### Root Cause Analysis

**Milestone 4 gap**: The largest mismatches (MISMATCH-001, MISMATCH-002, MISMATCH-011) share a single root cause: Milestone 4 (E2E Pipeline) has not been implemented. M4 is the critical juncture where Docker compose tiering, pipeline test files, and infrastructure deployment are built. This cascades to M5/M6's audit report generation.

**Structural design choices**: MISMATCH-003, MISMATCH-004, and MISMATCH-005 reflect implementation design decisions that deviate from the PRD's specified structure. The implementation uses nested dataclasses and a single convergence formula rather than the PRD's flat fields and 4-condition soft convergence. These are design-level deviations, not bugs.

**Extra features**: MISMATCH-006 through MISMATCH-010 are cases where the implementation has MORE capabilities than the PRD specified. The Contract Engine and Codebase Intelligence servers have additional tools beyond the PRD inventory. These are not defects.

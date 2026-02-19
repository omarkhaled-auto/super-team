# MASTER PLAN: Run 4 — End-to-End Integration, Verification & Audit

> **PRD Source**: RUN4_PRD.md
> **Generated**: 2026-02-18
> **Type**: Verification + Remediation Run (NOT a build)
> **Estimated LOC**: ~5,000 (fixes, test infrastructure, audit tooling)
> **Estimated Duration**: 5-9 hours
> **Budget**: $36-66 (max $100)

---

## Executive Summary

Run 4 wires the three independently-built systems of the Super Agent Team together, verifies every integration point, catalogs every defect, applies convergence-based fix passes, and produces the final audit report. This is a **verification and remediation run** — it does NOT build new features but validates and fixes existing ones.

### The Three Systems Being Wired

| System | Build | Components |
|--------|-------|------------|
| Foundation Services | Build 1 | Architect MCP (4 tools), Contract Engine MCP (9 tools), Codebase Intelligence MCP (7 tools) |
| Builder Fleet | Build 2 | agent-team v14.0 with ContractEngineClient, CodebaseIntelligenceClient, ArchitectClient |
| Orchestration Layer | Build 3 | Super Orchestrator, Integrator, Quality Gate, CLI |

### Success Criteria

| ID | Criterion | Pass Condition |
|----|-----------|----------------|
| SC-01 | Pipeline runs end-to-end | State reaches "complete" |
| SC-02 | 3-service TaskTracker deploys | All 3 "healthy" in docker compose ps |
| SC-03 | Integration tests pass | overall_health != "failed" |
| SC-04 | Contract violations detected | Planted violation in QUALITY_GATE_REPORT.md |
| SC-05 | Codebase Intelligence indexes code | total_symbols > 0 after build |
| SC-06 | Codebase Intelligence MCP responds | find_definition("User") returns result |
| SC-07 | Total time under 6 hours | GREEN: <6h |

---

## Milestone Dependency Graph

```
  milestone-1 (Test Infrastructure)
      |                |
      v                v
  milestone-2       milestone-3
  (MCP Wiring)    (Builder Wiring)
      |                |
      +-------+--------+
              |
              v
        milestone-4
        (E2E Pipeline)
              |
              v
        milestone-5
        (Fix Pass)
              |
              v
        milestone-6
        (Audit Report)
```

### Critical Path

```
M1 -> M2 -> M4 -> M5 -> M6  (longest chain)
M1 -> M3 ----^               (parallel with M2)
```

**Parallelization**: M2 and M3 can execute concurrently after M1 completes.

---

## Milestone Overview

## Milestone 1: Test Infrastructure + Fixtures
- ID: milestone-1
- Status: COMPLETE
- Dependencies: none
- Description: Establish the test framework, sample app fixtures, mock MCP servers, Run4Config, Run4State persistence, and shared test utilities. Foundation for all subsequent milestones.
- Estimated LOC: ~1,200
- Risk Level: LOW
- Files to Create: 10 source + 7 fixture + 1 conftest
- Requirements: REQ-001 through REQ-008, TECH-001 through TECH-003, INT-001 through INT-007, TEST-001 through TEST-007

## Milestone 2: Build 1 to Build 2 MCP Wiring Verification
- ID: milestone-2
- Status: COMPLETE
- Dependencies: milestone-1
- Description: Verify all 20 MCP tools across 3 servers are callable from Build 2 client wrappers. Test session lifecycle, error recovery, retry behavior, and fallback paths.
- Estimated LOC: ~1,000
- Risk Level: HIGH (MCP SDK compatibility, async edge cases)
- Files to Create: 2 test files
- Requirements: REQ-009 through REQ-015, WIRE-001 through WIRE-012, TEST-008, SVC-001 through SVC-017

## Milestone 3: Build 2 to Build 3 Wiring Verification
- ID: milestone-3
- Status: FAILED
- Dependencies: milestone-1
- Description: Verify Build 3 Super Orchestrator can invoke Build 2 Builders as subprocesses, parse output, generate valid configs, and feed fix instructions.
- Estimated LOC: ~800
- Risk Level: MEDIUM (subprocess management, Windows process handling)
- Files to Create: 2 test files + builder.py source
- Requirements: REQ-016 through REQ-020, WIRE-013 through WIRE-016, WIRE-021, TEST-009, TEST-010, SVC-018 through SVC-020

## Milestone 4: End-to-End Pipeline Test
- ID: milestone-4
- Status: PENDING
- Dependencies: milestone-2, milestone-3
- Description: Feed 3-service sample PRD through COMPLETE pipeline: Architect decomposition, Contract registration, 3 parallel Builders, Docker deployment, Integration tests, Quality Gate.
- Estimated LOC: ~1,200
- Risk Level: CRITICAL (Docker, networking, multi-service orchestration)
- Files to Create: 3 test files + Docker compose files
- Requirements: REQ-021 through REQ-028, WIRE-017 through WIRE-020, TECH-004 through TECH-006, SEC-001 through SEC-003, TEST-011, TEST-012

## Milestone 5: Fix Pass + Defect Remediation
- ID: milestone-5
- Status: PENDING
- Dependencies: milestone-4
- Description: Catalog all defects from M2-M4, classify by priority P0-P3, apply convergence-based fix passes, track effectiveness metrics, verify no regressions.
- Estimated LOC: ~600
- Risk Level: MEDIUM (convergence may not reach target)
- Files to Create: fix_pass.py source + 1 test file
- Requirements: REQ-029 through REQ-033, TECH-007, TECH-008, TEST-013 through TEST-015

## Milestone 6: Audit Report + Final Verification
- ID: milestone-6
- Status: PENDING
- Dependencies: milestone-5
- Description: Compute per-system and aggregate scores, generate SUPER_TEAM_AUDIT_REPORT.md with honest assessment, produce all appendices.
- Estimated LOC: ~800
- Risk Level: LOW
- Files to Create: scoring.py + audit_report.py source + 1 test file
- Requirements: REQ-034 through REQ-042, TECH-009, TEST-016 through TEST-018

---

## Source Directory Structure (New Files)

```
src/run4/
    __init__.py              # Package init, version
    config.py                # Run4Config dataclass (REQ-001, TECH-001)
    state.py                 # Run4State, Finding dataclasses (REQ-002, REQ-003, TECH-002)
    mcp_health.py            # check_mcp_health, poll_until_healthy (INT-004, INT-005)
    builder.py               # Builder invocation, parallel execution (REQ-016-020)
    fix_pass.py              # Fix loop, convergence, regression detection (REQ-029-033)
    scoring.py               # Per-system scoring, integration scoring, aggregate (REQ-034-036)
    audit_report.py          # Report generation, RTM, coverage matrices (REQ-037-042)
```

## Test Directory Structure (New Files)

```
tests/run4/
    __init__.py
    conftest.py                      # Session fixtures (INT-001 through INT-007)
    test_m1_infrastructure.py        # TEST-001 through TEST-007
    test_m2_mcp_wiring.py            # REQ-009 through REQ-012, WIRE-001 through WIRE-012, TEST-008
    test_m2_client_wrappers.py       # REQ-013 through REQ-015
    test_m3_builder_invocation.py    # REQ-016 through REQ-020, WIRE-013 through WIRE-016, WIRE-021
    test_m3_config_generation.py     # SVC-020, TEST-009, TEST-010
    test_m4_pipeline_e2e.py          # REQ-021 through REQ-025, TEST-011, TEST-012
    test_m4_health_checks.py         # REQ-021, WIRE-017 through WIRE-020
    test_m4_contract_compliance.py   # REQ-026 through REQ-028, SEC-001 through SEC-003
    test_m5_fix_pass.py              # REQ-029 through REQ-033, TEST-013 through TEST-015
    test_m6_audit.py                 # REQ-034 through REQ-042, TEST-016 through TEST-018
    test_regression.py               # Cross-milestone regression detection
    fixtures/
        sample_prd.md                # 3-service TaskTracker PRD (REQ-004)
        sample_openapi_auth.yaml     # Auth service OpenAPI 3.1 (REQ-005)
        sample_openapi_order.yaml    # Order service OpenAPI 3.1 (REQ-006)
        sample_asyncapi_order.yaml   # Order events AsyncAPI 3.0 (REQ-007)
        sample_pact_auth.json        # Pact V4 contract (REQ-008)
```

## Docker Compose Structure (New/Modified Files)

```
docker/
    docker-compose.infra.yml         # Tier 0: postgres, redis (exists/modify)
    docker-compose.build1.yml        # Tier 1: architect, contract-engine, codebase-intel (exists/modify)
    docker-compose.traefik.yml       # Tier 2: traefik v3.6 (exists/modify)
    docker-compose.generated.yml     # Tier 3: auth/order/notification (generated at runtime)
    docker-compose.run4.yml          # Tier 4: cross-build wiring overrides (NEW)
```

---

## Requirements Checklist Summary

| Category | Count |
|----------|-------|
| REQ-xxx | 42 |
| TECH-xxx | 9 |
| INT-xxx | 7 |
| WIRE-xxx | 21 |
| SVC-xxx | 20 |
| TEST-xxx | 18 |
| SEC-xxx | 3 |
| **TOTAL** | **120** |

## Test Matrix Summary

| Category | Tests | P0 | P1 | P2 |
|----------|-------|----|----|-----|
| Build 1 Verification (B1) | 20 | 14 | 5 | 1 |
| Build 2 Verification (B2) | 10 | 6 | 4 | 0 |
| Build 3 Verification (B3) | 10 | 5 | 4 | 1 |
| Cross-Build Integration (X) | 10 | 6 | 4 | 0 |
| **Total** | **57** | **37** | **18** | **2** |

---

## Technology Stack

| Component | Choice |
|-----------|--------|
| Test Framework | pytest + pytest-asyncio |
| HTTP Client | httpx (async) |
| Docker Testing | Testcontainers (Python) |
| MCP Client | mcp SDK (Python, >=1.25) |
| Contract Testing | Schemathesis + Pact |
| Process Mgmt | asyncio.create_subprocess_exec |
| State Persistence | JSON (atomic write via tmp+rename) |
| API Gateway | Traefik v3.6 |
| Database | PostgreSQL 16 |
| Cache | Redis 7 |

---

## Risk Register

| Risk | Probability | Impact | Mitigation |
|------|-------------|--------|------------|
| ChromaDB first-download timeout | Medium | CI MCP fails | mcp_first_start_timeout_ms: 120000 |
| Architect HTTP to Contract Engine fails | Medium | Empty results | Docker Compose up before MCP tests |
| Nested asyncio.run() in Build 3 | High | RuntimeError | Use subprocess isolation |
| Docker Compose v1 vs v2 | Medium | Not found | Use `docker compose` (v2) |
| Builder timeout on large PRD | Medium | 30-min insufficient | builder_timeout_s: 3600 |
| MCP SDK version mismatch | Low | Protocol error | Pin mcp>=1.25,<2 |
| Windows process management | Medium | Orphan processes | terminate() + kill() with timeout |

---

## Implementation Order

### Phase 1: Foundation (M1)
1. `src/run4/__init__.py`
2. `src/run4/config.py` — Run4Config dataclass
3. `src/run4/state.py` — Run4State + Finding dataclasses
4. `src/run4/mcp_health.py` — Health check utilities
5. `tests/run4/__init__.py`
6. `tests/run4/conftest.py` — Session fixtures
7. All fixture files (sample_prd.md, OpenAPI specs, AsyncAPI, Pact)
8. `tests/run4/test_m1_infrastructure.py`

### Phase 2: Wiring Verification (M2 + M3 in parallel)
9. `tests/run4/test_m2_mcp_wiring.py`
10. `tests/run4/test_m2_client_wrappers.py`
11. `src/run4/builder.py` — Builder subprocess invocation
12. `tests/run4/test_m3_builder_invocation.py`
13. `tests/run4/test_m3_config_generation.py`

### Phase 3: E2E Pipeline (M4)
14. `docker/docker-compose.run4.yml` — Cross-build wiring
15. `tests/run4/test_m4_pipeline_e2e.py`
16. `tests/run4/test_m4_health_checks.py`
17. `tests/run4/test_m4_contract_compliance.py`

### Phase 4: Fix Pass (M5)
18. `src/run4/fix_pass.py` — Fix loop, convergence
19. `tests/run4/test_m5_fix_pass.py`

### Phase 5: Audit (M6)
20. `src/run4/scoring.py` — Scoring formulas
21. `src/run4/audit_report.py` — Report generation
22. `tests/run4/test_m6_audit.py`
23. `tests/run4/test_regression.py`

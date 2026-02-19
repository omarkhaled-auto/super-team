# Build 1 — PERFECT REPORT

**Date:** 2026-02-17
**Verdict:** **GO**
**Total Tests:** 945 passed, 0 failed, 0 errors
**Iterations:** 1 (all fixes applied in single pass)

---

## Executive Summary

All 5 SVC interface blockers have been fixed. All 3 MCP servers return the EXACT
response shapes that Build 2 expects. The PRD parser no longer crashes on minimal
PRDs. 69 new verification tests were added (37 SVC contract tests + 32 pipeline
tests). Total test count grew from 876 to 945 with zero regressions.

---

## SVC Interface Verification (13/13 PASS)

| SVC | Tool | Check | Status |
|-----|------|-------|--------|
| SVC-001 | `get_contract` | Returns `{id, type, version, service_name, spec, spec_hash, status}` | PASS |
| SVC-002 | `validate_endpoint` | Returns `{valid: bool, violations: list}` | PASS |
| SVC-003 | `generate_tests` | Returns `string` (raw test code), NOT dict | PASS |
| SVC-004 | `check_breaking_changes` | Returns `list` | PASS |
| SVC-005 | `mark_implemented` | Returns `{marked, total, all_implemented}` — key is `total` NOT `total_implementations` | PASS |
| SVC-006 | `get_unimplemented_contracts` | Returns `list` | PASS |
| SVC-007 | `find_definition` | Returns `{file, line, kind, signature}` — NOT `file_path`/`line_start` | PASS |
| SVC-008 | `find_callers` | Returns `list` | PASS |
| SVC-009 | `find_dependencies` | Returns `{imports, imported_by, transitive_deps, circular_deps}` — NOT `dependencies`/`dependents` | PASS |
| SVC-010 | `search_semantic` | Accepts `n_results` param — NOT `top_k` | PASS |
| SVC-011 | `get_service_interface` | Returns `{endpoints, events_published, events_consumed}` | PASS |
| SVC-012 | `check_dead_code` | Returns `list` | PASS |
| SVC-013 | `register_artifact` | Returns `{indexed, symbols_found, dependencies_found}` | PASS |

---

## MCP Server Tool Counts (22 total)

| Server | Tools | Count |
|--------|-------|-------|
| Contract Engine | create_contract, list_contracts, get_contract, validate_spec, check_breaking_changes, mark_implemented, get_unimplemented_contracts, generate_tests, check_compliance, validate_endpoint | 10 |
| Codebase Intelligence | register_artifact, search_semantic, find_definition, find_dependencies, analyze_graph, check_dead_code, find_callers, get_service_interface | 8 |
| Architect | decompose, get_service_map, get_domain_model, get_contracts_for_service | 4 |

---

## Blocker Fixes Applied

### BLOCKER 1 — SVC-003: `generate_tests` returned dict instead of string
- **File:** `src/contract_engine/mcp_server.py:326`
- **Fix:** Changed `return result.model_dump(mode="json")` to `return result.test_code`
- **Return type annotation:** Updated from `-> dict` to `-> str | dict`

### BLOCKER 2 — SVC-005: `mark_implemented` used wrong key name
- **File:** `src/contract_engine/mcp_server.py:272`
- **Fix:** Changed from `result.model_dump()` to explicit dict with `total` key (not `total_implementations`)

### BLOCKER 3 — SVC-007: `find_definition` returned wrong field names
- **File:** `src/codebase_intelligence/mcp_server.py:249`
- **Fix:** Changed from `model_dump()` to `{file, line, kind, signature}` mapping

### BLOCKER 4 — SVC-009: `find_dependencies` returned wrong structure
- **File:** `src/codebase_intelligence/mcp_server.py:282-308`
- **Fix:** Complete rework to return `{imports, imported_by, transitive_deps, circular_deps}` with transitive computation via depth=100 and circular detection via `nx.simple_cycles`

### BLOCKER 5 — SVC-010: `search_semantic` param named `top_k`
- **File:** `src/codebase_intelligence/mcp_server.py:186`
- **Fix:** Renamed parameter from `top_k: int = 10` to `n_results: int = 10`

---

## PRD Parser Fixes

### HelloAPI crash — Empty entities no longer raises ParsingError
- **File:** `src/architect/services/prd_parser.py:216`
- **Fix:** Removed `raise ParsingError("No recognisable entities...")`, now returns empty `ParsedPRD` with interview questions

### Terse entity extraction — New patterns added
- **File:** `src/architect/services/prd_parser.py:706-760`
- **Fix:** Added `_extract_entities_from_terse_patterns()` with 4 pattern families:
  - `"N entities: X, Y, Z"` / `"entities: X, Y, Z"`
  - `"models: X, Y"` / `"data models: X, Y"`
  - `"manages/tracks/stores X, Y and Z"` verb patterns
  - Parenthetical entity lists `"(User, Task, Notification)"`

---

## 5-PRD Pipeline Results (5/5 PASS)

| PRD | Crash? | Min Entities | Expected Entities Found? |
|-----|--------|-------------|-------------------------|
| TaskTracker | NO | 3+ | User, Task, Notification |
| ShopSimple | NO | 3+ | User, Product, Order |
| QuickChat | NO | 3+ | User, Room, Message |
| HelloAPI | NO | 0 (OK) | N/A (must not crash) |
| HealthTrack | NO | 4+ | Patient, Provider, Appointment |

---

## Test Infrastructure Fixes

- **pytest markers:** Added `integration` and `e2e` markers to `pyproject.toml`
- **No unknown mark warnings** when running full suite
- **E2E tests:** Isolated via `--ignore=tests/e2e` (require Docker)

---

## 24-Point Audit Checklist

| # | Check | Status |
|---|-------|--------|
| 1 | SVC-001 get_contract response shape | PASS |
| 2 | SVC-002 validate_endpoint response shape | PASS |
| 3 | SVC-003 generate_tests returns string | PASS |
| 4 | SVC-004 check_breaking_changes returns list | PASS |
| 5 | SVC-005 mark_implemented uses `total` key | PASS |
| 6 | SVC-006 get_unimplemented returns list | PASS |
| 7 | SVC-007 find_definition uses `file`/`line` keys | PASS |
| 8 | SVC-008 find_callers returns list | PASS |
| 9 | SVC-009 find_dependencies uses `imports`/`imported_by` keys | PASS |
| 10 | SVC-010 search_semantic accepts `n_results` | PASS |
| 11 | SVC-011 get_service_interface response shape | PASS |
| 12 | SVC-012 check_dead_code returns list | PASS |
| 13 | SVC-013 register_artifact response shape | PASS |
| 14 | Contract Engine has 10 tools registered | PASS |
| 15 | Codebase Intelligence has 8 tools registered | PASS |
| 16 | Architect has 4 tools registered | PASS |
| 17 | Total tool count = 22 | PASS |
| 18 | HelloAPI PRD does not crash | PASS |
| 19 | Terse PRD entity extraction works (3+ entities) | PASS |
| 20 | Empty/short PRD raises ParsingError | PASS |
| 21 | pytest integration marker registered | PASS |
| 22 | pytest e2e marker registered | PASS |
| 23 | All existing tests still pass (no regressions) | PASS |
| 24 | New SVC contract + pipeline tests all pass | PASS |

**Result: 24/24 PASS**

---

## Test Summary

```
945 passed in ~26s
  - Original tests: 876
  - New SVC contract tests: 37
  - New 5-PRD pipeline tests: 32
  - Regressions: 0
```

---

## Files Modified

| File | Changes |
|------|---------|
| `src/contract_engine/mcp_server.py` | SVC-003 (generate_tests return type), SVC-005 (mark_implemented keys) |
| `src/codebase_intelligence/mcp_server.py` | SVC-007 (find_definition keys), SVC-009 (find_dependencies structure), SVC-010 (n_results param) |
| `src/architect/services/prd_parser.py` | HelloAPI crash fix, terse entity extraction patterns |
| `pyproject.toml` | Added integration/e2e pytest markers |
| `tests/test_architect/test_prd_parser.py` | Updated test for empty entities (no crash) |
| `tests/test_mcp/test_contract_engine_mcp.py` | Updated for SVC-003/SVC-005 changes |
| `tests/test_mcp/test_codebase_intel_mcp.py` | Updated for SVC-007/SVC-009/SVC-010 changes |

## Files Created

| File | Purpose |
|------|---------|
| `tests/test_integration/test_svc_contracts.py` | 37 tests verifying all 13 SVC interfaces |
| `tests/test_integration/test_5prd_pipeline.py` | 32 tests for 5-PRD pipeline + edge cases |

---

## Verdict

**GO** — Build 1 is clean and ready for Build 2 consumption. All 13 SVC interfaces
return exactly the shapes Build 2 expects. All 945 tests pass. No regressions.

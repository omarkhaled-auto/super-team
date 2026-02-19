# Build 1 → Build 2 Verification Report

**Date:** 2026-02-17
**Verdict:** NO-GO

---

## Test Suite

| Metric | Value |
|--------|-------|
| Total tests (non-e2e) | 876 |
| Passed | 876 |
| Failed | 0 |
| Errors | 0 |
| Warnings | 1 (PytestUnknownMarkWarning for `pytest.mark.integration`) |
| Duration | 19.53s |
| E2E tests (excluded) | 70 failed + 17 errors (require live Docker services) |

**Result: PASS** — 876 passed, 0 failures, 1 warning, ≥ 850 threshold met.

---

## MCP Tool Audit

### Contract Engine Tools (Build 2 SVC-001 through SVC-006)

| SVC | Build 2 Calls | Tool Exists? | Params Match? | Response Match? | Notes |
|-----|--------------|--------------|---------------|-----------------|-------|
| SVC-001 | `get_contract(contract_id)` | YES | YES | YES | Returns ContractEntry model_dump — has id, type, version, service_name, spec, spec_hash, status |
| SVC-002 | `validate_endpoint(service_name, method, path, response_body, status_code)` | YES | YES | YES | Returns `{valid: bool, violations: list}` |
| SVC-003 | `generate_tests(contract_id, framework, include_negative)` | YES | YES | **MISMATCH** | Returns **dict** (ContractTestSuite dump with test_code field), Build 2 expects raw **string** |
| SVC-004 | `check_breaking_changes(contract_id, new_spec)` | YES | YES | YES | Returns list of BreakingChange dicts |
| SVC-005 | `mark_implemented(contract_id, service_name, evidence_path)` | YES | YES | **MISMATCH** | Returns `total_implementations` but Build 2 expects field named `total` |
| SVC-006 | `get_unimplemented_contracts(service_name)` | YES | YES | YES | Returns list of UnimplementedContract dicts |

### Codebase Intelligence Tools (Build 2 SVC-007 through SVC-013)

| SVC | Build 2 Calls | Tool Exists? | Params Match? | Response Match? | Notes |
|-----|--------------|--------------|---------------|-----------------|-------|
| SVC-007 | `find_definition(symbol, language)` | YES | YES | **MISMATCH** | Returns `file_path` (Build 2 expects `file`), `line_start` (Build 2 expects `line`) |
| SVC-008 | `find_callers(symbol, max_results)` | YES | YES | YES | Returns list of caller dicts |
| SVC-009 | `find_dependencies(file_path)` | YES | YES | **MISMATCH** | Returns `{dependencies, dependents}` but Build 2 expects `{imports, imported_by, transitive_deps, circular_deps}` |
| SVC-010 | `search_semantic(query, language, service_name, n_results)` | YES | **MISMATCH** | YES | Build 1 param is `top_k`, Build 2 sends `n_results` |
| SVC-011 | `get_service_interface(service_name)` | YES | YES | YES | Returns endpoints, events_published, events_consumed |
| SVC-012 | `check_dead_code(service_name)` | YES | YES | YES | Returns list of DeadCodeEntry dicts |
| SVC-013 | `register_artifact(file_path, service_name)` | YES | YES | YES | Returns `{indexed, symbols_found, dependencies_found}` |

### Architect Tools (Build 2 does NOT call; Build 3 does)

| PRD Tool | Exists? | Params Match PRD REQ-059? |
|----------|---------|--------------------------|
| `decompose(prd_text)` | YES (`@mcp.tool(name="decompose")`) | YES |
| `get_service_map()` | YES (`@mcp.tool()`) | YES (has optional `project_name`) |
| `get_contracts_for_service(service_name)` | YES (`@mcp.tool(name="get_contracts_for_service")`) | YES |
| `get_domain_model()` | YES (`@mcp.tool()`) | YES (has optional `project_name`) |

### Tool Count Summary

| Server | PRD Tools | Bonus Tools | Total Registered |
|--------|-----------|-------------|-----------------|
| Architect | 4 | 0 | 4 |
| Contract Engine | 9 | 1 (`validate_endpoint`) | 10 |
| Codebase Intelligence | 7 | 1 (`analyze_graph`) | 8 |
| **Total** | **20** | **2** | **22** |

**Result: 20/20 PRD tools registered. But 5 interface mismatches found (see below).**

---

## MCP Live Call Results

Based on code review of return values (not runtime calls — runtime calls would crash on the same mismatches):

| SVC | Tool Called | Response Fields Verified | PASS/FAIL | Evidence |
|-----|-----------|------------------------|-----------|----------|
| SVC-001 | `get_contract` | id, type, version, service_name, spec, spec_hash, status | PASS | `contract_engine/mcp_server.py:153` returns `result.model_dump(mode="json")` |
| SVC-002 | `validate_endpoint` | valid, violations | PASS | `contract_engine/mcp_server.py:426` returns `{"valid": ..., "violations": ...}` |
| SVC-003 | `generate_tests` | Build 2 expects `str`, gets `dict` | **FAIL** | `contract_engine/mcp_server.py:322` returns `result.model_dump()` (dict with test_code, test_count, etc.) |
| SVC-004 | `check_breaking_changes` | list[dict] | PASS | `contract_engine/mcp_server.py:222` returns list of model dumps |
| SVC-005 | `mark_implemented` | marked ✓, `total_implementations` ≠ `total` | **FAIL** | `shared/models/contracts.py:238` — MarkResponse has `total_implementations` not `total` |
| SVC-006 | `get_unimplemented_contracts` | list[dict] | PASS | `contract_engine/mcp_server.py:292` returns list of model dumps |
| SVC-007 | `find_definition` | `file_path` ≠ `file`, `line_start` ≠ `line` | **FAIL** | `codebase_intelligence/mcp_server.py:247` returns `s.model_dump()` (SymbolDefinition fields) |
| SVC-008 | `find_callers` | list[dict] | PASS | `codebase_intelligence/mcp_server.py:397` returns file_path, line, caller_symbol |
| SVC-009 | `find_dependencies` | `dependencies`/`dependents` ≠ `imports`/`imported_by`/`transitive_deps`/`circular_deps` | **FAIL** | `codebase_intelligence/mcp_server.py:284` returns `{file_path, depth, dependencies, dependents}` |
| SVC-010 | `search_semantic` | list[dict] (but `n_results` param → `top_k`) | **FAIL** | `codebase_intelligence/mcp_server.py:185` param is `top_k` not `n_results` |
| SVC-011 | `get_service_interface` | endpoints, events_published, events_consumed | PASS | `codebase_intelligence/mcp_server.py:470` returns all expected fields |
| SVC-012 | `check_dead_code` | list[dict] | PASS | `codebase_intelligence/mcp_server.py:348` returns DeadCodeEntry dumps |
| SVC-013 | `register_artifact` | indexed, symbols_found, dependencies_found | PASS | `codebase_intelligence/services/incremental_indexer.py:153` returns correct dict |

**Result: 8/13 PASS, 5/13 FAIL — BLOCKING**

---

## spec_hash Check

| Aspect | Build 1 | Build 2 (TECH-014) | Match? |
|--------|---------|-------------------|--------|
| Algorithm | SHA-256 | SHA-256 | YES |
| Input | `json.dumps(spec, sort_keys=True).encode("utf-8")` | `json.dumps(spec, sort_keys=True).encode()` | YES |
| Compact separators | NO (default) | NO (explicitly "NO compact separators") | YES |
| Location | `src/shared/models/contracts.py:57` and `src/contract_engine/services/contract_store.py:38` | Build 2 TECH-014 spec | — |
| Test | `d8497d9d...` for `{"a": 1, "b": 2}` | `d8497d9d...` (identical) | YES |

**Result: MATCH**

---

## 5-PRD Pipeline

| PRD | Name | parse_prd | identify_boundaries | build_service_map | build_domain_model | Services | Entities | PASS/FAIL |
|-----|------|-----------|-------------------|------------------|-------------------|----------|----------|-----------|
| 1 | TaskTracker | OK | OK | OK | OK | 1 | 1 | PASS (low count) |
| 2 | ShopSimple | OK | OK | OK | OK | 1 | 1 | PASS (low count) |
| 3 | QuickChat | OK | OK | OK | OK | 1 | 1 | PASS (low count) |
| 4 | HelloAPI | FAIL | — | — | — | — | — | **FAIL** (ParsingError) |
| 5 | HealthTrack | OK | OK | OK | OK | 1 | 1 | PASS (low count) |

**Notes:**
- PRD 4 (HelloAPI) fails with `ParsingError: No recognisable entities or data model found`. This is an edge case — extremely minimal PRD.
- PRDs 1-3, 5 complete without crash, no `ValidationError` on language=None.
- Entity counts are very low (1 each) despite PRDs listing 3-6 entities. The parser works but entity extraction is weak for terse one-liner PRDs.

**Result: 4/5 PASS (≥ 4 required) — BORDERLINE PASS**

---

## Database Schema

| DB | Expected Tables | Found Tables | PASS/FAIL |
|----|----------------|--------------|-----------|
| Architect | service_maps, domain_models, decomposition_runs | decomposition_runs, domain_models, service_maps | PASS |
| Contracts | build_cycles, contracts, contract_versions, breaking_changes, implementations, test_suites, shared_schemas, schema_consumers | breaking_changes, build_cycles, contract_versions, contracts, implementations, schema_consumers, shared_schemas, test_suites | PASS |
| Symbols | indexed_files, symbols, dependency_edges, import_references, graph_snapshots | dependency_edges, graph_snapshots, import_references, indexed_files, symbols | PASS |

All `init_*_db()` functions ran without error. Cleanup successful.

**Result: 3/3 PASS**

---

## Verdict

### Scoring

| # | Verification | Result | Blocking? |
|---|-------------|--------|-----------|
| 1 | Test Suite (0 failures, ≥850 tests) | **PASS** (876 passed, 0 failures) | — |
| 2 | MCP Tool Names (20/20 PRD tools registered) | **20/20** tools exist | — |
| 3 | MCP Tool Live Calls (13/13 SVC tools return correct fields) | **8/13** | **YES — BLOCKING** |
| 4 | spec_hash compatibility | **MATCH** | — |
| 5 | 5-PRD Pipeline (5/5 complete without crash) | **4/5** | — |
| 6 | Database Schema (3/3 DBs initialize) | **3/3** | — |

### Decision: NO-GO

Build 2 **cannot proceed** because 5 of 13 SVC tools have interface mismatches that will cause runtime failures.

---

## Blocking Failures — Exact Fixes Required

### BLOCKER 1: SVC-005 `mark_implemented` response field name

**File:** `src/shared/models/contracts.py:238`
**Problem:** `MarkResponse.total_implementations` → Build 2 expects field named `total`
**Fix:** Rename field to `total` OR add alias, OR update Build 2 client to read `total_implementations`

### BLOCKER 2: SVC-007 `find_definition` response field names

**File:** `src/codebase_intelligence/mcp_server.py:247`
**Problem:** Returns full `SymbolDefinition.model_dump()` with `file_path`, `line_start`, `line_end`
**Build 2 expects:** `{file: str, line: int, kind: str, signature: str}`
**Fix:** Transform the response in the MCP tool to return `{"file": s.file_path, "line": s.line_start, "kind": s.kind.value, "signature": s.signature}` instead of raw model dump

### BLOCKER 3: SVC-009 `find_dependencies` response structure

**File:** `src/codebase_intelligence/mcp_server.py:284`
**Problem:** Returns `{file_path, depth, dependencies, dependents}`
**Build 2 expects:** `{imports, imported_by, transitive_deps, circular_deps}`
**Fix:** Restructure the return dict to:
```python
return {
    "imports": deps,              # was "dependencies"
    "imported_by": dependents,    # was "dependents"
    "transitive_deps": [...],     # need to add transitive dep computation
    "circular_deps": [...],       # need to add cycle detection for this file
}
```

### BLOCKER 4: SVC-010 `search_semantic` parameter name

**File:** `src/codebase_intelligence/mcp_server.py:185`
**Problem:** Parameter is `top_k: int = 10`
**Build 2 sends:** `n_results: int`
**Fix:** Rename parameter from `top_k` to `n_results` (and update the internal call to `_semantic_searcher.search(..., top_k=n_results)`)

### BLOCKER 5: SVC-003 `generate_tests` response type

**File:** `src/contract_engine/mcp_server.py:322`
**Problem:** Returns `result.model_dump(mode="json")` — a dict with `{contract_id, framework, test_code, test_count, generated_at}`
**Build 2 expects:** Raw string (test file content)
**Fix:** Return `result.test_code` instead of `result.model_dump()`, OR update Build 2's client to extract `test_code` from the dict response

---

## Summary

Build 1's core infrastructure is solid — tests pass, databases initialize, tools are registered with correct names, spec_hash is compatible. The 5 blocking issues are all **response format / parameter name mismatches** between what Build 1's MCP tools return and what Build 2's MCP clients expect to receive. These are localized fixes (5 files, ~20 lines of changes total) but they MUST be resolved before Build 2 begins.

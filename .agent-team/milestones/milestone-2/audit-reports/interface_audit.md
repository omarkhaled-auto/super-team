# Interface Audit Report — Milestone 2

**Auditor**: Interface Auditor (audit-team)
**Milestone**: milestone-2 (Build 1 to Build 2 MCP Wiring Verification)
**Date**: 2026-02-19
**Total Findings**: 18

---

## Summary

| Severity | Count |
|----------|-------|
| CRITICAL | 2     |
| HIGH     | 4     |
| MEDIUM   | 6     |
| LOW      | 3     |
| INFO     | 3     |
| **Total** | **18** |

---

## Findings

---

### FINDING-001 — CRITICAL — SVC-011: `find_definition` DTO field names mismatch

**Requirement**: SVC-011 specifies `DefinitionResult {file_path, line_start, line_end, kind, signature, docstring}`

**Source**: `src/codebase_intelligence/mcp_server.py` lines 249-254

**Actual Response**:
```python
return {
    "file": s.file_path,           # WRONG — should be "file_path"
    "line": s.line_start,           # WRONG — should be "line_start"
    "kind": s.kind.value,
    "signature": s.signature or "",
}
```

**Issues**:
1. Field `"file"` should be `"file_path"` per SVC-011 contract
2. Field `"line"` should be `"line_start"` per SVC-011 contract
3. Field `"line_end"` is entirely missing (required by contract)
4. Field `"docstring"` is entirely missing (required by contract)

The underlying `SymbolDefinition` model has all the required fields (`file_path`, `line_start`, `line_end`, `docstring`), but the MCP tool reshapes them to non-conformant field names and drops two fields.

**Impact**: Any Build 2 consumer of `find_definition` that accesses `result["file_path"]` or `result["line_start"]` will get `KeyError` at runtime. Consumers expecting `line_end` or `docstring` will fail silently or crash.

**Test Collusion**: The test file `test_m2_mcp_wiring.py` (line 448-460) and `test_m2_client_wrappers.py` (line 471-476) both assert on `"file"` and `"line"` — the **wrong** field names matching the buggy server rather than the SVC-011 contract. Tests are green but validating the wrong shape.

---

### FINDING-002 — CRITICAL — SVC-009: `mark_implemented` DTO field name mismatch

**Requirement**: SVC-009 specifies `MarkResult {marked, total_implementations, all_implemented}`

**Source**: `src/contract_engine/mcp_server.py` lines 272-276

**Actual Response**:
```python
return {
    "marked": result.marked,
    "total": result.total_implementations,  # WRONG — should be "total_implementations"
    "all_implemented": result.all_implemented,
}
```

The underlying `MarkResponse` model in `src/shared/models/contracts.py` uses the correct field name `total_implementations`, but the MCP tool layer maps it to `"total"`.

**Impact**: Any Build 2 consumer accessing `result["total_implementations"]` will get `KeyError`.

**Test Collusion**: Test `test_m2_mcp_wiring.py` (line 359-363) asserts on `"total"` instead of `"total_implementations"`. Test `test_m2_client_wrappers.py` (line 361-363) also asserts on `"total"`. Both tests validate the wrong field name.

---

### FINDING-003 — HIGH — SVC-012: `find_callers` DTO field name mismatch

**Requirement**: SVC-012 specifies response `list[{file_path, line, caller_name}]`

**Source**: `src/codebase_intelligence/mcp_server.py` lines 415-419

**Actual Response**:
```python
callers.append({
    "file_path": row["source_file"],
    "line": row["line"],
    "caller_symbol": row["caller_symbol"] or row["source_symbol_id"],  # WRONG
})
```

The response uses `"caller_symbol"` instead of `"caller_name"` as specified in SVC-012.

**Test Alignment**: Tests in `test_m2_client_wrappers.py` (line 493-495) assert on `"caller_symbol"` matching the server but not the SVC-012 contract.

---

### FINDING-004 — HIGH — Missing `CodebaseIntelligenceClient` MCP client wrapper

**Requirement**: SVC-011 through SVC-017 specify `CodebaseIntelligenceClient` as the Build 2 client wrapper with 7 methods: `find_definition`, `find_callers`, `find_dependencies`, `search_semantic`, `get_service_interface`, `check_dead_code`, `register_artifact`.

**Finding**: No file `src/codebase_intelligence/mcp_client.py` exists. No class `CodebaseIntelligenceClient` is defined anywhere in the codebase.

- `src/architect/mcp_client.py` exists (provides `call_architect_mcp`)
- `src/contract_engine/mcp_client.py` exists (provides `create_contract`, `validate_spec`, `list_contracts`)
- `src/codebase_intelligence/mcp_client.py` does **NOT** exist

**Impact**: Build 2 has no programmatic way to call CI MCP tools through a client abstraction. The 7 SVC entries (SVC-011 through SVC-017) that specify `CodebaseIntelligenceClient.method()` are unimplemented.

---

### FINDING-005 — HIGH — Missing `ArchitectClient` and `ContractEngineClient` class abstractions

**Requirement**: The SVC wiring map (SVC-001 through SVC-010) specifies class-based clients: `ArchitectClient.decompose()`, `ArchitectClient.get_service_map()`, `ContractEngineClient.get_contract()`, etc.

**Finding**: No classes named `ArchitectClient`, `ContractEngineClient`, or `CodebaseIntelligenceClient` exist anywhere in the source tree. Instead:
- `src/architect/mcp_client.py` exports a bare function `call_architect_mcp(prd_text, config)` — covers only `decompose` (SVC-001). Missing: `get_service_map` (SVC-002), `get_contracts_for_service` (SVC-003), `get_domain_model` (SVC-004).
- `src/contract_engine/mcp_client.py` exports 3 bare functions: `create_contract`, `validate_spec`, `list_contracts` — covers only SVC-010a, SVC-010b, SVC-010c. Missing: `get_contract` (SVC-005), `validate_endpoint` (SVC-006), `generate_tests` (SVC-007), `check_breaking_changes` (SVC-008), `mark_implemented` (SVC-009), `get_unimplemented_contracts` (SVC-010).

**Impact**: 14 of 17 client-method-to-tool wiring paths (SVC-002 through SVC-017, excluding SVC-010a/b/c) have no client implementation. Tests in `test_m2_client_wrappers.py` test against raw mock sessions, not actual client wrappers.

---

### FINDING-006 — HIGH — Contract Engine exposes 10 tools, requirements specify 9

**Requirement**: REQ-010 specifies Contract Engine should expose 9 tools.

**Source**: `src/contract_engine/mcp_server.py` registers 10 `@mcp.tool()` decorators:
1. `create_contract`
2. `list_contracts`
3. `get_contract`
4. `validate_spec`
5. `check_breaking_changes`
6. `mark_implemented`
7. `get_unimplemented_contracts`
8. `generate_tests`
9. `check_compliance` ← **extra, not in requirements**
10. `validate_endpoint`

**Finding**: `check_compliance` is an additional tool not listed in the MCP Tool-to-Client Wiring Map. The test `test_m2_mcp_wiring.py` sets `CONTRACT_ENGINE_TOOLS` to 9 tools (excluding `check_compliance`), so the handshake test uses `>=9` assertion (line 160), which passes with 10 tools.

**Impact**: `check_compliance` is an orphaned tool from the M2 wiring perspective — no client wrapper method targets it, and no SVC entry covers it. It is tested elsewhere (`tests/test_mcp/test_contract_engine_mcp.py`) but not part of M2 verification scope.

---

### FINDING-007 — MEDIUM — Codebase Intelligence exposes 8 tools, requirements specify 7

**Requirement**: REQ-011 specifies Codebase Intelligence should expose 7 tools.

**Source**: `src/codebase_intelligence/mcp_server.py` registers 8 `@mcp.tool()` decorators. The 8th tool is `analyze_graph`.

**Finding**: `analyze_graph` is an additional tool not listed in the SVC wiring map. Like `check_compliance` above, it has no corresponding client wrapper method or SVC entry. Tests use `>=7` assertion (line 196), which passes.

**Impact**: `analyze_graph` is orphaned from M2 verification. It is tested separately in `tests/test_mcp/test_codebase_intel_mcp.py`.

---

### FINDING-008 — MEDIUM — SVC-002/SVC-004: `get_service_map` and `get_domain_model` accept extra parameter

**Requirement**: SVC-002 specifies `ArchitectClient.get_service_map()` takes `None` (no parameters). SVC-004 specifies `ArchitectClient.get_domain_model()` takes `None` (no parameters).

**Source**: Both `get_service_map` and `get_domain_model` in `src/architect/mcp_server.py` accept an optional `project_name: str | None = None` parameter.

**Impact**: Low runtime risk since the parameter is optional and defaults to None. However, clients built against the SVC-002/SVC-004 contract that pass no arguments will work correctly. The extra parameter is an undocumented extension.

---

### FINDING-009 — MEDIUM — `register_artifact` accepts extra parameters not in SVC-017

**Requirement**: SVC-017 specifies `register_artifact` takes `{file_path, service_name}`.

**Source**: `src/codebase_intelligence/mcp_server.py` line 140-145:
```python
def index_file(
    file_path: str,
    service_name: str | None = None,
    source_base64: str | None = None,
    project_root: str | None = None,
) -> dict[str, Any]:
```

**Finding**: The tool accepts two additional optional parameters: `source_base64` and `project_root`, which are not documented in the SVC-017 wiring requirement.

**Impact**: Low risk. Parameters are optional. However, any client wrapper built strictly to SVC-017 will work, but consumers won't know about the extended parameters.

---

### FINDING-010 — MEDIUM — `check_mcp_health` imports `ClientSession` from wrong path

**Source**: `src/run4/mcp_health.py` line 115:
```python
from mcp import ClientSession
```

**Versus** `src/architect/mcp_client.py` line 20:
```python
from mcp.client.session import ClientSession
```

**Finding**: The `check_mcp_health` function imports `ClientSession` from `mcp` (top-level), while the architect client imports from `mcp.client.session`. This works because `mcp.__init__` re-exports `ClientSession`, but it creates a fragile dependency on the MCP SDK's re-export behavior.

**Impact**: If the MCP SDK changes its top-level exports, `check_mcp_health` would break while the mcp_client files would continue working.

---

### FINDING-011 — MEDIUM — Tests validate mock sessions, not actual client wrapper classes

**Requirement**: REQ-013 specifies "ContractEngineClient tests", REQ-014 specifies "CodebaseIntelligenceClient tests", REQ-015 specifies "ArchitectClient tests".

**Finding**: `test_m2_client_wrappers.py` does NOT instantiate or test any `ContractEngineClient`, `CodebaseIntelligenceClient`, or `ArchitectClient` class. All tests call `session.call_tool()` directly on `AsyncMock` objects. The tests verify mock MCP protocol shapes, not the wiring of actual client wrapper classes to MCP tools.

**Impact**: The stated requirement verification (REQ-013, REQ-014, REQ-015) is testing the MCP protocol layer, not the client class abstraction layer. If client classes were added later with bugs in argument mapping, these tests would not catch them.

---

### FINDING-012 — MEDIUM — `find_dependencies` has extra parameters not in SVC-013

**Requirement**: SVC-013 specifies `find_dependencies` takes `{file_path}`.

**Source**: `src/codebase_intelligence/mcp_server.py` line 261-265:
```python
def get_dependencies(
    file_path: str,
    depth: int = 1,
    direction: str = "both",
) -> dict[str, Any]:
```

**Finding**: Two additional optional parameters (`depth`, `direction`) not in the SVC-013 wiring specification.

**Impact**: Low. Parameters are optional with sensible defaults.

---

### FINDING-013 — LOW — `search_semantic` parameter name differs from SVC-014

**Requirement**: SVC-014 specifies `search_semantic` takes `{query, language, service_name, n_results}`.

**Source**: `src/codebase_intelligence/mcp_server.py` line 181-186: The server tool signature uses `n_results` as the parameter name.

**Finding**: The internal implementation passes this to `_semantic_searcher.search()` as `top_k=n_results`. While the external interface matches SVC-014, the naming inconsistency between the tool's `n_results` and the searcher's `top_k` is a minor maintenance risk.

**Impact**: Negligible. External interface is correct.

---

### FINDING-014 — LOW — Redundant `type: str = "text"` default in `MockTextContent`

**Source**: `tests/run4/conftest.py` line 40-44:
```python
@dataclass
class MockTextContent:
    type: str = "text"
    text: str = ""
```

**Finding**: The `type` field is always `"text"` and never overridden in any test. It adds no value and slightly obscures the data model.

**Impact**: Negligible. Purely cosmetic.

---

### FINDING-015 — LOW — `make_mcp_result` signature accepts `dict` but receives other types

**Source**: `tests/run4/conftest.py` line 47:
```python
def make_mcp_result(data: dict, is_error: bool = False) -> MockToolResult:
```

**Usage**: `test_m2_mcp_wiring.py` line 332 passes a string: `make_mcp_result("def test_endpoint(): pass")`. `test_m2_mcp_wiring.py` line 346 passes a list: `make_mcp_result([])`.

**Finding**: The type hint says `dict` but the function is called with `str`, `list`, and `dict`. This works because `json.dumps()` handles all JSON-serializable types, but the type annotation is misleading.

**Impact**: Static type checkers (mypy, pyright) would flag these calls. No runtime impact.

---

### FINDING-016 — INFO — `check_compliance` tool is fully functional but outside M2 scope

**Source**: `src/contract_engine/mcp_server.py` lines 332-361

**Finding**: The `check_compliance` tool is fully implemented, delegates to `ComplianceChecker`, and is tested in `tests/test_mcp/test_contract_engine_mcp.py`. It is simply not part of the M2 wiring verification scope, as it is not listed in the SVC table.

**Status**: Observation only. No action required for M2.

---

### FINDING-017 — INFO — `analyze_graph` tool is fully functional but outside M2 scope

**Source**: `src/codebase_intelligence/mcp_server.py` lines 317-335

**Finding**: Same as FINDING-016. The `analyze_graph` tool is implemented and tested, but not in M2 scope.

**Status**: Observation only. No action required for M2.

---

### FINDING-018 — INFO — WIRE-012 cross-server HTTP endpoint verified

**Requirement**: WIRE-012 specifies that `get_contracts_for_service` in Architect MCP internally calls Contract Engine HTTP.

**Source Verification**:
- `src/architect/mcp_server.py` lines 219-231: Uses `httpx.Client` to call `{contract_engine_url}/api/contracts/{contract_id}`
- `src/contract_engine/routers/contracts.py` line 69: Registers `@router.get("/contracts/{contract_id}")` with prefix `/api`
- URL path matches: `/api/contracts/{contract_id}` ← verified

**Conftest**: `architect_params` fixture (conftest.py line 125) sets `CONTRACT_ENGINE_URL: http://localhost:8002`, matching the default in `mcp_server.py` line 221.

**Status**: Cross-server HTTP wiring is correctly implemented.

---

## Orphan Detection Summary

| Item | Type | Status |
|------|------|--------|
| `check_compliance` tool (CE MCP) | Extra MCP tool | Orphaned from M2 scope; tested elsewhere |
| `analyze_graph` tool (CI MCP) | Extra MCP tool | Orphaned from M2 scope; tested elsewhere |
| `CodebaseIntelligenceClient` class | Required client | Does not exist |
| `ArchitectClient` class | Required client | Does not exist |
| `ContractEngineClient` class | Required client | Does not exist |
| `ArchitectClient.get_service_map()` | Required method | No client implementation |
| `ArchitectClient.get_contracts_for_service()` | Required method | No client implementation |
| `ArchitectClient.get_domain_model()` | Required method | No client implementation |
| `ContractEngineClient.get_contract()` | Required method | No client implementation |
| `ContractEngineClient.validate_endpoint()` | Required method | No client implementation |
| `ContractEngineClient.generate_tests()` | Required method | No client implementation |
| `ContractEngineClient.check_breaking_changes()` | Required method | No client implementation |
| `ContractEngineClient.mark_implemented()` | Required method | No client implementation |
| `ContractEngineClient.get_unimplemented_contracts()` | Required method | No client implementation |

---

## SVC Wiring Verification Matrix

| SVC-ID | Client Method | MCP Tool | Client Exists | Tool Exists | DTO Match | Verdict |
|--------|---------------|----------|:---:|:---:|:---:|---------|
| SVC-001 | `ArchitectClient.decompose()` | `decompose` | Partial (function) | YES | YES | PARTIAL |
| SVC-002 | `ArchitectClient.get_service_map()` | `get_service_map` | NO | YES | YES (extra param) | FAIL |
| SVC-003 | `ArchitectClient.get_contracts_for_service()` | `get_contracts_for_service` | NO | YES | YES | FAIL |
| SVC-004 | `ArchitectClient.get_domain_model()` | `get_domain_model` | NO | YES | YES (extra param) | FAIL |
| SVC-005 | `ContractEngineClient.get_contract()` | `get_contract` | NO | YES | YES | FAIL |
| SVC-006 | `ContractEngineClient.validate_endpoint()` | `validate_endpoint` | NO | YES | YES | FAIL |
| SVC-007 | `ContractEngineClient.generate_tests()` | `generate_tests` | NO | YES | YES | FAIL |
| SVC-008 | `ContractEngineClient.check_breaking_changes()` | `check_breaking_changes` | NO | YES | YES | FAIL |
| SVC-009 | `ContractEngineClient.mark_implemented()` | `mark_implemented` | NO | YES | **NO** (`total` vs `total_implementations`) | FAIL |
| SVC-010 | `ContractEngineClient.get_unimplemented_contracts()` | `get_unimplemented_contracts` | NO | YES | YES | FAIL |
| SVC-010a | Direct MCP | `create_contract` | YES (function) | YES | YES | PASS |
| SVC-010b | Direct MCP | `validate_spec` | YES (function) | YES | YES | PASS |
| SVC-010c | Direct MCP | `list_contracts` | YES (function) | YES | YES | PASS |
| SVC-011 | `CIClient.find_definition()` | `find_definition` | NO | YES | **NO** (4 field issues) | FAIL |
| SVC-012 | `CIClient.find_callers()` | `find_callers` | NO | YES | **NO** (`caller_symbol` vs `caller_name`) | FAIL |
| SVC-013 | `CIClient.find_dependencies()` | `find_dependencies` | NO | YES | YES (extra params) | FAIL |
| SVC-014 | `CIClient.search_semantic()` | `search_semantic` | NO | YES | YES | FAIL |
| SVC-015 | `CIClient.get_service_interface()` | `get_service_interface` | NO | YES | YES | FAIL |
| SVC-016 | `CIClient.check_dead_code()` | `check_dead_code` | NO | YES | YES | FAIL |
| SVC-017 | `CIClient.register_artifact()` | `register_artifact` | NO | YES | YES (extra params) | FAIL |

**Summary**: 3/20 PASS, 17/20 FAIL (14 due to missing client, 3 due to DTO mismatch)

---

## WIRE Verification Matrix

| WIRE-ID | Description | Test Exists | Test Mechanism | Verdict |
|---------|-------------|:---:|----------------|---------|
| WIRE-001 | Session sequential calls | YES | Mock session, 10 calls | PASS |
| WIRE-002 | Session crash recovery | YES | `BrokenPipeError` side_effect | PASS |
| WIRE-003 | Session timeout | YES | `asyncio.timeout` with slow mock | PASS |
| WIRE-004 | Multi-server concurrency | YES | 3 mock sessions, `asyncio.gather` | PASS |
| WIRE-005 | Session restart data access | YES | Two sequential mock sessions | PASS |
| WIRE-006 | Malformed JSON handling | YES | Invalid JSON in MockTextContent | PASS |
| WIRE-007 | Nonexistent tool call | YES | Error mock result | PASS |
| WIRE-008 | Server exit detection | YES | `ConnectionError` side_effect | PASS |
| WIRE-009 | Fallback CE unavailable | YES | `ConnectionError` catch + filesystem fallback | PASS |
| WIRE-010 | Fallback CI unavailable | YES | `ConnectionError` catch + safe defaults | PASS |
| WIRE-011 | Fallback Architect unavailable | YES | `ImportError` catch + flag | PASS |
| WIRE-012 | Cross-server contract lookup | YES | Mock session + HTTP endpoint verified | PASS |

**Summary**: 12/12 WIRE tests present and implemented. All test the correct failure/recovery scenarios.

---

## Conclusion

The M2 milestone has **comprehensive test coverage** for all 12 WIRE requirements and the MCP protocol-level behaviors. However, there are **two CRITICAL DTO mismatches** (FINDING-001, FINDING-002) where the MCP server tools return fields with wrong names, and the tests have been written to match the buggy output rather than the SVC contract.

The most significant structural gap is the **absence of Build 2 client wrapper classes** (FINDING-004, FINDING-005). The requirements specify `ArchitectClient`, `ContractEngineClient`, and `CodebaseIntelligenceClient` classes, but only bare functions exist for a subset of operations. The tests verify MCP protocol shapes via mock sessions rather than actual client wrapper wiring.

**Recommended Priority**:
1. Fix FINDING-001 and FINDING-002 (CRITICAL DTO mismatches) — update MCP server tools to return correct field names, then update tests
2. Address FINDING-004 and FINDING-005 (HIGH missing clients) — implement client wrapper classes or update requirements to reflect function-based architecture
3. Fix FINDING-003 (HIGH field name) — `caller_symbol` → `caller_name`

# Milestone 2 — Technical Audit Report

**Auditor**: Technical Auditor (Automated)
**Date**: 2026-02-19
**Scope**: All technical requirements (REQ-009 through REQ-015, WIRE-001 through WIRE-012, TEST-008, SVC-001 through SVC-017)
**Files Reviewed**:
- `tests/run4/test_m2_mcp_wiring.py` (1104 lines)
- `tests/run4/test_m2_client_wrappers.py` (894 lines)
- `tests/run4/conftest.py` (179 lines)
- `src/architect/mcp_server.py` (290 lines)
- `src/architect/mcp_client.py` (31 lines)
- `src/contract_engine/mcp_server.py` (476 lines)
- `src/contract_engine/mcp_client.py` (108 lines)
- `src/codebase_intelligence/mcp_server.py` (511 lines)
- `src/run4/mcp_health.py` (146 lines)
- `src/run4/config.py` (104 lines)

---

## Summary

| Severity | Count |
|----------|-------|
| CRITICAL | 0     |
| HIGH     | 2     |
| MEDIUM   | 5     |
| LOW      | 5     |
| INFO     | 3     |
| **Total** | **15** |

---

## Findings

---

### FINDING-001 — Response Schema Field Name Mismatch: `find_definition` (SVC-011)

**Severity**: HIGH
**Requirement**: SVC-011 / REQ-012 / REQ-014
**Category**: Schema Contract Violation

**Description**:
The REQUIREMENTS.md specifies the `DefinitionResult` schema as:
```
{file_path, line_start, line_end, kind, signature, docstring}
```
However, the actual `find_definition` tool in `src/codebase_intelligence/mcp_server.py` (lines 249–254) returns:
```python
{"file": s.file_path, "line": s.line_start, "kind": ..., "signature": ...}
```

**Discrepancies**:
| Spec Field         | Actual Field   | Status           |
|--------------------|----------------|------------------|
| `file_path`        | `file`         | **Renamed**      |
| `line_start`       | `line`         | **Renamed**      |
| `line_end`         | *(omitted)*    | **Missing**      |
| `docstring`        | *(omitted)*    | **Missing**      |
| `kind`             | `kind`         | OK               |
| `signature`        | `signature`    | OK               |

**Impact**: Any downstream consumer relying on `file_path` or `line_start` field names will fail. The test mocks (`test_m2_client_wrappers.py` line 92–97) are aligned with the actual server implementation (using `file` and `line`), so tests pass, but the REQUIREMENTS.md contract is violated.

**Evidence**:
- `src/codebase_intelligence/mcp_server.py:249-254` — actual response shape
- `tests/run4/test_m2_client_wrappers.py:92-97` — mock uses `file`/`line`
- `REQUIREMENTS.md` line 58 — specifies `file_path`/`line_start`/`line_end`/`docstring`

**Action Required**: Either update REQUIREMENTS.md to reflect the actual field names, or update the server to return the specified field names. The missing `line_end` and `docstring` fields should be added or explicitly documented as optional.

---

### FINDING-002 — Response Schema Field Name Mismatch: `mark_implemented` (SVC-009)

**Severity**: HIGH
**Requirement**: SVC-009 / REQ-013
**Category**: Schema Contract Violation

**Description**:
REQUIREMENTS.md specifies the `MarkResult` schema as:
```
{marked, total_implementations, all_implemented}
```
The actual `mark_implemented` tool in `src/contract_engine/mcp_server.py` (lines 272–276) returns:
```python
{"marked": ..., "total": result.total_implementations, "all_implemented": ...}
```

The field `total_implementations` is mapped to `total` in the response. Tests use `total` (matching actual), not `total_implementations` (matching spec).

**Evidence**:
- `src/contract_engine/mcp_server.py:272-276`
- `tests/run4/test_m2_client_wrappers.py:70-74` — mock uses `total`
- `REQUIREMENTS.md` line 48

**Action Required**: Align the spec or the implementation. If `total` is the intended field name, update REQUIREMENTS.md.

---

### FINDING-003 — Response Schema Field Name Mismatch: `find_callers` (SVC-012)

**Severity**: MEDIUM
**Requirement**: SVC-012 / REQ-014
**Category**: Schema Contract Deviation

**Description**:
REQUIREMENTS.md specifies the `find_callers` response shape as:
```
list[{file_path, line, caller_name}]
```
The actual `find_callers` tool in `src/codebase_intelligence/mcp_server.py` (lines 416–419) returns:
```python
{"file_path": ..., "line": ..., "caller_symbol": ...}
```

The field is `caller_symbol`, not `caller_name`. Tests align with actual (`caller_symbol`).

**Evidence**:
- `src/codebase_intelligence/mcp_server.py:416-419`
- `tests/run4/test_m2_client_wrappers.py:103-105`
- `REQUIREMENTS.md` line 59

**Action Required**: Sync spec and implementation.

---

### FINDING-004 — Type Annotation Mismatch on `make_mcp_result`

**Severity**: MEDIUM
**Requirement**: Cross-cutting (INT-003)
**Category**: Type Safety

**Description**:
The `make_mcp_result` helper in `conftest.py` (line 47) is annotated as:
```python
def make_mcp_result(data: dict, is_error: bool = False) -> MockToolResult:
```
However, it is invoked with `str` and `list` arguments throughout both test files:
- String: `make_mcp_result("def test_endpoint(): pass")` (test_m2_mcp_wiring.py:332)
- List: `make_mcp_result([])` (test_m2_mcp_wiring.py:346, 377, 500, 534)
- List of dicts: `make_mcp_result([{"id": "c1", ...}])` (test_m2_mcp_wiring.py:261)

While `json.dumps()` handles all these types at runtime, the type annotation is incorrect and will cause type-checker (mypy/pyright) errors.

**Evidence**:
- `tests/run4/conftest.py:47` — `data: dict`
- 15+ call sites across both test files with non-dict arguments

**Action Required**: Change annotation to `data: dict | list | str` or `data: Any`.

---

### FINDING-005 — Redundant Exception Clause: `except (ConnectionError, Exception)`

**Severity**: MEDIUM
**Requirement**: Cross-cutting
**Category**: Code Quality

**Description**:
In `test_m2_client_wrappers.py` (line 787):
```python
except (ConnectionError, Exception):
    result = None
```
`ConnectionError` is a subclass of `Exception`, so `except (ConnectionError, Exception)` is equivalent to `except Exception`. This is a code smell suggesting either overly broad error handling or a copy-paste artifact.

**Evidence**: `tests/run4/test_m2_client_wrappers.py:787`

**Action Required**: Replace with `except Exception:` if broad catch is intentional, or narrow to specific exception types.

---

### FINDING-006 — WIRE-003 Timeout Test Does Not Use `run4_config.mcp_tool_timeout_ms`

**Severity**: MEDIUM
**Requirement**: WIRE-003
**Category**: Test Fidelity

**Description**:
The WIRE-003 test (`test_session_timeout`) accepts `run4_config: Run4Config` as a fixture parameter but uses a hardcoded `0.1` second timeout instead of deriving the timeout from `run4_config.mcp_tool_timeout_ms`:

```python
async def test_session_timeout(self, run4_config: Run4Config) -> None:
    ...
    timeout_s = 0.1  # 100ms timeout for testing
    with pytest.raises((asyncio.TimeoutError, TimeoutError)):
        async with asyncio.timeout(timeout_s):
```

The test documents that it should "simulate slow tool exceeding `mcp_tool_timeout_ms`" but does not actually reference the config value.

**Evidence**: `tests/run4/test_m2_mcp_wiring.py:715-729`

**Action Required**: Either use `run4_config.mcp_tool_timeout_ms / 1000` or remove the fixture dependency if the hardcoded value is intentional.

---

### FINDING-007 — Contract Engine Exposes 10 Tools but Tests Assert >= 9

**Severity**: MEDIUM
**Requirement**: REQ-010
**Category**: Test Accuracy

**Description**:
The Contract Engine MCP server (`src/contract_engine/mcp_server.py`) registers **10 tools**:
1. `create_contract`
2. `list_contracts`
3. `get_contract`
4. `validate_spec`
5. `check_breaking_changes`
6. `mark_implemented`
7. `get_unimplemented_contracts`
8. `generate_tests`
9. `check_compliance`
10. `validate_endpoint`

The test constant `CONTRACT_ENGINE_TOOLS` (test_m2_mcp_wiring.py:42–52) lists only 9 tools and a comment notes "actual server also exposes check_compliance (10 total)". Similarly, `CODEBASE_INTEL_TOOLS` lists 7 with a note that `analyze_graph` (8 total) exists.

While the tests use `>=` assertions (line 160: `assert len(tool_names) >= 9`), the tool sets used for subset checking are incomplete relative to the actual server.

**Evidence**:
- `tests/run4/test_m2_mcp_wiring.py:42-63` — tool set definitions
- `src/contract_engine/mcp_server.py:332-361` — `check_compliance` tool
- `src/codebase_intelligence/mcp_server.py:317-335` — `analyze_graph` tool

**Action Required**: Add `check_compliance` and `analyze_graph` to the test inventories, or explicitly document why they are excluded from the verification set.

---

### FINDING-008 — MCP Client Wrappers Lack Error Handling and Retry Logic

**Severity**: LOW
**Requirement**: REQ-013, REQ-014 (retry/safe-defaults)
**Category**: Resilience

**Description**:
The MCP client wrappers (`src/architect/mcp_client.py` and `src/contract_engine/mcp_client.py`) contain no retry logic or safe-default returns. For example, `call_architect_mcp` will propagate any exception directly:

```python
async def call_architect_mcp(prd_text: str, config: object | None = None) -> dict:
    ...
    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool("decompose", {"prd_text": prd_text})
            return json.loads(result.content[0].text) if result.content else {}
```

The tests (REQ-013, REQ-014) verify retry and safe-default behavior via mock simulation, but the actual client modules don't implement these patterns. The assumption is that the caller (pipeline layer) implements retry/fallback, but this is not documented in the client module.

**Evidence**:
- `src/architect/mcp_client.py:8-30` — no try/except, no retry
- `src/contract_engine/mcp_client.py:8-107` — no try/except, no retry
- `tests/run4/test_m2_client_wrappers.py:422-452` — retry tested at mock level

**Action Required**: Either add retry/safe-default logic to the client wrappers or document that the calling layer (pipeline) is responsible for resilience patterns.

---

### FINDING-009 — MCP Client Wrappers Create New Session Per Call (No Session Reuse)

**Severity**: LOW
**Requirement**: SVC-001 through SVC-017
**Category**: Performance

**Description**:
Each function in `src/contract_engine/mcp_client.py` spawns a new stdio subprocess, creates a new session, and tears it down:

```python
async def create_contract(...) -> dict:
    server_params = StdioServerParameters(command="python", args=["-m", "src.contract_engine.mcp_server"])
    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            ...
```

This pattern is repeated for all 3 functions (`create_contract`, `validate_spec`, `list_contracts`) and the architect client. Each call incurs full subprocess startup + initialization overhead.

**Evidence**:
- `src/contract_engine/mcp_client.py:27-47, 60-74, 96-107`
- `src/architect/mcp_client.py:18-30`

**Action Required**: Consider session pooling or a persistent client for production usage.

---

### FINDING-010 — Fallback Tests Use Simulated Logic, Not Real Pipeline Integration

**Severity**: LOW
**Requirement**: WIRE-009, WIRE-010, WIRE-011
**Category**: Test Fidelity

**Description**:
The fallback tests (WIRE-009, WIRE-010, WIRE-011) simulate the fallback logic inline using basic Python constructs:

```python
# WIRE-009 test
mcp_available = False
fallback_used = False
try:
    if not mcp_available:
        raise ConnectionError("CE MCP unavailable")
except (ImportError, ConnectionError):
    fallback_used = True
assert fallback_used
```

These tests verify that a fallback *pattern* works conceptually, but do not exercise the actual pipeline's `_call_architect`, `_register_contracts_via_mcp`, or `generate_codebase_map()` fallback paths.

**Evidence**:
- `tests/run4/test_m2_mcp_wiring.py:855-950`

**Action Required**: Consider adding integration-level fallback tests that exercise the real pipeline code paths.

---

### FINDING-011 — Latency Benchmark Tests Mock Responses (No Real Timing)

**Severity**: LOW
**Requirement**: TEST-008
**Category**: Test Fidelity

**Description**:
The latency benchmark test (`TestMCPToolLatencyBenchmark`) uses fully mocked sessions:

```python
session = AsyncMock()
session.call_tool = AsyncMock(return_value=make_mcp_result({"status": "ok"}))
```

AsyncMock returns immediately, so the measured latencies are essentially zero. The test validates that the measurement *framework* works (median, p95, p99 calculations) but provides no real performance data.

**Evidence**: `tests/run4/test_m2_mcp_wiring.py:1000-1045`

**Action Required**: For meaningful benchmarks, run against real MCP server processes (likely as integration tests with a separate marker like `@pytest.mark.integration`).

---

### FINDING-012 — `type` Used as Parameter Name (Shadows Python Built-in)

**Severity**: LOW
**Requirement**: Cross-cutting
**Category**: Naming Convention

**Description**:
Multiple functions use `type` as a parameter name, shadowing the Python built-in:
- `src/contract_engine/mcp_server.py:66` — `create_contract(... type: str ...)`
- `src/contract_engine/mcp_server.py:161` — `validate_contract(spec: dict, type: str)`
- `src/contract_engine/mcp_client.py:10` — `create_contract(... type: str ...)`
- `src/contract_engine/mcp_client.py:50` — `validate_spec(spec: dict, type: str)`

**Evidence**: Multiple files as listed above

**Action Required**: Consider renaming to `contract_type` for clarity and to avoid shadowing. Note: `list_contracts` already uses `contract_type` (mcp_server.py:111).

---

### FINDING-013 — All MCP Servers Perform Module-Level DB Initialization

**Severity**: INFO
**Requirement**: Cross-cutting
**Category**: Testability

**Description**:
All three MCP servers (`architect`, `contract_engine`, `codebase_intelligence`) perform database initialization at module import time:

```python
pool = ConnectionPool(_database_path)
init_architect_db(pool)
service_map_store = ServiceMapStore(pool)
```

This makes the modules difficult to import in test contexts (hence the tests use `importlib.util.find_spec()` instead of direct import). It also means the `DATABASE_PATH` environment variable must be set or default to `./data/*.db` at import time.

**Evidence**:
- `src/architect/mcp_server.py:46-52`
- `src/contract_engine/mcp_server.py:48-56`
- `src/codebase_intelligence/mcp_server.py:62-94`
- `tests/run4/test_m2_client_wrappers.py:880-893` — uses `find_spec` instead of import

**Action Required**: No immediate action required; this is a known MCP SDK pattern. Consider lazy initialization for improved testability in future milestones.

---

### FINDING-014 — Good Practice: Broad Exception Handlers Are Documented

**Severity**: INFO
**Requirement**: Cross-cutting
**Category**: Positive Finding

**Description**:
All three MCP servers consistently use the pattern:
```python
# Top-level handler: broad catch intentional
except Exception as exc:
    logger.exception("Unexpected error ...")
    return {"error": str(exc)}
```

The broad `except Exception` handlers are intentionally documented with comments explaining they are top-level error boundaries for MCP tool safety. This is appropriate for MCP tools where uncaught exceptions would crash the server process.

**Evidence**: Multiple locations across all three mcp_server.py files

**Action Required**: None. Good practice.

---

### FINDING-015 — No Hardcoded Secrets Found in M2-Scoped Code

**Severity**: INFO
**Requirement**: Cross-cutting (security)
**Category**: Positive Finding

**Description**:
A comprehensive search for hardcoded passwords, API keys, tokens, and secrets across the M2-scoped source files (`src/architect/mcp_server.py`, `src/architect/mcp_client.py`, `src/contract_engine/mcp_server.py`, `src/contract_engine/mcp_client.py`, `src/codebase_intelligence/mcp_server.py`, `src/run4/mcp_health.py`, `src/run4/config.py`, and all M2 test files) found no hardcoded credentials.

Configuration values (database paths, service URLs) use environment variables with sensible defaults.

**Evidence**: Grep scan across all M2-scoped files

**Action Required**: None. Good practice.

---

## Requirement-by-Requirement Verification

### REQ-009: Architect MCP Handshake
**Status**: PASS
**Tests**: `TestArchitectMCPHandshake` (2 tests)
**Verification**: Tests verify session initialization and tool listing. Tool set matches the 4 required tools. Server registers tools via `@mcp.tool()` decorators.

### REQ-010: Contract Engine MCP Handshake
**Status**: PASS (with note — see FINDING-007)
**Tests**: `TestContractEngineMCPHandshake` (2 tests)
**Verification**: Tests verify >= 9 tools. Actual server has 10 (includes `check_compliance`).

### REQ-011: Codebase Intelligence MCP Handshake
**Status**: PASS (with note — see FINDING-007)
**Tests**: `TestCodebaseIntelMCPHandshake` (2 tests)
**Verification**: Tests verify >= 7 tools. Actual server has 8 (includes `analyze_graph`).

### REQ-012: Tool Roundtrip Tests
**Status**: PASS (with note — see FINDING-001, FINDING-002, FINDING-003)
**Tests**: 4 Architect + 9 CE + 7 CI + 1 invalid params + 5 response parsing = 26 tests
**Verification**: All 20 spec'd tools are tested with valid params. Invalid params test covers all 20 tools. Response field validation aligns with actual server responses but not spec (see findings).

### REQ-013: ContractEngineClient Tests
**Status**: PASS
**Tests**: 8 test classes covering types, safe defaults, and retry
**Verification**: All 6 CE client methods verified. Safe defaults and 3x exponential retry (1s, 2s, 4s) pattern validated.

### REQ-014: CodebaseIntelligenceClient Tests
**Status**: PASS
**Tests**: 9 test classes
**Verification**: All 7 CI client methods verified. Safe defaults and retry pattern validated.

### REQ-015: ArchitectClient Tests
**Status**: PASS
**Tests**: 5 test classes (plus 1 extra exception-catching test)
**Verification**: decompose, get_service_map, get_contracts_for_service, get_domain_model tested. Failure path returning None verified.

### WIRE-001: Session Sequential Calls
**Status**: PASS
**Verification**: 10 sequential calls on one session verified via `session.call_tool.call_count == 10`.

### WIRE-002: Session Crash Recovery
**Status**: PASS
**Verification**: `BrokenPipeError` raised and caught via `pytest.raises`.

### WIRE-003: Session Timeout
**Status**: PASS (with note — see FINDING-006)
**Verification**: `asyncio.timeout` cancels slow call. Does not use `run4_config` values.

### WIRE-004: Multi-Server Concurrency
**Status**: PASS
**Verification**: 3 sessions opened, `asyncio.gather` used for parallel calls, no conflicts verified.

### WIRE-005: Session Restart Data Access
**Status**: PASS
**Verification**: Two separate sessions created; data from first accessible from second.

### WIRE-006: Malformed JSON Handling
**Status**: PASS
**Verification**: `isError=True` set on malformed result; `json.JSONDecodeError` raised on parse.

### WIRE-007: Nonexistent Tool Call
**Status**: PASS
**Verification**: Error response returned with `isError=True`.

### WIRE-008: Server Exit Detection
**Status**: PASS
**Verification**: `ConnectionError` raised with descriptive message; caught via `pytest.raises`.

### WIRE-009: Fallback CE Unavailable
**Status**: PASS (with note — see FINDING-010)
**Tests**: 2 tests (fallback trigger + valid output)
**Verification**: Fallback path simulated; filesystem contract fallback produces valid JSON.

### WIRE-010: Fallback CI Unavailable
**Status**: PASS (with note — see FINDING-010)
**Tests**: 2 tests (fallback trigger + safe defaults)
**Verification**: Safe default shapes validated for all 7 CI methods.

### WIRE-011: Fallback Architect Unavailable
**Status**: PASS (with note — see FINDING-010)
**Verification**: ImportError caught; subprocess fallback flag set.

### WIRE-012: Cross-Server Contract Lookup
**Status**: PASS
**Verification**: `get_contracts_for_service` mock validates response shape with id, role, type, counterparty. Actual server implementation confirmed to use httpx.Client for cross-server HTTP calls.

### TEST-008: MCP Tool Latency Benchmark
**Status**: PASS (with note — see FINDING-011)
**Verification**: Measurement framework (median, p95, p99) computed correctly. Thresholds (<5s per call, <30s startup) asserted. All values near-zero due to mocking.

### SVC-001 through SVC-017: Wiring Checklist
**Status**: PASS
**Verification**:
- SVC-001–004: Architect tools registered and client wrapper verified
- SVC-005–010: CE tools registered and client wrapper methods tested
- SVC-010a–010c: Direct MCP tools (create_contract, validate_spec, list_contracts) tested via roundtrip and client signature verification
- SVC-011–017: CI tools registered and client wrapper methods tested
- Client module importability verified (`TestArchitectMCPClientWiring`, `TestContractEngineMCPClientWiring`)
- Function signatures verified via `inspect.signature`

---

## Cross-Cutting Quality Assessment

| Check                           | Result | Notes                                           |
|---------------------------------|--------|-------------------------------------------------|
| No hardcoded secrets            | PASS   | Env vars used for all config values             |
| No empty catch blocks           | PASS   | All catch blocks have logging + return/re-raise |
| Type safety                     | WARN   | `make_mcp_result` annotation too narrow (FINDING-004) |
| Consistent naming               | WARN   | `type` shadows built-in in 4 locations (FINDING-012) |
| No deprecated API usage         | PASS   | Uses `mcp.server.fastmcp.FastMCP` (current API) |
| Error handling completeness     | PASS   | Documented broad catches at tool boundaries     |
| Test coverage vs requirements   | PASS   | 81 tests covering all 20+ requirement items     |
| Spec-implementation alignment   | FAIL   | 3 field name mismatches (FINDINGS 001–003)      |

---

## Conclusion

Milestone 2 is **functionally complete** with all 81 tests passing and all requirement IDs covered. The primary technical concern is the **3 response schema field name mismatches** between REQUIREMENTS.md and the actual MCP server implementations (FINDING-001, FINDING-002, FINDING-003). The tests are internally consistent (aligned with actual server output), so they correctly verify real behavior, but the specification document is out of date.

**Recommendation**: Resolve the HIGH-severity findings (FINDING-001, FINDING-002) before downstream milestones consume these response schemas. The field name discrepancies could cause runtime failures in Build 2/Build 3 integration if consumers reference the spec rather than the actual responses.

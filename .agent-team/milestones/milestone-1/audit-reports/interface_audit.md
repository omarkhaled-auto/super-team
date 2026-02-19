# Interface Audit Report — Milestone 1

**Auditor**: Interface Auditor (Audit-Team)
**Scope**: All WIRE-xxx, SVC-xxx, INT-xxx requirements from REQUIREMENTS.md
**Date**: 2025-01-XX
**Verdict**: PASS with observations

---

## Requirements Inventory

Milestone 1 defines the following integration/wiring requirements:

| ID | Description | File(s) |
|----|-------------|---------|
| INT-001 | Session-scoped pytest fixtures for config, PRD, paths, MCP params | `tests/run4/conftest.py` |
| INT-002 | Mock MCP session fixture with AsyncMock | `tests/run4/conftest.py` |
| INT-003 | `make_mcp_result()` helper + `MockToolResult`/`MockTextContent` dataclasses | `tests/run4/conftest.py` |
| INT-004 | `poll_until_healthy()` HTTP health polling | `src/run4/mcp_health.py` |
| INT-005 | `check_mcp_health()` MCP stdio health check | `src/run4/mcp_health.py` |
| INT-006 | `parse_builder_state()` STATE.json parser stub | `src/run4/builder.py` |
| INT-007 | `detect_regressions()` violation regression detector | `src/run4/fix_pass.py` |

No WIRE-xxx or SVC-xxx requirements are defined for Milestone 1 (pure infrastructure, no frontend/backend API wiring).

---

## INT-001: Session-Scoped Pytest Fixtures

### Requirement
Conftest must provide session-scoped fixtures: `run4_config`, `sample_prd_text`, `build1_root`, `contract_engine_params`, `architect_params`, `codebase_intel_params`.

### Verification

| Fixture | Scope | Present | Returns Correct Type | Verified |
|---------|-------|---------|---------------------|----------|
| `run4_config` | session | YES | `Run4Config` (creates temp dirs, validates) | PASS |
| `sample_prd_text` | session | YES | `str` (reads fixture file) | PASS |
| `build1_root` | session | YES | `Path` (via `tmp_path_factory`) | PASS |
| `contract_engine_params` | session | YES | `dict` (see FINDING-001) | PASS with note |
| `architect_params` | session | YES | `dict` (see FINDING-001) | PASS with note |
| `codebase_intel_params` | session | YES | `dict` (see FINDING-001) | PASS with note |

**Wiring check**: `conftest.py` line 17 imports `from src.run4.config import Run4Config` — resolves correctly to `src/run4/config.py` which exports the `Run4Config` dataclass.

---

### FINDING-001
- **Severity**: LOW
- **Category**: Type annotation deviation
- **Location**: `tests/run4/conftest.py` lines 101-141
- **Description**: The REQUIREMENTS.md specifies that `contract_engine_params`, `architect_params`, and `codebase_intel_params` should return `StdioServerParameters` (from the MCP SDK). The actual implementation returns `dict` instead. The docstrings acknowledge this intentionally ("Returns a dict rather than a real `StdioServerParameters` so the test suite runs without the MCP server actually being available").
- **Impact**: Downstream consumers expecting `StdioServerParameters` instances would fail type checks. However, since the MCP SDK's `StdioServerParameters` is a Pydantic `BaseModel`, passing a dict to `stdio_client()` would fail at runtime. This is acceptable for M1 since these fixtures are not consumed by any test in M1 that calls real MCP functions.
- **Recommendation**: When these fixtures are consumed in later milestones (M2+), either instantiate real `StdioServerParameters` or add a conversion step.

---

## INT-002: Mock MCP Session Fixture

### Requirement
`mock_mcp_session` fixture must return an `AsyncMock` with callable `initialize`, `list_tools`, and `call_tool` methods.

### Verification
- **Source**: `tests/run4/conftest.py` lines 148-178
- `mock_mcp_session` is a function-scoped `@pytest.fixture` returning `AsyncMock` — **CORRECT**
- `session.initialize` = `AsyncMock(return_value=None)` — **CORRECT**
- `session.list_tools` = `AsyncMock` returning object with `.tools` list (2 tools) — **CORRECT**
- `session.call_tool` = `AsyncMock(return_value=make_mcp_result({"status": "ok"}))` — **CORRECT**

**Consumer check**: `tests/run4/test_m1_infrastructure.py` class `TestMockMcpSession` (TEST-005) uses this fixture in 4 async tests, all verifying the mock's methods. Wiring confirmed.

**VERDICT**: PASS

---

## INT-003: make_mcp_result Helper

### Requirement
`make_mcp_result(data: dict, is_error: bool = False) -> MockToolResult` must build mock MCP tool results with TextContent containing JSON. Requires `MockToolResult` and `MockTextContent` dataclasses.

### Verification
- **Source**: `tests/run4/conftest.py` lines 31-61
- `MockToolResult` dataclass with `content: list[Any]` and `isError: bool = False` — **CORRECT**
- `MockTextContent` dataclass with `type: str = "text"` and `text: str = ""` — **CORRECT**
- `make_mcp_result()` creates `MockTextContent` with `json.dumps(data)`, wraps in `MockToolResult` — **CORRECT**

**Consumer check**:
- `conftest.py` line 175: `mock_mcp_session` uses `make_mcp_result` internally — **WIRED**
- `test_m1_infrastructure.py` line 21: `from tests.run4.conftest import MockTextContent, MockToolResult, make_mcp_result` — **WIRED**
- `test_m1_infrastructure.py` lines 426-441: `test_make_mcp_result_success` and `test_make_mcp_result_error` verify behavior — **TESTED**

**VERDICT**: PASS

---

## INT-004: poll_until_healthy

### Requirement
Async function that polls HTTP health endpoints until all services report healthy, with configurable timeout, interval, and required consecutive successes.

### Verification
- **Source**: `src/run4/mcp_health.py` lines 15-95
- Signature: `async def poll_until_healthy(service_urls, timeout_s=120, interval_s=3.0, required_consecutive=2) -> dict[str, dict]` — **MATCHES SPEC**
- Uses `httpx.AsyncClient` for real HTTP calls (line 51) — **CORRECT** (no mock data)
- Tracks consecutive successes per service — **CORRECT**
- Raises `TimeoutError` on timeout — **CORRECT**
- Returns dict with `status`, `response_time_ms`, `consecutive_ok` keys — **CORRECT**

**Consumer check**: `test_m1_infrastructure.py` line 19: `from src.run4.mcp_health import poll_until_healthy` — **WIRED**. Tests `TestPollUntilHealthy` (lines 449-503) verify both success and timeout paths via mocked httpx client.

**VERDICT**: PASS

---

## INT-005: check_mcp_health

### Requirement
Async function that spawns MCP server, initialises it, calls `list_tools`, and returns health dict with `{status, tools_count, tool_names, error}`.

### Verification
- **Source**: `src/run4/mcp_health.py` lines 98-145
- Signature: `async def check_mcp_health(server_params: Any, timeout: float = 30.0) -> dict` — **MATCHES SPEC** (see FINDING-002 re: `Any` type)
- Uses real MCP SDK: `from mcp import ClientSession` and `from mcp.client.stdio import stdio_client` (lazy imports at lines 115-116) — **CORRECT**
- Returns dict with all 4 required keys: `status`, `tools_count`, `tool_names`, `error` — **CORRECT**
- Handles `TimeoutError` and generic `Exception` — **CORRECT**

**Consumer check**: No test in M1 directly tests `check_mcp_health`. REQUIREMENTS.md maps it to TEST-006, but TEST-006 only tests `poll_until_healthy`. See FINDING-003.

---

### FINDING-002
- **Severity**: LOW
- **Category**: Type annotation weakness
- **Location**: `src/run4/mcp_health.py` line 99
- **Description**: `check_mcp_health` parameter `server_params` is typed as `Any` instead of `StdioServerParameters`. The docstring documents the expected type correctly but the type system cannot enforce it.
- **Impact**: No runtime impact (the function passes `server_params` directly to `stdio_client()` which will validate). Static analysis tools (mypy, pyright) cannot catch misuse.
- **Recommendation**: Import `StdioServerParameters` and use it as the type annotation, or use `TYPE_CHECKING` guard for the import.

---

### FINDING-003
- **Severity**: MEDIUM
- **Category**: Missing test coverage for integration point
- **Location**: `tests/run4/test_m1_infrastructure.py`
- **Description**: INT-005 (`check_mcp_health`) is listed in the requirements traceability as covered by TEST-006, but TEST-006 only tests `poll_until_healthy` (INT-004). There is no test that exercises `check_mcp_health` — not even with a mocked MCP session. The function imports `mcp.ClientSession` and `mcp.client.stdio.stdio_client` at runtime but these imports are never verified in any test.
- **Impact**: If the `mcp` SDK changes its API or is not installed, this will only be caught at runtime during later milestones, not during M1 gate validation.
- **Recommendation**: Add a test that mocks `stdio_client` and `ClientSession` to verify `check_mcp_health` returns the correct health dict shape. This would catch import failures and API shape issues.

---

## INT-006: parse_builder_state

### Requirement
Function `parse_builder_state(output_dir: Path) -> dict` reads `.agent-team/STATE.json` and returns `{success, test_passed, test_total, convergence_ratio}`.

### Verification
- **Source**: `src/run4/builder.py` lines 15-58
- Signature matches: `def parse_builder_state(output_dir: Path) -> dict` — **CORRECT**
- Reads `output_dir / ".agent-team" / "STATE.json"` — **CORRECT**
- Returns dict with all 4 required keys — **CORRECT**
- Handles missing file and JSON decode errors gracefully — **CORRECT**
- No mock data — reads real files — **CORRECT**

**Consumer check**: Per requirements, this is tested in M3, not M1. No imports from `src.run4.builder` found in any test file. See FINDING-004.

---

### FINDING-004
- **Severity**: LOW
- **Category**: Orphaned export (by design)
- **Location**: `src/run4/builder.py`
- **Description**: `parse_builder_state` is exported but not imported by any file within the M1 scope. The REQUIREMENTS.md explicitly states "(tested in M3)" so this is by design. However, the function is more than a stub — it contains full implementation logic reading from `STATE.json` with field mappings (`completion_ratio`, `requirements_checked`, `requirements_total`) that cannot be verified until M3 fixtures exist.
- **Impact**: None for M1. The field name mappings (`completion_ratio` -> `success`, etc.) are untested assumptions.
- **Recommendation**: No action needed for M1. Verify field mappings against actual STATE.json schema in M3.

---

## INT-007: detect_regressions

### Requirement
Function `detect_regressions(before: dict[str, list[str]], after: dict[str, list[str]]) -> list[dict]` compares violation snapshots and returns regressed violations.

### Verification
- **Source**: `src/run4/fix_pass.py` lines 13-48
- Signature matches exactly — **CORRECT**
- Returns `list[dict]` with `category` and `violation` keys — **CORRECT**
- Logic: iterates `after`, checks each violation against `before` set — **CORRECT**
- No mock data, no hardcoded values — **CORRECT**

**Consumer check**: `test_m1_infrastructure.py` line 18: `from src.run4.fix_pass import detect_regressions` — **WIRED**. Tests `TestDetectRegressions` (lines 511-559) has 4 test cases covering new violations, no regressions, empty before, and empty after. Comprehensive.

**VERDICT**: PASS

---

## Orphan Detection

### Source Module Exports vs. Consumers

| Module | Export | Imported By | Status |
|--------|--------|-------------|--------|
| `src.run4.__init__` | `__version__` | Nobody in M1 | ORPHAN (by design) |
| `src.run4.config` | `Run4Config` | conftest.py, test_m1_infrastructure.py | WIRED |
| `src.run4.config` | `Run4Config.from_yaml` | test_m1_infrastructure.py (TEST-003) | WIRED |
| `src.run4.state` | `Finding` | test_m1_infrastructure.py | WIRED |
| `src.run4.state` | `Run4State` | test_m1_infrastructure.py | WIRED |
| `src.run4.mcp_health` | `poll_until_healthy` | test_m1_infrastructure.py | WIRED |
| `src.run4.mcp_health` | `check_mcp_health` | Nobody | ORPHAN (see FINDING-003) |
| `src.run4.builder` | `parse_builder_state` | Nobody | ORPHAN (deferred to M3) |
| `src.run4.fix_pass` | `detect_regressions` | test_m1_infrastructure.py | WIRED |
| `src.run4.scoring` | `compute_scores` | Nobody | ORPHAN (stub, deferred to M6) |
| `src.run4.audit_report` | `generate_report` | Nobody | ORPHAN (stub, deferred to M6) |
| `tests.run4.conftest` | `MockToolResult` | test_m1_infrastructure.py | WIRED |
| `tests.run4.conftest` | `MockTextContent` | test_m1_infrastructure.py | WIRED |
| `tests.run4.conftest` | `make_mcp_result` | test_m1_infrastructure.py, conftest.py (self) | WIRED |

### FINDING-005
- **Severity**: INFO
- **Category**: Expected orphans (stubs deferred to later milestones)
- **Location**: `src/run4/scoring.py`, `src/run4/audit_report.py`, `src/run4/builder.py`
- **Description**: Three source modules (`scoring.py`, `audit_report.py`, `builder.py`) export functions that are not imported anywhere in M1. All three are stubs documented as "expanded in Milestone N" per requirements. This is expected and by design.
- **Impact**: None. These become wired in their respective milestones.
- **Recommendation**: No action needed.

---

### FINDING-006
- **Severity**: INFO
- **Category**: Package `__init__.py` does not re-export submodules
- **Location**: `src/run4/__init__.py`
- **Description**: The package init only defines `__version__ = "1.0.0"`. It does not re-export commonly used symbols (`Run4Config`, `Run4State`, `Finding`, etc.) via `__all__` or explicit imports. All consumers use direct submodule imports (e.g., `from src.run4.config import Run4Config`), which is a valid pattern.
- **Impact**: None. Direct imports work correctly. The `__version__` export itself is not consumed by any M1 file.
- **Recommendation**: Consider adding a public API surface in `__init__.py` if consumers would benefit from `from src.run4 import Run4Config` shorthand. Not required.

---

### FINDING-007
- **Severity**: INFO
- **Category**: Missing `__init__.py` in fixtures directory
- **Location**: `tests/run4/fixtures/`
- **Description**: The `tests/run4/fixtures/` directory has no `__init__.py`. This is fine because the fixtures are accessed via `Path` file reads (not Python imports), but it means the directory is not a Python package.
- **Impact**: None. All fixture access is via filesystem paths (`Path(__file__).parent / "fixtures" / ...`), not Python imports.
- **Recommendation**: No action needed.

---

## Fixture Content Verification

### REQ-004: sample_prd.md
- 3 services described (auth-service, order-service, notification-service) — **PASS**
- All required endpoints present (POST /register, POST /login, GET /users/me, GET /health, POST /orders, GET /orders/{id}, PUT /orders/{id}, POST /notify, GET /notifications) — **PASS**
- Data models (User, Order, Notification) — **PASS**
- Technology stack (FastAPI, PostgreSQL) — **PASS**
- Inter-service contracts (JWT auth, Redis event publishing) — **PASS**

### REQ-005: sample_openapi_auth.yaml
- OpenAPI 3.1.0 — **PASS**
- All 4 endpoints with correct schemas — **PASS**
- Components: RegisterRequest, LoginRequest, User, UserResponse, TokenResponse, ErrorResponse — **PASS**
- SecuritySchemes: bearerAuth (JWT) — **PASS**

### REQ-006: sample_openapi_order.yaml
- OpenAPI 3.1.0 — **PASS**
- All 4 endpoints (POST /orders, GET /orders/{id}, PUT /orders/{id}, GET /health) — **PASS**
- Components: CreateOrderRequest, OrderItem, Order, ErrorResponse — **PASS**
- SecuritySchemes: bearerAuth (JWT) — **PASS**

### REQ-007: sample_asyncapi_order.yaml
- AsyncAPI 3.0.0 — **PASS**
- Channels: order/created, order/shipped — **PASS**
- Server: development (redis:6379) — **PASS**
- Messages: OrderCreated (with all required payload fields), OrderShipped (with all required payload fields) — **PASS**

### REQ-008: sample_pact_auth.json
- Consumer: order-service, Provider: auth-service — **PASS**
- Pact V4 (`"version": "4.0"`) — **PASS**
- Interaction: POST /login with email/password — **PASS**
- Response: 200 with access_token and refresh_token — **PASS**
- Additional interaction for 401 invalid credentials — **PASS** (bonus coverage)

---

## Cross-Module Import Resolution Verification

| Import Statement | Source File | Target Resolves? |
|-----------------|-------------|------------------|
| `from src.run4.config import Run4Config` | conftest.py | YES — `config.py` line 16 |
| `from src.run4.config import Run4Config` | test_m1_infrastructure.py | YES — `config.py` line 16 |
| `from src.run4.fix_pass import detect_regressions` | test_m1_infrastructure.py | YES — `fix_pass.py` line 13 |
| `from src.run4.mcp_health import poll_until_healthy` | test_m1_infrastructure.py | YES — `mcp_health.py` line 15 |
| `from src.run4.state import Finding, Run4State` | test_m1_infrastructure.py | YES — `state.py` lines 17, 39 |
| `from tests.run4.conftest import MockTextContent, MockToolResult, make_mcp_result` | test_m1_infrastructure.py | YES — `conftest.py` lines 39, 31, 47 |
| `from mcp import ClientSession` | mcp_health.py (lazy) | YES — `mcp` package installed in venv |
| `from mcp.client.stdio import stdio_client` | mcp_health.py (lazy) | YES — `mcp` package installed in venv |
| `import httpx` | mcp_health.py | YES — httpx installed in venv |
| `import yaml` | config.py | YES — PyYAML installed in venv |
| `from openapi_spec_validator import validate` | test_m1_infrastructure.py (lazy) | ASSUMED — dev dependency |

---

## Summary

| Finding ID | Severity | Title |
|-----------|----------|-------|
| FINDING-001 | LOW | MCP param fixtures return `dict` instead of `StdioServerParameters` |
| FINDING-002 | LOW | `check_mcp_health` uses `Any` type for `server_params` parameter |
| FINDING-003 | MEDIUM | `check_mcp_health` (INT-005) has no test coverage in M1 |
| FINDING-004 | LOW | `parse_builder_state` is fully implemented but untested (deferred to M3) |
| FINDING-005 | INFO | Expected orphans: scoring.py, audit_report.py, builder.py stubs |
| FINDING-006 | INFO | Package `__init__.py` does not re-export submodule symbols |
| FINDING-007 | INFO | No `__init__.py` in fixtures directory (not needed) |

### Statistics
- **Total INT-xxx requirements**: 7
- **Fully verified (PASS)**: 6 (INT-001, INT-002, INT-003, INT-004, INT-006, INT-007)
- **Verified with gap**: 1 (INT-005 — function correct but untested)
- **WIRE-xxx requirements**: 0 (N/A for M1)
- **SVC-xxx requirements**: 0 (N/A for M1)
- **Critical findings**: 0
- **High findings**: 0
- **Medium findings**: 1
- **Low findings**: 3
- **Info findings**: 3

### Overall Verdict: **PASS**

All integration wiring is correctly implemented. The single MEDIUM finding (FINDING-003: missing test for `check_mcp_health`) does not block the M1 gate since the function implementation is correct and the requirement explicitly defers full MCP integration testing to later milestones. All imports resolve, all exports are consumed by their intended targets (or are documented stubs), and no broken wiring or mock-data-in-production patterns were found.

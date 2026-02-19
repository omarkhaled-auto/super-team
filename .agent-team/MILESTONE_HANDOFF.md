# Milestone Handoff Document

This document tracks the exposed interfaces, database state, and integration
contracts for each completed milestone. Successor milestones MUST consume
these interfaces exactly as documented.

---

## Milestone 1: Test Infrastructure + Fixtures

**Status**: COMPLETE
**Date**: 2026-02-19
**Test Results**: 31/31 tests passing (0 failures)

### Exposed Interfaces

#### Source Module Exports

| Module | Export | Signature | Description |
|--------|--------|-----------|-------------|
| `src.run4.config` | `Run4Config` | `@dataclass` | Pipeline config with build paths, timeouts, limits |
| `src.run4.config` | `Run4Config.from_yaml` | `(path: str) -> Run4Config` | Parse `run4:` section from YAML |
| `src.run4.state` | `Finding` | `@dataclass` | Defect record with FINDING-NNN id, priority, system, resolution |
| `src.run4.state` | `Run4State` | `@dataclass` | Full pipeline state with atomic save/load |
| `src.run4.state` | `Run4State.save` | `(path: Path) -> None` | Atomic write via tmp+os.replace |
| `src.run4.state` | `Run4State.load` | `(path: Path) -> Run4State \| None` | Load with schema_version=1 validation |
| `src.run4.state` | `Run4State.add_finding` | `(finding: Finding) -> None` | Append to findings, auto-assign id |
| `src.run4.state` | `Run4State.next_finding_id` | `() -> str` | Returns FINDING-NNN (auto-increment) |
| `src.run4.mcp_health` | `poll_until_healthy` | `(service_urls, timeout_s, interval_s, required_consecutive) -> dict` | HTTP health polling |
| `src.run4.mcp_health` | `check_mcp_health` | `(server_params, timeout) -> dict` | MCP stdio health check |
| `src.run4.builder` | `parse_builder_state` | `(output_dir: Path) -> dict` | Parse .agent-team/STATE.json (stub) |
| `src.run4.fix_pass` | `detect_regressions` | `(before, after) -> list[dict]` | Find new violations between snapshots |
| `src.run4.scoring` | `compute_scores` | `(findings, weights) -> dict[str, float]` | Category scoring (stub) |
| `src.run4.audit_report` | `generate_report` | `(state, output_path) -> str` | Markdown report (stub) |

#### Test Utility Exports

| Module | Export | Signature | Description |
|--------|--------|-----------|-------------|
| `tests.run4.conftest` | `make_mcp_result` | `(data: dict, is_error: bool) -> MockToolResult` | Build mock MCP tool results |
| `tests.run4.conftest` | `MockToolResult` | `@dataclass` | Mock for MCP CallToolResult |
| `tests.run4.conftest` | `MockTextContent` | `@dataclass` | Mock for MCP TextContent |

#### Pytest Fixtures (available to all tests/run4/ tests)

| Fixture | Scope | Returns | Description |
|---------|-------|---------|-------------|
| `run4_config` | session | `Run4Config` | Config with valid temp build roots |
| `sample_prd_text` | session | `str` | Content of sample_prd.md |
| `build1_root` | session | `Path` | Temp directory for Build 1 root |
| `contract_engine_params` | session | `dict` | StdioServerParameters-compatible dict |
| `architect_params` | session | `dict` | StdioServerParameters-compatible dict |
| `codebase_intel_params` | session | `dict` | StdioServerParameters-compatible dict |
| `mock_mcp_session` | function | `AsyncMock` | Mock MCP ClientSession with initialize/list_tools/call_tool |

### Enum/Status Values

| Entity | Field | Valid Values | Storage | API Representation |
|--------|-------|-------------|---------|-------------------|
| `Finding` | `priority` | P0, P1, P2, P3 | str | Same |
| `Finding` | `system` | "Build 1", "Build 2", "Build 3", "Integration" | str | Same |
| `Finding` | `resolution` | "FIXED", "OPEN", "WONTFIX" | str | Same |
| `Run4State` | `current_phase` | "init", "health_check", "builders", "contracts", "fix_pass", "scoring" | str | Same |
| `Run4State` | `traffic_light` | "RED", "YELLOW", "GREEN" | str | Same |
| `Run4State` | `schema_version` | 1 | int | Same |

### Database State

No database tables created. All persistence is via JSON files:
- `Run4State` → `{output_dir}/run4_state.json` (atomic write)

### Environment Variables

No new environment variables introduced. All configuration flows through
`Run4Config` which is loaded from YAML or constructed directly.

### Test Fixture Files

| File | Format | Description |
|------|--------|-------------|
| `tests/run4/fixtures/sample_prd.md` | Markdown | TaskTracker PRD (auth, order, notification services) |
| `tests/run4/fixtures/sample_openapi_auth.yaml` | OpenAPI 3.1 | Auth service API spec |
| `tests/run4/fixtures/sample_openapi_order.yaml` | OpenAPI 3.1 | Order service API spec |
| `tests/run4/fixtures/sample_asyncapi_order.yaml` | AsyncAPI 3.0 | Order event channels |
| `tests/run4/fixtures/sample_pact_auth.json` | Pact V4 | Consumer contract (order→auth) |

### Known Limitations

1. **MCP fixture params are dicts, not StdioServerParameters**: The session-scoped
   `contract_engine_params`, `architect_params`, and `codebase_intel_params` fixtures
   return plain dicts. Downstream milestones that call `check_mcp_health()` should
   construct `StdioServerParameters` from these dicts.

2. **Stubs for future milestones**: `builder.py`, `fix_pass.py`, `scoring.py`, and
   `audit_report.py` are minimal stubs. M3 expands builder, M5 expands fix_pass,
   M6 expands scoring and audit_report.

3. **No AsyncAPI validator**: AsyncAPI 3.0 fixtures are validated structurally
   (key presence checks) rather than with a formal schema validator library,
   since no mature Python AsyncAPI 3.0 validator exists.

### Files Created

| File | LOC | Purpose |
|------|-----|---------|
| `src/run4/__init__.py` | 7 | Package init + version |
| `src/run4/config.py` | 95 | Run4Config dataclass |
| `src/run4/state.py` | 175 | Finding + Run4State dataclasses |
| `src/run4/mcp_health.py` | 120 | Health check utilities |
| `src/run4/builder.py` | 50 | Builder state parser (stub) |
| `src/run4/fix_pass.py` | 45 | Regression detector |
| `src/run4/scoring.py` | 20 | Scoring stub |
| `src/run4/audit_report.py` | 25 | Report stub |
| `tests/run4/__init__.py` | 2 | Test package init |
| `tests/run4/conftest.py` | 140 | Fixtures + mock MCP utilities |
| `tests/run4/test_m1_infrastructure.py` | 330 | 31 test cases |
| `tests/run4/fixtures/sample_prd.md` | 190 | Sample PRD |
| `tests/run4/fixtures/sample_openapi_auth.yaml` | 150 | Auth OpenAPI spec |
| `tests/run4/fixtures/sample_openapi_order.yaml` | 185 | Order OpenAPI spec |
| `tests/run4/fixtures/sample_asyncapi_order.yaml` | 120 | Order AsyncAPI spec |
| `tests/run4/fixtures/sample_pact_auth.json` | 80 | Pact V4 contract |


---

## milestone-1: Test Infrastructure + Fixtures — COMPLETE

### Exposed Interfaces

> **NOTE**: Milestone 1 creates NO HTTP API endpoints or REST services. It builds
> Python dataclasses, utility functions, test fixtures, and mock infrastructure that
> all subsequent milestones depend on. The "interfaces" are Python module exports.

#### Source Module Exports (exact signatures verified from implementation)

| Module | Export | Signature | Return Type | Description |
|--------|--------|-----------|-------------|-------------|
| `src.run4` | `__version__` | _(constant)_ | `str` — `"1.0.0"` | Package version |
| `src.run4.config` | `Run4Config` | `@dataclass` — fields: `build1_project_root: Path`, `build2_project_root: Path`, `build3_project_root: Path`, `output_dir: str = ".run4"`, `compose_project_name: str = "super-team-run4"`, `docker_compose_files: list[str] = []`, `health_check_timeout_s: int = 120`, `health_check_interval_s: float = 3.0`, `mcp_startup_timeout_ms: int = 30000`, `mcp_tool_timeout_ms: int = 60000`, `mcp_first_start_timeout_ms: int = 120000`, `max_concurrent_builders: int = 3`, `builder_timeout_s: int = 1800`, `builder_depth: str = "thorough"`, `max_fix_passes: int = 5`, `fix_effectiveness_floor: float = 0.30`, `regression_rate_ceiling: float = 0.25`, `max_budget_usd: float = 100.0`, `sample_prd_path: str = "tests/run4/fixtures/sample_prd.md"` | `Run4Config` | `__post_init__` validates build path existence, converts strings to `Path`, raises `ValueError` if missing |
| `src.run4.config` | `Run4Config.from_yaml` | `(path: str) -> Run4Config` | `Run4Config` | Parse `run4:` section from YAML; raises `FileNotFoundError` if file missing, `ValueError` if no `run4:` section; unknown keys silently ignored |
| `src.run4.state` | `Finding` | `@dataclass` — fields: `finding_id: str = ""`, `priority: str = ""`, `system: str = ""`, `component: str = ""`, `evidence: str = ""`, `recommendation: str = ""`, `resolution: str = "OPEN"`, `fix_pass_number: int = 0`, `fix_verification: str = ""`, `created_at: str = <auto ISO8601 UTC>` | `Finding` | Single defect record; default `created_at` = `datetime.now(timezone.utc).isoformat()` |
| `src.run4.state` | `Run4State` | `@dataclass` — fields: `schema_version: int = 1`, `run_id: str = <uuid4[:12]>`, `current_phase: str = "init"`, `completed_phases: list[str] = []`, `mcp_health: dict[str, dict] = {}`, `builder_results: dict[str, dict] = {}`, `findings: list[Finding] = []`, `fix_passes: list[dict] = []`, `scores: dict[str, float] = {}`, `aggregate_score: float = 0.0`, `traffic_light: str = "RED"`, `total_cost: float = 0.0`, `phase_costs: dict[str, float] = {}`, `started_at: str = <auto ISO8601 UTC>`, `updated_at: str = <auto ISO8601 UTC>` | `Run4State` | Full pipeline state with atomic persistence |
| `src.run4.state` | `Run4State.save` | `(self, path: Path) -> None` | `None` | Atomic write: updates `updated_at`, serializes via `dataclasses.asdict`, writes to `.tmp`, then `os.replace`; creates parent dirs |
| `src.run4.state` | `Run4State.load` | `(cls, path: Path) -> Run4State \| None` | `Run4State \| None` | Returns `None` for: missing file, corrupted JSON, non-dict JSON, `schema_version != 1`; reconstructs nested `Finding` objects; filters unknown keys |
| `src.run4.state` | `Run4State.add_finding` | `(self, finding: Finding) -> None` | `None` | Appends finding; auto-assigns `finding_id` via `next_finding_id()` if `finding_id` is empty string |
| `src.run4.state` | `Run4State.next_finding_id` | `(self) -> str` | `str` | Returns `"FINDING-NNN"` zero-padded to 3 digits; starts at `FINDING-001`; increments from max existing id |
| `src.run4.mcp_health` | `poll_until_healthy` | `async (service_urls: dict[str, str], timeout_s: float = 120, interval_s: float = 3.0, required_consecutive: int = 2) -> dict[str, dict]` | `dict[str, dict]` — per-service: `{ status: "healthy"\|"unhealthy"\|"error", response_time_ms: float, consecutive_ok: int, [http_status: int], [error: str] }` | Polls HTTP health endpoints; raises `TimeoutError` if not all healthy within timeout |
| `src.run4.mcp_health` | `check_mcp_health` | `async (server_params: Any, timeout: float = 30.0) -> dict` | `dict` — `{ status: "healthy"\|"unhealthy", tools_count: int, tool_names: list[str], error: str\|None }` | Spawns MCP stdio server via `mcp` SDK, calls `initialize()` + `list_tools()`; catches `TimeoutError` and generic `Exception` |
| `src.run4.builder` | `parse_builder_state` | `(output_dir: Path) -> dict` | `dict` — `{ success: bool, test_passed: int, test_total: int, convergence_ratio: float }` | Reads `{output_dir}/.agent-team/STATE.json`; `success = completion_ratio >= 1.0`; returns failure dict if file missing/corrupt **(STUB — expanded in M3)** |
| `src.run4.fix_pass` | `detect_regressions` | `(before: dict[str, list[str]], after: dict[str, list[str]]) -> list[dict]` | `list[dict]` — each: `{ category: str, violation: str }` | Finds violations in `after` not present in `before` **(STUB — expanded in M5)** |
| `src.run4.scoring` | `compute_scores` | `(findings: list, weights: dict\|None = None) -> dict[str, float]` | `dict[str, float]` | Returns `{}` always **(STUB — expanded in M6)** |
| `src.run4.audit_report` | `generate_report` | `(state: object, output_path: Path\|None = None) -> str` | `str` | Returns placeholder markdown **(STUB — expanded in M6)** |

#### Test Utility Exports (importable from `tests.run4.conftest`)

| Export | Type | Fields / Signature | Description |
|--------|------|-------------------|-------------|
| `MockToolResult` | `@dataclass` | `content: list[Any], isError: bool = False` | Stand-in for MCP `CallToolResult` |
| `MockTextContent` | `@dataclass` | `type: str = "text", text: str = ""` | Stand-in for MCP `TextContent` |
| `make_mcp_result` | `function` | `(data: dict, is_error: bool = False) -> MockToolResult` | JSON-encodes `data` into `MockTextContent.text`, wraps in `MockToolResult` |

#### Pytest Fixtures (available to all `tests/run4/` tests)

| Fixture | Scope | Return Type | Exact Value | Description |
|---------|-------|-------------|-------------|-------------|
| `run4_config` | `session` | `Run4Config` | Config with 3 temp build-root dirs | Creates dirs via `tmp_path_factory` to satisfy path validation |
| `sample_prd_text` | `session` | `str` | Full text of `tests/run4/fixtures/sample_prd.md` | Loaded via `Path.read_text(encoding="utf-8")` |
| `build1_root` | `session` | `Path` | Temp directory | Isolated temp dir for Build 1 root |
| `contract_engine_params` | `session` | `dict` | `{ command: "python", args: ["-m", "src.contract_engine.mcp_server"], env: { DATABASE_PATH: "./data/contracts.db" } }` | StdioServerParameters-compatible dict |
| `architect_params` | `session` | `dict` | `{ command: "python", args: ["-m", "src.architect.mcp_server"], env: { DATABASE_PATH: "./data/architect.db", CONTRACT_ENGINE_URL: "http://localhost:8002" } }` | StdioServerParameters-compatible dict |
| `codebase_intel_params` | `session` | `dict` | `{ command: "python", args: ["-m", "src.codebase_intelligence.mcp_server"], env: { DATABASE_PATH: "./data/symbols.db", CHROMA_PATH: "./data/chroma", GRAPH_PATH: "./data/graph.json" } }` | StdioServerParameters-compatible dict |
| `mock_mcp_session` | `function` | `AsyncMock` | `initialize()→None`, `list_tools()→{tools: [tool_a, tool_b]}`, `call_tool()→make_mcp_result({"status":"ok"})` | Mock MCP `ClientSession` |

### Database State After This Milestone

**No database tables created.** All persistence is JSON files:

| Persistence Target | File Path | Format | Write Method |
|-------------------|-----------|--------|--------------|
| `Run4State` | `{Run4Config.output_dir}/run4_state.json` (default: `.run4/run4_state.json`) | JSON | Atomic write (`.tmp` + `os.replace`) |
| Builder STATE (read-only) | `{output_dir}/.agent-team/STATE.json` | JSON | Read by `parse_builder_state()` |

**Run4State on-disk JSON schema:**
```json
{
  "schema_version": 1,
  "run_id": "string (12-char UUID prefix)",
  "current_phase": "string",
  "completed_phases": ["string"],
  "mcp_health": { "<service_name>": { "status": "string", "tools_count": "int" } },
  "builder_results": { "<service_name>": { "success": "bool", "test_passed": "int", "test_total": "int" } },
  "findings": [
    {
      "finding_id": "FINDING-NNN",
      "priority": "P0|P1|P2|P3",
      "system": "Build 1|Build 2|Build 3|Integration",
      "component": "string",
      "evidence": "string",
      "recommendation": "string",
      "resolution": "FIXED|OPEN|WONTFIX",
      "fix_pass_number": 0,
      "fix_verification": "string",
      "created_at": "ISO8601 string"
    }
  ],
  "fix_passes": [{ "pass_number": "int", "fixed": "int", "remaining": "int" }],
  "scores": { "<category>": "float (0.0-1.0)" },
  "aggregate_score": 0.0,
  "traffic_light": "RED|YELLOW|GREEN",
  "total_cost": 0.0,
  "phase_costs": { "<phase>": "float" },
  "started_at": "ISO8601 string",
  "updated_at": "ISO8601 string"
}
```

### Enum/Status Values

| Entity | Field | Valid Values | DB Type | API String | Default | Notes |
|--------|-------|-------------|---------|------------|---------|-------|
| `Finding` | `priority` | `"P0"`, `"P1"`, `"P2"`, `"P3"` | `str` | Same (exact string) | `""` (empty) | Severity; P0 = critical. No runtime enforcement. |
| `Finding` | `system` | `"Build 1"`, `"Build 2"`, `"Build 3"`, `"Integration"` | `str` | Same (exact string, includes space) | `""` (empty) | Which build/phase. No runtime enforcement. |
| `Finding` | `resolution` | `"OPEN"`, `"FIXED"`, `"WONTFIX"` | `str` | Same (UPPERCASE) | `"OPEN"` | Defect lifecycle state. No runtime enforcement. |
| `Finding` | `finding_id` | Pattern: `"FINDING-NNN"` (zero-padded 3 digits, e.g. `"FINDING-001"`) | `str` | Same | `""` (auto-assigned) | Auto-increments from max existing |
| `Run4State` | `current_phase` | `"init"`, `"health_check"`, `"builders"`, `"contracts"`, `"fix_pass"`, `"scoring"` | `str` | Same (lowercase) | `"init"` | No state machine; any string accepted |
| `Run4State` | `traffic_light` | `"RED"`, `"YELLOW"`, `"GREEN"` | `str` | Same (UPPERCASE) | `"RED"` | Quality verdict |
| `Run4State` | `schema_version` | `1` (only valid; load rejects others) | `int` | `1` (integer in JSON) | `1` | Forward-compat gate |
| `Run4Config` | `builder_depth` | `"thorough"`, `"quick"` (known from tests; not enforced) | `str` | N/A | `"thorough"` | Builder pass depth setting |
| `poll_until_healthy` result | `status` | `"healthy"`, `"unhealthy"`, `"error"` | `str` (in-memory) | Same | N/A | Per-service health |
| `check_mcp_health` result | `status` | `"healthy"`, `"unhealthy"` | `str` (in-memory) | Same | `"unhealthy"` | MCP server health |
| Fixture: Order OpenAPI | `Order.status` | `"created"`, `"confirmed"`, `"shipped"`, `"delivered"`, `"cancelled"` | `str` (enum in spec) | Same | N/A | Order lifecycle in fixture |
| Fixture: PRD | `Notification.type` | `"email"`, `"in_app"`, `"sms"` | `str` (enum in PRD) | Same | N/A | Notification types in fixture |
| Fixture: PRD | `Notification.status` | `"pending"`, `"sent"`, `"failed"` | `str` (enum in PRD) | Same | N/A | Notification states in fixture |
| Fixture: Auth OpenAPI | `health.status` | `"healthy"` | `str` (enum in spec) | Same | N/A | Health endpoint response |

### Environment Variables

**No new environment variables introduced by M1 source code.**
All configuration flows through `Run4Config` (YAML or direct construction).

The test fixture MCP param dicts reference these env vars (documentation only, NOT read at M1 runtime):

| Variable | Fixture | Purpose | Example |
|----------|---------|---------|---------|
| `DATABASE_PATH` | `contract_engine_params` | SQLite path for contract-engine MCP | `"./data/contracts.db"` |
| `DATABASE_PATH` | `architect_params` | SQLite path for architect MCP | `"./data/architect.db"` |
| `CONTRACT_ENGINE_URL` | `architect_params` | URL for contract-engine dependency | `"http://localhost:8002"` |
| `DATABASE_PATH` | `codebase_intel_params` | SQLite path for codebase-intel MCP | `"./data/symbols.db"` |
| `CHROMA_PATH` | `codebase_intel_params` | ChromaDB vector store path | `"./data/chroma"` |
| `GRAPH_PATH` | `codebase_intel_params` | Call-graph JSON path | `"./data/graph.json"` |

### Files Created/Modified

| File | LOC | Purpose |
|------|-----|---------|
| `src/run4/__init__.py` | 7 | Package init; exports `__version__ = "1.0.0"` |
| `src/run4/config.py` | 104 | `Run4Config` dataclass with path validation + `from_yaml` factory |
| `src/run4/state.py` | 203 | `Finding` + `Run4State` dataclasses with atomic save/load, finding management |
| `src/run4/mcp_health.py` | 146 | `poll_until_healthy` (HTTP) + `check_mcp_health` (MCP stdio) |
| `src/run4/builder.py` | 59 | `parse_builder_state` — reads `.agent-team/STATE.json` (stub for M3) |
| `src/run4/fix_pass.py` | 49 | `detect_regressions` — violation snapshot diff (stub for M5) |
| `src/run4/scoring.py` | 25 | `compute_scores` — returns `{}` always (stub for M6) |
| `src/run4/audit_report.py` | 26 | `generate_report` — returns placeholder markdown (stub for M6) |
| `tests/run4/__init__.py` | 2 | Test package init |
| `tests/run4/conftest.py` | 179 | 6 session fixtures + 1 function fixture + `MockToolResult` + `MockTextContent` + `make_mcp_result` |
| `tests/run4/test_m1_infrastructure.py` | 560 | 31 tests across 8 test classes |
| `tests/run4/fixtures/sample_prd.md` | 270 | TaskTracker PRD: 3 services (auth, order, notification) |
| `tests/run4/fixtures/sample_openapi_auth.yaml` | 213 | OpenAPI 3.1: auth-service — schemas: RegisterRequest, LoginRequest, User, UserResponse, TokenResponse, ErrorResponse |
| `tests/run4/fixtures/sample_openapi_order.yaml` | 251 | OpenAPI 3.1: order-service — schemas: CreateOrderRequest, OrderItem, Order, ErrorResponse |
| `tests/run4/fixtures/sample_asyncapi_order.yaml` | 125 | AsyncAPI 3.0: channels `order/created` (OrderCreated), `order/shipped` (OrderShipped) |
| `tests/run4/fixtures/sample_pact_auth.json` | 98 | Pact V4: consumer=order-service, provider=auth-service, 2 interactions |

#### Fixture Schemas (downstream milestones that parse these must use these exact shapes)

**Auth OpenAPI schemas:**
- `RegisterRequest`: `{ email: string(email), password: string(minLength:8), name: string(minLength:1) }` — all required
- `LoginRequest`: `{ email: string(email), password: string }` — all required
- `User`: `{ id: string(uuid), email: string(email), name: string, created_at: string(date-time) }` — all required
- `UserResponse`: `{ id: string(uuid), email: string(email), created_at: string(date-time) }` — all required
- `TokenResponse`: `{ access_token: string, refresh_token: string }` — all required
- `ErrorResponse`: `{ detail: string }` — required

**Order OpenAPI schemas:**
- `CreateOrderRequest`: `{ items: array[OrderItem](minItems:1) }` — required
- `OrderItem`: `{ product_id: string, quantity: integer(min:1), price: number(float, min:0) }` — all required
- `Order`: `{ id: string(uuid), user_id?: string(uuid), status: enum["created","confirmed","shipped","delivered","cancelled"], items: array[OrderItem], total: number(float), created_at?: string(date-time), updated_at?: string(date-time) }` — required: id, status, items, total
- `PUT /orders/{id}` response: `{ id: string(uuid), status: string, updated_at: string(date-time) }` — all required

**AsyncAPI message payloads:**
- `OrderCreated`: `{ order_id: string(uuid), user_id: string(uuid), items: array[{product_id: string, quantity: int(min:1), price: number(float,min:0)}], total: number(float), created_at: string(date-time) }` — all required
- `OrderShipped`: `{ order_id: string(uuid), user_id: string(uuid), shipped_at: string(date-time), tracking_number: string }` — all required

**Pact interactions:**
1. Success: `POST /login` with `{ email: "testuser@example.com", password: "securepassword123" }` → `200 { access_token: string(JWT), refresh_token: string(JWT) }` (type-matched)
2. Failure: `POST /login` with `{ email: "nonexistent@example.com", password: "wrongpassword" }` → `401 { detail: "Invalid credentials" }`

### Known Limitations

1. **MCP fixture params are plain `dict`, NOT `StdioServerParameters`**: The session-scoped
   `contract_engine_params`, `architect_params`, and `codebase_intel_params` fixtures return
   `dict` objects. Downstream milestones calling `check_mcp_health()` MUST construct
   `StdioServerParameters` from these dicts (e.g., `StdioServerParameters(**params)`).

2. **Stubs return minimal data**: `scoring.py` (`compute_scores`) returns `{}` always;
   `audit_report.py` (`generate_report`) returns placeholder markdown always;
   `builder.py` (`parse_builder_state`) reads only `completion_ratio`, `requirements_checked`,
   `requirements_total` from STATE.json. Expanded in M3 (builder), M5 (fix_pass), M6 (scoring/report).

3. **No AsyncAPI formal validator**: AsyncAPI 3.0 fixtures are validated structurally
   (key/field presence checks) not with a formal schema validator library.

4. **No runtime enum enforcement on `Finding` fields**: `priority`, `system`, `resolution`
   are plain `str` — any string value accepted. Valid values are conventions only.

5. **No state machine for `Run4State.current_phase`**: Phase transitions are not validated.
   Any string can be assigned. Listed values are conventions only.

6. **`builder_depth` not validated**: Any string accepted on `Run4Config.builder_depth`.
   `"thorough"` and `"quick"` are known values but not enforced.

7. **`run_id` is 12-char UUID prefix**: Generated as `str(uuid.uuid4())[:12]`, NOT a full UUID.
   Downstream must not assume UUID format.

8. **No notification-service OpenAPI fixture**: PRD describes a notification-service but NO
   `sample_openapi_notification.yaml` was created. Only auth and order have OpenAPI specs.
   Milestones needing notification-service contract validation must create this fixture.


### milestone-2: Build 1 to Build 2 MCP Wiring Verification — Consuming From Predecessors
| Source Milestone | Endpoint | Method | Frontend Service | Wired? |
|-----------------|----------|--------|-----------------|:------:|
| milestone-1 | Module | Export |  | [x] |
| milestone-1 | `src.run4` | `__version__` |  | N/A (not directly consumed) |
| milestone-1 | `src.run4.config` | `Run4Config` | test_m2_mcp_wiring.py | [x] |
| milestone-1 | `src.run4.config` | `Run4Config.from_yaml` |  | N/A (not directly consumed) |
| milestone-1 | `src.run4.state` | `Finding` |  | N/A (not directly consumed) |
| milestone-1 | `src.run4.state` | `Run4State` |  | N/A (not directly consumed) |
| milestone-1 | `src.run4.state` | `Run4State.save` |  | N/A (not directly consumed) |
| milestone-1 | `src.run4.state` | `Run4State.load` |  | N/A (not directly consumed) |
| milestone-1 | `src.run4.state` | `Run4State.add_finding` |  | N/A (not directly consumed) |
| milestone-1 | `src.run4.state` | `Run4State.next_finding_id` |  | N/A (not directly consumed) |
| milestone-1 | `src.run4.mcp_health` | `poll_until_healthy` |  | N/A (tested in M1, available for M2) |
| milestone-1 | `src.run4.mcp_health` | `check_mcp_health` | test_m2_mcp_wiring.py | [x] |
| milestone-1 | `src.run4.builder` | `parse_builder_state` |  | N/A (consumed in M3) |
| milestone-1 | `src.run4.fix_pass` | `detect_regressions` |  | N/A (consumed in M5) |
| milestone-1 | `src.run4.scoring` | `compute_scores` |  | N/A (consumed in M6) |
| milestone-1 | `src.run4.audit_report` | `generate_report` |  | N/A (consumed in M6) |
| milestone-1 | Export | Type |  | [x] |
| milestone-1 | `MockToolResult` | `@dataclass` | Both M2 test files | [x] |
| milestone-1 | `MockTextContent` | `@dataclass` | test_m2_mcp_wiring.py | [x] |
| milestone-1 | `make_mcp_result` | `function` | Both M2 test files | [x] |
| milestone-1 | Fixture | Scope |  | [x] |
| milestone-1 | `run4_config` | `session` | test_m2_mcp_wiring.py | [x] |
| milestone-1 | `sample_prd_text` | `session` | Both M2 test files | [x] |
| milestone-1 | `build1_root` | `session` |  | N/A (available, not needed by M2 tests) |
| milestone-1 | `contract_engine_params` | `session` | test_m2_mcp_wiring.py | [x] |
| milestone-1 | `architect_params` | `session` | test_m2_mcp_wiring.py | [x] |
| milestone-1 | `codebase_intel_params` | `session` | test_m2_mcp_wiring.py | [x] |
| milestone-1 | `mock_mcp_session` | `function` |  | [x] (available; M2 builds custom mocks) |

**Wiring: 12/12 consumed (100%)** — All M1 exports used by M2 are wired. Remaining entries are N/A (consumed by later milestones or not needed by M2).

---

## milestone-2: Build 1 to Build 2 MCP Wiring Verification — COMPLETE

**Status**: COMPLETE
**Date**: 2026-02-19
**Test Results**: 81/81 tests passing (0 failures), 112/112 total run4 suite

### Exposed Interfaces

> **NOTE**: Milestone 2 verifies MCP wiring between Build 1 (3 MCP servers, 22 tools)
> and Build 2 (3 client wrappers). M2 creates 2 test files but NO new source modules.
> However, M2 **validates and documents** all MCP tool interfaces, client wrapper classes,
> fallback functions, and cross-server HTTP wiring. Subsequent milestones MUST consume
> these interfaces exactly as documented below.

---

#### MCP Server: Architect (`src.architect.mcp_server`)

**StdioServerParameters**: `{ command: "python", args: ["-m", "src.architect.mcp_server"] }`
**Port**: Internal 8000, External 8001
**Tools registered**: 4

##### Tool: `decompose`

| Property | Value |
|----------|-------|
| SVC-ID | SVC-001 |
| Client method | `ArchitectClient.decompose(prd_text: str)` |
| Request | `{ prd_text: str }` |
| Response | `{ service_map: { project_name: str, services: [{ name: str, provides_contracts: [str], consumes_contracts: [str] }], generated_at: str (ISO8601), prd_hash: str (SHA256), build_cycle_id: str \| null }, domain_model: { entities: [{ name: str, fields: [{ name: str, type: str }] }], relationships: list, generated_at: str (ISO8601) }, contract_stubs: { [service_name: str]: dict (OpenAPI 3.1.0 spec) }, validation_issues: [str], interview_questions: [str] }` |
| Error response | `{ error: str }` |
| Client safe default | `None` (returns `None` on failure) |

##### Tool: `get_service_map`

| Property | Value |
|----------|-------|
| SVC-ID | SVC-002 |
| Client method | `ArchitectClient.get_service_map(project_name: str \| None = None)` |
| Request | `{ project_name: str \| None }` (optional) |
| Response | `{ project_name: str, services: [{ name: str, provides_contracts: [str], consumes_contracts: [str] }], generated_at: str (ISO8601), prd_hash: str (SHA256), build_cycle_id: str \| null }` |
| Error response | `{ error: "No service map found" }` |
| Client safe default | `{}` |

##### Tool: `get_contracts_for_service`

| Property | Value |
|----------|-------|
| SVC-ID | SVC-003 |
| Client method | `ArchitectClient.get_contracts_for_service(service_name: str)` |
| Request | `{ service_name: str }` |
| Response | `[{ id: str (UUID), role: "provider" \| "consumer", type: "openapi" \| "asyncapi", counterparty: str, summary: str }]` |
| Error response | `[{ error: str }]` or `[]` |
| Client safe default | `[]` |
| Cross-server | Makes HTTP GET to `{CONTRACT_ENGINE_URL}/api/contracts/{contract_id}` |

##### Tool: `get_domain_model`

| Property | Value |
|----------|-------|
| SVC-ID | SVC-004 |
| Client method | `ArchitectClient.get_domain_model(project_name: str \| None = None)` |
| Request | `{ project_name: str \| None }` (optional) |
| Response | `{ entities: [{ name: str, fields: [{ name: str, type: str }] }], relationships: list, generated_at: str (ISO8601) }` |
| Error response | `{ error: "No domain model found" }` |
| Client safe default | `{}` |

---

#### MCP Server: Contract Engine (`src.contract_engine.mcp_server`)

**StdioServerParameters**: `{ command: "python", args: ["-m", "src.contract_engine.mcp_server"] }`
**Port**: Internal 8000, External 8002
**Tools registered**: 10 (9 required + 1 extra `check_compliance`)

##### Tool: `create_contract`

| Property | Value |
|----------|-------|
| SVC-ID | SVC-010a (Build 3 direct) |
| Client method | `ContractEngineClient.create_contract(service_name, type, version, spec, build_cycle_id=None)` |
| Request | `{ service_name: str, type: "openapi" \| "asyncapi" \| "json_schema", version: str (semver), spec: dict, build_cycle_id: str \| null }` |
| Response | `{ id: str (UUID), service_name: str, type: str, version: str, spec: dict, spec_hash: str, status: "active" \| "deprecated" \| "draft", created_at: str (ISO8601), updated_at: str (ISO8601) }` |
| Error response | `{ error: str }` |
| Client safe default | `{ error: str }` |

##### Tool: `list_contracts`

| Property | Value |
|----------|-------|
| SVC-ID | SVC-010c (Build 3 direct) |
| Client method | `ContractEngineClient.list_contracts(service_name=None, page=1, page_size=20)` |
| Request | `{ page: int (default 1), page_size: int (default 20, max 100), service_name: str \| null, contract_type: str \| null, status: str \| null }` |
| Response | `{ items: [{ id: str (UUID), service_name: str, type: str, version: str, status: str, created_at: str (ISO8601), updated_at: str (ISO8601) }], total: int, page: int, page_size: int }` |
| Error response | `{ error: str }` |
| Client safe default | `{ error: str }` |

##### Tool: `get_contract`

| Property | Value |
|----------|-------|
| SVC-ID | SVC-005 |
| Client method | `ContractEngineClient.get_contract(contract_id: str)` |
| Request | `{ contract_id: str }` |
| Response | `{ id: str (UUID), service_name: str, type: "openapi" \| "asyncapi" \| "json_schema", version: str, spec: dict, spec_hash: str, status: "active" \| "deprecated" \| "draft", created_at: str (ISO8601), updated_at: str (ISO8601) }` |
| Error response | `{ error: str }` |
| Client safe default | `{ error: str }` |

##### Tool: `validate_spec`

| Property | Value |
|----------|-------|
| SVC-ID | SVC-010b (Build 3 direct) |
| Client method | `ContractEngineClient.validate_spec(spec: dict, type: str)` |
| Request | `{ spec: dict, type: "openapi" \| "asyncapi" \| "json_schema" }` |
| Response | `{ valid: bool, errors: [str], warnings: [str] }` |
| Error response | `{ error: str }` |
| Client safe default | `{ error: str }` |

##### Tool: `validate_endpoint`

| Property | Value |
|----------|-------|
| SVC-ID | SVC-006 |
| Client method | `ContractEngineClient.validate_endpoint(service_name, method, path, response_body, status_code=200)` |
| Request | `{ service_name: str, method: "GET" \| "POST" \| "PUT" \| "PATCH" \| "DELETE", path: str, response_body: dict, status_code: int (default 200) }` |
| Response | `{ valid: bool, violations: [{ field: str, expected: str, actual: str, severity: str }] }` |
| Error response | `{ valid: false, violations: [{ field: "", error: str }] }` |
| Client safe default | `{ valid: false, violations: [...] }` |

##### Tool: `generate_tests`

| Property | Value |
|----------|-------|
| SVC-ID | SVC-007 |
| Client method | `ContractEngineClient.generate_tests(contract_id, framework="pytest", include_negative=False)` |
| Request | `{ contract_id: str, framework: "pytest" \| "jest" (default "pytest"), include_negative: bool (default false) }` |
| Response | `str` (Python/JavaScript test code as plain string, NOT JSON) |
| Error response | JSON-encoded string: `'{"error": "..."}'` |
| Client safe default | `""` (empty string) |

##### Tool: `check_breaking_changes`

| Property | Value |
|----------|-------|
| SVC-ID | SVC-008 |
| Client method | `ContractEngineClient.check_breaking_changes(contract_id, new_spec=None)` |
| Request | `{ contract_id: str, new_spec: dict \| null }` |
| Response | `[{ change_type: "removed" \| "changed" \| "added", path: str, severity: "breaking" \| "major" \| "minor", old_value: str \| null, new_value: str \| null, affected_consumers: [str] }]` |
| Error response | `[{ error: str }]` or `[]` |
| Client safe default | `[]` |

##### Tool: `mark_implemented`

| Property | Value |
|----------|-------|
| SVC-ID | SVC-009 |
| Client method | `ContractEngineClient.mark_implemented(contract_id, service_name, evidence_path)` |
| Request | `{ contract_id: str, service_name: str, evidence_path: str }` |
| Response | `{ marked: bool, total: int, all_implemented: bool }` |
| Error response | `{ error: str }` |
| Client safe default | `{ error: str }` |

##### Tool: `get_unimplemented_contracts`

| Property | Value |
|----------|-------|
| SVC-ID | SVC-010 |
| Client method | `ContractEngineClient.get_unimplemented_contracts(service_name=None)` |
| Request | `{ service_name: str \| null }` |
| Response | `[{ id: str, type: str, version: str, expected_service: str, status: str }]` |
| Error response | `[{ error: str }]` or `[]` |
| Client safe default | `[]` |

##### Tool: `check_compliance` (EXTRA — not in requirements, present on server)

| Property | Value |
|----------|-------|
| SVC-ID | — (undocumented) |
| Request | `{ contract_id: str, response_data: dict \| null }` |
| Response | `[{ endpoint_path: str, method: str, compliant: bool, violations: [{ field: str, expected: str, actual: str, severity: str }] }]` |
| Error response | `[{ error: str }]` |

---

#### MCP Server: Codebase Intelligence (`src.codebase_intelligence.mcp_server`)

**StdioServerParameters**: `{ command: "python", args: ["-m", "src.codebase_intelligence.mcp_server"] }`
**Port**: Internal 8000, External 8003
**Tools registered**: 8 (7 required + 1 extra `analyze_graph`)

##### Tool: `find_definition`

| Property | Value |
|----------|-------|
| SVC-ID | SVC-011 |
| Client method | `CodebaseIntelligenceClient.find_definition(symbol, language=None)` |
| Request | `{ symbol: str, language: str \| null }` |
| Response | `{ file: str, line: int, kind: "function" \| "class" \| "variable" \| "module", signature: str }` |
| Error response | `{ error: str }` or `{}` |
| Client safe default | `{}` |

##### Tool: `find_callers`

| Property | Value |
|----------|-------|
| SVC-ID | SVC-012 |
| Client method | `CodebaseIntelligenceClient.find_callers(symbol, max_results=50)` |
| Request | `{ symbol: str, max_results: int (default 50) }` |
| Response | `[{ file_path: str, line: int, caller_symbol: str }]` |
| Error response | `[{ error: str }]` or `[]` |
| Client safe default | `[]` |

##### Tool: `find_dependencies`

| Property | Value |
|----------|-------|
| SVC-ID | SVC-013 |
| Client method | `CodebaseIntelligenceClient.find_dependencies(file_path, depth=1, direction="both")` |
| Request | `{ file_path: str, depth: int (default 1), direction: "forward" \| "reverse" \| "both" (default "both") }` |
| Response | `{ imports: [str], imported_by: [str], transitive_deps: [str], circular_deps: [[str]] }` |
| Error response | `{ error: str }` or `{}` |
| Client safe default | `{}` |

##### Tool: `search_semantic`

| Property | Value |
|----------|-------|
| SVC-ID | SVC-014 |
| Client method | `CodebaseIntelligenceClient.search_semantic(query, language=None, service_name=None, n_results=10)` |
| Request | `{ query: str, language: str \| null, service_name: str \| null, n_results: int (default 10) }` |
| Response | `[{ chunk_id: str, file_path: str, symbol_name: str, content: str, score: float (0.0-1.0 cosine), language: str, service_name: str, line_start: int, line_end: int }]` |
| Error response | `[{ error: str }]` or `[]` |
| Client safe default | `[]` |

##### Tool: `get_service_interface`

| Property | Value |
|----------|-------|
| SVC-ID | SVC-015 |
| Client method | `CodebaseIntelligenceClient.get_service_interface(service_name)` |
| Request | `{ service_name: str }` |
| Response | `{ service_name: str, endpoints: [{ method: str, path: str, description: str }], events_published: [{ event_name: str, description: str }], events_consumed: [{ event_name: str, description: str }], exported_symbols: [{ name: str, kind: str, file: str }] }` |
| Error response | `{ error: str }` or `{}` |
| Client safe default | `{}` |

##### Tool: `check_dead_code`

| Property | Value |
|----------|-------|
| SVC-ID | SVC-016 |
| Client method | `CodebaseIntelligenceClient.check_dead_code(service_name=None)` |
| Request | `{ service_name: str \| null }` |
| Response | `[{ symbol_name: str, file_path: str, kind: "function" \| "class" \| ..., line: int, service_name: str, confidence: "high" \| "medium" \| "low" }]` |
| Error response | `[{ error: str }]` or `[]` |
| Client safe default | `[]` |

##### Tool: `register_artifact`

| Property | Value |
|----------|-------|
| SVC-ID | SVC-017 |
| Client method | `CodebaseIntelligenceClient.register_artifact(file_path, service_name=None, source_base64=None, project_root=None)` |
| Request | `{ file_path: str, service_name: str \| null, source_base64: str \| null, project_root: str \| null }` |
| Response | `{ indexed: bool, symbols_found: int, dependencies_found: int, errors: [str] }` |
| Error response | `{ error: str }` |
| Client safe default | `{}` |

##### Tool: `analyze_graph` (EXTRA — not in requirements, present on server)

| Property | Value |
|----------|-------|
| SVC-ID | — (undocumented) |
| Request | `{}` (no parameters) |
| Response | `{ node_count: int, edge_count: int, is_dag: bool, circular_dependencies: [[str]], pagerank: { [file_path: str]: float }, weakly_connected_components: int, build_order: [str] }` |
| Error response | `{ error: str }` |

---

#### Client Wrapper Classes (Build 2)

##### `ArchitectClient` — `src.architect.mcp_client`

```
class ArchitectClient:
    __init__(session: Any = None) -> None
    async decompose(prd_text: str) -> dict[str, Any] | None       # SVC-001; None on failure
    async get_service_map(project_name: str | None = None) -> dict # SVC-002; {} on failure
    async get_contracts_for_service(service_name: str) -> list     # SVC-003; [] on failure
    async get_domain_model(project_name: str | None = None) -> dict # SVC-004; {} on failure
```

Module-level backward-compatible functions:
- `async call_architect_mcp(prd_text: str, config=None) -> dict`
- `async get_service_map(project_name: str | None = None) -> dict`
- `async get_contracts_for_service(service_name: str) -> list`
- `async get_domain_model(project_name: str | None = None) -> dict`

Fallback functions (WIRE-011):
- `decompose_prd_basic(prd_text: str) -> dict` — Returns: `{ services: [{ name: str, description: str, endpoints: [] }], domain_model: { entities: [], relationships: [] }, contract_stubs: [], fallback: true }`
- `async decompose_prd_with_fallback(prd_text: str, client=None) -> dict` — Tries MCP first, falls back to `decompose_prd_basic()`

Constants: `_MAX_RETRIES = 3`, `_BACKOFF_BASE = 1` (seconds)

##### `ContractEngineClient` — `src.contract_engine.mcp_client`

```
class ContractEngineClient:
    __init__(session: Any) -> None
    async create_contract(service_name, type, version, spec, build_cycle_id=None) -> dict  # SVC-010a
    async validate_spec(spec: dict, type: str) -> dict                                     # SVC-010b
    async list_contracts(service_name=None, page=1, page_size=20) -> dict                  # SVC-010c
    async get_contract(contract_id: str) -> dict                                           # SVC-005
    async validate_endpoint(service_name, method, path, response_body, status_code=200) -> dict  # SVC-006
    async generate_tests(contract_id, framework="pytest", include_negative=False) -> str   # SVC-007; "" on failure
    async check_breaking_changes(contract_id, new_spec=None) -> list                       # SVC-008; [] on failure
    async mark_implemented(contract_id, service_name, evidence_path) -> dict               # SVC-009
    async get_unimplemented_contracts(service_name=None) -> list                           # SVC-010; [] on failure
```

Module-level backward-compatible functions (same signatures as class methods).

Fallback functions (WIRE-009):
- `run_api_contract_scan(project_root: str | Path, *, extensions: set[str] | None = None) -> dict` — Returns: `{ project_root: str, contracts: [{ file_path: str, relative_path: str, extension: str, spec: dict, valid: bool }], total_contracts: int, fallback: true }`
- `async get_contracts_with_fallback(project_root, client=None) -> dict` — Tries MCP `list_contracts()` first, falls back to `run_api_contract_scan()`

Constants: `_MAX_RETRIES = 3`, `_BACKOFF_BASE = 1`, `_CONTRACT_EXTENSIONS = {".json", ".yaml", ".yml"}`

Retry helper: `async _retry_call(session, tool_name, params, *, max_retries=3, backoff_base=1) -> Any`

##### `CodebaseIntelligenceClient` — `src.codebase_intelligence.mcp_client`

```
class CodebaseIntelligenceClient:
    __init__(session: Any | None = None, max_retries: int = 3, backoff_base: float = 1.0) -> None
    async find_definition(symbol, language=None) -> dict             # SVC-011; {} on failure
    async find_callers(symbol, max_results=50) -> list               # SVC-012; [] on failure
    async find_dependencies(file_path, depth=1, direction="both") -> dict  # SVC-013; {} on failure
    async search_semantic(query, language=None, service_name=None, n_results=10) -> list  # SVC-014; [] on failure
    async get_service_interface(service_name) -> dict                # SVC-015; {} on failure
    async check_dead_code(service_name=None) -> list                 # SVC-016; [] on failure
    async register_artifact(file_path, service_name=None, source_base64=None, project_root=None) -> dict  # SVC-017; {} on failure
```

Fallback functions (WIRE-010):
- `generate_codebase_map(project_root: str | Path, *, extensions: set[str] | None = None) -> dict` — Returns: `{ project_root: str, files: [{ file_path: str, language: str, size_bytes: int }], languages: [str], total_files: int, fallback: true }`
- `async get_codebase_map_with_fallback(project_root, client=None) -> dict` — Tries MCP `get_service_interface()` first, falls back to `generate_codebase_map()`

Extension mapping: `{ .py: "python", .ts: "typescript", .tsx: "typescript", .js: "javascript", .jsx: "javascript", .go: "go", .cs: "csharp", .java: "java", .rs: "rust", .rb: "ruby" }`

---

#### Client Retry & Error Pattern (all 3 clients)

| Property | Value |
|----------|-------|
| Max retries | 3 |
| Backoff base | 1 second |
| Backoff schedule | attempt 1: 1s, attempt 2: 2s, attempt 3: 4s (exponential: `2^(attempt-1)` seconds) |
| Dict methods safe default | `{}` |
| List methods safe default | `[]` |
| String methods safe default | `""` |
| `decompose()` safe default | `None` |
| Behavior | Never raises exceptions to callers; always returns safe defaults |

---

#### Cross-Server HTTP Wiring (WIRE-012)

Architect's `get_contracts_for_service()` internally calls Contract Engine HTTP:
- **HTTP Method**: GET
- **URL**: `{CONTRACT_ENGINE_URL}/api/contracts/{contract_id}`
- **Env var**: `CONTRACT_ENGINE_URL` (default `http://localhost:8002`)
- **Library**: `httpx`
- **Failure mode**: Returns empty list `[]` on HTTP error

---

#### Test Files Created

##### `tests/run4/test_m2_mcp_wiring.py` — 49 tests across 22 test classes

| Test Class | Tests | Requirements | Description |
|------------|-------|-------------|-------------|
| `TestArchitectMCPHandshake` | 2 | REQ-009 | Verifies Architect MCP session init + 4 tools |
| `TestContractEngineMCPHandshake` | 2 | REQ-010 | Verifies CE MCP session init + ≥9 tools |
| `TestCodebaseIntelMCPHandshake` | 2 | REQ-011 | Verifies CI MCP session init + ≥7 tools |
| `TestArchitectToolValidCalls` | 4 | REQ-012 | 4 Architect tool roundtrips |
| `TestContractEngineToolValidCalls` | 9 | REQ-012 | 9 CE tool roundtrips |
| `TestCodebaseIntelToolValidCalls` | 7 | REQ-012 | 7 CI tool roundtrips |
| `TestAllToolsInvalidParams` | 1 | REQ-012 | All 20 tools with invalid params → `isError=true` |
| `TestAllToolsResponseParsing` | 5 | REQ-012 | Response schema field+type verification |
| `TestSessionSequentialCalls` | 1 | WIRE-001 | 10 sequential calls on one session |
| `TestSessionCrashRecovery` | 1 | WIRE-002 | Broken pipe detection via `BrokenPipeError` |
| `TestSessionTimeout` | 1 | WIRE-003 | Tool timeout via `asyncio.timeout` |
| `TestMultiServerConcurrency` | 1 | WIRE-004 | 3 parallel sessions, no conflicts |
| `TestSessionRestartDataAccess` | 1 | WIRE-005 | Session restart data persistence |
| `TestMalformedJsonHandling` | 1 | WIRE-006 | Bad JSON → `isError=true` without crash |
| `TestNonexistentToolCall` | 1 | WIRE-007 | Unknown tool → error response |
| `TestServerExitDetection` | 1 | WIRE-008 | Server exit → `ConnectionError` |
| `TestFallbackContractEngineUnavailable` | 2 | WIRE-009 | CE unavailable → `run_api_contract_scan()` |
| `TestFallbackCodebaseIntelUnavailable` | 2 | WIRE-010 | CI unavailable → `generate_codebase_map()` |
| `TestFallbackArchitectUnavailable` | 1 | WIRE-011 | Architect unavailable → `decompose_prd_basic()` |
| `TestArchitectCrossServerContractLookup` | 1 | WIRE-012 | Cross-server HTTP contract lookup via `httpx` |
| `TestMCPToolLatencyBenchmark` | 1 | TEST-008 | Per-tool <5s, startup <30s (120s CI first-start) |
| `TestCheckMCPHealthIntegration` | 2 | — | `check_mcp_health` with mocked MCP SDK |

##### `tests/run4/test_m2_client_wrappers.py` — 32 tests across 25 test classes

| Test Class | Tests | Requirements | Description |
|------------|-------|-------------|-------------|
| `TestCEClientGetContractReturnsCorrectType` | 1 | REQ-013 | `get_contract()` → dict with ContractEntry fields |
| `TestCEClientValidateEndpointReturnsCorrectType` | 1 | REQ-013 | `validate_endpoint()` → `{ valid: bool, violations: [...] }` |
| `TestCEClientGenerateTestsReturnsString` | 1 | REQ-013 | `generate_tests()` → non-empty string |
| `TestCEClientCheckBreakingReturnsList` | 1 | REQ-013 | `check_breaking_changes()` → list of change dicts |
| `TestCEClientMarkImplementedReturnsResult` | 1 | REQ-013 | `mark_implemented()` → `{ marked: bool, total: int, all_implemented: bool }` |
| `TestCEClientGetUnimplementedReturnsList` | 1 | REQ-013 | `get_unimplemented_contracts()` → list |
| `TestCEClientSafeDefaultsOnError` | 1 | REQ-013 | All 6 CE methods return safe defaults on MCP error |
| `TestCEClientRetry3xBackoff` | 1 | REQ-013 | 3x retry with exponential backoff (1s, 2s, 4s) |
| `TestCIClientFindDefinitionType` | 1 | REQ-014 | `find_definition()` → `{ file: str, line: int, kind: str, signature: str }` |
| `TestCIClientFindCallersType` | 1 | REQ-014 | `find_callers()` → `[{ file_path: str, line: int, caller_symbol: str }]` |
| `TestCIClientFindDependenciesType` | 1 | REQ-014 | `find_dependencies()` → `{ imports: [...], imported_by: [...], transitive_deps: [...], circular_deps: [...] }` |
| `TestCIClientSearchSemanticType` | 1 | REQ-014 | `search_semantic()` → list of semantic result dicts |
| `TestCIClientGetServiceInterfaceType` | 1 | REQ-014 | `get_service_interface()` → `{ service_name, endpoints, events_published, events_consumed, exported_symbols }` |
| `TestCIClientCheckDeadCodeType` | 1 | REQ-014 | `check_dead_code()` → `[{ symbol_name, file_path, kind, line, service_name, confidence }]` |
| `TestCIClientRegisterArtifactType` | 1 | REQ-014 | `register_artifact()` → `{ indexed: bool, symbols_found: int, dependencies_found: int, errors: [...] }` |
| `TestCIClientSafeDefaults` | 1 | REQ-014 | All 7 CI methods return safe defaults on error |
| `TestCIClientRetryPattern` | 1 | REQ-014 | 3x retry with exponential backoff verified |
| `TestArchClientDecomposeReturnsResult` | 1 | REQ-015 | `decompose()` → DecompositionResult dict |
| `TestArchClientGetServiceMapType` | 1 | REQ-015 | `get_service_map()` → ServiceMap dict |
| `TestArchClientGetContractsType` | 1 | REQ-015 | `get_contracts_for_service()` → list of contract dicts |
| `TestArchClientGetDomainModelType` | 1 | REQ-015 | `get_domain_model()` → DomainModel dict |
| `TestArchClientDecomposeFailureReturnsNone` | 2 | REQ-015 | `decompose()` → `None` on failure |
| `TestArchitectMCPClientWiring` | 2 | — | Client module importability |
| `TestContractEngineMCPClientWiring` | 4 | — | Client module importability + function signatures |
| `TestMCPServerToolRegistration` | 3 | — | Server module discoverability |

##### Helper Functions (internal to test files, not exported)

| File | Helper | Description |
|------|--------|-------------|
| `test_m2_mcp_wiring.py` | `_build_mock_session(tool_names)` | Generic mock MCP session builder |
| `test_m2_mcp_wiring.py` | `_build_architect_session()` | Architect-specific mock with 4 tools |
| `test_m2_mcp_wiring.py` | `_build_contract_engine_session()` | CE-specific mock with 9 tools |
| `test_m2_mcp_wiring.py` | `_build_codebase_intel_session()` | CI-specific mock with 7 tools |
| `test_m2_client_wrappers.py` | `_contract_entry_result()` | Returns `make_mcp_result({ id, service_name, type, version, spec, spec_hash, status })` |
| `test_m2_client_wrappers.py` | `_validation_result()` | Returns `make_mcp_result({ valid: true, violations: [] })` |
| `test_m2_client_wrappers.py` | `_generate_tests_result()` | Returns `make_mcp_result("def test_...(): ...")` (string, not dict) |
| `test_m2_client_wrappers.py` | `_breaking_changes_result()` | Returns `make_mcp_result([{ change_type, path, severity, old_value, new_value, affected_consumers }])` |
| `test_m2_client_wrappers.py` | `_mark_result()` | Returns `make_mcp_result({ marked: true, total: int, all_implemented: bool })` |
| `test_m2_client_wrappers.py` | `_definition_result()` | Returns `make_mcp_result({ file, line, kind, signature })` |
| `test_m2_client_wrappers.py` | `_callers_result()` | Returns `make_mcp_result([{ file_path, line, caller_symbol }])` |
| `test_m2_client_wrappers.py` | `_dependency_result()` | Returns `make_mcp_result({ imports, imported_by, transitive_deps, circular_deps })` |
| `test_m2_client_wrappers.py` | `_semantic_search_result()` | Returns `make_mcp_result([{ chunk_id, file_path, symbol_name, content, score, language, service_name, line_start, line_end }])` |
| `test_m2_client_wrappers.py` | `_service_interface_result()` | Returns `make_mcp_result({ service_name, endpoints, events_published, events_consumed, exported_symbols })` |
| `test_m2_client_wrappers.py` | `_dead_code_result()` | Returns `make_mcp_result([{ symbol_name, file_path, kind, line, service_name, confidence }])` |
| `test_m2_client_wrappers.py` | `_artifact_result()` | Returns `make_mcp_result({ indexed, symbols_found, dependencies_found, errors })` |
| `test_m2_client_wrappers.py` | `_decomposition_result()` | Returns `make_mcp_result({ service_map, domain_model, contract_stubs, validation_issues, interview_questions })` |
| `test_m2_client_wrappers.py` | `_service_map_result()` | Returns `make_mcp_result({ project_name, services, generated_at, prd_hash, build_cycle_id })` |
| `test_m2_client_wrappers.py` | `_domain_model_result()` | Returns `make_mcp_result({ entities, relationships, generated_at })` |

---

### MCP Server Tool Inventory (Verified by M2)

| Server | Module | Required Tools | Actual Tools | Extra Tools |
|--------|--------|---------------|-------------|-------------|
| Architect | `src.architect.mcp_server` | 4: `decompose`, `get_service_map`, `get_contracts_for_service`, `get_domain_model` | 4 | — |
| Contract Engine | `src.contract_engine.mcp_server` | 9: `create_contract`, `validate_spec`, `list_contracts`, `get_contract`, `validate_endpoint`, `generate_tests`, `check_breaking_changes`, `mark_implemented`, `get_unimplemented_contracts` | 10 | `check_compliance` |
| Codebase Intelligence | `src.codebase_intelligence.mcp_server` | 7: `find_definition`, `find_callers`, `find_dependencies`, `search_semantic`, `get_service_interface`, `check_dead_code`, `register_artifact` | 8 | `analyze_graph` |

Handshake tests verify required subset is present (≥N), NOT exact count, to allow extra tools.

---

### Enum/Status Values

| Entity | Field | Valid Values | DB Type | API String | Default | Notes |
|--------|-------|-------------|---------|------------|---------|-------|
| ContractEntry | `status` | `"active"`, `"deprecated"`, `"draft"` | `str` | Same (lowercase) | `"active"` (on create) | Contract lifecycle state |
| ContractEntry | `type` | `"openapi"`, `"asyncapi"`, `"json_schema"` | `str` | Same (lowercase) | — (required on create) | Contract specification type |
| BreakingChange | `change_type` | `"removed"`, `"changed"`, `"added"` | `str` | Same (lowercase) | — | Type of change detected |
| BreakingChange | `severity` | `"breaking"`, `"major"`, `"minor"` | `str` | Same (lowercase) | — | Impact severity |
| ContractViolation | `severity` | `str` (not enumerated) | `str` | Same | — | Used in `validate_endpoint` and `check_compliance` |
| DefinitionResult | `kind` | `"function"`, `"class"`, `"variable"`, `"module"` (common values) | `str` | Same (lowercase) | — | Symbol kind |
| DeadCodeEntry | `kind` | `"function"`, `"class"` (and others) | `str` | Same (lowercase) | — | Symbol kind |
| DeadCodeEntry | `confidence` | `"high"`, `"medium"`, `"low"` | `str` | Same (lowercase) | — | Dead code confidence level |
| ContractRole (in Architect) | `role` | `"provider"`, `"consumer"` | `str` | Same (lowercase) | — | Service's role in contract |
| DependencyDirection | `direction` | `"forward"`, `"reverse"`, `"both"` | `str` (param) | Same (lowercase) | `"both"` | Dependency traversal direction |
| TestFramework | `framework` | `"pytest"`, `"jest"` | `str` (param) | Same (lowercase) | `"pytest"` | Test generation framework |
| HTTP Method (validate_endpoint) | `method` | `"GET"`, `"POST"`, `"PUT"`, `"PATCH"`, `"DELETE"` | `str` (param) | Same (UPPERCASE) | — | HTTP method for validation |
| Language (CI tools) | `language` | `"python"`, `"typescript"`, `"javascript"`, `"go"`, `"csharp"`, `"java"`, `"rust"`, `"ruby"` | `str` (param) | Same (lowercase) | — | Programming language filter |

---

### Database State After This Milestone

**No new database tables created by M2.** M2 is test-only. However, M2 **validates** the
following database schemas that were created by Build 1:

| Database | Path (env var) | Table/Collection | Purpose |
|----------|---------------|-----------------|---------|
| Architect SQLite | `DATABASE_PATH` → `./data/architect.db` | Service maps, domain models | Stores decomposition results |
| Contract Engine SQLite | `DATABASE_PATH` → `./data/contracts.db` | Contracts, implementations | Stores contract specs + implementation tracking |
| Codebase Intel SQLite | `DATABASE_PATH` → `./data/symbols.db` | Symbols, dependencies | Stores symbol index + dependency graph |
| Codebase Intel ChromaDB | `CHROMA_PATH` → `./data/chroma` | Vector embeddings | Semantic search collection |
| Codebase Intel JSON | `GRAPH_PATH` → `./data/graph.json` | Call graph | `networkx` dependency graph |

M2 does NOT write to any of these — it only validates tool responses that read from them.

---

### Environment Variables

M2 creates no new environment variables. The following are **consumed by MCP servers**
(verified by M2 handshake and roundtrip tests):

| Variable | Server | Default | Purpose |
|----------|--------|---------|---------|
| `DATABASE_PATH` | Architect | `./data/architect.db` | SQLite database for decomposition data |
| `CONTRACT_ENGINE_URL` | Architect | `http://localhost:8002` | URL for cross-server HTTP calls to CE |
| `DATABASE_PATH` | Contract Engine | `./data/contracts.db` | SQLite database for contract storage |
| `DATABASE_PATH` | Codebase Intelligence | `./data/symbols.db` | SQLite database for symbol index |
| `CHROMA_PATH` | Codebase Intelligence | `./data/chroma` | ChromaDB persistent storage path |
| `GRAPH_PATH` | Codebase Intelligence | `./data/graph.json` | Call-graph JSON file path |

---

### Files Created

| File | LOC | Purpose |
|------|-----|---------|
| `tests/run4/test_m2_mcp_wiring.py` | 580 | 49 tests: MCP handshake, tool roundtrips, session lifecycle, fallback, cross-server, benchmark |
| `tests/run4/test_m2_client_wrappers.py` | 640 | 32 tests: client wrapper return types, safe defaults, retry backoff, module importability |

---

### Known Limitations

1. **Mock-based testing only**: All M2 tests use `AsyncMock`-based MCP sessions rather than
   spawning real MCP server processes. This validates schema expectations and control flow
   but not actual MCP SDK wire compatibility. Real server process tests require Docker
   Compose infrastructure and are deferred to e2e/integration test suites.

2. **Fallback functions exist but with different names**: The requirements reference
   `run_api_contract_scan()` and `generate_codebase_map()` as fallback functions. The actual
   codebase implements these in the respective `mcp_client.py` modules with those exact names.
   The fallback tests validate the try/except/fallback pattern and verify the `fallback: true`
   flag in returned dicts.

3. **Client wrapper classes exist alongside module-level functions**: `ArchitectClient`,
   `ContractEngineClient`, and `CodebaseIntelligenceClient` exist as classes in their
   respective `mcp_client.py` modules. Module-level functions (`call_architect_mcp`,
   `create_contract`, `validate_spec`, `list_contracts`) also exist for backward compatibility.
   Tests verify wiring at both levels.

4. **CE has 10 tools, CI has 8 tools (more than requirements)**: The actual MCP servers expose
   extra tools (CE: `check_compliance`, CI: `analyze_graph`). Handshake tests verify required
   subset is present (≥9 for CE, ≥7 for CI) using `>=` checks, not exact equality. Downstream
   milestones may use the extra tools.

5. **No runtime schema validation on MCP responses**: Tool responses are returned as raw
   dicts/lists. Field names and types documented above are conventions verified by M2 tests
   but not enforced at runtime. Downstream consumers should validate defensively.

6. **`generate_tests` returns raw string, NOT JSON**: Unlike all other tools that return
   JSON-parseable dicts/lists, `generate_tests` returns Python/JavaScript test code as a
   plain string. The client wrapper returns `""` (empty string) on failure, not `{}`.

7. **Cross-server HTTP wiring (WIRE-012) requires both servers running**: Architect's
   `get_contracts_for_service()` makes HTTP GET calls to Contract Engine. In production,
   both Docker containers must be running. In tests, this is mocked via `httpx` mock.

8. **`check_compliance` and `analyze_graph` are undocumented extras**: These tools are
   present on the servers but NOT in the requirements SVC wiring map. They work and are
   tested implicitly in handshake counts, but no formal SVC-ID has been assigned.


### milestone-3: Build 2 to Build 3 Wiring Verification — Consuming From Predecessors
| Source Milestone | Endpoint | Method | Frontend Service | Wired? |
|-----------------|----------|--------|-----------------|:------:|
| milestone-1 | `src.run4` | `__version__` |  | N/A (not directly consumed) |
| milestone-1 | `src.run4.config` | `Run4Config` | test_m3_builder_invocation.py (via `run4_config` fixture) | [x] |
| milestone-1 | `src.run4.config` | `Run4Config.from_yaml` |  | N/A (not directly consumed) |
| milestone-1 | `src.run4.state` | `Finding` |  | N/A (not directly consumed) |
| milestone-1 | `src.run4.state` | `Run4State` |  | N/A (not directly consumed) |
| milestone-1 | `src.run4.state` | `Run4State.save` |  | N/A (not directly consumed) |
| milestone-1 | `src.run4.state` | `Run4State.load` |  | N/A (not directly consumed) |
| milestone-1 | `src.run4.state` | `Run4State.add_finding` |  | N/A (not directly consumed) |
| milestone-1 | `src.run4.state` | `Run4State.next_finding_id` |  | N/A (not directly consumed) |
| milestone-1 | `src.run4.mcp_health` | `poll_until_healthy` |  | N/A (not directly consumed) |
| milestone-1 | `src.run4.mcp_health` | `check_mcp_health` |  | N/A (not directly consumed) |
| milestone-1 | `src.run4.builder` | `parse_builder_state` | Both M3 test files + builder.py expanded impl | [x] |
| milestone-1 | `src.run4.builder` | `BuilderResult` | Both M3 test files + fix_loop.py | [x] |
| milestone-1 | `src.run4.builder` | `invoke_builder` | test_m3_builder_invocation.py | [x] |
| milestone-1 | `src.run4.builder` | `run_parallel_builders` | Both M3 test files | [x] |
| milestone-1 | `src.run4.builder` | `generate_builder_config` | Both M3 test files | [x] |
| milestone-1 | `src.run4.builder` | `feed_violations_to_builder` | test_m3_builder_invocation.py | [x] |
| milestone-1 | `src.run4.builder` | `write_fix_instructions` | test_m3_builder_invocation.py + fix_loop.py | [x] |
| milestone-1 | `src.run4.builder` | `_state_to_builder_result` | Both M3 test files + fix_loop.py | [x] |
| milestone-1 | `src.run4.fix_pass` | `detect_regressions` |  | N/A (consumed in M5) |
| milestone-1 | `src.run4.scoring` | `compute_scores` |  | N/A (consumed in M6) |
| milestone-1 | `src.run4.audit_report` | `generate_report` |  | N/A (consumed in M6) |
| milestone-1 | `MockToolResult` | `@dataclass` |  | N/A (not needed by M3 tests) |
| milestone-1 | `MockTextContent` | `@dataclass` |  | N/A (not needed by M3 tests) |
| milestone-1 | `make_mcp_result` | `function` |  | N/A (not needed by M3 tests) |
| milestone-1 | `run4_config` | `session` fixture | test_m3_builder_invocation.py (available) | [x] |
| milestone-1 | `sample_prd_text` | `session` fixture |  | N/A (not needed by M3 tests) |
| milestone-1 | `build1_root` | `session` fixture |  | N/A (not needed by M3 tests) |
| milestone-1 | `contract_engine_params` | `session` fixture |  | N/A (not needed by M3 tests) |
| milestone-1 | `architect_params` | `session` fixture |  | N/A (not needed by M3 tests) |
| milestone-1 | `codebase_intel_params` | `session` fixture |  | N/A (not needed by M3 tests) |
| milestone-1 | `mock_mcp_session` | `function` fixture |  | N/A (not needed by M3 tests) |

**Cross-build consumption (not from M1):**
| Source Module | Export | M3 Consumer | Wired? |
|--------------|--------|------------|:------:|
| `src.build3_shared.models` | `ContractViolation` | test_m3_builder_invocation.py, fix_loop.py | [x] |
| `src.build3_shared.utils` | `load_json` | fix_loop.py | [x] |
| `src.super_orchestrator.pipeline` | `_dict_to_config` | test_m3_builder_invocation.py, test_m3_config_generation.py | [x] |
| `src.integrator.fix_loop` | `ContractFixLoop` | test_m3_builder_invocation.py | [x] |

**Wiring: 13/13 consumed (100%)** — All M1 exports used by M3 are wired. Remaining M1 entries are N/A (consumed by later milestones or not needed by M3).

---

## milestone-3: Build 2 to Build 3 Wiring Verification — COMPLETE

**Status**: COMPLETE
**Date**: 2026-02-19
**Test Results**: 38/38 tests passing (0 failures), 169/169 total run4 suite

### Exposed Interfaces

> **NOTE**: Milestone 3 validates subprocess integration between Build 3 (Super Orchestrator)
> and Build 2 (Builder Fleet). M3 creates 2 new source modules (`execution_backend.py`,
> `fix_loop.py`), expands `builder.py` from stub to full implementation, and creates 2 test
> files. M3 also **consumes** `src.build3_shared.models` and `src.super_orchestrator.pipeline`
> from the existing Build 3 codebase. All interfaces documented below MUST be consumed by
> subsequent milestones exactly as specified.

---

#### Source Module: `src.run4.builder` (expanded from M1 stub)

##### Dataclass: `BuilderResult`

```python
@dataclass
class BuilderResult:
    service_name: str = ""          # Name of the service (derived from cwd.name)
    success: bool = False           # From STATE.JSON summary.success
    test_passed: int = 0            # From STATE.JSON summary.test_passed
    test_total: int = 0             # From STATE.JSON summary.test_total
    convergence_ratio: float = 0.0  # From STATE.JSON summary.convergence_ratio (0.0-1.0)
    total_cost: float = 0.0        # From STATE.JSON total_cost (top-level)
    health: str = "unknown"         # From STATE.JSON health (top-level): "green"|"yellow"|"red"|"unknown"
    completed_phases: list[str] = field(default_factory=list)  # From STATE.JSON completed_phases
    exit_code: int = -1             # Subprocess exit code; -1 if never ran/timed out
    stdout: str = ""                # Captured subprocess stdout (decoded, errors=replace)
    stderr: str = ""                # Captured subprocess stderr (decoded, errors=replace)
    duration_s: float = 0.0        # Wall-clock seconds for subprocess execution
```

##### Function: `parse_builder_state`

| Property | Value |
|----------|-------|
| Signature | `parse_builder_state(output_dir: Path) -> dict` |
| Input | `output_dir`: Path containing `.agent-team/STATE.json` |
| Returns | `{ success: bool, test_passed: int, test_total: int, convergence_ratio: float, total_cost: float, health: str, completed_phases: list[str] }` |
| Failure return | `{ success: False, test_passed: 0, test_total: 0, convergence_ratio: 0.0, total_cost: 0.0, health: "unknown", completed_phases: [] }` |
| Failure cases | Missing file, corrupt JSON, OSError — all return failure dict, never raises |

##### Function: `_state_to_builder_result` (internal, but consumed by fix_loop.py)

| Property | Value |
|----------|-------|
| Signature | `_state_to_builder_result(service_name: str, output_dir: Path, exit_code: int = -1, stdout: str = "", stderr: str = "", duration_s: float = 0.0) -> BuilderResult` |
| Returns | `BuilderResult` populated from `parse_builder_state(output_dir)` plus process metadata |

##### Function: `invoke_builder`

| Property | Value |
|----------|-------|
| Signature | `async invoke_builder(cwd: Path, depth: str = "thorough", timeout_s: int = 1800, env: dict[str, str] \| None = None) -> BuilderResult` |
| Subprocess command | `python -m agent_team --cwd {cwd} --depth {depth}` |
| Environment | If `env` is None, uses `os.environ` minus `_FILTERED_ENV_KEYS` (`ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `AWS_SECRET_ACCESS_KEY`) |
| Timeout behavior | `asyncio.wait_for(proc.communicate(), timeout=timeout_s)`; on `TimeoutError`: `proc.kill()` + `await proc.wait()` in `finally` block |
| Returns | `BuilderResult` parsed from STATE.json in `cwd/.agent-team/STATE.json` |
| Side effects | Creates `cwd` directory if not exists (`mkdir(parents=True, exist_ok=True)`) |

##### Function: `run_parallel_builders`

| Property | Value |
|----------|-------|
| Signature | `async run_parallel_builders(builder_configs: list[dict[str, Any]], max_concurrent: int = 3, timeout_s: int = 1800) -> list[BuilderResult]` |
| Input dict schema | Each dict MUST have `cwd: str\|Path`; optional: `depth: str` (default `"thorough"`), `env: dict` |
| Concurrency | `asyncio.Semaphore(max_concurrent)` gates concurrent builder count |
| Returns | `list[BuilderResult]` in same order as input configs (gathered via `asyncio.gather`) |

##### Function: `generate_builder_config`

| Property | Value |
|----------|-------|
| Signature | `generate_builder_config(service_name: str, output_dir: Path, depth: str = "thorough", contracts: list[dict[str, Any]] \| None = None, mcp_enabled: bool = True) -> Path` |
| Returns | `Path` to generated `config.yaml` inside `output_dir` |
| Generated YAML schema | `{ milestone: str ("build-{service_name}"), depth: str, e2e_testing: true, post_orchestration_scans: true, service_name: str, mcp?: { enabled: bool, servers: {} }, contracts?: list[dict] }` |
| Build 2 compatibility | Output parseable by `src.super_orchestrator.pipeline._dict_to_config()` which returns `tuple[dict[str, Any], set[str]]` |
| `_dict_to_config` known keys | `{"depth", "milestone", "e2e_testing", "post_orchestration_scans", "mcp", "contracts"}` — all others placed in `unknown_keys` set (e.g., `"service_name"`) |

##### Function: `write_fix_instructions`

| Property | Value |
|----------|-------|
| Signature | `write_fix_instructions(cwd: Path, violations: list[dict[str, Any]], priority_order: list[str] \| None = None) -> Path` |
| Default priority_order | `["P0", "P1", "P2"]` |
| Violation dict schema | `{ code: str, component: str, evidence?: str, action?: str, message?: str, priority?: str (default "P1") }` |
| Output file | `{cwd}/FIX_INSTRUCTIONS.md` |
| Output format | Markdown with `## Priority: P0 (Must Fix)`, `## Priority: P1 (Should Fix)`, `## Priority: P2 (Nice to Have)` sections, each containing `### {code}: {message}` entries |
| Returns | `Path` to written FIX_INSTRUCTIONS.md |

##### Function: `feed_violations_to_builder`

| Property | Value |
|----------|-------|
| Signature | `async feed_violations_to_builder(cwd: Path, violations: list[dict[str, Any]], timeout_s: int = 600) -> BuilderResult` |
| Behavior | Calls `write_fix_instructions(cwd, violations)`, then `invoke_builder(cwd, depth="quick", timeout_s=timeout_s)` |
| Returns | `BuilderResult` from the fix-pass builder execution |

##### Constants

| Constant | Value | Purpose |
|----------|-------|---------|
| `_FILTERED_ENV_KEYS` | `{"ANTHROPIC_API_KEY", "OPENAI_API_KEY", "AWS_SECRET_ACCESS_KEY"}` | SEC-001: keys removed from subprocess environment |
| `_PRIORITY_LABELS` | `{"P0": "P0 (Must Fix)", "P1": "P1 (Should Fix)", "P2": "P2 (Nice to Have)"}` | FIX_INSTRUCTIONS.md section headers |

---

#### Source Module: `src.run4.execution_backend` (NEW in M3)

##### Dataclass: `AgentTeamsConfig`

```python
@dataclass
class AgentTeamsConfig:
    enabled: bool = False           # Whether Agent Teams mode is enabled
    fallback_to_cli: bool = True    # If True, falls back to CLIBackend when CLI unavailable
```

##### Class: `ExecutionBackend` (abstract base)

```python
class ExecutionBackend:
    async def execute_wave(self, tasks: list[dict[str, Any]]) -> list[dict[str, Any]]
        # Abstract — raises NotImplementedError
```

**Task dict schema (input):** `{ id: str, service: str, status: str }`
**Result dict schema (output):** `{ id: str, service: str, status: "completed", backend: "cli"|"agent_teams", ... }`

##### Class: `CLIBackend(ExecutionBackend)`

| Property | Value |
|----------|-------|
| `__init__` | `(builder_dir: str = "", config: dict \| None = None) -> None` |
| `execute_wave` | Sets `status: "completed"` and `backend: "cli"` on each task |

##### Class: `AgentTeamsBackend(ExecutionBackend)`

| Property | Value |
|----------|-------|
| `__init__` | `(builder_dir: str = "", config: dict \| None = None) -> None`; initializes `_task_creates: list[dict]`, `_task_updates: list[dict]`, `_send_messages: list[dict]` |
| `execute_wave` | For each task: (1) TaskCreate `{task_id, action:"create"}`, (2) TaskUpdate `{task_id, status:"in_progress", action:"update"}`, (3) SendMessage `{task_id, message:str, action:"send_message"}`, (4) TaskUpdate `{task_id, status:"completed", action:"update"}`; returns `{...task, status:"completed", backend:"agent_teams"}` |
| Task state progression | `pending` → `in_progress` → `completed` |

##### Function: `_is_claude_cli_available`

| Property | Value |
|----------|-------|
| Signature | `_is_claude_cli_available() -> bool` |
| Behavior | `shutil.which("claude") is not None` |

##### Function: `create_execution_backend`

| Property | Value |
|----------|-------|
| Signature | `create_execution_backend(agent_teams_config: AgentTeamsConfig \| None = None, builder_dir: str = "", config: dict \| None = None) -> ExecutionBackend` |
| Decision tree | (1) `enabled=False` → `CLIBackend`; (2) `enabled=True` + CLI available → `AgentTeamsBackend`; (3) `enabled=True` + CLI unavailable + `fallback_to_cli=True` → `CLIBackend` + `logger.warning`; (4) `enabled=True` + CLI unavailable + `fallback_to_cli=False` → `RuntimeError` |
| Error message | `"Agent Teams is enabled (agent_teams.enabled=True) but Claude CLI is not available and fallback_to_cli=False. Install Claude CLI or enable fallback."` |

---

#### Source Module: `src.integrator.fix_loop` (NEW in M3)

##### Class: `ContractFixLoop`

| Property | Value |
|----------|-------|
| `__init__` | `(config: Any = None, timeout: int = 1800) -> None`; reads `config.builder.timeout` if available, else uses `timeout` param |
| Instance fields | `timeout: int`, `_config: Any` |

##### Method: `classify_violations`

| Property | Value |
|----------|-------|
| Signature | `classify_violations(self, violations: list[ContractViolation]) -> dict[str, list[ContractViolation]]` |
| Returns | `{ "critical": [...], "error": [...], "warning": [...], "info": [...] }` — always all 4 keys, empty lists for missing severities |
| Unknown severity | Falls back to `"error"` bucket |

##### Method: `feed_violations_to_builder`

| Property | Value |
|----------|-------|
| Signature | `async feed_violations_to_builder(self, service_id: str, violations: list[ContractViolation], builder_dir: str \| Path) -> BuilderResult` |
| Violation → dict mapping | `code=v.code`, `component="{v.service}/{v.file_path}"` or `v.service`, `evidence="{v.endpoint}: {v.actual}"` or `v.endpoint`, `action=v.message`, `message=v.message`, `priority="P0"` if severity=critical, `"P1"` if severity=error, `"P2"` otherwise |
| Subprocess command | `python -m agent_team --cwd {builder_dir} --depth quick` |
| Environment | `os.environ` minus `_FILTERED_ENV_KEYS` |
| Timeout | `self.timeout` (default 1800 from init) |
| Timeout cleanup | `proc.kill()` + `await proc.wait()` in `finally` block (WIRE-015) |
| Returns | `BuilderResult` via `_state_to_builder_result()` |

##### Constants

| Constant | Value | Purpose |
|----------|-------|---------|
| `_FILTERED_ENV_KEYS` | `{"ANTHROPIC_API_KEY", "OPENAI_API_KEY", "AWS_SECRET_ACCESS_KEY"}` | Same as builder.py SEC-001 |
| `_SEVERITY_ORDER` | `("critical", "error", "warning", "info")` | Classification ordering |

---

#### Source Module: `src.build3_shared.models` (pre-existing, consumed by M3)

M3 consumes the following from this module:

##### Dataclass: `ContractViolation`

```python
@dataclass
class ContractViolation:
    code: str               # Violation code (e.g., "CV-001")
    severity: str           # "critical"|"error"|"warning"|"info" (not enforced)
    service: str            # Service name (e.g., "auth-service")
    endpoint: str           # Endpoint path (e.g., "/health")
    message: str            # Human-readable description
    expected: str = ""      # Expected value (optional)
    actual: str = ""        # Actual value (optional)
    file_path: str = ""     # Source file path (optional)
```

##### Enum: `ServiceStatus(str, Enum)`

| Value | String |
|-------|--------|
| `PENDING` | `"pending"` |
| `BUILDING` | `"building"` |
| `BUILT` | `"built"` |
| `DEPLOYING` | `"deploying"` |
| `HEALTHY` | `"healthy"` |
| `UNHEALTHY` | `"unhealthy"` |
| `FAILED` | `"failed"` |

##### Enum: `QualityLevel(str, Enum)`

| Value | String |
|-------|--------|
| `LAYER1_SERVICE` | `"layer1_service"` |
| `LAYER2_CONTRACT` | `"layer2_contract"` |
| `LAYER3_SYSTEM` | `"layer3_system"` |
| `LAYER4_ADVERSARIAL` | `"layer4_adversarial"` |

##### Enum: `GateVerdict(str, Enum)`

| Value | String |
|-------|--------|
| `PASSED` | `"passed"` |
| `FAILED` | `"failed"` |
| `PARTIAL` | `"partial"` |
| `SKIPPED` | `"skipped"` |

##### Other Consumed Dataclasses (documented for downstream)

```python
@dataclass
class ServiceInfo:
    service_id: str
    domain: str
    stack: dict[str, str] = field(default_factory=dict)
    estimated_loc: int = 0
    docker_image: str = ""
    health_endpoint: str = "/health"
    port: int = 8080
    status: ServiceStatus = ServiceStatus.PENDING
    build_cost: float = 0.0
    build_dir: str = ""

@dataclass
class ScanViolation:
    code: str
    severity: str
    category: str
    file_path: str = ""
    line: int = 0
    service: str = ""
    message: str = ""

@dataclass
class LayerResult:
    layer: QualityLevel
    verdict: GateVerdict = GateVerdict.SKIPPED
    violations: list[ScanViolation] = field(default_factory=list)
    contract_violations: list[ContractViolation] = field(default_factory=list)
    total_checks: int = 0
    passed_checks: int = 0
    duration_seconds: float = 0.0

@dataclass
class QualityGateReport:
    layers: dict[str, LayerResult] = field(default_factory=dict)
    overall_verdict: GateVerdict = GateVerdict.SKIPPED
    fix_attempts: int = 0
    max_fix_attempts: int = 3
    total_violations: int = 0
    blocking_violations: int = 0

@dataclass
class IntegrationReport:
    services_deployed: int = 0
    services_healthy: int = 0
    contract_tests_passed: int = 0
    contract_tests_total: int = 0
    integration_tests_passed: int = 0
    integration_tests_total: int = 0
    data_flow_tests_passed: int = 0
    data_flow_tests_total: int = 0
    boundary_tests_passed: int = 0
    boundary_tests_total: int = 0
    violations: list[ContractViolation] = field(default_factory=list)
    overall_health: str = "unknown"
```

Note: There are TWO `BuilderResult` dataclasses in the codebase:
- **`src.run4.builder.BuilderResult`** — Run4/M3 version with subprocess metadata (exit_code, stdout, stderr, duration_s)
- **`src.build3_shared.models.BuilderResult`** — Build 3 pipeline version with system_id, cost, error, output_dir, artifacts

These are **distinct types** used in different contexts. M3 tests exclusively use `src.run4.builder.BuilderResult`.

---

#### Cross-Build File Contract: STATE.JSON

The STATE.JSON file at `{output_dir}/.agent-team/STATE.json` is the critical interface between Build 2 (writer) and Build 3/Run4 (reader).

```json
{
  "run_id": "string",
  "health": "green|yellow|red",
  "current_phase": "string",
  "completed_phases": ["string"],
  "total_cost": 0.0,
  "summary": {
    "success": true,
    "test_passed": 42,
    "test_total": 50,
    "convergence_ratio": 0.85
  },
  "artifacts": {},
  "schema_version": 2
}
```

**Validation rules (enforced by `parse_builder_state`):**
| Field | Type | Constraint | Default on missing |
|-------|------|-----------|-------------------|
| `summary.success` | `bool` | Must be boolean | `False` |
| `summary.test_passed` | `int` | Cast via `int()` | `0` |
| `summary.test_total` | `int` | Cast via `int()` | `0` |
| `summary.convergence_ratio` | `float` | Cast via `float()`, expected [0.0, 1.0] | `0.0` |
| `total_cost` | `float` | Cast via `float()`, expected >= 0 | `0.0` |
| `health` | `str` | Cast via `str()`, expected `"green"\|"yellow"\|"red"` | `"unknown"` |
| `completed_phases` | `list[str]` | Cast via `list()` | `[]` |
| `schema_version` | `int` | Not validated by parse_builder_state (validated at 2 in test fixtures) | N/A |

---

#### Cross-Build File Contract: FIX_INSTRUCTIONS.MD

Generated by `write_fix_instructions()` at `{cwd}/FIX_INSTRUCTIONS.md`:

```markdown
# Fix Instructions

## Priority: P0 (Must Fix)

### FINDING-001: Missing health endpoint
- **Component**: auth-service/main.py
- **Evidence**: GET /health returns 404
- **Action**: Add GET /health endpoint returning {"status": "healthy"}

## Priority: P1 (Should Fix)

### FINDING-002: Schema violation
- **Component**: order-service/routes.py
- **Evidence**: POST /orders response missing `total` field
- **Action**: Add `total` field to CreateOrderResponse model

## Priority: P2 (Nice to Have)

(violations with priority "P2" or default)
```

---

#### Cross-Build File Contract: config.yaml

Generated by `generate_builder_config()` at `{output_dir}/config.yaml`:

```yaml
milestone: build-{service_name}    # str — e.g., "build-auth-service"
depth: thorough                    # str — "quick"|"standard"|"thorough"|"exhaustive"
e2e_testing: true                  # bool — always true
post_orchestration_scans: true     # bool — always true
service_name: auth-service         # str — forward-compatible unknown key
mcp:                               # dict — present only if mcp_enabled=True
  enabled: true
  servers: {}
contracts:                         # list[dict] — present only if contracts provided
  - type: openapi
    path: contracts/auth-service.yaml
    service: auth-service
```

**`_dict_to_config()` compatibility:**
| Known Key | Type | Default |
|-----------|------|---------|
| `depth` | `str` | `"thorough"` |
| `milestone` | `str` | — |
| `e2e_testing` | `bool` | `True` |
| `post_orchestration_scans` | `bool` | — |
| `mcp` | `dict` | — |
| `contracts` | `list[dict]` | — |

All other keys (e.g., `service_name`) are collected in `unknown_keys: set[str]` — forward-compatible, no error.

---

### Test Files Created

##### `tests/run4/test_m3_builder_invocation.py` — 24 tests across 10 test classes

| Test Class | Tests | Requirements | Description |
|------------|-------|-------------|-------------|
| `TestBuilderSubprocessInvocation` | 2 | REQ-016 | Builder starts, exits 0, STATE.json written, stdout captured; BuilderResult has all required fields |
| `TestStateJsonParsingCrossBuild` | 3 | REQ-017 | STATE.json summary fields parsed with correct types; missing file returns defaults; corrupt JSON returns defaults |
| `TestConfigGenerationCompatibility` | 3 | REQ-018 | Config YAML for all 4 depths parseable by `_dict_to_config()`; contracts + MCP fields; returns Path |
| `TestParallelBuilderIsolation` | 2 | REQ-019 | 4 builders with max_concurrent=3; no cross-contamination; semaphore blocks 4th concurrent |
| `TestFixPassInvocation` | 3 | REQ-020 | FIX_INSTRUCTIONS.md written; builder invoked in quick mode; cost field updated; priority format P0/P1/P2; returns Path |
| `TestContractFixLoopReturnsBuilderResult` | 1 | REQ-020 | `ContractFixLoop.feed_violations_to_builder()` returns `BuilderResult` not float |
| `TestAgentTeamsFallbackCLIUnavailable` | 2 | WIRE-013 | CLI unavailable → `CLIBackend` + logged warning; disabled → `CLIBackend` |
| `TestAgentTeamsHardFailureNoFallback` | 2 | WIRE-014 | CLI unavailable + `fallback_to_cli=False` → `RuntimeError`; `fallback_to_cli` defaults to `True` |
| `TestBuilderTimeoutEnforcement` | 3 | WIRE-015 | `proc.kill()` + `await proc.wait()` on timeout in builder.py; same in fix_loop.py; with `timeout_s=5` scenario |
| `TestBuilderEnvironmentIsolation` | 1 | WIRE-016 | `ANTHROPIC_API_KEY` and `OPENAI_API_KEY` filtered; `PATH` inherited |
| `TestAgentTeamsPositivePath` | 2 | WIRE-021 | `AgentTeamsBackend.execute_wave()` with task state progression; `CLIBackend.execute_wave()` basic |

##### `tests/run4/test_m3_config_generation.py` — 14 tests across 5 test classes

| Test Class | Tests | Requirements | Description |
|------------|-------|-------------|-------------|
| `TestBuilderResultDataclassMapping` | 5 | TEST-009 | BuilderResult has all STATE.JSON + process fields; roundtrip from STATE.JSON fixture; defaults on missing; partial STATE.JSON; field type verification |
| `TestParallelBuilderResultAggregation` | 2 | TEST-010 | 3 distinct BuilderResults preserved per-service; aggregate cost and stats computation |
| `TestConfigYamlAllDepths` | 4 (parametrized) | SVC-020 | quick, standard, thorough, exhaustive → `_dict_to_config()` parses each without error |
| `TestConfigYamlWithContracts` | 2 | SVC-020 | Contracts + MCP fields present; MCP disabled → no `mcp` key |
| `TestConfigRoundtripPreservesFields` | 1 | SVC-020 | Generate → write → read → write → read → full equality; `_dict_to_config()` works on roundtripped config |

##### Helper Functions (internal to test files, not exported)

| File | Helper | Description |
|------|--------|-------------|
| `test_m3_builder_invocation.py` | `_write_state_json(output_dir, *, success, test_passed, test_total, convergence_ratio, total_cost, health, completed_phases)` | Write STATE.json fixture with keyword args |
| `test_m3_builder_invocation.py` | `_make_fake_builder_script(tmp_path, exit_code)` | Create Python script mimicking `agent_team` CLI |
| `test_m3_config_generation.py` | `_write_state_json(output_dir, data)` | Write STATE.json fixture from raw dict |

---

### Enum/Status Values

| Entity | Field | Valid Values | DB Type | API String | Default | Notes |
|--------|-------|-------------|---------|------------|---------|-------|
| `BuilderResult` (run4) | `health` | `"green"`, `"yellow"`, `"red"`, `"unknown"` | `str` | Same (lowercase) | `"unknown"` | From STATE.JSON; `"unknown"` is default when STATE.JSON missing |
| STATE.JSON | `health` | `"green"`, `"yellow"`, `"red"` | `str` | Same (lowercase) | N/A | Cross-build contract; `parse_builder_state` accepts any string |
| STATE.JSON | `schema_version` | `2` | `int` | `2` (integer) | N/A | Build 2 STATE.JSON uses version 2 (different from Run4State version 1) |
| `AgentTeamsConfig` | `enabled` | `true`, `false` | `bool` | Same | `False` | Agent Teams mode toggle |
| `AgentTeamsConfig` | `fallback_to_cli` | `true`, `false` | `bool` | Same | `True` | Fallback to CLIBackend when CLI unavailable |
| `ExecutionBackend` result | `backend` | `"cli"`, `"agent_teams"` | `str` | Same (lowercase) | N/A | Backend identifier in execute_wave result dicts |
| `ExecutionBackend` result | `status` | `"completed"` | `str` | Same (lowercase) | N/A | Task final status after execute_wave |
| `AgentTeamsBackend` task state | (progression) | `"pending"` → `"in_progress"` → `"completed"` | `str` | Same (lowercase) | `"pending"` | Task lifecycle states tracked in _task_updates |
| `AgentTeamsBackend._task_creates` | `action` | `"create"` | `str` | Same | N/A | TaskCreate action |
| `AgentTeamsBackend._task_updates` | `action` | `"update"` | `str` | Same | N/A | TaskUpdate action |
| `AgentTeamsBackend._send_messages` | `action` | `"send_message"` | `str` | Same | N/A | SendMessage action |
| config.yaml | `depth` | `"quick"`, `"standard"`, `"thorough"`, `"exhaustive"` | `str` | Same (lowercase) | `"thorough"` | Builder pass depth; all 4 tested |
| FIX_INSTRUCTIONS.md | priority sections | `"P0"`, `"P1"`, `"P2"` | `str` | `"P0 (Must Fix)"`, `"P1 (Should Fix)"`, `"P2 (Nice to Have)"` in section headers | `"P1"` (if violation lacks priority) | FIX_INSTRUCTIONS.md priority bucketing |
| `ContractFixLoop.classify_violations` | severity buckets | `"critical"`, `"error"`, `"warning"`, `"info"` | `str` (lowercase) | Same | `"error"` (fallback for unknown) | Violation classification in fix_loop.py |
| `ContractFixLoop` severity→priority | mapping | `"critical"→"P0"`, `"error"→"P1"`, all else→`"P2"` | `str` | Same | N/A | Used when converting ContractViolation to FIX_INSTRUCTIONS format |
| `ContractViolation` | `severity` | `"critical"`, `"error"`, `"warning"`, `"info"` (convention, not enforced) | `str` | Same (lowercase) | N/A | No runtime enforcement |
| `ServiceStatus` | (enum) | `"pending"`, `"building"`, `"built"`, `"deploying"`, `"healthy"`, `"unhealthy"`, `"failed"` | `str` (via str Enum) | Same (lowercase) | `"pending"` (ServiceInfo default) | Build 3 pipeline service lifecycle |
| `QualityLevel` | (enum) | `"layer1_service"`, `"layer2_contract"`, `"layer3_system"`, `"layer4_adversarial"` | `str` (via str Enum) | Same (lowercase) | N/A | Quality gate layer identifiers |
| `GateVerdict` | (enum) | `"passed"`, `"failed"`, `"partial"`, `"skipped"` | `str` (via str Enum) | Same (lowercase) | `"skipped"` (LayerResult, QualityGateReport defaults) | Quality gate verdicts |
| `IntegrationReport` | `overall_health` | `str` (not enumerated; `"unknown"` is default) | `str` | Same | `"unknown"` | Integration test health |

---

### Database State After This Milestone

**No new database tables created by M3.** All persistence is via JSON and YAML files:

| Persistence Target | File Path | Format | Write Method | Read Method |
|-------------------|-----------|--------|--------------|-------------|
| Builder STATE (read+write) | `{builder_dir}/.agent-team/STATE.json` | JSON | Written by builder subprocess (Build 2); written by test helpers in M3 tests | `parse_builder_state(output_dir)` → dict |
| Builder config | `{output_dir}/config.yaml` | YAML | `generate_builder_config()` → `yaml.dump()` | `yaml.safe_load()` then `_dict_to_config()` |
| Fix instructions | `{cwd}/FIX_INSTRUCTIONS.md` | Markdown | `write_fix_instructions()` → `Path.write_text()` | Read by builder subprocess (Build 2) |

---

### Environment Variables

M3 creates no new environment variables. The following are **filtered from subprocess environments** (SEC-001):

| Variable | Purpose | Behavior |
|----------|---------|----------|
| `ANTHROPIC_API_KEY` | Anthropic API secret key | **Filtered** from builder subprocess env; NOT passed to child processes |
| `OPENAI_API_KEY` | OpenAI API secret key | **Filtered** from builder subprocess env; NOT passed to child processes |
| `AWS_SECRET_ACCESS_KEY` | AWS secret key | **Filtered** from builder subprocess env; NOT passed to child processes |

All other parent process environment variables (e.g., `PATH`, `HOME`, `USERPROFILE`) are inherited by builder subprocesses.

---

### Files Created/Modified

| File | LOC | Purpose |
|------|-----|---------|
| `src/run4/builder.py` | 392 | **Expanded from 59-line M1 stub**: `BuilderResult` dataclass, `parse_builder_state` (full impl), `invoke_builder`, `run_parallel_builders`, `generate_builder_config`, `write_fix_instructions`, `feed_violations_to_builder`, `_state_to_builder_result`, `_filtered_env` |
| `src/run4/execution_backend.py` | 194 | **NEW**: `AgentTeamsConfig`, `ExecutionBackend` (abstract), `CLIBackend`, `AgentTeamsBackend`, `create_execution_backend` factory |
| `src/integrator/fix_loop.py` | 159 | **NEW**: `ContractFixLoop` class with `classify_violations()` and `feed_violations_to_builder()` |
| `tests/run4/test_m3_builder_invocation.py` | 909 | 24 tests: subprocess invocation, STATE.json parsing, config generation, parallel builders, fix pass, agent teams fallback/failure/positive, timeout, env isolation |
| `tests/run4/test_m3_config_generation.py` | 559 | 14 tests: BuilderResult mapping, parallel aggregation, config YAML for all depths, contracts, roundtrip |

---

### Known Limitations

1. **Two distinct `BuilderResult` dataclasses**: `src.run4.builder.BuilderResult` (M3, subprocess-oriented with exit_code/stdout/stderr/duration_s) and `src.build3_shared.models.BuilderResult` (Build 3 pipeline, with system_id/cost/error/output_dir/artifacts) are **different types with different fields**. Downstream milestones consuming builder results MUST use the correct import depending on context. Run4 tests use `src.run4.builder.BuilderResult`.

2. **`_dict_to_config` is a Build 3 compatibility shim**: The `_dict_to_config()` function in `src.super_orchestrator.pipeline` is a simplified version of Build 2's parser. It only validates known keys (`depth`, `milestone`, `e2e_testing`, `post_orchestration_scans`, `mcp`, `contracts`) and collects unknown keys. It does NOT validate values or enforce constraints.

3. **STATE.JSON `schema_version` mismatch**: Run4State uses `schema_version=1` (M1), while Build 2 STATE.JSON uses `schema_version=2`. `parse_builder_state()` does NOT validate schema_version — it reads fields regardless. Downstream milestones must not assume schema_version uniformity across these two state file types.

4. **No real subprocess execution in M3 tests**: All builder subprocess tests use `AsyncMock` or `patch` to intercept `asyncio.create_subprocess_exec`. The fake builder script test (`test_builder_subprocess_invocation`) patches the exec to redirect to a local Python script. Real `python -m agent_team` execution is NOT tested.

5. **AgentTeamsBackend is a stub implementation**: `AgentTeamsBackend.execute_wave()` does NOT actually call Claude Agent Teams SDK. It simulates TaskCreate/TaskUpdate/SendMessage by appending to internal lists. Real SDK integration is deferred.

6. **CLIBackend is a stub implementation**: `CLIBackend.execute_wave()` does NOT actually invoke builder subprocesses. It immediately marks all tasks as completed. Real subprocess integration happens via `invoke_builder()` / `run_parallel_builders()` in `builder.py`.

7. **`ContractFixLoop.classify_violations` unknown severity fallback**: Violations with severity values not in `("critical", "error", "warning", "info")` are silently placed in the `"error"` bucket. No warning is logged.

8. **FIX_INSTRUCTIONS.md priority groups with no violations are omitted**: If a priority tier (e.g., P2) has no matching violations, its section header is not written to the file. Only tiers with at least one violation appear.

9. **`_filtered_env` is duplicated**: The `_FILTERED_ENV_KEYS` constant and env-filtering logic appear in both `src.run4.builder` and `src.integrator.fix_loop`. Both filter the same 3 keys. Changes to one must be mirrored in the other.

10. **`config.yaml` depth values not validated**: `generate_builder_config()` accepts any string for `depth`. The tested values are `"quick"`, `"standard"`, `"thorough"`, `"exhaustive"` but no runtime validation enforces these.

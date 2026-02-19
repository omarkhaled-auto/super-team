## Milestone 1: Test Infrastructure + Fixtures
- ID: milestone-1
- Status: COMPLETE
- Dependencies: none
- Description: Establish the test framework, sample app fixtures, mock MCP servers, Run4Config, Run4State persistence, and shared test utilities that all subsequent milestones depend on.

---

### Overview

Milestone 1 creates the foundational layer for the entire Run 4 verification pipeline. Every subsequent milestone depends on the dataclasses, fixtures, utilities, and test infrastructure defined here. This milestone produces NO verification results — it purely builds the scaffolding.

### Estimated Effort
- **LOC**: ~1,200
- **Files**: 10 source + 7 fixture + 1 conftest = 18 files
- **Risk**: LOW (pure infrastructure, no external dependencies)
- **Duration**: 1-2 hours

---

### Source Files

#### 1. `src/run4/__init__.py`
- Package initialization
- Version constant: `__version__ = "1.0.0"`
- ~5 LOC

#### 2. `src/run4/config.py` (~120 LOC)
**Implements**: REQ-001, TECH-001

```
@dataclass
class Run4Config:
    # Build paths
    build1_project_root: Path
    build2_project_root: Path
    build3_project_root: Path
    output_dir: str = ".run4"

    # Docker settings
    compose_project_name: str = "super-team-run4"
    docker_compose_files: list[str]

    # MCP timeouts
    health_check_timeout_s: int = 120
    health_check_interval_s: float = 3.0
    mcp_startup_timeout_ms: int = 30000
    mcp_tool_timeout_ms: int = 60000
    mcp_first_start_timeout_ms: int = 120000

    # Builder settings
    max_concurrent_builders: int = 3
    builder_timeout_s: int = 1800
    builder_depth: str = "thorough"

    # Fix pass limits
    max_fix_passes: int = 5
    fix_effectiveness_floor: float = 0.30
    regression_rate_ceiling: float = 0.25

    # Budget
    max_budget_usd: float = 100.0

    # Paths
    sample_prd_path: str = "tests/run4/fixtures/sample_prd.md"
```

**Validation** (TECH-001):
- `__post_init__()` validates all path fields exist
- Raises `ValueError` with specific missing path message
- Converts string paths to `Path` objects

**Factory method**:
- `Run4Config.from_yaml(path: str) -> Run4Config` — parse `run4:` section from config.yaml

#### 3. `src/run4/state.py` (~200 LOC)
**Implements**: REQ-002, REQ-003, TECH-002

```
@dataclass
class Finding:
    finding_id: str          # FINDING-NNN pattern
    priority: str            # P0, P1, P2, P3
    system: str              # "Build 1", "Build 2", "Build 3", "Integration"
    component: str           # specific module/function
    evidence: str            # exact reproduction or test output
    recommendation: str      # specific fix action
    resolution: str          # "FIXED", "OPEN", "WONTFIX"
    fix_pass_number: int     # which pass fixed it (0 = unfixed)
    fix_verification: str    # test ID confirming fix
    created_at: str          # ISO 8601 timestamp

@dataclass
class Run4State:
    schema_version: int = 1
    run_id: str = ""
    current_phase: str = "init"
    completed_phases: list[str] = field(default_factory=list)

    # MCP health results
    mcp_health: dict[str, dict] = field(default_factory=dict)

    # Builder results
    builder_results: dict[str, dict] = field(default_factory=dict)

    # Defect catalog
    findings: list[Finding] = field(default_factory=list)

    # Fix pass metrics
    fix_passes: list[dict] = field(default_factory=list)

    # Scoring
    scores: dict[str, float] = field(default_factory=dict)
    aggregate_score: float = 0.0
    traffic_light: str = "RED"

    # Cost tracking
    total_cost: float = 0.0
    phase_costs: dict[str, float] = field(default_factory=dict)

    # Timestamps
    started_at: str = ""
    updated_at: str = ""
```

**Methods**:
- `save(path: Path) -> None`: Atomic write (write to `.tmp` then `os.replace`)
- `load(path: Path) -> Run4State | None`: Load with `schema_version` validation; returns `None` for missing/corrupted files
- `add_finding(finding: Finding) -> None`: Append to findings list
- `next_finding_id() -> str`: Generate `FINDING-NNN` with auto-increment

#### 4. `src/run4/mcp_health.py` (~150 LOC)
**Implements**: INT-004, INT-005

```
async def poll_until_healthy(
    service_urls: dict[str, str],
    timeout_s: float = 120,
    interval_s: float = 3.0,
    required_consecutive: int = 2
) -> dict[str, dict]:
    """Poll HTTP health endpoints until all services report healthy."""

async def check_mcp_health(
    server_params: StdioServerParameters,
    timeout: float = 30.0
) -> dict:
    """Spawn MCP server, initialize, list_tools, return health dict.
    Returns: {status, tools_count, tool_names, error}"""
```

#### 5. `src/run4/builder.py` (stub ~50 LOC, expanded in M3)
**Implements**: INT-006

```
def parse_builder_state(output_dir: Path) -> dict:
    """Read .agent-team/STATE.json, extract summary dict.
    Returns: {success, test_passed, test_total, convergence_ratio}"""
```

#### 6. `src/run4/fix_pass.py` (stub ~30 LOC, expanded in M5)
**Implements**: INT-007

```
def detect_regressions(
    before: dict[str, list[str]],
    after: dict[str, list[str]]
) -> list[dict]:
    """Compare violation snapshots, return regressed violations."""
```

#### 7. `src/run4/scoring.py` (stub ~10 LOC, expanded in M6)
#### 8. `src/run4/audit_report.py` (stub ~10 LOC, expanded in M6)

---

### Test Fixtures

#### 9. `tests/run4/fixtures/sample_prd.md` (~200 LOC)
**Implements**: REQ-004

TaskTracker PRD with 3 services:
- **auth-service** (Python/FastAPI): POST /register, POST /login, GET /users/me, GET /health
- **order-service** (Python/FastAPI): POST /orders, GET /orders/:id, PUT /orders/:id, GET /health
- **notification-service** (Python/FastAPI): POST /notify, GET /notifications, GET /health

Must include:
- Service descriptions with endpoints
- Data models (User, Order, Notification)
- Inter-service contracts (JWT auth, event publishing)
- Technology stack specification (FastAPI, PostgreSQL)

#### 10. `tests/run4/fixtures/sample_openapi_auth.yaml` (~150 LOC)
**Implements**: REQ-005, TECH-003

OpenAPI 3.1 spec for auth-service:
- `POST /register` — request: {email, password, name}, response: {id, email, created_at}
- `POST /login` — request: {email, password}, response: {access_token, refresh_token}
- `GET /users/me` — header: Authorization Bearer, response: {id, email, name, created_at}
- `GET /health` — response: {status: "healthy"}
- Components: schemas for User, RegisterRequest, LoginRequest, TokenResponse, ErrorResponse
- SecuritySchemes: bearerAuth (JWT)

#### 11. `tests/run4/fixtures/sample_openapi_order.yaml` (~180 LOC)
**Implements**: REQ-006, TECH-003

OpenAPI 3.1 spec for order-service:
- `POST /orders` — header: JWT auth, request: {items: [{product_id, quantity, price}]}, response: {id, status, items, total}
- `GET /orders/{id}` — response: {id, status, items, total, user_id, created_at}
- `PUT /orders/{id}` — request: {status}, response: {id, status, updated_at}
- `GET /health` — response: {status: "healthy"}
- Components: Order, OrderItem, CreateOrderRequest, ErrorResponse
- SecuritySchemes: bearerAuth (JWT)

#### 12. `tests/run4/fixtures/sample_asyncapi_order.yaml` (~120 LOC)
**Implements**: REQ-007, TECH-003

AsyncAPI 3.0 spec for order events:
- Channel `order/created`: payload {order_id, user_id, items: [{product_id, quantity, price}], total, created_at}
- Channel `order/shipped`: payload {order_id, user_id, shipped_at, tracking_number}
- Servers: development (redis://redis:6379)

#### 13. `tests/run4/fixtures/sample_pact_auth.json` (~80 LOC)
**Implements**: REQ-008

Pact V4 contract:
- Consumer: order-service
- Provider: auth-service
- Interaction: order-service verifying JWT via POST /login
- Request: {email, password}
- Response: 200, {access_token, refresh_token}

---

### Test Configuration

#### 14. `tests/run4/__init__.py`
- Empty package init

#### 15. `tests/run4/conftest.py` (~120 LOC)
**Implements**: INT-001, INT-002, INT-003

**Session-scoped fixtures** (INT-001):
```python
@pytest.fixture(scope="session")
def run4_config() -> Run4Config: ...

@pytest.fixture(scope="session")
def sample_prd_text() -> str: ...

@pytest.fixture(scope="session")
def build1_root() -> Path: ...

@pytest.fixture(scope="session")
def contract_engine_params() -> StdioServerParameters: ...

@pytest.fixture(scope="session")
def architect_params() -> StdioServerParameters: ...

@pytest.fixture(scope="session")
def codebase_intel_params() -> StdioServerParameters: ...
```

**Mock MCP fixture** (INT-002):
```python
@pytest.fixture
def mock_mcp_session() -> AsyncMock:
    """AsyncMock with call_tool, list_tools, initialize methods."""
```

**Helper function** (INT-003):
```python
def make_mcp_result(data: dict, is_error: bool = False) -> MockToolResult:
    """Build mock MCP tool result with TextContent containing JSON."""
```

---

### Tests

#### 16. `tests/run4/test_m1_infrastructure.py` (~200 LOC)
**Implements**: TEST-001 through TEST-007

| Test ID | Function | Description | Priority |
|---------|----------|-------------|----------|
| TEST-001 | `test_state_save_load_roundtrip` | Save Run4State, load it back, verify ALL fields preserved including nested dicts and lists | P0 |
| TEST-002a | `test_state_load_missing_file` | `Run4State.load()` returns `None` for missing file | P0 |
| TEST-002b | `test_state_load_corrupted_json` | `Run4State.load()` returns `None` for corrupted JSON | P0 |
| TEST-003 | `test_config_validates_paths` | `Run4Config` raises `ValueError` when build root path missing | P0 |
| TEST-004 | `test_fixture_yaml_validity` | All OpenAPI specs pass `openapi-spec-validator`; AsyncAPI spec validates structurally against 3.0 schema | P1 |
| TEST-005 | `test_mock_mcp_session_usable` | `mock_mcp_session` fixture returns `AsyncMock` with callable methods | P1 |
| TEST-006 | `test_poll_until_healthy_success` | `poll_until_healthy` returns results within timeout for healthy mock HTTP servers | P1 |
| TEST-007 | `test_detect_regressions_finds_new` | `detect_regressions()` correctly identifies new violations not in previous snapshot | P1 |

---

### Requirements Traceability

| Requirement | File(s) | Test(s) | Status |
|-------------|---------|---------|--------|
| REQ-001 | `src/run4/config.py` | TEST-003 | [x] (review_cycles: 1) |
| REQ-002 | `src/run4/state.py` | TEST-001, TEST-002 | [x] (review_cycles: 1) |
| REQ-003 | `src/run4/state.py` | TEST-001, TEST-002 | [x] (review_cycles: 1) |
| REQ-004 | `tests/run4/fixtures/sample_prd.md` | TEST-004 | [x] (review_cycles: 1) |
| REQ-005 | `tests/run4/fixtures/sample_openapi_auth.yaml` | TEST-004 | [x] (review_cycles: 1) |
| REQ-006 | `tests/run4/fixtures/sample_openapi_order.yaml` | TEST-004 | [x] (review_cycles: 1) |
| REQ-007 | `tests/run4/fixtures/sample_asyncapi_order.yaml` | TEST-004 | [x] (review_cycles: 1) |
| REQ-008 | `tests/run4/fixtures/sample_pact_auth.json` | TEST-004 | [x] (review_cycles: 1) |
| TECH-001 | `src/run4/config.py` | TEST-003 | [x] (review_cycles: 1) |
| TECH-002 | `src/run4/state.py` | TEST-001 | [x] (review_cycles: 1) |
| TECH-003 | fixture YAML files | TEST-004 | [x] (review_cycles: 1) |
| INT-001 | `tests/run4/conftest.py` | TEST-005 | [x] (review_cycles: 1) |
| INT-002 | `tests/run4/conftest.py` | TEST-005 | [x] (review_cycles: 1) |
| INT-003 | `tests/run4/conftest.py` | TEST-005 | [x] (review_cycles: 1) |
| INT-004 | `src/run4/mcp_health.py` | TEST-006 | [x] (review_cycles: 1) |
| INT-005 | `src/run4/mcp_health.py` | TEST-006 | [x] (review_cycles: 1) |
| INT-006 | `src/run4/builder.py` | (tested in M3) | [x] (review_cycles: 1) |
| INT-007 | `src/run4/fix_pass.py` | TEST-007 | [x] (review_cycles: 1) |

---

### Implementation Order (within milestone)

1. `src/run4/__init__.py` — no dependencies
2. `src/run4/config.py` — depends on nothing
3. `src/run4/state.py` — depends on nothing
4. `src/run4/mcp_health.py` — depends on `mcp` SDK
5. `src/run4/builder.py` (stub) — depends on nothing
6. `src/run4/fix_pass.py` (stub) — depends on nothing
7. `src/run4/scoring.py` (stub) — depends on nothing
8. `src/run4/audit_report.py` (stub) — depends on nothing
9. All fixture files — independent of source
10. `tests/run4/__init__.py` — no dependencies
11. `tests/run4/conftest.py` — depends on config.py, state.py, mcp_health.py
12. `tests/run4/test_m1_infrastructure.py` — depends on conftest.py + all source + fixtures

### Gate Condition

**Milestone 1 is COMPLETE when**: All TEST-001 through TEST-007 pass. This unblocks M2 and M3.

### Existing Code Dependencies

| Module | Usage | Risk |
|--------|-------|------|
| `mcp` SDK | `StdioServerParameters` for MCP session creation | Must be >=1.25 |
| `httpx` | Async health check polling | Standard usage |
| `pydantic` | May use for config validation (optional) | Already in project |
| `openapi-spec-validator` | TECH-003 fixture validation | New dev dependency |

### Anti-Patterns to Avoid

- Do NOT modify any existing `src/shared/` models — Run4 dataclasses are independent
- Do NOT import from `src/build3_shared/` — those are Build 3 internal models
- Do NOT use `print()` — use `logging` module throughout
- Do NOT hardcode paths — all paths flow through `Run4Config`

---

### CONTRACTS — Module Exports (Milestone 1)

#### Public Exports

| Module | Export | Type | Description |
|--------|--------|------|-------------|
| `src.run4` | `__version__` | `str` | Package version "1.0.0" |
| `src.run4.config` | `Run4Config` | `dataclass` | Pipeline configuration with path validation |
| `src.run4.config` | `Run4Config.from_yaml(path)` | `classmethod` | YAML config loader |
| `src.run4.state` | `Finding` | `dataclass` | Single defect/observation record |
| `src.run4.state` | `Run4State` | `dataclass` | Full pipeline state with atomic persistence |
| `src.run4.state` | `Run4State.save(path)` | `method` | Atomic JSON write |
| `src.run4.state` | `Run4State.load(path)` | `classmethod` | Load with schema validation |
| `src.run4.state` | `Run4State.add_finding(f)` | `method` | Append finding to catalog |
| `src.run4.state` | `Run4State.next_finding_id()` | `method` | Auto-increment FINDING-NNN |
| `src.run4.mcp_health` | `poll_until_healthy(...)` | `async function` | HTTP health polling |
| `src.run4.mcp_health` | `check_mcp_health(...)` | `async function` | MCP stdio health check |
| `src.run4.builder` | `parse_builder_state(dir)` | `function` | Builder STATE.json parser (stub) |
| `src.run4.fix_pass` | `detect_regressions(b, a)` | `function` | Violation regression detector |
| `src.run4.scoring` | `compute_scores(...)` | `function` | Category scorer (stub) |
| `src.run4.audit_report` | `generate_report(...)` | `function` | Markdown report generator (stub) |
| `tests.run4.conftest` | `make_mcp_result(data, is_error)` | `function` | Mock MCP result builder |
| `tests.run4.conftest` | `MockToolResult` | `dataclass` | Mock MCP CallToolResult |
| `tests.run4.conftest` | `MockTextContent` | `dataclass` | Mock MCP TextContent |

#### Predecessor Dependencies

None — Milestone 1 has no predecessor milestones.

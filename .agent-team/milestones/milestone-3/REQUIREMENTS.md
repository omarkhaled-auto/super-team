## Milestone 3: Build 2 to Build 3 Wiring Verification
- ID: milestone-3
- Status: PENDING
- Dependencies: milestone-1
- Description: Verify that Build 3's Super Orchestrator can invoke Build 2 Builders as subprocesses, parse their output, generate valid configs, and feed fix instructions. Test parallel builder isolation.

---

### Overview

Milestone 3 validates the subprocess integration layer between Build 3 (Orchestration Layer) and Build 2 (Builder Fleet). Unlike M2's MCP protocol testing, M3 tests CLI subprocess invocation, JSON state file contracts, config generation compatibility, and parallel process isolation.

### Estimated Effort
- **LOC**: ~800
- **Files**: 2 test files + builder.py expansion
- **Risk**: MEDIUM (subprocess management, Windows process handling)
- **Duration**: 1-2 hours

---

### Subprocess Wiring Map

| SVC-ID | Caller | Command | Input | Output | Verification |
|--------|--------|---------|-------|--------|-------------|
| SVC-018 | `pipeline.run_parallel_builders` | `python -m agent_team --cwd {dir} --depth {depth}` | config.yaml in builder dir | `.agent-team/STATE.json` with summary dict | Exit code 0, STATE.json has `summary.success` |
| SVC-019 | `fix_loop.feed_violations_to_builder` | `python -m agent_team --cwd {dir} --depth quick` | FIX_INSTRUCTIONS.md in builder dir | Updated STATE.json with cost | Violations reduced after fix pass |
| SVC-020 | `pipeline.generate_builder_config` | N/A (file write) | SuperOrchestratorConfig | config.yaml loadable by `_dict_to_config()` | Config roundtrip: generate -> load -> no errors |

---

### Source File Updates

#### `src/run4/builder.py` (expand from stub, ~200 LOC total)
**Implements**: REQ-016 through REQ-020, INT-006

```python
@dataclass
class BuilderResult:
    service_name: str
    success: bool
    test_passed: int
    test_total: int
    convergence_ratio: float
    total_cost: float
    health: str
    completed_phases: list[str]
    exit_code: int
    stdout: str
    stderr: str
    duration_s: float

async def invoke_builder(
    cwd: Path,
    depth: str = "thorough",
    timeout_s: int = 1800,
    env: dict | None = None
) -> BuilderResult:
    """Invoke `python -m agent_team --cwd {cwd} --depth {depth}`.
    Uses asyncio.create_subprocess_exec.
    Captures stdout/stderr.
    Returns BuilderResult parsed from STATE.json."""

async def run_parallel_builders(
    builder_configs: list[dict],
    max_concurrent: int = 3,
    timeout_s: int = 1800
) -> list[BuilderResult]:
    """Launch builders with asyncio.Semaphore(max_concurrent).
    Each builder writes to its own directory.
    Returns list of BuilderResult."""

def generate_builder_config(
    service_name: str,
    output_dir: Path,
    depth: str = "thorough",
    contracts: list[dict] | None = None,
    mcp_enabled: bool = True
) -> Path:
    """Generate config.yaml compatible with Build 2's _dict_to_config().
    Returns path to generated config.yaml."""

def parse_builder_state(output_dir: Path) -> dict:
    """Read .agent-team/STATE.json, extract summary dict.
    Returns: {success, test_passed, test_total, convergence_ratio}"""

async def feed_violations_to_builder(
    cwd: Path,
    violations: list[dict],
    timeout_s: int = 600
) -> BuilderResult:
    """Write FIX_INSTRUCTIONS.md to cwd, invoke builder in quick mode."""

def write_fix_instructions(
    cwd: Path,
    violations: list[dict],
    priority_order: list[str] = ["P0", "P1", "P2"]
) -> Path:
    """Generate FIX_INSTRUCTIONS.md with categorized violations."""
```

---

### Test Files

#### 1. `tests/run4/test_m3_builder_invocation.py` (~350 LOC)
**Implements**: REQ-016 through REQ-020, WIRE-013 through WIRE-016, WIRE-021

##### Builder Subprocess Tests

| Test | Requirement | Description |
|------|-------------|-------------|
| `test_builder_subprocess_invocation` | REQ-016 | Build 3 calls `python -m agent_team --cwd {dir} --depth thorough`; builder starts, runs, exits 0; `STATE.json` written with summary dict; stdout/stderr captured |
| `test_state_json_parsing_cross_build` | REQ-017 | Verify Build 2's `RunState.to_dict()` writes summary with: success (bool), test_passed (int), test_total (int), convergence_ratio (float); also total_cost, health, completed_phases at top level |
| `test_config_generation_compatibility` | REQ-018 | Build 3's `generate_builder_config()` produces config.yaml parseable by Build 2's `_dict_to_config()`; test all depths: quick, standard, thorough, exhaustive; verify returns `tuple[AgentTeamConfig, set[str]]` |
| `test_parallel_builder_isolation` | REQ-019 | Launch 3 builders with `asyncio.Semaphore(3)`; each writes to own dir; verify no cross-contamination; verify Semaphore prevents 4th concurrent builder |
| `test_fix_pass_invocation` | REQ-020 | Write FIX_INSTRUCTIONS.md with categorized violations; invoke builder in quick mode; verify builder reads it; parse updated STATE.json; verify cost field updated |

##### Wiring Tests

| Test | Wire ID | Description |
|------|---------|-------------|
| `test_agent_teams_fallback_cli_unavailable` | WIRE-013 | `agent_teams.enabled=True` but Claude CLI unavailable; `create_execution_backend()` returns `CLIBackend` with logged warning; pipeline continues |
| `test_agent_teams_hard_failure_no_fallback` | WIRE-014 | `agent_teams.enabled=True`, `fallback_to_cli=False`, CLI unavailable; verify `RuntimeError` raised |
| `test_builder_timeout_enforcement` | WIRE-015 | Set `builder_timeout_s=5`; invoke builder on long task; verify `proc.kill() + await proc.wait()` in finally block |
| `test_builder_environment_isolation` | WIRE-016 | Verify builders inherit parent environment; ANTHROPIC_API_KEY is NOT passed explicitly (SEC-001 compliance) |
| `test_agent_teams_positive_path` | WIRE-021 | `agent_teams.enabled=True`, CLI available; `AgentTeamsBackend.execute_wave()` completes with task state progression (pending -> in_progress -> completed); verify TaskCreate, TaskUpdate, SendMessage invoked |

#### 2. `tests/run4/test_m3_config_generation.py` (~200 LOC)
**Implements**: SVC-020, TEST-009, TEST-010

| Test | Requirement | Description |
|------|-------------|-------------|
| `test_builder_result_dataclass_mapping` | TEST-009 | `BuilderResult` correctly maps all STATE.JSON summary fields |
| `test_parallel_builder_result_aggregation` | TEST-010 | Collect `BuilderResult` from 3 builders; verify per-service results preserved in aggregate |
| `test_config_yaml_all_depths` | SVC-020 | Generate config for each depth level; verify `_dict_to_config()` loads without error |
| `test_config_yaml_with_contracts` | SVC-020 | Generate config with contract-aware settings; verify MCP-related fields present |
| `test_config_roundtrip_preserves_fields` | SVC-020 | Generate -> write -> read -> parse; all fields intact |

---

### STATE.JSON Cross-Build Contract

The STATE.JSON file is the critical interface between Build 2 and Build 3. Expected structure:

```json
{
  "run_id": "string",
  "health": "green|yellow|red",
  "current_phase": "string",
  "completed_phases": ["phase1", "phase2"],
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

**Validation rules**:
- `summary.success` MUST be boolean
- `summary.test_passed` and `summary.test_total` MUST be int
- `summary.convergence_ratio` MUST be float in [0.0, 1.0]
- `total_cost` MUST be float >= 0
- `health` MUST be one of "green", "yellow", "red"
- `completed_phases` MUST be list of strings

---

### FIX_INSTRUCTIONS.MD Format

```markdown
# Fix Instructions

## Priority: P0 (Must Fix)

### FINDING-001: Missing health endpoint
- **Component**: auth-service/main.py
- **Evidence**: GET /health returns 404
- **Action**: Add GET /health endpoint returning {"status": "healthy"}

### FINDING-002: Schema violation
- **Component**: order-service/routes.py
- **Evidence**: POST /orders response missing `total` field
- **Action**: Add `total` field to CreateOrderResponse model

## Priority: P1 (Should Fix)

### FINDING-003: Print statement
- **Component**: notification-service/handlers.py
- **Evidence**: Line 42: print("notification sent")
- **Action**: Replace with logger.info("notification sent")
```

---

### Test Matrix Mapping (B2 + B3 + X entries for M3)

| Matrix ID | Test Function | Priority |
|-----------|---------------|----------|
| B2-01 | `test_ce_client_all_methods` | P0 |
| B2-02 | `test_ci_client_all_methods` | P0 |
| B2-03 | `test_mcp_safe_defaults` | P0 |
| B2-04 | `test_contract_scan_detection` | P0 |
| B2-05 | `test_parallel_builders` | P1 |
| B2-06 | `test_artifact_registration` | P1 |
| B2-09 | `test_backward_compat` | P1 |
| B2-10 | `test_retry_exponential_backoff` | P1 |
| X-03 | `test_mcp_b1_to_b3_architect` | P0 |
| X-04 | `test_subprocess_b3_to_b2` | P0 |
| X-05 | `test_state_json_contract` | P0 |
| X-06 | `test_config_generation_compat` | P0 |

---

### SVC Wiring Checklist

- [ ] SVC-018: pipeline.run_parallel_builders -> agent_team CLI subprocess
- [ ] SVC-019: fix_loop.feed_violations_to_builder -> agent_team CLI quick mode
- [ ] SVC-020: pipeline.generate_builder_config -> Build 2 config.yaml

---

### Dependencies on Milestone 1

| M1 Output | M3 Usage |
|-----------|----------|
| `Run4Config` | `builder_timeout_s`, `max_concurrent_builders`, `builder_depth` |
| `Run4State` | State persistence for builder results |
| `parse_builder_state()` stub | Expanded implementation |
| `conftest.py` fixtures | `run4_config`, `build1_root` |

### Risk Analysis

| Risk | Impact | Mitigation |
|------|--------|------------|
| Windows subprocess management | Orphan processes on timeout | Use `proc.terminate()` then `proc.kill()` with 5s grace |
| Build 2 `_dict_to_config()` return type changed | Config compat test fails | Verify against current Build 2 source |
| Agent Teams CLI not installed | WIRE-021 can't run | Mark as `skipif` with reason |
| Semaphore doesn't truly isolate filesystem | Cross-contamination possible | Verify with unique marker files per builder |

### Gate Condition

**Milestone 3 is COMPLETE when**: All REQ-016 through REQ-020, WIRE-013 through WIRE-016, WIRE-021, TEST-009, TEST-010 tests pass. Combined with M2 completion, this unblocks M4.

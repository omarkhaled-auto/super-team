# Library / MCP Audit Report — Milestone 3

**Auditor**: Library/MCP Auditor
**Date**: 2026-02-19
**Scope**: All third-party library API usage across the codebase, with focus on Milestone 3 (subprocess wiring, builder invocation, config generation)
**Method**: Verified against official documentation via Context7, runtime introspection of installed packages, and official source code

---

## Executive Summary

Audited **8 major libraries** against their official documentation. Found **3 CRITICAL** findings (runtime errors), **1 HIGH** finding, **2 MEDIUM** findings, and **3 LOW/INFO** observations. The critical issues are all in `src/super_orchestrator/pipeline.py` and involve dataclass field mismatches that will cause `TypeError` or `AttributeError` at runtime when the fix-pass or builder-timeout code paths are exercised.

---

## Libraries Audited

| Library | Version Spec | Installed | Status |
|---------|-------------|-----------|--------|
| FastAPI | `==0.129.0` | 0.129.0 | Verified real version on PyPI |
| httpx | `>=0.27.0` | 0.27.x+ | API usage correct |
| MCP SDK | `>=1.25,<2` | 1.26.0 | API usage correct |
| transitions | `>=0.9.0` | 0.9.3 | API usage correct |
| typer | `[all]>=0.12.0` | 0.12.x+ | Minor issues found |
| pytest-asyncio | `>=0.23.0` | 1.3.0 | Redundant decorators |
| Pydantic | `>=2.5.0` | 2.x | V2 API used correctly |
| PyYAML | `>=6.0` | 6.x | `yaml.safe_load` correct |

---

## Findings

---

### FINDING-001: `BuilderResult` constructed without required `system_id` field

- **Severity**: CRITICAL
- **Library**: Python dataclasses (stdlib) / `src.build3_shared.models.BuilderResult`
- **Component**: `src/super_orchestrator/pipeline.py` (lines 583, 689, 700, 745, 754)
- **Evidence**:
  The `BuilderResult` dataclass defines `system_id: str` as its **first positional field with no default value**:
  ```python
  # src/build3_shared/models.py:51-63
  @dataclass
  class BuilderResult:
      system_id: str        # <-- REQUIRED, no default
      service_id: str       # <-- REQUIRED, no default
      success: bool = False
      ...
  ```
  But five call sites construct `BuilderResult` without passing `system_id`:
  ```python
  # pipeline.py:583 (shutdown path)
  return BuilderResult(
      service_id=svc.service_id,  # TypeError: missing 'system_id'
      success=False,
      error="Pipeline shutdown requested",
  )
  ```
  Same pattern at lines 689 (timeout), 700 (exception), 745 (no STATE.json), 754 (parse error).
- **Impact**: `TypeError: BuilderResult.__init__() missing 1 required positional argument: 'system_id'` at runtime when any builder fails, times out, or is interrupted by shutdown. This affects the M3 `test_builder_timeout_enforcement` (WIRE-015) and `test_parallel_builder_isolation` (REQ-019) code paths directly.
- **Recommendation**: Either add `system_id=""` parameter to these 5 call sites, or change the `BuilderResult` dataclass to give `system_id` a default value (`system_id: str = ""`).

---

### FINDING-002: `ContractViolation` constructed with non-existent `line` field

- **Severity**: CRITICAL
- **Library**: Python dataclasses (stdlib) / `src.build3_shared.models.ContractViolation`
- **Component**: `src/super_orchestrator/pipeline.py` (line 1149)
- **Evidence**:
  The `ContractViolation` dataclass does NOT have a `line` field:
  ```python
  # src/build3_shared/models.py:67-76
  @dataclass
  class ContractViolation:
      code: str
      severity: str
      service: str
      endpoint: str
      message: str
      expected: str = ""
      actual: str = ""
      file_path: str = ""
      # NOTE: no 'line' field
  ```
  But `pipeline.py` line 1149 passes `line=int(...)`:
  ```python
  ContractViolation(
      ...
      file_path=str(v_data.get("file_path", "")),
      line=int(v_data.get("line", 0)),   # <-- TypeError
  )
  ```
- **Impact**: `TypeError: ContractViolation.__init__() got an unexpected keyword argument 'line'` at runtime during the fix-pass phase (`run_fix_pass` in pipeline.py). This blocks M3 test `test_fix_pass_invocation` (REQ-020).
- **Recommendation**: Either add `line: int = 0` to the `ContractViolation` dataclass, or remove the `line=` kwarg from the constructor call.

---

### FINDING-003: `config.builder.timeout` references non-existent attribute

- **Severity**: CRITICAL
- **Library**: Python dataclasses (stdlib) / `src.super_orchestrator.config.BuilderConfig`
- **Component**: `src/super_orchestrator/pipeline.py` (lines 681, 687, 692, 1131)
- **Evidence**:
  The `BuilderConfig` dataclass uses `timeout_per_builder`:
  ```python
  # src/super_orchestrator/config.py:21-27
  @dataclass
  class BuilderConfig:
      max_concurrent: int = 3
      timeout_per_builder: int = 1800   # <-- actual field name
      depth: str = "thorough"
  ```
  But `pipeline.py` accesses `config.builder.timeout` (4 times):
  ```python
  # pipeline.py:681
  await asyncio.wait_for(proc.wait(), timeout=config.builder.timeout)
  # pipeline.py:687
  config.builder.timeout,
  # pipeline.py:692
  error=f"Timed out after {config.builder.timeout}s",
  # pipeline.py:1131
  fix_loop = ContractFixLoop(timeout=config.builder.timeout)
  ```
- **Impact**: `AttributeError: 'BuilderConfig' object has no attribute 'timeout'` at runtime when builder subprocess execution or fix-loop is triggered. This directly blocks M3 `test_builder_subprocess_invocation` (REQ-016), `test_builder_timeout_enforcement` (WIRE-015), and `test_fix_pass_invocation` (REQ-020).
- **Recommendation**: Either rename `timeout_per_builder` to `timeout` in `BuilderConfig`, or change all pipeline references to `config.builder.timeout_per_builder`.

---

### FINDING-004: `config.integration.compose_timeout` references non-existent attribute

- **Severity**: HIGH
- **Library**: Python dataclasses (stdlib) / `src.super_orchestrator.config.IntegrationConfig`
- **Component**: `src/super_orchestrator/pipeline.py` (line 853)
- **Evidence**:
  The `IntegrationConfig` dataclass uses `timeout`:
  ```python
  # src/super_orchestrator/config.py:30-37
  @dataclass
  class IntegrationConfig:
      timeout: int = 600               # <-- actual field name
      traefik_image: str = "traefik:v3.6"
      compose_file: str = "docker-compose.yml"
      test_compose_file: str = "docker-compose.test.yml"
  ```
  But `pipeline.py` accesses `config.integration.compose_timeout`:
  ```python
  # pipeline.py:853
  health_result = await docker.wait_for_healthy(
      timeout_seconds=config.integration.compose_timeout,  # <-- AttributeError
  )
  ```
  Additionally, the YAML template in `cli.py` (line 116) defines `compose_timeout: 120` which will be silently ignored by `load_super_config` because the `IntegrationConfig` dataclass's `_pick()` filter will discard it as an unknown key.
- **Impact**: `AttributeError: 'IntegrationConfig' object has no attribute 'compose_timeout'` at runtime during the integration phase. While not directly in M3 scope (integration is part of the broader pipeline), it blocks the integration phase that the quality gate depends on.
- **Recommendation**: Either add `compose_timeout: int = 120` to `IntegrationConfig` (and rename/alias the existing `timeout`), or change the pipeline reference to `config.integration.timeout`.

---

### FINDING-005: Rich markup tags in `typer.echo()` render as literal text

- **Severity**: MEDIUM
- **Library**: typer (>=0.12.0)
- **Component**: `src/super_orchestrator/cli.py` (lines 192-195, 455, 545)
- **Evidence**:
  The app is configured with `rich_markup_mode="rich"`, but Rich markup only applies to **help text**, not to runtime output via `typer.echo()`. These calls pass Rich markup tags that will render as literal text:
  ```python
  # cli.py:192-195
  typer.echo(
      "[yellow]Warning: Docker Compose not available. "
      "Integration phase will not work.[/yellow]"
  )
  # cli.py:455
  typer.echo("\n[yellow]Pipeline interrupted. State saved.[/yellow]")
  # cli.py:545
  typer.echo("\n[yellow]Pipeline interrupted. State saved.[/yellow]")
  ```
  Per official Typer documentation, `typer.echo()` does NOT interpret Rich markup. The user will see literal `[yellow]...[/yellow]` text in their terminal.
- **Impact**: Cosmetic issue. Warning messages display with raw markup tags instead of colored text.
- **Recommendation**: Replace `typer.echo()` with `rich.print()` for these Rich-formatted messages, or use the project's existing `display.py` utilities (e.g., `print_error_panel`).

---

### FINDING-006: `@pytest.mark.asyncio` decorators redundant with `asyncio_mode = "auto"`

- **Severity**: MEDIUM
- **Library**: pytest-asyncio (>=0.23.0, installed 1.3.0)
- **Component**: 10 test files across `tests/build3/` and `tests/run4/`
- **Evidence**:
  The project configures pytest-asyncio in auto mode:
  ```toml
  # pyproject.toml:53
  asyncio_mode = "auto"
  ```
  Per official documentation: "The `pytest.mark.asyncio` marker can be omitted entirely in auto mode where the asyncio marker is added automatically to async test functions."

  Yet **225 `@pytest.mark.asyncio` decorators** exist across 10 files:
  | File | Redundant Count |
  |------|----------------|
  | `tests/run4/test_m2_mcp_wiring.py` | 60 |
  | `tests/build3/test_cross_service.py` | 37 |
  | `tests/run4/test_m2_client_wrappers.py` | 32 |
  | `tests/build3/test_pipeline.py` | 27 |
  | `tests/build3/test_state_machine.py` | 21 |
  | `tests/build3/test_contract_compliance.py` | 20 |
  | `tests/build3/test_docker_orchestrator.py` | 10 |
  | `tests/build3/test_fix_loop.py` | 7 |
  | `tests/run4/test_m1_infrastructure.py` | 6 |
  | `tests/build3/test_service_discovery.py` | 5 |
- **Impact**: No runtime impact -- decorators are harmless but add visual noise and may mislead developers into thinking they are required. They also complicate maintenance.
- **Recommendation**: Remove all 225 redundant `@pytest.mark.asyncio` decorators. The only reason to keep a marker is to override `loop_scope` (e.g., `@pytest.mark.asyncio(loop_scope="class")`), which this codebase does not use.

---

### FINDING-007: FastAPI lifespan type annotation imprecise

- **Severity**: LOW
- **Library**: FastAPI (==0.129.0)
- **Component**: `src/architect/main.py:22`, `src/codebase_intelligence/main.py`, `src/contract_engine/main.py`
- **Evidence**:
  The lifespan functions are annotated as:
  ```python
  async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
  ```
  The official FastAPI documentation uses no return annotation at all. The more precise annotation would be `AsyncIterator[None]` since `@asynccontextmanager` wraps the generator. `AsyncGenerator[None, None]` implies a generator with both yield and send types, which is more than the context manager protocol requires. This can cause mypy/pyright warnings.
- **Impact**: No runtime impact. Static type checker warnings only.
- **Recommendation**: Change to `-> AsyncIterator[None]` or remove the return annotation entirely to match official docs.

---

### FINDING-008: Typer version option type annotation deviates from docs

- **Severity**: LOW
- **Library**: typer (>=0.12.0)
- **Component**: `src/super_orchestrator/cli.py` (line 80-89)
- **Evidence**:
  The version option is declared as:
  ```python
  version: Annotated[bool, typer.Option(...)] = False
  ```
  Official Typer documentation recommends:
  ```python
  version: Annotated[Optional[bool], typer.Option(...)] = None
  ```
  Using `bool = False` works but doesn't match the documented convention for eager-callback boolean options.
- **Impact**: No runtime impact. The callback correctly checks `if value:` which works with both `False` and `None`.
- **Recommendation**: Consider changing to `Optional[bool] = None` for consistency with official docs.

---

### FINDING-009: Pydantic v2 API usage is correct across the codebase

- **Severity**: INFO
- **Library**: Pydantic (>=2.5.0)
- **Component**: Entire codebase
- **Evidence**:
  All Pydantic models consistently use v2 API:
  - `model_dump(mode="json")` -- used in all MCP servers and routers (38+ call sites)
  - `model_dump_json()` -- used in storage layers
  - `model_validate_json()` -- used in storage layers
  - `model_copy(update={...})` -- used in architect service
  - `BaseModel` subclassing -- 40+ model classes
  - `pydantic_settings.BaseSettings` -- used for config
  - `model_validator` decorator -- used in some models

  No deprecated Pydantic v1 API calls found (`.dict()`, `.json()`, `.parse_obj()`, `.parse_raw()`, `.from_orm()` are all absent). The codebase is fully migrated to Pydantic v2.
- **Impact**: None -- this is a positive observation.

---

### FINDING-010: MCP SDK API usage is correct and verified

- **Severity**: INFO
- **Library**: MCP SDK (>=1.25,<2, installed 1.26.0)
- **Component**: `src/architect/mcp_server.py`, `src/contract_engine/mcp_server.py`, `src/codebase_intelligence/mcp_server.py`, `src/run4/mcp_health.py`
- **Evidence**:
  All MCP patterns verified against official documentation:
  - `FastMCP` at `mcp.server.fastmcp` -- correct
  - `ClientSession` at `mcp` (top-level re-export) -- correct
  - `stdio_client` at `mcp.client.stdio` -- correct, yields `(read_stream, write_stream)` tuple
  - `@mcp.tool(name=...)` decorator -- correct
  - `session.initialize()` / `session.list_tools()` -- correct
  - `tools_response.tools[i].name` access pattern -- correct
- **Impact**: None -- this is a positive observation.

---

### FINDING-011: `transitions` AsyncMachine usage is correct and verified

- **Severity**: INFO
- **Library**: transitions (>=0.9.0, installed 0.9.3)
- **Component**: `src/super_orchestrator/state_machine.py`
- **Evidence**:
  All transitions patterns verified against official documentation and source:
  - `from transitions.extensions.asyncio import AsyncMachine` -- correct import
  - `AsyncMachine(queued=True, send_event=True, ignore_invalid_triggers=True)` -- all params verified
  - `State("name", on_enter=["callback"])` -- correct callback mechanism
  - `await model.trigger_name()` -- correct async trigger pattern
  - `model.state` -- correct default attribute for state access
- **Impact**: None -- this is a positive observation.

---

## Summary by Severity

| Severity | Count | Findings |
|----------|-------|----------|
| CRITICAL | 3 | FINDING-001, FINDING-002, FINDING-003 |
| HIGH | 1 | FINDING-004 |
| MEDIUM | 2 | FINDING-005, FINDING-006 |
| LOW | 2 | FINDING-007, FINDING-008 |
| INFO | 3 | FINDING-009, FINDING-010, FINDING-011 |

## Libraries NOT in Context7

The following libraries could not be fully verified via Context7 but were verified via PyPI / source inspection:

- **chromadb** (`==1.5.0`) -- Not queried (not directly used in M3 scope; used in codebase-intelligence service)
- **schemathesis** (`==4.10.1`) -- Not queried (not directly used in M3 scope; used in contract engine test generation)
- **tree-sitter** (`==0.25.2`) -- Not queried (not directly used in M3 scope; used in codebase-intelligence parsers)
- **networkx** (`==3.6.1`) -- Not queried (not directly used in M3 scope; used in codebase-intelligence graph)

---

## Impact on Milestone 3 Gate Condition

The **3 CRITICAL findings** (FINDING-001, -002, -003) directly block multiple M3 test cases:

| Finding | Blocked Tests |
|---------|---------------|
| FINDING-001 (missing `system_id`) | REQ-019 (parallel isolation), WIRE-015 (timeout enforcement) |
| FINDING-002 (invalid `line` field) | REQ-020 (fix pass invocation) |
| FINDING-003 (wrong attribute name) | REQ-016 (builder invocation), WIRE-015 (timeout), REQ-020 (fix pass) |

These must be resolved before M3 tests can pass.

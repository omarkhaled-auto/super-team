# Technical Audit Report — Milestone 3

**Auditor**: Technical Auditor (Audit-Team)
**Date**: 2026-02-19 (comprehensive re-audit)
**Scope**: All technical requirements from REQUIREMENTS.md — REQ-016 through REQ-020, WIRE-013 through WIRE-016, WIRE-021, SVC-018 through SVC-020, TEST-009, TEST-010, plus cross-cutting quality checks (secrets, error handling, type safety, conventions, deprecated APIs)
**Verdict**: **PASS — Milestone 3 gate condition is fully MET with minor non-blocking findings**

---

## Executive Summary

Milestone 3 is **fully implemented and tested**. All 15 gate-condition requirements have corresponding implementations with comprehensive test coverage:

- `src/run4/builder.py` (392 lines): Complete implementation of `BuilderResult`, `invoke_builder()`, `run_parallel_builders()`, `generate_builder_config()`, `parse_builder_state()`, `feed_violations_to_builder()`, and `write_fix_instructions()`.
- `tests/run4/test_m3_builder_invocation.py` (909 lines): 10 test classes covering REQ-016–020, WIRE-013–016, WIRE-021.
- `tests/run4/test_m3_config_generation.py` (559 lines): 5 test classes covering TEST-009, TEST-010, SVC-020.
- `src/run4/execution_backend.py` (194 lines): `AgentTeamsBackend`/`CLIBackend` abstraction with factory function.
- `src/integrator/fix_loop.py`: `ContractFixLoop.feed_violations_to_builder()` returns `BuilderResult` with proper `proc.kill()` + `await proc.wait()` cleanup.

The previous HIGH finding (FINDING-001 — `_dict_to_config()` not invoked in tests) has been **RESOLVED**. All config compatibility tests now import and call `_dict_to_config()` from `src.super_orchestrator.pipeline`. The remaining findings are MEDIUM or lower severity and do not block gate condition completion.

**Summary Statistics**:
- Total Findings: 16
- CRITICAL: 0
- HIGH: 1 (security gap)
- MEDIUM: 4
- LOW: 6
- INFO: 5

---

## FINDING-001: `_dict_to_config()` return type is `tuple[dict, set[str]]` not `tuple[AgentTeamConfig, set[str]]`

- **Severity**: MEDIUM
- **Requirement(s)**: REQ-018
- **Component**: `src/super_orchestrator/pipeline.py` lines 227-251, REQUIREMENTS.md line 114
- **Evidence**: REQUIREMENTS.md specifies: *"verify returns `tuple[AgentTeamConfig, set[str]]`"*. The actual `_dict_to_config()` implementation returns `tuple[dict[str, Any], set[str]]` — the first element is a plain `dict`, not an `AgentTeamConfig` dataclass/class. The tests correctly verify the actual return type (`isinstance(parsed_config, dict)`, `isinstance(unknown_keys, set)`), so this is a specification/implementation mismatch rather than a test gap.
  ```python
  # pipeline.py:227
  def _dict_to_config(raw: dict[str, Any]) -> tuple[dict[str, Any], set[str]]:
  ```
  The tests now do correctly call `_dict_to_config()` on generated configs (confirmed in 6 test methods across both test files), so the previous FINDING-001 about missing invocation is **RESOLVED**.
- **Impact**: Low — the REQUIREMENTS.md description mentions a type that doesn't match the implementation. The actual behavior is correct and well-tested.
- **Action**: Update REQUIREMENTS.md to reflect the actual return type `tuple[dict[str, Any], set[str]]`.

---

## FINDING-002: `_FILTERED_ENV_KEYS` missing `AWS_ACCESS_KEY_ID`

- **Severity**: HIGH
- **Requirement(s)**: SEC-001, WIRE-016
- **Component**: `src/run4/builder.py` line 31, `src/integrator/fix_loop.py` line 18, `src/super_orchestrator/pipeline.py` line 81
- **Evidence**: The constant filters three keys: `{"ANTHROPIC_API_KEY", "OPENAI_API_KEY", "AWS_SECRET_ACCESS_KEY"}`. However, `AWS_ACCESS_KEY_ID` is NOT filtered. AWS credentials consist of both the Access Key ID and Secret Access Key — filtering only the secret but leaking the key ID is an incomplete security posture. Additionally, other common secret keys are absent: `GOOGLE_API_KEY`, `AZURE_CLIENT_SECRET`, `DATABASE_URL`, `GITHUB_TOKEN`. Grep for `AWS_ACCESS_KEY_ID` across `src/` returns zero matches — the key is neither filtered nor mentioned.
- **Impact**: Subprocess builders receive `AWS_ACCESS_KEY_ID` in their environment, which combined with the filtered `AWS_SECRET_ACCESS_KEY` is not a direct credential leak, but the access key ID is still sensitive metadata. More importantly, any new secret env vars added to the system would also leak if not explicitly added to all three copies of `_FILTERED_ENV_KEYS`.
- **Action**: Add `AWS_ACCESS_KEY_ID` and consider using an allowlist approach (only pass explicitly safe keys) rather than a denylist approach (filter known-bad keys). See also FINDING-003 about deduplication.

---

## FINDING-003: No `proc.terminate()` before `proc.kill()` — Windows graceful shutdown risk

- **Severity**: MEDIUM
- **Requirement(s)**: Risk Analysis table in REQUIREMENTS.md
- **Component**: `src/run4/builder.py` lines 203-205, `src/integrator/fix_loop.py` lines 139-142
- **Evidence**: The Risk Analysis table in REQUIREMENTS.md states: *"Use `proc.terminate()` then `proc.kill()` with 5s grace"*. Both subprocess cleanup blocks use only:
  ```python
  proc.kill()
  await proc.wait()
  ```
  No `proc.terminate()` call with a grace period is implemented. `Grep("proc.terminate")` returns zero matches across all of `src/`.
- **Impact**: On Windows, `proc.kill()` sends `TerminateProcess` which cannot be caught by the child, potentially leaving orphaned grandchild processes, temp files, or corrupted state. A `proc.terminate()` call allows the subprocess a brief window to clean up.
- **Action**: Add `proc.terminate()` followed by `asyncio.wait_for(proc.wait(), timeout=5.0)` grace period, falling back to `proc.kill()` if the process doesn't exit within the grace period.

---

## FINDING-004: Duplicated `_FILTERED_ENV_KEYS` constant in three locations

- **Severity**: MEDIUM
- **Requirement(s)**: Cross-cutting: DRY principle, SEC-001
- **Component**: `src/run4/builder.py` line 31, `src/super_orchestrator/pipeline.py` line 81, `src/integrator/fix_loop.py` line 18
- **Evidence**: The exact same set `{"ANTHROPIC_API_KEY", "OPENAI_API_KEY", "AWS_SECRET_ACCESS_KEY"}` is independently defined in three separate files. If a new secret key needs filtering (per FINDING-002), it must be added in all three places, creating a high risk of inconsistency.
- **Impact**: Maintenance risk — inconsistent secret filtering across subprocess invocation paths. Adding `AWS_ACCESS_KEY_ID` per FINDING-002 requires three coordinated edits.
- **Action**: Move `_FILTERED_ENV_KEYS` and `_filtered_env()` to a shared module (e.g., `src/build3_shared/constants.py` or `src/build3_shared/security.py`) and import from all three locations.

---

## FINDING-005: Test Matrix entries X-03, X-04, X-05, X-06 and B2-series not mapped to actual test functions

- **Severity**: MEDIUM
- **Requirement(s)**: Test Matrix IDs X-03 through X-06 (all P0), B2-01 through B2-10
- **Component**: `tests/run4/`
- **Evidence**: The Test Matrix Mapping table in REQUIREMENTS.md specifies test function names that do not exist verbatim in the codebase:
  - X-03: `test_mcp_b1_to_b3_architect` — no counterpart in M3 tests
  - X-04: `test_subprocess_b3_to_b2` — covered by `test_builder_subprocess_invocation`
  - X-05: `test_state_json_contract` — covered by `test_state_json_parsing_cross_build`
  - X-06: `test_config_generation_compat` — covered by `test_config_generation_compatibility`
  - B2-01 through B2-10: Eight function names with zero matches in `tests/`

  The underlying functionality IS tested (with different names), but the traceability from matrix IDs to tests requires manual reasoning.
- **Impact**: Audit trail gap — matrix IDs cannot be mechanically traced to test functions. X-03 has no clear counterpart.
- **Action**: Add `pytest.mark` decorators or docstring references mapping matrix IDs to test functions. Clarify whether B2-xx entries are M2 or M3 owned.

---

## FINDING-006: `parse_builder_state()` return type annotation is bare `dict` instead of `dict[str, Any]`

- **Severity**: LOW
- **Requirement(s)**: Cross-cutting: Type safety
- **Component**: `src/run4/builder.py` line 61
- **Evidence**: The function signature is:
  ```python
  def parse_builder_state(output_dir: Path) -> dict:
  ```
  The internal implementation correctly annotates the return variable as `dict[str, Any]` (line 83), but the function signature uses bare `dict`. The project convention (seen in `mcp_health.py`, `state.py`) is inconsistent — some use bare `dict` and some use `dict[str, Any]`. Under `strict = true` mypy, bare `dict` is equivalent to `dict[Any, Any]`, which is less informative.

  Additional locations with bare `dict` return type:
  - `src/run4/mcp_health.py` line 101: `-> dict:`
  - `src/run4/state.py` line 199: `_to_dict(self) -> dict:`

  And bare `list[dict]` field annotations:
  - `src/run4/state.py` line 62: `fix_passes: list[dict]`
  - `src/run4/fix_pass.py` line 16: `-> list[dict]:`
  - `src/run4/execution_backend.py` lines 86-88: `list[dict]`
- **Impact**: Reduced IDE autocompletion and static type checking specificity across 8 annotations.
- **Action**: Update all bare `dict` and `list[dict]` annotations to `dict[str, Any]` and `list[dict[str, Any]]` for consistency with project typing standards.

---

## FINDING-007: `ExecutionBackend` uses informal abstract class pattern (no `ABC`)

- **Severity**: LOW
- **Requirement(s)**: Cross-cutting: Conventions
- **Component**: `src/run4/execution_backend.py` lines 42-54
- **Evidence**: `ExecutionBackend` raises `NotImplementedError` in `execute_wave()` instead of using `abc.ABC` and `@abstractmethod`. This allows instantiation of the base class (though it fails at runtime when `execute_wave()` is called). The `ABC` approach would catch the error at class definition time.
  ```python
  class ExecutionBackend:           # No ABC inheritance
      async def execute_wave(...):
          raise NotImplementedError  # Instead of @abstractmethod
  ```
- **Impact**: Low — both subclasses (`CLIBackend`, `AgentTeamsBackend`) correctly override `execute_wave()`. The pattern works but is less strict.
- **Action**: Consider `class ExecutionBackend(ABC)` with `@abstractmethod` for stronger enforcement.

---

## FINDING-008: `AgentTeamsBackend` test accesses private attributes directly

- **Severity**: LOW
- **Requirement(s)**: WIRE-021
- **Component**: `tests/run4/test_m3_builder_invocation.py` lines 880-893, `src/run4/execution_backend.py` lines 86-88
- **Evidence**: The WIRE-021 test (`test_agent_teams_positive_path`) verifies task lifecycle by accessing underscore-prefixed private attributes:
  ```python
  assert len(backend._task_creates) == 2     # line 880
  assert len(backend._task_updates) == 4     # line 885
  assert len(backend._send_messages) == 2    # line 891
  ```
  These internal tracking lists use bare `list[dict]` typing and are implementation details. If the `AgentTeamsBackend` tracking mechanism changes, tests break without any public API change.
- **Impact**: Test fragility — tightly coupled to internal implementation.
- **Action**: Consider exposing a public audit trail property or method (e.g., `backend.get_operation_log()`) rather than accessing private attributes.

---

## FINDING-009: `write_fix_instructions()` default parameter differs from REQUIREMENTS.md specification

- **Severity**: LOW
- **Requirement(s)**: REQ-020
- **Component**: `src/run4/builder.py` line 313
- **Evidence**: REQUIREMENTS.md specifies `priority_order: list[str] = ["P0", "P1", "P2"]`. The implementation uses:
  ```python
  priority_order: list[str] | None = None,
  # ... then inside body:
  if priority_order is None:
      priority_order = ["P0", "P1", "P2"]
  ```
  This is functionally equivalent and actually follows the Python best practice of avoiding mutable default arguments.
- **Impact**: None — behavior is identical, implementation is more Pythonic.
- **Action**: None required. Consider updating REQUIREMENTS.md to match the implementation pattern.

---

## FINDING-010: `BuilderResult` dataclass exists in two different modules with divergent schemas

- **Severity**: LOW
- **Requirement(s)**: TEST-009
- **Component**: `src/run4/builder.py` lines 34-53 vs `src/build3_shared/models.py`
- **Evidence**: Two distinct `BuilderResult` dataclasses exist:
  - `src/run4/builder.py`: 12 fields — `service_name`, `success`, `test_passed`, `test_total`, `convergence_ratio`, `total_cost`, `health`, `completed_phases`, `exit_code`, `stdout`, `stderr`, `duration_s` (matches M3 REQUIREMENTS.md exactly)
  - `src/build3_shared/models.py`: Different schema — `system_id`, `service_id`, `success`, `cost`, `error`, `output_dir`, `test_passed`, `test_total`, `convergence_ratio`, `artifacts`

  All M3 tests correctly import from `src.run4.builder`, and the `pipeline.py` module imports from `src.build3_shared.models`. No incorrect cross-imports were found.
- **Impact**: Potential developer confusion when choosing which `BuilderResult` to import.
- **Action**: Add module-level docstring clarification or consider a deprecation/consolidation plan.

---

## FINDING-011: `ContractFixLoop.__init__` uses bare `Any` for config parameter

- **Severity**: LOW
- **Requirement(s)**: Cross-cutting: Type safety
- **Component**: `src/integrator/fix_loop.py`
- **Evidence**: `ContractFixLoop.__init__(self, config: Any = None, ...)` uses `Any` for the config parameter. The function uses runtime `getattr` chains with no type safety:
  ```python
  self.timeout = getattr(getattr(config, "builder", None), "timeout", timeout)
  ```
- **Impact**: No static type checking for misconfigured config objects.
- **Action**: Replace `Any` with `SuperOrchestratorConfig | None` or a `Protocol` type.

---

## FINDING-012: SEC-001 environment filtering correctly implemented and tested

- **Severity**: INFO (positive finding)
- **Requirement(s)**: WIRE-016 (SEC-001 compliance)
- **Component**: `src/run4/builder.py` lines 31, 155-157; test at `test_m3_builder_invocation.py` lines 795-831
- **Evidence**: All subprocess invocation paths filter `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, and `AWS_SECRET_ACCESS_KEY` from the environment. The test `test_builder_environment_isolation` explicitly verifies filtered keys are absent while `PATH` is preserved. No hardcoded secrets or real credentials found anywhere in `src/` or `tests/` (test fixtures use clearly-fake values like `"sk-secret-key"` inside `patch.dict()`).
- **Impact**: Positive — well-implemented security control.
- **Action**: None required (see FINDING-002 for gap in key coverage).

---

## FINDING-013: Subprocess timeout pattern correctly implemented

- **Severity**: INFO (positive finding)
- **Requirement(s)**: WIRE-015
- **Component**: `src/run4/builder.py` lines 198-205, `src/integrator/fix_loop.py`
- **Evidence**: Both `invoke_builder()` and `ContractFixLoop.feed_violations_to_builder()` implement the timeout-kill-wait pattern correctly:
  ```python
  except asyncio.TimeoutError:
      logger.warning(...)
  finally:
      if proc is not None and proc.returncode is None:
          proc.kill()
          await proc.wait()
  ```
  Three tests validate this: `test_builder_timeout_enforcement`, `test_builder_timeout_enforcement_fix_loop`, and `test_builder_timeout_enforcement_with_timeout_s_5`. All verify `kill()` and `wait()` are called.
- **Impact**: Positive — prevents orphaned processes.
- **Action**: None required. See FINDING-003 for `terminate()` enhancement.

---

## FINDING-014: All required function signatures match REQUIREMENTS.md specification

- **Severity**: INFO (positive finding)
- **Requirement(s)**: REQ-016 through REQ-020, SVC-018 through SVC-020
- **Component**: `src/run4/builder.py`
- **Evidence**: Verification of all 7 required functions/classes:

  | Requirement | Function | Signature Match | Status |
  |-------------|----------|----------------|--------|
  | REQ-016 | `BuilderResult` dataclass | 12/12 fields present, types match | PASS |
  | REQ-016 | `invoke_builder(cwd, depth, timeout_s, env)` -> `BuilderResult` | Exact match | PASS |
  | REQ-019 | `run_parallel_builders(builder_configs, max_concurrent, timeout_s)` -> `list[BuilderResult]` | Exact match | PASS |
  | REQ-018/SVC-020 | `generate_builder_config(service_name, output_dir, depth, contracts, mcp_enabled)` -> `Path` | Exact match | PASS |
  | REQ-017 | `parse_builder_state(output_dir)` -> `dict` | Exact match | PASS |
  | REQ-020 | `feed_violations_to_builder(cwd, violations, timeout_s)` -> `BuilderResult` | Exact match | PASS |
  | REQ-020 | `write_fix_instructions(cwd, violations, priority_order)` -> `Path` | Match (FINDING-009) | PASS |

- **Impact**: Positive — complete API surface.
- **Action**: None required.

---

## FINDING-015: `_dict_to_config()` compatibility is now fully tested

- **Severity**: INFO (resolved finding)
- **Requirement(s)**: REQ-018, SVC-020
- **Component**: `tests/run4/test_m3_builder_invocation.py`, `tests/run4/test_m3_config_generation.py`
- **Evidence**: The previous audit found that `_dict_to_config()` was never invoked by tests. This has been **RESOLVED**. The function is now imported and called in 6 test methods across both test files:
  - `test_m3_builder_invocation.py`: `test_config_generation_compatibility` (line 256, 279), `test_config_with_contracts` (line 302, 320)
  - `test_m3_config_generation.py`: `test_config_yaml_all_depths` (line 413, 435), `test_config_roundtrip_preserves_fields` (line 503, 549)

  Each test verifies: (1) no exception raised, (2) return type is `tuple[dict, set]`, (3) known keys are in parsed config, (4) `service_name` appears in unknown keys set.
- **Impact**: Positive — full Build 2 compatibility verification.
- **Action**: None required.

---

## FINDING-016: Semaphore-gated parallel execution correctly implemented

- **Severity**: INFO (positive finding)
- **Requirement(s)**: REQ-019
- **Component**: `src/run4/builder.py` lines 227-252
- **Evidence**: `run_parallel_builders()` correctly uses `asyncio.Semaphore(max_concurrent)` with `async with semaphore:` inside `_run_one()`. The semaphore is created *inside* the function body (not at module level), avoiding event-loop issues per the project's documented design decision in `pipeline.py`. Two tests verify semaphore enforcement:
  - `test_parallel_builder_isolation`: 4 builders with max_concurrent=3, verifies `max_seen <= 3`
  - `test_semaphore_prevents_4th_concurrent`: 6 builders with max_concurrent=3, verifies `peak_concurrent <= 3`

  Cross-contamination is tested via unique marker files per builder directory.
- **Impact**: Positive — correctly prevents resource exhaustion.
- **Action**: None required.

---

## Cross-Cutting Technical Quality

| Area | Status | Details |
|------|--------|---------|
| Hardcoded secrets | **PASS** | No real secrets in source or tests. Test mocks use clearly-fake values inside `patch.dict()`. |
| Empty catch blocks | **PASS** | One narrow `except (ValueError, IndexError): pass` in `state.py:100` (finding ID parsing) — justified as it silently skips malformed finding IDs during auto-increment. All other exception handlers log warnings or re-raise. |
| Type safety (`Any` usage) | **MINOR** | `Any` used in 3 contexts: (1) `fix_loop.py` config param (FINDING-011, unjustified), (2) `builder.py` JSON dict values (justified — unstructured JSON), (3) `execution_backend.py` task dicts (justified). Bare `dict` used in 8 return/field annotations (FINDING-006). |
| Naming conventions | **PASS** | Consistent `snake_case` functions, `PascalCase` classes, `_UPPER_CASE` module constants, `FINDING-NNN` pattern throughout all M3 files. |
| Deprecated API usage | **PASS** | No deprecated APIs detected. Modern Python 3.11+ patterns: `from __future__ import annotations`, `X | None` union syntax, `list[str]` generic syntax. |
| Error handling | **PASS** | Proper `try/finally` in subprocess management. `json.JSONDecodeError` and `OSError` handled in state parsing. Timeout handling with cleanup. No swallowed exceptions in critical paths. |
| Subprocess security | **PASS** | Environment filtering implemented in all 3 subprocess paths and tested via WIRE-016. See FINDING-002 for coverage gap. |
| Import conventions | **PASS** | All files use `from __future__ import annotations`. Import order follows: stdlib -> third-party -> local. Module-level `logger = logging.getLogger(__name__)`. |
| Docstring conventions | **PASS** | Google-style docstrings with Args/Returns/Raises sections. Module-level docstrings document milestone requirements. |
| Atomic file operations | **PASS** | `state.py` uses write-to-tmp + `os.replace()` pattern. `builder.py` creates directories with `mkdir(parents=True, exist_ok=True)`. |

---

## Gate Condition Assessment

**REQUIREMENTS.md Gate**: *"Milestone 3 is COMPLETE when: All REQ-016 through REQ-020, WIRE-013 through WIRE-016, WIRE-021, TEST-009, TEST-010 tests pass."*

| Requirement | Status | Test Coverage | Findings |
|-------------|--------|---------------|----------|
| REQ-016 | **PASS** | `test_builder_subprocess_invocation`, `test_builder_result_fields` | -- |
| REQ-017 | **PASS** | `test_state_json_parsing_cross_build`, `test_missing_state_json_returns_defaults`, `test_corrupt_state_json` | -- |
| REQ-018 | **PASS** | `test_config_generation_compatibility` (4 depths + `_dict_to_config`), `test_config_with_contracts` (+ `_dict_to_config`), `test_config_returns_path` | FINDING-001 (spec/impl type mismatch, non-blocking) |
| REQ-019 | **PASS** | `test_parallel_builder_isolation`, `test_semaphore_prevents_4th_concurrent` | -- |
| REQ-020 | **PASS** | `test_fix_pass_invocation`, `test_write_fix_instructions_priority_format`, `test_write_fix_instructions_returns_path`, `test_fix_loop_returns_builder_result` | -- |
| WIRE-013 | **PASS** | `test_agent_teams_fallback_cli_unavailable`, `test_agent_teams_disabled_returns_cli_backend` | -- |
| WIRE-014 | **PASS** | `test_agent_teams_hard_failure_no_fallback`, `test_fallback_to_cli_default_is_true` | -- |
| WIRE-015 | **PASS** | `test_builder_timeout_enforcement`, `test_builder_timeout_enforcement_fix_loop`, `test_builder_timeout_enforcement_with_timeout_s_5` | FINDING-003 (no terminate, non-blocking) |
| WIRE-016 | **PASS** | `test_builder_environment_isolation` | -- |
| WIRE-021 | **PASS** | `test_agent_teams_positive_path`, `test_cli_backend_execute_wave` | -- |
| TEST-009 | **PASS** | `test_builder_result_dataclass_mapping`, `test_builder_result_from_state_json_roundtrip`, `test_builder_result_defaults_on_missing_state`, `test_builder_result_partial_state_json`, `test_parse_builder_state_field_types` | -- |
| TEST-010 | **PASS** | `test_parallel_builder_result_aggregation`, `test_aggregate_cost_and_stats` | -- |
| SVC-018 | **PASS** | `run_parallel_builders()` with subprocess invocation | -- |
| SVC-019 | **PASS** | `feed_violations_to_builder()` + `ContractFixLoop.feed_violations_to_builder()` | -- |
| SVC-020 | **PASS** | `test_config_yaml_all_depths` (4 parametrized + `_dict_to_config`), `test_config_yaml_with_contracts`, `test_config_yaml_mcp_disabled`, `test_config_roundtrip_preserves_fields` (+ `_dict_to_config`) | -- |

**Result: 15 of 15 gate-condition requirements are PASS. Milestone 3 gate condition is fully MET.**

---

## Severity Summary

| Severity | Count | Findings |
|----------|-------|----------|
| CRITICAL | 0 | -- |
| HIGH | 1 | FINDING-002 |
| MEDIUM | 4 | FINDING-001, FINDING-003, FINDING-004, FINDING-005 |
| LOW | 6 | FINDING-006, FINDING-007, FINDING-008, FINDING-009, FINDING-010, FINDING-011 |
| INFO | 5 | FINDING-012, FINDING-013, FINDING-014, FINDING-015, FINDING-016 |

---

## Recommendations (Priority Order)

1. **[HIGH] Add `AWS_ACCESS_KEY_ID` to `_FILTERED_ENV_KEYS`** — Complete the AWS credential filtering for SEC-001 compliance (FINDING-002)
2. **[MEDIUM] Update REQUIREMENTS.md return type spec** — Change `tuple[AgentTeamConfig, set[str]]` to `tuple[dict[str, Any], set[str]]` to match implementation (FINDING-001)
3. **[MEDIUM] Add `proc.terminate()` graceful shutdown** — Before `proc.kill()` in both `builder.py` and `fix_loop.py` per Risk Analysis table (FINDING-003)
4. **[MEDIUM] Consolidate `_FILTERED_ENV_KEYS`** — Move to a shared module to avoid 3-location duplication (FINDING-004)
5. **[MEDIUM] Add test matrix ID traceability** — Map X-03 through X-06 and B2-01 through B2-10 to actual test functions (FINDING-005)
6. **[LOW] Fix bare `dict` type annotations** — Use `dict[str, Any]` in 8 locations across 4 files (FINDING-006)
7. **[LOW] Use `ABC` for `ExecutionBackend`** — Stronger subclass enforcement (FINDING-007)
8. **[LOW] Add public audit trail API to `AgentTeamsBackend`** — Avoid test dependency on private attributes (FINDING-008)
9. **[LOW] Consolidate `BuilderResult` dataclasses** — Two divergent schemas in `run4/builder.py` and `build3_shared/models.py` (FINDING-010)

---

## Changes Since Previous Audit (2025-07-14)

| Previous Finding | Previous Severity | Current Status | Notes |
|------------------|-------------------|----------------|-------|
| FINDING-001 (`_dict_to_config` not invoked) | HIGH | **RESOLVED** | Now invoked in 6 test methods across 2 test files (FINDING-015) |
| FINDING-002 (no `proc.terminate`) | MEDIUM | **OPEN** | Carried forward as FINDING-003 |
| FINDING-003 (duplicated constant) | MEDIUM | **OPEN** | Carried forward as FINDING-004 |
| FINDING-004 (X-03 through X-06 naming) | MEDIUM | **OPEN** | Merged with B2-series as FINDING-005 |
| FINDING-005 (B2-series missing) | MEDIUM | **OPEN** | Merged into FINDING-005 |
| FINDING-006 (`Any` in fix_loop config) | MEDIUM | **OPEN** | Carried forward as FINDING-011 (downgraded to LOW) |
| FINDING-007 (priority_order default) | LOW | **OPEN** | Carried forward as FINDING-009 |
| FINDING-008 (BuilderResult divergence) | LOW | **OPEN** | Carried forward as FINDING-010 |
| FINDING-009 (`Any` usage in builder.py) | LOW | **OPEN** | Subsumed into FINDING-006 (bare `dict` annotations) |
| FINDING-010 (ExecutionBackend no ABC) | LOW | **OPEN** | Carried forward as FINDING-007 |
| FINDING-011 (untyped `list[dict]`) | LOW | **OPEN** | Merged into FINDING-006 and FINDING-008 |
| FINDING-012 (SEC-001 positive) | INFO | **CONFIRMED** | Carried forward as FINDING-012 |
| FINDING-013 (timeout positive) | INFO | **CONFIRMED** | Carried forward as FINDING-013 |
| FINDING-014 (signatures positive) | INFO | **CONFIRMED** | Carried forward as FINDING-014 |
| NEW: FINDING-002 (AWS_ACCESS_KEY_ID) | -- | **NEW (HIGH)** | Newly identified security gap |
| NEW: FINDING-001 (return type mismatch) | -- | **NEW (MEDIUM)** | Spec/impl type discrepancy in REQUIREMENTS.md |

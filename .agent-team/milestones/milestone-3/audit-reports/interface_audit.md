# Interface Audit Report -- Milestone 3

**Auditor**: Interface Auditor (Automated)
**Date**: 2026-02-19
**Scope**: All WIRE-xxx, SVC-xxx, and INT-xxx items from Milestone 3 REQUIREMENTS.md
**Status**: **FAIL** -- 12 findings (3 CRITICAL, 4 HIGH, 3 MEDIUM, 1 LOW, 1 INFO)

---

## Summary

Milestone 3 requires subprocess integration between Build 3 (Orchestration Layer) and Build 2 (Builder Fleet). The audit reveals that **the majority of M3 deliverables do not yet exist**: the required test files are missing, the `src/run4/builder.py` remains a minimal stub, and the `_dict_to_config()` function referenced in SVC-020 does not exist anywhere in the codebase. Several runtime wiring bugs were also found in the existing `pipeline.py` implementation.

| Category | Total | CRITICAL | HIGH | MEDIUM | LOW | INFO |
|----------|-------|----------|------|--------|-----|------|
| WIRE-xxx | 5     | 1        | 2    | 1      | 0   | 1    |
| SVC-xxx  | 3     | 1        | 1    | 1      | 0   | 0    |
| INT-xxx  | 1     | 0        | 0    | 1      | 0   | 0    |
| ORPHAN   | 3     | 1        | 1    | 0      | 1   | 0    |

---

## WIRE-xxx Findings

### FINDING-001: WIRE-013 test file missing -- Agent Teams fallback test unimplemented
- **Severity**: HIGH
- **Requirement**: WIRE-013 -- `test_agent_teams_fallback_cli_unavailable`
- **Source**: `tests/run4/test_m3_builder_invocation.py` (DOES NOT EXIST)
- **Target**: `src/super_orchestrator/pipeline.py` (lines 646-663 -- `create_execution_backend` fallback)
- **Evidence**: `Glob("tests/run4/test_m3_*")` returns zero matches. The test file `test_m3_builder_invocation.py` specified in REQUIREMENTS.md has not been created.
- **Impact**: WIRE-013 verification (Agent Teams fallback when CLI unavailable) cannot be validated. The production code at `pipeline.py:646-663` does attempt `create_execution_backend()` with an `ImportError` fallback, but there is no test proving the fallback path works correctly.
- **Action**: Create `tests/run4/test_m3_builder_invocation.py` with `test_agent_teams_fallback_cli_unavailable` test.

### FINDING-002: WIRE-014 test file missing -- Agent Teams hard failure test unimplemented
- **Severity**: HIGH
- **Requirement**: WIRE-014 -- `test_agent_teams_hard_failure_no_fallback`
- **Source**: `tests/run4/test_m3_builder_invocation.py` (DOES NOT EXIST)
- **Target**: Pipeline should raise `RuntimeError` when `fallback_to_cli=False` and CLI unavailable
- **Evidence**: The test file does not exist. Additionally, there is no `fallback_to_cli` configuration field in `SuperOrchestratorConfig`, `BuilderConfig`, or `Run4Config`. The pipeline code at `pipeline.py:646-663` always falls back silently on `ImportError` -- it never raises `RuntimeError`.
- **Impact**: The hard-failure path described in WIRE-014 has no implementation and no test. The `fallback_to_cli=False` configuration option does not exist.
- **Action**: Add `fallback_to_cli` field to config; implement conditional `RuntimeError` raise; create test.

### FINDING-003: WIRE-015 -- Builder timeout enforcement test missing but production code exists
- **Severity**: MEDIUM
- **Requirement**: WIRE-015 -- `test_builder_timeout_enforcement`
- **Source**: `tests/run4/test_m3_builder_invocation.py` (DOES NOT EXIST)
- **Target**: `src/super_orchestrator/pipeline.py` (lines 680-708)
- **Evidence**: The production code at `pipeline.py:680-708` correctly implements `asyncio.wait_for(proc.wait(), timeout=config.builder.timeout)` with a `finally` block that calls `proc.kill()` + `await proc.wait()`. However, there is no test validating this behavior.
- **Impact**: Timeout enforcement logic exists but is unverified by M3 tests. The `Run4Config.builder_timeout_s` field (line 43) is correctly defined.
- **Action**: Create test with `builder_timeout_s=5` that validates the kill+wait cleanup path.

### FINDING-004: WIRE-016 -- Builder environment isolation partially implemented
- **Severity**: INFO
- **Requirement**: WIRE-016 -- `test_builder_environment_isolation`
- **Source**: `src/super_orchestrator/pipeline.py` (line 678, `env=_filtered_env()`)
- **Target**: SEC-001 compliance -- ANTHROPIC_API_KEY not passed to builder subprocesses
- **Evidence**: The `_filtered_env()` function at `pipeline.py:82-84` correctly strips `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, and `AWS_SECRET_ACCESS_KEY` from the environment. The `src/integrator/fix_loop.py:119` also correctly implements the same filtering. However, the pipeline at line 646-650 passes `config=builder_config` dict to `create_execution_backend()` which could leak env through in-process execution.
- **Impact**: SEC-001 is satisfied for the subprocess path. In-process path (when `agent_team` is importable) may inherit the full process environment. No test exists to validate either path.
- **Action**: Create `test_builder_environment_isolation` test; verify in-process backend also respects env filtering.

### FINDING-005: WIRE-021 -- Agent Teams positive-path test missing and AgentTeamsBackend not found
- **Severity**: CRITICAL
- **Requirement**: WIRE-021 -- `test_agent_teams_positive_path`
- **Source**: `tests/run4/test_m3_builder_invocation.py` (DOES NOT EXIST)
- **Target**: `AgentTeamsBackend.execute_wave()` -- class does not exist in codebase
- **Evidence**: `Grep("AgentTeamsBackend", src/)` returns zero matches. The WIRE-021 requirement specifies testing `AgentTeamsBackend.execute_wave()` with `TaskCreate`, `TaskUpdate`, `SendMessage` verification. Neither the backend class nor the test exists.
- **Impact**: The Agent Teams positive-path integration cannot be tested or verified. This is a blocking requirement for M3 gate completion.
- **Action**: Implement `AgentTeamsBackend` class or clarify if it is provided by the external `agent_team` package; create test.

---

## SVC-xxx Findings

### FINDING-006: SVC-018 -- run_parallel_builders exists in pipeline.py but not in run4/builder.py as specified
- **Severity**: MEDIUM
- **Requirement**: SVC-018 -- `pipeline.run_parallel_builders` -> `python -m agent_team --cwd {dir} --depth {depth}`
- **Source**: `src/super_orchestrator/pipeline.py` (lines 535-631)
- **Target**: CLI subprocess `python -m agent_team --cwd {dir} --depth {depth}`
- **Evidence**: The `run_parallel_builders` function exists in `pipeline.py` and correctly:
  - Uses `asyncio.create_subprocess_exec` with `python -m agent_team --cwd ... --depth ...` (line 668-676)
  - Uses `asyncio.Semaphore(config.builder.max_concurrent)` (line 578)
  - Parses `STATE.json` via `_parse_builder_result()` (line 721)
  - Has `try/finally` with `proc.kill()` + `await proc.wait()` (lines 705-708)

  However, REQUIREMENTS.md specifies this function should be in `src/run4/builder.py` as an async function with `BuilderResult` dataclass. The `run4/builder.py` only contains the `parse_builder_state()` stub -- none of the 6 functions specified in REQUIREMENTS.md (Section "Source File Updates") have been added to it: `invoke_builder()`, `run_parallel_builders()`, `generate_builder_config()`, `feed_violations_to_builder()`, `write_fix_instructions()`, or `BuilderResult` dataclass.
- **Impact**: SVC-018 is functionally implemented in pipeline.py but NOT in the location specified by requirements. The `src/run4/builder.py` functions are not wired and cannot be tested.
- **Action**: Either update requirements to point to `pipeline.py` implementation, or expand `run4/builder.py` as specified.

### FINDING-007: SVC-019 -- feed_violations_to_builder return type mismatch causes runtime AttributeError
- **Severity**: CRITICAL
- **Requirement**: SVC-019 -- `fix_loop.feed_violations_to_builder` -> `python -m agent_team --cwd {dir} --depth quick`
- **Source**: `src/integrator/fix_loop.py` -- `ContractFixLoop.feed_violations_to_builder()` (line 65-154)
- **Target**: `src/super_orchestrator/pipeline.py` -- `run_fix_pass()` (line 1166-1171)
- **Evidence**:
  - `fix_loop.py:70` declares return type `float` and returns a bare `float` cost value at line 154.
  - `pipeline.py:1171` calls `result.get("cost", 0.0)` which expects a `dict` with a `"cost"` key.
  - **`float` has no `.get()` method** -- this will raise `AttributeError: 'float' object has no attribute 'get'` at runtime.
- **Impact**: **RUNTIME CRASH** -- Every fix pass invocation will fail with an `AttributeError`. The fix loop is broken.
- **Action**: Either change `pipeline.py:1171` to `total_fix_cost += result` (since result is already a float), or change `fix_loop.py` to return `{"cost": cost}` dict.

### FINDING-008: SVC-020 -- `_dict_to_config()` does not exist anywhere in the codebase
- **Severity**: HIGH
- **Requirement**: SVC-020 -- `pipeline.generate_builder_config` -> Build 2 `config.yaml` loadable by `_dict_to_config()`
- **Source**: `src/super_orchestrator/pipeline.py` -- `generate_builder_config()` (lines 176-209)
- **Target**: Build 2's `_dict_to_config()` function
- **Evidence**: `Grep("_dict_to_config", **/*.py)` across the entire project returns zero matches. The function is not defined in any module. The Super Orchestrator config uses `_pick()` (pipeline.py config.py:94) and `Run4Config.from_yaml()` (run4/config.py:72) for dict-to-config conversion, neither of which is named `_dict_to_config`.

  Furthermore, `generate_builder_config()` in `pipeline.py` returns a plain `dict` (not a config.yaml file path as REQUIREMENTS.md specifies). The test requirement `test_config_yaml_all_depths` expects generating a YAML file that roundtrips through `_dict_to_config()`, but neither the YAML generation nor the target function exists.
- **Impact**: SVC-020 cannot be verified. Config generation compatibility with Build 2 is unvalidated because the target function does not exist.
- **Action**: Clarify where Build 2's `_dict_to_config()` is located; implement the `generate_builder_config()` that writes YAML as specified.

---

## INT-xxx Findings

### FINDING-009: INT-006 -- parse_builder_state() reads wrong STATE.json field names
- **Severity**: MEDIUM
- **Requirement**: INT-006 -- `parse_builder_state(output_dir)` reads `.agent-team/STATE.json` and extracts summary dict
- **Source**: `src/run4/builder.py` (lines 15-58)
- **Target**: STATE.JSON Cross-Build Contract (REQUIREMENTS.md lines 141-169)
- **Evidence**: The STATE.JSON contract specifies these fields:
  ```json
  {"summary": {"success": true, "test_passed": 42, "test_total": 50, "convergence_ratio": 0.85}}
  ```
  But `parse_builder_state()` reads entirely different fields:
  - Line 42: `data.get("completion_ratio", 0.0) >= 1.0` -- field `completion_ratio` is not in the contract
  - Line 43: `data.get("requirements_checked", 0)` -- field `requirements_checked` is not in the contract
  - Line 44: `data.get("requirements_total", 0)` -- field `requirements_total` is not in the contract

  The contract specifies `summary.success`, `summary.test_passed`, `summary.test_total`, `summary.convergence_ratio`, but the implementation reads top-level keys with entirely different names and derives `success` via a threshold comparison instead of reading the boolean directly.

  Compare with `pipeline.py:731-739` (`_parse_builder_result`) which CORRECTLY reads `summary.success`, `summary.test_passed`, etc.
- **Impact**: `parse_builder_state()` will return incorrect data for any STATE.JSON conforming to the cross-build contract. The function in `run4/builder.py` is incompatible with both the specification AND the actual pipeline implementation.
- **Action**: Update `parse_builder_state()` to read `data["summary"]["success"]`, `data["summary"]["test_passed"]`, `data["summary"]["test_total"]`, `data["summary"]["convergence_ratio"]` per the contract.

---

## ORPHAN Detection Findings

### FINDING-010: Orphaned parse_builder_state() -- defined but never imported
- **Severity**: HIGH
- **Requirement**: N/A (Orphan detection)
- **Source**: `src/run4/builder.py` -- `parse_builder_state()`
- **Target**: No consumer found
- **Evidence**: `Grep("parse_builder_state", **/*.py)` returns only the definition site (`builder.py:15`). No file imports or calls this function. The pipeline uses its own `_parse_builder_result()` (pipeline.py:724) instead. The conftest.py and test files also do not reference it.
- **Impact**: Dead code. The function was created as an M1 stub for M3 expansion but was never wired into any consumer. The pipeline has its own independent implementation that reads the correct fields.
- **Action**: Either wire `parse_builder_state()` into the pipeline (replacing `_parse_builder_result()`), or remove it and update requirements to reference `_parse_builder_result()`.

### FINDING-011: Missing test files -- entire M3 test suite absent
- **Severity**: CRITICAL
- **Requirement**: Multiple (REQ-016 through REQ-020, WIRE-013 through WIRE-016, WIRE-021, SVC-020, TEST-009, TEST-010)
- **Source**: `tests/run4/test_m3_builder_invocation.py` (DOES NOT EXIST)
- **Source**: `tests/run4/test_m3_config_generation.py` (DOES NOT EXIST)
- **Target**: All M3 requirements
- **Evidence**: `Glob("tests/run4/test_m3_*")` returns zero files. Both test files specified in REQUIREMENTS.md are missing:
  - `test_m3_builder_invocation.py` (~350 LOC, 10 tests)
  - `test_m3_config_generation.py` (~200 LOC, 5 tests)

  The test matrix entries (B2-01 through B2-10, X-03 through X-06) have no implementations.
- **Impact**: **M3 gate condition CANNOT be met.** Zero of the 15 required tests exist. Milestone 3 is entirely unimplemented from a test perspective.
- **Action**: Create both test files with all specified test functions.

### FINDING-012: run4/builder.py BuilderResult dataclass not implemented
- **Severity**: LOW
- **Requirement**: REQUIREMENTS.md Source File Updates section
- **Source**: `src/run4/builder.py` -- missing `BuilderResult` dataclass
- **Target**: `src/build3_shared/models.py` -- contains `BuilderResult` with different field set
- **Evidence**: REQUIREMENTS.md specifies a `BuilderResult` dataclass in `src/run4/builder.py` with fields: `service_name`, `success`, `test_passed`, `test_total`, `convergence_ratio`, `total_cost`, `health`, `completed_phases`, `exit_code`, `stdout`, `stderr`, `duration_s`.

  The existing `BuilderResult` in `src/build3_shared/models.py` has a different schema: `system_id`, `service_id` (not `service_name`), `success`, `cost` (not `total_cost`), `error`, `output_dir`, `test_passed`, `test_total`, `convergence_ratio`, `artifacts`. Missing: `health`, `completed_phases`, `exit_code`, `stdout`, `stderr`, `duration_s`.

  The requirements expect the `run4` version to be a superset carrying subprocess-specific fields. It has not been implemented.
- **Impact**: Tests in `test_m3_builder_invocation.py` that reference the `run4` `BuilderResult` will fail. The existing `build3_shared.models.BuilderResult` lacks subprocess-oriented fields.
- **Action**: Implement the `run4` `BuilderResult` as specified, or update requirements to use `build3_shared.models.BuilderResult` with extended fields.

---

## Additional Wiring Observations

### PipelineState.builder_results Type Mismatch

`src/super_orchestrator/state.py:36` declares `builder_results: list[dict]` (a **list**), but `pipeline.py:596` uses it as `state.builder_results[r.service_id] = ...` (dict-style **key indexing**). Assigning to a list by string key will raise `TypeError` at runtime. This affects SVC-018's parallel builder result aggregation.

### IntegrationConfig Missing `compose_timeout` Field

`pipeline.py:853` accesses `config.integration.compose_timeout`, but `IntegrationConfig` in `config.py` only defines `timeout` (not `compose_timeout`). This will raise `AttributeError` at runtime during the integration phase. While not directly an M3 requirement, it blocks the full pipeline path that M3's builders feed into.

### fix_loop Return Type vs Pipeline Expectation

As detailed in FINDING-007, `fix_loop.feed_violations_to_builder()` returns `float` but `pipeline.py` calls `.get("cost")` on the result, expecting `dict`. This is a confirmed runtime crash.

---

## Verification Matrix

| Req ID   | Status     | Reason |
|----------|------------|--------|
| WIRE-013 | **FAIL**   | Test file missing; production code has fallback but untested |
| WIRE-014 | **FAIL**   | Test file missing; `fallback_to_cli` config field does not exist |
| WIRE-015 | **FAIL**   | Test file missing; production timeout code exists but unverified |
| WIRE-016 | **PARTIAL**| Production `_filtered_env()` correct; test missing; in-process path unprotected |
| WIRE-021 | **FAIL**   | Test file missing; `AgentTeamsBackend` class does not exist |
| SVC-018  | **PARTIAL**| Implemented in `pipeline.py` (not `run4/builder.py` as spec'd); state type mismatch |
| SVC-019  | **FAIL**   | Return type mismatch causes runtime `AttributeError` |
| SVC-020  | **FAIL**   | `_dict_to_config()` does not exist; config YAML generation not implemented |
| INT-006  | **FAIL**   | `parse_builder_state()` reads wrong field names from STATE.JSON |

---

## Gate Assessment

**Milestone 3 Gate: NOT MET**

- 0/5 WIRE tests exist
- 0/3 SVC wirings fully verified
- 1 confirmed runtime crash (FINDING-007)
- 1 state type mismatch (builder_results list vs dict usage)
- 2 missing test files (0 of ~550 LOC written)
- `_dict_to_config()` target function absent from codebase
- `AgentTeamsBackend` class absent from codebase
- `parse_builder_state()` incompatible with STATE.JSON contract

**Blocking items before M3 can pass:**
1. Create `test_m3_builder_invocation.py` with all 10 tests
2. Create `test_m3_config_generation.py` with all 5 tests
3. Fix `feed_violations_to_builder` return type mismatch (CRITICAL)
4. Fix `parse_builder_state()` field names to match STATE.JSON contract
5. Resolve `_dict_to_config()` dependency or update requirement
6. Implement or locate `AgentTeamsBackend` class
7. Expand `run4/builder.py` with specified functions or update requirements

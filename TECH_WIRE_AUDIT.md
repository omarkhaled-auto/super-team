# TECH + WIRE Requirements Audit Report

**Auditor:** tech-wire-auditor
**Date:** 2026-02-17
**Scope:** TECH-001 through TECH-032 (32 items) + WIRE-001 through WIRE-022 (22 items) = 54 items
**Scoring:** PASS = 5 pts, PARTIAL = 2 pts, FAIL = 0 pts

---

## Summary

| Category | Total | PASS | PARTIAL | FAIL | Points | Max |
|----------|-------|------|---------|------|--------|-----|
| TECH     | 32    | 25   | 5       | 2    | 135    | 160 |
| WIRE     | 22    | 18   | 3       | 1    | 96     | 110 |
| **TOTAL**| **54**| **43**| **8** | **3**| **231**| **270** |

**Overall Score: 231 / 270 (85.6%)**

---

## TECH Requirements (32 items)

| ID | Status | Evidence (file:line) | Issue (if not PASS) |
|----|--------|---------------------|---------------------|
| TECH-001 | PASS | `src/build3_shared/utils.py:7` uses `from pathlib import Path`; `state.py:8`, `pipeline.py:34`, `constants.py:141-142` all use `Path`. All file path operations use pathlib throughout. | |
| TECH-002 | PASS | `src/build3_shared/utils.py:22` `encoding="utf-8"` in write; `:48` in read. `state.py` delegates to `atomic_write_json` which specifies encoding. `pipeline.py:225` `read_text(encoding="utf-8")`, `:329` same. | |
| TECH-003 | PASS | `src/build3_shared/models.py:10` `class ServiceStatus(str, Enum)`, `:21` `class QualityLevel(str, Enum)`, `:29` `class GateVerdict(str, Enum)`. All three enums use `(str, Enum)`. | |
| TECH-004 | PASS | `src/build3_shared/utils.py:20-26` writes `.tmp` then `os.replace()`. `src/super_orchestrator/state.py:81` `save()` calls `atomic_write_json()`. | |
| TECH-005 | PASS | `src/super_orchestrator/state_machine.py:11` `from transitions.extensions.asyncio import AsyncMachine`. Factory at `:152` uses `AsyncMachine(...)`. | |
| TECH-006 | PASS | `src/super_orchestrator/shutdown.py:67-78` checks `sys.platform == "win32"` for `signal.signal`, else tries `loop.add_signal_handler` with `except RuntimeError` fallback. Reentrancy guard at `:82-83`. | |
| TECH-007 | PASS | `src/build3_shared/models.py:42` `field(default_factory=dict)`, `:64` `field(default_factory=list)`, `:99` `field(default_factory=list)`, `:100` `field(default_factory=list)`, `:110` `field(default_factory=dict)`, `:130` `field(default_factory=list)`. `state.py:27-46` all mutable defaults use `field(default_factory=...)`. | |
| TECH-008 | PASS | `src/integrator/docker_orchestrator.py:35-36` uses `"docker", "compose"` (v2 syntax, space not hyphen). | |
| TECH-009 | PASS | `src/integrator/docker_orchestrator.py:43-44` `stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE`. Both captured and decoded at `:48-51`. | |
| TECH-010 | PASS | `src/integrator/traefik_config.py:42` uses backtick syntax for PathPrefix: `` PathPrefix(`{path_prefix}`) ``. | |
| TECH-011 | PASS | `src/integrator/schemathesis_runner.py:177` `schemathesis.openapi.from_url(openapi_url, base_url=base_url)` for live; `:179` `schemathesis.openapi.from_path(openapi_url, base_url=base_url)` for static. | |
| TECH-012 | FAIL | `src/integrator/schemathesis_runner.py` -- The code does NOT catch `schemathesis.failures.FailureGroup`. It does not import `FailureGroup` anywhere. The `_run_via_test_runner` method (line 331+) uses raw httpx requests instead of the schemathesis programmatic API (`get_all_operations`, `make_case`, `validate_response`). No call to `case.validate_response()` exists. | PRD requires catching `schemathesis.failures.FailureGroup` explicitly; code bypasses schemathesis test API entirely and uses raw HTTP requests instead. |
| TECH-013 | PARTIAL | `src/integrator/pact_manager.py:157` `Verifier(provider_name)` correct; `:158` `verifier.add_transport(url=provider_url)` correct; `:172` `await asyncio.to_thread(verifier.verify)` correct. | Missing `verifier.state_handler()` call. PRD TECH-013 says "use `state_handler()` (not `set_state_handler()`)". No state_handler is ever configured on the verifier. |
| TECH-014 | PARTIAL | Cross-service tests use `httpx.AsyncClient(timeout=30.0)` at `cross_service_test_runner.py:167`. `boundary_tester.py:60` `timeout: float = 30.0`. `data_flow_tracer.py:35` `_timeout = 30.0`. However, `service_discovery.py` uses `httpx.AsyncClient(timeout=5.0)` for health checks, not 30.0. | `service_discovery.py` uses timeout=5.0 instead of 30.0. While health checks may warrant a shorter timeout, the PRD says "All async methods must use httpx.AsyncClient... with timeout=30.0". |
| TECH-014a | PASS | `src/integrator/schemathesis_runner.py:101-106` wraps sync calls in `asyncio.to_thread`. `pact_manager.py:172` `await asyncio.to_thread(verifier.verify)`. Both blocking libraries are wrapped. | |
| TECH-015 | PASS | `src/integrator/cross_service_test_generator.py` uses `sorted()` for deterministic ordering throughout. Chain links sorted, flows sorted by path length descending. | |
| TECH-016 | PASS | `src/integrator/cross_service_test_runner.py` `_TEMPLATE_VAR_PATTERN = re.compile(r"\{step_(\d+)_response\.([^}]+)\}")` at module level. Template variables `{step_N_response.field_name}` resolved at runtime in `_resolve_template_variables`. | |
| TECH-017 | PASS | `src/integrator/cross_service_test_runner.py:167-170` `httpx.AsyncClient(timeout=self._timeout, follow_redirects=True)` where `_timeout=30.0` set at `:40`. | |
| TECH-018 | PASS | `src/quality_gate/security_scanner.py` -- all 30+ regex patterns compiled at module level with `re.compile(...)`. `observability_checker.py` and `docker_security.py` also compile at module level. `adversarial_patterns.py` compiles all patterns at module level. | |
| TECH-019 | PASS | `src/quality_gate/security_scanner.py` `EXCLUDED_DIRS` includes `node_modules`, `.venv`, `venv`, `__pycache__`, `.git`, `dist`, `build`. Filtering via `if any(part in EXCLUDED_DIRS for part in path.parts): continue`. | |
| TECH-020 | PASS | `src/quality_gate/security_scanner.py` `_NOSEC_PATTERN` supports `nosec`, `noqa` inline suppression. Lines matching are skipped. | |
| TECH-021 | PASS | `src/quality_gate/layer3_system_level.py` `MAX_VIOLATIONS_PER_CATEGORY = 200`. Violations capped per category at line where `violations = violations[:MAX_VIOLATIONS_PER_CATEGORY]`. | |
| TECH-022 | PASS | `src/quality_gate/adversarial_patterns.py` -- purely static regex-based detection. No MCP imports, no Build 1 dependency. `layer4_adversarial.py` wraps it and verdict is always PASSED. | |
| TECH-023 | PASS | `src/super_orchestrator/pipeline.py:611-621` `asyncio.create_subprocess_exec(sys.executable, "-m", "agent_team", "--cwd", str(output_dir), "--depth", config.builder.depth, stdout=PIPE, stderr=PIPE)`. | |
| TECH-024 | PASS | `src/super_orchestrator/pipeline.py:602` `output_dir = Path(config.output_dir) / service_info.service_id`. Each builder gets its own directory. Config written per-builder at `:606-607`. | |
| TECH-025 | PARTIAL | `src/super_orchestrator/pipeline.py` -- `state.save()` is called in phase handlers (e.g., `_phase_architect` at `:1279,1282,1289,1294`). Also called in the loop at `:1263`. However, the save happens AFTER the transition trigger (e.g., `:1280` `await model.start_architect()` then `:1282` `state.save()`), not strictly BEFORE. For `_phase_architect`, the first save at `:1279` is before the transition, but subsequent saves are after. | Pattern is mixed: some saves are before transitions, some after. PRD says "BEFORE every phase transition". The loop saves at `:1263` after handler returns (after transitions). |
| TECH-026 | PASS | `src/super_orchestrator/pipeline.py:1259` `cost_tracker.check_budget()` called after every handler in `_run_pipeline_loop`. | |
| TECH-027 | PASS | `src/super_orchestrator/cli.py` -- each command calls `asyncio.run()` exactly once: `plan` at `:219`, `build` at `:271`, `integrate` at `:321`, `verify` at `:369`, `run_cmd` at `:421`, `resume` at `:502`. No nested `asyncio.run()`. | |
| TECH-028 | PASS | `src/super_orchestrator/cli.py:58-63` `app = typer.Typer(name="super-orchestrator", ... rich_markup_mode="rich", ...)`. | |
| TECH-029 | PASS | `src/super_orchestrator/cli.py` -- all async commands use sync wrapper + `asyncio.run(_async_impl())` pattern. E.g., `def plan(...)` calls `asyncio.run(_plan_async(...))` at `:219`. | |
| TECH-030 | PARTIAL | `src/super_orchestrator/display.py:22-28` imports `SpinnerColumn, TextColumn, BarColumn, TimeElapsedColumn` from `rich.progress`. `Progress(...)` at `:257-263` uses correct column layout. However, PRD also says `from rich.console import Console, Group` -- `Group` is NOT imported. | Missing `from rich.console import Group` import. `Group` is never used in `print_quality_summary` as PRD requires `Panel(Group(Table(...)))`. |
| TECH-031 | PASS | `src/integrator/compose_generator.py` uses `python:3.12-slim-bookworm` for default Python Dockerfile template (Debian-based). Node template uses `node:20-slim` (also Debian). | |
| TECH-032 | PASS | `pyproject.toml:53` `asyncio_mode = "auto"` under `[tool.pytest.ini_options]`. Also has `filterwarnings` at `:55-58`. | |

---

## WIRE Requirements (22 items)

| ID | Status | Evidence (file:line) | Issue (if not PASS) |
|----|--------|---------------------|---------------------|
| WIRE-001 | PASS | `src/build3_shared/models.py` imported by: `pipeline.py:46-53`, `layer1_per_service.py:11-16`, `layer2_contract_compliance.py`, `layer3_system_level.py`, `schemathesis_runner.py:23`, `pact_manager.py:16`, `adversarial_patterns.py`, `security_scanner.py`. All three packages import it. | |
| WIRE-002 | PASS | `src/super_orchestrator/state_machine.py:16-28` `STATES` is module-level list; `:33-121` `TRANSITIONS` is module-level list. Both are constants for testability. Note: `State` object from transitions is NOT explicitly imported -- STATES uses plain strings, not `State` objects. However, `transitions.AsyncMachine` accepts string states. | |
| WIRE-003 | PASS | `src/super_orchestrator/state.py:11` `from src.build3_shared.utils import atomic_write_json, load_json`. `save()` at `:81` calls `atomic_write_json(path, self.to_dict())`. | |
| WIRE-004 | PASS | `src/super_orchestrator/shutdown.py:49-58` `set_state(self, state: Any)` method for deferred injection. Constructor at `:35-38` does NOT accept state. `pipeline.py:1174` calls `shutdown.set_state(state)` after state creation. | |
| WIRE-005 | PASS | `src/integrator/compose_generator.py` internally creates `TraefikConfigGenerator` and calls `generate_labels()` for each service entry in the generated docker-compose.yml. | |
| WIRE-006 | FAIL | `src/integrator/docker_orchestrator.py` has its own `wait_for_healthy()` implementation that polls `docker compose ps --format json`. It does NOT delegate to `ServiceDiscovery.wait_all_healthy()` or compose `ServiceDiscovery`. | PRD says DockerOrchestrator.wait_for_healthy() "should delegate to ServiceDiscovery.wait_all_healthy() or compose ServiceDiscovery for health checking". The two classes operate independently. |
| WIRE-007 | PASS | `src/integrator/contract_compliance.py` composes `SchemathesisRunner` and `PactManager` internally. Callers interact only with `ContractComplianceVerifier`. | |
| WIRE-008 | PASS | `src/integrator/fix_loop.py` writes `FIX_INSTRUCTIONS.md` to builder directory and invokes `python -m agent_team` as subprocess. | |
| WIRE-009 | PASS | `src/integrator/cross_service_test_generator.py` constructor accepts `contract_registry_path: Path` -- same path format used by `ContractComplianceVerifier`. | |
| WIRE-010 | PASS | `src/integrator/cross_service_test_runner.py` constructor accepts `services: dict[str, str]` mapping service_name to base_url, same format as DockerOrchestrator output. | |
| WIRE-011 | PASS | `src/quality_gate/gate_engine.py` composes `Layer1Scanner`, `Layer2Scanner`, `Layer3Scanner`, `Layer4Scanner` internally. `run_all_layers()` accepts `builder_results` and `integration_report`. | |
| WIRE-012 | PASS | `src/quality_gate/layer2_contract_compliance.py` `evaluate(self, integration_report: IntegrationReport)` consumes `IntegrationReport` from M2. | |
| WIRE-013 | PASS | `src/quality_gate/layer3_system_level.py` instantiates `SecurityScanner()`, `ObservabilityChecker()`, `DockerSecurityScanner()` and calls their `scan_all()` methods. | |
| WIRE-014 | PASS | `src/quality_gate/gate_engine.py` calls `self._aggregator.aggregate()` (via `ScanAggregator`) to produce the final `QualityGateReport`. | |
| WIRE-015 | PASS | `src/super_orchestrator/pipeline.py:303-314` MCP import is lazy inside function body with `except ImportError` fallback to subprocess. | |
| WIRE-016 | PARTIAL | `src/super_orchestrator/pipeline.py:611-621` uses subprocess (`asyncio.create_subprocess_exec`) to run builders. There is no attempt to import or use Build 2's `create_execution_backend()`. | PRD says "must use Build 2's `create_execution_backend()` pattern when Agent Teams is available, falling back to subprocess mode". Only subprocess mode is implemented; no `create_execution_backend()` attempt. |
| WIRE-017 | PARTIAL | `src/super_orchestrator/pipeline.py:716-720` imports and composes `ComposeGenerator`, `ContractComplianceVerifier`, `CrossServiceTestRunner`, `DockerOrchestrator`. However, `BoundaryTester` from M3 is NOT imported or used in the integration phase. | PRD says must compose "BoundaryTester (M3)". Missing `BoundaryTester` integration. |
| WIRE-018 | PASS | `src/super_orchestrator/pipeline.py:1244-1250` checks `shutdown.should_stop` before each phase in `_run_pipeline_loop`. Also checked within individual phase functions (e.g., `:232`, `:396`, `:513`). | |
| WIRE-019 | PASS | `src/super_orchestrator/pipeline.py:854-864` calls `generate_integration_report(report)` and writes to `integration_report.md` in output directory. | |
| WIRE-020 | PARTIAL | `src/super_orchestrator/pipeline.py:977-987` calls `generate_quality_gate_report(report)` and writes to `quality_gate_report.md`. PRD says file should be `QUALITY_GATE_REPORT.md` (uppercase). Code writes `quality_gate_report.md` (lowercase). | Filename is `quality_gate_report.md` instead of PRD-specified `QUALITY_GATE_REPORT.md`. Minor naming deviation. |
| WIRE-021 | PASS | `src/super_orchestrator/cli.py:234` `config = load_super_config(config_path)` loads from config YAML. Default config generated at `:184-187`. Config path passed via `--config` option on all relevant commands. | |
| WIRE-022 | PASS | `src/super_orchestrator/cli.py:424-443` `run` command: imports `execute_pipeline`, calls it with `prd_path`, `config_path`, `resume`. `execute_pipeline` at `pipeline.py:1171-1174` creates `PipelineCostTracker`, `GracefulShutdown`, installs shutdown, sets state. | |

---

## Detailed Findings

### Critical Failures (FAIL)

**TECH-012: Schemathesis FailureGroup catch**
The PRD mandates that `case.validate_response()` raises `schemathesis.failures.FailureGroup` and this must be caught explicitly. The implementation in `schemathesis_runner.py` bypasses the schemathesis programmatic API entirely -- it uses raw `httpx.Client` requests (line 371) instead of `schema.get_all_operations()` / `case.call()` / `case.validate_response()`. The `FailureGroup` class is never imported or caught.

**WIRE-006: DockerOrchestrator delegation to ServiceDiscovery**
The PRD says `DockerOrchestrator.wait_for_healthy()` should delegate to `ServiceDiscovery.wait_all_healthy()`. Instead, `DockerOrchestrator` has its own independent health-checking implementation that polls `docker compose ps --format json`. `ServiceDiscovery` exists as a separate class but is not composed into `DockerOrchestrator`.

### Partial Issues

**TECH-013: Pact state_handler() missing** -- `Verifier.state_handler()` is never called. The PRD explicitly requires this call.

**TECH-014: httpx timeout inconsistency** -- `service_discovery.py` uses `timeout=5.0` instead of the mandated `timeout=30.0`.

**TECH-025: State save timing** -- Some saves occur after transitions rather than strictly before. The PRD says "BEFORE every phase transition."

**TECH-030: Missing Group import** -- `from rich.console import Group` is not present. `print_quality_summary` does not use `Panel(Group(Table(...)))` pattern.

**WIRE-016: No create_execution_backend() attempt** -- Only subprocess fallback is implemented; the Build 2 pattern is never tried.

**WIRE-017: Missing BoundaryTester** -- Integration phase composes Docker, compliance, and cross-service runners but omits `BoundaryTester`.

**WIRE-020: Filename case** -- Output file is `quality_gate_report.md` vs PRD-specified `QUALITY_GATE_REPORT.md`.

---

## Score Breakdown

| ID | Score |
|----|-------|
| TECH-001 | 5 |
| TECH-002 | 5 |
| TECH-003 | 5 |
| TECH-004 | 5 |
| TECH-005 | 5 |
| TECH-006 | 5 |
| TECH-007 | 5 |
| TECH-008 | 5 |
| TECH-009 | 5 |
| TECH-010 | 5 |
| TECH-011 | 5 |
| TECH-012 | 0 |
| TECH-013 | 2 |
| TECH-014 | 2 |
| TECH-014a | 5 |
| TECH-015 | 5 |
| TECH-016 | 5 |
| TECH-017 | 5 |
| TECH-018 | 5 |
| TECH-019 | 5 |
| TECH-020 | 5 |
| TECH-021 | 5 |
| TECH-022 | 5 |
| TECH-023 | 5 |
| TECH-024 | 5 |
| TECH-025 | 2 |
| TECH-026 | 5 |
| TECH-027 | 5 |
| TECH-028 | 5 |
| TECH-029 | 5 |
| TECH-030 | 2 |
| TECH-031 | 5 |
| TECH-032 | 5 |
| **TECH Subtotal** | **135 / 160** |
| WIRE-001 | 5 |
| WIRE-002 | 5 |
| WIRE-003 | 5 |
| WIRE-004 | 5 |
| WIRE-005 | 5 |
| WIRE-006 | 0 |
| WIRE-007 | 5 |
| WIRE-008 | 5 |
| WIRE-009 | 5 |
| WIRE-010 | 5 |
| WIRE-011 | 5 |
| WIRE-012 | 5 |
| WIRE-013 | 5 |
| WIRE-014 | 5 |
| WIRE-015 | 5 |
| WIRE-016 | 2 |
| WIRE-017 | 2 |
| WIRE-018 | 5 |
| WIRE-019 | 5 |
| WIRE-020 | 2 |
| WIRE-021 | 5 |
| WIRE-022 | 5 |
| **WIRE Subtotal** | **96 / 110** |
| **GRAND TOTAL** | **231 / 270 (85.6%)** |

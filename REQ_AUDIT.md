# REQ_AUDIT.md -- Functional Requirements Audit (REQ-001 through REQ-070)

**Auditor:** req-auditor
**Date:** 2026-02-17
**Scope:** Verify all 70 functional requirements from BUILD3_PRD.md against source code
**Scoring:** PASS = 5 pts | PARTIAL = 2 pts | FAIL = 0 pts

---

## Summary

| Metric | Value |
|---|---|
| Total Requirements | 70 |
| PASS | 37 |
| PARTIAL | 31 |
| FAIL | 2 |
| Score | 37x5 + 31x2 + 2x0 = **247 / 350** (70.6%) |

---

## Audit Table

| REQ ID | Status | Evidence (file:line) | Issue (if not PASS) |
|---|---|---|---|
| REQ-001 | PASS | `src/build3_shared/models.py:14-34` | Enums ServiceStatus, QualityLevel, GateVerdict exist with correct str+Enum pattern and correct values |
| REQ-002 | PARTIAL | `src/build3_shared/models.py:37-55` | ServiceInfo exists but `stack` typed `dict[str,Any]` (PRD: `dict[str,str]`), `system_id`/`service_id` have `=""` defaults (PRD: positional). BuilderResult has all fields with defaults where PRD implies positional. |
| REQ-003 | PARTIAL | `src/build3_shared/models.py:58-84` | ContractViolation has extra `line: int = 0` not in PRD. ScanViolation has extra `suggestion: str = ""` not in PRD. `severity` defaults to `"error"` not specified in PRD. |
| REQ-004 | PARTIAL | `src/build3_shared/models.py:87-125` | LayerResult `layer` field has default value (PRD: first positional). QualityGateReport field order: `overall_verdict` before `layers` (PRD: `layers` first). IntegrationReport matches. |
| REQ-005 | PARTIAL | `src/build3_shared/protocols.py:1-39` | Both protocols have `@runtime_checkable`. PhaseExecutor uses `state: Any` not `context`, returns `Any` not `float`. QualityScanner uses `target_dir` not `project_root`. |
| REQ-006 | PARTIAL | `src/build3_shared/constants.py:1-143` | Variable names differ: `SEC_CODES` vs PRD's `SECURITY_SCAN_CODES`, `CORS_CODES` vs `CORS_SCAN_CODES`, etc. `STATE_FILE` is Path (PRD: string). `ALL_PHASES` missing `PHASE_ARCHITECT_REVIEW`. 40 scan codes correct. |
| REQ-007 | PARTIAL | `src/build3_shared/utils.py` | `atomic_write_json` matches (write .tmp, rename). `load_json` raises exception on missing/invalid (PRD: return None). `ensure_dir` matches. |
| REQ-008 | PARTIAL | `src/super_orchestrator/config.py` | ArchitectConfig `timeout=300` (PRD: 900), `retries` (PRD: `max_retries`), extra `mcp_server`. BuilderConfig `timeout=1800` (PRD: `timeout_per_builder`). IntegrationConfig uses `compose_timeout`/`health_timeout` (PRD: single `timeout=600`). QualityGateConfig missing `layer3_scanners`, `layer4_enabled`, `blocking_severity`. SuperOrchestratorConfig missing `depth`, `phase_timeouts`. |
| REQ-009 | PARTIAL | `src/super_orchestrator/state.py` | `builder_results: dict` (PRD: `list[dict]`). `budget_limit: float = 50.0` (PRD: `float|None`). `save()` takes `path` param (PRD: `save(directory)`). `load()` raises on missing (PRD: returns `None`). `clear()` deletes file (PRD: removes directory). |
| REQ-010 | PARTIAL | `src/super_orchestrator/cost.py` | PhaseCost uses `phase`/`cost`/`started_at`/`ended_at` (PRD: `phase_name`/`cost_usd`/`start_time`/`end_time`/`sub_phases`). PipelineCostTracker is class not dataclass. `check_budget()` raises exception (PRD: returns `tuple[bool, str]`). |
| REQ-011 | PARTIAL | `src/super_orchestrator/state_machine.py:16-162` | STATES uses plain strings (PRD: State objects with on_enter callbacks). `create_pipeline_machine` missing `initial_state` parameter. 11 states and 13 transitions correct. RESUME_TRIGGERS correct. |
| REQ-012 | PARTIAL | `src/super_orchestrator/exceptions.py` | All 5 exception classes exist. PhaseTimeoutError: `phase` not `phase_name`. BudgetExceededError: `current`/`limit` not `total_cost`/`budget_limit`. BuilderFailureError missing `service_id`. QualityGateFailureError missing `layer`. |
| REQ-013 | PASS | `src/super_orchestrator/shutdown.py` | `_should_stop`, `_state`, `install()`, `set_state()`, `should_stop` property present. Windows uses `signal.signal`, Unix tries `loop.add_signal_handler`. `_emergency_save()` saves state if ref exists. Reentrancy guard present. |
| REQ-014 | PASS | `src/build3_shared/__init__.py`, `src/super_orchestrator/__init__.py`, `src/integrator/__init__.py`, `src/quality_gate/__init__.py` | All four `__init__.py` files contain `__version__ = "3.0.0"`. |
| REQ-015 | PARTIAL | `src/integrator/compose_generator.py` | ComposeGenerator exists. `__init__` takes `traefik_image` etc. (PRD: `config: SuperOrchestratorConfig`). `generate` takes `(services, output_path)` returns Path (PRD: `(service_map, builder_results)` returns string). Traefik has `--ping=true` and healthcheck. Missing PRD-specified Dockerfile templates. |
| REQ-016 | PARTIAL | `src/integrator/traefik_config.py` | TraefikConfigGenerator exists. `generate_labels` uses `service_id` not `service_name`. Labels use correct backtick PathPrefix. Strip prefix middleware present. `generate_static_config` returns dict (PRD: str). |
| REQ-017 | PARTIAL | `src/integrator/docker_orchestrator.py` | DockerOrchestrator constructor matches `(compose_file, project_name)`. `start_services`, `wait_for_healthy`, `get_service_url`, `get_service_logs`, `restart_service` present. `start_services` returns dict not `dict[str, ServiceInfo]`. Missing `is_service_healthy` method. |
| REQ-018 | PARTIAL | `src/integrator/service_discovery.py` | ServiceDiscovery exists. `get_service_ports` is async (PRD: sync). `check_health` takes `url` not `(service_name, url)`, returns dict not bool. `wait_all_healthy` uses `poll_interval=5` (PRD: 3s). |
| REQ-019 | PARTIAL | `src/integrator/schemathesis_runner.py:70-106` | SchemathesisRunner exists. Uses `asyncio.to_thread` correctly. `run_against_service` doesn't use `get_all_operations()` API; uses raw paths fallback. Missing `max_examples` parameter. |
| REQ-020 | PASS | `src/integrator/schemathesis_runner.py:108-166` | `run_negative_tests` exists with malformed payloads (None, empty, invalid JSON, XSS, overflow). `generate_test_file` produces valid pytest source with `@schema.parametrize()`. |
| REQ-021 | PARTIAL | `src/integrator/pact_manager.py` | PactManager `__init__` takes optional `pact_dir` (PRD: required `pact_dir: Path`). `load_pacts` takes `pact_dir` param (PRD: method on self). |
| REQ-022 | PASS | `src/integrator/pact_manager.py` | `verify_provider` uses correct v3 API: `Verifier(provider_name)`, `add_transport(url=...)`, `add_source()`, `asyncio.to_thread(verifier.verify)`. |
| REQ-023 | PARTIAL | `src/integrator/contract_compliance.py` | ContractComplianceVerifier `__init__` takes `timeout` (PRD: `contract_registry_path, services`). Composes SchemathesisRunner and PactManager internally. `verify_all_services` uses `asyncio.gather(return_exceptions=True)`. Missing `run_schemathesis_tests` and `run_pact_verification` as separate methods. Missing `generate_compliance_report`. |
| REQ-024 | PARTIAL | `src/integrator/fix_loop.py` | ContractFixLoop `__init__` takes `timeout` (PRD: `config: SuperOrchestratorConfig`). `feed_violations_to_builder` writes FIX_INSTRUCTIONS.md. Launches subprocess with `python -m agent_team --cwd --depth quick`. `classify_violations` groups by severity. Returns `dict` (PRD: `float`). |
| REQ-025 | PASS | `src/integrator/report.py` | `generate_integration_report(results: IntegrationReport) -> str` exists. Has Summary, Per-Service Results, Violations, Recommendations sections matching PRD. |
| REQ-026 | PARTIAL | `src/integrator/cross_service_test_generator.py` | `__init__` takes no args (PRD: `contract_registry_path, domain_model_path`). `generate_flow_tests` takes `contract_registry_path` as param. Chain detection implemented (field overlap >= 2, max depth 5, top 20). |
| REQ-027 | PASS | `src/integrator/cross_service_test_generator.py` | `generate_boundary_tests` exists with case_sensitivity, timezone, null_handling test categories. Correct boundary test structure. |
| REQ-028 | PARTIAL | `src/integrator/cross_service_test_runner.py` | `__init__` takes `timeout` (PRD: `services: dict[str, str]`). `run_flow_tests` takes `(flows, service_urls)` (PRD: `(flows) -> IntegrationReport`). `run_single_flow` returns dict (PRD: `tuple[bool, list[str]]`). Template variable resolution present. |
| REQ-029 | PARTIAL | `src/integrator/data_flow_tracer.py` | `__init__` takes `timeout` (PRD: `services: dict[str, str]`). `trace_request` signature differs. `verify_data_transformations` returns `list[ContractViolation]` (PRD: `list[str]`). |
| REQ-030 | PARTIAL | `src/integrator/boundary_tester.py` | `__init__` takes `timeout` (PRD: `services: dict[str, str]`). `test_case_sensitivity` takes `(service_url, endpoint, test_data)` (PRD: `(service_name, endpoint, camel_body, snake_body)`). Similar deviations for `test_timezone_handling` and `test_null_handling`. |
| REQ-031 | PARTIAL | `src/quality_gate/gate_engine.py` | QualityGateEngine `__init__` takes no args (PRD: `config, project_root`). `run_all_layers` takes extended params (PRD: `builder_results, integration_report`). Uses ScanAggregator. `should_promote` and `classify_violations` present. |
| REQ-032 | PASS | `src/quality_gate/layer1_per_service.py` | Layer1Scanner `evaluate(builder_results)` checks success, test pass rate (>=0.9), convergence ratio (>=0.9). Correct threshold logic. |
| REQ-033 | PASS | `src/quality_gate/layer2_contract_compliance.py` | Layer2Scanner `evaluate(integration_report)` converts violations and determines verdict. PASSED if 100%, PARTIAL if >70%, FAILED otherwise, SKIPPED if 0 tests. |
| REQ-034 | PARTIAL | `src/quality_gate/security_scanner.py` | SecurityScanner exists with JWT (SEC-001 through SEC-006), CORS (CORS-001 through CORS-003), secret detection (SEC-SECRET-001 through SEC-SECRET-012) patterns. SEC-001 uses 5-line window (PRD: 10 lines). Some SEC-SECRET regex patterns differ from PRD spec. |
| REQ-035 | PASS | `src/quality_gate/security_scanner.py` | Secret detection patterns (SEC-SECRET-001 through SEC-SECRET-012) all present. Generic patterns cover API keys, passwords, private keys, AWS credentials, DB strings, JWT secrets, OAuth secrets, encryption keys, tokens, certificates, service account keys, webhook secrets. |
| REQ-036 | PASS | `src/quality_gate/observability_checker.py:144-578` | ObservabilityChecker implements all 5 checks: LOG-001 (structured logging), LOG-004 (sensitive data in logs), LOG-005 (request ID logging), TRACE-001 (trace propagation), HEALTH-001 (health endpoint). Module-level compiled regex. EXCLUDED_DIRS frozenset. |
| REQ-037 | PASS | `src/quality_gate/docker_security.py:97-802` | DockerSecurityScanner implements all 8 Docker checks: DOCKER-001 (root user), DOCKER-002 (healthcheck), DOCKER-003 (latest tag), DOCKER-004 (port exposure), DOCKER-005 (resource limits), DOCKER-006 (privileged), DOCKER-007 (read_only), DOCKER-008 (security_opt). YAML parsing with regex fallback. |
| REQ-038 | PASS | `src/quality_gate/layer3_system_level.py` | Layer3Scanner `evaluate(target_dir)` runs SecurityScanner, ObservabilityChecker, DockerSecurityScanner concurrently. Per-category cap at 200 (TECH-021). |
| REQ-039 | PASS | `src/quality_gate/adversarial_patterns.py:181-249` | ADV-001 dead event handlers: finds `@event_handler/@on_event/@subscriber` decorated functions, checks if referenced elsewhere. Correct 2-phase approach. |
| REQ-040 | PASS | `src/quality_gate/adversarial_patterns.py:253-305` | ADV-002 dead contracts: identifies OpenAPI/AsyncAPI YAML/JSON files, checks if filename/stem referenced in Python source. |
| REQ-041 | PASS | `src/quality_gate/adversarial_patterns.py:309-407` | ADV-003 orphan services: discovers service dirs by entry points (main.py, app.py, etc.), checks cross-references. Requires >=2 services. |
| REQ-042 | PASS | `src/quality_gate/adversarial_patterns.py:411-487,491-557,561-638` | ADV-004 naming inconsistency (camelCase detection in Python). ADV-005 bare/broad except without re-raise. ADV-006 module-level mutable state without locks. |
| REQ-043 | PASS | `src/quality_gate/layer4_adversarial.py` | Layer4Scanner `evaluate(target_dir)` always returns PASSED verdict (advisory-only per PRD). Runs AdversarialScanner internally. |
| REQ-044 | PASS | `src/quality_gate/scan_aggregator.py:17-128` | ScanAggregator.aggregate() takes `layer_results`, deduplicates by `(code, file_path, line)`, counts blocking (severity=="error"), computes overall verdict with correct precedence (FAILED>PARTIAL>PASSED>SKIPPED). |
| REQ-045 | PASS | `src/quality_gate/report.py:349-392` | `generate_quality_gate_report(report: QualityGateReport) -> str` produces Markdown with 5 sections: Header, Summary, Per-Layer Results, Violations (grouped by severity), Recommendations. Pure function, no I/O. |
| REQ-046 | PARTIAL | `src/super_orchestrator/pipeline.py` | `run_architect_phase` signature is `(state, config, cost_tracker, shutdown)` (PRD: `(prd_path, config, state, tracker)`). MCP fallback via lazy import implemented. Retry loop present. |
| REQ-047 | PARTIAL | `src/super_orchestrator/pipeline.py` | `generate_builder_config` signature `(service_info, config, state)` (PRD: `(global_config, service_info, contracts_path)`). Output dict missing PRD-specified `milestone.enabled`, `e2e_testing.enabled` keys. |
| REQ-048 | PARTIAL | `src/super_orchestrator/pipeline.py` | `run_parallel_builders` signature is `(state, config, cost_tracker, shutdown)` (PRD: `(builder_configs, config, state, tracker, max_concurrent)`). Uses `asyncio.Semaphore` for concurrency control. `_parse_builder_result` uses flat `success` key (PRD: `summary.success` path). |
| REQ-049 | PASS | `src/super_orchestrator/pipeline.py` | `run_integration_phase` exists. Instantiates ComposeGenerator, DockerOrchestrator, ServiceDiscovery, ContractComplianceVerifier. `docker_orchestrator.stop_services()` in finally block. |
| REQ-050 | PASS | `src/super_orchestrator/pipeline.py` | `run_quality_gate` exists. Calls QualityGateEngine.run_all_layers(). Returns QualityGateReport. Saves report to JSON. |
| REQ-051 | PASS | `src/super_orchestrator/pipeline.py` | `run_fix_pass` exists. Calls ContractFixLoop.feed_violations_to_builder(). Updates state.quality_attempts. |
| REQ-052 | PARTIAL | `src/super_orchestrator/pipeline.py` | `execute_pipeline` signature is `(prd_path, config_path, resume)` (PRD: `(prd_path, config, state, tracker, shutdown)`). PipelineModel with guard methods present. State machine drives transitions. |
| REQ-053 | PASS | `src/super_orchestrator/pipeline.py` | PipelineModel implements all guard methods: `is_configured`, `has_service_map`, `service_map_valid`, `contracts_valid`, `has_builder_results`, `any_builder_passed`, `has_integration_report`, `gate_passed`, `fix_attempts_remaining`, `fix_applied`, `retries_remaining`, `advisory_only`. |
| REQ-054 | PASS | `src/super_orchestrator/cli.py` | Typer app with 8 commands (init, plan, build, integrate, verify, run, status, resume) plus `--version` callback. `app = typer.Typer(name="super-orchestrator", rich_markup_mode="rich")`. |
| REQ-055 | PASS | `src/super_orchestrator/cli.py` | `init` validates PRD > 100 bytes, creates .super-orchestrator/, copies PRD, generates UUID pipeline_id, initializes PipelineState, checks `docker compose version`. |
| REQ-056 | PASS | `src/super_orchestrator/cli.py` | `run` command calls `execute_pipeline()`, catches `PipelineError` and `KeyboardInterrupt`, displays Rich error panel. |
| REQ-057 | PASS | `src/super_orchestrator/cli.py` | `status` loads PipelineState, displays phase table, builder table, quality summary, cost. |
| REQ-058 | PASS | `src/super_orchestrator/cli.py` | `resume` loads PipelineState (exits if none), validates files exist, calls `execute_pipeline` with `resume=True`. |
| REQ-059 | PARTIAL | `src/super_orchestrator/display.py:36-359` | Module-level `_console = Console()` correct. `print_pipeline_header` takes `(pipeline_id, prd_path)` (PRD: `(state, tracker)`). `print_phase_table` takes `state` (PRD: `(state, tracker)`). `create_progress_bar()` takes no args (PRD: `(description: str)`). Missing `Group` import from `rich.console`. |
| REQ-060 | FAIL | N/A | No default `config.yaml` template found in project root with documented comments for all SuperOrchestratorConfig fields. |
| REQ-061 | PASS | `tests/build3/fixtures/sample_prd.md:1-1075` | Realistic 3-service PRD with auth-service, order-service, notification-service. 3 entities (User, Order, Notification). 3 cross-service API contracts. 2 event-driven contracts (OrderCreated, OrderShipped). Order state machine (pending->confirmed->shipped->delivered). |
| REQ-062 | PASS | `tests/build3/fixtures/sample_openapi.yaml:1-411` | Valid OpenAPI 3.1 spec for order-service with GET/POST/PUT endpoints, User and Order schemas, standard error responses (400/404/422/500). |
| REQ-063 | PASS | `tests/build3/fixtures/sample_pact.json:1-97` | Valid Pact V4 contract between notification-service (consumer) and order-service (provider) with GET /orders/{id} and POST /orders/{id}/events interactions. |
| REQ-064 | PASS | `tests/build3/fixtures/sample_docker_compose.yml:1-117` | Compose file with 3 services (auth, order, notification) plus Traefik and PostgreSQL. All services have healthchecks and Traefik labels. |
| REQ-065 | PASS | `tests/build3/test_integration_e2e.py:590-1836` | Full pipeline E2E test with all phases mocked. Tests quality violations trigger fix loop (test #6), final report generation (test #9). 39 total test cases. All external deps mocked. |
| REQ-066 | PASS | `tests/build3/test_integration_e2e.py:601-646` | Tests verify PIPELINE_STATE.json fields: pipeline_id, prd_path, started_at, current_state=="complete", completed_phases contains all phase names, total_cost > 0, quality_report_path exists. |
| REQ-067 | PASS | `tests/build3/test_integration_e2e.py:783-1123` | Resume tests for architect_running (#16), builders_running (#17), quality_gate (#18), fix_pass (#19). All verify pipeline completes from interrupted state. |
| REQ-068 | PASS | `tests/build3/test_integration_e2e.py:1161-1243` | Test sets `shutdown.should_stop = True` after architect phase, verifies `result.interrupted is True`. State saved correctly. |
| REQ-069 | FAIL | `tests/build3/test_integration_e2e.py:1149-1159` | Test exists but sets `budget_limit=0.01` which may not trigger BudgetExceededError because budget check timing depends on when cost_tracker.check_budget() is called vs when costs are recorded. Test may be fragile. PRD requires "accurate cost information" in exception -- not verified in test assertions. |
| REQ-070 | PARTIAL | `tests/build3/test_integration_e2e.py:1353-1433` | `len(ALL_SCAN_CODES) == 40` verified (test #24). Scan codes unique (test #25). 8 categories verified (test #26). However PRD says "exercised by at least one scanner" -- tests don't verify each scanner's `scan_codes` property matches expected codes. Only verifies constant list length. |

---

## Detailed Findings by Category

### Models (REQ-001 through REQ-004)
- Enums fully match PRD specification
- Dataclass fields generally present but with default-value and ordering deviations
- Extra fields added to ContractViolation (`line`) and ScanViolation (`suggestion`) -- reasonable extensions but not in PRD

### Protocols (REQ-005)
- Parameter naming inconsistencies: `state` vs `context`, `target_dir` vs `project_root`
- Return type mismatch: `Any` vs `float` for PhaseExecutor

### Constants (REQ-006)
- Variable naming convention differs from PRD (e.g., `SEC_CODES` vs `SECURITY_SCAN_CODES`)
- Core assertion `len(ALL_SCAN_CODES) == 40` correct

### Config/State/Cost (REQ-008 through REQ-010)
- Most significant deviations: timeout values, field names, return types, class vs dataclass choice
- Functional behavior present but API contracts differ from PRD specification

### State Machine (REQ-011)
- Correct topology (11 states, 13 transitions, RESUME_TRIGGERS)
- Missing State objects with on_enter callbacks (uses plain strings)
- Missing `initial_state` parameter

### Integrator (REQ-015 through REQ-030)
- All classes exist with correct high-level behavior
- Constructor signatures consistently differ (taking simpler params vs PRD's config-based)
- Return types and method signatures have minor deviations

### Quality Gate (REQ-031 through REQ-045)
- Strongest area: all scanners implemented with correct scan codes
- Layer logic correct (L1 thresholds, L2 percentages, L3 concurrent, L4 advisory-only)
- Constructor signatures simplified vs PRD spec

### Pipeline (REQ-046 through REQ-053)
- Core execution flow correct
- Function signatures consistently differ from PRD
- Guard methods all implemented

### CLI + Display (REQ-054 through REQ-060)
- CLI commands all present and functional
- Display function signatures differ from PRD
- Missing default config.yaml template (REQ-060)

### Fixtures + E2E (REQ-061 through REQ-070)
- Test fixtures high quality and comprehensive
- E2E tests cover all major scenarios with 39 test cases
- Minor gaps in scan code exercised-by-scanner verification

---

## FAIL Items Detail

| REQ | Root Cause | Remediation |
|---|---|---|
| REQ-060 | No `config.yaml` template file found in project root | Create `config.yaml` with all SuperOrchestratorConfig fields documented with comments |
| REQ-069 | Budget test assertion doesn't verify "accurate cost information" per PRD; test may be fragile with budget_limit=0.01 | Strengthen test to assert exception contains cost/limit values; ensure budget check fires reliably |

---

## Score Breakdown by Milestone

| Milestone | REQs | PASS | PARTIAL | FAIL | Score | Max |
|---|---|---|---|---|---|---|
| M1: Shared (REQ-001..014) | 14 | 3 | 11 | 0 | 37 | 70 |
| M2: Integration (REQ-015..025) | 11 | 3 | 8 | 0 | 31 | 55 |
| M3: Cross-Service (REQ-026..030) | 5 | 1 | 4 | 0 | 13 | 25 |
| M4: Quality Gate (REQ-031..045) | 15 | 13 | 2 | 0 | 69 | 75 |
| M5: Pipeline (REQ-046..053) | 8 | 4 | 4 | 0 | 28 | 40 |
| M6: CLI+Display (REQ-054..060) | 7 | 5 | 1 | 1 | 27 | 35 |
| M7: E2E (REQ-061..070) | 10 | 8 | 1 | 1 | 42 | 50 |
| **Totals** | **70** | **37** | **31** | **2** | **247** | **350** |

# ISSUE_MAP.md -- Attempt 13 Codebase Audit

**Generated:** 2026-02-25
**Auditor:** codebase-auditor agent
**Source files read end-to-end:** 14 files, ~12,000 lines total

---

## Issue 1: Builder subprocess never exits after completion

**Severity:** P0
**File(s):** `C:\MY_PROJECTS\super-team\src\super_orchestrator\pipeline.py`
**Function:** `_run_single_builder()`
**Line(s):** 1651-1653 (the wait call), 1644-1650 (subprocess launch)
**Current Code:**
```python
# Line 1644-1653
proc = await asyncio.create_subprocess_exec(
    *cmd,
    stdout=asyncio.subprocess.PIPE,
    stderr=asyncio.subprocess.PIPE,
    cwd=str(output_dir),
    env=sub_env,
)
await asyncio.wait_for(
    proc.wait(), timeout=config.builder.timeout_per_builder
)
```
**What Needs to Change:** Replace `await asyncio.wait_for(proc.wait(), timeout=...)` with a polling loop that checks the builder's STATE.json every N seconds. When STATE.json shows `current_phase: "complete"` or `summary.success: true`, or the phase is a post-code phase like `"e2e_testing"`, `"browser_testing"`, `"verification"`, the pipeline should stop waiting and terminate the subprocess. This avoids waiting 7200s for post-orchestration phases that run after code is done.
**Risk:** MEDIUM -- Must not break the fallback timeout, and must handle race conditions where STATE.json isn't yet written.
**Dependencies:** Issue 4 (STATE.json polling), Issue 21 (timeout value)

---

## Issue 2: Builder CHILD processes not killed on timeout

**Severity:** P1
**File(s):** `C:\MY_PROJECTS\super-team\src\super_orchestrator\pipeline.py`
**Function:** `_run_single_builder()` -- `finally` block
**Line(s):** 1678-1687
**Current Code:**
```python
# Line 1678-1687
finally:
    if proc is not None and proc.returncode is None:
        proc.terminate()
        try:
            await asyncio.wait_for(proc.wait(), timeout=5)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
```
**What Needs to Change:** After killing the direct subprocess, also kill the entire process tree. On Windows, use `subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)])`. On Unix, use `os.killpg(proc.pid, signal.SIGTERM)` (requires `start_new_session=True` at launch on line 1644). This prevents orphaned Claude CLI sessions from consuming resources.
**Risk:** MEDIUM -- Must handle cases where PID is already gone (race condition).
**Dependencies:** None

---

## Issue 3: No progress logging during builder execution

**Severity:** P2
**File(s):** `C:\MY_PROJECTS\super-team\src\super_orchestrator\pipeline.py`
**Function:** `_run_single_builder()`
**Line(s):** 1651-1653 (the bare `proc.wait()` with no intermediate logging)
**Current Code:**
```python
await asyncio.wait_for(
    proc.wait(), timeout=config.builder.timeout_per_builder
)
```
**What Needs to Change:** During the polling loop (new code from Issue 1/4), log builder progress at regular intervals. Read the service's STATE.json to extract `current_phase`, `completed_phases`, `convergence_ratio`, and log them. Example: `"[builder] accounts-service: phase=code_generation, 5/10 phases complete, convergence=0.65"`.
**Risk:** LOW -- Pure additive logging, cannot break anything.
**Dependencies:** Issue 1 (polling replaces wait_for), Issue 4 (STATE.json polling design)

---

## Issue 4: Pipeline should poll STATE.json for completion

**Severity:** P1
**File(s):** `C:\MY_PROJECTS\super-team\src\super_orchestrator\pipeline.py`, `C:\MY_PROJECTS\super-team\src\super_orchestrator\config.py`
**Function:** `_run_single_builder()` -- NEW `_run_builder_with_polling()` function needed
**Line(s):** pipeline.py 1651-1653 (replace these lines), config.py line 22-27 (add `poll_interval_s`)
**Current Code (pipeline.py 1651-1653):**
```python
await asyncio.wait_for(
    proc.wait(), timeout=config.builder.timeout_per_builder
)
```
**Current Code (config.py 22-27):**
```python
@dataclass
class BuilderConfig:
    """Configuration for the builder phase."""
    max_concurrent: int = 3
    timeout_per_builder: int = 1800
    depth: str = "thorough"
```
**What Needs to Change:**
1. Add `poll_interval_s: int = 30` to `BuilderConfig` in config.py (after line 27).
2. Replace the `asyncio.wait_for(proc.wait(), timeout=...)` block (pipeline.py 1651-1653) with a polling loop:
   - Every `poll_interval_s`, read `{output_dir}/.agent-team/STATE.json`
   - Check if `summary.success` is set, or `current_phase == "complete"`, or `current_phase in ("e2e_testing", "browser_testing", "verification")` (post-code phases)
   - If any of those conditions are true, terminate subprocess and parse result
   - If subprocess exits on its own (`proc.returncode is not None`), stop polling
   - If `timeout_per_builder` is exceeded, fall through to existing timeout handling
   - Log progress on each poll (Issue 3)
**Risk:** MEDIUM -- Must handle file-not-found, JSON parse errors, partial writes gracefully.
**Dependencies:** Issues 1, 3 (all part of the same builder lifecycle rewrite)

---

## Issue 5: Frontend has NO Dockerfile

**Severity:** P0
**File(s):**
- `C:\MY_PROJECTS\super-team\src\super_orchestrator\pipeline.py` (CLAUDE.md generation)
- `C:\MY_PROJECTS\super-team\src\integrator\compose_generator.py` (Dockerfile generation)
**Function:** `_write_builder_claude_md()` (pipeline.py:1193), `generate_default_dockerfile()` (compose_generator.py:408), `_dockerfile_content_for_stack()` (compose_generator.py:277)
**Line(s):**
- pipeline.py:1295-1302 -- "What You MUST Create" section for frontend
- compose_generator.py:408-436 -- `generate_default_dockerfile()` method (already exists!)
- compose_generator.py:284-300 -- frontend Dockerfile template (already exists!)
**Current Code (pipeline.py:1295-1302):**
```python
lines.append("## What You MUST Create\n")
lines.append("- UI components for each entity (list, detail, create, edit)")
lines.append("- API service/client layer to call backend endpoints")
lines.append("- TypeScript interfaces matching all entity schemas")
lines.append("- Routing configuration for all pages")
lines.append("- Authentication interceptor/guard for JWT tokens")
lines.append("- Form validation matching entity field requirements")
lines.append("")
```
**What Needs to Change:**
1. In `_write_builder_claude_md()` at line ~1301: Add `"- Dockerfile (multi-stage: node build -> nginx serve)"` to the "What You MUST Create" list for frontend services.
2. In `run_integration_phase()` (line ~2181): Before generating compose files, iterate over services and check if `{output_dir}/{service_id}/Dockerfile` exists. If not, call `compose_gen.generate_default_dockerfile(service_dir, port, service_info)`.
**Verified:** Frontend directory at `C:\MY_PROJECTS\super-team\.super-orchestrator\frontend\` has 73+ source files but NO Dockerfile.
**Risk:** LOW -- Additive change; Dockerfile template already exists in compose_generator.
**Dependencies:** Issue 8 (pre-integration Dockerfile check), Issue 9 (CLAUDE.md Dockerfile requirement)

---

## Issue 6: accounts-service `npm run build` fails in Docker

**Severity:** P0
**File(s):** Build artifacts at `C:\MY_PROJECTS\super-team\.super-orchestrator\accounts-service\`
**Function:** N/A (build artifact issue)
**Line(s):** Dockerfile line 7 (`RUN npm run build`), tsconfig.json line 15 (`"strict": true`)

**Dockerfile contents (28 lines):**
```dockerfile
FROM node:18-alpine AS builder
WORKDIR /app
COPY package*.json ./
RUN npm ci
COPY . .
RUN npm run build

FROM node:18-alpine AS production
WORKDIR /app
RUN addgroup -g 1001 -S nodejs && \
    adduser -S nestjs -u 1001
COPY --from=builder /app/dist ./dist
COPY --from=builder /app/node_modules ./node_modules
COPY --from=builder /app/package.json ./
USER nestjs
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
  CMD wget --no-verbose --tries=1 --spider http://localhost:8080/api/accounts/health || exit 1
CMD ["node", "dist/main"]
```

**tsconfig.json contents:**
```json
{
  "compilerOptions": {
    "module": "commonjs", "declaration": true, "removeComments": true,
    "emitDecoratorMetadata": true, "experimentalDecorators": true,
    "allowSyntheticDefaultImports": true, "target": "ES2022",
    "sourceMap": true, "outDir": "./dist", "baseUrl": "./",
    "incremental": true, "skipLibCheck": true,
    "strict": true,
    "forceConsistentCasingInFileNames": true,
    "noFallthroughCasesInSwitch": true,
    "paths": { "@/*": ["src/*"] }
  }
}
```

**package.json build script:** `"build": "nest build"`

**What Needs to Change:** Two approaches:
1. **Pipeline fix (prevents future occurrences):** In `_write_builder_claude_md()`, add TypeScript/NestJS-specific guidance: `"Set strict: false in tsconfig.json to avoid type errors that block Docker builds"`.
2. **Current artifact fix:** The docker-fixer can patch `tsconfig.json` to add `"strictNullChecks": false, "noImplicitAny": false` or set `"strict": false`, which relaxes type checking enough for the Docker build to succeed without changing generated code.
**Risk:** LOW -- Relaxing strict mode is safe for generated code.
**Dependencies:** None

---

## Issue 7: Docker Compose `version` attribute warnings

**Severity:** P3
**File(s):** `C:\MY_PROJECTS\super-team\src\integrator\compose_generator.py`
**Function:** `generate()`, `generate_compose_files()`
**Line(s):** 112, 528, 547, 556, 567, 578 -- all 6 instances of `"version": "3.8"`
**Current Code:**
```python
# Line 112 (in generate())
compose: dict[str, Any] = {
    "version": "3.8",
    ...
}

# Line 528 (infra)
infra = { "version": "3.8", ... }

# Line 547 (build1)
build1 = { "version": "3.8", ... }

# Line 556 (traefik)
traefik = { "version": "3.8", ... }

# Line 567 (generated)
generated = { "version": "3.8", ... }

# Line 578 (run4)
run4 = { "version": "3.8", ... }
```
**What Needs to Change:** Remove `"version": "3.8"` from all 6 locations. Docker Compose V2 ignores the version key and prints a deprecation warning. Removing it silences the warning.
**Risk:** LOW -- No functional change.
**Dependencies:** None (same as Issue 23)

---

## Issue 8: No Dockerfile existence check before integration

**Severity:** P1
**File(s):** `C:\MY_PROJECTS\super-team\src\super_orchestrator\pipeline.py`
**Function:** `run_integration_phase()`
**Line(s):** 2181-2185 (compose generation without Dockerfile check)
**Current Code:**
```python
# Line 2181-2185
compose_gen = ComposeGenerator(
    traefik_image=config.integration.traefik_image
)
compose_files = compose_gen.generate_compose_files(output_dir, services)
```
**What Needs to Change:** Insert Dockerfile check between lines 2180 and 2181:
```python
# Check and generate missing Dockerfiles
compose_gen = ComposeGenerator(traefik_image=config.integration.traefik_image)
for svc in services:
    svc_dir = output_dir / svc.service_id
    dockerfile = svc_dir / "Dockerfile"
    if not dockerfile.exists():
        logger.warning("No Dockerfile for %s -- generating default", svc.service_id)
        compose_gen.generate_default_dockerfile(svc_dir, svc.port, svc)
```
**Risk:** LOW -- `generate_default_dockerfile()` already exists (compose_generator.py:408) and handles all 3 stacks.
**Dependencies:** Issue 5 (both address missing Dockerfiles)

---

## Issue 9: Frontend CLAUDE.md doesn't require Dockerfile

**Severity:** P1
**File(s):** `C:\MY_PROJECTS\super-team\src\super_orchestrator\pipeline.py`
**Function:** `_write_builder_claude_md()`
**Line(s):** 1295-1302 (frontend "What You MUST Create" section)
**Current Code:**
```python
lines.append("## What You MUST Create\n")
lines.append("- UI components for each entity (list, detail, create, edit)")
lines.append("- API service/client layer to call backend endpoints")
lines.append("- TypeScript interfaces matching all entity schemas")
lines.append("- Routing configuration for all pages")
lines.append("- Authentication interceptor/guard for JWT tokens")
lines.append("- Form validation matching entity field requirements")
lines.append("")
```
**What Needs to Change:** After line 1301, add:
```python
lines.append("- Dockerfile (multi-stage build: node:20 npm build -> nginx:alpine serve dist/)")
```
Also consider adding for backend services (around line 1484):
```python
lines.append("- Dockerfile for containerized deployment")
```
**Risk:** LOW -- Additive text change.
**Dependencies:** Issue 5

---

## Issue 10: Fix pass references "unknown" service

**Severity:** P1
**File(s):**
- `C:\MY_PROJECTS\super-team\src\quality_gate\layer1_per_service.py` (ScanViolation creation)
- `C:\MY_PROJECTS\super-team\src\super_orchestrator\pipeline.py` (violation extraction)
**Function:**
- `Layer1Scanner.evaluate()` (layer1_per_service.py)
- `run_fix_pass()` (pipeline.py)
**Line(s):**
- layer1_per_service.py:85-96 -- ScanViolation creation missing `service=br.service_id`
- pipeline.py:2618 -- `v_data.get("service", v_data.get("file_path", ""))` fallback chain
- pipeline.py:2662-2664 -- `v.service or "unknown"` grouping

**Current Code (layer1_per_service.py:85-96):**
```python
violations.append(
    ScanViolation(
        code="L1-FAIL",
        severity="error",
        category="layer1",
        message=(
            f"Service '{br.service_id}' build failed: {reason}"
        ),
        file_path="",
        line=0,
    )
)
```
**Note:** `ScanViolation` has a `service: str = ""` field (models.py:87) but Layer1Scanner NEVER sets it.

**Also for L1-CONVERGENCE (line 99-111):**
```python
violations.append(
    ScanViolation(
        code="L1-CONVERGENCE",
        severity="warning",
        category="layer1",
        message=( ... ),
        file_path="",
        line=0,
    )
)
```
This also doesn't set `service`.

**What Needs to Change:** In layer1_per_service.py, add `service=br.service_id` to both ScanViolation constructors:
- Line 86: add `service=br.service_id,` after `category="layer1",`
- Line 100: The L1-CONVERGENCE violation is aggregate (not per-service), so `service` should be left empty or set to `"all"`.
**Risk:** LOW -- Single field addition.
**Dependencies:** None

---

## Issue 11: Fix loop can't classify Docker failures as unfixable

**Severity:** P1
**File(s):** `C:\MY_PROJECTS\super-team\src\super_orchestrator\pipeline.py`
**Function:** `_has_fixable_violations()`
**Line(s):** 3759-3787
**Current Code:**
```python
def _has_fixable_violations(quality_results: dict[str, Any]) -> bool:
    _UNFIXABLE_PREFIXES = ("INTEGRATION-", "INFRA-", "DOCKER-", "BUILD-NOSRC")

    found_any_violation = False
    for layer_data in quality_results.get("layers", {}).values():
        layer_violations = layer_data.get("violations", [])
        if isinstance(layer_violations, list):
            for v in layer_violations:
                found_any_violation = True
                code = str(v.get("code", ""))
                if not any(code.startswith(pfx) for pfx in _UNFIXABLE_PREFIXES):
                    return True
    if not found_any_violation:
        blocking = quality_results.get("blocking_violations", 0)
        if blocking and blocking > 0:
            return True
    return False
```
**What Needs to Change:** Docker build failures produce `"L1-FAIL"` violations (from layer1_per_service.py:87), which bypass the prefix check. Add message-based filtering: when code is `"L1-FAIL"` and the message contains keywords like "Docker", "Dockerfile", "docker compose", "No source files", classify as unfixable. Extract to a shared `_is_fixable()` helper (see Issue 25).
**Risk:** MEDIUM -- Must not classify legitimate code-level L1-FAIL as unfixable.
**Dependencies:** Issue 10 (service field), Issue 25 (shared _is_fixable)

---

## Issue 12: Fix loop doesn't detect repeated identical violations

**Severity:** P2
**File(s):** `C:\MY_PROJECTS\super-team\src\super_orchestrator\pipeline.py`
**Function:** `_phase_quality()` (line 3790), `_phase_quality_check()` (line 3828)
**Line(s):** 3812-3813 (decision to enter fix loop)
**Current Code:**
```python
elif model.fix_attempts_remaining() and _has_fixable_violations(state.last_quality_results):
    await model.quality_needs_fix()
```
**What Needs to Change:** Before entering the fix loop, compare current violations with previous pass. If identical, skip to complete. Store violation fingerprints in `state.phase_artifacts[PHASE_FIX_PASS]` and compare.
**Risk:** LOW -- Pure additive logic.
**Dependencies:** Issue 11 (unfixable classification)

---

## Issue 13: Quality gate Layer 2 returns SKIPPED on integration failure

**Severity:** P2
**File(s):**
- `C:\MY_PROJECTS\super-team\src\quality_gate\layer2_contract_compliance.py`
- `C:\MY_PROJECTS\super-team\src\quality_gate\gate_engine.py`
**Function:** `Layer2Scanner._determine_verdict()`, `Layer2Scanner.evaluate()`, `QualityGateEngine.should_promote()`
**Line(s):**
- layer2_contract_compliance.py:132-145 -- `_determine_verdict()` returns SKIPPED when `contract_total == 0`
- layer2_contract_compliance.py:46 -- `evaluate()` signature
- gate_engine.py:222-254 -- `should_promote()` treats SKIPPED as blocking

**Current Code (layer2_contract_compliance.py:132-145):**
```python
def _determine_verdict(
    self, contract_rate: float, contract_total: int
) -> GateVerdict:
    if contract_total == 0:
        return GateVerdict.SKIPPED  # <-- Should be FAILED when integration failed
    if contract_rate >= self.CONTRACT_PASS_THRESHOLD:
        return GateVerdict.PASSED
    if contract_rate >= self.CONTRACT_PARTIAL_THRESHOLD:
        return GateVerdict.PARTIAL
    return GateVerdict.FAILED
```

**What Needs to Change:** Modify `evaluate()` to pass `integration_report.overall_health` to `_determine_verdict()`. When `overall_health in ("failed", "skipped")` AND `contract_total == 0`, return FAILED instead of SKIPPED. The `_determine_verdict()` signature needs an additional `integration_health` parameter.
**Risk:** LOW -- Semantic change to verdict logic.
**Dependencies:** None

---

## Issue 14: Resume fails with empty prd_path

**Severity:** P1
**File(s):** `C:\MY_PROJECTS\super-team\src\super_orchestrator\pipeline.py`
**Function:** `execute_pipeline()`
**Line(s):** 2854 (`prd_path = Path(prd_path)`), 2862-2873 (resume path)
**Current Code:**
```python
prd_path = Path(prd_path)
...
if resume:
    try:
        state = PipelineState.load()
    except FileNotFoundError:
        raise ConfigurationError(...)
```
**What Needs to Change:** After loading state on resume, override empty/missing prd_path:
```python
if resume:
    state = PipelineState.load()
    # Fix 14: Override empty/missing prd_path from saved state
    if not state.prd_path or not Path(state.prd_path).exists():
        if prd_path and Path(prd_path).exists():
            state.prd_path = str(prd_path)
            state.save()
```
Also fix in cli.py `_resume_async()` (line 531) which passes `state.prd_path` as the prd_path arg -- if state.prd_path is empty, this creates `Path("")` which triggers PermissionError.
**Risk:** LOW -- Defensive override.
**Dependencies:** None

---

## Issue 15: Cancel scope poisoning

**Severity:** P3
**File(s):** `C:\MY_PROJECTS\super-team\src\super_orchestrator\pipeline.py`
**Function:** `_run_pipeline_loop()` -- `_run_handler_isolated()` inner function
**Line(s):** 2951-2970
**Current Code:** Already handled with `cancel_scope_poisoned` flag and `_run_handler_isolated()` pattern.
**What Needs to Change:** Nothing. Already fixed.
**Risk:** N/A
**Dependencies:** None

---

## Issue 16: Schemathesis MCP auth-service failure

**Severity:** P3
**File(s):** `C:\MY_PROJECTS\super-team\src\super_orchestrator\pipeline.py`
**Function:** Contract registration phase
**Line(s):** 796-807 (`schemathesis_mcp_ok` fast-fail)
**Current Code:** Already handled with `schemathesis_mcp_ok` fast-fail flag.
**What Needs to Change:** Nothing. Already fixed.
**Risk:** N/A
**Dependencies:** None

---

## Issue 17: Contract validation failures for all 6 services

**Severity:** P2
**File(s):** `C:\MY_PROJECTS\super-team\src\architect\services\contract_generator.py`, `C:\MY_PROJECTS\super-team\src\super_orchestrator\pipeline.py`
**Function:** `generate_contract_stubs()` (contract_generator.py:271), `_register_single_contract()` (pipeline.py:994)
**Line(s):**
- contract_generator.py:301-303 -- where `"type"` and `"service_id"` are injected into spec
- pipeline.py:1008 -- where spec is passed to `validate_spec()` without stripping

**Current Code (contract_generator.py:301-303):**
```python
spec: dict[str, Any] = {
    "type": "openapi",           # EXTRA property not in OpenAPI schema
    "service_id": service.name,  # EXTRA property not in OpenAPI schema
    "openapi": "3.1.0",
    "info": { ... },
    "paths": {},
    "components": { "schemas": {} },
}
```

**Current Code (pipeline.py:1008):**
```python
validation = await validate_spec(spec=spec, type="openapi")
```

**Validation chain:** `validate_spec()` -> `openapi_validator.validate_openapi()` -> `openapi-spec-validator` library -> OpenAPI 3.1.0 JSON Schema (`unevaluatedProperties: false`) -> rejects `"type"` and `"service_id"` as unexpected top-level keys.

**What Needs to Change:** In `_register_single_contract()` (pipeline.py:1008), strip extra keys before validation:
```python
# Strip custom metadata keys before OpenAPI validation
clean_spec = {k: v for k, v in spec.items() if k not in ("type", "service_id")}
validation = await validate_spec(spec=clean_spec, type="openapi")
```
Also use `clean_spec` for the `create_contract()` call, or store the metadata separately.
**Risk:** LOW -- Removing 2 keys from the spec before validation.
**Dependencies:** None

---

## Issue 18: Preflight `check_env_vars()` FAILs without API key even when CLI available

**Severity:** P3
**File(s):** `C:\MY_PROJECTS\super-team\scripts\preflight.py`
**Function:** `check_env_vars()`
**Line(s):** 114-133
**Current Code:**
```python
def check_env_vars() -> str:
    status = CheckResult.OK
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if api_key:
        masked = api_key[:8] + "..." + api_key[-4:] if len(api_key) > 12 else "***"
        _print_check("ANTHROPIC_API_KEY", CheckResult.OK, f"Set ({masked})")
    else:
        _print_check("ANTHROPIC_API_KEY", CheckResult.FAIL, "Not set")
        status = CheckResult.FAIL
    ...
    return status
```
**What Needs to Change:** When ANTHROPIC_API_KEY is not set, check for Claude CLI before failing:
```python
else:
    cli_path = shutil.which("claude")
    if cli_path:
        _print_check("ANTHROPIC_API_KEY", CheckResult.WARN,
                      f"Not set, but Claude CLI at {cli_path} (will use --backend cli)")
        if status == CheckResult.OK:
            status = CheckResult.WARN
    else:
        _print_check("ANTHROPIC_API_KEY", CheckResult.FAIL, "Not set and no Claude CLI")
        status = CheckResult.FAIL
```
**Risk:** LOW -- Only changes diagnostic output.
**Dependencies:** None

---

## Issue 19: Reporting-service convergence still 0.0

**Severity:** P2 (safety net only)
**File(s):** `C:\MY_PROJECTS\super-team\src\super_orchestrator\pipeline.py`
**Function:** `_parse_builder_result()`
**Line(s):** 1729-1892 (5-level convergence fallback chain at 1775-1862)
**Current Code:** The fallback chain already exists and gives `min(0.5, source_file_count / 100.0)` for reporting-service (54 files -> 0.50).
**What Needs to Change:** No pipeline-side change needed. The root cause is in agent_team_v15's convergence checker not running for reporting-service (`requirements_checked: 0` in STATE.json). The pipeline's safety-net (0.50) is reasonable.
**Risk:** N/A (no change)
**Dependencies:** None

---

## Issue 20: Unclosed transport warnings at pipeline exit

**Severity:** P3
**File(s):** `C:\MY_PROJECTS\super-team\src\super_orchestrator\pipeline.py`
**Function:** `execute_pipeline()` or module-level
**Line(s):** 2897-2924 (try/except in execute_pipeline, no transport cleanup)
**Current Code:** No `finally` block that closes transports or suppresses warnings.
**What Needs to Change:** Add ResourceWarning filter for Windows `_ProactorBasePipeTransport`:
```python
import warnings
if sys.platform == "win32":
    warnings.filterwarnings("ignore", category=ResourceWarning,
                            message=".*_ProactorBasePipeTransport.*")
```
Place at module level (after imports) or in `execute_pipeline()` preamble.
**Risk:** LOW -- Only suppresses cosmetic warning.
**Dependencies:** None

---

## Issue 21: Builder timeout too long (7200s in config.yaml)

**Severity:** P2
**File(s):** `C:\MY_PROJECTS\ledgerpro-test\config.yaml`
**Function:** N/A (configuration)
**Line(s):** config.yaml line 13
**Current Code:**
```yaml
builder:
  max_concurrent: 3
  timeout_per_builder: 7200
  depth: exhaustive
```
**Code default (config.py line 26):** `timeout_per_builder: int = 1800`
**What Needs to Change:** Change `timeout_per_builder` from `7200` to `3600` in config.yaml. With STATE.json polling (Issue 4), the timeout only covers edge cases.
**Risk:** LOW -- Configuration change only.
**Dependencies:** Issue 4 (polling makes timeout less critical)

---

## Issue 22: Pipeline Overview shows "unknown" for pipeline/PRD

**Severity:** P3
**File(s):**
- `C:\MY_PROJECTS\super-team\src\super_orchestrator\cli.py` (callers)
- `C:\MY_PROJECTS\super-team\src\super_orchestrator\display.py` (function)
**Function:** `print_pipeline_header()` (display.py:44)
**Line(s):**
- display.py:44 -- `def print_pipeline_header(state: Any, tracker: Any = None, pipeline_id: str | None = None, prd_path: str | None = None)`
- cli.py:201 -- `print_pipeline_header(state.pipeline_id, str(prd_path))`
- cli.py:433-436 -- `print_pipeline_header("pending" if not resume_flag else "resuming", str(prd_path))`
- cli.py:479 -- `print_pipeline_header(state.pipeline_id, state.prd_path)`
- cli.py:525 -- `print_pipeline_header(state.pipeline_id, state.prd_path)`

**Current Code (display.py:44):**
```python
def print_pipeline_header(state: Any, tracker: Any = None, pipeline_id: str | None = None, prd_path: str | None = None) -> None:
    pid = pipeline_id or _get_attr(state, "pipeline_id", "unknown")
    prd = prd_path or _get_attr(state, "prd_path", "unknown")
```

When called as `print_pipeline_header(state.pipeline_id, str(prd_path))`:
- `state` gets the string `"pending"` (not a PipelineState)
- `tracker` gets the prd path string (not a PipelineCostTracker)
- `pipeline_id` and `prd_path` are None
- `_get_attr("pending", "pipeline_id", "unknown")` returns `"unknown"`

**What Needs to Change:** Fix all 4 call sites in cli.py to use keyword args:
```python
# Line 201
print_pipeline_header(pipeline_id=state.pipeline_id, prd_path=str(prd_path))
# Line 433-436
print_pipeline_header(pipeline_id="pending" if not resume_flag else "resuming", prd_path=str(prd_path))
# Line 479
print_pipeline_header(pipeline_id=state.pipeline_id, prd_path=state.prd_path)
# Line 525
print_pipeline_header(pipeline_id=state.pipeline_id, prd_path=state.prd_path)
```
**Risk:** LOW -- Pure argument naming fix.
**Dependencies:** None

---

## Issue 23: Docker Compose `version: "3.8"` appears in 6 places (not 5)

**Severity:** P3
**File(s):** `C:\MY_PROJECTS\super-team\src\integrator\compose_generator.py`
**Function:** `generate()` and `generate_compose_files()`
**Line(s):** 112, 528, 547, 556, 567, 578
**What Needs to Change:** Same fix as Issue 7 -- remove all 6 instances. Merged with Issue 7.
**Risk:** LOW
**Dependencies:** Same as Issue 7

---

## Issue 25: Fix pass needs `_is_fixable()` integration with `_has_fixable_violations()`

**Severity:** P1
**File(s):** `C:\MY_PROJECTS\super-team\src\super_orchestrator\pipeline.py`
**Function:** `_has_fixable_violations()` (line 3759), `run_fix_pass()` (line 2543)
**Line(s):**
- 3759-3787 -- `_has_fixable_violations()` decides whether to ENTER the fix loop
- 2660-2664 -- `run_fix_pass()` processes ALL violations without filtering

**Current Code (run_fix_pass, line 2660-2664):**
```python
violations_by_service: dict[str, list[ContractViolation]] = {}
for v in all_violations:
    svc = v.service or "unknown"
    violations_by_service.setdefault(svc, []).append(v)
```

**Current Code (_has_fixable_violations, line 3766):**
```python
_UNFIXABLE_PREFIXES = ("INTEGRATION-", "INFRA-", "DOCKER-", "BUILD-NOSRC")
```

**What Needs to Change:** Extract a shared `_is_fixable(v: dict) -> bool` function:
```python
def _is_fixable(v: dict[str, Any]) -> bool:
    _UNFIXABLE_PREFIXES = ("INTEGRATION-", "INFRA-", "DOCKER-", "BUILD-NOSRC")
    code = str(v.get("code", ""))
    message = str(v.get("message", "")).lower()
    if any(code.startswith(pfx) for pfx in _UNFIXABLE_PREFIXES):
        return False
    if code == "L1-FAIL" and any(kw in message for kw in ("docker", "dockerfile", "no source files")):
        return False
    return True
```
Use in both `_has_fixable_violations()` and `run_fix_pass()` (filter violations before grouping).
**Risk:** LOW -- Filtering logic, pure function.
**Dependencies:** Issue 11 (closely related)

---

## Supplementary Information

### accounts-service Build Artifacts

| File | Status | Path |
|------|--------|------|
| Dockerfile | EXISTS | `C:\MY_PROJECTS\super-team\.super-orchestrator\accounts-service\Dockerfile` (28 lines, multi-stage node:18-alpine) |
| tsconfig.json | EXISTS | `"strict": true` -- likely cause of TS compilation errors |
| package.json | EXISTS | `"build": "nest build"` -- NestJS CLI, TS ^5.3.3, TypeORM ^0.3.19 |

### Frontend Service Artifacts

| File | Status | Path |
|------|--------|------|
| Dockerfile | **MISSING** | `C:\MY_PROJECTS\super-team\.super-orchestrator\frontend\Dockerfile` -- DOES NOT EXIST |
| angular.json | EXISTS | Frontend is Angular-based |
| src/ | EXISTS | 73+ source files |
| dist/ | EXISTS | Built output exists |
| package.json | EXISTS | Has build scripts |

### agent_team_v15 Post-Orchestration Phases (cli.py)

| Phase | Line | Condition | Blocking Risk |
|-------|------|-----------|---------------|
| E2E Testing | 6451 | `config.e2e_testing.enabled` | LOW -- runs tests, can hang on app startup |
| Browser MCP Testing | 6766 | `config.browser_testing.enabled` | **HIGH** -- starts app on port, runs Playwright, can hang indefinitely |
| Verification | 7120 | `config.verification.enabled` | MEDIUM -- `asyncio.run()` at line 7156 = nested event loop |
| Final State Save | 7205-7211 | Always runs | LOW -- just writes STATE.json |

**Exit:** Function returns implicitly at line 7212. No `sys.exit(0)`. Process exits when Python's natural cleanup finishes.

### Contract Engine -- service_id/type Injection Chain

1. **Generated at:** `contract_generator.py:301-303` -- `"type": "openapi"` and `"service_id": service.name` added as top-level keys
2. **Stored at:** `pipeline.py:554` -- `atomic_write_json(registry_dir / "stubs.json", contract_stubs)` (full spec with extra keys)
3. **Loaded at:** `pipeline.py:699-716` -- stubs loaded from `stubs.json`
4. **Validated at:** `pipeline.py:1008` -- `validate_spec(spec=spec, type="openapi")` (extra keys still present)
5. **Validation fails at:** `openapi_validator.py:140-148` -- `openapi-spec-validator` rejects `"type"` and `"service_id"` as unevaluated properties
6. **Stored at:** `contract_store.py:71` -- `json.dumps(create.spec)` (extra keys persist in DB)

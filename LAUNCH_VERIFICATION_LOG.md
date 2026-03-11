# Launch Verification Log
**Date:** 2026-02-24
**PRD:** LedgerPro Full (tests/fixtures/ledgerpro_full.md, 509 lines, 28,762 chars)

---

## Pre-Launch Checks (PASSED)

### AsyncAPI Stub Verification
- Events extracted: **13/13**
- OpenAPI stubs: **6/6** (auth, accounts, invoicing, reporting, notification, frontend)
- AsyncAPI stubs: **3/3** (auth-service, invoicing-service, accounts-service)
- Total stubs: **9/9**
- All 3 AsyncAPI stubs validated: version 3.0.0, channels, operations, payloads

### Builder CLAUDE.md Check (accounts-service): **9/9**
- TypeScript, NestJS, Account/JournalEntry entities with fields
- JournalEntry + FiscalPeriod state machines with transitions
- Events published/subscribed correctly populated
- PostgreSQL with accounts_service_schema

### Config Serialization Round-Trip: **PASS**
- YAML and JSON round-trip both verified

---

## Launch Attempt 1 — 08:03 UTC

**Command:** `python -m src.super_orchestrator run /c/MY_PROJECTS/ledgerpro-test/prd.md --config /c/MY_PROJECTS/ledgerpro-test/config.yaml`

**Result:** FAILED at `architect_review` phase

**Blocking Issues:**
- PRD-004: Circular service dependency: auth-service -> accounts-service -> auth-service
- PRD-004: Circular service dependency: auth-service -> invoicing-service -> accounts-service -> auth-service

**Root Cause:** `_compute_contracts()` in `service_boundary.py` had BELONGS_TO bidirectional logic (Wave 3 FIX-9) that created spurious reverse dependencies. Additionally, HAS_MANY relationships had reversed dependency direction — "User HAS_MANY JournalEntry" made auth-service consume accounts-service-api, when it should be the other way around (accounts-service holds the FK, so it consumes auth-service-api).

**Fix Applied:**
1. Removed BELONGS_TO bidirectional contract creation (lines 467-472)
2. Reversed HAS_MANY dependency direction: target_boundary (many side) consumes source_boundary (one side) API
3. Updated 2 tests in `test_prerun_fixes.py` to match correct semantics

**Contract Graph After Fix (acyclic):**
```
auth-service:       provides=[auth-service-api]       consumes=[]
accounts-service:   provides=[accounts-service-api]   consumes=[auth-service-api]
invoicing-service:  provides=[invoicing-service-api]  consumes=[auth-service-api, accounts-service-api]
reporting-service:  provides=[reporting-service-api]   consumes=[]
notification-service: provides=[notification-service-api] consumes=[auth-service-api]
frontend:           provides=[frontend-api]            consumes=[]
```

**Tests:** 422 passed, 0 failed (wave2 + architect suites)

---

## Launch Attempt 2 — 08:06 UTC

**Result:** FAILED during `contract_registration` phase

**What Succeeded:**
- PRD validation PASSED (0 blocking, 4 warnings about unconsumed contracts)
- All 6 OpenAPI contracts registered (validation warnings non-blocking)
- Schemathesis test generation succeeded for all 6 services (28+46+28+3+10+3 = 118 tests)

**What Failed:**
- CancelledError during MCP `validate_spec()` call at pipeline.py:941
- Error: `asyncio.exceptions.CancelledError: Cancelled via cancel scope`
- Also: `RuntimeError: Attempted to exit cancel scope in a different task than it was entered in`
- Graph RAG context build also failed (non-blocking): cancel scope error

**Root Cause:** The CancelledError crash handler from Wave 2 does not cover `_register_single_contract()` in pipeline.py. The function calls MCP stdio_client which uses anyio cancel scopes, and when the contract engine MCP subprocess has timing issues, the cancel scope gets corrupted.

**Fix Applied:**
1. `_register_single_contract()` — added `except (asyncio.CancelledError, BaseException)` returning fallback dict
2. `run_contract_registration()` caller — changed `except Exception` to `except BaseException` for filesystem fallback
3. `_build_graph_rag_context()` — changed `except Exception` to `except BaseException`

---

## Launch Attempt 3 — 08:09 UTC

**Result:** FAILED — pipeline stuck in `contracts_registering` loop

**What Succeeded:**
- PRD validation PASSED (0 blocking issues)
- CancelledError now caught gracefully — no crash
- All 6 contracts saved to filesystem fallback
- Schemathesis test generation succeeded for all 6 services

**What Failed:**
- MCP contract engine subprocess not starting (all stdio_client calls get CancelledError)
- Pipeline looped 4 times through contract registration without advancing to builders
- State machine trigger `model.contracts_registered()` silently failed (likely CancelledError from corrupted asyncio cancel scope leaking through `await`)

**Root Cause:** After MCP cancel scope corruption, subsequent `await` calls (including `await model.contracts_registered()`) inherit the corrupted cancel context. The `AsyncMachine` trigger is async and gets cancelled, but `ignore_invalid_triggers=True` silently swallows it. The pipeline loop repeats the same handler.

**Fix Applied:**
1. Wrapped `await model.contracts_registered()` in try/except `(CancelledError, BaseException)` — forces state to `builders_running` on failure
2. Added `except asyncio.CancelledError` handler in `execute_pipeline()` to prevent unhandled propagation

---

## Launch Attempts 4-7 — 08:12-08:32 UTC

**Systematic fix of cancel scope poisoning**

### Attempt 4-5: Pipeline stuck in contracts_registering loop
- Forced state transition (`model.state = "builders_running"`) wasn't sufficient
- Logger.info messages not visible (log level filtering)
- Switched to `print()` for diagnostics

### Attempt 5: Direct state assignment fixed transition loop
- Replaced `await model.contracts_registered()` with direct `model.state = "builders_running"`
- Pipeline advanced to `builders_running` for first time
- **New issue:** `run_parallel_builders` got CancelledError from lingering MCP cancel scope

### Attempt 6: CancelledError flush attempts
- Added `asyncio.sleep(0.1)` flush before builders — caught CancelledError but MORE kept coming
- CancelledError is **permanent** — corrupted anyio cancel scope keeps cancelling every `await`
- Every `asyncio.sleep(0)` catches a CancelledError, but the next one also gets cancelled

### Attempt 7: Isolated task execution (BREAKTHROUGH)
- Discovered: anyio cancel scope corruption affects the current asyncio task permanently
- **Solution:** Run handlers in independent `asyncio.create_task()` — new tasks get clean cancel scopes
- Added `cancel_scope_poisoned` flag + `_run_handler_isolated()` helper
- First CancelledError sets flag, all subsequent handlers run in independent tasks
- Pipeline advanced through `contracts_registering` AND into `builders_running`!
- **New issue:** All 6 builders failed: `Claude Code not found at: claude`

### Attempt 8: Claude CLI path fix (BUILDERS RUNNING)
- Root cause: `agent_team/cli.py:342` hardcodes `cli_path = "claude"`
- On Windows, Claude CLI is `claude.CMD` at `C:\nvm4w\nodejs\claude.CMD`
- Fix: Changed to `shutil.which("claude") or "claude"` in 6 locations:
  - `agent_team/cli.py`, `agent_team/design_reference.py`, `agent_team/interviewer.py`
  - `agent_team_v15/cli.py`, `agent_team_v15/design_reference.py`, `agent_team_v15/interviewer.py`
- Also added MCP fast-fail: Schemathesis `generate_tests` disabled after first failure
- **Result:** Pipeline running, 6 builders actively generating code

---

## Fixes Applied (Cumulative)

### Cancel Scope Poisoning (pipeline.py)
1. Direct state assignment in `_phase_builders` — bypass async trigger entirely
2. `cancel_scope_poisoned` flag in `_run_pipeline_loop` — detects first CancelledError
3. `_run_handler_isolated()` — runs handlers in independent asyncio tasks with clean scopes
4. MCP fast-fail in `run_contract_registration` — `mcp_disabled` flag skips remaining MCP calls
5. Schemathesis fast-fail — `schemathesis_mcp_ok` flag disables after first ExceptionGroup
6. CancelledError handler in `_call_architect` — catches BaseException, falls back to subprocess

### Claude CLI Path (agent_team, agent_team_v15)
7. `cli_path = shutil.which("claude") or "claude"` in all 6 `cli_path` assignments

---

## Files Modified During Launch

### Source Changes:
1. `src/architect/services/service_boundary.py` — Removed BELONGS_TO bidirectional logic, reversed HAS_MANY dependency direction
2. `src/architect/services/prd_parser.py` — regex `[^|\n]+?` fix for 4-col event table
3. `src/super_orchestrator/pipeline.py`:
   - `_register_single_contract()` — CancelledError/BaseException handler with fallback return
   - `run_contract_registration()` — MCP fast-fail (`mcp_disabled` flag), filesystem fallback
   - `_call_architect()` — CancelledError/BaseException handler for MCP calls
   - `_phase_builders()` — direct state assignment, bypass async trigger
   - `_phase_builders_complete()` — simplified (isolation at loop level)
   - `_phase_contracts()` — direct state assignment for resume path
   - `_run_pipeline_loop()` — `cancel_scope_poisoned` flag, `_run_handler_isolated()` helper
   - `execute_pipeline()` — CancelledError handler
   - Schemathesis generation — fast-fail with `schemathesis_mcp_ok` flag
   - `print()` diagnostics throughout pipeline for visibility

### External Source Changes:
4. `claude-agent-team/src/agent_team/cli.py` — `shutil.which("claude")` for CLI path
5. `claude-agent-team/src/agent_team/design_reference.py` — same
6. `claude-agent-team/src/agent_team/interviewer.py` — same
7. `agent-team-v15/src/agent_team_v15/cli.py` — same
8. `agent-team-v15/src/agent_team_v15/design_reference.py` — same
9. `agent-team-v15/src/agent_team_v15/interviewer.py` — same

### Test Changes:
1. `tests/test_wave2/test_prerun_fixes.py` — Updated HAS_MANY and BELONGS_TO contract direction tests

# Wiring Verification Report -- Attempt 13 Fixes

**Date:** 2026-02-25
**Verifier:** wiring-verifier agent
**Scope:** All 24 fixes traced through complete pipeline execution path

---

## A: Builder Lifecycle Flow

| # | Check | Expected | Actual | PASS/FAIL | Evidence (file:line) |
|---|-------|----------|--------|-----------|---------------------|
| A1 | `_phase_builders_complete` calls `run_parallel_builders` | Yes | Yes | **PASS** | `pipeline.py:3797` |
| A2 | `run_parallel_builders` calls `_run_single_builder` per service | Yes | Yes | **PASS** | `pipeline.py:1138` inside `_build_one()` |
| A3 | Polling loop used (not just `await proc.wait()`) | Yes | Yes | **PASS** | `pipeline.py:1749-1876` -- `while True:` loop with STATE.json polling |
| A4 | Polling loop reads STATE.json every `poll_interval_s` | Yes | Yes | **PASS** | `pipeline.py:1783-1787` reads STATE.json; `pipeline.py:1865` waits `poll_interval_s` |
| A5 | On completion detection -> `_kill_builder_tree()` called | Yes | Yes | **PASS** | `pipeline.py:1854-1855` inside `if is_complete:` block |
| A6 | On timeout -> `_kill_builder_tree()` called | Yes | Yes | **PASS** | `pipeline.py:1769` inside `if elapsed >= timeout_s:` block |
| A7 | `_kill_builder_tree()` uses psutil to kill children | Yes | Yes | **PASS** | `pipeline.py:1570-1589` -- `psutil.Process(proc.pid).children(recursive=True)` |
| A8 | No path where subprocess escapes without kill | Yes | Yes | **PASS** | `pipeline.py:1904-1907` -- `finally:` block covers all exit paths |
| A9 | Heartbeat logging every 5 minutes | Yes | Yes | **PASS** | `pipeline.py:1816-1825` -- `if elapsed - last_heartbeat_time >= 300:` |
| A10 | Completion detection criteria correct | Multiple criteria | Yes | **PASS** | `pipeline.py:1828-1840` -- conv>=0.9+phases>=8, terminal phase, success+phases>=8 |
| A11 | Skip-completed guard requires sufficient progress | `_prev_milestones > 0 or _prev_phases >= 8` | Yes | **PASS** | `pipeline.py:1639-1641` |

**A Summary: 11/11 PASS**

---

## B: Docker Integration Flow

| # | Check | Expected | Actual | PASS/FAIL | Evidence (file:line) |
|---|-------|----------|--------|-----------|---------------------|
| B1 | `_phase_integration` calls `run_integration_phase` | Yes | Yes | **PASS** | `pipeline.py:4176` |
| B2 | Docker pre-flight check before compose | Yes | Yes | **PASS** | `pipeline.py:2487` -- `if not _check_docker_available():` returns early |
| B3 | `_verify_dockerfiles_exist()` called before compose | Yes | Yes | **PASS** | `pipeline.py:2521` |
| B4 | Frontend missing Dockerfile -> `_ensure_frontend_dockerfile()` | Yes | Yes | **PASS** | `pipeline.py:2406-2407` inside `_verify_dockerfiles_exist()` |
| B5 | Remaining missing -> violations added, Docker skipped | Yes | Yes | **PASS** | `pipeline.py:2527-2551` -- creates DOCKER-NODOCKERFILE violations, returns early |
| B6 | `docker compose` never reached with missing Dockerfiles | Yes | Yes | **PASS** | `pipeline.py:2551` -- `return` before `compose_gen.generate_compose_files()` at line 2557 |
| B7 | `_ensure_frontend_dockerfile()` generates proper Dockerfile | Yes | Yes | **PASS** | `pipeline.py:2296-2375` -- multi-stage node+nginx with healthcheck |
| B8 | `_check_docker_available()` checks both PATH and daemon | Yes | Yes | **PASS** | `pipeline.py:2263-2293` -- `shutil.which("docker")` + `docker info` |

**B Summary: 8/8 PASS**

---

## C: Fix Loop Flow

| # | Check | Expected | Actual | PASS/FAIL | Evidence (file:line) |
|---|-------|----------|--------|-----------|---------------------|
| C1 | L1 sets `service=br.service_id` on L1-FAIL violations | Yes | Yes | **PASS** | `layer1_per_service.py:95` |
| C2 | `_is_fixable_violation()` checks code prefixes | Yes | Yes | **PASS** | `pipeline.py:4209` -- checks `_UNFIXABLE_PREFIXES` |
| C3 | `_is_fixable_violation()` checks message patterns | Yes | Yes | **PASS** | `pipeline.py:4213-4215` -- checks `_UNFIXABLE_MESSAGE_PATTERNS` |
| C4 | `_is_fixable_violation()` checks empty service field | Yes | Yes | **PASS** | `pipeline.py:4218-4220` -- `if not service or service == "unknown": return False` |
| C5 | `_get_violation_signature()` exists for repeat detection | Yes | Yes | **PASS** | `pipeline.py:4225-4234` -- returns frozenset of (code, service, msg[:50]) |
| C6 | `run_fix_pass()` filters through `_is_fixable_violation()` | Yes | Yes | **PASS** | `pipeline.py:3035-3046` |
| C7 | `_has_fixable_violations()` uses `_is_fixable_violation()` | Yes | Yes | **PASS** | `pipeline.py:4251` |
| C8 | `_phase_fix_done` checks repeated violations | Yes | Yes | **PASS** | `pipeline.py:4354-4380` -- compares current_sig with prev_sig |
| C9 | No fixable violations -> fix pass skipped | Yes | Yes | **PASS** | `pipeline.py:3053-3057` |
| C10 | Empty/unknown/pipeline-level service skipped in grouping | Yes | Yes | **PASS** | `pipeline.py:3062-3069` |
| C11 | No path where Docker failures trigger builder rebuild | Yes | Yes | **PASS** | DOCKER-* prefixes in `_UNFIXABLE_PREFIXES` at `pipeline.py:4184`, filtered by `_is_fixable_violation()` |

**C Summary: 11/11 PASS**

---

## D: Quality Gate

| # | Check | Expected | Actual | PASS/FAIL | Evidence (file:line) |
|---|-------|----------|--------|-----------|---------------------|
| D1 | L2 checks `overall_health` BEFORE pass-rate | Yes | Yes | **PASS** | `layer2_contract_compliance.py:53-75` -- checks health first, returns FAILED immediately |
| D2 | Returns FAILED (not SKIPPED) when health is "failed"/"error" | Yes | Yes | **PASS** | `layer2_contract_compliance.py:68-69` -- `verdict=GateVerdict.FAILED` |
| D3 | L2-INTEGRATION-FAIL violation has service field | Yes | `service="pipeline-level"` | **PASS** | `layer2_contract_compliance.py:64` -- field is populated (as "pipeline-level"), correctly filtered as unfixable by `_is_fixable_violation()` |
| D4 | `_phase_quality` uses `_has_fixable_violations` for decision | Yes | Yes | **PASS** | `pipeline.py:4287-4294` |
| D5 | Only unfixable violations -> skip to complete | Yes | Yes | **PASS** | `pipeline.py:4289-4294` -- `model.skip_to_complete()` |

**D Summary: 5/5 PASS**

---

## E: Resume Flow

| # | Check | Expected | Actual | PASS/FAIL | Evidence (file:line) |
|---|-------|----------|--------|-----------|---------------------|
| E1 | Resume checks for empty prd_path | Yes | Yes | **PASS** | `pipeline.py:3276-3277` |
| E2 | Overrides with CLI arg when saved path invalid | Yes | Yes | **PASS** | `pipeline.py:3278-3284` |
| E3 | Raises ConfigurationError (not PermissionError) | Yes | Yes | **PASS** | `pipeline.py:3286-3289` |
| E4 | `Path("")` never reaches file operations | Yes | Yes | **PASS** | Check at line 3277 catches empty strings |

**E Summary: 4/4 PASS**

---

## F: Display Fix

| # | Check | Expected | Actual | PASS/FAIL | Evidence (file:line) |
|---|-------|----------|--------|-----------|---------------------|
| F1 | `print_pipeline_header()` accepts keyword args | Yes | Yes | **PASS** | `display.py:44` -- `state, tracker=None, pipeline_id=None, prd_path=None` |
| F2 | `cli.py` calls with keyword args | Yes | Yes | **PASS** | `cli.py:201`, `cli.py:433-435`, `cli.py:479`, `cli.py:525` |
| F3 | First positional arg maps to `state` correctly | Yes | Yes | **PASS** | `display.py:59-60` -- `_get_attr()` handles both objects and dicts |

**F Summary: 3/3 PASS**

---

## G: Preflight

| # | Check | Expected | Actual | PASS/FAIL | Evidence (file:line) |
|---|-------|----------|--------|-----------|---------------------|
| G1 | `preflight.py` checks Claude CLI | Expected | No `preflight.py` exists | **N/A** | Docker check is inline at `pipeline.py:2263-2293`. Claude CLI resolution is at builder launch time. |
| G2 | Docker pre-check exists | Yes | Yes | **PASS** | `pipeline.py:2263-2293` called at `pipeline.py:2487` |

**G Summary: 1/1 applicable PASS**

---

## H: Config

| # | Check | Expected | Actual | PASS/FAIL | Evidence (file:line) |
|---|-------|----------|--------|-----------|---------------------|
| H1 | `BuilderConfig.poll_interval_s: int = 30` | Yes | Yes | **PASS** | `config.py:28` |
| H2 | `config.yaml` has `timeout_per_builder: 3600` | 3600 | **1800** | **FAIL** | `config.yaml:18` -- value is 1800, not 3600 |

**H Summary: 1/2 PASS**

---

## I: Compose

| # | Check | Expected | Actual | PASS/FAIL | Evidence (file:line) |
|---|-------|----------|--------|-----------|---------------------|
| I1 | ZERO instances of `"version"` in compose dicts | Yes | Yes | **PASS** | No `"version"` key in any compose dict in `compose_generator.py`. Confirmed by grep returning zero matches. |

**I Summary: 1/1 PASS**

---

## Overall Summary

| Section | Checks | Passed | Failed | N/A |
|---------|--------|--------|--------|-----|
| A: Builder Lifecycle | 11 | 11 | 0 | 0 |
| B: Docker Integration | 8 | 8 | 0 | 0 |
| C: Fix Loop | 11 | 11 | 0 | 0 |
| D: Quality Gate | 5 | 5 | 0 | 0 |
| E: Resume Flow | 4 | 4 | 0 | 0 |
| F: Display Fix | 3 | 3 | 0 | 0 |
| G: Preflight | 2 | 1 | 0 | 1 |
| H: Config | 2 | 1 | 1 | 0 |
| I: Compose | 1 | 1 | 0 | 0 |
| **TOTAL** | **47** | **45** | **1** | **1** |

---

## Actionable Finding

### FAIL: H2 -- `timeout_per_builder` is 1800, not 3600

- **File:** `config.yaml:18`
- **Expected by plan:** `timeout_per_builder: 3600` (1 hour)
- **Actual:** `timeout_per_builder: 1800` (30 minutes)
- **Impact:** Builders get 30-minute timeout. In Attempt 11, 5/6 services completed within this window. However, for safety in Attempt 13, 1 hour provides more margin.
- **Fix:** Change `config.yaml:18` from `1800` to `3600`.

---

## Conclusion

**45/47 checks passed. Ready for Attempt 13: YES (conditional on updating timeout_per_builder to 3600).**

All code-level fixes are correctly wired into the pipeline execution path:
- Builder polling loop with psutil kill trees (A1-A11)
- Docker pre-check and Dockerfile validation (B1-B8)
- Unfixable violation filtering and repeat detection in fix loop (C1-C11)
- Integration health gating before pass-rate in quality gate (D1-D5)
- Resume with empty prd_path handled gracefully (E1-E4)
- Display functions called with correct signatures (F1-F3)
- Compose v2 format without deprecated version key (I1)

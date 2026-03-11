# Super-Team 100K LOC Capability Assessment

> **Generated:** 2026-03-11 | **Methodology:** 7 parallel code investigations across architect, pipeline, builder, integrator, and agent-team-v15 codebases | **Scope:** Can the super-team produce 5 × 100K LOC services?

---

## Executive Answer

### CONDITIONALLY YES

The super-team **can** produce 5 × 100K LOC services (500K+ total), but **not with current default settings**. The builder engine (agent-team-v15) has **proven** 104K LOC capability (Bayan POC: 773 files, .NET 8/Angular 18, ~4 hours). The orchestrator architecture supports it — session rotation via milestone isolation prevents context overflow, PRD chunking handles large specs, and the architect has no hardcoded limits on service scope.

**3 critical blockers** must be addressed (all are config/wiring changes, not architectural redesigns):

1. **Builder timeout: 30 min → 5 hours** (config change, 1 line)
2. **Stall timeout: 10 min → 60 min** (config change, 1 line)
3. **Builder depth: "thorough" → "exhaustive"** (config change, 1 line)

**2 high-priority bugs** affect all builds (not just 100K):

4. **Init-db SQL never called** — all backend services fail at Docker startup
5. **Health check grace period: 30s → 90s** — large services killed before ready

**1 feature gap** blocks .NET specifically:

6. **.NET stack detection silently downgrades to Python** — C# services receive Python builder instructions

With these 6 fixes (estimated 2-4 hours for the config changes, 6-9 hours if .NET support included), the pipeline can produce 5 × 100K LOC services.

---

## Constraint Map

| # | Constraint | Current Value | Required for 100K/service | Blocker? | Fix Effort | Code Location |
|---|-----------|--------------|--------------------------|----------|-----------|---------------|
| 1 | **Builder timeout** | 1800s (30 min) | 18000s (5 hrs) | **YES — CRITICAL** | 1 line | `config.py:26` |
| 2 | **Stall timeout (building)** | 600s (10 min) | 3600s (60 min) | **YES — CRITICAL** | 1 line | `config.py:29` |
| 3 | **Builder depth** | "thorough" | "exhaustive" | **YES — CRITICAL** | 1 line | `config.py:27` |
| 4 | **Planning phase stall** | 2700s (45 min) | 5400s (90 min) | HIGH | 1 line | `pipeline.py:2373` |
| 5 | **Init-db SQL call** | Never invoked | Must invoke before Docker up | HIGH (all builds) | 5 lines | `pipeline.py:~2550` |
| 6 | **Health check grace** | 30s | 90s | HIGH (all builds) | 1 line | `compose_generator.py:340` |
| 7 | **.NET stack detection** | Falls through to "python" | Detect "csharp"/"c#" | YES (for .NET) | 3 lines | `pipeline.py:1624-1640` |
| 8 | **.NET builder instructions** | Missing | Full ASP.NET/EF Core guide | YES (for .NET) | ~80 lines | `pipeline.py:1491-1621` |
| 9 | **.NET Dockerfile template** | Missing | dotnet SDK→Runtime multi-stage | YES (for .NET) | ~30 lines | `compose_generator.py:393-486` |
| 10 | Config.yaml PRD content | Full PRD (untruncated) | Full PRD is correct | NO | — | `pipeline.py:2263-2268` |
| 11 | CLAUDE.md size | ~30-56 KB (backend) | ~67-88 KB (35 entities) | NO | — | `pipeline.py:1643-2142` |
| 12 | Context window budget | 200K tokens | ~44K used (22%), 156K available | NO | — | — |
| 13 | Completion detection | conv≥0.9 + phases≥8 | Works correctly for large builds | NO | — | `pipeline.py:2446-2458` |
| 14 | Max concurrent builders | 3 | 2-3 (acceptable) | NO | — | `config.py:25` |
| 15 | RAM budget | 4.5 GB | 2.9 GB needed (5 svc + infra) | NO | — | `compose_generator.py:14` |
| 16 | Entity count per service | No limit | No limit needed | NO | — | `service_boundary.py` |
| 17 | Contract truncation | No limit in pipeline | Should add 50-endpoint cap | LOW | 5 lines | `pipeline.py:1973-1986` |
| 18 | Cross-service standards | 38 KB (all services) | Could filter by type | LOW | 20 lines | `cross_service_standards.py` |

---

## Investigation 1: Architect Scoping — NO BLOCKERS

### How Service Count Is Determined

The architect uses a **4-tier hierarchical fallback** (`service_boundary.py:264-409`):

```
STEP 0: Explicit Services (Technology Stack Table)
        Trigger: len(parsed.explicit_services) >= 3
        → Create exactly N services from table

STEP 1: Explicit Bounded Contexts (Section Headings)
        Trigger: parsed.bounded_contexts is non-empty
        → One ServiceBoundary per context heading

STEP 2: Aggregate Root Discovery (Relationship Graph)
        Trigger: OWNS relationships found
        → One service per aggregate root + owned children

STEP 3: Relationship-Based Assignment (Proximity)
        → Assigns remaining entities to existing boundaries

STEP 4: Monolith Fallback
        Trigger: No boundaries created
        → Single service with ALL entities
```

### Key Findings

1. **No hardcoded service count limit.** If PRD declares 5 large services in its Technology Stack table, architect creates exactly 5.

2. **No entity-per-service limit.** A service can own 1, 30, 100+ entities. Only validation: each service must own ≥1 entity (`service_boundary.py:141-150`).

3. **No endpoint-per-service limit.** Endpoints aren't tracked at architect stage — that's the Contract Engine's job.

4. **PRD controls decomposition.** If PRD declares 3 bounded contexts, architect creates 3 services. If PRD has no structure, monolith fallback creates 1 service.

5. **LOC estimation is a heuristic only** (`service_boundary.py:557-559`): `estimated_loc = entity_count * 500`, clamped to `[100, 200_000]`. Does NOT validate or constrain service size.

### For 5 × 100K LOC

Write the PRD with a Technology Stack table listing exactly 5 services. The architect will respect it without splitting or merging. Each service can own 30+ entities. No changes needed.

---

## Investigation 2: Builder Config — NO BLOCKERS

### What Each Builder Receives

| Component | Source | Size (SupplyForge) | Size (100K service) |
|-----------|--------|-------------------|-------------------|
| `prd_input.md` | Full PRD, untruncated | 66.6 KB | 200-500 KB |
| `builder_config.json` | Service metadata + entities | 0.8-65 KB | 10-50 KB |
| `.claude/CLAUDE.md` | Builder instructions + standards | 30-53 KB | 67-88 KB |
| `contracts/` directory | OpenAPI/AsyncAPI specs | 5-20 KB | 20-50 KB |

### Key Findings

1. **No size limits on any config component.** No MAX_SIZE, no TRUNCATE, no validation gates (`pipeline.py:431-757`).

2. **Full PRD passed to every builder** (`pipeline.py:2263-2268`). No service-specific extraction. Written to disk (not CLI arg), so no Windows 32K limit issue.

3. **Frontend gets ALL entities** (`pipeline.py:536-546`), backend gets only owned entities (`pipeline.py:548-569`).

4. **Entity ownership often empty.** In SupplyForge, backend services received 0 entities because `owning_service` field wasn't populated by architect. This is a data flow gap, not a size limit.

5. **Graph RAG context always empty** (`config.py:67`, 2000-token soft budget). Context generation apparently broken.

### For 5 × 100K LOC

No changes needed. A 500KB PRD with 35 entities per service will flow through without truncation. Total disk overhead: ~2.5 MB per service × 5 = 12.5 MB. Negligible.

---

## Investigation 3: CLAUDE.md & Context Window — NO BLOCKERS

### Context Window Budget (200K tokens)

| Component | Tokens (typical) | Tokens (35-entity service) | % of 200K |
|-----------|------------------|---------------------------|-----------|
| System prompt + agent overhead | 13,000 | 13,000 | 6.5% |
| CLAUDE.md | 7,500-13,250 | 16,825-21,825 | 8.4-10.9% |
| PRD (on disk, loaded as needed) | 4,000-8,000 | 8,000-16,500 | 4-8% |
| Config + contracts | 2,000-5,000 | 3,000-5,000 | 1.5-2.5% |
| **Total initial context** | **26,500-39,250** | **40,825-56,325** | **20.4-28.2%** |
| **Available for code generation** | **160,750-173,500** | **143,675-159,175** | **71.8-79.6%** |

### Critical Insight: Session Rotation via Milestones

The builder does NOT hold 100K LOC in a single context window. Agent-team-v15 uses **milestone-based phase isolation**:

- Each milestone gets a **fresh `ClaudeSDKClient` session** (`cli.py:1312-1328`)
- Milestone REQUIREMENTS.md: 8-11 KB (NOT full PRD)
- Predecessor context: compressed summaries (2-3 KB per completed milestone)
- Per-session context: ~30 KB (well under 200K limit)
- 100K LOC ÷ 10 milestones = ~10K LOC per session

**Context overflow is architecturally impossible** with the milestone system.

### CLAUDE.md Size Breakdown (35-entity service)

| Component | Size | Source |
|-----------|------|--------|
| Service header + tech stack | 6.5 KB | `pipeline.py:1697-1791` |
| Entity schemas (35 × 200 chars) | 7.0 KB | `pipeline.py:1809-1843` |
| State machines (7 × 400 chars) | 2.8 KB | `pipeline.py:1845-1876` |
| Events (28 × 60 chars + hints) | 4.0 KB | `pipeline.py:1888-1950` |
| Contracts (own + consumed) | 5.0-25.0 KB | `pipeline.py:1948-1986` |
| Implementation notes + misc | 3.0 KB | `pipeline.py:2002-2130` |
| **Cross-service standards** | **38.0 KB** | `cross_service_standards.py:832-870` |
| **TOTAL** | **66.3-86.3 KB** | |

### For 5 × 100K LOC

No changes needed. Context budget allows 72-80% for code generation (143K-159K tokens). Each milestone session handles ~10K LOC independently. The 38 KB cross-service standards are redundant across services but not a blocker.

**Optional optimization:** Add contract endpoint truncation at `pipeline.py:1973-1986` (cap at 50 endpoints per consumed service). Saves 5-15 KB for heavily-connected services.

---

## Investigation 4: Builder Subprocess — 3 CRITICAL BLOCKERS

### Blocker #1: Builder Timeout (30 min)

| Metric | Current | Required | Gap |
|--------|---------|----------|-----|
| `timeout_per_builder` | 1800s (30 min) | 18000s (5 hrs) | **10× too short** |
| Location | `config.py:26` | Same | 1-line change |

**Evidence:** Bayan POC took ~4 hours for 104K LOC. The pipeline kills builders at 30 minutes.

**Fix:**
```python
# config.py:26
timeout_per_builder: int = 18000  # 5 hours for large services
```

### Blocker #2: Stall Timeout — Building Phase (10 min)

| Metric | Current | Required | Gap |
|--------|---------|----------|-----|
| `stall_timeout_s` | 600s (10 min) | 3600s (60 min) | **6× too short** |
| Location | `config.py:29` | Same | 1-line change |

**Evidence:** Large builds have 10+ minute gaps during compilation, test execution, and complex planning phases. Current stall detector kills active builders.

**Mitigation exists:** CPU-based safety check at `pipeline.py:2542-2558` — if process CPU > 5%, stall timer resets. But this requires `psutil` to be installed.

**Fix:**
```python
# config.py:29
stall_timeout_s: int = 3600  # 60 min for large services
```

### Blocker #3: Builder Depth ("thorough" vs "exhaustive")

| Metric | Current | Required | Gap |
|--------|---------|----------|-----|
| `depth` | "thorough" | "exhaustive" | Wrong default |
| Location | `config.py:27` | Same | 1-line change |

**Evidence:** Bayan used `--depth exhaustive` (auto-set by `--prd` flag in standalone CLI, `cli.py:5012-5014`). This enables:
- 10-11 parallel analyzer agents (vs 5-6 for "thorough")
- PRD chunking for specs > 80KB (`config.py:334-335`)
- Deeper convergence cycles

The super-team hardcodes `depth="thorough"` and passes it via `--depth thorough` (`pipeline.py:2330-2335`), bypassing the `--prd`-based auto-override.

**Fix:**
```python
# config.py:27
depth: str = "exhaustive"
```

### Non-Blocker: Planning Phase Stall (45 min)

| Metric | Current | Required | Status |
|--------|---------|----------|--------|
| Planning phase timeout | `max(stall_timeout_s, 2700)` = 2700s | 5400s (90 min) | HIGH but not critical |
| Location | `pipeline.py:2373` | Same | 1-line change |

For a 35-entity service, initial planning could take 60-90 minutes. Current 45-minute limit is tight.

### Non-Blocker: Completion Detection

Completion logic (`pipeline.py:2446-2458`) is well-designed:
```python
is_complete = (
    (conv >= 0.9 and (phases >= 8 or milestones >= 3))
    or current_phase in ("convergence_complete", "complete", "done", "finished")
    or (success and (phases >= 8 or milestones >= 3))
)
```

For a 50-phase build: at phase 8, convergence is ~0.5 → won't trigger. Correctly waits until both convergence and phase count are satisfied. **No false early termination.**

### Non-Blocker: Stall Recovery

Stall-killed builders with ≥3 completed milestones are treated as partial successes (`pipeline.py:2598-2627`). Skip-completed guard reuses their output on retry (`pipeline.py:2217-2256`). **Graceful degradation works.**

---

## Investigation 5: Bayan Build — PROOF OF 100K LOC

### What Bayan Achieved

| Metric | Value |
|--------|-------|
| Total source files | 773 (607 .cs, 100+ .ts) |
| PRD size | 111 KB (BAYAN_SPECIFICATIONS.md) |
| Duration | ~4 hours (including 30-min subscription pause) |
| Milestones | 7 sequential |
| Depth | exhaustive (auto-set by `--prd` flag) |
| Backend | .NET 8 Clean Architecture |
| Frontend | Angular 18 standalone components |
| Controllers | 17 |
| Database tables | 32 |
| Feature modules | 16+ |

### How It Handled 111KB PRD Without Context Overflow

**NOT session rotation. Milestone-based phase isolation:**

1. **PRD Chunking:** 111KB → 66 chunks (threshold: 80KB, max chunk: 20KB) (`prd_chunking.py:112-160`)
2. **Parallel Analysis:** 11 concurrent analyzer agents processed chunks simultaneously
3. **Per-Milestone REQUIREMENTS.md:** Each milestone gets focused 8-11 KB requirements (not full PRD)
4. **Per-Agent Context:** ~30 KB per agent (REQUIREMENTS.md + prompts + references)
5. **Compressed Predecessors:** Completed milestones represented as 2-3 KB summaries (`cli.py:705-739`)

### Can Super-Team Replicate?

**YES — with depth change only.** All mechanisms inherited:

| Mechanism | Inherited? | Evidence |
|-----------|-----------|----------|
| PRD chunking | ✅ Yes | Same agent-team binary; threshold applies |
| Milestone structure | ✅ Yes | Agent-team creates milestones automatically |
| Phase isolation | ✅ Yes | Each milestone gets focused REQUIREMENTS.md |
| Parallel agents | ✅ Yes | `scheduler.max_parallel_tasks` inherited |
| Convergence | ✅ Yes | Agent-team's config applies |
| Context scoping | ✅ Yes | `enable_context_scoping` inherited |
| Depth flag | ⚠️ Passed but wrong default | `pipeline.py:2330-2335` passes `--depth thorough` |

---

## Investigation 6: Docker Infrastructure — 2 HIGH-PRIORITY BUGS

### RAM Budget: FITS COMFORTABLY

```
5 Large Services:
  Traefik:      256 MB
  PostgreSQL:   512 MB
  Redis:        256 MB
  5 × App:    1,920 MB (5 × 384 MB)
  ─────────────────────
  TOTAL:      2,944 MB (2.9 GB)
  BUDGET:     4,500 MB (4.5 GB)
  HEADROOM:   1,556 MB (35%)
```

**Fewer, larger services actually reduce infrastructure overhead** (5 containers vs 10+).

### Bug #1: Init-DB SQL Never Called (CRITICAL)

**`ComposeGenerator.generate_init_sql()` exists** (`compose_generator.py:605-704`) and correctly generates per-service database creation SQL. **But it's never invoked** anywhere in the pipeline.

PostgreSQL mounts `./init-db:/docker-entrypoint-initdb.d:ro` (`compose_generator.py:209`), but the init-db directory is never created.

**Impact:** All backend services fail at startup — `database "xxx" does not exist`.

**Fix location:** `pipeline.py` in `run_integration_phase()`, before Docker compose up (~line 2550):
```python
compose_gen.generate_init_sql(output_dir, services, entities_by_service=entities_map)
```

### Bug #2: Health Check Grace Period Too Short

**Current:** `start_period: 30s` (`compose_generator.py:340`)

**Problem:** Large services with 35+ entity migrations take 40-60s to start. Service killed before ready.

**Fix:** Change to `start_period: "90s"` in `_generate_healthcheck()`.

### No Per-Service File Count Limits

The compose generator iterates services without file count validation. A service with 800+ files (like Bayan) builds without issues.

### No Docker Build Timeout

Individual `RUN` commands in Dockerfiles have no timeout. The entire `docker compose up --build` is bounded only by the builder subprocess timeout. Since Docker builds happen AFTER code generation (in a separate phase), they're not constrained by the builder timeout.

### Dockerfile Templates Available

| Stack | Template | Lines | Status |
|-------|----------|-------|--------|
| Frontend (Angular/React/Vue) | node:20-slim → nginx:stable-alpine | `compose_generator.py:404-442` | ✅ |
| TypeScript (NestJS/Express) | node:20-slim build → node:20-slim runtime | `compose_generator.py:444-466` | ✅ |
| Python (FastAPI/Django) | python:3.12-slim-bookworm | `compose_generator.py:468-486` | ✅ |
| **C# / .NET** | — | — | ❌ Missing |

---

## Investigation 7: .NET Support — FEATURE GAP

### Current State: Half-Implemented

| Layer | C# Support | Status |
|-------|-----------|--------|
| PRD Parser | `_LANGUAGES` includes "C#", "CSharp" (`prd_parser.py:28-29`) | ✅ Working |
| Framework detection | `_FRAMEWORKS` includes "ASP.NET" (`prd_parser.py:34`) | ✅ Working |
| Language normalization | "csharp" → "C#" (`prd_parser.py:80-84`) | ✅ Working |
| Supported languages | `SUPPORTED_LANGUAGES` includes "csharp" (`constants.py:14`) | ✅ Declared |
| C# AST parser | Tree-sitter parser for .cs files (`csharp_parser.py:1-268`) | ✅ Working |
| File extension detection | `.cs` → "csharp" (`_lang.py:30`) | ✅ Working |
| **Stack detection** | `_detect_stack_category()` has no C# case → returns "python" | ❌ **Silent downgrade** |
| **Builder instructions** | No entry in `_STACK_INSTRUCTIONS` for "csharp"/"dotnet" | ❌ Missing |
| **Dockerfile template** | No .NET multi-stage build template | ❌ Missing |
| **Cross-service standards** | JWT/Event examples only in Python & TypeScript | ⚠️ Partial |

### The Silent Downgrade Bug

`_detect_stack_category()` at `pipeline.py:1624-1640`:
```python
def _detect_stack_category(stack):
    # ... checks frontend, typescript ...
    return "python"  # ← C# falls through to this default
```

A service declared as `language="C#", framework="ASP.NET"` silently receives Python/FastAPI builder instructions. No warning logged. Builder generates Python code for what should be a C# service.

### Effort to Add .NET Support

| Task | Effort | Files |
|------|--------|-------|
| Fix `_detect_stack_category()` to detect C# | 15 min | `pipeline.py:1624-1640` |
| Add `_STACK_INSTRUCTIONS["dotnet"]` | 2-3 hours | `pipeline.py:1491-1621` |
| Add .NET Dockerfile template | 1-2 hours | `compose_generator.py:393-486` |
| Add C# examples to cross-service standards | 2-3 hours | `cross_service_standards.py` |
| Testing & validation | 2-3 hours | New test files |
| **TOTAL** | **6-9 hours** | 4-5 files |

### Bayan Rebuild Options

| Option | Effort | Recommendation |
|--------|--------|---------------|
| Keep Bayan as standalone (outside super-team) | 0 hours | Good for now |
| Re-platform Bayan to Python/NestJS | 3-5 weeks | Wasteful if .NET works |
| Add .NET support to super-team | 6-9 hours | **Best long-term investment** |

---

## Critical Path to 5 × 100K

### Phase 1: Config Changes (30 minutes, enables 100K LOC for Python/TypeScript)

1. **`config.py:26`** — `timeout_per_builder: int = 18000` (was 1800)
2. **`config.py:27`** — `depth: str = "exhaustive"` (was "thorough")
3. **`config.py:29`** — `stall_timeout_s: int = 3600` (was 600)
4. **`pipeline.py:2373`** — `_planning_phase_timeout = max(stall_timeout_s, 5400)` (was 2700)

### Phase 2: Bug Fixes (2 hours, fixes all builds)

5. **`pipeline.py:~2550`** — Add `compose_gen.generate_init_sql(output_dir, services)` call
6. **`compose_generator.py:340`** — `"start_period": "90s"` (was "30s")

### Phase 3: .NET Support (6-9 hours, enables C# builds)

7. **`pipeline.py:1634`** — Add C# detection: `if language in ("csharp", "c#"): return "dotnet"`
8. **`pipeline.py:1491-1621`** — Add `"dotnet"` entry to `_STACK_INSTRUCTIONS`
9. **`compose_generator.py:393-486`** — Add .NET Dockerfile template
10. **`cross_service_standards.py`** — Add C# JWT/Event code examples

---

## What Works Already (No Changes Needed)

| Component | Why It Works | Evidence |
|-----------|-------------|---------|
| **Architect scoping** | No limits on entity/endpoint count per service; respects PRD declarations | `service_boundary.py` — no MAX_ENTITIES constant |
| **PRD chunking** | Automatic for PRDs > 80KB; splits into parallel-processable chunks | `prd_chunking.py:112-160`, threshold at `config.py:334-335` |
| **Milestone isolation** | Fresh ClaudeSDKClient per milestone; 8-11 KB REQUIREMENTS.md per session | `cli.py:1312-1328` |
| **Context window** | 72-80% available for code generation even with 35-entity CLAUDE.md | Math: 44K tokens used / 200K budget = 22% |
| **Predecessor compression** | Completed milestones compressed to 2-3 KB summaries | `cli.py:705-739` |
| **Completion detection** | Conservative — requires both conv≥0.9 AND phases≥8; no false early termination | `pipeline.py:2446-2458` |
| **Stall recovery** | Builders with ≥3 milestones treated as partial success; output reused on retry | `pipeline.py:2598-2627` |
| **Skip-completed guard** | Previously built services reused on pipeline restart | `pipeline.py:2217-2256` |
| **RAM budget** | 5 large services + infra = 2.9 GB, well under 4.5 GB limit | `compose_generator.py` — 384m per service |
| **Config passthrough** | `--depth` flag correctly passed from pipeline to builder subprocess | `pipeline.py:2330-2335` |
| **PRD delivery** | Written to disk (not CLI arg); avoids Windows 32K limit | `pipeline.py:2263-2268` |
| **Subprocess stdout** | Redirected to log files (not PIPE); avoids 4KB pipe deadlock | `pipeline.py:2340-2345` |
| **Env filtering** | CLAUDE_CODE_* vars stripped from builder subprocess | `pipeline.py:190-202` |

---

## Risk Assessment

### High Risk: Build Duration Variability

Even with 5-hour timeout, large builds are unpredictable. Bayan took 4 hours with a subscription pause. Without pause, ~3.5 hours. But complexity scales non-linearly with entity count:

| Entities | Estimated Build Time | Confidence |
|----------|---------------------|-----------|
| 10 | 1-2 hours | High |
| 20 | 2-3 hours | Medium |
| 35 | 3-5 hours | Medium |
| 50+ | 4-8 hours | Low |

**Mitigation:** The stall recovery + skip-completed system means partial builds are preserved. A builder that completes 7 of 10 milestones before timeout can be resumed.

### Medium Risk: Claude API Rate Limiting

5 builders × exhaustive depth = 50+ concurrent Claude API calls. Rate limiting observed in SupplyForge (Run 2 used `max_concurrent=1` to avoid it).

**Mitigation:** Use `max_concurrent=2` for 100K LOC services. Total pipeline time: 2 batches × 5 hours = ~10-12 hours.

### Medium Risk: Entity Ownership Population

In SupplyForge, backend services received 0 entities because `owning_service` wasn't populated. This is an architect → domain model data flow gap that could leave large services without entity context.

**Mitigation:** Verify entity ownership in domain_model.json after architect phase. If empty, the builder relies on CLAUDE.md entity sections instead of config.json — which works but is less structured.

### Low Risk: Windows File System Limits

5 × 100K LOC = ~4,000 source files. Windows NTFS handles this without issues. Path length limit (260 chars) could theoretically be hit with deep nesting but is unlikely with standard project structures.

### Low Risk: Cost

Bayan cost ~$40 in Claude API credits (4 hours × exhaustive). 5 services × $40 = ~$200. With `max_concurrent=2` and rate limiting overhead, budget to $300-400.

---

## Appendix A: Timeout Arithmetic

### Scenario: 5 Services × 100K LOC, max_concurrent=2

```
Batch 1 (services 1-2, parallel):
  Planning:     60-90 min each
  Building:     120-180 min each
  Total:        180-270 min (3-4.5 hours)

Batch 2 (services 3-4, parallel):
  Same as batch 1: 180-270 min

Batch 3 (service 5, alone):
  Same: 180-270 min

Integration phase: 30-60 min
Quality gate: 30-60 min

TOTAL PIPELINE TIME: 9-15 hours

Required timeout_per_builder: 18000s (5 hours) per service
Required stall_timeout_s: 3600s (60 min) between file writes
```

### Scenario: 5 Services × 100K LOC, max_concurrent=3

```
Batch 1 (services 1-3): 3-4.5 hours
Batch 2 (services 4-5): 3-4.5 hours
Integration + Quality: 1-2 hours

TOTAL: 7-11 hours (faster but higher API rate limiting risk)
```

## Appendix B: Context Window Math

### Per-Session Budget for 35-Entity Service

```
200,000 tokens (Claude Opus context window)
 -13,000 tokens (system prompt + agent overhead)
 -16,825 tokens (CLAUDE.md for 35-entity service, baseline)
  -8,000 tokens (PRD service section, loaded on demand)
  -3,000 tokens (config + contracts)
  -3,000 tokens (milestone REQUIREMENTS.md)
  -2,000 tokens (predecessor summaries, compressed)
────────────────
=154,175 tokens available for code generation per milestone session

At 4 chars/token, 10K LOC = 40,000 tokens
→ 154K tokens supports ~38K LOC per session (3.8× headroom)
→ 10 milestones × 10K LOC = 100K LOC total ✓
```

### Worst Case: Verbose Contracts + Large PRD

```
200,000 tokens
 -13,000 (system)
 -21,825 (CLAUDE.md with verbose contracts)
 -16,500 (full 500KB PRD loaded)
  -5,000 (config + contracts)
  -3,000 (REQUIREMENTS.md)
  -3,000 (predecessors)
────────────────
=137,675 tokens available

Still supports ~34K LOC per session (3.4× headroom for 10K LOC milestones) ✓
```

## Appendix C: File Reference Index

| Investigation | Key Files | Critical Lines |
|--------------|-----------|---------------|
| Architect scoping | `src/architect/services/service_boundary.py` | 264-409 (4-tier fallback), 513-585 (ServiceMap build) |
| | `src/architect/services/prd_parser.py` | 1175-1293 (tech stack table), 1053-1105 (bounded contexts) |
| Builder config | `src/super_orchestrator/pipeline.py` | 431-757 (generate_builder_config), 2263-2268 (PRD copy) |
| CLAUDE.md | `src/super_orchestrator/pipeline.py` | 1643-2142 (_write_builder_claude_md) |
| | `src/super_orchestrator/cross_service_standards.py` | 832-870 (build_cross_service_standards) |
| Timeouts | `src/super_orchestrator/config.py` | 25-29 (BuilderConfig defaults) |
| | `src/super_orchestrator/pipeline.py` | 2363-2388 (timeout enforcement), 2478-2578 (stall detection) |
| Completion | `src/super_orchestrator/pipeline.py` | 2446-2458 (completion logic), 2598-2627 (stall recovery) |
| Session rotation | `agent-team-v15/src/agent_team_v15/cli.py` | 1312-1328 (fresh session per milestone), 705-739 (predecessor compression) |
| Bayan evidence | `claude-agent-team/BAYAN_TENDER/Logs/BUILD_LOG.md` | Full build timeline |
| Docker/infra | `src/integrator/compose_generator.py` | 393-486 (Dockerfile templates), 605-704 (init-db SQL) |
| .NET detection | `src/super_orchestrator/pipeline.py` | 1624-1640 (_detect_stack_category — missing C# case) |
| .NET constants | `src/shared/constants.py` | 14 (SUPPORTED_LANGUAGES includes "csharp") |

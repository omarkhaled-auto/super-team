# Super-Team Scoping Gap Analysis

> **Date:** 2026-03-11
> **Scope:** Read-only investigation of the full PRD → Architect → Builder Config → Builder Engine chain
> **Goal:** Determine what prevents the pipeline from producing 3–5 large bounded-context services instead of 8–12 small microservices

---

## Current State

### How the Architect Currently Decomposes PRDs

The architect phase is **entirely deterministic** — no LLM calls. Three Python modules run in sequence:

1. **`prd_parser.py`** (`parse_prd()`, line 229) — Pure regex/string extraction. Returns a `ParsedPRD` dataclass containing entities, relationships, bounded_contexts, state_machines, events, and `explicit_services`. **It does not decide service count.** It extracts whatever the PRD defines.

2. **`service_boundary.py`** (`identify_boundaries()`, line 238) — The critical decomposition logic. Uses this priority chain:
   - **Step 0**: If `parsed.explicit_services` has **≥ 3 entries**, use them directly (`_boundaries_from_explicit_services`, line 169). This is the path SupplyForge took — the PRD's Technology Stack table listed 9+ explicit services.
   - **Step 1**: Use explicit bounded contexts from the PRD (if any).
   - **Step 2**: Aggregate root algorithm — entities with no incoming OWNS edges each seed a boundary.
   - **Step 3**: Relationship-based assignment — orphan entities join the boundary with the most connections.
   - **Step 4**: Fallback — all entities in a single "monolith" boundary.

3. **`domain_modeler.py`** (`build_domain_model()`, line 74) — Assigns entities to their owning service based on the boundaries. Pure mapping, no splitting/merging.

### Key Finding: The PRD Controls Everything

The architect **never splits or merges services on its own**. If the PRD defines 3 large services with `explicit_services`, Step 0 fires and creates exactly 3 boundaries. If the PRD defines 10 services, it creates 10. The `≥ 3` threshold in Step 0 (line 264–268) means even a PRD with 3 explicit services will use the explicit path.

**There is no hardcoded minimum or maximum service count anywhere in the architect.**

### What SupplyForge Looked Like

The SupplyForge PRD defined 9 explicit services in its Technology Stack table. The architect created 10 services (splitting analytics into notification + reporting). The final `service_map.json`:

| Service | Entities | Est. LOC | Stack |
|---------|----------|----------|-------|
| auth-service | 4 (User, Tenant, Role, AuditLog) | 2,000 | Python/FastAPI |
| supplier-service | 4 (Supplier, Contact, Certification, Rating) | 2,000 | TypeScript/NestJS |
| product-service | 4 (Product, Category, ProductSupplier, PriceHistory) | 2,000 | Python/FastAPI |
| inventory-service | 5 (Warehouse, InventoryItem, StockMovement, Transfer, Reservation) | 2,500 | TypeScript/NestJS |
| procurement-service | 5 (PurchaseOrder, POLine, RFQ, RFQResponse, GoodsReceipt) | 2,500 | Python/FastAPI |
| shipping-service | 4 (Shipment, ShipmentItem, Carrier, DeliveryConfirmation) | 2,000 | TypeScript/NestJS |
| quality-service | 4 (QualityInspection, InspectionItem, NCR, QualityMetric) | 2,000 | Python/FastAPI |
| notification-service | 3 (Notification, NotificationPreference, EscalationRule) | 1,500 | TypeScript/NestJS |
| reporting-service | 2 (ReportSchedule, ReportExport) | 1,000 | Python/FastAPI |
| frontend | 0 (consumes all APIs) | 100 | TypeScript/Angular |

**Total: 35 entities across 9 backend services, average 3.9 entities/service.**

---

## The Chain: PRD → Architect → Config → Builder → Output

```
PRD Text (66KB, 736 lines)
    ↓
parse_prd() — regex extraction, no LLM
    ↓
ParsedPRD { entities: 35, explicit_services: 9, relationships: [], state_machines: 7 }
    ↓
identify_boundaries() — Step 0: explicit_services ≥ 3, use them directly
    ↓
ServiceBoundary[] — 10 boundaries (9 from PRD + 1 analytics split)
    ↓
build_service_map() — assigns stack, port, estimated_loc (500 × entity_count, clamped 100–200K)
    ↓
ServiceMap { services: 10, prd_hash: "..." }  →  saved to service_map.json
    ↓
generate_builder_config() — per service (pipeline.py:431)
    ↓
For each service:
  ├── builder_config.json  { entities: [...], state_machines: [...], contracts: {...}, ... }
  ├── .claude/CLAUDE.md    { stack instructions + entities + state machines + cross-service standards }
  ├── prd_input.md         { FULL original PRD (entire 66KB) }
  └── contracts/           { OpenAPI/AsyncAPI specs }
    ↓
agent-team-v15 subprocess  →  --prd prd_input.md --depth thorough --no-interview
    ↓
Phase 1: Decomposition → MASTER_PLAN.md (N milestones, determined by Claude)
Phase 2: Execution → one Claude session per milestone
    ↓
Source files, tests, Dockerfile, STATE.json
```

### Where Size Decisions Are Made

| Decision | Where | Who Decides |
|----------|-------|-------------|
| How many services | PRD → prd_parser → service_boundary Step 0 | **The PRD author** |
| How many entities per service | PRD entity `owning_context` field | **The PRD author** |
| How many milestones per service | agent-team-v15 decomposition (Claude call) | **Claude (no hard limit)** |
| How much code per milestone | agent-team-v15 execution (Claude sessions) | **Claude** |
| Estimated LOC per service | `build_service_map()`: `entity_count × 500` | **Formula** (informational only, not enforced) |

### Where Size Is Constrained

| Constraint | Where | Value | Hard/Soft |
|------------|-------|-------|-----------|
| Builder timeout | `config.builder.timeout_per_builder` | 1800s default (30min), 3600s SupplyForge | **Hard** — process killed |
| Stall detection | `config.builder.stall_timeout_s` | 600s default (10min), 1800s SupplyForge | **Hard** — process killed |
| Planning phase grace | `_planning_phase_timeout` | max(stall_timeout, 2700s = 45min) | **Hard** |
| Max concurrent builders | `config.builder.max_concurrent` | 1–3 (default 3) | Config |
| Docker RAM per service | `compose_generator._app_service()` | 384MB | **Hardcoded** |
| Docker RAM total budget | `compose_generator.py` docstring | 4.5GB (3.476GB for apps) | **Docker limit** |
| Max composable app services | 3476MB / 384MB | ~9 services | **Practical Docker limit** |
| Codebase map max files | `config.codebase_map.max_files` | 5000 | Config |
| Max milestones warning | `config.milestone.max_milestones_warning` | 30 | **Warning only** |
| CLAUDE.md size | Generated per service | ~30KB typical | Soft (context window) |

---

## What Limits Service Size Today

### Explicit Limits (Config Values, Hardcoded)

1. **Builder timeout: 1800s default (30 min), 3600s in SupplyForge** — `config.py:26`. The default is only 30 minutes; SupplyForge overrode to 3600s. A 15-entity service would need 90–120 minutes. Even at 3600s, the builder would be killed at 60 minutes with partial output. **This is the #1 blocker.**

2. **Stall detection: 600s default (10 min), 1800s in SupplyForge** — `config.py:29`. The planning phase timeout is `max(stall_timeout, 2700)` = 45 minutes (pipeline.py:2373). Once the first file is written, stall detection drops back to the configured value (600s default, 1800s SupplyForge). A larger service planning phase might take 30–60 minutes. **The building-phase stall (10 min default) is extremely aggressive for large services.**

3. **Docker RAM: 384MB per service, 4.5GB total budget** — `compose_generator.py:14,539`. Total budget is documented as 4.5GB (Traefik 256MB + PostgreSQL 512MB + Redis 256MB = 1.024GB infrastructure, leaving 3.476GB for app services). With 384MB per service, practical limit is ~9 app services. **Fewer, larger services actually benefit here.**

4. **Estimated LOC formula: `entity_count × 500`** — `service_boundary.py:558`. This is purely informational (used in reporting, not enforced). A 15-entity service would show estimated_loc=7500, which is accurate. **Not a constraint.**

### Implicit Limits (Prompt Wording, Conventions)

5. **CLAUDE.md cross-service standards: ~20KB** — The cross-service standards section (JWT, events, error format, Dockerfile template, testing) is ~20KB of the ~30KB CLAUDE.md. This is identical for every service regardless of size. For a 4-entity service, the entity-specific section is ~2KB; for a 15-entity service, it would be ~8KB. Total CLAUDE.md would grow from ~30KB to ~38KB. **Not a constraint** — Claude's context window handles this easily.

6. **PRD passed in full to every builder** — `pipeline.py:2264-2268`. The entire PRD (66KB for SupplyForge) is copied as `prd_input.md` to each builder directory. With fewer, larger services, the PRD would be the same size. **Not a constraint.**

7. **Builder creates its own MASTER_PLAN.md** — The builder (agent-team-v15) reads the PRD + CLAUDE.md and creates its own milestone decomposition via a Claude call. For a 4-entity service, this typically produces 5–8 milestones. For a 15-entity service, Claude would produce 12–20 milestones. The `max_milestones_warning` (30) is only a warning. **Not a constraint, but see timeout above.**

### Soft Limits (Untested but Probably Work)

8. **Context window saturation** — Claude Opus has a 200K context window. The CLAUDE.md (~30-38KB) + PRD (66KB) + MASTER_PLAN.md (~5-15KB) + accumulated code context = ~120-150K tokens for a large service. Multi-session rotation in agent-team-v15 starts fresh sessions per milestone, resetting context. **Probably fine** — Bayan proved 104K LOC in a single agent-team run.

9. **Codebase map limit: 5000 files** — `config.py:192`. A 15-entity service generating ~75 files is far below this limit. **Not a constraint.**

10. **Cost per builder** — No per-builder cost limit exists. The global `budget_limit` (999.0 in SupplyForge config) applies to the entire pipeline, not individual builders. A larger builder will cost more per service but the total cost for 3 builders vs 10 builders should be comparable. **Not a constraint.**

---

## Bayan Comparison

### What Bayan Was

Bayan was a **tender management system** built by the old `claude-agent-team` (not agent-team-v15, not super-team). It was run as a **single monolithic project** — one agent-team instance handling the entire scope. The original 104K LOC build config is not preserved — only the output and a subsequent UI-only restyling pass (65 files, 8 milestones, $30 budget) have configs in `BAYAN_TENDER/`.

| Metric | Value |
|--------|-------|
| Total LOC | 103,931 |
| Source files | 921 |
| Architecture | Clean Architecture (4 layers: API, Application, Domain, Infrastructure) |
| Backend | ASP.NET Core / C# — 22,899 LOC |
| Frontend | Angular 18 — 55,308 LOC |
| Entities | 34 (EF Core entity configurations) |
| CQRS handlers | 138 (79 commands, 59 queries) |
| Validators | 68 (FluentValidation) |
| Tests | 720 (E2E via Playwright) |
| Feature modules | 18 |
| Config | `depth: thorough`, `max_budget_usd: 30` (for UI-only pass) |
| Milestones | 8 |

### Key Difference: Scope Delivery

| Aspect | Bayan (claude-agent-team) | SupplyForge (super-team) |
|--------|---------------------------|--------------------------|
| **Scope unit** | 1 monolith with 34 entities | 10 microservices × ~4 entities each |
| **Builder instances** | 1 | 10 |
| **LOC per builder** | 104,000 | ~3,200 |
| **Entities per builder** | 34 | 3.9 average |
| **Builder capacity used** | ~100% | ~3% |
| **Architecture** | Clean Architecture layers | Separate process per service |
| **Integration** | Built-in (same codebase) | Docker Compose + Traefik |
| **Cross-service comms** | Method calls | Redis Pub/Sub + REST |

### Where the Scope Diverges

Bayan's builder received a **single PRD describing one system** and decomposed it into milestones internally. Each milestone was a vertical slice of the entire system.

SupplyForge's builders each received a **PRD for the entire system** but a **CLAUDE.md scoping them to 4 entities**. The builder had full context about the system but was told to only build its slice.

The builder engine (agent-team-v15) is **the same engine** that powered Bayan, just newer. It has no internal limit on scope — it creates as many milestones as needed and executes them sequentially. The 3% utilization is entirely due to the orchestrator giving it a small assignment.

---

## Gap Analysis: Microservices → Bounded Contexts

### What Would a "Bounded Context" Look Like?

Instead of SupplyForge's 10 services, a bounded-context decomposition might produce:

| Bounded Context | Entities | Est. LOC |
|-----------------|----------|----------|
| **Core Procurement** | PurchaseOrder, POLine, RFQ, RFQResponse, GoodsReceipt, Supplier, SupplierContact, SupplierCertification, SupplierRating, Product, Category, ProductSupplier, PriceHistory | ~30K |
| **Warehouse & Logistics** | Warehouse, InventoryItem, StockMovement, StockTransfer, StockReservation, Shipment, ShipmentItem, Carrier, DeliveryConfirmation | ~25K |
| **Quality & Compliance** | QualityInspection, InspectionItem, NonConformanceReport, QualityMetric, ReportSchedule, ReportExport | ~15K |
| **Platform Services** | User, Tenant, Role, AuditLog, Notification, NotificationPreference, EscalationRule | ~12K |
| **Frontend** | (consumes all APIs) | ~25K |

**4 backend services + 1 frontend = 5 builders at ~20K LOC each, well within the 104K proven capacity.**

### Component-by-Component Change Assessment

| Component | Current State | Change Needed | Effort | Risk |
|-----------|--------------|--------------|--------|------|
| **PRD format** | Defines 9 explicit services | Define 3–5 bounded contexts instead | **PRD author work** | Low |
| **prd_parser.py** | Extracts `explicit_services` from PRD | Works as-is — parses whatever the PRD defines | **None** | None |
| **service_boundary.py** | Step 0: uses explicit services if ≥ 3 | Works as-is — respects PRD's service definitions | **None** | None |
| **domain_modeler.py** | Assigns entities to owning service | Works as-is — handles any entity count per service | **None** | None |
| **build_service_map()** | `entity_count × 500` LOC estimate | Works as-is — 15 entities → 7500 LOC estimate | **None** | None |
| **generate_builder_config()** | Loads entities for service from domain model | Works as-is — loads all matching entities | **None** | None |
| **_write_builder_claude_md()** | Generates entity sections in CLAUDE.md | Works as-is — iterates all entities | **None but size grows** | Low |
| **CLAUDE.md size** | ~30KB (20KB standards + 2KB entities + 8KB other) | ~38KB (20KB standards + 8KB entities + 10KB other) | **None** | Low |
| **Builder timeout** | 3600s (1 hour) | **Needs 7200–10800s (2–3 hours)** | **Config change** | Medium |
| **Stall detection** | 1800s (30 min), planning grace 45 min | **Needs 3600s (1 hr), planning grace 90 min** | **Config change** | Medium |
| **Docker RAM** | 384MB hardcoded | **Should be 768MB for fat services** | **1-line code change** | Low |
| **Max concurrent** | 3 (default), 1 (SupplyForge) | 2–3 (fewer services, can parallelize) | **Config change** | Low |
| **agent-team-v15** | No internal scope limit | **No change needed** — proven at 104K LOC | **None** | None |
| **Quality gate** | Per-service scoring | Works the same regardless of service size | **None** | None |
| **Compose generator** | One container per service | Works the same — fewer, larger containers | **None** | None |

---

## Recommended Changes (Priority Ordered)

### Change 1: Write the PRD Differently (Effort: 0 code, PRD authoring)

**The architect is PRD-driven.** If the PRD defines 4 bounded contexts with 8–12 entities each, the pipeline will produce exactly 4 services. The parser, boundary detector, and domain modeler all handle arbitrary service sizes.

**Action:** Write the PRD's "Technology Stack" or "Services" table with 3–5 bounded contexts instead of 8–12 microservices. Assign entities to them via `owning_context`.

**Risk:** None. The code already supports this.

### Change 2: Increase Builder Timeout (Effort: 1-minute config change)

```yaml
builder:
  timeout_per_builder: 10800  # 3 hours for fat services
  stall_timeout_s: 3600       # 1 hour stall tolerance
```

**Action:** Update `config.yaml` for the target project.

**Risk:** Low. Longer timeout means longer recovery on actual stalls, but the stall detection + planning grace already handle this.

### Change 3: Increase Docker RAM for Fat Services (Effort: 5-minute code change)

In `compose_generator.py:539`, the 384MB is hardcoded. Change to scale with entity count:

```python
# Current
"mem_limit": "384m",

# Proposed — dynamic based on estimated_loc or entity count
ram_mb = 384 if svc.estimated_loc <= 5000 else 768
"mem_limit": f"{ram_mb}m",
```

Or simpler: just increase to 768MB for all services. With 3–5 services instead of 10, total Docker RAM is lower anyway.

**Risk:** Very low. Fewer containers = less total RAM usage even with higher per-container limits.

### Change 4: Adjust Planning Phase Grace Period (Effort: 1-line code change)

In `pipeline.py:2373`:
```python
# Current
_planning_phase_timeout = max(stall_timeout_s, 2700)  # 45 min during planning

# Proposed
_planning_phase_timeout = max(stall_timeout_s, 5400)  # 90 min during planning
```

A 15-entity service will generate a longer MASTER_PLAN.md — the planning Claude call might take 30–60 minutes.

**Risk:** Low.

### Change 5: Validate with a Test Run (Effort: 1 run)

Before investing in further changes, run the pipeline with a modified SupplyForge PRD that defines 4 bounded contexts instead of 9 services. Use the config from Change 2. Measure:

- Builder planning time (MASTER_PLAN.md creation)
- Builder execution time (milestones)
- Total LOC per builder
- Convergence ratio
- Total pipeline cost

**Expected result:** 4 builders × ~25K LOC each = ~100K LOC total, completed in 2–3 hours per builder.

---

## Known Bug: Entity Enrichment Sometimes Fails

The SupplyForge `procurement-service/builder_config.json` shows `"entities": []` despite the service owning 5 entities in the service map. This means the entity enrichment code in `generate_builder_config()` (pipeline.py:551-569) sometimes fails to match `owning_service` names. The matching uses `_normalize_service_name()` to compare the domain model's `owning_service` field against the service_id, but naming mismatches (e.g., "Procurement Service" vs "procurement-service") can cause silent failures.

**Impact for bounded contexts:** Larger services with more entities amplify this bug. If a 15-entity service gets `"entities": []` in its config, the builder receives NO entity context and must infer everything from the PRD. This should be fixed before testing bounded-context mode.

**Fix:** Add logging when entity matching fails, and implement fuzzy matching (strip "Service", normalize case/hyphens/spaces).

---

## Risk Assessment

### What Could Go Wrong

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| Builder context window overflow | Low | Medium | Multi-session rotation resets context per milestone. Bayan proved 104K LOC in one run. |
| Stall detection false kills | Medium | High | Increase stall_timeout_s to 3600s. Planning grace to 90 min. |
| Docker resource exhaustion | Low | Low | 5 containers × 768MB = 3.8GB vs 10 × 384MB = 3.8GB. Same total. |
| Builder timeout at 3 hours | Medium | High | Use 10800s timeout. Monitor cost. If builder stalls, it's the same as today. |
| CLAUDE.md too large | Very Low | Low | Even with 15 entities, CLAUDE.md is ~38KB. Claude handles 200K+ context. |
| Milestone count explosion | Low | Medium | 15 entities → ~15–20 milestones. Well under the 30 warning threshold. Bayan did 8 milestones for 34 entities. |
| Cross-service contract complexity | Low | Low | Fewer services = fewer inter-service contracts. Simpler dependency graph. |
| Quality gate failure | Low | Low | Quality gate is per-service. Larger services have more to check but fewer integration points. |
| Cost increase per builder | Medium | Low | Each builder costs more, but total builders drops from 10 to 4. Net cost likely similar or lower. |

### What Would Actually Be Better

1. **Fewer inter-service contracts** — 4 services need ~6 cross-service APIs. 10 services need ~20+.
2. **Simpler Docker Compose** — 4 app containers + 3 infra = 7 total. Easier to debug.
3. **No cross-service data consistency issues** — Entities in the same service share a database. No eventual consistency.
4. **Better code quality** — Each builder has full domain context. No split-entity problems.
5. **Fewer integration failures** — The quality gate's Docker all-or-nothing problem is less severe with 4 services.
6. **Lower total cost** — Pipeline overhead (contracts, compose, quality gate) runs once per service. Fewer services = less overhead.

---

## Summary

**The scoping gap is not in the code — it's in the PRD.**

The architect phase faithfully translates whatever the PRD defines into service boundaries. The builder engine (agent-team-v15) has proven it can handle 104K LOC in a single run. The pipeline infrastructure (timeouts, Docker RAM) needs minor config adjustments for larger services.

**Required changes for bounded-context mode:**

| # | Change | Type | Effort |
|---|--------|------|--------|
| 1 | Write PRD with 3–5 bounded contexts | PRD authoring | 2–4 hours |
| 2 | Set `timeout_per_builder: 10800` | Config | 1 minute |
| 3 | Set `stall_timeout_s: 3600` | Config | 1 minute |
| 4 | Increase Docker RAM to 768MB | Code (1 line) | 5 minutes |
| 5 | Increase planning grace to 90 min | Code (1 line) | 5 minutes |
| 6 | Test run with modified PRD | Validation | 3–4 hours |

**Total engineering effort: ~1 hour of config/code changes + ~4 hours PRD writing + ~4 hours test run.**

The pipeline is already designed to handle this. It just hasn't been asked to.

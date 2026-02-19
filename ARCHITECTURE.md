# Super Agent Team -- Architecture Document

> **Version:** 2.0.0
> **Last Updated:** 2026-02-19

---

## Table of Contents

1. [System Overview](#1-system-overview)
2. [Pipeline Flow Diagram](#2-pipeline-flow-diagram)
3. [State Machine](#3-state-machine)
4. [Build 1: Foundation Services](#4-build-1-foundation-services)
5. [Build 2: Builder Fleet (agent-team-v15)](#5-build-2-builder-fleet-agent-team-v15)
6. [Build 3: Super Orchestrator](#6-build-3-super-orchestrator)
7. [Run 4: Verification Suite](#7-run-4-verification-suite)
8. [Docker Architecture](#8-docker-architecture)
9. [Quality Gate Layers](#9-quality-gate-layers)
10. [Test Coverage](#10-test-coverage)

---

## 1. System Overview

Super Agent Team is a multi-repository AI-powered software factory that takes a Product Requirements Document (PRD) as input and produces a fully built, tested, and deployed multi-service application as output.

The system is organized across three independently-built repositories, wired together by a fourth verification run:

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         SUPER AGENT TEAM                                │
│                                                                         │
│  ┌──────────────────┐   ┌──────────────────┐   ┌────────────────────┐  │
│  │   Build 1         │   │   Build 2         │   │   Build 3          │  │
│  │   Foundation      │   │   Builder Fleet   │   │   Orchestration    │  │
│  │   Services        │   │   (agent-team-v15)│   │   Layer            │  │
│  │                   │   │                   │   │                    │  │
│  │  - Architect MCP  │   │  - Claude Code    │   │  - Super           │  │
│  │  - Contract       │   │    subprocess     │   │    Orchestrator    │  │
│  │    Engine MCP     │   │  - Milestone-     │   │  - Integrator      │  │
│  │  - Codebase       │   │    based builds   │   │  - Quality Gate    │  │
│  │    Intelligence   │   │  - Audit teams    │   │  - CLI             │  │
│  │    MCP            │   │  - Fix passes     │   │                    │  │
│  └────────┬─────────┘   └────────┬─────────┘   └────────┬───────────┘  │
│           │                      │                       │              │
│           └──────────────────────┼───────────────────────┘              │
│                                  │                                      │
│                          ┌───────▼──────────┐                           │
│                          │   Run 4           │                           │
│                          │   Verification    │                           │
│                          │   & Wiring        │                           │
│                          └──────────────────┘                           │
└─────────────────────────────────────────────────────────────────────────┘
```

### How They Connect

| Build | Repository | Role | Interfaces |
|-------|-----------|------|------------|
| **Build 1** | `super-team` (src/) | PRD decomposition, contract management, code intelligence | MCP stdio, HTTP REST (ports 8001-8003) |
| **Build 2** | `agent-team-v15` | Code generation via Claude Code subprocess agents | Subprocess CLI, MCP clients to Build 1 |
| **Build 3** | `super-team` (src/super_orchestrator, src/integrator, src/quality_gate) | Pipeline orchestration, Docker integration, quality verification | State machine, Docker Compose, subprocess to Build 2 |
| **Run 4** | `super-team` (src/run4, tests/run4) | End-to-end wiring verification, fix passes, audit scoring | Composes all three builds |

---

## 2. Pipeline Flow Diagram

The full pipeline from PRD to deployed application:

```
┌──────────────────────────────────────────────────────────────────────────────┐
│                          Super Orchestrator Pipeline                          │
│                                                                              │
│  ┌───────────┐    ┌─────────────┐    ┌───────────┐    ┌─────────────────┐   │
│  │ Architect  │ -> │  Contract   │ -> │ Builders  │ -> │  Integration    │   │
│  │  Phase     │    │Registration │    │  Phase    │    │    Phase        │   │
│  └─────┬─────┘    └──────┬──────┘    └─────┬─────┘    └───────┬─────────┘   │
│        │                 │                 │                   │             │
│  ┌─────▼─────┐    ┌──────▼──────┐    ┌────▼──────┐    ┌──────▼──────────┐   │
│  │ Architect  │    │ Contract    │    │ agent-    │    │ Docker Compose  │   │
│  │  MCP       │    │ Engine MCP  │    │ team-v15  │    │ 5-file merge    │   │
│  │  :8001     │    │  :8002      │    │ parallel  │    │ + Traefik       │   │
│  │            │    │             │    │ subprocess│    │ + health checks │   │
│  │ Outputs:   │    │ Outputs:    │    │           │    │ + contract      │   │
│  │ -service   │    │ -registered │    │ Outputs:  │    │   compliance    │   │
│  │  map.json  │    │  contracts  │    │ -source   │    │ + cross-service │   │
│  │ -domain    │    │ -stubs.json │    │  code     │    │   tests         │   │
│  │  model.json│    │             │    │ -tests    │    │ + boundary      │   │
│  │ -contract  │    │             │    │ -Dockerfile│   │   tests         │   │
│  │  stubs     │    │             │    │ -STATE.json│   │                 │   │
│  └───────────┘    └─────────────┘    └───────────┘    └─────────────────┘   │
│                                                                              │
│  ┌──────────────────────┐    ┌────────────────────────────┐                  │
│  │   Quality Gate        │ -> │      Fix Pass              │                  │
│  │   (4 layers)          │    │  (P0-P3 priority)          │                  │
│  │                       │    │                            │                  │
│  │ L1: Per-service eval  │    │  classify_priority()       │                  │
│  │ L2: Contract compliance│   │  feed violations to        │ ─── loop ──>    │
│  │ L3: System-level scan │    │    builders                │    builders     │
│  │ L4: Adversarial       │    │  detect_regressions()      │    phase        │
│  │     (advisory only)   │    │  compute_convergence()     │                  │
│  │                       │    │                            │                  │
│  │ Verdict:              │    │  Up to max_fix_retries     │                  │
│  │  PASSED -> complete   │    │  iterations                │                  │
│  │  FAILED -> fix pass   │    │                            │                  │
│  └───────────────────────┘    └────────────────────────────┘                  │
│                                                                              │
│  Terminal States:  [complete]  or  [failed]                                   │
└──────────────────────────────────────────────────────────────────────────────┘
```

### Phase Flow Summary

```
PRD File
   │
   ▼
init ──> architect_running ──> architect_review ──> contracts_registering
                                                          │
                    ┌─────────────────────────────────────┘
                    ▼
            builders_running ──> builders_complete ──> integrating
                    ▲                                       │
                    │                                       ▼
               fix_pass  <── quality_gate (FAILED)    quality_gate
                                                          │
                                              (PASSED) ──>│──> complete
                                              (FAILED,    │
                                               no retries)│──> failed
```

---

## 3. State Machine

The pipeline is driven by an async state machine implemented with the `transitions` library (AsyncMachine). It defines exactly **11 states** and **13 transitions**, each with a guard condition.

### States (11)

| # | State | Description |
|---|-------|-------------|
| 1 | `init` | Pipeline created, PRD loaded, waiting to start |
| 2 | `architect_running` | Architect MCP decomposing PRD into services |
| 3 | `architect_review` | Architecture produced, awaiting approval |
| 4 | `contracts_registering` | Registering OpenAPI/AsyncAPI contracts |
| 5 | `builders_running` | Parallel builder subprocesses generating code |
| 6 | `builders_complete` | All builders finished (at least one succeeded) |
| 7 | `integrating` | Docker Compose deployment + compliance tests |
| 8 | `quality_gate` | 4-layer quality verification running |
| 9 | `fix_pass` | Feeding violations back to builders |
| 10 | `complete` | Pipeline finished successfully |
| 11 | `failed` | Pipeline terminated with errors |

### Transitions (13)

| # | Trigger | Source | Destination | Guard Condition |
|---|---------|--------|-------------|-----------------|
| 1 | `start_architect` | init | architect_running | `is_configured` (PRD path set) |
| 2 | `architect_done` | architect_running | architect_review | `has_service_map` |
| 3 | `approve_architect` | architect_review | contracts_registering | `service_map_valid` |
| 4 | `contracts_registered` | contracts_registering | builders_running | `contracts_valid` |
| 5 | `builders_done` | builders_running | builders_complete | `has_builder_results` |
| 6 | `start_integration` | builders_complete | integrating | `any_builder_passed` |
| 7 | `integration_done` | integrating | quality_gate | `has_integration_report` |
| 8 | `quality_passed` | quality_gate | complete | `gate_passed` |
| 9 | `quality_needs_fix` | quality_gate | fix_pass | `fix_attempts_remaining` |
| 10 | `fix_done` | fix_pass | builders_running | `fix_applied` |
| 11 | `fail` | (any non-terminal) | failed | (unconditional) |
| 12 | `retry_architect` | architect_running | architect_running | `retries_remaining` |
| 13 | `skip_to_complete` | quality_gate | complete | `advisory_only` |

### State Diagram

```
                                   ┌──────────────┐
                                   │              │
                          ┌────────▼──┐  retry   │
            ┌─────┐       │ architect  │──────────┘
            │init │──────>│ _running   │
            └──┬──┘       └─────┬─────┘
               │                │ architect_done
               │          ┌─────▼─────┐
               │          │ architect  │
               │          │ _review    │
               │          └─────┬─────┘
               │                │ approve_architect
               │          ┌─────▼─────────┐
               │          │ contracts     │
               │          │ _registering  │
               │          └─────┬─────────┘
               │                │ contracts_registered
               │          ┌─────▼─────────┐
               │     ┌───>│ builders      │<────────────┐
               │     │    │ _running      │             │
               │     │    └─────┬─────────┘             │
               │     │          │ builders_done         │
               │     │    ┌─────▼─────────┐             │
               │     │    │ builders      │       fix_done
               │     │    │ _complete     │             │
               │     │    └─────┬─────────┘             │
               │     │          │ start_integration     │
               │     │    ┌─────▼─────────┐             │
               │     │    │ integrating   │             │
               │     │    └─────┬─────────┘             │
               │     │          │ integration_done      │
               │     │    ┌─────▼─────────┐             │
               │     │    │ quality_gate  │─────────────┘
               │     │    │               │  quality_needs_fix
               │     │    └──┬────────┬───┘
               │     │       │        │
               │     │  PASSED│   skip_to_complete
               │     │       │        │
               │     │  ┌────▼────────▼──┐
               │     │  │   complete     │
               │     │  └────────────────┘
               │     │
     fail      │     │
  (from any)   │     │
               │     │
            ┌──▼─────▼──┐
            │  failed    │
            └────────────┘
```

### Resume Support

Every state transition persists `PIPELINE_STATE.json` via `state.save()` before and after the transition. The `RESUME_TRIGGERS` map allows re-entering the pipeline from any interrupted state:

| Interrupted State | Resume Behavior |
|-------------------|-----------------|
| `init` | Trigger `start_architect` |
| `architect_running` | Re-run architect phase |
| `architect_review` | Re-run from review |
| `contracts_registering` | Re-run contract registration |
| `builders_running` | Re-run builder fleet |
| `builders_complete` | Trigger `start_integration` |
| `integrating` | Re-run integration phase |
| `quality_gate` | Re-run quality gate |
| `fix_pass` | Re-run fix pass |

---

## 4. Build 1: Foundation Services

Three Python/FastAPI microservices providing MCP tools for architecture analysis.

### Architect MCP (Port 8001)

**Purpose:** Decomposes PRDs into service boundaries and domain models using deterministic algorithms (no LLM).

| Component | Role |
|-----------|------|
| `prd_parser` | Parses and tokenizes PRD content, extracts entities and tech hints |
| `service_boundary` | Identifies service boundaries from parsed entities |
| `domain_modeler` | Constructs entity-relationship domain models |
| `validator` | Validates decomposition for consistency and completeness |
| `contract_generator` | Generates OpenAPI 3.1 contract stubs per service |

**MCP Tools (3):** `decompose_prd`, `get_service_map`, `get_domain_model`

**Storage:** SQLite WAL (`architect.db`) -- tables: `service_maps`, `domain_models`, `decomposition_runs`

**Inter-service:** HTTP POST to Contract Engine to register generated contract stubs.

### Contract Engine MCP (Port 8002)

**Purpose:** Manages the full API contract lifecycle -- storage, validation, versioning, breaking change detection, test generation, and compliance.

**Supported Specifications:**
- OpenAPI 3.0.x / 3.1.0
- AsyncAPI 3.0
- JSON Schema

| Feature | Description |
|---------|-------------|
| Contract CRUD | Create, read, update, delete contracts |
| Spec Validation | Validate against OpenAPI, AsyncAPI, JSON Schema specs |
| Breaking Change Detection | Compare versions, identify breaking changes |
| Implementation Tracking | Track which services implement a contract |
| Test Generation | Generate contract tests via Schemathesis |
| Compliance Checking | Verify services comply with registered contracts |

**MCP Tools (9):** `create_contract`, `list_contracts`, `get_contract`, `validate_contract`, `detect_breaking_changes`, `mark_implementation`, `get_unimplemented`, `generate_tests`, `check_compliance`

**Storage:** SQLite WAL (`contracts.db`) -- 8 tables: `build_cycles`, `contracts`, `contract_versions`, `breaking_changes`, `implementations`, `test_suites`, `shared_schemas`, `schema_consumers`

### Codebase Intelligence MCP (Port 8003)

**Purpose:** Multi-language code analysis via AST parsing, symbol extraction, dependency graphs, and semantic search.

**Supported Languages:** Python, TypeScript, C#, Go (via tree-sitter)

| Feature | Description |
|---------|-------------|
| AST Parsing | Multi-language parsing via tree-sitter 0.25.2 |
| Symbol Extraction | Classes, functions, interfaces, types, enums, variables, methods |
| Import Resolution | Resolve imports to target files and symbols |
| Dependency Graph | NetworkX-based dependency graph with snapshot persistence |
| Semantic Search | ChromaDB vector search with all-MiniLM-L6-v2 embeddings |
| Dead Code Detection | Identify unreferenced symbols across the codebase |

**MCP Tools (6):** `index_file`, `search_code`, `get_symbols`, `get_dependencies`, `analyze_graph`, `detect_dead_code`

**Storage:** SQLite WAL (`symbols.db`) + ChromaDB (vectors) + NetworkX (graph) -- 5 tables: `indexed_files`, `symbols`, `dependency_edges`, `import_references`, `graph_snapshots`

### Shared Infrastructure (`src/shared/`)

| Component | Description |
|-----------|-------------|
| Models | 52 Pydantic v2 models across 4 modules (architect, contracts, codebase, common) |
| ConnectionPool | Thread-local SQLite with WAL mode, 30s busy timeout, foreign key enforcement |
| Config | pydantic-settings based configuration from environment variables |
| Logging | Structured JSON logging with TraceIDMiddleware for distributed tracing |
| Errors | Custom exception hierarchy (`AppError` base) with FastAPI exception handlers |

---

## 5. Build 2: Builder Fleet (agent-team-v15)

The builder fleet is an external package (`agent-team-v15` or `agent-team`) that generates complete microservices from PRDs using Claude Code as a subprocess.

### How Builders Work

1. The Super Orchestrator creates a per-service output directory under `.super-orchestrator/<service-id>/`
2. A `builder_config.json` is generated with service metadata (domain, stack, port, depth)
3. The PRD is copied to `prd_input.md` in the builder directory
4. A subprocess is launched: `python -m agent_team_v15 --prd prd_input.md --depth thorough --no-interview`

### Subprocess Model

```
Super Orchestrator
    │
    ├── asyncio.Semaphore(max_concurrent=3)
    │
    ├── builder-1 (auth-service)
    │   └── python -m agent_team_v15 --prd ... --depth thorough --no-interview
    │       └── Claude Code subprocess (--backend cli)
    │           └── MCP clients → Build 1 services
    │
    ├── builder-2 (order-service)
    │   └── python -m agent_team_v15 --prd ... --depth thorough --no-interview
    │       └── Claude Code subprocess (--backend cli)
    │           └── MCP clients → Build 1 services
    │
    └── builder-3 (notification-service)
        └── python -m agent_team_v15 --prd ... --depth thorough --no-interview
            └── Claude Code subprocess (--backend cli)
                └── MCP clients → Build 1 services
```

### Builder Lifecycle

1. **Milestone-based execution:** Each builder works through milestones defined by the agent-team framework
2. **Audit teams:** 5 auditors (requirements, technical, interface, test, library) evaluate each milestone
3. **Fix passes:** Audit findings trigger targeted fixes with regression detection
4. **Result parsing:** The orchestrator reads `.agent-team/STATE.json` for success/failure, cost, test results, and convergence ratio
5. **Source validation:** Even if `STATE.json` claims success, the orchestrator verifies that actual source files (`.py`, `.js`, `.ts`, `Dockerfile`) were produced

### Environment Isolation

- `CLAUDECODE` and `CLAUDE_CODE_ENTRYPOINT` are filtered from the subprocess environment to avoid nested session guards
- `ANTHROPIC_API_KEY` is intentionally passed through (builders need it)
- Each builder runs in its own `cwd` to avoid config conflicts

---

## 6. Build 3: Super Orchestrator

The orchestration layer that drives the full pipeline.

### Package Structure

```
src/super_orchestrator/
    __init__.py
    __main__.py          # Module entry point
    cli.py               # Typer CLI (8 commands)
    config.py            # Dataclass configs (5 config classes)
    pipeline.py          # Phase handlers and main loop
    state_machine.py     # 11 states, 13 transitions
    state.py             # PipelineState persistence
    cost.py              # PipelineCostTracker
    shutdown.py          # GracefulShutdown (signal handling)
    display.py           # Rich terminal display
    exceptions.py        # PipelineError hierarchy
```

### CLI Commands (8)

| Command | Description |
|---------|-------------|
| `init` | Initialize a new pipeline run from a PRD file |
| `plan` | Run the Architect phase only |
| `build` | Run the Builder fleet only |
| `integrate` | Run Docker integration + compliance tests |
| `verify` | Run the 4-layer Quality Gate |
| `run` | Execute the full pipeline end-to-end |
| `status` | Display current pipeline state |
| `resume` | Resume an interrupted pipeline |

### Configuration Hierarchy

```
SuperOrchestratorConfig
    ├── ArchitectConfig       (max_retries, timeout, auto_approve)
    ├── BuilderConfig         (max_concurrent, timeout_per_builder, depth)
    ├── IntegrationConfig     (timeout, traefik_image, compose_file)
    ├── QualityGateConfig     (max_fix_retries, layer3_scanners, layer4_enabled)
    ├── budget_limit          (float | None)
    ├── depth                 (quick | standard | thorough)
    ├── mode                  (docker | mcp | auto)
    └── output_dir            (.super-orchestrator)
```

### Pipeline Loop

The `_run_pipeline_loop()` function maps each state to a phase handler and iterates until a terminal state (`complete` or `failed`) is reached or a graceful shutdown is requested:

```python
phase_handlers = {
    "init":                   _phase_architect,
    "architect_running":      _phase_architect_complete,
    "architect_review":       _phase_contracts,
    "contracts_registering":  _phase_builders,
    "builders_running":       _phase_builders_complete,
    "builders_complete":      _phase_integration,
    "integrating":            _phase_quality,
    "quality_gate":           _phase_quality_check,
    "fix_pass":               _phase_fix_done,
}
```

Safety bound: maximum 50 iterations to prevent infinite loops.

### MCP-First with Fallback

Every external call follows the same pattern:

1. Try MCP stdio (lazy import of client module)
2. If MCP fails (ImportError, connection error), fall back to subprocess
3. If subprocess fails, fall back to filesystem
4. Raise `ConfigurationError` only if all paths fail

### Budget and Cost Tracking

- `PipelineCostTracker` accumulates costs per phase
- Budget check after every phase transition
- `BudgetExceededError` triggers graceful shutdown with state persistence
- Cost data stored in `PipelineState` for resume

### Graceful Shutdown

- SIGINT/SIGTERM handlers installed via `GracefulShutdown`
- Sets `should_stop` flag checked by every phase handler
- State is persisted before shutdown
- Subprocess builders get `terminate()` then `kill()` after 5s timeout

---

## 7. Run 4: Verification Suite

Run 4 wires the three independently-built systems together and verifies every integration point.

### Purpose

- End-to-end pipeline verification with a 3-service test application (TaskTracker)
- Integration point catalog and defect detection
- Convergence-based fix passes with priority classification
- Final audit report and scoring

### Fix Pass System

The fix pass module (`src/run4/fix_pass.py`) provides:

| Function | Description |
|----------|-------------|
| `classify_priority()` | Classify violations as P0 (critical), P1 (high), P2 (medium), P3 (low) |
| `take_violation_snapshot()` | Capture current violation state for before/after comparison |
| `detect_regressions()` | Compare snapshots to find newly introduced violations |
| `compute_convergence()` | Calculate weighted convergence score (P0*0.4 + P1*0.3 + P2*0.1) |
| `check_convergence()` | Determine if fix passes should continue or stop |

### Convergence Formula

```
convergence = 1.0 - (current_weighted / initial_weighted)

where:
  current_weighted = P0 * 0.4 + P1 * 0.3 + P2 * 0.1
  initial_weighted = baseline from first fix pass
```

### Scoring Model (3-tier)

**SystemScore (per-build):** 6 categories summing to 100:

| Category | Weight |
|----------|--------|
| Functional Completeness | 0-30 |
| Test Health | 0-20 |
| Contract Compliance | 0-20 |
| Code Quality | 0-15 |
| Docker Health | 0-10 |
| Documentation | 0-5 |

**IntegrationScore:** 4 categories each 0-25, summing to 100:

| Category | Weight |
|----------|--------|
| MCP Connectivity | 0-25 |
| Data Flow Integrity | 0-25 |
| Contract Fidelity | 0-25 |
| Pipeline Completion | 0-25 |

**AggregateScore:** Weighted combination:

```
aggregate = build1 * 0.30 + build2 * 0.25 + build3 * 0.25 + integration * 0.20
```

Traffic light classification: GREEN >= 80, YELLOW >= 50, RED < 50.

---

## 8. Docker Architecture

### 5-File Compose Merge Strategy

The system uses a tiered Docker Compose merge architecture. Files are combined via `docker compose -f file1.yml -f file2.yml ... up`:

```
┌─────────────────────────────────────────────────────────────────────┐
│                   5-File Compose Merge Architecture                   │
│                                                                     │
│  Tier 0: docker-compose.infra.yml                                   │
│  ┌────────────────┐  ┌──────────────┐                               │
│  │  PostgreSQL 16  │  │  Redis 7     │                               │
│  │  :5432          │  │  :6379       │                               │
│  │  512MB limit    │  │  256MB limit │                               │
│  └───────┬────────┘  └──────┬───────┘                               │
│          │    Network: backend (bridge)    │                         │
│          └──────────────┬─────────────────┘                         │
│                         │                                           │
│  Tier 1: docker-compose.build1.yml                                  │
│  ┌──────────────┐  ┌──────────────────┐  ┌──────────────────────┐  │
│  │  Architect    │  │  Contract Engine  │  │  Codebase Intel      │  │
│  │  :8001->8000  │  │  :8002->8000     │  │  :8003->8000         │  │
│  │  768MB limit  │  │  768MB limit     │  │  768MB limit         │  │
│  └──────────────┘  └──────────────────┘  └──────────────────────┘  │
│          Networks: frontend + backend                               │
│                         │                                           │
│  Tier 2: docker-compose.traefik.yml                                 │
│  ┌───────────────────────────────────────────────────────────────┐  │
│  │  Traefik v3.6 -- API Gateway                                  │  │
│  │  :80 (web)  :8080 (dashboard, disabled)                       │  │
│  │  Docker socket: read-only mount                               │  │
│  │  PathPrefix routing for all services                          │  │
│  │  256MB limit                                                  │  │
│  └───────────────────────────────────────────────────────────────┘  │
│          Network: frontend                                          │
│                         │                                           │
│  Tier 3: docker-compose.generated.yml                               │
│  ┌──────────────┐  ┌──────────────────┐  ┌──────────────────────┐  │
│  │  auth-service │  │  order-service    │  │  notification-service│  │
│  │  :8080        │  │  :8080           │  │  :8080               │  │
│  │  /api/auth    │  │  /api/orders     │  │  /api/notifications  │  │
│  │  768MB limit  │  │  768MB limit     │  │  768MB limit         │  │
│  └──────────────┘  └──────────────────┘  └──────────────────────┘  │
│          Networks: frontend + backend                               │
│                         │                                           │
│  Tier 4: docker-compose.run4.yml                                    │
│  ┌───────────────────────────────────────────────────────────────┐  │
│  │  Overrides only -- no new services                            │  │
│  │  - Build 1 services join frontend network                     │  │
│  │  - Traefik labels for PathPrefix routing                      │  │
│  │  - LOG_LEVEL=DEBUG for all services                           │  │
│  │  - PostgreSQL: log_statement=all                              │  │
│  │  - Redis: loglevel debug                                      │  │
│  └───────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────┘
```

### Network Architecture

| Network | Type | Services |
|---------|------|----------|
| `backend` | bridge | PostgreSQL, Redis, Build 1 services, Generated services |
| `frontend` | bridge | Traefik, Build 1 services (via Run 4 override), Generated services |

### Startup Dependency Chain

```
PostgreSQL (healthy) ──> Contract Engine (healthy) ──> Architect
                    └──> Contract Engine (healthy) ──> Codebase Intelligence
                    └──> auth-service (healthy)    ──> order-service (healthy) ──> notification-service
Redis (healthy) ────────────────────────────────────────────────> notification-service
```

### Memory Budget

| Tier | Services | Per Service | Subtotal |
|------|----------|-------------|----------|
| Tier 0 | PostgreSQL + Redis | 512MB + 256MB | 768MB |
| Tier 1 | 3 Build 1 services | 768MB each | 2,304MB |
| Tier 2 | Traefik | 256MB | 256MB |
| Tier 3 | 3 Generated services | 768MB each | 2,304MB |
| **Total** | **9 containers** | | **~5.6GB** |

### Health Check Configuration

All application services use the same health check pattern:

```yaml
healthcheck:
  test: ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:8000/api/health')"]
  interval: 10s
  timeout: 5s
  retries: 5
  start_period: 10-20s  # varies by service
```

Generated services use `curl` to their `/health` endpoint on port 8080.

### Traefik PathPrefix Routing

| Route | Service | Port |
|-------|---------|------|
| `/api/architect` | architect | 8000 |
| `/api/contracts` | contract-engine | 8000 |
| `/api/codebase` | codebase-intelligence | 8000 |
| `/api/auth` | auth-service | 8080 |
| `/api/orders` | order-service | 8080 |
| `/api/notifications` | notification-service | 8080 |

---

## 9. Quality Gate Layers

The quality gate is a 4-layer sequential verification engine. Each layer must pass (or partially pass) before the next layer runs. If any layer fails, subsequent layers are set to SKIPPED.

### Layer Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                      QualityGateEngine                               │
│                                                                     │
│  ┌─────────────────────────────────────────────────────────────┐    │
│  │  Layer 1: Per-Service Build Evaluation (MUST PASS)          │    │
│  │                                                             │    │
│  │  For each builder result:                                   │    │
│  │  - Build success (source files exist?)                      │    │
│  │  - Test pass rate                                           │    │
│  │  - Convergence ratio                                        │    │
│  │  - Output validation (Dockerfile, source, tests present?)   │    │
│  └────────────────────────────┬────────────────────────────────┘    │
│                               │ PASS/PARTIAL -> promote             │
│  ┌────────────────────────────▼────────────────────────────────┐    │
│  │  Layer 2: Contract Compliance (MUST PASS or PARTIAL)        │    │
│  │                                                             │    │
│  │  - Contract validation against registered specs             │    │
│  │  - Breaking change detection                                │    │
│  │  - Implementation tracking verification                     │    │
│  │  - Cross-service contract consistency                       │    │
│  └────────────────────────────┬────────────────────────────────┘    │
│                               │ PASS/PARTIAL -> promote             │
│  ┌────────────────────────────▼────────────────────────────────┐    │
│  │  Layer 3: System-Level Scan (MUST PASS or PARTIAL)          │    │
│  │                                                             │    │
│  │  Configurable scanners:                                     │    │
│  │  - security: Secret detection, injection patterns           │    │
│  │  - cors: CORS configuration validation                      │    │
│  │  - logging: Structured logging presence                     │    │
│  │  - trace: Distributed tracing (X-Trace-ID) propagation      │    │
│  │  - secrets: Hardcoded credential detection                  │    │
│  │  - docker: Dockerfile security (non-root, HEALTHCHECK)      │    │
│  │  - health: Health endpoint verification                     │    │
│  └────────────────────────────┬────────────────────────────────┘    │
│                               │ PASS/PARTIAL -> promote             │
│  ┌────────────────────────────▼────────────────────────────────┐    │
│  │  Layer 4: Adversarial Analysis (ALWAYS ADVISORY)            │    │
│  │                                                             │    │
│  │  - Pattern-based adversarial checks                         │    │
│  │  - Edge case detection                                      │    │
│  │  - Security anti-pattern identification                     │    │
│  │  - Verdict always forced to PASSED (advisory only)          │    │
│  └─────────────────────────────────────────────────────────────┘    │
│                                                                     │
│  ┌─────────────────────────────────────────────────────────────┐    │
│  │  ScanAggregator                                             │    │
│  │  - Combines all layer results into QualityGateReport        │    │
│  │  - Computes overall_verdict (PASSED / FAILED / PARTIAL)     │    │
│  │  - Counts total_violations and blocking_violations          │    │
│  └─────────────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────────┘
```

### Layer 1: Per-Service Build Evaluation

Evaluates each builder's output individually:

- Did the build subprocess succeed?
- Were source files actually produced (not an empty success)?
- What percentage of tests pass?
- What is the convergence ratio?
- Are required artifacts present (Dockerfile, source code, test files)?

**Verdict:** PASSED if all builders pass, PARTIAL if some pass, FAILED if none pass.

### Layer 2: Contract Compliance

Validates that generated services honor their registered API contracts:

- Compares actual OpenAPI specs (from running services) against registered contracts
- Detects breaking changes using the Contract Engine's diff algorithm
- Verifies endpoint signatures, request/response schemas, and status codes
- Uses Schemathesis for property-based contract testing

**Verdict:** PASSED if all contracts comply, PARTIAL if minor deviations, FAILED if breaking changes detected.

### Layer 3: System-Level Scan

Scans all generated code for system-wide quality concerns:

| Scanner | Checks |
|---------|--------|
| `security` | SQL injection patterns, XSS vectors, path traversal, command injection |
| `cors` | CORS middleware presence, allowed origins configuration |
| `logging` | Structured logging setup, log level configuration |
| `trace` | X-Trace-ID header propagation, distributed tracing middleware |
| `secrets` | Hardcoded API keys, passwords, credentials in source |
| `docker` | Non-root user, HEALTHCHECK instruction, minimal base image |
| `health` | Health endpoint existence and proper response format |

**Verdict:** PASSED if no blocking violations, PARTIAL if warnings only, FAILED if errors found.

### Layer 4: Adversarial Analysis

Pattern-based adversarial checks that are always advisory (verdict forced to PASSED):

- Edge case patterns (empty inputs, large payloads, special characters)
- Security anti-patterns (eval usage, unsafe deserialization)
- Architectural anti-patterns (circular dependencies, god classes)
- Error handling gaps (uncaught exceptions, missing error boundaries)

**Verdict:** Always PASSED (advisory findings are logged but never block promotion).

### Fix Pass Integration

When the quality gate verdict is FAILED and `fix_attempts_remaining`:

1. Violations are extracted from the `QualityGateReport`
2. Each violation is classified by priority (P0-P3)
3. Violations are grouped by service
4. Violation snapshots are taken (before/after comparison)
5. Violations are fed to builder subprocesses via `ContractFixLoop`
6. After fix, regressions are detected
7. Convergence score is computed
8. Pipeline transitions back to `builders_running` for a rebuild

---

## 10. Test Coverage

### Test Suite Summary

The project maintains a comprehensive test suite across all components:

| Component | Test Directory | Test Files | Description |
|-----------|---------------|------------|-------------|
| Architect | `tests/test_architect/` | 6 | PRD parser, service boundary, domain modeler, validator, contract generator, routers |
| Contract Engine | `tests/test_contract_engine/` | 12 | OpenAPI/AsyncAPI validation, breaking changes, versioning, test generation, compliance, schema registry |
| Codebase Intelligence | `tests/test_codebase_intelligence/` | 14 | AST parsers (Python, TypeScript, C#, Go), symbol extraction, graph analysis, semantic search, dead code |
| Shared | `tests/test_shared/` | 6 | Models, config, constants, errors, DB connection, schema |
| Integration | `tests/test_integration/` | 6 | Cross-service workflows, Docker Compose, pipeline parametrized, 5-PRD pipeline |
| MCP | `tests/test_mcp/` | 3 | Architect MCP, Contract Engine MCP, Codebase Intelligence MCP |
| Build 3 | `tests/build3/` | 22 | State machine, CLI, quality gate, security scanner, Docker security, adversarial, compose generator, service discovery, contract compliance, fix loop |
| Run 4 | `tests/run4/` | 12+ | Infrastructure, MCP wiring, config generation, builder invocation, contract compliance, fix pass, audit, regression |
| E2E | `tests/e2e/api/` | 4 | Architect service, Contract Engine service, Codebase Intelligence service, cross-service workflow |
| **Total** | | **~95 test files** | |

### Test Categories

| Category | Count | Framework |
|----------|-------|-----------|
| Unit tests | ~700+ | pytest |
| Integration tests | ~100+ | pytest + httpx |
| MCP tests | ~50+ | pytest + mcp SDK |
| E2E tests | ~50+ | pytest + Docker |
| Performance benchmarks | 27 | pytest-benchmark |
| **Total** | **985+** | |

### Running Tests

```bash
# Full suite
pytest tests/ -v

# With coverage report
pytest tests/ -v --cov=src --cov-report=term-missing

# Specific component
pytest tests/test_architect/ -v
pytest tests/test_contract_engine/ -v
pytest tests/test_codebase_intelligence/ -v
pytest tests/build3/ -v
pytest tests/run4/ -v
pytest tests/e2e/ -v

# Performance benchmarks only
pytest tests/ -v -k "benchmark or performance"
```

### Quality Verification Results (Latest)

From the most recent Build 3 audit (SCORE_CARD.md):

| Category | Earned | Max | Percentage |
|----------|--------|-----|:----------:|
| Functional Requirements (70 REQs) | 350 | 350 | 100.0% |
| Technical Requirements (32 TECHs) | 160 | 160 | 100.0% |
| Wiring Requirements (22 WIREs) | 110 | 110 | 100.0% |
| Test Requirements (40 TESTs) | 200 | 200 | 100.0% |
| SVC Wiring (11 SVCs) | 55 | 55 | 100.0% |
| Integration Requirements (8 INTs) | 40 | 40 | 100.0% |
| Security Requirements (4 SECs) | 20 | 20 | 100.0% |
| Run 4 Contract (7 checks) | 35 | 35 | 100.0% |
| Library API Correctness (8 libs) | 40 | 40 | 100.0% |
| Test Suite Health | 50 | 50 | 100.0% |
| Code Quality | 40 | 40 | 100.0% |
| **TOTAL** | **1100** | **1100** | **100.0%** |

---

## Appendix: Technology Stack

| Category | Technology | Version |
|----------|-----------|---------|
| Language | Python | 3.12 |
| Web Framework | FastAPI | 0.129.0 |
| ASGI Server | Uvicorn | latest |
| Data Validation | Pydantic v2 | latest |
| Configuration | pydantic-settings | latest |
| CLI Framework | Typer | latest |
| State Machine | transitions (AsyncMachine) | latest |
| Database | SQLite (WAL mode) | built-in |
| Vector Store | ChromaDB | 1.5.0 |
| Graph Engine | NetworkX | 3.6.1 |
| AST Parsing | tree-sitter | 0.25.2 |
| MCP Integration | MCP SDK | >=1.25, <2 |
| Contract Testing | Schemathesis | 4.10.1 |
| OpenAPI Validation | openapi-spec-validator, prance | >=0.7.0 |
| Schema Validation | jsonschema | latest |
| HTTP Client | httpx | >=0.27.0 |
| Containerization | Docker, Docker Compose | v2 |
| API Gateway | Traefik | v3.6 |
| Infrastructure DB | PostgreSQL | 16 |
| Infrastructure Cache | Redis | 7 |
| Terminal Display | Rich | latest |
| Testing | pytest, pytest-asyncio, pytest-benchmark | latest |

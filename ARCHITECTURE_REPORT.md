# Architecture Report: Persistent Intelligence Layer Discovery

> **Report Type:** Discovery Agent Output (Phases 1A-1H)
> **Generated:** 2026-02-23
> **Scope:** Data lifecycle, storage infrastructure, architect decomposition, contract engine, quality gate scanners, MCP servers, config/depth-gating, test infrastructure
> **Status:** READ ONLY -- No source files modified

---

## Table of Contents

- [Phase 1A: Data Lifecycle](#phase-1a-data-lifecycle)
- [Phase 1B: Storage Infrastructure](#phase-1b-storage-infrastructure)
- [Phase 1C: Architect Decomposition Pipeline](#phase-1c-architect-decomposition-pipeline)
- [Phase 1D: Contract Engine](#phase-1d-contract-engine)
- [Phase 1E: Quality Gate Scanners](#phase-1e-quality-gate-scanners)
- [Phase 1F: MCP Server Patterns](#phase-1f-mcp-server-patterns)
- [Phase 1G: Config and Depth-Gating](#phase-1g-config-and-depth-gating)
- [Phase 1H: Test Infrastructure](#phase-1h-test-infrastructure)
- [DATA GAP Summary](#data-gap-summary)

---

## Phase 1A: Data Lifecycle

### 1A.1 Pipeline State Machine

**File:** `src/super_orchestrator/pipeline.py` (lines 1-77)

The pipeline is state-machine-driven with the following phase sequence:

```
architect -> contract_registration -> builders -> integration
-> quality_gate -> (fix_pass loop) -> complete
```

Phase names are defined in `src/build3_shared/constants.py` (lines 8-16):

| Constant | Value |
|----------|-------|
| `PHASE_ARCHITECT` | `"architect"` |
| `PHASE_ARCHITECT_REVIEW` | `"architect_review"` |
| `PHASE_CONTRACT_REGISTRATION` | `"contract_registration"` |
| `PHASE_BUILDERS` | `"builders"` |
| `PHASE_INTEGRATION` | `"integration"` |
| `PHASE_QUALITY_GATE` | `"quality_gate"` |
| `PHASE_FIX_PASS` | `"fix_pass"` |
| `PHASE_COMPLETE` | `"complete"` |
| `PHASE_FAILED` | `"failed"` |

Phase timeouts (`src/build3_shared/constants.py`, lines 31-39):

| Phase | Timeout (seconds) |
|-------|-------------------|
| architect | 900 |
| architect_review | 300 |
| contract_registration | 180 |
| builders | 3600 |
| integration | 600 |
| quality_gate | 600 |
| fix_pass | 900 |

### 1A.2 PipelineState Persistence

**File:** `src/super_orchestrator/state.py` (126 lines)

`PipelineState` is a dataclass with ~30 fields persisted to `PIPELINE_STATE.json` via atomic writes.

**Fields that survive pipeline restarts (persisted to disk):**

| Field | Type | Default | Purpose |
|-------|------|---------|---------|
| `pipeline_id` | `str` | `uuid4()` | Unique pipeline run ID |
| `prd_path` | `str` | `""` | Path to PRD input file |
| `config_path` | `str` | `""` | Path to config YAML |
| `depth` | `str` | `"thorough"` | Pipeline depth |
| `current_state` | `str` | `"init"` | Current state machine state |
| `previous_state` | `str` | `""` | Previous state |
| `completed_phases` | `list[str]` | `[]` | Phases completed so far |
| `phase_artifacts` | `dict[str, Any]` | `{}` | Artifacts produced per phase |
| `architect_retries` | `int` | `0` | Architect retry counter |
| `service_map_path` | `str` | `""` | Path to service_map.json |
| `contract_registry_path` | `str` | `""` | Path to contracts dir |
| `domain_model_path` | `str` | `""` | Path to domain_model.json |
| `builder_statuses` | `dict[str, str]` | `{}` | Per-builder status |
| `builder_costs` | `dict[str, float]` | `{}` | Per-builder cost |
| `builder_results` | `dict[str, dict]` | `{}` | Per-builder result dicts |
| `total_builders` | `int` | `0` | Total builder count |
| `successful_builders` | `int` | `0` | Successful builder count |
| `services_deployed` | `list[str]` | `[]` | Services deployed |
| `integration_report_path` | `str` | `""` | Path to integration report |
| `quality_attempts` | `int` | `0` | Quality gate attempts |
| `last_quality_results` | `dict[str, Any]` | `{}` | Last QG results |
| `quality_report_path` | `str` | `""` | Path to QG report |
| `total_cost` | `float` | `0.0` | Cumulative cost |
| `phase_costs` | `dict[str, float]` | `{}` | Per-phase costs |
| `budget_limit` | `float \| None` | `None` | Budget cap |
| `started_at` | `str` | ISO timestamp | Pipeline start time |
| `updated_at` | `str` | ISO timestamp | Last update time |
| `interrupted` | `bool` | `False` | Interrupted flag |
| `interrupt_reason` | `str` | `""` | Reason for interrupt |
| `schema_version` | `int` | `1` | State schema version |

**Persistence mechanism** (`state.py`, lines 68-85):

- `save()` calls `atomic_write_json(target, self.to_dict())`
- Target: `{STATE_DIR}/PIPELINE_STATE.json` (default: `.super-orchestrator/PIPELINE_STATE.json`)
- `to_dict()` uses `dataclasses.asdict(self)` (line 66)

**Load mechanism** (`state.py`, lines 87-109):

- `load()` calls `load_json(target)` then filters to known fields (line 107-108)
- Unknown fields are silently dropped for forward compatibility

### 1A.3 Atomic Write Pattern

**File:** `src/build3_shared/utils.py` (lines 11-31)

```python
def atomic_write_json(path, data):
    tmp_path = path.with_suffix(".tmp")
    with open(tmp_path, "w") as f:
        json.dump(data, f, indent=2, default=str)
        f.flush()
        os.fsync(f.fileno())
    os.replace(str(tmp_path), str(path))
```

Pattern: Write to `.tmp` file -> `flush()` + `os.fsync()` -> `os.replace()` for atomicity.

### 1A.4 Data Survival Table

| Data | Persists to Disk? | Location | Mechanism |
|------|-------------------|----------|-----------|
| PipelineState | YES | `.super-orchestrator/PIPELINE_STATE.json` | `atomic_write_json` |
| service_map | YES | `.super-orchestrator/service_map.json` | `atomic_write_json` |
| domain_model | YES | `.super-orchestrator/domain_model.json` | `atomic_write_json` |
| contract_stubs | YES | `.super-orchestrator/contracts/stubs.json` | `atomic_write_json` |
| Architect DB data | YES | `./data/architect.db` | SQLite (WAL) |
| Contracts DB data | YES | `./data/contracts.db` | SQLite (WAL) |
| Symbols DB data | YES | `./data/symbols.db` | SQLite (WAL) |
| Graph RAG DB | YES | `./data/graph_rag.db` | SQLite (WAL) |
| ChromaDB vectors | YES | `./data/chroma/` | ChromaDB PersistentClient |
| Graph RAG vectors | YES | `./data/graph_rag_chroma/` | ChromaDB PersistentClient |
| QualityGateReport | YES (path) | `state.quality_report_path` | Markdown file |
| IntegrationReport | YES (path) | `state.integration_report_path` | JSON file |
| BuilderResult | YES (dict) | `state.builder_results[service_id]` | via PipelineState.save() |
| **FixPassResult** | **NO** | In-memory only | **DATA GAP-01** |
| **LayerResult** | **NO** | Transient (QualityGateReport) | **DATA GAP-02** |
| **ConvergenceResult** | **NO** | FixPassResult.convergence (in-memory) | **DATA GAP-03** |
| **FixPassMetrics** | **NO** | FixPassResult.metrics (in-memory) | **DATA GAP-04** |

### 1A.5 Build 3 Shared Models

**File:** `src/build3_shared/models.py` (129 lines)

All Build 3 models are plain `dataclass` (NOT Pydantic):

| Class | Fields (key) | Lines |
|-------|-------------|-------|
| `ServiceStatus` | Enum: PENDING, BUILDING, BUILT, DEPLOYING, HEALTHY, UNHEALTHY, FAILED | 9-17 |
| `QualityLevel` | Enum: LAYER1_SERVICE, LAYER2_CONTRACT, LAYER3_SYSTEM, LAYER4_ADVERSARIAL | 20-25 |
| `GateVerdict` | Enum: PASSED, FAILED, PARTIAL, SKIPPED | 28-33 |
| `ServiceInfo` | service_id, domain, stack, estimated_loc, docker_image, health_endpoint, port, status, build_cost, build_dir | 36-49 |
| `BuilderResult` | system_id, service_id, success, cost, error, output_dir, test_passed, test_total, convergence_ratio, artifacts | 52-63 |
| `ContractViolation` | code, severity, service, endpoint, message, expected, actual, file_path | 66-77 |
| `ScanViolation` | code, severity, category, file_path, line, service, message | 80-88 |
| `LayerResult` | layer, verdict, violations, contract_violations, total_checks, passed_checks, duration_seconds | 91-100 |
| `QualityGateReport` | layers, overall_verdict, fix_attempts, max_fix_attempts, total_violations, blocking_violations | 103-111 |
| `IntegrationReport` | services_deployed, services_healthy, contract_tests_*, integration_tests_*, data_flow_tests_*, boundary_tests_*, violations, overall_health | 114-129 |

### 1A.6 Quality Gate Engine

**File:** `src/quality_gate/gate_engine.py` (282 lines)

`QualityGateEngine` orchestrates 4 layers sequentially with gating logic:

- Layer 1 (Per-Service) -- must PASS before Layer 2 runs
- Layer 2 (Contract) -- must PASS or PARTIAL before Layer 3 runs
- Layer 3 (System-Level) -- must PASS or PARTIAL before Layer 4 runs
- Layer 4 (Adversarial) -- always advisory-only (verdict forced to PASSED)

**`should_promote()` method** (lines 222-254):
- `PASSED` and `PARTIAL` allow promotion
- `FAILED` and `SKIPPED` block subsequent layers
- Additional check: if all violations are below `blocking_severity`, layer is promoted

**`classify_violations()` method** (lines 256-281):
- Groups violations by severity: `error`, `warning`, `info`
- Unknown severities are bucketed under `info`

### 1A.7 Fix Pass Pipeline

**File:** `src/run4/fix_pass.py` (931 lines)

**6-step fix cycle:** DISCOVER, CLASSIFY, GENERATE, APPLY, VERIFY, REGRESS

**`FixPassResult` dataclass** (lines 560-604):

| Field | Type | Purpose |
|-------|------|---------|
| `pass_number` | `int` | Current pass number |
| `status` | `str` | `"pending"`, `"in_progress"`, `"completed"` |
| `steps_completed` | `list[str]` | Steps executed (DISCOVER, CLASSIFY, etc.) |
| `violations_discovered` | `int` | Count from DISCOVER step |
| `p0_count` / `p1_count` / `p2_count` / `p3_count` | `int` | Classified counts |
| `fixes_generated` / `fixes_applied` / `fixes_verified` | `int` | Fix tracking |
| `regressions_found` | `int` | Regression count |
| `metrics` | `FixPassMetrics` | Computed metrics |
| `convergence` | `ConvergenceResult` | Convergence decision |
| `cost_usd` | `float` | Pass cost |
| `duration_s` | `float` | Pass duration |
| `snapshot_before` / `snapshot_after` | `dict` | Violation snapshots |

**`classify_priority()` function** (lines 153-244):
- Decision tree: P0 (system cannot start), P1 (primary use case fails), P2 (secondary feature broken), P3 (cosmetic)
- Graph RAG impact promotion: if `graph_rag_client` is provided, nodes impacting >=10 nodes are promoted to P0, >=3 nodes to P1

**`check_convergence()` function** (lines 403-552):
- 5 hard stops: P0==0 AND P1==0, max passes reached, budget exhausted, effectiveness below 30%, regression rate above 25%
- 2 soft convergence conditions: convergence score >= 0.85, PRD REQ-033 four-condition check

**`run_fix_loop()` function** (lines 801-931):
- Iterates `execute_fix_pass()` up to `max_fix_passes` (default 5)
- Checks convergence after each pass
- Returns `list[FixPassResult]`

### 1A.8 Contract Fix Loop (Integrator)

**File:** `src/integrator/fix_loop.py` (159 lines)

`ContractFixLoop` class:
- `classify_violations()` (lines 41-61): Groups `ContractViolation` by severity (critical, error, warning, info)
- `feed_violations_to_builder()` (lines 67-159): Writes `FIX_INSTRUCTIONS.md` via `write_fix_instructions()`, launches `agent_team` subprocess with `--depth quick`, parses `STATE.json` result
- Builder invoked via: `sys.executable -m agent_team --cwd {builder_dir} --depth quick`
- Timeout configurable via `config.builder.timeout` (default 1800s)
- Environment keys filtered: `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `AWS_SECRET_ACCESS_KEY`

### 1A.9 Quality Gate Report

**File:** `src/quality_gate/report.py` (392 lines)

Pure function `generate_quality_gate_report()` producing Markdown:
- Header with overall verdict
- Per-layer results table
- Violations grouped by severity (error -> warning -> info)
- Actionable recommendations

Verdict display mapping (lines 32-37):
- PASSED: checkmark icon
- FAILED: cross icon
- PARTIAL: warning icon
- SKIPPED: skip icon

---

## Phase 1B: Storage Infrastructure

### 1B.1 SQLite Connection Pool

**File:** `src/shared/db/connection.py` (74 lines)

`ConnectionPool` pattern:
1. **Thread-local storage** via `threading.local()` (line 24)
2. **WAL mode**: `PRAGMA journal_mode=WAL` (line 46)
3. **Busy timeout**: `PRAGMA busy_timeout=30000` (30 seconds, from `DB_BUSY_TIMEOUT_MS` in `src/shared/constants.py`)
4. **Foreign keys**: `PRAGMA foreign_keys=ON` (line 48)
5. **Row factory**: `sqlite3.Row` for dict-like access (line 49)
6. **Parent dir creation**: `self._db_path.parent.mkdir(parents=True, exist_ok=True)` (line 29)

### 1B.2 Six-Step Pattern for New SQLite-Backed Modules

Based on the existing patterns across architect, contract-engine, and codebase-intelligence:

1. **Define schema** in `src/shared/db/schema.py` -- Add `init_{module}_db(pool)` function with `CREATE TABLE IF NOT EXISTS` and indexes
2. **Create storage class** (e.g., `src/{module}/storage/{name}_store.py`) -- CRUD methods taking `ConnectionPool`
3. **Module-level init in MCP server** -- `pool = ConnectionPool(db_path); init_{module}_db(pool); store = Store(pool)`
4. **Lifespan init in FastAPI main** -- Same pattern as MCP but inside `@asynccontextmanager` lifespan
5. **Register in `.mcp.json`** -- Add `DATABASE_PATH` env var for the MCP server
6. **Add config dataclass** in `src/super_orchestrator/config.py` -- Add to `SuperOrchestratorConfig`

### 1B.3 Database Schema Overview

**File:** `src/shared/db/schema.py` (256 lines)

| Init Function | Tables Created | Lines |
|---------------|---------------|-------|
| `init_architect_db(pool)` | `service_maps`, `domain_models`, `decomposition_runs` | 7-43 |
| `init_contracts_db(pool)` | `build_cycles`, `contracts`, `contract_versions`, `breaking_changes`, `implementations`, `test_suites`, `shared_schemas`, `schema_consumers` | 46-154 |
| `init_symbols_db(pool)` | `indexed_files`, `symbols`, `dependency_edges`, `import_references`, `graph_snapshots` | 157-238 |
| `init_graph_rag_db(pool)` | `graph_rag_snapshots` | 241-255 |

Key schema patterns:
- All tables use `TEXT PRIMARY KEY` (UUIDs as strings)
- Timestamps: `TEXT NOT NULL DEFAULT (datetime('now'))`
- Status enums: `CHECK(status IN (...))` constraints
- Foreign keys with `ON DELETE CASCADE` or `ON DELETE SET NULL`
- Indexes on all query-targeted columns

### 1B.4 ChromaDB Vector Storage

**File:** `src/codebase_intelligence/storage/chroma_store.py` (188 lines)

`ChromaStore` pattern:
- **Client**: `chromadb.PersistentClient(path=chroma_path)` (line 31)
- **Embedding function**: `DefaultEmbeddingFunction()` -- `all-MiniLM-L6-v2` (line 32)
- **Collection**: `"code_chunks"` with cosine distance (`metadata={"hnsw:space": "cosine"}`) (lines 33-37)
- **ID format**: `file_path::symbol_name` (from `SymbolDefinition.id`)
- **Operations**: `add_chunks()`, `query()`, `delete_by_file()`, `get_stats()`

### 1B.5 Graph Snapshot Storage

**File:** `src/codebase_intelligence/storage/graph_db.py` (174 lines)

`GraphDB` pattern:
- `save_snapshot()`: Serializes NetworkX graph via `nx.node_link_data(graph, edges="edges")`
- `load_snapshot()`: Deserializes via `nx.node_link_graph(data, edges="edges")`
- `save_edges()`: Persists `DependencyEdge` to `dependency_edges` table
- `delete_by_file()`: Removes edges by source or target file

### 1B.6 Symbol Database

**File:** `src/codebase_intelligence/storage/symbol_db.py` (270 lines)

`SymbolDB` operations:
- `save_file()`: Inserts/updates `indexed_files` row
- `save_symbols()`: Inserts into `symbols` table with all metadata
- `save_imports()`: Inserts into `import_references` table
- `query_by_name()`: Searches symbols by name (exact match)
- `query_by_file()`: Retrieves all symbols for a file
- `update_chroma_id()`: Links symbol to ChromaDB vector
- `delete_by_file()`: Cascading delete of file + symbols + imports

---

## Phase 1C: Architect Decomposition Pipeline

### 1C.1 Decomposition Pipeline Steps

**File:** `src/architect/mcp_server.py` (lines 46-59 for init, tool at ~line 60+)

The `decompose` MCP tool runs a 7-step pipeline:

1. **`parse_prd(prd_text)`** -- `src/architect/services/prd_parser.py` (1639 lines)
   - 5 entity extraction strategies: tables, headings, sentences, data model sections, terse patterns
   - Relationship extraction, bounded context detection, technology hints, state machine detection
   - Returns parsed PRD with entities, relationships, contexts

2. **`identify_boundaries(parsed)`** -- `src/architect/services/service_boundary.py` (445 lines)
   - 4-step algorithm: explicit contexts, aggregate root discovery, relationship-based assignment, monolith fallback

3. **`build_service_map(boundaries, parsed)`** -- `src/architect/services/service_boundary.py`
   - Converts boundaries to `ServiceMap` with `ServiceDefinition` list

4. **`build_domain_model(parsed, boundaries)`** -- `src/architect/services/domain_modeler.py` (369 lines)
   - Creates `DomainEntity` + `DomainRelationship` list with state machine detection

5. **`generate_contract_stubs(service_map)`** -- `src/architect/services/contract_generator.py` (331 lines)
   - Produces OpenAPI 3.1 specs with CRUD endpoints per entity

6. **`validate_decomposition(service_map, domain_model)`** -- `src/architect/services/validator.py` (211 lines)
   - 7 checks: circular deps (NetworkX), entity overlap, orphans, completeness, relationship consistency, name uniqueness, contract consistency

7. **Persist results** -- `ServiceMapStore.save()`, `DomainModelStore.save()`

### 1C.2 Pydantic v2 Models (Architect)

**File:** `src/shared/models/architect.py` (150 lines)

Key models (all Pydantic v2 `BaseModel`):
- `ServiceStack`: language, framework, database
- `ServiceDefinition`: name (pattern `^[a-z][a-z0-9-]*$`), domain, description, stack, estimated_loc, owns_entities, provides/consumes_contracts
- `EntityField`: name, type, required, description
- `StateTransition`: from_state, to_state, trigger, guard
- `StateMachine`: entity_name, states, transitions
- `DomainEntity`: name, description, owning_service, fields, state_machine
- `DomainRelationship`: source_entity, target_entity, relationship_type, cardinality (pattern `^(1|N):(1|N)$`)
- `DomainModel`: entities, relationships, bounded_contexts
- `ServiceMap`: services, relationships, project_name, prd_hash
- `DecompositionResult`: service_map, domain_model, validation_errors, contract_stubs

### 1C.3 Insertion Points for Pre-Validation and Acceptance Tests

For a Persistent Intelligence Layer that needs to hook into the decomposition pipeline:

| Insertion Point | File | Location | Purpose |
|----------------|------|----------|---------|
| Post-parse hook | `src/architect/services/prd_parser.py` | After `parse_prd()` returns | Store parsed entities/relationships |
| Post-validation hook | `src/architect/services/validator.py` | After `validate_decomposition()` | Store validation results with patterns |
| Post-persist hook | `src/architect/mcp_server.py` | After `service_map_store.save()` | Index decomposition for pattern learning |
| Pre-decompose hook | `src/architect/mcp_server.py` | Before `parse_prd()` | Inject learned patterns as context |

---

## Phase 1D: Contract Engine

### 1D.1 Contract Test Generator

**File:** `src/contract_engine/services/test_generator.py` (605 lines)

`ContractTestGenerator` class:
- **OpenAPI tests**: Generates Schemathesis-based tests with parameterized endpoints
- **AsyncAPI tests**: Generates jsonschema validation tests
- **Caching**: Via `test_suites` table keyed by `(contract_id, framework, include_negative)` and `spec_hash`
- **Frameworks**: `pytest` (default), `jest`

### 1D.2 Contract Engine MCP Server

**File:** `src/contract_engine/mcp_server.py` (472 lines)

10 MCP tools:

| Tool | Purpose |
|------|---------|
| `create_contract` | Create/upsert a contract (openapi, asyncapi, json_schema) |
| `list_contracts` | Query contracts with optional filters |
| `get_contract` | Retrieve single contract by ID |
| `validate_spec` | Validate spec without persisting |
| `check_breaking_changes` | Compare current vs new spec |
| `mark_implemented` | Record implementation evidence |
| `get_unimplemented_contracts` | Find contracts without implementations |
| `generate_tests` | Generate test suites from contract |
| `check_compliance` | Check runtime data against contract |
| `validate_endpoint` | Validate a single endpoint response |

Module-level init (lines 46-52):
```python
pool = ConnectionPool(_database_path)
init_contracts_db(pool)
# ... 5 service objects instantiated
```

### 1D.3 Pipeline Contract Registration

**File:** `src/super_orchestrator/pipeline.py` (lines ~456-570)

`run_contract_registration()`:
- Reads contract stubs from `state.contract_registry_path`
- Attempts MCP registration via `ContractEngineClient.create_contract()`
- Filesystem fallback: writes contracts to `{output_dir}/contracts/{service_name}.json`
- Updates `state.phase_artifacts[PHASE_CONTRACT_REGISTRATION]`

### 1D.4 Insertion Points for Acceptance Test Generation

| Insertion Point | File | Location | Purpose |
|----------------|------|----------|---------|
| Post-contract-create | `src/contract_engine/mcp_server.py` | After `create_contract` tool | Trigger acceptance test generation |
| Post-test-generate | `src/contract_engine/services/test_generator.py` | After test code generated | Store generated tests as patterns |
| Pre-compliance-check | `src/contract_engine/mcp_server.py` | Before `check_compliance` tool | Inject learned compliance patterns |

---

## Phase 1E: Quality Gate Scanners

### 1E.1 Scanner Protocol

All scanners implement the async scan protocol:

```python
async def scan(self, target_dir: Path) -> list[ScanViolation]
```

**SecurityScanner** (`src/quality_gate/security_scanner.py`, 622 lines):
- `EXCLUDED_DIRS`: `frozenset({"node_modules", ".venv", "venv", "__pycache__", ".git", "dist", "build"})` (lines 25-27)
- `SCANNABLE_EXTENSIONS`: 16 extensions including `.py`, `.js`, `.ts`, `.yaml`, `.json`, `.env` (lines 31-36)
- `MAX_VIOLATIONS_PER_CATEGORY`: 200 (line 29)
- `_NOSEC_PATTERN`: Regex for `# nosec` / `// noqa:SEC-xxx` suppression (lines 42-45)

Scan code categories:
- JWT Security: SEC-001..SEC-006 (6 codes)
- CORS: CORS-001..CORS-003 (3 codes)
- Secret Detection: SEC-SECRET-001..SEC-SECRET-012 (12 codes)

**Layer3Scanner** (`src/quality_gate/layer3_system_level.py`, 233 lines):
- Composes: `SecurityScanner`, `ObservabilityChecker`, `DockerSecurityScanner`
- Runs all three via `asyncio.gather()` concurrently
- Per-category violation cap: 200 (`MAX_VIOLATIONS_PER_CATEGORY`)
- Verdict logic: any `error` -> FAILED, any `warning` (no errors) -> PARTIAL, no violations/only `info` -> PASSED

### 1E.2 Full Scan Code Catalog

**File:** `src/build3_shared/constants.py` (lines 44-128)

| Category | Code Range | Count |
|----------|-----------|-------|
| JWT Security | SEC-001..SEC-006 | 6 |
| CORS | CORS-001..CORS-003 | 3 |
| Secret Detection | SEC-SECRET-001..SEC-SECRET-012 | 12 |
| Logging | LOG-001, LOG-004, LOG-005 | 3 |
| Trace Propagation | TRACE-001 | 1 |
| Health Endpoints | HEALTH-001 | 1 |
| Docker Security | DOCKER-001..DOCKER-008 | 8 |
| Adversarial | ADV-001..ADV-006 | 6 |
| **Total** | | **40** |

Assertion at line 128: `assert len(ALL_SCAN_CODES) == 40`

### 1E.3 Scanner Registration Pattern

To add a new scanner category:

1. Define scan codes in `src/build3_shared/constants.py`
2. Create scanner class in `src/quality_gate/{scanner_name}.py` implementing `async def scan(self, target_dir: Path) -> list[ScanViolation]`
3. Register in `Layer3Scanner.__init__()` at `src/quality_gate/layer3_system_level.py` (line 68-71)
4. Add to `asyncio.gather()` in `Layer3Scanner.evaluate()` (implicit from list)
5. Add category prefix to `_KNOWN_CATEGORIES` tuple (line 43-51)
6. Update `QualityGateConfig.layer3_scanners` default in `src/super_orchestrator/config.py` (line 46-48)

### 1E.4 Quality Gate 4-Layer Architecture

**File:** `src/quality_gate/gate_engine.py` (282 lines)

| Layer | Scanner | Method | Sync/Async | Gating |
|-------|---------|--------|------------|--------|
| Layer 1 | `Layer1Scanner` | `evaluate(builder_results)` | Sync | Must PASS to continue |
| Layer 2 | `Layer2Scanner` | `evaluate(integration_report)` | Sync | Must PASS or PARTIAL |
| Layer 3 | `Layer3Scanner` | `evaluate(target_dir)` | Async | Must PASS or PARTIAL |
| Layer 4 | `Layer4Scanner` | `evaluate(target_dir)` | Async | Advisory-only |

Layer 4 receives `graph_rag_client` in constructor (line 67):
```python
self._layer4 = Layer4Scanner(graph_rag_client=graph_rag_client)
```

---

## Phase 1F: MCP Server Patterns

### 1F.1 Existing MCP Servers

**File:** `.mcp.json` (28 lines)

| Server Name | Module | Database | Port |
|-------------|--------|----------|------|
| `architect` | `src.architect.mcp_server` | `./data/architect.db` | N/A (stdio) |
| `contract-engine` | `src.contract_engine.mcp_server` | `./data/contracts.db` | N/A (stdio) |
| `codebase-intelligence` | `src.codebase_intelligence.mcp_server` | `./data/symbols.db` + `./data/chroma` + `./data/graph.json` | N/A (stdio) |

Additionally (not in .mcp.json but exists):
| `graph-rag` | `src.graph_rag.mcp_server` | `./data/graph_rag.db` + `./data/graph_rag_chroma` + 3 read-only DBs | N/A (stdio) |

### 1F.2 MCP Server Template Pattern

All 4 MCP servers follow the same structure:

```python
# 1. Imports
from mcp.server.fastmcp import FastMCP
from src.shared.db.connection import ConnectionPool
from src.shared.db.schema import init_{module}_db

# 2. Module-level init
_database_path = os.environ.get("DATABASE_PATH", "./data/{module}.db")
pool = ConnectionPool(_database_path)
init_{module}_db(pool)
# ... storage/service instantiation ...

# 3. MCP server instance
mcp = FastMCP("{ServerName}")

# 4. Tool definitions with @mcp.tool() decorator
@mcp.tool()
def tool_name(param1: str, param2: int = 0) -> dict:
    """Google-style docstring."""
    try:
        # ... business logic ...
        return result_dict
    except SomeError as exc:
        return {"error": str(exc)}
    except Exception as exc:
        logger.error("Unexpected error: %s", exc)
        return {"error": f"Internal error: {exc}"}
```

### 1F.3 Three-Tier Exception Handling Pattern

All MCP tools use consistent exception handling:

```python
@mcp.tool()
def some_tool(...) -> dict:
    try:
        # Business logic
        return result
    except AppError as exc:        # Tier 1: Known application errors
        return {"error": exc.message}
    except Exception as exc:       # Tier 2: Unexpected errors
        logger.error("...", exc)
        return {"error": f"Internal error: {exc}"}
```

Some tools add a third tier for specific exceptions (e.g., `ParsingError`, `NotFoundError`).

### 1F.4 Graph RAG MCP Server (4th Server)

**File:** `src/graph_rag/mcp_server.py` (lines 1-60)

7 MCP tools, read-only access to 3 external databases:

| Env Variable | Default Path | Access |
|-------------|--------------|--------|
| `GRAPH_RAG_DB_PATH` | `./data/graph_rag.db` | Read/Write |
| `GRAPH_RAG_CHROMA_PATH` | `./data/graph_rag_chroma` | Read/Write |
| `CI_DATABASE_PATH` | `./data/codebase_intel.db` | Read-only |
| `ARCHITECT_DATABASE_PATH` | `./data/architect.db` | Read-only |
| `CONTRACT_DATABASE_PATH` | `./data/contracts.db` | Read-only |

4 ConnectionPools created at module level (lines 56-59).

### 1F.5 Adding a New MCP Server

To add a Persistence Intelligence MCP server:

1. Create `src/persistence_intelligence/mcp_server.py` following the template in 1F.2
2. Add `init_persistence_db(pool)` to `src/shared/db/schema.py`
3. Register in `.mcp.json` with appropriate env vars
4. Add `PersistenceConfig` section to `src/super_orchestrator/config.py` (already exists at lines 72-79)
5. Create `src/persistence_intelligence/mcp_client.py` with retry pattern (3 retries, 1s exponential backoff)
6. Wire into pipeline phases that need persistence lookups

### 1F.6 MCP Tool Count Summary

| Server | Tool Count |
|--------|-----------|
| Architect | 4 |
| Contract Engine | 10 |
| Codebase Intelligence | 8 |
| Graph RAG | 7 |
| **Total** | **29** |

---

## Phase 1G: Config and Depth-Gating

### 1G.1 Configuration Architecture

**File:** `src/super_orchestrator/config.py` (150 lines)

```
SuperOrchestratorConfig
  |-- ArchitectConfig (max_retries, timeout, auto_approve)
  |-- BuilderConfig (max_concurrent, timeout_per_builder, depth)
  |-- IntegrationConfig (timeout, traefik_image, compose_file, test_compose_file)
  |-- QualityGateConfig (max_fix_retries, layer3_scanners, layer4_enabled, blocking_severity)
  |-- GraphRAGConfig (enabled, mcp_command, mcp_args, database_path, chroma_path, ...)
  |-- PersistenceConfig (enabled, db_path, chroma_path, max_patterns_per_injection, min_occurrences_for_promotion)
  |-- budget_limit, depth, phase_timeouts, mode, output_dir, ...
```

### 1G.2 PersistenceConfig (Already Defined)

**File:** `src/super_orchestrator/config.py` (lines 72-79)

```python
@dataclass
class PersistenceConfig:
    enabled: bool = False
    db_path: str = ".super-orchestrator/persistence.db"
    chroma_path: str = ".super-orchestrator/pattern-store"
    max_patterns_per_injection: int = 5
    min_occurrences_for_promotion: int = 10
```

This config is already wired into `SuperOrchestratorConfig` (line 91):
```python
persistence: PersistenceConfig = field(default_factory=PersistenceConfig)
```

And loaded from YAML (line 134, 147):
```python
persistence_raw = raw.get("persistence", {})
# ...
persistence=PersistenceConfig(**_pick(persistence_raw, PersistenceConfig)),
```

### 1G.3 Feature Flags and Depth-Gating

| Feature Flag | Config Location | Default | Effect |
|-------------|----------------|---------|--------|
| `layer4_enabled` | `QualityGateConfig` (line 50) | `True` | Controls whether adversarial analysis runs |
| `graph_rag.enabled` | `GraphRAGConfig` (line 57) | `True` | Controls Graph RAG module activation |
| `persistence.enabled` | `PersistenceConfig` (line 75) | `False` | Controls Persistent Intelligence Layer |
| `architect.auto_approve` | `ArchitectConfig` (line 18) | `False` | Auto-approve decomposition results |
| `depth` | `SuperOrchestratorConfig` (line 93) | `"standard"` | Pipeline depth (standard/thorough) |
| `mode` | `SuperOrchestratorConfig` (line 97) | `"auto"` | `"docker"`, `"mcp"`, or `"auto"` |

### 1G.4 YAML Config Loading

**File:** `src/super_orchestrator/config.py` (lines 101-149)

`load_super_config(path)`:
- Returns defaults if `path` is `None` or file doesn't exist
- Uses `_pick(data, cls)` helper to filter to known dataclass fields
- Unknown keys silently ignored (forward-compatible)
- Sub-configs extracted by key: `architect`, `builder`, `integration`, `quality_gate`, `graph_rag`, `persistence`

### 1G.5 Agent Team / Builder Config

**DATA GAP-05**: The `agent_team` and `agent_team_v15` directories are NOT present in the repository. They are external dependencies imported at runtime:

```python
# src/super_orchestrator/pipeline.py (line ~718+)
from agent_team_v15 import ...  # or
from agent_team import ...       # fallback
```

Builder context injection includes a `graph_rag_context` field from `phase_artifacts`, meaning the builder receives Graph RAG context for code generation.

---

## Phase 1H: Test Infrastructure

### 1H.1 Test Configuration

**File:** `pyproject.toml` (test section):
- `testpaths = ["tests"]`
- `asyncio_mode = "auto"` (pytest-asyncio)
- `pythonpath = ["."]`
- Custom markers: `integration`, `e2e`, `benchmark`

### 1H.2 Root Conftest

**File:** `tests/conftest.py` (197 lines)

12 fixtures using `sample_` naming convention:

| Fixture | Type | Key Data |
|---------|------|----------|
| `tmp_db_path` | `Path` | Temporary SQLite path |
| `connection_pool` | `ConnectionPool` | Auto-closed pool with temp DB |
| `sample_service_stack` | `ServiceStack` | python, fastapi, sqlite |
| `sample_service_definition` | `ServiceDefinition` | user-service |
| `sample_entity_field` | `EntityField` | email, string, required |
| `sample_state_machine` | `StateMachine` | 3-state (active/inactive/suspended) |
| `sample_domain_entity` | `DomainEntity` | User entity |
| `sample_domain_relationship` | `DomainRelationship` | Order REFERENCES User |
| `sample_contract_entry` | `ContractEntry` | OpenAPI contract |
| `sample_symbol_definition` | `SymbolDefinition` | AuthService class |
| `sample_health_status` | `HealthStatus` | Healthy test-service |
| `mock_env_vars` | Monkeypatch | LOG_LEVEL, DATABASE_PATH, etc. |

SQLite test isolation: All DB tests use `tmp_path` fixtures for isolated databases.

### 1H.3 Security Scanner Test Pattern

**File:** `tests/build3/test_security_scanner.py`

Pattern:
- Async test functions using `pytest.mark.asyncio` (auto mode)
- `_scan_file()` helper: writes content to temp file, runs scanner against temp dir
- `_codes()` helper: extracts violation codes from result list
- Class-per-scan-code organization (e.g., all SEC-001 tests in one class)
- Tests both positive (violation detected) and negative (clean code, nosec suppression)

```python
async def _scan_file(scanner, tmp_path, filename, content) -> list:
    f = tmp_path / filename
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(content, encoding="utf-8")
    return await scanner.scan(tmp_path)
```

### 1H.4 Graph Builder Test Pattern

**File:** `tests/test_codebase_intelligence/test_graph_builder.py`

Pattern:
- Sync tests (graph builder is synchronous)
- Factory helpers for creating test `ImportReference` and `DependencyEdge` objects
- Class-per-behavior organization
- Tests graph operations: add node, add edge, cycle detection, connected components

### 1H.5 Test Pattern Summary

| Pattern | Example | Usage |
|---------|---------|-------|
| Async scanner test | `test_security_scanner.py` | All quality gate scanner tests |
| Sync unit test | `test_graph_builder.py` | Pure function / class tests |
| Fixture per instance | `@pytest.fixture; def scanner()` | Fresh scanner per test |
| _scan_file helper | Write file, run scanner, return results | Scanner integration tests |
| _codes helper | Extract violation codes from list | Assertion shorthand |
| sample_ fixtures | `sample_service_definition` | Shared test data |
| tmp_path isolation | `connection_pool(tmp_path)` | Database isolation |
| monkeypatch env | `mock_env_vars` | Environment variable testing |

### 1H.6 Mock and Assertion Patterns

- **MCP mocks**: `AsyncMock` for `ClientSession` (in `tests/run4/conftest.py`)
- **Tool result mocks**: `MockToolResult` / `MockTextContent` classes
- **Database mocks**: Real SQLite with `tmp_path` (not mocked)
- **ChromaDB mocks**: `MagicMock` for collection operations
- **Assertion style**: `assert` statements with descriptive messages, `pytest.raises` for exceptions

---

## DATA GAP Summary

| ID | Gap Description | Impact | Location |
|----|----------------|--------|----------|
| **DATA GAP-01** | `FixPassResult` is NOT persisted to disk | Fix pass history lost between pipeline restarts; no learning from past fix attempts | `src/run4/fix_pass.py` line 560 -- `FixPassResult` only returned in-memory from `execute_fix_pass()` |
| **DATA GAP-02** | `LayerResult` is transient within `QualityGateReport` | Individual layer scan details not available for pattern learning after pipeline completes | `src/build3_shared/models.py` line 91 -- nested in `QualityGateReport.layers` dict |
| **DATA GAP-03** | `ConvergenceResult` not independently persisted | Convergence trends across builds cannot be analyzed | `src/run4/fix_pass.py` line 372 -- only stored inside `FixPassResult.convergence` |
| **DATA GAP-04** | `FixPassMetrics` not independently persisted | Fix effectiveness trends not available for pattern learning | `src/run4/fix_pass.py` line 252 -- only stored inside `FixPassResult.metrics` |
| **DATA GAP-05** | `agent_team`/`agent_team_v15` source not in repository | Cannot analyze builder internals for pattern injection points | External dependencies, imported at runtime in `src/super_orchestrator/pipeline.py` |
| **DATA GAP-06** | Priority classification decisions not logged to DB | Cannot learn from past priority assignments to improve future classification | `src/run4/fix_pass.py` `classify_priority()` line 153 -- returns string, no persistence |
| **DATA GAP-07** | Violation snapshots not persisted between pipeline runs | Cannot compare violation trends across builds | `src/run4/fix_pass.py` `take_violation_snapshot()` line 32 -- returns dict, stored only in `FixPassResult` |
| **DATA GAP-08** | No cross-build pattern storage | Patterns from successful builds (architect decisions, fix strategies, scan results) are not stored for reuse | No existing storage for build-over-build learning |
| **DATA GAP-09** | Scanner results not indexed in ChromaDB | Cannot perform semantic search over past scan results | `SecurityScanner` returns `list[ScanViolation]` but violations are not vectorized |

### Critical Observations

1. **`PersistenceConfig` already exists** in `src/super_orchestrator/config.py` (lines 72-79) with `enabled: bool = False`, `db_path`, `chroma_path`, `max_patterns_per_injection`, and `min_occurrences_for_promotion`. This is the intended entry point for the Persistent Intelligence Layer.

2. **The 6-step SQLite pattern** (Phase 1B.2) is well-established and should be followed for the persistence database.

3. **The MCP server template** (Phase 1F.2) is consistent across all 4 existing servers and should be replicated for any persistence MCP tools.

4. **Graph RAG already demonstrates cross-database reads** (Phase 1F.4) -- the persistence layer can follow the same pattern to read from architect, contract, and symbol databases.

5. **`PipelineState.phase_artifacts`** (dict field) is the primary mechanism for passing data between phases. The persistence layer should inject context via this field.

6. **All 9 DATA GAPs** represent opportunities for the Persistent Intelligence Layer to capture, store, and learn from pipeline execution data.

---

*End of Architecture Report. This document is the single source of truth for all Persistent Intelligence Layer implementation agents.*

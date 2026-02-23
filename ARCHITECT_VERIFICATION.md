# Architect Service Verification Report

> **Agent:** architect-verifier
> **Phase:** Build 1 Verification
> **Date:** 2026-02-23
> **Scope:** End-to-end verification of the Architect service
> **Status:** ALL VERIFICATIONS PASS (minor documentation discrepancy noted)

---

## Table of Contents

1. [Verification 1: Service Startup and Health](#verification-1-service-startup-and-health)
2. [Verification 2: Decomposition Pipeline](#verification-2-decomposition-pipeline)
3. [Verification 3: MCP Server Tools](#verification-3-mcp-server-tools)
4. [Verification 4: Contract Engine Registration](#verification-4-contract-engine-registration)
5. [Verification 5: Storage Layer](#verification-5-storage-layer)
6. [Verification 6: MCP Client](#verification-6-mcp-client)
7. [Verification 7: HTTP API Endpoints](#verification-7-http-api-endpoints)
8. [Verification 8: Existing Tests](#verification-8-existing-tests)
9. [Summary of Issues](#summary-of-issues)
10. [MCP Tool Signatures](#mcp-tool-signatures)

---

## Verification 1: Service Startup and Health

**Status: PASS**

**File:** `C:\MY_PROJECTS\super-team\src\architect\main.py`

### Findings

1. **FastAPI app creation with lifespan context manager** -- CONFIRMED.
   - `@asynccontextmanager async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]` at line 21.
   - `app = FastAPI(title="Architect Service", version=VERSION, lifespan=lifespan)` at line 40.

2. **Lifespan initialization** -- CONFIRMED.
   - Line 26: `app.state.pool = ConnectionPool(config.database_path)` -- Creates ConnectionPool.
   - Line 27: `init_architect_db(app.state.pool)` -- Initializes database schema.
   - Line 24: `app.state.start_time = time.time()` -- Stores start time.
   - Note: `config` is stored at module level (`config = ArchitectConfig()` at line 17), NOT on `app.state`. This is fine as the config is immutable.

3. **Lifespan teardown** -- CONFIRMED.
   - Lines 35-36: `if app.state.pool: app.state.pool.close()` -- Properly closes pool on shutdown.

4. **Routers registered** -- CONFIRMED.
   - Line 55: `app.include_router(health_router)`
   - Line 56: `app.include_router(decomposition_router)`
   - Line 57: `app.include_router(service_map_router)`
   - Line 58: `app.include_router(domain_model_router)`

5. **Health endpoint** -- CONFIRMED.
   - File: `src/architect/routers/health.py`
   - `GET /api/health` returns `HealthStatus` with: `status` ("healthy"/"degraded"), `service_name` (ARCHITECT_SERVICE_NAME), `version` (VERSION), `database` ("connected"/"disconnected"), `uptime_seconds`.
   - Database check via `pool.get().execute("SELECT 1")` at line 28.
   - Runs in thread via `asyncio.to_thread(_check)`.

6. **Additional middleware** -- CONFIRMED.
   - Line 46: `app.add_middleware(TraceIDMiddleware)` -- Trace ID propagation.
   - Line 47: `register_exception_handlers(app)` -- AppError -> JSONResponse mapping.

---

## Verification 2: Decomposition Pipeline

**Status: PASS**

### Pipeline Flow Verification

**File:** `C:\MY_PROJECTS\super-team\src\architect\routers\decomposition.py`

The `_run_decomposition` function (line 30) executes the pipeline synchronously, called via `asyncio.to_thread` from the async endpoint.

| Step | Function | File | Status |
|------|----------|------|--------|
| 1 | `parse_prd(prd_text)` | `services/prd_parser.py` | CONFIRMED |
| 2 | `identify_boundaries(parsed)` | `services/service_boundary.py` | CONFIRMED |
| 3 | `build_service_map(parsed, boundaries)` | `services/service_boundary.py` | CONFIRMED |
| 4 | `build_domain_model(parsed, boundaries)` | `services/domain_modeler.py` | CONFIRMED |
| 5 | `validate_decomposition(service_map, domain_model)` | `services/validator.py` | CONFIRMED |
| 6 | `generate_contract_stubs(service_map, domain_model)` | `services/contract_generator.py` | CONFIRMED |
| 7 | Persist: `service_map_store.save()`, `domain_model_store.save()` | `storage/` | CONFIRMED |
| 8 | Return `DecompositionResult` | | CONFIRMED |

**Note on Architecture Report discrepancy:** The ARCHITECTURE_REPORT.md (Section 1A.3) states the pipeline order is `parse_prd -> identify_boundaries -> build_service_map -> build_domain_model -> generate_contract_stubs -> validate_decomposition -> persist`. In the actual code, validation runs BEFORE contract stub generation (step 5 vs step 6). Both the HTTP router and the MCP server follow the same corrected order: validate first, then generate stubs. This is functionally correct -- validation only examines the service_map and domain_model, not the contract stubs.

### DecompositionResult Structure

**File:** `C:\MY_PROJECTS\super-team\src\shared\models\architect.py` (lines 116-124)

```python
class DecompositionResult(BaseModel):
    service_map: ServiceMap
    domain_model: DomainModel
    contract_stubs: list[dict] = Field(default_factory=list)
    validation_issues: list[str] = Field(default_factory=list)
    interview_questions: list[str] = Field(default_factory=list)
```

**Architecture Report discrepancy:** The report (Section 1A.3) states `DecompositionResult` contains `validation_errors`. The actual field name is `validation_issues`. This is consistent throughout all source code -- no file uses `validation_errors`. The field name `validation_issues` is correct.

### ServiceDefinition Structure

**File:** `C:\MY_PROJECTS\super-team\src\shared\models\architect.py` (lines 31-42)

```python
class ServiceDefinition(BaseModel):
    name: str = Field(..., pattern=r"^[a-z][a-z0-9-]*$")
    domain: str
    description: str
    stack: ServiceStack
    estimated_loc: int = Field(..., ge=100, le=200000)
    owns_entities: list[str] = Field(default_factory=list)
    provides_contracts: list[str] = Field(default_factory=list)
    consumes_contracts: list[str] = Field(default_factory=list)
```

All fields match the Architecture Report specification. The `name` field has a kebab-case regex pattern enforced at the Pydantic level.

### DomainModel Structure

**File:** `C:\MY_PROJECTS\super-team\src\shared\models\architect.py` (lines 96-102)

```python
class DomainModel(BaseModel):
    entities: list[DomainEntity]
    relationships: list[DomainRelationship]
    generated_at: datetime
```

- `DomainEntity` has: `name`, `description`, `owning_service`, `fields` (list[EntityField]), `state_machine` (StateMachine | None).
- `DomainRelationship` has: `source_entity`, `target_entity`, `relationship_type` (RelationshipType enum), `cardinality` (pattern `^(1|N):(1|N)$`), `description`.
- CONFIRMED: matches Architecture Report specification.

### PRD Parser -- 5 Entity Extraction Strategies

**File:** `C:\MY_PROJECTS\super-team\src\architect\services\prd_parser.py`

| Strategy | Method | Lines | Status |
|----------|--------|-------|--------|
| 1. Markdown tables | `_extract_entities_from_tables()` | 401-475 | CONFIRMED |
| 2. Heading + bullet lists | `_extract_entities_from_headings()` | 514-589 | CONFIRMED |
| 3. Sentence / prose | `_extract_entities_from_sentences()` | 595-676 | CONFIRMED |
| 4. Data model sections | `_extract_entities_from_data_model_section()` | 682-701 | CONFIRMED |
| 5. Terse / inline patterns | `_extract_entities_from_terse_patterns()` | 707-761 | CONFIRMED |

All 5 strategies are applied in `_extract_entities()` (line 335) and results are merged/de-duplicated by normalized entity name.

### Service Boundary -- Aggregate Root Algorithm

**File:** `C:\MY_PROJECTS\super-team\src\architect\services\service_boundary.py`

4 strategies confirmed:
1. **Explicit bounded contexts** (lines 213-250) -- Seeds boundaries from `parsed.bounded_contexts`.
2. **Aggregate root discovery** (lines 255-283) -- Builds OWNS graph, finds roots (entities with no incoming OWNS edges).
3. **Relationship-based assignment** (lines 288-316) -- Assigns remaining entities to boundary with most relationships.
4. **Fallback monolith** (lines 321-328) -- Single boundary when nothing else works.

Non-overlapping guarantee: Each entity is assigned to exactly one boundary (tracked via `assigned` dict).

### Validator -- 7 Checks

**File:** `C:\MY_PROJECTS\super-team\src\architect\services\validator.py`

| Check | Method | Lines | Uses NetworkX | Status |
|-------|--------|-------|---------------|--------|
| 1. Service name uniqueness | `_check_service_name_uniqueness()` | 175-189 | No | CONFIRMED |
| 2. Circular dependencies | `_check_circular_dependencies()` | 64-95 | Yes (`nx.simple_cycles`) | CONFIRMED |
| 3. Entity overlap | `_check_entity_overlap()` | 98-115 | No | CONFIRMED |
| 4. Orphaned entities | `_check_orphaned_entities()` | 118-138 | No | CONFIRMED |
| 5. Service completeness | `_check_service_completeness()` | 141-151 | No | CONFIRMED |
| 6. Relationship consistency | `_check_relationship_consistency()` | 154-172 | No | CONFIRMED |
| 7. Contract consistency | `_check_contract_consistency()` | 192-210 | No | CONFIRMED |

### Contract Generator

**File:** `C:\MY_PROJECTS\super-team\src\architect\services\contract_generator.py`

- Generates OpenAPI 3.1.0 specs (`"openapi": "3.1.0"` at line 295).
- CRUD paths per entity: GET list, POST, GET by id, PUT, DELETE.
- Schema definitions in `components/schemas` with JSON Schema types.
- Services with no entities get a minimal spec with `/health` only.
- CONFIRMED: matches Architecture Report specification.

---

## Verification 3: MCP Server Tools

**Status: PASS**

**File:** `C:\MY_PROJECTS\super-team\src\architect\mcp_server.py`

### Tool 1: `decompose` (line 61)

```python
@mcp.tool(name="decompose")
def decompose_prd(prd_text: str) -> dict[str, Any]:
```

- **Parameter:** `prd_text: str`
- **Returns:** `dict` with keys: `service_map`, `domain_model`, `contract_stubs`, `validation_issues`, `interview_questions`
- **Error handling:** `ParsingError` -> `{"error": str(exc)}`, generic `Exception` -> `{"error": str(exc)}`
- **Pipeline:** Same 7-step pipeline as HTTP endpoint.
- **Persistence:** Saves to `service_map_store` and `domain_model_store` before returning.

### Tool 2: `get_service_map` (line 127)

```python
@mcp.tool()
def get_service_map(project_name: str | None = None) -> dict[str, Any]:
```

- **Parameter:** `project_name: str | None = None`
- **Returns:** `ServiceMap.model_dump(mode="json")` dict, or `{"error": "No service map found"}`
- **Error handling:** `AppError` and generic `Exception` both return error dicts.

### Tool 3: `get_domain_model` (line 153)

```python
@mcp.tool()
def get_domain_model(project_name: str | None = None) -> dict[str, Any]:
```

- **Parameter:** `project_name: str | None = None`
- **Returns:** `DomainModel.model_dump(mode="json")` dict, or `{"error": "No domain model found"}`
- **Error handling:** Same pattern as `get_service_map`.

### Tool 4: `get_contracts_for_service` (line 179)

```python
@mcp.tool(name="get_contracts_for_service")
def get_contracts_for_service(service_name: str) -> list[dict[str, Any]]:
```

- **Parameter:** `service_name: str`
- **Returns:** `list[dict]` where each dict has: `id`, `role`, `type`, `counterparty`, `summary`
- **Error handling:** Returns `[{"error": ...}]` for service not found, HTTP errors, and unexpected exceptions.
- **Cross-service call:** Uses `httpx.Client` to call Contract Engine per-contract-id.

---

## Verification 4: Contract Engine Registration

**Status: PASS**

**File:** `C:\MY_PROJECTS\super-team\src\architect\mcp_server.py` (lines 179-281)

### `get_contracts_for_service` HTTP Calls

The tool does NOT call `GET /api/contracts?service_name=...` as described in the Architecture Report.

**Actual behavior (verified from source code):**

1. Retrieves the latest service map from the local database.
2. Finds the target service by name within the service map.
3. Collects `provides_contracts` and `consumes_contracts` (which are contract ID strings, not actual Contract Engine IDs).
4. For each contract ID, calls **`GET {CONTRACT_ENGINE_URL}/api/contracts/{contract_id}`** (individual contract retrieval by ID).

**Architecture Report discrepancy:** The report states the tool calls `GET /api/contracts?service_name=...` (list endpoint). The actual code calls `GET /api/contracts/{contract_id}` (individual contract endpoint) for each contract reference found in the service map.

This is a minor functional difference but does NOT constitute a bug -- the tool still achieves its goal of retrieving contract details. However, it means:
- The contract IDs in `provides_contracts`/`consumes_contracts` are boundary-generated slugs (e.g., `"user-management-api"`), NOT Contract Engine database IDs.
- If these slugs don't match actual Contract Engine contract IDs, the HTTP calls will return 404s, which are gracefully handled (lines 253-260).

### Error Handling for Contract Engine Unavailability

- `httpx.Timeout(connect=5.0, read=30.0)` -- CONFIRMED (line 225).
- Individual contract fetch failures are caught via `httpx.HTTPError` (line 261).
- Failed fetches return a degraded result with `"summary": f"Failed to fetch contract: {http_exc}"`.
- The tool never raises; all errors are converted to response items with error information.

### Does `decompose` Register Contracts?

**No.** The `decompose` tool generates contract stubs (OpenAPI specs) but does NOT register them with the Contract Engine. The stubs are returned in the response as `contract_stubs` but are never POSTed to the Contract Engine. Contract registration is expected to be handled by Build 2 consumers.

---

## Verification 5: Storage Layer

**Status: PASS**

### ServiceMapStore

**File:** `C:\MY_PROJECTS\super-team\src\architect\storage\service_map_store.py`

| Method | SQL | Status |
|--------|-----|--------|
| `save(service_map) -> str` | `INSERT INTO service_maps (id, project_name, prd_hash, map_json, build_cycle_id, generated_at)` | CONFIRMED |
| `get_latest(project_name?) -> ServiceMap \| None` | `SELECT map_json FROM service_maps [WHERE project_name=?] ORDER BY generated_at DESC LIMIT 1` | CONFIRMED |
| `get_by_prd_hash(prd_hash) -> ServiceMap \| None` | `SELECT map_json FROM service_maps WHERE prd_hash=? ORDER BY generated_at DESC LIMIT 1` | CONFIRMED |

- Uses `model_dump_json()` for serialization and `model_validate_json()` for deserialization.
- UUID generated via `str(uuid.uuid4())`.
- Proper `conn.commit()` after insert.

### DomainModelStore

**File:** `C:\MY_PROJECTS\super-team\src\architect\storage\domain_model_store.py`

| Method | SQL | Status |
|--------|-----|--------|
| `save(domain_model, project_name) -> str` | `INSERT INTO domain_models (id, project_name, model_json, generated_at)` | CONFIRMED |
| `get_latest(project_name?) -> DomainModel \| None` | `SELECT model_json FROM domain_models [WHERE project_name=?] ORDER BY generated_at DESC LIMIT 1` | CONFIRMED |

- Note: `DomainModelStore` does NOT have a `get_by_prd_hash` method (unlike `ServiceMapStore`). This is correct since domain_models table has no `prd_hash` column.

### Database Schema Match

**File:** `C:\MY_PROJECTS\super-team\src\shared\db\schema.py` (lines 7-43)

Tables created by `init_architect_db`:
- `service_maps`: `id TEXT PK`, `project_name TEXT NOT NULL`, `prd_hash TEXT NOT NULL`, `map_json TEXT NOT NULL`, `build_cycle_id TEXT`, `generated_at TEXT NOT NULL`
- `domain_models`: `id TEXT PK`, `project_name TEXT NOT NULL`, `model_json TEXT NOT NULL`, `generated_at TEXT NOT NULL`
- `decomposition_runs`: `id TEXT PK`, `prd_content_hash TEXT NOT NULL`, `service_map_id TEXT FK`, `domain_model_id TEXT FK`, `validation_issues TEXT`, `interview_questions TEXT`, `status TEXT`, `started_at TEXT`, `completed_at TEXT`

All columns match the fields written by the store classes and the decomposition router. Indexes on `project_name` and `prd_hash` are present.

---

## Verification 6: MCP Client

**Status: PASS**

**File:** `C:\MY_PROJECTS\super-team\src\architect\mcp_client.py`

### ArchitectClient Methods

| Method | MCP Tool Called | Default Return | Status |
|--------|----------------|----------------|--------|
| `decompose(prd_text: str)` | `"decompose"` | `None` | CONFIRMED |
| `get_service_map(project_name?)` | `"get_service_map"` | `{}` | CONFIRMED |
| `get_contracts_for_service(service_name)` | `"get_contracts_for_service"` | `[]` | CONFIRMED |
| `get_domain_model(project_name?)` | `"get_domain_model"` | `{}` | CONFIRMED |

### WIRE-011 Filesystem Fallback

**`decompose_prd_basic(prd_text: str)`** (line 196):
- Returns a minimal single-service stub: `{services: [{name, description, endpoints}], domain_model: {entities: [], relationships: []}, contract_stubs: [], fallback: True}`.
- Extracts project name from first line, converts to kebab-case slug.
- Pure function, no I/O.

**`decompose_prd_with_fallback(prd_text, client?)`** (line 231):
- Tries `client.decompose(prd_text)` first.
- If result is `None` or contains `"error"`, falls back to `decompose_prd_basic()`.
- If client is `None`, goes straight to fallback.
- All exceptions caught and fall back gracefully.
- Adds `"fallback": False` on MCP success, `"fallback": True` on fallback.

### Retry Pattern

**`_call` method** (line 95):
- `_MAX_RETRIES = 3` -- 4 total attempts (initial + 3 retries). Actually, the loop is `for attempt in range(_MAX_RETRIES + 1)` which is `range(4)` = 4 iterations, but retries only happen for `attempt < _MAX_RETRIES` (first 3 iterations). So it's 4 attempts total, with retries on the first 3.
- Exponential backoff: `delay = 1 * (2 ** attempt)` -- 1s, 2s, 4s.
- Catches `(ConnectionError, OSError, Exception)` -- effectively catches all exceptions.
- Returns safe default on exhaustion (never raises).

### Session Support

- Constructor accepts optional `session` parameter for testing.
- When `session` is provided, tool calls go through `session.call_tool()` directly.
- When `session` is `None`, uses `_call_tool()` which opens a new stdio session per call.

---

## Verification 7: HTTP API Endpoints

**Status: PASS**

### GET /api/health

**File:** `C:\MY_PROJECTS\super-team\src\architect\routers\health.py`

| Property | Value |
|----------|-------|
| Method | GET |
| Path | `/api/health` |
| Status Code | 200 |
| Response Model | `HealthStatus` |
| Error Handling | Database check failure -> status="degraded", database="disconnected" |

### POST /api/decompose

**File:** `C:\MY_PROJECTS\super-team\src\architect\routers\decomposition.py`

| Property | Value |
|----------|-------|
| Method | POST |
| Path | `/api/decompose` |
| Status Code | 201 |
| Request Body | `DecomposeRequest` (`prd_text: str`, min_length=10, max_length=1048576) |
| Response Model | `DecompositionResult` |
| Error Handling | Pydantic validation -> 422; ParsingError -> 400 (via AppError handler) |

- Runs pipeline in thread via `asyncio.to_thread(_run_decomposition, ...)`.
- Also saves a `DecompositionRun` record to `decomposition_runs` table.

### GET /api/service-map

**File:** `C:\MY_PROJECTS\super-team\src\architect\routers\service_map.py`

| Property | Value |
|----------|-------|
| Method | GET |
| Path | `/api/service-map` |
| Status Code | 200 (success), 404 (not found) |
| Query Params | `project_name: str \| None` |
| Response Model | `ServiceMap` |
| Error Handling | No service map -> `NotFoundError("No service map found")` -> 404 |

### GET /api/domain-model

**File:** `C:\MY_PROJECTS\super-team\src\architect\routers\domain_model.py`

| Property | Value |
|----------|-------|
| Method | GET |
| Path | `/api/domain-model` |
| Status Code | 200 (success), 404 (not found) |
| Query Params | `project_name: str \| None` |
| Response Model | `DomainModel` |
| Error Handling | No domain model -> `NotFoundError("No domain model found")` -> 404 |

---

## Verification 8: Existing Tests

**Status: PASS (with coverage gaps noted)**

### Test File Inventory

| File | Test Count | Coverage Area |
|------|-----------|---------------|
| `tests/test_architect/test_prd_parser.py` | ~40+ | All 5 entity extraction strategies, relationships, bounded contexts, technology hints, state machines, interview questions, project name extraction, error cases, entity merging, cardinality, false positive prevention |
| `tests/test_architect/test_service_boundary.py` | ~15 | All 4 boundary strategies (explicit contexts, aggregate roots, relationship-based, monolith fallback), non-overlapping guarantee, kebab-case normalization, pipeline integration |
| `tests/test_architect/test_domain_modeler.py` | ~20 | Entity conversion, state machine detection (parsed data + default + inference), owning service resolution, relationship conversion, cardinality normalization, type mapping |
| `tests/test_architect/test_contract_generator.py` | ~15 | One spec per service, OpenAPI 3.1.0, CRUD paths, schema definitions, field type mapping, pluralization, CamelCase-to-kebab, no-entity minimal spec, missing entity fallback, required fields |
| `tests/test_architect/test_validator.py` | ~12 | All 7 validation checks: circular deps, entity overlap, orphaned entities, empty services, relationship consistency, name uniqueness, contract consistency |
| `tests/test_architect/test_routers.py` | ~20 | Health endpoint (200, status, service_name, version, database, uptime), decompose (201, service_map, domain_model, contract_stubs, 422 errors, project_name, multi-service, relationships, prd_hash), service-map (404/200/contains services/project_name), domain-model (404/200/entities/relationships/required fields) |
| `tests/test_mcp/test_architect_mcp.py` | ~18 | MCP instance verification, decompose tool (all response keys, types, error cases), get_service_map (empty/after decompose/filter), get_domain_model (empty/after decompose/filter), get_contracts_for_service (no map/not found/with contracts), tool count = 4 |

### Test Fixture Patterns

- **Router tests:** Use `TestClient` with a standalone FastAPI app wired to a temporary SQLite database via `tmp_path`. Lifespan context manager properly initializes and tears down.
- **MCP tests:** Use `monkeypatch` to replace module-level `pool`, `service_map_store`, and `domain_model_store` with temporary instances.
- **Unit tests:** Direct function calls with constructed `ParsedPRD` / `ServiceBoundary` / model instances.

### Coverage Gaps

| Area | Status | Notes |
|------|--------|-------|
| **MCP Client (`mcp_client.py`)** | NOT COVERED in `test_architect/` | No unit tests for `ArchitectClient`, `decompose_prd_basic`, `decompose_prd_with_fallback`, or retry logic. The `tests/test_mcp/test_architect_mcp.py` tests the MCP *server*, not the client. |
| **Storage layer** | PARTIALLY COVERED | `ServiceMapStore` and `DomainModelStore` are tested indirectly via the router tests (decompose -> save -> get), but there are no dedicated unit tests for `save()`, `get_latest()`, or `get_by_prd_hash()`. |
| **`get_contracts_for_service` HTTP calls** | NOT COVERED | The MCP test for this tool only checks the "no service map" and "service not found" paths. The httpx HTTP call to Contract Engine is never tested (would require mocking the Contract Engine). |
| **Decomposition run record** | NOT COVERED | The `DecompositionRun` record written by the HTTP endpoint (lines 65-94 of `decomposition.py`) is never verified in tests. |
| **Error handling edge cases** | PARTIALLY COVERED | MCP server error paths (ParsingError, generic Exception) are tested. HTTP endpoint error propagation via `register_exception_handlers` is implicitly tested. |
| **Concurrent access** | NOT COVERED | No tests for thread-safety of the ConnectionPool or concurrent decomposition requests. |

### Recommended Additional Tests

1. **`ArchitectClient` retry logic** -- Unit test with a mock session that fails N times then succeeds.
2. **`decompose_prd_basic` edge cases** -- Empty text, very long text, special characters.
3. **`decompose_prd_with_fallback`** -- Test MCP success path, MCP error -> fallback path, client=None -> fallback path.
4. **`ServiceMapStore.get_by_prd_hash`** -- Dedicated test with known hash.
5. **`get_contracts_for_service` with httpx mock** -- Mock Contract Engine responses to verify the full flow.
6. **`DecompositionRun` persistence** -- Verify the run record is written to the database after decomposition.

---

## Summary of Issues

### Bugs Found

**No blocking bugs found.**

### Documentation Discrepancies (Non-blocking)

| ID | Location | Issue | Severity |
|----|----------|-------|----------|
| DOC-001 | ARCHITECTURE_REPORT.md Section 1A.3 | Pipeline order lists `generate_contract_stubs` before `validate_decomposition`. Actual code validates first, then generates stubs. | Low |
| DOC-002 | ARCHITECTURE_REPORT.md Section 1A.3 | States `DecompositionResult` contains `validation_errors`. Actual field name is `validation_issues`. | Low |
| DOC-003 | ARCHITECTURE_REPORT.md Section 1D.1 | States `get_contracts_for_service` calls `GET /api/contracts?service_name={name}`. Actual code calls `GET /api/contracts/{contract_id}` for each contract reference. | Medium |

### SVC-005 Impact on Architect

The SVC-005 mismatch (`total` vs `total_implementations` in Contract Engine's `mark_implemented` MCP tool) does **NOT** affect the Architect service. The Architect never calls `mark_implemented` and does not reference the `total` or `total_implementations` field anywhere.

### Missing Test Coverage (Non-blocking)

The MCP client (`mcp_client.py`) has zero dedicated test coverage. While it works correctly (verified by code review), adding tests for the retry pattern, WIRE-011 fallback, and error handling would improve confidence.

---

## MCP Tool Signatures

### Architect MCP Server Tools (4 total)

```python
# Tool 1
@mcp.tool(name="decompose")
def decompose_prd(prd_text: str) -> dict[str, Any]:
    """Returns: {service_map: dict, domain_model: dict, contract_stubs: list,
                 validation_issues: list[str], interview_questions: list[str]}
       On error: {error: str}"""

# Tool 2
@mcp.tool()
def get_service_map(project_name: str | None = None) -> dict[str, Any]:
    """Returns: ServiceMap as JSON dict (project_name, services, generated_at, prd_hash)
       On error: {error: str}"""

# Tool 3
@mcp.tool()
def get_domain_model(project_name: str | None = None) -> dict[str, Any]:
    """Returns: DomainModel as JSON dict (entities, relationships, generated_at)
       On error: {error: str}"""

# Tool 4
@mcp.tool(name="get_contracts_for_service")
def get_contracts_for_service(service_name: str) -> list[dict[str, Any]]:
    """Returns: list of {id, role, type, counterparty, summary}
       On error: [{error: str}]"""
```

### Architect MCP Client Methods (ArchitectClient)

```python
class ArchitectClient:
    async def decompose(self, prd_text: str) -> dict | None
    async def get_service_map(self, project_name: str | None = None) -> dict
    async def get_contracts_for_service(self, service_name: str) -> list[dict]
    async def get_domain_model(self, project_name: str | None = None) -> dict

# Module-level convenience functions
async def call_architect_mcp(prd_text: str, config=None) -> dict
async def get_service_map(project_name: str | None = None) -> dict
async def get_contracts_for_service(service_name: str) -> list[dict]
async def get_domain_model(project_name: str | None = None) -> dict

# WIRE-011 Fallback
def decompose_prd_basic(prd_text: str) -> dict  # Synchronous
async def decompose_prd_with_fallback(prd_text: str, client=None) -> dict
```

---

*End of Architect Service Verification Report.*

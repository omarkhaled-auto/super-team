# Architecture Report: Build 1 Verification (Phase 1)

> **Report Type:** Discovery Agent Output
> **Generated:** 2026-02-23
> **Scope:** Build 1 Foundation Services + Shared Modules + Docker Infrastructure + Test Infrastructure
> **Status:** READ ONLY -- No source files modified

---

## Table of Contents

- [Section 1A: Service Structure and Entry Points](#section-1a-service-structure-and-entry-points)
- [Section 1B: Docker Infrastructure](#section-1b-docker-infrastructure)
- [Section 1C: Test Infrastructure](#section-1c-test-infrastructure)
- [Section 1D: Known Integration Points](#section-1d-known-integration-points)
- [Section 1E: Known API Mismatches Verification](#section-1e-known-api-mismatches-verification)

---

## Section 1A: Service Structure and Entry Points

### 1A.1 Project Configuration

**File:** `pyproject.toml`

| Property | Value |
|----------|-------|
| Project Name | `super-team` |
| Version | `1.0.0` |
| Python | `>=3.11` (ruff/mypy target `3.12`) |
| FastAPI | `0.129.0` |
| tree-sitter | `0.25.2` |
| chromadb | `1.5.0` |
| networkx | `3.6.1` |
| mcp | `>=1.25,<2` |
| schemathesis | `4.10.1` |

**Test Configuration:**
- `testpaths = ["tests"]`
- `asyncio_mode = "auto"` (pytest-asyncio)
- `pythonpath = ["."]`
- Custom markers: `integration`, `e2e`, `benchmark`

**Entry Point:** `super-orchestrator = "src.super_orchestrator.cli:app"` (Build 3 CLI)

---

### 1A.2 Shared Modules (`src/shared/`)

All three Build 1 services depend on this shared layer.

#### 1A.2.1 Configuration (`src/shared/config.py`)

Base class: `SharedConfig(BaseSettings)` with fields:
- `log_level: str = "info"`
- `database_path: Path = Path("./data/service.db")`
- `database_url: str = ""` (PostgreSQL, optional)
- `redis_url: str = ""` (optional)

Derived configs:
- `ArchitectConfig` adds: `contract_engine_url`, `codebase_intel_url`
- `ContractEngineConfig` (no extra fields)
- `CodebaseIntelConfig` adds: `chroma_path`, `graph_path`, `contract_engine_url`

All load from environment variables via Pydantic Settings.

#### 1A.2.2 Constants (`src/shared/constants.py`)

| Constant | Value |
|----------|-------|
| `VERSION` | `"1.0.0"` |
| `ARCHITECT_PORT` | `8001` |
| `CONTRACT_ENGINE_PORT` | `8002` |
| `CODEBASE_INTEL_PORT` | `8003` |
| `ARCHITECT_SERVICE_NAME` | `"architect"` |
| `CONTRACT_ENGINE_SERVICE_NAME` | `"contract-engine"` |
| `CODEBASE_INTEL_SERVICE_NAME` | `"codebase-intelligence"` |

#### 1A.2.3 Error Hierarchy (`src/shared/errors.py`)

```
AppError (base)
  +-- ValidationError (422)
  +-- NotFoundError (404)
  +-- ConflictError (409)
  +-- ImmutabilityViolationError (409)
  +-- ParsingError (400)
  +-- SchemaError (422)
  +-- ContractNotFoundError (404)
```

All inherit from `AppError` which carries `status_code`, `message`, and `details`. A FastAPI exception handler is registered via `register_error_handlers(app)`.

#### 1A.2.4 Database (`src/shared/db/`)

**`connection.py`** -- `ConnectionPool`:
- Thread-local SQLite connections via `threading.local()`
- WAL mode, `busy_timeout=30000`, `foreign_keys=ON`, `journal_mode=WAL`
- `get() -> sqlite3.Connection` returns thread-local connection
- `close()` closes all thread-local connections

**`schema.py`** -- Three initializers:
1. `init_architect_db(pool)` -- Creates: `service_maps`, `domain_models`, `decomposition_runs`
2. `init_contracts_db(pool)` -- Creates: `build_cycles`, `contracts`, `contract_versions`, `breaking_changes`, `implementations`, `test_suites`, `shared_schemas`, `schema_consumers`
3. `init_symbols_db(pool)` -- Creates: `indexed_files`, `symbols`, `dependency_edges`, `import_references`, `graph_snapshots`

#### 1A.2.5 Data Models (`src/shared/models/`)

**`architect.py`:**
- `ServiceStack` (language, framework, database)
- `RelationshipType` (Enum: REFERENCES, BELONGS_TO, USES, PUBLISHES, SUBSCRIBES)
- `ServiceDefinition` (name, domain, description, stack, estimated_loc, owns_entities, provides/consumes_contracts)
- `EntityField`, `StateTransition`, `StateMachine`
- `DomainEntity` (name, description, owning_service, fields, state_machine)
- `DomainRelationship` (source_entity, target_entity, relationship_type, cardinality)
- `DomainModel` (entities, relationships, bounded_contexts)
- `ServiceMap` (services: list[ServiceDefinition], relationships, project_name, prd_hash)
- `DecompositionResult` (service_map, domain_model, validation_errors, contract_stubs)
- `DecomposeRequest` (prd_text, project_name)
- `DecompositionRun` (id, project_name, prd_hash, result_json, timestamps)

**`contracts.py`:**
- `ContractType` (Enum: OPENAPI, ASYNCAPI, GRPC, GRAPHQL, PACT)
- `ContractStatus` (Enum: DRAFT, ACTIVE, DEPRECATED, SUPERSEDED)
- `ImplementationStatus` (Enum: NOT_STARTED, IN_PROGRESS, IMPLEMENTED, VERIFIED)
- `ContractEntry` (id, type, version, service_name, spec, status, timestamps, build_cycle)
- `ContractCreate` (type, version, service_name, spec, build_cycle)
- `ContractListResponse` (contracts, total)
- `EndpointSpec`, `OpenAPIContract`, `AsyncAPIContract`, `SharedSchema`
- `BreakingChange` (contract_id, field, old_value, new_value, severity, description)
- `ContractVersion` (contract_id, version, spec_snapshot, changes, timestamps)
- `ImplementationRecord` (contract_id, service_name, status, verified_at)
- `ValidationResult` (valid, errors, warnings, spec_version)
- `ValidateRequest` (spec, spec_type)
- `MarkRequest` (contract_ids, service_name, status)
- `MarkResponse` (marked: int, total_implementations: int, all_implemented: bool)
- `UnimplementedContract` (contract_id, service_name, type, version)
- `ContractTestSuite` (contract_id, test_code, framework, generated_at, test_count)
- `ComplianceViolation`, `ComplianceResult`

**`codebase.py`:**
- `SymbolKind` (Enum: CLASS, FUNCTION, METHOD, INTERFACE, TYPE, ENUM, VARIABLE)
- `Language` (Enum: PYTHON, TYPESCRIPT, CSHARP, GO)
- `DependencyRelation` (Enum: IMPORTS, CALLS, INHERITS, IMPLEMENTS, USES)
- `SymbolDefinition` (id auto-generated as `{file_path}::{symbol_name}`, file_path, symbol_name, kind, language, service_name, line_start/end, signature, docstring, is_exported, parent_symbol)
- `ImportReference` (source_file, target_file, imported_names, line, is_relative)
- `DependencyEdge`, `CodeChunk`, `SemanticSearchResult`, `ServiceInterface`
- `DeadCodeEntry`, `GraphAnalysis`, `IndexStats`

**`common.py`:**
- `BuildCycle` (cycle_id, started_at, completed_at, services)
- `ArtifactRegistration` (file_path, service_name, source)
- `HealthStatus` (status, service_name, version, database, uptime_seconds, details)

#### 1A.2.6 Logging (`src/shared/logging.py`)

- `JSONFormatter` -- Structured JSON log output
- `TraceIDMiddleware` -- ASGI middleware that propagates `X-Trace-ID` header

#### 1A.2.7 Utilities (`src/shared/utils.py`)

- `read_file_safe(path) -> str | None`
- `compute_hash(text) -> str` (SHA-256)
- `safe_json_loads(text) -> dict | None`

---

### 1A.3 Architect Service (`src/architect/`)

#### Entry Point: `src/architect/main.py`

- FastAPI app with `lifespan` async context manager
- **Lifespan initialization:**
  1. `ConnectionPool(config.database_path)` -- SQLite pool
  2. `init_architect_db(pool)` -- Creates tables
  3. Stores `pool`, `config`, `start_time` on `app.state`
- **Lifespan teardown:** `pool.close()`
- **Routers registered:** `health_router`, `decomposition_router`, `service_map_router`, `domain_model_router`

#### HTTP Endpoints

| Method | Path | Status | Request Body | Response Model |
|--------|------|--------|-------------|----------------|
| `GET` | `/api/health` | 200 | -- | `HealthStatus` |
| `POST` | `/api/decompose` | 201 | `DecomposeRequest` | `DecompositionResult` |
| `GET` | `/api/service-map` | 200 | -- | `ServiceMap` |
| `GET` | `/api/domain-model` | 200 | -- | `DomainModel` |

#### Decomposition Pipeline (`POST /api/decompose`)

Runs via `asyncio.to_thread` in a blocking function:
1. `parse_prd(prd_text)` -- Extracts entities, relationships, contexts, tech hints, state machines
2. `identify_boundaries(parsed)` -- Aggregate root algorithm (4 strategies: explicit contexts, aggregate roots, relationship-based, fallback monolith)
3. `build_service_map(boundaries, parsed)` -- Creates ServiceDefinition list
4. `build_domain_model(parsed, boundaries)` -- Creates DomainEntity + DomainRelationship list
5. `generate_contract_stubs(service_map)` -- Creates OpenAPI 3.1 specs (CRUD paths per entity)
6. `validate_decomposition(service_map, domain_model)` -- 7 checks (circular deps, entity overlap, orphans, completeness, relationship consistency, name uniqueness, contract consistency)
7. Persist results (ServiceMapStore.save, DomainModelStore.save)
8. Return `DecompositionResult`

#### Services Layer

| Module | Purpose |
|--------|---------|
| `services/prd_parser.py` | 5 entity extraction strategies (tables, headings, sentences, data model sections, terse patterns), relationship extraction, bounded context detection, technology hints, state machine detection |
| `services/service_boundary.py` | Aggregate root algorithm, boundary identification |
| `services/domain_modeler.py` | Domain model construction with state machines |
| `services/contract_generator.py` | OpenAPI 3.1 stub generation with CRUD paths |
| `services/validator.py` | 7-check validation suite using NetworkX for circular dependency detection |

#### Storage Layer

| Module | Purpose |
|--------|---------|
| `storage/service_map_store.py` | `save()`, `get_latest()`, `get_by_prd_hash()` |
| `storage/domain_model_store.py` | `save()`, `get_latest()` |

#### MCP Server (`src/architect/mcp_server.py`)

Server name: `"Architect"` (FastMCP)

| Tool Name | Parameters | Returns |
|-----------|------------|---------|
| `decompose` | `prd_text: str` | `DecompositionResult` dict |
| `get_service_map` | `project_name: str = ""` | `ServiceMap` dict |
| `get_domain_model` | `project_name: str = ""` | `DomainModel` dict |
| `get_contracts_for_service` | `service_name: str` | list of contracts (makes HTTP calls to Contract Engine) |

**Cross-service dependency:** `get_contracts_for_service` tool calls Contract Engine HTTP API (`GET /api/contracts?service_name=...`).

#### MCP Client (`src/architect/mcp_client.py`)

Class: `ArchitectClient`

| Method | MCP Tool Called | Fallback |
|--------|----------------|----------|
| `decompose(prd_text)` | `decompose` | -- |
| `get_service_map()` | `get_service_map` | -- |
| `get_contracts_for_service(name)` | `get_contracts_for_service` | -- |
| `get_domain_model()` | `get_domain_model` | -- |
| `decompose_prd_basic(prd_text)` | -- | WIRE-011 filesystem fallback |
| `decompose_prd_with_fallback(prd_text)` | `decompose` | Falls back to `decompose_prd_basic` |

**Retry pattern:** 3 retries, base 1s exponential backoff.

---

### 1A.4 Contract Engine Service (`src/contract_engine/`)

#### Entry Point: `src/contract_engine/main.py`

- FastAPI app with `lifespan` async context manager
- **Lifespan initialization:**
  1. `ConnectionPool(config.database_path)` -- SQLite pool
  2. `init_contracts_db(pool)` -- Creates tables
  3. Stores `pool`, `config`, `start_time` on `app.state`
- **Lifespan teardown:** `pool.close()`
- **Routers registered:** `health_router`, `contracts_router`, `validation_router`, `breaking_changes_router`, `implementations_router`, `tests_router`

#### HTTP Endpoints

| Method | Path | Status | Request Body | Response Model |
|--------|------|--------|-------------|----------------|
| `GET` | `/api/health` | 200 | -- | `HealthStatus` |
| `POST` | `/api/contracts` | 201 | `ContractCreate` | `ContractEntry` |
| `GET` | `/api/contracts` | 200 | query: `service_name`, `type`, `status` | `ContractListResponse` |
| `GET` | `/api/contracts/{contract_id}` | 200 | -- | `ContractEntry` |
| `DELETE` | `/api/contracts/{contract_id}` | 204 | -- | -- |
| `POST` | `/api/validate` | 200 | `ValidateRequest` | `ValidationResult` |
| `POST` | `/api/breaking-changes/{contract_id}` | 200 | new spec (body) | `list[BreakingChange]` |
| `POST` | `/api/implementations/mark` | 200 | `MarkRequest` | `MarkResponse` |
| `GET` | `/api/implementations/unimplemented` | 200 | query: `service_name` | `list[UnimplementedContract]` |
| `POST` | `/api/tests/generate/{contract_id}` | 200 | -- | `ContractTestSuite` |
| `GET` | `/api/tests/{contract_id}` | 200 | -- | `ContractTestSuite` |
| `POST` | `/api/compliance/check/{contract_id}` | 200 | -- | `list[ComplianceResult]` |

#### Services Layer

| Module | Purpose |
|--------|---------|
| `services/contract_store.py` | CRUD for contracts with `ON CONFLICT DO UPDATE` upsert |
| `services/openapi_validator.py` | OpenAPI validation via `openapi-spec-validator` + `prance` for `$ref` resolution |
| `services/asyncapi_validator.py` | AsyncAPI validation via `jsonschema` Draft 2020-12 |
| `services/asyncapi_parser.py` | Full AsyncAPI 2.x/3.x parser with `$ref` resolution, circular ref detection |
| `services/breaking_change_detector.py` | Deep-diff of OpenAPI specs (paths, methods, params, request body, responses, schemas) |
| `services/compliance_checker.py` | OpenAPI/AsyncAPI runtime validation, max 3 levels deep |
| `services/implementation_tracker.py` | `mark_implemented()` returns `MarkResponse`, `verify_implementation()`, `get_unimplemented()` |
| `services/schema_registry.py` | Manages `shared_schemas` + `schema_consumers` tables |
| `services/test_generator.py` | Schemathesis tests for OpenAPI, jsonschema tests for AsyncAPI, with caching |
| `services/version_manager.py` | Build cycle immutability enforcement |

#### MCP Server (`src/contract_engine/mcp_server.py`)

Server name: `"Contract Engine"` (FastMCP)

| Tool Name | Parameters | Returns |
|-----------|------------|---------|
| `create_contract` | `type, version, service_name, spec` | `ContractEntry` dict |
| `list_contracts` | `service_name?, type?, status?` | `ContractListResponse` dict |
| `get_contract` | `contract_id` | `ContractEntry` dict |
| `validate_spec` | `spec, spec_type` | `ValidationResult` dict |
| `check_breaking_changes` | `contract_id, new_spec` | list of `BreakingChange` dicts |
| `mark_implemented` | `contract_ids, service_name, status?` | `{"marked", "total", "all_implemented"}` |
| `get_unimplemented_contracts` | `service_name?` | list of `UnimplementedContract` dicts |
| `generate_tests` | `contract_id` | `str` (test_code only) |
| `check_compliance` | `contract_id` | list of `ComplianceResult` dicts |
| `validate_endpoint` | `contract_id, method, path, status_code?, response_body?` | `{"valid", "errors"}` |

#### MCP Client (`src/contract_engine/mcp_client.py`)

Class: `ContractEngineClient`

| Method | MCP Tool Called | Fallback |
|--------|----------------|----------|
| `create_contract(...)` | `create_contract` | -- |
| `list_contracts(...)` | `list_contracts` | -- |
| `get_contract(id)` | `get_contract` | -- |
| `validate_spec(...)` | `validate_spec` | -- |
| `check_breaking_changes(...)` | `check_breaking_changes` | -- |
| `mark_implemented(...)` | `mark_implemented` | -- |
| `get_unimplemented(...)` | `get_unimplemented_contracts` | -- |
| `generate_tests(id)` | `generate_tests` | Returns `str` |
| `check_compliance(id)` | `check_compliance` | -- |
| `run_api_contract_scan(...)` | -- | WIRE-009 filesystem fallback |
| `get_contracts_with_fallback(...)` | `list_contracts` | Falls back to `run_api_contract_scan` |

**Retry pattern:** 3 retries, base 1s exponential backoff.

---

### 1A.5 Codebase Intelligence Service (`src/codebase_intelligence/`)

#### Entry Point: `src/codebase_intelligence/main.py`

- FastAPI app with `lifespan` async context manager
- **Lifespan initialization (most complex of the three):**
  1. `ConnectionPool(config.database_path)` -- SQLite pool
  2. `init_symbols_db(pool)` -- Creates tables
  3. `SymbolDB(pool)` -- Symbol storage
  4. `GraphDB(pool)` -- Graph edge/snapshot storage
  5. `ChromaStore(config.chroma_path)` -- Vector store (downloads embedding model if needed)
  6. `GraphBuilder(existing_snapshot)` -- Loads from `GraphDB.load_snapshot()` if available
  7. `GraphAnalyzer(graph_builder.graph)`
  8. `ASTParser()` -- Multi-language tree-sitter parser
  9. `SymbolExtractor()` -- Converts raw parser output to `SymbolDefinition` models
  10. `ImportResolver()` -- Resolves import statements to file paths
  11. `DeadCodeDetector(graph_builder.graph)` -- Dead code analysis
  12. `SemanticIndexer(chroma_store, symbol_db)` -- Vector indexing
  13. `SemanticSearcher(chroma_store)` -- Vector search
  14. `ServiceInterfaceExtractor(ast_parser, symbol_extractor)` -- Endpoint/event detection
  15. `IncrementalIndexer(ast_parser, symbol_extractor, import_resolver, graph_builder, symbol_db, graph_db, semantic_indexer)` -- Full pipeline orchestrator
- **Lifespan teardown:** Saves graph snapshot, closes pool
- **All objects stored on `app.state`**
- **Routers registered:** `health_router`, `symbols_router`, `dependencies_router`, `search_router`, `artifacts_router`, `dead_code_router`

#### HTTP Endpoints

| Method | Path | Status | Request Body | Response Model |
|--------|------|--------|-------------|----------------|
| `GET` | `/api/health` | 200 | -- | `HealthStatus` (includes ChromaDB status) |
| `GET` | `/api/symbols` | 200 | query: `name`, `kind`, `language`, `service_name`, `file_path` | `list[dict]` |
| `GET` | `/api/dependencies` | 200 | query: `file_path`, `depth`, `direction` | `dict` (file_path, depth, dependencies, dependents) |
| `GET` | `/api/graph/analysis` | 200 | -- | `GraphAnalysis` dict |
| `POST` | `/api/search` | 200 | `SearchRequest` (query, language?, service_name?, top_k) | `list[dict]` |
| `POST` | `/api/artifacts` | 200 | `ArtifactRequest` (file_path, service_name?, source?, project_root?) | `dict` (indexed, symbols_found, dependencies_found, errors) |
| `GET` | `/api/dead-code` | 200 | query: `service_name` | `list[dict]` |

#### Indexing Pipeline (`IncrementalIndexer.index_file`)

7-step pipeline per file:
1. Detect language (from file extension)
2. Parse AST with tree-sitter
3. Extract symbols (classes, functions, methods, etc.)
4. Resolve imports (Python `import`/`from`, TypeScript `import`)
5. Update dependency graph (NetworkX DiGraph)
6. Persist to SQLite (indexed_files, symbols, import_references)
7. Semantic indexing (generate ChromaDB embeddings)

#### Multi-Language Parsers (`src/codebase_intelligence/parsers/`)

| Parser | Language | Extensions | Symbol Types Extracted |
|--------|----------|------------|----------------------|
| `PythonParser` | Python | `.py`, `.pyi` | CLASS, FUNCTION, METHOD (with decorators, docstrings, signatures) |
| `TypeScriptParser` | TypeScript | `.ts`, `.tsx` | INTERFACE, TYPE, CLASS, FUNCTION, METHOD, VARIABLE (with JSDoc) |
| `CSharpParser` | C# | `.cs` | CLASS, INTERFACE, ENUM, METHOD (with XML doc, namespace inference) |
| `GoParser` | Go | `.go` | FUNCTION, METHOD (with receiver type), CLASS (struct), INTERFACE |

All parsers use tree-sitter 0.25.2 API: `Language()`, `Parser(lang)`, `Query(lang, pattern)`, `QueryCursor(query).matches(node)`.

#### Services Layer

| Module | Purpose |
|--------|---------|
| `services/ast_parser.py` | `ASTParser` - Language detection + delegation to language-specific parsers |
| `services/symbol_extractor.py` | `SymbolExtractor` - Converts raw dict output to `SymbolDefinition` instances |
| `services/import_resolver.py` | `ImportResolver` - Resolves Python/TypeScript imports to file paths (supports relative, aliases, tsconfig paths) |
| `services/graph_builder.py` | `GraphBuilder` - Builds/maintains NetworkX DiGraph from ImportReference + DependencyEdge |
| `services/graph_analyzer.py` | `GraphAnalyzer` - PageRank, cycle detection, topological sort, connected components |
| `services/dead_code_detector.py` | `DeadCodeDetector` - Confidence-level classification (high/medium/low) |
| `services/semantic_indexer.py` | `SemanticIndexer` - Creates CodeChunks, indexes in ChromaDB, back-links chroma_id in SymbolDB |
| `services/semantic_searcher.py` | `SemanticSearcher` - Vector similarity search with language/service filters |
| `services/service_interface_extractor.py` | `ServiceInterfaceExtractor` - AST-based HTTP endpoint + event pattern detection (FastAPI, Express, NestJS, ASP.NET, Go net/http) |
| `services/incremental_indexer.py` | `IncrementalIndexer` - Orchestrates the 7-step indexing pipeline |

#### Storage Layer

| Module | Purpose |
|--------|---------|
| `storage/symbol_db.py` | `SymbolDB` - CRUD for indexed_files, symbols, import_references |
| `storage/graph_db.py` | `GraphDB` - Dependency edges + NetworkX graph snapshots (via `node_link_data`/`node_link_graph` with `edges="edges"`) |
| `storage/chroma_store.py` | `ChromaStore` - ChromaDB PersistentClient, collection `"code_chunks"`, `all-MiniLM-L6-v2` embedding model, cosine distance |

#### MCP Server (`src/codebase_intelligence/mcp_server.py`)

Server name: `"Codebase Intelligence"` (FastMCP)

| Tool Name | Parameters | Returns |
|-----------|------------|---------|
| `register_artifact` | `file_path, source?, service_name?, project_root?` | `dict` (indexed, symbols_found, deps_found) |
| `search_semantic` | `query, language?, service_name?, n_results?` | list of `SemanticSearchResult` dicts |
| `find_definition` | `symbol_name, kind?` | `{"file", "line", "kind", "signature"}` |
| `find_dependencies` | `file_path, depth?` | `{"imports", "imported_by", "transitive_deps", "circular_deps"}` |
| `analyze_graph` | -- | `GraphAnalysis` dict |
| `check_dead_code` | `service_name?` | list of `DeadCodeEntry` dicts |
| `find_callers` | `file_path` | list of caller file paths |
| `get_service_interface` | `file_path, service_name` | `ServiceInterface` dict |

**Note:** `search_semantic` accepts `n_results` param, passes it as `top_k` to the searcher internally.

#### MCP Client (`src/codebase_intelligence/mcp_client.py`)

Class: `CodebaseIntelligenceClient`

| Method | MCP Tool Called | Fallback |
|--------|----------------|----------|
| `register_artifact(...)` | `register_artifact` | -- |
| `search_semantic(...)` | `search_semantic` | -- |
| `find_definition(...)` | `find_definition` | -- |
| `find_dependencies(...)` | `find_dependencies` | -- |
| `analyze_graph()` | `analyze_graph` | -- |
| `check_dead_code(...)` | `check_dead_code` | -- |
| `get_service_interface(...)` | `get_service_interface` | -- |
| `generate_codebase_map(...)` | -- | WIRE-010 filesystem fallback |
| `get_codebase_map_with_fallback(...)` | `analyze_graph` | Falls back to `generate_codebase_map` |

**Retry pattern:** 3 retries, base 1s exponential backoff.

---

## Section 1B: Docker Infrastructure

### 1B.1 Compose Architecture (5-Tier Merge)

The system uses a 5-file Docker Compose merge architecture:

| Tier | File | Purpose |
|------|------|---------|
| 0 | `docker/docker-compose.infra.yml` | PostgreSQL 16 + Redis 7 on `backend` network |
| 1 | `docker/docker-compose.build1.yml` | Architect, Contract Engine, Codebase Intel |
| 2 | `docker/docker-compose.traefik.yml` | Traefik v3.6 reverse proxy on `frontend` network |
| 3 | `docker/docker-compose.generated.yml` | Generated services: auth, order, notification |
| 4 | `docker/docker-compose.run4.yml` | Cross-build wiring overrides, debug logging |

Additionally, a root `docker-compose.yml` exists as a standalone development setup.

### 1B.2 Root Compose (`docker-compose.yml`)

Standalone development compose with all three Build 1 services:
- `architect`: port `8001:8000`, volume `architect-data:/data`
- `contract-engine`: port `8002:8000`, volume `contract-data:/data`
- `codebase-intel`: port `8003:8000`, volume `intel-data:/data`
- Single bridge network `super-team-net`
- No external dependencies (no PostgreSQL/Redis)

### 1B.3 Tier 0: Infrastructure (`docker/docker-compose.infra.yml`)

| Service | Image | Port | Network | Healthcheck |
|---------|-------|------|---------|-------------|
| `postgres` | `postgres:16-alpine` | `5432` | `backend` | `pg_isready -U postgres` every 5s |
| `redis` | `redis:7-alpine` | `6379` | `backend` | `redis-cli ping` every 5s |

PostgreSQL init: Multiple databases created via `POSTGRES_MULTIPLE_DATABASES` env var: `superteam,auth_db,order_db,notification_db`.

### 1B.4 Tier 1: Build 1 Services (`docker/docker-compose.build1.yml`)

| Service | Container Name | Port | Memory Limit | Depends On | Networks |
|---------|---------------|------|-------------|------------|----------|
| `contract-engine` | `super-team-contract-engine` | `8002:8000` | 768m | `postgres` (healthy) | frontend, backend |
| `architect` | `super-team-architect` | `8001:8000` | 768m | `postgres` (healthy), `contract-engine` (healthy) | frontend, backend |
| `codebase-intel` | `super-team-codebase-intel` | `8003:8000` | 768m | `postgres` (healthy), `contract-engine` (healthy) | frontend, backend |

**Key dependency chain:** `postgres` -> `contract-engine` -> `architect` + `codebase-intel`

**Environment variables (Build 1):**
- All services: `DATABASE_URL=postgresql://superteam:superteam_secret@postgres:5432/superteam`
- Architect: `CONTRACT_ENGINE_URL=http://contract-engine:8000`, `CODEBASE_INTEL_URL=http://codebase-intel:8000`
- Codebase Intel: `CONTRACT_ENGINE_URL=http://contract-engine:8000`, `CHROMA_PATH=/data/chroma`, `GRAPH_PATH=/data/graph.json`

**Healthchecks:** All use Python urllib: `urllib.request.urlopen('http://localhost:8000/api/health')`, interval 10s, timeout 5s, retries 5.

**Network topology:**
- `frontend`: bridge (defined in this file)
- `backend`: external, name `docker_backend` (from Tier 0)

### 1B.5 Tier 2: Traefik (`docker/docker-compose.traefik.yml`)

- Image: `traefik:v3.6`
- Port: `80:80`
- Docker provider enabled, `exposedbydefault=false`
- Entrypoint: `web` at `:80`
- Networks: `frontend`, `backend`
- Volume: Docker socket mounted read-only

### 1B.6 Tier 3: Generated Services (`docker/docker-compose.generated.yml`)

| Service | Port | Memory | Depends On | Traefik Route |
|---------|------|--------|------------|---------------|
| `auth-service` | `8080` | 768m | `postgres` (healthy) | `/api/auth` |
| `order-service` | `8080` | 768m | `auth-service` (healthy), `postgres` (healthy) | `/api/orders` |
| `notification-service` | `8080` | 768m | `order-service` (healthy), `redis` (healthy) | `/api/notifications` |

**Dependency chain:** `postgres` -> `auth-service` -> `order-service` -> `notification-service` (also needs `redis`)

### 1B.7 Tier 4: Overrides (`docker/docker-compose.run4.yml`)

- Adds `frontend` + `backend` networks to Build 1 services
- Adds Traefik labels (PathPrefix routing) for Build 1 services:
  - Architect: `/api/architect`
  - Contract Engine: `/api/contracts`
  - Codebase Intelligence: `/api/codebase`
- Sets `LOG_LEVEL=DEBUG` for all services
- Enables Postgres statement logging and Redis debug logging
- Adds full environment variables for generated services (DATABASE_URL, JWT_SECRET, AUTH_SERVICE_URL)

### 1B.8 Dockerfiles

All three Build 1 services follow the same pattern:

| Property | Value |
|----------|-------|
| Base image | `python:3.12-slim` |
| Workdir | `/app` |
| Install | `requirements.txt` via pip |
| Copy | Full project source (`src/`, `pyproject.toml`, etc.) |
| CMD | `uvicorn src.<service>.main:app --host 0.0.0.0 --port 8000` |
| User | `appuser` (non-root, UID 1000) |

**Codebase Intelligence Dockerfile** has an additional step: pre-downloads the ChromaDB ONNX embedding model at build time to avoid runtime downloads.

### 1B.9 Memory Budget

| Component | Memory | Count | Total |
|-----------|--------|-------|-------|
| Build 1 services | 768m each | 3 | 2.3 GB |
| Generated services | 768m each | 3 | 2.3 GB |
| PostgreSQL | 256m | 1 | 256 MB |
| Redis | 128m | 1 | 128 MB |
| Traefik | 128m | 1 | 128 MB |
| **Total** | | | **~5.1 GB** |

---

## Section 1C: Test Infrastructure

### 1C.1 Test Layout Overview

```
tests/
  conftest.py              -- Root fixtures (shared models, connection pool, sample data)
  __init__.py
  fixtures/                -- Static test data files
    sample_prd.md
    sample_openapi.yaml
    sample_pact.json
    sample_docker_compose.yml
  test_architect/          -- Architect service unit tests (6 files)
  test_contract_engine/    -- Contract Engine unit tests (11 files)
  test_codebase_intelligence/ -- Codebase Intel unit tests (15 files)
  test_mcp/                -- MCP server integration tests (3 files)
  test_integration/        -- Cross-service integration tests (6 files)
  test_shared/             -- Shared module unit tests (6 files)
  e2e/api/                 -- End-to-end HTTP tests (4 files)
  build3/                  -- Build 3 (orchestrator) tests (34 files)
  run4/                    -- Run 4 verification tests (11 files)
  benchmarks/              -- Performance benchmarks (conftest + modules)
```

### 1C.2 Test Counts

| Test Category | File Count | Approx. Test Functions |
|---------------|-----------|----------------------|
| Build 1 unit/integration/e2e | 52 | ~989 |
| Build 3 tests | 34 | ~400+ (estimated) |
| Run 4 tests | 11 | ~200+ (estimated) |
| Benchmarks | 3+ | ~50+ (estimated) |
| **Total** | **~100** | **~1000+** |

### 1C.3 Root Conftest (`tests/conftest.py`)

**Fixtures provided:**
- `tmp_db_path` -- Temporary SQLite path
- `connection_pool` -- `ConnectionPool` with temp DB, auto-closed
- `sample_service_stack` -- `ServiceStack(python, fastapi, sqlite)`
- `sample_service_definition` -- `ServiceDefinition` for user-service
- `sample_entity_field` -- `EntityField(email, string, required)`
- `sample_state_machine` -- 3-state (active/inactive/suspended) state machine
- `sample_domain_entity` -- `DomainEntity` for User
- `sample_domain_relationship` -- Order REFERENCES User
- `sample_contract_entry` -- OpenAPI contract for user-service
- `sample_symbol_definition` -- `SymbolDefinition` for AuthService class
- `sample_health_status` -- Healthy test-service
- `mock_env_vars` -- Monkeypatches LOG_LEVEL, DATABASE_PATH, etc.

### 1C.4 E2E Conftest (`tests/e2e/api/conftest.py`)

- Auto-skip when no service is reachable (`_any_service_reachable()`)
- Service URLs configurable via env vars (`ARCHITECT_URL`, `CONTRACT_ENGINE_URL`, `CODEBASE_INTEL_URL`)
- Default ports: `8001`, `8002`, `8003`
- Session-scoped httpx clients for each service
- Sample data: PRD text, OpenAPI spec, AsyncAPI spec, Python source code (base64 encoded)
- `wait_for_service()` helper with configurable timeout

### 1C.5 Build 3 Conftest (`tests/build3/conftest.py`)

**Key autouse fixtures (applied globally to Build 3 tests):**
1. `_patch_state_machine_states` -- Removes `on_enter` callbacks from state machine states
2. `_patch_contract_violation_defaults` -- Makes `ContractViolation` accept missing `service`/`endpoint` fields
3. `_patch_cost_tracker_compat` -- Adds `start_phase`/`end_phase`/`phase_costs` shims to `PipelineCostTracker`
4. `_patch_integration_config_compat` -- Adds `compose_timeout`/`health_timeout` aliases
5. `_patch_builder_config_compat` -- Adds `timeout` alias (maps to `timeout_per_builder`)
6. `_patch_architect_config_compat` -- Adds `retries` alias (maps to `max_retries`)

**Sample fixtures:** `ServiceInfo`, `BuilderResult`, `PipelineState`, `SuperOrchestratorConfig`, `IntegrationReport`, `QualityGateReport`

### 1C.6 Run 4 Conftest (`tests/run4/conftest.py`)

- `MockToolResult` / `MockTextContent` -- Lightweight MCP result stubs
- `make_mcp_result(data, is_error)` -- Builds mock MCP tool results
- Session-scoped: `run4_config`, `sample_prd_text`, `build1_root`
- `StdioServerParameters`-compatible dicts for each MCP server
- `mock_mcp_session` -- `AsyncMock` simulating an MCP `ClientSession`

### 1C.7 Benchmarks Conftest (`tests/benchmarks/conftest.py`)

- Registers `benchmark` marker
- `_ensure_cost_tracker_shims` -- Same as Build 3 shims (prevents AttributeError)
- `consolidated_benchmark_report` -- Session-scoped finalizer that prints a formatted benchmark summary

### 1C.8 Test Module Coverage by Service

**Architect (`tests/test_architect/`):**
- `test_prd_parser.py` -- PRD parsing (entity extraction, relationships, contexts)
- `test_service_boundary.py` -- Boundary identification algorithm
- `test_domain_modeler.py` -- Domain model construction
- `test_contract_generator.py` -- OpenAPI stub generation
- `test_validator.py` -- 7-check validation
- `test_routers.py` -- HTTP endpoint tests via TestClient

**Contract Engine (`tests/test_contract_engine/`):**
- `test_contract_store.py` -- CRUD operations
- `test_openapi_validator.py` -- OpenAPI spec validation
- `test_asyncapi_validator.py` -- AsyncAPI spec validation
- `test_asyncapi_parser.py` -- AsyncAPI parsing
- `test_breaking_change_detector.py` -- Breaking change detection
- `test_compliance_checker.py` -- Compliance checking
- `test_implementation_tracker.py` -- Implementation tracking
- `test_schema_registry.py` -- Schema registry operations
- `test_test_generator.py` -- Test generation
- `test_version_manager.py` -- Version management
- `test_routers.py` -- HTTP endpoint tests
- `test_test_routers.py` -- Test/compliance router tests

**Codebase Intelligence (`tests/test_codebase_intelligence/`):**
- `test_ast_parser.py` -- Multi-language AST parsing
- `test_python_parser.py` -- Python symbol extraction
- `test_typescript_parser.py` -- TypeScript symbol extraction
- `test_csharp_parser.py` -- C# symbol extraction
- `test_go_parser.py` -- Go symbol extraction
- `test_symbol_extractor.py` -- Symbol model conversion
- `test_import_resolver.py` -- Import resolution
- `test_graph_builder.py` -- Graph construction
- `test_graph_analyzer.py` -- Graph analysis
- `test_dead_code_detector.py` -- Dead code detection
- `test_semantic_indexer.py` -- Vector indexing
- `test_semantic_searcher.py` -- Vector search
- `test_incremental_indexer_m6.py` -- Full pipeline
- `test_routers.py` -- HTTP endpoint tests
- `test_performance.py` -- Performance tests

**MCP (`tests/test_mcp/`):**
- `test_architect_mcp.py` -- Architect MCP server tool tests
- `test_contract_engine_mcp.py` -- Contract Engine MCP server tool tests
- `test_codebase_intel_mcp.py` -- Codebase Intel MCP server tool tests

**Integration (`tests/test_integration/`):**
- `test_architect_to_contracts.py` -- Architect -> Contract Engine flow
- `test_codebase_indexing.py` -- Codebase indexing pipeline
- `test_docker_compose.py` -- Docker Compose validation
- `test_pipeline_parametrized.py` -- Parametrized pipeline tests
- `test_5prd_pipeline.py` -- 5-PRD pipeline test
- `test_svc_contracts.py` -- Service contract verification

**Shared (`tests/test_shared/`):**
- `test_config.py` -- Configuration loading
- `test_constants.py` -- Constants validation
- `test_db_connection.py` -- ConnectionPool tests
- `test_errors.py` -- Error hierarchy tests
- `test_models.py` -- Pydantic model tests
- `test_schema.py` -- Database schema tests

---

## Section 1D: Known Integration Points

### 1D.1 Service-to-Service HTTP Calls

| Caller | Target | Endpoint | Purpose |
|--------|--------|----------|---------|
| Architect MCP Server | Contract Engine | `GET /api/contracts?service_name={name}` | `get_contracts_for_service` tool |
| Architect Config | Contract Engine | `http://contract-engine:8000` (env `CONTRACT_ENGINE_URL`) | Cross-service URL |
| Architect Config | Codebase Intel | `http://codebase-intel:8000` (env `CODEBASE_INTEL_URL`) | Cross-service URL |
| Codebase Intel Config | Contract Engine | `http://contract-engine:8000` (env `CONTRACT_ENGINE_URL`) | Cross-service URL |

### 1D.2 MCP Tool Dependencies (Inter-Service)

| Consumer (MCP Client) | Provider (MCP Server) | Tools Used |
|------------------------|----------------------|------------|
| Build 2 Builders -> `ArchitectClient` | Architect | `decompose`, `get_service_map`, `get_domain_model`, `get_contracts_for_service` |
| Build 2 Builders -> `ContractEngineClient` | Contract Engine | `create_contract`, `list_contracts`, `get_contract`, `validate_spec`, `mark_implemented`, `generate_tests`, etc. |
| Build 2 Builders -> `CodebaseIntelligenceClient` | Codebase Intelligence | `register_artifact`, `search_semantic`, `find_definition`, `find_dependencies`, `analyze_graph`, `check_dead_code`, `get_service_interface` |

### 1D.3 Fallback Patterns (WIRE-009/010/011)

| Wire ID | Client | MCP Tool | Fallback Method |
|---------|--------|----------|-----------------|
| WIRE-009 | `ContractEngineClient` | `list_contracts` | `run_api_contract_scan()` -- filesystem-based contract scanning |
| WIRE-010 | `CodebaseIntelligenceClient` | `analyze_graph` | `generate_codebase_map()` -- filesystem-based codebase mapping |
| WIRE-011 | `ArchitectClient` | `decompose` | `decompose_prd_basic()` -- basic filesystem-based PRD decomposition |

All fallbacks are triggered when MCP connection fails after retries.

### 1D.4 Shared Database Dependencies

| Database | Services | Tables |
|----------|----------|--------|
| Architect SQLite | Architect | `service_maps`, `domain_models`, `decomposition_runs` |
| Contracts SQLite | Contract Engine | `build_cycles`, `contracts`, `contract_versions`, `breaking_changes`, `implementations`, `test_suites`, `shared_schemas`, `schema_consumers` |
| Symbols SQLite | Codebase Intelligence | `indexed_files`, `symbols`, `dependency_edges`, `import_references`, `graph_snapshots` |

Each service owns its own SQLite database. No shared database between Build 1 services.

### 1D.5 Startup Order

Required startup order based on `depends_on` chains in `docker-compose.build1.yml`:

```
postgres (healthy) -> contract-engine (healthy) -> architect
                                                -> codebase-intel
```

The `architect` and `codebase-intel` services both depend on `contract-engine` being healthy.

---

## Section 1E: Known API Mismatches Verification

This section verifies the 5 API mismatches reported in a prior analysis (SVC-003, SVC-005, SVC-007, SVC-009, SVC-010).

### SVC-003: `generate_tests` Return Type

**Prior Report:** MCP server returns string (test_code), Build 2 mcp_client expects string.

**Verification:**
- `src/contract_engine/mcp_server.py` -- The `generate_tests` tool:
  ```python
  result = test_generator.generate(contract, pool)
  return result.test_code  # Returns str
  ```
- `src/contract_engine/mcp_client.py` -- `ContractEngineClient.generate_tests()`:
  ```python
  return raw_text  # Returns str (raw text from MCP)
  ```

**Status: FIXED.** Both sides agree on `str` return type. The MCP server returns `result.test_code` (a string), and the client returns the raw text string directly.

---

### SVC-005: `mark_implemented` Response Field Name

**Prior Report:** MCP server returns `{"total"}` but Pydantic model has `total_implementations`.

**Verification:**
- `src/shared/models/contracts.py` -- `MarkResponse`:
  ```python
  class MarkResponse(BaseModel):
      marked: int
      total_implementations: int
      all_implemented: bool
  ```
- `src/contract_engine/mcp_server.py` (lines 272-276) -- `mark_implemented` tool:
  ```python
  return {
      "marked": result.marked,
      "total": result.total_implementations,  # KEY DIFFERENCE
      "all_implemented": result.all_implemented,
  }
  ```
- `src/contract_engine/routers/implementations.py` -- HTTP endpoint returns `MarkResponse` directly (with field `total_implementations`).
- `src/contract_engine/services/implementation_tracker.py` -- `mark_implemented()` returns `MarkResponse(marked=..., total_implementations=..., all_implemented=...)`.

**Status: CONFIRMED MISMATCH.**

The MCP server manually builds a dict with key `"total"` instead of using the `MarkResponse` model's field name `"total_implementations"`. This means:
- **HTTP consumers** see `{"marked": N, "total_implementations": N, "all_implemented": bool}` (correct per MarkResponse model)
- **MCP consumers** see `{"marked": N, "total": N, "all_implemented": bool}` (uses `"total"` not `"total_implementations"`)

Any MCP client code that accesses `result["total_implementations"]` will get a `KeyError`. MCP clients must use `result["total"]`.

The `ContractEngineClient.mark_implemented()` in `mcp_client.py` does:
```python
data = json.loads(result.content[0].text)
return data  # Returns the raw dict with "total" key
```
So the MCP client passes through the raw dict. Downstream consumers expecting `total_implementations` will break.

**Recommendation:** Either change the MCP server to use `result.model_dump()` (which would produce `total_implementations`), or update the MCP client to normalize the key.

---

### SVC-007: `find_definition` Return Field Names

**Prior Report:** MCP server used `file_path` and `line_start` instead of `file` and `line`.

**Verification:**
- `src/codebase_intelligence/mcp_server.py` -- `find_definition` tool:
  ```python
  return {
      "file": sym.file_path,
      "line": sym.line_start,
      "kind": sym.kind.value if isinstance(sym.kind, SymbolKind) else sym.kind,
      "signature": sym.signature,
  }
  ```

**Status: FIXED.** The MCP server returns `{"file", "line", "kind", "signature"}` as expected. Uses `file` (not `file_path`) and `line` (not `line_start`).

---

### SVC-009: `find_dependencies` Return Field Names

**Prior Report:** MCP server returned wrong field names.

**Verification:**
- `src/codebase_intelligence/mcp_server.py` -- `find_dependencies` tool:
  ```python
  return {
      "imports": forward_deps,
      "imported_by": reverse_deps,
      "transitive_deps": transitive,
      "circular_deps": circular_deps,
  }
  ```

**Status: FIXED.** The MCP server returns `{"imports", "imported_by", "transitive_deps", "circular_deps"}` as expected.

---

### SVC-010: `search_semantic` Parameter Name

**Prior Report:** MCP server tool used wrong parameter name for result count.

**Verification:**
- `src/codebase_intelligence/mcp_server.py` -- `search_semantic` tool signature:
  ```python
  @mcp.tool()
  def search_semantic(
      query: str,
      language: str = "",
      service_name: str = "",
      n_results: int = 10,
  ) -> list[dict]:
  ```
  Internally passes `n_results` as `top_k` to the searcher:
  ```python
  results = searcher.search(query=query, ..., top_k=n_results)
  ```

- `src/codebase_intelligence/mcp_client.py` -- `CodebaseIntelligenceClient.search_semantic()`:
  ```python
  result = await session.call_tool("search_semantic", arguments={
      "query": query,
      "n_results": max_results,
      ...
  })
  ```

**Status: FIXED.** The MCP tool accepts `n_results` and the client sends `n_results`. Internally mapped to `top_k` for the searcher.

---

### Mismatch Summary Table

| ID | Issue | Status | Severity | Location |
|----|-------|--------|----------|----------|
| SVC-003 | `generate_tests` return type | **FIXED** | -- | `mcp_server.py` returns `str`, client expects `str` |
| SVC-005 | `mark_implemented` field name `total` vs `total_implementations` | **OPEN** | Medium | `src/contract_engine/mcp_server.py` line 274 |
| SVC-007 | `find_definition` field names | **FIXED** | -- | Returns `file`/`line` correctly |
| SVC-009 | `find_dependencies` field names | **FIXED** | -- | Returns correct field names |
| SVC-010 | `search_semantic` parameter name | **FIXED** | -- | Accepts `n_results` correctly |

---

## Appendix A: Complete File Inventory

### Architect Service

| File | Lines | Purpose |
|------|-------|---------|
| `src/architect/__init__.py` | -- | Package init |
| `src/architect/main.py` | ~80 | FastAPI app + lifespan |
| `src/architect/config.py` | ~10 | Re-exports ArchitectConfig |
| `src/architect/mcp_server.py` | ~180 | 4 MCP tools |
| `src/architect/mcp_client.py` | ~200 | MCP client with fallback |
| `src/architect/routers/health.py` | ~30 | Health endpoint |
| `src/architect/routers/decomposition.py` | ~60 | Decompose endpoint |
| `src/architect/routers/service_map.py` | ~30 | Service map endpoint |
| `src/architect/routers/domain_model.py` | ~30 | Domain model endpoint |
| `src/architect/services/prd_parser.py` | ~600 | PRD text parsing |
| `src/architect/services/service_boundary.py` | ~300 | Boundary identification |
| `src/architect/services/domain_modeler.py` | ~200 | Domain model construction |
| `src/architect/services/contract_generator.py` | ~250 | OpenAPI stub generation |
| `src/architect/services/validator.py` | ~200 | 7-check validation |
| `src/architect/storage/service_map_store.py` | ~80 | Service map persistence |
| `src/architect/storage/domain_model_store.py` | ~80 | Domain model persistence |

### Contract Engine Service

| File | Lines | Purpose |
|------|-------|---------|
| `src/contract_engine/__init__.py` | -- | Package init |
| `src/contract_engine/main.py` | ~80 | FastAPI app + lifespan |
| `src/contract_engine/config.py` | ~10 | Re-exports ContractEngineConfig |
| `src/contract_engine/mcp_server.py` | ~320 | 10 MCP tools |
| `src/contract_engine/mcp_client.py` | ~250 | MCP client with fallback |
| `src/contract_engine/routers/health.py` | ~30 | Health endpoint |
| `src/contract_engine/routers/contracts.py` | ~80 | Contract CRUD endpoints |
| `src/contract_engine/routers/validation.py` | ~40 | Validation endpoint |
| `src/contract_engine/routers/breaking_changes.py` | ~50 | Breaking changes endpoint |
| `src/contract_engine/routers/implementations.py` | ~50 | Implementation tracking endpoints |
| `src/contract_engine/routers/tests.py` | ~60 | Test generation/compliance endpoints |
| `src/contract_engine/services/contract_store.py` | ~150 | Contract CRUD with upsert |
| `src/contract_engine/services/openapi_validator.py` | ~100 | OpenAPI validation |
| `src/contract_engine/services/asyncapi_validator.py` | ~100 | AsyncAPI validation |
| `src/contract_engine/services/asyncapi_parser.py` | ~350 | AsyncAPI 2.x/3.x parser |
| `src/contract_engine/services/breaking_change_detector.py` | ~300 | Deep-diff breaking changes |
| `src/contract_engine/services/compliance_checker.py` | ~400 | Runtime compliance validation |
| `src/contract_engine/services/implementation_tracker.py` | ~150 | Implementation tracking |
| `src/contract_engine/services/schema_registry.py` | ~150 | Shared schema management |
| `src/contract_engine/services/test_generator.py` | ~400 | Schemathesis test generation |
| `src/contract_engine/services/version_manager.py` | ~150 | Build cycle immutability |

### Codebase Intelligence Service

| File | Lines | Purpose |
|------|-------|---------|
| `src/codebase_intelligence/__init__.py` | ~3 | Package init |
| `src/codebase_intelligence/main.py` | ~120 | FastAPI app + complex lifespan |
| `src/codebase_intelligence/config.py` | ~10 | Re-exports CodebaseIntelConfig |
| `src/codebase_intelligence/mcp_server.py` | ~250 | 8 MCP tools |
| `src/codebase_intelligence/mcp_client.py` | ~250 | MCP client with fallback |
| `src/codebase_intelligence/routers/__init__.py` | ~17 | Router exports |
| `src/codebase_intelligence/routers/health.py` | ~60 | Health endpoint (SQLite + ChromaDB) |
| `src/codebase_intelligence/routers/symbols.py` | ~58 | Symbol query endpoint |
| `src/codebase_intelligence/routers/dependencies.py` | ~47 | Dependency/graph endpoints |
| `src/codebase_intelligence/routers/search.py` | ~36 | Semantic search endpoint |
| `src/codebase_intelligence/routers/artifacts.py` | ~41 | Artifact indexing endpoint |
| `src/codebase_intelligence/routers/dead_code.py` | ~45 | Dead code detection endpoint |
| `src/codebase_intelligence/services/ast_parser.py` | ~129 | Multi-language AST parser |
| `src/codebase_intelligence/services/symbol_extractor.py` | ~101 | Symbol model conversion |
| `src/codebase_intelligence/services/import_resolver.py` | ~603 | Import resolution (Python + TypeScript) |
| `src/codebase_intelligence/services/graph_builder.py` | ~154 | NetworkX DiGraph construction |
| `src/codebase_intelligence/services/graph_analyzer.py` | ~151 | Graph analysis (PageRank, cycles, topo sort) |
| `src/codebase_intelligence/services/dead_code_detector.py` | ~186 | Dead code with confidence levels |
| `src/codebase_intelligence/services/semantic_indexer.py` | ~139 | ChromaDB vector indexing |
| `src/codebase_intelligence/services/semantic_searcher.py` | ~166 | ChromaDB vector search |
| `src/codebase_intelligence/services/service_interface_extractor.py` | ~1279 | HTTP + event pattern detection (4 languages) |
| `src/codebase_intelligence/services/incremental_indexer.py` | ~159 | 7-step indexing pipeline |
| `src/codebase_intelligence/parsers/python_parser.py` | ~389 | Python AST symbol extraction |
| `src/codebase_intelligence/parsers/typescript_parser.py` | ~360 | TypeScript/TSX symbol extraction |
| `src/codebase_intelligence/parsers/csharp_parser.py` | ~268 | C# symbol extraction |
| `src/codebase_intelligence/parsers/go_parser.py` | ~261 | Go symbol extraction |
| `src/codebase_intelligence/storage/chroma_store.py` | ~188 | ChromaDB vector storage |
| `src/codebase_intelligence/storage/graph_db.py` | ~174 | Graph edge/snapshot SQLite storage |
| `src/codebase_intelligence/storage/symbol_db.py` | ~270 | Symbol/file/import SQLite storage |

### Shared Modules

| File | Lines | Purpose |
|------|-------|---------|
| `src/shared/__init__.py` | -- | Package init |
| `src/shared/config.py` | ~80 | Base + derived Pydantic Settings configs |
| `src/shared/constants.py` | ~30 | Service names, ports, version |
| `src/shared/errors.py` | ~100 | Error hierarchy + exception handler |
| `src/shared/logging.py` | ~80 | JSON formatter + trace ID middleware |
| `src/shared/utils.py` | ~40 | File/hash/JSON utilities |
| `src/shared/db/connection.py` | ~80 | Thread-local SQLite ConnectionPool |
| `src/shared/db/schema.py` | ~200 | Database schema initializers |
| `src/shared/models/architect.py` | ~120 | Architect data models |
| `src/shared/models/contracts.py` | ~180 | Contract data models |
| `src/shared/models/codebase.py` | ~150 | Codebase intelligence data models |
| `src/shared/models/common.py` | ~40 | Common shared models |

---

## Appendix B: Technology Stack Summary

| Category | Technology | Version |
|----------|-----------|---------|
| Language | Python | 3.12 |
| Web Framework | FastAPI | 0.129.0 |
| ASGI Server | Uvicorn | >=0.30.0 |
| Data Validation | Pydantic | >=2.5.0 |
| Settings | Pydantic Settings | >=2.1.0 |
| HTTP Client | httpx | >=0.27.0 |
| AST Parsing | tree-sitter | 0.25.2 |
| Vector DB | ChromaDB | 1.5.0 |
| Graph Analysis | NetworkX | 3.6.1 |
| Inter-Service Protocol | MCP (Model Context Protocol) | >=1.25,<2 |
| API Testing | Schemathesis | 4.10.1 |
| OpenAPI Validation | openapi-spec-validator | >=0.7.0 |
| $ref Resolution | prance | >=25.0.0 |
| YAML | PyYAML | >=6.0 |
| JSON Schema | jsonschema | >=4.20.0 |
| State Machines | transitions | >=0.9.0 |
| CLI | Typer | >=0.12.0 |
| Console Output | Rich | >=13.0.0 |
| Database | SQLite (WAL mode) | Built-in |
| Embedding Model | all-MiniLM-L6-v2 (ONNX) | Via ChromaDB |
| Container Runtime | Docker | -- |
| Container Orchestration | Docker Compose | v2 |
| Reverse Proxy | Traefik | v3.6 |
| Infrastructure DB | PostgreSQL | 16 (alpine) |
| Infrastructure Cache | Redis | 7 (alpine) |

---

*End of Architecture Report. This document is the single source of truth for all Build 1 verification agents.*

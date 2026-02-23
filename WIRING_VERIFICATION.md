# Wiring Verification Report: Build 1

> **Agent:** wiring-verifier
> **Generated:** 2026-02-23
> **Scope:** Docker infrastructure, health checks, inter-service communication, MCP transport layer
> **Status:** READ ONLY -- No source files modified

---

## Table of Contents

1. [4A: Docker Health Check Correctness](#4a-docker-health-check-correctness)
2. [4B: Startup Order Verification](#4b-startup-order-verification)
3. [4C: MCP Transport Layer](#4c-mcp-transport-layer)
4. [4D: Inter-Service HTTP Calls](#4d-inter-service-http-calls)
5. [4E: Database Initialization Idempotency](#4e-database-initialization-idempotency)
6. [4F: ChromaDB Embedding Model Availability](#4f-chromadb-embedding-model-availability)
7. [4G: Environment Variable Completeness](#4g-environment-variable-completeness)
8. [4H: Network Configuration](#4h-network-configuration)
9. [4I: Dockerfile Review](#4i-dockerfile-review)
10. [Issues Summary](#issues-summary)

---

## 4A: Docker Health Check Correctness

### Health Check Analysis Table

| Compose File | Service | Health Check Command | Tests What It Claims? | Interval | Timeout | Retries | Start Period | Compatible w/ python:3.12-slim? | Verdict |
|---|---|---|---|---|---|---|---|---|---|
| `docker-compose.yml` | `architect` | `python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/api/health')"` | YES -- hits `/api/health` endpoint | 10s | 5s | 5 | 15s | YES -- urllib is stdlib | PASS |
| `docker-compose.yml` | `contract-engine` | Same urllib pattern | YES | 10s | 5s | 5 | 10s | YES | PASS |
| `docker-compose.yml` | `codebase-intel` | Same urllib pattern | YES | 10s | 5s | 5 | 20s | YES | PASS |
| `infra.yml` | `postgres` | `pg_isready -U superteam -d superteam` | YES -- checks PG accepting connections | 10s | 5s | 5 | 10s | N/A (postgres:16-alpine has pg_isready) | PASS |
| `infra.yml` | `redis` | `redis-cli ping` | YES -- checks Redis PING/PONG | 10s | 5s | 5 | 5s | N/A (redis:7-alpine has redis-cli) | PASS |
| `build1.yml` | `contract-engine` | Same urllib pattern | YES | 10s | 5s | 5 | 10s | YES | PASS |
| `build1.yml` | `architect` | Same urllib pattern | YES | 10s | 5s | 5 | 15s | YES | PASS |
| `build1.yml` | `codebase-intel` | Same urllib pattern | YES | 10s | 5s | 5 | 20s | YES | PASS |
| `traefik.yml` | `traefik` | `traefik healthcheck` | YES -- Traefik built-in healthcheck CLI | 10s | 5s | 5 | 10s | N/A (traefik:v3.6 image) | PASS |
| `generated.yml` | `auth-service` | `curl -f http://localhost:8080/health` | **RISK** -- assumes `curl` is installed in the generated service image | 10s | 5s | 5 | 15s | DEPENDS on generated Dockerfile | WARN |
| `generated.yml` | `order-service` | `curl -f http://localhost:8080/health` | Same risk | 10s | 5s | 5 | 15s | DEPENDS | WARN |
| `generated.yml` | `notification-service` | `curl -f http://localhost:8080/health` | Same risk | 10s | 5s | 5 | 15s | DEPENDS | WARN |

### Health Endpoint Cross-Reference

Each Build 1 service health check calls `http://localhost:8000/api/health`. Verified in the actual code:

| Service | Health Route Path | Verified In |
|---|---|---|
| Architect | `@router.get("/api/health")` | `src/architect/routers/health.py` -- router has no prefix, path is `/api/health` |
| Contract Engine | `@router.get("/health")` with `prefix="/api"` | `src/contract_engine/routers/health.py` -- `APIRouter(prefix="/api")`, so final path is `/api/health` |
| Codebase Intelligence | `@router.get("/api/health")` | `src/codebase_intelligence/routers/health.py` -- router has no prefix, path is `/api/health` |

**All three endpoints resolve to `/api/health` on port 8000.** The health checks are correct.

### Timing Assessment

| Service | Start Period | Rationale | Assessment |
|---|---|---|---|
| postgres | 10s | PostgreSQL cold-start typically < 5s | Adequate |
| redis | 5s | Redis starts in < 1s | Adequate |
| contract-engine | 10s | Python + FastAPI + SQLite init | Adequate, but could be tight under memory pressure with 768m limit |
| architect | 15s | Python + FastAPI + SQLite init | Adequate |
| codebase-intel | 20s | Python + FastAPI + SQLite + ChromaDB + tree-sitter | **Marginal** -- ChromaDB initialization + embedding model load could exceed 20s on first run |
| traefik | 10s | Static binary, fast startup | Adequate |

---

## 4B: Startup Order Verification

### Dependency Chain Diagram

```
Root Compose (docker-compose.yml) -- Standalone Dev Mode:
  contract-engine (no deps)
    <- architect (depends_on: contract-engine healthy)
    <- codebase-intel (depends_on: contract-engine healthy)

Tier 0-1 Merge (infra.yml + build1.yml):
  postgres (no deps, Tier 0)
    <- contract-engine (depends_on: postgres healthy)
      <- architect (depends_on: postgres healthy, contract-engine healthy)
      <- codebase-intel (depends_on: postgres healthy, contract-engine healthy)

Tier 0-3 Merge (infra.yml + build1.yml + traefik.yml + generated.yml):
  postgres (no deps)
  redis (no deps)
    <- contract-engine (depends_on: postgres healthy)
      <- architect (depends_on: postgres + contract-engine healthy)
      <- codebase-intel (depends_on: postgres + contract-engine healthy)
        <- traefik (depends_on: architect + contract-engine + codebase-intelligence* healthy)
    <- auth-service (depends_on: postgres healthy)
      <- order-service (depends_on: auth-service + postgres healthy)
        <- notification-service (depends_on: order-service + redis healthy)
```

### Verification Results

| Check | Status | Notes |
|---|---|---|
| postgres starts before contract-engine | PASS | `build1.yml`: contract-engine `depends_on: postgres: condition: service_healthy` |
| contract-engine starts before architect | PASS | `build1.yml`: architect `depends_on: contract-engine: condition: service_healthy` |
| contract-engine starts before codebase-intel | PASS | `build1.yml`: codebase-intel `depends_on: contract-engine: condition: service_healthy` |
| No circular dependencies in Build 1 | PASS | Chain is strictly linear: postgres -> contract-engine -> {architect, codebase-intel} |
| postgres starts before auth-service | PASS | `generated.yml`: auth-service `depends_on: postgres: condition: service_healthy` |
| auth-service starts before order-service | PASS | `generated.yml`: order-service `depends_on: auth-service: condition: service_healthy` |
| order-service + redis start before notification-service | PASS | `generated.yml`: notification-service `depends_on: order-service + redis: condition: service_healthy` |
| Traefik depends on all Build 1 services | **FAIL** | See WIRE-ISSUE-001 below |

### **WIRE-ISSUE-001: Service Name Mismatch (CRITICAL)**

**Severity: CRITICAL**

In `docker-compose.traefik.yml` (line 42), Traefik declares a dependency on `codebase-intelligence`:
```yaml
depends_on:
  codebase-intelligence:
    condition: service_healthy
```

But in `docker-compose.build1.yml` (line 96), the service is defined as `codebase-intel`:
```yaml
services:
  codebase-intel:
    container_name: super-team-codebase-intel
```

And in `docker-compose.run4.yml` (line 50), the override also uses `codebase-intelligence`:
```yaml
services:
  codebase-intelligence:
```

**Impact:** When merging Tier 1 + Tier 2 (`-f build1.yml -f traefik.yml`):
- Docker Compose will treat `codebase-intel` (Tier 1) and `codebase-intelligence` (Tier 2/4) as **different services**
- Traefik's `depends_on: codebase-intelligence` will reference a service that does not exist in the merged definition
- The Tier 4 override for `codebase-intelligence` will create a new orphan service instead of overriding `codebase-intel`
- Result: **Docker Compose will error or create unexpected behavior on compose-up**

**Fix Required:** Either rename the service in `build1.yml` to `codebase-intelligence` OR change `traefik.yml` and `run4.yml` to use `codebase-intel`.

---

## 4C: MCP Transport Layer

### 4C.1: MCP Server Analysis

#### Server Names and Tool Registration

| Service | FastMCP Server Name | Name Format | Expected `mcp__` Prefix |
|---|---|---|---|
| Architect | `FastMCP("Architect")` | Clean | `mcp__Architect__<tool>` |
| Contract Engine | `FastMCP("Contract Engine")` | Contains space | `mcp__Contract Engine__<tool>` (space in name may cause issues) |
| Codebase Intelligence | `FastMCP("Codebase Intelligence")` | Contains space | `mcp__Codebase Intelligence__<tool>` (space in name may cause issues) |

**WIRE-ISSUE-002: MCP Server Names Contain Spaces (LOW)**

**Severity: LOW**

The FastMCP server names `"Contract Engine"` and `"Codebase Intelligence"` contain spaces. Whether this causes issues depends on how downstream consumers reference the `mcp__servername__toolname` format. The MCP SDK itself handles this, but any string-based tool name matching that constructs names from the server name could break.

#### Architect MCP Server Tools

| Tool Name | Decorator | Parameters | Return Type | JSON-Serializable? | Docstring? |
|---|---|---|---|---|---|
| `decompose` | `@mcp.tool(name="decompose")` | `prd_text: str` | `dict[str, Any]` | YES | YES (detailed) |
| `get_service_map` | `@mcp.tool()` | `project_name: str \| None = None` | `dict[str, Any]` | YES | YES |
| `get_domain_model` | `@mcp.tool()` | `project_name: str \| None = None` | `dict[str, Any]` | YES | YES |
| `get_contracts_for_service` | `@mcp.tool(name="get_contracts_for_service")` | `service_name: str` | `list[dict[str, Any]]` | YES | YES |

#### Contract Engine MCP Server Tools

| Tool Name | Decorator | Parameters | Return Type | JSON-Serializable? | Docstring? |
|---|---|---|---|---|---|
| `create_contract` | `@mcp.tool()` | `service_name: str, type: str, version: str, spec: dict, build_cycle_id: str \| None = None` | `dict` | YES | YES |
| `list_contracts` | `@mcp.tool()` | `page: int=1, page_size: int=20, service_name: str\|None, contract_type: str\|None, status: str\|None` | `dict` | YES | YES |
| `get_contract` | `@mcp.tool()` | `contract_id: str` | `dict` | YES | YES |
| `validate_spec` | `@mcp.tool(name="validate_spec")` | `spec: dict, type: str` | `dict` | YES | YES |
| `check_breaking_changes` | `@mcp.tool(name="check_breaking_changes")` | `contract_id: str, new_spec: dict\|None = None` | `list` | YES | YES |
| `mark_implemented` | `@mcp.tool(name="mark_implemented")` | `contract_id: str, service_name: str, evidence_path: str` | `dict` | YES | YES |
| `get_unimplemented_contracts` | `@mcp.tool(name="get_unimplemented_contracts")` | `service_name: str\|None = None` | `list` | YES | YES |
| `generate_tests` | `@mcp.tool()` | `contract_id: str, framework: str="pytest", include_negative: bool=False` | `str` | YES | YES |
| `check_compliance` | `@mcp.tool()` | `contract_id: str, response_data: dict\|None = None` | `list` | YES | YES |
| `validate_endpoint` | `@mcp.tool(name="validate_endpoint")` | `service_name: str, method: str, path: str, response_body: dict, status_code: int=200` | `dict` | YES | YES |

#### Codebase Intelligence MCP Server Tools

| Tool Name | Decorator | Parameters | Return Type | JSON-Serializable? | Docstring? |
|---|---|---|---|---|---|
| `register_artifact` | `@mcp.tool(name="register_artifact")` | `file_path: str, service_name: str\|None, source_base64: str\|None, project_root: str\|None` | `dict[str, Any]` | YES | YES |
| `search_semantic` | `@mcp.tool(name="search_semantic")` | `query: str, language: str\|None, service_name: str\|None, n_results: int=10` | `list[dict[str, Any]]` | YES | YES |
| `find_definition` | `@mcp.tool(name="find_definition")` | `symbol: str, language: str\|None = None` | `dict[str, Any]` | YES | YES |
| `find_dependencies` | `@mcp.tool(name="find_dependencies")` | `file_path: str, depth: int=1, direction: str="both"` | `dict[str, Any]` | YES | YES |
| `analyze_graph` | `@mcp.tool()` | (none) | `dict[str, Any]` | YES | YES |
| `check_dead_code` | `@mcp.tool(name="check_dead_code")` | `service_name: str\|None = None` | `list[dict[str, Any]]` | YES | YES |
| `find_callers` | `@mcp.tool(name="find_callers")` | `symbol: str, max_results: int=50` | `list[dict[str, Any]]` | YES | YES |
| `get_service_interface` | `@mcp.tool(name="get_service_interface")` | `service_name: str` | `dict[str, Any]` | YES | YES |

### 4C.2: MCP Client Analysis

#### Client-Server Tool Name Matching

| Client Class | Client Method | MCP Tool Called | Server Tool Name | Match? |
|---|---|---|---|---|
| `ArchitectClient` | `decompose()` | `"decompose"` | `decompose` (via `name="decompose"`) | PASS |
| `ArchitectClient` | `get_service_map()` | `"get_service_map"` | `get_service_map` (auto from func) | PASS |
| `ArchitectClient` | `get_contracts_for_service()` | `"get_contracts_for_service"` | `get_contracts_for_service` (via `name=`) | PASS |
| `ArchitectClient` | `get_domain_model()` | `"get_domain_model"` | `get_domain_model` (auto from func) | PASS |
| `ContractEngineClient` | `create_contract()` | `"create_contract"` | `create_contract` (auto) | PASS |
| `ContractEngineClient` | `validate_spec()` | `"validate_spec"` | `validate_spec` (via `name=`) | PASS |
| `ContractEngineClient` | `list_contracts()` | `"list_contracts"` | `list_contracts` (auto) | PASS |
| `ContractEngineClient` | `get_contract()` | `"get_contract"` | `get_contract` (auto) | PASS |
| `ContractEngineClient` | `validate_endpoint()` | `"validate_endpoint"` | `validate_endpoint` (via `name=`) | PASS |
| `ContractEngineClient` | `generate_tests()` | `"generate_tests"` | `generate_tests` (auto) | PASS |
| `ContractEngineClient` | `check_breaking_changes()` | `"check_breaking_changes"` | `check_breaking_changes` (via `name=`) | PASS |
| `ContractEngineClient` | `mark_implemented()` | `"mark_implemented"` | `mark_implemented` (via `name=`) | PASS |
| `ContractEngineClient` | `get_unimplemented_contracts()` | `"get_unimplemented_contracts"` | `get_unimplemented_contracts` (via `name=`) | PASS |
| `CodebaseIntelligenceClient` | `find_definition()` | `"find_definition"` | `find_definition` (via `name=`) | PASS |
| `CodebaseIntelligenceClient` | `find_callers()` | `"find_callers"` | `find_callers` (via `name=`) | PASS |
| `CodebaseIntelligenceClient` | `find_dependencies()` | `"find_dependencies"` | `find_dependencies` (via `name=`) | PASS |
| `CodebaseIntelligenceClient` | `search_semantic()` | `"search_semantic"` | `search_semantic` (via `name=`) | PASS |
| `CodebaseIntelligenceClient` | `get_service_interface()` | `"get_service_interface"` | `get_service_interface` (via `name=`) | PASS |
| `CodebaseIntelligenceClient` | `check_dead_code()` | `"check_dead_code"` | `check_dead_code` (via `name=`) | PASS |
| `CodebaseIntelligenceClient` | `register_artifact()` | `"register_artifact"` | `register_artifact` (via `name=`) | PASS |

#### Parameter Name Matching (Client -> Server)

| Client Call | Client Params | Server Params | Match? |
|---|---|---|---|
| `ArchitectClient.decompose()` | `{"prd_text": prd_text}` | `prd_text: str` | PASS |
| `CodebaseIntelligenceClient.find_definition()` | `{"symbol": symbol}` | `symbol: str` | PASS |
| `CodebaseIntelligenceClient.search_semantic()` | `{"query": ..., "n_results": ...}` | `query: str, n_results: int` | PASS |
| `CodebaseIntelligenceClient.find_callers()` | `{"symbol": ..., "max_results": ...}` | `symbol: str, max_results: int` | PASS |
| `CodebaseIntelligenceClient.register_artifact()` | `{"file_path": ..., "source_base64": ...}` | `file_path: str, source_base64: str\|None` | PASS |
| `ContractEngineClient.mark_implemented()` | `{"contract_id": ..., "service_name": ..., "evidence_path": ...}` | `contract_id: str, service_name: str, evidence_path: str` | PASS |

#### Retry Pattern Verification

| Client | Max Retries | Backoff Base | Backoff Type | Safe Default on Failure? |
|---|---|---|---|---|
| `ArchitectClient` | 3 (`_MAX_RETRIES`) | 1s (`_BACKOFF_BASE`) | Exponential (`2^attempt`) | YES -- returns `{}`, `[]`, or `None` depending on method |
| `ContractEngineClient` | 3 (`_MAX_RETRIES`) | 1s (`_BACKOFF_BASE`) | Exponential (`2^attempt`) | YES -- returns `{"error": ...}`, `[]`, or `""` |
| `CodebaseIntelligenceClient` | 3 (configurable) | 1.0s (configurable) | Exponential (`2^attempt`) | YES -- returns `{}` or `[]` via `_parse_result` |

#### Fallback Method Verification (WIRE-009, WIRE-010, WIRE-011)

| Wire ID | Client | Fallback Method | Implementation | Status |
|---|---|---|---|---|
| WIRE-009 | `ContractEngineClient` | `run_api_contract_scan()` | Filesystem scan for `.json`/`.yaml`/`.yml` in `contracts/`, `specs/`, `api/` dirs. Returns `{"fallback": True}` | PASS |
| WIRE-010 | `CodebaseIntelligenceClient` | `generate_codebase_map()` | Filesystem scan for source files by extension. Returns `{"fallback": True}` | PASS |
| WIRE-011 | `ArchitectClient` | `decompose_prd_basic()` | Heuristic single-service stub from PRD text. Returns `{"fallback": True}` | PASS |

All three `*_with_fallback()` wrapper functions are present and follow the pattern: try MCP client -> on failure -> use filesystem fallback.

### 4C.3: MCP Server StdioServerParameters

| Client | Command | Args | Correct Module? |
|---|---|---|---|
| Architect | `python` | `["-m", "src.architect.mcp_server"]` | YES |
| Contract Engine | `python` | `["-m", "src.contract_engine.mcp_server"]` | YES |
| Codebase Intelligence | `python` | `["-m", "src.codebase_intelligence.mcp_server"]` | YES |

---

## 4D: Inter-Service HTTP Calls

### 4D.1: Architect -> Contract Engine

**Location:** `src/architect/mcp_server.py`, function `get_contracts_for_service()` (lines 179-281)

**Call Pattern:**
```python
contract_engine_url = os.environ.get("CONTRACT_ENGINE_URL", "http://localhost:8002")
with httpx.Client(timeout=httpx.Timeout(connect=5.0, read=30.0)) as client:
    resp = client.get(f"{contract_engine_url}/api/contracts/{contract_id}")
```

| Aspect | Value | Assessment |
|---|---|---|
| URL Construction | `{contract_engine_url}/api/contracts/{contract_id}` | CORRECT -- matches `GET /api/contracts/{contract_id}` in Contract Engine |
| Timeout (connect) | 5.0s | Reasonable |
| Timeout (read) | 30.0s | Reasonable |
| Error Handling: HTTPError | Catches `httpx.HTTPError`, logs warning, returns error dict | PASS |
| Error Handling: HTTP 4xx/5xx | Checks `resp.status_code == 200`, returns error dict with HTTP code on failure | PASS |
| Error Handling: Connection Refused | Covered by `httpx.HTTPError` catch | PASS |
| Retry | **NONE** -- no retry on HTTP failures | **WARN** -- individual contract fetches are not retried |
| Fallback URL | `http://localhost:8002` (default if no env var) | Correct for root compose; in Docker build1.yml the env is `http://contract-engine:8000` |

**WIRE-ISSUE-003: No Retry on Inter-Service HTTP Calls (LOW)**

**Severity: LOW**

The `get_contracts_for_service` tool in the Architect MCP server makes direct HTTP calls to the Contract Engine without retry logic. While the MCP client layer (`ArchitectClient._call()`) has retry logic for the full MCP tool call, the individual HTTP requests inside the tool do not retry. If Contract Engine is temporarily overloaded but healthy, individual contract fetches could fail silently.

**Note:** The architecture report documents `CONTRACT_ENGINE_URL` is also used by Codebase Intelligence. However, a full grep of `src/codebase_intelligence/` confirms **no actual HTTP calls to Contract Engine exist** in the codebase intelligence code. The config field exists but is never consumed.

### 4D.2: Complete httpx Usage Map (Build 1 Services)

| File | httpx Usage | Target | Purpose |
|---|---|---|---|
| `src/architect/mcp_server.py` | `httpx.Client` (synchronous) | Contract Engine `/api/contracts/{id}` | Fetch individual contracts for `get_contracts_for_service` tool |

**Only one inter-service HTTP call exists in Build 1.** All other `httpx` usage is in Build 3 (orchestrator), Run 4 (health checks), and integrator modules (boundary testing, data flow tracing).

---

## 4E: Database Initialization Idempotency

### Schema Initializer Analysis

| Initializer | File | Tables Created | All `IF NOT EXISTS`? | Indexes `IF NOT EXISTS`? | Idempotent? |
|---|---|---|---|---|---|
| `init_architect_db(pool)` | `src/shared/db/schema.py` | `service_maps`, `domain_models`, `decomposition_runs` | YES | YES | PASS |
| `init_contracts_db(pool)` | `src/shared/db/schema.py` | `build_cycles`, `contracts`, `contract_versions`, `breaking_changes`, `implementations`, `test_suites`, `shared_schemas`, `schema_consumers` | YES | YES | PASS |
| `init_symbols_db(pool)` | `src/shared/db/schema.py` | `indexed_files`, `symbols`, `dependency_edges`, `import_references`, `graph_snapshots` | YES | YES | PASS |

**Detailed verification:**
- All `CREATE TABLE` statements use `IF NOT EXISTS`
- All `CREATE INDEX` statements use `IF NOT EXISTS`
- No `ALTER TABLE` statements present
- No migration logic present
- Each initializer uses `conn.executescript()` followed by `conn.commit()`
- Running any initializer multiple times will not produce errors or duplicate data

### Database Isolation

| Service | Database Path (from compose) | Tables | Isolated? |
|---|---|---|---|
| Architect | `/data/architect.db` | service_maps, domain_models, decomposition_runs | YES |
| Contract Engine | `/data/contracts.db` | build_cycles, contracts, etc. (8 tables) | YES |
| Codebase Intelligence | `/data/symbols.db` | indexed_files, symbols, etc. (5 tables) | YES |

Each service uses its own SQLite file. No cross-service database access.

**Note:** `DATABASE_URL` (PostgreSQL) is set in Docker Compose environment but the code **only uses SQLite** via `DATABASE_PATH`. The PostgreSQL connection string is unused. See WIRE-ISSUE-004 below.

---

## 4F: ChromaDB Embedding Model Availability

### Dockerfile Pre-Download (Build Time)

**File:** `docker/codebase_intelligence/Dockerfile`, lines 8-10:

```dockerfile
RUN python -c "from chromadb.utils.embedding_functions.onnx_mini_lm_l6_v2 import ONNXMiniLM_L6_V2; ONNXMiniLM_L6_V2().validate()" || \
    python -c "from chromadb.utils.embedding_functions import ONNXMiniLM_L6_V2; ONNXMiniLM_L6_V2()" || true
```

| Aspect | Assessment |
|---|---|
| Pre-download at build time? | YES -- two import attempts with fallback |
| First attempt | `onnx_mini_lm_l6_v2.ONNXMiniLM_L6_V2().validate()` -- newer ChromaDB API path |
| Second attempt | `embedding_functions.ONNXMiniLM_L6_V2()` -- older ChromaDB API path |
| Failure handling | `|| true` -- **build succeeds even if download fails** |
| Cache directory created? | YES -- `mkdir -p /home/appuser/.cache` with ownership set to `appuser` |

**WIRE-ISSUE-005: ChromaDB Model Download Silently Fails (MEDIUM)**

**Severity: MEDIUM**

The `|| true` at the end of the pre-download RUN command means the Docker build will succeed even if the embedding model download fails. If the model isn't pre-downloaded:

1. At runtime, `ChromaStore.__init__()` calls `DefaultEmbeddingFunction()` which triggers a download
2. The `appuser` (non-root) may not have network access or cache permissions
3. The 20s `start_period` in the health check may not be enough for a runtime download
4. There is **no timeout or error handling** around the ChromaDB initialization in `main.py` -- it's a synchronous call in the lifespan

**Runtime initialization path:**
```
main.py lifespan -> ChromaStore(config.chroma_path) -> chromadb.PersistentClient()
                                                     -> DefaultEmbeddingFunction()
                                                     -> get_or_create_collection()
```

The `ChromaStore.__init__()` constructor creates the PersistentClient and DefaultEmbeddingFunction synchronously. If the ONNX model is missing, DefaultEmbeddingFunction will attempt to download it, and there is no explicit timeout wrapper.

### ChromaDB Store Configuration

| Parameter | Value | Source |
|---|---|---|
| Client type | `PersistentClient` | `chroma_store.py` line 31 |
| Embedding function | `DefaultEmbeddingFunction()` (all-MiniLM-L6-v2 ONNX) | `chroma_store.py` line 32 |
| Collection name | `"code_chunks"` | `chroma_store.py` line 28 |
| Distance metric | `cosine` | `chroma_store.py` line 36 |
| Chroma path | `/data/chroma` (from env `CHROMA_PATH`) | `docker-compose` environment |

---

## 4G: Environment Variable Completeness

### Docker Compose -> Config.py Cross-Reference

#### Architect Service

| Env Var (Compose) | Config Field | Used In Code? | Match? |
|---|---|---|---|
| `DATABASE_PATH=/data/architect.db` | `SharedConfig.database_path` (via `DATABASE_PATH`) | YES -- `ConnectionPool(config.database_path)` | PASS |
| `CONTRACT_ENGINE_URL=http://contract-engine:8000` | `ArchitectConfig.contract_engine_url` (via `CONTRACT_ENGINE_URL`) | **PARTIALLY** -- config loads it, but `mcp_server.py` reads it directly via `os.environ.get("CONTRACT_ENGINE_URL")` | WARN |
| `CODEBASE_INTEL_URL=http://codebase-intel:8000` | `ArchitectConfig.codebase_intel_url` (via `CODEBASE_INTEL_URL`) | **NOT USED** -- config loads it but no code in Architect references `config.codebase_intel_url` | WARN |
| `LOG_LEVEL=info` | `SharedConfig.log_level` (via `LOG_LEVEL`) | YES -- `setup_logging(ARCHITECT_SERVICE_NAME, config.log_level)` | PASS |
| `DATABASE_URL=postgresql://...` (build1.yml) | **NOT IN CONFIG** | **NOT USED** -- no PostgreSQL code exists | **FAIL** |
| `REDIS_URL=redis://redis:6379/1` (build1.yml) | **NOT IN CONFIG** | **NOT USED** -- no Redis code exists | **FAIL** |

#### Contract Engine Service

| Env Var (Compose) | Config Field | Used In Code? | Match? |
|---|---|---|---|
| `DATABASE_PATH=/data/contracts.db` | `SharedConfig.database_path` | YES | PASS |
| `LOG_LEVEL=info` | `SharedConfig.log_level` | YES | PASS |
| `DATABASE_URL=postgresql://...` (build1.yml) | **NOT IN CONFIG** | **NOT USED** | **FAIL** |
| `REDIS_URL=redis://redis:6379/0` (build1.yml) | **NOT IN CONFIG** | **NOT USED** | **FAIL** |

#### Codebase Intelligence Service

| Env Var (Compose) | Config Field | Used In Code? | Match? |
|---|---|---|---|
| `DATABASE_PATH=/data/symbols.db` | `SharedConfig.database_path` | YES | PASS |
| `CHROMA_PATH=/data/chroma` | `CodebaseIntelConfig.chroma_path` | YES -- `ChromaStore(config.chroma_path)` | PASS |
| `GRAPH_PATH=/data/graph.json` | `CodebaseIntelConfig.graph_path` | **NOT USED** -- graph is loaded from SQLite (`GraphDB.load_snapshot()`), not from `GRAPH_PATH` | WARN |
| `CONTRACT_ENGINE_URL=http://contract-engine:8000` | `CodebaseIntelConfig.contract_engine_url` | **NOT USED** -- no HTTP calls to Contract Engine in codebase intelligence code | WARN |
| `LOG_LEVEL=info` | `SharedConfig.log_level` | YES | PASS |
| `DATABASE_URL=postgresql://...` (build1.yml) | **NOT IN CONFIG** | **NOT USED** | **FAIL** |
| `REDIS_URL=redis://redis:6379/2` (build1.yml) | **NOT IN CONFIG** | **NOT USED** | **FAIL** |

### **WIRE-ISSUE-004: Unused DATABASE_URL and REDIS_URL Environment Variables (MEDIUM)**

**Severity: MEDIUM**

All three Build 1 services have `DATABASE_URL` (PostgreSQL) and `REDIS_URL` (Redis) set in `docker-compose.build1.yml`, but:
1. The `SharedConfig` base class has no `database_url` or `redis_url` fields
2. All services use SQLite via `DATABASE_PATH` exclusively
3. No PostgreSQL or Redis client code exists in any Build 1 service

These environment variables are dead configuration. They occupy mental space and could mislead developers into thinking PostgreSQL/Redis are used. However, they are harmless because `SharedConfig` has `extra = "ignore"` which silently drops unknown environment variables.

**Note:** The ARCHITECTURE_REPORT.md (Section 1A.2.1) claims `SharedConfig` has `database_url: str = ""` and `redis_url: str = ""` fields. This is **incorrect** -- the actual `config.py` has no such fields. The architecture report is outdated on this point.

### Config Fields Not Set in Docker Compose

| Config Class | Field | Default | Set in Compose? | Risk |
|---|---|---|---|---|
| `ArchitectConfig` | `codebase_intel_url` | `http://codebase-intel:8000` | YES (redundant, default matches) | None |
| `CodebaseIntelConfig` | `graph_path` | `./data/graph.json` | YES (set to `/data/graph.json`) | None (but unused) |
| `CodebaseIntelConfig` | `contract_engine_url` | `http://contract-engine:8000` | YES (redundant, default matches) | None |

---

## 4H: Network Configuration

### Docker Network Topology

```
                  +-----------+
                  | frontend  |  (bridge, defined in build1.yml)
                  +-----------+
                       |
          +------------+------------------+------------------+
          |            |                  |                  |
     [architect]  [contract-engine] [codebase-intel]    [traefik]
          |            |                  |
          +------------+------------------+
                       |
                  +-----------+
                  |  backend  |  (bridge, defined in infra.yml)
                  +-----------+
                       |
              +--------+--------+
              |                 |
         [postgres]         [redis]
```

### Network Membership Verification

| Service | Networks (build1.yml) | Networks (run4.yml override) | Assessment |
|---|---|---|---|
| postgres | backend | -- | PASS |
| redis | backend | -- | PASS |
| contract-engine | frontend, backend | frontend, backend | PASS (redundant but harmless) |
| architect | frontend, backend | frontend, backend | PASS |
| codebase-intel | frontend, backend | frontend, backend (but as `codebase-intelligence` -- **MISMATCH**) | **FAIL** (see WIRE-ISSUE-001) |
| traefik | frontend | -- | PASS |
| auth-service | frontend, backend | -- | PASS |
| order-service | frontend, backend | -- | PASS |
| notification-service | frontend, backend | -- | PASS |

### Service Hostname Resolution

| Service Name (compose) | Hostname in Docker Network | URL Used By Others | Match? |
|---|---|---|---|
| `contract-engine` | `contract-engine` | `http://contract-engine:8000` | PASS |
| `architect` | `architect` | Not called by other services | N/A |
| `codebase-intel` | `codebase-intel` | `http://codebase-intel:8000` (Architect config) | PASS |
| `postgres` | `postgres` | `postgresql://...@postgres:5432/...` | PASS |
| `redis` | `redis` | `redis://redis:6379/...` | PASS |

### Port Mapping Verification

| Service | Internal Port | External Port | Conflicts? |
|---|---|---|---|
| postgres | 5432 | 5432 | No |
| redis | 6379 | 6379 | No |
| architect | 8000 | 8001 | No |
| contract-engine | 8000 | 8002 | No |
| codebase-intel | 8000 | 8003 | No |
| traefik | 80 | 80 | No |
| traefik (dashboard) | 8080 | 8080 | **WARN** -- dashboard port exposed but disabled |
| auth-service | 8080 | dynamic | No |
| order-service | 8080 | dynamic | No |
| notification-service | 8080 | dynamic | No |

**WIRE-ISSUE-006: Traefik Dashboard Port Exposed (LOW)**

**Severity: LOW**

In `docker-compose.traefik.yml` line 26, port `8080:8080` is exposed. The dashboard is disabled (`--api.dashboard=false`), but the port is still mapped. The Traefik API endpoint could still be partially accessible on port 8080.

### Network External References

| Compose File | Network | Type | Reference |
|---|---|---|---|
| `infra.yml` | `backend` | Defined locally (bridge) | Source of truth |
| `build1.yml` | `frontend` | Defined locally (bridge) | Source of truth |
| `build1.yml` | `backend` | `external: true`, name `docker_backend` | References infra.yml's `backend` network by Docker-generated name |
| `traefik.yml` | `frontend` | `external: true` | Must be created by build1.yml first |
| `generated.yml` | `frontend`, `backend` | Both `external: true` | Must be created first |
| `run4.yml` | `frontend`, `backend` | Both `external: true` | Must be created first |

**Note on `docker_backend` naming:** When Docker Compose creates a network from `infra.yml`, the default name depends on the project name. If the project directory is `docker/`, the network would be `docker_backend`. This is fragile -- if the compose project name changes, the external network reference breaks.

---

## 4I: Dockerfile Review

### Architect Dockerfile (`docker/architect/Dockerfile`)

```dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY docker/architect/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY src/shared/ src/shared/
COPY src/architect/ src/architect/
COPY src/__init__.py src/__init__.py
RUN mkdir -p /data && \
    adduser --disabled-password --no-create-home appuser && \
    chown -R appuser:appuser /app /data
USER appuser
EXPOSE 8000
CMD ["uvicorn", "src.architect.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

| Check | Status | Notes |
|---|---|---|
| Base image `python:3.12-slim` | PASS | Correct |
| Requirements installed correctly | PASS | `--no-cache-dir` for smaller image |
| Source code copied correctly | PASS | `src/shared/`, `src/architect/`, `src/__init__.py` |
| CMD uses uvicorn with correct module path | PASS | `src.architect.main:app` |
| Non-root user configured | PASS | `appuser` (no UID specified, auto-assigned) |
| No exposed secrets | PASS | No credentials in Dockerfile |
| `pyproject.toml` copied? | **NO** | Not needed -- uses `requirements.txt` instead |
| Missing: `src/shared/db/` subdirectory | PASS | `COPY src/shared/` copies all subdirs |

### Contract Engine Dockerfile (`docker/contract_engine/Dockerfile`)

| Check | Status | Notes |
|---|---|---|
| Base image `python:3.12-slim` | PASS | |
| Requirements installed correctly | PASS | Includes `openapi-spec-validator`, `prance`, `schemathesis` |
| Source code copied correctly | PASS | `src/shared/`, `src/contract_engine/`, `src/__init__.py` |
| CMD uses uvicorn with correct module path | PASS | `src.contract_engine.main:app` |
| Non-root user configured | PASS | `appuser` |
| No exposed secrets | PASS | |

### Codebase Intelligence Dockerfile (`docker/codebase_intelligence/Dockerfile`)

| Check | Status | Notes |
|---|---|---|
| Base image `python:3.12-slim` | PASS | |
| Requirements installed correctly | PASS | Includes `tree-sitter`, `chromadb`, `scipy` |
| ChromaDB model pre-download | WARN | See WIRE-ISSUE-005 -- `\|\| true` hides failures |
| Source code copied correctly | PASS | `src/shared/`, `src/codebase_intelligence/`, `src/__init__.py` |
| CMD uses uvicorn with correct module path | PASS | `src.codebase_intelligence.main:app` |
| Non-root user configured | PASS | `appuser` with cache directory |
| Cache directory for embedding model | PASS | `mkdir -p /home/appuser/.cache` with correct ownership |
| No exposed secrets | PASS | |

### Cross-Cutting Dockerfile Observations

| Observation | Severity | Details |
|---|---|---|
| No `.dockerignore` referenced | LOW | Build context includes everything; larger builds than necessary |
| No multi-stage builds | INFO | Simple images, not a concern for Build 1 |
| `adduser --no-create-home` + later `mkdir /home/appuser/.cache` | LOW | In codebase-intel Dockerfile, `--no-create-home` but then creates `/home/appuser/` -- this works but `--no-create-home` is misleading |
| Requirements pinned loosely | LOW | Most deps use `>=` instead of `==`; builds may differ over time |

---

## Issues Summary

### Critical Issues

| ID | Issue | Location | Impact |
|---|---|---|---|
| WIRE-ISSUE-001 | Service name mismatch: `codebase-intel` vs `codebase-intelligence` | `docker-compose.build1.yml` (line 96) vs `docker-compose.traefik.yml` (line 42) and `docker-compose.run4.yml` (line 50) | Docker Compose merge will fail or create orphan services. Traefik will not wait for codebase intelligence to be healthy. Run4 overrides will not apply to the codebase intelligence service. |

### Medium Issues

| ID | Issue | Location | Impact |
|---|---|---|---|
| WIRE-ISSUE-004 | `DATABASE_URL` and `REDIS_URL` set in compose but not used by code | `docker/docker-compose.build1.yml` | Dead configuration. Services use SQLite only. Misleading to developers. ARCHITECTURE_REPORT.md incorrectly claims these fields exist in config.py. |
| WIRE-ISSUE-005 | ChromaDB model pre-download silently fails (`\|\| true`) | `docker/codebase_intelligence/Dockerfile` line 10 | If model download fails at build time, runtime initialization will attempt download, potentially causing startup timeout or failure. |
| SVC-005 | `mark_implemented` returns `"total"` instead of `"total_implementations"` | `src/contract_engine/mcp_server.py` line 274 | MCP consumers expecting `total_implementations` key will get `KeyError`. Previously documented in ARCHITECTURE_REPORT.md, still open. |

### Low Issues

| ID | Issue | Location | Impact |
|---|---|---|---|
| WIRE-ISSUE-002 | MCP server names contain spaces ("Contract Engine", "Codebase Intelligence") | `src/contract_engine/mcp_server.py` line 43, `src/codebase_intelligence/mcp_server.py` line 136 | May cause issues with string-based tool name resolution in some MCP clients. |
| WIRE-ISSUE-003 | No retry on inter-service HTTP calls within MCP tool | `src/architect/mcp_server.py` lines 224-271 | Individual contract fetches from Contract Engine are not retried. The outer MCP call has retries, but HTTP failures within the tool execution are not retried. |
| WIRE-ISSUE-006 | Traefik dashboard port 8080 exposed despite dashboard being disabled | `docker/docker-compose.traefik.yml` line 26 | Unnecessary port exposure. Minor security concern. |
| WIRE-ISSUE-007 | Unused environment variables: `CODEBASE_INTEL_URL` (architect), `CONTRACT_ENGINE_URL` (codebase-intel), `GRAPH_PATH` (codebase-intel) | Various compose files and config.py | Config loads these values but no code consumes them. Dead configuration. |
| WIRE-ISSUE-008 | `CONTRACT_ENGINE_URL` read via `os.environ.get()` in mcp_server.py instead of using `config.contract_engine_url` | `src/architect/mcp_server.py` line 219 | Bypasses the Pydantic config system. Default fallback is `http://localhost:8002` which differs from config default `http://contract-engine:8000`. |

### Informational

| ID | Note | Location |
|---|---|---|
| INFO-001 | Architecture report incorrectly states SharedConfig has `database_url` and `redis_url` fields | `ARCHITECTURE_REPORT.md` Section 1A.2.1 vs actual `src/shared/config.py` |
| INFO-002 | Generated services use `curl` for health checks -- requires curl in their Docker images | `docker/docker-compose.generated.yml` |
| INFO-003 | No `.dockerignore` files found -- larger build contexts than necessary | `docker/` directory |
| INFO-004 | `docker_backend` external network name is project-name-dependent and fragile | `docker/docker-compose.build1.yml` line 152 |
| INFO-005 | PostgreSQL infra.yml creates only `superteam` database. Architecture report mentions `POSTGRES_MULTIPLE_DATABASES` for `auth_db`, `order_db`, `notification_db` but no init script exists | `docker/docker-compose.infra.yml` |

---

*End of Wiring Verification Report.*

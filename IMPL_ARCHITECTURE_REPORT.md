# IMPL_ARCHITECTURE_REPORT.md -- Graph RAG Implementation Architecture

> **Generated:** 2026-02-23
> **Agent:** Discovery Agent (Code Reviewer)
> **Purpose:** Single source of truth for Week 9 implementation agents
> **Source Files Verified:** All paths and signatures verified against actual source code

---

## Section 1A: New File Locations

### Existing Package Structure

```
C:\MY_PROJECTS\super-team\
  src\
    __init__.py (absent -- no top-level package marker)
    shared\
      __init__.py
      constants.py
      db\
        __init__.py
        connection.py         # ConnectionPool class
        schema.py             # init_symbols_db, init_architect_db, init_contracts_db
      models\
        __init__.py           # Re-exports all model classes
        architect.py          # ServiceDefinition, DomainEntity, etc.
        codebase.py           # SymbolDefinition, Language, etc.
        common.py             # BuildCycle, ArtifactRegistration, HealthStatus
        contracts.py          # ContractEntry, ContractCreate, etc.
    codebase_intelligence\
      __init__.py
      mcp_server.py           # FastMCP("Codebase Intelligence"), 8 tools
      mcp_client.py           # Fallback client (WIRE-010)
      main.py                 # FastAPI app
      config.py
      storage\
        __init__.py
        chroma_store.py       # ChromaStore class
        graph_db.py           # GraphDB class
        symbol_db.py          # SymbolDB class
      services\
        __init__.py
        (9 service modules)
      routers\
        __init__.py
        (6 router modules)
      parsers\
        __init__.py
        (4 language parsers)
    architect\
      mcp_server.py           # FastMCP("Architect"), 4 tools
      (services/)
    contract_engine\
      mcp_server.py           # FastMCP("Contract Engine"), 10 tools
      (services/)
    super_orchestrator\
      config.py               # SuperOrchestratorConfig dataclass
      pipeline.py             # Main orchestration engine
      state.py                # PipelineState dataclass
      state_machine.py        # transitions-based AsyncMachine
      cost.py                 # PipelineCostTracker
      (others)
    quality_gate\
      gate_engine.py          # QualityGateEngine (4-layer)
      adversarial_patterns.py # AdversarialScanner
      layer4_adversarial.py   # Layer4Scanner wraps AdversarialScanner
      (others)
    run4\
      fix_pass.py             # classify_priority, execute_fix_pass
      builder.py              # write_fix_instructions, feed_violations_to_builder
      (others)
    graph_rag\                # DOES NOT EXIST YET -- must be created
```

### `src/graph_rag/` Does Not Exist

Confirmed: `C:\MY_PROJECTS\super-team\src\graph_rag\` does not exist. All 8 source files must be created from scratch.

### New Files to Create (Exact Paths)

**Source files (8):**
```
C:\MY_PROJECTS\super-team\src\graph_rag\__init__.py
C:\MY_PROJECTS\super-team\src\graph_rag\mcp_server.py
C:\MY_PROJECTS\super-team\src\graph_rag\knowledge_graph.py
C:\MY_PROJECTS\super-team\src\graph_rag\graph_rag_store.py
C:\MY_PROJECTS\super-team\src\graph_rag\graph_rag_indexer.py
C:\MY_PROJECTS\super-team\src\graph_rag\graph_rag_engine.py
C:\MY_PROJECTS\super-team\src\graph_rag\context_assembler.py
C:\MY_PROJECTS\super-team\src\graph_rag\mcp_client.py
```

**Shared model file (1):**
```
C:\MY_PROJECTS\super-team\src\shared\models\graph_rag.py
```

**Test files (8):**
```
C:\MY_PROJECTS\super-team\tests\test_knowledge_graph.py
C:\MY_PROJECTS\super-team\tests\test_graph_rag_store.py
C:\MY_PROJECTS\super-team\tests\test_graph_rag_engine.py
C:\MY_PROJECTS\super-team\tests\test_graph_rag_indexer.py
C:\MY_PROJECTS\super-team\tests\test_context_assembler.py
C:\MY_PROJECTS\super-team\tests\test_mcp_server.py        (NOTE: may conflict -- see Section 1F)
C:\MY_PROJECTS\super-team\tests\test_graph_rag_integration.py
C:\MY_PROJECTS\super-team\tests\test_graph_properties.py
```

### Existing `shared/models/` File Patterns

**File:** `C:\MY_PROJECTS\super-team\src\shared\models\__init__.py`

All models use this import pattern:
```python
from src.shared.models.architect import (ServiceDefinition, ...)
from src.shared.models.contracts import (ContractEntry, ...)
from src.shared.models.codebase import (SymbolDefinition, ...)
from src.shared.models.common import (BuildCycle, ...)
```

The `__init__.py` has an `__all__` list that re-exports every model class. The new `graph_rag.py` models must be added here following the same pattern.

Model classes use `pydantic.BaseModel` in some cases (e.g., `SemanticSearchResult` has `.model_dump(mode="json")`), and plain `@dataclass` in others. The Graph RAG design specifies plain `@dataclass` for all new models.

### `schema.py` -- All `init_*` Functions

**File:** `C:\MY_PROJECTS\super-team\src\shared\db\schema.py`

| Function | Line | Signature | Creates Tables |
|----------|------|-----------|----------------|
| `init_architect_db` | 7 | `init_architect_db(pool: ConnectionPool) -> None` | `service_maps`, `domain_models`, `decomposition_runs` |
| `init_contracts_db` | 46 | `init_contracts_db(pool: ConnectionPool) -> None` | `build_cycles`, `contracts`, `contract_versions`, `breaking_changes`, `implementations`, `test_suites`, `shared_schemas`, `schema_consumers` |
| `init_symbols_db` | 157 | `init_symbols_db(pool: ConnectionPool) -> None` | `indexed_files`, `symbols`, `dependency_edges`, `import_references`, `graph_snapshots` |

**New function to add:** `init_graph_rag_db(pool: ConnectionPool) -> None` creating `graph_rag_snapshots` table.

**`__init__.py` must also be updated:**
```
C:\MY_PROJECTS\super-team\src\shared\db\__init__.py
```
Currently exports: `ConnectionPool`, `init_architect_db`, `init_contracts_db`, `init_symbols_db`.
Must add: `init_graph_rag_db`.

---

## Section 1B: Existing Codebase Intelligence Module

### ChromaDB Initialization Pattern

**File:** `C:\MY_PROJECTS\super-team\src\codebase_intelligence\storage\chroma_store.py`

```python
# Line 30-37
class ChromaStore:
    _COLLECTION_NAME = "code_chunks"

    def __init__(self, chroma_path: str) -> None:
        self._client = chromadb.PersistentClient(path=chroma_path)
        self._embedding_fn = DefaultEmbeddingFunction()
        self._collection = self._client.get_or_create_collection(
            name=self._COLLECTION_NAME,
            embedding_function=self._embedding_fn,
            metadata={"hnsw:space": "cosine"},
        )
```

**Critical details:**
- Client type: `chromadb.PersistentClient(path=chroma_path)` -- path is a string
- Embedding function: `DefaultEmbeddingFunction()` (module-level import from `chromadb.utils.embedding_functions`)
- Distance metric: `metadata={"hnsw:space": "cosine"}` -- uses legacy `metadata` style, NOT `configuration` dict
- The `GraphRAGStore` must follow this exact pattern

### `ChromaStore.__init__()` Exact Signature

```python
def __init__(self, chroma_path: str) -> None:
```
Takes a single `str` parameter. No `Path` type.

### `DefaultEmbeddingFunction` Import and Instantiation

```python
# Line 8
from chromadb.utils.embedding_functions import DefaultEmbeddingFunction

# Line 32 (inside __init__)
self._embedding_fn = DefaultEmbeddingFunction()
```
No arguments to constructor. This internally uses `all-MiniLM-L6-v2` (384 dimensions).

### `graph_db` Save/Load Snapshot Signatures

**File:** `C:\MY_PROJECTS\super-team\src\codebase_intelligence\storage\graph_db.py`

```python
# Line 69
def save_snapshot(self, graph: nx.DiGraph) -> None:
    data = nx.node_link_data(graph, edges="edges")
    graph_json = json.dumps(data)
    # INSERT INTO graph_snapshots (graph_json, node_count, edge_count, created_at) VALUES (?, ?, ?, datetime('now'))

# Line 95
def load_snapshot(self) -> nx.DiGraph | None:
    # SELECT graph_json FROM graph_snapshots ORDER BY id DESC LIMIT 1
    data = json.loads(row["graph_json"])
    graph: nx.DiGraph = nx.node_link_graph(data, edges="edges")
    return graph
```

**CRITICAL:** The existing code uses `edges="edges"` in both `node_link_data` and `node_link_graph`. The Graph RAG snapshot must use the same keyword. The column name is `graph_json` (not `snapshot_data` as stated in CODEBASE_EXPLORATION.md).

### `ConnectionPool` Definition

**File:** `C:\MY_PROJECTS\super-team\src\shared\db\connection.py`

```python
# Line 11-22
class ConnectionPool:
    def __init__(self, db_path: str | Path, timeout: float = 30.0) -> None:
```

**Import path:** `from src.shared.db.connection import ConnectionPool`
**Also available via:** `from src.shared.db import ConnectionPool` (through `__init__.py`)

**Parameters:** `db_path: str | Path` (accepts both), `timeout: float = 30.0`
**Key method:** `.get() -> sqlite3.Connection` (thread-local, creates on first call)
**Cleanup:** `.close() -> None`
**Property:** `.db_path -> Path`

### MCP Server Pattern

**File:** `C:\MY_PROJECTS\super-team\src\codebase_intelligence\mcp_server.py`

```python
# Line 27
from mcp.server.fastmcp import FastMCP

# Line 136
mcp = FastMCP("Codebase Intelligence")

# Tool decorator pattern:
@mcp.tool(name="register_artifact")
def index_file(file_path: str, ...) -> dict[str, Any]:
    ...

@mcp.tool()  # name defaults to function name
def analyze_graph() -> dict[str, Any]:
    ...

# Line 509-510
if __name__ == "__main__":
    mcp.run()
```

**Module-level initialization pattern (lines 62-94):**
1. Read env vars for paths
2. Create `ConnectionPool`
3. Call `init_*_db(pool)`
4. Instantiate service objects
5. Load existing state (e.g., graph snapshot)

### All `shared/` Imports Used in CI MCP Server

```python
from src.shared.db.connection import ConnectionPool
from src.shared.db.schema import init_symbols_db
from src.shared.models.codebase import (DeadCodeEntry, Language, SymbolDefinition, SymbolKind)
```

---

## Section 1C: Build 3 Pipeline Modification Points

### `contracts_registered` Transition Handler

**File:** `C:\MY_PROJECTS\super-team\src\super_orchestrator\pipeline.py`

There are TWO functions that handle the `contracts_registered` transition:

1. **`_phase_contracts`** (line 1924):
   ```python
   async def _phase_contracts(
       state: PipelineState,
       config: SuperOrchestratorConfig,
       cost_tracker: PipelineCostTracker,
       shutdown: GracefulShutdown,
       model: PipelineModel,
   ) -> None:
   ```
   - Line 1933: `await run_contract_registration(state, config, cost_tracker, shutdown)`
   - Line 1935: `await model.contracts_registered()`

2. **`_phase_builders`** (line 1940):
   ```python
   async def _phase_builders(
       state: PipelineState,
       config: SuperOrchestratorConfig,
       cost_tracker: PipelineCostTracker,
       shutdown: GracefulShutdown,
       model: PipelineModel,
   ) -> None:
   ```
   - Line 1948: `await run_contract_registration(state, config, cost_tracker, shutdown)`
   - Line 1950: `await model.contracts_registered()`

**The `_build_graph_rag_context()` call should be inserted AFTER `await run_contract_registration(...)` and BEFORE `await model.contracts_registered()` in both functions.**

### Builder Subprocess Config JSON

**File:** `C:\MY_PROJECTS\super-team\src\super_orchestrator\pipeline.py`

**`generate_builder_config` function (line 187):**
```python
def generate_builder_config(
    service_info: ServiceInfo,
    config: SuperOrchestratorConfig,
    state: PipelineState,
) -> tuple[dict[str, Any], Path]:
```

**Config dict keys (lines 218-228):**
```python
config_dict: dict[str, Any] = {
    "depth": config.builder.depth,
    "milestone": f"build-{service_info.service_id}",
    "e2e_testing": True,
    "post_orchestration_scans": True,
    "service_id": service_info.service_id,
    "domain": service_info.domain,
    "stack": service_info.stack,
    "port": service_info.port,
    "output_dir": str(output_dir),
}
```

**Where to add `graph_rag_context`:** Add a new key after line 228:
```python
"graph_rag_context": state.phase_artifacts.get("graph_rag_contexts", {}).get(service_info.service_id, ""),
```

**Where config is written (line 726-727):**
```python
config_file = output_dir / "builder_config.json"
atomic_write_json(config_file, builder_config)
```

### `_build_graph_rag_context()` Insertion Point

New method to add to `pipeline.py`. Should be an `async def` matching the pattern of other helper functions. Insert before `_phase_contracts` (around line 1920).

### Lazy Import Pattern for MCP Connections

**File:** `C:\MY_PROJECTS\agent-team-v15\src\agent_team_v15\mcp_clients.py`

```python
# Line 63-64 (inside create_contract_engine_session)
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

# Line 81 (StdioServerParameters usage)
server_params = StdioServerParameters(
    command=config.mcp_command,
    args=config.mcp_args,
    env=env,
)

# Line 91-92 (session creation)
async with stdio_client(server_params) as (read_stream, write_stream):
    async with ClientSession(read_stream, write_stream) as session:
        await asyncio.wait_for(session.initialize(), timeout=startup_timeout)
        yield session
```

**Environment variable filtering pattern (line 74-79):**
```python
env = {"PATH": os.environ.get("PATH", "")}
if db_path:
    env["DATABASE_PATH"] = db_path
```
Only passes specific env vars -- never spreads `os.environ`.

### `PipelineState.phase_artifacts` Type

**File:** `C:\MY_PROJECTS\super-team\src\super_orchestrator\state.py`, line 28

```python
phase_artifacts: dict[str, Any] = field(default_factory=dict)
```

This is an untyped dict. No schema change needed -- just store `"graph_rag_contexts"` and `"graph_rag_client"` as keys.

### `SuperOrchestratorConfig` Dataclass

**File:** `C:\MY_PROJECTS\super-team\src\super_orchestrator\config.py`

```python
# Lines 54-68
@dataclass
class SuperOrchestratorConfig:
    architect: ArchitectConfig = field(default_factory=ArchitectConfig)
    builder: BuilderConfig = field(default_factory=BuilderConfig)
    integration: IntegrationConfig = field(default_factory=IntegrationConfig)
    quality_gate: QualityGateConfig = field(default_factory=QualityGateConfig)
    budget_limit: float | None = None
    depth: str = "standard"
    phase_timeouts: dict[str, int] = field(default_factory=dict)
    build1_services_dir: str = ""
    agent_team_config_path: str = ""
    mode: str = "auto"
    output_dir: str = ".super-orchestrator"
```

**Existing nested config pattern:** Each sub-config is a separate `@dataclass` defined above `SuperOrchestratorConfig`. Add `GraphRAGConfig` before line 54, then add `graph_rag: GraphRAGConfig = field(default_factory=GraphRAGConfig)` as a new field.

### `load_super_config()` Missing Key Handling

**File:** `C:\MY_PROJECTS\super-team\src\super_orchestrator\config.py`, line 71

```python
def load_super_config(path: Path | str | None = None) -> SuperOrchestratorConfig:
```

**YAML key lookup pattern (lines 99-107):**
```python
architect_raw = raw.get("architect", {})
builder_raw = raw.get("builder", {})
integration_raw = raw.get("integration", {})
quality_gate_raw = raw.get("quality_gate", {})
```

**Missing keys return empty dict** (via `.get(..., {})`), which means all fields get defaults. Must add:
```python
graph_rag_raw = raw.get("graph_rag", {})
```

**The `_pick` helper (line 94-97)** filters to only keys accepted by the dataclass:
```python
def _pick(data: dict[str, Any], cls: type) -> dict[str, Any]:
    valid = {f.name for f in cls.__dataclass_fields__.values()}
    return {k: v for k, v in data.items() if k in valid}
```

**Also update the `for key in (...)` exclusion (line 106) to include `"graph_rag"`**, and add `graph_rag=GraphRAGConfig(**_pick(graph_rag_raw, GraphRAGConfig))` to the `SuperOrchestratorConfig(...)` constructor call on line 109.

### `AdversarialScanner.__init__()` Exact Signature

**File:** `C:\MY_PROJECTS\super-team\src\quality_gate\adversarial_patterns.py`, line 111

```python
class AdversarialScanner:
```

**There is NO explicit `__init__` method.** The class uses Python's default `__init__()` (no parameters beyond `self`). To add `graph_rag_client`, add:

```python
def __init__(self, graph_rag_client: Any = None) -> None:
    self._graph_rag_client = graph_rag_client
```

### `detect_dead_events()` and `detect_dead_contracts()` Insertion Points

**ADV-001 handler:** `_check_dead_event_handlers` method, line 181.
- The cross-service check should be added at line 230, BEFORE appending the violation.
- Check: `if self._graph_rag_client: result = await self._graph_rag_client.check_cross_service_events(); if event has publisher, skip flagging`.

**ADV-002 handler:** `_check_dead_contracts` method, line 251.
- The cross-service check should be added at line 284, BEFORE appending the violation.

**IMPORTANT:** The `scan` method (line 123) is `async def scan(self, target_dir: Path)`. The individual check methods `_check_dead_event_handlers` and `_check_dead_contracts` are currently synchronous (no `async` keyword). If Graph RAG calls are async, these methods must be converted to `async def` or the calls must be wrapped with `asyncio.run_coroutine_threadsafe` or similar.

### `gate_engine.py` AdversarialScanner Instantiation

**File:** `C:\MY_PROJECTS\super-team\src\quality_gate\gate_engine.py`

The `AdversarialScanner` is NOT directly instantiated in `gate_engine.py`. Instead:

1. `gate_engine.py` line 62: `self._layer4 = Layer4Scanner()`
2. `Layer4Scanner.__init__` (in `layer4_adversarial.py` line 45-46): `self._scanner = AdversarialScanner()`

**To pass `graph_rag_client`**, the chain is:
1. `QualityGateEngine.__init__` receives `graph_rag_client`
2. Passes to `Layer4Scanner(graph_rag_client=graph_rag_client)`
3. `Layer4Scanner` passes to `AdversarialScanner(graph_rag_client=graph_rag_client)`

**OR** (simpler): modify `AdversarialScanner` to accept `graph_rag_client` after construction (setter method), and have `gate_engine.py` set it before calling `run_all_layers()`.

### `classify_priority()` Exact Signature and Return Type

**File:** `C:\MY_PROJECTS\super-team\src\run4\fix_pass.py`, line 153

```python
def classify_priority(violation: dict[str, Any]) -> str:
```
Returns: `"P0"`, `"P1"`, `"P2"`, or `"P3"` (string).

**To add Graph RAG:** Add optional `graph_rag_client` parameter:
```python
def classify_priority(violation: dict[str, Any], *, graph_rag_client: Any = None) -> str:
```

### `write_fix_instructions()` Exact Signature

**File:** `C:\MY_PROJECTS\super-team\src\run4\builder.py`, line 310

```python
def write_fix_instructions(
    cwd: Path,
    violations: list[dict[str, Any]],
    priority_order: list[str] | None = None,
) -> Path:
```
Returns: `Path` to the written `FIX_INSTRUCTIONS.md`.

**To add Graph RAG:** Add optional `graph_rag_context` parameter:
```python
def write_fix_instructions(
    cwd: Path,
    violations: list[dict[str, Any]],
    priority_order: list[str] | None = None,
    *,
    graph_rag_context: str = "",
) -> Path:
```

---

## Section 1D: NetworkX and ChromaDB Versions

### Exact Installed Versions (from `pyproject.toml`)

**File:** `C:\MY_PROJECTS\super-team\pyproject.toml`

| Package | Pinned Version | Line |
|---------|---------------|------|
| `networkx` | `==3.6.1` | 23 |
| `chromadb` | `==1.5.0` | 22 |
| `mcp` | `>=1.25,<2` | 24 |
| `pydantic` | `>=2.5.0` | 13 |
| `pyyaml` | `>=6.0` | 28 |

**NetworkX is pinned as `networkx==3.6.1`** (not `networkx[default]`). The `[default]` extra is not used.

**Runtime verification:**
- `networkx.__version__` = `3.6.1`
- `chromadb.__version__` = `1.5.0`

### `louvain_communities` Import Path

Verified available:
```python
from networkx.algorithms.community import louvain_communities
# OR equivalently:
import networkx as nx
nx.community.louvain_communities(G, seed=42)
```

Both work with `networkx==3.6.1`.

### `sentence-transformers` Availability

**NOT directly installed** as a top-level dependency. However, `chromadb==1.5.0` pulls it in as a transitive dependency for `DefaultEmbeddingFunction()`. When tested:

```
chromadb 1.5.0 -- available
DefaultEmbeddingFunction() -- available
sentence_transformers -- ModuleNotFoundError
```

**This means `sentence_transformers` may not be importable directly.** However, `DefaultEmbeddingFunction()` works because ChromaDB bundles or lazily imports it internally. The design correctly specifies using `DefaultEmbeddingFunction()` and never importing `sentence_transformers` directly.

### `node_link_data` / `node_link_graph` Keyword Arguments

For `networkx==3.6.1`, the `edges` keyword is **required** (using `link` triggers a `FutureWarning`). The existing codebase already uses `edges="edges"`:

```python
nx.node_link_data(graph, edges="edges")
nx.node_link_graph(data, edges="edges")
```

---

## Section 1E: Existing Tests

### Test Runner Command

```bash
python -m pytest tests/
```

Or via pyproject.toml configuration:
```
[tool.pytest.ini_options]
testpaths = ["tests"]
asyncio_mode = "auto"
pythonpath = ["."]
```

### File Naming Convention

All test files follow: `test_*.py`
Test directories: `tests/test_shared/`, `tests/test_architect/`, `tests/test_codebase_intelligence/`, `tests/test_contract_engine/`, `tests/test_integration/`, `tests/test_mcp/`, `tests/build3/`, `tests/run4/`, `tests/benchmarks/`, `tests/e2e/`

### `pytest-asyncio` Usage and Async Test Pattern

```toml
asyncio_mode = "auto"
```

This means async test functions are automatically detected -- no `@pytest.mark.asyncio` decorator needed. Simply write:

```python
async def test_something():
    result = await some_async_function()
    assert result == expected
```

### `tmp_path` vs `tempfile` Usage

**Primary pattern: `tmp_path` fixture** (pytest built-in):

```python
# From conftest.py line 66-68
@pytest.fixture
def tmp_db_path(tmp_path: Path) -> Path:
    return tmp_path / "test.db"

@pytest.fixture
def connection_pool(tmp_db_path: Path) -> Generator[ConnectionPool, None, None]:
    pool = ConnectionPool(tmp_db_path)
    yield pool
    pool.close()
```

`tempfile` is also imported in conftest.py but `tmp_path` is the preferred pattern.

### MCP Session Mock Examples

No MCP session mocks were found in the root `conftest.py`. MCP tests typically use direct function calls rather than full stdio transport. See `tests/test_mcp/` for MCP-specific test patterns.

### `conftest.py` Structure and Shared Fixtures

**Root conftest:** `C:\MY_PROJECTS\super-team\tests\conftest.py`

Key fixtures available to all tests:
- `tmp_db_path(tmp_path)` -- temporary database path
- `connection_pool(tmp_db_path)` -- ConnectionPool with cleanup
- `sample_service_stack()` -- ServiceStack fixture
- `sample_service_definition(sample_service_stack)` -- ServiceDefinition fixture
- `sample_entity_field()` -- EntityField fixture
- `sample_state_machine()` -- StateMachine fixture
- `sample_domain_entity(sample_entity_field, sample_state_machine)` -- DomainEntity fixture
- `sample_domain_relationship()` -- DomainRelationship fixture
- `sample_contract_entry()` -- ContractEntry fixture
- `sample_symbol_definition()` -- SymbolDefinition fixture
- `sample_health_status()` -- HealthStatus fixture
- `mock_env_vars(monkeypatch)` -- sets mock environment variables

**Sub-conftest files:**
- `tests/build3/conftest.py` -- Build 3 specific fixtures (includes PipelineCostTracker shims)
- `tests/run4/conftest.py` -- Run 4 specific fixtures
- `tests/benchmarks/conftest.py` -- Benchmark fixtures
- `tests/e2e/api/conftest.py` -- E2E API fixtures

### Current Test Count

**2410 tests collected** (as of 2026-02-23).

---

## Section 1F: Discrepancies Between GRAPH_RAG_DESIGN.md and Actual Codebase

### DISCREPANCY 1: `dependency_edges` Table Column Names

**GRAPH_RAG_DESIGN.md (Section 5.2, lines 553-555) states:**
> Read all dependency_edges from SQL: SELECT source_file, target_file, relation, line, imported_names, source_symbol, target_symbol FROM dependency_edges

**CODEBASE_EXPLORATION.md (Section 1A.6) states columns as:**
> `source_file`, `target_file`, `relation`, `line`, `imported_names`, `source_symbol`, `target_symbol`

**Actual `schema.py` (line 199-209):**
```sql
CREATE TABLE IF NOT EXISTS dependency_edges (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_symbol_id TEXT NOT NULL,
    target_symbol_id TEXT NOT NULL,
    relation TEXT NOT NULL,
    source_file TEXT NOT NULL,
    target_file TEXT NOT NULL,
    line INTEGER,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(source_symbol_id, target_symbol_id, relation)
);
```

**CORRECT ANSWER:** The column names are `source_symbol_id` and `target_symbol_id`, NOT `source_symbol` and `target_symbol`. There is NO `imported_names` column in the `dependency_edges` table. The `imported_names` column exists only in the `import_references` table.

**Impact:** The `GraphRAGIndexer._load_existing_data()` SQL query must use:
```sql
SELECT source_symbol_id, target_symbol_id, relation, source_file, target_file, line
FROM dependency_edges
```

### DISCREPANCY 2: `dependency_edges` Primary Key Structure

**CODEBASE_EXPLORATION.md states composite PK:**
> `PRIMARY KEY (source_file, target_file, relation, source_symbol, target_symbol)`

**Actual schema:** Has `id INTEGER PRIMARY KEY AUTOINCREMENT` with a `UNIQUE(source_symbol_id, target_symbol_id, relation)` constraint. This is an auto-increment integer PK, not a composite PK.

### DISCREPANCY 3: `graph_snapshots` Column Name

**CODEBASE_EXPLORATION.md states:**
> `snapshot_data TEXT NOT NULL` -- JSON: nx.node_link_data(graph, edges="edges")

**Actual schema (line 230-236):**
```sql
CREATE TABLE IF NOT EXISTS graph_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    graph_json TEXT NOT NULL,
    node_count INTEGER NOT NULL DEFAULT 0,
    edge_count INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
```

**CORRECT ANSWER:** Column is `graph_json`, NOT `snapshot_data`. The `GraphDB.load_snapshot()` uses `row["graph_json"]` (line 110).

### DISCREPANCY 4: `symbols` Table Column Names vs Exploration Doc

**CODEBASE_EXPLORATION.md lists `content_hash`** in indexed_files, but actual schema uses `file_hash`.

**CODEBASE_EXPLORATION.md lists `last_indexed`** but actual schema uses `indexed_at`.

**CODEBASE_EXPLORATION.md lists `is_exported INTEGER DEFAULT 1`** but actual is `is_exported INTEGER NOT NULL DEFAULT 1`.

These are minor but the implementer should rely on the actual schema.py, not the exploration doc.

### DISCREPANCY 5: `AdversarialScanner` Has No `__init__`

**GRAPH_RAG_DESIGN.md (Section 8.3) states:**
> Add optional `graph_rag_client` parameter to `AdversarialScanner.__init__()`

**Actual code:** `AdversarialScanner` has NO explicit `__init__` method. An `__init__` must be ADDED to accept the parameter.

### DISCREPANCY 6: `QualityGateEngine` Does Not Directly Use `AdversarialScanner`

**GRAPH_RAG_DESIGN.md (Section 8.3, GATE-3 fix) states:**
> When `gate_engine.py` instantiates `AdversarialScanner`, it reads from `phase_artifacts`

**Actual code:** `gate_engine.py` does NOT instantiate `AdversarialScanner` directly. It instantiates `Layer4Scanner()` (line 62), which internally creates `AdversarialScanner()` (in `layer4_adversarial.py` line 46).

**CORRECT ANSWER:** The `graph_rag_client` must be passed through the chain:
1. `QualityGateEngine.__init__()` or `run_all_layers()` receives it
2. Passes to `Layer4Scanner`
3. `Layer4Scanner` passes to `AdversarialScanner`

Both `layer4_adversarial.py` and `gate_engine.py` must be modified.

### DISCREPANCY 7: `_check_dead_event_handlers` Is Synchronous

**GRAPH_RAG_DESIGN.md assumes** the Graph RAG client can be called within the scanner methods.

**Actual code:** `_check_dead_event_handlers` and `_check_dead_contracts` are synchronous methods (no `async` keyword), even though the top-level `scan()` is `async`. If Graph RAG calls are async, these private methods must either:
1. Be converted to `async def` and called with `await` from `scan()`
2. Or the graph_rag_client must provide synchronous wrappers

Currently `scan()` calls them as: `violations.extend(self._check_dead_event_handlers(target_dir))` -- synchronous.

### DISCREPANCY 8: `service_map_store` Data Column Name

**GRAPH_RAG_DESIGN.md (CODEBASE_EXPLORATION.md Section 1B.9) states:**
> `data TEXT NOT NULL` -- JSON: ServiceMap serialized

**Actual schema (line 11-18):**
```sql
CREATE TABLE IF NOT EXISTS service_maps (
    id TEXT PRIMARY KEY,
    project_name TEXT NOT NULL,
    prd_hash TEXT NOT NULL,
    map_json TEXT NOT NULL,
    build_cycle_id TEXT,
    generated_at TEXT NOT NULL DEFAULT (datetime('now'))
);
```

**CORRECT ANSWER:** Column is `map_json`, NOT `data`. Similarly, domain_models uses `model_json`, NOT `data`.

### DISCREPANCY 9: Test File Name Collision Risk

**GRAPH_RAG_DESIGN.md specifies:** `tests/test_mcp_server.py`

**Existing test directory:** `tests/test_mcp/` already contains MCP tests (`test_architect_mcp.py`, `test_codebase_intel_mcp.py`, `test_contract_engine_mcp.py`).

**Recommendation:** Name the file `tests/test_graph_rag_mcp_server.py` to avoid ambiguity.

### DISCREPANCY 10: `contracts` Table `spec` Column Name

**CODEBASE_EXPLORATION.md states:** `spec TEXT NOT NULL` -- JSON blob of the full spec

**Actual schema (line 68):** `spec_json TEXT NOT NULL`

**CORRECT ANSWER:** Column is `spec_json`, NOT `spec`. The indexer's SQL for reading contract specs must use `spec_json`.

### DISCREPANCY 11: CI Database Default Path

**GRAPH_RAG_DESIGN.md states default:** `./data/codebase_intel.db`

**Actual CI MCP server (line 62):** `os.environ.get("DATABASE_PATH", "./data/symbols.db")`

**CORRECT ANSWER:** The CI database default path is `./data/symbols.db`, NOT `./data/codebase_intel.db`. The `CI_DATABASE_PATH` env var default should be `./data/symbols.db`.

### Summary of Discrepancies

| # | Location | Design Says | Actual Code | Severity |
|---|----------|------------|-------------|----------|
| 1 | dependency_edges columns | `source_symbol`, `target_symbol` | `source_symbol_id`, `target_symbol_id` | **CRITICAL** -- wrong SQL will fail |
| 2 | dependency_edges PK | composite PK | auto-increment + UNIQUE constraint | Minor |
| 3 | graph_snapshots column | `snapshot_data` | `graph_json` | **CRITICAL** -- wrong SQL will fail |
| 4 | indexed_files columns | `content_hash`, `last_indexed` | `file_hash`, `indexed_at` | Minor |
| 5 | AdversarialScanner | Has `__init__` | No explicit `__init__` | Important -- must ADD it |
| 6 | gate_engine.py | Instantiates AdversarialScanner | Instantiates Layer4Scanner | Important -- different plumbing needed |
| 7 | Scanner methods | Async-compatible | Synchronous private methods | Important -- design decision needed |
| 8 | service_maps column | `data` | `map_json` | **CRITICAL** -- wrong SQL will fail |
| 9 | Test file name | `test_mcp_server.py` | Potential collision | Minor -- rename recommended |
| 10 | contracts column | `spec` | `spec_json` | **CRITICAL** -- wrong SQL will fail |
| 11 | CI DB default path | `./data/codebase_intel.db` | `./data/symbols.db` | **CRITICAL** -- wrong default path |

---

*End of IMPL_ARCHITECTURE_REPORT.md*

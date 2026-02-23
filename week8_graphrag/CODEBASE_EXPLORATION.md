# CODEBASE_EXPLORATION.md -- Week 8: Graph RAG Exploration

> **Generated:** 2026-02-23
> **Agent:** CODEBASE EXPLORER
> **Scope:** Build 1 (super-team), Build 2 (agent-team-v15), Build 3 (super-team)
> **Purpose:** Exhaustive codebase map for downstream Graph RAG design-synthesizer

---

## Table of Contents

- [1A. Build 1 -- Codebase Intelligence Deep Dive](#1a-build-1----codebase-intelligence-deep-dive)
- [1B. Build 1 -- Architect and Contract Engine](#1b-build-1----architect-and-contract-engine)
- [1C. Build 2 -- Integration Points (agent-team-v15)](#1c-build-2----integration-points-agent-team-v15)
- [1D. Build 3 -- Integration Points (super_orchestrator, run4)](#1d-build-3----integration-points-super_orchestrator-run4)
- [1E. Existing MCP Infrastructure](#1e-existing-mcp-infrastructure)
- [1F. What Is Currently Missing -- Graph RAG Gap Analysis](#1f-what-is-currently-missing----graph-rag-gap-analysis)

---

## 1A. Build 1 -- Codebase Intelligence Deep Dive

### 1A.1 NetworkX Graph Architecture

**File:** `C:\MY_PROJECTS\super-team\src\codebase_intelligence\services\graph_builder.py`

The dependency graph is a `networkx.DiGraph` (directed graph). It is the central data structure for all dependency analysis.

**Graph type:**
```python
import networkx as nx
self._graph: nx.DiGraph = graph if graph is not None else nx.DiGraph()
```

**Node schema:**
- **Node ID:** File path as a string (e.g., `"src/services/user_service.py"`)
- **Node attributes:**
  - `language` (str): Detected language from `Language` enum -- `"python"`, `"typescript"`, `"csharp"`, `"go"`
  - `service_name` (str): Optional service affiliation

**Edge schema:**
- **Edge:** `(source_file, target_file)` directed edge
- **Edge attributes:**
  - `relation` (str): One of `DependencyRelation` enum values -- `"imports"`, `"calls"`, `"inherits"`, `"implements"`, `"uses"`
  - `line` (int): Source line number of the reference
  - `imported_names` (list[str]): Names imported (for import edges)
  - `source_symbol` (str): Source symbol qualified name
  - `target_symbol` (str): Target symbol qualified name

**Key methods on GraphBuilder:**

| Method | Signature | Purpose |
|--------|-----------|---------|
| `build_graph` | `build_graph(imports: list[ImportReference], edges: list[DependencyEdge]) -> nx.DiGraph` | Bulk-build graph from parsed data |
| `add_file` | `add_file(file_path, imports, edges, language, service_name)` | Incrementally add a single file with its edges |
| `remove_file` | `remove_file(file_path)` | Remove a node and all incident edges |
| `graph` | `@property -> nx.DiGraph` | Access the underlying DiGraph |

**File:** `C:\MY_PROJECTS\super-team\src\codebase_intelligence\services\graph_analyzer.py`

**Graph analysis algorithms implemented:**

| Algorithm | NetworkX Function | Purpose | Location |
|-----------|------------------|---------|----------|
| PageRank | `nx.pagerank(graph)` | Find most-connected/important files (top 10) | `analyze()` |
| Cycle detection | `nx.simple_cycles(graph)` | Detect circular dependencies (capped at 20) | `analyze()` |
| DAG check | `nx.is_directed_acyclic_graph(graph)` | Determine if graph is cycle-free | `analyze()` |
| Topological sort | `nx.topological_sort(graph)` | Compute safe build order (only if DAG) | `analyze()` |
| Connected components | `nx.number_weakly_connected_components(graph)` | Count disconnected subgraphs | `analyze()` |
| BFS dependencies | Manual BFS using `graph.successors(node)` | Transitive deps to depth N | `get_dependencies()` |
| BFS dependents | Manual BFS using `graph.predecessors(node)` | Reverse transitive deps to depth N | `get_dependents()` |
| Impact analysis | Combines `get_dependencies()` + `get_dependents()` | Full impact surface for a file | `get_impact()` |

**Return type of `analyze()`:**
```python
@dataclass
class GraphAnalysis:
    node_count: int
    edge_count: int
    is_dag: bool
    circular_dependencies: list[list[str]]
    top_files_by_pagerank: list[tuple[str, float]]
    connected_components: int
    build_order: list[str] | None  # None if not a DAG
```
Defined in: `C:\MY_PROJECTS\super-team\src\shared\models\codebase.py` (line ~110)

### 1A.2 ChromaDB Semantic Search

**File:** `C:\MY_PROJECTS\super-team\src\codebase_intelligence\storage\chroma_store.py`

**ChromaDB configuration:**
```python
_COLLECTION_NAME = "code_chunks"
_embedding_fn = DefaultEmbeddingFunction()  # all-MiniLM-L6-v2
# Collection created with:
metadata={"hnsw:space": "cosine"}
```

**Client type:** `chromadb.PersistentClient(path=persist_directory)`

**Document schema stored in ChromaDB:**

| Field | Source | Example |
|-------|--------|---------|
| `id` | `"{file_path}::{symbol_name}"` | `"src/user.py::UserService"` |
| `document` | `CodeChunk.content` (full source text of the symbol) | Function/class body |
| `metadata.file_path` | From CodeChunk | `"src/user.py"` |
| `metadata.symbol_name` | From CodeChunk | `"UserService"` |
| `metadata.symbol_kind` | From CodeChunk (`SymbolKind` value) | `"class"`, `"function"` |
| `metadata.language` | From CodeChunk | `"python"` |
| `metadata.service_name` | From CodeChunk | `"user-service"` |
| `metadata.line_start` | From CodeChunk | `42` |
| `metadata.line_end` | From CodeChunk | `95` |

**Critical implementation detail:** `None` values in metadata are converted to empty strings `""` because ChromaDB does not accept `None` metadata values.

**Query method:**
```python
def query(
    self,
    query_text: str,
    n_results: int = 10,
    where: dict | None = None,
) -> dict:
```
Returns: `{"ids": [...], "documents": [...], "metadatas": [...], "distances": [...]}`

**Score conversion:** `score = 1.0 - distance` (cosine distance to similarity)

**Indexing pipeline (SemanticIndexer):**

File: `C:\MY_PROJECTS\super-team\src\codebase_intelligence\services\semantic_indexer.py`

```python
class SemanticIndexer:
    def __init__(self, chroma_store: ChromaStore, symbol_db: SymbolDB):
        self._chroma = chroma_store
        self._symbol_db = symbol_db

    def index_symbols(self, symbols: list[SymbolDefinition], source: str) -> int:
        # 1. Creates CodeChunks from SymbolDefinitions (extracts source lines)
        # 2. Calls chroma_store.add_chunks(chunks)
        # 3. Back-links chroma_id into symbol_db via update_chroma_id()
```

**Search pipeline (SemanticSearcher):**

File: `C:\MY_PROJECTS\super-team\src\codebase_intelligence\services\semantic_searcher.py`

```python
class SemanticSearcher:
    def search(
        self, query: str,
        language: str | None = None,
        service_name: str | None = None,
        top_k: int = 10,
    ) -> list[SemanticSearchResult]:
        # Builds `where` filter dict from language/service_name
        # Queries ChromaStore
        # Converts to SemanticSearchResult with score = 1.0 - distance
```

### 1A.3 MCP Tools (Codebase Intelligence Server)

**File:** `C:\MY_PROJECTS\super-team\src\codebase_intelligence\mcp_server.py`

**Server instantiation:**
```python
from mcp.server.fastmcp import FastMCP
mcp = FastMCP("Codebase Intelligence")
```

**8 MCP tools exposed:**

| Tool Name | Parameters | Return Type | Description |
|-----------|-----------|-------------|-------------|
| `register_artifact` (aliased `index_file`) | `file_path: str, service_name: str?, source_base64: str?, project_root: str?` | `dict` (ArtifactResult) | Index a source file through the full pipeline |
| `search_semantic` (aliased `search_code`) | `query: str, language: str?, service_name: str?, n_results: int=10` | `list[dict]` (SemanticSearchResult) | Semantic code search via ChromaDB |
| `find_definition` | `symbol: str, language: str?` | `dict` (SymbolDefinition or error) | Find definition location of a symbol |
| `find_dependencies` (aliased `get_dependencies`) | `file_path: str, depth: int=1, direction: str="both"` | `dict` with imports/imported_by/transitive/circular | Get dependency relationships for a file |
| `analyze_graph` | (none) | `dict` (GraphAnalysis) | Full graph analysis: PageRank, cycles, DAG check |
| `check_dead_code` (aliased `detect_dead_code`) | `service_name: str?` | `list[dict]` (DeadCodeEntry) | Detect potentially unreferenced code |
| `find_callers` | `symbol: str, max_results: int=50` | `list[dict]` (caller entries) | Find all callers of a symbol |
| `get_service_interface` | `service_name: str` | `dict` (ServiceInterface) | Extract public interface of a service |

**Module-level initialization (lines 40-65):**
```python
_db_path = os.environ.get("DATABASE_PATH", "./data/codebase_intel.db")
_chroma_path = os.environ.get("CHROMA_PATH", "./data/chroma")
_pool = ConnectionPool(_db_path)
init_symbols_db(_pool)
_symbol_db = SymbolDB(_pool)
_graph_db = GraphDB(_pool)
_chroma_store = ChromaStore(_chroma_path)
existing_graph = _graph_db.load_snapshot()
_graph_builder = GraphBuilder(graph=existing_graph)
_graph_analyzer = GraphAnalyzer(_graph_builder.graph)
_ast_parser = ASTParser()
_symbol_extractor = SymbolExtractor()
_import_resolver = ImportResolver()
_dead_code_detector = DeadCodeDetector(_graph_builder.graph)
_semantic_indexer = SemanticIndexer(_chroma_store, _symbol_db)
_semantic_searcher = SemanticSearcher(_chroma_store)
_incremental_indexer = IncrementalIndexer(...)
_service_interface_extractor = ServiceInterfaceExtractor(_ast_parser, _symbol_extractor)
```

### 1A.4 Data Models

**File:** `C:\MY_PROJECTS\super-team\src\shared\models\codebase.py`

**Enumerations:**

```python
class SymbolKind(str, Enum):
    CLASS = "class"
    FUNCTION = "function"
    INTERFACE = "interface"
    TYPE = "type"
    ENUM = "enum"
    VARIABLE = "variable"
    METHOD = "method"

class Language(str, Enum):
    PYTHON = "python"
    TYPESCRIPT = "typescript"
    CSHARP = "csharp"
    GO = "go"

class DependencyRelation(str, Enum):
    IMPORTS = "imports"
    CALLS = "calls"
    INHERITS = "inherits"
    IMPLEMENTS = "implements"
    USES = "uses"
```

**Core dataclasses:**

| Dataclass | Key Fields | ID Generation |
|-----------|-----------|---------------|
| `SymbolDefinition` | file_path, symbol_name, kind, language, service_name, line_start, line_end, signature, docstring, is_exported, parent_symbol | `id = f"{file_path}::{symbol_name}"` |
| `ImportReference` | source_file, target_file, imported_names, line, is_relative | N/A |
| `DependencyEdge` | source_symbol_id, target_symbol_id, relation, source_file, target_file, line | N/A |
| `CodeChunk` | id, file_path, content, language, service_name, symbol_name, symbol_kind, line_start, line_end | `id = f"{file_path}::{symbol_name}"` |
| `SemanticSearchResult` | chunk_id, file_path, symbol_name, content, score, language, service_name, line_start, line_end | N/A |
| `ServiceInterface` | service_name, endpoints, events_published, events_consumed, exported_symbols | N/A |
| `GraphAnalysis` | node_count, edge_count, is_dag, circular_dependencies, top_files_by_pagerank, connected_components, build_order | N/A |

### 1A.5 HTTP API (FastAPI Routers)

**File:** `C:\MY_PROJECTS\super-team\src\codebase_intelligence\main.py`

**Application setup:**
```python
app = FastAPI(title="Codebase Intelligence", version=VERSION, lifespan=lifespan)
app.add_middleware(TraceIDMiddleware)
register_exception_handlers(app)
```

**6 Routers registered (in order):**

| Router | Import Path | Prefix |
|--------|-------------|--------|
| `health_router` | `src.codebase_intelligence.routers.health` | `/api/health` (inferred) |
| `symbols_router` | `src.codebase_intelligence.routers.symbols` | `/api/symbols` (inferred) |
| `dependencies_router` | `src.codebase_intelligence.routers.dependencies` | `/api/dependencies` (inferred) |
| `search_router` | `src.codebase_intelligence.routers.search` | `/api/search` (inferred) |
| `artifacts_router` | `src.codebase_intelligence.routers.artifacts` | `/api/artifacts` (inferred) |
| `dead_code_router` | `src.codebase_intelligence.routers.dead_code` | `/api/dead-code` (inferred) |

**Lifespan initialization order:**
1. `ConnectionPool(config.database_path)` + `init_symbols_db(pool)`
2. `SymbolDB(pool)`, `GraphDB(pool)`, `ChromaStore(config.chroma_path)`
3. `graph_db.load_snapshot()` -> `GraphBuilder(graph=existing_graph)`
4. `GraphAnalyzer(graph_builder.graph)`
5. `ASTParser()`, `SymbolExtractor()`, `ImportResolver()`
6. `DeadCodeDetector(graph_builder.graph)`
7. `SemanticIndexer(chroma_store, symbol_db)`, `SemanticSearcher(chroma_store)`
8. `ServiceInterfaceExtractor(ast_parser, symbol_extractor)`
9. `IncrementalIndexer(ast_parser, symbol_extractor, import_resolver, graph_builder, symbol_db, graph_db, semantic_indexer)`

**Shutdown:** `graph_db.save_snapshot(graph_builder.graph)` then `pool.close()`

### 1A.6 SQLite Schema (Symbols Database)

**File:** `C:\MY_PROJECTS\super-team\src\shared\db\schema.py` -- function `init_symbols_db(pool)`

**Tables:**

```sql
-- indexed_files: Tracks which files have been indexed
CREATE TABLE IF NOT EXISTS indexed_files (
    file_path TEXT PRIMARY KEY,
    language TEXT NOT NULL,
    service_name TEXT DEFAULT '',
    last_indexed TEXT NOT NULL,
    content_hash TEXT NOT NULL
);

-- symbols: Symbol definitions
CREATE TABLE IF NOT EXISTS symbols (
    id TEXT PRIMARY KEY,           -- "file_path::symbol_name"
    file_path TEXT NOT NULL,
    symbol_name TEXT NOT NULL,
    kind TEXT NOT NULL,            -- SymbolKind value
    language TEXT NOT NULL,
    service_name TEXT DEFAULT '',
    line_start INTEGER,
    line_end INTEGER,
    signature TEXT DEFAULT '',
    docstring TEXT DEFAULT '',
    is_exported INTEGER DEFAULT 1,
    parent_symbol TEXT DEFAULT '',
    chroma_id TEXT DEFAULT ''      -- Back-link to ChromaDB
);

-- dependency_edges: Graph edges persisted to SQLite
CREATE TABLE IF NOT EXISTS dependency_edges (
    source_file TEXT NOT NULL,
    target_file TEXT NOT NULL,
    relation TEXT NOT NULL,
    line INTEGER DEFAULT 0,
    imported_names TEXT DEFAULT '[]',
    source_symbol TEXT DEFAULT '',
    target_symbol TEXT DEFAULT '',
    PRIMARY KEY (source_file, target_file, relation, source_symbol, target_symbol)
);

-- import_references: Raw import statements
CREATE TABLE IF NOT EXISTS import_references (
    source_file TEXT NOT NULL,
    target_file TEXT NOT NULL,
    imported_names TEXT DEFAULT '[]',
    line INTEGER DEFAULT 0,
    is_relative INTEGER DEFAULT 0
);

-- graph_snapshots: Serialized NetworkX graph
CREATE TABLE IF NOT EXISTS graph_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    snapshot_data TEXT NOT NULL,   -- JSON: nx.node_link_data(graph, edges="edges")
    created_at TEXT NOT NULL
);
```

**Connection pool:** `C:\MY_PROJECTS\super-team\src\shared\db\connection.py`
- WAL mode enabled: `PRAGMA journal_mode=WAL`
- Foreign keys ON: `PRAGMA foreign_keys=ON`
- Busy timeout: `PRAGMA busy_timeout=30000`

### 1A.7 Graph Persistence

**File:** `C:\MY_PROJECTS\super-team\src\codebase_intelligence\storage\graph_db.py`

**Serialization:**
```python
def save_snapshot(self, graph: nx.DiGraph) -> None:
    data = nx.node_link_data(graph, edges="edges")
    json_str = json.dumps(data)
    # INSERT INTO graph_snapshots (snapshot_data, created_at) VALUES (?, ?)
```

**Deserialization:**
```python
def load_snapshot(self) -> nx.DiGraph | None:
    # SELECT snapshot_data FROM graph_snapshots ORDER BY id DESC LIMIT 1
    data = json.loads(row["snapshot_data"])
    return nx.node_link_graph(data, edges="edges")
```

**Edge persistence (separate from graph snapshots):**
```python
def save_edges(self, edges: list[DependencyEdge]) -> None:
    # INSERT OR REPLACE INTO dependency_edges (...)
```

### 1A.8 AST Parsing (Tree-sitter)

**File:** `C:\MY_PROJECTS\super-team\src\codebase_intelligence\services\ast_parser.py`

**Language support:**

| Language | Tree-sitter Module | Language Instance |
|----------|-------------------|-------------------|
| Python | `tree_sitter_python` | `tree_sitter_python.language()` |
| TypeScript | `tree_sitter_typescript` | `tree_sitter_typescript.language_typescript()` |
| C# | `tree_sitter_c_sharp` | `tree_sitter_c_sharp.language()` |
| Go | `tree_sitter_go` | `tree_sitter_go.language()` |

**API pattern (tree-sitter 0.25.2):**
```python
from tree_sitter import Language, Parser, Query
parser = Parser(Language(tree_sitter_python.language()))
tree = parser.parse(source_bytes)
# Query pattern for symbol extraction:
query = Query(language, query_string)
cursor = query.exec(tree.root_node)
for match in cursor:
    ...
```

**File:** `C:\MY_PROJECTS\super-team\src\codebase_intelligence\services\symbol_extractor.py`

Extracts `SymbolDefinition` objects from tree-sitter parse trees. Handles classes, functions, methods, interfaces, enums, and type aliases per language.

### 1A.9 Import Resolution

**File:** `C:\MY_PROJECTS\super-team\src\codebase_intelligence\services\import_resolver.py`

**Python imports:** Tree-sitter queries for `import_statement` and `import_from_statement`. Handles:
- Absolute imports: `import foo.bar` -> target = `foo/bar.py`
- From imports: `from foo.bar import Baz` -> target = `foo/bar.py`, imported_names = `["Baz"]`
- Relative imports: `from . import utils` -> resolved relative to current file

**TypeScript imports:** Tree-sitter queries for `import_statement`. Handles:
- Relative paths: `import { Foo } from "./bar"` -> resolves to `bar.ts` or `bar/index.ts`
- tsconfig path aliases (partial)

### 1A.10 Dead Code Detection

**File:** `C:\MY_PROJECTS\super-team\src\codebase_intelligence\services\dead_code_detector.py`

**Confidence levels:**
- `high`: Symbol has zero in-degree in the dependency graph (never referenced by any other file)
- `medium`: Symbol only referenced from its own file, or is a method/interface with no external callers
- `low`: Symbol matches handler-like patterns (e.g., event handlers, lifecycle methods)

**Entry point exclusions (never flagged as dead):**
- `__main__` modules
- `test_*` functions/methods
- Lifecycle methods (`on_startup`, `on_shutdown`, etc.)
- Dunder methods (`__init__`, `__str__`, etc.)

### 1A.11 Service Interface Extraction

**File:** `C:\MY_PROJECTS\super-team\src\codebase_intelligence\services\service_interface_extractor.py`

Detects and extracts:
- **HTTP endpoints:** FastAPI (`@app.get/post/put/delete`), Express (`app.get/post`), NestJS (`@Get/@Post`), ASP.NET (`[HttpGet]`), Go `net/http` (`http.HandleFunc`)
- **Event publish/subscribe patterns:** Kafka (`producer.send`, `consumer.subscribe`), Redis pub/sub, custom event bus patterns
- **Exported symbols:** Public classes, functions, and constants marked as `is_exported=True`

Returns a `ServiceInterface` dataclass.

### 1A.12 Incremental Indexer Pipeline

**File:** `C:\MY_PROJECTS\super-team\src\codebase_intelligence\services\incremental_indexer.py`

**7-step pipeline for `index_file(file_path, source, service_name, project_root)`:**

1. **Detect language** -- from file extension via `Language` enum
2. **Parse AST** -- `ast_parser.parse_file(source, file_path)`
3. **Extract symbols** -- `symbol_extractor.extract(tree, file_path, language)`
4. **Resolve imports** -- `import_resolver.resolve(tree, file_path, language, project_root)`
5. **Update graph** -- `graph_builder.add_file(file_path, imports, edges, language, service_name)`
6. **Persist to DB** -- `symbol_db.save_symbols(symbols)`, `graph_db.save_edges(edges)`
7. **Semantic indexing** -- `semantic_indexer.index_symbols(symbols, source)`

---

## 1B. Build 1 -- Architect and Contract Engine

### 1B.1 Architect MCP Server

**File:** `C:\MY_PROJECTS\super-team\src\architect\mcp_server.py`

**Server:** `mcp = FastMCP("Architect")`

**4 MCP tools:**

| Tool | Parameters | Return | Purpose |
|------|-----------|--------|---------|
| `decompose` | `prd_text: str` | `dict` (DecompositionResult) | Full PRD decomposition pipeline |
| `get_service_map` | `project_name: str?` | `dict` (ServiceMap) | Retrieve most recent service map |
| `get_domain_model` | `project_name: str?` | `dict` (DomainModel) | Retrieve most recent domain model |
| `get_contracts_for_service` | `service_name: str` | `list[dict]` | Get contract stubs for a service |

**Decompose pipeline (executed inside `decompose` tool):**
1. `prd_parser.parse_prd(prd_text)` -> `ParsedPRD`
2. `service_boundary.identify_boundaries(parsed)` -> list of `ServiceBoundary`
3. `service_boundary.build_service_map(parsed, boundaries)` -> `ServiceMap`
4. `domain_modeler.build_domain_model(parsed, boundaries)` -> `DomainModel`
5. `validator.validate_decomposition(service_map, domain_model)` -> list of issues
6. `contract_generator.generate_contract_stubs(service_map, domain_model)` -> list of contract dicts
7. Persist to DB: `service_map_store.save(service_map)`, `domain_model_store.save(domain_model)`

### 1B.2 Architect Data Models

**File:** `C:\MY_PROJECTS\super-team\src\shared\models\architect.py`

**Key dataclasses:**

| Dataclass | Key Fields |
|-----------|-----------|
| `ServiceDefinition` | name, domain, description, stack (ServiceStack), estimated_loc, owns_entities, provides_contracts, consumes_contracts |
| `DomainEntity` | name, description, owning_service, fields (list[EntityField]), state_machine (StateMachine or None) |
| `DomainRelationship` | source_entity, target_entity, relationship_type (RelationshipType), cardinality |
| `ServiceMap` | project_name, services (list[ServiceDefinition]), generated_at, prd_hash, build_cycle_id |
| `DomainModel` | entities (list[DomainEntity]), relationships (list[DomainRelationship]), generated_at |
| `DecompositionResult` | service_map, domain_model, contract_stubs, validation_issues, interview_questions |
| `ParsedPRD` | project_name, entities, relationships, bounded_contexts, technology_hints, state_machines, interview_questions |

**RelationshipType enum:** `OWNS`, `REFERENCES`, `TRIGGERS`, `EXTENDS`, `DEPENDS_ON`

### 1B.3 PRD Parser (Deterministic, No LLM)

**File:** `C:\MY_PROJECTS\super-team\src\architect\services\prd_parser.py`

Pure regex/heuristic-based extraction. **5 entity extraction strategies:**
1. **Markdown tables** -- detects `|` delimited rows with entity names
2. **Heading + bullets** -- `### Entity Name\n- field1: type`
3. **Sentences/prose** -- NLP-like patterns: "The system manages X"
4. **Data model sections** -- dedicated `## Data Model` sections
5. **Terse/inline patterns** -- comma-separated entity mentions

**Relationship extraction:** Keyword patterns like "depends on", "triggers", "references", "extends", "owns"

**State machine detection:** Looks for status/state fields and transition descriptions (e.g., "from X to Y")

### 1B.4 Service Boundary Detection

**File:** `C:\MY_PROJECTS\super-team\src\architect\services\service_boundary.py`

**4-step algorithm:**
1. **Explicit bounded contexts** -- if PRD declares them, use directly
2. **Aggregate root discovery** -- entities with the most relationships become aggregate roots; each root gets its own service
3. **Relationship-based assignment** -- remaining entities assigned to the service that owns/references them most
4. **Fallback monolith** -- if no boundaries found, create a single-service monolith

### 1B.5 Contract Generator

**File:** `C:\MY_PROJECTS\super-team\src\architect\services\contract_generator.py`

Generates OpenAPI 3.1 specification stubs:
- CRUD endpoints per owned entity (GET collection, GET by ID, POST, PUT, DELETE)
- JSON Schema for request/response bodies derived from `DomainEntity.fields`
- Health endpoint (`GET /health`)

### 1B.6 Contract Engine MCP Server

**File:** `C:\MY_PROJECTS\super-team\src\contract_engine\mcp_server.py`

**Server:** `mcp = FastMCP("Contract Engine")`

**10 MCP tools:**

| Tool Name | MCP Alias | Parameters | Return |
|-----------|-----------|-----------|--------|
| `create_contract` | -- | service_name, type, version, spec, build_cycle_id? | dict (ContractEntry) |
| `list_contracts` | -- | page, page_size, service_name?, contract_type?, status? | dict (paginated) |
| `get_contract` | -- | contract_id | dict (ContractEntry) |
| `validate_contract` | `validate_spec` | spec, type | dict (ValidationResult) |
| `detect_breaking_changes` | `check_breaking_changes` | contract_id, new_spec? | list[dict] (BreakingChange) |
| `mark_implementation` | `mark_implemented` | contract_id, service_name, evidence_path | dict |
| `get_unimplemented` | `get_unimplemented_contracts` | service_name? | list[dict] |
| `generate_tests` | -- | contract_id, framework, include_negative | str (test code) |
| `check_compliance` | -- | contract_id, response_data? | list[dict] (ComplianceResult) |
| `validate_endpoint` | -- | service_name, method, path, response_body, status_code | dict (valid, violations) |

**Module-level initialization:**
```python
_db_path = os.environ.get("DATABASE_PATH", "./data/contracts.db")
_pool = ConnectionPool(_db_path)
init_contracts_db(_pool)
_contract_store = ContractStore(_pool)
_implementation_tracker = ImplementationTracker(_pool)
_version_manager = VersionManager(_pool)
_test_generator = ContractTestGenerator(_pool)
_compliance_checker = ComplianceChecker(_pool)
```

### 1B.7 Contract Engine Service Layer

**ContractStore** (`C:\MY_PROJECTS\super-team\src\contract_engine\services\contract_store.py`):
- `upsert(create: ContractCreate)` -- creates or updates; computes `spec_hash` for dedup
- `get(contract_id)` -- by UUID
- `list(page, page_size, filters)` -- paginated query

**BreakingChangeDetector** (`C:\MY_PROJECTS\super-team\src\contract_engine\services\breaking_change_detector.py`):
- `detect_breaking_changes(old_spec, new_spec)` -- compares OpenAPI specs
- Detects: removed endpoints, changed response schemas, removed fields, type changes
- Each change has `is_breaking: bool` and `severity: str`

**ImplementationTracker** (`C:\MY_PROJECTS\super-team\src\contract_engine\services\implementation_tracker.py`):
- `mark_implemented(contract_id, service_name, evidence_path)` -- records implementation evidence
- `get_unimplemented(service_name?)` -- finds contracts without full implementation coverage

**VersionManager** (`C:\MY_PROJECTS\super-team\src\contract_engine\services\version_manager.py`):
- `create_version(contract_id, new_spec, version_str)` -- creates version, runs breaking change detection
- `get_version_history(contract_id)` -- ordered version list

**TestGenerator** (`C:\MY_PROJECTS\super-team\src\contract_engine\services\test_generator.py`):
- Generates Schemathesis tests for OpenAPI contracts
- Generates jsonschema validation tests for AsyncAPI contracts
- Supports pytest and jest frameworks
- Optionally generates negative/4xx test cases

**ComplianceChecker** (`C:\MY_PROJECTS\super-team\src\contract_engine\services\compliance_checker.py`):
- Validates runtime response data against contracted schemas
- Reports per-field type mismatches, missing required fields

**OpenAPI Validator** (`C:\MY_PROJECTS\super-team\src\contract_engine\services\openapi_validator.py`):
- Structural validation via `openapi-spec-validator` / `prance`
- $ref resolution validation

**AsyncAPI Validator** (`C:\MY_PROJECTS\super-team\src\contract_engine\services\asyncapi_validator.py`):
- Structural validation of AsyncAPI 3.x documents

### 1B.8 Contract Engine SQLite Schema

**File:** `C:\MY_PROJECTS\super-team\src\shared\db\schema.py` -- function `init_contracts_db(pool)`

```sql
-- build_cycles: Immutability tracking
CREATE TABLE IF NOT EXISTS build_cycles (
    id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    status TEXT DEFAULT 'active'
);

-- contracts: Core contract storage
CREATE TABLE IF NOT EXISTS contracts (
    id TEXT PRIMARY KEY,
    type TEXT NOT NULL,         -- "openapi", "asyncapi", "json_schema"
    version TEXT NOT NULL,
    service_name TEXT NOT NULL,
    spec TEXT NOT NULL,         -- JSON blob of the full spec
    spec_hash TEXT NOT NULL,
    status TEXT DEFAULT 'active',
    build_cycle_id TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

-- contract_versions: Version history with breaking change records
CREATE TABLE IF NOT EXISTS contract_versions (...);

-- breaking_changes: Detected breaking changes
CREATE TABLE IF NOT EXISTS breaking_changes (...);

-- implementations: Which services implement which contracts
CREATE TABLE IF NOT EXISTS implementations (...);

-- test_suites: Generated test code cache
CREATE TABLE IF NOT EXISTS test_suites (...);

-- shared_schemas: Reusable JSON Schema definitions
CREATE TABLE IF NOT EXISTS shared_schemas (...);

-- schema_consumers: Which contracts reference shared schemas
CREATE TABLE IF NOT EXISTS schema_consumers (...);
```

### 1B.9 Architect SQLite Schema

**File:** `C:\MY_PROJECTS\super-team\src\shared\db\schema.py` -- function `init_architect_db(pool)`

```sql
CREATE TABLE IF NOT EXISTS service_maps (
    id TEXT PRIMARY KEY,
    project_name TEXT NOT NULL,
    data TEXT NOT NULL,          -- JSON: ServiceMap serialized
    prd_hash TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS domain_models (
    id TEXT PRIMARY KEY,
    project_name TEXT NOT NULL,
    data TEXT NOT NULL,          -- JSON: DomainModel serialized
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS decomposition_runs (
    id TEXT PRIMARY KEY,
    project_name TEXT NOT NULL,
    prd_hash TEXT,
    service_map_id TEXT,
    domain_model_id TEXT,
    validation_issues TEXT DEFAULT '[]',
    created_at TEXT NOT NULL
);
```

---

## 1C. Build 2 -- Integration Points (agent-team-v15)

### 1C.1 Codebase Intelligence Client

**File:** `C:\MY_PROJECTS\agent-team-v15\src\agent_team_v15\codebase_client.py`

**Class:** `CodebaseIntelligenceClient`

Wraps 7 CI MCP tools with typed return values:

| Method | MCP Tool | Return Type |
|--------|----------|-------------|
| `find_definition(symbol, language?)` | `find_definition` | `DefinitionResult` (file, line, kind, signature) |
| `find_callers(symbol, max_results=50)` | `find_callers` | `list[CallerResult]` |
| `find_dependencies(file_path, depth=1, direction="both")` | `find_dependencies` | `DependencyResult` (imports, imported_by, transitive, circular) |
| `search_semantic(query, language?, service_name?, n_results=10)` | `search_semantic` | `list[SearchResult]` |
| `get_service_interface(service_name)` | `get_service_interface` | `ServiceInterfaceResult` |
| `check_dead_code(service_name?)` | `check_dead_code` | `list[DeadCodeResult]` |
| `register_artifact(file_path, service_name?, source_base64?, project_root?)` | `register_artifact` | `ArtifactResult` |

### 1C.2 Contract Engine Client

**File:** `C:\MY_PROJECTS\agent-team-v15\src\agent_team_v15\contract_client.py`

**Class:** `ContractEngineClient`

Wraps 6 CE MCP tools:

| Method | MCP Tool | Return Type |
|--------|----------|-------------|
| `get_contract(contract_id)` | `get_contract` | dict |
| `validate_endpoint(service, method, path, body, status)` | `validate_endpoint` | dict (valid, violations) |
| `generate_tests(contract_id, framework, include_negative)` | `generate_tests` | str (test code) |
| `check_breaking_changes(contract_id, new_spec?)` | `check_breaking_changes` | list[dict] |
| `mark_implemented(contract_id, service_name, evidence_path)` | `mark_implemented` | dict |
| `get_unimplemented_contracts(service_name?)` | `get_unimplemented_contracts` | list[dict] |

**Retry helper:** `_call_with_retry(session, tool_name, params)` -- 3 retries, backoff [1s, 2s, 4s], classifies transient vs non-transient errors.

### 1C.3 Architect Client (Build 2 copy)

**File:** `C:\MY_PROJECTS\agent-team-v15\src\agent_team_v15\mcp_clients.py` (lines 189-278)

**Class:** `ArchitectClient`

| Method | MCP Tool | Return |
|--------|----------|--------|
| `decompose(description)` | `decompose` | dict |
| `get_service_map()` | `get_service_map` | dict |
| `get_contracts_for_service(service_name)` | `get_contracts_for_service` | list[dict] |
| `get_domain_model(service_name?)` | `get_domain_model` | dict |

All methods use `_call_with_retry` from `contract_client` module. All catch exceptions and return safe defaults (empty dict/list).

### 1C.4 MCP Session Management

**File:** `C:\MY_PROJECTS\agent-team-v15\src\agent_team_v15\mcp_clients.py`

Two async context managers for creating MCP sessions:

**`create_contract_engine_session(config: ContractEngineConfig)`:**
- Lazy imports MCP SDK
- SEC-001: Only passes `PATH` and `DATABASE_PATH` to subprocess (never `os.environ` spread)
- Uses `asyncio.wait_for(session.initialize(), timeout=startup_timeout)` for timeout
- Catches `TimeoutError`, `ConnectionError`, `ProcessLookupError`, `OSError` -> raises `MCPConnectionError`

**`create_codebase_intelligence_session(config: CodebaseIntelligenceConfig)`:**
- Same pattern, passes `PATH`, `DATABASE_PATH`, `CHROMA_PATH`, `GRAPH_PATH`
- Same timeout and error handling

**Config dataclasses** (referenced from `config.py`):

| Config | Key Fields |
|--------|-----------|
| `ContractEngineConfig` | mcp_command, mcp_args, database_path, startup_timeout_ms, server_root |
| `CodebaseIntelligenceConfig` | mcp_command, mcp_args, database_path, chroma_path, graph_path, startup_timeout_ms, server_root |

### 1C.5 Codebase Map (Static Analysis Fallback)

**File:** `C:\MY_PROJECTS\agent-team-v15\src\agent_team_v15\codebase_map.py`

**`generate_codebase_map(project_root, timeout)`:**
- Uses Python `ast` module for Python files (class/function/import extraction)
- Uses regex for TypeScript/JavaScript files
- Produces `CodebaseMap` dataclass: root, modules, import_graph, shared_files, frameworks, total_files, total_lines, primary_language
- Runs in `asyncio.get_event_loop().run_in_executor()` with timeout

**`generate_codebase_map_from_mcp(client: CodebaseIntelligenceClient)`:**
- MCP-backed alternative: uses `search_semantic`, `get_service_interface`, `check_dead_code`
- Falls back to static analysis if MCP unavailable

### 1C.6 Local Contract System

**File:** `C:\MY_PROJECTS\agent-team-v15\src\agent_team_v15\contracts.py`

Two layers:

**Layer 1 -- Local contracts (`ContractRegistry`):**
- `ModuleContract`: file_path, exports (list[str])
- `WiringContract`: source_module, target_module, imports (list[str])
- `MiddlewareContract`: name, applies_to (list[str])
- Serialized to `CONTRACTS.json` in project root
- `verify_all_contracts(registry, project_root)` -- checks module exports and wiring imports exist

**Layer 2 -- Service contracts (`ServiceContractRegistry`):**
- `ServiceContract`: service_name, endpoints (list), events (list), dependencies (list)
- Loads from Contract Engine MCP or local JSON cache
- Used for cross-service interface verification

### 1C.7 Fallback Functions (WIRE-009, WIRE-010, WIRE-011)

**WIRE-009 -- Contract scan fallback:**
- **File:** `C:\MY_PROJECTS\super-team\src\contract_engine\mcp_client.py`
- `run_api_contract_scan(project_root)` -- walks filesystem for `.json`/`.yaml`/`.yml` in `contracts/`, `specs/`, `api/` dirs
- `get_contracts_with_fallback(project_root, client?)` -- tries CE MCP first, falls back

**WIRE-010 -- Codebase map fallback:**
- **File:** `C:\MY_PROJECTS\super-team\src\codebase_intelligence\mcp_client.py`
- `generate_codebase_map(project_root)` -- walks filesystem, groups files by language
- `get_codebase_map_with_fallback(project_root, client?)` -- tries CI MCP first, falls back

**WIRE-011 -- PRD decomposition fallback:**
- **File:** `C:\MY_PROJECTS\super-team\src\architect\mcp_client.py`
- `decompose_prd_basic(prd_text)` -- extracts project slug from first line, returns single-service stub
- `decompose_prd_with_fallback(prd_text, client?)` -- tries Architect MCP first, falls back

All fallback results include `"fallback": True` marker.

---

## 1D. Build 3 -- Integration Points (super_orchestrator, run4)

### 1D.1 Super Orchestrator Pipeline

**File:** `C:\MY_PROJECTS\super-team\src\super_orchestrator\pipeline.py`

**Pipeline phases (in order):**
```
init -> architect_running -> architect_review -> contracts_registering
     -> builders_running -> builders_complete -> integrating
     -> quality_gate -> (fix_pass loop) -> complete
```

**Key design decisions:**
- MCP-first with fallback (architect phase tries MCP stdio first)
- Lazy imports (all external deps imported inside function bodies)
- Semaphore-guarded parallelism for builder subprocesses
- try/finally cleanup for all subprocesses

**Environment filtering for builder subprocesses:**
```python
_FILTERED_ENV_KEYS = {"AWS_SECRET_ACCESS_KEY", "CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT"}
```
Note: `ANTHROPIC_API_KEY` is intentionally NOT filtered (builders need it).

### 1D.2 State Machine

**File:** `C:\MY_PROJECTS\super-team\src\super_orchestrator\state_machine.py`

Uses `transitions` library with `AsyncMachine`.

**11 states:**
```python
STATES = [
    "init", "architect_running", "architect_review",
    "contracts_registering", "builders_running", "builders_complete",
    "integrating", "quality_gate", "fix_pass",
    "complete", "failed"
]
```

**13 transitions with guard conditions:**

| Trigger | Source | Dest | Guard |
|---------|--------|------|-------|
| `start_architect` | init | architect_running | `is_configured` |
| `architect_done` | architect_running | architect_review | `has_service_map` |
| `approve_architect` | architect_review | contracts_registering | `service_map_valid` |
| `contracts_registered` | contracts_registering | builders_running | `contracts_valid` |
| `builders_done` | builders_running | builders_complete | `has_builder_results` |
| `start_integration` | builders_complete | integrating | `any_builder_passed` |
| `integration_done` | integrating | quality_gate | `has_integration_report` |
| `quality_passed` | quality_gate | complete | `gate_passed` |
| `quality_needs_fix` | quality_gate | fix_pass | `fix_attempts_remaining` |
| `fix_done` | fix_pass | builders_running | `fix_applied` |
| `fail` | (9 states) | failed | (none) |
| `retry_architect` | architect_running | architect_running | `retries_remaining` |
| `skip_to_complete` | quality_gate | complete | `advisory_only` |

**PipelineModel guard methods** (12 guards on lines 119-179 of pipeline.py):
- `is_configured()`, `has_service_map()`, `service_map_valid()`, `contracts_valid()`,
  `has_builder_results()`, `any_builder_passed()`, `has_integration_report()`,
  `gate_passed()`, `fix_attempts_remaining()`, `fix_applied()`, `retries_remaining()`,
  `advisory_only()`

### 1D.3 Pipeline State Persistence

**File:** `C:\MY_PROJECTS\super-team\src\super_orchestrator\state.py`

**`PipelineState` dataclass with 30+ fields:**

| Field Group | Fields |
|-------------|--------|
| Identity | pipeline_id (UUID), prd_path, config_path, depth |
| State | current_state, previous_state, completed_phases, phase_artifacts |
| Architect | architect_retries, max_architect_retries, service_map_path, contract_registry_path, domain_model_path |
| Builders | builder_statuses, builder_costs, builder_results, total_builders, successful_builders |
| Integration | services_deployed, integration_report_path |
| Quality | quality_attempts, max_quality_retries, last_quality_results, quality_report_path |
| Cost | total_cost, phase_costs, budget_limit |
| Timing | started_at, updated_at |
| Interruption | interrupted, interrupt_reason |

**Persistence:** JSON file at `.super-orchestrator/PIPELINE_STATE.json` using `atomic_write_json`.

### 1D.4 Super Orchestrator Configuration

**File:** `C:\MY_PROJECTS\super-team\src\super_orchestrator\config.py`

```python
@dataclass
class SuperOrchestratorConfig:
    architect: ArchitectConfig      # max_retries=2, timeout=900, auto_approve=False
    builder: BuilderConfig          # max_concurrent=3, timeout_per_builder=1800, depth="thorough"
    integration: IntegrationConfig  # timeout=600, traefik_image="traefik:v3.6"
    quality_gate: QualityGateConfig # max_fix_retries=3, blocking_severity="error"
    budget_limit: float | None
    depth: str = "standard"
    mode: str = "auto"              # "docker", "mcp", or "auto"
    output_dir: str = ".super-orchestrator"
```

### 1D.5 Quality Gate Engine (4-Layer)

**File:** `C:\MY_PROJECTS\super-team\src\quality_gate\gate_engine.py`

**Sequential execution with gating:**
```
Layer 1 (Per-Service) -> must PASS -> Layer 2 (Contract)
    -> must PASS/PARTIAL -> Layer 3 (System-Level)
    -> must PASS/PARTIAL -> Layer 4 (Adversarial, advisory-only)
```

If any layer FAILS, subsequent layers are SKIPPED.

**Layer 1** (`layer1_per_service.py`): Evaluates `BuilderResult` list -- checks success flag, test pass ratio
**Layer 2** (`layer2_contract_compliance.py`): Evaluates `IntegrationReport` -- contract test pass ratio
**Layer 3** (`layer3_system_level.py`): Scans project directory -- security, CORS, logging, secrets, Docker, health
**Layer 4** (`layer4_adversarial.py`): Advisory-only -- dead event handlers, dead contracts, orphan services, naming inconsistencies

**40 scan codes across 8 categories:**

| Category | Codes | Count |
|----------|-------|-------|
| JWT Security | SEC-001 to SEC-006 | 6 |
| CORS | CORS-001 to CORS-003 | 3 |
| Secret Detection | SEC-SECRET-001 to SEC-SECRET-012 | 12 |
| Logging | LOG-001, LOG-004, LOG-005 | 3 |
| Trace Propagation | TRACE-001 | 1 |
| Health Endpoints | HEALTH-001 | 1 |
| Docker Security | DOCKER-001 to DOCKER-008 | 8 |
| Adversarial | ADV-001 to ADV-006 | 6 |

(Defined in `C:\MY_PROJECTS\super-team\src\build3_shared\constants.py`)

### 1D.6 Fix Pass Engine (Run 4)

**File:** `C:\MY_PROJECTS\super-team\src\run4\fix_pass.py`

**6-step fix cycle:**
1. **DISCOVER** -- take violation snapshot, count open findings
2. **CLASSIFY** -- assign P0/P1/P2/P3 priority to each finding
3. **GENERATE** -- create fix instructions for the builder
4. **APPLY** -- invoke builder to apply fixes (via `feed_violations_to_builder`)
5. **VERIFY** -- re-scan and verify fixes
6. **REGRESS** -- check for regressions (compare before/after snapshots)

**Priority classification (decision tree):**
- **P0:** System cannot start (fatal, crash, build failure, import error)
- **P1:** Primary use case fails (API error, auth broken, test failure)
- **P2:** Secondary feature broken (non-critical, documentation, coverage)
- **P3:** Cosmetic (style, naming, formatting)

**Convergence checking (`check_convergence`):**

Hard stops (any one triggers immediate stop):
1. P0 == 0 AND P1 == 0 (all critical resolved)
2. current_pass >= max_fix_passes
3. budget_remaining <= 0
4. fix_effectiveness < 30%
5. regression_rate > 25%

Soft convergence (either triggers):
A. `compute_convergence() >= 0.85` (weighted formula)
B. REQ-033 4-condition: P0=0, P1<=2, last 2 passes <3 new defects, aggregate score >= 70

**Convergence formula:**
```python
convergence = 1.0 - (remaining_p0 * 0.4 + remaining_p1 * 0.3 + remaining_p2 * 0.1) / initial_total_weighted
```

### 1D.7 Docker Compose Generation

**File:** `C:\MY_PROJECTS\super-team\src\integrator\compose_generator.py`

**5-file compose merge strategy (TECH-004):**
1. `docker-compose.infra.yml` -- PostgreSQL 16-alpine, Redis 7-alpine, networks, volumes
2. `docker-compose.build1.yml` -- Build 1 foundation services
3. `docker-compose.traefik.yml` -- Traefik v3.6 reverse proxy
4. `docker-compose.generated.yml` -- Generated app services
5. `docker-compose.run4.yml` -- Run 4 verification overrides

**RAM budget (TECH-006):** 4.5GB total
- Traefik: 256MB
- PostgreSQL: 512MB
- Redis: 256MB
- Per app service: 768MB

**Network segmentation:**
- `frontend` network: Traefik + app services
- `backend` network: PostgreSQL, Redis + app services
- Traefik NOT on backend, DB NOT on frontend

### 1D.8 Contract Compliance Verification

**File:** `C:\MY_PROJECTS\super-team\src\integrator\contract_compliance.py`

**`ContractComplianceVerifier` facade** composes:
- `SchemathesisRunner` -- property-based OpenAPI testing (positive + negative tests)
- `PactManager` -- consumer-driven contract verification

Both run in parallel per service via `asyncio.gather()`.

Returns `IntegrationReport` with violation list, test counts, overall health.

### 1D.9 Build 3 Shared Models

**File:** `C:\MY_PROJECTS\super-team\src\build3_shared\models.py`

| Dataclass | Purpose | Key Fields |
|-----------|---------|-----------|
| `ServiceInfo` | Service metadata | service_id, domain, stack, port, status, build_cost |
| `BuilderResult` | Builder execution outcome | system_id, service_id, success, cost, test_passed/total, convergence_ratio |
| `ContractViolation` | Contract compliance issue | code, severity, service, endpoint, message, expected, actual |
| `ScanViolation` | Quality gate scan issue | code, severity, category, file_path, line, service, message |
| `LayerResult` | Single quality gate layer | layer, verdict, violations, total_checks, passed_checks |
| `QualityGateReport` | Full quality gate report | layers, overall_verdict, fix_attempts, total_violations, blocking_violations |
| `IntegrationReport` | Integration test results | services_deployed/healthy, contract_tests, integration_tests, data_flow_tests, boundary_tests |

**Enums:**
- `ServiceStatus`: PENDING, BUILDING, BUILT, DEPLOYING, HEALTHY, UNHEALTHY, FAILED
- `QualityLevel`: LAYER1_SERVICE, LAYER2_CONTRACT, LAYER3_SYSTEM, LAYER4_ADVERSARIAL
- `GateVerdict`: PASSED, FAILED, PARTIAL, SKIPPED

### 1D.10 Build 3 Protocols

**File:** `C:\MY_PROJECTS\super-team\src\build3_shared\protocols.py`

```python
@runtime_checkable
class PhaseExecutor(Protocol):
    async def execute(self, context: Any) -> float: ...
    async def can_execute(self, context: Any) -> bool: ...

@runtime_checkable
class QualityScanner(Protocol):
    def scan(self, project_root: Path) -> list[ScanViolation]: ...
    @property
    def scan_codes(self) -> list[str]: ...
```

---

## 1E. Existing MCP Infrastructure

### 1E.1 Transport Architecture

All MCP communication uses **stdio transport** (subprocess + stdin/stdout JSON-RPC).

**Server-side pattern:**
```python
from mcp.server.fastmcp import FastMCP
mcp = FastMCP("Service Name")

@mcp.tool()
def tool_name(param: type) -> return_type:
    ...

if __name__ == "__main__":
    mcp.run()
```

**Client-side pattern:**
```python
from mcp import StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.client.session import ClientSession

server_params = StdioServerParameters(
    command="python",
    args=["-m", "src.service.mcp_server"],
)
async with stdio_client(server_params) as (read, write):
    async with ClientSession(read, write) as session:
        await session.initialize()
        result = await session.call_tool("tool_name", {"param": value})
```

### 1E.2 MCP Server Inventory

| Server | Module | Tool Count | Transport |
|--------|--------|-----------|-----------|
| Codebase Intelligence | `src.codebase_intelligence.mcp_server` | 8 | stdio |
| Architect | `src.architect.mcp_server` | 4 | stdio |
| Contract Engine | `src.contract_engine.mcp_server` | 10 | stdio |

**Total: 22 MCP tools across 3 servers.**

### 1E.3 MCP Client Inventory

| Client Class | Module | Wraps Server | Tool Count |
|-------------|--------|-------------|-----------|
| `ArchitectClient` (Build 1) | `src.architect.mcp_client` | Architect | 4 |
| `ContractEngineClient` (Build 1) | `src.contract_engine.mcp_client` | Contract Engine | 9 |
| `CodebaseIntelligenceClient` (Build 1) | `src.codebase_intelligence.mcp_client` | Codebase Intelligence | 7 |
| `CodebaseIntelligenceClient` (Build 2) | `agent_team_v15.codebase_client` | Codebase Intelligence | 7 |
| `ContractEngineClient` (Build 2) | `agent_team_v15.contract_client` | Contract Engine | 6 |
| `ArchitectClient` (Build 2) | `agent_team_v15.mcp_clients` | Architect | 4 |

### 1E.4 Retry and Resilience Patterns

**Common pattern across all clients:**
```python
_MAX_RETRIES = 3
_BACKOFF_BASE = 1  # seconds

for attempt in range(_MAX_RETRIES + 1):
    try:
        result = await session.call_tool(tool_name, params)
        return parse(result)
    except (ConnectionError, OSError, ...) as exc:
        if attempt < _MAX_RETRIES:
            delay = _BACKOFF_BASE * (2 ** attempt)  # 1s, 2s, 4s
            await asyncio.sleep(delay)
```

**Safe defaults:** Every client method returns a safe default (empty dict, empty list, `None`) on exhausted retries -- never raises.

### 1E.5 Session Management

**Build 2 session factories** (in `mcp_clients.py`):
- `create_contract_engine_session(config)` -- async context manager
- `create_codebase_intelligence_session(config)` -- async context manager

**Security (SEC-001):** Only specific env vars passed to MCP subprocesses:
```python
env = {
    "PATH": os.environ.get("PATH", ""),
    "DATABASE_PATH": db_path,
    # Never: os.environ spread (would leak API keys)
}
```

### 1E.6 Fallback Hierarchy

```
MCP Call Attempt (with 3 retries, exponential backoff)
    |
    +--> Success: Use MCP result
    |
    +--> Failure: Use filesystem/heuristic fallback
              |
              +--> WIRE-009: run_api_contract_scan()
              +--> WIRE-010: generate_codebase_map()
              +--> WIRE-011: decompose_prd_basic()
```

All fallback results include `"fallback": True` marker for downstream code to detect degraded mode.

---

## 1F. What Is Currently Missing -- Graph RAG Gap Analysis

### 1F.1 No Cross-Graph Correlation

**Current state:** Three separate data stores exist in isolation:
1. **NetworkX DiGraph** -- file-level dependency graph (imports/calls/inherits/implements/uses)
2. **ChromaDB** -- semantic embeddings of individual code chunks
3. **SQLite** -- structured symbol/contract/service metadata

**Missing:** There is no mechanism to query across these stores in a unified way. For example:
- "Find all services that depend on symbols semantically similar to X" requires manual orchestration of ChromaDB search -> symbol lookup -> graph traversal.
- There is no graph that connects services to their contracts to their code symbols in a single traversable structure.

### 1F.2 No Entity-Relationship Graph

**Current state:** The `DomainModel` from the Architect contains entities and relationships, and the NetworkX graph contains file-level dependencies. But:
- Domain entities are stored as flat JSON in SQLite (`domain_models.data`)
- There is no graph that connects domain entities to their implementing code symbols
- The relationship between "domain model entity `User`" and "symbol `UserService` in `user_service.py`" is not tracked

**Missing:** A unified knowledge graph that connects:
- Domain entities <-> Code symbols (implementation mapping)
- Services <-> Contracts <-> Endpoints (contract coverage)
- Files <-> Services <-> Domain (traceability)

### 1F.3 No Hybrid Search (Graph + Vector)

**Current state:** Semantic search via ChromaDB and structural queries via NetworkX are completely separate.

**Missing:**
- No way to "find code semantically similar to X that is within N hops of Y in the dependency graph"
- No graph-aware re-ranking of semantic search results
- No embedding of graph structural features (centrality, community, path distance) into the vector space
- No retrieval that combines textual relevance with structural importance (PageRank) or proximity

### 1F.4 No Graph-Based Context Window Construction

**Current state:** When the system needs to provide context about a code region, it retrieves individual symbols/chunks via ChromaDB.

**Missing:**
- No mechanism to construct optimal context windows by walking the dependency graph outward from a focal point
- No prioritization of context by graph centrality or call frequency
- No "smart context packing" that maximizes relevant information within a token budget by considering both semantic relevance and structural importance

### 1F.5 No Incremental Graph Update Pipeline

**Current state:** The `IncrementalIndexer` updates the NetworkX graph and ChromaDB when individual files change.

**Missing:**
- No event-driven mechanism to propagate graph changes to downstream consumers
- No change-impact analysis that automatically identifies what queries/embeddings are affected when a node changes
- No incremental re-embedding when graph structure changes (a node's embedding should reflect its structural context, not just its text)

### 1F.6 No Multi-Hop Reasoning Support

**Current state:** Graph traversal is limited to:
- Direct dependencies/dependents (BFS to depth N)
- Simple cycle detection
- PageRank (global, not query-specific)

**Missing:**
- No query-time graph reasoning (e.g., "what is the shortest path from service A's contract to service B's implementation?")
- No subgraph extraction for context (retrieve the relevant neighborhood, not the whole graph)
- No weighted path finding (paths through high-PageRank nodes are more important)
- No community detection for service boundary validation

### 1F.7 No Contract-Code Linkage

**Current state:** Contracts are stored in the Contract Engine (SQLite), code symbols are stored in Codebase Intelligence (SQLite + ChromaDB), but:
- There is no automated mapping from contract endpoints to implementing code
- `ImplementationTracker.mark_implemented()` requires manual evidence paths
- No way to ask "which code implements `GET /api/users`?"

**Missing:** Automated contract-to-code traceability:
- Parse contract endpoints -> find matching route handlers in code graph
- Validate that response schemas match actual return types
- Detect orphaned endpoints (in contract but not in code) and shadow endpoints (in code but not in contract)

### 1F.8 No Temporal/Version Graph

**Current state:** Graph snapshots are stored in SQLite (`graph_snapshots` table) but only the latest is loaded.

**Missing:**
- No temporal graph analysis (how has the dependency structure evolved?)
- No diff between graph versions
- No ability to answer "when did this circular dependency appear?"
- No version-aware contract-code mapping

### 1F.9 No Knowledge Graph Schema

**Current state:** Data is stored in ad-hoc formats:
- NetworkX graph: nodes are strings (file paths), edges have dict attributes
- ChromaDB: flat metadata on embeddings
- SQLite: relational tables per service

**Missing:** A formal ontology or schema for a unified knowledge graph that would define:
- Node types: File, Symbol, Service, Contract, Endpoint, DomainEntity, TestSuite
- Edge types: DEFINES, IMPLEMENTS, IMPORTS, TESTS, EXPOSES, CONSUMES, OWNS
- Property schemas per node/edge type
- Cardinality constraints

### 1F.10 Summary of Graph RAG Opportunities

| Opportunity | Current Gap | Graph RAG Solution |
|-------------|-----------|-------------------|
| Unified knowledge graph | 3 isolated stores | Single graph connecting code, contracts, domain |
| Hybrid search | Separate vector + graph | Graph-aware re-ranking, structural embeddings |
| Smart context windows | Flat retrieval | Graph-walk + token budget optimization |
| Multi-hop reasoning | BFS only | Query-time subgraph extraction + path finding |
| Contract traceability | Manual evidence | Automated endpoint-to-handler mapping |
| Incremental updates | File-level only | Event-driven graph propagation |
| Temporal analysis | Latest snapshot only | Version-diffing, evolution tracking |
| Cross-service analysis | Per-service isolation | Service interaction graph with contract edges |

---

## Appendix A: File Inventory

### Build 1 -- super-team/src/

```
codebase_intelligence/
    main.py                              -- FastAPI app with lifespan
    mcp_server.py                        -- 8 MCP tools (FastMCP)
    mcp_client.py                        -- CI client + WIRE-010 fallback
    services/
        ast_parser.py                    -- Tree-sitter multi-language parsing
        symbol_extractor.py              -- Symbol extraction from ASTs
        import_resolver.py               -- Python/TypeScript import resolution
        graph_builder.py                 -- NetworkX DiGraph builder
        graph_analyzer.py                -- PageRank, cycles, DAG, BFS
        dead_code_detector.py            -- Unreferenced symbol detection
        semantic_indexer.py              -- ChromaDB indexing pipeline
        semantic_searcher.py             -- ChromaDB query pipeline
        incremental_indexer.py           -- 7-step indexing pipeline
        service_interface_extractor.py   -- HTTP endpoint/event extraction
    storage/
        symbol_db.py                     -- SQLite CRUD for symbols
        graph_db.py                      -- Graph snapshot + edge persistence
        chroma_store.py                  -- ChromaDB wrapper
    routers/
        health.py, symbols.py, dependencies.py, search.py, artifacts.py, dead_code.py
    parsers/
        __init__.py, python_parser.py, typescript_parser.py, csharp_parser.py, go_parser.py

architect/
    mcp_server.py                        -- 4 MCP tools
    mcp_client.py                        -- Architect client + WIRE-011 fallback
    services/
        prd_parser.py                    -- Deterministic PRD parsing
        service_boundary.py              -- Bounded context detection
        domain_modeler.py                -- Domain model builder
        contract_generator.py            -- OpenAPI 3.1 stub generator
        validator.py                     -- Decomposition validator
    storage/
        service_map_store.py             -- ServiceMap persistence
        domain_model_store.py            -- DomainModel persistence

contract_engine/
    main.py                              -- FastAPI app
    mcp_server.py                        -- 10 MCP tools
    mcp_client.py                        -- CE client + WIRE-009 fallback
    services/
        contract_store.py                -- Contract CRUD (upsert/get/list)
        breaking_change_detector.py      -- Spec diff analysis
        implementation_tracker.py        -- Implementation evidence tracking
        version_manager.py               -- Version history management
        test_generator.py                -- Schemathesis/jsonschema test generation
        compliance_checker.py            -- Runtime response validation
        openapi_validator.py             -- OpenAPI spec validation
        asyncapi_validator.py            -- AsyncAPI spec validation

integrator/
    compose_generator.py                 -- Docker Compose YAML generation
    contract_compliance.py               -- Schemathesis + Pact facade
    docker_orchestrator.py               -- Docker container management
    service_discovery.py                 -- Service URL discovery
    schemathesis_runner.py               -- Property-based API testing
    pact_manager.py                      -- Consumer-driven contract testing
    traefik_config.py                    -- Traefik label generation
    cross_service_test_generator.py      -- Cross-service test generation
    cross_service_test_runner.py         -- Cross-service test execution
    data_flow_tracer.py                  -- Data flow verification
    boundary_tester.py                   -- Service boundary testing
    fix_loop.py                          -- Integration fix loop
    report.py                            -- Integration report generation

quality_gate/
    gate_engine.py                       -- 4-layer orchestrator
    scan_aggregator.py                   -- Violation aggregation
    layer1_per_service.py                -- Build result evaluation
    layer2_contract_compliance.py        -- Contract test evaluation
    layer3_system_level.py               -- Security/CORS/logging/Docker scanning
    layer4_adversarial.py                -- Advisory analysis
    security_scanner.py                  -- JWT/CORS/secret scanners
    docker_security.py                   -- Dockerfile scanning
    observability_checker.py             -- Logging/tracing checks
    adversarial_patterns.py              -- Dead code/orphan detection
    report.py                            -- Quality gate report generation

shared/
    config.py                            -- pydantic-settings config classes
    constants.py                         -- VERSION, service names
    errors.py                            -- Exception hierarchy + FastAPI handlers
    utils.py                             -- now_iso()
    logging.py                           -- JSON logging + TraceIDMiddleware
    db/
        connection.py                    -- SQLite connection pool (WAL mode)
        schema.py                        -- init_symbols_db, init_architect_db, init_contracts_db
    models/
        codebase.py                      -- SymbolDefinition, ImportReference, etc.
        architect.py                     -- ServiceMap, DomainModel, etc.
        contracts.py                     -- ContractEntry, BreakingChange, etc.
        common.py                        -- Shared utilities

build3_shared/
    constants.py                         -- Phase names, timeouts, 40 scan codes
    models.py                            -- ServiceInfo, BuilderResult, LayerResult, etc.
    protocols.py                         -- PhaseExecutor, QualityScanner protocols
    utils.py                             -- atomic_write_json, load_json, ensure_dir

super_orchestrator/
    pipeline.py                          -- Main orchestration engine
    state_machine.py                     -- 11 states, 13 transitions (AsyncMachine)
    state.py                             -- PipelineState dataclass + JSON persistence
    config.py                            -- SuperOrchestratorConfig + loader
    cost.py                              -- PipelineCostTracker
    exceptions.py                        -- Pipeline error hierarchy
    shutdown.py                          -- GracefulShutdown handler
    cli.py                               -- CLI entry point

run4/
    fix_pass.py                          -- 6-step fix cycle + convergence loop
    builder.py                           -- feed_violations_to_builder
    (+ additional run4 modules)
```

### Build 2 -- agent-team-v15/src/agent_team_v15/

```
codebase_client.py                       -- CodebaseIntelligenceClient (7 MCP tools)
codebase_map.py                          -- Static analysis + MCP-based codebase mapping
contract_client.py                       -- ContractEngineClient (6 MCP tools) + _call_with_retry
contracts.py                             -- Local ContractRegistry + ServiceContractRegistry
mcp_clients.py                           -- Session factories + ArchitectClient
config.py                                -- Full config hierarchy (OrchestratorConfig, etc.)
wiring.py                                -- WIRE-xxx task dependency parsing from TASKS.md
(+ agents.py, orchestrator_reasoning.py, claude_md_generator.py, scheduler.py, etc.)
```

---

## Appendix B: Data Flow Diagram (Text)

```
PRD Text
    |
    v
[Architect MCP Server]
    |--- parse_prd() ---------> ParsedPRD
    |--- identify_boundaries() -> ServiceBoundary[]
    |--- build_service_map() ---> ServiceMap -----> [SQLite: service_maps]
    |--- build_domain_model() --> DomainModel ----> [SQLite: domain_models]
    |--- generate_contracts() --> ContractStubs
    |
    v
[Contract Engine MCP Server]
    |--- create_contract() ----> ContractEntry ---> [SQLite: contracts]
    |--- validate_spec() ------> ValidationResult
    |--- generate_tests() -----> Test Code
    |
    v
[Build 2 Agents / Build 3 Pipeline]
    |--- register_artifact() to [CI MCP Server]
    |
    v
[Codebase Intelligence MCP Server]
    |--- parse AST (tree-sitter) -> Symbols -------> [SQLite: symbols]
    |--- resolve imports ---------> ImportRefs -----> [SQLite: import_references]
    |--- build graph -------------> DiGraph --------> [SQLite: graph_snapshots]
    |                                                  [SQLite: dependency_edges]
    |--- index semantically ------> Embeddings -----> [ChromaDB: code_chunks]
    |
    v
[Quality Gate Engine]
    |--- Layer 1: Per-service build checks
    |--- Layer 2: Contract compliance (Schemathesis + Pact)
    |--- Layer 3: System scanning (40 scan codes)
    |--- Layer 4: Adversarial analysis (advisory)
    |
    v
[Fix Pass Loop]
    |--- DISCOVER -> CLASSIFY -> GENERATE -> APPLY -> VERIFY -> REGRESS
    |--- Convergence check (hard stops + soft convergence)
    |--- Loop until converged or budget/attempts exhausted
```

---

*End of CODEBASE_EXPLORATION.md*

# Codebase Intelligence Service -- Verification Report

> **Agent:** intelligence-verifier
> **Phase:** 1 (Build 1 Verification)
> **Date:** 2026-02-23
> **Scope:** End-to-end verification of the Codebase Intelligence service
> **Files Reviewed:** 30+ source files, 16 test files

---

## Table of Contents

1. [Verification 1: Service Startup and Health](#verification-1-service-startup-and-health)
2. [Verification 2: Indexing Pipeline](#verification-2-indexing-pipeline)
3. [Verification 3: Multi-Language Parsers](#verification-3-multi-language-parsers)
4. [Verification 4: AST Parser Orchestration](#verification-4-ast-parser-orchestration)
5. [Verification 5: Symbol Extractor](#verification-5-symbol-extractor)
6. [Verification 6: Import Resolution](#verification-6-import-resolution)
7. [Verification 7: Graph System](#verification-7-graph-system)
8. [Verification 8: Storage Layer](#verification-8-storage-layer)
9. [Verification 9: Semantic Search](#verification-9-semantic-search)
10. [Verification 10: Dead Code Detection](#verification-10-dead-code-detection)
11. [Verification 11: Service Interface Extraction](#verification-11-service-interface-extraction)
12. [Verification 12: MCP Server Tools](#verification-12-mcp-server-tools)
13. [Verification 13: MCP Client](#verification-13-mcp-client)
14. [Verification 14: Graph Persistence and Reload](#verification-14-graph-persistence-and-reload)
15. [Verification 15: Existing Tests](#verification-15-existing-tests)
16. [Bug Summary](#bug-summary)
17. [ChromaDB Embedding Model Analysis](#chromadb-embedding-model-analysis)
18. [Graph Persistence Correctness Analysis](#graph-persistence-correctness-analysis)
19. [Missing Test Coverage](#missing-test-coverage)
20. [MCP Tool Signatures](#mcp-tool-signatures)
21. [HTTP Endpoint Shapes](#http-endpoint-shapes)

---

## Verification 1: Service Startup and Health

**Status: ISSUE -- Graph snapshot NOT saved on teardown**

### Lifespan Initialization (15 Components)

The lifespan in `src/codebase_intelligence/main.py` (lines 46-111) initializes components in this order:

| # | Component | Line | Constructor Args | Status |
|---|-----------|------|-----------------|--------|
| 1 | `ConnectionPool` | 53 | `config.database_path` | PASS |
| 2 | `init_symbols_db(pool)` | 54 | pool | PASS |
| 3 | `SymbolDB(pool)` | 58 | pool | PASS |
| 4 | `GraphDB(pool)` | 59 | pool | PASS |
| 5 | `ChromaStore(config.chroma_path)` | 60 | chroma_path | PASS |
| 6 | `graph_db.load_snapshot()` | 66 | -- | PASS |
| 7 | `GraphBuilder(graph=existing_graph)` | 67 | existing snapshot | PASS |
| 8 | `GraphAnalyzer(graph_builder.graph)` | 68 | graph ref | PASS |
| 9 | `ASTParser()` | 73 | -- | PASS |
| 10 | `SymbolExtractor()` | 74 | -- | PASS |
| 11 | `ImportResolver()` | 75 | -- | PASS |
| 12 | `DeadCodeDetector(graph_builder.graph)` | 76 | graph ref | PASS |
| 13 | `SemanticIndexer(chroma_store, symbol_db)` | 83 | chroma, db | PASS |
| 14 | `SemanticSearcher(chroma_store)` | 84 | chroma | PASS |
| 15 | `ServiceInterfaceExtractor(ast_parser, symbol_extractor)` | 89 | parser, extractor | PASS |
| -- | `IncrementalIndexer(...)` | 93-101 | 7 deps | PASS |

**Order correctness:** The initialization order is correct. ConnectionPool and schema are created first, then storage layer (SymbolDB, GraphDB, ChromaStore), then the graph is loaded from snapshot before GraphBuilder and GraphAnalyzer are created. Core services follow, and IncrementalIndexer (the orchestrator) is constructed last with all dependencies.

### Lifespan Teardown

**BUG FOUND: Graph snapshot is NOT saved on teardown.**

At `main.py:108-111`, the teardown block is:
```python
yield

pool.close()
logger.info("Service stopped: name=%s", CODEBASE_INTEL_SERVICE_NAME)
```

The ARCHITECTURE_REPORT.md states: "Lifespan teardown: saves graph snapshot, closes pool." However, the actual code does **NOT** call `graph_db.save_snapshot(graph_builder.graph)` before closing the pool. This means that any graph updates made during the service's lifetime will be lost on restart unless separately persisted.

**Severity:** HIGH -- Graph state accumulated during runtime is lost on shutdown.

**Fix:** Add `graph_db.save_snapshot(graph_builder.graph)` before `pool.close()` in the teardown.

### Health Endpoint

**Status: PASS**

`src/codebase_intelligence/routers/health.py` (lines 17-58):
- Checks SQLite via `pool.get().execute("SELECT 1")`
- Checks ChromaDB via `chroma_store.get_stats()`
- Reports `chroma_chunks` count and `chroma` connection status in `details`
- Returns `HealthStatus` with `status="healthy"` when DB is connected, `"degraded"` otherwise
- Runs in `asyncio.to_thread` to avoid blocking the event loop

---

## Verification 2: Indexing Pipeline

**Status: PASS**

### Full 7-Step Pipeline

`src/codebase_intelligence/services/incremental_indexer.py` (lines 51-158):

| Step | Action | Lines | Status |
|------|--------|-------|--------|
| 1 | Detect language from extension | 85-92 | PASS |
| 2 | Parse AST with tree-sitter | 104-106 | PASS |
| 3 | Extract typed symbols | 109-111 | PASS |
| 4 | Resolve imports | 114-116 | PASS |
| 5 | Update dependency graph | 119-121 | PASS |
| 6 | Persist to SQLite | 124-127 | PASS |
| 7 | Semantic indexing (embeddings) | 130-142 | PASS |

### register_artifact MCP Tool Trigger

`mcp_server.py:139-178` -- The `register_artifact` tool (internally `index_file`) calls `_incremental_indexer.index_file(...)`, which runs the full 7-step pipeline. Supports both disk-read and base64-encoded source.

### Duplicate Prevention on Re-registration

`storage/symbol_db.py:59-67` -- Uses `INSERT OR REPLACE INTO indexed_files` which overwrites the existing row by primary key (`file_path`). Symbols use `INSERT OR REPLACE INTO symbols` keyed by `id` (`file_path::symbol_name`). Import references use `INSERT OR REPLACE INTO import_references` with `UNIQUE(source_file, target_file, line)`. GraphBuilder's `add_file()` first calls `remove_file()` to delete all existing edges before adding new ones.

**Deduplication is correctly handled at all three levels: files, symbols, and graph edges.**

---

## Verification 3: Multi-Language Parsers

**Status: PASS**

### Python Parser (`parsers/python_parser.py`)

- Uses `tree_sitter_python.language()` with `Language()`, `Parser(lang)`, `Query(lang, pattern)`, `QueryCursor(query).matches(node)` -- correct 0.25.2 API
- Extracts: CLASS, FUNCTION, METHOD
- Handles: decorated definitions (deduplication via `seen_ranges`), docstrings, signatures (`def name(params) -> return_type`), class signatures with superclasses
- Export detection: `not name.startswith("_")`
- Parent symbol: walks tree upward to find enclosing class

### TypeScript Parser (`parsers/typescript_parser.py`)

- Uses `tree_sitter_typescript.language_typescript()` for `.ts`, `language_tsx()` for `.tsx`
- Extracts: INTERFACE, TYPE, CLASS, FUNCTION, METHOD, VARIABLE
- Handles: JSDoc comments, export detection (checks `export_statement` parent), meaningful variable filtering
- Uses `Parser(lang)` per-parse call (creates new parser each time, not cached -- minor performance concern but correct)

### C# Parser (`parsers/csharp_parser.py`)

- Uses `tree_sitter_c_sharp.language()` with correct 0.25.2 API
- Extracts: CLASS, INTERFACE, ENUM, METHOD (structs mapped to CLASS)
- Handles: XML doc comments (`///`), public modifier detection, namespace-based service_name inference
- Parent symbol: walks tree for enclosing class/struct

### Go Parser (`parsers/go_parser.py`)

- Uses `tree_sitter_go.language()` with correct 0.25.2 API
- Extracts: FUNCTION, METHOD (with receiver type as parent_symbol), CLASS (struct), INTERFACE
- Type classification: inspects `type_spec` children for `struct_type`/`interface_type`
- Handles: Go doc comments (`//` and `/* */`), export detection via uppercase first letter
- Receiver type extraction: handles both value `(r ReceiverType)` and pointer `(r *ReceiverType)` receivers

### tree-sitter 0.25.2 API Compliance

All four parsers use the correct API pattern:
```python
Language(tree_sitter_xxx.language())  # NOT the old ts.Language.build_library pattern
Parser(lang)                          # NOT Parser(); parser.set_language(lang)
Query(lang, pattern)                  # Correct
QueryCursor(query).matches(node)      # Correct (returns pattern_idx, captures_dict)
```

**All parsers correctly access `.text` as `bytes` and decode with `.decode()`.** This matches tree-sitter 0.25.2 where `node.text` returns `bytes`.

---

## Verification 4: AST Parser Orchestration

**Status: PASS**

`src/codebase_intelligence/services/ast_parser.py` (129 lines):

- **Language detection** (`detect_language`, line 55-59): Maps file extensions via `_EXTENSION_MAP` (`.py`, `.pyi`, `.ts`, `.tsx`, `.cs`, `.go`)
- **Delegation** (`_extract_symbols`, line 106-116): Routes to `PythonParser`, `TypeScriptParser`, `CSharpParser`, or `GoParser` based on language string
- **TSX handling** (line 83-84): Correctly selects `tsx` language key for `.tsx` files
- **Error handling**: Raises `ParsingError` for unsupported extensions; catches `ValueError`/`RuntimeError` from parsers and wraps them as `ParsingError`
- **Parse tree warning** (line 90-91): Logs a warning if `tree.root_node.has_error` is true

---

## Verification 5: Symbol Extractor

**Status: PASS**

`src/codebase_intelligence/services/symbol_extractor.py` (101 lines):

### Field Mapping

| Raw Parser Key | SymbolDefinition Field | Mapping |
|---------------|----------------------|---------|
| `raw["name"]` | `symbol_name` | Direct |
| -- | `file_path` | Passed as parameter |
| `raw["kind"]` | `kind` | Via `_map_kind()` (handles both `SymbolKind` enum and string) |
| -- | `language` | Passed as parameter, mapped via `_map_language()` |
| -- | `service_name` | Passed as parameter, falls back to `raw.get("service_name")` |
| `raw["line_start"]` | `line_start` | Direct |
| `raw["line_end"]` | `line_end` | Direct |
| `raw.get("signature")` | `signature` | Optional |
| `raw.get("docstring")` | `docstring` | Optional |
| `raw.get("is_exported", True)` | `is_exported` | Defaults to True |
| `raw.get("parent_symbol")` | `parent_symbol` | Optional |

**Note:** The `id` field is auto-generated by the `SymbolDefinition` model validator as `{file_path}::{symbol_name}` (see `src/shared/models/codebase.py:56-63`).

**Error handling:** Each symbol conversion is wrapped in a try/except that logs a warning and skips invalid symbols without failing the entire batch.

---

## Verification 6: Import Resolution

**Status: PASS**

`src/codebase_intelligence/services/import_resolver.py` (603 lines):

### Python Import Resolution

- **Absolute imports** (`import os, import os.path`): Extracts dotted names, converts to file paths via `_py_module_to_path()` which tries `<module>.py` first, then `<module>/__init__.py` if project_root is set and the package exists on disk
- **From imports** (`from x.y import z`): Extracts module name and dot count via `_py_from_module_name()`, handles both `relative_import` and `import_prefix` node types
- **Relative imports** (`from ..models import User`): Resolves via `_py_resolve_relative()` which walks up directories based on dot count and tries `.py` then `__init__.py`
- **Aliased imports** (`import os.path as osp`): Correctly extracts the original module name from `aliased_import` nodes
- **Wildcard imports** (`from x import *`): Records `"*"` in imported_names

### TypeScript Import Resolution

- **Relative imports** (`import { X } from './utils'`): Tries extensions `.ts`, `.tsx`, `.js`, `.jsx` and index files
- **tsconfig paths** (`import { X } from '@/utils'`): Loads `tsconfig.json` paths, supports wildcard patterns (`"@/*": ["src/*"]`)
- **Package imports** (`import express from 'express'`): Recorded as-is (the module specifier becomes the target_file)
- **Named imports** (`import { A, B } from ...`): Extracts individual names from `named_imports` -> `import_specifier` nodes
- **Namespace imports** (`import * as ns from ...`): Extracts the alias name

### Language Detection

Supports: `.py`, `.pyi` (Python), `.ts`, `.tsx`, `.js`, `.jsx`, `.mts`, `.cts` (TypeScript). Returns `"unknown"` for unsupported extensions.

**Note:** C# and Go import resolution is not implemented. The resolver returns an empty list for unknown languages. This is a design choice, not a bug -- C# uses `using` directives and Go uses package imports, which have different resolution semantics.

---

## Verification 7: Graph System

**Status: PASS**

### GraphBuilder (`services/graph_builder.py`, 154 lines)

- **Data structure:** `nx.DiGraph` with file paths as node IDs
- **From ImportReference:** Adds edge from `source_file` to `target_file` with `relation="imports"` and `line` attribute
- **From DependencyEdge:** Adds edge with `relation` (enum value), `source_symbol`, `target_symbol`, and `line` attributes
- **Incremental update** (`add_file`, line 85-141): First calls `remove_file()` to remove all existing edges from/to the file, then adds the file node with metadata and creates new edges
- **Remove** (`remove_file`, line 143-153): Removes all successor and predecessor edges (does NOT remove the node itself, which could leave orphaned nodes -- minor issue but not a bug since the node gets metadata updated in `add_file`)

### GraphAnalyzer (`services/graph_analyzer.py`, 151 lines)

- **PageRank** (line 53-58): `nx.pagerank()`, sorted descending, top 10
- **Cycle detection** (line 43-48): `nx.simple_cycles()`, limited to 20 cycles
- **Topological sort** (line 68-73): Only when `is_dag=True`
- **Connected components** (line 62-65): `nx.number_weakly_connected_components()`
- **BFS for dependencies** (line 86-116): Correct breadth-first traversal with depth limit
- **BFS for dependents** (line 118-143): Correct reverse BFS with depth limit

### Graph Consistency

The GraphBuilder maintains consistency by:
1. Using `add_file()` which removes old edges before adding new ones (prevents stale edges)
2. Storing metadata (`language`, `service_name`) on file nodes
3. Creating target nodes on-the-fly if they don't exist

**ISSUE:** `remove_file()` removes edges but not the node itself. This means orphaned nodes can accumulate if a file is deleted from the index without being re-indexed. However, this is a minor issue since `add_file()` re-adds the node with updated metadata.

---

## Verification 8: Storage Layer

**Status: PASS**

### SymbolDB (`storage/symbol_db.py`, 270 lines)

- **CRUD for indexed_files:** `save_file()` uses `INSERT OR REPLACE` keyed on `file_path` (primary key)
- **CRUD for symbols:** `save_symbols()` uses `INSERT OR REPLACE` keyed on `id` (`file_path::symbol_name`)
- **CRUD for import_references:** `save_imports()` uses `INSERT OR REPLACE` with `UNIQUE(source_file, target_file, line)`
- **Query methods:** `query_by_name()` supports optional `kind` filter, `query_by_file()` returns all symbols in a file
- **Chroma back-link:** `update_chroma_id()` sets the `chroma_id` column for a symbol
- **Deletion:** `delete_by_file()` removes from `indexed_files` (cascades to symbols and import_references via FK) and explicitly cleans up `dependency_edges`
- **Symbol deduplication on re-index:** `INSERT OR REPLACE` handles this correctly -- re-indexing the same file overwrites existing symbols

### GraphDB (`storage/graph_db.py`, 174 lines)

- **Edge storage:** `save_edges()` uses `INSERT OR REPLACE` with `UNIQUE(source_symbol_id, target_symbol_id, relation)`
- **Graph snapshot format:** `nx.node_link_data(graph, edges="edges")` for save, `nx.node_link_graph(data, edges="edges")` for load -- **correct and consistent**
- **Snapshot retrieval:** Loads the most recent snapshot by `ORDER BY id DESC LIMIT 1`

### ChromaStore (`storage/chroma_store.py`, 188 lines)

- **Client:** `chromadb.PersistentClient(path=chroma_path)` -- persistent storage
- **Collection:** `"code_chunks"` with `metadata={"hnsw:space": "cosine"}`
- **Embedding function:** `DefaultEmbeddingFunction()` -- this is ChromaDB's built-in default which uses `all-MiniLM-L6-v2` with ONNX backend
- **Chunk IDs:** Generated as `{file_path}::{symbol_name or ""}`
- **Metadata handling:** None values converted to empty strings (ChromaDB requirement)
- **Deletion:** `delete_by_file()` uses `where={"file_path": file_path}` filter

---

## Verification 9: Semantic Search

**Status: PASS**

### SemanticIndexer (`services/semantic_indexer.py`, 139 lines)

- Creates `CodeChunk` objects from `SymbolDefinition` instances by extracting source lines
- Line range clamping: `start = max(symbol.line_start, 1)`, `end = min(symbol.line_end, total_lines)`
- Skips symbols with `line_start > total_lines` (out of range) or empty content
- Stores chunks via `ChromaStore.add_chunks()`
- Back-links via `SymbolDB.update_chroma_id(chunk.id, chunk.id)`
- Chunk ID format: `{file_path}::{symbol_name}`

### SemanticSearcher (`services/semantic_searcher.py`, 166 lines)

- **Language filter:** `{"language": value}` when only language is provided
- **Service name filter:** `{"service_name": value}` when only service_name is provided
- **Combined filters:** `{"$and": [{"language": ...}, {"service_name": ...}]}` when both are provided
- **top_k handling:** Passed directly as `n_results` to `ChromaStore.query()`
- **Score conversion:** `max(0.0, min(1.0, 1.0 - distance))` -- correctly clamped to [0, 1]
- **Empty string restoration:** Converts `""` back to `None` for `symbol_name` and `service_name`
- **Error handling:** Catches `ValueError` and `RuntimeError` from ChromaDB, returns empty list

### MCP n_results to top_k Mapping

`mcp_server.py:181-214` -- The `search_semantic` MCP tool accepts `n_results: int = 10` and passes it as `top_k=n_results` to `SemanticSearcher.search()`. This mapping is correct and matches the SVC-010 contract.

---

## Verification 10: Dead Code Detection

**Status: PASS**

`src/codebase_intelligence/services/dead_code_detector.py` (186 lines):

### Confidence Classification

| Confidence | Condition |
|-----------|-----------|
| **high** | Default -- symbol is never referenced and has no special role |
| **medium** | Methods (could be used via polymorphism), interfaces/types (used for type checking) |
| **low** | Names starting with `on_`, `handle_`, `process_`, `do_`; top-level functions starting with `get_`, `post_`, `put_`, `delete_`, `create_`, `update_` |

### Entry Point Exclusion

Correctly excludes:
- Lifecycle methods: `__init__`, `__str__`, `setUp`, `tearDown`, `startup`, `shutdown`, `lifespan`, `constructor`, `render`, `ngOnInit`, `Init`, `Main`, `Dispose`, `ConfigureServices`, etc. (40+ methods)
- Entry point patterns: `^main$`, `^__main__$`, `^test_`, `^Test`, `_test$`
- Dunder methods: `__xxx__`
- `__main__.py` files

### Dead Code Identification Logic

1. For each symbol, check if it's an entry point (skip if yes)
2. Skip non-exported (private) symbols
3. Check if `symbol.id` is in the `referenced_symbols` set (skip if referenced)
4. If not referenced, assess confidence level
5. Build a `DeadCodeEntry` with symbol metadata

The `_build_reference_set()` method traverses graph edges to find `target_symbol` and `source_symbol` IDs from edge data. This is correct for finding graph-level references.

---

## Verification 11: Service Interface Extraction

**Status: PASS**

`src/codebase_intelligence/services/service_interface_extractor.py` (1279 lines):

### Framework Support

| Language | Framework | Detection Pattern | Status |
|----------|-----------|-------------------|--------|
| Python | FastAPI | `@app.get("/path")`, `@router.post("/path")` | PASS |
| Python | Flask | `@app.route("/path", methods=["GET"])` | PASS |
| TypeScript | Express | `app.get("/path", handler)` | PASS |
| TypeScript | NestJS | `@Get("/path")`, `@Post("/path")` | PASS |
| C# | ASP.NET | `[HttpGet]`, `[HttpPost]`, `[Route]` | PASS |
| Go | net/http | `http.HandleFunc("/path", handler)` | PASS |

### Event Pattern Detection

- **Python publish:** `emit`, `publish`, `send`, `send_event`, `dispatch`, `produce`
- **Python consume:** `on`, `subscribe`, `consume`, `listen`, `handle`, `on_event`
- **TypeScript publish:** `emit`, `publish`, `send`, `dispatch`, `produce`
- **TypeScript consume:** `on`, `subscribe`, `addEventListener`, `consume`, `listen`

### Extraction Flow

1. Parse file with `ASTParser.parse_file()` to get tree and raw symbols
2. Walk AST to detect endpoint patterns based on language
3. Walk AST to detect event publish/subscribe patterns
4. Convert raw symbols to `SymbolDefinition` via `SymbolExtractor`, filter to exported only
5. Return `ServiceInterface` with all four lists

---

## Verification 12: MCP Server Tools

**Status: PASS (all 8 tools verified)**

`src/codebase_intelligence/mcp_server.py` (511 lines):

### Tool 1: `register_artifact`

```python
@mcp.tool(name="register_artifact")
def index_file(
    file_path: str,
    service_name: str | None = None,
    source_base64: str | None = None,
    project_root: str | None = None,
) -> dict[str, Any]
```

**Returns:** `{"indexed": bool, "symbols_found": int, "dependencies_found": int, "errors": list[str]}`
**Note:** Parameter name differs from architecture spec -- uses `source_base64` instead of `source`. The MCP client also uses `source_base64`.

### Tool 2: `search_semantic`

```python
@mcp.tool(name="search_semantic")
def search_code(
    query: str,
    language: str | None = None,
    service_name: str | None = None,
    n_results: int = 10,
) -> list[dict[str, Any]]
```

**Returns:** List of `SemanticSearchResult.model_dump(mode="json")` dicts
**Mapping:** `n_results` -> `top_k` internally

### Tool 3: `find_definition`

```python
@mcp.tool(name="find_definition")
def find_definition(
    symbol: str,
    language: str | None = None,
) -> dict[str, Any]
```

**Returns:** `{"file": str, "line": int, "kind": str, "signature": str}` or `{"error": str}`
**Note:** Parameter is `symbol` (not `symbol_name`), and `language` is used as a filter (not `kind`). The architecture spec listed `kind?` as a parameter, but the implementation uses `language?` instead.

### Tool 4: `find_dependencies`

```python
@mcp.tool(name="find_dependencies")
def get_dependencies(
    file_path: str,
    depth: int = 1,
    direction: str = "both",
) -> dict[str, Any]
```

**Returns:** `{"imports": list, "imported_by": list, "transitive_deps": list, "circular_deps": list[list[str]]}`
**Note:** Has extra `direction` parameter not in the architecture spec (harmless addition).

### Tool 5: `analyze_graph`

```python
@mcp.tool()
def analyze_graph() -> dict[str, Any]
```

**Returns:** `GraphAnalysis.model_dump(mode="json")` -- `{"node_count", "edge_count", "is_dag", "circular_dependencies", "top_files_by_pagerank", "connected_components", "build_order"}`

### Tool 6: `check_dead_code`

```python
@mcp.tool(name="check_dead_code")
def detect_dead_code(
    service_name: str | None = None,
) -> list[dict[str, Any]]
```

**Returns:** List of `DeadCodeEntry.model_dump(mode="json")` dicts

### Tool 7: `find_callers`

```python
@mcp.tool(name="find_callers")
def find_callers(
    symbol: str,
    max_results: int = 50,
) -> list[dict[str, Any]]
```

**Returns:** List of `{"file_path": str, "line": int, "caller_symbol": str}`
**Note:** Parameter name is `symbol` (matching `find_definition`). Architecture spec listed `file_path` as parameter, but the implementation uses `symbol` -- this is a parameter name mismatch with the spec but is internally consistent.

### Tool 8: `get_service_interface`

```python
@mcp.tool(name="get_service_interface")
def get_service_interface(
    service_name: str,
) -> dict[str, Any]
```

**Returns:** `{"service_name": str, "endpoints": list, "events_published": list, "events_consumed": list, "exported_symbols": list}`
**Note:** Architecture spec listed `file_path` and `service_name` as parameters, but the implementation only takes `service_name`. The implementation queries all indexed files for the service and aggregates interfaces. This is a design deviation from the spec but is functionally correct (and arguably better since it returns the full service interface, not just one file).

### MCP Tool Count

Verified: exactly 8 tools registered. Test `test_mcp_tool_count_is_8` confirms this.

---

## Verification 13: MCP Client

**Status: PASS**

`src/codebase_intelligence/mcp_client.py` (391 lines):

### CodebaseIntelligenceClient Methods

| Method | MCP Tool Called | Params Sent | Safe Default |
|--------|----------------|------------|--------------|
| `find_definition(symbol, language?)` | `find_definition` | `{"symbol": ..., "language"?: ...}` | `{}` |
| `find_callers(symbol, max_results?)` | `find_callers` | `{"symbol": ..., "max_results": ...}` | `[]` |
| `find_dependencies(file_path, depth?, direction?)` | `find_dependencies` | `{"file_path": ..., "depth": ..., "direction": ...}` | `{}` |
| `search_semantic(query, language?, service_name?, n_results?)` | `search_semantic` | `{"query": ..., "n_results": ..., ...}` | `[]` |
| `get_service_interface(service_name)` | `get_service_interface` | `{"service_name": ...}` | `{}` |
| `check_dead_code(service_name?)` | `check_dead_code` | `{"service_name"?: ...}` | `[]` |
| `register_artifact(file_path, service_name?, source_base64?, project_root?)` | `register_artifact` (implied, uses `_call_tool`) | `{"file_path": ..., ...}` | `{}` |

### WIRE-010 Fallback

`generate_codebase_map(project_root)` -- Filesystem-based fallback that walks directories, collects source files, and returns a dict with `file_path`, `language`, `size_bytes` for each file. Skips hidden dirs, `node_modules`, `__pycache__`, `.venv`, `venv`.

`get_codebase_map_with_fallback(project_root, client?)` -- Tries CI MCP first via `get_service_interface("__healthcheck__")`, falls back to `generate_codebase_map()` on failure. Sets `"fallback": True` flag in the result.

### Retry Pattern

3 retries, base 1s exponential backoff: delays of 1s, 2s, 4s. Returns `None` on exhausted retries, which is converted to the safe default by `_parse_result()`.

---

## Verification 14: Graph Persistence and Reload

**Status: ISSUE -- Incomplete cycle (missing save on teardown)**

### Expected Cycle

1. IncrementalIndexer updates GraphBuilder via `graph_builder.add_file()` -- **PASS**
2. Lifespan teardown calls `graph_db.save_snapshot(graph_builder.graph)` -- **FAIL (NOT IMPLEMENTED)**
3. On restart, lifespan loads snapshot via `graph_db.load_snapshot()` -- **PASS** (line 66)
4. GraphBuilder reconstructs from snapshot -- **PASS** (line 67)

### Detailed Analysis

- **Step 1:** `IncrementalIndexer.index_file()` calls `self._graph_builder.add_file(file_path, imports, ...)` at line 119-121. This correctly updates the in-memory NetworkX DiGraph.

- **Step 2:** The lifespan teardown (`main.py:108-111`) only calls `pool.close()` and logs a message. It does **NOT** call `graph_db.save_snapshot()`. This is the same bug identified in Verification 1.

- **Step 3:** The lifespan startup (`main.py:66`) correctly calls `graph_db.load_snapshot()` which reads the most recent `graph_snapshots` row and deserializes via `nx.node_link_graph(data, edges="edges")`.

- **Step 4:** The loaded snapshot (or `None`) is passed to `GraphBuilder(graph=existing_graph)` which uses it as the initial graph or creates an empty DiGraph if None.

### GraphDB Snapshot Format

- **Save:** `nx.node_link_data(graph, edges="edges")` -> JSON string (lines 76-77 of `graph_db.py`)
- **Load:** `json.loads(row["graph_json"])` -> `nx.node_link_graph(data, edges="edges")` (lines 110-111 of `graph_db.py`)
- The `edges="edges"` parameter is consistent between save and load.

### Impact of Missing Save

The graph snapshot is never saved during normal operation. The only way it could be saved is if external code explicitly calls `graph_db.save_snapshot()`. The `IncrementalIndexer` does call `self._graph_db.save_edges([])` (with an empty list) but this only writes to the `dependency_edges` table, not the `graph_snapshots` table. Therefore, the in-memory graph state is always lost on restart.

---

## Verification 15: Existing Tests

**Status: PASS (comprehensive coverage with identified gaps)**

### Test File Inventory (16 files)

| Test File | Module Tested | Test Count (approx) |
|-----------|--------------|---------------------|
| `test_ast_parser.py` | ASTParser | ~10 |
| `test_python_parser.py` | PythonParser | ~15 |
| `test_typescript_parser.py` | TypeScriptParser | ~12 |
| `test_csharp_parser.py` | CSharpParser | ~10 |
| `test_go_parser.py` | GoParser | ~10 |
| `test_symbol_extractor.py` | SymbolExtractor | ~8 |
| `test_import_resolver.py` | ImportResolver | ~12 |
| `test_graph_builder.py` | GraphBuilder | ~8 |
| `test_graph_analyzer.py` | GraphAnalyzer | ~10 |
| `test_dead_code_detector.py` | DeadCodeDetector | ~8 |
| `test_semantic_indexer.py` | SemanticIndexer | ~20 |
| `test_semantic_searcher.py` | SemanticSearcher | ~15 |
| `test_incremental_indexer_m6.py` | IncrementalIndexer | ~10 |
| `test_routers.py` | All HTTP routers | ~15 |
| `test_performance.py` | Performance benchmarks | ~5 |
| `test_codebase_intel_mcp.py` | MCP server tools | ~25 |

### ChromaDB Mocking Strategy

- **MCP tests** (`test_codebase_intel_mcp.py`): Creates real `ChromaStore` with `tmp_path` -- uses actual ChromaDB PersistentClient with temporary directory. This is a true integration test that validates the embedding pipeline.
- **Router tests** (`test_routers.py`): Uses `MagicMock` for all `app.state` dependencies including `chroma_store` and `semantic_searcher`. Pure unit tests.
- **Semantic tests** (`test_semantic_indexer.py`, `test_semantic_searcher.py`): Uses `MagicMock` for `ChromaStore`. Tests the logic without actual embeddings.

### Coverage Gaps Identified

See [Missing Test Coverage](#missing-test-coverage) section below.

---

## Bug Summary

| # | Severity | Location | Description |
|---|----------|----------|-------------|
| **B-001** | **HIGH** | `src/codebase_intelligence/main.py:108-111` | Graph snapshot NOT saved on lifespan teardown. In-memory graph state is lost on every restart. |
| **B-002** | LOW | `src/codebase_intelligence/mcp_server.py:218-220` | `find_definition` parameter is `symbol` but architecture spec says `symbol_name` and `kind?`. The `kind` filter is not available; only `language` filter exists. |
| **B-003** | LOW | `src/codebase_intelligence/mcp_server.py:374-375` | `find_callers` parameter is `symbol` (name string), but architecture spec says `file_path`. The implementation queries by symbol name, not file path. |
| **B-004** | LOW | `src/codebase_intelligence/mcp_server.py:433-434` | `get_service_interface` only takes `service_name`, but architecture spec says it takes both `file_path` and `service_name`. |
| **B-005** | INFO | `src/codebase_intelligence/services/incremental_indexer.py:127` | `graph_db.save_edges([])` is called with an empty list on every index operation. This is a no-op that wastes a database call. |
| **B-006** | INFO | `src/codebase_intelligence/services/graph_builder.py:143-153` | `remove_file()` removes edges but not the node, potentially leaving orphaned nodes in the graph. |

---

## ChromaDB Embedding Model Analysis

### Model: `all-MiniLM-L6-v2`

- **Usage:** `ChromaStore` uses `DefaultEmbeddingFunction()` from `chromadb.utils.embedding_functions` (line 8 and 32 of `chroma_store.py`)
- **ChromaDB's DefaultEmbeddingFunction:** This wraps `sentence-transformers/all-MiniLM-L6-v2` using the ONNX runtime for CPU inference. It is bundled with ChromaDB and does NOT require a separate model download when ONNX Runtime is installed.
- **Docker consideration:** The Codebase Intelligence Dockerfile pre-downloads the ONNX model at build time to avoid runtime downloads (per architecture report section 1B.8).
- **Embedding dimensions:** 384 (MiniLM-L6-v2 output)
- **Distance metric:** Cosine (configured via `metadata={"hnsw:space": "cosine"}` at line 36 of `chroma_store.py`)
- **Availability:** The model is available via the `onnxruntime` package which is a ChromaDB dependency. No external API calls are needed.

### Performance Characteristics

- Local ONNX inference -- no network latency
- ~1-5ms per embedding on modern CPUs
- 384-dim vectors -- moderate storage footprint
- Cosine distance -- appropriate for semantic code similarity

### Risk Assessment

- **LOW RISK:** The model is bundled with ChromaDB. No external service dependency.
- **Potential issue:** First-time initialization may be slow if the ONNX model needs to be downloaded. The Dockerfile mitigates this by pre-downloading.
- **Memory:** ONNX model uses ~50-100MB RAM. Within the 768MB container limit.

---

## Graph Persistence Correctness Analysis

### Current State: PARTIALLY CORRECT

The graph persistence mechanism has two parts:

1. **Snapshot save/load in GraphDB:** The `save_snapshot()` and `load_snapshot()` methods correctly use `nx.node_link_data(graph, edges="edges")` / `nx.node_link_graph(data, edges="edges")`. The serialization format is JSON-compatible and correctly round-trips the full graph structure (nodes, edges, attributes).

2. **Lifespan integration:** The load on startup works correctly. The save on teardown is **MISSING** (Bug B-001). This means:
   - Any graph state accumulated during runtime is lost on shutdown
   - The `graph_snapshots` table will only contain snapshots saved by external code
   - On restart, the service may load a stale or empty graph

### Workaround

The MCP server module (`mcp_server.py`) creates its own independent set of instances (lines 62-94), including its own `GraphBuilder` and `GraphDB`. This is a separate lifecycle from the FastAPI lifespan. The MCP server does NOT save snapshots either.

### Edge Storage vs Snapshot Storage

- `dependency_edges` table: Stores individual edges via `GraphDB.save_edges()`. However, `IncrementalIndexer` always calls `save_edges([])` (empty list), so this table is never populated by the indexing pipeline. The edge information lives only in the in-memory NetworkX graph.
- `graph_snapshots` table: Designed to store full graph serialization. Never written to during normal operation due to Bug B-001.

### Recommendation

Add to `main.py` lifespan teardown:
```python
yield

# Save graph snapshot before closing
try:
    graph_db.save_snapshot(graph_builder.graph)
    logger.info("Graph snapshot saved: %d nodes, %d edges",
                graph_builder.graph.number_of_nodes(),
                graph_builder.graph.number_of_edges())
except Exception:
    logger.exception("Failed to save graph snapshot on shutdown")

pool.close()
```

---

## Missing Test Coverage

### Critical Gaps

| Area | Missing Coverage | Priority |
|------|-----------------|----------|
| **Graph snapshot save/load cycle** | No test verifies that `save_snapshot` -> `load_snapshot` produces an equivalent graph | HIGH |
| **Lifespan teardown** | No test verifies the full lifespan init/teardown (would catch B-001) | HIGH |
| **MCP client methods** | `CodebaseIntelligenceClient` methods have no unit tests | MEDIUM |
| **WIRE-010 fallback** | `generate_codebase_map()` and `get_codebase_map_with_fallback()` have no tests | MEDIUM |
| **ServiceInterfaceExtractor** | No dedicated test file for this 1279-line module | MEDIUM |
| **Import resolver: C#/Go** | No import resolution for C#/Go (by design), but no test verifies the graceful fallback | LOW |
| **ChromaStore integration** | No test for `delete_by_file()` or `get_stats()` in isolation | LOW |
| **SymbolDB deletion** | `delete_by_file()` cascade behavior not tested | LOW |

### Existing Coverage Strengths

- **Parser coverage:** All 4 language parsers have dedicated test files
- **MCP tool coverage:** All 8 MCP tools are tested via `test_codebase_intel_mcp.py`
- **Router coverage:** All HTTP endpoints tested via `test_routers.py` with mock app.state
- **Semantic pipeline:** Both SemanticIndexer and SemanticSearcher have thorough tests
- **IncrementalIndexer:** Step 7 (semantic indexing) integration well-covered including error handling
- **Dead code detector:** Confidence levels and entry point exclusion tested

### Test Infrastructure Notes

- Tests use `pytest` with `asyncio_mode = "auto"`
- ChromaDB in MCP tests uses real `PersistentClient` with `tmp_path` (true integration)
- Router tests use FastAPI `TestClient` with fully mocked `app.state`
- Semantic tests mock `ChromaStore` to avoid actual embedding computation

---

## MCP Tool Signatures

### Complete Signature Table

| # | Tool Name | Parameters | Return Type | Error Shape |
|---|-----------|-----------|------------|-------------|
| 1 | `register_artifact` | `file_path: str`, `service_name: str\|None`, `source_base64: str\|None`, `project_root: str\|None` | `dict` (`indexed`, `symbols_found`, `dependencies_found`, `errors`) | `{"error": str}` |
| 2 | `search_semantic` | `query: str`, `language: str\|None`, `service_name: str\|None`, `n_results: int = 10` | `list[dict]` (SemanticSearchResult shape) | `[{"error": str}]` |
| 3 | `find_definition` | `symbol: str`, `language: str\|None` | `dict` (`file`, `line`, `kind`, `signature`) | `{"error": str}` |
| 4 | `find_dependencies` | `file_path: str`, `depth: int = 1`, `direction: str = "both"` | `dict` (`imports`, `imported_by`, `transitive_deps`, `circular_deps`) | `{"error": str}` |
| 5 | `analyze_graph` | (none) | `dict` (GraphAnalysis shape) | `{"error": str}` |
| 6 | `check_dead_code` | `service_name: str\|None` | `list[dict]` (DeadCodeEntry shape) | `[{"error": str}]` |
| 7 | `find_callers` | `symbol: str`, `max_results: int = 50` | `list[dict]` (`file_path`, `line`, `caller_symbol`) | `[{"error": str}]` |
| 8 | `get_service_interface` | `service_name: str` | `dict` (`service_name`, `endpoints`, `events_published`, `events_consumed`, `exported_symbols`) | `{"error": str}` |

---

## HTTP Endpoint Shapes

### Complete Endpoint Table

| Method | Path | Status | Request | Response |
|--------|------|--------|---------|----------|
| `GET` | `/api/health` | 200 | -- | `HealthStatus` (`status`, `service_name`, `version`, `database`, `uptime_seconds`, `details` with `chroma` and `chroma_chunks`) |
| `GET` | `/api/symbols` | 200 | Query: `name?`, `kind?`, `language?`, `service_name?`, `file_path?` | `list[dict]` (SymbolDefinition.model_dump) |
| `GET` | `/api/dependencies` | 200 | Query: `file_path` (required), `depth?` (1-100), `direction?` (forward/reverse/both) | `{"file_path", "depth", "dependencies", "dependents"}` |
| `GET` | `/api/graph/analysis` | 200 | -- | `GraphAnalysis.model_dump()` (`node_count`, `edge_count`, `is_dag`, `circular_dependencies`, `top_files_by_pagerank`, `connected_components`, `build_order`) |
| `POST` | `/api/search` | 200 | Body: `{"query": str, "language"?: str, "service_name"?: str, "top_k"?: int}` | `list[dict]` (SemanticSearchResult.model_dump) |
| `POST` | `/api/artifacts` | 200 | Body: `{"file_path": str, "service_name"?: str, "source"?: str (base64), "project_root"?: str}` | `{"indexed", "symbols_found", "dependencies_found", "errors"}` |
| `GET` | `/api/dead-code` | 200 | Query: `service_name?` | `list[dict]` (DeadCodeEntry.model_dump) |

### Validation Behavior

- `POST /api/search` with empty `query` -> 422 (validated by `Field(min_length=1)`)
- `POST /api/artifacts` without `file_path` -> 422 (validated by `Field(..., min_length=1)`)
- `GET /api/dependencies` without `file_path` -> 422 (required query parameter)

---

*End of Verification Report.*

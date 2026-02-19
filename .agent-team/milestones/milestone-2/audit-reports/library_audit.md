# Library Audit Report - Milestone 2

**Auditor**: Library/MCP Auditor
**Date**: 2026-02-19
**Scope**: All third-party library API usage across the super-team codebase, with focus on Milestone 2 (MCP wiring verification) critical paths.
**Method**: Documentation-verified audit via installed package source inspection, type stubs, and Context7 docs.

---

## Executive Summary

Audited **10 major third-party libraries** across **40+ source files**. Found **2 actionable findings** (1 CRITICAL, 1 MEDIUM) and **4 informational observations**. The MCP SDK, tree-sitter, ChromaDB, NetworkX, Pydantic, and transitions library APIs are all used correctly. One httpx `Timeout` constructor call has incorrect arguments that will raise `ValueError` at runtime. The Starlette `BaseHTTPMiddleware` has a known `ContextVar` propagation limitation that affects the trace-ID middleware.

| Severity | Count |
|----------|-------|
| CRITICAL | 1 |
| HIGH | 0 |
| MEDIUM | 1 |
| LOW | 0 |
| INFO | 4 |

---

## Library Inventory

| Library | Pinned Version | Installed | Audit Status |
|---------|---------------|-----------|--------------|
| `mcp` (MCP SDK) | `>=1.25,<2` | 1.26.0 | PASS |
| `fastapi` | `==0.129.0` | 0.129.0 | PASS |
| `pydantic` | `>=2.5.0` | 2.x | PASS |
| `pydantic-settings` | `>=2.1.0` | 2.x | PASS |
| `httpx` | `>=0.27.0` | 0.27.x+ | **1 FINDING** |
| `tree-sitter` | `==0.25.2` | 0.25.2 | PASS |
| `tree-sitter-python` | `==0.25.0` | 0.25.0 | PASS |
| `chromadb` | `==1.5.0` | 1.5.0 | PASS |
| `networkx` | `==3.6.1` | 3.6.1 | PASS |
| `transitions` | `>=0.9.0` | 0.9.3 | PASS |
| `starlette` (via FastAPI) | transitive | 0.37.x | **1 FINDING** |
| `pyyaml` | `>=6.0` | 6.x | PASS |
| `jsonschema` | `>=4.20.0` | 4.x | PASS |

---

## Findings

### FINDING-001: httpx.Timeout constructor missing required parameters (CRITICAL)

**Severity**: CRITICAL
**File**: `src/architect/mcp_server.py`, line 224-226
**Library**: `httpx>=0.27.0`
**Verified Against**: httpx source `_config.py` Timeout class constructor

**Code**:
```python
with httpx.Client(
    timeout=httpx.Timeout(connect=5.0, read=30.0),
) as client:
```

**Issue**: The `httpx.Timeout` constructor requires either:
1. A positional `timeout` default that applies to all unset components, **OR**
2. All four named parameters (`connect`, `read`, `write`, `pool`) to be explicitly provided.

When only `connect` and `read` are specified and no default is given, `write` and `pool` remain as `UNSET`, triggering a `ValueError`:

```
ValueError: httpx.Timeout must either include a default, or set all four parameters explicitly.
```

**Impact**: The `get_contracts_for_service` MCP tool (SVC-004 / WIRE-012) will fail at runtime whenever a cross-server contract lookup is attempted. This is the cross-server call path tested by `test_architect_cross_server_contract_lookup` (WIRE-012). The test passes because it mocks the MCP session and never reaches the httpx code path.

**Correct Usage** (any of these):
```python
# Option A: provide a default for write/pool
httpx.Timeout(5.0, connect=5.0, read=30.0)

# Option B: specify all four explicitly
httpx.Timeout(connect=5.0, read=30.0, write=5.0, pool=5.0)

# Option C: single uniform timeout
httpx.Timeout(30.0)
```

**M2 Test Impact**: Milestone 2 tests all use mocked MCP sessions and do not exercise the real httpx path, so this bug is **latent** in the test suite. It would surface in WIRE-012 integration testing with live servers or in production.

---

### FINDING-002: BaseHTTPMiddleware ContextVar propagation limitation (MEDIUM)

**Severity**: MEDIUM
**File**: `src/shared/logging.py`, lines 64-72
**Library**: `starlette` (transitive via `fastapi==0.129.0`)
**Verified Against**: Starlette middleware documentation

**Code**:
```python
from starlette.middleware.base import BaseHTTPMiddleware

class TraceIDMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: Any) -> Response:
        request_trace_id = str(uuid.uuid4())
        trace_id_var.set(request_trace_id)
        response = await call_next(request)
        response.headers["X-Trace-ID"] = request_trace_id
        return response
```

**Issue**: Starlette's documentation explicitly warns:

> "Using `BaseHTTPMiddleware` will prevent changes to `contextvars.ContextVar`s from propagating upwards."

The `TraceIDMiddleware`'s entire purpose is to set `trace_id_var` (a `ContextVar`) for downstream logging. Due to the `BaseHTTPMiddleware` implementation, `trace_id_var.set(request_trace_id)` inside `dispatch()` may not be visible to route handlers and their logging calls, defeating the purpose of the middleware.

**Impact**: Trace IDs in structured JSON logs from route handlers may be empty strings (the `ContextVar` default) instead of the UUID set by the middleware. This affects observability but not correctness.

**Recommendation**: Replace with a pure ASGI middleware class that does not suffer from the ContextVar propagation issue.

**M2 Test Impact**: No direct impact on M2 test correctness. Affects runtime observability of all three services.

---

### FINDING-003: MCP SDK version constraint matches usage (INFO)

**Severity**: INFO
**Library**: `mcp>=1.25,<2`
**Installed**: 1.26.0

**Observation**: All MCP SDK APIs used in the codebase are verified correct against `mcp==1.26.0`:

| API | Import Path | Status |
|-----|-------------|--------|
| `FastMCP(name)` | `mcp.server.fastmcp` | Correct |
| `@mcp.tool(name=...)` | decorator on FastMCP | Correct |
| `@mcp.tool()` (inferred name) | decorator on FastMCP | Correct |
| `mcp.run()` | FastMCP.run() | Correct (defaults to stdio) |
| `ClientSession(read, write)` | `mcp.ClientSession` | Correct (async context manager) |
| `stdio_client(params)` | `mcp.client.stdio` | Correct (async context manager) |
| `session.initialize()` | ClientSession method | Correct |
| `session.list_tools()` | ClientSession method | Correct (returns `ListToolsResult.tools`) |
| `session.call_tool(name, args)` | ClientSession method | Correct (returns `CallToolResult`) |

The REQUIREMENTS.md constraint `Pin mcp>=1.25,<2` (Risk Analysis table) is correctly reflected in `pyproject.toml`.

The test mocking pattern (`MockToolResult`, `MockTextContent`, `make_mcp_result`) in `tests/run4/conftest.py` correctly mirrors the real `CallToolResult` and `TextContent` structures from the MCP SDK types.

---

### FINDING-004: tree-sitter 0.25.x API usage is fully modern (INFO)

**Severity**: INFO
**Library**: `tree-sitter==0.25.2`

**Observation**: The codebase uses the modern 0.25.x API throughout, with zero deprecated patterns:

| Pattern | Old API (deprecated) | Current API (used) |
|---------|---------------------|-------------------|
| Language creation | `Language(int_ptr)` | `Language(capsule_object)` |
| Parser initialization | `Parser(); parser.set_language(lang)` | `Parser(lang)` |
| Query creation | `language.query(pattern)` | `Query(language, pattern)` |
| Point access | `node.start_point[0]` (tuple index) | `node.start_point.row` (NamedTuple) |

All tree-sitter language grammars are version-compatible:
- `tree-sitter-python==0.25.0` (matches 0.25.x)
- `tree-sitter-typescript==0.23.2` (compatible)
- `tree-sitter-c-sharp==0.23.1` (compatible)
- `tree-sitter-go==0.25.0` (matches 0.25.x)

---

### FINDING-005: ChromaDB 1.5.0 API fully compatible (INFO)

**Severity**: INFO
**Library**: `chromadb==1.5.0`

**Observation**: All ChromaDB APIs in `src/codebase_intelligence/storage/chroma_store.py` are verified correct:

| API | Status | Notes |
|-----|--------|-------|
| `PersistentClient(path=...)` | Correct | Factory function returning `Client` |
| `DefaultEmbeddingFunction()` | Correct | No-arg constructor |
| `get_or_create_collection(name, embedding_function, metadata)` | Correct | New `schema`/`configuration` params in 1.x are unused (optional) |
| `collection.add(ids, documents, metadatas)` | Correct | None-metadata values correctly handled |
| `collection.query(query_texts, n_results, where)` | Correct | New `included` key in result safely ignored |
| `collection.delete(where=...)` | Correct | Standard metadata filter |
| `collection.count()` | Correct | No-arg, returns int |

The `metadata={"hnsw:space": "cosine"}` pattern for collection configuration is still supported without deprecation warnings in 1.5.0 (new alternative: `configuration` parameter).

The collection name `"code_chunks"` passes the stricter 1.5.0 name validation rules (3-512 chars, `[a-zA-Z0-9._-]`).

---

### FINDING-006: NetworkX pagerank exception handling gap (INFO)

**Severity**: INFO
**File**: `src/codebase_intelligence/services/graph_analyzer.py`, lines 52-58
**Library**: `networkx==3.6.1`

**Code**:
```python
try:
    pr = nx.pagerank(self._graph)
    sorted_pr = sorted(pr.items(), key=lambda x: x[1], reverse=True)
    top_files = sorted_pr[:10]
except (nx.NetworkXError, KeyError) as exc:
    logger.warning("PageRank failed: %s", exc)
```

**Observation**: In NetworkX 3.x, `nx.pagerank` requires `scipy` at runtime and will raise `ModuleNotFoundError` (not `NetworkXError`) if scipy is absent. The exception handler does not catch `ModuleNotFoundError`.

**Impact**: In practice, `scipy` is a transitive dependency of `networkx` and is also explicitly listed in the codebase-intelligence Docker requirements (`scipy>=1.11.0`), so this gap has near-zero risk. However, if this code were run in an environment where scipy was somehow absent, the `PageRank failed` log message would not appear -- instead an unhandled `ModuleNotFoundError` would propagate up.

**M2 Test Impact**: None. The graph analyzer is not directly tested by M2 milestone tests (which focus on MCP wiring), and the Codebase Intelligence MCP server's `analyze_graph` tool wraps calls in a top-level `except Exception` handler.

---

## Libraries Verified Clean (No Findings)

### Pydantic (>=2.5.0) / pydantic-settings (>=2.1.0)

All Pydantic v2 APIs verified correct:

| API | Files | Status |
|-----|-------|--------|
| `BaseModel` | 20+ model classes across `src/shared/models/` | Correct |
| `Field(...)` with `default`, `default_factory`, `pattern`, `max_length`, `ge` | Multiple | Correct v2 syntax |
| `model_validator(mode="before")` with `@classmethod` | `contracts.py` (2 validators) | Correct v2 pattern |
| `model_dump(mode="json")` | All MCP servers | Correct (v2 replacement for v1's `dict()`) |
| `model_copy(update={...})` | `architect/mcp_server.py` | Correct (v2 replacement for v1's `copy(update=)`) |
| `model_config = {"from_attributes": True}` | All model classes | Correct v2 Config |
| `BaseSettings` with `validation_alias` | `src/shared/config.py` | Correct pydantic-settings v2 |
| `model_config = {"populate_by_name": True, "extra": "ignore"}` | `SharedConfig` | Correct v2 settings config |

No deprecated v1 patterns found (no `.dict()`, `.copy()`, `class Config:`, `@validator`, `@root_validator`).

### FastAPI (==0.129.0)

All FastAPI APIs verified correct:

| API | Status |
|-----|--------|
| `FastAPI(title, version, lifespan)` | Correct (lifespan is recommended over on_event) |
| `app.include_router(router)` | Correct |
| `APIRouter()`, `@router.get/post(...)` | Correct |
| `Request`, `Query`, `Response`, `JSONResponse` | Correct |
| `from fastapi.testclient import TestClient` | Correct (re-exports Starlette's) |

### httpx (>=0.27.0) -- Excluding FINDING-001

| API | Status |
|-----|--------|
| `AsyncClient(timeout=10.0)` | Correct (float accepted) |
| `AsyncClient(timeout=..., follow_redirects=True)` | Correct |
| `client.get()`, `client.post()`, `client.request()` | Correct |
| `httpx.HTTPError`, `httpx.TimeoutException`, `httpx.ConnectError` | Correct hierarchy |

### NetworkX (==3.6.1)

| API | Status |
|-----|--------|
| `nx.DiGraph()`, `add_node()`, `add_edge()` | Correct |
| `successors()`, `predecessors()` | Correct |
| `nx.is_directed_acyclic_graph()` | Correct |
| `nx.simple_cycles()` | Correct (extended in 3.3 for undirected; DiGraph usage unchanged) |
| `nx.pagerank()` | Correct (canonical name; not deprecated) |
| `nx.number_weakly_connected_components()` | Correct |
| `nx.topological_sort()` | Correct (returns generator, correctly wrapped in `list()`) |
| `nx.NetworkXError` | Correct exception class |

### transitions (>=0.9.0)

| API | Status |
|-----|--------|
| `State(name, on_enter=[...])` | Correct |
| `AsyncMachine(model, states, transitions, initial, auto_transitions, send_event, queued, ignore_invalid_triggers)` | All parameters verified correct |

### PyYAML (>=6.0)

| API | Status |
|-----|--------|
| `yaml.safe_load(f)` | Correct (safe deserialization) |
| `yaml.dump(obj, default_flow_style=False, sort_keys=False)` | Correct |

### jsonschema (>=4.20.0)

| API | Status |
|-----|--------|
| `jsonschema.Draft202012Validator.check_schema()` | Correct |
| `jsonschema.exceptions.SchemaError` | Correct |

---

## M2-Specific MCP Wiring Verification

The following M2-critical API patterns are all verified correct:

### MCP Server-Side (Build 1)
- `FastMCP("Architect")`, `FastMCP("Contract Engine")`, `FastMCP("Codebase Intelligence")` -- correct
- All `@mcp.tool()` and `@mcp.tool(name=...)` decorators -- correct
- `mcp.run()` at `__main__` entrypoint -- correct (defaults to stdio transport)
- Tool functions returning `dict`, `list[dict]`, `str` -- all valid MCP tool return types

### MCP Client-Side (Build 2 test infrastructure)
- `ClientSession(read_stream, write_stream)` as async context manager -- correct
- `stdio_client(server_params)` as async context manager -- correct
- `session.initialize()` -- correct (required before other calls)
- `session.list_tools()` -> `.tools[].name` -- correct
- `session.call_tool(name, arguments)` -> `CallToolResult` -- correct

### Test Mocking Layer
- `MockToolResult(content=[MockTextContent], isError=False)` -- correctly mirrors `CallToolResult`
- `make_mcp_result(data, is_error=False)` -- correctly serializes to JSON TextContent

---

## Conclusion

The codebase demonstrates strong library API hygiene overall. The 1 CRITICAL finding (FINDING-001: httpx.Timeout) is a latent runtime bug in the cross-server contract lookup path that is not caught by M2's mock-based tests. It should be fixed before integration testing with live servers. The MEDIUM finding (FINDING-002: BaseHTTPMiddleware ContextVar) is a known Starlette limitation affecting observability but not correctness.

All MCP SDK APIs critical to Milestone 2 wiring verification are used correctly and match the installed `mcp==1.26.0` package.

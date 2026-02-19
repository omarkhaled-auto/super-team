# Library Audit Report

**Auditor**: Library/MCP Auditor (Automated)
**Date**: 2026-02-19
**Scope**: All third-party library API usage in `src/` verified against current documentation
**Libraries Audited**: 16 (FastAPI, Pydantic, pydantic-settings, ChromaDB, tree-sitter, httpx, networkx, MCP SDK, schemathesis, transitions, typer, rich, PyYAML, jsonschema, openapi-spec-validator, prance)

---

## Executive Summary

| Severity | Count |
|----------|-------|
| CRITICAL | 1 |
| HIGH     | 2 |
| MEDIUM   | 3 |
| LOW      | 2 |
| INFO     | 5 |

**Overall Assessment**: The codebase demonstrates generally strong library usage with modern API patterns. One CRITICAL finding relates to schemathesis programmatic API usage that may cause runtime errors. Two HIGH findings involve a known-problematic middleware base class and a ChromaDB version jump risk. Several MEDIUM/LOW items identify opportunities to use newer recommended patterns.

---

## Findings

---

### FINDING-001
**Severity**: CRITICAL
**Library**: schemathesis (pinned `==4.10.1`)
**File**: `src/integrator/schemathesis_runner.py`, lines 360-364
**Category**: Potentially invalid API method call

**Issue**: The `_run_via_test_runner` method calls `api_operation.make_case()` on objects yielded by `schema.get_all_operations()`. However, in schemathesis 4.x, `make_case()` is defined on the **schema** object (as `schema.make_case(operation=...)`) — not on `APIOperation` directly. The documented API for `APIOperation` exposes `Case()` constructor and `as_strategy()`, but NOT `make_case()` as an instance method.

**Code**:
```python
for api_operation in schema.get_all_operations():
    case = api_operation.make_case()        # <-- may not exist on APIOperation
    response = case.call(base_url=base_url)
    case.validate_response(response)
```

**Evidence**: Schemathesis Python API reference documents `APIOperation` with methods `as_strategy()`, `is_valid_response()`, `validate_response()`, and `Case()` — but NOT `make_case()`. The `make_case()` factory is on `BaseOpenAPISchema` (line 539 of schemathesis source), taking `operation=` as a keyword argument.

**Risk**: If `APIOperation` does not have `make_case()`, this code path will raise `AttributeError` at runtime during positive contract testing. The outer `try/except Exception` (line 426) would catch this silently, causing all positive tests to be skipped without clear error reporting.

**Mitigating Factor**: The broad `except Exception` handler at line 430 prevents a crash, but all positive schema conformance tests would effectively be no-ops.

**Recommendation**: Verify the exact schemathesis 4.10.1 API. If `make_case()` is not on `APIOperation`, refactor to:
```python
for api_operation in schema.get_all_operations():
    case = api_operation.as_strategy().example()
    # or: case = schema.make_case(operation=api_operation)
```

---

### FINDING-002
**Severity**: HIGH
**Library**: FastAPI / Starlette
**File**: `src/shared/logging.py`, lines 64-72
**Category**: Deprecated middleware base class

**Issue**: `TraceIDMiddleware` extends `BaseHTTPMiddleware` from Starlette. This class has been [proposed for deprecation](https://github.com/Kludex/starlette/discussions/2160) by Starlette maintainers and is documented as "fundamentally broken" with known issues:
- Does not play nicely with `contextVars` (ironic, since this middleware USES `contextvars`)
- Measurable performance overhead vs pure ASGI middleware
- Response body streaming issues

**Code**:
```python
class TraceIDMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: Any) -> Response:
        request_trace_id = str(uuid.uuid4())
        trace_id_var.set(request_trace_id)
        response = await call_next(request)
        response.headers["X-Trace-ID"] = request_trace_id
        return response
```

**Impact**: The middleware uses `contextvars.ContextVar` for trace ID propagation — the exact pattern that Starlette maintainers warn has issues with `BaseHTTPMiddleware`. The `trace_id_var.set()` may not correctly propagate to downstream async handlers in certain edge cases. Additionally, this will break when Starlette eventually removes `BaseHTTPMiddleware`.

**Used in**: All 3 services (architect, contract-engine, codebase-intelligence) via `app.add_middleware(TraceIDMiddleware)`.

**Recommendation**: Rewrite as pure ASGI middleware:
```python
class TraceIDMiddleware:
    def __init__(self, app):
        self.app = app
    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            trace_id = str(uuid.uuid4())
            trace_id_var.set(trace_id)
            async def send_wrapper(message):
                if message["type"] == "http.response.start":
                    headers = MutableHeaders(scope=message)
                    headers.append("X-Trace-ID", trace_id)
                await send(message)
            await self.app(scope, receive, send_wrapper)
        else:
            await self.app(scope, receive, send)
```

---

### FINDING-003
**Severity**: HIGH
**Library**: ChromaDB (pinned `==1.5.0`)
**File**: `src/codebase_intelligence/storage/chroma_store.py`
**Category**: Major version jump — API surface change risk

**Issue**: The project pins `chromadb==1.5.0`, which is a 1.x release (built 2026-02-09). ChromaDB underwent significant breaking changes from 0.x → 1.x:

1. **Embeddings as NumPy arrays**: `collection.query()` now returns embeddings as 2D NumPy arrays, not Python lists. The code in `semantic_searcher.py` accesses `results["distances"][0]` (line 121) which should still work since distances remain list-like, but any direct equality checks against lists would fail.

2. **`get_or_create_collection` metadata behavior**: In newer ChromaDB, if the collection already exists, metadata arguments are **ignored** (not overwritten). The code passes `metadata={"hnsw:space": "cosine"}` on every call — this is safe but the metadata will only apply on first creation.

3. **Import path stability**: `from chromadb.utils.embedding_functions import DefaultEmbeddingFunction` — this import path is confirmed valid in current ChromaDB documentation.

**Current code is likely functional** but the tight pin to `1.5.0` means the team must be aware of these 1.x behavioral changes if upgrading from older testing environments.

**Recommendation**: Add integration tests that verify ChromaDB query return types match expectations. Document the 1.x migration notes in a CHANGELOG or README.

---

### FINDING-004
**Severity**: MEDIUM
**Library**: networkx (pinned `==3.6.1`)
**File**: `src/codebase_intelligence/storage/graph_db.py`, line 111
**Category**: Missing `directed` parameter on deserialization

**Issue**: When deserializing graphs with `nx.node_link_graph()`, the code does not pass `directed=True`:

```python
graph: nx.DiGraph = nx.node_link_graph(data, edges="edges")
```

The `node_link_graph()` function defaults to `directed=False`, meaning it returns an undirected `Graph` by default, then the type hint asserts `nx.DiGraph`. In NetworkX 3.6.1, if the serialized data contains a `"directed": true` field (which `node_link_data()` includes by default), the function respects it. However, if that field is missing from the JSON data, the graph will be loaded as **undirected**, contradicting the `DiGraph` type annotation.

**Evidence**: [NetworkX 3.6.1 docs](https://networkx.org/documentation/stable/reference/readwrite/generated/networkx.readwrite.json_graph.node_link_graph.html) confirm `directed=False` is the default.

**Serialization** (line 76): `nx.node_link_data(graph, edges="edges")` — This DOES include `"directed": true/false` in the output, so the round-trip should work. But relying on implicit behavior is fragile.

**Recommendation**: Explicitly pass `directed=True`:
```python
graph = nx.node_link_graph(data, directed=True, edges="edges")
```

---

### FINDING-005
**Severity**: MEDIUM
**Library**: schemathesis (pinned `==4.10.1`)
**File**: `src/integrator/schemathesis_runner.py`, lines 244-248
**Category**: Fragile internal attribute access

**Issue**: The negative test implementation accesses raw schema data through undocumented internal attributes:

```python
raw: dict[str, Any] = {}
for attr in ("raw_schema", "raw", "schema"):
    raw = getattr(schema, attr, None) or {}
    if raw:
        break
```

This probes three different attribute names (`raw_schema`, `raw`, `schema`) hoping to find the raw OpenAPI dict. None of these are part of the documented schemathesis public API. Internal attribute names can change between minor versions.

**Risk**: When schemathesis updates, any of these attributes could be renamed or removed, causing the negative tests to silently get an empty `raw` dict and skip all negative testing.

**Recommendation**: Use `schema.raw_schema` if documented, or extract paths from the original OpenAPI URL/file directly rather than relying on internal schema attributes.

---

### FINDING-006
**Severity**: MEDIUM
**Library**: FastAPI (`==0.129.0`)
**File**: `src/contract_engine/routers/contracts.py`, line 26
**Category**: Return type mismatch in endpoint

**Issue**: The `create_contract` endpoint declares return type `ContractEntry` but can return `JSONResponse` for the 413 case:

```python
@router.post("/contracts", response_model=ContractEntry, status_code=201)
async def create_contract(body: ContractCreate, request: Request) -> ContractEntry:
    content_length = request.headers.get("content-length")
    if content_length and int(content_length) > _MAX_PAYLOAD_BYTES:
        return JSONResponse(status_code=413, content={"detail": "Payload too large"})
```

The Python return type annotation says `ContractEntry` but the function can return `JSONResponse`. While FastAPI handles this correctly at runtime (it bypasses the response_model serialization for raw Response objects), this is technically a type annotation lie that mypy strict mode would flag.

**Recommendation**: Change return annotation to `ContractEntry | JSONResponse` or use `raise HTTPException(status_code=413, detail="Payload too large")` instead.

---

### FINDING-007
**Severity**: LOW
**Library**: FastAPI (`==0.129.0`)
**File**: Multiple router files
**Category**: Inconsistent router prefix patterns

**Issue**: The three services use inconsistent patterns for URL prefixes:

- **Architect routers**: Prefix in route decorators (`@router.get("/api/health")`) — NO prefix on `APIRouter()`
- **Contract Engine routers**: Prefix on `APIRouter(prefix="/api")` + relative paths (`@router.get("/health")`)
- **Codebase Intelligence routers**: Mixed — some use `APIRouter(prefix="/api/...")`, health uses route-level `/api/health`

This inconsistency doesn't cause bugs but makes the codebase harder to maintain and reason about.

**Recommendation**: Standardize on one pattern across all services. The `APIRouter(prefix=...)` approach is preferred as it centralizes path management.

---

### FINDING-008
**Severity**: LOW
**Library**: transitions (`>=0.9.0`)
**File**: `src/super_orchestrator/state_machine.py`, `pyproject.toml`
**Category**: DeprecationWarning suppression

**Issue**: The `pyproject.toml` suppresses deprecation warnings from transitions:

```toml
filterwarnings = [
    "ignore::DeprecationWarning:transitions",
]
```

This indicates the transitions library is emitting deprecation warnings that are being silenced. While the code uses `AsyncMachine` from `transitions.extensions.asyncio` with a modern pattern, the suppressed warnings should be investigated to ensure the API surface won't break in the next transitions release.

**Recommendation**: Remove the filter temporarily, identify the specific deprecated APIs being warned about, and update accordingly.

---

### FINDING-009
**Severity**: INFO
**Library**: Pydantic (`>=2.5.0`) + pydantic-settings (`>=2.1.0`)
**Category**: Full v2 compliance — no issues found

**Details**: Comprehensive audit confirms:
- All 45 BaseModel subclasses use Pydantic v2 patterns exclusively
- All 4 BaseSettings subclasses use `pydantic_settings` (not deprecated `pydantic.BaseSettings`)
- All validators use `@model_validator(mode="before")` (v2 syntax), zero instances of deprecated `@validator` or `@root_validator`
- All config uses `model_config = {...}` dict (not deprecated `class Config:`)
- Uses `from_attributes=True` (not deprecated `orm_mode=True`)
- Uses `validation_alias` (not deprecated `Field(alias=...)`)
- Uses `model_dump()` (not deprecated `.dict()`)

**Verdict**: No issues. Full Pydantic v2 compliance.

---

### FINDING-010
**Severity**: INFO
**Library**: tree-sitter (`==0.25.2`) + language bindings
**Category**: Full modern API compliance — no issues found

**Details**: All tree-sitter usage follows the modern v0.25.2+ API:
- `Language(tree_sitter_python.language())` — modern constructor (not deprecated `Language(binary_path)`)
- `Parser(language)` — modern constructor
- `QueryCursor(query).matches(node)` — modern cursor-based API (not deprecated `query.matches(node)`)
- Proper `node.text.decode()` for bytes→str conversion
- Proper `node.start_point.row + 1` for 1-indexed line numbers

**Verdict**: No issues. All code is compatible with tree-sitter 0.25.2.

---

### FINDING-011
**Severity**: INFO
**Library**: httpx (`>=0.27.0`)
**Category**: Correct usage patterns — no issues found

**Details**: All httpx usage follows documented patterns:
- Proper context manager usage (`async with httpx.AsyncClient() as client:`)
- Correct timeout configuration: `httpx.Timeout(connect=5.0, read=30.0)` and simple `timeout=10.0`
- Proper exception hierarchy: catches `HTTPError`, `TimeoutException`, `ConnectError`
- `follow_redirects=True` used appropriately in integration testing modules
- Both sync `Client` and async `AsyncClient` used correctly per context

**Verdict**: No issues.

---

### FINDING-012
**Severity**: INFO
**Library**: MCP SDK (`>=1.25,<2`)
**Category**: Correct usage patterns — no issues found

**Details**: MCP usage follows documented patterns:
- `FastMCP("name")` server creation from `mcp.server.fastmcp`
- `@mcp.tool()` and `@mcp.tool(name="...")` decorators
- `StdioServerParameters` imported from `mcp`
- `stdio_client(server_params)` from `mcp.client.stdio`
- `ClientSession(read, write)` from `mcp.client.session`
- `session.initialize()` + `session.call_tool()` + `result.content[0].text` pattern
- Retry logic with exponential backoff for client connections
- 21 MCP tools defined across 3 services (4 Architect, 8 Codebase Intelligence, 10 Contract Engine)

**Verdict**: No issues. All import paths and API patterns match official SDK documentation.

---

### FINDING-013
**Severity**: INFO
**Library**: typer (`>=0.12.0`), rich (`>=13.0.0`), PyYAML (`>=6.0`), jsonschema (`>=4.20.0`), openapi-spec-validator (`>=0.7.0`), prance (`>=25.0.0`)
**Category**: Correct usage — no issues found

**Details**:
- **typer**: Uses `Annotated` type hints (modern pattern), `typer.Option()`, `typer.Argument()`, `rich_markup_mode="rich"` — all correct for typer 0.12+
- **rich**: Uses `Console`, `Panel`, `Table`, `Text`, `Progress` — standard API, no deprecated patterns
- **PyYAML**: Always uses `yaml.safe_load()` (not insecure `yaml.load()`), `yaml.dump()` with `default_flow_style=False`
- **jsonschema**: Uses `jsonschema.validate(instance, schema)` — standard API
- **openapi-spec-validator**: Lazy import with graceful fallback, uses `OpenAPIV30SpecValidator` and `OpenAPIV31SpecValidator`
- **prance**: Lazy import with graceful fallback, uses `ResolvingParser(spec_string=..., spec_url=...)` — correct API

**Verdict**: No issues across all utility libraries.

---

## Library Version Matrix

| Library | Pinned Version | Latest Verified | API Compliance | Notes |
|---------|---------------|-----------------|----------------|-------|
| fastapi | ==0.129.0 | 0.129.0 | GOOD | BaseHTTPMiddleware concern (FINDING-002) |
| pydantic | >=2.5.0 | 2.x | EXCELLENT | Full v2 compliance, zero deprecated patterns |
| pydantic-settings | >=2.1.0 | 2.x | EXCELLENT | Correct import paths |
| chromadb | ==1.5.0 | 1.5.0 | GOOD | 1.x migration awareness needed (FINDING-003) |
| tree-sitter | ==0.25.2 | 0.25.2 | EXCELLENT | All modern API patterns |
| tree-sitter-python | ==0.25.0 | 0.25.0 | EXCELLENT | Correct language() factory |
| tree-sitter-typescript | ==0.23.2 | 0.23.2 | EXCELLENT | Both language_typescript() and language_tsx() |
| tree-sitter-c-sharp | ==0.23.1 | 0.23.1 | EXCELLENT | Correct language() factory |
| tree-sitter-go | ==0.25.0 | 0.25.0 | EXCELLENT | Correct language() factory |
| httpx | >=0.27.0 | 0.27+ | EXCELLENT | Proper sync/async usage |
| networkx | ==3.6.1 | 3.6.1 | GOOD | node_link_graph directed param (FINDING-004) |
| mcp | >=1.25,<2 | 1.x | EXCELLENT | Correct FastMCP and client patterns |
| schemathesis | ==4.10.1 | 4.10.1 | POOR | Undocumented API usage (FINDING-001, -005) |
| transitions | >=0.9.0 | 0.9.x | GOOD | Deprecation warnings suppressed (FINDING-008) |
| typer | >=0.12.0 | 0.12+ | EXCELLENT | Modern Annotated patterns |
| rich | >=13.0.0 | 13.x | EXCELLENT | Standard API |
| pyyaml | >=6.0 | 6.x | EXCELLENT | Always safe_load |
| jsonschema | >=4.20.0 | 4.x | EXCELLENT | Standard validate() |
| openapi-spec-validator | >=0.7.0 | 0.7+ | EXCELLENT | Lazy import, graceful fallback |
| prance | >=25.0.0 | 25.x | EXCELLENT | Lazy import, graceful fallback |

---

## Methodology

1. **Codebase Scan**: All Python source files in `src/` were analyzed for third-party imports and usage patterns using automated agents scanning 120+ source files
2. **Documentation Verification**: Each library's API was verified against:
   - Official documentation websites (FastAPI, Pydantic, ChromaDB, NetworkX, tree-sitter, httpx, schemathesis, typer, rich)
   - GitHub source code (for schemathesis `schemas.py`, tree-sitter `py-tree-sitter`, networkx `node_link.py`)
   - PyPI package pages and changelogs
   - Migration guides (ChromaDB 0.x→1.x, schemathesis 3.x→4.0, NetworkX 3.4→3.6 `link`→`edges` keyword)
3. **Version Compatibility**: Pinned versions in `pyproject.toml` were cross-referenced against documented API surfaces
4. **Pattern Analysis**: Usage patterns were compared against recommended/deprecated approaches in each library's documentation

**Note**: Context7 MCP tools were not available in this environment. All verification was performed via web documentation lookup and GitHub source code review.

---

## Summary of Action Items

| Priority | Finding | Action |
|----------|---------|--------|
| P0 | FINDING-001 | Verify `api_operation.make_case()` works in schemathesis 4.10.1; refactor to `as_strategy().example()` if not |
| P1 | FINDING-002 | Rewrite `TraceIDMiddleware` as pure ASGI middleware |
| P1 | FINDING-003 | Add ChromaDB integration tests for 1.x return type compatibility |
| P2 | FINDING-004 | Add `directed=True` to `node_link_graph()` call |
| P2 | FINDING-005 | Replace internal attribute probing with documented API or direct spec access |
| P2 | FINDING-006 | Fix return type annotation or use HTTPException |
| P3 | FINDING-007 | Standardize router prefix patterns across services |
| P3 | FINDING-008 | Investigate suppressed transitions deprecation warnings |

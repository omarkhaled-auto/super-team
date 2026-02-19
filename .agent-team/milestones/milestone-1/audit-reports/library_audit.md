# Library & API Usage Audit Report — Milestone 1

**Auditor**: Library/MCP Auditor
**Scope**: All third-party library API usage in the `super-team` codebase
**Date**: 2026-02-19
**Milestone**: milestone-1 (Test Infrastructure + Fixtures)
**Methodology**: Web documentation verification (Context7 MCP unavailable — see NOTE below)

> **NOTE**: The Context7 MCP server is not configured in this project's `.mcp.json`.
> All verification was performed against official library documentation, PyPI, and
> GitHub repositories via web search and fetch. Findings are only flagged where
> documentation clearly confirms or contradicts the usage pattern.

---

## Summary

| Severity | Count |
|----------|-------|
| CRITICAL | 0 |
| HIGH     | 1 |
| MEDIUM   | 2 |
| LOW      | 2 |
| INFO     | 5 |

**Overall Assessment**: The codebase demonstrates generally correct and modern API usage across all major libraries. No CRITICAL runtime-breaking issues were found. One HIGH-severity deprecation notice and two MEDIUM-severity suboptimal patterns were identified.

---

## Libraries Audited

| Library | Pinned Version | Scope | Verdict |
|---------|---------------|-------|---------|
| `mcp` (MCP Python SDK) | >=1.25,<2 | Client + Server (FastMCP) | PASS |
| `fastapi` | ==0.129.0 | REST API framework | PASS |
| `httpx` | >=0.27.0 | HTTP client | PASS |
| `tree-sitter` | ==0.25.2 | AST parsing | PASS |
| `chromadb` | ==1.5.0 | Vector database | PASS (with notes) |
| `transitions` | >=0.9.0 | State machine | PASS |
| `pydantic` / `pydantic-settings` | >=2.5.0 / >=2.1.0 | Data models / Config | PASS (with deprecation note) |
| `openapi-spec-validator` | >=0.7.0 | Spec validation | PASS |
| `prance` | >=25.0.0 | $ref resolution | PASS |
| `schemathesis` | ==4.10.1 | Property-based API testing | PASS |
| `networkx` | ==3.6.1 | Graph analysis | PASS |
| `jsonschema` | >=4.20.0 | Schema validation | PASS |
| `typer` | >=0.12.0 | CLI framework | PASS |

---

## Findings

### FINDING-001
- **Severity**: HIGH
- **Library**: `pydantic-settings` (>=2.1.0)
- **File**: `src/shared/config.py` (line 15-18)
- **Issue**: `populate_by_name` is deprecated in Pydantic v2.11+ and will be removed in Pydantic v3
- **Evidence**:
  ```python
  model_config = {
      "populate_by_name": True,
      "extra": "ignore",
  }
  ```
  Per [Pydantic v2.11 release notes](https://docs.pydantic.dev/latest/api/config/), `populate_by_name` is superseded by `validate_by_name` (plus `validate_by_alias=True` for equivalent behavior). The current code works but will trigger deprecation warnings with Pydantic >=2.11 and will break in Pydantic v3.
- **Recommendation**: Replace with:
  ```python
  model_config = ConfigDict(
      validate_by_name=True,
      validate_by_alias=True,
      extra="ignore",
  )
  ```
  Also import `ConfigDict` from `pydantic` for type safety.

---

### FINDING-002
- **Severity**: MEDIUM
- **Library**: `pydantic-settings` (>=2.1.0)
- **File**: `src/shared/config.py` (lines 10-11, 22-24, 40-44)
- **Issue**: Using `validation_alias` instead of `alias` for environment variable field mapping
- **Evidence**:
  ```python
  log_level: str = Field(default="info", validation_alias="LOG_LEVEL")
  database_path: str = Field(
      default="./data/service.db", validation_alias="DATABASE_PATH"
  )
  ```
  In `pydantic-settings`, the `EnvSettingsSource` matches environment variables against field aliases. The `validation_alias` is only used during validation/parsing, not during environment variable lookup. There is a [known issue (#452)](https://github.com/pydantic/pydantic-settings/issues/452) where `EnvSettingsSource` does not fully respect `populate_by_name` for `validation_alias`-aliased fields. The current code **works** because `pydantic-settings` does special handling for `validation_alias` when it's a simple string, but using `alias` or `AliasPath` would be the canonical approach.
- **Recommendation**: Consider changing `validation_alias="LOG_LEVEL"` to `alias="LOG_LEVEL"` for clearer intent and guaranteed environment variable source compatibility. Monitor for behavioral changes across `pydantic-settings` releases.

---

### FINDING-003
- **Severity**: MEDIUM
- **Library**: `httpx` (>=0.27.0)
- **File**: `src/architect/mcp_server.py` (lines 224-226)
- **Issue**: `httpx.Timeout` constructor missing required positional argument `timeout`
- **Evidence**:
  ```python
  with httpx.Client(
      timeout=httpx.Timeout(connect=5.0, read=30.0),
  ) as client:
  ```
  The `httpx.Timeout` constructor signature is `Timeout(timeout=DEFAULT_TIMEOUT, *, connect=None, read=None, write=None, pool=None)`. When only keyword arguments are provided without the positional `timeout` argument, the unspecified timeouts (`write`, `pool`) default to the global `timeout` parameter value (which is 5.0s by default). This is **functional** but may be unintentional — the developer likely expected `write` and `pool` to use httpx defaults, but they will inherit the default `timeout` value (5.0s), not be unlimited.
- **Recommendation**: Either explicitly pass all four timeout values or set the base `timeout` first:
  ```python
  httpx.Timeout(30.0, connect=5.0)  # 30s default, 5s connect
  ```

---

### FINDING-004
- **Severity**: LOW
- **Library**: `mcp` (>=1.25,<2)
- **File**: `src/run4/mcp_health.py` (lines 115-128)
- **Issue**: MCP ClientSession usage pattern uses older context-manager nesting style
- **Evidence**:
  ```python
  from mcp import ClientSession
  from mcp.client.stdio import stdio_client
  # ...
  async with stdio_client(server_params) as (read_stream, write_stream):
      async with ClientSession(read_stream, write_stream) as session:
          await session.initialize()
  ```
  This is the **correct** pattern per [MCP SDK documentation](https://modelcontextprotocol.io/docs/develop/build-client). The import `from mcp import ClientSession` and `from mcp.client.stdio import stdio_client` are both correct. The `ClientSession(read_stream, write_stream)` constructor and the `session.initialize()` / `session.list_tools()` methods are all documented API. No issues found.
- **Recommendation**: Consider using `AsyncExitStack` for cleaner resource management as shown in the official tutorial, but current pattern is fully correct.

---

### FINDING-005
- **Severity**: LOW
- **Library**: `transitions` (>=0.9.0)
- **File**: `pyproject.toml` (line 56-58)
- **Issue**: Suppressing `DeprecationWarning` from `transitions` library in pytest config
- **Evidence**:
  ```toml
  filterwarnings = [
      "ignore::DeprecationWarning:transitions",
      "ignore::DeprecationWarning:asyncio",
  ]
  ```
  The `transitions` library is known to emit deprecation warnings. The `from transitions.extensions.asyncio import AsyncMachine` import path and `AsyncMachine` constructor usage in `src/super_orchestrator/state_machine.py` are correct per the [transitions documentation](https://github.com/pytransitions/transitions). The `State` import, transition dict format, and `AsyncMachine` keyword arguments (`model`, `states`, `transitions`, `initial`, `auto_transitions`, `send_event`, `queued`, `ignore_invalid_triggers`) are all valid API.
- **Recommendation**: Periodically check what specific deprecation the `transitions` library is emitting to avoid surprises in future major versions.

---

### FINDING-006
- **Severity**: INFO
- **Library**: `tree-sitter` (==0.25.2)
- **Files**: `src/codebase_intelligence/services/ast_parser.py` (lines 48-53, 87-88)
- **Issue**: API usage verified correct for tree-sitter 0.25.2
- **Evidence**:
  ```python
  # Language construction — CORRECT per 0.25.2 docs
  self._languages = {
      "python": Language(tree_sitter_python.language()),
      "typescript": Language(tree_sitter_typescript.language_typescript()),
      # ...
  }
  # Parser construction — CORRECT per 0.25.2 docs
  parser = Parser(ts_lang)  # Language as first positional arg
  tree = parser.parse(source)
  ```
  Per the [py-tree-sitter 0.25.2 documentation](https://tree-sitter.github.io/py-tree-sitter/), `Language(ptr)` accepts the result of `language()` calls from language packages, and `Parser(language)` accepts a `Language` as its first positional argument. Both patterns are the current, documented API.
- **Recommendation**: None — correct usage.

---

### FINDING-007
- **Severity**: INFO
- **Library**: `chromadb` (==1.5.0)
- **File**: `src/codebase_intelligence/storage/chroma_store.py` (lines 31-37)
- **Issue**: ChromaDB API usage verified correct for v1.5.0
- **Evidence**:
  ```python
  self._client = chromadb.PersistentClient(path=chroma_path)
  self._embedding_fn = DefaultEmbeddingFunction()
  self._collection = self._client.get_or_create_collection(
      name=self._COLLECTION_NAME,
      embedding_function=self._embedding_fn,
      metadata={"hnsw:space": "cosine"},
  )
  ```
  Per [ChromaDB migration docs](https://docs.trychroma.com/docs/overview/migration):
  - `PersistentClient(path=...)` is the correct modern API (replaces old `Client(Settings(...))`)
  - `DefaultEmbeddingFunction` from `chromadb.utils.embedding_functions` is still valid
  - `get_or_create_collection()`, `collection.add()`, `collection.query()`, `collection.delete()` APIs are unchanged
  - `collection.count()` is a valid method

  The `metadata={"hnsw:space": "cosine"}` parameter for setting distance metric is correct ChromaDB API.
- **Recommendation**: None — correct usage. Note: ChromaDB 1.x introduced authentication changes and CLI config changes, but the programmatic API used here is stable.

---

### FINDING-008
- **Severity**: INFO
- **Library**: `openapi-spec-validator` (>=0.7.0)
- **File**: `src/contract_engine/services/openapi_validator.py` (lines 121-148)
- **Issue**: API usage verified correct
- **Evidence**:
  ```python
  from openapi_spec_validator import (
      OpenAPIV30SpecValidator,
      OpenAPIV31SpecValidator,
  )
  validator = validator_cls(spec)
  for error in validator.iter_errors():
      # error.message, error.absolute_path — correct attributes
  ```
  Per [openapi-spec-validator docs](https://github.com/python-openapi/openapi-spec-validator), `OpenAPIV30SpecValidator(spec).iter_errors()` and `OpenAPIV31SpecValidator(spec).iter_errors()` are the documented API. The `error.message` and `error.absolute_path` attributes are correct (inherited from jsonschema validation errors).
- **Recommendation**: None — correct usage.

---

### FINDING-009
- **Severity**: INFO
- **Library**: `prance` (>=25.0.0)
- **File**: `src/contract_engine/services/openapi_validator.py` (lines 165-185)
- **Issue**: API usage verified correct
- **Evidence**:
  ```python
  from prance import ResolvingParser
  yaml_content: str = yaml.dump(spec, default_flow_style=False)
  ResolvingParser(
      spec_string=yaml_content,
      lazy=False,
  )
  ```
  Per [prance documentation](https://prance.readthedocs.io/en/latest/api/prance.html), `ResolvingParser` inherits from `BaseParser` and accepts `spec_string` as a keyword argument for in-memory spec parsing. The `lazy=False` parameter triggers immediate parsing and resolution.
- **Recommendation**: None — correct usage.

---

### FINDING-010
- **Severity**: INFO
- **Library**: `fastapi` (==0.129.0)
- **Files**: `src/architect/main.py`, `src/contract_engine/main.py`, `src/codebase_intelligence/main.py`, `src/shared/errors.py`
- **Issue**: FastAPI usage verified correct for v0.129.0
- **Evidence**: The codebase uses standard FastAPI patterns:
  - `FastAPI()` app creation
  - `APIRouter` for route organization
  - `@app.exception_handler(AppError)` for custom exception handling
  - `JSONResponse` for error responses
  - `Request` from both `fastapi` and `starlette.requests`

  FastAPI 0.129.0 dropped Python 3.9 support. The project targets Python >=3.11, so this is compatible. All API usage (`FastAPI`, `APIRouter`, `Query`, `Request`, `Response`, `JSONResponse`, `CORSMiddleware`, `exception_handler`) is standard stable FastAPI API.
- **Recommendation**: None — correct usage. Consider upgrading FastAPI for security patches (latest is 0.115.x+).

---

## Libraries NOT Verified (Context7 unavailable)

The following libraries could not be verified against Context7 documentation but were checked via web search with no issues found:

| Library | Usage | Assessment |
|---------|-------|------------|
| `schemathesis` ==4.10.1 | Listed as dependency; no direct API calls found in milestone-1 files | No issues — used in later milestones |
| `networkx` ==3.6.1 | `nx.simple_cycles()`, `nx.NetworkXError` | Standard API, verified via web docs |
| `jsonschema` >=4.20.0 | `jsonschema.Draft202012Validator.check_schema()` | Correct API per jsonschema docs |
| `typer` >=0.12.0 | `import typer`, `typer.Argument`, `typer.Option` | Standard API |
| `rich` >=13.0.0 | `Console`, `Panel`, `Table`, `Text`, progress bars | Standard API |

---

## MCP Server API Verification

All three MCP servers use `FastMCP` from the official MCP Python SDK:

| Server | Import | Pattern | Status |
|--------|--------|---------|--------|
| Architect | `from mcp.server.fastmcp import FastMCP` | `mcp = FastMCP("Architect")` | CORRECT |
| Contract Engine | `from mcp.server.fastmcp import FastMCP` | `mcp = FastMCP("Contract Engine")` | CORRECT |
| Codebase Intelligence | `from mcp.server.fastmcp import FastMCP` | `mcp = FastMCP("Codebase Intelligence")` | CORRECT |

The `@mcp.tool()` and `@mcp.tool(name="...")` decorator patterns are the documented FastMCP API. The `mcp.run()` entry point is correct.

---

## Version Compatibility Matrix

| Library | Installed | Min Required by REQUIREMENTS.md | Compatible? |
|---------|-----------|--------------------------------|-------------|
| `mcp` | >=1.25,<2 | >=1.25 (per REQUIREMENTS.md line 345) | YES |
| `httpx` | >=0.27.0 | Standard usage | YES |
| `pydantic` | >=2.5.0 | Not explicitly specified | YES |
| `openapi-spec-validator` | >=0.7.0 | New dev dependency | YES |
| Python | >=3.11 | 3.12 (target) | YES |

---

## Audit Limitations

1. **Context7 MCP unavailable**: The Context7 MCP server (`mcp__context7__resolve-library-id`, `mcp__context7__query-docs`) was not configured in `.mcp.json`. All verification was performed via web documentation search.
2. **Schemathesis 4.10.1**: This specific version's API could not be deeply verified as detailed release notes for 4.10.x were not available in search results. The library is pinned and only used in later milestones.
3. **ChromaDB 1.5.0**: This is a very recent version (released Feb 2026). The programmatic API appears stable from 0.4+ through 1.5, but edge cases in the v1.0 rewrite may exist that weren't captured by web documentation.

---

*End of Library Audit Report*

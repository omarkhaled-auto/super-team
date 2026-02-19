# Gap Report — Build 1 Final Hardening

Generated: 2026-02-16

## Known Issues Status (20 items)

| # | Status | Current File:Line | Notes |
|---|--------|-------------------|-------|
| 1 | **FIXED** | `src/architect/services/service_boundary.py:378-379` | `build_service_map()` now safely calls `hints.get("language", "python")` on line 379. If `technology_hints.language` is `None`, it defaults to `"python"`. The `hints = parsed.technology_hints or {}` on line 377 also guards against `None` dict. **No crash** — the `.get()` with default handles `None` values. |
| 2 | **STILL EXISTS** | `src/contract_engine/services/test_generator.py:81,109` | Cache key in `_get_cached()` (line 138-152) only uses `(contract_id, framework, spec_hash)`. The `include_negative` parameter is NOT part of the cache key. A suite generated with `include_negative=False` will be returned for `include_negative=True` requests if `spec_hash` matches. Similarly, `_save_suite()` (line 154-187) does not store `include_negative`. |
| 3 | **FIXED** | `src/shared/models/contracts.py:245-253` | `ContractTestSuite` does NOT have an `id` field — but this is actually correct for its use case. The `test_suites` DB table uses `(contract_id, framework)` as UNIQUE key (schema.py:135). The model is instantiated from DB rows via `_row_to_suite()` and directly from `_save_suite()`, neither needs an `id`. **Not a bug.** |
| 4 | **STILL EXISTS** | `src/contract_engine/services/asyncapi_parser.py:24,26` | Two `print()` statements in the module docstring example code block. Lines 24 and 26 contain `print(spec.title, spec.version)` and `print(ch.name, ch.address, ...)`. These are inside a docstring (lines 15-30), so they are **not executed at runtime**. However, they are still in the source file — technically not production code executing `print()`. **Low priority — cosmetic only since inside docstring.** |
| 5 | **FIXED** | `tests/conftest.py:190-197` | `mock_env_vars` fixture uses `monkeypatch.setenv()` which properly scopes the env var changes to the test function. The `monkeypatch` fixture automatically undoes changes on teardown. **No fixture pollution.** However, `tests/test_integration/test_architect_to_contracts.py:29-33` sets `os.environ["DATABASE_PATH"]` at module level OUTSIDE a fixture — this IS pollution if tests run in certain orders. |
| 6 | **STILL EXISTS (partial)** | `src/architect/services/prd_parser.py:441-453` | Entity extraction from headings (Strategy 2) uses pattern `^(#{2,4})\s+([A-Z][A-Za-z0-9_ ]*?)\s*\n` which matches any heading starting with a capital letter. The `_is_section_heading()` filter (line 449, 1180-1182) checks against `_SECTION_KEYWORDS` set (lines 1164-1177), but only catches exact matches. Headings like "Data Flow", "API Endpoints", "Technology Stack" with sub-words starting with capitals could be false-positively extracted as entities. Multi-word section titles not in the keyword set pass through. |
| 7 | **STILL EXISTS** | `src/shared/models/contracts.py:162-171`, `src/contract_engine/services/breaking_change_detector.py:9-48` | `BreakingChange` model is used for ALL change types including non-breaking ones (severity=`"info"` for `path_added`, `method_added`, `schema_added`, `optional_property_added`). The class name is misleading — `info`-severity changes are explicitly not breaking. The model should be `ContractChange` or the non-breaking detections should use a different model. |
| 8 | **STILL EXISTS** | `src/contract_engine/services/contract_store.py:33`, `src/contract_engine/services/implementation_tracker.py:29`, `src/contract_engine/services/schema_registry.py:24` | `_now_iso()` is defined as a `@staticmethod` in 3 separate classes. All have identical implementation: `datetime.now(timezone.utc).isoformat()`. Should be extracted to a shared utility. |
| 9 | **STILL EXISTS** | `src/codebase_intelligence/services/import_resolver.py:280-289,525`, `src/codebase_intelligence/parsers/typescript_parser.py:239` | 7 `os.path` calls found: `import_resolver.py` lines 282 (`os.path.join`), 285 (`os.path.join`), 286 (`os.path.join`), 287 (`os.path.isfile`), 289 (`os.path.isfile`), 525 (`os.path.join`); `typescript_parser.py` line 239 (`os.path.splitext`). The rest of these files already use `pathlib.Path`. |
| 10 | **STILL EXISTS** | `src/contract_engine/services/asyncapi_parser.py:53,387-417` | `_SUPPORTED_ASYNCAPI_MAJOR = "3"` on line 53. `_extract_asyncapi_version()` on lines 387-417 raises `ValueError` if the version doesn't start with `"3"`. AsyncAPI 2.x specs are rejected. No version adaptation/conversion is attempted. |
| 11 | **STILL EXISTS** | N/A (codebase-wide) | Return type hint coverage at ~63.6%. Not verified independently but accepted from prior audit. |
| 12 | **STILL EXISTS** | N/A (codebase-wide) | Docstring coverage at ~53.8%. Not verified independently but accepted from prior audit. |
| 13 | **STILL EXISTS** | See detailed locations below | 33 `except Exception` found across `src/`. Breakdown: `connection.py:62`, `architect/mcp_server.py:120,145,170`, `architect/routers/health.py:27`, `codebase_intelligence/routers/health.py:29,39`, `codebase_intelligence/mcp_server.py:171,206,263,304,326,361`, `contract_engine/services/asyncapi_validator.py:141`, `contract_engine/services/asyncapi_parser.py:558,621,649,734,902`, `contract_engine/services/openapi_validator.py:149,187`, `contract_engine/mcp_server.py:192`, `codebase_intelligence/services/ast_parser.py:102`, `codebase_intelligence/services/graph_analyzer.py:47,57,64`, `codebase_intelligence/services/semantic_searcher.py:68`, `codebase_intelligence/services/incremental_indexer.py:76,137,149`, `codebase_intelligence/services/service_interface_extractor.py:106`, `codebase_intelligence/services/symbol_extractor.py:61`, `contract_engine/routers/health.py:23`. Many of these are in MCP tool handlers (expected for top-level error handling) or parser skip-on-failure loops (acceptable). The health routers and `connection.py:close()` are also acceptable. Truly problematic broad catches: `ast_parser.py:102`, `graph_analyzer.py:47,57,64`, `incremental_indexer.py:76,137,149`, `semantic_searcher.py:68`, `symbol_extractor.py:61`. |
| 14 | **STILL EXISTS** | `src/shared/db/connection.py:45` | `conn.execute("PRAGMA busy_timeout=30000")` — the `30000` is a magic number. Should be extracted to a named constant or derived from the `timeout` constructor parameter (which is `30.0` seconds = 30000ms, but the relationship isn't explicit). |
| 15 | **STILL EXISTS** | N/A | Graph analysis and dead code detection are tested only for method existence (tests check that functions exist and return expected types, but don't verify correctness of analysis with known graph structures). |
| 16 | **STILL EXISTS** | `src/architect/services/prd_parser.py:27-50` | `_FRAMEWORKS` list (lines 32-37) does not include JWT, token, or auth-related frameworks. `_LANGUAGES` and other lists are technology categories, not auth patterns. The `_extract_technology_hints()` function (line 776) only scans for language/framework/database/message_broker. No detection for auth mechanisms (JWT, OAuth, SAML) as technology hints, caching layers (beyond Redis as DB), or API gateway patterns. |
| 17 | **STILL EXISTS** | `src/architect/services/prd_parser.py:776-804` | No context-clue based technology detection. `_first_mention()` does simple word-boundary matching. No inference from import statements, package.json references, or code patterns. Only direct text mentions of technology names are detected. |
| 18 | **STILL EXISTS** | `src/shared/models/contracts.py:152-159` | `SharedSchema` has a field named `schema` (line 155: `schema: dict[str, Any]`) which shadows `BaseModel.schema()` — a Pydantic v1 class method. In Pydantic v2 this is deprecated (replaced by `model_json_schema()`), so it works but generates a deprecation warning. Should be renamed to `schema_def` or `schema_data`. |
| 19 | **STILL EXISTS** | `src/contract_engine/services/test_generator.py:26` | `class TestGenerator:` — this class name starts with `Test` which causes pytest to attempt collection. pytest will emit a `PytestCollectionWarning` for this class. Should be renamed to `ContractTestGenerator` or configured in pytest to be ignored. |
| 20 | **STILL EXISTS** | Various | Additional precision items: (a) `datetime.utcnow` is deprecated in Python 3.12+ — found in 12 locations across `contracts.py`, `architect.py`, `common.py`, `decomposition.py`, `version_manager.py`. Should use `datetime.now(timezone.utc)`. (b) Type annotations could be more precise in several places. |

## New Issues Found

| # | Severity | Location | Description | Points Impact |
|---|----------|----------|-------------|---------------|
| N1 | **High** | `tests/test_integration/test_architect_to_contracts.py:29-33` | Module-level `os.environ["DATABASE_PATH"]` mutation outside of fixture scope. Sets env var at import time which can pollute other tests if import order changes. Uses `teardown_module()` for cleanup but this is fragile. | -5 test reliability |
| N2 | **High** | `tests/test_integration/test_codebase_indexing.py:43-51` | Same pattern — saves and restores env vars manually. Uses `tmp_path_factory` correctly but still mutates `os.environ` at fixture scope. At least this one properly restores values. | -3 test reliability |
| N3 | **Medium** | `src/architect/mcp_server.py:47-48` | Module-level database initialization: `pool = ConnectionPool(_database_path)` and `init_architect_db(pool)` execute at import time. If `DATABASE_PATH` isn't set or the path is invalid, the import itself fails. Same pattern in `contract_engine/mcp_server.py:48-50` and `codebase_intelligence/mcp_server.py:62-63`. | -3 robustness |
| N4 | **Medium** | `src/architect/mcp_server.py:126` | `get_service_map(project_name: str = None)` — `None` default for a typed parameter should be `str | None = None` for proper type safety. Same on line 151. Same pattern in `contract_engine/mcp_server.py:69,111,199,331` and `codebase_intelligence/mcp_server.py:138,139,140,213-217,271,333`. | -2 type safety |
| N5 | **Medium** | `src/shared/models/contracts.py:45-46,100,109,146,180,194,251` + `src/shared/models/architect.py:100,109,146` + `src/shared/models/common.py:15,33` | 12 uses of deprecated `datetime.utcnow` (deprecated since Python 3.12). Should use `datetime.now(timezone.utc)`. | -3 deprecation |
| N6 | **Low** | `src/contract_engine/mcp_server.py:63-103` | `create_contract` tool parameter is named `type` which shadows the Python builtin `type()`. Same issue on line 161 `validate_contract(..., type: str)`. | -1 code quality |
| N7 | **Low** | `src/codebase_intelligence/mcp_server.py:96` | `_VALID_LANGUAGES = {"python", "typescript", "csharp", "go"}` is a magic set. The `Language` enum from `src/shared/models/codebase.py` should be the single source of truth. If a language is added to the enum but not to this set, symbols get silently downgraded to `Language.PYTHON`. | -2 maintainability |
| N8 | **Low** | `src/shared/db/schema.py` | No `artifacts` table is defined in any of the schema init functions, but `test_codebase_indexing.py` tests `POST /api/artifacts` endpoint. The artifacts registration likely works through `indexed_files` table, but naming mismatch could cause confusion. | -1 clarity |
| N9 | **Low** | `src/codebase_intelligence/mcp_server.py:246-259` | Raw SQL query building with string concatenation in `get_symbols` tool. While parameterized (`?` placeholders), the dynamic `WHERE` clause construction is not ideal. Same pattern in `detect_dead_code` tool (lines 351-356). | -1 code quality |
| N10 | **Medium** | All 3 MCP servers | MCP servers catch `Exception` at tool handler level and return `{"error": str(exc)}` — this swallows stack traces and makes debugging difficult. The error response format is inconsistent (sometimes `{"error": ...}`, sometimes `[{"error": ...}]`). | -3 error handling |
| N11 | **Low** | `src/contract_engine/services/test_generator.py:26` | Class `TestGenerator` will trigger pytest `PytestCollectionWarning`. Combined with issue #19 — this affects test suite cleanliness. | -1 test quality |

## M6 Assessment

### ChromaDB Integration Status: COMPLETE

**Files reviewed:**
- `src/codebase_intelligence/storage/chroma_store.py` — Fully implemented
- `src/codebase_intelligence/services/semantic_indexer.py` — Fully implemented
- `src/codebase_intelligence/services/semantic_searcher.py` — Fully implemented

**Key findings:**
1. `ChromaStore` uses `chromadb.PersistentClient` with `DefaultEmbeddingFunction` (all-MiniLM-L6-v2) and cosine distance. Properly configured.
2. `add_chunks()` handles `None` metadata values by converting to empty strings (ChromaDB requirement).
3. `query()` method supports `where` filters for language and service_name.
4. `delete_by_file()` properly removes chunks by file_path metadata filter.
5. `SemanticIndexer.index_symbols()` creates `CodeChunk` objects from `SymbolDefinition` + source bytes, stores in ChromaDB, and back-links via `SymbolDB.update_chroma_id()`.
6. `SemanticSearcher.search()` converts ChromaDB distances to scores (`1.0 - distance`), handles edge cases (empty results, string line numbers, `None`-as-empty-string metadata).

**Potential issues:**
- `SemanticSearcher._convert_results()` catches broad `Exception` on line 68 — acceptable for ChromaDB resilience.
- No batch size limiting on `add_chunks()` — could be problematic for very large indexing jobs.
- `ChromaStore.__init__()` calls `self._collection.count()` which can be slow on large collections (called only once at init, acceptable).

## M7 MCP Tools Inventory

| # | Tool Name | Server | Registered | Params | Status |
|---|-----------|--------|------------|--------|--------|
| 1 | `decompose_prd` | Architect | Yes | `prd_text: str` | OK |
| 2 | `get_service_map` | Architect | Yes | `project_name: str = None` | OK (type annotation missing `| None`) |
| 3 | `get_domain_model` | Architect | Yes | `project_name: str = None` | OK (type annotation missing `| None`) |
| 4 | `create_contract` | Contract Engine | Yes | `service_name, type, version, spec, build_cycle_id` | OK (`type` shadows builtin) |
| 5 | `list_contracts` | Contract Engine | Yes | `page, page_size, service_name, contract_type, status` | OK |
| 6 | `get_contract` | Contract Engine | Yes | `contract_id: str` | OK |
| 7 | `validate_contract` | Contract Engine | Yes | `spec: dict, type: str` | OK (`type` shadows builtin) |
| 8 | `detect_breaking_changes` | Contract Engine | Yes | `contract_id: str, new_spec: dict = None` | OK |
| 9 | `mark_implementation` | Contract Engine | Yes | `contract_id, service_name, evidence_path` | OK |
| 10 | `get_unimplemented` | Contract Engine | Yes | `service_name: str = None` | OK |
| 11 | `generate_tests` | Contract Engine | Yes | `contract_id, framework, include_negative` | OK |
| 12 | `check_compliance` | Contract Engine | Yes | `contract_id, response_data` | OK |
| 13 | `index_file` | Codebase Intel | Yes | `file_path, service_name, source_base64, project_root` | OK |
| 14 | `search_code` | Codebase Intel | Yes | `query, language, service_name, top_k` | OK |
| 15 | `get_symbols` | Codebase Intel | Yes | `name, kind, language, service_name, file_path` | OK |
| 16 | `get_dependencies` | Codebase Intel | Yes | `file_path, depth, direction` | OK |
| 17 | `analyze_graph` | Codebase Intel | Yes | (none) | OK |
| 18 | `detect_dead_code` | Codebase Intel | Yes | `service_name: str = None` | OK |

**Total: 18 MCP tools registered across 3 servers.**

Missing from PRD expectation of 20 tools — likely 2 tools are registered via FastAPI REST endpoints only (not MCP). The FastAPI routers provide additional endpoints like `/api/health`, `/api/artifacts`, `/api/decompose` etc. that are not duplicated as MCP tools.

## M8 Integration Test Coverage

### Integration Tests (`tests/test_integration/`)

| Test File | Tests | Coverage |
|-----------|-------|----------|
| `test_architect_to_contracts.py` | 8 tests across 4 classes | Architect decomposition pipeline: POST /api/decompose, GET /api/service-map, GET /api/domain-model, contract stub validation, error cases, health endpoint |
| `test_codebase_indexing.py` | 6 tests across 5 classes | Full indexing pipeline: POST /api/artifacts, GET /api/symbols, POST /api/search, GET /api/dead-code, health endpoint |
| `test_docker_compose.py` | Not read (Docker-specific) | Docker Compose service orchestration |

### E2E Tests (`tests/e2e/api/`)

| Test File | Tests | Coverage |
|-----------|-------|----------|
| `test_architect_service.py` | Architect API endpoints | Direct HTTP tests against running service |
| `test_contract_engine_service.py` | Contract Engine API endpoints | Direct HTTP tests against running service |
| `test_codebase_intelligence_service.py` | Codebase Intel API endpoints | Direct HTTP tests against running service |
| `test_cross_service_workflow.py` | 2 tests | XS-01: Architect decompose -> Contract Engine store/validate/generate workflow |

**Key gaps:**
1. No integration test for the MCP tool interface (only REST API endpoints tested).
2. No integration test for breaking change detection workflow.
3. No integration test for implementation tracking workflow.
4. E2E tests require running Docker services — likely account for many of the 70 failures.

## Test Suite Current State

**Baseline: 663 passed, 70 failed, 17 errors, 17 skipped (326s)**

### Likely Failure Categories

1. **E2E tests requiring Docker** (~10-20 failures): `tests/e2e/api/` tests use `httpx.Client` with real URLs (`ARCHITECT_URL`, `CONTRACT_ENGINE_URL`). Without Docker services running, all these tests fail with connection errors.

2. **Integration tests with env pollution** (~5-10 failures): `test_architect_to_contracts.py` and `test_codebase_indexing.py` mutate `os.environ` at module level. Test ordering can cause state leakage.

3. **TestGenerator pytest collection warning** (~1 warning converted to error): `class TestGenerator` in `src/contract_engine/services/test_generator.py` may cause collection issues.

4. **Import/dependency issues** (~5-10 errors): If ChromaDB, tree-sitter, or other heavy dependencies fail to initialize, related test modules error at collection time.

5. **Test fixture dependencies** (~10-20 failures): Tests depending on module-scoped fixtures that fail during setup cascade into multiple test failures.

### Patterns in 17 Errors

Most likely causes:
- Module import errors (circular imports, missing optional dependencies)
- ChromaDB initialization failures in test environments
- Database file permission issues in CI/CD

## Recommended Fix Priority

### Priority 1 — Pipeline-blocking (fix first)
1. **Issue #2**: Test generator cache key ignores `include_negative` — add to cache key in `_get_cached()` and `_save_suite()` `UNIQUE` constraint
2. **Issue #5/N1/N2**: Test fixture env var pollution — use `monkeypatch` consistently
3. **Issue #19/N11**: Rename `TestGenerator` to `ContractTestGenerator` to avoid pytest collection warning

### Priority 2 — Quality improvements (high ROI)
4. **Issue #8**: Extract `_now_iso()` to shared utility
5. **Issue #9**: Replace `os.path` calls with `pathlib` in import_resolver and typescript_parser
6. **Issue #13**: Add specific exception types to the ~10 truly problematic broad catches
7. **Issue #14**: Extract `busy_timeout` magic number to named constant
8. **Issue #18**: Rename `SharedSchema.schema` to `SharedSchema.schema_def`
9. **Issue N5**: Replace deprecated `datetime.utcnow` with `datetime.now(timezone.utc)` (12 locations)

### Priority 3 — Deeper improvements (if time permits)
10. **Issue #7**: Rename `BreakingChange` to `ContractChange` or add `ChangeType` enum with breaking/non-breaking distinction
11. **Issue #6**: Expand `_SECTION_KEYWORDS` set or improve entity false-positive filtering
12. **Issue #10**: Consider AsyncAPI 2.x support or at least a clearer error message
13. **Issue #16/#17**: Expand technology detection to include auth patterns, caching, API gateways
14. **Issue N4**: Fix all `None` default parameter type annotations to use `| None`
15. **Issues #11/#12**: Improve return type hints and docstring coverage across codebase
16. **Issue N7**: Use `Language` enum as single source of truth instead of magic set

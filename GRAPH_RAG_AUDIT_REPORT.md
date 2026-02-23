# GRAPH_RAG_AUDIT_REPORT.md — Wave 3 Scoring

> **Date:** 2026-02-23
> **Auditor:** Claude Opus 4.6 (Automated, 5 Parallel Auditors)
> **Spec Authority:** `week8_graphrag/GRAPH_RAG_DESIGN.md` (Revision 1)
> **Test Baseline:** 81 passed, 0 failed (30.54s)

---

## Executive Summary

| Metric | Value |
|--------|-------|
| **Score** | **855 / 1100 (77.7%)** |
| **GO Threshold** | 900 / 1100 (81.8%) |
| **Verdict** | **CONDITIONAL NO-GO** |
| **CRITICAL Issues** | 5 (all in GATE-3 plumbing chain) |
| **P2 Issues** | 7 |
| **P3 Issues** | 7 |
| **Blocking Fix Items** | 4 (required for GO) |

**If all CRITICAL + P2 fixes are applied:** Projected score = **960/1100 (87.3%) = GO**

---

## Scoring Breakdown

### 1. Schema & Data Models — 80/100

| Item | Points | Status |
|------|--------|--------|
| NodeType enum (7 values match spec) | 20/20 | PASS |
| EdgeType enum (16 values match spec Section 10.1) | 20/20 | PASS |
| 9 dataclasses present with correct fields | 35/40 | DEVIATION: return types differ (dict vs dataclass) |
| `from __future__ import annotations` | 5/5 | PASS |
| Missing `get_neighbors()` method on KnowledgeGraph | -5 | FAIL |
| Extra `get_node_by_id()` on store (undocumented API) | 0 | ACCEPTABLE |

### 2. Knowledge Graph — 95/100

| Item | Points | Status |
|------|--------|--------|
| `nx.MultiDiGraph` (not DiGraph) | 15/15 | PASS |
| `to_json()` uses `node_link_data(G, edges="edges")` | 10/10 | PASS |
| `from_json()` with `multigraph=True, directed=True` | 10/10 | PASS |
| `compute_communities()` → undirected before Louvain, `seed=42` | 15/15 | PASS |
| `compute_pagerank()` with `alpha=0.85` | 10/10 | PASS |
| `get_ego_subgraph()` via `nx.ego_graph()` | 10/10 | PASS |
| `get_descendants()` via `single_source_shortest_path_length` | 10/10 | PASS |
| 14 public methods (spec Section 9.1) | 10/15 | FAIL: `get_neighbors()` missing |
| `graph` as attribute vs `@property` | 0 | DEVIATION (functionally equivalent) |

### 3. ChromaDB Store — 68/80

| Item | Points | Status |
|------|--------|--------|
| `PersistentClient(path=...)` | 10/10 | PASS |
| `DefaultEmbeddingFunction()` (not SentenceTransformer) | 10/10 | PASS (CR-4) |
| `metadata={"hnsw:space": "cosine"}` | 10/10 | PASS (CR-1) |
| Collection names `graph-rag-nodes` / `graph-rag-context` | 10/10 | PASS |
| `delete_collection()` + `get_or_create_collection()` pattern | 10/10 | PASS (CR-2) |
| Batch size 300 | 5/5 | PASS |
| None metadata → empty string | 5/5 | PASS |
| `n_results` guard: `min(n_results, count)` | 5/5 | PASS |
| Return types: `list[dict]` not `list[GraphRAGSearchResult]` | -5 | DEVIATION |
| `upsert_*()` returns `None` not `int` | -3 | DEVIATION |
| Missing `clear_all()` method | -2 | DEVIATION |

### 4. Indexer Pipeline — 157/200

| Item | Points | Status |
|------|--------|--------|
| 4 ConnectionPool params (own + CI + Architect + Contract) | 15/15 | PASS (INT-1/COMP-1) |
| Phase 1: Reads from all 3 external databases | 25/25 | PASS |
| `chroma_id` in symbols SQL | 5/5 | PASS (INT-3) |
| try/except per load step | 10/10 | PASS |
| service_interfaces parameter accepted | 5/5 | PASS |
| Node ID formats (file::, service::, symbol::, etc.) | 15/15 | PASS |
| PROVIDES_CONTRACT direction: service → contract | 5/5 | PASS |
| Event node ID: `event::{name}` (no service prefix) | 5/5 | PASS (SCH-1) |
| Symbol-to-entity matching with 7 suffixes | 10/10 | PASS |
| SHARED_UTILITY_PATTERNS exclusion | 5/5 | PASS (COMP-2) |
| PageRank + Louvain on undirected + seed=42 | 15/15 | PASS (NX-1) |
| ChromaDB population + snapshot persistence | 15/15 | PASS |
| **`_match_handlers_to_endpoints()` ABSENT** | **0/15** | **FAIL: No HANDLES_ENDPOINT edges ever created** |
| DOMAIN_RELATIONSHIP missing `cardinality` attr | -5 | FAIL |
| `via_endpoints` (plural, JSON array) vs `via_endpoint` (singular, str) | -3 | DEVIATION |
| Context record ID prefix `context::` vs spec `ctx::` | -5 | DEVIATION |
| OpenAPI method blacklist vs spec whitelist | -2 | DEVIATION |
| `build()` accepts `dict` not `str` param | 0 | DEVIATION (reasonable adaptation) |

### 5. Engine & Tools — 175/200

| Item | Points | Status |
|------|--------|--------|
| Tool 2: get_service_context (9-step algorithm) | 30/30 | PASS |
| Tool 3: query_graph_neighborhood | 25/25 | PASS |
| Tool 4: hybrid_search (n_results*3, formula, cache) | 30/30 | PASS |
| Tool 5: find_cross_service_impact (bidirectional BFS) | 25/25 | PASS |
| Tool 6: validate_service_boundaries (COMP-4/COMP-5) | 25/25 | PASS |
| Tool 7: check_cross_service_events (SCH-1 edge traversal) | 25/25 | PASS |
| Context assembler: markdown + truncate_to_budget | 20/20 | PASS |
| `_cached_undirected` attribute (NX-3) | 10/10 | PASS |
| **`force_rebuild=False` snapshot caching UNIMPLEMENTED** | **0/15** | **FAIL: Parameter accepted but ignored** |
| Where-filter location (store vs engine) | 0 | DEVIATION (functionally identical) |

### 6. Integration & Gating — 135/220

| Item | Points | Status |
|------|--------|--------|
| GraphRAGConfig: 11 fields, correct defaults | 25/25 | PASS |
| `_build_graph_rag_context()` exists | 10/10 | PASS |
| Layer 1 gating: `if not config.graph_rag.enabled` | 10/10 | PASS |
| Layer 2 gating: try/except around MCP calls | 10/10 | PASS |
| 5 env vars passed to subprocess | 10/10 | PASS |
| Not a new FSM state | 5/5 | PASS |
| `graph_rag_context` in builder config | 10/10 | PASS |
| `init_graph_rag_db()` correct schema | 15/15 | PASS |
| Adversarial scanner `graph_rag_client` code correct | 20/20 | PASS (code exists but unreachable) |
| Fix pass `graph_rag_client` code correct | 15/20 | DEVIATION: threshold values differ |
| Builder `graph_rag_context` code correct | 20/20 | PASS |
| Layer 3 gating: safe defaults on all functions | 10/10 | PASS |
| **INT-2: Pipeline does NOT pre-fetch service interfaces** | **0/15** | **CRITICAL: passes empty string** |
| **GATE-3: Client not stored in phase_artifacts** | **0/15** | **CRITICAL** |
| **GATE-3: gate_engine.py doesn't accept/pass client** | **0/15** | **CRITICAL** |
| **GATE-3: Layer4Scanner instantiated without client** | **0/15** | **CRITICAL** |
| **GATE-3: Full plumbing chain broken** | **0/10** | **CRITICAL: ADV suppression inoperative** |
| ADV-002 uses event matching not SERVICE_CALLS | -5 | DEVIATION |

### 7. Tests — 145/200

| Item | Points | Status |
|------|--------|--------|
| 81 tests total (matches spec target) | 20/20 | PASS |
| All 81 passing, 0 failures | 30/30 | PASS |
| test_knowledge_graph.py: 15/15 match | 15/15 | PASS |
| test_graph_rag_store.py: 11/12 match | 10/12 | FAIL: 1 missing |
| test_graph_rag_engine.py: 12/12 match | 12/12 | PASS |
| test_graph_rag_indexer.py: 14/15 match | 10/12 | FAIL: 1 missing (E2E test) |
| test_context_assembler.py: 4/5 match | 8/10 | FAIL: 1 merged |
| test_mcp_server.py: 6/7 match | 8/10 | FAIL: missing boundaries tool test |
| test_graph_rag_integration.py: 1/6 match | 5/20 | FAIL: 5 spec tests missing, all mock-only |
| test_graph_properties.py: 4/9 match | 7/15 | FAIL: 5 spec tests replaced |
| Test quality: real imports, not just mocks | 15/25 | DEVIATION: integration file is 100% mocks |
| Test quality: meaningful assertions | 15/25 | DEVIATION: MCP server tests shallow |

---

## All Findings by Severity

### CRITICAL (5 findings — blocks GO)

| ID | Auditor | File | Finding |
|----|---------|------|---------|
| C-1 | 2D | `pipeline.py:2023` | `service_interfaces_json=""` — pipeline does NOT pre-fetch service interfaces via CI MCP `get_service_interface` per spec INT-2/Section 5.7 |
| C-2 | 2D | `pipeline.py` | `GraphRAGClient` created in `_build_graph_rag_context()` is never stored in `state.phase_artifacts["graph_rag_client"]` per spec GATE-3 |
| C-3 | 2D | `gate_engine.py:56-62` | `QualityGateEngine.__init__()` does not accept/obtain `graph_rag_client`; no access to `phase_artifacts` |
| C-4 | 2D | `gate_engine.py:62` | `Layer4Scanner()` instantiated with no args — client never reaches scanner |
| C-5 | 2D | N/A | Full GATE-3 plumbing chain C-2→C-3→C-4 means ADV-001/ADV-002 false-positive suppression is completely inoperative despite scanner code being correctly written |

### P2 (7 findings — significant deviations)

| ID | Auditor | File | Finding |
|----|---------|------|---------|
| P2-1 | 2C | `mcp_server.py:88` | `force_rebuild=False` parameter accepted but completely ignored; no 300-second snapshot age check |
| P2-2 | 2B | `graph_rag_indexer.py` | `_match_handlers_to_endpoints()` method entirely absent — no HANDLES_ENDPOINT edges created |
| P2-3 | 2B | `graph_rag_indexer.py:551-554` | DOMAIN_RELATIONSHIP edges missing `cardinality` attribute (spec Section 3.3 requires it) |
| P2-4 | 2B | `graph_rag_indexer.py:992` | SERVICE_CALLS edge uses `via_endpoints` (plural, JSON array) instead of `via_endpoint` (singular, str) |
| P2-5 | 2B | `graph_rag_indexer.py` | Context record IDs use `context::` prefix instead of spec's `ctx::` |
| P2-6 | 2E | `test_graph_rag_integration.py` | All 6 tests are mock-only; 5 of 6 spec-required E2E tests (build_then_*) absent |
| P2-7 | 2E | `test_graph_properties.py` | 5 spec-required structural graph tests absent (orphan symbols, endpoint linkage, pagerank sum, community coverage, service-file connectivity) |

### P3 (7 findings — minor)

| ID | Auditor | File | Finding |
|----|---------|------|---------|
| P3-1 | 2A | `knowledge_graph.py` | Missing `get_neighbors()` method from spec Section 9.1 |
| P3-2 | 2A | `graph_rag_store.py` | `query_nodes()`/`query_contexts()` return `list[dict]` not `list[GraphRAGSearchResult]` |
| P3-3 | 2A | `graph_rag_store.py` | `upsert_nodes()`/`upsert_contexts()` return `None` not `int` |
| P3-4 | 2A | `graph_rag_store.py` | Missing `clear_all()` convenience method |
| P3-5 | 2D | `adversarial_patterns.py` | ADV-002 suppression uses event matching instead of spec's SERVICE_CALLS edge check |
| P3-6 | 2D | `fix_pass.py` | Impact boosting: jumps to P0 at >= 10 nodes instead of spec's "boost by one level" |
| P3-7 | 2B | `graph_rag_indexer.py` | OpenAPI endpoint parsing uses method blacklist instead of spec's explicit 8-method whitelist |

---

## Fix Priority for GO

To reach GO (900+), fix these in order:

| Priority | Finding | Points Recovered | Cumulative |
|----------|---------|-----------------|------------|
| 1 | C-2+C-3+C-4+C-5: Implement GATE-3 plumbing | +55 | 910 |
| 2 | C-1: Implement INT-2 pre-fetch | +15 | 925 |
| 3 | P2-1: Implement force_rebuild caching | +15 | 940 |
| 4 | P2-2: Implement HANDLES_ENDPOINT | +15 | 955 |
| 5 | P2-3: Add cardinality to DOMAIN_RELATIONSHIP | +5 | 960 |

**Minimum for GO:** Fix items 1-2 (GATE-3 + INT-2) = 925/1100

---

## Spec Validation Issues Landing Status

| Issue ID | Description | Landed? |
|----------|-------------|---------|
| INT-1 / COMP-1 / COMP-7 | 3 external ConnectionPools via env vars | YES |
| INT-2 | Pipeline pre-fetches service interfaces | **NO — pipeline passes empty string** |
| NX-1 | Louvain on undirected graph | YES |
| COMP-2 | _derive_service_edges with shared utility exclusion | YES |
| COMP-3 | OpenAPI-to-endpoint parsing | YES (minor: blacklist vs whitelist) |
| INT-3 | chroma_id from SQL symbols table | YES |
| INT-4 | ServiceStack serialization via json.dumps | YES (adapted for dict input) |
| INT-5 | Symbol ID translation (prefix prepend) | YES |
| CR-4 | DefaultEmbeddingFunction only | YES |
| NX-3 | Undirected graph caching | YES |
| CR-2 | delete_collection + get_or_create pattern | YES |
| INT-7 | Separate ChromaDB directory | YES |
| SCH-1 | Event node ID omits service_name | YES |
| COMP-4 / COMP-5 | isolated_files + services_declared | YES |
| GATE-3 | graph_rag_client through gate_engine | **NO — plumbing chain broken** |
| CR-1 | metadata dict style for cosine | YES |
| NX-2 | node_link_data key parameter (no change needed) | N/A |
| INT-6 | Sub-phase terminology (no change needed) | N/A |

**Landed: 13/15 addressable issues | NOT landed: 2 (INT-2, GATE-3)**

---

**Wave 3 Status: COMPLETE — Score 855/1100 — CONDITIONAL NO-GO — Proceeding to Wave 4 fixes**

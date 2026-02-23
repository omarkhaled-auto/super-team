# Week 8: Graph RAG Design — Completion Summary

> **Date:** 2026-02-23
> **Status:** APPROVED — Spec validated, all critical/major issues resolved
> **Deliverables:** 6 documents totaling ~350KB

---

## Design Overview

Graph RAG adds a **unified knowledge graph** that bridges the three isolated data stores in the super-team pipeline: Codebase Intelligence (NetworkX DiGraph + ChromaDB), Architect (service decomposition), and Contract Engine (API contracts). Currently, Builders construct services in isolation — when building `order-service`, they have no knowledge of `auth-service`'s API endpoints, shared domain entities, or event contracts. Quality gate scanners produce false positives because they cannot verify cross-service consumers. Fix loops cannot predict cross-service regressions.

The design introduces a new `src/graph_rag/` module within Build 1 that runs as a **fourth MCP server** (stdio transport, 7 new tools). It builds a `nx.MultiDiGraph` knowledge graph with 8 node types (service, file, symbol, contract, endpoint, domain_entity, event, community) and 13 edge types representing relationships like SERVICE_CALLS, EXPOSES_ENDPOINT, IMPLEMENTS_ENTITY, and PUBLISHES_EVENT. Two new ChromaDB collections (`graph-rag-nodes` and `graph-rag-context`) enable hybrid graph+vector retrieval. The knowledge graph is built once per pipeline run after contract registration and before builders launch.

The architecture was designed to be **fully gating-compatible** — when `graph_rag.enabled=False`, all operations are skipped and the existing pipeline runs identically. Triple-layer gating (config check, try/except, safe defaults) ensures zero risk to the existing system.

## Key Design Decisions

| Decision | Choice Made | Justification |
|---|---|---|
| NetworkX graph type | `nx.MultiDiGraph` | Preserves parallel edges lost by existing DiGraph; supports multiple relationship types between same nodes (NETWORKX_RESEARCH.md §1.1) |
| Relationship to existing graph | Runs alongside (not replaces) | Existing 8 CI MCP tools continue using the DiGraph unchanged; knowledge graph is a richer supergraph |
| ChromaDB collections | 2 new collections (`graph-rag-nodes`, `graph-rag-context`) | Separate from existing `code_chunks`; nodes for entity-level search, contexts for pre-assembled service summaries |
| Embedding model | `DefaultEmbeddingFunction()` (all-MiniLM-L6-v2) | Consistency with existing `code_chunks` collection; 384 dims, fastest sentence-transformer |
| Distance metric | Cosine (both collections) | Best for semantic similarity of text descriptions (CHROMADB_RESEARCH.md §2.4) |
| Community detection | Louvain (on undirected conversion) | Built into NetworkX, no external deps; handles disconnected graphs correctly |
| Data access pattern | Direct SQLite reads via ConnectionPool | Graph RAG subprocess gets 3 additional env vars (CI_DATABASE_PATH, ARCHITECT_DATABASE_PATH, CONTRACT_DATABASE_PATH) for read-only access |
| Service interface data | Pipeline pre-fetches via CI MCP `get_service_interface` tool | ServiceInterfaceExtractor computes on-the-fly from source files; not stored in any DB |
| New MCP tools | 7 tools | `build_knowledge_graph`, `get_service_context`, `query_graph_neighborhood`, `hybrid_search`, `find_cross_service_impact`, `validate_service_boundaries`, `check_cross_service_events` |
| Integration points | 4 in Build 3 pipeline, 2 in Build 2 agent-team | pipeline.py, adversarial_patterns.py, fix_pass.py, builder.py (Build 3); claude_md_generator.py, agents.py (Build 2) |
| Config gating | Triple-layer: config flag → try/except → safe defaults | Non-negotiable requirement; all parameters optional with defaults |
| Context token budget | 2000 tokens per service (configurable) | Priority-ranked truncation: endpoints → entities → events → dependencies |

## New Files to Create (Week 9)

| File | Purpose |
|---|---|
| `src/graph_rag/__init__.py` | Package marker |
| `src/graph_rag/mcp_server.py` | MCP server with 7 tools, module-level init with 5 ConnectionPools |
| `src/graph_rag/knowledge_graph.py` | `KnowledgeGraph` class wrapping `nx.MultiDiGraph` |
| `src/graph_rag/graph_rag_store.py` | `GraphRAGStore` class wrapping 2 ChromaDB collections |
| `src/graph_rag/graph_rag_indexer.py` | `GraphRAGIndexer` — full 5-phase build pipeline |
| `src/graph_rag/graph_rag_engine.py` | `GraphRAGEngine` — query algorithms for all 7 tools |
| `src/graph_rag/context_assembler.py` | `ContextAssembler` — structured context block assembly |
| `src/graph_rag/mcp_client.py` | `GraphRAGClient` — async wrapper for MCP tool calls |
| `src/shared/models/graph_rag.py` | All Graph RAG dataclasses and TypedDicts |
| `tests/test_knowledge_graph.py` | 15 unit tests for KnowledgeGraph |
| `tests/test_graph_rag_store.py` | 12 unit tests for GraphRAGStore |
| `tests/test_graph_rag_engine.py` | 12 unit tests for GraphRAGEngine |
| `tests/test_graph_rag_indexer.py` | 15 unit tests for GraphRAGIndexer |
| `tests/test_context_assembler.py` | 5 unit tests for ContextAssembler |
| `tests/test_mcp_server.py` | 7 MCP server tests |
| `tests/test_graph_rag_integration.py` | 6 integration tests |
| `tests/test_graph_properties.py` | 9 graph property tests |

**Total: 17 new files (8 source + 1 shared model + 8 test files)**

## Existing Files to Modify (Week 9)

| File | What Changes |
|---|---|
| `super-team/src/super_orchestrator/config.py` | Add `GraphRAGConfig` dataclass with 11 fields |
| `super-team/src/super_orchestrator/pipeline.py` | Add `_build_graph_rag_context()` method; call after contracts phase |
| `super-team/src/shared/db/schema.py` | Add `init_graph_rag_db()` for `graph_rag_snapshots` table |
| `super-team/src/quality_gate/adversarial_patterns.py` | Add optional `graph_rag_client` to `AdversarialScanner`; cross-service checks in ADV-001/ADV-002 |
| `super-team/src/run4/fix_pass.py` | Add optional `graph_rag_client` to `classify_priority()`; impact-based boosting |
| `super-team/src/run4/builder.py` | Add `graph_rag_context` to `write_fix_instructions()` |
| `agent-team-v15/src/agent_team_v15/claude_md_generator.py` | Add optional `graph_rag_context` parameter to `generate_claude_md()` |
| `agent-team-v15/src/agent_team_v15/agents.py` | Add optional `graph_rag_context` to `_append_contract_and_codebase_context()` |

**Total: 8 existing files modified (6 in super-team, 2 in agent-team-v15)**

## Research Quality Assessment

### NetworkX Research
- **Context7 queries:** Multiple targeted queries covering graph types, attributes, algorithms, serialization, subgraph extraction, heterogeneous graphs, performance, and vector store integration
- **Depth:** 1,260 lines / 44KB — comprehensive with exact method signatures and code examples
- **Key finding that changed the design:** `write_gpickle` is deprecated/removed in current NetworkX; `node_link_data`/`node_link_graph` is the recommended JSON serialization pattern. Louvain community detection requires undirected graph conversion.

### ChromaDB Research
- **Context7 queries:** Multiple queries covering client init, collections, embeddings, CRUD, queries, hybrid search, multi-collection patterns, performance, and GraphRAG patterns
- **Depth:** 1,320 lines / 43KB — comprehensive with exact current API signatures
- **Key finding that changed the design:** ChromaDB has no `collection.clear()` or `delete_all()` — must use `delete_collection` + `get_or_create_collection`. The `configuration` dict is the newer pattern but existing code uses `metadata` dict style. `DefaultEmbeddingFunction()` and `SentenceTransformerEmbeddingFunction(model_name="all-MiniLM-L6-v2")` are different class instances that should not be mixed.

## Validation Results

| Category | Count |
|---|---|
| Initial issues found | 20 |
| Critical (blocked implementation) | 3 |
| Major (required clarification) | 7 |
| Minor (cosmetic/style) | 10 |
| **After revision: Resolved** | **15** |
| **Not addressed (by design)** | **5** |
| **Unresolved** | **0** |

All 3 critical issues were resolved by adding environment variables for cross-database access and specifying the service interface data acquisition flow. All 7 major issues were resolved with complete algorithm specifications.

## Risks Carried into Week 9

| Risk | Severity | Mitigation |
|---|---|---|
| Data loading fails (missing databases) | Medium | try/except with partial data fallback; build result includes error list |
| MultiDiGraph JSON serialization size (>10MB for large projects) | Low | Typical projects ~2-5MB; gzip compression available if needed |
| ChromaDB embedding latency (3000+ nodes) | Low | all-MiniLM-L6-v2 is fastest model; batch upserts of 300; ~5-10s on CPU |
| Symbol-to-Entity name matching false positives | Low | Conservative matching: only class/interface/type symbols; exact base name match after suffix stripping |
| Windows subprocess startup (WinError 206) | Low | Config via env vars not CLI args; minimal args (`-m src.graph_rag.mcp_server`) |
| Community detection on disconnected graphs | Low | Louvain handles correctly; each component becomes own community |
| Gating failure causes pipeline crash | Low | Triple-layer protection tested in integration suite |

## Week 9 Readiness

**READY**

The design document (GRAPH_RAG_DESIGN.md, 127KB / 2,502 lines) contains:
- Complete graph schema with 8 node types and 13 edge types, all with Python type annotations
- Complete ChromaDB schema for 2 collections with exact metadata fields
- Complete algorithms for all 7 MCP tools using verified NetworkX and ChromaDB API calls
- Complete data population pipeline with 5 phases and full data flow specification
- Complete integration point modifications with gating at every entry point
- 81 specified tests across 8 test files
- 6-phase implementation sequence with explicit dependencies
- 11 configuration fields with types, defaults, and descriptions
- 7 documented risks with mitigations

A Week 9 implementation agent can build from this spec **without making a single design decision**.

---

## Document Inventory

| Document | Size | Purpose |
|---|---|---|
| `CODEBASE_EXPLORATION.md` | 66KB / 1,469 lines | Complete codebase analysis across all 3 builds |
| `NETWORKX_RESEARCH.md` | 44KB / 1,260 lines | Exhaustive Context7 NetworkX API reference |
| `CHROMADB_RESEARCH.md` | 43KB / 1,320 lines | Exhaustive Context7 ChromaDB API reference |
| `INTEGRATION_GAPS.md` | 36KB | 5 concrete gaps with graph query specifications |
| `GRAPH_RAG_DESIGN.md` | 127KB / 2,502 lines | Complete implementation specification (APPROVED) |
| `SPEC_VALIDATION.md` | 5KB | Validation report — APPROVED after revision |
| `WEEK8_COMPLETION_SUMMARY.md` | This file | Executive summary |

**Total research output: ~325KB across 7 documents**

---

*Week 8 complete. Week 9 implementation can begin.*

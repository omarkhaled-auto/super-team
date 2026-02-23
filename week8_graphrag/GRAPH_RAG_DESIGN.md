# GRAPH_RAG_DESIGN.md -- Week 9 Implementation Specification

> **Author:** Design Synthesizer Agent
> **Date:** 2026-02-23
> **Status:** REVISED -- Revision 1 addressing SPEC_VALIDATION.md findings
> **Inputs:** CODEBASE_EXPLORATION.md, NETWORKX_RESEARCH.md, CHROMADB_RESEARCH.md, INTEGRATION_GAPS.md

---

## Revision Notes (R1 -- 2026-02-23)

This revision addresses all 3 critical, 7 major, and 8 of 10 minor issues identified in SPEC_VALIDATION.md.

### Critical Fixes
- **INT-1 / COMP-1 / COMP-7:** Added three new environment variables (`CI_DATABASE_PATH`, `ARCHITECT_DATABASE_PATH`, `CONTRACT_DATABASE_PATH`) to the Graph RAG MCP server subprocess. Updated `mcp_server.py` module init, `GraphRAGIndexer` constructor, `GraphRAGConfig`, and env variable table. The indexer now creates dedicated `ConnectionPool` instances for each external database.
- **INT-2:** Specified how service interface data is obtained. The pipeline pre-fetches it by calling `get_service_interface` on the CI MCP server for each service, then passes the JSON-encoded result to `build_knowledge_graph` via a new `service_interfaces_json` parameter. Added Section 5.7 with detailed call flow.

### Major Fixes
- **NX-1:** Fixed Phase 3 build pipeline to convert MultiDiGraph to undirected before calling `louvain_communities`, consistent with Tool 6's approach.
- **COMP-2:** Fully specified the `_derive_service_edges()` algorithm, including cross-service import detection, SERVICE_CALLS edge creation, `via_endpoint` population, and shared utility module exclusion.
- **COMP-3:** Fully specified the OpenAPI-to-endpoint parsing algorithm, including JSON path traversal, method/path extraction, path parameter handling, and AsyncAPI handling for event nodes.
- **INT-3:** Corrected the `chroma_id` source column: now documented as coming from the SQL `symbols` table row, not the `SymbolDefinition` dataclass.
- **INT-4:** Specified `ServiceStack` to `str` serialization using `json.dumps(dataclasses.asdict(stack))`.
- **INT-5:** Specified ID format translation from `dependency_edges` table format (`file_path::symbol_name`) to knowledge graph node IDs (`symbol::file_path::symbol_name`) via a `f"symbol::{source_symbol}"` prefix prepend.
- **CR-4:** Clarified embedding function: use `DefaultEmbeddingFunction()` for consistency with the existing `code_chunks` collection. Added explicit warning against mixing embedding function classes.

### Minor Fixes
- **NX-3:** Added undirected graph caching in `hybrid_search` and `find_cross_service_impact` to avoid repeated `G.to_undirected()` copy overhead.
- **CR-2:** Specified `delete_all_nodes()` / `delete_all_contexts()` implementation using `delete_collection()` + `get_or_create_collection()` pattern.
- **INT-7:** Corrected the misleading claim in Section 2.2 about reading from the "same ChromaDB directory."
- **SCH-1:** Changed event node ID format to omit service_name, using `event::{event_name}` for shared event identity, enabling cross-service event matching.
- **COMP-4 / COMP-5:** Added computation logic for `isolated_files` and `services_declared` fields in the `validate_service_boundaries` algorithm.
- **GATE-3:** Specified how `graph_rag_client` is passed to `AdversarialScanner` through `gate_engine.py`.
- **CR-1:** Changed collection creation to use `metadata={"hnsw:space": "cosine"}` style for consistency with existing codebase.

### Issues Not Addressed (by design)
- **NX-2:** The `node_link_data` key parameter default is correct for our use case and the risk of key name collision is negligible (edge keys use EdgeType enum values). No change needed.
- **INT-6:** The "sub-phase" terminology is technically accurate since the Graph RAG build runs within the existing `contracts_registered` transition. Added a brief clarifying note but no structural change.

---

## Table of Contents

1. [Design Philosophy and Scope](#1-design-philosophy-and-scope)
2. [Architecture Overview](#2-architecture-overview)
3. [Graph Schema Design](#3-graph-schema-design)
4. [ChromaDB Schema Design](#4-chromadb-schema-design)
5. [Data Population Strategy](#5-data-population-strategy)
6. [Query Interface Design](#6-query-interface-design)
7. [Context Window Assembly](#7-context-window-assembly)
8. [Integration Points](#8-integration-points)
9. [File and Module Structure](#9-file-and-module-structure)
10. [Data Models](#10-data-models)
11. [Test Strategy](#11-test-strategy)
12. [Implementation Sequence](#12-implementation-sequence)
13. [Configuration](#13-configuration)
14. [Risk Assessment](#14-risk-assessment)

---

## 1. Design Philosophy and Scope

### 1.1 Problem Statement

The super-team pipeline operates three isolated data stores: a NetworkX DiGraph of file-level dependencies, a ChromaDB collection of code chunk embeddings, and SQLite tables of symbols/contracts/domain models. These stores are never queried together. As a result:

- **Builders** receive flat service definitions with no knowledge of sibling service APIs, shared entity schemas, or cross-service event contracts. This causes schema drift, missing integration endpoints, and duplicated data models.
- **Quality gate scanners** (Layers 3-4) produce false positives on dead event handlers and dead contracts because they cannot check cross-service consumers. They cannot weight violation severity by architectural centrality.
- **Fix loops** cannot route fixes to the correct service, predict cross-service regressions, or deduplicate violations sharing a common root cause.

### 1.2 What Will Be Measurably Different

After Graph RAG is implemented:

1. **Builder context includes a "Graph RAG context block"** -- a structured section injected into builder prompts containing: consumed/provided API schemas, shared entity definitions, event payload schemas, and dependency topology for the service being built. Measurable: builders produce correct cross-service API calls on the first attempt instead of failing at integration.

2. **Quality gate false positive rate decreases** -- ADV-001 (dead event handlers) and ADV-002 (dead contracts) queries cross-service the knowledge graph before flagging. Measurable: count of ADV-001/ADV-002 violations suppressed by cross-service evidence.

3. **Fix loop generates enriched fix instructions** -- each violation includes PageRank-weighted severity, dependency count warnings, and contract constraint annotations. Measurable: fix effectiveness rate (currently tracked in `check_convergence()`) increases; regression rate decreases.

4. **New MCP tools enable hybrid graph+vector queries** -- semantic search results are re-ranked by graph proximity and centrality. Measurable: relevance of returned context as judged by downstream builder success.

### 1.3 Explicit Out of Scope

- **Temporal/version graph analysis** (INTEGRATION_GAPS 5.5): Comparing graph snapshots across pipeline runs requires a graph diffing algorithm and historical query interface. This is valuable but adds complexity disproportionate to Week 9's timeline. Historical snapshots remain stored in `graph_snapshots` table for future use.
- **GPU-accelerated graph backends** (NetworkX backend dispatch to cugraph/graphblas): The knowledge graph will contain at most thousands of nodes (files + symbols + services + contracts + entities), well within in-memory Python dict-of-dicts performance. No backend dispatch is needed.
- **Chroma Cloud / AsyncHttpClient**: The existing codebase uses `PersistentClient`. We continue with `PersistentClient` for consistency.
- **LLM-generated community summaries**: Microsoft GraphRAG generates community summaries via LLM calls. This adds latency and cost. We use algorithmic community detection (Louvain) and deterministic summary construction instead.
- **Full-text search API** (`Search()`, `K()`, `Knn()`, `Rrf()`): These are Chroma Cloud features not reliably available in PersistentClient. We use the standard `collection.query()` API.

---

## 2. Architecture Overview

### 2.1 Placement Decision: New Module within Build 1

Graph RAG is implemented as a **new module** at `src/graph_rag/` within the super-team (Build 1) codebase. It is NOT a standalone service and NOT an extension of the existing `codebase_intelligence` module.

**Justification:**
- The knowledge graph unifies data from three existing modules (codebase_intelligence, architect, contract_engine). Placing it inside any one of them creates a circular dependency.
- A new module with its own MCP server follows the established pattern (3 existing MCP servers, each with a dedicated module).
- The module imports from `shared/models/` and `shared/db/` just like existing modules.
- It runs as a fourth MCP server in the stdio transport topology.

### 2.2 High-Level Component Diagram

```
+------------------------------------------------------------------+
|                        super-team/src/                            |
|                                                                   |
|  +------------------+  +-------------+  +-----------------+      |
|  | codebase_intel   |  | architect   |  | contract_engine |      |
|  |   mcp_server     |  |  mcp_server |  |   mcp_server    |      |
|  |   (8 tools)      |  |  (4 tools)  |  |   (10 tools)    |      |
|  +--------+---------+  +------+------+  +--------+--------+      |
|           |                   |                   |               |
|           |    Reads from     |    Reads from     |               |
|           v                   v                   v               |
|  +----------------------------------------------------------+    |
|  |                     graph_rag module                      |    |
|  |                                                           |    |
|  |  +-------------------+  +--------------------+            |    |
|  |  | knowledge_graph   |  | graph_rag_engine   |            |    |
|  |  | (NetworkX         |  | (hybrid query,     |            |    |
|  |  |  MultiDiGraph)    |  |  context assembly) |            |    |
|  |  +-------------------+  +--------------------+            |    |
|  |                                                           |    |
|  |  +-------------------+  +--------------------+            |    |
|  |  | graph_rag_store   |  | graph_rag_indexer  |            |    |
|  |  | (ChromaDB         |  | (population        |            |    |
|  |  |  collections)     |  |  pipeline)          |            |    |
|  |  +-------------------+  +--------------------+            |    |
|  |                                                           |    |
|  |  +-------------------+                                    |    |
|  |  | mcp_server        |                                    |    |
|  |  | (7 new tools)     |                                    |    |
|  |  +-------------------+                                    |    |
|  +----------------------------------------------------------+    |
|                                                                   |
|  +----------------------------------------------------------+    |
|  |                    shared/                                |    |
|  |  models/graph_rag.py  (new dataclasses)                   |    |
|  |  db/schema.py         (new table init)                    |    |
|  |  db/connection.py     (reused as-is)                      |    |
|  +----------------------------------------------------------+    |
+------------------------------------------------------------------+

MCP Transport:  All four servers use stdio (subprocess + stdin/stdout)
```

### 2.3 MCP Server Topology After Graph RAG

| Server | Module | Tool Count | Transport |
|--------|--------|-----------|-----------|
| Codebase Intelligence | `src.codebase_intelligence.mcp_server` | 8 (unchanged) | stdio |
| Architect | `src.architect.mcp_server` | 4 (unchanged) | stdio |
| Contract Engine | `src.contract_engine.mcp_server` | 10 (unchanged) | stdio |
| **Graph RAG** | **`src.graph_rag.mcp_server`** | **7 (new)** | **stdio** |

No existing MCP servers are modified. The Graph RAG server reads from the same SQLite databases as existing servers (read-only access to CI, Architect, and Contract Engine databases) and writes only to its own dedicated stores (`./data/graph_rag.db` for snapshots, `./data/graph_rag_chroma` for its own ChromaDB collections). It does NOT share a ChromaDB directory with the existing `code_chunks` collection. (Addresses INT-7)

---

## 3. Graph Schema Design

### 3.1 Graph Type: `nx.MultiDiGraph`

**Decision:** Use `nx.MultiDiGraph` instead of the existing `nx.DiGraph`.

**Justification from NETWORKX_RESEARCH.md Section 1.1 and 6.3:**
- The existing DiGraph loses parallel edges between the same file pair (INTEGRATION_GAPS 4.4: "The NetworkX graph loses all but the last edge per file pair").
- The knowledge graph must represent multiple relationship types between the same nodes (e.g., service A both `CALLS` and `SUBSCRIBES_TO` service B). `MultiDiGraph` supports this via the `key` parameter on edges.
- All DiGraph algorithms (PageRank, BFS, topological sort, shortest path, ego_graph) work on MultiDiGraph. Per NETWORKX_RESEARCH.md Section 1.1: MultiDiGraph is "Directed + allows parallel edges."
- Edge access uses `MG.edges[u, v, key]` syntax (NETWORKX_RESEARCH.md Section 6.3).

**The knowledge graph does NOT replace the existing Build 1 DiGraph.** It runs alongside it. The existing `graph_builder.py` DiGraph continues to serve the existing 8 CI MCP tools unchanged. The knowledge graph is a separate, richer graph that incorporates data from all three existing stores.

### 3.2 Node Types

Every node in the knowledge graph has a `node_type` attribute (str) that determines its schema. Node IDs are prefixed strings to ensure global uniqueness.

#### Node Type: `file`

| Attribute | Python Type | Description | Source |
|-----------|------------|-------------|--------|
| `node_type` | `str` | Always `"file"` | Literal |
| `file_path` | `str` | Absolute or project-relative file path | `graph_builder.py` node ID |
| `language` | `str` | One of `Language` enum values | `graph_builder.py` node attr |
| `service_name` | `str` | Owning service (empty string if unknown) | `graph_builder.py` node attr |
| `pagerank` | `float` | Cached PageRank score (0.0 default) | Computed at index time |

**Node ID format:** `file::{file_path}` (e.g., `file::src/services/auth.py`)

#### Node Type: `symbol`

| Attribute | Python Type | Description | Source |
|-----------|------------|-------------|--------|
| `node_type` | `str` | Always `"symbol"` | Literal |
| `symbol_name` | `str` | Qualified name | `SymbolDefinition.symbol_name` |
| `kind` | `str` | One of `SymbolKind` enum values | `SymbolDefinition.kind` |
| `language` | `str` | Language | `SymbolDefinition.language` |
| `service_name` | `str` | Owning service | `SymbolDefinition.service_name` |
| `file_path` | `str` | Containing file | `SymbolDefinition.file_path` |
| `line_start` | `int` | Start line | `SymbolDefinition.line_start` |
| `line_end` | `int` | End line | `SymbolDefinition.line_end` |
| `signature` | `str` | Function/method signature | `SymbolDefinition.signature` |
| `is_exported` | `bool` | Whether symbol is public | `SymbolDefinition.is_exported` |
| `chroma_id` | `str` | Back-link to ChromaDB code_chunks | SQL `symbols.chroma_id` column (not a `SymbolDefinition` dataclass field -- read via `SELECT chroma_id FROM symbols`) |

**Node ID format:** `symbol::{file_path}::{symbol_name}` (e.g., `symbol::src/services/auth.py::AuthService`)

#### Node Type: `service`

| Attribute | Python Type | Description | Source |
|-----------|------------|-------------|--------|
| `node_type` | `str` | Always `"service"` | Literal |
| `service_name` | `str` | Service identifier | `ServiceDefinition.name` |
| `domain` | `str` | Business domain | `ServiceDefinition.domain` |
| `description` | `str` | Service description | `ServiceDefinition.description` |
| `stack` | `str` | Technology stack string | `json.dumps(dataclasses.asdict(ServiceDefinition.stack))` -- `ServiceStack` is a dataclass, serialize via `dataclasses.asdict()` then `json.dumps()` (Addresses INT-4) |
| `estimated_loc` | `int` | Estimated lines of code | `ServiceDefinition.estimated_loc` |

**Node ID format:** `service::{service_name}` (e.g., `service::auth-service`)

#### Node Type: `contract`

| Attribute | Python Type | Description | Source |
|-----------|------------|-------------|--------|
| `node_type` | `str` | Always `"contract"` | Literal |
| `contract_id` | `str` | UUID from Contract Engine | `ContractEntry.id` |
| `contract_type` | `str` | `"openapi"`, `"asyncapi"`, `"json_schema"` | `ContractEntry.type` |
| `version` | `str` | Semantic version | `ContractEntry.version` |
| `service_name` | `str` | Providing service | `ContractEntry.service_name` |
| `status` | `str` | `"active"`, `"deprecated"` | `ContractEntry.status` |

**Node ID format:** `contract::{contract_id}` (e.g., `contract::550e8400-e29b-41d4-a716-446655440000`)

#### Node Type: `endpoint`

| Attribute | Python Type | Description | Source |
|-----------|------------|-------------|--------|
| `node_type` | `str` | Always `"endpoint"` | Literal |
| `method` | `str` | HTTP method (GET, POST, PUT, DELETE) | Extracted from contract spec or code |
| `path` | `str` | URL path (e.g., `/api/users/{id}`) | Extracted from contract spec or code |
| `service_name` | `str` | Owning service | From contract or code context |
| `handler_symbol` | `str` | Symbol ID of the handler function (empty if unknown) | From `ServiceInterface.endpoints` |

**Node ID format:** `endpoint::{service_name}::{method}::{path}` (e.g., `endpoint::auth-service::GET::/api/users/{id}`)

#### Node Type: `domain_entity`

| Attribute | Python Type | Description | Source |
|-----------|------------|-------------|--------|
| `node_type` | `str` | Always `"domain_entity"` | Literal |
| `entity_name` | `str` | Domain entity name | `DomainEntity.name` |
| `description` | `str` | Entity description | `DomainEntity.description` |
| `owning_service` | `str` | Service that owns this entity | `DomainEntity.owning_service` |
| `fields_json` | `str` | JSON-serialized field list | `json.dumps(DomainEntity.fields)` |

**Node ID format:** `domain_entity::{entity_name}` (e.g., `domain_entity::Order`)

#### Node Type: `event`

| Attribute | Python Type | Description | Source |
|-----------|------------|-------------|--------|
| `node_type` | `str` | Always `"event"` | Literal |
| `event_name` | `str` | Event identifier | From `ServiceInterface.events_published/consumed` |
| `channel` | `str` | Channel/topic name | From event extraction |

**Node ID format:** `event::{event_name}` (e.g., `event::order.created`)

**Design note (Addresses SCH-1):** Event node IDs intentionally omit `service_name` to create a shared event identity. When two services interact through the same event name, they both connect (via `PUBLISHES_EVENT` and `CONSUMES_EVENT` edges) to the same event node. This enables cross-service event matching in Tool 7 (`check_cross_service_events`). The publishing/consuming services are discoverable via in-edge traversal, not via the event node's attributes.

### 3.3 Edge Types

Every edge has a `relation` attribute (str) as its MultiDiGraph key. Edges also carry typed attributes.

#### Edge: `CONTAINS_FILE`

- **Direction:** `service` -> `file`
- **Key:** `"CONTAINS_FILE"`
- **Attributes:** None additional
- **Meaning:** Service owns this file

#### Edge: `DEFINES_SYMBOL`

- **Direction:** `file` -> `symbol`
- **Key:** `"DEFINES_SYMBOL"`
- **Attributes:** None additional
- **Meaning:** File defines this symbol

#### Edge: `IMPORTS`

- **Direction:** `file` -> `file`
- **Key:** `"IMPORTS"`
- **Attributes:**

| Attribute | Python Type | Description |
|-----------|------------|-------------|
| `imported_names` | `str` | JSON-serialized list of imported names |
| `line` | `int` | Source line number |

- **Meaning:** Source file imports from target file

#### Edge: `CALLS`

- **Direction:** `symbol` -> `symbol`
- **Key:** `"CALLS"`
- **Attributes:**

| Attribute | Python Type | Description |
|-----------|------------|-------------|
| `line` | `int` | Source line number |

- **Meaning:** Source symbol calls target symbol

#### Edge: `INHERITS`

- **Direction:** `symbol` -> `symbol`
- **Key:** `"INHERITS"`
- **Attributes:** None additional
- **Meaning:** Source symbol inherits from target symbol

#### Edge: `IMPLEMENTS`

- **Direction:** `symbol` -> `symbol`
- **Key:** `"IMPLEMENTS"`
- **Attributes:** None additional
- **Meaning:** Source symbol implements target symbol (interface)

#### Edge: `PROVIDES_CONTRACT`

- **Direction:** `service` -> `contract`
- **Key:** `"PROVIDES_CONTRACT"`
- **Attributes:** None additional
- **Meaning:** Service provides/publishes this contract

#### Edge: `EXPOSES_ENDPOINT`

- **Direction:** `contract` -> `endpoint`
- **Key:** `"EXPOSES_ENDPOINT"`
- **Attributes:** None additional
- **Meaning:** Contract defines this endpoint

#### Edge: `HANDLES_ENDPOINT`

- **Direction:** `symbol` -> `endpoint`
- **Key:** `"HANDLES_ENDPOINT"`
- **Attributes:** None additional
- **Meaning:** Symbol (handler function) implements this endpoint

#### Edge: `OWNS_ENTITY`

- **Direction:** `service` -> `domain_entity`
- **Key:** `"OWNS_ENTITY"`
- **Attributes:** None additional
- **Meaning:** Service owns this domain entity

#### Edge: `REFERENCES_ENTITY`

- **Direction:** `service` -> `domain_entity`
- **Key:** `"REFERENCES_ENTITY"`
- **Attributes:** None additional
- **Meaning:** Service references (but does not own) this entity

#### Edge: `IMPLEMENTS_ENTITY`

- **Direction:** `symbol` -> `domain_entity`
- **Key:** `"IMPLEMENTS_ENTITY"`
- **Attributes:** None additional
- **Meaning:** Code symbol implements this domain entity (matched by name similarity)

#### Edge: `PUBLISHES_EVENT`

- **Direction:** `service` -> `event`
- **Key:** `"PUBLISHES_EVENT"`
- **Attributes:** None additional
- **Meaning:** Service publishes this event

#### Edge: `CONSUMES_EVENT`

- **Direction:** `service` -> `event`
- **Key:** `"CONSUMES_EVENT"`
- **Attributes:** None additional
- **Meaning:** Service subscribes to this event

#### Edge: `SERVICE_CALLS`

- **Direction:** `service` -> `service`
- **Key:** `"SERVICE_CALLS"`
- **Attributes:**

| Attribute | Python Type | Description |
|-----------|------------|-------------|
| `via_endpoint` | `str` | Endpoint node ID being called |

- **Meaning:** Source service calls target service's API

#### Edge: `DOMAIN_RELATIONSHIP`

- **Direction:** `domain_entity` -> `domain_entity`
- **Key:** `"DOMAIN_RELATIONSHIP"`
- **Attributes:**

| Attribute | Python Type | Description |
|-----------|------------|-------------|
| `relationship_type` | `str` | One of `RelationshipType` enum values |
| `cardinality` | `str` | Cardinality string (e.g., `"1:N"`) |

- **Meaning:** Domain-level relationship between entities

### 3.4 Node/Edge Types Considered and Rejected

| Candidate | Reason for Rejection |
|-----------|---------------------|
| `test_suite` node type | Tests are already tracked as `symbol` nodes with `kind="function"` and names starting with `test_`. Adding a separate node type adds schema complexity without enabling queries that filtering by `kind` + name pattern cannot already serve. |
| `docker_service` node type | Docker Compose services are ephemeral deployment artifacts, not architectural entities. The `service` node type already captures the logical service. Docker-specific metadata (ports, networks, memory limits) changes per pipeline run and does not belong in the knowledge graph. |
| `TESTED_BY` edge type | Requires automated test-to-implementation mapping that relies on naming conventions (fragile). Out of scope for Week 9. Can be added later by matching `test_*` symbol names to production symbol names. |
| `shared_schema` node type | The Contract Engine has a `shared_schemas` table, but schema sharing is better modeled as `domain_entity` nodes referenced by multiple services via `REFERENCES_ENTITY` edges. |
| Undirected edges | All relationships in the codebase are inherently directional (imports flow, calls flow, ownership). No undirected edges are needed. When bidirectional traversal is required, we use `undirected=True` on `ego_graph()`. |

---

## 4. ChromaDB Schema Design

### 4.1 Collection Architecture: Two Collections

**Decision:** Two collections, not one and not three+.

**Justification:**
- The existing `code_chunks` collection (in `chroma_store.py`) stores symbol-level code embeddings. We leave it untouched.
- We need to embed two distinct types of text: (1) node descriptions for the knowledge graph, and (2) relationship/context summaries for community-level retrieval. Both use the same embedding model and same distance metric, but separating them allows independent scaling and avoids metadata filter overhead on every query.
- Per CHROMADB_RESEARCH.md Section 7.1: "Use MULTIPLE collections when data is fundamentally different in nature." Node descriptions and relationship context are fundamentally different texts.

### 4.2 Collection: `graph_rag_nodes`

**Purpose:** Embed textual descriptions of knowledge graph nodes for semantic retrieval.

**Embedding model:** `DefaultEmbeddingFunction()` -- same class as the existing `code_chunks` collection for consistency (internally uses `all-MiniLM-L6-v2`, 384 dimensions). Per CHROMADB_RESEARCH.md Section 3.2, this model offers good quality with fast speed. (Addresses CR-4: Week 9 implementers MUST always use `DefaultEmbeddingFunction()` and NEVER `SentenceTransformerEmbeddingFunction` for Graph RAG collections, to ensure embedding compatibility if any code path retrieves collections with the default function.)

**Distance metric:** `cosine` -- per CHROMADB_RESEARCH.md Section 2.5: "Use cosine for text-based node/edge embeddings since sentence transformer models typically produce embeddings optimized for cosine similarity."

**Creation code (Addresses CR-1 -- uses `metadata` dict style consistent with existing codebase):**
```python
from chromadb.utils.embedding_functions import DefaultEmbeddingFunction

collection = client.get_or_create_collection(
    name="graph-rag-nodes",
    embedding_function=DefaultEmbeddingFunction(),
    metadata={"hnsw:space": "cosine"}
)
```

**Document structure (what text is embedded):**

| Node Type | Embedded Text Template |
|-----------|----------------------|
| `file` | `"File: {file_path}. Language: {language}. Service: {service_name}."` |
| `symbol` | `"Symbol: {symbol_name} ({kind}) in {file_path}. Signature: {signature}. Service: {service_name}."` |
| `service` | `"Service: {service_name}. Domain: {domain}. Description: {description}. Stack: {stack}."` |
| `contract` | `"Contract: {contract_type} v{version} for {service_name}. Status: {status}."` |
| `endpoint` | `"Endpoint: {method} {path} on {service_name}."` |
| `domain_entity` | `"Domain Entity: {entity_name}. Description: {description}. Owned by: {owning_service}. Fields: {fields_summary}."` |
| `event` | `"Event: {event_name} on channel {channel}."` (publishers/consumers discoverable via graph edges, not stored on node per SCH-1 fix) |

**Metadata schema:**

| Field | Python Type | Description |
|-------|------------|-------------|
| `node_id` | `str` | Knowledge graph node ID (e.g., `"service::auth-service"`) |
| `node_type` | `str` | One of the 7 node types |
| `service_name` | `str` | Owning/associated service (empty string if none) |
| `language` | `str` | Programming language (empty string if N/A) |
| `community_id` | `int` | Louvain community ID (-1 if not yet computed) |
| `pagerank` | `float` | PageRank score (0.0 if not computed) |

**ChromaDB record ID:** Same as the knowledge graph node ID (e.g., `"service::auth-service"`). This creates a direct link: ChromaDB record ID == graph node ID.

### 4.3 Collection: `graph_rag_context`

**Purpose:** Embed pre-assembled context blocks for service-level and community-level retrieval. These are longer text summaries that combine information from multiple nodes.

**Embedding model:** `DefaultEmbeddingFunction()` -- same model and class as `graph-rag-nodes` collection.

**Distance metric:** `cosine`

**Creation code:**
```python
collection = client.get_or_create_collection(
    name="graph-rag-context",
    embedding_function=DefaultEmbeddingFunction(),
    metadata={"hnsw:space": "cosine"}
)
```

**Document types stored:**

1. **Service context summaries:** Pre-assembled text describing a service's full interface -- endpoints, events, consumed APIs, owned entities.
2. **Community summaries:** Deterministic summaries of Louvain communities -- member services, key files, dominant relationships.

**Metadata schema:**

| Field | Python Type | Description |
|-------|------------|-------------|
| `context_type` | `str` | `"service_context"` or `"community_summary"` |
| `service_name` | `str` | Service name (for service contexts) or empty string |
| `community_id` | `int` | Community ID (for community summaries) or -1 |
| `node_count` | `int` | Number of nodes summarized |
| `edge_count` | `int` | Number of edges summarized |

**ChromaDB record ID:**
- Service contexts: `"ctx::service::{service_name}"` (e.g., `"ctx::service::auth-service"`)
- Community summaries: `"ctx::community::{community_id}"` (e.g., `"ctx::community::3"`)

### 4.4 Collection Alternatives Considered and Rejected

| Alternative | Reason for Rejection |
|-------------|---------------------|
| Single unified collection with `record_type` metadata filter | Per CHROMADB_RESEARCH.md Section 7.4, single collection with filters adds "filter overhead" on every query. Node descriptions and context summaries have very different text lengths and query patterns. |
| Three collections (nodes + relationships + contexts) | Relationship descriptions are short and infrequent. Embedding them separately yields a tiny collection with poor HNSW quality. Relationship data is better queried via graph traversal (exact, not approximate). |
| Separate collection per node type (7 collections) | Excessive fragmentation. Most queries need to search across node types. Per CHROMADB_RESEARCH.md Section 7.2: "ChromaDB does NOT natively support cross-collection queries." |
| Using existing `code_chunks` collection with additional metadata | Pollutes the existing collection used by CI MCP tools. Violates separation of concerns. Different lifecycle (Graph RAG rebuild vs incremental file indexing). |

---

## 5. Data Population Strategy

### 5.1 Population Trigger: Explicit Build via MCP Tool

**Decision:** Graph RAG population is triggered by an explicit MCP tool call (`build_knowledge_graph`), NOT by individual artifact registration events.

**Justification:**
- The knowledge graph requires data from ALL three stores (CI graph + SQLite symbols, Architect domain model + service map, Contract Engine contracts). These stores are populated at different pipeline phases. Building the knowledge graph incrementally as each store updates would require complex consistency management.
- The pipeline has a natural point where all three stores are populated: after `contracts_registering` phase and before `builders_running` phase. A single `build_knowledge_graph` call at this point ensures consistency.
- Full rebuild is fast for the expected graph size (hundreds to low thousands of nodes). Per NETWORKX_RESEARCH.md Section 7.2: "Bare node: ~300-500 bytes." A 5000-node graph with 15000 edges fits in ~10MB RAM.

### 5.2 Data Flow: Build Pipeline

```
build_knowledge_graph() MCP tool called
    |
    v
Phase 1: LOAD EXISTING DATA
    |   (Addresses INT-1 / COMP-1 / COMP-7: Indexer uses three additional
    |    ConnectionPool instances for external databases, obtained via env vars)
    |
    |-- Read NetworkX DiGraph from graph_db.load_snapshot()
    |     Source: CI database (CI_DATABASE_PATH env var, default ./data/codebase_intel.db)
    |-- Read all symbols from SQL: SELECT file_path, symbol_name, kind, language,
    |     service_name, line_start, line_end, signature, docstring, is_exported,
    |     parent_symbol, chroma_id FROM symbols
    |     Source: CI database (same ConnectionPool as above)
    |-- Read all dependency_edges from SQL: SELECT source_file, target_file, relation,
    |     line, imported_names, source_symbol, target_symbol FROM dependency_edges
    |     Source: CI database (same ConnectionPool as above)
    |-- Read service map from service_map_store (latest)
    |     Source: Architect database (ARCHITECT_DATABASE_PATH env var, default ./data/architect.db)
    |-- Read domain model from domain_model_store (latest)
    |     Source: Architect database (same ConnectionPool as above)
    |-- Read all contracts from contract_store (list all)
    |     Source: Contract Engine database (CONTRACT_DATABASE_PATH env var, default ./data/contracts.db)
    |-- Read all service interfaces via CI MCP server's get_service_interface tool
    |     (Addresses INT-2: service interfaces are computed on-the-fly from source
    |      files by ServiceInterfaceExtractor, NOT stored in any database. The Graph
    |      RAG indexer obtains this data by calling the get_service_interface MCP tool
    |      on the CI MCP server for each service in the service map. See Section 5.7
    |      for detailed call flow.)
    |
    v
Phase 2: BUILD KNOWLEDGE GRAPH (NetworkX MultiDiGraph)
    |-- Create service nodes from ServiceMap.services
    |-- Create domain_entity nodes from DomainModel.entities
    |-- Create domain_entity->domain_entity edges from DomainModel.relationships
    |-- Create file nodes from DiGraph nodes (copy node attrs)
    |-- Create service->file edges (CONTAINS_FILE) using file service_name attr
    |-- Create file->file edges (IMPORTS) from DiGraph edges
    |-- Create symbol nodes from symbols table
    |-- Create file->symbol edges (DEFINES_SYMBOL)
    |-- Create symbol->symbol edges (CALLS/INHERITS/IMPLEMENTS) from dependency_edges table
    |     (Addresses INT-5: dependency_edges.source_symbol uses format "file_path::symbol_name"
    |      but knowledge graph symbol node IDs use "symbol::file_path::symbol_name". Translation:
    |      graph_node_id = f"symbol::{dep_edge['source_symbol']}" for source, and
    |      graph_node_id = f"symbol::{dep_edge['target_symbol']}" for target.
    |      Only create edge if both source and target nodes exist in the graph.)
    |-- Create contract nodes from contracts table
    |-- Create service->contract edges (PROVIDES_CONTRACT)
    |-- Create endpoint nodes from contract specs (parse OpenAPI paths)
    |-- Create contract->endpoint edges (EXPOSES_ENDPOINT)
    |-- Create event nodes from service interfaces
    |-- Create service->event edges (PUBLISHES_EVENT / CONSUMES_EVENT)
    |-- Match handler symbols to endpoints (HANDLES_ENDPOINT)
    |-- Match symbols to domain entities by name (IMPLEMENTS_ENTITY)
    |-- Derive service->service edges (SERVICE_CALLS) from cross-service file imports
    |-- Derive service->domain_entity edges (OWNS_ENTITY / REFERENCES_ENTITY)
    |
    v
Phase 3: COMPUTE GRAPH METRICS
    |-- Compute PageRank: pr = nx.pagerank(G, alpha=0.85)
    |-- Store pagerank as node attribute on all nodes
    |-- Convert to undirected for community detection: G_undirected = G.to_undirected()
    |-- Compute Louvain communities: nx.community.louvain_communities(G_undirected, seed=42)
    |     (Addresses NX-1: Louvain requires undirected graph; calling on MultiDiGraph
    |      produces ambiguous results due to parallel edge weight inflation)
    |-- Cache G_undirected for later use in hybrid_search (Addresses NX-3)
    |-- Store community_id as node attribute on all nodes
    |
    v
Phase 4: POPULATE CHROMADB
    |-- Clear and rebuild graph-rag-nodes collection
    |   |-- For each node: generate description text, upsert with metadata
    |   |-- Batch upsert in groups of 300 (per CHROMADB_RESEARCH.md Section 8.1)
    |
    |-- Clear and rebuild graph-rag-context collection
    |   |-- For each service: assemble service context summary, upsert
    |   |-- For each community: assemble community summary, upsert
    |
    v
Phase 5: PERSIST KNOWLEDGE GRAPH
    |-- Serialize to JSON: nx.node_link_data(G, edges="edges")
    |-- Store in graph_rag_snapshots table (new SQLite table)
    |
    v
DONE -- return GraphRAGBuildResult
```

### 5.3 Full Rebuild vs Incremental: Full Rebuild

**Decision:** Full rebuild on every `build_knowledge_graph` call.

**Justification:**
- The knowledge graph is built once per pipeline run, not continuously updated.
- Full rebuild ensures consistency -- no stale edges from deleted files, no orphan nodes.
- Expected rebuild time: <5 seconds for a typical project (hundreds of files, tens of services).
- ChromaDB `upsert()` is idempotent (CHROMADB_RESEARCH.md Section 4.5), so re-inserting the same data is safe.
- Incremental updates would require change tracking across three separate stores, adding significant complexity for minimal time savings.

### 5.4 Consistency Between Graph and ChromaDB

- Both are populated in a single synchronous function call.
- ChromaDB collections are cleared (all records deleted) before repopulation to prevent stale entries.
- ChromaDB record IDs match graph node IDs, ensuring a direct 1:1 mapping.
- If population fails mid-way, the old graph snapshot remains in SQLite (the new snapshot is only written on success). ChromaDB collections may be partially updated, but the next `build_knowledge_graph` call will do a clean rebuild.

### 5.5 Endpoint-to-Handler Matching Algorithm

To create `HANDLES_ENDPOINT` edges (Gap 7 in INTEGRATION_GAPS: "No Contract-Code Linkage"):

1. For each `endpoint` node, extract `method` and `path`.
2. For each service's `ServiceInterface.endpoints` (from `service_interface_extractor`), match by HTTP method and path pattern.
3. The `ServiceInterface` endpoint entries contain the handler function name and file path.
4. Create a `HANDLES_ENDPOINT` edge from the matching `symbol` node to the `endpoint` node.
5. If no handler is found, the endpoint remains unlinked (this is useful data: an endpoint in the contract with no implementing handler).

### 5.6 Symbol-to-DomainEntity Matching Algorithm

To create `IMPLEMENTS_ENTITY` edges (Gap 3 in INTEGRATION_GAPS: "No Domain-to-Code Traceability"):

1. For each `domain_entity` node, extract `entity_name` (e.g., `"Order"`).
2. For each `symbol` node with `kind` in `("class", "interface", "type")`:
   - Compute normalized names: lowercase, strip common suffixes (`Service`, `Model`, `Schema`, `Entity`, `Repository`, `Controller`, `Handler`).
   - If the symbol's normalized name matches the entity's normalized name, create an `IMPLEMENTS_ENTITY` edge.
3. Example: `DomainEntity("Order")` matches `Symbol("OrderService")`, `Symbol("OrderModel")`, `Symbol("OrderSchema")`, `Symbol("Order")`.

### 5.7 Service Interface Data Acquisition (Addresses INT-2)

Service interface data (endpoints, events published/consumed, handler functions) is NOT stored in any database. It is computed on-the-fly by `ServiceInterfaceExtractor`, which parses source files using `ASTParser` and `SymbolExtractor`. The Graph RAG indexer cannot import and instantiate these classes directly because it runs in its own MCP server subprocess without access to the source file tree.

**Solution:** The Graph RAG indexer obtains service interface data by calling the `get_service_interface` MCP tool on the Codebase Intelligence MCP server. This requires a live MCP session to the CI server.

**Call flow:**
```python
# In GraphRAGIndexer._load_existing_data():
# The indexer receives an optional ci_mcp_session (MCP ClientSession) at construction time.
# If available, it calls get_service_interface for each service.

service_interfaces: dict[str, dict] = {}
if self._ci_mcp_session is not None:
    for service_name in service_map.services:
        try:
            result = await self._ci_mcp_session.call_tool(
                "get_service_interface",
                {"service_name": service_name}
            )
            service_interfaces[service_name] = result
        except Exception as e:
            errors.append(f"Failed to get interface for {service_name}: {e}")
```

**How the CI MCP session is obtained:** The pipeline (`_build_graph_rag_context()` in `pipeline.py`) already has an active MCP client session to the CI server. When it launches the Graph RAG MCP server and calls `build_knowledge_graph`, it passes the CI server's connection info as a tool parameter:

```python
# In the build_knowledge_graph MCP tool handler:
# The tool receives an optional ci_server_command/ci_server_args parameter set.
# If provided, the indexer spawns a temporary MCP client session to the CI server
# to call get_service_interface for each service.
```

**Alternative (simpler, preferred):** Since the pipeline orchestrator (`pipeline.py`) already has MCP sessions to all servers, the pipeline pre-fetches all service interface data BEFORE calling `build_knowledge_graph`:

```python
# In _build_graph_rag_context() in pipeline.py:
service_interfaces = {}
for service_name in service_map.services:
    try:
        result = await ci_client.call_tool("get_service_interface", {"service_name": service_name})
        service_interfaces[service_name] = result
    except Exception:
        pass  # Partial data is acceptable

# Pass pre-fetched data to Graph RAG build
await graph_rag_client.call_tool("build_knowledge_graph", {
    "project_name": project_name,
    "service_interfaces_json": json.dumps(service_interfaces)  # Pre-fetched data
})
```

**Decision:** Use the "pipeline pre-fetch" approach. This avoids the complexity of the Graph RAG server needing its own MCP client connection to the CI server. The `build_knowledge_graph` tool gains a new optional parameter `service_interfaces_json: str = ""` (JSON-encoded dict). If provided, the indexer deserializes it and uses it directly. If not provided, service interface data is empty and event/endpoint nodes from service interfaces are skipped.

**Updated `build_knowledge_graph` parameters:**

| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| `project_name` | `str` | No | `""` | Project name filter |
| `force_rebuild` | `bool` | No | `True` | Skip rebuild if recent snapshot exists |
| `service_interfaces_json` | `str` | No | `""` | JSON-encoded dict of pre-fetched service interface data |

### 5.8 Derive Service Edges Algorithm (Addresses COMP-2)

The `_derive_service_edges()` method creates `SERVICE_CALLS` edges between service nodes based on cross-service file-level imports.

**Algorithm:**
```python
def _derive_service_edges(self) -> None:
    """Create SERVICE_CALLS edges from cross-service file imports.

    Logic:
    1. Iterate all IMPORTS edges (file -> file).
    2. For each IMPORTS edge, check if source and target files belong to
       different services.
    3. If yes, record a cross-service call from source_service to target_service.
    4. Aggregate: one SERVICE_CALLS edge per unique (source_service, target_service) pair.
    5. Populate via_endpoint by matching the imported file to any endpoint node
       in the target service.
    """
    G = self._knowledge_graph.graph

    # Step 1: Collect cross-service imports
    cross_service_imports: dict[tuple[str, str], list[str]] = {}  # (src_svc, tgt_svc) -> [target_file_ids]

    # Define shared utility patterns to exclude (Addresses COMP-2 shared utility concern)
    SHARED_UTIL_PATTERNS = {"shared/", "common/", "utils/", "lib/", "helpers/"}

    for u, v, k, d in G.edges(keys=True, data=True):
        if k != "IMPORTS":
            continue

        u_svc = G.nodes.get(u, {}).get("service_name", "")
        v_svc = G.nodes.get(v, {}).get("service_name", "")

        # Skip same-service imports
        if not u_svc or not v_svc or u_svc == v_svc:
            continue

        # Skip imports of shared utility modules
        v_path = G.nodes.get(v, {}).get("file_path", "")
        if any(pattern in v_path for pattern in SHARED_UTIL_PATTERNS):
            continue

        pair = (u_svc, v_svc)
        cross_service_imports.setdefault(pair, []).append(v)

    # Step 2: Create SERVICE_CALLS edges
    for (src_svc, tgt_svc), target_files in cross_service_imports.items():
        src_node = f"service::{src_svc}"
        tgt_node = f"service::{tgt_svc}"

        if src_node not in G or tgt_node not in G:
            continue

        # Step 3: Find via_endpoint -- check if any target file contains
        # a symbol that HANDLES_ENDPOINT for an endpoint in the target service
        via_endpoint = ""
        for target_file in target_files:
            # Find symbols defined in this file
            for _, sym_node, ek, _ in G.out_edges(target_file, keys=True, data=True):
                if ek != "DEFINES_SYMBOL":
                    continue
                # Check if this symbol handles an endpoint
                for _, ep_node, ep_key, _ in G.out_edges(sym_node, keys=True, data=True):
                    if ep_key == "HANDLES_ENDPOINT":
                        via_endpoint = ep_node
                        break
                if via_endpoint:
                    break
            if via_endpoint:
                break

        G.add_edge(src_node, tgt_node, key="SERVICE_CALLS",
                   via_endpoint=via_endpoint,
                   import_count=len(target_files))
```

### 5.9 OpenAPI-to-Endpoint Parsing Algorithm (Addresses COMP-3)

The `_parse_contract_endpoints()` method extracts endpoint nodes from OpenAPI and AsyncAPI contract specs.

**Algorithm:**
```python
def _parse_contract_endpoints(self, contract_node_id: str,
                                contract_type: str,
                                spec_json: str,
                                service_name: str) -> list[tuple[str, dict]]:
    """Parse a contract spec to extract endpoint or event nodes.

    Args:
        contract_node_id: Graph node ID of the contract
        contract_type: "openapi" or "asyncapi" or "json_schema"
        spec_json: JSON string of the full contract spec
        service_name: Owning service name

    Returns:
        List of (node_id, node_attrs) tuples for endpoint/event nodes,
        plus edges are added directly to the graph.
    """
    try:
        spec = json.loads(spec_json)
    except (json.JSONDecodeError, TypeError):
        return []

    nodes = []
    G = self._knowledge_graph.graph

    if contract_type == "openapi":
        # OpenAPI 3.x: paths are under spec["paths"]
        # OpenAPI 2.x (Swagger): also under spec["paths"]
        paths = spec.get("paths", {})

        for path, path_item in paths.items():
            if not isinstance(path_item, dict):
                continue

            # HTTP methods defined in OpenAPI
            HTTP_METHODS = {"get", "post", "put", "delete", "patch", "options", "head", "trace"}

            for method in HTTP_METHODS:
                if method not in path_item:
                    continue

                operation = path_item[method]
                method_upper = method.upper()

                # Node ID uses the path as-is (including path parameters like {id})
                node_id = f"endpoint::{service_name}::{method_upper}::{path}"

                node_attrs = {
                    "node_type": "endpoint",
                    "method": method_upper,
                    "path": path,
                    "service_name": service_name,
                    "handler_symbol": "",  # Populated later by _match_handlers_to_endpoints
                    "operation_id": operation.get("operationId", ""),
                    "summary": operation.get("summary", ""),
                }

                G.add_node(node_id, **node_attrs)
                G.add_edge(contract_node_id, node_id, key="EXPOSES_ENDPOINT")
                nodes.append((node_id, node_attrs))

    elif contract_type == "asyncapi":
        # AsyncAPI: channels are under spec["channels"]
        channels = spec.get("channels", {})

        for channel_name, channel_item in channels.items():
            if not isinstance(channel_item, dict):
                continue

            # Extract event names from publish/subscribe operations
            for op_type in ("publish", "subscribe"):
                op = channel_item.get(op_type, {})
                if not op:
                    continue

                event_name = op.get("operationId", channel_name)
                # Event nodes use the shared ID format (no service prefix, per SCH-1 fix)
                node_id = f"event::{event_name}"

                if node_id not in G:
                    G.add_node(node_id, **{
                        "node_type": "event",
                        "event_name": event_name,
                        "channel": channel_name,
                    })

                # publish = this service publishes; subscribe = this service consumes
                service_node = f"service::{service_name}"
                if op_type == "publish":
                    G.add_edge(service_node, node_id, key="PUBLISHES_EVENT")
                else:
                    G.add_edge(service_node, node_id, key="CONSUMES_EVENT")

    # json_schema contracts do not define endpoints or events directly
    # They define shared schemas, which are modeled as domain_entity nodes elsewhere

    return nodes
```

---

## 6. Query Interface Design

### 6.1 New MCP Tools (7 total)

All tools are registered on the Graph RAG MCP server (`src.graph_rag.mcp_server`).

---

#### Tool 1: `build_knowledge_graph`

**Purpose:** Build (or rebuild) the knowledge graph from all existing data stores.

**Parameters:**

| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| `project_name` | `str` | No | `""` | Project name filter for service map/domain model lookup |
| `force_rebuild` | `bool` | No | `True` | If False and a recent snapshot exists (< 5 min old), skip rebuild |
| `service_interfaces_json` | `str` | No | `""` | JSON-encoded dict of pre-fetched service interface data (Addresses INT-2). The pipeline pre-fetches this by calling `get_service_interface` on the CI MCP server for each service, then passes the result here. If empty, event/endpoint nodes from service interfaces are skipped. |

**Return type:** `dict` with schema:
```python
{
    "success": bool,
    "node_count": int,
    "edge_count": int,
    "node_types": dict[str, int],   # {"file": 150, "symbol": 800, ...}
    "edge_types": dict[str, int],   # {"IMPORTS": 300, "CALLS": 500, ...}
    "community_count": int,
    "build_time_ms": int,
    "services_indexed": list[str],
    "errors": list[str]
}
```

**Algorithm:**
1. Execute the full Phase 1-5 pipeline described in Section 5.2.
2. If `force_rebuild` is False, check `graph_rag_snapshots` table for a snapshot with `created_at` within the last 300 seconds. If found, load it and return stats without rebuilding.
3. Return stats dict on success, or `{"success": False, "errors": [...]}` on failure.

---

#### Tool 2: `get_service_context`

**Purpose:** Retrieve a structured context block for a specific service, including its consumed/provided APIs, events, entities, and dependency topology. This is the primary tool for builder context injection.

**Parameters:**

| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| `service_name` | `str` | Yes | -- | Target service name |
| `include_consumed_apis` | `bool` | No | `True` | Include APIs this service calls |
| `include_provided_apis` | `bool` | No | `True` | Include APIs this service exposes |
| `include_events` | `bool` | No | `True` | Include published/consumed events |
| `include_entities` | `bool` | No | `True` | Include owned/referenced domain entities |
| `include_dependencies` | `bool` | No | `True` | Include service dependency topology |
| `max_depth` | `int` | No | `2` | Max traversal depth for dependency topology |

**Return type:** `dict` with schema:
```python
{
    "service_name": str,
    "provided_endpoints": list[dict],   # [{"method": "GET", "path": "/api/users", "handler": "get_users", "contract_id": "..."}]
    "consumed_endpoints": list[dict],   # [{"method": "POST", "path": "/auth/validate", "provider_service": "auth-service"}]
    "events_published": list[dict],     # [{"event_name": "order.created", "channel": "orders"}]
    "events_consumed": list[dict],      # [{"event_name": "payment.completed", "publisher_service": "payment-service"}]
    "owned_entities": list[dict],       # [{"name": "Order", "fields": [...]}]
    "referenced_entities": list[dict],  # [{"name": "User", "owning_service": "auth-service", "fields": [...]}]
    "depends_on": list[str],            # ["auth-service", "payment-service"]
    "depended_on_by": list[str],        # ["notification-service", "analytics-service"]
    "context_text": str                 # Pre-formatted context block (see Section 7)
}
```

**Algorithm:**
```python
# 1. Find service node
service_node_id = f"service::{service_name}"
if service_node_id not in G:
    return {"service_name": service_name, "error": "Service not found in knowledge graph"}

# 2. Get provided endpoints
provided_contracts = [
    (u, v, k, d) for u, v, k, d in G.out_edges(service_node_id, keys=True, data=True)
    if k == "PROVIDES_CONTRACT"
]
provided_endpoints = []
for _, contract_node, _, _ in provided_contracts:
    for _, ep_node, ep_key, ep_data in G.out_edges(contract_node, keys=True, data=True):
        if ep_key == "EXPOSES_ENDPOINT":
            ep_attrs = G.nodes[ep_node]
            provided_endpoints.append({
                "method": ep_attrs["method"],
                "path": ep_attrs["path"],
                "handler": ep_attrs.get("handler_symbol", ""),
                "contract_id": G.nodes[contract_node].get("contract_id", "")
            })

# 3. Get consumed endpoints (via SERVICE_CALLS edges)
consumed_endpoints = []
for _, target_service, k, d in G.out_edges(service_node_id, keys=True, data=True):
    if k == "SERVICE_CALLS":
        via_endpoint = d.get("via_endpoint", "")
        if via_endpoint and via_endpoint in G:
            ep_attrs = G.nodes[via_endpoint]
            consumed_endpoints.append({
                "method": ep_attrs["method"],
                "path": ep_attrs["path"],
                "provider_service": G.nodes[target_service].get("service_name", "")
            })

# 4. Get events published
events_published = []
for _, event_node, k, _ in G.out_edges(service_node_id, keys=True, data=True):
    if k == "PUBLISHES_EVENT":
        ev = G.nodes[event_node]
        events_published.append({"event_name": ev["event_name"], "channel": ev.get("channel", "")})

# 5. Get events consumed
events_consumed = []
for _, event_node, k, _ in G.out_edges(service_node_id, keys=True, data=True):
    if k == "CONSUMES_EVENT":
        ev = G.nodes[event_node]
        # Find publisher
        publishers = [u for u, _, ek, _ in G.in_edges(event_node, keys=True, data=True) if ek == "PUBLISHES_EVENT"]
        publisher_name = G.nodes[publishers[0]].get("service_name", "") if publishers else ""
        events_consumed.append({
            "event_name": ev["event_name"],
            "publisher_service": publisher_name
        })

# 6. Get owned entities
owned_entities = []
for _, entity_node, k, _ in G.out_edges(service_node_id, keys=True, data=True):
    if k == "OWNS_ENTITY":
        ent = G.nodes[entity_node]
        owned_entities.append({
            "name": ent["entity_name"],
            "fields": json.loads(ent.get("fields_json", "[]"))
        })

# 7. Get referenced entities
referenced_entities = []
for _, entity_node, k, _ in G.out_edges(service_node_id, keys=True, data=True):
    if k == "REFERENCES_ENTITY":
        ent = G.nodes[entity_node]
        referenced_entities.append({
            "name": ent["entity_name"],
            "owning_service": ent["owning_service"],
            "fields": json.loads(ent.get("fields_json", "[]"))
        })

# 8. Get dependency topology via BFS
depends_on = []
for _, target, k, _ in G.out_edges(service_node_id, keys=True, data=True):
    if k == "SERVICE_CALLS" and G.nodes[target].get("node_type") == "service":
        depends_on.append(G.nodes[target]["service_name"])

depended_on_by = []
for source, _, k, _ in G.in_edges(service_node_id, keys=True, data=True):
    if k == "SERVICE_CALLS" and G.nodes[source].get("node_type") == "service":
        depended_on_by.append(G.nodes[source]["service_name"])

# 9. Assemble context_text (see Section 7)
context_text = assemble_service_context(service_name, provided_endpoints, consumed_endpoints,
                                         events_published, events_consumed,
                                         owned_entities, referenced_entities,
                                         depends_on, depended_on_by)
```

---

#### Tool 3: `query_graph_neighborhood`

**Purpose:** Extract the N-hop neighborhood around any node in the knowledge graph.

**Parameters:**

| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| `node_id` | `str` | Yes | -- | Knowledge graph node ID |
| `radius` | `int` | No | `2` | Hop count |
| `undirected` | `bool` | No | `True` | Include both incoming and outgoing edges |
| `filter_node_types` | `str` | No | `""` | Comma-separated node types to include (empty = all) |
| `filter_edge_types` | `str` | No | `""` | Comma-separated edge types to include (empty = all) |
| `max_nodes` | `int` | No | `50` | Maximum nodes to return |

**Return type:** `dict` with schema:
```python
{
    "center_node": dict,            # Node attributes of the center
    "nodes": list[dict],            # [{id, node_type, ...attrs}, ...]
    "edges": list[dict],            # [{source, target, relation, ...attrs}, ...]
    "total_nodes_in_neighborhood": int,  # Before max_nodes cap
    "truncated": bool
}
```

**Algorithm:**
```python
# 1. Extract ego graph
subgraph = nx.ego_graph(G, node_id, radius=radius, undirected=undirected)

# 2. Apply node type filter
if filter_node_types:
    allowed_types = set(filter_node_types.split(","))
    keep_nodes = [n for n in subgraph.nodes() if G.nodes[n].get("node_type") in allowed_types or n == node_id]
    subgraph = subgraph.subgraph(keep_nodes).copy()

# 3. Apply edge type filter
if filter_edge_types:
    allowed_edges = set(filter_edge_types.split(","))
    # For MultiDiGraph, filter by key
    remove_edges = [(u, v, k) for u, v, k in subgraph.edges(keys=True) if k not in allowed_edges]
    for u, v, k in remove_edges:
        subgraph.remove_edge(u, v, key=k)

# 4. Rank by distance, then PageRank
distances = nx.single_source_shortest_path_length(subgraph, node_id)
ranked = sorted(subgraph.nodes(), key=lambda n: (distances.get(n, 999), -G.nodes[n].get("pagerank", 0.0)))

# 5. Cap at max_nodes
total = len(ranked)
truncated = total > max_nodes
ranked = ranked[:max_nodes]

# 6. Build result
final_subgraph = subgraph.subgraph(ranked)
nodes = [{"id": n, **dict(G.nodes[n])} for n in final_subgraph.nodes()]
edges = [{"source": u, "target": v, "relation": k, **dict(d)} for u, v, k, d in final_subgraph.edges(keys=True, data=True)]
```

---

#### Tool 4: `hybrid_search`

**Purpose:** Combine semantic vector search with graph-structural re-ranking.

**Parameters:**

| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| `query` | `str` | Yes | -- | Natural language query |
| `n_results` | `int` | No | `10` | Number of results |
| `node_types` | `str` | No | `""` | Comma-separated node types to search (empty = all) |
| `service_name` | `str` | No | `""` | Filter to specific service |
| `anchor_node_id` | `str` | No | `""` | If set, re-rank results by graph distance to this node |
| `semantic_weight` | `float` | No | `0.6` | Weight for semantic score (0.0-1.0) |
| `graph_weight` | `float` | No | `0.4` | Weight for graph proximity score (0.0-1.0) |

**Return type:** `dict` with schema:
```python
{
    "results": list[dict],  # [{node_id, node_type, score, semantic_score, graph_score, distance, ...attrs}]
    "query": str,
    "anchor_node_id": str
}
```

**Algorithm:**
```python
# 1. Build ChromaDB where filter
where_filter = {}
conditions = []
if node_types:
    types = node_types.split(",")
    if len(types) == 1:
        conditions.append({"node_type": types[0]})
    else:
        conditions.append({"node_type": {"$in": types}})
if service_name:
    conditions.append({"service_name": service_name})
if len(conditions) == 1:
    where_filter = conditions[0]
elif len(conditions) > 1:
    where_filter = {"$and": conditions}

# 2. Semantic search on graph-rag-nodes collection
chroma_results = nodes_collection.query(
    query_texts=[query],
    n_results=n_results * 3,  # Over-fetch for re-ranking
    where=where_filter if where_filter else None,
    include=["documents", "metadatas", "distances"]
)

# 3. Convert to scored list
candidates = []
for i, node_id in enumerate(chroma_results["ids"][0]):
    semantic_score = 1.0 - chroma_results["distances"][0][i]  # cosine distance to similarity
    candidates.append({
        "node_id": node_id,
        "semantic_score": semantic_score,
        "metadata": chroma_results["metadatas"][0][i]
    })

# 4. Graph-structural re-ranking (Addresses NX-3: use cached undirected graph)
if anchor_node_id and anchor_node_id in G:
    # Use cached undirected graph from _compute_metrics() phase to avoid
    # O(V+E) copy on every hybrid_search call. Falls back to on-demand
    # conversion if cache is not available (e.g., graph loaded from snapshot).
    G_undirected = getattr(self, '_cached_undirected', None) or G.to_undirected()
    try:
        path_lengths = nx.single_source_shortest_path_length(G_undirected, anchor_node_id)
    except nx.NetworkXError:
        path_lengths = {}

    max_distance = max(path_lengths.values()) if path_lengths else 1
    for c in candidates:
        dist = path_lengths.get(c["node_id"], max_distance + 1)
        c["distance"] = dist
        # Normalize: closer = higher score
        c["graph_score"] = 1.0 - (dist / (max_distance + 1))
else:
    # No anchor: use PageRank as graph score
    max_pr = max((G.nodes[n].get("pagerank", 0.0) for n in G.nodes()), default=1.0) or 1.0
    for c in candidates:
        pr = G.nodes.get(c["node_id"], {}).get("pagerank", 0.0)
        c["graph_score"] = pr / max_pr
        c["distance"] = -1

# 5. Compute combined score
for c in candidates:
    c["score"] = (semantic_weight * c["semantic_score"]) + (graph_weight * c["graph_score"])

# 6. Sort by combined score, take top n_results
candidates.sort(key=lambda c: -c["score"])
results = candidates[:n_results]

# 7. Enrich with node attributes
for r in results:
    if r["node_id"] in G:
        r.update(dict(G.nodes[r["node_id"]]))
```

---

#### Tool 5: `find_cross_service_impact`

**Purpose:** Given a file or symbol, find all cross-service entities that would be affected by a change.

**Parameters:**

| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| `node_id` | `str` | Yes | -- | File or symbol node ID |
| `max_depth` | `int` | No | `3` | Maximum traversal depth |

**Return type:** `dict` with schema:
```python
{
    "source_node": str,
    "source_service": str,
    "impacted_services": list[dict],  # [{"service_name": str, "impact_count": int, "impact_paths": list[list[str]]}]
    "impacted_contracts": list[dict], # [{"contract_id": str, "service_name": str, "endpoints_affected": list[str]}]
    "impacted_entities": list[dict],  # [{"entity_name": str, "owning_service": str}]
    "total_impacted_nodes": int
}
```

**Algorithm:**
```python
# 1. Find all descendants within max_depth
descendants_set = set()
queue = [(node_id, 0)]
visited = {node_id}
while queue:
    current, depth = queue.pop(0)
    if depth >= max_depth:
        continue
    for _, successor, key, _ in G.out_edges(current, keys=True, data=True):
        if successor not in visited:
            visited.add(successor)
            descendants_set.add(successor)
            queue.append((successor, depth + 1))

# 2. Also check predecessors (who depends on this node)
predecessors_set = set()
queue = [(node_id, 0)]
visited_rev = {node_id}
while queue:
    current, depth = queue.pop(0)
    if depth >= max_depth:
        continue
    for predecessor, _, key, _ in G.in_edges(current, keys=True, data=True):
        if predecessor not in visited_rev:
            visited_rev.add(predecessor)
            predecessors_set.add(predecessor)
            queue.append((predecessor, depth + 1))

all_impacted = descendants_set | predecessors_set

# 3. Group by service
source_service = G.nodes[node_id].get("service_name", "")
impacted_by_service = {}
for n in all_impacted:
    svc = G.nodes[n].get("service_name", "")
    if svc and svc != source_service:
        impacted_by_service.setdefault(svc, []).append(n)

# 4. Find impacted contracts
impacted_contracts = [
    n for n in all_impacted if G.nodes.get(n, {}).get("node_type") == "contract"
]

# 5. Find impacted entities
impacted_entities = [
    n for n in all_impacted if G.nodes.get(n, {}).get("node_type") == "domain_entity"
]

# 6. Compute paths for each impacted service
impacted_services = []
for svc, nodes in impacted_by_service.items():
    paths = []
    svc_node = f"service::{svc}"
    if svc_node in G:
        try:
            # Use cached undirected graph (Addresses NX-3)
            G_undirected = getattr(self, '_cached_undirected', None) or G.to_undirected()
            path = nx.shortest_path(G_undirected, node_id, svc_node)
            paths.append(path)
        except nx.NetworkXNoPath:
            pass
    impacted_services.append({
        "service_name": svc,
        "impact_count": len(nodes),
        "impact_paths": paths
    })
```

---

#### Tool 6: `validate_service_boundaries`

**Purpose:** Use community detection to validate whether declared service boundaries align with actual code dependency clusters.

**Parameters:**

| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| `resolution` | `float` | No | `1.0` | Louvain resolution parameter (<1 = larger communities, >1 = smaller) |

**Return type:** `dict` with schema:
```python
{
    "communities_detected": int,
    "services_declared": int,
    "alignment_score": float,         # 0.0-1.0, higher = better alignment
    "misplaced_files": list[dict],    # [{"file": str, "declared_service": str, "community_service": str, "confidence": float}]
    "isolated_files": list[str],      # Files in no community
    "service_coupling": list[dict],   # [{"service_a": str, "service_b": str, "cross_edges": int}]
}
```

**Algorithm:**
```python
# 1. Extract file-level subgraph
file_nodes = [n for n in G.nodes() if G.nodes[n].get("node_type") == "file"]
file_subgraph = G.subgraph(file_nodes).copy()
# Convert to undirected for community detection
file_undirected = file_subgraph.to_undirected()

# 2. Run Louvain community detection
communities = nx.community.louvain_communities(file_undirected, resolution=resolution, seed=42)

# 3. For each community, find the dominant service_name
community_service_map = {}
for i, community in enumerate(communities):
    service_counts = {}
    for node in community:
        svc = G.nodes[node].get("service_name", "")
        if svc:
            service_counts[svc] = service_counts.get(svc, 0) + 1
    dominant = max(service_counts, key=service_counts.get) if service_counts else ""
    community_service_map[i] = dominant

# 4. Find misplaced files
misplaced = []
for i, community in enumerate(communities):
    dominant = community_service_map[i]
    for node in community:
        declared = G.nodes[node].get("service_name", "")
        if declared and dominant and declared != dominant:
            total_in_community = len(community)
            same_service_count = sum(1 for n in community if G.nodes[n].get("service_name") == dominant)
            confidence = same_service_count / total_in_community
            misplaced.append({
                "file": G.nodes[node].get("file_path", node),
                "declared_service": declared,
                "community_service": dominant,
                "confidence": round(confidence, 3)
            })

# 5. Compute services_declared (Addresses COMP-5)
services_declared = len(set(
    G.nodes[n].get("service_name", "")
    for n in file_nodes
    if G.nodes[n].get("service_name", "")
))

# 6. Compute isolated_files (Addresses COMP-4)
# Files that are singleton connected components in the file subgraph
# (i.e., files with no IMPORTS edges to or from other files)
isolated_files = [
    G.nodes[n].get("file_path", n)
    for n in file_nodes
    if file_undirected.degree(n) == 0
]

# 7. Compute alignment score
total_files = len(file_nodes)
aligned = total_files - len(misplaced)
alignment_score = aligned / total_files if total_files > 0 else 1.0

# 8. Compute service coupling (cross-service edges)
coupling = {}
for u, v, k, d in G.edges(keys=True, data=True):
    u_svc = G.nodes.get(u, {}).get("service_name", "")
    v_svc = G.nodes.get(v, {}).get("service_name", "")
    if u_svc and v_svc and u_svc != v_svc:
        pair = tuple(sorted([u_svc, v_svc]))
        coupling[pair] = coupling.get(pair, 0) + 1

service_coupling = [
    {"service_a": a, "service_b": b, "cross_edges": count}
    for (a, b), count in sorted(coupling.items(), key=lambda x: -x[1])
]
```

---

#### Tool 7: `check_cross_service_events`

**Purpose:** Validate that published events have consumers and consumed events have publishers. Directly addresses ADV-001/ADV-002 false positive reduction (INTEGRATION_GAPS Gap 2).

**Parameters:**

| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| `service_name` | `str` | No | `""` | Filter to specific service (empty = all) |

**Return type:** `dict` with schema:
```python
{
    "orphaned_events": list[dict],      # Published events with no consumer
    "unmatched_consumers": list[dict],   # Consumed events with no publisher
    "matched_events": list[dict],        # Events with both publisher and consumer
    "total_events": int,
    "match_rate": float                  # 0.0-1.0
}
```

**Algorithm:**
```python
# 1. Collect all event nodes
event_nodes = [n for n in G.nodes() if G.nodes[n].get("node_type") == "event"]

if service_name:
    # Event nodes no longer have a service_name attribute (SCH-1 fix: shared event identity).
    # Filter by checking if the given service is connected via PUBLISHES_EVENT or CONSUMES_EVENT edges.
    event_nodes = [n for n in event_nodes
                   if any(G.nodes[u].get("service_name") == service_name
                          for u, _, k, _ in G.in_edges(n, keys=True, data=True)
                          if k in ("PUBLISHES_EVENT", "CONSUMES_EVENT"))]

orphaned = []
unmatched = []
matched = []

for event_node in event_nodes:
    ev = G.nodes[event_node]
    publishers = [u for u, _, k, _ in G.in_edges(event_node, keys=True, data=True) if k == "PUBLISHES_EVENT"]
    consumers = [u for u, _, k, _ in G.in_edges(event_node, keys=True, data=True) if k == "CONSUMES_EVENT"]
    # Note: CONSUMES_EVENT goes from service -> event, so it's an OUT edge from service
    # Re-check: edges are service -> event, so for event node, in_edges are the services
    # Actually per schema: PUBLISHES_EVENT is service -> event, CONSUMES_EVENT is service -> event
    # So we need out_edges FROM services TO this event
    publishers = [u for u, _, k, _ in G.in_edges(event_node, keys=True, data=True) if k == "PUBLISHES_EVENT"]
    consumers = [u for u, _, k, _ in G.in_edges(event_node, keys=True, data=True) if k == "CONSUMES_EVENT"]

    entry = {
        "event_name": ev["event_name"],
        "channel": ev.get("channel", ""),
        "publishers": [G.nodes[p].get("service_name", "") for p in publishers],
        "consumers": [G.nodes[c].get("service_name", "") for c in consumers]
    }
    if publishers and consumers:
        matched.append(entry)
    elif publishers and not consumers:
        orphaned.append(entry)
    elif consumers and not publishers:
        unmatched.append(entry)

total = len(event_nodes)
match_rate = len(matched) / total if total > 0 else 1.0
```

### 6.2 No Existing MCP Tools Are Modified

All 22 existing MCP tools across the three servers remain unchanged. The Graph RAG module reads from the same data stores but does not modify them. This preserves full backward compatibility.

### 6.3 No New HTTP Endpoints

The Graph RAG module exposes its functionality exclusively through MCP tools (stdio transport), consistent with the existing architecture. If HTTP access is needed in the future, a FastAPI router can be added following the same pattern as `codebase_intelligence/main.py`.

---

## 7. Context Window Assembly

### 7.1 Structure of a Graph RAG Context Block

The `context_text` field returned by `get_service_context` is a structured markdown block designed for injection into builder prompts. Format:

```markdown
## Graph RAG Context: {service_name}

### Service Dependencies
- **Depends on:** auth-service, payment-service
- **Depended on by:** notification-service, analytics-service

### APIs This Service Provides
| Method | Path | Handler |
|--------|------|---------|
| GET | /api/orders | get_orders |
| POST | /api/orders | create_order |
| GET | /api/orders/{id} | get_order_by_id |

### APIs This Service Must Consume
| Method | Path | Provider Service |
|--------|------|-----------------|
| POST | /auth/validate-token | auth-service |
| POST | /payments/charge | payment-service |

### Events Published
| Event Name | Channel |
|------------|---------|
| order.created | orders |
| order.updated | orders |

### Events Consumed
| Event Name | Publisher |
|------------|----------|
| payment.completed | payment-service |

### Domain Entities Owned
#### Order
- id: string (primary key)
- user_id: string (references User)
- items: array
- total: number
- status: string (enum: pending, confirmed, shipped, delivered)

### Domain Entities Referenced (from other services)
#### User (owned by auth-service)
- id: string
- email: string
- name: string

### Cross-Service Integration Notes
- When calling auth-service POST /auth/validate-token, include Authorization header with JWT.
- When publishing order.created events, include order_id and user_id in payload.
- notification-service consumes order.created -- ensure payload schema is stable.
```

### 7.2 Context Truncation Strategy

When the assembled context exceeds the token budget:

1. **Priority ordering** (highest priority retained first):
   - Service dependencies (always included, ~50 tokens)
   - APIs this service must consume (critical for correct implementation, ~100 tokens per endpoint)
   - Domain entities referenced from other services (prevents schema drift, ~80 tokens per entity)
   - APIs this service provides (builder knows these from its own contract, ~50 tokens per endpoint)
   - Events published/consumed (~30 tokens per event)
   - Domain entities owned (builder will define these, ~80 tokens per entity)
   - Cross-service integration notes (~30 tokens per note)

2. **Truncation procedure:**
   ```python
   def truncate_context(context_sections: list[tuple[str, str, int]], max_tokens: int) -> str:
       """
       context_sections: [(section_name, section_text, priority), ...]
       priority: lower number = higher priority (retained first)
       """
       # Sort by priority
       sections = sorted(context_sections, key=lambda s: s[2])
       result = []
       tokens_used = 0
       for name, text, _ in sections:
           section_tokens = len(text) // 4  # Rough estimate: 4 chars per token
           if tokens_used + section_tokens <= max_tokens:
               result.append(text)
               tokens_used += section_tokens
           else:
               # Truncate this section to fit remaining budget
               remaining = max_tokens - tokens_used
               truncated_chars = remaining * 4
               result.append(text[:truncated_chars] + "\n[... truncated ...]")
               break
       return "\n\n".join(result)
   ```

### 7.3 Context Ranking When Multiple Relevant Nodes Found

When `hybrid_search` returns multiple results for context assembly:

1. **Combined score** = `semantic_weight * semantic_score + graph_weight * graph_score` (configurable, default 0.6/0.4).
2. **Within the same combined score tier** (scores within 0.05 of each other), prefer nodes with higher PageRank.
3. **Deduplication:** If two nodes are in the same file (e.g., two symbols from the same module), include the file once with both symbols listed.

### 7.4 Token Budget Allocation Strategy

Default token budget: 2000 tokens per service context block.

| Section | Allocation | Max Tokens |
|---------|-----------|------------|
| Service dependencies | 5% | 100 |
| Consumed APIs | 30% | 600 |
| Referenced entities | 20% | 400 |
| Provided APIs | 15% | 300 |
| Events | 10% | 200 |
| Owned entities | 10% | 200 |
| Integration notes | 10% | 200 |

These allocations are soft limits. The truncation procedure (Section 7.2) ensures the total stays within budget.

---

## 8. Integration Points

### 8.1 Build 3: Pipeline Integration (super_orchestrator)

**Where context gets injected:** In `run_parallel_builders()` in `C:\MY_PROJECTS\super-team\src\super_orchestrator\pipeline.py`, after the `contracts_registering` phase completes and before builder subprocesses are spawned.

**New pipeline step:** Between `contracts_registering` and `builders_running`, call `_build_graph_rag_context()` within the existing `contracts_registered` transition handler. (Clarification per INT-6: this is NOT a new state machine state. The Graph RAG build executes inside the existing `contracts_registered` transition callback, before the state machine advances to `builders_running`. The term "sub-phase" refers to a logical step within the transition, not a new FSM state.)

**File:** `C:\MY_PROJECTS\super-team\src\super_orchestrator\pipeline.py`

**What changes:** Add a new method `_build_graph_rag_context()` called from the `contracts_registered` transition handler. This method:

1. Calls `build_knowledge_graph` MCP tool on the Graph RAG server.
2. For each service in the service map, calls `get_service_context` MCP tool.
3. Stores each service's `context_text` in `PipelineState.phase_artifacts["graph_rag_contexts"]` (a dict mapping service_name to context_text string).

**Gating:** The entire `_build_graph_rag_context()` step is wrapped in a `try/except`. If the Graph RAG MCP server is unavailable or any call fails, the method logs a warning and sets `phase_artifacts["graph_rag_contexts"] = {}`. Downstream code checks for empty context and proceeds without it. No pipeline phase fails due to Graph RAG unavailability.

**File:** `C:\MY_PROJECTS\super-team\src\super_orchestrator\state.py`

**What changes:** Add `graph_rag_contexts: dict[str, str]` to `phase_artifacts` dict (already a `dict[str, Any]`, no schema change needed).

### 8.2 Build 2: Builder Context Injection

**Where context gets injected:** In the builder subprocess setup within `run_parallel_builders()`.

**File:** `C:\MY_PROJECTS\super-team\src\super_orchestrator\pipeline.py`

**What changes:** When constructing `builder_config.json` for each builder subprocess (line ~724-727), add a new field `graph_rag_context` containing the service's context text from `phase_artifacts["graph_rag_contexts"].get(service_name, "")`.

**File:** `C:\MY_PROJECTS\agent-team-v15\src\agent_team_v15\claude_md_generator.py`

**What changes:** The `generate_claude_md()` function (line ~216) receives a new optional parameter `graph_rag_context: str = ""`. If non-empty, this string is appended as a new section in the generated CLAUDE.md after the existing `codebase_context` section:

```python
# In generate_claude_md(), after codebase_context section:
if graph_rag_context:
    sections.append(graph_rag_context)
```

**File:** `C:\MY_PROJECTS\agent-team-v15\src\agent_team_v15\agents.py`

**What changes:** The `_append_contract_and_codebase_context()` function (line ~2241-2255) gains a new parameter `graph_rag_context: str = ""` which is appended to the builder prompt if non-empty. The caller at line ~2662 reads `graph_rag_context` from `builder_config.json`.

### 8.3 Build 3: Quality Gate Integration

**File:** `C:\MY_PROJECTS\super-team\src\quality_gate\adversarial_patterns.py`

**What changes:** The `AdversarialScanner` gains an optional `graph_rag_client` parameter. When available:

- **ADV-001 (dead event handlers):** Before flagging a handler as dead, call `check_cross_service_events` to verify whether the event has a cross-service publisher. If yes, suppress the violation.
- **ADV-002 (dead contracts):** Before flagging a contract as dead, check whether any other service has a `SERVICE_CALLS` edge pointing to the contract's service. If yes, suppress the violation.

**Gating:** If `graph_rag_client` is None, the scanner behaves exactly as it does today. The parameter defaults to None.

**Plumbing (Addresses GATE-3):** The `GraphRAGClient` instance is created in `pipeline.py`'s `_build_graph_rag_context()` method (which already establishes an MCP session to the Graph RAG server). This client is stored in `PipelineState.phase_artifacts["graph_rag_client"]`. When `gate_engine.py` instantiates `AdversarialScanner`, it reads from `phase_artifacts`:
```python
# In gate_engine.py, when creating AdversarialScanner:
graph_rag_client = self.state.phase_artifacts.get("graph_rag_client", None)
scanner = AdversarialScanner(..., graph_rag_client=graph_rag_client)
```
The `graph_rag_client` object is a `GraphRAGClient` wrapper (Section 9.1) that calls MCP tools via the existing session. If the Graph RAG server was never started (disabled or failed), this key is absent from `phase_artifacts` and the scanner receives `None`.

### 8.4 Build 3: Fix Loop Integration

**File:** `C:\MY_PROJECTS\super-team\src\run4\fix_pass.py`

**What changes:** The `classify_priority()` function gains an optional `graph_rag_client` parameter. When available:

- After keyword-based classification, call `find_cross_service_impact` for the violated file.
- If `total_impacted_nodes > 10`, boost priority by one level (P2 -> P1, P1 -> P0).
- Include impact summary in the violation's `action` field.

**File:** `C:\MY_PROJECTS\super-team\src\run4\builder.py`

**What changes:** The `write_fix_instructions()` function gains an optional `graph_rag_context: str = ""` parameter. If non-empty, each fix instruction block includes a "Dependencies Warning" section listing files that depend on the file being fixed (from `query_graph_neighborhood` results).

**Gating:** Both functions check `if graph_rag_client is not None` before making any Graph RAG calls.

### 8.5 New Config Fields

**File:** `C:\MY_PROJECTS\super-team\src\super_orchestrator\config.py`

Add to `SuperOrchestratorConfig`:

```python
@dataclass
class GraphRAGConfig:
    enabled: bool = True
    mcp_command: str = "python"
    mcp_args: list[str] = field(default_factory=lambda: ["-m", "src.graph_rag.mcp_server"])
    database_path: str = "./data/graph_rag.db"
    chroma_path: str = "./data/graph_rag_chroma"
    # External database paths (Addresses INT-1 / COMP-1)
    ci_database_path: str = "./data/codebase_intel.db"
    architect_database_path: str = "./data/architect.db"
    contract_database_path: str = "./data/contracts.db"
    context_token_budget: int = 2000
    semantic_weight: float = 0.6
    graph_weight: float = 0.4
    startup_timeout_ms: int = 30000
```

Add field to `SuperOrchestratorConfig`:
```python
graph_rag: GraphRAGConfig = field(default_factory=GraphRAGConfig)
```

### 8.6 Gating: How Existing Behavior Is Preserved

The gating strategy ensures Graph RAG is fully disableable:

1. **Config gate:** `SuperOrchestratorConfig.graph_rag.enabled` (default: `True`). When `False`, the `_build_graph_rag_context()` step is skipped entirely.
2. **Runtime gate:** All Graph RAG MCP calls are wrapped in try/except. Failure results in empty context, not pipeline failure.
3. **Parameter gate:** All modified functions accept Graph RAG parameters as optional with defaults that produce original behavior (`graph_rag_context=""`, `graph_rag_client=None`).
4. **No existing function signatures are broken:** All new parameters are keyword-only with defaults.

---

## 9. File and Module Structure

### 9.1 New Files

#### `C:\MY_PROJECTS\super-team\src\graph_rag\__init__.py`
- **Purpose:** Package marker
- **Public interface:** Empty (imports are from submodules)

#### `C:\MY_PROJECTS\super-team\src\graph_rag\mcp_server.py`
- **Purpose:** MCP server exposing 7 Graph RAG tools
- **Public interface:**
  - `mcp: FastMCP` instance
  - 7 `@mcp.tool()` decorated functions (one per tool from Section 6.1)
- **Module-level initialization (Addresses INT-1 / COMP-1):**
  ```python
  # Graph RAG's own stores
  _db_path = os.environ.get("GRAPH_RAG_DB_PATH", "./data/graph_rag.db")
  _chroma_path = os.environ.get("GRAPH_RAG_CHROMA_PATH", "./data/graph_rag_chroma")
  _pool = ConnectionPool(_db_path)
  init_graph_rag_db(_pool)

  # External database paths (read-only access to other modules' data)
  _ci_db_path = os.environ.get("CI_DATABASE_PATH", "./data/codebase_intel.db")
  _architect_db_path = os.environ.get("ARCHITECT_DATABASE_PATH", "./data/architect.db")
  _contract_db_path = os.environ.get("CONTRACT_DATABASE_PATH", "./data/contracts.db")
  _ci_pool = ConnectionPool(_ci_db_path)
  _architect_pool = ConnectionPool(_architect_db_path)
  _contract_pool = ConnectionPool(_contract_db_path)

  _graph_rag_store = GraphRAGStore(_chroma_path)
  _knowledge_graph = KnowledgeGraph()
  _graph_rag_engine = GraphRAGEngine(_knowledge_graph, _graph_rag_store)
  _graph_rag_indexer = GraphRAGIndexer(
      knowledge_graph=_knowledge_graph,
      store=_graph_rag_store,
      pool=_pool,
      ci_pool=_ci_pool,
      architect_pool=_architect_pool,
      contract_pool=_contract_pool,
  )
  ```

#### `C:\MY_PROJECTS\super-team\src\graph_rag\knowledge_graph.py`
- **Purpose:** Manages the NetworkX MultiDiGraph knowledge graph
- **Public interface:**
  ```python
  class KnowledgeGraph:
      def __init__(self) -> None: ...
      @property
      def graph(self) -> nx.MultiDiGraph: ...
      def add_node(self, node_id: str, **attrs: Any) -> None: ...
      def add_edge(self, source: str, target: str, key: str, **attrs: Any) -> None: ...
      def clear(self) -> None: ...
      def get_node(self, node_id: str) -> dict[str, Any] | None: ...
      def get_neighbors(self, node_id: str, direction: str = "both", edge_type: str = "") -> list[str]: ...
      def get_ego_subgraph(self, node_id: str, radius: int = 2, undirected: bool = True) -> nx.MultiDiGraph: ...
      def compute_pagerank(self) -> dict[str, float]: ...
      def compute_communities(self, resolution: float = 1.0) -> list[set[str]]: ...
      def get_shortest_path(self, source: str, target: str) -> list[str] | None: ...
      def get_descendants(self, node_id: str, max_depth: int = 3) -> set[str]: ...
      def get_ancestors(self, node_id: str, max_depth: int = 3) -> set[str]: ...
      def node_count(self) -> int: ...
      def edge_count(self) -> int: ...
      def to_json(self) -> str: ...
      def from_json(self, json_str: str) -> None: ...
  ```

#### `C:\MY_PROJECTS\super-team\src\graph_rag\graph_rag_store.py`
- **Purpose:** ChromaDB wrapper for the two Graph RAG collections
- **Public interface:**
  ```python
  class GraphRAGStore:
      def __init__(self, chroma_path: str) -> None: ...
      def clear_all(self) -> None: ...
      def upsert_nodes(self, records: list[GraphRAGNodeRecord]) -> int: ...
      def upsert_contexts(self, records: list[GraphRAGContextRecord]) -> int: ...
      def query_nodes(self, query: str, n_results: int = 10,
                      where: dict | None = None) -> list[GraphRAGSearchResult]: ...
      def query_contexts(self, query: str, n_results: int = 5,
                         where: dict | None = None) -> list[GraphRAGSearchResult]: ...
      def delete_all_nodes(self) -> None: ...
      def delete_all_contexts(self) -> None: ...
      def node_count(self) -> int: ...
      def context_count(self) -> int: ...
  ```
  **Implementation note for `delete_all_nodes()` / `delete_all_contexts()` (Addresses CR-2):**
  ChromaDB has no `collection.delete_all()` or `collection.clear()` API. To clear all records,
  use `client.delete_collection(name)` followed by `client.get_or_create_collection(name, ...)`
  with the same embedding function and metadata configuration:
  ```python
  def delete_all_nodes(self) -> None:
      self._client.delete_collection("graph-rag-nodes")
      self._nodes_collection = self._client.get_or_create_collection(
          name="graph-rag-nodes",
          embedding_function=DefaultEmbeddingFunction(),
          metadata={"hnsw:space": "cosine"}
      )

  def delete_all_contexts(self) -> None:
      self._client.delete_collection("graph-rag-context")
      self._contexts_collection = self._client.get_or_create_collection(
          name="graph-rag-context",
          embedding_function=DefaultEmbeddingFunction(),
          metadata={"hnsw:space": "cosine"}
      )
  ```

#### `C:\MY_PROJECTS\super-team\src\graph_rag\graph_rag_indexer.py`
- **Purpose:** Orchestrates the full knowledge graph build pipeline (Phase 1-5 from Section 5.2)
- **Public interface (Addresses INT-1 / COMP-1):**
  ```python
  class GraphRAGIndexer:
      def __init__(self, knowledge_graph: KnowledgeGraph,
                   store: GraphRAGStore, pool: ConnectionPool,
                   ci_pool: ConnectionPool | None = None,
                   architect_pool: ConnectionPool | None = None,
                   contract_pool: ConnectionPool | None = None) -> None:
          """
          Args:
              knowledge_graph: KnowledgeGraph instance for the graph
              store: GraphRAGStore instance for ChromaDB collections
              pool: ConnectionPool for the Graph RAG's own database (graph_rag.db)
              ci_pool: ConnectionPool for the CI database (codebase_intel.db).
                       Used to read: symbols, dependency_edges, graph_snapshots tables.
              architect_pool: ConnectionPool for the Architect database (architect.db).
                              Used to read: service_maps, domain_models tables.
              contract_pool: ConnectionPool for the Contract Engine database (contracts.db).
                             Used to read: contracts table.
          """
          ...
      def build(self, project_name: str = "",
                service_interfaces_json: str = "") -> GraphRAGBuildResult: ...
      def _load_existing_data(self, project_name: str,
                               service_interfaces_json: str = "") -> GraphRAGSourceData: ...
      def _build_graph(self, source_data: GraphRAGSourceData) -> None: ...
      def _compute_metrics(self) -> None: ...
      def _populate_chromadb(self) -> None: ...
      def _persist_snapshot(self) -> None: ...
      def _match_handlers_to_endpoints(self, service_interfaces: dict[str, Any]) -> None: ...
      def _match_symbols_to_entities(self) -> None: ...
      def _derive_service_edges(self) -> None: ...
      def _parse_contract_endpoints(self, contract_node_id: str,
                                     contract_type: str, spec_json: str,
                                     service_name: str) -> list[tuple[str, dict]]: ...
  ```

#### `C:\MY_PROJECTS\super-team\src\graph_rag\graph_rag_engine.py`
- **Purpose:** Implements the query algorithms for all 7 MCP tools
- **Public interface:**
  ```python
  class GraphRAGEngine:
      _cached_undirected: nx.Graph | None  # Cached undirected graph (Addresses NX-3).
                                            # Set by update_undirected_cache() after graph build.
                                            # Used by hybrid_search() and find_cross_service_impact().
      def __init__(self, knowledge_graph: KnowledgeGraph, store: GraphRAGStore) -> None: ...
      def update_undirected_cache(self) -> None:
          """Cache G.to_undirected() for use in distance-based queries."""
          ...
      def get_service_context(self, service_name: str, **options: Any) -> dict[str, Any]: ...
      def query_neighborhood(self, node_id: str, radius: int = 2,
                             undirected: bool = True, filter_node_types: list[str] | None = None,
                             filter_edge_types: list[str] | None = None,
                             max_nodes: int = 50) -> dict[str, Any]: ...
      def hybrid_search(self, query: str, n_results: int = 10,
                        node_types: list[str] | None = None,
                        service_name: str = "", anchor_node_id: str = "",
                        semantic_weight: float = 0.6,
                        graph_weight: float = 0.4) -> dict[str, Any]: ...
      def find_cross_service_impact(self, node_id: str, max_depth: int = 3) -> dict[str, Any]: ...
      def validate_service_boundaries(self, resolution: float = 1.0) -> dict[str, Any]: ...
      def check_cross_service_events(self, service_name: str = "") -> dict[str, Any]: ...
      def assemble_service_context_text(self, service_context: dict[str, Any],
                                         max_tokens: int = 2000) -> str: ...
  ```

#### `C:\MY_PROJECTS\super-team\src\graph_rag\context_assembler.py`
- **Purpose:** Assembles and truncates context blocks for builder injection
- **Public interface:**
  ```python
  class ContextAssembler:
      def __init__(self, max_tokens: int = 2000) -> None: ...
      def assemble_service_context(self, service_name: str,
                                    provided_endpoints: list[dict],
                                    consumed_endpoints: list[dict],
                                    events_published: list[dict],
                                    events_consumed: list[dict],
                                    owned_entities: list[dict],
                                    referenced_entities: list[dict],
                                    depends_on: list[str],
                                    depended_on_by: list[str]) -> str: ...
      def assemble_community_summary(self, community_id: int,
                                      members: list[dict],
                                      edges: list[dict]) -> str: ...
      def truncate_to_budget(self, sections: list[tuple[str, str, int]],
                              max_tokens: int) -> str: ...
  ```

#### `C:\MY_PROJECTS\super-team\src\shared\models\graph_rag.py`
- **Purpose:** All Graph RAG dataclasses and TypedDicts
- **Public interface:** See Section 10 for full definitions

#### `C:\MY_PROJECTS\super-team\src\graph_rag\mcp_client.py`
- **Purpose:** Client wrapper for calling Graph RAG MCP tools from Build 3 pipeline
- **Public interface:**
  ```python
  class GraphRAGClient:
      def __init__(self, session: Any) -> None: ...
      async def build_knowledge_graph(self, project_name: str = "",
                                       force_rebuild: bool = True) -> dict[str, Any]: ...
      async def get_service_context(self, service_name: str, **options: Any) -> dict[str, Any]: ...
      async def hybrid_search(self, query: str, **options: Any) -> dict[str, Any]: ...
      async def find_cross_service_impact(self, node_id: str,
                                           max_depth: int = 3) -> dict[str, Any]: ...
      async def check_cross_service_events(self, service_name: str = "") -> dict[str, Any]: ...
  ```

### 9.2 Existing Files Modified

#### `C:\MY_PROJECTS\super-team\src\super_orchestrator\config.py`
- **What changes:** Add `GraphRAGConfig` dataclass. Add `graph_rag: GraphRAGConfig` field to `SuperOrchestratorConfig`.
- **Why:** Pipeline needs config for the new MCP server.

#### `C:\MY_PROJECTS\super-team\src\super_orchestrator\pipeline.py`
- **What changes:** Add `_build_graph_rag_context()` method. Call it after `contracts_registering` phase. Pass `graph_rag_context` to builder config JSON.
- **Why:** This is the injection point for Graph RAG context into builder subprocesses.

#### `C:\MY_PROJECTS\super-team\src\shared\db\schema.py`
- **What changes:** Add `init_graph_rag_db(pool)` function that creates the `graph_rag_snapshots` table.
- **Why:** Knowledge graph snapshot persistence.

#### `C:\MY_PROJECTS\agent-team-v15\src\agent_team_v15\claude_md_generator.py`
- **What changes:** Add optional `graph_rag_context: str = ""` parameter to `generate_claude_md()`. Append as a section if non-empty.
- **Why:** Injects Graph RAG context into builder's CLAUDE.md.

#### `C:\MY_PROJECTS\agent-team-v15\src\agent_team_v15\agents.py`
- **What changes:** Add optional `graph_rag_context: str = ""` parameter to `_append_contract_and_codebase_context()`. Read from `builder_config.json`.
- **Why:** Passes Graph RAG context through the builder prompt chain.

#### `C:\MY_PROJECTS\super-team\src\quality_gate\adversarial_patterns.py`
- **What changes:** Add optional `graph_rag_client` parameter to `AdversarialScanner.__init__()`. Add cross-service event check in ADV-001 and ADV-002 handlers.
- **Why:** Reduces false positives using cross-service knowledge.

#### `C:\MY_PROJECTS\super-team\src\run4\fix_pass.py`
- **What changes:** Add optional `graph_rag_client` parameter to `classify_priority()`. Add impact-based priority boosting.
- **Why:** Enables centrality-weighted violation prioritization.

#### `C:\MY_PROJECTS\super-team\src\run4\builder.py`
- **What changes:** Add optional `graph_rag_context: str = ""` parameter to `write_fix_instructions()`. Include dependency warnings in fix instructions.
- **Why:** Enriches fix instructions with architectural context.

---

## 10. Data Models

### 10.1 New Dataclasses

All defined in `C:\MY_PROJECTS\super-team\src\shared\models\graph_rag.py`:

```python
"""Data models for the Graph RAG module."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import Enum


class NodeType(str, Enum):
    """Types of nodes in the knowledge graph."""
    FILE = "file"
    SYMBOL = "symbol"
    SERVICE = "service"
    CONTRACT = "contract"
    ENDPOINT = "endpoint"
    DOMAIN_ENTITY = "domain_entity"
    EVENT = "event"


class EdgeType(str, Enum):
    """Types of edges in the knowledge graph."""
    CONTAINS_FILE = "CONTAINS_FILE"
    DEFINES_SYMBOL = "DEFINES_SYMBOL"
    IMPORTS = "IMPORTS"
    CALLS = "CALLS"
    INHERITS = "INHERITS"
    IMPLEMENTS = "IMPLEMENTS"
    PROVIDES_CONTRACT = "PROVIDES_CONTRACT"
    EXPOSES_ENDPOINT = "EXPOSES_ENDPOINT"
    HANDLES_ENDPOINT = "HANDLES_ENDPOINT"
    OWNS_ENTITY = "OWNS_ENTITY"
    REFERENCES_ENTITY = "REFERENCES_ENTITY"
    IMPLEMENTS_ENTITY = "IMPLEMENTS_ENTITY"
    PUBLISHES_EVENT = "PUBLISHES_EVENT"
    CONSUMES_EVENT = "CONSUMES_EVENT"
    SERVICE_CALLS = "SERVICE_CALLS"
    DOMAIN_RELATIONSHIP = "DOMAIN_RELATIONSHIP"


@dataclass
class GraphRAGBuildResult:
    """Result of building/rebuilding the knowledge graph."""
    success: bool
    node_count: int = 0
    edge_count: int = 0
    node_types: dict[str, int] = field(default_factory=dict)
    edge_types: dict[str, int] = field(default_factory=dict)
    community_count: int = 0
    build_time_ms: int = 0
    services_indexed: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


@dataclass
class GraphRAGNodeRecord:
    """A record to upsert into the graph-rag-nodes ChromaDB collection."""
    id: str                     # Same as knowledge graph node ID
    document: str               # Embedded text description
    node_type: str              # NodeType value
    service_name: str = ""
    language: str = ""
    community_id: int = -1
    pagerank: float = 0.0


@dataclass
class GraphRAGContextRecord:
    """A record to upsert into the graph-rag-context ChromaDB collection."""
    id: str                     # e.g., "ctx::service::auth-service"
    document: str               # Context summary text
    context_type: str           # "service_context" or "community_summary"
    service_name: str = ""
    community_id: int = -1
    node_count: int = 0
    edge_count: int = 0


@dataclass
class GraphRAGSearchResult:
    """A single result from a Graph RAG query."""
    node_id: str
    node_type: str
    score: float
    semantic_score: float = 0.0
    graph_score: float = 0.0
    distance: int = -1
    document: str = ""
    metadata: dict[str, str | int | float] = field(default_factory=dict)


@dataclass
class ServiceContext:
    """Complete context for a service, ready for builder injection."""
    service_name: str
    provided_endpoints: list[dict[str, str]] = field(default_factory=list)
    consumed_endpoints: list[dict[str, str]] = field(default_factory=list)
    events_published: list[dict[str, str]] = field(default_factory=list)
    events_consumed: list[dict[str, str]] = field(default_factory=list)
    owned_entities: list[dict[str, str | list]] = field(default_factory=list)
    referenced_entities: list[dict[str, str | list]] = field(default_factory=list)
    depends_on: list[str] = field(default_factory=list)
    depended_on_by: list[str] = field(default_factory=list)
    context_text: str = ""


@dataclass
class CrossServiceImpact:
    """Result of cross-service impact analysis."""
    source_node: str
    source_service: str
    impacted_services: list[dict[str, str | int | list]] = field(default_factory=list)
    impacted_contracts: list[dict[str, str | list]] = field(default_factory=list)
    impacted_entities: list[dict[str, str]] = field(default_factory=list)
    total_impacted_nodes: int = 0


@dataclass
class EventValidationResult:
    """Result of cross-service event validation."""
    orphaned_events: list[dict[str, str | list]] = field(default_factory=list)
    unmatched_consumers: list[dict[str, str | list]] = field(default_factory=list)
    matched_events: list[dict[str, str | list]] = field(default_factory=list)
    total_events: int = 0
    match_rate: float = 0.0


@dataclass
class ServiceBoundaryValidation:
    """Result of service boundary validation via community detection."""
    communities_detected: int = 0
    services_declared: int = 0
    alignment_score: float = 0.0
    misplaced_files: list[dict[str, str | float]] = field(default_factory=list)
    isolated_files: list[str] = field(default_factory=list)
    service_coupling: list[dict[str, str | int]] = field(default_factory=list)


@dataclass
class GraphRAGSourceData:
    """All source data loaded for knowledge graph construction."""
    existing_graph: object | None = None      # nx.DiGraph from CI
    symbols: list[dict] = field(default_factory=list)
    service_map: dict | None = None
    domain_model: dict | None = None
    contracts: list[dict] = field(default_factory=list)
    service_interfaces: dict[str, dict] = field(default_factory=dict)
    dependency_edges: list[dict] = field(default_factory=list)
```

### 10.2 New SQLite Table

Added via `init_graph_rag_db(pool)` in `schema.py`:

```sql
CREATE TABLE IF NOT EXISTS graph_rag_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    snapshot_data TEXT NOT NULL,         -- JSON: nx.node_link_data(G, edges="edges")
    node_count INTEGER NOT NULL,
    edge_count INTEGER NOT NULL,
    community_count INTEGER NOT NULL,
    services_indexed TEXT NOT NULL,      -- JSON: list of service names
    created_at TEXT NOT NULL
);
```

---

## 11. Test Strategy

### 11.1 Unit Tests: Knowledge Graph (`test_knowledge_graph.py`)

| Test | What It Verifies |
|------|-----------------|
| `test_add_node_creates_node_with_attributes` | `KnowledgeGraph.add_node()` creates node with correct attributes in MultiDiGraph |
| `test_add_edge_creates_edge_with_key` | `KnowledgeGraph.add_edge()` creates edge with correct key and attributes |
| `test_multiple_edges_between_same_nodes` | MultiDiGraph supports parallel edges with different keys |
| `test_get_node_returns_attributes` | `get_node()` returns full attribute dict |
| `test_get_node_returns_none_for_missing` | `get_node()` returns None for nonexistent node |
| `test_get_ego_subgraph_respects_radius` | `get_ego_subgraph()` with radius=1 includes only direct neighbors |
| `test_get_ego_subgraph_undirected` | `get_ego_subgraph(undirected=True)` includes both predecessors and successors |
| `test_compute_pagerank_returns_scores` | `compute_pagerank()` returns dict with float scores summing to ~1.0 |
| `test_compute_communities_returns_sets` | `compute_communities()` returns list of non-empty sets |
| `test_get_shortest_path_finds_path` | `get_shortest_path()` returns valid path list |
| `test_get_shortest_path_no_path_returns_none` | Returns None when no path exists |
| `test_get_descendants_respects_max_depth` | Depth-limited BFS returns only nodes within depth |
| `test_get_ancestors_returns_predecessors` | Reverse BFS returns upstream nodes |
| `test_to_json_and_from_json_roundtrip` | Serialization preserves all nodes, edges, and attributes |
| `test_clear_removes_all_nodes_and_edges` | `clear()` leaves empty graph |

### 11.2 Unit Tests: Graph RAG Store (`test_graph_rag_store.py`)

| Test | What It Verifies |
|------|-----------------|
| `test_upsert_nodes_creates_records` | Records appear in `graph-rag-nodes` collection |
| `test_upsert_nodes_idempotent` | Upserting same IDs twice does not create duplicates |
| `test_query_nodes_returns_results` | Semantic query returns relevant results |
| `test_query_nodes_with_where_filter` | Metadata filter restricts results |
| `test_query_nodes_with_node_type_filter` | Filtering by `node_type` works correctly |
| `test_query_nodes_with_service_filter` | Filtering by `service_name` works correctly |
| `test_upsert_contexts_creates_records` | Records appear in `graph-rag-context` collection |
| `test_query_contexts_returns_summaries` | Context query returns service/community summaries |
| `test_delete_all_nodes_clears_collection` | `delete_all_nodes()` results in count == 0 |
| `test_delete_all_contexts_clears_collection` | `delete_all_contexts()` results in count == 0 |
| `test_batch_upsert_300_records` | 300 records upserted in single batch |
| `test_none_metadata_values_converted` | None values converted to empty string (per existing ChromaStore pattern) |

### 11.3 Unit Tests: Graph RAG Engine (`test_graph_rag_engine.py`)

| Test | What It Verifies |
|------|-----------------|
| `test_get_service_context_returns_all_sections` | All fields populated for a service with endpoints, events, entities |
| `test_get_service_context_unknown_service_returns_error` | Returns error dict for nonexistent service |
| `test_hybrid_search_combines_scores` | Combined score = semantic_weight * semantic + graph_weight * graph |
| `test_hybrid_search_with_anchor_reranks_by_distance` | Results closer to anchor node score higher |
| `test_hybrid_search_without_anchor_uses_pagerank` | Graph score derived from PageRank when no anchor |
| `test_find_cross_service_impact_finds_impacted_services` | Cross-service dependencies discovered |
| `test_find_cross_service_impact_respects_max_depth` | Depth limit prevents unbounded traversal |
| `test_validate_service_boundaries_detects_misplaced_files` | Files in wrong service community are reported |
| `test_validate_service_boundaries_perfect_alignment` | All files in correct communities yields score 1.0 |
| `test_check_cross_service_events_finds_orphaned` | Published events with no consumer detected |
| `test_check_cross_service_events_finds_unmatched` | Consumed events with no publisher detected |
| `test_check_cross_service_events_finds_matched` | Events with both publisher and consumer matched |

### 11.4 Unit Tests: Graph RAG Indexer (`test_graph_rag_indexer.py`)

| Test | What It Verifies |
|------|-----------------|
| `test_build_creates_service_nodes` | Service nodes created from ServiceMap |
| `test_build_creates_file_nodes_from_digraph` | File nodes created from existing DiGraph |
| `test_build_creates_symbol_nodes_from_db` | Symbol nodes created from symbols table |
| `test_build_creates_contract_nodes` | Contract nodes created from contracts table |
| `test_build_creates_endpoint_nodes_from_openapi` | Endpoint nodes parsed from OpenAPI specs |
| `test_build_creates_domain_entity_nodes` | Domain entity nodes from DomainModel |
| `test_build_creates_event_nodes` | Event nodes from ServiceInterface |
| `test_build_creates_service_calls_edges` | Cross-service import edges aggregated into SERVICE_CALLS |
| `test_build_matches_handlers_to_endpoints` | HANDLES_ENDPOINT edges created for matching handlers |
| `test_build_matches_symbols_to_entities` | IMPLEMENTS_ENTITY edges created by name matching |
| `test_build_populates_chromadb` | Both ChromaDB collections populated after build |
| `test_build_persists_snapshot` | Snapshot stored in graph_rag_snapshots table |
| `test_build_computes_pagerank` | PageRank scores stored as node attributes |
| `test_build_computes_communities` | Community IDs stored as node attributes |
| `test_full_build_pipeline_integration` | End-to-end: load data -> build graph -> populate chroma -> persist |

### 11.5 Unit Tests: Context Assembler (`test_context_assembler.py`)

| Test | What It Verifies |
|------|-----------------|
| `test_assemble_service_context_includes_all_sections` | All sections present in output text |
| `test_assemble_service_context_empty_sections_omitted` | Empty sections not included |
| `test_truncate_to_budget_respects_limit` | Output does not exceed token budget |
| `test_truncate_to_budget_preserves_priority_order` | Higher priority sections retained when truncating |
| `test_community_summary_includes_members_and_edges` | Community summary lists member services and relationships |

### 11.6 Unit Tests: MCP Server (`test_mcp_server.py`)

| Test | What It Verifies |
|------|-----------------|
| `test_build_knowledge_graph_tool_returns_stats` | MCP tool returns success and node/edge counts |
| `test_get_service_context_tool_returns_context` | MCP tool returns service context dict |
| `test_hybrid_search_tool_returns_results` | MCP tool returns ranked results |
| `test_query_graph_neighborhood_tool_returns_subgraph` | MCP tool returns nodes and edges |
| `test_find_cross_service_impact_tool_returns_impact` | MCP tool returns impacted services |
| `test_validate_service_boundaries_tool_returns_validation` | MCP tool returns alignment score |
| `test_check_cross_service_events_tool_returns_events` | MCP tool returns orphaned/unmatched/matched events |

### 11.7 Integration Tests (`test_graph_rag_integration.py`)

| Test | What It Verifies |
|------|-----------------|
| `test_build_then_query_service_context` | Full pipeline: build graph, then query context for a service |
| `test_build_then_hybrid_search` | Full pipeline: build graph, then semantic+graph search |
| `test_build_then_cross_service_impact` | Full pipeline: build graph, then impact analysis |
| `test_gating_disabled_graph_rag_produces_empty_context` | When enabled=False, all operations return empty/default results |
| `test_mcp_server_startup_and_tool_list` | MCP server starts and lists all 7 tools |
| `test_mcp_client_with_retry` | Client retries on transient errors |

### 11.8 Graph-Specific Tests (`test_graph_properties.py`)

| Test | What It Verifies |
|------|-----------------|
| `test_knowledge_graph_is_multidigraph` | `isinstance(G, nx.MultiDiGraph)` |
| `test_all_nodes_have_node_type` | Every node in G has `node_type` attribute |
| `test_all_edges_have_relation_key` | Every edge key is a valid `EdgeType` value |
| `test_service_nodes_connected_to_files` | Every service node has at least one CONTAINS_FILE edge |
| `test_no_orphan_symbols` | Every symbol node has exactly one incoming DEFINES_SYMBOL edge |
| `test_endpoint_nodes_linked_to_contracts` | Every endpoint has an incoming EXPOSES_ENDPOINT edge |
| `test_pagerank_sums_to_approximately_one` | Sum of PageRank values is ~1.0 |
| `test_community_ids_cover_all_nodes` | Every node has a non-negative community_id after build |
| `test_node_id_prefix_matches_node_type` | `"file::"` prefix on file nodes, `"service::"` on service nodes, etc. |

---

## 12. Implementation Sequence

### Phase 1: Foundation (Days 1-2)

**Goal:** Core data models, knowledge graph class, and snapshot persistence.

**Tasks:**
1. Create `src/graph_rag/__init__.py`
2. Create `src/shared/models/graph_rag.py` with all dataclasses from Section 10
3. Add `init_graph_rag_db()` to `src/shared/db/schema.py`
4. Create `src/graph_rag/knowledge_graph.py` with full `KnowledgeGraph` class
5. Write `test_knowledge_graph.py` -- all 15 tests from Section 11.1
6. Verify: All knowledge graph unit tests pass

**Dependencies:** None. This phase has no dependencies on other phases.

### Phase 2: ChromaDB Store (Day 2)

**Goal:** ChromaDB wrapper for the two new collections.

**Tasks:**
1. Create `src/graph_rag/graph_rag_store.py` with `GraphRAGStore` class
2. Write `test_graph_rag_store.py` -- all 12 tests from Section 11.2
3. Verify: All store unit tests pass

**Dependencies:** Phase 1 (needs `GraphRAGNodeRecord`, `GraphRAGContextRecord` dataclasses).

### Phase 3: Indexer Pipeline (Days 3-4)

**Goal:** Full knowledge graph build pipeline.

**Tasks:**
1. Create `src/graph_rag/graph_rag_indexer.py` with `GraphRAGIndexer` class
2. Implement Phase 1 (load data) -- read from CI SQLite, Architect SQLite, Contract Engine SQLite
3. Implement Phase 2 (build graph) -- all node and edge creation logic
4. Implement Phase 3 (compute metrics) -- PageRank and Louvain
5. Implement Phase 4 (populate ChromaDB) -- batch upserts
6. Implement Phase 5 (persist snapshot) -- JSON serialization to SQLite
7. Write `test_graph_rag_indexer.py` -- all 15 tests from Section 11.4
8. Verify: Full build pipeline works end-to-end with mock data

**Dependencies:** Phase 1 (KnowledgeGraph), Phase 2 (GraphRAGStore).

### Phase 4: Query Engine (Days 4-5)

**Goal:** All query algorithms implemented.

**Tasks:**
1. Create `src/graph_rag/context_assembler.py` with `ContextAssembler` class
2. Create `src/graph_rag/graph_rag_engine.py` with `GraphRAGEngine` class
3. Implement `get_service_context` algorithm
4. Implement `query_neighborhood` algorithm
5. Implement `hybrid_search` algorithm
6. Implement `find_cross_service_impact` algorithm
7. Implement `validate_service_boundaries` algorithm
8. Implement `check_cross_service_events` algorithm
9. Write `test_graph_rag_engine.py` -- all 12 tests from Section 11.3
10. Write `test_context_assembler.py` -- all 5 tests from Section 11.5
11. Verify: All engine and assembler tests pass

**Dependencies:** Phase 1 (KnowledgeGraph), Phase 2 (GraphRAGStore).

### Phase 5: MCP Server (Day 5)

**Goal:** MCP server exposing all 7 tools.

**Tasks:**
1. Create `src/graph_rag/mcp_server.py` with all 7 tool handlers
2. Create `src/graph_rag/mcp_client.py` with `GraphRAGClient` wrapper
3. Write `test_mcp_server.py` -- all 7 tests from Section 11.6
4. Verify: MCP server starts, lists tools, and responds to calls

**Dependencies:** Phase 3 (Indexer), Phase 4 (Engine).

### Phase 6: Integration (Days 6-7)

**Goal:** Connect Graph RAG to pipeline, builders, quality gate, and fix loop.

**Tasks:**
1. Add `GraphRAGConfig` to `src/super_orchestrator/config.py`
2. Add `_build_graph_rag_context()` to `src/super_orchestrator/pipeline.py`
3. Modify `claude_md_generator.py` to accept `graph_rag_context` parameter
4. Modify `agents.py` to pass `graph_rag_context` through prompt chain
5. Modify `adversarial_patterns.py` to use `graph_rag_client` for ADV-001/ADV-002
6. Modify `fix_pass.py` to use `graph_rag_client` for priority boosting
7. Modify `builder.py` to include dependency context in fix instructions
8. Write `test_graph_rag_integration.py` -- all 6 tests from Section 11.7
9. Write `test_graph_properties.py` -- all 9 tests from Section 11.8
10. Verify: Full integration tests pass. Gating tests verify disabled mode works.

**Dependencies:** Phase 5 (MCP Server). All existing module modifications are gated.

---

## 13. Configuration

### 13.1 New Config Fields

All fields belong to `GraphRAGConfig` dataclass, nested under `SuperOrchestratorConfig.graph_rag`.

| Field | Type | Default | What It Controls |
|-------|------|---------|-----------------|
| `enabled` | `bool` | `True` | Master switch. When False, all Graph RAG operations are skipped. |
| `mcp_command` | `str` | `"python"` | Command to launch the Graph RAG MCP server subprocess. |
| `mcp_args` | `list[str]` | `["-m", "src.graph_rag.mcp_server"]` | Arguments for the MCP server subprocess. |
| `database_path` | `str` | `"./data/graph_rag.db"` | SQLite database path for graph_rag_snapshots table. |
| `chroma_path` | `str` | `"./data/graph_rag_chroma"` | Directory for Graph RAG ChromaDB collections. |
| `ci_database_path` | `str` | `"./data/codebase_intel.db"` | CI SQLite database path (read-only). Passed as `CI_DATABASE_PATH` env var. (Addresses INT-1) |
| `architect_database_path` | `str` | `"./data/architect.db"` | Architect SQLite database path (read-only). Passed as `ARCHITECT_DATABASE_PATH` env var. (Addresses INT-1) |
| `contract_database_path` | `str` | `"./data/contracts.db"` | Contract Engine SQLite database path (read-only). Passed as `CONTRACT_DATABASE_PATH` env var. (Addresses INT-1) |
| `context_token_budget` | `int` | `2000` | Maximum tokens per service context block. |
| `semantic_weight` | `float` | `0.6` | Weight for semantic similarity in hybrid search (0.0-1.0). |
| `graph_weight` | `float` | `0.4` | Weight for graph proximity in hybrid search (0.0-1.0). |
| `startup_timeout_ms` | `int` | `30000` | Timeout for MCP server initialization in milliseconds. |

### 13.2 Environment Variables (Addresses INT-1 / COMP-1)

| Variable | Purpose | Default | Used By |
|----------|---------|---------|---------|
| `GRAPH_RAG_DB_PATH` | Graph RAG's own SQLite database | `./data/graph_rag.db` | `graph_rag/mcp_server.py` module init |
| `GRAPH_RAG_CHROMA_PATH` | Graph RAG's own ChromaDB directory | `./data/graph_rag_chroma` | `graph_rag/mcp_server.py` module init |
| `CI_DATABASE_PATH` | Codebase Intelligence SQLite database (read-only) | `./data/codebase_intel.db` | `graph_rag/mcp_server.py` module init, `GraphRAGIndexer._load_existing_data()` |
| `ARCHITECT_DATABASE_PATH` | Architect SQLite database (read-only) | `./data/architect.db` | `graph_rag/mcp_server.py` module init, `GraphRAGIndexer._load_existing_data()` |
| `CONTRACT_DATABASE_PATH` | Contract Engine SQLite database (read-only) | `./data/contracts.db` | `graph_rag/mcp_server.py` module init, `GraphRAGIndexer._load_existing_data()` |

### 13.3 Where Config Lives

`GraphRAGConfig` is defined in `C:\MY_PROJECTS\super-team\src\super_orchestrator\config.py` alongside existing `ArchitectConfig`, `BuilderConfig`, etc. It is loaded from the pipeline's YAML/JSON config file under the `graph_rag:` key, or uses defaults if the key is absent.

---

## 14. Risk Assessment

### Risk 1: Data Loading Fails Due to Missing Stores

**What:** The indexer attempts to read from CI, Architect, and Contract Engine SQLite databases. If any database is not initialized or is at a different path, loading fails.

**Why it's a risk:** The three databases are created by different MCP server initialization functions. The Graph RAG indexer runs in its own subprocess and may not have the correct paths.

**Mitigation:** Each data loading step in `_load_existing_data()` is wrapped in try/except. If a store is unavailable, the indexer proceeds with partial data. The build result includes a list of `errors` strings documenting what could not be loaded. The knowledge graph is still useful with partial data (e.g., even without contracts, the file/symbol/service graph provides value).

### Risk 2: MultiDiGraph Serialization Size

**What:** `nx.node_link_data()` on a MultiDiGraph with thousands of nodes and many attributes may produce a large JSON blob (potentially >10MB).

**Why it's a risk:** Storing large JSON in SQLite TEXT columns is slow. Loading it on startup adds latency.

**Mitigation:** The knowledge graph is rebuilt on each pipeline run, so startup loading is only needed if `force_rebuild=False`. For typical projects (500 files, 50 services, 2000 symbols), the JSON will be ~2-5MB -- well within SQLite's comfortable range. If needed, the snapshot can be gzip-compressed before storage (add `import gzip` -- simple enhancement).

### Risk 3: ChromaDB Embedding Computation Latency

**What:** Embedding thousands of node descriptions with `all-MiniLM-L6-v2` takes time.

**Why it's a risk:** The build pipeline has time constraints. If embedding 3000 nodes takes 30+ seconds, it may cause timeout issues.

**Mitigation:** `all-MiniLM-L6-v2` is the fastest sentence-transformer model (384 dims). Batch upserts of 300 records minimize API overhead (per CHROMADB_RESEARCH.md Section 8.1). For 3000 nodes, expect ~5-10 seconds on CPU. This is acceptable for a once-per-pipeline-run operation. If needed, reduce the number of embedded nodes by skipping low-PageRank file nodes.

### Risk 4: Community Detection on Disconnected Graphs

**What:** `nx.community.louvain_communities()` may behave unexpectedly on graphs with many disconnected components.

**Why it's a risk:** The knowledge graph may have disconnected subgraphs (isolated services, unlinked domain entities).

**Mitigation:** Louvain handles disconnected graphs correctly -- each connected component becomes its own community. We verify this in `test_compute_communities_returns_sets`. Isolated nodes get their own single-node community. The community_id is always assigned.

### Risk 5: Symbol-to-Entity Name Matching False Positives

**What:** The heuristic matching in `_match_symbols_to_entities()` (strip suffixes, lowercase compare) may create spurious `IMPLEMENTS_ENTITY` edges.

**Why it's a risk:** A domain entity named `Log` might match `LogService`, `Logger`, `LoginService`, etc.

**Mitigation:** The matching algorithm is conservative: only `class`, `interface`, and `type` symbols are candidates (not functions or variables). Suffix stripping is limited to a known list (`Service`, `Model`, `Schema`, `Entity`, `Repository`, `Controller`, `Handler`). The matching requires the base name to match exactly after normalization. `LoginService` normalizes to `Login`, not `Log`, so it would not match a `Log` entity. We include matched entity names in the build result for manual review.

### Risk 6: MCP Server Subprocess Startup Failure on Windows

**What:** The Graph RAG MCP server subprocess may fail to start due to Windows-specific issues (path length, env variable limits).

**Why it's a risk:** Per MEMORY.md, the super-team has encountered `WinError 206` from CLI argument length limits.

**Mitigation:** The MCP server is launched with minimal args (`["-m", "src.graph_rag.mcp_server"]`). Configuration is passed via environment variables, not CLI arguments. The env variable filtering pattern from `mcp_clients.py` (SEC-001) is followed: only `PATH`, `GRAPH_RAG_DB_PATH`, `GRAPH_RAG_CHROMA_PATH`, `CI_DATABASE_PATH`, `ARCHITECT_DATABASE_PATH`, and `CONTRACT_DATABASE_PATH` are passed. (Updated per INT-1 fix: all five database-related env vars are now included.)

### Risk 7: Gating Failure Causes Pipeline Crash

**What:** A bug in the gating logic causes Graph RAG code to execute when `enabled=False`, or a missing null check causes an AttributeError.

**Why it's a risk:** Graph RAG is a new module. Any regression in the pipeline's main path would block all pipeline runs.

**Mitigation:** Triple-layer gating:
1. Config check: `if not config.graph_rag.enabled: return`
2. try/except around all MCP calls
3. Optional parameters with safe defaults

Integration tests explicitly verify the disabled path (Section 11.7: `test_gating_disabled_graph_rag_produces_empty_context`).

---

*End of GRAPH_RAG_DESIGN.md*

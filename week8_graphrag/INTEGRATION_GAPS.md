# INTEGRATION_GAPS.md -- Week 8: Graph RAG Exploration

> **Generated:** 2026-02-23
> **Agent:** INTEGRATION ANALYST
> **Scope:** Gaps between Build 1 graph data, Build 2 context injection, and Build 3 cross-service awareness
> **Purpose:** Identify specific, concrete gaps where relationship context exists but is not surfaced, or is needed but currently impossible

---

## Table of Contents

- [Gap 1: What the Graph Knows vs What Builders Need](#gap-1-what-the-graph-knows-vs-what-builders-need)
- [Gap 2: What the Graph Knows vs What Layer 3 and Layer 4 Need](#gap-2-what-the-graph-knows-vs-what-layer-3-and-layer-4-need)
- [Gap 3: What the Graph Knows vs What the Fix Loop Needs](#gap-3-what-the-graph-knows-vs-what-the-fix-loop-needs)
- [Gap 4: What Is Already in the Graph but Not Exposed as an MCP Tool](#gap-4-what-is-already-in-the-graph-but-not-exposed-as-an-mcp-tool)
- [Gap 5: What Graph Queries Are Needed but Currently Impossible](#gap-5-what-graph-queries-are-needed-but-currently-impossible)

---

## Gap 1: What the Graph Knows vs What Builders Need

### Scenario: Three-service system (auth-service, order-service, notification-service)

When the super-orchestrator runs `run_parallel_builders()` in `C:\MY_PROJECTS\super-team\src\super_orchestrator\pipeline.py` (line ~637), it loads the service map from `service_map.json`, iterates over `services_raw`, and spawns one builder subprocess per service. Each builder is a Build 2 `agent_team` process that receives a PRD, a working directory, and optionally some contract/codebase context.

### What the Builder for order-service Currently Has

1. **Service map (flat JSON):** The builder receives its own service definition from `service_map.json` including `service_id`, `domain`, `stack`, `port`. This is stored in `builder_config.json` at the builder's output directory (pipeline.py line ~724-727). The builder knows its own name and stack but has no structured knowledge of sibling services.

2. **Contract stubs (flat JSON per service):** During the `run_contract_registration()` phase (pipeline.py line ~453), each service's OpenAPI stub is registered individually. The builder may receive a `contract_context` string (agents.py line ~2662) that is appended to the orchestrator prompt via `_append_contract_and_codebase_context()` (agents.py line ~2241-2255). This context is a flat text block listing contract IDs and provider services. It contains NO information about which other services consume order-service's API, or which APIs order-service needs to call.

3. **Codebase map summary (text string):** If the MCP-based codebase map is available, a markdown summary is injected via the `codebase_map_summary` parameter (agents.py line ~2687-2689). This summary from `generate_codebase_map_from_mcp()` in `C:\MY_PROJECTS\agent-team-v15\src\agent_team_v15\codebase_map.py` (line ~969-1037) contains only a module listing, endpoint count, and dead code candidates. It has NO dependency graph information, NO import relationships, NO service interaction topology.

4. **CLAUDE.md role instructions:** The `generate_claude_md()` function in `C:\MY_PROJECTS\agent-team-v15\src\agent_team_v15\claude_md_generator.py` (line ~216) generates role-specific instructions. The `dependencies` parameter (line ~224) accepts a `list[str]` but this is a simple name list -- it does not describe the nature of the dependency (API call? event subscription? shared schema?). The `codebase_context` parameter (line ~256) is an opaque string.

### What the Builder for order-service Needs but Cannot Get

1. **Consumer-provider topology:** "order-service calls `POST /auth/validate-token` on auth-service, and notification-service subscribes to `order.created` events from order-service." Currently, the only way to get this is from the domain model's `relationships` field, but that is stored as flat JSON in `C:\MY_PROJECTS\super-team\src\shared\db\schema.py` (`domain_models.data` column, line ~670) and never loaded into the builder's context. The `ServiceDefinition` dataclass in `C:\MY_PROJECTS\super-team\src\shared\models\architect.py` contains `consumes_contracts` and `provides_contracts` fields, but these are string lists, not traversable graph edges.

2. **Transitive dependency awareness:** "If auth-service's token validation schema changes, order-service's authentication middleware and notification-service's token-in-event-payload parsing both break." The NetworkX graph in `C:\MY_PROJECTS\super-team\src\codebase_intelligence\services\graph_builder.py` stores file-level import edges (line ~51-57, line ~70-79) but has no concept of service-to-service dependency. The `get_impact()` method in `graph_analyzer.py` (line ~145-150) does reverse BFS but only across file nodes, not service boundaries.

3. **Contract interface details for consumed services:** When the order-service builder needs to call auth-service's `/validate-token` endpoint, it needs the request/response schema of that endpoint. Currently, the builder would need to call the Contract Engine MCP `get_contract()` tool at runtime, but the builder subprocess does not have the Contract Engine MCP session configured -- only the orchestrator does. The builder's CLAUDE.md lists available MCP tools (claude_md_generator.py line ~110-118) but whether those MCP servers are actually running for the builder depends on the `mcp_servers` dict passed to `generate_claude_md()`, which is typically empty for builder subprocesses.

4. **Shared domain entity schemas:** The `DomainModel` from the Architect contains entities with their fields and owning services (`C:\MY_PROJECTS\super-team\src\shared\models\architect.py`, `DomainEntity` dataclass). If `User` entity is owned by auth-service but referenced by order-service, the builder for order-service has no way to discover the canonical field names, types, or validation rules. This leads to schema drift between services.

5. **Event schema compatibility:** The `ServiceInterface` extracted by `service_interface_extractor.py` (line ~81-148) detects `events_published` and `events_consumed` patterns with event names and channels. But there is no mechanism to check that the payload schema of `order.created` as published by order-service matches what notification-service expects to consume. This data exists in the AST analysis but is never connected across service boundaries.

### Summary Table: order-service Builder Context

| Context Category | Currently Has | Needs but Lacks |
|---|---|---|
| Own service definition | service_id, domain, stack, port | - |
| Own contract spec | OpenAPI stub (flat JSON) | - |
| Sibling service names | Only if manually listed in PRD | Always, with relationship type |
| APIs it must call | Nothing | auth-service endpoints with schemas |
| Events it publishes | Nothing | Schema for `order.created` payload |
| Events it consumes | Nothing | Schema for events from other services |
| Shared entity schemas | Nothing | `User` entity field definitions from auth-service |
| Transitive impact surface | Nothing | "If I change OrderResponse, notification-service breaks" |
| Contract compliance status | Nothing | "auth-service GET /users/{id} is IMPLEMENTED" |

---

## Gap 2: What the Graph Knows vs What Layer 3 and Layer 4 Need

### Current Scanner Architecture

**Layer 3** (`C:\MY_PROJECTS\super-team\src\quality_gate\layer3_system_level.py`) runs three concurrent sub-scanners: `SecurityScanner`, `ObservabilityChecker`, and `DockerSecurityScanner`. All three use static regex/AST pattern matching on individual files. They scan the filesystem at `target_dir` and look for patterns like hardcoded secrets (SEC-SECRET-*), missing JWT validation (SEC-001 to SEC-006), CORS misconfiguration (CORS-001 to CORS-003), and Docker best practices (DOCKER-001 to DOCKER-008).

**Layer 4** (`C:\MY_PROJECTS\super-team\src\quality_gate\layer4_adversarial.py` + `C:\MY_PROJECTS\super-team\src\quality_gate\adversarial_patterns.py`) runs the `AdversarialScanner` which detects:
- ADV-001: Dead event handlers (regex `@event_handler`, `@on_event`, `@subscriber` patterns, line ~38-42)
- ADV-002: Dead contracts (regex for `openapi`/`swagger`/`asyncapi` indicators in YAML/JSON, line ~45-50)
- ADV-003: Orphan services (looks for `main.py`/`app.py`/`server.py` entry points, line ~53-55)
- ADV-004: Naming inconsistency (camelCase in Python, line ~58-65)
- ADV-005: Missing error handling (bare except, line ~68-79)
- ADV-006: Potential race conditions (module-level mutable state, line ~82-97)

### What Layer 3 and Layer 4 Currently Cannot Detect (but a Graph Would Enable)

1. **Cross-service secret propagation (Layer 3 enhancement):**
   - Currently: SEC-SECRET-* scans each file individually for hardcoded strings.
   - With graph: Query `MATCH (f1)-[:IMPORTS]->(f2) WHERE f1.service_name != f2.service_name AND f2 CONTAINS secret_pattern` to find secrets that propagate across service boundaries via shared utility modules. A secret in `shared/config.py` imported by 3 services is more critical than a secret in a single service's test file.
   - Graph operation: Subgraph extraction of all cross-service import edges, then regex scan only on nodes reachable from multiple services.

2. **ADV-001 false positive reduction (Dead event handlers):**
   - Currently: The regex in adversarial_patterns.py (line ~38-42) finds event handler decorators and flags them as dead if the handler function is not called elsewhere. But it has no way to know if the decorated handler is triggered by an event published in a DIFFERENT service.
   - With graph: Query `MATCH (handler {kind: "event_handler", event_name: E})<-[:HANDLES]-(service_A), (publisher)-[:PUBLISHES {event_name: E}]->(service_B) WHERE service_A != service_B` to verify that a handler is actually subscribed to an event that IS published somewhere. If the publisher exists in another service, the handler is NOT dead.
   - Graph operation: Cross-service event matching -- correlate `events_published` from `ServiceInterface` of service B with `events_consumed` from service A.

3. **ADV-002 false positive/negative reduction (Dead contracts):**
   - Currently: Finds OpenAPI/AsyncAPI spec files via regex and flags contracts that appear unused. No ability to check if a contract is actually consumed by another service.
   - With graph: Query `MATCH (contract {service: S})-[:CONSUMED_BY]->(consumer_service) RETURN contract, count(consumer_service)`. Contracts with zero consumers are truly dead. Contracts consumed by 3+ services are high-risk for breaking changes.
   - Graph operation: Contract-to-consumer edge traversal, which requires linking Contract Engine data to Codebase Intelligence data.

4. **ADV-003 enhanced orphan detection (Orphan services):**
   - Currently: Looks for entry-point files (`main.py`, `app.py`, etc.) and flags services that have entry points but no Docker Compose references.
   - With graph: Query `MATCH (service) WHERE NOT EXISTS((service)-[:CALLED_BY|SUBSCRIBED_BY]->()) AND NOT EXISTS((service)-[:CALLS|PUBLISHES]->())` to find services completely disconnected from the service interaction graph, not just lacking a Docker reference.
   - Graph operation: Degree-zero node detection in the service interaction subgraph.

5. **Cross-service CORS validation (Layer 3 enhancement):**
   - Currently: CORS-001/002/003 check each service's CORS configuration independently.
   - With graph: Query `MATCH (frontend)-[:CALLS]->(backend) WHERE frontend.service_name = "gateway" RETURN backend.cors_origin` to verify that CORS origins on backend services actually match the domains that the frontend/gateway will call from. Currently, the scanner cannot know which services are called by the frontend.
   - Graph operation: Service call graph traversal from gateway/frontend service to all backend services.

6. **Security boundary violation detection (new capability):**
   - Currently impossible: No scanner checks if an internal-only service is accidentally exposed via Traefik routes.
   - With graph: Query `MATCH (service {visibility: "internal"})-[:EXPOSED_VIA]->(traefik_route {network: "frontend"})` to detect internal services on the frontend network.
   - Graph operation: Cross-reference Docker Compose network assignments with service visibility declarations from the domain model.

### Summary: Scanner Capabilities vs Graph RAG Capabilities

| Scanner Code | Current Method | Graph-Enhanced Method | False Positive Reduction |
|---|---|---|---|
| ADV-001 (dead handlers) | Regex for decorator + reference check within single project | Cross-service event publisher/consumer matching | High -- many handlers ARE alive via cross-service events |
| ADV-002 (dead contracts) | Regex for OpenAPI indicators | Contract-to-consumer traversal across service graph | High -- contracts consumed by other services are not dead |
| ADV-003 (orphan services) | Entry-point file existence check | Service interaction graph degree analysis | Medium -- some services are legitimately standalone |
| SEC-SECRET-* | Per-file regex scan | Cross-service import graph + PageRank-weighted severity | Medium -- shared module secrets are higher severity |
| CORS-* | Per-service config check | Frontend-to-backend call graph for origin validation | Medium -- validates CORS against actual callers |

---

## Gap 3: What the Graph Knows vs What the Fix Loop Needs

### Current Fix Loop Architecture

The fix loop in `C:\MY_PROJECTS\super-team\src\run4\fix_pass.py` executes a 6-step cycle: DISCOVER, CLASSIFY, GENERATE, APPLY, VERIFY, REGRESS.

In the GENERATE step, fix instructions are produced by `write_fix_instructions()` in `C:\MY_PROJECTS\super-team\src\run4\builder.py` (line ~310-373). This function takes a flat list of violation dicts and groups them by priority (P0/P1/P2). Each violation dict has: `code`, `component`, `evidence`, `action`, and `priority`.

In the APPLY step, `feed_violations_to_builder()` (builder.py line ~381-391) writes `FIX_INSTRUCTIONS.md` to the builder's working directory and re-invokes the builder in `quick` mode. The builder reads FIX_INSTRUCTIONS.md and attempts fixes.

### What the Fix Loop Currently Lacks

1. **No cross-service fix coordination:**
   - When a violation is detected in order-service (e.g., "response schema does not match contract"), the fix instruction is sent ONLY to the order-service builder. But if the contract violation stems from a shared entity schema change in auth-service, the fix must be applied in auth-service, not order-service.
   - Currently: `feed_violations_to_builder()` takes a single `cwd: Path` (builder.py line ~381) -- it targets exactly one service directory. There is no mechanism to route a fix instruction to a different service's builder.
   - With graph: Query `MATCH (violation {service: "order-service", code: "CONTRACT-SCHEMA-MISMATCH"})-[:CAUSED_BY]->(root_cause {service: "auth-service", file: "models/user.py"})` to determine the true fix target.
   - Graph operation: Root cause traversal from violation node to source node across service boundaries.

2. **No fix impact prediction:**
   - When the fix agent modifies `order-service/src/models/order.py`, the fix loop has no way to predict whether this change will regress notification-service (which may parse order events).
   - Currently: `detect_regressions()` in fix_pass.py (line ~104-145) compares before/after violation snapshots WITHIN the same scan. It cannot detect regressions that will manifest in a different service.
   - With graph: Query `MATCH (modified_file)-[:EXPORTS]->(symbol)-[:CONSUMED_BY]->(consumer_file) WHERE consumer_file.service_name != modified_file.service_name RETURN consumer_file` to predict cross-service impact.
   - Graph operation: Forward impact analysis across service boundary edges.

3. **No fix prioritization by architectural centrality:**
   - The `classify_priority()` function in fix_pass.py (line ~153-218) uses keyword matching on severity, category, and message text. A violation in a file with PageRank 0.95 (central hub) should be prioritized higher than a violation in a leaf file.
   - Currently: PageRank is computed by `graph_analyzer.py` (line ~52-58) and exposed via the `analyze_graph` MCP tool, but the fix loop never queries it. The priority classifier has no access to graph centrality data.
   - With graph: Query `MATCH (file {path: violation.file_path}) RETURN file.pagerank` and use it as a multiplier in priority classification.
   - Graph operation: Node attribute lookup on the dependency graph for the violated file.

4. **No duplicate/cascading fix detection:**
   - When the same root cause produces violations in 5 different files (e.g., a shared interface change), the fix loop generates 5 separate fix instructions. Each builder fix agent may attempt conflicting resolutions.
   - Currently: The `take_violation_snapshot()` function (fix_pass.py line ~32-96) groups violations by scan_code, but does not detect common causes across different codes.
   - With graph: Query `MATCH (v1)-[:IMPORTS]->(common_dep)<-[:IMPORTS]-(v2) WHERE v1.has_violation AND v2.has_violation RETURN common_dep, count(*)` to cluster violations by shared dependency.
   - Graph operation: Common ancestor detection in the dependency graph for the set of violated files.

5. **No fix instruction enrichment with dependency context:**
   - The `write_fix_instructions()` function (builder.py line ~310-373) emits markdown with code, component, evidence, and action. It provides NO context about what other files depend on the file being fixed, or what contracts constrain the fix.
   - With graph: For each violation, query `MATCH (file)-[:IMPORTED_BY]->(dependent) RETURN dependent LIMIT 10` and `MATCH (file)-[:IMPLEMENTS]->(contract) RETURN contract` to enrich fix instructions with "WARNING: 8 files depend on this module" and "This file implements contract GET /api/orders -- changes must maintain backward compatibility."
   - Graph operation: One-hop neighborhood query for each violated file node.

### Summary: Fix Loop Context Deficits

| Fix Phase | Currently Has | Needs but Lacks |
|---|---|---|
| CLASSIFY | Keyword-based severity/category matching | PageRank/centrality weighting, cross-service impact score |
| GENERATE | Flat list of violations per service | Root cause deduplication, dependency context, contract constraints |
| APPLY | Single-service fix instruction delivery | Cross-service fix routing (route fix to auth-service when violation is in order-service) |
| VERIFY | Before/after snapshot comparison within one scan | Cross-service regression prediction |
| REGRESS | New violations = regressions | Predicted vs actual regression correlation |

---

## Gap 4: What Is Already in the Graph but Not Exposed as an MCP Tool

### 4.1 Edge Attributes Are Stored but Not Queryable

The NetworkX graph in `graph_builder.py` stores rich edge attributes:
- `relation`: one of `"imports"`, `"calls"`, `"inherits"`, `"implements"`, `"uses"` (line ~54, ~73-75)
- `source_symbol` and `target_symbol`: qualified symbol IDs (line ~76-77)
- `line`: source line number (line ~55, ~78)
- `imported_names`: list of imported names (line ~56)

However, the `find_dependencies` MCP tool (mcp_server.py line ~261-314) returns only file paths in its `imports` and `imported_by` lists. The edge attributes (relation type, symbol names, line numbers) are discarded:
```python
deps = _graph_analyzer.get_dependencies(file_path, depth)  # Returns list[str] -- file paths only
dependents = _graph_analyzer.get_dependents(file_path, depth)  # Returns list[str] -- file paths only
```

The `get_dependencies()` and `get_dependents()` methods in `graph_analyzer.py` (line ~85-150) return `list[str]` (just node IDs), losing all edge attribute data.

**Hidden data:** For every edge in the graph, we know the relationship type (imports vs calls vs inherits vs implements vs uses), the specific symbols involved, and the line numbers. None of this is accessible through any MCP tool.

### 4.2 Node Attributes Are Stored but Not Queryable

Each node in the graph has `language` and `service_name` attributes set by `graph_builder.add_file()` (line ~108):
```python
self._graph.add_node(file_path, language=language, service_name=service_name)
```

No MCP tool exposes the ability to query "all files belonging to service X" from the graph (as opposed to the `indexed_files` SQL table). The graph's `service_name` attribute could enable service-level subgraph extraction, but this capability is not exposed.

**Hidden data:** The graph knows which service each file belongs to. A query like "extract the subgraph of all files in order-service and their cross-service edges" is possible with the data but not exposed.

### 4.3 Weakly Connected Components Are Computed but Not Exposed Per-Service

The `analyze()` method in `graph_analyzer.py` (line ~61-63) computes `nx.number_weakly_connected_components(self._graph)` -- the global count. But the actual component membership (which files are in which component) is not returned. The `analyze_graph` MCP tool (mcp_server.py line ~317-335) returns this as a single integer.

**Hidden data:** The actual list of connected components. A query like "which files are isolated from the main dependency cluster?" is answerable but not exposed.

### 4.4 The SQLite `dependency_edges` Table Contains Symbol-Level Edges Not in the Graph

The `dependency_edges` table in SQLite (schema.py line ~320-329) stores:
```sql
source_file, target_file, relation, line, imported_names, source_symbol, target_symbol
PRIMARY KEY (source_file, target_file, relation, source_symbol, target_symbol)
```

The `find_callers` MCP tool (mcp_server.py line ~374-430) queries this table directly (line ~405-413) to find symbol-level callers. But the results are limited to direct callers -- there is no transitive caller analysis. And crucially, the table supports multi-edge relationships (the primary key includes `source_symbol` and `target_symbol`), meaning multiple edges can exist between the same two files with different symbol-level connections. The NetworkX graph, which uses `add_edge()` with `(source_file, target_file)`, OVERWRITES parallel edges because NetworkX DiGraph does not support multi-edges by default.

**Hidden data:** The SQLite table preserves all symbol-level edges between two files. The NetworkX graph loses all but the last edge per file pair. Any edge added via `build_graph()` overwrites the previous edge between the same two files (graph_builder.py line ~51-57, ~70-79).

### 4.5 ServiceInterface Data Is Not Linked to the Graph

The `get_service_interface` MCP tool (mcp_server.py line ~433-502) extracts endpoints, events_published, events_consumed, and exported_symbols for a service. This data is returned as a flat dict and is NOT stored in the NetworkX graph or ChromaDB. It is computed on-the-fly by reading source files from disk.

**Hidden data:** The service interface extraction contains the exact endpoint paths, HTTP methods, handler function names, event names, and channels for each service. If this data were stored as graph nodes/edges, we could query "which services publish events that no service consumes" or "which endpoints have no corresponding contract."

### 4.6 The Domain Model Contains Relationships Not Connected to Code

The `DomainModel` stored in `domain_models` SQLite table (schema.py line ~669-674) contains `DomainRelationship` objects with:
- `source_entity`, `target_entity`
- `relationship_type`: OWNS, REFERENCES, TRIGGERS, EXTENDS, DEPENDS_ON
- `cardinality`

These domain-level relationships are never connected to the code-level dependency graph. The Architect MCP `get_domain_model` tool returns them as flat JSON. There is no mechanism to traverse from "Order REFERENCES User" (domain level) to "order_service.py imports user_model from auth_service" (code level).

**Hidden data:** The entire domain relationship graph exists in structured form but is completely disconnected from the code dependency graph.

### Summary: Hidden Data in Existing Stores

| Data Location | What Is Stored | What Is Exposed | What Is Hidden |
|---|---|---|---|
| NetworkX edge attributes | relation, source_symbol, target_symbol, line, imported_names | File path lists only | All edge attributes |
| NetworkX node attributes | language, service_name | Nothing (not queryable) | Per-node service affiliation |
| SQLite dependency_edges | Multi-edge symbol-level relationships | Single-edge file-level through graph | Parallel edges between same file pair |
| ServiceInterface (computed on-the-fly) | Endpoints, events, exported symbols | Returned once per call, not persisted | Cross-service event matching data |
| DomainModel (SQLite JSON) | Entity relationships with types and cardinality | Flat JSON via get_domain_model | Domain-to-code traceability edges |
| Connected components | Per-component membership lists | Global count integer | Isolated file clusters |

---

## Gap 5: What Graph Queries Are Needed but Currently Impossible

### 5.1 Service Interaction Topology Queries

These queries require a service-level graph that does not currently exist. The existing graph is file-level only.

| Query | Graph Operation | Use Case |
|---|---|---|
| "Find all services that transitively depend on auth-service" | Forward BFS from auth-service node in service interaction graph | Builder context: know which services break if auth-service changes |
| "Find the shortest path of API calls from user-input to database-write" | Dijkstra/BFS across service call edges | Security audit: trace untrusted input propagation |
| "Find all services that order-service calls, and all services that call order-service" | One-hop neighborhood in service interaction graph | Fix loop: determine cross-service impact of order-service changes |
| "Detect service cycles (A calls B calls C calls A)" | `nx.simple_cycles()` on service interaction graph | Architecture review: identify circular service dependencies |
| "Find services with highest in-degree (most depended upon)" | Degree centrality on service interaction graph | Risk assessment: identify critical services |

**Why impossible:** The NetworkX graph in `graph_builder.py` contains file-level nodes, not service-level nodes. While nodes have a `service_name` attribute, there is no aggregated service-level graph. Building one would require: (1) grouping file nodes by `service_name`, (2) creating service-level super-nodes, (3) creating edges between super-nodes wherever a file in service A imports/calls a file in service B.

### 5.2 Contract-Code Traceability Queries

These queries require edges between contract definitions and implementing code, which do not exist.

| Query | Graph Operation | Use Case |
|---|---|---|
| "Find all code that implements `GET /api/orders`" | Edge traversal from contract endpoint node to handler function nodes | Contract compliance: verify implementation exists |
| "Find all contracts that order-service provides but no service currently consumes" | Degree-zero check on outgoing edges from order-service contract nodes | Dead contract detection (ADV-002 enhancement) |
| "Find endpoints in code that have no corresponding contract" | Set difference: code endpoints minus contract endpoints | Shadow endpoint detection |
| "Find contracts where the response schema does not match the actual return type" | Compare contract schema node with code return-type node | Schema drift detection |

**Why impossible:** The Contract Engine stores contracts in `C:\MY_PROJECTS\super-team\src\contract_engine\services\contract_store.py` (SQLite). The Codebase Intelligence stores code symbols in a separate SQLite database. There is no join key between them. The `ImplementationTracker` (contract_engine) requires manual `mark_implemented()` calls with an `evidence_path` string -- there is no automated contract-to-code linking.

### 5.3 Domain-to-Code Traceability Queries

These queries require edges between domain entities and their implementing code symbols.

| Query | Graph Operation | Use Case |
|---|---|---|
| "Find all code files that implement the `Order` domain entity" | Traverse from DomainEntity node to SymbolDefinition nodes | Impact analysis: entity schema change affects which files? |
| "Find domain entities that have no implementing code" | Degree-zero check on DomainEntity-to-code edges | Architecture gap: entities declared but never implemented |
| "Find code symbols that reference no domain entity" | Degree-zero check on code-to-DomainEntity edges | Orphan code: implementation without architectural grounding |
| "Trace data flow from `User.email` field through all services" | Multi-hop traversal following field references across service boundaries | GDPR/privacy: where does PII flow? |

**Why impossible:** The `DomainModel` exists as JSON in the `domain_models` table. The `SymbolDefinition` objects exist in the `symbols` table. There is no mapping table or graph edge connecting domain entities to code symbols. The entity name `Order` and the code class `OrderService` are semantically related but not explicitly linked.

### 5.4 Hybrid Graph + Vector Queries

These queries require combining graph structure with semantic similarity, which the current architecture cannot do.

| Query | Combined Operation | Use Case |
|---|---|---|
| "Find code semantically similar to `validate user token` that is within 2 hops of `auth-service/routes.py`" | ChromaDB semantic search filtered by graph neighborhood | Context window construction: relevant code near the focal point |
| "Find the most relevant code to include in a fix instruction, weighted by both semantic relevance and dependency proximity" | Semantic score * (1 / graph_distance) ranking | Fix loop: smarter context for fix agents |
| "Find all implementations of a pattern similar to `retry with exponential backoff` across all services" | Semantic search + service_name grouping from graph node attributes | Architecture review: consistency check across services |
| "Given a failing test, find the most likely root cause file considering both error message similarity and dependency graph proximity" | Semantic search on error message + reverse BFS from test file | Debugging: root cause ranking |

**Why impossible:** ChromaDB and NetworkX are completely separate systems. `SemanticSearcher.search()` in `C:\MY_PROJECTS\super-team\src\codebase_intelligence\services\semantic_searcher.py` returns results based solely on vector distance. There is no mechanism to filter or re-rank results by graph proximity. The `_build_where_filter()` method (line ~78-100) only supports `language` and `service_name` metadata filters, not graph-structural filters.

### 5.5 Temporal/Evolutionary Queries

These queries require comparing graph states across time, which the current snapshot system does not support.

| Query | Required Data | Use Case |
|---|---|---|
| "When did the circular dependency between auth-service and order-service first appear?" | Graph snapshot diff over time | Architecture regression: identify when bad patterns were introduced |
| "Which files have gained the most new dependents in the last 3 builds?" | Delta between consecutive graph snapshots | Architectural drift: files becoming unexpected hubs |
| "Has the service interaction topology changed since the last pipeline run?" | Service-level graph diff | Build-over-build comparison |

**Why impossible:** The `graph_snapshots` table in SQLite (schema.py line ~341-345) stores serialized graphs with timestamps, but only the latest snapshot is loaded on startup (`graph_db.load_snapshot()` returns `ORDER BY id DESC LIMIT 1`). Historical snapshots are never queried. There is no diff algorithm between graph versions.

### 5.6 Community Detection and Service Boundary Validation

| Query | Graph Operation | Use Case |
|---|---|---|
| "Do the actual code dependency clusters match the declared service boundaries?" | Community detection (Louvain/Girvan-Newman) vs service_name attribute comparison | Architecture validation: are service boundaries correctly drawn? |
| "Find files that are more tightly coupled to a different service than the one they belong to" | Compare intra-service edge density vs inter-service edge density per file | Misplaced code: file in wrong service |
| "Find the minimum edge cut between auth-service and order-service" | `nx.minimum_edge_cut()` on the subgraph | Coupling assessment: how entangled are two services? |

**Why impossible:** While NetworkX supports community detection algorithms (`nx.community`), they are never invoked in the current codebase. The `GraphAnalyzer` class only implements PageRank, cycle detection, DAG check, topological sort, and BFS (graph_analyzer.py line ~27-150). Service boundary validation requires correlating graph structure with the `service_name` node attributes, which is not implemented.

---

## Appendix: Source File Reference

All file paths and line numbers referenced in this document correspond to the following source files:

### Build 1 (super-team)
- `C:\MY_PROJECTS\super-team\src\codebase_intelligence\services\graph_builder.py` -- NetworkX DiGraph construction
- `C:\MY_PROJECTS\super-team\src\codebase_intelligence\services\graph_analyzer.py` -- Graph analysis algorithms
- `C:\MY_PROJECTS\super-team\src\codebase_intelligence\mcp_server.py` -- 8 MCP tools
- `C:\MY_PROJECTS\super-team\src\codebase_intelligence\services\semantic_searcher.py` -- ChromaDB query pipeline
- `C:\MY_PROJECTS\super-team\src\codebase_intelligence\storage\chroma_store.py` -- ChromaDB wrapper
- `C:\MY_PROJECTS\super-team\src\codebase_intelligence\services\service_interface_extractor.py` -- Endpoint/event extraction
- `C:\MY_PROJECTS\super-team\src\shared\models\architect.py` -- DomainModel, ServiceDefinition
- `C:\MY_PROJECTS\super-team\src\shared\db\schema.py` -- SQLite schemas
- `C:\MY_PROJECTS\super-team\src\quality_gate\layer3_system_level.py` -- Layer 3 scanner
- `C:\MY_PROJECTS\super-team\src\quality_gate\layer4_adversarial.py` -- Layer 4 scanner
- `C:\MY_PROJECTS\super-team\src\quality_gate\adversarial_patterns.py` -- ADV-001 to ADV-006 regex patterns
- `C:\MY_PROJECTS\super-team\src\integrator\cross_service_test_generator.py` -- Cross-service flow detection
- `C:\MY_PROJECTS\super-team\src\integrator\data_flow_tracer.py` -- W3C trace context tracer
- `C:\MY_PROJECTS\super-team\src\run4\fix_pass.py` -- 6-step fix cycle
- `C:\MY_PROJECTS\super-team\src\run4\builder.py` -- Builder invocation and FIX_INSTRUCTIONS.md generation
- `C:\MY_PROJECTS\super-team\src\super_orchestrator\pipeline.py` -- Main pipeline orchestration

### Build 2 (agent-team-v15)
- `C:\MY_PROJECTS\agent-team-v15\src\agent_team_v15\codebase_map.py` -- Static analysis + MCP-based codebase map
- `C:\MY_PROJECTS\agent-team-v15\src\agent_team_v15\agents.py` -- Prompt construction (build_orchestrator_prompt, build_milestone_execution_prompt)
- `C:\MY_PROJECTS\agent-team-v15\src\agent_team_v15\claude_md_generator.py` -- CLAUDE.md generation with contract/codebase context
- `C:\MY_PROJECTS\agent-team-v15\src\agent_team_v15\contract_client.py` -- Contract Engine MCP client
- `C:\MY_PROJECTS\agent-team-v15\src\agent_team_v15\codebase_client.py` -- Codebase Intelligence MCP client
- `C:\MY_PROJECTS\agent-team-v15\src\agent_team_v15\contracts.py` -- Local ContractRegistry + ServiceContractRegistry

---

*End of INTEGRATION_GAPS.md*

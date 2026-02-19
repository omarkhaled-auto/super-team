# MCP Tools Reference

## Overview

The **Model Context Protocol (MCP)** is an open standard that enables AI assistants such as Claude Code to communicate with external tool servers over a structured, bidirectional channel. Instead of hard-coding integrations, Claude Code discovers available tools at runtime by connecting to one or more MCP servers declared in a `.mcp.json` configuration file at the project root.

The Super Agent Team platform exposes **18 tools** across **3 MCP servers**:

| Server | Purpose | Tools |
|---|---|---|
| **Architect** | PRD decomposition, service maps, domain models | 3 |
| **Contract Engine** | API contract lifecycle management | 9 |
| **Codebase Intelligence** | Code indexing, semantic search, dependency analysis | 6 |

All three servers use **stdio transport** via [FastMCP](https://github.com/jlowin/fastmcp) and are launched as Python modules.

---

## Configuration

Place the following `.mcp.json` file in the project root so Claude Code can discover and connect to every server automatically:

```json
{
  "mcpServers": {
    "architect": {
      "command": "python",
      "args": ["-m", "src.architect.mcp_server"],
      "env": {
        "DATABASE_PATH": "./data/architect.db",
        "CONTRACT_ENGINE_URL": "http://localhost:8002"
      }
    },
    "contract-engine": {
      "command": "python",
      "args": ["-m", "src.contract_engine.mcp_server"],
      "env": {
        "DATABASE_PATH": "./data/contracts.db"
      }
    },
    "codebase-intelligence": {
      "command": "python",
      "args": ["-m", "src.codebase_intelligence.mcp_server"],
      "env": {
        "DATABASE_PATH": "./data/symbols.db",
        "CHROMA_PATH": "./data/chroma",
        "GRAPH_PATH": "./data/graph.json"
      }
    }
  }
}
```

When Claude Code opens a project containing this file it will:

1. Spawn each server as a child process using the specified `command` and `args`.
2. Negotiate capabilities over stdio.
3. Register every tool the server advertises so that Claude can call them during a conversation.

---

## Architect MCP Server

**Server name:** `Architect`
**Version:** `1.0.0` (platform VERSION)
**Module:** `src.architect.mcp_server`

The Architect server handles high-level system design. Given a Product Requirements Document it can decompose the system into services, build a domain model, and generate OpenAPI contract stubs.

### `decompose_prd`

Decompose a Product Requirements Document into services, domain model, and contracts. Runs the full Architect decomposition pipeline including PRD parsing, service boundary identification, service map building, domain model building, decomposition validation, and OpenAPI 3.1 contract stub generation.

#### Parameters

| Name | Type | Required | Description |
|---|---|---|---|
| `prd_text` | `str` | Yes | The full text of the PRD document (Markdown or plain text) |

#### Return Value

A `dict` containing:

| Field | Description |
|---|---|
| `service_map` | The decomposed service map |
| `domain_model` | The domain model with entities and relationships |
| `contract_stubs` | OpenAPI 3.1 specs for each service |
| `validation_issues` | List of detected structural issues (may be empty) |
| `interview_questions` | Clarification questions for ambiguous requirements |

#### Example Usage

```python
result = await mcp.call("decompose_prd", {
    "prd_text": "# My SaaS Platform\n\n## Overview\nA multi-tenant SaaS platform..."
})

print(result["service_map"])          # service topology
print(result["contract_stubs"])       # generated OpenAPI 3.1 specs
print(result["interview_questions"])  # follow-up questions
```

---

### `get_service_map`

Retrieve the most recent service map, optionally filtered by project name.

#### Parameters

| Name | Type | Required | Default | Description |
|---|---|---|---|---|
| `project_name` | `str` | No | _None_ | Project name to filter by. When omitted, latest service map across all projects is returned |

#### Return Value

A `dict` containing the service map as a JSON-serializable dictionary, or `{"error": "..."}` if not found.

#### Example Usage

```python
# Latest service map across all projects
service_map = await mcp.call("get_service_map", {})

# Service map for a specific project
service_map = await mcp.call("get_service_map", {
    "project_name": "my-saas-platform"
})
```

---

### `get_domain_model`

Retrieve the most recent domain model, optionally filtered by project name.

#### Parameters

| Name | Type | Required | Default | Description |
|---|---|---|---|---|
| `project_name` | `str` | No | _None_ | Project name to filter by. When omitted, latest domain model across all projects is returned |

#### Return Value

A `dict` containing the domain model as a JSON-serializable dictionary, or `{"error": "..."}` if not found.

#### Example Usage

```python
# Latest domain model across all projects
domain_model = await mcp.call("get_domain_model", {})

# Domain model for a specific project
domain_model = await mcp.call("get_domain_model", {
    "project_name": "my-saas-platform"
})
```

---

## Contract Engine MCP Server

**Server name:** `Contract Engine`
**Module:** `src.contract_engine.mcp_server`

The Contract Engine manages the full lifecycle of API contracts -- creation, validation, versioning, breaking-change detection, implementation tracking, test generation, and runtime compliance checking.

### `create_contract`

Create or update an API contract. Validates the contract type, persists the specification via upsert, and returns the stored contract entry.

#### Parameters

| Name | Type | Required | Default | Description |
|---|---|---|---|---|
| `service_name` | `str` | Yes | -- | Name of the service that owns this contract |
| `type` | `str` | Yes | -- | Contract type -- `"openapi"`, `"asyncapi"`, or `"json_schema"` |
| `version` | `str` | Yes | -- | Semantic version string (e.g. `"1.0.0"`) |
| `spec` | `dict` | Yes | -- | The full specification document |
| `build_cycle_id` | `str` | No | _None_ | Build cycle identifier for immutability tracking |

#### Return Value

A `dict` containing the persisted contract entry, or `{"error": "..."}` on validation errors.

#### Example Usage

```python
contract = await mcp.call("create_contract", {
    "service_name": "user-service",
    "type": "openapi",
    "version": "1.0.0",
    "spec": {
        "openapi": "3.1.0",
        "info": {"title": "User Service", "version": "1.0.0"},
        "paths": {
            "/users": {
                "get": {
                    "summary": "List users",
                    "responses": {"200": {"description": "OK"}}
                }
            }
        }
    }
})
```

---

### `list_contracts`

List contracts with optional filtering and pagination.

#### Parameters

| Name | Type | Required | Default | Description |
|---|---|---|---|---|
| `page` | `int` | No | `1` | Page number (1-based) |
| `page_size` | `int` | No | `20` | Items per page (max 100) |
| `service_name` | `str` | No | _None_ | Filter by service |
| `contract_type` | `str` | No | _None_ | Filter by type (`openapi` / `asyncapi` / `json_schema`) |
| `status` | `str` | No | _None_ | Filter by status (`active` / `deprecated` / `draft`) |

#### Return Value

A `dict` with the following shape:

```json
{
  "items": [],
  "total": 0,
  "page": 1,
  "page_size": 20
}
```

#### Example Usage

```python
# List all active OpenAPI contracts for user-service
result = await mcp.call("list_contracts", {
    "service_name": "user-service",
    "contract_type": "openapi",
    "status": "active",
    "page": 1,
    "page_size": 10
})

for contract in result["items"]:
    print(contract["id"], contract["version"])
```

---

### `get_contract`

Retrieve a single contract by its unique identifier.

#### Parameters

| Name | Type | Required | Description |
|---|---|---|---|
| `contract_id` | `str` | Yes | UUID of the contract |

#### Return Value

A `dict` containing the contract entry, or `{"error": "..."}` if not found.

#### Example Usage

```python
contract = await mcp.call("get_contract", {
    "contract_id": "550e8400-e29b-41d4-a716-446655440000"
})
```

---

### `validate_contract`

Validate a contract specification without persisting it.

#### Parameters

| Name | Type | Required | Description |
|---|---|---|---|
| `spec` | `dict` | Yes | The specification document to validate |
| `type` | `str` | Yes | Contract type -- `"openapi"`, `"asyncapi"`, or `"json_schema"` |

#### Return Value

A `dict` with the following shape:

```json
{
  "valid": true,
  "errors": [],
  "warnings": []
}
```

#### Example Usage

```python
result = await mcp.call("validate_contract", {
    "type": "openapi",
    "spec": {
        "openapi": "3.1.0",
        "info": {"title": "My API", "version": "1.0.0"},
        "paths": {}
    }
})

if result["valid"]:
    print("Specification is valid")
else:
    for error in result["errors"]:
        print("ERROR:", error)
```

---

### `detect_breaking_changes`

Detect breaking changes for a contract. If `new_spec` is provided, compares the current spec against the new spec. Otherwise retrieves version history.

#### Parameters

| Name | Type | Required | Default | Description |
|---|---|---|---|---|
| `contract_id` | `str` | Yes | -- | UUID of the contract |
| `new_spec` | `dict` | No | _None_ | New specification to compare against current |

#### Return Value

A `list` of breaking-change dicts, or `[{"error": "..."}]` if the contract is not found.

#### Example Usage

```python
# Compare current contract against a proposed new spec
changes = await mcp.call("detect_breaking_changes", {
    "contract_id": "550e8400-e29b-41d4-a716-446655440000",
    "new_spec": {
        "openapi": "3.1.0",
        "info": {"title": "User Service", "version": "2.0.0"},
        "paths": {}
    }
})

for change in changes:
    print(change)
```

---

### `mark_implementation`

Mark a contract as implemented by a service.

#### Parameters

| Name | Type | Required | Description |
|---|---|---|---|
| `contract_id` | `str` | Yes | UUID of the contract |
| `service_name` | `str` | Yes | Name of the implementing service |
| `evidence_path` | `str` | Yes | Filesystem path to implementation evidence |

#### Return Value

A `dict` with the following shape:

```json
{
  "marked": true,
  "total_implementations": 1,
  "all_implemented": false
}
```

#### Example Usage

```python
result = await mcp.call("mark_implementation", {
    "contract_id": "550e8400-e29b-41d4-a716-446655440000",
    "service_name": "user-service",
    "evidence_path": "src/user_service/routes/users.py"
})

if result["all_implemented"]:
    print("All services have implemented this contract")
```

---

### `get_unimplemented`

List contracts that have not yet been fully implemented.

#### Parameters

| Name | Type | Required | Default | Description |
|---|---|---|---|---|
| `service_name` | `str` | No | _None_ | Filter to a single service |

#### Return Value

A `list` of unimplemented-contract dicts, each containing:

| Field | Description |
|---|---|
| `id` | Contract UUID |
| `type` | Contract type |
| `version` | Semantic version |
| `expected_service` | Service expected to implement |
| `status` | Contract status |

#### Example Usage

```python
# All unimplemented contracts
unimplemented = await mcp.call("get_unimplemented", {})

# Only for a specific service
unimplemented = await mcp.call("get_unimplemented", {
    "service_name": "order-service"
})

for contract in unimplemented:
    print(f"{contract['id']} - {contract['expected_service']} ({contract['type']})")
```

---

### `generate_tests`

Generate a test suite from a stored contract. Produces executable test code (Schemathesis for OpenAPI, jsonschema for AsyncAPI).

#### Parameters

| Name | Type | Required | Default | Description |
|---|---|---|---|---|
| `contract_id` | `str` | Yes | -- | UUID of the contract |
| `framework` | `str` | No | `"pytest"` | `"pytest"` or `"jest"` |
| `include_negative` | `bool` | No | `False` | Include negative/4xx test cases |

#### Return Value

A `dict` with the following shape:

```json
{
  "contract_id": "550e8400-...",
  "framework": "pytest",
  "test_code": "import schemathesis\n...",
  "test_count": 12,
  "generated_at": "2026-01-15T10:30:00Z"
}
```

#### Example Usage

```python
tests = await mcp.call("generate_tests", {
    "contract_id": "550e8400-e29b-41d4-a716-446655440000",
    "framework": "pytest",
    "include_negative": True
})

# Write the generated tests to disk
with open("tests/test_user_service_contract.py", "w") as f:
    f.write(tests["test_code"])

print(f"Generated {tests['test_count']} tests")
```

---

### `check_compliance`

Check runtime response data against a contract's endpoint schemas.

#### Parameters

| Name | Type | Required | Default | Description |
|---|---|---|---|---|
| `contract_id` | `str` | Yes | -- | UUID of the contract |
| `response_data` | `dict` | No | _None_ | Mapping of `"METHOD /path"` to response body dicts |

#### Return Value

A `list` of compliance-result dicts, each containing:

| Field | Description |
|---|---|
| `endpoint_path` | The API path checked |
| `method` | HTTP method |
| `compliant` | `true` / `false` |
| `violations` | List of violations found |

#### Example Usage

```python
results = await mcp.call("check_compliance", {
    "contract_id": "550e8400-e29b-41d4-a716-446655440000",
    "response_data": {
        "GET /users": {
            "users": [
                {"id": 1, "name": "Alice", "email": "alice@example.com"}
            ]
        },
        "GET /users/1": {
            "id": 1,
            "name": "Alice",
            "email": "alice@example.com"
        }
    }
})

for result in results:
    status = "PASS" if result["compliant"] else "FAIL"
    print(f"[{status}] {result['method']} {result['endpoint_path']}")
    for v in result["violations"]:
        print(f"  - {v}")
```

---

## Codebase Intelligence MCP Server

**Server name:** `Codebase Intelligence`
**Module:** `src.codebase_intelligence.mcp_server`

The Codebase Intelligence server indexes source code into a searchable symbol database backed by ChromaDB for semantic search and a dependency graph for structural analysis.

### `index_file`

Index a source file through the full codebase-intelligence pipeline (AST parse, symbol extraction, import resolution, dependency graph update, semantic embeddings).

#### Parameters

| Name | Type | Required | Default | Description |
|---|---|---|---|---|
| `file_path` | `str` | Yes | -- | Path to the source file |
| `service_name` | `str` | No | _None_ | Service name the file belongs to |
| `source_base64` | `str` | No | _None_ | Base64-encoded file contents (used instead of reading from disk) |
| `project_root` | `str` | No | _None_ | Project root for import resolution |

#### Return Value

A `dict` with the following shape:

```json
{
  "indexed": true,
  "symbols_found": 14,
  "dependencies_found": 5,
  "errors": []
}
```

#### Example Usage

```python
result = await mcp.call("index_file", {
    "file_path": "src/user_service/models/user.py",
    "service_name": "user-service",
    "project_root": "/workspace/my-project"
})

print(f"Indexed {result['symbols_found']} symbols, {result['dependencies_found']} deps")
```

---

### `search_code`

Search indexed code using natural-language semantic similarity via ChromaDB.

#### Parameters

| Name | Type | Required | Default | Description |
|---|---|---|---|---|
| `query` | `str` | Yes | -- | Natural-language or code search query |
| `language` | `str` | No | _None_ | Language filter (`python` / `typescript` / `csharp` / `go`) |
| `service_name` | `str` | No | _None_ | Service name filter |
| `top_k` | `int` | No | `10` | Max results |

#### Return Value

A `list` of search result dicts sorted by descending score.

#### Example Usage

```python
results = await mcp.call("search_code", {
    "query": "function that hashes user passwords",
    "language": "python",
    "service_name": "auth-service",
    "top_k": 5
})

for hit in results:
    print(f"{hit['file_path']}:{hit['line']} - {hit['symbol_name']} (score: {hit['score']:.3f})")
```

---

### `get_symbols`

Look up symbol definitions from the index by file, name, kind, language, or service.

#### Parameters

| Name | Type | Required | Default | Description |
|---|---|---|---|---|
| `name` | `str` | No | _None_ | Exact symbol name |
| `kind` | `str` | No | _None_ | Symbol kind (`class` / `function` / `interface` / `type` / `enum` / `variable` / `method`) |
| `language` | `str` | No | _None_ | Language filter |
| `service_name` | `str` | No | _None_ | Service name filter |
| `file_path` | `str` | No | _None_ | File path to get all symbols from |

#### Return Value

A `list` of symbol definition dicts.

#### Example Usage

```python
# Find all classes in the user-service
classes = await mcp.call("get_symbols", {
    "kind": "class",
    "service_name": "user-service"
})

# Look up a specific function by name
symbols = await mcp.call("get_symbols", {
    "name": "hash_password",
    "kind": "function"
})

# Get every symbol in a file
symbols = await mcp.call("get_symbols", {
    "file_path": "src/user_service/models/user.py"
})
```

---

### `get_dependencies`

Retrieve dependency relationships for a file (forward/reverse/both).

#### Parameters

| Name | Type | Required | Default | Description |
|---|---|---|---|---|
| `file_path` | `str` | Yes | -- | File to query |
| `depth` | `int` | No | `1` | Max traversal depth |
| `direction` | `str` | No | `"both"` | `"forward"`, `"reverse"`, or `"both"` |

#### Return Value

A `dict` with the following shape:

```json
{
  "file_path": "src/user_service/models/user.py",
  "depth": 1,
  "dependencies": [],
  "dependents": []
}
```

#### Example Usage

```python
deps = await mcp.call("get_dependencies", {
    "file_path": "src/user_service/models/user.py",
    "depth": 2,
    "direction": "both"
})

print("This file depends on:")
for d in deps["dependencies"]:
    print(f"  -> {d}")

print("These files depend on this file:")
for d in deps["dependents"]:
    print(f"  <- {d}")
```

---

### `analyze_graph`

Analyse the full dependency graph for structural metrics (DAG check, cycles, PageRank, build order).

#### Parameters

_None._

#### Return Value

A `dict` containing:

| Field | Description |
|---|---|
| `node_count` | Total number of nodes in the graph |
| `edge_count` | Total number of edges |
| `is_dag` | Whether the graph is a directed acyclic graph |
| `circular_dependencies` | List of detected cycles |
| `top_files_by_pagerank` | Files ranked by PageRank as `[file_path, score]` tuples |
| `connected_components` | Number of weakly-connected components (int) |
| `build_order` | Topological build order (only if `is_dag` is `true`), or `null` |

#### Example Usage

```python
analysis = await mcp.call("analyze_graph", {})

print(f"Graph: {analysis['node_count']} nodes, {analysis['edge_count']} edges")
print(f"Is DAG: {analysis['is_dag']}")

if not analysis["is_dag"]:
    print("Circular dependencies detected:")
    for cycle in analysis["circular_dependencies"]:
        print(f"  {' -> '.join(cycle)}")
```

---

### `detect_dead_code`

Detect potentially unused (dead) code by cross-referencing symbols against the dependency graph.

#### Parameters

| Name | Type | Required | Default | Description |
|---|---|---|---|---|
| `service_name` | `str` | No | _None_ | Limit analysis to a service |

#### Return Value

A `list` of dead code entry dicts, each containing:

| Field | Description |
|---|---|
| `symbol_name` | Name of the unused symbol |
| `file_path` | File where the symbol is defined |
| `kind` | Symbol kind (class, function, etc.) |
| `line` | Line number of the definition |
| `confidence` | `high`, `medium`, or `low` |

#### Example Usage

```python
dead = await mcp.call("detect_dead_code", {
    "service_name": "user-service"
})

for entry in dead:
    print(f"[{entry['confidence']}] {entry['kind']} {entry['symbol_name']} "
          f"at {entry['file_path']}:{entry['line']}")
```

---

## Summary Table

The table below lists every tool, the server it belongs to, and a brief description.

| # | Tool | Server | Description |
|---|---|---|---|
| 1 | `decompose_prd` | Architect | Decompose a PRD into services, domain model, and OpenAPI contract stubs |
| 2 | `get_service_map` | Architect | Retrieve the most recent service map |
| 3 | `get_domain_model` | Architect | Retrieve the most recent domain model |
| 4 | `create_contract` | Contract Engine | Create or update an API contract |
| 5 | `list_contracts` | Contract Engine | List contracts with filtering and pagination |
| 6 | `get_contract` | Contract Engine | Retrieve a single contract by UUID |
| 7 | `validate_contract` | Contract Engine | Validate a contract spec without persisting |
| 8 | `detect_breaking_changes` | Contract Engine | Detect breaking changes between contract versions |
| 9 | `mark_implementation` | Contract Engine | Mark a contract as implemented by a service |
| 10 | `get_unimplemented` | Contract Engine | List contracts not yet fully implemented |
| 11 | `generate_tests` | Contract Engine | Generate test suites from a stored contract |
| 12 | `check_compliance` | Contract Engine | Check runtime responses against contract schemas |
| 13 | `index_file` | Codebase Intelligence | Index a source file through the full pipeline |
| 14 | `search_code` | Codebase Intelligence | Semantic code search via ChromaDB |
| 15 | `get_symbols` | Codebase Intelligence | Look up symbol definitions from the index |
| 16 | `get_dependencies` | Codebase Intelligence | Retrieve dependency relationships for a file |
| 17 | `analyze_graph` | Codebase Intelligence | Analyse the full dependency graph for structural metrics |
| 18 | `detect_dead_code` | Codebase Intelligence | Detect potentially unused code |

# GAP AUDIT -- super-team Project

**Date:** 2026-02-23
**Auditor:** gap-auditor agent
**Project:** `C:\MY_PROJECTS\super-team`

---

## Table of Contents

1. [1A: State Machine Parser](#1a-state-machine-parser)
2. [1B: Relationship Extractor](#1b-relationship-extractor)
3. [1C: Domain Modeler State Machine Attachment](#1c-domain-modeler-state-machine-attachment)
4. [1D: Schemathesis Wiring](#1d-schemathesis-wiring)
5. [1E: Pact Wiring](#1e-pact-wiring)
6. [1F: Builder Config Generation](#1f-builder-config-generation)
7. [1G: Agent-Team-v15 Contract Consumption](#1g-agent-team-v15-contract-consumption)
8. [1H: Graph RAG Context](#1h-graph-rag-context)
9. [1I: Compose Generator](#1i-compose-generator)
10. [1J: Contract Cross-References](#1j-contract-cross-references)

---

## 1A: State Machine Parser

**File:** `C:\MY_PROJECTS\super-team\src\architect\services\prd_parser.py`
**Function:** `_extract_state_machines()` at line 1159
**Called from:** `parse_prd()` at line 299

### Extraction Strategies (8 total)

| # | Strategy | Lines | Regex Pattern | What It Matches |
|---|----------|-------|---------------|-----------------|
| 1 | Status fields with enum values | 1173-1185 | N/A (iterates entity fields, calls `_find_enum_values_near_entity()`) | Entity fields named `status/state/phase/lifecycle/stage/workflow_state` (set `_STATE_FIELD_NAMES` at line 169) |
| 2 | Explicit transition sentences | 1188-1199 | `r"\b([A-Z][A-Za-z]+)\s+transitions?\s+from\s+[\"']?(\w+)[\"']?\s+to\s+[\"']?(\w+)[\"']?"` | "Invoice transitions from draft to submitted" |
| 3 | Arrow notation | 1202-1219 | `r"\b([A-Z][A-Za-z]+)\s*(?:status\|state\|lifecycle\|workflow)\s*[:\-]\s*([\w]+(?:\s*(?:->\|-->\|=>\|,)\s*[\w]+)+)"` | "Invoice status: pending -> confirmed -> shipped" |
| 4 | Heading-separated format | 1228-1248 | `r"^#{2,5}\s+([A-Z][A-Za-z]+(?:\s+[A-Z][a-z]+)*)\s+(?:Status\s+)?State\s+Machine\s*\n((?:(?!^#{1,5}\s).*\n)*)"` | "#### Invoice Status State Machine" heading followed by arrow transitions in body |
| 5 | Unicode arrows | 1251-1271 | `r"\b([A-Z][A-Za-z]+)\b[^\n]*?([\w]+(?:\s*(?:\u2192\|\u2192\|->\|-->\|=>)\s*[\w]+)+)"` | "Invoice draft \u2192 submitted \u2192 approved" |
| 6 | State list | 1274-1292 | `r"\b([A-Z][A-Za-z]+)\s+(?:valid\s+)?states?\s*:\s*([\w]+(?:\s*,\s*[\w]+)+)"` | "Invoice states: draft, submitted, approved, posted" |
| 7 | Transition table | 1295-1329 | `r"^\|[^\n]*(?:from\s+state\|from\|source)[^\n]*\|[^\n]*(?:to\s+state\|to\|target)[^\n]*\|\s*\n\|[-:\s\|]+\|\s*\n((?:\|[^\n]+\n?)+)"` | Markdown tables with From State / To State columns |
| 8 | Prose transitions | 1332-1347 | `r"transitions?\s+from\s+[\"']?(\w+)[\"']?\s+to\s+[\"']?(\w+)[\"']?(?:\s+(?:when\|if\|on\|after)\s+(\w[\w\s]+?))?[.\n]"` | "transitions from draft to submitted when approved" |

### Does It Parse `**Transitions:**` Sections?

**NO.** None of the 8 strategies explicitly look for a `**Transitions:**` markdown section heading. The strategies look for:
- Arrow notation inline with entity name (Strategy 3)
- Explicit "State Machine" heading (Strategy 4)
- Transition tables (Strategy 7)
- Prose "transitions from X to Y" (Strategy 2 and 8)

A PRD section formatted as:

```markdown
**Transitions:**
- draft -> submitted (user submits)
- submitted -> approved (manager approves)
```

Would only be caught by Strategy 5 (Unicode arrows) IF the entity name appears on the same line. But this typical PRD format has the entity name on a PRECEDING heading, not on the arrow line itself. Strategy 8 might catch "transitions from X to Y" prose, but not bare arrow syntax without "transitions" keyword.

### Does It Handle Unicode Box-Drawing Characters?

**PARTIALLY.** Strategy 5 handles Unicode arrows (`\u2192` / `\u2192`), but the parser does NOT handle box-drawing characters like `\u2502 \u250C \u2518 \u2500` etc. These are used in ASCII art state machine diagrams in some PRDs.

### Why Invoice Gets 5/7 States

Looking at the domain_model.json output at `C:\MY_PROJECTS\super-team\.super-orchestrator\domain_model.json`:

**Invoice has `"state_machine": null`** -- it gets ZERO states currently.

The "5/7" figure likely refers to a prior run or target expectation. The reason no states are extracted for Invoice:

1. **No fields extracted**: The domain_model.json shows `"fields": []` for Invoice. Without a `status` field, Strategy 1 never fires.
2. **Strategy 1 needs a status field**: Line 1174: `if fld["name"] in _STATE_FIELD_NAMES` -- since no fields exist, this is skipped.
3. **Strategy 2-8 depend on entity name + transition text**: If the PRD uses a format like `**Transitions:** draft -> submitted -> ...` under an Invoice heading (without the entity name on the same line as the arrows), no strategy can associate the transitions with Invoice.

### Why JournalEntry Gets 2/5 States

Same issue: `"state_machine": null` in the output. The domain_model.json shows `"fields": []` for JournalEntry, so no status field is detected.

### Why FiscalPeriod Gets 2/4 States

Same issue: `"state_machine": null`, `"fields": []`.

### Root Cause Summary

1. **Entity field extraction is failing for the LedgerPro PRD.** All entities have `"fields": []` in the domain_model.json, which means table-based field extraction (Strategy 1 of entity extraction) is not matching the PRD format.
2. **Without fields, Strategy 1 of state machine extraction never fires** (it requires a status/state field).
3. **The `**Transitions:**` section format is not matched by any strategy.** Strategies 2-8 either require the entity name inline with the transition arrows, or require specific heading formats like "#### Invoice State Machine".
4. **`_find_enum_values_near_entity()` (line 1396)** only works when the entity has a status field AND the PRD contains patterns like "Invoice status: draft, submitted, approved" -- which may not match all PRD formats.

### Key Helper Functions

| Function | Line | Purpose |
|----------|------|---------|
| `_find_enum_values_near_entity()` | 1396 | Finds state values near entity name. Uses 3 priority patterns. |
| `_find_or_create_machine()` | 1457 | Finds existing machine for entity or creates new one. |
| `_add_state()` | 1473 | Adds state to machine if not present. |
| `_add_transition()` | 1479 | Adds transition if not duplicate. |
| `_infer_linear_transitions()` | 1493 | Creates sequential transitions from ordered state list. |
| `_find_entity_context_for_state_table()` | 1352 | Finds entity for a transition table by looking at preceding headings. |
| `_find_entity_context_for_prose_transition()` | 1377 | Finds entity from prose context near transition mention. |

---

## 1B: Relationship Extractor

**File:** `C:\MY_PROJECTS\super-team\src\architect\services\prd_parser.py`
**Function:** `_extract_relationships()` at line 893

### Patterns Used

**Phase 1: Keyword-based matching** (lines 907-932)

Uses `_RELATIONSHIP_KEYWORDS` list (line 98-120) with compiled regex:
```python
r"\b([A-Z][A-Za-z]+)\s+" + re.escape(keyword) + r"\s+(?:an?\s+)?([A-Z][A-Za-z]+)"
```

This requires BOTH entity names to start with a capital letter (`[A-Z][A-Za-z]+`).

**Keyword -> RelationshipType mappings (critical issue):**

| Keyword | Mapped Type | Notes |
|---------|-------------|-------|
| `"belongs to"` | `OWNS` (N:1) | **BUG: Should be BELONGS_TO** |
| `"has many"` | `OWNS` (1:N) | **BUG: Should be HAS_MANY** |
| `"contains"` | `OWNS` (1:N) | Maps to OWNS |
| `"has multiple"` | `HAS_MANY` (1:N) | Correct |
| `"is owned by"` | `BELONGS_TO` (N:1) | Correct |
| `"is part of"` | `BELONGS_TO` (N:1) | Correct |
| `"references"` | `REFERENCES` (N:1) | Correct |
| `"triggers"` | `TRIGGERS` (1:N) | Correct |
| `"extends"` | `EXTENDS` (1:1) | Correct |
| `"depends on"` | `DEPENDS_ON` (N:1) | Correct |

The comment on lines 93-97 says: `"belongs to", "has many", "contains" remain mapped to OWNS for backward compatibility with existing tests`.

**Phase 2: Arrow patterns** (lines 935-952)
```python
r"\b([A-Z][A-Za-z]+)\s*(?:<->|<-->|-->|->)\s*([A-Z][A-Za-z]+)\b"
```
All arrow relationships default to `REFERENCES`.

**Phase 3: Prose relationship patterns** (lines 957-973)

Uses `_PROSE_RELATIONSHIP_PATTERNS` (lines 125-151):
- `r"\b(\w+)\s+(?:has\s+many|has\s+multiple|contains)\s+(\w+)"` -> `OWNS` (1:N) **BUG: Should be HAS_MANY for "has many"**
- `r"\b(\w+)\s+(?:belongs?\s+to|is\s+(?:owned|part)\s+of)\s+(\w+)"` -> `OWNS` (N:1) **BUG: Should be BELONGS_TO**
- `r"\b(\w+)\s+(?:references?|refers?\s+to|links?\s+to)\s+(\w+)"` -> `REFERENCES` (N:1)
- `r"\b(\w+)\s*(?:\u2192|->|=>|triggers?)\s*(\w+)"` -> `TRIGGERS` (1:N)
- `r"\b(\w+)\s+(?:depends?\s+on|requires?)\s+(\w+)"` -> `DEPENDS_ON` (N:1)

### Does It Match "HAS MANY" (uppercase, two words)?

**YES, but maps it to OWNS instead of HAS_MANY.** The keyword `"has many"` at line 103 maps to `RelationshipType.OWNS`, not `RelationshipType.HAS_MANY`. The prose pattern at line 127 (`has\s+many`) also maps to `RelationshipType.OWNS`.

Only `"has multiple"` (line 104) correctly maps to `RelationshipType.HAS_MANY`.

### Why Everything Comes Back as OWNS or REFERENCES

1. **"has many"** (the most common relationship keyword in PRDs) maps to `OWNS` instead of `HAS_MANY`
2. **"belongs to"** maps to `OWNS` instead of `BELONGS_TO`
3. **"contains"** maps to `OWNS`
4. Arrow patterns default to `REFERENCES`
5. Only `"has multiple"`, `"is owned by"`, and `"is part of"` use the correct non-OWNS types

The domain_model.json confirms: all 15 relationships are either `OWNS` (12) or `REFERENCES` (3). Zero `HAS_MANY`, zero `BELONGS_TO`, zero `TRIGGERS`, zero `DEPENDS_ON`.

### domain_modeler.py Relationship Mapping (Line 33-61)

The domain_modeler has its OWN `_RELATIONSHIP_TYPE_MAP` which DOES include `"has many": RelationshipType.HAS_MANY`. However, this mapping only applies when processing already-extracted relationships from the parser. Since the parser emits `type: "OWNS"` for "has many" relationships, the domain_modeler's correct mapping never gets a chance to fire.

The chain is: **parser extracts "has many" -> emits `"OWNS"` -> domain_modeler receives `"OWNS"` -> maps to `OWNS`**.

---

## 1C: Domain Modeler State Machine Attachment

**File:** `C:\MY_PROJECTS\super-team\src\architect\services\domain_modeler.py`
**Function:** `_detect_state_machine()` at line 181
**Called from:** `_build_entity()` at line 168

### Attachment Condition

```python
def _detect_state_machine(entity_name, fields, parsed):
    # Priority 1: Check parsed.state_machines for this entity
    parsed_sm = _find_parsed_state_machine(entity_name, parsed)
    if parsed_sm is not None:
        return _state_machine_from_parsed(parsed_sm)

    # Priority 2: Check for status/state/phase field
    for field in fields:
        if field.name.lower() in _STATE_FIELD_NAMES:
            return _default_state_machine()  # active -> inactive

    # No state machine
    return None
```

### Does the Wave 2 Fix Work?

**YES, partially.** The comment at line 199 says: "This takes priority and works EVEN WITHOUT a status field in entity.fields". The logic at Priority 1 (lines 200-202) checks `parsed.state_machines` for the entity name, and if found, creates a `StateMachine` from the parsed data regardless of whether the entity has a status field.

**BUT the upstream parser is the bottleneck.** If `parsed.state_machines` is empty (because the parser failed to extract state machines), then this Priority 1 path never fires. And if `fields` is empty (which it IS for the LedgerPro run -- all entities have `fields: []`), then Priority 2 also never fires.

### State Machine Construction

When `parsed_sm` is found (line 235-266):
- `states` from `sm_data.get("states", ["active", "inactive"])`
- `initial_state` from `sm_data.get("initial_state", states[0])`
- `transitions` from `sm_data.get("transitions", [])` -- each with `from_state`, `to_state`, `trigger`, optional `guard`
- If states exist but no transitions, infers sequential transitions via `_infer_sequential_transitions()`

When only a status field is found (line 269-276):
- Returns minimal default: `["active", "inactive"]` with one transition `active -> inactive`

### Key Constants

`_STATE_FIELD_NAMES` (line 26-28): `{"status", "state", "phase", "lifecycle", "workflow_state"}`

---

## 1D: Schemathesis Wiring

**Files searched:**
- `C:\MY_PROJECTS\super-team\src\super_orchestrator\pipeline.py`
- `C:\MY_PROJECTS\super-team\src\integrator\schemathesis_runner.py`
- `C:\MY_PROJECTS\super-team\src\integrator\contract_compliance.py`
- `C:\MY_PROJECTS\super-team\src\contract_engine\mcp_server.py`
- `C:\MY_PROJECTS\super-team\src\contract_engine\services\test_generator.py`

### Schemathesis Infrastructure Exists

**YES.** Full implementation at:

| Component | File | Class/Function |
|-----------|------|----------------|
| Runner | `src/integrator/schemathesis_runner.py` | `SchemathesisRunner` |
| Positive tests | Line 88 | `run_against_service()` |
| Negative tests | Line 111 | `run_negative_tests()` |
| Test file gen | Line 132 | `generate_test_file()` |
| Facade | `src/integrator/contract_compliance.py` | `ContractComplianceVerifier` |

### Is Schemathesis Wired into the Pipeline?

**INDIRECTLY through the integration phase.** The pipeline calls:

1. `run_integration_phase()` at line 1215 of pipeline.py
2. Which creates `ContractComplianceVerifier` at line 1365
3. Which internally creates `SchemathesisRunner` at line 47 of contract_compliance.py
4. Then calls `verifier.verify_all_services()` at line 1374

**BUT** this only runs during the INTEGRATION phase (Docker-based). If Docker is not available (`state.docker_available` is False), the entire integration phase is SKIPPED (line 1230-1266), and schemathesis never runs.

### Contract Engine `generate_tests` Tool

The Contract Engine MCP server exposes a `generate_tests` tool (line 298-326 of contract_engine/mcp_server.py) that generates Schemathesis test files. **However, no pipeline phase calls this tool.** The pipeline's contract registration phase (`run_contract_registration()` at line 534) only calls `create_contract` and `list_contracts` -- never `generate_tests`.

The `register_contracts_batch` tool (line 468) DOES call `_test_generator.generate_tests()` internally (line 619), but this batch tool is also never called by the pipeline.

### Insertion Point

To wire `generate_tests` into the pipeline, the call should be added to `run_contract_registration()` (around line 614-616 of pipeline.py) after each contract is successfully registered. Alternatively, the pipeline could call `register_contracts_batch` instead of registering contracts one-by-one.

---

## 1E: Pact Wiring

**Files searched:**
- `C:\MY_PROJECTS\super-team\src\integrator\pact_manager.py`
- `C:\MY_PROJECTS\super-team\src\integrator\contract_compliance.py`
- `C:\MY_PROJECTS\super-team\src\super_orchestrator\pipeline.py`

### Pact Infrastructure Exists

**YES.** Full implementation at `C:\MY_PROJECTS\super-team\src\integrator\pact_manager.py`:

| Component | Line | Method |
|-----------|------|--------|
| Class | 22 | `PactManager` |
| Pact loading | 53 | `load_pacts()` -- groups JSON files by provider name |
| Provider verification | 100 | `verify_provider()` -- uses `pact.v3.verifier.Verifier` |
| State handler gen | 212 | `generate_pact_state_handler()` -- generates FastAPI endpoint code |
| Error parsing | 272 | `_parse_verification_error()` |

### Is Pact Wired into the Pipeline?

**PARTIALLY.** The `ContractComplianceVerifier` facade (contract_compliance.py) creates a `PactManager` at line 49:

```python
pact_dir = self._contract_registry_path / "pacts"
self._pact = PactManager(pact_dir=pact_dir)
```

**BUT** examining the `verify_all_services()` method would be needed to confirm if it actually calls `load_pacts()` and `verify_provider()`. The pipeline creates the verifier and calls `verify_all_services()` at line 1374 of pipeline.py.

### Key Issue: Pact File Generation

Even if the Pact verification code is wired, **no pipeline phase generates pact files**. The `pact_dir` would be `{contract_registry}/pacts/` which is created only if something writes pact JSON files there. Neither the architect phase nor the contract registration phase generates pact files. Without pact files, `PactManager.load_pacts()` returns an empty dict and no verification occurs.

### Insertion Point

Pact file generation should be added to the contract registration phase or the architect's `generate_contract_stubs()` function, producing consumer-driven contract files in the `{registry_dir}/pacts/` directory.

---

## 1F: Builder Config Generation

**File:** `C:\MY_PROJECTS\super-team\src\super_orchestrator\pipeline.py`
**Function:** `generate_builder_config()` at line 215

### Generated Config Fields

```python
config_dict = {
    "depth": config.builder.depth,                    # str, e.g. "thorough"
    "milestone": f"build-{service_info.service_id}",  # str
    "e2e_testing": True,                              # bool
    "post_orchestration_scans": True,                 # bool
    "service_id": service_info.service_id,            # str
    "domain": service_info.domain,                    # str
    "stack": service_info.stack,                      # dict (from ServiceInfo)
    "port": service_info.port,                        # int
    "output_dir": str(output_dir),                    # str (path)
    "graph_rag_context": state.phase_artifacts.get(   # str (may be empty)
        "graph_rag_contexts", {}
    ).get(service_info.service_id, ""),
    "failure_context": failure_context,               # str (from persistence)
    "acceptance_test_requirements": acceptance_test_requirements,  # str (from ACCEPTANCE_TESTS.md)
}
```

### Field-by-Field Analysis

| Field | Present? | Notes |
|-------|----------|-------|
| `tech_stack` | **NO (as "tech_stack")** | Present as `stack` (line 292) -- a dict like `{"language": "Python", "framework": "FastAPI", ...}` |
| `service_type` | **NO** | Not included. No `is_frontend` flag is passed to builder. |
| `entities` | **NO** | Not included. Builder does not know which entities it owns. |
| `state_machines` | **NO** | Not included. Builder does not know about state machines. |
| `contracts` | **NO** | Not included. No contract spec or path is passed. |
| `graph_rag_context` | **YES** | Line 295 -- context text from Graph RAG (may be empty string). |
| `failure_context` | **YES** | Line 298 -- from persistence layer (empty when disabled). |
| `acceptance_test_requirements` | **YES** | Line 299 -- from ACCEPTANCE_TESTS.md file if it exists. |

### Frontend Services Get Different Configs?

**NO.** The `generate_builder_config()` function produces identical config structure for all services. The `is_frontend` field from `ServiceDefinition` is NOT propagated to the builder config. There is no frontend-specific handling (no React/Next.js config, no port 3000 default, etc.).

### Missing Critical Information for Builders

1. **No entity list**: Builder does not know which entities it should implement CRUD for.
2. **No state machine data**: Builder cannot generate state transition endpoints.
3. **No contract specs**: Builder cannot implement against the contracted API surface.
4. **No `is_frontend` flag**: Builder cannot decide between backend (FastAPI/Express) vs frontend (React/Vue) scaffolding.
5. **No `provides_contracts` / `consumes_contracts`**: Builder has no knowledge of cross-service dependencies.

---

## 1G: Agent-Team-v15 Contract Consumption

**File:** `C:\MY_PROJECTS\super-team\src\super_orchestrator\pipeline.py`
**Function:** `_run_single_builder()` at line 802

### How Builders Are Invoked

The pipeline tries two execution approaches (line 825-847):

1. **In-process** via `agent_team_v15.execution.create_execution_backend` or `agent_team.execution.create_execution_backend`
2. **Subprocess fallback** (not shown in the read portion but exists further in the file)

The builder receives:
- `builder_dir=output_dir` -- the per-service output directory
- `config=builder_config` -- the config dict from `generate_builder_config()`

### What Format Do Builders Expect?

The builder config is written to `builder_config.json` at line 814:
```python
config_file = output_dir / "builder_config.json"
atomic_write_json(config_file, builder_config)
```

The builder also gets `prd_input.md` (line 817-821) -- the full original PRD text copied into the service directory.

### Does It Read Contract Files?

**NO.** The builder config does NOT contain a path to contract files. The contract registry is at `state.contract_registry_path` but this path is never passed to the builder. The `graph_rag_context` field (line 295) may contain some contract-related context if Graph RAG indexed the contracts, but this is an indirect and unreliable path.

The per-service output directory may contain individual contract JSON files if the contract registration phase saved them there, but the builder has no explicit instruction to look for them.

### Key Gap

Builders operate in isolation from contracts. They receive:
- The full PRD (too broad -- not service-specific)
- A minimal config (no entities, no state machines, no contracts)
- Optionally, Graph RAG context (if Graph RAG is enabled and succeeded)

They do NOT receive:
- Service-specific contract specs (OpenAPI/AsyncAPI)
- Entity field definitions
- State machine definitions
- Cross-service dependency information

---

## 1H: Graph RAG Context

**Files:**
- `C:\MY_PROJECTS\super-team\src\super_orchestrator\pipeline.py` (lines 2515-2619)
- `C:\MY_PROJECTS\super-team\src\graph_rag\graph_rag_engine.py`
- `C:\MY_PROJECTS\super-team\src\graph_rag\context_assembler.py`
- `C:\MY_PROJECTS\super-team\src\graph_rag\mcp_client.py`

### Pipeline Call Chain

1. `_phase_contracts_registered()` at line 2467 of pipeline.py
2. Calls `_build_graph_rag_context()` at line 2482 (non-blocking, best-effort)
3. Which connects to Graph RAG MCP server via stdio
4. Calls `client.build_knowledge_graph()` at line 2583
5. Then calls `client.get_service_context()` for each service at line 2601
6. Stores results in `state.phase_artifacts["graph_rag_contexts"]` -- a `dict[str, str]`

### What Context Is Produced Per Service

The `GraphRAGEngine.get_service_context()` method (line 62 of graph_rag_engine.py) produces:

| Section | Priority | Content |
|---------|----------|---------|
| Header | 0 | `## Graph RAG Context: {service_name}` |
| Service Dependencies | 1 | Depends-on and depended-on-by lists |
| Consumed APIs | 2 | Method, Path, Provider Service table |
| Referenced Entities | 3 | Entity name, owning service, field list |
| Provided APIs | 4 | Method, Path, Handler table |
| Events Published | 5 | Event Name, Channel table |
| Events Consumed | 5 | Event Name, Publisher table |
| Owned Entities | 6 | Entity name with field list |
| Integration Notes | 7 | Auto-generated cross-service integration tips |

The `ContextAssembler.truncate_to_budget()` (line 215 of context_assembler.py) truncates lower-priority sections to fit within the token budget (default 2000 tokens, configured via `GraphRAGConfig.context_token_budget`).

### Fallback Case

When Graph RAG fails (any exception), the pipeline catches all exceptions (lines 2489-2619) and logs a warning. The `graph_rag_contexts` dict remains empty. In the builder config, `graph_rag_context` will be an empty string (`""` at line 297 of pipeline.py).

**The fallback provides NO context at all.** There is no secondary mechanism to provide service context when Graph RAG is unavailable.

### How Context Is Injected into Builder Configs

At line 295-297 of pipeline.py:
```python
"graph_rag_context": state.phase_artifacts.get(
    "graph_rag_contexts", {}
).get(service_info.service_id, ""),
```

This retrieves the pre-formatted markdown context string for the specific service and includes it as a string field in the builder config dict. The builder is expected to inject this context into its prompt.

### Key Issue

The `service_info.service_id` used in the lookup may not match the `service_name` used in Graph RAG. The service_map uses `service_id` (kebab-case, e.g., `"owning-service"`) but Graph RAG may use the `name` field. This mismatch could cause context to be lost silently.

---

## 1I: Compose Generator

**File:** `C:\MY_PROJECTS\super-team\src\integrator\compose_generator.py`
**Class:** `ComposeGenerator`

### How Services Map to Containers

The `generate()` method (line 52) and `generate_compose_files()` method (line 321) create Docker Compose entries:

1. **Infrastructure services** (always included unless flags set to False):
   - `postgres` -- PostgreSQL 16-alpine, backend network, 512MB RAM
   - `redis` -- Redis 7-alpine, backend network, 256MB RAM
   - `traefik` -- Traefik v3.6, frontend network, 256MB RAM

2. **Application services** (one per `ServiceInfo`):
   - Built from `./{service_id}/Dockerfile`
   - Both frontend and backend networks
   - Depends on postgres (healthy) and redis (healthy)
   - Traefik labels for routing
   - 768MB RAM limit per service
   - Health check via curl to `{health_endpoint}`

### Mixed Tech Stack Handling

**NOT HANDLED.** The `_app_service()` method (line 240) produces a generic service definition:
- Always uses `build: {context: "./{service_id}", dockerfile: "Dockerfile"}`
- No distinction between Python/Node/Go services
- No language-specific health check commands
- The `generate_default_dockerfile()` (line 286) always generates a Python Dockerfile (`FROM python:3.12-slim-bookworm`, `uvicorn main:app`)

Frontend services (React/Vue/Angular) would get the same Python Dockerfile template, which is incorrect.

### Infrastructure Included

| Service | Image | Network | RAM | Health Check |
|---------|-------|---------|-----|-------------|
| PostgreSQL | `postgres:16-alpine` | backend | 512MB | `pg_isready -U app` |
| Redis | `redis:7-alpine` | backend | 256MB | `redis-cli ping` |
| Traefik | `traefik:v3.6` | frontend | 256MB | `traefik healthcheck --ping` |

### 5-File Compose Merge Strategy (TECH-004)

The `generate_compose_files()` method (line 321) produces 5 files:

1. `docker-compose.infra.yml` -- postgres, redis, networks, volumes
2. `docker-compose.build1.yml` -- empty (placeholder for Build 1 services)
3. `docker-compose.traefik.yml` -- Traefik reverse proxy
4. `docker-compose.generated.yml` -- generated app services
5. `docker-compose.run4.yml` -- empty (placeholder for Run 4 overrides)

### Network Segmentation

- **frontend network**: Traefik + app services
- **backend network**: PostgreSQL + Redis + app services
- App services are on BOTH networks (line 258)
- Traefik is on frontend ONLY (line 169)
- PostgreSQL/Redis are on backend ONLY (line 200/226)

### Total RAM Budget: 4.5GB (TECH-006)

- Traefik: 256MB
- PostgreSQL: 512MB
- Redis: 256MB
- Per-service: 768MB each
- With 3 services: 256 + 512 + 256 + (3 * 768) = 3,328MB

---

## 1J: Contract Cross-References

**Files:**
- `C:\MY_PROJECTS\super-team\src\contract_engine\mcp_server.py`
- `C:\MY_PROJECTS\super-team\src\super_orchestrator\pipeline.py`
- `C:\MY_PROJECTS\super-team\src\architect\services\service_boundary.py`
- `C:\MY_PROJECTS\super-team\src\architect\services\contract_generator.py`
- `C:\MY_PROJECTS\super-team\src\shared\models\architect.py`

### Contract Registration Code

The pipeline registers contracts in `run_contract_registration()` (line 534 of pipeline.py):
1. Reads `service_map.json`
2. Loads `stubs.json` from the contract registry
3. For each service, finds its contract stub and calls `_register_single_contract()`
4. `_register_single_contract()` calls `create_contract()` via MCP (or filesystem fallback)

The Contract Engine's `create_contract` tool (line 64 of mcp_server.py) stores contracts in SQLite via `ContractStore.upsert()`. Each contract has: `service_name`, `type`, `version`, `spec`.

### Do Contracts Reference Other Services' Entities?

**PARTIALLY.** The `generate_contract_stubs()` function (line 273 of contract_generator.py) generates OpenAPI specs with schemas for owned entities. It DOES generate `$ref` references to entity schemas within the same spec (e.g., `"$ref": "#/components/schemas/Invoice"`), but it does NOT generate cross-service schema references (e.g., referencing a User schema from an Invoice service's spec).

### Is `consumes_contracts` Populated?

**YES, in the service_boundary module.** The `_compute_contracts()` function (line 504 of service_boundary.py) populates `consumes_contracts`:

```python
# A boundary consumes when it has a cross-boundary non-OWNS relationship
for rel in relationships:
    if rel_type == "OWNS": continue  # intra-boundary
    source_boundary = entity_to_boundary.get(source)
    target_boundary = entity_to_boundary.get(target)
    if source_boundary != target_boundary:
        target_contract = f"{kebab_name}-api"
        source_boundary.consumes_contracts.append(target_contract)
```

**BUT** the domain_model.json shows all relationships are `OWNS` (12) or `REFERENCES` (3). Since `OWNS` is skipped, only the 3 `REFERENCES` relationships could trigger cross-service contract consumption. And looking at the service_map.json, ALL services have `"consumes_contracts": []`.

This means the `_compute_contracts()` function's cross-boundary check is not finding cross-boundary REFERENCES relationships, likely because all entities are assigned to the same "owning-service" boundary (the service_map shows most entities under "owning-service").

### Is a Cross-Service Dependency Map Generated?

**NO.** There is no explicit cross-service dependency map artifact. The closest thing is:
1. `consumes_contracts` on each service definition (currently empty)
2. Graph RAG's `depends_on` / `depended_on_by` (if Graph RAG runs)
3. The `ServiceMap` itself contains `provides_contracts` and `consumes_contracts` per service

There is no standalone dependency map file generated as a pipeline artifact.

### Key Gap

The contract system has the infrastructure for cross-references (`provides_contracts`, `consumes_contracts`), but the actual population is broken because:
1. The parser maps "has many" to OWNS instead of HAS_MANY
2. Only non-OWNS relationships trigger cross-boundary contract consumption
3. Entity boundary assignment puts too many entities in a single "owning-service"
4. No cross-service schema references are generated in OpenAPI specs

---

## Additional Findings

### Bogus Entity Filter Failure

**File:** `C:\MY_PROJECTS\super-team\src\architect\services\prd_parser.py`
**Function:** `_entity_confidence()` at line 2426
**Function:** `_filter_entities()` at line 2481

The domain_model.json shows 27 entities including many bogus ones:
- `EntityRelationships`, `EventsPublished`, `EventChains`, `UserRolesAndPermissions` -- section headings
- `DataIntegrity`, `Docker`, `SeedData`, `SuccessCriteria` -- non-domain terms
- `Domain`, `With`, `Concurrent`, `All` -- generic words
- `Pages`, `Observability`, `Reliability` -- non-entity concepts

These names ARE in `_ENTITY_STOP_LIST` (line 2398-2423), but the filter fails because:

1. `EntityRelationships` has description `"- User HAS MANY JournalEntries (created_by)"` which is not empty and doesn't start with `|`
2. `has_real_description = True` on line 2452
3. `has_evidence = True` on line 2453
4. On line 2463: even though `name_lower in _ENTITY_STOP_LIST`, the condition `len(fields) <= 1 and not has_real_description` is FALSE (it has real description), so it passes
5. Returns `"MEDIUM"` instead of `"REJECT"`

**Root cause:** The filter gives too much weight to descriptions that are actually just section content bleed-through from the PRD extraction. A description like `"- User HAS MANY JournalEntries (created_by)"` is not evidence that `EntityRelationships` is a domain entity -- it's the content of that section heading.

### Service Boundary Quality

The service_map.json shows only 3 services:
1. `owning-service` -- owns 11 entities (User, Tenant, Role, Account, Notification, All, Invoice, InvoiceLine, JournalEntry, JournalLine, Payment)
2. `fiscal-period` -- owns 1 entity (FiscalPeriod)
3. `miscellaneous` -- owns 14 entities (all bogus: AuditEntry, Concurrent, DataIntegrity, Docker, etc.)

The "owning-service" boundary incorrectly groups entities from different domains (auth, accounts, invoicing, notifications) into a single service.

### Test Coverage for Parser Issues

Relevant test files:
- `C:\MY_PROJECTS\super-team\tests\test_wave2\test_prd_parser_new.py` -- Tests explicit services, events, endpoints, entity filtering, state machines, relationships
- `C:\MY_PROJECTS\super-team\tests\test_architect\test_prd_parser.py` -- Original parser tests
- `C:\MY_PROJECTS\super-team\tests\test_wave2\test_contract_generator_new.py` -- Tests contract generation

The test at line 258 of test_prd_parser_new.py tests arrow notation:
```python
"Invoice status: draft -> submitted -> approved -> paid\n"
```
This is Strategy 3 format. But it does NOT test the `**Transitions:**` format or Unicode box-drawing.

---

## Summary of Critical Gaps

| Gap ID | Severity | Component | Issue |
|--------|----------|-----------|-------|
| 1A-1 | HIGH | prd_parser | `**Transitions:**` section format not parsed |
| 1A-2 | HIGH | prd_parser | Entity fields not extracted (all `fields: []`) for LedgerPro format |
| 1A-3 | MEDIUM | prd_parser | Unicode box-drawing not handled |
| 1B-1 | HIGH | prd_parser | "has many" maps to OWNS instead of HAS_MANY |
| 1B-2 | HIGH | prd_parser | "belongs to" maps to OWNS instead of BELONGS_TO |
| 1B-3 | MEDIUM | prd_parser | Prose patterns also map to wrong types |
| 1C-1 | LOW | domain_modeler | Fix works correctly but depends on parser output |
| 1D-1 | MEDIUM | pipeline | `generate_tests` tool never called by pipeline |
| 1D-2 | LOW | pipeline | Schemathesis only runs when Docker available |
| 1E-1 | HIGH | pipeline | No pact file generation anywhere in pipeline |
| 1F-1 | HIGH | pipeline | Builder config missing entities, state_machines, contracts |
| 1F-2 | MEDIUM | pipeline | No `is_frontend` flag in builder config |
| 1F-3 | MEDIUM | pipeline | No `provides_contracts`/`consumes_contracts` in config |
| 1G-1 | HIGH | pipeline | Builder has no contract specs to implement against |
| 1H-1 | MEDIUM | pipeline | No fallback when Graph RAG unavailable |
| 1H-2 | LOW | pipeline | Service ID/name mismatch possible in context lookup |
| 1I-1 | MEDIUM | compose | No mixed tech stack support (all Python Dockerfiles) |
| 1I-2 | LOW | compose | Frontend services get wrong Dockerfile template |
| 1J-1 | HIGH | contracts | `consumes_contracts` always empty due to relationship type bug |
| 1J-2 | MEDIUM | contracts | No cross-service schema references in OpenAPI specs |
| 1J-3 | MEDIUM | contracts | No dependency map artifact generated |
| FILTER-1 | HIGH | prd_parser | Entity filter passes bogus entities with section content as "evidence" |
| BOUNDARY-1 | HIGH | service_boundary | All real entities lumped into single "owning-service" |

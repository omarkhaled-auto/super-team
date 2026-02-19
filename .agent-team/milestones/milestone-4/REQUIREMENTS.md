## Milestone 4: End-to-End Pipeline Test
- ID: milestone-4
- Status: PENDING
- Dependencies: milestone-2, milestone-3
- Description: Feed the 3-service sample PRD through the COMPLETE pipeline — Architect decomposition, Contract registration, 3 parallel Builders, Docker deployment, Integration tests, Quality Gate. All with real subprocesses; Docker via Testcontainers.

---

### Overview

Milestone 4 is the most complex and highest-risk milestone. It orchestrates the full 7-phase pipeline, requiring Docker Compose management, real MCP server interaction, subprocess builder invocation, and multi-service deployment verification. This is the milestone that exercises every integration point in the system.

### Estimated Effort
- **LOC**: ~1,200
- **Files**: 3 test files + Docker compose files
- **Risk**: CRITICAL (Docker, networking, multi-service orchestration)
- **Duration**: 2-3 hours

---

### 7-Phase Pipeline

```
Phase 1: Build 1 Health        -> All 3 services HTTP 200
Phase 2: MCP Smoke              -> Key MCP tools callable
Phase 3: Architect Decomposition -> ServiceMap + DomainModel
Phase 4: Contract Registration   -> All contracts stored + valid
Phase 5: Parallel Builders       -> 3 services built
Phase 6: Deployment + Integration -> Docker up + tests pass
Phase 7: Quality Gate            -> 4-layer verdict
```

---

### Phase Requirements

#### Phase 1: Build 1 Health (REQ-021)

**Action**: Start all Build 1 services via Docker Compose
**Services**:
- Architect API on `:8001` (internal `:8000`)
- Contract Engine on `:8002` (internal `:8000`)
- Codebase Intelligence on `:8003` (internal `:8000`)

**Verification**:
- All respond HTTP 200 on `/api/health`
- Use `poll_until_healthy()` from M1

**Gate**: ALL 3 must be healthy before proceeding

#### Phase 2: MCP Smoke (REQ-022)

**Action**: Verify key MCP tools are callable
**Tests**:
- Architect MCP `decompose` tool callable with sample PRD
- Contract Engine MCP `validate_spec` and `get_contract` tools callable
- Codebase Intelligence MCP `find_definition` and `register_artifact` tools callable

**Gate**: ALL smoke tests pass

#### Phase 3: Architect Decomposition (REQ-023)

**Action**: Feed sample TaskTracker PRD to Architect via MCP `decompose`
**Expected**:
- `ServiceMap` with 3 services: auth-service, order-service, notification-service
- `DomainModel` with entities: User, Order, Notification
- `ContractStubs` with inter-service contracts

**Gate**: Valid ServiceMap with >= 3 services AND DomainModel with >= 3 entities

#### Phase 4: Contract Registration (REQ-024)

**Action**: Register contract stubs with Contract Engine via `create_contract()` MCP calls
**Steps**:
1. Call `create_contract()` for each contract stub
2. Call `validate_spec()` for each — expect `valid: true`
3. Call `list_contracts()` — expect all 3+ contracts present

**Gate**: ALL contracts registered AND valid

#### Phase 5: Parallel Builders (REQ-025)

**Action**: Launch 3 Builder subprocesses (one per ServiceMap service)
**Configuration**:
- Each runs full agent-team pipeline with contract-aware config
- Uses `generate_builder_config()` from M3
- `max_concurrent_builders: 3` via Semaphore

**Expected**:
- Each builder writes `STATE.JSON` with summary dict
- `BuilderResult` collected per service

**Gate**: >= 2 of 3 builders succeed (partial success acceptable)

#### Phase 6: Deployment + Integration (REQ-026)

**Action**: Deploy built services and run integration tests
**Sub-steps**:

1. **Compose Generation**: `ComposeGenerator` produces `docker-compose.generated.yml` from builder outputs
2. **Docker Up**: `DockerOrchestrator` runs `docker compose up -d` with merged compose files
3. **Health Check**: `ServiceDiscovery.wait_all_healthy()` polls all services
4. **OpenAPI Precondition**: Each service responds to `GET /openapi.json` with HTTP 200
5. **Schemathesis Contract Testing**: Property-based testing against each service's OpenAPI spec
   - Stateful mode enabled
   - Authenticate with JWT from auth-service login
   - Target: `http://localhost:{port}/openapi.json`
6. **Cross-Service Integration Tests**:
   - Step 1: `POST /register` -> 201, body has `{id, email, created_at}`
   - Step 2: `POST /login` -> 200, body has `{access_token, refresh_token}`
   - Step 3: `POST /orders` with JWT -> 201, body has `{id, status, items, total}`
   - Step 4: `GET /notifications` -> 200, body is list with `len >= 1`

**Gate**: All services healthy AND > 70% contract compliance

#### Phase 7: Quality Gate (REQ-027)

**Action**: Run 4-layer quality verification

**Layer 1: Builder Results** — evaluate `BuilderResult` per service (test pass rate, convergence)

**Layer 2: Integration Results** — evaluate contract test results from Schemathesis/Pact

**Layer 3: Code Quality Checks**:
| Check ID | Rule | Detection |
|----------|------|-----------|
| SEC-SCAN-001 | No hardcoded secrets | Regex: `password\|secret\|api_key\s*=\s*["'][^"']+["']` |
| CORS-001 | CORS origins not `"*"` in production | Config file scan |
| LOG-001 | No `print()` statements | AST/grep scan, use `logging` |
| LOG-002 | All endpoints have request logging middleware | Route inspection |
| DOCKER-001 | All services have `HEALTHCHECK` instruction | Dockerfile scan |
| DOCKER-002 | No `:latest` tags in `FROM` | Dockerfile scan |

**Layer 4: Static Analysis Checks**:
| Check ID | Rule | Detection |
|----------|------|-----------|
| DEAD-001 | Events published but never consumed | Cross-reference publish/subscribe |
| DEAD-002 | Contracts registered but never validated | Contract Engine query |
| ORPHAN-001 | Service in compose but no Traefik route | Compose + label scan |
| NAME-001 | Service names consistent across compose/code/contracts | String matching |

**Gate**: `overall_verdict != "failed"`

---

### Planted Violation Detection (REQ-028)

Deliberate violations included in test setup:
1. **HEALTH-001**: One service missing `/health` endpoint
2. **SCHEMA-001**: One endpoint returning field not in OpenAPI contract
3. **LOG-001**: One `print()` instead of `logger`

**Verification**: All 3 must appear in Quality Gate report

---

### Docker Compose Architecture

#### 5-File Merge (TECH-004)

| File | Tier | Contents |
|------|------|----------|
| `docker-compose.infra.yml` | 0 | postgres (16-alpine), redis (7-alpine) |
| `docker-compose.build1.yml` | 1 | architect, contract-engine, codebase-intelligence |
| `docker-compose.traefik.yml` | 2 | traefik (v3.6) |
| `docker-compose.generated.yml` | 3 | auth-service, order-service, notification-service |
| `docker-compose.run4.yml` | 4 | Cross-build wiring overrides |

#### Network Architecture (WIRE-017)

**Frontend network**:
- traefik, architect, contract-engine, codebase-intelligence, auth-service, order-service, notification-service

**Backend network**:
- postgres, redis, architect, contract-engine, codebase-intelligence, auth-service, order-service, notification-service

**Constraints**:
- Traefik is NOT on backend network
- postgres and redis are NOT on frontend network

#### Health Check Cascade (WIRE-020)

```
Tier 0: postgres, redis (service_healthy)
    |
Tier 1: contract-engine (depends_on: postgres)
    |
Tier 2: architect, codebase-intelligence (depends_on: contract-engine)
    |
Tier 3: generated services (depends_on: architect, contract-engine)
    |
Tier 4: traefik (depends_on: all services)
```

#### Port Assignments

| Service | Internal | External | Protocol |
|---------|----------|----------|----------|
| architect | 8000 | 8001 | HTTP |
| contract-engine | 8000 | 8002 | HTTP |
| codebase-intelligence | 8000 | 8003 | HTTP |
| postgres | 5432 | 5432 | TCP |
| redis | 6379 | 6379 | TCP |
| traefik (HTTP) | 80 | 80 | HTTP |
| traefik (API) | 8080 | 8080 | HTTP |
| auth-service | 8080 | dynamic | HTTP |
| order-service | 8080 | dynamic | HTTP |
| notification-service | 8080 | dynamic | HTTP |

#### Resource Budget (TECH-006)

| Component | RAM Limit |
|-----------|-----------|
| 3 Build 1 services | 2GB total |
| postgres + redis | 640MB total |
| traefik | 128MB |
| 3 generated services | 1.5GB total |
| **Total** | **~4.3GB** (under 4.5GB cap) |

---

### Docker Compose Run4 Overlay File

`docker/docker-compose.run4.yml` — NEW file to create:

```yaml
# Tier 4: Cross-build wiring overrides for Run 4

services:
  architect:
    networks:
      - frontend
      - backend
    labels:
      - "traefik.enable=true"
      - "traefik.http.routers.architect.rule=PathPrefix(`/api/architect`)"
      - "traefik.http.services.architect.loadbalancer.server.port=8000"

  contract-engine:
    networks:
      - frontend
      - backend
    labels:
      - "traefik.enable=true"
      - "traefik.http.routers.contract-engine.rule=PathPrefix(`/api/contracts`)"
      - "traefik.http.services.contract-engine.loadbalancer.server.port=8000"

  codebase-intelligence:
    networks:
      - frontend
      - backend
    labels:
      - "traefik.enable=true"
      - "traefik.http.routers.codebase-intel.rule=PathPrefix(`/api/codebase`)"
      - "traefik.http.services.codebase-intel.loadbalancer.server.port=8000"

  traefik:
    command:
      - "--api.dashboard=false"
      - "--providers.docker=true"
      - "--providers.docker.exposedbydefault=false"
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock:ro

networks:
  frontend:
    driver: bridge
  backend:
    driver: bridge
```

---

### Security Requirements

| ID | Requirement | Verification |
|----|-------------|-------------|
| SEC-001 | No ANTHROPIC_API_KEY passed explicitly to builder subprocesses | Check builder env dict, verify key NOT in explicit args |
| SEC-002 | Traefik dashboard disabled by default | Check `--api.dashboard=false` in compose command |
| SEC-003 | Docker socket mounted read-only | Check `:ro` suffix on docker.sock volume |

---

### Test Files

#### 1. `tests/run4/test_m4_pipeline_e2e.py` (~400 LOC)
**Implements**: REQ-021 through REQ-025, TEST-011, TEST-012

| Test | Requirement | Description |
|------|-------------|-------------|
| `test_pipeline_phase1_build1_health` | REQ-021 | Start Build 1 via compose; verify all 3 HTTP 200 on /api/health |
| `test_pipeline_phase2_mcp_smoke` | REQ-022 | Verify key MCP tools callable after health check |
| `test_pipeline_phase3_architect_decompose` | REQ-023 | Feed PRD, get ServiceMap with 3+ services, DomainModel with 3+ entities |
| `test_pipeline_phase4_contract_registration` | REQ-024 | Register, validate, list contracts — all 3+ valid |
| `test_pipeline_phase5_parallel_builders` | REQ-025 | Launch 3 builders, >= 2 succeed, STATE.JSON written |
| `test_pipeline_e2e_timing` | TEST-011 | Record total duration; GREEN < 6h |
| `test_pipeline_checkpoint_resume` | TEST-012 | Save state after each phase; kill mid-build; verify resume from checkpoint |

#### 2. `tests/run4/test_m4_health_checks.py` (~250 LOC)
**Implements**: REQ-021, WIRE-017 through WIRE-020

| Test | Requirement | Description |
|------|-------------|-------------|
| `test_docker_compose_merge_networks` | WIRE-017 | Verify frontend/backend network membership via `docker network inspect` |
| `test_inter_container_dns` | WIRE-018 | Architect container resolves `contract-engine` hostname via HTTP |
| `test_traefik_pathprefix_routing` | WIRE-019 | PathPrefix labels route correctly through Traefik |
| `test_health_check_cascade_order` | WIRE-020 | Startup order respects dependency chain |
| `test_resource_budget_compliance` | TECH-006 | Total Docker RAM under 4.5GB |

#### 3. `tests/run4/test_m4_contract_compliance.py` (~350 LOC)
**Implements**: REQ-026 through REQ-028, SEC-001 through SEC-003, TECH-004, TECH-005

| Test | Requirement | Description |
|------|-------------|-------------|
| `test_schemathesis_contract_compliance` | REQ-026 | Run Schemathesis against each service's /openapi.json; > 70% compliance |
| `test_cross_service_integration_flow` | REQ-026 | Register -> Login -> Create Order -> Check Notification flow |
| `test_quality_gate_4_layers` | REQ-027 | L1 builder, L2 integration, L3 code quality, L4 static analysis |
| `test_planted_violations_detected` | REQ-028 | All 3 planted violations appear in report |
| `test_sec_001_no_explicit_api_key` | SEC-001 | Builder env does not contain explicit API key |
| `test_sec_002_traefik_dashboard_disabled` | SEC-002 | `--api.dashboard=false` in compose |
| `test_sec_003_docker_socket_readonly` | SEC-003 | docker.sock mounted `:ro` |
| `test_compose_5_file_merge` | TECH-004 | 5-file merge produces valid compose |
| `test_testcontainers_lifecycle` | TECH-005 | Testcontainers handles startup/cleanup; ephemeral volumes |

---

### Test Matrix Mapping (B1 + B3 + X entries for M4)

| Matrix ID | Test Function | Priority |
|-----------|---------------|----------|
| B1-01 | `test_build1_deploy` | P0 |
| B1-02 | `test_build1_health` | P0 |
| B1-03 | `test_architect_decompose` | P0 |
| B1-04 | `test_contract_validation` | P0 |
| B1-20 | `test_inter_container_dns` | P1 |
| B3-01 | `test_pipeline_e2e` | P0 |
| B3-02 | `test_deploy_and_health` | P0 |
| B3-03 | `test_schemathesis_violations` | P1 |
| B3-04 | `test_gate_layer_order` | P0 |
| B3-05 | `test_cli_commands` | P1 |
| B3-06 | `test_compose_generation` | P0 |
| B3-07 | `test_traefik_routing` | P1 |
| B3-08 | `test_state_persistence` | P0 |
| B3-09 | `test_graceful_shutdown` | P1 |
| X-08 | `test_docker_compose_merge` | P1 |
| X-09 | `test_quality_gate_l1_builder_result` | P1 |
| X-10 | `test_quality_gate_l3_generated_code` | P1 |

---

### Dependencies on M2 and M3

| Dependency | Source | Usage |
|------------|--------|-------|
| MCP tool verification | M2 | Confirms tools work before pipeline uses them |
| Client wrapper validation | M2 | Confirms safe defaults and retry behavior |
| Builder invocation | M3 | `invoke_builder()`, `run_parallel_builders()` |
| Config generation | M3 | `generate_builder_config()` |
| STATE.JSON parsing | M3 | `parse_builder_state()` |
| Fix pass invocation | M3 | `feed_violations_to_builder()` |

### Risk Analysis

| Risk | Impact | Mitigation |
|------|--------|------------|
| Docker Desktop not running | All Docker tests fail | Check Docker availability at test start |
| Port conflicts on 80/8080 | Traefik can't bind | Use random port mapping |
| Builder takes > 30 min | Pipeline timeout | Set `builder_timeout_s: 3600` for initial runs |
| Generated services don't start | Phase 6 fails | Log container output, retry with compose restart |
| Schemathesis takes very long | Test timeout | Set reasonable `--hypothesis-max-examples` |

### Gate Condition

**Milestone 4 is COMPLETE when**: All REQ-021 through REQ-028, WIRE-017 through WIRE-020, TECH-004 through TECH-006, SEC-001 through SEC-003, TEST-011, TEST-012 tests pass. This unblocks M5.

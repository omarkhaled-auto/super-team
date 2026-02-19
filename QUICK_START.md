# Quick Start: Build an App with Super Agent Team

Get from a PRD (Product Requirements Document) to a running, tested, multi-service application in under 5 minutes.

---

## Prerequisites

| Requirement | Minimum Version | Install |
|-------------|-----------------|---------|
| Docker Desktop | Docker Compose v2 | [docker.com](https://www.docker.com/products/docker-desktop/) |
| Python | 3.12+ | [python.org](https://www.python.org/downloads/) |
| Claude Code CLI | Latest | `npm install -g @anthropic-ai/claude-code && claude login` |
| Anthropic API Key | -- | `export ANTHROPIC_API_KEY=sk-ant-...` |

Verify your environment:

```bash
docker compose version   # Docker Compose v2.x.x
python --version         # Python 3.12+
claude --version         # Claude Code CLI
```

---

## Step 1: Install Super Team

```bash
cd C:\MY_PROJECTS\super-team
pip install -e ".[dev]"
```

---

## Step 2: Start Foundation Services (Build 1)

Start the three MCP foundation services with Docker Compose:

```bash
docker compose up -d --build
```

Wait for all 3 services to become healthy (30-60 seconds):

```bash
# Check health endpoints
curl http://localhost:8001/api/health  # Architect
curl http://localhost:8002/api/health  # Contract Engine
curl http://localhost:8003/api/health  # Codebase Intelligence
```

Or watch them with:

```bash
docker compose ps
```

All three services should show `(healthy)` status.

---

## Step 3: Write Your PRD

Create a PRD file describing your application. The PRD should define:

- Service names and responsibilities
- API endpoints for each service
- Data models / entities
- Inter-service communication patterns
- Technology stack preferences

See `tests/run4/fixtures/sample_prd.md` for a complete reference (the TaskTracker 3-service example).

Minimal PRD structure:

```markdown
# My Application

## Service 1: auth-service
### Description
Handles user registration, login, and JWT authentication.
### Endpoints
- POST /register - Create new user
- POST /login - Authenticate and return JWT
- GET /users/me - Get current user profile

## Service 2: order-service
### Description
Manages order lifecycle.
### Endpoints
- POST /orders - Create an order (requires JWT)
- GET /orders/:id - Get order details
```

---

## Step 4: Run the Pipeline

### Option A: Full End-to-End (Recommended)

```bash
python -m src.super_orchestrator.cli run your_prd.md --config config.yaml
```

This executes all 6 phases automatically:

1. **Architect** -- Decomposes your PRD into service boundaries and domain models
2. **Contract Registration** -- Registers OpenAPI/AsyncAPI contracts for each service
3. **Builders** -- Launches parallel builder agents (agent-team) to generate each service
4. **Integration** -- Deploys services via Docker Compose with Traefik, runs compliance tests
5. **Quality Gate** -- 4-layer quality verification (per-service, contract, system, adversarial)
6. **Fix Pass** -- If quality gate fails, feeds violations back to builders (up to 3 retries)

### Option B: Step-by-Step

```bash
# Initialize a new pipeline run
python -m src.super_orchestrator.cli init your_prd.md

# Run architect decomposition only
python -m src.super_orchestrator.cli plan

# Run builder fleet only
python -m src.super_orchestrator.cli build --max-concurrent 3

# Run integration tests
python -m src.super_orchestrator.cli integrate

# Run quality gate verification
python -m src.super_orchestrator.cli verify
```

---

## Step 5: Check Results

### Pipeline State

```bash
python -m src.super_orchestrator.cli status
```

### Docker Services (if integration ran)

```bash
docker compose --project-name super-team-run4 ps
```

### Quality Report

```bash
cat .super-orchestrator/QUALITY_GATE_REPORT.md
```

### Integration Report

```bash
cat .super-orchestrator/INTEGRATION_REPORT.md
```

### Pipeline Artifacts

All artifacts are stored in `.super-orchestrator/`:

```
.super-orchestrator/
  PIPELINE_STATE.json       # Current state machine position
  service_map.json          # Architect decomposition output
  domain_model.json         # Entity/relationship model
  contracts/                # Registered API contracts
  <service-id>/             # Per-service builder output
    builder_config.json     # Builder configuration
    prd_input.md            # PRD copy for builder
    .agent-team/STATE.json  # Builder result
  integration_report.json   # Integration test results
  INTEGRATION_REPORT.md     # Human-readable integration report
  quality_gate_report.json  # Quality gate results
  QUALITY_GATE_REPORT.md    # Human-readable quality report
```

---

## Step 6: Resume an Interrupted Pipeline

If the pipeline is interrupted (Ctrl+C, timeout, budget exceeded), resume from exactly where it stopped:

```bash
python -m src.super_orchestrator.cli resume --config config.yaml
```

The pipeline persists its state after every phase transition, so no work is lost.

---

## Configuration

Edit `config.yaml` to customize pipeline behavior:

```yaml
# Architect phase
architect:
  max_retries: 2          # Retry attempts on failure
  timeout: 900            # Seconds for decomposition (default: 900)
  auto_approve: false     # Skip human review of architecture

# Builder fleet
builder:
  max_concurrent: 3       # Parallel builders (default: 3)
  timeout_per_builder: 1800  # Per-builder timeout in seconds (default: 1800)
  depth: "thorough"       # Build depth: quick, standard, thorough

# Integration testing
integration:
  timeout: 600            # Docker health check timeout (seconds)
  traefik_image: "traefik:v3.6"  # API gateway image

# Quality gate
quality_gate:
  max_fix_retries: 3      # Fix pass iterations before giving up
  layer3_scanners:         # System-level scanners to run
    - security
    - cors
    - logging
    - trace
    - secrets
    - docker
    - health
  layer4_enabled: true     # Enable adversarial analysis

# Global
budget_limit: 50.0        # Maximum spend in USD (null for unlimited)
output_dir: ".super-orchestrator"  # Artifact output directory
mode: "auto"              # Execution mode: docker, mcp, or auto
```

---

## Troubleshooting

| Problem | Solution |
|---------|----------|
| **Services won't start** | Run `docker compose logs` to check for errors. Ensure ports 8001-8003 are free. |
| **Builder timeout** | Increase `builder.timeout_per_builder` in config.yaml. Default is 1800s (30 min). |
| **Quality gate fails** | Check `.super-orchestrator/QUALITY_GATE_REPORT.md` for specific violations. The fix pass will attempt automatic remediation up to `max_fix_retries` times. |
| **Budget exceeded** | Increase `budget_limit` in config.yaml or set to `null` for unlimited. Resume with `--resume`. |
| **No builder module found** | Install agent-team: `pip install agent-team-v15` or `pip install agent-team`. |
| **MCP not available** | The pipeline falls back to subprocess mode automatically. Ensure Build 1 services are running. |
| **Docker Compose not found** | Install Docker Desktop with Compose v2. Verify with `docker compose version`. |
| **Pipeline state corrupt** | Delete `.super-orchestrator/PIPELINE_STATE.json` and restart the pipeline. |

---

## Running Tests

```bash
# All tests
pytest tests/ -v

# With coverage
pytest tests/ -v --cov=src --cov-report=term-missing

# By component
pytest tests/test_architect/ -v           # Architect service
pytest tests/test_contract_engine/ -v     # Contract engine
pytest tests/test_codebase_intelligence/ -v  # Codebase intelligence
pytest tests/test_integration/ -v         # Integration tests
pytest tests/test_mcp/ -v                 # MCP server tests
pytest tests/build3/ -v                   # Build 3 (orchestrator, quality gate)
pytest tests/run4/ -v                     # Run 4 (verification suite)
pytest tests/e2e/ -v                      # End-to-end API tests
```

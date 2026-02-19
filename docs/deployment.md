# Deployment Guide

Deployment guide for the Super Agent Team platform covering Docker Compose deployment, local development setup, environment configuration, and operational procedures.

---

## Prerequisites

- **Docker and Docker Compose** for containerized deployment
- **Python 3.11+** (3.12 recommended) for local development
- **pip** for package management
- **Git** for source control

---

## Docker Compose Deployment

### Services Overview

The `docker-compose.yml` defines three services on a shared `super-team-net` bridge network:

#### 1. architect

| Setting | Value |
|---------|-------|
| Build context | `.` (root) |
| Dockerfile | `docker/architect/Dockerfile` |
| Port mapping | `8001:8000` |
| Volume | `architect-data:/data` |
| Depends on | `contract-engine` (condition: `service_healthy`) |
| Restart policy | `unless-stopped` |

**Environment variables:**

```yaml
DATABASE_PATH: /data/architect.db
CONTRACT_ENGINE_URL: http://contract-engine:8000
CODEBASE_INTEL_URL: http://codebase-intel:8000
LOG_LEVEL: info
```

**Health check:**

```yaml
test: python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/api/health')"
interval: 10s
timeout: 5s
retries: 5
start_period: 15s
```

#### 2. contract-engine

| Setting | Value |
|---------|-------|
| Build context | `.` (root) |
| Dockerfile | `docker/contract_engine/Dockerfile` |
| Port mapping | `8002:8000` |
| Volume | `contract-data:/data` |
| Depends on | None (starts first) |
| Restart policy | `unless-stopped` |

**Environment variables:**

```yaml
DATABASE_PATH: /data/contracts.db
LOG_LEVEL: info
```

**Health check:**

```yaml
test: python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/api/health')"
interval: 10s
timeout: 5s
retries: 5
start_period: 10s
```

#### 3. codebase-intel

| Setting | Value |
|---------|-------|
| Build context | `.` (root) |
| Dockerfile | `docker/codebase_intelligence/Dockerfile` |
| Port mapping | `8003:8000` |
| Volume | `intel-data:/data` |
| Depends on | `contract-engine` (condition: `service_healthy`) |
| Restart policy | `unless-stopped` |

**Environment variables:**

```yaml
DATABASE_PATH: /data/symbols.db
CHROMA_PATH: /data/chroma
GRAPH_PATH: /data/graph.json
CONTRACT_ENGINE_URL: http://contract-engine:8000
LOG_LEVEL: info
```

**Health check:**

```yaml
test: python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/api/health')"
interval: 10s
timeout: 5s
retries: 5
start_period: 20s
```

### Dockerfile Common Pattern

All three services follow the same Dockerfile structure:

1. Base image: `python:3.12-slim`
2. Set `WORKDIR /app`
3. Install dependencies from `requirements.txt`
4. Copy `src/shared/` and the service-specific source code
5. Create `/data` directory with a non-root `appuser`
6. `EXPOSE 8000`
7. Run the service with `uvicorn`

The **Codebase Intelligence** Dockerfile additionally pre-downloads the ChromaDB embedding model during the build step to avoid a slow first start at runtime.

### Named Volumes

| Volume | Contents |
|--------|----------|
| `architect-data` | `architect.db` |
| `contract-data` | `contracts.db` |
| `intel-data` | `symbols.db`, `chroma/`, `graph.json` |

---

## Environment Variables

| Variable | Default | Services | Description |
|----------|---------|----------|-------------|
| `DATABASE_PATH` | `./data/service.db` | All | SQLite database path |
| `LOG_LEVEL` | `info` | All | Logging level (`debug`/`info`/`warning`/`error`) |
| `CONTRACT_ENGINE_URL` | `http://contract-engine:8000` | Architect, Codebase Intel | Contract Engine URL |
| `CODEBASE_INTEL_URL` | `http://codebase-intel:8000` | Architect | Codebase Intelligence URL |
| `CHROMA_PATH` | `./data/chroma` | Codebase Intel | ChromaDB persistence path |
| `GRAPH_PATH` | `./data/graph.json` | Codebase Intel | NetworkX graph path |

> **Note:** In Docker, service names (`contract-engine`, `codebase-intel`) serve as hostnames on the `super-team-net` network. For local development, use `localhost` with the mapped ports instead.

### .env.example

```bash
DATABASE_PATH=./data/service.db
CONTRACT_ENGINE_URL=http://localhost:8002
CODEBASE_INTEL_URL=http://localhost:8003
CHROMA_PATH=./data/chroma
GRAPH_PATH=./data/graph.json
LOG_LEVEL=info
```

---

## Health Check Monitoring

All services expose a `GET /api/health` endpoint that returns:

```json
{
  "status": "healthy" | "degraded" | "unhealthy",
  "service_name": "<string>",
  "version": "1.0.0",
  "database": "connected" | "disconnected",
  "uptime_seconds": 123.45,
  "details": {}
}
```

Docker health checks use Python `urllib.request` (not `curl`) to maintain a minimal container footprint with the `python:3.12-slim` base image.

---

## MCP Server Configuration

The `.mcp.json` file configures three MCP servers for Claude Code integration:

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

Place this file in the project root. Claude Code will automatically discover and launch the MCP servers. Each MCP server creates its own `ConnectionPool` instance independent from the FastAPI apps.

---

## Local Development Setup (without Docker)

### Install Dependencies

```bash
pip install -e ".[dev]"
```

### Create Data Directories

```bash
mkdir -p data
```

### Set Environment Variables

```bash
cp .env.example .env
# Edit .env — use localhost URLs:
# CONTRACT_ENGINE_URL=http://localhost:8002
# CODEBASE_INTEL_URL=http://localhost:8003
```

### Start Services

Start each service in a separate terminal. The Contract Engine must start first since it has no dependencies and other services depend on it.

```bash
# Terminal 1: Contract Engine (start first — no dependencies)
DATABASE_PATH=./data/contracts.db uvicorn src.contract_engine.main:app --host 0.0.0.0 --port 8002

# Terminal 2: Architect
DATABASE_PATH=./data/architect.db CONTRACT_ENGINE_URL=http://localhost:8002 uvicorn src.architect.main:app --host 0.0.0.0 --port 8001

# Terminal 3: Codebase Intelligence
DATABASE_PATH=./data/symbols.db CHROMA_PATH=./data/chroma GRAPH_PATH=./data/graph.json CONTRACT_ENGINE_URL=http://localhost:8002 uvicorn src.codebase_intelligence.main:app --host 0.0.0.0 --port 8003
```

### Run Tests

```bash
pytest tests/ -v
pytest tests/ -v --cov=src --cov-report=term-missing
```

### Run MCP Servers Locally

```bash
python -m src.architect.mcp_server
python -m src.contract_engine.mcp_server
python -m src.codebase_intelligence.mcp_server
```

---

## pyproject.toml Key Settings

| Setting | Value |
|---------|-------|
| `name` | `super-team` |
| `version` | `1.0.0` |
| `requires-python` | `>=3.11` |
| pytest `asyncio_mode` | `auto` |
| pytest `pythonpath` | `["."]` |
| ruff `target-version` | `py312` |
| ruff `line-length` | `100` |

---

## Volume Management

- **Reset all data:** `docker-compose down -v` removes all named volumes
- **Backup data:** `docker cp <container>:/data ./backup/`
- **Persistence:** Volumes persist across container restarts
- **Database location:** SQLite databases are stored at `/data/<service>.db` inside containers

---

## Troubleshooting

| Issue | Resolution |
|-------|------------|
| **Port conflicts** | Check that ports `8001`, `8002`, and `8003` are free before starting services |
| **Health check failures** | Check service logs with `docker-compose logs <service>` |
| **Database locked** | SQLite uses WAL mode with a 30-second busy timeout; ensure only one writer at a time |
| **ChromaDB model download** | First start of `codebase-intel` may be slow due to embedding model download (pre-downloaded during Docker build) |

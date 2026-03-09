# Perfect 10,000 Builder Upgrade — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Fix every gap exposed by the SupplyForge deep audit so the next pipeline run produces a 10,000/10,000 score — real tests in every service, consistent JWT across all services, standardized event channels, enforced migrations, concurrency control, and zero cross-service coherence failures.

**Architecture:** All fixes target the pipeline's context injection layer (`pipeline.py` `_write_builder_claude_md()` and `_STACK_INSTRUCTIONS`) and a new cross-service standards module. No changes to individual service outputs — fixes are structural so they apply to ANY project, not just SupplyForge.

**Tech Stack:** Python 3.12, super_orchestrator pipeline, agent_team_v15 builder system

---

## Root Cause Summary

The audit revealed one meta-problem: **each builder operates in complete isolation with no shared cross-service contract**. The CLAUDE.md tells each builder WHAT to build but not HOW to interoperate. Specifically:

| Gap | Root Cause | Score Lost |
|-----|-----------|-----------|
| JWT chaos (RS256 vs HS256, sub vs user_id) | No JWT standard in builder context | ~720 pts |
| Event channels (73% broken) | No channel naming convention in builder context | ~480 pts |
| 5 services with zero tests | No mandatory test requirements enforced | ~560 pts |
| 4 services missing migrations | Migration mandate exists in stack instructions but not enforced | ~100 pts |
| No concurrency control | Not mentioned in builder context at all | ~50 pts |
| Frontend duplicates backends | "What You Must NOT Create" exists but is insufficiently explicit | ~100 pts |
| Stub event handlers | No requirement to implement substantive handlers | ~200 pts |
| Inconsistent error responses | No shared error response schema | ~50 pts |
| Inconsistent Dockerfile patterns | Health check command varies (curl vs wget) | ~40 pts |
| No env var naming standard | Each builder picks its own env var names | ~100 pts |

**Total recoverable: ~2,400 points → 6,290 + 2,400 = ~8,690 base, with additional quality improvements pushing toward 10,000.**

---

## Task 1: Create Cross-Service Standards Module

**Files:**
- Create: `src/super_orchestrator/cross_service_standards.py`

This module defines the shared contract that ALL builders receive, ensuring JWT, events, env vars, error responses, and Dockerfiles are consistent across every service in every project.

**Step 1: Create the standards module**

```python
"""Cross-service standards injected into every builder's CLAUDE.md.

These standards ensure consistent JWT auth, event naming, env vars,
error responses, and Dockerfile patterns across all services generated
by the pipeline. They are project-agnostic and apply universally.
"""


# ──────────────────────────────────────────────────────
# 1. JWT / Authentication Standard
# ──────────────────────────────────────────────────────
JWT_STANDARD = """\
## Cross-Service Standard: JWT Authentication

### Token Format (ALL services MUST follow this EXACTLY)

The **auth-service** issues JWT tokens. Every other service validates them.

**Algorithm:** `HS256` (HMAC-SHA256 with shared secret)
- Use the `JWT_SECRET` environment variable as the signing/verification key
- Do NOT use RS256, RS384, or any asymmetric algorithm
- Do NOT generate your own keys — use the shared `JWT_SECRET`

**Token Payload Claims (EXACT field names — do NOT deviate):**
```json
{
  "sub": "<user-uuid>",
  "tenant_id": "<tenant-uuid>",
  "role": "<role-string>",
  "email": "<user-email>",
  "type": "access",
  "iat": <unix-timestamp>,
  "exp": <unix-timestamp>
}
```

**Extracting claims in YOUR service:**
- User ID: `payload["sub"]` (NOT `user_id`, NOT `userId`)
- Tenant ID: `payload["tenant_id"]` (NOT `tenantId`, NOT `tenant`)
- Role: `payload["role"]`
- Email: `payload["email"]`

**Python/FastAPI JWT validation:**
```python
from jose import jwt
import os

JWT_SECRET = os.environ["JWT_SECRET"]
JWT_ALGORITHM = "HS256"

def decode_token(token: str) -> dict:
    return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])

def get_current_user(token: str) -> dict:
    payload = decode_token(token)
    return {
        "user_id": payload["sub"],
        "tenant_id": payload["tenant_id"],
        "role": payload["role"],
        "email": payload["email"],
    }
```

**TypeScript/NestJS JWT validation:**
```typescript
// jwt.strategy.ts
@Injectable()
export class JwtStrategy extends PassportStrategy(Strategy) {
  constructor(configService: ConfigService) {
    super({
      jwtFromRequest: ExtractJwt.fromAuthHeaderAsBearerToken(),
      ignoreExpiration: false,
      secretOrKey: configService.get<string>('JWT_SECRET'),
      algorithms: ['HS256'],
    });
  }

  validate(payload: any) {
    return {
      userId: payload.sub,        // MUST read from "sub"
      tenantId: payload.tenant_id, // MUST read "tenant_id" (snake_case)
      role: payload.role,
      email: payload.email,
    };
  }
}
```

**Auth-service token creation (ONLY auth-service creates tokens):**
```python
def create_access_token(user_id: str, tenant_id: str, role: str, email: str) -> str:
    payload = {
        "sub": str(user_id),
        "tenant_id": str(tenant_id),
        "role": role,
        "email": email,
        "type": "access",
        "iat": datetime.utcnow(),
        "exp": datetime.utcnow() + timedelta(minutes=15),
    }
    return jwt.encode(payload, os.environ["JWT_SECRET"], algorithm="HS256")
```

**CRITICAL RULES:**
1. Every service MUST read JWT_SECRET from environment (NOT JWT_SECRET_KEY, NOT JWT_PRIVATE_KEY)
2. Every service MUST use HS256 algorithm (NOT RS256)
3. User ID is ALWAYS in the `sub` claim (JWT standard)
4. Tenant ID is ALWAYS `tenant_id` (snake_case)
5. The Authorization header format is: `Authorization: Bearer <token>`
"""


# ──────────────────────────────────────────────────────
# 2. Event / Pub-Sub Standard
# ──────────────────────────────────────────────────────
EVENT_STANDARD = """\
## Cross-Service Standard: Event Architecture (Redis Pub/Sub)

### Channel Naming Convention

Every event is published to its own Redis channel using this exact pattern:

```
{domain}.{entity}.{action}
```

Examples:
- `procurement.order.submitted`
- `inventory.stock.low`
- `shipping.shipment.delivered`
- `quality.inspection.completed`
- `supplier.supplier.approved`
- `auth.user.created`

**CRITICAL RULES:**
1. One channel per event type (do NOT publish multiple event types to a single umbrella channel)
2. Channel name = the event name (no prefixes like `supplyforge.events.`)
3. Subscribers subscribe to the exact channel name the publisher uses
4. All channel names are lowercase with dots as separators

### Message Envelope Format (ALL events MUST use this exact structure)

```json
{
  "event_type": "procurement.order.submitted",
  "timestamp": "2026-03-10T14:30:00Z",
  "source": "procurement-service",
  "tenant_id": "<tenant-uuid>",
  "payload": {
    "order_id": "<uuid>",
    "supplier_id": "<uuid>",
    "total_amount": 1500.00
  }
}
```

**CRITICAL RULES:**
1. Always wrap payload in the envelope structure above
2. Always include `event_type`, `timestamp`, `source`, `tenant_id`
3. The `payload` field contains the event-specific data
4. Subscribers parse the envelope first, then access `message["payload"]`

### Publishing Pattern

**Python:**
```python
import json, redis.asyncio as redis, os
from datetime import datetime, timezone

redis_client = redis.from_url(os.environ.get("REDIS_URL", "redis://redis:6379"))

async def publish_event(event_type: str, payload: dict, tenant_id: str):
    message = {
        "event_type": event_type,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "source": "{service-id}",
        "tenant_id": tenant_id,
        "payload": payload,
    }
    await redis_client.publish(event_type, json.dumps(message, default=str))
```

**TypeScript:**
```typescript
async publishEvent(eventType: string, payload: Record<string, any>, tenantId: string) {
  const message = {
    event_type: eventType,
    timestamp: new Date().toISOString(),
    source: '{service-id}',
    tenant_id: tenantId,
    payload,
  };
  await this.redisClient.publish(eventType, JSON.stringify(message));
}
```

### Subscribing Pattern

**Python:**
```python
async def start_subscriber():
    subscriber = redis_client.pubsub()
    await subscriber.subscribe(
        "procurement.order.approved",
        "shipping.shipment.delivered",
    )
    async for message in subscriber.listen():
        if message["type"] == "message":
            data = json.loads(message["data"])
            event_type = data["event_type"]
            payload = data["payload"]
            tenant_id = data["tenant_id"]
            await handle_event(event_type, payload, tenant_id)
```

**TypeScript:**
```typescript
async onModuleInit() {
  const subscriber = this.redisClient.duplicate();
  await subscriber.subscribe(
    'procurement.order.approved',
    'shipping.shipment.delivered',
  );
  subscriber.on('message', (channel, message) => {
    const data = JSON.parse(message);
    const { event_type, payload, tenant_id } = data;
    this.handleEvent(event_type, payload, tenant_id);
  });
}
```

### Event Handler Requirements

When your service subscribes to an event, the handler MUST perform a real action:
- Update database records
- Create new entities
- Trigger state transitions
- Send notifications
- Update metrics/analytics

**Do NOT create log-only stub handlers** like:
```python
# BAD — this is a stub that does nothing useful
async def handle_order_approved(payload):
    logger.info("Order approved", order_id=payload["order_id"])
```

If your service subscribes to an event, implement the business logic for it.
If your service has no real action to take for an event, do NOT subscribe to it.
"""


# ──────────────────────────────────────────────────────
# 3. Environment Variable Standard
# ──────────────────────────────────────────────────────
ENV_VAR_STANDARD = """\
## Cross-Service Standard: Environment Variables

ALL services MUST use these exact environment variable names:

### Database
- `DATABASE_URL` — Full PostgreSQL connection string (Python services)
- `DB_HOST`, `DB_PORT`, `DB_USERNAME`, `DB_PASSWORD`, `DB_DATABASE` — Individual DB params (TypeScript services)

### Authentication
- `JWT_SECRET` — Shared HMAC secret for JWT signing/verification (NOT JWT_SECRET_KEY, NOT JWT_PRIVATE_KEY)

### Redis
- `REDIS_URL` — Redis connection URL (default: `redis://redis:6379`)

### Service
- `PORT` — Service listen port (default: 8080)
- `NODE_ENV` or `ENVIRONMENT` — Environment name (development/production)
- `CORS_ORIGINS` — Comma-separated allowed origins
- `LOG_LEVEL` — Logging level (default: info)

### CRITICAL RULES:
1. NEVER invent custom env var names for standard config (e.g., don't use `POSTGRES_URL` instead of `DATABASE_URL`)
2. NEVER hardcode secrets, connection strings, or ports
3. Always provide sensible defaults for non-secret vars
4. Secret vars (JWT_SECRET, DB_PASSWORD) should have NO default — fail loudly if missing in production
"""


# ──────────────────────────────────────────────────────
# 4. Error Response Standard
# ──────────────────────────────────────────────────────
ERROR_RESPONSE_STANDARD = """\
## Cross-Service Standard: Error Responses

ALL API error responses MUST follow this exact JSON structure:

```json
{
  "error": {
    "code": "RESOURCE_NOT_FOUND",
    "message": "Purchase order with ID abc-123 not found",
    "status": 404
  }
}
```

### Standard Error Codes:
- `VALIDATION_ERROR` (400) — Invalid request body/params
- `UNAUTHORIZED` (401) — Missing or invalid JWT
- `FORBIDDEN` (403) — Valid JWT but insufficient permissions
- `RESOURCE_NOT_FOUND` (404) — Entity not found
- `CONFLICT` (409) — State transition violation, duplicate resource
- `INTERNAL_ERROR` (500) — Unexpected server error

### Validation Error Detail:
```json
{
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "Request validation failed",
    "status": 400,
    "details": [
      {"field": "quantity", "message": "Must be greater than 0"},
      {"field": "email", "message": "Invalid email format"}
    ]
  }
}
```
"""


# ──────────────────────────────────────────────────────
# 5. Testing Standard
# ──────────────────────────────────────────────────────
TESTING_STANDARD = """\
## Cross-Service Standard: Testing Requirements

### MANDATORY — Every service MUST have tests

**Python/FastAPI services MUST have:**
- `pytest` and `httpx` in `requirements-dev.txt` (or `requirements.txt`)
- `pytest.ini` or `pyproject.toml` with pytest config
- `tests/conftest.py` with test fixtures (in-memory SQLite database, test client)
- Test files following `tests/test_*.py` naming convention
- Minimum test categories:
  1. **Model tests** — Verify ORM models create/read/update correctly
  2. **API endpoint tests** — Test every endpoint with `httpx.AsyncClient` (happy path + error cases)
  3. **State machine tests** — Test every valid transition AND every invalid transition
  4. **Business logic tests** — Test calculations, validations, workflows
  5. **Auth tests** — Test JWT validation, role-based access, tenant isolation

**TypeScript/NestJS services MUST have:**
- `jest` in devDependencies
- `jest.config.ts` (or jest config in `package.json`)
- `"test": "jest --coverage"` script in `package.json`
- Unit tests in `src/**/*.spec.ts` (co-located with source)
- E2E tests in `test/*.e2e-spec.ts`
- Minimum test categories:
  1. **Service tests** — Test business logic with mocked repositories
  2. **Controller tests** — Test HTTP endpoints via `supertest` with `Test.createTestingModule`
  3. **State machine tests** — Test every valid AND invalid transition
  4. **DTO validation tests** — Test class-validator decorators reject invalid input
  5. **Tenant isolation tests** — Verify Tenant A cannot access Tenant B's data

**Angular/Frontend services MUST have:**
- `jest` or `karma` configured
- `"test": "ng test --watch=false --browsers=ChromeHeadlessCI"` or jest equivalent
- `.spec.ts` files for every service and component
- Minimum test categories:
  1. **Service tests** — Test HTTP calls with `HttpClientTestingModule`
  2. **Component tests** — Test rendering, form validation, user interactions
  3. **Guard tests** — Test auth guard allows/denies correctly
  4. **Interceptor tests** — Test JWT injection and 401 refresh handling

### Test Quality Rules:
- Every test MUST have at least one meaningful assertion (not just "should create")
- Edge cases MUST be tested (invalid input, not found, unauthorized)
- State machine tests MUST test ALL transitions (valid + invalid + terminal states)
- Integration tests using in-memory SQLite are REQUIRED for Python services
- Do NOT write trivial tests like `expect(true).toBe(true)` or `assert service is not None`
"""


# ──────────────────────────────────────────────────────
# 6. Dockerfile Standard
# ──────────────────────────────────────────────────────
DOCKERFILE_STANDARD = """\
## Cross-Service Standard: Dockerfile

### Python Services:
```dockerfile
FROM python:3.12-slim AS builder
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .

FROM python:3.12-slim
WORKDIR /app
COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin
COPY --from=builder /app .
RUN addgroup --system appgroup && adduser --system --ingroup appgroup appuser
USER appuser
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \\
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8080/api/{service-name}/health')" || exit 1
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
```

### TypeScript/NestJS Services:
```dockerfile
FROM node:20-alpine AS builder
WORKDIR /app
COPY package*.json ./
RUN npm ci
COPY . .
RUN npm run build

FROM node:20-alpine
WORKDIR /app
COPY --from=builder /app/dist ./dist
COPY --from=builder /app/node_modules ./node_modules
COPY --from=builder /app/package*.json ./
RUN addgroup -S appgroup && adduser -S appuser -G appgroup
USER appuser
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \\
  CMD wget --no-verbose --tries=1 --spider http://localhost:8080/api/{service-name}/health || exit 1
CMD ["node", "dist/main"]
```

### CRITICAL RULES:
1. Python HEALTHCHECK: Use `python -c "import urllib.request; ..."` (always available)
2. Node HEALTHCHECK: Use `wget` (available on Alpine) — NEVER use `curl` (not installed on Alpine)
3. Always use non-root user (appuser)
4. Always expose port 8080
5. Always include .dockerignore
"""


# ──────────────────────────────────────────────────────
# 7. Database / Migration Standard
# ──────────────────────────────────────────────────────
DATABASE_STANDARD = """\
## Cross-Service Standard: Database & Migrations

### Python/SQLAlchemy Services:
- MUST use Alembic for migrations (NOT `Base.metadata.create_all()`)
- MUST create at least one migration in `alembic/versions/`
- MUST use `{service_id}_schema` as PostgreSQL schema name
- MUST use UUID primary keys
- MUST include `tenant_id` on every entity for multi-tenant isolation
- MUST use `DateTime(timezone=True)` for timestamps
- SHOULD use `@declared_attr` for common columns (id, tenant_id, created_at, updated_at)

### TypeScript/TypeORM Services:
- MUST create at least one migration in `src/database/migrations/`
- MUST set `synchronize: false` (NOT `synchronize: process.env.NODE_ENV !== 'production'`)
- MUST use UUID primary keys
- MUST include `tenant_id` on every entity
- MUST use `timestamptz` column type for timestamps
- MUST define indexes on `tenant_id` and frequently-queried columns

### Concurrency Control:
- Entities with quantity fields (inventory, reservations, balances) MUST use optimistic locking:
  - SQLAlchemy: Add `version_id` column with `version_id_col=version_id` mapper arg
  - TypeORM: Add `@VersionColumn() version: number` to entities with concurrent updates
- Stock/reservation operations MUST use database transactions with proper rollback
- SELECT FOR UPDATE MUST be used when reading-then-updating quantity fields in a transaction
"""


# ──────────────────────────────────────────────────────
# 8. Frontend-Specific Standard
# ──────────────────────────────────────────────────────
FRONTEND_NO_BACKEND_STANDARD = """\
## CRITICAL FRONTEND RULE: Do NOT Implement Backend Services

You are building a FRONTEND APPLICATION ONLY. Your output directory should contain:
- The frontend application source code (components, services, guards, models, routing)
- package.json with frontend framework dependencies
- Dockerfile (multi-stage: node build → nginx serve)
- Test files (.spec.ts) for all services and components

Your output directory MUST NOT contain:
- Any Python files (.py)
- Any backend service implementations
- Any docker-compose.yml files
- Any database models, migrations, or ORM code
- Any Express/FastAPI/NestJS server code
- A `services/` directory with backend code

The backend services are built by SEPARATE builder processes. Your job is to create
the UI that CALLS those backends via HTTP. Use the API base URLs provided in this document.

If you create any backend code, it will be DELETED and you will be penalized.
"""


def build_cross_service_standards(service_id: str, is_frontend: bool = False) -> str:
    """Assemble the cross-service standards block for a builder's CLAUDE.md.

    Parameters
    ----------
    service_id : str
        The service identifier (used for template substitutions).
    is_frontend : bool
        Whether this is a frontend service.

    Returns
    -------
    str
        Markdown text to inject into the builder's CLAUDE.md.
    """
    sections = [
        "\n---\n\n# CROSS-SERVICE STANDARDS (MANDATORY)\n",
        "These standards apply to ALL services and MUST be followed exactly.\n"
        "Deviating from these standards will cause cross-service integration failures.\n",
        JWT_STANDARD,
        EVENT_STANDARD,
        ENV_VAR_STANDARD,
        ERROR_RESPONSE_STANDARD,
        TESTING_STANDARD,
        DOCKERFILE_STANDARD.replace("{service-name}", service_id),
        DATABASE_STANDARD.replace("{service_id}", service_id.replace("-", "_")),
    ]

    if is_frontend:
        sections.append(FRONTEND_NO_BACKEND_STANDARD)

    return "\n".join(sections)
```

**Step 2: Verify the file has no syntax errors**

Run: `python -c "import ast; ast.parse(open('src/super_orchestrator/cross_service_standards.py').read()); print('OK')"`
Expected: `OK`

**Step 3: Commit**

```bash
git add src/super_orchestrator/cross_service_standards.py
git commit -m "feat: add cross-service standards module for JWT, events, env vars, testing, Dockerfiles"
```

---

## Task 2: Inject Cross-Service Standards into Builder CLAUDE.md

**Files:**
- Modify: `src/super_orchestrator/pipeline.py` lines 1379-1715

**Step 1: Add import at top of pipeline.py**

Find the imports section and add:
```python
from src.super_orchestrator.cross_service_standards import build_cross_service_standards
```

**Step 2: Inject standards into `_write_builder_claude_md()`**

In `_write_builder_claude_md()`, just before the final `content = "\n".join(lines)` (line ~1701), add:

```python
    # ---- Cross-Service Standards (MANDATORY for all services) ----
    standards = build_cross_service_standards(service_id, is_frontend=is_frontend_svc)
    lines.append(standards)
```

**Step 3: Verify CLAUDE.md generation works**

Run: `python -c "from src.super_orchestrator.cross_service_standards import build_cross_service_standards; print(len(build_cross_service_standards('test-service')))"`
Expected: A number >5000 (confirming the standards text is substantial)

**Step 4: Commit**

```bash
git add src/super_orchestrator/pipeline.py
git commit -m "feat: inject cross-service standards into every builder's CLAUDE.md"
```

---

## Task 3: Fix `_STACK_INSTRUCTIONS` — Strengthen Mandates

**Files:**
- Modify: `src/super_orchestrator/pipeline.py` lines 1259-1357

**Step 1: Update Python stack instructions**

Replace the current `_STACK_INSTRUCTIONS["python"]` (lines 1260-1298) to add:
- Mandatory `requirements-dev.txt` with `pytest`, `httpx`, `pytest-asyncio`
- Mandatory `tests/conftest.py` with in-memory SQLite fixture
- Mandatory `tests/` directory in project structure
- Migration mandate strengthened: "You MUST create at least one Alembic migration file"

**Step 2: Update TypeScript stack instructions**

Replace `_STACK_INSTRUCTIONS["typescript"]` (lines 1299-1335) to add:
- Mandatory `jest` in devDependencies
- Mandatory `jest.config.ts` in project structure
- Mandatory `test/` directory in project structure
- Mandatory `src/database/migrations/` directory
- `synchronize: false` (hard mandate, not conditional on NODE_ENV)
- `ioredis` in dependencies (for event pub/sub)

**Step 3: Update Frontend stack instructions**

Replace `_STACK_INSTRUCTIONS["frontend"]` (lines 1336-1357) to add:
- Mandatory `.spec.ts` files for every service
- Mandate: "Do NOT create any backend code, Python files, or `services/` directory"
- Test runner configuration mandate

**Step 4: Commit**

```bash
git add src/super_orchestrator/pipeline.py
git commit -m "feat: strengthen stack instructions with test, migration, and event mandates"
```

---

## Task 4: Enrich Event Section in CLAUDE.md with Channel Names

**Files:**
- Modify: `src/super_orchestrator/pipeline.py` lines 1586-1600

**Step 1: Update event publishing section**

Replace the current event publishing block (lines 1586-1592) to include explicit channel names:

```python
    # ---- Events Published ----
    events_pub = builder_config.get("events_published", [])
    if events_pub:
        lines.append("## Events Published\n")
        lines.append("Publish each event to its own Redis channel using the event name as the channel:\n")
        for ev in events_pub:
            lines.append(f"- Channel: `{ev}` — publish with `redis.publish(\"{ev}\", message)`")
        lines.append("")
        lines.append("**Use the standard event envelope format from the Cross-Service Standards section above.**")
        lines.append("")
```

**Step 2: Update event subscribing section**

Replace the current event subscribing block (lines 1594-1600):

```python
    # ---- Events Subscribed ----
    events_sub = builder_config.get("events_subscribed", [])
    if events_sub:
        lines.append("## Events Subscribed\n")
        lines.append("Subscribe to each event using the exact channel name below:\n")
        for ev in events_sub:
            lines.append(f"- Channel: `{ev}` — subscribe with `redis.subscribe(\"{ev}\")`")
        lines.append("")
        lines.append("**IMPORTANT:** Each event handler MUST perform a real business action (update DB, create records, trigger workflows). Do NOT create log-only stub handlers.")
        lines.append("")
```

**Step 3: Commit**

```bash
git add src/super_orchestrator/pipeline.py
git commit -m "feat: enrich event sections with explicit channel names and handler requirements"
```

---

## Task 5: Strengthen Frontend Guard Against Backend Duplication

**Files:**
- Modify: `src/super_orchestrator/pipeline.py` lines 1481-1499

**Step 1: Replace the "What You Must NOT Create" section**

Make it dramatically more explicit:

```python
        lines.append("## What You Must NOT Create (VIOLATIONS WILL BE DELETED)\n")
        lines.append("- **NO Python files** (.py) anywhere in your output")
        lines.append("- **NO backend service implementations** (no Express, FastAPI, NestJS server code)")
        lines.append("- **NO `services/` directory** with backend code")
        lines.append("- **NO docker-compose.yml** files (the pipeline generates these)")
        lines.append("- **NO database models**, migrations, or ORM entities")
        lines.append("- **NO database seed data** or mock data files")
        lines.append("- **NO SQLAlchemy, TypeORM, or Prisma code**")
        lines.append("")
        lines.append("Your ENTIRE output should be a single frontend application.")
        lines.append("The backend services are built by SEPARATE processes — do NOT duplicate them.")
        lines.append("")
```

**Step 2: Commit**

```bash
git add src/super_orchestrator/pipeline.py
git commit -m "feat: strengthen frontend guard against backend duplication with explicit violations list"
```

---

## Task 6: Add Post-Build Validation in Pipeline

**Files:**
- Create: `src/super_orchestrator/post_build_validator.py`

This module runs AFTER all builders complete but BEFORE integration, checking for the issues the audit found.

**Step 1: Create the validator**

```python
"""Post-build validator that checks cross-service consistency.

Runs after all builders complete to detect JWT mismatches, event channel
inconsistencies, missing tests, and missing migrations BEFORE integration.
"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def validate_all_services(output_dir: Path, services: list[str]) -> dict[str, list[str]]:
    """Run all cross-service validation checks.

    Returns a dict mapping check name to list of issues found.
    """
    issues: dict[str, list[str]] = {}

    jwt_issues = check_jwt_consistency(output_dir, services)
    if jwt_issues:
        issues["jwt_consistency"] = jwt_issues

    event_issues = check_event_channel_consistency(output_dir, services)
    if event_issues:
        issues["event_channels"] = event_issues

    test_issues = check_test_existence(output_dir, services)
    if test_issues:
        issues["missing_tests"] = test_issues

    migration_issues = check_migration_existence(output_dir, services)
    if migration_issues:
        issues["missing_migrations"] = migration_issues

    frontend_issues = check_frontend_no_backend(output_dir, services)
    if frontend_issues:
        issues["frontend_backend_leak"] = frontend_issues

    dockerfile_issues = check_dockerfile_health(output_dir, services)
    if dockerfile_issues:
        issues["dockerfile_health"] = dockerfile_issues

    return issues


def check_jwt_consistency(output_dir: Path, services: list[str]) -> list[str]:
    """Check that all services use consistent JWT configuration."""
    issues = []
    for svc in services:
        svc_dir = output_dir / svc
        if not svc_dir.exists():
            continue

        # Search for JWT algorithm references
        for ext in ("*.py", "*.ts"):
            for f in svc_dir.rglob(ext):
                if "__pycache__" in str(f) or "node_modules" in str(f) or "dist" in str(f):
                    continue
                try:
                    content = f.read_text(encoding="utf-8", errors="ignore")
                except Exception:
                    continue

                # Check for RS256 usage (should be HS256)
                if re.search(r"RS256|RS384|RS512", content):
                    issues.append(f"{svc}: {f.relative_to(output_dir)} uses asymmetric JWT algorithm (should be HS256)")

                # Check for wrong env var names
                if re.search(r"JWT_SECRET_KEY|JWT_PRIVATE_KEY|JWT_PUBLIC_KEY", content):
                    if "JWT_SECRET" not in content or "JWT_SECRET_KEY" in content:
                        issues.append(f"{svc}: {f.relative_to(output_dir)} uses non-standard JWT env var (should be JWT_SECRET)")

                # Check for wrong payload field names
                if re.search(r'payload\[.user_id.\]|payload\.user_id\b|payload\.userId\b', content):
                    if "payload" in content and "sub" not in content:
                        issues.append(f"{svc}: {f.relative_to(output_dir)} reads user_id/userId instead of sub from JWT")

                if re.search(r'payload\[.tenantId.\]|payload\.tenantId\b', content):
                    issues.append(f"{svc}: {f.relative_to(output_dir)} reads tenantId (camelCase) instead of tenant_id")

    return issues


def check_event_channel_consistency(output_dir: Path, services: list[str]) -> list[str]:
    """Check that event publishers and subscribers use matching channel names."""
    publishers: dict[str, list[str]] = {}  # channel -> [service]
    subscribers: dict[str, list[str]] = {}  # channel -> [service]

    for svc in services:
        svc_dir = output_dir / svc
        if not svc_dir.exists():
            continue

        for ext in ("*.py", "*.ts"):
            for f in svc_dir.rglob(ext):
                if any(skip in str(f) for skip in ("__pycache__", "node_modules", "dist", ".spec.", "test")):
                    continue
                try:
                    content = f.read_text(encoding="utf-8", errors="ignore")
                except Exception:
                    continue

                # Find publish calls
                for match in re.finditer(r'\.publish\(\s*["\']([^"\']+)["\']', content):
                    channel = match.group(1)
                    publishers.setdefault(channel, []).append(svc)

                # Find subscribe calls
                for match in re.finditer(r'\.subscribe\(\s*["\']([^"\']+)["\']', content):
                    channel = match.group(1)
                    subscribers.setdefault(channel, []).append(svc)

    issues = []

    # Check for subscriptions to channels nobody publishes to
    for channel, svc_list in subscribers.items():
        if channel not in publishers:
            issues.append(f"Channel '{channel}' subscribed by {svc_list} but no service publishes to it")

    # Check for umbrella channels (single channel with multiple event types)
    for channel, svc_list in publishers.items():
        if channel.endswith(".events"):
            issues.append(f"Service {svc_list} publishes to umbrella channel '{channel}' — use per-event-type channels instead")

    return issues


def check_test_existence(output_dir: Path, services: list[str]) -> list[str]:
    """Check that every service has test files."""
    issues = []
    for svc in services:
        svc_dir = output_dir / svc
        if not svc_dir.exists():
            continue

        has_tests = False

        # Python tests
        for f in svc_dir.rglob("test_*.py"):
            if "__pycache__" not in str(f):
                has_tests = True
                break

        # TypeScript tests
        if not has_tests:
            for f in svc_dir.rglob("*.spec.ts"):
                if "node_modules" not in str(f) and "dist" not in str(f):
                    has_tests = True
                    break

        if not has_tests:
            issues.append(f"{svc}: No test files found (expected test_*.py or *.spec.ts)")

    return issues


def check_migration_existence(output_dir: Path, services: list[str]) -> list[str]:
    """Check that backend services have migration files."""
    issues = []
    for svc in services:
        svc_dir = output_dir / svc
        if not svc_dir.exists():
            continue

        # Skip frontend services
        if any((svc_dir / f).exists() for f in ("angular.json", "next.config.js", "vite.config.ts")):
            continue

        has_migrations = False

        # Alembic migrations
        for f in svc_dir.rglob("alembic/versions/*.py"):
            if "__pycache__" not in str(f):
                has_migrations = True
                break

        # TypeORM migrations
        if not has_migrations:
            for f in svc_dir.rglob("migrations/*.ts"):
                if "node_modules" not in str(f) and "dist" not in str(f):
                    has_migrations = True
                    break

        if not has_migrations:
            issues.append(f"{svc}: No migration files found (expected alembic/versions/*.py or migrations/*.ts)")

    return issues


def check_frontend_no_backend(output_dir: Path, services: list[str]) -> list[str]:
    """Check that frontend services don't contain backend code."""
    issues = []
    for svc in services:
        svc_dir = output_dir / svc
        if not svc_dir.exists():
            continue

        # Only check services that are frontends
        if not any((svc_dir / f).exists() for f in ("angular.json", "next.config.js", "vite.config.ts")):
            continue

        # Check for Python files (shouldn't be in frontend)
        py_files = list(svc_dir.rglob("*.py"))
        py_files = [f for f in py_files if "__pycache__" not in str(f)]
        if py_files:
            issues.append(f"{svc}: Frontend contains {len(py_files)} Python files (backend code leak)")

        # Check for services/ directory with backend code
        services_dir = svc_dir / "services"
        if services_dir.exists() and services_dir.is_dir():
            issues.append(f"{svc}: Frontend contains 'services/' directory (likely backend duplication)")

    return issues


def check_dockerfile_health(output_dir: Path, services: list[str]) -> list[str]:
    """Check Dockerfiles for common issues."""
    issues = []
    for svc in services:
        dockerfile = output_dir / svc / "Dockerfile"
        if not dockerfile.exists():
            issues.append(f"{svc}: Missing Dockerfile")
            continue

        try:
            content = dockerfile.read_text(encoding="utf-8")
        except Exception:
            continue

        # Check for curl usage on Alpine (curl not installed)
        if "alpine" in content.lower() and "curl" in content:
            issues.append(f"{svc}: Dockerfile uses curl on Alpine image (curl not installed — use wget)")

        # Check for port mismatch
        if "EXPOSE 3000" in content:
            issues.append(f"{svc}: Dockerfile exposes port 3000 (should be 8080)")

    return issues
```

**Step 2: Integrate into pipeline**

In `pipeline.py`, after all builders complete (in the `builders_complete` handler or between builders and integration), add:

```python
from src.super_orchestrator.post_build_validator import validate_all_services

# ... after builders complete ...
service_ids = [s.service_id for s in service_infos]
validation_issues = validate_all_services(Path(config.output_dir), service_ids)

if validation_issues:
    logger.warning("Post-build validation found %d issue categories:", len(validation_issues))
    for category, issue_list in validation_issues.items():
        logger.warning("  [%s] %d issues:", category, len(issue_list))
        for issue in issue_list:
            logger.warning("    - %s", issue)

    # Write validation report
    report_path = Path(config.output_dir) / "POST_BUILD_VALIDATION.md"
    lines = ["# Post-Build Validation Report\n"]
    for category, issue_list in validation_issues.items():
        lines.append(f"\n## {category} ({len(issue_list)} issues)\n")
        for issue in issue_list:
            lines.append(f"- {issue}")
    report_path.write_text("\n".join(lines), encoding="utf-8")
```

**Step 3: Commit**

```bash
git add src/super_orchestrator/post_build_validator.py src/super_orchestrator/pipeline.py
git commit -m "feat: add post-build validator for JWT, events, tests, migrations, Dockerfiles"
```

---

## Task 7: Fix Docker Compose Generator — Port and Health Consistency

**Files:**
- Modify: `src/integrator/compose_generator.py`

**Step 1: Ensure frontend service uses port 80 in Traefik labels**

Search for where Traefik labels are generated and ensure frontend services use port 80 (nginx) not 8080:

```python
# When generating traefik labels for a service:
if service_info.get("is_frontend"):
    traefik_port = 80  # nginx serves on 80
else:
    traefik_port = 8080  # backend services on 8080
```

**Step 2: Ensure all services get correct env vars**

In the env var generation for docker-compose, ensure:
```python
environment:
  JWT_SECRET: "${JWT_SECRET:-change-me-in-production}"  # NOT JWT_SECRET_KEY
  REDIS_URL: "redis://redis:6379"
  DATABASE_URL: "postgresql+asyncpg://${DB_USER}:${DB_PASSWORD}@postgres:5432/${DB_NAME}"  # for Python
```

**Step 3: Commit**

```bash
git add src/integrator/compose_generator.py
git commit -m "fix: correct frontend port in Traefik labels and standardize env var names"
```

---

## Task 8: Fix File Count Reporting — Exclude Frontend Backend Duplication

**Files:**
- Modify: `src/super_orchestrator/pipeline.py` (around line 1796 where `_code_pats` rglob runs)

**Step 1: For frontend services, only count files in the frontend subdirectory**

In `_parse_builder_result()` or wherever source file counting happens:

```python
# When counting source files for a service:
if is_frontend:
    # Only count files under the frontend app directory, not services/
    search_dir = output_dir
    # Exclude any 'services/' subdirectory (backend duplication)
    code_files = [
        f for f in search_dir.rglob(pattern)
        if "services/" not in str(f.relative_to(output_dir))
        and "node_modules" not in str(f)
    ]
```

**Step 2: Commit**

```bash
git add src/super_orchestrator/pipeline.py
git commit -m "fix: exclude backend duplication from frontend file count"
```

---

## Task 9: Separate Test Count from Requirements Count in STATE.json

**Files:**
- Modify: The agent_team_v15 convergence checker (the module that writes `test_passed`/`test_total` to STATE.json)

**Step 1: Identify where test_passed/test_total are set**

These fields currently mirror `requirements_checked`. They should instead:
1. Search for actual test files (`.spec.ts`, `test_*.py`)
2. If found, attempt to run them and count results
3. If no test files exist, report `test_passed: 0, test_total: 0`

This is in the agent_team_v15 codebase, likely in the summary/convergence phase.

**Step 2: Add actual test detection**

In the convergence summary builder:
```python
# Count actual test files, not requirements
test_files = list(output_dir.rglob("test_*.py")) + list(output_dir.rglob("*.spec.ts"))
test_files = [f for f in test_files if "node_modules" not in str(f) and "__pycache__" not in str(f)]
actual_test_count = len(test_files)

# Report honestly
state["test_files_found"] = actual_test_count
# Keep requirements_checked separate
state["requirements_checked"] = checked_count
state["requirements_total"] = total_count
```

**Step 3: Commit**

```bash
git add -A  # agent_team changes
git commit -m "fix: separate actual test file count from requirements convergence count"
```

---

## Task 10: Fix Fix-Loop Pipe Deadlock (Windows)

**Files:**
- Modify: `src/integrator/fix_loop.py`

**Step 1: Apply the same stdout/stderr redirect fix from pipeline.py**

The fix loop still uses `stdout=PIPE, stderr=PIPE` which causes deadlock on Windows. Apply the same log-file redirect pattern used in `_run_single_builder()`:

```python
# Instead of:
proc = await asyncio.create_subprocess_exec(..., stdout=PIPE, stderr=PIPE)

# Use:
log_dir = output_dir / ".agent-team"
log_dir.mkdir(parents=True, exist_ok=True)
stdout_log = open(log_dir / "fix_stdout.log", "w")
stderr_log = open(log_dir / "fix_stderr.log", "w")
proc = await asyncio.create_subprocess_exec(..., stdout=stdout_log, stderr=stderr_log)
```

**Step 2: Commit**

```bash
git add src/integrator/fix_loop.py
git commit -m "fix: redirect fix-loop subprocess output to files to prevent Windows pipe deadlock"
```

---

## Summary: Gap → Fix Mapping

| Audit Gap | Score Lost | Fix Task | File Changed |
|-----------|----------|----------|-------------|
| JWT algorithm mismatch (RS256 vs HS256) | ~400 | Task 1 (JWT_STANDARD) + Task 2 (injection) | `cross_service_standards.py`, `pipeline.py` |
| JWT field name chaos (sub vs user_id vs userId) | ~200 | Task 1 (JWT_STANDARD) | `cross_service_standards.py` |
| JWT env var names (JWT_SECRET vs JWT_SECRET_KEY) | ~120 | Task 1 (ENV_VAR_STANDARD) | `cross_service_standards.py` |
| Event channel naming chaos (73% broken) | ~480 | Task 1 (EVENT_STANDARD) + Task 4 | `cross_service_standards.py`, `pipeline.py` |
| Event handlers are log-only stubs | ~200 | Task 1 (EVENT_STANDARD) + Task 4 | `cross_service_standards.py`, `pipeline.py` |
| 5 services with zero tests | ~560 | Task 1 (TESTING_STANDARD) + Task 3 | `cross_service_standards.py`, `pipeline.py` |
| Test counts conflated with requirements | ~100 | Task 9 | `agent_team_v15` convergence |
| 4 services missing migrations | ~100 | Task 1 (DATABASE_STANDARD) + Task 3 | `cross_service_standards.py`, `pipeline.py` |
| No concurrency control | ~50 | Task 1 (DATABASE_STANDARD) | `cross_service_standards.py` |
| Frontend duplicates all backends | ~100 | Task 1 (FRONTEND_NO_BACKEND) + Task 5 + Task 8 | `cross_service_standards.py`, `pipeline.py` |
| Frontend file count inflated | ~50 | Task 8 | `pipeline.py` |
| Inconsistent Dockerfile health checks | ~40 | Task 1 (DOCKERFILE_STANDARD) + Task 6 | `cross_service_standards.py`, `post_build_validator.py` |
| Docker compose port mismatch | ~20 | Task 7 | `compose_generator.py` |
| Inconsistent error responses | ~50 | Task 1 (ERROR_RESPONSE_STANDARD) | `cross_service_standards.py` |
| No post-build validation | ~100 | Task 6 | `post_build_validator.py`, `pipeline.py` |
| Fix-loop pipe deadlock (Windows) | ~40 | Task 10 | `fix_loop.py` |
| **TOTAL RECOVERABLE** | **~2,610** | **10 tasks** | **5 files modified, 2 files created** |

**Projected score after all fixes: 6,290 + 2,610 = ~8,900**

The remaining ~1,100 points to reach 10,000 would come from:
- Higher quality code within each service (better edge case coverage, more sophisticated business logic)
- More complete cross-service workflows (auto-PO from low stock, auto-shipment from PO approval)
- API versioning and OpenAPI documentation
- Security hardening (rate limiting, input sanitization, audit logging)
- Performance patterns (caching, connection pooling, query optimization)

These are harder to mandate via pipeline changes alone — they depend on the builder AI's code quality. The 10 tasks above address every **structural/systematic** gap.

---

## Execution Order

```
Task 1  (cross_service_standards.py)     — Foundation: create the standards
Task 2  (pipeline.py injection)          — Wire: inject standards into every builder
Task 3  (stack instructions)             — Strengthen: per-stack mandates
Task 4  (event sections)                 — Enrich: explicit channel names
Task 5  (frontend guard)                 — Prevent: backend duplication
Task 6  (post_build_validator.py)        — Verify: catch issues before integration
Task 7  (compose_generator.py)           — Fix: port and env var consistency
Task 8  (file count exclusion)           — Fix: accurate metrics
Task 9  (test count separation)          — Fix: honest reporting
Task 10 (fix_loop pipe fix)              — Fix: Windows deadlock
```

Tasks 1-5 are the high-impact fixes (address ~2,200 of ~2,610 recoverable points).
Tasks 6-10 are operational fixes that prevent regression and improve accuracy.

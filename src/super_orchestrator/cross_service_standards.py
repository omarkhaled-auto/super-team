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

**C# / ASP.NET Core JWT validation:**
```csharp
// In Program.cs:
builder.Services.AddAuthentication(JwtBearerDefaults.AuthenticationScheme)
    .AddJwtBearer(options => {
        options.TokenValidationParameters = new TokenValidationParameters {
            ValidateIssuerSigningKey = true,
            IssuerSigningKey = new SymmetricSecurityKey(
                Encoding.UTF8.GetBytes(builder.Configuration["JWT_SECRET"])),
            ValidateIssuer = false,
            ValidateAudience = false,
            ClockSkew = TimeSpan.Zero,
        };
    });

// Reading claims in a controller:
var userId = User.FindFirstValue("sub");           // NOT "user_id"
var tenantId = User.FindFirstValue("tenant_id");   // snake_case
var role = User.FindFirstValue("role");
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

### Cross-Service Workflow Examples

When your service subscribes to events, implement these workflows:

**If you are inventory-service and receive `procurement.order.approved`:**
- Create stock reservations for the ordered products
- Decrement available quantity

**If you are inventory-service and receive `procurement.receipt.created`:**
- Increase quantity_on_hand for received products
- Create stock movement audit records
- Check reorder points and publish `inventory.stock.low` if needed

**If you are quality-service and receive `procurement.receipt.created`:**
- Auto-create a quality inspection record for the received goods
- Set inspection status to SCHEDULED

**If you are quality-service and receive `shipping.shipment.delivered`:**
- Auto-create a quality inspection for delivered goods

**If you are shipping-service and receive `procurement.order.sent`:**
- Create a shipment record linked to the purchase order
- Set shipment status to PENDING

**If you are notification-service and receive ANY event:**
- Create an in-app notification for relevant users
- Check user preferences before sending email/SMS
- Apply escalation rules if configured

**If you are reporting-service and receive events:**
- Update analytics aggregations (not just log the event)
- Increment counters, update dashboards, recalculate KPIs

These are EXAMPLES. Implement the appropriate business logic for your service's domain.
The key rule: every event handler must DO something meaningful, not just log.

### Event Handler Error Handling and Idempotency

**Error handling**: Wrap every event handler in try/except (Python) or try/catch (TypeScript).
On failure, log the error with full event context but do NOT crash the subscriber loop.
The subscriber must continue processing subsequent events.

```python
# Python pattern
async def handle_event(event_type: str, payload: dict, tenant_id: str):
    try:
        if event_type == "procurement.order.approved":
            await process_order_approval(payload, tenant_id)
    except Exception as e:
        logger.error("Failed to handle %s: %s", event_type, e, exc_info=True)
        # Do NOT re-raise — continue processing other events
```

```typescript
// TypeScript pattern
private async handleEvent(eventType: string, payload: any, tenantId: string): Promise<void> {
    try {
        switch (eventType) {
            case 'procurement.order.approved':
                await this.processOrderApproval(payload, tenantId);
                break;
        }
    } catch (error) {
        this.logger.error(`Failed to handle ${eventType}:`, error);
        // Do NOT re-throw — continue processing other events
    }
}
```

### C# Event Publishing
```csharp
// Publishing via StackExchange.Redis
await _redis.GetSubscriber().PublishAsync(
    "procurement.order.approved",
    JsonSerializer.Serialize(new {
        event_type = "procurement.order.approved",
        timestamp = DateTime.UtcNow,
        source = "procurement-service",
        tenant_id = tenantId,
        payload = new { order_id = orderId, approved_by = userId }
    })
);
```

### C# Event Subscribing
```csharp
// Subscribing via StackExchange.Redis
var subscriber = _redis.GetSubscriber();
await subscriber.SubscribeAsync("procurement.order.approved", async (channel, message) => {
    try {
        var data = JsonSerializer.Deserialize<EventEnvelope>(message!);
        await ProcessOrderApproval(data.Payload, data.TenantId);
    } catch (Exception ex) {
        _logger.LogError(ex, "Failed to handle {Channel}", channel);
        // Do NOT re-throw — continue processing other events
    }
});
```
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
HEALTHCHECK --interval=15s --timeout=5s --start-period=90s --retries=5 \\
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/api/{service-name}/health')" || exit 1
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
HEALTHCHECK --interval=15s --timeout=5s --start-period=90s --retries=5 \\
  CMD wget -qO- http://127.0.0.1:8080/api/{service-name}/health || exit 1
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
# 8. State Machine Standard
# ──────────────────────────────────────────────────────
STATE_MACHINE_STANDARD = """\
## Cross-Service Standard: State Machine Implementation

Every entity with a `status` field MUST have a proper state machine:

### Implementation Requirements:
1. **Transition validator function**: Create `validate_transition(current_state, target_state) -> bool` that checks against an explicit allowed-transitions dict/map
2. **Enforcement in handlers**: Every PATCH/PUT endpoint that changes status MUST call the validator. Return HTTP 409 with error code `INVALID_TRANSITION` on invalid transitions
3. **Terminal states**: Define which states are terminal (no outgoing transitions). Attempting to transition FROM a terminal state MUST return 409
4. **Audit trail**: Log every successful transition with user_id, timestamp, from_state, to_state, entity_id
5. **Tests**: Write tests for every valid transition AND at least 3 invalid transitions AND self-transitions (same→same should fail)

### Python Pattern:
```python
VALID_TRANSITIONS = {
    "draft": {"submitted", "cancelled"},
    "submitted": {"approved", "rejected"},
    "approved": {"completed"},
    "rejected": {"draft"},  # allow re-edit
    "completed": set(),     # terminal
    "cancelled": set(),     # terminal
}

def validate_transition(current: str, target: str) -> bool:
    return target in VALID_TRANSITIONS.get(current, set())
```

### TypeScript Pattern:
```typescript
const VALID_TRANSITIONS: Record<string, string[]> = {
    draft: ['submitted', 'cancelled'],
    submitted: ['approved', 'rejected'],
    approved: ['completed'],
    rejected: ['draft'],
    completed: [],
    cancelled: [],
};

function validateTransition(current: string, target: string): boolean {
    return (VALID_TRANSITIONS[current] || []).includes(target);
}
```

### C# Pattern:
```csharp
public enum OrderStatus { Draft, Submitted, Approved, Rejected, Completed, Cancelled }

private static readonly Dictionary<OrderStatus, HashSet<OrderStatus>> ValidTransitions = new()
{
    [OrderStatus.Draft] = new() { OrderStatus.Submitted, OrderStatus.Cancelled },
    [OrderStatus.Submitted] = new() { OrderStatus.Approved, OrderStatus.Rejected },
    [OrderStatus.Approved] = new() { OrderStatus.Completed },
    [OrderStatus.Rejected] = new() { OrderStatus.Draft },
    [OrderStatus.Completed] = new(),   // terminal
    [OrderStatus.Cancelled] = new(),   // terminal
};

public static bool ValidateTransition(OrderStatus current, OrderStatus target)
    => ValidTransitions.TryGetValue(current, out var allowed) && allowed.Contains(target);
```
"""


# ──────────────────────────────────────────────────────
# 9. Handler Completeness Standard
# ──────────────────────────────────────────────────────
HANDLER_COMPLETENESS_STANDARD = """\
## Cross-Service Standard: API Handler Completeness

Every REST endpoint handler MUST implement ALL of the following:

1. **Input validation**: Use Pydantic model (Python) or DTO with class-validator (TypeScript)
2. **Authorization check**: Verify JWT token, check role permissions, enforce tenant isolation
3. **Business logic**: Call service layer — do NOT put business logic in route handlers
4. **Error handling**: Handle not-found (404), validation error (400/422), conflict (409), unauthorized (401/403)
5. **Response schema**: Return typed response (Pydantic model or DTO), not raw dicts/objects
6. **Tenant filtering**: ALL database queries MUST filter by `tenant_id` from JWT — never return data from other tenants

### Every Entity MUST Have These Endpoints:
- `GET /api/{svc}/{entities}` — List with pagination (limit, offset/page), filtering, sorting
- `GET /api/{svc}/{entities}/:id` — Get by ID (return 404 if not found or wrong tenant)
- `POST /api/{svc}/{entities}` — Create (validate input, return 201)
- `PATCH /api/{svc}/{entities}/:id` — Update (validate input, return 404 if not found)

### Pagination Pattern (MANDATORY for all list endpoints):
```python
# Python/FastAPI
@router.get("/items")
async def list_items(
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    sort_by: str = Query("created_at"),
    order: str = Query("desc", regex="^(asc|desc)$"),
):
```

```typescript
// NestJS
@Get()
async findAll(
    @Query('page', new DefaultValuePipe(1), ParseIntPipe) page: number,
    @Query('limit', new DefaultValuePipe(20), ParseIntPipe) limit: number,
) {
```
"""


# ──────────────────────────────────────────────────────
# 10. Frontend UX Standard
# ──────────────────────────────────────────────────────
FRONTEND_UX_STANDARD = """\
## Cross-Service Standard: Frontend UX Requirements

### Every Data-Fetching Page MUST Implement Three States:

1. **Loading state**: Show spinner/skeleton while API call is in progress
```typescript
@if (loading) {
  <div class="loading-spinner">Loading...</div>
}
```

2. **Empty state**: Show helpful message when data array is empty
```typescript
@if (!loading && items.length === 0) {
  <div class="empty-state">No items found. Create your first item.</div>
}
```

3. **Error state**: Show error message with retry button when API call fails
```typescript
@if (error) {
  <div class="error-state">
    <p>Failed to load data: {{ error }}</p>
    <button (click)="retry()">Retry</button>
  </div>
}
```

### JWT Token Refresh (MANDATORY):
The auth interceptor MUST handle 401 responses:
1. On 401: attempt token refresh via `POST /api/auth/refresh`
2. On refresh success: retry the original request with new token
3. On refresh failure: redirect to login page
4. Queue concurrent requests during refresh (don't send multiple refresh calls)

### Form Validation:
- Use Reactive Forms (Angular) or controlled forms (React)
- Show field-level validation errors below each input
- Disable submit button until form is valid
- Show loading state on submit button while API call is in progress

### Responsive Design:
- Use CSS Grid or Flexbox for layouts
- Tables should scroll horizontally on mobile
- Navigation should collapse to hamburger menu on small screens
"""


# ──────────────────────────────────────────────────────
# 11. Business Logic Standard
# ──────────────────────────────────────────────────────
BUSINESS_LOGIC_STANDARD = """\
## Cross-Service Standard: Business Logic Depth

### Service Layer Separation (MANDATORY):
- Route handlers/controllers handle HTTP concerns (request parsing, response formatting)
- Service classes contain ALL business logic (calculations, validations, workflows)
- Do NOT put business logic in route handlers — call service methods instead

### Business Rules MUST Be Enforced in Code:
Every domain constraint mentioned in the PRD MUST be implemented:
- Amount/quantity limits → validation in service layer
- Role-based restrictions (e.g., "cannot approve own request") → guard in service
- Referential integrity beyond FK constraints → check before save
- Computed/derived fields → calculate in service before persisting
- Time-based rules (expiry, deadlines) → validate in service

### Common Patterns to Implement:
1. **Total calculation**: Sum line items, apply discounts, compute tax
2. **Status-dependent validation**: Only allow edits in "draft" status
3. **Uniqueness checks**: Verify unique constraints before insert (return 409 on conflict)
4. **Cascade effects**: When parent status changes, update related entities
5. **Metric updates**: After data changes, update related metrics/ratings

### What NOT to Do:
- Do NOT return hardcoded/mock data from any endpoint
- Do NOT skip validation because "it's just a demo"
- Do NOT leave TODO/FIXME comments without implementing the feature
- Do NOT create empty service methods that just pass through to repository
"""


# ──────────────────────────────────────────────────────
# 12. API Versioning Standard
# ──────────────────────────────────────────────────────
API_VERSIONING_STANDARD = """\
## Cross-Service Standard: API Versioning

All API endpoints MUST be prefixed with the service name:
- Pattern: `/api/{service-name}/{resource}`
- Example: `/api/procurement/purchase-orders`
- Example: `/api/inventory/warehouses`
- Example: `/api/auth/login`

Rules:
1. ALL endpoints (except health) must start with `/api/{service-name}/`
2. Health endpoint: `GET /api/{service-name}/health`
3. Use kebab-case for URL paths (e.g., `purchase-orders`, not `purchaseOrders`)
4. Use plural nouns for collections (e.g., `/products`, not `/product`)
5. Use UUID path params for individual resources (e.g., `/products/:id`)
"""


# ──────────────────────────────────────────────────────
# 13. Security Standard
# ──────────────────────────────────────────────────────
SECURITY_STANDARD = """\
## Cross-Service Standard: Security

### Rate Limiting
- Login/register endpoints: 5 requests per minute per IP
- API endpoints: 100 requests per minute per user
- Use middleware/guard for enforcement

### Input Sanitization
- Validate ALL user input via Pydantic (Python) or class-validator (TypeScript)
- Never interpolate user input into SQL queries — use parameterized queries only
- Sanitize string inputs to prevent XSS (strip HTML tags in user-facing text fields)
- Validate UUID format for all ID parameters (use ParseUUIDPipe in NestJS, UUID type in Pydantic)

### Audit Logging
- Log ALL state transitions (who changed what, when, from which state to which state)
- Log ALL authentication events (login success, login failure, token refresh)
- Include `user_id`, `tenant_id`, `action`, `resource_type`, `resource_id`, `timestamp` in audit records
- Store audit logs in the database (not just console output)

### CORS
- Read allowed origins from `CORS_ORIGINS` environment variable
- Split by comma for multiple origins
- In development: allow `http://localhost:*`
- NEVER use `*` (allow all) in production configuration

### Headers
- Set `X-Content-Type-Options: nosniff`
- Set `X-Frame-Options: DENY`
- Remove `X-Powered-By` header (NestJS: `app.getHttpAdapter().getInstance().disable('x-powered-by')`)
"""


# ──────────────────────────────────────────────────────
# 14. Swagger / API Documentation Standard
# ──────────────────────────────────────────────────────
SWAGGER_STANDARD = """\
## Cross-Service Standard: API Documentation (OpenAPI/Swagger)

### Python/FastAPI
FastAPI auto-generates OpenAPI docs. Ensure:
- All endpoints have `summary` and `description` parameters in decorators
- All Pydantic models have `model_config = ConfigDict(json_schema_extra={"example": {...}})`
- Swagger UI available at `/api/{service-name}/docs`

### TypeScript/NestJS
- Install `@nestjs/swagger` and `swagger-ui-express`
- Add to `main.ts`:
```typescript
import { SwaggerModule, DocumentBuilder } from '@nestjs/swagger';

const config = new DocumentBuilder()
  .setTitle('{Service Name}')
  .setVersion('1.0')
  .addBearerAuth()
  .build();
const document = SwaggerModule.createDocument(app, config);
SwaggerModule.setup('api/{service-name}/docs', app, document);
```
- Use `@ApiTags`, `@ApiOperation`, `@ApiResponse` decorators on all controllers
- Use `@ApiProperty` on all DTO fields
"""


# ──────────────────────────────────────────────────────
# 15. Frontend-Specific Standard
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
        STATE_MACHINE_STANDARD,
        HANDLER_COMPLETENESS_STANDARD,
        BUSINESS_LOGIC_STANDARD,
        API_VERSIONING_STANDARD.replace("{service-name}", service_id),
        SECURITY_STANDARD,
        SWAGGER_STANDARD.replace("{service-name}", service_id),
    ]

    if is_frontend:
        sections.append(FRONTEND_NO_BACKEND_STANDARD)
        sections.append(FRONTEND_UX_STANDARD)

    return "\n".join(sections)

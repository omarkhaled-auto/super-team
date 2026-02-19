# Tech Stack Research

> **Research Date:** February 2026 (Updated: February 19, 2026)
> **Purpose:** Actionable best practices and patterns for production implementation
> **Note:** Research compiled from official documentation, authoritative web sources, and web search results. Context7 MCP tools were unavailable; research gathered via comprehensive web search.

---

## FastAPI (v0.129.0)

### Setup
- **ASGI Server Architecture**: Use Gunicorn with Uvicorn workers for production deployments. Worker count should equal the number of available CPU cores to minimize context switching overhead while maximizing utilization.
- **Project Structure**: Organize code by domain, not by file type. Each domain package should have its own `router.py`, `schemas.py`, `models.py`, `services.py`, and `exceptions.py` files.
- **Dependency Injection**: Leverage FastAPI's built-in dependency injection system. Dependencies are cached within a request's scope by default - if called multiple times in one route, it executes only once.
- **Lifespan Context Manager**: Use `@asynccontextmanager` for application lifecycle management (DB pools, Redis connections, ChromaDB client).

### Best Practices

#### API Design & Middleware
```python
# Middleware registration order matters - security middleware should execute before business logic
# Middleware added last executes first for incoming requests (onion model)

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
import uuid

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: Initialize DB pools, Redis connections, ChromaDB client
    app.state.db_pool = await create_db_pool()
    app.state.redis = await aioredis.from_url("redis://localhost")
    yield
    # Shutdown: Close connections
    await app.state.db_pool.close()
    await app.state.redis.close()

app = FastAPI(lifespan=lifespan)

# Add middleware in correct order - CORS first
app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://yourdomain.com"],  # Never use "*" in production
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["*"],
    allow_credentials=True,
)

# Request ID middleware for distributed tracing
@app.middleware("http")
async def add_request_id(request: Request, call_next):
    request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
    request.state.request_id = request_id
    response = await call_next(request)
    response.headers["X-Request-ID"] = request_id
    return response

# Timing middleware for performance monitoring
import time

@app.middleware("http")
async def add_timing(request: Request, call_next):
    start_time = time.perf_counter()
    response = await call_next(request)
    process_time = time.perf_counter() - start_time
    response.headers["X-Process-Time"] = str(process_time)
    return response
```

#### Authentication & Security (OAuth2 + JWT)
```python
from fastapi import Depends, HTTPException, status, Security
from fastapi.security import OAuth2PasswordBearer, SecurityScopes
from jose import JWTError, jwt
from passlib.context import CryptContext
from datetime import datetime, timedelta
import os

# Password hashing - ALWAYS hash passwords before storage
# 2026 Best Practice: Use Argon2id via pwdlib (memory-hard, GPU-resistant)
# Alternative: bcrypt via passlib (still acceptable)
from pwdlib import PasswordHash
pwd_hash = PasswordHash.recommended()  # Uses Argon2id

# Legacy bcrypt approach (still valid):
# pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(
    tokenUrl="token",
    scopes={
        "read": "Read access",
        "write": "Write access",
        "admin": "Admin access"
    }
)

# JWT configuration - ALWAYS use environment variables
SECRET_KEY = os.getenv("JWT_SECRET_KEY")  # Never hardcode
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30  # Short-lived access tokens

def create_access_token(data: dict, expires_delta: timedelta | None = None):
    to_encode = data.copy()
    expire = datetime.utcnow() + (expires_delta or timedelta(minutes=15))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

async def get_current_user(
    security_scopes: SecurityScopes,
    token: str = Depends(oauth2_scheme)
):
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": f'Bearer scope="{security_scopes.scope_str}"'},
    )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        token_scopes = payload.get("scopes", [])
        if username is None:
            raise credentials_exception
        # Verify required scopes
        for scope in security_scopes.scopes:
            if scope not in token_scopes:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Not enough permissions"
                )
    except JWTError:
        raise credentials_exception
    return username

# Usage with scopes
@app.get("/admin/users")
async def get_users(user: str = Security(get_current_user, scopes=["admin"])):
    return {"users": []}
```

#### Error Handling & Validation (Pydantic v2)
```python
from pydantic import BaseModel, field_validator, model_validator, EmailStr
from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError

# Custom exception handler for validation errors
@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    errors = []
    for error in exc.errors():
        errors.append({
            "field": ".".join(str(x) for x in error["loc"]),
            "message": error["msg"],
            "type": error["type"]
        })
    return JSONResponse(
        status_code=422,
        content={
            "detail": "Validation failed",
            "errors": errors,
            "request_id": getattr(request.state, "request_id", None)
        }
    )

# Domain-specific exceptions
class ResourceNotFoundError(Exception):
    def __init__(self, resource: str, id: str):
        self.resource = resource
        self.id = id

@app.exception_handler(ResourceNotFoundError)
async def resource_not_found_handler(request, exc):
    return JSONResponse(
        status_code=404,
        content={"error": f"{exc.resource} with id {exc.id} not found"}
    )

# Pydantic v2 syntax - key changes from v1:
# - @validator -> @field_validator
# - @root_validator -> @model_validator
# - .dict() -> .model_dump()
# - .json() -> .model_dump_json()

class UserCreate(BaseModel):
    username: str
    email: EmailStr  # Built-in email validation
    password: str

    @field_validator('username')
    @classmethod
    def validate_username(cls, v: str) -> str:
        if len(v) < 3:
            raise ValueError('Username must be at least 3 characters')
        if not v.isalnum():
            raise ValueError('Username must be alphanumeric')
        return v.lower()

    @model_validator(mode='after')
    def validate_password_strength(self) -> 'UserCreate':
        if len(self.password) < 8:
            raise ValueError('Password must be at least 8 characters')
        if self.username.lower() in self.password.lower():
            raise ValueError('Password cannot contain username')
        return self

# IMPORTANT: Never reuse one model for request and response
class UserResponse(BaseModel):
    id: int
    username: str
    email: EmailStr
    created_at: datetime
    # Note: password is NOT included in response

# Document all error responses in API
@app.post("/users", responses={
    201: {"description": "User created successfully"},
    400: {"description": "Validation error"},
    409: {"description": "User already exists"},
    500: {"description": "Internal server error"}
})
async def create_user(user: UserCreate):
    pass
```

#### Async/Await Best Practices
```python
# Use async def ONLY when performing I/O operations
# Use regular def for CPU-bound work (FastAPI runs it in threadpool)

# GOOD: async for I/O
@app.get("/data")
async def get_data(db: AsyncSession = Depends(get_db)):
    return await db.execute(query)

# GOOD: sync for CPU work (FastAPI handles in threadpool)
@app.get("/compute")
def compute_heavy():
    return heavy_computation()

# BAD: blocking in async - BLOCKS EVENT LOOP
@app.get("/broken")
async def broken():
    time.sleep(1)  # WRONG - use asyncio.sleep()
    requests.get(url)  # WRONG - use httpx

# CORRECT async patterns
import asyncio
import httpx

async def fetch_with_timeout(url: str, timeout: float = 5.0):
    async with asyncio.timeout(timeout):
        async with httpx.AsyncClient() as client:
            return await client.get(url)

# Background tasks for non-blocking work
from fastapi import BackgroundTasks

@app.post("/send-email")
async def send_email(background_tasks: BackgroundTasks):
    background_tasks.add_task(send_email_async, email_data)
    return {"message": "Email queued"}
```

### Pitfalls
- **Blocking I/O in async functions**: Never use synchronous libraries (like `requests`) in async endpoints without `run_in_executor`. Use `httpx` or `aiohttp` instead.
- **Missing await**: Forgetting to `await` async calls returns coroutine object, not results
- **Single Worker**: Running with one worker = single point of failure in production
- **High-Cardinality Metrics**: Unlimited label combinations (unique user_ids) cause Prometheus OOM
- **Sync DB in Async**: Using synchronous DB drivers in async endpoints blocks event loop
- **Global Mutable State**: Mutable global state without proper locking causes race conditions
- **Missing middleware order**: Security middleware must be registered before business logic middleware
- **Over-specification in Pydantic**: Use Pydantic validators for data shape; use FastAPI dependencies for database/external service validation
- **CORS misconfiguration**: Never use `allow_origins=["*"]` with `allow_credentials=True`
- **Not documenting error responses**: Always use `responses` parameter to document all possible error codes
- **Accidental data exposure**: Response models are security controls - returning ORM objects can leak `password_hash`, `access_token`, internal fields
- **Storing API keys in .env in production**: Use proper secret management (AWS Secrets Manager, HashiCorp Vault, etc.)

### Security
- Use `scram-sha-256` for database authentication when connecting from FastAPI
- Implement rate limiting middleware for public endpoints (use `slowapi` or `fastapi-limiter` with Redis)
- Use HTTPS in production (configure SSL in reverse proxy like nginx)
- Validate and sanitize all user inputs via Pydantic
- Store secrets in environment variables, never in code
- Implement CORS properly - whitelist specific origins in production
- Log auth failures as audit logs, but never log passwords or full token contents
- Use short-lived access tokens (15-30 minutes) with refresh token rotation
- Disable or protect API docs (`/docs`, `/redoc`) in production

### Production Deployment
```bash
# Use Gunicorn with Uvicorn workers for multi-core utilization
gunicorn main:app -w 4 -k uvicorn.workers.UvicornWorker --bind 0.0.0.0:8000

# Each worker process runs independent event loop on separate CPU cores
# with isolated memory spaces for fault isolation
```

---

## ChromaDB (v1.5.0)

### Setup
```python
import chromadb
from chromadb.config import Settings

# Development - Ephemeral (data lost on restart)
client = chromadb.Client()

# Development - Persistent (data stored locally)
client = chromadb.PersistentClient(path="./chroma_db")

# Production - HTTP client (RECOMMENDED)
client = chromadb.HttpClient(
    host="localhost",
    port=8000,
    settings=Settings(
        chroma_api_impl="rest",
        anonymized_telemetry=False
    )
)

# Production with authentication
client = chromadb.HttpClient(
    host="chroma.yourdomain.com",
    port=443,
    ssl=True,
    headers={"Authorization": f"Bearer {API_KEY}"}
)

# Create or get collection - ALWAYS specify embedding function
from chromadb.utils import embedding_functions
sentence_transformer_ef = embedding_functions.SentenceTransformerEmbeddingFunction(
    model_name="all-MiniLM-L6-v2"  # 384 dimensions
)

collection = client.get_or_create_collection(
    name="documents",
    embedding_function=sentence_transformer_ef,
    metadata={
        "hnsw:space": "cosine",  # cosine, l2, or ip
        "hnsw:construction_ef": 100,  # Index build quality
        "hnsw:M": 16,  # Max neighbors per node
        "hnsw:search_ef": 50,  # Query-time search quality
        "hnsw:batch_size": 1000  # Buffer before flushing
    }
)
```

### Best Practices

#### Collection & Embedding Management
```python
# Standard embedding dimensions:
# - 384 (MiniLM) - fast, good for most use cases
# - 768 (BERT) - better quality, more memory
# - 1536 (OpenAI ada-002) - highest quality, external API

# Use metadata for filtering to narrow search space BEFORE vector search
collection.add(
    documents=["document text here"],
    metadatas=[{
        "source": "wiki",
        "category": "tech",
        "timestamp": "2026-02-18",
        "user_id": "user123"  # For row-level security
    }],
    ids=["doc1"]
)

# Query with metadata filters - be aware of overhead:
# - Category filtering: ~3.3x query overhead
# - Numeric range queries: ~8x query overhead
results = collection.query(
    query_texts=["search query"],
    n_results=10,
    where={"category": "tech"},  # Filter by metadata
    where_document={"$contains": "keyword"},  # Filter by document content
    include=["documents", "metadatas", "distances"]
)

# CRITICAL: Batch operations for efficiency (500-5000 vectors typical)
# BAD: Individual inserts create high indexing overhead
for doc in documents:
    collection.add(documents=[doc], ...)  # SLOW

# GOOD: Batch inserts
collection.add(
    documents=documents_list,
    metadatas=metadatas_list,
    ids=ids_list  # Must be unique
)
```

#### FastAPI Integration
```python
from fastapi import FastAPI, Depends, BackgroundTasks, Request
import chromadb
from functools import lru_cache
import asyncio
from concurrent.futures import ThreadPoolExecutor

# Thread pool for blocking ChromaDB operations
executor = ThreadPoolExecutor(max_workers=4)

@lru_cache()
def get_chroma_client():
    return chromadb.PersistentClient(path="./chroma_db")

def get_collection(client = Depends(get_chroma_client)):
    return client.get_or_create_collection("documents")

# Async wrapper for blocking ChromaDB operations
async def async_query(collection, query_texts: list[str], n_results: int = 10):
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        executor,
        lambda: collection.query(query_texts=query_texts, n_results=n_results)
    )

@app.post("/search")
async def search_documents(
    query: str,
    collection = Depends(get_collection)
):
    results = await async_query(collection, [query], n_results=10)
    return {"results": results}

# Large document ingestion - use background tasks
@app.post("/documents/bulk")
async def bulk_add_documents(
    documents: list[str],
    background_tasks: BackgroundTasks,
    collection = Depends(get_collection)
):
    background_tasks.add_task(
        ingest_documents, collection, documents
    )
    return {"status": "processing", "count": len(documents)}
```

#### Data Preprocessing
```python
import numpy as np

def preprocess_embeddings(embeddings: list[list[float]]) -> list[list[float]]:
    """Normalize embeddings for better similarity search."""
    embeddings_np = np.array(embeddings)
    norms = np.linalg.norm(embeddings_np, axis=1, keepdims=True)
    normalized = embeddings_np / norms
    return normalized.tolist()
```

### Pitfalls
- **Embedding Model Mismatch**: Query and document embeddings MUST use same model and dimensions. First embedding sets collection dimensions - all must match.
- **Not specifying embedding function**: If not specified, ChromaDB uses a default; always be explicit
- **Mixing embedding models**: A new embedding model requires a new collection - never partially update with different models
- **Over-strict metadata filters**: Too restrictive filters can hurt recall; balance precision and recall
- **Large batch operations in API calls**: Handle large document ingestion asynchronously to prevent timeouts
- **Ignoring HNSW parameters**: Tune `hnsw:M` (default 16) and `hnsw:construction_ef` (default 100) for your use case
- **Small batches**: Individual inserts create excessive indexing overhead
- **No volume mount**: Docker without `-v` loses data on container removal
- **Disk space**: Large documents duplicate storage (metadata + FTS5 index)
- **Scaling beyond limits**: ChromaDB is ideal for prototyping and MVPs under 10 million vectors; consider alternatives for larger scale

### Security
- For HTTP deployments, always use HTTPS and authentication
- Configure network isolation for production deployments
- Don't expose ChromaDB directly to the internet; use a reverse proxy
- Use separate tenants/databases for multi-tenant applications
- Regular backups of persistent storage directory
- **Versions 1.0.0-1.0.10**: No native auth - requires proxy-based authentication (nginx, traefik)
- **StatefulSets for Kubernetes**: Retain state even when pods are deleted/restarted
- **Enterprise features**: BYOC (Bring Your Own Cloud), multi-region replication, point-in-time recovery

### Backup
```bash
# Simple backup - copy the persistence directory
cp -r ./chroma_db ./chroma_db_backup_$(date +%Y%m%d)

# For production: implement scheduled backups with encryption
tar -czf - ./chroma_db | gpg --encrypt -r backup@yourdomain.com > chroma_backup_$(date +%Y%m%d).tar.gz.gpg
```

---

## PostgreSQL (v16)

### Setup
```python
# asyncpg for async FastAPI applications
import asyncpg
from contextlib import asynccontextmanager
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

# asyncpg direct connection
DATABASE_URL = "postgresql://user:pass@localhost:5432/dbname"

@asynccontextmanager
async def get_db_pool():
    pool = await asyncpg.create_pool(
        DATABASE_URL,
        min_size=5,
        max_size=20,
        command_timeout=60,
        statement_cache_size=0  # Required for PgBouncer transaction mode
    )
    try:
        yield pool
    finally:
        await pool.close()

# SQLAlchemy async configuration
ASYNC_DATABASE_URL = "postgresql+asyncpg://user:pass@localhost/dbname"

engine = create_async_engine(
    ASYNC_DATABASE_URL,
    pool_size=10,          # Base pool connections
    max_overflow=20,       # Additional connections under load (total 30)
    pool_pre_ping=True,    # Verify connections before use
    pool_recycle=3600,     # Recycle connections after 1 hour
)

AsyncSessionLocal = sessionmaker(
    engine, class_=AsyncSession, expire_on_commit=False
)

async def get_db():
    async with AsyncSessionLocal() as session:
        yield session
```

### Best Practices

#### Schema Design & Indexing
```sql
-- B-tree indexes for equality and range queries (most common)
CREATE INDEX idx_users_email ON users(email);

-- Partial indexes for specific subsets - smaller and faster (275x improvement possible)
CREATE INDEX idx_active_users ON users(created_at)
    WHERE status = 'active';

-- Covering indexes - avoid table lookups entirely
CREATE INDEX idx_users_covering ON users(email) INCLUDE (name, created_at);

-- Expression indexes for computed values
CREATE INDEX idx_users_lower_email ON users(LOWER(email));

-- GIN indexes for JSONB columns and full-text search
CREATE INDEX idx_data_gin ON documents USING GIN (metadata jsonb_path_ops);
CREATE INDEX idx_posts_content ON posts USING GIN(to_tsvector('english', content));

-- Multi-column indexes for filter queries (column order matters!)
-- Put equality conditions first, then range conditions
CREATE INDEX idx_orders_user_date ON orders(user_id, created_at DESC);

-- Build indexes without locking writes (CRITICAL for production)
CREATE INDEX CONCURRENTLY idx_large_table ON large_table(column);

-- Hash indexes for equality-only lookups (faster than B-tree for =)
CREATE INDEX idx_users_uuid ON users USING hash(uuid);

-- BRIN indexes for large naturally ordered tables (small, fast inserts)
CREATE INDEX idx_logs_timestamp ON logs USING brin(created_at);

-- Use appropriate data types
CREATE TABLE users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email VARCHAR(255) NOT NULL UNIQUE,
    password_hash VARCHAR(255) NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW(),  -- Always use TIMESTAMPTZ, not TIMESTAMP
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Add constraints for data integrity
ALTER TABLE orders ADD CONSTRAINT positive_amount CHECK (amount > 0);
```

#### Connection Management
```python
# PgBouncer configuration for production
# Each PostgreSQL connection consumes ~10MB RAM
# Rule of thumb: ~400 connections per GB of RAM

# pool_mode options:
# - transaction: best for web apps, releases connection after transaction
# - session: needed for prepared statements, advisory locks, listen/notify
# - statement: most restrictive, releases after each statement

# PgBouncer config example (pgbouncer.ini)
"""
[databases]
mydb = host=127.0.0.1 port=5432 dbname=mydb

[pgbouncer]
listen_addr = 127.0.0.1
listen_port = 6432
auth_type = scram-sha-256
pool_mode = transaction
max_client_conn = 1000
default_pool_size = 25
reserve_pool_size = 5
reserve_pool_timeout = 3
"""

# IMPORTANT: When using PgBouncer in transaction/statement mode:
# - Prepared statements are NOT supported
# - Use statement_cache_size=0 or prepare=False with asyncpg
```

#### Performance Optimization
```sql
-- Run ANALYZE after bulk data changes to update statistics
ANALYZE users;

-- Keep planner statistics fresh
VACUUM ANALYZE;

-- Monitor index usage - identify unused indexes
SELECT
    schemaname, tablename, indexname, idx_scan,
    pg_size_pretty(pg_relation_size(indexrelid)) as index_size
FROM pg_stat_user_indexes
WHERE idx_scan = 0 AND indexrelid NOT IN (
    SELECT conindid FROM pg_constraint
)
ORDER BY pg_relation_size(indexrelid) DESC;

-- Find slow queries
SELECT query, calls, mean_exec_time, total_exec_time
FROM pg_stat_statements
ORDER BY mean_exec_time DESC
LIMIT 10;

-- Always use EXPLAIN ANALYZE before optimization
EXPLAIN ANALYZE SELECT * FROM users WHERE email = 'test@example.com';

-- Table partitioning for large tables (PostgreSQL 16+)
CREATE TABLE orders (
    id BIGSERIAL,
    created_at TIMESTAMPTZ NOT NULL,
    user_id INT NOT NULL,
    amount DECIMAL(10,2)
) PARTITION BY RANGE (created_at);

CREATE TABLE orders_2026_01 PARTITION OF orders
    FOR VALUES FROM ('2026-01-01') TO ('2026-02-01');
```

### Pitfalls
- **Not using connection pooling**: Direct connections don't scale; always use PgBouncer or pgpool-II in production
- **Over-indexing**: Each index adds write overhead (typically 5-10%); only index columns used in WHERE/JOIN/ORDER BY
- **Ignoring VACUUM/ANALYZE**: Run regularly to keep planner statistics fresh and reclaim dead tuple space
- **Storing secrets in code**: Use environment variables or secrets manager
- **N+1 queries**: Use JOINs or batch queries; never loop single queries in application code
- **Wrong column order in composite indexes**: Most selective column first, equality before range
- **Not using EXPLAIN ANALYZE**: Always analyze query plans before optimization
- **Using TIMESTAMP**: Always use TIMESTAMPTZ for timezone safety
- **Synchronous in Async**: Using psycopg2 instead of asyncpg in async applications

### Security
```sql
-- Use SCRAM-SHA-256 authentication (MD5 is deprecated)
-- In pg_hba.conf:
hostssl all all 0.0.0.0/0 scram-sha-256

-- Disable trust method in production
-- NEVER use: host all all 0.0.0.0/0 trust

-- Set specific listen_addresses (postgresql.conf)
listen_addresses = '10.0.0.1,10.0.0.2'  -- NOT '*'

-- Enable SSL/TLS
-- In postgresql.conf:
ssl = on
ssl_cert_file = 'server.crt'
ssl_key_file = 'server.key'
ssl_min_protocol_version = 'TLSv1.2'

-- Row-level security
ALTER TABLE documents ENABLE ROW LEVEL SECURITY;
CREATE POLICY documents_user_policy ON documents
    FOR ALL TO app_user
    USING (user_id = current_setting('app.current_user_id')::int);

-- Application role separation
CREATE ROLE app_readonly;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO app_readonly;

CREATE ROLE app_readwrite;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO app_readwrite;

-- Create application-specific users with minimal privileges
CREATE USER app_user WITH PASSWORD 'secure_password';
GRANT SELECT, INSERT, UPDATE ON ALL TABLES IN SCHEMA public TO app_user;
REVOKE DELETE ON sensitive_table FROM app_user;
```

### Auditing
```sql
-- Enable pgaudit extension
CREATE EXTENSION pgaudit;

-- Log all DDL and write operations
ALTER SYSTEM SET pgaudit.log = 'ddl, write';
SELECT pg_reload_conf();

-- Column-level encryption using pgcrypto (for sensitive fields)
CREATE EXTENSION pgcrypto;

INSERT INTO users (email, ssn_encrypted)
VALUES ('user@example.com', pgp_sym_encrypt('123-45-6789', 'secret_key'));

SELECT email, pgp_sym_decrypt(ssn_encrypted::bytea, 'secret_key')
FROM users WHERE id = 1;

-- Key management: Use HSM or dedicated key management for encryption keys
```

### Backup (3-2-1 Rule)
```bash
# 3 copies, 2 different media types, 1 offsite

# pg_dump for logical backups (single database)
pg_dump -h localhost -U user -d dbname -F c -f backup.dump

# pg_basebackup with compression (PostgreSQL 16+ - physical backup)
pg_basebackup -h localhost -U replication_user -D /backup \
    --compress=lz4 --manifest --manifest-checksums

# Point-in-Time Recovery (PITR) setup
# In postgresql.conf:
archive_mode = on
archive_command = 'cp %p /archive/%f'
# Or for S3: 'aws s3 cp %p s3://bucket/wal/%f'

# Restore
pg_restore -h localhost -U user -d dbname backup.dump

# Enterprise tools for production:
# - pgBackRest: incremental backups, parallelism, encryption
# - Barman: centralized backup management
# - WAL-G: cloud-native, S3/GCS integration

# CRITICAL: Test restoration regularly!
```

---

## Redis (v7)

### Setup

**Important (2026)**: TLS is mandatory in production - adds ~5-10% overhead but is a security requirement. Redis has no authentication by default and listens on all interfaces.

```python
import redis.asyncio as aioredis
from redis.asyncio.connection import ConnectionPool

# Async connection pool for FastAPI
pool = ConnectionPool.from_url(
    "redis://localhost:6379/0",
    max_connections=20,
    decode_responses=True,
    socket_timeout=5.0,
    socket_connect_timeout=5.0,
    retry_on_timeout=True
)

async def get_redis():
    return aioredis.Redis(connection_pool=pool)

# With SSL/TLS (production)
pool = ConnectionPool.from_url(
    "rediss://user:password@redis.yourdomain.com:6379/0",  # Note: rediss:// for SSL
    max_connections=20,
    ssl_cert_reqs="required",
    ssl_ca_certs="/path/to/ca.crt"
)

# FastAPI lifespan integration
@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.redis = await aioredis.from_url("redis://localhost")
    yield
    await app.state.redis.close()

# Always close connections explicitly in async context
async def shutdown():
    await pool.disconnect()
```

### Best Practices

#### Data Structure Selection
```python
# String: simple key-value, counters
await redis.set("user:1001:session", session_token, ex=3600)

# Hash: objects with multiple fields (MORE MEMORY EFFICIENT than multiple strings)
# A hash with 10 fields is more memory-efficient than 10 separate string keys
await redis.hset("user:1001", mapping={
    "name": "John",
    "email": "john@example.com",
    "role": "admin"
})
await redis.expire("user:1001", 3600)

# List: ordered collection, queues
await redis.lpush("task:queue", json.dumps(task))
task = await redis.rpop("task:queue")

# Set: unique values, membership testing
await redis.sadd("online:users", user_id)
is_online = await redis.sismember("online:users", user_id)

# Sorted Set: ranked data, leaderboards, time-series
await redis.zadd("leaderboard", {user_id: score})
top_10 = await redis.zrevrange("leaderboard", 0, 9, withscores=True)

# Stream: event sourcing, message queues (Redis 5+)
await redis.xadd("events", {"type": "user.created", "data": json.dumps(data)})
```

#### Caching Patterns
```python
import json
from datetime import timedelta

# Cache-Aside (Lazy Loading) - Most common pattern
# Can reduce database load by 80-95% for read-heavy workloads
async def get_user(user_id: str, redis_client, db):
    cache_key = f"user:{user_id}"

    # Try cache first
    cached = await redis_client.get(cache_key)
    if cached:
        return json.loads(cached)

    # Cache miss - query database
    user = await db.fetch_user(user_id)
    if user:
        await redis_client.setex(
            cache_key,
            timedelta(hours=1),  # TTL - ALWAYS set expiration
            json.dumps(user)
        )
    return user

# Write-Through - Cache and DB updated together (strong consistency)
async def update_user(user_id: str, data: dict, redis_client, db):
    # Update database first
    await db.update_user(user_id, data)
    # Then update cache
    await redis_client.setex(
        f"user:{user_id}",
        timedelta(hours=1),
        json.dumps(data)
    )

# Cache invalidation on update
async def invalidate_user_cache(user_id: str, redis_client):
    await redis_client.delete(f"user:{user_id}")

# Key naming convention: objectType:objectId:field
# Examples: user:1001:profile, session:abc123, cache:api:users:list, rate:limit:user:1001
```

#### TTL & Memory Management
```python
# ALWAYS set TTL for cache keys - keys without TTL accumulate forever
await redis.setex("cache:key", 3600, "value")  # 1 hour TTL

# Use SCAN instead of KEYS for production (KEYS blocks server!)
async def find_keys(pattern: str, redis_client):
    keys = []
    async for key in redis_client.scan_iter(match=pattern, count=100):
        keys.append(key)
    return keys

# Pipeline for batch operations - reduces round trips dramatically
async with redis_client.pipeline() as pipe:
    for key, value in items:
        pipe.setex(key, 3600, value)
    await pipe.execute()

# Memory configuration (redis.conf)
# maxmemory 2gb
# maxmemory-policy allkeys-lru  # Evict any key using LRU for caching
```

#### Redis 7 Features
```python
# Client-side caching (Redis 7+)
# Reduces network round-trips by caching on client

# Hash field expiration (Redis 7.4+)
await redis.hset("user:1001", "session", "abc123")
await redis.hexpire("user:1001", 3600, "session")  # Expire specific field

# Sharded Pub/Sub (Redis 7+) - better scalability
await redis.spublish("channel{shard1}", "message")
```

### Pitfalls
- **Using KEYS command**: Blocks Redis; use `SCAN` instead
- **No TTL**: Keys without expiration accumulate forever - memory grows unbounded
- **Large values**: Redis optimized for many small values (<100KB); chunk large data
- **Hot keys**: Single popular key causes thundering herd on expiration
- **Using as Primary Storage**: Redis is a cache, not a database of record
- **Wildcard deletions**: `DEL user:*` blocks Redis - use SCAN with incremental deletes
- **Multiple databases**: Use separate Redis instances instead of numbered DBs (Redis author called this "worst design mistake")
- **Very short TTLs**: Frequent eviction and re-computation is costly
- **Ignoring connection pooling**: Each connection has overhead; reuse connections
- **Storing sensitive data without encryption**: Redis stores data in memory; use application-level encryption
- **Persistence doubling memory**: When snapshotting, Redis needs to store changes aside

### Security
```python
# Redis 7 ACL configuration (RECOMMENDED over password-only auth)
# Redis 6+ ACLs allow fine-grained permissions per user
# In redis.conf or ACL file:
"""
# Syntax: user <name> on|off [>password] [~key-patterns] [+commands|-commands]
user app_user on >strong_password ~cache:* ~session:* +get +set +del +expire
user readonly_user on >password ~* +@read -@write
user default off  # Disable default user - CRITICAL for security
"""

# Connect with ACL user
redis_client = await aioredis.from_url(
    "redis://app_user:secure_password@localhost:6379"
)

# Dangerous commands to disable or rename
# In redis.conf:
"""
rename-command FLUSHDB ""
rename-command FLUSHALL ""
rename-command CONFIG "CONFIG_a8f9d2e3"
rename-command SHUTDOWN ""
rename-command KEYS ""
"""

# SSL/TLS connection (production required)
redis_client = aioredis.Redis(
    host='redis.yourdomain.com',
    port=6379,
    ssl=True,
    ssl_cert_reqs='required',
    ssl_ca_certs='/path/to/ca.crt',
    password='strong_password'
)

# Network security
# - NEVER expose Redis directly to internet
# - Deploy behind firewall, use private subnets in cloud
# - Enable authentication (requirepass or ACLs)
# - Use VPN for cross-network access
```

### Backup & Persistence
```bash
# RDB snapshot (default) - faster recovery, possible data loss between snapshots
# In redis.conf:
save 900 1      # Save after 900 sec if at least 1 key changed
save 300 10     # Save after 300 sec if at least 10 keys changed
save 60 10000   # Save after 60 sec if at least 10000 keys changed

# AOF (Append Only File) - more durable, larger files
appendonly yes
appendfsync everysec  # fsync every second (good balance)
# Options: always (safest, slowest), everysec (recommended), no (OS decides)

# Hybrid persistence (Redis 7+) - best of both
aof-use-rdb-preamble yes

# Backup the dump.rdb or appendonly.aof file
cp /var/lib/redis/dump.rdb /backup/redis_$(date +%Y%m%d).rdb

# For HA: Redis Sentinel or Redis Cluster
```

---

## Python (3.11+)

### Project Structure (src layout RECOMMENDED)
```
project/
├── pyproject.toml
├── README.md
├── LICENSE
├── .env.example
├── .pre-commit-config.yaml
├── src/
│   └── mypackage/
│       ├── __init__.py
│       ├── api/
│       │   ├── __init__.py
│       │   ├── routes/
│       │   └── dependencies.py
│       ├── core/
│       │   ├── __init__.py
│       │   ├── config.py
│       │   └── security.py
│       ├── models/
│       │   ├── __init__.py
│       │   └── schemas.py
│       ├── services/
│       │   └── __init__.py
│       └── repositories/
│           └── __init__.py
├── tests/
│   ├── __init__.py
│   ├── conftest.py
│   ├── unit/
│   ├── integration/
│   └── contract/
└── docker/
    └── Dockerfile
```

**Why src layout?** If your package lives in `src/`, it won't be added to Python path by default, forcing imports to use the installed package. This prevents accidentally importing local files and keeps wheel/dist files clean.

### Setup & Tooling (2026 Recommendations)
```toml
# pyproject.toml - Standard for all modern Python projects
[project]
name = "super-team"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
    "fastapi>=0.129.0",
    "uvicorn[standard]>=0.30.0",
    "pydantic>=2.0.0",
    "asyncpg>=0.29.0",
    "redis>=5.0.0",
    "chromadb>=1.5.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0.0",
    "pytest-asyncio>=0.23.0",
    "mypy>=1.10.0",
    "ruff>=0.4.0",
    "pre-commit>=3.7.0",
]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/mypackage"]

[tool.ruff]
line-length = 100
target-version = "py311"

[tool.ruff.lint]
select = ["E", "F", "I", "N", "W", "UP", "B", "C4", "SIM"]

[tool.mypy]
python_version = "3.11"
strict = true
warn_return_any = true
disallow_untyped_defs = true
```

```bash
# uv commands (preferred for speed - Rust-based)
uv pip install -r requirements.txt
uv pip compile requirements.in -o requirements.txt
uv venv && source .venv/bin/activate

# poetry commands (comprehensive management)
poetry install
poetry add fastapi
poetry lock

# Commit lock files to version control for reproducible builds
```

### Best Practices

#### Type Hints (Python 3.10+)
```python
# Use built-in generics (Python 3.9+) - no import needed
def process_items(items: list[str]) -> dict[str, int]:
    return {item: len(item) for item in items}

# Union syntax with | (Python 3.10+)
def get_user(user_id: int) -> User | None:
    pass

# Type aliases (Python 3.12+)
type UserId = int
type UserMap = dict[UserId, User]

# TypedDict for structured dictionaries
from typing import TypedDict, Required, NotRequired

class UserDict(TypedDict):
    id: Required[int]
    name: Required[str]
    email: NotRequired[str | None]

# Protocol for structural typing (duck typing with types)
from typing import Protocol, runtime_checkable

@runtime_checkable
class Repository(Protocol):
    async def get(self, id: str) -> dict | None: ...
    async def save(self, data: dict) -> str: ...

# Generic types
from typing import TypeVar, Generic

T = TypeVar('T')

class Result(Generic[T]):
    def __init__(self, value: T | None, error: str | None = None):
        self.value = value
        self.error = error

    def is_ok(self) -> bool:
        return self.error is None

# Use object instead of Any when accepting anything
def log_value(value: object) -> None:
    print(value)

# ParamSpec for decorator typing (Python 3.10+)
from typing import ParamSpec, Callable, TypeVar

P = ParamSpec('P')
R = TypeVar('R')

def retry(times: int) -> Callable[[Callable[P, R]], Callable[P, R]]:
    def decorator(func: Callable[P, R]) -> Callable[P, R]:
        async def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
            for _ in range(times):
                try:
                    return await func(*args, **kwargs)
                except Exception:
                    pass
            raise Exception("Retry failed")
        return wrapper
    return decorator
```

#### Async Patterns
```python
import asyncio
from typing import AsyncIterator
from contextlib import asynccontextmanager

# Async context manager
class AsyncDatabaseConnection:
    async def __aenter__(self):
        self.conn = await create_connection()
        return self.conn

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.conn.close()

# Or using decorator
@asynccontextmanager
async def get_connection():
    conn = await create_connection()
    try:
        yield conn
    finally:
        await conn.close()

# Async generator
async def stream_results(query: str) -> AsyncIterator[dict]:
    async for row in db.execute_stream(query):
        yield dict(row)

# Concurrent execution with gather
async def fetch_all_data():
    results = await asyncio.gather(
        fetch_users(),
        fetch_orders(),
        fetch_products(),
        return_exceptions=True  # Don't fail all on single exception
    )
    # Filter out exceptions
    return [r for r in results if not isinstance(r, Exception)]

# Timeout handling (Python 3.11+)
async def fetch_with_timeout(url: str, timeout: float = 5.0):
    try:
        async with asyncio.timeout(timeout):
            return await fetch(url)
    except asyncio.TimeoutError:
        return None

# TaskGroup for structured concurrency (Python 3.11+)
async def process_urls(urls: list[str]):
    results = []
    async with asyncio.TaskGroup() as tg:
        tasks = [tg.create_task(fetch(url)) for url in urls]
    return [task.result() for task in tasks]

# Semaphore for rate limiting
async def fetch_with_limit(urls: list[str], max_concurrent: int = 10):
    semaphore = asyncio.Semaphore(max_concurrent)

    async def fetch_one(url: str):
        async with semaphore:
            return await fetch(url)

    return await asyncio.gather(*[fetch_one(url) for url in urls])
```

### Pitfalls
- **Mutable default arguments**: Use `None` default with conditional initialization
  ```python
  # BAD
  def append_item(item, items=[]):
      items.append(item)  # Same list reused across calls!

  # GOOD
  def append_item(item, items: list | None = None):
      if items is None:
          items = []
      items.append(item)
      return items
  ```
- **Late binding closures**: Variables captured by reference, not value
  ```python
  # BAD - all return 2
  funcs = [lambda: i for i in range(3)]

  # GOOD - capture value with default argument
  funcs = [lambda i=i: i for i in range(3)]
  ```
- **Blocking in async**: Using `time.sleep()` or `requests` in async code
- **Missing type narrowing**: Check for `None` before using optional values
- **Forgetting to await**: Unawaited coroutines don't execute
- **Using uppercase typing imports**: Use `list[int]` not `List[int]` for Python 3.9+
- **No type checking in CI**: Always run mypy in your CI pipeline
- **Ignoring pre-commit hooks**: Use pre-commit for formatting, linting, type checking
- **Not pinning dependencies**: Use lockfiles (poetry.lock, requirements.txt with hashes)

### Security
```python
import secrets
import os
from pathlib import Path

# Use secrets module for cryptographic randomness, not random
api_key = secrets.token_urlsafe(32)
csrf_token = secrets.token_hex(16)

# Environment variables for configuration
DATABASE_URL = os.environ["DATABASE_URL"]  # Will raise if not set
DEBUG = os.getenv("DEBUG", "false").lower() == "true"

# Never commit .env files or credentials
# Use .gitignore and secrets managers

# Dependency auditing
# pip-audit --requirement requirements.txt
# safety check -r requirements.txt

# Security linting with bandit
# bandit -r src/
```

---

## Pact (Contract Testing)

### Setup
```python
# pyproject.toml dependencies
[project.optional-dependencies]
test = [
    "pact-python>=2.1.0",
    "pytest>=8.0.0",
    "pytest-asyncio>=0.23.0",
]

# Directory structure
tests/
├── contract/
│   ├── consumer/
│   │   └── test_user_service_consumer.py
│   └── provider/
│       └── test_user_service_provider.py
├── pacts/
│   └── consumer-provider.json
└── conftest.py
```

### Best Practices

#### Consumer Tests
```python
import pytest
from pact import Consumer, Provider, Like, EachLike, Term, Format

@pytest.fixture
def pact():
    pact = Consumer('UserClient').has_pact_with(
        Provider('UserService'),
        pact_dir='./pacts',
        version='4.0'  # Use Pact V4 specification
    )
    pact.start_service()
    yield pact
    pact.stop_service()

def test_get_user(pact):
    # Define expected interaction using matchers (not exact values!)
    expected = {
        "id": Like(1),  # Type matching - any integer
        "name": Like("John"),  # Type matching - any string
        "email": Term(r'.+@.+\..+', 'test@example.com'),  # Regex pattern
        "uuid": Format().uuid,  # UUID format
        "roles": EachLike("admin", minimum=1),  # Array with at least 1 item
        "created_at": Format().iso_8601_datetime  # ISO datetime
    }

    (pact
        .given('a user with ID 1 exists')  # Provider state
        .upon_receiving('a request for user 1')
        .with_request('GET', '/users/1', headers={'Accept': 'application/json'})
        .will_respond_with(200, body=expected, headers={'Content-Type': 'application/json'}))

    with pact:
        result = client.get_user(1)
        assert result['id'] == 1

# Test error scenarios (IMPORTANT!)
def test_get_user_not_found(pact):
    (pact
        .given('no users exist')
        .upon_receiving('a request for non-existent user')
        .with_request('GET', '/users/999')
        .will_respond_with(404, body={"error": Like("Not found")}))

    with pact:
        with pytest.raises(UserNotFoundError):
            client.get_user(999)

# For collections
def test_get_users(pact):
    expected = EachLike({
        "id": Like(1),
        "name": Like("John")
    }, minimum=1)

    (pact
        .upon_receiving('a request for all users')
        .with_request('GET', '/users')
        .will_respond_with(200, body=expected))
```

#### Provider Verification
```python
from pact import Verifier
import pytest
from fastapi.testclient import TestClient

@pytest.fixture
def provider_app():
    """Set up the provider application with test data"""
    app = create_test_app()
    return app

def test_provider_against_pacts(provider_app):
    verifier = Verifier(
        provider='UserService',
        provider_base_url='http://localhost:8000'
    )

    # Set up provider states endpoint
    verifier.set_state(
        'http://localhost:8000/_pact/states',
        teardown=True
    )

    # Verify against all consumer pacts
    output, _ = verifier.verify_pacts(
        './pacts/',
        enable_pending=True,  # Allow WIP pacts
        publish_version='1.0.0',
        publish_verification_results=True,
        provider_tags=['main', 'ci']
    )
    assert output == 0

# Provider state handler in FastAPI
@app.post("/_pact/states")
async def handle_provider_state(request: dict):
    state = request.get("state")
    action = request.get("action", "setup")

    if state == "a user with ID 1 exists":
        if action == "setup":
            await db.create_user(id=1, name="Test User")
        else:  # teardown
            await db.delete_user(id=1)

    return {"status": "ok"}
```

#### Async/Message Testing (Pact v3+)
```python
from pact import MessageConsumer, MessageProvider
from pact.v3 import Pact

# Consumer side - define expected message shape
def test_message_consumer():
    consumer = MessageConsumer('OrderProcessor')
    pact = consumer.has_pact_with(
        MessageProvider('OrderService'),
        pact_dir='./pacts'
    )

    expected = {
        "orderId": Like("order-123"),
        "status": Term(r'created|paid|shipped', 'created'),
        "items": EachLike({"sku": Like("ABC123"), "quantity": Like(1)})
    }

    (pact
        .given('an order is created')
        .expects_to_receive('order created event')
        .with_content(expected)
        .with_metadata({'contentType': 'application/json'}))

    with pact:
        message = pact.receive()
        result = process_order_event(message)
        assert result is not None

# Async handler function
def message_handler(message: bytes) -> None:
    data = json.loads(message)
    process_user_created_event(data)
```

### Pitfalls
- **Over-specifying contracts**: Don't require exact JSON formatting or field order; focus on what the consumer actually needs. Use matchers!
- **Testing only happy path**: Add provider states for error scenarios (404, 500, validation errors, timeouts)
- **Exact value matching**: Use matchers (Like, EachLike, Term) instead of exact values
- **Vague or incomplete contracts**: Always specify required fields, data types, and validation rules
- **Not testing resilience**: Contract tests verify shape, not retry logic or circuit breakers
- **Ignoring version coordination**: Use Pact Broker for managing contract versions across environments
- **Large contracts**: Keep contracts focused on specific interactions
- **Missing CI/CD**: Automate verification on every build
- **Not running can-i-deploy**: Always check deployment compatibility before deploying

### Security
- Store Pact Broker credentials as CI/CD secrets
- Use authentication for Pact Broker in CI/CD
- Don't include sensitive data in pact files (use matchers instead)
- Version contracts with semantic versioning

### CI/CD Integration
```yaml
# GitHub Actions example
name: Contract Tests

on: [push, pull_request]

jobs:
  consumer-tests:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Run Consumer Tests
        run: pytest tests/contract/consumer/

      - name: Publish Pacts
        run: |
          pact-broker publish ./pacts \
            --broker-base-url=${{ secrets.PACT_BROKER_URL }} \
            --broker-token=${{ secrets.PACT_BROKER_TOKEN }} \
            --consumer-app-version=${{ github.sha }} \
            --tag=${{ github.ref_name }} \
            --tag-with-git-branch

  provider-verification:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Verify Provider
        run: pytest tests/contract/provider/

      - name: Can I Deploy?
        run: |
          pact-broker can-i-deploy \
            --pacticipant=UserService \
            --version=${{ github.sha }} \
            --to-environment=production
```

---

## Integration Patterns

### FastAPI + PostgreSQL + Redis + ChromaDB Stack
```python
from fastapi import FastAPI, Depends, Request
from contextlib import asynccontextmanager
import asyncpg
import redis.asyncio as aioredis
import chromadb
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Initialize all connections
    app.state.db_engine = create_async_engine(DATABASE_URL, pool_size=10)
    app.state.redis = await aioredis.from_url(REDIS_URL)
    app.state.chroma = chromadb.HttpClient(host=CHROMA_HOST, port=8000)

    yield

    # Cleanup
    await app.state.db_engine.dispose()
    await app.state.redis.close()

app = FastAPI(lifespan=lifespan)

# Dependency injection
async def get_db(request: Request) -> AsyncSession:
    async with AsyncSession(request.app.state.db_engine) as session:
        yield session

async def get_redis(request: Request) -> aioredis.Redis:
    return request.app.state.redis

def get_chroma(request: Request) -> chromadb.HttpClient:
    return request.app.state.chroma
```

### Cache-Aside with Redis + PostgreSQL
```python
class UserService:
    def __init__(self, db: AsyncSession, redis: aioredis.Redis):
        self.db = db
        self.redis = redis
        self.cache_ttl = 3600

    async def get_user(self, user_id: str) -> User | None:
        # Try cache
        cache_key = f"user:{user_id}"
        cached = await self.redis.get(cache_key)
        if cached:
            return User.model_validate_json(cached)

        # Fetch from DB
        result = await self.db.execute(
            select(UserModel).where(UserModel.id == user_id)
        )
        user_model = result.scalar_one_or_none()

        if user_model:
            user = User.model_validate(user_model)
            await self.redis.setex(
                cache_key,
                self.cache_ttl,
                user.model_dump_json()
            )
            return user

        return None

    async def invalidate_user_cache(self, user_id: str) -> None:
        await self.redis.delete(f"user:{user_id}")
```

### Vector Search with ChromaDB
```python
from concurrent.futures import ThreadPoolExecutor
import asyncio

executor = ThreadPoolExecutor(max_workers=4)

class DocumentService:
    def __init__(self, chroma: chromadb.HttpClient, embedding_model):
        self.chroma = chroma
        self.embedding_model = embedding_model
        self.collection = chroma.get_or_create_collection(
            name="documents",
            metadata={"hnsw:space": "cosine"}
        )

    async def add_document(self, doc_id: str, content: str, metadata: dict):
        loop = asyncio.get_event_loop()
        embedding = await loop.run_in_executor(
            executor,
            lambda: self.embedding_model.encode(content).tolist()
        )
        await loop.run_in_executor(
            executor,
            lambda: self.collection.add(
                ids=[doc_id],
                embeddings=[embedding],
                documents=[content],
                metadatas=[metadata]
            )
        )

    async def search(self, query: str, n_results: int = 10) -> list[dict]:
        loop = asyncio.get_event_loop()
        query_embedding = await loop.run_in_executor(
            executor,
            lambda: self.embedding_model.encode(query).tolist()
        )
        results = await loop.run_in_executor(
            executor,
            lambda: self.collection.query(
                query_embeddings=[query_embedding],
                n_results=n_results,
                include=["documents", "metadatas", "distances"]
            )
        )
        return [
            {
                "id": results["ids"][0][i],
                "document": results["documents"][0][i],
                "metadata": results["metadatas"][0][i],
                "distance": results["distances"][0][i]
            }
            for i in range(len(results["ids"][0]))
        ]
```

---

## Quick Reference Checklist

### Pre-Production Checklist

- [ ] **FastAPI**: Middleware order correct, request ID tracking, proper error responses, rate limiting
- [ ] **FastAPI**: All async endpoints use async drivers (asyncpg, aioredis, httpx)
- [ ] **FastAPI**: Response models separate from request models
- [ ] **FastAPI**: API docs disabled or protected in production
- [ ] **PostgreSQL**: PgBouncer configured, indexes optimized and created CONCURRENTLY
- [ ] **PostgreSQL**: SCRAM-SHA-256 auth, SSL enabled, PITR configured
- [ ] **PostgreSQL**: Database backups scheduled and restoration tested
- [ ] **Redis**: TTL on ALL cache keys, connection pooling configured
- [ ] **Redis**: ACLs configured, TLS enabled, dangerous commands disabled
- [ ] **Redis**: Persistence configured appropriately (RDB/AOF/hybrid)
- [ ] **ChromaDB**: Using HTTP client (not ephemeral), persistence configured
- [ ] **ChromaDB**: Embedding function explicitly specified, batch operations used
- [ ] **Python**: Type hints complete, mypy passing, ruff linting clean
- [ ] **Python**: Async patterns correct (no blocking in async)
- [ ] **Pact**: Consumer and provider tests, CI/CD integration, Pact Broker setup
- [ ] **Pact**: can-i-deploy gate configured
- [ ] **Security**: All secrets in environment variables
- [ ] **Security**: HTTPS enabled, CORS configured for specific origins only
- [ ] **Monitoring**: Request logging with IDs, error tracking, performance metrics
- [ ] **Monitoring**: Health check endpoints implemented

---

## Sources

### FastAPI
- [FastAPI Official Documentation - Middleware](https://fastapi.tiangolo.com/tutorial/middleware/)
- [FastAPI Official Documentation - Handling Errors](https://fastapi.tiangolo.com/tutorial/handling-errors/)
- [FastAPI Official Documentation - Security](https://fastapi.tiangolo.com/tutorial/security/)
- [FastAPI Official Documentation - Lifespan Events](https://fastapi.tiangolo.com/advanced/events/)
- [FastAPI Best Practices for Production 2026](https://fastlaunchapi.dev/blog/fastapi-best-practices-production-2026)
- [FastAPI Best Practices GitHub](https://github.com/zhanymkanov/fastapi-best-practices)
- [FastAPI Middleware Patterns 2026](https://johal.in/fastapi-middleware-patterns-custom-logging-metrics-and-error-handling-2026-2/)
- [FastAPI Error Handling Patterns](https://betterstack.com/community/guides/scaling-python/error-handling-fastapi/)
- [Authentication and Authorization with FastAPI](https://betterstack.com/community/guides/scaling-python/authentication-fastapi/)
- [12 FastAPI Anti-Patterns Killing Throughput](https://medium.com/@Modexa/12-fastapi-anti-patterns-quietly-killing-throughput-bddaa961634a)

### ChromaDB
- [ChromaDB Official Documentation](https://www.trychroma.com/)
- [ChromaDB Cookbook - Running Chroma](https://cookbook.chromadb.dev/running/running-chroma/)
- [ChromaDB FAQ](https://cookbook.chromadb.dev/faq/)
- [Introduction to ChromaDB 2026](https://thelinuxcode.com/introduction-to-chromadb-2026-a-practical-docsfirst-guide-to-semantic-search/)
- [Embeddings and Vector Databases With ChromaDB](https://realpython.com/chromadb-vector-database/)
- [Common Pitfalls in Vector Databases](https://dagshub.com/blog/common-pitfalls-to-avoid-when-using-vector-databases/)

### PostgreSQL
- [PostgreSQL Official Documentation - Indexes](https://www.postgresql.org/docs/current/indexes.html)
- [PostgreSQL Indexing Playbook 2026](https://www.sachith.co.uk/postgresql-indexing-playbook-practical-guide-feb-12-2026/)
- [PostgreSQL Database Security Best Practices](https://www.percona.com/blog/postgresql-database-security-best-practices/)
- [PostgreSQL Security Hardening](https://www.percona.com/blog/postgresql-database-security-what-you-need-to-know/)
- [Connection Pooling - SQLAlchemy Documentation](https://docs.sqlalchemy.org/en/20/core/pooling.html)
- [asyncpg FAQ](https://magicstack.github.io/asyncpg/current/faq.html)

### Redis
- [Redis Official Security Documentation](https://redis.io/docs/latest/operate/oss_and_stack/management/security/)
- [Redis ACL Documentation](https://redis.io/docs/latest/operate/oss_and_stack/management/security/acl/)
- [Redis Best Practices](https://www.dragonflydb.io/guides/redis-best-practices)
- [Redis Caching Strategies 2026](https://miracl.in/blog/redis-caching-strategies-2026/)
- [Redis Anti-Patterns to Avoid](https://redis.io/tutorials/redis-anti-patterns-every-developer-should-avoid/)
- [Database Caching Strategies Using Redis - AWS](https://docs.aws.amazon.com/whitepapers/latest/database-caching-strategies-using-redis/caching-patterns.html)
- [Securing Redis 7 Deployment](https://nextbrick.com/securing-your-redis-7-8-2-deployment-best-practices/)

### Python
- [Typing Best Practices - Python Documentation](https://typing.python.org/en/latest/reference/best_practices.html)
- [Python Type Hints Complete Guide 2026](https://devtoolbox.dedyn.io/blog/python-type-hints-complete-guide)
- [Python asyncio Complete Guide 2026](https://devtoolbox.dedyn.io/blog/python-asyncio-complete-guide)
- [Structuring Your Project - Hitchhiker's Guide](https://docs.python-guide.org/writing/structure/)
- [Python Project Structure Best Practices](https://dagster.io/blog/python-project-best-practices)
- [Python Packaging Best Practices 2026](https://dasroot.net/posts/2026/01/python-packaging-best-practices-setuptools-poetry-hatch/)

### Pact
- [Pact Python Documentation - Consumer](https://docs.pact.io/implementation_guides/python/docs/consumer)
- [Pact Python Documentation - Provider](https://docs.pact.io/implementation_guides/python/docs/provider)
- [Pact Python Examples](https://docs.pact.io/implementation_guides/python/examples)
- [Pact Python GitHub](https://github.com/pact-foundation/pact-python)
- [Asynchronous Message Support](https://pact-foundation.github.io/pact-python/blog/2024/07/26/asynchronous-message-support/)

---

*Research compiled from official documentation and authoritative sources. Context7 MCP tools were unavailable during this research phase; findings gathered via comprehensive web search of official documentation and authoritative sources. Always refer to the latest official documentation for the most current best practices.*

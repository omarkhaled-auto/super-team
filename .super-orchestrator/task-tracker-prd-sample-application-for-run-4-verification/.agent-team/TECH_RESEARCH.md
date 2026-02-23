# Tech Stack Research

## FastAPI (v0.129.0)

### Setup
- **Project Structure**: Use routers (APIRouter) to organize endpoints by domain/feature
- **Application Factory Pattern**:
```python
from fastapi import FastAPI

app = FastAPI(
    title="API Title",
    servers=[
        {"url": "https://stag.example.com", "description": "Staging"},
        {"url": "https://prod.example.com", "description": "Production"},
    ]
)
```
- **Database Initialization**: Use `@app.on_event("startup")` for table creation
```python
@app.on_event("startup")
def on_startup():
    create_db_and_tables()
```

### Best Practices

#### Dependency Injection with Annotated (Recommended for FastAPI 0.95.0+)
- Use `Annotated` for cleaner dependency injection:
```python
from typing import Annotated
from fastapi import Depends

SessionDep = Annotated[Session, Depends(get_session)]

@app.get("/items/")
def read_items(session: SessionDep):
    return session.exec(select(Item)).all()
```

#### Router Organization
- Apply shared dependencies, tags, and prefixes at router level:
```python
from fastapi import APIRouter, Depends

router = APIRouter(
    prefix="/items",
    tags=["items"],
    dependencies=[Depends(get_token_header)],
    responses={404: {"description": "Not found"}},
)
```
- Include routers with additional config in main app:
```python
app.include_router(
    admin.router,
    prefix="/admin",
    tags=["admin"],
    dependencies=[Depends(get_token_header)],
)
```

#### Middleware Patterns
- HTTP middleware for cross-cutting concerns:
```python
@app.middleware("http")
async def add_process_time_header(request: Request, call_next):
    start_time = time.perf_counter()
    response = await call_next(request)
    process_time = time.perf_counter() - start_time
    response.headers["X-Process-Time"] = str(process_time)
    return response
```
- Add CORS middleware:
```python
from fastapi.middleware.cors import CORSMiddleware

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure appropriately for production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

#### Background Tasks
- Use `BackgroundTasks` for non-blocking operations:
```python
from fastapi import BackgroundTasks

def write_notification(email: str, message=""):
    with open("log.txt", mode="w") as email_file:
        content = f"notification for {email}: {message}"
        email_file.write(content)

@app.post("/send-notification/{email}")
async def send_notification(email: str, background_tasks: BackgroundTasks):
    background_tasks.add_task(write_notification, email, message="notification")
    return {"message": "Notification sent in the background"}
```

#### Database Integration (SQLModel)
- Use separate models for Base, Create, Public, and Update operations:
```python
class HeroBase(SQLModel):
    name: str = Field(index=True)
    age: int | None = Field(default=None, index=True)

class Hero(HeroBase, table=True):
    id: int | None = Field(default=None, primary_key=True)
    secret_name: str

class HeroPublic(HeroBase):
    id: int

class HeroCreate(HeroBase):
    secret_name: str

class HeroUpdate(HeroBase):
    name: str | None = None
    age: int | None = None
    secret_name: str | None = None
```
- Session dependency with yield:
```python
def get_session():
    with Session(engine) as session:
        yield session
```
- SQLite connection args for async:
```python
connect_args = {"check_same_thread": False}
engine = create_engine(sqlite_url, connect_args=connect_args)
```

#### Query Parameter Validation
- Use `Query` with constraints:
```python
@app.get("/items/")
async def read_items(
    q: Annotated[str | None, Query(min_length=3, max_length=50, pattern="^fixedquery$")] = None,
):
    pass
```

#### Pagination Best Practice
```python
@app.get("/heroes/", response_model=list[HeroPublic])
def read_heroes(
    session: SessionDep,
    offset: int = 0,
    limit: Annotated[int, Query(le=100)] = 100,  # Max 100 items
):
    heroes = session.exec(select(Hero).offset(offset).limit(limit)).all()
    return heroes
```

#### PATCH with exclude_unset
```python
@app.patch("/heroes/{hero_id}", response_model=HeroPublic)
def update_hero(hero_id: int, hero: HeroUpdate, session: SessionDep):
    hero_db = session.get(Hero, hero_id)
    if not hero_db:
        raise HTTPException(status_code=404, detail="Hero not found")
    # Use exclude_unset to only update provided fields
    hero_data = hero.model_dump(exclude_unset=True)
    hero_db.sqlmodel_update(hero_data)
    session.add(hero_db)
    session.commit()
    session.refresh(hero_db)
    return hero_db
```

### Security

#### OAuth2 with JWT
- Use `OAuth2PasswordBearer` for token authentication:
```python
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")

async def get_current_user(token: Annotated[str, Depends(oauth2_scheme)]):
    user = decode_token(token)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user
```

#### HTTP Basic Auth (use secrets.compare_digest to prevent timing attacks)
```python
import secrets
from fastapi.security import HTTPBasic, HTTPBasicCredentials

security = HTTPBasic()

def get_current_username(credentials: Annotated[HTTPBasicCredentials, Depends(security)]):
    current_username_bytes = credentials.username.encode("utf8")
    correct_username_bytes = b"admin"
    is_correct_username = secrets.compare_digest(current_username_bytes, correct_username_bytes)
    current_password_bytes = credentials.password.encode("utf8")
    correct_password_bytes = b"secret"
    is_correct_password = secrets.compare_digest(current_password_bytes, correct_password_bytes)
    if not (is_correct_username and is_correct_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Basic"},
        )
    return credentials.username
```

#### Security Best Practices
- Never store plaintext passwords
- Use strong hashing (bcrypt, argon2) via `pwdlib`
- Include user identification in JWT `sub` claim
- Transmit tokens in Authorization header only
- Return 401 for unauthenticated, 403 for unauthorized

### Pitfalls

#### 1. CRITICAL (v0.110.0+): Dependencies with Yield Must Re-raise Exceptions
```python
# WRONG - causes memory leak and unhandled errors
def my_dep():
    try:
        yield
    except SomeException:
        pass  # DON'T DO THIS

# CORRECT - always re-raise exceptions
def my_dep():
    try:
        yield
    except SomeException:
        raise  # Always re-raise
```

#### 2. Deprecated `regex` parameter
Use `pattern` instead of `regex` for string validation (deprecated in FastAPI 0.100.0 and Pydantic v2)

#### 3. Middleware order matters
The last middleware added becomes the outermost:
```python
app.add_middleware(MiddlewareA)  # Runs second
app.add_middleware(MiddlewareB)  # Runs first
```

#### 4. SQLite thread safety
Always use `connect_args = {"check_same_thread": False}` for SQLite

#### 5. Async vs Sync functions
Use `async def` when you need to await, use regular `def` for CPU-bound operations

#### 6. Don't forget to refresh after commit
```python
session.add(db_hero)
session.commit()
session.refresh(db_hero)  # Important to get updated data
return db_hero
```

#### 7. Always check if entity exists before operations
```python
@app.get("/heroes/{hero_id}", response_model=HeroPublic)
def read_hero(hero_id: int, session: SessionDep):
    hero = session.get(Hero, hero_id)
    if not hero:
        raise HTTPException(status_code=404, detail="Hero not found")
    return hero
```

#### 8. Always use Response Models
Control what data is exposed to clients. Prevents accidentally exposing sensitive fields.

### Error Handling

#### HTTPException for Client Errors
```python
from fastapi import FastAPI, HTTPException

@app.get("/items/{item_id}")
async def read_item(item_id: str):
    if item_id not in items:
        raise HTTPException(
            status_code=404,
            detail="Item not found",
            headers={"X-Error": "Item not found"}
        )
    return {"item": items[item_id]}
```

#### Custom Exception Handlers
```python
from fastapi.exception_handlers import (
    http_exception_handler,
    request_validation_exception_handler,
)
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException

@app.exception_handler(StarletteHTTPException)
async def custom_http_exception_handler(request, exc):
    print(f"HTTP error: {repr(exc)}")  # Log for debugging
    return await http_exception_handler(request, exc)

@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request, exc):
    print(f"Validation error: {exc}")  # Log for debugging
    return await request_validation_exception_handler(request, exc)
```

#### Include Request Body in Validation Errors (for debugging)
```python
from fastapi.encoders import jsonable_encoder

@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    return JSONResponse(
        status_code=422,
        content=jsonable_encoder({"detail": exc.errors(), "body": exc.body}),
    )
```

### Deployment

```bash
# Single worker
fastapi run main.py
uvicorn main:app --host 0.0.0.0 --port 8000

# Multiple workers (recommended for production)
fastapi run --workers 4 main.py
uvicorn main:app --host 0.0.0.0 --port 8080 --workers 4
```

**Supported Databases (via SQLAlchemy/SQLModel):** PostgreSQL, MySQL, SQLite, Oracle, Microsoft SQL Server

---

## Python (3.10+)

### Setup

#### Project Structure
Use packages with `__init__.py` for organization:
```
project/
    __init__.py
    main.py
    config.py
    api/
        __init__.py
        routes/
            __init__.py
            items.py
            users.py
    core/
        __init__.py
        security.py
    models/
        __init__.py
        item.py
        user.py
    services/
        __init__.py
```

#### Import Organization (PEP 8)
```python
# Standard library imports
import sys
import os

# Third-party imports
import requests
from fastapi import FastAPI

# Local application imports
from .models import User
```

#### Relative Imports Within a Package
```python
from . import echo                    # Import from current package
from .. import formats                # Import from parent package
from ..filters import equalizer       # Import from sibling package
```

### Best Practices

#### Type Hints
```python
def sum_two_numbers(a: int, b: int) -> int:
    return a + b

def process_items(items: list[str], config: dict[str, any] | None = None) -> int:
    return len(items)
```

#### Dictionary-Based Logging Configuration (Recommended)
```python
import logging.config

log_config = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'standard': {
            'format': '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        }
    },
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
            'formatter': 'standard',
            'level': 'DEBUG'
        },
        'file': {
            'class': 'logging.FileHandler',
            'filename': 'app.log',
            'formatter': 'standard'
        }
    },
    'root': {
        'handlers': ['console', 'file'],
        'level': 'DEBUG'
    }
}

logging.config.dictConfig(log_config)
logger = logging.getLogger(__name__)
```

#### Error Handling - Try-Except-Else-Finally
```python
def divide(x, y):
    try:
        result = x / y
    except ZeroDivisionError:
        print("division by zero!")
    else:
        print("result is", result)
    finally:
        print("executing finally clause")
```

#### Log and Re-raise Unexpected Exceptions
```python
try:
    f = open('myfile.txt')
    s = f.readline()
    i = int(s.strip())
except OSError as err:
    print("OS error:", err)
except ValueError:
    print("Could not convert data to an integer.")
except Exception as err:
    print(f"Unexpected {err=}, {type(err)=}")
    raise  # Re-raise for higher-level handling
```

#### Async/Await Patterns
```python
import asyncio

async def nested():
    return 42

async def main():
    # WRONG - creates coroutine but doesn't execute it
    nested()  # RuntimeWarning

    # CORRECT
    result = await nested()  # Executes and returns 42

asyncio.run(main())
```

#### Concurrent Task Execution
```python
import asyncio

async def main():
    # Sequential (slower - 3 seconds total)
    await say_after(1, 'hello')
    await say_after(2, 'world')

    # Concurrent (faster - 2 seconds total)
    task1 = asyncio.create_task(say_after(1, 'hello'))
    task2 = asyncio.create_task(say_after(2, 'world'))
    await task1
    await task2

    # Or use asyncio.gather for concurrent execution
    await asyncio.gather(
        factorial("A", 2),
        factorial("B", 3),
        factorial("C", 4),
    )
```

### Pitfalls

#### 1. CRITICAL: Mutable Default Arguments
```python
# WRONG - list is shared across all calls
def f(a, L=[]):
    L.append(a)
    return L

f(1)  # [1]
f(2)  # [1, 2] - Unexpected!

# CORRECT - use None and create new object
def f(a, L=None):
    if L is None:
        L = []
    L.append(a)
    return L
```

#### 2. List Multiplication with Mutable Objects
```python
# WRONG - all elements reference the same list
lists = [[]] * 3
lists[0].append(3)
print(lists)  # [[3], [3], [3]] - All modified!

# CORRECT - use list comprehension
lists = [[] for _ in range(3)]
lists[0].append(3)
print(lists)  # [[3], [], []]
```

#### 3. Never-Awaited Coroutines
Enable asyncio debug mode to detect:
```python
import asyncio
asyncio.get_event_loop().set_debug(True)
```

#### 4. Wildcard Imports
```python
# WRONG - obscures name origins
from module import *

# CORRECT - explicit imports
from module import specific_function, SpecificClass
```

### Security
- Use `secrets` module for secure comparisons and random generation
- Never store sensitive data in default arguments
- Use environment variables for configuration secrets
- Validate and sanitize all external input

---

## Summary: Key Integration Points

### FastAPI + Python Best Practices

1. **Use `Annotated` for dependency injection** - Provides better type hints and IDE support
2. **Separate concerns with APIRouter** - Organize routes into modules with prefixes and tags
3. **Use Pydantic models for validation** - Automatic request/response validation with separate Create/Update/Public models
4. **Implement proper error handling** - Custom exception handlers with logging
5. **Use dependency injection for database sessions** - Clean resource management with `yield`
6. **Configure CORS properly for production** - Don't use `allow_origins=["*"]` in production
7. **Use environment variables for secrets** - Never hardcode SECRET_KEY or credentials
8. **Implement proper logging** - Use dictionary-based configuration
9. **Use type hints everywhere** - Improves code quality and enables better tooling
10. **Test with dependency overrides** - Use `app.dependency_overrides` for testing
11. **Cache settings with `@lru_cache`** - Avoid repeated .env file reads
12. **Always validate and constrain inputs** - Use Query parameters with `le`, `ge`, `pattern` constraints
13. **Use `exclude_unset=True` for PATCH** - Only update fields that were actually provided
14. **Return proper HTTP status codes** - 401 with WWW-Authenticate header, 404 for not found, 422 for validation errors
15. **CRITICAL: Re-raise exceptions in yield dependencies** - Prevents memory leaks (FastAPI 0.110.0+)
16. **CRITICAL: Never use mutable default arguments** - Use None and create inside function

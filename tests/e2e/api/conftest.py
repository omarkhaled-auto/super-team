"""Shared fixtures and helpers for E2E API tests."""
import os
import subprocess
import time
import httpx
import pytest
import base64

# Service base URLs — each service runs on its own port
# Supports both Docker Compose (8001-8003) and direct uvicorn (9876-9878)
ARCHITECT_URL = os.environ.get("ARCHITECT_URL", "http://localhost:8001")
CONTRACT_ENGINE_URL = os.environ.get("CONTRACT_ENGINE_URL", "http://localhost:8002")
CODEBASE_INTEL_URL = os.environ.get("CODEBASE_INTEL_URL", "http://localhost:8003")

# Generous timeout for real HTTP calls
TIMEOUT = httpx.Timeout(30.0, connect=10.0)

# Configurable wait interval for service readiness polling
SERVICE_POLL_INTERVAL = float(os.environ.get("E2E_POLL_INTERVAL", "1"))


def _any_service_reachable() -> bool:
    """Check whether at least one E2E service is reachable.

    Tries the health endpoint of each service. If ANY responds with 200,
    the suite is considered available. This supports both Docker Compose
    and direct uvicorn-launched services.
    """
    for url in (ARCHITECT_URL, CONTRACT_ENGINE_URL, CODEBASE_INTEL_URL):
        try:
            resp = httpx.get(f"{url}/api/health", timeout=3.0)
            if resp.status_code == 200:
                return True
        except (httpx.ConnectError, httpx.ReadTimeout, httpx.ConnectTimeout):
            continue
    return False


# Auto-skip every test collected under tests/e2e/api/ when no service is up
pytestmark = pytest.mark.skipif(
    not _any_service_reachable(),
    reason="E2E services not available — skipping E2E tests",
)


@pytest.fixture(scope="session")
def architect_client():
    """HTTP client for the Architect service."""
    with httpx.Client(base_url=ARCHITECT_URL, timeout=TIMEOUT) as client:
        yield client


@pytest.fixture(scope="session")
def contract_engine_client():
    """HTTP client for the Contract Engine service."""
    with httpx.Client(base_url=CONTRACT_ENGINE_URL, timeout=TIMEOUT) as client:
        yield client


@pytest.fixture(scope="session")
def codebase_intel_client():
    """HTTP client for the Codebase Intelligence service."""
    with httpx.Client(base_url=CODEBASE_INTEL_URL, timeout=TIMEOUT) as client:
        yield client


# ── Sample Data ──────────────────────────────────────────────────────────

SAMPLE_PRD_TEXT = """
# E-Commerce Platform - Product Requirements Document

## 1. Project Overview

**Project Name:** E-Commerce Platform
**Version:** 2.0

The E-Commerce Platform is a distributed microservices-based online marketplace.

### Technology Stack

- **Language:** Python 3.12+
- **Framework:** FastAPI
- **Primary Database:** PostgreSQL 16
- **Message Broker:** RabbitMQ 3.13

## 2. Service Boundaries

### 2.1 User Service

The User Service is the identity and access management hub. It owns all user-related data
including profiles, credentials, addresses, and authentication tokens.

#### User Entity

- **id** (UUID, primary key)
- **email** (string, unique)
- **name** (string)
- **role** (enum: customer, admin)

### 2.2 Order Service

The Order Service manages the complete order lifecycle from creation to fulfillment.
It owns order data, line items, and order status transitions.

#### Order Entity

- **id** (UUID, primary key)
- **user_id** (UUID, foreign key)
- **status** (enum: pending, confirmed, shipped, delivered, cancelled)
- **total** (decimal)
- **created_at** (datetime)

### 2.3 Inventory Service

The Inventory Service tracks product stock levels and manages reservations.

#### Product Entity

- **id** (UUID, primary key)
- **name** (string)
- **sku** (string, unique)
- **quantity** (integer)
- **price** (decimal)
"""

SAMPLE_OPENAPI_SPEC = {
    "openapi": "3.1.0",
    "info": {"title": "User Service API", "version": "1.0.0"},
    "paths": {
        "/api/users": {
            "get": {
                "summary": "List users",
                "operationId": "listUsers",
                "parameters": [
                    {
                        "name": "page",
                        "in": "query",
                        "schema": {"type": "integer", "default": 1},
                    }
                ],
                "responses": {
                    "200": {
                        "description": "Success",
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "properties": {
                                        "items": {
                                            "type": "array",
                                            "items": {"type": "object"},
                                        },
                                        "total": {"type": "integer"},
                                    },
                                }
                            }
                        },
                    }
                },
            },
            "post": {
                "summary": "Create user",
                "operationId": "createUser",
                "requestBody": {
                    "required": True,
                    "content": {
                        "application/json": {
                            "schema": {
                                "type": "object",
                                "required": ["name", "email"],
                                "properties": {
                                    "name": {"type": "string"},
                                    "email": {"type": "string", "format": "email"},
                                },
                            }
                        }
                    },
                },
                "responses": {
                    "201": {
                        "description": "Created",
                        "content": {
                            "application/json": {
                                "schema": {"type": "object"}
                            }
                        },
                    }
                },
            },
        }
    },
}

SAMPLE_ASYNCAPI_SPEC = {
    "asyncapi": "3.0.0",
    "info": {"title": "User Events", "version": "1.0.0"},
    "defaultContentType": "application/json",
    "channels": {
        "user/created": {
            "address": "user/created",
            "messages": {
                "UserCreated": {
                    "payload": {
                        "type": "object",
                        "properties": {
                            "user_id": {"type": "string"},
                            "name": {"type": "string"},
                        },
                    }
                }
            },
        }
    },
    "operations": {
        "sendUserCreated": {
            "action": "send",
            "channel": {"$ref": "#/channels/user~1created"},
            "messages": [
                {"$ref": "#/channels/user~1created/messages/UserCreated"}
            ],
        }
    },
}

SAMPLE_PYTHON_SOURCE = '''"""Authentication and authorization service."""

import hashlib
import os
from datetime import datetime, timedelta
from functools import wraps
from typing import Optional

from .models import TokenPayload, User, UserRole


SECRET_KEY = os.environ.get("SECRET_KEY", "dev-secret-key")
TOKEN_EXPIRY_HOURS = 24


def require_auth(func):
    """Decorator that enforces authentication on a route handler."""

    @wraps(func)
    def wrapper(*args, **kwargs):
        token = kwargs.get("token")
        if not token:
            raise PermissionError("Authentication required")
        return func(*args, **kwargs)

    return wrapper


def get_current_user(token: str, users: dict) -> Optional[User]:
    """Resolve the current user from a token string."""
    payload = AuthService().verify_token(token)
    if payload is None:
        return None
    return users.get(payload.user_id)


class AuthService:
    """Handles password hashing, token creation, and token verification."""

    def __init__(self, secret: str = SECRET_KEY):
        self.secret = secret

    def authenticate(self, email: str, password: str, users: dict) -> Optional[User]:
        """Validate credentials and return the user if they match."""
        hashed = self.hash_password(password)
        for user in users.values():
            if user.email == email and self._check_hash(password, hashed):
                return user
        return None

    def create_token(self, user: User) -> str:
        """Generate an access token for the given user."""
        payload = TokenPayload(
            user_id=user.id,
            exp=datetime.utcnow() + timedelta(hours=TOKEN_EXPIRY_HOURS),
        )
        raw = f"{payload.user_id}:{payload.exp.isoformat()}:{self.secret}"
        return hashlib.sha256(raw.encode()).hexdigest()

    def verify_token(self, token: str) -> Optional[TokenPayload]:
        """Verify a token and return its payload, or None if invalid."""
        if not token or len(token) != 64:
            return None
        return self._decode_token(token)

    def hash_password(self, password: str) -> str:
        """Return a salted SHA-256 hash of the password."""
        salted = f"{self.secret}:{password}"
        return hashlib.sha256(salted.encode()).hexdigest()

    def _check_hash(self, password: str, hashed: str) -> bool:
        """Compare a plain-text password against a stored hash."""
        return self.hash_password(password) == hashed

    def _decode_token(self, token: str) -> Optional[TokenPayload]:
        """Internal helper to decode a token string."""
        return TokenPayload(
            user_id=0,
            exp=datetime.utcnow() + timedelta(hours=TOKEN_EXPIRY_HOURS),
        )


class PermissionChecker:
    """Checks whether a user has the required role for an action."""

    ROLE_HIERARCHY = {
        UserRole.ADMIN: 3,
        UserRole.MODERATOR: 2,
        UserRole.USER: 1,
    }

    def check_permission(self, user: User, required_role: UserRole) -> bool:
        """Return True if the user's role meets or exceeds the required role."""
        user_level = self.ROLE_HIERARCHY.get(user.role, 0)
        required_level = self.ROLE_HIERARCHY.get(required_role, 0)
        return user_level >= required_level
'''

# Base64 encode the source for artifact registration
SAMPLE_PYTHON_SOURCE_B64 = base64.b64encode(SAMPLE_PYTHON_SOURCE.encode("utf-8")).decode("utf-8")


def wait_for_service(base_url: str, timeout: int = 30) -> bool:
    """Wait for a service to become healthy."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            resp = httpx.get(f"{base_url}/api/health", timeout=5.0)
            if resp.status_code == 200:
                return True
        except (httpx.ConnectError, httpx.ReadTimeout):
            pass
        time.sleep(SERVICE_POLL_INTERVAL)
    return False

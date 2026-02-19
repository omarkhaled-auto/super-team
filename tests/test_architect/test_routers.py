"""Integration tests for the Architect service routers.

Tests cover the health, decomposition, service-map, and domain-model
endpoints using FastAPI TestClient with a temporary SQLite database.
Each test gets a fresh database instance to ensure isolation.
"""
from __future__ import annotations

import time
from contextlib import asynccontextmanager

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.shared.config import ArchitectConfig
from src.shared.constants import ARCHITECT_SERVICE_NAME, VERSION
from src.shared.db.connection import ConnectionPool
from src.shared.db.schema import init_architect_db
from src.shared.errors import register_exception_handlers
from src.shared.logging import TraceIDMiddleware

# ---------------------------------------------------------------------------
# Sample PRD used across decomposition tests
# ---------------------------------------------------------------------------

SAMPLE_PRD = """\
# E-Commerce Platform

## Services

### User Service
Manages user accounts and authentication.

### Order Service
Handles order processing and fulfillment.

### Product Service
Manages product catalog and inventory.

## Data Model

### User
- id: UUID (required)
- email: string (required)
- name: string (required)
- status: string

### Order
- id: UUID (required)
- user_id: UUID (required)
- total: float (required)
- status: string

### Product
- id: UUID (required)
- name: string (required)
- price: float (required)
- description: string

## Relationships
- Order belongs to User
- Order has many OrderItem
- OrderItem references Product

## Technology
Built with Python and FastAPI, using PostgreSQL for storage and RabbitMQ for messaging.

Order status: pending -> confirmed -> shipped -> delivered
User status: active -> suspended -> deactivated
"""


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def client(tmp_path):
    """Create a test client with a temporary database.

    Builds a standalone FastAPI app wired to a fresh SQLite database
    under ``tmp_path``, registers all Architect routers, and yields
    a ``TestClient`` instance that is properly started and shut down
    via the lifespan context manager.
    """
    db_path = tmp_path / "test.db"
    pool = ConnectionPool(db_path)
    init_architect_db(pool)

    @asynccontextmanager
    async def lifespan(app):
        app.state.pool = pool
        app.state.start_time = time.time()
        yield
        pool.close()

    test_app = FastAPI(
        title="Architect Service",
        version=VERSION,
        lifespan=lifespan,
    )
    test_app.add_middleware(TraceIDMiddleware)
    register_exception_handlers(test_app)

    from src.architect.routers.health import router as health_router
    from src.architect.routers.decomposition import router as decomposition_router
    from src.architect.routers.service_map import router as service_map_router
    from src.architect.routers.domain_model import router as domain_model_router

    test_app.include_router(health_router)
    test_app.include_router(decomposition_router)
    test_app.include_router(service_map_router)
    test_app.include_router(domain_model_router)

    with TestClient(test_app) as c:
        yield c


# ---------------------------------------------------------------------------
# Health endpoint tests
# ---------------------------------------------------------------------------


class TestHealthEndpoint:
    """Tests for GET /api/health."""

    def test_health_returns_200(self, client: TestClient):
        """GET /api/health should return HTTP 200."""
        response = client.get("/api/health")
        assert response.status_code == 200

    def test_health_status_healthy(self, client: TestClient):
        """GET /api/health should report status as 'healthy' when the
        database is reachable."""
        response = client.get("/api/health")
        data = response.json()
        assert data["status"] == "healthy"

    def test_health_service_name(self, client: TestClient):
        """GET /api/health should return the correct service_name."""
        response = client.get("/api/health")
        data = response.json()
        assert data["service_name"] == ARCHITECT_SERVICE_NAME

    def test_health_version(self, client: TestClient):
        """GET /api/health should return the correct application version."""
        response = client.get("/api/health")
        data = response.json()
        assert data["version"] == VERSION

    def test_health_database_connected(self, client: TestClient):
        """GET /api/health should report database as 'connected'."""
        response = client.get("/api/health")
        data = response.json()
        assert data["database"] == "connected"

    def test_health_uptime_positive(self, client: TestClient):
        """GET /api/health should return a non-negative uptime value."""
        response = client.get("/api/health")
        data = response.json()
        assert data["uptime_seconds"] >= 0


# ---------------------------------------------------------------------------
# Decomposition endpoint tests
# ---------------------------------------------------------------------------


class TestDecomposeEndpoint:
    """Tests for POST /api/decompose."""

    def test_decompose_returns_201(self, client: TestClient):
        """POST /api/decompose with a valid PRD should return HTTP 201."""
        response = client.post(
            "/api/decompose",
            json={"prd_text": SAMPLE_PRD},
        )
        assert response.status_code == 201

    def test_decompose_response_has_service_map_with_services(
        self, client: TestClient
    ):
        """The decomposition result should contain a service_map with a
        non-empty services list."""
        response = client.post(
            "/api/decompose",
            json={"prd_text": SAMPLE_PRD},
        )
        data = response.json()
        assert "service_map" in data
        assert "services" in data["service_map"]
        assert isinstance(data["service_map"]["services"], list)
        assert len(data["service_map"]["services"]) >= 1

    def test_decompose_response_has_domain_model_with_entities(
        self, client: TestClient
    ):
        """The decomposition result should contain a domain_model with a
        non-empty entities list."""
        response = client.post(
            "/api/decompose",
            json={"prd_text": SAMPLE_PRD},
        )
        data = response.json()
        assert "domain_model" in data
        assert "entities" in data["domain_model"]
        assert isinstance(data["domain_model"]["entities"], list)
        assert len(data["domain_model"]["entities"]) >= 1

    def test_decompose_response_has_contract_stubs(self, client: TestClient):
        """The decomposition result should contain a contract_stubs list."""
        response = client.post(
            "/api/decompose",
            json={"prd_text": SAMPLE_PRD},
        )
        data = response.json()
        assert "contract_stubs" in data
        assert isinstance(data["contract_stubs"], list)

    def test_decompose_too_short_text_returns_422(self, client: TestClient):
        """POST /api/decompose with text shorter than the minimum length
        (Pydantic min_length=10) should return HTTP 422."""
        response = client.post(
            "/api/decompose",
            json={"prd_text": "short"},
        )
        assert response.status_code == 422

    def test_decompose_empty_text_returns_422(self, client: TestClient):
        """POST /api/decompose with an empty string should return HTTP 422."""
        response = client.post(
            "/api/decompose",
            json={"prd_text": ""},
        )
        assert response.status_code == 422

    def test_decompose_missing_prd_text_returns_422(self, client: TestClient):
        """POST /api/decompose with a missing prd_text field should return
        HTTP 422."""
        response = client.post(
            "/api/decompose",
            json={},
        )
        assert response.status_code == 422

    def test_decompose_service_map_has_project_name(self, client: TestClient):
        """The service_map in the decomposition result should include a
        project_name derived from the PRD."""
        response = client.post(
            "/api/decompose",
            json={"prd_text": SAMPLE_PRD},
        )
        data = response.json()
        project_name = data["service_map"]["project_name"]
        assert project_name  # non-empty
        assert "E-Commerce" in project_name or "e-commerce" in project_name.lower()

    def test_decompose_multi_service_prd_produces_multiple_services(
        self, client: TestClient
    ):
        """A PRD describing multiple service boundaries should result in
        more than one service in the service_map."""
        response = client.post(
            "/api/decompose",
            json={"prd_text": SAMPLE_PRD},
        )
        data = response.json()
        services = data["service_map"]["services"]
        assert len(services) > 1, (
            f"Expected multiple services for a multi-service PRD, "
            f"got {len(services)}"
        )

    def test_decompose_domain_model_has_relationships(
        self, client: TestClient
    ):
        """The domain_model should contain relationships between entities."""
        response = client.post(
            "/api/decompose",
            json={"prd_text": SAMPLE_PRD},
        )
        data = response.json()
        relationships = data["domain_model"]["relationships"]
        assert isinstance(relationships, list)
        # The sample PRD explicitly defines relationships, so at least
        # one should be detected.
        assert len(relationships) >= 1

    def test_decompose_contract_stubs_match_services(
        self, client: TestClient
    ):
        """There should be at least one contract stub for the decomposed
        services."""
        response = client.post(
            "/api/decompose",
            json={"prd_text": SAMPLE_PRD},
        )
        data = response.json()
        assert len(data["contract_stubs"]) >= 1

    def test_decompose_service_map_has_prd_hash(self, client: TestClient):
        """The service_map should contain a non-empty prd_hash field."""
        response = client.post(
            "/api/decompose",
            json={"prd_text": SAMPLE_PRD},
        )
        data = response.json()
        prd_hash = data["service_map"]["prd_hash"]
        assert isinstance(prd_hash, str)
        assert len(prd_hash) > 0


# ---------------------------------------------------------------------------
# Service map endpoint tests
# ---------------------------------------------------------------------------


class TestServiceMapEndpoint:
    """Tests for GET /api/service-map."""

    def test_service_map_returns_404_when_empty(self, client: TestClient):
        """GET /api/service-map should return HTTP 404 when no
        decomposition has been performed yet."""
        response = client.get("/api/service-map")
        assert response.status_code == 404

    def test_service_map_returns_200_after_decomposition(
        self, client: TestClient
    ):
        """GET /api/service-map should return HTTP 200 after a successful
        decomposition has been stored."""
        # First, run a decomposition to populate the database.
        decompose_resp = client.post(
            "/api/decompose",
            json={"prd_text": SAMPLE_PRD},
        )
        assert decompose_resp.status_code == 201

        # Now fetch the service map.
        response = client.get("/api/service-map")
        assert response.status_code == 200

    def test_service_map_contains_services(self, client: TestClient):
        """GET /api/service-map after decomposition should return a body
        with a services list."""
        client.post("/api/decompose", json={"prd_text": SAMPLE_PRD})

        response = client.get("/api/service-map")
        data = response.json()
        assert "services" in data
        assert isinstance(data["services"], list)
        assert len(data["services"]) >= 1

    def test_service_map_contains_project_name(self, client: TestClient):
        """GET /api/service-map after decomposition should return a body
        with the project_name field populated."""
        client.post("/api/decompose", json={"prd_text": SAMPLE_PRD})

        response = client.get("/api/service-map")
        data = response.json()
        assert "project_name" in data
        assert data["project_name"]  # non-empty


# ---------------------------------------------------------------------------
# Domain model endpoint tests
# ---------------------------------------------------------------------------


class TestDomainModelEndpoint:
    """Tests for GET /api/domain-model."""

    def test_domain_model_returns_404_when_empty(self, client: TestClient):
        """GET /api/domain-model should return HTTP 404 when no
        decomposition has been performed yet."""
        response = client.get("/api/domain-model")
        assert response.status_code == 404

    def test_domain_model_returns_200_after_decomposition(
        self, client: TestClient
    ):
        """GET /api/domain-model should return HTTP 200 after a successful
        decomposition has been stored."""
        # First, run a decomposition to populate the database.
        decompose_resp = client.post(
            "/api/decompose",
            json={"prd_text": SAMPLE_PRD},
        )
        assert decompose_resp.status_code == 201

        # Now fetch the domain model.
        response = client.get("/api/domain-model")
        assert response.status_code == 200

    def test_domain_model_contains_entities(self, client: TestClient):
        """GET /api/domain-model after decomposition should return a body
        with an entities list."""
        client.post("/api/decompose", json={"prd_text": SAMPLE_PRD})

        response = client.get("/api/domain-model")
        data = response.json()
        assert "entities" in data
        assert isinstance(data["entities"], list)
        assert len(data["entities"]) >= 1

    def test_domain_model_contains_relationships(self, client: TestClient):
        """GET /api/domain-model after decomposition should return a body
        with a relationships list."""
        client.post("/api/decompose", json={"prd_text": SAMPLE_PRD})

        response = client.get("/api/domain-model")
        data = response.json()
        assert "relationships" in data
        assert isinstance(data["relationships"], list)

    def test_domain_model_entities_have_required_fields(
        self, client: TestClient
    ):
        """Each entity in the domain model should have 'name',
        'owning_service', and 'fields' keys."""
        client.post("/api/decompose", json={"prd_text": SAMPLE_PRD})

        response = client.get("/api/domain-model")
        data = response.json()
        for entity in data["entities"]:
            assert "name" in entity, f"Entity missing 'name': {entity}"
            assert "owning_service" in entity, (
                f"Entity missing 'owning_service': {entity}"
            )
            assert "fields" in entity, f"Entity missing 'fields': {entity}"

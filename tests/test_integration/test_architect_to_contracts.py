"""Integration tests: Architect decomposition pipeline (REQ-017).

Verifies the full decomposition pipeline using the Architect service's
FastAPI TestClient (in-process, no Docker, no real HTTP).

Test cases:
    1. POST /api/decompose with sample PRD returns 201 with expected keys.
    2. The service_map in the response has at least 1 service.
    3. The domain_model in the response has at least 1 entity.
    4. After decompose, GET /api/service-map returns persisted ServiceMap.
    5. After decompose, GET /api/domain-model returns persisted DomainModel.
    6. Each contract stub is a valid OpenAPI 3.1.0 spec.
    7. POST /api/decompose with very short text returns 400.
    8. GET /api/health returns 200 with status="healthy".
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# Sample PRD text -- long enough to pass the >=30 char minimum and rich
# enough to exercise entity/relationship/bounded-context extraction.
# ---------------------------------------------------------------------------
SAMPLE_PRD = """\
# E-Commerce Platform - Product Requirements Document

## 1. Project Overview

**Project Name:** E-Commerce Platform
**Version:** 2.0

The E-Commerce Platform is a distributed, microservices-based online marketplace
that enables customers to browse products, place orders, and manage their accounts.
The system must support high availability, horizontal scaling, and eventual
consistency across service boundaries.

### Technology Stack

- **Language:** Python 3.12+
- **Framework:** FastAPI
- **Primary Database:** PostgreSQL 16
- **Cache Layer:** Redis 7
- **Message Broker:** RabbitMQ 3.13

---

## 2. Service Boundaries

### 2.1 User Service

The User Service is the identity and access management hub. It owns all
user-related data including profiles, credentials, addresses, and
authentication tokens. It publishes `user.registered`, `user.updated`, and
`user.deactivated` domain events to RabbitMQ.

#### User Entity

| Field | Type | Constraints | Description |
|-------|------|-------------|-------------|
| id | UUID | primary key | Unique user identifier |
| email | string | unique, indexed | User email address |
| password_hash | string | not null | Hashed password |
| first_name | string | max 100 | First name |
| last_name | string | max 100 | Last name |
| role | enum | not null | Role: customer, admin |
| account_status | enum | not null | Status: active, suspended, deactivated |
| created_at | datetime | UTC | Creation timestamp |

#### Address Entity

| Field | Type | Constraints | Description |
|-------|------|-------------|-------------|
| id | UUID | primary key | Unique address identifier |
| user_id | UUID | foreign key | Reference to User |
| city | string | max 100 | City name |
| country_code | string | ISO 3166 | Country code |

### 2.2 Product Service

The Product Service manages the entire product catalog including categories,
product listings, inventory counts, and pricing.

#### Product Entity

| Field | Type | Constraints | Description |
|-------|------|-------------|-------------|
| id | UUID | primary key | Unique product identifier |
| sku | string | unique | Stock keeping unit |
| name | string | max 255 | Product name |
| price_cents | integer | not null | Price in cents |
| category_id | UUID | foreign key | Parent category |
| is_active | boolean | default true | Whether listed |

#### Category Entity

| Field | Type | Constraints | Description |
|-------|------|-------------|-------------|
| id | UUID | primary key | Category identifier |
| name | string | max 100 | Category name |
| parent_id | UUID | nullable | Parent category |

#### Inventory Entity

| Field | Type | Constraints | Description |
|-------|------|-------------|-------------|
| id | UUID | primary key | Inventory record |
| product_id | UUID | foreign key | Associated product |
| quantity_on_hand | integer | not null | Current stock |

### 2.3 Order Service

The Order Service orchestrates the entire purchase lifecycle.
Order belongs to User. OrderItem references Product.

#### Order Entity

| Field | Type | Constraints | Description |
|-------|------|-------------|-------------|
| id | UUID | primary key | Order identifier |
| user_id | UUID | not null | Ordering user |
| status | enum | not null | Status: pending, confirmed, shipped, delivered, cancelled |
| total_cents | integer | not null | Grand total |
| created_at | datetime | UTC | Placement time |

#### OrderItem Entity

| Field | Type | Constraints | Description |
|-------|------|-------------|-------------|
| id | UUID | primary key | Item identifier |
| order_id | UUID | foreign key | Parent order |
| product_id | UUID | foreign key | Product reference |
| quantity | integer | not null | Item quantity |
| unit_price_cents | integer | not null | Price at purchase |

### 2.4 Payment Service

The Payment Service handles all monetary transactions.
Payment depends on Order.

#### Payment Entity

| Field | Type | Constraints | Description |
|-------|------|-------------|-------------|
| id | UUID | primary key | Payment identifier |
| order_id | UUID | not null | Associated order |
| amount_cents | integer | not null | Payment amount |
| status | enum | not null | Status: pending, captured, failed, refunded |
| created_at | datetime | UTC | Initiation time |

### 2.5 Notification Service

The Notification Service is a downstream consumer responsible for sending
transactional emails, SMS messages, and push notifications.

#### NotificationLog Entity

| Field | Type | Constraints | Description |
|-------|------|-------------|-------------|
| id | UUID | primary key | Log identifier |
| user_id | UUID | not null | Target user |
| channel | enum | not null | Channel: email, sms, push |
| status | enum | not null | Status: pending, sent, failed |
| created_at | datetime | UTC | Sent timestamp |
"""


# ---------------------------------------------------------------------------
# Module-scoped fixtures using monkeypatch equivalent for env isolation
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def client(tmp_path_factory: pytest.TempPathFactory):
    """Create a TestClient backed by a temporary database.

    Sets DATABASE_PATH before importing the app so ArchitectConfig picks
    up the temp path.  Restores the original value on teardown.
    """
    from fastapi.testclient import TestClient

    tmp = tmp_path_factory.mktemp("architect_integ")
    db_path = str(tmp / "architect_integ_test.db")

    original = os.environ.get("DATABASE_PATH")
    os.environ["DATABASE_PATH"] = db_path

    from src.architect.main import app  # noqa: E402

    with TestClient(app, raise_server_exceptions=False) as c:
        yield c

    # Restore original env var
    if original is None:
        os.environ.pop("DATABASE_PATH", None)
    else:
        os.environ["DATABASE_PATH"] = original


@pytest.fixture(scope="module")
def decompose_response(client) -> dict:
    """Run POST /api/decompose once and cache the result for the module.

    Multiple tests inspect different facets of the same response, so we
    avoid repeating the (relatively expensive) decomposition call.
    """
    resp = client.post("/api/decompose", json={"prd_text": SAMPLE_PRD})
    assert resp.status_code == 201, (
        f"Expected 201 from /api/decompose, got {resp.status_code}: {resp.text}"
    )
    return resp.json()


# ---------------------------------------------------------------------------
# Test cases
# ---------------------------------------------------------------------------


class TestDecomposePipeline:
    """Tests for the full decomposition pipeline via POST /api/decompose."""

    def test_decompose_sample_prd_returns_201(
        self, decompose_response: dict
    ) -> None:
        """POST /api/decompose returns 201 with service_map, domain_model,
        and contract_stubs in the response body."""
        assert "service_map" in decompose_response
        assert "domain_model" in decompose_response
        assert "contract_stubs" in decompose_response

    def test_decompose_result_has_services(
        self, decompose_response: dict
    ) -> None:
        """The service_map in the response contains at least 1 service."""
        service_map = decompose_response["service_map"]
        assert "services" in service_map
        assert isinstance(service_map["services"], list)
        assert len(service_map["services"]) >= 1, (
            "Expected at least 1 service in the service_map"
        )

    def test_decompose_result_has_domain_entities(
        self, decompose_response: dict
    ) -> None:
        """The domain_model in the response contains at least 1 entity."""
        domain_model = decompose_response["domain_model"]
        assert "entities" in domain_model
        assert isinstance(domain_model["entities"], list)
        assert len(domain_model["entities"]) >= 1, (
            "Expected at least 1 entity in the domain_model"
        )

    def test_decompose_result_has_project_name(
        self, decompose_response: dict
    ) -> None:
        """The service_map carries a non-empty project_name."""
        service_map = decompose_response["service_map"]
        assert "project_name" in service_map
        assert len(service_map["project_name"]) > 0

    def test_decompose_result_has_prd_hash(
        self, decompose_response: dict
    ) -> None:
        """The service_map carries a non-empty prd_hash."""
        service_map = decompose_response["service_map"]
        assert "prd_hash" in service_map
        assert len(service_map["prd_hash"]) > 0


class TestPersistence:
    """Tests that decomposition results are persisted and retrievable."""

    def test_service_map_persisted(
        self, client, decompose_response: dict
    ) -> None:
        """After decompose, GET /api/service-map returns 200 with a valid
        ServiceMap containing services and a project_name."""
        resp = client.get("/api/service-map")
        assert resp.status_code == 200, (
            f"Expected 200 from /api/service-map, got {resp.status_code}: {resp.text}"
        )
        body = resp.json()
        assert "services" in body
        assert isinstance(body["services"], list)
        assert len(body["services"]) >= 1
        assert "project_name" in body
        assert len(body["project_name"]) > 0

    def test_domain_model_persisted(
        self, client, decompose_response: dict
    ) -> None:
        """After decompose, GET /api/domain-model returns 200 with a valid
        DomainModel containing entities and relationships."""
        resp = client.get("/api/domain-model")
        assert resp.status_code == 200, (
            f"Expected 200 from /api/domain-model, got {resp.status_code}: {resp.text}"
        )
        body = resp.json()
        assert "entities" in body
        assert isinstance(body["entities"], list)
        assert len(body["entities"]) >= 1
        assert "relationships" in body
        assert isinstance(body["relationships"], list)


class TestContractStubs:
    """Tests that generated contract stubs are valid OpenAPI 3.1.0 specs."""

    def test_contract_stubs_are_valid_openapi(
        self, decompose_response: dict
    ) -> None:
        """Each contract stub must be a valid OpenAPI 3.1.0 spec with
        openapi, info (title + version), and paths."""
        stubs = decompose_response["contract_stubs"]
        assert isinstance(stubs, list)
        assert len(stubs) >= 1, "Expected at least 1 contract stub"

        for i, stub in enumerate(stubs):
            assert "openapi" in stub, (
                f"Contract stub [{i}] missing 'openapi' key"
            )
            assert stub["openapi"] == "3.1.0", (
                f"Contract stub [{i}] openapi version is {stub['openapi']!r}, expected '3.1.0'"
            )
            assert "info" in stub, (
                f"Contract stub [{i}] missing 'info' key"
            )
            info = stub["info"]
            assert "title" in info, (
                f"Contract stub [{i}] info missing 'title'"
            )
            assert "version" in info, (
                f"Contract stub [{i}] info missing 'version'"
            )
            assert "paths" in stub, (
                f"Contract stub [{i}] missing 'paths' key"
            )

    def test_contract_stubs_have_paths_or_health(
        self, decompose_response: dict
    ) -> None:
        """Each contract stub must have at least one path (CRUD endpoints or
        a health endpoint)."""
        stubs = decompose_response["contract_stubs"]
        for i, stub in enumerate(stubs):
            paths = stub.get("paths", {})
            assert len(paths) >= 1, (
                f"Contract stub [{i}] ({stub.get('info', {}).get('title', '?')}) "
                f"has no paths"
            )


class TestEdgeCases:
    """Tests for error handling and edge cases."""

    def test_decompose_short_prd_fails(self, client) -> None:
        """POST /api/decompose with very short text returns 400 (ParsingError)
        because the PRD text is below the minimum length threshold."""
        resp = client.post("/api/decompose", json={"prd_text": "Too short."})
        assert resp.status_code == 400, (
            f"Expected 400 for short PRD, got {resp.status_code}: {resp.text}"
        )

    def test_decompose_empty_prd_returns_422(self, client) -> None:
        """POST /api/decompose with empty string returns 422 because
        prd_text has min_length=10 in the Pydantic model."""
        resp = client.post("/api/decompose", json={"prd_text": ""})
        assert resp.status_code == 422, (
            f"Expected 422 for empty PRD, got {resp.status_code}: {resp.text}"
        )

    def test_decompose_missing_body_returns_422(self, client) -> None:
        """POST /api/decompose with no JSON body returns 422."""
        resp = client.post("/api/decompose")
        assert resp.status_code == 422, (
            f"Expected 422 for missing body, got {resp.status_code}: {resp.text}"
        )


class TestHealthEndpoint:
    """Tests for the health check endpoint."""

    def test_health_endpoint_returns_healthy(self, client) -> None:
        """GET /api/health returns 200 with status='healthy'."""
        resp = client.get("/api/health")
        assert resp.status_code == 200, (
            f"Expected 200 from /api/health, got {resp.status_code}: {resp.text}"
        )
        body = resp.json()
        assert body["status"] == "healthy"
        assert "service_name" in body
        assert "version" in body
        assert "uptime_seconds" in body
        assert body["database"] == "connected"

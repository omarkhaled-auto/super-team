"""Parametrised integration tests for the Architect decomposition pipeline.

Exercises ``decompose_prd`` with five structurally different PRD documents
to verify the pipeline handles varying service counts, communication
styles, entity complexity, and state-machine definitions.
"""
from __future__ import annotations

import pytest

from src.shared.db.connection import ConnectionPool
from src.shared.db.schema import init_architect_db
from src.architect.storage.service_map_store import ServiceMapStore
from src.architect.storage.domain_model_store import DomainModelStore

# ---------------------------------------------------------------------------
# PRD fixtures — each >=200 characters with proper markdown structure
# ---------------------------------------------------------------------------

PRD_SIMPLE = """\
# Simple E-Commerce Platform

## Overview
A lightweight e-commerce system with two core services handling user
management and order processing. Built with Python and PostgreSQL.

## Services

### User Service
- Manages user registration and authentication
- Stores user profiles, addresses, and preferences

### Order Service
- Handles order creation and tracking
- Processes order status updates and history

## Entities

### User
- id: uuid
- email: string
- name: string
- created_at: datetime

### Order
- id: uuid
- user_id: uuid
- total: number
- status: string

### OrderItem
- id: uuid
- order_id: uuid
- product_name: string
- quantity: integer
- price: number

## Relationships
- User has many Orders
- Order has many OrderItems
"""

PRD_EVENTS = """\
# Event-Driven Notification Platform

## Overview
A microservices platform using event-driven communication between services.
Services publish and subscribe to domain events via a message broker.
Built with Python, FastAPI, and RabbitMQ for async messaging.

## Services

### User Service
- Manages user accounts and authentication
- Publishes UserCreated and UserUpdated events
- Stores user profiles and notification preferences

### Order Service
- Processes customer orders end-to-end
- Publishes OrderPlaced and OrderCompleted events
- Subscribes to UserCreated events for account linking

### Notification Service
- Sends email, SMS, and push notifications
- Subscribes to OrderPlaced and OrderCompleted events
- Subscribes to UserCreated events for welcome messages

## Entities

### User
- id: uuid
- email: string
- name: string
- notification_preferences: json

### Order
- id: uuid
- user_id: uuid
- items: list
- total: number
- status: string

### Notification
- id: uuid
- user_id: uuid
- channel: string
- message: string
- sent_at: datetime

## Events
- UserCreated: published by User Service
- UserUpdated: published by User Service
- OrderPlaced: published by Order Service
- OrderCompleted: published by Order Service

## Relationships
- User has many Orders
- User has many Notifications
- Order triggers Notifications
"""

PRD_SINGLE = """\
# Task Management Application

## Overview
A single-service CRUD application for managing tasks, tags, and categories.
Monolithic architecture using Python with FastAPI and SQLite as the database.

## Services

### Task Management Service
- Full CRUD operations for tasks, tags, and categories
- Supports filtering and search across tasks
- Handles task assignment and status tracking
- Manages tag-based categorisation of tasks

## Entities

### Task
- id: uuid
- title: string
- description: string
- status: string
- priority: string
- due_date: datetime
- created_at: datetime

### Tag
- id: uuid
- name: string
- color: string

### Category
- id: uuid
- name: string
- description: string
- parent_id: uuid

## Relationships
- Task belongs to Category
- Task has many Tags (many-to-many)
- Category has many sub-Categories
"""

PRD_COMPLEX = """\
# Enterprise Marketplace Platform

## Overview
A large-scale marketplace with five microservices handling users, products,
orders, payments, and shipping. Built with Python microservices, PostgreSQL
per service, and Redis for caching. API Gateway handles routing.

## Services

### User Service
- User registration, authentication, and profile management
- Role-based access control (buyer, seller, admin)
- Session and token management

### Product Service
- Product catalog with full-text search
- Inventory management and stock tracking
- Seller product listing and management

### Order Service
- Shopping cart and checkout flow
- Order lifecycle management
- Order history and reporting

### Payment Service
- Payment processing and gateway integration
- Refund and chargeback handling
- Invoice generation and tax calculation

### Shipping Service
- Shipping rate calculation and carrier selection
- Shipment tracking and delivery confirmation
- Return and exchange logistics

## Entities

### User
- id: uuid
- email: string
- name: string
- role: string

### Product
- id: uuid
- name: string
- description: string
- price: number
- stock: integer
- seller_id: uuid

### Order
- id: uuid
- user_id: uuid
- total: number
- status: string

### OrderItem
- id: uuid
- order_id: uuid
- product_id: uuid
- quantity: integer
- unit_price: number

### Payment
- id: uuid
- order_id: uuid
- amount: number
- method: string
- status: string

### Invoice
- id: uuid
- payment_id: uuid
- issued_at: datetime
- total: number

### Shipment
- id: uuid
- order_id: uuid
- carrier: string
- tracking_number: string
- status: string

### Address
- id: uuid
- user_id: uuid
- street: string
- city: string
- country: string
- postal_code: string

## Relationships
- User has many Orders
- User has many Addresses
- Order has many OrderItems
- OrderItem references Product
- Order has one Payment
- Payment has one Invoice
- Order has one Shipment
- Product belongs to User (seller)
"""

PRD_STATE_MACHINES = """\
# Order and Payment Processing System

## Overview
A system focusing on complex state transitions for order and payment
lifecycles. Services coordinate through well-defined state machines
to ensure data consistency. Built with Python, FastAPI, and PostgreSQL.

## Services

### Order Service
- Manages the full order lifecycle with explicit state transitions
- Validates state changes and enforces business rules
- Tracks order history and audit trail

### Payment Service
- Handles payment processing with state-tracked transactions
- Manages refund workflows with approval gates
- Records all payment state transitions for compliance

### Fulfillment Service
- Manages warehouse picking and packing
- Coordinates with shipping carriers
- Handles delivery confirmation and exceptions

## Entities

### Order
- id: uuid
- user_id: uuid
- total: number
- status: string
- created_at: datetime

### Payment
- id: uuid
- order_id: uuid
- amount: number
- method: string
- status: string

### Fulfillment
- id: uuid
- order_id: uuid
- warehouse_id: string
- status: string

## State Machines

### Order States
- pending -> paid: Payment confirmed
- paid -> shipped: Shipment dispatched
- shipped -> delivered: Delivery confirmed
- pending -> cancelled: Customer cancellation
- paid -> cancelled: Cancellation with refund

### Payment States
- initiated -> completed: Payment processed successfully
- initiated -> failed: Payment processor declined
- completed -> refunded: Full refund issued
- completed -> partially_refunded: Partial refund issued

## Relationships
- Order has one Payment
- Order has one Fulfillment
- Payment belongs to Order
"""

# ---------------------------------------------------------------------------
# Parametrise IDs — kept short for readable test output
# ---------------------------------------------------------------------------

ALL_PRDS = [
    pytest.param(PRD_SIMPLE, id="simple"),
    pytest.param(PRD_EVENTS, id="events"),
    pytest.param(PRD_SINGLE, id="single"),
    pytest.param(PRD_COMPLEX, id="complex"),
    pytest.param(PRD_STATE_MACHINES, id="state-machines"),
]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def architect_mcp(tmp_path, monkeypatch):
    """Architect MCP module wired to an isolated temp SQLite database."""
    db_path = str(tmp_path / "pipeline_test.db")
    monkeypatch.setenv("DATABASE_PATH", db_path)

    import src.architect.mcp_server as mod

    pool = ConnectionPool(db_path)
    init_architect_db(pool)

    monkeypatch.setattr(mod, "pool", pool)
    monkeypatch.setattr(mod, "service_map_store", ServiceMapStore(pool))
    monkeypatch.setattr(mod, "domain_model_store", DomainModelStore(pool))

    yield mod

    pool.close()


# ---------------------------------------------------------------------------
# Parametrised integration tests
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("prd_text", ALL_PRDS)
def test_pipeline_produces_service_map(architect_mcp, prd_text: str):
    """decompose_prd returns a service_map with project_name and services."""
    result = architect_mcp.decompose_prd(prd_text)

    assert "error" not in result, f"Pipeline returned error: {result.get('error')}"

    service_map = result["service_map"]
    assert isinstance(service_map, dict)
    assert "project_name" in service_map, "service_map missing project_name"
    assert isinstance(service_map["project_name"], str)
    assert len(service_map["project_name"]) > 0

    assert "services" in service_map, "service_map missing services list"
    assert isinstance(service_map["services"], list)
    assert len(service_map["services"]) > 0


@pytest.mark.parametrize("prd_text", ALL_PRDS)
def test_pipeline_produces_domain_model(architect_mcp, prd_text: str):
    """decompose_prd returns a domain_model with a non-empty entities list."""
    result = architect_mcp.decompose_prd(prd_text)

    assert "error" not in result, f"Pipeline returned error: {result.get('error')}"

    domain_model = result["domain_model"]
    assert isinstance(domain_model, dict)
    assert "entities" in domain_model, "domain_model missing entities"
    assert isinstance(domain_model["entities"], list)
    assert len(domain_model["entities"]) > 0


@pytest.mark.parametrize("prd_text", ALL_PRDS)
def test_pipeline_produces_contract_stubs(architect_mcp, prd_text: str):
    """decompose_prd returns a non-empty list of contract stubs."""
    result = architect_mcp.decompose_prd(prd_text)

    assert "error" not in result, f"Pipeline returned error: {result.get('error')}"

    contract_stubs = result["contract_stubs"]
    assert isinstance(contract_stubs, list)
    assert len(contract_stubs) > 0, "contract_stubs should be non-empty"


@pytest.mark.parametrize("prd_text", ALL_PRDS)
def test_pipeline_no_validation_errors(architect_mcp, prd_text: str):
    """decompose_prd returns no critical validation issues."""
    result = architect_mcp.decompose_prd(prd_text)

    assert "error" not in result, f"Pipeline returned error: {result.get('error')}"

    validation_issues = result["validation_issues"]
    assert isinstance(validation_issues, list)
    # Allow informational/warning issues but fail on errors
    errors = [
        issue for issue in validation_issues
        if isinstance(issue, dict) and issue.get("severity") == "error"
    ]
    assert len(errors) == 0, (
        f"Found {len(errors)} validation error(s): {errors}"
    )

# TaskTracker PRD — Sample Application for Run 4 Verification

## Overview

TaskTracker is a multi-service task management application consisting of three
microservices: **auth-service**, **order-service**, and **notification-service**.
Each service is implemented in Python using FastAPI with a PostgreSQL database
backend. Services communicate via REST APIs and asynchronous events published
through Redis Pub/Sub.

---

## Technology Stack

| Layer          | Technology        | Version  |
|----------------|-------------------|----------|
| Language       | Python            | 3.12     |
| Framework      | FastAPI           | 0.129.0  |
| Database       | PostgreSQL        | 16       |
| Cache/Pubsub   | Redis             | 7.2      |
| ORM            | SQLAlchemy        | 2.0      |
| Auth           | JWT (python-jose) | latest   |
| Containerisation | Docker Compose  | 3.8      |

---

## Service 1: auth-service

### Description

The auth-service manages user registration, authentication, and JWT token
issuance. It is the identity provider for all other services in the system.

### Data Model

#### User

| Field        | Type     | Constraints            |
|--------------|----------|------------------------|
| id           | UUID     | Primary key            |
| email        | string   | Unique, not null       |
| password_hash| string   | Not null (bcrypt)      |
| name         | string   | Not null               |
| created_at   | datetime | Auto-generated (UTC)   |
| updated_at   | datetime | Auto-updated (UTC)     |

### Endpoints

#### POST /register

Register a new user account.

- **Request Body**: `{ "email": string, "password": string, "name": string }`
- **Response 201**: `{ "id": UUID, "email": string, "created_at": ISO8601 }`
- **Response 409**: `{ "detail": "Email already registered" }`

#### POST /login

Authenticate a user and issue JWT tokens.

- **Request Body**: `{ "email": string, "password": string }`
- **Response 200**: `{ "access_token": string, "refresh_token": string }`
- **Response 401**: `{ "detail": "Invalid credentials" }`

#### GET /users/me

Retrieve the authenticated user's profile.

- **Headers**: `Authorization: Bearer <access_token>`
- **Response 200**: `{ "id": UUID, "email": string, "name": string, "created_at": ISO8601 }`
- **Response 401**: `{ "detail": "Not authenticated" }`

#### GET /health

Service health check endpoint.

- **Response 200**: `{ "status": "healthy" }`

### Inter-Service Contract

- Issues JWT tokens with `sub` = user UUID, `exp` = 30 minutes
- Other services validate JWTs using a shared secret or public key
- Token payload: `{ "sub": UUID, "email": string, "exp": int }`

---

## Service 2: order-service

### Description

The order-service manages customer orders. It validates incoming requests
against the auth-service JWT and publishes order lifecycle events to Redis
for downstream consumers.

### Data Model

#### Order

| Field      | Type     | Constraints          |
|------------|----------|----------------------|
| id         | UUID     | Primary key          |
| user_id    | UUID     | Foreign key (User)   |
| status     | string   | Enum: created, confirmed, shipped, delivered, cancelled |
| items      | JSON     | Array of OrderItem   |
| total      | decimal  | Computed from items  |
| created_at | datetime | Auto-generated (UTC) |
| updated_at | datetime | Auto-updated (UTC)   |

#### OrderItem

| Field      | Type    | Constraints   |
|------------|---------|---------------|
| product_id | string  | Not null      |
| quantity   | integer | > 0           |
| price      | decimal | >= 0          |

### Endpoints

#### POST /orders

Create a new order (requires JWT authentication).

- **Headers**: `Authorization: Bearer <access_token>`
- **Request Body**: `{ "items": [{ "product_id": string, "quantity": int, "price": float }] }`
- **Response 201**: `{ "id": UUID, "status": "created", "items": [...], "total": float }`
- **Response 401**: `{ "detail": "Not authenticated" }`

#### GET /orders/{id}

Retrieve a specific order by ID.

- **Headers**: `Authorization: Bearer <access_token>`
- **Response 200**: `{ "id": UUID, "status": string, "items": [...], "total": float, "user_id": UUID, "created_at": ISO8601 }`
- **Response 404**: `{ "detail": "Order not found" }`

#### PUT /orders/{id}

Update order status.

- **Headers**: `Authorization: Bearer <access_token>`
- **Request Body**: `{ "status": string }`
- **Response 200**: `{ "id": UUID, "status": string, "updated_at": ISO8601 }`
- **Response 404**: `{ "detail": "Order not found" }`

#### GET /health

Service health check endpoint.

- **Response 200**: `{ "status": "healthy" }`

### Events Published

| Event           | Channel          | Payload                                      |
|-----------------|------------------|----------------------------------------------|
| order.created   | order/created    | `{ order_id, user_id, items, total, created_at }` |
| order.shipped   | order/shipped    | `{ order_id, user_id, shipped_at, tracking_number }` |

---

## Service 3: notification-service

### Description

The notification-service listens for events from other services and delivers
notifications to users via email or in-app messaging. It also provides an
API for sending direct notifications and querying notification history.

### Data Model

#### Notification

| Field      | Type     | Constraints                     |
|------------|----------|---------------------------------|
| id         | UUID     | Primary key                     |
| user_id    | UUID     | Target user                     |
| type       | string   | Enum: email, in_app, sms        |
| subject    | string   | Not null                        |
| body       | string   | Not null                        |
| status     | string   | Enum: pending, sent, failed     |
| created_at | datetime | Auto-generated (UTC)            |

### Endpoints

#### POST /notify

Send a notification to a user.

- **Headers**: `Authorization: Bearer <access_token>`
- **Request Body**: `{ "user_id": UUID, "type": string, "subject": string, "body": string }`
- **Response 201**: `{ "id": UUID, "status": "pending" }`
- **Response 400**: `{ "detail": "Invalid notification type" }`

#### GET /notifications

List notifications for the authenticated user.

- **Headers**: `Authorization: Bearer <access_token>`
- **Response 200**: `[{ "id": UUID, "type": string, "subject": string, "status": string, "created_at": ISO8601 }]`

#### GET /health

Service health check endpoint.

- **Response 200**: `{ "status": "healthy" }`

### Event Subscriptions

| Event         | Action                                         |
|---------------|-------------------------------------------------|
| order.created | Send confirmation notification to order owner  |
| order.shipped | Send shipping notification with tracking info  |

---

## Inter-Service Contracts

### JWT Authentication Flow

1. Client calls `POST /login` on auth-service to obtain access token
2. Client includes `Authorization: Bearer <token>` on all requests to order-service and notification-service
3. order-service and notification-service validate the JWT signature and extract `sub` (user_id)

### Event Contract

- Publisher: order-service
- Subscriber: notification-service
- Transport: Redis Pub/Sub
- Serialisation: JSON
- Channels: `order/created`, `order/shipped`

---

## Deployment

All three services are deployed as Docker containers orchestrated via
Docker Compose. Each service has its own PostgreSQL database instance.
Redis is shared across services for event transport.

```yaml
services:
  auth-service:
    build: ./auth-service
    ports: ["8001:8000"]
    environment:
      DATABASE_URL: postgresql://...
      JWT_SECRET: ${JWT_SECRET}

  order-service:
    build: ./order-service
    ports: ["8002:8000"]
    environment:
      DATABASE_URL: postgresql://...
      JWT_SECRET: ${JWT_SECRET}

  notification-service:
    build: ./notification-service
    ports: ["8003:8000"]
    environment:
      DATABASE_URL: postgresql://...
      REDIS_URL: redis://redis:6379

  postgres:
    image: postgres:16
    environment:
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}

  redis:
    image: redis:7.2
```

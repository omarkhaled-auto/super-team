# Product Requirements Document: ShopFlow E-Commerce Platform

**Version:** 1.0.0
**Date:** 2026-02-17
**Author:** Platform Engineering Team
**Status:** Approved

---

## 1. Overview

ShopFlow is a microservices-based e-commerce platform designed for high-throughput order processing. The system is decomposed into three core services that communicate via synchronous REST APIs and asynchronous events over a message broker.

### 1.1 Goals

- Enable user registration and secure authentication via JWT tokens.
- Support the full order lifecycle from creation through delivery with an auditable state machine.
- Deliver real-time notifications to customers via email and SMS at key order milestones.
- Maintain clear service boundaries with well-defined API contracts and event schemas.

### 1.2 Architecture Summary

```
+-----------------+       REST        +------------------+
|  auth-service   |<------------------+  order-service   |
|  (Port 3001)    |  /auth/validate   |  (Port 3002)     |
+-----------------+                   +--------+---------+
                                               |
                                               | Events (AMQP)
                                               | OrderCreated
                                               | OrderShipped
                                               v
                                      +--------+---------+
                                      | notification-svc |
                                      |  (Port 3003)     |
                                      +------------------+
                                               |
                                               | REST
                                               v
                                      +------------------+
                                      |  order-service   |
                                      |  GET /orders/:id |
                                      +------------------+
```

---

## 2. Services

### 2.1 auth-service

**Purpose:** Manages user accounts, handles registration and login, issues and validates JWT access tokens.

**Tech Stack:**
- Runtime: Node.js 20 LTS
- Framework: Express.js 4.x
- Database: PostgreSQL 16
- ORM: Prisma 5.x
- Auth: jsonwebtoken, bcryptjs
- Validation: Zod

**Port:** 3001

### 2.2 order-service

**Purpose:** Manages the full order lifecycle including creation, state transitions, and order queries. Publishes domain events when order state changes occur.

**Tech Stack:**
- Runtime: Node.js 20 LTS
- Framework: Express.js 4.x
- Database: PostgreSQL 16
- ORM: Prisma 5.x
- Message Broker: RabbitMQ 3.13 (amqplib)
- Validation: Zod

**Port:** 3002

### 2.3 notification-service

**Purpose:** Listens for order domain events and delivers notifications to customers via email and SMS. Maintains a log of all sent notifications for auditing.

**Tech Stack:**
- Runtime: Node.js 20 LTS
- Framework: Express.js 4.x
- Database: PostgreSQL 16
- ORM: Prisma 5.x
- Message Broker: RabbitMQ 3.13 (amqplib)
- Email Provider: AWS SES
- SMS Provider: Twilio
- Validation: Zod

**Port:** 3003

---

## 3. Entities

### 3.1 User (auth-service)

| Field          | Type      | Constraints                        | Description                        |
|----------------|-----------|------------------------------------|------------------------------------|
| id             | UUID      | Primary Key, auto-generated        | Unique user identifier             |
| email          | String    | Unique, not null, max 255 chars    | User email address                 |
| password_hash  | String    | Not null                           | Bcrypt-hashed password             |
| first_name     | String    | Not null, max 100 chars            | User first name                    |
| last_name      | String    | Not null, max 100 chars            | User last name                     |
| phone          | String    | Nullable, max 20 chars             | Phone number for SMS notifications |
| role           | Enum      | Values: customer, admin            | User role for authorization        |
| is_active      | Boolean   | Default: true                      | Soft-delete flag                   |
| created_at     | Timestamp | Auto-set on creation               | Account creation time              |
| updated_at     | Timestamp | Auto-set on update                 | Last modification time             |

**Indexes:**
- Unique index on `email`
- Index on `created_at`

### 3.2 Order (order-service)

| Field          | Type      | Constraints                                    | Description                          |
|----------------|-----------|------------------------------------------------|--------------------------------------|
| id             | UUID      | Primary Key, auto-generated                    | Unique order identifier              |
| user_id        | UUID      | Not null, foreign reference (logical)          | Reference to User in auth-service    |
| status         | Enum      | Values: pending, confirmed, shipped, delivered | Current state of the order           |
| items          | JSONB     | Not null                                       | Array of order line items            |
| shipping_address | JSONB   | Not null                                       | Structured shipping address          |
| total_amount   | Decimal   | Not null, precision 10 scale 2                 | Total order value in USD             |
| currency       | String    | Not null, default: "USD", max 3 chars          | ISO 4217 currency code               |
| notes          | String    | Nullable, max 500 chars                        | Customer notes for the order         |
| confirmed_at   | Timestamp | Nullable                                       | When order was confirmed             |
| shipped_at     | Timestamp | Nullable                                       | When order was shipped               |
| delivered_at   | Timestamp | Nullable                                       | When order was delivered             |
| created_at     | Timestamp | Auto-set on creation                           | Order creation time                  |
| updated_at     | Timestamp | Auto-set on update                             | Last modification time               |

**Items JSONB Schema:**
```json
[
  {
    "product_id": "uuid",
    "product_name": "string",
    "quantity": "integer (min 1)",
    "unit_price": "decimal",
    "subtotal": "decimal"
  }
]
```

**Shipping Address JSONB Schema:**
```json
{
  "street": "string",
  "city": "string",
  "state": "string",
  "zip_code": "string",
  "country": "string (ISO 3166-1 alpha-2)"
}
```

**Indexes:**
- Index on `user_id`
- Index on `status`
- Index on `created_at`
- Composite index on `(user_id, status)`

### 3.3 Notification (notification-service)

| Field          | Type      | Constraints                                    | Description                          |
|----------------|-----------|------------------------------------------------|--------------------------------------|
| id             | UUID      | Primary Key, auto-generated                    | Unique notification identifier       |
| user_id        | UUID      | Not null                                       | Recipient user identifier            |
| order_id       | UUID      | Nullable                                       | Related order identifier             |
| channel        | Enum      | Values: email, sms                             | Delivery channel                     |
| type           | String    | Not null, max 100 chars                        | Notification type key                |
| recipient      | String    | Not null, max 255 chars                        | Email address or phone number        |
| subject        | String    | Nullable, max 255 chars                        | Email subject line (null for SMS)    |
| body           | Text      | Not null                                       | Rendered notification content        |
| status         | Enum      | Values: queued, sent, failed                   | Delivery status                      |
| provider_ref   | String    | Nullable, max 255 chars                        | External provider message ID         |
| error_message  | String    | Nullable, max 1000 chars                       | Error details on failure             |
| sent_at        | Timestamp | Nullable                                       | Actual delivery time                 |
| created_at     | Timestamp | Auto-set on creation                           | Record creation time                 |

**Indexes:**
- Index on `user_id`
- Index on `order_id`
- Index on `status`
- Index on `created_at`

---

## 4. API Specifications

### 4.1 auth-service Endpoints

#### POST /auth/register

Create a new user account.

**Request Body:**
```json
{
  "email": "jane.doe@example.com",
  "password": "S3cur3P@ssw0rd!",
  "first_name": "Jane",
  "last_name": "Doe",
  "phone": "+15551234567"
}
```

**Validation Rules:**
- `email`: Valid email format, required
- `password`: Minimum 8 characters, at least one uppercase, one lowercase, one digit, one special character, required
- `first_name`: 1-100 characters, required
- `last_name`: 1-100 characters, required
- `phone`: E.164 format, optional

**Response (201 Created):**
```json
{
  "id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "email": "jane.doe@example.com",
  "first_name": "Jane",
  "last_name": "Doe",
  "phone": "+15551234567",
  "role": "customer",
  "created_at": "2026-02-17T10:30:00.000Z"
}
```

**Error Responses:**
- `400 Bad Request` -- Validation errors
- `409 Conflict` -- Email already registered

---

#### POST /auth/login

Authenticate a user and return a JWT token pair.

**Request Body:**
```json
{
  "email": "jane.doe@example.com",
  "password": "S3cur3P@ssw0rd!"
}
```

**Response (200 OK):**
```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIs...",
  "refresh_token": "eyJhbGciOiJIUzI1NiIs...",
  "token_type": "Bearer",
  "expires_in": 3600
}
```

**Error Responses:**
- `400 Bad Request` -- Missing fields
- `401 Unauthorized` -- Invalid credentials
- `403 Forbidden` -- Account deactivated

**JWT Access Token Payload:**
```json
{
  "sub": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "email": "jane.doe@example.com",
  "role": "customer",
  "iat": 1739789400,
  "exp": 1739793000
}
```

- Access token TTL: 1 hour
- Refresh token TTL: 30 days
- Signing algorithm: HS256
- Secret: Loaded from environment variable `JWT_SECRET`

---

#### POST /auth/refresh

Exchange a valid refresh token for a new token pair.

**Request Body:**
```json
{
  "refresh_token": "eyJhbGciOiJIUzI1NiIs..."
}
```

**Response (200 OK):**
```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIs...",
  "refresh_token": "eyJhbGciOiJIUzI1NiIs...",
  "token_type": "Bearer",
  "expires_in": 3600
}
```

**Error Responses:**
- `401 Unauthorized` -- Invalid or expired refresh token

---

#### POST /auth/validate

Validate a JWT access token and return the decoded user claims. This endpoint is called by other services for authentication verification.

**Request Headers:**
```
Authorization: Bearer eyJhbGciOiJIUzI1NiIs...
```

**Response (200 OK):**
```json
{
  "valid": true,
  "user": {
    "id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
    "email": "jane.doe@example.com",
    "role": "customer"
  }
}
```

**Error Responses:**
- `401 Unauthorized` -- Missing, malformed, or expired token

---

#### GET /auth/users/:id

Retrieve user profile by ID. Requires a valid JWT. Users can only retrieve their own profile unless they have the admin role.

**Request Headers:**
```
Authorization: Bearer eyJhbGciOiJIUzI1NiIs...
```

**Response (200 OK):**
```json
{
  "id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "email": "jane.doe@example.com",
  "first_name": "Jane",
  "last_name": "Doe",
  "phone": "+15551234567",
  "role": "customer",
  "is_active": true,
  "created_at": "2026-02-17T10:30:00.000Z",
  "updated_at": "2026-02-17T10:30:00.000Z"
}
```

**Error Responses:**
- `401 Unauthorized` -- Invalid token
- `403 Forbidden` -- Not authorized to view this profile
- `404 Not Found` -- User does not exist

---

### 4.2 order-service Endpoints

All order-service endpoints require a valid JWT in the `Authorization` header. The order-service validates tokens by calling `POST auth-service/auth/validate` on every inbound request.

#### POST /orders

Create a new order. The authenticated user's ID is extracted from the validated JWT claims.

**Request Headers:**
```
Authorization: Bearer eyJhbGciOiJIUzI1NiIs...
```

**Request Body:**
```json
{
  "items": [
    {
      "product_id": "f47ac10b-58cc-4372-a567-0e02b2c3d479",
      "product_name": "Wireless Headphones",
      "quantity": 2,
      "unit_price": 49.99
    },
    {
      "product_id": "6ba7b810-9dad-11d1-80b4-00c04fd430c8",
      "product_name": "USB-C Cable",
      "quantity": 1,
      "unit_price": 12.99
    }
  ],
  "shipping_address": {
    "street": "742 Evergreen Terrace",
    "city": "Springfield",
    "state": "IL",
    "zip_code": "62704",
    "country": "US"
  },
  "currency": "USD",
  "notes": "Please leave at the front door."
}
```

**Validation Rules:**
- `items`: Non-empty array, required. Each item must have valid `product_id` (UUID), `product_name` (1-200 chars), `quantity` (integer >= 1), and `unit_price` (decimal > 0).
- `shipping_address`: All fields required except `state` which is optional for non-US addresses.
- `currency`: ISO 4217 code, defaults to "USD".
- `notes`: Max 500 characters, optional.

**Server-Side Computation:**
- `subtotal` for each item is computed as `quantity * unit_price`.
- `total_amount` is the sum of all item subtotals.
- `status` is set to `pending`.

**Response (201 Created):**
```json
{
  "id": "b2c3d4e5-f6a7-8901-bcde-f12345678901",
  "user_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "status": "pending",
  "items": [
    {
      "product_id": "f47ac10b-58cc-4372-a567-0e02b2c3d479",
      "product_name": "Wireless Headphones",
      "quantity": 2,
      "unit_price": 49.99,
      "subtotal": 99.98
    },
    {
      "product_id": "6ba7b810-9dad-11d1-80b4-00c04fd430c8",
      "product_name": "USB-C Cable",
      "quantity": 1,
      "unit_price": 12.99,
      "subtotal": 12.99
    }
  ],
  "shipping_address": {
    "street": "742 Evergreen Terrace",
    "city": "Springfield",
    "state": "IL",
    "zip_code": "62704",
    "country": "US"
  },
  "total_amount": 112.97,
  "currency": "USD",
  "notes": "Please leave at the front door.",
  "confirmed_at": null,
  "shipped_at": null,
  "delivered_at": null,
  "created_at": "2026-02-17T11:00:00.000Z",
  "updated_at": "2026-02-17T11:00:00.000Z"
}
```

**Side Effects:**
- Publishes an `OrderCreated` event to the `order.events` exchange (see Section 5.1).

**Error Responses:**
- `400 Bad Request` -- Validation errors
- `401 Unauthorized` -- Invalid or missing token

---

#### GET /orders

List orders for the authenticated user with pagination.

**Request Headers:**
```
Authorization: Bearer eyJhbGciOiJIUzI1NiIs...
```

**Query Parameters:**
| Parameter | Type    | Default | Description                     |
|-----------|---------|---------|---------------------------------|
| page      | Integer | 1       | Page number (1-based)           |
| limit     | Integer | 20      | Items per page (max 100)        |
| status    | String  | (all)   | Filter by order status          |
| sort_by   | String  | created_at | Sort field                   |
| sort_dir  | String  | desc    | Sort direction: asc or desc     |

**Response (200 OK):**
```json
{
  "data": [
    {
      "id": "b2c3d4e5-f6a7-8901-bcde-f12345678901",
      "status": "pending",
      "total_amount": 112.97,
      "currency": "USD",
      "created_at": "2026-02-17T11:00:00.000Z"
    }
  ],
  "pagination": {
    "page": 1,
    "limit": 20,
    "total_items": 1,
    "total_pages": 1
  }
}
```

**Error Responses:**
- `401 Unauthorized` -- Invalid or missing token

---

#### GET /orders/:id

Retrieve a single order by ID. Users may only access their own orders; admin users may access any order.

**Request Headers:**
```
Authorization: Bearer eyJhbGciOiJIUzI1NiIs...
```

**Response (200 OK):**
Returns the full order object (same schema as the POST /orders response).

**Error Responses:**
- `401 Unauthorized` -- Invalid or missing token
- `403 Forbidden` -- User does not own this order
- `404 Not Found` -- Order does not exist

---

#### PATCH /orders/:id/status

Transition an order to the next state. Only admin users may perform state transitions.

**Request Headers:**
```
Authorization: Bearer eyJhbGciOiJIUzI1NiIs...
```

**Request Body:**
```json
{
  "status": "confirmed"
}
```

**Validation Rules:**
- `status`: Must be a valid next state according to the order state machine (see Section 6).
- Only transitions defined in the state machine are permitted.

**Response (200 OK):**
```json
{
  "id": "b2c3d4e5-f6a7-8901-bcde-f12345678901",
  "status": "confirmed",
  "confirmed_at": "2026-02-17T14:00:00.000Z",
  "updated_at": "2026-02-17T14:00:00.000Z"
}
```

**Side Effects:**
- If transitioning to `shipped`, publishes an `OrderShipped` event (see Section 5.2).
- Updates the corresponding timestamp field (`confirmed_at`, `shipped_at`, or `delivered_at`).

**Error Responses:**
- `400 Bad Request` -- Invalid state transition
- `401 Unauthorized` -- Invalid or missing token
- `403 Forbidden` -- Requires admin role
- `404 Not Found` -- Order does not exist
- `409 Conflict` -- Order is already in the requested state

---

### 4.3 notification-service Endpoints

#### GET /notifications

List notifications for a user. Requires a valid JWT.

**Request Headers:**
```
Authorization: Bearer eyJhbGciOiJIUzI1NiIs...
```

**Query Parameters:**
| Parameter | Type    | Default | Description                     |
|-----------|---------|---------|---------------------------------|
| page      | Integer | 1       | Page number                     |
| limit     | Integer | 20      | Items per page (max 100)        |
| channel   | String  | (all)   | Filter by channel: email or sms |
| order_id  | UUID    | (none)  | Filter by related order         |

**Response (200 OK):**
```json
{
  "data": [
    {
      "id": "c3d4e5f6-a7b8-9012-cdef-123456789012",
      "user_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
      "order_id": "b2c3d4e5-f6a7-8901-bcde-f12345678901",
      "channel": "email",
      "type": "order_created",
      "recipient": "jane.doe@example.com",
      "subject": "Order Confirmation - #b2c3d4e5",
      "status": "sent",
      "sent_at": "2026-02-17T11:00:05.000Z",
      "created_at": "2026-02-17T11:00:01.000Z"
    }
  ],
  "pagination": {
    "page": 1,
    "limit": 20,
    "total_items": 1,
    "total_pages": 1
  }
}
```

---

#### GET /notifications/:id

Retrieve a single notification by ID.

**Request Headers:**
```
Authorization: Bearer eyJhbGciOiJIUzI1NiIs...
```

**Response (200 OK):**
```json
{
  "id": "c3d4e5f6-a7b8-9012-cdef-123456789012",
  "user_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "order_id": "b2c3d4e5-f6a7-8901-bcde-f12345678901",
  "channel": "email",
  "type": "order_created",
  "recipient": "jane.doe@example.com",
  "subject": "Order Confirmation - #b2c3d4e5",
  "body": "<html>...<p>Your order #b2c3d4e5 has been placed.</p>...</html>",
  "status": "sent",
  "provider_ref": "ses-msg-01HQXYZ",
  "error_message": null,
  "sent_at": "2026-02-17T11:00:05.000Z",
  "created_at": "2026-02-17T11:00:01.000Z"
}
```

**Error Responses:**
- `401 Unauthorized` -- Invalid or missing token
- `404 Not Found` -- Notification does not exist

---

## 5. Event-Driven Contracts

All events are published to a RabbitMQ topic exchange named `order.events`. Notification-service binds queues using routing key patterns.

**Exchange Configuration:**
- Exchange name: `order.events`
- Exchange type: `topic`
- Durable: `true`

**Queue Bindings (notification-service):**
| Queue Name                        | Routing Key      |
|-----------------------------------|------------------|
| `notifications.order.created`     | `order.created`  |
| `notifications.order.shipped`     | `order.shipped`  |

### 5.1 OrderCreated Event

**Published by:** order-service
**Consumed by:** notification-service
**Routing Key:** `order.created`
**Trigger:** A new order is successfully persisted with status `pending`.

**Event Schema:**
```json
{
  "event_id": "d4e5f6a7-b8c9-0123-def0-123456789abc",
  "event_type": "OrderCreated",
  "timestamp": "2026-02-17T11:00:00.000Z",
  "version": "1.0",
  "payload": {
    "order_id": "b2c3d4e5-f6a7-8901-bcde-f12345678901",
    "user_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
    "status": "pending",
    "total_amount": 112.97,
    "currency": "USD",
    "items_count": 2,
    "shipping_address": {
      "city": "Springfield",
      "state": "IL",
      "country": "US"
    }
  }
}
```

**Consumer Behavior (notification-service):**
1. Receive the `OrderCreated` event.
2. Call `GET order-service/orders/:id` using a service-to-service token to fetch the full order details.
3. Call `GET auth-service/auth/users/:id` using a service-to-service token to fetch the user's email and phone.
4. Render an order confirmation email template with the order details.
5. Send the email via AWS SES.
6. If the user has a phone number on file, also send an SMS via Twilio.
7. Persist a Notification record for each channel used.
8. Acknowledge the message upon successful processing.

**Retry Policy:**
- Max retries: 3
- Backoff: Exponential (1s, 4s, 16s)
- Dead-letter exchange: `order.events.dlx`
- Dead-letter routing key: `order.created.failed`

---

### 5.2 OrderShipped Event

**Published by:** order-service
**Consumed by:** notification-service
**Routing Key:** `order.shipped`
**Trigger:** An order transitions from `confirmed` to `shipped`.

**Event Schema:**
```json
{
  "event_id": "e5f6a7b8-c9d0-1234-ef01-23456789abcd",
  "event_type": "OrderShipped",
  "timestamp": "2026-02-18T09:30:00.000Z",
  "version": "1.0",
  "payload": {
    "order_id": "b2c3d4e5-f6a7-8901-bcde-f12345678901",
    "user_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
    "status": "shipped",
    "shipped_at": "2026-02-18T09:30:00.000Z",
    "shipping_address": {
      "city": "Springfield",
      "state": "IL",
      "country": "US"
    }
  }
}
```

**Consumer Behavior (notification-service):**
1. Receive the `OrderShipped` event.
2. Call `GET order-service/orders/:id` to fetch the complete order details.
3. Call `GET auth-service/auth/users/:id` to fetch recipient contact information.
4. Render a shipment notification email with order and shipping details.
5. Send the email via AWS SES.
6. If the user has a phone number, send an SMS via Twilio.
7. Persist Notification records.
8. Acknowledge the message.

**Retry Policy:**
- Same as OrderCreated (see Section 5.1).

---

## 6. Order State Machine

### 6.1 State Diagram

```
                    +-----------+
                    |           |
     POST /orders  |  pending  |
     ------------->|           |
                    +-----+-----+
                          |
                          | PATCH /orders/:id/status { "status": "confirmed" }
                          v
                    +-----+-----+
                    |           |
                    | confirmed |
                    |           |
                    +-----+-----+
                          |
                          | PATCH /orders/:id/status { "status": "shipped" }
                          | [publishes OrderShipped event]
                          v
                    +-----+-----+
                    |           |
                    |  shipped  |
                    |           |
                    +-----+-----+
                          |
                          | PATCH /orders/:id/status { "status": "delivered" }
                          v
                    +-----+-----+
                    |           |
                    | delivered |
                    |           |
                    +-----------+
```

### 6.2 Transition Rules

| Current State | Allowed Next State | Side Effects                         | Required Role |
|---------------|--------------------|--------------------------------------|---------------|
| pending       | confirmed          | Sets `confirmed_at` timestamp        | admin         |
| confirmed     | shipped            | Sets `shipped_at`, publishes event   | admin         |
| shipped       | delivered          | Sets `delivered_at` timestamp        | admin         |

**Invalid Transitions (return 400 Bad Request):**
- Any backward transition (e.g., `shipped` to `confirmed`)
- Skipping states (e.g., `pending` to `shipped`)
- Transitioning from a terminal state (`delivered`)
- Transitioning to the same state (return 409 Conflict)

### 6.3 State Invariants

- An order in `pending` state has `confirmed_at = null`, `shipped_at = null`, `delivered_at = null`.
- An order in `confirmed` state has `confirmed_at != null`, `shipped_at = null`, `delivered_at = null`.
- An order in `shipped` state has `confirmed_at != null`, `shipped_at != null`, `delivered_at = null`.
- An order in `delivered` state has all three timestamps set to non-null values.

---

## 7. Cross-Service API Contracts

### 7.1 Contract: order-service calls auth-service for token validation

**Consumer:** order-service
**Provider:** auth-service
**Endpoint:** `POST http://auth-service:3001/auth/validate`

**Contract:**
- order-service sends every inbound request's JWT in the `Authorization` header.
- auth-service responds with a `200 OK` containing `{ "valid": true, "user": { "id", "email", "role" } }` for valid tokens.
- auth-service responds with `401 Unauthorized` for invalid, expired, or malformed tokens.
- order-service rejects the inbound request with `401 Unauthorized` if auth-service returns a non-200 status.

**SLA:**
- auth-service must respond to validation requests within 50ms at the 99th percentile.
- auth-service must maintain 99.99% availability for this endpoint.

### 7.2 Contract: notification-service calls order-service for order details

**Consumer:** notification-service
**Provider:** order-service
**Endpoint:** `GET http://order-service:3002/orders/:id`

**Contract:**
- notification-service authenticates using a service-to-service JWT issued with role `service`.
- order-service returns the full order object for valid requests.
- order-service returns `404 Not Found` if the order does not exist.
- The response schema matches the order entity definition in Section 3.2.

**SLA:**
- order-service must respond within 100ms at the 99th percentile.

### 7.3 Contract: notification-service calls auth-service for user contact details

**Consumer:** notification-service
**Provider:** auth-service
**Endpoint:** `GET http://auth-service:3001/auth/users/:id`

**Contract:**
- notification-service authenticates using a service-to-service JWT issued with role `service`.
- auth-service returns user profile data including `email` and `phone` fields.
- auth-service returns `404 Not Found` if the user does not exist.

**SLA:**
- auth-service must respond within 50ms at the 99th percentile.

---

## 8. Authentication Flow

### 8.1 User Authentication (External Requests)

```
Client                    order-service              auth-service
  |                            |                          |
  |  POST /orders              |                          |
  |  Authorization: Bearer ... |                          |
  |--------------------------->|                          |
  |                            |  POST /auth/validate     |
  |                            |  Authorization: Bearer...|
  |                            |------------------------->|
  |                            |                          |
  |                            |  200 OK { valid, user }  |
  |                            |<-------------------------|
  |                            |                          |
  |  201 Created { order }     |                          |
  |<---------------------------|                          |
```

### 8.2 Service-to-Service Authentication

Services authenticate with each other using dedicated service account JWTs. These tokens are long-lived (24h TTL) and carry the `service` role, which bypasses per-user ownership checks.

**Service Token Payload:**
```json
{
  "sub": "notification-service",
  "role": "service",
  "iat": 1739789400,
  "exp": 1739875800
}
```

Service tokens are provisioned via environment variables:
- `AUTH_SERVICE_TOKEN` -- Token for calling auth-service
- `ORDER_SERVICE_TOKEN` -- Token for calling order-service

---

## 9. Database Schemas

### 9.1 auth-service Database (PostgreSQL)

```sql
CREATE TABLE users (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email         VARCHAR(255) NOT NULL UNIQUE,
    password_hash VARCHAR(255) NOT NULL,
    first_name    VARCHAR(100) NOT NULL,
    last_name     VARCHAR(100) NOT NULL,
    phone         VARCHAR(20),
    role          VARCHAR(20) NOT NULL DEFAULT 'customer'
                    CHECK (role IN ('customer', 'admin')),
    is_active     BOOLEAN NOT NULL DEFAULT true,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_users_email ON users (email);
CREATE INDEX idx_users_created_at ON users (created_at);
```

### 9.2 order-service Database (PostgreSQL)

```sql
CREATE TABLE orders (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id          UUID NOT NULL,
    status           VARCHAR(20) NOT NULL DEFAULT 'pending'
                       CHECK (status IN ('pending', 'confirmed', 'shipped', 'delivered')),
    items            JSONB NOT NULL,
    shipping_address JSONB NOT NULL,
    total_amount     DECIMAL(10, 2) NOT NULL,
    currency         VARCHAR(3) NOT NULL DEFAULT 'USD',
    notes            VARCHAR(500),
    confirmed_at     TIMESTAMPTZ,
    shipped_at       TIMESTAMPTZ,
    delivered_at     TIMESTAMPTZ,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_orders_user_id ON orders (user_id);
CREATE INDEX idx_orders_status ON orders (status);
CREATE INDEX idx_orders_created_at ON orders (created_at);
CREATE INDEX idx_orders_user_status ON orders (user_id, status);
```

### 9.3 notification-service Database (PostgreSQL)

```sql
CREATE TABLE notifications (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id       UUID NOT NULL,
    order_id      UUID,
    channel       VARCHAR(10) NOT NULL CHECK (channel IN ('email', 'sms')),
    type          VARCHAR(100) NOT NULL,
    recipient     VARCHAR(255) NOT NULL,
    subject       VARCHAR(255),
    body          TEXT NOT NULL,
    status        VARCHAR(10) NOT NULL DEFAULT 'queued'
                    CHECK (status IN ('queued', 'sent', 'failed')),
    provider_ref  VARCHAR(255),
    error_message VARCHAR(1000),
    sent_at       TIMESTAMPTZ,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_notifications_user_id ON notifications (user_id);
CREATE INDEX idx_notifications_order_id ON notifications (order_id);
CREATE INDEX idx_notifications_status ON notifications (status);
CREATE INDEX idx_notifications_created_at ON notifications (created_at);
```

---

## 10. Non-Functional Requirements

### 10.1 Performance

| Metric                              | Target           |
|-------------------------------------|------------------|
| auth-service /auth/validate p99     | < 50ms           |
| auth-service /auth/login p99        | < 200ms          |
| order-service POST /orders p99      | < 300ms          |
| order-service GET /orders p99       | < 100ms          |
| Event publish latency (to broker)   | < 20ms           |
| Notification delivery (email)       | < 30 seconds     |
| Notification delivery (SMS)         | < 10 seconds     |

### 10.2 Availability

| Service              | Target SLA  |
|----------------------|-------------|
| auth-service         | 99.99%      |
| order-service        | 99.95%      |
| notification-service | 99.9%       |

### 10.3 Scalability

- Each service is stateless and horizontally scalable behind a load balancer.
- Database connections are pooled (max 20 connections per service instance).
- RabbitMQ consumers use prefetch count of 10 for controlled concurrency.
- Target throughput: 500 orders per minute at peak load.

### 10.4 Observability

- All services emit structured JSON logs to stdout.
- Distributed tracing via OpenTelemetry with W3C Trace Context propagation.
- Metrics exported in Prometheus format on `/metrics` endpoint per service.
- Health check endpoints at `GET /health` returning `{ "status": "ok" }` with a 200 status code.

### 10.5 Security

- All inter-service communication occurs over the internal network; no public exposure.
- Passwords are hashed using bcrypt with a cost factor of 12.
- JWT secrets are stored in environment variables, rotated quarterly.
- Input validation on all endpoints using Zod schemas.
- Rate limiting: 100 requests per minute per IP on auth endpoints; 1000 requests per minute per user on order endpoints.
- CORS is disabled on service-to-service endpoints and configured per-domain on public endpoints.

### 10.6 Data Retention

- User records are soft-deleted (is_active = false) and permanently purged after 90 days.
- Order records are retained for 7 years for compliance.
- Notification records are retained for 1 year, then archived to cold storage.

---

## Appendix A: Environment Variables

### auth-service
| Variable        | Description                  | Example                |
|-----------------|------------------------------|------------------------|
| DATABASE_URL    | PostgreSQL connection string | postgres://...         |
| JWT_SECRET      | Secret for signing JWTs      | (generated)            |
| PORT            | HTTP listen port             | 3001                   |
| LOG_LEVEL       | Logging verbosity            | info                   |

### order-service
| Variable           | Description                    | Example             |
|--------------------|--------------------------------|----------------------|
| DATABASE_URL       | PostgreSQL connection string   | postgres://...       |
| AUTH_SERVICE_URL   | Base URL of auth-service       | http://auth:3001     |
| AUTH_SERVICE_TOKEN | Service-to-service JWT         | eyJhbGci...          |
| RABBITMQ_URL       | AMQP connection string         | amqp://...           |
| PORT               | HTTP listen port               | 3002                 |
| LOG_LEVEL          | Logging verbosity              | info                 |

### notification-service
| Variable            | Description                    | Example             |
|---------------------|--------------------------------|----------------------|
| DATABASE_URL        | PostgreSQL connection string   | postgres://...       |
| AUTH_SERVICE_URL    | Base URL of auth-service       | http://auth:3001     |
| AUTH_SERVICE_TOKEN  | Service-to-service JWT         | eyJhbGci...          |
| ORDER_SERVICE_URL   | Base URL of order-service      | http://order:3002    |
| ORDER_SERVICE_TOKEN | Service-to-service JWT         | eyJhbGci...          |
| RABBITMQ_URL        | AMQP connection string         | amqp://...           |
| AWS_SES_REGION      | AWS region for SES             | us-east-1            |
| AWS_SES_FROM_EMAIL  | Sender email address           | noreply@shopflow.com |
| TWILIO_ACCOUNT_SID  | Twilio account SID             | AC...                |
| TWILIO_AUTH_TOKEN   | Twilio auth token              | (secret)             |
| TWILIO_FROM_NUMBER  | Twilio sender phone number     | +15550001234         |
| PORT                | HTTP listen port               | 3003                 |
| LOG_LEVEL           | Logging verbosity              | info                 |

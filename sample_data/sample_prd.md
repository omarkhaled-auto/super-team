# E-Commerce Platform - Product Requirements Document

## 1. Project Overview

**Project Name:** E-Commerce Platform
**Version:** 2.0
**Last Updated:** 2026-02-16

The E-Commerce Platform is a distributed, microservices-based online marketplace that enables customers to browse products, place orders, and manage their accounts. The system must support high availability, horizontal scaling, and eventual consistency across service boundaries.

### Technology Stack

- **Language:** Python 3.12+
- **Framework:** FastAPI
- **Primary Database:** PostgreSQL 16
- **Cache Layer:** Redis 7
- **Message Broker:** RabbitMQ 3.13
- **Containerization:** Docker + Kubernetes
- **API Gateway:** Kong

---

## 2. Service Boundaries

The platform is decomposed into five bounded contexts, each owning its data and exposing well-defined contracts.

### 2.1 User Service

The User Service is the identity and access management hub. It owns all user-related data including profiles, credentials, addresses, and authentication tokens. It exposes a REST API for registration, login, profile management, and address CRUD. Internally it manages password hashing with bcrypt, JWT token issuance and validation, and refresh token rotation. It publishes `user.registered`, `user.updated`, and `user.deactivated` domain events to RabbitMQ for downstream consumers.

Authentication is handled via OAuth2 with JWT bearer tokens. The User Service acts as the authorization server, issuing access tokens (15-minute expiry) and refresh tokens (7-day expiry). All other services validate tokens by calling the User Service's `/auth/verify` endpoint or by verifying the JWT signature locally using a shared public key.

Role-based access control (RBAC) is enforced: customers can only access their own resources, while admin users have elevated privileges for inventory and order management.

#### User Entity

- **id** (UUID, primary key)
- **email** (string, unique, indexed, max 255 chars)
- **password_hash** (string, bcrypt, never exposed via API)
- **first_name** (string, max 100 chars)
- **last_name** (string, max 100 chars)
- **phone** (string, optional, E.164 format)
- **role** (enum: customer, admin, support)
- **account_status** (enum: active, suspended, deactivated)
- **email_verified** (boolean, default false)
- **created_at** (datetime, UTC)
- **updated_at** (datetime, UTC)

#### Address Entity

- **id** (UUID, primary key)
- **user_id** (UUID, foreign key to User)
- **label** (string: "home", "work", "other")
- **street_line_1** (string, max 200 chars)
- **street_line_2** (string, optional, max 200 chars)
- **city** (string, max 100 chars)
- **state** (string, max 100 chars)
- **postal_code** (string, max 20 chars)
- **country_code** (string, ISO 3166-1 alpha-2)
- **is_default** (boolean, default false)

### 2.2 Product Service

The Product Service manages the entire product catalog including categories, product listings, inventory counts, and pricing. It provides full-text search via PostgreSQL tsvector and caches hot product data in Redis with a 5-minute TTL.

| Field | Type | Constraints | Description |
|-------|------|-------------|-------------|
| id | UUID | primary key | Unique product identifier |
| sku | string | unique, indexed, max 50 | Stock keeping unit |
| name | string | max 255, not null | Product display name |
| slug | string | unique, indexed, max 255 | URL-friendly name |
| description | text | nullable | Full product description |
| price_cents | integer | not null, >= 0 | Price in cents (USD) |
| compare_at_price_cents | integer | nullable, >= 0 | Original price for sale display |
| currency | string | default "USD", ISO 4217 | Currency code |
| category_id | UUID | foreign key to Category | Parent category |
| brand | string | max 100, nullable | Brand name |
| weight_grams | integer | nullable, >= 0 | Product weight for shipping |
| is_active | boolean | default true | Whether product is listed |
| created_at | datetime | UTC, auto | Creation timestamp |
| updated_at | datetime | UTC, auto | Last update timestamp |

| Field | Type | Constraints | Description |
|-------|------|-------------|-------------|
| id | UUID | primary key | Unique category identifier |
| name | string | max 100, not null | Category display name |
| slug | string | unique, indexed | URL-friendly category name |
| parent_id | UUID | nullable, self-referential FK | Parent category for nesting |
| description | text | nullable | Category description |
| sort_order | integer | default 0 | Display ordering |

#### Inventory Entity

| Field | Type | Constraints | Description |
|-------|------|-------------|-------------|
| id | UUID | primary key | Unique inventory record |
| product_id | UUID | foreign key to Product, unique | Associated product |
| quantity_on_hand | integer | not null, >= 0 | Current stock count |
| quantity_reserved | integer | not null, default 0, >= 0 | Reserved by pending orders |
| reorder_threshold | integer | default 10 | Low-stock alert threshold |
| warehouse_location | string | max 50, nullable | Physical warehouse code |
| last_restocked_at | datetime | nullable | Last restock timestamp |

The Product Service publishes `product.created`, `product.updated`, `product.out_of_stock`, and `inventory.low_stock` events. It consumes `order.confirmed` events to decrement inventory and `order.cancelled` events to release reserved stock.

### 2.3 Order Service

The Order Service orchestrates the entire purchase lifecycle. When a customer places an order, the service validates the cart, reserves inventory (by calling the Product Service), calculates totals, and initiates payment (by calling the Payment Service). It owns the Order and OrderItem entities and maintains a strict state machine for order progression.

#### Order Entity

| Field | Type | Constraints | Description |
|-------|------|-------------|-------------|
| id | UUID | primary key | Unique order identifier |
| order_number | string | unique, indexed, auto-generated | Human-readable order number (e.g., ORD-20260216-XXXX) |
| user_id | UUID | not null, indexed | Reference to the ordering user (from User Service) |
| status | enum | not null, default "pending" | Current order state |
| subtotal_cents | integer | not null, >= 0 | Sum of line items before tax |
| tax_cents | integer | not null, default 0, >= 0 | Calculated tax amount |
| shipping_cents | integer | not null, default 0, >= 0 | Shipping cost |
| total_cents | integer | not null, >= 0 | Grand total |
| shipping_address_snapshot | JSONB | not null | Denormalized copy of address at time of order |
| notes | text | nullable | Customer notes for the order |
| created_at | datetime | UTC, auto | Order placement time |
| updated_at | datetime | UTC, auto | Last status change |

#### OrderItem Entity

Each order contains one or more order items. An OrderItem captures the product snapshot at purchase time so historical orders remain accurate even if product details change.

- **id** (UUID, primary key)
- **order_id** (UUID, foreign key to Order, indexed)
- **product_id** (UUID, references Product Service's product, indexed)
- **product_name_snapshot** (string, max 255 -- captured at order time)
- **sku_snapshot** (string, max 50 -- captured at order time)
- **unit_price_cents** (integer, not null, >= 0 -- price at purchase time)
- **quantity** (integer, not null, >= 1)
- **line_total_cents** (integer, not null, computed: unit_price_cents * quantity)

#### Order State Machine

The Order entity follows a strict state machine with the following transitions:

```
pending --> confirmed    (payment successfully captured)
pending --> cancelled    (customer cancels before payment, or payment fails)
confirmed --> shipped    (warehouse marks as shipped, tracking number assigned)
confirmed --> cancelled  (admin cancels, triggers refund via Payment Service)
shipped --> delivered    (carrier confirms delivery)
shipped --> cancelled    (return initiated before delivery, triggers refund)
```

Valid states: `pending`, `confirmed`, `shipped`, `delivered`, `cancelled`

The `cancelled` and `delivered` states are terminal -- no further transitions are allowed. Every state transition emits a domain event: `order.confirmed`, `order.shipped`, `order.delivered`, `order.cancelled`.

### 2.4 Payment Service

The Payment Service handles all monetary transactions. It integrates with Stripe as the primary payment gateway and provides an internal abstraction layer so additional gateways (PayPal, etc.) can be added. It owns Payment and Refund entities.

#### Payment Entity

| Field | Type | Constraints | Description |
|-------|------|-------------|-------------|
| id | UUID | primary key | Unique payment identifier |
| order_id | UUID | not null, indexed | Associated order |
| user_id | UUID | not null, indexed | Payer reference |
| amount_cents | integer | not null, > 0 | Payment amount |
| currency | string | default "USD" | ISO 4217 currency |
| method | enum | not null | Payment method: credit_card, debit_card, wallet |
| status | enum | not null, default "pending" | Payment status: pending, captured, failed, refunded |
| gateway_transaction_id | string | nullable, indexed | External gateway reference |
| gateway_response | JSONB | nullable | Raw gateway response for debugging |
| created_at | datetime | UTC, auto | Payment initiation time |
| captured_at | datetime | nullable | Successful capture time |

#### Refund Entity

A Refund is always associated with a Payment. The Payment Service processes refunds when an order is cancelled after payment has been captured.

- **id** (UUID, primary key)
- **payment_id** (UUID, foreign key to Payment)
- **amount_cents** (integer, not null, > 0 -- may be partial refund)
- **reason** (string, max 500)
- **status** (enum: pending, processed, failed)
- **gateway_refund_id** (string, nullable)
- **created_at** (datetime, UTC)
- **processed_at** (datetime, nullable)

The Payment Service publishes `payment.captured`, `payment.failed`, and `refund.processed` events. It consumes `order.confirmed` to initiate payment capture and `order.cancelled` to initiate refunds.

### 2.5 Notification Service

The Notification Service is a downstream consumer responsible for sending transactional emails, SMS messages, and push notifications. It does not own any domain entities in the traditional sense but maintains a log of all notifications sent for audit and retry purposes.

#### NotificationLog Entity

- **id** (UUID, primary key)
- **user_id** (UUID, not null, indexed)
- **channel** (enum: email, sms, push)
- **template_name** (string, max 100 -- e.g., "order_confirmation", "password_reset")
- **recipient** (string, max 255 -- email address or phone number)
- **subject** (string, max 255, nullable -- for emails)
- **payload** (JSONB -- template variables)
- **status** (enum: queued, sent, failed, bounced)
- **sent_at** (datetime, nullable)
- **failure_reason** (text, nullable)
- **retry_count** (integer, default 0)
- **created_at** (datetime, UTC)

The Notification Service consumes events from all other services: `user.registered` triggers a welcome email, `order.confirmed` triggers an order confirmation email, `order.shipped` triggers a shipping notification with tracking link, and `payment.failed` triggers a payment failure alert.

---

## 3. Cross-Service Relationships

The Order Service references users by storing a `user_id` that corresponds to the User Service's User entity; however, it does not directly query the User Service database. Instead, it calls the User Service API to validate the user exists and to fetch the shipping address at order creation time, then snapshots the address into the order record.

Each OrderItem references a `product_id` from the Product Service. At order creation, the Order Service calls the Product Service to verify product availability and current pricing, then snapshots the product name, SKU, and price into the OrderItem to preserve historical accuracy.

The Payment Service is invoked by the Order Service during the order confirmation flow. The Order Service sends a payment request containing the `order_id`, `user_id`, and `amount_cents`. The Payment Service processes the charge and publishes the result as a domain event, which the Order Service consumes to transition the order from `pending` to `confirmed` (on success) or `cancelled` (on failure).

The Notification Service has no synchronous API dependencies on other services. It operates entirely through event consumption from RabbitMQ, making it fully decoupled and independently deployable.

---

## 4. User Account State Machine

User accounts follow a lifecycle state machine:

```
active --> suspended     (admin action or policy violation detected)
active --> deactivated   (user requests account deletion)
suspended --> active     (admin reinstates the account after review)
suspended --> deactivated (admin permanently deactivates after review)
```

Valid states: `active`, `suspended`, `deactivated`

The `deactivated` state is terminal. When a user is deactivated, the User Service publishes a `user.deactivated` event. The Notification Service sends a farewell email, and the Order Service cancels any pending orders for that user.

---

## 5. API Contracts Summary

### User Service Endpoints
- `POST /api/v1/auth/register` -- Register a new user
- `POST /api/v1/auth/login` -- Authenticate and receive tokens
- `POST /api/v1/auth/refresh` -- Refresh access token
- `GET /api/v1/auth/verify` -- Verify a JWT token
- `GET /api/v1/users/{user_id}` -- Get user profile
- `PUT /api/v1/users/{user_id}` -- Update user profile
- `GET /api/v1/users/{user_id}/addresses` -- List user addresses
- `POST /api/v1/users/{user_id}/addresses` -- Add an address

### Product Service Endpoints
- `GET /api/v1/products` -- List/search products (paginated, filterable)
- `GET /api/v1/products/{product_id}` -- Get product details
- `POST /api/v1/products` -- Create product (admin only)
- `PUT /api/v1/products/{product_id}` -- Update product (admin only)
- `GET /api/v1/categories` -- List categories (tree structure)
- `GET /api/v1/products/{product_id}/inventory` -- Check stock level

### Order Service Endpoints
- `POST /api/v1/orders` -- Place a new order
- `GET /api/v1/orders/{order_id}` -- Get order details
- `GET /api/v1/users/{user_id}/orders` -- List orders for a user
- `PUT /api/v1/orders/{order_id}/status` -- Update order status (admin/system)
- `POST /api/v1/orders/{order_id}/cancel` -- Cancel an order

### Payment Service Endpoints
- `POST /api/v1/payments` -- Initiate a payment
- `GET /api/v1/payments/{payment_id}` -- Get payment status
- `POST /api/v1/payments/{payment_id}/refund` -- Initiate a refund

### Notification Service Endpoints
- `GET /api/v1/notifications/{user_id}` -- List notification history
- `POST /api/v1/notifications/send` -- Manually trigger a notification (admin only)

---

## 6. Non-Functional Requirements

- **Latency:** P99 API response time under 200ms for read endpoints, under 500ms for writes.
- **Throughput:** Support 1,000 concurrent users and 100 orders per minute at launch.
- **Availability:** 99.9% uptime SLA for User, Product, and Order services.
- **Data Retention:** Order and payment records retained for 7 years for compliance.
- **Security:** All inter-service communication over mTLS. PII encrypted at rest. OWASP Top 10 mitigations required.

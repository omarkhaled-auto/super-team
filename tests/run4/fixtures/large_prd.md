# MegaCommerce PRD -- Large-Scale Microservices E-Commerce Platform

## Overview

MegaCommerce is a comprehensive, enterprise-grade e-commerce platform consisting of 14
microservices. Each service is implemented in Python using FastAPI with PostgreSQL as the
primary database, Redis for caching and Pub/Sub, and Elasticsearch for search capabilities.
Services communicate via REST APIs, asynchronous events published through Redis Pub/Sub,
and gRPC for low-latency internal calls.

This platform supports multi-tenant operations, real-time inventory tracking, AI-powered
recommendations, payment processing, logistics coordination, and comprehensive analytics.

---

## Technology Stack

| Layer              | Technology           | Version    |
|--------------------|----------------------|------------|
| Language           | Python               | 3.12       |
| Framework          | FastAPI              | 0.129.0    |
| Database           | PostgreSQL           | 16         |
| Cache/Pubsub       | Redis                | 7.2        |
| Search             | Elasticsearch        | 8.12       |
| ORM                | SQLAlchemy           | 2.0        |
| Auth               | JWT (python-jose)    | latest     |
| Message Queue      | RabbitMQ             | 3.13       |
| Containerisation   | Docker Compose       | 3.8        |
| API Gateway        | Traefik              | v3.6       |
| Monitoring         | Prometheus + Grafana | latest     |
| Tracing            | OpenTelemetry        | 1.24       |

---

## Service 1: auth-service

### Description

The auth-service is the central identity provider for the entire MegaCommerce platform.
It manages user registration, authentication, JWT token issuance, role-based access
control (RBAC), multi-factor authentication (MFA), OAuth2 social login, and session
management. All other services depend on auth-service for identity verification.

The service implements a layered security architecture with rate limiting, account lockout
policies, password strength enforcement, and audit logging of all authentication events.
It supports both access tokens (short-lived, 15 minutes) and refresh tokens (long-lived,
7 days) with token rotation on each refresh.

### Data Model

#### User

| Field              | Type       | Constraints                          |
|--------------------|------------|--------------------------------------|
| id                 | UUID       | Primary key, auto-generated          |
| email              | string     | Unique, not null, max 255 chars      |
| password_hash      | string     | Not null (bcrypt, cost factor 12)    |
| name               | string     | Not null, max 100 chars              |
| phone              | string     | Optional, E.164 format               |
| avatar_url         | string     | Optional, max 512 chars              |
| role               | string     | Enum: customer, merchant, admin      |
| status             | string     | Enum: active, suspended, deleted     |
| email_verified     | boolean    | Default false                        |
| mfa_enabled        | boolean    | Default false                        |
| mfa_secret         | string     | Encrypted TOTP secret                |
| failed_login_count | integer    | Default 0, reset on success          |
| locked_until       | datetime   | Null if not locked                   |
| last_login_at      | datetime   | Nullable                             |
| last_login_ip      | string     | Nullable, IPv4 or IPv6               |
| created_at         | datetime   | Auto-generated (UTC)                 |
| updated_at         | datetime   | Auto-updated (UTC)                   |
| deleted_at         | datetime   | Nullable, soft delete                |

#### RefreshToken

| Field              | Type       | Constraints                          |
|--------------------|------------|--------------------------------------|
| id                 | UUID       | Primary key                          |
| user_id            | UUID       | Foreign key (User), indexed          |
| token_hash         | string     | Unique, SHA-256 hash of token        |
| device_info        | JSON       | Browser/device metadata              |
| ip_address         | string     | Client IP at issuance                |
| expires_at         | datetime   | Token expiry                         |
| revoked            | boolean    | Default false                        |
| created_at         | datetime   | Auto-generated (UTC)                 |

#### AuditLog

| Field              | Type       | Constraints                          |
|--------------------|------------|--------------------------------------|
| id                 | UUID       | Primary key                          |
| user_id            | UUID       | Foreign key (User), nullable         |
| action             | string     | Enum: login, logout, register, etc.  |
| ip_address         | string     | Client IP                            |
| user_agent         | string     | Browser user agent                   |
| success            | boolean    | Whether action succeeded             |
| failure_reason     | string     | Nullable                             |
| metadata           | JSON       | Additional context                   |
| created_at         | datetime   | Auto-generated (UTC)                 |

#### OAuthConnection

| Field              | Type       | Constraints                          |
|--------------------|------------|--------------------------------------|
| id                 | UUID       | Primary key                          |
| user_id            | UUID       | Foreign key (User)                   |
| provider           | string     | Enum: google, github, facebook       |
| provider_user_id   | string     | Provider's user ID                   |
| access_token       | string     | Encrypted OAuth access token         |
| refresh_token      | string     | Encrypted OAuth refresh token        |
| token_expires_at   | datetime   | OAuth token expiry                   |
| profile_data       | JSON       | Raw profile from provider            |
| created_at         | datetime   | Auto-generated (UTC)                 |
| updated_at         | datetime   | Auto-updated (UTC)                   |

### Endpoints

#### POST /auth/register

Register a new user account with email verification.

- **Request Body**:
  ```json
  {
    "email": "string (required, valid email)",
    "password": "string (required, min 8 chars, must contain uppercase, lowercase, digit, special)",
    "name": "string (required, 1-100 chars)",
    "phone": "string (optional, E.164 format)",
    "role": "string (optional, default: customer)"
  }
  ```
- **Response 201**:
  ```json
  {
    "id": "UUID",
    "email": "string",
    "name": "string",
    "role": "customer",
    "email_verified": false,
    "created_at": "ISO8601"
  }
  ```
- **Response 409**: `{ "detail": "Email already registered" }`
- **Response 422**: `{ "detail": "Password does not meet complexity requirements" }`
- **Side Effects**: Sends email verification link, publishes `user.registered` event

#### POST /auth/login

Authenticate a user and issue JWT token pair.

- **Request Body**:
  ```json
  {
    "email": "string (required)",
    "password": "string (required)",
    "device_info": {
      "browser": "string",
      "os": "string",
      "device_type": "string"
    }
  }
  ```
- **Response 200**:
  ```json
  {
    "access_token": "string (JWT, 15min expiry)",
    "refresh_token": "string (opaque, 7day expiry)",
    "token_type": "bearer",
    "expires_in": 900,
    "user": {
      "id": "UUID",
      "email": "string",
      "name": "string",
      "role": "string",
      "mfa_enabled": false
    }
  }
  ```
- **Response 401**: `{ "detail": "Invalid credentials" }`
- **Response 423**: `{ "detail": "Account locked until <datetime>", "locked_until": "ISO8601" }`
- **Rate Limit**: 5 attempts per 15 minutes per email

#### POST /auth/login/mfa

Complete MFA verification after initial login.

- **Request Body**:
  ```json
  {
    "mfa_token": "string (6-digit TOTP code)",
    "session_token": "string (from initial login response)"
  }
  ```
- **Response 200**: Same as `/auth/login` success response
- **Response 401**: `{ "detail": "Invalid MFA code" }`

#### POST /auth/refresh

Refresh an expired access token using a refresh token.

- **Request Body**:
  ```json
  {
    "refresh_token": "string (required)"
  }
  ```
- **Response 200**:
  ```json
  {
    "access_token": "string (new JWT)",
    "refresh_token": "string (rotated refresh token)",
    "token_type": "bearer",
    "expires_in": 900
  }
  ```
- **Response 401**: `{ "detail": "Invalid or expired refresh token" }`

#### POST /auth/logout

Revoke the current refresh token and invalidate the session.

- **Headers**: `Authorization: Bearer <access_token>`
- **Request Body**:
  ```json
  {
    "refresh_token": "string (required)"
  }
  ```
- **Response 204**: No content
- **Response 401**: `{ "detail": "Not authenticated" }`

#### GET /auth/me

Retrieve the authenticated user's profile.

- **Headers**: `Authorization: Bearer <access_token>`
- **Response 200**:
  ```json
  {
    "id": "UUID",
    "email": "string",
    "name": "string",
    "phone": "string|null",
    "avatar_url": "string|null",
    "role": "string",
    "email_verified": true,
    "mfa_enabled": false,
    "last_login_at": "ISO8601|null",
    "created_at": "ISO8601"
  }
  ```
- **Response 401**: `{ "detail": "Not authenticated" }`

#### PUT /auth/me

Update the authenticated user's profile.

- **Headers**: `Authorization: Bearer <access_token>`
- **Request Body**:
  ```json
  {
    "name": "string (optional)",
    "phone": "string (optional)",
    "avatar_url": "string (optional)"
  }
  ```
- **Response 200**: Updated user profile (same as GET /auth/me)
- **Response 401**: `{ "detail": "Not authenticated" }`
- **Response 422**: `{ "detail": "Validation error" }`

#### PUT /auth/me/password

Change the authenticated user's password.

- **Headers**: `Authorization: Bearer <access_token>`
- **Request Body**:
  ```json
  {
    "current_password": "string (required)",
    "new_password": "string (required, meets complexity)"
  }
  ```
- **Response 204**: No content
- **Response 400**: `{ "detail": "Current password is incorrect" }`
- **Response 422**: `{ "detail": "New password does not meet complexity requirements" }`
- **Side Effects**: Revokes all refresh tokens, publishes `user.password_changed` event

#### POST /auth/mfa/enable

Enable MFA for the authenticated user.

- **Headers**: `Authorization: Bearer <access_token>`
- **Response 200**:
  ```json
  {
    "secret": "string (base32 TOTP secret)",
    "qr_code_url": "string (otpauth:// URI)",
    "backup_codes": ["string (10 backup codes)"]
  }
  ```

#### POST /auth/mfa/verify

Verify MFA setup with a TOTP code.

- **Headers**: `Authorization: Bearer <access_token>`
- **Request Body**: `{ "code": "string (6-digit TOTP)" }`
- **Response 200**: `{ "mfa_enabled": true }`
- **Response 400**: `{ "detail": "Invalid verification code" }`

#### POST /auth/password/reset

Request a password reset email.

- **Request Body**: `{ "email": "string (required)" }`
- **Response 200**: `{ "message": "If an account exists, a reset email has been sent" }`
- **Side Effects**: Sends password reset email with time-limited token

#### POST /auth/password/reset/confirm

Confirm password reset with the token from email.

- **Request Body**:
  ```json
  {
    "token": "string (from email)",
    "new_password": "string (meets complexity)"
  }
  ```
- **Response 200**: `{ "message": "Password has been reset successfully" }`
- **Response 400**: `{ "detail": "Invalid or expired reset token" }`

#### POST /auth/email/verify

Verify email address with the token from registration email.

- **Request Body**: `{ "token": "string (from email)" }`
- **Response 200**: `{ "email_verified": true }`
- **Response 400**: `{ "detail": "Invalid or expired verification token" }`

#### POST /auth/oauth/{provider}/callback

Handle OAuth2 callback from social login providers.

- **Path Parameter**: `provider` - one of: google, github, facebook
- **Request Body**:
  ```json
  {
    "code": "string (authorization code)",
    "state": "string (CSRF state token)",
    "redirect_uri": "string (callback URL)"
  }
  ```
- **Response 200**: Same as `/auth/login` success response
- **Response 400**: `{ "detail": "Invalid OAuth callback" }`

#### GET /auth/sessions

List active sessions for the authenticated user.

- **Headers**: `Authorization: Bearer <access_token>`
- **Response 200**:
  ```json
  [
    {
      "id": "UUID",
      "device_info": { "browser": "string", "os": "string" },
      "ip_address": "string",
      "created_at": "ISO8601",
      "last_used_at": "ISO8601",
      "is_current": true
    }
  ]
  ```

#### DELETE /auth/sessions/{session_id}

Revoke a specific session.

- **Headers**: `Authorization: Bearer <access_token>`
- **Response 204**: No content
- **Response 404**: `{ "detail": "Session not found" }`

#### GET /auth/admin/users

Admin endpoint to list all users with pagination and filtering.

- **Headers**: `Authorization: Bearer <access_token>` (admin role required)
- **Query Parameters**: `page`, `per_page`, `role`, `status`, `search`
- **Response 200**:
  ```json
  {
    "items": [{ "id": "UUID", "email": "string", "name": "string", "role": "string", "status": "string" }],
    "total": 150,
    "page": 1,
    "per_page": 20
  }
  ```
- **Response 403**: `{ "detail": "Insufficient permissions" }`

#### PUT /auth/admin/users/{user_id}/status

Admin endpoint to change a user's status (suspend, activate, etc.).

- **Headers**: `Authorization: Bearer <access_token>` (admin role required)
- **Request Body**: `{ "status": "string (active|suspended|deleted)" }`
- **Response 200**: Updated user object
- **Response 403**: `{ "detail": "Insufficient permissions" }`
- **Response 404**: `{ "detail": "User not found" }`

#### GET /health

Service health check endpoint.

- **Response 200**: `{ "status": "healthy", "version": "1.0.0", "uptime_seconds": 3600 }`

### Inter-Service Contract

- Issues JWT tokens with `sub` = user UUID, `role` = user role, `exp` = 15 minutes
- Access tokens are signed with RS256 using a private key
- Other services validate JWTs using the corresponding public key
- Token payload: `{ "sub": UUID, "email": string, "role": string, "exp": int, "iat": int, "jti": UUID }`
- Refresh tokens are opaque and stored hashed in the database
- Account lockout after 5 failed attempts for 30 minutes

### Events Published

| Event                   | Channel                | Payload                                                    |
|-------------------------|------------------------|------------------------------------------------------------|
| user.registered         | auth/user.registered   | `{ user_id, email, name, role, created_at }`              |
| user.logged_in          | auth/user.logged_in    | `{ user_id, ip_address, device_info, timestamp }`         |
| user.password_changed   | auth/user.password_changed | `{ user_id, timestamp }`                              |
| user.mfa_enabled        | auth/user.mfa_enabled  | `{ user_id, timestamp }`                                  |
| user.status_changed     | auth/user.status_changed | `{ user_id, old_status, new_status, admin_id }`         |
| user.email_verified     | auth/user.email_verified | `{ user_id, email, timestamp }`                         |

---

## Service 2: catalog-service

### Description

The catalog-service manages the product catalog, categories, brands, and product variants.
It supports full-text search via Elasticsearch, faceted filtering, product relationships
(cross-sells, up-sells), and dynamic pricing rules. The service maintains a denormalized
search index that is kept in sync with the authoritative PostgreSQL data store through
change data capture (CDC) events.

Products support multiple variants (e.g., size, color) with independent pricing and
inventory tracking. Categories form a hierarchical tree structure with path materialization
for efficient querying.

### Data Model

#### Product

| Field              | Type       | Constraints                          |
|--------------------|------------|--------------------------------------|
| id                 | UUID       | Primary key                          |
| sku                | string     | Unique, not null, max 50 chars       |
| name               | string     | Not null, max 255 chars              |
| slug               | string     | Unique, URL-safe                     |
| description        | text       | Nullable                             |
| short_description  | string     | Max 500 chars                        |
| brand_id           | UUID       | Foreign key (Brand), nullable        |
| category_id        | UUID       | Foreign key (Category)               |
| base_price         | decimal    | Not null, >= 0, precision 10,2       |
| sale_price         | decimal    | Nullable, >= 0                       |
| cost_price         | decimal    | Not null, >= 0 (merchant only)       |
| currency           | string     | ISO 4217 code, default USD           |
| weight             | decimal    | Grams, nullable                      |
| dimensions         | JSON       | `{ length, width, height }` in cm    |
| images             | JSON       | Array of image URLs with alt text    |
| tags               | string[]   | Array of searchable tags             |
| status             | string     | Enum: draft, active, archived        |
| is_featured        | boolean    | Default false                        |
| meta_title         | string     | SEO title, max 70 chars              |
| meta_description   | string     | SEO description, max 160 chars       |
| average_rating     | decimal    | Computed, 0-5 scale                  |
| review_count       | integer    | Computed                             |
| created_at         | datetime   | Auto-generated (UTC)                 |
| updated_at         | datetime   | Auto-updated (UTC)                   |

#### ProductVariant

| Field              | Type       | Constraints                          |
|--------------------|------------|--------------------------------------|
| id                 | UUID       | Primary key                          |
| product_id         | UUID       | Foreign key (Product)                |
| sku                | string     | Unique, not null                     |
| name               | string     | E.g., "Large / Blue"                |
| price_modifier     | decimal    | Added to base_price                  |
| weight_modifier    | decimal    | Added to product weight              |
| attributes         | JSON       | `{ "size": "L", "color": "blue" }`  |
| image_url          | string     | Variant-specific image               |
| is_active          | boolean    | Default true                         |
| created_at         | datetime   | Auto-generated (UTC)                 |

#### Category

| Field              | Type       | Constraints                          |
|--------------------|------------|--------------------------------------|
| id                 | UUID       | Primary key                          |
| name               | string     | Not null, max 100 chars              |
| slug               | string     | Unique within parent                 |
| parent_id          | UUID       | Nullable, self-referencing FK        |
| path               | string     | Materialized path (e.g., /electronics/phones) |
| depth              | integer    | Tree depth level                     |
| sort_order         | integer    | Display ordering                     |
| image_url          | string     | Nullable                             |
| description        | text       | Nullable                             |
| is_active          | boolean    | Default true                         |
| product_count      | integer    | Denormalized count                   |
| created_at         | datetime   | Auto-generated (UTC)                 |
| updated_at         | datetime   | Auto-updated (UTC)                   |

#### Brand

| Field              | Type       | Constraints                          |
|--------------------|------------|--------------------------------------|
| id                 | UUID       | Primary key                          |
| name               | string     | Unique, not null                     |
| slug               | string     | Unique                               |
| logo_url           | string     | Nullable                             |
| description        | text       | Nullable                             |
| website_url        | string     | Nullable                             |
| is_active          | boolean    | Default true                         |
| created_at         | datetime   | Auto-generated (UTC)                 |

#### PricingRule

| Field              | Type       | Constraints                          |
|--------------------|------------|--------------------------------------|
| id                 | UUID       | Primary key                          |
| name               | string     | Not null                             |
| rule_type          | string     | Enum: percentage, fixed, buy_x_get_y |
| target_type        | string     | Enum: product, category, brand, all  |
| target_id          | UUID       | Nullable (null = all)                |
| discount_value     | decimal    | Not null                             |
| min_quantity       | integer    | Default 1                            |
| max_uses           | integer    | Nullable                             |
| starts_at          | datetime   | Not null                             |
| ends_at            | datetime   | Not null                             |
| is_active          | boolean    | Default true                         |
| priority           | integer    | Higher = applied first               |
| created_at         | datetime   | Auto-generated (UTC)                 |

### Endpoints

#### GET /catalog/products

List products with filtering, sorting, and pagination.

- **Query Parameters**:
  - `page` (int, default 1)
  - `per_page` (int, default 20, max 100)
  - `category_id` (UUID, optional)
  - `brand_id` (UUID, optional)
  - `min_price` (decimal, optional)
  - `max_price` (decimal, optional)
  - `status` (string, optional)
  - `tags` (comma-separated, optional)
  - `sort_by` (string: price_asc, price_desc, newest, rating, name)
  - `search` (string, full-text search)
- **Response 200**:
  ```json
  {
    "items": [
      {
        "id": "UUID",
        "sku": "string",
        "name": "string",
        "slug": "string",
        "base_price": 29.99,
        "sale_price": null,
        "currency": "USD",
        "images": [{ "url": "string", "alt": "string" }],
        "brand": { "id": "UUID", "name": "string" },
        "category": { "id": "UUID", "name": "string", "path": "string" },
        "average_rating": 4.5,
        "review_count": 42,
        "status": "active",
        "is_featured": false
      }
    ],
    "total": 1500,
    "page": 1,
    "per_page": 20,
    "facets": {
      "categories": [{ "id": "UUID", "name": "string", "count": 45 }],
      "brands": [{ "id": "UUID", "name": "string", "count": 30 }],
      "price_ranges": [{ "min": 0, "max": 50, "count": 200 }],
      "tags": [{ "tag": "string", "count": 15 }]
    }
  }
  ```

#### GET /catalog/products/{product_id}

Get detailed product information including variants and related products.

- **Response 200**:
  ```json
  {
    "id": "UUID",
    "sku": "string",
    "name": "string",
    "slug": "string",
    "description": "string",
    "short_description": "string",
    "base_price": 29.99,
    "sale_price": null,
    "cost_price": 15.00,
    "currency": "USD",
    "weight": 500,
    "dimensions": { "length": 20, "width": 15, "height": 5 },
    "images": [{ "url": "string", "alt": "string", "is_primary": true }],
    "brand": { "id": "UUID", "name": "string", "logo_url": "string" },
    "category": { "id": "UUID", "name": "string", "path": "/electronics/phones" },
    "variants": [
      {
        "id": "UUID",
        "sku": "string",
        "name": "Large / Blue",
        "price_modifier": 5.00,
        "attributes": { "size": "L", "color": "blue" },
        "image_url": "string",
        "is_active": true
      }
    ],
    "tags": ["smartphone", "5g"],
    "average_rating": 4.5,
    "review_count": 42,
    "related_products": [{ "id": "UUID", "name": "string", "base_price": 39.99 }],
    "pricing_rules": [{ "name": "Summer Sale", "discount_value": 10, "rule_type": "percentage" }],
    "meta_title": "string",
    "meta_description": "string",
    "created_at": "ISO8601",
    "updated_at": "ISO8601"
  }
  ```
- **Response 404**: `{ "detail": "Product not found" }`

#### POST /catalog/products

Create a new product (merchant/admin only).

- **Headers**: `Authorization: Bearer <access_token>` (merchant or admin role)
- **Request Body**: Full product object minus computed fields
- **Response 201**: Created product object
- **Response 403**: `{ "detail": "Insufficient permissions" }`
- **Response 422**: `{ "detail": "Validation error" }`

#### PUT /catalog/products/{product_id}

Update a product (merchant/admin only).

- **Headers**: `Authorization: Bearer <access_token>` (merchant or admin role)
- **Request Body**: Partial product object
- **Response 200**: Updated product object
- **Response 403**: `{ "detail": "Insufficient permissions" }`
- **Response 404**: `{ "detail": "Product not found" }`

#### DELETE /catalog/products/{product_id}

Soft-delete a product (admin only).

- **Headers**: `Authorization: Bearer <access_token>` (admin role)
- **Response 204**: No content
- **Response 403**: `{ "detail": "Insufficient permissions" }`
- **Response 404**: `{ "detail": "Product not found" }`

#### POST /catalog/products/{product_id}/variants

Add a variant to a product.

- **Headers**: `Authorization: Bearer <access_token>` (merchant or admin)
- **Request Body**: ProductVariant object
- **Response 201**: Created variant
- **Response 404**: `{ "detail": "Product not found" }`

#### GET /catalog/categories

List all categories as a hierarchical tree.

- **Response 200**: Array of category trees
- **Query Parameters**: `parent_id` (optional, for subtree), `include_products` (boolean)

#### POST /catalog/categories

Create a new category (admin only).

- **Headers**: `Authorization: Bearer <access_token>` (admin role)
- **Request Body**: Category object
- **Response 201**: Created category

#### GET /catalog/brands

List all brands.

- **Query Parameters**: `search`, `page`, `per_page`
- **Response 200**: Paginated brand list

#### POST /catalog/brands

Create a new brand (admin only).

- **Headers**: `Authorization: Bearer <access_token>` (admin role)
- **Request Body**: Brand object
- **Response 201**: Created brand

#### POST /catalog/products/bulk-import

Import products from CSV or JSON file (admin only).

- **Headers**: `Authorization: Bearer <access_token>` (admin role)
- **Request Body**: Multipart form with file upload
- **Response 202**: `{ "job_id": "UUID", "status": "processing" }`

#### GET /catalog/products/bulk-import/{job_id}

Check bulk import job status.

- **Response 200**: `{ "job_id": "UUID", "status": "completed", "imported": 150, "failed": 3, "errors": [...] }`

#### POST /catalog/search/reindex

Trigger Elasticsearch reindex (admin only).

- **Headers**: `Authorization: Bearer <access_token>` (admin role)
- **Response 202**: `{ "job_id": "UUID", "status": "indexing" }`

#### GET /health

Service health check endpoint.

- **Response 200**: `{ "status": "healthy", "version": "1.0.0", "elasticsearch": "connected", "uptime_seconds": 3600 }`

### Events Published

| Event                   | Channel                | Payload                                                    |
|-------------------------|------------------------|------------------------------------------------------------|
| product.created         | catalog/product.created | `{ product_id, sku, name, category_id, base_price }`     |
| product.updated         | catalog/product.updated | `{ product_id, changed_fields, old_values, new_values }` |
| product.deleted         | catalog/product.deleted | `{ product_id, sku, deleted_by }`                        |
| product.price_changed   | catalog/product.price_changed | `{ product_id, old_price, new_price, reason }`    |
| category.created        | catalog/category.created | `{ category_id, name, parent_id }`                      |

### Event Subscriptions

| Event              | Action                                                     |
|--------------------|------------------------------------------------------------|
| review.aggregated  | Update product average_rating and review_count             |
| inventory.low      | Flag product with low stock warning                        |

---

## Service 3: inventory-service

### Description

The inventory-service tracks real-time stock levels for all product variants across
multiple warehouse locations. It supports stock reservations during checkout, automatic
reorder point alerts, warehouse transfers, and stock audit trails. The service ensures
strong consistency for stock operations using database-level row locking and optimistic
concurrency control.

The inventory system supports multiple fulfillment strategies: pick from closest warehouse,
split shipment, and backorder. It integrates with the order service to automatically
decrement stock upon order confirmation and restore stock upon cancellation.

### Data Model

#### WarehouseLocation

| Field              | Type       | Constraints                          |
|--------------------|------------|--------------------------------------|
| id                 | UUID       | Primary key                          |
| code               | string     | Unique, e.g., "WH-NYC-01"          |
| name               | string     | Not null                             |
| address            | JSON       | Full address object                  |
| timezone           | string     | IANA timezone                        |
| is_active          | boolean    | Default true                         |
| capacity           | integer    | Total unit capacity                  |
| current_utilization| integer    | Current units stored                 |
| coordinates        | JSON       | `{ lat, lng }` for distance calc     |
| created_at         | datetime   | Auto-generated (UTC)                 |

#### StockLevel

| Field              | Type       | Constraints                          |
|--------------------|------------|--------------------------------------|
| id                 | UUID       | Primary key                          |
| product_id         | UUID       | Foreign key                          |
| variant_id         | UUID       | Foreign key (ProductVariant)         |
| warehouse_id       | UUID       | Foreign key (WarehouseLocation)      |
| quantity_on_hand   | integer    | Not null, >= 0                       |
| quantity_reserved  | integer    | Not null, >= 0                       |
| quantity_available | integer    | Computed: on_hand - reserved         |
| reorder_point      | integer    | Default 10                           |
| reorder_quantity   | integer    | Default 50                           |
| last_counted_at    | datetime   | Last physical count                  |
| version            | integer    | Optimistic concurrency control       |
| updated_at         | datetime   | Auto-updated (UTC)                   |

#### StockReservation

| Field              | Type       | Constraints                          |
|--------------------|------------|--------------------------------------|
| id                 | UUID       | Primary key                          |
| order_id           | UUID       | Foreign key                          |
| product_id         | UUID       | Foreign key                          |
| variant_id         | UUID       | Foreign key                          |
| warehouse_id       | UUID       | Foreign key                          |
| quantity           | integer    | > 0                                  |
| status             | string     | Enum: reserved, committed, released  |
| expires_at         | datetime   | Reservation timeout (15 min default) |
| created_at         | datetime   | Auto-generated (UTC)                 |

#### StockMovement

| Field              | Type       | Constraints                          |
|--------------------|------------|--------------------------------------|
| id                 | UUID       | Primary key                          |
| product_id         | UUID       | Foreign key                          |
| variant_id         | UUID       | Foreign key                          |
| from_warehouse_id  | UUID       | Nullable (null = external receipt)   |
| to_warehouse_id    | UUID       | Nullable (null = external shipment)  |
| quantity           | integer    | > 0                                  |
| movement_type      | string     | Enum: receipt, shipment, transfer, adjustment, return |
| reference_id       | UUID       | Order or transfer reference          |
| notes              | text       | Nullable                             |
| created_by         | UUID       | User who created the movement        |
| created_at         | datetime   | Auto-generated (UTC)                 |

### Endpoints

#### GET /inventory/stock/{product_id}

Get stock levels for a product across all warehouses.

- **Response 200**:
  ```json
  {
    "product_id": "UUID",
    "total_available": 500,
    "warehouses": [
      {
        "warehouse_id": "UUID",
        "warehouse_code": "WH-NYC-01",
        "quantity_on_hand": 200,
        "quantity_reserved": 20,
        "quantity_available": 180,
        "reorder_point": 10
      }
    ]
  }
  ```
- **Response 404**: `{ "detail": "Product not found in inventory" }`

#### POST /inventory/reserve

Create a stock reservation for a checkout session.

- **Request Body**:
  ```json
  {
    "order_id": "UUID",
    "items": [
      {
        "product_id": "UUID",
        "variant_id": "UUID",
        "quantity": 2,
        "preferred_warehouse_id": "UUID (optional)"
      }
    ]
  }
  ```
- **Response 201**:
  ```json
  {
    "reservation_id": "UUID",
    "items": [
      {
        "product_id": "UUID",
        "variant_id": "UUID",
        "warehouse_id": "UUID",
        "quantity": 2,
        "status": "reserved",
        "expires_at": "ISO8601"
      }
    ]
  }
  ```
- **Response 409**: `{ "detail": "Insufficient stock for item <sku>" }`

#### POST /inventory/commit

Commit a reservation (order confirmed).

- **Request Body**: `{ "reservation_id": "UUID" }`
- **Response 200**: `{ "status": "committed" }`
- **Response 404**: `{ "detail": "Reservation not found" }`
- **Response 410**: `{ "detail": "Reservation expired" }`

#### POST /inventory/release

Release a reservation (order cancelled or expired).

- **Request Body**: `{ "reservation_id": "UUID" }`
- **Response 200**: `{ "status": "released" }`

#### POST /inventory/adjust

Manual stock adjustment (admin only).

- **Headers**: `Authorization: Bearer <access_token>` (admin role)
- **Request Body**:
  ```json
  {
    "product_id": "UUID",
    "variant_id": "UUID",
    "warehouse_id": "UUID",
    "adjustment": -5,
    "reason": "string"
  }
  ```
- **Response 200**: Updated stock level

#### POST /inventory/transfer

Transfer stock between warehouses.

- **Headers**: `Authorization: Bearer <access_token>` (admin role)
- **Request Body**:
  ```json
  {
    "product_id": "UUID",
    "variant_id": "UUID",
    "from_warehouse_id": "UUID",
    "to_warehouse_id": "UUID",
    "quantity": 50
  }
  ```
- **Response 201**: Transfer movement record

#### GET /inventory/movements

List stock movements with filtering.

- **Query Parameters**: `product_id`, `warehouse_id`, `movement_type`, `from_date`, `to_date`, `page`, `per_page`
- **Response 200**: Paginated list of movements

#### GET /inventory/alerts

Get low stock alerts.

- **Response 200**:
  ```json
  {
    "alerts": [
      {
        "product_id": "UUID",
        "variant_id": "UUID",
        "warehouse_id": "UUID",
        "quantity_available": 3,
        "reorder_point": 10,
        "suggested_reorder": 50
      }
    ]
  }
  ```

#### GET /health

Service health check endpoint.

- **Response 200**: `{ "status": "healthy", "version": "1.0.0" }`

### Events Published

| Event                    | Channel                        | Payload                                              |
|--------------------------|--------------------------------|------------------------------------------------------|
| inventory.reserved       | inventory/reserved             | `{ reservation_id, order_id, items }`               |
| inventory.committed      | inventory/committed            | `{ reservation_id, order_id }`                      |
| inventory.released       | inventory/released             | `{ reservation_id, order_id, reason }`              |
| inventory.low_stock      | inventory/low_stock            | `{ product_id, variant_id, warehouse_id, available, reorder_point }` |
| inventory.out_of_stock   | inventory/out_of_stock         | `{ product_id, variant_id, warehouse_id }`          |
| inventory.restocked      | inventory/restocked            | `{ product_id, variant_id, warehouse_id, new_quantity }` |

### Event Subscriptions

| Event              | Action                                                     |
|--------------------|------------------------------------------------------------|
| order.confirmed    | Commit stock reservations                                  |
| order.cancelled    | Release stock reservations                                 |
| order.returned     | Add returned stock back to inventory                       |

---

## Service 4: order-service

### Description

The order-service manages the complete order lifecycle from creation through fulfillment.
It coordinates with the inventory service for stock reservations, the payment service for
payment processing, and the shipping service for logistics. The service maintains a
comprehensive state machine for order status transitions with validation rules.

The order service supports draft orders, order editing before payment, partial fulfillment,
returns and refunds, and order notes. It also provides real-time order status updates via
Server-Sent Events (SSE).

### Data Model

#### Order

| Field              | Type       | Constraints                          |
|--------------------|------------|--------------------------------------|
| id                 | UUID       | Primary key                          |
| order_number       | string     | Unique, auto-generated (e.g., ORD-2024-00001) |
| user_id            | UUID       | Foreign key (User)                   |
| status             | string     | Enum: draft, pending_payment, paid, processing, partially_shipped, shipped, delivered, cancelled, returned, refunded |
| items              | JSON       | Array of OrderItem                   |
| subtotal           | decimal    | Sum of item totals                   |
| tax_amount         | decimal    | Calculated tax                       |
| shipping_amount    | decimal    | Shipping cost                        |
| discount_amount    | decimal    | Applied discounts                    |
| total              | decimal    | Final total                          |
| currency           | string     | ISO 4217, default USD                |
| shipping_address   | JSON       | Delivery address object              |
| billing_address    | JSON       | Billing address object               |
| payment_id         | UUID       | Foreign key (Payment), nullable      |
| shipping_method    | string     | Selected shipping method             |
| tracking_number    | string     | Nullable                             |
| notes              | text       | Customer notes                       |
| internal_notes     | text       | Admin notes (not visible to customer)|
| coupon_code        | string     | Applied coupon, nullable             |
| reservation_id     | UUID       | Inventory reservation reference      |
| ip_address         | string     | Order placement IP                   |
| user_agent         | string     | Browser user agent                   |
| created_at         | datetime   | Auto-generated (UTC)                 |
| updated_at         | datetime   | Auto-updated (UTC)                   |
| paid_at            | datetime   | Nullable                             |
| shipped_at         | datetime   | Nullable                             |
| delivered_at       | datetime   | Nullable                             |
| cancelled_at       | datetime   | Nullable                             |

#### OrderItem

| Field              | Type       | Constraints                          |
|--------------------|------------|--------------------------------------|
| id                 | UUID       | Primary key                          |
| order_id           | UUID       | Foreign key (Order)                  |
| product_id         | UUID       | Foreign key                          |
| variant_id         | UUID       | Nullable                             |
| sku                | string     | Snapshot at order time               |
| name               | string     | Snapshot at order time               |
| quantity           | integer    | > 0                                  |
| unit_price         | decimal    | Price at order time                  |
| total_price        | decimal    | quantity * unit_price                |
| discount_amount    | decimal    | Per-item discount                    |
| tax_rate           | decimal    | Tax rate applied                     |
| fulfillment_status | string     | Enum: pending, shipped, delivered    |

#### OrderStatusHistory

| Field              | Type       | Constraints                          |
|--------------------|------------|--------------------------------------|
| id                 | UUID       | Primary key                          |
| order_id           | UUID       | Foreign key (Order)                  |
| from_status        | string     | Previous status                      |
| to_status          | string     | New status                           |
| changed_by         | UUID       | User or system that made the change  |
| reason             | string     | Nullable                             |
| metadata           | JSON       | Additional context                   |
| created_at         | datetime   | Auto-generated (UTC)                 |

### Endpoints

#### POST /orders

Create a new order (requires authentication).

- **Headers**: `Authorization: Bearer <access_token>`
- **Request Body**:
  ```json
  {
    "items": [
      { "product_id": "UUID", "variant_id": "UUID", "quantity": 2 }
    ],
    "shipping_address": {
      "street": "string", "city": "string", "state": "string",
      "zip": "string", "country": "string"
    },
    "billing_address": { "..." },
    "shipping_method": "standard",
    "coupon_code": "string (optional)",
    "notes": "string (optional)"
  }
  ```
- **Response 201**: Full order object with `status: "pending_payment"`
- **Response 401**: `{ "detail": "Not authenticated" }`
- **Response 409**: `{ "detail": "Insufficient stock for item <sku>" }`
- **Side Effects**: Creates inventory reservation, publishes `order.created`

#### GET /orders

List orders for the authenticated user.

- **Headers**: `Authorization: Bearer <access_token>`
- **Query Parameters**: `page`, `per_page`, `status`, `from_date`, `to_date`
- **Response 200**: Paginated order list

#### GET /orders/{order_id}

Get detailed order information.

- **Headers**: `Authorization: Bearer <access_token>`
- **Response 200**: Full order object with items, status history
- **Response 404**: `{ "detail": "Order not found" }`

#### PUT /orders/{order_id}/status

Update order status (with state machine validation).

- **Headers**: `Authorization: Bearer <access_token>`
- **Request Body**: `{ "status": "string", "reason": "string (optional)" }`
- **Response 200**: Updated order
- **Response 400**: `{ "detail": "Invalid status transition from <current> to <new>" }`
- **Response 404**: `{ "detail": "Order not found" }`

#### POST /orders/{order_id}/cancel

Cancel an order (before shipment only).

- **Headers**: `Authorization: Bearer <access_token>`
- **Request Body**: `{ "reason": "string" }`
- **Response 200**: Cancelled order
- **Response 400**: `{ "detail": "Cannot cancel order in status <status>" }`
- **Side Effects**: Releases inventory, initiates refund if paid

#### POST /orders/{order_id}/return

Initiate a return for a delivered order.

- **Headers**: `Authorization: Bearer <access_token>`
- **Request Body**:
  ```json
  {
    "items": [{ "item_id": "UUID", "quantity": 1, "reason": "string" }],
    "return_method": "mail|drop_off"
  }
  ```
- **Response 201**: Return request object
- **Response 400**: `{ "detail": "Order not eligible for return" }`

#### GET /orders/{order_id}/events

SSE endpoint for real-time order status updates.

- **Headers**: `Authorization: Bearer <access_token>`, `Accept: text/event-stream`
- **Response**: Server-Sent Events stream

#### GET /orders/admin

Admin endpoint to list all orders with advanced filtering.

- **Headers**: `Authorization: Bearer <access_token>` (admin role)
- **Query Parameters**: `status`, `user_id`, `from_date`, `to_date`, `min_total`, `max_total`, `page`, `per_page`
- **Response 200**: Paginated order list with admin details

#### GET /health

Service health check endpoint.

- **Response 200**: `{ "status": "healthy", "version": "1.0.0" }`

### Events Published

| Event                | Channel              | Payload                                                      |
|----------------------|----------------------|--------------------------------------------------------------|
| order.created        | order/created        | `{ order_id, user_id, items, total, created_at }`           |
| order.paid           | order/paid           | `{ order_id, user_id, payment_id, amount, paid_at }`        |
| order.shipped        | order/shipped        | `{ order_id, user_id, tracking_number, shipped_at }`        |
| order.delivered      | order/delivered      | `{ order_id, user_id, delivered_at }`                        |
| order.cancelled      | order/cancelled      | `{ order_id, user_id, reason, cancelled_at }`               |
| order.returned       | order/returned       | `{ order_id, user_id, return_items, returned_at }`          |
| order.status_changed | order/status_changed | `{ order_id, from_status, to_status, changed_by }`          |

### Event Subscriptions

| Event                  | Action                                                |
|------------------------|-------------------------------------------------------|
| payment.completed      | Update order status to paid                           |
| payment.failed         | Update order to pending_payment, notify user          |
| inventory.committed    | Confirm stock allocation for the order                |
| shipping.label_created | Update order with tracking number                     |

---

## Service 5: payment-service

### Description

The payment-service handles all payment processing for the MegaCommerce platform. It
integrates with multiple payment providers (Stripe, PayPal, bank transfers) through a
provider abstraction layer. The service supports payment intents, captures, refunds,
partial refunds, recurring billing, and payment method management.

PCI compliance is achieved through tokenization -- the service never stores raw card
numbers. All sensitive payment data is handled through provider SDKs that communicate
directly from the client to the provider's servers.

### Data Model

#### Payment

| Field              | Type       | Constraints                          |
|--------------------|------------|--------------------------------------|
| id                 | UUID       | Primary key                          |
| order_id           | UUID       | Foreign key (Order)                  |
| user_id            | UUID       | Foreign key (User)                   |
| provider           | string     | Enum: stripe, paypal, bank_transfer  |
| provider_payment_id| string     | External payment reference           |
| amount             | decimal    | Payment amount, precision 10,2       |
| currency           | string     | ISO 4217                             |
| status             | string     | Enum: pending, processing, completed, failed, refunded, partially_refunded |
| payment_method     | JSON       | Tokenized payment method details     |
| metadata           | JSON       | Provider-specific metadata           |
| error_message      | string     | Nullable                             |
| idempotency_key    | string     | Unique, for retry safety             |
| created_at         | datetime   | Auto-generated (UTC)                 |
| updated_at         | datetime   | Auto-updated (UTC)                   |
| completed_at       | datetime   | Nullable                             |

#### Refund

| Field              | Type       | Constraints                          |
|--------------------|------------|--------------------------------------|
| id                 | UUID       | Primary key                          |
| payment_id         | UUID       | Foreign key (Payment)                |
| amount             | decimal    | Refund amount                        |
| reason             | string     | Refund reason                        |
| status             | string     | Enum: pending, completed, failed     |
| provider_refund_id | string     | External refund reference            |
| created_at         | datetime   | Auto-generated (UTC)                 |
| completed_at       | datetime   | Nullable                             |

#### PaymentMethod

| Field              | Type       | Constraints                          |
|--------------------|------------|--------------------------------------|
| id                 | UUID       | Primary key                          |
| user_id            | UUID       | Foreign key (User)                   |
| provider           | string     | Payment provider                     |
| provider_token     | string     | Tokenized card/method reference      |
| type               | string     | Enum: card, paypal, bank_account     |
| last_four          | string     | Last 4 digits of card                |
| brand              | string     | Card brand (visa, mastercard, etc.)  |
| exp_month          | integer    | Expiration month                     |
| exp_year           | integer    | Expiration year                      |
| is_default         | boolean    | Default payment method               |
| created_at         | datetime   | Auto-generated (UTC)                 |

### Endpoints

#### POST /payments/create-intent

Create a payment intent for an order.

- **Headers**: `Authorization: Bearer <access_token>`
- **Request Body**:
  ```json
  {
    "order_id": "UUID",
    "amount": 99.99,
    "currency": "USD",
    "payment_method_id": "UUID (optional)",
    "provider": "stripe",
    "idempotency_key": "string"
  }
  ```
- **Response 201**:
  ```json
  {
    "payment_id": "UUID",
    "client_secret": "string (for frontend SDK)",
    "status": "pending"
  }
  ```

#### POST /payments/{payment_id}/capture

Capture a previously authorized payment.

- **Headers**: `Authorization: Bearer <access_token>`
- **Response 200**: `{ "payment_id": "UUID", "status": "completed", "completed_at": "ISO8601" }`
- **Response 400**: `{ "detail": "Payment cannot be captured in current status" }`

#### POST /payments/{payment_id}/refund

Issue a full or partial refund.

- **Headers**: `Authorization: Bearer <access_token>`
- **Request Body**:
  ```json
  {
    "amount": 25.00,
    "reason": "Customer requested return"
  }
  ```
- **Response 201**: Refund object
- **Response 400**: `{ "detail": "Refund amount exceeds original payment" }`

#### GET /payments/{payment_id}

Get payment details.

- **Headers**: `Authorization: Bearer <access_token>`
- **Response 200**: Full payment object with refund history

#### GET /payments/methods

List saved payment methods for the authenticated user.

- **Headers**: `Authorization: Bearer <access_token>`
- **Response 200**: Array of payment methods

#### POST /payments/methods

Save a new payment method.

- **Headers**: `Authorization: Bearer <access_token>`
- **Request Body**: `{ "provider": "stripe", "provider_token": "tok_xxx", "set_default": true }`
- **Response 201**: Saved payment method

#### DELETE /payments/methods/{method_id}

Remove a saved payment method.

- **Headers**: `Authorization: Bearer <access_token>`
- **Response 204**: No content

#### POST /payments/webhook/{provider}

Webhook endpoint for payment provider callbacks.

- **Request Body**: Provider-specific webhook payload
- **Response 200**: `{ "received": true }`
- **Security**: Webhook signature verification

#### GET /health

Service health check endpoint.

- **Response 200**: `{ "status": "healthy", "version": "1.0.0" }`

### Events Published

| Event                  | Channel                  | Payload                                              |
|------------------------|--------------------------|------------------------------------------------------|
| payment.completed      | payment/completed        | `{ payment_id, order_id, amount, provider }`        |
| payment.failed         | payment/failed           | `{ payment_id, order_id, error_message }`           |
| payment.refunded       | payment/refunded         | `{ payment_id, order_id, refund_amount, reason }`   |

### Event Subscriptions

| Event              | Action                                                     |
|--------------------|------------------------------------------------------------|
| order.cancelled    | Auto-refund if payment was completed                       |

---

## Service 6: shipping-service

### Description

The shipping-service manages shipment logistics, carrier integration, rate calculation,
label generation, and package tracking. It integrates with multiple shipping carriers
(FedEx, UPS, USPS, DHL) through a unified carrier abstraction. The service calculates
optimal shipping rates based on package dimensions, weight, origin/destination, and
delivery speed requirements.

### Data Model

#### Shipment

| Field              | Type       | Constraints                          |
|--------------------|------------|--------------------------------------|
| id                 | UUID       | Primary key                          |
| order_id           | UUID       | Foreign key (Order)                  |
| carrier            | string     | Enum: fedex, ups, usps, dhl         |
| service_level      | string     | E.g., ground, express, overnight     |
| tracking_number    | string     | Unique, nullable until shipped       |
| label_url          | string     | Shipping label PDF URL               |
| status             | string     | Enum: created, label_created, picked_up, in_transit, out_for_delivery, delivered, exception, returned |
| estimated_delivery | datetime   | Carrier estimated delivery           |
| actual_delivery    | datetime   | Nullable                             |
| origin_address     | JSON       | Warehouse address                    |
| destination_address| JSON       | Customer address                     |
| packages           | JSON       | Array of package details             |
| shipping_cost      | decimal    | Actual shipping cost                 |
| insurance_cost     | decimal    | Optional insurance cost              |
| weight_kg          | decimal    | Total weight                         |
| created_at         | datetime   | Auto-generated (UTC)                 |
| updated_at         | datetime   | Auto-updated (UTC)                   |

#### ShippingRate

| Field              | Type       | Constraints                          |
|--------------------|------------|--------------------------------------|
| id                 | UUID       | Primary key                          |
| carrier            | string     | Shipping carrier                     |
| service_level      | string     | Service tier                         |
| origin_zip         | string     | Origin postal code                   |
| destination_zip    | string     | Destination postal code              |
| weight_range_min   | decimal    | Minimum weight (kg)                  |
| weight_range_max   | decimal    | Maximum weight (kg)                  |
| base_rate          | decimal    | Base shipping cost                   |
| per_kg_rate        | decimal    | Additional cost per kg               |
| estimated_days     | integer    | Estimated transit days               |
| is_active          | boolean    | Default true                         |

#### TrackingEvent

| Field              | Type       | Constraints                          |
|--------------------|------------|--------------------------------------|
| id                 | UUID       | Primary key                          |
| shipment_id        | UUID       | Foreign key (Shipment)               |
| event_type         | string     | Status event type                    |
| location           | string     | Event location                       |
| description        | string     | Event description                    |
| timestamp          | datetime   | Event occurrence time                |
| carrier_event_id   | string     | Carrier's event ID                   |
| created_at         | datetime   | Auto-generated (UTC)                 |

### Endpoints

#### POST /shipping/rates

Calculate shipping rates for a set of items.

- **Request Body**:
  ```json
  {
    "origin": { "zip": "string", "country": "string" },
    "destination": { "zip": "string", "country": "string" },
    "packages": [
      { "weight_kg": 2.5, "length_cm": 30, "width_cm": 20, "height_cm": 10 }
    ]
  }
  ```
- **Response 200**:
  ```json
  {
    "rates": [
      {
        "carrier": "fedex",
        "service_level": "ground",
        "rate": 12.99,
        "currency": "USD",
        "estimated_days": 5,
        "guaranteed_delivery": false
      }
    ]
  }
  ```

#### POST /shipping/shipments

Create a new shipment.

- **Headers**: `Authorization: Bearer <access_token>` (admin/merchant)
- **Request Body**:
  ```json
  {
    "order_id": "UUID",
    "carrier": "fedex",
    "service_level": "ground",
    "packages": [...],
    "origin_warehouse_id": "UUID"
  }
  ```
- **Response 201**: Shipment object with `status: "created"`

#### POST /shipping/shipments/{shipment_id}/label

Generate a shipping label.

- **Headers**: `Authorization: Bearer <access_token>` (admin/merchant)
- **Response 200**: `{ "label_url": "string", "tracking_number": "string" }`
- **Side Effects**: Publishes `shipping.label_created`

#### GET /shipping/shipments/{shipment_id}/track

Get tracking events for a shipment.

- **Response 200**:
  ```json
  {
    "tracking_number": "string",
    "carrier": "fedex",
    "status": "in_transit",
    "estimated_delivery": "ISO8601",
    "events": [
      {
        "event_type": "in_transit",
        "location": "Memphis, TN",
        "description": "Package in transit",
        "timestamp": "ISO8601"
      }
    ]
  }
  ```

#### POST /shipping/webhook/{carrier}

Webhook for carrier tracking updates.

- **Request Body**: Carrier-specific tracking payload
- **Response 200**: `{ "received": true }`

#### GET /health

Service health check endpoint.

- **Response 200**: `{ "status": "healthy", "version": "1.0.0" }`

### Events Published

| Event                    | Channel                    | Payload                                          |
|--------------------------|----------------------------|--------------------------------------------------|
| shipping.label_created   | shipping/label_created     | `{ shipment_id, order_id, tracking_number }`    |
| shipping.picked_up       | shipping/picked_up         | `{ shipment_id, order_id, carrier }`            |
| shipping.in_transit      | shipping/in_transit        | `{ shipment_id, order_id, location }`           |
| shipping.delivered       | shipping/delivered         | `{ shipment_id, order_id, delivered_at }`       |
| shipping.exception       | shipping/exception         | `{ shipment_id, order_id, exception_type }`     |

### Event Subscriptions

| Event              | Action                                                     |
|--------------------|------------------------------------------------------------|
| order.paid         | Create shipment for the order                              |
| order.cancelled    | Cancel pending shipments                                   |

---

## Service 7: notification-service

### Description

The notification-service is the central communication hub for the MegaCommerce platform.
It handles email, SMS, push notifications, and in-app notifications. The service uses
templated messages with variable substitution, supports notification preferences per user,
batching for high-volume sends, and delivery tracking.

The service integrates with SendGrid for email, Twilio for SMS, and Firebase Cloud
Messaging (FCM) for push notifications. All notifications are queued via RabbitMQ for
reliable delivery with retry logic.

### Data Model

#### Notification

| Field              | Type       | Constraints                          |
|--------------------|------------|--------------------------------------|
| id                 | UUID       | Primary key                          |
| user_id            | UUID       | Target user                          |
| channel            | string     | Enum: email, sms, push, in_app      |
| template_id        | string     | Notification template identifier     |
| subject            | string     | Notification subject                 |
| body               | text       | Rendered notification body           |
| data               | JSON       | Template variables                   |
| status             | string     | Enum: queued, sending, sent, delivered, failed, bounced |
| priority           | string     | Enum: low, normal, high, critical    |
| provider_message_id| string     | External message reference           |
| error_message      | string     | Nullable                             |
| retry_count        | integer    | Default 0                            |
| max_retries        | integer    | Default 3                            |
| scheduled_at       | datetime   | Nullable (for delayed sends)         |
| sent_at            | datetime   | Nullable                             |
| delivered_at       | datetime   | Nullable                             |
| read_at            | datetime   | Nullable (for in-app)                |
| created_at         | datetime   | Auto-generated (UTC)                 |

#### NotificationTemplate

| Field              | Type       | Constraints                          |
|--------------------|------------|--------------------------------------|
| id                 | string     | Primary key (e.g., "order.confirmed")|
| channel            | string     | Target channel                       |
| subject_template   | string     | Subject with {{variables}}           |
| body_template      | text       | Body with {{variables}}              |
| is_active          | boolean    | Default true                         |
| version            | integer    | Template version                     |
| created_at         | datetime   | Auto-generated (UTC)                 |
| updated_at         | datetime   | Auto-updated (UTC)                   |

#### NotificationPreference

| Field              | Type       | Constraints                          |
|--------------------|------------|--------------------------------------|
| id                 | UUID       | Primary key                          |
| user_id            | UUID       | Foreign key (User)                   |
| channel            | string     | Notification channel                 |
| category           | string     | E.g., "order_updates", "promotions"  |
| enabled            | boolean    | Default true                         |
| updated_at         | datetime   | Auto-updated (UTC)                   |

### Endpoints

#### POST /notifications/send

Send a notification to a user.

- **Headers**: `Authorization: Bearer <access_token>`
- **Request Body**:
  ```json
  {
    "user_id": "UUID",
    "channel": "email",
    "template_id": "order.confirmed",
    "data": { "order_number": "ORD-2024-00001", "total": 99.99 },
    "priority": "high",
    "scheduled_at": "ISO8601 (optional)"
  }
  ```
- **Response 201**: `{ "notification_id": "UUID", "status": "queued" }`

#### POST /notifications/broadcast

Send a notification to multiple users.

- **Headers**: `Authorization: Bearer <access_token>` (admin)
- **Request Body**:
  ```json
  {
    "user_ids": ["UUID"],
    "channel": "push",
    "template_id": "promotion.flash_sale",
    "data": { "sale_name": "Summer Sale", "discount": "20%" }
  }
  ```
- **Response 202**: `{ "batch_id": "UUID", "total_recipients": 500, "status": "processing" }`

#### GET /notifications

List notifications for the authenticated user.

- **Headers**: `Authorization: Bearer <access_token>`
- **Query Parameters**: `channel`, `status`, `page`, `per_page`, `unread_only`
- **Response 200**: Paginated notification list

#### PUT /notifications/{notification_id}/read

Mark a notification as read.

- **Headers**: `Authorization: Bearer <access_token>`
- **Response 200**: `{ "read_at": "ISO8601" }`

#### GET /notifications/preferences

Get notification preferences for the authenticated user.

- **Headers**: `Authorization: Bearer <access_token>`
- **Response 200**: Array of preference objects

#### PUT /notifications/preferences

Update notification preferences.

- **Headers**: `Authorization: Bearer <access_token>`
- **Request Body**: Array of preference updates
- **Response 200**: Updated preferences

#### GET /notifications/templates

List notification templates (admin only).

- **Headers**: `Authorization: Bearer <access_token>` (admin)
- **Response 200**: Array of templates

#### GET /health

Service health check endpoint.

- **Response 200**: `{ "status": "healthy", "version": "1.0.0" }`

### Event Subscriptions

| Event                  | Action                                                |
|------------------------|-------------------------------------------------------|
| user.registered        | Send welcome email                                    |
| user.password_changed  | Send password change confirmation                     |
| order.created          | Send order confirmation                               |
| order.shipped          | Send shipping notification with tracking              |
| order.delivered        | Send delivery confirmation                            |
| order.cancelled        | Send cancellation confirmation                        |
| payment.completed      | Send payment receipt                                  |
| payment.failed         | Send payment failure alert                            |
| payment.refunded       | Send refund confirmation                              |
| inventory.low_stock    | Alert merchants about low stock                       |
| review.submitted       | Notify merchant of new review                         |

---

## Service 8: review-service

### Description

The review-service manages product reviews and ratings. It supports text reviews,
star ratings (1-5), review images, helpful/unhelpful votes, merchant responses,
and automated review moderation using content filters. The service computes aggregate
ratings that are published to the catalog service.

### Data Model

#### Review

| Field              | Type       | Constraints                          |
|--------------------|------------|--------------------------------------|
| id                 | UUID       | Primary key                          |
| product_id         | UUID       | Foreign key                          |
| user_id            | UUID       | Foreign key (User)                   |
| order_id           | UUID       | Must have purchased the product      |
| rating             | integer    | 1-5                                  |
| title              | string     | Max 200 chars                        |
| body               | text       | Max 5000 chars                       |
| images             | JSON       | Array of image URLs (max 5)          |
| status             | string     | Enum: pending, approved, rejected    |
| moderation_notes   | string     | Nullable                             |
| helpful_count      | integer    | Default 0                            |
| unhelpful_count    | integer    | Default 0                            |
| verified_purchase  | boolean    | Auto-set based on order verification |
| created_at         | datetime   | Auto-generated (UTC)                 |
| updated_at         | datetime   | Auto-updated (UTC)                   |

#### ReviewResponse

| Field              | Type       | Constraints                          |
|--------------------|------------|--------------------------------------|
| id                 | UUID       | Primary key                          |
| review_id          | UUID       | Foreign key (Review)                 |
| user_id            | UUID       | Merchant/admin user                  |
| body               | text       | Response text                        |
| created_at         | datetime   | Auto-generated (UTC)                 |

#### ReviewVote

| Field              | Type       | Constraints                          |
|--------------------|------------|--------------------------------------|
| id                 | UUID       | Primary key                          |
| review_id          | UUID       | Foreign key (Review)                 |
| user_id            | UUID       | Voter                                |
| vote_type          | string     | Enum: helpful, unhelpful             |
| created_at         | datetime   | Auto-generated (UTC)                 |

### Endpoints

#### POST /reviews

Submit a product review.

- **Headers**: `Authorization: Bearer <access_token>`
- **Request Body**:
  ```json
  {
    "product_id": "UUID",
    "order_id": "UUID",
    "rating": 5,
    "title": "Great product!",
    "body": "Very satisfied with this purchase...",
    "images": ["data:image/jpeg;base64,..."]
  }
  ```
- **Response 201**: Review object with `status: "pending"`
- **Response 400**: `{ "detail": "You have already reviewed this product" }`
- **Response 403**: `{ "detail": "Must purchase product before reviewing" }`

#### GET /reviews/product/{product_id}

List reviews for a product.

- **Query Parameters**: `page`, `per_page`, `sort_by` (newest, highest, lowest, most_helpful), `rating`
- **Response 200**:
  ```json
  {
    "items": [{ "..." }],
    "total": 42,
    "average_rating": 4.5,
    "rating_distribution": { "5": 20, "4": 12, "3": 5, "2": 3, "1": 2 }
  }
  ```

#### PUT /reviews/{review_id}

Update own review.

- **Headers**: `Authorization: Bearer <access_token>`
- **Request Body**: Updated review fields
- **Response 200**: Updated review

#### DELETE /reviews/{review_id}

Delete own review.

- **Headers**: `Authorization: Bearer <access_token>`
- **Response 204**: No content

#### POST /reviews/{review_id}/vote

Vote on a review's helpfulness.

- **Headers**: `Authorization: Bearer <access_token>`
- **Request Body**: `{ "vote_type": "helpful" }`
- **Response 200**: `{ "helpful_count": 15, "unhelpful_count": 2 }`

#### POST /reviews/{review_id}/respond

Merchant response to a review.

- **Headers**: `Authorization: Bearer <access_token>` (merchant)
- **Request Body**: `{ "body": "Thank you for your feedback..." }`
- **Response 201**: Response object

#### PUT /reviews/admin/{review_id}/moderate

Moderate a review (approve/reject).

- **Headers**: `Authorization: Bearer <access_token>` (admin)
- **Request Body**: `{ "status": "approved", "notes": "string (optional)" }`
- **Response 200**: Moderated review

#### GET /health

Service health check.

- **Response 200**: `{ "status": "healthy", "version": "1.0.0" }`

### Events Published

| Event                | Channel              | Payload                                          |
|----------------------|----------------------|--------------------------------------------------|
| review.submitted     | review/submitted     | `{ review_id, product_id, user_id, rating }`   |
| review.approved      | review/approved      | `{ review_id, product_id, rating }`             |
| review.aggregated    | review/aggregated    | `{ product_id, average_rating, review_count }`  |

---

## Service 9: cart-service

### Description

The cart-service manages shopping carts with support for guest carts (cookie-based),
authenticated carts (persisted), cart merging on login, coupon application, abandoned
cart recovery, and real-time price/availability validation.

### Data Model

#### Cart

| Field              | Type       | Constraints                          |
|--------------------|------------|--------------------------------------|
| id                 | UUID       | Primary key                          |
| user_id            | UUID       | Nullable (null for guest carts)      |
| session_id         | string     | For guest cart identification        |
| items              | JSON       | Array of CartItem                    |
| coupon_code        | string     | Nullable                             |
| subtotal           | decimal    | Computed                             |
| discount_amount    | decimal    | Computed from coupon                 |
| tax_estimate       | decimal    | Estimated tax                        |
| total_estimate     | decimal    | Subtotal - discount + tax            |
| currency           | string     | ISO 4217, default USD                |
| expires_at         | datetime   | Cart expiry (30 days)                |
| created_at         | datetime   | Auto-generated (UTC)                 |
| updated_at         | datetime   | Auto-updated (UTC)                   |

#### CartItem

| Field              | Type       | Constraints                          |
|--------------------|------------|--------------------------------------|
| product_id         | UUID       | Product reference                    |
| variant_id         | UUID       | Nullable                             |
| quantity           | integer    | > 0                                  |
| unit_price         | decimal    | Current product price                |
| name               | string     | Product name snapshot                |
| image_url          | string     | Product image                        |

### Endpoints

#### GET /cart

Get the current cart.

- **Headers**: `Authorization: Bearer <access_token>` (optional)
- **Cookie**: `cart_session_id` (for guest carts)
- **Response 200**: Full cart object

#### POST /cart/items

Add an item to the cart.

- **Request Body**: `{ "product_id": "UUID", "variant_id": "UUID", "quantity": 1 }`
- **Response 200**: Updated cart
- **Response 409**: `{ "detail": "Product is out of stock" }`

#### PUT /cart/items/{product_id}

Update item quantity.

- **Request Body**: `{ "quantity": 3 }`
- **Response 200**: Updated cart

#### DELETE /cart/items/{product_id}

Remove an item from the cart.

- **Response 200**: Updated cart

#### POST /cart/coupon

Apply a coupon code.

- **Request Body**: `{ "coupon_code": "SUMMER20" }`
- **Response 200**: Updated cart with discount
- **Response 400**: `{ "detail": "Invalid or expired coupon" }`

#### DELETE /cart/coupon

Remove applied coupon.

- **Response 200**: Updated cart

#### POST /cart/merge

Merge guest cart into authenticated cart on login.

- **Headers**: `Authorization: Bearer <access_token>`
- **Request Body**: `{ "guest_session_id": "string" }`
- **Response 200**: Merged cart

#### POST /cart/checkout

Validate cart and create an order.

- **Headers**: `Authorization: Bearer <access_token>`
- **Request Body**:
  ```json
  {
    "shipping_address": { "..." },
    "billing_address": { "..." },
    "shipping_method": "standard"
  }
  ```
- **Response 201**: `{ "order_id": "UUID", "redirect_to": "/orders/<order_id>/pay" }`
- **Response 400**: `{ "detail": "Cart validation failed", "errors": [...] }`

#### GET /health

Service health check.

- **Response 200**: `{ "status": "healthy", "version": "1.0.0" }`

### Events Published

| Event                  | Channel              | Payload                              |
|------------------------|----------------------|--------------------------------------|
| cart.abandoned         | cart/abandoned       | `{ cart_id, user_id, items, total }` |
| cart.checkout_started  | cart/checkout        | `{ cart_id, user_id }`              |

---

## Service 10: search-service

### Description

The search-service provides advanced search capabilities powered by Elasticsearch.
It handles full-text search, autocomplete, spell correction, search analytics,
personalized results based on user behavior, and A/B testing for search relevance tuning.

### Data Model

#### SearchIndex

| Field              | Type       | Constraints                          |
|--------------------|------------|--------------------------------------|
| product_id         | UUID       | Document ID                          |
| name               | string     | Searchable, boosted                  |
| description        | string     | Searchable                           |
| category_path      | string     | Facetable                            |
| brand              | string     | Facetable                            |
| tags               | string[]   | Searchable, facetable                |
| price              | decimal    | Sortable, rangeable                  |
| rating             | decimal    | Sortable                             |
| popularity_score   | decimal    | Sort boosting factor                 |
| in_stock           | boolean    | Filterable                           |
| image_url          | string     | Display only                         |
| created_at         | datetime   | Sortable                             |

#### SearchQuery

| Field              | Type       | Constraints                          |
|--------------------|------------|--------------------------------------|
| id                 | UUID       | Primary key                          |
| user_id            | UUID       | Nullable                             |
| query_text         | string     | Raw search query                     |
| filters_applied    | JSON       | Filters used                         |
| results_count      | integer    | Number of results                    |
| clicked_product_id | UUID       | Nullable (if user clicked a result)  |
| conversion         | boolean    | Whether search led to purchase       |
| created_at         | datetime   | Auto-generated (UTC)                 |

### Endpoints

#### GET /search

Full-text product search.

- **Query Parameters**: `q` (search query), `category`, `brand`, `min_price`, `max_price`, `in_stock`, `sort`, `page`, `per_page`
- **Response 200**:
  ```json
  {
    "query": "wireless headphones",
    "items": [{ "..." }],
    "total": 150,
    "suggestions": ["wireless earbuds", "bluetooth headphones"],
    "facets": { "..." },
    "spell_correction": null
  }
  ```

#### GET /search/autocomplete

Autocomplete suggestions.

- **Query Parameters**: `q` (partial query), `limit` (default 5)
- **Response 200**:
  ```json
  {
    "suggestions": [
      { "text": "wireless headphones", "category": "Electronics", "score": 0.95 }
    ]
  }
  ```

#### GET /search/trending

Get trending searches.

- **Response 200**: `{ "trending": ["iphone 15", "airpods", "laptop stand"] }`

#### POST /search/reindex

Trigger full reindex (admin only).

- **Headers**: `Authorization: Bearer <access_token>` (admin)
- **Response 202**: `{ "job_id": "UUID", "status": "indexing" }`

#### GET /health

Service health check.

- **Response 200**: `{ "status": "healthy", "version": "1.0.0", "elasticsearch_status": "green" }`

---

## Service 11: analytics-service

### Description

The analytics-service collects, processes, and serves business intelligence data.
It tracks page views, product impressions, conversion funnels, revenue metrics,
customer cohort analysis, and real-time dashboards. Data is ingested via events
and stored in a time-series optimized schema.

### Data Model

#### Event

| Field              | Type       | Constraints                          |
|--------------------|------------|--------------------------------------|
| id                 | UUID       | Primary key                          |
| event_type         | string     | E.g., "page_view", "add_to_cart"    |
| user_id            | UUID       | Nullable (anonymous events)          |
| session_id         | string     | Browser session                      |
| properties         | JSON       | Event-specific data                  |
| ip_address         | string     | Client IP                            |
| user_agent         | string     | Browser info                         |
| referrer           | string     | Referring URL                        |
| timestamp          | datetime   | Event occurrence time                |
| created_at         | datetime   | Auto-generated (UTC)                 |

#### DailyMetric

| Field              | Type       | Constraints                          |
|--------------------|------------|--------------------------------------|
| date               | date       | Partition key                        |
| metric_name        | string     | E.g., "revenue", "orders", "visitors"|
| value              | decimal    | Metric value                         |
| dimensions         | JSON       | `{ category, brand, region }`        |
| updated_at         | datetime   | Auto-updated                         |

### Endpoints

#### POST /analytics/events

Track an analytics event.

- **Request Body**:
  ```json
  {
    "event_type": "page_view",
    "properties": { "page": "/products/123", "referrer": "google.com" },
    "session_id": "string"
  }
  ```
- **Response 202**: `{ "received": true }`

#### GET /analytics/dashboard

Get dashboard metrics.

- **Headers**: `Authorization: Bearer <access_token>` (admin/merchant)
- **Query Parameters**: `from_date`, `to_date`, `granularity` (hour, day, week, month)
- **Response 200**:
  ```json
  {
    "revenue": { "total": 150000, "trend": 12.5, "data_points": [...] },
    "orders": { "total": 3200, "trend": 8.3, "data_points": [...] },
    "visitors": { "total": 45000, "trend": -2.1, "data_points": [...] },
    "conversion_rate": { "value": 3.2, "trend": 0.5 },
    "average_order_value": { "value": 46.87, "trend": 1.2 }
  }
  ```

#### GET /analytics/funnel

Get conversion funnel data.

- **Headers**: `Authorization: Bearer <access_token>` (admin/merchant)
- **Query Parameters**: `from_date`, `to_date`
- **Response 200**:
  ```json
  {
    "stages": [
      { "name": "page_view", "count": 45000 },
      { "name": "product_view", "count": 18000 },
      { "name": "add_to_cart", "count": 5400 },
      { "name": "checkout_started", "count": 3800 },
      { "name": "order_completed", "count": 3200 }
    ]
  }
  ```

#### GET /analytics/products/top

Get top performing products.

- **Headers**: `Authorization: Bearer <access_token>` (admin/merchant)
- **Query Parameters**: `metric` (revenue, units, views), `limit`, `from_date`, `to_date`
- **Response 200**: Array of product performance data

#### GET /analytics/cohorts

Get customer cohort analysis.

- **Headers**: `Authorization: Bearer <access_token>` (admin)
- **Query Parameters**: `cohort_type` (registration_month, first_purchase), `from_date`, `to_date`
- **Response 200**: Cohort retention matrix

#### GET /health

Service health check.

- **Response 200**: `{ "status": "healthy", "version": "1.0.0" }`

### Event Subscriptions

| Event                  | Action                                            |
|------------------------|---------------------------------------------------|
| order.created          | Track order creation metric                       |
| order.paid             | Track revenue metric                              |
| user.registered        | Track new user metric                             |
| cart.abandoned         | Track abandoned cart metric                       |
| product.viewed         | Track product impression                          |

---

## Service 12: coupon-service

### Description

The coupon-service manages promotional codes, discount rules, and coupon validation.
It supports percentage discounts, fixed amount discounts, free shipping, buy-X-get-Y
promotions, and tiered discounts. Coupons can be restricted by user, product category,
minimum order amount, usage limits, and date ranges.

### Data Model

#### Coupon

| Field              | Type       | Constraints                          |
|--------------------|------------|--------------------------------------|
| id                 | UUID       | Primary key                          |
| code               | string     | Unique, uppercase, max 50 chars      |
| description        | string     | Admin description                    |
| discount_type      | string     | Enum: percentage, fixed, free_shipping, buy_x_get_y |
| discount_value     | decimal    | Discount amount or percentage        |
| min_order_amount   | decimal    | Minimum order total, nullable        |
| max_discount       | decimal    | Cap on discount amount, nullable     |
| usage_limit        | integer    | Total usage limit, nullable          |
| per_user_limit     | integer    | Per-user usage limit, default 1      |
| times_used         | integer    | Current usage count                  |
| applicable_products| UUID[]     | Specific products, nullable (=all)   |
| applicable_categories| UUID[]   | Specific categories, nullable (=all) |
| starts_at          | datetime   | Validity start                       |
| expires_at         | datetime   | Validity end                         |
| is_active          | boolean    | Default true                         |
| created_by         | UUID       | Admin who created                    |
| created_at         | datetime   | Auto-generated (UTC)                 |
| updated_at         | datetime   | Auto-updated (UTC)                   |

#### CouponUsage

| Field              | Type       | Constraints                          |
|--------------------|------------|--------------------------------------|
| id                 | UUID       | Primary key                          |
| coupon_id          | UUID       | Foreign key (Coupon)                 |
| user_id            | UUID       | User who used the coupon             |
| order_id           | UUID       | Order where coupon was applied       |
| discount_applied   | decimal    | Actual discount amount               |
| created_at         | datetime   | Auto-generated (UTC)                 |

### Endpoints

#### POST /coupons/validate

Validate a coupon code for a cart.

- **Request Body**:
  ```json
  {
    "code": "SUMMER20",
    "user_id": "UUID",
    "cart_total": 150.00,
    "items": [{ "product_id": "UUID", "category_id": "UUID", "quantity": 2, "price": 75.00 }]
  }
  ```
- **Response 200**:
  ```json
  {
    "valid": true,
    "discount_amount": 30.00,
    "discount_type": "percentage",
    "message": "20% off applied"
  }
  ```
- **Response 400**: `{ "valid": false, "message": "Coupon has expired" }`

#### POST /coupons

Create a new coupon (admin only).

- **Headers**: `Authorization: Bearer <access_token>` (admin)
- **Request Body**: Full coupon object
- **Response 201**: Created coupon

#### GET /coupons

List coupons (admin only).

- **Headers**: `Authorization: Bearer <access_token>` (admin)
- **Query Parameters**: `is_active`, `search`, `page`, `per_page`
- **Response 200**: Paginated coupon list

#### PUT /coupons/{coupon_id}

Update a coupon (admin only).

- **Headers**: `Authorization: Bearer <access_token>` (admin)
- **Response 200**: Updated coupon

#### DELETE /coupons/{coupon_id}

Deactivate a coupon (admin only).

- **Headers**: `Authorization: Bearer <access_token>` (admin)
- **Response 204**: No content

#### POST /coupons/{coupon_id}/record-usage

Record coupon usage (internal, called by order-service).

- **Request Body**: `{ "user_id": "UUID", "order_id": "UUID", "discount_applied": 30.00 }`
- **Response 200**: `{ "recorded": true }`

#### GET /health

Service health check.

- **Response 200**: `{ "status": "healthy", "version": "1.0.0" }`

---

## Service 13: recommendation-service

### Description

The recommendation-service provides AI-powered product recommendations using
collaborative filtering, content-based filtering, and hybrid approaches. It serves
personalized recommendations on product pages, the homepage, in emails, and during
checkout. The service maintains user behavior profiles and product similarity matrices
that are updated periodically through batch processing jobs.

### Data Model

#### UserProfile

| Field              | Type       | Constraints                          |
|--------------------|------------|--------------------------------------|
| user_id            | UUID       | Primary key                          |
| viewed_products    | UUID[]     | Last 100 viewed products             |
| purchased_products | UUID[]     | All purchased products               |
| category_affinities| JSON       | `{ category_id: score }` map         |
| brand_affinities   | JSON       | `{ brand_id: score }` map            |
| price_range        | JSON       | `{ min, max, avg }` preferred range  |
| updated_at         | datetime   | Auto-updated                         |

#### ProductSimilarity

| Field              | Type       | Constraints                          |
|--------------------|------------|--------------------------------------|
| product_id         | UUID       | Source product                       |
| similar_product_id | UUID       | Similar product                      |
| similarity_score   | decimal    | 0-1 similarity score                |
| algorithm          | string     | Which algorithm computed this        |
| computed_at        | datetime   | When similarity was computed         |

#### RecommendationLog

| Field              | Type       | Constraints                          |
|--------------------|------------|--------------------------------------|
| id                 | UUID       | Primary key                          |
| user_id            | UUID       | Target user                          |
| context            | string     | Where recommendations were shown     |
| recommended_ids    | UUID[]     | Products recommended                 |
| clicked_id         | UUID       | Product user clicked, nullable       |
| algorithm_used     | string     | Which algorithm was used             |
| created_at         | datetime   | Auto-generated                       |

### Endpoints

#### GET /recommendations/products/{product_id}

Get similar products (content-based).

- **Query Parameters**: `limit` (default 10)
- **Response 200**:
  ```json
  {
    "product_id": "UUID",
    "recommendations": [
      { "product_id": "UUID", "name": "string", "price": 29.99, "score": 0.92 }
    ]
  }
  ```

#### GET /recommendations/user

Get personalized recommendations for authenticated user.

- **Headers**: `Authorization: Bearer <access_token>`
- **Query Parameters**: `context` (homepage, checkout, email), `limit`
- **Response 200**: Array of recommended products with scores

#### GET /recommendations/trending

Get trending products.

- **Query Parameters**: `category_id`, `limit`
- **Response 200**: Array of trending products

#### GET /recommendations/frequently-bought-together/{product_id}

Get frequently bought together products.

- **Response 200**: Array of product bundles with combined discount

#### POST /recommendations/retrain

Trigger model retraining (admin only).

- **Headers**: `Authorization: Bearer <access_token>` (admin)
- **Response 202**: `{ "job_id": "UUID", "status": "training" }`

#### GET /health

Service health check.

- **Response 200**: `{ "status": "healthy", "version": "1.0.0" }`

### Event Subscriptions

| Event              | Action                                                     |
|--------------------|------------------------------------------------------------|
| order.paid         | Update user purchase history and product co-occurrence     |
| product.viewed     | Update user viewing history                                |
| review.approved    | Factor review sentiment into recommendations               |

---

## Service 14: media-service

### Description

The media-service handles file uploads, image processing, and media asset management.
It supports image resizing, format conversion (WebP, AVIF), CDN integration, and
automatic thumbnail generation. The service stores original files in object storage
(S3-compatible) and serves processed versions through a CDN with cache invalidation.

### Data Model

#### MediaAsset

| Field              | Type       | Constraints                          |
|--------------------|------------|--------------------------------------|
| id                 | UUID       | Primary key                          |
| original_url       | string     | S3 URL of original file              |
| cdn_url            | string     | CDN URL for serving                  |
| filename           | string     | Original filename                    |
| mime_type          | string     | MIME type                            |
| size_bytes         | integer    | File size                            |
| width              | integer    | Image width (nullable for non-images)|
| height             | integer    | Image height                         |
| alt_text           | string     | Accessibility text                   |
| variants           | JSON       | Generated size variants              |
| uploaded_by        | UUID       | User who uploaded                    |
| entity_type        | string     | E.g., "product", "review", "brand"  |
| entity_id          | UUID       | Related entity                       |
| created_at         | datetime   | Auto-generated (UTC)                 |

### Endpoints

#### POST /media/upload

Upload a media file.

- **Headers**: `Authorization: Bearer <access_token>`
- **Request Body**: Multipart form data with file
- **Response 201**:
  ```json
  {
    "id": "UUID",
    "original_url": "string",
    "cdn_url": "string",
    "variants": {
      "thumbnail": "string (150x150)",
      "small": "string (300x300)",
      "medium": "string (600x600)",
      "large": "string (1200x1200)"
    }
  }
  ```
- **Response 413**: `{ "detail": "File too large (max 10MB)" }`
- **Response 415**: `{ "detail": "Unsupported file type" }`

#### GET /media/{media_id}

Get media asset details.

- **Response 200**: Full media asset object

#### DELETE /media/{media_id}

Delete a media asset.

- **Headers**: `Authorization: Bearer <access_token>`
- **Response 204**: No content

#### POST /media/bulk-upload

Upload multiple files at once.

- **Headers**: `Authorization: Bearer <access_token>`
- **Request Body**: Multipart form with multiple files
- **Response 201**: Array of created media assets

#### POST /media/{media_id}/regenerate

Regenerate image variants (admin only).

- **Headers**: `Authorization: Bearer <access_token>` (admin)
- **Response 202**: `{ "status": "processing" }`

#### GET /health

Service health check.

- **Response 200**: `{ "status": "healthy", "version": "1.0.0", "storage_status": "connected" }`

---

## Inter-Service Contracts

### JWT Authentication Flow

1. Client calls `POST /auth/login` on auth-service to obtain access/refresh token pair
2. Client includes `Authorization: Bearer <token>` on all requests to other services
3. All services validate JWT signature using the auth-service public key
4. Token payload includes: `sub` (user_id), `role`, `exp`, `iat`, `jti`

### Event Contract

- **Transport**: Redis Pub/Sub for real-time events, RabbitMQ for reliable queued events
- **Serialization**: JSON with schema versioning
- **Naming**: `{service}/{event_type}` (e.g., `order/created`)
- **Dead Letter**: Failed events are routed to a dead-letter queue after 3 retries
- **Schema Registry**: All event schemas are registered in the contract engine

### Service Communication Matrix

| From               | To                  | Method   | Purpose                              |
|--------------------|---------------------|----------|--------------------------------------|
| order-service      | inventory-service   | REST     | Stock reservation/commitment         |
| order-service      | payment-service     | REST     | Payment processing                   |
| order-service      | shipping-service    | REST     | Shipment creation                    |
| order-service      | coupon-service      | REST     | Coupon validation & recording        |
| cart-service       | catalog-service     | REST     | Product price/availability lookup    |
| cart-service       | coupon-service      | REST     | Coupon validation                    |
| cart-service       | order-service       | REST     | Order creation from cart             |
| search-service     | catalog-service     | REST     | Product data for indexing            |
| recommendation-svc | catalog-service     | REST     | Product data for model training      |
| notification-svc   | auth-service        | REST     | User email/phone lookup              |
| review-service     | order-service       | REST     | Purchase verification                |
| analytics-service  | ALL                 | Events   | Collects events from all services    |
| media-service      | catalog-service     | Events   | Image URL updates                    |

---

## Deployment

All 14 services are deployed as Docker containers orchestrated via Docker Compose.
Each service has its own PostgreSQL database instance for data isolation. Redis and
RabbitMQ are shared infrastructure. Elasticsearch is shared between catalog-service,
search-service, and analytics-service.

```yaml
services:
  auth-service:
    build: ./auth-service
    ports: ["8001:8000"]
    environment:
      DATABASE_URL: postgresql://auth:password@postgres-auth:5432/auth
      JWT_PRIVATE_KEY_PATH: /secrets/jwt_private.pem
      JWT_PUBLIC_KEY_PATH: /secrets/jwt_public.pem
      REDIS_URL: redis://redis:6379/0
    depends_on: [postgres-auth, redis]
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/health"]
      interval: 30s
      timeout: 10s
      retries: 3

  catalog-service:
    build: ./catalog-service
    ports: ["8002:8000"]
    environment:
      DATABASE_URL: postgresql://catalog:password@postgres-catalog:5432/catalog
      ELASTICSEARCH_URL: http://elasticsearch:9200
      REDIS_URL: redis://redis:6379/1
      JWT_PUBLIC_KEY_PATH: /secrets/jwt_public.pem
    depends_on: [postgres-catalog, elasticsearch, redis]

  inventory-service:
    build: ./inventory-service
    ports: ["8003:8000"]
    environment:
      DATABASE_URL: postgresql://inventory:password@postgres-inventory:5432/inventory
      REDIS_URL: redis://redis:6379/2
      JWT_PUBLIC_KEY_PATH: /secrets/jwt_public.pem
    depends_on: [postgres-inventory, redis]

  order-service:
    build: ./order-service
    ports: ["8004:8000"]
    environment:
      DATABASE_URL: postgresql://orders:password@postgres-orders:5432/orders
      REDIS_URL: redis://redis:6379/3
      RABBITMQ_URL: amqp://guest:guest@rabbitmq:5672
      INVENTORY_SERVICE_URL: http://inventory-service:8000
      PAYMENT_SERVICE_URL: http://payment-service:8000
      SHIPPING_SERVICE_URL: http://shipping-service:8000
      COUPON_SERVICE_URL: http://coupon-service:8000
      JWT_PUBLIC_KEY_PATH: /secrets/jwt_public.pem
    depends_on: [postgres-orders, redis, rabbitmq]

  payment-service:
    build: ./payment-service
    ports: ["8005:8000"]
    environment:
      DATABASE_URL: postgresql://payments:password@postgres-payments:5432/payments
      STRIPE_SECRET_KEY: ${STRIPE_SECRET_KEY}
      STRIPE_WEBHOOK_SECRET: ${STRIPE_WEBHOOK_SECRET}
      PAYPAL_CLIENT_ID: ${PAYPAL_CLIENT_ID}
      PAYPAL_CLIENT_SECRET: ${PAYPAL_CLIENT_SECRET}
      REDIS_URL: redis://redis:6379/4
      JWT_PUBLIC_KEY_PATH: /secrets/jwt_public.pem
    depends_on: [postgres-payments, redis]

  shipping-service:
    build: ./shipping-service
    ports: ["8006:8000"]
    environment:
      DATABASE_URL: postgresql://shipping:password@postgres-shipping:5432/shipping
      FEDEX_API_KEY: ${FEDEX_API_KEY}
      UPS_API_KEY: ${UPS_API_KEY}
      REDIS_URL: redis://redis:6379/5
      JWT_PUBLIC_KEY_PATH: /secrets/jwt_public.pem
    depends_on: [postgres-shipping, redis]

  notification-service:
    build: ./notification-service
    ports: ["8007:8000"]
    environment:
      DATABASE_URL: postgresql://notifications:password@postgres-notifications:5432/notifications
      SENDGRID_API_KEY: ${SENDGRID_API_KEY}
      TWILIO_ACCOUNT_SID: ${TWILIO_ACCOUNT_SID}
      TWILIO_AUTH_TOKEN: ${TWILIO_AUTH_TOKEN}
      FCM_SERVER_KEY: ${FCM_SERVER_KEY}
      REDIS_URL: redis://redis:6379/6
      RABBITMQ_URL: amqp://guest:guest@rabbitmq:5672
      JWT_PUBLIC_KEY_PATH: /secrets/jwt_public.pem
    depends_on: [postgres-notifications, redis, rabbitmq]

  review-service:
    build: ./review-service
    ports: ["8008:8000"]
    environment:
      DATABASE_URL: postgresql://reviews:password@postgres-reviews:5432/reviews
      REDIS_URL: redis://redis:6379/7
      ORDER_SERVICE_URL: http://order-service:8000
      JWT_PUBLIC_KEY_PATH: /secrets/jwt_public.pem
    depends_on: [postgres-reviews, redis]

  cart-service:
    build: ./cart-service
    ports: ["8009:8000"]
    environment:
      DATABASE_URL: postgresql://carts:password@postgres-carts:5432/carts
      REDIS_URL: redis://redis:6379/8
      CATALOG_SERVICE_URL: http://catalog-service:8000
      COUPON_SERVICE_URL: http://coupon-service:8000
      ORDER_SERVICE_URL: http://order-service:8000
      JWT_PUBLIC_KEY_PATH: /secrets/jwt_public.pem
    depends_on: [postgres-carts, redis]

  search-service:
    build: ./search-service
    ports: ["8010:8000"]
    environment:
      ELASTICSEARCH_URL: http://elasticsearch:9200
      REDIS_URL: redis://redis:6379/9
      CATALOG_SERVICE_URL: http://catalog-service:8000
      JWT_PUBLIC_KEY_PATH: /secrets/jwt_public.pem
    depends_on: [elasticsearch, redis]

  analytics-service:
    build: ./analytics-service
    ports: ["8011:8000"]
    environment:
      DATABASE_URL: postgresql://analytics:password@postgres-analytics:5432/analytics
      ELASTICSEARCH_URL: http://elasticsearch:9200
      REDIS_URL: redis://redis:6379/10
      RABBITMQ_URL: amqp://guest:guest@rabbitmq:5672
      JWT_PUBLIC_KEY_PATH: /secrets/jwt_public.pem
    depends_on: [postgres-analytics, elasticsearch, redis, rabbitmq]

  coupon-service:
    build: ./coupon-service
    ports: ["8012:8000"]
    environment:
      DATABASE_URL: postgresql://coupons:password@postgres-coupons:5432/coupons
      REDIS_URL: redis://redis:6379/11
      JWT_PUBLIC_KEY_PATH: /secrets/jwt_public.pem
    depends_on: [postgres-coupons, redis]

  recommendation-service:
    build: ./recommendation-service
    ports: ["8013:8000"]
    environment:
      DATABASE_URL: postgresql://recommendations:password@postgres-recommendations:5432/recommendations
      REDIS_URL: redis://redis:6379/12
      CATALOG_SERVICE_URL: http://catalog-service:8000
      JWT_PUBLIC_KEY_PATH: /secrets/jwt_public.pem
    depends_on: [postgres-recommendations, redis]

  media-service:
    build: ./media-service
    ports: ["8014:8000"]
    environment:
      DATABASE_URL: postgresql://media:password@postgres-media:5432/media
      S3_BUCKET: megacommerce-media
      S3_ENDPOINT: http://minio:9000
      S3_ACCESS_KEY: ${S3_ACCESS_KEY}
      S3_SECRET_KEY: ${S3_SECRET_KEY}
      CDN_BASE_URL: https://cdn.megacommerce.com
      JWT_PUBLIC_KEY_PATH: /secrets/jwt_public.pem
    depends_on: [postgres-media, minio]

  # Shared infrastructure
  postgres-auth:
    image: postgres:16
    environment: { POSTGRES_DB: auth, POSTGRES_USER: auth, POSTGRES_PASSWORD: password }
    volumes: [pgdata-auth:/var/lib/postgresql/data]

  postgres-catalog:
    image: postgres:16
    environment: { POSTGRES_DB: catalog, POSTGRES_USER: catalog, POSTGRES_PASSWORD: password }
    volumes: [pgdata-catalog:/var/lib/postgresql/data]

  postgres-inventory:
    image: postgres:16
    environment: { POSTGRES_DB: inventory, POSTGRES_USER: inventory, POSTGRES_PASSWORD: password }
    volumes: [pgdata-inventory:/var/lib/postgresql/data]

  postgres-orders:
    image: postgres:16
    environment: { POSTGRES_DB: orders, POSTGRES_USER: orders, POSTGRES_PASSWORD: password }
    volumes: [pgdata-orders:/var/lib/postgresql/data]

  postgres-payments:
    image: postgres:16
    environment: { POSTGRES_DB: payments, POSTGRES_USER: payments, POSTGRES_PASSWORD: password }
    volumes: [pgdata-payments:/var/lib/postgresql/data]

  postgres-shipping:
    image: postgres:16
    environment: { POSTGRES_DB: shipping, POSTGRES_USER: shipping, POSTGRES_PASSWORD: password }
    volumes: [pgdata-shipping:/var/lib/postgresql/data]

  postgres-notifications:
    image: postgres:16
    environment: { POSTGRES_DB: notifications, POSTGRES_USER: notifications, POSTGRES_PASSWORD: password }
    volumes: [pgdata-notifications:/var/lib/postgresql/data]

  postgres-reviews:
    image: postgres:16
    environment: { POSTGRES_DB: reviews, POSTGRES_USER: reviews, POSTGRES_PASSWORD: password }
    volumes: [pgdata-reviews:/var/lib/postgresql/data]

  postgres-carts:
    image: postgres:16
    environment: { POSTGRES_DB: carts, POSTGRES_USER: carts, POSTGRES_PASSWORD: password }
    volumes: [pgdata-carts:/var/lib/postgresql/data]

  postgres-analytics:
    image: postgres:16
    environment: { POSTGRES_DB: analytics, POSTGRES_USER: analytics, POSTGRES_PASSWORD: password }
    volumes: [pgdata-analytics:/var/lib/postgresql/data]

  postgres-coupons:
    image: postgres:16
    environment: { POSTGRES_DB: coupons, POSTGRES_USER: coupons, POSTGRES_PASSWORD: password }
    volumes: [pgdata-coupons:/var/lib/postgresql/data]

  postgres-recommendations:
    image: postgres:16
    environment: { POSTGRES_DB: recommendations, POSTGRES_USER: recommendations, POSTGRES_PASSWORD: password }
    volumes: [pgdata-recommendations:/var/lib/postgresql/data]

  postgres-media:
    image: postgres:16
    environment: { POSTGRES_DB: media, POSTGRES_USER: media, POSTGRES_PASSWORD: password }
    volumes: [pgdata-media:/var/lib/postgresql/data]

  redis:
    image: redis:7.2
    ports: ["6379:6379"]
    command: redis-server --maxmemory 512mb --maxmemory-policy allkeys-lru

  rabbitmq:
    image: rabbitmq:3.13-management
    ports: ["5672:5672", "15672:15672"]
    environment:
      RABBITMQ_DEFAULT_USER: guest
      RABBITMQ_DEFAULT_PASS: guest

  elasticsearch:
    image: elasticsearch:8.12.0
    ports: ["9200:9200"]
    environment:
      - discovery.type=single-node
      - xpack.security.enabled=false
      - "ES_JAVA_OPTS=-Xms512m -Xmx512m"
    volumes: [esdata:/var/lib/elasticsearch/data]

  minio:
    image: minio/minio:latest
    ports: ["9000:9000", "9001:9001"]
    command: server /data --console-address ":9001"
    environment:
      MINIO_ROOT_USER: ${S3_ACCESS_KEY}
      MINIO_ROOT_PASSWORD: ${S3_SECRET_KEY}
    volumes: [miniodata:/data]

  traefik:
    image: traefik:v3.6
    ports: ["80:80", "443:443", "8080:8080"]
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock:ro
      - ./traefik.yml:/etc/traefik/traefik.yml:ro
    command:
      - --api.dashboard=true
      - --providers.docker=true
      - --entryPoints.web.address=:80

volumes:
  pgdata-auth:
  pgdata-catalog:
  pgdata-inventory:
  pgdata-orders:
  pgdata-payments:
  pgdata-shipping:
  pgdata-notifications:
  pgdata-reviews:
  pgdata-carts:
  pgdata-analytics:
  pgdata-coupons:
  pgdata-recommendations:
  pgdata-media:
  esdata:
  miniodata:
```

---

## Non-Functional Requirements

### Performance

- API response time < 200ms (p95) for read endpoints
- API response time < 500ms (p95) for write endpoints
- Search response time < 100ms (p95)
- Support 10,000 concurrent users
- Handle 1,000 orders per minute during peak

### Availability

- 99.9% uptime SLA
- Zero-downtime deployments
- Circuit breakers between all service-to-service calls
- Graceful degradation when non-critical services are down

### Security

- All inter-service communication over HTTPS in production
- JWT tokens signed with RS256
- Rate limiting on all public endpoints
- CORS configured per service
- SQL injection prevention via parameterized queries
- XSS prevention through response sanitization
- OWASP Top 10 compliance

### Observability

- Structured JSON logging with correlation IDs
- Distributed tracing via OpenTelemetry (W3C Trace Context)
- Prometheus metrics on /metrics endpoint per service
- Health check endpoints on /health per service
- Grafana dashboards for service health, latency, error rates
- Alert rules for error rate > 1%, latency p99 > 1s

### Data Consistency

- Saga pattern for distributed transactions (order creation)
- Eventual consistency for search index updates (< 5s lag)
- Idempotency keys for all payment operations
- Optimistic concurrency control for inventory updates
- Event sourcing for order status changes

---

## Testing Strategy

### Unit Tests

- Minimum 80% code coverage per service
- Test all business logic functions
- Mock external dependencies (databases, APIs, message brokers)

### Integration Tests

- Test all API endpoints per service
- Test database migrations up and down
- Test event publishing and consumption
- Test authentication/authorization flows

### Contract Tests

- Pact-based consumer-driven contract tests
- OpenAPI specification validation
- Event schema validation
- Breaking change detection

### End-to-End Tests

- Full user journey: browse -> cart -> checkout -> payment -> delivery
- Cross-service event propagation verification
- Error handling and recovery scenarios
- Load testing with k6 (10,000 virtual users)

---

## Migration Strategy

### Phase 1: Core Services (Week 1-2)
Deploy auth-service, catalog-service, cart-service

### Phase 2: Transaction Services (Week 3-4)
Deploy order-service, payment-service, inventory-service

### Phase 3: Communication Services (Week 5-6)
Deploy notification-service, shipping-service, media-service

### Phase 4: Intelligence Services (Week 7-8)
Deploy search-service, review-service, recommendation-service, analytics-service, coupon-service

### Phase 5: Integration & Hardening (Week 9-10)
Full integration testing, performance optimization, security audit

---

## Appendix A: Detailed API Error Codes

### Auth Service Error Codes

| Code    | HTTP Status | Description                                | Resolution                                      |
|---------|-------------|--------------------------------------------|-------------------------------------------------|
| AUTH-001 | 401        | Invalid credentials provided               | Verify email and password combination           |
| AUTH-002 | 401        | Access token has expired                   | Refresh using the refresh token endpoint        |
| AUTH-003 | 401        | Refresh token is invalid or revoked        | User must log in again                          |
| AUTH-004 | 409        | Email address already registered           | Use a different email or reset password         |
| AUTH-005 | 422        | Password complexity requirements not met   | Include uppercase, lowercase, digit, special    |
| AUTH-006 | 423        | Account temporarily locked                 | Wait for lockout period to expire               |
| AUTH-007 | 401        | Invalid MFA verification code              | Enter correct 6-digit TOTP code                |
| AUTH-008 | 400        | MFA already enabled for this account       | Disable MFA before re-enabling                  |
| AUTH-009 | 400        | Invalid or expired password reset token    | Request a new password reset email              |
| AUTH-010 | 400        | Invalid or expired email verification token| Request a new verification email                |
| AUTH-011 | 403        | Insufficient permissions for admin endpoint| Requires admin role                             |
| AUTH-012 | 400        | Invalid OAuth authorization code           | Retry the OAuth flow                            |
| AUTH-013 | 400        | OAuth provider returned an error           | Check provider configuration                    |
| AUTH-014 | 429        | Rate limit exceeded for login attempts     | Wait 15 minutes before retrying                 |
| AUTH-015 | 404        | Session not found                          | Session may have already been revoked           |
| AUTH-016 | 400        | Current password is incorrect              | Verify the current password and retry           |
| AUTH-017 | 400        | New password same as current password      | Choose a different password                     |
| AUTH-018 | 400        | Account has been deleted                   | Contact support for account recovery            |
| AUTH-019 | 400        | Account has been suspended                 | Contact support for account reinstatement       |
| AUTH-020 | 422        | Invalid phone number format                | Use E.164 format (e.g., +1234567890)            |

### Catalog Service Error Codes

| Code     | HTTP Status | Description                                | Resolution                                      |
|----------|-------------|--------------------------------------------|-------------------------------------------------|
| CAT-001  | 404        | Product not found                          | Verify the product ID                           |
| CAT-002  | 404        | Category not found                         | Verify the category ID                          |
| CAT-003  | 404        | Brand not found                            | Verify the brand ID                             |
| CAT-004  | 409        | SKU already exists                         | Use a unique SKU                                |
| CAT-005  | 409        | Product slug already exists                | Use a unique slug                               |
| CAT-006  | 422        | Invalid price value                        | Price must be >= 0 with precision 10,2          |
| CAT-007  | 403        | Merchant role required                     | Only merchants and admins can manage products   |
| CAT-008  | 403        | Admin role required                        | Only admins can manage categories               |
| CAT-009  | 400        | Circular category reference detected       | Category cannot be its own parent               |
| CAT-010  | 422        | Maximum category depth exceeded            | Categories support max 5 levels of nesting      |
| CAT-011  | 400        | Bulk import file too large                 | Maximum 10MB file size                          |
| CAT-012  | 400        | Invalid bulk import format                 | Accepted formats: CSV, JSON                     |
| CAT-013  | 422        | Invalid product dimensions                 | All dimensions must be > 0                      |
| CAT-014  | 422        | Too many product images                    | Maximum 20 images per product                   |
| CAT-015  | 422        | Invalid image URL format                   | Must be a valid HTTPS URL                       |
| CAT-016  | 400        | Product is already archived                | Cannot modify archived products                 |
| CAT-017  | 409        | Category slug already exists under parent  | Use a unique slug within the parent category    |
| CAT-018  | 400        | Cannot delete category with products       | Move or delete products first                   |
| CAT-019  | 503        | Elasticsearch index unavailable            | Search is temporarily unavailable               |
| CAT-020  | 422        | Variant attributes conflict                | Variant attribute combination must be unique    |

### Inventory Service Error Codes

| Code     | HTTP Status | Description                                | Resolution                                      |
|----------|-------------|--------------------------------------------|-------------------------------------------------|
| INV-001  | 404        | Product not found in inventory             | Register the product with inventory service     |
| INV-002  | 409        | Insufficient stock for reservation         | Reduce quantity or wait for restock             |
| INV-003  | 404        | Reservation not found                      | Verify the reservation ID                       |
| INV-004  | 410        | Reservation has expired                    | Create a new reservation                        |
| INV-005  | 409        | Reservation already committed              | Cannot modify committed reservations            |
| INV-006  | 409        | Optimistic concurrency conflict            | Retry the operation                             |
| INV-007  | 404        | Warehouse not found                        | Verify the warehouse ID                         |
| INV-008  | 400        | Cannot transfer to same warehouse          | Source and destination must differ              |
| INV-009  | 409        | Insufficient stock for transfer            | Reduce transfer quantity                        |
| INV-010  | 422        | Adjustment would result in negative stock  | Cannot adjust below zero                        |
| INV-011  | 403        | Admin role required for adjustments        | Only admins can make manual adjustments         |
| INV-012  | 400        | Invalid movement type                      | Use: receipt, shipment, transfer, adjustment    |
| INV-013  | 422        | Quantity must be positive                  | All quantities must be > 0                      |
| INV-014  | 400        | Warehouse is not active                    | Reactivate the warehouse first                  |
| INV-015  | 409        | Warehouse capacity exceeded                | Cannot add more stock to this warehouse         |

### Order Service Error Codes

| Code     | HTTP Status | Description                                | Resolution                                      |
|----------|-------------|--------------------------------------------|-------------------------------------------------|
| ORD-001  | 404        | Order not found                            | Verify the order ID                             |
| ORD-002  | 400        | Invalid status transition                  | Check allowed transitions from current status   |
| ORD-003  | 400        | Cannot cancel order in current status      | Only pending/processing orders can be cancelled |
| ORD-004  | 400        | Order not eligible for return              | Only delivered orders within return window      |
| ORD-005  | 409        | Stock reservation failed                   | Items may be out of stock                       |
| ORD-006  | 400        | Empty order items                          | Order must contain at least one item            |
| ORD-007  | 422        | Invalid shipping address                   | Verify address fields                           |
| ORD-008  | 400        | Invalid coupon code                        | Verify coupon is valid for this order           |
| ORD-009  | 403        | Order belongs to different user            | Users can only access their own orders          |
| ORD-010  | 403        | Admin role required                        | Only admins can access admin order endpoints    |
| ORD-011  | 400        | Return window has expired                  | Returns must be within 30 days of delivery      |
| ORD-012  | 422        | Return quantity exceeds ordered quantity   | Cannot return more than purchased               |
| ORD-013  | 400        | Payment failed for this order              | Retry payment or use different payment method   |
| ORD-014  | 400        | Duplicate idempotency key                  | This request has already been processed         |
| ORD-015  | 400        | Order total is zero or negative            | Verify item prices and quantities               |

### Payment Service Error Codes

| Code     | HTTP Status | Description                                | Resolution                                      |
|----------|-------------|--------------------------------------------|-------------------------------------------------|
| PAY-001  | 400        | Payment cannot be captured in current status| Only authorized payments can be captured        |
| PAY-002  | 400        | Refund amount exceeds original payment     | Reduce refund amount                            |
| PAY-003  | 400        | Payment already refunded                   | Cannot refund a fully refunded payment          |
| PAY-004  | 404        | Payment not found                          | Verify the payment ID                           |
| PAY-005  | 400        | Invalid payment provider                   | Supported: stripe, paypal, bank_transfer        |
| PAY-006  | 402        | Card declined by issuer                    | Use a different card or contact bank            |
| PAY-007  | 400        | Insufficient funds                         | Use a different payment method                  |
| PAY-008  | 400        | Invalid card number                        | Verify card details                             |
| PAY-009  | 400        | Card expired                               | Use a non-expired card                          |
| PAY-010  | 400        | Invalid CVC                                | Verify the security code                        |
| PAY-011  | 400        | Duplicate idempotency key                  | This payment has already been processed         |
| PAY-012  | 404        | Payment method not found                   | Verify the payment method ID                    |
| PAY-013  | 400        | Invalid webhook signature                  | Webhook payload tampered or wrong secret        |
| PAY-014  | 503        | Payment provider temporarily unavailable   | Retry after a short delay                       |
| PAY-015  | 400        | Currency not supported                     | Supported: USD, EUR, GBP, CAD, AUD             |

### Shipping Service Error Codes

| Code     | HTTP Status | Description                                | Resolution                                      |
|----------|-------------|--------------------------------------------|-------------------------------------------------|
| SHIP-001 | 404        | Shipment not found                         | Verify the shipment ID                          |
| SHIP-002 | 400        | Cannot generate label in current status    | Shipment must be in "created" status            |
| SHIP-003 | 400        | Invalid carrier                            | Supported: fedex, ups, usps, dhl               |
| SHIP-004 | 400        | Address validation failed                  | Verify shipping address                         |
| SHIP-005 | 400        | Package dimensions exceed carrier limits   | Reduce package size or use different carrier    |
| SHIP-006 | 400        | Package weight exceeds carrier limits      | Reduce weight or split into multiple packages   |
| SHIP-007 | 503        | Carrier API temporarily unavailable        | Retry after a short delay                       |
| SHIP-008 | 400        | Invalid tracking number                    | Verify with carrier                             |
| SHIP-009 | 400        | Shipment already delivered                 | Cannot modify delivered shipments               |
| SHIP-010 | 422        | Invalid postal code for destination        | Verify postal code                              |

### Notification Service Error Codes

| Code     | HTTP Status | Description                                | Resolution                                      |
|----------|-------------|--------------------------------------------|-------------------------------------------------|
| NOTIF-001| 400        | Invalid notification channel               | Supported: email, sms, push, in_app             |
| NOTIF-002| 404        | Template not found                         | Verify the template ID                          |
| NOTIF-003| 400        | Missing required template variables        | Provide all required variables in data field    |
| NOTIF-004| 404        | Notification not found                     | Verify the notification ID                      |
| NOTIF-005| 400        | User has disabled this notification type   | Cannot send when user has opted out             |
| NOTIF-006| 429        | Notification rate limit exceeded           | Too many notifications to this user             |
| NOTIF-007| 503        | Email provider temporarily unavailable     | Will retry automatically                        |
| NOTIF-008| 503        | SMS provider temporarily unavailable       | Will retry automatically                        |
| NOTIF-009| 400        | Invalid phone number for SMS               | User must have a valid phone number             |
| NOTIF-010| 400        | Push notification token expired            | User needs to re-register push token            |

### Review Service Error Codes

| Code     | HTTP Status | Description                                | Resolution                                      |
|----------|-------------|--------------------------------------------|-------------------------------------------------|
| REV-001  | 400        | Already reviewed this product              | Users can only submit one review per product    |
| REV-002  | 403        | Must purchase product before reviewing     | Only verified purchasers can review             |
| REV-003  | 404        | Review not found                           | Verify the review ID                            |
| REV-004  | 403        | Cannot edit another user's review          | Users can only edit their own reviews           |
| REV-005  | 400        | Rating must be between 1 and 5            | Provide a valid rating value                    |
| REV-006  | 422        | Review body exceeds maximum length         | Maximum 5000 characters                         |
| REV-007  | 400        | Too many images in review                  | Maximum 5 images per review                     |
| REV-008  | 403        | Merchant role required for responses       | Only merchants can respond to reviews           |
| REV-009  | 403        | Admin role required for moderation         | Only admins can moderate reviews                |
| REV-010  | 400        | Review already has a merchant response     | Merchants can only respond once                 |

### Cart Service Error Codes

| Code     | HTTP Status | Description                                | Resolution                                      |
|----------|-------------|--------------------------------------------|-------------------------------------------------|
| CART-001 | 409        | Product is out of stock                    | Item is no longer available                     |
| CART-002 | 400        | Invalid coupon code                        | Verify coupon is valid and not expired          |
| CART-003 | 400        | Cart is empty                              | Add items before checkout                       |
| CART-004 | 400        | Cart validation failed                     | Check individual item availability and prices   |
| CART-005 | 404        | Product not found                          | Product may have been removed                   |
| CART-006 | 422        | Quantity exceeds available stock           | Reduce quantity                                 |
| CART-007 | 400        | Maximum cart items exceeded                | Maximum 50 unique items per cart                |
| CART-008 | 400        | Guest session ID not found for merge       | Guest cart may have expired                     |
| CART-009 | 400        | Cart has expired                           | Create a new cart                               |
| CART-010 | 400        | Coupon minimum order not met               | Add more items to meet minimum                  |

### Search Service Error Codes

| Code     | HTTP Status | Description                                | Resolution                                      |
|----------|-------------|--------------------------------------------|-------------------------------------------------|
| SRCH-001 | 400        | Empty search query                         | Provide a search term                           |
| SRCH-002 | 503        | Elasticsearch cluster unavailable          | Search is temporarily unavailable               |
| SRCH-003 | 400        | Invalid search filter combination          | Check filter parameter values                   |
| SRCH-004 | 422        | Page number exceeds available results      | Reduce page number                              |
| SRCH-005 | 400        | Search query too long                      | Maximum 200 characters                          |

### Analytics Service Error Codes

| Code     | HTTP Status | Description                                | Resolution                                      |
|----------|-------------|--------------------------------------------|-------------------------------------------------|
| ANA-001  | 400        | Invalid date range                         | from_date must be before to_date                |
| ANA-002  | 400        | Date range too large                       | Maximum 1 year range                            |
| ANA-003  | 400        | Invalid granularity                        | Supported: hour, day, week, month               |
| ANA-004  | 403        | Admin or merchant role required            | Dashboard requires elevated permissions         |
| ANA-005  | 503        | Analytics processing backlog               | Data may be delayed                             |

### Coupon Service Error Codes

| Code     | HTTP Status | Description                                | Resolution                                      |
|----------|-------------|--------------------------------------------|-------------------------------------------------|
| CPN-001  | 400        | Coupon has expired                         | The coupon is no longer valid                   |
| CPN-002  | 400        | Coupon usage limit reached                 | This coupon has been fully used                 |
| CPN-003  | 400        | Per-user usage limit reached               | You have already used this coupon               |
| CPN-004  | 400        | Minimum order amount not met               | Order total must meet minimum requirement       |
| CPN-005  | 400        | Coupon not applicable to these products    | Check product/category restrictions             |
| CPN-006  | 404        | Coupon code not found                      | Verify the coupon code                          |
| CPN-007  | 409        | Coupon code already exists                 | Use a different coupon code                     |
| CPN-008  | 403        | Admin role required                        | Only admins can manage coupons                  |

### Recommendation Service Error Codes

| Code     | HTTP Status | Description                                | Resolution                                      |
|----------|-------------|--------------------------------------------|-------------------------------------------------|
| REC-001  | 404        | Product not found in recommendation index  | Product may not have been indexed yet           |
| REC-002  | 404        | No recommendations available               | Insufficient data for recommendations           |
| REC-003  | 400        | Invalid recommendation context             | Supported: homepage, checkout, email            |
| REC-004  | 503        | Recommendation model is being retrained    | Temporarily unavailable during training         |
| REC-005  | 403        | Admin role required for retraining         | Only admins can trigger model retraining        |

### Media Service Error Codes

| Code     | HTTP Status | Description                                | Resolution                                      |
|----------|-------------|--------------------------------------------|-------------------------------------------------|
| MED-001  | 413        | File too large                             | Maximum 10MB for images, 50MB for videos        |
| MED-002  | 415        | Unsupported file type                      | Accepted: JPEG, PNG, GIF, WebP, SVG            |
| MED-003  | 404        | Media asset not found                      | Verify the media ID                             |
| MED-004  | 400        | Image processing failed                    | File may be corrupted                           |
| MED-005  | 503        | Object storage unavailable                 | Storage is temporarily unavailable              |
| MED-006  | 400        | Maximum 10 files per bulk upload           | Reduce number of files                          |
| MED-007  | 403        | Cannot delete another user's media         | Only asset owner or admin can delete            |

---

## Appendix B: Detailed Sequence Diagrams

### B.1 User Registration Flow

```
Client          auth-service         PostgreSQL       Redis          notification-service
  |                 |                    |               |                   |
  |--- POST /auth/register ----------->|                |               |                   |
  |                 |--- Validate email format -------->|                |                   |
  |                 |--- Check email uniqueness ------->|                |                   |
  |                 |<-- Email available --------------|                |                   |
  |                 |--- Hash password (bcrypt) ------->|                |                   |
  |                 |--- INSERT user ------------------>|                |                   |
  |                 |<-- User created ------------------|                |                   |
  |                 |--- Generate email token --------->|                |                   |
  |                 |--- Cache token (TTL: 24h) ------>|                |                   |
  |                 |--- Publish user.registered ------>|--------------->|                   |
  |                 |                                   |               |--- Render template |
  |                 |                                   |               |--- Send email ---->|
  |<-- 201 Created--|                                   |               |                   |
```

### B.2 Order Creation Flow (Saga Pattern)

```
Client       cart-service    order-service    inventory-service    payment-service    notification-service
  |               |               |                  |                   |                    |
  |-- checkout -->|               |                  |                   |                    |
  |               |-- validate -->|                  |                   |                    |
  |               |               |-- reserve ------>|                   |                    |
  |               |               |<-- reserved -----|                   |                    |
  |               |               |-- create_intent ->|                  |                    |
  |               |               |<-- intent --------|                  |                    |
  |               |               |                  |                   |                    |
  |               |               |--- await payment confirmation ----->|                    |
  |               |               |                  |                   |                    |
  |               |               |<-- payment.completed ---------------|                    |
  |               |               |-- commit ------->|                   |                    |
  |               |               |<-- committed ----|                   |                    |
  |               |               |                  |                   |                    |
  |               |               |-- publish order.paid --------------->|-- send receipt --->|
  |               |               |                  |                   |                    |
  |<-- 201 -------|               |                  |                   |                    |
```

### B.3 Compensation Flow (Order Cancellation)

```
Client       order-service    inventory-service    payment-service    shipping-service    notification-service
  |               |                  |                   |                  |                    |
  |-- cancel ---->|                  |                   |                  |                    |
  |               |-- check status ->|                   |                  |                    |
  |               |-- release ------>|                   |                  |                    |
  |               |<-- released -----|                   |                  |                    |
  |               |-- refund ------->|                   |                  |                    |
  |               |<-- refunded -----|                   |                  |                    |
  |               |-- cancel_ship -->|                   |-- cancel ------->|                    |
  |               |                  |                   |<-- cancelled ----|                    |
  |               |-- publish order.cancelled ---------->|                  |-- send notif ----->|
  |<-- 200 -------|                  |                   |                  |                    |
```

### B.4 Product Search Flow

```
Client       search-service     Elasticsearch      catalog-service     analytics-service
  |               |                   |                  |                    |
  |-- GET /search?q=... ------------>|                   |                    |
  |               |-- query --------->|                   |                    |
  |               |<-- results -------|                   |                    |
  |               |                   |                   |                    |
  |               |-- enrich -------->|-- get products -->|                    |
  |               |                   |<-- product data --|                    |
  |               |<-- enriched ------|                   |                    |
  |               |                   |                   |                    |
  |               |-- track_search -->|                   |-- record event -->|
  |               |                   |                   |                    |
  |<-- 200 -------|                   |                   |                    |
```

### B.5 Review Submission and Aggregation Flow

```
Client       review-service     order-service      catalog-service     notification-service
  |               |                   |                  |                    |
  |-- POST /reviews ----------------->|                   |                    |
  |               |-- verify purchase ->|                  |                    |
  |               |<-- purchase verified|                  |                    |
  |               |-- save review ---->|                   |                    |
  |               |                   |                   |                    |
  |               |-- auto-moderate ->|                   |                    |
  |               |-- publish review.submitted ---------->|                    |
  |               |                   |                   |--- notify merchant->|
  |               |                   |                   |                    |
  |               |-- aggregate ratings ----------------->|                    |
  |               |                   |-- publish review.aggregated ---------->|
  |               |                   |                   |-- update product ->|
  |               |                   |                   |                    |
  |<-- 201 -------|                   |                   |                    |
```

---

## Appendix C: Architecture Decision Records

### ADR-001: Microservice per Domain Boundary

**Status**: Accepted
**Date**: 2024-01-15

**Context**: The MegaCommerce platform needs to support independent scaling, deployment, and
development of different business capabilities. The team expects rapid growth in transaction
volume and product catalog size.

**Decision**: Each bounded context (auth, catalog, inventory, orders, payments, shipping,
notifications, reviews, cart, search, analytics, coupons, recommendations, media) gets its
own microservice with an independent database.

**Consequences**:
- Positive: Independent scaling, technology flexibility, team autonomy
- Negative: Increased operational complexity, distributed data management
- Mitigation: Shared libraries for cross-cutting concerns, standardized observability

### ADR-002: Event-Driven Communication for Cross-Service Operations

**Status**: Accepted
**Date**: 2024-01-15

**Context**: Services need to react to changes in other services (e.g., order creation
triggers inventory reservation, payment confirmation, and notification). Direct synchronous
calls create tight coupling and cascade failures.

**Decision**: Use Redis Pub/Sub for real-time events and RabbitMQ for reliable queued events.
The saga pattern coordinates multi-step transactions. Each event includes a schema version
for backward compatibility.

**Consequences**:
- Positive: Loose coupling, resilience, temporal decoupling
- Negative: Eventual consistency, event ordering challenges, debugging complexity
- Mitigation: Correlation IDs in all events, dead-letter queues, event replay capability

### ADR-003: JWT with RS256 for Inter-Service Authentication

**Status**: Accepted
**Date**: 2024-01-20

**Context**: All services need to verify user identity and roles. Sharing database access
for session validation creates coupling and a single point of failure.

**Decision**: Use JWT tokens signed with RS256 (asymmetric). The auth-service holds the
private key and signs tokens. All other services hold only the public key and can verify
tokens independently without network calls.

**Consequences**:
- Positive: Stateless authentication, no cross-service calls for verification
- Negative: Cannot immediately revoke tokens (must wait for expiry)
- Mitigation: Short token lifetime (15 min), refresh token rotation, token blacklist in Redis

### ADR-004: Elasticsearch for Product Search

**Status**: Accepted
**Date**: 2024-01-25

**Context**: Product search requires full-text search, faceted filtering, autocomplete,
spell correction, and relevance ranking. PostgreSQL's full-text search capabilities are
insufficient for the required feature set.

**Decision**: Maintain a denormalized Elasticsearch index alongside the authoritative
PostgreSQL data store. The catalog service publishes CDC events that the search service
consumes to keep the index in sync.

**Consequences**:
- Positive: Rich search capabilities, sub-100ms search latency
- Negative: Index staleness (eventual consistency), operational overhead
- Mitigation: < 5 second sync lag target, manual reindex endpoint, dual-read during transitions

### ADR-005: Saga Pattern for Distributed Transactions

**Status**: Accepted
**Date**: 2024-02-01

**Context**: Order creation involves multiple services (inventory, payment, shipping) that
must all succeed or all compensate. Traditional distributed transactions (2PC) are
impractical in a microservices architecture.

**Decision**: Implement the choreography-based saga pattern where each service publishes
events and listens for events to coordinate. Compensation actions are defined for each step.

**Saga Steps for Order Creation**:
1. order-service creates order (status: pending_payment)
2. inventory-service reserves stock (compensation: release reservation)
3. payment-service processes payment (compensation: refund payment)
4. inventory-service commits reservation (compensation: release stock)
5. shipping-service creates shipment (compensation: cancel shipment)
6. notification-service sends confirmation (no compensation needed)

**Consequences**:
- Positive: No distributed transactions, services remain independent
- Negative: Complex error handling, eventual consistency
- Mitigation: Timeout-based reservation expiry, idempotent operations, dead-letter handling

### ADR-006: Optimistic Concurrency for Inventory Management

**Status**: Accepted
**Date**: 2024-02-05

**Context**: Multiple concurrent orders may try to reserve the same inventory. Pessimistic
locking (SELECT FOR UPDATE) causes contention under high load.

**Decision**: Use optimistic concurrency control with a version column on stock levels.
Reservation attempts check the version and retry on conflict. Database-level constraints
ensure quantity never goes negative.

**Consequences**:
- Positive: Higher throughput under normal load, no lock contention
- Negative: Retry storms under extreme contention
- Mitigation: Exponential backoff with jitter, circuit breaker, warehouse-level sharding

### ADR-007: Provider Abstraction for Payment Processing

**Status**: Accepted
**Date**: 2024-02-10

**Context**: The platform needs to support multiple payment providers (Stripe, PayPal, bank
transfers) and may add more in the future. Each provider has a different API and webhook format.

**Decision**: Implement a provider abstraction layer with a common interface. Each provider
is a pluggable adapter that translates between the internal payment model and the provider's
API. Webhook handlers are also provider-specific adapters.

**Consequences**:
- Positive: Easy to add new providers, consistent internal API
- Negative: Lowest common denominator features, adapter maintenance
- Mitigation: Feature flags for provider-specific capabilities, comprehensive adapter tests

### ADR-008: Template-Based Notification System

**Status**: Accepted
**Date**: 2024-02-15

**Context**: Notifications are sent across multiple channels (email, SMS, push, in-app) with
consistent content. Marketing and product teams need to update notification content without
code deployments.

**Decision**: Use a template-based system where notification templates are stored in the
database with variable placeholders. Templates are versioned and can be updated through the
admin API without service restarts.

**Consequences**:
- Positive: Non-technical content updates, consistent messaging
- Negative: Template debugging complexity, variable validation
- Mitigation: Template preview API, variable validation at send time, template versioning

### ADR-009: Hybrid Recommendation Engine

**Status**: Accepted
**Date**: 2024-02-20

**Context**: Product recommendations need to balance between exploiting known preferences
(collaborative filtering) and discovering new relevant products (content-based filtering).
Cold-start users and products need special handling.

**Decision**: Implement a hybrid recommendation engine that combines:
1. Collaborative filtering (user-user and item-item) for existing users
2. Content-based filtering (product attributes, categories) for cold-start
3. Popularity-based fallback for new users with no history
4. Re-ranking based on real-time signals (current session, trending)

**Consequences**:
- Positive: Handles cold-start, diverse recommendations, adaptive
- Negative: Model complexity, training cost, A/B testing infrastructure needed
- Mitigation: Incremental model updates, offline batch training, recommendation quality metrics

### ADR-010: CDN-First Media Architecture

**Status**: Accepted
**Date**: 2024-02-25

**Context**: Product images are the largest bandwidth consumer. Image processing (resize,
format conversion) must not block the upload flow. Users expect fast image loading globally.

**Decision**: Store originals in S3-compatible object storage (MinIO in dev, S3 in prod).
Generate multiple size variants asynchronously after upload. Serve all images through a CDN
with aggressive cache headers. Support modern formats (WebP, AVIF) with content negotiation.

**Consequences**:
- Positive: Fast global delivery, reduced origin load, modern formats
- Negative: Cache invalidation complexity, storage costs for variants
- Mitigation: Cache busting via version hashes, lifecycle policies for unused variants

---

## Appendix D: Data Flow Specifications

### D.1 Real-Time Inventory Update Flow

When a product's stock level changes (due to order, return, manual adjustment, or transfer),
the following data flow ensures all dependent systems are updated:

1. **Stock Change Event** originates from inventory-service
2. **Event Payload**:
   ```json
   {
     "event_id": "UUID",
     "event_type": "inventory.stock_changed",
     "timestamp": "ISO8601",
     "correlation_id": "UUID",
     "data": {
       "product_id": "UUID",
       "variant_id": "UUID",
       "warehouse_id": "UUID",
       "previous_quantity": 100,
       "new_quantity": 95,
       "change_type": "reservation",
       "reference_id": "UUID"
     }
   }
   ```
3. **Consumers**:
   - **catalog-service**: Updates in_stock flag if quantity reaches zero
   - **search-service**: Updates Elasticsearch document availability
   - **cart-service**: Validates active carts containing this product
   - **analytics-service**: Records inventory metric

### D.2 Price Change Propagation

When a product price changes in the catalog, the following systems must be updated:

1. **Price Change Event** from catalog-service
2. **Event Payload**:
   ```json
   {
     "event_id": "UUID",
     "event_type": "catalog.price_changed",
     "timestamp": "ISO8601",
     "data": {
       "product_id": "UUID",
       "old_base_price": 29.99,
       "new_base_price": 24.99,
       "old_sale_price": null,
       "new_sale_price": 19.99,
       "reason": "seasonal_promotion",
       "effective_from": "ISO8601"
     }
   }
   ```
3. **Consumers**:
   - **search-service**: Update price in search index
   - **cart-service**: Recalculate cart totals for carts containing this product
   - **recommendation-service**: Update product price for ranking
   - **analytics-service**: Record price change metric

### D.3 User Activity Tracking Pipeline

User activities are tracked from client to analytics with the following pipeline:

1. **Client-Side Events**: Page views, product impressions, clicks, add-to-cart
2. **Server-Side Events**: Order creation, payment, shipment, returns
3. **Event Collection**: POST /analytics/events (fire-and-forget, async)
4. **Event Processing Pipeline**:
   ```
   Raw Event → Validation → Enrichment → Deduplication → Storage → Aggregation
   ```
5. **Enrichment Steps**:
   - Resolve user_id from session if anonymous
   - Add geolocation from IP address
   - Add device category from user agent
   - Add product details from catalog cache
6. **Storage**: Events stored in time-partitioned PostgreSQL tables
7. **Aggregation**: Hourly and daily rollups computed via background jobs

### D.4 Abandoned Cart Recovery Flow

1. **Detection**: Background job runs every 15 minutes
2. **Criteria**: Cart with items, last updated > 1 hour ago, not checked out
3. **Recovery Pipeline**:
   ```
   Detect → Check user preferences → Apply discount → Send notification → Track conversion
   ```
4. **Notification Sequence**:
   - Hour 1: In-app notification "You left items in your cart"
   - Hour 4: Email with cart summary and product images
   - Hour 24: Email with discount offer (5% off)
   - Hour 72: Final email with urgency messaging
5. **Conversion Tracking**: If user completes checkout within 7 days of first notification,
   attributed as recovered cart

### D.5 Review Moderation Pipeline

1. **Submission**: User submits review via POST /reviews
2. **Auto-Moderation**:
   - Profanity filter (regex-based + ML classifier)
   - Spam detection (duplicate content, suspicious patterns)
   - Sentiment analysis (flag extremely negative reviews for manual review)
   - Image moderation (NSFW detection via ML)
3. **Auto-Approved**: Reviews that pass all auto-moderation checks
4. **Flagged for Review**: Reviews that fail any check go to moderation queue
5. **Manual Moderation**: Admin approves/rejects with moderation notes
6. **Post-Approval**: Trigger rating aggregation and notify merchant

### D.6 Search Index Synchronization

1. **Source of Truth**: catalog-service PostgreSQL database
2. **Change Detection**: CDC events published on product/category/brand changes
3. **Index Update Pipeline**:
   ```
   CDC Event → Transformer → Bulk Indexer → Index Refresh
   ```
4. **Transformer**: Denormalizes product data (joins category path, brand name, variant info)
5. **Bulk Indexer**: Batches updates every 2 seconds for efficiency
6. **Index Refresh**: Elasticsearch near-real-time refresh (1 second interval)
7. **Full Reindex**: Triggered manually or weekly via cron, uses scroll API
8. **Consistency Check**: Hourly job compares PostgreSQL count with ES document count

---

## Appendix E: Database Schema Details

### E.1 auth-service Schema

```sql
CREATE TABLE users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email VARCHAR(255) UNIQUE NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    name VARCHAR(100) NOT NULL,
    phone VARCHAR(20),
    avatar_url VARCHAR(512),
    role VARCHAR(20) NOT NULL DEFAULT 'customer' CHECK (role IN ('customer', 'merchant', 'admin')),
    status VARCHAR(20) NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'suspended', 'deleted')),
    email_verified BOOLEAN NOT NULL DEFAULT FALSE,
    mfa_enabled BOOLEAN NOT NULL DEFAULT FALSE,
    mfa_secret VARCHAR(255),
    failed_login_count INTEGER NOT NULL DEFAULT 0,
    locked_until TIMESTAMPTZ,
    last_login_at TIMESTAMPTZ,
    last_login_ip VARCHAR(45),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    deleted_at TIMESTAMPTZ
);

CREATE INDEX idx_users_email ON users (email) WHERE deleted_at IS NULL;
CREATE INDEX idx_users_role ON users (role) WHERE deleted_at IS NULL;
CREATE INDEX idx_users_status ON users (status) WHERE deleted_at IS NULL;

CREATE TABLE refresh_tokens (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    token_hash VARCHAR(64) UNIQUE NOT NULL,
    device_info JSONB,
    ip_address VARCHAR(45),
    expires_at TIMESTAMPTZ NOT NULL,
    revoked BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_refresh_tokens_user ON refresh_tokens (user_id) WHERE NOT revoked;
CREATE INDEX idx_refresh_tokens_expires ON refresh_tokens (expires_at) WHERE NOT revoked;

CREATE TABLE audit_logs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID REFERENCES users(id),
    action VARCHAR(50) NOT NULL,
    ip_address VARCHAR(45),
    user_agent TEXT,
    success BOOLEAN NOT NULL,
    failure_reason TEXT,
    metadata JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_audit_logs_user ON audit_logs (user_id, created_at DESC);
CREATE INDEX idx_audit_logs_action ON audit_logs (action, created_at DESC);

CREATE TABLE oauth_connections (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    provider VARCHAR(20) NOT NULL CHECK (provider IN ('google', 'github', 'facebook')),
    provider_user_id VARCHAR(255) NOT NULL,
    access_token TEXT NOT NULL,
    refresh_token TEXT,
    token_expires_at TIMESTAMPTZ,
    profile_data JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (provider, provider_user_id)
);

CREATE INDEX idx_oauth_user ON oauth_connections (user_id);
```

### E.2 catalog-service Schema

```sql
CREATE TABLE brands (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(100) UNIQUE NOT NULL,
    slug VARCHAR(120) UNIQUE NOT NULL,
    logo_url VARCHAR(512),
    description TEXT,
    website_url VARCHAR(512),
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE categories (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(100) NOT NULL,
    slug VARCHAR(120) NOT NULL,
    parent_id UUID REFERENCES categories(id),
    path VARCHAR(500) NOT NULL,
    depth INTEGER NOT NULL DEFAULT 0,
    sort_order INTEGER NOT NULL DEFAULT 0,
    image_url VARCHAR(512),
    description TEXT,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    product_count INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (parent_id, slug)
);

CREATE INDEX idx_categories_path ON categories (path);
CREATE INDEX idx_categories_parent ON categories (parent_id);

CREATE TABLE products (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    sku VARCHAR(50) UNIQUE NOT NULL,
    name VARCHAR(255) NOT NULL,
    slug VARCHAR(280) UNIQUE NOT NULL,
    description TEXT,
    short_description VARCHAR(500),
    brand_id UUID REFERENCES brands(id),
    category_id UUID NOT NULL REFERENCES categories(id),
    base_price DECIMAL(10, 2) NOT NULL CHECK (base_price >= 0),
    sale_price DECIMAL(10, 2) CHECK (sale_price >= 0),
    cost_price DECIMAL(10, 2) NOT NULL CHECK (cost_price >= 0),
    currency VARCHAR(3) NOT NULL DEFAULT 'USD',
    weight DECIMAL(10, 2),
    dimensions JSONB,
    images JSONB DEFAULT '[]',
    tags TEXT[] DEFAULT '{}',
    status VARCHAR(20) NOT NULL DEFAULT 'draft' CHECK (status IN ('draft', 'active', 'archived')),
    is_featured BOOLEAN NOT NULL DEFAULT FALSE,
    meta_title VARCHAR(70),
    meta_description VARCHAR(160),
    average_rating DECIMAL(3, 2) NOT NULL DEFAULT 0,
    review_count INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_products_category ON products (category_id) WHERE status = 'active';
CREATE INDEX idx_products_brand ON products (brand_id) WHERE status = 'active';
CREATE INDEX idx_products_price ON products (base_price) WHERE status = 'active';
CREATE INDEX idx_products_tags ON products USING GIN (tags);
CREATE INDEX idx_products_status ON products (status);

CREATE TABLE product_variants (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    product_id UUID NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    sku VARCHAR(50) UNIQUE NOT NULL,
    name VARCHAR(100) NOT NULL,
    price_modifier DECIMAL(10, 2) NOT NULL DEFAULT 0,
    weight_modifier DECIMAL(10, 2) NOT NULL DEFAULT 0,
    attributes JSONB NOT NULL DEFAULT '{}',
    image_url VARCHAR(512),
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_variants_product ON product_variants (product_id) WHERE is_active;

CREATE TABLE pricing_rules (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(100) NOT NULL,
    rule_type VARCHAR(20) NOT NULL CHECK (rule_type IN ('percentage', 'fixed', 'buy_x_get_y')),
    target_type VARCHAR(20) NOT NULL CHECK (target_type IN ('product', 'category', 'brand', 'all')),
    target_id UUID,
    discount_value DECIMAL(10, 2) NOT NULL,
    min_quantity INTEGER NOT NULL DEFAULT 1,
    max_uses INTEGER,
    starts_at TIMESTAMPTZ NOT NULL,
    ends_at TIMESTAMPTZ NOT NULL,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    priority INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_pricing_rules_active ON pricing_rules (starts_at, ends_at) WHERE is_active;
```

### E.3 inventory-service Schema

```sql
CREATE TABLE warehouse_locations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    code VARCHAR(20) UNIQUE NOT NULL,
    name VARCHAR(100) NOT NULL,
    address JSONB NOT NULL,
    timezone VARCHAR(50) NOT NULL DEFAULT 'UTC',
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    capacity INTEGER NOT NULL DEFAULT 0,
    current_utilization INTEGER NOT NULL DEFAULT 0,
    coordinates JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE stock_levels (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    product_id UUID NOT NULL,
    variant_id UUID NOT NULL,
    warehouse_id UUID NOT NULL REFERENCES warehouse_locations(id),
    quantity_on_hand INTEGER NOT NULL DEFAULT 0 CHECK (quantity_on_hand >= 0),
    quantity_reserved INTEGER NOT NULL DEFAULT 0 CHECK (quantity_reserved >= 0),
    reorder_point INTEGER NOT NULL DEFAULT 10,
    reorder_quantity INTEGER NOT NULL DEFAULT 50,
    last_counted_at TIMESTAMPTZ,
    version INTEGER NOT NULL DEFAULT 1,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (product_id, variant_id, warehouse_id),
    CHECK (quantity_reserved <= quantity_on_hand)
);

CREATE INDEX idx_stock_product ON stock_levels (product_id, variant_id);
CREATE INDEX idx_stock_warehouse ON stock_levels (warehouse_id);
CREATE INDEX idx_stock_low ON stock_levels (product_id) WHERE quantity_on_hand - quantity_reserved <= reorder_point;

CREATE TABLE stock_reservations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    order_id UUID NOT NULL,
    product_id UUID NOT NULL,
    variant_id UUID NOT NULL,
    warehouse_id UUID NOT NULL REFERENCES warehouse_locations(id),
    quantity INTEGER NOT NULL CHECK (quantity > 0),
    status VARCHAR(20) NOT NULL DEFAULT 'reserved' CHECK (status IN ('reserved', 'committed', 'released')),
    expires_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_reservations_order ON stock_reservations (order_id);
CREATE INDEX idx_reservations_expires ON stock_reservations (expires_at) WHERE status = 'reserved';

CREATE TABLE stock_movements (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    product_id UUID NOT NULL,
    variant_id UUID NOT NULL,
    from_warehouse_id UUID REFERENCES warehouse_locations(id),
    to_warehouse_id UUID REFERENCES warehouse_locations(id),
    quantity INTEGER NOT NULL CHECK (quantity > 0),
    movement_type VARCHAR(20) NOT NULL CHECK (movement_type IN ('receipt', 'shipment', 'transfer', 'adjustment', 'return')),
    reference_id UUID,
    notes TEXT,
    created_by UUID,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_movements_product ON stock_movements (product_id, created_at DESC);
CREATE INDEX idx_movements_warehouse ON stock_movements (to_warehouse_id, created_at DESC);
```

---

## Appendix F: Monitoring and Alerting Rules

### F.1 Service Health Alerts

| Alert Name                  | Condition                                | Severity | Channel    |
|-----------------------------|------------------------------------------|----------|------------|
| ServiceDown                 | Health endpoint returns non-200 for 1min | Critical | PagerDuty  |
| HighErrorRate               | Error rate > 1% for 5 minutes            | Warning  | Slack      |
| HighErrorRateCritical       | Error rate > 5% for 2 minutes            | Critical | PagerDuty  |
| HighLatency                 | P95 latency > 500ms for 5 minutes        | Warning  | Slack      |
| HighLatencyCritical         | P99 latency > 2s for 2 minutes           | Critical | PagerDuty  |
| HighCPUUsage                | CPU > 80% for 10 minutes                 | Warning  | Slack      |
| HighMemoryUsage             | Memory > 85% for 5 minutes               | Warning  | Slack      |
| DiskSpaceLow                | Disk usage > 80%                         | Warning  | Slack      |
| DatabaseConnectionPoolFull  | Available connections < 5                | Critical | PagerDuty  |
| RedisConnectionFailure      | Redis ping fails for 30 seconds          | Critical | PagerDuty  |
| ElasticsearchClusterRed     | Cluster status is red for 1 minute       | Critical | PagerDuty  |
| RabbitMQQueueBacklog        | Queue depth > 10000 for 5 minutes        | Warning  | Slack      |

### F.2 Business Metric Alerts

| Alert Name                  | Condition                                | Severity | Channel    |
|-----------------------------|------------------------------------------|----------|------------|
| OrderVolumeAnomaly          | Orders < 50% of same-hour average        | Warning  | Slack      |
| PaymentFailureSpike         | Payment failures > 10% for 5 minutes     | Critical | PagerDuty  |
| CartAbandonmentSpike        | Abandonment > 80% for 1 hour             | Warning  | Slack      |
| InventoryOutOfStock         | > 100 products out of stock              | Warning  | Slack      |
| SearchLatencyDegraded       | Search P95 > 200ms for 5 minutes         | Warning  | Slack      |
| NotificationDeliveryFailure | Email bounce rate > 5% for 1 hour        | Warning  | Slack      |
| ReviewModerationBacklog     | Pending reviews > 500                    | Info     | Slack      |

### F.3 Prometheus Metrics per Service

Every service exposes the following standard metrics at `/metrics`:

```
# Request metrics
http_requests_total{method, path, status_code}
http_request_duration_seconds{method, path, quantile}
http_request_size_bytes{method, path}
http_response_size_bytes{method, path}

# Database metrics
db_connections_active
db_connections_idle
db_query_duration_seconds{query_type}
db_query_errors_total{query_type}

# Redis metrics
redis_connections_active
redis_command_duration_seconds{command}
redis_cache_hits_total
redis_cache_misses_total

# Application-specific metrics (examples)
auth_login_attempts_total{result}
auth_token_refreshes_total
catalog_products_total{status}
inventory_stock_reservations_total{status}
orders_total{status}
payments_total{provider, status}
notifications_sent_total{channel, status}
```

---

## Appendix G: Security Specifications

### G.1 Authentication and Authorization Matrix

| Endpoint Pattern                | Auth Required | Roles Allowed           | Rate Limit          |
|--------------------------------|---------------|-------------------------|---------------------|
| POST /auth/register            | No            | Public                  | 10/hour per IP      |
| POST /auth/login               | No            | Public                  | 5/15min per email   |
| POST /auth/refresh             | No            | Public (with token)     | 30/hour per user    |
| GET /auth/me                   | Yes           | Any authenticated       | 60/min per user     |
| GET /auth/admin/*              | Yes           | admin                   | 30/min per user     |
| GET /catalog/products          | No            | Public                  | 100/min per IP      |
| POST /catalog/products         | Yes           | merchant, admin         | 30/min per user     |
| POST /inventory/reserve        | Yes           | System (internal)       | 100/min per service |
| POST /orders                   | Yes           | customer, merchant      | 10/min per user     |
| GET /orders                    | Yes           | customer, merchant      | 60/min per user     |
| GET /orders/admin              | Yes           | admin                   | 30/min per user     |
| POST /payments/create-intent   | Yes           | customer                | 5/min per user      |
| POST /payments/webhook/*       | No            | Signature verified      | 100/min per IP      |
| POST /shipping/shipments       | Yes           | merchant, admin         | 30/min per user     |
| POST /notifications/send       | Yes           | System (internal)       | 100/min per service |
| POST /notifications/broadcast  | Yes           | admin                   | 5/min per user      |
| POST /reviews                  | Yes           | customer                | 5/day per user/product |
| GET /cart                      | Optional      | Any                     | 60/min per session  |
| GET /search                    | No            | Public                  | 100/min per IP      |
| POST /analytics/events         | No            | Public                  | 1000/min per IP     |
| POST /coupons/validate         | No            | System (internal)       | 100/min per service |
| GET /recommendations/*         | Optional      | Any                     | 60/min per session  |
| POST /media/upload             | Yes           | customer, merchant, admin| 20/min per user    |
| GET /health                    | No            | Public                  | Unlimited           |

### G.2 Data Encryption Requirements

| Data Category        | At Rest           | In Transit         | Notes                              |
|----------------------|-------------------|--------------------|-------------------------------------|
| User passwords       | bcrypt (cost 12)  | HTTPS/TLS 1.3     | Never stored in plaintext           |
| Payment tokens       | AES-256-GCM       | HTTPS/TLS 1.3     | PCI DSS compliant                   |
| OAuth tokens         | AES-256-GCM       | HTTPS/TLS 1.3     | Encrypted in database               |
| MFA secrets          | AES-256-GCM       | HTTPS/TLS 1.3     | Encrypted at application level      |
| JWT private key      | File permissions   | N/A                | 600 permissions, not in env vars    |
| Database connections | SSL required       | TLS 1.2+          | Certificate verification enabled    |
| Redis connections    | AUTH + TLS         | TLS 1.2+          | Requirepass enabled in production   |
| S3 credentials       | AWS KMS            | HTTPS              | IAM roles preferred over access keys|
| API keys (Stripe)    | Vault/KMS          | HTTPS              | Never committed to source control   |

### G.3 OWASP Top 10 Mitigations

| Vulnerability          | Mitigation Strategy                                          |
|------------------------|--------------------------------------------------------------|
| A01 Broken Access Control | JWT role verification, endpoint-level RBAC, row-level security |
| A02 Cryptographic Failures | AES-256-GCM encryption, TLS 1.3, bcrypt passwords, RS256 JWTs |
| A03 Injection          | SQLAlchemy ORM (parameterized queries), input validation, Pydantic models |
| A04 Insecure Design    | Threat modeling, security architecture reviews, defense in depth |
| A05 Security Misconfiguration | Hardened Docker images, non-root users, minimal base images, security headers |
| A06 Vulnerable Components | Automated dependency scanning (Dependabot), regular updates |
| A07 Authentication     | JWT with short expiry, MFA, account lockout, rate limiting |
| A08 Software Integrity | Docker image signing, CI/CD pipeline integrity checks |
| A09 Logging & Monitoring | Structured logging, audit trails, anomaly detection alerts |
| A10 SSRF               | URL validation, allowlists for internal service calls, network policies |

---

## Appendix H: OpenAPI Contract Specifications

### H.1 auth-service OpenAPI Specification (Abbreviated)

```yaml
openapi: "3.1.0"
info:
  title: "Auth Service API"
  version: "1.0.0"
  description: "Central identity provider for MegaCommerce platform. Manages user registration, authentication, JWT issuance, RBAC, MFA, OAuth2 social login, and session management."
  contact:
    name: "MegaCommerce Backend Team"
    email: "backend@megacommerce.example.com"
  license:
    name: "Proprietary"
servers:
  - url: "http://localhost:8001"
    description: "Development"
  - url: "https://api.megacommerce.com/auth"
    description: "Production"
paths:
  /auth/register:
    post:
      operationId: "registerUser"
      summary: "Register a new user account"
      tags: ["Authentication"]
      requestBody:
        required: true
        content:
          application/json:
            schema:
              type: object
              required: ["email", "password", "name"]
              properties:
                email: { type: string, format: email, maxLength: 255 }
                password: { type: string, minLength: 8, maxLength: 128 }
                name: { type: string, minLength: 1, maxLength: 100 }
                phone: { type: string, pattern: "^\\+[1-9]\\d{1,14}$" }
                role: { type: string, enum: [customer, merchant], default: customer }
      responses:
        "201":
          description: "User registered successfully"
          content:
            application/json:
              schema: { $ref: "#/components/schemas/UserResponse" }
        "409":
          description: "Email already registered"
          content:
            application/json:
              schema: { $ref: "#/components/schemas/ErrorResponse" }
        "422":
          description: "Validation error"
          content:
            application/json:
              schema: { $ref: "#/components/schemas/ValidationError" }
  /auth/login:
    post:
      operationId: "loginUser"
      summary: "Authenticate user and issue JWT tokens"
      tags: ["Authentication"]
      requestBody:
        required: true
        content:
          application/json:
            schema:
              type: object
              required: ["email", "password"]
              properties:
                email: { type: string, format: email }
                password: { type: string }
                device_info:
                  type: object
                  properties:
                    browser: { type: string }
                    os: { type: string }
                    device_type: { type: string }
      responses:
        "200":
          description: "Login successful"
          content:
            application/json:
              schema: { $ref: "#/components/schemas/TokenResponse" }
        "401":
          description: "Invalid credentials"
          content:
            application/json:
              schema: { $ref: "#/components/schemas/ErrorResponse" }
        "423":
          description: "Account locked"
          content:
            application/json:
              schema: { $ref: "#/components/schemas/LockedResponse" }
  /auth/refresh:
    post:
      operationId: "refreshToken"
      summary: "Refresh access token using refresh token"
      tags: ["Authentication"]
      requestBody:
        required: true
        content:
          application/json:
            schema:
              type: object
              required: ["refresh_token"]
              properties:
                refresh_token: { type: string }
      responses:
        "200":
          description: "Token refreshed"
          content:
            application/json:
              schema: { $ref: "#/components/schemas/TokenResponse" }
        "401":
          description: "Invalid or expired refresh token"
  /auth/me:
    get:
      operationId: "getCurrentUser"
      summary: "Get current user profile"
      tags: ["User"]
      security: [{ BearerAuth: [] }]
      responses:
        "200":
          description: "User profile"
          content:
            application/json:
              schema: { $ref: "#/components/schemas/UserProfile" }
        "401":
          description: "Not authenticated"
    put:
      operationId: "updateCurrentUser"
      summary: "Update current user profile"
      tags: ["User"]
      security: [{ BearerAuth: [] }]
      requestBody:
        content:
          application/json:
            schema: { $ref: "#/components/schemas/UpdateUserRequest" }
      responses:
        "200":
          description: "Updated profile"
          content:
            application/json:
              schema: { $ref: "#/components/schemas/UserProfile" }
  /health:
    get:
      operationId: "healthCheck"
      summary: "Service health check"
      tags: ["Health"]
      responses:
        "200":
          description: "Service is healthy"
          content:
            application/json:
              schema: { $ref: "#/components/schemas/HealthResponse" }
components:
  securitySchemes:
    BearerAuth:
      type: http
      scheme: bearer
      bearerFormat: JWT
  schemas:
    UserResponse:
      type: object
      properties:
        id: { type: string, format: uuid }
        email: { type: string, format: email }
        name: { type: string }
        role: { type: string }
        email_verified: { type: boolean }
        created_at: { type: string, format: date-time }
    TokenResponse:
      type: object
      properties:
        access_token: { type: string }
        refresh_token: { type: string }
        token_type: { type: string, default: "bearer" }
        expires_in: { type: integer, default: 900 }
        user: { $ref: "#/components/schemas/UserResponse" }
    UserProfile:
      type: object
      properties:
        id: { type: string, format: uuid }
        email: { type: string }
        name: { type: string }
        phone: { type: string, nullable: true }
        avatar_url: { type: string, nullable: true }
        role: { type: string }
        email_verified: { type: boolean }
        mfa_enabled: { type: boolean }
        last_login_at: { type: string, format: date-time, nullable: true }
        created_at: { type: string, format: date-time }
    UpdateUserRequest:
      type: object
      properties:
        name: { type: string, maxLength: 100 }
        phone: { type: string, pattern: "^\\+[1-9]\\d{1,14}$" }
        avatar_url: { type: string, maxLength: 512 }
    ErrorResponse:
      type: object
      properties:
        detail: { type: string }
    ValidationError:
      type: object
      properties:
        detail:
          type: array
          items:
            type: object
            properties:
              loc: { type: array, items: { type: string } }
              msg: { type: string }
              type: { type: string }
    LockedResponse:
      type: object
      properties:
        detail: { type: string }
        locked_until: { type: string, format: date-time }
    HealthResponse:
      type: object
      properties:
        status: { type: string }
        version: { type: string }
        uptime_seconds: { type: integer }
```

### H.2 order-service OpenAPI Specification (Abbreviated)

```yaml
openapi: "3.1.0"
info:
  title: "Order Service API"
  version: "1.0.0"
  description: "Manages complete order lifecycle from creation through fulfillment. Coordinates with inventory, payment, and shipping services."
servers:
  - url: "http://localhost:8004"
    description: "Development"
paths:
  /orders:
    post:
      operationId: "createOrder"
      summary: "Create a new order"
      tags: ["Orders"]
      security: [{ BearerAuth: [] }]
      requestBody:
        required: true
        content:
          application/json:
            schema: { $ref: "#/components/schemas/CreateOrderRequest" }
      responses:
        "201":
          description: "Order created"
          content:
            application/json:
              schema: { $ref: "#/components/schemas/OrderResponse" }
        "401": { description: "Not authenticated" }
        "409": { description: "Stock reservation failed" }
    get:
      operationId: "listOrders"
      summary: "List orders for authenticated user"
      tags: ["Orders"]
      security: [{ BearerAuth: [] }]
      parameters:
        - name: page
          in: query
          schema: { type: integer, default: 1 }
        - name: per_page
          in: query
          schema: { type: integer, default: 20, maximum: 100 }
        - name: status
          in: query
          schema: { type: string }
        - name: from_date
          in: query
          schema: { type: string, format: date }
        - name: to_date
          in: query
          schema: { type: string, format: date }
      responses:
        "200":
          description: "Order list"
          content:
            application/json:
              schema: { $ref: "#/components/schemas/OrderListResponse" }
  /orders/{order_id}:
    get:
      operationId: "getOrder"
      summary: "Get order details"
      tags: ["Orders"]
      security: [{ BearerAuth: [] }]
      parameters:
        - name: order_id
          in: path
          required: true
          schema: { type: string, format: uuid }
      responses:
        "200":
          description: "Order details"
          content:
            application/json:
              schema: { $ref: "#/components/schemas/OrderDetailResponse" }
        "404": { description: "Order not found" }
  /orders/{order_id}/status:
    put:
      operationId: "updateOrderStatus"
      summary: "Update order status"
      tags: ["Orders"]
      security: [{ BearerAuth: [] }]
      parameters:
        - name: order_id
          in: path
          required: true
          schema: { type: string, format: uuid }
      requestBody:
        content:
          application/json:
            schema:
              type: object
              required: ["status"]
              properties:
                status: { type: string }
                reason: { type: string }
      responses:
        "200": { description: "Status updated" }
        "400": { description: "Invalid status transition" }
  /orders/{order_id}/cancel:
    post:
      operationId: "cancelOrder"
      summary: "Cancel an order"
      tags: ["Orders"]
      security: [{ BearerAuth: [] }]
      parameters:
        - name: order_id
          in: path
          required: true
          schema: { type: string, format: uuid }
      requestBody:
        content:
          application/json:
            schema:
              type: object
              required: ["reason"]
              properties:
                reason: { type: string }
      responses:
        "200": { description: "Order cancelled" }
        "400": { description: "Cannot cancel in current status" }
  /health:
    get:
      operationId: "healthCheck"
      summary: "Service health check"
      tags: ["Health"]
      responses:
        "200":
          content:
            application/json:
              schema: { $ref: "#/components/schemas/HealthResponse" }
components:
  securitySchemes:
    BearerAuth:
      type: http
      scheme: bearer
      bearerFormat: JWT
  schemas:
    CreateOrderRequest:
      type: object
      required: ["items", "shipping_address"]
      properties:
        items:
          type: array
          minItems: 1
          items:
            type: object
            required: ["product_id", "quantity"]
            properties:
              product_id: { type: string, format: uuid }
              variant_id: { type: string, format: uuid }
              quantity: { type: integer, minimum: 1 }
        shipping_address:
          type: object
          required: ["street", "city", "state", "zip", "country"]
          properties:
            street: { type: string }
            city: { type: string }
            state: { type: string }
            zip: { type: string }
            country: { type: string }
        billing_address:
          type: object
          properties:
            street: { type: string }
            city: { type: string }
            state: { type: string }
            zip: { type: string }
            country: { type: string }
        shipping_method: { type: string, default: "standard" }
        coupon_code: { type: string }
        notes: { type: string }
    OrderResponse:
      type: object
      properties:
        id: { type: string, format: uuid }
        order_number: { type: string }
        user_id: { type: string, format: uuid }
        status: { type: string }
        items: { type: array }
        subtotal: { type: number }
        tax_amount: { type: number }
        shipping_amount: { type: number }
        discount_amount: { type: number }
        total: { type: number }
        currency: { type: string }
        created_at: { type: string, format: date-time }
    OrderListResponse:
      type: object
      properties:
        items: { type: array, items: { $ref: "#/components/schemas/OrderResponse" } }
        total: { type: integer }
        page: { type: integer }
        per_page: { type: integer }
    OrderDetailResponse:
      allOf:
        - $ref: "#/components/schemas/OrderResponse"
        - type: object
          properties:
            shipping_address: { type: object }
            billing_address: { type: object }
            payment_id: { type: string, format: uuid }
            tracking_number: { type: string }
            status_history:
              type: array
              items:
                type: object
                properties:
                  from_status: { type: string }
                  to_status: { type: string }
                  changed_by: { type: string }
                  created_at: { type: string, format: date-time }
    HealthResponse:
      type: object
      properties:
        status: { type: string }
        version: { type: string }
```

### H.3 inventory-service OpenAPI Specification (Abbreviated)

```yaml
openapi: "3.1.0"
info:
  title: "Inventory Service API"
  version: "1.0.0"
  description: "Real-time stock tracking across multiple warehouse locations with reservations, transfers, and audit trails."
servers:
  - url: "http://localhost:8003"
paths:
  /inventory/stock/{product_id}:
    get:
      operationId: "getStockLevels"
      summary: "Get stock levels for a product across all warehouses"
      tags: ["Stock"]
      parameters:
        - name: product_id
          in: path
          required: true
          schema: { type: string, format: uuid }
      responses:
        "200":
          content:
            application/json:
              schema: { $ref: "#/components/schemas/StockResponse" }
        "404": { description: "Product not found in inventory" }
  /inventory/reserve:
    post:
      operationId: "createReservation"
      summary: "Reserve stock for checkout"
      tags: ["Reservations"]
      requestBody:
        required: true
        content:
          application/json:
            schema: { $ref: "#/components/schemas/ReservationRequest" }
      responses:
        "201":
          content:
            application/json:
              schema: { $ref: "#/components/schemas/ReservationResponse" }
        "409": { description: "Insufficient stock" }
  /inventory/commit:
    post:
      operationId: "commitReservation"
      summary: "Commit a reservation (order confirmed)"
      tags: ["Reservations"]
      requestBody:
        content:
          application/json:
            schema:
              type: object
              required: ["reservation_id"]
              properties:
                reservation_id: { type: string, format: uuid }
      responses:
        "200": { description: "Committed" }
        "404": { description: "Reservation not found" }
        "410": { description: "Reservation expired" }
  /inventory/release:
    post:
      operationId: "releaseReservation"
      summary: "Release a reservation"
      tags: ["Reservations"]
      requestBody:
        content:
          application/json:
            schema:
              type: object
              required: ["reservation_id"]
              properties:
                reservation_id: { type: string, format: uuid }
      responses:
        "200": { description: "Released" }
  /inventory/adjust:
    post:
      operationId: "adjustStock"
      summary: "Manual stock adjustment (admin only)"
      tags: ["Stock"]
      security: [{ BearerAuth: [] }]
      requestBody:
        content:
          application/json:
            schema: { $ref: "#/components/schemas/AdjustmentRequest" }
      responses:
        "200": { description: "Adjusted" }
        "403": { description: "Admin required" }
  /health:
    get:
      operationId: "healthCheck"
      tags: ["Health"]
      responses:
        "200":
          content:
            application/json:
              schema: { $ref: "#/components/schemas/HealthResponse" }
components:
  securitySchemes:
    BearerAuth:
      type: http
      scheme: bearer
      bearerFormat: JWT
  schemas:
    StockResponse:
      type: object
      properties:
        product_id: { type: string, format: uuid }
        total_available: { type: integer }
        warehouses:
          type: array
          items:
            type: object
            properties:
              warehouse_id: { type: string, format: uuid }
              warehouse_code: { type: string }
              quantity_on_hand: { type: integer }
              quantity_reserved: { type: integer }
              quantity_available: { type: integer }
              reorder_point: { type: integer }
    ReservationRequest:
      type: object
      required: ["order_id", "items"]
      properties:
        order_id: { type: string, format: uuid }
        items:
          type: array
          items:
            type: object
            required: ["product_id", "variant_id", "quantity"]
            properties:
              product_id: { type: string, format: uuid }
              variant_id: { type: string, format: uuid }
              quantity: { type: integer, minimum: 1 }
              preferred_warehouse_id: { type: string, format: uuid }
    ReservationResponse:
      type: object
      properties:
        reservation_id: { type: string, format: uuid }
        items:
          type: array
          items:
            type: object
            properties:
              product_id: { type: string, format: uuid }
              variant_id: { type: string, format: uuid }
              warehouse_id: { type: string, format: uuid }
              quantity: { type: integer }
              status: { type: string }
              expires_at: { type: string, format: date-time }
    AdjustmentRequest:
      type: object
      required: ["product_id", "variant_id", "warehouse_id", "adjustment", "reason"]
      properties:
        product_id: { type: string, format: uuid }
        variant_id: { type: string, format: uuid }
        warehouse_id: { type: string, format: uuid }
        adjustment: { type: integer }
        reason: { type: string }
    HealthResponse:
      type: object
      properties:
        status: { type: string }
        version: { type: string }
```

---

## Appendix I: Load Testing Specifications

### I.1 k6 Load Test Scenarios

#### Scenario 1: Browsing Load (Baseline)

Simulates typical browsing traffic with product search and catalog navigation.

| Stage        | Duration | Virtual Users | Requests/sec (target) |
|-------------|----------|---------------|----------------------|
| Ramp up     | 2 min    | 0 -> 500      | 0 -> 2500           |
| Steady      | 10 min   | 500           | 2500                |
| Spike       | 1 min    | 500 -> 2000   | 2500 -> 10000       |
| Recovery    | 2 min    | 2000 -> 500   | 10000 -> 2500       |
| Cool down   | 2 min    | 500 -> 0      | 2500 -> 0           |

**Request Mix**:
- 40% GET /catalog/products (browse)
- 25% GET /search?q=... (search)
- 15% GET /catalog/products/{id} (product detail)
- 10% GET /recommendations/products/{id} (similar products)
- 5% GET /reviews/product/{id} (reviews)
- 5% GET /search/autocomplete (autocomplete)

**Success Criteria**:
- P95 latency < 200ms for all GET endpoints
- Error rate < 0.1%
- Zero 5xx responses during steady state

#### Scenario 2: Shopping Flow (Peak)

Simulates peak shopping activity including cart operations and checkout.

| Stage        | Duration | Virtual Users | Orders/min (target)  |
|-------------|----------|---------------|---------------------|
| Ramp up     | 3 min    | 0 -> 1000     | 0 -> 500            |
| Steady      | 15 min   | 1000          | 500                 |
| Flash sale  | 5 min    | 1000 -> 5000  | 500 -> 2000         |
| Recovery    | 5 min    | 5000 -> 1000  | 2000 -> 500         |
| Cool down   | 2 min    | 1000 -> 0     | 500 -> 0            |

**Request Mix**:
- 20% GET /cart (view cart)
- 15% POST /cart/items (add to cart)
- 10% PUT /cart/items/{id} (update quantity)
- 5% DELETE /cart/items/{id} (remove item)
- 5% POST /cart/coupon (apply coupon)
- 15% POST /cart/checkout (checkout)
- 10% POST /payments/create-intent (create payment)
- 10% POST /payments/{id}/capture (capture payment)
- 5% GET /orders/{id} (check order status)
- 5% POST /inventory/reserve (stock reservation)

**Success Criteria**:
- P95 latency < 500ms for write endpoints
- P95 latency < 200ms for read endpoints
- Order creation success rate > 99.5%
- Payment success rate > 99.9%

### I.2 Performance Budgets per Service

| Service              | P50 (ms) | P95 (ms) | P99 (ms) | Max (ms) | RPS Target |
|---------------------|----------|----------|----------|----------|-----------|
| auth-service        | 20       | 100      | 250      | 1000     | 500       |
| catalog-service     | 30       | 150      | 300      | 1000     | 2000      |
| inventory-service   | 10       | 50       | 100      | 500      | 1000      |
| order-service       | 50       | 200      | 500      | 2000     | 500       |
| payment-service     | 100      | 300      | 800      | 3000     | 200       |
| shipping-service    | 50       | 200      | 500      | 2000     | 200       |
| notification-service| 20       | 100      | 200      | 1000     | 1000      |
| review-service      | 30       | 100      | 200      | 1000     | 500       |
| cart-service        | 20       | 80       | 150      | 500      | 1000      |
| search-service      | 20       | 80       | 150      | 500      | 3000      |
| analytics-service   | 30       | 150      | 300      | 1000     | 5000      |
| coupon-service      | 10       | 50       | 100      | 500      | 500       |
| recommendation-svc  | 50       | 200      | 400      | 1000     | 500       |
| media-service       | 100      | 500      | 1000     | 5000     | 100       |

### I.3 Disaster Recovery Specifications

| Metric                 | Target                                                      |
|-----------------------|-------------------------------------------------------------|
| RTO (Recovery Time)   | < 15 minutes for any single service failure                 |
| RPO (Recovery Point)  | < 1 minute data loss for transaction services               |
| Failover time         | < 30 seconds for database failover                          |
| Backup frequency      | Every 6 hours for databases, daily for media                |
| Backup retention      | 30 days for databases, 90 days for media                    |

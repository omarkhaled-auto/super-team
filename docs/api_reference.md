# Super Agent Team Platform -- API Reference

This document is the authoritative reference for every HTTP endpoint exposed by the three core services of the Super Agent Team platform.

| Service              | Base URL                  | Default Port |
|----------------------|---------------------------|--------------|
| Architect            | `http://localhost:8001`   | 8001         |
| Contract Engine      | `http://localhost:8002`   | 8002         |
| Codebase Intelligence| `http://localhost:8003`   | 8003         |

---

## Table of Contents

- [Common Error Responses](#common-error-responses)
- [Architect Service (port 8001)](#architect-service)
  - [GET /api/health](#architect--get-apihealth)
  - [POST /api/decompose](#architect--post-apidecompose)
  - [GET /api/service-map](#architect--get-apiservice-map)
  - [GET /api/domain-model](#architect--get-apidomain-model)
- [Contract Engine Service (port 8002)](#contract-engine-service)
  - [GET /api/health](#contract-engine--get-apihealth)
  - [POST /api/contracts](#contract-engine--post-apicontracts)
  - [GET /api/contracts](#contract-engine--get-apicontracts)
  - [GET /api/contracts/{contract_id}](#contract-engine--get-apicontractscontract_id)
  - [DELETE /api/contracts/{contract_id}](#contract-engine--delete-apicontractscontract_id)
  - [POST /api/validate](#contract-engine--post-apivalidate)
  - [POST /api/breaking-changes/{contract_id}](#contract-engine--post-apibreaking-changescontract_id)
  - [POST /api/implementations/mark](#contract-engine--post-apiimplementationsmark)
  - [GET /api/implementations/unimplemented](#contract-engine--get-apiimplementationsunimplemented)
  - [POST /api/tests/generate/{contract_id}](#contract-engine--post-apitestsgeneratecontract_id)
  - [GET /api/tests/{contract_id}](#contract-engine--get-apitestscontract_id)
  - [POST /api/compliance/check/{contract_id}](#contract-engine--post-apicompliancecheckcontract_id)
- [Codebase Intelligence Service (port 8003)](#codebase-intelligence-service)
  - [GET /api/health](#codebase-intelligence--get-apihealth)
  - [GET /api/symbols](#codebase-intelligence--get-apisymbols)
  - [GET /api/dependencies](#codebase-intelligence--get-apidependencies)
  - [GET /api/graph/analysis](#codebase-intelligence--get-apigraphanalysis)
  - [POST /api/search](#codebase-intelligence--post-apisearch)
  - [POST /api/artifacts](#codebase-intelligence--post-apiartifacts)
  - [GET /api/dead-code](#codebase-intelligence--get-apidead-code)

---

## Common Error Responses

All three services use a consistent error envelope. Every error response body has the shape:

```json
{
  "detail": "<human-readable error message>"
}
```

| HTTP Status | Error Name                  | Applicable Services       |
|-------------|-----------------------------|---------------------------|
| 400         | ParsingError                | All                       |
| 404         | NotFoundError               | All                       |
| 404         | ContractNotFoundError       | Contract Engine            |
| 409         | ConflictError               | All                       |
| 409         | ImmutabilityViolationError  | All                       |
| 413         | Payload Too Large           | Contract Engine only       |
| 422         | ValidationError             | All                       |
| 422         | SchemaError                 | All                       |
| 500         | AppError (base)             | All                       |

---

## Architect Service

**Base URL:** `http://localhost:8001`

The Architect Service decomposes Product Requirements Documents (PRDs) into service maps, domain models, contract stubs, and validation artifacts.

---

### Architect -- GET /api/health

Returns the current health status of the Architect service.

| Property | Value            |
|----------|------------------|
| Method   | `GET`            |
| Path     | `/api/health`    |
| Auth     | None             |

#### Parameters

None.

#### Response

**Status 200 OK**

| Field            | Type   | Description                                      |
|------------------|--------|--------------------------------------------------|
| `status`         | string | `"healthy"`, `"degraded"`, or `"unhealthy"`      |
| `service_name`   | string | Always `"architect"`                             |
| `version`        | string | Always `"1.0.0"`                                 |
| `database`       | string | `"connected"` or `"disconnected"`                |
| `uptime_seconds` | float  | Seconds since the service started                |
| `details`        | object | Additional diagnostic information                |

```json
{
  "status": "healthy",
  "service_name": "architect",
  "version": "1.0.0",
  "database": "connected",
  "uptime_seconds": 3621.47,
  "details": {}
}
```

#### curl Example

```bash
curl -s http://localhost:8001/api/health | python -m json.tool
```

---

### Architect -- POST /api/decompose

Accepts raw PRD text and returns a full decomposition: service map, domain model, contract stubs, validation issues, and interview questions.

| Property | Value             |
|----------|-------------------|
| Method   | `POST`            |
| Path     | `/api/decompose`  |
| Auth     | None              |

#### Request Body

`Content-Type: application/json`

| Field      | Type   | Required | Constraints                          | Description                  |
|------------|--------|----------|--------------------------------------|------------------------------|
| `prd_text` | string | Yes      | Min 10 characters, max 1,048,576 characters | The raw PRD text to decompose |

```json
{
  "prd_text": "The system shall provide a user authentication service that supports OAuth 2.0 and JWT tokens..."
}
```

#### Response

**Status 201 Created**

| Field                 | Type           | Description                                                |
|-----------------------|----------------|------------------------------------------------------------|
| `service_map`         | ServiceMap     | Decomposed service topology                                |
| `domain_model`        | DomainModel    | Entity and relationship model extracted from the PRD       |
| `contract_stubs`      | list[dict]     | Preliminary API contract stubs for each identified service |
| `validation_issues`   | list[string]   | Warnings or issues found during decomposition              |
| `interview_questions` | list[string]   | Clarifying questions for ambiguous requirements            |

```json
{
  "service_map": {
    "project_name": "auth-platform",
    "services": [
      {
        "name": "auth-service",
        "description": "Handles authentication and token management",
        "endpoints": ["/login", "/token/refresh"]
      }
    ],
    "generated_at": "2026-02-16T12:00:00Z",
    "prd_hash": "a1b2c3d4e5f6",
    "build_cycle_id": "cycle-001"
  },
  "domain_model": {
    "entities": [
      {
        "name": "User",
        "attributes": ["id", "email", "password_hash"],
        "description": "A registered platform user"
      }
    ],
    "relationships": [
      {
        "source": "User",
        "target": "Session",
        "type": "one-to-many"
      }
    ],
    "generated_at": "2026-02-16T12:00:00Z"
  },
  "contract_stubs": [
    {
      "service": "auth-service",
      "type": "openapi",
      "paths": {
        "/login": { "post": {} },
        "/token/refresh": { "post": {} }
      }
    }
  ],
  "validation_issues": [
    "No rate-limiting strategy specified in the PRD"
  ],
  "interview_questions": [
    "Should the auth service support multi-factor authentication?"
  ]
}
```

#### Error Responses

| Status | Condition                                         |
|--------|---------------------------------------------------|
| 422    | `prd_text` missing, shorter than 10 chars, or exceeds 1,048,576 chars |

#### curl Example

```bash
curl -s -X POST http://localhost:8001/api/decompose \
  -H "Content-Type: application/json" \
  -d '{
    "prd_text": "The platform shall provide a user authentication service with OAuth 2.0, a product catalog service, and an order management service..."
  }' | python -m json.tool
```

---

### Architect -- GET /api/service-map

Retrieves the most recently generated service map, optionally filtered by project name.

| Property | Value              |
|----------|--------------------|
| Method   | `GET`              |
| Path     | `/api/service-map` |
| Auth     | None               |

#### Query Parameters

| Parameter      | Type   | Required | Default | Description                           |
|----------------|--------|----------|---------|---------------------------------------|
| `project_name` | string | No       | None    | Filter the service map by project name |

#### Response

**Status 200 OK**

Returns a `ServiceMap` object:

| Field            | Type                   | Description                            |
|------------------|------------------------|----------------------------------------|
| `project_name`   | string                 | Name of the project                    |
| `services`       | list[ServiceDefinition]| List of decomposed service definitions |
| `generated_at`   | string (ISO 8601)      | Timestamp of generation                |
| `prd_hash`       | string                 | Hash of the source PRD                 |
| `build_cycle_id` | string                 | Identifier for the build cycle         |

```json
{
  "project_name": "auth-platform",
  "services": [
    {
      "name": "auth-service",
      "description": "Handles authentication and token management",
      "endpoints": ["/login", "/token/refresh"]
    }
  ],
  "generated_at": "2026-02-16T12:00:00Z",
  "prd_hash": "a1b2c3d4e5f6",
  "build_cycle_id": "cycle-001"
}
```

#### Error Responses

| Status | Condition                      |
|--------|--------------------------------|
| 404    | No service map found           |

#### curl Examples

```bash
# Retrieve the current service map
curl -s http://localhost:8001/api/service-map | python -m json.tool

# Filter by project name
curl -s "http://localhost:8001/api/service-map?project_name=auth-platform" | python -m json.tool
```

---

### Architect -- GET /api/domain-model

Retrieves the most recently generated domain model, optionally filtered by project name.

| Property | Value                |
|----------|----------------------|
| Method   | `GET`                |
| Path     | `/api/domain-model`  |
| Auth     | None                 |

#### Query Parameters

| Parameter      | Type   | Required | Default | Description                             |
|----------------|--------|----------|---------|-----------------------------------------|
| `project_name` | string | No       | None    | Filter the domain model by project name |

#### Response

**Status 200 OK**

Returns a `DomainModel` object:

| Field           | Type                      | Description                          |
|-----------------|---------------------------|--------------------------------------|
| `entities`      | list[DomainEntity]        | Domain entities extracted from PRD   |
| `relationships` | list[DomainRelationship]  | Relationships between entities       |
| `generated_at`  | string (ISO 8601)         | Timestamp of generation              |

```json
{
  "entities": [
    {
      "name": "User",
      "attributes": ["id", "email", "password_hash"],
      "description": "A registered platform user"
    },
    {
      "name": "Session",
      "attributes": ["id", "user_id", "token", "expires_at"],
      "description": "An active authentication session"
    }
  ],
  "relationships": [
    {
      "source": "User",
      "target": "Session",
      "type": "one-to-many"
    }
  ],
  "generated_at": "2026-02-16T12:00:00Z"
}
```

#### Error Responses

| Status | Condition                      |
|--------|--------------------------------|
| 404    | No domain model found          |

#### curl Examples

```bash
# Retrieve the current domain model
curl -s http://localhost:8001/api/domain-model | python -m json.tool

# Filter by project name
curl -s "http://localhost:8001/api/domain-model?project_name=auth-platform" | python -m json.tool
```

---

## Contract Engine Service

**Base URL:** `http://localhost:8002`

The Contract Engine Service manages API contracts (OpenAPI, AsyncAPI, JSON Schema), validates them, detects breaking changes, tracks implementations, generates test suites, and checks compliance.

---

### Contract Engine -- GET /api/health

Returns the current health status of the Contract Engine service.

| Property | Value            |
|----------|------------------|
| Method   | `GET`            |
| Path     | `/api/health`    |
| Auth     | None             |

#### Parameters

None.

#### Response

**Status 200 OK**

| Field            | Type   | Description                                      |
|------------------|--------|--------------------------------------------------|
| `status`         | string | `"healthy"`, `"degraded"`, or `"unhealthy"`      |
| `service_name`   | string | Always `"contract-engine"`                       |
| `version`        | string | Always `"1.0.0"`                                 |
| `database`       | string | `"connected"` or `"disconnected"`                |
| `uptime_seconds` | float  | Seconds since the service started                |
| `details`        | object | Additional diagnostic information                |

```json
{
  "status": "healthy",
  "service_name": "contract-engine",
  "version": "1.0.0",
  "database": "connected",
  "uptime_seconds": 7842.12,
  "details": {}
}
```

#### curl Example

```bash
curl -s http://localhost:8002/api/health | python -m json.tool
```

---

### Contract Engine -- POST /api/contracts

Creates a new contract entry. The spec is validated before storage (OpenAPI and AsyncAPI specs are structurally validated).

| Property    | Value             |
|-------------|-------------------|
| Method      | `POST`            |
| Path        | `/api/contracts`  |
| Auth        | None              |
| Max Payload | 5 MB              |

#### Request Body

`Content-Type: application/json`

| Field            | Type        | Required | Constraints                                       | Description                          |
|------------------|-------------|----------|---------------------------------------------------|--------------------------------------|
| `service_name`   | string      | Yes      | Max 100 characters                                | Name of the service this contract belongs to |
| `type`           | string      | Yes      | One of: `"openapi"`, `"asyncapi"`, `"json_schema"`| Contract specification type          |
| `version`        | string      | Yes      | Semver pattern: `^\d+\.\d+\.\d+$`                 | Semantic version of the contract     |
| `spec`           | dict        | Yes      | Must be a valid spec for the given type            | The full contract specification      |
| `build_cycle_id` | string/null | No       | None                                               | Optional build cycle identifier      |

```json
{
  "service_name": "auth-service",
  "type": "openapi",
  "version": "1.0.0",
  "spec": {
    "openapi": "3.0.3",
    "info": {
      "title": "Auth Service API",
      "version": "1.0.0"
    },
    "paths": {
      "/login": {
        "post": {
          "summary": "User login",
          "responses": {
            "200": {
              "description": "Successful login"
            }
          }
        }
      }
    }
  },
  "build_cycle_id": "cycle-001"
}
```

#### Response

**Status 201 Created**

Returns a `ContractEntry` object:

| Field            | Type              | Description                                   |
|------------------|-------------------|-----------------------------------------------|
| `id`             | string (UUID)     | Unique identifier for the contract             |
| `type`           | string            | `"openapi"`, `"asyncapi"`, or `"json_schema"` |
| `version`        | string            | Semantic version                               |
| `service_name`   | string            | Owning service name                            |
| `spec`           | dict              | The full contract specification                |
| `spec_hash`      | string            | Hash of the spec for change detection          |
| `status`         | string            | Current status of the contract                 |
| `build_cycle_id` | string/null       | Build cycle identifier                         |
| `created_at`     | string (ISO 8601) | Creation timestamp                             |
| `updated_at`     | string (ISO 8601) | Last update timestamp                          |

```json
{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "type": "openapi",
  "version": "1.0.0",
  "service_name": "auth-service",
  "spec": { "..." : "..." },
  "spec_hash": "sha256:abc123...",
  "status": "draft",
  "build_cycle_id": "cycle-001",
  "created_at": "2026-02-16T12:00:00Z",
  "updated_at": "2026-02-16T12:00:00Z"
}
```

> **Note:** Newly created contracts are stored with status `"draft"`. Status can be `"active"`, `"deprecated"`, or `"draft"`.

#### Error Responses

| Status | Condition                                                |
|--------|----------------------------------------------------------|
| 413    | Request payload exceeds 5 MB                             |
| 422    | Invalid `version` format, invalid `type`, or spec validation failure |

#### curl Example

```bash
curl -s -X POST http://localhost:8002/api/contracts \
  -H "Content-Type: application/json" \
  -d '{
    "service_name": "auth-service",
    "type": "openapi",
    "version": "1.0.0",
    "spec": {
      "openapi": "3.0.3",
      "info": { "title": "Auth Service API", "version": "1.0.0" },
      "paths": {}
    },
    "build_cycle_id": null
  }' | python -m json.tool
```

---

### Contract Engine -- GET /api/contracts

Lists contract entries with pagination and optional filtering.

| Property | Value             |
|----------|-------------------|
| Method   | `GET`             |
| Path     | `/api/contracts`  |
| Auth     | None              |

#### Query Parameters

| Parameter      | Type   | Required | Default | Constraints       | Description                       |
|----------------|--------|----------|---------|-------------------|-----------------------------------|
| `page`         | int    | No       | 1       | >= 1              | Page number                       |
| `page_size`    | int    | No       | 20      | >= 1, <= 100      | Number of items per page          |
| `service_name` | string | No       | None    |                   | Filter by service name            |
| `type`         | string | No       | None    |                   | Filter by contract type           |
| `status`       | string | No       | None    |                   | Filter by contract status         |

#### Response

**Status 200 OK**

| Field       | Type                | Description                     |
|-------------|---------------------|---------------------------------|
| `items`     | list[ContractEntry] | List of contract entries        |
| `total`     | int                 | Total number of matching entries|
| `page`      | int                 | Current page number             |
| `page_size` | int                 | Items per page                  |

```json
{
  "items": [
    {
      "id": "550e8400-e29b-41d4-a716-446655440000",
      "type": "openapi",
      "version": "1.0.0",
      "service_name": "auth-service",
      "spec": { "..." : "..." },
      "spec_hash": "sha256:abc123...",
      "status": "active",
      "build_cycle_id": "cycle-001",
      "created_at": "2026-02-16T12:00:00Z",
      "updated_at": "2026-02-16T12:00:00Z"
    }
  ],
  "total": 1,
  "page": 1,
  "page_size": 20
}
```

#### curl Examples

```bash
# List all contracts (default pagination)
curl -s http://localhost:8002/api/contracts | python -m json.tool

# Page 2 with 10 items per page
curl -s "http://localhost:8002/api/contracts?page=2&page_size=10" | python -m json.tool

# Filter by service name
curl -s "http://localhost:8002/api/contracts?service_name=auth-service" | python -m json.tool

# Filter by type and status
curl -s "http://localhost:8002/api/contracts?type=openapi&status=active" | python -m json.tool

# Combine all filters
curl -s "http://localhost:8002/api/contracts?service_name=auth-service&type=openapi&status=active&page=1&page_size=50" \
  | python -m json.tool
```

---

### Contract Engine -- GET /api/contracts/{contract_id}

Retrieves a single contract by its UUID.

| Property | Value                           |
|----------|---------------------------------|
| Method   | `GET`                           |
| Path     | `/api/contracts/{contract_id}`  |
| Auth     | None                            |

#### Path Parameters

| Parameter     | Type          | Required | Description                  |
|---------------|---------------|----------|------------------------------|
| `contract_id` | string (UUID) | Yes      | The unique contract identifier |

#### Response

**Status 200 OK**

Returns a single `ContractEntry` object (same schema as in [POST /api/contracts](#contract-engine--post-apicontracts) response).

```json
{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "type": "openapi",
  "version": "1.0.0",
  "service_name": "auth-service",
  "spec": { "..." : "..." },
  "spec_hash": "sha256:abc123...",
  "status": "active",
  "build_cycle_id": "cycle-001",
  "created_at": "2026-02-16T12:00:00Z",
  "updated_at": "2026-02-16T12:00:00Z"
}
```

#### Error Responses

| Status | Condition                     |
|--------|-------------------------------|
| 404    | Contract with given ID not found |

#### curl Example

```bash
curl -s http://localhost:8002/api/contracts/550e8400-e29b-41d4-a716-446655440000 \
  | python -m json.tool
```

---

### Contract Engine -- DELETE /api/contracts/{contract_id}

Deletes a contract by its UUID.

| Property | Value                           |
|----------|---------------------------------|
| Method   | `DELETE`                        |
| Path     | `/api/contracts/{contract_id}`  |
| Auth     | None                            |

#### Path Parameters

| Parameter     | Type          | Required | Description                  |
|---------------|---------------|----------|------------------------------|
| `contract_id` | string (UUID) | Yes      | The unique contract identifier |

#### Response

**Status 204 No Content**

No response body is returned on successful deletion.

#### Error Responses

| Status | Condition                     |
|--------|-------------------------------|
| 404    | Contract with given ID not found |

#### curl Example

```bash
curl -s -X DELETE http://localhost:8002/api/contracts/550e8400-e29b-41d4-a716-446655440000 \
  -w "\nHTTP Status: %{http_code}\n"
```

---

### Contract Engine -- POST /api/validate

Validates a specification without storing it. Useful for dry-run validation before creating a contract.

| Property | Value             |
|----------|-------------------|
| Method   | `POST`            |
| Path     | `/api/validate`   |
| Auth     | None              |

#### Request Body

`Content-Type: application/json`

| Field  | Type   | Required | Constraints                                          | Description                     |
|--------|--------|----------|------------------------------------------------------|---------------------------------|
| `spec` | dict   | Yes      | Must be a valid specification object                 | The specification to validate   |
| `type` | string | Yes      | One of: `"openapi"`, `"asyncapi"`, `"json_schema"`   | The specification type          |

```json
{
  "spec": {
    "openapi": "3.0.3",
    "info": { "title": "My API", "version": "1.0.0" },
    "paths": {}
  },
  "type": "openapi"
}
```

#### Response

**Status 200 OK**

| Field      | Type          | Description                                |
|------------|---------------|--------------------------------------------|
| `valid`    | bool          | Whether the spec passes validation         |
| `errors`   | list[string]  | List of validation error messages          |
| `warnings` | list[string]  | List of non-blocking validation warnings   |

```json
{
  "valid": true,
  "errors": [],
  "warnings": [
    "No security schemes defined"
  ]
}
```

#### curl Example

```bash
curl -s -X POST http://localhost:8002/api/validate \
  -H "Content-Type: application/json" \
  -d '{
    "spec": {
      "openapi": "3.0.3",
      "info": { "title": "My API", "version": "1.0.0" },
      "paths": {}
    },
    "type": "openapi"
  }' | python -m json.tool
```

---

### Contract Engine -- POST /api/breaking-changes/{contract_id}

Detects breaking changes for a given contract. If a `new_spec` is provided in the request body, the current contract spec is compared against it. Otherwise, the current version is compared with the previous version of the same contract.

| Property | Value                                    |
|----------|------------------------------------------|
| Method   | `POST`                                   |
| Path     | `/api/breaking-changes/{contract_id}`    |
| Auth     | None                                     |

#### Path Parameters

| Parameter     | Type          | Required | Description                  |
|---------------|---------------|----------|------------------------------|
| `contract_id` | string (UUID) | Yes      | The unique contract identifier |

#### Request Body (Optional)

`Content-Type: application/json`

| Field      | Type | Required | Description                                                        |
|------------|------|----------|--------------------------------------------------------------------|
| `new_spec` | dict | No       | A new spec to compare against the current contract's spec          |

```json
{
  "new_spec": {
    "openapi": "3.0.3",
    "info": { "title": "Auth Service API", "version": "2.0.0" },
    "paths": {
      "/login": {
        "post": {
          "summary": "User login (updated)",
          "responses": {
            "200": { "description": "Success" }
          }
        }
      }
    }
  }
}
```

#### Response

**Status 200 OK**

Returns a list of `BreakingChange` objects:

| Field                | Type         | Description                                          |
|----------------------|--------------|------------------------------------------------------|
| `change_type`        | string       | The category of the breaking change                  |
| `path`               | string       | JSON path or endpoint path where the change occurred |
| `old_value`          | string/null  | The value before the change                          |
| `new_value`          | string/null  | The value after the change                           |
| `severity`           | string       | One of: `"error"`, `"warning"`, `"info"`             |
| `affected_consumers` | list[string] | List of consumers affected by this change            |

```json
[
  {
    "change_type": "endpoint_removed",
    "path": "/token/refresh",
    "old_value": "{\"post\": {\"summary\": \"Refresh token\"}}",
    "new_value": null,
    "severity": "error",
    "affected_consumers": ["auth-client", "mobile-app"]
  },
  {
    "change_type": "field_type_changed",
    "path": "/login.post.responses.200.schema.properties.token",
    "old_value": "string",
    "new_value": "object",
    "severity": "warning",
    "affected_consumers": []
  }
]
```

#### Error Responses

| Status | Condition                     |
|--------|-------------------------------|
| 404    | Contract with given ID not found |

#### curl Examples

```bash
# Compare with previous version (no body)
curl -s -X POST http://localhost:8002/api/breaking-changes/550e8400-e29b-41d4-a716-446655440000 \
  -H "Content-Type: application/json" \
  | python -m json.tool

# Compare with a new spec
curl -s -X POST http://localhost:8002/api/breaking-changes/550e8400-e29b-41d4-a716-446655440000 \
  -H "Content-Type: application/json" \
  -d '{
    "new_spec": {
      "openapi": "3.0.3",
      "info": { "title": "Auth Service API", "version": "2.0.0" },
      "paths": {}
    }
  }' | python -m json.tool
```

---

### Contract Engine -- POST /api/implementations/mark

Marks a contract as implemented by a specific service, providing evidence of the implementation.

| Property | Value                          |
|----------|--------------------------------|
| Method   | `POST`                         |
| Path     | `/api/implementations/mark`    |
| Auth     | None                           |

#### Request Body

`Content-Type: application/json`

| Field           | Type   | Required | Description                                             |
|-----------------|--------|----------|---------------------------------------------------------|
| `contract_id`   | string | Yes      | UUID of the contract being implemented                  |
| `service_name`  | string | Yes      | Name of the service that implemented the contract       |
| `evidence_path` | string | Yes      | File path or URL pointing to the implementation evidence|

```json
{
  "contract_id": "550e8400-e29b-41d4-a716-446655440000",
  "service_name": "auth-service",
  "evidence_path": "src/auth_service/routes.py"
}
```

#### Response

**Status 200 OK**

| Field                   | Type | Description                                                  |
|-------------------------|------|--------------------------------------------------------------|
| `marked`                | bool | Whether the marking was successful                           |
| `total_implementations` | int  | Total number of implementations recorded for this contract   |
| `all_implemented`       | bool | Whether all expected services have implemented this contract |

```json
{
  "marked": true,
  "total_implementations": 1,
  "all_implemented": false
}
```

#### curl Example

```bash
curl -s -X POST http://localhost:8002/api/implementations/mark \
  -H "Content-Type: application/json" \
  -d '{
    "contract_id": "550e8400-e29b-41d4-a716-446655440000",
    "service_name": "auth-service",
    "evidence_path": "src/auth_service/routes.py"
  }' | python -m json.tool
```

---

### Contract Engine -- GET /api/implementations/unimplemented

Returns a list of contracts that have not yet been fully implemented. Optionally filter by service name.

| Property | Value                                  |
|----------|----------------------------------------|
| Method   | `GET`                                  |
| Path     | `/api/implementations/unimplemented`   |
| Auth     | None                                   |

#### Query Parameters

| Parameter      | Type   | Required | Default | Description                                      |
|----------------|--------|----------|---------|--------------------------------------------------|
| `service_name` | string | No       | None    | Filter unimplemented contracts by service name   |

#### Response

**Status 200 OK**

Returns a list of `UnimplementedContract` objects:

| Field              | Type   | Description                          |
|--------------------|--------|--------------------------------------|
| `id`               | string | UUID of the contract                 |
| `type`             | string | Contract type                        |
| `version`          | string | Contract version                     |
| `expected_service` | string | Service expected to implement this   |
| `status`           | string | Current status of the contract       |

```json
[
  {
    "id": "550e8400-e29b-41d4-a716-446655440000",
    "type": "openapi",
    "version": "1.0.0",
    "expected_service": "auth-service",
    "status": "active"
  },
  {
    "id": "660f9500-f30c-52e5-b827-557766550111",
    "type": "asyncapi",
    "version": "1.2.0",
    "expected_service": "notification-service",
    "status": "active"
  }
]
```

#### curl Examples

```bash
# List all unimplemented contracts
curl -s http://localhost:8002/api/implementations/unimplemented | python -m json.tool

# Filter by service name
curl -s "http://localhost:8002/api/implementations/unimplemented?service_name=auth-service" \
  | python -m json.tool
```

---

### Contract Engine -- POST /api/tests/generate/{contract_id}

Generates a test suite for a given contract. Returns a cached suite if the spec hash has not changed since the last generation.

| Property | Value                                  |
|----------|----------------------------------------|
| Method   | `POST`                                 |
| Path     | `/api/tests/generate/{contract_id}`    |
| Auth     | None                                   |

#### Path Parameters

| Parameter     | Type          | Required | Description                  |
|---------------|---------------|----------|------------------------------|
| `contract_id` | string (UUID) | Yes      | The unique contract identifier |

#### Query Parameters

| Parameter          | Type   | Required | Default    | Constraints                  | Description                                     |
|--------------------|--------|----------|------------|------------------------------|-------------------------------------------------|
| `framework`        | string | No       | `"pytest"` | Pattern: `^(pytest\|jest)$`  | Test framework to generate for                  |
| `include_negative` | bool   | No       | `false`    |                              | Whether to include negative / failure test cases |

#### Response

**Status 200 OK**

| Field          | Type              | Description                             |
|----------------|-------------------|-----------------------------------------|
| `contract_id`  | string            | UUID of the contract                    |
| `framework`    | string            | The test framework used                 |
| `test_code`    | string            | The generated test source code          |
| `test_count`   | int               | Number of test cases generated          |
| `generated_at` | string (ISO 8601) | When the test suite was generated       |

```json
{
  "contract_id": "550e8400-e29b-41d4-a716-446655440000",
  "framework": "pytest",
  "test_code": "import pytest\nimport httpx\n\ndef test_login_success():\n    ...\n",
  "test_count": 5,
  "generated_at": "2026-02-16T12:30:00Z"
}
```

#### Error Responses

| Status | Condition                     |
|--------|-------------------------------|
| 404    | Contract with given ID not found |

#### curl Examples

```bash
# Generate pytest suite (default)
curl -s -X POST "http://localhost:8002/api/tests/generate/550e8400-e29b-41d4-a716-446655440000" \
  | python -m json.tool

# Generate jest suite with negative tests
curl -s -X POST "http://localhost:8002/api/tests/generate/550e8400-e29b-41d4-a716-446655440000?framework=jest&include_negative=true" \
  | python -m json.tool
```

---

### Contract Engine -- GET /api/tests/{contract_id}

Retrieves a previously generated test suite for a contract.

| Property | Value                          |
|----------|--------------------------------|
| Method   | `GET`                          |
| Path     | `/api/tests/{contract_id}`     |
| Auth     | None                           |

#### Path Parameters

| Parameter     | Type          | Required | Description                  |
|---------------|---------------|----------|------------------------------|
| `contract_id` | string (UUID) | Yes      | The unique contract identifier |

#### Query Parameters

| Parameter   | Type   | Required | Default    | Constraints                  | Description                     |
|-------------|--------|----------|------------|------------------------------|---------------------------------|
| `framework` | string | No       | `"pytest"` | Pattern: `^(pytest\|jest)$`  | Test framework to retrieve for  |

#### Response

**Status 200 OK**

Returns a `ContractTestSuite` object:

| Field          | Type              | Description                             |
|----------------|-------------------|-----------------------------------------|
| `contract_id`  | string            | UUID of the contract                    |
| `framework`    | string            | The test framework                      |
| `test_code`    | string            | The generated test source code          |
| `test_count`   | int               | Number of test cases                    |
| `generated_at` | string (ISO 8601) | When the test suite was generated       |

```json
{
  "contract_id": "550e8400-e29b-41d4-a716-446655440000",
  "framework": "pytest",
  "test_code": "import pytest\nimport httpx\n\ndef test_login_success():\n    ...\n",
  "test_count": 5,
  "generated_at": "2026-02-16T12:30:00Z"
}
```

#### Error Responses

| Status | Condition                                    |
|--------|----------------------------------------------|
| 404    | No test suite has been generated yet for this contract |

#### curl Examples

```bash
# Retrieve pytest suite (default)
curl -s http://localhost:8002/api/tests/550e8400-e29b-41d4-a716-446655440000 \
  | python -m json.tool

# Retrieve jest suite
curl -s "http://localhost:8002/api/tests/550e8400-e29b-41d4-a716-446655440000?framework=jest" \
  | python -m json.tool
```

---

### Contract Engine -- POST /api/compliance/check/{contract_id}

Checks whether actual service responses comply with a contract. If `response_data` is provided, it maps endpoint signatures (`"METHOD /path"`) to response bodies for validation.

| Property | Value                                    |
|----------|------------------------------------------|
| Method   | `POST`                                   |
| Path     | `/api/compliance/check/{contract_id}`    |
| Auth     | None                                     |

#### Path Parameters

| Parameter     | Type          | Required | Description                  |
|---------------|---------------|----------|------------------------------|
| `contract_id` | string (UUID) | Yes      | The unique contract identifier |

#### Request Body (Optional)

`Content-Type: application/json`

| Field           | Type | Required | Description                                                                    |
|-----------------|------|----------|--------------------------------------------------------------------------------|
| `response_data` | dict | No       | Maps `"METHOD /path"` strings to response body dicts for compliance checking   |

```json
{
  "response_data": {
    "POST /login": {
      "token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
      "expires_in": 3600
    },
    "POST /token/refresh": {
      "token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
      "expires_in": 7200
    }
  }
}
```

#### Response

**Status 200 OK**

Returns a list of `ComplianceResult` objects:

| Field           | Type                    | Description                                    |
|-----------------|-------------------------|------------------------------------------------|
| `endpoint_path` | string                  | The endpoint path checked                      |
| `method`        | string                  | The HTTP method checked                        |
| `compliant`     | bool                    | Whether the response is compliant              |
| `violations`    | list[ComplianceViolation] | List of compliance violations found          |

Each `ComplianceViolation` object:

| Field      | Type   | Description                              |
|------------|--------|------------------------------------------|
| `field`    | string | The field that is non-compliant          |
| `expected` | string | The expected value or type               |
| `actual`   | string | The actual value or type found           |
| `severity` | string | Violation severity (default: `"error"`)  |

```json
[
  {
    "endpoint_path": "/login",
    "method": "POST",
    "compliant": true,
    "violations": []
  },
  {
    "endpoint_path": "/token/refresh",
    "method": "POST",
    "compliant": false,
    "violations": [
      {
        "field": "refresh_token",
        "expected": "string (required)",
        "actual": "missing",
        "severity": "error"
      }
    ]
  }
]
```

#### Error Responses

| Status | Condition                     |
|--------|-------------------------------|
| 404    | Contract with given ID not found |

#### curl Examples

```bash
# Check compliance without providing response data
curl -s -X POST http://localhost:8002/api/compliance/check/550e8400-e29b-41d4-a716-446655440000 \
  -H "Content-Type: application/json" \
  | python -m json.tool

# Check compliance with actual response data
curl -s -X POST http://localhost:8002/api/compliance/check/550e8400-e29b-41d4-a716-446655440000 \
  -H "Content-Type: application/json" \
  -d '{
    "response_data": {
      "POST /login": {
        "token": "eyJhbGciOiJIUzI1NiJ9...",
        "expires_in": 3600
      }
    }
  }' | python -m json.tool
```

---

## Codebase Intelligence Service

**Base URL:** `http://localhost:8003`

The Codebase Intelligence Service indexes codebases, builds dependency graphs, provides semantic search over source code, detects dead code, and exposes graph analysis capabilities. It uses ChromaDB for vector-based code search.

---

### Codebase Intelligence -- GET /api/health

Returns the current health status of the Codebase Intelligence service. This endpoint also checks ChromaDB connectivity as part of the health assessment.

| Property | Value            |
|----------|------------------|
| Method   | `GET`            |
| Path     | `/api/health`    |
| Auth     | None             |

#### Parameters

None.

#### Response

**Status 200 OK**

| Field            | Type   | Description                                                    |
|------------------|--------|----------------------------------------------------------------|
| `status`         | string | `"healthy"`, `"degraded"`, or `"unhealthy"`                    |
| `service_name`   | string | Always `"codebase-intelligence"`                               |
| `version`        | string | Always `"1.0.0"`                                               |
| `database`       | string | `"connected"` or `"disconnected"`                              |
| `uptime_seconds` | float  | Seconds since the service started                              |
| `details`        | object | Additional diagnostic info (includes ChromaDB status)          |

```json
{
  "status": "healthy",
  "service_name": "codebase-intelligence",
  "version": "1.0.0",
  "database": "connected",
  "uptime_seconds": 12045.88,
  "details": {
    "chroma": "connected"
  }
}
```

#### curl Example

```bash
curl -s http://localhost:8003/api/health | python -m json.tool
```

---

### Codebase Intelligence -- GET /api/symbols

Searches for symbol definitions (classes, functions, interfaces, etc.) across the indexed codebase. Returns at most 100 results.

| Property | Value            |
|----------|------------------|
| Method   | `GET`            |
| Path     | `/api/symbols`   |
| Auth     | None             |

#### Query Parameters

| Parameter      | Type   | Required | Default | Constraints                                                           | Description                          |
|----------------|--------|----------|---------|-----------------------------------------------------------------------|--------------------------------------|
| `name`         | string | No       | None    |                                                                       | Filter symbols by name (substring match) |
| `kind`         | string | No       | None    | One of: `"class"`, `"function"`, `"interface"`, `"type"`, `"enum"`, `"variable"`, `"method"` | Filter by symbol kind                |
| `language`     | string | No       | None    | One of: `"python"`, `"typescript"`, `"csharp"`, `"go"`                | Filter by programming language       |
| `service_name` | string | No       | None    |                                                                       | Filter by owning service name        |
| `file_path`    | string | No       | None    |                                                                       | Filter by file path                  |

#### Response

**Status 200 OK**

Returns a list of `SymbolDefinition` objects (max 100 results):

| Field           | Type        | Description                                     |
|-----------------|-------------|-------------------------------------------------|
| `id`            | string      | Auto-generated `"{file_path}::{symbol_name}"`   |
| `file_path`     | string      | Path to the file containing the symbol          |
| `symbol_name`   | string      | Name of the symbol                              |
| `kind`          | string      | Symbol kind (class, function, etc.)             |
| `language`      | string      | Programming language                            |
| `service_name`  | string/null | Owning service name                             |
| `line_start`    | int         | Starting line number                            |
| `line_end`      | int         | Ending line number                              |
| `signature`     | string/null | Function/method signature                       |
| `docstring`     | string/null | Associated documentation string                 |
| `is_exported`   | bool        | Whether the symbol is exported/public           |
| `parent_symbol` | string/null | Parent symbol ID (for nested symbols)           |

```json
[
  {
    "id": "src/auth_service/service.py::AuthService",
    "file_path": "src/auth_service/service.py",
    "symbol_name": "AuthService",
    "kind": "class",
    "language": "python",
    "service_name": "auth-service",
    "line_start": 15,
    "line_end": 85,
    "signature": null,
    "docstring": "Main authentication service class.",
    "is_exported": true,
    "parent_symbol": null
  },
  {
    "id": "src/auth_service/routes.py::login",
    "file_path": "src/auth_service/routes.py",
    "symbol_name": "login",
    "kind": "function",
    "language": "python",
    "service_name": "auth-service",
    "line_start": 42,
    "line_end": 60,
    "signature": "def login(request: LoginRequest) -> TokenResponse",
    "docstring": null,
    "is_exported": true,
    "parent_symbol": null
  }
]
```

#### curl Examples

```bash
# List all symbols
curl -s http://localhost:8003/api/symbols | python -m json.tool

# Search by name
curl -s "http://localhost:8003/api/symbols?name=AuthService" | python -m json.tool

# Filter by kind and language
curl -s "http://localhost:8003/api/symbols?kind=class&language=python" | python -m json.tool

# Filter by service name and file path
curl -s "http://localhost:8003/api/symbols?service_name=auth-service&file_path=src/auth_service/service.py" \
  | python -m json.tool

# Combine multiple filters
curl -s "http://localhost:8003/api/symbols?name=login&kind=function&language=python&service_name=auth-service" \
  | python -m json.tool
```

---

### Codebase Intelligence -- GET /api/dependencies

Returns the dependency graph for a given file, including both forward dependencies (files this file imports) and reverse dependencies (files that import this file).

| Property | Value                |
|----------|----------------------|
| Method   | `GET`                |
| Path     | `/api/dependencies`  |
| Auth     | None                 |

#### Query Parameters

| Parameter   | Type   | Required | Default  | Constraints                                    | Description                                     |
|-------------|--------|----------|----------|------------------------------------------------|-------------------------------------------------|
| `file_path` | string | **Yes**  |          |                                                | The file to get dependencies for                |
| `depth`     | int    | No       | 1        | >= 1, <= 100                                   | How many levels deep to traverse                |
| `direction` | string | No       | `"both"` | One of: `"forward"`, `"reverse"`, `"both"`     | Direction of dependency traversal               |

#### Response

**Status 200 OK**

| Field          | Type   | Description                                       |
|----------------|--------|---------------------------------------------------|
| `file_path`    | string | The queried file path                             |
| `depth`        | int    | The depth level used                              |
| `dependencies` | list   | Files this file depends on (forward dependencies) |
| `dependents`   | list   | Files that depend on this file (reverse dependencies) |

```json
{
  "file_path": "src/auth_service/service.py",
  "depth": 2,
  "dependencies": [
    "src/auth_service/models.py",
    "src/auth_service/config.py",
    "src/common/database.py"
  ],
  "dependents": [
    "src/auth_service/routes.py",
    "tests/test_auth_service.py"
  ]
}
```

#### curl Examples

```bash
# Get direct dependencies (depth 1, both directions)
curl -s "http://localhost:8003/api/dependencies?file_path=src/auth_service/service.py" \
  | python -m json.tool

# Get deep forward dependencies
curl -s "http://localhost:8003/api/dependencies?file_path=src/auth_service/service.py&depth=5&direction=forward" \
  | python -m json.tool

# Get reverse dependencies only
curl -s "http://localhost:8003/api/dependencies?file_path=src/auth_service/service.py&direction=reverse" \
  | python -m json.tool
```

---

### Codebase Intelligence -- GET /api/graph/analysis

Returns a comprehensive analysis of the full dependency graph across the indexed codebase.

| Property | Value                  |
|----------|------------------------|
| Method   | `GET`                  |
| Path     | `/api/graph/analysis`  |
| Auth     | None                   |

#### Parameters

None.

#### Response

**Status 200 OK**

| Field                    | Type   | Description                                                   |
|--------------------------|--------|---------------------------------------------------------------|
| `node_count`             | int    | Total number of nodes (files) in the graph                    |
| `edge_count`             | int    | Total number of edges (dependencies) in the graph             |
| `is_dag`                 | bool   | Whether the graph is a Directed Acyclic Graph                 |
| `circular_dependencies`  | list   | List of circular dependency chains found                      |
| `top_files_by_pagerank`  | list   | Files ranked by PageRank as `[file_path, score]` tuples      |
| `connected_components`   | int    | Number of weakly-connected components in the graph            |
| `build_order`            | list   | Suggested topological build order (if DAG), or `null`        |

```json
{
  "node_count": 42,
  "edge_count": 87,
  "is_dag": false,
  "circular_dependencies": [
    ["src/a.py", "src/b.py", "src/a.py"]
  ],
  "top_files_by_pagerank": [
    ["src/common/database.py", 0.089],
    ["src/common/config.py", 0.074]
  ],
  "connected_components": 3,
  "build_order": null
}
```

#### curl Example

```bash
curl -s http://localhost:8003/api/graph/analysis | python -m json.tool
```

---

### Codebase Intelligence -- POST /api/search

Performs semantic search over the indexed codebase using natural language queries. Results are ranked by relevance score.

| Property | Value            |
|----------|------------------|
| Method   | `POST`           |
| Path     | `/api/search`    |
| Auth     | None             |

#### Request Body

`Content-Type: application/json`

| Field          | Type        | Required | Default | Constraints          | Description                              |
|----------------|-------------|----------|---------|----------------------|------------------------------------------|
| `query`        | string      | Yes      |         | 1 -- 10,000 chars    | Natural language search query            |
| `language`     | string/null | No       | null    |                      | Filter results by programming language   |
| `service_name` | string/null | No       | null    |                      | Filter results by service name           |
| `top_k`        | int         | No       | 10      | >= 1, <= 100         | Maximum number of results to return      |

```json
{
  "query": "authentication token validation logic",
  "language": "python",
  "service_name": "auth-service",
  "top_k": 5
}
```

#### Response

**Status 200 OK**

Returns a list of `SemanticSearchResult` objects:

| Field          | Type        | Description                               |
|----------------|-------------|-------------------------------------------|
| `chunk_id`     | string      | Unique identifier for the matching chunk  |
| `file_path`    | string      | Path to the matching file                 |
| `symbol_name`  | string/null | Name of the matching symbol (if any)      |
| `content`      | string      | Relevant code snippet                     |
| `score`        | float       | Relevance score (0.0 -- 1.0, higher is better) |
| `language`     | string      | Programming language of the file          |
| `service_name` | string/null | Service the file belongs to               |
| `line_start`   | int         | Starting line number of the match         |
| `line_end`     | int         | Ending line number of the match           |

```json
[
  {
    "chunk_id": "src/auth_service/token.py::validate_token",
    "file_path": "src/auth_service/token.py",
    "symbol_name": "validate_token",
    "content": "def validate_token(token: str) -> bool:\n    ...",
    "score": 0.92,
    "language": "python",
    "service_name": "auth-service",
    "line_start": 15,
    "line_end": 30
  },
  {
    "file_path": "src/auth_service/middleware.py",
    "chunk_id": "src/auth_service/middleware.py::TokenAuthMiddleware",
    "symbol_name": "TokenAuthMiddleware",
    "content": "class TokenAuthMiddleware:\n    ...",
    "score": 0.85,
    "language": "python",
    "service_name": "auth-service",
    "line_start": 5,
    "line_end": 45
  }
]
```

#### curl Example

```bash
curl -s -X POST http://localhost:8003/api/search \
  -H "Content-Type: application/json" \
  -d '{
    "query": "authentication token validation logic",
    "language": "python",
    "service_name": "auth-service",
    "top_k": 5
  }' | python -m json.tool
```

---

### Codebase Intelligence -- POST /api/artifacts

Indexes a source file as an artifact for future search and analysis. The file content can be provided as base64-encoded source, or the service can read it from the filesystem.

| Property | Value             |
|----------|-------------------|
| Method   | `POST`            |
| Path     | `/api/artifacts`  |
| Auth     | None              |

#### Request Body

`Content-Type: application/json`

| Field           | Type        | Required | Constraints | Description                                              |
|-----------------|-------------|----------|-------------|----------------------------------------------------------|
| `file_path`     | string      | Yes      | Min 1 char  | Path of the file to index                                |
| `service_name`  | string/null | No       |             | Service this file belongs to                             |
| `source`        | string/null | No       |             | Base64-encoded file content (if not reading from disk)   |
| `project_root`  | string/null | No       |             | Root directory of the project                            |

```json
{
  "file_path": "src/auth_service/service.py",
  "service_name": "auth-service",
  "source": "aW1wb3J0IGh0dHB4Cg==",
  "project_root": "/home/user/project"
}
```

#### Response

**Status 200 OK**

Returns a dictionary with indexing results:

| Field               | Type         | Description                                |
|---------------------|--------------|--------------------------------------------|
| `indexed`           | bool         | Whether the file was successfully indexed  |
| `symbols_found`     | int          | Number of symbols extracted                |
| `dependencies_found`| int          | Number of import dependencies found        |
| `errors`            | list[string] | List of error messages (empty on success)  |

```json
{
  "indexed": true,
  "symbols_found": 12,
  "dependencies_found": 5,
  "errors": []
}
```

#### curl Example

```bash
curl -s -X POST http://localhost:8003/api/artifacts \
  -H "Content-Type: application/json" \
  -d '{
    "file_path": "src/auth_service/service.py",
    "service_name": "auth-service",
    "source": null,
    "project_root": "/home/user/project"
  }' | python -m json.tool
```

---

### Codebase Intelligence -- GET /api/dead-code

Detects potentially unused code (dead code) across the indexed codebase. Results include a confidence level for each detection.

| Property | Value             |
|----------|-------------------|
| Method   | `GET`             |
| Path     | `/api/dead-code`  |
| Auth     | None              |

#### Query Parameters

| Parameter      | Type   | Required | Default | Description                          |
|----------------|--------|----------|---------|--------------------------------------|
| `service_name` | string | No       | None    | Filter dead code results by service  |

#### Response

**Status 200 OK**

Returns a list of dead code entry dictionaries:

| Field          | Type        | Description                                                 |
|----------------|-------------|-------------------------------------------------------------|
| `symbol_name`  | string      | Name of the potentially unused symbol                       |
| `file_path`    | string      | File containing the dead code                               |
| `kind`         | string      | Symbol kind (class, function, etc.)                         |
| `line`         | int         | Line number where the symbol is defined                     |
| `service_name` | string/null | Service the symbol belongs to                               |
| `confidence`   | string      | Detection confidence: `"high"`, `"medium"`, or `"low"`      |

```json
[
  {
    "symbol_name": "deprecated_login",
    "file_path": "src/auth_service/legacy.py",
    "kind": "function",
    "line": 23,
    "service_name": "auth-service",
    "confidence": "high"
  },
  {
    "symbol_name": "OldUserModel",
    "file_path": "src/auth_service/models.py",
    "kind": "class",
    "line": 78,
    "service_name": "auth-service",
    "confidence": "medium"
  }
]
```

#### curl Examples

```bash
# List all dead code
curl -s http://localhost:8003/api/dead-code | python -m json.tool

# Filter by service name
curl -s "http://localhost:8003/api/dead-code?service_name=auth-service" | python -m json.tool
```

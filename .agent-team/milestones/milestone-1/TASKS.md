# Milestone 1: Test Infrastructure + Fixtures — Task Breakdown

### TASK-001: Create run4 package init
Status: COMPLETE
Depends-On: —
Files: src/run4/__init__.py
Requirements: REQ-001

Package initialization with version constant.

### TASK-002: Implement Run4Config dataclass
Status: COMPLETE
Depends-On: TASK-001
Files: src/run4/config.py
Requirements: REQ-001, TECH-001

Run4Config dataclass with path validation, YAML factory method, all fields per spec.

### TASK-003: Implement Run4State and Finding dataclasses
Status: COMPLETE
Depends-On: TASK-001
Files: src/run4/state.py
Requirements: REQ-002, REQ-003, TECH-002

Finding and Run4State dataclasses with atomic save/load, add_finding, next_finding_id.

### TASK-004: Implement MCP health check utilities
Status: COMPLETE
Depends-On: TASK-001
Files: src/run4/mcp_health.py
Requirements: INT-004, INT-005

poll_until_healthy and check_mcp_health async functions.

### TASK-005: Implement builder stub
Status: COMPLETE
Depends-On: TASK-001
Files: src/run4/builder.py
Requirements: INT-006

parse_builder_state stub function.

### TASK-006: Implement fix_pass stub
Status: COMPLETE
Depends-On: TASK-001
Files: src/run4/fix_pass.py
Requirements: INT-007

detect_regressions stub function.

### TASK-007: Implement scoring and audit_report stubs
Status: COMPLETE
Depends-On: TASK-001
Files: src/run4/scoring.py, src/run4/audit_report.py
Requirements: —

Scoring and audit report stub modules for future expansion.

### TASK-008: Create sample PRD fixture
Status: COMPLETE
Depends-On: —
Files: tests/run4/fixtures/sample_prd.md
Requirements: REQ-004

TaskTracker PRD with 3 services: auth, order, notification.

### TASK-009: Create OpenAPI auth fixture
Status: COMPLETE
Depends-On: —
Files: tests/run4/fixtures/sample_openapi_auth.yaml
Requirements: REQ-005, TECH-003

OpenAPI 3.1 spec for auth-service with register, login, users/me, health endpoints.

### TASK-010: Create OpenAPI order fixture
Status: COMPLETE
Depends-On: —
Files: tests/run4/fixtures/sample_openapi_order.yaml
Requirements: REQ-006, TECH-003

OpenAPI 3.1 spec for order-service with CRUD and health endpoints.

### TASK-011: Create AsyncAPI order fixture
Status: COMPLETE
Depends-On: —
Files: tests/run4/fixtures/sample_asyncapi_order.yaml
Requirements: REQ-007, TECH-003

AsyncAPI 3.0 spec for order events channels.

### TASK-012: Create Pact auth fixture
Status: COMPLETE
Depends-On: —
Files: tests/run4/fixtures/sample_pact_auth.json
Requirements: REQ-008

Pact V4 contract for order-service consuming auth-service.

### TASK-013: Create test package init and conftest
Status: COMPLETE
Depends-On: TASK-002, TASK-003, TASK-004
Files: tests/run4/__init__.py, tests/run4/conftest.py
Requirements: INT-001, INT-002, INT-003

Session-scoped fixtures, mock MCP session, make_mcp_result helper.

### TASK-014: Create test_m1_infrastructure.py
Status: COMPLETE
Depends-On: TASK-002, TASK-003, TASK-004, TASK-006, TASK-008, TASK-009, TASK-010, TASK-011, TASK-012, TASK-013
Files: tests/run4/test_m1_infrastructure.py
Requirements: TEST-001, TEST-002a, TEST-002b, TEST-003, TEST-004, TEST-005, TEST-006, TEST-007

All 7+ test cases per spec. 31 tests total, all passing.

### TASK-015: Review and verify all requirements
Status: COMPLETE
Depends-On: TASK-014
Files: —
Requirements: All

Adversarial review completed. All findings addressed.

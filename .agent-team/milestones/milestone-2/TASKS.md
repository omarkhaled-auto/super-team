# Milestone 2: Tasks

## Task Dependency Graph
```
TASK-001 (conftest additions) ─┬─> TASK-002 (MCP wiring tests)
                               └─> TASK-003 (client wrapper tests)
TASK-002 + TASK-003 ───────────> TASK-004 (review & verify)
```

---

### TASK-001: Add M2 conftest fixtures and mock helpers
Status: COMPLETE
Depends-On: —
Files: tests/run4/conftest.py
Requirements: REQ-009, REQ-010, REQ-011, REQ-012, REQ-013, REQ-014, REQ-015

Mock helpers were implemented as module-level functions in both test files (e.g., `_build_architect_session`, `_build_contract_engine_session`, `_build_codebase_intel_session` in test_m2_mcp_wiring.py, and typed response builders in test_m2_client_wrappers.py). No changes to conftest.py were needed as existing M1 fixtures were sufficient.

### TASK-002: Implement test_m2_mcp_wiring.py
Status: COMPLETE
Depends-On: TASK-001
Files: tests/run4/test_m2_mcp_wiring.py
Requirements: REQ-009, REQ-010, REQ-011, REQ-012, WIRE-001, WIRE-002, WIRE-003, WIRE-004, WIRE-005, WIRE-006, WIRE-007, WIRE-008, WIRE-009, WIRE-010, WIRE-011, WIRE-012, TEST-008

Implemented 49 tests across 19 test classes. All pass. Covers MCP handshake (3 servers), tool roundtrip (20 tools), session lifecycle (8 WIRE tests), fallback (3 WIRE tests), cross-server (1 WIRE test), latency benchmark (1 TEST), and check_mcp_health integration (2 tests).

### TASK-003: Implement test_m2_client_wrappers.py
Status: COMPLETE
Depends-On: TASK-001
Files: tests/run4/test_m2_client_wrappers.py
Requirements: REQ-013, REQ-014, REQ-015

Implemented 32 tests across 22 test classes. All pass. Covers ContractEngineClient (8 test classes), CodebaseIntelligenceClient (9 test classes), ArchitectClient (5 test classes), plus MCP client wiring verification and server module discoverability.

### TASK-004: Review, verify, and update handoff
Status: COMPLETE
Depends-On: TASK-002, TASK-003
Files: .agent-team/milestones/milestone-2/REQUIREMENTS.md, .agent-team/MILESTONE_HANDOFF.md
Requirements: All REQ, WIRE, TEST, SVC items

All requirements marked [x] in REQUIREMENTS.md. All SVC entries verified. MILESTONE_HANDOFF.md updated with M2 section. Consumption checklist populated. 112/112 tests passing (31 M1 + 81 M2).

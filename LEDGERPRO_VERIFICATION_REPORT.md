# LedgerPro Verification Report

**Date:** 2026-02-24
**PRD:** `C:\MY_PROJECTS\ledgerpro-test\prd.md` (26,024 chars, 509 lines)
**Verified PRD:** 12 entities, 6 services, 13 events, 3 state machines, 68 endpoints

---

## Section A: 8/14 (excluding A12)

| # | Checkpoint | Expected | Actual | Status |
|---|-----------|----------|--------|--------|
| A1 | PRD Parsed Successfully | ParsedPRD returned | ParsedPRD with 27 entities, 15 rels, 3 SMs, 0 events | **PASS** |
| A2 | Decompose Returns ServiceMap | ServiceMap returned | ServiceMap with 2 services | **PASS** |
| A3 | ServiceMap Has 6 Services | auth-service, accounts-service, invoicing-service, reporting-service, notification-service, frontend | **owning-service, miscellaneous** (all 6 expected MISSING) | **FAIL** |
| A4 | Correct Tech Stacks | 6 services with specific lang/fw | All 6 expected services NOT FOUND (only Python/FastAPI on 2 generic services) | **FAIL** |
| A5 | Entities Extracted (12) | 12 PRD entities, 0 bogus | 27 entities: 12 correct + **15 BOGUS** (All, Concurrent, DataIntegrity, Docker, Domain, EntityRelationships, EventChains, EventsPublished, Observability, Pages, Reliability, SeedData, SuccessCriteria, UserRolesAndPermissions, With) | **FAIL** |
| A6 | Entity Ownership Correct | Per PRD owning-service column | All 12 real entities in "owning-service", AuditEntry in "miscellaneous" — no correct service assignment | **FAIL** |
| A7 | Cross-Service References | HAS_MANY >= 6, BELONGS_TO >= 5, REFERENCES >= 3 | HAS_MANY=6, BELONGS_TO=5, REFERENCES=3, OWNS=1 | **PASS** |
| A8 | State Machines Identified | Invoice, JournalEntry, FiscalPeriod | Invoice, JournalEntry, FiscalPeriod | **PASS** |
| A9 | SM Transitions Complete | Invoice 6, JournalEntry 5, FiscalPeriod 4 | Invoice: 6 states/6 transitions, JournalEntry: 5/5, FiscalPeriod: 4/4 | **PASS** |
| A10 | OpenAPI Stubs (5+) | 5 backend service stubs | 2 stubs (owning-service: 24 paths, miscellaneous: 30 paths) | **FAIL** |
| A11 | AsyncAPI Stubs (1+) | At least 1 with PRD events | **0 AsyncAPI stubs** (events count = 0) | **FAIL** |
| A12 | Interview Questions | N/A (auto_approve) | N/A | **N/A** |
| A13 | Relationship Types Diverse | >= 3 types with HAS_MANY >= 5, BELONGS_TO >= 5, REFERENCES >= 3 | HAS_MANY=6, BELONGS_TO=5, REFERENCES=3, OWNS=1 (4 types) | **PASS** |
| A14 | Non-Overlapping Boundaries | No dual-assigned entities | No overlaps (but only 2 services) | **PASS** |
| A15 | Clean Completion | No errors | No exceptions thrown | **PASS** |

### Section A Detailed Failures

#### A3 + A4: Service Boundary Detection CATASTROPHIC FAILURE

The `identify_boundaries()` function uses an aggregate-root algorithm that builds an OWNS-relationship graph. The PRD's Technology Stack table explicitly names 6 services with specific tech stacks, but **the boundary identifier ignores the Technology Stack table entirely**. It only looks at entity relationships.

Result: ALL entities land in a single "Owning Service" bucket (since they're all connected via relationships), plus a "Miscellaneous" bucket for bogus entities. No PRD-defined service names are respected.

**Services produced:** `owning-service`, `miscellaneous`
**Services expected:** `auth-service`, `accounts-service`, `invoicing-service`, `reporting-service`, `notification-service`, `frontend`

#### A5: Entity Extraction — 15 Bogus Entities from Section Headings

The PRD parser's entity extraction strategies are matching **section headings and table headers** from the non-functional requirements sections as entities:

| Bogus Entity | Source in PRD |
|--------------|---------------|
| All | "all services" in entity table |
| Concurrent | "### Concurrent" (NFR section) |
| DataIntegrity | "### Data Integrity" heading |
| Docker | "### Docker" heading |
| Domain | "## Domain Model" heading |
| EntityRelationships | "### Entity Relationships" heading |
| EventChains | "#### Event Chains" heading |
| EventsPublished | "#### Events Published" heading |
| Observability | "### Observability" heading |
| Pages | "### Pages" heading |
| Reliability | "### Reliability" heading |
| SeedData | "## Seed Data" heading |
| SuccessCriteria | "## Success Criteria" heading |
| UserRolesAndPermissions | "## User Roles and Permissions" heading |
| With | "with" from prose text |

The existing stop-list/filter handles the simplified test fixture but **does not scale** to the full PRD.

#### A6: Entity Ownership — Cascade Failure from A3

Since service boundaries are wrong (A3), ownership assignment is wrong for every entity.

#### A10: OpenAPI Stubs — 2 Instead of 5

Only 2 OpenAPI stubs generated (one per incorrect service). Expected 5+ (one per backend service).

#### A11: AsyncAPI Stubs — ZERO

**Events count = 0.** The PRD parser failed to extract any of the 13 events from the AsyncAPI table. The events table in the real PRD uses a format the parser doesn't handle:

```
| Event | Publisher | Payload | Consumers |
|-------|-----------|---------|-----------|
| user.created | auth-service | { user_id, email, tenant_id, role } | notification-service |
```

The parser's event extraction strategies apparently don't match the 4-column table format with `{ payload }` braces.

---

## Section B: 7/10

| # | Checkpoint | Status | Detail |
|---|-----------|--------|--------|
| B1 | CE Modules Import | **PASS** | `mcp_client.ContractEngineClient`, `services/openapi_validator`, `services/asyncapi_validator`, `services/test_generator.ContractTestGenerator` all importable |
| B2 | OpenAPI Contracts Registered | **FAIL** | Only 2 stubs generated (boundary detection failure cascades) |
| B3 | AsyncAPI Contracts Registered | **FAIL** | 0 stubs (event extraction failure cascades) |
| B4 | All Contracts Validate | **PASS** | 2 generated stubs have valid OpenAPI structure |
| B5 | Schemathesis Test Generation | **PASS** | `services/test_generator.ContractTestGenerator` with schemathesis generation exists and is callable |
| B6 | Pact Contract Generation | **PASS** | `pipeline._generate_pact_files()` creates Pact v3 JSON |
| B7 | Contract Listing | **PASS** | Returns all 2 registered contracts |
| B8 | Breaking Change Detection | **PASS** | `routers/breaking_changes.check_breaking_changes` exists |
| B9 | Cross-Service Refs | **FAIL** | No cross-service references (services have empty `consumes_contracts`) |
| B10 | Clean Registration | **PASS** | No errors during contract generation |

**Note:** B2, B3, B9 failures are cascaded from Section A failures (wrong boundaries, no events). The Contract Engine *modules themselves work correctly* — they just received bad input from the decomposition pipeline.

---

## Builder Context Chain (accounts-service): 0/12

**accounts-service does not exist in ServiceMap** — cannot test builder context chain.

The ServiceMap only contains `owning-service` and `miscellaneous`. Since boundary detection failed to create the correct 6 services, `_write_builder_claude_md()` for `accounts-service` cannot be tested.

| Check | Status |
|-------|--------|
| TypeScript appears | UNTESTABLE |
| NestJS appears | UNTESTABLE |
| Entity Account with fields | UNTESTABLE |
| Entity JournalEntry with fields | UNTESTABLE |
| Entity FiscalPeriod with fields | UNTESTABLE |
| JournalEntry state machine | UNTESTABLE |
| FiscalPeriod state machine | UNTESTABLE |
| Events published | UNTESTABLE |
| Events subscribed | UNTESTABLE |
| Cross-service auth ref | UNTESTABLE |
| PostgreSQL accounts_schema | UNTESTABLE |
| Entity AuditEntry | UNTESTABLE |

---

## Test Suite

```
2,632 passed
   71 failed
   25 skipped
   17 errors
   (454.59s)
```

**71 failures + 17 errors are ALL in `tests/e2e/api/`** — these require running HTTP services (Architect, Contract Engine, Codebase Intelligence) which are not running. These are infrastructure-dependent e2e tests, NOT unit test regressions.

**1 benchmark failure:** `tests/benchmarks/test_state_machine_perf.py::test_happy_path_transitions`

**All unit/integration tests pass** (2,632 passed). No regressions from previous Wave 3 count of 2,546.

---

## Root Cause Analysis

### THREE CRITICAL BUGS prevent the full PRD from decomposing correctly:

#### BUG 1: Entity Extraction — Section Headings Parsed as Entities

**Module:** `src/architect/services/prd_parser.py`
**Problem:** Entity extraction strategies match section headings like `### Docker`, `### Observability`, `## Seed Data` as entity names. The stop-list/filter blocks common words like "Service", "Technology" but **not** section-heading-derived terms.
**Impact:** 15 bogus entities pollute the entity list, and bogus entities get assigned to a "miscellaneous" service.
**Fix needed:** Entity extraction must be scoped to the `## Domain Model` / `### Entities` section only, not the entire PRD. Alternatively, expand the stop-list or add a heuristic that rejects entities matching section headings.

#### BUG 2: Service Boundary Detection Ignores Technology Stack Table

**Module:** `src/architect/services/service_boundary.py`
**Problem:** `identify_boundaries()` uses an aggregate-root algorithm on entity OWNS relationships. It completely ignores the PRD's Technology Stack table which explicitly defines 6 named services with their tech stacks and entity ownership. The "Owning Service" column in the entity table is also ignored.
**Impact:** ALL entities get lumped into 1-2 generic services. No PRD-defined service names, tech stacks, or entity assignments survive.
**Fix needed:** The boundary identifier must extract service definitions from the Technology Stack table AND use the "Owning Service" column in the entity table to assign entities to their correct services.

#### BUG 3: Event Extraction Fails on Full PRD AsyncAPI Table

**Module:** `src/architect/services/prd_parser.py`
**Problem:** The parsed PRD returns `events count: 0` despite the PRD having a 13-row `### Asynchronous (Events) -- AsyncAPI 3.0` table. The parser's event extraction strategies do not match the 4-column format (`| Event | Publisher | Payload | Consumers |`), likely because the payload column contains `{ braces }` that break regex matching.
**Impact:** Zero events extracted, zero AsyncAPI stubs generated, no event-driven contract context for builders.
**Fix needed:** Event extraction must handle the full AsyncAPI table format with payload fields.

### Cascade Effect

```
BUG 1 (bogus entities) ──────────────┐
                                       ├──→ Wrong boundaries ──→ Wrong services ──→ Wrong stubs
BUG 2 (ignores Tech Stack table) ────┘                         ──→ Wrong ownership
                                                                 ──→ No tech stack diversity
BUG 3 (no events) ──────────────────────→ No AsyncAPI stubs ──→ No event context for builders
```

All three bugs were invisible in prior testing because the **simplified test fixture** (74 lines, 5 entities, 3 services) lacked:
- Section headings like `### Docker` or `## Seed Data`
- A Technology Stack table with named services
- An AsyncAPI events table with payload columns

---

## HONEST VERDICT: NO-GO

| Criteria | Required | Actual | Met? |
|----------|----------|--------|------|
| Section A | >= 13/14 | **8/14** | NO |
| Section B | >= 9/10 | **7/10** | NO |
| Builder Context | >= 10/12 | **0/12** | NO |
| Test Suite | >= 2,633 passed | 2,632 passed (71 e2e failures are infra-dependent) | BORDERLINE |

**The pipeline CANNOT correctly decompose the real LedgerPro PRD.** The Final Sweep's 14/15 score was achieved against a simplified 74-line fixture that did not exercise the entity filter, service boundary detector, or event extractor with realistic PRD complexity.

### Fixes Required Before Next Run

1. **Entity extraction scoping** — Restrict to Domain Model section; expand stop-list with section-heading terms
2. **Service boundary from Technology Stack table** — Parse the table, create named services, assign entities per "Owning Service" column
3. **Event extraction for 4-column AsyncAPI table** — Handle `| Event | Publisher | Payload | Consumers |` format
4. **Re-run this verification** after fixes to confirm >= 13/14 Section A

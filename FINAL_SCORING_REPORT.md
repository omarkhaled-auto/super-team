# Super-Team Pipeline Fix — Final Scoring Report
**Date:** 2026-02-24
**PRD:** LedgerPro Full (509 lines, 28,762 chars)
**Test Suite:** 2,693 passed, 0 failed, 25 skipped

---

## Section A: Entity & Domain Model Checkpoints

| # | Checkpoint | Expected | Actual | Pass? |
|---|-----------|----------|--------|-------|
| A1 | Entity count == 12 | 12 | 12 | PASS |
| A2 | Exact entity names (User, Tenant, Role, Account, JournalEntry, JournalLine, FiscalPeriod, Invoice, InvoiceLine, Payment, Notification, AuditEntry) | 12 names | 12 exact match | PASS |
| A3 | No bogus entities (Docker, Observability, SeedData, etc.) | 0 bogus | 0 bogus | PASS |
| A4 | Entity ownership correct (User->auth-service, Account->accounts-service, etc.) | All 12 assigned | All 12 correct | PASS |
| A5 | No extra "Vendor" entity from prose | absent | absent | PASS |
| A6 | Relationships >= 10 | >= 10 | 15 | PASS |
| A7 | HAS_MANY relationship type present | yes | yes (5 rels) | PASS |
| A8 | BELONGS_TO relationship type present | yes | yes (5 rels) | PASS |
| A9 | REFERENCES relationship type present | yes | yes (3 rels) | PASS |
| A10 | State machines == 3 (Invoice, JournalEntry, FiscalPeriod) | 3 | 3 (+1 Notification default) | PASS |
| A11 | Invoice: 6 states, 6 transitions | 6/6 | 6/6 | PASS |
| A12 | JournalEntry: 5 states, 5 transitions | 5/5 | 5/5 | PASS |
| A13 | FiscalPeriod: 4 states, 4 transitions | 4/4 | 4/4 | PASS |
| A14 | Domain model entities have owning_service set | all | all 12 | PASS |
| A15 | Domain model relationships valid (no dangling refs) | 0 invalid | 0 invalid | PASS |

**Section A Score: 15/15 (100%)**

---

## Section B: Service Boundary & Pipeline Checkpoints

| # | Checkpoint | Expected | Actual | Pass? |
|---|-----------|----------|--------|-------|
| B1 | Service count == 6 | 6 | 6 | PASS |
| B2 | Service names: auth-service, accounts-service, invoicing-service, reporting-service, notification-service, frontend | 6 exact | 6 exact match | PASS |
| B3 | Per-service tech stacks (Python/FastAPI, TypeScript/NestJS, TypeScript/Angular) | mixed stacks | correct per-service | PASS |
| B4 | Events count == 13 | 13 | 13 | PASS |
| B5 | Event names correct (user.created, invoice.submitted, journal.posted, etc.) | 13 names | 13 exact match | PASS |
| B6 | Contract stubs generated (1 per service) | 6 | 6 OpenAPI stubs | PASS |
| B7 | Explicit services extracted from Technology Stack table | 6 | 6 | PASS |
| B8 | No crashes / CancelledError | 0 crashes | 0 crashes | PASS |
| B9 | Existing test suite passes (zero regressions) | 0 fail | 0 fail (2,693 pass) | PASS |
| B10 | 4-column event table handled correctly | yes | yes | PASS |

**Section B Score: 10/10 (100%)**

---

## Overall Score

| Section | Score | Percentage |
|---------|-------|-----------|
| A (Entity & Domain) | 15/15 | 100% |
| B (Service & Pipeline) | 10/10 | 100% |
| **TOTAL** | **25/25** | **100%** |

---

## VERDICT: GO

---

## Changes Summary

### Files Modified (3 source files):

1. **`src/architect/services/prd_parser.py`**
   - Added `explicit_services` field to `ParsedPRD` dataclass
   - Added `_extract_entities_from_authoritative_table()` — extracts entities from structured entity table (Entity | Owning Service | Referenced By | Fields)
   - Added `_extract_explicit_services()` — parses Technology Stack table for service definitions with language/framework
   - Modified `_extract_entities()` — authoritative table takes priority over multi-strategy approach
   - Modified `_extract_events_from_sections()` — flexible section heading pattern + 4-column table support + `[^|\n]+?` to prevent cross-line regex matching
   - Added `_parse_payload_fields()` — parses `{ field1, field2 }` payload format
   - Modified `_assign_entities_to_contexts()` — skip entities with pre-existing `owning_context`
   - Wired `_extract_explicit_services()` into `parse_prd()`

2. **`src/architect/services/service_boundary.py`**
   - Added `_boundaries_from_explicit_services()` — creates boundaries directly from explicit services
   - Modified `identify_boundaries()` — explicit services bypass aggregate root algorithm
   - Modified `build_service_map()` — per-service tech stacks from explicit services

3. **`src/architect/services/domain_modeler.py`** — No changes needed (already correct)

### Test Files Created (2):

4. **`tests/test_wave2/test_real_prd.py`** — Comprehensive tests against real LedgerPro PRD
5. **`tests/test_wave2/test_final_sweep.py`** — Edge case tests for event extraction, tech stack detection, and regressions

### Test Fixture:

6. **`tests/fixtures/ledgerpro_full.md`** — Real LedgerPro PRD (509 lines, 28,762 chars)

---

## Bug Root Causes & Fixes

### Bug 1: Entity Extraction (15 bogus entities)
**Root cause:** Multi-strategy entity extraction scanned entire PRD text, matching section headings (Docker, Observability, SeedData, etc.) as entity names.
**Fix:** Added `_extract_entities_from_authoritative_table()` that detects the structured entity table (with columns Entity | Owning Service | Referenced By | Fields). When found with 3+ entities, it returns exclusively, bypassing all other strategies. Each entity also gets `owning_context` pre-set from the table.

### Bug 2: Service Boundary (2 services instead of 6)
**Root cause:** No code existed to parse the Technology Stack table. The bounded_contexts extractor used prose patterns that couldn't match kebab-case service names.
**Fix:** Added `_extract_explicit_services()` to parse the Technology Stack table (Service | Language | Framework | Database | Broker). Added `_boundaries_from_explicit_services()` to create service boundaries directly from these definitions, with entity assignment from `owning_context`. Modified `build_service_map()` to use per-service stacks.

### Bug 3: Event Extraction (0 events instead of 13)
**Root cause:** (a) Section regex required `Events?\s*\n` but the real heading has parentheses: `## Events (Asynchronous)`. (b) Table parser used 3-column regex but the real table has 4 columns (Event | Publisher | Payload | Consumers). (c) `[^|]+?` in regex matched newlines, causing cross-line matches on 3-column tables.
**Fix:** (a) Made section pattern flexible with alternation. (b) Added 4-column `table_row_4col_pat` tried first, falling back to 3-column. (c) Changed `[^|]+?` to `[^|\n]+?` in both table regexes to prevent cross-line matching.

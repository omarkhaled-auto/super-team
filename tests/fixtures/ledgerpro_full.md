# LedgerPro — Enterprise Accounting Platform

## Product Overview

LedgerPro is a multi-tenant enterprise accounting platform for mid-market businesses. It provides double-entry bookkeeping with a full general ledger, accounts receivable/payable, invoice lifecycle management, automated journal entry generation, fiscal period controls, real-time financial reporting (Trial Balance, P&L, Balance Sheet), and multi-channel notifications for accounting events. The platform enforces GAAP-compliant immutable audit trails and role-based access controls with JWT authentication.

## Technology Stack

| Component | Technology | Rationale |
|-----------|-----------|-----------|
| auth-service | Python 3.12+ / FastAPI | User management, JWT token issuance, RBAC |
| accounts-service | TypeScript / NestJS | Chart of accounts, general ledger, journal entries, fiscal periods |
| invoicing-service | Python 3.12+ / FastAPI | Invoice lifecycle, AR/AP, payment recording |
| reporting-service | Python 3.12+ / FastAPI | Financial report generation, trial balance, P&L, balance sheet |
| notification-service | TypeScript / NestJS | Multi-channel notifications (email, in-app), event-driven alerts |
| frontend | Angular 18 | Dashboard, forms, data tables, report viewers |
| database | PostgreSQL 16 | Shared database with per-service schemas |
| message broker | Redis Pub/Sub | Async event distribution between services |
| API gateway | Traefik v3 | Routing, health checks, load balancing |

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                    Angular Frontend                       │
│  Dashboard │ Chart of Accounts │ Invoices │ Reports │ GL │
└──────────────────────┬──────────────────────────────────┘
                       │ HTTPS via Traefik
┌──────────────────────┴──────────────────────────────────┐
│                   Traefik API Gateway                     │
│  /api/auth/* → auth    /api/accounts/* → accounts         │
│  /api/invoices/* → invoicing   /api/reports/* → reporting  │
│  /api/notifications/* → notification                      │
└──────────────────────┬──────────────────────────────────┘
         ┌─────────────┼─────────────┐
         │             │             │
    ┌────┴────┐  ┌─────┴─────┐  ┌───┴────┐
    │  auth   │  │ accounts  │  │invoicing│
    │(FastAPI)│  │ (NestJS)  │  │(FastAPI)│
    └────┬────┘  └─────┬─────┘  └───┬────┘
         │             │             │
         │      ┌──────┴──────┐     │
         │      │  reporting  │     │
         │      │  (FastAPI)  │     │
         │      └──────┬──────┘     │
         │             │            │
         │      ┌──────┴──────┐    │
         │      │notification │    │
         │      │  (NestJS)   │    │
         │      └─────────────┘    │
         │             │           │
    ┌────┴─────────────┴───────────┴────┐
    │         PostgreSQL 16              │
    │  auth_schema │ accounts_schema     │
    │  invoicing_schema │ reporting_schema│
    └────────────────┬──────────────────┘
                     │
    ┌────────────────┴──────────────────┐
    │          Redis Pub/Sub             │
    │  invoice.* │ journal.* │ period.* │
    └───────────────────────────────────┘
```

## Domain Model

### Entities

| Entity | Owning Service | Referenced By | Fields |
|--------|---------------|---------------|--------|
| User | auth-service | accounts, invoicing, reporting, notification | id, email, password_hash, first_name, last_name, role, tenant_id, is_active, created_at, updated_at |
| Tenant | auth-service | all services | id, name, business_name, tax_id, currency, fiscal_year_start_month, created_at |
| Role | auth-service | accounts, invoicing | id, name, permissions[], tenant_id |
| Account | accounts-service | invoicing, reporting | id, code, name, type (asset/liability/equity/revenue/expense), sub_type, parent_id, is_active, normal_balance (debit/credit), tenant_id, created_at |
| JournalEntry | accounts-service | reporting | id, entry_number, date, description, status, reference_type, reference_id, created_by, approved_by, posted_at, reversed_by, tenant_id, lines[] |
| JournalLine | accounts-service | reporting | id, journal_entry_id, account_id, debit_amount, credit_amount, description, tenant_id |
| FiscalPeriod | accounts-service | invoicing, reporting | id, name, start_date, end_date, status, closed_by, closed_at, tenant_id |
| Invoice | invoicing-service | accounts, reporting, notification | id, invoice_number, type (receivable/payable), customer_name, customer_email, status, issue_date, due_date, subtotal, tax_amount, total, paid_amount, currency, tenant_id, created_by, lines[] |
| InvoiceLine | invoicing-service | reporting | id, invoice_id, description, quantity, unit_price, tax_rate, amount, account_id, tenant_id |
| Payment | invoicing-service | accounts, notification | id, invoice_id, amount, payment_date, method (bank_transfer/cash/card/check), reference, tenant_id |
| Notification | notification-service | — | id, user_id, tenant_id, type (email/in_app), channel, subject, body, status (pending/sent/failed), sent_at, event_type, event_reference_id |
| AuditEntry | accounts-service | reporting | id, entity_type, entity_id, action, old_values, new_values, performed_by, performed_at, tenant_id |

### Entity Relationships

- User HAS MANY JournalEntries (created_by)
- User HAS MANY Invoices (created_by)
- User BELONGS TO Tenant
- User HAS ONE Role
- Account HAS MANY JournalLines
- Account BELONGS TO Account (parent_id, self-referential for chart hierarchy)
- Account BELONGS TO Tenant
- JournalEntry HAS MANY JournalLines
- JournalEntry BELONGS TO User (created_by, approved_by)
- Invoice HAS MANY InvoiceLines
- Invoice HAS MANY Payments
- InvoiceLine REFERENCES Account (for GL mapping)
- FiscalPeriod BELONGS TO Tenant
- Payment REFERENCES Invoice
- Notification REFERENCES User

## State Machines

### Invoice Status State Machine

```
                    ┌──────────┐
                    │  draft   │
                    └────┬─────┘
                         │ submit
                    ┌────┴─────┐
                    │submitted │
                    └────┬─────┘
                    ┌────┴─────┐
             reject │          │ approve
            ┌───────┘          └────────┐
            ▼                           ▼
       ┌─────────┐              ┌──────────┐
       │ draft   │              │ approved │
       └─────────┘              └────┬─────┘
                                     │ post
                                ┌────┴─────┐
                                │  posted  │
                                └────┬─────┘
                           ┌─────────┤
                     pay   │         │ void
                    ┌──────┘         └──────┐
                    ▼                       ▼
               ┌─────────┐           ┌──────────┐
               │  paid   │           │  voided  │
               └─────────┘           └──────────┘
```

**Transitions:**
- draft → submitted: submit (requires at least 1 line item, valid amounts)
- submitted → approved: approve (requires user with approve_invoices permission)
- submitted → draft: reject (returns to draft with rejection reason)
- approved → posted: post (requires open fiscal period for invoice date, creates JournalEntry)
- posted → paid: pay (when paid_amount >= total, creates Payment record + JournalEntry)
- posted → voided: void (creates reversing JournalEntry, requires void_invoices permission)
- Partial payments: posted remains posted, tracks paid_amount incrementally

### Journal Entry Status State Machine

```
    ┌──────────┐
    │  draft   │
    └────┬─────┘
         │ submit_for_review
    ┌────┴──────────┐
    │pending_review │
    └────┬──────────┘
    ┌────┴─────┐
    │          │ approve
    │ reject   └────────┐
    ▼                    ▼
┌─────────┐       ┌──────────┐
│  draft  │       │ approved │
└─────────┘       └────┬─────┘
                       │ post
                  ┌────┴─────┐
                  │  posted  │
                  └────┬─────┘
                       │ reverse
                  ┌────┴──────┐
                  │ reversed  │
                  └───────────┘
```

**Transitions:**
- draft → pending_review: submit (requires balanced debits = credits)
- pending_review → approved: approve (requires different user than creator)
- pending_review → draft: reject (with reason)
- approved → posted: post (requires open fiscal period, updates account balances)
- posted → reversed: reverse (creates a new reversing entry with opposite debits/credits)

### Fiscal Period Status State Machine

```
    ┌──────────┐
    │   open   │
    └────┬─────┘
         │ initiate_close
    ┌────┴──────┐
    │  closing  │
    └────┬──────┘
    ┌────┴─────┐
    │          │ complete_close
    │ reopen   └────────┐
    ▼                    ▼
┌──────────┐       ┌──────────┐
│   open   │       │  closed  │
└──────────┘       └────┬─────┘
                        │ lock
                   ┌────┴─────┐
                   │  locked  │
                   └──────────┘
```

**Transitions:**
- open → closing: initiate_close (triggers validation — all entries must be posted or voided)
- closing → closed: complete_close (calculates period-end balances, generates closing entries for revenue/expense accounts)
- closing → open: reopen (if issues found during closing validation)
- closed → locked: lock (permanent, prevents any modifications — regulatory compliance)

## Service Contracts

### Synchronous (REST) — OpenAPI 3.1

#### auth-service API

```
POST   /api/auth/register          — Register new user
POST   /api/auth/login             — Login, receive JWT token
POST   /api/auth/refresh           — Refresh JWT token
GET    /api/auth/users             — List users (admin only)
GET    /api/auth/users/{id}        — Get user details
PUT    /api/auth/users/{id}        — Update user
POST   /api/auth/validate-token    — Validate JWT (service-to-service)
GET    /api/auth/users/{id}/permissions — Get user permissions
GET    /api/auth/tenants/{id}      — Get tenant config (currency, fiscal year start)
GET    /api/auth/health            — Health check
```

#### accounts-service API

```
GET    /api/accounts/chart                    — List chart of accounts (tree structure)
POST   /api/accounts/chart                    — Create account
GET    /api/accounts/chart/{id}               — Get account details
PUT    /api/accounts/chart/{id}               — Update account
DELETE /api/accounts/chart/{id}               — Deactivate account (soft delete)
GET    /api/accounts/chart/{id}/balance       — Get account balance for date range

POST   /api/accounts/journal-entries          — Create journal entry
GET    /api/accounts/journal-entries          — List journal entries (filterable)
GET    /api/accounts/journal-entries/{id}     — Get journal entry with lines
PUT    /api/accounts/journal-entries/{id}     — Update draft journal entry
POST   /api/accounts/journal-entries/{id}/submit    — Submit for review
POST   /api/accounts/journal-entries/{id}/approve   — Approve
POST   /api/accounts/journal-entries/{id}/reject    — Reject
POST   /api/accounts/journal-entries/{id}/post      — Post to ledger
POST   /api/accounts/journal-entries/{id}/reverse   — Reverse posted entry

GET    /api/accounts/fiscal-periods           — List fiscal periods
POST   /api/accounts/fiscal-periods           — Create fiscal period
POST   /api/accounts/fiscal-periods/{id}/close      — Initiate close
POST   /api/accounts/fiscal-periods/{id}/complete   — Complete close
POST   /api/accounts/fiscal-periods/{id}/reopen     — Reopen
POST   /api/accounts/fiscal-periods/{id}/lock       — Lock permanently

GET    /api/accounts/ledger                   — General ledger entries (filterable by account, date range)
GET    /api/accounts/audit-trail              — Audit trail entries (filterable)
GET    /api/accounts/health                   — Health check
```

#### invoicing-service API

```
POST   /api/invoices                    — Create invoice
GET    /api/invoices                    — List invoices (filterable by status, type, date)
GET    /api/invoices/{id}               — Get invoice with lines
PUT    /api/invoices/{id}               — Update draft invoice
DELETE /api/invoices/{id}               — Delete draft invoice
POST   /api/invoices/{id}/submit        — Submit for approval
POST   /api/invoices/{id}/approve       — Approve
POST   /api/invoices/{id}/reject        — Reject (returns to draft)
POST   /api/invoices/{id}/post          — Post (creates journal entry)
POST   /api/invoices/{id}/void          — Void (creates reversing entry)

POST   /api/invoices/{id}/payments      — Record payment
GET    /api/invoices/{id}/payments      — List payments for invoice

GET    /api/invoices/aging              — AR/AP aging report
GET    /api/invoices/summary            — Invoice summary statistics
GET    /api/invoices/health             — Health check
```

#### reporting-service API

```
GET    /api/reports/trial-balance       — Trial balance for date/period
GET    /api/reports/income-statement    — Profit & Loss for date range
GET    /api/reports/balance-sheet       — Balance sheet as of date
GET    /api/reports/cash-flow           — Cash flow statement
GET    /api/reports/general-ledger      — Detailed GL report
GET    /api/reports/aging               — Combined AR/AP aging
GET    /api/reports/journal-register    — Journal entry register
GET    /api/reports/account-activity/{id} — Activity for specific account
POST   /api/reports/export              — Export report to CSV/PDF
GET    /api/reports/dashboard           — Dashboard summary metrics
GET    /api/reports/health              — Health check
```

#### notification-service API

```
GET    /api/notifications               — List notifications for current user
GET    /api/notifications/unread-count  — Unread notification count
PUT    /api/notifications/{id}/read     — Mark as read
PUT    /api/notifications/read-all      — Mark all as read
GET    /api/notifications/preferences   — Get user notification preferences
PUT    /api/notifications/preferences   — Update preferences
GET    /api/notifications/health        — Health check
```

### Asynchronous (Events) — AsyncAPI 3.0

#### Events Published

| Event | Publisher | Payload | Consumers |
|-------|-----------|---------|-----------|
| user.created | auth-service | { user_id, email, tenant_id, role } | notification-service |
| user.role_changed | auth-service | { user_id, old_role, new_role, tenant_id } | notification-service |
| invoice.submitted | invoicing-service | { invoice_id, invoice_number, type, total, tenant_id, submitted_by } | notification-service |
| invoice.approved | invoicing-service | { invoice_id, invoice_number, type, total, tenant_id, approved_by } | accounts-service, notification-service |
| invoice.posted | invoicing-service | { invoice_id, invoice_number, type, total, account_mappings[], tenant_id } | accounts-service, reporting-service, notification-service |
| invoice.paid | invoicing-service | { invoice_id, payment_id, amount, method, tenant_id } | accounts-service, reporting-service, notification-service |
| invoice.voided | invoicing-service | { invoice_id, invoice_number, journal_entry_id, tenant_id, voided_by } | accounts-service, reporting-service, notification-service |
| journal.posted | accounts-service | { journal_entry_id, entry_number, total_amount, account_ids[], tenant_id } | reporting-service, notification-service |
| journal.reversed | accounts-service | { journal_entry_id, reversing_entry_id, tenant_id } | reporting-service, notification-service |
| period.closing | accounts-service | { period_id, period_name, tenant_id } | invoicing-service, reporting-service, notification-service |
| period.closed | accounts-service | { period_id, period_name, closing_balances, tenant_id } | reporting-service, notification-service |
| period.locked | accounts-service | { period_id, period_name, tenant_id } | invoicing-service, reporting-service, notification-service |
| payment.received | invoicing-service | { payment_id, invoice_id, amount, method, tenant_id } | accounts-service, notification-service |

#### Event Chains

**Chain 1: Invoice-to-Ledger**
```
invoicing → invoice.posted → accounts-service creates JournalEntry → journal.posted → reporting recalculates → notification sent to approver
```

**Chain 2: Payment Processing**
```
invoicing → payment.received → accounts-service creates payment JournalEntry → journal.posted → reporting updates cash position → notification sent to customer + accountant
```

**Chain 3: Period Close**
```
accounts → period.closing → invoicing freezes posting for period → reporting prepares period snapshot → notification sent to all accountants
accounts → period.closed → reporting generates period-end reports → notification sent to CFO
```

**Chain 4: Invoice Void Reversal**
```
invoicing → invoice.voided → accounts-service creates reversing JournalEntry → journal.reversed → reporting recalculates → notification sent to accountant + approver
```

## Cross-Service Interactions

### auth-service → all services
Every service validates JWT tokens by calling `POST /api/auth/validate-token`. The response includes `{ user_id, tenant_id, role, permissions[] }`. All services must include the `Authorization: Bearer <token>` header on cross-service calls.

### invoicing-service → accounts-service
When an invoice is posted, invoicing-service publishes `invoice.posted` with `account_mappings[]` (which invoice lines map to which GL accounts). accounts-service listens and creates a balanced JournalEntry with:
- For receivable invoices: DR Accounts Receivable, CR Revenue accounts per line
- For payable invoices: DR Expense accounts per line, CR Accounts Payable

### accounts-service → reporting-service
When a journal entry is posted (`journal.posted`), reporting-service updates its cached account balances and recalculates any active report views. reporting-service also reads from accounts-service's ledger API for on-demand report generation.

### invoicing-service → notification-service
All invoice state transitions trigger notifications — submitted (notify approver), approved (notify creator), posted (notify accountant), paid (notify customer via email + creator in-app), voided (notify original approver + accountant).

### accounts-service → invoicing-service
When a fiscal period enters "closing" or "locked" status, invoicing-service must prevent posting any new invoices dated within that period. This is enforced by subscribing to `period.closing` and `period.locked` events.

## User Roles and Permissions

| Role | Permissions |
|------|------------|
| admin | Full access to all features, user management, tenant configuration |
| accountant | Create/edit journal entries, manage chart of accounts, manage fiscal periods, post invoices, view all reports |
| accounts_payable | Create/edit payable invoices, record payments, view AP reports |
| accounts_receivable | Create/edit receivable invoices, record payments, view AR reports |
| auditor | Read-only access to all data, audit trail, all reports |
| viewer | Dashboard and basic report viewing only |

## Frontend Requirements

### Pages

1. **Login Page** — Email/password authentication, JWT storage
2. **Dashboard** — Key metrics: total revenue, total expenses, outstanding AR, outstanding AP, recent journal entries, recent invoices, period status indicators, quick-action buttons
3. **Chart of Accounts** — Tree view of account hierarchy, inline editing, drag-and-drop reordering, account type color coding, balance display
4. **General Ledger** — Searchable/filterable ledger entries, date range picker, account filter, export to CSV
5. **Journal Entries** — List view with status badges, create/edit form with dynamic line items (auto-balancing validation), approval workflow buttons, reversal form
6. **Invoices** — List view with status badges and type tabs (receivable/payable), create/edit form with line items, GL account mapping per line, approval workflow buttons, payment recording dialog, aging summary cards
7. **Payments** — Payment recording form, payment history per invoice, batch payment view
8. **Fiscal Periods** — Period list with status indicators, close/lock workflow, period balance summary
9. **Reports** — Trial balance, P&L, balance sheet, cash flow statement, journal register, account activity detail — all with date range selection, export options, print-friendly layout
10. **Notifications** — Notification center with badge count, mark as read, filter by type
11. **User Management** (admin only) — User list, role assignment, permission matrix
12. **Audit Trail** — Searchable audit log with entity type filter, user filter, date range filter, detail expansion

### Frontend Technical Requirements

- Angular 18 with standalone components
- PrimeNG component library for data tables, forms, dialogs, tree views
- Angular Material for supplementary components (date pickers, chips)
- NgRx or Angular signals for state management
- HTTP interceptor for JWT token injection and refresh
- Route guards for role-based access
- Reactive forms with real-time validation
- Responsive layout (desktop-first, tablet-compatible)
- Dark mode support
- Chart.js or ngx-charts for dashboard visualizations

## Non-Functional Requirements

### Security
- JWT token-based authentication with RS256 signing
- Refresh token rotation
- CORS restricted to frontend origin
- Rate limiting on auth endpoints (10 req/min for login)
- SQL injection prevention via parameterized queries
- XSS prevention via Angular's built-in sanitization
- CSRF protection via double-submit cookie
- No secrets in source code or environment variables logged
- Non-root Docker containers
- Read-only container filesystems where possible
- Bcrypt password hashing with salt rounds >= 12

### Observability
- Health endpoints on every service returning { status, uptime, database_connected }
- Structured JSON logging with correlation IDs
- W3C Trace Context (traceparent header) propagation across all service-to-service calls
- Request/response logging with PII redaction
- Prometheus-compatible metrics exposure (/metrics endpoint)

### Data Integrity
- Double-entry bookkeeping enforcement: every journal entry must balance (total debits = total credits)
- Immutable audit trail: append-only, no updates or deletes
- Foreign key enforcement across all tables
- Database migration scripts (Alembic for Python services, TypeORM migrations for NestJS)
- Transaction boundaries on all multi-table operations
- Optimistic locking on concurrent entity updates

### Performance
- N+1 query prevention: use eager loading / joins for related entities
- Database indexes on: account_code, invoice_number, journal_entry_date, tenant_id (all tables)
- Pagination on all list endpoints (default 50, max 200)
- Connection pooling for PostgreSQL
- Redis connection pooling for pub/sub

### Reliability
- Retry logic on all cross-service HTTP calls (3 retries, exponential backoff)
- Circuit breaker pattern on external service calls
- Timeout configuration on all HTTP clients (30s default)
- Graceful shutdown handling (drain connections, complete in-flight requests)
- Health check dependencies: each service reports database connectivity + Redis connectivity

### Docker
- Multi-stage builds for all services
- Non-root user in all containers
- Resource limits (CPU, memory) defined in docker-compose
- Health check commands in Dockerfiles
- .dockerignore files to minimize image size
- docker-compose with depends_on health conditions
- Traefik labels for automatic service discovery

## Seed Data

The system should include seed data for development/testing:

**Tenant:** "Acme Corp" with USD currency, January fiscal year start

**Users:**
- admin@acmecorp.com / Admin123! (admin role)
- accountant@acmecorp.com / Account123! (accountant role)
- ap.clerk@acmecorp.com / APClerk123! (accounts_payable role)
- ar.clerk@acmecorp.com / ARClerk123! (accounts_receivable role)
- auditor@acmecorp.com / Auditor123! (auditor role)
- viewer@acmecorp.com / Viewer123! (viewer role)

**Chart of Accounts:**
- Standard chart with ~40 accounts across 5 types:
  - Assets: Cash, Accounts Receivable, Inventory, Equipment, Accumulated Depreciation
  - Liabilities: Accounts Payable, Accrued Expenses, Notes Payable, Unearned Revenue
  - Equity: Owner's Equity, Retained Earnings, Dividends
  - Revenue: Sales Revenue, Service Revenue, Interest Income, Other Income
  - Expenses: COGS, Salaries, Rent, Utilities, Office Supplies, Depreciation, Insurance, Interest Expense

**Fiscal Periods:** 12 monthly periods for current year (January = closed, February = open, March-December = open)

**Sample Data:**
- 5 receivable invoices (1 draft, 1 submitted, 1 approved, 1 posted, 1 paid)
- 3 payable invoices (1 draft, 1 posted, 1 paid)
- 10 journal entries across various statuses
- Payment records for paid invoices
- Notification history

## Success Criteria

1. All 5 services start and pass health checks
2. User can register, login, and receive JWT token
3. Full chart of accounts CRUD with hierarchy display
4. Journal entry lifecycle: create → submit → approve → post → reverse
5. Invoice lifecycle: create → submit → approve → post → pay (and void path)
6. Fiscal period lifecycle: open → closing → closed → locked
7. Event-driven journal entry creation from invoice posting
8. Event-driven notification delivery on all state transitions
9. Fiscal period locking prevents invoice posting in locked periods
10. Trial balance, P&L, and balance sheet generate correct numbers
11. Audit trail records all entity changes with before/after values
12. Frontend displays all pages with correct data and working forms
13. Role-based access controls enforced in both backend and frontend
14. All cross-service calls include JWT authentication
15. Docker Compose deploys all services with Traefik routing

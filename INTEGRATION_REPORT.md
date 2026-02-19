# Integration Pipeline Verification Report

**Generated:** 2026-02-16T18:18:03.887180+00:00
**PRDs tested:** 5

## Summary Matrix

| Check | PRD 1 | PRD 2 | PRD 3 | PRD 4 | PRD 5 |
|-------|------|------|------|------|------|
| 1. parse_prd() succeeds | PASS | PASS | PASS | PASS | PASS |
| 2. Entity count reasonable (FP<=80%) | PASS | PASS | PASS | PASS | PASS |
| 3. identify_boundaries() >= 1 | PASS | PASS | PASS | PASS | PASS |
| 4. build_service_map() no crash | PASS | FAIL | FAIL | FAIL | PASS |
| 5. Service count matches (range) | PASS | PASS | PASS | PASS | PASS |
| 6. build_domain_model() entities+rels | PASS | PASS | PASS | PASS | PASS |
| 7. generate_contract_stubs() valid | PASS | PASS | PASS | PASS | PASS |
| 8. Contracts stored successfully | PASS | PASS | PASS | PASS | PASS |
| 9. Test gen produces compilable code | PASS | PASS | PASS | PASS | PASS |
| 10. No unhandled exception | PASS | FAIL | FAIL | FAIL | PASS |

**Overall: 44/50 checks passed (88.0%)**

## Known Issues Found During Integration

### Issue 1: `build_service_map()` crashes when `language` is `None`

**Affected PRDs:** PRD 2 (ShopSimple), PRD 3 (QuickChat), PRD 4 (HelloAPI)

**Root cause:** In `src/architect/services/service_boundary.py:378-379`,
`hints.get('language', 'python')` returns `None` because the key exists in the dict
but its value is `None`. The default `'python'` is only used when the key is missing.
`ServiceStack(language=None)` fails Pydantic validation since `language: str` is not optional.

**Fix:** Change `hints.get('language', 'python')` to `hints.get('language') or 'python'`.

### Issue 2: Entity extraction false positives

**Affected PRDs:** All 5 PRDs show entity extraction false positives.

**Root cause:** The PRD parser's heading-based entity extraction (Strategy 2)
picks up headings like 'Auth Service', 'Project Overview', 'User Entity', etc. as entities.
These are section headings describing services or entity definitions, not actual domain entities.

**Examples of false positives:**
- `ProjectOverview`, `ProjectName` (project-level headings)
- `AuthService`, `TaskService`, `NotificationService` (service headings)
- `UserEntity`, `TaskEntity`, `GreetingEntity` (entity definition headings)
- `TaskStatusStateMachine`, `OrderStateMachine` (state machine headings)

**Impact:** False positive entities end up in a 'Miscellaneous' service boundary,
inflating the entity count and generating unnecessary CRUD endpoints.
The real domain entities ARE still correctly extracted and assigned.

### Issue 3: State machines not detected for Task/Order/Appointment

**Affected PRDs:** PRD 1, 2, 5 (entities with explicit state machine definitions)

**Root cause:** The arrow-notation state machine parser (`Strategy 3` in `_extract_state_machines`)
requires the pattern `<Entity> status/state: state1 -> state2`. The PRDs use a separate heading
like `#### Task Status State Machine` followed by transition lines, which doesn't match the regex.

## Detailed Results

### PRD 1: TaskTracker

**1. parse_prd() succeeds:** `PASS`
> project=TaskTracker PRD, entities=12, relationships=2, contexts=3, tech_hints={'language': 'Python', 'framework': 'FastAPI', 'database': 'PostgreSQL', 'message_broker': 'RabbitMQ', 'auth': 'jwt'}, state_machines=0

**2. Entity count reasonable (FP<=80%):** `PASS`
> Total entities: 12, real found: 3/3, false positives: 9 (75%). All expected found: True. Real: ['User', 'Task', 'Notification'], FP: ['ProjectOverview', 'AuthService', 'UserEntity', 'TaskService', 'TaskEntity', 'TaskStatusStateMachine', 'NotificationService', 'NotificationEntity', 'ProjectName']

**3. identify_boundaries() >= 1:** `PASS`
> Found 4 boundaries: [('Auth Service', ['User', 'Task']), ('Task Service', ['Notification']), ('Notification Service', []), ('Miscellaneous', ['AuthService', 'NotificationEntity', 'NotificationService', 'ProjectName', 'ProjectOverview', 'TaskEntity', 'TaskService', 'TaskStatusStateMachine', 'UserEntity'])]

**4. build_service_map() no crash:** `PASS`
> project=TaskTracker PRD, services=4, prd_hash=428f9e41e5fc...

**5. Service count matches (range):** `PASS`
> Expected [3, 5], got 4. Services: ['auth-service', 'task-service', 'notification-service', 'miscellaneous']

**6. build_domain_model() entities+rels:** `PASS`
> entities=12, relationships=2, state_machines=0

**7. generate_contract_stubs() valid:** `PASS`
> Generated 4 specs, all valid OpenAPI=True. Total paths: 25

**8. Contracts stored successfully:** `PASS`
> Stored 4 contracts: [('auth-service', '8242372d'), ('task-service', '72138148'), ('notification-service', '90442eee'), ('miscellaneous', '79f49bd9')]

**9. Test gen produces compilable code:** `PASS`
> Generated 4 suites, total tests=114, all_have_code=True, all_compilable=True

**10. No unhandled exception:** `PASS`
> Full pipeline completed successfully without any exceptions.

---

### PRD 2: ShopSimple (no tech hints)

**1. parse_prd() succeeds:** `PASS`
> project=ShopSimple PRD, entities=12, relationships=2, contexts=3, tech_hints={'language': None, 'framework': None, 'database': None, 'message_broker': None}, state_machines=0

**2. Entity count reasonable (FP<=80%):** `PASS`
> Total entities: 12, real found: 3/3, false positives: 9 (75%). All expected found: True. Real: ['UserAccount', 'Product', 'Order'], FP: ['ProjectOverview', 'UserAccountService', 'UseraccountEntity', 'ProductCatalogService', 'ProductEntity', 'OrderService', 'OrderEntity', 'OrderStateMachine', 'ProjectName']

**3. identify_boundaries() >= 1:** `PASS`
> Found 4 boundaries: [('User Account Service', ['UserAccount', 'Product', 'Order']), ('Product Catalog Service', []), ('Order Service', []), ('Miscellaneous', ['OrderEntity', 'OrderService', 'OrderStateMachine', 'ProductCatalogService', 'ProductEntity', 'ProjectName', 'ProjectOverview', 'UserAccountService', 'UseraccountEntity'])]

**4. build_service_map() no crash:** `FAIL`
> EXCEPTION: ValidationError: 1 validation error for ServiceStack
> language
>   Input should be a valid string [type=string_type, input_value=None, input_type=NoneType]
>     For further information visit https://errors.pydantic.dev/2.11/v/string_type
>   ** KNOWN BUG: build_service_map() crashes when technology_hints['language'] is None. ServiceStack(language=None) fails validation. hints.get('language', 'python') returns None because the key exists with None value. Fix: use `hints.get('language') or 'python'`.
> Traceback (most recent call last):
>   File "C:\Users\Omar Khaled\OneDrive\Desktop\super-team\test_integration_pipeline.py", line 422, in run_pipeline
>     service_map = build_service_map(parsed, boundaries)
>                   ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
>   File "C:\Users\Omar Khaled\OneDrive\Desktop\super-team\src\architect\services\service_boundary.py", line 378, in build_service_map
>     stack = ServiceStack(
>             ^^^^^^^^^^^^^
>   File "C:\Users\Omar Khaled\AppData\Roaming\Python\Python311\site-packages\pydantic\main.py", line 253, in __init__
>     validated_self = self.__pydantic_validator__.validate_python(data, self_instance=self)
>                      ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
> pydantic_core._pydantic_core.ValidationError: 1 validation error for ServiceStack
> language
>   Input should be a valid string [type=string_type, input_value=None, input_type=NoneType]
>     For further information visit https://errors.pydantic.dev/2.11/v/string_type
> 
>   ** WORKAROUND APPLIED: Manually set language='python' to test remaining steps.

**5. Service count matches (range):** `PASS`
> Expected [3, 5], got 4. Services: ['user-account-service', 'product-catalog-service', 'order-service', 'miscellaneous']

**6. build_domain_model() entities+rels:** `PASS`
> entities=12, relationships=2, state_machines=0

**7. generate_contract_stubs() valid:** `PASS`
> Generated 4 specs, all valid OpenAPI=True. Total paths: 26

**8. Contracts stored successfully:** `PASS`
> Stored 4 contracts: [('user-account-service', '69dea46d'), ('product-catalog-service', '94c5d401'), ('order-service', '51b1082f'), ('miscellaneous', '79f49bd9')]

**9. Test gen produces compilable code:** `PASS`
> Generated 4 suites, total tests=116, all_have_code=True, all_compilable=True

**10. No unhandled exception:** `FAIL`
> Pipeline had an error at build_service_map (language=None bug) but remaining steps completed with workaround.

---

### PRD 3: QuickChat (WebSocket)

**1. parse_prd() succeeds:** `PASS`
> project=QuickChat PRD, entities=9, relationships=3, contexts=2, tech_hints={'language': None, 'framework': None, 'database': None, 'message_broker': None, 'auth': 'jwt', 'api_style': 'rest', 'messaging': 'websocket'}, state_machines=0

**2. Entity count reasonable (FP<=80%):** `PASS`
> Total entities: 9, real found: 3/3, false positives: 6 (67%). All expected found: True. Real: ['ChatUser', 'ChatRoom', 'Message'], FP: ['ProjectOverview', 'AuthService', 'ChatuserEntity', 'ChatService', 'ChatroomEntity', 'MessageEntity']

**3. identify_boundaries() >= 1:** `PASS`
> Found 3 boundaries: [('Auth Service', ['ChatUser', 'ChatRoom', 'Message']), ('Chat Service', []), ('Miscellaneous', ['AuthService', 'ChatService', 'ChatroomEntity', 'ChatuserEntity', 'MessageEntity', 'ProjectOverview'])]

**4. build_service_map() no crash:** `FAIL`
> EXCEPTION: ValidationError: 1 validation error for ServiceStack
> language
>   Input should be a valid string [type=string_type, input_value=None, input_type=NoneType]
>     For further information visit https://errors.pydantic.dev/2.11/v/string_type
>   ** KNOWN BUG: build_service_map() crashes when technology_hints['language'] is None. ServiceStack(language=None) fails validation. hints.get('language', 'python') returns None because the key exists with None value. Fix: use `hints.get('language') or 'python'`.
> Traceback (most recent call last):
>   File "C:\Users\Omar Khaled\OneDrive\Desktop\super-team\test_integration_pipeline.py", line 422, in run_pipeline
>     service_map = build_service_map(parsed, boundaries)
>                   ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
>   File "C:\Users\Omar Khaled\OneDrive\Desktop\super-team\src\architect\services\service_boundary.py", line 378, in build_service_map
>     stack = ServiceStack(
>             ^^^^^^^^^^^^^
>   File "C:\Users\Omar Khaled\AppData\Roaming\Python\Python311\site-packages\pydantic\main.py", line 253, in __init__
>     validated_self = self.__pydantic_validator__.validate_python(data, self_instance=self)
>                      ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
> pydantic_core._pydantic_core.ValidationError: 1 validation error for ServiceStack
> language
>   Input should be a valid string [type=string_type, input_value=None, input_type=NoneType]
>     For further information visit https://errors.pydantic.dev/2.11/v/string_type
> 
>   ** WORKAROUND APPLIED: Manually set language='python' to test remaining steps.

**5. Service count matches (range):** `PASS`
> Expected [2, 4], got 3. Services: ['auth-service', 'chat-service', 'miscellaneous']

**6. build_domain_model() entities+rels:** `PASS`
> entities=9, relationships=3, state_machines=0

**7. generate_contract_stubs() valid:** `PASS`
> Generated 3 specs, all valid OpenAPI=True. Total paths: 19

**8. Contracts stored successfully:** `PASS`
> Stored 3 contracts: [('auth-service', '8242372d'), ('chat-service', '5afc7d0f'), ('miscellaneous', '79f49bd9')]

**9. Test gen produces compilable code:** `PASS`
> Generated 3 suites, total tests=86, all_have_code=True, all_compilable=True

**10. No unhandled exception:** `FAIL`
> Pipeline had an error at build_service_map (language=None bug) but remaining steps completed with workaround.

---

### PRD 4: HelloAPI (minimal)

**1. parse_prd() succeeds:** `PASS`
> project=HelloAPI PRD, entities=4, relationships=0, contexts=1, tech_hints={'language': None, 'framework': None, 'database': None, 'message_broker': None, 'api_style': 'rest'}, state_machines=0

**2. Entity count reasonable (FP<=80%):** `PASS`
> Total entities: 4, real found: 1/1, false positives: 3 (75%). All expected found: True. Real: ['Greeting'], FP: ['ProjectOverview', 'HelloService', 'GreetingEntity']

**3. identify_boundaries() >= 1:** `PASS`
> Found 2 boundaries: [('Hello Service', ['Greeting']), ('Miscellaneous', ['GreetingEntity', 'HelloService', 'ProjectOverview'])]

**4. build_service_map() no crash:** `FAIL`
> EXCEPTION: ValidationError: 1 validation error for ServiceStack
> language
>   Input should be a valid string [type=string_type, input_value=None, input_type=NoneType]
>     For further information visit https://errors.pydantic.dev/2.11/v/string_type
>   ** KNOWN BUG: build_service_map() crashes when technology_hints['language'] is None. ServiceStack(language=None) fails validation. hints.get('language', 'python') returns None because the key exists with None value. Fix: use `hints.get('language') or 'python'`.
> Traceback (most recent call last):
>   File "C:\Users\Omar Khaled\OneDrive\Desktop\super-team\test_integration_pipeline.py", line 422, in run_pipeline
>     service_map = build_service_map(parsed, boundaries)
>                   ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
>   File "C:\Users\Omar Khaled\OneDrive\Desktop\super-team\src\architect\services\service_boundary.py", line 378, in build_service_map
>     stack = ServiceStack(
>             ^^^^^^^^^^^^^
>   File "C:\Users\Omar Khaled\AppData\Roaming\Python\Python311\site-packages\pydantic\main.py", line 253, in __init__
>     validated_self = self.__pydantic_validator__.validate_python(data, self_instance=self)
>                      ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
> pydantic_core._pydantic_core.ValidationError: 1 validation error for ServiceStack
> language
>   Input should be a valid string [type=string_type, input_value=None, input_type=NoneType]
>     For further information visit https://errors.pydantic.dev/2.11/v/string_type
> 
>   ** WORKAROUND APPLIED: Manually set language='python' to test remaining steps.

**5. Service count matches (range):** `PASS`
> Expected [1, 3], got 2. Services: ['hello-service', 'miscellaneous']

**6. build_domain_model() entities+rels:** `PASS`
> entities=4, relationships=0, state_machines=0

**7. generate_contract_stubs() valid:** `PASS`
> Generated 2 specs, all valid OpenAPI=True. Total paths: 8

**8. Contracts stored successfully:** `PASS`
> Stored 2 contracts: [('hello-service', '73fcbee5'), ('miscellaneous', '79f49bd9')]

**9. Test gen produces compilable code:** `PASS`
> Generated 2 suites, total tests=38, all_have_code=True, all_compilable=True

**10. No unhandled exception:** `FAIL`
> Pipeline had an error at build_service_map (language=None bug) but remaining steps completed with workaround.

---

### PRD 5: HealthTrack (complex)

**1. parse_prd() succeeds:** `PASS`
> project=HealthTrack PRD, entities=21, relationships=3, contexts=6, tech_hints={'language': 'Python', 'framework': 'FastAPI', 'database': 'PostgreSQL', 'message_broker': None, 'notification': 'sms'}, state_machines=0

**2. Entity count reasonable (FP<=80%):** `PASS`
> Total entities: 21, real found: 6/6, false positives: 15 (71%). All expected found: True. Real: ['Patient', 'Provider', 'Appointment', 'Invoice', 'NotificationRecord', 'AuditLog'], FP: ['ProjectOverview', 'PatientService', 'PatientEntity', 'ProviderService', 'ProviderEntity', 'AppointmentService', 'AppointmentEntity', 'AppointmentStateMachine', 'BillingService', 'InvoiceEntity', 'NotificationService', 'NotificationrecordEntity', 'AuditService', 'AuditlogEntity', 'ProjectName']

**3. identify_boundaries() >= 1:** `PASS`
> Found 7 boundaries: [('Patient Service', ['Patient', 'Provider', 'Appointment']), ('Provider Service', []), ('Appointment Service', []), ('Billing Service', ['Invoice', 'NotificationRecord', 'AuditLog']), ('Notification Service', []), ('Audit Service', []), ('Miscellaneous', ['AppointmentEntity', 'AppointmentService', 'AppointmentStateMachine', 'AuditService', 'AuditlogEntity', 'BillingService', 'InvoiceEntity', 'NotificationService', 'NotificationrecordEntity', 'PatientEntity', 'PatientService', 'ProjectName', 'ProjectOverview', 'ProviderEntity', 'ProviderService'])]

**4. build_service_map() no crash:** `PASS`
> project=HealthTrack PRD, services=7, prd_hash=11857fc1b92b...

**5. Service count matches (range):** `PASS`
> Expected [5, 8], got 7. Services: ['patient-service', 'provider-service', 'appointment-service', 'billing-service', 'notification-service', 'audit-service', 'miscellaneous']

**6. build_domain_model() entities+rels:** `PASS`
> entities=21, relationships=3, state_machines=0

**7. generate_contract_stubs() valid:** `PASS`
> Generated 7 specs, all valid OpenAPI=True. Total paths: 46

**8. Contracts stored successfully:** `PASS`
> Stored 7 contracts: [('patient-service', '3c01c410'), ('provider-service', '50f8c594'), ('appointment-service', 'cdaa8848'), ('billing-service', '9199585d'), ('notification-service', '90442eee'), ('audit-service', '3fe7250e'), ('miscellaneous', '79f49bd9')]

**9. Test gen produces compilable code:** `PASS`
> Generated 7 suites, total tests=204, all_have_code=True, all_compilable=True

**10. No unhandled exception:** `PASS`
> Full pipeline completed successfully without any exceptions.

---

## Verdict

**44/50 checks passed (88.0%)**

6 checks failed. Key blockers:

1. **Critical:** `build_service_map()` crashes for PRDs without tech hints (language=None)
   - Affects 3/5 PRDs. Fix: `hints.get('language') or 'python'`
   - With workaround applied, all subsequent pipeline steps succeed

2. **Moderate:** Entity extraction false positives (all 5 PRDs)
   - The parser correctly finds real entities but also extracts section headings
   - Words like 'Service', 'Entity', 'State Machine' in headings need filtering

3. **Minor:** State machine detection misses heading-separated definitions
   - State machines in separate `#### ... State Machine` sections not detected
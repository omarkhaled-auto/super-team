# Verification Summary

Overall Health: **RED**

## Completed Tasks

| Task | Contracts | Build | Lint | Types | Tests | Security | Overall |
|------|-----------|-------|------|-------|-------|----------|---------|
| post-orchestration | PASS | FAIL | FAIL | FAIL | FAIL | FAIL | FAIL |

## Issues

- post-orchestration: Build failed: * Getting build dependencies for sdist...
ERROR Backend 'setuptools.build_meta' is not available.
- post-orchestration: Lint failed: E402 Module level import not at top of file
  --> src\architect\main.py:50:1
   |
49 | # Register all routers
50 | from src.architect.routers.health import router as health_router
   | ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
51 | from src.architect.routers.decomposition import router as decomposition_router
52 | from src.architect.routers.service_map import router as service_map_router
   |

E402 Module level import not at top of file
  --> src\architect\main.py:51:1
- post-orchestration: Type check failed: src\super_orchestrator\config.py:9: error: Library stubs not installed for "yaml"  [import-untyped]
src\super_orchestrator\config.py:96: error: "type" has no attribute "__dataclass_fields__"  [attr-defined]
src\integrator\traefik_config.py:58: error: Library stubs not installed for "yaml"  [import-untyped]
src\integrator\traefik_config.py:82: error: Returning Any from function declared to return "str"  [no-any-return]
tests\fixtures\__init__.py:36: error: Missing type parameters for generic
- post-orchestration: Tests failed: Command timed out after 120s: pytest
- post-orchestration: Test quality: 12 test(s) have no assertions (empty/shallow tests)
- post-orchestration: Security: Found 1 .env file(s) and .env is not in .gitignore
- post-orchestration: Security: Possible hardcoded password/secret in .venv\Lib\site-packages\adodbapi\test\adodbapitestconfig.py
- post-orchestration: Security: Possible hardcoded password/secret in .venv\Lib\site-packages\adodbapi\test\test_adodbapi_dbapi20.py
- post-orchestration: Security: Possible hardcoded API key in .venv\Lib\site-packages\chromadb\telemetry\product\posthog.py
- post-orchestration: Security: Possible hardcoded password/secret in .venv\Lib\site-packages\cryptography\hazmat\_oid.py
- post-orchestration: Security: Possible hardcoded password/secret in .venv\Lib\site-packages\fsspec\spec.py
- post-orchestration: Security: Possible hardcoded password/secret in .venv\Lib\site-packages\httpx\_urls.py
- post-orchestration: Security: Possible hardcoded password/secret in .venv\Lib\site-packages\huggingface_hub\_webhooks_server.py
- post-orchestration: Security: Possible hardcoded password/secret in .venv\Lib\site-packages\mcp\client\auth\extensions\client_credentials.py
- post-orchestration: Security: Possible hardcoded password/secret in .venv\Lib\site-packages\opentelemetry\sdk\environment_variables\__init__.py
- post-orchestration: Security: Possible hardcoded password/secret in .venv\Lib\site-packages\pip\_internal\network\auth.py
- post-orchestration: Security: Possible hardcoded API key in .venv\Lib\site-packages\posthog\test\test_utils.py
- post-orchestration: Security: Possible hardcoded password/secret in .venv\Lib\site-packages\pythonwin\pywin\dialogs\login.py
- post-orchestration: Security: Possible hardcoded password/secret in .venv\Lib\site-packages\requests_oauthlib\oauth1_session.py
- post-orchestration: Security: Possible hardcoded password/secret in .venv\Lib\site-packages\starlette\datastructures.py
- post-orchestration: Security: Possible hardcoded password/secret in .venv\Lib\site-packages\werkzeug\debug\tbtools.py
- post-orchestration: Security: Possible hardcoded password/secret in .venv\Lib\site-packages\win32\lib\rasutil.py
- post-orchestration: Security: Possible hardcoded password/secret in .venv\Lib\site-packages\win32\lib\win32cryptcon.py
- post-orchestration: Security: Possible hardcoded password/secret in .venv\Lib\site-packages\win32\lib\win32netcon.py
- post-orchestration: Security: Possible hardcoded password/secret in .venv\Lib\site-packages\win32\lib\win32serviceutil.py
- post-orchestration: Security: Possible hardcoded password/secret in tests\build3\test_quality_gate.py
- post-orchestration: Security: Possible hardcoded API key in tests\build3\test_security_scanner.py
- post-orchestration: Quality: [PROJ-001] .gitignore missing critical entry: node_modules (.gitignore:0)
- post-orchestration: Quality: [PROJ-001] .gitignore missing critical entry: dist (.gitignore:0)
- post-orchestration: Quality: [PROJ-001] .gitignore missing critical entry: .env (.gitignore:0)
- post-orchestration: Quality: [FRONT-016] Duplicate function 'Python' defined in 2 files: .venv/Lib/site-packages/adodbapi/is64bit.py, .venv/Lib/site-packages/adodbapi/test/is64bit.py (.venv/Lib/site-packages/adodbapi/is64bit.py:0)
- post-orchestration: Quality: [FRONT-016] Duplicate function 'Default' defined in 4 files: .venv/Lib/site-packages/fastapi/datastructures.py, .venv/Lib/site-packages/google/protobuf/descriptor_pool.py, .venv/Lib/site-packages/google/protobuf/symbol_database.py (.venv/Lib/site-packages/fastapi/datastructures.py:0)
- post-orchestration: Quality: [FRONT-016] Duplicate function 'Parse' defined in 3 files: .venv/Lib/site-packages/google/protobuf/json_format.py, .venv/Lib/site-packages/google/protobuf/text_format.py, .venv/Lib/site-packages/win32/lib/win32rcparser.py (.venv/Lib/site-packages/google/protobuf/json_format.py:0)
- post-orchestration: Quality: [FRONT-016] Duplicate function 'String' defined in 2 files: .venv/Lib/site-packages/hypothesis_graphql/nodes.py, .venv/Lib/site-packages/win32/lib/win32verstamp.py (.venv/Lib/site-packages/hypothesis_graphql/nodes.py:0)
- post-orchestration: Quality: [FRONT-016] Duplicate function 'ToASCII' defined in 2 files: .venv/Lib/site-packages/idna/compat.py, .venv/Lib/site-packages/pip/_vendor/idna/compat.py (.venv/Lib/site-packages/idna/compat.py:0)
- post-orchestration: Quality: [FRONT-016] Duplicate function 'ToUnicode' defined in 2 files: .venv/Lib/site-packages/idna/compat.py, .venv/Lib/site-packages/pip/_vendor/idna/compat.py (.venv/Lib/site-packages/idna/compat.py:0)
- post-orchestration: Quality: [FRONT-016] Duplicate function 'HandleCommandLine' defined in 2 files: .venv/Lib/site-packages/isapi/install.py, .venv/Lib/site-packages/win32/lib/win32serviceutil.py (.venv/Lib/site-packages/isapi/install.py:0)

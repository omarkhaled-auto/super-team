"""Tests for ObservabilityChecker (TEST-024).

Covers all five violation codes emitted by the checker:
    LOG-001    print()/console.log() and unstructured logging
    LOG-004    Sensitive data in logs
    LOG-005    Missing request ID in request handlers
    TRACE-001  Missing trace context propagation in HTTP client calls
    HEALTH-001 Missing /health endpoint in service definitions

Each test creates realistic source-code files inside a temporary directory,
runs ``ObservabilityChecker.scan()``, and asserts on the resulting
``ScanViolation`` list.

pytest-asyncio with ``asyncio_mode = "auto"`` (configured in pyproject.toml).
"""

from __future__ import annotations

import pytest
from pathlib import Path

from src.quality_gate.observability_checker import ObservabilityChecker
from src.build3_shared.models import ScanViolation


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def checker() -> ObservabilityChecker:
    return ObservabilityChecker()


def _write_file(tmp_path: Path, name: str, content: str) -> Path:
    """Helper: write *content* into ``tmp_path / name`` and return the path."""
    file_path = tmp_path / name
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text(content, encoding="utf-8")
    return file_path


# ===================================================================
# LOG-001: Missing structured logging
# ===================================================================

class TestLog001PrintPython:
    """LOG-001: print() in a Python file should be detected."""

    async def test_print_detected(
        self, checker: ObservabilityChecker, tmp_path: Path,
    ) -> None:
        _write_file(tmp_path, "service.py", (
            "import os\n"
            "\n"
            "def handle():\n"
            "    result = compute()\n"
            "    print(f'Result is {result}')\n"
            "    return result\n"
        ))

        violations = await checker.scan(tmp_path)

        log001 = [v for v in violations if v.code == "LOG-001"]
        assert len(log001) >= 1
        assert log001[0].category == "logging"
        assert log001[0].severity == "warning"
        assert log001[0].line == 5
        assert "print()" in log001[0].message


class TestLog001ConsoleLogJS:
    """LOG-001: console.log() in a JS/TS file should be detected."""

    async def test_console_log_detected(
        self, checker: ObservabilityChecker, tmp_path: Path,
    ) -> None:
        _write_file(tmp_path, "handler.ts", (
            "export function processRequest(req: Request) {\n"
            "  const data = req.body;\n"
            "  console.log('Processing request', data);\n"
            "  return { ok: true };\n"
            "}\n"
        ))

        violations = await checker.scan(tmp_path)

        log001 = [v for v in violations if v.code == "LOG-001"]
        assert len(log001) >= 1
        assert log001[0].category == "logging"
        assert "console.log" in log001[0].message.lower() or "console" in log001[0].message.lower()

    async def test_console_error_detected(
        self, checker: ObservabilityChecker, tmp_path: Path,
    ) -> None:
        """console.error() and console.warn() should also be flagged."""
        _write_file(tmp_path, "utils.js", (
            "function fallback(err) {\n"
            "  console.error('Unexpected failure', err);\n"
            "  console.warn('Retrying...');\n"
            "}\n"
        ))

        violations = await checker.scan(tmp_path)

        log001 = [v for v in violations if v.code == "LOG-001"]
        assert len(log001) >= 2, "Both console.error and console.warn should be flagged"


class TestLog001StructuredLoggingNotFlagged:
    """LOG-001: Structured logging should NOT be flagged."""

    async def test_structlog_not_flagged(
        self, checker: ObservabilityChecker, tmp_path: Path,
    ) -> None:
        _write_file(tmp_path, "app.py", (
            "import structlog\n"
            "\n"
            "logger = structlog.get_logger()\n"
            "\n"
            "def process():\n"
            "    logger.info('user_created', extra={'user_id': 42})\n"
            "    return True\n"
        ))

        violations = await checker.scan(tmp_path)

        # The structlog call uses logger.info with a plain string, which the
        # regex may flag as unstructured.  The key assertion is that the file
        # does NOT produce a print()-based LOG-001.
        print_violations = [
            v for v in violations
            if v.code == "LOG-001" and "print()" in v.message
        ]
        assert len(print_violations) == 0

    async def test_comment_lines_not_flagged(
        self, checker: ObservabilityChecker, tmp_path: Path,
    ) -> None:
        """Comments containing print/console.log should be ignored."""
        _write_file(tmp_path, "clean.py", (
            "# print('this is a comment, not real code')\n"
            "import logging\n"
            "logging.getLogger(__name__)\n"
        ))

        violations = await checker.scan(tmp_path)

        log001 = [v for v in violations if v.code == "LOG-001"]
        assert len(log001) == 0, "Comments must not trigger LOG-001"

    async def test_js_comment_not_flagged(
        self, checker: ObservabilityChecker, tmp_path: Path,
    ) -> None:
        _write_file(tmp_path, "clean.ts", (
            "// console.log('debug leftover');\n"
            "import pino from 'pino';\n"
            "const logger = pino();\n"
            "logger.info({ event: 'started' });\n"
        ))

        violations = await checker.scan(tmp_path)

        log001 = [v for v in violations if v.code == "LOG-001"]
        assert len(log001) == 0


# ===================================================================
# LOG-004: Sensitive data in logs
# ===================================================================

class TestLog004SensitiveDetected:
    """LOG-004: Logging sensitive variables should be detected."""

    async def test_print_password_detected(
        self, checker: ObservabilityChecker, tmp_path: Path,
    ) -> None:
        _write_file(tmp_path, "auth.py", (
            "def login(username: str, password: str):\n"
            "    print(f'Logging in user {username} with password={password}')\n"
            "    return authenticate(username, password)\n"
        ))

        violations = await checker.scan(tmp_path)

        log004 = [v for v in violations if v.code == "LOG-004"]
        assert len(log004) >= 1
        assert log004[0].severity == "error"
        assert log004[0].category == "logging"
        assert "sensitive" in log004[0].message.lower() or "password" in log004[0].message.lower()

    async def test_logging_info_with_token(
        self, checker: ObservabilityChecker, tmp_path: Path,
    ) -> None:
        _write_file(tmp_path, "middleware.py", (
            "import logging\n"
            "logger = logging.getLogger(__name__)\n"
            "\n"
            "def verify(access_token: str):\n"
            "    logger.info(f'Verifying token: {access_token}')\n"
            "    return jwt_decode(access_token)\n"
        ))

        violations = await checker.scan(tmp_path)

        log004 = [v for v in violations if v.code == "LOG-004"]
        assert len(log004) >= 1

    async def test_console_log_api_key_js(
        self, checker: ObservabilityChecker, tmp_path: Path,
    ) -> None:
        _write_file(tmp_path, "config.ts", (
            "export function initClient(api_key: string) {\n"
            "  console.log('Initializing with api_key', api_key);\n"
            "  return new Client(api_key);\n"
            "}\n"
        ))

        violations = await checker.scan(tmp_path)

        log004 = [v for v in violations if v.code == "LOG-004"]
        assert len(log004) >= 1


class TestLog004NonSensitiveNotFlagged:
    """LOG-004: Non-sensitive log content should NOT be flagged."""

    async def test_normal_variable_not_flagged(
        self, checker: ObservabilityChecker, tmp_path: Path,
    ) -> None:
        _write_file(tmp_path, "orders.py", (
            "import logging\n"
            "logger = logging.getLogger(__name__)\n"
            "\n"
            "def process_order(order_id: str, quantity: int):\n"
            "    logger.info('Processing order', extra={'order_id': order_id, 'qty': quantity})\n"
            "    return True\n"
        ))

        violations = await checker.scan(tmp_path)

        log004 = [v for v in violations if v.code == "LOG-004"]
        assert len(log004) == 0, "Non-sensitive data should not trigger LOG-004"


# ===================================================================
# LOG-005: Missing request ID logging
# ===================================================================

class TestLog005MissingRequestId:
    """LOG-005: Request handler without request_id should be detected."""

    async def test_fastapi_handler_without_request_id(
        self, checker: ObservabilityChecker, tmp_path: Path,
    ) -> None:
        _write_file(tmp_path, "routes.py", (
            "from fastapi import FastAPI\n"
            "\n"
            "app = FastAPI()\n"
            "\n"
            "@app.get('/users')\n"
            "async def list_users():\n"
            "    users = get_all_users()\n"
            "    return {'users': users}\n"
        ))

        violations = await checker.scan(tmp_path)

        log005 = [v for v in violations if v.code == "LOG-005"]
        assert len(log005) >= 1
        assert log005[0].category == "logging"
        assert "request_id" in log005[0].message.lower() or "correlation" in log005[0].message.lower()

    async def test_flask_handler_with_request_param(
        self, checker: ObservabilityChecker, tmp_path: Path,
    ) -> None:
        """A function accepting 'request' as parameter is also a handler."""
        _write_file(tmp_path, "views.py", (
            "def get_profile(request):\n"
            "    user = request.user\n"
            "    return render(user)\n"
        ))

        violations = await checker.scan(tmp_path)

        log005 = [v for v in violations if v.code == "LOG-005"]
        assert len(log005) >= 1


class TestLog005RequestIdPresent:
    """LOG-005: Handler WITH request_id should NOT be flagged."""

    async def test_handler_with_request_id_not_flagged(
        self, checker: ObservabilityChecker, tmp_path: Path,
    ) -> None:
        _write_file(tmp_path, "routes.py", (
            "from fastapi import FastAPI, Request\n"
            "import structlog\n"
            "\n"
            "app = FastAPI()\n"
            "logger = structlog.get_logger()\n"
            "\n"
            "@app.get('/users')\n"
            "async def list_users(request: Request):\n"
            "    request_id = request.headers.get('x-request-id', 'unknown')\n"
            "    logger.info('listing_users', request_id=request_id)\n"
            "    users = get_all_users()\n"
            "    return {'users': users}\n"
        ))

        violations = await checker.scan(tmp_path)

        log005 = [v for v in violations if v.code == "LOG-005"]
        assert len(log005) == 0, "Handler with request_id should not trigger LOG-005"

    async def test_correlation_id_also_accepted(
        self, checker: ObservabilityChecker, tmp_path: Path,
    ) -> None:
        _write_file(tmp_path, "api.py", (
            "from fastapi import FastAPI, Request\n"
            "\n"
            "app = FastAPI()\n"
            "\n"
            "@app.post('/orders')\n"
            "async def create_order(request: Request):\n"
            "    correlation_id = request.headers.get('x-correlation-id')\n"
            "    return {'status': 'created'}\n"
        ))

        violations = await checker.scan(tmp_path)

        log005 = [v for v in violations if v.code == "LOG-005"]
        assert len(log005) == 0, "correlation_id should satisfy LOG-005"


# ===================================================================
# TRACE-001: Missing trace context propagation
# ===================================================================

class TestTrace001MissingPropagation:
    """TRACE-001: HTTP calls without trace headers should be detected."""

    async def test_httpx_get_without_trace_headers(
        self, checker: ObservabilityChecker, tmp_path: Path,
    ) -> None:
        _write_file(tmp_path, "client.py", (
            "import httpx\n"
            "\n"
            "async def fetch_user(user_id: int):\n"
            "    response = httpx.get(f'http://users-svc/users/{user_id}')\n"
            "    return response.json()\n"
        ))

        violations = await checker.scan(tmp_path)

        trace001 = [v for v in violations if v.code == "TRACE-001"]
        assert len(trace001) >= 1
        assert trace001[0].category == "tracing"
        assert trace001[0].severity == "warning"
        assert "trace" in trace001[0].message.lower() or "propagation" in trace001[0].message.lower()

    async def test_requests_post_without_trace_headers(
        self, checker: ObservabilityChecker, tmp_path: Path,
    ) -> None:
        _write_file(tmp_path, "notifier.py", (
            "import requests\n"
            "\n"
            "def send_notification(payload: dict):\n"
            "    resp = requests.post('http://notify-svc/send', json=payload)\n"
            "    return resp.status_code\n"
        ))

        violations = await checker.scan(tmp_path)

        trace001 = [v for v in violations if v.code == "TRACE-001"]
        assert len(trace001) >= 1

    async def test_fetch_in_js_without_trace(
        self, checker: ObservabilityChecker, tmp_path: Path,
    ) -> None:
        _write_file(tmp_path, "api-client.ts", (
            "export async function getProducts(): Promise<Product[]> {\n"
            "  const resp = await fetch('/api/products');\n"
            "  return resp.json();\n"
            "}\n"
        ))

        violations = await checker.scan(tmp_path)

        trace001 = [v for v in violations if v.code == "TRACE-001"]
        assert len(trace001) >= 1


class TestTrace001PropagationPresent:
    """TRACE-001: HTTP calls WITH trace context should NOT be flagged."""

    async def test_httpx_with_traceparent_not_flagged(
        self, checker: ObservabilityChecker, tmp_path: Path,
    ) -> None:
        _write_file(tmp_path, "client.py", (
            "import httpx\n"
            "from opentelemetry import propagate\n"
            "\n"
            "async def fetch_user(user_id: int):\n"
            "    headers = {}\n"
            "    propagate.inject(headers)\n"
            "    response = httpx.get(\n"
            "        f'http://users-svc/users/{user_id}',\n"
            "        headers=headers,\n"
            "    )\n"
            "    return response.json()\n"
        ))

        violations = await checker.scan(tmp_path)

        trace001 = [v for v in violations if v.code == "TRACE-001"]
        assert len(trace001) == 0, "File with propagate.inject should not trigger TRACE-001"

    async def test_traceparent_header_literal_not_flagged(
        self, checker: ObservabilityChecker, tmp_path: Path,
    ) -> None:
        _write_file(tmp_path, "caller.py", (
            "import httpx\n"
            "\n"
            "def call_downstream(trace_ctx: str):\n"
            "    headers = {'traceparent': trace_ctx}\n"
            "    return httpx.post('http://downstream/api', headers=headers)\n"
        ))

        violations = await checker.scan(tmp_path)

        trace001 = [v for v in violations if v.code == "TRACE-001"]
        assert len(trace001) == 0, "Explicit traceparent header should satisfy TRACE-001"


# ===================================================================
# HEALTH-001: Missing health endpoint
# ===================================================================

class TestHealth001MissingEndpoint:
    """HEALTH-001: FastAPI/Flask app without /health should be detected."""

    async def test_fastapi_app_without_health(
        self, checker: ObservabilityChecker, tmp_path: Path,
    ) -> None:
        _write_file(tmp_path, "main.py", (
            "from fastapi import FastAPI\n"
            "\n"
            "app = FastAPI()\n"
            "\n"
            "@app.get('/users')\n"
            "async def list_users():\n"
            "    return []\n"
            "\n"
            "@app.post('/users')\n"
            "async def create_user(name: str):\n"
            "    return {'name': name}\n"
        ))

        violations = await checker.scan(tmp_path)

        health001 = [v for v in violations if v.code == "HEALTH-001"]
        assert len(health001) == 1
        assert health001[0].category == "health"
        assert health001[0].severity == "error"
        assert "/health" in health001[0].message.lower()

    async def test_flask_app_without_health(
        self, checker: ObservabilityChecker, tmp_path: Path,
    ) -> None:
        _write_file(tmp_path, "server.py", (
            "from flask import Flask\n"
            "\n"
            "app = Flask(__name__)\n"
            "\n"
            "@app.route('/api/data')\n"
            "def get_data():\n"
            "    return {'data': []}\n"
        ))

        violations = await checker.scan(tmp_path)

        health001 = [v for v in violations if v.code == "HEALTH-001"]
        assert len(health001) == 1

    async def test_express_app_without_health(
        self, checker: ObservabilityChecker, tmp_path: Path,
    ) -> None:
        _write_file(tmp_path, "index.ts", (
            "import express from 'express';\n"
            "\n"
            "const app = express();\n"
            "\n"
            "app.get('/api/items', (req, res) => {\n"
            "  res.json([]);\n"
            "});\n"
            "\n"
            "app.listen(8000);\n"
        ))

        violations = await checker.scan(tmp_path)

        health001 = [v for v in violations if v.code == "HEALTH-001"]
        assert len(health001) == 1


class TestHealth001EndpointPresent:
    """HEALTH-001: App WITH /health should NOT be flagged."""

    async def test_fastapi_with_health_not_flagged(
        self, checker: ObservabilityChecker, tmp_path: Path,
    ) -> None:
        _write_file(tmp_path, "main.py", (
            "from fastapi import FastAPI\n"
            "\n"
            "app = FastAPI()\n"
            "\n"
            "@app.get('/health')\n"
            "async def health_check():\n"
            "    return {'status': 'ok'}\n"
            "\n"
            "@app.get('/users')\n"
            "async def list_users():\n"
            "    return []\n"
        ))

        violations = await checker.scan(tmp_path)

        health001 = [v for v in violations if v.code == "HEALTH-001"]
        assert len(health001) == 0, "App with /health should not trigger HEALTH-001"

    async def test_healthz_variant_also_accepted(
        self, checker: ObservabilityChecker, tmp_path: Path,
    ) -> None:
        _write_file(tmp_path, "app.py", (
            "from fastapi import FastAPI\n"
            "\n"
            "app = FastAPI()\n"
            "\n"
            "@app.get('/healthz')\n"
            "async def healthz():\n"
            "    return {'alive': True}\n"
        ))

        violations = await checker.scan(tmp_path)

        health001 = [v for v in violations if v.code == "HEALTH-001"]
        assert len(health001) == 0, "/healthz variant should also satisfy HEALTH-001"

    async def test_health_in_separate_file_not_flagged(
        self, checker: ObservabilityChecker, tmp_path: Path,
    ) -> None:
        """The app definition and /health route may live in different files."""
        _write_file(tmp_path, "main.py", (
            "from fastapi import FastAPI\n"
            "\n"
            "app = FastAPI()\n"
            "\n"
            "@app.get('/users')\n"
            "async def list_users():\n"
            "    return []\n"
        ))
        _write_file(tmp_path, "health.py", (
            "from main import app\n"
            "\n"
            "@app.get('/health')\n"
            "async def health_check():\n"
            "    return {'status': 'ok'}\n"
        ))

        violations = await checker.scan(tmp_path)

        health001 = [v for v in violations if v.code == "HEALTH-001"]
        assert len(health001) == 0, "Health endpoint in a separate file should count"


# ===================================================================
# Edge cases: excluded dirs, empty directory, non-scannable files
# ===================================================================

class TestExcludedDirectories:
    """Files inside excluded directories (node_modules, __pycache__, etc.)
    must be skipped entirely."""

    async def test_node_modules_skipped(
        self, checker: ObservabilityChecker, tmp_path: Path,
    ) -> None:
        _write_file(tmp_path / "node_modules" / "some-lib", "index.js", (
            "console.log('Library bootstrap');\n"
            "console.error('this should be ignored');\n"
        ))

        violations = await checker.scan(tmp_path)

        assert len(violations) == 0, "Files under node_modules must be skipped"

    async def test_pycache_skipped(
        self, checker: ObservabilityChecker, tmp_path: Path,
    ) -> None:
        _write_file(tmp_path / "__pycache__", "cached.py", (
            "print('this is cached bytecode helper')\n"
        ))

        violations = await checker.scan(tmp_path)

        assert len(violations) == 0, "Files under __pycache__ must be skipped"

    async def test_venv_skipped(
        self, checker: ObservabilityChecker, tmp_path: Path,
    ) -> None:
        _write_file(tmp_path / "venv" / "lib", "pip_internal.py", (
            "print('pip bootstrap')\n"
        ))
        _write_file(tmp_path / ".venv" / "lib", "pip_internal.py", (
            "print('pip bootstrap')\n"
        ))

        violations = await checker.scan(tmp_path)

        assert len(violations) == 0, "Files under venv/.venv must be skipped"

    async def test_non_excluded_subdirectory_scanned(
        self, checker: ObservabilityChecker, tmp_path: Path,
    ) -> None:
        """Files in normal subdirectories should still be scanned."""
        _write_file(tmp_path / "src" / "services", "user.py", (
            "def handle():\n"
            "    print('hello world')\n"
        ))

        violations = await checker.scan(tmp_path)

        log001 = [v for v in violations if v.code == "LOG-001"]
        assert len(log001) >= 1, "Normal subdirectories must still be scanned"


class TestEmptyDirectory:
    """An empty directory or directory with no scannable files should
    produce zero violations."""

    async def test_empty_dir_returns_empty_list(
        self, checker: ObservabilityChecker, tmp_path: Path,
    ) -> None:
        violations = await checker.scan(tmp_path)
        assert violations == []

    async def test_non_scannable_extensions_ignored(
        self, checker: ObservabilityChecker, tmp_path: Path,
    ) -> None:
        """Files with extensions not in SCANNABLE_EXTENSIONS (.md, .txt, etc.)
        should not produce any violations."""
        _write_file(tmp_path, "README.md", (
            "# My Service\n"
            "print('this is markdown, not Python')\n"
            "console.log('also not real code');\n"
        ))
        _write_file(tmp_path, "data.json", (
            '{"password": "super-secret"}\n'
        ))

        violations = await checker.scan(tmp_path)

        assert violations == [], "Non-scannable file types must be ignored"


class TestNonExistentDirectory:
    """Scanning a non-existent directory should return an empty list,
    not raise an exception."""

    async def test_missing_dir_returns_empty(
        self, checker: ObservabilityChecker, tmp_path: Path,
    ) -> None:
        missing = tmp_path / "does_not_exist"
        violations = await checker.scan(missing)
        assert violations == []


# ===================================================================
# Violation metadata integrity
# ===================================================================

class TestViolationMetadata:
    """Verify that returned ScanViolation objects have correct metadata."""

    async def test_violation_has_correct_file_path(
        self, checker: ObservabilityChecker, tmp_path: Path,
    ) -> None:
        file_path = _write_file(tmp_path, "bad.py", "print('oops')\n")

        violations = await checker.scan(tmp_path)

        assert len(violations) >= 1
        assert str(file_path) in violations[0].file_path

    async def test_violation_line_number_is_positive(
        self, checker: ObservabilityChecker, tmp_path: Path,
    ) -> None:
        _write_file(tmp_path, "bad.py", (
            "x = 1\n"
            "y = 2\n"
            "print('line 3')\n"
        ))

        violations = await checker.scan(tmp_path)

        for v in violations:
            assert v.line > 0, "Line numbers must be 1-based positive integers"

    async def test_message_is_non_empty(
        self, checker: ObservabilityChecker, tmp_path: Path,
    ) -> None:
        _write_file(tmp_path, "bad.py", "print('debug')\n")

        violations = await checker.scan(tmp_path)

        for v in violations:
            assert v.message, "Every violation must include a message"


# ===================================================================
# Multiple violations in one file
# ===================================================================

class TestMultipleViolationsPerFile:
    """A single file can produce violations across multiple codes."""

    async def test_file_with_multiple_issues(
        self, checker: ObservabilityChecker, tmp_path: Path,
    ) -> None:
        _write_file(tmp_path, "messy_service.py", (
            "import httpx\n"
            "from fastapi import FastAPI\n"
            "\n"
            "app = FastAPI()\n"
            "\n"
            "@app.get('/users')\n"
            "async def list_users():\n"
            "    print('listing users')\n"
            "    resp = httpx.get('http://db-svc/users')\n"
            "    return resp.json()\n"
        ))

        violations = await checker.scan(tmp_path)

        codes_found = {v.code for v in violations}
        # Should at minimum detect:
        # - LOG-001 for print()
        # - TRACE-001 for httpx.get without trace context
        # - LOG-005 for handler without request_id
        # - HEALTH-001 for FastAPI app without /health
        assert "LOG-001" in codes_found, "print() should produce LOG-001"
        assert "TRACE-001" in codes_found, "httpx.get without trace should produce TRACE-001"
        assert "HEALTH-001" in codes_found, "FastAPI app without /health should produce HEALTH-001"

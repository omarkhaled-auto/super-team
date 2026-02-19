"""Observability checker for Build 3 quality gate.

Scans source code for observability issues including:
- LOG-001:   Missing structured logging (print statements, unstructured logging)
- LOG-004:   Sensitive data in logs (passwords, tokens, secrets, etc.)
- LOG-005:   Missing request ID logging in request handlers
- TRACE-001: Missing trace context propagation in HTTP client calls
- HEALTH-001: Missing health endpoint in service definitions
"""

from __future__ import annotations

import re
from pathlib import Path

from src.build3_shared.constants import HEALTH_SCAN_CODES, LOGGING_SCAN_CODES, TRACE_SCAN_CODES
from src.build3_shared.models import ScanViolation

# ---------------------------------------------------------------------------
# Excluded directories (TECH-018: frozenset for O(1) lookup)
# ---------------------------------------------------------------------------
EXCLUDED_DIRS: frozenset[str] = frozenset({
    "node_modules",
    ".venv",
    "venv",
    "__pycache__",
    ".git",
    "dist",
    "build",
})

# File extensions to scan
SCANNABLE_EXTENSIONS: frozenset[str] = frozenset({
    ".py", ".js", ".ts", ".jsx", ".tsx",
})

# ---------------------------------------------------------------------------
# TECH-018: All regex patterns compiled at module level
# ---------------------------------------------------------------------------

# --- LOG-001: Missing structured logging ---
# Detect bare print() calls used for logging
RE_PRINT_CALL = re.compile(
    r"\bprint\s*\(",
)
# Detect logging calls that do NOT use structured format (dict/JSON)
# Matches: logging.info("some string"), logger.warning(f"..."), etc.
RE_LOGGING_UNSTRUCTURED = re.compile(
    r"\b(?:logging|logger)\s*\.\s*(?:debug|info|warning|error|critical|exception|log)"
    r"\s*\(\s*(?:f?[\"']|f?\"\"\")",
)
# Detect console.log / console.error / console.warn in JS/TS
RE_CONSOLE_LOG = re.compile(
    r"\bconsole\s*\.\s*(?:log|error|warn|info|debug)\s*\(",
)

# --- LOG-004: Sensitive data in logs ---
# Detect logging/printing of sensitive data patterns
_SENSITIVE_NAMES = (
    r"password|passwd|pwd|token|secret|api_key|apikey|api[-_]?secret"
    r"|credit_card|creditcard|card_number|cardnumber"
    r"|ssn|social_security|secret_key|private_key"
    r"|access_token|refresh_token|auth_token|bearer"
)
# Python: logging/print of sensitive variable names
RE_SENSITIVE_LOG_PY = re.compile(
    r"\b(?:print|logging\s*\.\s*\w+|logger\s*\.\s*\w+)\s*\("
    r"[^)]*\b(?:" + _SENSITIVE_NAMES + r")\b",
    re.IGNORECASE,
)
# JS/TS: console.log/warn/error of sensitive data
RE_SENSITIVE_LOG_JS = re.compile(
    r"\bconsole\s*\.\s*(?:log|error|warn|info|debug)\s*\("
    r"[^)]*\b(?:" + _SENSITIVE_NAMES + r")\b",
    re.IGNORECASE,
)
# Generic: string interpolation containing sensitive variable names in log context
RE_SENSITIVE_FSTRING = re.compile(
    r"(?:f[\"']|`)[^\"'`]*\{[^}]*\b(?:" + _SENSITIVE_NAMES + r")\b[^}]*\}",
    re.IGNORECASE,
)

# --- LOG-005: Missing request ID logging ---
# Detect Python request handler definitions (FastAPI, Flask, Django)
RE_PY_REQUEST_HANDLER = re.compile(
    r"(?:@(?:app|router|api)\s*\.\s*(?:get|post|put|patch|delete|route|api_route)\s*\()"
    r"|(?:(?:async\s+)?def\s+\w+\s*\(\s*request\s*[:\s,)])",
)
# Detect JS/TS request handler definitions (Express, Koa, etc.)
RE_JS_REQUEST_HANDLER = re.compile(
    r"(?:(?:app|router)\s*\.\s*(?:get|post|put|patch|delete|all|use)\s*\()"
    r"|(?:(?:export\s+)?(?:async\s+)?function\s+\w+\s*\(\s*(?:req|request|ctx)\b)",
)
# Detect request_id or correlation_id usage
RE_REQUEST_ID_USAGE = re.compile(
    r"\b(?:request_id|requestId|request[-_]?id|correlation_id|correlationId|correlation[-_]?id"
    r"|x[-_]request[-_]id|x[-_]correlation[-_]id)\b",
    re.IGNORECASE,
)

# --- TRACE-001: Missing trace context propagation ---
# Python HTTP client calls
RE_PY_HTTP_CLIENT = re.compile(
    r"\b(?:requests|httpx|aiohttp|urllib)\s*\.\s*(?:get|post|put|patch|delete|head|options|request)\s*\(",
)
# httpx.AsyncClient / httpx.Client usage
RE_PY_HTTPX_CLIENT = re.compile(
    r"\b(?:httpx\s*\.\s*(?:AsyncClient|Client)\s*\(|(?:async\s+with|with)\s+httpx)",
)
# aiohttp.ClientSession usage
RE_PY_AIOHTTP_SESSION = re.compile(
    r"\baiohttp\s*\.\s*ClientSession\s*\(",
)
# JS/TS HTTP client calls (fetch, axios, got, etc.)
RE_JS_HTTP_CLIENT = re.compile(
    r"\b(?:fetch|axios|got|superagent|node-fetch|undici)\s*[.(]",
)
# Trace header propagation
RE_TRACE_HEADER = re.compile(
    r"\b(?:traceparent|tracestate|x[-_]?trace[-_]?id|opentelemetry|"
    r"propagate|inject|W3CTraceContextPropagator|TraceContextTextMapPropagator)\b",
    re.IGNORECASE,
)

# --- HEALTH-001: Missing health endpoint ---
# Python health endpoint definitions (FastAPI, Flask)
RE_PY_HEALTH_ENDPOINT = re.compile(
    r"""['"]/health(?:z)?['"]""",
)
# Python app/router definition (indicates this is a service)
RE_PY_APP_DEFINITION = re.compile(
    r"\b(?:FastAPI|Flask|Starlette|Litestar|Sanic|Quart)\s*\(",
)
# JS/TS health endpoint definitions (Express, Koa, etc.)
RE_JS_HEALTH_ENDPOINT = re.compile(
    r"""['"]/health(?:z)?['"]""",
)
# JS/TS app definition (indicates this is a service)
RE_JS_APP_DEFINITION = re.compile(
    r"\b(?:express|koa|fastify|hapi|createServer)\s*\(",
)


class ObservabilityChecker:
    """Scans source code for observability issues.

    Satisfies the ``QualityScanner`` protocol: exposes an
    ``async def scan(self, target_dir: Path) -> list[ScanViolation]`` method.

    Checks performed:
        LOG-001    Missing structured logging
        LOG-004    Sensitive data in logs
        LOG-005    Missing request ID logging
        TRACE-001  Missing trace context propagation
        HEALTH-001 Missing health endpoint
    """

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    async def scan(self, target_dir: Path) -> list[ScanViolation]:
        """Scan *target_dir* recursively for observability violations.

        Args:
            target_dir: Root directory to scan.

        Returns:
            A list of ``ScanViolation`` instances for every issue found.
        """
        violations: list[ScanViolation] = []
        target = Path(target_dir)

        if not target.is_dir():
            return violations

        # Collect all scannable files first, then check for HEALTH-001
        # across the entire service.
        service_files: list[Path] = []

        for ext in SCANNABLE_EXTENSIONS:
            for file_path in target.rglob(f"*{ext}"):
                if self._should_skip_file(file_path):
                    continue
                service_files.append(file_path)

        # Per-file checks
        for file_path in service_files:
            violations.extend(self._scan_file(file_path))

        # Service-level health endpoint check
        violations.extend(self._check_health_endpoint_service(service_files))

        return violations

    # ------------------------------------------------------------------
    # File filtering
    # ------------------------------------------------------------------

    def _should_skip_file(self, file_path: Path) -> bool:
        """Return ``True`` if the file resides under an excluded directory."""
        for part in file_path.parts:
            if part in EXCLUDED_DIRS:
                return True
        return False

    # ------------------------------------------------------------------
    # Per-file scanning
    # ------------------------------------------------------------------

    def _scan_file(self, file_path: Path) -> list[ScanViolation]:
        """Run all per-file observability checks.

        Args:
            file_path: Path to the source file to scan.

        Returns:
            A list of violations found in this file.
        """
        try:
            content = file_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return []

        if not content.strip():
            return []

        lines = content.splitlines()
        violations: list[ScanViolation] = []

        violations.extend(self._check_structured_logging(content, lines, file_path))
        violations.extend(self._check_sensitive_logging(content, lines, file_path))
        violations.extend(self._check_request_id_logging(content, lines, file_path))
        violations.extend(self._check_trace_propagation(content, lines, file_path))
        violations.extend(self._check_health_endpoint(content, file_path))

        return violations

    # ------------------------------------------------------------------
    # LOG-001: Missing structured logging
    # ------------------------------------------------------------------

    def _check_structured_logging(
        self,
        content: str,
        lines: list[str],
        file_path: Path,
    ) -> list[ScanViolation]:
        """Detect print() statements and unstructured logging calls.

        Returns:
            A list of LOG-001 violations.
        """
        violations: list[ScanViolation] = []
        is_python = file_path.suffix == ".py"
        is_js_ts = file_path.suffix in {".js", ".ts", ".jsx", ".tsx"}

        for line_no, line in enumerate(lines, start=1):
            stripped = line.lstrip()

            # Skip comments
            if stripped.startswith("#") or stripped.startswith("//"):
                continue

            if is_python:
                if RE_PRINT_CALL.search(line):
                    violations.append(ScanViolation(
                        code=LOGGING_SCAN_CODES[0],  # LOG-001
                        severity="warning",
                        category="logging",
                        file_path=str(file_path),
                        line=line_no,
                        message=(
                            "print() used instead of structured logging. "
                            "Suggestion: Replace print() with a structured logger "
                            "(e.g. structlog, python-json-logger) that emits JSON."
                        ),
                    ))
                elif RE_LOGGING_UNSTRUCTURED.search(line):
                    violations.append(ScanViolation(
                        code=LOGGING_SCAN_CODES[0],  # LOG-001
                        severity="warning",
                        category="logging",
                        file_path=str(file_path),
                        line=line_no,
                        message=(
                            "Logging call uses plain string instead of structured format. "
                            "Suggestion: Use structured logging with key-value pairs or dict format "
                            "(e.g. logger.info('event', extra={'key': 'value'}))."
                        ),
                    ))

            if is_js_ts and RE_CONSOLE_LOG.search(line):
                violations.append(ScanViolation(
                    code=LOGGING_SCAN_CODES[0],  # LOG-001
                    severity="warning",
                    category="logging",
                    file_path=str(file_path),
                    line=line_no,
                    message=(
                        "console.log/warn/error used instead of structured logging. "
                        "Suggestion: Replace console.log with a structured logger "
                        "(e.g. pino, winston) that emits JSON."
                    ),
                ))

        return violations

    # ------------------------------------------------------------------
    # LOG-004: Sensitive data in logs
    # ------------------------------------------------------------------

    def _check_sensitive_logging(
        self,
        content: str,
        lines: list[str],
        file_path: Path,
    ) -> list[ScanViolation]:
        """Detect logging of sensitive data (passwords, tokens, secrets, etc.).

        Returns:
            A list of LOG-004 violations.
        """
        violations: list[ScanViolation] = []
        is_python = file_path.suffix == ".py"
        is_js_ts = file_path.suffix in {".js", ".ts", ".jsx", ".tsx"}

        for line_no, line in enumerate(lines, start=1):
            stripped = line.lstrip()

            # Skip comments
            if stripped.startswith("#") or stripped.startswith("//"):
                continue

            found = False

            if is_python and RE_SENSITIVE_LOG_PY.search(line):
                found = True
            elif is_js_ts and RE_SENSITIVE_LOG_JS.search(line):
                found = True

            # Check f-string / template literal interpolation of sensitive data
            if not found and RE_SENSITIVE_FSTRING.search(line):
                # Only flag if this line is in a logging/print context
                if RE_PRINT_CALL.search(line) or RE_LOGGING_UNSTRUCTURED.search(line) or RE_CONSOLE_LOG.search(line):
                    found = True

            if found:
                violations.append(ScanViolation(
                    code=LOGGING_SCAN_CODES[1],  # LOG-004
                    severity="error",
                    category="logging",
                    file_path=str(file_path),
                    line=line_no,
                    message=(
                        "Sensitive data (password, token, secret, etc.) may be logged. "
                        "Suggestion: Never log sensitive fields directly. Mask or redact sensitive "
                        "values before logging (e.g. '***REDACTED***')."
                    ),
                ))

        return violations

    # ------------------------------------------------------------------
    # LOG-005: Missing request ID logging
    # ------------------------------------------------------------------

    def _check_request_id_logging(
        self,
        content: str,
        lines: list[str],
        file_path: Path,
    ) -> list[ScanViolation]:
        """Detect request handlers that do not propagate a request/correlation ID.

        Looks for route handler or request-accepting function definitions and
        checks whether ``request_id`` / ``correlation_id`` is referenced within
        a reasonable window after the handler definition.

        Returns:
            A list of LOG-005 violations.
        """
        violations: list[ScanViolation] = []
        is_python = file_path.suffix == ".py"
        is_js_ts = file_path.suffix in {".js", ".ts", ".jsx", ".tsx"}

        # If the file already has request_id at module/global level, skip
        if RE_REQUEST_ID_USAGE.search(content):
            return violations

        handler_lines: list[int] = []

        for line_no, line in enumerate(lines, start=1):
            if is_python and RE_PY_REQUEST_HANDLER.search(line):
                handler_lines.append(line_no)
            elif is_js_ts and RE_JS_REQUEST_HANDLER.search(line):
                handler_lines.append(line_no)

        for handler_line in handler_lines:
            # Look ahead up to 30 lines for request_id usage
            window_start = handler_line - 1
            window_end = min(handler_line + 29, len(lines))
            window = "\n".join(lines[window_start:window_end])

            if not RE_REQUEST_ID_USAGE.search(window):
                violations.append(ScanViolation(
                    code=LOGGING_SCAN_CODES[2],  # LOG-005
                    severity="warning",
                    category="logging",
                    file_path=str(file_path),
                    line=handler_line,
                    message=(
                        "Request handler does not propagate request_id/correlation_id in logs. "
                        "Suggestion: Extract or generate a request_id/correlation_id from the incoming "
                        "request headers and include it in all log entries for traceability."
                    ),
                ))

        return violations

    # ------------------------------------------------------------------
    # TRACE-001: Missing trace context propagation
    # ------------------------------------------------------------------

    def _check_trace_propagation(
        self,
        content: str,
        lines: list[str],
        file_path: Path,
    ) -> list[ScanViolation]:
        """Detect HTTP client calls that do not propagate trace context headers.

        Returns:
            A list of TRACE-001 violations.
        """
        violations: list[ScanViolation] = []
        is_python = file_path.suffix == ".py"
        is_js_ts = file_path.suffix in {".js", ".ts", ".jsx", ".tsx"}

        # If the file already has trace header propagation at module level, skip
        if RE_TRACE_HEADER.search(content):
            return violations

        for line_no, line in enumerate(lines, start=1):
            stripped = line.lstrip()

            # Skip comments
            if stripped.startswith("#") or stripped.startswith("//"):
                continue

            found_http_call = False

            if is_python:
                if (RE_PY_HTTP_CLIENT.search(line)
                        or RE_PY_HTTPX_CLIENT.search(line)
                        or RE_PY_AIOHTTP_SESSION.search(line)):
                    found_http_call = True

            if is_js_ts and RE_JS_HTTP_CLIENT.search(line):
                found_http_call = True

            if found_http_call:
                # Look in a small window around this line for trace header usage
                window_start = max(0, line_no - 6)
                window_end = min(len(lines), line_no + 5)
                window = "\n".join(lines[window_start:window_end])

                if not RE_TRACE_HEADER.search(window):
                    violations.append(ScanViolation(
                        code=TRACE_SCAN_CODES[0],  # TRACE-001
                        severity="warning",
                        category="tracing",
                        file_path=str(file_path),
                        line=line_no,
                        message=(
                            "HTTP client call without trace context propagation. "
                            "Suggestion: Propagate W3C trace context headers (traceparent, tracestate) "
                            "in outgoing HTTP requests. Use OpenTelemetry instrumentation or "
                            "manually inject headers from the current span context."
                        ),
                    ))

        return violations

    # ------------------------------------------------------------------
    # HEALTH-001: Missing health endpoint (per-file component)
    # ------------------------------------------------------------------

    def _check_health_endpoint(
        self,
        content: str,
        file_path: Path,
    ) -> list[ScanViolation]:
        """Check individual file for app definition without health endpoint.

        This is the per-file component. The service-level aggregation happens
        in ``_check_health_endpoint_service``.

        Returns:
            An empty list (per-file checks delegate to service-level).
        """
        # Per-file detection is handled at the service level to avoid
        # false positives. The health endpoint may be defined in a
        # different file from the app definition. See _check_health_endpoint_service.
        return []

    # ------------------------------------------------------------------
    # HEALTH-001: Service-level health endpoint check
    # ------------------------------------------------------------------

    def _check_health_endpoint_service(
        self,
        service_files: list[Path],
    ) -> list[ScanViolation]:
        """Check whether the service defines a /health or /healthz endpoint.

        Examines all scanned files for an application framework definition
        (FastAPI, Flask, Express, etc.) and verifies that at least one file
        in the service defines a ``/health`` or ``/healthz`` route.

        Args:
            service_files: All scannable files in the service.

        Returns:
            A list containing at most one HEALTH-001 violation.
        """
        app_definition_file: Path | None = None
        app_definition_line: int = 0
        has_health_endpoint = False

        for file_path in service_files:
            try:
                content = file_path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue

            is_python = file_path.suffix == ".py"
            is_js_ts = file_path.suffix in {".js", ".ts", ".jsx", ".tsx"}

            # Check for health endpoint definition
            if is_python and RE_PY_HEALTH_ENDPOINT.search(content):
                has_health_endpoint = True
                break
            if is_js_ts and RE_JS_HEALTH_ENDPOINT.search(content):
                has_health_endpoint = True
                break

            # Track app framework definition for reporting
            if app_definition_file is None:
                if is_python and RE_PY_APP_DEFINITION.search(content):
                    app_definition_file = file_path
                    for line_no, line in enumerate(content.splitlines(), start=1):
                        if RE_PY_APP_DEFINITION.search(line):
                            app_definition_line = line_no
                            break
                elif is_js_ts and RE_JS_APP_DEFINITION.search(content):
                    app_definition_file = file_path
                    for line_no, line in enumerate(content.splitlines(), start=1):
                        if RE_JS_APP_DEFINITION.search(line):
                            app_definition_line = line_no
                            break

        if has_health_endpoint or app_definition_file is None:
            return []

        return [ScanViolation(
            code=HEALTH_SCAN_CODES[0],  # HEALTH-001
            severity="error",
            category="health",
            file_path=str(app_definition_file),
            line=app_definition_line,
            message=(
                "Service does not define a /health or /healthz endpoint. "
                "Suggestion: Add a health check endpoint (e.g. GET /health or GET /healthz) "
                "that returns service status. This is required for container "
                "orchestration readiness/liveness probes."
            ),
        )]

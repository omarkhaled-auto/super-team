"""Schemathesis-based contract compliance verification.

Runs OpenAPI schema conformance tests against live services using
schemathesis 4.x.  All blocking schemathesis and requests calls are
offloaded to a thread via ``asyncio.to_thread`` so the event loop is
never blocked.

Violation codes emitted:
    SCHEMA-001  Response body does not conform to the declared schema.
    SCHEMA-002  Unexpected HTTP status code (4xx / 5xx when 2xx expected).
    SCHEMA-003  Response time exceeded the 5-second threshold.
"""

from __future__ import annotations

import asyncio
import logging
import textwrap
import time
from pathlib import Path
from typing import Any

from src.build3_shared.models import ContractViolation

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Lazy / defensive schemathesis imports -- the library may not be installed
# in every environment, so we defer the import and surface a clear message.
# ---------------------------------------------------------------------------
_schemathesis = None
_requests_exceptions = None


def _ensure_schemathesis() -> Any:
    """Import schemathesis lazily and cache it at module level."""
    global _schemathesis  # noqa: PLW0603
    if _schemathesis is None:
        try:
            import schemathesis
            _schemathesis = schemathesis
        except ImportError as exc:
            raise RuntimeError(
                "schemathesis is required for contract compliance testing. "
                "Install it with:  pip install schemathesis==4.10.1"
            ) from exc
    return _schemathesis


def _ensure_requests_exceptions() -> Any:
    """Import requests.exceptions lazily and cache it at module level."""
    global _requests_exceptions  # noqa: PLW0603
    if _requests_exceptions is None:
        try:
            import requests.exceptions
            _requests_exceptions = requests.exceptions
        except ImportError:
            _requests_exceptions = None
    return _requests_exceptions


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
_RESPONSE_TIME_THRESHOLD = 5.0  # seconds
_CODE_SCHEMA = "SCHEMA-001"
_CODE_STATUS = "SCHEMA-002"
_CODE_SLOW = "SCHEMA-003"


class SchemathesisRunner:
    """Run schemathesis contract-compliance tests against a live service.

    Parameters
    ----------
    timeout:
        HTTP request timeout in seconds for individual test calls.
    """

    def __init__(self, project_root: Path | None = None, timeout: float = 30.0) -> None:
        self.project_root = project_root or Path(".")
        self.timeout = timeout

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def run_against_service(
        self,
        service_name: str,
        openapi_url: str,
        base_url: str,
        max_examples: int = 50,
    ) -> list[ContractViolation]:
        """Run positive contract-conformance tests against *base_url*.

        Loads the OpenAPI schema from *openapi_url*, iterates over every
        operation, generates valid test cases, calls the live service, and
        validates each response.

        Returns a (possibly empty) list of :class:`ContractViolation` items.
        """
        return await asyncio.to_thread(
            self._run_against_service_sync,
            service_name,
            openapi_url,
            base_url,
            max_examples,
        )

    async def run_negative_tests(
        self,
        service_name: str,
        openapi_url: str,
        base_url: str,
    ) -> list[ContractViolation]:
        """Run negative / malformed-input tests against *base_url*.

        Sends intentionally invalid payloads to every operation and
        verifies that the service responds with a proper 4xx error
        rather than a 5xx crash.

        Returns a (possibly empty) list of :class:`ContractViolation` items.
        """
        return await asyncio.to_thread(
            self._run_negative_tests_sync,
            service_name,
            openapi_url,
            base_url,
        )

    def generate_test_file(self, openapi_url: str) -> str:
        """Generate a standalone ``pytest`` test file that uses schemathesis.

        The returned string is valid Python source code using the
        ``@schema.parametrize()`` decorator so that ``pytest`` can
        discover and run the tests directly.

        Parameters
        ----------
        openapi_url:
            URL (or file path) pointing to the OpenAPI specification.
        """
        return textwrap.dedent(f"""\
            \"\"\"Auto-generated schemathesis contract tests.

            Run with:  pytest tests/contract_tests.py -v
            \"\"\"
            import schemathesis

            schema = schemathesis.openapi.from_url("{openapi_url}")


            @schema.parametrize()
            def test_api_conformance(case):
                \"\"\"Validate that every endpoint conforms to the OpenAPI schema.\"\"\"
                response = case.call()
                case.validate_response(response)


            @schema.parametrize()
            def test_response_status_codes(case):
                \"\"\"Ensure no unexpected 5xx errors are returned.\"\"\"
                response = case.call()
                assert response.status_code < 500, (
                    f"Unexpected server error {{response.status_code}} "
                    f"on {{case.method}} {{case.path}}"
                )
        """)

    # ------------------------------------------------------------------
    # Internal helpers (synchronous -- called inside to_thread)
    # ------------------------------------------------------------------

    def _load_schema(self, openapi_url: str, base_url: str) -> Any:
        """Load an OpenAPI schema, pointing requests at *base_url*."""
        schemathesis = _ensure_schemathesis()

        if openapi_url.startswith(("http://", "https://")):
            schema = schemathesis.openapi.from_url(openapi_url, base_url=base_url)
        else:
            schema = schemathesis.openapi.from_path(
                openapi_url, base_url=base_url,
            )
        return schema

    def _run_against_service_sync(
        self,
        service_name: str,
        openapi_url: str,
        base_url: str,
        max_examples: int = 50,
    ) -> list[ContractViolation]:
        """Synchronous implementation of :meth:`run_against_service`.

        Loads the OpenAPI schema and iterates every operation using the
        schemathesis programmatic API (``get_all_operations`` /
        ``make_case`` / ``call`` / ``validate_response``).
        """
        _ensure_requests_exceptions()
        schemathesis = _ensure_schemathesis()

        # --- Load schema ---------------------------------------------------
        try:
            schema = self._load_schema(openapi_url, base_url)
        except Exception as exc:
            logger.error(
                "Failed to load OpenAPI schema from %s: %s", openapi_url, exc,
            )
            return []

        # --- Run tests via schemathesis programmatic API -------------------
        return self._run_via_test_runner(
            schema, service_name, base_url, max_examples,
        )

    def _run_negative_tests_sync(
        self,
        service_name: str,
        openapi_url: str,
        base_url: str,
    ) -> list[ContractViolation]:
        """Synchronous implementation of :meth:`run_negative_tests`.

        Iterates the raw OpenAPI spec paths dict to discover operations,
        then sends malformed payloads via ``httpx`` to POST/PUT/PATCH
        endpoints and asserts the service responds with 4xx (not 5xx).
        """
        import httpx

        schemathesis = _ensure_schemathesis()
        violations: list[ContractViolation] = []

        # --- Load schema ---------------------------------------------------
        try:
            schema = self._load_schema(openapi_url, base_url)
        except Exception as exc:
            logger.error(
                "Failed to load OpenAPI schema from %s: %s", openapi_url, exc,
            )
            return []

        # --- Extract paths from the raw OpenAPI spec -----------------------
        raw: dict[str, Any] = {}
        for attr in ("raw_schema", "raw", "schema"):
            raw = getattr(schema, attr, None) or {}
            if raw:
                break

        paths: dict[str, Any] = raw.get("paths", {})

        # --- Malformed-payload tests ----------------------------------------
        _MALFORMED_PAYLOADS: list[Any] = [
            None,
            "",
            "{{invalid json}}",
            {"__inject": "<script>alert(1)</script>"},
            {"": ""},
            12345,
            [],
            {"a" * 10_000: "overflow"},
        ]

        for path, methods in paths.items():
            if not isinstance(methods, dict):
                continue
            for method, _spec in methods.items():
                method_upper = method.upper()

                # Only POST / PUT / PATCH typically accept a body.
                if method_upper not in ("POST", "PUT", "PATCH"):
                    continue

                endpoint = f"{method_upper} {path}"

                for payload in _MALFORMED_PAYLOADS:
                    try:
                        url = f"{base_url.rstrip('/')}{path}"
                        start = time.monotonic()
                        with httpx.Client(timeout=self.timeout) as client:
                            resp = client.request(
                                method_upper,
                                url,
                                json=payload,
                                headers={"Content-Type": "application/json"},
                            )
                        elapsed = time.monotonic() - start

                        # A 5xx response to bad input is a server-side defect.
                        if resp.status_code >= 500:
                            violations.append(
                                ContractViolation(
                                    code=_CODE_STATUS,
                                    severity="error",
                                    service=service_name,
                                    endpoint=endpoint,
                                    message=(
                                        f"Server error {resp.status_code} on "
                                        f"malformed input (expected 4xx)"
                                    ),
                                    expected="4xx",
                                    actual=str(resp.status_code),
                                )
                            )

                        # Response-time check applies to negative tests too.
                        if elapsed > _RESPONSE_TIME_THRESHOLD:
                            violations.append(
                                ContractViolation(
                                    code=_CODE_SLOW,
                                    severity="warning",
                                    service=service_name,
                                    endpoint=endpoint,
                                    message=(
                                        f"Response took {elapsed:.2f}s "
                                        f"(threshold {_RESPONSE_TIME_THRESHOLD}s)"
                                    ),
                                    expected=f"<{_RESPONSE_TIME_THRESHOLD}s",
                                    actual=f"{elapsed:.2f}s",
                                )
                            )
                    except httpx.ConnectError:
                        logger.warning(
                            "Connection error during negative test for %s",
                            endpoint,
                        )
                    except Exception as req_exc:
                        logger.debug(
                            "Error during negative test for %s: %s",
                            endpoint,
                            req_exc,
                        )

        return violations

    def _run_via_test_runner(
        self,
        schema: Any,
        service_name: str,
        base_url: str,
        max_examples: int = 50,
    ) -> list[ContractViolation]:
        """Iterate every operation using the schemathesis 4.x programmatic API.

        Uses ``schema.get_all_operations()`` which yields ``Result`` wrappers,
        unwrapped via ``.ok()``.  Creates test cases with
        ``api_operation.Case()``, executes via ``case.call()``, and validates
        via ``case.validate_response()``.  Catches
        ``schemathesis.core.failures.FailureGroup`` for SCHEMA-001 violations.
        """
        try:
            from schemathesis.core.failures import FailureGroup
        except ImportError:
            FailureGroup = Exception  # fallback

        violations: list[ContractViolation] = []
        examples_run = 0

        try:
            for result in schema.get_all_operations():
                if examples_run >= max_examples:
                    break

                # schemathesis 4.x wraps operations in Result objects
                try:
                    api_operation = result.ok()
                except AttributeError:
                    # Fallback: result IS the operation (future-proofing)
                    api_operation = result

                try:
                    # schemathesis 4.x: use api_operation.Case() instead of make_case()
                    case = api_operation.Case()
                    endpoint = f"{case.method.upper()} {case.path}"

                    start = time.monotonic()
                    response = case.call(base_url=base_url)
                    elapsed = time.monotonic() - start
                    examples_run += 1

                    # SCHEMA-003: slow response check
                    if elapsed > _RESPONSE_TIME_THRESHOLD:
                        violations.append(
                            ContractViolation(
                                code=_CODE_SLOW,
                                severity="warning",
                                service=service_name,
                                endpoint=endpoint,
                                message=(
                                    f"Response took {elapsed:.2f}s "
                                    f"(threshold {_RESPONSE_TIME_THRESHOLD}s)"
                                ),
                                expected=f"<{_RESPONSE_TIME_THRESHOLD}s",
                                actual=f"{elapsed:.2f}s",
                            )
                        )

                    # SCHEMA-002: unexpected status code check
                    if response.status_code >= 400:
                        violations.append(
                            ContractViolation(
                                code=_CODE_STATUS,
                                severity=(
                                    "error" if response.status_code >= 500
                                    else "warning"
                                ),
                                service=service_name,
                                endpoint=endpoint,
                                message=(
                                    f"Unexpected status code "
                                    f"{response.status_code}"
                                ),
                                expected="2xx",
                                actual=str(response.status_code),
                            )
                        )

                    # SCHEMA-001: validate response against schema
                    try:
                        case.validate_response(response)
                    except FailureGroup as fg:
                        for failure in fg.exceptions:
                            violations.append(
                                ContractViolation(
                                    code=_CODE_SCHEMA,
                                    severity="error",
                                    service=service_name,
                                    endpoint=endpoint,
                                    message=str(failure),
                                    expected="Schema-compliant response",
                                    actual=str(response.status_code),
                                )
                            )

                except FailureGroup as fg:
                    # call_and_validate style failures
                    for failure in fg.exceptions:
                        violations.append(
                            ContractViolation(
                                code=_CODE_SCHEMA,
                                severity="error",
                                service=service_name,
                                endpoint=str(getattr(api_operation, 'label', 'unknown')),
                                message=str(failure),
                                expected="Schema-compliant response",
                                actual="validation failure",
                            )
                        )
                except Exception as exc:
                    logger.debug(
                        "Error testing operation %s: %s",
                        getattr(api_operation, 'label', 'unknown'),
                        exc,
                    )
        except Exception as exc:
            logger.warning(
                "Error iterating schema operations: %s", exc,
            )

        return violations


"""Boundary-condition testing for serialization edge cases.

Verifies that services handle edge cases in data serialization
correctly: case sensitivity of field names, timezone format variants
in ISO 8601 datetime strings, and null / missing / empty field handling.

Violation codes emitted:
    BOUNDARY-CASE-001  Inconsistent case-sensitivity handling.
    BOUNDARY-TZ-001    Inconsistent timezone format handling.
    BOUNDARY-NULL-001  Server crash (5xx) on null / missing / empty input.
"""

from __future__ import annotations

import logging
import re
from typing import Any

import httpx

from src.build3_shared.models import ContractViolation

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# ISO 8601 timezone variants used by the timezone-handling tests
# ---------------------------------------------------------------------------
_TZ_VARIANTS: list[tuple[str, str]] = [
    ("2024-01-01T00:00:00Z", "UTC with Z"),
    ("2024-01-01T00:00:00+00:00", "UTC with offset"),
    ("2024-01-01T00:00:00+05:30", "non-UTC offset"),
    ("2024-01-01T00:00:00", "naive / no timezone"),
]

# ---------------------------------------------------------------------------
# Violation codes
# ---------------------------------------------------------------------------
_CODE_CASE = "BOUNDARY-CASE-001"
_CODE_TZ = "BOUNDARY-TZ-001"
_CODE_NULL = "BOUNDARY-NULL-001"

# Simple heuristic to detect ISO 8601 datetime strings.
_ISO_DATETIME_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}"
)


class BoundaryTester:
    """Tests serialization boundary conditions across services.

    Verifies that services handle edge cases in data serialization:
    case sensitivity, timezone formats, and null/missing field handling.

    Parameters
    ----------
    timeout:
        HTTP request timeout in seconds for every outgoing request.
    """

    def __init__(self, services: dict[str, str] | None = None, timeout: float = 30.0) -> None:
        """Initialize with service URL mapping and HTTP timeout.

        Args:
            services: Mapping of service_name to base URL.
            timeout: HTTP request timeout in seconds.
        """
        self._services = services or {}
        self.timeout = timeout

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def test_case_sensitivity(
        self,
        service_name: str,
        endpoint: str,
        camel_body: dict[str, Any],
        snake_body: dict[str, Any],
        *,
        service_url: str = "",
        test_data: dict[str, Any] | None = None,
    ) -> list[ContractViolation]:
        """Test case sensitivity handling.

        Sends the same data in both camelCase and snake_case formats
        and verifies the service handles both correctly or consistently
        rejects one format.

        Args:
            service_name: Name of the service.
            endpoint: Endpoint path.
            camel_body: Request body with camelCase keys.
            snake_body: Request body with snake_case keys.

        Returns list of ContractViolation for any issues found.
        """
        violations: list[ContractViolation] = []

        # Resolve service URL
        if not service_url:
            service_url = self._services.get(service_name, "")
        if not service_url:
            return []

        snake_payload = snake_body
        camel_payload = camel_body

        url = f"{service_url.rstrip('/')}{endpoint}"

        try:
            async with httpx.AsyncClient(
                timeout=self.timeout,
                follow_redirects=True,
            ) as client:
                snake_resp = await client.post(url, json=snake_payload)
                camel_resp = await client.post(url, json=camel_payload)
        except httpx.HTTPError as exc:
            logger.warning(
                "HTTP error during case-sensitivity test for %s%s: %s",
                service_url,
                endpoint,
                exc,
            )
            return []

        snake_status = snake_resp.status_code
        camel_status = camel_resp.status_code

        # If one variant triggers a 500 but the other does not, the service
        # has an inconsistent / crashy path -- that is a violation.
        snake_crash = snake_status >= 500
        camel_crash = camel_status >= 500

        if snake_crash != camel_crash:
            crashing_format = "snake_case" if snake_crash else "camelCase"
            ok_format = "camelCase" if snake_crash else "snake_case"
            violations.append(
                ContractViolation(
                    code=_CODE_CASE,
                    severity="error",
                    service=service_name,
                    endpoint=endpoint,
                    message=(
                        f"Service crashes (5xx) with {crashing_format} keys "
                        f"but succeeds with {ok_format} keys"
                    ),
                    expected="Consistent handling of both key formats",
                    actual=(
                        f"snake_case={snake_status}, "
                        f"camelCase={camel_status}"
                    ),
                )
            )

        # Informational: different (non-500) status codes hint at
        # inconsistent behaviour worth noting.
        if (
            snake_status != camel_status
            and not snake_crash
            and not camel_crash
        ):
            violations.append(
                ContractViolation(
                    code=_CODE_CASE,
                    severity="warning",
                    service=service_name,
                    endpoint=endpoint,
                    message=(
                        f"Different status codes for snake_case vs "
                        f"camelCase keys"
                    ),
                    expected="Same status code for both key formats",
                    actual=(
                        f"snake_case={snake_status}, "
                        f"camelCase={camel_status}"
                    ),
                )
            )

        return violations

    async def test_timezone_handling(
        self,
        service_name: str,
        endpoint: str,
        timestamps: list[str] | None = None,
        *,
        service_url: str = "",
        test_data: dict[str, Any] | None = None,
    ) -> list[ContractViolation]:
        """Test timezone handling with ISO 8601 variants.

        Args:
            service_name: Name of the service.
            endpoint: Endpoint path.
            timestamps: List of ISO 8601 timestamp strings to test.

        Returns list of ContractViolation for inconsistent handling.
        """
        # Resolve service URL
        if not service_url:
            service_url = self._services.get(service_name, "")
        if not service_url:
            return []

        # Build test_data from timestamps if not provided
        if test_data is None:
            test_data = {}
            if timestamps:
                test_data = {"timestamp": timestamps[0]}
        violations: list[ContractViolation] = []

        # Identify datetime-like fields in test_data.
        datetime_fields = _find_datetime_fields(test_data)
        if not datetime_fields:
            logger.debug(
                "No datetime fields found in test_data for %s%s; "
                "skipping timezone test",
                service_url,
                endpoint,
            )
            return []

        url = f"{service_url.rstrip('/')}{endpoint}"

        try:
            async with httpx.AsyncClient(
                timeout=self.timeout,
                follow_redirects=True,
            ) as client:
                for field_name in datetime_fields:
                    results: list[tuple[str, str, int]] = []

                    for tz_value, tz_label in _TZ_VARIANTS:
                        payload = _replace_field(test_data, field_name, tz_value)
                        resp = await client.post(url, json=payload)
                        results.append((tz_value, tz_label, resp.status_code))

                    # Analyse results: if the service accepts some variants
                    # but crashes (500+) on others, that is a violation.
                    crashing = [
                        (val, label, code)
                        for val, label, code in results
                        if code >= 500
                    ]
                    non_crashing = [
                        (val, label, code)
                        for val, label, code in results
                        if code < 500
                    ]

                    if crashing and non_crashing:
                        crash_labels = ", ".join(
                            f"{label} ({code})"
                            for _, label, code in crashing
                        )
                        ok_labels = ", ".join(
                            f"{label} ({code})"
                            for _, label, code in non_crashing
                        )
                        violations.append(
                            ContractViolation(
                                code=_CODE_TZ,
                                severity="error",
                                service=service_name,
                                endpoint=endpoint,
                                message=(
                                    f"Field '{field_name}': service crashes "
                                    f"on some timezone formats but not others"
                                ),
                                expected=(
                                    "Consistent handling of all ISO 8601 "
                                    "timezone variants"
                                ),
                                actual=(
                                    f"Crashes: [{crash_labels}]; "
                                    f"OK: [{ok_labels}]"
                                ),
                            )
                        )

        except httpx.HTTPError as exc:
            logger.warning(
                "HTTP error during timezone test for %s%s: %s",
                service_url,
                endpoint,
                exc,
            )
            return []

        return violations

    async def test_null_handling(
        self,
        service_name: str,
        endpoint: str,
        field_name: str = "",
        *,
        service_url: str = "",
        test_data: dict[str, Any] | None = None,
    ) -> list[ContractViolation]:
        """Test null, missing, and empty field handling.

        Args:
            service_name: Name of the service.
            endpoint: Endpoint path.
            field_name: Name of the field to test.

        For each field in test_data, tests three variants:
        - Field set to null
        - Field missing entirely
        - Field set to empty string ""

        Returns list of ContractViolation for any unexpected behavior
        (e.g., 500 errors instead of 400/422 validation errors).
        """
        # Resolve service URL
        if not service_url:
            service_url = self._services.get(service_name, "")
        if not service_url:
            return []

        # Build test_data from field_name if not provided
        if test_data is None:
            test_data = {field_name: "test_value"} if field_name else {}
        violations: list[ContractViolation] = []
        url = f"{service_url.rstrip('/')}{endpoint}"

        variant_builders: list[tuple[str, Any]] = [
            ("null", None),
            ("missing", _SENTINEL_MISSING),
            ("empty string", ""),
        ]

        try:
            async with httpx.AsyncClient(
                timeout=self.timeout,
                follow_redirects=True,
            ) as client:
                for field_name in test_data:
                    for variant_label, variant_value in variant_builders:
                        if variant_value is _SENTINEL_MISSING:
                            # Build a payload with the field removed.
                            payload = {
                                k: v
                                for k, v in test_data.items()
                                if k != field_name
                            }
                        else:
                            payload = {**test_data, field_name: variant_value}

                        resp = await client.post(url, json=payload)

                        # A 500+ response to null/missing/empty is a
                        # violation -- the service should return 400 or 422.
                        if resp.status_code >= 500:
                            violations.append(
                                ContractViolation(
                                    code=_CODE_NULL,
                                    severity="error",
                                    service=service_name,
                                    endpoint=endpoint,
                                    message=(
                                        f"Server error {resp.status_code} "
                                        f"when field '{field_name}' is "
                                        f"{variant_label}"
                                    ),
                                    expected="400 or 422 validation error",
                                    actual=str(resp.status_code),
                                )
                            )

        except httpx.HTTPError as exc:
            logger.warning(
                "HTTP error during null-handling test for %s%s: %s",
                service_url,
                endpoint,
                exc,
            )
            return []

        return violations

    async def run_all_boundary_tests(
        self,
        contracts: list[dict[str, Any]],
        service_urls: dict[str, str] | None = None,
        boundary_tests: list[dict[str, Any]] | None = None,
    ) -> list[ContractViolation]:
        """Run all boundary tests across services.

        Each contract dict must contain: service_name, endpoint, method,
        request_schema, response_schema (extracted from OpenAPI specs).

        Args:
            contracts: List of contract dicts from OpenAPI specs.
            service_urls: Optional override for service URLs.
            boundary_tests: Optional pre-generated boundary test dicts.

        Returns aggregated list of ContractViolation from all tests.
        """
        urls = service_urls or self._services
        all_violations: list[ContractViolation] = []

        # If pre-generated boundary tests are provided, dispatch them
        if boundary_tests:
            for test_spec in boundary_tests:
                test_id = test_spec.get("test_id", "<unknown>")
                test_type = test_spec.get("test_type", "")
                service = test_spec.get("service", "")
                endpoint = test_spec.get("endpoint", "")
                test_data = test_spec.get("test_data", {})

                svc_url = urls.get(service, "")
                if not svc_url:
                    continue

                if test_type == "case_sensitivity":
                    violations = await self.test_case_sensitivity(
                        service_name=service,
                        endpoint=endpoint,
                        camel_body=test_data,
                        snake_body=test_data,
                        service_url=svc_url,
                    )
                elif test_type == "timezone_handling":
                    violations = await self.test_timezone_handling(
                        service_name=service,
                        endpoint=endpoint,
                        service_url=svc_url,
                        test_data=test_data,
                    )
                elif test_type == "null_handling":
                    violations = await self.test_null_handling(
                        service_name=service,
                        endpoint=endpoint,
                        service_url=svc_url,
                        test_data=test_data,
                    )
                else:
                    continue
                all_violations.extend(violations)

            return all_violations

        # Generate tests from contracts
        for contract in contracts:
            service_name = contract.get("service_name", "")
            endpoint = contract.get("endpoint", "")
            request_schema = contract.get("request_schema", {})

            svc_url = urls.get(service_name, "")
            if not svc_url or not endpoint:
                continue

            # Generate camel/snake variants from request schema
            properties = request_schema.get("properties", {})
            if properties:
                snake_body = {k: "test" for k in properties}
                camel_body = {_snake_to_camel(k): "test" for k in properties}
                violations = await self.test_case_sensitivity(
                    service_name=service_name,
                    endpoint=endpoint,
                    camel_body=camel_body,
                    snake_body=snake_body,
                    service_url=svc_url,
                )
                all_violations.extend(violations)

        logger.info(
            "Boundary testing complete: %d violation(s) from %d contract(s)",
            len(all_violations),
            len(contracts),
        )

        return all_violations

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    # (none required beyond module-level helpers below)


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------

# Sentinel object used to distinguish "field missing" from "field is None".
_SENTINEL_MISSING = object()


def _snake_to_camel(name: str) -> str:
    """Convert a snake_case string to camelCase.

    Examples
    --------
    >>> _snake_to_camel("my_field_name")
    'myFieldName'
    >>> _snake_to_camel("already")
    'already'
    >>> _snake_to_camel("_leading")
    '_leading'
    """
    parts = name.split("_")
    if len(parts) <= 1:
        return name
    return parts[0] + "".join(word.capitalize() for word in parts[1:])


def _find_datetime_fields(data: dict[str, Any]) -> list[str]:
    """Return names of top-level fields whose values look like ISO 8601 datetimes."""
    fields: list[str] = []
    for key, value in data.items():
        if isinstance(value, str) and _ISO_DATETIME_RE.match(value):
            fields.append(key)
    return fields


def _replace_field(data: dict[str, Any], field: str, value: Any) -> dict[str, Any]:
    """Return a shallow copy of *data* with *field* set to *value*."""
    copy = dict(data)
    copy[field] = value
    return copy


def _service_from_url(url: str) -> str:
    """Extract a human-friendly service identifier from a URL.

    Falls back to the full URL if parsing yields nothing useful.
    """
    # Strip scheme and trailing slashes, take the host part.
    stripped = re.sub(r"^https?://", "", url).rstrip("/")
    return stripped or url

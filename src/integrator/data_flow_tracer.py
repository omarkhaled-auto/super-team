"""Data-flow tracing across service hops using W3C Trace Context.

Provides :class:`DataFlowTracer` which injects ``traceparent`` headers
into outgoing HTTP requests and collects trace records from every
service hop.  Collected records can then be verified against expected
data-transformation rules via :meth:`verify_data_transformations`.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

import httpx

from src.build3_shared.models import ContractViolation

logger = logging.getLogger(__name__)


class DataFlowTracer:
    """Traces data flow across service hops using W3C Trace Context.

    Injects ``traceparent`` headers into requests and collects trace
    records from each service hop to verify data integrity and
    propagation.

    Parameters
    ----------
    timeout:
        HTTP request timeout in seconds.  Defaults to ``30.0``.
    """

    def __init__(self, services: dict[str, str] | None = None, timeout: float = 30.0) -> None:
        """Initialize with service URL mapping and HTTP timeout.

        Args:
            services: Mapping of service_name to base URL.
            timeout: HTTP request timeout in seconds.
        """
        self._services = services or {}
        self._timeout = timeout

    # ------------------------------------------------------------------
    # W3C Trace Context helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _generate_trace_id() -> str:
        """Generate a new UUID4 trace-id as a 32-character hex string."""
        return uuid.uuid4().hex

    @staticmethod
    def _build_traceparent(trace_id: str) -> str:
        """Build a W3C ``traceparent`` header value.

        Format: ``00-{trace_id}-{parent_id}-{flags}``

        * Version is always ``00``.
        * *trace_id* must be a 32-character hex string.
        * Parent-id is fixed to ``0000000000000001`` for the initial
          request originating from the tracer.
        * Flags are ``01`` (sampled).
        """
        return f"00-{trace_id}-0000000000000001-01"

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def trace_request(
        self,
        service_urls: dict[str, str],
        method: str,
        path: str,
        body: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> list[dict[str, Any]]:
        """Trace an HTTP request across service hops.

        Sends a request with a W3C ``traceparent`` header to every
        service listed in *service_urls* (in insertion order) and
        collects trace records from each responding service.

        Parameters
        ----------
        service_urls:
            Ordered mapping of ``service_name`` to base URL.
        method:
            HTTP method (``GET``, ``POST``, etc.).
        path:
            URL path to append to each service base URL.
        body:
            Optional JSON body for the request.
        headers:
            Optional additional headers merged into every request.

        Returns
        -------
        list[dict[str, Any]]
            A trace record for every service hop::

                {
                    "service": "service-a",
                    "status": 200,
                    "body": { ... },
                    "trace_id": "550e8400e29b41d4a716446655440000"
                }
        """
        trace_id = self._generate_trace_id()
        traceparent = self._build_traceparent(trace_id)

        merged_headers: dict[str, str] = {**(headers or {})}
        merged_headers["traceparent"] = traceparent

        trace_records: list[dict[str, Any]] = []

        async with httpx.AsyncClient(
            timeout=self._timeout,
            follow_redirects=True,
        ) as client:
            for service_name, base_url in service_urls.items():
                url = f"{base_url.rstrip('/')}/{path.lstrip('/')}"
                record = await self._send_traced_request(
                    client=client,
                    service_name=service_name,
                    url=url,
                    method=method,
                    body=body,
                    headers=merged_headers,
                    trace_id=trace_id,
                )
                trace_records.append(record)

        logger.info(
            "Traced %s %s across %d service(s) [trace_id=%s]",
            method.upper(),
            path,
            len(trace_records),
            trace_id,
        )
        return trace_records

    async def verify_data_transformations(
        self,
        trace: list[dict[str, Any]],
        expected_transformations: list[dict[str, Any]],
    ) -> list[str]:
        """Verify data transformations across service hops.

        Checks that data flowing between services is transformed
        correctly according to the supplied transformation rules.

        Parameters
        ----------
        trace:
            Records returned by :meth:`trace_request`.
        expected_transformations:
            List of transformation rule dicts.  Each dict must contain:

            * ``hop_index`` -- int, index into the trace list.
            * ``field`` -- field name to check.
            * ``expected_type`` -- expected Python type name (str, int, etc.).
            * ``expected_value_pattern`` -- optional regex or None.

        Returns
        -------
        list[str]
            A list of error message strings (empty if all checks pass).
        """
        errors: list[str] = []

        for tx in expected_transformations:
            hop_index = tx.get("hop_index", 0)
            field_name = tx.get("field", "")
            expected_type = tx.get("expected_type", "")
            expected_value_pattern = tx.get("expected_value_pattern")

            if hop_index >= len(trace) or hop_index < 0:
                errors.append(
                    f"hop_index {hop_index} out of range "
                    f"(trace has {len(trace)} hop(s))"
                )
                continue

            body = trace[hop_index].get("body") or {}
            if not isinstance(body, dict):
                errors.append(
                    f"Hop {hop_index}: body is not a dict"
                )
                continue

            if field_name not in body:
                errors.append(
                    f"Hop {hop_index}: field '{field_name}' not found"
                )
                continue

            value = body[field_name]
            actual_type = type(value).__name__

            if expected_type and actual_type != expected_type:
                errors.append(
                    f"Hop {hop_index}: field '{field_name}' expected type "
                    f"'{expected_type}', got '{actual_type}'"
                )

            if expected_value_pattern is not None:
                import re
                if not re.search(expected_value_pattern, str(value)):
                    errors.append(
                        f"Hop {hop_index}: field '{field_name}' value "
                        f"'{value}' does not match pattern "
                        f"'{expected_value_pattern}'"
                    )

        if errors:
            logger.warning(
                "Data-flow verification found %d error(s)", len(errors),
            )
        else:
            logger.info("Data-flow verification passed with no errors")

        return errors

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    async def _send_traced_request(
        self,
        *,
        client: httpx.AsyncClient,
        service_name: str,
        url: str,
        method: str,
        body: dict[str, Any] | None,
        headers: dict[str, str],
        trace_id: str,
    ) -> dict[str, Any]:
        """Send a single traced HTTP request and return a trace record.

        On failure the record still contains the *service* and
        *trace_id* but carries a non-200 status and an error body.
        """
        try:
            response = await client.request(
                method=method.upper(),
                url=url,
                json=body,
                headers=headers,
            )

            # Attempt to parse a JSON body; fall back to raw text.
            try:
                response_body = response.json()
            except (ValueError, TypeError):
                response_body = {"_raw": response.text}

            record: dict[str, Any] = {
                "service": service_name,
                "status": response.status_code,
                "body": response_body,
                "trace_id": trace_id,
            }

            logger.debug(
                "Hop %s -> %d %s",
                service_name,
                response.status_code,
                url,
            )
            return record

        except httpx.TimeoutException as exc:
            logger.error(
                "Timeout contacting service '%s' at %s: %s",
                service_name,
                url,
                exc,
            )
            return {
                "service": service_name,
                "status": 504,
                "body": {"error": f"Timeout: {exc}"},
                "trace_id": trace_id,
            }
        except httpx.ConnectError as exc:
            logger.error(
                "Connection error for service '%s' at %s: %s",
                service_name,
                url,
                exc,
            )
            return {
                "service": service_name,
                "status": 502,
                "body": {"error": f"Connection error: {exc}"},
                "trace_id": trace_id,
            }
        except httpx.HTTPError as exc:
            logger.error(
                "HTTP error for service '%s' at %s: %s",
                service_name,
                url,
                exc,
            )
            return {
                "service": service_name,
                "status": 500,
                "body": {"error": f"HTTP error: {exc}"},
                "trace_id": trace_id,
            }

    @staticmethod
    def _check_transform(
        *,
        transform: str,
        field_name: str,
        source_service: str,
        target_service: str,
        source_field: str,
        target_field: str,
        source_body: dict[str, Any],
        target_body: dict[str, Any],
    ) -> ContractViolation | None:
        """Check a single transformation rule and return a violation or *None*.

        Supported transforms:

        ``passthrough``
            The value at *source_field* in the source body must be
            identical to the value at *target_field* in the target body.

        ``rename``
            Semantically equivalent to ``passthrough`` -- the value at
            *source_field* must equal the value at *target_field*, but
            the key names are allowed to differ.

        ``format``
            Both fields must be present and non-``None``.  The actual
            values are not compared (only existence is asserted).
        """
        source_value = source_body.get(source_field)
        target_value = target_body.get(target_field)

        if transform == "passthrough":
            # Source field must exist.
            if source_field not in source_body:
                return ContractViolation(
                    code="DATAFLOW-002",
                    severity="error",
                    service=source_service,
                    endpoint="",
                    message=(
                        f"Field '{source_field}' missing in source service "
                        f"'{source_service}' for passthrough of '{field_name}'"
                    ),
                    expected=source_field,
                    actual="<missing>",
                )
            # Target field must exist.
            if target_field not in target_body:
                return ContractViolation(
                    code="DATAFLOW-002",
                    severity="error",
                    service=target_service,
                    endpoint="",
                    message=(
                        f"Field '{target_field}' missing in target service "
                        f"'{target_service}' for passthrough of '{field_name}'"
                    ),
                    expected=target_field,
                    actual="<missing>",
                )
            # Values must be identical.
            if source_value != target_value:
                return ContractViolation(
                    code="DATAFLOW-003",
                    severity="error",
                    service=target_service,
                    endpoint="",
                    message=(
                        f"Passthrough mismatch for '{field_name}': "
                        f"'{source_service}'.{source_field} != "
                        f"'{target_service}'.{target_field}"
                    ),
                    expected=str(source_value),
                    actual=str(target_value),
                )
            return None

        if transform == "rename":
            # Source field must exist.
            if source_field not in source_body:
                return ContractViolation(
                    code="DATAFLOW-002",
                    severity="error",
                    service=source_service,
                    endpoint="",
                    message=(
                        f"Field '{source_field}' missing in source service "
                        f"'{source_service}' for rename of '{field_name}'"
                    ),
                    expected=source_field,
                    actual="<missing>",
                )
            # Target field must exist.
            if target_field not in target_body:
                return ContractViolation(
                    code="DATAFLOW-002",
                    severity="error",
                    service=target_service,
                    endpoint="",
                    message=(
                        f"Field '{target_field}' missing in target service "
                        f"'{target_service}' for rename of '{field_name}'"
                    ),
                    expected=target_field,
                    actual="<missing>",
                )
            # Values must be equal despite differing key names.
            if source_value != target_value:
                return ContractViolation(
                    code="DATAFLOW-003",
                    severity="error",
                    service=target_service,
                    endpoint="",
                    message=(
                        f"Rename mismatch for '{field_name}': "
                        f"'{source_service}'.{source_field} != "
                        f"'{target_service}'.{target_field}"
                    ),
                    expected=str(source_value),
                    actual=str(target_value),
                )
            return None

        if transform == "format":
            # Both fields must be present and non-None.
            if source_field not in source_body or source_value is None:
                return ContractViolation(
                    code="DATAFLOW-002",
                    severity="error",
                    service=source_service,
                    endpoint="",
                    message=(
                        f"Field '{source_field}' missing or null in source "
                        f"service '{source_service}' for format check of "
                        f"'{field_name}'"
                    ),
                    expected=f"{source_field} (non-null)",
                    actual=str(source_value),
                )
            if target_field not in target_body or target_value is None:
                return ContractViolation(
                    code="DATAFLOW-002",
                    severity="error",
                    service=target_service,
                    endpoint="",
                    message=(
                        f"Field '{target_field}' missing or null in target "
                        f"service '{target_service}' for format check of "
                        f"'{field_name}'"
                    ),
                    expected=f"{target_field} (non-null)",
                    actual=str(target_value),
                )
            return None

        # Unknown transform -- emit a warning-level violation.
        return ContractViolation(
            code="DATAFLOW-004",
            severity="warning",
            service=source_service,
            endpoint="",
            message=(
                f"Unknown transform type '{transform}' for field "
                f"'{field_name}' between '{source_service}' and "
                f"'{target_service}'"
            ),
            expected="passthrough | rename | format",
            actual=transform,
        )

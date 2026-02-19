"""Cross-service integration test runner.

Executes cross-service integration test flows against running services.
Takes flow definitions (from CrossServiceTestGenerator) and runs
multi-step request chains, propagating response data between steps
via template variable resolution.

This module is part of Milestone 3 of the super-team pipeline and satisfies
TECH-016 (template variable resolution): template variables in request
templates are resolved from previous step responses using the pattern
``{step_N_response.field_name}``.
"""

from __future__ import annotations

import copy
import json
import logging
import re
from typing import Any

import httpx

from src.build3_shared.models import ContractViolation, IntegrationReport

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Regex pattern for template variable references.
# Matches: {step_0_response.field_name}
_TEMPLATE_VAR_PATTERN = re.compile(r"\{step_(\d+)_response\.([^}]+)\}")

# Violation codes
_VIOLATION_STATUS_MISMATCH = "FLOW-001"
_VIOLATION_CONNECTION_ERROR = "FLOW-002"
_VIOLATION_TEMPLATE_ERROR = "FLOW-003"


class CrossServiceTestRunner:
    """Executes cross-service integration test flows against running services.

    Takes flow definitions (from CrossServiceTestGenerator) and runs
    multi-step request chains, propagating response data between steps
    via template variable resolution.
    """

    def __init__(self, services: dict[str, str] | None = None, timeout: float = 30.0) -> None:
        """Initialize with service URL mapping and HTTP timeout.

        Args:
            services: Mapping of service_name to base URL.
            timeout: HTTP request timeout in seconds. Applied to every
                outgoing request made during flow execution.
        """
        self._services = services or {}
        self._timeout = timeout

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def run_flow_tests(
        self,
        flows: list[dict[str, Any]],
        service_urls: dict[str, str] | None = None,
    ) -> IntegrationReport:
        """Execute all flow tests.

        Iterates over every flow definition and executes each one
        sequentially via :meth:`run_single_flow`.

        Parameters
        ----------
        flows:
            List of flow dicts from
            ``CrossServiceTestGenerator.generate_flow_tests()``.
        service_urls:
            Optional override for service URLs. If not provided, uses
            the URLs from ``__init__``.

        Returns
        -------
        IntegrationReport
            Aggregated report with test counts and violations.
        """
        urls = service_urls or self._services
        all_violations: list[ContractViolation] = []
        passed = 0
        total = len(flows)

        for flow in flows:
            flow_id = flow.get("flow_id", "unknown")
            logger.info("Running flow test: %s", flow_id)

            success, errors = await self.run_single_flow(flow, urls)

            if success:
                passed += 1
                logger.info("Flow %s passed", flow_id)
            else:
                logger.warning(
                    "Flow %s failed: %s", flow_id, "; ".join(errors),
                )
                for err_msg in errors:
                    all_violations.append(
                        ContractViolation(
                            code="FLOW-001",
                            severity="error",
                            service=flow_id,
                            endpoint="",
                            message=err_msg,
                        )
                    )

        logger.info(
            "Flow test run complete: %d/%d passed", passed, total,
        )

        return IntegrationReport(
            integration_tests_passed=passed,
            integration_tests_total=total,
            violations=all_violations,
            overall_health="passed" if passed == total else "failed",
        )

    async def run_single_flow(
        self,
        flow: dict[str, Any],
        service_urls: dict[str, str] | None = None,
    ) -> tuple[bool, list[str]]:
        """Execute a single flow test.

        Executes each step sequentially, resolving template variables
        from previous step responses.  Passes response data from step N
        as request data for step N+1.

        Parameters
        ----------
        flow:
            A single flow dict containing ``flow_id``, ``description``,
            and ``steps``.
        service_urls:
            Optional override for service URLs. If not provided, uses
            the URLs from ``__init__``.

        Returns
        -------
        tuple[bool, list[str]]
            (success, error_messages)
        """
        urls = service_urls or self._services
        flow_id: str = flow.get("flow_id", "unknown")
        steps: list[dict[str, Any]] = flow.get("steps", [])
        total_steps = len(steps)

        step_responses: dict[int, dict[str, Any]] = {}
        steps_completed = 0
        errors: list[str] = []

        async with httpx.AsyncClient(
            timeout=self._timeout,
            follow_redirects=True,
        ) as client:
            for step_index, step in enumerate(steps):
                service = step.get("service", "")
                method = step.get("method", "GET").upper()
                path = step.get("path", "/")
                request_template = step.get("request_template", {})
                expected_status = step.get("expected_status", 200)

                # --- Validate service URL availability ---
                base_url = urls.get(service)
                if base_url is None:
                    msg = (
                        f"Service URL not found for '{service}' "
                        f"at step {step_index}"
                    )
                    logger.error("Flow %s: %s", flow_id, msg)
                    errors.append(msg)
                    break

                # --- Resolve template variables ---
                try:
                    resolved_body = self._resolve_templates(
                        request_template, step_responses,
                    )
                except _TemplateResolutionError as exc:
                    msg = (
                        f"Template resolution failed at step {step_index}: "
                        f"{exc}"
                    )
                    logger.error("Flow %s: %s", flow_id, msg)
                    errors.append(msg)
                    break

                # --- Build full URL ---
                url = base_url.rstrip("/") + path

                # --- Execute HTTP request ---
                try:
                    logger.debug(
                        "Flow %s step %d: %s %s (service=%s)",
                        flow_id, step_index, method, url, service,
                    )

                    if resolved_body:
                        response = await client.request(
                            method, url, json=resolved_body,
                        )
                    else:
                        response = await client.request(method, url)

                except httpx.HTTPError as exc:
                    msg = (
                        f"HTTP error at step {step_index} "
                        f"({method} {url}): {exc}"
                    )
                    logger.error("Flow %s: %s", flow_id, msg)
                    errors.append(msg)
                    break

                # --- Check response status ---
                actual_status = response.status_code
                if actual_status != expected_status:
                    msg = (
                        f"Status mismatch at step {step_index} "
                        f"({method} {path}): "
                        f"expected {expected_status}, got {actual_status}"
                    )
                    logger.warning("Flow %s: %s", flow_id, msg)
                    errors.append(msg)
                    break

                # --- Store response body for template resolution ---
                try:
                    response_body = response.json()
                except (json.JSONDecodeError, ValueError):
                    response_body = {}

                if isinstance(response_body, dict):
                    step_responses[step_index] = response_body
                else:
                    step_responses[step_index] = {"_value": response_body}

                steps_completed += 1

        success = steps_completed == total_steps and not errors
        return (success, errors)

    # ------------------------------------------------------------------
    # Private: template resolution
    # ------------------------------------------------------------------

    @staticmethod
    def _resolve_templates(
        template: dict[str, Any],
        step_responses: dict[int, dict[str, Any]],
    ) -> dict[str, Any]:
        """Resolve template variables in a request template dict.

        Deep-copies the template, then walks through all string values
        and replaces occurrences of ``{step_N_response.field_name}`` with
        the corresponding value from the stored step responses.

        Nested dicts and lists are handled by JSON-serialising the entire
        template, performing regex-based replacement on the serialised
        string, then deserialising back to a dict.

        Args:
            template: The request template dict (may contain template
                variable placeholders in string values).
            step_responses: Mapping of step index to the JSON response
                body dict from that step.

        Returns:
            A new dict with all template variables resolved.

        Raises:
            _TemplateResolutionError: If a template variable references a
                step that has not yet executed or a field that does not
                exist in the referenced step's response.
        """
        if not template:
            return {}

        # Deep-copy to avoid mutating the original template
        resolved = copy.deepcopy(template)

        # Serialise to JSON string for uniform replacement across all
        # nesting levels.
        serialised = json.dumps(resolved)

        # Find all template variable references
        matches = list(_TEMPLATE_VAR_PATTERN.finditer(serialised))
        if not matches:
            return resolved

        # Process matches in reverse order so that replacements don't
        # shift positions of earlier matches.
        for match in reversed(matches):
            step_idx = int(match.group(1))
            field_name = match.group(2)

            # Validate step index
            if step_idx not in step_responses:
                raise _TemplateResolutionError(
                    f"step_{step_idx}_response is not available "
                    f"(step {step_idx} has not executed yet or failed)"
                )

            step_data = step_responses[step_idx]

            # Validate field existence
            if field_name not in step_data:
                raise _TemplateResolutionError(
                    f"Field '{field_name}' not found in "
                    f"step_{step_idx}_response. "
                    f"Available fields: {sorted(step_data.keys())}"
                )

            value = step_data[field_name]

            # Determine the replacement string.  If the template var is
            # the entire JSON string value (i.e. the match is surrounded
            # by double-quotes), we can replace with the JSON
            # representation of the value directly.  Otherwise we
            # stringify it for embedding inside a larger string.
            match_start = match.start()
            match_end = match.end()

            # Check if the match is the sole content of a JSON string
            # value: pattern is "...{step_N_response.field}..."
            if (
                match_start >= 1
                and match_end < len(serialised)
                and serialised[match_start - 1] == '"'
                and serialised[match_end] == '"'
                and serialised[match_start - 1:match_start] == '"'
                and serialised[match_end:match_end + 1] == '"'
                # Ensure there's nothing else inside the quotes
                and _is_sole_content_of_json_string(
                    serialised, match_start, match_end,
                )
            ):
                # Replace the entire quoted string with the JSON-encoded
                # value (which includes quotes for strings, bare numbers
                # for ints, etc.)
                replacement = json.dumps(value)
                serialised = (
                    serialised[:match_start - 1]
                    + replacement
                    + serialised[match_end + 1:]
                )
            else:
                # The template var is embedded in a larger string; convert
                # to string representation for inline replacement.
                replacement = str(value)
                serialised = (
                    serialised[:match_start]
                    + replacement
                    + serialised[match_end:]
                )

        try:
            return json.loads(serialised)
        except json.JSONDecodeError as exc:
            raise _TemplateResolutionError(
                f"Failed to deserialise resolved template: {exc}"
            ) from exc


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

class _TemplateResolutionError(Exception):
    """Raised when template variable resolution fails."""


def _is_sole_content_of_json_string(
    serialised: str,
    match_start: int,
    match_end: int,
) -> bool:
    """Check if a regex match is the sole content of a JSON string value.

    Verifies that between the opening quote (at ``match_start - 1``)
    and the match start there is no other content, and between the
    match end and the closing quote (at ``match_end``) there is no
    other content.

    Args:
        serialised: The full JSON-serialised string.
        match_start: Start index of the regex match.
        match_end: End index of the regex match.

    Returns:
        ``True`` if the match is the entire content between quotes.
    """
    # Walk backwards from match_start - 1 to find the opening quote
    # (skipping escaped characters).
    quote_before = match_start - 1
    if quote_before < 0 or serialised[quote_before] != '"':
        return False

    # Walk forwards from match_end to find the closing quote.
    quote_after = match_end
    if quote_after >= len(serialised) or serialised[quote_after] != '"':
        return False

    # The match must be the sole content between the two quotes.
    content_between_open_and_match = serialised[quote_before + 1:match_start]
    content_between_match_and_close = serialised[match_end:quote_after]

    return (
        content_between_open_and_match == ""
        and content_between_match_and_close == ""
    )


def _violation_to_dict(violation: ContractViolation) -> dict[str, Any]:
    """Convert a ContractViolation dataclass to a plain dict.

    Args:
        violation: The violation instance.

    Returns:
        A JSON-serialisable dict representation.
    """
    return {
        "code": violation.code,
        "severity": violation.severity,
        "service": violation.service,
        "endpoint": violation.endpoint,
        "message": violation.message,
        "expected": violation.expected,
        "actual": violation.actual,
        "file_path": violation.file_path,
        "line": violation.line,
    }

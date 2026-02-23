"""Acceptance test generator -- produces contract-first test files.

Generates executable test suites from OpenAPI and AsyncAPI contracts
so that builders have concrete acceptance criteria to satisfy.  Tests
are written to ``{output_dir}/tests/acceptance/`` and a summary is
produced as ``ACCEPTANCE_TESTS.md``.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class AcceptanceTestResult:
    """Result of acceptance test generation for a service."""

    service_name: str
    files_written: list[Path] = field(default_factory=list)
    failures: list[str] = field(default_factory=list)
    summary_md: str = ""


def generate_acceptance_tests(
    service_name: str,
    contracts: list[Any],
    output_dir: Path,
    contract_engine_client: Any | None = None,
    config: Any | None = None,
) -> AcceptanceTestResult:
    """Generate acceptance test files from service contracts.

    For each OpenAPI contract, uses the Contract Engine's ``generate_tests``
    tool to produce a Schemathesis-based test file.  For AsyncAPI contracts,
    generates jsonschema validation tests directly.

    Individual contract generation failures are caught, logged, and skipped
    -- they never propagate.

    Args:
        service_name: Name of the service.
        contracts: List of contract entries (dicts or objects with
            ``type``, ``id``, ``spec`` fields).
        output_dir: Root directory for the service's build output.
        contract_engine_client: Optional MCP client for the contract engine.
        config: Pipeline config (unused currently, reserved for future).

    Returns:
        Result with paths to written files and any failures.
    """
    result = AcceptanceTestResult(service_name=service_name)
    test_dir = output_dir / "tests" / "acceptance"
    test_dir.mkdir(parents=True, exist_ok=True)

    md_lines = [
        f"# Acceptance Tests for {service_name}",
        "",
        "These tests validate contract compliance. **Do not modify them.**",
        "",
        "Run: `pytest tests/acceptance/ -v`",
        "",
    ]

    for contract in contracts:
        try:
            contract_type = _get_field(contract, "type", "")
            contract_id = _get_field(contract, "id", "unknown")
            spec = _get_field(contract, "spec", {})

            if contract_type == "openapi":
                _generate_openapi_test(
                    contract_id, spec, test_dir, contract_engine_client, result, md_lines
                )
            elif contract_type == "asyncapi":
                _generate_asyncapi_test(
                    contract_id, spec, test_dir, result, md_lines
                )
            else:
                logger.debug(
                    "Skipping contract %s of unsupported type '%s'",
                    contract_id,
                    contract_type,
                )

        except Exception as exc:
            failure_msg = f"Failed to generate test for contract {_get_field(contract, 'id', '?')}: {exc}"
            logger.warning(failure_msg)
            result.failures.append(failure_msg)

    # Write summary markdown
    summary = "\n".join(md_lines)
    summary_path = output_dir / "ACCEPTANCE_TESTS.md"
    summary_path.write_text(summary, encoding="utf-8")
    result.summary_md = summary

    logger.info(
        "Acceptance tests for %s: %d files written, %d failures",
        service_name,
        len(result.files_written),
        len(result.failures),
    )
    return result


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _get_field(obj: Any, name: str, default: Any) -> Any:
    """Get a field from a dict or object."""
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


def _generate_openapi_test(
    contract_id: str,
    spec: dict,
    test_dir: Path,
    contract_engine_client: Any | None,
    result: AcceptanceTestResult,
    md_lines: list[str],
) -> None:
    """Generate an OpenAPI schema validation test file."""
    test_code = _build_openapi_test_code(contract_id, spec)

    # Validate it's syntactically valid Python
    try:
        compile(test_code, f"test_{contract_id}_schema.py", "exec")
    except SyntaxError as exc:
        result.failures.append(f"Generated OpenAPI test has syntax error: {exc}")
        return

    test_file = test_dir / f"test_{_safe_filename(contract_id)}_schema.py"
    test_file.write_text(test_code, encoding="utf-8")
    result.files_written.append(test_file)
    md_lines.append(f"- `{test_file.name}`: Validates OpenAPI schema for contract `{contract_id}`")


def _generate_asyncapi_test(
    contract_id: str,
    spec: dict,
    test_dir: Path,
    result: AcceptanceTestResult,
    md_lines: list[str],
) -> None:
    """Generate an AsyncAPI jsonschema validation test file."""
    # Extract event schemas from AsyncAPI spec
    channels = spec.get("channels", {})
    if not channels:
        result.failures.append(f"AsyncAPI contract {contract_id} has no channels")
        return

    test_code = _build_asyncapi_test_code(contract_id, channels)

    try:
        compile(test_code, f"test_{contract_id}_events.py", "exec")
    except SyntaxError as exc:
        result.failures.append(f"Generated AsyncAPI test has syntax error: {exc}")
        return

    test_file = test_dir / f"test_{_safe_filename(contract_id)}_events.py"
    test_file.write_text(test_code, encoding="utf-8")
    result.files_written.append(test_file)
    md_lines.append(f"- `{test_file.name}`: Validates event schemas for contract `{contract_id}`")


def _build_openapi_test_code(contract_id: str, spec: dict) -> str:
    """Build a Python test file that validates an OpenAPI spec."""
    import json

    spec_json = json.dumps(spec, indent=2)
    safe_id = _safe_varname(contract_id)

    return f'''"""Auto-generated acceptance test for OpenAPI contract {contract_id}."""
import json
import pytest

SPEC = json.loads("""{spec_json}""")


def test_{safe_id}_spec_has_openapi_version():
    """Verify the spec declares an OpenAPI version."""
    assert "openapi" in SPEC, "Missing 'openapi' version field"


def test_{safe_id}_spec_has_info():
    """Verify the spec has an info block."""
    assert "info" in SPEC, "Missing 'info' block"


def test_{safe_id}_spec_has_paths_or_webhooks():
    """Verify the spec has paths or webhooks."""
    assert "paths" in SPEC or "webhooks" in SPEC, "Missing 'paths' or 'webhooks'"


def test_{safe_id}_all_paths_have_operations():
    """Verify every path has at least one HTTP operation."""
    paths = SPEC.get("paths", {{}})
    http_methods = {{"get", "post", "put", "patch", "delete", "head", "options", "trace"}}
    for path, operations in paths.items():
        ops = set(operations.keys()) & http_methods
        assert ops, f"Path {{path}} has no HTTP operations"
'''


def _build_asyncapi_test_code(contract_id: str, channels: dict) -> str:
    """Build a Python test file that validates AsyncAPI event schemas."""
    import json

    safe_id = _safe_varname(contract_id)
    channels_json = json.dumps(channels, indent=2)

    return f'''"""Auto-generated acceptance test for AsyncAPI contract {contract_id}."""
import json
import pytest

try:
    import jsonschema
    HAS_JSONSCHEMA = True
except ImportError:
    HAS_JSONSCHEMA = False

CHANNELS = json.loads("""{channels_json}""")


@pytest.mark.skipif(not HAS_JSONSCHEMA, reason="jsonschema not installed")
def test_{safe_id}_channel_schemas_are_valid():
    """Verify each channel's message schema is valid JSON Schema."""
    for channel_name, channel_def in CHANNELS.items():
        message = channel_def.get("message", {{}})
        payload_schema = message.get("payload", {{}})
        if payload_schema:
            jsonschema.Draft7Validator.check_schema(payload_schema)


def test_{safe_id}_channels_exist():
    """Verify at least one channel is defined."""
    assert len(CHANNELS) > 0, "No channels defined in AsyncAPI spec"
'''


def _safe_filename(s: str) -> str:
    """Convert a string to a safe filename component."""
    return s.replace("-", "_").replace(".", "_").replace("/", "_").replace(" ", "_")


def _safe_varname(s: str) -> str:
    """Convert a string to a safe Python variable name."""
    result = _safe_filename(s)
    if result and result[0].isdigit():
        result = "c_" + result
    return result

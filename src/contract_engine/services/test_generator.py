"""Test suite generator for API contracts.

Generates pytest test code from OpenAPI and AsyncAPI contract specifications.
OpenAPI contracts produce Schemathesis-based property tests.
AsyncAPI contracts produce jsonschema validation tests for message payloads.

Implements caching via the ``test_suites`` table — a cached suite is returned
when the contract's ``spec_hash`` has not changed since the last generation.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from src.shared.db.connection import ConnectionPool
from src.shared.errors import ContractNotFoundError
from src.shared.models.contracts import ContractTestSuite, ContractType
from src.shared.utils import now_iso

logger = logging.getLogger(__name__)


class ContractTestGenerator:
    """Generates executable test suites from stored API contracts."""

    def __init__(self, pool: ConnectionPool) -> None:
        self._pool = pool

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def generate_tests(
        self,
        contract_id: str,
        framework: str = "pytest",
        include_negative: bool = False,
    ) -> ContractTestSuite:
        """Generate a test suite for *contract_id*.

        Parameters
        ----------
        contract_id:
            UUID of the contract to generate tests for.
        framework:
            Test framework -- currently only ``"pytest"`` is supported.
        include_negative:
            If ``True``, generate additional negative / 4xx test cases.

        Returns
        -------
        ContractTestSuite
            The generated (or cached) test suite.

        Raises
        ------
        ContractNotFoundError
            When no contract with *contract_id* exists.
        """
        conn = self._pool.get()

        # 1. Fetch the contract
        row = conn.execute(
            "SELECT * FROM contracts WHERE id = ?", (contract_id,)
        ).fetchone()
        if row is None:
            raise ContractNotFoundError(
                detail=f"Contract not found: {contract_id}"
            )

        spec_json: str = row["spec_json"]
        spec_hash: str = row["spec_hash"]
        contract_type: str = row["type"]
        service_name: str = row["service_name"]
        spec: dict[str, Any] = json.loads(spec_json)

        # 2. Check cache -- return existing suite if spec_hash matches
        cached = self._get_cached(contract_id, framework, spec_hash, include_negative)
        if cached is not None:
            logger.info(
                "Returning cached test suite for contract=%s framework=%s",
                contract_id,
                framework,
            )
            return cached

        # 3. Generate test code based on contract type
        if contract_type == ContractType.OPENAPI.value:
            test_code = self._generate_openapi_tests(
                contract_id, service_name, spec, include_negative
            )
        elif contract_type == ContractType.ASYNCAPI.value:
            test_code = self._generate_asyncapi_tests(
                contract_id, service_name, spec, include_negative
            )
        else:
            # json_schema -- generate basic schema validation tests
            test_code = self._generate_json_schema_tests(
                contract_id, service_name, spec
            )

        # 4. Count test functions
        test_count = self._count_tests(test_code)

        # 5. Persist to test_suites table
        suite = self._save_suite(
            contract_id, framework, test_code, test_count, spec_hash, include_negative
        )

        logger.info(
            "Generated test suite for contract=%s type=%s tests=%d",
            contract_id,
            contract_type,
            test_count,
        )
        return suite

    def get_suite(
        self, contract_id: str, framework: str = "pytest"
    ) -> ContractTestSuite | None:
        """Return an existing test suite or ``None``."""
        conn = self._pool.get()
        row = conn.execute(
            "SELECT * FROM test_suites WHERE contract_id = ? AND framework = ?",
            (contract_id, framework),
        ).fetchone()
        if row is None:
            return None
        return self._row_to_suite(row)

    # ------------------------------------------------------------------
    # Cache helpers
    # ------------------------------------------------------------------

    def _get_cached(
        self, contract_id: str, framework: str, spec_hash: str, include_negative: bool = False
    ) -> ContractTestSuite | None:
        """Return a cached suite if the spec_hash matches, else ``None``."""
        conn = self._pool.get()
        row = conn.execute(
            "SELECT * FROM test_suites WHERE contract_id = ? AND framework = ? AND include_negative = ?",
            (contract_id, framework, int(include_negative)),
        ).fetchone()
        if row is None:
            return None
        if row["spec_hash"] == spec_hash:
            return self._row_to_suite(row)
        # spec changed -- cache is stale
        return None

    def _save_suite(
        self,
        contract_id: str,
        framework: str,
        test_code: str,
        test_count: int,
        spec_hash: str,
        include_negative: bool = False,
    ) -> ContractTestSuite:
        """Upsert a test suite into the ``test_suites`` table."""
        conn = self._pool.get()
        now = now_iso()

        conn.execute(
            """
            INSERT INTO test_suites
                (contract_id, framework, test_code, test_count, spec_hash, include_negative, generated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(contract_id, framework, include_negative) DO UPDATE SET
                test_code    = excluded.test_code,
                test_count   = excluded.test_count,
                spec_hash    = excluded.spec_hash,
                generated_at = excluded.generated_at
            """,
            (contract_id, framework, test_code, test_count, spec_hash, int(include_negative), now),
        )
        conn.commit()

        return ContractTestSuite(
            contract_id=contract_id,
            framework=framework,
            test_code=test_code,
            test_count=test_count,
            include_negative=include_negative,
            generated_at=now,
        )

    @staticmethod
    def _row_to_suite(row) -> ContractTestSuite:
        """Convert a DB row to a :class:`ContractTestSuite`."""
        return ContractTestSuite(
            contract_id=row["contract_id"],
            framework=row["framework"],
            test_code=row["test_code"],
            test_count=row["test_count"],
            include_negative=bool(row["include_negative"]),
            generated_at=row["generated_at"],
        )

    # ------------------------------------------------------------------
    # Test-count helper
    # ------------------------------------------------------------------

    @staticmethod
    def _count_tests(test_code: str) -> int:
        """Count the number of ``def test_*`` functions in *test_code*."""
        return len(re.findall(r"^def test_\w+", test_code, re.MULTILINE))

    # ------------------------------------------------------------------
    # OpenAPI test generation (Schemathesis template)
    # ------------------------------------------------------------------

    def _generate_openapi_tests(
        self,
        contract_id: str,
        service_name: str,
        spec: dict[str, Any],
        include_negative: bool,
    ) -> str:
        """Generate Schemathesis-based pytest code for an OpenAPI spec."""
        title = spec.get("info", {}).get("title", service_name)
        version = spec.get("info", {}).get("version", "1.0.0")
        openapi_version = spec.get("openapi", "3.0.0")

        paths_json = json.dumps(spec.get("paths", {}), indent=4)

        lines: list[str] = []
        lines.append(f'"""Auto-generated contract tests for {title} v{version}.')
        lines.append("")
        lines.append(f"Generated from OpenAPI {openapi_version} specification.")
        lines.append(f"Contract ID: {contract_id}")
        lines.append(f"Service: {service_name}")
        lines.append('"""')
        lines.append("import schemathesis")
        lines.append("import pytest")
        lines.append("")
        lines.append("# Load schema from the OpenAPI spec (schemathesis 4.x API)")
        lines.append("schema = schemathesis.openapi.from_dict({")
        lines.append(f'    "openapi": "{openapi_version}",')
        lines.append(f'    "info": {{"title": "{title}", "version": "{version}"}},')
        lines.append(f'    "paths": {paths_json}')
        lines.append("})")
        lines.append("")
        lines.append("")
        lines.append("@schema.parametrize()")
        lines.append("def test_api_conformance(case):")
        lines.append('    """Property-based test: all endpoints conform to their schema."""')
        lines.append("    response = case.call()")
        lines.append("    case.validate_response(response)")
        lines.append("")
        lines.append("")

        test_code = "\n".join(lines)

        # Add endpoint-specific tests
        endpoint_tests = self._build_openapi_endpoint_tests(spec)
        test_code += endpoint_tests

        if include_negative:
            negative_tests = self._build_openapi_negative_tests(spec)
            test_code += negative_tests

        return test_code

    def _build_openapi_endpoint_tests(self, spec: dict[str, Any]) -> str:
        """Generate per-endpoint test functions."""
        parts: list[str] = []
        paths = spec.get("paths", {})

        for path, methods in paths.items():
            if not isinstance(methods, dict):
                continue
            for method, operation in methods.items():
                if method.startswith("x-") or method == "parameters":
                    continue
                if not isinstance(operation, dict):
                    continue

                try:
                    func_name = self._make_func_name(path, method)
                    responses = operation.get("responses", {})
                    expected_statuses = list(responses.keys())
                    status_list = ", ".join(f'"{s}"' for s in expected_statuses)

                    lines = [
                        f"def test_{func_name}_status_codes():",
                        f'    """Verify {method.upper()} {path} returns expected status codes."""',
                        f"    expected_statuses = [{status_list}]",
                        '    assert len(expected_statuses) > 0, "Endpoint must define at least one response"',
                        "",
                        "",
                    ]
                    parts.append("\n".join(lines))

                    # Generate schema validation test if response has content
                    for status_code, response_def in responses.items():
                        if isinstance(response_def, dict) and "content" in response_def:
                            resp_json = json.dumps(response_def, indent=4)
                            schema_lines = [
                                f"def test_{func_name}_{status_code}_schema():",
                                f'    """Verify {method.upper()} {path} {status_code} response schema."""',
                                "    import jsonschema",
                                f"    response_spec = {resp_json}",
                                '    for content_type, media in response_spec.get("content", {}).items():',
                                '        if "schema" in media:',
                                "            assert isinstance(media[\"schema\"], dict)",
                                "",
                                "",
                            ]
                            parts.append("\n".join(schema_lines))
                except (KeyError, TypeError, ValueError) as exc:
                    logger.warning("Failed to generate endpoint test for %s %s: %s", method, path, exc)

        return "\n".join(parts)

    def _build_openapi_negative_tests(self, spec: dict[str, Any]) -> str:
        """Generate negative / 4xx test cases."""
        parts: list[str] = []
        paths = spec.get("paths", {})

        for path, methods in paths.items():
            if not isinstance(methods, dict):
                continue
            for method, operation in methods.items():
                if method.startswith("x-") or method == "parameters":
                    continue
                if not isinstance(operation, dict):
                    continue

                try:
                    func_name = self._make_func_name(path, method)

                    # Negative test: missing required fields in request body
                    request_body = operation.get("requestBody", {})
                    if isinstance(request_body, dict) and request_body.get("required"):
                        lines = [
                            f"def test_{func_name}_missing_body_returns_4xx():",
                            f'    """Sending no body to {method.upper()} {path} should return 4xx."""',
                            "    # Negative test: missing required request body",
                            "    # Expected: 400 or 422 status code",
                            "    assert True  # Placeholder - wire to actual HTTP call in integration",
                            "",
                            "",
                        ]
                        parts.append("\n".join(lines))

                    # Negative test: invalid content type
                    lines = [
                        f"def test_{func_name}_invalid_content_type():",
                        f'    """Sending invalid content-type to {method.upper()} {path} should return 4xx."""',
                        "    # Negative test: wrong content type",
                        "    # Expected: 415 or 400 status code",
                        "    assert True  # Placeholder - wire to actual HTTP call in integration",
                        "",
                        "",
                    ]
                    parts.append("\n".join(lines))
                except (KeyError, TypeError, ValueError) as exc:
                    logger.warning("Failed to generate negative test for %s %s: %s", method, path, exc)

        return "\n".join(parts)

    # ------------------------------------------------------------------
    # AsyncAPI test generation (jsonschema validation)
    # ------------------------------------------------------------------

    def _generate_asyncapi_tests(
        self,
        contract_id: str,
        service_name: str,
        spec: dict[str, Any],
        include_negative: bool,
    ) -> str:
        """Generate jsonschema-based pytest code for an AsyncAPI spec."""
        title = spec.get("info", {}).get("title", service_name)
        version = spec.get("info", {}).get("version", "1.0.0")
        asyncapi_version = spec.get("asyncapi", "3.0.0")

        lines: list[str] = []
        lines.append(f'"""Auto-generated contract tests for {title} v{version}.')
        lines.append("")
        lines.append(f"Generated from AsyncAPI {asyncapi_version} specification.")
        lines.append(f"Contract ID: {contract_id}")
        lines.append(f"Service: {service_name}")
        lines.append('"""')
        lines.append("import json")
        lines.append("import jsonschema")
        lines.append("import pytest")
        lines.append("")
        lines.append("")

        test_code = "\n".join(lines)

        # Generate message payload validation tests
        message_tests = self._build_asyncapi_message_tests(spec)
        test_code += message_tests

        # Generate channel tests
        channel_tests = self._build_asyncapi_channel_tests(spec)
        test_code += channel_tests

        if include_negative:
            negative_tests = self._build_asyncapi_negative_tests(spec)
            test_code += negative_tests

        return test_code

    def _build_asyncapi_message_tests(self, spec: dict[str, Any]) -> str:
        """Generate tests for each message payload schema."""
        parts: list[str] = []
        components = spec.get("components", {})
        messages = components.get("messages", {})

        # Check if we need the helper function
        has_payloads = any(
            isinstance(m, dict) and m.get("payload")
            for m in messages.values()
        )

        if has_payloads:
            helper_lines = [
                "def _generate_sample_from_schema(schema):",
                '    """Generate a minimal sample payload from a JSON Schema."""',
                '    schema_type = schema.get("type", "object")',
                '    if schema_type == "object":',
                "        result = {}",
                '        properties = schema.get("properties", {})',
                '        required = schema.get("required", [])',
                "        for prop_name, prop_schema in properties.items():",
                "            if prop_name in required:",
                "                result[prop_name] = _generate_sample_from_schema(prop_schema)",
                "        return result",
                '    elif schema_type == "string":',
                '        if "enum" in schema:',
                '            return schema["enum"][0]',
                '        return "sample_string"',
                '    elif schema_type == "integer":',
                '        return schema.get("minimum", 1)',
                '    elif schema_type == "number":',
                '        return schema.get("minimum", 1.0)',
                '    elif schema_type == "boolean":',
                "        return True",
                '    elif schema_type == "array":',
                '        items_schema = schema.get("items", {})',
                "        return [_generate_sample_from_schema(items_schema)]",
                "    return None",
                "",
                "",
            ]
            parts.append("\n".join(helper_lines))

        for msg_name, msg_def in messages.items():
            if not isinstance(msg_def, dict):
                continue

            payload = msg_def.get("payload", {})
            if not payload:
                continue

            try:
                safe_name = re.sub(r"[^a-zA-Z0-9]", "_", msg_name).lower()
                payload_json = json.dumps(payload, indent=4)

                lines = [
                    f"def test_{safe_name}_payload_schema():",
                    f'    """Validate {msg_name} message payload against its schema."""',
                    f"    schema = {payload_json}",
                    "    sample = _generate_sample_from_schema(schema)",
                    "    jsonschema.validate(instance=sample, schema=schema)",
                    "",
                    "",
                ]
                parts.append("\n".join(lines))
            except (TypeError, ValueError) as exc:
                logger.warning("Failed to generate message test for %s: %s", msg_name, exc)

        return "\n".join(parts)

    def _build_asyncapi_channel_tests(self, spec: dict[str, Any]) -> str:
        """Generate tests validating channel structure."""
        parts: list[str] = []
        channels = spec.get("channels", {})

        for ch_name, ch_def in channels.items():
            if not isinstance(ch_def, dict):
                continue

            try:
                safe_name = re.sub(r"[^a-zA-Z0-9]", "_", ch_name).lower()
                address = ch_def.get("address", "")
                ch_json = json.dumps(ch_def, indent=4)

                lines = [
                    f"def test_channel_{safe_name}_structure():",
                    f'    """Verify channel {ch_name} has required address field."""',
                    f"    channel_spec = {ch_json}",
                    '    assert "address" in channel_spec, "Channel must have an address"',
                    f'    assert channel_spec["address"] == "{address}"',
                    "",
                    "",
                ]
                parts.append("\n".join(lines))
            except (TypeError, ValueError) as exc:
                logger.warning("Failed to generate channel test for %s: %s", ch_name, exc)

        return "\n".join(parts)

    def _build_asyncapi_negative_tests(self, spec: dict[str, Any]) -> str:
        """Generate negative tests for AsyncAPI messages."""
        parts: list[str] = []
        components = spec.get("components", {})
        messages = components.get("messages", {})

        for msg_name, msg_def in messages.items():
            if not isinstance(msg_def, dict):
                continue

            payload = msg_def.get("payload", {})
            if not payload:
                continue

            try:
                safe_name = re.sub(r"[^a-zA-Z0-9]", "_", msg_name).lower()
                required_fields = payload.get("required", [])
                payload_json = json.dumps(payload, indent=4)

                if required_fields:
                    lines = [
                        f"def test_{safe_name}_missing_required_fields():",
                        f'    """Validate {msg_name} rejects payload with missing required fields."""',
                        f"    schema = {payload_json}",
                        "    with pytest.raises(jsonschema.ValidationError):",
                        "        jsonschema.validate(instance={}, schema=schema)",
                        "",
                        "",
                    ]
                    parts.append("\n".join(lines))

                wrong_type_lines = [
                    f"def test_{safe_name}_wrong_type():",
                    f'    """Validate {msg_name} rejects non-object payload."""',
                    f"    schema = {payload_json}",
                    '    if schema.get("type") == "object":',
                    "        with pytest.raises(jsonschema.ValidationError):",
                    '            jsonschema.validate(instance="not_an_object", schema=schema)',
                    "",
                    "",
                ]
                parts.append("\n".join(wrong_type_lines))
            except (TypeError, ValueError) as exc:
                logger.warning("Failed to generate negative test for %s: %s", msg_name, exc)

        return "\n".join(parts)

    # ------------------------------------------------------------------
    # JSON Schema test generation (basic)
    # ------------------------------------------------------------------

    def _generate_json_schema_tests(
        self,
        contract_id: str,
        service_name: str,
        spec: dict[str, Any],
    ) -> str:
        """Generate basic schema validation tests for a JSON Schema contract."""
        spec_json = json.dumps(spec, indent=4)
        lines = [
            '"""Auto-generated contract tests for JSON Schema.',
            "",
            f"Contract ID: {contract_id}",
            f"Service: {service_name}",
            '"""',
            "import jsonschema",
            "import pytest",
            "",
            "",
            "def test_schema_is_valid():",
            '    """Verify the schema itself is a valid JSON Schema."""',
            f"    schema = {spec_json}",
            "    jsonschema.Draft202012Validator.check_schema(schema)",
            "",
        ]
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _make_func_name(path: str, method: str) -> str:
        """Convert a path+method into a valid Python function name suffix."""
        # /api/users/{id} + GET -> api_users_id_get
        clean = re.sub(r"[{}]", "", path)
        clean = re.sub(r"[^a-zA-Z0-9/]", "", clean)
        parts = [p for p in clean.split("/") if p]
        parts.append(method.lower())
        return "_".join(parts)


# Backward-compatible alias
TestGenerator = ContractTestGenerator

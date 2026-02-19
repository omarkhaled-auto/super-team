"""Cross-service integration test generator.

Generates cross-service integration test flows from OpenAPI contracts by
reading specs from a contract registry directory, detecting service chains
through field-overlap analysis between response and request schemas, and
producing deterministic test flow definitions.

This module is part of Milestone 3 of the super-team pipeline and satisfies
TECH-015 (deterministic generation): given identical contracts, this module
always produces identical flows in the same order.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
_MAX_CHAIN_DEPTH = 5
_MAX_FLOWS = 20
_MIN_FIELD_OVERLAP = 2

# Timezone variants used for boundary tests (ISO 8601)
_TIMEZONE_VARIANTS = [
    "2024-01-15T10:30:00Z",
    "2024-01-15T10:30:00+00:00",
    "2024-01-15T10:30:00-05:00",
    "2024-01-15T10:30:00+05:30",
    "2024-01-15T10:30:00+09:00",
    "2024-01-15T10:30:00+12:00",
]

# Date/time field name patterns
_DATETIME_FIELD_PATTERN = re.compile(
    r"(date|time|timestamp|created|updated|modified|expires|deadline|scheduled)",
    re.IGNORECASE,
)

# String format types that indicate date/time
_DATETIME_FORMATS = {"date", "date-time", "datetime", "time"}


class CrossServiceTestGenerator:
    """Generates cross-service integration test flows from OpenAPI contracts.

    Reads OpenAPI specs from a contract registry directory, detects service
    chains by analyzing field overlap between response and request schemas,
    and generates deterministic test flow definitions.
    """

    def __init__(
        self,
        contract_registry_path: Path,
        domain_model_path: Path | None = None,
    ) -> None:
        self._contract_registry_path = Path(contract_registry_path)
        self._domain_model_path = domain_model_path

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def generate_flow_tests(self) -> list[dict]:
        """Generate flow test definitions from OpenAPI contracts.

        Chain Detection Algorithm:
            1. Extract response/request schemas from each OpenAPI spec
            2. Compute field overlap between services (>=2 matching
               fields = chain link)
            3. Build directed graph of service dependencies
            4. Find all simple paths (depth <= 5)
            5. Sort by path length descending
            6. Return top 20 flows

        Args:
            contract_registry_path: Directory containing OpenAPI spec
                JSON files, one per service.

        Returns:
            A list of flow dicts, each containing ``flow_id``,
            ``description``, and ``steps``.
        """
        registry = self._contract_registry_path
        specs = self._load_all_specs(registry)

        if not specs:
            logger.warning(
                "No OpenAPI specs found in %s; returning empty flows",
                registry,
            )
            return []

        # 1. Extract schemas per service
        service_schemas = self._extract_all_schemas(specs)

        # 2 & 3. Build directed adjacency graph based on field overlap
        graph = self._build_service_graph(service_schemas)

        # 4. Find all simple paths up to depth limit
        all_paths = self._find_all_simple_paths(graph, max_depth=_MAX_CHAIN_DEPTH)

        # 5. Sort by path length descending (stable sort for determinism)
        all_paths.sort(key=lambda p: len(p), reverse=True)

        # 6. Take top 20
        top_paths = all_paths[:_MAX_FLOWS]

        # Convert paths into flow definitions
        flows: list[dict] = []
        for idx, path in enumerate(top_paths):
            flow_id = f"flow_{idx + 1:03d}"
            description = " -> ".join(path)
            steps = self._build_flow_steps(path, specs, service_schemas)
            flows.append(
                {
                    "flow_id": flow_id,
                    "description": description,
                    "steps": steps,
                }
            )

        logger.info(
            "Generated %d flow test(s) from %d service(s)",
            len(flows),
            len(specs),
        )
        return flows

    async def generate_boundary_tests(self) -> list[dict]:
        """Generate boundary test definitions.

        Produces three categories of boundary tests:
            - ``case_sensitivity``: Test camelCase vs snake_case for
              string fields.
            - ``timezone_handling``: Test ISO 8601 timezone variants
              for date/time fields.
            - ``null_handling``: Test null, missing key, and empty
              string for nullable fields.

        Returns:
            A list of boundary test dicts, each containing ``test_id``,
            ``test_type``, ``service``, ``endpoint``, and ``test_data``.
        """
        registry = self._contract_registry_path
        specs = self._load_all_specs(registry)

        if not specs:
            logger.warning(
                "No OpenAPI specs found in %s; returning empty boundary tests",
                registry,
            )
            return []

        boundary_tests: list[dict] = []
        counter = 0

        # Process services in sorted order for determinism (TECH-015)
        for service_name in sorted(specs.keys()):
            spec = specs[service_name]
            paths = spec.get("paths", {})

            for endpoint_path in sorted(paths.keys()):
                methods = paths[endpoint_path]
                if not isinstance(methods, dict):
                    continue

                for method in sorted(methods.keys()):
                    method_upper = method.upper()
                    if method_upper not in (
                        "GET", "POST", "PUT", "PATCH", "DELETE",
                    ):
                        continue

                    operation = methods[method]
                    if not isinstance(operation, dict):
                        continue

                    # Extract request body schema fields
                    request_schema = self._extract_request_schema(
                        operation, spec,
                    )
                    if not request_schema:
                        continue

                    properties = request_schema.get("properties", {})
                    required_fields = set(request_schema.get("required", []))

                    for field_name in sorted(properties.keys()):
                        field_schema = properties[field_name]
                        if not isinstance(field_schema, dict):
                            continue

                        field_type = field_schema.get("type", "")
                        field_format = field_schema.get("format", "")
                        nullable = field_schema.get("nullable", False)

                        # --- case_sensitivity tests for string fields ---
                        if field_type == "string" and not self._is_datetime_field(
                            field_name, field_format,
                        ):
                            counter += 1
                            boundary_tests.append(
                                {
                                    "test_id": f"boundary_{counter:03d}",
                                    "test_type": "case_sensitivity",
                                    "service": service_name,
                                    "endpoint": endpoint_path,
                                    "test_data": {
                                        "method": method_upper,
                                        "field": field_name,
                                        "variants": [
                                            {
                                                "style": "camelCase",
                                                "key": self._to_camel_case(
                                                    field_name,
                                                ),
                                                "value": "test_value",
                                            },
                                            {
                                                "style": "snake_case",
                                                "key": self._to_snake_case(
                                                    field_name,
                                                ),
                                                "value": "test_value",
                                            },
                                        ],
                                    },
                                }
                            )

                        # --- timezone_handling tests for date/time fields ---
                        if self._is_datetime_field(field_name, field_format):
                            counter += 1
                            boundary_tests.append(
                                {
                                    "test_id": f"boundary_{counter:03d}",
                                    "test_type": "timezone_handling",
                                    "service": service_name,
                                    "endpoint": endpoint_path,
                                    "test_data": {
                                        "method": method_upper,
                                        "field": field_name,
                                        "variants": _TIMEZONE_VARIANTS,
                                    },
                                }
                            )

                        # --- null_handling tests for nullable fields ---
                        if nullable or field_name not in required_fields:
                            counter += 1
                            boundary_tests.append(
                                {
                                    "test_id": f"boundary_{counter:03d}",
                                    "test_type": "null_handling",
                                    "service": service_name,
                                    "endpoint": endpoint_path,
                                    "test_data": {
                                        "method": method_upper,
                                        "field": field_name,
                                        "variants": [
                                            {"case": "null_value", "value": None},
                                            {"case": "missing_key", "value": "__MISSING__"},
                                            {"case": "empty_string", "value": ""},
                                        ],
                                    },
                                }
                            )

        logger.info(
            "Generated %d boundary test(s) from %d service(s)",
            len(boundary_tests),
            len(specs),
        )
        return boundary_tests

    def generate_test_file(
        self,
        flows: list[dict],
        boundary_tests: list[dict],
    ) -> str:
        """Generate valid Python test source string.

        Produces a self-contained pytest + httpx test module with test
        functions for every flow and boundary test provided.

        Args:
            flows: Flow test definitions as returned by
                :meth:`generate_flow_tests`.
            boundary_tests: Boundary test definitions as returned by
                :meth:`generate_boundary_tests`.

        Returns:
            A string of valid Python code using pytest and httpx patterns.
        """
        lines: list[str] = []

        # --- Module header ---------------------------------------------------
        lines.append('"""Auto-generated cross-service integration tests.')
        lines.append("")
        lines.append("Run with:  pytest tests/cross_service_tests.py -v")
        lines.append('"""')
        lines.append("")
        lines.append("from __future__ import annotations")
        lines.append("")
        lines.append("import httpx")
        lines.append("import pytest")
        lines.append("")
        lines.append("")
        lines.append("# ---------------------------------------------------------------------------")
        lines.append("# Configuration")
        lines.append("# ---------------------------------------------------------------------------")
        lines.append("BASE_URLS: dict[str, str] = {}")
        lines.append("")
        lines.append("")
        lines.append("def get_base_url(service: str) -> str:")
        lines.append('    """Return the base URL for a service, falling back to localhost."""')
        lines.append('    return BASE_URLS.get(service, f"http://localhost:8080")')
        lines.append("")

        # --- Flow tests -------------------------------------------------------
        if flows:
            lines.append("")
            lines.append("# ---------------------------------------------------------------------------")
            lines.append("# Flow tests")
            lines.append("# ---------------------------------------------------------------------------")

            for flow in flows:
                flow_id = flow["flow_id"]
                description = flow.get("description", "")
                steps = flow.get("steps", [])
                func_name = f"test_{flow_id}"

                lines.append("")
                lines.append("")
                lines.append(f"@pytest.mark.asyncio")
                lines.append(f"async def {func_name}():")
                lines.append(f'    """{description}."""')
                lines.append(f"    async with httpx.AsyncClient() as client:")

                if not steps:
                    lines.append(f"        pass  # No steps generated")
                else:
                    lines.append(f"        context: dict = {{}}")
                    for step_idx, step in enumerate(steps):
                        service = step.get("service", "unknown")
                        method = step.get("method", "GET")
                        path = step.get("path", "/")
                        expected_status = step.get("expected_status", 200)
                        request_template = step.get("request_template", {})

                        lines.append(f"")
                        lines.append(f"        # Step {step_idx + 1}: {service} {method} {path}")
                        lines.append(
                            f"        url_{step_idx} = "
                            f'get_base_url("{service}") + "{path}"'
                        )
                        if request_template:
                            lines.append(
                                f"        payload_{step_idx} = {json.dumps(request_template, sort_keys=True)}"
                            )
                            lines.append(
                                f"        resp_{step_idx} = await client.request("
                            )
                            lines.append(
                                f'            "{method}",'
                            )
                            lines.append(
                                f"            url_{step_idx},"
                            )
                            lines.append(
                                f"            json=payload_{step_idx},"
                            )
                            lines.append(f"        )")
                        else:
                            lines.append(
                                f"        resp_{step_idx} = await client.request("
                            )
                            lines.append(
                                f'            "{method}",'
                            )
                            lines.append(
                                f"            url_{step_idx},"
                            )
                            lines.append(f"        )")

                        lines.append(
                            f"        assert resp_{step_idx}.status_code == {expected_status}, ("
                        )
                        lines.append(
                            f'            f"Expected {expected_status} from {service} {method} {path}, "'
                        )
                        lines.append(
                            f'            f"got {{resp_{step_idx}.status_code}}"'
                        )
                        lines.append(f"        )")
                        lines.append(
                            f"        context[\"{service}_{step_idx}\"] = resp_{step_idx}.json()"
                        )

        # --- Boundary tests ---------------------------------------------------
        if boundary_tests:
            lines.append("")
            lines.append("")
            lines.append("# ---------------------------------------------------------------------------")
            lines.append("# Boundary tests")
            lines.append("# ---------------------------------------------------------------------------")

            for bt in boundary_tests:
                test_id = bt["test_id"]
                test_type = bt["test_type"]
                service = bt.get("service", "unknown")
                endpoint = bt.get("endpoint", "/")
                test_data = bt.get("test_data", {})
                method = test_data.get("method", "POST")
                field = test_data.get("field", "field")
                func_name = f"test_{test_id}_{test_type}"

                lines.append("")
                lines.append("")
                if test_type == "case_sensitivity":
                    lines.append(f"@pytest.mark.asyncio")
                    lines.append(f"async def {func_name}():")
                    lines.append(
                        f'    """Case sensitivity test for {service} '
                        f'{endpoint} field \'{field}\'."""'
                    )
                    lines.append(f"    async with httpx.AsyncClient() as client:")
                    lines.append(
                        f'        url = get_base_url("{service}") + "{endpoint}"'
                    )
                    variants = test_data.get("variants", [])
                    lines.append(f"        responses = []")
                    for v_idx, variant in enumerate(variants):
                        key = variant.get("key", field)
                        value = variant.get("value", "test_value")
                        lines.append(
                            f"        resp_{v_idx} = await client.request("
                        )
                        lines.append(f'            "{method}",')
                        lines.append(f"            url,")
                        lines.append(
                            f"            json={{{json.dumps(key)}: {json.dumps(value)}}},"
                        )
                        lines.append(f"        )")
                        lines.append(f"        responses.append(resp_{v_idx})")
                    lines.append(
                        f"        # Verify server handles both naming conventions"
                    )
                    lines.append(
                        f"        status_codes = [r.status_code for r in responses]"
                    )
                    lines.append(
                        f"        assert all("
                    )
                    lines.append(
                        f"            s < 500 for s in status_codes"
                    )
                    lines.append(
                        f'        ), f"Server error on case variant: {{status_codes}}"'
                    )

                elif test_type == "timezone_handling":
                    lines.append(f"@pytest.mark.asyncio")
                    lines.append(f"async def {func_name}():")
                    lines.append(
                        f'    """Timezone handling test for {service} '
                        f'{endpoint} field \'{field}\'."""'
                    )
                    lines.append(f"    async with httpx.AsyncClient() as client:")
                    lines.append(
                        f'        url = get_base_url("{service}") + "{endpoint}"'
                    )
                    variants = test_data.get("variants", _TIMEZONE_VARIANTS)
                    lines.append(f"        timezone_variants = {json.dumps(variants)}")
                    lines.append(f"        for tz_value in timezone_variants:")
                    lines.append(
                        f"            resp = await client.request("
                    )
                    lines.append(f'                "{method}",')
                    lines.append(f"                url,")
                    lines.append(
                        f"                json={{{json.dumps(field)}: tz_value}},"
                    )
                    lines.append(f"            )")
                    lines.append(
                        f"            assert resp.status_code < 500, ("
                    )
                    lines.append(
                        f'                f"Server error on timezone variant {{tz_value}}: "'
                    )
                    lines.append(
                        f'                f"{{resp.status_code}}"'
                    )
                    lines.append(f"            )")

                elif test_type == "null_handling":
                    lines.append(f"@pytest.mark.asyncio")
                    lines.append(f"async def {func_name}():")
                    lines.append(
                        f'    """Null handling test for {service} '
                        f'{endpoint} field \'{field}\'."""'
                    )
                    lines.append(f"    async with httpx.AsyncClient() as client:")
                    lines.append(
                        f'        url = get_base_url("{service}") + "{endpoint}"'
                    )
                    lines.append(f"")
                    lines.append(f"        # Test null value")
                    lines.append(
                        f"        resp_null = await client.request("
                    )
                    lines.append(f'            "{method}",')
                    lines.append(f"            url,")
                    lines.append(
                        f"            json={{{json.dumps(field)}: None}},"
                    )
                    lines.append(f"        )")
                    lines.append(
                        f"        assert resp_null.status_code < 500, ("
                    )
                    lines.append(
                        f'            f"Server error on null value: {{resp_null.status_code}}"'
                    )
                    lines.append(f"        )")
                    lines.append(f"")
                    lines.append(f"        # Test missing key")
                    lines.append(
                        f"        resp_missing = await client.request("
                    )
                    lines.append(f'            "{method}",')
                    lines.append(f"            url,")
                    lines.append(f"            json={{}},")
                    lines.append(f"        )")
                    lines.append(
                        f"        assert resp_missing.status_code < 500, ("
                    )
                    lines.append(
                        f'            f"Server error on missing key: {{resp_missing.status_code}}"'
                    )
                    lines.append(f"        )")
                    lines.append(f"")
                    lines.append(f"        # Test empty string")
                    lines.append(
                        f"        resp_empty = await client.request("
                    )
                    lines.append(f'            "{method}",')
                    lines.append(f"            url,")
                    lines.append(
                        f"            json={{{json.dumps(field)}: \"\"}},"
                    )
                    lines.append(f"        )")
                    lines.append(
                        f"        assert resp_empty.status_code < 500, ("
                    )
                    lines.append(
                        f'            f"Server error on empty string: {{resp_empty.status_code}}"'
                    )
                    lines.append(f"        )")

        # Ensure trailing newline
        lines.append("")
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Private: spec loading
    # ------------------------------------------------------------------

    @staticmethod
    def _load_all_specs(registry: Path) -> dict[str, dict[str, Any]]:
        """Load all OpenAPI JSON specs from the registry directory.

        Files are processed in sorted order for determinism (TECH-015).

        Args:
            registry: Path to the directory containing OpenAPI spec JSON
                files.

        Returns:
            Mapping of service name to parsed OpenAPI spec dict.
        """
        specs: dict[str, dict[str, Any]] = {}

        if not registry.is_dir():
            logger.warning(
                "Contract registry path does not exist or is not a directory: %s",
                registry,
            )
            return specs

        json_files = sorted(registry.glob("*.json"))
        if not json_files:
            logger.info("No JSON files found in %s", registry)
            return specs

        for json_file in json_files:
            try:
                raw = json_file.read_text(encoding="utf-8")
                data = json.loads(raw)
            except (OSError, json.JSONDecodeError) as exc:
                logger.warning(
                    "Skipping unreadable spec file %s: %s", json_file, exc,
                )
                continue

            if not isinstance(data, dict):
                logger.warning(
                    "Skipping non-object spec file %s", json_file,
                )
                continue

            # Determine service name: prefer info.title, fall back to
            # filename stem.
            info = data.get("info", {})
            service_name = ""
            if isinstance(info, dict):
                service_name = info.get("title", "")
            if not service_name:
                service_name = json_file.stem

            # Normalise to lowercase kebab-case for consistent keying
            service_name = (
                service_name.lower()
                .replace(" ", "-")
                .replace("_", "-")
            )

            specs[service_name] = data
            logger.debug(
                "Loaded spec for service '%s' from %s",
                service_name,
                json_file.name,
            )

        logger.info(
            "Loaded %d OpenAPI spec(s) from %s", len(specs), registry,
        )
        return specs

    # ------------------------------------------------------------------
    # Private: schema extraction
    # ------------------------------------------------------------------

    def _extract_all_schemas(
        self, specs: dict[str, dict[str, Any]],
    ) -> dict[str, dict[str, set[str]]]:
        """Extract request and response field sets for every service.

        Args:
            specs: Mapping of service name to OpenAPI spec.

        Returns:
            Mapping of service name to ``{"request_fields": set,
            "response_fields": set, "endpoints": [...]}``.
        """
        result: dict[str, dict[str, Any]] = {}

        for service_name in sorted(specs.keys()):
            spec = specs[service_name]
            request_fields: set[str] = set()
            response_fields: set[str] = set()
            endpoints: list[dict[str, Any]] = []

            paths = spec.get("paths", {})
            for path_str in sorted(paths.keys()):
                methods = paths[path_str]
                if not isinstance(methods, dict):
                    continue

                for method in sorted(methods.keys()):
                    method_upper = method.upper()
                    if method_upper not in (
                        "GET", "POST", "PUT", "PATCH", "DELETE",
                    ):
                        continue

                    operation = methods[method]
                    if not isinstance(operation, dict):
                        continue

                    # --- Request schema ---
                    req_schema = self._extract_request_schema(
                        operation, spec,
                    )
                    req_props = sorted(
                        req_schema.get("properties", {}).keys(),
                    ) if req_schema else []
                    request_fields.update(req_props)

                    # --- Response schema ---
                    resp_schema = self._extract_response_schema(
                        operation, spec,
                    )
                    resp_props = sorted(
                        resp_schema.get("properties", {}).keys(),
                    ) if resp_schema else []
                    response_fields.update(resp_props)

                    endpoints.append(
                        {
                            "method": method_upper,
                            "path": path_str,
                            "request_fields": sorted(req_props),
                            "response_fields": sorted(resp_props),
                            "request_schema": req_schema or {},
                        }
                    )

            result[service_name] = {
                "request_fields": request_fields,
                "response_fields": response_fields,
                "endpoints": endpoints,
            }

        return result

    def _extract_request_schema(
        self, operation: dict[str, Any], spec: dict[str, Any],
    ) -> dict[str, Any] | None:
        """Extract the JSON request body schema from an operation.

        Resolves ``$ref`` pointers one level deep into the spec's
        ``components/schemas``.

        Args:
            operation: A single OpenAPI operation object.
            spec: The full OpenAPI spec (for $ref resolution).

        Returns:
            The resolved schema dict, or ``None`` if no request body
            schema is found.
        """
        request_body = operation.get("requestBody", {})
        if not isinstance(request_body, dict):
            return None

        content = request_body.get("content", {})
        if not isinstance(content, dict):
            return None

        # Prefer application/json
        media = content.get("application/json", {})
        if not isinstance(media, dict):
            return None

        schema = media.get("schema", {})
        return self._resolve_schema(schema, spec)

    def _extract_response_schema(
        self, operation: dict[str, Any], spec: dict[str, Any],
    ) -> dict[str, Any] | None:
        """Extract the primary success response schema from an operation.

        Looks for 200, 201, or the first 2xx response in sorted order.

        Args:
            operation: A single OpenAPI operation object.
            spec: The full OpenAPI spec (for $ref resolution).

        Returns:
            The resolved schema dict, or ``None`` if no success response
            schema is found.
        """
        responses = operation.get("responses", {})
        if not isinstance(responses, dict):
            return None

        # Try specific success codes first, then any 2xx
        for code in ["200", "201"]:
            resp_obj = responses.get(code)
            if resp_obj and isinstance(resp_obj, dict):
                schema = self._extract_schema_from_response(resp_obj)
                if schema:
                    return self._resolve_schema(schema, spec)

        # Fallback: first 2xx response in sorted order
        for code in sorted(responses.keys()):
            if code.startswith("2") and isinstance(responses[code], dict):
                schema = self._extract_schema_from_response(responses[code])
                if schema:
                    return self._resolve_schema(schema, spec)

        return None

    @staticmethod
    def _extract_schema_from_response(
        response_obj: dict[str, Any],
    ) -> dict[str, Any] | None:
        """Extract schema from a response object's content block.

        Args:
            response_obj: An OpenAPI response object.

        Returns:
            The raw schema dict (may contain $ref), or ``None``.
        """
        content = response_obj.get("content", {})
        if not isinstance(content, dict):
            return None

        media = content.get("application/json", {})
        if not isinstance(media, dict):
            return None

        schema = media.get("schema")
        if isinstance(schema, dict):
            return schema
        return None

    def _resolve_schema(
        self,
        schema: dict[str, Any] | None,
        spec: dict[str, Any],
    ) -> dict[str, Any] | None:
        """Resolve a schema, following ``$ref`` pointers.

        Handles ``$ref`` in the form ``#/components/schemas/ModelName``
        and also resolves ``allOf``, ``items``, and nested ``$ref``
        within properties.

        Args:
            schema: The schema object (may be ``None`` or contain a
                ``$ref``).
            spec: The full OpenAPI spec for reference resolution.

        Returns:
            The resolved schema dict, or ``None`` if resolution fails.
        """
        if schema is None:
            return None

        if not isinstance(schema, dict):
            return None

        # Handle $ref
        ref = schema.get("$ref")
        if ref and isinstance(ref, str):
            resolved = self._follow_ref(ref, spec)
            if resolved is not None:
                return resolved

        # Handle allOf -- merge all sub-schemas
        all_of = schema.get("allOf")
        if isinstance(all_of, list):
            merged: dict[str, Any] = {"type": "object", "properties": {}}
            required: list[str] = []
            for sub in all_of:
                resolved_sub = self._resolve_schema(sub, spec)
                if resolved_sub and isinstance(resolved_sub, dict):
                    merged["properties"].update(
                        resolved_sub.get("properties", {}),
                    )
                    required.extend(resolved_sub.get("required", []))
            if required:
                merged["required"] = sorted(set(required))
            return merged

        # Handle array items
        if schema.get("type") == "array":
            items = schema.get("items")
            if isinstance(items, dict):
                return self._resolve_schema(items, spec)

        return schema

    @staticmethod
    def _follow_ref(
        ref: str, spec: dict[str, Any],
    ) -> dict[str, Any] | None:
        """Follow a JSON $ref pointer within the spec.

        Only supports internal references of the form
        ``#/path/to/object``.

        Args:
            ref: The $ref string (e.g.
                ``#/components/schemas/User``).
            spec: The full OpenAPI spec.

        Returns:
            The referenced object, or ``None`` if not found.
        """
        if not ref.startswith("#/"):
            return None

        parts = ref[2:].split("/")
        current: Any = spec
        for part in parts:
            if isinstance(current, dict):
                current = current.get(part)
            else:
                return None
            if current is None:
                return None

        if isinstance(current, dict):
            return current
        return None

    # ------------------------------------------------------------------
    # Private: graph building and path finding
    # ------------------------------------------------------------------

    def _build_service_graph(
        self,
        service_schemas: dict[str, dict[str, Any]],
    ) -> dict[str, list[str]]:
        """Build a directed adjacency graph based on field overlap.

        An edge from service A to service B exists when the response
        fields of A overlap with the request fields of B by at least
        ``_MIN_FIELD_OVERLAP`` field names.

        Args:
            service_schemas: The per-service schema data from
                :meth:`_extract_all_schemas`.

        Returns:
            Adjacency list mapping each service name to a sorted list of
            service names it can feed data to.
        """
        graph: dict[str, list[str]] = {}
        sorted_services = sorted(service_schemas.keys())

        for svc_a in sorted_services:
            graph.setdefault(svc_a, [])
            response_fields_a = service_schemas[svc_a]["response_fields"]

            for svc_b in sorted_services:
                if svc_a == svc_b:
                    continue

                request_fields_b = service_schemas[svc_b]["request_fields"]
                overlap = response_fields_a & request_fields_b

                if len(overlap) >= _MIN_FIELD_OVERLAP:
                    graph[svc_a].append(svc_b)
                    logger.debug(
                        "Chain link: %s -> %s (overlap: %s)",
                        svc_a,
                        svc_b,
                        sorted(overlap),
                    )

            # Sort neighbours for determinism
            graph[svc_a] = sorted(graph[svc_a])

        return graph

    @staticmethod
    def _find_all_simple_paths(
        graph: dict[str, list[str]],
        max_depth: int = _MAX_CHAIN_DEPTH,
    ) -> list[list[str]]:
        """Find all simple (non-repeating) paths in the graph via DFS.

        A path of length 1 (single node with no outgoing edges in the
        path) is not included -- only paths with at least 2 nodes.

        Args:
            graph: Adjacency list.
            max_depth: Maximum number of nodes in a path.

        Returns:
            A sorted list of paths (each path is a list of service
            names). Sorted by length descending, then lexicographically
            for determinism.
        """
        all_paths: list[list[str]] = []

        def dfs(
            node: str,
            current_path: list[str],
            visited: set[str],
        ) -> None:
            """Depth-first search collecting all simple paths."""
            if len(current_path) >= 2:
                all_paths.append(list(current_path))

            if len(current_path) >= max_depth:
                return

            for neighbour in graph.get(node, []):
                if neighbour not in visited:
                    visited.add(neighbour)
                    current_path.append(neighbour)
                    dfs(neighbour, current_path, visited)
                    current_path.pop()
                    visited.discard(neighbour)

        # Start DFS from every node in sorted order
        for start_node in sorted(graph.keys()):
            visited: set[str] = {start_node}
            dfs(start_node, [start_node], visited)

        # Sort: length descending, then lexicographic on the path tuple
        all_paths.sort(key=lambda p: (-len(p), tuple(p)))

        return all_paths

    # ------------------------------------------------------------------
    # Private: flow step construction
    # ------------------------------------------------------------------

    def _build_flow_steps(
        self,
        path: list[str],
        specs: dict[str, dict[str, Any]],
        service_schemas: dict[str, dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Build step definitions for a single flow path.

        For each service in the path, selects the most relevant endpoint
        (preferring POST endpoints that accept request bodies, then any
        endpoint with request fields).

        Args:
            path: Ordered list of service names in the flow.
            specs: The loaded OpenAPI specs.
            service_schemas: The extracted schema data.

        Returns:
            A list of step dicts suitable for inclusion in a flow.
        """
        steps: list[dict[str, Any]] = []

        for svc_name in path:
            schema_data = service_schemas.get(svc_name, {})
            endpoints = schema_data.get("endpoints", [])

            # Pick the best endpoint for this flow step
            chosen = self._pick_best_endpoint(endpoints)

            if chosen:
                request_template = self._build_request_template(
                    chosen.get("request_schema", {}),
                )
                steps.append(
                    {
                        "service": svc_name,
                        "method": chosen["method"],
                        "path": chosen["path"],
                        "request_template": request_template,
                        "expected_status": (
                            201 if chosen["method"] == "POST" else 200
                        ),
                    }
                )
            elif endpoints:
                # Fallback to first endpoint
                ep = endpoints[0]
                steps.append(
                    {
                        "service": svc_name,
                        "method": ep["method"],
                        "path": ep["path"],
                        "request_template": {},
                        "expected_status": 200,
                    }
                )
            else:
                # Service has no endpoints -- include a placeholder step
                steps.append(
                    {
                        "service": svc_name,
                        "method": "GET",
                        "path": "/",
                        "request_template": {},
                        "expected_status": 200,
                    }
                )

        return steps

    @staticmethod
    def _pick_best_endpoint(
        endpoints: list[dict[str, Any]],
    ) -> dict[str, Any] | None:
        """Select the most suitable endpoint for a flow step.

        Preference order:
            1. POST endpoints with request fields
            2. PUT/PATCH endpoints with request fields
            3. Any endpoint with request fields
            4. Any POST endpoint
            5. ``None`` (caller uses fallback)

        Args:
            endpoints: List of endpoint dicts with ``method``,
                ``path``, and ``request_fields`` keys.

        Returns:
            The chosen endpoint dict, or ``None``.
        """
        post_with_body: list[dict[str, Any]] = []
        mutate_with_body: list[dict[str, Any]] = []
        any_with_body: list[dict[str, Any]] = []
        post_any: list[dict[str, Any]] = []

        for ep in endpoints:
            has_request = bool(ep.get("request_fields"))
            method = ep.get("method", "")

            if method == "POST" and has_request:
                post_with_body.append(ep)
            elif method in ("PUT", "PATCH") and has_request:
                mutate_with_body.append(ep)
            elif has_request:
                any_with_body.append(ep)
            elif method == "POST":
                post_any.append(ep)

        for candidate_list in [
            post_with_body,
            mutate_with_body,
            any_with_body,
            post_any,
        ]:
            if candidate_list:
                return candidate_list[0]

        return None

    @staticmethod
    def _build_request_template(
        schema: dict[str, Any],
    ) -> dict[str, Any]:
        """Build a deterministic request template from a schema.

        Generates sensible default values for each property type:
            - ``string``: ``"test"``
            - ``integer`` / ``number``: ``0``
            - ``boolean``: ``false``
            - ``array``: ``[]``
            - ``object``: ``{}``

        Date/time formatted strings receive an ISO 8601 value.

        Args:
            schema: An OpenAPI schema object with a ``properties``
                key.

        Returns:
            A dict with default values for every property, keys in
            sorted order.
        """
        properties = schema.get("properties", {})
        if not properties:
            return {}

        template: dict[str, Any] = {}
        for field_name in sorted(properties.keys()):
            field_schema = properties[field_name]
            if not isinstance(field_schema, dict):
                template[field_name] = "test"
                continue

            field_type = field_schema.get("type", "string")
            field_format = field_schema.get("format", "")

            if field_type == "string":
                if field_format in _DATETIME_FORMATS:
                    template[field_name] = "2024-01-15T10:30:00Z"
                elif field_format == "email":
                    template[field_name] = "test@example.com"
                elif field_format == "uri" or field_format == "url":
                    template[field_name] = "https://example.com"
                elif field_format == "uuid":
                    template[field_name] = "00000000-0000-0000-0000-000000000000"
                else:
                    template[field_name] = "test"
            elif field_type == "integer":
                template[field_name] = 0
            elif field_type == "number":
                template[field_name] = 0.0
            elif field_type == "boolean":
                template[field_name] = False
            elif field_type == "array":
                template[field_name] = []
            elif field_type == "object":
                template[field_name] = {}
            else:
                template[field_name] = "test"

        return template

    # ------------------------------------------------------------------
    # Private: boundary test helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _is_datetime_field(field_name: str, field_format: str) -> bool:
        """Determine whether a field represents a date/time value.

        Checks both the OpenAPI ``format`` keyword and the field name
        against common date/time patterns.

        Args:
            field_name: The property name.
            field_format: The OpenAPI ``format`` value (may be empty).

        Returns:
            ``True`` if the field is likely a date/time field.
        """
        if field_format in _DATETIME_FORMATS:
            return True
        return bool(_DATETIME_FIELD_PATTERN.search(field_name))

    @staticmethod
    def _to_camel_case(name: str) -> str:
        """Convert a string to camelCase.

        Args:
            name: The input string (may be snake_case, kebab-case, or
                already camelCase).

        Returns:
            The camelCase version of the string.
        """
        # Split on underscores and hyphens
        parts = re.split(r"[_\-]+", name)
        if not parts:
            return name
        return parts[0].lower() + "".join(
            p.capitalize() for p in parts[1:]
        )

    @staticmethod
    def _to_snake_case(name: str) -> str:
        """Convert a string to snake_case.

        Args:
            name: The input string (may be camelCase, PascalCase, or
                kebab-case).

        Returns:
            The snake_case version of the string.
        """
        # Insert underscores before uppercase letters
        s1 = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1_\2", name)
        s2 = re.sub(r"([a-z\d])([A-Z])", r"\1_\2", s1)
        return s2.replace("-", "_").lower()

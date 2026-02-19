"""Compliance checker for API contracts.

Validates runtime response data against contracted OpenAPI/AsyncAPI schemas.
Checks required fields, types, and nested objects up to 3 levels deep.

Extra fields are reported with ``info`` or ``warning`` severity but do not
cause a compliance failure (only ``error``-severity violations do).
"""

from __future__ import annotations

import json
import logging
from typing import Any

from src.shared.db.connection import ConnectionPool
from src.shared.errors import ContractNotFoundError
from src.shared.models.contracts import (
    ComplianceResult,
    ComplianceViolation,
    ContractType,
)

logger = logging.getLogger(__name__)

# JSON Schema type → Python type mapping
_JSON_TYPE_MAP: dict[str, tuple[type, ...]] = {
    "string": (str,),
    "integer": (int,),
    "number": (int, float),
    "boolean": (bool,),
    "array": (list,),
    "object": (dict,),
    "null": (type(None),),
}


class ComplianceChecker:
    """Validates response data against contract specifications."""

    def __init__(self, pool: ConnectionPool) -> None:
        self._pool = pool

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def check_compliance(
        self,
        contract_id: str,
        response_data: dict[str, Any],
    ) -> list[ComplianceResult]:
        """Check *response_data* against the contract's endpoint schemas.

        Parameters
        ----------
        contract_id:
            UUID of the contract to check against.
        response_data:
            Mapping of ``"METHOD /path"`` → response body (dict).
            Example: ``{"GET /api/users": {"users": [...]}}``

        Returns
        -------
        list[ComplianceResult]
            One result per endpoint checked.

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

        spec: dict[str, Any] = json.loads(row["spec_json"])
        contract_type: str = row["type"]

        # 2. Dispatch based on contract type
        if contract_type == ContractType.OPENAPI.value:
            return self._check_openapi_compliance(spec, response_data)
        elif contract_type == ContractType.ASYNCAPI.value:
            return self._check_asyncapi_compliance(spec, response_data)
        else:
            # json_schema — no compliance checking defined
            return []

    # ------------------------------------------------------------------
    # OpenAPI compliance
    # ------------------------------------------------------------------

    def _check_openapi_compliance(
        self,
        spec: dict[str, Any],
        response_data: dict[str, Any],
    ) -> list[ComplianceResult]:
        """Check response data against OpenAPI endpoint schemas."""
        results: list[ComplianceResult] = []
        paths = spec.get("paths", {})

        # Resolve component schemas for $ref lookups
        component_schemas = spec.get("components", {}).get("schemas", {})

        for endpoint_key, body in response_data.items():
            try:
                self._check_single_endpoint(
                    endpoint_key, body, paths, component_schemas, results
                )
            except (KeyError, TypeError, ValueError) as exc:
                results.append(ComplianceResult(
                    endpoint_path=endpoint_key,
                    method="UNKNOWN",
                    compliant=False,
                    violations=[ComplianceViolation(
                        field="internal",
                        expected="successful validation",
                        actual=str(exc),
                        severity="error",
                    )],
                ))

        return results

    def _check_single_endpoint(
        self,
        endpoint_key: str,
        body: Any,
        paths: dict[str, Any],
        component_schemas: dict[str, Any],
        results: list[ComplianceResult],
    ) -> None:
        """Validate a single endpoint response against its spec schema."""
        # Parse endpoint key: "GET /api/users" -> method="GET", path="/api/users"
        parts = endpoint_key.split(" ", 1)
        if len(parts) != 2:
            results.append(ComplianceResult(
                endpoint_path=endpoint_key,
                method="UNKNOWN",
                compliant=False,
                violations=[ComplianceViolation(
                    field="endpoint_key",
                    expected="METHOD /path",
                    actual=endpoint_key,
                    severity="error",
                )],
            ))
            return

        method, path = parts[0].upper(), parts[1]

        # Find matching path spec
        path_spec = paths.get(path)
        if path_spec is None:
            results.append(ComplianceResult(
                endpoint_path=path,
                method=method,
                compliant=False,
                violations=[ComplianceViolation(
                    field="path",
                    expected=f"Path defined in spec: {list(paths.keys())}",
                    actual=path,
                    severity="error",
                )],
            ))
            return

        method_spec = path_spec.get(method.lower())
        if method_spec is None:
            results.append(ComplianceResult(
                endpoint_path=path,
                method=method,
                compliant=False,
                violations=[ComplianceViolation(
                    field="method",
                    expected=f"Method defined for path: {list(path_spec.keys())}",
                    actual=method.lower(),
                    severity="error",
                )],
            ))
            return

        # Find response schema (check 200 first, then 2xx codes)
        response_schema = self._find_response_schema(
            method_spec, component_schemas
        )

        if response_schema is None:
            # No schema defined -- consider compliant
            results.append(ComplianceResult(
                endpoint_path=path,
                method=method,
                compliant=True,
                violations=[],
            ))
            return

        # Validate response body against schema
        violations = self._validate_against_schema(
            body, response_schema, component_schemas, prefix="", depth=0
        )

        compliant = not any(v.severity == "error" for v in violations)

        results.append(ComplianceResult(
            endpoint_path=path,
            method=method,
            compliant=compliant,
            violations=violations,
        ))

    def _find_response_schema(
        self,
        method_spec: dict[str, Any],
        component_schemas: dict[str, Any],
    ) -> dict[str, Any] | None:
        """Extract the response schema from a method spec."""
        responses = method_spec.get("responses", {})

        # Try status codes in order of preference
        for status_code in ["200", "201", "202", "2xx", "default"]:
            response_def = responses.get(status_code)
            if response_def is None:
                continue

            content = response_def.get("content", {})
            for content_type in ["application/json", "*/*"]:
                media = content.get(content_type)
                if media and "schema" in media:
                    schema = media["schema"]
                    return self._resolve_ref(schema, component_schemas)

        return None

    # ------------------------------------------------------------------
    # AsyncAPI compliance
    # ------------------------------------------------------------------

    def _check_asyncapi_compliance(
        self,
        spec: dict[str, Any],
        response_data: dict[str, Any],
    ) -> list[ComplianceResult]:
        """Check message data against AsyncAPI schemas."""
        results: list[ComplianceResult] = []
        component_schemas = spec.get("components", {}).get("schemas", {})
        messages = spec.get("components", {}).get("messages", {})

        for message_key, body in response_data.items():
            try:
                # message_key = "send channel_name" or just "MessageName"
                parts = message_key.split(" ", 1)
                if len(parts) == 2:
                    action, channel = parts
                else:
                    action, channel = "receive", message_key

                # Find message schema
                msg_schema = None
                if message_key in messages:
                    msg_def = messages[message_key]
                    if isinstance(msg_def, dict):
                        msg_schema = msg_def.get("payload", {})
                elif channel in messages:
                    msg_def = messages[channel]
                    if isinstance(msg_def, dict):
                        msg_schema = msg_def.get("payload", {})

                if msg_schema is None:
                    results.append(ComplianceResult(
                        endpoint_path=channel,
                        method=action.upper(),
                        compliant=True,
                        violations=[],
                    ))
                    continue

                resolved_schema = self._resolve_ref(msg_schema, component_schemas)
                violations = self._validate_against_schema(
                    body, resolved_schema, component_schemas, prefix="", depth=0
                )
                compliant = not any(v.severity == "error" for v in violations)

                results.append(ComplianceResult(
                    endpoint_path=channel,
                    method=action.upper(),
                    compliant=compliant,
                    violations=violations,
                ))
            except (KeyError, TypeError, ValueError) as exc:
                results.append(ComplianceResult(
                    endpoint_path=message_key,
                    method="UNKNOWN",
                    compliant=False,
                    violations=[ComplianceViolation(
                        field="internal",
                        expected="successful validation",
                        actual=str(exc),
                        severity="error",
                    )],
                ))

        return results

    # ------------------------------------------------------------------
    # Schema validation (recursive, max 3 levels)
    # ------------------------------------------------------------------

    def _validate_against_schema(
        self,
        data: Any,
        schema: dict[str, Any],
        component_schemas: dict[str, Any],
        prefix: str = "",
        depth: int = 0,
    ) -> list[ComplianceViolation]:
        """Validate *data* against *schema*, checking up to 3 levels deep.

        Returns a list of violations. ``error``-severity violations indicate
        non-compliance; ``info``/``warning`` are informational (extra fields).
        """
        violations: list[ComplianceViolation] = []
        max_depth = 3

        if depth > max_depth:
            return violations

        if not isinstance(schema, dict):
            return violations

        schema_type = schema.get("type")

        # Type checking
        if schema_type and data is not None:
            expected_types = _JSON_TYPE_MAP.get(schema_type)
            if expected_types and not isinstance(data, expected_types):
                actual_type = type(data).__name__
                field_path = prefix or "(root)"
                violations.append(ComplianceViolation(
                    field=field_path,
                    expected=schema_type,
                    actual=actual_type,
                    severity="error",
                ))
                return violations  # Can't check deeper if type is wrong

        # Object-level validation
        if schema_type == "object" and isinstance(data, dict):
            properties = schema.get("properties", {})
            required_fields = schema.get("required", [])

            # Check required fields
            for field_name in required_fields:
                field_path = f"{prefix}.{field_name}" if prefix else field_name
                if field_name not in data:
                    violations.append(ComplianceViolation(
                        field=field_path,
                        expected="present (required)",
                        actual="missing",
                        severity="error",
                    ))

            # Check field types and recurse into nested objects
            for field_name, field_schema in properties.items():
                field_path = f"{prefix}.{field_name}" if prefix else field_name
                if field_name not in data:
                    continue  # Already flagged if required

                field_value = data[field_name]
                resolved_field_schema = self._resolve_ref(
                    field_schema, component_schemas
                )

                # Recurse for nested validation
                sub_violations = self._validate_against_schema(
                    field_value,
                    resolved_field_schema,
                    component_schemas,
                    prefix=field_path,
                    depth=depth + 1,
                )
                violations.extend(sub_violations)

            # Check for extra fields (info/warning — not error)
            defined_fields = set(properties.keys())
            actual_fields = set(data.keys())
            extra_fields = actual_fields - defined_fields

            for extra_field in sorted(extra_fields):
                field_path = f"{prefix}.{extra_field}" if prefix else extra_field
                violations.append(ComplianceViolation(
                    field=field_path,
                    expected="not defined in schema",
                    actual="present",
                    severity="info",
                ))

        # Array-level validation
        elif schema_type == "array" and isinstance(data, list):
            items_schema = schema.get("items", {})
            if items_schema and data:
                # Validate first item as representative
                resolved_items = self._resolve_ref(items_schema, component_schemas)
                sub_violations = self._validate_against_schema(
                    data[0],
                    resolved_items,
                    component_schemas,
                    prefix=f"{prefix}[0]" if prefix else "[0]",
                    depth=depth + 1,
                )
                violations.extend(sub_violations)

        return violations

    # ------------------------------------------------------------------
    # $ref resolution
    # ------------------------------------------------------------------

    @staticmethod
    def _resolve_ref(
        schema: dict[str, Any],
        component_schemas: dict[str, Any],
    ) -> dict[str, Any]:
        """Resolve a ``$ref`` to the actual schema definition."""
        if not isinstance(schema, dict):
            return schema

        ref = schema.get("$ref")
        if ref is None:
            return schema

        # Handle #/components/schemas/Name
        if ref.startswith("#/components/schemas/"):
            schema_name = ref.split("/")[-1]
            resolved = component_schemas.get(schema_name)
            if resolved is not None:
                return resolved

        return schema

"""AsyncAPI specification validator using jsonschema Draft 2020-12."""
from __future__ import annotations

from typing import Any

import jsonschema

from src.shared.models.contracts import ValidationResult


def validate_asyncapi(spec: dict[str, Any]) -> ValidationResult:
    """Validate an AsyncAPI specification.

    Checks:
    1. spec is a dict with 'asyncapi' key
    2. asyncapi version starts with "3."
    3. info.title and info.version present
    4. channels have valid structure (address required)
    5. operations have valid structure (action must be send/receive, channel reference)
    6. schemas in components are valid JSON schemas (using jsonschema Draft 2020-12)

    Returns ValidationResult with valid, errors, warnings lists.
    """
    errors: list[str] = []
    warnings: list[str] = []

    try:
        # ------------------------------------------------------------------
        # 1. Top-level 'asyncapi' key must exist
        # ------------------------------------------------------------------
        if not isinstance(spec, dict):
            errors.append("Spec must be a dict")
            return ValidationResult(valid=False, errors=errors, warnings=warnings)

        asyncapi_version = spec.get("asyncapi")
        if asyncapi_version is None:
            errors.append("Missing required key: 'asyncapi'")
            return ValidationResult(valid=False, errors=errors, warnings=warnings)

        # ------------------------------------------------------------------
        # 2. Version must start with "3."
        # ------------------------------------------------------------------
        if not isinstance(asyncapi_version, str) or not asyncapi_version.startswith("3."):
            errors.append(
                f"Unsupported AsyncAPI version: {asyncapi_version!r} (expected 3.x)"
            )

        # ------------------------------------------------------------------
        # 3. info.title and info.version
        # ------------------------------------------------------------------
        info = spec.get("info")
        if not isinstance(info, dict):
            errors.append("Missing or invalid 'info' object")
        else:
            if not info.get("title"):
                errors.append("Missing required field: info.title")
            if not info.get("version"):
                errors.append("Missing required field: info.version")

        # ------------------------------------------------------------------
        # 4. Channels – each must have an address
        # ------------------------------------------------------------------
        channels = spec.get("channels")
        if channels is not None:
            if not isinstance(channels, dict):
                errors.append("'channels' must be an object")
            else:
                for channel_name, channel_def in channels.items():
                    if not isinstance(channel_def, dict):
                        errors.append(
                            f"Channel '{channel_name}' must be an object"
                        )
                        continue
                    if "address" not in channel_def:
                        errors.append(
                            f"Channel '{channel_name}' missing required field: address"
                        )

        # ------------------------------------------------------------------
        # 5. Operations – action (send/receive) and channel reference
        # ------------------------------------------------------------------
        operations = spec.get("operations")
        if operations is not None:
            if not isinstance(operations, dict):
                errors.append("'operations' must be an object")
            else:
                valid_actions = {"send", "receive"}
                for op_name, op_def in operations.items():
                    if not isinstance(op_def, dict):
                        errors.append(
                            f"Operation '{op_name}' must be an object"
                        )
                        continue

                    action = op_def.get("action")
                    if action not in valid_actions:
                        errors.append(
                            f"Operation '{op_name}' has invalid action: {action!r} "
                            f"(must be 'send' or 'receive')"
                        )

                    channel_ref = op_def.get("channel")
                    if channel_ref is None:
                        errors.append(
                            f"Operation '{op_name}' missing required field: channel"
                        )
                    elif isinstance(channel_ref, dict):
                        ref = channel_ref.get("$ref")
                        if ref and channels and isinstance(channels, dict):
                            # $ref format: #/channels/<name>
                            parts = ref.split("/")
                            if len(parts) >= 3 and parts[1] == "channels":
                                ref_name = parts[2]
                                if ref_name not in channels:
                                    warnings.append(
                                        f"Operation '{op_name}' references "
                                        f"undefined channel: {ref_name}"
                                    )

        # ------------------------------------------------------------------
        # 6. Component schemas – validate with jsonschema Draft 2020-12
        # ------------------------------------------------------------------
        components = spec.get("components")
        if isinstance(components, dict):
            schemas = components.get("schemas")
            if isinstance(schemas, dict):
                for schema_name, schema_def in schemas.items():
                    if not isinstance(schema_def, dict):
                        warnings.append(
                            f"Component schema '{schema_name}' is not an object"
                        )
                        continue
                    try:
                        jsonschema.Draft202012Validator.check_schema(schema_def)
                    except jsonschema.exceptions.SchemaError as exc:
                        errors.append(
                            f"Invalid JSON Schema in components.schemas.{schema_name}: "
                            f"{exc.message}"
                        )

    except (KeyError, ValueError, TypeError) as exc:
        errors.append(f"Unexpected validation error: {exc}")

    return ValidationResult(
        valid=len(errors) == 0,
        errors=errors,
        warnings=warnings,
    )

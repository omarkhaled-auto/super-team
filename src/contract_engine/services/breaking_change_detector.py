"""Breaking change detection for API specifications."""
from __future__ import annotations

import logging
from typing import Any

from src.shared.models.contracts import BreakingChange

logger = logging.getLogger(__name__)


def detect_breaking_changes(
    old_spec: dict[str, Any],
    new_spec: dict[str, Any],
) -> list[BreakingChange]:
    """Deep-diff two OpenAPI specs and detect breaking changes.

    Severity classification:
    - **error**: Removing endpoints, removing required fields, changing field
      types, narrowing enums.
    - **warning**: Adding required fields to request bodies, changing response
      structure.
    - **info**: Adding new endpoints, adding optional fields, documentation
      changes.

    Returns a list of :class:`BreakingChange` objects.
    """
    changes: list[BreakingChange] = []

    # ------------------------------------------------------------------
    # 1. Compare top-level paths
    # ------------------------------------------------------------------
    old_paths: dict[str, Any] = old_spec.get("paths") or {}
    new_paths: dict[str, Any] = new_spec.get("paths") or {}

    _compare_paths(old_paths, new_paths, changes)

    # ------------------------------------------------------------------
    # 2. Compare components/schemas
    # ------------------------------------------------------------------
    old_schemas = (old_spec.get("components") or {}).get("schemas") or {}
    new_schemas = (new_spec.get("components") or {}).get("schemas") or {}

    _compare_component_schemas(old_schemas, new_schemas, changes)

    # ------------------------------------------------------------------
    # 3. Info / documentation changes
    # ------------------------------------------------------------------
    _compare_info(old_spec, new_spec, changes)

    return changes


# ======================================================================
# Path-level comparison
# ======================================================================

def _compare_paths(
    old_paths: dict[str, Any],
    new_paths: dict[str, Any],
    changes: list[BreakingChange],
) -> None:
    """Compare OpenAPI paths for removed, added, and modified endpoints."""
    old_keys = set(old_paths)
    new_keys = set(new_paths)

    # Removed paths -> error
    for path in sorted(old_keys - new_keys):
        changes.append(
            BreakingChange(
                change_type="path_removed",
                path=path,
                old_value=path,
                new_value=None,
                severity="error",
            )
        )

    # Added paths -> info
    for path in sorted(new_keys - old_keys):
        changes.append(
            BreakingChange(
                change_type="path_added",
                path=path,
                old_value=None,
                new_value=path,
                severity="info",
            )
        )

    # Shared paths -> compare methods
    for path in sorted(old_keys & new_keys):
        try:
            old_path_item = old_paths[path] or {}
            new_path_item = new_paths[path] or {}
            _compare_methods(path, old_path_item, new_path_item, changes)
        except (KeyError, TypeError, AttributeError) as exc:
            logger.warning("Error comparing path %s: %s", path, exc)


# ======================================================================
# Method-level comparison
# ======================================================================

_HTTP_METHODS = {"get", "post", "put", "patch", "delete", "head", "options", "trace"}


def _compare_methods(
    path: str,
    old_item: dict[str, Any],
    new_item: dict[str, Any],
    changes: list[BreakingChange],
) -> None:
    """Compare HTTP methods within a single path."""
    old_methods = {m for m in old_item if m.lower() in _HTTP_METHODS}
    new_methods = {m for m in new_item if m.lower() in _HTTP_METHODS}

    # Removed methods -> error
    for method in sorted(old_methods - new_methods):
        changes.append(
            BreakingChange(
                change_type="method_removed",
                path=f"{path}.{method.upper()}",
                old_value=method.upper(),
                new_value=None,
                severity="error",
            )
        )

    # Added methods -> info
    for method in sorted(new_methods - old_methods):
        changes.append(
            BreakingChange(
                change_type="method_added",
                path=f"{path}.{method.upper()}",
                old_value=None,
                new_value=method.upper(),
                severity="info",
            )
        )

    # Shared methods -> compare operation details
    for method in sorted(old_methods & new_methods):
        try:
            base_path = f"{path}.{method.upper()}"
            old_op = old_item.get(method) or {}
            new_op = new_item.get(method) or {}

            _compare_parameters(base_path, old_op, new_op, changes)
            _compare_request_body(base_path, old_op, new_op, changes)
            _compare_responses(base_path, old_op, new_op, changes)
        except (KeyError, TypeError, AttributeError) as exc:
            logger.warning("Error comparing method %s on %s: %s", method, path, exc)


# ======================================================================
# Parameter comparison
# ======================================================================

def _compare_parameters(
    base_path: str,
    old_op: dict[str, Any],
    new_op: dict[str, Any],
    changes: list[BreakingChange],
) -> None:
    """Compare parameters between two operation objects."""
    old_params = {_param_key(p): p for p in (old_op.get("parameters") or [])}
    new_params = {_param_key(p): p for p in (new_op.get("parameters") or [])}

    old_keys = set(old_params)
    new_keys = set(new_params)

    # Removed required parameters -> error
    for key in sorted(old_keys - new_keys):
        param = old_params[key]
        if param.get("required", False):
            changes.append(
                BreakingChange(
                    change_type="required_parameter_removed",
                    path=f"{base_path}.parameters.{key}",
                    old_value=key,
                    new_value=None,
                    severity="error",
                )
            )

    # Added required parameters -> warning
    for key in sorted(new_keys - old_keys):
        param = new_params[key]
        severity = "warning" if param.get("required", False) else "info"
        changes.append(
            BreakingChange(
                change_type="parameter_added",
                path=f"{base_path}.parameters.{key}",
                old_value=None,
                new_value=key,
                severity=severity,
            )
        )

    # Shared parameters -- check type changes
    for key in sorted(old_keys & new_keys):
        try:
            old_p = old_params[key]
            new_p = new_params[key]
            old_type = _schema_type(old_p.get("schema"))
            new_type = _schema_type(new_p.get("schema"))
        except (KeyError, TypeError, AttributeError) as exc:
            logger.warning("Error comparing parameter %s: %s", key, exc)
            continue
        if old_type and new_type and old_type != new_type:
            changes.append(
                BreakingChange(
                    change_type="parameter_type_changed",
                    path=f"{base_path}.parameters.{key}",
                    old_value=old_type,
                    new_value=new_type,
                    severity="error",
                )
            )


def _param_key(param: dict[str, Any]) -> str:
    """Build a unique key for a parameter (name + in)."""
    return f"{param.get('name', '?')}:{param.get('in', '?')}"


# ======================================================================
# Request body comparison
# ======================================================================

def _compare_request_body(
    base_path: str,
    old_op: dict[str, Any],
    new_op: dict[str, Any],
    changes: list[BreakingChange],
) -> None:
    """Compare request body schemas between two operations."""
    old_body = old_op.get("requestBody")
    new_body = new_op.get("requestBody")

    if old_body is None and new_body is None:
        return

    if old_body is not None and new_body is None:
        changes.append(
            BreakingChange(
                change_type="request_body_removed",
                path=f"{base_path}.requestBody",
                old_value="present",
                new_value=None,
                severity="error",
            )
        )
        return

    if old_body is None and new_body is not None:
        severity = "warning" if new_body.get("required", False) else "info"
        changes.append(
            BreakingChange(
                change_type="request_body_added",
                path=f"{base_path}.requestBody",
                old_value=None,
                new_value="present",
                severity=severity,
            )
        )
        return

    # Both exist – compare the JSON schema content
    old_schema = _extract_body_schema(old_body)
    new_schema = _extract_body_schema(new_body)

    if old_schema and new_schema:
        _compare_schemas(
            f"{base_path}.requestBody.schema",
            old_schema,
            new_schema,
            changes,
            context="request",
        )


def _extract_body_schema(body: dict[str, Any]) -> dict[str, Any] | None:
    """Extract the JSON schema from a request body content object."""
    content = body.get("content") or {}
    for media_type in ("application/json", "application/xml", "text/plain"):
        media = content.get(media_type)
        if isinstance(media, dict) and "schema" in media:
            return media["schema"]
    # Fallback: pick the first media type with a schema
    for media in content.values():
        if isinstance(media, dict) and "schema" in media:
            return media["schema"]
    return None


# ======================================================================
# Response comparison
# ======================================================================

def _compare_responses(
    base_path: str,
    old_op: dict[str, Any],
    new_op: dict[str, Any],
    changes: list[BreakingChange],
) -> None:
    """Compare response schemas between two operations."""
    old_responses: dict[str, Any] = old_op.get("responses") or {}
    new_responses: dict[str, Any] = new_op.get("responses") or {}

    old_codes = set(old_responses)
    new_codes = set(new_responses)

    for code in sorted(old_codes - new_codes):
        changes.append(
            BreakingChange(
                change_type="response_removed",
                path=f"{base_path}.responses.{code}",
                old_value=code,
                new_value=None,
                severity="warning",
            )
        )

    for code in sorted(old_codes & new_codes):
        try:
            old_resp = old_responses[code] or {}
            new_resp = new_responses[code] or {}
            old_schema = _extract_body_schema(old_resp)
            new_schema = _extract_body_schema(new_resp)
        except (KeyError, TypeError, AttributeError) as exc:
            logger.warning("Error comparing response %s: %s", code, exc)
            continue
        if old_schema and new_schema:
            _compare_schemas(
                f"{base_path}.responses.{code}.schema",
                old_schema,
                new_schema,
                changes,
                context="response",
            )


# ======================================================================
# Recursive schema comparison
# ======================================================================

def _compare_schemas(
    path: str,
    old_schema: dict[str, Any],
    new_schema: dict[str, Any],
    changes: list[BreakingChange],
    *,
    context: str = "request",
) -> None:
    """Recursively compare two JSON schemas and detect breaking changes.

    *context* is either ``"request"`` or ``"response"`` and affects severity:
    - In request context: added required fields = warning, removed = error
    - In response context: removed fields = warning, type changes = warning
    """
    # Type change
    old_type = _schema_type(old_schema)
    new_type = _schema_type(new_schema)
    if old_type and new_type and old_type != new_type:
        severity = "error" if context == "request" else "warning"
        changes.append(
            BreakingChange(
                change_type="type_changed",
                path=path,
                old_value=old_type,
                new_value=new_type,
                severity=severity,
            )
        )
        return  # No point comparing properties if types differ

    # Enum narrowing
    old_enum = old_schema.get("enum")
    new_enum = new_schema.get("enum")
    if old_enum is not None and new_enum is not None:
        old_set = set(str(v) for v in old_enum)
        new_set = set(str(v) for v in new_enum)
        removed_values = old_set - new_set
        if removed_values:
            changes.append(
                BreakingChange(
                    change_type="enum_values_removed",
                    path=path,
                    old_value=", ".join(sorted(removed_values)),
                    new_value=", ".join(sorted(new_set)),
                    severity="error",
                )
            )

    # Property comparison (for object types)
    old_props: dict[str, Any] = old_schema.get("properties") or {}
    new_props: dict[str, Any] = new_schema.get("properties") or {}

    old_required: set[str] = set(old_schema.get("required") or [])
    new_required: set[str] = set(new_schema.get("required") or [])

    old_prop_keys = set(old_props)
    new_prop_keys = set(new_props)

    # Removed properties
    for prop in sorted(old_prop_keys - new_prop_keys):
        severity = "error" if context == "request" else "warning"
        changes.append(
            BreakingChange(
                change_type="property_removed",
                path=f"{path}.properties.{prop}",
                old_value=prop,
                new_value=None,
                severity=severity,
            )
        )

    # Added properties
    for prop in sorted(new_prop_keys - old_prop_keys):
        if prop in new_required:
            severity = "warning" if context == "request" else "info"
            change_type = "required_property_added"
        else:
            severity = "info"
            change_type = "optional_property_added"
        changes.append(
            BreakingChange(
                change_type=change_type,
                path=f"{path}.properties.{prop}",
                old_value=None,
                new_value=prop,
                severity=severity,
            )
        )

    # Shared properties -- recurse
    for prop in sorted(old_prop_keys & new_prop_keys):
        try:
            _compare_schemas(
                f"{path}.properties.{prop}",
                old_props[prop],
                new_props[prop],
                changes,
                context=context,
            )
        except (KeyError, TypeError, AttributeError) as exc:
            logger.warning("Error comparing property %s in %s: %s", prop, path, exc)

    # Newly required fields (existing optional field becomes required)
    newly_required = (new_required - old_required) & old_prop_keys
    for prop in sorted(newly_required):
        if prop in new_prop_keys and prop in old_prop_keys:
            severity = "warning" if context == "request" else "warning"
            changes.append(
                BreakingChange(
                    change_type="field_became_required",
                    path=f"{path}.required.{prop}",
                    old_value="optional",
                    new_value="required",
                    severity=severity,
                )
            )

    # Items comparison (for array types)
    old_items = old_schema.get("items")
    new_items = new_schema.get("items")
    if isinstance(old_items, dict) and isinstance(new_items, dict):
        _compare_schemas(
            f"{path}.items",
            old_items,
            new_items,
            changes,
            context=context,
        )


# ======================================================================
# Component schemas comparison
# ======================================================================

def _compare_component_schemas(
    old_schemas: dict[str, Any],
    new_schemas: dict[str, Any],
    changes: list[BreakingChange],
) -> None:
    """Compare component-level schemas between two specs."""
    old_keys = set(old_schemas)
    new_keys = set(new_schemas)

    for name in sorted(old_keys - new_keys):
        changes.append(
            BreakingChange(
                change_type="schema_removed",
                path=f"components.schemas.{name}",
                old_value=name,
                new_value=None,
                severity="error",
            )
        )

    for name in sorted(new_keys - old_keys):
        changes.append(
            BreakingChange(
                change_type="schema_added",
                path=f"components.schemas.{name}",
                old_value=None,
                new_value=name,
                severity="info",
            )
        )

    for name in sorted(old_keys & new_keys):
        try:
            old_s = old_schemas[name] or {}
            new_s = new_schemas[name] or {}
            _compare_schemas(
                f"components.schemas.{name}",
                old_s,
                new_s,
                changes,
                context="request",
            )
        except (KeyError, TypeError, AttributeError) as exc:
            logger.warning("Error comparing component schema %s: %s", name, exc)


# ======================================================================
# Info / documentation comparison
# ======================================================================

def _compare_info(
    old_spec: dict[str, Any],
    new_spec: dict[str, Any],
    changes: list[BreakingChange],
) -> None:
    """Detect documentation-level changes in the info object."""
    old_info: dict[str, Any] = old_spec.get("info") or {}
    new_info: dict[str, Any] = new_spec.get("info") or {}

    for field in ("title", "description", "termsOfService"):
        try:
            old_val = old_info.get(field)
            new_val = new_info.get(field)
            if old_val != new_val and old_val is not None and new_val is not None:
                changes.append(
                    BreakingChange(
                        change_type="info_changed",
                        path=f"info.{field}",
                        old_value=str(old_val),
                        new_value=str(new_val),
                        severity="info",
                    )
                )
        except (TypeError, AttributeError) as exc:
            logger.warning("Error comparing info field %s: %s", field, exc)


# ======================================================================
# Utilities
# ======================================================================

def _schema_type(schema: dict[str, Any] | None) -> str | None:
    """Extract the ``type`` string from a JSON schema, if present."""
    if not isinstance(schema, dict):
        return None
    return schema.get("type")

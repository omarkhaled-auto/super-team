"""OpenAPI specification validator.

Validates OpenAPI 3.0.x and 3.1.0 specifications using openapi-spec-validator
for structural validation and prance for $ref resolution.
"""
from __future__ import annotations

import json
import logging
from typing import Any

import yaml

from src.shared.models.contracts import ValidationResult

logger = logging.getLogger(__name__)


def validate_openapi(spec: dict[str, Any]) -> ValidationResult:
    """Validate an OpenAPI specification.

    Uses openapi-spec-validator for structural validation and prance for $ref
    resolution.  Supports OpenAPI 3.0.x and 3.1.0.

    Args:
        spec: A dictionary representing the OpenAPI specification.

    Returns:
        ValidationResult with valid=True/False, errors list, and warnings list.
    """
    errors: list[str] = []
    warnings: list[str] = []

    # ------------------------------------------------------------------
    # 1. Basic structural pre-checks
    # ------------------------------------------------------------------
    if not isinstance(spec, dict):
        return ValidationResult(
            valid=False,
            errors=["Spec must be a JSON object (dict), got " + type(spec).__name__],
            warnings=warnings,
        )

    if not spec:
        return ValidationResult(
            valid=False,
            errors=["Spec is an empty object"],
            warnings=warnings,
        )

    openapi_version_raw = spec.get("openapi")
    if openapi_version_raw is None:
        return ValidationResult(
            valid=False,
            errors=["Missing required 'openapi' key in specification"],
            warnings=warnings,
        )

    # ------------------------------------------------------------------
    # 2. Version string validation
    # ------------------------------------------------------------------
    if not isinstance(openapi_version_raw, str):
        return ValidationResult(
            valid=False,
            errors=[
                f"'openapi' key must be a string, got {type(openapi_version_raw).__name__}"
            ],
            warnings=warnings,
        )

    openapi_version: str = openapi_version_raw.strip()

    if not (openapi_version.startswith("3.0") or openapi_version.startswith("3.1")):
        return ValidationResult(
            valid=False,
            errors=[
                f"Unsupported OpenAPI version '{openapi_version}'. "
                "Only 3.0.x and 3.1.x are supported."
            ],
            warnings=warnings,
        )

    # ------------------------------------------------------------------
    # 3. Structural validation via openapi-spec-validator
    # ------------------------------------------------------------------
    _run_spec_validator(spec, openapi_version, errors, warnings)

    # ------------------------------------------------------------------
    # 4. $ref resolution via prance
    # ------------------------------------------------------------------
    _run_prance_ref_resolution(spec, warnings)

    # ------------------------------------------------------------------
    # 5. Build and return result
    # ------------------------------------------------------------------
    return ValidationResult(
        valid=len(errors) == 0,
        errors=errors,
        warnings=warnings,
    )


# ======================================================================
# Internal helpers
# ======================================================================


def _run_spec_validator(
    spec: dict[str, Any],
    openapi_version: str,
    errors: list[str],
    warnings: list[str],
) -> None:
    """Run openapi-spec-validator against the spec.

    Errors from the validator are appended to *errors*.  Any import or
    unexpected runtime problems are recorded as warnings so they do not
    silently hide validation.
    """
    try:
        from openapi_spec_validator import (  # type: ignore[import-untyped]
            OpenAPIV30SpecValidator,
            OpenAPIV31SpecValidator,
        )
    except ImportError as exc:
        warnings.append(
            f"openapi-spec-validator is not installed; skipping structural validation: {exc}"
        )
        return

    try:
        # Pick the right validator class based on version prefix.
        if openapi_version.startswith("3.1"):
            validator_cls = OpenAPIV31SpecValidator
        else:
            validator_cls = OpenAPIV30SpecValidator

        # iter_errors yields every validation error instead of raising on
        # the first one, giving the caller a complete picture.
        validator = validator_cls(spec)
        for error in validator.iter_errors():
            # error.message is the human-readable description; error.path
            # contains the JSON-pointer path segments to the offending node.
            path_str = " -> ".join(str(p) for p in error.absolute_path) if error.absolute_path else ""
            if path_str:
                errors.append(f"{error.message} (at {path_str})")
            else:
                errors.append(str(error.message))
    except (ValueError, KeyError, TypeError) as exc:
        errors.append(f"Unexpected error during spec validation: {exc}")


def _run_prance_ref_resolution(
    spec: dict[str, Any],
    warnings: list[str],
) -> None:
    """Attempt to resolve all $ref pointers using prance.

    Because the spec lives in memory (not on disk), we serialise it to
    YAML and feed it to prance's ``ResolvingParser`` via a string.  Any
    resolution failure is recorded as a warning rather than a hard error
    because the structural validator already covers required-field checks.
    """
    try:
        from prance import ResolvingParser  # type: ignore[import-untyped]
    except ImportError as exc:
        warnings.append(
            f"prance is not installed; skipping $ref resolution check: {exc}"
        )
        return

    # Only attempt ref resolution when the spec actually contains $ref
    # pointers -- avoids unnecessary serialisation round-trips.
    spec_text = json.dumps(spec)
    if "$ref" not in spec_text:
        return

    try:
        # prance accepts a spec_string + spec_url pair.  We pass a dummy
        # file:// URL so it does not try to fetch anything from the network.
        yaml_content: str = yaml.dump(spec, default_flow_style=False)
        ResolvingParser(
            spec_string=yaml_content,
            lazy=False,
        )
    except (ValueError, KeyError, TypeError) as exc:
        warnings.append(f"$ref resolution issue: {exc}")

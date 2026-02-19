"""Tests for the OpenAPI specification validator.

Covers structural pre-checks, version handling, and integration with
openapi-spec-validator / prance (mocked where appropriate).
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from src.contract_engine.services.openapi_validator import validate_openapi


# ======================================================================
# 1. Valid specifications
# ======================================================================


def test_valid_openapi_31():
    """A minimal but complete OpenAPI 3.1.0 spec should pass validation."""
    spec = {
        "openapi": "3.1.0",
        "info": {"title": "Test", "version": "1.0.0"},
        "paths": {},
    }
    result = validate_openapi(spec)
    assert result.valid is True
    assert result.errors == []


def test_valid_openapi_30():
    """A minimal but complete OpenAPI 3.0.3 spec should pass validation."""
    spec = {
        "openapi": "3.0.3",
        "info": {"title": "Test", "version": "1.0.0"},
        "paths": {},
    }
    result = validate_openapi(spec)
    assert result.valid is True
    assert result.errors == []


def test_valid_with_paths():
    """A spec that includes populated paths should still pass."""
    spec = {
        "openapi": "3.1.0",
        "info": {"title": "Test API", "version": "1.0.0"},
        "paths": {
            "/users": {
                "get": {
                    "summary": "List users",
                    "responses": {"200": {"description": "OK"}},
                }
            }
        },
    }
    result = validate_openapi(spec)
    assert result.valid is True
    assert result.errors == []


# ======================================================================
# 2. Empty / missing input
# ======================================================================


def test_empty_spec():
    """An empty dict should be reported as invalid."""
    result = validate_openapi({})
    assert result.valid is False
    assert len(result.errors) >= 1
    assert any("empty" in e.lower() for e in result.errors)


def test_not_a_dict():
    """A non-dict input (e.g. a bare string) should be reported as invalid."""
    result = validate_openapi("not a dict")
    assert result.valid is False
    assert len(result.errors) >= 1
    assert any("dict" in e.lower() or "object" in e.lower() for e in result.errors)


# ======================================================================
# 3. Missing / invalid top-level keys
# ======================================================================


def test_missing_openapi_key():
    """A spec without the 'openapi' key should fail validation."""
    result = validate_openapi({"info": {"title": "Test", "version": "1.0.0"}})
    assert result.valid is False
    assert any("openapi" in e.lower() for e in result.errors)


def test_unsupported_version():
    """An OpenAPI 2.0 (Swagger) version string should be rejected."""
    spec = {
        "openapi": "2.0",
        "info": {"title": "Test", "version": "1.0.0"},
        "paths": {},
    }
    result = validate_openapi(spec)
    assert result.valid is False
    assert any("unsupported" in e.lower() or "version" in e.lower() for e in result.errors)


def test_missing_info():
    """A spec without the 'info' object should fail structural validation."""
    spec = {"openapi": "3.1.0", "paths": {}}
    result = validate_openapi(spec)
    # The structural validator (openapi-spec-validator) should flag this.
    assert result.valid is False
    assert len(result.errors) >= 1


# ======================================================================
# 4. Edge cases
# ======================================================================


def test_openapi_version_not_a_string():
    """If the 'openapi' key value is not a string, validation should fail."""
    spec = {
        "openapi": 3.1,
        "info": {"title": "Test", "version": "1.0.0"},
        "paths": {},
    }
    result = validate_openapi(spec)
    assert result.valid is False
    assert any("string" in e.lower() for e in result.errors)


def test_result_contains_warnings_list():
    """Even a valid result should carry an (empty) warnings list."""
    spec = {
        "openapi": "3.1.0",
        "info": {"title": "T", "version": "0.0.1"},
        "paths": {},
    }
    result = validate_openapi(spec)
    assert isinstance(result.warnings, list)


def test_result_model_fields():
    """The ValidationResult should expose valid, errors, and warnings."""
    result = validate_openapi({})
    assert hasattr(result, "valid")
    assert hasattr(result, "errors")
    assert hasattr(result, "warnings")

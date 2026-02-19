"""Tests for the AsyncAPI specification validator.

Covers top-level key checks, version validation, info block validation,
operation action validation, and full valid specs with channels and
operations.
"""
from __future__ import annotations

from typing import Any

import pytest

from src.contract_engine.services.asyncapi_validator import validate_asyncapi


# ======================================================================
# Helpers
# ======================================================================


def _minimal_valid_spec(**overrides: Any) -> dict[str, Any]:
    """Return a minimal AsyncAPI 3.0 spec that passes validation."""
    base: dict[str, Any] = {
        "asyncapi": "3.0.0",
        "info": {"title": "Test Service", "version": "1.0.0"},
    }
    base.update(overrides)
    return base


# ======================================================================
# 1. Valid specifications
# ======================================================================


def test_valid_asyncapi_30():
    """A minimal valid AsyncAPI 3.0 spec should return valid=True with no errors."""
    spec = _minimal_valid_spec()
    result = validate_asyncapi(spec)
    assert result.valid is True
    assert result.errors == []


def test_valid_with_channels_and_operations():
    """A spec with well-formed channels and operations should pass validation."""
    spec: dict[str, Any] = {
        "asyncapi": "3.0.0",
        "info": {"title": "Events API", "version": "2.0.0"},
        "channels": {
            "userSignedup": {
                "address": "user/signedup",
                "description": "User signup events",
            }
        },
        "operations": {
            "publishUserSignedup": {
                "action": "send",
                "channel": {"$ref": "#/channels/userSignedup"},
                "summary": "Publish user signup event",
            }
        },
    }
    result = validate_asyncapi(spec)
    assert result.valid is True
    assert result.errors == []


# ======================================================================
# 2. Missing top-level keys
# ======================================================================


def test_missing_asyncapi_key():
    """A spec without the 'asyncapi' key should return valid=False."""
    spec = {"info": {"title": "Test", "version": "1.0.0"}}
    result = validate_asyncapi(spec)
    assert result.valid is False
    assert any("asyncapi" in e.lower() for e in result.errors)


def test_empty_spec():
    """An empty dict should return valid=False."""
    result = validate_asyncapi({})
    assert result.valid is False
    assert len(result.errors) >= 1


def test_not_a_dict():
    """A non-dict input should return valid=False."""
    result = validate_asyncapi("not a dict")  # type: ignore[arg-type]
    assert result.valid is False
    assert any("dict" in e.lower() for e in result.errors)


# ======================================================================
# 3. Version validation
# ======================================================================


def test_wrong_version():
    """A version that does not start with '3.' should produce errors."""
    spec = {
        "asyncapi": "2.6.0",
        "info": {"title": "Test", "version": "1.0.0"},
    }
    result = validate_asyncapi(spec)
    assert result.valid is False
    assert any("version" in e.lower() or "unsupported" in e.lower() for e in result.errors)


# ======================================================================
# 4. Info block validation
# ======================================================================


def test_missing_info_title():
    """A spec with info but no title should produce an error."""
    spec = {
        "asyncapi": "3.0.0",
        "info": {"version": "1.0.0"},
    }
    result = validate_asyncapi(spec)
    assert result.valid is False
    assert any("title" in e.lower() for e in result.errors)


def test_missing_info_version():
    """A spec with info but no version should produce an error."""
    spec = {
        "asyncapi": "3.0.0",
        "info": {"title": "Test"},
    }
    result = validate_asyncapi(spec)
    assert result.valid is False
    assert any("version" in e.lower() for e in result.errors)


# ======================================================================
# 5. Operation validation
# ======================================================================


def test_invalid_operation_action():
    """An operation whose action is not 'send' or 'receive' should produce errors."""
    spec: dict[str, Any] = {
        "asyncapi": "3.0.0",
        "info": {"title": "Test", "version": "1.0.0"},
        "channels": {
            "events": {"address": "events"},
        },
        "operations": {
            "badOp": {
                "action": "publish",  # invalid -- must be send or receive
                "channel": {"$ref": "#/channels/events"},
            }
        },
    }
    result = validate_asyncapi(spec)
    assert result.valid is False
    assert any("action" in e.lower() for e in result.errors)


# ======================================================================
# 6. Result model structure
# ======================================================================


def test_result_has_warnings_list():
    """Every result should carry a warnings list, even when empty."""
    result = validate_asyncapi(_minimal_valid_spec())
    assert isinstance(result.warnings, list)


def test_result_model_fields():
    """The ValidationResult should expose valid, errors, and warnings."""
    result = validate_asyncapi({})
    assert hasattr(result, "valid")
    assert hasattr(result, "errors")
    assert hasattr(result, "warnings")

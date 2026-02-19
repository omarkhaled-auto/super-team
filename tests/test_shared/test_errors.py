"""Tests for shared error classes and exception handlers."""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.shared.errors import (
    AppError,
    ConflictError,
    ContractNotFoundError,
    ImmutabilityViolationError,
    NotFoundError,
    ParsingError,
    SchemaError,
    ValidationError,
    register_exception_handlers,
)


class TestAppError:
    """Tests for the base AppError exception."""

    def test_default_status_code(self):
        err = AppError(detail="something broke")
        assert err.status_code == 500
        assert err.detail == "something broke"

    def test_custom_status_code(self):
        err = AppError(detail="bad request", status_code=400)
        assert err.status_code == 400

    def test_inherits_from_exception(self):
        err = AppError(detail="test")
        assert isinstance(err, Exception)

    def test_str_is_detail(self):
        err = AppError(detail="human readable")
        assert str(err) == "human readable"


class TestValidationError:
    """Tests for ValidationError (422)."""

    def test_default_detail(self):
        err = ValidationError()
        assert err.status_code == 422
        assert err.detail == "Validation error"

    def test_custom_detail(self):
        err = ValidationError(detail="Field 'name' is required")
        assert err.detail == "Field 'name' is required"
        assert err.status_code == 422

    def test_inherits_from_app_error(self):
        assert issubclass(ValidationError, AppError)


class TestNotFoundError:
    """Tests for NotFoundError (404)."""

    def test_default_detail(self):
        err = NotFoundError()
        assert err.status_code == 404
        assert err.detail == "Resource not found"

    def test_custom_detail(self):
        err = NotFoundError(detail="User not found")
        assert err.detail == "User not found"

    def test_inherits_from_app_error(self):
        assert issubclass(NotFoundError, AppError)


class TestConflictError:
    """Tests for ConflictError (409)."""

    def test_default_detail(self):
        err = ConflictError()
        assert err.status_code == 409
        assert err.detail == "Conflict"

    def test_custom_detail(self):
        err = ConflictError(detail="Duplicate entry")
        assert err.detail == "Duplicate entry"

    def test_inherits_from_app_error(self):
        assert issubclass(ConflictError, AppError)


class TestImmutabilityViolationError:
    """Tests for ImmutabilityViolationError (409)."""

    def test_default_detail(self):
        err = ImmutabilityViolationError()
        assert err.status_code == 409
        assert err.detail == "Immutability violation"

    def test_custom_detail(self):
        err = ImmutabilityViolationError(detail="Cannot modify frozen contract")
        assert err.detail == "Cannot modify frozen contract"

    def test_inherits_from_app_error(self):
        assert issubclass(ImmutabilityViolationError, AppError)


class TestParsingError:
    """Tests for ParsingError (400)."""

    def test_default_detail(self):
        err = ParsingError()
        assert err.status_code == 400
        assert err.detail == "Parsing error"

    def test_custom_detail(self):
        err = ParsingError(detail="Invalid YAML syntax")
        assert err.detail == "Invalid YAML syntax"

    def test_inherits_from_app_error(self):
        assert issubclass(ParsingError, AppError)


class TestSchemaError:
    """Tests for SchemaError (422)."""

    def test_default_detail(self):
        err = SchemaError()
        assert err.status_code == 422
        assert err.detail == "Schema error"

    def test_custom_detail(self):
        err = SchemaError(detail="Missing required property 'type'")
        assert err.detail == "Missing required property 'type'"

    def test_inherits_from_app_error(self):
        assert issubclass(SchemaError, AppError)


class TestContractNotFoundError:
    """Tests for ContractNotFoundError (404)."""

    def test_default_detail(self):
        err = ContractNotFoundError()
        assert err.status_code == 404
        assert err.detail == "Contract not found"

    def test_custom_detail(self):
        err = ContractNotFoundError(detail="Contract abc-123 not found")
        assert err.detail == "Contract abc-123 not found"

    def test_inherits_from_app_error(self):
        assert issubclass(ContractNotFoundError, AppError)

    def test_inherits_from_not_found(self):
        """ContractNotFoundError is a specialized NotFoundError-like class
        but actually inherits from AppError directly."""
        assert issubclass(ContractNotFoundError, AppError)


class TestRegisterExceptionHandlers:
    """Tests for register_exception_handlers on a FastAPI app."""

    def test_app_error_returns_json(self):
        app = FastAPI()
        register_exception_handlers(app)

        @app.get("/test-500")
        async def _raise_app():
            raise AppError(detail="server error")

        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get("/test-500")
        assert resp.status_code == 500
        assert resp.json() == {"detail": "server error"}

    def test_not_found_error_returns_404(self):
        app = FastAPI()
        register_exception_handlers(app)

        @app.get("/test-404")
        async def _raise_nf():
            raise NotFoundError(detail="gone")

        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get("/test-404")
        assert resp.status_code == 404
        assert resp.json() == {"detail": "gone"}

    def test_validation_error_returns_422(self):
        app = FastAPI()
        register_exception_handlers(app)

        @app.get("/test-422")
        async def _raise_val():
            raise ValidationError(detail="bad field")

        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get("/test-422")
        assert resp.status_code == 422
        assert resp.json() == {"detail": "bad field"}

    def test_conflict_error_returns_409(self):
        app = FastAPI()
        register_exception_handlers(app)

        @app.get("/test-409")
        async def _raise_conflict():
            raise ConflictError(detail="already exists")

        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get("/test-409")
        assert resp.status_code == 409
        assert resp.json() == {"detail": "already exists"}

    def test_immutability_error_returns_409(self):
        app = FastAPI()
        register_exception_handlers(app)

        @app.get("/test-immutable")
        async def _raise_immut():
            raise ImmutabilityViolationError(detail="frozen")

        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get("/test-immutable")
        assert resp.status_code == 409
        assert resp.json() == {"detail": "frozen"}

    def test_parsing_error_returns_400(self):
        app = FastAPI()
        register_exception_handlers(app)

        @app.get("/test-parse")
        async def _raise_parse():
            raise ParsingError(detail="bad input")

        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get("/test-parse")
        assert resp.status_code == 400
        assert resp.json() == {"detail": "bad input"}

    def test_schema_error_returns_422(self):
        app = FastAPI()
        register_exception_handlers(app)

        @app.get("/test-schema")
        async def _raise_schema():
            raise SchemaError(detail="bad schema")

        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get("/test-schema")
        assert resp.status_code == 422
        assert resp.json() == {"detail": "bad schema"}

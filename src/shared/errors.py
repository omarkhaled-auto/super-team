"""Custom exception classes and FastAPI exception handlers."""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from starlette.requests import Request


class AppError(Exception):
    """Base application error."""

    def __init__(self, detail: str, status_code: int = 500) -> None:
        self.detail = detail
        self.status_code = status_code
        super().__init__(detail)


class ValidationError(AppError):
    """Validation error (422)."""

    def __init__(self, detail: str = "Validation error") -> None:
        super().__init__(detail=detail, status_code=422)


class NotFoundError(AppError):
    """Resource not found (404)."""

    def __init__(self, detail: str = "Resource not found") -> None:
        super().__init__(detail=detail, status_code=404)


class ConflictError(AppError):
    """Conflict error (409)."""

    def __init__(self, detail: str = "Conflict") -> None:
        super().__init__(detail=detail, status_code=409)


class ImmutabilityViolationError(AppError):
    """Immutability violation (409)."""

    def __init__(self, detail: str = "Immutability violation") -> None:
        super().__init__(detail=detail, status_code=409)


class ParsingError(AppError):
    """Parsing error (400)."""

    def __init__(self, detail: str = "Parsing error") -> None:
        super().__init__(detail=detail, status_code=400)


class SchemaError(AppError):
    """Schema error (422)."""

    def __init__(self, detail: str = "Schema error") -> None:
        super().__init__(detail=detail, status_code=422)


class ContractNotFoundError(AppError):
    """Contract not found (404)."""

    def __init__(self, detail: str = "Contract not found") -> None:
        super().__init__(detail=detail, status_code=404)


def register_exception_handlers(app: FastAPI) -> None:
    """Register custom exception handlers with a FastAPI app."""

    @app.exception_handler(AppError)
    async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": exc.detail},
        )

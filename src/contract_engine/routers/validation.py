"""Validation endpoint for contract specifications."""
from __future__ import annotations
import asyncio
from typing import Any

from fastapi import APIRouter, Request

from src.contract_engine.services.openapi_validator import validate_openapi
from src.contract_engine.services.asyncapi_validator import validate_asyncapi
from src.shared.models.contracts import ValidationResult, ValidateRequest, ContractType

router = APIRouter(prefix="/api", tags=["validation"])


@router.post("/validate", response_model=ValidationResult)
async def validate_spec(body: ValidateRequest, request: Request) -> ValidationResult:
    """Validate a contract specification.

    Dispatches to the appropriate validator based on the type field.
    Returns ValidationResult with valid, errors, warnings.
    """
    if body.type == ContractType.OPENAPI:
        return await asyncio.to_thread(validate_openapi, body.spec)
    elif body.type == ContractType.ASYNCAPI:
        return await asyncio.to_thread(validate_asyncapi, body.spec)
    else:
        # json_schema type - basic validation
        return ValidationResult(valid=True, errors=[], warnings=["JSON Schema validation not yet implemented"])

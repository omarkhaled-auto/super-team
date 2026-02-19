from __future__ import annotations

import asyncio

from fastapi import APIRouter, Query, Request, Response
from fastapi.responses import JSONResponse

from src.contract_engine.services.asyncapi_validator import validate_asyncapi
from src.contract_engine.services.contract_store import ContractStore
from src.contract_engine.services.openapi_validator import validate_openapi
from src.shared.errors import SchemaError
from src.shared.models.contracts import (
    ContractCreate,
    ContractEntry,
    ContractListResponse,
    ContractType,
)

router = APIRouter(prefix="/api", tags=["contracts"])

# 5 MB limit
_MAX_PAYLOAD_BYTES = 5 * 1024 * 1024


@router.post("/contracts", response_model=ContractEntry, status_code=201)
async def create_contract(body: ContractCreate, request: Request) -> ContractEntry:
    """Create or update a contract. Validates spec before storage."""
    content_length = request.headers.get("content-length")
    if content_length and int(content_length) > _MAX_PAYLOAD_BYTES:
        return JSONResponse(status_code=413, content={"detail": "Payload too large"})

    # Validate spec based on type
    if body.type == ContractType.OPENAPI:
        result = await asyncio.to_thread(validate_openapi, body.spec)
    elif body.type == ContractType.ASYNCAPI:
        result = await asyncio.to_thread(validate_asyncapi, body.spec)
    else:
        result = None  # json_schema - no built-in validator yet

    if result and not result.valid:
        raise SchemaError(detail=f"Invalid spec: {'; '.join(result.errors)}")

    store = ContractStore(request.app.state.pool)
    entry = await asyncio.to_thread(store.upsert, body)
    return entry


@router.get("/contracts", response_model=ContractListResponse)
async def list_contracts(
    request: Request,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    service_name: str | None = Query(None),
    type: str | None = Query(None),
    status: str | None = Query(None),
) -> ContractListResponse:
    """List contracts with pagination and optional filters."""
    store = ContractStore(request.app.state.pool)
    return await asyncio.to_thread(
        store.list,
        page=page,
        page_size=page_size,
        service_name=service_name,
        contract_type=type,
        status=status,
    )


@router.get("/contracts/{contract_id}", response_model=ContractEntry)
async def get_contract(contract_id: str, request: Request) -> ContractEntry:
    """Get a single contract by ID."""
    store = ContractStore(request.app.state.pool)
    return await asyncio.to_thread(store.get, contract_id)


@router.delete("/contracts/{contract_id}", status_code=204)
async def delete_contract(contract_id: str, request: Request) -> Response:
    """Delete a contract by ID."""
    store = ContractStore(request.app.state.pool)
    await asyncio.to_thread(store.delete, contract_id)
    return Response(status_code=204)

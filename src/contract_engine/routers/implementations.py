"""Implementation tracking endpoints."""
from __future__ import annotations
import asyncio
from fastapi import APIRouter, Request, Query

from src.contract_engine.services.implementation_tracker import ImplementationTracker
from src.shared.models.contracts import MarkRequest, MarkResponse, UnimplementedContract

router = APIRouter(prefix="/api", tags=["implementations"])


@router.post("/implementations/mark", response_model=MarkResponse)
async def mark_implemented(body: MarkRequest, request: Request) -> MarkResponse:
    """Mark a contract as implemented by a service."""
    tracker = ImplementationTracker(request.app.state.pool)
    return await asyncio.to_thread(
        tracker.mark_implemented, body.contract_id, body.service_name, body.evidence_path
    )


@router.get("/implementations/unimplemented", response_model=list[UnimplementedContract])
async def get_unimplemented(
    request: Request,
    service_name: str | None = Query(None),
) -> list[UnimplementedContract]:
    """Get contracts that haven't been implemented yet."""
    tracker = ImplementationTracker(request.app.state.pool)
    return await asyncio.to_thread(tracker.get_unimplemented, service_name)

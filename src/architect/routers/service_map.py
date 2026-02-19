"""Service map router for the Architect service."""
from __future__ import annotations

import asyncio

from fastapi import APIRouter, Query, Request

from src.shared.errors import NotFoundError
from src.shared.models.architect import ServiceMap
from src.architect.storage.service_map_store import ServiceMapStore

router = APIRouter(tags=["service-map"])


@router.get("/api/service-map")
async def get_service_map(
    request: Request,
    project_name: str | None = Query(default=None, description="Filter by project name"),
) -> ServiceMap:
    """Get the latest service map, optionally filtered by project name."""
    pool = request.app.state.pool
    store = ServiceMapStore(pool)

    service_map = await asyncio.to_thread(store.get_latest, project_name)

    if service_map is None:
        raise NotFoundError("No service map found")

    return service_map

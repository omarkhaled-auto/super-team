"""Domain model router for the Architect service."""
from __future__ import annotations

import asyncio

from fastapi import APIRouter, Query, Request

from src.shared.errors import NotFoundError
from src.shared.models.architect import DomainModel
from src.architect.storage.domain_model_store import DomainModelStore

router = APIRouter(tags=["domain-model"])


@router.get("/api/domain-model")
async def get_domain_model(
    request: Request,
    project_name: str | None = Query(default=None, description="Filter by project name"),
) -> DomainModel:
    """Get the latest domain model, optionally filtered by project name."""
    pool = request.app.state.pool
    store = DomainModelStore(pool)

    domain_model = await asyncio.to_thread(store.get_latest, project_name)

    if domain_model is None:
        raise NotFoundError("No domain model found")

    return domain_model

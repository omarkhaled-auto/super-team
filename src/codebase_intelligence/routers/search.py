"""Semantic search router."""
from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

router = APIRouter(prefix="/api/search", tags=["search"])


class SearchRequest(BaseModel):
    """Semantic search request body."""
    query: str = Field(..., min_length=1, max_length=10000)
    language: str | None = None
    service_name: str | None = None
    top_k: int = Field(10, ge=1, le=100)


@router.post("")
async def semantic_search(request: Request, body: SearchRequest) -> list[dict[str, Any]]:
    """Search code semantically."""
    searcher = request.app.state.semantic_searcher

    def _search() -> list[dict[str, Any]]:
        results = searcher.search(
            query=body.query,
            language=body.language,
            service_name=body.service_name,
            top_k=body.top_k,
        )
        return [r.model_dump() for r in results]

    return await asyncio.to_thread(_search)

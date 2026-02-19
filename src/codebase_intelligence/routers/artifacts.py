"""Artifact indexing router."""
from __future__ import annotations

import asyncio
import base64
from typing import Any

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

router = APIRouter(prefix="/api/artifacts", tags=["artifacts"])


class ArtifactRequest(BaseModel):
    """Artifact registration request body."""
    file_path: str = Field(..., min_length=1)
    service_name: str | None = None
    source: str | None = Field(None, description="Base64-encoded source content")
    project_root: str | None = None


@router.post("")
async def register_artifact(request: Request, body: ArtifactRequest) -> dict[str, Any]:
    """Index a file through the full pipeline."""
    indexer = request.app.state.incremental_indexer

    def _index() -> dict[str, Any]:
        source_bytes = None
        if body.source:
            source_bytes = base64.b64decode(body.source)

        result = indexer.index_file(
            file_path=body.file_path,
            source=source_bytes,
            service_name=body.service_name,
            project_root=body.project_root,
        )
        return result

    return await asyncio.to_thread(_index)

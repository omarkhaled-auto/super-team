"""Dependency and graph analysis router."""
from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, Query, Request

from src.shared.errors import NotFoundError

router = APIRouter(tags=["dependencies"])


@router.get("/api/dependencies")
async def get_dependencies(
    request: Request,
    file_path: str = Query(..., description="File path to analyze"),
    depth: int = Query(1, ge=1, le=100, description="Traversal depth"),
    direction: str = Query("both", description="Direction: forward, reverse, or both"),
) -> dict[str, Any]:
    """Get dependencies for a file."""
    graph_analyzer = request.app.state.graph_analyzer

    def _analyze() -> dict[str, Any]:
        forward = graph_analyzer.get_dependencies(file_path, depth=depth) if direction in ("forward", "both") else []
        reverse = graph_analyzer.get_dependents(file_path, depth=depth) if direction in ("reverse", "both") else []
        return {
            "file_path": file_path,
            "depth": depth,
            "dependencies": forward,
            "dependents": reverse,
        }

    return await asyncio.to_thread(_analyze)


@router.get("/api/graph/analysis")
async def get_graph_analysis(request: Request) -> dict[str, Any]:
    """Get full graph analysis."""
    graph_analyzer = request.app.state.graph_analyzer

    def _analyze() -> dict[str, Any]:
        analysis = graph_analyzer.analyze()
        return analysis.model_dump()

    return await asyncio.to_thread(_analyze)

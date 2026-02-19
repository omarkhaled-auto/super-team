"""Health check router."""
from __future__ import annotations

import asyncio
import time

import sqlite3

from fastapi import APIRouter, Request

from src.shared.constants import CODEBASE_INTEL_SERVICE_NAME, VERSION
from src.shared.models.common import HealthStatus

router = APIRouter(tags=["health"])


@router.get("/api/health")
async def health(request: Request) -> HealthStatus:
    """Health check with database and ChromaDB connectivity."""

    def _check() -> HealthStatus:
        db_status = "disconnected"
        details: dict = {}

        # Check SQLite
        pool = getattr(request.app.state, "pool", None)
        if pool:
            try:
                pool.get().execute("SELECT 1")
                db_status = "connected"
            except (sqlite3.Error, OSError, RuntimeError):
                db_status = "disconnected"

        # Check ChromaDB
        chroma_store = getattr(request.app.state, "chroma_store", None)
        if chroma_store:
            try:
                count = chroma_store.get_stats()
                details["chroma_chunks"] = count
                details["chroma"] = "connected"
            except (OSError, RuntimeError):
                details["chroma"] = "disconnected"
        else:
            details["chroma"] = "not_initialized"

        status = "healthy" if db_status == "connected" else "degraded"
        start_time = getattr(request.app.state, "start_time", time.time())

        return HealthStatus(
            status=status,
            service_name=CODEBASE_INTEL_SERVICE_NAME,
            version=VERSION,
            database=db_status,
            uptime_seconds=time.time() - start_time,
            details=details,
        )

    return await asyncio.to_thread(_check)

"""Health check endpoint for the Contract Engine."""
from __future__ import annotations
import asyncio
import time
import sqlite3

from fastapi import APIRouter, Request

from src.shared.models.common import HealthStatus
from src.shared.constants import VERSION, CONTRACT_ENGINE_SERVICE_NAME

router = APIRouter(prefix="/api", tags=["health"])


@router.get("/health", response_model=HealthStatus)
async def health(request: Request) -> HealthStatus:
    """Health check endpoint."""

    def _check() -> HealthStatus:
        db_status = "connected"
        pool = getattr(request.app.state, "pool", None)
        if pool:
            try:
                pool.get().execute("SELECT 1")
            except (sqlite3.Error, OSError):
                db_status = "disconnected"
        else:
            db_status = "disconnected"

        start_time = getattr(request.app.state, "start_time", time.time())

        return HealthStatus(
            status="healthy" if db_status == "connected" else "degraded",
            service_name=CONTRACT_ENGINE_SERVICE_NAME,
            version=VERSION,
            database=db_status,
            uptime_seconds=time.time() - start_time,
        )

    return await asyncio.to_thread(_check)

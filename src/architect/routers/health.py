"""Health check router for the Architect service."""
from __future__ import annotations

import asyncio
import time

import sqlite3

from fastapi import APIRouter, Request

from src.shared.constants import ARCHITECT_SERVICE_NAME, VERSION
from src.shared.models.common import HealthStatus

router = APIRouter(tags=["health"])


@router.get("/api/health")
async def health(request: Request) -> HealthStatus:
    """Health check endpoint returning service status."""

    def _check() -> HealthStatus:
        pool = request.app.state.pool
        start_time = request.app.state.start_time

        db_status = "connected"
        if pool:
            try:
                pool.get().execute("SELECT 1")
            except (sqlite3.Error, OSError):
                db_status = "disconnected"
        else:
            db_status = "disconnected"

        return HealthStatus(
            status="healthy" if db_status == "connected" else "degraded",
            service_name=ARCHITECT_SERVICE_NAME,
            version=VERSION,
            database=db_status,
            uptime_seconds=time.time() - start_time,
        )

    return await asyncio.to_thread(_check)

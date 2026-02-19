"""Dead code detection router."""
from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, Query, Request

router = APIRouter(prefix="/api/dead-code", tags=["dead-code"])


@router.get("")
async def find_dead_code(
    request: Request,
    service_name: str | None = Query(None, description="Filter by service"),
) -> list[dict[str, Any]]:
    """Detect potentially dead code."""
    dead_code_detector = request.app.state.dead_code_detector
    symbol_db = request.app.state.symbol_db

    def _detect() -> list[dict[str, Any]]:
        # Get all symbols from DB
        conn = symbol_db._pool.get()
        if service_name:
            cursor = conn.execute(
                "SELECT * FROM symbols WHERE service_name = ?", (service_name,)
            )
        else:
            cursor = conn.execute("SELECT * FROM symbols")

        symbols = [symbol_db._row_to_symbol(row) for row in cursor.fetchall()]

        if not symbols:
            return []

        entries = dead_code_detector.find_dead_code(symbols)

        # Filter by service_name if provided
        if service_name:
            entries = [e for e in entries if e.service_name == service_name]

        return [e.model_dump() for e in entries]

    return await asyncio.to_thread(_detect)

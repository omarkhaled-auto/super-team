"""Symbol query router."""
from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, Query, Request

from src.shared.models.codebase import SymbolDefinition

router = APIRouter(prefix="/api/symbols", tags=["symbols"])


@router.get("")
async def list_symbols(
    request: Request,
    name: str | None = Query(None, description="Filter by symbol name"),
    kind: str | None = Query(None, description="Filter by symbol kind"),
    language: str | None = Query(None, description="Filter by language"),
    service_name: str | None = Query(None, description="Filter by service"),
    file_path: str | None = Query(None, description="Filter by file path"),
) -> list[dict[str, Any]]:
    """Query symbols with optional filters."""
    symbol_db = request.app.state.symbol_db

    def _query() -> list[dict[str, Any]]:
        if name:
            results = symbol_db.query_by_name(name, kind=kind)
        elif file_path:
            results = symbol_db.query_by_file(file_path)
        else:
            # Query all symbols from DB with filters
            conn = symbol_db._pool.get()
            sql = "SELECT * FROM symbols WHERE 1=1"
            params = []
            if kind:
                sql += " AND kind = ?"
                params.append(kind)
            if language:
                sql += " AND language = ?"
                params.append(language)
            if service_name:
                sql += " AND service_name = ?"
                params.append(service_name)
            sql += " LIMIT 100"
            cursor = conn.execute(sql, params)
            results = [symbol_db._row_to_symbol(row) for row in cursor.fetchall()]

        # Apply additional filters if needed
        if name and language:
            results = [s for s in results if s.language.value == language]
        if name and service_name:
            results = [s for s in results if s.service_name == service_name]

        return [s.model_dump() for s in results]

    return await asyncio.to_thread(_query)

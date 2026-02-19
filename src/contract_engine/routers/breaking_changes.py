"""Breaking change detection endpoint."""
from __future__ import annotations
import asyncio
import json
from typing import Any

from fastapi import APIRouter, Request

from src.contract_engine.services.contract_store import ContractStore
from src.contract_engine.services.breaking_change_detector import detect_breaking_changes
from src.contract_engine.services.version_manager import VersionManager
from src.shared.models.contracts import BreakingChange, ContractVersion
from src.shared.errors import ContractNotFoundError


router = APIRouter(prefix="/api", tags=["breaking-changes"])


@router.post("/breaking-changes/{contract_id}", response_model=list[BreakingChange])
async def check_breaking_changes(
    contract_id: str,
    request: Request,
    new_spec: dict[str, Any] | None = None,
) -> list[BreakingChange]:
    """Detect breaking changes for a contract.

    Compares the current stored spec with either:
    - The provided new_spec in the request body
    - The previous version of the same contract (if no new_spec provided)

    Logic:
    1. Get the current contract from store
    2. If new_spec provided, compare current vs new_spec
    3. If no new_spec, compare with previous version (get version history, use second entry)
    4. Return list of BreakingChange objects
    """
    store = ContractStore(request.app.state.pool)
    current_contract = await asyncio.to_thread(store.get, contract_id)
    current_spec = current_contract.spec

    if new_spec is not None:
        return await asyncio.to_thread(detect_breaking_changes, current_spec, new_spec)

    # No new_spec provided -- compare against the previous version
    version_mgr = VersionManager(request.app.state.pool)
    history = await asyncio.to_thread(version_mgr.get_version_history, contract_id)

    if len(history) < 2:
        # No previous version to compare against
        return []

    # history is ordered by created_at DESC: index 0 is latest, index 1 is previous
    previous_version = history[1]

    # Retrieve the previous contract spec from the contracts table.
    def _get_prev_spec() -> dict[str, Any] | None:
        conn = request.app.state.pool.get()
        row = conn.execute(
            "SELECT spec_json FROM contracts "
            "WHERE service_name = ? AND type = ? AND version = ?",
            (current_contract.service_name, current_contract.type.value, previous_version.version),
        ).fetchone()
        if row is None:
            return None
        return json.loads(row["spec_json"])

    old_spec = await asyncio.to_thread(_get_prev_spec)
    if old_spec is None:
        return []

    return await asyncio.to_thread(detect_breaking_changes, old_spec, current_spec)

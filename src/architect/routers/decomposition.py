"""Decomposition router for the Architect service."""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Request

from src.shared.models.architect import (
    DecomposeRequest,
    DecompositionResult,
    DecompositionRun,
)
from src.architect.services.prd_parser import parse_prd
from src.architect.services.service_boundary import identify_boundaries, build_service_map
from src.architect.services.domain_modeler import build_domain_model
from src.architect.services.validator import validate_decomposition
from src.architect.services.contract_generator import generate_contract_stubs
from src.architect.storage.service_map_store import ServiceMapStore
from src.architect.storage.domain_model_store import DomainModelStore

logger = logging.getLogger("architect")

router = APIRouter(tags=["decomposition"])


def _run_decomposition(
    prd_text: str,
    service_map_store: ServiceMapStore,
    domain_model_store: DomainModelStore,
) -> DecompositionResult:
    """Run the full decomposition pipeline synchronously.

    This function is called via asyncio.to_thread() from the async endpoint.
    """
    # Step 1: Parse PRD
    parsed = parse_prd(prd_text)

    # Step 2: Identify service boundaries
    boundaries = identify_boundaries(parsed)

    # Step 3: Build service map
    prd_hash = hashlib.sha256(prd_text.encode("utf-8")).hexdigest()
    service_map = build_service_map(parsed, boundaries)
    # Override prd_hash with actual hash of the full text
    service_map = service_map.model_copy(update={"prd_hash": prd_hash})

    # Step 4: Build domain model
    domain_model = build_domain_model(parsed, boundaries)

    # Step 5: Validate decomposition
    validation_issues = validate_decomposition(service_map, domain_model)

    # Step 6: Generate contract stubs
    contract_stubs = generate_contract_stubs(service_map, domain_model)

    # Step 7: Persist results
    service_map_id = service_map_store.save(service_map)
    domain_model_id = domain_model_store.save(domain_model, service_map.project_name)

    # Step 8: Save decomposition run record
    run = DecompositionRun(
        prd_content_hash=prd_hash,
        status="completed" if not validation_issues else "review",
        service_map_id=service_map_id,
        domain_model_id=domain_model_id,
        validation_issues=validation_issues,
        interview_questions=parsed.interview_questions,
        completed_at=datetime.now(timezone.utc),
    )

    # Save the run to the database
    conn = service_map_store._pool.get()
    conn.execute(
        """INSERT INTO decomposition_runs
           (id, prd_content_hash, service_map_id, domain_model_id,
            validation_issues, interview_questions, status, started_at, completed_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            run.id,
            run.prd_content_hash,
            run.service_map_id,
            run.domain_model_id,
            json.dumps(run.validation_issues),
            json.dumps(run.interview_questions),
            run.status,
            run.started_at.isoformat(),
            run.completed_at.isoformat() if run.completed_at else None,
        ),
    )
    conn.commit()

    return DecompositionResult(
        service_map=service_map,
        domain_model=domain_model,
        contract_stubs=contract_stubs,
        validation_issues=validation_issues,
        interview_questions=parsed.interview_questions,
    )


@router.post("/api/decompose", status_code=201)
async def decompose(request: Request, body: DecomposeRequest) -> DecompositionResult:
    """Decompose a PRD into services, domain model, and contracts.

    Orchestrates the full decomposition pipeline:
    1. Parse PRD text
    2. Identify service boundaries
    3. Build service map
    4. Build domain model
    5. Validate decomposition
    6. Generate contract stubs
    7. Persist all results
    """
    pool = request.app.state.pool
    service_map_store = ServiceMapStore(pool)
    domain_model_store = DomainModelStore(pool)

    result = await asyncio.to_thread(
        _run_decomposition,
        body.prd_text,
        service_map_store,
        domain_model_store,
    )

    return result

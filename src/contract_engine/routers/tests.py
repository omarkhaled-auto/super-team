"""Router for test generation and compliance checking endpoints."""
from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse

from src.contract_engine.services.compliance_checker import ComplianceChecker
from src.contract_engine.services.test_generator import ContractTestGenerator
from src.shared.errors import ContractNotFoundError
from src.shared.models.contracts import ComplianceResult, ContractTestSuite

router = APIRouter(prefix="/api", tags=["tests"])


@router.post(
    "/tests/generate/{contract_id}",
    response_model=ContractTestSuite,
    status_code=200,
)
async def generate_tests(
    contract_id: str,
    request: Request,
    framework: str = Query("pytest", pattern=r"^(pytest|jest)$"),
    include_negative: bool = Query(False),
) -> ContractTestSuite:
    """Generate a test suite for a contract.

    If a cached suite exists with a matching ``spec_hash``, returns the
    cached version.  Otherwise generates fresh test code and persists it.
    """
    generator = ContractTestGenerator(request.app.state.pool)
    suite = await asyncio.to_thread(
        generator.generate_tests,
        contract_id,
        framework,
        include_negative,
    )
    return suite


@router.get(
    "/tests/{contract_id}",
    response_model=ContractTestSuite,
)
async def get_test_suite(
    contract_id: str,
    request: Request,
    framework: str = Query("pytest", pattern=r"^(pytest|jest)$"),
) -> ContractTestSuite:
    """Retrieve a previously generated test suite.

    Returns 404 if no test suite has been generated for this contract.
    """
    generator = ContractTestGenerator(request.app.state.pool)
    suite = await asyncio.to_thread(generator.get_suite, contract_id, framework)
    if suite is None:
        raise ContractNotFoundError(
            detail=f"No test suite found for contract: {contract_id}"
        )
    return suite


@router.post(
    "/compliance/check/{contract_id}",
    response_model=list[ComplianceResult],
)
async def check_compliance(
    contract_id: str,
    request: Request,
    response_data: dict[str, Any] | None = None,
) -> list[ComplianceResult]:
    """Check response data against a contract's schemas.

    The ``response_data`` body should map endpoint keys to response bodies::

        {
            "GET /api/users": {"users": [...]},
            "POST /api/users": {"id": "abc", "name": "Alice"}
        }
    """
    if response_data is None:
        response_data = {}

    checker = ComplianceChecker(request.app.state.pool)
    results = await asyncio.to_thread(
        checker.check_compliance, contract_id, response_data
    )
    return results

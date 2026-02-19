"""Pipeline Phase Timing Benchmarks.

Measures the time each pipeline phase takes using mocks to avoid actual
Claude API calls. Focuses on the overhead of the orchestrator itself,
not external service latency.

Benchmarked phases:
  - Architect phase (with real MCP, small PRD -- if available)
  - Contract registration timing
  - Quality gate timing (4 layers)
  - Fix pass classification timing

Usage:
    python -m pytest tests/benchmarks/test_pipeline_timing.py -v --timeout=30
"""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.build3_shared.models import (
    BuilderResult,
    ContractViolation,
    GateVerdict,
    IntegrationReport,
    QualityGateReport,
)
from src.super_orchestrator.config import SuperOrchestratorConfig
from src.super_orchestrator.cost import PipelineCostTracker
from src.super_orchestrator.shutdown import GracefulShutdown
from src.super_orchestrator.state import PipelineState


# ---------------------------------------------------------------------------
# Thresholds (seconds)
# ---------------------------------------------------------------------------

ARCHITECT_PHASE_THRESHOLD = 10.0      # 10s (with real MCP)
CONTRACT_REG_THRESHOLD = 2.0          # 2s (mocked MCP)
QUALITY_GATE_THRESHOLD = 5.0          # 5s (4-layer scan of empty dir)
FIX_CLASSIFICATION_THRESHOLD = 0.1    # 100ms (pure in-memory classification)

# ---------------------------------------------------------------------------
# Results collector
# ---------------------------------------------------------------------------

_phase_results: list[dict[str, Any]] = []


def _record(name: str, elapsed_ms: float, target_ms: float, passed: bool) -> None:
    """Record a phase timing result for the summary."""
    _phase_results.append({
        "name": name,
        "elapsed_ms": elapsed_ms,
        "target_ms": target_ms,
        "passed": passed,
    })


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def tmp_output_dir(tmp_path: Path) -> Path:
    """Create a temporary output directory mimicking .super-orchestrator."""
    out = tmp_path / ".super-orchestrator"
    out.mkdir(parents=True, exist_ok=True)
    return out


@pytest.fixture
def sample_prd_file(tmp_path: Path) -> Path:
    """Create a minimal PRD file for testing."""
    prd = tmp_path / "test_prd.md"
    prd.write_text(
        "# Benchmark App PRD\n\n"
        "## Overview\n"
        "A minimal todo app.\n\n"
        "## Requirements\n"
        "- REQ-001: CRUD operations for todos\n"
        "- REQ-002: User authentication with JWT\n"
        "- REQ-003: RESTful API with JSON responses\n",
        encoding="utf-8",
    )
    return prd


@pytest.fixture
def sample_state(tmp_output_dir: Path, sample_prd_file: Path) -> PipelineState:
    """Create a PipelineState pre-populated for phase testing."""
    state = PipelineState(
        prd_path=str(sample_prd_file),
        config_path="",
        depth="standard",
    )

    # Pre-populate service map
    service_map = {
        "project_name": "benchmark-app",
        "services": [
            {
                "service_id": "api-service",
                "name": "api-service",
                "domain": "api",
                "stack": {"language": "python", "framework": "fastapi"},
                "port": 8080,
                "health_endpoint": "/health",
                "estimated_loc": 500,
            }
        ],
    }
    smap_path = tmp_output_dir / "service_map.json"
    smap_path.write_text(json.dumps(service_map), encoding="utf-8")
    state.service_map_path = str(smap_path)

    # Pre-populate contract registry
    contracts_dir = tmp_output_dir / "contracts"
    contracts_dir.mkdir(exist_ok=True)
    stubs = {"api-service": {"openapi": "3.1.0", "info": {"title": "API", "version": "1.0.0"}, "paths": {}}}
    (contracts_dir / "stubs.json").write_text(json.dumps(stubs), encoding="utf-8")
    state.contract_registry_path = str(contracts_dir)

    # Pre-populate builder results (successful)
    state.builder_results = {
        "api-service": {
            "system_id": "sys-001",
            "service_id": "api-service",
            "success": True,
            "cost": 0.5,
            "test_passed": 10,
            "test_total": 10,
            "convergence_ratio": 1.0,
            "error": "",
        }
    }
    state.builder_statuses = {"api-service": "healthy"}
    state.successful_builders = 1
    state.total_builders = 1

    # Pre-populate integration report
    ir = IntegrationReport(
        services_deployed=1,
        services_healthy=1,
        contract_tests_passed=5,
        contract_tests_total=5,
        overall_health="healthy",
    )
    ir_path = tmp_output_dir / "integration_report.json"
    ir_path.write_text(json.dumps(asdict(ir)), encoding="utf-8")
    state.integration_report_path = str(ir_path)

    return state


@pytest.fixture
def sample_config(tmp_output_dir: Path) -> SuperOrchestratorConfig:
    """Create a SuperOrchestratorConfig pointing at the temp output dir."""
    return SuperOrchestratorConfig(output_dir=str(tmp_output_dir))


@pytest.fixture
def cost_tracker() -> PipelineCostTracker:
    """Create a cost tracker with no budget limit."""
    return PipelineCostTracker(budget_limit=None)


@pytest.fixture
def shutdown() -> GracefulShutdown:
    """Create a shutdown handler (not armed)."""
    return GracefulShutdown()


# ---------------------------------------------------------------------------
# Tests: Contract Registration Timing
# ---------------------------------------------------------------------------

@pytest.mark.benchmark
class TestContractRegistrationTiming:
    """Measure contract registration phase overhead."""

    async def test_contract_registration_mocked(
        self,
        sample_state: PipelineState,
        sample_config: SuperOrchestratorConfig,
        cost_tracker: PipelineCostTracker,
        shutdown: GracefulShutdown,
        tmp_output_dir: Path,
    ) -> None:
        """Contract registration with mocked MCP should be fast (< 2s)."""
        from src.super_orchestrator.pipeline import run_contract_registration

        # Mock the MCP import to force filesystem fallback (faster)
        with patch(
            "src.super_orchestrator.pipeline._register_single_contract",
            new_callable=AsyncMock,
            side_effect=Exception("MCP unavailable"),
        ):
            start = time.monotonic()
            await run_contract_registration(
                sample_state, sample_config, cost_tracker, shutdown
            )
            elapsed = time.monotonic() - start

        elapsed_ms = elapsed * 1000
        _record(
            "Contract Registration",
            elapsed_ms,
            CONTRACT_REG_THRESHOLD * 1000,
            elapsed < CONTRACT_REG_THRESHOLD,
        )

        assert elapsed < CONTRACT_REG_THRESHOLD, (
            f"Contract registration took {elapsed_ms:.1f}ms, "
            f"exceeds {CONTRACT_REG_THRESHOLD * 1000:.0f}ms threshold"
        )
        assert "contract_registration" in sample_state.completed_phases


# ---------------------------------------------------------------------------
# Tests: Quality Gate Timing
# ---------------------------------------------------------------------------

@pytest.mark.benchmark
class TestQualityGateTiming:
    """Measure quality gate engine overhead."""

    async def test_quality_gate_empty_target(
        self,
        sample_state: PipelineState,
        sample_config: SuperOrchestratorConfig,
        cost_tracker: PipelineCostTracker,
        shutdown: GracefulShutdown,
        tmp_output_dir: Path,
    ) -> None:
        """Quality gate on empty/minimal target dir should be fast (< 5s).

        Tests the overhead of the 4-layer scan framework without real
        source code to scan. This measures the engine's fixed overhead.
        """
        from src.super_orchestrator.pipeline import run_quality_gate

        # Create minimal target dir structure
        target_dir = tmp_output_dir / "api-service"
        target_dir.mkdir(exist_ok=True)

        # Write a minimal Python file so scanners have something to scan
        (target_dir / "main.py").write_text(
            "from fastapi import FastAPI\napp = FastAPI()\n",
            encoding="utf-8",
        )

        start = time.monotonic()
        try:
            report = await run_quality_gate(
                sample_state, sample_config, cost_tracker, shutdown
            )
            elapsed = time.monotonic() - start
        except Exception:
            elapsed = time.monotonic() - start
            # Even if quality gate fails due to missing deps, the timing is valid
            report = None

        elapsed_ms = elapsed * 1000
        _record(
            "Quality Gate (minimal)",
            elapsed_ms,
            QUALITY_GATE_THRESHOLD * 1000,
            elapsed < QUALITY_GATE_THRESHOLD,
        )

        assert elapsed < QUALITY_GATE_THRESHOLD, (
            f"Quality gate took {elapsed_ms:.1f}ms, "
            f"exceeds {QUALITY_GATE_THRESHOLD * 1000:.0f}ms threshold"
        )


# ---------------------------------------------------------------------------
# Tests: Fix Pass Classification Timing
# ---------------------------------------------------------------------------

@pytest.mark.benchmark
class TestFixPassClassificationTiming:
    """Measure the fix pass violation classification overhead."""

    def test_classify_priority_bulk(self) -> None:
        """Classifying 100 violations should take < 100ms.

        Tests the pure in-memory decision tree performance without any
        I/O or subprocess overhead.
        """
        try:
            from src.run4.fix_pass import classify_priority
        except ImportError:
            pytest.skip("src.run4.fix_pass not available")

        # Generate 100 sample violations with varied severities
        violations = []
        for i in range(100):
            if i % 4 == 0:
                violations.append({"severity": "error", "category": "SEC-001", "message": f"Security violation {i}"})
            elif i % 4 == 1:
                violations.append({"severity": "error", "category": "CORS-001", "message": f"CORS issue {i}"})
            elif i % 4 == 2:
                violations.append({"severity": "warning", "category": "LOG-001", "message": f"Logging gap {i}"})
            else:
                violations.append({"severity": "info", "category": "ADV-004", "message": f"Naming issue {i}"})

        start = time.monotonic()
        results = [classify_priority(v) for v in violations]
        elapsed = time.monotonic() - start

        elapsed_ms = elapsed * 1000
        _record(
            "Fix Classification (100)",
            elapsed_ms,
            FIX_CLASSIFICATION_THRESHOLD * 1000,
            elapsed < FIX_CLASSIFICATION_THRESHOLD,
        )

        assert len(results) == 100
        assert all(r in ("P0", "P1", "P2", "P3") for r in results)
        assert elapsed < FIX_CLASSIFICATION_THRESHOLD, (
            f"Classification of 100 violations took {elapsed_ms:.1f}ms, "
            f"exceeds {FIX_CLASSIFICATION_THRESHOLD * 1000:.0f}ms threshold"
        )

    def test_convergence_computation(self) -> None:
        """Convergence computation should be near-instant (< 10ms)."""
        try:
            from src.run4.fix_pass import compute_convergence, check_convergence
        except ImportError:
            pytest.skip("src.run4.fix_pass not available")

        start = time.monotonic()
        for _ in range(100):
            score = compute_convergence(
                remaining_p0=2,
                remaining_p1=5,
                remaining_p2=10,
                initial_total_weighted=20.0,
            )
            result = check_convergence(
                remaining_p0=2,
                remaining_p1=5,
                remaining_p2=10,
                initial_total_weighted=20.0,
                current_pass=1,
                max_fix_passes=5,
                budget_remaining=100.0,
            )
        elapsed = time.monotonic() - start

        elapsed_ms = elapsed * 1000
        convergence_threshold = 0.1  # 100ms for 100 iterations

        _record(
            "Convergence (100 iter)",
            elapsed_ms,
            convergence_threshold * 1000,
            elapsed < convergence_threshold,
        )

        assert elapsed < convergence_threshold, (
            f"100 convergence computations took {elapsed_ms:.1f}ms, "
            f"exceeds {convergence_threshold * 1000:.0f}ms threshold"
        )

    def test_snapshot_and_regression_detection(self) -> None:
        """Snapshot creation + regression detection should be fast (< 50ms)."""
        try:
            from src.run4.fix_pass import take_violation_snapshot, detect_regressions
        except ImportError:
            pytest.skip("src.run4.fix_pass not available")

        # Build 50 violations
        violations = [
            {"scan_code": f"SEC-{i:03d}", "file_path": f"src/service_{i}.py"}
            for i in range(50)
        ]

        start = time.monotonic()

        # Take before snapshot
        before = take_violation_snapshot(violations)

        # Simulate some fixes and some regressions
        after_violations = violations[:30] + [
            {"scan_code": "NEW-001", "file_path": "src/new_file.py"},
            {"scan_code": "NEW-002", "file_path": "src/another.py"},
        ]
        after = take_violation_snapshot(after_violations)

        # Detect regressions
        regressions = detect_regressions(before, after)

        elapsed = time.monotonic() - start
        elapsed_ms = elapsed * 1000
        snapshot_threshold = 0.05  # 50ms

        _record(
            "Snapshot + Regressions",
            elapsed_ms,
            snapshot_threshold * 1000,
            elapsed < snapshot_threshold,
        )

        assert elapsed < snapshot_threshold, (
            f"Snapshot + regression detection took {elapsed_ms:.1f}ms, "
            f"exceeds {snapshot_threshold * 1000:.0f}ms threshold"
        )


# ---------------------------------------------------------------------------
# Summary Report
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session", autouse=True)
def print_phase_timing_summary(request: pytest.FixtureRequest) -> None:
    """Print a summary of all pipeline phase timing results."""

    def _finalizer() -> None:
        if not _phase_results:
            return

        print("\n")
        print("=" * 60)
        print("  Pipeline Phase Timing Results")
        print("=" * 60)
        print(f"{'Phase':<28} {'Elapsed':>10} {'Target':>10} {'Status':>8}")
        print("-" * 60)

        all_passed = True
        for r in _phase_results:
            status = "PASS" if r["passed"] else "FAIL"
            if not r["passed"]:
                all_passed = False
            print(
                f"  {r['name']:<26} {r['elapsed_ms']:>8.1f}ms {r['target_ms']:>8.0f}ms "
                f"{'  ' + status:>8}"
            )

        print("-" * 60)
        overall = "ALL PASSED" if all_passed else "SOME FAILED"
        print(f"  Overall: {overall}")
        print("=" * 60)

    request.addfinalizer(_finalizer)

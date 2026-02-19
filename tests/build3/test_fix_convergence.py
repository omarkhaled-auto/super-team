"""Tests for fix pass convergence logic.

Phase 4 (Stress Test & Hardening) - Task 4.6: Fix Convergence Test

Verifies:
  - Priority classification (P0-P3) for various violation types.
  - Convergence scoring via compute_convergence / check_convergence.
  - Regression detection via detect_regressions.
  - Full fix loop integration via run_fix_loop.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from src.run4.fix_pass import (
    ConvergenceResult,
    FixPassMetrics,
    FixPassResult,
    check_convergence,
    classify_priority,
    compute_convergence,
    compute_fix_pass_metrics,
    detect_regressions,
    run_fix_loop,
    take_violation_snapshot,
)


# ---------------------------------------------------------------------------
# 4.6a -- Priority classification (P0-P3)
# ---------------------------------------------------------------------------


class TestClassifyPriority:
    """classify_priority should map violations to P0/P1/P2/P3."""

    def test_p0_missing_health_endpoint(self) -> None:
        """A missing /health endpoint is a startup failure => P0."""
        violation = {
            "severity": "critical",
            "category": "health",
            "message": "missing /health endpoint",
        }
        assert classify_priority(violation) == "P0"

    def test_p0_container_crash(self) -> None:
        """Container crash keyword in the message => P0."""
        violation = {
            "severity": "error",
            "category": "infrastructure",
            "message": "container crash on startup",
        }
        assert classify_priority(violation) == "P0"

    def test_p0_build_failure(self) -> None:
        """build fail keyword => P0."""
        violation = {
            "severity": "warning",
            "category": "build",
            "message": "build fail: missing dependency",
        }
        assert classify_priority(violation) == "P0"

    def test_p0_fatal_severity(self) -> None:
        """severity=fatal => P0 regardless of message."""
        violation = {
            "severity": "fatal",
            "category": "general",
            "message": "something bad",
        }
        assert classify_priority(violation) == "P0"

    def test_p0_blocker_severity(self) -> None:
        """severity=blocker => P0."""
        violation = {
            "severity": "blocker",
            "category": "unknown",
            "message": "blocks deployment",
        }
        assert classify_priority(violation) == "P0"

    def test_p0_syntax_error(self) -> None:
        """syntax error in message => P0."""
        violation = {
            "severity": "warning",
            "category": "code",
            "message": "syntax error in main.py line 42",
        }
        assert classify_priority(violation) == "P0"

    def test_p1_wrong_response_schema(self) -> None:
        """severity=error falls to P1 by default."""
        violation = {
            "severity": "error",
            "category": "response",
            "message": "wrong response schema for GET /users",
        }
        assert classify_priority(violation) == "P1"

    def test_p1_contract_violation(self) -> None:
        """category=contract => P1."""
        violation = {
            "severity": "info",
            "category": "contract",
            "message": "contract violation detected",
        }
        assert classify_priority(violation) == "P1"

    def test_p1_api_error_keyword(self) -> None:
        """'api error' keyword => P1."""
        violation = {
            "severity": "info",
            "category": "general",
            "message": "api error on POST /orders",
        }
        assert classify_priority(violation) == "P1"

    def test_p1_security_category(self) -> None:
        """category=security => P1."""
        violation = {
            "severity": "info",
            "category": "security",
            "message": "JWT token not validated",
        }
        assert classify_priority(violation) == "P1"

    def test_p2_missing_auth_middleware(self) -> None:
        """severity=warning => P2."""
        violation = {
            "severity": "warning",
            "category": "middleware",
            "message": "missing auth middleware on /admin routes",
        }
        assert classify_priority(violation) == "P2"

    def test_p2_documentation_category(self) -> None:
        """category=documentation => P2."""
        violation = {
            "severity": "info",
            "category": "documentation",
            "message": "missing API docs for POST /items",
        }
        assert classify_priority(violation) == "P2"

    def test_p2_coverage_keyword(self) -> None:
        """'coverage' keyword in message => P2."""
        violation = {
            "severity": "info",
            "category": "general",
            "message": "test coverage below 80%",
        }
        assert classify_priority(violation) == "P2"

    def test_p3_print_instead_of_logger(self) -> None:
        """severity=style => P3 (cosmetic)."""
        violation = {
            "severity": "style",
            "category": "code",
            "message": "print() instead of logger",
        }
        assert classify_priority(violation) == "P3"

    def test_p3_naming_convention(self) -> None:
        """category=naming => P3."""
        violation = {
            "severity": "info",
            "category": "naming",
            "message": "variable 'x' violates naming convention",
        }
        assert classify_priority(violation) == "P3"

    def test_p3_hint_severity(self) -> None:
        """severity=hint => P3."""
        violation = {
            "severity": "hint",
            "category": "general",
            "message": "consider using f-strings",
        }
        assert classify_priority(violation) == "P3"

    def test_default_unknown_maps_to_p2(self) -> None:
        """Completely unknown violation defaults to P2."""
        violation = {
            "severity": "unknown-sev",
            "category": "unknown-cat",
            "message": "completely unknown violation type",
        }
        assert classify_priority(violation) == "P2"


# ---------------------------------------------------------------------------
# 4.6b -- Convergence scoring
# ---------------------------------------------------------------------------


class TestConvergenceScoring:
    """compute_convergence and check_convergence behavior."""

    def test_convergence_score_increases_when_violations_decrease(self) -> None:
        """Fewer remaining violations => higher convergence score."""
        initial_weighted = 10 * 0.4 + 5 * 0.3 + 3 * 0.1  # 5.8

        # Before any fixing.
        score_before = compute_convergence(10, 5, 3, initial_weighted)

        # After fixing half the P0s.
        score_after = compute_convergence(5, 5, 3, initial_weighted)

        assert score_after > score_before

    def test_convergence_all_fixed(self) -> None:
        """When all violations are fixed, convergence = 1.0."""
        initial_weighted = 5 * 0.4 + 3 * 0.3 + 2 * 0.1  # 3.1
        score = compute_convergence(0, 0, 0, initial_weighted)
        assert score == pytest.approx(1.0)

    def test_convergence_no_change(self) -> None:
        """When nothing is fixed, convergence = 0.0."""
        p0, p1, p2 = 5, 3, 2
        initial_weighted = p0 * 0.4 + p1 * 0.3 + p2 * 0.1
        score = compute_convergence(p0, p1, p2, initial_weighted)
        assert score == pytest.approx(0.0)

    def test_convergence_clamped_0_to_1(self) -> None:
        """Convergence is clamped between 0.0 and 1.0."""
        # Edge case: initial_weighted=0 should yield 1.0.
        score = compute_convergence(0, 0, 0, 0.0)
        assert score == pytest.approx(1.0)
        assert 0.0 <= score <= 1.0

    def test_hard_stop_when_p0_is_zero(self) -> None:
        """Hard stop triggers when P0=0 AND P1=0."""
        result = check_convergence(
            remaining_p0=0,
            remaining_p1=0,
            remaining_p2=5,
            initial_total_weighted=10.0,
            current_pass=1,
            max_fix_passes=5,
        )
        assert result.should_stop is True
        assert result.is_hard_stop is True
        assert "P0" in result.reason and "P1" in result.reason

    def test_no_hard_stop_when_p0_nonzero(self) -> None:
        """No hard stop when P0 > 0."""
        result = check_convergence(
            remaining_p0=1,
            remaining_p1=0,
            remaining_p2=0,
            initial_total_weighted=10.0,
            current_pass=1,
            max_fix_passes=5,
        )
        # Should not stop just because P1 is zero but P0 is still there.
        # It may stop for other reasons (convergence threshold) but not the P0/P1 check.
        if result.should_stop:
            assert "P0" not in result.reason or "P1" not in result.reason or result.is_soft_convergence

    def test_soft_stop_when_convergence_above_threshold(self) -> None:
        """Soft stop triggers when convergence >= 0.85."""
        # Remaining is very small relative to initial.
        # initial_weighted=10.0, remaining = 1*0.4 + 0*0.3 + 0*0.1 = 0.4
        # convergence = 1.0 - 0.4/10.0 = 0.96 >= 0.85
        result = check_convergence(
            remaining_p0=1,
            remaining_p1=0,
            remaining_p2=0,
            initial_total_weighted=10.0,
            current_pass=1,
            max_fix_passes=5,
        )
        assert result.should_stop is True
        assert result.is_soft_convergence is True
        assert result.convergence_score >= 0.85

    def test_hard_stop_max_passes_reached(self) -> None:
        """Hard stop when current_pass >= max_fix_passes."""
        result = check_convergence(
            remaining_p0=5,
            remaining_p1=3,
            remaining_p2=2,
            initial_total_weighted=10.0,
            current_pass=5,
            max_fix_passes=5,
        )
        assert result.should_stop is True
        assert result.is_hard_stop is True
        assert "max" in result.reason.lower() or "Max" in result.reason

    def test_hard_stop_budget_exhausted(self) -> None:
        """Hard stop when budget_remaining <= 0."""
        result = check_convergence(
            remaining_p0=5,
            remaining_p1=3,
            remaining_p2=2,
            initial_total_weighted=10.0,
            current_pass=1,
            max_fix_passes=5,
            budget_remaining=0.0,
        )
        assert result.should_stop is True
        assert result.is_hard_stop is True
        assert "budget" in result.reason.lower() or "Budget" in result.reason

    def test_hard_stop_low_effectiveness(self) -> None:
        """Hard stop when fix_effectiveness < floor (after first pass)."""
        result = check_convergence(
            remaining_p0=5,
            remaining_p1=3,
            remaining_p2=2,
            initial_total_weighted=10.0,
            current_pass=2,
            max_fix_passes=5,
            fix_effectiveness=0.10,
            fix_effectiveness_floor=0.30,
        )
        assert result.should_stop is True
        assert result.is_hard_stop is True
        assert "effectiveness" in result.reason.lower()

    def test_hard_stop_high_regression_rate(self) -> None:
        """Hard stop when regression_rate > ceiling."""
        result = check_convergence(
            remaining_p0=5,
            remaining_p1=3,
            remaining_p2=2,
            initial_total_weighted=10.0,
            current_pass=1,
            max_fix_passes=5,
            regression_rate=0.50,
            regression_rate_ceiling=0.25,
        )
        assert result.should_stop is True
        assert result.is_hard_stop is True
        assert "regression" in result.reason.lower() or "Regression" in result.reason

    def test_continue_when_not_converged(self) -> None:
        """No stop when convergence is below threshold and no hard stop."""
        # initial_weighted=10.0
        # remaining = 5*0.4 + 3*0.3 + 2*0.1 = 3.1
        # convergence = 1.0 - 3.1/10.0 = 0.69 < 0.85
        result = check_convergence(
            remaining_p0=5,
            remaining_p1=3,
            remaining_p2=2,
            initial_total_weighted=10.0,
            current_pass=1,
            max_fix_passes=5,
            budget_remaining=100.0,
        )
        assert result.should_stop is False
        assert result.convergence_score == pytest.approx(0.69)


# ---------------------------------------------------------------------------
# 4.6c -- Regression detection
# ---------------------------------------------------------------------------


class TestRegressionDetection:
    """detect_regressions should find new or reappeared violations."""

    def test_no_regressions(self) -> None:
        """When after is subset of before, no regressions."""
        before = {"SEC-001": ["auth.py"], "LOG-001": ["main.py"]}
        after = {"SEC-001": ["auth.py"]}
        regressions = detect_regressions(before, after)
        assert len(regressions) == 0

    def test_new_violation_detected(self) -> None:
        """A completely new scan_code in 'after' is a regression."""
        before = {"SEC-001": ["auth.py"]}
        after = {"SEC-001": ["auth.py"], "CORS-001": ["server.py"]}
        regressions = detect_regressions(before, after)
        assert len(regressions) == 1
        assert regressions[0]["scan_code"] == "CORS-001"
        assert regressions[0]["type"] == "new"

    def test_reappeared_violation(self) -> None:
        """A file_path that was removed then reappears is a regression."""
        before = {"SEC-001": ["auth.py"]}
        after = {"SEC-001": ["auth.py", "new_auth.py"]}
        regressions = detect_regressions(before, after)
        assert len(regressions) == 1
        assert regressions[0]["scan_code"] == "SEC-001"
        assert regressions[0]["file_path"] == "new_auth.py"
        assert regressions[0]["type"] == "reappeared"

    def test_multiple_regressions(self) -> None:
        """Multiple new violations across different scan codes."""
        before = {"SEC-001": ["auth.py"]}
        after = {
            "SEC-001": ["auth.py", "admin.py"],
            "LOG-001": ["server.py"],
            "CORS-001": ["api.py"],
        }
        regressions = detect_regressions(before, after)
        assert len(regressions) == 3  # admin.py + server.py + api.py

    def test_regression_count_reported(self) -> None:
        """detect_regressions returns the correct count."""
        before = {}
        after = {"SEC-001": ["a.py", "b.py"], "LOG-001": ["c.py"]}
        regressions = detect_regressions(before, after)
        assert len(regressions) == 3

    def test_empty_snapshots_no_regression(self) -> None:
        """Both empty snapshots => no regressions."""
        regressions = detect_regressions({}, {})
        assert len(regressions) == 0


# ---------------------------------------------------------------------------
# Violation snapshots (helper for regression detection)
# ---------------------------------------------------------------------------


class TestViolationSnapshots:
    """take_violation_snapshot normalises various input formats."""

    def test_flat_list_of_dicts(self) -> None:
        """Standard flat list of dicts with scan_code/file_path."""
        items = [
            {"scan_code": "SEC-001", "file_path": "auth.py"},
            {"scan_code": "SEC-001", "file_path": "admin.py"},
            {"scan_code": "LOG-001", "file_path": "main.py"},
        ]
        snap = take_violation_snapshot(items)
        assert "SEC-001" in snap
        assert len(snap["SEC-001"]) == 2
        assert "LOG-001" in snap
        assert len(snap["LOG-001"]) == 1

    def test_pre_grouped_dict(self) -> None:
        """Already-grouped dict passthrough."""
        grouped = {"SEC-001": ["auth.py"], "LOG-001": ["main.py"]}
        snap = take_violation_snapshot(grouped)
        assert snap == grouped

    def test_dict_with_violations_key(self) -> None:
        """Dict wrapping a 'violations' list."""
        data = {
            "violations": [
                {"scan_code": "CORS-001", "file_path": "server.py"},
            ]
        }
        snap = take_violation_snapshot(data)
        assert "CORS-001" in snap


# ---------------------------------------------------------------------------
# 4.6d -- Full fix loop integration
# ---------------------------------------------------------------------------


@dataclass
class MockFinding:
    """Minimal mock for a Finding object used by run_fix_loop."""

    finding_id: str = ""
    system: str = ""
    priority: str = ""
    resolution: str = "OPEN"
    component: str = ""
    evidence: str = ""
    recommendation: str = ""
    fix_pass_number: int = 0


@dataclass
class MockRun4State:
    """Minimal mock for Run4State used by run_fix_loop."""

    findings: list[Any] = field(default_factory=list)
    aggregate_score: float = 0.0
    total_cost: float = 0.0


@dataclass
class MockRun4Config:
    """Minimal mock for Run4Config used by run_fix_loop."""

    max_fix_passes: int = 5
    max_budget_usd: float = 100.0
    fix_effectiveness_floor: float = 0.30
    regression_rate_ceiling: float = 0.25
    build1_project_root: str | None = None
    build2_project_root: str | None = None
    build3_project_root: str | None = None
    builder_timeout_s: int = 60


class TestFullFixLoopIntegration:
    """run_fix_loop drives the convergence loop until stop."""

    @pytest.mark.asyncio
    async def test_convergence_reached_within_max_iterations(self) -> None:
        """Simulate decreasing violations => convergence within max passes."""
        # Start with 5 P0 and 3 P1 findings.
        findings = [
            MockFinding(finding_id=f"F-P0-{i}", system="build", priority="P0")
            for i in range(5)
        ] + [
            MockFinding(finding_id=f"F-P1-{i}", system="api", priority="P1")
            for i in range(3)
        ]

        state = MockRun4State(findings=findings, aggregate_score=50.0)
        config = MockRun4Config(max_fix_passes=5)

        call_count = 0

        # Each call to the fix function resolves some findings.
        async def mock_fix_fn(cwd: Any, violations: Any) -> None:
            nonlocal call_count
            call_count += 1
            # Resolve half the OPEN findings each pass.
            open_findings = [f for f in state.findings if f.resolution == "OPEN"]
            for i, f in enumerate(open_findings):
                if i < len(open_findings) // 2 + 1:
                    f.resolution = "FIXED"
                    f.fix_pass_number = call_count

        with patch("src.run4.builder.feed_violations_to_builder", new_callable=AsyncMock):
            results = await run_fix_loop(
                state=state,
                config=config,
                fix_fn=mock_fix_fn,
            )

        assert len(results) >= 1
        # The last result should have should_stop=True (convergence reached).
        last = results[-1]
        assert last.convergence.should_stop is True

    @pytest.mark.asyncio
    async def test_max_passes_stops_loop(self) -> None:
        """Loop stops at max_fix_passes even if not converged."""
        # Findings that never get fixed.
        findings = [
            MockFinding(finding_id=f"F-{i}", system="build", priority="P0")
            for i in range(10)
        ]

        state = MockRun4State(findings=findings, aggregate_score=20.0)
        # Disable the effectiveness floor so only the max_fix_passes
        # hard stop triggers (otherwise 0% effectiveness triggers first).
        config = MockRun4Config(
            max_fix_passes=3,
            fix_effectiveness_floor=0.0,
        )

        async def noop_fix(cwd: Any, violations: Any) -> None:
            pass  # No fixing happens.

        with patch("src.run4.builder.feed_violations_to_builder", new_callable=AsyncMock):
            results = await run_fix_loop(
                state=state,
                config=config,
                fix_fn=noop_fix,
            )

        assert len(results) == 3
        last = results[-1]
        assert last.convergence.should_stop is True
        assert last.convergence.is_hard_stop is True

    @pytest.mark.asyncio
    async def test_fix_pass_artifacts_populated(self) -> None:
        """Each FixPassResult contains steps_completed and metrics."""
        findings = [
            MockFinding(finding_id="F-1", system="api", priority="P1"),
            MockFinding(finding_id="F-2", system="api", priority="P2"),
        ]

        state = MockRun4State(findings=findings, aggregate_score=60.0)
        config = MockRun4Config(max_fix_passes=1)

        async def mark_fixed(cwd: Any, violations: Any) -> None:
            for f in state.findings:
                f.resolution = "FIXED"
                f.fix_pass_number = 1

        with patch("src.run4.builder.feed_violations_to_builder", new_callable=AsyncMock):
            results = await run_fix_loop(
                state=state,
                config=config,
                fix_fn=mark_fixed,
            )

        assert len(results) == 1
        result = results[0]
        assert "DISCOVER" in result.steps_completed
        assert "CLASSIFY" in result.steps_completed
        assert "GENERATE" in result.steps_completed
        assert "APPLY" in result.steps_completed
        assert "VERIFY" in result.steps_completed
        assert "REGRESS" in result.steps_completed
        assert result.status == "completed"
        assert isinstance(result.metrics, FixPassMetrics)
        assert isinstance(result.convergence, ConvergenceResult)

    @pytest.mark.asyncio
    async def test_scan_fn_used_for_initial_snapshot(self) -> None:
        """If scan_fn is provided, it is used for the initial snapshot."""
        findings = [
            MockFinding(finding_id="F-1", system="test", priority="P0"),
        ]
        state = MockRun4State(findings=findings)
        config = MockRun4Config(max_fix_passes=1)

        scan_called = False

        def my_scan_fn() -> list[dict]:
            nonlocal scan_called
            scan_called = True
            return [{"scan_code": "TEST-001", "file_path": "test.py"}]

        async def mark_done(cwd: Any, violations: Any) -> None:
            for f in state.findings:
                f.resolution = "FIXED"

        with patch("src.run4.builder.feed_violations_to_builder", new_callable=AsyncMock):
            await run_fix_loop(
                state=state,
                config=config,
                scan_fn=my_scan_fn,
                fix_fn=mark_done,
            )

        assert scan_called is True


# ---------------------------------------------------------------------------
# Fix pass metrics computation
# ---------------------------------------------------------------------------


class TestFixPassMetrics:
    """compute_fix_pass_metrics returns correct effectiveness values."""

    def test_all_fixed_effectiveness(self) -> None:
        """100% effectiveness when all open findings are fixed."""
        before = [{"resolution": "OPEN"}] * 5
        after = [{"resolution": "FIXED"}] * 5
        metrics = compute_fix_pass_metrics(before, after, regressions=[])
        assert metrics.fix_effectiveness == pytest.approx(1.0)

    def test_none_fixed_effectiveness(self) -> None:
        """0% effectiveness when nothing is fixed."""
        before = [{"resolution": "OPEN"}] * 5
        after = [{"resolution": "OPEN"}] * 5
        metrics = compute_fix_pass_metrics(before, after, regressions=[])
        assert metrics.fix_effectiveness == pytest.approx(0.0)

    def test_regression_rate_computation(self) -> None:
        """Regression rate = regressions / total_after."""
        before = [{"resolution": "OPEN"}] * 4
        after = [{"resolution": "OPEN"}] * 4
        regs = [{"scan_code": "X", "file_path": "a.py", "type": "new"}]
        metrics = compute_fix_pass_metrics(before, after, regressions=regs)
        assert metrics.regression_rate == pytest.approx(1.0 / 4.0)
        assert metrics.regression_count == 1

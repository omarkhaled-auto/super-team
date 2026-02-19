"""Tests for Milestone 5: Fix Pass Loop.

Covers:
    TEST-014: Convergence formula values
    TEST-015: Hard stop terminating fix loop
    Plus: classify_priority, FixPassResult, execute_fix_pass, metrics,
          take_violation_snapshot, detect_regressions with specified schema.
"""

from __future__ import annotations

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
    take_violation_snapshot,
)
from src.run4.state import Finding, Run4State


# ---------------------------------------------------------------------------
# classify_priority tests
# ---------------------------------------------------------------------------


class TestClassifyPriority:
    """Test the P0-P3 priority decision tree."""

    def test_p0_critical_severity(self) -> None:
        result = classify_priority({"severity": "critical"})
        assert result == "P0"

    def test_p0_build_failure_message(self) -> None:
        result = classify_priority({"message": "container crash on startup"})
        assert result == "P0"

    def test_p0_fatal_severity(self) -> None:
        result = classify_priority({"severity": "fatal"})
        assert result == "P0"

    def test_p0_infrastructure_error(self) -> None:
        result = classify_priority({"category": "infrastructure", "severity": "error"})
        assert result == "P0"

    def test_p1_error_severity(self) -> None:
        result = classify_priority({"severity": "error"})
        assert result == "P1"

    def test_p1_test_fail_message(self) -> None:
        result = classify_priority({"message": "test fail in auth module"})
        assert result == "P1"

    def test_p1_contract_category(self) -> None:
        result = classify_priority({"category": "contract"})
        assert result == "P1"

    def test_p2_warning_severity(self) -> None:
        result = classify_priority({"severity": "warning"})
        assert result == "P2"

    def test_p2_documentation_category(self) -> None:
        result = classify_priority({"category": "documentation"})
        assert result == "P2"

    def test_p3_info_severity(self) -> None:
        result = classify_priority({"severity": "info"})
        assert result == "P3"

    def test_p3_style_category(self) -> None:
        result = classify_priority({"category": "style"})
        assert result == "P3"

    def test_default_unknown(self) -> None:
        result = classify_priority({})
        assert result == "P2"


# ---------------------------------------------------------------------------
# take_violation_snapshot tests
# ---------------------------------------------------------------------------


class TestTakeViolationSnapshot:
    """Test violation snapshot creation."""

    def test_from_flat_list(self) -> None:
        scan_results = [
            {"scan_code": "SEC-001", "file_path": "src/a.py"},
            {"scan_code": "SEC-001", "file_path": "src/b.py"},
            {"scan_code": "LINT-002", "file_path": "src/c.py"},
        ]
        snapshot = take_violation_snapshot(scan_results)
        assert "SEC-001" in snapshot
        assert len(snapshot["SEC-001"]) == 2
        assert "LINT-002" in snapshot

    def test_from_pre_grouped_dict(self) -> None:
        scan_results = {
            "SEC-001": ["src/a.py", "src/b.py"],
            "LINT-002": ["src/c.py"],
        }
        snapshot = take_violation_snapshot(scan_results)
        assert snapshot["SEC-001"] == ["src/a.py", "src/b.py"]

    def test_from_violations_key(self) -> None:
        scan_results = {
            "violations": [
                {"scan_code": "SEC-001", "file_path": "src/a.py"},
            ]
        }
        snapshot = take_violation_snapshot(scan_results)
        assert "SEC-001" in snapshot

    def test_from_findings_list(self) -> None:
        """Test with Finding dataclass instances."""
        findings = [
            Finding(finding_id="F-001", system="Build 1", resolution="OPEN"),
            Finding(finding_id="F-002", system="Build 1", resolution="OPEN"),
            Finding(finding_id="F-003", system="Build 2", resolution="FIXED"),
        ]
        snapshot = take_violation_snapshot(findings)
        assert "Build 1" in snapshot
        assert len(snapshot["Build 1"]) == 2
        # FIXED findings are excluded
        assert "Build 2" not in snapshot


# ---------------------------------------------------------------------------
# detect_regressions tests
# ---------------------------------------------------------------------------


class TestDetectRegressions:
    """Test regression detection with specified return schema."""

    def test_no_regressions(self) -> None:
        before = {"SEC-001": ["src/a.py"]}
        after = {"SEC-001": ["src/a.py"]}
        result = detect_regressions(before, after)
        assert result == []

    def test_new_regression(self) -> None:
        before = {}
        after = {"SEC-001": ["src/a.py"]}
        result = detect_regressions(before, after)
        assert len(result) == 1
        assert result[0]["scan_code"] == "SEC-001"
        assert result[0]["file_path"] == "src/a.py"
        assert result[0]["type"] == "new"

    def test_reappeared_regression(self) -> None:
        before = {"SEC-001": ["src/a.py"]}
        after = {"SEC-001": ["src/a.py", "src/b.py"]}
        result = detect_regressions(before, after)
        assert len(result) == 1
        assert result[0]["scan_code"] == "SEC-001"
        assert result[0]["file_path"] == "src/b.py"
        assert result[0]["type"] == "reappeared"

    def test_return_schema_has_required_keys(self) -> None:
        before = {}
        after = {"SEC-001": ["src/a.py"]}
        result = detect_regressions(before, after)
        assert len(result) == 1
        entry = result[0]
        assert "scan_code" in entry
        assert "file_path" in entry
        assert "type" in entry
        assert entry["type"] in ("new", "reappeared")


# ---------------------------------------------------------------------------
# FixPassMetrics tests
# ---------------------------------------------------------------------------


class TestFixPassMetrics:
    """Test fix pass metrics computation."""

    def test_metrics_all_fixed(self) -> None:
        before = [Finding(resolution="OPEN"), Finding(resolution="OPEN")]
        after = [Finding(resolution="FIXED"), Finding(resolution="FIXED")]
        metrics = compute_fix_pass_metrics(before, after, regressions=[])
        assert metrics.fix_effectiveness == 1.0
        assert metrics.regression_rate == 0.0
        assert metrics.fixed_count == 2

    def test_metrics_with_regressions(self) -> None:
        before = [Finding(resolution="OPEN")]
        after = [Finding(resolution="OPEN"), Finding(resolution="OPEN")]
        regressions = [{"scan_code": "X", "file_path": "y", "type": "new"}]
        metrics = compute_fix_pass_metrics(before, after, regressions)
        assert metrics.regression_rate > 0.0
        assert metrics.regression_count == 1
        assert metrics.new_defect_count == 1

    def test_metrics_score_delta(self) -> None:
        before = [Finding(resolution="OPEN")]
        after = [Finding(resolution="FIXED")]
        metrics = compute_fix_pass_metrics(
            before, after, regressions=[], score_before=50.0, score_after=75.0
        )
        assert metrics.score_delta == 25.0

    def test_metrics_empty_before(self) -> None:
        metrics = compute_fix_pass_metrics([], [], regressions=[])
        assert metrics.fix_effectiveness == 0.0
        assert metrics.regression_rate == 0.0


# ---------------------------------------------------------------------------
# TEST-014: Convergence formula values
# ---------------------------------------------------------------------------


class TestConvergenceFormula:
    """TEST-014: Verify convergence formula with known inputs."""

    def test_all_resolved(self) -> None:
        """All findings resolved => convergence = 1.0."""
        score = compute_convergence(
            remaining_p0=0,
            remaining_p1=0,
            remaining_p2=0,
            initial_total_weighted=10.0,
        )
        assert score == 1.0

    def test_none_resolved(self) -> None:
        """Nothing resolved => convergence = 0.0 (all weight remaining)."""
        # initial: 5 P0 (5*0.4=2.0) + 5 P1 (5*0.3=1.5) + 5 P2 (5*0.1=0.5) = 4.0
        score = compute_convergence(
            remaining_p0=5,
            remaining_p1=5,
            remaining_p2=5,
            initial_total_weighted=4.0,
        )
        assert score == 0.0

    def test_partial_resolution(self) -> None:
        """Partial resolution => score between 0 and 1."""
        # initial weighted = 3*0.4 + 5*0.3 + 10*0.1 = 1.2 + 1.5 + 1.0 = 3.7
        # remaining = 1*0.4 + 2*0.3 + 5*0.1 = 0.4 + 0.6 + 0.5 = 1.5
        # convergence = 1.0 - 1.5/3.7 = 1.0 - 0.4054 = 0.5946
        score = compute_convergence(
            remaining_p0=1,
            remaining_p1=2,
            remaining_p2=5,
            initial_total_weighted=3.7,
        )
        assert abs(score - 0.5946) < 0.001

    def test_above_threshold(self) -> None:
        """When convergence >= 0.85, soft convergence triggers."""
        # initial_weighted = 10*0.4 + 10*0.3 + 10*0.1 = 8.0
        # remaining = 0*0.4 + 1*0.3 + 1*0.1 = 0.4
        # convergence = 1.0 - 0.4/8.0 = 0.95
        score = compute_convergence(
            remaining_p0=0,
            remaining_p1=1,
            remaining_p2=1,
            initial_total_weighted=8.0,
        )
        assert score >= 0.85
        assert abs(score - 0.95) < 0.001

    def test_zero_initial_weight(self) -> None:
        """Zero initial weight => convergence = 1.0 (nothing to fix)."""
        score = compute_convergence(0, 0, 0, 0.0)
        assert score == 1.0

    def test_formula_exact_values(self) -> None:
        """Verify exact formula: 1.0 - (p0*0.4 + p1*0.3 + p2*0.1) / initial."""
        remaining_p0 = 2
        remaining_p1 = 3
        remaining_p2 = 4
        initial = 5.0
        expected = 1.0 - (2 * 0.4 + 3 * 0.3 + 4 * 0.1) / 5.0
        score = compute_convergence(remaining_p0, remaining_p1, remaining_p2, initial)
        assert abs(score - expected) < 1e-10


# ---------------------------------------------------------------------------
# TEST-015: Hard stop terminating fix loop
# ---------------------------------------------------------------------------


class TestHardStopTermination:
    """TEST-015: Verify hard stop triggers terminate the fix loop."""

    def test_hard_stop_p0_p1_resolved(self) -> None:
        """Hard stop: P0==0 AND P1==0."""
        result = check_convergence(
            remaining_p0=0,
            remaining_p1=0,
            remaining_p2=5,
            initial_total_weighted=10.0,
            current_pass=2,
        )
        assert result.should_stop is True
        assert result.is_hard_stop is True
        assert "P0 and P1" in result.reason

    def test_hard_stop_max_passes(self) -> None:
        """Hard stop: current_pass >= max_fix_passes."""
        result = check_convergence(
            remaining_p0=1,
            remaining_p1=1,
            remaining_p2=0,
            initial_total_weighted=10.0,
            current_pass=5,
            max_fix_passes=5,
        )
        assert result.should_stop is True
        assert result.is_hard_stop is True
        assert "Max fix passes" in result.reason

    def test_hard_stop_budget_exhausted(self) -> None:
        """Hard stop: budget_remaining <= 0."""
        result = check_convergence(
            remaining_p0=1,
            remaining_p1=1,
            remaining_p2=0,
            initial_total_weighted=10.0,
            current_pass=2,
            budget_remaining=0.0,
        )
        assert result.should_stop is True
        assert result.is_hard_stop is True
        assert "Budget" in result.reason

    def test_hard_stop_effectiveness_below_floor(self) -> None:
        """Hard stop: fix_effectiveness < 30%."""
        result = check_convergence(
            remaining_p0=3,
            remaining_p1=3,
            remaining_p2=0,
            initial_total_weighted=10.0,
            current_pass=3,  # > 1 so effectiveness check applies
            fix_effectiveness=0.10,
            fix_effectiveness_floor=0.30,
        )
        assert result.should_stop is True
        assert result.is_hard_stop is True
        assert "effectiveness" in result.reason.lower()

    def test_hard_stop_regression_above_ceiling(self) -> None:
        """Hard stop: regression_rate > 25%."""
        result = check_convergence(
            remaining_p0=1,
            remaining_p1=1,
            remaining_p2=0,
            initial_total_weighted=10.0,
            current_pass=2,
            regression_rate=0.30,
            regression_rate_ceiling=0.25,
        )
        assert result.should_stop is True
        assert result.is_hard_stop is True
        assert "regression" in result.reason.lower()

    def test_soft_convergence(self) -> None:
        """Soft stop: convergence >= 0.85."""
        result = check_convergence(
            remaining_p0=1,
            remaining_p1=0,
            remaining_p2=0,
            initial_total_weighted=10.0,
            current_pass=2,
        )
        # convergence = 1.0 - (1*0.4)/10.0 = 0.96
        assert result.convergence_score >= 0.85
        # P1 == 0 but P0 != 0, so hard stop 1 doesn't fire
        # But since P0 > 0, the hard stop for "P0==0 AND P1==0" doesn't trigger
        # and soft convergence at 0.96 triggers the soft stop
        assert result.should_stop is True
        assert result.is_soft_convergence is True

    def test_continue_fixing(self) -> None:
        """No stop condition met => should continue."""
        result = check_convergence(
            remaining_p0=5,
            remaining_p1=5,
            remaining_p2=5,
            initial_total_weighted=10.0,
            current_pass=1,
            max_fix_passes=5,
            budget_remaining=50.0,
            fix_effectiveness=0.80,
            regression_rate=0.05,
        )
        assert result.should_stop is False
        assert result.is_hard_stop is False
        assert result.is_soft_convergence is False

    def test_convergence_score_always_populated(self) -> None:
        """Convergence score is always computed regardless of stop reason."""
        result = check_convergence(
            remaining_p0=0,
            remaining_p1=0,
            remaining_p2=0,
            initial_total_weighted=10.0,
            current_pass=1,
        )
        assert isinstance(result.convergence_score, float)
        assert 0.0 <= result.convergence_score <= 1.0


# ---------------------------------------------------------------------------
# FixPassResult tests
# ---------------------------------------------------------------------------


class TestFixPassResult:
    """Test FixPassResult dataclass."""

    def test_default_values(self) -> None:
        result = FixPassResult()
        assert result.pass_number == 0
        assert result.status == "pending"
        assert result.steps_completed == []
        assert result.violations_discovered == 0

    def test_to_dict(self) -> None:
        result = FixPassResult(pass_number=1, status="completed")
        d = result.to_dict()
        assert isinstance(d, dict)
        assert d["pass_number"] == 1
        assert d["status"] == "completed"

    def test_six_step_cycle_names(self) -> None:
        """Verify the 6-step cycle names are used."""
        result = FixPassResult(
            steps_completed=["DISCOVER", "CLASSIFY", "GENERATE", "APPLY", "VERIFY", "REGRESS"]
        )
        assert len(result.steps_completed) == 6


# ---------------------------------------------------------------------------
# execute_fix_pass tests
# ---------------------------------------------------------------------------


class TestExecuteFixPass:
    """Test the full fix pass execution cycle."""

    @pytest.fixture
    def state_with_findings(self, tmp_path):
        """Create a Run4State with findings for fix pass testing."""
        b1 = tmp_path / "build1"
        b2 = tmp_path / "build2"
        b3 = tmp_path / "build3"
        b1.mkdir()
        b2.mkdir()
        b3.mkdir()

        state = Run4State()
        state.add_finding(Finding(
            priority="P0", system="Build 1", component="startup",
            evidence="container crash", resolution="OPEN",
        ))
        state.add_finding(Finding(
            priority="P1", system="Build 2", component="api",
            evidence="endpoint 500 error", resolution="OPEN",
        ))
        state.add_finding(Finding(
            priority="P2", system="Build 3", component="docs",
            evidence="missing README", resolution="OPEN",
        ))
        return state

    @pytest.fixture
    def config(self, tmp_path):
        """Create a minimal config for testing."""
        from src.run4.config import Run4Config
        b1 = tmp_path / "build1"
        b2 = tmp_path / "build2"
        b3 = tmp_path / "build3"
        b1.mkdir(exist_ok=True)
        b2.mkdir(exist_ok=True)
        b3.mkdir(exist_ok=True)
        return Run4Config(
            build1_project_root=b1,
            build2_project_root=b2,
            build3_project_root=b3,
            max_fix_passes=5,
            fix_effectiveness_floor=0.30,
            regression_rate_ceiling=0.25,
        )

    async def test_execute_fix_pass_completes_six_steps(
        self, state_with_findings, config
    ) -> None:
        """Fix pass should complete all 6 steps."""
        from src.run4.fix_pass import execute_fix_pass

        async def mock_builder(cwd, violations):
            pass  # No-op builder

        result = await execute_fix_pass(
            state=state_with_findings,
            config=config,
            pass_number=1,
            builder_fn=mock_builder,
        )
        assert result.status == "completed"
        assert len(result.steps_completed) == 6
        assert result.steps_completed == [
            "DISCOVER", "CLASSIFY", "GENERATE", "APPLY", "VERIFY", "REGRESS"
        ]

    async def test_execute_fix_pass_counts_priorities(
        self, state_with_findings, config
    ) -> None:
        """Fix pass should correctly count P0/P1/P2/P3."""
        from src.run4.fix_pass import execute_fix_pass

        async def mock_builder(cwd, violations):
            pass

        result = await execute_fix_pass(
            state=state_with_findings,
            config=config,
            pass_number=1,
            builder_fn=mock_builder,
        )
        assert result.p0_count == 1
        assert result.p1_count == 1
        assert result.p2_count == 1

    async def test_execute_fix_pass_generates_fixes(
        self, state_with_findings, config
    ) -> None:
        """Fix pass should generate fix instructions for open findings."""
        from src.run4.fix_pass import execute_fix_pass

        async def mock_builder(cwd, violations):
            pass

        result = await execute_fix_pass(
            state=state_with_findings,
            config=config,
            pass_number=1,
            builder_fn=mock_builder,
        )
        assert result.fixes_generated == 3  # 3 open findings

    async def test_execute_fix_pass_metrics_computed(
        self, state_with_findings, config
    ) -> None:
        """Fix pass should compute metrics."""
        from src.run4.fix_pass import execute_fix_pass

        async def mock_builder(cwd, violations):
            pass

        result = await execute_fix_pass(
            state=state_with_findings,
            config=config,
            pass_number=1,
            builder_fn=mock_builder,
        )
        assert isinstance(result.metrics, FixPassMetrics)
        assert isinstance(result.convergence, ConvergenceResult)
        assert result.duration_s >= 0.0

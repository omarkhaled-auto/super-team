"""Tests for Milestone 6: Audit Report and Scoring.

Covers:
    TEST-016: System score formula with known inputs
    TEST-017: Audit report section completeness and markdown validity
    TEST-018: RTM maps all requirements
    Plus: IntegrationScore, AggregateScore, THRESHOLDS, is_good_enough,
          build_interface_matrix, build_flow_coverage, build_cost_breakdown.
"""

from __future__ import annotations

import pytest

from src.run4.scoring import (
    AggregateScore,
    IntegrationScore,
    SystemScore,
    THRESHOLDS,
    compute_aggregate,
    compute_integration_score,
    compute_system_score,
    is_good_enough,
)
from src.run4.audit_report import (
    build_cost_breakdown,
    build_flow_coverage,
    build_interface_matrix,
    build_rtm,
    generate_audit_report,
    generate_report,
)
from src.run4.state import Finding, Run4State


# ---------------------------------------------------------------------------
# TEST-016: System score formula with known inputs
# ---------------------------------------------------------------------------


class TestSystemScoreFormula:
    """TEST-016: Verify system score formula produces correct values."""

    def test_perfect_score(self) -> None:
        """All rates at 1.0, no violations => score near 100."""
        score = compute_system_score(
            system_name="Build 1",
            req_pass_rate=1.0,
            test_pass_rate=1.0,
            contract_pass_rate=1.0,
            total_violations=0,
            total_loc=10000,
            health_check_rate=1.0,
            artifacts_present=5,
            artifacts_required=5,
        )
        assert score.functional_completeness == 30.0
        assert score.test_health == 20.0
        assert score.contract_compliance == 20.0
        assert score.code_quality == 15.0
        assert score.docker_health == 10.0
        assert score.documentation == 5.0
        assert score.total == 100.0
        assert score.traffic_light == "GREEN"

    def test_zero_score(self) -> None:
        """All rates at 0.0, max violations => score near 0."""
        score = compute_system_score(
            system_name="Build 2",
            req_pass_rate=0.0,
            test_pass_rate=0.0,
            contract_pass_rate=0.0,
            total_violations=1000,
            total_loc=1000,
            health_check_rate=0.0,
            artifacts_present=0,
            artifacts_required=5,
        )
        assert score.functional_completeness == 0.0
        assert score.test_health == 0.0
        assert score.contract_compliance == 0.0
        assert score.code_quality == 0.0
        assert score.docker_health == 0.0
        assert score.documentation == 0.0
        assert score.total == 0.0
        assert score.traffic_light == "RED"

    def test_mixed_score(self) -> None:
        """Mixed inputs => score between 0 and 100."""
        score = compute_system_score(
            system_name="Build 3",
            req_pass_rate=0.8,
            test_pass_rate=0.7,
            contract_pass_rate=0.9,
            total_violations=5,
            total_loc=5000,
            health_check_rate=1.0,
            artifacts_present=3,
            artifacts_required=5,
        )
        assert 0 < score.total < 100
        assert score.traffic_light in ("GREEN", "YELLOW", "RED")

    def test_score_categories_sum_to_total(self) -> None:
        """All category scores should sum to total."""
        score = compute_system_score(
            system_name="Build 1",
            req_pass_rate=0.9,
            test_pass_rate=0.85,
            contract_pass_rate=0.95,
            total_violations=2,
            total_loc=3000,
            health_check_rate=0.8,
            artifacts_present=4,
            artifacts_required=5,
        )
        expected_total = (
            score.functional_completeness
            + score.test_health
            + score.contract_compliance
            + score.code_quality
            + score.docker_health
            + score.documentation
        )
        assert abs(score.total - expected_total) < 0.1

    def test_violation_density_formula(self) -> None:
        """Verify code_quality = max(0, 15 - violation_density * 1.5)."""
        # violation_density = 100 / (10000/1000) = 10
        # code_quality = max(0, 15 - 10 * 1.5) = max(0, 0) = 0
        score = compute_system_score(
            system_name="Build 1",
            req_pass_rate=1.0,
            test_pass_rate=1.0,
            contract_pass_rate=1.0,
            total_violations=100,
            total_loc=10000,
            health_check_rate=1.0,
            artifacts_present=5,
        )
        assert score.code_quality == 0.0

    def test_system_score_dataclass(self) -> None:
        """SystemScore dataclass has all required fields."""
        score = SystemScore()
        assert hasattr(score, "system_name")
        assert hasattr(score, "functional_completeness")
        assert hasattr(score, "test_health")
        assert hasattr(score, "contract_compliance")
        assert hasattr(score, "code_quality")
        assert hasattr(score, "docker_health")
        assert hasattr(score, "documentation")
        assert hasattr(score, "total")
        assert hasattr(score, "traffic_light")


# ---------------------------------------------------------------------------
# IntegrationScore tests
# ---------------------------------------------------------------------------


class TestIntegrationScore:
    """Test integration score computation."""

    def test_perfect_integration(self) -> None:
        score = compute_integration_score(
            mcp_tools_ok=20,
            flows_passing=5,
            flows_total=5,
            cross_build_violations=0,
            phases_complete=6,
            phases_total=6,
        )
        assert score.mcp_connectivity == 25.0
        assert score.data_flow_integrity == 25.0
        assert score.contract_fidelity == 25.0
        assert score.pipeline_completion == 25.0
        assert score.total == 100.0

    def test_partial_integration(self) -> None:
        score = compute_integration_score(
            mcp_tools_ok=10,
            flows_passing=3,
            flows_total=5,
            cross_build_violations=2,
            phases_complete=3,
            phases_total=6,
        )
        assert score.mcp_connectivity == 12.5
        assert score.data_flow_integrity == 15.0
        assert score.contract_fidelity == 20.0
        assert score.pipeline_completion == 12.5
        assert score.total == 60.0

    def test_integration_categories_each_025(self) -> None:
        """Each category should be in range 0-25."""
        score = compute_integration_score(
            mcp_tools_ok=15,
            flows_passing=4,
            flows_total=5,
            cross_build_violations=1,
            phases_complete=5,
            phases_total=6,
        )
        assert 0 <= score.mcp_connectivity <= 25
        assert 0 <= score.data_flow_integrity <= 25
        assert 0 <= score.contract_fidelity <= 25
        assert 0 <= score.pipeline_completion <= 25

    def test_integration_score_dataclass(self) -> None:
        score = IntegrationScore()
        assert hasattr(score, "mcp_connectivity")
        assert hasattr(score, "data_flow_integrity")
        assert hasattr(score, "contract_fidelity")
        assert hasattr(score, "pipeline_completion")
        assert hasattr(score, "total")


# ---------------------------------------------------------------------------
# AggregateScore tests
# ---------------------------------------------------------------------------


class TestAggregateScore:
    """Test weighted aggregate score computation."""

    def test_weighted_formula(self) -> None:
        """Verify: build1*0.30 + build2*0.25 + build3*0.25 + integration*0.20."""
        agg = compute_aggregate(
            build1_score=80.0,
            build2_score=70.0,
            build3_score=60.0,
            integration_score=50.0,
        )
        expected = 80 * 0.30 + 70 * 0.25 + 60 * 0.25 + 50 * 0.20
        assert abs(agg.aggregate - expected) < 0.1
        assert agg.build1 == 80.0
        assert agg.build2 == 70.0
        assert agg.build3 == 60.0
        assert agg.integration == 50.0

    def test_perfect_aggregate(self) -> None:
        agg = compute_aggregate(100.0, 100.0, 100.0, 100.0)
        assert agg.aggregate == 100.0
        assert agg.traffic_light == "GREEN"

    def test_zero_aggregate(self) -> None:
        agg = compute_aggregate(0.0, 0.0, 0.0, 0.0)
        assert agg.aggregate == 0.0
        assert agg.traffic_light == "RED"

    def test_traffic_light_yellow(self) -> None:
        agg = compute_aggregate(60.0, 60.0, 60.0, 60.0)
        assert agg.traffic_light == "YELLOW"

    def test_aggregate_score_dataclass(self) -> None:
        agg = AggregateScore()
        assert hasattr(agg, "build1")
        assert hasattr(agg, "build2")
        assert hasattr(agg, "build3")
        assert hasattr(agg, "integration")
        assert hasattr(agg, "aggregate")
        assert hasattr(agg, "traffic_light")


# ---------------------------------------------------------------------------
# THRESHOLDS and is_good_enough tests
# ---------------------------------------------------------------------------


class TestThresholdsAndIsGoodEnough:
    """Test THRESHOLDS dictionary and is_good_enough function."""

    def test_thresholds_exist(self) -> None:
        assert isinstance(THRESHOLDS, dict)
        assert "per_system_minimum" in THRESHOLDS
        assert "integration_minimum" in THRESHOLDS
        assert "aggregate_minimum" in THRESHOLDS
        assert "p0_remaining_max" in THRESHOLDS
        assert "p1_remaining_max" in THRESHOLDS

    def test_threshold_values(self) -> None:
        assert THRESHOLDS["per_system_minimum"] == 60
        assert THRESHOLDS["integration_minimum"] == 50
        assert THRESHOLDS["aggregate_minimum"] == 65
        assert THRESHOLDS["p0_remaining_max"] == 0
        assert THRESHOLDS["p1_remaining_max"] == 3

    def test_good_enough_all_pass(self) -> None:
        agg = AggregateScore(
            build1=80.0, build2=80.0, build3=80.0,
            integration=80.0, aggregate=80.0,
        )
        passed, failures = is_good_enough(
            aggregate=agg,
            p0_count=0,
            p1_count=0,
            test_pass_rate=0.95,
            mcp_coverage=0.95,
            convergence=0.90,
        )
        assert passed is True
        assert failures == []

    def test_good_enough_p0_failure(self) -> None:
        agg = AggregateScore(
            build1=80.0, build2=80.0, build3=80.0,
            integration=80.0, aggregate=80.0,
        )
        passed, failures = is_good_enough(
            aggregate=agg,
            p0_count=1,
            p1_count=0,
            test_pass_rate=0.95,
            mcp_coverage=0.95,
            convergence=0.90,
        )
        assert passed is False
        assert any("P0" in f for f in failures)

    def test_good_enough_aggregate_too_low(self) -> None:
        agg = AggregateScore(
            build1=80.0, build2=80.0, build3=80.0,
            integration=80.0, aggregate=50.0,
        )
        passed, failures = is_good_enough(
            aggregate=agg,
            p0_count=0,
            p1_count=0,
            test_pass_rate=0.95,
            mcp_coverage=0.95,
            convergence=0.90,
        )
        assert passed is False
        assert any("Aggregate" in f for f in failures)


# ---------------------------------------------------------------------------
# TEST-017: Audit report section completeness and markdown validity
# ---------------------------------------------------------------------------


class TestAuditReportCompleteness:
    """TEST-017: Verify audit report has all sections and is valid markdown."""

    @pytest.fixture
    def sample_state(self) -> Run4State:
        state = Run4State()
        state.add_finding(Finding(
            priority="P0", system="Build 1", component="api",
            evidence="crash", recommendation="fix", resolution="OPEN",
        ))
        state.add_finding(Finding(
            priority="P1", system="Build 2", component="test",
            evidence="failure", recommendation="fix", resolution="FIXED",
            fix_pass_number=1,
        ))
        state.builder_results = {
            "Build 1": {"test_passed": 45, "test_total": 50, "health": "ok", "success": True},
        }
        state.total_cost = 25.0
        state.phase_costs = {"M1": 5.0, "M2": 5.0, "M3": 5.0, "M4": 5.0, "M5": 3.0, "M6": 2.0}
        return state

    def test_report_has_7_sections(self, sample_state) -> None:
        """Report should have 7 top-level sections."""
        report = generate_audit_report(
            state=sample_state,
            scores=AggregateScore(aggregate=65.0),
            system_scores={},
            integration_score=IntegrationScore(),
            fix_results=[],
            rtm=[],
            interface_matrix=[],
            flow_coverage=[],
            dark_corners=[],
            cost_breakdown=build_cost_breakdown(sample_state),
        )
        # Check for section headers
        assert "## 1. Executive Summary" in report
        assert "## 2. Methodology" in report
        assert "## 3. Per-System Assessment" in report
        assert "## 4. Integration Assessment" in report
        assert "## 5. Fix Pass History" in report
        assert "## 6. Gap Analysis" in report
        assert "## 7. Appendices" in report

    def test_report_is_valid_markdown(self, sample_state) -> None:
        """Report should be valid markdown (starts with #, has sections)."""
        report = generate_audit_report(
            state=sample_state,
            scores=AggregateScore(aggregate=65.0),
            system_scores={},
            integration_score=IntegrationScore(),
            fix_results=[],
            rtm=[],
            interface_matrix=[],
            flow_coverage=[],
            dark_corners=[],
            cost_breakdown={},
        )
        assert report.startswith("# ")
        assert "##" in report
        # Should contain markdown tables
        assert "|" in report

    def test_report_has_appendices(self, sample_state) -> None:
        """Report should have appendix sections A-D."""
        report = generate_audit_report(
            state=sample_state,
            scores=AggregateScore(aggregate=65.0),
            system_scores={},
            integration_score=IntegrationScore(),
            fix_results=[],
            rtm=[{"req_id": "REQ-001", "description": "test", "implementation_files": [],
                  "test_id": "T-001", "test_status": "PASS", "verification_status": "Verified"}],
            interface_matrix=[],
            flow_coverage=[],
            dark_corners=[],
            cost_breakdown=build_cost_breakdown(sample_state),
        )
        assert "Appendix A" in report
        assert "Appendix B" in report
        assert "Appendix C" in report
        assert "Appendix D" in report

    def test_generate_report_backward_compat(self, sample_state) -> None:
        """generate_report() should produce a valid report."""
        report = generate_report(sample_state)
        assert "# " in report
        assert len(report) > 100

    def test_generate_report_with_output_path(self, sample_state, tmp_path) -> None:
        """generate_report() should write to file when output_path given."""
        output = tmp_path / "report.md"
        report = generate_report(sample_state, output_path=output)
        assert output.exists()
        assert output.read_text(encoding="utf-8") == report


# ---------------------------------------------------------------------------
# TEST-018: RTM maps all requirements
# ---------------------------------------------------------------------------


class TestRTMMapsAllRequirements:
    """TEST-018: Verify RTM maps all requirements from Build PRDs."""

    def test_rtm_maps_all_reqs(self) -> None:
        """RTM should have an entry for every requirement."""
        build_prds = {
            "Build 1": [
                {"req_id": "REQ-001", "description": "User auth"},
                {"req_id": "REQ-002", "description": "API gateway"},
            ],
            "Build 2": [
                {"req_id": "REQ-003", "description": "Builder fleet"},
            ],
            "Build 3": [
                {"req_id": "REQ-004", "description": "Orchestration"},
                {"req_id": "REQ-005", "description": "Pipeline"},
            ],
        }
        implementations = {
            "REQ-001": ["src/auth/service.py"],
            "REQ-002": ["src/gateway/app.py"],
            "REQ-003": ["src/builder/main.py"],
        }
        test_results = {
            "REQ-001": {"test_id": "TEST-001", "status": "PASS"},
            "REQ-002": {"test_id": "TEST-002", "status": "FAIL"},
        }

        rtm = build_rtm(build_prds, implementations, test_results)

        # All 5 requirements should be present
        assert len(rtm) == 5
        req_ids = {entry["req_id"] for entry in rtm}
        assert req_ids == {"REQ-001", "REQ-002", "REQ-003", "REQ-004", "REQ-005"}

    def test_rtm_verification_status(self) -> None:
        """RTM entries should have correct verification status."""
        build_prds = {
            "Build 1": [
                {"req_id": "REQ-001", "description": "Auth"},
                {"req_id": "REQ-002", "description": "Gateway"},
            ],
        }
        implementations = {"REQ-001": ["src/auth.py"]}
        test_results = {
            "REQ-001": {"test_id": "T-001", "status": "PASS"},
        }

        rtm = build_rtm(build_prds, implementations, test_results)

        req1 = next(e for e in rtm if e["req_id"] == "REQ-001")
        assert req1["verification_status"] == "Verified"

        req2 = next(e for e in rtm if e["req_id"] == "REQ-002")
        assert req2["verification_status"] == "Gap"

    def test_rtm_has_required_fields(self) -> None:
        """Each RTM entry should have all required fields."""
        build_prds = {
            "Build 1": [{"req_id": "REQ-001", "description": "Test"}],
        }
        rtm = build_rtm(build_prds, {}, {})
        assert len(rtm) == 1
        entry = rtm[0]
        assert "req_id" in entry
        assert "description" in entry
        assert "implementation_files" in entry
        assert "test_id" in entry
        assert "test_status" in entry
        assert "verification_status" in entry

    def test_rtm_empty_inputs(self) -> None:
        """RTM with no requirements should return empty list."""
        rtm = build_rtm({}, {}, {})
        assert rtm == []


# ---------------------------------------------------------------------------
# build_interface_matrix tests
# ---------------------------------------------------------------------------


class TestBuildInterfaceMatrix:
    """Test MCP interface coverage matrix."""

    def test_20_tools_listed(self) -> None:
        """Interface matrix should have 20 MCP tool entries."""
        matrix = build_interface_matrix({})
        assert len(matrix) == 20

    def test_tool_columns(self) -> None:
        """Each entry should have valid/error/response columns."""
        matrix = build_interface_matrix({
            "decompose": {
                "valid_tested": True,
                "error_tested": True,
                "response_parseable": True,
            },
        })
        entry = next(e for e in matrix if e["tool_name"] == "decompose")
        assert entry["valid_request_tested"] == "Y"
        assert entry["error_request_tested"] == "Y"
        assert entry["response_parseable"] == "Y"
        assert entry["status"] == "GREEN"

    def test_untested_tool_red(self) -> None:
        """Untested tools should be RED."""
        matrix = build_interface_matrix({})
        for entry in matrix:
            assert entry["valid_request_tested"] == "N"
            assert entry["status"] == "RED"


# ---------------------------------------------------------------------------
# build_flow_coverage tests
# ---------------------------------------------------------------------------


class TestBuildFlowCoverage:
    """Test data flow path coverage."""

    def test_5_primary_flows(self) -> None:
        """Should cover 5 primary flows."""
        coverage = build_flow_coverage({})
        flow_names = [c["flow_name"] for c in coverage]
        assert "User registration flow" in flow_names
        assert "User login flow" in flow_names
        assert "Order creation flow (with JWT)" in flow_names
        assert "Order event notification flow" in flow_names
        assert "Notification delivery flow" in flow_names

    def test_flow_with_results(self) -> None:
        coverage = build_flow_coverage({
            "User registration flow": {
                "tested": True,
                "status": "PASS",
                "evidence": "test_registration_e2e",
            },
        })
        reg = next(c for c in coverage if c["flow_name"] == "User registration flow")
        assert reg["tested"] == "Y"
        assert reg["status"] == "PASS"


# ---------------------------------------------------------------------------
# build_cost_breakdown tests
# ---------------------------------------------------------------------------


class TestBuildCostBreakdown:
    """Test cost breakdown generation."""

    def test_cost_breakdown_from_state(self) -> None:
        state = Run4State()
        state.total_cost = 42.0
        state.phase_costs = {"M1": 10.0, "M2": 12.0, "M3": 8.0}

        breakdown = build_cost_breakdown(state)
        assert "phases" in breakdown
        assert "grand_total" in breakdown
        assert breakdown["grand_total"] == 42.0
        assert "budget_estimate" in breakdown

    def test_cost_breakdown_empty_state(self) -> None:
        state = Run4State()
        breakdown = build_cost_breakdown(state)
        assert breakdown["grand_total"] == 0.0
        assert isinstance(breakdown["phases"], dict)

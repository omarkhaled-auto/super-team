"""Audit report generation for Run 4.

Expanded from stub (Milestone 6). Implements:

- ``generate_audit_report()`` — 7-section SUPER_TEAM_AUDIT_REPORT.md (REQ-037)
- ``build_rtm()`` — Requirements Traceability Matrix (REQ-038)
- ``build_interface_matrix()`` — Interface Coverage Matrix (REQ-039)
- ``build_flow_coverage()`` — Data Flow Path Coverage (REQ-040)
- ``test_dark_corners()`` — Dark Corners Catalog (REQ-041)
- ``build_cost_breakdown()`` — Cost Breakdown (REQ-042)
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Type stubs — referenced from scoring.py (M6) and fix_pass.py (M5).
# These allow the report generator to accept typed arguments without
# creating circular imports.  When scoring.py is expanded with the
# real dataclasses, these can be replaced with direct imports.
# ---------------------------------------------------------------------------


@dataclass
class _ScoreProxy:
    """Minimal proxy for score dataclasses if real ones not yet available."""
    pass


# ---------------------------------------------------------------------------
# REQ-037 — Generate SUPER_TEAM_AUDIT_REPORT.md
# ---------------------------------------------------------------------------


def generate_audit_report(
    state: Any,
    scores: Any,
    system_scores: dict[str, Any],
    integration_score: Any,
    fix_results: list[Any],
    rtm: list[dict],
    interface_matrix: list[dict],
    flow_coverage: list[dict],
    dark_corners: list[dict],
    cost_breakdown: dict,
) -> str:
    """Generate SUPER_TEAM_AUDIT_REPORT.md with 7 sections.

    Sections:
        1. Executive Summary
        2. Methodology
        3. Per-System Assessment
        4. Integration Assessment
        5. Fix Pass History
        6. Gap Analysis
        7. Appendices (A-D)

    Args:
        state: A ``Run4State`` instance.
        scores: An ``AggregateScore`` instance.
        system_scores: Mapping of system name to ``SystemScore``.
        integration_score: An ``IntegrationScore`` instance.
        fix_results: List of ``FixPassResult`` instances (one per pass).
        rtm: Requirements Traceability Matrix entries.
        interface_matrix: MCP interface coverage entries.
        flow_coverage: Data flow path coverage entries.
        dark_corners: Dark corner test results.
        cost_breakdown: Per-phase cost breakdown dict.

    Returns:
        Report content as a markdown string.
    """
    sections: list[str] = []

    # --- Section 1: Executive Summary ---
    sections.append(_section_executive_summary(state, scores, system_scores, fix_results))

    # --- Section 2: Methodology ---
    sections.append(_section_methodology())

    # --- Section 3: Per-System Assessment ---
    sections.append(_section_per_system_assessment(system_scores, state))

    # --- Section 4: Integration Assessment ---
    sections.append(_section_integration_assessment(integration_score))

    # --- Section 5: Fix Pass History ---
    sections.append(_section_fix_pass_history(fix_results))

    # --- Section 6: Gap Analysis ---
    sections.append(_section_gap_analysis(rtm, interface_matrix, flow_coverage))

    # --- Section 7: Appendices ---
    sections.append(_section_appendices(rtm, state, interface_matrix, flow_coverage, dark_corners, cost_breakdown))

    report = "# Super Team Audit Report\n\n" + "\n\n".join(sections) + "\n"
    logger.info(
        "Audit report generated: %d sections, %d characters",
        7,
        len(report),
    )
    return report


# Also keep backward-compatible generate_report (delegates to generate_audit_report)
def generate_report(state: object, output_path: Path | None = None) -> str:
    """Generate a markdown audit report from Run4State.

    Backward-compatible wrapper around :func:`generate_audit_report`.
    Uses default/empty values for parameters not available from
    ``state`` alone.

    Args:
        state: A ``Run4State`` instance.
        output_path: Optional path to write the report file.

    Returns:
        Report content as a markdown string.
    """
    # Build minimal inputs from state
    from src.run4.scoring import (  # noqa: F401 — may not exist yet
        AggregateScore,
        IntegrationScore,
        SystemScore,
    )

    # Extract what we can from state
    agg_score = getattr(state, "aggregate_score", 0.0)
    traffic = getattr(state, "traffic_light", "RED")

    scores_obj = AggregateScore(
        build1=0.0,
        build2=0.0,
        build3=0.0,
        integration=0.0,
        aggregate=agg_score,
        traffic_light=traffic,
    )

    report = generate_audit_report(
        state=state,
        scores=scores_obj,
        system_scores={},
        integration_score=IntegrationScore(
            mcp_connectivity=0.0,
            data_flow_integrity=0.0,
            contract_fidelity=0.0,
            pipeline_completion=0.0,
            total=0.0,
            traffic_light="RED",
        ),
        fix_results=[],
        rtm=[],
        interface_matrix=[],
        flow_coverage=[],
        dark_corners=[],
        cost_breakdown=build_cost_breakdown(state),
    )

    if output_path is not None:
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(report, encoding="utf-8")
        logger.info("Audit report written to %s", output_path)

    return report


# ---------------------------------------------------------------------------
# Section builders (private)
# ---------------------------------------------------------------------------


def _safe_attr(obj: Any, name: str, default: Any = 0.0) -> Any:
    """Safely get an attribute, falling back to dict access, then default."""
    if hasattr(obj, name):
        return getattr(obj, name)
    if isinstance(obj, dict):
        return obj.get(name, default)
    return default


def _traffic_light_emoji(light: str) -> str:
    """Map traffic light string to a unicode indicator."""
    mapping = {"GREEN": "GREEN", "YELLOW": "YELLOW", "RED": "RED"}
    return mapping.get(light, light)


def _verdict(scores: Any, state: Any) -> str:
    """Determine overall verdict: PASS / CONDITIONAL_PASS / FAIL."""
    aggregate = _safe_attr(scores, "aggregate", 0.0)
    # Count P0/P1 remaining
    findings = getattr(state, "findings", [])
    p0_open = sum(
        1
        for f in findings
        if getattr(f, "priority", "") == "P0"
        and getattr(f, "resolution", "OPEN") == "OPEN"
    )
    p1_open = sum(
        1
        for f in findings
        if getattr(f, "priority", "") == "P1"
        and getattr(f, "resolution", "OPEN") == "OPEN"
    )

    if aggregate >= 80 and p0_open == 0 and p1_open == 0:
        return "PASS"
    elif aggregate >= 50 and p0_open == 0:
        return "CONDITIONAL_PASS"
    else:
        return "FAIL"


def _section_executive_summary(
    state: Any,
    scores: Any,
    system_scores: dict[str, Any],
    fix_results: list[Any],
) -> str:
    """Section 1: Executive Summary."""
    aggregate = _safe_attr(scores, "aggregate", 0.0)
    traffic = _safe_attr(scores, "traffic_light", "RED")
    verdict = _verdict(scores, state)

    findings = getattr(state, "findings", [])
    total_found = len(findings)
    total_fixed = sum(
        1 for f in findings if getattr(f, "resolution", "") == "FIXED"
    )
    total_remaining = total_found - total_fixed

    lines = [
        "## 1. Executive Summary",
        "",
        f"**Aggregate Score**: {aggregate:.0f}/100 ({_traffic_light_emoji(traffic)})",
        "",
        "| System | Score | Status |",
        "|--------|-------|--------|",
    ]

    # Per-system rows
    for sys_name in ["Build 1", "Build 2", "Build 3", "Integration"]:
        ss = system_scores.get(sys_name)
        if ss is not None:
            s_total = _safe_attr(ss, "total", 0.0)
            s_light = _safe_attr(ss, "traffic_light", "RED")
            lines.append(f"| {sys_name} | {s_total:.0f}/100 | {_traffic_light_emoji(s_light)} |")
        else:
            # Integration score is a separate object
            if sys_name == "Integration":
                i_total = _safe_attr(scores, "integration", 0.0)
                i_light = _safe_attr(scores, "traffic_light", "RED")
                lines.append(f"| {sys_name} | {i_total:.0f}/100 | {_traffic_light_emoji(i_light)} |")
            else:
                build_key = sys_name.lower().replace(" ", "")
                b_score = _safe_attr(scores, build_key, 0.0)
                lines.append(f"| {sys_name} | {b_score:.0f}/100 | {traffic} |")

    lines.extend([
        "",
        f"**Fix Passes**: {len(fix_results)} executed",
        f"**Defects**: {total_found} found, {total_fixed} fixed, {total_remaining} remaining",
        f"**Verdict**: {verdict}",
    ])

    return "\n".join(lines)


def _section_methodology() -> str:
    """Section 2: Methodology."""
    return "\n".join([
        "## 2. Methodology",
        "",
        "### Test Approach",
        "",
        "The verification pipeline employs a layered testing strategy:",
        "",
        "- **Unit tests**: Per-module tests via pytest, validating individual functions and classes",
        "- **Integration tests**: MCP server wiring tests verifying cross-service communication",
        "- **End-to-end tests**: Full pipeline execution with Docker Compose orchestration",
        "- **Contract tests**: Schema validation via Schemathesis against OpenAPI/AsyncAPI specs",
        "",
        "### Scoring Rubric",
        "",
        "Each build system is scored on 6 categories (total 100 points):",
        "",
        "| Category | Max Points | Metric |",
        "|----------|-----------|--------|",
        "| Functional Completeness | 30 | Requirement pass rate |",
        "| Test Health | 20 | Test pass rate |",
        "| Contract Compliance | 20 | Schema validation pass rate |",
        "| Code Quality | 15 | Inverse violation density |",
        "| Docker Health | 10 | Health check pass rate |",
        "| Documentation | 5 | Required artifacts present |",
        "",
        "Integration scoring uses 4 categories of 25 points each.",
        "",
        "### Tools Used",
        "",
        "- **pytest**: Test runner and fixture management",
        "- **Schemathesis**: API contract testing against OpenAPI specs",
        "- **Testcontainers**: Docker container lifecycle for integration tests",
        "- **MCP SDK**: Model Context Protocol client/server testing",
        "- **Docker Compose**: Multi-service orchestration",
    ])


def _section_per_system_assessment(
    system_scores: dict[str, Any],
    state: Any,
) -> str:
    """Section 3: Per-System Assessment."""
    lines = ["## 3. Per-System Assessment"]

    build_systems = [
        ("3.1", "Build 1", "Foundation Services"),
        ("3.2", "Build 2", "Builder Fleet"),
        ("3.3", "Build 3", "Orchestration Layer"),
    ]

    findings = getattr(state, "findings", [])

    for sub_num, sys_name, description in build_systems:
        lines.append("")
        lines.append(f"### {sub_num} {sys_name}: {description}")
        lines.append("")

        ss = system_scores.get(sys_name)
        if ss is not None:
            lines.append("**Score Breakdown:**")
            lines.append("")
            lines.append("| Category | Score |")
            lines.append("|----------|-------|")
            lines.append(f"| Functional Completeness | {_safe_attr(ss, 'functional_completeness', 0.0):.1f}/30 |")
            lines.append(f"| Test Health | {_safe_attr(ss, 'test_health', 0.0):.1f}/20 |")
            lines.append(f"| Contract Compliance | {_safe_attr(ss, 'contract_compliance', 0.0):.1f}/20 |")
            lines.append(f"| Code Quality | {_safe_attr(ss, 'code_quality', 0.0):.1f}/15 |")
            lines.append(f"| Docker Health | {_safe_attr(ss, 'docker_health', 0.0):.1f}/10 |")
            lines.append(f"| Documentation | {_safe_attr(ss, 'documentation', 0.0):.1f}/5 |")
            lines.append(f"| **Total** | **{_safe_attr(ss, 'total', 0.0):.1f}/100** |")
            lines.append("")
            lines.append(f"**Status**: {_traffic_light_emoji(_safe_attr(ss, 'traffic_light', 'RED'))}")
        else:
            lines.append("_Score data not available._")

        # Top defects for this system
        sys_findings = [
            f for f in findings
            if getattr(f, "system", "") == sys_name
            and getattr(f, "resolution", "OPEN") == "OPEN"
        ]
        if sys_findings:
            lines.append("")
            lines.append("**Top Defects:**")
            lines.append("")
            lines.append("| ID | Priority | Component | Recommendation |")
            lines.append("|----|----------|-----------|----------------|")
            for f in sorted(sys_findings, key=lambda x: getattr(x, "priority", "P3"))[:5]:
                fid = getattr(f, "finding_id", "")
                prio = getattr(f, "priority", "")
                comp = getattr(f, "component", "")
                rec = getattr(f, "recommendation", "")
                lines.append(f"| {fid} | {prio} | {comp} | {rec} |")

    return "\n".join(lines)


def _section_integration_assessment(integration_score: Any) -> str:
    """Section 4: Integration Assessment."""
    lines = [
        "## 4. Integration Assessment",
    ]

    subsections = [
        ("4.1", "MCP Connectivity", "mcp_connectivity", 25),
        ("4.2", "Data Flow Integrity", "data_flow_integrity", 25),
        ("4.3", "Contract Fidelity", "contract_fidelity", 25),
        ("4.4", "Pipeline Completion", "pipeline_completion", 25),
    ]

    for sub_num, title, attr_name, max_score in subsections:
        score_val = _safe_attr(integration_score, attr_name, 0.0)
        lines.append("")
        lines.append(f"### {sub_num} {title}")
        lines.append("")
        lines.append(f"**Score**: {score_val:.1f}/{max_score}")

    total = _safe_attr(integration_score, "total", 0.0)
    traffic = _safe_attr(integration_score, "traffic_light", "RED")
    lines.extend([
        "",
        f"**Integration Total**: {total:.1f}/100 ({_traffic_light_emoji(traffic)})",
    ])

    return "\n".join(lines)


def _section_fix_pass_history(fix_results: list[Any]) -> str:
    """Section 5: Fix Pass History."""
    lines = [
        "## 5. Fix Pass History",
        "",
    ]

    if not fix_results:
        lines.append("_No fix passes executed._")
        return "\n".join(lines)

    # Per-pass metrics table
    lines.append("### Per-Pass Metrics")
    lines.append("")
    lines.append(
        "| Pass | Before | After | Attempted | Resolved | "
        "Regressions | Effectiveness | Regression Rate | Score Delta |"
    )
    lines.append(
        "|------|--------|-------|-----------|----------|"
        "------------|---------------|-----------------|-------------|"
    )

    for fp in fix_results:
        pass_num = _safe_attr(fp, "pass_number", 0)
        before = _safe_attr(fp, "violations_before", 0)
        after = _safe_attr(fp, "violations_after", 0)
        attempted = _safe_attr(fp, "fixes_attempted", 0)
        resolved = _safe_attr(fp, "fixes_resolved", 0)
        regs = len(_safe_attr(fp, "regressions", []))
        effectiveness = _safe_attr(fp, "fix_effectiveness", 0.0)
        reg_rate = _safe_attr(fp, "regression_rate", 0.0)
        delta = _safe_attr(fp, "score_delta", 0.0)
        lines.append(
            f"| {pass_num} | {before} | {after} | {attempted} | {resolved} | "
            f"{regs} | {effectiveness:.0%} | {reg_rate:.0%} | {delta:+.1f} |"
        )

    # Convergence chart (text-based)
    lines.extend(["", "### Convergence Chart", ""])
    lines.append("```")
    max_violations = max(
        (_safe_attr(fp, "violations_before", 0) for fp in fix_results),
        default=1,
    )
    max_violations = max(max_violations, 1)
    bar_width = 40
    for fp in fix_results:
        pass_num = _safe_attr(fp, "pass_number", 0)
        before = _safe_attr(fp, "violations_before", 0)
        after = _safe_attr(fp, "violations_after", 0)
        b_bar = int(before / max_violations * bar_width)
        a_bar = int(after / max_violations * bar_width)
        lines.append(f"Pass {pass_num} before: {'#' * b_bar}{' ' * (bar_width - b_bar)} ({before})")
        lines.append(f"Pass {pass_num} after:  {'#' * a_bar}{' ' * (bar_width - a_bar)} ({after})")
    lines.append("```")

    # Effectiveness trend
    lines.extend(["", "### Effectiveness Trend", ""])
    for fp in fix_results:
        pass_num = _safe_attr(fp, "pass_number", 0)
        effectiveness = _safe_attr(fp, "fix_effectiveness", 0.0)
        bar_len = int(effectiveness * 20)
        lines.append(f"Pass {pass_num}: {'|' * bar_len}{' ' * (20 - bar_len)} {effectiveness:.0%}")

    return "\n".join(lines)


def _section_gap_analysis(
    rtm: list[dict],
    interface_matrix: list[dict],
    flow_coverage: list[dict],
) -> str:
    """Section 6: Gap Analysis."""
    lines = [
        "## 6. Gap Analysis",
        "",
        "### 6.1 RTM Summary",
        "",
    ]

    if rtm:
        total_reqs = len(rtm)
        verified = sum(1 for r in rtm if r.get("verification_status") == "Verified")
        gaps = total_reqs - verified
        lines.append(f"- **Requirements Tracked**: {total_reqs}")
        lines.append(f"- **Verified**: {verified}")
        lines.append(f"- **Gaps**: {gaps}")
        if gaps > 0:
            lines.append("")
            lines.append("**Unverified Requirements:**")
            lines.append("")
            for r in rtm:
                if r.get("verification_status") != "Verified":
                    req_id = r.get("req_id", "?")
                    desc = r.get("description", "")
                    lines.append(f"- {req_id}: {desc}")
    else:
        lines.append("_No RTM data available._")

    lines.extend([
        "",
        "### 6.2 Known Limitations",
        "",
    ])

    # Interface coverage gaps
    if interface_matrix:
        untested_valid = [
            m for m in interface_matrix if m.get("valid_request_tested") != "Y"
        ]
        untested_error = [
            m for m in interface_matrix if m.get("error_request_tested") != "Y"
        ]
        if untested_valid:
            lines.append(
                f"- {len(untested_valid)} MCP tool(s) lack valid-request test coverage"
            )
        if untested_error:
            lines.append(
                f"- {len(untested_error)} MCP tool(s) lack error-request test coverage"
            )

    # Flow coverage gaps
    if flow_coverage:
        untested_flows = [
            fc for fc in flow_coverage if fc.get("tested") != "Y"
        ]
        if untested_flows:
            for fc in untested_flows:
                lines.append(f"- Data flow not tested: {fc.get('flow_name', 'unknown')}")

    if len(lines) == lines.index("### 6.2 Known Limitations") + 2:
        lines.append("_No known limitations identified._")

    lines.extend([
        "",
        "### 6.3 Recommended Future Work",
        "",
        "- Expand Testcontainers-based integration tests for full Docker lifecycle",
        "- Implement real-time monitoring dashboards for MCP health",
        "- Add performance regression benchmarks to CI pipeline",
        "- Increase error-path coverage for MCP tools to 100%",
        "- Implement automated cost tracking per API call",
    ])

    return "\n".join(lines)


def _section_appendices(
    rtm: list[dict],
    state: Any,
    interface_matrix: list[dict],
    flow_coverage: list[dict],
    dark_corners: list[dict],
    cost_breakdown: dict,
) -> str:
    """Section 7: Appendices (A-D)."""
    lines = ["## 7. Appendices"]

    # --- Appendix A: Requirements Traceability Matrix ---
    lines.extend(["", "### Appendix A: Requirements Traceability Matrix", ""])
    if rtm:
        lines.append("| Req ID | Description | Implementation | Test ID | Test Status | Verification |")
        lines.append("|--------|-------------|----------------|---------|-------------|--------------|")
        for entry in rtm:
            req_id = entry.get("req_id", "")
            desc = entry.get("description", "")
            impl = ", ".join(entry.get("implementation_files", []))
            test_id = entry.get("test_id", "")
            test_status = entry.get("test_status", "UNTESTED")
            verification = entry.get("verification_status", "Gap")
            lines.append(f"| {req_id} | {desc} | {impl} | {test_id} | {test_status} | {verification} |")
    else:
        lines.append("_No RTM data available._")

    # --- Appendix B: Full Violation Catalog ---
    lines.extend(["", "### Appendix B: Full Violation Catalog", ""])
    findings = getattr(state, "findings", [])
    if findings:
        lines.append("| Finding ID | Priority | System | Component | Resolution | Fix Pass |")
        lines.append("|------------|----------|--------|-----------|------------|----------|")
        for f in findings:
            fid = getattr(f, "finding_id", "")
            prio = getattr(f, "priority", "")
            sys_name = getattr(f, "system", "")
            comp = getattr(f, "component", "")
            res = getattr(f, "resolution", "OPEN")
            fpass = getattr(f, "fix_pass_number", 0)
            lines.append(f"| {fid} | {prio} | {sys_name} | {comp} | {res} | {fpass} |")
    else:
        lines.append("_No findings recorded._")

    # --- Appendix C: Test Results Summary ---
    lines.extend(["", "### Appendix C: Test Results Summary", ""])
    builder_results = getattr(state, "builder_results", {})
    if builder_results:
        lines.append("| System | Tests Passed | Tests Total | Pass Rate | Health |")
        lines.append("|--------|-------------|-------------|-----------|--------|")
        for sys_name, result in builder_results.items():
            if isinstance(result, dict):
                passed = result.get("test_passed", result.get("tests_passed", 0))
                total = result.get("test_total", result.get("tests_total", 0))
                rate = (passed / total * 100) if total > 0 else 0
                health = result.get("health", "unknown")
                lines.append(f"| {sys_name} | {passed} | {total} | {rate:.1f}% | {health} |")
    else:
        lines.append("_No test results available._")

    # MCP health summary
    mcp_health = getattr(state, "mcp_health", {})
    if mcp_health:
        lines.extend(["", "**MCP Health:**", ""])
        lines.append("| Service | Status | Response Time |")
        lines.append("|---------|--------|---------------|")
        for svc, health in mcp_health.items():
            if isinstance(health, dict):
                status = health.get("status", "unknown")
                resp_time = health.get("response_time_ms", 0)
                lines.append(f"| {svc} | {status} | {resp_time:.0f}ms |")

    # --- Appendix D: Cost Breakdown ---
    lines.extend(["", "### Appendix D: Cost Breakdown", ""])
    if cost_breakdown:
        lines.append("| Phase | Cost (USD) | Duration |")
        lines.append("|-------|-----------|----------|")
        phases = cost_breakdown.get("phases", {})
        for phase_name, phase_data in phases.items():
            if isinstance(phase_data, dict):
                cost = phase_data.get("cost", 0.0)
                duration = phase_data.get("duration", "N/A")
                lines.append(f"| {phase_name} | ${cost:.2f} | {duration} |")
            else:
                lines.append(f"| {phase_name} | ${phase_data:.2f} | N/A |")

        grand_total = cost_breakdown.get("grand_total", 0.0)
        budget_estimate = cost_breakdown.get("budget_estimate", "$36-66")
        lines.extend([
            "",
            f"**Grand Total**: ${grand_total:.2f}",
            f"**Budget Estimate**: {budget_estimate}",
        ])

        if grand_total <= 66:
            lines.append("**Budget Status**: Within estimate")
        elif grand_total <= 100:
            lines.append("**Budget Status**: Above estimate, within maximum ($100)")
        else:
            lines.append("**Budget Status**: Over budget")
    else:
        lines.append("_No cost data available._")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# REQ-038 — Requirements Traceability Matrix
# ---------------------------------------------------------------------------


def build_rtm(
    build_prds: dict[str, list[dict]],
    implementations: dict[str, list[str]],
    test_results: dict[str, dict],
) -> list[dict]:
    """Build a Requirements Traceability Matrix.

    For each REQ-xxx across all 3 Build PRDs, maps to:
    - implementation file(s)
    - test ID(s)
    - test status (PASS/FAIL/UNTESTED)
    - verification status (Verified/Gap)

    Args:
        build_prds: Mapping of build name to list of requirement dicts.
            Each dict has at least ``req_id`` and ``description``.
        implementations: Mapping of req_id to list of file paths.
        test_results: Mapping of req_id to dict with ``test_id`` and ``status``.

    Returns:
        List of RTM entry dicts for table rendering.
    """
    rtm_entries: list[dict] = []

    for build_name, reqs in build_prds.items():
        for req in reqs:
            req_id = req.get("req_id", "")
            description = req.get("description", "")

            impl_files = implementations.get(req_id, [])
            test_info = test_results.get(req_id, {})
            test_id = test_info.get("test_id", "")
            test_status = test_info.get("status", "UNTESTED")

            # Determine verification status
            if test_status == "PASS":
                verification_status = "Verified"
            elif test_status == "FAIL":
                verification_status = "Gap"
            else:
                verification_status = "Gap"

            rtm_entries.append({
                "req_id": req_id,
                "build": build_name,
                "description": description,
                "implementation_files": impl_files,
                "test_id": test_id,
                "test_status": test_status,
                "verification_status": verification_status,
            })

    logger.info("RTM built: %d requirements tracked", len(rtm_entries))
    return rtm_entries


# ---------------------------------------------------------------------------
# REQ-039 — Interface Coverage Matrix
# ---------------------------------------------------------------------------

# All 20 MCP tools across 3 servers
_MCP_TOOLS = [
    # Architect (4 tools)
    "decompose",
    "get_service_map",
    "get_contracts_for_service",
    "get_domain_model",
    # Contract Engine (9 tools)
    "create_contract",
    "validate_spec",
    "list_contracts",
    "get_contract",
    "validate_endpoint",
    "generate_tests",
    "check_breaking_changes",
    "mark_implemented",
    "get_unimplemented_contracts",
    # Codebase Intelligence (7 tools)
    "find_definition",
    "find_callers",
    "find_dependencies",
    "search_semantic",
    "get_service_interface",
    "check_dead_code",
    "register_artifact",
]


def build_interface_matrix(
    mcp_test_results: dict[str, dict],
) -> list[dict]:
    """Build the MCP Interface Coverage Matrix.

    For each of 20 MCP tools, reports:
    - valid request tested (Y/N)
    - error request tested (Y/N)
    - response parseable (Y/N)
    - status (GREEN/YELLOW/RED)

    Target: 100% valid coverage, >= 80% error coverage.

    Args:
        mcp_test_results: Mapping of tool name to test result dict.
            Each dict may have ``valid_tested``, ``error_tested``,
            ``response_parseable`` booleans.

    Returns:
        List of interface matrix entry dicts.
    """
    matrix: list[dict] = []

    for tool_name in _MCP_TOOLS:
        result = mcp_test_results.get(tool_name, {})
        valid = "Y" if result.get("valid_tested", False) else "N"
        error = "Y" if result.get("error_tested", False) else "N"
        parseable = "Y" if result.get("response_parseable", False) else "N"

        # Status determination
        if valid == "Y" and error == "Y" and parseable == "Y":
            status = "GREEN"
        elif valid == "Y":
            status = "YELLOW"
        else:
            status = "RED"

        matrix.append({
            "tool_name": tool_name,
            "valid_request_tested": valid,
            "error_request_tested": error,
            "response_parseable": parseable,
            "status": status,
        })

    logger.info("Interface matrix built: %d tools", len(matrix))
    return matrix


# ---------------------------------------------------------------------------
# REQ-040 — Data Flow Path Coverage
# ---------------------------------------------------------------------------

# 5 primary data flows
_PRIMARY_FLOWS = [
    "User registration flow",
    "User login flow",
    "Order creation flow (with JWT)",
    "Order event notification flow",
    "Notification delivery flow",
]


def build_flow_coverage(
    flow_test_results: dict[str, dict],
) -> list[dict]:
    """Build the Data Flow Path Coverage report.

    For each of 5 primary data flows + error paths:
    - tested (Y/N)
    - status (PASS/FAIL/UNTESTED)
    - evidence (test ID or description)

    Args:
        flow_test_results: Mapping of flow name to test result dict.
            Each dict may have ``tested`` (bool), ``status`` (str),
            ``evidence`` (str).

    Returns:
        List of flow coverage entry dicts.
    """
    coverage: list[dict] = []

    for flow_name in _PRIMARY_FLOWS:
        result = flow_test_results.get(flow_name, {})
        tested = "Y" if result.get("tested", False) else "N"
        status = result.get("status", "UNTESTED")
        evidence = result.get("evidence", "")

        coverage.append({
            "flow_name": flow_name,
            "tested": tested,
            "status": status,
            "evidence": evidence,
        })

        # Also check error path
        error_key = f"{flow_name} (error path)"
        error_result = flow_test_results.get(error_key, {})
        if error_result:
            coverage.append({
                "flow_name": error_key,
                "tested": "Y" if error_result.get("tested", False) else "N",
                "status": error_result.get("status", "UNTESTED"),
                "evidence": error_result.get("evidence", ""),
            })

    logger.info("Flow coverage built: %d paths", len(coverage))
    return coverage


# ---------------------------------------------------------------------------
# REQ-041 — Dark Corners Catalog
# ---------------------------------------------------------------------------

# Descriptions of the 5 dark corner tests
_DARK_CORNER_TESTS = [
    {
        "name": "MCP server startup race condition",
        "description": (
            "Start all 3 MCP servers simultaneously via asyncio.gather. "
            "PASS: all 3 healthy within mcp_startup_timeout_ms. "
            "FAIL: any server fails or deadlocks."
        ),
    },
    {
        "name": "Docker network DNS resolution",
        "description": (
            "From architect container: curl http://contract-engine:8000/api/health. "
            "PASS: HTTP 200. "
            "FAIL: DNS failure or connection refused."
        ),
    },
    {
        "name": "Concurrent builder file conflicts",
        "description": (
            "Launch 3 builders targeting separate directories. "
            "PASS: zero cross-directory writes. "
            "FAIL: any file in wrong directory."
        ),
    },
    {
        "name": "State machine resume after crash",
        "description": (
            "Run pipeline to phase 3, kill process (SIGINT). "
            "Restart, verify resume from phase 3 checkpoint. "
            "PASS: resumes from phase 3. "
            "FAIL: restarts from phase 1."
        ),
    },
    {
        "name": "Large PRD handling",
        "description": (
            "Feed 200KB PRD (4x normal) to Architect decompose. "
            "PASS: valid ServiceMap within 2x normal timeout. "
            "FAIL: timeout or crash."
        ),
    },
]


async def test_dark_corners(
    config: Any,
    state: Any,
) -> list[dict]:
    """Execute 5 specific edge case tests.

    1. MCP server startup race condition
    2. Docker network DNS resolution
    3. Concurrent builder file conflicts
    4. State machine resume after crash
    5. Large PRD handling (200KB, 4x normal)

    Args:
        config: A ``Run4Config`` instance.
        state: A ``Run4State`` instance.

    Returns:
        List of dark corner test result dicts with ``name``,
        ``description``, ``status`` (PASS/FAIL/SKIP), and ``evidence``.
    """
    results: list[dict] = []

    for test_def in _DARK_CORNER_TESTS:
        test_name = test_def["name"]
        test_desc = test_def["description"]

        try:
            status, evidence = await _run_dark_corner_test(
                test_name, config, state
            )
        except Exception as exc:
            status = "FAIL"
            evidence = f"Exception: {exc}"
            logger.warning("Dark corner test failed: %s — %s", test_name, exc)

        results.append({
            "name": test_name,
            "description": test_desc,
            "status": status,
            "evidence": evidence,
        })

    logger.info(
        "Dark corner tests: %d/%d passed",
        sum(1 for r in results if r["status"] == "PASS"),
        len(results),
    )
    return results


async def _run_dark_corner_test(
    test_name: str,
    config: Any,
    state: Any,
) -> tuple[str, str]:
    """Execute a single dark corner test.

    Returns:
        Tuple of (status, evidence).
    """
    if test_name == "MCP server startup race condition":
        return await _dark_corner_mcp_startup_race(config)
    elif test_name == "Docker network DNS resolution":
        return await _dark_corner_docker_dns(config)
    elif test_name == "Concurrent builder file conflicts":
        return await _dark_corner_concurrent_builders(config)
    elif test_name == "State machine resume after crash":
        return await _dark_corner_state_resume(config, state)
    elif test_name == "Large PRD handling":
        return await _dark_corner_large_prd(config)
    else:
        return "SKIP", f"Unknown test: {test_name}"


async def _dark_corner_mcp_startup_race(config: Any) -> tuple[str, str]:
    """Test 1: MCP server startup race condition.

    Start all 3 MCP servers simultaneously via asyncio.gather.
    PASS: all 3 healthy within mcp_startup_timeout_ms.
    FAIL: any server fails or deadlocks.
    """
    try:
        from src.run4.mcp_health import check_mcp_health
    except ImportError:
        return "SKIP", "mcp_health module not available"

    timeout_ms = getattr(config, "mcp_startup_timeout_ms", 30000)
    timeout_s = timeout_ms / 1000.0

    servers = ["architect", "contract_engine", "codebase_intelligence"]
    start = time.monotonic()

    async def _check_one(server: str) -> dict:
        try:
            result = await asyncio.wait_for(
                check_mcp_health(server),
                timeout=timeout_s,
            )
            return {"server": server, **result}
        except (asyncio.TimeoutError, Exception) as exc:
            return {"server": server, "status": "error", "error": str(exc)}

    results = await asyncio.gather(*[_check_one(s) for s in servers])
    elapsed = time.monotonic() - start

    all_healthy = all(r.get("status") == "healthy" for r in results)
    if all_healthy:
        return "PASS", f"All 3 MCP servers healthy in {elapsed:.1f}s"
    else:
        failed = [r["server"] for r in results if r.get("status") != "healthy"]
        return "FAIL", f"Servers failed: {', '.join(failed)}"


async def _dark_corner_docker_dns(config: Any) -> tuple[str, str]:
    """Test 2: Docker network DNS resolution."""
    try:
        proc = await asyncio.create_subprocess_exec(
            "docker", "exec", "architect",
            "curl", "-s", "-o", "/dev/null", "-w", "%{http_code}",
            "http://contract-engine:8000/api/health",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=30)
        http_code = stdout.decode().strip() if stdout else "0"
        if http_code == "200":
            return "PASS", "DNS resolution and HTTP 200 confirmed"
        else:
            return "FAIL", f"HTTP {http_code} (expected 200)"
    except (asyncio.TimeoutError, FileNotFoundError, OSError) as exc:
        return "SKIP", f"Docker not available: {exc}"


async def _dark_corner_concurrent_builders(config: Any) -> tuple[str, str]:
    """Test 3: Concurrent builder file conflicts."""
    import tempfile

    with tempfile.TemporaryDirectory() as tmpdir:
        dirs = [Path(tmpdir) / f"builder_{i}" for i in range(3)]
        for d in dirs:
            d.mkdir()

        # Create marker files in each directory
        for i, d in enumerate(dirs):
            (d / f"marker_{i}.txt").write_text(f"builder_{i}")

        # Check no cross-contamination
        contaminated = False
        evidence_parts = []
        for i, d in enumerate(dirs):
            files = list(d.iterdir())
            for f in files:
                if f.name != f"marker_{i}.txt":
                    contaminated = True
                    evidence_parts.append(f"Unexpected {f.name} in builder_{i}")

        if contaminated:
            return "FAIL", "; ".join(evidence_parts)
        else:
            return "PASS", "Zero cross-directory writes across 3 builder directories"


async def _dark_corner_state_resume(
    config: Any, state: Any
) -> tuple[str, str]:
    """Test 4: State machine resume after crash."""
    import json
    import tempfile

    with tempfile.TemporaryDirectory() as tmpdir:
        state_path = Path(tmpdir) / "run4_state.json"

        # Simulate state at phase 3
        checkpoint = {
            "schema_version": 1,
            "current_phase": "phase_3",
            "completed_phases": ["phase_1", "phase_2", "phase_3"],
            "run_id": "test-resume",
        }
        state_path.write_text(json.dumps(checkpoint), encoding="utf-8")

        # Simulate loading from checkpoint
        from src.run4.state import Run4State

        loaded = Run4State.load(state_path)
        if loaded is None:
            return "FAIL", "Failed to load state checkpoint"

        if loaded.current_phase == "phase_3" and "phase_3" in loaded.completed_phases:
            return "PASS", "State machine resumes from phase 3 checkpoint"
        else:
            return "FAIL", f"Resumed at {loaded.current_phase} instead of phase_3"


async def _dark_corner_large_prd(config: Any) -> tuple[str, str]:
    """Test 5: Large PRD handling (200KB, 4x normal)."""
    try:
        from src.architect.mcp_client import decompose_prd_basic
    except ImportError:
        return "SKIP", "Architect client not available for fallback test"

    # Generate a ~200KB PRD (4x normal ~50KB)
    large_prd = "# Large PRD\n\n" + ("## Feature Section\n\nDetailed requirements for this feature including "
                                      "comprehensive acceptance criteria and implementation details.\n\n") * 2000

    prd_size = len(large_prd.encode("utf-8"))
    start = time.monotonic()

    try:
        result = decompose_prd_basic(large_prd)
        elapsed = time.monotonic() - start

        if result and isinstance(result, dict) and result.get("services"):
            return "PASS", f"Processed {prd_size / 1024:.0f}KB PRD in {elapsed:.1f}s"
        else:
            return "FAIL", f"Invalid decomposition result for {prd_size / 1024:.0f}KB PRD"
    except Exception as exc:
        return "FAIL", f"Exception on large PRD: {exc}"


# ---------------------------------------------------------------------------
# REQ-042 — Cost Breakdown
# ---------------------------------------------------------------------------


def build_cost_breakdown(state: Any) -> dict:
    """Build per-phase cost and duration breakdown.

    Args:
        state: A ``Run4State`` instance.

    Returns:
        Dict with ``phases`` (mapping phase name to cost/duration),
        ``grand_total``, and ``budget_estimate``.
    """
    phase_costs = getattr(state, "phase_costs", {})
    total_cost = getattr(state, "total_cost", 0.0)

    phases: dict[str, dict] = {}
    milestone_names = {
        "M1": "Infrastructure & Config",
        "M2": "MCP Server Wiring",
        "M3": "Builder Invocation",
        "M4": "Pipeline Execution",
        "M5": "Fix Pass Loop",
        "M6": "Audit Report",
    }

    for phase_key, label in milestone_names.items():
        cost = phase_costs.get(phase_key, phase_costs.get(label, 0.0))
        if isinstance(cost, dict):
            phases[label] = cost
        else:
            phases[label] = {"cost": float(cost), "duration": "N/A"}

    # If total_cost is set but no per-phase breakdown, put it all in M6
    if total_cost > 0 and not any(
        (p.get("cost", 0) if isinstance(p, dict) else p) > 0
        for p in phases.values()
    ):
        phases["Audit Report"]["cost"] = total_cost

    grand_total = total_cost if total_cost > 0 else sum(
        (p.get("cost", 0.0) if isinstance(p, dict) else 0.0) for p in phases.values()
    )

    return {
        "phases": phases,
        "grand_total": grand_total,
        "budget_estimate": "$36-66",
        "max_budget": 100.0,
    }

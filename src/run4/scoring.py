"""Scoring engine for Run 4 verification results.

Implements the 3-tier scoring model:

1. **SystemScore** (per-build) -- 6 categories summing to 100:
   - functional_completeness  0-30
   - test_health              0-20
   - contract_compliance      0-20
   - code_quality             0-15
   - docker_health            0-10
   - documentation            0-5

2. **IntegrationScore** -- 4 categories each 0-25, summing to 100:
   - mcp_connectivity
   - data_flow_integrity
   - contract_fidelity
   - pipeline_completion

3. **AggregateScore** -- weighted combination:
   build1 * 0.30 + build2 * 0.25 + build3 * 0.25 + integration * 0.20

Plus **THRESHOLDS** and **is_good_enough()** for "good enough" evaluation.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Traffic-light classification
# ---------------------------------------------------------------------------

def _traffic_light(score: float) -> str:
    """Classify a 0-100 score into GREEN / YELLOW / RED."""
    if score >= 80:
        return "GREEN"
    if score >= 50:
        return "YELLOW"
    return "RED"


# ---------------------------------------------------------------------------
# SystemScore  (REQ-034)
# ---------------------------------------------------------------------------

@dataclass
class SystemScore:
    """Per-system scoring breakdown (Build 1, Build 2, or Build 3).

    Each category has a fixed maximum contributing to a total of 100:
      functional_completeness  0-30
      test_health              0-20
      contract_compliance      0-20
      code_quality             0-15
      docker_health            0-10
      documentation            0-5

    Attributes:
        system_name: Human label, e.g. "Build 1".
        functional_completeness: REQ pass rate * 30.
        test_health: Test pass rate * 20.
        contract_compliance: Schema validation pass rate * 20.
        code_quality: max(0, 15 - violation_density * 1.5).
        docker_health: Health-check pass rate * 10.
        documentation: artifacts_present / artifacts_required * 5.
        total: Sum of all categories (0-100).
        traffic_light: GREEN (>=80), YELLOW (>=50), RED (<50).
    """

    system_name: str = ""
    functional_completeness: float = 0.0
    test_health: float = 0.0
    contract_compliance: float = 0.0
    code_quality: float = 0.0
    docker_health: float = 0.0
    documentation: float = 0.0
    total: float = 0.0
    traffic_light: str = "RED"


def compute_system_score(
    system_name: str,
    req_pass_rate: float,
    test_pass_rate: float,
    contract_pass_rate: float,
    total_violations: int,
    total_loc: int,
    health_check_rate: float,
    artifacts_present: int,
    artifacts_required: int = 5,
) -> SystemScore:
    """Compute a per-system score across all 6 categories.

    Formula (REQ-034)::

        score = (req_pass_rate * 30)
              + (test_pass_rate * 20)
              + (contract_pass_rate * 20)
              + max(0, 15 - violation_density * 1.5)
              + (health_check_rate * 10)
              + (artifacts_present / artifacts_required * 5)

    Where ``violation_density = total_violations / (total_loc / 1000)``.

    Args:
        system_name: Human label ("Build 1", "Build 2", "Build 3").
        req_pass_rate: 0.0-1.0 fraction of requirements passing.
        test_pass_rate: 0.0-1.0 fraction of tests passing.
        contract_pass_rate: 0.0-1.0 fraction of contract validations passing.
        total_violations: Absolute count of code-quality violations.
        total_loc: Lines of code (.py files, excluding tests/__pycache__/venv).
        health_check_rate: 0.0-1.0 fraction of /health endpoints passing.
        artifacts_present: Number of required artifacts found.
        artifacts_required: Total expected artifacts (default 5:
            Dockerfile, requirements.txt/pyproject.toml, README.md,
            OpenAPI/AsyncAPI spec, /health endpoint).

    Returns:
        Populated ``SystemScore`` with all categories and traffic light.
    """
    # Clamp rates to [0, 1]
    req_pass_rate = max(0.0, min(1.0, req_pass_rate))
    test_pass_rate = max(0.0, min(1.0, test_pass_rate))
    contract_pass_rate = max(0.0, min(1.0, contract_pass_rate))
    health_check_rate = max(0.0, min(1.0, health_check_rate))

    # Category 1: functional_completeness (0-30)
    functional_completeness = req_pass_rate * 30.0

    # Category 2: test_health (0-20)
    test_health = test_pass_rate * 20.0

    # Category 3: contract_compliance (0-20)
    contract_compliance = contract_pass_rate * 20.0

    # Category 4: code_quality (0-15)
    if total_loc > 0:
        violation_density = total_violations / (total_loc / 1000.0)
    else:
        # No code => no violations possible => perfect quality
        violation_density = 0.0
    code_quality = max(0.0, 15.0 - violation_density * 1.5)

    # Category 5: docker_health (0-10)
    docker_health = health_check_rate * 10.0

    # Category 6: documentation (0-5)
    if artifacts_required > 0:
        documentation = (min(artifacts_present, artifacts_required)
                         / artifacts_required) * 5.0
    else:
        documentation = 5.0

    total = (functional_completeness + test_health + contract_compliance
             + code_quality + docker_health + documentation)
    # Clamp to [0, 100]
    total = max(0.0, min(100.0, total))

    score = SystemScore(
        system_name=system_name,
        functional_completeness=round(functional_completeness, 2),
        test_health=round(test_health, 2),
        contract_compliance=round(contract_compliance, 2),
        code_quality=round(code_quality, 2),
        docker_health=round(docker_health, 2),
        documentation=round(documentation, 2),
        total=round(total, 2),
        traffic_light=_traffic_light(total),
    )
    logger.info(
        "SystemScore[%s]: total=%.1f traffic_light=%s",
        system_name, score.total, score.traffic_light,
    )
    return score


# ---------------------------------------------------------------------------
# IntegrationScore  (REQ-035)
# ---------------------------------------------------------------------------

@dataclass
class IntegrationScore:
    """Cross-build integration scoring.

    4 categories, each 0-25, summing to 100:
      mcp_connectivity     -- MCP tool coverage
      data_flow_integrity  -- E2E data flow pass rate
      contract_fidelity    -- Cross-build contract compliance
      pipeline_completion  -- Pipeline phase completion rate

    Attributes:
        mcp_connectivity: mcp_tools_ok / 20 * 25.
        data_flow_integrity: flows_passing / flows_total * 25.
        contract_fidelity: max(0, 25 - cross_build_violations * 2.5).
        pipeline_completion: phases_complete / phases_total * 25.
        total: Sum of all categories (0-100).
        traffic_light: GREEN (>=80), YELLOW (>=50), RED (<50).
    """

    mcp_connectivity: float = 0.0
    data_flow_integrity: float = 0.0
    contract_fidelity: float = 0.0
    pipeline_completion: float = 0.0
    total: float = 0.0
    traffic_light: str = "RED"


def compute_integration_score(
    mcp_tools_ok: int,
    flows_passing: int,
    flows_total: int,
    cross_build_violations: int,
    phases_complete: int,
    phases_total: int,
) -> IntegrationScore:
    """Compute the integration score across 4 categories.

    Formula (REQ-035)::

        score = (mcp_tools_ok / 20 * 25)
              + (flows_passing / flows_total * 25)
              + max(0, 25 - cross_build_violations * 2.5)
              + (phases_complete / phases_total * 25)

    Args:
        mcp_tools_ok: Number of MCP tools responding correctly (out of 20).
        flows_passing: Number of E2E data flows passing.
        flows_total: Total number of data flows (typically 5).
        cross_build_violations: Detected contract violations between builds.
        phases_complete: Pipeline phases completed.
        phases_total: Total pipeline phases.

    Returns:
        Populated ``IntegrationScore``.
    """
    # Category 1: mcp_connectivity (0-25)
    mcp_connectivity = min(mcp_tools_ok, 20) / 20.0 * 25.0

    # Category 2: data_flow_integrity (0-25)
    if flows_total > 0:
        data_flow_integrity = min(flows_passing, flows_total) / flows_total * 25.0
    else:
        data_flow_integrity = 25.0

    # Category 3: contract_fidelity (0-25)
    contract_fidelity = max(0.0, 25.0 - cross_build_violations * 2.5)

    # Category 4: pipeline_completion (0-25)
    if phases_total > 0:
        pipeline_completion = min(phases_complete, phases_total) / phases_total * 25.0
    else:
        pipeline_completion = 25.0

    total = (mcp_connectivity + data_flow_integrity
             + contract_fidelity + pipeline_completion)
    total = max(0.0, min(100.0, total))

    iscore = IntegrationScore(
        mcp_connectivity=round(mcp_connectivity, 2),
        data_flow_integrity=round(data_flow_integrity, 2),
        contract_fidelity=round(contract_fidelity, 2),
        pipeline_completion=round(pipeline_completion, 2),
        total=round(total, 2),
        traffic_light=_traffic_light(total),
    )
    logger.info(
        "IntegrationScore: total=%.1f traffic_light=%s",
        iscore.total, iscore.traffic_light,
    )
    return iscore


# ---------------------------------------------------------------------------
# AggregateScore  (REQ-036)
# ---------------------------------------------------------------------------

@dataclass
class AggregateScore:
    """Weighted aggregate of per-system and integration scores.

    Formula::

        aggregate = build1 * 0.30
                  + build2 * 0.25
                  + build3 * 0.25
                  + integration * 0.20

    Attributes:
        build1: SystemScore.total for Build 1.
        build2: SystemScore.total for Build 2.
        build3: SystemScore.total for Build 3.
        integration: IntegrationScore.total.
        aggregate: Final weighted score (0-100).
        traffic_light: GREEN (>=80), YELLOW (>=50), RED (<50).
    """

    build1: float = 0.0
    build2: float = 0.0
    build3: float = 0.0
    integration: float = 0.0
    aggregate: float = 0.0
    traffic_light: str = "RED"


def compute_aggregate(
    build1_score: float,
    build2_score: float,
    build3_score: float,
    integration_score: float,
) -> AggregateScore:
    """Compute the weighted aggregate score.

    Formula (REQ-036)::

        aggregate = build1 * 0.30
                  + build2 * 0.25
                  + build3 * 0.25
                  + integration * 0.20

    Args:
        build1_score: SystemScore.total for Build 1 (0-100).
        build2_score: SystemScore.total for Build 2 (0-100).
        build3_score: SystemScore.total for Build 3 (0-100).
        integration_score: IntegrationScore.total (0-100).

    Returns:
        Populated ``AggregateScore``.
    """
    aggregate = (
        build1_score * 0.30
        + build2_score * 0.25
        + build3_score * 0.25
        + integration_score * 0.20
    )
    aggregate = max(0.0, min(100.0, aggregate))

    agg = AggregateScore(
        build1=round(build1_score, 2),
        build2=round(build2_score, 2),
        build3=round(build3_score, 2),
        integration=round(integration_score, 2),
        aggregate=round(aggregate, 2),
        traffic_light=_traffic_light(aggregate),
    )
    logger.info(
        "AggregateScore: %.1f (B1=%.1f B2=%.1f B3=%.1f Int=%.1f) => %s",
        agg.aggregate, agg.build1, agg.build2, agg.build3,
        agg.integration, agg.traffic_light,
    )
    return agg


# ---------------------------------------------------------------------------
# THRESHOLDS and is_good_enough()  (TECH-009)
# ---------------------------------------------------------------------------

THRESHOLDS: dict[str, float | int] = {
    "per_system_minimum": 60,
    "integration_minimum": 50,
    "aggregate_minimum": 65,
    "p0_remaining_max": 0,
    "p1_remaining_max": 3,
    "test_pass_rate_min": 0.85,
    "mcp_tool_coverage_min": 0.90,
    "fix_convergence_min": 0.70,
}
"""Minimum thresholds for the "good enough" gate.

- per_system_minimum: Each Build must score >= 60.
- integration_minimum: Integration score must be >= 50.
- aggregate_minimum: Final weighted aggregate must be >= 65.
- p0_remaining_max: No P0 defects allowed (hard requirement).
- p1_remaining_max: At most 3 P1 defects allowed.
- test_pass_rate_min: Overall test pass rate >= 85%.
- mcp_tool_coverage_min: MCP tool coverage >= 90%.
- fix_convergence_min: Fix convergence ratio >= 70%.
"""


def is_good_enough(
    aggregate: AggregateScore,
    p0_count: int,
    p1_count: int,
    test_pass_rate: float,
    mcp_coverage: float,
    convergence: float,
) -> tuple[bool, list[str]]:
    """Evaluate whether the system meets all "good enough" thresholds.

    Checks 10 conditions derived from THRESHOLDS.  Returns a tuple of
    ``(passed, failures)`` where *failures* is a list of human-readable
    strings describing each violated threshold.

    Args:
        aggregate: Computed ``AggregateScore`` (contains per-build and
            integration totals).
        p0_count: Remaining P0 defect count.
        p1_count: Remaining P1 defect count.
        test_pass_rate: Overall test pass rate (0.0-1.0).
        mcp_coverage: MCP tool coverage fraction (0.0-1.0).
        convergence: Fix convergence ratio (0.0-1.0).

    Returns:
        ``(True, [])`` if all thresholds pass, otherwise
        ``(False, ["Failure description", ...])``.
    """
    failures: list[str] = []

    # P0 hard requirement
    if p0_count > THRESHOLDS["p0_remaining_max"]:
        failures.append(
            f"P0 defects remaining: {p0_count} "
            f"(max {THRESHOLDS['p0_remaining_max']})"
        )

    # P1 limit
    if p1_count > THRESHOLDS["p1_remaining_max"]:
        failures.append(
            f"P1 defects remaining: {p1_count} "
            f"(max {THRESHOLDS['p1_remaining_max']})"
        )

    # Test pass rate
    if test_pass_rate < THRESHOLDS["test_pass_rate_min"]:
        failures.append(
            f"Test pass rate {test_pass_rate:.2%} "
            f"< {THRESHOLDS['test_pass_rate_min']:.0%}"
        )

    # MCP tool coverage
    if mcp_coverage < THRESHOLDS["mcp_tool_coverage_min"]:
        failures.append(
            f"MCP tool coverage {mcp_coverage:.2%} "
            f"< {THRESHOLDS['mcp_tool_coverage_min']:.0%}"
        )

    # Fix convergence
    if convergence < THRESHOLDS["fix_convergence_min"]:
        failures.append(
            f"Fix convergence {convergence:.2%} "
            f"< {THRESHOLDS['fix_convergence_min']:.0%}"
        )

    # Per-system minimums
    if aggregate.build1 < THRESHOLDS["per_system_minimum"]:
        failures.append(
            f"Build 1 score {aggregate.build1:.1f} "
            f"< {THRESHOLDS['per_system_minimum']}"
        )
    if aggregate.build2 < THRESHOLDS["per_system_minimum"]:
        failures.append(
            f"Build 2 score {aggregate.build2:.1f} "
            f"< {THRESHOLDS['per_system_minimum']}"
        )
    if aggregate.build3 < THRESHOLDS["per_system_minimum"]:
        failures.append(
            f"Build 3 score {aggregate.build3:.1f} "
            f"< {THRESHOLDS['per_system_minimum']}"
        )

    # Integration minimum
    if aggregate.integration < THRESHOLDS["integration_minimum"]:
        failures.append(
            f"Integration score {aggregate.integration:.1f} "
            f"< {THRESHOLDS['integration_minimum']}"
        )

    # Aggregate minimum
    if aggregate.aggregate < THRESHOLDS["aggregate_minimum"]:
        failures.append(
            f"Aggregate score {aggregate.aggregate:.1f} "
            f"< {THRESHOLDS['aggregate_minimum']}"
        )

    passed = len(failures) == 0
    if passed:
        logger.info("is_good_enough: PASSED (all %d thresholds met)",
                     len(THRESHOLDS))
    else:
        logger.warning("is_good_enough: FAILED (%d/%d thresholds violated)",
                       len(failures), len(THRESHOLDS) + 2)  # +2 for per-build split
    return passed, failures


# ---------------------------------------------------------------------------
# Backward-compatible compute_scores()  (original stub contract)
# ---------------------------------------------------------------------------

def compute_scores(findings: list, weights: dict | None = None) -> dict[str, float]:
    """Compute category scores from a list of findings.

    This is the original stub interface preserved for backward compatibility.
    It groups findings by their ``system`` attribute and computes a simplified
    score per system based on the fraction of resolved findings.

    Args:
        findings: List of Finding dataclass instances (from
            ``src.run4.state.Finding``).
        weights: Optional category weight overrides (currently unused;
            reserved for future customisation).

    Returns:
        Mapping of system name to score (0.0-1.0), where 1.0 means
        all findings resolved.
    """
    if not findings:
        return {}

    # Group by system
    by_system: dict[str, list] = {}
    for f in findings:
        system = getattr(f, "system", "unknown")
        by_system.setdefault(system, []).append(f)

    scores: dict[str, float] = {}
    for system, system_findings in by_system.items():
        total = len(system_findings)
        resolved = sum(
            1 for f in system_findings
            if getattr(f, "resolution", "OPEN") == "FIXED"
        )
        scores[system] = resolved / total if total > 0 else 0.0

    logger.info("compute_scores: %d systems scored", len(scores))
    return scores

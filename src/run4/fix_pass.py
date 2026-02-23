"""Fix-pass orchestration for Run 4 (Milestone 5).

Implements the 6-step fix cycle: DISCOVER, CLASSIFY, GENERATE, APPLY, VERIFY, REGRESS.
Includes priority classification (P0-P3), regression detection, violation snapshots,
fix pass metrics computation, and convergence checking.

Functions:
    take_violation_snapshot: Create a snapshot from scan results or findings.
    detect_regressions: Compare before/after snapshots to find regressions.
    classify_priority: Classify a violation into P0-P3 priority.
    compute_fix_pass_metrics: Compute effectiveness, regression rate, etc.
    compute_convergence: Compute convergence score from remaining findings.
    check_convergence: Check all hard/soft stop conditions.
    execute_fix_pass: Execute a single 6-step fix pass cycle.
"""

from __future__ import annotations

import logging
import time
from dataclasses import asdict, dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Violation snapshot (TECH-008)
# ---------------------------------------------------------------------------


def take_violation_snapshot(scan_results: Any) -> dict[str, list[str]]:
    """Create a violation snapshot from scan results or findings.

    Converts raw scan results into a normalised snapshot mapping each
    scan code to the list of file paths where violations were found.
    The snapshot is intended to be saved as JSON before and after each
    fix pass so that ``detect_regressions`` can compare them.

    Args:
        scan_results: Raw scan output.  Accepted formats:

            * **Flat list of dicts** -- each dict must have ``scan_code``
              and ``file_path`` keys.

            * **Pre-grouped dict** -- keys are scan codes, values are
              lists of file paths (already in snapshot format).

            * **Dict with a ``violations`` key** -- the value is treated
              as a flat list of dicts.

            * **List of Finding dataclass instances** -- uses ``system``
              as category and ``finding_id`` as identifier.

    Returns:
        Mapping of ``{scan_code: [file_path1, file_path2, ...]}``
        suitable for JSON serialisation and later comparison.
    """
    snapshot: dict[str, list[str]] = {}

    # Handle dict with a "violations" key wrapping a list.
    if isinstance(scan_results, dict) and "violations" in scan_results:
        scan_results = scan_results["violations"]

    if isinstance(scan_results, list):
        for item in scan_results:
            if isinstance(item, dict):
                code = item.get("scan_code", "")
                path = item.get("file_path", "")
                if code:
                    snapshot.setdefault(code, []).append(path)
            elif hasattr(item, "system"):
                # Finding dataclass instance
                category = getattr(item, "system", "unknown")
                finding_id = getattr(item, "finding_id", "unknown")
                resolution = getattr(item, "resolution", "OPEN")
                if resolution == "OPEN":
                    snapshot.setdefault(category, []).append(finding_id)
    elif isinstance(scan_results, dict):
        for code, paths in scan_results.items():
            if isinstance(paths, list):
                snapshot[code] = list(paths)
            else:
                snapshot[code] = [str(paths)]
    else:
        logger.warning(
            "take_violation_snapshot received unsupported type: %s",
            type(scan_results).__name__,
        )

    logger.debug(
        "Violation snapshot: %d scan codes, %d total paths",
        len(snapshot),
        sum(len(v) for v in snapshot.values()),
    )
    return snapshot


# ---------------------------------------------------------------------------
# Regression detection (TECH-008)
# ---------------------------------------------------------------------------


def detect_regressions(
    before: dict[str, list[str]],
    after: dict[str, list[str]],
) -> list[dict]:
    """Compare violation snapshots and return regressed violations.

    A regression is a violation that appears in *after* but was not
    present in *before*, or was previously fixed but reappeared.

    Args:
        before: Mapping of scan_code to list of file paths
                from the previous snapshot.
        after: Mapping of scan_code to list of file paths
               from the current snapshot.

    Returns:
        List of dicts with keys:
            - ``scan_code``: the scan category code
            - ``file_path``: the file where the violation was found
            - ``type``: ``"new"`` if the scan_code is entirely new,
              ``"reappeared"`` if the scan_code existed in *before*.
    """
    regressions: list[dict] = []

    for scan_code, after_paths in after.items():
        before_paths = set(before.get(scan_code, []))

        for file_path in after_paths:
            if file_path not in before_paths:
                regression_type = "reappeared" if scan_code in before else "new"
                regressions.append({
                    "scan_code": scan_code,
                    "file_path": file_path,
                    "type": regression_type,
                })

    if regressions:
        logger.warning("Detected %d regressions across scan codes", len(regressions))
    else:
        logger.info("No regressions detected")

    return regressions


# ---------------------------------------------------------------------------
# Priority classification (REQ-032)
# ---------------------------------------------------------------------------


def classify_priority(
    violation: dict[str, Any],
    graph_rag_client: Any | None = None,
) -> str:
    """Classify a violation into P0-P3 priority using a decision tree.

    Decision tree:
        P0: system cannot start (build failure, container crash, missing entrypoint)
        P1: primary use case fails (API endpoint error, auth broken, critical test fail)
        P2: secondary feature broken (non-critical test failure, docs gaps)
        P3: cosmetic (style issues, naming conventions, minor warnings)

    Args:
        violation: Dict with keys like ``severity``, ``category``, ``message``,
                   ``code``, ``type``, ``component``.
        graph_rag_client: Optional Graph RAG client for cross-service impact
                          analysis.  When provided (and the classified priority
                          is not already P0), high-impact nodes may be promoted.

    Returns:
        Priority string: ``"P0"``, ``"P1"``, ``"P2"``, or ``"P3"``.
    """
    severity = str(violation.get("severity", "")).lower()
    category = str(violation.get("category", "")).lower()
    message = str(violation.get("message", "")).lower()

    # P0: system cannot start
    p0_keywords = [
        "cannot start", "build fail", "container crash", "missing entrypoint",
        "fatal", "startup fail", "compose fail", "docker fail", "import error",
        "module not found", "syntax error", "crash", "segfault", "oom",
    ]
    if severity in ("critical", "fatal", "blocker"):
        classified_priority = "P0"
    elif any(kw in message for kw in p0_keywords):
        classified_priority = "P0"
    elif category in ("build", "startup", "infrastructure") and severity == "error":
        classified_priority = "P0"

    # P1: primary use case fails
    elif severity == "error":
        classified_priority = "P1"
    elif any(kw in message for kw in [
        "primary", "endpoint fail", "auth broken", "test fail", "api error",
        "500 error", "connection refused", "timeout", "data loss",
        "contract violation", "breaking change",
    ]):
        classified_priority = "P1"
    elif category in ("test", "api", "contract", "security"):
        classified_priority = "P1"

    # P2: secondary feature broken
    elif severity == "warning":
        classified_priority = "P2"
    elif any(kw in message for kw in [
        "secondary", "non-critical", "minor", "documentation",
        "incomplete", "missing test", "coverage",
    ]):
        classified_priority = "P2"
    elif category in ("documentation", "coverage", "performance"):
        classified_priority = "P2"

    # P3: cosmetic
    elif severity in ("info", "style", "hint"):
        classified_priority = "P3"
    elif category in ("style", "naming", "formatting"):
        classified_priority = "P3"

    else:
        # Default: P2 for unknown
        classified_priority = "P2"

    # Graph RAG cross-service impact promotion
    if graph_rag_client is not None and classified_priority not in ("P0",):
        try:
            import asyncio
            node_id = violation.get("file_path", "") or violation.get("component", "")
            if node_id:
                result = asyncio.get_event_loop().run_until_complete(
                    graph_rag_client.find_cross_service_impact(
                        node_id=node_id, max_depth=2
                    )
                )
                impact_count = result.get("total_impacted_nodes", 0)
                if impact_count >= 10:
                    classified_priority = "P0"
                elif impact_count >= 3 and classified_priority > "P1":
                    classified_priority = "P1"
        except Exception:
            pass  # Non-blocking

    return classified_priority


# ---------------------------------------------------------------------------
# Fix pass metrics (REQ-032)
# ---------------------------------------------------------------------------


@dataclass
class FixPassMetrics:
    """Metrics computed after a fix pass completes."""

    fix_effectiveness: float = 0.0
    regression_rate: float = 0.0
    new_defect_discovery_rate: float = 0.0
    score_delta: float = 0.0
    fixed_count: int = 0
    regression_count: int = 0
    new_defect_count: int = 0
    total_before: int = 0
    total_after: int = 0


def compute_fix_pass_metrics(
    findings_before: list[Any],
    findings_after: list[Any],
    regressions: list[dict],
    score_before: float = 0.0,
    score_after: float = 0.0,
) -> FixPassMetrics:
    """Compute fix pass effectiveness metrics.

    Args:
        findings_before: Findings list before the fix pass.
        findings_after: Findings list after the fix pass.
        regressions: List of detected regressions.
        score_before: Aggregate score before fix pass.
        score_after: Aggregate score after fix pass.

    Returns:
        FixPassMetrics with computed values.
    """

    def _count_open(findings: list) -> int:
        count = 0
        for f in findings:
            if hasattr(f, "resolution"):
                res = f.resolution
            elif isinstance(f, dict):
                res = f.get("resolution", "OPEN")
            else:
                res = "OPEN"
            if res == "OPEN":
                count += 1
        return count

    open_before = _count_open(findings_before)
    open_after = _count_open(findings_after)

    fixed_count = max(0, open_before - open_after + len(regressions))
    fix_effectiveness = fixed_count / open_before if open_before > 0 else 0.0

    total_after = len(findings_after)
    regression_rate = len(regressions) / total_after if total_after > 0 else 0.0

    new_defect_count = max(0, len(findings_after) - len(findings_before))
    new_defect_discovery_rate = (
        new_defect_count / len(findings_before) if len(findings_before) > 0 else 0.0
    )

    return FixPassMetrics(
        fix_effectiveness=fix_effectiveness,
        regression_rate=regression_rate,
        new_defect_discovery_rate=new_defect_discovery_rate,
        score_delta=score_after - score_before,
        fixed_count=fixed_count,
        regression_count=len(regressions),
        new_defect_count=new_defect_count,
        total_before=len(findings_before),
        total_after=total_after,
    )


# ---------------------------------------------------------------------------
# Convergence computation (TECH-007)
# ---------------------------------------------------------------------------


def compute_convergence(
    remaining_p0: int,
    remaining_p1: int,
    remaining_p2: int,
    initial_total_weighted: float,
) -> float:
    """Compute convergence score.

    Formula::

        1.0 - (remaining_p0 * 0.4 + remaining_p1 * 0.3 + remaining_p2 * 0.1)
              / initial_total_weighted

    Convergence threshold: >= 0.85 indicates convergence.

    Args:
        remaining_p0: Count of remaining P0 findings.
        remaining_p1: Count of remaining P1 findings.
        remaining_p2: Count of remaining P2 findings.
        initial_total_weighted: Initial weighted total
            (initial_p0 * 0.4 + initial_p1 * 0.3 + initial_p2 * 0.1).

    Returns:
        Convergence score between 0.0 and 1.0.
    """
    if initial_total_weighted <= 0:
        return 1.0

    remaining_weighted = (
        remaining_p0 * 0.4 + remaining_p1 * 0.3 + remaining_p2 * 0.1
    )
    convergence = 1.0 - remaining_weighted / initial_total_weighted
    return max(0.0, min(1.0, convergence))


# ---------------------------------------------------------------------------
# Convergence check / hard stop (REQ-033)
# ---------------------------------------------------------------------------


@dataclass
class ConvergenceResult:
    """Result of a convergence check."""

    should_stop: bool = False
    reason: str = ""
    convergence_score: float = 0.0
    is_hard_stop: bool = False
    is_soft_convergence: bool = False


def _get_new_defects(result: Any) -> int:
    """Extract new defect count from a FixPassResult.

    Checks ``new_defects`` attribute first, then falls back to
    ``metrics.new_defect_count``.

    Args:
        result: A FixPassResult (or similar) instance.

    Returns:
        Integer count of new defects discovered in the pass.
    """
    if hasattr(result, "new_defects"):
        return int(result.new_defects)
    metrics = getattr(result, "metrics", None)
    if metrics is not None:
        return int(getattr(metrics, "new_defect_count", 0))
    return 0


def check_convergence(
    remaining_p0: int,
    remaining_p1: int,
    remaining_p2: int,
    initial_total_weighted: float,
    current_pass: int,
    max_fix_passes: int = 5,
    budget_remaining: float = 100.0,
    fix_effectiveness: float = 1.0,
    regression_rate: float = 0.0,
    fix_effectiveness_floor: float = 0.30,
    regression_rate_ceiling: float = 0.25,
    convergence_threshold: float = 0.85,
    results: list[Any] | None = None,
    aggregate_score: float = 0.0,
) -> ConvergenceResult:
    """Check all convergence and hard stop conditions.

    Hard stop triggers (any one triggers immediate stop):
        1. P0 == 0 AND P1 == 0 (all critical issues resolved)
        2. current_pass >= max_fix_passes
        3. budget_remaining <= 0 (budget exhausted)
        4. fix_effectiveness < fix_effectiveness_floor (< 30%)
        5. regression_rate > regression_rate_ceiling (> 25%)

    Soft convergence (either condition triggers):
        A. compute_convergence() >= convergence_threshold (0.85)
        B. PRD REQ-033 four-condition check (all must be true):
           - P0 count == 0
           - P1 count <= 2
           - Last 2 passes each produced < 3 new defects
           - Aggregate score >= 70

    Args:
        remaining_p0: Count of remaining P0 findings.
        remaining_p1: Count of remaining P1 findings.
        remaining_p2: Count of remaining P2 findings.
        initial_total_weighted: Initial weighted total for convergence formula.
        current_pass: Current fix pass number (1-based).
        max_fix_passes: Maximum allowed fix passes.
        budget_remaining: Remaining budget in USD.
        fix_effectiveness: Current fix pass effectiveness (0.0-1.0).
        regression_rate: Current regression rate (0.0-1.0).
        fix_effectiveness_floor: Minimum acceptable effectiveness.
        regression_rate_ceiling: Maximum acceptable regression rate.
        convergence_threshold: Convergence score threshold for soft stop.
        results: List of FixPassResult objects from prior passes (for
            REQ-033 soft convergence check).  ``None`` skips the check.
        aggregate_score: Current aggregate system score (0-100) for
            REQ-033 soft convergence check.

    Returns:
        ConvergenceResult with stop decision and reason.
    """
    convergence_score = compute_convergence(
        remaining_p0, remaining_p1, remaining_p2, initial_total_weighted
    )

    # Hard stop 1: All critical issues resolved
    if remaining_p0 == 0 and remaining_p1 == 0:
        return ConvergenceResult(
            should_stop=True,
            reason="All P0 and P1 issues resolved",
            convergence_score=convergence_score,
            is_hard_stop=True,
        )

    # Hard stop 2: Max fix passes reached
    if current_pass >= max_fix_passes:
        return ConvergenceResult(
            should_stop=True,
            reason=f"Max fix passes reached ({max_fix_passes})",
            convergence_score=convergence_score,
            is_hard_stop=True,
        )

    # Hard stop 3: Budget exhausted
    if budget_remaining <= 0:
        return ConvergenceResult(
            should_stop=True,
            reason="Budget exhausted",
            convergence_score=convergence_score,
            is_hard_stop=True,
        )

    # Hard stop 4: Effectiveness below floor (only after first pass)
    if current_pass > 1 and fix_effectiveness < fix_effectiveness_floor:
        return ConvergenceResult(
            should_stop=True,
            reason=(
                f"Fix effectiveness {fix_effectiveness:.1%} below "
                f"floor {fix_effectiveness_floor:.1%}"
            ),
            convergence_score=convergence_score,
            is_hard_stop=True,
        )

    # Hard stop 5: Regression rate above ceiling
    if regression_rate > regression_rate_ceiling:
        return ConvergenceResult(
            should_stop=True,
            reason=(
                f"Regression rate {regression_rate:.1%} above "
                f"ceiling {regression_rate_ceiling:.1%}"
            ),
            convergence_score=convergence_score,
            is_hard_stop=True,
        )

    # Soft convergence: convergence score threshold
    if convergence_score >= convergence_threshold:
        return ConvergenceResult(
            should_stop=True,
            reason=(
                f"Convergence {convergence_score:.3f} >= "
                f"threshold {convergence_threshold}"
            ),
            convergence_score=convergence_score,
            is_soft_convergence=True,
        )

    # Soft convergence: PRD-specified 4-condition check (REQ-033)
    if results is not None and len(results) >= 2:
        last_new = _get_new_defects(results[-1])
        prev_new = _get_new_defects(results[-2])
        soft = (
            remaining_p0 == 0
            and remaining_p1 <= 2
            and last_new < 3
            and prev_new < 3
            and aggregate_score >= 70
        )
        if soft:
            return ConvergenceResult(
                should_stop=True,
                reason=(
                    f"Soft convergence: P0=0, P1={remaining_p1}<=2, "
                    f"new_defects<3 for last 2 passes, "
                    f"aggregate={aggregate_score:.1f}>=70"
                ),
                convergence_score=convergence_score,
                is_soft_convergence=True,
            )

    # Continue fixing
    return ConvergenceResult(
        should_stop=False,
        reason="Convergence not yet reached",
        convergence_score=convergence_score,
    )


# ---------------------------------------------------------------------------
# FixPassResult dataclass
# ---------------------------------------------------------------------------


@dataclass
class FixPassResult:
    """Result of a single fix pass cycle.

    Tracks the 6-step cycle: DISCOVER, CLASSIFY, GENERATE, APPLY, VERIFY, REGRESS.
    """

    pass_number: int = 0
    status: str = "pending"
    steps_completed: list[str] = field(default_factory=list)

    # DISCOVER
    violations_discovered: int = 0

    # CLASSIFY
    p0_count: int = 0
    p1_count: int = 0
    p2_count: int = 0
    p3_count: int = 0

    # GENERATE + APPLY
    fixes_generated: int = 0
    fixes_applied: int = 0

    # VERIFY
    fixes_verified: int = 0

    # REGRESS
    regressions_found: int = 0

    # Metrics
    metrics: FixPassMetrics = field(default_factory=FixPassMetrics)
    convergence: ConvergenceResult = field(default_factory=ConvergenceResult)

    # Cost & timing
    cost_usd: float = 0.0
    duration_s: float = 0.0

    # Snapshots
    snapshot_before: dict[str, list[str]] = field(default_factory=dict)
    snapshot_after: dict[str, list[str]] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a plain dict for JSON storage."""
        return asdict(self)


# ---------------------------------------------------------------------------
# Fix pass execution (REQ-032)
# ---------------------------------------------------------------------------


async def execute_fix_pass(
    state: Any,
    config: Any,
    pass_number: int,
    builder_fn: Any = None,
) -> FixPassResult:
    """Execute a single fix pass cycle.

    The 6-step cycle:
        1. DISCOVER: Take violation snapshot, count open findings.
        2. CLASSIFY: Classify each finding by P0-P3 priority.
        3. GENERATE: Generate fix instructions for the builder.
        4. APPLY: Invoke builder to apply fixes.
        5. VERIFY: Re-scan and verify fixes.
        6. REGRESS: Check for regressions.

    Args:
        state: Run4State instance.
        config: Run4Config instance.
        pass_number: Current fix pass number (1-based).
        builder_fn: Optional async callable(cwd, violations) for builder invocation.

    Returns:
        FixPassResult with all metrics and outcomes.
    """
    from src.run4.builder import feed_violations_to_builder

    result = FixPassResult(pass_number=pass_number, status="in_progress")
    start_time = time.monotonic()
    score_before = getattr(state, "aggregate_score", 0.0)

    # --- Step 1: DISCOVER ---
    findings_before = list(state.findings)
    snapshot_before = take_violation_snapshot(state.findings)
    result.snapshot_before = snapshot_before
    result.violations_discovered = sum(len(v) for v in snapshot_before.values())
    result.steps_completed.append("DISCOVER")

    # --- Step 2: CLASSIFY ---
    for finding in state.findings:
        if hasattr(finding, "resolution") and finding.resolution == "OPEN":
            priority = classify_priority({
                "severity": getattr(finding, "priority", ""),
                "category": getattr(finding, "system", ""),
                "message": getattr(finding, "evidence", ""),
            })
            if finding.priority not in ("P0", "P1", "P2", "P3"):
                finding.priority = priority

    result.p0_count = sum(
        1 for f in state.findings
        if getattr(f, "priority", "") == "P0"
        and getattr(f, "resolution", "") == "OPEN"
    )
    result.p1_count = sum(
        1 for f in state.findings
        if getattr(f, "priority", "") == "P1"
        and getattr(f, "resolution", "") == "OPEN"
    )
    result.p2_count = sum(
        1 for f in state.findings
        if getattr(f, "priority", "") == "P2"
        and getattr(f, "resolution", "") == "OPEN"
    )
    result.p3_count = sum(
        1 for f in state.findings
        if getattr(f, "priority", "") == "P3"
        and getattr(f, "resolution", "") == "OPEN"
    )
    result.steps_completed.append("CLASSIFY")

    # --- Step 3: GENERATE ---
    open_findings = [
        f for f in state.findings
        if getattr(f, "resolution", "OPEN") == "OPEN"
    ]
    violations_for_builder: list[dict[str, Any]] = []
    for f in open_findings:
        violations_for_builder.append({
            "code": getattr(f, "finding_id", ""),
            "priority": getattr(f, "priority", "P1"),
            "component": getattr(f, "component", ""),
            "evidence": getattr(f, "evidence", ""),
            "action": getattr(f, "recommendation", ""),
            "message": getattr(f, "evidence", ""),
        })
    result.fixes_generated = len(violations_for_builder)
    result.steps_completed.append("GENERATE")

    # --- Step 4: APPLY ---
    if violations_for_builder and builder_fn is not None:
        try:
            for root_attr in (
                "build1_project_root", "build2_project_root", "build3_project_root"
            ):
                cwd = getattr(config, root_attr, None)
                if cwd is not None:
                    await builder_fn(cwd, violations_for_builder)
            result.fixes_applied = len(violations_for_builder)
        except Exception as exc:
            logger.error("Builder invocation failed: %s", exc)
            result.fixes_applied = 0
    elif violations_for_builder:
        for root_attr in (
            "build1_project_root", "build2_project_root", "build3_project_root"
        ):
            cwd = getattr(config, root_attr, None)
            if cwd is not None:
                try:
                    await feed_violations_to_builder(
                        cwd,
                        violations_for_builder,
                        timeout_s=getattr(config, "builder_timeout_s", 600),
                    )
                except Exception as exc:
                    logger.error("Default builder failed for %s: %s", cwd, exc)
        result.fixes_applied = len(violations_for_builder)
    result.steps_completed.append("APPLY")

    # --- Step 5: VERIFY ---
    result.fixes_verified = sum(
        1 for f in state.findings
        if getattr(f, "resolution", "") == "FIXED"
        and getattr(f, "fix_pass_number", 0) == pass_number
    )
    result.steps_completed.append("VERIFY")

    # --- Step 6: REGRESS ---
    snapshot_after = take_violation_snapshot(state.findings)
    result.snapshot_after = snapshot_after
    regressions = detect_regressions(snapshot_before, snapshot_after)
    result.regressions_found = len(regressions)
    result.steps_completed.append("REGRESS")

    # Compute metrics
    score_after = getattr(state, "aggregate_score", 0.0)
    result.metrics = compute_fix_pass_metrics(
        findings_before=findings_before,
        findings_after=list(state.findings),
        regressions=regressions,
        score_before=score_before,
        score_after=score_after,
    )

    # Compute initial weighted total for convergence
    initial_p0 = sum(1 for f in findings_before if getattr(f, "priority", "") == "P0")
    initial_p1 = sum(1 for f in findings_before if getattr(f, "priority", "") == "P1")
    initial_p2 = sum(1 for f in findings_before if getattr(f, "priority", "") == "P2")
    initial_total_weighted = initial_p0 * 0.4 + initial_p1 * 0.3 + initial_p2 * 0.1

    result.convergence = check_convergence(
        remaining_p0=result.p0_count,
        remaining_p1=result.p1_count,
        remaining_p2=result.p2_count,
        initial_total_weighted=initial_total_weighted,
        current_pass=pass_number,
        max_fix_passes=getattr(config, "max_fix_passes", 5),
        budget_remaining=(
            getattr(config, "max_budget_usd", 100.0)
            - getattr(state, "total_cost", 0.0)
        ),
        fix_effectiveness=result.metrics.fix_effectiveness,
        regression_rate=result.metrics.regression_rate,
        fix_effectiveness_floor=getattr(config, "fix_effectiveness_floor", 0.30),
        regression_rate_ceiling=getattr(config, "regression_rate_ceiling", 0.25),
    )

    result.duration_s = time.monotonic() - start_time
    result.status = "completed"

    logger.info(
        "Fix pass %d completed: %d discovered, %d fixed, %d regressions, "
        "convergence=%.3f, should_stop=%s",
        pass_number,
        result.violations_discovered,
        result.fixes_verified,
        result.regressions_found,
        result.convergence.convergence_score,
        result.convergence.should_stop,
    )

    return result


# ---------------------------------------------------------------------------
# Fix loop orchestrator (REQ-033)
# ---------------------------------------------------------------------------


async def run_fix_loop(
    state: Any,
    config: Any,
    scan_fn: Any = None,
    fix_fn: Any = None,
) -> list[FixPassResult]:
    """Run the fix-pass convergence loop.

    Wraps :func:`execute_fix_pass` in a loop that checks convergence
    after each pass and stops when a hard or soft condition is met or
    when ``config.max_fix_passes`` is exhausted.

    Args:
        state: A ``Run4State`` instance.
        config: A ``Run4Config`` instance.
        scan_fn: Optional callable returning current violations
            (list of dicts or Finding objects).  Used to take the
            initial snapshot.  If ``None``, ``state.findings`` is used.
        fix_fn: Optional async callable ``(cwd, violations)`` passed
            as ``builder_fn`` to :func:`execute_fix_pass`.

    Returns:
        List of :class:`FixPassResult` objects, one per pass executed.
    """
    max_passes = getattr(config, "max_fix_passes", 5)
    results: list[FixPassResult] = []

    # Step 1: Take initial violation snapshot
    if scan_fn is not None:
        initial_scan = scan_fn()
    else:
        initial_scan = state.findings
    initial_snapshot = take_violation_snapshot(initial_scan)

    # Compute initial weighted totals for convergence scoring
    initial_p0 = sum(
        1 for f in state.findings
        if getattr(f, "priority", "") == "P0"
        and getattr(f, "resolution", "OPEN") == "OPEN"
    )
    initial_p1 = sum(
        1 for f in state.findings
        if getattr(f, "priority", "") == "P1"
        and getattr(f, "resolution", "OPEN") == "OPEN"
    )
    initial_p2 = sum(
        1 for f in state.findings
        if getattr(f, "priority", "") == "P2"
        and getattr(f, "resolution", "OPEN") == "OPEN"
    )
    initial_total_weighted = initial_p0 * 0.4 + initial_p1 * 0.3 + initial_p2 * 0.1

    logger.info(
        "Starting fix loop: max_passes=%d, initial_violations=%d, "
        "initial_weighted=%.2f (P0=%d, P1=%d, P2=%d)",
        max_passes,
        sum(len(v) for v in initial_snapshot.values()),
        initial_total_weighted,
        initial_p0,
        initial_p1,
        initial_p2,
    )

    # Step 2: Loop up to max_fix_passes
    for pass_number in range(1, max_passes + 1):
        findings_before = list(state.findings)

        # Execute a single fix pass
        fp_result = await execute_fix_pass(
            state=state,
            config=config,
            pass_number=pass_number,
            builder_fn=fix_fn,
        )

        # Compute metrics (before/after this pass)
        findings_after = list(state.findings)
        snapshot_after = take_violation_snapshot(state.findings)
        regressions = detect_regressions(initial_snapshot, snapshot_after)
        fp_result.metrics = compute_fix_pass_metrics(
            findings_before=findings_before,
            findings_after=findings_after,
            regressions=regressions,
            score_before=getattr(state, "aggregate_score", 0.0),
            score_after=getattr(state, "aggregate_score", 0.0),
        )

        results.append(fp_result)

        # Check convergence with the full results list for REQ-033
        convergence = check_convergence(
            remaining_p0=fp_result.p0_count,
            remaining_p1=fp_result.p1_count,
            remaining_p2=fp_result.p2_count,
            initial_total_weighted=initial_total_weighted,
            current_pass=pass_number,
            max_fix_passes=max_passes,
            budget_remaining=(
                getattr(config, "max_budget_usd", 100.0)
                - getattr(state, "total_cost", 0.0)
            ),
            fix_effectiveness=fp_result.metrics.fix_effectiveness,
            regression_rate=fp_result.metrics.regression_rate,
            fix_effectiveness_floor=getattr(config, "fix_effectiveness_floor", 0.30),
            regression_rate_ceiling=getattr(config, "regression_rate_ceiling", 0.25),
            results=results,
            aggregate_score=getattr(state, "aggregate_score", 0.0),
        )
        fp_result.convergence = convergence

        logger.info(
            "Fix loop pass %d/%d: should_stop=%s reason=%s",
            pass_number,
            max_passes,
            convergence.should_stop,
            convergence.reason,
        )

        if convergence.should_stop:
            break

        # Update initial snapshot for next iteration's regression detection
        initial_snapshot = snapshot_after

    logger.info(
        "Fix loop completed: %d passes executed, final_stop=%s",
        len(results),
        results[-1].convergence.reason if results else "no passes",
    )
    return results

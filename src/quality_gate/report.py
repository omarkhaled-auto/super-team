"""Quality gate report generator for Milestone 4 -- Quality Gate Verification.

Produces a Markdown report from a ``QualityGateReport`` dataclass.  The
report includes an overall summary, per-layer results table, violations
grouped by severity, and actionable recommendations.

This module contains only pure functions -- no I/O, no side effects.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass

from src.build3_shared.models import (
    GateVerdict,
    LayerResult,
    QualityGateReport,
    ScanViolation,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Verdict formatting helpers
# ---------------------------------------------------------------------------

_VERDICT_DISPLAY: dict[GateVerdict, str] = {
    GateVerdict.PASSED: "\u2705 PASSED",
    GateVerdict.FAILED: "\u274c FAILED",
    GateVerdict.PARTIAL: "\u26a0\ufe0f PARTIAL",
    GateVerdict.SKIPPED: "\u23ed\ufe0f SKIPPED",
}

_SEVERITY_ORDER: list[str] = ["error", "warning", "info"]

_SEVERITY_EMOJI: dict[str, str] = {
    "error": "\u274c",
    "warning": "\u26a0\ufe0f",
    "info": "\u2139\ufe0f",
}

# Human-readable layer names for display purposes.
_LAYER_DISPLAY_NAMES: dict[str, str] = {
    "layer1_service": "Layer 1 -- Service Build",
    "layer2_contract": "Layer 2 -- Contract Compliance",
    "layer3_system": "Layer 3 -- System Scan",
    "layer4_adversarial": "Layer 4 -- Adversarial Analysis",
}

# Violation-category prefixes used to drive recommendations.
_SECURITY_PREFIXES = ("SEC-", "CORS-")
_DOCKER_PREFIXES = ("DOCKER-",)
_LOGGING_PREFIXES = ("LOG-",)
_TRACE_PREFIXES = ("TRACE-",)
_HEALTH_PREFIXES = ("HEALTH-",)
_ADVERSARIAL_PREFIXES = ("ADV-",)


def _verdict_label(verdict: GateVerdict) -> str:
    """Return the emoji + text label for a ``GateVerdict``."""
    return _VERDICT_DISPLAY.get(verdict, str(verdict.value))


def _severity_label(severity: str) -> str:
    """Return a display label for a severity string."""
    emoji = _SEVERITY_EMOJI.get(severity.lower(), "")
    tag = severity.upper()
    return f"{emoji} {tag}" if emoji else tag


def _layer_display_name(layer_key: str) -> str:
    """Return a human-friendly name for a layer key."""
    return _LAYER_DISPLAY_NAMES.get(layer_key, layer_key)


def _format_duration(seconds: float) -> str:
    """Format a duration in seconds to a human-readable string."""
    if seconds < 1.0:
        return f"{seconds * 1000:.0f}ms"
    if seconds < 60.0:
        return f"{seconds:.1f}s"
    minutes = int(seconds // 60)
    remaining = seconds % 60
    return f"{minutes}m {remaining:.1f}s"


def _code_matches_any(code: str, prefixes: tuple[str, ...]) -> bool:
    """Check whether a violation code starts with any of the given prefixes."""
    return any(code.startswith(p) for p in prefixes)


# ---------------------------------------------------------------------------
# Section builders
# ---------------------------------------------------------------------------


def _header_section(report: QualityGateReport) -> str:
    """Build the title / header section."""
    verdict = _verdict_label(report.overall_verdict)
    lines: list[str] = [
        "# Quality Gate Report",
        "",
        f"**Verdict:** {verdict}",
    ]
    return "\n".join(lines)


def _summary_section(report: QualityGateReport) -> str:
    """Build the summary statistics section."""
    lines: list[str] = [
        "## Summary",
        "",
        f"| Metric | Value |",
        f"|---|---|",
        f"| Overall verdict | {_verdict_label(report.overall_verdict)} |",
        f"| Total violations | {report.total_violations} |",
        f"| Blocking violations | {report.blocking_violations} |",
        f"| Fix attempts | {report.fix_attempts} / {report.max_fix_attempts} |",
        f"| Layers executed | {len(report.layers)} |",
    ]
    return "\n".join(lines)


def _per_layer_section(report: QualityGateReport) -> str:
    """Build the per-layer results table."""
    lines: list[str] = [
        "## Per-Layer Results",
        "",
    ]

    if not report.layers:
        lines.append("No layers executed.")
        return "\n".join(lines)

    lines.append(
        "| Layer | Verdict | Checks (passed/total) | Violations | Duration |"
    )
    lines.append("|---|---|---|---|---|")

    for layer_key, result in report.layers.items():
        name = _layer_display_name(layer_key)
        verdict = _verdict_label(result.verdict)
        checks = f"{result.passed_checks}/{result.total_checks}"
        violations = str(len(result.violations))
        duration = _format_duration(result.duration_seconds)
        lines.append(
            f"| {name} | {verdict} | {checks} | {violations} | {duration} |"
        )

    return "\n".join(lines)


def _violations_section(report: QualityGateReport) -> str:
    """Build the violations section, grouped by severity."""
    lines: list[str] = [
        "## Violations",
        "",
    ]

    # Collect all violations across every layer.
    all_violations: list[ScanViolation] = []
    for result in report.layers.values():
        all_violations.extend(result.violations)

    if not all_violations:
        lines.append("No violations found.")
        return "\n".join(lines)

    # Group by severity.
    by_severity: dict[str, list[ScanViolation]] = defaultdict(list)
    for v in all_violations:
        by_severity[v.severity.lower()].append(v)

    # Render groups in defined order, then any remaining unknown severities.
    rendered_severities: set[str] = set()
    for sev in _SEVERITY_ORDER:
        if sev in by_severity:
            rendered_severities.add(sev)
            lines.extend(_violation_group(sev, by_severity[sev]))
            lines.append("")

    # Handle any unexpected severity values not in the canonical list.
    for sev in sorted(by_severity.keys()):
        if sev not in rendered_severities:
            lines.extend(_violation_group(sev, by_severity[sev]))
            lines.append("")

    return "\n".join(lines)


def _violation_group(severity: str, violations: list[ScanViolation]) -> list[str]:
    """Render a single severity group as a sub-heading + table."""
    label = _severity_label(severity)
    lines: list[str] = [
        f"### {label} ({len(violations)})",
        "",
        "| Severity | Code | File | Line | Message |",
        "|---|---|---|---|---|",
    ]
    for v in violations:
        sev_display = severity.upper()
        file_display = v.file_path if v.file_path else "--"
        line_display = str(v.line) if v.line else "--"
        message = v.message.replace("|", "\\|") if v.message else "--"
        lines.append(
            f"| {sev_display} | `{v.code}` | `{file_display}` | {line_display} | {message} |"
        )
    return lines


def _recommendations_section(report: QualityGateReport) -> str:
    """Build actionable recommendations based on findings."""
    lines: list[str] = [
        "## Recommendations",
        "",
    ]

    recommendations: list[str] = []

    # Collect all violations for analysis.
    all_violations: list[ScanViolation] = []
    for result in report.layers.values():
        all_violations.extend(result.violations)

    # Categorise violations by code prefix.
    has_security = any(
        _code_matches_any(v.code, _SECURITY_PREFIXES) for v in all_violations
    )
    has_docker = any(
        _code_matches_any(v.code, _DOCKER_PREFIXES) for v in all_violations
    )
    has_logging = any(
        _code_matches_any(v.code, _LOGGING_PREFIXES) for v in all_violations
    )
    has_trace = any(
        _code_matches_any(v.code, _TRACE_PREFIXES) for v in all_violations
    )
    has_health = any(
        _code_matches_any(v.code, _HEALTH_PREFIXES) for v in all_violations
    )
    has_adversarial = any(
        _code_matches_any(v.code, _ADVERSARIAL_PREFIXES) for v in all_violations
    )

    # Overall verdict-based recommendations.
    if report.overall_verdict == GateVerdict.FAILED:
        recommendations.append(
            "- **Critical:** The quality gate has FAILED. "
            "Resolve all blocking violations before merging."
        )

    if report.blocking_violations > 0:
        recommendations.append(
            f"- **Blocking:** {report.blocking_violations} blocking violation(s) "
            "must be fixed before the build can proceed."
        )

    if report.fix_attempts >= report.max_fix_attempts:
        recommendations.append(
            "- **Fix budget exhausted:** All automatic fix attempts have been used. "
            "Manual intervention is required."
        )

    # Category-specific recommendations.
    if has_security:
        sec_count = sum(
            1 for v in all_violations
            if _code_matches_any(v.code, _SECURITY_PREFIXES)
        )
        recommendations.append(
            f"- **Security ({sec_count} violation(s)):** Review and fix security "
            "findings including JWT configuration, CORS policy, and secret management."
        )

    if has_docker:
        docker_count = sum(
            1 for v in all_violations
            if _code_matches_any(v.code, _DOCKER_PREFIXES)
        )
        recommendations.append(
            f"- **Docker ({docker_count} violation(s)):** Harden container "
            "configuration -- avoid running as root, add health checks, "
            "pin image tags, and apply resource limits."
        )

    if has_logging:
        log_count = sum(
            1 for v in all_violations
            if _code_matches_any(v.code, _LOGGING_PREFIXES)
        )
        recommendations.append(
            f"- **Logging ({log_count} violation(s)):** Adopt structured logging, "
            "ensure request IDs are propagated, and remove sensitive data from log output."
        )

    if has_trace:
        recommendations.append(
            "- **Tracing:** Add distributed trace context propagation "
            "(e.g. OpenTelemetry) to all inter-service calls."
        )

    if has_health:
        recommendations.append(
            "- **Health checks:** Implement health endpoints "
            "(`/health` or `/healthz`) in all services for readiness "
            "and liveness probes."
        )

    if has_adversarial:
        adv_count = sum(
            1 for v in all_violations
            if _code_matches_any(v.code, _ADVERSARIAL_PREFIXES)
        )
        recommendations.append(
            f"- **Adversarial ({adv_count} violation(s)):** Address dead code, "
            "orphan services, naming inconsistencies, and potential race conditions."
        )

    # Layer-specific observations.
    for layer_key, result in report.layers.items():
        if result.verdict == GateVerdict.FAILED and result.total_checks > 0:
            failed_checks = result.total_checks - result.passed_checks
            name = _layer_display_name(layer_key)
            recommendations.append(
                f"- **{name}:** {failed_checks} of {result.total_checks} "
                "check(s) failed. Review the layer output for details."
            )

    if not recommendations:
        lines.append(
            "All quality gate checks passed. No action required."
        )
    else:
        lines.extend(recommendations)

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def generate_quality_gate_report(report: QualityGateReport) -> str:
    """Generate a Markdown quality-gate report from a ``QualityGateReport``.

    This is a pure function: it performs no I/O and has no side effects.
    It returns a single Markdown-formatted string suitable for writing to
    a file or displaying in a terminal.

    The report is structured into five sections:

    1. **Header** -- title and overall verdict badge.
    2. **Summary** -- key metrics in a table (violations, fix attempts, etc.).
    3. **Per-Layer Results** -- one row per layer with verdict, checks, and
       duration.
    4. **Violations** -- all violations grouped by severity (error, warning,
       info) and rendered in tables.
    5. **Recommendations** -- actionable advice derived from the findings.

    Args:
        report: The ``QualityGateReport`` dataclass populated by the quality
            gate engine.

    Returns:
        A complete Markdown report string.
    """
    logger.debug(
        "Generating quality gate report (verdict=%s, violations=%d, "
        "blocking=%d, fix_attempts=%d/%d)",
        report.overall_verdict.value,
        report.total_violations,
        report.blocking_violations,
        report.fix_attempts,
        report.max_fix_attempts,
    )

    sections: list[str] = [
        _header_section(report),
        _summary_section(report),
        _per_layer_section(report),
        _violations_section(report),
        _recommendations_section(report),
    ]

    return "\n\n".join(sections)

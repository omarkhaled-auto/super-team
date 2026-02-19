"""Layer 3 Quality Gate -- System-Level Security & Observability Scanner.

Aggregates three sub-scanners to perform a comprehensive system-level
quality analysis:

- **SecurityScanner** -- JWT security, CORS configuration, and secret
  detection (SEC-*, CORS-*, SEC-SECRET-*).
- **ObservabilityChecker** -- Structured logging, sensitive log data,
  request-ID propagation, trace context, and health endpoints
  (LOG-*, TRACE-*, HEALTH-*).
- **DockerSecurityScanner** -- Dockerfile and docker-compose security
  best practices (DOCKER-*).

All three sub-scanners are executed concurrently via ``asyncio.gather``.
Violations are merged, capped at ``MAX_VIOLATIONS_PER_CATEGORY`` per
category (TECH-021), and a verdict is computed based on severity levels.
"""

from __future__ import annotations

import asyncio
import time
from collections import defaultdict
from pathlib import Path

from src.build3_shared.models import (
    GateVerdict,
    LayerResult,
    QualityLevel,
    ScanViolation,
)
from src.quality_gate.docker_security import DockerSecurityScanner
from src.quality_gate.observability_checker import ObservabilityChecker
from src.quality_gate.security_scanner import SecurityScanner

# ---------------------------------------------------------------------------
# Per-category violation cap (TECH-021)
# ---------------------------------------------------------------------------
MAX_VIOLATIONS_PER_CATEGORY: int = 200

# Known category prefixes, ordered longest-first so that "SEC-SECRET" is
# matched before "SEC" during prefix extraction.
_KNOWN_CATEGORIES: tuple[str, ...] = (
    "SEC-SECRET",
    "SEC",
    "CORS",
    "LOG",
    "TRACE",
    "HEALTH",
    "DOCKER",
)


class Layer3Scanner:
    """Aggregates system-level sub-scanners into a single quality gate layer.

    Sub-scanners are instantiated once during ``__init__`` and reused across
    calls to :meth:`evaluate`.  Each invocation of ``evaluate`` runs all three
    sub-scanners concurrently, merges their results, applies per-category
    caps, and computes the final verdict.

    Verdict logic:
        - Any ``error`` severity violation -> ``FAILED``
        - Any ``warning`` severity violation (but no errors) -> ``PARTIAL``
        - No violations (or only ``info``) -> ``PASSED``
    """

    def __init__(self) -> None:
        self._security = SecurityScanner()
        self._observability = ObservabilityChecker()
        self._docker = DockerSecurityScanner()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def evaluate(self, target_dir: Path) -> LayerResult:
        """Run all system-level scanners against *target_dir*.

        Parameters
        ----------
        target_dir:
            Root directory to scan.  Passed unchanged to each sub-scanner.

        Returns
        -------
        LayerResult
            Layer 3 result containing the merged (and capped) violations,
            the computed verdict, and timing information.
        """
        start = time.monotonic()

        # Run all three scanners concurrently.
        security_violations, observability_violations, docker_violations = (
            await asyncio.gather(
                self._security.scan(target_dir),
                self._observability.scan(target_dir),
                self._docker.scan(target_dir),
            )
        )

        # Merge all violations into a single list.
        all_violations: list[ScanViolation] = []
        all_violations.extend(security_violations)
        all_violations.extend(observability_violations)
        all_violations.extend(docker_violations)

        # Cap per category (TECH-021).
        capped = self._cap_by_category(all_violations)

        # Determine verdict from the capped list.
        verdict = self._compute_verdict(capped)

        duration = time.monotonic() - start

        return LayerResult(
            layer=QualityLevel.LAYER3_SYSTEM,
            verdict=verdict,
            violations=capped,
            total_checks=len(all_violations),
            passed_checks=len(all_violations) - sum(
                1 for v in capped if v.severity == "error"
            ),
            duration_seconds=duration,
        )

    # ------------------------------------------------------------------
    # Category extraction
    # ------------------------------------------------------------------

    @staticmethod
    def _get_category(code: str) -> str:
        """Derive the category key from a violation code.

        The category is the prefix portion of the code before the trailing
        numeric segment.  For example:

        - ``"SEC-001"``        -> ``"SEC"``
        - ``"SEC-SECRET-001"`` -> ``"SEC-SECRET"``
        - ``"CORS-002"``      -> ``"CORS"``
        - ``"DOCKER-005"``    -> ``"DOCKER"``

        The method checks known multi-part prefixes (longest first) so
        that ``SEC-SECRET`` is correctly distinguished from ``SEC``.  If
        no known prefix matches, the code is split on ``"-"`` and the
        last segment (assumed numeric) is dropped to form the category.
        """
        upper = code.upper()
        for prefix in _KNOWN_CATEGORIES:
            if upper.startswith(prefix + "-"):
                # Ensure what follows the prefix-dash is the numeric portion
                # (e.g. "SEC-SECRET-001" starts with "SEC-SECRET-").
                return prefix
            if upper == prefix:
                return prefix
        # Fallback: drop the last dash-separated segment (the numeric id).
        parts = code.rsplit("-", 1)
        return parts[0] if len(parts) > 1 else code

    # ------------------------------------------------------------------
    # Per-category capping (TECH-021)
    # ------------------------------------------------------------------

    def _cap_by_category(
        self, violations: list[ScanViolation]
    ) -> list[ScanViolation]:
        """Group violations by category and cap each at ``MAX_VIOLATIONS_PER_CATEGORY``.

        The relative ordering of violations within each category is
        preserved; only the tail is trimmed when the cap is exceeded.

        Parameters
        ----------
        violations:
            The full, uncapped list of violations from all sub-scanners.

        Returns
        -------
        list[ScanViolation]
            A new list with at most ``MAX_VIOLATIONS_PER_CATEGORY``
            violations per category.
        """
        buckets: dict[str, list[ScanViolation]] = defaultdict(list)

        for violation in violations:
            category = self._get_category(violation.code)
            if len(buckets[category]) < MAX_VIOLATIONS_PER_CATEGORY:
                buckets[category].append(violation)

        # Flatten the buckets back into a single list, preserving
        # category order as encountered in the original violations.
        seen_categories: list[str] = []
        for violation in violations:
            cat = self._get_category(violation.code)
            if cat not in seen_categories:
                seen_categories.append(cat)

        result: list[ScanViolation] = []
        for cat in seen_categories:
            result.extend(buckets[cat])

        return result

    # ------------------------------------------------------------------
    # Verdict computation
    # ------------------------------------------------------------------

    @staticmethod
    def _compute_verdict(violations: list[ScanViolation]) -> GateVerdict:
        """Derive a :class:`GateVerdict` from the severity of violations.

        - If **any** violation has ``severity == "error"`` -> ``FAILED``
        - If **any** violation has ``severity == "warning"`` (but no
          errors) -> ``PARTIAL``
        - Otherwise (empty list or only ``"info"`` severity) -> ``PASSED``
        """
        has_error = False
        has_warning = False

        for v in violations:
            if v.severity == "error":
                has_error = True
                # No need to check further; FAILED is the worst verdict.
                break
            if v.severity == "warning":
                has_warning = True

        if has_error:
            return GateVerdict.FAILED
        if has_warning:
            return GateVerdict.PARTIAL
        return GateVerdict.PASSED

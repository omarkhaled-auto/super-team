"""Quality Gate Engine -- Top-level orchestrator for the 4-layer quality gate.

Executes quality gate layers sequentially with gating logic:

    Layer 1 (Per-Service)  -- must PASS before Layer 2 runs
    Layer 2 (Contract)     -- must PASS or PARTIAL before Layer 3 runs
    Layer 3 (System-Level) -- must PASS or PARTIAL before Layer 4 runs
    Layer 4 (Adversarial)  -- always advisory-only (verdict forced to PASSED)

If any layer FAILS, all subsequent layers are set to SKIPPED and the
engine returns immediately via the :class:`ScanAggregator`.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path

from src.build3_shared.models import (
    BuilderResult,
    GateVerdict,
    IntegrationReport,
    LayerResult,
    QualityGateReport,
    QualityLevel,
    ScanViolation,
)
from src.quality_gate.layer1_per_service import Layer1Scanner
from src.quality_gate.layer2_contract_compliance import Layer2Scanner
from src.quality_gate.layer3_system_level import Layer3Scanner
from src.quality_gate.layer4_adversarial import Layer4Scanner
from src.quality_gate.scan_aggregator import ScanAggregator
from src.super_orchestrator.config import QualityGateConfig

logger = logging.getLogger(__name__)


class QualityGateEngine:
    """Top-level orchestrator for the 4-layer quality gate.

    Composes all four layer scanners and the :class:`ScanAggregator` to
    produce a unified :class:`QualityGateReport`.

    Usage
    -----
    ::

        engine = QualityGateEngine(config=config, project_root=Path("src/"))
        report = await engine.run_all_layers(
            builder_results=results,
            integration_report=report,
        )
    """

    def __init__(self, config: QualityGateConfig | None = None, project_root: Path | None = None) -> None:
        self._config = config or QualityGateConfig()
        self._project_root = project_root or Path(".")
        self._layer1 = Layer1Scanner()
        self._layer2 = Layer2Scanner()
        self._layer3 = Layer3Scanner()
        self._layer4 = Layer4Scanner()
        self._aggregator = ScanAggregator()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def run_all_layers(
        self,
        builder_results: list[BuilderResult],
        integration_report: IntegrationReport,
        target_dir: Path | None = None,
        fix_attempts: int = 0,
        max_fix_attempts: int = 3,
    ) -> QualityGateReport:
        """Execute all quality gate layers sequentially with gating logic.

        Layers run in order L1 -> L2 -> L3 -> L4.  Each layer's verdict
        is checked via :meth:`should_promote` before the next layer runs.
        If a layer does not pass the promotion check, all remaining layers
        are marked as :attr:`GateVerdict.SKIPPED`.

        Parameters
        ----------
        builder_results:
            Per-service build outcomes from the build pipeline.
        integration_report:
            Integration test report from Milestone 2.
        target_dir:
            Root directory to scan for system-level and adversarial checks.
        fix_attempts:
            Number of auto-fix attempts already made in this cycle.
        max_fix_attempts:
            Maximum number of auto-fix attempts allowed.

        Returns
        -------
        QualityGateReport
            Aggregated report across all layers.
        """
        if target_dir is None:
            target_dir = self._project_root

        layer_results: dict[str, LayerResult] = {}
        total_start = time.monotonic()

        # ---- Layer 1: Per-service build results (sync) -------------------
        logger.info("Quality gate: starting Layer 1 (per-service build results)")
        l1_result = self._layer1.evaluate(builder_results)
        layer_results[QualityLevel.LAYER1_SERVICE.value] = l1_result
        logger.info(
            "Quality gate: Layer 1 complete -- verdict=%s, "
            "checks=%d/%d, violations=%d, duration=%.3fs",
            l1_result.verdict.value,
            l1_result.passed_checks,
            l1_result.total_checks,
            len(l1_result.violations),
            l1_result.duration_seconds,
        )

        if not self.should_promote(current_layer=QualityLevel.LAYER1_SERVICE, result=l1_result):
            logger.warning(
                "Quality gate: Layer 1 verdict is %s -- skipping layers 2, 3, 4",
                l1_result.verdict.value,
            )
            for level in [
                QualityLevel.LAYER2_CONTRACT,
                QualityLevel.LAYER3_SYSTEM,
                QualityLevel.LAYER4_ADVERSARIAL,
            ]:
                layer_results[level.value] = LayerResult(
                    layer=level, verdict=GateVerdict.SKIPPED
                )
            return self._aggregator.aggregate(
                layer_results, fix_attempts, max_fix_attempts
            )

        # ---- Layer 2: Contract compliance (sync) -------------------------
        logger.info("Quality gate: starting Layer 2 (contract compliance)")
        l2_result = self._layer2.evaluate(integration_report)
        layer_results[QualityLevel.LAYER2_CONTRACT.value] = l2_result
        logger.info(
            "Quality gate: Layer 2 complete -- verdict=%s, "
            "checks=%d/%d, violations=%d, duration=%.3fs",
            l2_result.verdict.value,
            l2_result.passed_checks,
            l2_result.total_checks,
            len(l2_result.violations),
            l2_result.duration_seconds,
        )

        if not self.should_promote(current_layer=QualityLevel.LAYER2_CONTRACT, result=l2_result):
            logger.warning(
                "Quality gate: Layer 2 verdict is %s -- skipping layers 3, 4",
                l2_result.verdict.value,
            )
            for level in [
                QualityLevel.LAYER3_SYSTEM,
                QualityLevel.LAYER4_ADVERSARIAL,
            ]:
                layer_results[level.value] = LayerResult(
                    layer=level, verdict=GateVerdict.SKIPPED
                )
            return self._aggregator.aggregate(
                layer_results, fix_attempts, max_fix_attempts
            )

        # ---- Layer 3: System-level scanning (async) ----------------------
        logger.info("Quality gate: starting Layer 3 (system-level scanning)")
        l3_result = await self._layer3.evaluate(target_dir)
        layer_results[QualityLevel.LAYER3_SYSTEM.value] = l3_result
        logger.info(
            "Quality gate: Layer 3 complete -- verdict=%s, "
            "checks=%d/%d, violations=%d, duration=%.3fs",
            l3_result.verdict.value,
            l3_result.passed_checks,
            l3_result.total_checks,
            len(l3_result.violations),
            l3_result.duration_seconds,
        )

        if not self.should_promote(current_layer=QualityLevel.LAYER3_SYSTEM, result=l3_result):
            logger.warning(
                "Quality gate: Layer 3 verdict is %s -- skipping layer 4",
                l3_result.verdict.value,
            )
            layer_results[QualityLevel.LAYER4_ADVERSARIAL.value] = LayerResult(
                layer=QualityLevel.LAYER4_ADVERSARIAL,
                verdict=GateVerdict.SKIPPED,
            )
            return self._aggregator.aggregate(
                layer_results, fix_attempts, max_fix_attempts
            )

        # ---- Layer 4: Adversarial analysis (async, advisory-only) --------
        logger.info("Quality gate: starting Layer 4 (adversarial analysis, advisory-only)")
        l4_result = await self._layer4.evaluate(target_dir)
        layer_results[QualityLevel.LAYER4_ADVERSARIAL.value] = l4_result
        logger.info(
            "Quality gate: Layer 4 complete -- verdict=%s (advisory), "
            "findings=%d, duration=%.3fs",
            l4_result.verdict.value,
            len(l4_result.violations),
            l4_result.duration_seconds,
        )

        total_duration = time.monotonic() - total_start
        logger.info(
            "Quality gate: all layers complete in %.3fs", total_duration
        )

        return self._aggregator.aggregate(
            layer_results, fix_attempts, max_fix_attempts
        )

    def should_promote(self, current_layer: QualityLevel | None = None, result: LayerResult | None = None, layer_result: LayerResult | None = None) -> bool:
        """Check if a layer's verdict allows the next layer to run.

        PASSED and PARTIAL allow promotion.  FAILED and SKIPPED block
        subsequent layers from executing.  When all violations are below
        ``self._config.blocking_severity``, the layer is also promoted.

        Parameters
        ----------
        current_layer:
            The quality level of the layer being checked (optional).
        result:
            The result from a completed layer evaluation (preferred param name).
        layer_result:
            Legacy alias for *result*.

        Returns
        -------
        bool
            ``True`` if the next layer should execute, ``False`` otherwise.
        """
        lr = result or layer_result
        if lr is None:
            return False
        if lr.verdict in (GateVerdict.PASSED, GateVerdict.PARTIAL):
            return True
        # Check if all violations are below blocking severity
        blocking_severity = getattr(self._config, "blocking_severity", "error")
        if lr.violations and blocking_severity:
            has_blocking = any(v.severity == blocking_severity for v in lr.violations)
            if not has_blocking:
                return True
        return False

    def classify_violations(
        self, violations: list[ScanViolation]
    ) -> dict[str, list[ScanViolation]]:
        """Group violations by severity level.

        Parameters
        ----------
        violations:
            A flat list of scan violations from any layer.

        Returns
        -------
        dict[str, list[ScanViolation]]
            Mapping of severity (``"error"``, ``"warning"``, ``"info"``)
            to the violations at that severity.  Unrecognised severity
            values are bucketed under ``"info"``.
        """
        result: dict[str, list[ScanViolation]] = {
            "error": [],
            "warning": [],
            "info": [],
        }
        for v in violations:
            severity = v.severity if v.severity in result else "info"
            result[severity].append(v)
        return result

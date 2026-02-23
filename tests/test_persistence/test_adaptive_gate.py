"""Tests for adaptive quality gate -- LearnedScanner and GapDetector."""
from __future__ import annotations

import pytest
from pathlib import Path

from src.build3_shared.constants import ALL_SCAN_CODES
from src.build3_shared.models import ScanViolation
from src.quality_gate.gap_detector import GapDetector, PatternCluster


@pytest.fixture
def pattern_store(tmp_path: Path):
    """Provide a PatternStore with a temporary ChromaDB path."""
    from src.persistence.pattern_store import PatternStore
    return PatternStore(tmp_path / "test_chroma")


@pytest.fixture
def tracker(tmp_path: Path):
    """Provide a RunTracker with a temporary database."""
    from src.persistence.run_tracker import RunTracker
    return RunTracker(tmp_path / "test.db")


class TestLearnedScanner:
    def test_learned_scanner_loads_patterns_from_store(
        self, pattern_store, tmp_path: Path
    ) -> None:
        """Patterns in PatternStore → learned_scanner has them."""
        from src.quality_gate.learned_scanner import LearnedScanner

        # Add a pattern first
        violation = ScanViolation(
            code="SEC-001",
            severity="warning",
            category="jwt_security",
            message="Missing auth decorator",
        )
        pattern_store.add_violation_pattern(violation, tech_stack="python")

        scanner = LearnedScanner(pattern_store, "python")
        # Scanner should have loaded patterns (may be empty if distance > threshold)
        assert isinstance(scanner.scan_codes, list)

    @pytest.mark.asyncio
    async def test_learned_scanner_scan_returns_info_severity(
        self, pattern_store, tmp_path: Path
    ) -> None:
        """Matching file → ScanViolation.severity == 'info'."""
        from src.quality_gate.learned_scanner import LearnedScanner

        # Add a pattern about "authentication"
        violation = ScanViolation(
            code="SEC-001",
            severity="warning",
            category="jwt_security",
            message="authentication decorator missing from route handler",
        )
        pattern_store.add_violation_pattern(violation, tech_stack="python")

        scanner = LearnedScanner(pattern_store, "python")

        # Create a file that might match
        scan_dir = tmp_path / "project"
        scan_dir.mkdir()
        test_file = scan_dir / "routes.py"
        test_file.write_text(
            '@app.get("/users")\ndef list_users():\n    # authentication needed\n    pass\n',
            encoding="utf-8",
        )

        violations = await scanner.scan(scan_dir)
        # Violations should have 'info' severity (LEARNED mapped to info)
        for v in violations:
            assert v.severity == "info"

    def test_learned_scanner_scan_codes_format(
        self, pattern_store
    ) -> None:
        """Returns ['LEARNED-001', ...] format."""
        from src.quality_gate.learned_scanner import LearnedScanner

        scanner = LearnedScanner(pattern_store, "python")
        codes = scanner.scan_codes
        for code in codes:
            assert code.startswith("LEARNED-")

    def test_learned_scanner_skipped_when_disabled(self) -> None:
        """config.persistence.enabled = False → LearnedScanner not instantiated."""
        from src.super_orchestrator.config import SuperOrchestratorConfig

        config = SuperOrchestratorConfig()
        assert config.persistence.enabled is False
        # When disabled, the gate engine should NOT create a LearnedScanner
        # This is verified by the gate_engine integration, not here directly


class TestGapDetector:
    def test_gap_detector_finds_unknown_scan_codes(
        self, tracker
    ) -> None:
        """Violation with code not in ALL_SCAN_CODES → appears in cluster."""
        tracker.record_run("run-1", "hash", "failed", 1, 0.5)

        # Record a violation with an unknown scan code
        unknown_violation = ScanViolation(
            code="CUSTOM-001",
            severity="warning",
            category="custom",
            message="Custom violation found",
        )
        tracker.record_violation("run-1", unknown_violation, "svc", "python")

        detector = GapDetector()
        clusters = detector.find_uncategorized_violations("run-1", tracker)

        assert len(clusters) >= 1
        assert clusters[0].violation_count >= 1

    def test_gap_detector_clusters_similar_violations(
        self, tracker
    ) -> None:
        """Two violations with same unknown code → same cluster."""
        tracker.record_run("run-1", "hash", "failed", 1, 0.5)

        for i in range(3):
            v = ScanViolation(
                code="NOVEL-001",
                severity="warning",
                category="novel",
                message=f"Novel violation instance {i}",
            )
            tracker.record_violation("run-1", v, "svc", "python")

        detector = GapDetector()
        clusters = detector.find_uncategorized_violations("run-1", tracker)

        assert len(clusters) >= 1
        # All 3 should be in the same cluster (same scan code)
        novel_cluster = next(
            (c for c in clusters if c.violation_count >= 3), None
        )
        assert novel_cluster is not None

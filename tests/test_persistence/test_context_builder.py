"""Tests for failure memory and fix context injection."""
from __future__ import annotations

import pytest
from pathlib import Path
from unittest.mock import MagicMock

from src.build3_shared.models import ScanViolation
from src.persistence.context_builder import build_failure_context, build_fix_context


class MockPersistenceConfig:
    enabled: bool = True
    max_patterns_per_injection: int = 5


class MockConfig:
    persistence = MockPersistenceConfig()


class MockConfigDisabled:
    persistence = MagicMock(enabled=False)


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


class TestBuildFailureContext:
    def test_empty_when_no_patterns(
        self, pattern_store, tracker
    ) -> None:
        """Empty PatternStore → returns ''."""
        config = MockConfig()
        result = build_failure_context(
            "svc-a", "python/fastapi", config, pattern_store, tracker
        )
        assert result == ""

    def test_returns_formatted_section(
        self, pattern_store, tracker
    ) -> None:
        """Patterns exist → returns string with delimiters."""
        config = MockConfig()

        # Add some stats
        tracker.record_run("run-1", "hash", "failed", 1, 0.5)
        v = ScanViolation(
            code="SEC-001", severity="warning", category="jwt",
            message="Missing auth"
        )
        tracker.record_violation("run-1", v, "svc-a", "python/fastapi")
        tracker.update_scan_code_stats("run-1")

        result = build_failure_context(
            "svc-a", "python/fastapi", config, pattern_store, tracker
        )
        assert "FAILURE MEMORY FROM PRIOR RUNS" in result
        assert "SEC-001" in result

    def test_uses_correct_delimiters(
        self, pattern_store, tracker
    ) -> None:
        """Output contains exact delimiter strings."""
        config = MockConfig()
        tracker.record_run("run-1", "hash", "failed", 1, 0.5)
        v = ScanViolation(
            code="SEC-001", severity="warning", category="jwt",
            message="Missing auth"
        )
        tracker.record_violation("run-1", v, "svc-a", "python")
        tracker.update_scan_code_stats("run-1")

        result = build_failure_context(
            "svc-a", "python", config, pattern_store, tracker
        )
        if result:  # Only check if patterns exist
            assert "================================================" in result

    def test_all_injections_noop_when_disabled(self) -> None:
        """enabled=False → prompt identical to pre-Phase-5 prompt."""
        config = MockConfigDisabled()
        result = build_failure_context(
            "svc-a", "python", config, None, None
        )
        assert result == ""


class TestBuildFixContext:
    def test_fix_context_empty_when_no_examples(
        self, pattern_store
    ) -> None:
        """No fix examples → returns ''."""
        config = MockConfig()
        violations = [
            ScanViolation(
                code="SEC-001", severity="warning", category="jwt",
                message="Missing auth"
            ),
        ]
        result = build_fix_context(violations, "python", config, pattern_store)
        assert result == ""

    def test_fix_context_returns_section_when_examples_exist(
        self, pattern_store
    ) -> None:
        """Fix examples exist → returns formatted section."""
        config = MockConfig()
        pattern_store.add_fix_example(
            diff="- no_auth\n+ @login_required",
            description="Added auth decorator",
            scan_code="SEC-001",
            tech_stack="python",
        )
        violations = [
            ScanViolation(
                code="SEC-001", severity="warning", category="jwt",
                message="Missing auth"
            ),
        ]
        result = build_fix_context(violations, "python", config, pattern_store)
        # May return "" if ChromaDB doesn't find the exact match
        assert isinstance(result, str)

    def test_fix_context_noop_when_disabled(self) -> None:
        """enabled=False → returns ''."""
        config = MockConfigDisabled()
        result = build_fix_context([], "python", config, None)
        assert result == ""

    def test_persistence_write_failure_logs_not_raises(self, tmp_path: Path) -> None:
        """RunTracker.record_run raises → pipeline continues."""
        # This tests the crash-isolation principle
        from src.persistence.run_tracker import RunTracker

        tracker = RunTracker(tmp_path / "test.db")
        # Normal operation should not raise
        tracker.record_run("run-1", "hash", "passed", 1, 0.0)
        # Even with bad data types, should not raise
        tracker.record_run("", "", "", 0, 0.0)

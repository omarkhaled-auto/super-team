"""Tests for RunTracker -- SQLite-backed violation tracking."""
from __future__ import annotations

import pytest
from pathlib import Path

from src.build3_shared.models import ScanViolation
from src.persistence.run_tracker import RunTracker
from src.persistence.schema import SCHEMA_VERSION, init_persistence_db
from src.shared.db.connection import ConnectionPool


@pytest.fixture
def tracker(tmp_path: Path) -> RunTracker:
    """Provide a RunTracker with a temporary database."""
    return RunTracker(tmp_path / "test_persistence.db")


@pytest.fixture
def sample_violation() -> ScanViolation:
    """Provide a sample ScanViolation."""
    return ScanViolation(
        code="SEC-001",
        severity="warning",
        category="jwt_security",
        file_path="src/auth/routes.py",
        line=42,
        service="auth-service",
        message="Route handler missing authentication decorator",
    )


class TestRunTracker:
    def test_record_run_writes_correct_row(self, tracker: RunTracker) -> None:
        """Verify all fields in pipeline_runs after record_run."""
        tracker.record_run("run-1", "abc123", "passed", 3, 1.5)

        conn = tracker._pool.get()
        row = conn.execute(
            "SELECT * FROM pipeline_runs WHERE run_id = ?", ("run-1",)
        ).fetchone()

        assert row is not None
        assert row["run_id"] == "run-1"
        assert row["prd_hash"] == "abc123"
        assert row["overall_verdict"] == "passed"
        assert row["service_count"] == 3
        assert row["total_cost"] == 1.5

    def test_record_violation_links_to_run_id(
        self, tracker: RunTracker, sample_violation: ScanViolation
    ) -> None:
        """Verify FK relationship between violations and runs."""
        tracker.record_run("run-1", "hash", "failed", 1, 0.5)
        vid = tracker.record_violation("run-1", sample_violation, "auth-service", "python/fastapi")

        conn = tracker._pool.get()
        row = conn.execute(
            "SELECT * FROM violations_observed WHERE violation_id = ?", (vid,)
        ).fetchone()

        assert row is not None
        assert row["run_id"] == "run-1"
        assert row["scan_code"] == "SEC-001"
        assert row["service_name"] == "auth-service"
        assert row["service_tech_stack"] == "python/fastapi"

    def test_mark_fixed_updates_was_fixed_flag(
        self, tracker: RunTracker, sample_violation: ScanViolation
    ) -> None:
        """Verify was_fixed = 1 after mark_fixed call."""
        tracker.record_run("run-1", "hash", "failed", 1, 0.5)
        vid = tracker.record_violation("run-1", sample_violation, "auth", "python")

        tracker.mark_fixed(vid, fix_cost=0.25)

        conn = tracker._pool.get()
        row = conn.execute(
            "SELECT was_fixed, fix_cost FROM violations_observed WHERE violation_id = ?",
            (vid,),
        ).fetchone()

        assert row["was_fixed"] == 1
        assert row["fix_cost"] == 0.25

    def test_get_stats_for_stack_returns_aggregates(
        self, tracker: RunTracker, sample_violation: ScanViolation
    ) -> None:
        """Verify correct scan_code counts for given tech_stack."""
        tracker.record_run("run-1", "hash", "failed", 1, 0.5)
        tracker.record_violation("run-1", sample_violation, "auth", "python/fastapi")
        tracker.record_violation("run-1", sample_violation, "auth", "python/fastapi")
        tracker.update_scan_code_stats("run-1")

        stats = tracker.get_stats_for_stack("python/fastapi")
        assert len(stats) >= 1
        sec_stat = next((s for s in stats if s["scan_code"] == "SEC-001"), None)
        assert sec_stat is not None
        assert sec_stat["occurrence_count"] == 2

    def test_record_run_failure_does_not_raise(self, tmp_path: Path) -> None:
        """Corrupt path → logs warning, returns safely."""
        # Use an invalid path that can't be opened
        tracker = RunTracker(tmp_path / "nonexistent_dir" / "sub" / "test.db")
        # Should not raise -- the ConnectionPool creates parent dirs
        tracker.record_run("run-1", "hash", "passed", 1, 0.0)

    def test_schema_is_idempotent(self, tmp_path: Path) -> None:
        """Call init_persistence_db twice → no error, same schema."""
        pool = ConnectionPool(tmp_path / "test.db")
        init_persistence_db(pool)
        init_persistence_db(pool)  # Should not raise

        conn = pool.get()
        row = conn.execute("SELECT version FROM schema_version").fetchone()
        assert row[0] == SCHEMA_VERSION
        pool.close()


class TestRunTrackerRecordFix:
    def test_record_fix_stores_data(
        self, tracker: RunTracker, sample_violation: ScanViolation
    ) -> None:
        """Verify fix patterns are stored correctly."""
        tracker.record_run("run-1", "hash", "failed", 1, 0.5)
        vid = tracker.record_violation("run-1", sample_violation, "auth", "python")
        tracker.record_fix(vid, "before_code", "after_code", "diff_text", "Added auth decorator")

        conn = tracker._pool.get()
        row = conn.execute(
            "SELECT * FROM fix_patterns WHERE violation_id = ?", (vid,)
        ).fetchone()

        assert row is not None
        assert row["code_before"] == "before_code"
        assert row["code_after"] == "after_code"
        assert row["diff"] == "diff_text"
        assert row["fix_description"] == "Added auth decorator"

"""Cross-milestone regression detection tests.

Covers:
    - take_violation_snapshot format verification
    - detect_regressions before/after comparison
    - Clean run (no regressions) verification
    - Fix-agent-introduced regression detection
"""
from __future__ import annotations

import pytest

from src.run4.fix_pass import detect_regressions, take_violation_snapshot
from src.run4.state import Finding


# ---------------------------------------------------------------------------
# Cross-milestone regression detection
# ---------------------------------------------------------------------------


class TestCrossMilestoneRegression:
    """Verify regression detection across milestone snapshots."""

    def test_new_violation_detected_as_regression(self) -> None:
        """A scan code absent from 'before' but present in 'after' is a new regression."""
        before = take_violation_snapshot([
            {"scan_code": "SEC-001", "file_path": "src/auth/login.py"},
        ])
        after = take_violation_snapshot([
            {"scan_code": "SEC-001", "file_path": "src/auth/login.py"},
            {"scan_code": "LINT-003", "file_path": "src/orders/api.py"},
        ])

        regressions = detect_regressions(before, after)

        assert len(regressions) == 1
        assert regressions[0]["scan_code"] == "LINT-003"
        assert regressions[0]["file_path"] == "src/orders/api.py"
        assert regressions[0]["type"] == "new"

    def test_reappeared_violation_detected(self) -> None:
        """A file added under an existing scan code is a reappeared regression."""
        before = take_violation_snapshot([
            {"scan_code": "SEC-001", "file_path": "src/auth/login.py"},
        ])
        after = take_violation_snapshot([
            {"scan_code": "SEC-001", "file_path": "src/auth/login.py"},
            {"scan_code": "SEC-001", "file_path": "src/auth/register.py"},
        ])

        regressions = detect_regressions(before, after)

        assert len(regressions) == 1
        assert regressions[0]["scan_code"] == "SEC-001"
        assert regressions[0]["file_path"] == "src/auth/register.py"
        assert regressions[0]["type"] == "reappeared"

    def test_multiple_regressions_across_codes(self) -> None:
        """Multiple new and reappeared regressions are all detected."""
        before = {"SEC-001": ["src/a.py"]}
        after = {
            "SEC-001": ["src/a.py", "src/b.py"],      # reappeared
            "DOCKER-001": ["Dockerfile"],              # new
            "LOG-001": ["src/c.py", "src/d.py"],       # new (2 files)
        }

        regressions = detect_regressions(before, after)

        codes = [r["scan_code"] for r in regressions]
        assert "SEC-001" in codes
        assert "DOCKER-001" in codes
        assert "LOG-001" in codes
        assert len(regressions) == 4  # 1 reappeared + 1 new + 2 new


# ---------------------------------------------------------------------------
# No-regression clean run
# ---------------------------------------------------------------------------


class TestNoRegressionOnCleanRun:
    """Verify empty violation diff when nothing changes."""

    def test_identical_snapshots_yield_no_regressions(self) -> None:
        """Identical before and after snapshots produce zero regressions."""
        snapshot = {
            "SEC-001": ["src/a.py", "src/b.py"],
            "LINT-002": ["src/c.py"],
        }
        regressions = detect_regressions(snapshot, snapshot)
        assert regressions == []

    def test_empty_snapshots_yield_no_regressions(self) -> None:
        """Both empty snapshots produce zero regressions."""
        regressions = detect_regressions({}, {})
        assert regressions == []

    def test_violations_removed_yields_no_regressions(self) -> None:
        """Removing violations (fixes) does not count as regressions."""
        before = {
            "SEC-001": ["src/a.py", "src/b.py"],
            "LINT-002": ["src/c.py"],
        }
        after = {
            "SEC-001": ["src/a.py"],  # b.py was fixed
            # LINT-002 entirely fixed
        }
        regressions = detect_regressions(before, after)
        assert regressions == []


# ---------------------------------------------------------------------------
# Fix-agent introduced regression
# ---------------------------------------------------------------------------


class TestRegressionFromFixAgent:
    """Simulate a fix agent introducing a new violation during a fix pass."""

    def test_fix_agent_introduces_new_scan_code(self) -> None:
        """Fix agent resolves SEC-001 but introduces LOG-001 -- detected."""
        before = take_violation_snapshot([
            {"scan_code": "SEC-001", "file_path": "src/auth/login.py"},
        ])
        # After fix: SEC-001 removed, but LOG-001 introduced
        after = take_violation_snapshot([
            {"scan_code": "LOG-001", "file_path": "src/auth/login.py"},
        ])

        regressions = detect_regressions(before, after)

        assert len(regressions) == 1
        assert regressions[0]["scan_code"] == "LOG-001"
        assert regressions[0]["type"] == "new"

    def test_fix_agent_introduces_violation_in_different_file(self) -> None:
        """Fix agent fixes file A but introduces violation in file B."""
        before = {"LINT-001": ["src/a.py"]}
        # After: a.py fixed, but b.py now has same lint issue
        after = {"LINT-001": ["src/b.py"]}

        regressions = detect_regressions(before, after)

        assert len(regressions) == 1
        assert regressions[0]["file_path"] == "src/b.py"
        assert regressions[0]["type"] == "reappeared"

    def test_fix_agent_net_positive_still_flags_regression(self) -> None:
        """Even when net violations decrease, new ones are flagged."""
        before = {
            "SEC-001": ["src/a.py", "src/b.py", "src/c.py"],
        }
        # Fixed 2 of 3, but introduced a new DOCKER-001
        after = {
            "SEC-001": ["src/a.py"],
            "DOCKER-001": ["Dockerfile"],
        }

        regressions = detect_regressions(before, after)

        assert len(regressions) == 1
        assert regressions[0]["scan_code"] == "DOCKER-001"
        assert regressions[0]["type"] == "new"


# ---------------------------------------------------------------------------
# Snapshot format validation
# ---------------------------------------------------------------------------


class TestSnapshotFormat:
    """Verify snapshot dict has correct {scan_code: [file_paths]} structure."""

    def test_snapshot_from_flat_list(self) -> None:
        """Flat list of dicts produces {scan_code: [file_paths]}."""
        scan_results = [
            {"scan_code": "SEC-001", "file_path": "src/a.py"},
            {"scan_code": "SEC-001", "file_path": "src/b.py"},
            {"scan_code": "LINT-002", "file_path": "src/c.py"},
        ]
        snapshot = take_violation_snapshot(scan_results)

        assert isinstance(snapshot, dict)
        assert "SEC-001" in snapshot
        assert "LINT-002" in snapshot
        assert isinstance(snapshot["SEC-001"], list)
        assert len(snapshot["SEC-001"]) == 2
        assert len(snapshot["LINT-002"]) == 1

    def test_snapshot_keys_are_scan_codes(self) -> None:
        """All keys in snapshot are scan code strings."""
        scan_results = [
            {"scan_code": "A-001", "file_path": "x.py"},
            {"scan_code": "B-002", "file_path": "y.py"},
        ]
        snapshot = take_violation_snapshot(scan_results)

        for key in snapshot:
            assert isinstance(key, str)
            assert len(key) > 0

    def test_snapshot_values_are_file_path_lists(self) -> None:
        """All values in snapshot are lists of file path strings."""
        scan_results = [
            {"scan_code": "SEC-001", "file_path": "src/a.py"},
            {"scan_code": "SEC-001", "file_path": "src/b.py"},
        ]
        snapshot = take_violation_snapshot(scan_results)

        for paths in snapshot.values():
            assert isinstance(paths, list)
            for path in paths:
                assert isinstance(path, str)

    def test_snapshot_from_pre_grouped_dict(self) -> None:
        """Pre-grouped dict passes through as valid snapshot."""
        pre_grouped = {
            "SEC-001": ["src/a.py", "src/b.py"],
            "LINT-002": ["src/c.py"],
        }
        snapshot = take_violation_snapshot(pre_grouped)

        assert snapshot == pre_grouped

    def test_snapshot_empty_input(self) -> None:
        """Empty input produces empty snapshot."""
        assert take_violation_snapshot([]) == {}
        assert take_violation_snapshot({}) == {}

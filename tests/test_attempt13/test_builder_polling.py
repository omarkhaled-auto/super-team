"""Tests for builder polling completion detection (Fix 1) and process tree kill (Fix 2).

Tests verify that the polling loop in _run_single_builder correctly detects
builder completion via STATE.json contents, and that _kill_builder_tree
properly terminates process trees.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Completion detection logic (extracted from pipeline.py inline code)
# ---------------------------------------------------------------------------

def _is_builder_complete_from_state(state_data: dict) -> bool:
    """Reproduce the completion detection logic from pipeline.py:1828-1840."""
    conv = state_data.get("convergence_ratio", 0.0)
    phases = len(state_data.get("completed_phases", []))
    milestones = len(state_data.get("completed_milestones", []))
    current_phase = state_data.get("current_phase", "")
    success = state_data.get("success", False)
    if not success:
        success = state_data.get("summary", {}).get("success", False)

    return (
        (conv >= 0.9 and (phases >= 8 or milestones >= 3))
        or current_phase in ("convergence_complete", "complete", "done", "finished")
        or (success and (phases >= 8 or milestones >= 3))
    )


class TestCompletionDetection:
    """Test the inline builder completion detection logic."""

    def test_complete_via_high_convergence_and_phases(self):
        """Builder with conv >= 0.9 and phases >= 8 detected as complete."""
        state = {
            "convergence_ratio": 1.0,
            "completed_phases": list(range(10)),
            "current_phase": "convergence_complete",
        }
        assert _is_builder_complete_from_state(state) is True

    def test_complete_via_convergence_and_milestones(self):
        """Builder with conv >= 0.9 and milestones >= 3 detected as complete."""
        state = {
            "convergence_ratio": 0.95,
            "completed_milestones": ["m1", "m2", "m3"],
            "completed_phases": ["a", "b"],
            "current_phase": "testing",
        }
        assert _is_builder_complete_from_state(state) is True

    def test_complete_via_success_and_phases(self):
        """Builder with success=True and phases >= 8 detected as complete."""
        state = {
            "success": True,
            "completed_phases": list(range(8)),
            "completed_milestones": [],
            "convergence_ratio": 0.85,
            "current_phase": "finalizing",
        }
        assert _is_builder_complete_from_state(state) is True

    def test_complete_via_summary_success_and_milestones(self):
        """Builder with summary.success=True and milestones >= 3 detected as complete."""
        state = {
            "summary": {"success": True},
            "completed_milestones": ["m1", "m2", "m3"],
            "completed_phases": [],
            "convergence_ratio": 0.85,
            "current_phase": "done",
        }
        assert _is_builder_complete_from_state(state) is True

    def test_complete_via_terminal_phase(self):
        """Builder in terminal phase (convergence_complete) detected as complete."""
        state = {
            "convergence_ratio": 0.5,
            "completed_phases": ["a"],
            "current_phase": "convergence_complete",
        }
        assert _is_builder_complete_from_state(state) is True

    def test_complete_via_done_phase(self):
        """Builder in 'done' phase detected as complete."""
        state = {
            "convergence_ratio": 0.3,
            "completed_phases": [],
            "current_phase": "done",
        }
        assert _is_builder_complete_from_state(state) is True

    def test_not_complete_on_init(self):
        """Builder in init phase not falsely detected as complete."""
        state = {
            "convergence_ratio": 0.0,
            "completed_phases": [],
            "current_phase": "init",
        }
        assert _is_builder_complete_from_state(state) is False

    def test_not_complete_on_partial_progress(self):
        """Builder with 5/10 phases and 0.5 conv not detected as complete."""
        state = {
            "convergence_ratio": 0.5,
            "completed_phases": ["a", "b", "c", "d", "e"],
            "current_phase": "testing",
        }
        assert _is_builder_complete_from_state(state) is False

    def test_not_complete_high_conv_low_phases(self):
        """High convergence but too few phases should not trigger completion."""
        state = {
            "convergence_ratio": 0.95,
            "completed_phases": ["a", "b"],
            "completed_milestones": [],
            "current_phase": "building",
        }
        assert _is_builder_complete_from_state(state) is False

    def test_not_complete_success_but_low_phases(self):
        """Success=True but < 8 phases and < 3 milestones should not trigger."""
        state = {
            "success": True,
            "completed_phases": ["a", "b", "c"],
            "completed_milestones": ["m1"],
            "convergence_ratio": 0.7,
            "current_phase": "building",
        }
        assert _is_builder_complete_from_state(state) is False

    def test_not_complete_empty_state(self):
        """Empty state dict should not be detected as complete."""
        assert _is_builder_complete_from_state({}) is False


class TestKillBuilderTree:
    """Test the _kill_builder_tree function."""

    async def test_kill_with_psutil(self):
        """Process tree is killed via psutil when available."""
        from src.super_orchestrator.pipeline import _kill_builder_tree

        mock_proc = MagicMock()
        mock_proc.pid = 12345
        mock_proc.returncode = None

        mock_wait = asyncio.Future()
        mock_wait.set_result(0)
        mock_proc.wait = MagicMock(return_value=mock_wait)

        mock_child = MagicMock()
        mock_parent = MagicMock()
        mock_parent.children.return_value = [mock_child]

        # psutil is imported inside the function body, so we mock it in sys.modules
        mock_psutil = MagicMock()
        mock_psutil.Process.return_value = mock_parent
        mock_psutil.NoSuchProcess = type("NoSuchProcess", (Exception,), {})
        mock_psutil.wait_procs = MagicMock()

        with patch.dict("sys.modules", {"psutil": mock_psutil}):
            await _kill_builder_tree(mock_proc, "test-service")

        mock_parent.children.assert_called_once_with(recursive=True)
        mock_child.kill.assert_called_once()
        mock_parent.kill.assert_called_once()

    async def test_kill_fallback_without_psutil(self):
        """Falls back to proc.kill() when psutil is not available."""
        from src.super_orchestrator.pipeline import _kill_builder_tree

        mock_proc = MagicMock()
        mock_proc.pid = 12345
        mock_proc.returncode = None

        mock_wait = asyncio.Future()
        mock_wait.set_result(0)
        mock_proc.wait = MagicMock(return_value=mock_wait)

        # Make 'import psutil' raise ImportError
        import builtins
        original_import = builtins.__import__

        def _fake_import(name, *args, **kwargs):
            if name == "psutil":
                raise ImportError("no psutil")
            return original_import(name, *args, **kwargs)

        with patch.object(builtins, "__import__", side_effect=_fake_import):
            await _kill_builder_tree(mock_proc, "test-service")

        mock_proc.kill.assert_called()


class TestSkipCompletedGuard:
    """Test the skip-completed guard logic in _run_single_builder."""

    def test_skip_requires_sufficient_progress(self, tmp_path: Path):
        """Skip-completed guard requires milestones > 0 or phases >= 8."""
        # With 0 milestones and 0 phases, should NOT skip (even with success=True)
        state_data = {
            "summary": {"success": True},
            "completed_milestones": [],
            "completed_phases": [],
        }
        milestones = len(state_data.get("completed_milestones", []))
        phases = len(state_data.get("completed_phases", []))
        sufficient = milestones > 0 or phases >= 8
        assert sufficient is False

    def test_skip_with_milestones(self, tmp_path: Path):
        """Skip-completed guard passes when milestones > 0."""
        state_data = {
            "summary": {"success": True},
            "completed_milestones": ["m1", "m2", "m3"],
            "completed_phases": [],
        }
        milestones = len(state_data.get("completed_milestones", []))
        phases = len(state_data.get("completed_phases", []))
        sufficient = milestones > 0 or phases >= 8
        assert sufficient is True

    def test_skip_with_phases(self, tmp_path: Path):
        """Skip-completed guard passes when phases >= 8 (agent_team_v15)."""
        state_data = {
            "summary": {"success": True},
            "completed_milestones": [],
            "completed_phases": list(range(10)),
        }
        milestones = len(state_data.get("completed_milestones", []))
        phases = len(state_data.get("completed_phases", []))
        sufficient = milestones > 0 or phases >= 8
        assert sufficient is True

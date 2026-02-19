"""Tests for ContractFixLoop.

TEST-003: >= 8 test cases covering classify_violations and feed_violations_to_builder.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.build3_shared.models import ContractViolation
from src.integrator.fix_loop import ContractFixLoop
from src.run4.builder import BuilderResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_violation(
    severity: str = "error",
    code: str = "V001",
    endpoint: str = "/api/test",
    message: str = "test violation",
    expected: str = "string",
    actual: str = "int",
) -> ContractViolation:
    """Create a ContractViolation with sensible defaults."""
    return ContractViolation(
        code=code,
        severity=severity,
        service="test-svc",
        endpoint=endpoint,
        message=message,
        expected=expected,
        actual=actual,
    )


def _mock_process(returncode: int = 0) -> MagicMock:
    """Return a mock subprocess whose .communicate() is an awaitable."""
    proc = MagicMock()
    proc.returncode = returncode
    proc.communicate = AsyncMock(return_value=(b"ok\n", b""))
    proc.wait = AsyncMock(return_value=returncode)
    proc.kill = MagicMock()
    return proc


def _write_state_json(builder_dir: Path, total_cost: float = 0.0,
                       success: bool = True) -> None:
    """Write a minimal STATE.json for the builder."""
    state_dir = builder_dir / ".agent-team"
    state_dir.mkdir(parents=True, exist_ok=True)
    state_data = {
        "health": "green",
        "completed_phases": [],
        "total_cost": total_cost,
        "summary": {
            "success": success,
            "test_passed": 5,
            "test_total": 5,
            "convergence_ratio": 1.0,
        },
    }
    (state_dir / "STATE.json").write_text(
        json.dumps(state_data), encoding="utf-8"
    )


# ---------------------------------------------------------------------------
# classify_violations
# ---------------------------------------------------------------------------

class TestClassifyViolations:
    """Tests for ContractFixLoop.classify_violations."""

    def test_classify_violations_groups_by_severity(self) -> None:
        """Violations with different severities land in the correct buckets."""
        loop = ContractFixLoop()
        violations = [
            _make_violation(severity="critical"),
            _make_violation(severity="error"),
            _make_violation(severity="warning"),
            _make_violation(severity="info"),
            _make_violation(severity="critical"),
        ]
        classified = loop.classify_violations(violations)

        assert len(classified["critical"]) == 2
        assert len(classified["error"]) == 1
        assert len(classified["warning"]) == 1
        assert len(classified["info"]) == 1

    def test_classify_violations_unknown_severity_falls_to_error(self) -> None:
        """A violation with an unrecognised severity falls into 'error'."""
        loop = ContractFixLoop()
        violations = [
            _make_violation(severity="catastrophic"),
        ]
        classified = loop.classify_violations(violations)

        assert len(classified["error"]) == 1
        assert classified["error"][0].severity == "catastrophic"
        # All other buckets must be empty.
        assert classified["critical"] == []
        assert classified["warning"] == []
        assert classified["info"] == []

    def test_classify_violations_empty_list(self) -> None:
        """An empty violations list returns a dict with four empty lists."""
        loop = ContractFixLoop()
        classified = loop.classify_violations([])

        assert set(classified.keys()) == {"critical", "error", "warning", "info"}
        for group in classified.values():
            assert group == []


# ---------------------------------------------------------------------------
# feed_violations_to_builder
# ---------------------------------------------------------------------------

class TestFeedViolationsToBuilder:
    """Tests for ContractFixLoop.feed_violations_to_builder."""

    @pytest.mark.asyncio
    async def test_feed_violations_writes_fix_instructions(
        self, tmp_path: Path
    ) -> None:
        """FIX_INSTRUCTIONS.md is written inside builder_dir."""
        loop = ContractFixLoop()
        builder_dir = tmp_path / "builder"
        violations = [_make_violation(severity="error", code="E001")]

        mock_proc = _mock_process()
        # Pre-write STATE.json so parse_builder_state finds it
        builder_dir.mkdir(parents=True, exist_ok=True)
        _write_state_json(builder_dir)

        with patch("src.integrator.fix_loop.asyncio.create_subprocess_exec",
                    new_callable=AsyncMock, return_value=mock_proc):
            await loop.feed_violations_to_builder("svc-1", violations, builder_dir)

        instructions = builder_dir / "FIX_INSTRUCTIONS.md"
        assert instructions.exists()
        content = instructions.read_text(encoding="utf-8")
        assert "E001" in content

    @pytest.mark.asyncio
    async def test_fix_instructions_has_priority_sections(
        self, tmp_path: Path
    ) -> None:
        """The generated markdown contains priority section headers.

        The new fix_loop maps severity to priority:
        critical -> P0, error -> P1, warning/info -> P2.
        """
        loop = ContractFixLoop()
        builder_dir = tmp_path / "builder"
        violations = [
            _make_violation(severity="critical", code="C001"),
            _make_violation(severity="warning", code="W001"),
        ]

        mock_proc = _mock_process()
        builder_dir.mkdir(parents=True, exist_ok=True)
        _write_state_json(builder_dir)

        with patch("src.integrator.fix_loop.asyncio.create_subprocess_exec",
                    new_callable=AsyncMock, return_value=mock_proc):
            await loop.feed_violations_to_builder("svc-2", violations, builder_dir)

        content = (builder_dir / "FIX_INSTRUCTIONS.md").read_text(encoding="utf-8")
        # Now uses priority-based format
        assert "P0" in content  # critical -> P0
        assert "P2" in content  # warning -> P2
        assert "C001" in content
        assert "W001" in content

    @pytest.mark.asyncio
    async def test_feed_violations_subprocess_args(
        self, tmp_path: Path
    ) -> None:
        """create_subprocess_exec is called with the correct arguments."""
        loop = ContractFixLoop()
        builder_dir = tmp_path / "builder"
        violations = [_make_violation()]

        mock_proc = _mock_process()
        builder_dir.mkdir(parents=True, exist_ok=True)
        _write_state_json(builder_dir)

        with patch("src.integrator.fix_loop.asyncio.create_subprocess_exec",
                    new_callable=AsyncMock, return_value=mock_proc) as mock_exec:
            await loop.feed_violations_to_builder("svc-3", violations, builder_dir)

        # Verify key positional args (source also passes env= kwarg
        # with filtered environment variables)
        call_args = mock_exec.call_args
        assert call_args[0][0] == sys.executable
        assert call_args[0][1] == "-m"
        assert call_args[0][2] == "agent_team"
        assert "--cwd" in call_args[0]
        assert str(builder_dir) in call_args[0]
        assert call_args[1]["stdout"] == asyncio.subprocess.PIPE
        assert call_args[1]["stderr"] == asyncio.subprocess.PIPE

    @pytest.mark.asyncio
    async def test_feed_violations_extracts_cost(
        self, tmp_path: Path
    ) -> None:
        """Cost is extracted from STATE.json written by the builder."""
        loop = ContractFixLoop()
        builder_dir = tmp_path / "builder"
        violations = [_make_violation()]

        mock_proc = _mock_process()
        builder_dir.mkdir(parents=True, exist_ok=True)
        _write_state_json(builder_dir, total_cost=4.25)

        with patch("src.integrator.fix_loop.asyncio.create_subprocess_exec",
                    new_callable=AsyncMock, return_value=mock_proc):
            result = await loop.feed_violations_to_builder("svc-4", violations, builder_dir)

        # feed_violations_to_builder now returns BuilderResult
        assert isinstance(result, BuilderResult)
        assert result.total_cost == 4.25

    @pytest.mark.asyncio
    async def test_feed_violations_timeout_kills_process(
        self, tmp_path: Path
    ) -> None:
        """When the subprocess times out, proc.kill() is called."""
        loop = ContractFixLoop(timeout=1)
        builder_dir = tmp_path / "builder"
        violations = [_make_violation()]

        mock_proc = _mock_process()
        # Simulate timeout: returncode stays None until killed.
        mock_proc.returncode = None

        mock_proc.kill = MagicMock(side_effect=lambda: None)
        # After kill, the second wait should resolve.
        mock_proc.wait = AsyncMock(return_value=-9)

        builder_dir.mkdir(parents=True, exist_ok=True)
        _write_state_json(builder_dir)

        async def _fake_wait_for(coro, *, timeout=None):
            """Close the coroutine to avoid 'was never awaited' warning."""
            coro.close()
            raise asyncio.TimeoutError

        with patch("src.integrator.fix_loop.asyncio.create_subprocess_exec",
                    new_callable=AsyncMock, return_value=mock_proc), \
             patch("src.integrator.fix_loop.asyncio.wait_for",
                    side_effect=_fake_wait_for):
            await loop.feed_violations_to_builder("svc-5", violations, builder_dir)

        mock_proc.kill.assert_called_once()

    @pytest.mark.asyncio
    async def test_feed_violations_missing_state_json(
        self, tmp_path: Path
    ) -> None:
        """Cost defaults to 0.0 when STATE.json does not exist."""
        loop = ContractFixLoop()
        builder_dir = tmp_path / "builder"
        violations = [_make_violation()]

        mock_proc = _mock_process()
        builder_dir.mkdir(parents=True, exist_ok=True)
        # Don't write STATE.json — defaults should apply

        with patch("src.integrator.fix_loop.asyncio.create_subprocess_exec",
                    new_callable=AsyncMock, return_value=mock_proc):
            result = await loop.feed_violations_to_builder("svc-6", violations, builder_dir)

        # BuilderResult with defaults when STATE.json missing
        assert isinstance(result, BuilderResult)
        assert result.total_cost == 0.0
        assert result.success is False

    @pytest.mark.asyncio
    async def test_feed_violations_creates_builder_dir(
        self, tmp_path: Path
    ) -> None:
        """builder_dir is created if it does not already exist."""
        loop = ContractFixLoop()
        builder_dir = tmp_path / "nested" / "deep" / "builder"
        assert not builder_dir.exists()

        violations = [_make_violation()]
        mock_proc = _mock_process()

        with patch("src.integrator.fix_loop.asyncio.create_subprocess_exec",
                    new_callable=AsyncMock, return_value=mock_proc):
            await loop.feed_violations_to_builder("svc-7", violations, builder_dir)

        assert builder_dir.exists()
        assert builder_dir.is_dir()

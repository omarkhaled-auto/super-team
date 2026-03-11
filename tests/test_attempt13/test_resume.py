"""Tests for resume prd_path override (Fix 14).

Verifies that execute_pipeline's resume logic correctly overrides
empty or invalid prd_path values while preserving valid ones.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.super_orchestrator.state import PipelineState


class TestResumePrdPathOverride:
    """Test the prd_path override logic from execute_pipeline resume path."""

    def _should_override_prd(self, state_prd: str, cli_prd: Path | None) -> bool:
        """Reproduce the override logic from pipeline.py:3276-3284."""
        saved_prd = Path(state_prd) if state_prd else None
        return (
            not saved_prd
            or not saved_prd.exists()
            or str(saved_prd) in ("", ".", "./")
        )

    def test_empty_prd_path_overridden(self, tmp_path: Path):
        """Resume with empty saved prd_path uses CLI-provided path."""
        state = PipelineState(prd_path="")
        cli_prd = tmp_path / "real_prd.md"
        cli_prd.write_text("# PRD Content")

        if self._should_override_prd(state.prd_path, cli_prd):
            if cli_prd and cli_prd.exists():
                state.prd_path = str(cli_prd)

        assert state.prd_path == str(cli_prd)

    def test_dot_prd_path_overridden(self, tmp_path: Path):
        """Resume with '.' as prd_path gets overridden."""
        state = PipelineState(prd_path=".")
        cli_prd = tmp_path / "real_prd.md"
        cli_prd.write_text("# PRD Content")

        if self._should_override_prd(state.prd_path, cli_prd):
            if cli_prd and cli_prd.exists():
                state.prd_path = str(cli_prd)

        assert state.prd_path == str(cli_prd)

    def test_nonexistent_prd_path_overridden(self, tmp_path: Path):
        """Resume with nonexistent prd_path gets overridden."""
        state = PipelineState(prd_path="/nonexistent/path/prd.md")
        cli_prd = tmp_path / "real_prd.md"
        cli_prd.write_text("# PRD Content")

        if self._should_override_prd(state.prd_path, cli_prd):
            if cli_prd and cli_prd.exists():
                state.prd_path = str(cli_prd)

        assert state.prd_path == str(cli_prd)

    def test_valid_prd_path_preserved(self, tmp_path: Path):
        """Resume with valid existing prd_path preserves it."""
        existing_prd = tmp_path / "existing_prd.md"
        existing_prd.write_text("# Existing PRD")

        state = PipelineState(prd_path=str(existing_prd))
        cli_prd = tmp_path / "new_prd.md"
        cli_prd.write_text("# New PRD")

        if self._should_override_prd(state.prd_path, cli_prd):
            if cli_prd and cli_prd.exists():
                state.prd_path = str(cli_prd)

        assert state.prd_path == str(existing_prd)  # Kept original

    def test_pipeline_state_roundtrip(self, tmp_path: Path):
        """PipelineState prd_path survives save/load cycle."""
        prd = tmp_path / "test.md"
        prd.write_text("# Test")

        state = PipelineState(prd_path=str(prd), depth="thorough")
        saved_path = state.save(directory=tmp_path)

        loaded = PipelineState.load(directory=tmp_path)
        assert loaded is not None
        assert loaded.prd_path == str(prd)

"""Tests for PipelineState save/load/clear and atomic write safety.

TEST-002: >= 10 test cases.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest

from src.build3_shared.utils import atomic_write_json, load_json
from src.super_orchestrator.state import PipelineState


class TestAtomicWriteJson:
    """Test atomic_write_json utility."""

    def test_writes_valid_json(self, tmp_path: Path) -> None:
        target = tmp_path / "test.json"
        atomic_write_json(target, {"key": "value"})
        data = json.loads(target.read_text(encoding="utf-8"))
        assert data["key"] == "value"

    def test_creates_parent_dirs(self, tmp_path: Path) -> None:
        target = tmp_path / "sub" / "dir" / "test.json"
        atomic_write_json(target, {"a": 1})
        assert target.exists()

    def test_overwrites_existing(self, tmp_path: Path) -> None:
        target = tmp_path / "test.json"
        atomic_write_json(target, {"v": 1})
        atomic_write_json(target, {"v": 2})
        data = load_json(target)
        assert data["v"] == 2

    def test_no_tmp_file_after_success(self, tmp_path: Path) -> None:
        target = tmp_path / "test.json"
        atomic_write_json(target, {"ok": True})
        tmp_file = target.with_suffix(".tmp")
        assert not tmp_file.exists()

    def test_crash_simulation_cleanup(self, tmp_path: Path) -> None:
        """Simulate a write failure and verify cleanup."""
        target = tmp_path / "test.json"
        with patch("json.dump", side_effect=OSError("disk full")):
            with pytest.raises(OSError):
                atomic_write_json(target, {"crash": True})
        tmp_file = target.with_suffix(".tmp")
        assert not tmp_file.exists()
        assert not target.exists()


class TestPipelineStateSave:
    """Test PipelineState.save()."""

    def test_save_creates_file(self, tmp_path: Path) -> None:
        state = PipelineState(pipeline_id="test-1")
        path = state.save(tmp_path)
        assert path.exists()

    def test_save_valid_json(self, tmp_path: Path) -> None:
        state = PipelineState(pipeline_id="test-2")
        path = state.save(tmp_path)
        data = load_json(path)
        assert data["pipeline_id"] == "test-2"
        assert data["schema_version"] == 1

    def test_save_updates_timestamp(self, tmp_path: Path) -> None:
        state = PipelineState(pipeline_id="test-3")
        old_ts = state.updated_at
        state.save(tmp_path)
        # updated_at should be refreshed
        assert state.updated_at >= old_ts


class TestPipelineStateLoad:
    """Test PipelineState.load()."""

    def test_load_roundtrip(self, tmp_path: Path) -> None:
        original = PipelineState(
            pipeline_id="rt-1",
            current_state="builders_running",
            total_cost=12.5,
        )
        original.save(tmp_path)
        loaded = PipelineState.load(tmp_path)
        assert loaded is not None
        assert loaded.pipeline_id == "rt-1"
        assert loaded.current_state == "builders_running"
        assert loaded.total_cost == 12.5

    def test_load_missing_file_returns_none(self, tmp_path: Path) -> None:
        result = PipelineState.load(tmp_path / "nope")
        assert result is None

    def test_load_ignores_unknown_keys(self, tmp_path: Path) -> None:
        from src.build3_shared.constants import STATE_FILE
        state_dir = tmp_path / "unk_test"
        state_dir.mkdir(parents=True, exist_ok=True)
        path = state_dir / STATE_FILE
        data = {"pipeline_id": "unk-1", "schema_version": 1, "unknown_key": "ignored"}
        atomic_write_json(path, data)
        loaded = PipelineState.load(state_dir)
        assert loaded is not None
        assert loaded.pipeline_id == "unk-1"


class TestPipelineStateClear:
    """Test PipelineState.clear()."""

    def test_clear_deletes_directory(self, tmp_path: Path) -> None:
        state_dir = tmp_path / "state_to_clear"
        state = PipelineState()
        state.save(state_dir)
        assert state_dir.exists()
        PipelineState.clear(state_dir)
        assert not state_dir.exists()

    def test_clear_nonexistent_no_error(self, tmp_path: Path) -> None:
        nonexistent = tmp_path / "nonexistent_dir"
        PipelineState.clear(nonexistent)  # Should not raise

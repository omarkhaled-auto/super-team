"""Tests for config additions (Fix 4, Fix 20, Fix 21).

Verifies that BuilderConfig has poll_interval_s, timeout values are correct,
and display functions accept keyword args.
"""

from __future__ import annotations

import dataclasses

import pytest

from src.super_orchestrator.config import (
    BuilderConfig,
    SuperOrchestratorConfig,
)
from src.super_orchestrator.display import print_pipeline_header
from src.super_orchestrator.state import PipelineState


class TestBuilderConfigPollInterval:
    """Test poll_interval_s field in BuilderConfig."""

    def test_poll_interval_exists(self):
        """BuilderConfig has poll_interval_s field."""
        config = BuilderConfig()
        assert hasattr(config, "poll_interval_s")

    def test_poll_interval_default_30(self):
        """Default poll_interval_s is 30 seconds."""
        config = BuilderConfig()
        assert config.poll_interval_s == 30

    def test_poll_interval_customizable(self):
        """poll_interval_s can be overridden."""
        config = BuilderConfig(poll_interval_s=60)
        assert config.poll_interval_s == 60

    def test_poll_interval_is_int(self):
        """poll_interval_s is typed as int."""
        fields = {f.name: f for f in dataclasses.fields(BuilderConfig)}
        assert "poll_interval_s" in fields
        assert fields["poll_interval_s"].type == "int"


class TestBuilderConfigTimeout:
    """Test timeout_per_builder configuration."""

    def test_default_timeout(self):
        """Default timeout_per_builder value."""
        config = BuilderConfig()
        assert config.timeout_per_builder > 0

    def test_timeout_from_super_config(self):
        """SuperOrchestratorConfig builder timeout is accessible."""
        config = SuperOrchestratorConfig()
        assert config.builder.timeout_per_builder > 0

    def test_max_concurrent_default(self):
        """Default max_concurrent is 3."""
        config = BuilderConfig()
        assert config.max_concurrent == 3


class TestPrintPipelineHeaderKwargs:
    """Test that print_pipeline_header accepts keyword args (Fix 21)."""

    def test_accepts_keyword_args(self):
        """print_pipeline_header works with keyword arguments."""
        state = PipelineState(
            pipeline_id="test-123",
            prd_path="/test/prd.md",
        )
        # Should not raise TypeError -- keyword args must be accepted
        print_pipeline_header(
            state,
            pipeline_id=state.pipeline_id,
            prd_path=state.prd_path,
        )

    def test_accepts_positional_and_keyword(self):
        """print_pipeline_header works with mixed positional and keyword args."""
        state = PipelineState(
            pipeline_id="test-123",
            prd_path="/test/prd.md",
        )
        # tracker=None is the second positional arg
        print_pipeline_header(state, None, pipeline_id="test-123")

    def test_accepts_state_only(self):
        """print_pipeline_header works with just state arg."""
        state = PipelineState(
            pipeline_id="test-123",
            prd_path="/test/prd.md",
        )
        print_pipeline_header(state)

"""Tests for GracefulShutdown.

TEST-010: >= 6 test cases covering set_state, emergency_save, should_stop, signal handler.
"""

from __future__ import annotations

import signal
from unittest.mock import MagicMock, patch

import pytest

from src.super_orchestrator.shutdown import GracefulShutdown


class TestGracefulShutdown:
    """Test GracefulShutdown class."""

    def test_initial_should_stop_false(self) -> None:
        gs = GracefulShutdown()
        assert gs.should_stop is False

    def test_set_should_stop(self) -> None:
        gs = GracefulShutdown()
        gs.should_stop = True
        assert gs.should_stop is True

    def test_set_state(self) -> None:
        gs = GracefulShutdown()
        mock_state = MagicMock()
        gs.set_state(mock_state)
        assert gs._state is mock_state

    def test_signal_handler_sets_should_stop(self) -> None:
        gs = GracefulShutdown()
        gs._signal_handler(signal.SIGINT, None)
        assert gs.should_stop is True

    def test_emergency_save_no_state(self) -> None:
        gs = GracefulShutdown()
        # Should not raise when no state is set
        gs._emergency_save()

    def test_emergency_save_with_state(self) -> None:
        gs = GracefulShutdown()
        mock_state = MagicMock()
        gs.set_state(mock_state)
        gs._emergency_save()
        assert mock_state.interrupted is True
        mock_state.save.assert_called_once()

    def test_reentrancy_guard(self) -> None:
        gs = GracefulShutdown()
        gs._handling = True
        gs._signal_handler(signal.SIGINT, None)
        # should_stop should NOT be set because handler returned early
        assert gs.should_stop is False

    def test_async_handler_sets_should_stop(self) -> None:
        gs = GracefulShutdown()
        gs._async_handler()
        assert gs.should_stop is True

    def test_install_windows(self) -> None:
        gs = GracefulShutdown()
        with patch("sys.platform", "win32"):
            with patch("signal.signal") as mock_signal:
                gs.install()
                assert mock_signal.call_count >= 2

    def test_emergency_save_failure_does_not_raise(self) -> None:
        gs = GracefulShutdown()
        mock_state = MagicMock()
        mock_state.save.side_effect = OSError("disk full")
        gs.set_state(mock_state)
        # Should not raise -- logs the error instead
        gs._emergency_save()

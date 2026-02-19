"""Graceful shutdown handler for the pipeline.

Handles both Windows (``signal.signal``) and Unix
(``loop.add_signal_handler``) signal registration with a reentrancy guard.
"""

from __future__ import annotations

import asyncio
import logging
import signal
import sys
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from src.super_orchestrator.state import PipelineState

logger = logging.getLogger(__name__)


class GracefulShutdown:
    """Manages graceful shutdown on SIGINT / SIGTERM.

    Usage::

        shutdown = GracefulShutdown()
        shutdown.install()
        shutdown.set_state(pipeline_state)

        # In the pipeline loop:
        if shutdown.should_stop:
            ...
    """

    def __init__(self) -> None:
        self._should_stop = False
        self._state: PipelineState | None = None
        self._handling = False  # reentrancy guard

    @property
    def should_stop(self) -> bool:
        """Whether a shutdown signal has been received."""
        return self._should_stop

    @should_stop.setter
    def should_stop(self, value: bool) -> None:
        self._should_stop = value

    def set_state(self, state: Any) -> None:
        """Inject the pipeline state for emergency saving.

        This uses deferred injection so the shutdown handler can be
        created before the state object exists.

        Args:
            state: A ``PipelineState`` instance (or duck-typed equivalent).
        """
        self._state = state

    def install(self) -> None:
        """Register signal handlers for SIGINT and SIGTERM.

        On Windows, uses ``signal.signal`` directly.
        On Unix, uses ``loop.add_signal_handler`` if a running event loop
        is available, falling back to ``signal.signal``.
        """
        if sys.platform == "win32":
            signal.signal(signal.SIGINT, self._signal_handler)
            signal.signal(signal.SIGTERM, self._signal_handler)
        else:
            try:
                loop = asyncio.get_running_loop()
                for sig in (signal.SIGINT, signal.SIGTERM):
                    loop.add_signal_handler(sig, self._async_handler)
            except RuntimeError:
                # No running loop -- fall back to signal.signal
                signal.signal(signal.SIGINT, self._signal_handler)
                signal.signal(signal.SIGTERM, self._signal_handler)

    def _signal_handler(self, signum: int, frame: Any) -> None:
        """Synchronous signal handler (Windows / fallback)."""
        if self._handling:
            return  # reentrancy guard
        self._handling = True
        logger.warning("Received signal %s -- initiating graceful shutdown", signum)
        self._should_stop = True
        self._emergency_save()
        self._handling = False

    def _async_handler(self) -> None:
        """Async-compatible signal handler (Unix)."""
        if self._handling:
            return  # reentrancy guard
        self._handling = True
        logger.warning("Received shutdown signal -- initiating graceful shutdown")
        self._should_stop = True
        self._emergency_save()
        self._handling = False

    def _emergency_save(self) -> None:
        """Attempt to save pipeline state during emergency shutdown."""
        if self._state is None:
            logger.warning("No pipeline state to save during emergency shutdown")
            return
        try:
            self._state.interrupted = True
            self._state.interrupt_reason = "Signal received"
            self._state.save()
            logger.info("Emergency state save completed")
        except Exception:
            logger.exception("Failed to save state during emergency shutdown")

"""Structured JSON logging with trace_id support."""
from __future__ import annotations

import contextvars
import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

# Context variable for trace_id
trace_id_var: contextvars.ContextVar[str] = contextvars.ContextVar(
    "trace_id", default=""
)


class JSONFormatter(logging.Formatter):
    """Custom JSON log formatter."""

    def __init__(self, service_name: str = "unknown") -> None:
        super().__init__()
        self.service_name = service_name

    def format(self, record: logging.LogRecord) -> str:
        log_entry: dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "service_name": self.service_name,
            "trace_id": trace_id_var.get(""),
            "message": record.getMessage(),
        }
        if record.exc_info and record.exc_info[1]:
            log_entry["exception"] = str(record.exc_info[1])
        return json.dumps(log_entry)


def setup_logging(service_name: str, level: str = "INFO") -> logging.Logger:
    """Configure structured JSON logging for a service.

    Args:
        service_name: Name of the service for log entries.
        level: Log level string (e.g. "INFO", "DEBUG").

    Returns:
        Configured logger instance.
    """
    logger = logging.getLogger(service_name)
    logger.setLevel(getattr(logging, level.upper(), logging.INFO))

    # Remove existing handlers
    logger.handlers.clear()

    handler = logging.StreamHandler()
    handler.setFormatter(JSONFormatter(service_name=service_name))
    logger.addHandler(handler)

    return logger


class TraceIDMiddleware(BaseHTTPMiddleware):
    """FastAPI middleware that sets a unique trace_id per request."""

    async def dispatch(self, request: Request, call_next: Any) -> Response:
        request_trace_id = str(uuid.uuid4())
        trace_id_var.set(request_trace_id)
        response = await call_next(request)
        response.headers["X-Trace-ID"] = request_trace_id
        return response

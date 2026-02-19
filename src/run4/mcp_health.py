"""MCP and HTTP health-check utilities for Run 4."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

import httpx

logger = logging.getLogger(__name__)


async def poll_until_healthy(
    service_urls: dict[str, str],
    timeout_s: float = 120,
    interval_s: float = 3.0,
    required_consecutive: int = 2,
) -> dict[str, dict]:
    """Poll HTTP health endpoints until all services report healthy.

    Each service must return HTTP 200 for *required_consecutive*
    consecutive checks before it is considered healthy.

    Args:
        service_urls: Mapping of service name to health-check URL.
        timeout_s: Maximum seconds to wait for all services.
        interval_s: Seconds between poll attempts.
        required_consecutive: Number of consecutive successes required.

    Returns:
        Mapping of service name to health result dict containing
        ``status``, ``response_time_ms``, and ``consecutive_ok`` keys.

    Raises:
        TimeoutError: If not all services become healthy within *timeout_s*.
    """
    results: dict[str, dict[str, Any]] = {}
    consecutive: dict[str, int] = {name: 0 for name in service_urls}
    healthy_set: set[str] = set()

    deadline = time.monotonic() + timeout_s
    logger.info(
        "Polling %d services for health (timeout=%ss, interval=%ss)",
        len(service_urls),
        timeout_s,
        interval_s,
    )

    async with httpx.AsyncClient(timeout=10.0) as client:
        while time.monotonic() < deadline:
            for name, url in service_urls.items():
                if name in healthy_set:
                    continue
                start = time.monotonic()
                try:
                    resp = await client.get(url)
                    elapsed_ms = (time.monotonic() - start) * 1000
                    if resp.status_code == 200:
                        consecutive[name] += 1
                        results[name] = {
                            "status": "healthy",
                            "response_time_ms": round(elapsed_ms, 1),
                            "consecutive_ok": consecutive[name],
                        }
                        if consecutive[name] >= required_consecutive:
                            healthy_set.add(name)
                            logger.info("Service %s is healthy", name)
                    else:
                        consecutive[name] = 0
                        results[name] = {
                            "status": "unhealthy",
                            "http_status": resp.status_code,
                            "response_time_ms": round(elapsed_ms, 1),
                            "consecutive_ok": 0,
                        }
                except httpx.HTTPError as exc:
                    consecutive[name] = 0
                    results[name] = {
                        "status": "error",
                        "error": str(exc),
                        "consecutive_ok": 0,
                    }

            if healthy_set == set(service_urls.keys()):
                logger.info("All %d services healthy", len(service_urls))
                return results

            await asyncio.sleep(interval_s)

    unhealthy = set(service_urls.keys()) - healthy_set
    raise TimeoutError(
        f"Services not healthy after {timeout_s}s: {', '.join(sorted(unhealthy))}"
    )


async def check_mcp_health(
    server_params: Any,
    timeout: float = 30.0,
) -> dict:
    """Spawn an MCP server, initialise it, list tools, and return health info.

    Uses the ``mcp`` SDK to create a stdio session with the provided
    server parameters.

    Args:
        server_params: ``StdioServerParameters`` instance from the MCP SDK.
        timeout: Maximum seconds for the entire health check.

    Returns:
        Dict with ``status``, ``tools_count``, ``tool_names``, and
        ``error`` keys.
    """
    from mcp import ClientSession
    from mcp.client.stdio import stdio_client

    result: dict[str, Any] = {
        "status": "unhealthy",
        "tools_count": 0,
        "tool_names": [],
        "error": None,
    }

    try:
        async with asyncio.timeout(timeout):
            async with stdio_client(server_params) as (read_stream, write_stream):
                async with ClientSession(read_stream, write_stream) as session:
                    await session.initialize()
                    tools_response = await session.list_tools()
                    tool_names = [t.name for t in tools_response.tools]
                    result["status"] = "healthy"
                    result["tools_count"] = len(tool_names)
                    result["tool_names"] = tool_names
                    logger.info(
                        "MCP server healthy — %d tools available", len(tool_names)
                    )
    except TimeoutError:
        result["error"] = f"MCP health check timed out after {timeout}s"
        logger.warning(result["error"])
    except Exception as exc:
        result["error"] = str(exc)
        logger.warning("MCP health check failed: %s", exc)

    return result

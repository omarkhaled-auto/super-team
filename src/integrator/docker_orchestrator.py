"""Docker Compose orchestration.

Manages the lifecycle of Docker Compose services: start, stop,
health checking, URL resolution, log retrieval, and restart.
All subprocess calls capture stdout and stderr.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

from src.build3_shared.models import ServiceInfo
from src.integrator.service_discovery import ServiceDiscovery

logger = logging.getLogger(__name__)


class DockerOrchestrator:
    """Orchestrates Docker Compose services.

    Supports a single compose file path (backward compatible) or a list of
    compose file paths for the 5-file merge strategy (TECH-004).
    """

    def __init__(
        self,
        compose_file: Path | str | list[Path | str],
        project_name: str = "super-team",
    ) -> None:
        if isinstance(compose_file, list):
            self.compose_files: list[Path] = [Path(f) for f in compose_file]
        else:
            self.compose_files = [Path(compose_file)]
        # Backward-compatible attribute: first file in the list
        self.compose_file = self.compose_files[0]
        self.project_name = project_name
        self._discovery = ServiceDiscovery(
            compose_file=self.compose_files if len(self.compose_files) > 1 else self.compose_file,
            project_name=self.project_name,
        )

    def _run_sync(self, *args: str) -> tuple[int, str, str]:
        """Run a docker compose command synchronously.

        Uses ``subprocess.run`` directly instead of
        ``asyncio.create_subprocess_exec`` to avoid Windows-specific
        ``CancelledError`` issues when MCP stdio sessions leave
        dangling ``anyio`` cancel scopes in the event loop.

        Returns:
            Tuple of (return_code, stdout, stderr).
        """
        import subprocess

        cmd = ["docker", "compose"]
        for f in self.compose_files:
            cmd.extend(["-f", str(f)])
        cmd.extend(["-p", self.project_name, *args])
        logger.debug("Running: %s", " ".join(cmd))

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            errors="replace",
        )
        return (result.returncode, result.stdout, result.stderr)

    async def _run(self, *args: str) -> tuple[int, str, str]:
        """Async wrapper around :meth:`_run_sync`.

        Delegates to ``loop.run_in_executor`` with a dedicated
        ``ThreadPoolExecutor`` to ensure the synchronous subprocess
        call runs outside the asyncio event loop and is not affected
        by dangling ``anyio`` cancel scopes.
        """
        import concurrent.futures

        loop = asyncio.get_running_loop()
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            return await loop.run_in_executor(
                pool, lambda: self._run_sync(*args)
            )

    async def start_services(self) -> dict[str, ServiceInfo]:
        """Start all services via ``docker compose up -d``.

        Returns:
            Dict mapping service name to ServiceInfo.
        """
        rc, stdout, stderr = await self._run("up", "-d", "--build")
        if rc != 0:
            logger.error("Failed to start services: %s", stderr)
            return {}

        # List running services
        rc2, ps_out, _ = await self._run("ps", "--format", "{{.Service}}")
        service_names = [s.strip() for s in ps_out.strip().splitlines() if s.strip()]
        result: dict[str, ServiceInfo] = {}
        for name in service_names:
            url = await self.get_service_url(name)
            result[name] = ServiceInfo(
                service_id=name,
                domain=name,
                build_dir=name,
            )
        return result

    async def stop_services(self) -> dict[str, Any]:
        """Stop all services via ``docker compose down``.

        Returns:
            Dict with ``success`` key.
        """
        rc, stdout, stderr = await self._run("down", "--remove-orphans")
        return {"success": rc == 0, "error": stderr if rc != 0 else ""}

    async def wait_for_healthy(
        self,
        services: dict[str, str] | None = None,
        timeout_seconds: int = 120,
        poll_interval_seconds: int = 3,
    ) -> dict[str, Any]:
        """Poll until all services are healthy or timeout.

        Delegates to ``ServiceDiscovery.wait_all_healthy()`` per WIRE-006.

        Args:
            services: Mapping of service name to health URL. If None,
                attempts to discover services from compose.
            timeout_seconds: Maximum wait time.
            poll_interval_seconds: Seconds between polls.

        Returns:
            Dict with ``all_healthy`` and per-service ``services`` status.
        """
        if services is None:
            services = {}
        return await self._discovery.wait_all_healthy(
            services=services,
            timeout_seconds=timeout_seconds,
            poll_interval=poll_interval_seconds,
        )

    async def is_service_healthy(self, service_name: str, url: str) -> bool:
        """Check if a single service is healthy.

        Args:
            service_name: Name of the service.
            url: Health check URL.

        Returns:
            True if the service is healthy.
        """
        return await self._discovery.check_health(service_name, url)

    async def get_service_url(self, service_name: str, port: int = 8080) -> str:
        """Get the URL for a running service.

        Args:
            service_name: Name of the compose service.
            port: Internal port to look up.

        Returns:
            URL string (e.g. ``http://localhost:32768``).
        """
        rc, out, _ = await self._run("port", service_name, str(port))
        host_port = out.strip()
        if not host_port:
            return f"http://localhost:{port}"
        # Format is usually 0.0.0.0:PORT
        if ":" in host_port:
            mapped_port = host_port.rsplit(":", 1)[-1]
            return f"http://localhost:{mapped_port}"
        return f"http://localhost:{host_port}"

    async def get_service_logs(
        self, service_name: str, tail: int = 100
    ) -> str:
        """Retrieve recent logs for a service.

        Args:
            service_name: Compose service name.
            tail: Number of lines to retrieve.

        Returns:
            Log output as a string.
        """
        rc, out, stderr = await self._run(
            "logs", "--tail", str(tail), service_name
        )
        return out or stderr

    async def restart_service(self, service_name: str) -> dict[str, Any]:
        """Restart a single service.

        Args:
            service_name: Compose service name.

        Returns:
            Dict with ``success`` key.
        """
        rc, _, stderr = await self._run("restart", service_name)
        return {"success": rc == 0, "error": stderr if rc != 0 else ""}

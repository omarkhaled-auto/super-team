"""Service discovery via Docker Compose port inspection and health checking."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

import httpx

logger = logging.getLogger(__name__)


class ServiceDiscovery:
    """Discovers and health-checks services running in Docker Compose."""

    def __init__(
        self,
        compose_file: Path | str,
        project_name: str = "super-team",
    ) -> None:
        self.compose_file = Path(compose_file)
        self.project_name = project_name

    async def _run_compose(self, *args: str) -> tuple[int, str, str]:
        """Run a docker compose command."""
        cmd = [
            "docker", "compose",
            "-f", str(self.compose_file),
            "-p", self.project_name,
            *args,
        ]
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        return (
            proc.returncode or 0,
            stdout.decode("utf-8", errors="replace"),
            stderr.decode("utf-8", errors="replace"),
        )

    def get_service_ports(self) -> dict[str, int]:
        """Parse ``docker compose ps`` output to get mapped ports.

        This is a synchronous method per PRD REQ-018.

        Returns:
            Dict mapping service name to host port.
        """
        import subprocess

        cmd = [
            "docker", "compose",
            "-f", str(self.compose_file),
            "-p", self.project_name,
            "ps", "--format", "{{.Service}}:{{.Ports}}",
        ]
        try:
            completed = subprocess.run(
                cmd, capture_output=True, text=True, timeout=30,
            )
            out = completed.stdout
        except Exception as exc:
            logger.warning("Failed to get service ports: %s", exc)
            return {}

        result: dict[str, int] = {}
        for line in out.strip().splitlines():
            line = line.strip()
            if ":" not in line:
                continue
            parts = line.split(":", 1)
            service_name = parts[0].strip()
            ports_str = parts[1].strip()
            if not service_name or not ports_str:
                continue
            # Parse port mapping like "0.0.0.0:32768->8080/tcp"
            for mapping in ports_str.split(","):
                mapping = mapping.strip()
                if "->" in mapping:
                    host_part = mapping.split("->")[0]
                    if ":" in host_part:
                        try:
                            port = int(host_part.rsplit(":", 1)[-1])
                            result[service_name] = port
                            break
                        except ValueError:
                            continue
        return result

    async def check_health(
        self,
        service_name: str,
        url: str,
    ) -> bool:
        """Check a service's health endpoint.

        Args:
            service_name: Name of the service being checked.
            url: Full URL to the health endpoint.

        Returns:
            True if the service is healthy, False otherwise.
        """
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.get(url)
                healthy = resp.status_code < 400
                if not healthy:
                    logger.warning(
                        "Service '%s' unhealthy: status %d from %s",
                        service_name, resp.status_code, url,
                    )
                return healthy
        except httpx.HTTPError as exc:
            logger.warning(
                "Health check failed for '%s' at %s: %s",
                service_name, url, exc,
            )
            return False
        except Exception as exc:
            logger.warning(
                "Health check error for '%s' at %s: %s",
                service_name, url, exc,
            )
            return False

    async def wait_all_healthy(
        self,
        services: dict[str, str],
        timeout_seconds: int = 120,
        poll_interval: int = 3,
    ) -> dict[str, Any]:
        """Wait until all services report healthy or timeout.

        Args:
            services: Mapping of service name to health URL.
            timeout_seconds: Maximum wait time.
            poll_interval: Seconds between polls (default 3s per PRD).

        Returns:
            Dict with ``all_healthy`` and per-service status.
        """
        import time

        deadline = time.monotonic() + timeout_seconds
        statuses: dict[str, bool] = {}

        while time.monotonic() < deadline:
            all_ok = True
            for name, url in services.items():
                healthy = await self.check_health(name, url)
                statuses[name] = healthy
                if not healthy:
                    all_ok = False

            if all_ok and statuses:
                return {"all_healthy": True, "services": statuses}

            await asyncio.sleep(poll_interval)

        return {"all_healthy": False, "services": statuses}

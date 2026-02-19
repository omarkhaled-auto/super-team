"""Traefik v3 configuration generator.

Generates Docker labels with backtick syntax for PathPrefix rules
and static Traefik configuration for the Docker provider.
"""

from __future__ import annotations


class TraefikConfigGenerator:
    """Generates Traefik v3.6 configuration for Docker Compose services."""

    def __init__(self, domain: str = "localhost") -> None:
        self.domain = domain

    def generate_labels(
        self,
        service_name: str = "",
        port: int = 8080,
        path_prefix: str | None = None,
        *,
        service_id: str = "",
    ) -> dict[str, str]:
        """Generate Traefik Docker labels for a service.

        Uses backtick syntax for PathPrefix rules as required by Traefik v3.

        Args:
            service_name: Service name (PRD REQ-016).
            port: Container port the service listens on.
            path_prefix: URL path prefix (defaults to ``/service_name``).
            service_id: Alias for service_name (backwards compat).

        Returns:
            Dictionary of Docker label key-value pairs.
        """
        # Support both service_name (PRD) and service_id (backwards compat)
        name = service_name or service_id
        if path_prefix is None:
            path_prefix = f"/{name}"

        router_name = name.replace("-", "_")
        return {
            "traefik.enable": "true",
            f"traefik.http.routers.{router_name}.rule": f"PathPrefix(`{path_prefix}`)",
            f"traefik.http.routers.{router_name}.entrypoints": "web",
            f"traefik.http.routers.{router_name}.middlewares": f"{router_name}-strip",
            f"traefik.http.middlewares.{router_name}-strip.stripprefix.prefixes": path_prefix,
            f"traefik.http.services.{router_name}.loadbalancer.server.port": str(port),
        }

    def generate_static_config(self) -> str:
        """Generate Traefik v3 static configuration as YAML string.

        Returns:
            YAML string suitable for writing as traefik.yml.
        """
        import yaml

        config = {
            "api": {
                "dashboard": False,
                "insecure": False,
            },
            "entryPoints": {
                "web": {
                    "address": ":80",
                },
            },
            "providers": {
                "docker": {
                    "endpoint": "unix:///var/run/docker.sock",
                    "exposedByDefault": False,
                    "watch": True,
                },
            },
            "ping": {},
            "log": {
                "level": "WARN",
            },
        }
        return yaml.dump(config, default_flow_style=False, sort_keys=False)

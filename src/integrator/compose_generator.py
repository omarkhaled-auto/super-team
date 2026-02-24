"""Docker Compose file generator.

Generates docker-compose.yml with Traefik v3.6 reverse proxy,
PostgreSQL 16-alpine, Redis 7-alpine, and per-service entries
with health checks, Traefik labels, and memory limits.

Supports 5-file compose merge strategy (TECH-004):
    1. docker-compose.infra.yml — postgres, redis, networks, volumes
    2. docker-compose.build1.yml — Build 1 services
    3. docker-compose.traefik.yml — Traefik reverse proxy
    4. docker-compose.generated.yml — generated app services
    5. docker-compose.run4.yml — Run 4 verification overrides

Total Docker RAM budget: 4.5GB (TECH-006).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from src.build3_shared.models import BuilderResult, ServiceInfo
from src.integrator.traefik_config import TraefikConfigGenerator


class ComposeGenerator:
    """Generates Docker Compose v2 YAML files."""

    def __init__(
        self,
        config: Any = None,
        traefik_image: str = "traefik:v3.6",
        postgres_image: str = "postgres:16-alpine",
        redis_image: str = "redis:7-alpine",
        project_name: str = "super-team",
    ) -> None:
        # Accept config: SuperOrchestratorConfig per REQ-015
        if config is not None:
            self.traefik_image = getattr(
                getattr(config, "integration", None), "traefik_image", traefik_image,
            )
        else:
            self.traefik_image = traefik_image
        self.postgres_image = postgres_image
        self.redis_image = redis_image
        self.project_name = project_name
        self._traefik = TraefikConfigGenerator()
        self._config = config

    def generate(
        self,
        services: list[ServiceInfo] | dict | None = None,
        output_path: Path | str | None = None,
        include_traefik: bool = True,
        include_postgres: bool = True,
        include_redis: bool = True,
        *,
        service_map: dict | None = None,
        builder_results: list[BuilderResult] | None = None,
    ) -> str | Path:
        """Generate a docker-compose.yml file.

        Supports both the original signature (services, output_path)
        and the PRD-specified signature (service_map, builder_results)
        which returns a YAML string.

        Args:
            services: List of service definitions to include.
            output_path: Where to write the compose file.
            include_traefik: Whether to include Traefik reverse proxy.
            include_postgres: Whether to include PostgreSQL.
            include_redis: Whether to include Redis.
            service_map: Dict from architect decomposition (PRD REQ-015).
            builder_results: List of BuilderResult (PRD REQ-015).

        Returns:
            Path to the generated compose file, or YAML string if
            service_map is provided without output_path.
        """
        # Handle PRD-style call: generate(service_map=..., builder_results=...)
        if service_map is not None and services is None:
            svc_list = []
            for svc_data in service_map.get("services", []):
                if isinstance(svc_data, dict):
                    svc_list.append(ServiceInfo(
                        service_id=svc_data.get("service_id", svc_data.get("name", "")),
                        domain=svc_data.get("domain", ""),
                        port=svc_data.get("port", 8080),
                    ))
            services = svc_list
        elif services is None:
            services = []
        elif isinstance(services, dict):
            # If services is a dict (service_map), treat as PRD-style
            svc_list = []
            for svc_data in services.get("services", []):
                if isinstance(svc_data, dict):
                    svc_list.append(ServiceInfo(
                        service_id=svc_data.get("service_id", svc_data.get("name", "")),
                        domain=svc_data.get("domain", ""),
                        port=svc_data.get("port", 8080),
                    ))
            services = svc_list

        if output_path is not None:
            output_path = Path(output_path)
        else:
            output_path = None
        compose: dict[str, Any] = {
            "version": "3.8",
            "services": {},
            "networks": {
                "frontend": {
                    "driver": "bridge",
                },
                "backend": {
                    "driver": "bridge",
                },
            },
            "volumes": {},
        }

        if include_traefik:
            compose["services"]["traefik"] = self._traefik_service()

        if include_postgres:
            compose["services"]["postgres"] = self._postgres_service()
            compose["volumes"]["postgres-data"] = None

        if include_redis:
            compose["services"]["redis"] = self._redis_service()

        for svc in services:
            compose["services"][svc.service_id] = self._app_service(svc)

        yaml_str = yaml.dump(compose, default_flow_style=False, sort_keys=False)

        if output_path is not None:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            with open(output_path, "w", encoding="utf-8") as f:
                f.write(yaml_str)
            return output_path

        return yaml_str

    def _traefik_service(self) -> dict[str, Any]:
        """Generate Traefik service definition.

        Traefik is placed on the frontend network only — it must NOT
        be on the backend network to enforce network segmentation.
        Memory limit: 256MB (TECH-006).
        """
        return {
            "image": self.traefik_image,
            "container_name": f"{self.project_name}-traefik",
            "ports": ["80:80"],
            "volumes": [
                "/var/run/docker.sock:/var/run/docker.sock:ro",
            ],
            "command": [
                "--api.dashboard=false",
                "--providers.docker=true",
                "--providers.docker.exposedbydefault=false",
                "--entrypoints.web.address=:80",
                "--ping=true",
            ],
            "networks": ["frontend"],
            "mem_limit": "256m",
            "deploy": {
                "resources": {
                    "limits": {"memory": "256m"},
                },
            },
            "healthcheck": {
                "test": ["CMD", "traefik", "healthcheck", "--ping"],
                "interval": "10s",
                "timeout": "5s",
                "retries": 3,
            },
        }

    def _postgres_service(self) -> dict[str, Any]:
        """Generate PostgreSQL service definition.

        PostgreSQL is placed on the backend network only — it must NOT
        be on the frontend network to enforce network segmentation.
        Memory limit: 512MB (TECH-006).

        Mounts ``./init-db/`` as the Docker init directory so that
        per-service schema creation scripts run on first start.
        """
        return {
            "image": self.postgres_image,
            "container_name": f"{self.project_name}-postgres",
            "environment": {
                "POSTGRES_USER": "${POSTGRES_USER:-app}",
                "POSTGRES_PASSWORD": "${POSTGRES_PASSWORD:-changeme}",
                "POSTGRES_DB": "${POSTGRES_DB:-app}",
            },
            "volumes": [
                "postgres-data:/var/lib/postgresql/data",
                "./init-db:/docker-entrypoint-initdb.d:ro",
            ],
            "networks": ["backend"],
            "mem_limit": "512m",
            "deploy": {
                "resources": {
                    "limits": {"memory": "512m"},
                },
            },
            "healthcheck": {
                "test": ["CMD-SHELL", "pg_isready -U app"],
                "interval": "10s",
                "timeout": "5s",
                "retries": 5,
            },
        }

    def _redis_service(self) -> dict[str, Any]:
        """Generate Redis service definition.

        Redis is placed on the backend network only — it must NOT
        be on the frontend network to enforce network segmentation.
        Memory limit: 256MB (TECH-006).
        """
        return {
            "image": self.redis_image,
            "container_name": f"{self.project_name}-redis",
            "networks": ["backend"],
            "mem_limit": "256m",
            "deploy": {
                "resources": {
                    "limits": {"memory": "256m"},
                },
            },
            "healthcheck": {
                "test": ["CMD", "redis-cli", "ping"],
                "interval": "10s",
                "timeout": "5s",
                "retries": 3,
            },
        }

    @staticmethod
    def _detect_stack(service_info: "ServiceInfo | None") -> str:
        """Detect the technology stack category for a service.

        Returns one of: ``"python"``, ``"typescript"``, ``"frontend"``.
        Defaults to ``"python"`` when the stack cannot be determined.
        """
        if service_info is None:
            return "python"
        stack = service_info.stack
        if not isinstance(stack, dict):
            return "python"
        language = (stack.get("language") or "").lower()
        framework = (stack.get("framework") or "").lower()

        frontend_frameworks = {
            "angular", "react", "vue", "next", "nextjs", "nuxt", "svelte",
        }
        if framework in frontend_frameworks or language in frontend_frameworks:
            return "frontend"

        if language in ("typescript", "javascript", "node", "nodejs"):
            return "typescript"
        if framework in (
            "nestjs", "nest", "express", "koa", "hapi", "fastify",
        ):
            return "typescript"

        return "python"

    @staticmethod
    def _dockerfile_content_for_stack(
        port: int,
        service_info: "ServiceInfo | None" = None,
    ) -> str:
        """Return the Dockerfile content string for the detected stack."""
        stack = ComposeGenerator._detect_stack(service_info)

        if stack == "frontend":
            return (
                "FROM node:20-slim AS build\n"
                "WORKDIR /app\n"
                "COPY package*.json ./\n"
                "RUN npm ci\n"
                "COPY . .\n"
                "RUN npm run build\n"
                "\n"
                "FROM nginx:alpine\n"
                "COPY --from=build /app/dist /usr/share/nginx/html\n"
                "COPY --from=build /app/build /usr/share/nginx/html\n"
                f"EXPOSE {port}\n"
                "HEALTHCHECK --interval=15s --timeout=5s --retries=3 \\\n"
                f"  CMD wget -qO- http://localhost:{port}/ || exit 1\n"
                'CMD ["nginx", "-g", "daemon off;"]\n'
            )

        if stack == "typescript":
            return (
                "FROM node:20-slim\n"
                "WORKDIR /app\n"
                "COPY package*.json ./\n"
                "RUN npm ci\n"
                "COPY . .\n"
                "RUN npm run build\n"
                f"EXPOSE {port}\n"
                "HEALTHCHECK --interval=15s --timeout=5s --retries=3 \\\n"
                f"  CMD curl -f http://localhost:{port}/health || exit 1\n"
                'CMD ["node", "dist/main.js"]\n'
            )

        # Default: Python / FastAPI
        return (
            "FROM python:3.12-slim-bookworm\n"
            "\n"
            "WORKDIR /app\n"
            "COPY requirements.txt .\n"
            "RUN pip install --no-cache-dir -r requirements.txt\n"
            "COPY . .\n"
            f"EXPOSE {port}\n"
            "CMD [\"python\", \"-m\", \"uvicorn\", \"main:app\","
            f" \"--host\", \"0.0.0.0\", \"--port\", \"{port}\"]\n"
        )

    def _app_service(self, svc: ServiceInfo) -> dict[str, Any]:
        """Generate a per-application service definition.

        Backend services are placed on both frontend and backend networks
        so they can receive traffic from Traefik (frontend) and access
        postgres/redis (backend).  Frontend services are placed on the
        frontend network only and do NOT depend on postgres/redis.
        """
        labels = self._traefik.generate_labels(
            service_id=svc.service_id,
            port=svc.port,
        )

        is_frontend = self._detect_stack(svc) == "frontend"

        # Determine health check command based on stack
        if is_frontend:
            health_cmd = (
                f"wget -qO- http://localhost:{svc.port}/ || exit 1"
            )
        else:
            health_cmd = (
                f"curl -f http://localhost:{svc.port}"
                f"{svc.health_endpoint} || exit 1"
            )

        # Build environment variables — backend services get DATABASE_URL
        # with a per-service schema search_path and REDIS_URL.
        env: dict[str, str] = {
            "SERVICE_ID": svc.service_id,
            "PORT": str(svc.port),
        }

        if not is_frontend:
            schema_name = svc.service_id.replace("-", "_") + "_schema"
            env["DATABASE_URL"] = (
                "postgresql://${POSTGRES_USER:-app}:${POSTGRES_PASSWORD:-changeme}"
                "@postgres:5432/${POSTGRES_DB:-app}"
                f"?options=-c search_path={schema_name}"
            )
            env["REDIS_URL"] = "redis://redis:6379/0"

        service_def: dict[str, Any] = {
            "build": {
                "context": f"./{svc.service_id}",
                "dockerfile": "Dockerfile",
            },
            "container_name": f"{self.project_name}-{svc.service_id}",
            "labels": labels,
            "healthcheck": {
                "test": [
                    "CMD-SHELL",
                    health_cmd,
                ],
                "interval": "15s",
                "timeout": "5s",
                "retries": 3,
                "start_period": "30s",
            },
            "environment": env,
            "mem_limit": "768m",
            "deploy": {
                "resources": {
                    "limits": {"memory": "768m"},
                },
            },
        }

        if is_frontend:
            service_def["networks"] = ["frontend"]
        else:
            service_def["networks"] = ["frontend", "backend"]
            service_def["depends_on"] = {
                "postgres": {"condition": "service_healthy"},
                "redis": {"condition": "service_healthy"},
            }

        return service_def

    def generate_default_dockerfile(
        self,
        service_dir: Path | str,
        port: int = 8080,
        service_info: "ServiceInfo | None" = None,
    ) -> Path:
        """Generate a default Dockerfile when one does not exist.

        Supports multi-stack Dockerfile generation based on the service's
        technology stack.

        Args:
            service_dir: Directory to write the Dockerfile into.
            port: Port the service listens on.
            service_info: Optional ``ServiceInfo`` for tech stack detection.

        Returns:
            Path to the generated Dockerfile.
        """
        service_dir = Path(service_dir)
        dockerfile = service_dir / "Dockerfile"
        if dockerfile.exists():
            return dockerfile

        service_dir.mkdir(parents=True, exist_ok=True)
        content = self._dockerfile_content_for_stack(port, service_info)
        with open(dockerfile, "w", encoding="utf-8") as f:
            f.write(content)
        return dockerfile

    @staticmethod
    def generate_init_sql(
        output_dir: Path | str,
        services: list[ServiceInfo] | None = None,
    ) -> Path:
        """Generate a PostgreSQL init script that creates per-service schemas.

        The generated ``init.sql`` is placed in ``{output_dir}/init-db/``
        so that the PostgreSQL Docker container runs it on first start via
        the ``/docker-entrypoint-initdb.d`` volume mount.

        Each backend service gets a dedicated schema named
        ``{service_id_underscored}_schema`` with ``GRANT ALL`` to the
        default ``app`` user.

        Args:
            output_dir: Root output directory (same level as compose files).
            services: List of services.  Only non-frontend services get schemas.

        Returns:
            Path to the written ``init.sql`` file.
        """
        output_dir = Path(output_dir)
        init_dir = output_dir / "init-db"
        init_dir.mkdir(parents=True, exist_ok=True)
        init_sql_path = init_dir / "init.sql"

        lines: list[str] = [
            "-- Auto-generated per-service PostgreSQL schema init",
            "-- This script runs once on first container start.",
            "",
        ]

        if services:
            for svc in services:
                stack_cat = ComposeGenerator._detect_stack(svc)
                if stack_cat == "frontend":
                    continue
                schema_name = svc.service_id.replace("-", "_") + "_schema"
                lines.append(f"CREATE SCHEMA IF NOT EXISTS {schema_name};")
                lines.append(
                    f"GRANT ALL ON SCHEMA {schema_name} "
                    f"TO ${{POSTGRES_USER:-app}};"
                )
                lines.append("")

        if len(lines) <= 3:
            # No backend services — write a no-op comment
            lines.append("-- No backend services detected; no schemas to create.")
            lines.append("")

        with open(init_sql_path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))

        return init_sql_path

    # ------------------------------------------------------------------
    # 5-file compose merge strategy (TECH-004)
    # ------------------------------------------------------------------

    def generate_compose_files(
        self,
        output_dir: Path | str,
        services: list[ServiceInfo] | None = None,
    ) -> list[Path]:
        """Generate 5 separate compose files with proper merge order.

        Files (in merge order):
            1. docker-compose.infra.yml — postgres, redis, networks, volumes
            2. docker-compose.build1.yml — Build 1 foundation services
            3. docker-compose.traefik.yml — Traefik reverse proxy
            4. docker-compose.generated.yml — generated app services
            5. docker-compose.run4.yml — Run 4 verification overrides

        Args:
            output_dir: Directory to write compose files into.
            services: Optional list of app services for generated file.

        Returns:
            List of Paths to generated compose files, in merge order.
        """
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        if services is None:
            services = []

        files: list[Path] = []

        # 1. docker-compose.infra.yml
        infra = {
            "version": "3.8",
            "services": {
                "postgres": self._postgres_service(),
                "redis": self._redis_service(),
            },
            "networks": {
                "frontend": {"driver": "bridge"},
                "backend": {"driver": "bridge"},
            },
            "volumes": {
                "postgres-data": None,
            },
        }
        infra_path = output_dir / "docker-compose.infra.yml"
        self._write_yaml(infra_path, infra)
        files.append(infra_path)

        # 2. docker-compose.build1.yml
        build1 = {
            "version": "3.8",
            "services": {},
        }
        build1_path = output_dir / "docker-compose.build1.yml"
        self._write_yaml(build1_path, build1)
        files.append(build1_path)

        # 3. docker-compose.traefik.yml
        traefik = {
            "version": "3.8",
            "services": {
                "traefik": self._traefik_service(),
            },
        }
        traefik_path = output_dir / "docker-compose.traefik.yml"
        self._write_yaml(traefik_path, traefik)
        files.append(traefik_path)

        # 4. docker-compose.generated.yml
        generated = {
            "version": "3.8",
            "services": {},
        }
        for svc in services:
            generated["services"][svc.service_id] = self._app_service(svc)
        gen_path = output_dir / "docker-compose.generated.yml"
        self._write_yaml(gen_path, generated)
        files.append(gen_path)

        # 5. docker-compose.run4.yml
        run4 = {
            "version": "3.8",
            "services": {},
        }
        run4_path = output_dir / "docker-compose.run4.yml"
        self._write_yaml(run4_path, run4)
        files.append(run4_path)

        return files

    @staticmethod
    def compose_merge_order() -> list[str]:
        """Return the 5 compose file names in merge order.

        Returns:
            List of file names (not paths) in the correct merge order
            for ``docker compose -f f1 -f f2 ...``.
        """
        return [
            "docker-compose.infra.yml",
            "docker-compose.build1.yml",
            "docker-compose.traefik.yml",
            "docker-compose.generated.yml",
            "docker-compose.run4.yml",
        ]

    @staticmethod
    def _write_yaml(path: Path, data: dict) -> None:
        """Write a YAML dict to a file."""
        with open(path, "w", encoding="utf-8") as f:
            yaml.dump(data, f, default_flow_style=False, sort_keys=False)

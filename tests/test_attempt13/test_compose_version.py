"""Tests for compose file version key removal (Fix 7).

Verifies that generated docker-compose files do not contain the deprecated
'version' key which is no longer needed by modern Docker Compose.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from src.build3_shared.models import ServiceInfo
from src.integrator.compose_generator import ComposeGenerator


class TestComposeNoVersionKey:
    """Test that generated compose files have no version attribute."""

    def test_generate_no_version_key(self, tmp_path: Path):
        """Generated compose file does not contain 'version' key."""
        gen = ComposeGenerator()
        services = [
            ServiceInfo(
                service_id="auth-service",
                domain="auth",
                stack={"language": "python", "framework": "fastapi"},
                port=8001,
            ),
        ]
        output_path = tmp_path / "docker-compose.yml"
        gen.generate(services=services, output_path=output_path)

        with open(output_path, encoding="utf-8") as f:
            compose = yaml.safe_load(f)

        assert "version" not in compose

    def test_generate_yaml_string_no_version(self):
        """YAML string output does not contain 'version' key."""
        gen = ComposeGenerator()
        services = [
            ServiceInfo(
                service_id="auth-service",
                domain="auth",
                stack={"language": "python", "framework": "fastapi"},
                port=8001,
            ),
        ]
        result = gen.generate(services=services)
        assert isinstance(result, str)
        compose = yaml.safe_load(result)
        assert "version" not in compose

    def test_generate_with_all_infra(self, tmp_path: Path):
        """Compose with traefik, postgres, redis still has no version."""
        gen = ComposeGenerator()
        services = [
            ServiceInfo(service_id="svc1", domain="d1", port=8001),
            ServiceInfo(service_id="svc2", domain="d2", port=8002),
        ]
        output_path = tmp_path / "docker-compose.yml"
        gen.generate(
            services=services,
            output_path=output_path,
            include_traefik=True,
            include_postgres=True,
            include_redis=True,
        )

        with open(output_path, encoding="utf-8") as f:
            compose = yaml.safe_load(f)

        assert "version" not in compose
        assert "services" in compose

    def test_generate_compose_files_no_version(self, tmp_path: Path):
        """generate_compose_files method also produces version-free files."""
        gen = ComposeGenerator()
        services = [
            ServiceInfo(service_id="auth", domain="auth", port=8001),
        ]
        gen.generate_compose_files(
            services=services,
            output_dir=tmp_path,
        )

        for yml_file in tmp_path.glob("*.yml"):
            with open(yml_file, encoding="utf-8") as f:
                compose = yaml.safe_load(f)
            if compose:
                assert "version" not in compose, f"version found in {yml_file.name}"

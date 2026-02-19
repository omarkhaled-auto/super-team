"""Tests for ComposeGenerator.

TEST-007: >= 10 test cases covering YAML validity, Traefik labels, healthchecks.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from src.build3_shared.models import ServiceInfo
from src.integrator.compose_generator import ComposeGenerator


@pytest.fixture
def generator() -> ComposeGenerator:
    return ComposeGenerator()


@pytest.fixture
def sample_services() -> list[ServiceInfo]:
    return [
        ServiceInfo(
            service_id="auth-service",
            domain="auth",
            port=8001,
            health_endpoint="/api/health",
        ),
        ServiceInfo(
            service_id="order-service",
            domain="orders",
            port=8002,
            health_endpoint="/health",
        ),
    ]


class TestComposeGenerator:
    """Test Docker Compose YAML generation."""

    def test_generates_valid_yaml(self, generator, sample_services, tmp_path) -> None:
        output = tmp_path / "docker-compose.yml"
        generator.generate(sample_services, output)
        with open(output, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        assert "services" in data

    def test_includes_traefik(self, generator, sample_services, tmp_path) -> None:
        output = tmp_path / "docker-compose.yml"
        generator.generate(sample_services, output)
        with open(output, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        assert "traefik" in data["services"]
        assert "traefik:v3.6" in data["services"]["traefik"]["image"]

    def test_includes_postgres(self, generator, sample_services, tmp_path) -> None:
        output = tmp_path / "docker-compose.yml"
        generator.generate(sample_services, output)
        with open(output, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        assert "postgres" in data["services"]
        assert "postgres:16-alpine" in data["services"]["postgres"]["image"]

    def test_includes_redis(self, generator, sample_services, tmp_path) -> None:
        output = tmp_path / "docker-compose.yml"
        generator.generate(sample_services, output)
        with open(output, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        assert "redis" in data["services"]
        assert "redis:7-alpine" in data["services"]["redis"]["image"]

    def test_per_service_entries(self, generator, sample_services, tmp_path) -> None:
        output = tmp_path / "docker-compose.yml"
        generator.generate(sample_services, output)
        with open(output, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        assert "auth-service" in data["services"]
        assert "order-service" in data["services"]

    def test_traefik_labels_on_services(self, generator, sample_services, tmp_path) -> None:
        output = tmp_path / "docker-compose.yml"
        generator.generate(sample_services, output)
        with open(output, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        labels = data["services"]["auth-service"]["labels"]
        assert labels["traefik.enable"] == "true"

    def test_healthcheck_on_services(self, generator, sample_services, tmp_path) -> None:
        output = tmp_path / "docker-compose.yml"
        generator.generate(sample_services, output)
        with open(output, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        hc = data["services"]["auth-service"]["healthcheck"]
        assert "curl" in hc["test"][-1]
        assert "/api/health" in hc["test"][-1]

    def test_postgres_healthcheck(self, generator, sample_services, tmp_path) -> None:
        output = tmp_path / "docker-compose.yml"
        generator.generate(sample_services, output)
        with open(output, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        hc = data["services"]["postgres"]["healthcheck"]
        assert "pg_isready" in hc["test"][-1]

    def test_exclude_optional_services(self, generator, sample_services, tmp_path) -> None:
        output = tmp_path / "docker-compose.yml"
        generator.generate(
            sample_services, output,
            include_traefik=False,
            include_postgres=False,
            include_redis=False,
        )
        with open(output, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        assert "traefik" not in data["services"]
        assert "postgres" not in data["services"]
        assert "redis" not in data["services"]

    def test_default_dockerfile_generation(self, generator, tmp_path) -> None:
        service_dir = tmp_path / "my-service"
        result = generator.generate_default_dockerfile(service_dir, port=3000)
        assert result.exists()
        content = result.read_text(encoding="utf-8")
        assert "3000" in content
        assert "python:3.12-slim" in content

    def test_default_dockerfile_no_overwrite(self, generator, tmp_path) -> None:
        service_dir = tmp_path / "my-service"
        service_dir.mkdir()
        existing = service_dir / "Dockerfile"
        existing.write_text("FROM node:20", encoding="utf-8")
        result = generator.generate_default_dockerfile(service_dir)
        assert result.read_text(encoding="utf-8") == "FROM node:20"

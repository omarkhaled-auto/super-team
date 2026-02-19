"""Tests for TraefikConfigGenerator.

TEST-008: >= 6 test cases covering labels, PathPrefix backticks, static config.
"""

from __future__ import annotations

import pytest

from src.integrator.traefik_config import TraefikConfigGenerator


@pytest.fixture
def generator() -> TraefikConfigGenerator:
    return TraefikConfigGenerator()


class TestTraefikLabels:
    """Test Traefik Docker label generation."""

    def test_generates_enable_label(self, generator) -> None:
        labels = generator.generate_labels("auth-service")
        assert labels["traefik.enable"] == "true"

    def test_pathprefix_uses_backticks(self, generator) -> None:
        labels = generator.generate_labels("auth-service", path_prefix="/auth")
        rule_key = "traefik.http.routers.auth_service.rule"
        assert rule_key in labels
        assert labels[rule_key] == "PathPrefix(`/auth`)"

    def test_default_path_prefix(self, generator) -> None:
        labels = generator.generate_labels("order-service")
        rule_key = "traefik.http.routers.order_service.rule"
        assert labels[rule_key] == "PathPrefix(`/order-service`)"

    def test_port_label(self, generator) -> None:
        labels = generator.generate_labels("api", port=3000)
        port_key = "traefik.http.services.api.loadbalancer.server.port"
        assert labels[port_key] == "3000"

    def test_entrypoints_label(self, generator) -> None:
        labels = generator.generate_labels("web-service")
        ep_key = "traefik.http.routers.web_service.entrypoints"
        assert labels[ep_key] == "web"


class TestTraefikStaticConfig:
    """Test Traefik static configuration generation."""

    def test_static_config_structure(self, generator) -> None:
        config = generator.generate_static_config()
        assert "api" in config
        assert "entryPoints" in config
        assert "providers" in config

    def test_dashboard_disabled(self, generator) -> None:
        import yaml
        config = yaml.safe_load(generator.generate_static_config())
        assert config["api"]["dashboard"] is False

    def test_docker_provider(self, generator) -> None:
        import yaml
        config = yaml.safe_load(generator.generate_static_config())
        docker = config["providers"]["docker"]
        assert docker["exposedByDefault"] is False
        assert "docker.sock" in docker["endpoint"]

    def test_web_entrypoint(self, generator) -> None:
        import yaml
        config = yaml.safe_load(generator.generate_static_config())
        assert config["entryPoints"]["web"]["address"] == ":80"

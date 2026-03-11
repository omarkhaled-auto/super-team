"""Tests for compose environment variable generation.

Verifies framework-aware env vars:
- Python/FastAPI: DATABASE_URL with postgresql+asyncpg://, REDIS_URL, JWT_SECRET
- NestJS: individual DB_HOST/DB_PORT/DB_USERNAME/DB_PASSWORD/DB_DATABASE, REDIS_HOST/PORT
- Frontend: minimal (NODE_ENV=production only)
- Database names use underscore (auth-service -> auth_service)
"""

from __future__ import annotations

import pytest

from src.build3_shared.models import ServiceInfo
from src.integrator.compose_generator import ComposeGenerator


class TestPythonEnvVars:
    """Python/FastAPI services get asyncpg DATABASE_URL and REDIS_URL."""

    def test_python_env_has_asyncpg_url(self):
        """FastAPI services get postgresql+asyncpg:// in DATABASE_URL."""
        env = ComposeGenerator._generate_env_vars(
            service_id="auth-service",
            stack="python",
            port=8000,
        )
        assert "DATABASE_URL" in env
        assert "postgresql+asyncpg://" in env["DATABASE_URL"]

    def test_python_env_has_jwt_secret(self):
        """Python services get JWT_SECRET env var."""
        env = ComposeGenerator._generate_env_vars(
            service_id="auth-service",
            stack="python",
            port=8000,
        )
        assert "JWT_SECRET" in env

    def test_python_env_has_redis_url(self):
        """Python services get REDIS_URL."""
        env = ComposeGenerator._generate_env_vars(
            service_id="auth-service",
            stack="python",
            port=8000,
        )
        assert "REDIS_URL" in env
        assert "redis://" in env["REDIS_URL"]

    def test_python_env_has_service_port(self):
        """Python services get SERVICE_PORT."""
        env = ComposeGenerator._generate_env_vars(
            service_id="auth-service",
            stack="python",
            port=8000,
        )
        assert env["SERVICE_PORT"] == "8000"

    def test_python_env_has_log_level(self):
        """Python services get LOG_LEVEL."""
        env = ComposeGenerator._generate_env_vars(
            service_id="auth-service",
            stack="python",
            port=8000,
        )
        assert "LOG_LEVEL" in env

    def test_python_env_db_name_uses_underscore(self):
        """Database name in DATABASE_URL uses underscore not dash."""
        env = ComposeGenerator._generate_env_vars(
            service_id="auth-service",
            stack="python",
            port=8000,
        )
        assert "auth_service" in env["DATABASE_URL"]
        assert "auth-service" not in env["DATABASE_URL"]


class TestNestJSEnvVars:
    """NestJS services get individual DB_* variables, not composite DATABASE_URL."""

    def test_nestjs_env_has_individual_db_vars(self):
        """NestJS services get DB_HOST, DB_PORT, DB_USERNAME, DB_PASSWORD, DB_DATABASE."""
        env = ComposeGenerator._generate_env_vars(
            service_id="accounts-service",
            stack="typescript",
            port=8080,
        )
        assert env["DB_HOST"] == "postgres"
        assert env["DB_PORT"] == "5432"
        assert env["DB_USERNAME"] == "app"
        assert env["DB_PASSWORD"] == "app"
        assert "DB_DATABASE" in env

    def test_nestjs_env_has_no_composite_database_url(self):
        """NestJS services should NOT have composite DATABASE_URL."""
        env = ComposeGenerator._generate_env_vars(
            service_id="accounts-service",
            stack="typescript",
            port=8080,
        )
        assert "DATABASE_URL" not in env

    def test_nestjs_env_has_jwt_secret(self):
        """NestJS services get JWT_SECRET."""
        env = ComposeGenerator._generate_env_vars(
            service_id="accounts-service",
            stack="typescript",
            port=8080,
        )
        assert "JWT_SECRET" in env

    def test_nestjs_env_has_redis_host_and_port(self):
        """NestJS services get REDIS_HOST and REDIS_PORT (not REDIS_URL)."""
        env = ComposeGenerator._generate_env_vars(
            service_id="accounts-service",
            stack="typescript",
            port=8080,
        )
        assert env["REDIS_HOST"] == "redis"
        assert env["REDIS_PORT"] == "6379"

    def test_nestjs_env_has_node_env(self):
        """NestJS services get NODE_ENV=production."""
        env = ComposeGenerator._generate_env_vars(
            service_id="accounts-service",
            stack="typescript",
            port=8080,
        )
        assert env["NODE_ENV"] == "production"

    def test_nestjs_env_db_name_uses_underscore(self):
        """Database name uses underscore not dash."""
        env = ComposeGenerator._generate_env_vars(
            service_id="accounts-service",
            stack="typescript",
            port=8080,
        )
        assert env["DB_DATABASE"] == "accounts_service"


class TestFrontendEnvVars:
    """Frontend services get minimal env vars."""

    def test_frontend_env_minimal(self):
        """Frontend services get only NODE_ENV=production."""
        env = ComposeGenerator._generate_env_vars(
            service_id="frontend",
            stack="frontend",
            port=80,
        )
        assert env == {"NODE_ENV": "production"}

    def test_frontend_env_no_database_url(self):
        """Frontend services have no DATABASE_URL."""
        env = ComposeGenerator._generate_env_vars(
            service_id="frontend",
            stack="frontend",
            port=80,
        )
        assert "DATABASE_URL" not in env
        assert "DB_HOST" not in env

    def test_frontend_env_no_jwt_secret(self):
        """Frontend services have no JWT_SECRET (handled client-side)."""
        env = ComposeGenerator._generate_env_vars(
            service_id="frontend",
            stack="frontend",
            port=80,
        )
        assert "JWT_SECRET" not in env

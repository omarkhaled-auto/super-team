"""Exhaustive tests for the 100K LOC Unlock implementation.

Covers ALL 15+ implemented fixes across 3 tiers plus regression guards:

    Tier 1 — Config Unlock (T1-1 to T1-5):
        - Builder timeout 1800 -> 18000
        - Stall timeout 600 -> 3600
        - Depth thorough -> exhaustive
        - Planning phase timeout 2700 -> 5400
        - Docker RAM 384m -> 768m

    Tier 2 — Bug Fixes (T2-2, N2):
        - Health check start_period 30s -> 90s (compose + pipeline templates)
        - Pipeline Dockerfile templates use 90s

    Tier 3 — .NET/C# Support (T3-1 to T3-6):
        - Stack detection (pipeline + compose)
        - Builder instructions (.NET entry in _STACK_INSTRUCTIONS)
        - Dockerfile templates (.NET SDK -> Runtime multi-stage)
        - Health check (.NET uses wget)
        - Env vars (.NET uses ConnectionStrings__)
        - Cross-service standards (C# examples)

    Stall Detection:
        - Planning phase timeout value
        - .NET Dockerfile template exists in pipeline

    Regression Guards:
        - Python/TypeScript/Frontend detection unchanged
        - Existing stack instructions unchanged

Total: ~65 tests.

Run with:
    pytest tests/test_infra_generation/test_100k_unlock.py -v --tb=short
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from src.build3_shared.models import ServiceInfo
from src.integrator.compose_generator import ComposeGenerator
from src.super_orchestrator.config import (
    BuilderConfig,
    SuperOrchestratorConfig,
    load_super_config,
)
from src.super_orchestrator.cross_service_standards import build_cross_service_standards
from src.super_orchestrator.pipeline import (
    _DOTNET_DOCKERFILE_TEMPLATE,
    _FASTAPI_DOCKERFILE_TEMPLATE,
    _GENERIC_DOCKERFILE_TEMPLATE,
    _NESTJS_DOCKERFILE_TEMPLATE,
    _detect_stack_category,
    _ensure_backend_dockerfile,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def generator() -> ComposeGenerator:
    """Create a default ComposeGenerator instance."""
    return ComposeGenerator()


@pytest.fixture
def dotnet_service() -> ServiceInfo:
    """Mock service info for an ASP.NET Core/.NET backend."""
    return ServiceInfo(
        service_id="procurement-service",
        domain="procurement",
        stack={"language": "csharp", "framework": "ASP.NET Core"},
        port=8080,
        health_endpoint="/api/procurement-service/health",
    )


@pytest.fixture
def python_service() -> ServiceInfo:
    """Mock service info for a Python/FastAPI backend."""
    return ServiceInfo(
        service_id="auth-service",
        domain="authentication",
        stack={"language": "python", "framework": "fastapi"},
        port=8000,
        health_endpoint="/api/auth-service/health",
    )


@pytest.fixture
def typescript_service() -> ServiceInfo:
    """Mock service info for a TypeScript/NestJS backend."""
    return ServiceInfo(
        service_id="accounts-service",
        domain="accounts",
        stack={"language": "typescript", "framework": "nestjs"},
        port=8080,
        health_endpoint="/api/accounts-service/health",
    )


# ═══════════════════════════════════════════════════════════════════════════
# TIER 1: CONFIG UNLOCK
# ═══════════════════════════════════════════════════════════════════════════


class TestConfigUnlock:
    """Tier 1: Config defaults unlocked for 100K LOC builds."""

    # -- T1-1: Builder timeout --

    def test_builder_timeout_default_is_18000(self) -> None:
        """Default builder timeout is 5 hours (18000s), not 30 min."""
        cfg = BuilderConfig()
        assert cfg.timeout_per_builder == 18000

    def test_builder_timeout_is_int(self) -> None:
        """Builder timeout is an integer (seconds)."""
        cfg = BuilderConfig()
        assert isinstance(cfg.timeout_per_builder, int)

    # -- T1-2: Stall timeout --

    def test_stall_timeout_default_is_3600(self) -> None:
        """Default stall timeout is 60 minutes (3600s), not 10 min."""
        cfg = BuilderConfig()
        assert cfg.stall_timeout_s == 3600

    def test_stall_timeout_is_int(self) -> None:
        """Stall timeout is an integer (seconds)."""
        cfg = BuilderConfig()
        assert isinstance(cfg.stall_timeout_s, int)

    # -- T1-3: Depth --

    def test_depth_default_is_exhaustive(self) -> None:
        """Default depth is 'exhaustive', not 'thorough'."""
        cfg = BuilderConfig()
        assert cfg.depth == "exhaustive"

    def test_depth_is_string(self) -> None:
        """Depth is a string value."""
        cfg = BuilderConfig()
        assert isinstance(cfg.depth, str)

    # -- T1-4: Planning phase timeout --

    def test_planning_phase_timeout_uses_5400_floor(self) -> None:
        """Pipeline source uses 5400 (90 min) as planning phase timeout floor."""
        import inspect
        from src.super_orchestrator import pipeline
        # Read the actual source to verify the constant
        source = inspect.getsource(pipeline)
        assert "max(stall_timeout_s, 5400)" in source, (
            "Planning phase timeout floor should be max(stall_timeout_s, 5400)"
        )

    def test_planning_phase_timeout_at_least_90_min(self) -> None:
        """With default stall_timeout_s=3600, planning timeout is 5400s (90 min)."""
        cfg = BuilderConfig()
        # The pipeline computes: max(stall_timeout_s, 5400)
        planning_timeout = max(cfg.stall_timeout_s, 5400)
        assert planning_timeout == 5400
        assert planning_timeout >= 5400  # Always at least 90 min

    # -- Config override --

    def test_config_override_from_yaml(self, tmp_path: Path) -> None:
        """YAML config overrides all BuilderConfig defaults."""
        config_data = {
            "builder": {
                "timeout_per_builder": 7200,
                "stall_timeout_s": 1800,
                "depth": "thorough",
                "max_concurrent": 1,
                "poll_interval_s": 60,
            }
        }
        path = tmp_path / "config.yaml"
        with open(path, "w", encoding="utf-8") as f:
            yaml.dump(config_data, f)

        cfg = load_super_config(path)
        assert cfg.builder.timeout_per_builder == 7200
        assert cfg.builder.stall_timeout_s == 1800
        assert cfg.builder.depth == "thorough"
        assert cfg.builder.max_concurrent == 1
        assert cfg.builder.poll_interval_s == 60

    def test_partial_yaml_override_keeps_new_defaults(self, tmp_path: Path) -> None:
        """Partial YAML override preserves new defaults for unspecified fields."""
        config_data = {"builder": {"max_concurrent": 5}}
        path = tmp_path / "config.yaml"
        with open(path, "w", encoding="utf-8") as f:
            yaml.dump(config_data, f)

        cfg = load_super_config(path)
        assert cfg.builder.max_concurrent == 5
        # New defaults should be preserved
        assert cfg.builder.timeout_per_builder == 18000
        assert cfg.builder.stall_timeout_s == 3600
        assert cfg.builder.depth == "exhaustive"

    def test_super_config_has_builder_defaults(self) -> None:
        """SuperOrchestratorConfig propagates BuilderConfig defaults."""
        cfg = SuperOrchestratorConfig()
        assert cfg.builder.timeout_per_builder == 18000
        assert cfg.builder.stall_timeout_s == 3600
        assert cfg.builder.depth == "exhaustive"


# ═══════════════════════════════════════════════════════════════════════════
# TIER 1: T1-5 Docker RAM
# ═══════════════════════════════════════════════════════════════════════════


class TestDockerRAM:
    """T1-5: Docker memory limits increased to 768m."""

    def test_mem_limit_768m(self, generator: ComposeGenerator, python_service: ServiceInfo) -> None:
        """Service mem_limit is 768m."""
        svc_def = generator._app_service(python_service)
        assert svc_def["mem_limit"] == "768m"

    def test_deploy_memory_limit_768m(self, generator: ComposeGenerator, python_service: ServiceInfo) -> None:
        """Deploy resources limits memory is 768m."""
        svc_def = generator._app_service(python_service)
        assert svc_def["deploy"]["resources"]["limits"]["memory"] == "768m"

    def test_mem_limit_consistent(self, generator: ComposeGenerator, python_service: ServiceInfo) -> None:
        """mem_limit and deploy.resources.limits.memory match."""
        svc_def = generator._app_service(python_service)
        assert svc_def["mem_limit"] == svc_def["deploy"]["resources"]["limits"]["memory"]

    def test_dotnet_service_mem_limit_768m(self, generator: ComposeGenerator, dotnet_service: ServiceInfo) -> None:
        """Dotnet service also gets 768m memory limit."""
        svc_def = generator._app_service(dotnet_service)
        assert svc_def["mem_limit"] == "768m"

    def test_typescript_service_mem_limit_768m(self, generator: ComposeGenerator, typescript_service: ServiceInfo) -> None:
        """TypeScript service also gets 768m memory limit."""
        svc_def = generator._app_service(typescript_service)
        assert svc_def["mem_limit"] == "768m"


# ═══════════════════════════════════════════════════════════════════════════
# TIER 2: BUG FIXES — Health Check start_period
# ═══════════════════════════════════════════════════════════════════════════


class TestHealthCheckStartPeriod:
    """T2-2 + N2: Health check start_period updated to 90s everywhere."""

    def test_compose_healthcheck_start_period_90s(self, generator: ComposeGenerator) -> None:
        """Compose generator healthcheck start_period is 90s."""
        hc = generator._generate_healthcheck(
            service_id="auth",
            stack="python",
            internal_port=8000,
            health_endpoint="/health",
        )
        assert hc["start_period"] == "90s"

    def test_pipeline_fastapi_template_start_period_90s(self) -> None:
        """Pipeline FastAPI Dockerfile template uses start-period=90s."""
        assert "start-period=90s" in _FASTAPI_DOCKERFILE_TEMPLATE
        assert "start-period=30s" not in _FASTAPI_DOCKERFILE_TEMPLATE

    def test_pipeline_nestjs_template_start_period_90s(self) -> None:
        """Pipeline NestJS Dockerfile template uses start-period=90s."""
        assert "start-period=90s" in _NESTJS_DOCKERFILE_TEMPLATE
        assert "start-period=30s" not in _NESTJS_DOCKERFILE_TEMPLATE

    def test_pipeline_generic_template_start_period_90s(self) -> None:
        """Pipeline generic Dockerfile template uses start-period=90s."""
        assert "start-period=90s" in _GENERIC_DOCKERFILE_TEMPLATE
        assert "start-period=30s" not in _GENERIC_DOCKERFILE_TEMPLATE

    def test_pipeline_dotnet_template_start_period_90s(self) -> None:
        """Pipeline .NET Dockerfile template uses start-period=90s."""
        assert "start-period=90s" in _DOTNET_DOCKERFILE_TEMPLATE
        assert "start-period=30s" not in _DOTNET_DOCKERFILE_TEMPLATE

    @pytest.mark.parametrize("stack", ["python", "typescript", "frontend", "dotnet"])
    def test_all_stacks_healthcheck_start_period_90s(self, generator: ComposeGenerator, stack: str) -> None:
        """All stacks get start_period=90s in compose healthcheck."""
        port = 80 if stack == "frontend" else 8080
        hc = generator._generate_healthcheck(
            service_id="svc",
            stack=stack,
            internal_port=port,
            health_endpoint="/health",
        )
        assert hc["start_period"] == "90s"


# ═══════════════════════════════════════════════════════════════════════════
# TIER 3: .NET SUPPORT — Stack Detection (Pipeline)
# ═══════════════════════════════════════════════════════════════════════════


class TestDotNetStackDetectionPipeline:
    """T3-1: Pipeline _detect_stack_category handles C#/.NET."""

    def test_detect_csharp_language(self) -> None:
        """Language 'csharp' detected as 'dotnet'."""
        assert _detect_stack_category({"language": "csharp"}) == "dotnet"

    def test_detect_cs_language(self) -> None:
        """Language 'cs' detected as 'dotnet'."""
        assert _detect_stack_category({"language": "cs"}) == "dotnet"

    def test_detect_csharp_uppercase(self) -> None:
        """Language 'C#' detected as 'dotnet' (case-insensitive)."""
        assert _detect_stack_category({"language": "C#"}) == "dotnet"

    def test_detect_aspnet_framework(self) -> None:
        """Framework 'ASP.NET' detected as 'dotnet'."""
        assert _detect_stack_category({"framework": "ASP.NET"}) == "dotnet"

    def test_detect_aspnet_core_framework(self) -> None:
        """Framework 'ASP.NET Core' detected as 'dotnet'."""
        assert _detect_stack_category({"framework": "ASP.NET Core"}) == "dotnet"

    def test_detect_dotnet_framework(self) -> None:
        """Framework '.NET' detected as 'dotnet'."""
        assert _detect_stack_category({"framework": ".NET"}) == "dotnet"

    def test_detect_dotnet_string_framework(self) -> None:
        """Framework 'dotnet' detected as 'dotnet'."""
        assert _detect_stack_category({"framework": "dotnet"}) == "dotnet"

    def test_detect_entity_framework(self) -> None:
        """Framework 'Entity Framework' detected as 'dotnet'."""
        assert _detect_stack_category({"framework": "Entity Framework"}) == "dotnet"

    def test_csharp_not_python(self) -> None:
        """C# does NOT fall through to 'python' default."""
        result = _detect_stack_category({"language": "csharp", "framework": "ASP.NET Core"})
        assert result != "python"
        assert result == "dotnet"

    def test_csharp_with_both_lang_and_framework(self) -> None:
        """C# language + .NET framework both work together."""
        result = _detect_stack_category({"language": "C#", "framework": ".NET"})
        assert result == "dotnet"


# ═══════════════════════════════════════════════════════════════════════════
# TIER 3: .NET SUPPORT — Stack Detection (Compose Generator)
# ═══════════════════════════════════════════════════════════════════════════


class TestDotNetStackDetectionCompose:
    """T3-1b: Compose generator _detect_stack handles C#/.NET."""

    def test_compose_detect_csharp(self) -> None:
        """ComposeGenerator._detect_stack returns 'dotnet' for C#."""
        svc = ServiceInfo(
            service_id="procurement",
            domain="procurement",
            stack={"language": "csharp", "framework": "ASP.NET Core"},
        )
        assert ComposeGenerator._detect_stack(svc) == "dotnet"

    def test_compose_detect_cs(self) -> None:
        """ComposeGenerator._detect_stack returns 'dotnet' for cs language."""
        svc = ServiceInfo(
            service_id="svc",
            domain="d",
            stack={"language": "cs"},
        )
        assert ComposeGenerator._detect_stack(svc) == "dotnet"

    def test_compose_detect_dotnet_framework(self) -> None:
        """ComposeGenerator._detect_stack returns 'dotnet' for .NET framework."""
        svc = ServiceInfo(
            service_id="svc",
            domain="d",
            stack={"framework": "dotnet"},
        )
        assert ComposeGenerator._detect_stack(svc) == "dotnet"

    def test_compose_detect_entity_framework(self) -> None:
        """ComposeGenerator._detect_stack returns 'dotnet' for Entity Framework."""
        svc = ServiceInfo(
            service_id="svc",
            domain="d",
            stack={"framework": "Entity Framework"},
        )
        assert ComposeGenerator._detect_stack(svc) == "dotnet"

    def test_compose_detect_none_is_python(self) -> None:
        """ComposeGenerator._detect_stack returns 'python' for None."""
        assert ComposeGenerator._detect_stack(None) == "python"


# ═══════════════════════════════════════════════════════════════════════════
# TIER 3: .NET SUPPORT — Builder Instructions
# ═══════════════════════════════════════════════════════════════════════════


class TestDotNetBuilderInstructions:
    """T3-2: _STACK_INSTRUCTIONS has a 'dotnet' entry with key content."""

    def test_dotnet_entry_exists(self) -> None:
        """_STACK_INSTRUCTIONS contains a 'dotnet' key."""
        from src.super_orchestrator.pipeline import _STACK_INSTRUCTIONS
        assert "dotnet" in _STACK_INSTRUCTIONS

    def test_dotnet_mentions_appsettings(self) -> None:
        """Dotnet instructions mention appsettings.json."""
        from src.super_orchestrator.pipeline import _STACK_INSTRUCTIONS
        assert "appsettings.json" in _STACK_INSTRUCTIONS["dotnet"]

    def test_dotnet_mentions_ef_core(self) -> None:
        """Dotnet instructions mention Entity Framework / EF Core."""
        from src.super_orchestrator.pipeline import _STACK_INSTRUCTIONS
        instr = _STACK_INSTRUCTIONS["dotnet"]
        assert "EF Core" in instr or "Entity Framework" in instr or "EntityFrameworkCore" in instr

    def test_dotnet_mentions_hs256(self) -> None:
        """Dotnet instructions mention HS256 for JWT."""
        from src.super_orchestrator.pipeline import _STACK_INSTRUCTIONS
        assert "HS256" in _STACK_INSTRUCTIONS["dotnet"]

    def test_dotnet_mentions_port_8080(self) -> None:
        """Dotnet instructions mention port 8080."""
        from src.super_orchestrator.pipeline import _STACK_INSTRUCTIONS
        assert "8080" in _STACK_INSTRUCTIONS["dotnet"]

    def test_dotnet_mentions_mediatr(self) -> None:
        """Dotnet instructions mention MediatR for CQRS."""
        from src.super_orchestrator.pipeline import _STACK_INSTRUCTIONS
        assert "MediatR" in _STACK_INSTRUCTIONS["dotnet"]

    def test_dotnet_mentions_tenant_id(self) -> None:
        """Dotnet instructions mention TenantId for multi-tenancy."""
        from src.super_orchestrator.pipeline import _STACK_INSTRUCTIONS
        assert "TenantId" in _STACK_INSTRUCTIONS["dotnet"]

    def test_dotnet_mentions_connection_string(self) -> None:
        """Dotnet instructions mention ConnectionStrings__ env pattern."""
        from src.super_orchestrator.pipeline import _STACK_INSTRUCTIONS
        assert "ConnectionStrings__" in _STACK_INSTRUCTIONS["dotnet"]


# ═══════════════════════════════════════════════════════════════════════════
# TIER 3: .NET SUPPORT — Dockerfile Templates
# ═══════════════════════════════════════════════════════════════════════════


class TestDotNetDockerfileTemplate:
    """T3-3: .NET Dockerfile templates use SDK -> Runtime multi-stage."""

    # -- Pipeline-level template --

    def test_pipeline_dotnet_template_exists(self) -> None:
        """Pipeline has a _DOTNET_DOCKERFILE_TEMPLATE constant."""
        assert _DOTNET_DOCKERFILE_TEMPLATE is not None
        assert len(_DOTNET_DOCKERFILE_TEMPLATE) > 100

    def test_pipeline_dotnet_template_uses_sdk(self) -> None:
        """Pipeline .NET template uses mcr.microsoft.com/dotnet/sdk:8.0."""
        assert "mcr.microsoft.com/dotnet/sdk:8.0" in _DOTNET_DOCKERFILE_TEMPLATE

    def test_pipeline_dotnet_template_uses_aspnet_runtime(self) -> None:
        """Pipeline .NET template uses mcr.microsoft.com/dotnet/aspnet:8.0."""
        assert "mcr.microsoft.com/dotnet/aspnet:8.0" in _DOTNET_DOCKERFILE_TEMPLATE

    def test_pipeline_dotnet_template_runs_publish(self) -> None:
        """Pipeline .NET template runs 'dotnet publish'."""
        assert "dotnet publish" in _DOTNET_DOCKERFILE_TEMPLATE

    def test_pipeline_dotnet_template_has_healthcheck(self) -> None:
        """Pipeline .NET template includes HEALTHCHECK."""
        assert "HEALTHCHECK" in _DOTNET_DOCKERFILE_TEMPLATE

    def test_pipeline_dotnet_template_uses_wget(self) -> None:
        """Pipeline .NET template health check uses wget."""
        assert "wget" in _DOTNET_DOCKERFILE_TEMPLATE

    def test_pipeline_dotnet_template_uses_127_0_0_1(self) -> None:
        """Pipeline .NET template health check uses 127.0.0.1."""
        assert "127.0.0.1" in _DOTNET_DOCKERFILE_TEMPLATE
        assert "localhost" not in _DOTNET_DOCKERFILE_TEMPLATE

    def test_pipeline_dotnet_template_has_format_placeholder(self) -> None:
        """Pipeline .NET template has {service_id} format placeholder."""
        assert "{service_id}" in _DOTNET_DOCKERFILE_TEMPLATE

    # -- Compose generator template --

    def test_compose_dotnet_template_uses_sdk(self) -> None:
        """Compose generator .NET template uses dotnet/sdk:8.0."""
        content = ComposeGenerator._dockerfile_content_for_stack(
            port=8080,
            service_info=ServiceInfo(
                service_id="svc",
                domain="d",
                stack={"language": "csharp", "framework": "ASP.NET Core"},
                port=8080,
            ),
        )
        assert "mcr.microsoft.com/dotnet/sdk:8.0" in content

    def test_compose_dotnet_template_uses_aspnet_runtime(self) -> None:
        """Compose generator .NET template uses dotnet/aspnet:8.0."""
        content = ComposeGenerator._dockerfile_content_for_stack(
            port=8080,
            service_info=ServiceInfo(
                service_id="svc",
                domain="d",
                stack={"language": "csharp"},
                port=8080,
            ),
        )
        assert "mcr.microsoft.com/dotnet/aspnet:8.0" in content

    def test_compose_dotnet_template_runs_publish(self) -> None:
        """Compose generator .NET template runs 'dotnet publish'."""
        content = ComposeGenerator._dockerfile_content_for_stack(
            port=8080,
            service_info=ServiceInfo(
                service_id="svc",
                domain="d",
                stack={"language": "csharp"},
                port=8080,
            ),
        )
        assert "dotnet publish" in content

    def test_compose_dotnet_template_has_healthcheck(self) -> None:
        """Compose generator .NET template includes HEALTHCHECK."""
        content = ComposeGenerator._dockerfile_content_for_stack(
            port=8080,
            service_info=ServiceInfo(
                service_id="svc",
                domain="d",
                stack={"language": "csharp"},
                port=8080,
            ),
        )
        assert "HEALTHCHECK" in content

    # -- _ensure_backend_dockerfile --

    def test_ensure_backend_dockerfile_generates_dotnet(self, tmp_path: Path) -> None:
        """_ensure_backend_dockerfile generates .NET Dockerfile for dotnet stack."""
        service_dir = tmp_path / "procurement-service"
        service_dir.mkdir()

        _ensure_backend_dockerfile(service_dir, "procurement-service", "dotnet")

        dockerfile = service_dir / "Dockerfile"
        assert dockerfile.exists()
        content = dockerfile.read_text(encoding="utf-8")
        assert "dotnet" in content.lower()
        assert "HEALTHCHECK" in content


# ═══════════════════════════════════════════════════════════════════════════
# TIER 3: .NET SUPPORT — Health Check
# ═══════════════════════════════════════════════════════════════════════════


class TestDotNetHealthCheck:
    """T3-4: Dotnet health check uses wget."""

    def test_dotnet_healthcheck_uses_wget(self, generator: ComposeGenerator) -> None:
        """Dotnet health check command uses wget."""
        hc = generator._generate_healthcheck(
            service_id="procurement-service",
            stack="dotnet",
            internal_port=8080,
            health_endpoint="/api/procurement-service/health",
        )
        cmd = hc["test"][-1]
        assert "wget" in cmd

    def test_dotnet_healthcheck_uses_127_0_0_1(self, generator: ComposeGenerator) -> None:
        """Dotnet health check uses 127.0.0.1 (not localhost)."""
        hc = generator._generate_healthcheck(
            service_id="svc",
            stack="dotnet",
            internal_port=8080,
            health_endpoint="/health",
        )
        cmd = hc["test"][-1]
        assert "127.0.0.1" in cmd
        assert "localhost" not in cmd

    def test_dotnet_healthcheck_includes_port(self, generator: ComposeGenerator) -> None:
        """Dotnet health check targets the correct port."""
        hc = generator._generate_healthcheck(
            service_id="svc",
            stack="dotnet",
            internal_port=8080,
            health_endpoint="/health",
        )
        cmd = hc["test"][-1]
        assert "8080" in cmd

    def test_dotnet_healthcheck_includes_endpoint(self, generator: ComposeGenerator) -> None:
        """Dotnet health check includes the health endpoint path."""
        hc = generator._generate_healthcheck(
            service_id="svc",
            stack="dotnet",
            internal_port=8080,
            health_endpoint="/api/svc/health",
        )
        cmd = hc["test"][-1]
        assert "/api/svc/health" in cmd

    def test_dotnet_healthcheck_no_curl(self, generator: ComposeGenerator) -> None:
        """Dotnet health check does NOT use curl."""
        hc = generator._generate_healthcheck(
            service_id="svc",
            stack="dotnet",
            internal_port=8080,
            health_endpoint="/health",
        )
        cmd = hc["test"][-1]
        assert "curl" not in cmd


# ═══════════════════════════════════════════════════════════════════════════
# TIER 3: .NET SUPPORT — Environment Variables
# ═══════════════════════════════════════════════════════════════════════════


class TestDotNetEnvVars:
    """T3-5: Dotnet env vars use ConnectionStrings__ pattern."""

    def test_dotnet_env_has_connection_string(self) -> None:
        """Dotnet env vars include ConnectionStrings__DefaultConnection."""
        env = ComposeGenerator._generate_env_vars(
            service_id="procurement-service",
            stack="dotnet",
            port=8080,
        )
        assert "ConnectionStrings__DefaultConnection" in env

    def test_dotnet_env_has_aspnetcore_urls(self) -> None:
        """Dotnet env vars include ASPNETCORE_URLS."""
        env = ComposeGenerator._generate_env_vars(
            service_id="procurement-service",
            stack="dotnet",
            port=8080,
        )
        assert "ASPNETCORE_URLS" in env
        assert "http://+:8080" in env["ASPNETCORE_URLS"]

    def test_dotnet_env_has_jwt_secret(self) -> None:
        """Dotnet env vars include JWT_SECRET."""
        env = ComposeGenerator._generate_env_vars(
            service_id="procurement-service",
            stack="dotnet",
            port=8080,
        )
        assert "JWT_SECRET" in env

    def test_dotnet_env_has_aspnetcore_environment(self) -> None:
        """Dotnet env vars include ASPNETCORE_ENVIRONMENT."""
        env = ComposeGenerator._generate_env_vars(
            service_id="svc",
            stack="dotnet",
            port=8080,
        )
        assert "ASPNETCORE_ENVIRONMENT" in env

    def test_dotnet_env_has_redis(self) -> None:
        """Dotnet env vars include Redis connection string."""
        env = ComposeGenerator._generate_env_vars(
            service_id="svc",
            stack="dotnet",
            port=8080,
        )
        assert "Redis__ConnectionString" in env

    def test_dotnet_env_connection_string_has_postgres(self) -> None:
        """Dotnet connection string references postgres host."""
        env = ComposeGenerator._generate_env_vars(
            service_id="svc",
            stack="dotnet",
            port=8080,
        )
        conn = env["ConnectionStrings__DefaultConnection"]
        assert "postgres" in conn.lower() or "Host=postgres" in conn

    def test_dotnet_env_no_database_url(self) -> None:
        """Dotnet env vars do NOT have Python-style DATABASE_URL."""
        env = ComposeGenerator._generate_env_vars(
            service_id="svc",
            stack="dotnet",
            port=8080,
        )
        assert "DATABASE_URL" not in env

    def test_dotnet_env_no_node_env(self) -> None:
        """Dotnet env vars do NOT have NODE_ENV."""
        env = ComposeGenerator._generate_env_vars(
            service_id="svc",
            stack="dotnet",
            port=8080,
        )
        assert "NODE_ENV" not in env


# ═══════════════════════════════════════════════════════════════════════════
# TIER 3: .NET SUPPORT — Cross-Service Standards
# ═══════════════════════════════════════════════════════════════════════════


class TestDotNetCrossServiceStandards:
    """T3-6: Cross-service standards include C# code examples."""

    def test_standards_have_csharp_keyword(self) -> None:
        """Cross-service standards mention 'csharp' or 'C#'."""
        standards = build_cross_service_standards("test-service", is_frontend=False)
        text_lower = standards.lower()
        assert "csharp" in text_lower or "c#" in text_lower

    def test_standards_have_csharp_jwt_example(self) -> None:
        """Cross-service standards include C# JWT validation example."""
        standards = build_cross_service_standards("test-service", is_frontend=False)
        # The JWT_STANDARD has "C# / ASP.NET Core JWT validation:"
        assert "ASP.NET" in standards or "JwtBearer" in standards

    def test_standards_have_csharp_event_example(self) -> None:
        """Cross-service standards include C# event publishing example."""
        standards = build_cross_service_standards("test-service", is_frontend=False)
        assert "PublishAsync" in standards or "C# Event Publishing" in standards

    def test_standards_have_csharp_state_machine_example(self) -> None:
        """Cross-service standards include C# state machine pattern."""
        standards = build_cross_service_standards("test-service", is_frontend=False)
        # The STATE_MACHINE_STANDARD has "### C# Pattern:"
        assert "C# Pattern" in standards or "OrderStatus" in standards


# ═══════════════════════════════════════════════════════════════════════════
# REGRESSION GUARDS
# ═══════════════════════════════════════════════════════════════════════════


class TestRegressionGuards:
    """Ensure existing Python/TypeScript/Frontend detection still works."""

    # -- Pipeline _detect_stack_category --

    def test_python_detection_unchanged(self) -> None:
        """Python language still detected correctly."""
        assert _detect_stack_category({"language": "python"}) == "python"

    def test_python_fastapi_detection_unchanged(self) -> None:
        """FastAPI framework still detected as python."""
        # FastAPI is not in the framework check but language "python" triggers it
        assert _detect_stack_category({"language": "python", "framework": "fastapi"}) == "python"

    def test_typescript_detection_unchanged(self) -> None:
        """TypeScript language still detected correctly."""
        assert _detect_stack_category({"language": "typescript"}) == "typescript"

    def test_nestjs_detection_unchanged(self) -> None:
        """NestJS framework still detected as typescript."""
        assert _detect_stack_category({"framework": "nestjs"}) == "typescript"

    def test_express_detection_unchanged(self) -> None:
        """Express framework still detected as typescript."""
        assert _detect_stack_category({"framework": "express"}) == "typescript"

    def test_angular_detection_unchanged(self) -> None:
        """Angular framework still detected as frontend."""
        assert _detect_stack_category({"framework": "angular"}) == "frontend"

    def test_react_detection_unchanged(self) -> None:
        """React framework still detected as frontend."""
        assert _detect_stack_category({"framework": "react"}) == "frontend"

    def test_vue_detection_unchanged(self) -> None:
        """Vue framework still detected as frontend."""
        assert _detect_stack_category({"framework": "vue"}) == "frontend"

    def test_none_defaults_to_python(self) -> None:
        """None input defaults to 'python'."""
        assert _detect_stack_category(None) == "python"

    def test_empty_dict_defaults_to_python(self) -> None:
        """Empty dict defaults to 'python'."""
        assert _detect_stack_category({}) == "python"

    def test_empty_string_defaults_to_python(self) -> None:
        """Empty string defaults to 'python'."""
        assert _detect_stack_category("") == "python"

    def test_non_dict_defaults_to_python(self) -> None:
        """Non-dict input defaults to 'python'."""
        assert _detect_stack_category("python") == "python"

    # -- Compose _detect_stack --

    def test_compose_python_unchanged(self) -> None:
        """Compose generator Python detection unchanged."""
        svc = ServiceInfo(
            service_id="auth",
            domain="auth",
            stack={"language": "python", "framework": "fastapi"},
        )
        assert ComposeGenerator._detect_stack(svc) == "python"

    def test_compose_typescript_unchanged(self) -> None:
        """Compose generator TypeScript detection unchanged."""
        svc = ServiceInfo(
            service_id="svc",
            domain="d",
            stack={"language": "typescript", "framework": "nestjs"},
        )
        assert ComposeGenerator._detect_stack(svc) == "typescript"

    def test_compose_frontend_unchanged(self) -> None:
        """Compose generator frontend detection unchanged."""
        svc = ServiceInfo(
            service_id="frontend",
            domain="ui",
            stack={"language": "typescript", "framework": "angular"},
        )
        assert ComposeGenerator._detect_stack(svc) == "frontend"

    # -- _STACK_INSTRUCTIONS regression --

    def test_stack_instructions_python_still_exists(self) -> None:
        """_STACK_INSTRUCTIONS still has 'python' entry."""
        from src.super_orchestrator.pipeline import _STACK_INSTRUCTIONS
        assert "python" in _STACK_INSTRUCTIONS

    def test_stack_instructions_typescript_still_exists(self) -> None:
        """_STACK_INSTRUCTIONS still has 'typescript' entry."""
        from src.super_orchestrator.pipeline import _STACK_INSTRUCTIONS
        assert "typescript" in _STACK_INSTRUCTIONS

    def test_stack_instructions_frontend_still_exists(self) -> None:
        """_STACK_INSTRUCTIONS still has 'frontend' entry."""
        from src.super_orchestrator.pipeline import _STACK_INSTRUCTIONS
        assert "frontend" in _STACK_INSTRUCTIONS

    def test_stack_instructions_has_four_entries(self) -> None:
        """_STACK_INSTRUCTIONS now has exactly 4 entries (python, typescript, frontend, dotnet)."""
        from src.super_orchestrator.pipeline import _STACK_INSTRUCTIONS
        assert len(_STACK_INSTRUCTIONS) == 4
        assert set(_STACK_INSTRUCTIONS.keys()) == {"python", "typescript", "frontend", "dotnet"}


# ═══════════════════════════════════════════════════════════════════════════
# STALL DETECTION — Child CPU Check
# ═══════════════════════════════════════════════════════════════════════════


class TestStallDetectionChildCPU:
    """Stall detection includes child process CPU checking via psutil."""

    def test_child_cpu_check_exists_in_stall_detection(self) -> None:
        """Stall detection includes child process CPU checking."""
        import inspect
        from src.super_orchestrator import pipeline
        source = inspect.getsource(pipeline)
        assert "children(recursive=True)" in source, (
            "Stall detection should check child process CPU via psutil"
        )
        assert "_child_cpu" in source or "child_cpu" in source, (
            "Stall detection should sum child CPU usage"
        )

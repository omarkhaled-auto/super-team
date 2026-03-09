"""Post-build validator that checks cross-service consistency.

Runs after all builders complete to detect JWT mismatches, event channel
inconsistencies, missing tests, and missing migrations BEFORE integration.
"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def validate_all_services(output_dir: Path, services: list[str]) -> dict[str, list[str]]:
    """Run all cross-service validation checks.

    Returns a dict mapping check name to list of issues found.
    """
    issues: dict[str, list[str]] = {}

    jwt_issues = check_jwt_consistency(output_dir, services)
    if jwt_issues:
        issues["jwt_consistency"] = jwt_issues

    event_issues = check_event_channel_consistency(output_dir, services)
    if event_issues:
        issues["event_channels"] = event_issues

    test_issues = check_test_existence(output_dir, services)
    if test_issues:
        issues["missing_tests"] = test_issues

    migration_issues = check_migration_existence(output_dir, services)
    if migration_issues:
        issues["missing_migrations"] = migration_issues

    frontend_issues = check_frontend_no_backend(output_dir, services)
    if frontend_issues:
        issues["frontend_backend_leak"] = frontend_issues

    dockerfile_issues = check_dockerfile_health(output_dir, services)
    if dockerfile_issues:
        issues["dockerfile_health"] = dockerfile_issues

    test_quality = check_test_quality(output_dir, services)
    if test_quality:
        issues["test_quality"] = test_quality

    handler_issues = check_handler_completeness(output_dir, services)
    if handler_issues:
        issues["handler_completeness"] = handler_issues

    event_quality = check_event_handler_quality(output_dir, services)
    if event_quality:
        issues["event_handler_quality"] = event_quality

    api_issues = check_api_completeness(output_dir, services)
    if api_issues:
        issues["api_completeness"] = api_issues

    security_issues = check_security_basics(output_dir, services)
    if security_issues:
        issues["security_basics"] = security_issues

    error_issues = check_error_response_consistency(output_dir, services)
    if error_issues:
        issues["error_response_consistency"] = error_issues

    db_issues = check_database_quality(output_dir, services)
    if db_issues:
        issues["database_quality"] = db_issues

    env_issues = check_env_var_consistency(output_dir, services)
    if env_issues:
        issues["env_var_consistency"] = env_issues

    return issues


def check_jwt_consistency(output_dir: Path, services: list[str]) -> list[str]:
    """Check that all services use consistent JWT configuration."""
    issues = []
    for svc in services:
        svc_dir = output_dir / svc
        if not svc_dir.exists():
            continue

        # Search for JWT algorithm references
        for ext in ("*.py", "*.ts"):
            for f in svc_dir.rglob(ext):
                if "__pycache__" in str(f) or "node_modules" in str(f) or "dist" in str(f):
                    continue
                try:
                    content = f.read_text(encoding="utf-8", errors="ignore")
                except Exception:
                    continue

                # Check for RS256 usage (should be HS256)
                if re.search(r"RS256|RS384|RS512", content):
                    issues.append(f"{svc}: {f.relative_to(output_dir)} uses asymmetric JWT algorithm (should be HS256)")

                # Check for wrong env var names
                if re.search(r"JWT_SECRET_KEY|JWT_PRIVATE_KEY|JWT_PUBLIC_KEY", content):
                    if "JWT_SECRET" not in content or "JWT_SECRET_KEY" in content:
                        issues.append(f"{svc}: {f.relative_to(output_dir)} uses non-standard JWT env var (should be JWT_SECRET)")

                # Check for wrong payload field names
                if re.search(r'payload\[.user_id.\]|payload\.user_id\b|payload\.userId\b', content):
                    if "payload" in content and "sub" not in content:
                        issues.append(f"{svc}: {f.relative_to(output_dir)} reads user_id/userId instead of sub from JWT")

                if re.search(r'payload\[.tenantId.\]|payload\.tenantId\b', content):
                    issues.append(f"{svc}: {f.relative_to(output_dir)} reads tenantId (camelCase) instead of tenant_id")

    return issues


def check_event_channel_consistency(output_dir: Path, services: list[str]) -> list[str]:
    """Check that event publishers and subscribers use matching channel names."""
    publishers: dict[str, list[str]] = {}  # channel -> [service]
    subscribers: dict[str, list[str]] = {}  # channel -> [service]

    for svc in services:
        svc_dir = output_dir / svc
        if not svc_dir.exists():
            continue

        for ext in ("*.py", "*.ts"):
            for f in svc_dir.rglob(ext):
                if any(skip in str(f) for skip in ("__pycache__", "node_modules", "dist", ".spec.", "test")):
                    continue
                try:
                    content = f.read_text(encoding="utf-8", errors="ignore")
                except Exception:
                    continue

                # Find publish calls
                for match in re.finditer(r'\.publish\(\s*["\']([^"\']+)["\']', content):
                    channel = match.group(1)
                    publishers.setdefault(channel, []).append(svc)

                # Find subscribe calls
                for match in re.finditer(r'\.subscribe\(\s*["\']([^"\']+)["\']', content):
                    channel = match.group(1)
                    subscribers.setdefault(channel, []).append(svc)

    issues = []

    # Check for subscriptions to channels nobody publishes to
    for channel, svc_list in subscribers.items():
        if channel not in publishers:
            issues.append(f"Channel '{channel}' subscribed by {svc_list} but no service publishes to it")

    # Check for umbrella channels (single channel with multiple event types)
    for channel, svc_list in publishers.items():
        if channel.endswith(".events"):
            issues.append(f"Service {svc_list} publishes to umbrella channel '{channel}' — use per-event-type channels instead")

    return issues


def check_test_existence(output_dir: Path, services: list[str]) -> list[str]:
    """Check that every service has test files."""
    issues = []
    for svc in services:
        svc_dir = output_dir / svc
        if not svc_dir.exists():
            continue

        has_tests = False

        # Python tests
        for f in svc_dir.rglob("test_*.py"):
            if "__pycache__" not in str(f):
                has_tests = True
                break

        # TypeScript tests
        if not has_tests:
            for f in svc_dir.rglob("*.spec.ts"):
                if "node_modules" not in str(f) and "dist" not in str(f):
                    has_tests = True
                    break

        if not has_tests:
            issues.append(f"{svc}: No test files found (expected test_*.py or *.spec.ts)")

    return issues


def check_migration_existence(output_dir: Path, services: list[str]) -> list[str]:
    """Check that backend services have migration files."""
    issues = []
    for svc in services:
        svc_dir = output_dir / svc
        if not svc_dir.exists():
            continue

        # Skip frontend services
        if any((svc_dir / f).exists() for f in ("angular.json", "next.config.js", "vite.config.ts")):
            continue

        has_migrations = False

        # Alembic migrations
        for f in svc_dir.rglob("alembic/versions/*.py"):
            if "__pycache__" not in str(f):
                has_migrations = True
                break

        # TypeORM migrations
        if not has_migrations:
            for f in svc_dir.rglob("migrations/*.ts"):
                if "node_modules" not in str(f) and "dist" not in str(f):
                    has_migrations = True
                    break

        if not has_migrations:
            issues.append(f"{svc}: No migration files found (expected alembic/versions/*.py or migrations/*.ts)")

    return issues


def check_frontend_no_backend(output_dir: Path, services: list[str]) -> list[str]:
    """Check that frontend services don't contain backend code."""
    issues = []
    for svc in services:
        svc_dir = output_dir / svc
        if not svc_dir.exists():
            continue

        # Only check services that are frontends
        if not any((svc_dir / f).exists() for f in ("angular.json", "next.config.js", "vite.config.ts")):
            continue

        # Check for Python files (shouldn't be in frontend)
        py_files = list(svc_dir.rglob("*.py"))
        py_files = [f for f in py_files if "__pycache__" not in str(f)]
        if py_files:
            issues.append(f"{svc}: Frontend contains {len(py_files)} Python files (backend code leak)")

        # Check for services/ directory with backend code
        services_dir = svc_dir / "services"
        if services_dir.exists() and services_dir.is_dir():
            issues.append(f"{svc}: Frontend contains 'services/' directory (likely backend duplication)")

    return issues


def check_dockerfile_health(output_dir: Path, services: list[str]) -> list[str]:
    """Check Dockerfiles for common issues."""
    issues = []
    for svc in services:
        dockerfile = output_dir / svc / "Dockerfile"
        if not dockerfile.exists():
            issues.append(f"{svc}: Missing Dockerfile")
            continue

        try:
            content = dockerfile.read_text(encoding="utf-8")
        except Exception:
            continue

        # Check for curl usage on Alpine (curl not installed)
        if "alpine" in content.lower() and "curl" in content:
            issues.append(f"{svc}: Dockerfile uses curl on Alpine image (curl not installed — use wget)")

        # Check for port mismatch
        if "EXPOSE 3000" in content:
            issues.append(f"{svc}: Dockerfile exposes port 3000 (should be 8080)")

    return issues


def check_test_quality(output_dir: Path, services: list[str]) -> list[str]:
    """Check test files for quality — not just existence but meaningful assertions."""
    issues = []
    for svc in services:
        svc_dir = output_dir / svc
        if not svc_dir.exists():
            continue

        for pattern in ("test_*.py", "*.spec.ts"):
            for f in svc_dir.rglob(pattern):
                if any(skip in str(f) for skip in ("node_modules", "__pycache__", "dist")):
                    continue
                try:
                    content = f.read_text(encoding="utf-8", errors="ignore")
                except Exception:
                    continue

                rel = f.relative_to(output_dir)

                # Count assertions
                if f.suffix == ".py":
                    assertion_count = content.count("assert ")
                    test_count = content.count("def test_")
                    trivial = content.count("is not None") + content.count("is None")
                else:
                    assertion_count = content.count("expect(")
                    test_count = content.count("it(") + content.count("test(")
                    trivial = content.count("toBeTruthy") + content.count("toBeDefined") + content.count("toBeNull")

                if test_count < 3:
                    issues.append(f"{svc}: {rel} has only {test_count} test cases (minimum 3)")
                if assertion_count < 3:
                    issues.append(f"{svc}: {rel} has only {assertion_count} assertions (minimum 3)")
                if trivial > 0 and assertion_count > 0 and trivial / assertion_count > 0.5:
                    issues.append(f"{svc}: {rel} has {trivial}/{assertion_count} trivial assertions (>50%)")
    return issues


def check_handler_completeness(output_dir: Path, services: list[str]) -> list[str]:
    """Verify route handlers have validation, error handling, and tenant filtering."""
    issues = []
    for svc in services:
        svc_dir = output_dir / svc
        if not svc_dir.exists():
            continue
        # Skip frontend
        if any((svc_dir / f).exists() for f in ("angular.json", "next.config.js", "vite.config.ts")):
            continue

        route_files = []
        for pattern in ("*/routes/*.py", "*/routers/*.py", "**/controller*.ts", "**/controllers/*.ts"):
            route_files.extend(f for f in svc_dir.rglob(pattern.split("/")[-1])
                             if not any(skip in str(f) for skip in ("node_modules", "__pycache__", "dist", "spec", "test")))

        for f in route_files:
            try:
                content = f.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                continue
            rel = f.relative_to(output_dir)

            has_validation = any(v in content for v in ("Pydantic", "BaseModel", "class-validator", "ValidationPipe", "ParseUUIDPipe", "Body(", "Query("))
            has_error_handling = any(e in content for e in ("HTTPException", "HttpException", "NotFoundException", "BadRequestException", "raise ", "throw new"))
            has_tenant = "tenant_id" in content or "tenantId" in content

            if not has_validation:
                issues.append(f"{svc}: {rel} has no input validation (missing Pydantic/class-validator)")
            if not has_error_handling:
                issues.append(f"{svc}: {rel} has no error handling (missing HTTPException/throw)")
            if not has_tenant:
                issues.append(f"{svc}: {rel} has no tenant_id filtering (multi-tenant isolation missing)")
    return issues


def check_event_handler_quality(output_dir: Path, services: list[str]) -> list[str]:
    """Verify event handlers do real work, not just log."""
    issues = []
    for svc in services:
        svc_dir = output_dir / svc
        if not svc_dir.exists():
            continue

        # Find subscriber/handler files
        handler_files = []
        for pattern in ("**/subscriber*.py", "**/consumer*.py", "**/event*handler*.ts", "**/event*subscriber*.ts"):
            handler_files.extend(f for f in svc_dir.rglob(pattern.split("/")[-1])
                               if not any(skip in str(f) for skip in ("node_modules", "__pycache__", "dist", "spec", "test")))

        for f in handler_files:
            try:
                content = f.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                continue
            rel = f.relative_to(output_dir)

            # Check for DB operations (sign of real work)
            has_db_ops = any(op in content for op in (
                ".save(", ".create(", ".update(", ".delete(", ".insert(",
                ".add(", ".commit(", ".execute(", "INSERT", "UPDATE",
                "queryRunner", "getRepository", "manager.",
            ))
            has_only_logging = (
                ("logger.info" in content or "console.log" in content or "logging.info" in content)
                and not has_db_ops
            )

            if has_only_logging:
                issues.append(f"{svc}: {rel} appears to have log-only event handlers (no DB operations found)")
    return issues


def check_api_completeness(output_dir: Path, services: list[str]) -> list[str]:
    """Verify CRUD endpoints exist for entities."""
    issues = []
    for svc in services:
        svc_dir = output_dir / svc
        if not svc_dir.exists():
            continue
        if any((svc_dir / f).exists() for f in ("angular.json", "next.config.js", "vite.config.ts")):
            continue

        # Count endpoints
        endpoint_count = 0
        has_pagination = False
        for ext in ("*.py", "*.ts"):
            for f in svc_dir.rglob(ext):
                if any(skip in str(f) for skip in ("node_modules", "__pycache__", "dist", "spec", "test")):
                    continue
                try:
                    content = f.read_text(encoding="utf-8", errors="ignore")
                except Exception:
                    continue
                # Count route decorators
                endpoint_count += len(re.findall(r"@(Get|Post|Put|Patch|Delete|app\.(get|post|put|patch|delete)|router\.(get|post|put|patch|delete))", content))

                if not has_pagination and any(p in content for p in ("limit", "offset", "page", "page_size", "pageSize", "skip", "take")):
                    has_pagination = True

        if endpoint_count < 5:
            issues.append(f"{svc}: Only {endpoint_count} API endpoints found (expected at least 5 for any service)")

        if not has_pagination:
            issues.append(f"{svc}: No pagination support found in any endpoint")
    return issues


def check_security_basics(output_dir: Path, services: list[str]) -> list[str]:
    """Check for rate limiting, .dockerignore, and CORS from env."""
    issues = []
    for svc in services:
        svc_dir = output_dir / svc
        if not svc_dir.exists():
            continue
        if any((svc_dir / f).exists() for f in ("angular.json", "next.config.js", "vite.config.ts")):
            continue

        all_content = ""
        for ext in ("*.py", "*.ts"):
            for f in svc_dir.rglob(ext):
                if any(skip in str(f) for skip in ("node_modules", "__pycache__", "dist", "spec", "test")):
                    continue
                try:
                    all_content += f.read_text(encoding="utf-8", errors="ignore") + "\n"
                except Exception:
                    continue

        # Check rate limiting
        has_rate_limit = any(rl in all_content for rl in ("Throttler", "ThrottlerModule", "slowapi", "Limiter", "rate_limit", "RateLimit"))
        if not has_rate_limit:
            issues.append(f"{svc}: No rate limiting found (expected Throttler/slowapi)")

        # Check .dockerignore
        if not (svc_dir / ".dockerignore").exists():
            issues.append(f"{svc}: Missing .dockerignore file")

        # Check CORS references env var
        has_cors_env = any(c in all_content for c in ("CORS_ORIGINS", "cors_origins", "allowedOrigins"))
        if not has_cors_env:
            issues.append(f"{svc}: CORS not configured from environment variable")
    return issues


def check_error_response_consistency(output_dir: Path, services: list[str]) -> list[str]:
    """Check for global exception handler for consistent error responses."""
    issues = []
    for svc in services:
        svc_dir = output_dir / svc
        if not svc_dir.exists():
            continue
        if any((svc_dir / f).exists() for f in ("angular.json", "next.config.js", "vite.config.ts")):
            continue

        # Check for custom exception handler (sign of consistent error responses)
        has_error_handler = False
        for ext in ("*.py", "*.ts"):
            for f in svc_dir.rglob(ext):
                if any(skip in str(f) for skip in ("node_modules", "__pycache__", "dist", "spec", "test")):
                    continue
                try:
                    content = f.read_text(encoding="utf-8", errors="ignore")
                except Exception:
                    continue
                if any(eh in content for eh in ("exception_handler", "ExceptionFilter", "AllExceptionsFilter", "http_exception_handler", "GlobalExceptionFilter")):
                    has_error_handler = True
                    break
            if has_error_handler:
                break

        if not has_error_handler:
            issues.append(f"{svc}: No global exception handler found (needed for consistent error responses)")
    return issues


def check_database_quality(output_dir: Path, services: list[str]) -> list[str]:
    """Check models have tenant_id indexes."""
    issues = []
    for svc in services:
        svc_dir = output_dir / svc
        if not svc_dir.exists():
            continue
        if any((svc_dir / f).exists() for f in ("angular.json", "next.config.js", "vite.config.ts")):
            continue

        has_models = False
        has_tenant_index = False

        for ext in ("*.py", "*.ts"):
            for f in svc_dir.rglob(ext):
                if any(skip in str(f) for skip in ("node_modules", "__pycache__", "dist", "spec", "test", "migration")):
                    continue
                try:
                    content = f.read_text(encoding="utf-8", errors="ignore")
                except Exception:
                    continue

                # Check for model definitions
                if any(m in content for m in ("class.*Base)", "@Entity", "mapped_column", "@Column")):
                    has_models = True

                # Check for tenant_id index
                if any(idx in content for idx in ("Index.*tenant_id", "@Index.*tenant", "index=True", "tenant_id")):
                    has_tenant_index = True

        if has_models and not has_tenant_index:
            issues.append(f"{svc}: Models found but no tenant_id index detected")
    return issues


def check_env_var_consistency(output_dir: Path, services: list[str]) -> list[str]:
    """Check for non-standard environment variable names."""
    issues = []
    non_standard_vars = {
        "POSTGRES_URL": "DATABASE_URL",
        "MONGO_URI": "DATABASE_URL",
        "DB_URL": "DATABASE_URL",
        "JWT_KEY": "JWT_SECRET",
        "JWT_SECRET_KEY": "JWT_SECRET",
        "JWT_PRIVATE_KEY": "JWT_SECRET",
        "REDIS_HOST": "REDIS_URL (for Python services)",
    }

    for svc in services:
        svc_dir = output_dir / svc
        if not svc_dir.exists():
            continue

        for ext in ("*.py", "*.ts"):
            for f in svc_dir.rglob(ext):
                if any(skip in str(f) for skip in ("node_modules", "__pycache__", "dist", "spec", "test")):
                    continue
                try:
                    content = f.read_text(encoding="utf-8", errors="ignore")
                except Exception:
                    continue

                for bad_var, good_var in non_standard_vars.items():
                    if bad_var in content and f.suffix == ".py":
                        # For Python, REDIS_HOST is non-standard
                        if bad_var == "REDIS_HOST" and f.suffix != ".py":
                            continue
                        rel = f.relative_to(output_dir)
                        issues.append(f"{svc}: {rel} uses {bad_var} (should use {good_var})")
    return issues

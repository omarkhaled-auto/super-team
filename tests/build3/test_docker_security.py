"""Tests for DockerSecurityScanner (TEST-025).

Covers all 8 Docker scan codes (DOCKER-001 through DOCKER-008) with 14+ test
cases exercising both positive detection and negative (clean) scenarios, plus
edge cases such as non-Docker files and empty directories.

Run with:
    pytest tests/build3/test_docker_security.py -v
"""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from src.quality_gate.docker_security import DockerSecurityScanner


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def scanner() -> DockerSecurityScanner:
    return DockerSecurityScanner()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_file(directory: Path, name: str, content: str) -> Path:
    """Write a file into *directory* and return its path."""
    file_path = directory / name
    file_path.write_text(textwrap.dedent(content), encoding="utf-8")
    return file_path


def _codes(violations: list) -> list[str]:
    """Extract sorted violation codes from a list of ScanViolation objects."""
    return sorted(v.code for v in violations)


def _codes_unsorted(violations: list) -> list[str]:
    """Extract violation codes preserving order."""
    return [v.code for v in violations]


# ---------------------------------------------------------------------------
# DOCKER-001: Running as root (no USER instruction)
# ---------------------------------------------------------------------------


class TestDocker001RootUser:
    """DOCKER-001 checks that Dockerfiles include a non-root USER."""

    async def test_dockerfile_without_user_instruction_flagged(
        self, scanner: DockerSecurityScanner, tmp_path: Path
    ) -> None:
        """A Dockerfile with no USER instruction should trigger DOCKER-001."""
        _write_file(
            tmp_path,
            "Dockerfile",
            """\
            FROM python:3.12-slim
            WORKDIR /app
            COPY . .
            RUN pip install -r requirements.txt
            CMD ["python", "main.py"]
            """,
        )

        violations = await scanner.scan(tmp_path)
        docker001 = [v for v in violations if v.code == "DOCKER-001"]

        assert len(docker001) >= 1
        assert docker001[0].category == "docker"
        assert docker001[0].severity == "error"
        assert "root" in docker001[0].message.lower() or "USER" in docker001[0].message

    async def test_dockerfile_with_nonroot_user_not_flagged(
        self, scanner: DockerSecurityScanner, tmp_path: Path
    ) -> None:
        """A Dockerfile that sets USER to a non-root user should NOT trigger DOCKER-001."""
        _write_file(
            tmp_path,
            "Dockerfile",
            """\
            FROM python:3.12-slim
            WORKDIR /app
            COPY . .
            RUN pip install -r requirements.txt
            RUN adduser --disabled-password appuser
            USER appuser
            HEALTHCHECK --interval=30s CMD curl -f http://localhost:8080/ || exit 1
            CMD ["python", "main.py"]
            """,
        )

        violations = await scanner.scan(tmp_path)
        docker001 = [v for v in violations if v.code == "DOCKER-001"]

        assert len(docker001) == 0

    async def test_dockerfile_with_explicit_user_root_flagged(
        self, scanner: DockerSecurityScanner, tmp_path: Path
    ) -> None:
        """A Dockerfile whose last USER instruction is 'USER root' should trigger DOCKER-001."""
        _write_file(
            tmp_path,
            "Dockerfile",
            """\
            FROM python:3.12-slim
            WORKDIR /app
            USER appuser
            RUN pip install -r requirements.txt
            USER root
            CMD ["python", "main.py"]
            """,
        )

        violations = await scanner.scan(tmp_path)
        docker001 = [v for v in violations if v.code == "DOCKER-001"]

        assert len(docker001) >= 1
        assert docker001[0].severity == "error"


# ---------------------------------------------------------------------------
# DOCKER-002: No HEALTHCHECK instruction
# ---------------------------------------------------------------------------


class TestDocker002HealthCheck:
    """DOCKER-002 checks that Dockerfiles include a HEALTHCHECK."""

    async def test_dockerfile_without_healthcheck_flagged(
        self, scanner: DockerSecurityScanner, tmp_path: Path
    ) -> None:
        """A Dockerfile missing HEALTHCHECK should trigger DOCKER-002."""
        _write_file(
            tmp_path,
            "Dockerfile",
            """\
            FROM python:3.12-slim
            USER appuser
            WORKDIR /app
            COPY . .
            CMD ["python", "main.py"]
            """,
        )

        violations = await scanner.scan(tmp_path)
        docker002 = [v for v in violations if v.code == "DOCKER-002"]

        assert len(docker002) == 1
        assert docker002[0].category == "docker"
        assert docker002[0].severity == "warning"
        assert "HEALTHCHECK" in docker002[0].message

    async def test_dockerfile_with_healthcheck_not_flagged(
        self, scanner: DockerSecurityScanner, tmp_path: Path
    ) -> None:
        """A Dockerfile that includes HEALTHCHECK should NOT trigger DOCKER-002."""
        _write_file(
            tmp_path,
            "Dockerfile",
            """\
            FROM python:3.12-slim
            USER appuser
            WORKDIR /app
            COPY . .
            HEALTHCHECK --interval=30s --timeout=3s CMD curl -f http://localhost:8080/ || exit 1
            CMD ["python", "main.py"]
            """,
        )

        violations = await scanner.scan(tmp_path)
        docker002 = [v for v in violations if v.code == "DOCKER-002"]

        assert len(docker002) == 0


# ---------------------------------------------------------------------------
# DOCKER-003: Using :latest tag or no tag in FROM
# ---------------------------------------------------------------------------


class TestDocker003LatestTag:
    """DOCKER-003 checks for pinned image versions in FROM."""

    async def test_from_with_latest_tag_flagged(
        self, scanner: DockerSecurityScanner, tmp_path: Path
    ) -> None:
        """FROM image:latest should trigger DOCKER-003."""
        _write_file(
            tmp_path,
            "Dockerfile",
            """\
            FROM python:latest
            USER appuser
            HEALTHCHECK CMD true
            CMD ["python"]
            """,
        )

        violations = await scanner.scan(tmp_path)
        docker003 = [v for v in violations if v.code == "DOCKER-003"]

        assert len(docker003) >= 1
        assert docker003[0].severity == "warning"
        assert "latest" in docker003[0].message.lower()

    async def test_from_without_any_tag_flagged(
        self, scanner: DockerSecurityScanner, tmp_path: Path
    ) -> None:
        """FROM image (no tag at all) should trigger DOCKER-003 (implicit :latest)."""
        _write_file(
            tmp_path,
            "Dockerfile",
            """\
            FROM python
            USER appuser
            HEALTHCHECK CMD true
            CMD ["python"]
            """,
        )

        violations = await scanner.scan(tmp_path)
        docker003 = [v for v in violations if v.code == "DOCKER-003"]

        assert len(docker003) >= 1
        assert "no tag" in docker003[0].message.lower() or "latest" in docker003[0].message.lower()

    async def test_from_with_specific_version_not_flagged(
        self, scanner: DockerSecurityScanner, tmp_path: Path
    ) -> None:
        """FROM python:3.12-slim should NOT trigger DOCKER-003."""
        _write_file(
            tmp_path,
            "Dockerfile",
            """\
            FROM python:3.12-slim
            USER appuser
            HEALTHCHECK CMD true
            CMD ["python"]
            """,
        )

        violations = await scanner.scan(tmp_path)
        docker003 = [v for v in violations if v.code == "DOCKER-003"]

        assert len(docker003) == 0


# ---------------------------------------------------------------------------
# DOCKER-004: Exposing unnecessary / debug ports
# ---------------------------------------------------------------------------


class TestDocker004DebugPorts:
    """DOCKER-004 checks for exposing well-known debug or sensitive ports."""

    async def test_expose_debug_ports_flagged(
        self, scanner: DockerSecurityScanner, tmp_path: Path
    ) -> None:
        """EXPOSE with known debug ports (5005, 9229) should trigger DOCKER-004."""
        _write_file(
            tmp_path,
            "Dockerfile",
            """\
            FROM python:3.12-slim
            USER appuser
            HEALTHCHECK CMD true
            EXPOSE 8080 5005 9229
            CMD ["python", "main.py"]
            """,
        )

        violations = await scanner.scan(tmp_path)
        docker004 = [v for v in violations if v.code == "DOCKER-004"]

        assert len(docker004) >= 2  # 5005 and 9229 are both debug ports
        flagged_messages = " ".join(v.message for v in docker004)
        assert "5005" in flagged_messages
        assert "9229" in flagged_messages

    async def test_expose_safe_port_not_flagged(
        self, scanner: DockerSecurityScanner, tmp_path: Path
    ) -> None:
        """EXPOSE with only standard application ports should NOT trigger DOCKER-004."""
        _write_file(
            tmp_path,
            "Dockerfile",
            """\
            FROM python:3.12-slim
            USER appuser
            HEALTHCHECK CMD true
            EXPOSE 8080
            CMD ["python", "main.py"]
            """,
        )

        violations = await scanner.scan(tmp_path)
        docker004 = [v for v in violations if v.code == "DOCKER-004"]

        assert len(docker004) == 0


# ---------------------------------------------------------------------------
# DOCKER-005: Missing resource limits in compose
# ---------------------------------------------------------------------------


class TestDocker005ResourceLimits:
    """DOCKER-005 checks for deploy.resources.limits in compose services."""

    async def test_compose_without_resource_limits_flagged(
        self, scanner: DockerSecurityScanner, tmp_path: Path
    ) -> None:
        """A docker-compose service without deploy.resources.limits triggers DOCKER-005."""
        _write_file(
            tmp_path,
            "docker-compose.yml",
            """\
            version: "3.8"
            services:
              api-server:
                image: myapp:1.0
                ports:
                  - "8080:8080"
            """,
        )

        violations = await scanner.scan(tmp_path)
        docker005 = [v for v in violations if v.code == "DOCKER-005"]

        assert len(docker005) >= 1
        assert docker005[0].category == "docker"
        assert docker005[0].severity == "warning"
        assert "api-server" in docker005[0].message

    async def test_compose_with_resource_limits_not_flagged(
        self, scanner: DockerSecurityScanner, tmp_path: Path
    ) -> None:
        """A docker-compose service with deploy.resources.limits should NOT trigger DOCKER-005."""
        _write_file(
            tmp_path,
            "docker-compose.yml",
            """\
            version: "3.8"
            services:
              api-server:
                image: myapp:1.0
                ports:
                  - "8080:8080"
                deploy:
                  resources:
                    limits:
                      cpus: "0.5"
                      memory: 256M
            """,
        )

        violations = await scanner.scan(tmp_path)
        docker005 = [v for v in violations if v.code == "DOCKER-005"]

        assert len(docker005) == 0


# ---------------------------------------------------------------------------
# DOCKER-006: Privileged container in compose
# ---------------------------------------------------------------------------


class TestDocker006Privileged:
    """DOCKER-006 checks for privileged: true in compose services."""

    async def test_compose_with_privileged_true_flagged(
        self, scanner: DockerSecurityScanner, tmp_path: Path
    ) -> None:
        """A compose service with privileged: true should trigger DOCKER-006."""
        _write_file(
            tmp_path,
            "docker-compose.yml",
            """\
            version: "3.8"
            services:
              worker:
                image: worker:1.0
                privileged: true
                deploy:
                  resources:
                    limits:
                      cpus: "1.0"
                      memory: 512M
            """,
        )

        violations = await scanner.scan(tmp_path)
        docker006 = [v for v in violations if v.code == "DOCKER-006"]

        assert len(docker006) >= 1
        assert docker006[0].severity == "error"
        assert "privileged" in docker006[0].message.lower()

    async def test_compose_without_privileged_not_flagged(
        self, scanner: DockerSecurityScanner, tmp_path: Path
    ) -> None:
        """A compose service without privileged flag should NOT trigger DOCKER-006."""
        _write_file(
            tmp_path,
            "docker-compose.yml",
            """\
            version: "3.8"
            services:
              worker:
                image: worker:1.0
                deploy:
                  resources:
                    limits:
                      cpus: "1.0"
                      memory: 512M
            """,
        )

        violations = await scanner.scan(tmp_path)
        docker006 = [v for v in violations if v.code == "DOCKER-006"]

        assert len(docker006) == 0


# ---------------------------------------------------------------------------
# DOCKER-007: Writable root filesystem in compose
# ---------------------------------------------------------------------------


class TestDocker007WritableRootFs:
    """DOCKER-007 checks that security-sensitive services set read_only: true."""

    async def test_compose_without_read_only_flagged(
        self, scanner: DockerSecurityScanner, tmp_path: Path
    ) -> None:
        """A security-sensitive service without read_only: true triggers DOCKER-007."""
        _write_file(
            tmp_path,
            "docker-compose.yml",
            """\
            version: "3.8"
            services:
              api-service:
                image: myapi:1.0
                deploy:
                  resources:
                    limits:
                      cpus: "0.5"
                      memory: 256M
            """,
        )

        violations = await scanner.scan(tmp_path)
        docker007 = [v for v in violations if v.code == "DOCKER-007"]

        assert len(docker007) >= 1
        assert docker007[0].severity == "warning"
        assert "read_only" in docker007[0].message

    async def test_compose_with_read_only_not_flagged(
        self, scanner: DockerSecurityScanner, tmp_path: Path
    ) -> None:
        """A service with read_only: true should NOT trigger DOCKER-007."""
        _write_file(
            tmp_path,
            "docker-compose.yml",
            """\
            version: "3.8"
            services:
              api-service:
                image: myapi:1.0
                read_only: true
                deploy:
                  resources:
                    limits:
                      cpus: "0.5"
                      memory: 256M
            """,
        )

        violations = await scanner.scan(tmp_path)
        docker007 = [v for v in violations if v.code == "DOCKER-007"]

        assert len(docker007) == 0


# ---------------------------------------------------------------------------
# DOCKER-008: Missing security opts in compose
# ---------------------------------------------------------------------------


class TestDocker008SecurityOpts:
    """DOCKER-008 checks for security_opt: no-new-privileges in compose."""

    async def test_compose_without_security_opt_flagged(
        self, scanner: DockerSecurityScanner, tmp_path: Path
    ) -> None:
        """A compose service without security_opt triggers DOCKER-008."""
        _write_file(
            tmp_path,
            "docker-compose.yml",
            """\
            version: "3.8"
            services:
              backend:
                image: backend:1.0
                deploy:
                  resources:
                    limits:
                      cpus: "0.5"
                      memory: 256M
            """,
        )

        violations = await scanner.scan(tmp_path)
        docker008 = [v for v in violations if v.code == "DOCKER-008"]

        assert len(docker008) >= 1
        assert docker008[0].severity == "warning"
        assert "no-new-privileges" in docker008[0].message

    async def test_compose_with_security_opt_not_flagged(
        self, scanner: DockerSecurityScanner, tmp_path: Path
    ) -> None:
        """A compose service with no-new-privileges should NOT trigger DOCKER-008."""
        _write_file(
            tmp_path,
            "docker-compose.yml",
            """\
            version: "3.8"
            services:
              backend:
                image: backend:1.0
                security_opt:
                  - "no-new-privileges:true"
                deploy:
                  resources:
                    limits:
                      cpus: "0.5"
                      memory: 256M
            """,
        )

        violations = await scanner.scan(tmp_path)
        docker008 = [v for v in violations if v.code == "DOCKER-008"]

        assert len(docker008) == 0


# ---------------------------------------------------------------------------
# Edge cases: Non-Docker files, excluded directories, empty directory
# ---------------------------------------------------------------------------


class TestEdgeCases:
    """Edge cases for file classification and directory traversal."""

    async def test_non_docker_files_not_scanned(
        self, scanner: DockerSecurityScanner, tmp_path: Path
    ) -> None:
        """Files that are not Dockerfiles or docker-compose should produce no violations."""
        _write_file(
            tmp_path,
            "requirements.txt",
            """\
            flask==3.0.0
            requests==2.31.0
            """,
        )
        _write_file(
            tmp_path,
            "main.py",
            """\
            print("Hello World")
            """,
        )
        _write_file(
            tmp_path,
            "config.yaml",
            """\
            server:
              port: 8080
            """,
        )

        violations = await scanner.scan(tmp_path)

        assert len(violations) == 0

    async def test_excluded_directories_skipped(
        self, scanner: DockerSecurityScanner, tmp_path: Path
    ) -> None:
        """Dockerfiles inside excluded directories (node_modules, .git, etc.) are ignored."""
        excluded_dir = tmp_path / "node_modules" / "some-package"
        excluded_dir.mkdir(parents=True)

        # This Dockerfile would trigger violations if it were scanned
        _write_file(
            excluded_dir,
            "Dockerfile",
            """\
            FROM python:latest
            CMD ["python"]
            """,
        )

        violations = await scanner.scan(tmp_path)

        assert len(violations) == 0

    async def test_empty_directory_returns_empty_list(
        self, scanner: DockerSecurityScanner, tmp_path: Path
    ) -> None:
        """Scanning an empty directory should return an empty list."""
        empty = tmp_path / "empty_project"
        empty.mkdir()

        violations = await scanner.scan(empty)

        assert violations == []

    async def test_nonexistent_directory_returns_empty_list(
        self, scanner: DockerSecurityScanner, tmp_path: Path
    ) -> None:
        """Scanning a directory that does not exist should return an empty list."""
        nonexistent = tmp_path / "does_not_exist"

        violations = await scanner.scan(nonexistent)

        assert violations == []


# ---------------------------------------------------------------------------
# Integration / combined scenario tests
# ---------------------------------------------------------------------------


class TestCombinedScenarios:
    """Tests combining multiple violations and realistic project structures."""

    async def test_dockerfile_multiple_violations(
        self, scanner: DockerSecurityScanner, tmp_path: Path
    ) -> None:
        """A Dockerfile with many issues should produce multiple distinct violations."""
        _write_file(
            tmp_path,
            "Dockerfile",
            """\
            FROM python:latest
            WORKDIR /app
            COPY . .
            RUN pip install -r requirements.txt
            EXPOSE 8080 5005 9229 22
            CMD ["python", "main.py"]
            """,
        )

        violations = await scanner.scan(tmp_path)
        codes = _codes(violations)

        # No USER -> DOCKER-001
        assert "DOCKER-001" in codes
        # No HEALTHCHECK -> DOCKER-002
        assert "DOCKER-002" in codes
        # :latest tag -> DOCKER-003
        assert "DOCKER-003" in codes
        # Debug ports 5005, 9229, 22 -> DOCKER-004
        assert "DOCKER-004" in codes

    async def test_compose_multiple_violations(
        self, scanner: DockerSecurityScanner, tmp_path: Path
    ) -> None:
        """A compose file with many issues should produce multiple violations."""
        _write_file(
            tmp_path,
            "docker-compose.yml",
            """\
            version: "3.8"
            services:
              api-server:
                image: myapi:1.0
                privileged: true
            """,
        )

        violations = await scanner.scan(tmp_path)
        codes = _codes(violations)

        # No deploy.resources.limits -> DOCKER-005
        assert "DOCKER-005" in codes
        # privileged: true -> DOCKER-006
        assert "DOCKER-006" in codes
        # No read_only on security-sensitive name -> DOCKER-007
        assert "DOCKER-007" in codes
        # No security_opt -> DOCKER-008
        assert "DOCKER-008" in codes

    async def test_fully_secure_dockerfile_clean(
        self, scanner: DockerSecurityScanner, tmp_path: Path
    ) -> None:
        """A fully hardened Dockerfile should produce no violations."""
        _write_file(
            tmp_path,
            "Dockerfile",
            """\
            FROM python:3.12-slim AS builder
            WORKDIR /app
            COPY requirements.txt .
            RUN pip install --no-cache-dir -r requirements.txt

            FROM python:3.12-slim
            RUN adduser --disabled-password --gecos '' appuser
            WORKDIR /app
            COPY --from=builder /app /app
            COPY . .
            EXPOSE 8080
            HEALTHCHECK --interval=30s --timeout=3s --retries=3 \
                CMD curl -f http://localhost:8080/health || exit 1
            USER appuser
            CMD ["python", "main.py"]
            """,
        )

        violations = await scanner.scan(tmp_path)

        assert len(violations) == 0

    async def test_fully_secure_compose_clean(
        self, scanner: DockerSecurityScanner, tmp_path: Path
    ) -> None:
        """A fully hardened compose file should produce no violations."""
        _write_file(
            tmp_path,
            "docker-compose.yml",
            """\
            version: "3.8"
            services:
              api-service:
                image: myapi:1.0
                read_only: true
                security_opt:
                  - "no-new-privileges:true"
                deploy:
                  resources:
                    limits:
                      cpus: "0.5"
                      memory: 256M
            """,
        )

        violations = await scanner.scan(tmp_path)

        assert len(violations) == 0

    async def test_mixed_project_with_dockerfile_and_compose(
        self, scanner: DockerSecurityScanner, tmp_path: Path
    ) -> None:
        """A project with both Dockerfile and compose issues yields violations from both."""
        # Insecure Dockerfile
        _write_file(
            tmp_path,
            "Dockerfile",
            """\
            FROM node:latest
            WORKDIR /app
            COPY . .
            EXPOSE 9229
            CMD ["node", "server.js"]
            """,
        )
        # Insecure compose
        _write_file(
            tmp_path,
            "docker-compose.yml",
            """\
            version: "3.8"
            services:
              web-app:
                build: .
                privileged: true
            """,
        )

        violations = await scanner.scan(tmp_path)
        codes = _codes(violations)

        # Dockerfile violations
        assert "DOCKER-001" in codes  # no USER
        assert "DOCKER-002" in codes  # no HEALTHCHECK
        assert "DOCKER-003" in codes  # :latest
        assert "DOCKER-004" in codes  # debug port 9229

        # Compose violations
        assert "DOCKER-005" in codes  # no resource limits
        assert "DOCKER-006" in codes  # privileged
        assert "DOCKER-007" in codes  # no read_only (web-app is sensitive name)
        assert "DOCKER-008" in codes  # no security_opt

    async def test_dockerfile_variant_names_recognised(
        self, scanner: DockerSecurityScanner, tmp_path: Path
    ) -> None:
        """Dockerfile variants like Dockerfile.prod and app.dockerfile are scanned."""
        _write_file(
            tmp_path,
            "Dockerfile.prod",
            """\
            FROM python:3.12-slim
            WORKDIR /app
            COPY . .
            CMD ["python", "main.py"]
            """,
        )
        _write_file(
            tmp_path,
            "app.dockerfile",
            """\
            FROM node:20-slim
            WORKDIR /app
            COPY . .
            CMD ["node", "index.js"]
            """,
        )

        violations = await scanner.scan(tmp_path)

        # Both files should be scanned and produce at least DOCKER-001 (no USER) each
        docker001 = [v for v in violations if v.code == "DOCKER-001"]
        assert len(docker001) >= 2

    async def test_violation_file_path_is_set(
        self, scanner: DockerSecurityScanner, tmp_path: Path
    ) -> None:
        """Every violation should carry the file_path of the offending file."""
        dockerfile = _write_file(
            tmp_path,
            "Dockerfile",
            """\
            FROM python:latest
            CMD ["python"]
            """,
        )

        violations = await scanner.scan(tmp_path)

        assert len(violations) > 0
        for v in violations:
            assert v.file_path != ""
            assert "Dockerfile" in v.file_path

    async def test_multiple_excluded_dirs_all_skipped(
        self, scanner: DockerSecurityScanner, tmp_path: Path
    ) -> None:
        """Dockerfiles under .venv, __pycache__, .git, and dist are all skipped."""
        for dirname in (".venv", "__pycache__", ".git", "dist", "build"):
            excluded = tmp_path / dirname
            excluded.mkdir(parents=True, exist_ok=True)
            _write_file(
                excluded,
                "Dockerfile",
                """\
                FROM python:latest
                CMD ["python"]
                """,
            )

        violations = await scanner.scan(tmp_path)

        assert len(violations) == 0

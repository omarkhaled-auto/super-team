"""Docker security scanner for Build 3 quality gate.

Scans Dockerfiles and docker-compose files for security issues including
running as root, missing health checks, latest tags, excessive port exposure,
missing resource limits, privileged containers, writable root filesystems,
and missing security options.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

import yaml

from src.build3_shared.constants import DOCKER_SCAN_CODES
from src.build3_shared.models import ScanViolation

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Excluded directories -- never descend into these
# ---------------------------------------------------------------------------
EXCLUDED_DIRS: frozenset[str] = frozenset({
    "node_modules",
    ".venv",
    "venv",
    "__pycache__",
    ".git",
    "dist",
    "build",
})

# ---------------------------------------------------------------------------
# Module-level compiled regex patterns
# ---------------------------------------------------------------------------

# Dockerfile patterns
_RE_FROM = re.compile(r"^\s*FROM\s+", re.IGNORECASE)
_RE_FROM_LINE = re.compile(
    r"^\s*FROM\s+(?P<image>[^\s]+)(?:\s+AS\s+\S+)?",
    re.IGNORECASE,
)
_RE_USER_INSTRUCTION = re.compile(r"^\s*USER\s+", re.IGNORECASE)
_RE_USER_ROOT = re.compile(r"^\s*USER\s+root\s*$", re.IGNORECASE)
_RE_HEALTHCHECK = re.compile(r"^\s*HEALTHCHECK\s+", re.IGNORECASE | re.MULTILINE)
_RE_EXPOSE = re.compile(
    r"^\s*EXPOSE\s+(?P<ports>.+)",
    re.IGNORECASE,
)
_RE_LATEST_TAG = re.compile(r":latest\s*$")
_RE_NO_TAG = re.compile(
    r"^\s*FROM\s+(?P<image>[a-zA-Z0-9._/-]+)\s*(?:AS\s+\S+)?\s*$",
    re.IGNORECASE,
)
_RE_PORT_NUMBER = re.compile(r"\d+")

# Compose patterns (regex fallback)
_RE_PRIVILEGED = re.compile(r"^\s*privileged\s*:\s*true", re.IGNORECASE | re.MULTILINE)
_RE_READ_ONLY = re.compile(r"^\s*read_only\s*:\s*true", re.IGNORECASE | re.MULTILINE)
_RE_SECURITY_OPT_NO_NEW_PRIV = re.compile(
    r"no-new-privileges\s*:\s*true", re.IGNORECASE
)
_RE_DEPLOY_RESOURCES = re.compile(
    r"^\s*deploy\s*:", re.IGNORECASE | re.MULTILINE
)
_RE_SERVICE_BLOCK = re.compile(
    r"^\s{2}(\S+)\s*:", re.MULTILINE
)

# Well-known debug / sensitive ports that should not be exposed
_DEBUG_PORTS: frozenset[int] = frozenset({
    22,     # SSH
    2375,   # Docker daemon (unencrypted)
    2376,   # Docker daemon (TLS)
    5005,   # Java debug
    5858,   # Node debug (legacy)
    8000,   # Common dev server
    9229,   # Node inspector
    9090,   # Prometheus
    15672,  # RabbitMQ management
    27017,  # MongoDB
})

# Maximum number of exposed ports before flagging
_MAX_EXPOSED_PORTS = 5

# Security-sensitive service name patterns
_RE_SENSITIVE_SERVICE = re.compile(
    r"(api|auth|gateway|proxy|web|app|server|backend|frontend|service)",
    re.IGNORECASE,
)


class DockerSecurityScanner:
    """Scans Dockerfiles and docker-compose files for security issues.

    Implements the QualityScanner protocol with
    ``async def scan(self, target_dir: Path) -> list[ScanViolation]``.
    """

    # -----------------------------------------------------------------------
    # Public interface
    # -----------------------------------------------------------------------

    async def scan(self, target_dir: Path) -> list[ScanViolation]:
        """Scan a target directory for Docker security violations.

        Args:
            target_dir: Root directory to recursively scan.

        Returns:
            List of all Docker security violations found.
        """
        violations: list[ScanViolation] = []
        target = Path(target_dir)

        if not target.is_dir():
            logger.warning("Target directory does not exist: %s", target)
            return violations

        for file_path in target.rglob("*"):
            if not file_path.is_file():
                continue
            if self._should_skip_file(file_path):
                continue

            try:
                if self._is_dockerfile(file_path):
                    violations.extend(self._scan_dockerfile(file_path))
                elif self._is_compose_file(file_path):
                    violations.extend(self._scan_compose_file(file_path))
            except Exception:
                logger.exception("Error scanning file: %s", file_path)

        return violations

    # -----------------------------------------------------------------------
    # File classification helpers
    # -----------------------------------------------------------------------

    def _should_skip_file(self, file_path: Path) -> bool:
        """Return True if the file resides in an excluded directory."""
        parts = file_path.parts
        return any(part in EXCLUDED_DIRS for part in parts)

    def _is_dockerfile(self, file_path: Path) -> bool:
        """Return True if the file is a Dockerfile.

        Matches files named ``Dockerfile``, ``Dockerfile.*``, or ``*.dockerfile``.
        """
        name = file_path.name
        name_lower = name.lower()
        if name_lower == "dockerfile" or name_lower.startswith("dockerfile."):
            return True
        if name_lower.endswith(".dockerfile"):
            return True
        return False

    def _is_compose_file(self, file_path: Path) -> bool:
        """Return True if the file is a docker-compose YAML file.

        Matches files named ``docker-compose*.yml`` or ``docker-compose*.yaml``.
        """
        name_lower = file_path.name.lower()
        if name_lower.startswith("docker-compose") and name_lower.endswith(
            (".yml", ".yaml")
        ):
            return True
        return False

    # -----------------------------------------------------------------------
    # Dockerfile scanning
    # -----------------------------------------------------------------------

    def _scan_dockerfile(self, file_path: Path) -> list[ScanViolation]:
        """Run all Dockerfile checks against a single file."""
        try:
            content = file_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            logger.warning("Could not read file: %s", file_path)
            return []

        lines = content.splitlines()
        violations: list[ScanViolation] = []

        violations.extend(self._check_root_user(content, lines, file_path))
        violations.extend(self._check_health_check(content, file_path))
        violations.extend(self._check_latest_tag(lines, file_path))
        violations.extend(self._check_exposed_ports(lines, file_path))

        return violations

    # -----------------------------------------------------------------------
    # Compose file scanning
    # -----------------------------------------------------------------------

    def _scan_compose_file(self, file_path: Path) -> list[ScanViolation]:
        """Run all docker-compose checks against a single file."""
        try:
            content = file_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            logger.warning("Could not read file: %s", file_path)
            return []

        violations: list[ScanViolation] = []

        violations.extend(self._check_resource_limits(content, file_path))
        violations.extend(self._check_privileged(content, content.splitlines(), file_path))
        violations.extend(self._check_read_only(content, file_path))
        violations.extend(self._check_security_opts(content, file_path))

        return violations

    # -----------------------------------------------------------------------
    # DOCKER-001: Running as root
    # -----------------------------------------------------------------------

    def _check_root_user(
        self,
        content: str,
        lines: list[str],
        file_path: Path,
    ) -> list[ScanViolation]:
        """Check for containers running as root (DOCKER-001).

        Flags when:
        - No USER instruction exists in the Dockerfile.
        - An explicit ``USER root`` is the last USER instruction.
        """
        violations: list[ScanViolation] = []
        user_lines: list[tuple[int, str]] = []

        for idx, line in enumerate(lines, start=1):
            if _RE_USER_INSTRUCTION.match(line):
                user_lines.append((idx, line.strip()))

        if not user_lines:
            # No USER instruction at all -- running as root by default
            violations.append(
                ScanViolation(
                    code=DOCKER_SCAN_CODES[0],  # DOCKER-001
                    severity="error",
                    category="docker",
                    file_path=str(file_path),
                    line=1,
                    message=(
                        "Dockerfile has no USER instruction; "
                        "container will run as root by default. "
                        "Suggestion: Add a USER instruction to run as a non-root user, "
                        "e.g. 'USER appuser' or 'USER 1001'."
                    ),
                )
            )
        else:
            # Check if the last USER instruction is USER root
            last_line_num, last_line_text = user_lines[-1]
            if _RE_USER_ROOT.match(last_line_text):
                violations.append(
                    ScanViolation(
                        code=DOCKER_SCAN_CODES[0],  # DOCKER-001
                        severity="error",
                        category="docker",
                        file_path=str(file_path),
                        line=last_line_num,
                        message=(
                            "Dockerfile explicitly sets USER root; "
                            "container will run with root privileges. "
                            "Suggestion: Change to a non-root user, e.g. 'USER appuser' "
                            "or 'USER 1001'."
                        ),
                    )
                )

        return violations

    # -----------------------------------------------------------------------
    # DOCKER-002: No health check
    # -----------------------------------------------------------------------

    def _check_health_check(
        self,
        content: str,
        file_path: Path,
    ) -> list[ScanViolation]:
        """Check for missing HEALTHCHECK instruction (DOCKER-002)."""
        violations: list[ScanViolation] = []

        if not _RE_HEALTHCHECK.search(content):
            violations.append(
                ScanViolation(
                    code=DOCKER_SCAN_CODES[1],  # DOCKER-002
                    severity="warning",
                    category="docker",
                    file_path=str(file_path),
                    line=1,
                    message=(
                        "Dockerfile is missing a HEALTHCHECK instruction. "
                        "Suggestion: Add a HEALTHCHECK instruction, e.g. "
                        "'HEALTHCHECK --interval=30s --timeout=3s "
                        "CMD curl -f http://localhost/ || exit 1'."
                    ),
                )
            )

        return violations

    # -----------------------------------------------------------------------
    # DOCKER-003: Using latest tag
    # -----------------------------------------------------------------------

    def _check_latest_tag(
        self,
        lines: list[str],
        file_path: Path,
    ) -> list[ScanViolation]:
        """Check for FROM instructions using :latest or no tag (DOCKER-003)."""
        violations: list[ScanViolation] = []

        for idx, line in enumerate(lines, start=1):
            match = _RE_FROM_LINE.match(line)
            if not match:
                continue

            image = match.group("image")

            # Skip scratch and ARG-based images
            if image.lower() == "scratch":
                continue
            if image.startswith("$"):
                continue

            # Check for explicit :latest
            if _RE_LATEST_TAG.search(image):
                violations.append(
                    ScanViolation(
                        code=DOCKER_SCAN_CODES[2],  # DOCKER-003
                        severity="warning",
                        category="docker",
                        file_path=str(file_path),
                        line=idx,
                        message=(
                            f"FROM uses ':latest' tag: {image}. "
                            "Builds may break when the upstream image changes. "
                            "Suggestion: Pin to a specific version tag, e.g. "
                            f"'{image.rsplit(':latest', 1)[0]}:3.12-slim'."
                        ),
                    )
                )
            elif ":" not in image and "@" not in image:
                # No tag and no digest -- implicitly :latest
                violations.append(
                    ScanViolation(
                        code=DOCKER_SCAN_CODES[2],  # DOCKER-003
                        severity="warning",
                        category="docker",
                        file_path=str(file_path),
                        line=idx,
                        message=(
                            f"FROM has no tag: {image}. "
                            "This implicitly uses ':latest'. "
                            f"Suggestion: Pin to a specific version, e.g. '{image}:3.12-slim'."
                        ),
                    )
                )

        return violations

    # -----------------------------------------------------------------------
    # DOCKER-004: Exposing unnecessary ports
    # -----------------------------------------------------------------------

    def _check_exposed_ports(
        self,
        lines: list[str],
        file_path: Path,
    ) -> list[ScanViolation]:
        """Check for excessive or debug port exposure (DOCKER-004)."""
        violations: list[ScanViolation] = []
        all_ports: list[tuple[int, int]] = []  # (line_number, port)

        for idx, line in enumerate(lines, start=1):
            match = _RE_EXPOSE.match(line)
            if not match:
                continue

            ports_str = match.group("ports")
            port_numbers = _RE_PORT_NUMBER.findall(ports_str)
            for port_str in port_numbers:
                try:
                    port = int(port_str)
                    all_ports.append((idx, port))
                except ValueError:
                    continue

        # Flag debug ports
        for line_num, port in all_ports:
            if port in _DEBUG_PORTS:
                violations.append(
                    ScanViolation(
                        code=DOCKER_SCAN_CODES[3],  # DOCKER-004
                        severity="warning",
                        category="docker",
                        file_path=str(file_path),
                        line=line_num,
                        message=(
                            f"EXPOSE includes well-known debug/sensitive port {port}. "
                            f"Suggestion: Remove port {port} from EXPOSE unless it is "
                            "required in production."
                        ),
                    )
                )

        # Flag too many ports
        if len(all_ports) > _MAX_EXPOSED_PORTS:
            # Report on the first EXPOSE line
            first_line = all_ports[0][0] if all_ports else 1
            violations.append(
                ScanViolation(
                    code=DOCKER_SCAN_CODES[3],  # DOCKER-004
                    severity="warning",
                    category="docker",
                    file_path=str(file_path),
                    line=first_line,
                    message=(
                        f"Dockerfile exposes {len(all_ports)} ports, "
                        f"which exceeds the recommended maximum of {_MAX_EXPOSED_PORTS}. "
                        "Suggestion: Reduce the number of exposed ports. "
                        "Only expose ports that are required in production."
                    ),
                )
            )

        return violations

    # -----------------------------------------------------------------------
    # DOCKER-005: Missing resource limits
    # -----------------------------------------------------------------------

    def _check_resource_limits(
        self,
        content: str,
        file_path: Path,
    ) -> list[ScanViolation]:
        """Check for missing deploy.resources.limits in compose services (DOCKER-005)."""
        violations: list[ScanViolation] = []
        compose_data = self._parse_yaml_safe(content)

        if compose_data is not None:
            services = self._extract_services(compose_data)
            for svc_name, svc_config in services.items():
                if not isinstance(svc_config, dict):
                    continue
                deploy = svc_config.get("deploy", {})
                if not isinstance(deploy, dict):
                    deploy = {}
                resources = deploy.get("resources", {})
                if not isinstance(resources, dict):
                    resources = {}
                limits = resources.get("limits")

                if not limits:
                    line = self._find_service_line(content, svc_name)
                    violations.append(
                        ScanViolation(
                            code=DOCKER_SCAN_CODES[4],  # DOCKER-005
                            severity="warning",
                            category="docker",
                            file_path=str(file_path),
                            line=line,
                            message=(
                                f"Service '{svc_name}' has no "
                                "deploy.resources.limits configured. "
                                f"Suggestion: Add resource limits for service '{svc_name}': "
                                "deploy.resources.limits.cpus and "
                                "deploy.resources.limits.memory."
                            ),
                        )
                    )
        else:
            # Regex fallback: check if any service-like block lacks deploy
            self._check_resource_limits_regex(content, file_path, violations)

        return violations

    # -----------------------------------------------------------------------
    # DOCKER-006: Privileged container
    # -----------------------------------------------------------------------

    def _check_privileged(
        self,
        content: str,
        lines: list[str],
        file_path: Path,
    ) -> list[ScanViolation]:
        """Check for privileged: true in compose file (DOCKER-006)."""
        violations: list[ScanViolation] = []
        compose_data = self._parse_yaml_safe(content)

        if compose_data is not None:
            services = self._extract_services(compose_data)
            for svc_name, svc_config in services.items():
                if not isinstance(svc_config, dict):
                    continue
                if svc_config.get("privileged") is True:
                    line = self._find_key_line(content, "privileged", svc_name)
                    violations.append(
                        ScanViolation(
                            code=DOCKER_SCAN_CODES[5],  # DOCKER-006
                            severity="error",
                            category="docker",
                            file_path=str(file_path),
                            line=line,
                            message=(
                                f"Service '{svc_name}' runs in privileged mode. "
                                "Suggestion: Remove 'privileged: true' and use specific "
                                "capabilities with cap_add instead."
                            ),
                        )
                    )
        else:
            # Regex fallback
            for match in _RE_PRIVILEGED.finditer(content):
                line_num = content[:match.start()].count("\n") + 1
                violations.append(
                    ScanViolation(
                        code=DOCKER_SCAN_CODES[5],  # DOCKER-006
                        severity="error",
                        category="docker",
                        file_path=str(file_path),
                        line=line_num,
                        message=(
                            "Container runs in privileged mode. "
                            "Suggestion: Remove 'privileged: true' and use specific "
                            "capabilities with cap_add instead."
                        ),
                    )
                )

        return violations

    # -----------------------------------------------------------------------
    # DOCKER-007: Writable root filesystem
    # -----------------------------------------------------------------------

    def _check_read_only(
        self,
        content: str,
        file_path: Path,
    ) -> list[ScanViolation]:
        """Check for missing read_only: true on security-sensitive services (DOCKER-007)."""
        violations: list[ScanViolation] = []
        compose_data = self._parse_yaml_safe(content)

        if compose_data is not None:
            services = self._extract_services(compose_data)
            for svc_name, svc_config in services.items():
                if not isinstance(svc_config, dict):
                    continue
                # Only flag security-sensitive services
                if not _RE_SENSITIVE_SERVICE.search(svc_name):
                    continue
                if svc_config.get("read_only") is not True:
                    line = self._find_service_line(content, svc_name)
                    violations.append(
                        ScanViolation(
                            code=DOCKER_SCAN_CODES[6],  # DOCKER-007
                            severity="warning",
                            category="docker",
                            file_path=str(file_path),
                            line=line,
                            message=(
                                f"Service '{svc_name}' does not set "
                                "'read_only: true' for its root filesystem. "
                                f"Suggestion: Add 'read_only: true' to service '{svc_name}' "
                                "to prevent filesystem modification. Use tmpfs "
                                "mounts for directories that need to be writable."
                            ),
                        )
                    )
        else:
            # Regex fallback: if no read_only found at all, flag the file
            if not _RE_READ_ONLY.search(content):
                violations.append(
                    ScanViolation(
                        code=DOCKER_SCAN_CODES[6],  # DOCKER-007
                        severity="warning",
                        category="docker",
                        file_path=str(file_path),
                        line=1,
                        message=(
                            "No service has 'read_only: true' set for its "
                            "root filesystem. "
                            "Suggestion: Add 'read_only: true' to security-sensitive "
                            "services to prevent filesystem modification."
                        ),
                    )
                )

        return violations

    # -----------------------------------------------------------------------
    # DOCKER-008: Missing security opts
    # -----------------------------------------------------------------------

    def _check_security_opts(
        self,
        content: str,
        file_path: Path,
    ) -> list[ScanViolation]:
        """Check for missing security_opt: no-new-privileges (DOCKER-008)."""
        violations: list[ScanViolation] = []
        compose_data = self._parse_yaml_safe(content)

        if compose_data is not None:
            services = self._extract_services(compose_data)
            for svc_name, svc_config in services.items():
                if not isinstance(svc_config, dict):
                    continue
                security_opts = svc_config.get("security_opt", [])
                if not isinstance(security_opts, list):
                    security_opts = []

                has_no_new_priv = any(
                    "no-new-privileges" in str(opt)
                    for opt in security_opts
                )

                if not has_no_new_priv:
                    line = self._find_service_line(content, svc_name)
                    violations.append(
                        ScanViolation(
                            code=DOCKER_SCAN_CODES[7],  # DOCKER-008
                            severity="warning",
                            category="docker",
                            file_path=str(file_path),
                            line=line,
                            message=(
                                f"Service '{svc_name}' is missing "
                                "'security_opt: [\"no-new-privileges:true\"]'. "
                                f"Suggestion: Add 'security_opt: "
                                f'["no-new-privileges:true"]'
                                f"' to service '{svc_name}'."
                            ),
                        )
                    )
        else:
            # Regex fallback
            if not _RE_SECURITY_OPT_NO_NEW_PRIV.search(content):
                violations.append(
                    ScanViolation(
                        code=DOCKER_SCAN_CODES[7],  # DOCKER-008
                        severity="warning",
                        category="docker",
                        file_path=str(file_path),
                        line=1,
                        message=(
                            "No service has "
                            "'security_opt: [\"no-new-privileges:true\"]' set. "
                            "Suggestion: Add 'security_opt: [\"no-new-privileges:true\"]' "
                            "to all services."
                        ),
                    )
                )

        return violations

    # -----------------------------------------------------------------------
    # YAML parsing helpers
    # -----------------------------------------------------------------------

    @staticmethod
    def _parse_yaml_safe(content: str) -> dict[str, Any] | None:
        """Attempt to parse YAML content, returning None on failure."""
        try:
            data = yaml.safe_load(content)
            if isinstance(data, dict):
                return data
        except yaml.YAMLError:
            logger.debug("Failed to parse YAML content; falling back to regex.")
        return None

    @staticmethod
    def _extract_services(compose_data: dict[str, Any]) -> dict[str, Any]:
        """Extract the services mapping from a compose data dict.

        Handles both ``services:`` key and top-level service definitions
        (Compose v1 without the services key).
        """
        services = compose_data.get("services")
        if isinstance(services, dict):
            return services
        # Compose v1 fallback: top-level keys that look like service defs
        result: dict[str, Any] = {}
        skip_keys = {"version", "volumes", "networks", "configs", "secrets", "x-"}
        for key, value in compose_data.items():
            if any(key.startswith(sk) for sk in skip_keys):
                continue
            if isinstance(value, dict) and ("image" in value or "build" in value):
                result[key] = value
        return result

    @staticmethod
    def _find_service_line(content: str, service_name: str) -> int:
        """Find the line number where a service is defined in raw YAML content."""
        pattern = re.compile(
            rf"^\s{{2}}{re.escape(service_name)}\s*:", re.MULTILINE
        )
        match = pattern.search(content)
        if match:
            return content[:match.start()].count("\n") + 1
        return 1

    @staticmethod
    def _find_key_line(
        content: str, key: str, service_name: str | None = None
    ) -> int:
        """Find the line number of a specific key, optionally within a service."""
        if service_name:
            # Try to find the key under the service
            svc_pattern = re.compile(
                rf"^\s{{2}}{re.escape(service_name)}\s*:", re.MULTILINE
            )
            svc_match = svc_pattern.search(content)
            if svc_match:
                remaining = content[svc_match.start():]
                key_pattern = re.compile(
                    rf"^\s+{re.escape(key)}\s*:", re.MULTILINE
                )
                key_match = key_pattern.search(remaining)
                if key_match:
                    offset = svc_match.start() + key_match.start()
                    return content[:offset].count("\n") + 1

        # Fallback: find the key anywhere
        key_pattern = re.compile(rf"^\s+{re.escape(key)}\s*:", re.MULTILINE)
        match = key_pattern.search(content)
        if match:
            return content[:match.start()].count("\n") + 1
        return 1

    def _check_resource_limits_regex(
        self,
        content: str,
        file_path: Path,
        violations: list[ScanViolation],
    ) -> None:
        """Regex fallback for resource limits check when YAML parsing fails."""
        service_matches = list(_RE_SERVICE_BLOCK.finditer(content))
        if not service_matches:
            return

        has_deploy = bool(_RE_DEPLOY_RESOURCES.search(content))
        if not has_deploy:
            for match in service_matches:
                svc_name = match.group(1)
                line_num = content[:match.start()].count("\n") + 1
                violations.append(
                    ScanViolation(
                        code=DOCKER_SCAN_CODES[4],  # DOCKER-005
                        severity="warning",
                        category="docker",
                        file_path=str(file_path),
                        line=line_num,
                        message=(
                            f"Service '{svc_name}' appears to have no "
                            "deploy.resources.limits configured. "
                            f"Suggestion: Add resource limits for service '{svc_name}': "
                            "deploy.resources.limits.cpus and "
                            "deploy.resources.limits.memory."
                        ),
                    )
                )

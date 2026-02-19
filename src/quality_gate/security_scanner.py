"""Security scanner for quality gate layer.

Scans source code for security violations across three categories:
- JWT security (SEC-001..SEC-006)
- CORS configuration (CORS-001..CORS-003)
- Secret detection (SEC-SECRET-001..SEC-SECRET-012)

All regex patterns are compiled at module level (TECH-018).
File walking uses pathlib.Path.rglob() exclusively (AC-004).
"""

from __future__ import annotations

import asyncio
import re
from pathlib import Path

from src.build3_shared.constants import CORS_SCAN_CODES, SECURITY_SCAN_CODES, SECRET_SCAN_CODES
from src.build3_shared.models import ScanViolation

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

EXCLUDED_DIRS: frozenset[str] = frozenset(
    {"node_modules", ".venv", "venv", "__pycache__", ".git", "dist", "build"}
)

MAX_VIOLATIONS_PER_CATEGORY: int = 200

SCANNABLE_EXTENSIONS: frozenset[str] = frozenset(
    {
        ".py", ".js", ".ts", ".jsx", ".tsx", ".java", ".go", ".rb", ".rs",
        ".yaml", ".yml", ".json", ".env", ".cfg", ".ini", ".toml",
    }
)

# ---------------------------------------------------------------------------
# Nosec suppression pattern (TECH-020)
# ---------------------------------------------------------------------------

_NOSEC_PATTERN: re.Pattern[str] = re.compile(
    r"(?:#|//)\s*(?:nosec|noqa:\s*(?P<code>SEC-SECRET-\d{3}|SEC-\d{3}|CORS-\d{3}))",
    re.IGNORECASE,
)

# ---------------------------------------------------------------------------
# JWT Security patterns (SEC-001..006)
# ---------------------------------------------------------------------------

# SEC-001: Route definitions without auth decorators/middleware.
# We detect route declarations and then check if preceding lines have auth.
_JWT_ROUTE_PATTERN: re.Pattern[str] = re.compile(
    r"@(?:app|router|blueprint)\."
    r"(?:get|post|put|patch|delete|route|api_route)\s*\(",
    re.IGNORECASE,
)
_JWT_AUTH_DECORATOR_PATTERN: re.Pattern[str] = re.compile(
    r"(?:@(?:login_required|auth_required|requires_auth|jwt_required|authenticate|"
    r"token_required|permission_required|Authorize|AuthGuard|secured|protected))|"
    r"(?:Depends\s*\(\s*(?:get_current_user|auth|verify_token|require_auth))|"
    r"(?:middleware\s*[:=]\s*\[?\s*['\"]?auth)",
    re.IGNORECASE,
)

# SEC-002: Hardcoded JWT secret -- jwt.encode/decode with a literal string.
_JWT_HARDCODED_SECRET_PATTERN: re.Pattern[str] = re.compile(
    r"jwt\.(?:encode|decode)\s*\([^)]*(?:key|secret)\s*=\s*[\"'][^\"']+[\"']",
    re.IGNORECASE,
)
_JWT_HARDCODED_SECRET_ALT_PATTERN: re.Pattern[str] = re.compile(
    r"jwt\.(?:encode|decode)\s*\(\s*[^,]+,\s*[\"'][A-Za-z0-9+/=_\-]{4,}[\"']",
    re.IGNORECASE,
)

# SEC-003: JWT creation without expiry (exp claim).
_JWT_ENCODE_PATTERN: re.Pattern[str] = re.compile(
    r"jwt\.encode\s*\(", re.IGNORECASE
)
_JWT_EXP_CLAIM_PATTERN: re.Pattern[str] = re.compile(
    r"""["\']exp["\']""", re.IGNORECASE
)

# SEC-004: Weak signing algorithm (HS256 or "none").
_JWT_WEAK_ALGO_PATTERN: re.Pattern[str] = re.compile(
    r"(?:algorithm|algorithms)\s*=\s*[\[\(]?\s*[\"'](?:HS256|none)[\"']",
    re.IGNORECASE,
)
_JWT_WEAK_ALGO_ALT_PATTERN: re.Pattern[str] = re.compile(
    r"jwt\.(?:encode|decode)\s*\([^)]*[\"'](?:HS256|none)[\"']",
    re.IGNORECASE,
)

# SEC-005: JWT decode without audience validation.
_JWT_DECODE_PATTERN: re.Pattern[str] = re.compile(
    r"jwt\.decode\s*\(", re.IGNORECASE
)
_JWT_AUDIENCE_PATTERN: re.Pattern[str] = re.compile(
    r"audience\s*=", re.IGNORECASE
)

# SEC-006: JWT decode without issuer validation.
_JWT_ISSUER_PATTERN: re.Pattern[str] = re.compile(
    r"issuer\s*=", re.IGNORECASE
)

# ---------------------------------------------------------------------------
# CORS patterns (CORS-001..003)
# ---------------------------------------------------------------------------

# CORS-001: Wildcard origin.
_CORS_WILDCARD_ORIGIN_PATTERN: re.Pattern[str] = re.compile(
    r"""(?:allow_origins\s*=\s*\[\s*["']\*["']\s*\])|"""
    r"""(?:Access-Control-Allow-Origin\s*[:=]\s*["']?\*)""",
    re.IGNORECASE,
)

# CORS-002: We check if a file has route definitions but no CORS config.
_CORS_CONFIG_PATTERN: re.Pattern[str] = re.compile(
    r"(?:CORSMiddleware|cors\s*\(|add_cors|cors_allowed|"
    r"Access-Control-Allow-Origin|cors\.init_app|enableCors|"
    r"@CrossOrigin|cors:\s*true|allow_origins)",
    re.IGNORECASE,
)
_ROUTE_DEFINITION_PATTERN: re.Pattern[str] = re.compile(
    r"(?:@(?:app|router|blueprint)\.(?:get|post|put|patch|delete|route|api_route)\s*\()|"
    r"(?:app\.use\s*\()|"
    r"(?:@RequestMapping|@GetMapping|@PostMapping|@PutMapping|@DeleteMapping)|"
    r"(?:func\s+\w+Handler\s*\()",
    re.IGNORECASE,
)

# CORS-003: Credentials with wildcard.
_CORS_CREDENTIALS_WITH_WILDCARD_PATTERN: re.Pattern[str] = re.compile(
    r"allow_credentials\s*=\s*True",
    re.IGNORECASE,
)

# ---------------------------------------------------------------------------
# Secret detection patterns (SEC-SECRET-001..012)
# ---------------------------------------------------------------------------

# SEC-SECRET-001: API key in source.
_SECRET_API_KEY_PATTERN: re.Pattern[str] = re.compile(
    r"""(?:api[_-]?key|apikey|x[_-]api[_-]key)\s*[:=]\s*["'][A-Za-z0-9+/=_\-]{8,}["']""",
    re.IGNORECASE,
)

# SEC-SECRET-002: Password in source.
_SECRET_PASSWORD_PATTERN: re.Pattern[str] = re.compile(
    r"""(?:password|passwd|pwd|db_password|DB_PASSWORD)\s*[:=]\s*["'][^"']{4,}["']""",
    re.IGNORECASE,
)

# SEC-SECRET-003: Private key block.
_SECRET_PRIVATE_KEY_PATTERN: re.Pattern[str] = re.compile(
    r"-----BEGIN\s+(?:RSA\s+)?PRIVATE\s+KEY-----",
    re.IGNORECASE,
)

# SEC-SECRET-004: AWS credentials.
_SECRET_AWS_KEY_PATTERN: re.Pattern[str] = re.compile(
    r"(?:AKIA[0-9A-Z]{16})|"
    r"""(?:aws_secret_access_key\s*[:=]\s*["'][A-Za-z0-9+/=]{20,}["'])""",
    re.IGNORECASE,
)

# SEC-SECRET-005: Database connection string.
_SECRET_DB_CONN_PATTERN: re.Pattern[str] = re.compile(
    r"""(?:postgresql|mysql|mongodb|redis|amqp|mssql)://[^\s"']+:[^\s"']+@""",
    re.IGNORECASE,
)

# SEC-SECRET-006: JWT secret in source.
_SECRET_JWT_SECRET_PATTERN: re.Pattern[str] = re.compile(
    r"""(?:jwt[_-]?secret|JWT_SECRET|jwt_secret_key|JWT_SECRET_KEY)\s*[:=]\s*["'][^"']{4,}["']""",
    re.IGNORECASE,
)

# SEC-SECRET-007: OAuth client secret.
_SECRET_OAUTH_PATTERN: re.Pattern[str] = re.compile(
    r"""(?:client[_-]?secret|CLIENT_SECRET|oauth[_-]?secret)\s*[:=]\s*["'][^"']{4,}["']""",
    re.IGNORECASE,
)

# SEC-SECRET-008: Encryption key in source.
_SECRET_ENCRYPTION_KEY_PATTERN: re.Pattern[str] = re.compile(
    r"""(?:encryption[_-]?key|ENCRYPTION_KEY|encrypt[_-]?key|aes[_-]?key|AES_KEY)\s*[:=]\s*["'][^"']{4,}["']""",
    re.IGNORECASE,
)

# SEC-SECRET-009: Token in source (long hex or base64 strings).
_SECRET_TOKEN_PATTERN: re.Pattern[str] = re.compile(
    r"""(?:token|auth_token|access_token|bearer_token|refresh_token)\s*[:=]\s*["'][A-Za-z0-9+/=_\-]{20,}["']""",
    re.IGNORECASE,
)

# SEC-SECRET-010: Certificate / EC private key.
_SECRET_CERT_KEY_PATTERN: re.Pattern[str] = re.compile(
    r"-----BEGIN\s+(?:CERTIFICATE|EC\s+PRIVATE\s+KEY)-----",
    re.IGNORECASE,
)

# SEC-SECRET-011: Service account key (GCP).
_SECRET_SERVICE_ACCOUNT_PATTERN: re.Pattern[str] = re.compile(
    r"""["']type["']\s*:\s*["']service_account["']""",
    re.IGNORECASE,
)

# SEC-SECRET-012: Webhook secret.
_SECRET_WEBHOOK_PATTERN: re.Pattern[str] = re.compile(
    r"""(?:webhook[_-]?secret|WEBHOOK_SECRET)\s*[:=]\s*["'][^"']{4,}["']""",
    re.IGNORECASE,
)

# Map secret codes to their compiled patterns, human-readable messages,
# and fix suggestions.
_SECRET_CHECKS: list[
    tuple[str, re.Pattern[str], str, str]
] = [
    (
        "SEC-SECRET-001",
        _SECRET_API_KEY_PATTERN,
        "API key found hardcoded in source code",
        "Move API keys to environment variables or a secrets manager",
    ),
    (
        "SEC-SECRET-002",
        _SECRET_PASSWORD_PATTERN,
        "Password found hardcoded in source code",
        "Move passwords to environment variables or a secrets manager",
    ),
    (
        "SEC-SECRET-003",
        _SECRET_PRIVATE_KEY_PATTERN,
        "Private key block found in source code",
        "Store private keys in a secure vault and load at runtime",
    ),
    (
        "SEC-SECRET-004",
        _SECRET_AWS_KEY_PATTERN,
        "AWS credentials found in source code",
        "Use IAM roles or AWS Secrets Manager instead of hardcoded credentials",
    ),
    (
        "SEC-SECRET-005",
        _SECRET_DB_CONN_PATTERN,
        "Database connection string with credentials found in source code",
        "Move connection strings to environment variables or a secrets manager",
    ),
    (
        "SEC-SECRET-006",
        _SECRET_JWT_SECRET_PATTERN,
        "JWT secret found hardcoded in source code",
        "Load JWT secrets from environment variables or a secrets manager",
    ),
    (
        "SEC-SECRET-007",
        _SECRET_OAUTH_PATTERN,
        "OAuth client secret found in source code",
        "Move OAuth secrets to environment variables or a secrets manager",
    ),
    (
        "SEC-SECRET-008",
        _SECRET_ENCRYPTION_KEY_PATTERN,
        "Encryption key found hardcoded in source code",
        "Store encryption keys in a key management service (KMS)",
    ),
    (
        "SEC-SECRET-009",
        _SECRET_TOKEN_PATTERN,
        "Token found hardcoded in source code",
        "Move tokens to environment variables or a secrets manager",
    ),
    (
        "SEC-SECRET-010",
        _SECRET_CERT_KEY_PATTERN,
        "Certificate or EC private key found in source code",
        "Store certificates and keys in a secure vault",
    ),
    (
        "SEC-SECRET-011",
        _SECRET_SERVICE_ACCOUNT_PATTERN,
        "Service account key file content found in source code",
        "Use workload identity or store service account keys in a secrets manager",
    ),
    (
        "SEC-SECRET-012",
        _SECRET_WEBHOOK_PATTERN,
        "Webhook secret found hardcoded in source code",
        "Move webhook secrets to environment variables or a secrets manager",
    ),
]


# ---------------------------------------------------------------------------
# SecurityScanner class
# ---------------------------------------------------------------------------


class SecurityScanner:
    """Scans source files for JWT, CORS, and secret-related security violations.

    Satisfies the ``QualityScanner`` protocol::

        async def scan(self, target_dir: Path) -> list[ScanViolation]
    """

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #

    async def scan(self, target_dir: Path) -> list[ScanViolation]:
        """Scan *target_dir* recursively for security violations.

        Returns a combined list of violations across all categories, capped
        at ``MAX_VIOLATIONS_PER_CATEGORY`` per category.
        """
        target_dir = Path(target_dir)
        if not target_dir.is_dir():
            return []

        # Collect all scannable files using pathlib.rglob (AC-004).
        files: list[Path] = [
            p
            for p in target_dir.rglob("*")
            if p.is_file()
            and p.suffix in SCANNABLE_EXTENSIONS
            and not self._should_skip_file(p)
        ]

        # Run file scans in a thread pool so we don't block the event loop.
        loop = asyncio.get_running_loop()
        violations: list[ScanViolation] = await loop.run_in_executor(
            None, self._scan_all_files, files
        )
        return violations

    # ------------------------------------------------------------------ #
    # Filtering helpers
    # ------------------------------------------------------------------ #

    def _should_skip_file(self, file_path: Path) -> bool:
        """Return ``True`` if *file_path* resides inside an excluded directory."""
        return bool(EXCLUDED_DIRS & set(file_path.parts))

    def _has_nosec(self, line: str, code: str = "") -> bool:
        """Return ``True`` if the *line* contains a ``nosec`` / ``noqa`` suppression.

        When *code* is provided, a ``noqa:`` suppression must reference that
        specific code to match.  A bare ``# nosec`` or ``// nosec`` always
        suppresses.
        """
        for m in _NOSEC_PATTERN.finditer(line):
            matched_code = m.group("code")
            if matched_code is None:
                # Bare nosec -- always suppresses.
                return True
            if code and matched_code.upper() == code.upper():
                return True
        return False

    # ------------------------------------------------------------------ #
    # Internal scanning
    # ------------------------------------------------------------------ #

    def _scan_all_files(self, files: list[Path]) -> list[ScanViolation]:
        """Scan all *files* and merge results with per-category caps."""
        jwt_violations: list[ScanViolation] = []
        cors_violations: list[ScanViolation] = []
        secret_violations: list[ScanViolation] = []

        for fp in files:
            file_results = self._scan_file(fp)
            for v in file_results:
                if v.category == "jwt_security":
                    if len(jwt_violations) < MAX_VIOLATIONS_PER_CATEGORY:
                        jwt_violations.append(v)
                elif v.category == "cors":
                    if len(cors_violations) < MAX_VIOLATIONS_PER_CATEGORY:
                        cors_violations.append(v)
                elif v.category == "secret_detection":
                    if len(secret_violations) < MAX_VIOLATIONS_PER_CATEGORY:
                        secret_violations.append(v)

        return jwt_violations + cors_violations + secret_violations

    def _scan_file(self, file_path: Path) -> list[ScanViolation]:
        """Scan a single file for all security violation categories."""
        try:
            content = file_path.read_text(encoding="utf-8", errors="replace")
        except (OSError, PermissionError):
            return []

        lines = content.splitlines()
        file_str = str(file_path)

        violations: list[ScanViolation] = []
        violations.extend(self._check_jwt_security(content, lines, file_str))
        violations.extend(self._check_cors(content, lines, file_str))
        violations.extend(self._check_secrets(content, lines, file_str))
        return violations

    # ------------------------------------------------------------------ #
    # JWT security checks (SEC-001..006)
    # ------------------------------------------------------------------ #

    def _check_jwt_security(
        self, content: str, lines: list[str], file_path: str
    ) -> list[ScanViolation]:
        violations: list[ScanViolation] = []

        # SEC-001: Route without auth decorator/middleware.
        for line_no, line in enumerate(lines, start=1):
            if _JWT_ROUTE_PATTERN.search(line):
                if self._has_nosec(line, "SEC-001"):
                    continue
                # Look backward up to 10 lines for an auth decorator.
                context_start = max(0, line_no - 11)
                context_lines = lines[context_start : line_no - 1]
                context_block = "\n".join(context_lines)
                if not _JWT_AUTH_DECORATOR_PATTERN.search(context_block):
                    violations.append(
                        ScanViolation(
                            code="SEC-001",
                            severity="warning",
                            category="jwt_security",
                            file_path=file_path,
                            line=line_no,
                            message=(
                                "Route handler missing authentication decorator or middleware. "
                                "Suggestion: Add an authentication decorator (e.g. @login_required, "
                                "@jwt_required) or inject an auth dependency"
                            ),
                        )
                    )

        # SEC-002: Hardcoded JWT secret.
        for line_no, line in enumerate(lines, start=1):
            if self._has_nosec(line, "SEC-002"):
                continue
            if _JWT_HARDCODED_SECRET_PATTERN.search(line) or _JWT_HARDCODED_SECRET_ALT_PATTERN.search(line):
                violations.append(
                    ScanViolation(
                        code="SEC-002",
                        severity="error",
                        category="jwt_security",
                        file_path=file_path,
                        line=line_no,
                        message="Hardcoded JWT secret detected in jwt.encode/decode call. Suggestion: Load the JWT signing secret from an environment variable or secrets manager",
                    )
                )

        # SEC-003: JWT creation without expiry claim.
        # Strategy: find jwt.encode calls and look for 'exp' in the surrounding
        # context (up to 10 lines before the call for the payload dict).
        for line_no, line in enumerate(lines, start=1):
            if _JWT_ENCODE_PATTERN.search(line):
                if self._has_nosec(line, "SEC-003"):
                    continue
                context_start = max(0, line_no - 11)
                context_end = min(len(lines), line_no + 3)
                context_block = "\n".join(lines[context_start:context_end])
                if not _JWT_EXP_CLAIM_PATTERN.search(context_block):
                    violations.append(
                        ScanViolation(
                            code="SEC-003",
                            severity="error",
                            category="jwt_security",
                            file_path=file_path,
                            line=line_no,
                            message="JWT token created without an expiry (exp) claim. Suggestion: Include an 'exp' claim in the JWT payload to limit token lifetime",
                        )
                    )

        # SEC-004: Weak signing algorithm.
        for line_no, line in enumerate(lines, start=1):
            if self._has_nosec(line, "SEC-004"):
                continue
            if _JWT_WEAK_ALGO_PATTERN.search(line) or _JWT_WEAK_ALGO_ALT_PATTERN.search(line):
                violations.append(
                    ScanViolation(
                        code="SEC-004",
                        severity="warning",
                        category="jwt_security",
                        file_path=file_path,
                        line=line_no,
                        message="Weak JWT signing algorithm detected (HS256 or 'none'). Suggestion: Use a stronger algorithm such as RS256 or ES256",
                    )
                )

        # SEC-005 / SEC-006: JWT decode without audience/issuer validation.
        # We locate jwt.decode calls and scan the surrounding context.
        for line_no, line in enumerate(lines, start=1):
            if _JWT_DECODE_PATTERN.search(line):
                context_start = max(0, line_no - 1)
                context_end = min(len(lines), line_no + 5)
                context_block = "\n".join(lines[context_start:context_end])

                if not self._has_nosec(line, "SEC-005"):
                    if not _JWT_AUDIENCE_PATTERN.search(context_block):
                        violations.append(
                            ScanViolation(
                                code="SEC-005",
                                severity="warning",
                                category="jwt_security",
                                file_path=file_path,
                                line=line_no,
                                message="JWT decode call missing audience validation. Suggestion: Pass the 'audience' parameter to jwt.decode() to validate the intended recipient",
                            )
                        )

                if not self._has_nosec(line, "SEC-006"):
                    if not _JWT_ISSUER_PATTERN.search(context_block):
                        violations.append(
                            ScanViolation(
                                code="SEC-006",
                                severity="warning",
                                category="jwt_security",
                                file_path=file_path,
                                line=line_no,
                                message="JWT decode call missing issuer validation. Suggestion: Pass the 'issuer' parameter to jwt.decode() to validate the token issuer",
                            )
                        )

        return violations

    # ------------------------------------------------------------------ #
    # CORS checks (CORS-001..003)
    # ------------------------------------------------------------------ #

    def _check_cors(
        self, content: str, lines: list[str], file_path: str
    ) -> list[ScanViolation]:
        violations: list[ScanViolation] = []

        has_wildcard_origin = False

        # CORS-001: Wildcard origin.
        for line_no, line in enumerate(lines, start=1):
            if _CORS_WILDCARD_ORIGIN_PATTERN.search(line):
                if self._has_nosec(line, "CORS-001"):
                    continue
                has_wildcard_origin = True
                violations.append(
                    ScanViolation(
                        code="CORS-001",
                        severity="warning",
                        category="cors",
                        file_path=file_path,
                        line=line_no,
                        message="CORS wildcard origin ('*') allows any website to make requests. Suggestion: Restrict allow_origins to specific trusted domains",
                    )
                )

        # CORS-002: Route definitions present but no CORS configuration in file.
        has_routes = bool(_ROUTE_DEFINITION_PATTERN.search(content))
        has_cors_config = bool(_CORS_CONFIG_PATTERN.search(content))
        if has_routes and not has_cors_config:
            # Find the first route line for reporting.
            for line_no, line in enumerate(lines, start=1):
                if _ROUTE_DEFINITION_PATTERN.search(line):
                    if self._has_nosec(line, "CORS-002"):
                        break
                    violations.append(
                        ScanViolation(
                            code="CORS-002",
                            severity="info",
                            category="cors",
                            file_path=file_path,
                            line=line_no,
                            message="File defines route handlers but has no CORS configuration. Suggestion: Add CORS middleware or headers to control cross-origin access",
                        )
                    )
                    break

        # CORS-003: Credentials with wildcard origin.
        if has_wildcard_origin:
            for line_no, line in enumerate(lines, start=1):
                if _CORS_CREDENTIALS_WITH_WILDCARD_PATTERN.search(line):
                    if self._has_nosec(line, "CORS-003"):
                        continue
                    violations.append(
                        ScanViolation(
                            code="CORS-003",
                            severity="error",
                            category="cors",
                            file_path=file_path,
                            line=line_no,
                            message="CORS allows credentials with wildcard origin, which is a security risk. Suggestion: When allow_credentials=True, specify explicit origins instead of '*'",
                        )
                    )

        return violations

    # ------------------------------------------------------------------ #
    # Secret detection checks (SEC-SECRET-001..012)
    # ------------------------------------------------------------------ #

    def _check_secrets(
        self, content: str, lines: list[str], file_path: str
    ) -> list[ScanViolation]:
        violations: list[ScanViolation] = []

        for code, pattern, message, suggestion in _SECRET_CHECKS:
            for line_no, line in enumerate(lines, start=1):
                if pattern.search(line):
                    if self._has_nosec(line, code):
                        continue
                    violations.append(
                        ScanViolation(
                            code=code,
                            severity="error",
                            category="secret_detection",
                            file_path=file_path,
                            line=line_no,
                            message=f"{message}. Suggestion: {suggestion}",
                        )
                    )

        return violations

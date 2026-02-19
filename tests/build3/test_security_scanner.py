"""Tests for SecurityScanner (TEST-023).

Covers JWT security (SEC-001..006), CORS (CORS-001..003),
secret detection (SEC-SECRET-001..012), nosec suppression,
directory exclusion, and edge cases (empty/missing directories).
"""

from __future__ import annotations

import pytest
from pathlib import Path

from src.quality_gate.security_scanner import SecurityScanner, MAX_VIOLATIONS_PER_CATEGORY


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def scanner() -> SecurityScanner:
    """Create a fresh SecurityScanner instance."""
    return SecurityScanner()


@pytest.fixture
def source_dir(tmp_path: Path) -> Path:
    """Provide a temporary directory to act as the scan target."""
    return tmp_path


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _scan_file(
    scanner: SecurityScanner,
    tmp_path: Path,
    filename: str,
    content: str,
) -> list:
    """Write *content* to *filename* inside *tmp_path* and run the scanner."""
    f = tmp_path / filename
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(content, encoding="utf-8")
    return await scanner.scan(tmp_path)


def _codes(violations: list) -> list[str]:
    """Extract just the violation codes from a list of ScanViolation objects."""
    return [v.code for v in violations]


# ===================================================================
# SEC-001: Route without auth decorator
# ===================================================================


class TestSEC001:
    """SEC-001 -- route handler missing authentication decorator."""

    async def test_route_without_auth_decorator_detected(
        self, scanner: SecurityScanner, source_dir: Path
    ) -> None:
        """1. A bare route definition without any auth decorator is flagged."""
        content = """\
from fastapi import FastAPI
app = FastAPI()

@app.get("/users")
def list_users():
    return []
"""
        violations = await _scan_file(scanner, source_dir, "app.py", content)
        sec001 = [v for v in violations if v.code == "SEC-001"]
        assert len(sec001) == 1
        assert sec001[0].category == "jwt_security"
        assert sec001[0].severity == "warning"

    async def test_route_with_auth_decorator_not_flagged(
        self, scanner: SecurityScanner, source_dir: Path
    ) -> None:
        """2. A route preceded by @login_required within 5 lines is NOT flagged."""
        content = """\
from fastapi import FastAPI
app = FastAPI()

@login_required
@app.get("/users")
def list_users():
    return []
"""
        violations = await _scan_file(scanner, source_dir, "app.py", content)
        sec001 = [v for v in violations if v.code == "SEC-001"]
        assert len(sec001) == 0

    async def test_route_with_depends_auth_not_flagged(
        self, scanner: SecurityScanner, source_dir: Path
    ) -> None:
        """2b. A route with Depends(get_current_user) in context is NOT flagged."""
        content = """\
from fastapi import FastAPI, Depends
app = FastAPI()

# Auth dependency
Depends(get_current_user)
@app.post("/items")
def create_item():
    pass
"""
        violations = await _scan_file(scanner, source_dir, "app.py", content)
        sec001 = [v for v in violations if v.code == "SEC-001"]
        assert len(sec001) == 0


# ===================================================================
# SEC-002: Hardcoded JWT secret
# ===================================================================


class TestSEC002:
    """SEC-002 -- hardcoded JWT secret."""

    async def test_hardcoded_jwt_secret_keyword_arg(
        self, scanner: SecurityScanner, source_dir: Path
    ) -> None:
        """3. jwt.encode with key='literal' is flagged."""
        content = """\
import jwt
token = jwt.encode(payload, key="my-super-secret-key", algorithm="RS256")
"""
        violations = await _scan_file(scanner, source_dir, "auth.py", content)
        sec002 = [v for v in violations if v.code == "SEC-002"]
        assert len(sec002) >= 1
        assert sec002[0].severity == "error"
        assert sec002[0].category == "jwt_security"

    async def test_hardcoded_jwt_secret_positional(
        self, scanner: SecurityScanner, source_dir: Path
    ) -> None:
        """3b. jwt.encode(payload, 'literal-secret') positional form is flagged."""
        content = """\
import jwt
token = jwt.encode(payload, "SuperSecretKey123", algorithm="RS256")
"""
        violations = await _scan_file(scanner, source_dir, "auth.py", content)
        sec002 = [v for v in violations if v.code == "SEC-002"]
        assert len(sec002) >= 1


# ===================================================================
# SEC-003: JWT encode without exp claim
# ===================================================================


class TestSEC003:
    """SEC-003 -- JWT creation without expiry."""

    async def test_jwt_encode_without_exp(
        self, scanner: SecurityScanner, source_dir: Path
    ) -> None:
        """4. jwt.encode() with no 'exp' in surrounding context is flagged."""
        content = """\
import jwt
payload = {"sub": "user123"}
token = jwt.encode(payload, secret, algorithm="RS256")
"""
        violations = await _scan_file(scanner, source_dir, "token.py", content)
        sec003 = [v for v in violations if v.code == "SEC-003"]
        assert len(sec003) == 1
        assert sec003[0].severity == "error"
        assert sec003[0].category == "jwt_security"

    async def test_jwt_encode_with_exp_not_flagged(
        self, scanner: SecurityScanner, source_dir: Path
    ) -> None:
        """5. jwt.encode() with 'exp' in the payload dict is NOT flagged."""
        content = """\
import jwt
import datetime
payload = {
    "sub": "user123",
    "exp": datetime.datetime.utcnow() + datetime.timedelta(hours=1),
}
token = jwt.encode(payload, secret, algorithm="RS256")
"""
        violations = await _scan_file(scanner, source_dir, "token.py", content)
        sec003 = [v for v in violations if v.code == "SEC-003"]
        assert len(sec003) == 0


# ===================================================================
# SEC-004: Weak algorithm
# ===================================================================


class TestSEC004:
    """SEC-004 -- weak JWT signing algorithm (HS256 or 'none')."""

    async def test_weak_algorithm_hs256(
        self, scanner: SecurityScanner, source_dir: Path
    ) -> None:
        """6. algorithm='HS256' is flagged as weak."""
        content = """\
import jwt
token = jwt.encode(payload, secret, algorithm='HS256')
"""
        violations = await _scan_file(scanner, source_dir, "enc.py", content)
        sec004 = [v for v in violations if v.code == "SEC-004"]
        assert len(sec004) >= 1
        assert sec004[0].severity == "warning"
        assert sec004[0].category == "jwt_security"

    async def test_weak_algorithm_none(
        self, scanner: SecurityScanner, source_dir: Path
    ) -> None:
        """6b. algorithm='none' is flagged as weak."""
        content = """\
import jwt
token = jwt.encode(payload, "", algorithm='none')
"""
        violations = await _scan_file(scanner, source_dir, "enc.py", content)
        sec004 = [v for v in violations if v.code == "SEC-004"]
        assert len(sec004) >= 1


# ===================================================================
# SEC-005: JWT decode without audience
# ===================================================================


class TestSEC005:
    """SEC-005 -- JWT decode missing audience validation."""

    async def test_decode_without_audience(
        self, scanner: SecurityScanner, source_dir: Path
    ) -> None:
        """7. jwt.decode() without audience= is flagged."""
        content = """\
import jwt
data = jwt.decode(token, secret, algorithms=["RS256"])
"""
        violations = await _scan_file(scanner, source_dir, "verify.py", content)
        sec005 = [v for v in violations if v.code == "SEC-005"]
        assert len(sec005) == 1
        assert sec005[0].severity == "warning"
        assert sec005[0].category == "jwt_security"

    async def test_decode_with_audience_not_flagged(
        self, scanner: SecurityScanner, source_dir: Path
    ) -> None:
        """7b. jwt.decode() with audience= in context is NOT flagged."""
        content = """\
import jwt
data = jwt.decode(
    token,
    secret,
    algorithms=["RS256"],
    audience="my-app",
)
"""
        violations = await _scan_file(scanner, source_dir, "verify.py", content)
        sec005 = [v for v in violations if v.code == "SEC-005"]
        assert len(sec005) == 0


# ===================================================================
# SEC-006: JWT decode without issuer
# ===================================================================


class TestSEC006:
    """SEC-006 -- JWT decode missing issuer validation."""

    async def test_decode_without_issuer(
        self, scanner: SecurityScanner, source_dir: Path
    ) -> None:
        """8. jwt.decode() without issuer= is flagged."""
        content = """\
import jwt
data = jwt.decode(token, secret, algorithms=["RS256"])
"""
        violations = await _scan_file(scanner, source_dir, "verify.py", content)
        sec006 = [v for v in violations if v.code == "SEC-006"]
        assert len(sec006) == 1
        assert sec006[0].severity == "warning"
        assert sec006[0].category == "jwt_security"

    async def test_decode_with_issuer_not_flagged(
        self, scanner: SecurityScanner, source_dir: Path
    ) -> None:
        """8b. jwt.decode() with issuer= in context is NOT flagged."""
        content = """\
import jwt
data = jwt.decode(
    token,
    secret,
    algorithms=["RS256"],
    issuer="https://auth.example.com",
)
"""
        violations = await _scan_file(scanner, source_dir, "verify.py", content)
        sec006 = [v for v in violations if v.code == "SEC-006"]
        assert len(sec006) == 0


# ===================================================================
# CORS-001: Wildcard origin
# ===================================================================


class TestCORS001:
    """CORS-001 -- wildcard origin detected."""

    async def test_wildcard_origin_allow_origins(
        self, scanner: SecurityScanner, source_dir: Path
    ) -> None:
        """9. allow_origins=['*'] is flagged."""
        content = """\
from fastapi.middleware.cors import CORSMiddleware
app.add_middleware(CORSMiddleware, allow_origins=["*"])
"""
        violations = await _scan_file(scanner, source_dir, "main.py", content)
        cors001 = [v for v in violations if v.code == "CORS-001"]
        assert len(cors001) == 1
        assert cors001[0].category == "cors"
        assert cors001[0].severity == "warning"

    async def test_wildcard_origin_header(
        self, scanner: SecurityScanner, source_dir: Path
    ) -> None:
        """9b. Access-Control-Allow-Origin: * is flagged."""
        content = """\
Access-Control-Allow-Origin: *
"""
        violations = await _scan_file(scanner, source_dir, "server.py", content)
        cors001 = [v for v in violations if v.code == "CORS-001"]
        assert len(cors001) >= 1


# ===================================================================
# CORS-002: Routes without CORS config
# ===================================================================


class TestCORS002:
    """CORS-002 -- routes present but no CORS configuration."""

    async def test_routes_without_cors_config(
        self, scanner: SecurityScanner, source_dir: Path
    ) -> None:
        """10. A file with route definitions but no CORS setup is flagged."""
        content = """\
from fastapi import FastAPI
app = FastAPI()

@app.get("/items")
def list_items():
    return []

@app.post("/items")
def create_item():
    pass
"""
        violations = await _scan_file(scanner, source_dir, "api.py", content)
        cors002 = [v for v in violations if v.code == "CORS-002"]
        assert len(cors002) == 1
        assert cors002[0].category == "cors"
        assert cors002[0].severity == "info"

    async def test_routes_with_cors_config_not_flagged(
        self, scanner: SecurityScanner, source_dir: Path
    ) -> None:
        """10b. A file with routes AND CORSMiddleware is NOT flagged."""
        content = """\
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=[os.environ.get("CORS_ORIGIN", "")])

@app.get("/items")
def list_items():
    return []
"""
        violations = await _scan_file(scanner, source_dir, "api.py", content)
        cors002 = [v for v in violations if v.code == "CORS-002"]
        assert len(cors002) == 0


# ===================================================================
# CORS-003: Credentials with wildcard
# ===================================================================


class TestCORS003:
    """CORS-003 -- allow_credentials=True combined with wildcard origin."""

    async def test_credentials_with_wildcard(
        self, scanner: SecurityScanner, source_dir: Path
    ) -> None:
        """11. allow_credentials=True when wildcard origin is present is flagged."""
        content = """\
from fastapi.middleware.cors import CORSMiddleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
)
"""
        violations = await _scan_file(scanner, source_dir, "cors.py", content)
        cors003 = [v for v in violations if v.code == "CORS-003"]
        assert len(cors003) == 1
        assert cors003[0].severity == "error"
        assert cors003[0].category == "cors"

    async def test_credentials_without_wildcard_not_flagged(
        self, scanner: SecurityScanner, source_dir: Path
    ) -> None:
        """11b. allow_credentials=True without wildcard origin is NOT flagged as CORS-003."""
        content = """\
from fastapi.middleware.cors import CORSMiddleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=[os.environ.get("CORS_ORIGIN", "")],
    allow_credentials=True,
)
"""
        violations = await _scan_file(scanner, source_dir, "cors.py", content)
        cors003 = [v for v in violations if v.code == "CORS-003"]
        assert len(cors003) == 0


# ===================================================================
# SEC-SECRET-001: API key in source
# ===================================================================


class TestSECSECRET001:
    """SEC-SECRET-001 -- API key detected in source."""

    async def test_api_key_in_source(
        self, scanner: SecurityScanner, source_dir: Path
    ) -> None:
        """12. Hardcoded api_key = 'value' is flagged."""
        content = """\
api_key = "sk_live_abcdef1234567890"
"""
        violations = await _scan_file(scanner, source_dir, "config.py", content)
        sec_secret_001 = [v for v in violations if v.code == "SEC-SECRET-001"]
        assert len(sec_secret_001) >= 1
        assert sec_secret_001[0].category == "secret_detection"
        assert sec_secret_001[0].severity == "error"


# ===================================================================
# SEC-SECRET-002: Password in source
# ===================================================================


class TestSECSECRET002:
    """SEC-SECRET-002 -- password in source."""

    async def test_password_in_source(
        self, scanner: SecurityScanner, source_dir: Path
    ) -> None:
        """13. Hardcoded password = 'value' is flagged."""
        content = """\
password = "SuperSecret123!"
"""
        violations = await _scan_file(scanner, source_dir, "db.py", content)
        sec_secret_002 = [v for v in violations if v.code == "SEC-SECRET-002"]
        assert len(sec_secret_002) >= 1
        assert sec_secret_002[0].category == "secret_detection"


# ===================================================================
# SEC-SECRET-003: Private key block
# ===================================================================


class TestSECSECRET003:
    """SEC-SECRET-003 -- private key block in source."""

    async def test_private_key_block(
        self, scanner: SecurityScanner, source_dir: Path
    ) -> None:
        """14. -----BEGIN RSA PRIVATE KEY----- is flagged."""
        content = """\
key = \"\"\"
-----BEGIN RSA PRIVATE KEY-----
MIIBogIBAAJBALRiMLAHudeSA/x3hB2f+2NRkJLA...
-----END RSA PRIVATE KEY-----
\"\"\"
"""
        violations = await _scan_file(scanner, source_dir, "keys.py", content)
        sec_secret_003 = [v for v in violations if v.code == "SEC-SECRET-003"]
        assert len(sec_secret_003) >= 1
        assert sec_secret_003[0].category == "secret_detection"

    async def test_plain_private_key_block(
        self, scanner: SecurityScanner, source_dir: Path
    ) -> None:
        """14b. -----BEGIN PRIVATE KEY----- (non-RSA) is also flagged."""
        content = """\
-----BEGIN PRIVATE KEY-----
MIIEvgIBADANBgkqhkiG9w0BAQEFAASC...
-----END PRIVATE KEY-----
"""
        violations = await _scan_file(scanner, source_dir, "cert.py", content)
        sec_secret_003 = [v for v in violations if v.code == "SEC-SECRET-003"]
        assert len(sec_secret_003) >= 1


# ===================================================================
# SEC-SECRET-004: AWS credentials
# ===================================================================


class TestSECSECRET004:
    """SEC-SECRET-004 -- AWS credentials in source."""

    async def test_aws_access_key_id(
        self, scanner: SecurityScanner, source_dir: Path
    ) -> None:
        """15. An AKIA... key ID pattern is flagged."""
        content = """\
AWS_ACCESS_KEY_ID = "AKIAIOSFODNN7EXAMPLE"
"""
        violations = await _scan_file(scanner, source_dir, "aws.py", content)
        sec_secret_004 = [v for v in violations if v.code == "SEC-SECRET-004"]
        assert len(sec_secret_004) >= 1
        assert sec_secret_004[0].category == "secret_detection"

    async def test_aws_secret_access_key(
        self, scanner: SecurityScanner, source_dir: Path
    ) -> None:
        """15b. aws_secret_access_key = 'value' is flagged."""
        content = """\
aws_secret_access_key = "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"
"""
        violations = await _scan_file(scanner, source_dir, "aws.py", content)
        sec_secret_004 = [v for v in violations if v.code == "SEC-SECRET-004"]
        assert len(sec_secret_004) >= 1


# ===================================================================
# SEC-SECRET-005: Database connection string
# ===================================================================


class TestSECSECRET005:
    """SEC-SECRET-005 -- database connection string with credentials."""

    async def test_db_connection_string(
        self, scanner: SecurityScanner, source_dir: Path
    ) -> None:
        """16. A postgresql://creds@host connection string is flagged."""
        content = """\
DATABASE_URL = "postgresql://admin:secretpass@contract-engine:5432/mydb"
"""
        violations = await _scan_file(scanner, source_dir, "db.py", content)
        sec_secret_005 = [v for v in violations if v.code == "SEC-SECRET-005"]
        assert len(sec_secret_005) >= 1
        assert sec_secret_005[0].category == "secret_detection"

    async def test_mysql_connection_string(
        self, scanner: SecurityScanner, source_dir: Path
    ) -> None:
        """16b. A mysql://creds@host connection string is also flagged."""
        content = """\
DB_URL = "mysql://root:password123@architect:3306/app"
"""
        violations = await _scan_file(scanner, source_dir, "db.py", content)
        sec_secret_005 = [v for v in violations if v.code == "SEC-SECRET-005"]
        assert len(sec_secret_005) >= 1


# ===================================================================
# SEC-SECRET-006: JWT secret in source
# ===================================================================


class TestSECSECRET006:
    """SEC-SECRET-006 -- JWT secret value hardcoded."""

    async def test_jwt_secret_in_source(
        self, scanner: SecurityScanner, source_dir: Path
    ) -> None:
        """17. JWT_SECRET = 'value' is flagged."""
        content = """\
JWT_SECRET = "my-jwt-secret-value-that-is-long"
"""
        violations = await _scan_file(scanner, source_dir, "settings.py", content)
        sec_secret_006 = [v for v in violations if v.code == "SEC-SECRET-006"]
        assert len(sec_secret_006) >= 1
        assert sec_secret_006[0].category == "secret_detection"

    async def test_jwt_secret_key_in_source(
        self, scanner: SecurityScanner, source_dir: Path
    ) -> None:
        """17b. jwt_secret_key = 'value' variant is also flagged."""
        content = """\
jwt_secret_key = "another-jwt-secret-here"
"""
        violations = await _scan_file(scanner, source_dir, "settings.py", content)
        sec_secret_006 = [v for v in violations if v.code == "SEC-SECRET-006"]
        assert len(sec_secret_006) >= 1


# ===================================================================
# Nosec suppression
# ===================================================================


class TestNosecSuppression:
    """Nosec / noqa inline suppression for violations."""

    async def test_hash_nosec_suppresses_violation(
        self, scanner: SecurityScanner, source_dir: Path
    ) -> None:
        """18. '# nosec' at end of line suppresses the violation."""
        content = """\
password = "SuperSecret123!"  # nosec
"""
        violations = await _scan_file(scanner, source_dir, "config.py", content)
        sec_secret_002 = [v for v in violations if v.code == "SEC-SECRET-002"]
        assert len(sec_secret_002) == 0

    async def test_slash_nosec_suppresses_violation(
        self, scanner: SecurityScanner, source_dir: Path
    ) -> None:
        """19. '// nosec' at end of line suppresses the violation (JS-style comment)."""
        content = """\
const password = "SuperSecret123!"; // nosec
"""
        violations = await _scan_file(scanner, source_dir, "config.js", content)
        sec_secret_002 = [v for v in violations if v.code == "SEC-SECRET-002"]
        assert len(sec_secret_002) == 0

    async def test_noqa_specific_code_suppresses_only_that_code(
        self, scanner: SecurityScanner, source_dir: Path
    ) -> None:
        """20. '# noqa: SEC-SECRET-001' suppresses SEC-SECRET-001 but not other codes."""
        # This line matches both SEC-SECRET-001 (api_key) and SEC-SECRET-002 (password).
        content = """\
api_key = "sk_live_abcdef1234567890"  # noqa: SEC-SECRET-001
password = "SuperSecret123!"
"""
        violations = await _scan_file(scanner, source_dir, "config.py", content)
        # SEC-SECRET-001 should be suppressed
        sec_secret_001 = [v for v in violations if v.code == "SEC-SECRET-001"]
        assert len(sec_secret_001) == 0
        # SEC-SECRET-002 should still be present (on a different line, no suppression)
        sec_secret_002 = [v for v in violations if v.code == "SEC-SECRET-002"]
        assert len(sec_secret_002) >= 1

    async def test_noqa_wrong_code_does_not_suppress(
        self, scanner: SecurityScanner, source_dir: Path
    ) -> None:
        """20b. '# noqa: CORS-001' does NOT suppress SEC-SECRET-002."""
        content = """\
password = "SuperSecret123!"  # noqa: CORS-001
"""
        violations = await _scan_file(scanner, source_dir, "config.py", content)
        sec_secret_002 = [v for v in violations if v.code == "SEC-SECRET-002"]
        assert len(sec_secret_002) >= 1

    async def test_nosec_suppresses_jwt_sec001(
        self, scanner: SecurityScanner, source_dir: Path
    ) -> None:
        """18b. '# nosec' suppresses SEC-001 on a route line."""
        content = """\
from fastapi import FastAPI
app = FastAPI()

@app.get("/public")  # nosec
def public_endpoint():
    return {"status": "ok"}
"""
        violations = await _scan_file(scanner, source_dir, "app.py", content)
        sec001 = [v for v in violations if v.code == "SEC-001"]
        assert len(sec001) == 0


# ===================================================================
# Directory exclusion
# ===================================================================


class TestDirectoryExclusion:
    """Files in excluded directories should be skipped entirely."""

    async def test_node_modules_skipped(
        self, scanner: SecurityScanner, source_dir: Path
    ) -> None:
        """21. Files under node_modules/ are not scanned."""
        nm_dir = source_dir / "node_modules" / "some-pkg"
        nm_dir.mkdir(parents=True)
        secret_file = nm_dir / "config.js"
        secret_file.write_text(
            'const password = "SuperSecret123!";\n', encoding="utf-8"
        )
        violations = await scanner.scan(source_dir)
        sec_secret_002 = [v for v in violations if v.code == "SEC-SECRET-002"]
        assert len(sec_secret_002) == 0

    async def test_venv_skipped(
        self, scanner: SecurityScanner, source_dir: Path
    ) -> None:
        """22. Files under .venv/ are not scanned."""
        venv_dir = source_dir / ".venv" / "lib"
        venv_dir.mkdir(parents=True)
        secret_file = venv_dir / "settings.py"
        secret_file.write_text(
            'password = "SuperSecret123!"\n', encoding="utf-8"
        )
        violations = await scanner.scan(source_dir)
        sec_secret_002 = [v for v in violations if v.code == "SEC-SECRET-002"]
        assert len(sec_secret_002) == 0

    async def test_pycache_skipped(
        self, scanner: SecurityScanner, source_dir: Path
    ) -> None:
        """22b. Files under __pycache__/ are not scanned."""
        cache_dir = source_dir / "__pycache__"
        cache_dir.mkdir(parents=True)
        secret_file = cache_dir / "module.py"
        secret_file.write_text(
            'password = "SuperSecret123!"\n', encoding="utf-8"
        )
        violations = await scanner.scan(source_dir)
        sec_secret_002 = [v for v in violations if v.code == "SEC-SECRET-002"]
        assert len(sec_secret_002) == 0


# ===================================================================
# Edge cases: empty and non-existent directories
# ===================================================================


class TestEdgeCases:
    """Edge cases for empty or missing scan targets."""

    async def test_empty_directory_returns_no_violations(
        self, scanner: SecurityScanner, source_dir: Path
    ) -> None:
        """23. An empty directory produces zero violations."""
        violations = await scanner.scan(source_dir)
        assert violations == []

    async def test_nonexistent_directory_returns_no_violations(
        self, scanner: SecurityScanner, source_dir: Path
    ) -> None:
        """24. A non-existent directory produces zero violations."""
        fake_dir = source_dir / "does_not_exist"
        violations = await scanner.scan(fake_dir)
        assert violations == []

    async def test_unscannable_extension_ignored(
        self, scanner: SecurityScanner, source_dir: Path
    ) -> None:
        """24b. Files with non-scannable extensions (e.g. .png) are ignored."""
        img = source_dir / "image.png"
        img.write_text('password = "SuperSecret123!"', encoding="utf-8")
        violations = await scanner.scan(source_dir)
        assert violations == []

    async def test_multiple_violations_in_single_file(
        self, scanner: SecurityScanner, source_dir: Path
    ) -> None:
        """24c. Multiple different violation types can be found in one file."""
        content = """\
from fastapi import FastAPI
app = FastAPI()

password = "MyPassword123!"
api_key = "sk_live_abcdef1234567890"

@app.get("/items")
def list_items():
    return []
"""
        violations = await _scan_file(scanner, source_dir, "multi.py", content)
        codes = _codes(violations)
        # Should detect at least password, api_key, route without auth, route without cors
        assert "SEC-SECRET-001" in codes
        assert "SEC-SECRET-002" in codes
        assert "SEC-001" in codes

    async def test_violation_has_correct_file_path(
        self, scanner: SecurityScanner, source_dir: Path
    ) -> None:
        """24d. Violations report the correct file path."""
        content = """\
password = "SuperSecret123!"
"""
        f = source_dir / "app.py"
        f.write_text(content, encoding="utf-8")
        violations = await scanner.scan(source_dir)
        assert len(violations) >= 1
        assert str(f) in violations[0].file_path

    async def test_violation_has_correct_line_number(
        self, scanner: SecurityScanner, source_dir: Path
    ) -> None:
        """24e. Violations report the correct line number."""
        content = """\
# line 1
# line 2
password = "SuperSecret123!"
"""
        violations = await _scan_file(scanner, source_dir, "app.py", content)
        sec_secret_002 = [v for v in violations if v.code == "SEC-SECRET-002"]
        assert len(sec_secret_002) >= 1
        assert sec_secret_002[0].line == 3


# ===================================================================
# Per-category cap
# ===================================================================


class TestPerCategoryCap:
    """MAX_VIOLATIONS_PER_CATEGORY is enforced per category."""

    async def test_violations_capped_per_category(
        self, scanner: SecurityScanner, source_dir: Path
    ) -> None:
        """Violations beyond the per-category cap are dropped."""
        # Generate more than MAX_VIOLATIONS_PER_CATEGORY password lines
        lines = []
        for i in range(MAX_VIOLATIONS_PER_CATEGORY + 50):
            lines.append(f'password_{i} = "Secret{i}Value!"')
        content = "\n".join(lines)

        violations = await _scan_file(scanner, source_dir, "overflow.py", content)
        secret_violations = [
            v for v in violations if v.category == "secret_detection"
        ]
        assert len(secret_violations) <= MAX_VIOLATIONS_PER_CATEGORY


# ===================================================================
# Additional secret detection patterns (SEC-SECRET-007..012)
# ===================================================================


class TestAdditionalSecrets:
    """SEC-SECRET-007 through SEC-SECRET-012."""

    async def test_sec_secret_007_oauth_client_secret(
        self, scanner: SecurityScanner, source_dir: Path
    ) -> None:
        """SEC-SECRET-007: OAuth client_secret in source is flagged."""
        content = """\
client_secret = "oauth-secret-value-here-long"
"""
        violations = await _scan_file(scanner, source_dir, "oauth.py", content)
        hits = [v for v in violations if v.code == "SEC-SECRET-007"]
        assert len(hits) >= 1
        assert hits[0].category == "secret_detection"

    async def test_sec_secret_008_encryption_key(
        self, scanner: SecurityScanner, source_dir: Path
    ) -> None:
        """SEC-SECRET-008: encryption_key in source is flagged."""
        content = """\
encryption_key = "aes256-key-value-long-enough"
"""
        violations = await _scan_file(scanner, source_dir, "crypto.py", content)
        hits = [v for v in violations if v.code == "SEC-SECRET-008"]
        assert len(hits) >= 1

    async def test_sec_secret_009_token_in_source(
        self, scanner: SecurityScanner, source_dir: Path
    ) -> None:
        """SEC-SECRET-009: Long token value in source is flagged."""
        content = """\
access_token = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9abcdefghijk"
"""
        violations = await _scan_file(scanner, source_dir, "token.py", content)
        hits = [v for v in violations if v.code == "SEC-SECRET-009"]
        assert len(hits) >= 1

    async def test_sec_secret_010_certificate_key(
        self, scanner: SecurityScanner, source_dir: Path
    ) -> None:
        """SEC-SECRET-010: Certificate / EC private key block is flagged."""
        content = """\
-----BEGIN EC PRIVATE KEY-----
MHQCAQEEIODv...
-----END EC PRIVATE KEY-----
"""
        violations = await _scan_file(scanner, source_dir, "cert.py", content)
        hits = [v for v in violations if v.code == "SEC-SECRET-010"]
        assert len(hits) >= 1

    async def test_sec_secret_011_service_account(
        self, scanner: SecurityScanner, source_dir: Path
    ) -> None:
        """SEC-SECRET-011: GCP service account key content is flagged."""
        content = """\
{
  "type": "service_account",
  "project_id": "my-project"
}
"""
        violations = await _scan_file(scanner, source_dir, "sa.json", content)
        hits = [v for v in violations if v.code == "SEC-SECRET-011"]
        assert len(hits) >= 1

    async def test_sec_secret_012_webhook_secret(
        self, scanner: SecurityScanner, source_dir: Path
    ) -> None:
        """SEC-SECRET-012: webhook_secret in source is flagged."""
        content = """\
webhook_secret = "whsec_abcdefghijklmnop"
"""
        violations = await _scan_file(scanner, source_dir, "webhooks.py", content)
        hits = [v for v in violations if v.code == "SEC-SECRET-012"]
        assert len(hits) >= 1


# ===================================================================
# Category classification
# ===================================================================


class TestCategoryClassification:
    """Verify that each violation type uses the correct category string."""

    async def test_jwt_violations_use_jwt_security_category(
        self, scanner: SecurityScanner, source_dir: Path
    ) -> None:
        """All SEC-00x violations should have category='jwt_security'."""
        content = """\
import jwt
@app.get("/users")
def users():
    pass
"""
        violations = await _scan_file(scanner, source_dir, "app.py", content)
        sec_violations = [v for v in violations if v.code.startswith("SEC-00")]
        for v in sec_violations:
            assert v.category == "jwt_security", f"{v.code} has wrong category: {v.category}"

    async def test_cors_violations_use_cors_category(
        self, scanner: SecurityScanner, source_dir: Path
    ) -> None:
        """All CORS-00x violations should have category='cors'."""
        content = """\
app.add_middleware(CORSMiddleware, allow_origins=["*"])
allow_credentials = True
"""
        violations = await _scan_file(scanner, source_dir, "app.py", content)
        cors_violations = [v for v in violations if v.code.startswith("CORS-")]
        for v in cors_violations:
            assert v.category == "cors", f"{v.code} has wrong category: {v.category}"

    async def test_secret_violations_use_secret_detection_category(
        self, scanner: SecurityScanner, source_dir: Path
    ) -> None:
        """All SEC-SECRET-xxx violations should have category='secret_detection'."""
        content = """\
password = "SuperSecret123!"
api_key = "sk_live_abcdef1234567890"
"""
        violations = await _scan_file(scanner, source_dir, "conf.py", content)
        secret_violations = [
            v for v in violations if v.code.startswith("SEC-SECRET-")
        ]
        for v in secret_violations:
            assert v.category == "secret_detection", (
                f"{v.code} has wrong category: {v.category}"
            )

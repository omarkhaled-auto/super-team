"""Shared constants for Build 3 pipeline."""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Phase names
# ---------------------------------------------------------------------------
PHASE_ARCHITECT = "architect"
PHASE_ARCHITECT_REVIEW = "architect_review"
PHASE_CONTRACT_REGISTRATION = "contract_registration"
PHASE_BUILDERS = "builders"
PHASE_INTEGRATION = "integration"
PHASE_QUALITY_GATE = "quality_gate"
PHASE_FIX_PASS = "fix_pass"
PHASE_COMPLETE = "complete"
PHASE_FAILED = "failed"

ALL_PHASES = [
    PHASE_ARCHITECT,
    PHASE_ARCHITECT_REVIEW,
    PHASE_CONTRACT_REGISTRATION,
    PHASE_BUILDERS,
    PHASE_INTEGRATION,
    PHASE_QUALITY_GATE,
    PHASE_FIX_PASS,
]

# ---------------------------------------------------------------------------
# Phase timeouts (seconds)
# ---------------------------------------------------------------------------
PHASE_TIMEOUTS: dict[str, int] = {
    PHASE_ARCHITECT: 900,
    PHASE_ARCHITECT_REVIEW: 300,
    PHASE_CONTRACT_REGISTRATION: 180,
    PHASE_BUILDERS: 3600,
    PHASE_INTEGRATION: 600,
    PHASE_QUALITY_GATE: 600,
    PHASE_FIX_PASS: 900,
}

# ---------------------------------------------------------------------------
# Scan codes -- 40 codes across 8 categories
# ---------------------------------------------------------------------------

# JWT Security (6)
SECURITY_SCAN_CODES = [
    "SEC-001",  # Missing JWT validation
    "SEC-002",  # Hardcoded JWT secret
    "SEC-003",  # Missing token expiry
    "SEC-004",  # Weak signing algorithm
    "SEC-005",  # Missing audience validation
    "SEC-006",  # Missing issuer validation
]

# CORS (3)
CORS_SCAN_CODES = [
    "CORS-001",  # Wildcard origin
    "CORS-002",  # Missing CORS headers
    "CORS-003",  # Credentials with wildcard
]

# Secret Detection (12)
SECRET_SCAN_CODES = [
    "SEC-SECRET-001",  # API key in source
    "SEC-SECRET-002",  # Password in source
    "SEC-SECRET-003",  # Private key in source
    "SEC-SECRET-004",  # AWS credentials
    "SEC-SECRET-005",  # Database connection string
    "SEC-SECRET-006",  # JWT secret in source
    "SEC-SECRET-007",  # OAuth client secret
    "SEC-SECRET-008",  # Encryption key in source
    "SEC-SECRET-009",  # Token in source
    "SEC-SECRET-010",  # Certificate private key
    "SEC-SECRET-011",  # Service account key
    "SEC-SECRET-012",  # Webhook secret
]

# Logging (3)
LOGGING_SCAN_CODES = [
    "LOG-001",  # Missing structured logging
    "LOG-004",  # Sensitive data in logs
    "LOG-005",  # Missing request ID logging
]

# Trace Propagation (1)
TRACE_SCAN_CODES = [
    "TRACE-001",  # Missing trace context propagation
]

# Health Endpoints (1)
HEALTH_SCAN_CODES = [
    "HEALTH-001",  # Missing health endpoint
]

# Docker Security (8)
DOCKER_SCAN_CODES = [
    "DOCKER-001",  # Running as root
    "DOCKER-002",  # No health check
    "DOCKER-003",  # Using latest tag
    "DOCKER-004",  # Exposing unnecessary ports
    "DOCKER-005",  # Missing resource limits
    "DOCKER-006",  # Privileged container
    "DOCKER-007",  # Writable root filesystem
    "DOCKER-008",  # Missing security opts
]

# Adversarial (6)
ADVERSARIAL_SCAN_CODES = [
    "ADV-001",  # Dead event handlers
    "ADV-002",  # Dead contracts
    "ADV-003",  # Orphan services
    "ADV-004",  # Naming inconsistency
    "ADV-005",  # Missing error handling patterns
    "ADV-006",  # Potential race conditions
]

ALL_SCAN_CODES: list[str] = (
    SECURITY_SCAN_CODES
    + CORS_SCAN_CODES
    + SECRET_SCAN_CODES
    + LOGGING_SCAN_CODES
    + TRACE_SCAN_CODES
    + HEALTH_SCAN_CODES
    + DOCKER_SCAN_CODES
    + ADVERSARIAL_SCAN_CODES
)

assert len(ALL_SCAN_CODES) == 40, f"Expected 40 scan codes, got {len(ALL_SCAN_CODES)}"

# ---------------------------------------------------------------------------
# Builder defaults
# ---------------------------------------------------------------------------
DEFAULT_BUILDER_DEPTH = "thorough"
DEFAULT_MAX_CONCURRENT_BUILDERS = 3
DEFAULT_BUILDER_TIMEOUT = 1800  # 30 minutes

# ---------------------------------------------------------------------------
# State persistence
# ---------------------------------------------------------------------------
STATE_DIR = ".super-orchestrator"
STATE_FILE = "PIPELINE_STATE.json"

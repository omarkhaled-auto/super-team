"""Tests for shared constants values."""
from __future__ import annotations

from src.shared.constants import (
    ARCHITECT_PORT,
    ARCHITECT_SERVICE_NAME,
    CODEBASE_INTEL_PORT,
    CODEBASE_INTEL_SERVICE_NAME,
    CONTRACT_ENGINE_PORT,
    CONTRACT_ENGINE_SERVICE_NAME,
    DB_BUSY_TIMEOUT_MS,
    INTERNAL_PORT,
    SUPPORTED_CONTRACT_TYPES,
    SUPPORTED_LANGUAGES,
    VERSION,
)


class TestPortConstants:
    """Verify port numbers are correctly defined and non-overlapping."""

    def test_architect_port(self):
        assert ARCHITECT_PORT == 8001

    def test_contract_engine_port(self):
        assert CONTRACT_ENGINE_PORT == 8002

    def test_codebase_intel_port(self):
        assert CODEBASE_INTEL_PORT == 8003

    def test_internal_port(self):
        assert INTERNAL_PORT == 8000

    def test_ports_are_unique(self):
        ports = [ARCHITECT_PORT, CONTRACT_ENGINE_PORT, CODEBASE_INTEL_PORT, INTERNAL_PORT]
        assert len(ports) == len(set(ports)), "Service ports must be unique"

    def test_ports_are_positive_integers(self):
        for port in [ARCHITECT_PORT, CONTRACT_ENGINE_PORT, CODEBASE_INTEL_PORT, INTERNAL_PORT]:
            assert isinstance(port, int)
            assert port > 0


class TestServiceNames:
    """Verify service name constants."""

    def test_architect_service_name(self):
        assert ARCHITECT_SERVICE_NAME == "architect"

    def test_contract_engine_service_name(self):
        assert CONTRACT_ENGINE_SERVICE_NAME == "contract-engine"

    def test_codebase_intel_service_name(self):
        assert CODEBASE_INTEL_SERVICE_NAME == "codebase-intelligence"

    def test_service_names_are_kebab_case(self):
        for name in [ARCHITECT_SERVICE_NAME, CONTRACT_ENGINE_SERVICE_NAME, CODEBASE_INTEL_SERVICE_NAME]:
            assert name == name.lower(), f"Service name '{name}' should be lowercase"
            assert " " not in name, f"Service name '{name}' should not contain spaces"
            assert "_" not in name, f"Service name '{name}' should use hyphens, not underscores"


class TestDatabaseSettings:
    """Verify database configuration constants."""

    def test_busy_timeout_value(self):
        assert DB_BUSY_TIMEOUT_MS == 30000

    def test_busy_timeout_is_milliseconds(self):
        # 30 seconds = 30000 ms
        assert DB_BUSY_TIMEOUT_MS == 30 * 1000

    def test_busy_timeout_is_int(self):
        assert isinstance(DB_BUSY_TIMEOUT_MS, int)


class TestVersion:
    """Verify version constant."""

    def test_version_format(self):
        parts = VERSION.split(".")
        assert len(parts) == 3, "Version should be semver format X.Y.Z"
        for part in parts:
            assert part.isdigit(), f"Version part '{part}' should be numeric"

    def test_version_value(self):
        assert VERSION == "1.0.0"


class TestSupportedLanguages:
    """Verify supported languages list."""

    def test_contains_python(self):
        assert "python" in SUPPORTED_LANGUAGES

    def test_contains_typescript(self):
        assert "typescript" in SUPPORTED_LANGUAGES

    def test_contains_csharp(self):
        assert "csharp" in SUPPORTED_LANGUAGES

    def test_contains_go(self):
        assert "go" in SUPPORTED_LANGUAGES

    def test_exactly_four_languages(self):
        assert len(SUPPORTED_LANGUAGES) == 4

    def test_all_lowercase(self):
        for lang in SUPPORTED_LANGUAGES:
            assert lang == lang.lower()


class TestSupportedContractTypes:
    """Verify supported contract types list."""

    def test_contains_openapi(self):
        assert "openapi" in SUPPORTED_CONTRACT_TYPES

    def test_contains_asyncapi(self):
        assert "asyncapi" in SUPPORTED_CONTRACT_TYPES

    def test_contains_json_schema(self):
        assert "json_schema" in SUPPORTED_CONTRACT_TYPES

    def test_exactly_three_types(self):
        assert len(SUPPORTED_CONTRACT_TYPES) == 3

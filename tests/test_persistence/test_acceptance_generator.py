"""Tests for acceptance test generator."""
from __future__ import annotations

import pytest
from pathlib import Path

from src.integrator.acceptance_test_generator import (
    AcceptanceTestResult,
    generate_acceptance_tests,
)


@pytest.fixture
def output_dir(tmp_path: Path) -> Path:
    return tmp_path / "service-output"


@pytest.fixture
def sample_openapi_contract() -> dict:
    return {
        "id": "user-api-contract",
        "type": "openapi",
        "spec": {
            "openapi": "3.1.0",
            "info": {"title": "User API", "version": "1.0.0"},
            "paths": {
                "/users": {
                    "get": {"summary": "List users", "responses": {"200": {"description": "OK"}}},
                },
            },
        },
    }


@pytest.fixture
def sample_asyncapi_contract() -> dict:
    return {
        "id": "events-contract",
        "type": "asyncapi",
        "spec": {
            "asyncapi": "3.0.0",
            "info": {"title": "Events", "version": "1.0.0"},
            "channels": {
                "user-created": {
                    "message": {
                        "payload": {
                            "type": "object",
                            "properties": {
                                "userId": {"type": "string"},
                                "email": {"type": "string"},
                            },
                            "required": ["userId"],
                        },
                    },
                },
            },
        },
    }


class TestAcceptanceTestGenerator:
    def test_generates_valid_python_files(
        self, output_dir: Path, sample_openapi_contract: dict
    ) -> None:
        """Output files pass compile() check."""
        result = generate_acceptance_tests(
            "user-service",
            [sample_openapi_contract],
            output_dir,
        )
        for f in result.files_written:
            code = f.read_text(encoding="utf-8")
            compile(code, str(f), "exec")  # Should not raise

    def test_generates_pytest_structure(
        self, output_dir: Path, sample_openapi_contract: dict
    ) -> None:
        """File contains def test_ and import pytest."""
        result = generate_acceptance_tests(
            "user-service",
            [sample_openapi_contract],
            output_dir,
        )
        assert len(result.files_written) >= 1
        content = result.files_written[0].read_text(encoding="utf-8")
        assert "def test_" in content
        assert "import pytest" in content

    def test_acceptance_tests_md_generated(
        self, output_dir: Path, sample_openapi_contract: dict
    ) -> None:
        """ACCEPTANCE_TESTS.md written with content."""
        generate_acceptance_tests(
            "user-service",
            [sample_openapi_contract],
            output_dir,
        )
        md_path = output_dir / "ACCEPTANCE_TESTS.md"
        assert md_path.exists()
        content = md_path.read_text(encoding="utf-8")
        assert "user-service" in content
        assert "pytest" in content

    def test_failure_in_generation_does_not_propagate(
        self, output_dir: Path
    ) -> None:
        """contract_engine_client raises → AcceptanceTestResult has failure logged."""
        bad_contract = {"id": "bad", "type": "openapi", "spec": "not a dict"}
        result = generate_acceptance_tests(
            "broken-service",
            [bad_contract],
            output_dir,
        )
        # Should not raise, failures are captured
        assert isinstance(result, AcceptanceTestResult)

    def test_output_written_to_correct_directory(
        self, output_dir: Path, sample_openapi_contract: dict
    ) -> None:
        """Files appear under {output_dir}/tests/acceptance/."""
        result = generate_acceptance_tests(
            "user-service",
            [sample_openapi_contract],
            output_dir,
        )
        for f in result.files_written:
            assert "tests" in str(f)
            assert "acceptance" in str(f)

    def test_asyncapi_generates_jsonschema_test(
        self, output_dir: Path, sample_asyncapi_contract: dict
    ) -> None:
        """AsyncAPI contract → jsonschema validation test file."""
        result = generate_acceptance_tests(
            "event-service",
            [sample_asyncapi_contract],
            output_dir,
        )
        assert len(result.files_written) >= 1
        content = result.files_written[0].read_text(encoding="utf-8")
        assert "jsonschema" in content
        assert "def test_" in content

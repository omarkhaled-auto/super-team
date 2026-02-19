"""Test fixtures for E2E integration testing.

Provides realistic sample data files for pipeline testing:
- sample_prd.md — 3-service e-commerce PRD
- sample_openapi.yaml — OpenAPI 3.1 spec for order-service
- sample_pact.json — Pact V4 contract (notification ↔ order)
- sample_docker_compose.yml — Docker Compose for test services
"""

from __future__ import annotations

import json
from pathlib import Path

FIXTURES_DIR = Path(__file__).parent


def fixture_path(name: str) -> Path:
    """Return the absolute path to a named fixture file."""
    path = FIXTURES_DIR / name
    if not path.exists():
        raise FileNotFoundError(f"Fixture not found: {path}")
    return path


def load_prd() -> str:
    """Load the sample PRD as a string."""
    return fixture_path("sample_prd.md").read_text(encoding="utf-8")


def load_openapi() -> str:
    """Load the sample OpenAPI spec as a string."""
    return fixture_path("sample_openapi.yaml").read_text(encoding="utf-8")


def load_pact() -> dict:
    """Load the sample Pact contract as a dict."""
    return json.loads(
        fixture_path("sample_pact.json").read_text(encoding="utf-8")
    )


def load_docker_compose() -> str:
    """Load the sample Docker Compose file as a string."""
    return fixture_path("sample_docker_compose.yml").read_text(encoding="utf-8")
